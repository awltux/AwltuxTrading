"""The broker's view of the account: what is held, and when it was traded.

`/equity/positions` has always been read -- it is how `is_held` is decided -- and everything
except the ticker was discarded, including the position's open date. `/equity/history/orders`
was implemented in the provider and had no callers at all. These tests cover the two things
that make the data worth storing: the parse, and the clearing.
"""

from __future__ import annotations

import pytest

from awltux.db import T212Order
from awltux.ingest.jobs import _apply_positions, _parse_position, _store_order
from awltux.web.queries import trade_row
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


BASE_URL = "https://live.trading212.com/api/v0"
ORIGIN = "https://live.trading212.com"
CURSOR_PATH = "/api/v0/equity/history/orders?cursor=1720618206583&limit=50"

PAGE_ONE = {
    "items": [{"order": {"id": 3}}, {"order": {"id": 2}}],
    "nextPagePath": CURSOR_PATH,
}
PAGE_TWO = {"items": [{"order": {"id": 1}}]}


class _RecordingClient:
    """Answers one canned page per call, and remembers what it was asked for."""

    def __init__(self, pages: list[dict]):
        self._pages = list(pages)
        self.asked: list[str] = []

    def get_json(self, url: str, **kwargs) -> dict:
        self.asked.append(url)
        return self._pages.pop(0) if self._pages else {}


def _paging_provider(pages: list[dict]):
    from awltux.providers.t212 import T212Provider

    class _Env:
        t212_base_url = BASE_URL

    class _Settings:
        env = _Env()

    provider = T212Provider.__new__(T212Provider)
    provider.settings = _Settings()
    client = _RecordingClient(pages)
    provider.client = lambda scope: client  # type: ignore[method-assign]
    return provider, client


def _fetched(url: str) -> str:
    """The address `HttpClient` would actually send.

    It concatenates rather than resolving (``providers/http.py``: *url if url.startswith
    ("http") else f"{self.base_url}{url}"*), and that is the rule the 404 turned on: a
    cursor path is host-root absolute, so a second ``/api/v0`` is prepended to the one it
    already carries.
    """
    return url if url.startswith("http") else f"{BASE_URL}{url}"


class TestPagingPastTheFirstPage:
    """A cursor path is absolute from the host root; the first page is not.

    `nextPagePath` comes back as `/api/v0/equity/history/orders?cursor=…` while the client's
    base URL already ends in `/api/v0`, so asking for it unchanged requests
    `/api/v0/api/v0/equity/...` and the API answers 404. Nothing had ever called a history
    endpoint with a limit past one page, so the bug had never been exercised: measured
    2026-10-08, `limit=5` returned its five items (it stops after page one) while `limit=200`
    404'd on the second.
    """

    def test_the_walk_asks_for_both_pages_at_a_single_api_prefix(self):
        provider, client = _paging_provider([PAGE_ONE, PAGE_TWO])
        id_of = lambda item: (item.get("order") or {}).get("id")  # noqa: E731

        items = provider._paginate("/equity/history/orders", 50, id_of=id_of, stop_at_id=0)

        assert len(items) == 3, "the second page was read, not abandoned after a 404"
        assert client.asked == ["/equity/history/orders", f"{ORIGIN}{CURSOR_PATH}"]
        assert [_fetched(url) for url in client.asked] == [
            f"{BASE_URL}/equity/history/orders",
            f"{BASE_URL}/equity/history/orders?cursor=1720618206583&limit=50",
        ]

    def test_an_overlapping_page_does_not_serve_the_same_order_twice(self):
        """The cursor is a timestamp and several fills share one, so a page repeats a bucket.

        Measured 2026-10-08: `get_order_history(limit=200)` returned 200 items with only
        **148 distinct ids** -- 28 repeated up to six times. Those repeats consumed the
        caller's limit and reached the ingest as duplicates.
        """
        provider, _ = _paging_provider(
            [
                {"items": [{"order": {"id": 3}}, {"order": {"id": 2}}], "nextPagePath": CURSOR_PATH},
                {"items": [{"order": {"id": 2}}, {"order": {"id": 1}}]},
            ]
        )
        id_of = lambda item: (item.get("order") or {}).get("id")  # noqa: E731

        items = provider._paginate("/equity/history/orders", 50, id_of=id_of)

        assert [id_of(item) for item in items] == [3, 2, 1]


