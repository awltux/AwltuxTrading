"""What a deep-dive is allowed to read, gathered from this database and this disk.

**Nothing here fetches anything.** The whole evidence set is rows this application already
stored and files it already downloaded: the filings a refresh brought in, the news corpus
with its appraisals, the figures derived from those filings, and the latest decision. A
research run *refreshes the instrument first* (see :mod:`awltux.research.service`) and then
reads what that refresh left behind, so the answer is about the data this system has rather
than about what a search engine would return. `TODO.md` records the standing decision
against fetching article bodies and against a general web-search channel.

**The news filter is the subject's own "What it concerns" entry.** Not "the story mentions
the ticker": ``NewsItem.tickers`` is set from the feed it was fetched by, and a Google News
search for one company returns pieces that merely say its name. The stored appraisal is the
only thing that says a story is about this subject, and it exists exactly when the story has
a direct concern entry -- ``analysis.news_analysis.subjects_of`` derives the subjects from
those same two fields. So the filter and "has an appraisal for this subject" are one
predicate rather than two that have to agree, which is why a digest entry always carries the
appraisal the prompt's news rules describe.

**Ordered by the priority score, and the score is shown.** ``analysis.relevance.priority``
is materiality x credibility x recency, whose known flaw is recorded rather than hidden: the
unassessed weight (0.6) exceeds the ceiling a single-source appraisal lands under (0.25), so
a story nobody has judged outranks the same story judged single-source by roughly eleven
times. Measured 2026-10-09 over a 30-day window: of 7,641 appraisals, 7,617 were
single-source and 7,144 of those stories had no other carrier at all. The prompt is told
this, in those words, because a model handed a ranked list will otherwise read the ranking
as a verdict on truth.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import case, desc, func, literal, select
from sqlalchemy.orm import Session

from awltux.analysis.news_analysis import INSTRUMENT
from awltux.analysis.relevance import priority
from awltux.config import ResearchConfig, Settings
from awltux.db.models import (
    DecisionRun,
    Filing,
    FundamentalPeriod,
    Instrument,
    NewsAnalysis,
    NewsItem,
    utcnow,
)
from awltux.db.news import (
    appraisals_for,
    mentions_sector,
    mentions_ticker,
    news_for_sector,
    news_for_ticker,
)
from awltux.llm.extractors import truncate_middle
from awltux.timezones import as_utc

logger = logging.getLogger(__name__)

#: How many periods of stored figures are offered as quotable evidence. Three years of
#: annuals is what "how has this business gone" needs; more is prompt budget spent on
#: figures the documents below already contain in full.
FIGURE_PERIODS = 3

#: The most figures quoted from one period. The set is already ordered by usefulness, so
#: this is a display cap rather than a filter of last resort.
FIGURE_LIMIT = 24

#: The smallest a document is shrunk to before it is dropped instead. Below this a filing is
#: a title page and a heading, which is not evidence about anything.
MIN_DOCUMENT_CHARS = 20_000

#: Figures worth offering first. Ordered by how much a judgement of suitability rests on
#: them, because the cap above has to cut somewhere and cutting a revenue line to keep a
#: share count would be the wrong end.
FIGURE_ORDER = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps",
    "operating_cash_flow",
    "free_cash_flow",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "net_debt",
    "cash_and_equivalents",
    "equity",
    "shares_outstanding",
    "dividend_per_share",
)


@dataclass(slots=True)
class HeldDocument:
    """One stored filing, read as text."""

    label: str
    source: str
    filed_at: str | None
    url: str | None
    chars: int
    truncated: bool
    text: str = field(repr=False, default="")


@dataclass(slots=True)
class NewsEntry:
    """One story in the digest, with everything the ordering and the prompt rules cite."""

    headline: str
    published_at: str | None
    priority: float
    components: dict[str, Any]
    materiality: str | None
    credibility: float | None
    assessed: bool
    flags: list[str]
    carrier_count: int | None
    independent_sources: int | None
    publisher: str | None
    source: str | None
    relevance_reason: str | None
    #: The story's address, given to the model as a citation. Nothing in this application
    #: fetches it -- see the news rules in `llm/prompts.py` -- so it identifies the source
    #: rather than being something the run can read.
    url: str | None = None
    #: The headline digest used to recognise republication, and how many stories collapsed
    #: into this entry. Kept on the entry so a reader -- and the model -- can see that an
    #: entry stands for more than one story rather than inferring it from a carrier count.
    story_key: str | None = None
    merged: int = 1


@dataclass(slots=True)
class NewsDigest:
    """The ranked digest, and what it is a digest *of*."""

    entries: list[NewsEntry] = field(default_factory=list)
    window_days: int = 0
    total: int = 0
    appraised_total: int = 0
    single_source_total: int = 0

    @property
    def unappraised_total(self) -> int:
        return max(self.total - self.appraised_total, 0)

    def as_dict(self) -> dict[str, Any]:
        """The coverage half, which is what the report's provenance footer prints."""
        return {
            "window_days": self.window_days,
            "shown": len(self.entries),
            "total": self.total,
            "appraised": self.appraised_total,
            "unappraised": self.unappraised_total,
            "single_source": self.single_source_total,
        }

    def text(self) -> str:
        """The digest as the model reads it, highest priority first."""
        if not self.entries:
            return (
                f"No news story in the last {self.window_days} days concerns this directly."
            )
        counted = sum(entry.merged for entry in self.entries)
        blocks = [
            f"{len(self.entries)} distinct stories "
            f"({counted} of {self.total} in-window stories, counting republication), "
            "highest priority first:"
        ]
        for position, entry in enumerate(self.entries, start=1):
            blocks.append(f"\n{position}. {entry.headline}")
            if entry.url:
                blocks.append(f"   url {entry.url}")
            if entry.merged > 1:
                blocks.append(
                    f"   ({entry.merged - 1} further stor{'y' if entry.merged == 2 else 'ies'} "
                    "carrying this headline, collapsed into this entry)"
                )
            if entry.published_at:
                blocks.append(f"   published {entry.published_at}")
            blocks.append(
                f"   priority {entry.priority:.4f} "
                f"(materiality {entry.materiality or 'unclassified'} "
                f"x credibility {_credibility_text(entry)} "
                f"x recency {entry.components.get('recency_weight')})"
            )
            if entry.publisher or entry.source:
                blocks.append(f"   publisher {entry.publisher or entry.source}")
            if entry.flags:
                blocks.append(f"   appraisal flags {', '.join(entry.flags)}")
            if entry.carrier_count is not None:
                blocks.append(
                    f"   carried by {entry.carrier_count} story(ies) here, "
                    f"{entry.independent_sources or 0} independent origin(s)"
                )
            if entry.relevance_reason:
                blocks.append(f"   why it is relevant: {entry.relevance_reason}")
        return "\n".join(blocks)

    def urls(self) -> str:
        """The stories' addresses alone, for the prompt the reader reads and edits.

        Asked for directly: *"The suggested research prompt should contain a list of all the
        news article URL's."* The reader approving a spend can see exactly which stories the
        run has, and the addresses are in the box they can edit -- so one they judge
        irrelevant can be struck out, and the model is told whose words it is working from.

        The addresses are repeated in the digest below, beside the headline they belong to.
        That costs about 880 tokens of a 110,000-token budget and is deliberate: the prompt is
        for the reader, the document is what the model reads in order, and making one cite the
        other by position would be a cross-reference that a trimmed digest could break.
        """
        if not self.entries:
            return ""
        lines = [f"News URLs, highest priority first ({len(self.entries)}):"]
        for position, entry in enumerate(self.entries, start=1):
            lines.append(f"{position}. {entry.headline} -- {entry.url or 'no address stored'}")
        return "\n".join(lines)


