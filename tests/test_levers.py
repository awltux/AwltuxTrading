"""The lever vocabulary, the records written against it, and the pages that read them.

The feature exists to answer one question across instruments -- *what is affected if this
mover changes?* -- so the tests are mostly about the two things that question depends on: that
a lever is one of a fixed vocabulary rather than free text, and that a direction means the same
thing on every instrument it is recorded against.
"""

from __future__ import annotations

import argparse

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from awltux.analysis import levers
from awltux.db import Instrument, InstrumentLever, ResearchReport, session_scope


class TestTheVocabulary:
    def test_no_key_is_repeated(self):
        keys = [lever.key for lever in levers.LEVERS]
        assert len(keys) == len(set(keys))

    def test_every_lever_names_a_real_group_and_a_page_prints_it(self):
        """A lever in a group no page prints would be a lever with no heading."""
        assert {lever.group for lever in levers.LEVERS} == set(levers.GROUP_ORDER)
        assert all(group in levers.GROUP_LABELS for group in levers.GROUP_ORDER)
        assert all(group in levers.GROUP_NOTES for group in levers.GROUP_ORDER)

    def test_every_lever_says_how_it_reaches_a_business(self):
        """The channel is the rule a recorder files against, so a missing one is a lever
        nobody can place -- and it is prose, so the check is its shape rather than a schema."""
        for lever in levers.LEVERS:
            assert len(lever.channel) > 40, lever.key
            assert lever.channel.endswith("."), lever.key

    @pytest.mark.parametrize(
        "written",
        ["interest_rates", "Interest rates", "interest rates", "INTEREST  RATES"],
    )
    def test_a_reader_s_word_finds_its_key(self, written):
        assert levers.resolve(written) == "interest_rates"

    def test_an_unknown_word_resolves_to_nothing_rather_than_a_neighbour(self):
        """The failure this prevents: 'interest' filed under the nearest string, say
        `economic_growth`. A wrong lever is a claim about what moves a business, and nothing
        downstream would show the substitution."""
        assert levers.resolve("interest") is None
        assert levers.resolve("") is None
        assert levers.resolve("vibes") is None

    def test_every_label_is_reachable_by_its_own_text(self):
        """The alias table is built from the vocabulary, so this is the guard that it stayed
        built: a label a reader can see on the page but not name in the CLI is a trap."""
        for lever in levers.LEVERS:
            assert levers.resolve(lever.label) == lever.key

    def test_an_unknown_key_still_prints_as_itself(self):
        """Rows are read back from storage, and a lever retired between two versions must
        still render as its key rather than as blank."""
        assert levers.label_for("carrying_costs") == "carrying_costs"
        assert levers.channel_for("carrying_costs") == ""
        assert levers.group_of("carrying_costs") == ""


class TestThePromptOffersIt:
    """The vocabulary reaches the model through one generator, so it cannot offer a lever the
    reader then refuses -- the invariant `metric_fields` was written to protect."""

    def test_every_lever_is_listed_once_and_nothing_else_is(self):
        from awltux.llm.prompts import research_instruction

        block = levers.prompt_block()
        instruction = research_instruction("Test Co (TEST_US_EQ)")

        assert block in instruction, "the prompt must carry the vocabulary"
        assert block.count("\n") + 1 == len(levers.LEVERS)
        for lever in levers.LEVERS:
            assert f"- {lever.key}: {lever.label}" in block

    def test_the_schema_asks_for_the_block(self):
        """A vocabulary the prompt lists but the schema does not ask for is a field the model
        has no reason to fill."""
        from awltux.llm.prompts import research_instruction

        assert '"levers"' in research_instruction("Test Co (TEST_US_EQ)")


