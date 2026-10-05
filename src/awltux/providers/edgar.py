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

import logging
import re
from typing import Any

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

_CIK_RE = re.compile(r"^\d{1,10}$")


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