@dataclass(slots=True)
class Evidence:
    """Everything one deep-dive reads, plus what it says about its own scope."""

    subject_type: str
    subject_id: str
    label: str
    documents: list[HeldDocument] = field(default_factory=list)
    news: NewsDigest = field(default_factory=NewsDigest)
    figures: str = ""
    decision: str = ""
    problems: list[str] = field(default_factory=list)
    refreshed_at: str | None = None
    #: What the context window forced out, named. Printed in the report's footer beside the
    #: problems, because "the annual report was dropped to fit" is a fact about how much the
    #: conclusion rests on.
    dropped: list[str] = field(default_factory=list)

    @property
    def document_chars(self) -> int:
        return sum(document.chars for document in self.documents)

    def inventory(self) -> str:
        """The plain-text scope, shown in the prompt box before the run is paid for.

        It names what was *not* available as well as what was, because the reader is being
        asked to approve a spend and the gaps are the part they cannot see from the outside.
        """
        lines: list[str] = []
        if self.subject_type == INSTRUMENT:
            if self.documents:
                lines.append(
                    f"- {len(self.documents)} stored filing(s), "
                    f"{self.document_chars:,} characters of text:"
                )
                for document in self.documents:
                    cut = ", truncated in the middle" if document.truncated else ""
                    lines.append(
                        f"  - {document.label} ({document.source}"
                        f"{', ' + document.filed_at if document.filed_at else ''}"
                        f"{cut})"
                    )
            else:
                lines.append("- No stored filing text: nothing readable is held for this company.")
            if self.figures:
                lines.append("- Figures already extracted from those filings, with their quotations.")
            else:
                lines.append("- No figures have been extracted for this company yet.")
            if self.decision:
                lines.append("- The most recent decision this system made about it.")
            else:
                lines.append("- No decision has been made about it yet.")
        else:
            lines.append(
                "- Sector runs read the news corpus only: the documents held here are "
                "company filings, and a sector has none of its own."
            )
        lines.append(
            f"- News: {self.news.total} stories in the last {self.news.window_days} days "
            f"concern this subject directly; {self.news.appraised_total} carry an appraisal "
            f"for it and {self.news.unappraised_total} do not. The "
            f"{len(self.news.entries)} highest-priority are given below."
        )
        lines.append(
            "- Not available, and not asked for: live quotes, broker research, analyst "
            "estimates, article text behind a paywall, or anything published since the "
            "data was last refreshed."
        )
        # The addresses themselves, so the box the reader approves names every story the run
        # was given. `NewsDigest.urls` records why the list is here as well as in the digest.
        urls = self.news.urls()
        if urls:
            lines.append("")
            lines.append(urls)
        if self.problems:
            lines.append("- Problems reading the material above:")
            lines.extend(f"  - {problem}" for problem in self.problems)
        if self.dropped:
            lines.append("- Dropped to fit the model's context window:")
            lines.extend(f"  - {entry}" for entry in self.dropped)
        return "\n".join(lines)

    def text(self) -> str:
        """The model's document: the material, then the digest, then the stored figures.

        The order is the order the deep model should weigh them: what the company itself
        published, what the world has said about it since, and finally the figures this
        system has already extracted -- each of which carries the words it was taken from,
        so a figure echoed into the report is echoed with a quotation that exists.
        """
        blocks: list[str] = []
        if self.documents:
            blocks.append("## Documents\n")
            for document in self.documents:
                blocks.append(f"### {document.label}")
                if document.url:
                    blocks.append(f"({document.url})")
                blocks.append(document.text)
        elif self.subject_type == INSTRUMENT:
            blocks.append(
                "## Documents\n\nNone held. Judge from the figures and the news below, and say "
                "plainly which parts of the conclusion rest on nothing."
            )
        blocks.append(f"\n## News, last {self.news.window_days} days\n")
        blocks.append(self.news.text())
        if self.figures:
            blocks.append("\n## Figures already extracted from the documents above\n")
            blocks.append(self.figures)
        if self.decision:
            blocks.append("\n## The most recent decision this system made\n")
            blocks.append(self.decision)
        return "\n".join(blocks)


