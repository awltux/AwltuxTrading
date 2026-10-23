"""Dashboard pages (server-rendered HTML).

Sorting and filtering are done server-side and driven by query parameters, so
the table works without JavaScript and every view is a shareable URL. Live
updates (the news ticker) are the only thing that requires JS.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
from typing import Any, Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import desc, select

from awltux import __version__, version
from awltux import metrics as metrics_module
from awltux.analysis import adopted as adopted_map
from awltux.analysis import corrections as corrections_rules
from awltux.analysis import ledger
from awltux.analysis import levers as lever_map
from awltux.analysis import sectors as sector_map
from awltux.analysis.fundamental import build_snapshot
from awltux.audit.calibration import HORIZON_WINDOWS, calibration_report
from awltux.buildinfo import DEFAULT_COMMIT_COUNT, load_build_info
from awltux.config import get_settings
from awltux.db import Filing, IngestRun, Instrument, ResearchReport, session_scope
from awltux.ingest import lease, universe
from awltux.ingest.universe import cached_t212_capabilities
from awltux.research import report as research_report
from awltux.research import service as research_service
from awltux.scheduler import scoped
from awltux.timezones import as_utc
from awltux.web import configuration, filters, listing, queries, sources
from awltux.web.routes.research import launch as launch_research
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
    # The outcome of "add to the universe" for a ticker this database does not hold, which is
    # the one case that lands back here rather than on the instrument page.
    context["added"] = request.query_params.get("added")
    # And of a removal, which lands here because the instrument it was about is no longer in
    # the universe the page describes.
    context["removed"] = request.query_params.get("removed")
    context["deleted"] = request.query_params.get("deleted")
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
        # What Trading 212 lists under this search and the universe does not hold. Read here
        # rather than in the page context so the *region* keeps it: a page change fetches
        # only the region, and an "add this one" block that vanished on page two would read
        # as a result set that had changed. Free when there is no search term.
        outside = queries.candidates_outside_universe(session, spec.opt("q") or "")

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": max((total + per_page - 1) // per_page, 1),
        "per_page": per_page,
        "filters": spec,
        "universe_size": size,
        "outside": outside,
    }


def _price_chart(
    session, ticker: str, detail: dict[str, Any], *, window: dt.timedelta | None = None
) -> dict[str, Any]:
    """The price panel's facts: the bars, the reader's fills on them, what the model thinks
    they are worth, how much history is held, and what the panel is waiting for.

    One helper because they are one panel and three of them derive from the first -- the
    markers and the valuation steps are placed on the very bars that are plotted, so the
    chart and the tables below cannot describe different date windows. The waiting
    sentence is computed here rather than in the template because reaching it is four
    different reads.

    ``window`` narrows the bars the chart draws, and everything placed on them with it. The
    **stored count does not follow it**: that number is a fact about the instrument, and it
    is what tells the reader the window is a window.
    """
    history = queries.price_history(session, ticker, window=window)
    return {
        "history": history,
        "markers": queries.price_markers(history, detail["trades"], detail["instrument"]),
        "valuations": queries.price_valuations(session, ticker, history),
        "stored_bars": queries.price_bar_count(session, ticker),
        "waiting_note": queries.price_history_waiting_note(
            session, ticker, bars=len(history)
        ),
    }


def _price_window(
    ticker: str, requested: str | None
) -> tuple[str, dt.timedelta | None, list[dict[str, object]], str | None]:
    """Resolve the chart's window: the name, the age it means, its buttons, any refusal.

    Kept beside :func:`_instrument_tab` because it is the same shape of decision -- a view
    selector that lives in the query string, whose buttons are real links and whose
    unusable value is reported rather than 404ed. The windows themselves are declared in
    `web/filters.py`, next to the news listing's, so the two vocabularies for "how far
    back" sit together.
    """
    name, age, ignored = filters.price_window(requested)
    base = f"/instrument/{quote(ticker, safe='')}?tab=price"
    buttons = [
        {
            "name": candidate,
            "label": filters.PRICE_WINDOW_LABELS[candidate],
            # The default is omitted from its own link, so the commonest address stays
            # short and a link carries only what the reader chose.
            "url": base
            if candidate == filters.PRICE_WINDOW_DEFAULT
            else f"{base}&window={candidate}",
            "active": candidate == name,
        }
        for candidate in filters.PRICE_WINDOW_AGES
    ]
    return name, age, buttons, ignored


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
    # What moves the business. Its own tab from 2026-10-23 (asked for directly), because it is a
    # list of records that grows, not a summary: it sat under the business description above the
    # tabs and so appeared on every visit to every tab. Next to Research because both are about
    # the business rather than about a number.
    ("levers", "Levers"),
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
    detail: dict[str, Any], history: list[dict[str, Any]], *, stored: int
) -> dict[str, Any]:
    """The handful of figures the top of the page shows on every tab.

    **Deliberately small.** The detail is one click away and repeating it here would rebuild
    the long page this replaced. What belongs at the top is what a reader needs in order to
    decide *which* tab to open: what it is, what it costs and which way it moved, what the
    engine says on each horizon, and how stale any of that is.

    The price comes from the same `history` the chart draws, so the number in the summary
    and the last point of the line cannot disagree -- they are one query.

    ``stored`` is the exception, and it is passed in rather than derived: the details panel
    reports how many bars are *held*, which is not how many the chart is drawing once a
    window is selected. Reading that number off `history` would have made it shrink with
    the window, and "Price bars: 21" reads as "this is all we have".
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
        "stored_bars": stored,
    }


def _lever_context(detail: dict[str, Any], request: Request) -> dict[str, Any]:
    """The recorded exposures and the vocabulary the form offers -- the Levers tab's block.

    The vocabulary travels with the exposures because the form on that tab is the way a lever
    is recorded: a page that could show a lever but not name one would send the reader to a
    shell to write one down. The outcome note is looked up here rather than in the template so
    that a code a caller invented prints nothing instead of a raw query parameter.

    **Read only when the Levers tab is rendered.** It moved out of the panel above the tabs on
    2026-10-23, and the description that stayed there does not use any of this -- so the other
    nine tabs would otherwise pay for the query and the vocabulary build to print nothing.
    """
    return {
        "levers": detail["levers"],
        "levers_recorded": detail["levers_recorded"],
        "lever_note": LEVER_NOTES.get(request.query_params.get("levers") or ""),
        "lever_choices": lever_map.LEVERS,
        "lever_groups": lever_map.GROUP_ORDER,
        "lever_group_labels": lever_map.GROUP_LABELS,
        "lever_directions": lever_map.DIRECTIONS,
        "lever_direction_labels": lever_map.DIRECTION_LABELS,
        "lever_strengths": lever_map.STRENGTHS,
        "lever_strength_labels": lever_map.STRENGTH_LABELS,
    }