class TestParsingAnExposure:
    def test_the_three_parts_are_read(self):
        exposure = levers.parse("interest_rates=negative:secondary")
        assert (exposure.lever, exposure.direction, exposure.strength) == (
            "interest_rates",
            "negative",
            "secondary",
        )

    def test_strength_defaults_to_primary(self):
        assert levers.parse("inflation=positive").strength == levers.PRIMARY

    def test_the_label_may_be_written_instead_of_the_key(self):
        assert levers.parse("Exchange rates=mixed").lever == "exchange_rates"

    def test_an_unknown_lever_is_refused_and_lists_the_ones_that_exist(self):
        with pytest.raises(ValueError) as raised:
            levers.parse("rates=positive")
        assert "interest_rates" in str(raised.value)

    def test_a_bad_direction_is_refused_rather_than_defaulted(self):
        """Silently reading `up` as `unknown` would store a judgement nobody made."""
        with pytest.raises(ValueError, match="direction"):
            levers.parse("inflation=up")

    def test_a_bad_strength_is_refused(self):
        with pytest.raises(ValueError, match="strength"):
            levers.parse("inflation=positive:enormous")


@pytest.fixture()
def named_instrument(session):
    """One instrument, committed -- the CLI and a request each open their own session."""
    session.add(
        Instrument(
            t212_ticker="TESTl_EQ",
            name="Test plc",
            currency_code="GBP",
            in_universe=True,
        )
    )
    session.commit()
    return "TESTl_EQ"


class TestRecording:
    def test_a_lever_is_written_and_read_back(self, session, named_instrument):
        levers.record(
            session,
            named_instrument,
            [levers.Exposure("interest_rates", levers.NEGATIVE, levers.PRIMARY)],
            reason="most of its debt is floating",
        )
        session.commit()
        stored = levers.stored(session, named_instrument)
        assert len(stored) == 1
        assert stored[0].lever == "interest_rates"
        assert stored[0].direction == levers.NEGATIVE
        assert stored[0].reason == "most of its debt is floating"

    def test_recording_the_same_lever_again_replaces_the_judgement(
        self, session, named_instrument
    ):
        """One row per (instrument, lever): the question the page asks is what the exposure
        *is*, so a second recording is a correction rather than a second opinion."""
        levers.record(session, named_instrument, [levers.Exposure("inflation", levers.POSITIVE)])
        levers.record(
            session,
            named_instrument,
            [levers.Exposure("inflation", levers.NEGATIVE)],
            reason="pricing power went",
        )
        session.commit()
        rows = session.execute(
            select(InstrumentLever).where(
                InstrumentLever.instrument_t212_ticker == named_instrument
            )
        ).scalars().all()
        assert len(rows) == 1
        assert rows[0].direction == levers.NEGATIVE
        assert rows[0].reason == "pricing power went"
        assert rows[0].updated_at >= rows[0].created_at

    def test_a_reason_nobody_gave_is_recorded_as_one(self, session, named_instrument):
        levers.record(session, named_instrument, [levers.Exposure("inflation")])
        assert levers.stored(session, named_instrument)[0].reason == levers.NO_REASON

    def test_a_direction_outside_the_vocabulary_is_stored_as_unknown(
        self, session, named_instrument
    ):
        """The route validates, so this is the library refusing to invent a direction for a
        caller that skipped it: `unknown` is an answer, and a made-up one is not."""
        levers.record(
            session, named_instrument, [levers.Exposure("inflation", direction="sideways")]
        )
        assert levers.stored(session, named_instrument)[0].direction == levers.UNKNOWN

    def test_an_unknown_lever_is_refused_at_the_write(self, session, named_instrument):
        with pytest.raises(ValueError):
            levers.record(session, named_instrument, [levers.Exposure("carrying_costs")])

    def test_forgetting_one_leaves_the_others(self, session, named_instrument):
        levers.record(
            session,
            named_instrument,
            [levers.Exposure("inflation"), levers.Exposure("labour_costs")],
        )
        session.commit()
        assert levers.forget(session, named_instrument, "inflation") == 1
        assert [exposure.lever for exposure in levers.stored(session, named_instrument)] == [
            "labour_costs"
        ]

    def test_forgetting_everything_reports_nothing_the_second_time(
        self, session, named_instrument
    ):
        levers.record(session, named_instrument, [levers.Exposure("inflation")])
        session.commit()
        assert levers.forget(session, named_instrument) == 1
        assert levers.forget(session, named_instrument) == 0

    def test_a_primary_lever_is_listed_before_a_secondary_one(self, session, named_instrument):
        """The panel's order is the strength band first: the question a reader opens it with is
        what moves this business, not what is alphabetically first."""
        levers.record(
            session,
            named_instrument,
            [
                levers.Exposure("weather_and_climate", strength=levers.SECONDARY),
                levers.Exposure("interest_rates", strength=levers.PRIMARY),
            ],
        )
        session.commit()
        assert [exposure.lever for exposure in levers.stored(session, named_instrument)] == [
            "interest_rates",
            "weather_and_climate",
        ]

    def test_describe_fills_in_the_vocabulary_rather_than_the_row(
        self, session, named_instrument
    ):
        """The label and the channel are properties of the vocabulary. Storing them on the row
        would freeze the wording of a lever at the moment it was recorded and let two rows
        disagree about what a lever means."""
        levers.record(
            session, named_instrument, [levers.Exposure("interest_rates", levers.NEGATIVE)]
        )
        session.commit()
        described = levers.describe(levers.stored(session, named_instrument)[0])
        assert described["label"] == "Interest rates"
        assert described["group_label"] == levers.GROUP_LABELS["macro"]
        assert described["direction_label"] == levers.DIRECTION_LABELS[levers.NEGATIVE]
        assert described["channel"] == levers.channel_for("interest_rates")


