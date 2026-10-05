"""Instrument sync: the exchange join and the two distinct id spaces.

The bug these cover: ``instrument.working_schedule_id`` was declared as a foreign
key to ``exchange.id``. Trading 212's ``workingScheduleId`` is **not** an exchange
id -- schedule ids live inside each exchange's ``workingSchedules`` list -- and
because both are small integers the mistake survived review until the sync failed
on 18,483 rows with ``FOREIGN KEY constraint failed``.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from awltux.db import Exchange, Instrument, session_scope
from awltux.ingest.universe import _schedule_to_exchange_map, synchronize_instruments
from tests.helpers import make_instrument


def t212_exchanges() -> list[dict[str, Any]]:
    """Two exchanges whose *schedule* ids deliberately do not match their ids.

    This is the whole point: if the ids coincided, a wrong join would look right.
    """
    return [
        {
            "id": 1,
            "name": "London Stock Exchange",
            "workingSchedules": [{"id": 101, "timeEvents": []}, {"id": 154, "timeEvents": []}],
        },
        {
            "id": 2,
            "name": "NASDAQ",
            "workingSchedules": [{"id": 56, "timeEvents": []}],
        },
    ]


def t212_instruments() -> list[dict[str, Any]]:
    return [
        {
            "ticker": "VODl_EQ",
            "isin": "GB00BH4HKS39",
            "name": "Vodafone",
            "shortName": "VOD",
            "currencyCode": "GBX",
            "type": "STOCK",
            "extendedHours": False,
            "maxOpenQuantity": 1000.0,
            "addedOn": "2020-01-01T00:00:00.000+02:00",
            "workingScheduleId": 101,
        },
        {
            "ticker": "AAPL_US_EQ",
            "isin": "US0378331005",
            "name": "Apple",
            "shortName": "AAPL",
            "currencyCode": "USD",
            "type": "STOCK",
            "extendedHours": True,
            "maxOpenQuantity": 5000.0,
            "addedOn": "2020-01-01T00:00:00.000+02:00",
            "workingScheduleId": 56,
        },
        {
            "ticker": "XNASl_EQ",
            "isin": "IE00BMFKG444",
            "name": "Xtrackers NASDAQ 100",
            "shortName": "XNAS",
            "currencyCode": "USD",
            "type": "ETF",
            "workingScheduleId": 154,
        },
    ]


class FakeT212:
    def __init__(self) -> None:
        self._exchanges = t212_exchanges()
        self._instruments = t212_instruments()

    def get_exchanges(self):
        return self._exchanges

    def get_instruments(self):
        return self._instruments


class TestScheduleMapping:
    def test_schedule_ids_resolve_to_their_owning_exchange(self):
        mapping = _schedule_to_exchange_map(t212_exchanges())
        assert mapping[101]["name"] == "London Stock Exchange"
        assert mapping[154]["name"] == "London Stock Exchange"
        assert mapping[56]["name"] == "NASDAQ"

    def test_schedule_ids_are_not_exchange_ids(self):
        """Guards the assumption the schema got wrong."""
        mapping = _schedule_to_exchange_map(t212_exchanges())
        exchange_ids = {exchange["id"] for exchange in t212_exchanges()}
        assert 101 not in exchange_ids
        assert 56 not in exchange_ids
        assert set(mapping) & exchange_ids == set()


class TestSyncPersistsBothIdentifiers:
    def test_the_sync_does_not_violate_the_foreign_key(self, session):
        """The exact failure: 18,483 rows rejected on a bad exchange reference."""
        report = synchronize_instruments(session, provider=FakeT212())
        assert report.instruments_seen == 3
        assert report.instruments_created == 3

    def test_the_raw_schedule_id_is_kept(self, session):
        synchronize_instruments(session, provider=FakeT212())
        vodafone = session.get(Instrument, "VODl_EQ")
        assert vodafone.working_schedule_id == 101

    def test_the_exchange_reference_points_at_a_real_exchange(self, session):
        synchronize_instruments(session, provider=FakeT212())
        vodafone = session.get(Instrument, "VODl_EQ")
        assert vodafone.exchange_id == 1
        assert session.get(Exchange, vodafone.exchange_id).name == "London Stock Exchange"
        assert vodafone.exchange_name == "LSE"

    def test_the_two_ids_are_stored_separately(self, session):
        """A reader must be able to tell which is which."""
        synchronize_instruments(session, provider=FakeT212())
        apple = session.get(Instrument, "AAPL_US_EQ")
        assert apple.working_schedule_id == 56
        assert apple.exchange_id == 2

    def test_instruments_sharing_a_schedule_share_an_exchange(self, session):
        synchronize_instruments(session, provider=FakeT212())
        vodafone = session.get(Instrument, "VODl_EQ")
        xtrackers = session.get(Instrument, "XNASl_EQ")
        assert vodafone.exchange_id == xtrackers.exchange_id == 1
        assert vodafone.working_schedule_id != xtrackers.working_schedule_id


class TestSchema:
    def test_working_schedule_id_has_no_foreign_key(self, settings):
        """It is informational. Constraining it was the original bug."""
        from awltux.db.session import get_engine

        inspector = sa.inspect(get_engine(settings))
        foreign_keys = inspector.get_foreign_keys("instrument")
        constrained = {
            column
            for fk in foreign_keys
            for column in fk["constrained_columns"]
        }
        assert "working_schedule_id" not in constrained
        assert "exchange_id" in constrained

    def test_a_bad_exchange_reference_is_rejected(self, session):
        """The constraint still protects the column that *is* an exchange id."""
        session.add(make_instrument("BAD_US_EQ", exchange_id=9999))
        with pytest.raises(sa.exc.IntegrityError):
            session.flush()
        session.rollback()

    def test_a_raw_schedule_id_is_accepted_without_a_matching_exchange(self, session):
        """Which is the point: schedule ids are not exchange ids."""
        session.add(
            make_instrument("FREE_US_EQ", working_schedule_id=999_999, exchange_id=None)
        )
        session.flush()
        with session_scope() as check:
            assert check.get(Instrument, "FREE_US_EQ").working_schedule_id == 999_999
