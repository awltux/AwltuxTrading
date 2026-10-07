"""News ingest: gather, canonicalise, dedupe, persist.

The shape of this pipeline is driven by the free tiers it sits on: hundreds of
loosely-matched headlines arrive from RSS, a small number of precisely-tagged and
sentiment-scored articles arrive from Marketaux, and only a handful are material.
So the work is staged to spend the expensive step (LLM classification) on as few
items as possible:

1. **Gather** from every configured source, swallowing per-source failures.
2. **Prefilter** cheaply -- drop obvious non-news, and require the subject to be
   mentioned at all.
3. **Dedupe** on a canonical URL, because the same story arrives via Google News,
   Yahoo and Finnhub with different tracking parameters.
4. **Classify** (optional, injected) to fill in materiality and direction.

Classification is a callback rather than a direct dependency so this module stays
testable without an LLM and so the pipeline still runs when no API key is set.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from awltux.analysis.relevance import assess
from awltux.config import Settings, get_settings
from awltux.db import Instrument, NewsItem, utcnow
from awltux.db.session import release_write_lock
from awltux.llm.classify import apply_classification
from awltux.providers.http import BudgetExhausted
from awltux.providers.news_rss import (
    FinnhubNewsProvider,
    GdeltProvider,
    MarketauxNewsProvider,
    RawNewsItem,
    RssNewsProvider,
    company_query,
)
from awltux.scheduler import progress
from awltux.timezones import as_utc

logger = logging.getLogger(__name__)

#: Signature of an injected classifier: item -> updates, or None to leave as-is.
Classifier = Callable[[RawNewsItem, Instrument | None], dict[str, Any] | None]


@dataclass(slots=True)
class NewsIngestReport:
    fetched: int = 0
    prefiltered_out: int = 0
    duplicates: int = 0
    written: int = 0
    classified: int = 0
    #: Stories whose verdict was copied from an already-judged copy of the same
    #: headline rather than bought again. Counted separately from ``classified``
    #: because that number is the model spend, and this one is the spend avoided.
    reused: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    #: Set when the walk left because a stop was requested. The caller needs it because
    #: the leaving has to happen *after* the commit: abandoning the batch would discard
    #: the articles already classified, and each one of those was a model call.
    stopped_early: bool = False
    #: Instruments this run was allowed to spend the marketaux quota on, so the run's
    #: detail says how much of the day's ration it used. Zero when the provider is not
    #: configured, which is the same number as "configured but the day is spent" and is
    #: why the detail also carries the provider's own remaining count.
    marketaux_allowance: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "fetched": self.fetched,
            "prefiltered_out": self.prefiltered_out,
            "duplicates": self.duplicates,
            "written": self.written,
            "classified": self.classified,
            "reused": self.reused,
            "by_source": self.by_source,
            "errors": self.errors[:10],
            "stopped_early": self.stopped_early,
            "marketaux_allowance": self.marketaux_allowance,
        }


#: Articles between progress lines. The poll runs for hours over a 500-instrument
#: universe and, before this, wrote one INFO line at the start and nothing until it
#: finished -- so a working job and a hung one looked identical for the whole run.
PROGRESS_EVERY_ARTICLES = 10

#: Instruments between progress lines, and it is a second throttle rather than the same
#: one for a reason: a stretch of feeds that carry nothing new advances no article count
#: at all, so an article-only line would go quiet in exactly the case that most looks
#: like a hang. Counting instruments bounds that silence.
PROGRESS_EVERY_INSTRUMENTS = 25


class Prefilter:
    """Cheap rejection rules applied before anything expensive runs.

    Rules are deliberately conservative: rejecting a real headline is worse than
    passing a dull one, because the dull one only costs a classification call
    while the rejected one is invisible forever.
    """

    def __init__(self, settings: Settings) -> None:
        config = settings.news.prefilter
        self.min_title_chars = config.min_title_chars
        self.require_ticker_mention = config.require_any_ticker_mention
        self.drop_patterns = [re.compile(p) for p in config.drop_patterns]

    def keep(self, item: RawNewsItem, instrument: Instrument | None = None) -> bool:
        title = item.title.strip()
        if len(title) < self.min_title_chars:
            return False
        for pattern in self.drop_patterns:
            if pattern.search(title):
                return False
        if self.require_ticker_mention and instrument is not None:
            # Require the company name or a distinctive word of it to appear.
            words = [
                word
                for word in re.split(r"[^A-Za-z0-9]+", instrument.name)
                if len(word) > 3
            ]
            haystack = f"{title} {item.summary or ''}".lower()
            if words and not any(word.lower() in haystack for word in words):
                return False
        return True


def gather_for_instrument(
    instrument: Instrument,
    *,
    settings: Settings,
    rss: RssNewsProvider,
    finnhub: FinnhubNewsProvider | None = None,
    marketaux: MarketauxNewsProvider | None = None,
) -> list[RawNewsItem]:
    """Collect headlines for one instrument from every configured source.

    Google News gets both a UK and a US edition for UK listings, since UK
    coverage often surfaces only in one of them.
    """
    items: list[RawNewsItem] = []
    query = company_query(instrument.name, instrument.t212_ticker)

    regions = [("GB", "en")] if _is_uk(instrument) else [("US", "en")]
    for region, language in regions:
        items.extend(
            rss.fetch_feed(rss.google_news_url(query, region=region, language=language))
        )
        for item in items[-_FEED_SIZE:]:
            item.tickers = [instrument.t212_ticker]

    if instrument.yahoo_symbol:
        symbol = instrument.yahoo_symbol
        region = "GB" if symbol.upper().endswith(".L") else "US"
        lang = "en-GB" if region == "GB" else "en-US"
        yahoo_items = rss.fetch_feed(rss.yahoo_news_url(symbol, region=region, language=lang))
        for item in yahoo_items:
            item.tickers = [instrument.t212_ticker]
        items.extend(yahoo_items)

    if finnhub is not None and finnhub.configured and instrument.yahoo_symbol:
        # Finnhub takes the bare symbol, without the exchange suffix.
        bare = instrument.yahoo_symbol.split(".")[0]
        items.extend(finnhub.company_news(bare))

    if marketaux is not None and marketaux.configured and instrument.yahoo_symbol:
        bare = instrument.yahoo_symbol.split(".")[0]
        items.extend(marketaux.news([bare]))

    for item in items:
        if not item.tickers:
            item.tickers = [instrument.t212_ticker]
    return items


_FEED_SIZE = 50


def _is_uk(instrument: Instrument) -> bool:
    from awltux.ingest.symbols import is_uk_listing

    return is_uk_listing(instrument.exchange_name, instrument.yahoo_symbol)


#: Sources whose feed is addressed by **symbol** and returns a pool of articles rather
#: than that symbol's own news.
#:
#: A ticker from one of these is evidence that the feed was *asked*, not that the story
#: concerns the instrument. Measured 2026-10-07: 21 `yahoo_rss` rows carried more than
#: three tickers and 49 more than one, because `?s=PET.L` returns a shared pool of
#: investment-trust announcements and `_merge_duplicate` appended a ticker for every
#: instrument whose feed happened to return the same article --
#:
#:     id=6572  tickers=8  feed=s=PET.L
#:       "Fidelity Asian Values Plc - Transaction in Own Shares"
#:       PETl_EQ, ARRl_EQ, PMPl_EQ, AVGl_EQ, SCFl_EQ, PENl_EQ, BGFDl_EQ, CYNl_EQ
#:
#: Nobody in that list is the subject, and the feed's own symbol is not either. Google
#: News is not in this set on purpose: its feed is a *query for the company's name*, so
#: a result is at least about what was asked for, and a story naming two companies is
#: the case the union exists to serve.
SYMBOL_POOLED_SOURCES = frozenset({"yahoo_rss"})


def _merge_target(existing: NewsItem, item: RawNewsItem) -> None:
    """Add a second feed's instrument to a story that is already stored.

    Only the target is added. The direction and materiality are the story's --
    judged once, against whichever instrument's feed found it first -- and
    pretending otherwise per instrument would need a judgement per instrument.

    A story from a symbol-addressed feed contributes **nothing**: see
    :data:`SYMBOL_POOLED_SOURCES`. The row keeps the ticker of the feed that stored it,
    and no second feed can add another on the strength of having been asked.
    """
    if item.source in SYMBOL_POOLED_SOURCES:
        return
    tickers = list(existing.tickers or [])
    for ticker in item.tickers or []:
        if ticker not in tickers:
            tickers.append(ticker)
    existing.tickers = tickers

    sectors = list(existing.sectors or [])
    for sector in item.sectors or []:
        if sector not in sectors:
            sectors.append(sector)
    existing.sectors = sectors


def _apply_relevance(row: NewsItem, *, about: bool | None) -> None:
    """Record whether this story is a claim about a share price.

    ``None`` where nothing has judged it yet -- an item stored before the
    classifier was configured, or one whose classification failed. That is left
    NULL rather than defaulted to false, because "not assessed" is worth chasing
    and "assessed as irrelevant" is not.
    """
    if row.direction is None and row.materiality is None and about is None:
        return
    verdict = assess(
        tickers=row.tickers,
        sectors=row.sectors,
        direction=row.direction,
        materiality=row.materiality,
        about=about,
    )
    row.relevant = verdict.relevant
    if not row.relevance_reason:
        # The structural reason, used only where the model gave none.
        row.relevance_reason = verdict.reason


#: Google News renders a headline as "Headline - Publisher". That suffix is the only
#: part that differs when a wire story is carried by two outlets, so it is the part the
#: title key drops.
_PUBLISHER_SEPARATOR = " - "

#: The shortest "headline" that may be left after stripping. A short remainder means the
#: separator was part of the headline rather than a masthead -- "Form 8.3 - [ADVANCED
#: MEDICAL SOLUTIONS GROUP PLC - 02 10 2026]" would otherwise key on "Form 8.3" and
#: merge every filing of that kind into one.
_MIN_HEADLINE_CHARS = 25


def title_key(title: str) -> str:
    """A digest of a headline that ignores the publisher carrying it.

    The same wire story syndicated by two outlets arrives as two rows with two URLs, so
    `url_hash` cannot see the duplication and each copy bought its own model call.
    Matching on the headline *with the masthead removed* is what lets the second copy
    reuse the first's verdict.

    **The whole headline is digested, not a prefix.** Measured 2026-10-07 over 26,008
    stored headlines, a 40-character prefix matches 3,028 repeats (11.6%) -- twice as
    many -- but **972 of those prefixes merge two or more genuinely different
    headlines**, covering 2,723 rows, and the difference is often the company itself:
    "What is the current Price Target and Forecast for 5E Advanced Materials (FEAM)" and
    the same sentence about "Aeon Biopharma, Inc. (AEON)" are one prefix and two
    companies. Copying a verdict through that key would stamp one company's judgement
    onto another's row, silently. Stripping the masthead and matching the rest finds
    1,570 (6.0%), and every group checked was one story under two names.
    """
    normalised = re.sub(r"\s+", " ", title or "").strip().lower()
    head, separator, _tail = normalised.rpartition(_PUBLISHER_SEPARATOR)
    if separator and len(head) >= _MIN_HEADLINE_CHARS:
        normalised = head
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _verdict_of(row: NewsItem) -> dict[str, Any]:
    """A stored row's judgement, shaped like a classifier's answer.

    Only the judgement: not the tickers and not the sectors, which belong to the feed
    that found the story rather than to the story itself.
    """
    return {
        "materiality": row.materiality,
        "direction": row.direction,
        "horizon": row.horizon,
        "sentiment_score": row.sentiment_score,
        "relevance": row.relevance,
        "engine": row.engine,
        "event_type": row.event_type,
        "metric": row.metric,
        "period": row.period,
        "magnitude": row.magnitude,
        "reasoning": row.relevance_reason,
    }


def _reusable_verdict(
    session: Session, item: RawNewsItem, instrument: Instrument | None
) -> NewsItem | None:
    """An already-judged copy of this headline, or ``None`` to classify it properly.

    **Only a verdict reached for the same instrument is reused.** ``is_about_this_company``
    is answered *against a subject*, so a headline judged for one company is not an answer
    about another; borrowing it would attribute a judgement nobody made. The ticker has to
    be in the earlier row's own list for that reason, which also keeps a story that merely
    passes through a feed from inheriting the verdict of the company it mentioned.

    The rows this returns are the reason the column is indexed: this runs once per new
    story, and a scan of `news_item` per story is the cost the reuse is meant to avoid.
    """
    if instrument is None:
        return None

    candidates = session.execute(
        select(NewsItem)
        .where(NewsItem.title_key == title_key(item.title))
        .where(NewsItem.engine.isnot(None))
        .order_by(NewsItem.id.asc())
    ).scalars().all()

    for candidate in candidates:
        if instrument.t212_ticker in (candidate.tickers or []):
            return candidate
    return None


def _judge(
    session: Session,
    row: NewsItem,
    item: RawNewsItem,
    *,
    instrument: Instrument | None,
    classifier: Classifier | None,
    report: NewsIngestReport,
) -> None:
    """Settle this story's verdict: reuse a judged copy of the headline, or buy one.

    Two ways to arrive at the same place, and which one applies is a property of the
    *story* rather than of the caller -- so it is named here instead of being a branch
    threaded through the insert loop.

    A reused verdict copies ``relevant`` as well as the classification fields.
    ``is_about_this_company`` was answered against the earlier row's subject and is not
    recoverable from the columns, so re-running the rule here would re-derive it from a
    guess rather than reproduce the verdict that was actually reached.
    """
    reused = _reusable_verdict(session, item, instrument)
    if reused is not None:
        report.reused += 1
        apply_classification(row, _verdict_of(reused))
        row.relevant = reused.relevant
        return

    # The classifier's answer to "is this even about that company", kept so the
    # relevance rule can tell a connection from a passing mention.
    about: bool | None = None
    if classifier is not None:
        # Release SQLite's write lock before classifying. The previous iteration's
        # flush left a transaction open, and a model call takes seconds: holding it
        # here is what made a concurrent job fail with "database is locked". The lock
        # is also released inside the model client; this is the same guarantee stated
        # where the slow call is.
        release_write_lock(session)
        try:
            updates = classifier(item, instrument)
        except Exception as exc:
            # A classifier failure must not lose the headline.
            logger.warning("classification failed for %r: %s", item.title[:80], exc)
            updates = None
        if updates:
            report.classified += 1
            about = updates.get("is_about_this_company")
            apply_classification(row, updates)
            if updates.get("tickers"):
                row.tickers = list({*row.tickers, *updates["tickers"]})
            if updates.get("sectors"):
                row.sectors = list({*row.sectors, *updates["sectors"]})

    _apply_relevance(row, about=about)


def _merge_duplicate(existing: NewsItem, item: RawNewsItem, report: NewsIngestReport) -> None:
    """Fold a story we already hold into the row we hold it as.

    The same story surfaces in more than one instrument's feed, and a story about two
    companies is exactly the case the news page exists to show. This used to `continue`
    without recording the second ticker, so a row's ticker list could never hold more
    than the one feed that happened to win -- every stored item had exactly one, in a
    database of five thousand.

    The direction and materiality stay those of the first classification.
    Per-instrument judgements would need a link table and a second classifier call per
    instrument; until that exists, the page says the judgement is the story's rather
    than the instrument's.

    **No classifier call happens here**, which is what makes a story processed once: the
    row's existence is the marker, and this is the branch that honours it.
    """
    _merge_target(existing, item)
    report.duplicates += 1


def persist_items(
    session: Session,
    items: Iterable[RawNewsItem],
    *,
    classifier: Classifier | None = None,
    report: NewsIngestReport | None = None,
    instrument: Instrument | None = None,
) -> NewsIngestReport:
    """Insert new items, skipping ones already stored. Returns a report."""
    report = report or NewsIngestReport()

    for item in items:
        # Checked *between* articles, because that is where a story ends: the flag is
        # read here rather than raised on so that the articles already classified for
        # this instrument are still committed by the caller. Leaving by exception here
        # would throw away up to a feed's worth of model calls, which is the one thing a
        # stop must not do -- it is meant to save work, not repeat it.
        if progress.stop_requested():
            report.stopped_early = True
            return report

        report.fetched += 1
        # Every tenth article, and the count is the one that has just been reached --
        # this is the only place it advances per article, because every new story costs
        # a model call here.
        if report.fetched % PROGRESS_EVERY_ARTICLES == 0:
            progress.note(
                f"{report.fetched} articles: {report.written} new, "
                f"{report.classified} classified"
                + (f" ({instrument.t212_ticker})" if instrument is not None else "")
            )
        report.by_source[item.source] = report.by_source.get(item.source, 0) + 1

        url_hash = item.url_hash
        existing = session.execute(
            select(NewsItem).where(NewsItem.url_hash == url_hash).limit(1)
        ).scalar_one_or_none()
        if existing is not None:
            _merge_duplicate(existing, item, report)
            continue

        row = NewsItem(
            source=item.source,
            url=item.url,
            url_hash=url_hash,
            title_key=title_key(item.title),
            title=item.title[:768],
            summary=item.summary,
            published_at=item.published_at,
            tickers=list(item.tickers),
            sectors=list(item.sectors),
            provider_sentiment=item.provider_sentiment,
            raw=item.raw,
            created_at=utcnow(),
        )

        _judge(
            session,
            row,
            item,
            instrument=instrument,
            classifier=classifier,
            report=report,
        )

        # Flush inside the loop so the dedupe lookup sees rows added in this same
        # batch; without it, two copies of one story in a single feed both insert.
        #
        # The savepoint is not decoration. The unique index on ``url_hash`` is the
        # real duplicate guard and the lookup above is only an optimisation, so two
        # overlapping ingests can both pass the lookup and only one can win the
        # insert. That race killed the whole job with an IntegrityError -- and it is
        # reachable, because ``SchedulerService.run_now`` calls the job directly and
        # so bypasses APScheduler's ``max_instances=1``. A story already stored is a
        # duplicate, not an error.
        try:
            with session.begin_nested():
                session.add(row)
                session.flush()
        except IntegrityError:
            report.duplicates += 1
            continue
        report.written += 1

    return report


def _instruments_to_poll(
    session: Session, *, tickers: list[str] | None, limit_instruments: int | None
) -> list[Instrument]:
    """Which instruments this run polls, and in what order.

    **The order is the cursor.** Least recently polled first, never-polled ahead of
    everything, which is what makes a run continue where the last one stopped and what
    makes the sweep wrap without anything resetting a counter: once every row has been
    stamped, the least recently polled is the one polled first last time.

    ``nullsfirst`` matters more than it looks. A universe that has never been polled is
    all nulls, and without it the order would be arbitrary on the very first run -- which
    is the one where the whole list has to be covered.

    ``Instrument.updated_at`` is the obvious column and the wrong one: nothing in this
    job otherwise touches the instrument row, but plenty of other jobs do, so it would
    order the poll by whatever ran last. ``sync_xbrl_fundamentals`` documents the same
    trap for its own rotation.
    """
    statement = (
        select(Instrument)
        .where(Instrument.in_universe.is_(True))
        .where(Instrument.excluded.is_(False))
        .order_by(Instrument.news_polled_at.asc().nullsfirst(), Instrument.t212_ticker.asc())
    )
    if tickers:
        statement = statement.where(Instrument.t212_ticker.in_(tickers))
    else:
        # A sweep skips instruments a scoped refresh holds, so the poll and the refresh
        # cannot both be writing this company's stories. The cursor is unaffected either
        # way: a skipped instrument keeps its stamp and comes round again next run.
        from awltux.ingest.lease import exclude_locked

        statement = exclude_locked(statement, session)
    instruments = list(session.execute(statement).scalars().all())

    if limit_instruments:
        # Prioritise held names when the poll is rationed -- but a *stable* sort, so the
        # rotation survives inside each group. The obvious `sort(key=(not held, ticker))`
        # would put every rationed run back at the same instrument and the cursor would
        # never advance, which is the bug this ordering exists to fix.
        instruments = sorted(instruments, key=lambda row: not row.is_held)[:limit_instruments]
    return instruments


class _Feeds(NamedTuple):
    """The three news providers, opened once per run and closed together."""

    rss: Any
    finnhub: Any
    marketaux: Any

    def close(self) -> None:
        self.rss.close()
        self.finnhub.close()
        self.marketaux.close()


def _marketaux_slice(
    instruments: list[Instrument], *, allowance: int
) -> set[str]:
    """Which instruments this run spends the marketaux allowance on.

    **The day's allowance is a fraction of the book, so the choice has to rotate.** 100
    requests a day, one request per instrument, 500 instruments: any pass covers a fifth.
    Spending it on whatever the poll reached first gave the quota to an arbitrary fifth,
    and spent it inside the first couple of hours of the window, so the rest of the day
    had no marketaux at all.

    Ordering by `marketaux_polled_at` -- never asked first, then longest-waiting -- makes
    the quota itself the rotation: at three an hour the book comes round in about a week,
    and yesterday's names are not today's. Ties break on the ticker so "which three this
    hour" is answerable rather than whatever order the poll loaded.
    """
    if allowance <= 0:
        return set()
    ordered = sorted(instruments, key=_marketaux_age)
    return {row.t212_ticker for row in ordered[:allowance]}


def _marketaux_age(row: Instrument) -> tuple[int, float, str]:
    """Sort key for the rotation: never asked first, then the longest wait."""
    stamp = row.marketaux_polled_at
    if stamp is None:
        return (0, 0.0, row.t212_ticker)
    # `as_utc`, because SQLite hands back a naive datetime whatever the column declares
    # and a naive/aware comparison raises rather than sorting.
    return (1, as_utc(stamp).timestamp(), row.t212_ticker)


def _marketaux_allowance(settings: Settings, marketaux: Any) -> int:
    """How many marketaux requests this run may spend.

    A day's quota divided by the runs in a day, so the allowance lasts the day instead
    of being spent by the first run after midnight. Derived from the budget rule and the
    poll's interval rather than configured separately: two numbers that must agree is
    one number too many.
    """
    runs_per_day = max(1, int(86400 // max(1, settings.schedule.news_rss)))
    return marketaux.requests_this_run(runs_per_day=runs_per_day)


def _poll_instrument(
    session: Session,
    instrument: Instrument,
    feeds: _Feeds,
    *,
    settings: Settings,
    prefilter: Prefilter,
    classifier: Classifier | None,
    report: NewsIngestReport,
    ask_marketaux: bool = True,
) -> None:
    """Gather one instrument's feeds and store what survives the prefilter.

    Leaves the instrument's articles uncommitted: the caller commits them together with
    the cursor, so that a crash cannot save one without the other. Raises nothing -- a
    provider failure is recorded on the report and the walk continues, because one dead
    feed is not a reason to abandon the universe.

    ``ask_marketaux`` is False for every instrument outside the day's rationed slice.
    """
    try:
        gathered = gather_for_instrument(
            instrument,
            settings=settings,
            rss=feeds.rss,
            finnhub=feeds.finnhub,
            marketaux=feeds.marketaux if ask_marketaux else None,
        )
    except BudgetExhausted:
        # Not a provider failure: the *allowance* is gone. Raised to the sweep, which
        # ends with the cursor where it is rather than walking the rest of the universe
        # fetching nothing and stamping each instrument as polled.
        raise
    except Exception as exc:
        report.errors.append(f"{instrument.t212_ticker}: {exc}")
        return

    kept = []
    for item in gathered:
        if prefilter.keep(item, instrument):
            kept.append(item)
        else:
            report.prefiltered_out += 1

    persist_items(
        session,
        kept[: settings.news.max_items_per_feed_poll],
        classifier=classifier,
        report=report,
        instrument=instrument,
    )


def _finish_instrument(
    session: Session,
    instrument: Instrument,
    report: NewsIngestReport,
    *,
    position: int,
    total: int,
    asked_marketaux: bool = False,
) -> None:
    """Commit this instrument's articles together with its cursor, or leave instead.

    Stamped before the release, so the cursor and the commit that makes the articles
    durable are the same transaction: a crash between them would either re-poll an
    instrument whose stories were saved (cheap) or skip one whose were not (a lost gap),
    and this order makes it the cheap one.

    The release is also where SQLite's write lock is given up between instruments. This
    loop makes roughly a thousand HTTP requests for a 500-instrument universe, and
    holding one transaction across all of them locked every other writer out for minutes.

    **A half-read feed is not stamped.** `stopped_early` means the rest of that
    instrument's articles were never read, so the cursor would be claiming a poll that
    did not happen -- and the unread articles would then be dropped until the sweep came
    round again. Leaving it unstamped puts the instrument first in the queue next run;
    the articles written before the stop are committed here either way, and re-polling
    costs nothing because a stored story is recognised by its `url_hash`.
    """
    if report.stopped_early:
        release_write_lock(session)
        raise progress.Stopped(
            f"{position} of {total} instruments, part-way through {instrument.t212_ticker}"
        )

    instrument.news_polled_at = utcnow()
    if asked_marketaux:
        # The rationed provider's own cursor, stamped in the same transaction: the
        # articles it returned and the record that it was asked travel together, so a
        # rollback cannot mark a day's allowance as spent on an instrument whose news
        # was never stored.
        instrument.marketaux_polled_at = utcnow()
    release_write_lock(session)


def ingest_rss_news(
    session: Session,
    *,
    settings: Settings | None = None,
    tickers: list[str] | None = None,
    classifier: Classifier | None = None,
    limit_instruments: int | None = None,
) -> NewsIngestReport:
    """Poll RSS (and optional Finnhub/Marketaux) for the universe."""
    settings = settings or get_settings()
    report = NewsIngestReport()
    prefilter = Prefilter(settings)

    instruments = _instruments_to_poll(
        session, tickers=tickers, limit_instruments=limit_instruments
    )

    feeds = _Feeds(
        rss=RssNewsProvider(settings),
        finnhub=FinnhubNewsProvider(settings),
        marketaux=MarketauxNewsProvider(settings),
    )
    marketaux_slice = (
        _marketaux_slice(
            instruments,
            allowance=_marketaux_allowance(settings, feeds.marketaux),
        )
        if feeds.marketaux.configured
        else set()
    )
    report.marketaux_allowance = len(marketaux_slice)

    try:
        for position, instrument in enumerate(instruments, start=1):
            # The instrument boundary is the cheapest place to leave: the previous
            # instrument's articles and its cursor were committed together on the last
            # pass through this loop, so stopping here costs nothing at all. Checked
            # before gathering rather than after, because `gather_for_instrument` makes
            # one to three HTTP requests and there is no reason to spend them on a walk
            # that is already over.
            progress.barrier(f"{position - 1} of {len(instruments)} instruments")

            # The instrument throttle. `gather_for_instrument` makes one to three
            # requests and can come back with nothing, in which case no article count
            # moves -- so without this the log goes silent for exactly as long as the
            # feeds have no news, which is when a reader most wants to know it is alive.
            if position % PROGRESS_EVERY_INSTRUMENTS == 0:
                progress.note(
                    f"{position} of {len(instruments)} instruments: "
                    f"{report.fetched} articles, {report.written} new"
                )

            asked_marketaux = instrument.t212_ticker in marketaux_slice
            try:
                _poll_instrument(
                    session,
                    instrument,
                    feeds,
                    settings=settings,
                    prefilter=prefilter,
                    classifier=classifier,
                    report=report,
                    ask_marketaux=asked_marketaux,
                )
            except BudgetExhausted as exc:
                # A spent *feed* allowance ends the sweep here rather than walking the
                # rest of the universe fetching nothing. This instrument keeps its old
                # cursor, so the next run resumes at it -- which is the whole point of
                # the cursor. Reported with its own reason, because nobody asked for
                # this and a deploy is what the wording usually means.
                raise progress.Stopped(
                    f"{position} of {len(instruments)} instruments", reason=str(exc)
                ) from exc

            _finish_instrument(
                session,
                instrument,
                report,
                position=position,
                total=len(instruments),
                asked_marketaux=asked_marketaux,
            )
    finally:
        feeds.close()

    logger.info("news ingest: %s", report.as_dict())
    return report


def gather_for_sector(
    sector: str,
    *,
    settings: Settings,
    rss: RssNewsProvider,
) -> list[RawNewsItem]:
    """Collect headlines about one industry sector.

    Both editions, for the same reason the per-instrument poll takes both: sector
    coverage surfaces in one and not the other, and the duplicate that costs is one
    ``url_hash`` lookup rather than a wasted model call.

    The items carry ``sectors`` and **no tickers**, which is the whole difference from
    an instrument poll: the sector is the subject, so there is no name to attribute the
    story to and nothing for the per-instrument classifier to be about.
    """
    from awltux.analysis.sectors import query_for

    query = query_for(sector)
    items: list[RawNewsItem] = []
    for region, language in (("GB", "en"), ("US", "en")):
        fetched = rss.fetch_feed(rss.google_news_url(query, region=region, language=language))
        for item in fetched:
            item.sectors = [sector]
            item.tickers = []
        items.extend(fetched)
    return items


def ingest_sector_news(
    session: Session,
    *,
    settings: Settings | None = None,
    classifier: Classifier | None = None,
    sectors: list[str] | None = None,
    rss: RssNewsProvider | None = None,
) -> NewsIngestReport:
    """Poll news for each industry sector, and classify what is new.

    A separate walk from the per-instrument poll rather than a branch inside it. The
    two have different subjects, different keys and different sizes -- eleven sectors
    against five hundred instruments -- and the instrument poll's cursor, prefilter and
    lease handling are all about instruments. Sharing the loop would mean every one of
    those grew an ``if sector`` branch.

    ``rss`` is injectable so a test can supply feeds without a network, the same way
    ``resolve_uk_companies`` takes its provider.
    """
    from awltux.analysis.sectors import SECTOR_NAMES

    settings = settings or get_settings()
    report = NewsIngestReport()
    names = list(sectors or SECTOR_NAMES)
    provider = rss or RssNewsProvider(settings)
    try:
        for position, name in enumerate(names, start=1):
            # The sector boundary is the cheapest place to leave: the previous
            # sector's articles were committed together, so stopping here costs
            # nothing -- and it is checked before the fetches, not after.
            progress.barrier(f"{position - 1} of {len(names)} sectors")
            progress.note(
                f"{position} of {len(names)} sectors ({name}): "
                f"{report.fetched} articles, {report.written} new"
            )
            try:
                items = gather_for_sector(name, settings=settings, rss=provider)
            except BudgetExhausted as exc:
                # The same clean exit as the instrument poll: the feed allowance is
                # spent, so the remaining sectors would each be asked, refused and
                # reported as "no news" for a sector nothing actually fetched.
                raise progress.Stopped(
                    f"{position} of {len(names)} sectors", reason=str(exc)
                ) from exc
            except Exception as exc:  # noqa: BLE001 - one sector must not stop the poll
                report.errors.append(f"{name}: {exc}")
                continue
            persist_items(session, items, classifier=classifier, report=report)
            session.flush()
    finally:
        if rss is None:
            provider.close()

    logger.info("sector news ingest: %s", report.as_dict())
    return report


def ingest_sector_sentiment(
    session: Session,
    *,
    settings: Settings | None = None,
    sectors: list[str] | None = None,
) -> dict[str, Any]:
    """Sample GDELT tone per sector. Keyless, so this runs without any quota cost.

    GDELT has no ticker mapping, which is exactly why it is used here rather than
    for per-stock signals: it measures the mood around a *topic*.
    """
    settings = settings or get_settings()
    gdelt = GdeltProvider(settings)
    results: dict[str, Any] = {}

    targets = sectors or sorted(
        {
            row.sector
            for row in session.execute(
                select(Instrument).where(Instrument.in_universe.is_(True))
            ).scalars().all()
            if row.sector
        }
    )

    try:
        for sector in targets[:25]:
            tone = gdelt.article_tone(f'"{sector}" stock market')
            if tone is None:
                continue
            results[sector] = {"tone": tone, "source": "gdelt"}
    finally:
        gdelt.close()
    return results
