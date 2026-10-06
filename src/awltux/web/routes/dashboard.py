"""Dashboard pages (server-rendered HTML).

Sorting and filtering are done server-side and driven by query parameters, so
the table works without JavaScript and every view is a shareable URL. Live
updates (the news ticker) are the only thing that requires JS.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import desc, select

from awltux import __version__, version
from awltux.analysis import ledger
from awltux.analysis.fundamental import build_snapshot
from awltux.audit.calibration import HORIZON_WINDOWS, calibration_report
from awltux.buildinfo import DEFAULT_COMMIT_COUNT, load_build_info
from awltux.config import get_settings
from awltux.db import Filing, IngestRun, session_scope
from awltux.ingest.universe import cached_t212_capabilities
from awltux.timezones import as_utc
from awltux.web import filters, queries
from awltux.web.templating import templates

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=10, le=500),
) -> HTMLResponse:
    """The recommendations table -- the site's Recommendations page.

    The filters are read from the query string through
    :mod:`awltux.web.filters`, which is also what builds every link on the page, so
    a view is shareable and nothing is lost when the reader clicks a column header
    or moves a page.

    Only ``page`` and ``per_page`` are declared as typed parameters. They are the
    two the reader never types, so a nonsensical value is a bug worth refusing;
    the rest are validated against their own option lists and *reported* rather
    than refused, because a stale bookmark or a hand-edited URL should show the
    table and name what it ignored.
    """
    return templates.TemplateResponse(
        request, "dashboard.html", _recommendations_context(request, page, per_page)
    )


@router.get(
    "/partials/recommendations", response_class=HTMLResponse, include_in_schema=False
)
def recommendations_partial(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=10, le=500),
) -> HTMLResponse:
    """Just the recommendations table, for a page change that must not reload the page.

    The same region builder as the full page, so a fragment cannot show different rows,
    different counts or a different filter state from the page it replaces.
    """
    return templates.TemplateResponse(
        request,
        "partials/recommendations.html",
        _recommendations_region(request, page, per_page),
    )


def _recommendations_context(request: Request, page: int, per_page: int) -> dict[str, Any]:
    """Everything the whole page needs: the region plus what sits around it."""
    context = _recommendations_region(request, page, per_page)
    with session_scope() as session:
        context["stats"] = queries.universe_stats(session)
        context["capabilities"] = (
            cached_t212_capabilities(session) if get_settings().env.t212_configured else None
        )
    context["horizons"] = {
        "long_term": get_settings().horizons.long_term,
        "short_term": get_settings().horizons.short_term,
    }
    return context


def _recommendations_region(request: Request, page: int, per_page: int) -> dict[str, Any]:
    """The rows and the pager -- everything the swapped fragment needs, and no more.

    Split from the page context deliberately. A page change fetches only the region, so
    everything left in :func:`_recommendations_context` would otherwise be recomputed on
    every click: `universe_stats` is a full sweep of the universe and it is used by the
    summary strip *above* the table, which the swap does not touch.
    """
    with session_scope() as session:
        sectors = filters.sector_options(queries.sector_counts(session))
        # The one figure from the page header the region itself needs: it explains an
        # empty table, and an empty table is a thing the swap has to be able to render.
        size = queries.universe_size(session)

    allowed = filters.recommendation_specs(sectors=sectors)
    spec = filters.FilterSet.parse(allowed, request.query_params)

    sector, sector_unknown = filters.sector_filter(spec.opt("sector"))

    with session_scope() as session:
        rows, total = queries.recommendations(
            session,
            # Both are narrowed above by the specs' own option lists; a checker
            # cannot follow a runtime lookup back to a Literal, and the alternative
            # is restating the vocabulary here, which is what the specs removed.
            sort=spec.value("sort"),  # type: ignore[arg-type]
            direction=spec.value("direction"),  # type: ignore[arg-type]
            action=spec.opt("action"),
            engine=spec.opt("engine"),
            horizon=spec.value("horizon"),
            horizon_fit=spec.opt("horizon_fit"),
            sector=sector,
            sector_unknown=sector_unknown,
            only_suggestions=(spec.value("view") == "suggestions"),
            only_held=(spec.value("view") == "held"),
            search=spec.opt("q"),
            limit=per_page,
            offset=(page - 1) * per_page,
        )

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": max((total + per_page - 1) // per_page, 1),
        "per_page": per_page,
        "filters": spec,
        "universe_size": size,
    }


@router.get("/instrument/{ticker}", response_class=HTMLResponse, include_in_schema=False)
def instrument_page(
    request: Request,
    ticker: str,
    news_page: int = Query(1, ge=1),
) -> HTMLResponse:
    with session_scope() as session:
        detail = queries.instrument_detail(session, ticker, news_page=news_page)
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
            "news_total": detail["news_total"],
            "news_page": detail["news_page"],
            "news_pages": detail["news_pages"],
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


@router.get("/accounts/{period_id}", response_class=HTMLResponse, include_in_schema=False)
@router.get("/accounts/{period_id}/{statement}", response_class=HTMLResponse, include_in_schema=False)
def accounts_page(
    request: Request,
    period_id: int,
    statement: str = ledger.DEFAULT_STATEMENT,
) -> HTMLResponse:
    """One period's accounts, as a ledger, one statement per URL.

    A path segment rather than a query parameter so each statement is a real address:
    it can be linked to, bookmarked and reloaded, and the page works with JavaScript
    off like every other page here. A tab strip that only moved the highlight would
    make "send me the balance sheet" impossible to answer.

    An unknown statement is a 404 rather than a silent fallback to the first tab,
    because quietly showing profit and loss to someone who asked for the cash flow is
    how a reader ends up reading the wrong statement.
    """
    if statement not in ledger.TAB_NAMES:
        raise HTTPException(status_code=404, detail=f"no statement {statement!r}")

    with session_scope() as session:
        detail = queries.accounts_detail(session, period_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no accounts stored as {period_id}")

    period = detail["period"]
    previous = detail["previous"]
    metrics = period.metrics or {}
    # The same snapshot the instrument page reads, over the periods up to this one, so
    # the markers and red flags here cannot disagree with the ones shown there.
    snapshot = build_snapshot(detail["series"])

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "period": period,
            "previous": previous,
            "instrument": detail["instrument"],
            "statement": statement,
            "tabs": [
                {
                    "name": name,
                    "label": label,
                    "url": f"/accounts/{period_id}/{name}",
                    "active": name == statement,
                }
                for name, label in ledger.TABS
            ],
            "built": (
                ledger.statement(period, statement)
                if statement in ledger.STATEMENT_KINDS
                else None
            ),
            "health": ledger.checks(period, previous),
            "snapshot": snapshot,
            "empty": not metrics,
            "currency": period.currency or "",
            "period_type": period.period_type,
            "source": period.source,
            "metric_sources": (period.metric_sources or {}),
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
    """Sector sentiment, and the way into the instruments behind each sector.

    The drill-down is a link to the recommendations table with the sector filter
    applied rather than a table of its own. A sector view would otherwise need its
    own sorting, paging and filtering, and would be a second place for those rules
    to disagree with the first -- so the sector is handed to the page that already
    knows how to show instruments, and the link is just a querystring.

    The instrument count is carried into the link text because "sector" here is the
    SEC SIC industry string: the live universe has 144 of them for 500 instruments,
    and a reader who cannot see that most name one company will click expecting a
    list and find a single row.
    """
    with session_scope() as session:
        sectors = queries.sector_sentiment(session, days=60)
        counts = dict(queries.sector_counts(session))

    latest = {name: series[-1] if series else None for name, series in sectors.items()}
    ordered = sorted(
        sectors.items(),
        key=lambda item: (latest[item[0]]["score"] if latest[item[0]] else -99),
        reverse=True,
    )
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {
            "sectors": ordered,
            "latest": latest,
            "counts": counts,
        },
    )


@router.get("/jobs/{job_id}/log", response_class=HTMLResponse, include_in_schema=False)
def job_log_page(request: Request, job_id: str) -> HTMLResponse:
    """One job's most recent progress log, following it while it runs.

    Rendered server-side with the log already in it, so the page is useful with
    JavaScript off -- it simply stops following. That matters more here than
    elsewhere: this page exists to be read when a job is misbehaving, which is
    exactly when a script is the most likely thing to be broken.

    An unknown job id is not a 404. "That job has no log" is a true and useful
    answer, and a panel that refuses to open is worse than one that says there is
    nothing to show yet.
    """
    from awltux.scheduler import progress

    scheduler = getattr(request.app.state, "scheduler", None)
    spec = scheduler.get(job_id) if scheduler else None

    with session_scope() as session:
        run = session.execute(
            select(IngestRun)
            .where(IngestRun.job == job_id)
            .order_by(desc(IngestRun.id))
            .limit(1)
        ).scalar_one_or_none()

    text, offset, _size = progress.read(job_id, 0)
    # Normalised, because SQLite returns these naive however the column was declared
    # and the "still running" branch below subtracts them from an aware `now`. That
    # raised "can't subtract offset-naive and offset-aware datetimes", which main.py's
    # global handler turned into {"ok": false, "error": "TypeError"} -- so the panel
    # that exists to watch a job in flight was the one thing it refused to show. Every
    # finished run passed, because then both sides come back naive and agree.
    started = as_utc(run.started_at) if run else None
    finished = as_utc(run.finished_at) if run else None
    elapsed = None
    if started is not None:
        elapsed = ((finished or dt.datetime.now(dt.UTC)) - started).total_seconds()

    detail = (run.detail or {}) if run and run.detail else {}
    return templates.TemplateResponse(
        request,
        "job_log.html",
        {
            "job_id": job_id,
            "spec": spec,
            "run": run,
            "log_text": text,
            "offset": offset,
            "running": run is not None and finished is None,
            "elapsed": elapsed,
            "note": detail.get("note") or (run.error if run else None),
        },
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
            # Quieted-for-upgrade is a state a human set and must be able to see, or
            # the next person reads "no next run" on every row as a broken
            # scheduler -- which is exactly how the paused-jobs bug presented.
            "quiet": scheduler.quiet_status() if scheduler else None,
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
            # How the number was arrived at. A fallback that cannot be seen is a
            # fallback nobody fixes, and two of the three routes here (untagged,
            # packaging metadata) mean the version is not what a release would say.
            "version_source": version.current().source,
            "version_tag": version.current().tag,
            "revision": _schema_revision(),
            "provenance": _provenance_note(info),
            "environment": environment,
        },
    )
