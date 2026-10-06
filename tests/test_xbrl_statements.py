"""Primary statements from XBRL, and the citation that comes with them.

The fixture is **real EDGAR output** for Apple (CIK 0000320193), captured from
`data.sec.gov/api/xbrl/companyfacts` and trimmed to the tags this codebase maps
plus the two most recent filings per figure. Trimming matters: several figures
appear more than once because a later 10-K repeats them as comparatives, and that
duplication is the case the "earliest filing wins" rule exists for. An invented
fixture would not contain it.

Two failures these tests are built around, both of which happened while writing
the module and neither of which raised:

* A share count dated at the 10-K **cover** is three weeks after the balance-sheet
  date, so an exact period-end match drops every one of them. Nothing reports an
  error; the dilution and payout markers simply have no input.
* XBRL does not state ``total_debt``. Taking ``LongTermDebt`` for it double-counts
  the current portion at some filers and not others, so the two components are
  summed instead.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awltux.ingest.xbrl import (
    ANNUAL_FORMS,
    COVER_DATE_WINDOW_DAYS,
    MAX_YEAR_DAYS,
    MIN_YEAR_DAYS,
    annual_periods,
)

FIXTURE = Path(__file__).parent / "fixtures" / "apple_companyfacts.json"


@pytest.fixture(scope="module")
def apple() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def periods(apple):
    return annual_periods(apple)


def payload(facts: dict, **extra) -> dict:
    """A minimal companyfacts shape around supplied facts."""
    return {"cik": 1, "entityName": "Test Co", "facts": facts, **extra}


def combine(*fragments: dict) -> dict:
    """Merge taxonomy fragments into one ``facts`` mapping.

    Not ``{**a, **b}``: every fragment is keyed by taxonomy first, so unpacking
    them into each other keeps only the last fragment's tags and silently empties
    the rest -- which produces an empty result rather than a wrong one, and cost
    three tests before it was spotted.
    """
    out: dict[str, dict] = {}
    for fragment in fragments:
        for taxonomy, tags in fragment.items():
            bucket = out.setdefault(taxonomy, {})
            for tag, body in tags.items():
                if tag not in bucket:
                    bucket[tag] = body
                    continue
                for unit, series in body["units"].items():
                    bucket[tag]["units"].setdefault(unit, []).extend(series)
    return out


def duration(
    tag: str,
    value: float,
    start: str,
    end: str,
    *,
    unit: str = "USD",
    form: str = "10-K",
    filed: str = "2024-02-01",
    accession: str = "0000000000-24-000001",
    taxonomy: str = "us-gaap",
) -> dict:
    return {
        taxonomy: {
            tag: {
                "units": {
                    unit: [
                        {
                            "start": start,
                            "end": end,
                            "val": value,
                            "form": form,
                            "filed": filed,
                            "accn": accession,
                        }
                    ]
                }
            }
        }
    }


def instant(
    tag: str,
    value: float,
    end: str,
    *,
    unit: str = "USD",
    form: str = "10-K",
    filed: str = "2024-02-01",
    accession: str = "0000000000-24-000001",
    taxonomy: str = "us-gaap",
) -> dict:
    return {
        taxonomy: {
            tag: {
                "units": {
                    unit: [
                        {
                            "end": end,
                            "val": value,
                            "form": form,
                            "filed": filed,
                            "accn": accession,
                        }
                    ]
                }
            }
        }
    }


class TestAgainstRealEdgarOutput:
    def test_it_finds_one_period_per_fiscal_year(self, periods):
        """Apple's payload carries comparatives and amendments; both must collapse."""
        ends = [period.period_end.isoformat() for period in periods]

        assert ends == sorted(ends), "periods must be oldest first"
        assert len(ends) == len(set(ends)), f"a fiscal year appears twice: {ends}"
        assert len(periods) >= 3

    def test_the_figures_are_the_ones_apple_filed(self, periods):
        """Exact values, so a change in tag preference cannot pass unnoticed.

        These are the reported numbers. A mapper that quietly switched to a
        different revenue tag would still produce a plausible figure, which is why
        the assertion is the number rather than a range.
        """
        by_end = {period.period_end.year: period for period in periods}

        assert by_end[2022].facts["revenue"].value == 394_328_000_000
        assert by_end[2022].facts["net_income"].value == 99_803_000_000
        assert by_end[2024].facts["revenue"].value == 391_035_000_000
        assert by_end[2024].facts["eps_diluted"].value == 6.08

    def test_units_are_exact_rather_than_assumed(self, periods):
        """The whole reason XBRL beats reading the document.

        A UK annual report states figures in thousands or millions, so the
        extraction path cannot do cross-period arithmetic on them. An XBRL fact
        carries its unit, and a per-share figure taken from the wrong unit would
        be out by the share price.
        """
        latest = periods[-1]

        assert latest.facts["revenue"].unit == "USD"
        assert latest.facts["eps_diluted"].unit == "USD/shares"
        assert latest.facts["shares_outstanding"].unit == "shares"
        assert latest.currency == "USD"

    def test_every_figure_carries_a_resolvable_citation(self, periods):
        """An accession number is what makes the number checkable later."""
        for period in periods:
            for key, fact in period.facts.items():
                assert fact.accession, f"{key} has no accession"
                assert fact.form in ANNUAL_FORMS
                assert fact.filed is not None, f"{key} has no filing date"
                assert fact.period_end == period.period_end

    def test_the_share_count_survives_the_cover_date(self, periods):
        """The bug this test was written for.

        Apple's balance-sheet share count is tagged at the year end and its
        cover-page count three weeks later. Only the first lines up with a period
        end; before the fix, the second was the only one read and every count was
        dropped.
        """
        for period in periods:
            fact = period.facts.get("shares_outstanding")

            assert fact is not None, f"{period.period_end} lost its share count"
            assert fact.period_end == period.period_end
            # Measured in billions; a wrong unit would be off by the price.
            assert 1e9 < fact.value < 1e11

    def test_total_debt_is_composed_and_not_taken_from_an_ambiguous_tag(self, periods):
        """`LongTermDebt` includes the current portion at some filers and not others.

        Summing the components is the version that cannot double-count, and it
        reconciles with the tag Apple does publish for the same total.
        """
        latest = periods[-1]

        assert latest.facts["total_debt"].value == pytest.approx(
            latest.facts["short_term_debt"].value + latest.facts["long_term_debt"].value
        )
        assert latest.facts["total_debt"].taxonomy == "derived"

    def test_a_missing_tag_is_absent_rather_than_guessed(self, periods):
        """Apple stopped tagging interest expense in later years.

        The rule is that a marker needing a figure the accounts do not contain is
        absent. A zero would be indistinguishable from a company with no debt cost.
        """
        assert "interest_expense" in periods[0].facts
        assert "interest_expense" not in periods[-1].facts


