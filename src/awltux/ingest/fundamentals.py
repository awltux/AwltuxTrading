"""Fundamentals: canonical metrics, and UK entity resolution.

Two jobs, joined by one idea: get financial numbers into a single shape with a
recorded source, and be honest about confidence when the source is uncertain.

**Canonical metrics.** US GAAP and UK FRS/IFRS tag different line items under
different names. Everything is mapped onto one key set here so the valuation
model never has to know which taxonomy produced a number.

**UK entity resolution is the weakest link in the pipeline.** A London ticker
does not come with a Companies House company number, the register's search is
name-based, and UK company names collide constantly. So a match is scored, not
assumed: an exact normalised name match against an active company is trusted,
anything weaker is recorded but excluded from decisions until confirmed.
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis.sectors import assign
from awltux.config import Settings, get_settings
from awltux.db import FundamentalPeriod, Instrument, InstrumentAlias, utcnow
from awltux.db.session import release_write_lock
from awltux.ingest.blockers import clear_blocker, record_blocker
from awltux.metrics import CANONICAL_METRICS, OUTFLOW_METRICS  # noqa: F401  (re-exported)
from awltux.numbers import as_finite_float
from awltux.providers.companies_house import CompaniesHouseProvider, normalise_company_number
from awltux.providers.http import ProviderError
from awltux.providers.yahoo import YahooProvider
from awltux.scheduler import progress

logger = logging.getLogger(__name__)

#: This job's registry id, used to key the blockers it records.
JOB = "fundamentals"

#: The other job this module serves: `resolve_uk_companies` is the `uk_companies` job's
#: whole body, so a blocker it records under `JOB` would be attributed to the wrong job
#: and reported by the attention check as `fundamentals` failing to do something it
#: never attempted.
UK_JOB = "uk_companies"

#: Yahoo ``income_stmt`` / ``balance_sheet`` / ``cashflow`` row labels mapped onto
#: canonical keys. Order matters: the first label present wins, and later entries
#: act as fallbacks for the different names Yahoo uses between sectors.
#:
#: **Prefer the specific label to the combined one.** Yahoo publishes both
#: "Goodwill" and "Goodwill And Other Intangible Assets", and both "Long Term
#: Debt" and "Long Term Debt And Capital Lease Obligation". Mapping the combined
#: figure onto the narrow key would silently inflate every marker built on it, so
#: the narrow key only ever reads the narrow label and stays missing otherwise.
STATEMENT_LABELS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "TotalRevenue", "Operating Revenue"),
    "cost_of_goods_sold": ("Cost Of Revenue", "Reconciled Cost Of Revenue", "Cost Of Goods Sold"),
    "gross_profit": ("Gross Profit", "GrossProfit"),
    "research_and_development": ("Research And Development",),
    "sga_expense": ("Selling General And Administration", "Selling General And Administrative"),
    "operating_income": ("Operating Income", "EBIT", "Total Operating Income As Reported"),
    "ebit": ("EBIT",),
    "net_income": ("Net Income", "Net Income Common Stockholders", "NetIncome"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "depreciation_amortisation": (
        "Reconciled Depreciation",
        "Depreciation And Amortization",
        "Depreciation",
    ),
    "interest_expense": ("Interest Expense", "Interest Expense Non Operating"),
    "pretax_income": ("Pretax Income", "Pre Tax Income"),
    "tax_expense": ("Tax Provision",),
    "eps_diluted": ("Diluted EPS", "Basic EPS"),
    "dividend_per_share": ("Common Stock Dividend", "Dividend Per Share"),
    "cash_and_equivalents": (
        "Cash And Cash Equivalents",
        "Cash Cash Equivalents And Short Term Investments",
    ),
    "receivables": ("Receivables", "Accounts Receivable", "Gross Accounts Receivable"),
    "inventory": ("Inventory",),
    "current_assets": ("Current Assets",),
    "net_ppe": ("Net PPE", "Net Property Plant And Equipment"),
    "goodwill": ("Goodwill",),
    "intangible_assets": ("Other Intangible Assets", "Net Intangible Assets"),
    "total_assets": ("Total Assets",),
    "payables": ("Payables", "Payables And Accrued Expenses", "Accounts Payable"),
    "short_term_debt": ("Current Debt", "Current Debt And Capital Lease Obligation"),
    "current_liabilities": ("Current Liabilities",),
    "long_term_debt": ("Long Term Debt", "Long Term Debt And Capital Lease Obligation"),
    "lease_liabilities": ("Capital Lease Obligations",),
    "total_debt": ("Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"),
    "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liabilities"),
    "retained_earnings": ("Retained Earnings",),
    "total_equity": (
        "Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ),
    "shares_outstanding": ("Ordinary Shares Number", "Share Issued"),
    "stock_based_compensation": ("Stock Based Compensation",),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure", "Capital Expenditures"),
    "free_cash_flow": ("Free Cash Flow",),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
}

#: ``info`` fields mapped onto canonical keys, used when statements are thin.
INFO_FIELDS: dict[str, str] = {
    "revenue": "totalRevenue",
    "ebitda": "ebitda",
    "eps_diluted": "trailingEps",
    "total_debt": "totalDebt",
    "cash_and_equivalents": "totalCash",
    "free_cash_flow": "freeCashflow",
    "operating_cash_flow": "operatingCashflow",
    "shares_outstanding": "sharesOutstanding",
    "dividend_per_share": "trailingAnnualDividendRate",
}


@dataclass(slots=True)
class FundamentalsReport:
    tickers_attempted: int = 0
    periods_written: int = 0
    profile_only: int = 0
    failures: list[str] = field(default_factory=list)
    derived: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "tickers_attempted": self.tickers_attempted,
            "periods_written": self.periods_written,
            "profile_only": self.profile_only,
            "failures": self.failures[:25],
            "failure_count": len(self.failures),
        }


def _pick(row_map: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    """The first candidate label that carries a finite number, or ``None``.

    An absent label and an unparseable one are both skipped rather than ending the
    search, which is the whole point: a provider renaming one column should fall
    through to the next spelling, not report the metric as missing.
    """
    for label in candidates:
        number = as_finite_float(row_map.get(label))
        if number is not None:
            return number
    return None


def metrics_from_statements(financials: dict[str, Any], column_index: int) -> dict[str, float]:
    """Extract canonical metrics for one reporting period.

    ``column_index`` selects the period: 0 is the most recent, which is the
    convention Yahoo uses for the columns of its statement frames.
    """
    merged = _merged_rows(financials, column_index)

    metrics: dict[str, float] = {}
    for key, labels in STATEMENT_LABELS.items():
        value = _pick(merged, labels)
        if value is not None:
            metrics[key] = value

    # Outflows are stored as positive magnitudes, because `analysis/ledger.py` subtracts
    # them and `free_cash_flow` is `operating_cash_flow - capex`. Yahoo reports them with
    # the provider's own sign, which for dividends is a *credit*.
    #
    # This used to normalise `capex` alone -- it was the one that a check happened to
    # trip over -- and `dividends_paid` was left with Yahoo's sign. Measured 2026-10-07:
    # 16 periods stored it negative against XBRL's 1, and the retained-earnings
    # roll-forward came out wrong by exactly twice the dividend.
    for key in OUTFLOW_METRICS:
        if key in metrics and metrics[key] < 0:
            metrics[key] = abs(metrics[key])

    return metrics


#: Which statement of *ours* each of Yahoo's three frames feeds.
YAHOO_STATEMENTS: tuple[tuple[str, str], ...] = (
    ("income", "profit_and_loss"),
    ("balance", "balance_sheet"),
    ("cashflow", "cash_flow"),
)

#: A row label reduced to a stable key for a line no canonical metric claims.
#:
#: A provider's caption is the only identity such a line has -- there is no tag here, which is
#: exactly why a period built from a Yahoo statement could not offer one -- so the key is the
#: caption, slugged. It is stable across years because the caption is, and it cannot collide with
#: a canonical key (those have no colon), the same argument `analysis/corrections.Line` makes for a
#: taxonomy tag.
SOURCE_KEY_PREFIX = "src:"


def source_key(label: str) -> str:
    """The key a source's own caption is stored under."""
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return f"{SOURCE_KEY_PREFIX}{slug}"


