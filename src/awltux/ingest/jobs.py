"""Scheduled job entry points.

Each function opens its own session and returns a
:class:`~awltux.scheduler.jobs.JobResult`. They are intentionally thin: all the
work lives in the ingest modules, which are directly testable without the
scheduler.

A job is allowed to fail. The scheduler records the failure and moves on, because
one unreachable free-tier provider must not stop the prices, the filings and the
decisions from being refreshed.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from awltux.db import Instrument

from awltux.config import get_settings
from awltux.db import session_scope
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobResult

logger = logging.getLogger(__name__)

#: Rows the relevance backfill will load in one run. Only bounds memory: the work
#: that costs money is capped separately, by ``news.relevance_backfill_per_run``.
RELEVANCE_BACKFILL_ROWS = 5_000

#: Rows written before the backfill releases SQLite's write lock. See
#: ``INSTRUMENT_FLUSH_EVERY`` in ``ingest/universe.py`` for why an unbounded bulk
#: write is not acceptable here.
RELEVANCE_FLUSH_EVERY = 250


def universe_is_empty(session) -> bool:
    """Whether anything is actually in scope for the universe-driven jobs.

    Several jobs read ``in_universe`` instruments and legitimately do nothing when
    there are none -- but they reported that as a bare ``0``, which looks
    identical to a job that ran and found no news. Naming the cause is the
    difference between "nothing happened" and "nothing could happen".
    """
    from sqlalchemy import func, select

    from awltux.db import Instrument

    count = session.execute(
        select(func.count())
        .select_from(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
    ).scalar_one()
    return int(count or 0) == 0


def empty_universe_note(session) -> str | None:
    """Explain a zero-result run, or return ``None`` if the universe is populated."""
    if not universe_is_empty(session):
        return None

    from sqlalchemy import func, select

    from awltux.db import Instrument

    total = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    if int(total or 0) == 0:
        return (
            "nothing to do: no instruments are stored yet. Run the "
            "'t212_instruments' job first (it needs a working Trading 212 API key)."
        )
    return (
        f"nothing to do: {total} instruments are stored but none are in the "
        "analysed universe. Run the 'universe_refresh' job, or check that the "
        "instrument window includes the exchanges you want."
    )


def sync_instruments() -> JobResult:
    """Pull the Trading 212 instrument universe and resolve provider symbols.

    **Fetch first, then persist.** Trading 212's limits are strict enough that a
    call can sleep for a minute inside the rate-limit guard, and holding a
    transaction across that wait takes SQLite's write lock for the whole time --
    which is what produced "database is locked" for every other writer, and for
    readers once ``BEGIN IMMEDIATE`` was in play.
    """
    from awltux.ingest.universe import (
        synchronize_instruments,
    )
    from awltux.providers.t212 import T212Provider

    provider = T212Provider()

    # --- network phase: no transaction open ---------------------------------
    exchanges = provider.get_exchanges()
    instruments = provider.get_instruments()

    try:
        positions = provider.get_positions()
        holds_readable = True
    except Exception as exc:
        # A metadata-only key cannot read positions. That is a supported
        # configuration, so it is recorded rather than treated as a failure.
        logger.info("positions are not readable with this key: %s", exc)
        positions = []
        holds_readable = False

    # --- database phase: short, and with nothing left to wait for -----------
    with session_scope() as session:
        report = synchronize_instruments(
            session, provider=provider, exchanges=exchanges, instruments=instruments
        )
        held = _apply_positions(session, positions) if holds_readable else 0
        capabilities = _record_capabilities(session, holds_readable, bool(exchanges))

    return JobResult(
        items_seen=report.instruments_seen,
        items_written=report.instruments_created + report.instruments_updated,
        detail={**report.as_dict(), "held": held, "capabilities": capabilities},
    )


#: Every position column, so they are set and cleared as one group and a row is never
#: left half-populated -- a quantity with no cost basis would read as a free holding.
_POSITION_FIELDS = (
    "position_opened_at",
    "position_quantity",
    "position_average_price",
    "position_in_pies",
    "position_cost_gbp",
    "position_value_gbp",
    "position_unrealised_gbp",
    "position_currency",
    "position_synced_at",
)


@dataclass(frozen=True, slots=True)
class _Position:
    """One position, parsed out of the broker's payload.

    Parsed once so the write below is about the database rather than about JSON shapes: the
    ticker is nested under ``instrument``, the money under ``walletImpact``, and every field
    is optional as far as this code is concerned.
    """

    ticker: str
    opened_at: dt.datetime | None
    quantity: float | None
    average_price: float | None
    in_pies: float | None
    cost: float | None
    value: float | None
    unrealised: float | None
    currency: str | None


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None  # NaN


def _as_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_position(payload: dict[str, Any]) -> _Position | None:
    """One position from the broker's JSON, or ``None`` if it names no instrument.

    A position with no ticker cannot be mapped to anything, so it is skipped rather than
    guessed at.
    """
    instrument = payload.get("instrument") or {}
    ticker = instrument.get("ticker") or payload.get("ticker")
    if not ticker:
        return None
    impact = payload.get("walletImpact") or {}
    currency = impact.get("currency")
    return _Position(
        ticker=str(ticker),
        opened_at=_as_datetime(payload.get("createdAt")),
        quantity=_as_float(payload.get("quantity")),
        average_price=_as_float(payload.get("averagePricePaid")),
        in_pies=_as_float(payload.get("quantityInPies")),
        cost=_as_float(impact.get("totalCost")),
        value=_as_float(impact.get("currentValue")),
        unrealised=_as_float(impact.get("unrealizedProfitLoss")),
        currency=str(currency) if currency else None,
    )


def _clear_position(row) -> None:
    for field in _POSITION_FIELDS:
        setattr(row, field, None)


def _apply_positions(session, positions: list[dict[str, Any]]) -> int:
    """Write what the broker says about each holding, and clear the ones it no longer has.

    **The clearing is the contract, not housekeeping.** `is_held` alone cannot carry it: the
    instrument page reads the figures, so a position that closes must stop being shown.
    Setting and clearing move together, which also makes `position_synced_at IS NOT NULL`
    mean exactly "this row currently holds a position".

    Kept as the broker reports it rather than recomputed from our own prices. The cost
    includes the FX leg and the conversion fee, which the app's price series cannot
    reproduce.
    """
    from sqlalchemy import select

    from awltux.db import Instrument, utcnow

    parsed = [item for item in (_parse_position(p) for p in positions) if item is not None]
    by_ticker = {item.ticker: item for item in parsed}
    now = utcnow()

    applied = 0
    for row in session.execute(select(Instrument)).scalars().all():
        position = by_ticker.get(row.t212_ticker)
        row.is_held = position is not None
        if position is None:
            _clear_position(row)
            continue
        row.position_opened_at = position.opened_at
        row.position_quantity = position.quantity
        row.position_average_price = position.average_price
        row.position_in_pies = position.in_pies
        row.position_cost_gbp = position.cost
        row.position_value_gbp = position.value
        row.position_unrealised_gbp = position.unrealised
        row.position_currency = position.currency
        row.position_synced_at = now
        applied += 1

    session.flush()
    return applied


#: How many orders one run will read. The API's page size is 50 and the paginator caps at
#: 40 pages, so this is a ceiling of 2,000 raw items either way.
#:
#: **Above the whole history, deliberately.** Measured 2026-10-08: the account's entire
#: order history is 263 distinct orders (367 items, 28% of them cursor repeats) over eight
#: requests, from 2024-03-18. At the 200 this used to be, the first run read only the newest
#: 148 and -- because the next run starts from the newest id it holds -- **the older ones
#: were never read at all**. Trading is a handful of orders a day, so one complete backfill
#: on the first run is cheaper than any scheme for resuming a partial one; see `TODO.md` for
#: what happens on an account whose history genuinely exceeds this.
ORDERS_PER_RUN = 1_000


def _pending_order(session, order_id: int):
    """The row this session has already added for ``order_id``, if it has one.

    The lookup in `_store_order` cannot see it. Sessions here run with
    ``autoflush=False`` (`db/session.py`), so a ``SELECT`` goes to the database and a row
    added a moment ago is invisible; the second ``add`` then makes two pending ``INSERT``s
    of the same ``order_id`` and the flush raises
    ``UNIQUE constraint failed: t212_order.order_id``. Since the whole batch shares one
    transaction, that single repeat discards every order read in the run -- measured
    2026-10-08, when the cursor returned 200 items with only 148 distinct ids.
    """
    from awltux.db import T212Order

    for obj in session.new:
        if isinstance(obj, T212Order) and obj.order_id == order_id:
            return obj
    return None


def _store_order(session, item: dict[str, Any]) -> bool:
    """Upsert one historical order from the broker's payload. True when it was new.

    Upsert rather than insert because history is re-read from the newest page backwards and
    a page can be re-read after a failed run; `order_id` is the idempotency key.
    """
    from sqlalchemy import select

    from awltux.db import T212Order

    order = item.get("order") or {}
    fill = item.get("fill") or {}
    order_id = order.get("id")
    if not isinstance(order_id, int):
        return False

    row = _pending_order(session, order_id)
    if row is None:
        row = session.execute(
            select(T212Order).where(T212Order.order_id == order_id)
        ).scalar_one_or_none()
    created = row is None
    if row is None:
        row = T212Order(order_id=order_id)
        session.add(row)

    instrument = order.get("instrument") or {}
    ticker = instrument.get("ticker") or order.get("ticker")
    impact = fill.get("walletImpact") or {}
    currency = impact.get("currency") or order.get("currency")

    # A ticker that matches no instrument is still stored, unlinked: the account can hold
    # something outside the stored universe and dropping the row would lose a real trade.
    row.instrument_t212_ticker = str(ticker) if ticker else None
    row.side = order.get("side")
    row.status = order.get("status")
    row.order_type = order.get("type")
    row.strategy = order.get("strategy")
    row.created_at = _as_datetime(order.get("createdAt"))
    row.filled_at = _as_datetime(fill.get("filledAt"))
    row.filled_quantity = _as_float(fill.get("quantity"))
    row.fill_price = _as_float(fill.get("price"))
    row.fill_type = fill.get("type")
    row.net_value = _as_float(impact.get("netValue"))
    row.currency = str(currency) if currency else None
    return created


def sync_orders() -> JobResult:
    """Store Trading 212's order history: the buy and sell dates the pages were missing.

    **Incremental.** The newest `order_id` already stored is the cursor and the walk stops
    there, so an hourly run reads only what is new. That cursor is also why the first run
    must read the whole history: it can only ever walk *newer* than what it holds, so
    anything older than the first run's window is out of reach for good. `ORDERS_PER_RUN`
    is set above the measured size of the account's history for exactly that reason, and a
    run that does hit the ceiling says so in its note rather than claiming the rest will
    follow.

    **A key without `history:orders` is a supported configuration**, not a fault: the same
    way a metadata-only key cannot read positions. It is reported as a note, which the
    operations page shows.
    """
    from sqlalchemy import func, select

    from awltux.db import T212Order
    from awltux.providers.t212 import ScopeUnavailable, T212Provider

    settings = get_settings()
    provider = T212Provider(settings)
    if not provider.configured:
        return JobResult(note="Trading 212 is not configured")

    with session_scope() as session:
        newest = session.execute(select(func.max(T212Order.order_id))).scalar()

    try:
        with provider:
            orders = provider.get_order_history(
                limit=ORDERS_PER_RUN, since_order_id=newest
            )
    except ScopeUnavailable as exc:
        return JobResult(note=f"order history is not readable with this key: {exc}")
    except Exception as exc:
        # One unreadable endpoint is not a reason to fail the schedule.
        logger.warning("could not read the trading history: %s", exc)
        return JobResult(note=f"could not read the trading history: {exc}")

    written = 0
    with session_scope() as session:
        for item in orders:
            if _store_order(session, item):
                written += 1
        session.flush()

    return JobResult(
        items_seen=len(orders),
        items_written=written,
        note=(
            f"read the newest {ORDERS_PER_RUN} orders and stopped there; the incremental "
            "cursor cannot reach the older ones, so a bigger ORDERS_PER_RUN is needed"
            if len(orders) >= ORDERS_PER_RUN
            else None
        ),
        detail={"since_order_id": newest, "read": len(orders), "new": written},
    )


#: How long one run of the held-name sweep may take, in seconds.
#:
#: Each instrument's own refresh is bounded separately (``refresh.TOTAL_BUDGET_SECONDS``,
#: 900); this bounds the *set*. Measured 2026-10-08: one instrument's refresh takes about
#: 100 seconds, so the cap is only reachable with a large number of holdings -- and it exists
#: for the case where a wedged provider makes each instrument burn its whole budget. Without
#: it, an hourly job could spend the hour and hold up every other job behind the single
#: worker, which is exactly what the interval is supposed to prevent.
HELD_REFRESH_BUDGET_SECONDS = 2_700


def refresh_held(tickers: list[str] | None = None) -> JobResult:
    """Run the full refresh for every instrument the account holds, one after another.

    The instrument page's Refresh button does this for one company on its own thread. This is
    the scheduled version of the same sequence for the positions actually at risk, so a
    holding's filings, news, valuation and decision stay current without anyone pressing
    anything.

    **Sequential, and through the same lease.** Each holding is refreshed under its own
    instrument lease, which is what stops a scheduled run and a button press writing one
    company at once -- a name another refresh already holds is *skipped and named*, not
    waited for, because a refresh that has been running for ten minutes is not a lock worth
    blocking an hourly job behind. The scheduler's single worker means one job at a time
    anyway; going one instrument at a time also keeps each step's provider and model calls
    inside the per-instrument budget.

    **Cooperative stop between instruments.** `progress.checkpoint` leaves at an item
    boundary, where the previous instrument is committed and its lease released, so
    `awltux quiet` before a deploy does not leave a half-refreshed company behind.
    """
    from awltux.db import utcnow
    from awltux.ingest import refresh
    from awltux.ingest.lease import acquire, expire_stale

    with session_scope() as session:
        held = _held_instruments(session)
        outside = _held_outside_the_universe(session)

    if tickers is not None:
        scope = set(tickers)
        held = [row for row in held if row.t212_ticker in scope]

    if not held:
        return JobResult(
            note=(
                f"nothing to refresh: {outside} held instrument(s) are outside the analysed "
                "universe"
                if outside
                else "nothing held, or positions have not been read yet"
            ),
            detail={"held": 0, "outside_universe": outside},
        )

    started = utcnow()
    refreshed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    partial: list[str] = []
    failed_steps: list[str] = []
    truncated: str | None = None

    for position, row in enumerate(held, start=1):
        progress.checkpoint(f"{position} of {len(held)}: {row.t212_ticker}")

        if (utcnow() - started).total_seconds() > HELD_REFRESH_BUDGET_SECONDS:
            truncated = (
                f"stopped after {position - 1} of {len(held)}: the run's budget of "
                f"{HELD_REFRESH_BUDGET_SECONDS}s was spent"
            )
            progress.note(truncated)
            break

        with session_scope() as session:
            expire_stale(session)
            lease_row = acquire(session, row.t212_ticker, note="scheduled held refresh")
            token = lease_row.token if lease_row is not None else None

        if token is None:
            skipped.append(row.t212_ticker)
            progress.note(f"{row.t212_ticker} is already being refreshed; skipping it")
            continue

        outcome = refresh.run_under_lease(row.t212_ticker, token)

        # A step that fails does not fail the refresh -- `refresh.run` records it and carries
        # on, and the instrument's own page shows which step it was. Counted here so a run
        # whose steps all failed does not read as a clean one, without pretending the
        # *instrument* was not refreshed.
        for step_result in outcome.get("results") or []:
            if not step_result.get("ok"):
                failed_steps.append(f"{row.t212_ticker}/{step_result.get('step')}")

        if isinstance(outcome.get("failed"), str):
            failed.append(f"{row.t212_ticker}: {outcome['failed']}")
        elif outcome.get("stopped"):
            # The sequence gave up: it lost the lease to somebody else, or spent its own
            # per-instrument budget. Not a failure of this job, and not a refreshed
            # instrument either.
            partial.append(f"{row.t212_ticker}: {outcome['stopped']}")
        else:
            refreshed.append(row.t212_ticker)

    return JobResult(
        items_seen=len(held),
        items_written=len(refreshed),
        note=truncated,
        detail={
            "held": len(held),
            "refreshed": refreshed,
            "skipped": skipped,
            "failed": failed,
            "partial": partial,
            "failed_steps": failed_steps,
            "outside_universe": outside,
        },
    )


def _held_instruments(session) -> list[Instrument]:
    """What the account holds, in ticker order, for the refresh to walk.

    ``in_universe`` because that is what every scoped step filters on and what the Refresh
    button itself requires (`refresh.instrument_or_none`): a holding outside it has no
    analysed data to refresh. How many are outside is reported separately rather than
    dropped silently -- it means the pipeline is not looking at something the account owns.
    """
    from sqlalchemy import select

    from awltux.db import Instrument

    return list(
        session.execute(
            select(Instrument)
            .where(Instrument.is_held.is_(True))
            .where(Instrument.in_universe.is_(True))
            .where(Instrument.excluded.is_(False))
            .order_by(Instrument.t212_ticker)
        )
        .scalars()
        .all()
    )


def _held_outside_the_universe(session) -> int:
    """Held instruments the pipeline does not analyse, counted so the run can say so."""
    from sqlalchemy import func, select

    from awltux.db import Instrument

    return int(
        session.execute(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.is_held.is_(True))
            .where((Instrument.in_universe.is_(False)) | (Instrument.excluded.is_(True)))
        ).scalar_one()
        or 0
    )


def _record_capabilities(session, holds_readable: bool, metadata_ok: bool) -> dict[str, Any]:
    """Cache what this key can do, so the UI can explain a reduced feature set."""
    from awltux.db import AppSetting, utcnow
    from awltux.ingest.universe import CAPABILITIES_KEY

    capabilities: dict[str, Any] = {
        "metadata": metadata_ok,
        "portfolio": holds_readable,
        "checked_at": utcnow().isoformat(),
        "errors": {}
        if holds_readable
        else {"portfolio": "the key lacks the 'portfolio' scope, or the read failed"},
    }
    row = session.get(AppSetting, CAPABILITIES_KEY)
    if row is None:
        session.add(
            AppSetting(
                key=CAPABILITIES_KEY,
                value=capabilities,
                note="Cached Trading 212 key capabilities",
            )
        )
    else:
        row.value = capabilities
    session.flush()
    return capabilities


def refresh_universe() -> JobResult:
    """Re-select which instruments are actively analysed.

    The ``note`` matters more here than in most jobs. This runs on startup
    alongside ``t212_instruments``, and on a fresh database it can read the
    instrument table before that job has committed -- producing a run that selected
    nothing and looks identical to a legitimate "no instrument qualified". That
    happened: the container's own run history shows the two jobs starting 2ms
    apart, the refresh seeing 0 instruments, and the next run selecting 500.
    """
    from awltux.ingest.universe import refresh_universe as _refresh

    with session_scope() as session:
        stats = _refresh(session)

    stored = stats.get("instruments_stored", 0)
    eligible = stats.get("eligible", 0)
    selected = stats.get("selected", 0)

    note: str | None = None
    if selected == 0:
        if stored == 0:
            note = (
                "no instruments are stored yet, so there was nothing to select from. "
                "This is expected on a fresh database while t212_instruments is still "
                "running; re-run once it has finished."
            )
        elif eligible == 0:
            filters = stats.get("filtered_out") or {}
            reasons = ", ".join(f"{count} by {name}" for name, count in filters.items() if count)
            note = (
                f"{stored} instruments stored but none eligible"
                + (f" ({reasons})" if reasons else "")
                + ". Check universe.instrument_types and universe.exchanges."
            )

    return JobResult(
        items_seen=eligible,
        items_written=selected,
        note=note,
        detail=stats,
    )


#: How many trading days a sector's index covers. The same 400 the instrument page charts,
#: so the two lines a reader compares are the same length.
SECTOR_INDEX_DAYS = 400


def rebuild_sector_index(tickers: list[str] | None = None) -> JobResult:
    """Rebuild every sector's equal-weighted price index from its constituents' bars.

    A sector page lists its instruments and each instrument's page draws its own price line,
    so the sector itself had no price view. This is the aggregation behind one line: each
    constituent rebased to 100 at its first bar in the window, the level the mean of those
    ratios -- see `analysis.sectors.index_from_closes` for why rebasing rather than averaging
    raw closes, and why that makes mixed currencies a non-issue.

    **Whole series per sector, replaced not extended.** The base is the oldest date in the
    window, so a row from an earlier run is on a different basis and the two cannot be one
    line. Every run deletes the sector's rows and writes the new set, which also keeps the
    table bounded: 400 rows × twelve sectors.

    **After the prices, because the bars are its input.** `depends_on=("price_eod",)`, and it
    is cheap enough not to care: measured 2026-10-08 on the live database, the whole sweep --
    5 sectors' worth of queries at 20,000-60,000 bars each -- is about two seconds, against
    135-445 ms *per sector page view* for deriving it there.

    ``tickers`` is accepted for the scoped-refresh convention and **deliberately ignored**: an
    index of one instrument is that instrument's own line, which its page already draws. A
    refresh of one company must not rewrite the sector's series from a single constituent.
    """
    from awltux.analysis import sectors as sector_map

    del tickers  # see the docstring: an index needs the whole sector, not a scope

    with session_scope() as session:
        members = _sector_constituents(session)

    written = 0
    skipped: list[str] = []
    sectors: dict[str, Any] = {}

    for group in (*sector_map.SECTOR_NAMES, None):
        sector = group if group is not None else sector_map.UNCLASSIFIED
        names = members.get(group) or []
        progress.checkpoint(f"{sector}: {len(names)} instruments")
        if not names:
            skipped.append(sector)
            sectors[sector] = {"instruments": 0, "points": 0}
            continue

        with session_scope() as session:
            series = _sector_series(session, names)
            if not series:
                skipped.append(sector)
                sectors[sector] = {"instruments": len(names), "points": 0}
                continue
            _replace_sector_series(session, sector, series)
            written += len(series)
            sectors[sector] = {
                "instruments": len(names),
                "points": len(series),
                "base_date": series[0][0].isoformat(),
                "first": round(series[0][1], 2),
                "last": round(series[-1][1], 2),
                "contributors": series[-1][2],
            }

    return JobResult(
        items_seen=len(members),
        items_written=written,
        note=(
            "no sector has both constituents and stored prices yet" if not written else None
        ),
        detail={"days": SECTOR_INDEX_DAYS, "sectors": sectors, "skipped": skipped},
    )


def _sector_constituents(session) -> dict[str | None, list[str]]:
    """Every in-universe instrument's ticker, grouped by its sector, ticker order.

    One read for the whole run: the job needs each sector's membership, and asking per sector
    would be twelve queries for one table.
    """
    from sqlalchemy import select

    from awltux.db import Instrument

    members: dict[str | None, list[str]] = {}
    rows = session.execute(
        select(Instrument.sector_group, Instrument.t212_ticker)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .order_by(Instrument.t212_ticker)
    ).all()
    for group, ticker in rows:
        members.setdefault(group, []).append(ticker)
    return members


def _sector_series(session, names: list[str]) -> list[tuple[dt.date, float, int]]:
    """One sector's index points, from the bars of the instruments in ``names``.

    The window is the newest ``SECTOR_INDEX_DAYS`` distinct dates the sector trades on, taken
    across its constituents: bounding by rows *per instrument* would give a thinly traded
    constituent a longer history than a busy one, and the two lines would then cover different
    spans.
    """
    from sqlalchemy import desc, select

    from awltux.analysis import sectors as sector_map
    from awltux.db import PriceBar

    cutoff = session.execute(
        select(PriceBar.date)
        .where(PriceBar.instrument_t212_ticker.in_(names))
        .group_by(PriceBar.date)
        .order_by(desc(PriceBar.date))
        .offset(SECTOR_INDEX_DAYS - 1)
        .limit(1)
    ).scalar()

    # Fewer distinct dates than the window -- a young database, or a sector whose constituents
    # are newly listed -- so there is no cutoff and the whole stored history is the window.
    # `None` here would otherwise become `date >= NULL`, which matches nothing and would
    # silently index nothing at all.
    bars = select(PriceBar.instrument_t212_ticker, PriceBar.date, PriceBar.close).where(
        PriceBar.instrument_t212_ticker.in_(names)
    )
    if cutoff is not None:
        bars = bars.where(PriceBar.date >= cutoff)
    return sector_map.index_from_closes(session.execute(bars.order_by(PriceBar.date)).all())


def _replace_sector_series(session, sector: str, series: list[tuple[dt.date, float, int]]) -> None:
    """Replace one sector's stored line, whole.

    Whole, because the level is rebased to the oldest date in the window: rows from an earlier
    run are on a different basis, so mixing them would draw a jump that never happened.
    """
    from sqlalchemy import delete

    from awltux.db import SectorPriceIndex, utcnow

    base_date = series[0][0]
    now = utcnow()
    session.execute(delete(SectorPriceIndex).where(SectorPriceIndex.sector == sector))
    session.add_all(
        [
            SectorPriceIndex(
                sector=sector,
                date=date,
                level=level,
                contributors=contributors,
                base_date=base_date,
                computed_at=now,
            )
            for date, level, contributors in series
        ]
    )
    # Flushed per sector, not once at the end: a series is replaced as one unit, so a run that
    # stops at the next sector's checkpoint has either written this one whole or not at all.
    session.flush()


def refresh_prices_eod(tickers: list[str] | None = None) -> JobResult:
    """End-of-day OHLCV for the universe, plus FX for the majors.

    Alternates network and database phases per batch rather than wrapping the
    whole run in one transaction. A single transaction spanning every batch would
    hold SQLite's write lock across hundreds of provider calls, locking out the
    dashboard for the duration.

    Instruments are asked for **most in need first** -- never priced, then least
    recently covered -- so a run that cannot reach everything still makes progress
    on the gaps rather than refreshing whichever names happened to sort first.
    """
    from awltux.analysis import fx
    from awltux.ingest.prices import (
        PriceIngestReport,
        chunks,
        load_price_targets,
        persist_batch,
        update_turnover_estimates,
    )
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    provider = YahooProvider(settings)
    report = PriceIngestReport()

    # --- database phase: which instruments, in what order --------------------
    with session_scope() as session:
        if tickers:
            # Scoped: the named instruments and nothing else, whatever the ration and
            # whatever their coverage. The targeted ordering below exists to spread a
            # universe sweep across runs, and a single named instrument has no queue to
            # be fair to.
            targets = load_price_targets(session, only=tickers)
        else:
            targets = load_price_targets(
                session, limit=settings.schedule.price_eod_max_per_run or None
            )
    report.tickers_requested = len(targets)
    if not targets.symbols:
        return JobResult(detail={**report.as_dict(), "skipped": "empty universe"})

    symbols = targets.symbols
    for batch in chunks(symbols, 40):
        # --- network phase: no transaction open -----------------------------
        try:
            # The unit each symbol is quoted in travels with the targets: the broker's own
            # instrument record, so the provider is told rather than left to guess from the
            # symbol. It cannot guess correctly for a batch -- the response is one frame with
            # one currency for the whole request -- and the ".L means pence" convention it
            # fell back on is what stored an LSE ETF quoted in pounds at 100x too little.
            series_map = provider.get_history_batch(
                batch, period="2y", currencies=targets.currencies
            )
        except Exception as exc:
            logger.warning("price batch failed (%d symbols): %s", len(batch), exc)
            report.tickers_failed.extend(batch)
            continue

        # --- database phase: short ------------------------------------------
        with session_scope() as session:
            persist_batch(session, batch, series_map, report=report)

    # --- turnover and FX, each in their own short phase ---------------------
    with session_scope() as session:
        report.turnover_updated = update_turnover_estimates(session)

    rates = fx.refresh_common_rates()

    return JobResult(
        items_seen=report.tickers_requested,
        items_written=report.bars_written,
        detail={
            **report.as_dict(),
            "fx": rates,
            # What the run was aiming at, so the page can say whether it is
            # closing the gaps or just keeping the covered names fresh.
            "never_priced_targeted": targets.never_priced,
            "stale_targeted": targets.stale,
            "oldest_coverage": targets.oldest_bar,
            "newest_coverage": targets.newest_bar,
        },
    )


def refresh_prices_intraday() -> JobResult:
    """Quotes for held and pinned names while their markets are open."""
    from sqlalchemy import select

    from awltux.db import Instrument
    from awltux.ingest.prices import QuoteIngestReport, persist_quotes
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    provider = YahooProvider(settings)

    with session_scope() as session:
        # Intraday polling is rationed: held and pinned names only. Refreshing
        # quotes for 500 names every 15 minutes would exhaust the free tier.
        rows = session.execute(
            select(Instrument).where(
                Instrument.is_held.is_(True) | Instrument.pinned.is_(True)
            )
        ).scalars().all()
        targets = [
            (row.t212_ticker, row.yahoo_symbol)
            for row in rows
            if row.yahoo_symbol
        ]

    if not targets:
        return JobResult(detail={"skipped": "no held or pinned instruments"})

    report = QuoteIngestReport(tickers_requested=len(targets))
    # --- network phase ------------------------------------------------------
    snapshots: list[tuple[str, object]] = []
    for ticker, symbol in targets:
        try:
            snapshots.append((ticker, provider.get_quote(symbol)))
        except Exception as exc:
            logger.debug("quote failed for %s: %s", symbol, exc)
            report.tickers_failed.append(symbol)

    # --- database phase -----------------------------------------------------
    with session_scope() as session:
        persist_quotes(session, snapshots, report=report)

    return JobResult(
        items_seen=report.tickers_requested,
        items_written=report.tickers_returned,
        detail=report.as_dict(),
    )


def ingest_news_rss(tickers: list[str] | None = None) -> JobResult:
    """Poll RSS and optional providers, then classify anything new.

    ``tickers`` scopes the poll to named instruments, for a manual one-instrument
    refresh. The universe walk is ordered by its own cursor, so a scoped run neither
    reads nor advances it.
    """
    from awltux.ingest.news import ingest_rss_news
    from awltux.llm.classify import build_classifier

    classifier = build_classifier()
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            # A bare zero here was misleading: it looked like "no news was
            # published" rather than "there was nothing to look for".
            logger.info("news ingest skipped: %s", note)
            return JobResult(note=note)
        report = ingest_rss_news(session, tickers=tickers, classifier=classifier)

    return JobResult(
        items_seen=report.fetched,
        items_written=report.written,
        note=(
            "polled the whole universe but every feed returned nothing"
            if report.fetched == 0
            else None
        ),
        detail=report.as_dict(),
    )


def ingest_sector_news_job() -> JobResult:
    """Poll news for each of the eleven industry sectors.

    Sector stories are what a sector page has to show and what produces a `sector`
    appraisal at all: measured 2026-10-07, 19,418 of 19,475 stored stories carried no
    sector, because every feed this system polls is addressed by ticker.
    """
    from awltux.ingest.news import ingest_sector_news
    from awltux.llm.classify import build_sector_classifier

    classifier = build_sector_classifier()
    with session_scope() as session:
        report = ingest_sector_news(session, classifier=classifier)

    return JobResult(
        items_seen=report.fetched,
        items_written=report.written,
        note=(
            "polled all eleven sectors but every feed returned nothing"
            if report.fetched == 0
            else None
        ),
        detail=report.as_dict(),
    )


def analyse_news(tickers: list[str] | None = None) -> JobResult:
    """Sceptically appraise recent news: sources, framing, corroboration, claims.

    Deliberately a separate job from the poll. The poll is volume work on hundreds
    of loose headlines and has to stay cheap; this is per-story work that costs a
    model call for the stories that warrant one, and mixing the two would put the
    paid work on the critical path of every five-minute poll.
    """
    from awltux.analysis.news_analysis import analyse_universe
    from awltux.config import get_settings
    from awltux.llm.news_sceptic import build_analyser

    settings = get_settings()
    config = settings.news.scepticism
    if not config.enabled:
        return JobResult(note="news scepticism is disabled in configuration")

    analyser = build_analyser(settings)
    with session_scope() as session:
        report = analyse_universe(
            session,
            tickers=tickers,
            settings=settings,
            analyser=analyser,
            days=config.lookback_days,
            # A scoped refresh is asking about one company, so the ration that spreads
            # forty deep reads across the universe has nothing to spread here.
            limit=None if tickers else config.max_deep_per_run,
            refresh_after_days=config.refresh_after_days,
        )

    if report["examined"] == 0:
        note = "no news in the lookback window to appraise"
    elif report["selected"] == 0:
        note = (
            f"appraised nothing: none of the {report['examined']} recent items cleared "
            "the interest threshold (materiality, framing, held position or thin coverage)"
        )
    elif analyser is None:
        note = (
            "deterministic appraisal only: DeepSeek is not configured, so claims, "
            "omissions and primary-source tracing were not produced"
        )
    else:
        note = None

    return JobResult(
        items_seen=report["selected"],
        items_written=report["appraised"],
        note=note,
        detail=report,
    )


def embed_news() -> JobResult:
    """Give stored stories a vector, so one event can be recognised as one event.

    Only relevant stories are embedded. A story with no instrument and no direction
    never reaches the banner, so a vector for it would be paid for and never
    compared against anything.

    Newest first, because clustering is what the banner uses and the banner looks at
    recent stories. An old backlog is worth less than today's coverage.

    Rationed like every other paid job, and it records *why* it did nothing: "one
    entry per event" and "one entry per story" look identical in the UI, and only
    one of them means the feature works.
    """
    from sqlalchemy import select

    from awltux.analysis.embeddings import EmbeddingClient, embed_text, store_vectors
    from awltux.config import get_settings
    from awltux.db import NewsEmbedding, NewsItem
    from awltux.db.session import release_write_lock

    settings = get_settings()
    config = settings.news.embeddings
    client = EmbeddingClient(settings)
    if not client.configured:
        return JobResult(
            note=(
                "embeddings are not configured, so stories cannot be grouped by "
                "event: set news.embeddings.base_url to an OpenAI-compatible endpoint"
            )
        )

    embedded = 0
    errors: list[str] = []
    fatal = False
    with session_scope() as session:
        already = select(NewsEmbedding.news_item_id).where(
            NewsEmbedding.model == config.model
        )
        pending = list(
            session.execute(
                select(NewsItem)
                .where(NewsItem.relevant.is_(True))
                .where(NewsItem.id.not_in(already))
                .order_by(NewsItem.id.desc())
                .limit(config.max_per_run)
            ).scalars().all()
        )
        if not pending:
            return JobResult(note="every relevant story already has a vector")

        batch_size = max(1, config.batch_size)
        batch_count = (len(pending) + batch_size - 1) // batch_size
        for start in range(0, len(pending), batch_size):
            # Between batches, on the committed side of the previous one: one model call
            # per batch and `max_per_run` of them, so without this a quiet waits for the
            # whole ration.
            progress.checkpoint(
                f"batch {start // batch_size + 1} of {batch_count} ({len(pending)} stories)"
            )
            batch = pending[start : start + batch_size]
            texts = [embed_text(item) for item in batch]
            # Vector maths is ours; the provider only turns text into numbers.
            release_write_lock(session)
            result = client.embed(texts)
            errors.extend(result.errors)
            if result.vectors:
                kept = len(result.vectors)
                embedded += store_vectors(
                    [item.id for item in batch][:kept],
                    texts[:kept],
                    result.vectors,
                    model=config.model,
                )
            if result.fatal:
                # A rejected credential or a model the account cannot use. The
                # remaining batches cannot succeed either, so asking is sixteen more
                # requests against a rate-limited endpoint to learn nothing.
                fatal = True
                break
            release_write_lock(session)

    client.close()

    # Deduplicate: a rejection repeats identically for every batch, and sixteen
    # copies of one sentence is not more information than one.
    unique: list[str] = []
    for message in errors:
        if message not in unique:
            unique.append(message)

    if fatal:
        note = (
            "stopped after the first batch: "
            f"{unique[0] if unique else 'the endpoint refused the request'}"
        )
    elif embedded == 0:
        note = "no vectors were produced: " + (
            "; ".join(unique[:2]) or "the provider returned nothing"
        )
    elif unique:
        note = f"{embedded} stories embedded; {len(unique)} batch(es) failed and will retry"
    else:
        note = None

    return JobResult(
        items_seen=len(pending),
        items_written=embedded,
        note=note,
        detail={
            "embedded": embedded,
            "model": config.model,
            "stopped_early": fatal,
            "errors": unique[:5],
        },
    )


def _pending_relevance_verdicts(session, tickers: list[str] | None) -> list[Any]:
    """The stories this run may judge: the backlog window, minus other people's work.

    A named step because the two narrowings are different questions asked of one window,
    and only one of them applies per run. A scoped run asks about *this* instrument. A
    sweep asks about everything except the instruments a one-instrument refresh is
    working on -- both processes write the verdict to the same story row.

    Both are answered in Python, because a story's instruments are a JSON list and
    `json_each` cannot use an index: matched in SQL it would cost a table scan to skip
    a handful of rows.
    """
    from sqlalchemy import select

    from awltux.db import NewsItem

    pending = list(
        session.execute(
            select(NewsItem)
            .where(NewsItem.relevant.is_(None))
            .order_by(NewsItem.id)
            .limit(RELEVANCE_BACKFILL_ROWS if not tickers else None)
        ).scalars().all()
    )
    if tickers:
        # Scoped to a manual refresh, so the window is the instrument rather than a
        # rationed slice of the backlog -- for one instrument over a deliberate button
        # press that is the right trade, and for the scheduled sweep the rationed window
        # above is what keeps it bounded.
        wanted = set(tickers)
        return [item for item in pending if wanted & set(item.tickers or [])]

    from awltux.ingest.lease import locked_tickers, touches_locked

    locked = locked_tickers(session)
    if not locked:
        return pending
    return [item for item in pending if not touches_locked(item.tickers, locked)]


def assess_news_relevance(tickers: list[str] | None = None) -> JobResult:
    """Decide whether stored stories are claims about a share price.

    Relevance is normally settled at ingest, by the same classifier call that
    produces the direction. This job exists for the rows that call never reached:

    * items stored before the classifier was configured (the deployment has 261 of
      them, all with ``direction`` and ``materiality`` NULL);
    * items whose classification failed on a transient error;
    * everything written before this rule existed, which the migration deliberately
      left NULL rather than deciding in an unattended schema change.

    It is a separate job from ``news_analysis`` because the two cost very different
    things and answer different questions. Relevance is one cheap classification
    per story -- about a five-hundred-token prompt -- while the scepticism
    appraisal is a deep read rationed to sixty calls a run. Putting them in one job
    would make the cheap backfill wait behind the expensive one.

    Rationed for the same reason every other paid job is: a bounded number of model
    calls per run, oldest first, so a backlog drains over several runs instead of
    spending the month's budget in one. The bound is on calls rather than on rows,
    because the rows decided from what is already stored cost nothing.
    """
    from sqlalchemy import select

    from awltux.analysis.relevance import assess
    from awltux.config import get_settings
    from awltux.db import Instrument
    from awltux.db.session import release_write_lock
    from awltux.llm.classify import apply_classification, build_classifier
    from awltux.providers.news_rss import RawNewsItem

    settings = get_settings()
    # The cap is on *model calls*, not rows. Relevance is decided structurally
    # wherever a direction is already stored -- which is 5,500 of the 5,800 rows in
    # this deployment -- so bounding the row window would make a free, instant
    # backfill take thirty runs to drain while protecting nothing. The paid work is
    # what needs rationing, and the row window is only there to bound memory.
    call_limit = settings.news.relevance_backfill_per_run
    classifier = build_classifier(settings)

    with session_scope() as session:
        pending = _pending_relevance_verdicts(session, tickers)
        if not pending:
            return JobResult(note="every stored story already has a relevance verdict")

        # Resolve the instrument a story was fetched for, so the classifier is
        # asked about the right company rather than about the ticker string.
        wanted = {ticker for item in pending for ticker in (item.tickers or [])}
        instruments = (
            {
                row.t212_ticker: row
                for row in session.execute(
                    select(Instrument).where(Instrument.t212_ticker.in_(wanted))
                ).scalars().all()
            }
            if wanted
            else {}
        )

        assessed = 0
        classified = 0
        structural = 0
        errors: list[str] = []

        for position, item in enumerate(pending, start=1):
            # Checked on every story, reported every hundredth: the row window is
            # thousands of rows and most of them cost nothing, so a line each would bury
            # the log it exists to make readable. `progress.py` names this split.
            if position % 100 == 1:
                progress.note(f"{position} of {len(pending)} stories")
            progress.barrier(f"{position} of {len(pending)} stories")
            instrument = next(
                (instruments.get(ticker) for ticker in (item.tickers or []) if instruments.get(ticker)),
                None,
            )
            about: bool | None = None

            # Only ask the model where there is something to ask. A row that already
            # carries a direction is decided entirely by the structural half of the
            # rule, and re-classifying it would pay again for an answer that is
            # already stored -- 5,500 of the 5,800 rows in this deployment are in
            # that position. The model is needed only for rows whose classification
            # never ran or failed, which is the backlog this job exists for.
            # The row window bounds memory; the call limit bounds spend.
            needs_model = (
                item.direction is None
                and classifier is not None
                and instrument is not None
                and classified < call_limit
            )
            if needs_model:
                # The same rule the ingest path follows: no provider call inside an
                # open transaction.
                release_write_lock(session)
                raw = RawNewsItem(
                    title=item.title,
                    url=item.url or "",
                    source=item.source,
                    summary=item.summary,
                    published_at=item.published_at,
                    tickers=list(item.tickers or []),
                )
                try:
                    updates = classifier(raw, instrument)
                except Exception as exc:  # noqa: BLE001 - one story must not stop the run
                    errors.append(f"{item.id}: {exc}")
                    updates = None
                if updates:
                    apply_classification(item, updates)
                    about = updates.get("is_about_this_company")
                    classified += 1
            else:
                structural += 1

            verdict = assess(
                tickers=item.tickers,
                sectors=item.sectors,
                direction=item.direction,
                materiality=item.materiality,
                about=about,
            )
            item.relevant = verdict.relevant
            if not item.relevance_reason:
                item.relevance_reason = verdict.reason
            assessed += 1

            # Bound the transaction, not just the calls. Only a couple of hundred of
            # the five thousand rows need a model call, so releasing the lock only
            # around those leaves long stretches where thousands of pending updates
            # accumulate and land in one flush -- the same shape as the 31-second
            # instrument sync that broke every concurrent writer.
            if assessed % RELEVANCE_FLUSH_EVERY == 0:
                session.flush()
                release_write_lock(session)

        session.flush()

    if classifier is None:
        note = (
            "relevance recorded structurally only: DeepSeek is not configured, so "
            "stories with no stored direction are not relevant"
        )
    elif classified == 0:
        note = (
            f"no model calls needed: all {assessed} stories already carried a stored "
            "direction, so the rule decided them"
        )
    elif classified >= call_limit:
        remaining = len(pending) - assessed
        note = (
            f"hit the {call_limit}-call ceiling for one run; "
            f"{remaining} stories were not examined and will be picked up next run"
        )
    else:
        note = (
            f"{classified} stories had no direction and were classified; {structural} "
            "were decided from what was already stored"
        )

    return JobResult(
        items_seen=len(pending),
        items_written=assessed,
        note=note,
        detail={
            "assessed": assessed,
            "classified": classified,
            "decided_structurally": structural,
            "errors": errors[:10],
        },
    )


def _lookup_symbol(provider, query: str, instrument: Any, *, by_isin: bool):
    """Score the candidates one provider search returns.

    Split out because the job now makes this call twice per stuck instrument, and
    the two calls have to be scored identically apart from where they were found.
    """
    from awltux.ingest.identity import choose_symbol

    if not query:
        return None
    return choose_symbol(
        provider.search_symbols(query),
        instrument_name=instrument.name,
        instrument_exchange=instrument.exchange_name,
        instrument_type=instrument.instrument_type,
        queried_by_isin=by_isin,
    )


def refresh_provider_balances() -> JobResult:
    """Ask each model provider what is left on the account.

    Running out of credit is the one provider failure that is neither transient nor a bug,
    and it presents like both: the decision engine falls back to the deterministic rules,
    the embeddings job records a fatal error, and nothing says *the account is empty*.
    This is the only job here that costs nothing to run and prevents the most.

    A provider that cannot be asked is recorded as unreadable rather than skipped, so the
    banner can say which provider it cannot see and why. Nothing about this job fails the
    run: an unreadable balance is a state, not an error.
    """
    from awltux.providers import balances as balance_probes

    readings = balance_probes.read_all()
    with session_scope() as session:
        balance_probes.store(session, readings)

    readable = [row for row in readings if row.amount is not None]
    unreadable = [row for row in readings if row.amount is None]
    return JobResult(
        items_seen=len(readings),
        items_written=len(readable),
        note=(
            None
            if readable
            else "no provider reported a balance; see the notes for why"
        ),
        detail={
            "balances": {
                row.provider: {
                    "available": row.available,
                    "amount": row.amount,
                    "currency": row.currency,
                    "note": row.note,
                }
                for row in readings
            },
            "unreadable": [row.provider for row in unreadable],
        },
    )


def refresh_macro_rates() -> JobResult:
    """Observe the risk-free rate for every currency the model discounts in.

    One number per currency, and it decides every discounted fair value in the
    database: the rate anchors the CAPM cost of equity, which anchors the discount
    rate. It used to be a constant in ``config.yaml``, which is correct on the day it
    is typed and silently wrong afterwards -- on 2026-10-05 the ten-year Treasury
    yielded 5.31% against a configured 4.2%.

    **Per currency, because a discount rate must match the cash flows.** Roughly a
    quarter of this universe is sterling, and discounting sterling cash flows at a
    dollar rate embeds a cross-currency view the model does not hold. Each currency
    reads its own sovereign's curve; a currency with none wired up is left to the
    configured constant rather than quietly given someone else's rate.

    The observation is *stored* rather than read at import so that a valuation can
    be reproduced against the rate actually in force when it was computed, and so a
    failed fetch degrades to the configured constant instead of failing the sweep.
    One currency failing does not stop the others being recorded.
    """
    from awltux.analysis import macro
    from awltux.providers.gilt import GiltProvider
    from awltux.providers.http import ProviderError
    from awltux.providers.treasury import TreasuryProvider

    settings = get_settings()
    tenor = settings.valuation.risk_free_rate_tenor
    builders = {"treasury": TreasuryProvider, "gilt": GiltProvider}

    written = 0
    seen = 0
    errors: list[str] = []
    detail: dict[str, Any] = {"tenor": tenor, "currencies": {}}

    # One fetch per *source*, not per currency: both currencies a source serves come
    # from the same published curve, and the Treasury's is the whole curve at once.
    for source in sorted(set(macro.CURRENCY_CURVES.values())):
        provider = builders[source](settings)
        try:
            # No session is open across this call, so nothing holds the write lock.
            curve = provider.yield_curve()
        except ProviderError as exc:
            errors.append(f"{source}: {exc}")
            continue
        finally:
            provider.close()

        currencies = [
            code for code, name in macro.CURRENCY_CURVES.items() if name == source
        ]
        for currency in currencies:
            seen += len(curve.rates)
            with session_scope() as session:
                observation = macro.store_observation(
                    session, curve, currency=currency, tenor=tenor
                )
            if observation is None:
                errors.append(
                    f"{currency}: the {tenor} point was missing or implausible in the "
                    f"curve published {curve.as_of.isoformat()}"
                )
                continue
            written += 1
            detail["currencies"][currency] = {
                "as_of": curve.as_of.isoformat(),
                "risk_free_rate": observation.value,
                "source": source,
                "yield_curve": curve.as_dict(),
            }

    if not written:
        note = (
            "; ".join(errors)
            if errors
            else "no currency has a sovereign curve wired up, so nothing was observed"
        )
        return JobResult(note=f"no risk-free rate was stored: {note}", detail=detail)

    if errors:
        # Reported, not swallowed: one currency falling back to the configured
        # constant while another is priced off the market is a state a reader needs
        # to be able to see.
        detail["errors"] = errors

    return JobResult(items_seen=seen, items_written=written, detail=detail)


def sync_shareholder_reports(tickers: list[str] | None = None) -> JobResult:
    """Find and download the annual reports: this year and the previous one.

    The annual report is the primary evidence about a business, and until now this
    system held only a pointer to one. The ``filing`` table carried 4,529 rows and
    not a single document -- ``raw_path``, ``doc_hash`` and ``parsed`` were columns
    on the model that nothing ever wrote -- so every filing sat at ``pending`` for
    ever and the reports could not be read, quoted or checked.

    Two phases, and they are reported separately because they fail differently. The
    first asks EDGAR for the annual forms by date, which is what a multi-year window
    needs and what the general filing sync cannot give: that takes the fifteen most
    recent *interesting* filings, so a company that files a lot of 8-Ks had its
    older 10-Ks cut off by a limit rather than by a date. The second downloads the
    documents behind those rows.

    ``tickers`` scopes both phases to one company and lifts the per-run download
    ration, which exists to spread a universe-wide sweep over several runs.
    """
    from awltux.ingest.documents import (
        deepen_annual_history,
        fetch_annual_reports,
        refresh_report_flags,
    )

    settings = get_settings()
    years = settings.reports.years
    per_run = settings.reports.per_run

    with session_scope() as session:
        discovery = deepen_annual_history(
            session, years=years, settings=settings, tickers=tickers
        )

    with session_scope() as session:
        download = fetch_annual_reports(
            session,
            limit=None if tickers else per_run,
            settings=settings,
            tickers=tickers,
        )
        # The flag is recomputed from the rows rather than incremented as documents
        # arrive, so a run that dies halfway leaves it describing what is held
        # rather than what was attempted.
        flagged = refresh_report_flags(session)

    detail = _document_detail(discovery, download, years=years, flagged=flagged)

    if not discovery.discovered and not download.fetched:
        return JobResult(
            note=(
                "no annual report needed fetching: either every filer already has "
                "its reports stored or none has a resolved CIK"
            ),
            detail=detail,
        )
    return JobResult(
        items_seen=discovery.discovered,
        items_written=download.fetched,
        detail=detail,
    )


def _document_detail(
    discovery: Any, download: Any, *, years: int, flagged: int
) -> dict[str, Any]:
    """What the two phases did, as one run's detail.

    A named step because the two phases fail differently and the reader needs both halves:
    a run that discovered six reports and downloaded none is a download problem, and one
    that discovered none is a discovery problem -- and the counts for each come from a
    different report.
    """
    return {
        "years": years,
        "discovered": discovery.discovered,
        "downloaded": download.fetched,
        "failed": download.failed,
        "bytes_written": download.bytes_written,
        "instruments_covered": len(download.instruments),
        "instruments_flagged": flagged,
        "discovery_errors": discovery.errors[:5],
        "download_errors": download.errors[:5],
    }


def _stuck_instruments(
    session, *, tickers: list[str] | None, limit: int
) -> list[Instrument]:
    """Instruments with an ISIN and no price history: the ones a lookup can help.

    A named step rather than a block inside the job for the reason the job's own docstring
    gives: this is the *input* to the whole thing, and the scoped and sweeping cases
    differ only here. The limit rations a daily sweep across runs; a one-instrument
    refresh must not be rationed out of the run it was asked for, and the "no price
    history" filter is why the refresh runs this *before* prices -- a derived symbol that
    is wrong shows up as an instrument with no bars.
    """
    from sqlalchemy import select

    from awltux.db import Instrument, PriceBar

    priced = select(PriceBar.instrument_t212_ticker).distinct()
    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.isin.is_not(None))
        .where(Instrument.t212_ticker.not_in(priced))
        .order_by(Instrument.t212_ticker)
    )
    if tickers is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(tickers)))
    else:
        statement = statement.limit(limit)
    return list(session.execute(statement).scalars().all())


def resolve_symbols(tickers: list[str] | None = None) -> JobResult:
    """Look up the provider symbol for instruments a derived one cannot reach.

    Every price, account and news item joins on a provider symbol, and until now
    that symbol was *derived* from the Trading 212 ticker. That works until the
    ticker is stale, and T212's are frequently former ones -- Humacyte is
    ``AHAC_US_EQ`` there and ``HUMA`` on Yahoo. Deriving cannot recover from that,
    and 92 of 500 instruments were failing every price run forever, invisibly.

    An ISIN does not go stale. It is Trading 212's own identifier, it survives
    renames and restructurings, and searching by it returned the right company for
    seven of the first eight instruments that no derived symbol could reach.

    Only instruments that are actually *stuck* are looked up: those with no stored
    bar. Re-resolving the whole universe would spend hundreds of searches a day to
    confirm what is already working.

    Every outcome is recorded on the alias, including the failures. An alias saying
    "below the 0.70 floor, names share 40% of their words" is a request for a human;
    an instrument with no alias at all is one nobody will ever look at.
    """

    from awltux.config import get_settings
    from awltux.db.session import release_write_lock
    from awltux.ingest.blockers import record_blocker
    from awltux.ingest.identity import APPLY_FLOOR
    from awltux.providers.http import ProviderError
    from awltux.providers.yahoo import YahooProvider

    settings = get_settings()
    limit = settings.schedule.symbol_resolution_per_run
    provider = YahooProvider(settings)

    with session_scope() as session:
        stuck = _stuck_instruments(session, tickers=tickers, limit=limit)
        if not stuck:
            return JobResult(
                note=(
                    "every universe instrument with an ISIN has price history, so "
                    "there is no symbol left to resolve"
                )
            )

    resolved: list[str] = []
    rejected: list[str] = []
    unresolved: list[str] = []
    errors: list[str] = []

    for position, instrument in enumerate(stuck, start=1):
        # Two provider searches per instrument, each rate-limited, so this run is
        # minutes long and silent without a counted line -- and it is a *checkpoint*
        # rather than a note, because a loop that can say how far it has got is a loop
        # that can be left. Each phase below is its own committed scope.
        progress.checkpoint(f"{position} of {len(stuck)}: {instrument.t212_ticker}")
        # Release before the search, like every other network call in this codebase.
        with session_scope() as session:
            release_write_lock(session)

        by_isin = True
        try:
            # The ISIN goes first: it survives a rename, which is the whole reason
            # this job exists.
            resolution = _lookup_symbol(provider, instrument.isin or "", instrument, by_isin=True)
            if resolution is None or not resolution.usable:
                # Then the name, whenever the ISIN lookup did not produce something
                # worth applying.
                #
                # This used to run only when the ISIN search returned *no*
                # candidates, which is the rarer case. An ISIN identifies the
                # *company*, and a company can be listed in several places, so
                # Yahoo's ISIN search frequently returns only the foreign listings:
                # BRP's ``CA05577W2004`` comes back as ``DOO.TO`` and
                # ``CA05577W2004.SG``, never as the Nasdaq ``DOO``. The venue check
                # then refuses them -- correctly, because a Toronto price is not the
                # one we want -- and the instrument stayed stuck with its own
                # venue's listing sitting one name search away, never asked for.
                by_isin = False
                by_name = _lookup_symbol(provider, instrument.name, instrument, by_isin=False)
                if by_name is not None and (
                    by_name.usable
                    or resolution is None
                    or by_name.confidence > resolution.confidence
                ):
                    # A usable name match wins outright; otherwise keep whichever of
                    # the two carries more evidence, so the alias records the best
                    # candidate found rather than merely the first.
                    resolution = by_name
        except ProviderError as exc:
            errors.append(f"{instrument.t212_ticker}: {exc}")
            # The alias row records this too, but only for a reader who opens this
            # instrument: the blocker is what puts it in front of one.
            with session_scope() as session:
                record_blocker(
                    session,
                    instrument.t212_ticker,
                    job="symbol_resolution",
                    stage="symbol",
                    reason=str(exc),
                )
            continue

        outcome, symbol = _store_symbol_verdict(instrument, resolution, by_isin=by_isin)
        if outcome == "resolved":
            resolved.append(f"{instrument.t212_ticker}->{symbol}")
        elif outcome == "rejected":
            rejected.append(f"{instrument.t212_ticker}->{symbol}")
        elif outcome == "unresolved":
            unresolved.append(instrument.t212_ticker)

    if errors:
        note = f"{len(errors)} lookups failed and will retry: {errors[0]}"
    elif not resolved and not rejected:
        note = (
            f"{len(unresolved)} instruments were searched and none has a listing "
            "that matches, so they need a human"
        )
    else:
        note = None

    return JobResult(
        items_seen=len(stuck),
        items_written=len(resolved),
        note=note,
        detail={
            "looked_up": len(stuck),
            "resolved": len(resolved),
            "resolved_symbols": resolved[:25],
            "rejected_below_floor": len(rejected),
            "rejected_symbols": rejected[:25],
            "no_match": len(unresolved),
            "no_match_tickers": unresolved[:25],
            "floor": APPLY_FLOOR,
            "errors": errors[:10],
        },
    )


def _store_symbol_verdict(
    instrument: Any, resolution: Any, *, by_isin: bool
) -> tuple[str, str | None]:
    """Write the candidate to the alias, and say what the run made of it.

    Returns ``(outcome, symbol)``, where the outcome is ``"resolved"``, ``"rejected"``,
    ``"unresolved"`` or ``"manual"`` -- a human's correction is never overwritten, which
    is the same rule the universe sync follows.

    A named step because the outcome *is* the blocker: every answer except a trusted
    symbol records why this instrument still has no provider to fetch prices from, and
    the attention filter reads that instead of a run's log. Its own session, like every
    other database phase in this job -- the searches that produced the candidate are
    network calls and must not be inside a transaction.
    """
    from sqlalchemy import select

    from awltux.db import Instrument, InstrumentAlias, session_scope, utcnow
    from awltux.ingest.blockers import clear_blocker, record_blocker
    from awltux.ingest.identity import describe

    ticker = instrument.t212_ticker
    with session_scope() as session:
        row = session.get(Instrument, ticker)
        if row is None:
            return "manual", None
        alias = session.execute(
            select(InstrumentAlias).where(
                InstrumentAlias.instrument_t212_ticker == ticker,
                InstrumentAlias.provider == "yahoo",
            )
        ).scalar_one_or_none()
        if alias is None:
            alias = InstrumentAlias(
                instrument_t212_ticker=ticker, provider="yahoo", symbol=""
            )
            session.add(alias)
        if alias.is_manual:
            return "manual", None

        if resolution is not None:
            alias.symbol = resolution.symbol
            alias.confidence = resolution.confidence
            alias.method = resolution.method
            alias.note = describe(resolution, instrument_name=instrument.name)
        else:
            alias.confidence = 0.0
            alias.method = "isin" if by_isin else "name"
            alias.note = describe(None)
        alias.verified_at = utcnow()

        if resolution is not None and resolution.usable:
            row.yahoo_symbol = resolution.symbol
            row.mapping_confidence = resolution.confidence
            clear_blocker(session, ticker, job="symbol_resolution", stage="symbol")
            session.flush()
            return "resolved", resolution.symbol

        if resolution is not None:
            # Recorded but not trusted. Left unresolved on purpose: attaching another
            # company's prices would be worse than a visible gap.
            record_blocker(
                session,
                ticker,
                job="symbol_resolution",
                stage="symbol",
                reason=alias.note or "no candidate above the confidence floor",
            )
            session.flush()
            return "rejected", resolution.symbol

        record_blocker(
            session,
            ticker,
            job="symbol_resolution",
            stage="symbol",
            reason=(
                "no Yahoo listing matched the ISIN or the company name, so this "
                "instrument has no provider symbol to fetch prices with"
            ),
        )
        session.flush()
        return "unresolved", None


def ingest_edgar_events() -> JobResult:
    """Poll EDGAR's current-events feed for new US filings."""
    from awltux.ingest.edgar import ingest_current_events

    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("edgar event ingest skipped: %s", note)
            return JobResult(note=note)
        report = ingest_current_events(session)

    return JobResult(
        items_seen=len(report.errors),
        items_written=report.events_written,
        detail=report.as_dict(),
    )


