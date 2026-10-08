"""The broker's view of the account: what is held, and when it was traded.

`/equity/positions` has always been read -- it is how `is_held` is decided -- and everything
except the ticker was discarded, including the position's open date. `/equity/history/orders`
was implemented in the provider and had no callers at all. These tests cover the two things
that make the data worth storing: the parse, and the clearing.
"""

from __future__ import annotations

from awltux.db import T212Order
from awltux.ingest.jobs import _apply_positions, _parse_position, _store_order
from tests.helpers import make_instrument

POSITION = {
    "instrument": {"ticker": "GWW_US_EQ", "name": "WW Grainger"},
    "createdAt": "2025-01-31T17:29:15.000+02:00",
    "quantity": 1.1848359,
    "quantityInPies": 0,
    "currentPrice": 1261.38,
    "averagePricePaid": 1097.71319387,
    "walletImpact": {
        "currency": "GBP",
        "totalCost": 977.35,
        "currentValue": 1133.08,
        "unrealizedProfitLoss": 155.73,
        "fxImpact": 8.71,
    },
}

ORDER = {
    "order": {
        "id": 58419120582,
        "strategy": "VALUE",
        "type": "MARKET",
        "ticker": "AIT_US_EQ",
        "status": "FILLED",
        "filledValue": 252.47,
        "currency": "GBP",
        "side": "BUY",
        "createdAt": "2026-10-05T16:00:20.000Z",
        "instrument": {"ticker": "AIT_US_EQ", "name": "Applied Industrial"},
    },
    "fill": {
        "id": 58419120588,
        "quantity": 0.95851493,
        "price": 347.6,
        "type": "TRADE",
        "tradingMethod": "OTC",
        "filledAt": "2026-10-05T16:00:21.000Z",
        "walletImpact": {"currency": "GBP", "netValue": 252.47, "fxRate": 1.32166999},
    },
}


class TestParsingAPosition:
    def test_the_nested_fields_are_flattened(self):
        parsed = _parse_position(POSITION)
        assert parsed is not None
        assert parsed.ticker == "GWW_US_EQ"
        assert parsed.quantity == 1.1848359
        assert parsed.average_price == 1097.71319387
        assert parsed.cost == 977.35
        assert parsed.value == 1133.08
        assert parsed.unrealised == 155.73
        assert parsed.currency == "GBP"
        assert parsed.opened_at is not None and parsed.opened_at.year == 2025

    def test_a_position_with_no_ticker_is_skipped(self):
        """It cannot be mapped to anything, so it is dropped rather than guessed at."""
        assert _parse_position({"quantity": 1.0}) is None

    def test_a_missing_wallet_impact_does_not_lose_the_holding(self):
        """The money is optional; the fact that the account holds it is not."""
        parsed = _parse_position({"instrument": {"ticker": "X_US_EQ"}, "quantity": 3.0})
        assert parsed is not None
        assert parsed.ticker == "X_US_EQ"
        assert parsed.cost is None and parsed.currency is None


class TestApplyingPositions:
    def _held(self, session, ticker="GWW_US_EQ"):
        row = make_instrument(ticker)
        session.add(row)
        session.flush()
        return row

    def test_the_facts_are_written_for_a_held_instrument(self, session):
        row = self._held(session)
        _apply_positions(session, [POSITION])

        assert row.is_held is True
        assert row.position_quantity == 1.1848359
        assert row.position_cost_gbp == 977.35
        assert row.position_unrealised_gbp == 155.73
        assert row.position_currency == "GBP"
        assert row.position_opened_at is not None
        assert row.position_synced_at is not None

    def test_a_position_that_closes_is_cleared(self, session):
        """The failure this exists to prevent, and the whole point of the feature inverted.

        A sold instrument keeping a quantity, a cost basis and an open date for ever would
        read as a holding the account does not have.
        """
        row = self._held(session)
        _apply_positions(session, [POSITION])
        assert row.position_quantity is not None

        # The next read does not mention it.
        _apply_positions(session, [])

        assert row.is_held is False
        assert row.position_quantity is None
        assert row.position_cost_gbp is None
        assert row.position_average_price is None
        assert row.position_opened_at is None
        assert row.position_synced_at is None, "the group moves together"

    def test_an_instrument_never_held_stays_empty(self, session):
        row = self._held(session, "OTHER_US_EQ")
        _apply_positions(session, [POSITION])
        assert row.is_held is False
        assert row.position_synced_at is None

    def test_the_count_is_the_positions_applied(self, session):
        self._held(session)
        assert _apply_positions(session, [POSITION]) == 1


class TestStoringAnOrder:
    def test_a_trade_is_stored_with_its_execution_date(self, session):
        assert _store_order(session, ORDER) is True
        session.flush()

        row = session.query(T212Order).filter_by(order_id=58419120582).one()
        assert row.instrument_t212_ticker == "AIT_US_EQ"
        assert row.side == "BUY"
        assert row.status == "FILLED"
        assert row.strategy == "VALUE"
        assert row.filled_quantity == 0.95851493
        assert row.fill_price == 347.6
        assert row.net_value == 252.47
        assert row.currency == "GBP"
        assert row.filled_at is not None and row.filled_at.year == 2026

    def test_storing_the_same_order_twice_leaves_one_row(self, session):
        """History is re-read from the newest page backwards, so a repeat is normal."""
        assert _store_order(session, ORDER) is True
        session.flush()
        assert _store_order(session, ORDER) is False, "the second write is not new"
        session.flush()

        assert session.query(T212Order).count() == 1

    def test_a_re_read_updates_rather_than_duplicating(self, session):
        _store_order(session, ORDER)
        session.flush()

        amended = {
            "order": {**ORDER["order"], "status": "CANCELLED"},
            "fill": ORDER["fill"],
        }
        assert _store_order(session, amended) is False
        session.flush()

        assert session.query(T212Order).count() == 1
        assert session.query(T212Order).one().status == "CANCELLED"

    def test_an_order_for_an_unknown_instrument_is_kept_unlinked(self, session):
        """The account can hold something outside the stored universe.

        Dropping the row would lose a real trade to a gap in our own metadata.
        """
        unknown = {
            "order": {
                **ORDER["order"],
                "id": 9,
                "ticker": "NOPE_US_EQ",
                # The nested form is the one that counts, so it has to move too.
                "instrument": {"ticker": "NOPE_US_EQ", "name": "Not in the universe"},
            },
            "fill": {},
        }
        assert _store_order(session, unknown) is True
        session.flush()

        row = session.query(T212Order).filter_by(order_id=9).one()
        assert row.instrument_t212_ticker == "NOPE_US_EQ"

    def test_a_fill_with_no_order_id_is_skipped(self, session):
        """`order_id` is the idempotency key; without it there is nothing to upsert on."""
        assert _store_order(session, {"order": {}, "fill": {}}) is False
        assert session.query(T212Order).count() == 0