def source_lines(
    financials: dict[str, Any], column_index: int
) -> dict[str, list[dict[str, Any]]]:
    """The figures a source states that no canonical metric claims, by statement.

    **Kept because the alternative is a vocabulary.** Asked for after working through `JELl_EQ`:
    *"It appears each company can use their own terminology and accounting practices ... it is
    difficult to construct accounts from just the prescribed titles."* `STATEMENT_LABELS` is that
    prescribed vocabulary, and everything not in it was discarded at ingest -- including the
    38,688,000 that Jersey Electricity's operating expense actually is, which is why the accounts
    page showed that section out by 26,867,000 with no way to fix it from the page.

    What is kept is deliberately narrow: a label with a non-zero finite figure that no canonical
    key reads. A stated zero is dropped because it is rarely a line worth adding and there are
    many of them, and a label a key already reads is dropped because the chart has that line
    already -- offering it twice is how one figure gets counted in two places.

    Nothing here is *presented*: a stored caption is a figure the page can offer, and the reader
    decides where it goes. That is the whole point -- the same caption means different things to
    different filers, and to the same filer in different years.
    """
    claimed = {
        label
        for labels in STATEMENT_LABELS.values()
        for label in labels
    }
    out: dict[str, list[dict[str, Any]]] = {}
    for section, statement in YAHOO_STATEMENTS:
        rows = (financials.get(section) or {}).get("rows") or {}
        found: list[dict[str, Any]] = []
        for label, values in rows.items():
            if label in claimed:
                continue
            if not isinstance(values, list) or column_index >= len(values):
                continue
            value = as_finite_float(values[column_index])
            if value is None or value == 0:
                continue
            found.append(
                {"label": str(label), "key": source_key(str(label)), "value": value}
            )
        if found:
            out[statement] = found
    return out


def _merged_rows(financials: dict[str, Any], column_index: int) -> dict[str, Any]:
    """Every row of every statement for one period, in one label space.

    Yahoo names its three frames separately but a caption can appear in more than one, and the
    first frame wins -- which is deliberate for a label that means the same thing in both, and is
    also how a *cash flow* caption came to fill a profit and loss line: `Depreciation And
    Amortization` is stated on Jersey Electricity's cash flow and reached
    `depreciation_amortisation` through here. That is why a line's figure is not the same question
    as where the line is presented -- see `analysis/layout.py`.
    """
    merged: dict[str, Any] = {}
    for section in ("income", "balance", "cashflow"):
        block = financials.get(section) or {}
        rows = block.get("rows") or {}
        for label, values in rows.items():
            if label in merged:
                continue  # an earlier section wins; balance sheet labels are unique
            if isinstance(values, list) and column_index < len(values):
                merged[label] = values[column_index]
    return merged


