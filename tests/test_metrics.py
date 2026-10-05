"""The canonical metric vocabulary, and the drift it exists to prevent.

The bug this guards against is silence. If a name is in the extractor's gate but
not in the prompt, the model is never asked for it and it simply never appears --
which is indistinguishable from a company that does not report it. If a name is in
the prompt but not the gate, it is extracted and then thrown away. Neither leaves
a trace at runtime, so both need a test rather than a comment.
"""

from __future__ import annotations

import re

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
    prompt_metric_names,
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
        would be extracted and silently discarded on arrival."""
        asked: set[str] = set()
        for line in prompt_metric_names().splitlines():
            _, _, names = line.partition(":")
            asked.update(name.strip() for name in names.split(",") if name.strip())
        assert asked == set(EXTRACTABLE_METRICS)

    def test_the_prompt_groups_metrics_by_statement(self):
        generated = prompt_metric_names()
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
