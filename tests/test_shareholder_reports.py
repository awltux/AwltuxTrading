"""Shareholders' reports: finding them, downloading them, and keeping the bytes.

The annual report is the primary evidence about a business, and until this existed
the system held only a pointer to one: 4,529 filing rows, not a single document,
every one of them stuck at ``status='pending'``.

Two things here were found by running the code against the live endpoint rather
than by reading it, and both have tests:

* the SEC answers an archive request whose User-Agent declares no contact with HTTP
  403, for every request rather than once;
* **"Access Denied" is served as HTTP 200 with content type text/html**, which is
  the same content type as a real 10-K. The first version of the check looked only
  at the content type and stored 1.5 megabytes of refusal as a fetched report.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import Filing, Instrument, session_scope
from awltux.ingest import documents
from awltux.providers.edgar import DATA_BASE, Document, EdgarProvider, _FilingRow
from tests.helpers import make_instrument

TICKER = "TEST_US_EQ"

ACCESSIONS = {
    2026: "000032019326000111",
    2025: "000032019325000079",
}

#: A reported US 10-K is XBRL-flavoured HTML and runs to megabytes.
REAL_FILING = (
    b"<?xml version='1.0' encoding='ASCII'?>\n<!--XBRL Document Created with the Workiva"
    b" Platform -->\n<html><body>" + b"<p>Consolidated Statements of Operations</p>" * 200
)

#: What the SEC actually answered, verbatim in shape and served with HTTP 200.
ACCESS_DENIED = (
    b"<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Transitional//EN\" "
    b"\"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd\">\n<html><head>"
    b"<meta http-equiv=\"Content-Type\" content=\"text/html; charset=utf-8\" /></head>"
    b"<body><H1>Access Denied</H1>\nYou don't have permission to access "
    b"\"http://www.sec.gov/Archives/edgar/data/320193/\" on this server."
)


class TestWhatCountsAsADocument:
    """The content type cannot distinguish a refusal from a filing."""

    def test_a_real_filing_is_accepted(self):
        document = Document("u", 200, "text/html", REAL_FILING)
        assert document.is_document
        assert document.refusal is None

    def test_an_access_denied_page_is_refused_despite_http_200(self):
        """The exact response the live endpoint gave, and the bug it caused.

        A refusal page is ``text/html`` with HTTP 200, so every other field says
        success. Without this check the archive fills with apologies that look like
        fetched reports.
        """
        document = Document("u", 200, "text/html", ACCESS_DENIED)
        assert not document.is_document
        assert document.refusal is not None
        assert "refused" in document.refusal

    @pytest.mark.parametrize(
        "document, fragment",
        [
            (Document("u", 403, "text/html", REAL_FILING), "HTTP 403"),
            (Document("u", 200, "text/html", b""), "empty"),
            (Document("u", 200, "application/json", b"{}"), "content type"),
            (Document("u", 200, "text/html", b"<html>Undeclared Automated Tool</html>"), "refused"),
        ],
    )
    def test_other_non_documents_are_refused(self, document, fragment):
        assert not document.is_document
        assert fragment in (document.refusal or "")

    def test_a_filing_may_mention_a_refusal_phrase_in_its_own_text(self):
        """Only the head of the body is inspected.

        A real 10-K discusses rate limits and access restrictions in its risk
        factors; scanning the whole document would reject it.
        """
        body = REAL_FILING + b"<p>Our systems may be subject to access denied errors.</p>"
        assert Document("u", 200, "text/html", body).is_document


class TestFilingDiscovery:
    """Which filings count as the shareholders' report, over a two-year window."""

    def _provider(self, monkeypatch, rows):
        """An EdgarProvider whose submissions pages are supplied, not fetched."""
        provider = EdgarProvider.__new__(EdgarProvider)

        def fake_rows(cik, *, cache_ttl, since=None):
            yield from rows

        monkeypatch.setattr(provider, "_filing_rows", fake_rows)
        monkeypatch.setattr(provider, "_require_cik", staticmethod(lambda cik: "0000320193"))
        return provider

    ROWS = [
        # form, date, accession, primary document, description, period reported on
        _FilingRow("10-K", "2026-02-01", "000032019326000111", "aapl-20250927.htm", "Annual report", "2025-09-27"),
        _FilingRow("10-Q", "2025-08-01", "000032019325000222", "aapl-20250628.htm", "Quarterly", "2025-06-28"),
        _FilingRow("8-K", "2025-06-01", "000032019325000333", "aapl-8k.htm", "Event", None),
        _FilingRow("10-K", "2025-02-01", "000032019325000079", "aapl-20240928.htm", "Annual report", "2024-09-28"),
        # Older than the window: the point of filtering by date rather than by limit.
        _FilingRow("10-K", "2019-02-01", "000032019319000000", "aapl-20180929.htm", "Annual report", "2018-09-29"),
    ]

    def test_only_annual_forms_are_returned(self, monkeypatch):
        provider = self._provider(monkeypatch, self.ROWS)
        found = provider.get_annual_filings("0000320193", since=dt.date(2024, 1, 1))
        assert [entry["form"] for entry in found] == ["10-K", "10-K"]
        # A 10-Q is not a shareholders' report, and an 8-K is not either.
        assert not any(entry["form"] in {"10-Q", "8-K"} for entry in found)

    def test_the_window_is_a_date_not_a_count(self, monkeypatch):
        """A limit would cut off an older annual report behind a run of 8-Ks."""
        provider = self._provider(monkeypatch, self.ROWS)
        found = provider.get_annual_filings("0000320193", since=dt.date(2024, 1, 1))
        assert "000032019319000000" not in {entry["accession_number"] for entry in found}

    def test_newest_first(self, monkeypatch):
        provider = self._provider(monkeypatch, self.ROWS)
        found = provider.get_annual_filings("0000320193", since=dt.date(2024, 1, 1))
        assert found[0]["filing_date"] > found[1]["filing_date"]

    def test_the_archive_url_is_built_from_the_accession(self, monkeypatch):
        provider = self._provider(monkeypatch, self.ROWS)
        found = provider.get_annual_filings("0000320193", since=dt.date(2024, 1, 1))
        assert (
            found[0]["url"]
            == "https://www.sec.gov/Archives/edgar/data/320193/000032019326000111/"
            "aapl-20250927.htm"
        )