def _credibility_text(entry: NewsEntry) -> str:
    """The credibility term as the model should read it: a number, or a stated absence."""
    if not entry.assessed or entry.credibility is None:
        return "unappraised (nothing has judged this story)"
    return f"{entry.credibility:.3f}"


def _subject_label(session: Session, subject_type: str, subject_id: str) -> str:
    """What the report is about, in the reader's words rather than a key."""
    if subject_type == INSTRUMENT:
        instrument = session.get(Instrument, subject_id)
        if instrument is not None:
            return f"{instrument.name} ({instrument.t212_ticker})"
        return subject_id
    return f"{subject_id} sector"


def _entry(item: NewsItem, appraisal: Any, *, now: dt.datetime) -> NewsEntry:
    """One digest entry. The priority and its components come from `relevance.priority`."""
    credibility = getattr(appraisal, "credibility", None)
    checked, components = priority(
        materiality=item.materiality,
        credibility=credibility,
        published_at=item.published_at,
        now=now,
    )
    return NewsEntry(
        headline=item.title,
        published_at=as_utc(item.published_at).strftime("%Y-%m-%d %H:%M UTC")
        if item.published_at
        else None,
        priority=checked,
        components=components,
        materiality=item.materiality,
        credibility=credibility,
        assessed=credibility is not None,
        flags=list(getattr(appraisal, "flags", None) or []),
        carrier_count=getattr(appraisal, "carrier_count", None),
        independent_sources=getattr(appraisal, "independent_sources", None),
        publisher=item.publisher or item.source,
        source=item.source,
        relevance_reason=item.relevance_reason,
        url=item.url,
        story_key=item.title_key,
    )


