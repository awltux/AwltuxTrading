"""`shorten`, the trimming both the hover hint and the configuration index use.

Tested here rather than beside either caller because it belongs to neither: it is the one
rule for "this is more prose than a reader wants in a cell or a tooltip", and it lives in
`web/templating.py` with the rest of the display formatting.
"""

from __future__ import annotations

from awltux.web.templating import shorten


class TestShorten:
    def test_a_short_string_is_returned_unchanged(self):
        assert shorten("Stantec makes things.", 240) == "Stantec makes things."

    def test_it_collapses_whitespace_onto_one_line(self):
        """A `title` attribute is one line by construction, so a provider's paragraphs must
        not put line breaks inside it."""
        assert shorten("one\n\ntwo   three", 240) == "one two three"

    def test_a_long_string_is_cut_at_a_word(self):
        text = " ".join(["word"] * 200)

        trimmed = shorten(text, 100)

        assert len(trimmed) <= 101
        assert trimmed.endswith("…")
        assert not trimmed.endswith(" …"), "the cut landed after a space, leaving a gap"

    def test_an_absent_value_is_an_empty_string(self):
        assert shorten("", 10) == ""
        assert shorten(None, 10) == ""

    def test_a_string_exactly_at_the_limit_is_not_cut(self):
        text = "x" * 40

        assert shorten(text, 40) == text