def metrics_from_info(info: dict[str, Any]) -> dict[str, float]:
    """Fallback metrics from the ``info`` payload, for thin statement coverage."""
    metrics: dict[str, float] = {}
    for canonical_key, provider_key in INFO_FIELDS.items():
        value = info.get(provider_key)
        if value is None:
            continue
        try:
            metrics[canonical_key] = float(value)
        except (TypeError, ValueError):
            continue
    return metrics


def derive_metrics(metrics: dict[str, float]) -> dict[str, float]:
    """Compute the ratios the analysis layer needs but no provider supplies.

    Derived values are recomputed here rather than trusted from a provider, so
    the sign conventions are ours and are applied consistently across taxonomies.

    One named helper per family rather than one long sequence. Each ``_..._ratios``
    helper names what it measures, guards its own preconditions, and returns only
    what it could compute -- so a provider that publishes revenue but no balance
    sheet yields margins and nothing else, without a branch in a caller.
    """
    derived: dict[str, float] = {}
    for compute in (
        _margin_ratios,
        _leverage_ratios,
        _return_ratios,
        _per_share_ratios,
        _cash_flow_ratios,
        _income_bridges,
    ):
        derived.update(compute(metrics))
    return derived


def _margin_ratios(metrics: dict[str, float]) -> dict[str, float]:
    """Profit as a share of revenue. Silent when revenue is absent or non-positive."""
    revenue = metrics.get("revenue")
    if not revenue or revenue <= 0:
        return {}

    return {
        key: value / revenue
        for key, source in (
            ("gross_margin", "gross_profit"),
            ("operating_margin", "operating_income"),
            ("net_margin", "net_income"),
            ("ebitda_margin", "ebitda"),
        )
        if (value := metrics.get(source)) is not None
    }


def _leverage_ratios(metrics: dict[str, float]) -> dict[str, float]:
    """How the capital is financed, and whether the interest on it is covered."""
    derived: dict[str, float] = {}

    debt = metrics.get("total_debt")
    if debt is not None:
        cash = metrics.get("cash_and_equivalents") or 0.0
        derived["net_debt"] = debt - cash

    equity = metrics.get("total_equity")
    if equity and equity > 0 and "total_liabilities" in metrics:
        derived["debt_to_equity"] = metrics["total_liabilities"] / equity
    elif equity and equity > 0 and debt is not None:
        derived["debt_to_equity"] = debt / equity

    interest = metrics.get("interest_expense")
    operating = metrics.get("operating_income")
    if interest and interest > 0 and operating is not None:
        derived["interest_cover"] = operating / interest

    return derived


def _return_ratios(metrics: dict[str, float]) -> dict[str, float]:
    """What the capital earned, against the three bases a reader might compare."""
    derived: dict[str, float] = {}

    equity = metrics.get("total_equity")
    net_income = metrics.get("net_income")

    if equity and equity > 0 and net_income is not None:
        derived["roe"] = net_income / equity

    total_assets = metrics.get("total_assets")
    if total_assets and net_income is not None:
        derived["roa"] = net_income / total_assets

    # ROCE uses operating profit over capital employed -- the measure that
    # survives differences in how a company is financed.
    debt = metrics.get("total_debt")
    capital_employed = None
    if equity is not None and debt is not None:
        capital_employed = equity + debt
    elif total_assets is not None:
        current_liabilities = metrics.get("current_liabilities")
        capital_employed = (
            total_assets - current_liabilities
            if current_liabilities is not None
            else total_assets
        )

    operating = metrics.get("operating_income")
    if capital_employed and capital_employed > 0 and operating is not None:
        derived["roce"] = operating / capital_employed

    return derived


def _per_share_ratios(metrics: dict[str, float]) -> dict[str, float]:
    """The share of earnings paid out, which only exists against a positive EPS."""
    eps = metrics.get("eps_diluted")
    dividend = metrics.get("dividend_per_share")
    if eps and eps > 0 and dividend is not None:
        return {"payout_ratio": dividend / eps}
    return {}


def _cash_flow_ratios(metrics: dict[str, float]) -> dict[str, float]:
    """Free cash flow is an identity, not a disclosure.

    Providers publish it for large caps and omit it for most others, and where they
    omit it we can still state it from two figures they do publish. Only filled when
    absent, so a provider's own definition is never overwritten by ours.
    """
    if metrics.get("free_cash_flow") is not None:
        return {}

    operating_cash = metrics.get("operating_cash_flow")
    capex = metrics.get("capex")
    if operating_cash is not None and capex is not None:
        return {"free_cash_flow": operating_cash - capex}
    return {}


def _income_bridges(metrics: dict[str, float]) -> dict[str, float]:
    """EBIT, stated by an identity when no provider publishes it.

    ``free_cash_flow`` above is the same shape, and this one is measured rather than
    assumed: on the live database **0 of 88 stored periods carry a stated ``ebit``**,
    against 89% carrying ``pretax_income``, 75% ``operating_income`` and 60%
    ``interest_expense``. The metric is in the extraction vocabulary because
    ``awltux/metrics.py`` records what consumes it -- "NOPAT and Altman Z''" -- and a
    name no provider ever populates leaves both of those permanently uncomputable.

    Two routes, in the order of how well each answers the question:

    * ``pretax_income + interest_expense`` is the identity, and the only route that
      stays right when there is non-operating income.
    * ``operating_income`` is the fallback, and it is an **approximation**: the same
      metric note records that the two are "distinct from operating income when there
      is non-operating income". It is used anyway because it is the difference
      between EBIT existing for three quarters of filers and for half of them.

    Only filled when absent, so a provider that does state EBIT is never overwritten.
    """
    if metrics.get("ebit") is not None:
        return {}

    pretax = metrics.get("pretax_income")
    interest = metrics.get("interest_expense")
    if pretax is not None and interest is not None:
        return {"ebit": pretax + interest}

    operating = metrics.get("operating_income")
    if operating is not None:
        return {"ebit": operating}
    return {}