def news_digest(
    session: Session,
    *,
    subject_type: str,
    subject_id: str,
    window_days: int,
    limit: int,
    now: dt.datetime | None = None,
) -> NewsDigest:
    """The stories that concern this subject directly, ranked by priority.

    The window is applied in SQL by the same predicate the count uses, and the appraisal is
    the one written *for this subject* -- a story naming a company and an industry has two,
    and the sector page must read the sector's.
    """
    moment = now or utcnow()
    since = moment - dt.timedelta(days=window_days)
    digest = NewsDigest(window_days=window_days)

    if subject_type == INSTRUMENT:
        items, digest.total = news_for_ticker(
            session, subject_id, since=since, limit=_scan_limit(limit)
        )
    else:
        items, digest.total = news_for_sector(
            session, subject_id, since=since, limit=_scan_limit(limit)
        )

    # Counted over the whole window, not over the rows ranked below: the inventory tells the
    # reader how much news this company has and how much of it has been judged, and a figure
    # taken from the top few hundred rows would understate both on exactly the instruments
    # that have the most news.
    appraised, single = _coverage(
        session, subject_type=subject_type, subject_id=subject_id, since=since
    )
    if appraised > digest.total:
        # Two statements, one predicate. If they disagree, one of them is wrong and the
        # reader is about to be told "186 of 116 stories carry an appraisal" -- so the page
        # gets the number that cannot be absurd and the log gets the discrepancy.
        logger.warning(
            "news coverage for %s %s: %d appraised over %d stories; clamping",
            subject_type,
            subject_id,
            appraised,
            digest.total,
        )
        appraised = digest.total
    digest.appraised_total = appraised
    digest.single_source_total = min(single, appraised)

    appraisals = appraisals_for(session, items, subject=(subject_type, subject_id))
    entries = [_entry(item, appraisals.get(item.id), now=moment) for item in items]
    entries.sort(key=lambda entry: entry.priority, reverse=True)
    collapsed = _collapse_headlines(entries)
    digest.entries = collapsed[:limit]
    return digest