class TestTheCrossInstrumentQuestion:
    """The query the feature exists for: which instruments does one lever move?"""

    @pytest.fixture()
    def universe(self, session):
        for ticker, name, sector, held in (
            ("BANKl_EQ", "Test Bank", "Financials", True),
            ("HOUSl_EQ", "Test Housebuilder", "Consumer Discretionary", False),
            ("UTILl_EQ", "Test Utility", "Utilities", False),
            ("OTHERl_EQ", "Test Other", "Technology", False),
        ):
            session.add(
                Instrument(
                    t212_ticker=ticker,
                    name=name,
                    currency_code="GBP",
                    in_universe=True,
                    is_held=held,
                    sector_group=sector,
                )
            )
        session.flush()
        levers.record(
            session,
            "BANKl_EQ",
            [levers.Exposure("interest_rates", levers.POSITIVE, levers.PRIMARY)],
            reason="the margin reprices faster than deposits",
        )
        levers.record(
            session,
            "HOUSl_EQ",
            [levers.Exposure("interest_rates", levers.NEGATIVE, levers.PRIMARY)],
            reason="mortgage affordability",
        )
        levers.record(
            session,
            "UTILl_EQ",
            [
                levers.Exposure("interest_rates", levers.NEGATIVE, levers.SECONDARY),
                levers.Exposure("regulation", levers.MIXED, levers.PRIMARY),
            ],
        )
        session.commit()
        return session

    def test_a_held_instrument_comes_first_within_its_strength_band(self, session, universe):
        rows = levers.instruments_for(session, "interest_rates")
        assert [row["ticker"] for row in rows] == ["BANKl_EQ", "HOUSl_EQ", "UTILl_EQ"]

    def test_each_row_carries_the_direction_recorded_for_it(self, session, universe):
        """The point of the page: one lever, opposite directions, readable without opening a
        single instrument. A bank and a housebuilder are the canonical pair."""
        rows = {
            row["ticker"]: row for row in levers.instruments_for(session, "interest_rates")
        }
        assert rows["BANKl_EQ"]["direction"] == levers.POSITIVE
        assert rows["HOUSl_EQ"]["direction"] == levers.NEGATIVE
        assert rows["BANKl_EQ"]["is_held"] is True

    def test_an_instrument_with_no_record_is_not_listed(self, session, universe):
        tickers = {row["ticker"] for row in levers.instruments_for(session, "interest_rates")}
        assert "OTHERl_EQ" not in tickers

    def test_a_lever_nothing_is_recorded_against_lists_nothing(self, session, universe):
        assert levers.instruments_for(session, "energy_costs") == []

    def test_totals_count_instruments_and_split_them_by_strength(self, session, universe):
        totals = levers.totals(session)
        assert totals["interest_rates"]["instruments"] == 3
        assert totals["interest_rates"]["primary"] == 2
        assert totals["interest_rates"]["secondary"] == 1
        assert "energy_costs" not in totals

    def test_coverage_counts_what_has_any_record_and_the_universe_it_sits_in(
        self, session, universe
    ):
        assert levers.coverage(session) == {"universe": 4, "recorded": 3, "held": 1}

    def test_an_excluded_instrument_drops_out_of_the_counts(self, session, universe):
        """Excluded means "not analysed", and a count that included it would promise a page
        the instrument no longer appears on."""
        session.get(Instrument, "HOUSl_EQ").excluded = True
        session.commit()
        assert levers.totals(session)["interest_rates"]["instruments"] == 2
        assert levers.coverage(session)["recorded"] == 2

    def test_an_instrument_outside_the_universe_is_not_counted(self, session, universe):
        session.get(Instrument, "UTILl_EQ").in_universe = False
        session.commit()
        assert levers.coverage(session)["recorded"] == 2


