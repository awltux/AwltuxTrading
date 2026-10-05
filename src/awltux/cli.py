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

    settings = get_settings()
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