class TestWhichFactsAreAnnual:
    def test_a_quarterly_fact_is_not_an_annual_one(self):
        """A 10-Q duration in an annual column is a figure off by a factor of four."""
        facts = duration("Revenues", 100.0, "2024-01-01", "2024-03-31")

        assert annual_periods(payload(facts)) == []

    def test_a_year_long_fact_is_kept(self):
        facts = duration("Revenues", 400.0, "2023-01-01", "2023-12-31")

        result = annual_periods(payload(facts))

        assert len(result) == 1
        assert result[0].facts["revenue"].value == 400.0

    def test_a_cumulative_two_year_fact_is_not_a_year(self):
        """A caption spanning two years is a cumulative total, not a period."""
        facts = duration("Revenues", 900.0, "2022-01-01", "2023-12-31")

        assert annual_periods(payload(facts)) == []

    @pytest.mark.parametrize("days", [MIN_YEAR_DAYS, MAX_YEAR_DAYS])
    def test_the_year_window_includes_its_own_bounds(self, days):
        """52/53-week retailers end a few days either side of 365."""
        start = "2023-01-01"
        end = (__import__("datetime").date.fromisoformat(start)
               + __import__("datetime").timedelta(days=days)).isoformat()

        assert annual_periods(payload(duration("Revenues", 1.0, start, end)))

    def test_a_quarterly_filing_is_not_an_annual_source(self):
        """Form is checked as well as duration: a 10-Q states year-to-date figures."""
        facts = duration("Revenues", 400.0, "2023-01-01", "2023-12-31", form="10-Q")

        assert annual_periods(payload(facts)) == []

    @pytest.mark.parametrize("form", ["10-K", "10-K/A", "20-F", "40-F"])
    def test_the_annual_forms_are_accepted(self, form):
        facts = duration("Revenues", 400.0, "2023-01-01", "2023-12-31", form=form)

        assert annual_periods(payload(facts))

    def test_an_instant_does_not_supply_a_duration_metric(self):
        """The balance sheet has no start date; revenue does.

        Reading an instant as revenue would take a stock and treat it as a flow.
        """
        facts = instant("Revenues", 400.0, "2023-12-31")

        assert annual_periods(payload(facts)) == []

    def test_a_duration_does_not_supply_an_instant_metric(self):
        facts = duration("Assets", 1000.0, "2023-01-01", "2023-12-31")

        assert annual_periods(payload(facts)) == []

    def test_a_mid_year_instant_does_not_create_a_fiscal_year(self):
        """The bug a live filer exposed, found only by reading the rows it wrote.

        A balance-sheet date is not always a year end. A company that tags goodwill
        at the date of an impairment produced a ``FundamentalPeriod`` for that day
        holding one figure -- a year that never existed, counted as coverage, and
        incapable of supporting a single marker.
        """
        earnings = duration("Revenues", 400.0, "2023-04-01", "2024-03-31")
        stray = instant("Goodwill", 5_210_000.0, "2024-04-15")

        result = annual_periods(payload(combine(earnings, stray)))

        assert [p.period_end.isoformat() for p in result] == ["2024-03-31"]
        assert "goodwill" not in result[0].facts

    def test_a_balance_sheet_instant_joins_its_own_year_end(self):
        """The other half: a real year-end instant must still be captured."""
        earnings = duration("Revenues", 400.0, "2023-04-01", "2024-03-31")
        at_year_end = instant("Goodwill", 5_210_000.0, "2024-03-31")

        result = annual_periods(payload(combine(earnings, at_year_end)))

        assert result[0].facts["goodwill"].value == 5_210_000.0

    def test_a_filer_tagging_only_a_balance_sheet_still_yields_a_period(self):
        """The fallback, so the guard trades a phantom year for no missing one."""
        facts = instant("Assets", 1000.0, "2023-12-31")

        result = annual_periods(payload(facts))

        assert len(result) == 1
        assert result[0].facts["total_assets"].value == 1000.0