class TestTheDescriptionComesFromTheDeepDive:
    """`business.summary` and friends are read out of the stored report, not copied onto the
    instrument -- one place to argue with, and one place a verdict rests on."""

    @staticmethod
    def _report(subject_id: str, result: dict, status: str = "done") -> ResearchReport:
        return ResearchReport(
            subject_type="instrument",
            subject_id=subject_id,
            status=status,
            title=subject_id,
            prompt="p",
            prompt_sha256="0" * 64,
            bytes=1,
            verdict="buy",
            result=result,
        )

    def test_no_report_yields_nothing_rather_than_an_empty_description(self, session):
        from awltux.web import queries

        session.add(Instrument(t212_ticker="NONEl_EQ", name="Nobody", in_universe=True))
        session.commit()
        assert queries.latest_business(session, "NONEl_EQ") is None

    def test_a_report_with_a_business_block_is_read(self, session):
        from awltux.web import queries

        session.add(
            self._report(
                "TOLDl_EQ",
                {
                    "business": {
                        "summary": "Sells widgets to builders.",
                        "moat": "The only widget that works in the rain.",
                        "competition": "Two rivals, neither accredited.",
                    }
                },
            )
        )
        session.commit()
        business = queries.latest_business(session, "TOLDl_EQ")
        assert business["summary"] == "Sells widgets to builders."
        assert business["moat"] == "The only widget that works in the rain."
        assert business["competition"] == "Two rivals, neither accredited."
        assert business["verdict"] == "buy"
        assert business["report_id"] is not None

    def test_a_report_that_said_nothing_about_the_business_reads_as_none(self, session):
        """The page must be able to tell "the model was silent" from "there is no report" --
        both print nothing, but only one of them is worth offering the Research tab for."""
        from awltux.web import queries

        session.add(self._report("QUIETl_EQ", {"business": {"summary": "   ", "moat": None}}))
        session.commit()
        assert queries.latest_business(session, "QUIETl_EQ") is None

    def test_a_running_report_does_not_describe_the_business(self, session):
        from awltux.web import queries

        session.add(
            self._report(
                "RUNl_EQ", {"business": {"summary": "Nearly done."}}, status="running"
            )
        )
        session.commit()
        assert queries.latest_business(session, "RUNl_EQ") is None


class TestTheLeversPages:
    def test_the_page_lists_every_lever_in_its_group(self, client, session):
        response = client.get("/levers")
        assert response.status_code == 200
        for lever in levers.LEVERS:
            assert lever.label in response.text
        for group in levers.GROUP_ORDER:
            assert levers.GROUP_LABELS[group] in response.text

    def test_a_lever_with_no_records_says_so_rather_than_showing_an_empty_table(
        self, client
    ):
        response = client.get("/levers/energy_costs")
        assert response.status_code == 200
        assert "No in-universe instrument is recorded" in response.text

    def test_an_unknown_lever_is_a_404(self, client):
        assert client.get("/levers/carrying_costs").status_code == 404

    def test_one_lever_lists_the_instruments_that_record_it(self, client, session):
        session.add(
            Instrument(
                t212_ticker="BANKl_EQ",
                name="Test Bank",
                in_universe=True,
                is_held=True,
                sector_group="Financials",
            )
        )
        session.flush()
        levers.record(
            session,
            "BANKl_EQ",
            [levers.Exposure("interest_rates", levers.POSITIVE)],
            reason="the margin reprices faster than deposits",
        )
        session.commit()
        response = client.get("/levers/interest_rates")
        assert response.status_code == 200
        assert "Test Bank" in response.text
        assert "the margin reprices faster than deposits" in response.text
        assert "Rises help" in response.text

    def test_the_nav_offers_the_page(self, client):
        assert '<a href="/levers"' in client.get("/dashboard").text