def sync_filings(tickers: list[str] | None = None) -> JobResult:
    """Refresh filing history for instruments with a resolved CIK.

    ``tickers`` scopes the CIK resolution *and* the fetch to named instruments. The
    resolution half matters for a single US listing and is otherwise a no-op, because
    an instrument with a CIK already resolves to itself.
    """
    from sqlalchemy import func, select

    from awltux.db import Instrument
    from awltux.ingest.edgar import resolve_ciks
    from awltux.ingest.edgar import sync_filings as _sync

    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("filing sync skipped: %s", note)
            return JobResult(note=note)

        with_cik = session.execute(
            select(func.count())
            .select_from(Instrument)
            .where(Instrument.sec_cik.is_not(None))
        ).scalar_one()

        resolution = resolve_ciks(session, tickers=tickers)
        if int(with_cik or 0) == 0 and not resolution.resolved:
            # Worth naming explicitly: EDGAR covers US filers only, so a
            # London-only book legitimately has nothing here.
            return JobResult(
                note=(
                    "no instruments have a resolved SEC CIK. EDGAR covers US "
                    "filers only; a London-only listing is absent by design and is "
                    "served by Companies House instead."
                ),
                detail={"cik_resolution": resolution.as_dict()},
            )

        report = _sync(session, tickers=tickers)

    return JobResult(
        items_seen=report.filings_seen,
        # A backfilled period is a write: most of the stored filings gained the
        # period they report on in one pass, and reporting written=0 while 4,958
        # rows changed is the kind of number that stops being believed.
        items_written=report.filings_written + report.periods_backfilled,
        detail={**report.as_dict(), "cik_resolution": resolution.as_dict()},
    )


