"""Running one deep-dive: the queue, the guard, the refresh, the model call, the report.

**It runs on a thread rather than in the request**, for the reason
:mod:`awltux.scheduler.scoped` records for a scoped refresh: this makes network calls and
one long model call -- minutes, not milliseconds -- and a request that blocks that long is
one the browser or a proxy will abandon, leaving a run the reader believes failed. It goes
through :func:`~awltux.scheduler.jobs.execute_job`, so it appears in the run history with a
progress log and a close-out line.

**The queue is the report rows themselves, and the claim is the single slot.** A press writes
a ``queued`` row and returns; a consumer takes the oldest queued row, runs it, and takes the
next. The claim is ``UPDATE ... WHERE status = 'queued'``, which either changes one row or
none -- and SQLite serialises writers across processes, so however many consumers exist (four
web workers, each with one) exactly one can win a given row. One deep-dive at a time, across
every process sharing the database, with the waiting request visible on the page meanwhile.

That replaces a process-wide semaphore, which was the wrong shape twice over. It **refused**
the second press instead of remembering it, which is what the reader reported: *"launching a
second Research job fails"*. And after the 2026-10-20 process split it was one permit **per
worker**, so it stopped nothing at all -- four presses on four workers could run four
deep-dives, sharing one job log file and one job id.

**Two guards, and they protect different things.**

* The **subject-level guard** is the row itself: a ``queued`` row, or a ``running`` one that is
  not stale, for this ``(subject_type, subject_id)`` means somebody already paid for this answer
  (or is about to) and the press is refused. The row rather than a lock, because the row has to
  exist anyway -- it is what the list shows while the request waits -- and a second source of
  truth for "is this running" is how the two come to disagree.
* The **queue claim** keeps the application to one deep-dive at a time, for the reason above:
  the run history has one id and one log file for this job, truncated at the start of every run.

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
from typing import Any

from sqlalchemy import select, update
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

#: The pipeline stages a finished instrument report invalidates, in the order they must run.
#:
#: Both read what `_finish` contributed rather than the document itself. ``valuation``
#: re-collates the accounts, where a report's cited figures sit as a ``deep_research`` period
#: ranked below the filer's own tagged data (`analysis/collate.py`); ``decision`` assembles the
#: state the report is one block of, and would otherwise argue with a judgement the reader paid
#: for. Nothing else in the pipeline reads a report -- the attention filter and the levers panel
#: read one at render time -- so this is the whole set, and it is written down rather than
#: derived because no `JobSpec.depends_on` declares it: research is not a pipeline input, it is
#: an amendment to one.
#:
#: It runs at the end of the research run because nothing else triggers it. `research` writes
#: the report and returns, and `decision` is on its own interval, so without this the report is
#: invisible to the decision until the next scheduled pass -- which for a name that is not held
#: is hours to days. `TODO.md` recorded that gap on 2026-10-09 and named this the first of three
#: ways to close it.
RESEARCH_FOLLOW_UP: tuple[str, ...] = ("valuation", "decision")

#: How often a sleeping consumer looks for work queued by another process.
#:
#: The press that fills the queue wakes the consumer in the same process, so this is only the
#: cross-process case: a deep-dive queued by one web worker while another worker's consumer is
#: asleep. Five seconds is the longest a queued run waits to be noticed, and the cost of
#: missing it is one `SELECT` of an empty set per sleeping process per interval.
QUEUE_POLL_SECONDS = 5.0

#: A client handed to :func:`start` for one run, keyed by report id.
#:
#: A client is a live object -- its injected double in a test, its rate limiter in production --
#: so it cannot be stored on the row, and yet the run a caller asked for must use the client the
#: caller passed. Popped when the run starts, so nothing accumulates. Production passes none:
#: the run builds its own from the configuration, exactly as a scheduled job would.
_queued_clients: dict[int, DeepSeekClient] = {}

#: Wakes the consumer of *this process* when a press queues something.
_wake = threading.Event()

#: Guards :data:`_consumer_started`, which is per process rather than per press.
_spawn_lock = threading.Lock()
_consumer_started = False

#: The subjects a deep-dive may be started about.
SUBJECT_TYPES = ("instrument", "sector")


class Started:
    """What happened when the Research button was pressed.

    ``report_id`` is set when a row was created, which is what the caller redirects to.
    ``queued`` distinguishes "there was a queue in front of it" from "nothing else was running";
    the run itself is on a thread either way, so this is what the page says rather than what the
    process did. The refusals are told apart because each is a different thing for the reader to
    do: this subject already holds a run, not a subject we know, or the feature switched off.
    """

    __slots__ = ("ok", "message", "report_id", "queued")

    def __init__(
        self, ok: bool, message: str, report_id: int | None = None, *, queued: bool = False
    ) -> None:
        self.ok = ok
        self.message = message
        self.report_id = report_id
        self.queued = queued


def start(
    *,
    subject_type: str,
    subject_id: str,
    prompt: str,
    settings: Settings | None = None,
    client: DeepSeekClient | None = None,
) -> Started:
    """Queue a deep-dive and return immediately.

    Returns whether the request was accepted and, when it was not, why. The prompt is stored
    exactly as submitted -- edited or not -- because the report has to be arguable and the
    wording that produced it is half of that argument.

    **Accepted is not started.** The row is written ``queued`` and the consumer picks it up,
    which is what makes a second press survive the first run instead of being refused. Callers
    that need the run to have finished -- tests, mostly -- drain the queue themselves; see
    :func:`drain_queue`.
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
        held = _pending(session, subject_type, subject_id, settings)
        if held is not None:
            return Started(False, _held_message(held))

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

    if client is not None:
        _queued_clients[row.id] = client
    ensure_consumer(settings)
    return Started(True, "queued", row.id, queued=True)


