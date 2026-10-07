"""Which of a filing's other captions actually close a composition gap.

The vocabulary can be allowed to grow on its own only because a candidate is *provable*:
a caption belongs on the list when its value closes a residual exactly. These tests pin
that down, on the numbers the live database actually produced.

MSFT_US_EQ, 2026-06-30, from its own 10-K balance sheet:

    current assets      20,935 + [55,908] + 80,876 + 1,397 + 48,594 = 207,710  = stated
    total assets        ... + 313,076 + 24,177 + [36,348] + 119,651 + 18,609 + 38,805 = 758,376

so `current_assets_composition` is out by exactly 55,908 and `assets_composition` by
exactly 92,256 = 55,908 + 36,348. Neither caption is in the 46-name vocabulary.
"""

from __future__ import annotations

from awltux.analysis import gap

MSFT_CAPTIONS = {"short_term_investments": 55_908.0, "equity_investments": 36_348.0}


class TestClosingAResidual:
    def test_one_caption_closes_the_current_assets_gap(self):
        found = gap.best(55_908.0, MSFT_CAPTIONS)

        assert found is not None
        assert found.labels == ("short_term_investments",)
        assert found.exact

    def test_two_captions_close_the_total_assets_gap(self):
        """A balance sheet can leave two lines out at once, so a single-exact-match rule
        would report nothing where the truth is a pair."""
        found = gap.best(92_256.0, MSFT_CAPTIONS)

        assert found is not None
        assert set(found.labels) == {"short_term_investments", "equity_investments"}
        assert not found.exact

    def test_nothing_is_found_when_no_caption_fits(self):
        """The ordinary answer. Most filings present nothing that closes their gap, and
        inventing one would put a wrong name in the prompt for every later filing."""
        assert gap.best(92_256.0, {"some_line": 1_000.0}) is None
        assert gap.unexplained(92_256.0, {"some_line": 1_000.0})

    def test_a_zero_residual_is_not_a_discovery(self):
        assert gap.closing_captions(0.0, MSFT_CAPTIONS) == []
        assert gap.best(0.0, MSFT_CAPTIONS) is None

    def test_no_captions_means_nothing_to_find(self):
        assert gap.best(55_908.0, {}) is None

    def test_the_filer_s_own_rounding_is_within_tolerance(self):
        """The residual is a difference of figures we hold, so the tolerance has to be
        the one the comparison that produced it used. A tighter one would reject a
        correct match over rounding in the filing itself."""
        assert gap.best(55_908.0, {"short_term_investments": 55_910.0}) is not None
        assert gap.best(55_908.0, {"short_term_investments": 60_000.0}) is None


class TestAmbiguityIsDeclined:
    def test_two_captions_that_both_close_it_are_not_a_discovery(self):
        """The arithmetic cannot tell which is the missing line, and recording either
        would be a coin toss written into a prompt for every later filing."""
        ambiguous = {"line_a": 55_908.0, "line_b": 55_908.0}

        assert gap.closing_captions(55_908.0, ambiguous) != []
        assert gap.best(55_908.0, ambiguous) is None

    def test_a_single_beat_is_still_taken_when_a_pair_also_fits(self):
        """One caption is a better explanation than two, so the shortest is preferred
        even where a combination would also work."""
        captions = {"short_term_investments": 55_908.0, "a": 20_000.0, "b": 35_908.0}

        found = gap.best(55_908.0, captions)

        assert found is not None and found.labels == ("short_term_investments",)


class TestTheSearchBounds:
    def test_it_does_not_combine_more_than_the_limit(self):
        """Three lines that happen to sum to a residual is a coincidence more often
        than a discovery, and the search costs combinations."""
        three = {"a": 20_000.0, "b": 20_000.0, "c": 15_908.0}

        assert gap.best(55_908.0, three) is None, "a triple must not be proposed"
        assert gap.closing_captions(55_908.0, three, max_combination=3) != []

    def test_the_order_is_stable_for_the_same_mapping(self):
        once = gap.closing_captions(92_256.0, MSFT_CAPTIONS)
        twice = gap.closing_captions(92_256.0, MSFT_CAPTIONS)

        assert once == twice, "the same filing must always give the same answer"

    def test_a_zero_valued_caption_cannot_close_a_gap(self):
        """A line reported as zero adds nothing, and pairing it with the real caption
        would offer a name that explains nothing."""
        assert gap.best(55_908.0, {"real": 55_908.0, "zero": 0.0}) is not None
        assert gap.best(0.0, {"zero": 0.0}) is None


class TestLabelling:
    def test_a_caption_becomes_a_key(self):
        assert gap.normalise_labels(["Short-term investments"]) == {
            "Short-term investments": "short_term_investments"
        }

    def test_punctuation_and_runs_collapse(self):
        assert gap.normalise_labels(["Property, plant & equipment (net)"]) == {
            "Property, plant & equipment (net)": "property_plant_equipment_net"
        }

    def test_it_reports_what_it_could_not_use(self):
        assert gap.normalise_labels(["", "   ", "---"]) == {}
