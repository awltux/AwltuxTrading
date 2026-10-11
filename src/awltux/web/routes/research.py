"""Starting a deep-dive, and handing the reader the prompt it will use.

Four routes, two subjects, one implementation. The dialog is filled from
:func:`instrument_research_prompt` on demand rather than at page render, and that is not a
style choice: building the prompt reads the held annual reports to work out what the run will
read -- measured 2026-10-09, **8.4 seconds** for a company with two 10-Ks on file. Rendering it
with the page would put that on every visit to the Research tab, including the visits where the
reader only wants to read the last report.

A POST rather than a link for the launch, for the reason the instrument refresh records: a GET
would be followed by any prefetcher or crawler that happened to see the URL, and this is the
most expensive call the application makes. The outcome travels back as a query parameter, so
the page can say why nothing started without keeping state anywhere.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from awltux.research import service as research
from awltux.web.templating import templates

router = APIRouter(tags=["research"], include_in_schema=False)


def _prompt(request: Request, subject_type: str, subject_id: str) -> HTMLResponse:
    """The editable prompt as a fragment, or a 404 for a subject this database lacks."""
    prompt = research.draft_prompt(subject_type, subject_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"no such {subject_type} {subject_id}")
    return templates.TemplateResponse(
        request,
        "partials/research_prompt.html",
        {"prompt": prompt, "subject_type": subject_type, "subject_id": subject_id},
    )


def launch(subject_type: str, subject_id: str, prompt: str) -> RedirectResponse:
    """Launch, and send the reader back to the block they pressed the button in.

    Public because two pages start a run on the same subject and both have to say what
    happened in the same words: this one, where the reader arrives already looking at the
    instrument, and the universe search, which adds an instrument and starts its first
    deep-dive in one press. A second copy of the redirect would be a second place for the
    outcome vocabulary to drift.

    The refusal *reason* travels in the query string rather than as a fixed sentence per
    outcome, because there are six of them -- the feature is off, the subject is unknown, a run
    already holds it, another deep-dive has the single slot, no key is configured, the prompt
    was empty -- and each is a different thing for the reader to do. It is our own text, and
    the page escapes it like anything else.
    """
    outcome = research.start(subject_type=subject_type, subject_id=subject_id, prompt=prompt)
    where = quote(subject_id, safe="")
    tail = (
        "research=started"
        if outcome.ok
        else f"research=refused&why={quote(outcome.message)}"
    )
    if subject_type == "instrument":
        return RedirectResponse(
            url=f"/instrument/{where}?tab=research&{tail}", status_code=status.HTTP_303_SEE_OTHER
        )
    return RedirectResponse(
        url=f"/sectors/{where}?{tail}#research", status_code=status.HTTP_303_SEE_OTHER
    )


def _prompt_or_template(subject_type: str, subject_id: str, submitted: str) -> str:
    """What to run: the reader's prompt, or the template if they submitted an empty one.

    An empty field means "use the template", which is what the form does when JavaScript is
    off and the reader never saw the editable box. That path costs one extra evidence build and
    the same model call, so it is worth having as a fallback rather than an error.
    """
    if submitted.strip():
        return submitted
    return research.draft_prompt(subject_type, subject_id) or ""


@router.get("/instrument/{ticker}/research/prompt", response_class=HTMLResponse)
def instrument_research_prompt(request: Request, ticker: str) -> HTMLResponse:
    return _prompt(request, "instrument", ticker)


@router.get("/sectors/{name}/research/prompt", response_class=HTMLResponse)
def sector_research_prompt(request: Request, name: str) -> HTMLResponse:
    return _prompt(request, "sector", name)


@router.post("/instrument/{ticker}/research")
def instrument_research(ticker: str, prompt: str = Form("")) -> RedirectResponse:
    return launch("instrument", ticker, _prompt_or_template("instrument", ticker, prompt))


@router.post("/sectors/{name}/research")
def sector_research(name: str, prompt: str = Form("")) -> RedirectResponse:
    return launch("sector", name, _prompt_or_template("sector", name, prompt))
