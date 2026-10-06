"""Accounting-quality markers.

The tests are weighted towards two properties rather than towards arithmetic:

* **a marker must carry its inputs**, because the failure mode of every tool in
  this area is a number that reads as a verdict;
* **a marker must be absent rather than estimated** when its inputs are missing,
  because a zero-filled or guessed input is indistinguishable from a real one
  once it is in a ranking.

The arithmetic tests are here too, but the arithmetic is the easy part.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis.accounting import (
    Marker,
    accrual_marker,
    altman_inputs_marker,
    analyse,
    beneish_inputs_marker,
    cash_conversion_marker,
    goodwill_intensity_marker,
    gross_profitability_marker,
    inventory_drift_marker,
    piotroski_marker,
    receivables_drift_marker,
)
from awltux.analysis.fundamental import build_snapshot
from tests.helpers import make_period


def _series(*years: dict[str, float]) -> list:
    """Annual periods, oldest first, ending 2024-12-31."""
    out = []
    for offset, metrics in enumerate(years):
        end = dt.date(2024 - (len(years) - 1 - offset), 12, 31)
        out.append(make_period("T", end, metrics))
    return out


def _year(
    net_income: float = 100.0,
    cfo: float = 120.0,
    assets: float = 1_000.0,
    **extra: float,
) -> dict[str, float]:
    metrics = {
        "net_income": net_income,
        "operating_cash_flow": cfo,
        "total_assets": assets,
    }
    metrics.update(extra)
    return metrics


class TestAccrualMarker:
    def test_the_cash_flow_method_is_the_identity(self):
        """(net income - operating cash flow) / total assets."""
        marker = accrual_marker(_series(_year(net_income=100.0, cfo=120.0, assets=1_000.0)))
        assert marker is not None
        assert marker.value == pytest.approx(-0.02)
        assert marker.unit == "ratio"
        assert marker.tier == "A"

    def test_the_average_spans_the_periods_rather_than_using_one(self):
        """The note's claim is about persistence, so the headline is the average and
        the individual years are inputs."""
        marker = accrual_marker(
            _series(_year(assets=1_000.0), _year(assets=1_200.0))
        )
        assert marker is not None
        # 2023 is divided by closing assets (1,000) and 2024 by the average (1,100).
        assert marker.value == pytest.approx((-0.02 + (-20.0 / 1_100.0)) / 2)

    def test_the_inputs_are_carried_on_the_marker(self):
        marker = accrual_marker(_series(_year(), _year()))
        assert marker is not None
        assert marker.inputs["by_period"] == {
            "2023-12-31": pytest.approx(-0.02),
            "2024-12-31": pytest.approx(-0.02),
        }
        assert marker.inputs["method"] == "net income less operating cash flow"

    def test_the_first_period_states_that_it_used_closing_assets(self):
        """A company that bought a business mid-year would otherwise be divided by
        a denominator that never existed, without saying so."""
        marker = accrual_marker(_series(_year()))
        assert marker is not None
        basis = marker.inputs["denominator_used"]["2024-12-31"]
        assert "closing" in basis
        marker_two = accrual_marker(_series(_year(), _year()))
        assert marker_two is not None
        assert (
            marker_two.inputs["denominator_used"]["2024-12-31"] == "average total assets"
        )

    def test_a_short_series_says_it_is_not_a_trend(self):
        marker = accrual_marker(_series(_year(), _year()))
        assert marker is not None
        assert "not yet a trend" in marker.reading

    def test_a_long_series_is_reported_as_an_average(self):
        marker = accrual_marker(_series(_year(), _year(), _year(), _year()))
        assert marker is not None
        assert marker.inputs["periods"] == 4
        assert "not yet a trend" not in marker.reading

    def test_the_reading_says_which_way_round_it_is(self):
        good = accrual_marker(_series(_year(net_income=100.0, cfo=160.0)))
        bad = accrual_marker(_series(_year(net_income=100.0, cfo=40.0)))
        assert good is not None and bad is not None
        assert "operating cash flow exceeded profit" in good.reading
        assert "profit exceeded operating cash flow" in bad.reading

    def test_a_missing_input_makes_the_marker_absent_rather_than_wrong(self):
        assert accrual_marker(_series({"net_income": 100.0, "total_assets": 1_000.0})) is None
        assert accrual_marker(_series({"operating_cash_flow": 100.0})) is None
        assert accrual_marker([]) is None

    def test_an_unusable_number_is_treated_as_missing(self):
        for bad in (float("nan"), float("inf"), "not a number"):
            assert accrual_marker(_series(_year(total_assets=bad))) is None

    def test_zero_assets_do_not_produce_an_infinite_ratio(self):
        assert accrual_marker(_series(_year(assets=0.0))) is None

    def test_the_caveat_travels_with_the_marker(self):
        marker = accrual_marker(_series(_year()))
        assert marker is not None
        assert "not a short signal" in marker.caveat


class TestCashConversionMarker:
    def test_the_average_is_the_marker_and_the_year_is_an_input(self):
        marker = cash_conversion_marker(
            _series(
                _year(net_income=100.0, cfo=50.0),
                _year(net_income=100.0, cfo=100.0),
                _year(net_income=100.0, cfo=150.0),
            )
        )
        assert marker is not None
        assert marker.value == pytest.approx(1.0)
        assert marker.inputs["latest"] == pytest.approx(1.5)
        assert marker.inputs["periods"] == 3

    def test_the_trend_is_computed_over_three_or_more_periods(self):
        marker = cash_conversion_marker(
            _series(
                _year(net_income=100.0, cfo=40.0),
                _year(net_income=100.0, cfo=50.0),
                _year(net_income=100.0, cfo=150.0),
                _year(net_income=100.0, cfo=160.0),
            )
        )
        assert marker is not None
        assert marker.inputs["trend"] > 0
        assert "rising" in marker.reading

    def test_a_loss_making_period_is_excluded_not_clamped(self):
        """The ratio is meaningless for a loss, and a negative one reads as
        'terrible conversion' for a business that is simply unprofitable."""
        marker = cash_conversion_marker(
            _series(_year(net_income=-50.0, cfo=20.0), _year(net_income=100.0, cfo=120.0))
        )
        assert marker is not None
        assert marker.inputs["periods"] == 1

    def test_no_profitable_period_means_no_marker(self):
        assert cash_conversion_marker(_series(_year(net_income=-50.0, cfo=20.0))) is None

    def test_the_caveat_names_the_serial_acquirer_hole(self):
        marker = cash_conversion_marker(_series(_year()))
        assert marker is not None
        assert "serial acquirer" in marker.caveat


class TestAnalyse:
    def test_every_applicable_marker_is_returned(self):
        """Piotroski and the Beneish indices always appear; the rest need inputs.

        Piotroski is nine named questions, so it is produced whenever there is a
        period at all -- several answers being "the accounts do not say" is the
        marker working, not a reason to withhold it. TATA is computable from the
        three figures `_year` supplies, which is enough for the index list.
        """
        markers = analyse(_series(_year(), _year(), _year()))
        assert {marker.name for marker in markers} == {
            "accrual_ratio",
            "cash_conversion",
            "piotroski",
            "beneish_inputs",
        }

    def test_markers_are_unique_by_name(self):
        names = [marker.name for marker in analyse(_series(_year(), _year()))]
        assert len(names) == len(set(names))

    def test_no_periods_means_no_markers(self):
        assert analyse([]) == []

    def test_the_marker_shape_is_serialisable_with_its_inputs(self):
        marker = Marker(
            name="x", label="X", tier="A", unit="ratio", value=1.0, reading="r", inputs={"a": 1.0}
        )
        assert marker.as_dict()["inputs"] == {"a": 1.0}


class TestFlagsFromMarkers:
    """The flags key off persistence and direction, never off a magnitude."""

    def test_persistently_positive_accruals_are_flagged(self):
        snapshot = build_snapshot(
            _series(
                _year(net_income=100.0, cfo=60.0),
                _year(net_income=100.0, cfo=70.0),
                _year(net_income=100.0, cfo=80.0),
            )
        )
        assert any("exceeded operating cash flow in every one" in flag for flag in snapshot.red_flags)

    def test_one_year_of_positive_accruals_is_not_a_flag(self):
        """One year's working-capital swing is noise, and flagging it would be the
        conventional one-period error this work exists to remove."""
        snapshot = build_snapshot(_series(_year(net_income=100.0, cfo=60.0)))
        assert not any("operating cash flow" in flag for flag in snapshot.red_flags)

    def test_persistently_weak_conversion_is_flagged(self):
        snapshot = build_snapshot(
            _series(
                _year(net_income=100.0, cfo=40.0),
                _year(net_income=100.0, cfo=50.0),
                _year(net_income=100.0, cfo=60.0),
            )
        )
        assert any("converted to cash on average" in flag for flag in snapshot.red_flags)

    def test_persistently_strong_conversion_is_a_positive(self):
        snapshot = build_snapshot(
            _series(
                _year(net_income=100.0, cfo=140.0),
                _year(net_income=100.0, cfo=150.0),
                _year(net_income=100.0, cfo=160.0),
            )
        )
        assert any("converting to cash at" in item for item in snapshot.positives)

    def test_a_single_period_is_never_flagged_on_conversion(self):
        snapshot = build_snapshot(_series(_year(net_income=100.0, cfo=10.0)))
        assert not any("converted to cash on average" in flag for flag in snapshot.red_flags)

    def test_no_marker_means_no_marker_flag(self):
        snapshot = build_snapshot(_series({"revenue": 100.0}))
        assert not any("operating cash flow" in flag for flag in snapshot.red_flags)


class TestMarkersReachTheDecisionState:
    def test_the_snapshot_serialises_the_markers_with_their_inputs(self):
        snapshot = build_snapshot(_series(_year(), _year(), _year()))
        payload = snapshot.as_dict()
        assert payload["quality_markers"]
        accruals = next(
            item for item in payload["quality_markers"] if item["label"].startswith("Accrual")
        )
        assert accruals["inputs"]["by_period"]
        assert accruals["tier"] == "A"

    def test_a_marker_can_be_looked_up_by_name(self):
        snapshot = build_snapshot(_series(_year(), _year()))
        assert snapshot.marker("accrual_ratio") is not None
        assert snapshot.marker("beneish_m") is None

    def test_empty_accounts_serialise_without_markers(self):
        assert build_snapshot([]).as_dict()["quality_markers"] == []


# --------------------------------------------------------------------------- #
# stage D markers
# --------------------------------------------------------------------------- #


def _healthy(assets: float = 1_000.0, **extra: float) -> dict[str, float]:
    """A period carrying the inputs the stage D markers need, healthy by default."""
    metrics = {
        "net_income": 120.0,
        "operating_cash_flow": 140.0,
        "revenue": 1_000.0,
        "cost_of_goods_sold": 600.0,
        "gross_profit": 400.0,
        "total_assets": assets,
        "current_assets": 500.0,
        "current_liabilities": 250.0,
        "receivables": 100.0,
        "inventory": 120.0,
        "net_ppe": 300.0,
        "long_term_debt": 200.0,
        "shares_outstanding": 1_000.0,
        "depreciation_amortisation": 50.0,
        "gross_margin": 0.4,
        "roa": 0.12,
    }
    metrics.update(extra)
    return metrics


class TestPiotroski:
    def test_it_is_nine_named_questions_and_not_a_score(self):
        """The research note asks for this shape explicitly.

        "Not a score out of nine -- the individual answers are the value." A
        headline figure invites a threshold, and a threshold on nine binary
        questions about one company is a verdict in disguise.
        """
        marker = piotroski_marker(_series(_healthy(), _healthy()))

        assert marker is not None
        assert marker.value is None, "there must be no score to threshold"
        assert len(marker.inputs["checks"]) == 9
        for check in marker.inputs["checks"]:
            assert check["question"].endswith("?")
            assert check["detail"]

    def test_a_missing_input_is_unanswered_and_never_no(self):
        """Collapsing "the accounts do not say" into "no" is how a checklist
        becomes a score: it reports a company failing a test it was never asked."""
        marker = piotroski_marker([make_period("T", dt.date(2024, 12, 31), {"revenue": 5.0})])

        assert all(check["answer"] is None for check in marker.inputs["checks"])
        assert "could not be answered" in marker.reading

    def test_it_reads_a_healthy_improving_year_as_passing(self):
        """Health alone does not pass the direction tests: flat is not improving.

        Two identical years pass five of the nine, because four of them ask
        *whether something changed* and nothing did. That is the checklist working
        -- a company treading water should not read the same as one getting better.
        """
        marker = piotroski_marker(
            _series(
                _healthy(roa=0.08, gross_margin=0.34, revenue=900.0),
                _healthy(roa=0.12, gross_margin=0.40, revenue=1_000.0, long_term_debt=150.0),
            )
        )

        assert marker.inputs["answered"] == 9
        assert marker.inputs["passed"] >= 7

    def test_flat_years_pass_only_the_four_that_are_true_at_equality(self):
        """Four pass: the three level tests, plus "no new shares" at equality.

        "Were no new shares issued?" is a change test, but a flat share count
        satisfies it -- not issuing is not issuing. The other five ask for an
        improvement and get none, which is the distinction between a checklist and
        a health score.
        """
        marker = piotroski_marker(_series(_healthy(), _healthy()))

        answers = {check["question"]: check["answer"] for check in marker.inputs["checks"]}
        assert answers["Is the return on assets positive?"] is True
        assert answers["Does cash flow exceed profit?"] is True
        assert answers["Were no new shares issued?"] is True
        assert answers["Did the current ratio improve?"] is False
        assert marker.inputs["passed"] == 4

    def test_it_reads_a_deteriorating_year_as_failing(self):
        """The direction tests have to be able to fail, or they assert nothing."""
        marker = piotroski_marker(
            _series(
                _healthy(roa=0.20, gross_margin=0.50, revenue=1_000.0, shares_outstanding=900.0),
                _healthy(roa=0.05, gross_margin=0.30, revenue=700.0, shares_outstanding=1_200.0),
            )
        )

        answers = {check["question"]: check["answer"] for check in marker.inputs["checks"]}
        assert answers["Did the return on assets improve?"] is False
        assert answers["Did the gross margin improve?"] is False
        assert answers["Were no new shares issued?"] is False

    def test_one_year_answers_only_the_three_needing_no_comparison(self):
        """ROA>0, cash flow>0, and cash flow exceeding profit are level tests.

        The other six ask whether something *changed*, and one year cannot say.
        The note lists the accruals check under profitability, not under change.
        """
        marker = piotroski_marker([make_period("T", dt.date(2024, 12, 31), _healthy(roa=0.1))])

        answered = [c for c in marker.inputs["checks"] if c["answer"] is not None]
        assert len(answered) == 3


class TestGrossProfitability:
    def test_it_is_gross_profit_over_total_assets(self):
        marker = gross_profitability_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy(assets=2_000.0))]
        )

        assert marker.value == pytest.approx(400.0 / 2_000.0)
        assert marker.tier == "B"

    def test_it_falls_back_to_revenue_less_cost_of_sales(self):
        """A filer that states the two lines but never the subtotal."""
        metrics = _healthy()
        del metrics["gross_profit"]

        marker = gross_profitability_marker([make_period("T", dt.date(2024, 12, 31), metrics)])

        assert marker.value == pytest.approx((1_000.0 - 600.0) / 1_000.0)

    def test_it_is_absent_without_total_assets(self):
        metrics = _healthy()
        del metrics["total_assets"]

        assert gross_profitability_marker(
            [make_period("T", dt.date(2024, 12, 31), metrics)]
        ) is None

    def test_the_caveat_says_it_is_only_meaningful_within_an_industry(self):
        marker = gross_profitability_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy())]
        )

        assert "within" in marker.caveat.lower()


class TestReceivablesDrift:
    def test_it_reports_days_sales_outstanding(self):
        marker = receivables_drift_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy(receivables=100.0, revenue=1_000.0))]
        )

        assert marker.value == pytest.approx(100.0 / 1_000.0 * 365, rel=1e-6)

    def test_a_persistent_rise_reads_as_rising(self):
        marker = receivables_drift_marker(
            _series(
                _healthy(receivables=50.0),
                _healthy(receivables=80.0),
                _healthy(receivables=150.0),
            )
        )

        assert "rising" in marker.reading

    def test_it_is_absent_without_receivables(self):
        """Not every business has them, and an absence is not a zero."""
        metrics = _healthy()
        del metrics["receivables"]

        assert receivables_drift_marker([make_period("T", dt.date(2024, 12, 31), metrics)]) is None


class TestInventoryDrift:
    def test_it_reports_inventory_days_and_the_margin_alongside(self):
        marker = inventory_drift_marker(_series(_healthy(), _healthy()))

        assert marker.value == pytest.approx(120.0 / 1_000.0 * 365, rel=1e-6)
        assert marker.inputs["gross_margin_by_period"]

    def test_a_company_with_no_inventory_yields_no_marker(self):
        metrics = _healthy()
        del metrics["inventory"]

        assert inventory_drift_marker([make_period("T", dt.date(2024, 12, 31), metrics)]) is None


class TestGoodwillIntensity:
    def test_it_is_goodwill_and_intangibles_over_assets(self):
        marker = goodwill_intensity_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy(goodwill=200.0, intangible_assets=100.0))]
        )

        assert marker.value == pytest.approx(0.3)

    def test_disclosing_neither_is_absent_rather_than_clean(self):
        """The failure this guards: a company disclosing nothing reading as 0%."""
        assert goodwill_intensity_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy())]
        ) is None

    def test_a_stated_zero_is_a_real_zero(self):
        """Stating no goodwill is not the same as not stating goodwill."""
        marker = goodwill_intensity_marker(
            [make_period("T", dt.date(2024, 12, 31), _healthy(goodwill=0.0))]
        )

        assert marker.value == 0.0

    def test_a_rising_share_is_called_out(self):
        marker = goodwill_intensity_marker(
            _series(
                _healthy(goodwill=50.0, intangible_assets=50.0),
                _healthy(goodwill=300.0, intangible_assets=100.0),
            )
        )

        assert "rising" in marker.reading


class TestBeneishInputs:
    def test_it_produces_indices_and_no_composite(self):
        """The M-score is deliberately absent, and the marker says why.

        Its coefficients are not in this project's evidence base, and it is only
        meaningful ranked within an industry -- which a universe spread across 144
        sectors rarely allows. Computing it anyway would be unverifiable arithmetic
        presented as a score.
        """
        marker = beneish_inputs_marker(_series(_healthy(), _healthy()))

        assert marker is not None
        assert marker.value is None
        assert "M-score" in marker.caveat
        assert marker.inputs["indices"]

    def test_it_needs_two_years(self):
        assert beneish_inputs_marker([make_period("T", dt.date(2024, 12, 31), _healthy())]) is None

    def test_an_index_above_one_means_the_ratio_moved_the_flagged_way(self):
        marker = beneish_inputs_marker(_series(_healthy(receivables=50.0), _healthy(receivables=150.0)))

        assert marker.inputs["indices"]["DSRI days sales in receivables"] == pytest.approx(3.0)

    def test_a_non_positive_base_yields_no_index_rather_than_an_inverted_one(self):
        """A margin collapsing from +5% to -2% must not read as an improvement.

        GMI is prior margin over current margin, so a current margin at or below
        zero makes the ratio negative -- below 1, which is the "improved" direction.
        The guard is on the denominator for exactly that reason.
        """
        marker = beneish_inputs_marker(
            _series(
                _healthy(gross_margin=0.05, gross_profit=50.0),
                _healthy(gross_margin=-0.02, gross_profit=-20.0),
            )
        )

        assert "GMI gross margin" not in marker.inputs["indices"]

    def test_a_margin_that_improved_from_negative_is_read_correctly(self):
        """The mirror case is legitimate, and must not be suppressed with it.

        Prior -2% to current +3% is a real improvement. The index is negative,
        which is the correct direction to read, and suppressing it would hide a
        genuine recovery.
        """
        marker = beneish_inputs_marker(
            _series(
                _healthy(gross_margin=-0.02, gross_profit=-20.0),
                _healthy(gross_margin=0.03, gross_profit=30.0),
            )
        )

        assert marker.inputs["indices"]["GMI gross margin"] < 1.0

    def test_the_caveat_never_lets_a_flag_read_as_a_verdict(self):
        marker = beneish_inputs_marker(_series(_healthy(), _healthy()))

        assert "not evidence of manipulation" in marker.caveat
        assert "read this" in marker.caveat

    def test_there_is_still_no_marker_called_beneish_m(self):
        """The name a reader would expect, and the one that must not exist."""
        names = {marker.name for marker in analyse(_series(_healthy(), _healthy()))}

        assert "beneish_m" not in names


def _altman_year(assets: float = 1_000.0, **extra: float) -> dict[str, float]:
    """A period carrying all four Z'' inputs, at values with a hand-checkable score."""
    metrics = {
        "total_assets": assets,
        "current_assets": 500.0,
        "current_liabilities": 250.0,
        "retained_earnings": 300.0,
        "ebit": 150.0,
        "total_equity": 600.0,
        "total_liabilities": 400.0,
    }
    metrics.update(extra)
    return metrics


class TestAltmanInputs:
    def test_the_coefficients_are_the_ones_the_note_verifies(self):
        """Pinned, because the evidence base is what licenses computing a score here.

        The note records that the leading 6.56 was confirmed from Altman's own 2000
        text and that its earlier "Wikipedia only" caveat was withdrawn. A quiet edit
        to any of these would produce a number that still looks like a Z'' score and
        is not one, which is the failure a reader could not detect.
        """
        from awltux.analysis.accounting import ALTMAN_Z_DOUBLE_PRIME

        assert dict(ALTMAN_Z_DOUBLE_PRIME) == {
            "working capital to total assets": 6.56,
            "retained earnings to total assets": 3.26,
            "EBIT to total assets": 6.72,
            "book equity to total liabilities": 1.05,
        }

    def test_the_inputs_are_the_four_ratios_the_note_defines(self):
        """X1..X4 of Z'', including X4 as **book** equity rather than market value."""
        marker = altman_inputs_marker(_series(_altman_year()))

        assert marker is not None
        ratios = marker.inputs["ratios"]
        assert ratios["working capital to total assets"] == pytest.approx(0.25)
        assert ratios["retained earnings to total assets"] == pytest.approx(0.30)
        assert ratios["EBIT to total assets"] == pytest.approx(0.15)
        assert ratios["book equity to total liabilities"] == pytest.approx(1.50)

    def test_the_composite_is_the_z_double_prime_arithmetic(self):
        """6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4, worked through by hand.

        6.56(0.25) + 3.26(0.30) + 6.72(0.15) + 1.05(1.50)
        = 1.640 + 0.978 + 1.008 + 1.575 = 5.201
        """
        marker = altman_inputs_marker(_series(_altman_year()))

        assert marker.inputs["z_double_prime"] == pytest.approx(5.201)

    def test_the_headline_value_is_absent_so_nothing_can_rank_on_it(self):
        """The note's demotion, enforced in the shape of the marker.

        "Its inputs belong on the page and its score does not belong in a ranking."
        `value` is the field a ranking would read, so it stays empty and the score
        lives in the audit trail beside the ratios that produced it.
        """
        marker = altman_inputs_marker(_series(_altman_year()))

        assert marker.value is None
        assert marker.inputs["z_double_prime"] is not None

    def test_the_zone_is_never_applied(self):
        """No cut-off verdict, which is this module's second rule.

        The zones exist in the literature and are deliberately not used: the same
        evidence that demotes the score says 47% of listed firms sit below the
        distress cut-off while 19% of the failures sat above it. Asserted on the
        cut-offs themselves rather than on the word "distress", which the caveat
        legitimately uses when it forbids exactly this reading.
        """
        marker = altman_inputs_marker(_series(_altman_year()))

        assert "zones are deliberately not applied" in marker.caveat
        for cutoff in ("1.1", "1.81", "2.6", "2.99"):
            assert cutoff not in marker.reading, f"{cutoff} restated as a threshold"
            assert cutoff not in marker.caveat, f"{cutoff} restated as a threshold"

    def test_a_missing_input_withholds_the_composite(self):
        """Three of four inputs summed is a number that looks like the score and is
        not, and the missing input is the same one for a whole class of filers."""
        without_equity = _altman_year()
        del without_equity["total_equity"]

        marker = altman_inputs_marker(_series(without_equity))

        assert marker.inputs["z_double_prime"] is None
        assert marker.inputs["missing"] == ["book equity to total liabilities"]

    def test_it_names_what_could_not_be_built(self):
        """X1 is the input that is usually absent -- current assets and liabilities
        are missing for a large minority of filers, and legally absent for UK small
        and micro filers -- so the marker says so rather than going quiet.

        Dropping both liquidity figures costs exactly one of the four ratios, because
        only X1 is built from them; the count is asserted so a widened dependency
        would have to be a deliberate change rather than an accident.
        """
        without_liquidity = _altman_year()
        del without_liquidity["current_assets"]
        del without_liquidity["current_liabilities"]

        marker = altman_inputs_marker(_series(without_liquidity))

        assert marker is not None
        assert marker.inputs["ratios"]["working capital to total assets"] is None
        assert marker.inputs["missing"] == ["working capital to total assets"]
        assert "1 of 4 could not be built" in marker.reading
        assert "working capital to total assets" in marker.reading

    def test_a_negative_equity_year_keeps_a_negative_input(self):
        """Insolvency is exactly the case this marker is looked at for, so the
        reading is kept rather than suppressed for being below zero."""
        marker = altman_inputs_marker(
            _series(_altman_year(total_equity=-200.0, total_liabilities=1_200.0))
        )

        assert marker.inputs["ratios"]["book equity to total liabilities"] == pytest.approx(
            -0.1667, abs=1e-4
        )

    def test_a_period_with_none_of_the_inputs_produces_no_marker(self):
        """Rule three: a marker that needs a figure the accounts do not contain is
        absent, not estimated."""
        assert altman_inputs_marker(_series(_year())) is None

    def test_no_periods_means_no_marker(self):
        assert altman_inputs_marker([]) is None

    def test_it_appears_in_analyse_once_the_inputs_exist(self):
        names = {marker.name for marker in analyse(_series(_altman_year(), _altman_year()))}

        assert "altman_inputs" in names

    def test_the_caveat_carries_the_us_calibration_warning(self):
        """The note calls this "required, not optional": Beneish and Altman were
        fitted to US GAAP data, and FRS 102 and IFRS differ on leases, development
        costs and goodwill."""
        marker = altman_inputs_marker(_series(_altman_year()))

        assert "must not be ported" in marker.caveat
        assert "0.07" in marker.caveat
        assert "read this" in marker.caveat

    def test_there_is_no_marker_called_altman_z(self):
        """The name a reader would expect, and the one that must not exist.

        A marker named for the score is a marker that gets ranked and thresholded,
        which is the demotion the note asks for.
        """
        names = {marker.name for marker in analyse(_series(_altman_year(), _altman_year()))}

        assert "altman_z" not in names
        assert "altman_z_double_prime" not in names
