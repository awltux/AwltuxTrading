"""Where a set of figures came from, as a link -- the accounts page's SOURCE.

Asked for 2026-10-23: *"When viewing specific accounts, can the SOURCE item be a link to the
original website the data was gathered from? I don't know if this info is currently held."*

**Partly held, and the split is a fact about each source rather than a matter of taste.**
Measured on the live database (824 periods):

* ``xbrl_companyfacts`` (234) -- **held, and exactly.** Every row records the SEC accession in
  ``metric_sources``, and 192 of the 234 resolve to a ``filing`` row in this database with the
  document's own URL. The other 42 are periods whose document was never downloaded; their
  origin is still known -- the companyfacts endpoint the figures were read from -- and that is
  what they link to.
* ``yahoo_statements`` (391) and ``yahoo_info`` (168) -- **derived.** They came from Yahoo
  Finance through `yfinance`, which takes a symbol and nothing else, so the link is Yahoo's own
  page for this listing.
* ``llm_extraction`` (22) -- **not held, and now recorded.** A figure read out of a filed
  document belongs to that document, but nothing wrote ``filing_id`` until 2026-10-23: 0 of 824
  rows carried one. New rows do, and link the filing. The rows already stored have no link and
  say so; matching them by ``period_end`` would name a document for 14 of the 22 without
  proving it is the one that was read, and a wrong provenance link is worse than none on a page
  whose subject is provenance.
* ``deep_research`` (9) -- **this application.** The reading is our own deep-dive, so the link
  is the Research tab of the instrument it was run about, not an outside site.

Nothing here guesses: a source with no derivable origin returns an :class:`Origin` with no URL
and a sentence saying why, which the page prints rather than inventing a link.
"""

from __future__ import annotations

import urllib.parse
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.analysis import linkbase
from awltux.db.models import Filing, Instrument
from awltux.providers.edgar import normalise_cik

#: The SEC endpoint the structured XBRL figures are read from.
#:
#: The same URL `providers/edgar.py` calls, spelled from the CIK: a period whose document was
#: never downloaded still came from here, and this is the honest link for it.
_SEC_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

#: Yahoo's own pages for a listing. `yfinance` wraps Yahoo's API, so the site is Yahoo Finance
#: and the page is the one a reader can open.
_YAHOO_PAGES = {
    "yahoo_statements": ("https://finance.yahoo.com/quote/{symbol}/financials", "statements"),
    "yahoo_info": ("https://finance.yahoo.com/quote/{symbol}/key-statistics", "key statistics"),
}

#: Companies House's filing history for a company number -- where its accounts are published.
_COMPANIES_HOUSE = (
    "https://find-and-update.company-information.service.gov.uk/company/{number}/filing-history"
)


@dataclass(frozen=True, slots=True)
class Origin:
    """Where a period's figures came from: the link, the place, and why.

    ``url`` is ``None`` when the origin is not recorded, and then ``note`` carries the sentence
    that says so -- which is the case the page must print rather than leave blank.
    """

    url: str | None
    site: str
    note: str
    #: Whether the link leaves this application, which decides whether it opens in its own tab.
    external: bool = True


def origins(
    session: Session, instrument: Instrument, periods: list[object]
) -> dict[int, Origin]:
    """The origin of each period's figures on one accounts page, keyed by period id.

    One query for the filing URLs and no query per rule, because a page shows at most a handful
    of periods: the chosen set of accounts plus the sources it displaced.
    """
    documents = _document_urls(session, instrument, periods)
    return {
        period.id: _origin(period, instrument, documents.get(period.id))
        for period in periods
    }


