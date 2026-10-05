"""SQLAlchemy models. The schema is the audit trail's backbone.

Design rules that the rest of the app depends on:

* **Provenance is mandatory.** Anything derived from the outside world carries
  ``source`` and an ``as_of``/``fetched_at`` timestamp, so no number in the UI is
  ever orphaned from where it came from.
* **Raw evidence is archived.** Long provider payloads are written to disk and
  referenced by path rather than inflating the database.
* **Decisions are immutable.** A ``decision_run`` is written once and never
  updated; re-evaluation produces a new row. This is what makes a past decision
  provable rather than merely remembered.
* **Money is normalised at write time.** LSE quotes arrive in pence (GBp) and the
  raw unit is recorded alongside the normalised value, because a silent 100x
  error is the classic failure mode in UK equity code.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def utcnow() -> dt.datetime:
    """Timezone-aware UTC now. Always use this, never ``datetime.now()``."""
    return dt.datetime.now(dt.UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# reference data
# --------------------------------------------------------------------------- #


class Exchange(Base, TimestampMixin):
    """Trading 212 exchange + its working schedule.

    The schedule drives market-hours logic, so we never poll prices for a closed
    market or treat a closed-market stale quote as a live one.
    """

    __tablename__ = "exchange"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # "LSE", "NASDAQ", "NYSE", ... derived from the T212 name when possible.
    country_code: Mapped[str | None] = mapped_column(String(8))
    timezone: Mapped[str | None] = mapped_column(String(64))
    # Full T212 workingSchedules payload (timeEvents -> open/close windows).
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    instruments: Mapped[list[Instrument]] = relationship(back_populates="exchange_ref")


class Instrument(Base, TimestampMixin):
    """A share tradeable on Trading 212, joined to every external identity.

    ``t212_ticker`` is the primary key because it is the only identifier Trading
    212 guarantees. ``isin`` is the cross-provider join key, but it is optional
    in their schema and one ISIN can map to several T212 tickers (dual
    listings), so it is indexed rather than unique.
    """

    __tablename__ = "instrument"

    t212_ticker: Mapped[str] = mapped_column(String(64), primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(16), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(128))
    currency_code: Mapped[str | None] = mapped_column(String(8))
    instrument_type: Mapped[str | None] = mapped_column(String(24))
    extended_hours: Mapped[bool] = mapped_column(Boolean, default=False)
    max_open_quantity: Mapped[float | None] = mapped_column(Float)
    added_on: Mapped[str | None] = mapped_column(String(32))

    # --- exchange -----------------------------------------------------------
    #: The exchange this instrument trades on. Resolved from
    #: ``workingScheduleId`` at sync time, because that is the only documented
    #: route from an instrument to its venue.
    exchange_id: Mapped[int | None] = mapped_column(
        ForeignKey("exchange.id"), index=True
    )
    #: Trading 212's raw ``workingScheduleId``. **Not** an exchange id: schedule
    #: ids live in their own space inside each exchange's ``workingSchedules``
    #: list, so this deliberately carries no foreign key. Treating it as an
    #: exchange reference violated the constraint on 18,000 instruments.
    working_schedule_id: Mapped[int | None] = mapped_column(Integer, index=True)
    exchange_name: Mapped[str | None] = mapped_column(String(64), index=True)

    # --- resolved external identities ---------------------------------------
    # yfinance symbol ("VOD.L", "AAPL"). LSE names take a ".L" suffix.
    yahoo_symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    # Zero-padded 10-digit SEC CIK for US filers.
    sec_cik: Mapped[str | None] = mapped_column(String(10), index=True)
    # Companies House company number for UK filers.
    ch_company_number: Mapped[str | None] = mapped_column(String(16), index=True)

    # 0..1 -- how sure we are of the yahoo/CIK/CH mapping. Anything below the
    # configured floor is excluded from decisions until a human confirms it.
    mapping_confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # --- classification -----------------------------------------------------
    sector: Mapped[str | None] = mapped_column(String(96), index=True)
    industry: Mapped[str | None] = mapped_column(String(128))
    sector_source: Mapped[str | None] = mapped_column(String(32))
    sic_code: Mapped[str | None] = mapped_column(String(8))

    # --- universe membership -------------------------------------------------
    in_universe: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    is_held: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    market_cap: Mapped[float | None] = mapped_column(Float)
    median_daily_turnover_gbp: Mapped[float | None] = mapped_column(Float)

    exchange_ref: Mapped[Exchange | None] = relationship(back_populates="instruments")
    aliases: Mapped[list[InstrumentAlias]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_instrument_universe", "in_universe", "excluded"),)

    @property
    def display_name(self) -> str:
        return self.short_name or self.name

    @property
    def price_symbol(self) -> str | None:
        """Symbol to use for price lookups, or ``None`` if unresolved."""
        return self.yahoo_symbol


class InstrumentAlias(Base, TimestampMixin):
    """History of symbol mappings, plus human overrides.

    Tickers change on renames, and providers disagree on suffixes. Keeping every
    mapping (rather than overwriting) means an old price row can still be
    explained, and a manual override is a recorded fact rather than a silent
    edit.
    """

    __tablename__ = "instrument_alias"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))  # yahoo | edgar | ch
    symbol: Mapped[str] = mapped_column(String(96))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str | None] = mapped_column(String(48))  # isin | name | manual | ticker
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)

    instrument: Mapped[Instrument] = relationship(back_populates="aliases")

    __table_args__ = (
        UniqueConstraint("instrument_t212_ticker", "provider", name="uq_alias_provider"),
    )


# --------------------------------------------------------------------------- #
# market data
# --------------------------------------------------------------------------- #


class PriceBar(Base):
    """One daily OHLCV bar, normalised to ``currency``.

    ``raw_currency``/``raw_multiplier`` preserve what the provider actually sent
    (LSE names quote in GBp), so the GBp -> GBP conversion is auditable rather
    than assumed. ``source_rank`` lets a better provider overwrite a worse one
    without creating duplicate series.
    """

    __tablename__ = "price_bar"

    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), primary_key=True
    )
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)

    currency: Mapped[str | None] = mapped_column(String(8))
    raw_currency: Mapped[str | None] = mapped_column(String(8))
    raw_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    raw_close: Mapped[float | None] = mapped_column(Float)

    source: Mapped[str] = mapped_column(String(24), nullable=False)
    source_rank: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (Index("ix_price_bar_date", "date"),)


class Quote(Base):
    """A point-in-time quote, kept hot for the dashboard and for freshness gates."""

    __tablename__ = "quote"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )
    ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8))
    raw_currency: Mapped[str | None] = mapped_column(String(8))
    raw_multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    # How stale the provider says this price is (15-min delayed feeds, etc).
    delay_seconds: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    fetched_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_quote_instrument_ts", "instrument_t212_ticker", "ts"),
    )


# --------------------------------------------------------------------------- #
# fundamentals & filings
# --------------------------------------------------------------------------- #


class Filing(Base, TimestampMixin):
    """A published document: EDGAR 10-K/10-Q/8-K, or Companies House accounts.

    The parsed representation is produced by an LLM extractor but every figure
    in it must carry a source span (see ``llm/extractors.py``). ``doc_hash``
    makes re-processing idempotent and detects silently re-issued documents.
    """

    __tablename__ = "filing"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )

    source: Mapped[str] = mapped_column(String(24))  # edgar | companies_house
    filing_type: Mapped[str | None] = mapped_column(String(32))  # 10-K | AA | 8-K ...
    title: Mapped[str | None] = mapped_column(String(512))
    filed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    period_end: Mapped[dt.date | None] = mapped_column(Date)
    url: Mapped[str | None] = mapped_column(String(1024))
    # sha256 of the document bytes -- idempotency + tamper evidence.
    doc_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    content_type: Mapped[str | None] = mapped_column(String(64))
    raw_path: Mapped[str | None] = mapped_column(String(512))

    # Extractor output: canonical metrics each carrying a source span.
    parsed: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    extractor_version: Mapped[str | None] = mapped_column(String(32))
    # pending | fetched | parsed | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text)

    periods: Mapped[list[FundamentalPeriod]] = relationship(back_populates="filing")

    __table_args__ = (
        UniqueConstraint("instrument_t212_ticker", "url", name="uq_filing_url"),
    )


class FundamentalPeriod(Base, TimestampMixin):
    """Normalised financials for one reporting period.

    ``metrics`` uses canonical keys (see ``analysis/fundamental.py``) so UK iXBRL
    and US XBRL land in the same shape despite different taxonomies.
    """

    __tablename__ = "fundamental_period"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )
    filing_id: Mapped[int | None] = mapped_column(
        ForeignKey("filing.id", ondelete="SET NULL")
    )

    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_type: Mapped[str] = mapped_column(String(16), nullable=False)  # annual|interim|quarterly|ttm
    currency: Mapped[str | None] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(24))
    # When this figure became knowable -- not when we fetched it. Look-ahead bias
    # guard for any future backtesting.
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Per-metric provenance: metric key -> {value, source, span, page, confidence}
    metric_sources: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    filing: Mapped[Filing | None] = relationship(back_populates="periods")

    __table_args__ = (
        UniqueConstraint(
            "instrument_t212_ticker",
            "period_end",
            "period_type",
            "source",
            name="uq_fundamental_period",
        ),
    )


# --------------------------------------------------------------------------- #
# news & sentiment
# --------------------------------------------------------------------------- #


class NewsItem(Base, TimestampMixin):
    """A headline/announcement, deduplicated and LLM-classified.

    ``url_hash`` is unique across sources so the same story arriving via RSS,
    Google News and Finnhub is stored once.
    """

    __tablename__ = "news_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    url: Mapped[str | None] = mapped_column(String(1024))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(768), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    # T212 tickers this story is judged to concern, + the sectors to roll up to.
    tickers: Mapped[list[str]] = mapped_column(JSON, default=list)
    sectors: Mapped[list[str]] = mapped_column(JSON, default=list)

    # Provider-supplied sentiment where available (Marketaux, Alpha Vantage).
    provider_sentiment: Mapped[float | None] = mapped_column(Float)
    # Our own classification, produced by the LLM layer.
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    materiality: Mapped[str | None] = mapped_column(String(16), index=True)
    direction: Mapped[str | None] = mapped_column(String(16))
    horizon: Mapped[str | None] = mapped_column(String(16))
    relevance: Mapped[float | None] = mapped_column(Float)

    engine: Mapped[str | None] = mapped_column(String(16))  # which model classified it
    #: What kind of event the classifier judged this to be. Recorded because it is
    #: what routes a claim to the register where its primary source would live: a
    #: results story has a filing behind it, a rumour has nothing.
    event_type: Mapped[str | None] = mapped_column(String(24), index=True)
    raw: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    raw_path: Mapped[str | None] = mapped_column(String(512))

    __table_args__ = (
        Index("ix_news_published_materiality", "published_at", "materiality"),
    )


class NewsAnalysis(Base):
    """The sceptical read of one news item.

    Separate from :class:`NewsItem` on purpose. The item is the *observation* --
    what a publisher said, kept verbatim and never rewritten. This is the
    *appraisal* -- who said it, what it rests on, what it leaves out, and how much
    weight it therefore gets.

    Keeping them apart means the appraisal can be recomputed when the source
    registry or the prompts change without touching the record of what was
    published, and a disagreement with the appraisal is arguable without accusing
    the system of altering the evidence.

    ``claims``, ``techniques``, ``omissions`` and ``corroboration`` are stored as
    JSON rather than normalised into tables. They are read as a document, per
    article, and never aggregated across articles in SQL; splitting them into four
    more tables would buy joins nothing asks for.
    """

    __tablename__ = "news_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_item_id: Mapped[int] = mapped_column(
        ForeignKey("news_item.id", ondelete="CASCADE"), unique=True, index=True
    )

    # --- who published it, and what that is worth ---------------------------
    source_domain: Mapped[str | None] = mapped_column(String(96), index=True)
    source_name: Mapped[str | None] = mapped_column(String(128))
    source_kind: Mapped[str | None] = mapped_column(String(24))
    source_reliability: Mapped[float | None] = mapped_column(Float)
    source_independence: Mapped[float | None] = mapped_column(Float)
    source_biases: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_basis: Mapped[str | None] = mapped_column(Text)
    source_assessed: Mapped[bool | None] = mapped_column(Boolean)

    # --- presentation -------------------------------------------------------
    rhetoric_score: Mapped[float | None] = mapped_column(Float, index=True)
    rhetoric: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    techniques: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # --- corroboration ------------------------------------------------------
    carrier_count: Mapped[int | None] = mapped_column(Integer)
    independent_sources: Mapped[int | None] = mapped_column(Integer)
    corroboration: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # --- what it claims -----------------------------------------------------
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    omissions: Mapped[list[str]] = mapped_column(JSON, default=list)
    headline_matches_body: Mapped[bool | None] = mapped_column(Boolean)
    headline_overstates: Mapped[str | None] = mapped_column(Text)
    who_benefits: Mapped[str | None] = mapped_column(Text)
    agenda_basis: Mapped[str | None] = mapped_column(Text)
    base_rate: Mapped[str | None] = mapped_column(Text)
    what_would_change_my_mind: Mapped[str | None] = mapped_column(Text)
    primary_source: Mapped[str | None] = mapped_column(Text)
    scepticism_summary: Mapped[str | None] = mapped_column(Text)
    injection_suspected: Mapped[bool | None] = mapped_column(Boolean)

    # --- the conclusion -----------------------------------------------------
    credibility: Mapped[float | None] = mapped_column(Float, index=True)
    evidence_grade: Mapped[str | None] = mapped_column(String(16), index=True)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    caveats: Mapped[list[str]] = mapped_column(JSON, default=list)
    factors: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    #: Which model produced the reading half, and when. The arithmetic half is
    #: ours and is versioned by the code, not recorded here.
    engine: Mapped[str | None] = mapped_column(String(64))
    analysed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    __table_args__ = (
        Index("ix_news_analysis_grade_credibility", "evidence_grade", "credibility"),
    )


class SentimentSeries(Base):
    """Daily sentiment aggregate for a stock or a sector.

    ``components`` keeps the breakdown so a headline index can always be
    decomposed into the news/price/flow inputs that produced it.
    """

    __tablename__ = "sentiment_series"

    scope_type: Mapped[str] = mapped_column(String(16), primary_key=True)  # instrument|sector
    scope_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)

    score: Mapped[float] = mapped_column(Float, nullable=False)  # -1..+1
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    components: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


# --------------------------------------------------------------------------- #
# valuation & decisions
# --------------------------------------------------------------------------- #


class ValuationRun(Base):
    """One execution of the deterministic valuation model.

    ``inputs`` is everything the model saw; ``model_outputs`` is every method's
    value and the inputs it used. Together they make the fair value recomputable
    without trusting this row's arithmetic.
    """

    __tablename__ = "valuation_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )
    as_of: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    price: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(8))
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    model_outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    fair_value_low: Mapped[float | None] = mapped_column(Float)
    fair_value_base: Mapped[float | None] = mapped_column(Float)
    fair_value_high: Mapped[float | None] = mapped_column(Float)
    margin_of_safety: Mapped[float | None] = mapped_column(Float)
    # Confidence in the *valuation*, distinct from confidence in the decision.
    valuation_confidence: Mapped[float | None] = mapped_column(Float)

    methods_applied: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(24), default="ok", index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    engine_version: Mapped[str] = mapped_column(String(32), default="1")

    __table_args__ = (Index("ix_valuation_instrument_asof", "instrument_t212_ticker", "as_of"),)


class DecisionRun(Base):
    """An immutable decision record -- the unit of provability.

    Everything needed to reproduce and to audit the verdict is stored here: the
    canonical state and its hash, the exact questions asked, which engine and
    model version answered, the raw answers, the composite score, and the risk
    gate's verdict with the single binding rule if it refused.

    Rows are never updated. Re-deciding inserts a new row, so history is kept.
    """

    __tablename__ = "decision_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )
    valuation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("valuation_run.id", ondelete="SET NULL")
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    # --- inputs --------------------------------------------------------------
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # sha256 over the canonical serialisation of `state`.
    state_sha256: Mapped[str] = mapped_column(String(64), index=True)
    state_tokens_est: Mapped[int | None] = mapped_column(Integer)
    questions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # --- who answered --------------------------------------------------------
    engine: Mapped[str] = mapped_column(String(16), index=True)  # jev|deepseek|offline
    model_id: Mapped[str | None] = mapped_column(String(64))
    # True when probabilities are model-estimated rather than calibrated.
    uncalibrated: Mapped[bool] = mapped_column(Boolean, default=False)
    fallback_reason: Mapped[str | None] = mapped_column(String(255))

    # --- answers -------------------------------------------------------------
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    narrative: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # --- derived, per horizon ------------------------------------------------
    # Two independent verdicts, because they answer different questions from
    # different inputs and may legitimately disagree. The long-term pair is the
    # primary one and keeps the unprefixed column names.
    composite: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    composite_score: Mapped[float | None] = mapped_column(Float, index=True)
    long_term_action: Mapped[str | None] = mapped_column(String(24), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    gate: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    gate_allowed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    short_term_composite: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    short_term_composite_score: Mapped[float | None] = mapped_column(Float, index=True)
    short_term_action: Mapped[str | None] = mapped_column(String(24), index=True)
    short_term_confidence: Mapped[float | None] = mapped_column(Float)
    short_term_gate: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    short_term_gate_allowed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    #: Which horizon the engine judged the opportunity to suit: long_term,
    #: short_term, both, or neither.
    horizon_fit: Mapped[str | None] = mapped_column(String(16), index=True)
    conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    llm_call_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    app_version: Mapped[str] = mapped_column(String(32), default="0.1.0")

    outcomes: Mapped[list[DecisionOutcome]] = relationship(
        back_populates="decision", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_decision_instrument_created", "instrument_t212_ticker", "created_at"),
        Index("ix_decision_long_gate", "long_term_action", "gate_allowed"),
        Index("ix_decision_short_gate", "short_term_action", "short_term_gate_allowed"),
    )

    #: Convenience aliases so callers can address a horizon by name.
    @property
    def action(self) -> str | None:
        """The long-term action. Kept as ``action`` because it is the primary one."""
        return self.long_term_action

    def action_for(self, horizon: str) -> str | None:
        return self.short_term_action if horizon == "short_term" else self.long_term_action

    def gate_for(self, horizon: str) -> dict[str, Any] | None:
        return self.short_term_gate if horizon == "short_term" else self.gate

    def allowed_for(self, horizon: str) -> bool:
        return (
            self.short_term_gate_allowed
            if horizon == "short_term"
            else self.gate_allowed
        )

    def score_for(self, horizon: str) -> float | None:
        return (
            self.short_term_composite_score
            if horizon == "short_term"
            else self.composite_score
        )


class DecisionOutcome(Base):
    """Realised result of a past decision, used for calibration.

    Without this table "provable" is just a claim; with it, hit rate and average
    return can be reported per confidence bucket, per engine and per horizon.

    Outcomes are tracked **separately per horizon**, and on different timescales:
    a tactical call is judged over days and a long-term call over months. Scoring
    both on the same 90-day window would make the tactical record meaningless.
    """

    __tablename__ = "decision_outcome"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    decision_run_id: Mapped[int] = mapped_column(
        ForeignKey("decision_run.id", ondelete="CASCADE"), index=True
    )
    horizon: Mapped[str] = mapped_column(String(16), default="long_term", index=True)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)

    price_at_decision: Mapped[float | None] = mapped_column(Float)
    price_at_horizon: Mapped[float | None] = mapped_column(Float)
    return_pct: Mapped[float | None] = mapped_column(Float)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Float)
    # direction_correct | direction_wrong | flat | no_direction
    verdict: Mapped[str | None] = mapped_column(String(24))
    computed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )

    decision: Mapped[DecisionRun] = relationship(back_populates="outcomes")

    __table_args__ = (
        UniqueConstraint(
            "decision_run_id", "horizon", "horizon_days", name="uq_outcome_horizon"
        ),
    )


# --------------------------------------------------------------------------- #
# operations
# --------------------------------------------------------------------------- #


class LLMCall(Base):
    """Every model call, with token counts and cost.

    Doubles as the spend guard: the decision layer checks the running monthly
    total before making a call and degrades rather than exceed the cap.
    Request/response bodies are redacted of credentials and truncated; large
    payloads are referenced by path.
    """

    __tablename__ = "llm_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(24), index=True)  # deepseek|typesafe
    model: Mapped[str | None] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(48), index=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    request_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    response_path: Mapped[str | None] = mapped_column(String(512))

    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[int | None] = mapped_column(Integer)

    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class ProviderBudget(Base, TimestampMixin):
    """Persisted token-bucket state so rate limits survive a restart."""

    __tablename__ = "provider_budget"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    blocked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base, TimestampMixin):
    """Runtime overrides of ``config.yaml`` values, plus small UI state."""

    __tablename__ = "app_setting"

    key: Mapped[str] = mapped_column(String(96), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text)


class IngestRun(Base):
    """One execution of a scheduled job: observability for the background loop."""

    __tablename__ = "ingest_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job: Mapped[str] = mapped_column(String(48), index=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_written: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON)