def ensure_consumer(settings: Settings | None = None) -> None:
    """Make sure this process is serving the queue, and nudge it. Idempotent.

    Called at startup and by every press. Idempotent because the consumer is one thread per
    *process*: what a press needs is the wake, not another consumer, and a second reader of the
    same rows would only contend for the same claim.
    """
    global _consumer_started

    settings = settings or get_settings()
    if not settings.research.enabled:
        return
    with _spawn_lock:
        if not _consumer_started:
            thread = threading.Thread(target=_queue_worker, name="research-queue", daemon=True)
            try:
                thread.start()
            except Exception:  # noqa: BLE001 - the row is queued either way, and the next press retries
                logger.exception("could not start the research queue consumer")
            else:
                _consumer_started = True
                # Logged because "is anything serving the queue?" is the first question when a
                # request sits at `queued` and nothing happens to it.
                logger.info("research queue consumer started")
    _wake.set()


def drain_queue(limit: int | None = None) -> int:
    """Run queued deep-dives on this thread until the queue empties. Returns how many ran.

    The consumer's body, and the seam a test uses: a press enqueues, and this serves the queue
    synchronously so the assertions can be about a finished run.

    Two reasons to stop with work still queued, both deliberate. **Research switched off** leaves
    the rows where they are -- they are requests somebody made, and throwing them away because
    the feature is off would lose them for a configuration change that may be temporary.
    **A stop request** (``awltux quiet``) is checked between runs: that command asks a *running*
    deep-dive to leave at its next checkpoint, and starting the next one while the container is
    being rebuilt is exactly the lost work it exists to prevent.
    """
    settings = get_settings()
    ran = 0
    while limit is None or ran < limit:
        if not settings.research.enabled or progress.stop_requested():
            break
        report_id = _claim_next()
        if report_id is None:
            break
        _run(report_id)
        ran += 1
    return ran