class TestTheBuyPointOnTheChart:
    """The chart drew the market and nothing the account did.

    `queries.price_markers` places each execution on a *stored bar*, because the x axis is
    the bar dates and a fill can land on a weekend, and it carries the price actually paid
    rather than that day's close -- the two are different facts and the reader bought at one
    of them.
    """

    HISTORY = [
        {"date": "2026-10-01", "close": 100.0, "volume": 1},
        {"date": "2026-10-02", "close": 101.0, "volume": 1},
        {"date": "2026-10-05", "close": 102.0, "volume": 1},
    ]

    def _trade(self, order_id, day, price, side="BUY"):
        """A page-shaped row, which is what the marker reads.

        `id_of`-style fields are not needed here: a marker needs when it happened, what it
        cost and which way it went, and `trade_row` is where those are assembled.
        """
        import datetime as dt

        from awltux.web.queries import trade_row

        return trade_row(
            T212Order(
                order_id=order_id,
                side=side,
                fill_price=price,
                filled_at=dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC),
            ),
            None,
        )

    def test_a_fill_on_a_saturday_is_placed_on_the_next_bar(self):
        from awltux.web.queries import price_markers

        markers = price_markers(self.HISTORY, [self._trade(1, "2026-10-03", 99.5)], None)

        assert markers == [{"date": "2026-10-05", "price": 99.5, "letter": "B"}]

    def test_a_sell_is_marked_as_one(self):
        from awltux.web.queries import price_markers

        markers = price_markers(
            self.HISTORY, [self._trade(1, "2026-10-02", 110.0, side="SELL")], None
        )

        assert markers[0]["letter"] == "S"

    def test_a_trade_before_the_plotted_window_is_dropped_not_clamped(self):
        """An edge dot would read as a date the trade did not happen on."""
        from awltux.web.queries import price_markers

        markers = price_markers(self.HISTORY, [self._trade(1, "2024-01-02", 5.0)], None)

        assert markers == []

    def test_a_trade_after_the_last_bar_takes_the_last_bar(self):
        """Prices are stored end-of-day, so today's fill has no bar yet.

        Dropping it would hide the most recent execution -- the one the reader just made --
        and the chart cannot put a point past its own last bar.
        """
        from awltux.web.queries import price_markers

        markers = price_markers(self.HISTORY, [self._trade(1, "2026-10-09", 111.0)], None)

        assert markers == [{"date": "2026-10-05", "price": 111.0, "letter": "B"}]

    def test_the_position_is_marked_when_no_individual_trade_is_stored(self):
        """Bought before the order history reaches, or transferred in: still a real cost."""
        import datetime as dt

        from awltux.web.queries import price_markers

        instrument = _HeldPosition(average=95.0, opened=dt.datetime(2026, 10, 2, tzinfo=dt.UTC))

        markers = price_markers(self.HISTORY, [], instrument)

        assert markers == [{"date": "2026-10-02", "price": 95.0, "letter": "A"}]

    def test_stored_trades_win_over_the_positions_average(self):
        import datetime as dt

        from awltux.web.queries import price_markers

        instrument = _HeldPosition(average=95.0, opened=dt.datetime(2026, 10, 2, tzinfo=dt.UTC))

        markers = price_markers(self.HISTORY, [self._trade(1, "2026-10-02", 110.0)], instrument)

        assert [marker["letter"] for marker in markers] == ["B"], "one marker per execution"

    def test_an_instrument_with_no_bars_has_no_markers(self):
        from awltux.web.queries import price_markers

        assert price_markers([], [self._trade(1, "2026-10-02", 110.0)], None) == []