def sync_fundamentals(
    session: Session,
    *,
    tickers: list[str] | None = None,
    settings: Settings | None = None,
    provider: YahooProvider | None = None,
    limit: int | None = None,
) -> FundamentalsReport:
    """Refresh fundamentals for universe instruments.

    Statements and the ``info`` profile are fetched separately and failures are
    tolerated independently: a company whose profile is unavailable may still
    have usable statements, and vice versa.

    **The queue drains because an attempt is stamped, not a success.** It used to order on
    ``Instrument.updated_at``, which this job only bumps when it writes something -- so an
    instrument the provider refuses kept its old timestamp, led the next run's queue as well,
    and consumed the whole ration. Measured 2026-10-24: seven consecutive runs over seventeen
    hours attempting `CYBAl_EQ` and `HGENl_EQ` and writing nothing, while 323 of the 506
    in-universe instruments had no accounts. `fundamentals_checked_at` is stamped at the start
    of an attempt, so every instrument is reached once per pass and a permanently unfetchable
    one waits its turn; the blocker row keeps the failure visible meanwhile.
    """
    settings = settings or get_settings()
    provider = provider or YahooProvider(settings)
    report = FundamentalsReport()

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.yahoo_symbol.is_not(None))
        # Never checked first, then least recently checked: a rationed refresh that rotates
        # fairly, keyed on work *this* job did.
        .order_by(
            Instrument.fundamentals_checked_at.asc().nullsfirst(),
            Instrument.t212_ticker.asc(),
        )
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    else:
        # A sweep skips instruments a scoped refresh holds. See `ingest/lease.py`.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    if limit:
        statement = statement.limit(limit)

    instruments = session.execute(statement).scalars().all()

    total = len(instruments)
    for position, instrument in enumerate(instruments, start=1):
        report.tickers_attempted += 1
        progress.note(f"{position} of {total}: {instrument.t212_ticker}")
        # Stamped before the calls, because it records that this instrument was *asked about*.
        # A refusal below writes nothing else to the row, which is exactly how the queue used to
        # stall: see the function's docstring.
        instrument.fundamentals_checked_at = utcnow()
        _sync_one(session, instrument, provider, report)

    logger.info("fundamentals sync: %s", report.as_dict())
    return report


def _sync_one(
    session: Session,
    instrument: Instrument,
    provider: YahooProvider,
    report: FundamentalsReport,
) -> None:
    """One instrument's profile and statements, with the failure recorded rather than raised.

    The named step the loop body was: a company whose profile is unavailable may still have
    usable statements, so the two calls fail independently and the run continues either way.
    """
    symbol = instrument.yahoo_symbol
    assert symbol is not None

    _sync_profile(session, instrument, provider, report)

    try:
        financials = provider.get_financials(symbol)
    except ProviderError as exc:
        report.failures.append(f"{instrument.t212_ticker}: {exc}")
        # The provider refused, so this instrument's statements cannot be had from here.
        # Recorded as a blocker as well as a failure: the report's list is for the run's log
        # and expires with it, and the dashboard's attention filter needs to outlive the run.
        record_blocker(
            session,
            instrument.t212_ticker,
            job=JOB,
            stage="statements",
            reason=str(exc),
        )
        session.flush()
        return

    columns = (financials.get("income") or {}).get("columns") or []
    # One period per column; income statement columns define the set.
    for index, period_end in enumerate(columns[:5]):
        metrics = metrics_from_statements(financials, index)
        if not metrics:
            continue
        metrics.update(derive_metrics(metrics))
        _upsert_period(
            session,
            instrument,
            period_end=_parse_period_end(period_end),
            period_type="annual",
            metrics=metrics,
            source="yahoo_statements",
            confidence=0.7,
            # The captions no canonical metric reads, kept so the accounts page can offer them
            # as lines. See `source_lines`: without this, a figure the source states and this
            # project's vocabulary lacks is not merely unplaced, it is unrecorded.
            presentation=source_lines(financials, index),
        )
        report.periods_written += 1
    # Statements arrived, so whatever was recorded against this step is stale.
    clear_blocker(session, instrument.t212_ticker, job=JOB, stage="statements")
    session.flush()
    # Two provider calls per instrument, so the write lock is released between them rather than
    # held across the whole run.
    release_write_lock(session)


def _sync_profile(
    session: Session, instrument: Instrument, provider: YahooProvider, report: FundamentalsReport
) -> None:
    """Fetch and apply profile fields, plus fallback metrics when statements fail."""
    symbol = instrument.yahoo_symbol
    if not symbol:
        return
    try:
        info = provider.get_profile(symbol)
    except ProviderError:
        return

    if not info:
        return

    report.profile_only += 1
    if info.get("sector") and not instrument.sector:
        instrument.sector = str(info["sector"])
        instrument.sector_source = "yahoo"
        # Yahoo gives a GICS name rather than a code, and `sectors.group_for` reads it
        # through the alias table -- "Basic Materials" becomes Materials. Assigned here
        # too because a sector page grouped by a value nothing filled in is a page that
        # silently excludes the instrument.
        assign(instrument)
    if info.get("industry") and not instrument.industry:
        instrument.industry = str(info["industry"])
    if info.get("longBusinessSummary") and not instrument.business_summary:
        # Kept as the provider wrote it. Nothing parses this: it is the hover hint on the
        # recommendations table, and the first description held wins, as with the sector and
        # industry above -- a company's account of what it does changes rarely, so rewriting
        # it on every rotation would churn the row for the same words.
        instrument.business_summary = str(info["longBusinessSummary"])
    if info.get("marketCap"):
        with contextlib.suppress(TypeError, ValueError):
            instrument.market_cap = float(info["marketCap"])

    metrics = metrics_from_info(info)
    if not metrics:
        return
    metrics.update(derive_metrics(metrics))
    _upsert_period(
        session,
        instrument,
        period_end=utcnow().date(),
        period_type="ttm",
        metrics=metrics,
        source="yahoo_info",
        # Profile-sourced figures are a snapshot, not a filed statement.
        confidence=0.5,
    )
    session.flush()


