"""Companies House provider.

The free UK company register. What it does and does not give matters:

* It **does** give company profile, filing history, officers, persons with
  significant control, charges and insolvency.
* It **does not** give financial line items over REST. The structured route is
  the iXBRL accounts document itself, retrieved through the Document API or the
  bulk Accounts Data Product.

Authentication is HTTP Basic with the **API key as the username and a blank
password** -- a shape that surprises people who expect a bearer token. The free
limit is 600 requests per 5 minutes.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from awltux.config import Settings, get_settings
from awltux.providers.http import HttpClient, ProviderError, ProviderNotConfigured

logger = logging.getLogger(__name__)

SOURCE = "companies_house"
API_BASE = "https://api.company-information.service.gov.uk"
DOCUMENT_BASE = "https://document-api.company-information.service.gov.uk"

#: Filing-history categories that carry financial statements.
FINANCIAL_CATEGORIES = {"accounts"}


class CompaniesHouseProvider:
    """Search, profile, filing history and document retrieval."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: HttpClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.env.companies_house_api_key)

    def client(self) -> HttpClient:
        if self._client is None:
            if not self.configured:
                raise ProviderNotConfigured("Companies House", "companies_house_api_key")
            key = self.settings.env.require("Companies House", "companies_house_api_key")
            # Basic auth with the key as username and an empty password.
            self._client = HttpClient(
                SOURCE,
                settings=self.settings,
                base_url=API_BASE,
                auth=httpx.BasicAuth(key, ""),
                headers={"Accept": "application/json"},
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> CompaniesHouseProvider:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -------------------------------------------------------------- company
    def get_company(self, company_number: str) -> dict[str, Any]:
        payload = self.client().get_json(f"/company/{company_number}")
        if not isinstance(payload, dict):
            raise ProviderError(SOURCE, f"unexpected profile for {company_number}")
        return payload

    def search_companies(self, query: str, *, items_per_page: int = 20) -> list[dict[str, Any]]:
        """Search by name. Results are a *candidate list*, never a resolution.

        Names collide constantly on the UK register, so callers must verify a
        candidate before trusting it (see ``ingest.fundamentals``).
        """
        payload = self.client().get_json(
            "/search/companies",
            params={"q": query, "items_per_page": items_per_page},
            cache_ttl=86400.0,
        )
        if not isinstance(payload, dict):
            return []
        return list(payload.get("items") or [])

    # -------------------------------------------------------------- filings
    def get_filing_history(
        self, company_number: str, *, items_per_page: int = 50
    ) -> list[dict[str, Any]]:
        """Filing history, including accounts filings.

        Each accounts entry carries a ``links.document_metadata`` pointer; the
        financial content itself is only in the document.
        """
        payload = self.client().get_json(
            f"/company/{company_number}/filing-history",
            params={"items_per_page": items_per_page},
            cache_ttl=3600.0,
        )
        if not isinstance(payload, dict):
            return []
        return list(payload.get("items") or [])

    def get_accounts_filings(self, company_number: str) -> list[dict[str, Any]]:
        """Only the accounts filings, newest first."""
        items = self.get_filing_history(company_number)
        accounts = [
            item
            for item in items
            if (item.get("category") or "").lower() in FINANCIAL_CATEGORIES
        ]
        return sorted(
            accounts,
            key=lambda item: item.get("date") or "",
            reverse=True,
        )

    # ------------------------------------------------------------ documents
    def document_metadata(self, document_id: str) -> dict[str, Any]:
        payload = self.client().request(
            "GET",
            f"{DOCUMENT_BASE}/document/{document_id}",
            headers={"Accept": "application/json"},
        ).json()
        if not isinstance(payload, dict):
            raise ProviderError(SOURCE, f"unexpected document metadata for {document_id}")
        return payload

    def document_content(self, document_id: str) -> tuple[bytes, str]:
        """Fetch a filed document's bytes plus its content type.

        iXBRL arrives as ``application/xhtml+xml``; ``parse_ixbrl`` handles it.
        """
        result = self.client().request(
            "GET",
            f"{DOCUMENT_BASE}/document/{document_id}/content",
            headers={"Accept": "application/xhtml+xml, text/html, application/pdf"},
            expect_json=False,
            archive_as=f"ch_document_{document_id}",
        )
        content_type = ""
        return result.body, content_type

    # --------------------------------------------------------------- people
    def get_officers(self, company_number: str) -> list[dict[str, Any]]:
        payload = self.client().get_json(
            f"/company/{company_number}/officers", cache_ttl=86400.0
        )
        if not isinstance(payload, dict):
            return []
        return list(payload.get("items") or [])

    def get_psc(self, company_number: str) -> list[dict[str, Any]]:
        """Persons with significant control: who actually owns the company."""
        payload = self.client().get_json(
            f"/company/{company_number}/persons-with-significant-control",
            cache_ttl=86400.0,
        )
        if not isinstance(payload, dict):
            return []
        return list(payload.get("items") or [])


def normalise_company_number(value: str | None) -> str | None:
    """Uppercase and strip a company number; they are 8 characters on the register."""
    if not value:
        return None
    cleaned = value.strip().upper().replace(" ", "")
    return cleaned or None
