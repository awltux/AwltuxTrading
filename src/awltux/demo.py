"""Synthetic data, so the application can be exercised without any credentials.

Waiting for live provider data to validate a dashboard is a bad feedback loop: the
universe sync alone is rate-limited to roughly one request per minute, filings
arrive episodically, and a fresh install has nothing to look at. Seeding lets the
UI, the valuation maths and the decision pipeline all be checked immediately --
and the same fixture is what the template tests use, which is how two template
bugs were found that an empty database had been hiding.

The data is deliberately awkward in the places real data is awkward:

* a **UK listing quoted in pence**, to exercise the GBp/GBP conversion;
* an **expensive, high-quality compounder** and a **cheap, leveraged cyclical**,
  so the two horizons have something to disagree about;
* one **loss-making** name, so the valuation engine has to refuse rather than
  invent a fair value;
* one **net-cash** balance sheet and one **heavily indebted** one.

Prices are generated from a seeded RNG, so a given ticker always produces the same
series and a screenshot is reproducible.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis.sectors import assign
from awltux.db import (
    FundamentalPeriod,
    Instrument,
    NewsItem,
    PriceBar,
    SentimentSeries,
    utcnow,
)
from awltux.timezones import utc_today

logger = logging.getLogger(__name__)

#: Marker in ``Instrument.industry`` so seeded rows are identifiable and can be
#: removed without touching anything fetched from a provider.
DEMO_MARKER = "__demo__"


@dataclass(slots=True)
class DemoSpec:
    """One synthetic company, described by the traits we want to exercise."""

    ticker: str
    name: str
    symbol: str
    exchange: str
    currency: str
    #: Provider currency. UK listings quote in pence, which is the point.
    quote_currency: str
    sector: str
    start_price: float
    annual_return: float
    volatility: float
    shares: float
    revenue: float
    net_margin: float
    equity: float
    debt: float
    cash: float
    dividend: float = 0.0
    loss_making: bool = False
    notes: str = ""


SPECS: tuple[DemoSpec, ...] = (
    DemoSpec(
        ticker="DEMO1_US_EQ",
        name="Demo Compounders Inc",
        symbol="DEMO1",
        exchange="NASDAQ",
        currency="USD",
        quote_currency="USD",
        sector="Technology",
        start_price=120.0,
        annual_return=0.18,
        volatility=0.28,
        shares=250_000.0,
        revenue=900_000.0,
        net_margin=0.22,
        equity=800_000.0,
        debt=50_000.0,
        cash=220_000.0,
        dividend=0.0,
        notes="expensive, high-quality compounder",
    ),
    DemoSpec(
        ticker="DEMO2l_EQ",
        name="Demo UK Cyclical",
        symbol="DEMO2.L",
        exchange="LSE",
        currency="GBP",
        quote_currency="GBp",
        sector="Industrials",
        start_price=245.0,
        annual_return=-0.02,
        volatility=0.34,
        shares=180_000.0,
        revenue=1_400_000.0,
        net_margin=0.05,
        equity=600_000.0,
        debt=900_000.0,
        cash=60_000.0,
        dividend=0.03,
        notes="cheap, leveraged, quoted in pence",
    ),
    DemoSpec(
        ticker="DEMO3_US_EQ",
        name="Demo Lossmaker Corp",
        symbol="DEMO3",
        exchange="NYSE",
        currency="USD",
        quote_currency="USD",
        sector="Consumer Discretionary",
        start_price=48.0,
        annual_return=-0.12,
        volatility=0.52,
        shares=120_000.0,
        revenue=400_000.0,
        net_margin=-0.08,
        equity=150_000.0,
        debt=300_000.0,
        cash=25_000.0,
        loss_making=True,
        notes="loss-making, so the valuation engine must refuse",
    ),
    DemoSpec(
        ticker="DEMO4l_EQ",
        name="Demo UK Quality",
        symbol="DEMO4.L",
        exchange="LSE",
        currency="GBP",
        quote_currency="GBp",
        sector="Consumer Staples",
        start_price=880.0,
        annual_return=0.07,
        volatility=0.19,
        shares=90_000.0,
        revenue=2_200_000.0,
        net_margin=0.16,
        equity=1_100_000.0,
        debt=120_000.0,
        cash=400_000.0,
        dividend=0.028,
        notes="net cash, steady compounder",
    ),
    DemoSpec(
        ticker="DEMO5_US_EQ",
        name="Demo Fallen Angel",
        symbol="DEMO5",
        exchange="NASDAQ",
        currency="USD",
        quote_currency="USD",
        sector="Healthcare",
        start_price=310.0,
        annual_return=-0.22,
        volatility=0.61,
        shares=140_000.0,
        revenue=700_000.0,
        net_margin=0.09,
        equity=520_000.0,
        debt=180_000.0,
        cash=150_000.0,
        dividend=0.0,
        notes="good fundamentals, badly out of favour",
    ),
)


@dataclass(slots=True)
class SeedReport:
    instruments: int = 0
    bars: int = 0
    periods: int = 0
    news: int = 0
    sentiment: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "instruments": self.instruments,
            "bars": self.bars,
            "periods": self.periods,
            "news": self.news,
            "sentiment": self.sentiment,
            "errors": self.errors,
        }


def _trading_days(days: int) -> list[dt.date]:
    """Weekdays only, oldest first, ending yesterday."""
    today = utc_today()
    out: list[dt.date] = []
    cursor = today - dt.timedelta(days=days)
    while cursor < today:
        if cursor.weekday() < 5:
            out.append(cursor)
        cursor += dt.timedelta(days=1)
    return out


def _price_path(spec: DemoSpec, days: list[dt.date]) -> list[float]:
    """A reproducible path with drift, volatility and a little mean reversion.

    Seeded from the ticker, so the same instrument always produces the same
    series -- a dashboard screenshot stays reproducible and a failing assertion
    stays failing for a reason.
    """
    rng = random.Random(f"demo:{spec.ticker}")
    daily_drift = spec.annual_return / 252.0
    closes: list[float] = []
    price = spec.start_price

    for index, _day in enumerate(days):
        shock = rng.gauss(0.0, spec.volatility / (252**0.5))
        # Mild mean reversion keeps a 15% annual decline from reaching zero over
        # a year of trading, which would make ratios meaningless.
        pull = (spec.start_price - price) / spec.start_price * 0.01
        price = max(price * (1.0 + daily_drift + shock + pull), spec.start_price * 0.15)
        # A late drawdown on the "fallen angel" so the tactical view has a trend.
        if spec.ticker == "DEMO5_US_EQ" and index > len(days) * 0.75:
            price *= 0.997
        closes.append(round(price, 4))
    return closes


def seed_demo_data(
    session: Session,
    *,
    history_days: int = 400,
    reset: bool = False,
) -> SeedReport:
    """Create the synthetic universe. Idempotent unless ``reset`` is set."""
    report = SeedReport()

    if reset:
        report.errors.extend(_clear(session))

    days = _trading_days(history_days)
    for spec in SPECS:
        try:
            report.instruments += _seed_instrument(session, spec, days, report)
        except Exception as exc:  # one bad spec must not lose the others
            report.errors.append(f"{spec.ticker}: {exc}")

    session.flush()
    logger.info("seeded demo data: %s", report.as_dict())
    return report


def _clear(session: Session) -> list[str]:
    """Remove previously seeded rows, leaving provider data alone."""
    errors: list[str] = []
    try:
        tickers = [
            row.t212_ticker
            for row in session.query(Instrument)
            .filter(Instrument.industry == DEMO_MARKER)
            .all()
        ]
        if not tickers:
            return errors
        # Cascades handle the dependent rows.
        for model in (NewsItem, SentimentSeries):
            session.query(model).filter(
                model.id.in_(
                    session.query(model.id).filter(
                        model.tickers.contains(tickers[0])  # type: ignore[attr-defined]
                    )
                )
            ).delete(synchronize_session=False)
        session.query(Instrument).filter(
            Instrument.t212_ticker.in_(tickers)
        ).delete(synchronize_session=False)
        session.flush()
    except Exception as exc:
        errors.append(f"reset failed: {exc}")
    return errors


def _seed_instrument(
    session: Session, spec: DemoSpec, days: list[dt.date], report: SeedReport
) -> int:
    instrument = session.get(Instrument, spec.ticker)
    if instrument is None:
        instrument = Instrument(t212_ticker=spec.ticker, name=spec.name)
        session.add(instrument)

    instrument.name = spec.name
    instrument.short_name = spec.name.split()[-1][:12]
    instrument.isin = f"GB00DEMO{abs(hash(spec.ticker)) % 100000:05d}"
    instrument.currency_code = spec.currency
    instrument.instrument_type = "STOCK"
    instrument.exchange_name = spec.exchange
    instrument.yahoo_symbol = spec.symbol
    instrument.sector = spec.sector
    instrument.sector_source = "demo"
    assign(instrument)
    instrument.industry = DEMO_MARKER
    instrument.in_universe = True
    instrument.excluded = False
    instrument.mapping_confidence = 1.0
    instrument.is_held = spec.ticker in {"DEMO1_US_EQ", "DEMO2l_EQ"}
    instrument.market_cap = spec.shares * spec.start_price
    instrument.median_daily_turnover_gbp = 25_000_000.0
    session.flush()

    # --- prices --------------------------------------------------------------
    closes = _price_path(spec, days)
    multiplier = 0.01 if spec.quote_currency == "GBp" else 1.0
    for index, day in enumerate(days):
        close = closes[index]
        session.merge(
            PriceBar(
                instrument_t212_ticker=spec.ticker,
                date=day,
                open=round(close * 0.995, 6),
                high=round(close * 1.012, 6),
                low=round(close * 0.988, 6),
                close=close,
                adj_close=close,
                volume=round(250_000 + (index % 30) * 9_000, 2),
                currency=spec.currency,
                raw_currency=spec.quote_currency,
                raw_multiplier=multiplier,
                raw_close=round(close / multiplier, 6),
                source="demo",
                source_rank=99,
                fetched_at=utcnow(),
            )
        )
        report.bars += 1

    # --- accounts ------------------------------------------------------------
    this_year = utc_today().year
    for offset, year in enumerate(range(this_year - 3, this_year)):
        growth = 1.0 + 0.06 * offset
        revenue = spec.revenue * growth
        net_income = revenue * spec.net_margin
        metrics = _metrics(spec, revenue, net_income, growth)
        period_end = dt.date(year, 12, 31)

        # Matched on the *unique* key, not the surrogate id: `session.merge` only
        # looks at the primary key, so it would insert a duplicate and trip the
        # unique constraint on a second run.
        period = session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == spec.ticker)
            .where(FundamentalPeriod.period_end == period_end)
            .where(FundamentalPeriod.period_type == "annual")
            .where(FundamentalPeriod.source == "demo")
        ).scalar_one_or_none()
        if period is None:
            period = FundamentalPeriod(
                instrument_t212_ticker=spec.ticker,
                period_end=period_end,
                period_type="annual",
                source="demo",
            )
            session.add(period)

        period.currency = spec.currency
        period.as_of = utcnow()
        period.metrics = metrics
        period.confidence = 0.9
        report.periods += 1

    # --- news and sentiment --------------------------------------------------
    for index, (title, direction, materiality) in enumerate(
        (
            (f"{spec.name} reports results in line with guidance", "neutral", "mild"),
            (f"Analysts debate outlook for {spec.name}", "negative", "moderate"),
        )
    ):
        url = f"https://demo.example/{spec.ticker}/{index}"
        exists = (
            session.query(NewsItem).filter(NewsItem.url == url).one_or_none()
        )
        if exists is None:
            session.add(
                NewsItem(
                    source="demo",
                    url=url,
                    url_hash=f"{abs(hash(url)):064d}"[:64],
                    title=title,
                    published_at=utcnow() - dt.timedelta(hours=6 * (index + 1)),
                    tickers=[spec.ticker],
                    sectors=[spec.sector],
                    materiality=materiality,
                    direction=direction,
                    sentiment_score=-0.2 if direction == "negative" else 0.0,
                    relevance=0.8,
                    engine="demo",
                )
            )
            report.news += 1

    session.merge(
        SentimentSeries(
            scope_type="instrument",
            scope_id=spec.ticker,
            date=utc_today(),
            score=-0.15 if spec.annual_return < 0 else 0.25,
            article_count=2,
            components={"source": "demo"},
            computed_at=utcnow(),
        )
    )
    report.sentiment += 1
    session.flush()
    return 1


def _metrics(
    spec: DemoSpec, revenue: float, net_income: float, growth: float
) -> dict[str, float]:
    """A consistent set of accounts, including the derived ratios."""
    gross = revenue * (0.55 if spec.net_margin > 0 else 0.30)
    operating = revenue * (spec.net_margin + 0.05)
    ebitda = operating * 1.2
    equity = spec.equity * growth
    net_debt = spec.debt - spec.cash
    fcf = net_income * 0.85
    shares = spec.shares

    metrics: dict[str, float] = {
        "revenue": round(revenue, 2),
        "gross_profit": round(gross, 2),
        "operating_income": round(operating, 2),
        "net_income": round(net_income, 2),
        "ebitda": round(ebitda, 2),
        "eps_diluted": round(net_income / shares, 4),
        "total_assets": round(equity + spec.debt, 2),
        "total_liabilities": round(spec.debt, 2),
        "total_equity": round(equity, 2),
        "total_debt": round(spec.debt, 2),
        "cash_and_equivalents": round(spec.cash, 2),
        "net_debt": round(net_debt, 2),
        "operating_cash_flow": round(net_income * 1.1, 2),
        "capex": round(abs(net_income) * 0.25, 2),
        "free_cash_flow": round(fcf, 2),
        "dividends_paid": round(revenue * spec.dividend, 2),
        "shares_outstanding": shares,
        "dividend_per_share": round(revenue * spec.dividend / shares, 4),
        "gross_margin": 0.55 if spec.net_margin > 0 else 0.30,
        "operating_margin": spec.net_margin + 0.05,
        "net_margin": spec.net_margin,
        "roe": round(net_income / equity, 4) if equity else 0.0,
        "roce": round(operating / (equity + spec.debt), 4),
        "debt_to_equity": round(spec.debt / equity, 4) if equity else 0.0,
        "interest_cover": round(operating / max(spec.debt * 0.05, 1.0), 2),
    }
    if spec.dividend and metrics["eps_diluted"] > 0:
        metrics["payout_ratio"] = round(
            metrics["dividend_per_share"] / metrics["eps_diluted"], 4
        )
    return metrics


def demoTickers() -> list[str]:
    """The tickers the seeder creates, for tests and the CLI to report."""
    return [spec.ticker for spec in SPECS]