def _parse_period_end(value: Any):
    import datetime as dt

    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _upsert_period(
    session: Session,
    instrument: Instrument,
    *,
    period_end,
    period_type: str,
    metrics: dict[str, float],
    source: str,
    confidence: float,
    metric_sources: dict[str, Any] | None = None,
    presentation: dict[str, Any] | None = None,
    filing_id: int | None = None,
) -> FundamentalPeriod | None:
    if period_end is None:
        return None

    row = session.execute(
        select(FundamentalPeriod)
        .where(FundamentalPeriod.instrument_t212_ticker == instrument.t212_ticker)
        .where(FundamentalPeriod.period_end == period_end)
        .where(FundamentalPeriod.period_type == period_type)
        .where(FundamentalPeriod.source == source)
        .limit(1)
    ).scalar_one_or_none()

    if row is None:
        row = FundamentalPeriod(
            instrument_t212_ticker=instrument.t212_ticker,
            period_end=period_end,
            period_type=period_type,
            source=source,
        )
        session.add(row)

    # The document these figures were read out of, when the writer read one. It is what lets
    # the accounts page's SOURCE link the filing itself rather than the provider it came
    # through (`web/sources.py`), and until 2026-10-23 nothing populated this column: measured,
    # 0 of 824 stored periods carried one.
    #
    # Assigned only by the writer that knows a document, so a later provider re-derive of the
    # same period cannot clear a filing written by an extraction -- and it overwrites when the
    # *same* extraction is re-run over a different document, because then it is the document
    # this row was last read from.
    if filing_id is not None:
        row.filing_id = filing_id

    # Preserve any metric an LLM extractor sourced from the filed document: a
    # figure with a citation beats a scraped snapshot of the same figure.
    if row.metric_sources:
        for key, provenance in row.metric_sources.items():
            if isinstance(provenance, dict) and provenance.get("source") == "llm_extraction":
                metrics.pop(key, None)

    row.metrics = metrics
    row.currency = instrument.currency_code
    row.confidence = confidence
    row.as_of = utcnow()
    if metric_sources is not None:
        row.metric_sources = metric_sources
    # The source's own captions are *about* this period's payload, so a re-derive of the same
    # period replaces them the same way it replaces the figures: leaving a caption behind that the
    # provider no longer states is a line the page offers and nothing can fill.
    if presentation is not None:
        row.presentation = presentation

    # **And a correction outlives the re-derive that reproduces the row.** The write above
    # replaces every figure with what the payload says, which is what this function is for --
    # but a line a reader removed, or a value they put back by hand, is a statement about the
    # filing that the payload does not contain. Re-applied here rather than in each caller so
    # every writer gets it: the four `_upsert_period` call sites are the only way a period's
    # figures are ever rewritten.
    #
    # Only when there is something to apply: a row nobody has corrected is left exactly as its
    # writer made it, derived ratios included, because a provider's own margins are not ours to
    # overwrite. The filer rules are read whatever happens, so a rule recorded after a period
    # was last written still reaches it the next time that period is.
    from awltux.analysis import corrections as corrections_module

    # The same key the pages write (`corrections.filer_key`), or a rule recorded against an
    # instrument with no SEC CIK would never reach the row it was made for.
    rules = corrections_module.load_filer(
        session,
        corrections_module.filer_key(cik=instrument.sec_cik, ticker=instrument.t212_ticker),
    )
    if row.corrections or rules:
        corrections_module.apply_to_row(row, rules)
    return row


# --------------------------------------------------------------------------- #
# UK entity resolution (Companies House)
# --------------------------------------------------------------------------- #

#: Legal-form suffixes and noise stripped before comparing company names.
_NAME_NOISE = re.compile(
    r"\b(public limited company|plc|p\.l\.c|ltd|limited|holdings?|group|"
    r"the|company|co|inc|corporation|corp)\b",
    re.IGNORECASE,
)

#: Entity types a **listed** share cannot be, so a name match on one is a namesake.
#:
#: The reason this is a refusal rather than a penalty: measured 2026-10-25 on the live database,
#: **44 of the 115 stored company numbers did not name the listed issuer** and 40 of those were
#: private limited companies -- `CLAl_EQ` (Celsius Resources) held the number for `CELSIUS LTD`, a
#: micro-entity filing £21,766 of net assets, and `SUSl_EQ` (S&U) held `S&U DISTRIBUTION LTD`, its
#: own subsidiary. A private company cannot be listed, so its accounts and its filings are not the
#: instrument's whatever the names look like.
#:
#: Overseas entities and limited partnerships are **not** here and must not be: `PFCl_EQ`
#: (Petrofac) is `FC042865 PETROFAC LIMITED`, an oversea-company, and `GRXl_EQ` (GreenX Metals) is
#: `OE020671`, a registered overseas entity -- both are the listed issuer, and neither is a plc.
PRIVATE_ENTITY_TYPES = frozenset(
    {
        "ltd",
        "private-limited-guarant-nsc",
        "private-limited-guarant-nsc-limited-exemption",
        "private-limited-shares-section-30-exemption",
        "private-unlimited",
        "private-unlimited-nsc",
    }
)

