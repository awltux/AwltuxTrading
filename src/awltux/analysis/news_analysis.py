"""Sceptical news analysis: decide what a story is actually worth.

Runs *after* ingest and classification, never inside it. The split matters:

* Ingest is volume work on hundreds of loose headlines, and must stay cheap.
* This is per-story work -- read it, count the sources, find the primary record --
  and is spent only where it can change an answer.

The choice of what to spend it on is a set of explicit rules rather than a
relevance score, because "interesting enough" is exactly the judgement that
should be inspectable. A story qualifies if any of:

1. it is classified material or critical, or
2. it uses manipulation techniques heavily enough that the framing is the story,
   or
3. it concerns something the portfolio actually holds, or
4. it is the only coverage of its subject and the publisher is unrated.

Depth is rationed too. Every qualifying item gets the deterministic work -- the
source registry, the rhetoric scan, a corroboration count. Only items that pass a
higher bar get the model call, because that is the part that costs money and the
part that the deterministic layer cannot do.

Everything is idempotent: re-running re-appraises items whose appraisal predates
the current source registry or rhetoric lexicon, which is what makes the table a
record of *current* understanding rather than a frozen first impression.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis.corroboration import Corroboration, assess
from awltux.analysis.news_scepticism import Claim, NewsAssessment, grade
from awltux.analysis.rhetoric import RhetoricReport, analyse_text
from awltux.analysis.sources import domain_of, lookup
from awltux.config import Settings, get_settings
from awltux.db import Instrument, NewsAnalysis, NewsItem, utcnow
from awltux.db.session import release_write_lock
from awltux.scheduler import progress

logger = logging.getLogger(__name__)

#: Signature of an injected deep analyser: kwargs -> analysis dict, or None.
#: Injected rather than imported so the pipeline runs, and is testable, with no
#: model configured.
DeepAnalyser = Callable[..., dict[str, Any] | None]

#: Materiality levels that always justify a full appraisal.
_MATERIAL = {"material", "critical"}

#: Publisher kinds whose output cannot be taken at face value when it is the only
#: coverage there is.
_NEEDS_CHECKING = {"press_release", "aggregator", "opinion", "unknown"}


@dataclass(slots=True)
class AnalysisReport:
    examined: int = 0
    selected: int = 0
    #: Stories appraised for at least one subject. ``appraised`` counts *rows*, which
    #: is what the run actually wrote: a story naming three instruments contributes
    #: three, and the two numbers are the difference between "how much news was read"
    #: and "how much work was done".
    subjects: int = 0
    appraised: int = 0
    deep_analysed: int = 0
    skipped_not_interesting: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "selected": self.selected,
            "subjects": self.subjects,
            "appraised": self.appraised,
            "deep_analysed": self.deep_analysed,
            "skipped_not_interesting": self.skipped_not_interesting,
            "errors": self.errors[:10],
        }


def is_interesting(
    item: NewsItem,
    *,
    rhetoric: RhetoricReport,
    publisher_kind: str,
    held: bool,
    carrier_count: int,
    settings: Settings,
) -> tuple[bool, str]:
    """Whether this story is worth the sceptical treatment, and why.

    Returns ``(interesting, reason)``. The reason is recorded so that "the system
    ignored this story" is always answerable -- a silent filter is indistinguishable
    from a bug, which is the same reasoning behind the job notes elsewhere.
    """
    config = settings.news.scepticism
    if item.materiality in _MATERIAL:
        return True, f"classified {item.materiality}"
    if rhetoric.score >= config.rhetoric_attention_threshold:
        return True, f"manipulation markers at {rhetoric.score:.2f}"
    if held and item.materiality not in (None, "none"):
        return True, "held name with relevant news"
    if publisher_kind in _NEEDS_CHECKING and carrier_count <= 1:
        return True, f"single-source coverage from a {publisher_kind.replace('_', ' ')} publisher"
    return False, ""


@dataclass(frozen=True, slots=True)
class Subject:
    """What an appraisal is *about*: one instrument, or one sector.

    A story is a single observation and can concern several things at once, and the
    appraisal is not the same for each -- ``is_held`` is what decides whether the model
    is asked to read a piece deeply, and "the reader holds this" is a fact about the
    subject, not about the story. Storing one appraisal per story made a story about a
    held company and an unheld one carry whichever answer was written first.
    """

    type: str  # "instrument" | "sector"
    id: str

    def as_dict(self) -> dict[str, str]:
        return {"subject_type": self.type, "subject_id": self.id}


INSTRUMENT = "instrument"
SECTOR = "sector"


def subjects_of(item: NewsItem) -> list[Subject]:
    """Every subject a story is about, instruments first, each group in id order.

    Instruments before sectors because a reader's own company is the more specific
    answer, and :func:`primary_subject` takes the first -- so this order decides which
    appraisal a list page shows. Sorted rather than left in the order the feed supplied
    because the same rule is applied in SQL by the sentiment weighting, and the two
    have to agree about which appraisal is *the* one for a story. A story's tickers
    arrive in provider order, which is not a property either side can sort on.
    """
    out = [Subject(INSTRUMENT, str(ticker)) for ticker in sorted(item.tickers or [])]
    out.extend(Subject(SECTOR, str(sector)) for sector in sorted(item.sectors or []))
    return out


def primary_subject(item: NewsItem) -> Subject | None:
    """The one subject a page shows when it has room for one.

    Used by the scoring and list paths, which predate per-subject appraisals and key
    on the story. The *specific* subject is passed explicitly wherever it is known --
    an instrument page, a sector page -- because that is the whole point of the split;
    this is the answer for callers that genuinely have no subject to hand.
    """
    subjects = subjects_of(item)
    return subjects[0] if subjects else None


def _held(session: Session) -> tuple[set[str], set[str]]:
    """What the reader holds: ``(tickers, sector groups)``.

    One query rather than two, and the sector side is derived from the instrument's
    own ``sector_group`` with the mapping as a fallback -- an instrument that has not
    been through the backfill yet still counts, because "the reader holds something in
    this industry" is the fact being established and a missing column is not evidence
    against it.
    """
    from awltux.analysis.sectors import group_for

    tickers: set[str] = set()
    sectors: set[str] = set()
    rows = session.execute(
        select(Instrument).where(Instrument.is_held.is_(True))
    ).scalars().all()
    for row in rows:
        tickers.add(row.t212_ticker)
        group = row.sector_group or group_for(row.sic_code, row.sector)
        if group:
            sectors.add(group)
    return tickers, sectors


def subject_is_held(subject: Subject, tickers: set[str], sectors: set[str]) -> bool:
    """Whether the reader holds the thing an appraisal is about."""
    if subject.type == INSTRUMENT:
        return subject.id in tickers
    return subject.id in sectors


def any_is_held(subjects: list[Subject], tickers: set[str], sectors: set[str]) -> bool:
    """Whether the reader holds anything a story is about. Selection is per story."""
    return any(subject_is_held(subject, tickers, sectors) for subject in subjects)


def _recent_coverage(
    session: Session, *, days: int, limit: int = 400
) -> list[NewsItem]:
    """Recent items, newest first, used as the corroboration pool.

    One query for the whole window rather than one per story: the pool is the same
    for every item being appraised, and a per-item query here would be hundreds of
    scans of the same table.
    """
    cutoff = utcnow() - dt.timedelta(days=days)
    return list(
        session.execute(
            select(NewsItem)
            .where(NewsItem.published_at >= cutoff)
            .order_by(NewsItem.published_at.desc())
            .limit(limit)
        ).scalars().all()
    )


def appraise_item(
    item: NewsItem,
    *,
    settings: Settings,
    subject: Subject,
    analyser: DeepAnalyser | None = None,
    rhetoric: RhetoricReport | None = None,
    corroboration: Corroboration | None = None,
    is_held: bool = False,
    known_context: str | None = None,
) -> NewsAnalysis:
    """Build the appraisal row for one item, about one subject.

    Deterministic first: the publisher, the rhetoric and the corroboration count
    are all computed here, and the credibility arithmetic runs on them. The model
    call is additive -- it supplies the claims and the omissions, and can lower the
    grade by revealing that nothing checkable is being asserted, but it cannot
    raise a weight the rules have already capped.

    ``rhetoric`` and ``corroboration`` may be supplied by the caller when it has
    already computed them for selection; recomputing them here keeps the function
    usable on its own.

    ``is_held`` is about the **subject**, not the story: an instrument is held when
    the reader owns it, a sector when they own anything in it. It is the one input
    that legitimately differs between two appraisals of the same story, so a caller
    that cannot say which subject it means cannot call this.
    """
    config = settings.news.scepticism
    domain = domain_of(item.url)
    publisher = lookup(item.url) if item.url else lookup(None)

    rhetoric = rhetoric or analyse_text(item.summary or item.title, headline=item.title)
    corroboration = corroboration or Corroboration()

    should_go_deep = analyser is not None and (
        item.materiality in _MATERIAL
        or rhetoric.score >= config.rhetoric_attention_threshold
        or (item.provider_sentiment is not None and abs(item.provider_sentiment) >= 0.5)
        or (is_held and item.materiality not in (None, "none"))
    )

    deep: dict[str, Any] | None = None
    if should_go_deep:
        try:
            deep = analyser(
                title=item.title,
                summary=item.summary,
                source_name=publisher.name,
                publisher=publisher.as_dict(),
                known_context=known_context,
            )
        except Exception as exc:  # a model failure must not lose the appraisal
            logger.warning("deep news analysis failed for %r: %s", item.title[:70], exc)
            deep = None

    claims = _coerce_claims((deep or {}).get("claims"))

    assessment: NewsAssessment = grade(
        publisher=publisher,
        rhetoric=rhetoric,
        corroboration=corroboration,
        claims=claims,
        direction=item.direction,
        materiality=item.materiality,
        source_category=_category_from_event(item.event_type),
    )

    row = NewsAnalysis(
        news_item_id=item.id,
        subject_type=subject.type,
        subject_id=subject.id,
        source_domain=domain or "unknown",
        source_name=publisher.name,
        source_kind=publisher.kind,
        source_reliability=publisher.reliability,
        source_independence=publisher.independence,
        source_biases=list(publisher.biases),
        source_basis=publisher.basis,
        source_assessed=publisher.assessed,
        rhetoric_score=rhetoric.score,
        rhetoric=rhetoric.as_dict(),
        techniques=(deep or {}).get("techniques") or [],
        carrier_count=corroboration.carrier_count,
        independent_sources=corroboration.independent_count,
        corroboration=corroboration.as_dict(),
        claims=[claim.as_dict() for claim in assessment.claims],
        omissions=(deep or {}).get("omissions") or [],
        headline_matches_body=(deep or {}).get("headline_matches_body"),
        headline_overstates=(deep or {}).get("headline_overstates"),
        who_benefits=(deep or {}).get("who_benefits"),
        agenda_basis=(deep or {}).get("agenda_basis"),
        base_rate=(deep or {}).get("base_rate"),
        what_would_change_my_mind=(deep or {}).get("what_would_change_my_mind"),
        primary_source=(deep or {}).get("primary_source"),
        scepticism_summary=(deep or {}).get("scepticism_summary"),
        injection_suspected=(deep or {}).get("injection_suspected"),
        credibility=assessment.credibility,
        evidence_grade=assessment.grade,
        flags=list(assessment.flags),
        warnings=list(assessment.warnings),
        caveats=list(assessment.caveats),
        factors={
            "source_weight": assessment.source_weight,
            "corroboration_factor": assessment.corroboration_factor,
            "rhetoric_score": assessment.rhetoric_score,
            "claim_support": assessment.claim_support,
            "materiality": item.materiality,
            "direction": item.direction,
        },
        engine=(deep or {}).get("engine") or "deterministic",
        analysed_at=utcnow(),
    )
    return row


def _category_from_event(event_type: str | None) -> str | None:
    """Route a classified event type to the register its primary source lives in."""
    return {
        "earnings": "financial_result",
        "guidance": "guidance",
        "m_and_a": "ownership_change",
        "capital_raise": "financial_result",
        "regulatory": "regulatory_action",
        "legal": "legal_proceeding",
        "management_change": "financial_result",
        "product": "product_or_contract",
        "analyst": "analyst_opinion",
    }.get(event_type or "")


def _coerce_claims(raw: Any) -> list[Claim]:
    """Accept claims as :class:`Claim` objects or as the dicts they serialise to.

    The model path returns ``Claim`` instances, but an analyser is injectable and
    nothing stops one handing back the ``Claim.as_dict`` shape. Without this, such
    an analyser raises on every item and the failure is swallowed into the run's
    error list -- a pipeline quietly appraising nothing while reporting that it
    ran. Tolerating both shapes costs a few lines.
    """
    if not raw:
        return []
    claims: list[Claim] = []
    for entry in raw:
        if isinstance(entry, Claim):
            claims.append(entry)
            continue
        if not isinstance(entry, dict) or not entry.get("text"):
            continue
        claims.append(
            Claim(
                text=str(entry["text"]),
                claim_type=str(entry.get("claim_type") or "reported_fact"),
                attribution=str(entry.get("attribution") or "none"),
                span=entry.get("span"),
                primary_register=entry.get("primary_register"),
                where_to_check=entry.get("where_to_check"),
            )
        )
    return claims


def _as_utc(value: dt.datetime | None) -> dt.datetime | None:
    """SQLite hands back naive datetimes however the column was declared.

    Comparing one of those to an aware ``utcnow()`` raises rather than returning
    the wrong answer, which is how this was caught -- but only by the re-run path,
    so it is worth saying out loud: any timestamp read back out of the database
    has to be normalised before it is compared to anything.
    """
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _coverage_index(pool: list[NewsItem]) -> dict[str, list[NewsItem]]:
    """The corroboration pool indexed by the tickers each row names."""
    index: dict[str, list[NewsItem]] = {}
    for row in pool:
        for ticker in row.tickers or []:
            index.setdefault(ticker, []).append(row)
    return index


def coverage_of(item: NewsItem, index: dict[str, list[NewsItem]]) -> list[NewsItem]:
    """The pool items carrying this story, deduplicated.

    The pool used to be handed to :func:`~awltux.analysis.corroboration.assess` whole,
    which was a defect with two consequences and a cost.

    `assess` counts the candidates it is given and collapses the near-identical ones
    into origins, so measuring a story against everything published that fortnight gave
    every story the same answer -- on the live database, a headline about Apple and one
    about an unrelated micro-cap both returned `carrier_count=400, independent_count=7`.
    That meant `is_interesting`'s single-source condition (`carrier_count <= 1`) could
    never fire, so coverage from a press release or an aggregator was never selected;
    and every appraisal was told the story was carried by seven independent origins,
    which is what the credibility weighting reads.

    The cost was the same mistake seen from the other side: `assess` groups its
    candidates pairwise, so 400 candidates is about 80,000 title comparisons per story.
    Measured over the live pool, a story's own coverage is a median of 8 rows, and the
    per-story work falls from 5.8 seconds to 14 milliseconds.

    Ticker and window, because that is the signal available for "the same story".
    Narrowing to near-identical headlines instead would report every story as
    single-source -- `tests/test_news_scepticism.py` is explicit that coverage worded
    differently is separate reporting, not a copy.
    """
    found: dict[int, NewsItem] = {}
    for ticker in item.tickers or []:
        for row in index.get(ticker, ()):
            found[row.id] = row
    # A story the pool does not reach still has itself as one carrier, which reads as
    # single-source -- the honest answer when there is nothing to compare it to.
    return list(found.values()) or [item]


#: The appraisal columns copied onto an existing row. Every field a fresh appraisal
#: produces and nothing else: the news item's own columns, and the row's identity,
#: belong to whoever wrote them.
APPRAISAL_COLUMNS: tuple[str, ...] = (
    "source_domain", "source_name", "source_kind", "source_reliability",
    "source_independence", "source_biases", "source_basis", "source_assessed",
    "rhetoric_score", "rhetoric", "techniques", "carrier_count",
    "independent_sources", "corroboration", "claims", "omissions",
    "headline_matches_body", "headline_overstates", "who_benefits",
    "agenda_basis", "base_rate", "what_would_change_my_mind",
    "primary_source", "scepticism_summary", "injection_suspected",
    "credibility", "evidence_grade", "flags", "warnings", "caveats",
    "factors", "engine", "analysed_at",
)


def _carry_forward(prior: NewsAnalysis, fresh: NewsAnalysis) -> None:
    """Copy a fresh appraisal onto the row already stored for that story.

    Re-appraising a story updates it in place rather than inserting a second row, so a
    reader sees one assessment per story and its history is the `analysed_at` moving.
    The columns are named rather than taken from the model, because the alternative --
    `for column in fresh.__table__.columns` -- would also copy the primary key and the
    foreign key back onto the stored row.
    """
    for column in APPRAISAL_COLUMNS:
        setattr(prior, column, getattr(fresh, column))


@dataclass(slots=True)
class _Run:
    """What every appraisal in one run shares.

    Bundled rather than passed as eight arguments, because they travel together: the
    holdings, the corroboration window, the model ration and the counters the caller
    reports. The one thing that varies per appraisal -- the subject -- is a parameter.
    """

    settings: Settings
    analyser: DeepAnalyser | None
    held: set[str]
    held_sectors: set[str]
    stale_before: dt.datetime
    existing: dict[tuple[int, str, str], NewsAnalysis]
    limit: int
    report: AnalysisReport


def _analyser_for(run: _Run) -> DeepAnalyser | None:
    """The analyser this appraisal may use, or ``None`` once the ration is spent.

    The deterministic appraisal still runs either way; the paid half is what is
    rationed, because an unbounded sweep after a quiet period would run into the
    spend ceiling and leave the rest unappraised with no explanation.
    """
    if run.report.deep_analysed >= run.limit and run.analyser is not None:
        return None
    return run.analyser


def _store_appraisal(session: Session, prior: NewsAnalysis | None, row: NewsAnalysis) -> None:
    """Upsert onto the row already stored for this subject, or insert one."""
    if prior is not None:
        _carry_forward(prior, row)
        session.add(prior)
    else:
        session.add(row)


def _appraise_subject(
    session: Session,
    run: _Run,
    item: NewsItem,
    subject: Subject,
    *,
    rhetoric: RhetoricReport,
    corroboration: Corroboration,
    reason: str,
) -> None:
    """One appraisal, or a decision not to make one.

    Three outcomes and all of them are normal: the subject was appraised recently
    enough that re-running would reproduce a conclusion nothing has changed, the model
    ration is spent so only the deterministic half runs, or it is appraised properly.
    Counting them is the point -- ``appraised`` is rows written, ``deep_analysed`` is
    the part that cost money, and a run that writes rows without spending is working.
    """
    report = run.report
    report.subjects += 1

    prior = run.existing.get((item.id, subject.type, subject.id))
    prior_analysed = _as_utc(prior.analysed_at) if prior is not None else None
    if prior_analysed is not None and prior_analysed > run.stale_before:
        report.appraised += 1
        return

    analyser = _analyser_for(run)

    # Release the write lock before appraising. The appraisal is where the model call
    # happens, and the release at the end of the caller's loop body comes too late: the
    # transaction opened by the previous subject's flush would otherwise be held across
    # this subject's model call, locking out every other writer for the duration.
    release_write_lock(session)
    try:
        row = appraise_item(
            item,
            settings=run.settings,
            subject=subject,
            analyser=analyser,
            rhetoric=rhetoric,
            corroboration=corroboration,
            is_held=subject_is_held(subject, run.held, run.held_sectors),
        )
    except Exception as exc:  # noqa: BLE001 - one subject must not stop the run
        report.errors.append(f"{item.id}/{subject.type}:{subject.id}: {exc}")
        return

    if analyser is not None:
        report.deep_analysed += 1

    _store_appraisal(session, prior, row)
    report.appraised += 1
    logger.info(
        "news appraisal: %s %s [%s %s] -> %s (%s)",
        item.source,
        item.title[:60],
        subject.type,
        subject.id,
        row.evidence_grade,
        reason,
    )

    # Released between subjects: each appraisal can involve a model call taking
    # seconds, and holding a transaction across dozens of those would lock out every
    # other writer for minutes.
    session.flush()
    release_write_lock(session)


def analyse_universe(
    session: Session,
    *,
    settings: Settings | None = None,
    tickers: list[str] | None = None,
    analyser: DeepAnalyser | None = None,
    days: int = 14,
    limit: int = 60,
    refresh_after_days: int = 7,
) -> dict[str, Any]:
    """Appraise recent, interesting news for the analysed universe.

    One appraisal per *subject* per story: a story naming two instruments and a sector
    produces three rows, because whether the subject is held is what decides whether
    the model is asked to read the piece. The decision to appraise at all is the
    story's, so a piece interesting only because one of its companies is held is
    appraised for all of them.

    ``limit`` caps how many model calls one run can make. The callers are scheduled
    jobs with a spend ceiling above them, and an unbounded sweep after a quiet
    period would run into it and leave the rest unappraised with no explanation.
    """
    settings = settings or get_settings()
    report = AnalysisReport()

    statement = select(NewsItem).where(
        NewsItem.published_at >= utcnow() - dt.timedelta(days=days)
    )
    items = list(
        session.execute(statement.order_by(NewsItem.published_at.desc())).scalars().all()
    )
    if tickers:
        wanted = set(tickers)
        items = [item for item in items if wanted & set(item.tickers or [])]

    stale_before = utcnow() - dt.timedelta(days=refresh_after_days)
    existing = {
        (row.news_item_id, row.subject_type, row.subject_id): row
        for row in session.execute(select(NewsAnalysis)).scalars().all()
    }

    held, held_sectors = _held(session)
    run = _Run(
        settings=settings,
        analyser=analyser,
        held=held,
        held_sectors=held_sectors,
        stale_before=stale_before,
        existing=existing,
        limit=limit,
        report=report,
    )
    pool = _recent_coverage(session, days=days)
    index = _coverage_index(pool)

    total = len(items)
    for item in items:
        # Between stories, and on the committed side of the previous one: this loop
        # spends one model call per subject, so it is the longest run in the pipeline
        # (measured at 14-39 minutes for a bounded 40 calls) and the one an upgrade most
        # needs to be able to end.
        progress.barrier(f"{report.examined} of {total} examined")

        report.examined += 1
        # One model call per selected subject, so this run is measured in tens of
        # minutes. The counted line is what turns "running" into "at 24 of 40".
        progress.note(f"{report.examined} of {total} examined, {report.selected} selected")
        subjects = subjects_of(item)
        if not subjects:
            # Untagged news cannot be attributed to a name or an industry, so it
            # cannot inform either.
            report.skipped_not_interesting += 1
            continue

        publisher = lookup(item.url) if item.url else lookup(None)
        rhetoric = analyse_text(item.summary or item.title, headline=item.title)
        corroboration = assess(
            item.title,
            coverage_of(item, index),
            window_hours=settings.news.scepticism.corroboration_window_hours,
        )
        # Selection is about the *story*, so "held" here means "the reader holds
        # something this story is about". Whether each subject is itself held is
        # decided per appraisal, which is the one input that differs between two
        # appraisals of the same story.
        interesting, reason = is_interesting(
            item,
            rhetoric=rhetoric,
            publisher_kind=publisher.kind,
            held=any_is_held(subjects, held, held_sectors),
            carrier_count=corroboration.carrier_count,
            settings=settings,
        )
        if not interesting:
            report.skipped_not_interesting += 1
            continue

        report.selected += 1
        for subject in subjects:
            _appraise_subject(
                session,
                run,
                item,
                subject,
                rhetoric=rhetoric,
                corroboration=corroboration,
                reason=reason,
            )

    session.flush()
    logger.info("news scepticism: %s", report.as_dict())
    return report.as_dict()
