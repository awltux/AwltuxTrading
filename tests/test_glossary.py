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
        assert "bigger number is safer" in text

    def test_no_explanation_carries_markup(self):
        """The text goes into an HTML attribute and is shown verbatim by CSS.

        Markdown emphasis written here is not rendered, it is *displayed* -- the first
        version of the margin-of-safety entry reached the browser reading
        `**Bigger is safer**`. Emphasis in a tooltip has to be carried by the sentence.

        The derived question entries are checked too: their text comes from
        `decision/questions.py`, where a criterion written with a bracket or a backtick would
        reach a tooltip the same way.
        """
        for field in (*glossary.FIELDS, *glossary.QUESTION_FIELDS.values()):
            for half in (field.what, field.reading):
                for markup in ("**", "__", "[", "]", "`", "<"):
                    assert markup not in half, (
                        f"{field.key} carries {markup!r}, which the tooltip will show "
                        f"literally: {half[:70]!r}"
                    )

    def test_where_a_figure_is_not_arithmetic_the_entry_says_so(self):
        """The engine's confidence is a model's statement, not a probability, and the
        difference is the whole reason it can be refused a verdict."""
        text = glossary.explanation("confidence")

        assert "not as a probability" in text


class TestTheModelAnswers:
    """The Question column of the instrument page's Model answers table.

    Asked for by a reader: *"It is currently unclear what each of these rows represents and
    how to read the values."* The rows are the typed questions put to the model, and the
    answer is a level on a scale whose direction differs by row -- `short_term_setup 1` is
    poor, `business_quality 1` is weak, `short_term_drawdown_risk 1` is low risk -- so a
    bare number cannot be read without the scale.
    """

    def test_every_question_has_a_tooltip(self):
        """Derived from `QUESTION_DEFS`, so a question added to the engine gets one
        automatically rather than rendering an unexplained row."""
        from awltux.decision.questions import QUESTION_DEFS

        for question in QUESTION_DEFS:
            text = glossary.explanation(f"answer_{question.name}")
            assert text.strip(), f"{question.name} has no tooltip"
            assert question.meaning in text, "the tooltip must say what the row means"

    def test_a_scored_question_names_every_level(self):
        """The scale is the answer to "how do I read 1.0", and 0-4 with no key is a
        number a reader has to guess at."""
        text = glossary.explanation("answer_short_term_setup")

        assert "Rated 0 to 4" in text
        for level in range(5):
            assert f"{level} " in text, f"level {level} is not named"
        assert "well-confirmed setup" in text

    def test_a_score_is_not_read_as_good_in_the_same_direction_everywhere(self):
        """The distinction a reader cannot guess: a high score is good for quality and
        bad for risk, and both rows look identical."""
        quality = glossary.explanation("answer_business_quality")
        risk = glossary.explanation("answer_short_term_drawdown_risk")

        assert "Excellent" in quality, "4 is an excellent business"
        assert "Minimal" in risk, "0 is minimal risk"
        assert "Severe" in risk, "and 4 is severe"

    def test_a_yes_no_question_says_it_is_a_probability(self):
        """`going_concern 0.03` is not "no": the model answers in 0..1, while the
        deterministic rules answer yes or no, and the row shows whichever engine ran."""
        text = glossary.explanation("answer_going_concern")

        assert "probability between 0 and 1" in text
        assert "say yes or no" in text

    def test_a_choice_question_lists_its_options(self):
        text = glossary.explanation("answer_horizon_fit")

        assert "One of:" in text
        for option in ("long term", "short term", "both", "neither"):
            assert option in text, option

    def test_the_derived_keys_do_not_shadow_the_written_ones(self):
        """`margin_of_safety` is already explained as the percentage column on the
        recommendations table -- a different thing from the model's 0-4 score for the same
        question. One key cannot be both, so the derived entries are prefixed."""
        from awltux.decision.questions import QUESTION_DEFS

        for question in QUESTION_DEFS:
            assert question.name not in glossary.QUESTION_FIELDS
            assert f"answer_{question.name}" in glossary.QUESTION_FIELDS
        assert "discount" in glossary.explanation("margin_of_safety")
        assert "Rated 0 to 4" in glossary.explanation("answer_margin_of_safety")

    def test_the_confidence_and_distribution_columns_are_explained(self):
        """The two numbers beside every row, and the two a reader is most likely to
        mistake for probabilities the system stands behind."""
        confidence = glossary.explanation("answer_confidence")
        distribution = glossary.explanation("answer_distribution")

        assert "not a calibrated probability" in confidence
        assert "uncalibrated" in distribution
        assert "will not always sum to exactly 100%" in distribution


class TestItReachesThePage:
    def test_the_dashboard_columns_carry_their_explanations(self, client):
        body = client.get("/dashboard").text

        assert 'class="help"' in body
        assert "bigger number is safer" in body, "the margin-of-safety reading is missing"

    def test_the_fragment_carries_them_too(self, client):
        """The table is served twice -- included by the page and returned by the
        fragment -- so the help has to survive the swap, not only the first paint."""
        fragment = client.get("/partials/recommendations").text

        assert 'class="help"' in fragment
        assert "bigger number is safer" in fragment

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
