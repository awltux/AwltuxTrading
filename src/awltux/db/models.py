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
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from awltux import __version__

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
    # ``sector`` is the industry *description* the register supplied -- 148 distinct
    # strings over 500 in-universe instruments, one or two names each. ``sector_group``
    # is the coarse eleven a page and a news query can actually be built on, derived
    # from ``sic_code`` by ``analysis/sectors.py``. Both are kept: the description is
    # what EDGAR said, and the group is a derivation that can be recomputed.
    sector: Mapped[str | None] = mapped_column(String(96), index=True)
    sector_group: Mapped[str | None] = mapped_column(String(32), index=True)
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

    # --- shareholders' reports ------------------------------------------------
    #: Annual-report *documents* held for this instrument.
    #:
    #: A stored count rather than one derived from `filing` on every read. The
    #: question the flag answers -- "can I read this company's accounts?" -- is asked
    #: once per row on the dashboard and once per instrument by the acquisition job,
    #: and deriving it both times means a join over the largest table in the database
    #: to answer something that changes once a day.
    #:
    #: Zero means "none held", not "unknown": an instrument nobody has looked at yet
    #: and one whose reports genuinely do not exist are the same state as far as a
    #: reader is concerned, and `reports_synced_at` distinguishes them.
    annual_reports: Mapped[int] = mapped_column(Integer, default=0)
    #: When the count was last refreshed, so a zero can be dated.
    reports_synced_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    #: When this instrument's news feeds were last polled, which is the news poll's
    #: cursor rather than a fact about the instrument.
    #:
    #: The poll walks the whole universe and takes hours, and it used to start at the
    #: first row every time -- so a run that was interrupted re-fetched every feed it
    #: had already fetched, and the instruments at the end of the list were reached only
    #: if a run happened to get that far. Ordering on this column makes each run continue
    #: where the last one stopped, and makes the sweep wrap: once every row has been
    #: stamped, the least recently polled is the first one polled, so the next run
    #: begins again at the beginning without anything having to reset a counter.
    #:
    #: `Instrument.updated_at` is the obvious column and the wrong one -- nothing else
    #: in this job touches the instrument row, but plenty of other jobs do, so it would
    #: order the poll by whatever ran last.
    #:
    #: Indexed because it *is* the poll's sort key: `_instruments_to_poll` orders the
    #: whole universe by it every run. Migration `0008` created the index and the model
    #: did not declare it, which `alembic check` reports as an index to remove -- the
    #: migration was right and the declaration was missing.
    news_polled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    #: When the *marketaux* quota was last spent on this instrument, which is a different
    #: question from `news_polled_at` and needs its own answer.
    #:
    #: The poll asks RSS for every instrument in the universe; marketaux is rationed to a
    #: hundred requests a **day**, which is one request for one instrument's news, so a
    #: pass covers a fifth of the book. Sharing the poll's stamp would make the quota
    #: follow the poll's cursor -- the same fifth of the universe every day, because the
    #: cursor moves far faster than the quota. Its own stamp makes the quota itself the
    #: rotation: today's names are the ones it has waited longest to see.
    #:
    #: Indexed because it is the sort key that picks the day's slice.
    marketaux_polled_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

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
# instrument-level attention and refresh
# --------------------------------------------------------------------------- #


class InstrumentRefresh(Base, TimestampMixin):
    """A one-instrument refresh: the lock that serialises it, and its progress.

    Two jobs in one row, deliberately. It is a **lease** -- while a row is unexpired
    and running, the universe-wide jobs skip that instrument, so a scoped refresh and
    a sweep over the whole universe cannot write the same company at once. And it is
    the **record** of what the refresh did, so the instrument page can say "step 4 of
    13, xbrl_statements" and a reader can see which step failed without opening a log.

    **One row per instrument, primary key on the ticker.** That *is* the lock: a second
    refresh of the same instrument finds the row held and refuses, which is the
    behaviour asked for -- and it needs no separate table, because the thing being
    protected and the thing being reported are the same fact.

    **A lease, not a flag.** `expires_at` is what stops a crashed refresh from wedging
    an instrument out of every universe job forever. The holder renews it as it moves
    between steps (see :func:`~awltux.ingest.refresh.heartbeat`), so an expiry means the
    process is gone rather than that the work is slow -- and the TTL is generous for
    exactly that reason: a refresh legitimately spends minutes in model calls.

    **The lock is cooperative.** Universe jobs consult it at the boundary between one
    instrument and the next, which is the same boundary the cooperative stop uses
    (`progress.checkpoint`). Nothing here can interrupt a job that is already inside an
    instrument, and pretending otherwise would be worse than saying so: `SQLite`
    serialises the writes either way, so the cost of a collision is a wait, not a
    corrupted figure.
    """

    __tablename__ = "instrument_refresh"

    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), primary_key=True
    )

    #: Random per-acquisition token. Only the holder releases the lease, so a refresh
    #: that overran its TTL cannot release the one that replaced it.
    token: Mapped[str] = mapped_column(String(36))
    #: What the row means right now. `running` holds the lock; the other states do not.
    state: Mapped[str] = mapped_column(String(16), default="running", index=True)
    #: Free text for the reader: which step is in progress, or why the run failed.
    note: Mapped[str | None] = mapped_column(String(512))

    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    #: Renewed between steps. An unexpired row is a held lock.
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    #: One entry per step: its job id, whether it ran, and what it did. JSON rather
    #: than a child table because it is written once, read whole, and never queried
    #: across rows -- the same reasoning as `Filing.parsed`.
    steps: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)

    @property
    def held(self) -> bool:
        """Whether this row is currently locking the instrument."""
        return self.state == "running"


