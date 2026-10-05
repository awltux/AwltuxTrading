"""Dashboard pages (server-rendered HTML).

Sorting and filtering are done server-side and driven by query parameters, so
the table works without JavaScript and every view is a shareable URL. Live
updates (the news ticker) are the only thing that requires JS.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from awltux import __version__
from awltux.audit.calibration import calibration_report
from awltux.buildinfo import DEFAULT_COMMIT_COUNT, load_build_info
from awltux.config import get_settings
from awltux.db import session_scope
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

    return templates.TemplateResponse(
        request,
        "instrument.html",
        {
            "ticker": ticker,
            "instrument": detail["instrument"],
            "decision": detail["decision"],
            "valuation": detail["valuation"],
            "history": history,
            "filings": detail["filings"],
            "fundamentals": detail["fundamentals"],
            "news": detail["news"],
            "outcomes": detail["outcomes"],
            "horizons": {
                "long_term": get_settings().horizons.long_term,
                "short_term": get_settings().horizons.short_term,
            },
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
def jobs_page(request: Request) -> HTMLResponse:
    scheduler = getattr(request.app.state, "scheduler", None)
    with session_scope() as session:
        stats = queries.universe_stats(session)

    # Recent runs per job, newest first, for the operations panel.
    from sqlalchemy import desc, select

    from awltux.db import IngestRun

    with session_scope() as session:
        runs = session.execute(
            select(IngestRun).order_by(desc(IngestRun.started_at)).limit(100)
        ).scalars().all()

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "jobs": scheduler.status() if scheduler else [],
            "runs": runs,
            "stats": stats,
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


@router.get("/info", response_class=HTMLResponse, include_in_schema=False)
def info_page(request: Request) -> HTMLResponse:
    """What this process is running, and which commit that was."""
    info = load_build_info(DEFAULT_COMMIT_COUNT)
    return templates.TemplateResponse(
        request,
        "info.html",
        {
            "info": info,
            "version": __version__,
            "revision": _schema_revision(),
            "provenance": _provenance_note(info),
        },
    )
