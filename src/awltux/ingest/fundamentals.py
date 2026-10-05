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

from awltux.config import Settings, get_settings
from awltux.db import FundamentalPeriod, Instrument, InstrumentAlias, utcnow
from awltux.providers.companies_house import CompaniesHouseProvider, normalise_company_number
from awltux.providers.http import ProviderError
from awltux.providers.yahoo import YahooProvider

logger = logging.getLogger(__name__)

#: Canonical metric keys. Adding one here is a deliberate act: the valuation
#: model reads these names, so a typo becomes a silently missing input.
CANONICAL_METRICS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "ebitda",
    "eps_diluted",
    "total_assets",
    "total_liabilities",
    "total_equity",
    "total_debt",
    "cash_and_equivalents",
    "net_debt",
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "dividends_paid",
    "shares_outstanding",
    "dividend_per_share",
)

#: Yahoo ``income_stmt`` / ``balance_sheet`` / ``cashflow`` row labels mapped onto
#: canonical keys. Order matters: the first label present wins, and later entries
#: act as fallbacks for the different names Yahoo uses between sectors.
STATEMENT_LABELS: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "TotalRevenue", "Operating Revenue"),
    "gross_profit": ("Gross Profit", "GrossProfit"),
    "operating_income": ("Operating Income", "EBIT", "Total Operating Income As Reported"),
    "net_income": ("Net Income", "Net Income Common Stockholders", "NetIncome"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "eps_diluted": ("Diluted EPS", "Basic EPS"),
    "total_assets": ("Total Assets",),
    "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liabilities"),
    "total_equity": (
        "Stockholders Equity",
        "Total Equity Gross Minority Interest",
        "Common Stock Equity",
    ),
    "total_debt": ("Total Debt", "Long Term Debt And Capital Lease Obligation", "Long Term Debt"),
    "cash_and_equivalents": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure", "Capital Expenditures"),
    "free_cash_flow": ("Free Cash Flow",),
    "dividends_paid": ("Cash Dividends Paid", "Common Stock Dividend Paid"),
    "shares_outstanding": ("Ordinary Shares Number", "Share Issued"),
    "dividend_per_share": ("Common Stock Dividend", "Dividend Per Share"),
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
    for label in candidates:
        value = row_map.get(label)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number != number:  # NaN
            continue
        return number
    return None


