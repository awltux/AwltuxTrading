"""SEC EDGAR provider.

Free, keyless, and the only genuinely authoritative structured source available:
US filers (and foreign private issuers via the ``ifrs-full`` taxonomy) tag their
financials, so revenue, debt and cash flow can be read as numbers rather than
parsed out of prose.

Conditions the SEC enforces, and which this client therefore enforces too:

* a **declared User-Agent containing a real contact**, or the request is answered
  with HTTP 403 "Undeclared Automated Tool";
* **no more than 10 requests per second** across all clients from one IP;
* no CORS, so it must be fetched server-side.

CIKs are zero-padded to ten digits everywhere. ``company_tickers.json`` returns
*unpadded* CIKs, which is a reliable source of subtle 404s.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, NamedTuple

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError

logger = logging.getLogger(__name__)

SOURCE = "edgar"
DATA_BASE = "https://data.sec.gov"
WWW_BASE = "https://www.sec.gov"

#: Filing types worth ingesting, mapped to whether they carry full financials.
INTERESTING_FORMS = {
    "10-K": "annual",
    "10-Q": "quarterly",
    "8-K": "event",
    "20-F": "annual",
    "40-F": "annual",
    "6-K": "interim",
    "S-1": "registration",
    "DEF 14A": "proxy",
}

#: The forms that *are* the shareholders' report: the annual filing containing the
#: audited primary statements. 10-K is the domestic form; 20-F and 40-F are the
#: foreign-private-issuer equivalents, and a company files one or the other rather
#: than both.
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


#: Content types a filing's primary document is allowed to be.
DOCUMENT_CONTENT_TYPES = (
    "text/html",
    "text/plain",
    "application/xhtml",
    "application/xml",
    "text/xml",
)

#: Markers of an SEC refusal served as a successful response.
#:
#: **The content type cannot tell these apart from a real filing**, which is the
#: whole problem: a 10-K is served as ``text/html`` and so is "Access Denied". The
#: first version of this check looked only at the content type and cheerfully stored
#: 1.5 megabytes of refusal as a fetched annual report -- the exact failure the check
#: existed to prevent, found by running it against the live endpoint rather than by
#: reading it. The body is the only evidence that distinguishes them.
_REFUSAL_MARKERS = (
    b"access denied",
    b"your request has been rate-limited",
    b"undeclared automated tool",
    b"request rate threshold",
)


@dataclass(frozen=True, slots=True)
class Document:
    """A fetched filing document, and whether it is one."""

    url: str
    status: int
    content_type: str | None
    body: bytes

    @property
    def refusal(self) -> str | None:
        """Why this is not the document, or ``None`` if it looks like one."""
        if self.status >= 400:
            return f"HTTP {self.status}"
        if not self.body:
            return "empty response"
        kind = (self.content_type or "").lower()
        if not any(allowed in kind for allowed in DOCUMENT_CONTENT_TYPES):
            return f"unexpected content type {self.content_type!r}"

        # Only the head is inspected: a real filing can mention any of these phrases
        # in its risk factors, but a refusal page leads with one.
        head = self.body[:4096].lower()
        for marker in _REFUSAL_MARKERS:
            if marker in head:
                return f"the provider refused the request ({marker.decode()})"
        return None

    @property
    def is_document(self) -> bool:
        return self.refusal is None


def _parse_iso_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


class _FilingRow(NamedTuple):
    """One entry from EDGAR's parallel-array submissions payload."""

    form: str
    filed_on: str
    accession: str
    primary_document: str
    description: str | None
    #: ``reportDate`` -- the period reported on, not the date filed. Often empty.
    report_date: str | None