class TestRecordingFromThePage:
    @pytest.fixture()
    def page_instrument(self, session):
        session.add(
            Instrument(
                t212_ticker="FORMl_EQ",
                name="Form plc",
                in_universe=True,
                is_held=True,
            )
        )
        session.commit()
        return "FORMl_EQ"

    def test_the_form_records_a_lever(self, client, session, page_instrument):
        response = client.post(
            "/instrument/FORMl_EQ/levers",
            data={
                "lever": "interest_rates",
                "direction": "negative",
                "strength": "primary",
                "reason": "floating-rate debt",
                "tab": "decision",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert "levers=lever-recorded" in response.headers["location"]
        with session_scope() as scope:
            stored = levers.stored(scope, page_instrument)
        assert stored[0].direction == "negative"
        assert stored[0].reason == "floating-rate debt"

    def test_the_form_refuses_a_lever_outside_the_vocabulary(
        self, client, session, page_instrument
    ):
        response = client.post(
            "/instrument/FORMl_EQ/levers",
            data={"lever": "carrying_costs", "direction": "negative", "tab": "decision"},
            follow_redirects=False,
        )
        assert "levers=unknown-lever" in response.headers["location"]
        with session_scope() as scope:
            assert levers.stored(scope, page_instrument) == []

    def test_the_form_refuses_a_direction_outside_the_vocabulary(
        self, client, session, page_instrument
    ):
        response = client.post(
            "/instrument/FORMl_EQ/levers",
            data={"lever": "inflation", "direction": "sideways", "tab": "decision"},
            follow_redirects=False,
        )
        assert "levers=bad-direction" in response.headers["location"]
        with session_scope() as scope:
            assert levers.stored(scope, page_instrument) == []

    def test_recording_again_replaces_rather_than_adds(self, client, session, page_instrument):
        for direction in ("positive", "negative"):
            client.post(
                "/instrument/FORMl_EQ/levers",
                data={"lever": "inflation", "direction": direction, "tab": "decision"},
                follow_redirects=False,
            )
        with session_scope() as scope:
            stored = levers.stored(scope, page_instrument)
        assert len(stored) == 1
        assert stored[0].direction == "negative"

    def test_an_outcome_code_that_means_nothing_prints_nothing(self, client, page_instrument):
        """Nothing a caller puts in the query string becomes page text: the sentence is chosen
        from a fixed table in the route, keyed by a code."""
        response = client.get("/instrument/FORMl_EQ?levers=%3Cscript%3Ealert(1)%3C/script%3E")
        assert response.status_code == 200
        assert "alert(1)" not in response.text

    def test_the_instrument_page_shows_what_is_recorded_for_it(
        self, client, session, page_instrument
    ):
        levers.record(
            session,
            page_instrument,
            [levers.Exposure("exchange_rates", levers.MIXED, levers.PRIMARY)],
            reason="earns in dollars, reports in pounds",
        )
        session.commit()
        response = client.get("/instrument/FORMl_EQ?tab=levers")
        assert response.status_code == 200
        assert "Exchange rates" in response.text
        assert "earns in dollars, reports in pounds" in response.text

    def test_the_list_is_on_its_own_tab_and_not_above_the_tabs(self, client, session, page_instrument):
        """Asked for 2026-10-23: *"Move the instruments 'levers' list into its own tab."*

        It was in the panel above the tab strip, so it appeared on every visit to every tab; the
        description above the tabs is a summary and this is a list of records.
        """
        levers.record(
            session,
            page_instrument,
            [levers.Exposure("exchange_rates", levers.MIXED, levers.PRIMARY)],
            reason="earns in dollars, reports in pounds",
        )
        session.commit()

        on_levers = BeautifulSoup(client.get("/instrument/FORMl_EQ?tab=levers").text, "lxml")
        assert on_levers.select_one("#levers") is not None

        on_decision = BeautifulSoup(client.get("/instrument/FORMl_EQ?tab=decision").text, "lxml")
        assert on_decision.select_one("#levers") is None
        assert on_decision.select_one(".business-profile") is not None, (
            "the description is still above the tabs; only the list moved"
        )
        assert "earns in dollars, reports in pounds" not in on_decision.get_text(" ")

    def test_the_instrument_page_says_when_nothing_is_recorded(
        self, client, session, page_instrument
    ):
        """An empty panel would read as a broken query. "Nobody has written it down" and
        "nothing moves this business" are different claims and the page makes the first."""
        response = client.get("/instrument/FORMl_EQ?tab=levers")
        assert "Nothing is recorded against this business" in response.text

    def test_forgetting_from_the_page_removes_the_row(self, client, session, page_instrument):
        levers.record(session, page_instrument, [levers.Exposure("inflation")])
        session.commit()
        response = client.post(
            "/instrument/FORMl_EQ/levers/inflation/forget",
            data={"tab": "decision"},
            follow_redirects=False,
        )
        assert "levers=lever-forgotten" in response.headers["location"]
        with session_scope() as scope:
            assert levers.stored(scope, page_instrument) == []


class TestTheCommandLine:
    def test_set_records_and_prints_what_it_wrote(self, session, named_instrument, capsys):
        from awltux.cli import cmd_levers_set

        code = cmd_levers_set(
            argparse.Namespace(
                ticker=named_instrument,
                exposure=["interest_rates=negative:primary"],
                reason="floating-rate debt",
                source="",
            )
        )
        assert code == 0
        assert "interest_rates" in capsys.readouterr().out
        with session_scope() as scope:
            assert levers.stored(scope, named_instrument)[0].reason == "floating-rate debt"

    def test_set_refuses_a_bad_argument_without_writing_the_good_ones(
        self, session, named_instrument, capsys
    ):
        """A half-applied command is worse than a refused one, so every argument is parsed
        before anything is written."""
        from awltux.cli import cmd_levers_set

        code = cmd_levers_set(
            argparse.Namespace(
                ticker=named_instrument,
                exposure=["inflation=positive", "inflation=sideways"],
                reason="",
                source="",
            )
        )
        assert code == 2
        assert "direction" in capsys.readouterr().err
        with session_scope() as scope:
            assert levers.stored(scope, named_instrument) == []

    def test_set_refuses_an_instrument_that_does_not_exist(self, session, capsys):
        from awltux.cli import cmd_levers_set

        code = cmd_levers_set(
            argparse.Namespace(
                ticker="NONE l_EQ", exposure=["inflation=positive"], reason="", source=""
            )
        )
        assert code == 2
        assert "no such instrument" in capsys.readouterr().err

    def test_forget_reports_what_went(self, session, named_instrument, capsys):
        from awltux.cli import cmd_levers_forget

        levers.record(session, named_instrument, [levers.Exposure("inflation")])
        session.commit()
        assert (
            cmd_levers_forget(argparse.Namespace(ticker=named_instrument, lever="inflation")) == 0
        )
        assert "1 record(s)" in capsys.readouterr().out

    def test_show_says_not_recorded_rather_than_nothing_moves_it(
        self, session, named_instrument, capsys
    ):
        from awltux.cli import cmd_levers_show

        assert cmd_levers_show(argparse.Namespace(ticker=named_instrument)) == 0
        assert "no levers recorded" in capsys.readouterr().out

    def test_the_vocabulary_prints_grouped(self, capsys):
        from awltux.cli import cmd_levers_list

        assert cmd_levers_list(argparse.Namespace()) == 0
        out = capsys.readouterr().out
        for lever in levers.LEVERS:
            assert lever.key in out
