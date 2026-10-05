"""The prediction ledger: what was said, and how it turned out.

Every decision was already stored immutably — state, state hash, engine, prompt
hashes, both horizons' calls — but the only way to read one back was to know its id
and request the receipt. A record you cannot find again is not much of a record.

The distinction these tests exist to protect is between **scored** and **not
knowable yet**. An outcome is computed only once the window has elapsed *and* a
price exists at or after it, so on any given day most predictions have no result.
Showing a blank there would read as "scored flat"; hiding the row would make an
empty accuracy table look like a working one.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import DecisionOutcome, DecisionRun, Instrument
from awltux.web.queries import decision_history


def _decision(session, ticker: str = "TEST_US_EQ", **overrides):
    # The ticker column has a foreign key, so the instrument has to exist even
    # where the test does not care about it.
    if session.get(Instrument, ticker) is None:
        from tests.helpers import make_instrument

        session.add(make_instrument(ticker, name=f"{ticker} Holdings"))
        session.flush()

    values = {
        "instrument_t212_ticker": ticker,
        "state_sha256": "x" * 8,
        "engine": "deepseek",
        "long_term_action": "buy",
        "short_term_action": "hold",
        "confidence": 0.7,
        "created_at": dt.datetime(2026, 1, 1, 12, tzinfo=dt.UTC),
    }
    values.update(overrides)
    row = DecisionRun(**values)
    session.add(row)
    session.flush()
    return row


def _outcome(session, decision, *, horizon: str, days: int, return_pct: float, verdict: str):
    session.add(
        DecisionOutcome(
            decision_run_id=decision.id,
            horizon=horizon,
            horizon_days=days,
            price_at_decision=100.0,
            price_at_horizon=100.0 * (1 + return_pct / 100),
            return_pct=return_pct,
            verdict=verdict,
        )
    )
    session.flush()


class TestTheLedger:
    def test_it_lists_predictions_newest_first(self, session):
        _decision(session, created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        newer = _decision(session, created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))

        rows, total = decision_history(session)
        assert total == 2
        assert rows[0].decision.id == newer.id

    def test_a_prediction_carries_its_outcomes(self, session):
        decision = _decision(session)
        _outcome(session, decision, horizon="short_term", days=5, return_pct=3.2, verdict="direction_correct")

        rows, _ = decision_history(session)
        assert rows[0].scored is True
        assert rows[0].outcome("short_term", 5).return_pct == pytest.approx(3.2)

    def test_an_unelapsed_window_is_not_an_outcome(self, session):
        """Not knowable yet is a different state from scored flat."""
        _decision(session)

        rows, _ = decision_history(session)
        assert rows[0].scored is False
        assert rows[0].outcome("short_term", 5) is None

    def test_the_long_and_short_windows_are_kept_apart(self, session):
        decision = _decision(session)
        _outcome(session, decision, horizon="short_term", days=5, return_pct=1.0, verdict="direction_correct")
        _outcome(session, decision, horizon="long_term", days=30, return_pct=-4.0, verdict="direction_wrong")

        rows, _ = decision_history(session)
        assert rows[0].outcome("short_term", 5).return_pct == pytest.approx(1.0)
        assert rows[0].outcome("long_term", 30).return_pct == pytest.approx(-4.0)

    def test_the_instrument_name_travels_with_the_prediction(self, session):
        from tests.helpers import make_instrument

        session.add(make_instrument("TEST_US_EQ", name="Test Industries"))
        session.flush()
        _decision(session)

        rows, _ = decision_history(session)
        assert rows[0].name == "Test Industries"


class TestTheFilters:
    def test_by_instrument(self, session):
        _decision(session, ticker="A_US_EQ")
        _decision(session, ticker="B_US_EQ")

        rows, total = decision_history(session, ticker="A_US_EQ")
        assert total == 1
        assert rows[0].ticker == "A_US_EQ"

    def test_by_engine(self, session):
        _decision(session, engine="deepseek")
        _decision(session, engine="offline")

        rows, total = decision_history(session, engine="offline")
        assert total == 1
        assert rows[0].decision.engine == "offline"

    def test_actionable_only_excludes_holds(self, session):
        """HOLD asserts no direction, so scoring it either way would credit or blame
        the model for a claim it never made."""
        _decision(session, long_term_action="buy", short_term_action="hold")
        _decision(session, long_term_action="hold", short_term_action="hold")

        rows, total = decision_history(session, only="actionable")
        assert total == 1
        assert rows[0].actionable is True

    def test_holds_only(self, session):
        _decision(session, long_term_action="buy", short_term_action="hold")
        _decision(session, long_term_action="hold", short_term_action="hold")

        rows, _ = decision_history(session, only="hold")
        assert len(rows) == 1
        assert rows[0].actionable is False

    def test_scored_only_drops_the_unelapsed(self, session):
        scored = _decision(session)
        _outcome(session, scored, horizon="short_term", days=5, return_pct=1.0, verdict="direction_correct")
        _decision(session)

        rows, _ = decision_history(session, only="scored")
        assert [row.decision.id for row in rows] == [scored.id]


class TestTheShapes:
    def test_an_empty_database_is_empty_not_broken(self, session):
        rows, total = decision_history(session)
        assert rows == []
        assert total == 0

    def test_paging_does_not_change_the_count(self, session):
        for index in range(6):
            _decision(
                session,
                created_at=dt.datetime(2026, 1, 1 + index, tzinfo=dt.UTC),
            )

        first, total = decision_history(session, limit=4, offset=0)
        second, _ = decision_history(session, limit=4, offset=4)
        assert total == 6
        assert len(first) == 4
        assert len(second) == 2
        assert not {row.decision.id for row in first} & {row.decision.id for row in second}

    def test_the_instrument_name_travels_with_every_prediction(self, session):
        """The name is looked up in a second query and defaulted rather than
        assumed. The foreign key makes a decision with no instrument impossible
        today, so this pins the shape the code relies on."""
        _decision(session, ticker="GONE_US_EQ")

        rows, _ = decision_history(session)
        assert rows[0].name == "GONE_US_EQ Holdings"


class TestThePages:
    def test_the_ledger_page_renders(self, client, universe_instrument, session):
        _decision(session)
        session.commit()

        response = client.get("/decisions")
        assert response.status_code == 200
        assert "TEST_US_EQ" in response.text

    def test_an_unscored_prediction_says_so_rather_than_showing_a_blank(
        self, client, universe_instrument, session
    ):
        _decision(session)
        session.commit()

        body = client.get("/decisions").text
        assert "None of these has a forward return yet" in body
        assert "Not knowable yet" in body

    def test_a_scored_prediction_shows_the_return_and_its_verdict(
        self, client, universe_instrument, session
    ):
        decision = _decision(session)
        _outcome(session, decision, horizon="short_term", days=5, return_pct=4.2, verdict="direction_correct")
        session.commit()

        body = client.get("/decisions").text
        assert "4.2%" in body
        assert "direction correct" in body

    def test_the_ledger_filters_by_instrument(self, client, universe_instrument, session):
        _decision(session, ticker="TEST_US_EQ")
        _decision(session, ticker="OTHER_US_EQ")
        session.commit()

        body = client.get("/decisions?ticker=TEST_US_EQ").text
        assert "1 prediction matched" in body

    def test_the_instrument_page_carries_its_own_history(
        self, client, universe_instrument, session
    ):
        """The page used to show only the latest decision, so "what did it say last
        week, and was it right" had no answer anywhere."""
        _decision(session, created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
        _decision(session, created_at=dt.datetime(2026, 2, 1, tzinfo=dt.UTC))
        session.commit()

        body = client.get("/instrument/TEST_US_EQ").text
        assert "Past predictions" in body
        assert "2 in total" in body

    def test_the_instrument_page_links_into_the_ledger(
        self, client, universe_instrument, session
    ):
        _decision(session)
        session.commit()

        body = client.get("/instrument/TEST_US_EQ").text
        assert "/decisions?ticker=TEST_US_EQ" in body

    def test_the_nav_reaches_the_ledger(self, client, universe_instrument):
        body = client.get("/dashboard").text
        assert 'href="/decisions"' in body
