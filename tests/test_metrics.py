"""The canonical metric vocabulary, and the drift it exists to prevent.

The bug this guards against is silence. If a name is in the extractor's gate but
not in the prompt, the model is never asked for it and it simply never appears --
which is indistinguishable from a company that does not report it. If a name is in
the prompt but not the gate, it is extracted and then thrown away. Neither leaves
a trace at runtime, so both need a test rather than a comment.
"""

from __future__ import annotations

import re

import pytest

from awltux.llm.prompts import FILING_EXTRACTION_INSTRUCTION
from awltux.metrics import (
    BALANCE_METRICS,
    CANONICAL_METRICS,
    CASH_METRICS,
    DERIVED_METRICS,
    EXTRACTABLE_METRICS,
    INCOME_METRICS,
    METRIC_NOTES,
    STATED_METRICS,
    is_canonical,
    unit_scale,
)


class TestVocabularyShape:
    def test_the_three_groups_are_disjoint(self):
        """A name in two groups would appear twice in the prompt."""
        groups = [set(INCOME_METRICS), set(BALANCE_METRICS), set(CASH_METRICS)]
        assert len(set.union(*groups)) == sum(len(group) for group in groups)

    def test_stated_metrics_is_exactly_the_union_of_the_groups(self):
        assert set(STATED_METRICS) == set(INCOME_METRICS) | set(BALANCE_METRICS) | set(
            CASH_METRICS
        )

    def test_derived_ratios_are_not_extractable(self):
        """`roce` has a definition here; a model must not supply its own."""
        assert not (set(DERIVED_METRICS) & EXTRACTABLE_METRICS)

    def test_canonical_is_stated_plus_derived(self):
        assert set(STATED_METRICS) | set(DERIVED_METRICS) == CANONICAL_METRICS

    def test_every_metric_is_documented(self):
        """Adding a name without saying what consumes it should fail here."""
        assert set(STATED_METRICS) == set(METRIC_NOTES)

    def test_is_canonical_agrees_with_the_set(self):
        assert is_canonical("receivables")
        assert not is_canonical("ebitda_margin_2")

    def test_the_marker_inputs_the_research_note_asked_for_are_present(self):
        """docs/investment-markers.md names these as the first dependency."""
        for name in (
            "receivables",
            "inventory",
            "payables",
            "depreciation_amortisation",
            "stock_based_compensation",
            "goodwill",
            "intangible_assets",
            "short_term_debt",
            "ebit",
            "pretax_income",
            "tax_expense",
            "research_and_development",
            "lease_liabilities",
            "retained_earnings",
            "long_term_debt",
            "net_ppe",
        ):
            assert name in EXTRACTABLE_METRICS, name


class TestPromptStaysInStepWithTheGate:
    def test_every_extractable_metric_is_named_in_the_prompt(self):
        """The regression: the prompt used to omit interest_expense and the
        current-assets pair, so three names the gate accepted were never asked
        for."""
        missing = [
            name
            for name in sorted(EXTRACTABLE_METRICS)
            # A word boundary matters: `\bebit\b` must not be satisfied by `ebitda`.
            if not re.search(rf"\b{re.escape(name)}\b", FILING_EXTRACTION_INSTRUCTION)
        ]
        assert missing == []

    def test_the_prompt_names_no_metric_outside_the_gate(self):
        """The other direction: a name the prompt asks for and the gate rejects
        would be extracted and silently discarded on arrival.

        Read from `metric_fields.prompt_block`, which is what builds the live prompt.
        The equivalent function in `metrics.py` was deleted when the vocabulary became
        dynamic -- it was a second generator of the same block, and two of those is one
        more than can be kept in step with the gate.
        """
        from awltux.analysis.metric_fields import prompt_block

        asked: set[str] = set()
        for line in prompt_block().splitlines():
            _, _, names = line.partition(":")
            asked.update(name.strip() for name in names.split(",") if name.strip())
        assert asked == set(EXTRACTABLE_METRICS)

    def test_the_prompt_groups_metrics_by_statement(self):
        from awltux.analysis.metric_fields import prompt_block

        generated = prompt_block()
        assert "income statement:" in generated
        assert "balance sheet:" in generated
        assert "cash flow:" in generated

    def test_the_prompt_never_asks_the_model_to_divide(self):
        """Derived ratios are ours. A model asked for `roce` can return one with a
        citation attached, and the analysis layer would then read it as if it had
        computed it."""
        present = [
            name
            for name in sorted(DERIVED_METRICS)
            if re.search(rf"\b{re.escape(name)}\b", FILING_EXTRACTION_INSTRUCTION)
        ]
        assert present == []


class TestUnitScale:
    """A filing states its figures in whatever it likes, and the stored periods do not.

    `SOURCE_PREFERENCE` ranks `llm_extraction` above every provider, so an extracted
    period stored at the document's own scale would be the one that *wins* every
    comparison -- MSFT's revenue at 331,839 where the provider sources hold 331,839,012,864.
    No marker would catch it, because the ratios are scale-invariant.
    """

    @pytest.mark.parametrize(
        "stated, scale",
        [
            ("millions", 1e6),
            ("in millions", 1e6),
            ("USD millions", 1e6),
            ("thousands", 1e3),
            ("thousands of Canadian dollars", 1e3),
            ("($000s)", 1e3),
            ("US$'000", 1e3),
            ("in $000's", 1e3),
            ("actual", 1.0),
            ("units", 1.0),
            ("billions", 1e9),
            # A document that names two is read as the larger: the vague catch-alls are
            # tried last, so "units" cannot answer for a filing that said "thousands".
            ("in thousands of units", 1e3),
        ],
    )
    def test_a_stated_scale_is_read(self, stated, scale):
        assert unit_scale(stated) == scale

    @pytest.mark.parametrize(
        "stated",
        ["", None, "not stated", "bananas", "per share", "not actually stated"],
    )
    def test_an_unstated_or_unknown_scale_is_refused(self, stated):
        """`None` rather than a default of 1.0. Assuming "actual" is the one guess that
        silently multiplies every figure by a million, and nothing later would notice.

        "not actually stated" is here because matching is on whole words: a substring rule
        finds "actual" inside "actually" and reads a refusal as actual units."""
        assert unit_scale(stated) is None

    def test_the_apostrophe_spelling_of_thousands_is_read(self):
        """`($000's)` is the same notation as `($000s)`, and the token is split on the
        apostrophe rather than searched for as a substring."""
        assert unit_scale("in $000's") == 1e3
        assert unit_scale("US$'000") == 1e3
