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

import datetime as dt
import logging
from dataclasses import dataclass, field
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis import fx
from awltux.config import Settings, get_settings
from awltux.db import Instrument, PriceBar, Quote, utcnow
from awltux.providers.http import ProviderError
from awltux.providers.yahoo import BarSeries, YahooProvider

logger = logging.getLogger(__name__)

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
        }


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def store_bar_series(
    session: Session,
    instrument: Instrument,
    series: BarSeries,
    *,
    report: PriceIngestReport | None = None,
) -> int:
    """Upsert a bar series, respecting source rank. Returns rows written."""
    if not series.bars:
        return 0
    report = report or PriceIngestReport()

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
    for batch in _chunks(symbols, BATCH_SIZE):
        try:
            series_map = provider.get_history_batch(batch, period=period)
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


def latest_bar(session: Session, ticker: str) -> PriceBar | None:
    return session.execute(
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
    return (dt.date.today() - bar.date).total_seconds()