def _collapse_headlines(entries: list[NewsEntry]) -> list[NewsEntry]:
    """One entry per story, keeping the highest-priority copy of a syndicated headline.

    ``NewsItem.title_key`` is the headline digest with its " - Publisher" suffix dropped,
    which is the part that differs when a wire story is reprinted -- so five rewrites of one
    announcement become one entry rather than five of the twelve slots. What it does *not*
    catch is a publisher that rewords the headline, and the prompt is told so: coverage
    volume is not corroboration, and the per-entry carrier counts say how much of it there is.
    """
    kept: dict[str, NewsEntry] = {}
    merged: dict[str, int] = {}
    for entry in entries:
        key = entry.story_key or _normalise(entry.headline)
        if key in kept:
            merged[key] = merged.get(key, 1) + 1
            continue
        kept[key] = entry
        merged[key] = 1
    for key, count in merged.items():
        kept[key].merged = count
    return list(kept.values())


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _coverage(
    session: Session, *, subject_type: str, subject_id: str, since: dt.datetime
) -> tuple[int, int]:
    """``(appraised, single_source)`` over every in-window story concerning the subject.

    ``single_source`` is tested with ``json_each`` over the appraisal's flag list rather than
    with a ``LIKE`` on the JSON text: the flags are a list of distinct tokens, one of which
    could later contain another as a substring, and a count that silently starts matching two
    flags is the kind of number nobody re-derives.
    """
    tags = func.json_each(NewsAnalysis.flags).table_valued("value")
    flagged = (
        select(literal(1))
        .select_from(tags)
        .where(tags.c.value == "single_source")
        .exists()
    )
    statement = (
        select(func.count(), func.sum(case((flagged, 1), else_=0)))
        .select_from(NewsAnalysis)
        .join(NewsItem, NewsItem.id == NewsAnalysis.news_item_id)
        .where(NewsAnalysis.subject_type == subject_type)
        .where(NewsAnalysis.subject_id == subject_id)
        .where(_concerns(subject_type, subject_id))
        .where(NewsItem.published_at >= since)
    )
    appraised, single = session.execute(statement).one()
    return int(appraised or 0), int(single or 0)


def _concerns(subject_type: str, subject_id: str):
    """The direct-concern predicate for one subject, from the module that owns it."""
    if subject_type == INSTRUMENT:
        return mentions_ticker(subject_id)
    return mentions_sector(subject_id)


def _scan_limit(limit: int) -> int:
    """How many rows to rank before taking the top ``limit``.

    The ranking is computed in Python -- it needs the appraisal's credibility and the age
    decay -- so the window has to be widened to be sure the highest-priority story is in it.
    A story ranks high because it is *recent* and material; under a three-day half-life a
    story a few hundred places back in publication order cannot outrank one published today
    unless the new one is classified ``none``, and those are the ones this is willing to miss.
    """
    return max(limit * 25, 100)


def held_documents(
    session: Session,
    settings: Settings,
    ticker: str,
    *,
    limit: int,
    max_document_chars: int,
    max_total_chars: int,
) -> tuple[list[HeldDocument], list[str]]:
    """The company's own published documents, newest first, as text.

    Only filings whose stored file can still be read: a row whose document was never
    downloaded, or whose PDF has no text extractor, is reported as a problem rather than
    silently omitted, because the reader is being asked to accept a conclusion drawn
    without it.
    """
    from awltux.ingest.parsing import document_text

    rows = list(
        session.execute(
            select(Filing)
            .where(Filing.instrument_t212_ticker == ticker)
            .where(Filing.raw_path.is_not(None))
            .order_by(desc(Filing.filed_at), desc(Filing.id))
            .limit(limit * 4)
        ).scalars().all()
    )

    documents: list[HeldDocument] = []
    problems: list[str] = []
    spent = 0
    for filing in rows:
        if len(documents) >= limit or spent >= max_total_chars:
            break
        path = Path(settings.data_dir) / (filing.raw_path or "")
        text = document_text(path)
        if not text:
            problems.append(
                f"{filing.filing_type or 'filing'} of "
                f"{filing.filed_at.date() if filing.filed_at else 'unknown date'}: "
                "the stored document could not be read as text"
            )
            continue
        allowance = min(max_document_chars, max_total_chars - spent)
        trimmed, truncated = truncate_middle(text, allowance)
        spent += len(trimmed)
        documents.append(
            HeldDocument(
                label=_filing_label(filing),
                source=filing.source,
                filed_at=filing.filed_at.date().isoformat() if filing.filed_at else None,
                url=filing.url,
                chars=len(trimmed),
                truncated=truncated,
                text=trimmed,
            )
        )
    return documents, problems


def _filing_label(filing: Filing) -> str:
    """A filing as a citation: what kind of document it is and when it was filed."""
    kind = filing.filing_type or "filing"
    when = filing.filed_at.date().isoformat() if filing.filed_at else "undated"
    period = f", period to {filing.period_end.isoformat()}" if filing.period_end else ""
    title = f" -- {filing.title}" if filing.title else ""
    return f"{kind} filed {when}{period}{title}"