def _rows_from_page(page: dict[str, Any]) -> Iterator[_FilingRow]:
    """One submissions page's parallel arrays, as rows.

    EDGAR returns ``form``/``filingDate``/``accessionNumber`` as parallel lists
    rather than a list of objects, and the arrays can disagree in length, so every
    index is bounds-checked rather than zipped into a silent truncation.

    ``reportDate`` is the period the filing *reports on* -- the fiscal year end for a
    10-K, the quarter end for a 10-Q -- as distinct from ``filingDate``, when it
    reached EDGAR. It is the filer's own statement of the period, and it is what
    lets a stored :class:`~awltux.db.FundamentalPeriod` be traced back to the
    document that reports it. It is often empty (8-Ks and some forms), so it is
    carried as ``None`` rather than guessed from the dates that are present.
    """
    forms = page.get("form") or []
    dates = page.get("filingDate") or []
    accessions = page.get("accessionNumber") or []
    documents = page.get("primaryDocument") or []
    descriptions = page.get("primaryDocDescription") or []
    report_dates = page.get("reportDate") or []

    for index, form in enumerate(forms):
        if index >= len(dates) or index >= len(accessions):
            break
        yield _FilingRow(
            form=form,
            filed_on=dates[index],
            accession=accessions[index],
            primary_document=documents[index] if index < len(documents) else "",
            description=descriptions[index] if index < len(descriptions) else None,
            report_date=report_dates[index] if index < len(report_dates) else None,
        )

_CIK_RE = re.compile(r"^\d{1,10}$")


def _newest_row_is_before(page: dict[str, Any], since: dt.date) -> bool:
    """Whether a ``filings.files`` entry ends before the caller's cutoff.

    EDGAR states each page's own range as ``filingFrom``/``filingTo``, so the question "can
    this page hold anything I want" is answered without requesting it. A page with no
    usable range is treated as possibly relevant, which costs a request rather than a
    silently missing year.
    """
    newest = _parse_iso_date(page.get("filingTo"))
    return newest is not None and newest < since


def normalise_cik(value: str | int | None) -> str | None:
    """Zero-pad a CIK to the ten digits EDGAR requires in URLs."""
    if value is None:
        return None
    text = str(value).strip().lstrip("0") or "0"
    if not _CIK_RE.match(text):
        return None
    return text.zfill(10)


