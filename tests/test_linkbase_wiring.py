"""Reading a filing's linkbase from EDGAR, keeping it, and showing it on the page.

The parser and the reconciliation are tested in `test_linkbase.py` against DFPH's real
document. What is under test here is the wiring that was missing: the fetch by CIK and
accession, the stored copy the page reads instead of making a request, and the accounts
page rendering the filer's declared subtotals.

Offline throughout: the provider is a stub, because a test that reaches EDGAR is a bug.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from awltux.db import AppSetting, FundamentalPeriod
from awltux.ingest import linkbase as linkbases
from tests.helpers import make_instrument

CAL = Path(__file__).parent / "fixtures" / "dac-20251231_cal.xml"
ACCESSION = "0001104659-26-021574"


class StubEdgar:
    """The two calls :func:`linkbases.fetch` makes, and nothing else.

    Records what it was asked for, because "did it use the accession it was given" is
    the part of this that a wrong answer would still pass without.
    """

    def __init__(self, *, names: list[str] | None = None, document: bytes | None = None):
        self.names = names if names is not None else ["dac-20251231_cal.xml", "a.htm"]
        self.document = document if document is not None else CAL.read_bytes()
        self.index_calls: list[tuple] = []
        self.document_calls: list[tuple] = []

    def get_filing_index(self, cik, accession, **_kwargs):
        self.index_calls.append((cik, accession))
        return self.names

    def document_url(self, cik, accession, name=""):
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"

    def fetch_document(self, url, **_kwargs):
        self.document_calls.append(url)
        return type("Document", (), {"url": url, "body": self.document})()


class TestFindingTheDocument:
    def test_it_finds_the_calculation_linkbase_by_its_suffix(self):
        assert linkbases.find_calculation(["a.htm", "dac-20251231_cal.xml"]) == (
            "dac-20251231_cal.xml"
        )

    def test_a_filing_without_one_says_so_rather_than_guessing(self):
        """Filers are not required to publish one, and a guessed name is a 404."""
        assert linkbases.find_calculation(["a.htm", "b.xml"]) is None


class TestFetching:
    def test_it_reads_the_linkbase_for_the_accession_it_was_given(self):
        provider = StubEdgar()

        linkbase, name = linkbases.fetch(provider, cik="1369241", accession=ACCESSION)

        assert name == "dac-20251231_cal.xml"
        assert provider.index_calls == [("1369241", ACCESSION)]
        assert provider.document_calls == [
            f"https://www.sec.gov/Archives/edgar/data/1369241/{ACCESSION}/"
            "dac-20251231_cal.xml"
        ]
        assert linkbase is not None and linkbase.calculations

    def test_the_real_document_declares_the_children_that_closed_the_gap(self):
        """Danaos's own balance sheet, and the two captions this app did not read.

        `AssetsCurrent` is out by 48,843,000 in our figures, and the filer declares it as
        six lines: the four we hold plus `OtherReceivablesNetCurrent` and
        `PrepaidExpenseCurrent`. `OtherAssetsCurrent` is a *sibling* of both, which is why
        adding `PrepaidExpenseCurrent` to it is right here and wrong for the filers whose
        linkbase declares `PrepaidExpenseAndOtherAssetsCurrent` as the whole bucket.
        """
        linkbase, _name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        assert linkbase is not None
        [current] = linkbase.for_parent("us-gaap:AssetsCurrent")

        assert [tag for tag, _weight in current.children] == [
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "us-gaap:AccountsReceivableNetCurrent",
            "us-gaap:InventoryNet",
            "us-gaap:PrepaidExpenseCurrent",
            "us-gaap:OtherReceivablesNetCurrent",
            "us-gaap:OtherAssetsCurrent",
        ]

    def test_a_filing_that_publishes_none_is_not_an_error(self):
        provider = StubEdgar(names=["a.htm"])

        linkbase, name = linkbases.fetch(provider, cik="1", accession=ACCESSION)

        assert linkbase is None
        assert name == ""
        assert provider.document_calls == [], "it must not fetch a document it cannot name"


class TestKeepingIt:
    def test_a_stored_linkbase_round_trips_with_its_filename(self, session):
        """The page reads SQLite; the filename is the citation it prints.

        Compared on ``calculations`` rather than on the whole object, because
        ``bytes_read`` is a fact about the parse and a stored copy has no bytes --
        `test_linkbase.py` draws the same line for the same reason.
        """
        linkbase, name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)

        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        stored, stored_name = linkbases.stored(session, ACCESSION)
        assert stored.calculations == linkbase.calculations
        assert stored_name == "dac-20251231_cal.xml"
        row = session.get(AppSetting, linkbases.setting_key(ACCESSION))
        assert row is not None and row.value["cik"] == "1369241"

    def test_storing_it_twice_replaces_rather_than_duplicates(self, session):
        linkbase, name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        rows = session.query(AppSetting).filter(
            AppSetting.key == linkbases.setting_key(ACCESSION)
        ).all()

        assert len(rows) == 1

    def test_nothing_stored_is_none_rather_than_an_empty_linkbase(self, session):
        """An empty tree would render as "the filer declares nothing", which is a claim."""
        assert linkbases.stored(session, ACCESSION) is None
        assert linkbases.stored(session, "") is None

    def test_forgetting_it_is_possible(self, session):
        """A wrong read must not be permanent."""
        linkbase, name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")

        assert linkbases.forget(session, ACCESSION) is True
        assert linkbases.stored(session, ACCESSION) is None
        assert linkbases.forget(session, ACCESSION) is False


class TestThePage:
    @pytest.fixture
    def filer(self, session):
        """Danaos, with the period as stored: the figures 22a27aa produced."""
        instrument = make_instrument("DAC_US_EQ", name="Danaos", sector="Industrials")
        instrument.sec_cik = "0001369241"
        session.add(instrument)
        session.flush()
        return instrument

    def _period(self, session) -> FundamentalPeriod:
        metrics = {
            "total_assets": 5_113_930_000.0,
            "current_assets": 1_319_419_000.0,
            "current_liabilities": 401_676_000.0,
            "total_liabilities": 1_318_353_000.0,
            "cash_and_equivalents": 1_037_292_000.0,
            "receivables": 38_730_000.0,
            "inventory": 23_417_000.0,
            "other_current_assets": 217_887_000.0,
            "net_ppe": 3_269_703_000.0,
            "other_noncurrent_assets": 42_305_000.0,
        }
        spans = {
            "total_assets": "us-gaap:Assets",
            "current_assets": "us-gaap:AssetsCurrent",
            "current_liabilities": "us-gaap:LiabilitiesCurrent",
            "total_liabilities": "us-gaap:Liabilities",
            "cash_and_equivalents": "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            "receivables": "us-gaap:AccountsReceivableNetCurrent",
            "inventory": "us-gaap:InventoryNet",
            "other_current_assets": "us-gaap:OtherAssetsCurrent+OtherReceivablesNetCurrent",
            "net_ppe": "us-gaap:PropertyPlantAndEquipmentNet",
            "other_noncurrent_assets": "us-gaap:OtherAssetsNoncurrent",
        }
        period = FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2025, 12, 31),
            period_type="annual",
            source="xbrl_companyfacts",
            currency="USD",
            metrics=metrics,
            metric_sources={
                metric: {"value": metrics[metric], "span": span, "accession": ACCESSION}
                for metric, span in spans.items()
            },
        )
        session.add(period)
        session.commit()
        return period

    def test_it_offers_to_read_the_filings_arithmetic(self, client, session, filer):
        period = self._period(session)

        body = client.get(f"/accounts/{period.id}/health").text

        assert "Not read yet" in body
        assert f'action="/accounts/{period.id}/linkbase"' in body

    def test_a_stored_linkbase_is_shown_as_declared_subtotals(self, client, session, filer):
        period = self._period(session)
        linkbase, name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        session.commit()

        body = " ".join(client.get(f"/accounts/{period.id}/health").text.split())

        assert "The filer&#39;s own arithmetic" in body or "filer" in body.lower()
        assert "Declared: us-gaap:AssetsCurrent" in body
        assert "no figure for OtherReceivablesNetCurrent" not in body, (
            "we hold that caption now — it is a sibling inside other_current_assets"
        )
        assert "PrepaidExpenseCurrent" in body, "the line we still do not hold is named"
        assert "dac-20251231_cal.xml" in body

    def test_the_page_reads_sqlite_and_makes_no_request(self, client, session, filer, monkeypatch):
        """A render must not fetch: the POST is where the network call lives.

        Patched at the provider class itself rather than at the route module's namespace,
        which is where the route imports it from -- a patch that lands nowhere would let
        this pass while the page happily phoned EDGAR.
        """
        period = self._period(session)
        linkbase, name = linkbases.fetch(StubEdgar(), cik="1369241", accession=ACCESSION)
        linkbases.save(session, ACCESSION, linkbase, source=name, cik="1369241")
        session.commit()

        def explode(*_args, **_kwargs):
            raise AssertionError("the accounts page fetched from EDGAR")

        monkeypatch.setattr("awltux.providers.edgar.EdgarProvider", explode)

        body = client.get(f"/accounts/{period.id}/health").text

        assert "dac-20251231_cal.xml" in body, "and it renders what it has stored"

    def test_reading_it_stores_it_and_says_so(self, client, session, filer, monkeypatch):
        period = self._period(session)
        provider = StubEdgar()
        monkeypatch.setattr(
            "awltux.providers.edgar.EdgarProvider", lambda *a, **k: provider
        )

        response = client.post(f"/accounts/{period.id}/linkbase", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"] == (
            f"/accounts/{period.id}/health?linkbase=read#filer-arithmetic"
        )
        assert linkbases.stored(session, ACCESSION) is not None

    def test_a_failure_is_reported_rather_than_500ing(self, client, session, filer, monkeypatch):
        from awltux.providers.edgar import ProviderError

        period = self._period(session)

        class Broken:
            def get_filing_index(self, *_args, **_kwargs):
                raise ProviderError("edgar", "the SEC refused us")

        monkeypatch.setattr("awltux.providers.edgar.EdgarProvider", lambda *a, **k: Broken())

        response = client.post(f"/accounts/{period.id}/linkbase", follow_redirects=False)

        assert response.status_code == 303
        assert "linkbase=failed" in response.headers["location"]

    def test_a_period_with_no_accession_says_which_case_it_is(self, client, session, filer):
        """A Yahoo or model-read period has no filing to read, and that is not a failure."""
        period = FundamentalPeriod(
            instrument_t212_ticker="DAC_US_EQ",
            period_end=dt.date(2024, 12, 31),
            period_type="annual",
            source="yahoo_statements",
            currency="USD",
            metrics={"total_assets": 1.0},
            metric_sources=None,
        )
        session.add(period)
        session.commit()

        body = client.get(f"/accounts/{period.id}/health").text

        assert "no accession" in body