def stored_figures(session: Session, ticker: str, *, periods: int = FIGURE_PERIODS) -> str:
    """The figures this system already extracted, each with the words it was taken from.

    Only metrics that carry a recorded span are offered. A figure without one is a number
    this system cannot show its work for, and handing it to a model that is required to
    quote its evidence would invite a quotation to be invented for it -- which is the one
    failure the extraction gate exists to prevent.
    """
    rows = list(
        session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == ticker)
            .order_by(desc(FundamentalPeriod.period_end))
        ).scalars().all()
    )
    if not rows:
        return ""

    # One row per period, best source first, newest period first -- the same preference
    # order the valuation reads, so the deep-dive and the decision see one set of figures.
    from awltux.analysis.fundamental import SOURCE_PREFERENCE

    chosen: dict[Any, FundamentalPeriod] = {}
    for row in rows:
        key = (row.period_end, row.period_type)
        current = chosen.get(key)
        if current is None or SOURCE_PREFERENCE.get(row.source, 0) > SOURCE_PREFERENCE.get(
            current.source, 0
        ):
            chosen[key] = row
    wanted = [row for row in sorted(
        chosen.values(), key=lambda row: row.period_end, reverse=True
    ) if _figure_names(row.metrics, row.metric_sources or {})]

    blocks: list[str] = []
    for row in wanted[:periods]:
        blocks.append(
            f"\n{row.period_end.isoformat()} ({row.period_type}, {row.source}"
            f"{', ' + row.currency if row.currency else ''}):"
        )
        quoted = 0
        sources = row.metric_sources or {}
        for name in _figure_names(row.metrics, sources):
            if quoted >= FIGURE_LIMIT:
                break
            entry = sources.get(name) or {}
            # Collapsed to one line: a filing's span can be a table row torn out with its
            # newlines intact, and a quotation that runs over five lines reads as five
            # quotations when the model cites it back.
            span = " ".join(str(entry.get("span") or "").split())
            if not span or name not in row.metrics:
                continue
            location = " ".join(str(entry.get("location") or "").split())
            blocks.append(
                f'  {name} = {row.metrics[name]}  quoted: "{span}"'
                f"{' (' + location + ')' if location else ''}"
            )
            quoted += 1
    return "\n".join(blocks)


def _figure_names(metrics: dict[str, Any], sources: dict[str, Any]) -> list[str]:
    """The period's metrics, most useful first, with the ones nobody can quote dropped.

    A period with no quotable figure at all is skipped by the caller rather than printed as
    an empty heading: three slots of "no quoted figures" would push out the annual reports a
    reader actually came for, and the provider-sourced periods are the ones that land there.
    """
    quotable = [name for name in sources if name in metrics]
    ranked = [name for name in FIGURE_ORDER if name in quotable]
    rest = sorted(name for name in quotable if name not in FIGURE_ORDER)
    return ranked + rest


