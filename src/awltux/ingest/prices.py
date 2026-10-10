"""Price ingest: daily bars and point quotes.

Two rules the rest of the app relies on:

* **Provenance wins ties.** Each source carries a rank, and a stored bar is only
  replaced by a source of equal or higher rank. That way a Yahoo backfill does
  not overwrite a bar already archived from a better source, and re-running a
  backfill is idempotent.
* **Un-normalised money never reaches the database.** LSE symbols arrive in pence
  from Yahoo; the multiplier is applied on write and recorded alongside, so the
  100x question is always answerable from the row itself.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awltux.analysis import fx
from awltux.config import Settings, get_settings
from awltux.db import Instrument, PriceBar, Quote, utcnow
from awltux.db.session import release_write_lock
from awltux.ingest.blockers import clear_blocker, record_blocker
from awltux.money import multiplier_for
from awltux.providers.http import ProviderError
from awltux.providers.yahoo import BarSeries, YahooProvider
from awltux.scheduler import progress
from awltux.timezones import utc_today

logger = logging.getLogger(__name__)

#: This job's registry id, used to key the blockers it records. Named rather than
#: repeated, because a blocker keyed by a misspelt job id is a blocker the attention
#: check never reports.
JOB = "price_eod"

#: Tickers per batch download call. Large enough to be efficient, small enough
#: that one bad symbol does not lose the whole batch.
BATCH_SIZE = 40
#: Bars sampled when computing median daily turnover.
TURNOVER_WINDOW = 60


@dataclass(slots=True)
class PriceIngestReport:
    tickers_requested: int = 0
    tickers_returned: int = 0
    bars_written: int = 0
    bars_skipped_lower_rank: int = 0
    tickers_failed: list[str] = field(default_factory=list)
    #: Instruments whose bars were refused because the provider's unit contradicts the
    #: instrument's own. Kept apart from ``tickers_failed``: the provider answered, and the
    #: answer was in a unit we cannot reconcile with the one the broker prices in.
    tickers_unit_mismatch: list[str] = field(default_factory=list)
    turnover_updated: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tickers_requested": self.tickers_requested,
            "tickers_returned": self.tickers_returned,
            "bars_written": self.bars_written,
            "bars_skipped_lower_rank": self.bars_skipped_lower_rank,
            "turnover_updated": self.turnover_updated,
            "failed": self.tickers_failed[:25],
            "failed_count": len(self.tickers_failed),
            "unit_mismatch": self.tickers_unit_mismatch[:25],
            "unit_mismatch_count": len(self.tickers_unit_mismatch),
        }


def chunks(items: list[str], size: int) -> list[list[str]]:
    """Split a list into batches, so fetch and persist can alternate.

    Public because the scheduler job drives the batch loop itself: it fetches a
    batch with no transaction open, then opens one only to persist.
    """
    return [items[i : i + size] for i in range(0, len(items), size)]


@dataclass(slots=True)
class PriceTargets:
    """Which instruments to price, in the order they should be asked for."""

    #: Provider symbols, most deserving first.
    symbols: list[str] = field(default_factory=list)
    #: Symbol -> the unit the instrument is quoted in, from the broker's own instrument
    #: record. Carried with the symbols because a batched download cannot say what any one
    #: of them is quoted in, and guessing it from the ``.L`` suffix is what made an LSE ETF
    #: quoted in pounds 100x too cheap.
    currencies: dict[str, str] = field(default_factory=dict)
    #: Instruments with no stored bar at all -- the ones this job exists to fill.
    never_priced: int = 0
    #: Instruments whose newest bar predates the newest in the universe.
    stale: int = 0
    #: Oldest coverage date among the targets, for the run report.
    oldest_bar: str | None = None
    newest_bar: str | None = None

    def __len__(self) -> int:
        return len(self.symbols)


def load_price_targets(
    session: Session,
    *,
    limit: int | None = None,
    only: list[str] | None = None,
) -> PriceTargets:
    """The instruments to price, **most in need first**.

    A separate step from :func:`persist_batch` so the network phase can run with
    no transaction open.

    The order answers a question the old selection did not: which instruments
    actually need this run? It used to return every universe instrument in rowid
    order -- stable, arbitrary, and with no way to tell an instrument that has
    never been priced from one that was priced an hour ago.

    Priority, and it is deliberately this way round:

    1. **Never priced.** No bar at all: the instrument is invisible to every
       downstream model, so it is worth more than a refresh of anything else.
    2. **Oldest coverage.** Least recently priced first, so a run that cannot
       cover everything rotates through the universe instead of refreshing the
       same head of the list every day.
    3. Ticker, so the order is deterministic and a run can be reproduced.

    ``limit`` caps the run. The default prices everything, which is what a daily
    job on a 500-name universe can afford; the cap exists so a deployment on a
    tight rate limit can ration, and it is the priority order above that makes
    rationing fair rather than arbitrary.

    ``only`` names the instruments instead of ordering them. The priority above is a
    fairness rule for a sweep; a one-instrument refresh is not a sweep, and ordering by
    need would silently drop the instrument the reader asked about whenever it happened
    to be well covered. The symbol requirement still applies -- an instrument with no
    provider symbol has nothing to request.
    """
    coverage = (
        select(
            PriceBar.instrument_t212_ticker.label("ticker"),
            func.max(PriceBar.date).label("last_bar"),
        )
        .group_by(PriceBar.instrument_t212_ticker)
        .subquery()
    )

    statement = (
        select(Instrument, coverage.c.last_bar)
        .outerjoin(coverage, coverage.c.ticker == Instrument.t212_ticker)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.yahoo_symbol.is_not(None))
        .order_by(
            # `IS NULL` is 1/0 in SQLite and every other engine, so descending
            # puts the never-priced instruments first. Portable, unlike
            # NULLS FIRST, which SQLite only gained in 3.30.
            coverage.c.last_bar.is_(None).desc(),
            coverage.c.last_bar.asc(),
            Instrument.t212_ticker.asc(),
        )
    )
    if only is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(only)))
    else:
        # A sweep skips instruments a scoped refresh currently holds, so the two cannot
        # write the same bars at once. Not applied to `only`: that *is* the refresh.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    rows = session.execute(statement).all()

    targets = PriceTargets()
    dated: list[str] = []
    for instrument, last_bar in rows:
        if not instrument.yahoo_symbol:
            continue
        targets.symbols.append(instrument.yahoo_symbol)
        if instrument.currency_code:
            targets.currencies[instrument.yahoo_symbol] = instrument.currency_code
        if last_bar is None:
            targets.never_priced += 1
        else:
            dated.append(str(last_bar))

    if dated:
        targets.oldest_bar = min(dated)
        targets.newest_bar = max(dated)
        # "Stale" is relative: anything behind the newest coverage in the
        # universe. An absolute cutoff would call the whole universe stale on a
        # quiet day and nothing stale after a market holiday.
        targets.stale = sum(1 for value in dated if value < targets.newest_bar)

    if limit is not None and limit > 0:
        targets.symbols = targets.symbols[:limit]
        # Trimmed with the symbols, so the map cannot describe instruments this run will
        # not ask for -- the reader of a run report should not have to intersect the two.
        targets.currencies = {
            symbol: unit
            for symbol, unit in targets.currencies.items()
            if symbol in set(targets.symbols)
        }
    return targets


def persist_batch(
    session: Session,
    symbols: list[str],
    series_map: dict[str, BarSeries],
    *,
    report: PriceIngestReport | None = None,
) -> int:
    """Store one already-fetched batch. Returns rows written."""
    report = report or PriceIngestReport()
    written = 0
    for symbol in symbols:
        series = series_map.get(symbol)
        instrument = session.execute(
            select(Instrument).where(Instrument.yahoo_symbol == symbol).limit(1)
        ).scalar_one_or_none()
        if instrument is None:
            report.tickers_failed.append(symbol)
            continue
        if series is None or not series.bars:
            report.tickers_failed.append(symbol)
            # Recorded per instrument even though the call was per batch: "the provider
            # returned nothing for this symbol" is a fact about one company, and a
            # blocker on all forty when the *batch* call raised would report a rate limit
            # as forty broken instruments -- which is why the batch-level failure above
            # is not recorded here.
            record_blocker(
                session,
                instrument.t212_ticker,
                job=JOB,
                stage="prices",
                reason=f"the provider returned no bars for {symbol}",
            )
            continue
        report.tickers_returned += 1
        written += store_bar_series(session, instrument, series, report=report)
        # Commit per instrument. A batch of 40 is roughly 20,000 bars, and writing
        # that as one transaction holds SQLite's write lock long enough to time
        # out any other writer -- which is exactly what happened when a price run
        # overlapped the scheduler's own jobs. Per-instrument granularity keeps
        # each lock acquisition to about 500 rows, while the HTTP calls stay
        # batched, which is what the rate limits care about.
        release_write_lock(session)
    session.flush()
    return written


@dataclass(slots=True)
class QuoteIngestReport:
    """Outcome of a quote refresh."""

    tickers_requested: int = 0
    tickers_returned: int = 0
    tickers_failed: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tickers_requested": self.tickers_requested,
            "tickers_returned": self.tickers_returned,
            "failed_count": len(self.tickers_failed),
            "failed": self.tickers_failed[:25],
        }


def persist_quotes(
    session: Session,
    snapshots: list[tuple[str, Any]],
    *,
    report: QuoteIngestReport | None = None,
) -> int:
    """Store already-fetched quotes. Returns rows written."""
    report = report or QuoteIngestReport()
    now = utcnow()
    written = 0

    for ticker, snapshot in snapshots:
        instrument = session.get(Instrument, ticker)
        if instrument is None:
            continue
        session.add(
            Quote(
                instrument_t212_ticker=ticker,
                ts=now,
                price=snapshot.price,
                currency=snapshot.currency,
                raw_currency=snapshot.raw_currency,
                raw_multiplier=snapshot.raw_multiplier,
                source=snapshot.source,
                fetched_at=now,
            )
        )
        if snapshot.market_cap:
            instrument.market_cap = snapshot.market_cap
        report.tickers_returned += 1
        written += 1

    session.flush()
    return written


def store_bar_series(
    session: Session,
    instrument: Instrument,
    series: BarSeries,
    *,
    report: PriceIngestReport | None = None,
) -> int:
    """Upsert a bar series, respecting source rank. Returns rows written.

    **A series whose unit contradicts the instrument's own is refused, not stored.** The
    multiplier the provider applied has to be the one this instrument's currency code implies;
    when it is not, the price is wrong by whatever factor separates them -- usually 100 -- and
    it is still a plausible-looking number, which is exactly the failure this project's money
    handling exists to prevent. Measured 2026-10-09: an LSE ETF quoted in pounds was divided by
    100 on every refresh, so the page showed £1.41 for something the broker valued at £141.30.
    Storing nothing leaves the instrument visibly unpriced; storing the wrong unit leaves it
    confidently wrong, which is worse.
    """
    if not series.bars:
        return 0
    report = report or PriceIngestReport()

    expected = multiplier_for(instrument.currency_code) if instrument.currency_code else None
    if expected is not None and abs(series.raw_multiplier - expected) > 1e-9:
        report.tickers_unit_mismatch.append(instrument.t212_ticker)
        record_blocker(
            session,
            instrument.t212_ticker,
            job=JOB,
            stage="prices",
            reason=(
                f"{series.raw_currency or 'the provider unit'} against "
                f"{instrument.currency_code}: the bars came back at "
                f"{series.raw_multiplier:g} of a unit and this instrument is quoted at "
                f"{expected:g}, so every price would be out by "
                f"{expected / series.raw_multiplier:g}x"
            ),
        )
        return 0

    # One read of the existing window: the portable alternative to a
    # dialect-specific upsert, and cheap because a daily refresh touches
    # only a handful of new dates per instrument.
    existing = {
        bar_date: rank
        for bar_date, rank in session.execute(
            select(PriceBar.date, PriceBar.source_rank).where(
                PriceBar.instrument_t212_ticker == instrument.t212_ticker,
                PriceBar.date >= series.bars[0].date,
            )
        ).all()
    }

    written = 0
    for bar in series.bars:
        current_rank = existing.get(bar.date)
        if current_rank is not None and current_rank > series.source_rank:
            report.bars_skipped_lower_rank += 1
            continue

        row = session.get(PriceBar, (instrument.t212_ticker, bar.date))
        if row is None:
            row = PriceBar(
                instrument_t212_ticker=instrument.t212_ticker,
                date=bar.date,
                close=bar.close,
            )
            session.add(row)

        raw_close = bar.close / series.raw_multiplier if series.raw_multiplier else bar.close
        row.open = bar.open
        row.high = bar.high
        row.low = bar.low
        row.close = bar.close
        row.adj_close = bar.adj_close
        row.volume = bar.volume
        row.currency = series.currency or instrument.currency_code
        row.raw_currency = series.raw_currency
        row.raw_multiplier = series.raw_multiplier
        row.raw_close = raw_close
        row.source = series.source
        row.source_rank = series.source_rank
        row.fetched_at = utcnow()
        written += 1

    session.flush()
    report.bars_written += written
    # The one place that knows whether this instrument is storable, so the one place that
    # clears what a previous run recorded against it. Both callers get it for free.
    clear_blocker(session, instrument.t212_ticker, job=JOB, stage="prices")
    return written


def refresh_prices(
    session: Session,
    *,
    tickers: list[str] | None = None,
    period: str = "2y",
    settings: Settings | None = None,
    provider: YahooProvider | None = None,
    update_turnover: bool = True,
) -> PriceIngestReport:
    """Refresh daily bars for the universe (or an explicit ticker list)."""
    settings = settings or get_settings()
    provider = provider or YahooProvider(settings)
    report = PriceIngestReport()

    if tickers is None:
        rows = session.execute(
            select(Instrument)
            .where(Instrument.in_universe.is_(True))
            .where(Instrument.excluded.is_(False))
            .where(Instrument.yahoo_symbol.is_not(None))
        ).scalars().all()
    else:
        rows = session.execute(
            select(Instrument).where(Instrument.t212_ticker.in_(tickers))
        ).scalars().all()

    by_symbol: dict[str, Instrument] = {
        row.yahoo_symbol: row for row in rows if row.yahoo_symbol
    }
    report.tickers_requested = len(by_symbol)
    if not by_symbol:
        return report

    symbols = list(by_symbol)
    # **The unit each instrument is quoted in, told to the provider rather than guessed.**
    # Trading 212 publishes one per instrument (`currencyCode`) and we already hold it; a
    # batched download cannot say (its frame carries one currency for the whole request), so
    # the ".L means pence" convention used to stand in. That convention is right for nearly
    # every LSE line and wrong for the ones quoted in a major unit: measured 2026-10-09, it
    # divided an LSE ETF quoted in pounds by 100, so a £141.30 unit price was stored,
    # valued and charted as £1.41 while the broker's own position arithmetic used £141.30.
    currencies = {
        symbol: row.currency_code for symbol, row in by_symbol.items() if row.currency_code
    }
    batches = chunks(symbols, BATCH_SIZE)
    for position, batch in enumerate(batches, start=1):
        # Batches alternate network and database, so the count is the only visible
        # sign of progress on a run that prices the whole universe.
        progress.note(f"batch {position} of {len(batches)} ({len(batch)} symbols)")
        try:
            series_map = provider.get_history_batch(batch, period=period, currencies=currencies)
        except ProviderError as exc:
            logger.warning("price batch failed (%d symbols): %s", len(batch), exc)
            report.tickers_failed.extend(batch)
            continue

        for symbol in batch:
            series = series_map.get(symbol)
            if series is None or not series.bars:
                report.tickers_failed.append(symbol)
                continue
            instrument = by_symbol[symbol]
            report.tickers_returned += 1
            store_bar_series(session, instrument, series, report=report)

    if update_turnover:
        report.turnover_updated = update_turnover_estimates(session, list(by_symbol.values()))

    logger.info("price refresh: %s", report.as_dict())
    return report


def refresh_quotes(
    session: Session,
    *,
    tickers: list[str] | None = None,
    settings: Settings | None = None,
    provider: YahooProvider | None = None,
) -> PriceIngestReport:
    """Fetch point quotes and store them, for freshness and the live dashboard.

    Deliberately separate from the EOD path: quotes are cheap, frequent and
    perishable, while bars are the research record.
    """
    settings = settings or get_settings()
    provider = provider or YahooProvider(settings)
    report = PriceIngestReport()

    if tickers is None:
        rows = session.execute(
            select(Instrument)
            .where(Instrument.in_universe.is_(True))
            .where(Instrument.excluded.is_(False))
            .where(Instrument.yahoo_symbol.is_not(None))
        ).scalars().all()
    else:
        rows = session.execute(
            select(Instrument).where(Instrument.t212_ticker.in_(tickers))
        ).scalars().all()

    report.tickers_requested = len(rows)
    now = utcnow()

    for instrument in rows:
        if not instrument.yahoo_symbol:
            continue
        try:
            snapshot = provider.get_quote(instrument.yahoo_symbol)
        except ProviderError as exc:
            logger.debug("quote failed for %s: %s", instrument.yahoo_symbol, exc)
            report.tickers_failed.append(instrument.yahoo_symbol)
            continue

        session.add(
            Quote(
                instrument_t212_ticker=instrument.t212_ticker,
                ts=now,
                price=snapshot.price,
                currency=snapshot.currency,
                raw_currency=snapshot.raw_currency,
                raw_multiplier=snapshot.raw_multiplier,
                source=snapshot.source,
                fetched_at=now,
            )
        )
        if snapshot.market_cap:
            instrument.market_cap = snapshot.market_cap
        report.tickers_returned += 1

    session.flush()
    logger.info("quote refresh: %d/%d", report.tickers_returned, report.tickers_requested)
    return report


def update_turnover_estimates(
    session: Session, instruments: list[Instrument] | None = None
) -> int:
    """Recompute median daily turnover in GBP for liquidity gating.

    Turnover is ``close x volume`` in the instrument's trading currency converted
    to GBP. If no FX rate is available the value is left unset rather than
    assumed, and the risk gate treats an unknown turnover as unfavourable.
    """
    if instruments is None:
        instruments = session.execute(
            select(Instrument).where(Instrument.in_universe.is_(True))
        ).scalars().all()

    updated = 0
    for instrument in instruments:
        bars = session.execute(
            select(PriceBar)
            .where(PriceBar.instrument_t212_ticker == instrument.t212_ticker)
            .order_by(PriceBar.date.desc())
            .limit(TURNOVER_WINDOW)
        ).scalars().all()

        samples: list[float] = []
        for bar in bars:
            if not bar.volume or not bar.close:
                continue
            notional = bar.close * bar.volume
            currency = bar.currency or instrument.currency_code or "GBP"
            gbp = fx.to_gbp(notional, currency)
            if gbp is not None:
                samples.append(gbp)

        if len(samples) < 10:
            # Too few observations to call it a median; leave it unknown so the
            # gate can refuse rather than pass on thin evidence.
            continue

        instrument.median_daily_turnover_gbp = float(median(samples))
        updated += 1

    session.flush()
    return updated


def repair_price_units(session: Session, *, dry_run: bool = False) -> dict[str, Any]:
    """Rewrite stored bars whose multiplier contradicts the instrument's own currency.

    **A refresh does not necessarily reach every row, which is why this exists.** The write
    path refuses a wrong-unit series now, but a row already stored keeps its wrong unit until
    something overwrites it -- and the row the page reads is the *newest* one. Measured
    2026-10-10: after the unit fix, 504 of `VWRLl_EQ`'s 507 bars were re-written correctly and
    the newest was not, because the provider's live row for that date carries a `NaN` close and
    every row without a close is skipped. So the page still showed £1.41 from a bar nothing
    could overwrite.

    **The figures are exact to restore, not re-estimated.** `raw_close` is the provider's own
    number and the multiplier to apply is the one the instrument's currency code implies; open,
    high, low and adj_close were all scaled by the same wrong factor as the close, so dividing
    them by it recovers them. Nothing is fetched, so this is safe to run on a live database and
    says what it would do with ``dry_run``.
    """
    instruments = {
        instrument.t212_ticker: instrument
        for instrument in session.execute(select(Instrument)).scalars()
    }
    changed: list[dict[str, Any]] = []
    skipped: list[str] = []
    for bar in session.execute(select(PriceBar)).scalars():
        instrument = instruments.get(bar.instrument_t212_ticker)
        if instrument is None or not instrument.currency_code:
            continue
        expected = multiplier_for(instrument.currency_code)
        stored = bar.raw_multiplier or 0.0
        if stored <= 0 or abs(stored - expected) <= 1e-9:
            continue
        raw_close = bar.raw_close if bar.raw_close is not None else bar.close
        if raw_close is None:
            skipped.append(bar.instrument_t212_ticker)
            continue
        ratio = expected / stored
        entry = {
            "ticker": bar.instrument_t212_ticker,
            "date": bar.date.isoformat(),
            "currency": instrument.currency_code,
            "was_multiplier": stored,
            "now_multiplier": expected,
            "was": bar.close,
            "now": raw_close * expected,
        }
        changed.append(entry)
        if dry_run:
            continue
        bar.open = _scaled_by(bar.open, ratio)
        bar.high = _scaled_by(bar.high, ratio)
        bar.low = _scaled_by(bar.low, ratio)
        bar.adj_close = _scaled_by(bar.adj_close, ratio)
        bar.close = raw_close * expected
        # The provider's own number, left exactly as it came: it is what the multiplier is
        # recorded to undo.
        bar.raw_close = raw_close
        bar.raw_multiplier = expected
        # The unit the figure is quoted in. It was *our* guess that was wrong, so what is
        # recorded afterwards is the instrument's own -- not the label the guess produced.
        bar.raw_currency = instrument.currency_code
        bar.currency = _major_currency(instrument.currency_code)
    if not dry_run:
        session.flush()
    return {
        "changed": changed,
        "changed_count": len(changed),
        "unreadable": len(skipped),
        "tickers": sorted({entry["ticker"] for entry in changed}),
    }


def _scaled_by(value: float | None, ratio: float) -> float | None:
    return None if value is None else value * ratio


def _major_currency(currency_code: str) -> str:
    from awltux.money import to_major_currency

    return to_major_currency(1.0, currency_code)[1]


def latest_bar(session: Session, ticker: str) -> PriceBar | None:    return session.execute(
        select(PriceBar)
        .where(PriceBar.instrument_t212_ticker == ticker)
        .order_by(PriceBar.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def bars_for(
    session: Session, ticker: str, *, limit: int = 500, ascending: bool = True
) -> list[PriceBar]:
    """Return stored bars, defaulting to chronological order for indicators."""
    statement = select(PriceBar).where(PriceBar.instrument_t212_ticker == ticker)
    statement = (
        statement.order_by(PriceBar.date.asc() if ascending else PriceBar.date.desc())
        .limit(limit)
    )
    rows = list(session.execute(statement).scalars().all())
    return rows if ascending else list(reversed(rows))


def bar_currency(session: Session, ticker: str) -> str | None:
    bar = latest_bar(session, ticker)
    return bar.currency if bar else None


def freshness_seconds(session: Session, ticker: str) -> float | None:
    """Age of the most recent bar, used by the decision gate's staleness check."""
    bar = latest_bar(session, ticker)
    if bar is None:
        return None
    return (utc_today() - bar.date).total_seconds()