def _document_urls(
    session: Session, instrument: Instrument, periods: list[object]
) -> dict[int, str]:
    """The URL of the filing each period's figures were read out of, where that is known.

    Two routes, and the first is the one that should be used whenever it exists: ``filing_id``
    is a direct reference and cannot be wrong. The second is how an XBRL period is tied to a
    document at all -- it records the accession it was filed under rather than a filing id (see
    :func:`awltux.analysis.linkbase.accession`) -- and the accession is matched against the
    filing's URL because that is where EDGAR puts it.
    """
    wanted = [period.filing_id for period in periods if getattr(period, "filing_id", None)]
    by_id: dict[int, str] = {}
    if wanted:
        for filing_id, url in session.execute(
            select(Filing.id, Filing.url).where(Filing.id.in_(wanted))
        ).all():
            if url:
                by_id[filing_id] = url

    out: dict[int, str] = {}
    for period in periods:
        filing_id = getattr(period, "filing_id", None)
        if filing_id:
            if filed := by_id.get(filing_id):
                out[period.id] = filed
            continue
        accession = linkbase.accession(period)
        if not accession:
            continue
        row = session.execute(
            select(Filing.url)
            .where(Filing.instrument_t212_ticker == instrument.t212_ticker)
            .where(Filing.url.like(f"%{accession.replace('-', '')}%"))
            .order_by(Filing.filed_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if row:
            out[period.id] = row
    return out


def _origin(period: object, instrument: Instrument, document: str | None) -> Origin:
    """One period's origin, in the order the evidence is worth trusting.

    A filed document first, because that is where the figures physically are; then whichever
    identifier the source is addressed by. The order matters for ``xbrl_companyfacts``, which is
    a government source *and* a provider endpoint: when the document is held it is the better
    link, and when it is not the endpoint is still true.

    The rest of this function is a dispatch, one named rule per source, because that is what the
    answer is -- a table of where each source comes from rather than a chain of conditions.
    """
    if document:
        return Origin(
            url=document,
            site=_host(document),
            note=f"the filed document these figures were read from, on {_host(document)}",
        )

    source = str(getattr(period, "source", ""))
    if source in _YAHOO_PAGES:
        return _yahoo_origin(instrument, source)
    if source == "xbrl_companyfacts":
        return _sec_origin(instrument)
    if source == "companies_house_ixbrl":
        return _companies_house_origin(instrument)
    if source == "llm_extraction":
        return _extraction_origin()
    if source == "deep_research":
        return _deep_dive_origin(instrument)
    return Origin(url=None, site="", note=f"no origin is recorded for the {source} source")


def _yahoo_origin(instrument: Instrument, source: str) -> Origin:
    """Yahoo's own page for this listing: `yfinance` takes a symbol and nothing else."""
    template, page = _YAHOO_PAGES[source]
    symbol = (instrument.yahoo_symbol or "").strip()
    if not symbol:
        return Origin(
            url=None,
            site="finance.yahoo.com",
            note="Yahoo Finance, but this instrument has no Yahoo symbol on file to link to",
        )
    return Origin(
        url=template.format(symbol=urllib.parse.quote(symbol, safe="")),
        site="finance.yahoo.com",
        note=f"Yahoo Finance's {page} page for {symbol}",
    )


def _sec_origin(instrument: Instrument) -> Origin:
    """The SEC's structured-data endpoint, which is what an XBRL period was read from.

    Used only when the document behind the period is not held: 42 of the 234 live XBRL periods
    are in that state, and the endpoint is still exactly where their figures came from.
    """
    cik = normalise_cik(instrument.sec_cik)
    if not cik:
        return Origin(
            url=None,
            site="sec.gov",
            note="the SEC's structured XBRL data, but this instrument has no SEC CIK on file",
        )
    return Origin(
        url=_SEC_COMPANYFACTS.format(cik=cik),
        site="data.sec.gov",
        note=(
            "the SEC's structured XBRL data for this company -- the endpoint these figures "
            "were read from, which EDGAR builds from its filings"
        ),
    )


def _companies_house_origin(instrument: Instrument) -> Origin:
    """The company's filing history at Companies House, where its accounts are published."""
    number = (instrument.ch_company_number or "").strip()
    if not number:
        return Origin(
            url=None,
            site="Companies House",
            note="Companies House, but this instrument has no company number on file",
        )
    return Origin(
        url=_COMPANIES_HOUSE.format(number=urllib.parse.quote(number, safe="")),
        site="Companies House",
        note="this company's filing history at Companies House, where its accounts are published",
    )


def _extraction_origin() -> Origin:
    """Our own model's reading of a filed document, when that document is not recorded."""
    return Origin(
        url=None,
        site="this app",
        note=(
            "this app's model reading of a filed document; the specific document is not "
            "recorded against rows written before 2026-10-23, so there is nothing to link"
        ),
    )


def _deep_dive_origin(instrument: Instrument) -> Origin:
    """This application's own deep-dive: the link is its report list, not an outside site."""
    where = urllib.parse.quote(instrument.t212_ticker, safe="")
    return Origin(
        url=f"/instrument/{where}?tab=research",
        site="this app",
        note=(
            "this app's own deep-dive, read from the documents it holds -- the report is on the "
            "instrument's Research tab"
        ),
        external=False,
    )


def _host(url: str) -> str:
    """The site a URL is on, for a sentence rather than a link."""
    return urllib.parse.urlsplit(url).netloc or url


__all__ = ["Origin", "origins"]