#: Company statuses that mean the record is no longer the live issuer.
#:
#: ``dissolved`` is the one that caught a real case: `TMGl_EQ` (Mission) was matched to
#: `MISSION LTD`, dissolved since 2015. ``administration`` and ``liquidation`` are deliberately
#: absent -- `PFCl_EQ`'s Petrofac is in administration and is still the company whose accounts a
#: reader wants.
INELIGIBLE_STATUSES = frozenset({"dissolved", "converted-closed"})

#: How good a match has to be before a company number is written.
#:
#: Only an **exact normalised name match** clears this (0.9); a partial or token-overlap match is
#: 0.5 and below. The threshold is named because the caller used to write every match it was
#: given: `match_company`'s own docstring said a weak match "can be recorded for human review
#: without being acted on", and `resolve_uk_companies` acted on all of them.
MIN_MATCH_CONFIDENCE = 0.8

#: How alike two names must be for the *repair* to keep a stored number.
#:
#: Looser than the matcher on purpose, and the cases that set it are real instruments measured
#: 2026-10-25: `RNEWl_EQ` is "Ecofin US Renewables Infrastructure Trust" against the register's
#: "ECOFIN U.S. RENEWABLES INFRASTRUCTURE TRUST PLC" (a dotted initial), and `YNGAl_EQ` is
#: "Young & Co's Brewery (Class A)" against "YOUNG & CO'S BREWERY PLC" (a share class). Neither is a
#: different company. A different *fund* is, and overlaps on only its sector words: Macau Property
#: Opportunities against Threadneedle UK Opportunities Property Fund scores 0.4.
NAME_TOKEN_MATCH = 0.8


def normalise_company_name(name: str) -> str:
    """Reduce a company name to a comparable form."""
    cleaned = _NAME_NOISE.sub(" ", name.lower())
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def same_issuer_name(instrument_name: str, register_name: str) -> bool:
    """Whether two names are the same issuer, allowing for the ways a listed name varies.

    A share-class suffix, a dotted initial and a punctuation difference are not a different
    company; a different fund is. Compared with spaces removed first, then by word overlap.
    """
    left = normalise_company_name(instrument_name)
    right = normalise_company_name(register_name)
    flat_left = left.replace(" ", "")
    flat_right = right.replace(" ", "")
    if not flat_left or not flat_right:
        return False
    if flat_left == flat_right or flat_left in flat_right or flat_right in flat_left:
        return True
    return _token_overlap(left, right) >= NAME_TOKEN_MATCH


def entity_type(candidate: dict[str, Any]) -> str:
    """A Companies House search result's entity type, lower-cased.

    ``company_type`` in search results, ``type`` in the company profile. Normalised here so the
    matcher and the repair cannot disagree about which field means what.
    """
    value = candidate.get("company_type") or candidate.get("type") or ""
    return str(value).strip().lower()


def listed_entity_problem(candidate: dict[str, Any]) -> str:
    """Why this candidate cannot be a listed share, or ``""`` when nothing rules it out.

    Returns a sentence rather than a bool so the caller can put the reason in the blocker a reader
    sees -- "we did not attach this number" is useless without "because it is a private company".
    """
    kind = entity_type(candidate)
    status = str(candidate.get("company_status") or candidate.get("status") or "").strip().lower()
    if kind in PRIVATE_ENTITY_TYPES:
        return f"it is a {kind.replace('-', ' ')} company, which cannot be listed"
    if status in INELIGIBLE_STATUSES:
        return f"it is {status}"
    if not kind:
        # The API always sends the type on a search result. A candidate without one cannot be
        # checked, and "unknown" is exactly how a namesake gets attached.
        return "the register states no entity type, so it cannot be told from a namesake"
    return ""


@dataclass(frozen=True, slots=True)
class CompanyMatch:
    company_number: str
    company_name: str
    confidence: float
    method: str
    status: str | None = None


def match_company(
    instrument: Instrument, candidates: list[dict[str, Any]]
) -> CompanyMatch | None:
    """Score Companies House search results against an instrument.

    Only an **exact normalised name match** is treated as dependable (0.9). Anything weaker is
    returned at 0.5 or below so it can be recorded for human review; only :func:`match_company`'s
    caller decides whether to write it, and it writes nothing below
    :data:`MIN_MATCH_CONFIDENCE` -- attaching the wrong company's accounts to a ticker produces
    confident, completely wrong analysis.

    **A candidate that cannot be a listed share is not a candidate at all.** See
    :data:`PRIVATE_ENTITY_TYPES` for the measurement: 40 of the 115 stored numbers named a private
    limited company, and the name often does not say so ("CELSIUS LTD" for Celsius Resources,
    "S&U DISTRIBUTION LTD" for S&U). Eligibility is checked before the name, because a perfect name
    match on a private company is exactly the failure.
    """
    target = normalise_company_name(instrument.name)
    if not target:
        return None

    best: CompanyMatch | None = None
    for candidate in candidates:
        if listed_entity_problem(candidate):
            continue
        raw_name = str(candidate.get("title") or candidate.get("company_name") or "")
        number = normalise_company_number(candidate.get("company_number"))
        if not number:
            continue
        status = str(candidate.get("company_status") or candidate.get("status") or "")
        matched = normalise_company_name(raw_name)

        if matched == target:
            confidence = 0.9
            method = "exact_name"
        elif matched and (matched in target or target in matched):
            confidence = 0.5
            method = "partial_name"
        else:
            overlap = _token_overlap(target, matched)
            if overlap < 0.6:
                continue
            confidence = 0.4
            method = "token_overlap"

        if best is None or confidence > best.confidence:
            best = CompanyMatch(
                company_number=number,
                company_name=raw_name,
                confidence=confidence,
                method=method,
                status=status or None,
            )

    return best