class _JsonResponse:
    """What the HTTP client hands back, as far as `_filing_rows` is concerned."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class TestTheOlderSubmissionsPages:
    """EDGAR's older filings live on the submissions host, not in the archive.

    ``filings.files[].name`` is served from ``data.sec.gov/submissions/``. This asked
    ``www.sec.gov/Archives/edgar/data/<cik>/<name>``, a path that does not exist, and the CDN
    answers a non-existent path with an HTTP 403 *Access Denied* page rather than a 404 -- so
    a plain URL mistake read as a permission wall, complete with "check the User-Agent / key
    scope", for months.

    Measured on 2026-10-08 against the live endpoint for CIK 277135 (GWW): the wrong address
    returns **403**, the right one returns **200** with the same parallel arrays the recent
    window uses -- 1,762 filings from 1994-03-04 to 2016-09-15, including 18 10-Ks -- and
    `_rows_from_page` reads them unchanged.
    """

    PAGE = "CIK0000277135-submissions-001.json"

    RECENT = {
        "filings": {
            "recent": {
                "form": ["8-K"],
                "filingDate": ["2026-10-01"],
                "accessionNumber": ["000027713526000001"],
                "primaryDocument": ["gww-8k.htm"],
            },
            "files": [
                {
                    "name": PAGE,
                    "filingCount": 2,
                    "filingFrom": "1994-03-04",
                    "filingTo": "2016-09-15",
                }
            ],
        }
    }

    OLDER = {
        "form": ["10-K", "10-K"],
        "filingDate": ["2016-02-29", "1996-03-01"],
        "accessionNumber": ["000027713516000037", "000027713596000002"],
        "primaryDocument": ["gww20151231-10k.htm", "gww19951231-10k.htm"],
        "reportDate": ["2015-12-31", "1995-12-31"],
    }

    def _provider(self, monkeypatch, *, fails: bool = False):
        provider = EdgarProvider.__new__(EdgarProvider)
        asked: list[str] = []

        class _Client:
            def request(self, method, url, **kwargs):
                asked.append(url)
                if fails:
                    from awltux.providers.http import ProviderError

                    raise ProviderError("edgar", "HTTP 403 (check the User-Agent / key scope)")
                return _JsonResponse(TestTheOlderSubmissionsPages.OLDER)

        provider._client = _Client()  # type: ignore[assignment]
        monkeypatch.setattr(provider, "get_submissions", lambda cik, cache_ttl: self.RECENT)
        return provider, asked

    def test_the_older_page_is_requested_from_the_submissions_host(self, monkeypatch):
        provider, asked = self._provider(monkeypatch)

        rows = list(provider._filing_rows("0000277135", cache_ttl=0.0, since=dt.date(1990, 1, 1)))

        assert asked == [f"{DATA_BASE}/submissions/{self.PAGE}"]
        assert "Archives" not in asked[0]
        # And the rows are actually read, which is the half a URL fix alone would not give:
        # the older pages are the same parallel arrays as the recent window.
        assert [row.filed_on for row in rows] == ["2026-10-01", "2016-02-29", "1996-03-01"]
        assert rows[-1].report_date == "1995-12-31"

    def test_a_page_older_than_the_cutoff_is_not_requested_at_all(self, monkeypatch):
        """The recent window already covers this call, so there is nothing to look for.

        `deepen_annual_history` asks for two years while the window holds ten, so walking the
        older pages here would spend a 267 KB request per filer per run for nothing.
        """
        provider, asked = self._provider(monkeypatch)

        rows = list(provider._filing_rows("0000277135", cache_ttl=0.0, since=dt.date(2024, 1, 1)))

        assert asked == [], "the older page was fetched for a period the window already covers"
        assert [row.filed_on for row in rows] == ["2026-10-01"]

    def test_a_refused_older_page_costs_history_and_not_the_run(self, monkeypatch):
        provider, asked = self._provider(monkeypatch, fails=True)

        rows = list(provider._filing_rows("0000277135", cache_ttl=0.0, since=dt.date(1990, 1, 1)))

        assert asked, "it has to be tried to be refused"
        assert [row.filed_on for row in rows] == ["2026-10-01"], "the recent window is kept"


class TestWhereADocumentLands:
    def test_the_accession_is_the_filename(self, settings):
        url = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
        path = documents.document_path(settings, TICKER, url)
        assert path.name == "000032019325000079.htm"
        assert path.parent.name == TICKER
        assert documents.DOCUMENT_DIR in path.parts

    def test_a_url_that_is_not_an_archive_gets_a_stable_hash(self, settings):
        """The same document must always land at the same path, or a re-fetch would
        sit beside the first copy instead of replacing it."""
        url = "https://example.com/somewhere/report.htm"
        assert documents._document_key(url) == documents._document_key(url)
        assert documents.document_path(settings, TICKER, url) == documents.document_path(
            settings, TICKER, url
        )

    def test_the_extension_comes_from_the_url_so_it_cannot_drift(self, settings):
        assert documents.document_path(settings, TICKER, "https://x/a/000000000000000001.txt").suffix == ".txt"
        assert documents.document_path(settings, TICKER, "https://x/a/000000000000000001.htm").suffix == ".htm"
        # A query string must not become part of the suffix.
        assert documents.document_path(settings, TICKER, "https://x/a/000000000000000001.htm?v=2").suffix == ".htm"


class _FakeProvider:
    """A provider that serves documents from a dict and records what was asked for."""

    def __init__(self, by_url):
        self.by_url = by_url
        self.requested: list[str] = []

    def fetch_document(self, url):
        self.requested.append(url)
        return self.by_url[url]


def _filing(session, ticker, *, url, form="10-K", filed="2026-02-01", status="pending"):
    # The filing table has a foreign key to the instrument, so the instrument has to
    # exist first; most tests here only care about the filing.
    if session.get(Instrument, ticker) is None:
        session.add(make_instrument(ticker))
        session.flush()

    row = Filing(
        instrument_t212_ticker=ticker,
        source="edgar",
        filing_type=form,
        title=form,
        filed_at=dt.datetime.fromisoformat(filed).replace(tzinfo=dt.UTC),
        url=url,
        status=status,
    )
    session.add(row)
    session.flush()
    return row


def _url(accession: str, name: str = "report.htm") -> str:
    return f"https://www.sec.gov/Archives/edgar/data/320193/{accession}/{name}"


class TestDownloadingTheDocument:
    def test_the_bytes_are_stored_with_a_hash_and_a_status(self, settings):
        url = _url(ACCESSIONS[2025])
        with session_scope() as session:
            row = _filing(session, TICKER, url=url)
            provider = _FakeProvider({url: Document(url, 200, "text/html", REAL_FILING)})

            written = documents.fetch_document(
                session, row, settings=settings, provider=provider
            )

            assert written == len(REAL_FILING)
            assert row.status == "fetched"
            assert row.doc_hash is not None
            assert row.content_type == "text/html"
            assert row.error is None
            path = settings.data_dir / (row.raw_path or "")
            assert path.exists()
            assert path.read_bytes() == REAL_FILING

    def test_a_refusal_page_is_not_stored_as_a_report(self, settings):
        """The failure this whole check exists for: it looks fetched afterwards."""
        url = _url(ACCESSIONS[2026])
        with session_scope() as session:
            row = _filing(session, TICKER, url=url)
            provider = _FakeProvider({url: Document(url, 200, "text/html", ACCESS_DENIED)})

            written = documents.fetch_document(
                session, row, settings=settings, provider=provider
            )

            assert written is None
            assert row.status == "failed"
            assert row.raw_path is None, "a refusal must not become an archived report"
            assert row.doc_hash is None
            assert "refused" in (row.error or "")

    def test_a_provider_error_is_recorded_rather_than_raised(self, settings):
        from awltux.providers.http import ProviderError

        url = _url(ACCESSIONS[2026])

        class Failing(_FakeProvider):
            def fetch_document(self, url):
                raise ProviderError("edgar", "connection reset")

        with session_scope() as session:
            row = _filing(session, TICKER, url=url)
            written = documents.fetch_document(
                session, row, settings=settings, provider=Failing({})
            )

            assert written is None
            assert row.status == "failed"
            assert "connection reset" in (row.error or "")

    def test_only_the_pending_annual_reports_are_queued(self, settings):
        with session_scope() as session:
            _filing(session, TICKER, url=_url("000000000000000001"), form="10-K")
            _filing(session, TICKER, url=_url("000000000000000002"), form="8-K")
            _filing(
                session,
                TICKER,
                url=_url("000000000000000003"),
                form="20-F",
                status="fetched",
            )
            session.flush()

            queued = documents.pending_annual_reports(session)

            # The 10-K is waiting; the 8-K is not a shareholders' report and the
            # 20-F is already held.
            assert [row.filing_type for row in queued] == ["10-K"]

    def test_an_instrument_with_no_cik_is_left_alone(self, settings):
        """Nothing to ask for, and asking anyway would be a wasted request per name."""
        with session_scope() as session:
            session.add(make_instrument("NO_CIK_US_EQ", sec_cik=None))
            session.flush()

            report = documents.deepen_annual_history(session, settings=settings)

            assert report.discovered == 0


class TestTheInstrumentFlag:
    """Whether the reports are held, recorded on the instrument.

    The question "can I read this company's accounts?" is asked once per row on the
    dashboard and once per instrument by the acquisition job, so it is stored rather
    than derived. It is recomputed from the rows on every run, never incremented, so
    a half-finished run leaves it describing what is held rather than what was
    attempted.
    """

    def test_the_count_comes_from_documents_actually_held(self, settings):
        with session_scope() as session:
            session.add(make_instrument(TICKER, in_universe=True))
            session.flush()
            _filing(session, TICKER, url=_url("000000000000000001"), status="fetched")
            _filing(session, TICKER, url=_url("000000000000000002"), status="fetched")
            # Still pending, so it is not held.
            _filing(session, TICKER, url=_url("000000000000000003"), status="pending")
            # A quarterly report is not a shareholders' report.
            _filing(
                session, TICKER, url=_url("000000000000000004"), form="10-Q", status="fetched"
            )
            session.flush()

            documents.refresh_report_flags(session)

            instrument = session.get(Instrument, TICKER)
            assert instrument is not None
            assert instrument.annual_reports == 2
            assert instrument.reports_synced_at is not None

    def test_it_corrects_itself_when_a_document_disappears(self, settings):
        """Derived, not incremented: a run that dies halfway must not inflate it."""
        with session_scope() as session:
            session.add(make_instrument(TICKER, in_universe=True))
            session.flush()
            row = _filing(session, TICKER, url=_url("000000000000000001"), status="fetched")
            session.flush()
            documents.refresh_report_flags(session)
            assert session.get(Instrument, TICKER).annual_reports == 1

            # The document is lost, or turns out never to have been one.
            row.status = "failed"
            session.flush()
            documents.refresh_report_flags(session)

            assert session.get(Instrument, TICKER).annual_reports == 0

    def test_an_instrument_with_nothing_collected_is_zero_not_unknown(self, settings):
        with session_scope() as session:
            session.add(make_instrument(TICKER, in_universe=True))
            session.flush()

            documents.refresh_report_flags(session)

            instrument = session.get(Instrument, TICKER)
            # Zero is a true statement about a fresh install; the timestamp is what
            # says whether anyone has looked.
            assert instrument.annual_reports == 0
            assert instrument.reports_synced_at is not None


class TestReadingADocument:
    """Serving a filing is serving third-party HTML from the dashboard's origin."""

    def _store(self, settings, body=REAL_FILING, status="fetched"):
        url = _url(ACCESSIONS[2026])
        path = documents.document_path(settings, TICKER, url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        with session_scope() as session:
            row = _filing(session, TICKER, url=url, status=status)
            row.raw_path = str(path.relative_to(settings.data_dir))
            row.content_type = "text/html"
            row.doc_hash = "0" * 64
            session.flush()
            return row.id

    def test_the_stored_bytes_are_served(self, client, settings):
        filing_id = self._store(settings)
        response = client.get(f"/filing/{filing_id}/document")

        assert response.status_code == 200
        assert response.content == REAL_FILING
        assert response.headers["content-type"].startswith("text/html")

    def test_it_is_served_under_a_sandbox_policy(self, client, settings):
        """Not merely as a file.

        A filing is untrusted HTML served from an origin that can reach the API and
        therefore the account. `sandbox` puts it in an opaque origin with scripts and
        same-origin reads disabled; `allow-same-origin` would hand back exactly the
        access the policy exists to remove.
        """
        filing_id = self._store(settings)
        response = client.get(f"/filing/{filing_id}/document")

        policy = response.headers["content-security-policy"]
        assert "sandbox" in policy
        assert "allow-same-origin" not in policy
        assert "allow-scripts" not in policy
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_a_filing_with_no_document_is_a_404(self, client, session):
        with session_scope() as scope:
            row = _filing(scope, TICKER, url=_url(ACCESSIONS[2026]), status="pending")
            scope.flush()
            filing_id = row.id

        assert client.get(f"/filing/{filing_id}/document").status_code == 404

    def test_an_unknown_filing_is_a_404(self, client):
        assert client.get("/filing/999999/document").status_code == 404

    def test_a_stored_path_cannot_escape_the_data_directory(self, client, settings):
        """It comes from our own database, but a stored path is still a path."""
        with session_scope() as session:
            row = _filing(session, TICKER, url=_url(ACCESSIONS[2026]), status="fetched")
            row.raw_path = "../../../../etc/passwd"
            session.flush()
            filing_id = row.id

        assert client.get(f"/filing/{filing_id}/document").status_code == 404

    def test_a_row_whose_file_is_gone_is_a_404_rather_than_a_500(self, client, settings):
        filing_id = self._store(settings)
        url = _url(ACCESSIONS[2026])
        documents.document_path(settings, TICKER, url).unlink()

        assert client.get(f"/filing/{filing_id}/document").status_code == 404


class TestTheInstrumentPage:
    def test_it_reports_how_many_reports_are_held(self, client, settings):
        with session_scope() as session:
            session.add(make_instrument(TICKER, in_universe=True))
            session.flush()
            _filing(session, TICKER, url=_url(ACCESSIONS[2026]), status="fetched")
            session.flush()
            documents.refresh_report_flags(session)
            session.commit()

        text = " ".join(client.get(f"/instrument/{TICKER}").text.split())
        assert "Annual reports held:" in text

    def test_a_held_document_offers_a_read_link(self, client, settings):
        url = _url(ACCESSIONS[2026])
        path = documents.document_path(settings, TICKER, url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(REAL_FILING)
        with session_scope() as session:
            row = _filing(session, TICKER, url=url, status="fetched")
            row.raw_path = str(path.relative_to(settings.data_dir))
            session.flush()
            filing_id = row.id
            session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert f"/filing/{filing_id}/document" in body
        assert ">read<" in body

    def test_a_pending_filing_is_not_offered_as_readable(self, client, session):
        with session_scope() as scope:
            row = _filing(scope, TICKER, url=_url(ACCESSIONS[2026]), status="pending")
            scope.flush()
            filing_id = row.id
            scope.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert f"/filing/{filing_id}/document" not in body
        # The original is still reachable, which is the honest thing to offer.
        assert ">source<" in body


class TestDiscoveringTheHistory:
    def _patch(self, monkeypatch, provider, *, entries):
        monkeypatch.setattr(
            "awltux.providers.edgar.EdgarProvider.get_annual_filings",
            lambda self, cik, *, since, limit=12: entries,
        )

    def test_missing_annual_reports_are_added_and_known_ones_are_not(self, settings, monkeypatch):
        entries = [
            {
                "form": "10-K",
                "filing_date": "2026-02-01",
                "accession_number": ACCESSIONS[2026],
                "description": "Annual report",
                "url": _url(ACCESSIONS[2026]),
            },
            {
                "form": "10-K",
                "filing_date": "2025-02-01",
                "accession_number": ACCESSIONS[2025],
                "description": "Annual report",
                "url": _url(ACCESSIONS[2025]),
            },
        ]
        self._patch(monkeypatch, None, entries=entries)

        with session_scope() as session:
            session.add(make_instrument(TICKER, sec_cik="0000320193"))
            # Flushed before the filing is added: `_filing` creates the instrument
            # if it cannot see one, and a pending row is not visible to `session.get`.
            session.flush()
            # The older one is already known, by URL.
            _filing(session, TICKER, url=_url(ACCESSIONS[2025]), filed="2025-02-01")
            session.flush()

            report = documents.deepen_annual_history(session, years=2, settings=settings)

            assert report.discovered == 2
            stored = session.execute(
                Filing.__table__.select().where(Filing.instrument_t212_ticker == TICKER)
            ).all()
            assert len(stored) == 2, "the known filing must not be inserted twice"

    def test_an_annual_filing_records_the_year_it_covers(self, settings, monkeypatch):
        """The period, not the filing date: an annual report is *for* a year.

        Measured before this was written: 0 of 4,958 stored filings had a period.
        The discovery entries carry EDGAR's ``reportDate``, which for a 10-K is the
        fiscal year end -- the citation link from a document to the figures taken
        from it.
        """
        self._patch(
            monkeypatch,
            None,
            entries=[
                {
                    "form": "10-K",
                    "filing_date": "2026-02-01",
                    "report_date": "2025-09-27",
                    "accession_number": ACCESSIONS[2026],
                    "description": "Annual report",
                    "url": _url(ACCESSIONS[2026]),
                }
            ],
        )

        with session_scope() as session:
            session.add(make_instrument(TICKER, sec_cik="0000320193"))
            session.flush()

            documents.deepen_annual_history(session, years=2, settings=settings)

            stored = session.execute(
                Filing.__table__.select().where(Filing.instrument_t212_ticker == TICKER)
            ).all()

        assert len(stored) == 1
        assert stored[0].period_end == dt.date(2025, 9, 27)
        assert stored[0].filed_at.date() == dt.date(2026, 2, 1)

    def test_the_window_is_read_from_the_configuration(self, settings, monkeypatch):
        """Two years for now; the request was six, and this is the one knob."""
        from awltux.config import ReportsConfig

        assert settings.reports.years == 2
        assert ReportsConfig().years == 2
