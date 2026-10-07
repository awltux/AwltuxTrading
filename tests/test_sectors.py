"""One coarse sector per instrument, derived from the SEC SIC code.

The rule this file tests exists because the universe's own sector is unusable as a
grouping: `instrument.sector` is the SIC *industry description*, 148 distinct strings
over 500 in-universe instruments, most holding one or two names. Measured 2026-10-07,
`Services-Computer Programming, Data Processing, Etc.` is a sector of five and 185
in-universe instruments have no sector at all.

Two properties matter more than the table's contents, and they are what is asserted
here: **the eleven are the only outputs**, so a sector page is never keyed on a value
no page exists for; and **a two-digit division default cannot swallow the exceptions**,
because SIC is numeric by division and 2834 drugs and 2810 industrial chemicals are
both "28, chemicals". Getting that one wrong puts every pharmaceutical company in
Materials, which reads as plausible and is exactly the failure that is hard to notice.
"""

from __future__ import annotations

import pytest

from awltux.analysis.sectors import (
    SECTOR_NAMES,
    assign,
    group_for,
    is_sector,
    normalise_code,
)


class TestTheRule:
    def test_a_drug_company_is_health_care_and_a_chemical_company_is_not(self):
        """Both are SIC 28. This is the case a range table alone gets wrong."""
        assert group_for("2834") == "Health Care"
        assert group_for("2810") == "Materials"

    def test_the_major_group_overrides_the_division_it_sits_in(self):
        """367 is semiconductors inside "36, electronic equipment", which the division
        would send to Information Technology anyway -- so the pair to check is 362,
        electrical apparatus, which is not."""
        assert group_for("3674") == "Information Technology"
        assert group_for("7372") == "Information Technology"
        assert group_for("1311") == "Energy", "crude oil is not Materials"
        assert group_for("1389") == "Energy", "oil services is not Materials"
        assert group_for("1040") == "Materials", "gold really is Materials"

    def test_an_exact_code_beats_its_major_group(self):
        """679 is miscellaneous investing and is Financials. 6798 is a REIT and belongs
        with the property companies, so the four-digit rule has to win."""
        assert group_for("6798") == "Real Estate"
        assert group_for("6799") == "Financials"

    def test_every_output_is_one_of_the_eleven(self):
        """The invariant a sector page depends on. Enumerated over the whole SIC space
        rather than the codes in the universe, because the universe changes and a page
        keyed on a value with no route is a 404 the taxonomy caused."""
        seen = {group_for(f"{code:04d}") for code in range(100, 10_000)}
        assert None not in seen, "every four-digit code must classify, via its division"
        assert seen <= set(SECTOR_NAMES)

    def test_the_divisions_leave_no_gap(self):
        """The property that makes the test above hold for an edit as well as today.
        The first draft of the table had six holes -- 18, 19, 68, 69, 74, 77 -- and no
        amount of reading the ranges shows them; only walking the space does."""
        from awltux.analysis.sectors import DIVISIONS

        covered: set[int] = set()
        for low, high, _sector in DIVISIONS:
            covered.update(range(low, high + 1))
        assert covered == set(range(1, 100)), sorted(set(range(1, 100)) - covered)

    def test_an_unknown_string_is_no_sector_rather_than_a_default(self):
        """185 in-universe instruments have neither a code nor a sector. Bucketing them
        somewhere would make every sector page wrong by an amount nobody can see."""
        assert group_for(None, None) is None
        assert group_for("", "") is None
        assert group_for(None, "Vibes") is None

    def test_a_sector_string_is_used_when_there_is_no_code(self):
        """Yahoo supplies a GICS name and no code, and spells two of them differently
        from the eleven."""
        assert group_for(None, "Healthcare") == "Health Care"
        assert group_for(None, "Technology") == "Information Technology"
        assert group_for(None, "Basic Materials") == "Materials"
        assert group_for(None, "Financial Services") == "Financials"

    def test_a_code_wins_over_a_contradicting_string(self):
        """When both are present the code is authoritative: it is the number EDGAR
        supplies, and the string is free text the register spells three ways."""
        assert group_for("2834", "Technology") == "Health Care"

    def test_the_code_is_normalised(self):
        assert normalise_code("100") == "0100", "agriculture arrives without its zeros"
        assert normalise_code(" 2834.0 ") == "2834"
        assert normalise_code(None) is None
        assert normalise_code("") is None

    def test_is_sector_accepts_only_the_eleven(self):
        assert all(is_sector(name) for name in SECTOR_NAMES)
        assert not is_sector("Technology")
        assert not is_sector(None)


class TestAssign:
    def test_it_sets_the_group_from_the_rows_own_fields(self):
        class Row:
            sic_code = "6022"
            sector = "State Commercial Banks"

        row = Row()
        assert assign(row) == "Financials"
        assert row.sector_group == "Financials"

    def test_it_clears_a_group_the_fields_no_longer_support(self):
        """Recomputed, not merged. A row whose SIC code was corrected to something
        unclassifiable must stop claiming the old sector."""
        class Row:
            sic_code = None
            sector = None
            sector_group = "Energy"

        row = Row()
        assert assign(row) is None
        assert row.sector_group is None


class TestTheVocabulary:
    def test_the_news_vocabulary_normalises_into_it(self):
        """The 57 news items carrying a sector use Marketaux's names. If these did not
        map, the sector pages would collect instruments and no news."""
        for written in ("Industrials", "Healthcare", "Financial Services", "Energy", "Technology"):
            assert group_for(None, written) in SECTOR_NAMES

    @pytest.mark.parametrize("name", SECTOR_NAMES)
    def test_each_name_round_trips(self, name):
        assert group_for(None, name) == name