def _queue_worker() -> None:
    """Serve the queue for the life of this process.

    Woken by a press, and by nothing else in this process; the timeout covers a row queued by
    *another* process, which cannot set this one's event. A run that raises is caught here so a
    single failure cannot kill the consumer and leave every later request queued for ever.
    """
    while True:
        try:
            served = drain_queue()
        except Exception:  # noqa: BLE001 - the consumer must outlive any one run
            logger.exception("the research queue consumer failed; it will try again")
            served = 0
        if served:
            continue
        _wake.wait(QUEUE_POLL_SECONDS)
        _wake.clear()


def _claim_next() -> int | None:
    """Take the oldest queued deep-dive, or ``None`` when the queue is empty.

    **The claim is the single slot.** ``UPDATE ... WHERE status = 'queued'`` changes one row or
    none, and SQLite serialises writers across processes, so if two consumers read the same
    candidate only one of them can claim it -- the loser tries again and takes the next. Ordered
    by ``id``: it is monotonic, unambiguous, and it is the order the page prints the position in.

    ``started_at`` is written here rather than at the press, because this is when the run the
    reader is waiting for actually begins.
    """
    with _session() as session:
        while True:
            candidate = session.execute(
                select(ResearchReport.id)
                .where(ResearchReport.status == "queued")
                .order_by(ResearchReport.id)
                .limit(1)
            ).scalar_one_or_none()
            if candidate is None:
                return None
            claimed = session.execute(
                update(ResearchReport)
                .where(ResearchReport.id == candidate)
                .where(ResearchReport.status == "queued")
                .values(status="running", started_at=utcnow())
            ).rowcount
            session.commit()
            if claimed:
                return candidate
            # Another process claimed it between the read and the write: take the next one.


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


def _pending(
    session: Session, subject_type: str, subject_id: str, settings: Settings
) -> ResearchReport | None:
    """The row that already holds this subject: queued, or running and not stale.

    Both refuse a second press, and they are told apart because they are different things to
    say: a queued request has not begun and *will*, so pressing again would add a duplicate
    answer nobody asked for once the first arrives.

    A ``running`` row older than ``research.stale_minutes`` does not hold the subject: a process
    killed mid-run leaves ``running`` behind, and refusing every later run until somebody edits
    the database would make one crash permanent. The stale row is left as it is -- the list shows
    it as stale, which is the truth -- and the new run takes the subject over.
    """
    cutoff = utcnow() - dt.timedelta(minutes=settings.research.stale_minutes)
    rows = session.execute(
        select(ResearchReport)
        .where(ResearchReport.subject_type == subject_type)
        .where(ResearchReport.subject_id == subject_id)
        .where(ResearchReport.status.in_(("queued", "running")))
        .order_by(ResearchReport.id)
    ).scalars().all()
    for row in rows:
        if row.status == "queued":
            return row
        if _started_at(row) > cutoff:
            return row
    return None


def _held_message(row: ResearchReport) -> str:
    """Why a press was refused, in the words the page prints."""
    if row.status == "queued":
        return "a deep-dive of this subject is already queued"
    return "a deep-dive of this subject is already running"


def _started_at(row: ResearchReport) -> dt.datetime:
    """When this row's run began: the claim, or the request itself for a pre-queue row.

    A row written before the queue existed has no ``started_at``, and its run did begin when it
    was requested -- so the fallback is the same fact, not a guess. SQLite hands both columns
    back naive, as everywhere here.
    """
    from awltux.timezones import as_utc

    return as_utc(row.started_at) or as_utc(row.created_at) or utcnow()


def _open_report(
    session: Session,
    *,
    subject_type: str,
    subject_id: str,
    subject: str,
    prompt: str,
) -> ResearchReport:
    """Insert the ``queued`` row, and commit it.

    Committed rather than flushed: the request is read by a consumer in another thread (and, in
    the container, another process), so a row that has been flushed is invisible to the very
    thing it is waiting for.
    """
    row = ResearchReport(
        subject_type=subject_type,
        subject_id=subject_id,
        title=subject,
        status="queued",
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        inventory=None,
        result=None,
        finished_at=None,
    )
    session.add(row)
    session.commit()
    return row


