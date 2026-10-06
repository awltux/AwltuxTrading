"""Dashboard pages (server-rendered HTML).

Sorting and filtering are done server-side and driven by query parameters, so
the table works without JavaScript and every view is a shareable URL. Live
updates (the news ticker) are the only thing that requires JS.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from awltux import __version__
from awltux.audit.calibration import HORIZON_WINDOWS, calibration_report
from awltux.buildinfo import DEFAULT_COMMIT_COUNT, load_build_info
from awltux.config import get_settings
from awltux.db import Filing, session_scope
from awltux.ingest.universe import cached_t212_capabilities
from awltux.web import queries
from awltux.web.templating import templates

router = APIRouter(tags=["dashboard"])

SortKey = Literal[
    "composite_score", "short_term_score", "margin_of_safety", "confidence",
    "short_term_confidence", "action", "short_term_action", "name",
    "change_pct", "sentiment", "freshness", "horizon_fit",
]


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    sort: SortKey = "composite_score",
    direction: Literal["asc", "desc"] = "desc",
    action: str | None = None,
    engine: str | None = None,
    horizon: Literal["long_term", "short_term"] = "long_term",
    horizon_fit: str | None = None,
    view: Literal["all", "suggestions", "held"] = "all",
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=10, le=500),
) -> HTMLResponse:
    """The recommendations table.

    ``horizon`` selects which verdict drives the *actionable* filter and the
    action column; both are always shown, because the point of separating them is
    that a reader can see them disagree.
    """
    offset = (page - 1) * per_page
    with session_scope() as session:
        rows, total = queries.recommendations(
            session,
            sort=sort,
            direction=direction,
            action=action,
            engine=engine,
            horizon=horizon,
            horizon_fit=horizon_fit,
            only_suggestions=(view == "suggestions"),
            only_held=(view == "held"),
            search=q,
            limit=per_page,
            offset=offset,
        )
        stats = queries.universe_stats(session)
        sectors = queries.sector_sentiment(session, days=30)
        capabilities = cached_t212_capabilities(session) if get_settings().env.t212_configured else None

    pages = max((total + per_page - 1) // per_page, 1)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "rows": rows,
            "total": total,
            "page": page,
            "pages": pages,
            "per_page": per_page,
            "sort": sort,
            "direction": direction,
            "action": action,
            "engine": engine,
            "horizon": horizon,
            "horizon_fit": horizon_fit,
            "view": view,
            "q": q or "",
            "stats": stats,
            "sectors": sectors,
            "capabilities": capabilities,
            "horizons": {
                "long_term": get_settings().horizons.long_term,
                "short_term": get_settings().horizons.short_term,
            },
        },
    )


@router.get("/instrument/{ticker}", response_class=HTMLResponse, include_in_schema=False)
def instrument_page(request: Request, ticker: str) -> HTMLResponse:
    with session_scope() as session:
        detail = queries.instrument_detail(session, ticker)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument {ticker}")
        history = queries.price_history(session, ticker, limit=400)
        # The chart frame is drawn whether or not there is anything to put in it,
        # so the panel needs a sentence saying what it is waiting for. Computed
        # here rather than in the template because it is four different reads.
        waiting_note = queries.price_history_waiting_note(session, ticker, bars=len(history))
        # The page used to show only the latest decision, so "what did it say last
        # week, and was it right" had no answer anywhere.
        predictions, prediction_count = queries.decision_history(
            session, ticker=ticker, limit=25
        )

    return templates.TemplateResponse(
        request,
        "instrument.html",
        {
            "ticker": ticker,
            "instrument": detail["instrument"],
            "decision": detail["decision"],
            "valuation": detail["valuation"],
            "history": history,
            "waiting_note": waiting_note,
            "filings": detail["filings"],
            "fundamentals": detail["fundamentals"],
            "news": detail["news"],
            "news_analysis": detail["news_analysis"],
            "outcomes": detail["outcomes"],
            "predictions": predictions,
            "prediction_count": prediction_count,
            "horizon_windows": HORIZON_WINDOWS,
            "horizons": {
                "long_term": get_settings().horizons.long_term,
                "short_term": get_settings().horizons.short_term,
            },
        },
    )


@router.get("/decisions", response_class=HTMLResponse, include_in_schema=False)
def decisions_page(
    request: Request,
    ticker: str | None = None,
    engine: str | None = None,
    only: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> HTMLResponse:
    """Every prediction ever made, with how it turned out.

    The predictions were always stored immutably -- state, state hash, engine,
    prompt hashes, both horizons' calls -- but the only way to read one back was to
    know its id and request the receipt. A record you cannot find again is not much
    of a record.

    Unscored rows are shown, not hidden. A horizon that has not elapsed yet is
    "not knowable", which is a different thing from "scored flat", and hiding them
    would make an empty accuracy table look like a working one.
    """
    from sqlalchemy import select

    from awltux.audit.calibration import HORIZON_WINDOWS, calibration_report
    from awltux.db import DecisionRun

    page = max(1, page)
    per_page = min(max(per_page, 10), 200)

    with session_scope() as session:
        rows, total = queries.decision_history(
            session,
            ticker=ticker or None,
            engine=engine or None,
            only=only or None,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        pages = max(1, -(-total // per_page))
        # The aggregate view is only meaningful once outcomes exist, and it already
        # has its own page; this repeats it in miniature so the ledger says whether
        # the numbers above mean anything yet.
        reports = {
            horizon: calibration_report(session, horizon=horizon)
            for horizon in HORIZON_WINDOWS
        }
        engines = [
            name
            for (name,) in session.execute(
                select(DecisionRun.engine).distinct().order_by(DecisionRun.engine)
            ).all()
            if name
        ]

    return templates.TemplateResponse(
        request,
        "decisions.html",
        {
            "predictions": rows,
            "total": total,
            "page": min(page, pages),
            "pages": pages,
            "per_page": per_page,
            "horizon_windows": HORIZON_WINDOWS,
            "reports": reports,
            "engines": engines,
            "filters": {"ticker": ticker or "", "engine": engine or "", "only": only or ""},
        },
    )


@router.get("/sectors", response_class=HTMLResponse, include_in_schema=False)
def sectors_page(request: Request) -> HTMLResponse:
    with session_scope() as session:
        sectors = queries.sector_sentiment(session, days=60)
    latest = {
        name: series[-1] if series else None for name, series in sectors.items()
    }
    ordered = sorted(
        sectors.items(),
        key=lambda item: (latest[item[0]]["score"] if latest[item[0]] else -99),
        reverse=True,
    )
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {"sectors": ordered, "latest": latest},
    )


@router.get("/calibration", response_class=HTMLResponse, include_in_schema=False)
def calibration_page(
    request: Request,
    horizon: Literal["long_term", "short_term"] = "long_term",
) -> HTMLResponse:
    """Calibration for one horizon at a time.

    Reported separately because the two are judged on different timescales and
    blending them would produce a hit rate that describes neither.
    """
    with session_scope() as session:
        report = calibration_report(session, horizon=horizon)
        other = calibration_report(
            session, horizon="short_term" if horizon == "long_term" else "long_term"
        )
    return templates.TemplateResponse(
        request,
        "calibration.html",
        {
            "report": report,
            "other": other,
            "horizon": horizon,
            "horizons": {
                "long_term": get_settings().horizons.long_term,
                "short_term": get_settings().horizons.short_term,
            },
        },
    )


@router.get("/jobs", response_class=HTMLResponse, include_in_schema=False)
def jobs_page(
    request: Request,
    run_job: str | None = None,
    run_since: str | None = None,
    run_until: str | None = None,
    run_min_seconds: float | None = None,
    run_page: int = 1,
    run_per_page: int = 25,
) -> HTMLResponse:
    """Operations: the pipeline, and the history of what it has actually done.

    The history grows without bound -- one row per job per interval, so a few
    hundred a week -- so it is paged and filtered rather than capped at the newest
    hundred. Finding "the ingest that took forty minutes last Tuesday" is the whole
    point of keeping it.
    """
    scheduler = getattr(request.app.state, "scheduler", None)
    with session_scope() as session:
        stats = queries.universe_stats(session)

    from sqlalchemy import desc, func, select

    from awltux.db import IngestRun
    from awltux.scheduler.outcomes import outcome_for
    from awltux.timezones import parse_moment

    run_page = max(1, run_page)
    run_per_page = min(max(run_per_page, 10), 200)

    with session_scope() as session:
        conditions = []
        if run_job:
            conditions.append(IngestRun.job == run_job)

        # Dates are inclusive of the whole day the reader picked, because a filter
        # that silently excludes the day you chose is worse than no filter.
        since = parse_moment(run_since, end_of_day=False)
        until = parse_moment(run_until, end_of_day=True)
        if since is not None:
            conditions.append(IngestRun.started_at >= since)
        if until is not None:
            conditions.append(IngestRun.started_at <= until)
        if run_min_seconds is not None and run_min_seconds > 0:
            # Duration is not stored: it is the gap between two timestamps, and
            # SQLite compares them as text in the same sortable format.
            conditions.append(
                (func.julianday(IngestRun.finished_at) - func.julianday(IngestRun.started_at))
                * 86400.0
                >= run_min_seconds
            )

        total = session.execute(
            select(func.count()).select_from(IngestRun).where(*conditions)
        ).scalar_one()
        pages = max(1, -(-total // run_per_page))
        run_page = min(run_page, pages)

        runs = list(
            session.execute(
                select(IngestRun)
                .where(*conditions)
                .order_by(desc(IngestRun.started_at))
                .offset((run_page - 1) * run_per_page)
                .limit(run_per_page)
            ).scalars().all()
        )
        job_names = [
            name
            for (name,) in session.execute(
                select(IngestRun.job).distinct().order_by(IngestRun.job)
            ).all()
            if name
        ]
        # Derived here rather than stored: the wording improves, and every past run
        # should benefit from a better explanation instead of being frozen at the
        # phrasing that happened to be current when it ran.
        outcomes = {run.id: outcome_for(run) for run in runs}

    # What each job still owes, and which ones are worth running now. Computed
    # from the data rather than the run history: "never run" and "its dependency
    # never ran" look identical in a history and need different actions.
    from awltux.scheduler.dependencies import (
        job_statuses,
        jobs_that_have_ever_succeeded,
        next_steps,
    )
    from awltux.scheduler.jobs import running_jobs

    specs = scheduler.specs() if scheduler else []
    with session_scope() as session:
        statuses = job_statuses(session, specs) if specs else []
        succeeded = jobs_that_have_ever_succeeded(session) if specs else set()
        in_flight = running_jobs(session) if specs else set()
    queue = next_steps(statuses)
    # Used to colour the "needs first" chips: a prerequisite that has never
    # completed is a different problem from one that merely ran a while ago.
    blocked_jobs = {spec.id for spec in specs} - succeeded

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "jobs": scheduler.status() if scheduler else [],
            "runs": runs,
            "stats": stats,
            "statuses": statuses,
            "queue": queue,
            "blocked_jobs": blocked_jobs,
            # A job appears in two tables -- "run these next" and "scheduled jobs"
            # -- so both must show the same state. The browser cannot be trusted to
            # remember that across a reload, and the first job to finish triggers
            # one.
            "in_flight": in_flight,
            "outcomes": outcomes,
            "job_names": job_names,
            "run_total": total,
            "run_page": run_page,
            "run_pages": pages,
            "run_per_page": run_per_page,
            "filters": {
                "job": run_job or "",
                "since": run_since or "",
                "until": run_until or "",
                "min_seconds": run_min_seconds if run_min_seconds else "",
            },
        },
    )


def _schema_revision() -> str | None:
    """The Alembic revision the live database is stamped with.

    Read through the session's own connection rather than ``migrate.current_revision``,
    which would open a second engine just to answer a question the dashboard can
    already ask. The failure text is deliberately not surfaced -- it can quote the
    database URL, and this page is unauthenticated.
    """
    from alembic.runtime.migration import MigrationContext

    try:
        with session_scope() as session:
            return MigrationContext.configure(session.connection()).get_current_revision()
    except Exception:  # noqa: BLE001 - an unknown revision must not break the page
        return None


def _provenance_note(info) -> str:
    """Say where the history on the page came from, because the sources differ in
    how much they can be trusted."""
    if info.source == "git":
        return "Read live from the git checkout this process was started from."
    if info.source == "bundled":
        when = f" on {info.generated_at}" if info.generated_at else ""
        return f"Recorded in the installed package when the image was built{when}."
    return (
        "No git checkout and no recorded build artifact, so this install cannot "
        "name the revision it is running."
    )


@router.get("/filing/{filing_id}/document", include_in_schema=False)
def filing_document(filing_id: int) -> Response:
    """Serve a downloaded shareholders' report so it can be read.

    **Served with a sandbox policy, not merely as a file.** A filing is third-party
    HTML from a host this application does not control, and it is served from the
    dashboard's own origin -- an origin that can reach the API and therefore the
    account. `Content-Security-Policy: sandbox` puts the document in an opaque origin
    with scripts, forms and same-origin reads disabled, so the browser will lay out a
    10-K and refuse to let it do anything else. Deliberately not `allow-same-origin`,
    which would hand back exactly the access the policy exists to remove.

    The path is re-resolved against the data directory before it is opened. It comes
    from our own database, but a stored path is still a path, and a route that joins
    one to a root without checking is how a traversal arrives.
    """
    settings = get_settings()
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None or not filing.raw_path:
            raise HTTPException(
                status_code=404,
                detail=f"no stored document for filing {filing_id}",
            )
        raw_path = filing.raw_path
        document_type = filing.content_type or "text/html"
        title = filing.title or filing.filing_type or "filing"

    data_dir = settings.data_dir.resolve()
    path = (data_dir / raw_path).resolve()
    if not path.is_relative_to(data_dir) or not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"stored document for filing {filing_id} is missing"
        )

    return Response(
        content=path.read_bytes(),
        media_type=document_type,
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{filing_id}.htm"',
            # The document is immutable once filed, so it is worth caching in the
            # browser; a reader going back and forth through six years should not
            # re-download a megabyte each time.
            "Cache-Control": "private, max-age=86400",
            "X-Document": title[:120],
        },
    )


@router.get("/info", response_class=HTMLResponse, include_in_schema=False)
def info_page(request: Request) -> HTMLResponse:
    """What this process is running, and which commit that was."""
    info = load_build_info(DEFAULT_COMMIT_COUNT)
    with session_scope() as session:
        # The rate environment belongs on this page: it is what the model is
        # valuing against, in the same way the commit is what it is running.
        environment = queries.rate_environment(session)
    return templates.TemplateResponse(
        request,
        "info.html",
        {
            "info": info,
            "version": __version__,
            "revision": _schema_revision(),
            "provenance": _provenance_note(info),
            "environment": environment,
        },
    )