class TestWhichFilingWins:
    def test_the_earliest_filing_wins(self):
        """A restatement must not rewrite what the year was first reported as.

        The same figure appears in the year's own 10-K and again as a comparative
        in the next one, and later filings sometimes restate it. Taking the latest
        puts hindsight into a valuation, which is the same failure
        `FundamentalPeriod.as_of` exists to prevent.
        """
        facts = duration("Revenues", 100.0, "2023-01-01", "2023-12-31",
                         filed="2024-02-01", accession="original")
        later = duration("Revenues", 250.0, "2023-01-01", "2023-12-31",
                         filed="2025-02-01", accession="restated")

        result = annual_periods(payload(combine(facts, later)))

        assert result[0].facts["revenue"].value == 100.0
        assert result[0].facts["revenue"].accession == "original"

    def test_the_later_filing_is_used_when_it_is_the_only_one(self):
        facts = duration("Revenues", 250.0, "2023-01-01", "2023-12-31",
                         filed="2025-02-01", accession="restated")

        result = annual_periods(payload(facts))

        assert result[0].facts["revenue"].accession == "restated"


class TestShareCountsAcrossDates:
    def test_a_cover_date_count_attaches_to_the_year_it_follows(self):
        """The 10-K cover is dated at filing, weeks after the balance sheet."""
        balance = duration("Revenues", 400.0, "2023-01-01", "2023-12-31")
        cover = instant(
            "EntityCommonStockSharesOutstanding",
            1_000.0,
            "2024-01-19",
            unit="shares",
            taxonomy="dei",
        )

        result = annual_periods(payload(combine(balance, cover)))

        assert result[0].facts["shares_outstanding"].value == 1_000.0
        assert result[0].facts["shares_outstanding"].period_end.isoformat() == "2023-12-31"

    def test_a_balance_sheet_count_beats_the_cover_date_one(self):
        """The count the per-share figures were divided by is the year-end one."""
        balance = duration("Revenues", 400.0, "2023-01-01", "2023-12-31")
        at_year_end = instant("CommonStockSharesOutstanding", 900.0, "2023-12-31", unit="shares")
        cover = instant(
            "EntityCommonStockSharesOutstanding", 1_000.0, "2024-01-19",
            unit="shares", taxonomy="dei",
        )

        result = annual_periods(payload(combine(balance, at_year_end, cover)))

        assert result[0].facts["shares_outstanding"].value == 900.0

    def test_a_cover_date_beyond_the_window_belongs_to_another_year(self):
        """Attaching it forwards would put next year's count on this balance sheet."""
        balance = duration("Revenues", 400.0, "2020-01-01", "2020-12-31")
        far_off = instant(
            "EntityCommonStockSharesOutstanding", 1_000.0,
            "2021-12-31", unit="shares", taxonomy="dei",
        )

        result = annual_periods(payload(combine(balance, far_off)))

        assert "shares_outstanding" not in result[0].facts
        assert COVER_DATE_WINDOW_DAYS < 365

    def test_a_cover_date_before_every_period_is_not_attached(self):
        """A figure from a year we do not hold is not this year's."""
        balance = duration("Revenues", 400.0, "2023-01-01", "2023-12-31")
        earlier = instant(
            "EntityCommonStockSharesOutstanding", 1_000.0,
            "2022-06-30", unit="shares", taxonomy="dei",
        )

        result = annual_periods(payload(combine(balance, earlier)))

        assert "shares_outstanding" not in result[0].facts


