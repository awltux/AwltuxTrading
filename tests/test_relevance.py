"""The materiality scale: one order, one floor, two shapes.

`materiality` is written by the classifier and read by the flash ticker, which needs the
same floor twice: as a predicate over a value it already holds (`is_material_enough`) and
as a set of levels for a SQL `IN` (`materiality_floor_values`). Two answers to "what is
material enough" is how a rendered list and the live refresh that feeds it come to
disagree about what the reader is looking at, so the invariant that the two agree is
asserted here rather than assumed.

The order and the weights live together in `analysis/relevance.py`. The order is spelled
out rather than derived from the weights, because the weights are tunable floats and a
re-tune would silently move a floor; these tests tie the two lists together instead.
"""

from __future__ import annotations

import pytest

from awltux.analysis.relevance import (
    MATERIALITY_ORDER,
    MATERIALITY_WEIGHT,
    is_material_enough,
    materiality_floor_values,
)


class TestTheScale:
    def test_the_order_and_the_weights_describe_the_same_levels(self):
        """A level added to one and not the other is the drift this catches.

        `priority` looks a level up in the weights; a floor compares it against the
        order. A level present in one and missing from the other is either an
        unweighted score or a floor that cannot be reached.
        """
        assert set(MATERIALITY_ORDER) == set(MATERIALITY_WEIGHT), (
            "MATERIALITY_ORDER and MATERIALITY_WEIGHT must name the same levels: "
            f"only in the order {set(MATERIALITY_ORDER) - set(MATERIALITY_WEIGHT)}, "
            f"only in the weights {set(MATERIALITY_WEIGHT) - set(MATERIALITY_ORDER)}"
        )

    def test_the_order_is_least_to_most_severe(self):
        """The whole file depends on this being the order, not just a set."""
        assert MATERIALITY_ORDER[0] == "none"
        assert MATERIALITY_ORDER[-1] == "critical"
        assert MATERIALITY_WEIGHT["none"] < MATERIALITY_WEIGHT["critical"]


class TestTheFloorIsTheSameInBothShapes:
    """The property that keeps the banner's list and its live refresh in step."""

    @pytest.mark.parametrize("threshold", MATERIALITY_ORDER)
    def test_the_predicate_agrees_with_the_value_list(self, threshold: str):
        allowed = materiality_floor_values(threshold)
        for level in MATERIALITY_ORDER:
            assert is_material_enough(level, threshold=threshold) == (level in allowed), (
                f"{level!r} against a {threshold!r} floor: the predicate and the SQL set "
                "disagree, so the ticker and the query that refreshes it would show "
                "different things"
            )

    @pytest.mark.parametrize(
        "threshold,expected",
        [
            ("mild", ("mild", "moderate", "material", "critical")),
            ("moderate", ("moderate", "material", "critical")),
            ("critical", ("critical",)),
        ],
    )
    def test_the_floor_includes_the_threshold_itself(self, threshold, expected):
        """"At least moderate" includes moderate; an off-by-one here silently raises
        every floor by one level."""
        assert materiality_floor_values(threshold) == expected

    def test_a_none_floor_admits_everything(self):
        assert materiality_floor_values("none") == tuple(MATERIALITY_ORDER)


class TestWhatDoesNotClearAFloor:
    def test_unassessed_does_not_clear_a_floor(self):
        """""Nothing has judged this" is not "judged unimportant".

        Most ticker floors exclude an unclassified story, which is the correct reading of
        a materiality-filtered banner: it is not *known* to be material.
        """
        assert is_material_enough(None) is False

    def test_a_level_that_is_not_on_the_scale_does_not_clear_a_floor(self):
        assert is_material_enough("enormous") is False

    def test_an_unknown_threshold_falls_back_to_mild(self):
        """Unreachable from configuration -- the setting is a validated `Literal` -- but
        it must keep the banner rendering rather than raise inside a page."""
        assert materiality_floor_values("enormous") == materiality_floor_values("mild")

    def test_none_clears_a_none_floor(self):
        """The floor is a floor, not a filter for the word "none"."""
        assert is_material_enough("none", threshold="none") is True
