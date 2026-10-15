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

from awltux.db import IngestRun, InstrumentAlias, ValuationRun
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


class TestTheFairValueOverlay:
    """The model's answer drawn against the price it is an answer about.

    The panel showed the market and nothing else, so the comparison this whole
    application exists to make was on a different tab. Measured on the live database
    2026-10-15: 73 instruments held a drawn valuation, and the axis wanted to grow by a
    median of 2.1x to reach it -- so most of these are about *where* the band lands
    rather than about it being absent.

    The bars are dated explicitly here. `make_bars` defaults to the last few days before
    today, and a valuation is a *date* on that axis: a step dated before the window is
    correctly dropped, so a test that used the default start would be asserting the
    empty overlay and calling it a pass.
    """

    #: Bars run 2026-05-01, 05-02, 05-03 -- the dates the valuations below name.
    START = dt.date(2026, 5, 1)

    @classmethod
    def _priced(cls, session, closes):
        session.add_all(make_bars(TICKER, closes, start=cls.START))
        session.flush()

    @staticmethod
    def _valuation(session, *, day, low, base, high, status="ok", hour=17):
        session.add(
            ValuationRun(
                instrument_t212_ticker=TICKER,
                as_of=dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00"),
                fair_value_low=low,
                fair_value_base=base,
                fair_value_high=high,
                status=status,
            )
        )
        session.flush()

    def test_a_step_starts_on_its_own_bar_and_ends_at_the_edge(self, session):
        _instrument(session)
        self._priced(session, [100.0, 101.0, 102.0])
        self._valuation(session, day="2026-05-02", low=90.0, base=110.0, high=130.0)
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert [step["date"] for step in overlay.steps] == ["2026-05-02"]
        assert overlay.steps[0]["base"] == 110.0
        assert (overlay.steps[0]["low"], overlay.steps[0]["high"]) == (90.0, 130.0)
        assert overlay.offscale == 0

    def test_the_last_calculation_of_a_bar_is_the_one_that_stands(self, session):
        """The job runs on an hourly rotation, so a day usually holds several readings.

        Drawing each of them is a smudge at daily resolution: the chart's x axis is the
        stored bar dates, and 13 calculations of one day share a single pixel column.
        """
        _instrument(session)
        self._priced(session, [100.0, 101.0])
        self._valuation(session, day="2026-05-02", low=80.0, base=100.0, high=120.0, hour=9)
        self._valuation(session, day="2026-05-02", low=90.0, base=111.0, high=132.0, hour=17)
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert len(overlay.steps) == 1, "one bar, one step"
        assert overlay.steps[0]["base"] == 111.0, "the later calculation of the day wins"

    def test_a_refused_valuation_is_not_drawn_as_zero(self, session):
        """``insufficient_data`` is the model declining to answer, not answering zero.

        The row stores no band at all -- `blend` returns ``None`` for the base and 0.0
        for the range -- so a chart that plotted it would invent the number the model
        refused to give, at the bottom of the axis where "worthless" lives.
        """
        _instrument(session)
        self._priced(session, [100.0, 101.0])
        self._valuation(
            session, day="2026-05-02", low=0.0, base=None, high=0.0, status="insufficient_data"
        )
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert overlay.steps == []
        assert overlay.offscale == 0, "a refusal is not an off-scale band"

    def test_a_band_below_the_price_is_drawn(self, session):
        """The ordinary case, and the one a "does it overlap the axis" rule would drop.

        GWW on 2026-10-15: prices 918-1402 against a band of 178-420. That gap -- the
        market paying four times what the model says the business is worth -- is the
        single most interesting thing on the chart.
        """
        _instrument(session)
        self._priced(session, [1000.0, 1200.0, 1400.0])
        self._valuation(session, day="2026-05-02", low=178.0, base=299.0, high=420.0)
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert len(overlay.steps) == 1
        assert overlay.offscale == 0

    def test_a_band_far_past_every_price_is_counted_rather_than_plotted(self, session):
        """The three live instruments this is for, and the measurement behind the ratio.

        A linear axis holding AAPL's stored base of 2.27e61 against a $343 price is not a
        chart with an annotation on it: nineteen months of price collapse into the bottom
        pixel, and the panel goes from working to unreadable. The band is counted, and
        the template says how many -- a missing red line must never be a mystery.
        """
        _instrument(session)
        self._priced(session, [100.0, 101.0])
        self._valuation(session, day="2026-05-02", low=9.09e60, base=2.27e61, high=3.64e61)
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert overlay.steps == []
        assert overlay.offscale == 1

    def test_a_valuation_older_than_the_chart_is_left_off_it(self, session):
        """The left edge is a real boundary: a step there would claim a date it never had."""
        _instrument(session)
        self._priced(session, [100.0, 101.0])
        self._valuation(session, day="2020-01-01", low=90.0, base=110.0, high=130.0)
        history = queries.price_history(session, TICKER, limit=400)

        overlay = queries.price_valuations(session, TICKER, history)

        assert overlay.steps == []
        assert overlay.offscale == 0

    def test_no_bars_means_no_overlay(self, session):
        _instrument(session)

        overlay = queries.price_valuations(session, TICKER, [])

        assert overlay.steps == []
        assert overlay.offscale == 0


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

        body = client.get(f"/instrument/{TICKER}?tab=price").text
        series = _attribute(body, "data-series")
        dates = _attribute(body, "data-dates")
        assert json.loads(series) == [100.0, 101.0, 102.0, 103.0]
        assert len(json.loads(dates)) == 4

    def test_the_canvas_is_rendered_with_no_bars_at_all(self, client, session):
        _instrument(session, in_universe=False)
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text
        assert 'id="price-chart"' in body, "the frame must be drawn even when empty"
        assert "Waiting for data" in body
        assert "no instrument is in the analysed universe yet" in body
    def test_the_empty_canvas_carries_the_data_the_script_needs(self, client, session):
        """The drawing happens in the browser, so what the page owes is the element,
        the (empty) series, and the reason as a tooltip rather than as canvas text
        that no screen reader can reach."""
        _instrument(session, in_universe=False)
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text
        assert json.loads(_attribute(body, "data-series")) == []
        assert 'title="Waiting for data' in body

    def test_a_covered_instrument_shows_the_chart_and_not_the_waiting_notice(self, client, session):
        _instrument(session)
        _bars(session, [100.0, 101.0, 102.0, 103.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text
        assert "Waiting for data" not in body
        assert "4 daily bars" in body

    def test_a_single_bar_is_still_reported_as_waiting(self, client, session):
        _instrument(session)
        _bars(session, [100.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text
        assert "Waiting for data" in body
        assert "needs two" in body

    def test_the_fair_value_steps_reach_the_script_as_json(self, client, session):
        """Single-quoted, like every other attribute here: `tojson` emits raw quotes."""
        _instrument(session)
        # Dated, not `make_bars`' default: a valuation is a date on this axis, and one
        # dated before the first bar is correctly left off the chart entirely.
        session.add_all(make_bars(TICKER, [100.0, 101.0, 102.0, 103.0], start=dt.date(2026, 5, 1)))
        session.add(
            ValuationRun(
                instrument_t212_ticker=TICKER,
                as_of=dt.datetime(2026, 5, 3, 17, 0, tzinfo=dt.UTC),
                fair_value_low=90.0,
                fair_value_base=110.0,
                fair_value_high=130.0,
                status="ok",
            )
        )
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text

        steps = json.loads(_attribute(body, "data-valuations"))
        assert steps == [{"date": "2026-05-03", "base": 110.0, "low": 90.0, "high": 130.0}]
        # The key names both marks, because the two colours carry two different readings.
        assert "The red line is the fair value the model calculated" in body
        assert "pale yellow bar at its start" in body

    def test_a_chart_with_no_valuation_says_nothing_about_one(self, client, session):
        """A key for a line that is not there reads as a line that failed to draw."""
        _instrument(session)
        _bars(session, [100.0, 101.0, 102.0, 103.0])
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text

        assert json.loads(_attribute(body, "data-valuations")) == []
        assert "The red line is the fair value" not in body

    def test_an_off_scale_valuation_is_counted_where_the_reader_can_see_it(self, client, session):
        """The line is missing, so the page has to say why rather than leave a gap."""
        _instrument(session)
        session.add_all(make_bars(TICKER, [100.0, 101.0, 102.0, 103.0], start=dt.date(2026, 5, 1)))
        session.add(
            ValuationRun(
                instrument_t212_ticker=TICKER,
                as_of=dt.datetime(2026, 5, 3, 17, 0, tzinfo=dt.UTC),
                fair_value_low=9.09e60,
                fair_value_base=2.27e61,
                fair_value_high=3.64e61,
                status="ok",
            )
        )
        session.commit()

        body = client.get(f"/instrument/{TICKER}?tab=price").text

        assert json.loads(_attribute(body, "data-valuations")) == []
        assert "1 valuation is not drawn" in body
        assert "leave no room for the prices" in body
