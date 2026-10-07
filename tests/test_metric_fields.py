"""The vocabulary the filing extractor may ask for, and how it grows.

The list was a frozen `frozenset` feeding both the prompt and the gate, so the model
could only ever answer questions we already knew to ask. That is the whole of the
measured extraction gap: of 187 stored periods, 166 fail a composition check -- a stated
subtotal against the parts we hold -- and MSFT's residual is exactly the sum of two
captions the 46 names do not include.

The properties that matter are asserted here rather than in the prompt: the seed is the
code's, a stored row cannot override it, and **the prompt and the gate are built from the
same mapping** -- which is the invariant that a second generator of the block would
break.
"""

from __future__ import annotations

from awltux.analysis import metric_fields
from awltux.metrics import EXTRACTABLE_METRICS, STATED_METRICS


class TestTheSeed:
    def test_it_is_exactly_the_canonical_names(self):
        assert set(metric_fields.seed()) == set(EXTRACTABLE_METRICS)
        assert len(metric_fields.seed()) == len(STATED_METRICS)

    def test_every_seeded_field_knows_its_statement(self):
        """A name with no group would be listed under "other reported totals", which is
        where a discovered caption goes -- so a canonical one landing there would be a
        mis-filing rather than a gap."""
        groups = {field.group for field in metric_fields.seed().values()}
        assert groups <= {metric_fields.INCOME, metric_fields.BALANCE, metric_fields.CASH}
        assert metric_fields.OTHER not in groups

    def test_no_session_still_gives_a_usable_vocabulary(self):
        """A caller with no database -- a prompt built in a test, a CLI -- must get the
        canonical list rather than an empty one."""
        assert metric_fields.load(None).keys() == metric_fields.seed().keys()
        assert metric_fields.names(None) == frozenset(EXTRACTABLE_METRICS)


class TestGrowingIt:
    def test_a_discovered_field_is_remembered_and_offered(self, session):
        assert metric_fields.record(
            session, "short_term_investments", group=metric_fields.BALANCE,
            reason="closed a 55,908,000,000 current-assets residual", discovered_for="MSFT_US_EQ",
        )

        loaded = metric_fields.load(session)

        assert "short_term_investments" in loaded
        field = loaded["short_term_investments"]
        assert field.origin == "discovered"
        assert field.group == metric_fields.BALANCE
        assert field.discovered_for == "MSFT_US_EQ"
        assert "short_term_investments" in metric_fields.names(session)

    def test_recording_the_same_field_twice_is_not_a_second_entry(self, session):
        assert metric_fields.record(session, "short_term_investments", group=metric_fields.BALANCE)
        assert not metric_fields.record(session, "short_term_investments", group=metric_fields.BALANCE)

    def test_a_canonical_name_cannot_be_recorded_as_discovered(self, session):
        """The code owns those. A stored row claiming one would be a second source of
        truth for a name that is already declared."""
        assert not metric_fields.record(session, "total_assets", group=metric_fields.BALANCE)
        assert metric_fields.load(session)["total_assets"].origin == "canonical"

    def test_a_stored_row_cannot_override_a_canonical_group(self, session):
        """Written directly, the way a stale row from an older vocabulary would be."""
        from awltux.db import AppSetting

        session.add(
            AppSetting(
                key=metric_fields.SETTING_KEY,
                value={"total_assets": {"group": metric_fields.CASH, "origin": "discovered"}},
            )
        )
        session.flush()

        field = metric_fields.load(session)["total_assets"]

        assert field.group == metric_fields.BALANCE, "code wins over a stored row"
        assert field.origin == "canonical"

    def test_a_caption_that_is_not_a_key_is_refused(self, session):
        """The registry is a prompt. A sentence in it would be offered to a model as a
        field to fill, which is worse than not having the name at all."""
        for bad in (
            "Short-term investments",
            "short term investments",
            "SHORT_TERM",
            "_leading",
            "trailing_",
            "double__underscore",
            "x" * 49,
            "",
        ):
            assert not metric_fields.record(session, bad), bad
        assert set(metric_fields.load(session)) == set(EXTRACTABLE_METRICS)

    def test_an_unreadable_store_degrades_to_the_seed(self, session):
        """An empty vocabulary would silently stop the extractor accepting figures it
        currently stores, which is worse than ignoring a corrupt entry."""
        from awltux.db import AppSetting

        session.add(AppSetting(key=metric_fields.SETTING_KEY, value="not a mapping"))
        session.flush()

        assert set(metric_fields.load(session)) == set(EXTRACTABLE_METRICS)


class TestThePromptAndTheGateAgree:
    """The invariant, and the one a second generator of the block would break."""

    def test_a_discovered_field_reaches_both(self, session):
        from awltux.llm.extractors import validate_extraction
        from awltux.llm.prompts import filing_extraction_instruction

        metric_fields.record(
            session, "short_term_investments", group=metric_fields.BALANCE,
            reason="residual", discovered_for="MSFT_US_EQ",
        )
        vocabulary = metric_fields.load(session)

        instruction = filing_extraction_instruction(vocabulary)
        assert "short_term_investments" in instruction, "the prompt must offer it"

        entry = {"value": 55908.0, "span": "Short-term investments 55,908", "location": "Balance Sheets"}
        accepted = validate_extraction(
            {"metrics": {"short_term_investments": entry}}, allowed=frozenset(vocabulary)
        )
        assert "short_term_investments" in accepted.metrics, "the gate must accept it"

    def test_the_gate_still_refuses_a_name_nobody_offered(self):
        """Otherwise a model could invent a key, and `validate_extraction`'s whole job is
        to keep the stored vocabulary the one we asked for."""
        from awltux.llm.extractors import validate_extraction

        entry = {"value": 1.0, "span": "Invented metric 1", "location": "Nowhere"}
        result = validate_extraction({"metrics": {"made_up_metric": entry}})

        assert "made_up_metric" not in result.metrics
        assert any("made_up_metric" in discarded for discarded in result.discarded)

    def test_the_prompt_block_and_the_gate_come_from_one_mapping(self, session):
        """No second generator. `metrics.prompt_metric_names` was deleted for this
        reason: two functions producing the block is one more than can be kept in step
        with the gate, and being out of step is the bug this file exists for."""
        from awltux.llm.prompts import filing_extraction_instruction

        metric_fields.record(session, "equity_investments", group=metric_fields.BALANCE)
        vocabulary = metric_fields.load(session)

        block = metric_fields.prompt_block(vocabulary)
        instruction = filing_extraction_instruction(vocabulary)

        for name in vocabulary:
            assert name in block, name
            assert name in instruction, name
        assert "equity_investments" in block
        assert "other reported totals" not in block, "a balance-sheet caption is filed there"
