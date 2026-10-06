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
    appraised: int = 0
    deep_analysed: int = 0
    skipped_not_interesting: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "examined": self.examined,
            "selected": self.selected,
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


def _held_tickers(session: Session) -> set[str]:
    return {
        row.t212_ticker
        for row in session.execute(
            select(Instrument).where(Instrument.is_held.is_(True))
        ).scalars().all()
    }


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
    analyser: DeepAnalyser | None = None,
    rhetoric: RhetoricReport | None = None,
    corroboration: Corroboration | None = None,
    is_held: bool = False,
    known_context: str | None = None,
) -> NewsAnalysis:
    """Build the appraisal row for one item.

    Deterministic first: the publisher, the rhetoric and the corroboration count
    are all computed here, and the credibility arithmetic runs on them. The model
    call is additive -- it supplies the claims and the omissions, and can lower the
    grade by revealing that nothing checkable is being asserted, but it cannot
    raise a weight the rules have already capped.

    ``rhetoric`` and ``corroboration`` may be supplied by the caller when it has
    already computed them for selection; recomputing them here keeps the function
    usable on its own.
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
        row.news_item_id: row
        for row in session.execute(select(NewsAnalysis)).scalars().all()
    }

    held = _held_tickers(session)
    pool = _recent_coverage(session, days=days)

    total = len(items)
    for item in items:
        report.examined += 1
        # One model call per selected story, so this run is measured in tens of
        # minutes. The counted line is what turns "running" into "at 24 of 40".
        progress.note(f"{report.examined} of {total} examined, {report.selected} selected")
        if not item.tickers:
            # Untagged news cannot be attributed to a name, so it cannot inform one.
            report.skipped_not_interesting += 1
            continue

        publisher = lookup(item.url) if item.url else lookup(None)
        rhetoric = analyse_text(item.summary or item.title, headline=item.title)
        corroboration = assess(
            item.title, pool, window_hours=settings.news.scepticism.corroboration_window_hours
        )
        is_held = bool(set(item.tickers or []) & held)

        interesting, reason = is_interesting(
            item,
            rhetoric=rhetoric,
            publisher_kind=publisher.kind,
            held=is_held,
            carrier_count=corroboration.carrier_count,
            settings=settings,
        )
        if not interesting:
            report.skipped_not_interesting += 1
            continue

        report.selected += 1
        prior = existing.get(item.id)
        prior_analysed = _as_utc(prior.analysed_at) if prior is not None else None
        if prior_analysed is not None and prior_analysed > stale_before:
            # Already appraised recently. Re-appraising would spend a model call to
            # reproduce a conclusion nothing has changed.
            report.appraised += 1
            continue

        if report.deep_analysed >= limit and analyser is not None:
            # Deterministic appraisal still runs; the paid half is what is rationed.
            analyser_for_item: DeepAnalyser | None = None
        else:
            analyser_for_item = analyser

        # Release the write lock before appraising. The appraisal is where the
        # model call happens, and the release at the end of this loop body comes
        # too late: the transaction opened by the previous item's flush would
        # otherwise be held across this item's model call, locking out every
        # other writer for the duration.
        release_write_lock(session)
        try:
            row = appraise_item(
                item,
                settings=settings,
                analyser=analyser_for_item,
                rhetoric=rhetoric,
                corroboration=corroboration,
                is_held=is_held,
            )
        except Exception as exc:
            report.errors.append(f"{item.id}: {exc}")
            continue

        if analyser_for_item is not None:
            report.deep_analysed += 1

        if prior is not None:
            for column in (
                "source_domain", "source_name", "source_kind", "source_reliability",
                "source_independence", "source_biases", "source_basis", "source_assessed",
                "rhetoric_score", "rhetoric", "techniques", "carrier_count",
                "independent_sources", "corroboration", "claims", "omissions",
                "headline_matches_body", "headline_overstates", "who_benefits",
                "agenda_basis", "base_rate", "what_would_change_my_mind",
                "primary_source", "scepticism_summary", "injection_suspected",
                "credibility", "evidence_grade", "flags", "warnings", "caveats",
                "factors", "engine", "analysed_at",
            ):
                setattr(prior, column, getattr(row, column))
            session.add(prior)
        else:
            session.add(row)

        report.appraised += 1
        logger.info(
            "news appraisal: %s %s -> %s (%s)",
            item.source,
            item.title[:60],
            row.evidence_grade,
            reason,
        )

        # The write lock is released between items: each appraisal can involve a
        # model call taking seconds, and holding a transaction across dozens of
        # those would lock out every other writer for minutes.
        session.flush()
        release_write_lock(session)

    session.flush()
    logger.info("news scepticism: %s", report.as_dict())
    return report.as_dict()