def decision_note(session: Session, ticker: str) -> str:
    """The last decision this system made, in one line, or an empty string.

    Included because the report is meant to *contribute* to that decision, and a run that
    does not know what the system currently thinks cannot say what it disagrees with.
    """
    from awltux.web.templating import fmt_ago

    row = session.execute(
        select(DecisionRun)
        .where(DecisionRun.instrument_t212_ticker == ticker)
        .order_by(desc(DecisionRun.created_at))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return ""
    made = as_utc(row.created_at)
    gate = "allowed" if row.gate_allowed else "refused by the risk gate"
    confidence = f"{row.confidence:.2f}" if row.confidence is not None else "unknown"
    return (
        f"{made.date().isoformat()} ({fmt_ago(made)}): "
        f"{row.long_term_action or 'no long-term action'}, "
        f"confidence {confidence}, {gate}, engine {row.engine}. "
        "This is the system's own view, not an input document -- it may be wrong, and saying "
        "where you disagree with it is useful."
    )


def build_evidence(
    session: Session,
    settings: Settings,
    *,
    subject_type: str,
    subject_id: str,
    now: dt.datetime | None = None,
) -> Evidence:
    """Assemble the whole evidence set for one subject, trimmed to the context window.

    Instruments get documents, figures and the last decision; sectors get the news corpus,
    because a sector's evidence in this database *is* the news -- there is no sector filing
    and no sector refresh, and the report says so rather than implying the absence is a
    finding.
    """
    config = settings.research
    moment = now or utcnow()
    evidence = Evidence(
        subject_type=subject_type,
        subject_id=subject_id,
        label=_subject_label(session, subject_type, subject_id),
    )
    evidence.news = news_digest(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        window_days=config.news_digest_days,
        limit=config.news_digest_limit,
        now=moment,
    )
    if subject_type == INSTRUMENT:
        documents, problems = held_documents(
            session,
            settings,
            subject_id,
            limit=config.max_documents,
            max_document_chars=config.max_document_chars,
            max_total_chars=config.max_total_document_chars,
        )
        evidence.documents = documents
        evidence.problems = problems
        evidence.figures = stored_figures(session, subject_id)
        evidence.decision = decision_note(session, subject_id)
    _fit_to_context(evidence, config)
    return evidence


def _fit_to_context(evidence: Evidence, config: ResearchConfig) -> None:
    """Drop the least load-bearing material until the prompt fits the model's window.

    Measured 2026-10-09: MSFT's evidence -- two 10-Ks, the digest, the stored figures and the
    last decision -- is 410,826 characters, about 120,800 tokens, against a 128,000-token
    window with a 16,000-token answer requested.

    **The order is by what a removal buys, not by what reads as least important.** The first
    version shed the decision, then the figures, then the news digest, and only then touched
    the documents -- and on the measurement above it deleted every headline, the figures and
    the decision, and *still* had to shrink a document, because the documents are 95% of the
    prompt and nothing else can bring it under the budget. Removing 5,000 characters to save
    1,500 tokens, at the cost of a whole input the prompt has a section about, is the wrong
    trade however low the block ranks. So:

    1. the documents, oldest first, shrunk as the extractor would shrink them -- head and tail
       kept -- and dropped outright only once one is down to its floor;
    2. the extracted figures, which are in the documents themselves;
    3. the previous decision, one line the model is told is not an input document;
    4. the tail of the news digest, which is already the bottom of a ranking.

    The totals in ``research.*`` are what the caller asked for; this is the window refusing
    them. It is applied here rather than in the config so the reader can raise the document
    budget without producing a request the provider rejects.
    """
    from awltux.analysis.state import estimate_tokens

    budget = config.context_tokens - config.max_output_tokens - config.reserve_tokens

    def over() -> bool:
        return estimate_tokens(evidence.text()) > budget

    if not over():
        return

    for document in list(reversed(evidence.documents)):
        if not over():
            break
        while document.chars > MIN_DOCUMENT_CHARS and over():
            _shrink(document)
        if over():
            evidence.documents.remove(document)
            evidence.dropped.append(f"the document '{document.label}'")
        else:
            evidence.dropped.append(f"the middle of '{document.label}', cut to fit the context")

    if evidence.documents and over():
        # One document left and still too long: its floor does not apply.
        document = evidence.documents[0]
        while document.chars > 1_000 and over():
            _shrink(document)
        evidence.dropped.append(f"the middle of '{document.label}', cut again to fit the context")

    if evidence.figures and over():
        evidence.figures = ""
        evidence.dropped.append("the quoted figures, which the documents already contain")

    if evidence.decision and over():
        evidence.decision = ""
        evidence.dropped.append("the previous decision, to fit the context window")

    while evidence.news.entries and over():
        dropped = evidence.news.entries.pop()
        evidence.dropped.append(f"the lowest-priority headline: {dropped.headline[:60]}")


def _shrink(document: HeldDocument) -> None:
    """Halve a document the way the extractor would, keeping its head and its tail."""
    document.text, document.truncated = truncate_middle(
        document.text, max(len(document.text) // 2, 1_000)
    )
    document.chars = len(document.text)


__all__ = [
    "Evidence",
    "HeldDocument",
    "NewsDigest",
    "NewsEntry",
    "build_evidence",
    "decision_note",
    "held_documents",
    "news_digest",
    "stored_figures",
]
