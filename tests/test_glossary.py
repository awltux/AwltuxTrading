"""The hover help: one explanation per field, and it reaches the page.

Asked for by a reader who could not tell what the figures meant. Two properties matter
more than the wording: **each field is explained once**, because the same figure appears
on more than one page and two copies of an explanation drift; and **the explanation
reaches the markup**, because a glossary nothing renders is documentation rather than a
feature.

The wording itself is not asserted. What is asserted is that every entry says what the
number is *and* how to read it -- the second half being the part a reader who does not
know the vocabulary cannot supply, and the part that stops a number reading as a verdict.
"""

from __future__ import annotations

import pytest

from awltux.web import glossary

#: Fields a reader sees on the pages that carry them.
SHOWN_ON_DASHBOARD = (
    "name",
    "horizon_fit",
    "margin_of_safety",
    "price",
    "long_term_action",
    "composite_score",
    "confidence",
    "short_term_action",
    "short_term_score",
    "short_term_confidence",
    "setup",
    "sentiment",
    "engine",
    "freshness",
)

SHOWN_ON_VALUATION = ("fair_value_base", "fair_value_range", "margin_of_safety", "methods_applied")
SHOWN_ON_ACCOUNTS = ("stated", "computed")


class TestTheExplanations:
    def test_every_field_says_what_it_is_and_how_to_read_it(self):
        """Two halves, and the second is the one that was missing.

        "Margin of safety 12%" is unreadable without knowing that bigger is safer and
        that it is a percentage of an estimate rather than of a fact. An entry that
        only defines the term leaves the reader exactly where they were.
        """
        for field in glossary.FIELDS:
            assert field.what.strip(), f"{field.key} does not say what it is"
            assert field.reading.strip(), f"{field.key} does not say how to read it"
            assert len(field.reading) > 40, (
                f"{field.key}'s reading is too thin to be a reading: {field.reading!r}"
            )

    def test_no_key_is_explained_twice(self):
        keys = [field.key for field in glossary.FIELDS]
        assert len(keys) == len(set(keys)), "a duplicate key would shadow the first"

    @pytest.mark.parametrize(
        "key", SHOWN_ON_DASHBOARD + SHOWN_ON_VALUATION + SHOWN_ON_ACCOUNTS
    )
    def test_every_field_a_page_shows_has_an_explanation(self, key):
        """The gap this catches is a template calling `help()` for a field nobody has
        written up: it renders nothing at all, which looks deliberate."""
        assert glossary.BY_KEY.get(key) is not None, f"{key} is shown but not explained"

    def test_an_unknown_key_produces_nothing_rather_than_a_placeholder(self):
        """A tooltip reading "no description" is worse than no tooltip: it advertises
        that the interface does not know, at the moment the reader asked."""
        assert glossary.explanation("not_a_field") == ""

    def test_the_tooltip_text_carries_both_halves(self):
        text = glossary.explanation("margin_of_safety")

        assert "discount" in text
        assert "Bigger is safer" in text

    def test_where_a_figure_is_not_arithmetic_the_entry_says_so(self):
        """The engine's confidence is a model's statement, not a probability, and the
        difference is the whole reason it can be refused a verdict."""
        text = glossary.explanation("confidence")

        assert "not as a probability" in text


class TestItReachesThePage:
    def test_the_dashboard_columns_carry_their_explanations(self, client):
        body = client.get("/dashboard").text

        assert 'class="help"' in body
        assert "Bigger is safer" in body, "the margin-of-safety reading is missing"

    def test_the_fragment_carries_them_too(self, client):
        """The table is served twice -- included by the page and returned by the
        fragment -- so the help has to survive the swap, not only the first paint."""
        fragment = client.get("/partials/recommendations").text

        assert 'class="help"' in fragment
        assert "Bigger is safer" in fragment

    def test_the_help_is_a_data_attribute_and_not_a_title(self, client):
        """`title` waits, truncates and never appears on touch. The text rides in a
        `data-help` attribute that CSS shows on hover *and* focus."""
        body = client.get("/dashboard").text

        assert "data-help=" in body
        assert 'tabindex="0"' in body, "keyboard users must reach it too"

    def test_a_field_the_glossary_does_not_know_renders_nothing(self):
        """Rendered through the template environment, so the macro is exercised rather
        than the function behind it."""
        from awltux.web.templating import templates

        rendered = templates.env.from_string(
            '{% from "partials/_help.html" import help %}[{{ help("not_a_field") }}]'
        ).render()

        assert rendered == "[]"
