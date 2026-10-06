"""The price panel with nothing in it.

An instrument with no stored bars used to render a blank gap where the chart
should be, with a bare "No price history stored." underneath. That sentence is
true of four situations needing four different responses, so the panel could not
tell the reader whether the gap would close on its own or never close at all.

These tests pin both halves of the fix: the frame is always drawn, and the words
underneath say which situation this is.
"""

from __future__ import annotations

import datetime as dt
import json
import re

from awltux.db import IngestRun, InstrumentAlias
from awltux.web import queries
from tests.helpers import make_bars, make_instrument

TICKER = "AIT_US_EQ"


def _attribute(html: str, name: str) -> str:
    """The raw value of an attribute, whichever quote style it was written with."""
    match = re.search(rf"{name}=(['\"])(.*?)\1", html, re.S)
    assert match, f"{name} not found in the rendered page"
    return match.group(2)


def _instrument(session, **overrides):
    """An instrument in the universe with a resolved symbol, unless told otherwise."""
    # ``make_instrument`` defaults the provider symbol to AAPL, whoever the ticker
    # is; this fixture wants the symbol to match the instrument it describes.
    overrides.setdefault("yahoo_symbol", "AIT")
    instrument = make_instrument(TICKER, name="Applied Industrial Technologies", **overrides)
    session.add(instrument)
    session.flush()
    return instrument


def _bars(session, closes):
    session.add_all(make_bars(TICKER, closes))
    session.flush()


def _price_run(session, **overrides):
    fields = {
        "job": "price_eod",
        "started_at": dt.datetime(2026, 5, 1, 21, 0, tzinfo=dt.UTC),
        "finished_at": dt.datetime(2026, 5, 1, 21, 4, tzinfo=dt.UTC),
        "ok": True,
        "items_seen": 10,
        "items_written": 400,
    }
    fields.update(overrides)
    run = IngestRun(**fields)
    session.add(run)
    session.flush()
    return run


class TestTheWaitingNote:
    def test_enough_bars_means_nothing_to_say(self, session):
        assert queries.price_history_waiting_note(session, TICKER, bars=2) is None
        assert queries.price_history_waiting_note(session, TICKER, bars=250) is None

    def test_one_bar_says_a_line_needs_two(self, session):
        note = queries.price_history_waiting_note(session, TICKER, bars=1)
        assert note is not None
        assert "one daily bar" in note
        assert "needs two" in note

    def test_an_instrument_outside_the_universe_says_it_will_not_fill_itself(self, session):
        """``load_price_targets`` only ever asks for universe instruments, so an
        instrument outside the universe does not fill on the next run, or the one
        after that. Distinguished from an empty universe by another named instrument
        being in it."""
        _instrument(session, in_universe=False)
        session.add(make_instrument("OTHER_US_EQ", yahoo_symbol="OTHER", in_universe=True))
        session.flush()

        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "not in the analysed universe" in note
        assert "stays empty until" in note

    def test_an_empty_universe_is_reported_as_the_pipeline_not_the_instrument(self, session):
        """The live database's actual state: nothing has been selected, so *every*
        instrument reads as "not in the universe". Saying that per-instrument would
        send the reader looking for a filter that excluded this one name."""
        _instrument(session, in_universe=False)

        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "no instrument is in the analysed universe yet" in note
        assert "universe refresh has run" in note

    def test_an_excluded_instrument_says_so(self, session):
        _instrument(session, excluded=True)
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "excluded from analysis" in note

    def test_an_unresolved_symbol_names_the_missing_step(self, session):
        _instrument(session, yahoo_symbol=None)
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "no Yahoo symbol has been resolved" in note

    def test_a_resolved_symbol_with_no_run_yet_says_it_will_fetch(self, session):
        _instrument(session)
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "AIT" in note
        assert "has not recorded a run yet" in note

    def test_a_run_that_stored_nothing_is_reported_with_its_time(self, session):
        _instrument(session)
        _price_run(session)
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "stored no bars for it" in note
        assert "2026-05-01" in note

    def test_a_failed_run_is_reported_as_a_failure(self, session):
        _instrument(session)
        _price_run(session, ok=False, error="yahoo returned 429")
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "failed" in note
        assert "yahoo returned 429" in note

    def test_a_symbol_the_provider_had_no_history_for_is_not_blamed_on_the_schedule(self, session):
        """A run that asked and got nothing needs a different response from one
        that never reached the symbol: the first will not fix itself."""
        _instrument(session)
        _price_run(session, detail={"failed": ["AIT"], "failed_count": 1})
        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "returned no history" in note
        assert "suspended" in note

    def test_the_recorded_symbol_lookup_note_travels_with_the_answer(self, session):
        _instrument(session, in_universe=False)
        session.add(
            InstrumentAlias(
                instrument_t212_ticker=TICKER,
                provider="yahoo",
                symbol="AIT",
                confidence=0.4,
                method="name",
                note="two listings matched; not applied",
            )
        )
        session.flush()

        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        assert "The symbol lookup recorded: two listings matched; not applied" in note

    def test_an_alias_supplies_the_symbol_when_the_instrument_lacks_one(self, session):
        _instrument(session, yahoo_symbol=None)
        session.add(
            InstrumentAlias(
                instrument_t212_ticker=TICKER, provider="yahoo", symbol="AIT", confidence=0.9
            )
        )
        session.flush()

        note = queries.price_history_waiting_note(session, TICKER, bars=0)
        assert note is not None
        # Named the symbol rather than "no symbol resolved", which the alias forbids.
        assert "no Yahoo symbol has been resolved" not in note
        assert "AIT" in note


class TestTheInstrumentPage:
    def test_the_chart_attributes_are_parseable_json(self, client, session):
        """The bug that actually blanked the panel on any instrument with prices.

        ``tojson`` emits raw ``"`` and escapes only ``'``, so the double-quoted
        ``data-dates="[...]"`` ended at the first date and the browser read
        ``data-dates="["``. ``JSON.parse`` threw, the draw function returned, and
        the chart was blank -- for exactly the instruments that had data.
        """
        _instrument(session)
        _bars(session, [100.0, 101.0, 102.0, 103.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        series = _attribute(body, "data-series")
        dates = _attribute(body, "data-dates")
        assert json.loads(series) == [100.0, 101.0, 102.0, 103.0]
        assert len(json.loads(dates)) == 4

    def test_the_canvas_is_rendered_with_no_bars_at_all(self, client, session):
        _instrument(session, in_universe=False)
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert 'id="price-chart"' in body, "the frame must be drawn even when empty"
        assert "Waiting for data" in body
        assert "no instrument is in the analysed universe yet" in body
    def test_the_empty_canvas_carries_the_data_the_script_needs(self, client, session):
        """The drawing happens in the browser, so what the page owes is the element,
        the (empty) series, and the reason as a tooltip rather than as canvas text
        that no screen reader can reach."""
        _instrument(session, in_universe=False)
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert json.loads(_attribute(body, "data-series")) == []
        assert 'title="Waiting for data' in body

    def test_a_covered_instrument_shows_the_chart_and_not_the_waiting_notice(self, client, session):
        _instrument(session)
        _bars(session, [100.0, 101.0, 102.0, 103.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert "Waiting for data" not in body
        assert "4 daily bars" in body

    def test_a_single_bar_is_still_reported_as_waiting(self, client, session):
        _instrument(session)
        _bars(session, [100.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text
        assert "Waiting for data" in body
        assert "needs two" in body