def _token_overlap(a: str, b: str) -> float:
    left, right = set(a.split()), set(b.split())
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def resolve_uk_companies(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: CompaniesHouseProvider | None = None,
    tickers: list[str] | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Attach Companies House company numbers to UK-listed instruments.

    ``tickers`` scopes it to named instruments, for a one-instrument refresh. The filter
    is applied to the selection rather than after it, so a scoped run of a US listing
    reports nothing attempted rather than spending a request to find out it is not a UK
    company.
    """
    from awltux.ingest.symbols import uk_listing_predicate

    settings = settings or get_settings()
    provider = provider or CompaniesHouseProvider(settings)
    if not provider.configured:
        return {"skipped": "AWLTUX_COMPANIES_HOUSE_API_KEY is not set"}

    # The UK restriction is in the *query*, not applied afterwards. Filtering in Python
    # spent the limit on instruments about to be discarded: a run selected 50 of 18,488
    # unresolved rows, kept the 11 UK ones among them, and -- because nothing is written
    # when nothing matches -- selected the same 11 every time. Measured 2026-10-07: eight
    # consecutive runs with `matched=0`, and 107 of the universe's 118 UK listings never
    # attempted at all.
    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.ch_company_number.is_(None))
        .where(uk_listing_predicate(Instrument.exchange_name, Instrument.yahoo_symbol))
        # Deterministic, so "which fifty" is answerable and the walk advances in a
        # stated order rather than in whatever rowid order SQLite returns.
        .order_by(Instrument.t212_ticker)
    )
    if tickers is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(tickers)))
    else:
        # A sweep skips instruments a scoped refresh holds. See `ingest/lease.py`.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    if limit:
        statement = statement.limit(limit)
    instruments = list(session.execute(statement).scalars().all())

    summary: dict[str, Any] = {
        "attempted": len(instruments),
        "matched": 0,
        "candidates": 0,
        "unmatched": 0,
    }
    for position, instrument in enumerate(instruments, start=1):
        progress.note(f"{position} of {len(instruments)}: {instrument.t212_ticker}")
        _resolve_one(session, instrument, provider, summary)

    session.flush()
    logger.info("UK company resolution: %s", summary)
    return summary


def _resolve_one(
    session: Session,
    instrument: Instrument,
    provider: CompaniesHouseProvider,
    summary: dict[str, Any],
) -> None:
    """Search, match and attach one instrument's company number -- or say why not.

    The named step the loop body was. Three outcomes and none of them is silent: a **match** at or
    above :data:`MIN_MATCH_CONFIDENCE` is written with its alias, a **candidate** below it is
    recorded with its score, and **nothing** matching is recorded with the count searched.
    """
    try:
        candidates = provider.search_companies(instrument.name)
    except ProviderError as exc:
        logger.debug("CH search failed for %s: %s", instrument.name, exc)
        # The level-2 reason for a UK listing used to be "no Companies House number", which is the
        # *symptom*: this says which company could not be matched and why, and outlives the run.
        record_blocker(
            session,
            instrument.t212_ticker,
            job=UK_JOB,
            stage="company_number",
            reason=str(exc),
        )
        return

    match = match_company(instrument, candidates)
    if match is None:
        summary["unmatched"] += 1
        record_blocker(
            session,
            instrument.t212_ticker,
            job=UK_JOB,
            stage="company_number",
            reason=(
                f'no Companies House record matched "{instrument.name}" '
                f"({len(candidates)} candidate(s) searched, none of them an entity that can be "
                "listed)"
            ),
        )
        return

    # **A candidate is not a resolution.** Everything below the threshold is a partial or
    # token-overlap match, and writing one is how 40 private namesakes came to be attached to
    # listed tickers: the number is then presented as this company's filings, and any accounts read
    # from it would be another company's. Recorded rather than dropped, because the best candidate
    # and its score are what a reader needs to judge the refusal.
    if match.confidence < MIN_MATCH_CONFIDENCE:
        summary["candidates"] += 1
        record_blocker(
            session,
            instrument.t212_ticker,
            job=UK_JOB,
            stage="company_number",
            reason=(
                f'no dependable Companies House match for "{instrument.name}": best candidate '
                f"{match.company_name} ({match.company_number}, {match.status or 'no status'}) "
                f"scored {match.confidence:.1f} by {match.method}, below {MIN_MATCH_CONFIDENCE}"
            ),
        )
        return

    clear_blocker(session, instrument.t212_ticker, job=UK_JOB, stage="company_number")
    instrument.ch_company_number = match.company_number
    summary["matched"] += 1
    _record_alias(session, instrument, match)

    # One Companies House search per instrument; release between them.
    release_write_lock(session)


def _record_alias(
    session: Session, instrument: Instrument, match: CompanyMatch
) -> None:
    """Keep the alias table in step with the number, unless a reader set it by hand."""
    note = f"{match.company_name} ({match.status or 'status unknown'})"
    alias = session.execute(
        select(InstrumentAlias).where(
            InstrumentAlias.instrument_t212_ticker == instrument.t212_ticker,
            InstrumentAlias.provider == "companies_house",
        )
    ).scalar_one_or_none()
    if alias is None:
        session.add(
            InstrumentAlias(
                instrument_t212_ticker=instrument.t212_ticker,
                provider="companies_house",
                symbol=match.company_number,
                confidence=match.confidence,
                method=match.method,
                is_manual=False,
                note=note,
            )
        )
    elif not alias.is_manual:
        alias.symbol = match.company_number
        alias.confidence = match.confidence
        alias.method = match.method
        alias.note = note


def _stored_number_problem(instrument: Instrument, profile: dict[str, Any]) -> str:
    """Why the number stored on this row is not the listed company, or ``""`` when it is.

    The same question the write-time gate asks, asked of what is already stored: the entity type
    first, then whether the register's name and the instrument's name are the same after
    normalisation. The name check is the one that catches a plausible legal form on the wrong
    company -- a limited partnership that is a different fund has no other tell.
    """
    problem = listed_entity_problem(profile)
    official = str(profile.get("company_name") or "")
    if not problem and not same_issuer_name(instrument.name, official):
        problem = f'the register calls it "{official}", which is not this instrument'
    return problem


def _repair_one(
    session: Session,
    instrument: Instrument,
    provider: CompaniesHouseProvider,
    report: dict[str, Any],
    *,
    dry_run: bool,
) -> None:
    """Check one stored number and clear it when the register says it is the wrong company."""
    number = instrument.ch_company_number
    assert number is not None
    report["examined"] += 1

    alias = session.execute(
        select(InstrumentAlias).where(
            InstrumentAlias.instrument_t212_ticker == instrument.t212_ticker,
            InstrumentAlias.provider == "companies_house",
        )
    ).scalar_one_or_none()
    if alias is not None and alias.is_manual:
        # A reader attached this one deliberately, and a name comparison does not overrule that.
        report["manual"].append({"ticker": instrument.t212_ticker, "number": number})
        return

    try:
        profile = provider.get_company(number)
    except ProviderError as exc:
        report["failed"].append(
            {"ticker": instrument.t212_ticker, "number": number, "reason": str(exc)[:200]}
        )
        return

    problem = _stored_number_problem(instrument, profile)
    if not problem:
        report["kept"] += 1
        return

    report["cleared"].append(
        {
            "ticker": instrument.t212_ticker,
            "instrument": instrument.name,
            "number": number,
            "registered_as": str(profile.get("company_name") or ""),
            "type": entity_type(profile),
            "status": str(profile.get("company_status") or ""),
            "reason": problem,
        }
    )
    if dry_run:
        return
    instrument.ch_company_number = None
    if alias is not None:
        session.delete(alias)
    record_blocker(
        session,
        instrument.t212_ticker,
        job=UK_JOB,
        stage="company_number",
        reason=(
            f"the stored company number {number} was cleared: {problem}. The next resolution run "
            "will look again."
        ),
    )
    session.flush()
    release_write_lock(session)


def repair_uk_company_numbers(
    session: Session,
    *,
    settings: Settings | None = None,
    provider: CompaniesHouseProvider | None = None,
    tickers: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Clear stored company numbers that name something other than the listed issuer.

    The companion to the write-time gate in :func:`resolve_uk_companies`. Numbers already on rows
    were matched by name alone and acted on whatever ``match_company`` returned, so measured
    2026-10-25 **44 of the 115 stored numbers did not name the listed company**: 40 private limited
    companies (`CELSIUS LTD` for Celsius Resources, `S&U DISTRIBUTION LTD` for S&U, `MISSION LTD`
    for Mission -- dissolved since 2015), plus a limited partnership belonging to a different fund.

    Three refusals, and each is a fact about the register rather than about the name:

    * the entity type is one a listed share cannot be (:data:`PRIVATE_ENTITY_TYPES`);
    * the company is dissolved or converted-closed (:data:`INELIGIBLE_STATUSES`);
    * the register's name and the instrument's name are **not the same** after normalisation --
      which is the check that catches a plausible legal form on the wrong company, and the only one
      that would have caught `THREADNEEDLE UK OPPORTUNITIES PROPERTY FUND` sitting on Macau
      Property Opportunities.

    A number set by hand (``InstrumentAlias.is_manual``) is left alone and reported: a reader who
    attached one deliberately is not overruled by a name comparison. ``dry_run`` reports without
    writing.

    Clearing is the honest repair rather than a re-resolution: the next ``uk_companies`` run picks
    the row up again (:func:`resolve_uk_companies` selects ``ch_company_number IS NULL``) and either
    finds a dependable match under the new rule or records why it cannot.
    """
    from awltux.ingest.symbols import uk_listing_predicate

    settings = settings or get_settings()
    provider = provider or CompaniesHouseProvider(settings)
    report: dict[str, Any] = {
        "examined": 0,
        "kept": 0,
        "cleared": [],
        "manual": [],
        "failed": [],
        "dry_run": dry_run,
    }
    if not provider.configured:
        report["skipped"] = "AWLTUX_COMPANIES_HOUSE_API_KEY is not set"
        return report

    statement = (
        select(Instrument)
        .where(Instrument.ch_company_number.is_not(None))
        .where(uk_listing_predicate(Instrument.exchange_name, Instrument.yahoo_symbol))
        .order_by(Instrument.t212_ticker)
    )
    if tickers is not None:
        statement = statement.where(Instrument.t212_ticker.in_(list(tickers)))
    instruments = list(session.execute(statement).scalars().all())

    for position, instrument in enumerate(instruments, start=1):
        progress.checkpoint(f"{position} of {len(instruments)}: {instrument.t212_ticker}")
        _repair_one(session, instrument, provider, report, dry_run=dry_run)

    if not dry_run:
        session.flush()
    logger.info("UK company number repair: %s", {k: v for k, v in report.items() if k != "cleared"})
    return report