def metrics_from_statements(financials: dict[str, Any], column_index: int) -> dict[str, float]:
    """Extract canonical metrics for one reporting period.

    ``column_index`` selects the period: 0 is the most recent, which is the
    convention Yahoo uses for the columns of its statement frames.
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

    metrics: dict[str, float] = {}
    for key, labels in STATEMENT_LABELS.items():
        value = _pick(merged, labels)
        if value is not None:
            metrics[key] = value

    # Capex is reported negatively by Yahoo; normalise to a positive outflow.
    if "capex" in metrics and metrics["capex"] < 0:
        metrics["capex"] = abs(metrics["capex"])

    return metrics


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
    """
    derived: dict[str, float] = {}

    revenue = metrics.get("revenue")
    if revenue and revenue > 0:
        for key, source in (
            ("gross_margin", "gross_profit"),
            ("operating_margin", "operating_income"),
            ("net_margin", "net_income"),
            ("ebitda_margin", "ebitda"),
        ):
            value = metrics.get(source)
            if value is not None:
                derived[key] = value / revenue

    debt = metrics.get("total_debt")
    if debt is not None:
        cash = metrics.get("cash_and_equivalents") or 0.0
        derived["net_debt"] = debt - cash

    equity = metrics.get("total_equity")
    if equity and equity > 0:
        net_income = metrics.get("net_income")
        if net_income is not None:
            derived["roe"] = net_income / equity
        if "total_liabilities" in metrics:
            derived["debt_to_equity"] = metrics["total_liabilities"] / equity
        elif debt is not None:
            derived["debt_to_equity"] = debt / equity

    if metrics.get("total_assets") and metrics.get("net_income") is not None:
        derived["roa"] = metrics["net_income"] / metrics["total_assets"]  # type: ignore[operator]

    # ROCE uses operating profit over capital employed -- the measure that
    # survives differences in how a company is financed.
    capital_employed = None
    if equity is not None and debt is not None:
        capital_employed = equity + debt
    elif metrics.get("total_assets") is not None:
        current_liabilities = metrics.get("current_liabilities")
        capital_employed = (
            metrics["total_assets"] - current_liabilities
            if current_liabilities is not None
            else metrics["total_assets"]
        )
    if capital_employed and capital_employed > 0 and metrics.get("operating_income") is not None:
        derived["roce"] = metrics["operating_income"] / capital_employed

    interest = metrics.get("interest_expense")
    operating = metrics.get("operating_income")
    if interest and interest > 0 and operating is not None:
        derived["interest_cover"] = operating / interest

    eps = metrics.get("eps_diluted")
    if eps and eps > 0 and metrics.get("dividend_per_share") is not None:
        derived["payout_ratio"] = metrics["dividend_per_share"] / eps

    return derived


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
    """
    settings = settings or get_settings()
    provider = provider or YahooProvider(settings)
    report = FundamentalsReport()

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .where(Instrument.yahoo_symbol.is_not(None))
        # Least recently updated first, so a rationed refresh rotates fairly.
        .order_by(Instrument.updated_at.asc())
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    if limit:
        statement = statement.limit(limit)

    instruments = session.execute(statement).scalars().all()

    for instrument in instruments:
        report.tickers_attempted += 1
        symbol = instrument.yahoo_symbol
        assert symbol is not None

        _sync_profile(session, instrument, provider, report)

        try:
            financials = provider.get_financials(symbol)
        except ProviderError as exc:
            report.failures.append(f"{instrument.t212_ticker}: {exc}")
            continue

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
            )
            report.periods_written += 1
        session.flush()

    logger.info("fundamentals sync: %s", report.as_dict())
    return report


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
    if info.get("industry") and not instrument.industry:
        instrument.industry = str(info["industry"])
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


def normalise_company_name(name: str) -> str:
    """Reduce a company name to a comparable form."""
    cleaned = _NAME_NOISE.sub(" ", name.lower())
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


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

    Only an exact normalised name match on an active company is treated as
    dependable. Anything weaker is returned with a low confidence so it can be
    recorded for human review without being acted on -- attaching the wrong
    company's accounts to a ticker produces confident, completely wrong analysis.
    """
    target = normalise_company_name(instrument.name)
    if not target:
        return None

    best: CompanyMatch | None = None
    for candidate in candidates:
        raw_name = str(candidate.get("title") or candidate.get("company_name") or "")
        number = normalise_company_number(candidate.get("company_number"))
        if not number:
            continue
        status = str(candidate.get("company_status") or "")
        matched = normalise_company_name(raw_name)

        if matched == target:
            confidence = 0.9 if status in ("active", "") else 0.6
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
    limit: int | None = None,
) -> dict[str, Any]:
    """Attach Companies House company numbers to UK-listed instruments."""
    from awltux.ingest.symbols import is_uk_listing

    settings = settings or get_settings()
    provider = provider or CompaniesHouseProvider(settings)
    if not provider.configured:
        return {"skipped": "AWLTUX_COMPANIES_HOUSE_API_KEY is not set"}

    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.ch_company_number.is_(None))
    )
    if limit:
        statement = statement.limit(limit)
    instruments = [
        row
        for row in session.execute(statement).scalars().all()
        if is_uk_listing(row.exchange_name, row.yahoo_symbol)
    ]

    summary = {"attempted": len(instruments), "matched": 0, "confident": 0, "unmatched": 0}
    for instrument in instruments:
        try:
            candidates = provider.search_companies(instrument.name)
        except ProviderError as exc:
            logger.debug("CH search failed for %s: %s", instrument.name, exc)
            continue

        match = match_company(instrument, candidates)
        if match is None:
            summary["unmatched"] += 1
            continue

        instrument.ch_company_number = match.company_number
        summary["matched"] += 1
        if match.confidence >= 0.8:
            summary["confident"] += 1

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
                    note=f"{match.company_name} ({match.status or 'status unknown'})",
                )
            )
        elif not alias.is_manual:
            alias.symbol = match.company_number
            alias.confidence = match.confidence
            alias.method = match.method
            alias.note = f"{match.company_name} ({match.status or 'status unknown'})"

    session.flush()
    logger.info("UK company resolution: %s", summary)
    return summary