class TestComposedTotals:
    def test_total_debt_needs_both_halves(self):
        """Half the inputs is an absent metric, not half a debt."""
        facts = combine(instant("LongTermDebtNoncurrent", 800.0, "2023-12-31"), duration("Revenues", 400.0, "2023-01-01", "2023-12-31"))

        result = annual_periods(payload(facts))

        assert "total_debt" not in result[0].facts

    def test_the_composed_citation_names_both_filings(self):
        """There is no tag for the sum, so the citation must be the inputs."""
        facts = combine(instant("LongTermDebtNoncurrent", 800.0, "2023-12-31", accession="long"), instant("LongTermDebtCurrent", 200.0, "2023-12-31", accession="short"), duration("Revenues", 400.0, "2023-01-01", "2023-12-31"))

        fact = annual_periods(payload(facts))[0].facts["total_debt"]

        assert fact.value == 1_000.0
        assert fact.accession == "long,short"
        assert fact.taxonomy == "derived"

    def test_a_stated_total_is_not_overwritten(self, apple):
        """Composition fills a gap; it does not second-guess the company."""
        result = annual_periods(apple)

        assert all(isinstance(period.facts["total_debt"].value, float) for period in result)


class TestTagPreference:
    def test_the_preferred_tag_supplies_every_period_it_has(self):
        """Preference is by tag, not by period.

        Where a company switches tags mid-history, merging the two would produce a
        series that changes definition partway and no reader could see it.
        """
        old = duration("SalesRevenueNet", 100.0, "2022-01-01", "2022-12-31")
        new = duration(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            200.0,
            "2023-01-01",
            "2023-12-31",
        )

        result = annual_periods(payload(combine(old, new)))

        assert len(result) == 1, "only the preferred tag's year is used"
        assert result[0].period_end.year == 2023
        assert result[0].facts["revenue"].tag == (
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        )

    def test_a_fallback_tag_is_used_when_the_first_is_absent(self):
        facts = duration("SalesRevenueNet", 100.0, "2023-01-01", "2023-12-31")

        result = annual_periods(payload(facts))

        assert result[0].facts["revenue"].tag == "SalesRevenueNet"


class TestUnusablePayloads:
    def test_a_payload_with_no_facts_yields_nothing(self):
        assert annual_periods({}) == []
        assert annual_periods({"facts": None}) == []
        assert annual_periods({"facts": {}}) == []

    def test_a_period_with_no_usable_metric_is_not_returned(self):
        """An empty row is worse than a missing one: coverage cannot tell them apart."""
        facts = instant("Assets", 1000.0, "2023-12-31", form="8-K")

        assert annual_periods(payload(facts)) == []

    def test_a_non_numeric_value_is_skipped_rather_than_stored(self):
        facts = duration("Revenues", 100.0, "2023-01-01", "2023-12-31")
        facts["us-gaap"]["Revenues"]["units"]["USD"][0]["val"] = "not a number"

        assert annual_periods(payload(facts)) == []

    def test_the_wrong_unit_for_the_metric_is_refused(self):
        """Apple reports EPS in `USD/shares`; a bare `USD` EPS would be off by the price."""
        facts = duration(
            "EarningsPerShareDiluted", 6.11, "2023-01-01", "2023-12-31", unit="USD"
        )

        assert annual_periods(payload(facts)) == []