class EdgarProvider:
    """Submissions, XBRL company facts, and the current-events feed."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        # The SEC requires a contactable identity; our configured value is used
        # verbatim and the default deliberately carries a placeholder address.
        self._client = HttpClient(
            SOURCE,
            settings=self.settings,
            headers={
                "User-Agent": self.settings.env.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Accept": "application/json, text/xml, application/atom+xml",
            },
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EdgarProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _require_cik(cik: str | int) -> str:
        padded = normalise_cik(cik)
        if padded is None:
            raise ProviderError(SOURCE, f"invalid CIK {cik!r}")
        return padded

    # ----------------------------------------------------------- submissions
    def get_submissions(self, cik: str | int, *, cache_ttl: float = 3600.0) -> dict[str, Any]:
        """Filing history for a company, plus its SIC classification."""
        padded = self._require_cik(cik)
        payload = self._client.get_json(
            f"{DATA_BASE}/submissions/CIK{padded}.json",
            cache_ttl=cache_ttl,
            archive_as=f"submissions_{padded}.json",
        )
        if not isinstance(payload, dict):
            raise ProviderError(SOURCE, f"unexpected submissions payload for CIK {padded}")
        return payload

    def get_recent_filings(self, cik: str | int, *, limit: int = 40) -> list[dict[str, Any]]:
        """Recent filings flattened from EDGAR's parallel-array representation.

        EDGAR returns ``form``/``filingDate``/``accessionNumber`` as parallel
        lists rather than a list of objects, and truncates older history into
        separate ``files``. This flattens the recent window, which is what the
        app acts on.
        """
        payload = self.get_submissions(cik)
        recent = ((payload.get("filings") or {}).get("recent")) or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        documents = recent.get("primaryDocument") or []
        descriptions = recent.get("primaryDocDescription") or []
        report_dates = recent.get("reportDate") or []

        out: list[dict[str, Any]] = []
        for index, form in enumerate(forms):
            if index >= len(dates) or index >= len(accessions):
                break
            if form not in INTERESTING_FORMS:
                continue
            accession = accessions[index]
            primary = documents[index] if index < len(documents) else ""
            out.append(
                {
                    "form": form,
                    "category": INTERESTING_FORMS[form],
                    "filing_date": dates[index],
                    "accession_number": accession,
                    "primary_document": primary,
                    "description": descriptions[index] if index < len(descriptions) else None,
                    "report_date": report_dates[index] if index < len(report_dates) else None,
                    "url": self.document_url(payload.get("cik") or cik, accession, primary),
                    "sic": payload.get("sic"),
                    "sic_description": payload.get("sicDescription"),
                    "company_name": payload.get("name"),
                }
            )
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def document_url(cik: str | int, accession: str, primary_document: str = "") -> str:
        """Build the public URL of a filing's primary document."""
        padded = normalise_cik(cik) or str(cik)
        bare = accession.replace("-", "")
        base = f"{WWW_BASE}/Archives/edgar/data/{int(padded)}/{bare}"
        return f"{base}/{accession}-index.htm" if not primary_document else f"{base}/{primary_document}"

    def get_annual_filings(
        self,
        cik: str | int,
        *,
        since: dt.date,
        limit: int = 12,
        cache_ttl: float = 86_400.0,
    ) -> list[dict[str, Any]]:
        """Annual reports filed on or after ``since``, newest first.

        Separate from :meth:`get_recent_filings` for two reasons, both of which
        would silently truncate a six-year request:

        * that method caps the *interesting* forms it returns, so a company filing
          many 8-Ks would have its older 10-Ks cut off by the limit rather than by
          the date;
        * EDGAR keeps roughly the last thousand filings in ``filings.recent`` and
          moves everything older into additional ``filings.files`` pages. A company
          filing 200 documents a year exhausts the recent window before six years
          are up, so the older pages have to be followed rather than assumed empty.
        """
        padded = self._require_cik(cik)

        annual: list[dict[str, Any]] = []
        for row in self._filing_rows(cik, cache_ttl=cache_ttl, since=since):
            if row.form not in ANNUAL_FORMS:
                continue
            filed = _parse_iso_date(row.filed_on)
            if filed is None or filed < since:
                continue
            annual.append(
                {
                    "form": row.form,
                    "category": INTERESTING_FORMS[row.form],
                    "filing_date": row.filed_on,
                    "filed_on": filed,
                    "accession_number": row.accession,
                    "primary_document": row.primary_document,
                    "description": row.description,
                    "report_date": row.report_date,
                    "url": self.document_url(padded, row.accession, row.primary_document),
                }
            )

        annual.sort(key=lambda entry: entry["filed_on"], reverse=True)
        return annual[:limit]

    def _filing_rows(
        self, cik: str | int, *, cache_ttl: float, since: dt.date | None = None
    ) -> Iterator[_FilingRow]:
        """Every stored filing as a :class:`_FilingRow`.

        Walks the recent window and then any older pages, newest page first. Nothing is
        sorted here: EDGAR already returns each page in reverse-chronological order.

        ``since`` is the date the caller stops caring, and it is what keeps the older pages
        from being fetched for nothing: a page is requested only while the newest row read so
        far is still on or after it. A company whose recent window already covers the period
        asked for therefore makes one request, not two.

        **The older pages live on the submissions host, not in the archive.** They are named
        by ``filings.files[].name`` and served from ``data.sec.gov/submissions/``. Asking
        ``www.sec.gov/Archives/edgar/data/<cik>/<name>`` for one -- which is what this did
        until 2026-10-08 -- gets an HTTP 403 *Access Denied* page, because that path does not
        exist, and the CDN answers with a refusal rather than a 404. It read as a permission
        wall for months; measured, the same name on the submissions host returns 200 and the
        identical parallel arrays the recent window uses, so `_rows_from_page` reads it
        unchanged. GWW's page alone carries 1,762 filings back to 1994.
        """
        payload = self.get_submissions(cik, cache_ttl=cache_ttl)
        yield from _rows_from_page(((payload.get("filings") or {}).get("recent")) or {})

        for page in (payload.get("filings") or {}).get("files") or []:
            name = page.get("name")
            if not name:
                continue
            if since is not None and _newest_row_is_before(page, since):
                # Every page after this one is older still, so none of them can hold a
                # filing the caller asked for.
                return
            try:
                older = self._client.request(
                    "GET",
                    f"{DATA_BASE}/submissions/{name}",
                    cache_ttl=cache_ttl,
                ).json()
            except (ProviderError, ValueError) as exc:
                # A missing older page costs history, not the run: the recent window
                # has already been yielded, so the caller still gets what it can.
                logger.warning("could not read the older submissions page %s: %s", name, exc)
                continue
            if not isinstance(older, dict):
                continue
            yield from _rows_from_page(older)

    def fetch_document(self, url: str, *, cache_ttl: float = 604_800.0) -> Document:
        """Download a filing's primary document.

        Cached for a week: a filed document is immutable, and re-parsing one should
        never mean re-requesting it. The SEC's rate limit makes that worth more here
        than elsewhere.
        """
        # The SEC answers an archive request whose User-Agent declares no contact
        # with HTTP 403, and it does so for every request rather than once. Checking
        # here turns a silent backlog of 4,500 refusals into one sentence naming the
        # setting -- the deployed `.env` carries a contact, but the code default does
        # not, so a fresh install would otherwise fail with no explanation.
        agent = self.settings.env.sec_user_agent or ""
        if "@" not in agent:
            raise ProviderError(
                SOURCE,
                "the SEC refuses archive requests whose User-Agent declares no contact. "
                "Set AWLTUX_SEC_USER_AGENT to 'App/version (you@example.com)'.",
            )

        try:
            result = self._client.request(
                "GET", url, cache_ttl=cache_ttl, expect_json=False
            )
        except ProviderError as exc:
            raise ProviderError(SOURCE, f"could not fetch {url}: {exc}") from exc

        return Document(
            url=url,
            status=result.status,
            content_type=result.content_type,
            body=result.body,
        )


    def get_filing_index(
        self, cik: str | int, accession: str, *, cache_ttl: float = 604_800.0
    ) -> list[str]:
        """The filenames in one filing's directory, as EDGAR lists them.

        **A listing rather than a guessed name.** The linkbase beside a filing is called
        ``dac-20251231_cal.xml``, ``toi-20251231_cal.xml`` -- the filer's own prefix and
        its own period label -- so the name cannot be constructed from the accession.
        EDGAR serves the directory as JSON, which is one small request cached for a week
        because a filed directory never changes.

        Empty rather than raising when the payload is not the directory shape the endpoint
        documents: a filing we cannot list is a filing whose linkbase we cannot read, and
        the caller says so.
        """
        padded = self._require_cik(cik)
        # Built by `document_url` with the filename `index.json`, **not** by rewriting the
        # `-index.htm` URL: the accession appears in that URL twice (once as the directory
        # and once in the filename), so a replace leaves `.../<accession>/<accession>/
        # index.json` and EDGAR answers 404.
        url = self.document_url(padded, accession, "index.json")
        try:
            payload = self._client.get_json(url, cache_ttl=cache_ttl)
        except ProviderError as exc:
            raise ProviderError(SOURCE, f"could not list {url}: {exc}") from exc
        items = ((payload or {}).get("directory") or {}).get("item")
        if not isinstance(items, list):
            return []
        return sorted(
            str(item.get("name"))
            for item in items
            if isinstance(item, dict) and item.get("name")
        )


    # ------------------------------------------------------------ XBRL facts
    def get_company_facts(self, cik: str | int, *, cache_ttl: float = 86400.0) -> dict[str, Any]:
        """Every XBRL fact a company has ever tagged. Large; cache it hard."""
        padded = self._require_cik(cik)
        payload = self._client.get_json(
            f"{DATA_BASE}/api/xbrl/companyfacts/CIK{padded}.json",
            cache_ttl=cache_ttl,
            archive_as=f"companyfacts_{padded}.json",
        )
        if not isinstance(payload, dict):
            raise ProviderError(SOURCE, f"unexpected companyfacts payload for CIK {padded}")
        return payload

    def get_concept(
        self, cik: str | int, taxonomy: str, tag: str, *, cache_ttl: float = 86400.0
    ) -> dict[str, Any]:
        """A single concept's history, useful for a targeted refresh."""
        padded = self._require_cik(cik)
        payload = self._client.get_json(
            f"{DATA_BASE}/api/xbrl/companyconcept/CIK{padded}/{taxonomy}/{tag}.json",
            cache_ttl=cache_ttl,
        )
        if not isinstance(payload, dict):
            raise ProviderError(SOURCE, f"unexpected concept payload for {taxonomy}:{tag}")
        return payload

    # -------------------------------------------------------------- ticker map
    def get_ticker_map(self, *, cache_ttl: float = 604800.0) -> dict[str, dict[str, Any]]:
        """``{TICKER: {cik, title}}`` from EDGAR's official mapping file.

        Values are normalised to zero-padded CIKs because the file itself returns
        them unpadded.
        """
        payload = self._client.get_json(
            f"{WWW_BASE}/files/company_tickers.json",
            cache_ttl=cache_ttl,
            archive_as="company_tickers.json",
        )
        out: dict[str, dict[str, Any]] = {}
        if not isinstance(payload, dict):
            return out
        for entry in payload.values():
            if not isinstance(entry, dict):
                continue
            ticker = str(entry.get("ticker") or "").upper()
            cik = normalise_cik(entry.get("cik_str"))
            if ticker and cik:
                out[ticker] = {"cik": cik, "title": entry.get("title")}
        return out

    # ------------------------------------------------------- current events
    def get_current_events(
        self,
        *,
        form_type: str | None = "8-K",
        count: int = 100,
        cache_ttl: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Latest filings from the current-events Atom feed.

        This is the closest thing to a free real-time US corporate-events stream:
        filings appear within about a second of dissemination. ``cache_ttl`` is
        zero by default because the whole point is freshness.
        """
        params: dict[str, Any] = {"action": "getcurrent", "output": "atom", "count": count}
        if form_type:
            params["type"] = form_type
        result = self._client.get(
            f"{WWW_BASE}/cgi-bin/browse-edgar",
            params=params,
            cache_ttl=cache_ttl,
            expect_json=False,
        )
        return parse_atom_entries(result.text())

    # ------------------------------------------------------------- SIC codes
    def get_sic(self, cik: str | int) -> tuple[str | None, str | None]:
        try:
            payload = self.get_submissions(cik)
        except ProviderError:
            return None, None
        sic = payload.get("sic")
        return (str(sic) if sic else None, payload.get("sicDescription"))


def parse_atom_entries(xml_text: str) -> list[dict[str, Any]]:
    """Parse an EDGAR Atom feed into plain dicts.

    Uses BeautifulSoup rather than a strict Atom parser because EDGAR's feed is
    RSS-era XML that does not always satisfy a modern parser's expectations.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(xml_text, "xml")
    entries: list[dict[str, Any]] = []
    for entry in soup.find_all("entry"):
        # ``entry`` is bound as a default so the closure captures this
        # iteration's element rather than the loop variable by reference.
        def text(tag: str, _entry: Any = entry) -> str | None:
            node = _entry.find(tag)
            return node.get_text(strip=True) if node else None

        link_node = entry.find("link")
        link = link_node.get("href") if link_node and link_node.has_attr("href") else None

        entries.append(
            {
                "title": text("title"),
                "updated": text("updated"),
                "summary": text("summary"),
                "link": link,
                "form_type": text("category") or _form_from_title(text("title")),
                "cik": _cik_from_link(link),
            }
        )
    return entries


def _form_from_title(title: str | None) -> str | None:
    if not title:
        return None
    match = re.search(r"\b(10-K|10-Q|8-K|20-F|40-F|6-K|S-1|DEF 14A)\b", title)
    return match.group(1) if match else None


def _cik_from_link(link: str | None) -> str | None:
    """Extract the filer CIK from an EDGAR document URL."""
    if not link:
        return None
    match = re.search(r"/data/(\d+)/", link)
    if not match:
        return None
    return match.group(1).zfill(10)