def _research_links(base: str, *, return_to: str) -> dict[str, Any]:
    """Where the deep-dive block posts, and where it sends the reader back to.

    Shared by the instrument and sector pages, which render the same block over the same two
    routes. Only two things differ, and they are the arguments: the subject's own URL, and how
    *that* page addresses the block -- the instrument page returns to a tab, the sector page to
    a fragment. Stating them twice is how one of them silently loses its anchor.
    """
    return {
        "research_action": f"{base}/research",
        "research_prompt_url": f"{base}/research/prompt",
        "research_base": f"{base}{return_to}",
        "research_job": research_service.RESEARCH_JOB,
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
    removable: str | None,
    active: str,
    strip: list[dict[str, object]],
    tab_ignored: str | None,
    windows: list[dict[str, object]],
    window_ignored: str | None,
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
        # What Trading 212's metadata says about the listing, for the panel the deep-dive's own
        # account sits in. Derived from the row rather than stored -- see `listing.listing_about`
        # for why, and for what that API does and does not know about a company.
        "about": listing.listing_about(detail["instrument"]),
        "summary": _instrument_summary(detail, chart["history"], stored=chart["stored_bars"]),
        "tabs": strip,
        "tab": active,
        "tab_ignored": tab_ignored,
        "decision": detail["decision"],
        "valuation": detail["valuation"],
        "history": chart["history"],
        "markers": chart["markers"],
        "valuations": chart["valuations"],
        "windows": windows,
        "window_ignored": window_ignored,
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
        # Why this instrument cannot be taken out of the universe, or `None` when it can --
        # see `ingest.universe.removable`. Read only for the Refresh tab, which is the one
        # that offers the removal, so every other tab carries `None`.
        "removable": removable,
        # The outcome of the search page's "add to the universe", which lands here because
        # this is the page about the instrument that was added. A code, not a sentence: a
        # caller that invents one prints nothing rather than a raw query parameter.
        "added_message": request.query_params.get("added"),
        # The deep-dive block, and the latest report's executive summary at the top of every
        # tab. Both come from one query that is cheap -- a subject has a handful of reports --
        # so it is not gated behind the Research tab the way the news block is.
        **detail["research"],
        # What the business is, in the panel above the tabs: the latest finished deep-dive's own
        # account of it, or the listing's facts when no deep-dive has run.
        "business": detail["business"],
        # What moves it is its own tab now, so the exposures and their vocabulary are read only
        # for that tab -- see `_lever_context`.
        **(_lever_context(detail, request) if active == "levers" else {}),
        "subject_type": "instrument",
        "subject_label": f"{detail['instrument'].name} ({ticker})",
        **_research_links(f"/instrument/{quote(ticker, safe='')}", return_to="?tab=research"),
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
    window: str | None = None,
    news_page: int = Query(1, ge=1),
) -> HTMLResponse:
    """One instrument, summarised at the top and split into tabs below.

    Only the current tab is rendered, and only its sections are read -- see
    ``INSTRUMENT_TAB_SECTIONS``. ``news_page`` is parsed on every request and read on one of
    them: FastAPI validates it before this runs, and a tab that ignored a malformed page
    number silently would be worse than one that refuses it.

    ``window`` is the price chart's date range, read on every tab because the summary strip's
    close comes from the same bars even when the chart is not drawn. Its value is resolved
    rather than validated: an unusable one is reported on the page, exactly as an unusable
    ``tab`` is.
    """
    active, strip, tab_ignored = _instrument_tab(ticker, tab)
    sections = INSTRUMENT_TAB_SECTIONS.get(active, ())
    _, window_age, windows, window_ignored = _price_window(ticker, window)

    # A cache key of only what changes the *body*: the ticker, the tab, the price range and the
    # news page. Any other parameter is a message the page prints (a refresh outcome, an add
    # notice, an ignored value), so a URL carrying one is rendered and never stored -- the
    # alternative is a reader seeing "nothing started" twice.
    cache = getattr(request.app.state, "page_cache", None)
    cacheable = set(request.query_params) <= {"tab", "window", "news_page"}
    key = (ticker, active, window_age, news_page)
    if cache is not None and cacheable:
        hit = cache.get(key)
        if hit is not None:
            return HTMLResponse(hit)

    with session_scope() as session:
        detail = queries.instrument_detail(
            session, ticker, news_page=news_page, sections=sections
        )
        if detail is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument {ticker}")
        chart = _price_chart(session, ticker, detail, window=window_age)
        # The page used to show only the latest decision, so "what did it say last
        # week, and was it right" had no answer anywhere.
        predictions, prediction_count = (
            queries.decision_history(session, ticker=ticker, limit=25)
            if active == "decision"
            else ([], 0)
        )
        # The lease doubles as the refresh's progress: the same row that stops a sweep
        # touching this instrument says which step is running. Read on **every** tab since
        # 2026-10-23: the instrument header offers Refresh everywhere, and a header that said
        # "Refresh now" while a refresh was already running would offer a button the route then
        # refuses. It is one primary-key read, which is why it can move off the Refresh tab.
        refresh_row = lease.current(session, ticker)
        refresh_state = queries.refresh_state(refresh_row)
        # Read only on the tab that offers the removal, and from the one function that decides
        # it -- so the button is never drawn where the POST would refuse.
        removable = universe.removable(session, ticker) if active == "refresh" else None

    context = _instrument_context(
        request,
        ticker=ticker,
        detail=detail,
        chart=chart,
        predictions=predictions,
        prediction_count=prediction_count,
        refresh_state=refresh_state,
        removable=removable,
        active=active,
        strip=strip,
        tab_ignored=tab_ignored,
        windows=windows,
        window_ignored=window_ignored,
    )
    # Rendered here rather than through `TemplateResponse` because the cache stores the body,
    # and a response object is not the thing worth keeping. `TemplateResponse` does exactly this
    # -- inject the request and render -- so the output is the same page.
    page = templates.get_template("instrument.html").render(request=request, **context)
    if cache is not None and cacheable:
        cache.set(key, page)
    return HTMLResponse(page)