# --------------------------------------------------------------------------- #
# instrument-level blockers
# --------------------------------------------------------------------------- #


class InstrumentBlocker(Base, TimestampMixin):
    """A job that could not do its work for one instrument, and why.

    Advisory tooling has one failure that is worse than a wrong number: a *missing*
    one that looks like an answer. When `fundamentals` reports "no statements
    available for ADV.L", the dashboard shows the same em-dash it shows for a company
    nobody has fetched yet -- and the reader cannot tell "this cannot be had" from
    "not got round to it". The distinction is the whole point of the "Needs attention"
    filter, and nothing recorded it.

    **Why not read the run history.** Per-instrument failures *are* in
    ``IngestRun.detail`` as free text (``failures: ["ADVl_EQ: [yahoo] no statements
    available for ADV.L"]``), and that is where this started. Measured 2026-10-07:
    scanning the last 400 runs yielded **5 instruments**, because each job rations
    itself to a couple of instruments per run and the detail rotates away with
    ``retention``. A signal that decays is not a record.

    **One row per (instrument, job, stage).** A job fails an instrument for a
    particular reason at a particular step -- fetching statements, resolving a CIK,
    downloading a document -- so the same job failing at two steps is two blockers.
    The row is *upserted*: :func:`~awltux.ingest.blockers.record_blocker` bumps
    ``occurrences`` and ``last_seen_at`` rather than appending, because the question
    is "is this still broken", and an append-only log of a nightly failure is a table
    that grows forever to answer a boolean.

    **Resolved, not deleted.** A success clears ``resolved_at``-style by setting
    ``resolved_at`` (see :func:`~awltux.ingest.blockers.clear_blocker`), and the
    attention check reads only rows where it is null. Keeping the row means the
    history survives -- "this was broken for six weeks and then fixed" is the fact
    worth having -- and deleting it on success would make a flapping provider
    invisible.
    """

    __tablename__ = "instrument_blocker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instrument_t212_ticker: Mapped[str] = mapped_column(
        ForeignKey("instrument.t212_ticker", ondelete="CASCADE"), index=True
    )

    #: The job that could not proceed, by its registry id (`fundamentals`,
    #: `xbrl_statements`, `shareholder_reports`).
    job: Mapped[str] = mapped_column(String(48))
    #: What it was trying to do when it gave up -- `statements`, `cik`, `document`.
    #: Part of the key because one job failing at two steps is two different problems.
    stage: Mapped[str] = mapped_column(String(32))
    #: The provider's own words, kept verbatim. A paraphrase is a second guess, and
    #: the whole reason to store this is that the reader may need to believe it.
    reason: Mapped[str] = mapped_column(String(512))

    first_seen_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    #: How many consecutive times the same failure has been seen, so a transient and a
    #: permanent one are distinguishable without reading the log.
    occurrences: Mapped[int] = mapped_column(Integer, default=1)
    #: When a run last succeeded at this step, so the blocker stops counting.
    resolved_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )

    __table_args__ = (
        UniqueConstraint(
            "instrument_t212_ticker", "job", "stage", name="uq_instrument_blocker"
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

    #: Which number the story is *about*. ``event_type`` says what kind of fact this
    #: is; this says what the fact is about, and the two come apart exactly where the
    #: same-event grouping was failing: "Golar LNG gains 1.65% in October 5 trading"
    #: and "BTIG raises its Golar price target to $75" are both one company, one day
    #: and no news; only the metric separates a share moving from a broker changing
    #: its mind. ``"none"`` is a stated answer -- the story is not about a number --
    #: and is a different state from ``NULL``, which means this was never assessed.
    metric: Mapped[str | None] = mapped_column(String(24))

    #: The period the claim covers, as the story states it: "FY26", "Q1 2026",
    #: "2026-10-05", "this year". Free text on purpose, and **shown, not compared**.
    #: A "CN Rail falls Monday" story and a "CN Rail rises Wednesday" story differ
    #: here as well as in ``direction``, but normalising the two spellings into a
    #: comparable form is a job of its own, and a wrong comparison silently vetoes a
    #: real join -- the failure this grouping exists to prevent.
    period: Mapped[str | None] = mapped_column(String(32))

    #: The size as the story states it, units included: "1.65%", "$7.7bn".
    magnitude: Mapped[str | None] = mapped_column(String(32))

    #: Whether this story is a claim about a share price: it names an instrument
    #: or a sector *and* carries a direction. See ``analysis/relevance.py`` for the
    #: rule and the reasoning behind the conjunction.
    #:
    #: **Nullable on purpose.** ``None`` means "not assessed", which is a different
    #: and more actionable state than "assessed as not relevant" -- the same
    #: distinction ``ingest_run.ok`` needed. A story that was never judged should
    #: be visible as pending rather than silently filed as irrelevant.
    relevant: Mapped[bool | None] = mapped_column(Boolean, index=True)
    #: The classifier's own one-sentence justification, which used to be produced
    #: on every call and thrown away at this boundary. The news page shows it
    #: beside the instruments, because "relevant" with no reason is unarguable.
    relevance_reason: Mapped[str | None] = mapped_column(Text)

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
    #: The story this appraises. **Not unique, and that is the point.** A story naming
    #: three instruments and a sector has four appraisals, and they are not the same
    #: appraisal: whether the *subject* is held is what decides whether the model is
    #: asked to read the piece deeply, and a sector is held when any instrument in it
    #: is. One row per story was one row too few.
    news_item_id: Mapped[int] = mapped_column(
        ForeignKey("news_item.id", ondelete="CASCADE"), index=True
    )

    #: What this appraisal is *about* -- ``instrument`` with a T212 ticker, or
    #: ``sector`` with one of the eleven names from ``analysis/sectors.py``. Together
    #: with ``news_item_id`` this is the identity of the row; a reader looking at one
    #: company's page sees the appraisal for *that* company, not whichever subject
    #: happened to be written first.
    subject_type: Mapped[str] = mapped_column(String(16), index=True)
    subject_id: Mapped[str] = mapped_column(String(64), index=True)

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
        # One appraisal per story per subject. Named, because a violation of this is
        # how "the same event was appraised twice for the same company" would present
        # -- and the ingest path re-appraises in place rather than inserting, so a
        # conflict here means that lookup missed rather than that a second opinion
        # was wanted.
        UniqueConstraint(
            "news_item_id", "subject_type", "subject_id", name="uq_news_analysis_subject"
        ),
    )


class NewsEmbedding(Base):
    """The vector for one story, so the same event can be recognised as one event.

    A profit warning reaches this system five or six times, from different outlets,
    rewritten each time. The corroboration layer already collapses syndication --
    the same text pasted everywhere -- by comparing word sets. It cannot see the
    commoner case: one event reported in different words. A vector can, because it
    compares what the text means rather than which words it uses.

    **A separate table, not columns on the story.** The vector is only meaningful
    alongside the model that produced it -- re-embedding with another model is a
    different measurement, not an update -- so the model name is part of the row.
    And ``news_item`` is read on every dashboard render while this is read only
    when clustering, so a kilobyte of float32 does not belong on the hot path.

    Stored as raw ``float32`` bytes rather than JSON: a quarter the size, and it
    exists only to be fed back into numpy.
    """

    __tablename__ = "news_embedding"

    news_item_id: Mapped[int] = mapped_column(
        ForeignKey("news_item.id", ondelete="CASCADE"), primary_key=True
    )
    #: Which model produced it. Two vectors are comparable only if this matches.
    model: Mapped[str] = mapped_column(String(96), index=True)
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Hash of the text that was embedded, so a change to the input can be spotted
    #: rather than silently compared against vectors built from something else.
    text_hash: Mapped[str] = mapped_column(String(64))
    embedded_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
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
    # Defaulted from the derived version, not a literal. This was the fourth copy of
    # "0.1.0" in the tree, and the one a reader would trust most: it is the value the
    # ledger falls back to when a decision is written without one passed in.
    app_version: Mapped[str] = mapped_column(String(32), default=lambda: __version__)

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