class TestWhatATradeIsWorthNow:
    """The trades table stated what was paid and left "and now?" to the reader.

    `current_value` is the cash the trade moved, scaled by the price change since, so the
    percentage beside it is *exactly* the ratio of the two money columns. Re-pricing the
    shares through an FX rate of our own would put a second number beside the first that does
    not agree with it, and the reader would have no way to tell which is the trade.
    """

    def _order(self, price=100.0, value=1000.0, side="BUY", quantity=10.0, **overrides):
        import datetime as dt

        fields = {
            "order_id": 1,
            "side": side,
            "fill_price": price,
            "net_value": value,
            "filled_quantity": quantity,
            "currency": "GBP",
            "status": "FILLED",
            "fill_type": "TRADE",
            "filled_at": dt.datetime(2026, 7, 1, 16, 0, tzinfo=dt.UTC),
        }
        fields.update(overrides)
        return T212Order(**fields)

    def test_the_paid_figure_moves_with_the_price(self):
        row = trade_row(self._order(price=100.0, value=1000.0), 110.0)

        assert row.current_value == pytest.approx(1100.0)
        assert row.change == pytest.approx(0.1)

    def test_the_percentage_is_the_ratio_of_the_two_money_columns(self):
        """The invariant a reader can check by eye, on a fall as well as a rise."""
        for close in (88.0, 110.0, 100.0):
            row = trade_row(self._order(price=100.0, value=1000.0), close)
            assert row.current_value / row.value - 1 == pytest.approx(row.change)

    def test_a_sale_is_priced_the_same_way(self):
        """The counterfactual is the point: did selling there cost or save money?"""
        row = trade_row(
            self._order(price=100.0, value=500.0, side="SELL", quantity=-5.0), 120.0
        )

        assert row.current_value == pytest.approx(600.0)
        assert row.change == pytest.approx(0.2)

    def test_no_stored_close_leaves_both_columns_empty(self):
        """Empty, not zero and not the paid figure dressed up as today's price."""
        row = trade_row(self._order(), None)

        assert (row.current_value, row.change) == (None, None)

    def test_a_zero_fill_price_does_not_divide_by_zero(self):
        assert trade_row(self._order(price=0.0), 10.0).change is None

    def test_a_missing_paid_figure_still_states_the_price_change(self):
        row = trade_row(self._order(value=None), 110.0)

        assert row.current_value is None
        assert row.change == pytest.approx(0.1)

    def test_the_kind_names_the_brokers_own_words(self):
        """A split arrives in this feed wearing an order's clothes."""
        split = self._order(fill_type="STOCK_SPLIT")
        cancelled = self._order(status="CANCELLED")

        assert trade_row(split, 100.0).kind == "stock split"
        assert trade_row(cancelled, 100.0).kind == "cancelled"
        assert trade_row(self._order(), 100.0).kind == "trade"

    def test_the_execution_date_falls_back_to_when_the_order_was_created(self):
        import datetime as dt

        created = dt.datetime(2026, 7, 1, 15, 0, tzinfo=dt.UTC)
        order = self._order()
        order.filled_at = None
        order.created_at = created

        assert trade_row(order, 100.0).executed_at == created


class _HeldPosition:
    """The three `Instrument` attributes the marker fallback reads."""

    def __init__(self, average, opened):
        self.position_average_price = average
        self.position_opened_at = opened


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

    def test_a_repeat_is_caught_before_the_flush(self, session):
        """The one that cost a whole batch: two repeats inside one transaction.

        Sessions run with `autoflush=False`, so the `SELECT` in `_store_order` cannot see
        the row it added a moment ago. Two pending `INSERT`s of one `order_id` then raise
        `UNIQUE constraint failed`, and because the batch shares a transaction every order
        in the run is discarded -- which is what the first production run of `t212_orders`
        did, reporting `items_written: 0` and storing nothing for 148 distinct orders.
        """
        first = _store_order(session, ORDER)
        second = _store_order(session, ORDER)

        assert (first, second) == (True, False), "the second call is not a new order"
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