def _run(report_id: int) -> None:
    """Execute one claimed deep-dive as a job.

    The row is re-read rather than passed in: it was claimed by id from another session, and
    the three things this needs -- subject, prompt, and the client its caller supplied -- are
    read at the moment they are used, so a consumer serving a row another process queued works
    the same way as one serving its own.
    """
    with _session() as session:
        row = session.get(ResearchReport, report_id)
        if row is None:
            return
        subject_type, subject_id, prompt = row.subject_type, row.subject_id, row.prompt

    client = _queued_clients.pop(report_id, None)
    spec = JobSpec(
        id=RESEARCH_JOB,
        func=lambda: _body(report_id, subject_type, subject_id, prompt, client),
        interval_seconds=3600,
        max_instances=1,
        description=f"Deep-dive research on {subject_id}",
        target=subject_id,
    )
    # `execute_job` records how the run ended -- including a `progress.Stopped`, which it
    # reports as "stopped" rather than letting it escape -- so the queue loop can carry on to
    # the next row without a `try` of its own.
    execute_job(spec)


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

        # After the row is closed, so the steps read a finished report rather than one still
        # marked `running`. Wrapped because the report is stored by now: a follow-up that
        # cannot run is a delay, not a lost result, and failing the run here would report a
        # finished deep-dive as a failed one.
        try:
            follow_up = _follow_up(subject_type, subject_id)
        except Exception as exc:  # noqa: BLE001 - the report is already stored
            logger.exception("deep-dive follow-up failed for %s %s", subject_type, subject_id)
            follow_up = {"state": "failed", "note": f"{type(exc).__name__}: {exc}"}
        progress.note(f"follow-up {follow_up['state']}: {follow_up['note']}")

        note = f"{result.verdict} from {len(evidence.documents)} document(s)"
        # A sector has nothing to re-run, and saying so in the run's own result would be noise
        # on every sector report; every other outcome is worth the reader's eye.
        if follow_up["state"] != "not_applicable":
            note = f"{note}; follow-up {follow_up['note']}"
        return JobResult(
            items_seen=len(evidence.documents) + len(evidence.news.entries),
            items_written=1,
            note=note,
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


def _follow_up(subject_type: str, subject_id: str) -> dict:
    """Re-run the stages a finished report changes, so it counts before the next sweep.

    See :data:`RESEARCH_FOLLOW_UP` for which stages and why. Two refusals, both recorded
    rather than silent: a sector has no pipeline to re-run, and an instrument whose refresh is
    already running is left alone -- the lease is the same one every other path takes, and
    fighting over it would be worse than waiting for the next scheduled pass.

    Never raises: the report is already written and stored by the time this is called, and a
    follow-up that cannot run is a delay, not a lost result.
    """
    from awltux.ingest import refresh
    from awltux.ingest.lease import acquire, expire_stale

    if subject_type != "instrument":
        return {"state": "not_applicable", "note": "a sector has no pipeline to re-run"}

    with _session() as session:
        expire_stale(session)
        row = acquire(session, subject_id, note="deep-dive follow-up")
        session.commit()
        token = row.token if row is not None else None

    if token is None:
        return {
            "state": "skipped",
            "note": "a refresh of this instrument is already running, so the decision "
            "waits for its next scheduled pass",
        }

    steps = [step for step in refresh.steps() if step.job in RESEARCH_FOLLOW_UP]
    names = ", ".join(step.job for step in steps)
    progress.note(f"the report is in: re-running {names}")
    outcome = refresh.run_under_lease(subject_id, token, steps_to_run=steps)
    if "failed" in outcome:
        return {"state": "failed", "note": str(outcome.get("failed"))}
    return {"state": "re-ran", "note": f"{names}: {refresh.summary(outcome)}"}


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
    """Write the document to disk, contribute the figures, and close the row out."""
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

    # The result set's other half: the cited figures become a stored period, so a deep-dive
    # *contributes* to the analysis rather than sitting beside it. Same writer, same scaling
    # and same unit refusal as a filing extraction -- see `ingest.parsing.store_cited_period`
    # -- and ranked below it in `SOURCE_PREFERENCE`, because the filing extractor's whole job
    # is one document while this is a synthesis across several.
    #
    # The levers it named are written here too. Both are the same idea: the run was paid for
    # once and what it found is filed where the rest of the analysis can read it, rather than
    # left inside a document. Both keys are always present, because the report's own footer
    # says what the run did and "recorded none" is a different answer from a missing field.
    contributed: dict[str, Any] = {
        "periods": {},
        # A sector is not an instrument, so it has no row to attach an exposure to: the block
        # is read out of a sector report's answer and goes nowhere. Recorded as none rather
        # than omitted, so the footer of a sector report does not look like an older report.
        "levers": {"recorded": [], "kept_by_hand": []},
    }
    if row.subject_type == "instrument":
        from awltux.ingest.parsing import store_cited_period

        # `store_cited_period` counts its outcomes into the dict it is handed -- the same
        # counters a filing run reports -- so it is the inventory's own ``periods`` object
        # rather than a copy of it.
        periods: dict[str, Any] = contributed["periods"]
        outcome = store_cited_period(
            session, row.subject_id, result.extraction, periods, source="deep_research"
        )
        periods["outcome"] = outcome
        contributed["levers"] = _record_levers(session, row.subject_id, result.levers)

    row.status = "done"
    row.result = result.as_dict()
    row.exec_summary = result.executive_summary
    row.verdict = result.verdict
    row.confidence = result.confidence
    row.model = completion.model
    row.llm_call_id = completion.llm_call_id
    # Relative to the data directory, the same shape `ingest/documents.py` stores for a filing
    # -- it was `path.name` until 2026-10-10, a bare `1.xhtml`, which is a file name rather
    # than a location and made the serving route's join resolve to nothing.
    row.raw_path = str(path.relative_to(get_settings().data_dir))
    row.bytes = size
    row.error = None
    row.finished_at = utcnow()
    row.inventory = _inventory(evidence, completion) | contributed
    session.commit()


def _record_levers(session: Session, ticker: str, exposures: list[Any]) -> dict[str, Any]:
    """Write the exposures the deep-dive named, leaving every lever a person recorded alone.

    `analysis.levers.record` upserts on ``(ticker, lever)``, so writing the model's list
    wholesale would let a deep-dive replace a judgement somebody made deliberately -- and
    because a lever row shows its provenance rather than ranking it, nothing downstream would
    show that it had happened. The model's answer is one reading of the documents; a person's
    is a decision, and the decision is the one that stays. Everything else is the model's,
    including a lever an earlier deep-dive recorded and this one did not repeat: a run that
    leaves a lever out has not said the lever is gone.

    The return value is what the report's inventory records, because "recorded four" and
    "recorded none, the reader holds these" are different runs and the footer should say which.
    """
    from awltux.analysis import levers as lever_module

    held = {
        exposure.lever
        for exposure in lever_module.stored(session, ticker)
        if exposure.source == lever_module.MANUAL
    }
    named = {exposure.lever for exposure in exposures}
    written = lever_module.record(
        session,
        ticker,
        [exposure for exposure in exposures if exposure.lever not in held],
        source=lever_module.DEEP_RESEARCH,
    )
    return {
        "recorded": sorted(row.lever for row in written),
        "kept_by_hand": sorted(held & named),
    }


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

    **A ``queued`` row is left alone, and that is the point of the queue.** It is not interrupted
    work, it is a request nobody has picked up yet -- failing it at a restart would lose exactly
    the presses this exists to remember. It is drained by the next consumer to start.
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
    "QUEUE_POLL_SECONDS",
    "RESEARCH_JOB",
    "RESEARCH_PURPOSE",
    "SUBJECT_TYPES",
    "Started",
    "close_orphaned_research",
    "drain_queue",
    "draft_prompt",
    "ensure_consumer",
    "start",
]