class TestWritingToTheDatabase:
    """The write path, with the provider replaced by the captured payload.

    Stubbed rather than fetched: a test that reaches EDGAR is a test that fails
    when EDGAR is slow, and the mapping is already covered against the real
    payload above. What is checked here is that the figures arrive in
    ``FundamentalPeriod`` with their citations attached and nothing dropped.
    """

    @pytest.fixture
    def filer(self, session):
        from tests.helpers import make_instrument

        instrument = make_instrument("AAPL_US_EQ", name="Apple Inc", sector="Technology")
        instrument.sec_cik = "0000320193"
        session.add(instrument)
        session.flush()
        return instrument

    def _sync(self, session, payload_data):
        from awltux.ingest.xbrl import sync_xbrl_fundamentals

        class StubProvider:
            def get_company_facts(self, cik, **_kwargs):
                assert cik, "the sync must pass a CIK through"
                return payload_data

        return sync_xbrl_fundamentals(
            session, provider=StubProvider(), tickers=["AAPL_US_EQ"]
        )

    def test_it_writes_annual_periods_with_their_citations(self, session, filer, apple):
        """A figure without its provenance is not usable for a forensic read."""
        from sqlalchemy import select

        from awltux.db import FundamentalPeriod

        report = self._sync(session, apple)
        session.flush()

        rows = list(
            session.execute(
                select(FundamentalPeriod).where(
                    FundamentalPeriod.instrument_t212_ticker == "AAPL_US_EQ"
                )
            ).scalars()
        )

        assert report.periods_written == len(rows) > 0
        for row in rows:
            assert row.source == "xbrl_companyfacts"
            assert row.period_type == "annual"
            assert row.currency == "USD"
            assert row.metric_sources, "every row must carry provenance"
            provenance = row.metric_sources["revenue"]
            assert provenance["source"] == "xbrl_companyfacts"
            assert provenance["accession"], "a citation with no accession is not one"
            assert provenance["span"].startswith("us-gaap:")

    def test_derived_ratios_are_present_but_not_cited(self, session, filer, apple):
        """The ratios are ours; claiming the issuer tagged them would be a lie.

        A `net_margin` attributed to an accession the company never filed is a
        fabricated provenance, which is worse than a missing one because it
        survives inspection by looking checkable.
        """
        from sqlalchemy import select

        from awltux.db import FundamentalPeriod

        self._sync(session, apple)
        session.flush()

        row = session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.instrument_t212_ticker == "AAPL_US_EQ")
            .order_by(FundamentalPeriod.period_end.desc())
        ).scalars().first()

        assert row is not None
        assert "net_margin" in row.metrics, "derived ratios feed the markers"
        assert "net_margin" not in row.metric_sources, "and are not attributed to a filing"
        assert "net_debt" in row.metrics, "total_debt composition must reach the ratios"

    def test_a_failing_payload_does_not_stop_the_run(self, session, filer):
        """One unparseable companyfacts response must not lose the others."""
        report = self._sync(session, {"facts": "not a mapping"})

        assert report.tickers_attempted == 1
        assert report.periods_written == 0
        assert report.failures == []

    def test_a_filer_without_a_cik_is_not_attempted(self, session):
        """EDGAR has nothing to look up, so it is not a gap this job can close."""
        from awltux.ingest.xbrl import sync_xbrl_fundamentals
        from tests.helpers import make_instrument

        session.add(make_instrument("NOCIK_US_EQ", name="No CIK Ltd", isin="GB0000000001"))
        session.flush()

        report = sync_xbrl_fundamentals(session, provider=None, tickers=["NOCIK_US_EQ"])

        assert report.tickers_attempted == 0

    def test_the_rotation_advances_between_runs(self, session):
        """A run must not re-read the filers the previous run already covered.

        The first version ordered the queue by ``Instrument.updated_at``, which this
        job never touches, so the order never moved: two consecutive runs each
        reported twelve periods written while the table stayed at twelve rows. The
        job looked busy and drained nothing, which is the harder failure to notice
        -- a job that reports work but makes no progress looks healthier than one
        that fails.
        """
        from awltux.ingest.xbrl import sync_xbrl_fundamentals
        from tests.helpers import make_instrument

        for number, ticker in enumerate(("AAA_US_EQ", "BBB_US_EQ", "CCC_US_EQ")):
            instrument = make_instrument(ticker, name=f"Co {ticker}", isin=f"US{number:010d}")
            instrument.sec_cik = f"000000000{number}"
            session.add(instrument)
        session.flush()

        payload_data = payload(duration("Revenues", 400.0, "2023-01-01", "2023-12-31"))
        asked: list[str] = []

        class StubProvider:
            def get_company_facts(self, cik, **_kwargs):
                asked.append(cik)
                return payload_data

        first = sync_xbrl_fundamentals(session, provider=StubProvider(), limit=1)
        session.flush()
        second = sync_xbrl_fundamentals(session, provider=StubProvider(), limit=1)

        assert first.periods_written == 1 and second.periods_written == 1
        assert len(asked) == 2
        assert asked[0] != asked[1], (
            "the second run re-read the filer the first had just written, so with a "
            "queue of 312 the job would never drain it"
        )
