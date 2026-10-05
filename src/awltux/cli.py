"""Command-line interface.

The same code paths the scheduler uses are exposed here, which makes every
scheduled action reproducible by hand -- useful when a provider is misbehaving
and you want to see the error rather than read it in the run history.

    awltux serve                 # run the web app and scheduler
    awltux init-db               # create the schema
    awltux settings              # show effective configuration (secrets redacted)
    awltux job <job-id>          # run one scheduled job now
    awltux jobs                  # list the registered jobs
"""

from __future__ import annotations

import argparse
import json
import sys

from awltux import __version__


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

    uvicorn.run(
        "awltux.main:app",
        host=args.host or settings.env.host,
        port=args.port or settings.env.port,
        log_config=None,  # our own redacting logging is already configured
        access_log=False,
    )
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


def cmd_jobs(_args: argparse.Namespace) -> int:
    from awltux.config import get_settings
    from awltux.scheduler.registry import build_job_specs

    for spec in build_job_specs(get_settings()):
        state = "enabled" if spec.enabled else f"disabled (needs {', '.join(spec.requires)})"
        print(f"{spec.id:24} every {spec.interval_seconds:>7}s  {state}")
        if spec.description:
            print(f"{'':24} {spec.description}")
    return 0


def cmd_job(args: argparse.Namespace) -> int:
    from awltux.config import get_settings
    from awltux.scheduler.jobs import execute_job
    from awltux.scheduler.registry import build_job_specs

    specs = {spec.id: spec for spec in build_job_specs(get_settings())}
    spec = specs.get(args.job_id)
    if spec is None:
        print(f"unknown job {args.job_id!r}. Available: {', '.join(sorted(specs))}", file=sys.stderr)
        return 2

    result = execute_job(spec)
    if result is not None:
        print(json.dumps(result.detail, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="awltux", description="AwltuxTrading")
    parser.add_argument("--log-level", default=None, help="override the configured log level")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the web app and background scheduler")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=cmd_serve)

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

    job = sub.add_parser("job", help="run one scheduled job now")
    job.add_argument("job_id")
    job.set_defaults(func=cmd_job)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _configure(args.log_level or "INFO")
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
