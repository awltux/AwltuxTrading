"""Dashboard pages (server-rendered HTML).

Sorting and filtering are done server-side and driven by query parameters, so
the table works without JavaScript and every view is a shareable URL. Live
updates (the news ticker) are the only thing that requires JS.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, select

from awltux import __version__, version
from awltux import metrics as metrics_module
from awltux.analysis import adopted as adopted_map
from awltux.analysis import corrections as corrections_rules
from awltux.analysis import ledger
from awltux.analysis import sectors as sector_map
from awltux.analysis.fundamental import build_snapshot
from awltux.audit.calibration import HORIZON_WINDOWS, calibration_report
from awltux.buildinfo import DEFAULT_COMMIT_COUNT, load_build_info
from awltux.config import get_settings
from awltux.db import Filing, IngestRun, ResearchReport, session_scope
from awltux.ingest import lease
from awltux.ingest.universe import cached_t212_capabilities
from awltux.research import service as research_service
from awltux.scheduler import scoped
from awltux.timezones import as_utc
from awltux.web import filters, queries
from awltux.web.templating import templates

logger = logging.getLogger(__name__)

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
            needs_attention=spec.given("attention"),
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


def _price_chart(session, ticker: str, detail: dict[str, Any]) -> dict[str, Any]:
    """The price panel's three facts: the bars, the reader's fills on them, and what it is
    waiting for.

    One helper because they are one panel and two of them derive from the first -- the
    markers are placed on the very bars that are plotted, so the chart and the tables below
    cannot describe different date windows. The waiting sentence is computed here rather
    than in the template because reaching it is four different reads.
    """
    history = queries.price_history(session, ticker, limit=400)
    return {
        "history": history,
        "markers": queries.price_markers(history, detail["trades"], detail["instrument"]),
        "waiting_note": queries.price_history_waiting_note(
            session, ticker, bars=len(history)
        ),
    }


#: The instrument page's topics, in the order a reader wants them.
#:
#: **One topic per URL, and one rendered at a time.** The page had grown to nine topics on a
#: single scroll -- a decision, its history, a valuation, a chart, filings, accounts, news,
#: a position and a refresh control -- so "send me the news for this company" had no address
#: that meant it, and a reader arriving from the recommendations table landed at the top of
#: a document they then had to search. `accounts_page` already does this with its
#: statements, for the same reason, and the shape is copied from there rather than invented
#: again: real links, so the strip works with JavaScript off.
INSTRUMENT_TABS: tuple[tuple[str, str], ...] = (
    ("decision", "Decision"),
    ("valuation", "Valuation"),
    ("price", "Price history"),
    ("reports", "Published reports"),
    ("accounts", "Accounts"),
    ("news", "News"),
    ("research", "Research"),
    ("position", "Position"),
    ("refresh", "Refresh"),
)

INSTRUMENT_TAB_NAMES: tuple[str, ...] = tuple(name for name, _ in INSTRUMENT_TABS)

#: What `/instrument/{ticker}` shows with no `?tab=`. The verdict, because "what do you
#: think" is the question the page exists to answer, and it is where a link from the
#: recommendations table should land.
INSTRUMENT_DEFAULT_TAB = "decision"

#: Which query sections each tab needs. Anything not listed is still fetched, because the
#: summary strip at the top of every tab needs it -- the instrument, the decision, the
#: valuation and the price bars. The news block is the expensive one: it pages, it appraises
#: and it clusters events through the embeddings, and running all of that for the Refresh
#: tab would be work nobody asked for.
INSTRUMENT_TAB_SECTIONS: dict[str, tuple[str, ...]] = {
    "news": ("news",),
    "reports": ("filings",),
    "accounts": ("fundamentals",),
    "position": ("trades",),
    "price": ("trades",),
}


def _instrument_tab(
    ticker: str, requested: str | None
) -> tuple[str, list[dict[str, object]], str | None]:
    """Resolve the requested tab, the strip, and any value that had to be ignored.

    An unusable value renders the page and says so rather than 404ing, which is the rule
    `web/filters.py` states for a query parameter: this is a view selector, not the address,
    and a bookmark to a tab that has been renamed should not cost the reader the page. It is
    the one place this deliberately differs from `accounts_page`, where the statement *is* a
    path segment and an unknown one is a 404.
    """
    ignored = None
    if requested and requested not in INSTRUMENT_TAB_NAMES:
        ignored, requested = requested, None
    active = requested or INSTRUMENT_DEFAULT_TAB

    base = f"/instrument/{quote(ticker, safe='')}"
    strip = [
        {"name": name, "label": label, "url": f"{base}?tab={name}", "active": name == active}
        for name, label in INSTRUMENT_TABS
    ]
    return active, strip, ignored


def _instrument_summary(
    detail: dict[str, Any], history: list[dict[str, Any]]
) -> dict[str, Any]:
    """The handful of figures the top of the page shows on every tab.

    **Deliberately small.** The detail is one click away and repeating it here would rebuild
    the long page this replaced. What belongs at the top is what a reader needs in order to
    decide *which* tab to open: what it is, what it costs and which way it moved, what the
    engine says on each horizon, and how stale any of that is.

    The price comes from the same `history` the chart draws, so the number in the summary
    and the last point of the line cannot disagree -- they are one query.
    """
    close = history[-1]["close"] if history else None
    previous = history[-2]["close"] if len(history) > 1 else None
    change = None
    if close is not None and previous:
        change = (close - previous) / previous
    return {
        "close": close,
        "close_date": history[-1]["date"] if history else None,
        "change": change,
        "bars": len(history),
    }


def _instrument_context(
    request: Request,
    *,
    ticker: str,
    detail: dict[str, Any],
    chart: dict[str, Any],
    predictions: list[Any],
    prediction_count: int,
    refresh_state: dict[str, Any] | None,
    active: str,
    strip: list[dict[str, object]],
    tab_ignored: str | None,
) -> dict[str, Any]:
    """Everything `instrument.html` reads, assembled in one place.

    Split from the route because the route's job is to decide *what* to fetch -- which is now
    a question about the current tab -- and the template's is to render it. Every name here
    has to be present even when its tab is not being rendered: Jinja's default undefined is
    falsy rather than an error, so a key the route forgets renders as nothing at all, which
    is how the trades table and the event grouping were both lost for a commit each.
    """
    return {
        "ticker": ticker,
        "instrument": detail["instrument"],
        "summary": _instrument_summary(detail, chart["history"]),
        "tabs": strip,
        "tab": active,
        "tab_ignored": tab_ignored,
        "decision": detail["decision"],
        "valuation": detail["valuation"],
        "history": chart["history"],
        "markers": chart["markers"],
        "waiting_note": chart["waiting_note"],
        "filings": detail["filings"],
        "fundamentals": detail["fundamentals"],
        "account_years": detail["account_years"],
        "news": detail["news"],
        "news_events": detail["news_events"],
        "news_clustering": detail["news_clustering"],
        "news_analysis": detail["news_analysis"],
        "news_total": detail["news_total"],
        "news_page": detail["news_page"],
        "news_pages": detail["news_pages"],
        "outcomes": detail["outcomes"],
        "trades": detail["trades"],
        "trades_truncated": detail["trades_truncated"],
        "predictions": predictions,
        "prediction_count": prediction_count,
        "horizon_windows": HORIZON_WINDOWS,
        "refresh": refresh_state,
        "refresh_job": scoped.REFRESH_JOB,
        "refresh_message": request.query_params.get("refresh"),
        # The deep-dive block, and the latest report's executive summary at the top of every
        # tab. Both come from one query that is cheap -- a subject has a handful of reports --
        # so it is not gated behind the Research tab the way the news block is.
        **detail["research"],
        "subject_type": "instrument",
        "subject_label": f"{detail['instrument'].name} ({ticker})",
        "research_action": f"/instrument/{quote(ticker, safe='')}/research",
        "research_prompt_url": f"/instrument/{quote(ticker, safe='')}/research/prompt",
        "research_base": f"/instrument/{quote(ticker, safe='')}?tab=research",
        "research_job": research_service.RESEARCH_JOB,
        "research_message": request.query_params.get("research"),
        "research_reason": request.query_params.get("why"),
        "horizons": {
            "long_term": get_settings().horizons.long_term,
            "short_term": get_settings().horizons.short_term,
        },
    }


@router.get("/instrument/{ticker}", response_class=HTMLResponse, include_in_schema=False)
def instrument_page(
    request: Request,
    ticker: str,
    tab: str | None = None,
    news_page: int = Query(1, ge=1),
) -> HTMLResponse:
    """One instrument, summarised at the top and split into tabs below.

    Only the current tab is rendered, and only its sections are read -- see
    ``INSTRUMENT_TAB_SECTIONS``. ``news_page`` is parsed on every request and read on one of
    them: FastAPI validates it before this runs, and a tab that ignored a malformed page
    number silently would be worse than one that refuses it.
    """
    active, strip, tab_ignored = _instrument_tab(ticker, tab)
    sections = INSTRUMENT_TAB_SECTIONS.get(active, ())

    with session_scope() as session:
        detail = queries.instrument_detail(
            session, ticker, news_page=news_page, sections=sections
        )
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument {ticker}")
        chart = _price_chart(session, ticker, detail)
        # The page used to show only the latest decision, so "what did it say last
        # week, and was it right" had no answer anywhere.
        predictions, prediction_count = (
            queries.decision_history(session, ticker=ticker, limit=25)
            if active == "decision"
            else ([], 0)
        )
        # The lease doubles as the refresh's progress: the same row that stops a sweep
        # touching this instrument says which step is running.
        refresh_row = lease.current(session, ticker) if active == "refresh" else None
        refresh_state = queries.refresh_state(refresh_row)

    return templates.TemplateResponse(
        request,
        "instrument.html",
        _instrument_context(
            request,
            ticker=ticker,
            detail=detail,
            chart=chart,
            predictions=predictions,
            prediction_count=prediction_count,
            refresh_state=refresh_state,
            active=active,
            strip=strip,
            tab_ignored=tab_ignored,
        ),
    )


@router.post("/instrument/{ticker}/refresh", include_in_schema=False)
def instrument_refresh(ticker: str) -> RedirectResponse:
    """Force the pipeline stages for one instrument, and return immediately.

    A POST rather than a link, and not because of the semantics: a GET would be followed
    by any prefetcher or crawler that happened to see the URL, and this spends provider
    and model budget. The redirect carries the outcome as a query parameter, so the page
    can say why nothing started without keeping state anywhere.
    """
    outcome = scoped.start(ticker)
    reason = "started" if outcome.ok else "refused"
    return RedirectResponse(
        # Back to the tab the button is on, so the outcome it prints is the outcome the
        # reader sees rather than a decision tab they then have to navigate away from.
        url=f"/instrument/{quote(ticker, safe='')}?tab=refresh&refresh={reason}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/credit/refresh", include_in_schema=False)
def credit_refresh(request: Request) -> RedirectResponse:
    """Re-read every provider's balance, and return to the page that asked.

    A POST for the reason the instrument refresh is one: a GET would be followed by any
    prefetcher or crawler that saw the URL, and this spends two provider calls. The
    redirect is what makes the button feel like a button -- the reader stays where they
    were, and the *only* visible change is the reading timestamp, which is the feedback.

    The balance read happens **before** the session opens, so the network call is not
    made inside a transaction. Two provider calls a second or so apart is a real hold on
    SQLite's single writer, and ``db/session.py`` documents what holding it costs.
    """
    from awltux.providers import balances as balance_probes

    readings = balance_probes.read_all()
    with session_scope() as session:
        balance_probes.store(session, readings)

    return RedirectResponse(
        url=_same_page(request.query_params.get("next")),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _same_page(target: str | None) -> str:
    """``target`` if it is a path on this site, else the dashboard.

    The value arrives from the template as the page the strip was rendered on, which
    makes it a redirect target a caller controls. Anything absolute, protocol-relative
    or backslash-escaped is refused: an unchecked one turns every page in the
    application into an open redirect, which is a phishing primitive rather than a bug.
    """
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/dashboard"


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
        detail = _accounts_detail(session, period_id)

    period = detail["period"]
    previous = detail["previous"]
    metrics = period.metrics or {}
    # The same snapshot the instrument page reads, over the periods up to this one, so
    # the markers and red flags here cannot disagree with the ones shown there. The series is
    # the collated years, so the snapshot is computed from the same figures the ledger lays out.
    snapshot = build_snapshot(detail["series"])
    # Read once, because the filer's declared arithmetic drives both: the statement's
    # Computed column and the composition checks. See `_filer_arithmetic`. The row is the one
    # read from a filed document when there is one, because the linkbase belongs to a filing
    # and the chosen row may be the SEC's own aggregate.
    arithmetic = _filer_arithmetic(
        session, detail["instrument"], detail.get("filing_period") or period, request
    )
    declared = arithmetic.pop("declared")
    # What a reader has changed by hand, and whether there is a filer to change it for.
    instrument = detail["instrument"]
    corrections_context = _corrected_accounts(
        session, period, instrument, request.query_params.get("corrections")
    )

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "period": period,
            "previous": previous,
            "year": detail["year"],
            "instrument": instrument,
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
                ledger.statement(period, statement, declared=declared)
                if statement in ledger.STATEMENT_KINDS
                else None
            ),
            "health": ledger.checks(period, previous, declared=declared),
            **arithmetic,
            "snapshot": snapshot,
            "empty": not metrics,
            "currency": period.currency or "",
            "period_type": period.period_type,
            "source": period.source,
            "metric_sources": (period.metric_sources or {}),
            **corrections_context,
        },
    )


def _corrected_accounts(
    session: Any, period: Any, instrument: Any, outcome: str | None
) -> dict[str, Any]:
    """What a reader has changed about this period, ready for the page's context.

    A named step rather than lines in the route, because it is the one part of the accounts page
    that is about *this project* rather than about the filing: everything above it is the filer's
    own arithmetic, and this is the record of where a person disagreed with it.
    """
    cik = instrument.sec_cik if instrument is not None else None
    rules = corrections_rules.load_filer(session, cik)
    return {
        "corrections": corrections_rules.corrections_for(period, rules),
        "correction_note": CORRECTION_NOTES.get(outcome or ""),
        # Offered only where there is a filer to offer it for: a removal recorded against a CIK
        # that this period does not have would have nothing to apply to.
        "cik": cik,
    }


def _filer_arithmetic(
    session: Any, instrument: Any, period: Any, request: Request
) -> dict[str, Any]:
    """The filer's own declared subtotals, its linkbase state, and its arithmetic.

    A named step rather than lines inside the route, because it is the one part of the
    accounts page that is about the *filing* rather than about our figures: the stored
    linkbase is read here, reconciled against this period, and the button's outcome is
    carried in from the redirect. ``filer_checks`` is empty until somebody presses it,
    which the template renders as the button rather than as an empty table.

    ``declared`` is the same declaration expressed as *values* -- what the filer's own
    children add up to from the figures we hold -- and the caller hands it to the ledger,
    so the statement's Computed column and the composition checks are the issuer's
    arithmetic rather than this codebase's key lists. It is popped out of the context
    because no template needs it.
    """
    from awltux.analysis import linkbase as reconciliation
    from awltux.ingest import linkbase as linkbases

    accession = reconciliation.accession(period)
    stored = linkbases.stored(session, accession) if accession else None
    figures = dict(stored.values.get(period.period_end.isoformat()) or {}) if stored else {}
    names = dict(stored.labels.names) if stored else {}
    return {
        "declared": (
            reconciliation.declared_sums(
                period, stored.linkbase, figures=figures, names=names
            )
            if stored
            else {}
        ),
        "filer_checks": (
            reconciliation.ordered(
                reconciliation.checks(
                    period, stored.linkbase, figures=figures, names=names
                ),
                stored.presentation,
            )
            if stored
            else []
        ),
        "adoption": _adoption(session, instrument, period, stored, figures, names),
        "linkbase": {
            "accession": accession,
            "file": stored.source if stored else "",
            "files": dict(stored.files) if stored else {},
            "labels": len(stored.labels.names) if stored else 0,
            "outcome": request.query_params.get("linkbase", ""),
            "cik": instrument.sec_cik if instrument is not None else None,
        },
    }


def _adoption(
    session: Any, instrument: Any, period: Any, stored: Any, figures: dict, names: dict
) -> dict[str, Any]:
    """What this filing's arithmetic proves, and what has already been adopted from it.

    Both halves of the one question the adoption answers: *which lines does this filing
    prove we are missing, and which of them have we already taken?* Reading them together
    is what lets the page offer the action only while there is something to adopt -- a
    proof the figures have already absorbed is not an offer, it is a receipt.
    """
    from awltux.analysis import linkbase as reconciliation

    proven = (
        reconciliation.provable(period, stored.linkbase, figures=figures, names=names)
        if stored
        else ()
    )
    adoption = adopted_map.read(session, instrument.sec_cik if instrument else None)
    return {
        "proven": [
            {
                "side": proof.side,
                "residual": proof.residual,
                # The filer's own words for the lines; the tags are in the store.
                "additions": {
                    metric: [names.get(tag) or tag for tag in tags]
                    for metric, tags in proof.additions.items()
                },
            }
            for proof in proven
        ],
        "tags": adoption.tags,
        "evidence": adoption.evidence[-1] if adoption.evidence else None,
    }


def _read_filing_arithmetic(
    provider: Any, *, cik: str, accession: str, ends: list[str]
) -> tuple[Any, dict[str, dict[str, float]]]:
    """The filing's three linkbases, and the figures it tagged for the dates we hold.

    One errand in two requests: the linkbases say what the subtotals are made of and what
    the filer calls each line, and the companyfacts payload says what each of those
    concepts was tagged at. The second is against the payload the xbrl job already
    fetched today, so it is a cache hit in the ordinary case.
    """
    from awltux.ingest import linkbase as linkbases

    read = linkbases.fetch(provider, cik=cik, accession=accession)
    if read.calculation is None:
        return read, {}
    figures = linkbases.declared_values(
        provider.get_company_facts(cik),
        linkbases.declared_tags(read.calculation),
        ends=ends,
    )
    return read, figures


@router.post("/accounts/{period_id}/linkbase", include_in_schema=False)
def read_filing_linkbase(period_id: int) -> RedirectResponse:
    """Fetch this filing's own calculation linkbase, and return to the health tab.

    A POST because it is a network call to EDGAR, and because the *page* reads SQLite:
    a GET that fetched would put a provider request on the critical path of a page that
    is normally a database read, and the week-long cache would only hide that.

    The outcome travels as a query parameter, the shape the instrument refresh and the
    story appraisal already use, so the page can say what happened without keeping state.
    """
    from awltux.analysis import linkbase as reconciliation
    from awltux.ingest import linkbase as linkbases
    from awltux.providers.edgar import EdgarProvider, ProviderError

    # Phase one: what the stored period says about which filing to read, and which of the
    # period ends we hold this filing reported. The session is closed before the first
    # request goes out, so no database lock is held across it.
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        accession = reconciliation.accession(period)
        cik = instrument.sec_cik if instrument is not None else None
        ends = [
            row.period_end.isoformat()
            for row in detail["series"]
            if reconciliation.accession(row) == accession
        ]

    if not cik or not accession:
        # A period from a Yahoo snapshot or a model's reading of a document has no filing
        # behind it, and so no linkbase to read.
        outcome = "no-filing"
    else:
        # Phase two: the network, with nothing open.
        try:
            read, figures = _read_filing_arithmetic(
                EdgarProvider(), cik=cik, accession=accession, ends=ends
            )
        except ProviderError as exc:
            logger.warning("linkbase read failed for %s: %s", accession, exc)
            outcome = "failed"
        else:
            # Phase three: store what came back, or record that the filer published none.
            outcome = "read" if read.calculation is not None and read.source else "none-published"
            if outcome == "read":
                with session_scope() as session:
                    linkbases.save(
                        session,
                        accession,
                        read.calculation,
                        source=read.source,
                        cik=cik,
                        values=figures,
                        presentation=read.presentation,
                        labels=read.labels,
                        files=read.files,
                    )

    return RedirectResponse(
        url=f"/accounts/{period_id}/health?linkbase={outcome}#filer-arithmetic",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/accounts/{period_id}/adopt", include_in_schema=False)
def adopt_declared_lines(period_id: int) -> RedirectResponse:
    """Adopt the captions this filing's own arithmetic proves belong to a line.

    The proof is that the declared leaves we do not hold add up to the residual to the
    pound (`analysis/linkbase.py::provable`), which is why this is a decision the code can
    make rather than a person: it is arithmetic, per filing. What it changes is the
    *stored* figures, not the display of them -- the period is re-derived so the balance
    sheet in the database is the complete one the filer describes, and every consumer of
    those figures (markers, sentiment, decisions) sees it.

    A POST, and it re-reads the filing, so it spends one cached EDGAR request.
    """
    from awltux.analysis import linkbase as reconciliation
    from awltux.ingest import linkbase as linkbases

    outcome = "no-filing"
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        stored = linkbases.stored(session, reconciliation.accession(period))
        if instrument is None or not cik or stored is None:
            pass
        else:
            figures = dict(stored.values.get(period.period_end.isoformat()) or {})
            proven = reconciliation.provable(
                period, stored.linkbase, figures=figures, names=dict(stored.labels.names)
            )
            outcome = (
                f"adopted-{adopted_map.record(session, cik, proven)}"
                if proven
                else "nothing-proven"
            )

    if outcome.startswith("adopted-"):
        #  Re-derive, so the adopted captions are in the stored figures rather than only in
        #  the page's arithmetic. This is the one place the mapping takes effect.
        from awltux.ingest.xbrl import sync_xbrl_fundamentals

        with session_scope() as session:
            sync_xbrl_fundamentals(session, tickers=[instrument.t212_ticker])

    return RedirectResponse(
        url=f"/accounts/{period_id}/health?linkbase={outcome}#filer-arithmetic",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/accounts/{period_id}/adopt/forget", include_in_schema=False)
def forget_adopted_lines(period_id: int) -> RedirectResponse:
    """Drop this filer's adopted captions and re-derive, so the figures revert too."""
    from awltux.ingest.xbrl import sync_xbrl_fundamentals

    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        instrument = detail["instrument"]
        if instrument is None or not instrument.sec_cik:
            raise HTTPException(status_code=404, detail="no filer for this period")
        adopted_map.forget(session, instrument.sec_cik)
        sync_xbrl_fundamentals(session, tickers=[instrument.t212_ticker])

    return RedirectResponse(
        url=f"/accounts/{period_id}/health?linkbase=forgotten-adoptions#filer-arithmetic",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/accounts/{period_id}/linkbase/forget", include_in_schema=False)
def forget_filing_linkbase(period_id: int) -> RedirectResponse:
    """Drop the stored linkbase for this filing, so a wrong read is not permanent."""
    from awltux.analysis import linkbase as reconciliation
    from awltux.ingest import linkbase as linkbases

    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        accession = reconciliation.accession(detail["period"])
        linkbases.forget(session, accession)

    return RedirectResponse(
        url=f"/accounts/{period_id}/health?linkbase=forgotten#filer-arithmetic",
        status_code=status.HTTP_303_SEE_OTHER,
    )


# --------------------------------------------------------------------------- #
# Correcting the accounts by hand
# --------------------------------------------------------------------------- #
# The stored figures are what a writer put there -- an XBRL tag, a Yahoo statement, a model's
# reading of a 10-K -- and automated extraction is wrong often enough that a reader who can
# see the mistake has to be able to fix it. What a correction changes is the *stored* figures,
# not the display of them: see `analysis/corrections.py` for why, and for what is recorded so
# that the fix does not destroy the record it contradicts.

#: What each correction outcome says on the page it returns to. The code travels in the URL
#: and the sentence is chosen here, so nothing a reader typed is ever echoed back as page text.
CORRECTION_NOTES: dict[str, str] = {
    "removed": "The line was taken out of these accounts.",
    "removed-filer": "The line was taken out of every period this filer has.",
    "added": "The line was written into these accounts.",
    "forgotten": "The correction was undone; the line is as the filing had it.",
    "rule-forgotten": "The filer-wide removal was undone for every period this filer has.",
    "already-removed": "That line had already been taken out, so nothing changed.",
    "nothing-to-undo": "There was no correction on that line to undo.",
    "no-rule": "There was no filer-wide removal on that line to undo.",
    "no-line": "That is not one of the accounts on this statement, so nothing was changed.",
    "bad-value": "That is not a figure, so nothing was changed.",
}

#: The origins an added figure may carry. Anything else is recorded as typed, because the
#: distinction is "a person read this out of a filing" against "a person entered it", and a
#: value that came from anywhere else has no filing to point at.
CORRECTION_ORIGINS = ("typed", "filing")


def _accounts_detail(session: Any, period_id: int) -> dict[str, Any]:
    """One period's accounts, or a 404. The lookup every accounts route begins with."""
    detail = queries.accounts_detail(session, period_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"no accounts stored as {period_id}")
    return detail


def _correction_tab(statement: str | None) -> str:
    """The tab a correction returns to: the one it was made from, or the first."""
    return statement if statement in ledger.TAB_NAMES else ledger.DEFAULT_STATEMENT


def _correction_redirect(
    period_id: int, statement: str | None, outcome: str
) -> RedirectResponse:
    """Back to the accounts with what happened in the URL, next to the panel it concerns."""
    return RedirectResponse(
        url=f"/accounts/{period_id}/{_correction_tab(statement)}?corrections={outcome}#corrections",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _parse_figure(raw: str) -> float | None:
    """A figure a reader typed, or ``None`` when it is not one.

    Thousands separators and a currency symbol are accepted, because a reader copying a number
    out of a filing brings them along. A number in parentheses is **negative**: that is how a
    filing prints a credit, and reading ``(1,234)`` as a positive figure would put a wrong
    number on the balance sheet with nothing to complain about.
    """
    text = re.sub(r"^[$£€¥]", "", (raw or "").strip())
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace(",", "").replace("\u00a0", "").replace(" ", "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def _line_choices(which: str) -> list[dict[str, Any]]:
    """The chart's lines for one statement, grouped by the section that prints them.

    This is the picker a reader gets when adding a line. The headings are the statement's own,
    so the question the form asks is "which heading does this figure belong under" rather than
    one that needs the project's metric vocabulary to answer.
    """
    groups: dict[str, list[ledger.Account]] = {}
    for account in ledger.CHART:
        if account.statement == which:
            groups.setdefault(account.section, []).append(account)
    return [{"section": title, "lines": lines} for title, lines in groups.items()]


@router.get(
    "/accounts/{period_id}/corrections/new",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def corrections_form(
    request: Request,
    period_id: int,
    remove: str | None = None,
    section: str | None = None,
    metric: str | None = None,
    value: str = "",
    tag: str = "",
    url: str = "",
    statement: str = ledger.DEFAULT_STATEMENT,
) -> HTMLResponse:
    """The page that confirms a correction before it is made.

    A page of its own rather than a form posted straight from the ledger, because each
    correction has to decide something the line itself cannot say: a removal needs to know
    whether it applies to this period or to every period the filer has, and an addition needs
    a figure and a side. Keeping it out of the ledger also keeps that table a statement of the
    accounts rather than a form.

    It is not a dialog *inside* the filing, either: the filing is served sandboxed, so a form
    rendered in it could not post back here at all.

    ``metric``, ``value``, ``tag`` and ``url`` prefill the form, which is how a figure read out
    of the filing arrives here: the picker on the filing page cannot make the correction itself,
    because it runs on an opaque origin with nothing but its own document -- so it hands the
    reader to this page with what they clicked, and the decision is still made here.
    """
    tab = _correction_tab(statement)
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        record = corrections_rules.load_period(period)
        rules = corrections_rules.load_filer(session, cik)
        metrics = period.metrics or {}
        if remove is not None and remove not in ledger.BY_KEY:
            raise HTTPException(status_code=404, detail=f"no line {remove!r}")
        target = None
        if remove is not None:
            entry = (period.metric_sources or {}).get(remove) or {}
            target = {
                "account": ledger.BY_KEY[remove],
                "value": metrics_module.value_of(metrics, remove),
                "tag": entry.get("span") or "",
                "accession": entry.get("accession") or "",
                # A line a filer-wide rule already removes is not something this period's own
                # page can put back: its undo is the rule's, and the form says so.
                "filer_rule": remove in rules.removed,
                "removed": remove in record.removed or remove in rules.removed,
            }
        context = {
            "period": period,
            "instrument": instrument,
            "cik": cik,
            "statement": tab,
            "mode": "remove" if target else "add",
            "target": target,
            "section": section or "",
            "groups": _line_choices(tab),
            "held": set(metrics),
            "sides": corrections_rules.SIDES,
            # A line named by the picker is chosen outright; otherwise the section the reader
            # pressed "add a line" beside decides which line the form opens on.
            "chosen": metric if metric in ledger.BY_KEY else "",
            "value": value,
            "tag": tag,
            "url": url,
        }
    return templates.TemplateResponse(request, "corrections.html", context)


@router.post("/accounts/{period_id}/corrections/remove", include_in_schema=False)
def remove_corrected_line(
    period_id: int,
    metric: str = Form(...),
    statement: str = Form(ledger.DEFAULT_STATEMENT),
    reason: str = Form(""),
    scope: str = Form("period"),
) -> RedirectResponse:
    """Take a line out of the accounts, for this period or for every period the filer has.

    A removal is written through into the stored figures, so every reader of them sees the
    corrected accounts and not only this page -- the modules from the ledger upwards.
    """
    if metric not in ledger.BY_KEY:
        return _correction_redirect(period_id, statement, "no-line")
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        rules = corrections_rules.load_filer(session, cik)
        record = corrections_rules.load_period(period)
        # A filer-wide scope needs a filer to record it against; without one the correction is
        # still made, for this period only, rather than dropped on the floor.
        filer_wide = scope == "filer" and bool(cik)
        if metric in record.removed or metric in rules.removed:
            outcome = "already-removed"
        else:
            corrections_rules.remove(
                period,
                metric,
                reason=reason,
                scope="filer" if filer_wide else "period",
                rules=rules,
            )
            if filer_wide:
                corrections_rules.save_filer(session, cik, rules)
                # The other periods of this filer read their own rows, so the rule has to reach
                # them now rather than at each one's next sync -- otherwise two periods of the
                # same company would disagree on screen about the same line.
                corrections_rules.reapply_filer(session, cik, rules)
            outcome = "removed-filer" if filer_wide else "removed"
    return _correction_redirect(period_id, statement, outcome)


@router.post("/accounts/{period_id}/corrections/add", include_in_schema=False)
def add_corrected_line(
    period_id: int,
    metric: str = Form(...),
    value: str = Form(""),
    side: str = Form(corrections_rules.CREDIT),
    statement: str = Form(ledger.DEFAULT_STATEMENT),
    tag: str = Form(""),
    url: str = Form(""),
    note: str = Form(""),
    origin: str = Form("typed"),
) -> RedirectResponse:
    """Put a figure on a line by hand, on this period's row and no other.

    A figure belongs to the period it was stated for, so unlike a removal this cannot be
    carried to the filer's other periods; see the module docstring of `analysis/corrections.py`.
    """
    figure = _parse_figure(value)
    if metric not in ledger.BY_KEY:
        return _correction_redirect(period_id, statement, "no-line")
    if figure is None:
        return _correction_redirect(period_id, statement, "bad-value")
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        rules = corrections_rules.load_filer(session, cik)
        corrections_rules.add(
            period,
            metric,
            value=figure,
            side=side,
            tag=tag.strip(),
            url=url.strip(),
            note=note.strip(),
            origin=origin if origin in CORRECTION_ORIGINS else "typed",
            rules=rules,
        )
    return _correction_redirect(period_id, statement, "added")


@router.post("/accounts/{period_id}/filer-rules/forget", include_in_schema=False)
def forget_correction_rule(
    period_id: int,
    metric: str = Form(...),
    statement: str = Form(ledger.DEFAULT_STATEMENT),
) -> RedirectResponse:
    """Undo a removal that was made for every period the filer has.

    Its own route rather than a flag on the line's undo, because it is a different act: the
    line comes back in every period this filer filed, not only the one on screen. The figure
    is restored from each row's own evidence -- the rule took a *different* figure out of each
    period, so only that period can say what it was.
    """
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        filer = detail["instrument"]
        cik = filer.sec_cik if filer is not None else None
        if not cik:
            return _correction_redirect(period_id, statement, "no-rule")
        rules = corrections_rules.load_filer(session, cik)
        if not corrections_rules.forget_rule(rules, metric):
            return _correction_redirect(period_id, statement, "no-rule")
        corrections_rules.save_filer(session, cik, rules)
        corrections_rules.reapply_filer(session, cik, rules, restoring=metric)
    return _correction_redirect(period_id, statement, "rule-forgotten")


@router.post(
    "/accounts/{period_id}/corrections/{metric}/forget", include_in_schema=False
)
def forget_corrected_line(
    period_id: int,
    metric: str,
    statement: str = Form(ledger.DEFAULT_STATEMENT),
) -> RedirectResponse:
    """Undo this period's own correction to a line, and put back what it displaced."""
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        rules = corrections_rules.load_filer(session, cik)
        outcome = (
            "forgotten"
            if corrections_rules.forget(period, metric, rules=rules)
            else "nothing-to-undo"
        )
    return _correction_redirect(period_id, statement, outcome)


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
    """The eleven coarse sectors, plus the unclassified bucket, with counts.

    Keyed on ``sector_group`` and not on the SIC industry string. The *sentiment* series
    is still recorded against the industry string by the older jobs, so it is matched in
    where it can be -- but the index lists the eleven, because those are the sectors that
    have pages, that news can be captured for, and that a reader recognises.
    """
    with session_scope() as session:
        counts = dict(queries.sector_group_counts(session))
        series = queries.sector_sentiment(session, days=60)

    latest = {name: points[-1] if points else None for name, points in series.items()}
    rows = [
        {
            "name": name,
            "count": counts.get(name, 0),
            "latest": latest.get(name),
        }
        for name in sector_map.SECTOR_NAMES
    ]
    # Sorted by instrument count: the empty corners of the taxonomy fall to the bottom,
    # which is where a reader who wants a sector with something in it will look. Ties
    # keep the classification's own order, so the page does not reshuffle between loads.
    rows.sort(key=lambda row: -row["count"])
    return templates.TemplateResponse(
        request,
        "sectors.html",
        {
            "sectors": rows,
            "unclassified": {
                "name": sector_map.UNCLASSIFIED,
                "count": counts.get(None, 0),
            },
            "total_instruments": sum(counts.values()),
        },
    )


@router.get("/sectors/{name}", response_class=HTMLResponse, include_in_schema=False)
def sector_page(request: Request, name: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """One sector: its instruments, its news, and its sentiment.

    This is the sector's page rather than a filtered view of the recommendations table,
    which is what the old link was. The table is the same template either way --
    `partials/recommendations.html` is included here with `list_base` set to this page --
    so sorting and paging behave identically and a click on a column heading re-sorts the
    sector instead of dropping the reader into the whole universe.

    An unknown name is a 404 rather than an empty page: "no such sector" and "a sector
    with nothing in it" are different answers, and the second is already reachable
    through the unclassified bucket.
    """
    if not sector_map.is_sector_page(name):
        raise HTTPException(status_code=404, detail="no such sector")

    per_page = 50
    with session_scope() as session:
        counts = dict(queries.sector_group_counts(session))
        rows, total = queries.recommendations(
            session,
            sector_group=name,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        news = queries.sector_news(session, name)
        series = queries.sector_sentiment_series(session, name, days=60)
        index = queries.sector_price_index(session, name)
        index_basis = queries.sector_index_basis(session, name)
        size = queries.universe_size(session)
        deep_dives = queries.research_reports(session, subject_type="sector", subject_id=name)

    pages = max(1, -(-total // per_page))
    return templates.TemplateResponse(
        request,
        "sector.html",
        {
            "name": name,
            "rows": rows,
            "total": total,
            "page": min(page, pages),
            "pages": pages,
            "per_page": per_page,
            "filters": filters.FilterSet.parse(filters.recommendation_specs(), {}),
            "universe_size": size,
            "list_base": f"/sectors/{quote(name, safe='')}",
            "news": news,
            "series": series,
            "index": index,
            "index_basis": index_basis,
            "latest": series[-1] if series else None,
            "instrument_count": counts.get(name if name != sector_map.UNCLASSIFIED else None, 0),
            "is_unclassified": name == sector_map.UNCLASSIFIED,
            # The deep-dive block and the executive summary, the same partial the instrument
            # page uses. A sector's evidence is the news corpus alone, which the block says.
            **deep_dives,
            "subject_type": "sector",
            "subject_label": f"the {name} sector" if name != sector_map.UNCLASSIFIED else name,
            "research_action": f"/sectors/{quote(name, safe='')}/research",
            "research_prompt_url": f"/sectors/{quote(name, safe='')}/research/prompt",
            "research_base": f"/sectors/{quote(name, safe='')}#research",
            "research_job": research_service.RESEARCH_JOB,
            "research_message": request.query_params.get("research"),
            "research_reason": request.query_params.get("why"),
        },
    )


def _lease_rows(session) -> list[tuple[Any, Any, str]]:
    """Every refresh lease as ``(taken at, released at, ticker)``.

    Read in one query for a whole page of runs: the rule that matches a run to its lease is
    in `_target_of`, and it needs them all to pick the right one.
    """
    from awltux.db import InstrumentRefresh

    return [
        (as_utc(row.started_at), as_utc(row.finished_at), row.instrument_t212_ticker)
        for row in session.execute(select(InstrumentRefresh)).scalars()
        if row.instrument_t212_ticker
    ]


def _target_of(run, leases: list[tuple[Any, Any, str]]) -> str | None:
    """The instrument a refresh run was about, or ``None``.

    The run states its target when it starts (`JobSpec.target`), and that answers it for
    every run recorded since -- including one that failed, since a failure returns no result
    at all. A run recorded before that existed has none, so the *lease* is the fallback: the
    one whose window contains the moment this run started.

    **Containment, not nearness**, which is what makes the fallback exact rather than a guess:
    the refresh takes the lease before its run row is written and gives it up after the row's
    work ends, so a run's own lease always brackets its start, while an earlier attempt of the
    same instrument has been overwritten into a later window. Measured on the live rows,
    2026-10-08: run 797 started 11:38:40.837 and its lease spans 11:38:40.834 to 11:40:24.185.

    A run that no lease window contains gets ``None`` rather than the nearest one. All three
    refresh runs in the history predate the target, and one of them -- interrupted -- has no
    lease left to identify it; naming a company from an approximate match would be a wrong
    holding on a page about a company, which is worse than saying nothing.
    """
    detail = (run.detail or {}) if run is not None else {}
    target = detail.get("target")
    if isinstance(target, str) and target:
        return target

    started = as_utc(run.started_at) if run is not None else None
    if started is None:
        return None
    holding = [
        (taken, ticker)
        for taken, released, ticker in leases
        if taken is not None
        and taken <= started
        and (released is None or released >= started)
    ]
    return max(holding)[1] if holding else None


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
        # What the run is about, when it is about one instrument. A scoped refresh writes
        # every company's log to the *same* file under the same job id, so the page cannot
        # know from the job id which one it is showing -- and its back link went to
        # Operations, which is the wrong place to return to after pressing Refresh on an
        # instrument. Read while the session is open, like the run itself.
        target = _target_of(run, _lease_rows(session)) if job_id == scoped.REFRESH_JOB else None

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
            "target": target,
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
        # Which instrument each of these runs was about, for the refresh runs that are older
        # than `JobSpec.target`. One read of the leases for the whole page, not one per row.
        leases = _lease_rows(session)
        run_targets = {run.id: _target_of(run, leases) for run in runs}

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
            "run_targets": run_targets,
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


def _header_safe(value: str) -> str:
    """A header value that cannot break the response.

    HTTP headers are latin-1 on the wire, and a report's title carries an em dash by
    construction ("TEST_US_EQ — 9 Oct 2026"). Passing that through raised
    ``UnicodeEncodeError: 'latin-1' codec can't encode character '\\u2014'`` while the
    response was being sent -- **after** the body had been written, so it surfaced as a 500
    on every report rather than as a wrong header.

    A filing title has the same exposure: EDGAR carries accents ("Société Générale"), so the
    document route had the same latent fault and never met it because the stored titles
    happen to be ASCII.

    The header is informational and nothing reads it programmatically, so anything outside
    ASCII is replaced rather than encoded. Nothing is truncated by this: the caller's own
    length limit still applies.
    """
    return value.encode("ascii", "replace").decode("ascii")


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
            "X-Document": _header_safe(title[:120]),
        },
    )


@router.get("/research/{report_id}", include_in_schema=False)
def research_report_document(report_id: int) -> Response:
    """Serve one deep-dive research report so it can be read.

    **Sandboxed for the same reason a filing is, and one more.** A filing is third-party HTML
    served from this application's own origin, and this is model-written HTML served from the
    same origin -- an origin that can reach the API and therefore the account. The reporting
    path escapes every field it renders, so this is belt and braces; it is fitted anyway
    because the day someone adds a `|safe` is the day the sandbox is the only thing left.

    The path is re-resolved against the data directory before it is opened. It comes from our
    own database, but a stored path is still a path, and a route that joins one to a root
    without checking is how a traversal arrives.
    """
    settings = get_settings()
    with session_scope() as session:
        row = session.get(ResearchReport, report_id)
        if row is None or not row.raw_path:
            raise HTTPException(
                status_code=404,
                detail=f"no stored report for {report_id}",
            )
        raw_path = row.raw_path
        title = row.title or f"research {report_id}"

    data_dir = settings.data_dir.resolve()
    path = (data_dir / raw_path).resolve()
    if not path.is_relative_to(data_dir) or not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"stored report {report_id} is missing"
        )

    return Response(
        content=path.read_bytes(),
        media_type="application/xhtml+xml",
        headers={
            "Content-Security-Policy": "sandbox",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'inline; filename="{report_id}.xhtml"',
            # A report is immutable once written -- editing one is a new run with a new row --
            # so it is worth caching, the same reasoning `filing_document` records.
            "Cache-Control": "private, max-age=86400",
            "X-Document": _header_safe(title[:120]),
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
