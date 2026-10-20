"""Command-line interface.

The same code paths the scheduler uses are exposed here, which makes every
scheduled action reproducible by hand -- useful when a provider is misbehaving
and you want to see the error rather than read it in the run history.

    awltux serve                 # run the web app and scheduler
    awltux init-db               # create the schema
    awltux settings              # show effective configuration (secrets redacted)
    awltux job <job-id>          # run one scheduled job now
    awltux jobs                  # list the registered jobs
    awltux quiet                 # pause scheduling and wait, before a rebuild
    awltux unquiet               # undo it, if the rebuild was called off
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time

from awltux import __version__

logger = logging.getLogger(__name__)


def _configure(level: str) -> None:
    from awltux.logging_setup import configure_logging

    configure_logging(level)


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from awltux.config import get_settings
    from awltux.db.migrate import run_migrations

    settings = get_settings()

    # Migrate before serving, exactly as the container does. `serve` used to call
    # only ``init_db`` (via the app's lifespan), which creates *missing tables* and
    # never alters existing ones -- so running it against a database from a
    # previous version failed at the first query with a raw "no such column",
    # naming the symptom and not the cause. The deployment path never saw this
    # because the image chains `migrate && serve`; a local run did.
    #
    # A migration failure is logged and stepped over rather than fatal: on a fresh
    # database ``init_db`` will still build the schema, and refusing to start would
    # turn a recoverable state into a dead one.
    try:
        revision = run_migrations(settings)
        print(f"schema at revision {revision}")
    except Exception as exc:
        print(f"warning: could not migrate ({exc}); continuing with create_all")

    workers = args.workers if args.workers is not None else settings.env.web_workers
    if workers > 1 and settings.env.scheduler_enabled and not settings.env.scheduler_control_url:
        print(
            f"refusing to serve with {workers} workers: each worker's lifespan would start its "
            "own scheduler and every job would run once per worker. Run `awltux schedule` "
            "beside it and set AWLTUX_SCHEDULER_ENABLED=false with "
            "AWLTUX_SCHEDULER_CONTROL_URL pointing at it -- which is what the container's "
            "entrypoint does.",
            file=sys.stderr,
        )
        return 2

    uvicorn.run(
        "awltux.main:app",
        host=args.host or settings.env.host,
        port=args.port or settings.env.port,
        workers=workers,
        log_config=None,  # our own redacting logging is already configured
        access_log=False,
    )
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Run the background scheduler on its own, with a loopback control API.

    The other half of `serve --workers N`: one process owns the jobs, and the web tier asks it
    what is happening. It is the same ``SchedulerService`` the web app used to own, so the
    registry, the catch-up sweep, the quiet protocol and the progress logs are unchanged.

    The control port is **loopback only** by default and unauthenticated: it can start jobs that
    spend provider and model budget, so it must not be published. ``--host`` exists for a
    two-container deployment on a private network and for the test suite.
    """
    import signal

    import uvicorn

    from awltux.config import get_settings
    from awltux.scheduler.control import create_control_app
    from awltux.scheduler.registry import build_job_specs
    from awltux.scheduler.service import SchedulerService

    settings = get_settings()
    _configure(settings.env.log_level)

    from awltux.main import _close_interrupted_work

    # The scheduler owns the run rows, so it owns the sweep that fails what a previous process
    # left open -- and it must happen before `start()`, or a fresh run could be closed by it. In
    # the web processes this deliberately does not happen: with several workers, each one would
    # mark a job this process is still running as interrupted.
    _close_interrupted_work()

    service = SchedulerService(build_job_specs(settings))
    service.start()
    control = create_control_app(service)

    def stop(_signum, _frame):
        """Drain, then exit. The container's grace period is the real deadline."""
        budget = settings.env.shutdown_drain_seconds
        logger.info("scheduler stopping; draining up to %.0fs", budget)
        try:
            if budget > 0:
                service.drain(timeout=budget)
        finally:
            service.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    uvicorn.run(
        control,
        host=args.host,
        port=args.port or settings.env.control_port,
        log_config=None,
        access_log=False,
    )
    service.shutdown(wait=False)
    return 0


