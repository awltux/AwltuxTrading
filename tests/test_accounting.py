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
    analyse,
    cash_conversion_marker,
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
        markers = analyse(_series(_year(), _year(), _year()))
        assert {marker.name for marker in markers} == {"accrual_ratio", "cash_conversion"}

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