@router.post("/instrument/{ticker}/refresh", include_in_schema=False)
def instrument_refresh(
    ticker: str, request: Request, tab: str = Form("refresh")
) -> RedirectResponse:
    """Force the pipeline stages for one instrument, and return immediately.

    A POST rather than a link, and not because of the semantics: a GET would be followed
    by any prefetcher or crawler that happened to see the URL, and this spends provider
    and model budget. The redirect carries the outcome as a query parameter, so the page
    can say why nothing started without keeping state anywhere.

    ``tab`` is where the button was pressed, and the reader goes back there with the outcome
    printed above the tabs (`partials/_refresh_notice.html`). Since 2026-10-23 the instrument
    header offers this button on **every** tab, and sending a reader who pressed it from the
    Decision tab to the Refresh tab would throw away the receipt they were reading. An unknown
    value falls back to the Refresh tab, which is where the progress is.

    The ticker's cached pages go, because a page rendered before the POST would report the
    previous refresh state.
    """
    outcome = scoped.start(ticker)
    reason = "started" if outcome.ok else "refused"
    cache = getattr(request.app.state, "page_cache", None)
    if cache is not None:
        cache.invalidate((ticker,))
    back = tab if tab in INSTRUMENT_TAB_NAMES else "refresh"
    return RedirectResponse(
        url=_instrument_tab_url(ticker, back, refresh=reason),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/instrument/{ticker}/include", include_in_schema=False)
def include_instrument(ticker: str, research: str = Form("")) -> RedirectResponse:
    """Add an instrument Trading 212 lists to the universe this app analyses.

    Asked for directly: *"If there are results, provide an add button on the instrument that
    adds it to the local universe. Add an option to do deep research on it as well."*

    A POST with a 303 back to the instrument page, for the reason
    :func:`instrument_refresh` gives -- a GET would be followed by any prefetcher, and this
    changes what the pipeline analyses. ``research`` is the second button on the same form:
    landing on an instrument with no prices and no filings and being told to press two more
    things is not the option the reader asked for, so that path adds it and starts its first
    deep-dive, which refreshes the instrument before it reads anything.
    """
    with session_scope() as session:
        included = universe.include(session, ticker)
    if not included:
        # Not "no such company": Trading 212's list is synced into this database daily, so a
        # ticker that is absent means the sync predates the listing. The dashboard says so.
        return RedirectResponse(url="/dashboard?added=unknown", status_code=status.HTTP_303_SEE_OTHER)
    if research:
        # The same prompt the Research tab would have offered: a deep-dive is the expensive
        # call, and giving it different wording depending on which button started it would
        # make the two reports incomparable.
        return launch_research(
            "instrument", ticker, research_service.draft_prompt("instrument", ticker) or ""
        )
    return RedirectResponse(
        url=f"/instrument/{quote(ticker, safe='')}?added=1",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get(
    "/instrument/{ticker}/remove", response_class=HTMLResponse, include_in_schema=False
)
def instrument_remove_page(request: Request, ticker: str) -> HTMLResponse:
    """The page that confirms taking an instrument out of the universe.

    Asked for directly: *"existing instruments in the universe can be removed using a red
    confirmation button on the instruments refresh tab. All data held on that instrument will
    be removed once confirmed."*

    A page rather than a second button on the Refresh tab, for the reason `corrections_form`
    gives for being a page: what is about to be destroyed has to be *stated* before it is,
    and a reader who cannot see the size of it cannot decide. The counts come from the same
    list the deletion runs (`ingest.universe.footprint`), so the page cannot promise one
    thing and the delete do another.
    """
    with session_scope() as session:
        row = session.get(Instrument, ticker)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown instrument {ticker}")
        counts = universe.footprint(session, ticker)
        refused = universe.removable(session, ticker)
        name = row.name

    return templates.TemplateResponse(
        request,
        "instrument_remove.html",
        {
            "ticker": ticker,
            "name": name,
            "counts": counts,
            "total": sum(counts.values()),
            "refused": refused,
            # A refusal that arrives with the POST rather than from the page, so the page can
            # say which one it was without keeping state anywhere.
            "why": request.query_params.get("why"),
        },
    )


@router.post("/instrument/{ticker}/remove", include_in_schema=False)
def remove_instrument(ticker: str) -> RedirectResponse:
    """Take an instrument out of the universe and delete what was collected about it.

    A POST, and the guard is re-checked here even though the page already applied it: the
    page is a rendering and this is the act, and a hand-made request must not be able to do
    what the page would not offer.
    """
    with session_scope() as session:
        outcome = universe.remove(session, ticker)

    where = quote(ticker, safe="")
    if "refused" in outcome:
        return RedirectResponse(
            url=f"/instrument/{where}/remove?why={outcome['refused']}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    deleted = sum((outcome.get("removed") or {}).values())
    return RedirectResponse(
        url=f"/dashboard?removed={where}&deleted={deleted}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


#: How many instruments one comparison shows. A comparison of thirty names is a table nobody
#: reads, and the page exists to make ten legible — so the cap is a judgement, and the count of
#: what it dropped is printed rather than the list being silently truncated.
MAX_COMPARE = 12


@router.get("/compare", response_class=HTMLResponse, include_in_schema=False)
def compare_page(request: Request, tickers: str = "") -> HTMLResponse:
    """Several instruments side by side, in one request.

    Asked for as *"multiple windows for 10 or so instruments"*: the way to compare names was ten
    tabs, and ten tabs is what made the interface crawl before the web tier had workers. This is
    the same answer for ten companies in **one** request, built from the same rows the
    recommendations table reads — so the comparison and the table cannot disagree about what the
    engine said, and the numbers carry their own provenance (as-of, engine, confidence).

    ``tickers`` is a comma- or space-separated list, in the order the reader gave it, because the
    order *is* part of the question. A ticker this app does not know is reported rather than
    dropped: a comparison silently missing a name is worse than one that says it could not find
    it.
    """
    wanted, overflow = _compare_set(tickers)
    rows: list[queries.RecommendationRow] = []
    missing: list[str] = []
    if wanted:
        with session_scope() as session:
            found, _ = queries.recommendations(session, tickers=wanted, limit=len(wanted))
        by_ticker = {row.ticker: row for row in found}
        for ticker in wanted:
            row = by_ticker.get(ticker)
            if row is None:
                missing.append(ticker)
            else:
                rows.append(row)

    return templates.TemplateResponse(
        request,
        "compare.html",
        {
            "rows": rows,
            "missing": missing,
            "overflow": overflow,
            "raw": tickers,
            "limit": MAX_COMPARE,
        },
    )


def _compare_set(raw: str) -> tuple[list[str], int]:
    """The tickers a comparison is about, and how many were dropped for being past the cap.

    Pure and separate from the query so the parsing rules are testable on their own: commas or
    whitespace, upper-cased, deduplicated **in the order given**, and capped. The cap is not
    arbitrary — a comparison of thirty names is a table nobody reads, and the page exists to
    make ten legible — so the overflow is *counted* rather than silently truncated.
    """
    seen: list[str] = []
    for part in raw.replace(",", " ").split():
        ticker = part.strip().upper()
        if ticker and ticker not in seen:
            seen.append(ticker)
    return seen[:MAX_COMPARE], max(0, len(seen) - MAX_COMPARE)


@router.post("/instrument/{ticker}/levers", include_in_schema=False)
def add_instrument_lever(
    ticker: str,
    lever: str = Form(...),
    direction: str = Form(lever_map.UNKNOWN),
    strength: str = Form(lever_map.PRIMARY),
    reason: str = Form(""),
    tab: str = Form("decision"),
) -> RedirectResponse:
    """Record one lever against an instrument, replacing any earlier judgement of it.

    A POST with a 303 back to the tab the form was on, for the reason
    :func:`instrument_refresh` gives: the reader stays where they were and the page prints
    what happened.

    **Both halves are validated here and neither is inferred.** An unknown lever key, a
    direction outside the vocabulary or a strength outside it is refused with an outcome the
    page turns into a sentence -- not mapped to the nearest legal value, because the page
    these feed is a claim about what moves a business and nothing downstream would show the
    substitution.
    """
    key = lever_map.resolve(lever)
    if key is None:
        outcome = "unknown-lever"
    elif direction not in lever_map.DIRECTIONS or strength not in lever_map.STRENGTHS:
        outcome = "bad-direction"
    else:
        with session_scope() as session:
            if session.get(Instrument, ticker) is None:
                return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
            lever_map.record(
                session,
                ticker,
                [
                    lever_map.Exposure(
                        lever=key, direction=direction, strength=strength
                    )
                ],
                reason=reason,
            )
        outcome = "lever-recorded"
    return RedirectResponse(
        url=_instrument_tab_url(ticker, tab, levers=outcome),
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/instrument/{ticker}/levers/{key}/forget", include_in_schema=False)
def forget_instrument_lever(
    ticker: str,
    key: str,
    tab: str = Form("decision"),
) -> RedirectResponse:
    """Drop one lever from an instrument.

    Refuses a key the vocabulary does not know rather than reporting a deletion of nothing: a
    link built against a lever that has since been retired should look wrong, not succeed
    silently.
    """
    if not lever_map.is_lever(key):
        outcome = "unknown-lever"
    else:
        with session_scope() as session:
            gone = lever_map.forget(session, ticker, key)
        outcome = "lever-forgotten" if gone else "nothing-to-forget"
    return RedirectResponse(
        url=_instrument_tab_url(ticker, tab, levers=outcome),
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _instrument_tab_url(ticker: str, tab: str, **message: str) -> str:
    """Back to one instrument's tab, with an outcome for the page to print.

    Encoded rather than pasted, because the tab arrives in a form field a caller controls and
    it is going into a URL.
    """
    return f"/instrument/{quote(ticker, safe='')}?{urlencode({'tab': tab or 'decision', **message})}"


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
    # What a reader has changed by hand, whether there is a filer to change it for, and the
    # lines this filer has taught the page -- which the statement has to print and the checks
    # have to count, or adding one would change nothing.
    instrument = detail["instrument"]
    corrections_context = _corrected_accounts(
        session, period, instrument, request.query_params.get("corrections")
    )
    extra = corrections_context.pop("extra")
    # The filing behind these figures, when they are the government's own XBRL and we hold the
    # document: that is what lets the page open it at the line that does not reconcile.
    filing = _filing_target(session, period)
    # Where each source on this page gathered its figures -- the chosen set of accounts and the
    # ones it displaced. Read here because it needs the session: the answer for an XBRL period
    # is a filing row resolved by accession, not a column copied onto the period.
    year = detail["year"]
    origins = sources.origins(
        session,
        instrument,
        [period, *[row.period for row in (year.superseded if year else ())]],
    )

    return templates.TemplateResponse(
        request,
        "accounts.html",
        {
            "period": period,
            "previous": previous,
            "year": year,
            "origins": origins,
            "instrument": instrument,
            "statement": statement,
            "tabs": _account_tabs(period_id, statement),
            "built": (
                ledger.statement(period, statement, declared=declared, extra=extra)
                if statement in ledger.STATEMENT_KINDS
                else None
            ),
            "health": ledger.checks(period, previous, declared=declared, extra=extra),
            **arithmetic,
            "snapshot": snapshot,
            "empty": not metrics,
            "currency": period.currency or "",
            "period_type": period.period_type,
            "source": period.source,
            "metric_sources": (period.metric_sources or {}),
            "filing": filing,
            # Where each printed line sits -- which statement, and which heading on it -- so a
            # residual link tells the picker what the line it came from *is*, and a line created
            # out of a caption in the filing is offered under the heading the reader is in.
            "placements": _placements(period),
            **corrections_context,
        },
    )


def _placements(period: Any) -> dict[str, dict[str, str]]:
    """Every printed line's statement and heading, keyed by metric.

    Asked of the statements themselves rather than read off the chart, because the two do not
    name their headings the same way: the profit and loss chart splits "Finance" and "Tax" where
    the statement prints "Finance and tax". A second table here would be a second table to keep
    true, and the one thing this map exists for -- naming a heading a reader can see -- is
    exactly what the statement builder knows.

    ``declared`` is left out: it changes what a figure *is*, not where a line is printed.
    """
    out: dict[str, dict[str, str]] = {}
    for which in ledger.STATEMENT_KINDS:
        try:
            built = ledger.statement(period, which)
        except KeyError:  # pragma: no cover - STATEMENT_KINDS is the builder list
            continue
        for section in built.sections:
            for line in section.lines:
                out.setdefault(
                    line.key, {"statement": which, "section": section.title}
                )
    return out


def _filing_target(session: Any, period: Any) -> dict[str, Any] | None:
    """The stored filing behind a period the *government's own* XBRL describes.

    Asked for directly: *"if the accounts for a period are based on government xbrl, convert the
    'out by Y' field into links that open the relevant government report in a separate tab e.g.
    10-K for USA"*. Two conditions, and both matter:

    * **The accounts have to come from the filer's own submission.** A residual against a
      Yahoo statement or a model's reading of a document is a residual against a copy, and
      opening the real 10-K beside it would invite the reader to correct our figures from a
      source the page has already decided not to use.
    * **We have to hold the document.** ``raw_path`` is the stored copy; the accession alone
      would mean an EDGAR fetch on the reader's click, which is a provider call this page does
      not make.

    The accession is matched against the Filing row's URL rather than against a column of its
    own, because that is where it is: ``0001193125-26-323660`` is in the path. Matched on the
    dashes-stripped form, since EDGAR's file names carry it as one token.
    """
    from awltux.analysis import collate
    from awltux.analysis import linkbase as reconciliation

    if period.source not in collate.GOVERNMENT_SOURCES:
        return None
    accession = reconciliation.accession(period)
    if not accession:
        return None
    row = session.execute(
        select(Filing)
        .where(Filing.instrument_t212_ticker == period.instrument_t212_ticker)
        .where(Filing.raw_path.is_not(None))
        .where(Filing.url.like(f"%{accession.replace('-', '')}%"))
        .order_by(desc(Filing.filed_at))
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "id": row.id,
        "type": row.filing_type or "filing",
        "url": row.url or "",        # The coordinates travel in the picker's own query string, so its script has nothing to
        # decide: which period and which line are fixed by the link the reader pressed. The
        # period *end* goes with them because a filing prints the current year and the prior year
        # in one row under one caption, both tagged, and the script marks a figure clicked out of
        # the wrong column rather than letting it be written in.
        #
        # **The statement and the heading are per link**, appended by the template from
        # `placements`: a residual on the health tab audits a line that is printed on a statement
        # of its own, and a duplicate `awltux_statement` here would be read by `URLSearchParams`
        # as the *first* one -- which is this one, the tab the reader happens to be on.
        "pick": (
            f"/filing/{row.id}/pick"
            f"?awltux_period={period.id}"
            f"&awltux_period_end={period.period_end.isoformat()}"
        ),
        "document": f"/filing/{row.id}/document",
    }


def _account_tabs(period_id: int, statement: str) -> list[dict[str, Any]]:
    """The tab strip: one real URL per statement, so each can be linked to and bookmarked."""
    return [
        {
            "name": name,
            "label": label,
            "url": f"/accounts/{period_id}/{name}",
            "active": name == statement,
        }
        for name, label in ledger.TABS
    ]


def _corrected_accounts(
    session: Any, period: Any, instrument: Any, outcome: str | None
) -> dict[str, Any]:
    """What a reader has changed about this period, ready for the page's context.

    A named step rather than lines in the route, because it is the one part of the accounts page
    that is about *this project* rather than about the filing: everything above it is the filer's
    own arithmetic, and this is the record of where a person disagreed with it.

    ``extra`` comes back with the rest because the ledger needs it as *accounts* rather than as
    records -- a line the filer names is printed in its section and counted in that section's
    subtotal -- and the caller hands it straight on. It is popped out of the context by the
    caller, because no template needs it.
    """
    cik = instrument.sec_cik if instrument is not None else None
    rules = corrections_rules.load_filer(session, cik)
    offerable, superseded = _learned_lines(rules, period)
    return {
        "corrections": corrections_rules.corrections_for(period, rules),
        "correction_note": CORRECTION_NOTES.get(outcome or ""),
        # Offered only where there is a filer to offer it for: a removal recorded against a CIK
        # that this period does not have would have nothing to apply to.
        "cik": cik,
        "learned_lines": [line.as_dict() | {"metric": line.metric} for line in offerable],
        "superseded_lines": [line.as_dict() | {"metric": line.metric} for line in superseded],
        "extra": [_account_for(line) for line in offerable],
    }


def _learned_lines(rules: Any, period: Any) -> tuple[list[Any], list[Any]]:
    """A filer's learned lines, split into the ones to offer and the ones the chart has caught up.

    ``TAG_MAP`` grows: a caption that had no line when a reader taught the page one may be carried
    by the chart now. Where that has happened *and* the chart's line holds a figure, the learned
    line is the same money again -- the extractor filled the chart's line from the payload while
    the reader's figure still sits under the tag -- so it is no longer printed, no longer counted,
    and reported rather than dropped in silence.

    Where the chart's line holds *nothing*, the learned line keeps its place: nothing else is
    holding that figure, and hiding it would lose the one set of accounts that has it.
    """
    chart = {}
    for line in getattr(rules, "lines", {}).values():
        mapped = _metric_for_tag(line.tag or line.metric, period)
        # Only a mapping to a *different* line counts as the chart catching up. A learned line's
        # metric *is* its tag and its own provenance records that tag as the span, so the period's
        # own evidence names the line itself -- which would make every learned line supersede
        # itself the moment a figure was put on it.
        chart[line.metric] = mapped if mapped and mapped != line.metric else ""
    held = set((period.metrics or {}).keys())
    offerable = [
        line for line in rules.lines.values() if not (chart[line.metric] and chart[line.metric] in held)
    ]
    superseded = [line for line in rules.lines.values() if line not in offerable]
    return offerable, superseded


def _account_for(line: Any) -> Any:
    """A learned line as one of the ledger's accounts, so it prints like any other.

    `Account` already carries exactly what a line needs to be laid out -- key, label, statement,
    section, side -- so a filer's own caption travels through the same path the chart's do rather
    than through a parallel one that would eventually disagree about a heading's name.
    """
    return ledger.Account(
        key=line.metric,
        label=line.label,
        statement=line.statement,
        section=line.section,
        side=line.side,
    )


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
    "added-line": (
        "The line was written into these accounts, and the filer's own heading for it will be "
        "offered under the same section in every other period this company filed."
    ),
    "forgotten": "The correction was undone; the line is as the filing had it.",
    "rule-forgotten": "The filer-wide removal was undone for every period this filer has.",
    "line-forgotten": (
        "The heading is no longer offered for this company. Any figure already put on it stays "
        "on the period it was written to."
    ),
    "already-removed": "That line had already been taken out, so nothing changed.",
    "nothing-to-undo": "There was no correction on that line to undo.",
    "no-rule": "There was no filer-wide removal on that line to undo.",
    "no-line": "That is not one of the accounts on this statement, so nothing was changed.",
    "no-section": (
        "That is not a heading this statement prints, and a line under no heading is a line "
        "nothing shows, so nothing was changed."
    ),
    "no-filer": (
        "A line belongs to the company that filed it and this period has no filer recorded, so "
        "nothing was changed."
    ),
    "bad-value": "That is not a figure, so nothing was changed.",
}

# The levers a business is exposed to, recorded by hand for now. `analysis/levers.py` owns the
# vocabulary and the direction convention; what a lever is *for* is the cross-instrument
# question the `/levers` pages answer, and that is why the key is one of a fixed list rather
# than free text.
#
# Nothing fills these from the model yet. The deep-dive already reads the whole company, so the
# block that would ride on it costs output tokens on a call that is made anyway rather than a
# call of its own -- but the mechanism came first, and `TODO.md` carries the prompt change and
# the shape to read when it is wanted.

#: What each lever outcome says on the page it returns to. The code travels in the URL and the
#: sentence is chosen here, so nothing a reader typed is ever echoed back as page text.
LEVER_NOTES: dict[str, str] = {
    "lever-recorded": (
        "The lever was recorded. It now appears on this page and under /levers, where the "
        "instruments exposed to it are listed."
    ),
    "lever-forgotten": "The lever was removed from this instrument.",
    "nothing-to-forget": "That lever was not recorded on this instrument, so nothing changed.",
    "unknown-lever": (
        "That is not one of the levers in the vocabulary, so nothing was recorded. The list is "
        "on /levers -- a lever outside it would not be found by the query this feature exists "
        "for."
    ),
    "bad-direction": (
        "The direction or the strength was not one of the allowed values, so nothing was "
        "recorded."
    ),
}

#: How the form says "this is a line to create, not one to choose". The option's value carries
#: the taxonomy tag, because the tag is the line's identity: it is what the filing calls the
#: caption, and what next year's filing will call it again.
NEW_LINE_PREFIX = "new:"

#: The origins an added figure may carry. Anything else is recorded as typed, because the
#: distinction is "a person read this out of a filing" against "a person entered it", and a
#: value that came from anywhere else has no filing to point at.
#:
#: ``table`` is a figure clicked out of a filing whose tables carry no `ix:` elements, so there
#: is no tag to point at either -- the reader read it off the page, and the record says which of
#: the two that was. Kept apart from ``filing`` because the tag column is empty for one of them
#: and a reader comparing two corrections deserves to know which.
CORRECTION_ORIGINS = ("typed", "filing", "table")


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
    note: str = "",
    caption: str = "",
    origin: str = "typed",
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

    ``caption`` is the filing's own header for the line the figure sat under. Where it names
    something this project's chart does not carry -- *"I've already found entries in the 10-K that
    aren't in the pre-defined entries"* -- the form offers it as a **line to create**, with the
    heading the reader is working in, and the addition teaches that line to the filer for its
    later periods.

    **Whether the side is asked depends on the line.** Which way a figure moves the total is
    decided by the *line*: the chart's own lines are posted on the side the chart gives them, and
    the ledger sums them with that weight whatever the form says, so a line the chart carries
    shows its side rather than offering a choice that would be ignored. For a line created from
    the filing's caption nothing else knows, so the reader is asked.
    """
    tab = _correction_tab(statement)
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        record = corrections_rules.load_period(period)
        rules = corrections_rules.load_filer(session, cik)
        metrics = period.metrics or {}
        target = _removal_target(period, remove, record, rules)
        groups = _line_choices(tab)
        learned = [line for line in rules.lines.values() if line.statement == tab]
        # The headings this statement *prints*, asked of the statement rather than of the chart:
        # the chart splits "Finance" and "Tax" where the statement prints "Finance and tax", and a
        # line learned under a heading nobody prints is a line nothing shows.
        headings = _printed_headings(period, tab)
        mapped = _metric_for_tag(tag, period)
        new_line = _offered_line(
            caption, tag, section=section, headings=headings, known=learned, mapped=mapped
        )
        chosen = _preselected(mapped=mapped, tag=tag, learned=learned, new_line=new_line, metric=metric)
        # Nothing to go on -- the reader pressed *add a line* on a heading -- so the form opens on
        # the first line of that heading. Decided **here** rather than in the template, where it
        # used to be: which line is being edited is what decides whether the side is asked for, and
        # one rule in two places is how a form and the record it posts come to disagree.
        if not chosen:
            chosen = _default_line(groups, section)
        context = {
            "period": period,
            "instrument": instrument,
            "cik": cik,
            "statement": tab,
            "mode": "remove" if target else "add",
            "target": target,
            "section": section or "",
            "groups": groups,
            "learned": learned,
            "new_line": new_line,
            "sections": headings,
            # Said when the preselect is not the line the reader arrived from, so a dropdown that
            # quietly moved is explained rather than trusted.
            "moved_from": (
                _label_for(metric) if chosen and metric in ledger.BY_KEY and metric != chosen else ""
            ),
            "held": set(metrics),
            "sides": corrections_rules.SIDES,
            # A line the chart carries has its side already, and the ledger posts it there
            # whatever the form says -- so the form stops asking. Empty for a line to create,
            # which is the one case the reader has to decide.
            "fixed_side": (
                ""
                if chosen.startswith(NEW_LINE_PREFIX) or chosen not in ledger.BY_KEY
                else ledger.BY_KEY[chosen].side
            ),
            "chosen": chosen,
            "value": value,
            "tag": tag,
            "url": url,
            # The picker fills this with the filing's own caption for the line -- "filed as:
            # Property and equipment, net" -- so the record says where the figure was read from
            # in the filer's words rather than in a taxonomy's.
            "note": note,
            "caption": caption,
            "origin": origin if origin in CORRECTION_ORIGINS else "typed",
        }
    return templates.TemplateResponse(request, "corrections.html", context)


def _printed_headings(period: Any, statement: str) -> list[str]:
    """The headings a statement prints, in order, or none for a tab that prints no statement.

    Asked of the statement builder rather than of the chart, which names its sections
    differently in two places. A line learned under a heading nobody prints is a line nothing
    shows, so this is the list both the offer and the validation are made against.
    """
    if statement not in ledger.STATEMENT_KINDS:
        return []
    return [section.title for section in ledger.statement(period, statement).sections]


def _offered_line(
    caption: str,
    tag: str,
    *,
    section: str | None,
    headings: list[str],
    known: list[Any],
    mapped: str,
) -> dict[str, Any] | None:
    """The filing's own header as a line to create, or nothing when it is not worth offering.

    Offered only when it is genuinely not one of ours: a tag that already feeds a chart line has
    a figure of its own, and a second line for one caption is two figures that will disagree the
    first time one of them is corrected. A line that has already been learned is offered as
    itself, so there is nothing to create.
    """
    if not caption or not tag or mapped or tag in {line.metric for line in known}:
        return None
    return {
        "tag": tag,
        "caption": caption,
        # The heading the reader is working in, when the picker handed one over -- the heading
        # the line they came from is printed under, so a new line lands beside its neighbours.
        "section": section if section in headings else (headings[0] if headings else ""),
    }


def _preselected(
    *,
    mapped: str,
    tag: str,
    learned: list[Any],
    new_line: dict[str, Any] | None,
    metric: str | None,
) -> str:
    """Which option the form opens on, decided from the figure that was clicked.

    Not from the residual the reader arrived through: the residual is what sent them looking,
    and the clicked figure is tagged with the line it belongs to, which is the question the
    dropdown asks. Falling back to the residual's line would offer to put a missing caption's
    figure on the *total* it is missing from.
    """
    if mapped:
        return mapped
    if tag and tag in {line.metric for line in learned}:
        return tag
    if new_line:
        return NEW_LINE_PREFIX + str(new_line["tag"])
    return metric if metric in ledger.BY_KEY else ""


def _label_for(metric: str) -> str:
    """The printed label of a chart line, for naming it back to a reader."""
    account = ledger.BY_KEY.get(metric)
    return account.label if account else metric


def _default_line(groups: list[dict[str, Any]], section: str) -> str:
    """The line the form opens on when the reader arrived with nothing to go on.

    The first line of the heading they pressed *add a line* under, or ``""`` when they named no
    heading -- in which case the form opens on nothing and the reader chooses. Its own function
    because the answer decides more than what is highlighted: the side is only asked for a line
    the chart does not carry, so "which line is this" has to be settled before the page is built.
    """
    for group in groups:
        if group["section"] == section and group["lines"]:
            return group["lines"][0].key
    return ""


def _metric_for_tag(tag: str, period: Any) -> str:
    """The chart line a clicked taxonomy tag already feeds, or ``""``.

    Two sources, because either alone is incomplete: the tags this project maps by name
    (`ingest/xbrl.py::TAG_MAP`), and the provenance of the period in front of us -- a tag we
    extracted from *this* filing has a line whether or not the hand-maintained table lists it.

    **Only a chart line answers here.** The provenance also holds the keys of figures a reader
    put in by hand, and for one of those the key *is* the filing's tag -- so a learned line
    looked like a tag that already fed a line, which is the one condition that suppresses the
    offer to create one. Reported 2026-10-10: *"the 'Add a line to these accounts' ... no [longer]
    gives the option to use the line name from the accounts read page"*, after a reader had added
    a caption from a 20-F and then removed and restored it. Whether a key the chart does not carry
    is *printed* depends on the filer still having that line, which the caller checks against its
    own list of learned lines; this function answers only for the chart.
    """
    if not tag:
        return ""
    from awltux.ingest.xbrl import metric_for_tag

    known = metric_for_tag(tag)
    if known:
        return known
    for name, entry in (period.metric_sources or {}).items():
        if name not in ledger.BY_KEY:
            continue
        if isinstance(entry, dict) and str(entry.get("span") or "") == tag:
            return name
    return ""


def _removal_target(
    period: Any, remove: str | None, record: Any, rules: Any
) -> dict[str, Any] | None:
    """What the form shows about the line being taken out, or nothing when it is an addition.

    A named step because the confirmation page has two modes and this is what decides which:
    the presence of a target *is* the mode, rather than a second flag that could disagree with
    it. What a reader wants before agreeing is the figure and where it was extracted from.

    A line the filer names is removable like any other -- the ledger prints it in the statement
    and offers the same link -- so the two sources of a line are looked up together.
    """
    if remove is None:
        return None
    account = ledger.BY_KEY.get(remove)
    if account is None:
        learned = corrections_rules.known_line(rules, remove)
        if learned is None:
            raise HTTPException(status_code=404, detail=f"no line {remove!r}")
        account = ledger.Account(
            key=learned.metric,
            label=learned.label,
            statement=learned.statement,
            section=learned.section,
            side=learned.side,
        )
    entry = (period.metric_sources or {}).get(remove) or {}
    return {
        "account": account,
        "value": metrics_module.value_of(period.metrics or {}, remove),
        "tag": entry.get("span") or "",
        "accession": entry.get("accession") or "",
        # A line a filer-wide rule already removes is not something this period's own page can
        # put back: its undo is the rule's, and the form says so.
        "filer_rule": remove in rules.removed,
        "removed": remove in record.removed or remove in rules.removed,
    }


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
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        rules = corrections_rules.load_filer(session, cik)
        record = corrections_rules.load_period(period)
        if metric not in ledger.BY_KEY and corrections_rules.known_line(rules, metric) is None:
            # A line the filer taught the page is a line of the accounts too, and the ledger
            # offers the same remove link beside it.
            return _correction_redirect(period_id, statement, "no-line")
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
    section: str = Form(""),
    caption: str = Form(""),
    tag: str = Form(""),
    url: str = Form(""),
    note: str = Form(""),
    origin: str = Form("typed"),
) -> RedirectResponse:
    """Put a figure on a line by hand, on this period's row and no other.

    A figure belongs to the period it was stated for, so unlike a removal this cannot be carried
    to the filer's other periods; see the module docstring of `analysis/corrections.py`.

    **A line the filer names is learned, and that is the one thing here that does carry.** A
    figure the 10-K states under a caption this project's chart does not carry arrives as
    ``new:<taxonomy:Tag>``: the tag becomes the line's name -- it is the identity the *filing*
    gives the caption, so next year's 10-K answers to it -- and the filing's own header and the
    heading the reader chose are recorded against the filer, so every later period offers the
    line in the same place.
    """
    figure = _parse_figure(value)
    tab = _correction_tab(statement)
    tag = tag.strip()
    learned = None
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        period, instrument = detail["period"], detail["instrument"]
        cik = instrument.sec_cik if instrument is not None else None
        rules = corrections_rules.load_filer(session, cik)
        if metric.startswith(NEW_LINE_PREFIX):
            learned, refusal = _requested_line(
                period,
                tab,
                metric,
                tag=tag,
                caption=caption,
                section=section,
                cik=cik,
            )
            if refusal or learned is None:
                return _correction_redirect(period_id, statement, refusal or "no-line")
            metric, tag = learned["metric"], learned["tag"]
        elif metric not in ledger.BY_KEY and corrections_rules.known_line(rules, metric) is None:
            return _correction_redirect(period_id, statement, "no-line")
        if figure is None:
            return _correction_redirect(period_id, statement, "bad-value")
        # A line the chart already carries is posted on **the chart's side**, whatever the form
        # said. The ledger sums it with the weight its own line carries, so a reader's choice
        # here was recorded and then ignored by everything that reads the accounts -- the live
        # row read "revenue ... debit" while the chart posts revenue as a credit. Reported
        # 2026-10-10: *"selecting the debit/credit selectors when configuring the add line
        # doesn't seem to do anything"*. The form no longer asks for those lines either.
        posted_side = side if metric not in ledger.BY_KEY else ledger.BY_KEY[metric].side
        corrections_rules.add(
            period,
            metric,
            value=figure,
            side=posted_side,
            tag=tag,
            url=url.strip(),
            note=note.strip(),
            origin=origin if origin in CORRECTION_ORIGINS else "typed",
            rules=rules,
        )
        if learned is not None:
            corrections_rules.learn_line(
                rules,
                metric,
                label=learned["label"],
                statement=tab,
                section=learned["section"],
                side=side,
                tag=learned["tag"],
            )
            corrections_rules.save_filer(session, cik or "", rules)
    return _correction_redirect(period_id, statement, "added-line" if learned else "added")


def _requested_line(
    period: Any,
    statement: str,
    metric: str,
    *,
    tag: str,
    caption: str,
    section: str,
    cik: str | None,
) -> tuple[dict[str, Any] | None, str]:
    """The line a ``new:`` submission asks to create, or the reason it cannot be.

    Returns the record to learn and an outcome code -- ``""`` when it is a line to create, else
    the same code the redirect carries, so the rule and the message cannot drift apart.

    Three refusals, each for a different reason: no tag to name the line by, no heading the
    statement prints (a line nothing shows), and no filer to record it against -- a line is a
    statement about the company, and one stored on a single period would silently not survive to
    the next.
    """
    tag = tag or metric[len(NEW_LINE_PREFIX) :]
    if not tag or not caption.strip():
        return None, "no-line"
    if section not in _printed_headings(period, statement):
        return None, "no-section"
    if not cik:
        return None, "no-filer"
    return {"metric": tag, "tag": tag, "label": caption.strip(), "section": section}, ""


@router.post("/accounts/{period_id}/filer-lines/forget", include_in_schema=False)
def forget_learned_line(
    period_id: int,
    metric: str = Form(...),
    statement: str = Form(ledger.DEFAULT_STATEMENT),
) -> RedirectResponse:
    """Stop offering a line this filer taught the page, for every one of its periods.

    The line is only *offered*, so forgetting it changes no figure: the value that was put on it
    stays on the period it was written to, where it can be taken off in the usual way. Said that
    way in the panel too, because a reader who removes a heading from a dropdown and finds the
    figure still counted would reasonably call it a bug.
    """
    with session_scope() as session:
        detail = _accounts_detail(session, period_id)
        filer = detail["instrument"]
        cik = filer.sec_cik if filer is not None else None
        if not cik:
            return _correction_redirect(period_id, statement, "no-rule")
        rules = corrections_rules.load_filer(session, cik)
        if not corrections_rules.forget_line(rules, metric):
            return _correction_redirect(period_id, statement, "no-line")
        corrections_rules.save_filer(session, cik, rules)
    return _correction_redirect(period_id, statement, "line-forgotten")


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


def _sector_facts(session, name: str) -> dict[str, Any]:
    """Everything a sector page shows beside its instruments, from one session.

    Split out so the route reads as what it *decides* -- which instruments, in what order, on
    which page -- and this as what the sector *is*. They share a session and nothing more: none
    of these reads depends on another, and none depends on the reader's sort.
    """
    counts = dict(queries.sector_group_counts(session))
    series = queries.sector_sentiment_series(session, name, days=60)
    return {
        "news": queries.sector_news(session, name),
        "series": series,
        "latest": series[-1] if series else None,
        "index": queries.sector_price_index(session, name),
        "index_basis": queries.sector_index_basis(session, name),
        "universe_size": queries.universe_size(session),
        # The count is of *this* sector, and "unclassified" is the absence of one -- so it is
        # read from the empty column rather than from a name that no instrument carries.
        "instrument_count": counts.get(
            name if name != sector_map.UNCLASSIFIED else None, 0
        ),
        **queries.research_reports(session, subject_type="sector", subject_id=name),
    }


@router.get("/sectors/{name}", response_class=HTMLResponse, include_in_schema=False)
def sector_page(request: Request, name: str, page: int = Query(1, ge=1)) -> HTMLResponse:
    """One sector: its instruments, its news, and its sentiment.

    This is the sector's page rather than a filtered view of the recommendations table,
    which is what the old link was. The table is the same template either way --
    `partials/recommendations.html` is included here with `list_base` set to this page --
    so sorting and paging behave identically and a click on a column heading re-sorts the
    sector instead of dropping the reader into the whole universe.

    The state the page honours is therefore the *ordering and the page number*
    (`filters.SECTOR_TABLE_PARAMS`), and it has to be read from the request: the headings emit
    `?sort=sentiment`, and a route that ignores the query string renders the default order
    while the arrow stays on the default column, which is what made every heading look like it
    sorted by the wrong one.

    An unknown name is a 404 rather than an empty page: "no such sector" and "a sector
    with nothing in it" are different answers, and the second is already reachable
    through the unclassified bucket.
    """
    if not sector_map.is_sector_page(name):
        raise HTTPException(status_code=404, detail="no such sector")

    per_page = 50
    table = filters.FilterSet.parse(
        filters.recommendation_specs(),
        filters.sector_table_params(request.query_params),
    )
    with session_scope() as session:
        rows, total = queries.recommendations(
            session,
            sort=table.value("sort"),  # type: ignore[arg-type]
            direction=table.value("direction"),  # type: ignore[arg-type]
            horizon=table.value("horizon"),
            sector_group=name,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        facts = _sector_facts(session, name)

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
            "filters": table,
            "horizon": table.value("horizon"),
            # The region is a page, not a fragment: nothing fetches it on its own, so the
            # pager must be a real navigation. See `recommendations.html` -- swapping this
            # table through `/partials/recommendations` would replace the sector's rows with
            # the whole universe's, which is a bug that only shows on a sector with more than
            # one page of instruments.
            "region_source": None,
            "list_base": f"/sectors/{quote(name, safe='')}",
            "is_unclassified": name == sector_map.UNCLASSIFIED,
            # The deep-dive block and the executive summary, the same partial the instrument
            # page uses. A sector's evidence is the news corpus alone, which the block says.
            "subject_type": "sector",
            "subject_label": f"the {name} sector" if name != sector_map.UNCLASSIFIED else name,
            **_research_links(f"/sectors/{quote(name, safe='')}", return_to="#research"),
            "research_message": request.query_params.get("research"),
            "research_reason": request.query_params.get("why"),
            **facts,
        },
    )


@router.get("/levers", response_class=HTMLResponse, include_in_schema=False)
def levers_page(request: Request) -> HTMLResponse:
    """The lever vocabulary, and how many instruments are recorded against each.

    Grouped by the vocabulary's own groups and ordered by them, not by the counts: this page
    is also the place a reader checks what a lever *means* before recording one, and a page
    that reordered itself as exposures were added would make that harder every time.

    The counts are the honest headline of the feature's state. Nothing fills these
    automatically yet -- `TODO.md` carries the deep-dive block that will -- so a reader who
    finds the page nearly empty should be able to see that plainly rather than wonder whether
    the query is broken.
    """
    with session_scope() as session:
        totals = lever_map.totals(session)
        recorded = lever_map.coverage(session)

    groups = []
    for group in lever_map.GROUP_ORDER:
        rows = []
        for lever in lever_map.LEVERS:
            if lever.group != group:
                continue
            counted = totals.get(lever.key, {})
            rows.append(
                {
                    "key": lever.key,
                    "label": lever.label,
                    "channel": lever.channel,
                    "instruments": counted.get("instruments", 0),
                    "primary": counted.get("primary", 0),
                }
            )
        groups.append(
            {
                "key": group,
                "label": lever_map.GROUP_LABELS.get(group, group),
                "note": lever_map.GROUP_NOTES.get(group, ""),
                "levers": rows,
            }
        )

    return templates.TemplateResponse(
        request,
        "levers.html",
        {
            "groups": groups,
            "vocabulary": len(lever_map.LEVERS),
            "coverage": recorded,
            "directions": lever_map.DIRECTIONS,
            "direction_labels": lever_map.DIRECTION_LABELS,
        },
    )


@router.get("/levers/{key}", response_class=HTMLResponse, include_in_schema=False)
def lever_page(request: Request, key: str) -> HTMLResponse:
    """One lever: what it is, and every in-universe instrument recorded against it.

    An unknown key is a 404 rather than an empty list, for the reason
    :func:`sector_page` gives: "no such lever" and "nothing recorded for it yet" are
    different answers, and only one of them should make a reader doubt their spelling.
    """
    if not lever_map.is_lever(key):
        raise HTTPException(status_code=404, detail="no such lever")

    with session_scope() as session:
        rows = lever_map.instruments_for(session, key)
        coverage = lever_map.coverage(session)

    lever = lever_map.BY_KEY[key]
    return templates.TemplateResponse(
        request,
        "lever.html",
        {
            "key": key,
            "label": lever.label,
            "channel": lever.channel,
            "group": lever.group,
            "group_label": lever_map.GROUP_LABELS.get(lever.group, lever.group),
            "group_note": lever_map.GROUP_NOTES.get(lever.group, ""),
            "rows": rows,
            "coverage": coverage,
            "direction_labels": lever_map.DIRECTION_LABELS,
            "strength_labels": lever_map.STRENGTH_LABELS,
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
    target = _stated_target(run)
    if target:
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


def _stated_target(run) -> str | None:
    """The target the run recorded when it started, when it is a usable string.

    `JobSpec.target` is written onto the row at `start_run`, so this answers for a run that
    is still in flight -- which is the only state the log page is ever read in.
    """
    detail = (run.detail or {}) if run is not None else {}
    target = detail.get("target")
    return target if isinstance(target, str) and target else None


def _log_target(session, job_id: str, run) -> tuple[str | None, str | None]:
    """What a run is about, and where to read about it: ``(name, href)``.

    ``(None, None)`` for the jobs that are about nothing in particular, which is most of them.

    **A deep-dive has the refresh's problem one level up.** The refresh writes every company's
    log to one file under one job id, so the job id cannot say which company it is showing --
    the reason `_target_of` exists. A deep-dive is the other job whose log is watched from a
    page about a single subject, and it writes one file for *every* subject it can be asked
    about, instrument or sector.

    The run records the subject's id but not its kind, so the kind is read from the subject's
    own report row. That row is committed before the run's thread starts
    (`research.service._open_report`), so it is there for the whole time the log is being
    watched -- unlike `ResearchReport.run_id`, which is attached only after the refresh step
    has finished, which for a company with filings on file is minutes into the run.

    A subject with no report row gets no link rather than a guessed one: the two paths differ,
    and naming the wrong one would put a 404 behind a breadcrumb.
    """
    if job_id == scoped.REFRESH_JOB:
        ticker = _target_of(run, _lease_rows(session))
        if ticker is None:
            return None, None
        return ticker, f"/instrument/{quote(ticker, safe='')}"

    if job_id != research_service.RESEARCH_JOB:
        return None, None

    subject = _stated_target(run)
    if not subject:
        return None, None
    kind = session.execute(
        select(ResearchReport.subject_type)
        .where(ResearchReport.subject_id == subject)
        .order_by(desc(ResearchReport.id))
        .limit(1)
    ).scalar_one_or_none()
    where = quote(subject, safe="")
    if kind == "sector":
        return subject, f"/sectors/{where}"
    if kind == "instrument":
        return subject, f"/instrument/{where}"
    return subject, None


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
        # What the run is about, and where to read about it, when it is about one subject at
        # all. Read while the session is open, like the run itself.
        target, target_href = _log_target(session, job_id, run)

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
            "target_href": target_href,
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


def _stored_document(filing_id: int) -> tuple[Any, str, str]:
    """Where a filing's bytes are, its media type, and its title -- or a 404.

    The path is re-resolved against the data directory before it is opened. It comes from our
    own database, but a stored path is still a path, and a route that joins one to a root
    without checking is how a traversal arrives. Shared by the two routes that serve a filing,
    so the check cannot be tightened on one and forgotten on the other.
    """
    settings = get_settings()
    with session_scope() as session:
        filing = session.get(Filing, filing_id)
        if filing is None or not filing.raw_path:
            raise HTTPException(
                status_code=404, detail=f"no stored document for filing {filing_id}"
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
    return path, document_type, title


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

    Bare ``sandbox``, with nothing allowed: this is the route a reader opens to *read* a
    filing, and it needs no script to do that. The picker at ``/filing/{id}/pick`` is the one
    that runs a script, and it is a separate URL with a separate policy so that relaxing
    anything is a visible, testable decision rather than a property of every filing view.
    """
    path, document_type, title = _stored_document(filing_id)

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


#: What the picker's own script is allowed to be, and why nothing else is.
#:
#: The filing is third-party HTML and it arrives with whatever the filer's filing agent wrote,
#: including inline ``on*`` handlers -- which a ``sandbox`` directive does **not** disable,
#: because event handlers are governed by ``script-src``, not by the sandbox. So the policy
#: names the one script the page may run. It cannot be ``'self'``: the sandbox puts the document
#: in an *opaque* origin, and an opaque origin matches no source expression, so the origin is
#: spelled out from the request the browser actually made.
_PICKER_SCRIPT = "/static/filing-picker.js"

#: The id the injected tag carries, so the script can read the chart's labels off it. An id
#: rather than `document.currentScript`: this tag is inserted into a document written by
#: somebody else, and an id is the one thing about it the script can be sure of.
_PICKER_SCRIPT_ID = "awltux-picker-script"


def _picker_accounts(statement: str) -> list[dict[str, str]]:
    """The chart's own lines for one statement, as ``{label, metric}`` pairs.

    Handed to the picker so it can say which of them an *untagged* table row's caption looks
    like -- the one thing that can tell a filing with no `ix:` elements which of its hundreds
    of rows is "Trade receivables". Filtered by the same rule the correction form uses
    (:func:`_line_choices`), so the picker can never recognise a line the form does not offer.

    Both sides of the comparison are normalised in the script rather than here: the caption
    being matched is in the browser, and one normaliser is one thing to keep true.
    """
    return [
        {"label": account.label, "metric": account.key}
        for account in ledger.CHART
        if account.statement == statement
    ]


def _picker_origin(request: Request) -> str:
    """The origin this request was served from, as the browser sees it."""
    url = request.url
    return f"{url.scheme}://{url.netloc}"


def _strip_scripts(document: str) -> str:
    """Remove every script the filing brought with it.

    Both halves are needed. The policy above stops the *inline* handlers from running at all,
    but a document carrying a ``<script src>`` from somewhere else would still be a network
    request the filer chose, and the reader's picker is not the place for it. A parser would be
    the thorough answer; a filing's scripts are exactly the tags and the regex is bounded by
    the document being static HTML.
    """
    without_paired = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", document, flags=re.I | re.S)
    return re.sub(r"<script\b[^>]*/\s*>", "", without_paired, flags=re.I)


def _with_picker(document: str, *, accounts: list[dict[str, str]]) -> str:
    """The filing with the picker's script appended, before the end of the body.

    The statement's lines travel on the tag itself rather than on the URL, because they are
    the same for every visit to one statement and the query string is where the *reader's*
    coordinates live. Escaped for an attribute and not for HTML text: the payload is JSON, so
    its quotes are the ones that would end the attribute early.
    """
    payload = html.escape(json.dumps(accounts, separators=(",", ":")), quote=True)
    tag = (
        f'<script id="{_PICKER_SCRIPT_ID}" src="{_PICKER_SCRIPT}" '
        f'defer data-awltux-accounts="{payload}"></script>'
    )
    at = document.lower().rfind("</body>")
    if at == -1:
        return document + tag
    return document[:at] + tag + document[at:]


@router.get("/filing/{filing_id}/pick", include_in_schema=False)
def filing_picker(filing_id: int, request: Request) -> Response:
    """Serve a filing with the script that lets a reader click its tagged figures.

    Asked for directly: *"Allow the user to click xbrl values in the government report which
    adds them to Account section indicated by the url property."* The coordinates of what the
    reader is correcting -- which period, which line of the accounts -- travel in this page's
    own query string, so the script has only to read them; nothing is decided by the filing.

    **A separate URL from the plain document, and this is the whole reason.** This page needs
    ``allow-scripts`` to run the picker at all, and the policy to run a script is not one to
    give every filing view. It is also not ``allow-forms``: the picker does not post anything.
    It hands the reader to a page of ours in a new tab, which needs ``allow-popups`` and
    ``allow-popups-to-escape-sandbox`` -- without the second, our own page would *inherit* the
    sandbox and load in an opaque origin, where it could neither keep a session nor run its own
    script. Opening a popup the reader cannot trust is the failure this arrangement avoids, so
    the new tab is one of ours rather than anything the filing asked for.
    """
    path, document_type, _ = _stored_document(filing_id)
    text = path.read_bytes().decode("utf-8", errors="replace")
    headers = {
        "Content-Security-Policy": (
            "sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; "
            f"script-src {_picker_origin(request)}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{filing_id}.htm"',
        "Cache-Control": "private, max-age=86400",
    }
    # The statement the reader came from. It decides which of the chart's labels the picker
    # matches an untagged table row against, so a balance-sheet caption is never compared with
    # an income-statement line. Defaulted rather than refused: the same default the confirmation
    # form and the script use, so an old link still works.
    statement = request.query_params.get("awltux_statement") or ledger.DEFAULT_STATEMENT
    return Response(
        content=_with_picker(
            _strip_scripts(text), accounts=_picker_accounts(statement)
        ),
        media_type=document_type,
        headers=headers,
    )


@router.get("/research/{report_id}", include_in_schema=False)
def research_report_document(report_id: int) -> Response:
    """Serve one deep-dive research report so it can be read.

    **Sandboxed for the same reason a filing is, and one more.** A filing is third-party HTML
    served from this application's own origin, and this is model-written HTML served from the
    same origin -- an origin that can reach the API and therefore the account. The reporting
    path escapes every field it renders, so this is belt and braces; it is fitted anyway
    because the day someone adds a `|safe` is the day the sandbox is the only thing left.

    The path is **derived from the row, not read out of it**. `raw_path` was written as a bare
    file name where this route joined it to the data directory, so the file it named was never
    where the row said it was and a finished report answered 404 -- reported 2026-10-10 against
    the first deep-dive ever completed. The location is a pure function of the subject and the
    id, all of them columns, so deriving it cannot disagree with itself the way a stored copy
    can. The stored path is still written correctly for anyone reading the volume; it is just
    not what decides which file is served.

    The re-resolve is kept even though nothing a writer controls is in the path any more: it
    is the check that says the derived location is inside the directory it is supposed to be
    in, which is a claim about the configuration rather than about the input.
    """
    settings = get_settings()
    with session_scope() as session:
        row = session.get(ResearchReport, report_id)
        if row is None or row.status != "done":
            raise HTTPException(
                status_code=404,
                detail=f"no stored report for {report_id}",
            )
        subject_type, subject_id = row.subject_type, row.subject_id
        title = row.title or f"research {report_id}"

    data_dir = settings.data_dir.resolve()
    path = research_report.report_path(
        settings,
        subject_type=subject_type,
        subject_id=subject_id,
        report_id=report_id,
    ).resolve()
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
            # What the app is configured to do, with the reasons the config file gives for
            # each. Read rather than restated -- see `web/configuration.py`.
            "configuration": configuration.rows(),
        },
    )