def cmd_init_db(_args: argparse.Namespace) -> int:
    """Create missing tables only. Use ``migrate`` to upgrade an existing database."""
    from awltux.config import get_settings
    from awltux.db import init_db

    settings = get_settings()
    init_db(settings)
    print(f"schema ready at {settings.db_path}")
    return 0


def cmd_migrate(_args: argparse.Namespace) -> int:
    """Bring an existing database up to the current schema.

    The deployment path. ``init-db`` creates a schema for a fresh install, but only
    ``migrate`` will *alter* an existing one -- and a container restarting against
    an older volume needs exactly that. The image runs this before serving.
    """
    from awltux.config import get_settings
    from awltux.db.migrate import run_migrations

    settings = get_settings()
    try:
        revision = run_migrations(settings)
    except FileNotFoundError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 2
    print(f"database at {settings.db_path} is at revision {revision}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Diagnose configuration and provider connectivity.

    Exits non-zero if any check failed, so it is usable as a preflight step.
    """
    from awltux.config import get_settings
    from awltux.doctor import run_diagnosis

    settings = get_settings()
    # The rate-limit budget lives in the database and the HTTP client needs it, so
    # the schema must exist before any connectivity check can run.
    #
    # Migrations rather than ``init_db``: create_all leaves the database unstamped,
    # so the revision would read as "none" and the diagnostic would warn about a
    # problem it had just caused itself.
    try:
        from awltux.db.migrate import run_migrations

        run_migrations(settings)
    except Exception as exc:
        from awltux.db import init_db

        init_db(settings)
        print(f"warning: could not migrate ({exc}); using create_all instead")
        print()

    diagnosis = run_diagnosis(settings, live=not args.offline)

    symbols = {"ok": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}
    for check in diagnosis.checks:
        print(f"[{symbols[check.status]}] {check.name}: {check.detail}")
        if check.hint and (args.verbose or check.status in ("fail", "warn")):
            for line in _wrap(check.hint, 96):
                print(f"         {line}")

    print()
    print(f"overall: {symbols[diagnosis.worst]}")
    return 1 if diagnosis.worst == "fail" else 0


def _wrap(text: str, width: int) -> list[str]:
    import textwrap

    return textwrap.wrap(text, width=width) or [""]


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """Create a synthetic universe so the whole app can be exercised offline.

    Deliberately writes into ``universe`` and then runs the real valuation and
    decision pipelines, so what you see is the actual dashboard behaviour rather
    than a mocked-up set of rows.
    """
    from awltux.config import get_settings
    from awltux.db import session_scope
    from awltux.db.migrate import run_migrations
    from awltux.demo import seed_demo_data

    settings = get_settings()
    try:
        run_migrations(settings)
    except Exception as exc:
        print(f"warning: could not migrate ({exc}); continuing")

    with session_scope() as session:
        report = seed_demo_data(session, history_days=args.days, reset=args.reset)
        print(f"seeded {report.instruments} instruments, {report.bars} bars, "
              f"{report.periods} account periods, {report.news} news items")
        for error in report.errors:
            print(f"  warning: {error}")

        if not args.no_analysis:
            # Run the real pipelines so the dashboard has verdicts to show.
            from awltux.analysis.sentiment import aggregate_all
            from awltux.analysis.valuation import run_valuations
            from awltux.decision.service import decide_universe

            valuations = run_valuations(session)
            print(f"valued {valuations.get('valued', 0)} of "
                  f"{valuations.get('attempted', 0)} "
                  f"({valuations.get('insufficient_data', 0)} lacked enough data)")
            sentiment = aggregate_all(session)
            print(f"sentiment rows: {sentiment.get('rows_written', 0)}")
            decisions = decide_universe(session)
            print(f"decided {decisions.get('decided', 0)}: "
                  f"{decisions.get('long_term_suggestions', 0)} long-term and "
                  f"{decisions.get('short_term_suggestions', 0)} short-term suggestions")

    print()
    print("Open the dashboard and look for the DEMO tickers. Remove them with")
    print("`awltux seed-demo --reset --no-analysis` and a fresh database, or by")
    print(f"editing out rows whose industry is '{'__demo__'}'.")
    return 0


def cmd_settings(_args: argparse.Namespace) -> int:
    from awltux.config import get_settings, redacted_dump

    settings = get_settings()
    print(json.dumps(redacted_dump(settings), indent=2))
    return 0


def cmd_repair_scaled(args: argparse.Namespace) -> int:
    """Correct extraction figures a document's unit scale should never have multiplied.

    A price per share and a share count are not magnitudes of the statement's currency: a
    10-K presented in millions still states ``Diluted $ 17.95``, and multiplying it stored
    MSFT's EPS as 17,950,000. The write-time rule is fixed; this repairs the rows already
    written, from the span each figure was quoted from rather than by re-extraction, which
    would cost a model call per filing and change figures for unrelated reasons.

    ``--dry-run`` prints what it would change and writes nothing.
    """
    from awltux.db.session import session_scope
    from awltux.ingest import parsing

    with session_scope() as session:
        report = parsing.repair_scaled_figures(session, dry_run=args.dry_run)

    for entry in report["changed"]:
        arrow = "would be" if args.dry_run else "now"
        print(
            f"{entry['ticker']} {entry['period_end']} {entry['metric']}: "
            f"{entry['was']:,.4g} {arrow} {entry['now']:,.4g}"
        )
    note = "would change" if args.dry_run else "changed"
    print(
        f"{len(report['changed'])} figure(s) {note} across {report['checked']} period(s); "
        f"{report['unreadable']} had no readable span and were left alone"
    )
    return 0


def cmd_repair_filing_summaries(args: argparse.Namespace) -> int:
    """Read the filings that were parsed before anything wrote a summary.

    Its two siblings re-derive what is already recorded and spend nothing. **This one
    spends**: it is a model call per filing, on the cheap model, over a whole document. So
    ``--dry-run`` lists the candidates and opens nothing at all, and ``--limit`` is there for
    a first run that wants to see the cost before paying the rest of it.
    """
    from awltux.db.session import session_scope
    from awltux.ingest import parsing

    with session_scope() as session:
        report = parsing.repair_filing_summaries(
            session, dry_run=args.dry_run, limit=args.limit
        )

    for entry in report["changed"]:
        print(f"{entry['ticker']} {entry['filing_type']} {entry['filed_at'] or 'undated'}")
    note = "would be summarised" if args.dry_run else "summarised"
    line = (
        f"{report['changed_count']} filing(s) {note}, of {report['checked']} already read"
        f" ({report['already']} had a summary)"
    )
    if report["no_text"]:
        line += f"; {report['no_text']} could not be read"
    if report["failed"]:
        line += f"; {report['failed']} produced nothing and will be retried"
    print(line)
    return 0


def cmd_repair_price_units(args: argparse.Namespace) -> int:
    """Rewrite stored price bars whose unit contradicts the instrument's own currency.

    The companion to the write-time refusal in ``ingest/prices.py``: the guard stops a wrong
    unit being stored again, and this corrects the rows a previous version already wrote. It
    fetches nothing -- ``raw_close`` is the provider's own number and the multiplier is the one
    the instrument's currency code implies -- which is why it is safe to run against the live
    database.

    ``--dry-run`` prints what it would change and writes nothing.
    """
    from awltux.db.session import session_scope
    from awltux.ingest.prices import repair_price_units

    with session_scope() as session:
        report = repair_price_units(session, dry_run=args.dry_run)

    for entry in report["changed"]:
        arrow = "would be" if args.dry_run else "now"
        print(
            f"{entry['ticker']} {entry['date']} ({entry['currency']}): "
            f"{entry['was']:,.6g} {arrow} {entry['now']:,.6g} "
            f"[multiplier {entry['was_multiplier']:g} -> {entry['now_multiplier']:g}]"
        )
    note = "would change" if args.dry_run else "changed"
    tickers = len(report["tickers"])
    print(
        f"{report['changed_count']} bar(s) {note}, across {tickers} instrument(s)"
        + (f": {', '.join(report['tickers'][:10])}" if tickers else "")
    )
    return 0


def cmd_jobs(_args: argparse.Namespace) -> int:
    from awltux.config import get_settings
    from awltux.scheduler.registry import build_job_specs

    for spec in build_job_specs(get_settings()):
        state = "enabled" if spec.enabled else f"disabled (needs {', '.join(spec.requires)})"
        cadence = (
            f"every {spec.interval_seconds:>7}s"
            if spec.interval_seconds is not None
            else "on demand"
        )
        print(f"{spec.id:24} {cadence:<14}  {state}")
        if spec.description:
            print(f"{'':24} {spec.description}")
    return 0


def cmd_news_publishers(args: argparse.Namespace) -> int:
    """Name the writer on every stored story, and re-rate what was rated against the feed.

    Two passes and both are idempotent. The first fills `news_item.publisher` for the rows
    that predate the column; the second rebuilds every stored appraisal whose source came
    from a feed URL -- which is 96% of them, because a Google News URL is a redirect.

    **No model calls.** The rebuild is the deterministic half of `appraise_item`; the
    claims and the omissions the model produced are copied across untouched. The numbers
    that move are the credibility, the grade and the flags, so the command prints what
    moved rather than reporting a row count.
    """
    from awltux.analysis.news_analysis import backfill_publishers, rerate_publishers
    from awltux.db import session_scope

    with session_scope() as session:
        named = backfill_publishers(session)
        print(
            f"stories {named['stories']}: {named['named']} named, "
            f"{named['already_named']} already correct"
        )
        if args.names_only:
            return 0
        report = rerate_publishers(session)

    print(
        f"appraisals {report['appraisals']} across {report['stories']} stories: "
        f"{report['renamed']} re-attributed, {report['rewritten']} re-rated"
    )
    for sample in report["samples"]:
        print(
            f"  {sample['credibility_was']} -> {sample['credibility_now']}  "
            f"{sample['was']} -> {sample['now']}  {sample['title']}"
        )
    return 0


def _local_base_url(settings) -> str:
    """Where a server started by `serve` would be listening.

    ``0.0.0.0`` is a bind address, not a destination, so it is mapped to loopback —
    the CLI and the server are on the same machine by construction.
    """
    host = settings.env.host or "127.0.0.1"
    if host in ("0.0.0.0", "::", ""):
        host = "127.0.0.1"
    return f"http://{host}:{settings.env.port}"


def _run_via_server(settings, job_id: str) -> dict | None:
    """Ask a running server to run the job. ``None`` when nothing is listening.

    Running the job here instead would open a second connection to the same SQLite
    file while the server's scheduler is writing, and the loser gets "database is
    locked". `busy_timeout` handles a brief wait; a job that sleeps inside a
    rate-limit guard is longer than any sane timeout. The server is already
    running the same code path and already holds the write lock correctly.
    """
    import httpx

    url = f"{_local_base_url(settings)}/api/jobs/{job_id}/run"
    try:
        response = httpx.post(url, timeout=httpx.Timeout(600.0, connect=2.0))
    except httpx.HTTPError:
        # Nothing listening, or not answering. Fall through to a direct run: the
        # CLI has to work when the server is down, which is half its purpose.
        return None
    if response.status_code == 404:
        return None
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        print(f"server refused the job: {exc}", file=sys.stderr)
        return {"error": str(exc)}
    return response.json()


def cmd_job(args: argparse.Namespace) -> int:
    from awltux.config import get_settings
    from awltux.scheduler.jobs import execute_job
    from awltux.scheduler.registry import build_job_specs

    settings = get_settings()
    specs = {spec.id: spec for spec in build_job_specs(settings)}
    spec = specs.get(args.job_id)
    if spec is None:
        print(f"unknown job {args.job_id!r}. Available: {', '.join(sorted(specs))}", file=sys.stderr)
        return 2

    if not args.direct:
        delegated = _run_via_server(settings, args.job_id)
        if delegated is not None:
            print(f"ran {args.job_id} on the running server at {_local_base_url(settings)}")
            print(json.dumps(delegated.get("detail") or delegated, indent=2, default=str))
            return 0

    result = execute_job(spec)
    if result is not None:
        print(json.dumps(result.detail, indent=2, default=str))
    return 0


#: How many consecutive unanswered polls before `quiet` gives up waiting.
#:
#: `quiet` waits without a deadline, and the one way an unbounded wait hangs for
#: ever is a server that has gone away -- the last answer it gave would be waited
#: on indefinitely. Three consecutive misses is about ten seconds at the default
#: poll interval, which is long enough to ride out a single dropped request and
#: short enough not to look like the tool has hung.
MISSES_BEFORE_GIVING_UP = 3


def _elapsed(seconds: float) -> str:
    """A duration a person reads at a glance: ``8s``, ``2m10s``, ``1h04m``."""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    if total < 3600:
        return f"{total // 60}m{total % 60:02d}s"
    return f"{total // 3600}h{(total % 3600) // 60:02d}m"


def cmd_quiet(args: argparse.Namespace) -> int:
    """Ask the running server to stop starting work, and wait for what is running.

    Deliberately the first half of an upgrade rather than a nicer shutdown. By the
    time SIGTERM arrives the drain has a deadline and a job that overruns it is
    killed mid-write; the run row is closed as interrupted on the next boot, which
    is honest but is still work lost. Asking before the rebuild costs nothing and
    leaves nothing to interrupt.

    **There is no timeout by default, and that is the point.** The jobs this exists
    to wait for are longer than any deadline an operator would guess: `news_analysis`
    is bounded at forty model calls and still runs 14 to 39 minutes, and `decision`
    runs about two hours. A default of fifteen minutes failed on the first real job
    it met, twice, and both times the rebuild went ahead and the run was killed --
    which is the outcome the command exists to prevent.

    Bounding the *shutdown* drain is a different question with a different answer:
    that one runs inside the SIGTERM handler, and the container is stopped at
    `stop_grace_period` whether the wait has finished or not, so an unbounded wait
    there buys a SIGKILL mid-write instead of a clean stop. Quiet runs before the
    rebuild, while the container is healthy and nothing is forcing it to end.
    """
    from awltux.config import get_settings

    settings = get_settings()
    status = _ask_server(settings, "POST", "/api/quiet")
    if status is None:
        print(
            f"nothing is listening at {_local_base_url(settings)}, so no scheduler is "
            "running and there is nothing to quiet.",
            file=sys.stderr,
        )
        return _report_open_runs_without_a_server()

    print(f"quieted at {status.get('quiet_since') or 'now'}")

    started = time.monotonic()
    deadline = started + float(args.timeout) if args.timeout > 0 else None
    missed = 0

    while not status.get("idle"):
        if deadline is not None and time.monotonic() >= deadline:
            break
        running = ", ".join(status.get("running") or []) or "?"
        print(
            f"  waiting for {running} ({_elapsed(time.monotonic() - started)})",
            file=sys.stderr,
        )
        time.sleep(args.poll)
        fresh = _ask_server(settings, "GET", "/api/quiet")
        if fresh is None:
            # The one way an unbounded wait can hang for ever. A server that has
            # gone is not a job that is still running, and waiting on the last
            # answer it gave would never end.
            missed += 1
            if missed >= MISSES_BEFORE_GIVING_UP:
                print(
                    f"the server stopped answering after {_elapsed(time.monotonic() - started)}. "
                    "It has probably been stopped or restarted, in which case any job "
                    "it was running has already been interrupted.",
                    file=sys.stderr,
                )
                return 2
            continue
        missed = 0
        status = fresh

    if not status.get("idle"):
        running = ", ".join(status.get("running") or [])
        print(
            f"still running after {args.timeout:.0f}s: {running}\n"
            "Not safe to rebuild yet. Re-run without --timeout to wait for it, or "
            "accept that the job will be interrupted and closed as such on the "
            "next start.",
            file=sys.stderr,
        )
        return 3

    print(
        f"idle after {_elapsed(time.monotonic() - started)}: no jobs running. "
        "Safe to rebuild and redeploy."
    )
    return 0


def cmd_unquiet(args: argparse.Namespace) -> int:
    """Undo `awltux quiet`, for an upgrade that was called off."""
    from awltux.config import get_settings

    settings = get_settings()
    status = _ask_server(settings, "DELETE", "/api/quiet")
    if status is None:
        print(f"nothing is listening at {_local_base_url(settings)}", file=sys.stderr)
        return 1
    print("resumed: the scheduler is taking work again.")
    return 0


def _report_open_runs_without_a_server() -> int:
    """Distinguish "no server, so nothing is scheduled" from "no server, but a run
    row is open" -- the second means something died mid-job and the last word on the
    deployment is wrong."""
    from awltux.db import session_scope
    from awltux.scheduler.jobs import running_jobs

    try:
        with session_scope() as session:
            open_runs = sorted(running_jobs(session))
    except Exception as exc:  # pragma: no cover - diagnostics only
        print(f"could not read the run table: {exc}", file=sys.stderr)
        return 2

    if open_runs:
        print(
            "but the run table has open rows for: "
            + ", ".join(open_runs)
            + "\nA previous process died mid-job; the next start closes these as "
            "interrupted.",
            file=sys.stderr,
        )
        return 3

    print("The run table has no open rows either: nothing is mid-write.")
    return 0


def _ask_server(settings, method: str, path: str) -> dict | None:
    """One request to the local server. ``None`` when nothing is listening.

    ``DELETE`` is included because `unquiet` is an undo rather than a resource of
    its own; the pair reads as create/destroy on the quiet state.
    """
    import httpx

    url = f"{_local_base_url(settings)}{path}"
    try:
        response = httpx.request(
            method,
            url,
            # Short: a quiet call is a question about state, not work. Hanging here
            # would block the upgrade on the very thing quiet exists to unblock.
            timeout=httpx.Timeout(30.0, connect=2.0),
        )
    except httpx.HTTPError:
        return None
    if response.status_code >= 400:
        print(f"server refused: HTTP {response.status_code} {response.text}", file=sys.stderr)
        return None
    try:
        return response.json()
    except ValueError:  # pragma: no cover - the endpoint returns JSON
        return None


def _lever_instrument(session, ticker: str):
    """The instrument row for a ticker, or ``None`` -- with why it was refused left to the
    caller.

    The levers are stored against ``instrument.t212_ticker``, a real foreign key, so a typo
    would otherwise surface as an integrity error or, worse on a database with the pragma off,
    as a row attached to nothing. Resolving it here turns that into one sentence.
    """
    from awltux.db import Instrument

    return session.get(Instrument, ticker)


def cmd_levers_list(args: argparse.Namespace) -> int:
    """The vocabulary, in the order the pages show it, so a recording can be checked by eye."""
    from awltux.analysis.levers import (
        DIRECTIONS,
        GROUP_LABELS,
        GROUP_ORDER,
        LEVERS,
        STRENGTHS,
    )

    for group in GROUP_ORDER:
        print(f"\n{GROUP_LABELS[group]}")
        for lever in LEVERS:
            if lever.group != group:
                continue
            print(f"  {lever.key:<20} {lever.label}")
            print(f"  {'':<20} {lever.channel}")
    print(f"\ndirection (what happens to the business when the lever rises): {', '.join(DIRECTIONS)}")
    print(f"strength: {', '.join(STRENGTHS)}")
    print("\nset one with: awltux levers set TICKER lever=direction[:strength] --reason TEXT")
    return 0


def cmd_levers_show(args: argparse.Namespace) -> int:
    """What is recorded for one instrument, primary first."""
    from awltux.analysis import levers
    from awltux.db import session_scope

    with session_scope() as session:
        instrument = _lever_instrument(session, args.ticker)
        if instrument is None:
            print(f"no such instrument: {args.ticker}", file=sys.stderr)
            return 2
        rows = [levers.describe(exposure) for exposure in levers.stored(session, args.ticker)]

    print(f"{instrument.name} ({args.ticker})")
    if not rows:
        print("  no levers recorded. The pages show this as 'not recorded yet' rather than")
        print("  as 'nothing moves it' -- the two are different answers.")
        return 0
    for row in rows:
        print(
            f"  [{row['strength_label']:<9}] {row['label']:<28} "
            f"{row['direction_label']}"
        )
        print(f"  {'':<12} {row['reason']}  ({row['source']}, {row['group_label']})")
    return 0


def cmd_levers_set(args: argparse.Namespace) -> int:
    """Record one or more levers against an instrument.

    Every argument is validated before anything is written, so a typo in the third assignment
    does not leave the first two stored -- a half-applied command is worse than a refused one.
    """
    from awltux.analysis import levers
    from awltux.db import session_scope

    try:
        exposures = [levers.parse(text) for text in args.exposure]
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not exposures:
        print("nothing to record: give at least one lever=DIRECTION", file=sys.stderr)
        return 2

    with session_scope() as session:
        instrument = _lever_instrument(session, args.ticker)
        if instrument is None:
            print(f"no such instrument: {args.ticker}", file=sys.stderr)
            return 2
        written = levers.record(
            session,
            args.ticker,
            exposures,
            reason=args.reason or "",
            source=args.source or levers.MANUAL,
        )
        names = [row.lever for row in written]

    for name in names:
        print(f"recorded {name} for {instrument.name} ({args.ticker})")
    print("it is on the instrument page now, and in the list under /levers")
    return 0


def cmd_levers_forget(args: argparse.Namespace) -> int:
    """Drop one lever, or every lever, from an instrument."""
    from awltux.analysis import levers
    from awltux.db import session_scope

    lever = None
    if args.lever:
        # Through the same resolver the setter uses, so a key, a label or a stray capital all
        # name the same lever here as they do there.
        lever = levers.resolve(args.lever)
        if lever is None:
            print(f"unknown lever: {args.lever}", file=sys.stderr)
            return 2

    with session_scope() as session:
        gone = levers.forget(session, args.ticker, lever)

    what = lever or "every lever"
    print(f"forgot {gone} record(s) of {what} for {args.ticker}")
    return 0


def cmd_levers(args: argparse.Namespace) -> int:
    return int(
        {
            "list": cmd_levers_list,
            "show": cmd_levers_show,
            "set": cmd_levers_set,
            "forget": cmd_levers_forget,
        }[args.levers_command](args)
        or 0
    )


def _add_levers_parser(sub) -> None:
    """The `levers` command group: the vocabulary, and what is recorded against an instrument.

    Its own function because `build_parser` is a flat list of declarations and this is
    thirty lines of them: inlined, the group reads as the shape of the whole CLI rather than
    as one command's arguments.
    """
    levers = sub.add_parser(
        "levers",
        help="record the levers an instrument's business is exposed to",
    )
    levers_sub = levers.add_subparsers(dest="levers_command", required=True)
    levers_sub.add_parser("list", help="print the lever vocabulary").set_defaults(
        func=cmd_levers
    )
    levers_show = levers_sub.add_parser("show", help="what is recorded for one instrument")
    levers_show.add_argument("ticker")
    levers_show.set_defaults(func=cmd_levers)

    levers_set = levers_sub.add_parser(
        "set",
        help="record lever=direction[:strength], replacing any earlier judgement",
    )
    levers_set.add_argument("ticker")
    levers_set.add_argument(
        "exposure",
        nargs="+",
        metavar="LEVER=DIRECTION[:STRENGTH]",
        help="e.g. interest_rates=negative:primary inflation=mixed",
    )
    levers_set.add_argument(
        "--reason",
        default="",
        help=(
            "the evidence for the judgement, stored verbatim and shown on the page. "
            "Left out, the record says 'no reason given' rather than inventing one."
        ),
    )
    levers_set.add_argument(
        "--source",
        default="",
        help="who recorded it: defaults to 'manual', the label a page prints as by hand",
    )
    levers_set.set_defaults(func=cmd_levers)

    levers_forget = levers_sub.add_parser("forget", help="drop one lever, or all of them")
    levers_forget.add_argument("ticker")
    levers_forget.add_argument("lever", nargs="?", default=None)
    levers_forget.set_defaults(func=cmd_levers)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="awltux", description="AwltuxTrading")
    parser.add_argument("--log-level", default=None, help="override the configured log level")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app and background scheduler")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "uvicorn workers. More than one needs the scheduler in its own process "
            "(`awltux schedule` plus AWLTUX_SCHEDULER_CONTROL_URL), because every worker's "
            "lifespan would otherwise start its own scheduler"
        ),
    )
    serve.set_defaults(func=cmd_serve)

    schedule = sub.add_parser(
        "schedule",
        help="run the background scheduler on its own, serving the control API the web tier uses",
    )
    schedule.add_argument("--host", default="127.0.0.1")
    schedule.add_argument("--port", type=int, default=None)
    schedule.set_defaults(func=cmd_schedule)

    sub.add_parser(
        "init-db", help="create missing tables (fresh installs only)"
    ).set_defaults(func=cmd_init_db)
    sub.add_parser(
        "migrate", help="upgrade an existing database to the current schema"
    ).set_defaults(func=cmd_migrate)

    doctor = sub.add_parser(
        "doctor", help="diagnose configuration and provider connectivity"
    )
    doctor.add_argument(
        "--offline",
        action="store_true",
        help="skip every network check and report local state only",
    )
    doctor.add_argument("-v", "--verbose", action="store_true", help="show all hints")
    doctor.set_defaults(func=cmd_doctor)

    seed = sub.add_parser(
        "seed-demo",
        help="create synthetic instruments so the dashboard works without any keys",
    )
    seed.add_argument(
        "--days", type=int, default=400, help="trading days of price history"
    )
    seed.add_argument(
        "--reset", action="store_true", help="remove previously seeded rows first"
    )
    seed.add_argument(
        "--no-analysis",
        action="store_true",
        help="seed data only, without running valuation, sentiment and decisions",
    )
    seed.set_defaults(func=cmd_seed_demo)
    sub.add_parser("settings", help="print effective configuration").set_defaults(
        func=cmd_settings
    )
    sub.add_parser("jobs", help="list registered scheduled jobs").set_defaults(func=cmd_jobs)

    publishers = sub.add_parser(
        "news-publishers",
        help="name the writer on stored stories and re-rate appraisals made against the feed",
    )
    publishers.add_argument(
        "--names-only",
        action="store_true",
        help="fill news_item.publisher but leave the stored appraisals alone",
    )
    publishers.set_defaults(func=cmd_news_publishers)

    job = sub.add_parser("job", help="run one scheduled job now")
    job.add_argument("job_id")
    job.add_argument(
        "--direct",
        action="store_true",
        help=(
            "run in this process instead of asking a running server to run it. "
            "Only use it when no server is up: two processes writing the same "
            "SQLite file contend for the write lock."
        ),
    )
    job.set_defaults(func=cmd_job)

    repair = sub.add_parser(
        "repair-scaled",
        help="correct stored figures a filing's unit scale should not have multiplied",
    )
    repair.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change and write nothing",
    )
    repair.set_defaults(func=cmd_repair_scaled)

    repair_units = sub.add_parser(
        "repair-price-units",
        help="correct stored prices whose unit contradicts the instrument's own currency",
    )
    repair_units.add_argument(
        "--dry-run",
        action="store_true",
        help="print what would change and write nothing",
    )
    repair_units.set_defaults(func=cmd_repair_price_units)

    repair_summaries = sub.add_parser(
        "repair-filing-summaries",
        help="summarise the filings read before anything wrote a summary",
    )
    repair_summaries.add_argument(
        "--dry-run",
        action="store_true",
        help="list the filings that would be read, and call nothing",
    )
    repair_summaries.add_argument(
        "--limit",
        type=int,
        default=0,
        help="stop after this many filings; the default is 0, meaning all of them",
    )
    repair_summaries.set_defaults(func=cmd_repair_filing_summaries)

    _add_levers_parser(sub)

    quiet = sub.add_parser(
        "quiet",
        help="stop starting jobs and wait for the running ones, before a rebuild",
    )
    quiet.add_argument(
        "--timeout",
        type=float,
        default=0.0,
        help=(
            "give up after this many seconds and exit 3. The default is 0: wait "
            "until nothing is running, however long that takes. A timeout shorter "
            "than the job being waited for defeats the purpose -- re-deciding is "
            "always faster than re-running a two-hour job."
        ),
    )
    quiet.add_argument("--poll", type=float, default=3.0, help="seconds between checks")
    quiet.set_defaults(func=cmd_quiet)

    sub.add_parser(
        "unquiet", help="resume scheduling after an abandoned upgrade"
    ).set_defaults(func=cmd_unquiet)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure(args.log_level or "INFO")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