def sync_fundamentals_job(tickers: list[str] | None = None) -> JobResult:
    """Rotating fundamentals refresh, rationed to keep within free-tier limits.

    The configured per-day rotation is divided across the 24 hourly runs so the
    load is spread rather than concentrated in one burst.

    ``tickers`` is the one-instrument scope a manual refresh uses. It is a keyword with a
    default rather than a second function so the scheduled and the scoped run take
    exactly the same path -- same blockers, same progress lines, same report -- and the
    rotation limit is lifted, because a rationed batch of two is not "refresh this one".
    """
    settings = get_settings()
    from awltux.ingest.fundamentals import sync_fundamentals

    per_run = 1 if tickers else max(1, settings.schedule.fundamentals_rotation_per_day // 24)
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("fundamentals sync skipped: %s", note)
            return JobResult(note=note)
        report = sync_fundamentals(
            session, tickers=tickers, limit=None if tickers else per_run
        )

    return JobResult(
        items_seen=report.tickers_attempted,
        items_written=report.periods_written,
        detail={**report.as_dict(), "per_run_limit": per_run if not tickers else "scoped"},
    )


def sync_xbrl_statements_job(tickers: list[str] | None = None) -> JobResult:
    """Annual statements from XBRL company facts, for US filers.

    Separate from ``fundamentals`` because the two answer different questions and
    fail in different ways. ``fundamentals`` asks a market-data provider for a
    normalised snapshot; this reads the issuer's own tagging of its own statements
    out of EDGAR, which is slower per name and far better per figure. Keeping them
    apart means a rate-limited Yahoo run does not also stop the filings being read.
    """
    settings = get_settings()
    from awltux.ingest.xbrl import sync_xbrl_fundamentals

    per_run = 1 if tickers else max(1, settings.schedule.fundamentals_rotation_per_day // 24)
    with session_scope() as session:
        note = empty_universe_note(session)
        if note:
            logger.info("xbrl statements skipped: %s", note)
            return JobResult(note=note)
        report = sync_xbrl_fundamentals(
            session, settings=settings, tickers=tickers, limit=None if tickers else per_run
        )

    return JobResult(
        items_seen=report.tickers_attempted,
        items_written=report.periods_written,
        detail={**report.as_dict(), "per_run_limit": per_run if not tickers else "scoped"},
    )


def resolve_uk_companies_job(tickers: list[str] | None = None) -> JobResult:
    """Attach Companies House numbers to UK-listed instruments."""
    from awltux.ingest.fundamentals import resolve_uk_companies

    with session_scope() as session:
        summary = resolve_uk_companies(
            session, tickers=tickers, limit=None if tickers else 50
        )

    return JobResult(
        items_seen=summary.get("attempted", 0),
        items_written=summary.get("matched", 0),
        detail=summary,
    )


def run_valuations(tickers: list[str] | None = None) -> JobResult:
    """Recompute the deterministic valuation for the universe."""
    from awltux.analysis.valuation import run_valuations as _run

    with session_scope() as session:
        stats = _run(session, tickers=tickers)

    return JobResult(
        items_seen=stats.get("attempted", 0),
        items_written=stats.get("valued", 0),
        detail=stats,
    )


def run_decisions(tickers: list[str] | None = None) -> JobResult:
    """Decide for a rotated slice of instruments, least recently decided first.

    Bounded like every other paid job here. Measured 2026-10-07: about **4.1 decisions a
    minute**, so the whole universe in one call is a 110-minute job -- longer than the
    interval it runs on, killed by every deploy, and the reason `decision` had 6 runs and
    0 successes. The per-day rotation is divided across the 24 hourly runs, the shape
    `sync_fundamentals_job` uses; a scoped refresh is one instrument and is not rationed.

    A bounded run is only honest because the selection rotates: `decide_universe` orders
    by least recently decided, so successive runs walk the whole universe rather than
    deciding the same names every hour.
    """
    from awltux.decision.service import decide_universe

    settings = get_settings()
    per_run = (
        None
        if tickers
        else max(1, settings.schedule.decision_rotation_per_day // 24)
    )
    with session_scope() as session:
        stats = decide_universe(session, tickers=tickers, limit=per_run)

    stats["per_run_limit"] = per_run if per_run is not None else "scoped"
    return JobResult(
        items_seen=stats.get("attempted", 0),
        items_written=stats.get("decided", 0),
        detail=stats,
    )


def update_calibration() -> JobResult:
    """Score elapsed decisions against subsequent prices."""
    from awltux.audit.calibration import score_pending_decisions

    with session_scope() as session:
        stats = score_pending_decisions(session)

    return JobResult(
        items_seen=stats.get("scored", 0) + stats.get("skipped_no_price", 0),
        items_written=stats.get("scored", 0),
        detail=stats,
    )


def aggregate_sentiment(tickers: list[str] | None = None) -> JobResult:
    """Roll news items up into per-stock and per-sector sentiment series."""
    from awltux.analysis.sentiment import aggregate_all

    with session_scope() as session:
        stats = aggregate_all(session, tickers=tickers)

    return JobResult(
        items_seen=stats.get("instruments_seen", 0),
        items_written=stats.get("rows_written", 0),
        detail=stats,
    )


def apply_retention() -> JobResult:
    """Prune high-volume tables according to the retention policy."""
    import datetime as dt

    from sqlalchemy import delete

    from awltux.db import LLMCall, ProviderBalanceReading, Quote

    settings = get_settings()
    retention = settings.retention
    now = dt.datetime.now(dt.UTC)
    removed: dict[str, int] = {}

    with session_scope() as session:
        quote_cutoff = now - dt.timedelta(days=retention.quote_days)
        result = session.execute(delete(Quote).where(Quote.ts < quote_cutoff))
        removed["quotes"] = result.rowcount or 0

        llm_cutoff = now - dt.timedelta(days=retention.llm_call_days)
        result = session.execute(delete(LLMCall).where(LLMCall.created_at < llm_cutoff))
        removed["llm_calls"] = result.rowcount or 0

        # A balance reading is small and irreplaceable -- nothing can re-ask what the
        # account held last March -- so this window is measured in years where the two
        # above are measured in months.
        balance_cutoff = now - dt.timedelta(days=retention.balance_days)
        result = session.execute(
            delete(ProviderBalanceReading).where(
                ProviderBalanceReading.read_at < balance_cutoff
            )
        )
        removed["balance_readings"] = result.rowcount or 0

    return JobResult(items_written=sum(removed.values()), detail={"removed": removed})
