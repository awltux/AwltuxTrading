"""Running one deep-dive: the guard, the refresh, the model call, the stored report.

**It runs on a thread rather than in the request**, for the reason
:mod:`awltux.scheduler.scoped` records for a scoped refresh: this makes network calls and
one long model call -- minutes, not milliseconds -- and a request that blocks that long is
one the browser or a proxy will abandon, leaving a run the reader believes failed. It goes
through :func:`~awltux.scheduler.jobs.execute_job`, so it appears in the run history with a
progress log and a close-out line.

**Two guards, and they protect different things.**

* The **subject-level guard** is the report row itself: a ``running`` row for this
  ``(subject_type, subject_id)`` that is not stale means somebody already paid for this
  answer and the second press is refused. The row rather than a lock, because the row has to
  exist anyway -- it is what the list shows while the run is going -- and a second source of
  truth for "is this running" is how the two come to disagree.
* The **process-wide permit** is a single slot. A deep-dive is the most expensive call this
  application makes, and two at once would both be in the run history under one job id whose
  progress log is one file, truncated at the start of every run.

**The data is refreshed first, and the lease is given up before the model call.** A deep-dive
is a judgement about what this system holds, so it refreshes the instrument first -- and only
the instrument, because a sector has no refresh pipeline and the report says so rather than
implying a gap that is really an absence of machinery. The refresh runs under the
instrument's own lease (:mod:`awltux.ingest.lease`), which ``refresh.run_under_lease``
releases when the refresh finishes: the model call is minutes long, and holding a lease
across it would keep the instrument out of every sweep for its duration while the Refresh
panel printed "step 14 of 13" -- a refresh that looks stuck because a *different* run is
holding its lock.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import threading

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db.models import ResearchReport, utcnow
from awltux.llm.deepseek import DeepSeekClient, build_messages, model_for_purpose
from awltux.llm.prompts import RESEARCH_SYSTEM, prompt_fingerprint, research_instruction
from awltux.research import report as report_module
from awltux.research.evidence import Evidence, build_evidence
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobResult, JobSpec, execute_job

logger = logging.getLogger(__name__)

#: The run id a deep-dive appears under in the history and in `data/joblogs/`.
RESEARCH_JOB = "research_report"

#: What `llm_call.purpose` records, and what :func:`model_for_purpose` routes.
RESEARCH_PURPOSE = "research"

#: One deep-dive at a time. See the module docstring: the reason is the job log and the bill.
_permit = threading.Semaphore(1)

#: The subjects a deep-dive may be started about.
SUBJECT_TYPES = ("instrument", "sector")


class Started:
    """What happened when the Research button was pressed.

    ``report_id`` is set when a row was created, which is what the caller redirects to.
    The refusals are told apart because each is a different thing for the reader to do:
    already running, not a subject we know, the feature switched off, or another deep-dive
    holding the single slot.
    """

    __slots__ = ("ok", "message", "report_id")

    def __init__(self, ok: bool, message: str, report_id: int | None = None) -> None:
        self.ok = ok
        self.message = message
        self.report_id = report_id


def start(
    *,
    subject_type: str,
    subject_id: str,
    prompt: str,
    settings: Settings | None = None,
    client: DeepSeekClient | None = None,
) -> Started:
    """Record the report, take a slot, and run the deep-dive on a background thread.

    Returns immediately with whether it started and, when it did not, why. The prompt is
    stored exactly as submitted -- edited or not -- because the report has to be arguable
    and the wording that produced it is half of that argument.
    """
    settings = settings or get_settings()
    if not settings.research.enabled:
        return Started(False, "deep-dive research is switched off in the configuration")
    if subject_type not in SUBJECT_TYPES:
        return Started(False, f"{subject_type!r} is not something research runs about")
    if not prompt.strip():
        return Started(False, "the prompt is empty")

    # Everything knowable without spending anything is checked before the credential, so the
    # refusal names the thing the reader can act on: "no API key" is not the useful answer to
    # a link to a ticker this database has never heard of.
    with _session() as session:
        subject = _subject(session, subject_type, subject_id)
        if subject is None:
            return Started(False, f"{subject_id} is not in this database")
        if _running(session, subject_type, subject_id, settings):
            return Started(False, "a deep-dive of this subject is already running")

    if client is None and not DeepSeekClient(settings).configured:
        return Started(False, "no DeepSeek API key is configured, so a run could not read anything")

    with _session() as session:
        row = _open_report(
            session,
            subject_type=subject_type,
            subject_id=subject_id,
            subject=subject,
            prompt=prompt,
        )

    if not _permit.acquire(blocking=False):
        with _session() as session:
            _fail(session, row.id, "another deep-dive is already running")
        return Started(False, "another deep-dive is already running")

    thread = threading.Thread(
        target=_run,
        args=(row.id, subject_type, subject_id, prompt, client),
        name=f"research-{subject_id}",
        daemon=True,
    )
    try:
        thread.start()
    except Exception:  # noqa: BLE001 - the permit and the row must not be left behind
        logger.exception("could not start the deep-dive thread for %s", subject_id)
        _permit.release()
        with _session() as session:
            _fail(session, row.id, "the background thread could not be started")
        return Started(False, "the deep-dive could not be started")
    return Started(True, "research started", row.id)


def draft_prompt(
    subject_type: str,
    subject_id: str,
    *,
    settings: Settings | None = None,
    session: Session | None = None,
) -> str | None:
    """The prompt the dialog opens with, or ``None`` when the subject is unknown.

    Built here rather than in the route because the inventory in it comes from the same
    evidence builder the run uses -- so what the reader approves is what the run reads, and
    the two cannot drift into describing different scopes. Cheap: no model call, no refresh.
    """
    settings = settings or get_settings()
    if session is not None:
        return _draft(session, settings, subject_type, subject_id)
    with _session() as opened:
        return _draft(opened, settings, subject_type, subject_id)


def _draft(
    session: Session, settings: Settings, subject_type: str, subject_id: str
) -> str | None:
    subject = _subject(session, subject_type, subject_id)
    if subject is None:
        return None
    evidence = build_evidence(
        session, settings, subject_type=subject_type, subject_id=subject_id
    )
    return research_instruction(evidence.label, evidence.inventory())


def _session():
    """A session scope, imported here so this module stays importable without a database."""
    from awltux.db.session import session_scope

    return session_scope()


def _subject(session: Session, subject_type: str, subject_id: str) -> str | None:
    """The subject's display label, or ``None`` when this database does not hold it.

    A label rather than a boolean, because it is also what the report is titled with and
    what the prompt addresses. Refusing an unknown subject is the point: a stale link to a
    delisted ticker must not spend a model call on a company nothing is known about.

    A sector is validated against the same list the sector *page* uses, so a name that
    reaches here from a hand-typed URL cannot start a paid run about an industry this
    application has no page for.
    """
    if subject_type == "sector":
        from awltux.analysis.sectors import is_sector_page

        return subject_id if subject_id and is_sector_page(subject_id) else None
    from awltux.db.models import Instrument

    instrument = session.get(Instrument, subject_id)
    if instrument is None:
        return None
    return f"{instrument.name} ({instrument.t212_ticker})"


def _running(
    session: Session, subject_type: str, subject_id: str, settings: Settings
) -> bool:
    """Whether a live deep-dive already holds this subject.

    A row older than ``research.stale_minutes`` does not: a process killed mid-run leaves
    ``running`` behind, and refusing every later run until somebody edits the database would
    make one crash permanent. The stale row is left as it is -- the list shows it as stale,
    which is the truth -- and the new run takes the subject over.
    """
    cutoff = utcnow() - dt.timedelta(minutes=settings.research.stale_minutes)
    rows = session.execute(
        select(ResearchReport)
        .where(ResearchReport.subject_type == subject_type)
        .where(ResearchReport.subject_id == subject_id)
        .where(ResearchReport.status == "running")
    ).scalars().all()
    return any(_created_at(row) > cutoff for row in rows)


def _created_at(row: ResearchReport) -> dt.datetime:
    """``created_at`` as an aware datetime. SQLite hands it back naive, as everywhere here."""
    from awltux.timezones import as_utc

    return as_utc(row.created_at) or utcnow()


def _open_report(
    session: Session,
    *,
    subject_type: str,
    subject_id: str,
    subject: str,
    prompt: str,
) -> ResearchReport:
    """Insert the ``running`` row, and commit it.

    Committed rather than flushed: the run's progress is read by a request on its own
    session in another thread, so a row that has been flushed is invisible to the page that
    is about to show it.
    """
    row = ResearchReport(
        subject_type=subject_type,
        subject_id=subject_id,
        title=subject,
        status="running",
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        inventory=None,
        result=None,
        finished_at=None,
    )
    session.add(row)
    session.commit()
    return row


def _run(
    report_id: int,
    subject_type: str,
    subject_id: str,
    prompt: str,
    client: DeepSeekClient | None,
) -> None:
    """The thread body: execute the deep-dive as a job, then give the permit back."""
    spec = JobSpec(
        id=RESEARCH_JOB,
        func=lambda: _body(report_id, subject_type, subject_id, prompt, client),
        interval_seconds=3600,
        max_instances=1,
        description=f"Deep-dive research on {subject_id}",
        target=subject_id,
    )
    try:
        execute_job(spec)
    finally:
        _permit.release()


def _body(
    report_id: int,
    subject_type: str,
    subject_id: str,
    prompt: str,
    client: DeepSeekClient | None,
) -> JobResult:
    """Read the evidence, refresh first, call the model, store the report.

    Every ending writes the row: a run that failed leaves a row saying so rather than one
    frozen at ``running``, because the reader is looking at a list whose whole purpose is to
    say what happened.
    """
    settings = get_settings()
    log = progress.current()
    run_id = log.run_id if log is not None else None

    try:
        progress.checkpoint("research: gathering evidence")
        refresh_outcome = _refresh_first(subject_type, subject_id, settings)

        with _session() as session:
            evidence = build_evidence(
                session, settings, subject_type=subject_type, subject_id=subject_id
            )
            _record_refresh(session, report_id, refresh_outcome, evidence, run_id)

        progress.checkpoint("research: asking the model")
        completion, result = _ask(evidence, prompt, settings, client)

        document = report_module.render_xhtml(
            result,
            subject_label=evidence.label,
            prompt=prompt,
            model=completion.model,
            created=utcnow(),
            inventory=_inventory(evidence, completion),
            refresh=refresh_outcome,
            news=evidence.news.as_dict(),
            problems=evidence.problems,
        )

        with _session() as session:
            _finish(session, report_id, result, completion, document, evidence)
        return JobResult(
            items_seen=len(evidence.documents) + len(evidence.news.entries),
            items_written=1,
            note=f"{result.verdict} from {len(evidence.documents)} document(s)",
        )
    except progress.Stopped:
        with _session() as session:
            _fail(session, report_id, "stopped before the report was finished")
        raise
    except Exception as exc:  # noqa: BLE001 - the row must not stay at `running`
        logger.exception("deep-dive research failed for %s %s", subject_type, subject_id)
        with _session() as session:
            _fail(session, report_id, f"{type(exc).__name__}: {exc}")
        return JobResult(note=f"failed: {type(exc).__name__}: {exc}")


def _refresh_first(subject_type: str, subject_id: str, settings: Settings) -> dict:
    """Bring the subject's data up to date, and say what that did.

    Only instruments: a sector has no refresh pipeline, so a sector run reads the corpus as
    it stands and the report records that rather than pretending a refresh happened.

    A refresh that finished recently is **not repeated**. The button is pressed to get a
    judgement, not to re-fetch what was fetched ten minutes ago, and a deep-dive that always
    refreshed would spend a provider budget on every re-run of a report that differs only in
    its wording.
    """
    from awltux.ingest import refresh
    from awltux.ingest.lease import acquire, expire_stale

    if subject_type != "instrument":
        return {
            "state": "not_applicable",
            "note": "a sector has no refresh pipeline; the news corpus was read as it stood",
        }

    with _session() as session:
        expire_stale(session)
        state = _refresh_state(session, subject_id, settings)
        if state is not None:
            return state
        row = acquire(session, subject_id, note="deep-dive research")
        session.commit()
        token = row.token if row is not None else None

    if token is None:
        return {
            "state": "skipped",
            "note": "a refresh of this instrument is already running, so the data "
            "was read as it stood",
        }

    progress.note(f"refreshing {subject_id} before the deep-dive")
    outcome = refresh.run_under_lease(subject_id, token)
    note = refresh.summary(outcome) if "failed" not in outcome else str(outcome.get("failed"))
    return {"state": "failed" if "failed" in outcome else "refreshed", "note": note}


def _refresh_state(session: Session, ticker: str, settings: Settings) -> dict | None:
    """A reason not to refresh, or ``None`` to go ahead.

    The recent-success rule only. Everything else -- a lease somebody else holds, an
    instrument with no filings -- is discovered by trying, and reporting a refusal that did
    not happen would be worse than the attempt.
    """
    from awltux.db.models import InstrumentRefresh
    from awltux.timezones import as_utc

    row = session.get(InstrumentRefresh, ticker)
    if row is None or row.state != "done" or row.finished_at is None:
        return None
    finished = as_utc(row.finished_at)
    if finished is None:
        return None
    age = (utcnow() - finished).total_seconds() / 60.0
    if age > settings.research.refresh_within_minutes:
        return None
    return {
        "state": "recent",
        "note": f"refreshed {age:.0f} minutes ago, so it was not refreshed again",
        "finished_at": finished.isoformat(),
    }


def _ask(
    evidence: Evidence,
    prompt: str,
    settings: Settings,
    client: DeepSeekClient | None,
):
    """One model call, and the validated result set it produced.

    The documents and the digest go in the cacheable prefix (``build_messages``), so a
    re-run of the same subject with an edited prompt hits DeepSeek's prefix cache; the
    prompt itself goes last, where its variability costs nothing.
    """
    from awltux.analysis.metric_fields import load as load_fields

    with _session() as session:
        vocabulary = load_fields(session)

    client = client or DeepSeekClient(settings)
    completion = client.complete(
        purpose=RESEARCH_PURPOSE,
        messages=build_messages(
            system=RESEARCH_SYSTEM,
            document=evidence.text(),
            instruction=prompt,
        ),
        model=settings.research.model or model_for_purpose(settings, RESEARCH_PURPOSE),
        json_mode=True,
        max_tokens=settings.research.max_output_tokens,
        prompt_hash=prompt_fingerprint(RESEARCH_SYSTEM + prompt),
    )
    payload = completion.json_object()
    result = report_module.validate_result(
        payload,
        vocabulary=vocabulary,
        headlines=[entry.headline for entry in evidence.news.entries],
    )
    return completion, result


def _inventory(evidence: Evidence, completion=None) -> dict:
    """What the run read, as stored on the row and printed in the report's footer.

    **One shape, written twice.** The pre-model write records the scope so a run that dies in
    the model call still says what it had read; the post-model write adds the accounting. Two
    shapes for one column would mean two readers of it, and the page would show whichever
    the run happened to reach.
    """
    inventory = {
        "subject": evidence.label,
        "documents": [
            {
                "label": document.label,
                "source": document.source,
                "filed_at": document.filed_at,
                "chars": document.chars,
                "truncated": document.truncated,
            }
            for document in evidence.documents
        ],
        "document_chars": evidence.document_chars,
        "news": evidence.news.as_dict(),
        "problems": list(evidence.problems),
    }
    if completion is not None:
        inventory |= {
            "model": completion.model,
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "cost_usd": completion.cost_usd,
        }
    return inventory


def _record_refresh(
    session: Session,
    report_id: int,
    refresh_outcome: dict,
    evidence: Evidence,
    run_id: int | None,
) -> None:
    """Store the refresh outcome and the evidence scope, before the model call.

    Before, so a run that dies in the model call still records what it had read and whether
    its data was refreshed -- which is the first thing a reader wants to know about a
    report that never arrived.
    """
    row = session.get(ResearchReport, report_id)
    if row is None:
        return
    row.refresh = refresh_outcome
    row.inventory = _inventory(evidence)
    if run_id is not None:
        row.run_id = run_id
    session.commit()


def _finish(
    session: Session,
    report_id: int,
    result,
    completion,
    document: str,
    evidence: Evidence,
) -> None:
    """Write the document to disk and close the row out."""
    row = session.get(ResearchReport, report_id)
    if row is None:
        return
    path = report_module.report_path(
        get_settings(),
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        report_id=row.id,
    )
    size = report_module.write_report(path, document)

    row.status = "done"
    row.result = result.as_dict()
    row.exec_summary = result.executive_summary
    row.verdict = result.verdict
    row.confidence = result.confidence
    row.model = completion.model
    row.llm_call_id = completion.llm_call_id
    row.raw_path = str(path.name)
    row.bytes = size
    row.error = None
    row.finished_at = utcnow()
    row.inventory = _inventory(evidence, completion)
    session.commit()


def _fail(session: Session, report_id: int, message: str) -> None:
    row = session.get(ResearchReport, report_id)
    if row is None:
        return
    row.status = "failed"
    row.error = message
    row.finished_at = utcnow()
    session.commit()


def close_orphaned_research() -> int:
    """Fail every report left ``running`` by a dead process. Returns how many.

    Called at startup, exactly as the restart sweep closes interrupted ingest runs: a
    ``running`` row whose process is gone is not work in progress, it is a run that never
    finished, and leaving it would block the subject until ``research.stale_minutes``
    expired. The error says which of the two it was.
    """
    with _session() as session:
        rows = session.execute(
            select(ResearchReport).where(ResearchReport.status == "running")
        ).scalars().all()
        for row in rows:
            row.status = "failed"
            row.error = "interrupted by a restart"
            row.finished_at = utcnow()
        session.commit()
        if rows:
            logger.info("closed %d interrupted deep-dive(s)", len(rows))
        return len(rows)


__all__ = [
    "RESEARCH_JOB",
    "RESEARCH_PURPOSE",
    "SUBJECT_TYPES",
    "Started",
    "close_orphaned_research",
    "draft_prompt",
    "start",
]
