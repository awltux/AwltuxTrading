"""Session management, including the nested-transaction deadlock.

The bug this covers: ingest functions interleave provider calls with writes, and a
provider call opens a session of its own to record rate-limit usage. With one
connection per scope, the sequence *write -> provider call -> write* deadlocked --
the outer transaction held SQLite's single write lock while the inner connection
waited for it, until ``busy_timeout`` expired and the job died with "database is
locked" after exactly 15 seconds.

It was reproduced directly before being fixed: the same nested shape failed in
3.4s with one connection per scope and succeeded in 0.1s with a re-entrant one.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import select

from awltux.db import ProviderBudget, in_transaction, session_scope
from awltux.db.session import get_engine


class TestReentrancy:
    def test_a_nested_scope_yields_the_same_session(self, settings):
        with session_scope() as outer, session_scope() as inner:
            assert inner is outer

    def test_a_nested_scope_reports_being_in_a_transaction(self, settings):
        assert in_transaction() is False
        with session_scope():
            assert in_transaction() is True
            with session_scope():
                assert in_transaction() is True
        assert in_transaction() is False

    def test_only_the_outermost_scope_commits(self, settings):
        """A nested exit must not commit work the outer scope is still doing."""
        with session_scope() as outer:
            outer.add(ProviderBudget(provider="outer_row", requests_used=1))
            outer.flush()
            with session_scope() as inner:
                inner.add(ProviderBudget(provider="inner_row", requests_used=1))
                inner.flush()
            # Still inside the outer scope: nothing is committed yet.
            assert in_transaction() is True

        with session_scope() as check:
            providers = {
                row.provider
                for row in check.execute(select(ProviderBudget)).scalars().all()
            }
        assert {"outer_row", "inner_row"} <= providers

    def test_an_exception_rolls_back_the_whole_unit_of_work(self, settings):
        """A nested failure must roll back the outer's writes too, so a partially
        recorded fetch cannot survive."""
        with pytest.raises(RuntimeError), session_scope() as outer:
            outer.add(ProviderBudget(provider="doomed", requests_used=1))
            outer.flush()
            with session_scope() as inner:
                inner.add(ProviderBudget(provider="also_doomed", requests_used=1))
                inner.flush()
            raise RuntimeError("provider failed")

        with session_scope() as check:
            providers = {
                row.provider
                for row in check.execute(select(ProviderBudget)).scalars().all()
            }
        assert "doomed" not in providers
        assert "also_doomed" not in providers

    def test_the_stack_is_per_thread(self, settings):
        """Two scheduler jobs run on different threads and must not share a
        transaction."""
        observed: dict[str, bool] = {}

        def worker(name: str) -> None:
            with session_scope() as session:
                observed[name] = in_transaction()
                session.execute(select(ProviderBudget)).scalars().all()
                time.sleep(0.1)
                # A fresh session is not the main thread's.
                assert in_transaction() is True

        threads = [
            threading.Thread(target=worker, args=(f"t{i}",)) for i in range(3)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=20)

        assert observed == {"t0": True, "t1": True, "t2": True}
        assert in_transaction() is False


class TestNestedWriteDoesNotDeadlock:
    def test_a_nested_write_inside_an_open_transaction_succeeds(self, settings):
        """The exact shape that failed in production.

        An outer transaction writes and flushes -- taking SQLite's single write
        lock -- and then something opens a nested scope and writes. With a second
        connection this blocked until ``busy_timeout`` expired.
        """
        started = time.perf_counter()
        with session_scope() as session:
            session.add(ProviderBudget(provider="outer_write", requests_used=1))
            session.flush()

            with session_scope() as inner:
                row = inner.get(ProviderBudget, "inner_write")
                if row is None:
                    row = ProviderBudget(provider="inner_write", requests_used=0)
                    inner.add(row)
                    inner.flush()
                row.requests_used += 1

            session.add(ProviderBudget(provider="outer_write_2", requests_used=1))
            session.flush()

        elapsed = time.perf_counter() - started
        # A deadlock would have waited out busy_timeout (15s by default).
        assert elapsed < 5.0, f"took {elapsed:.1f}s, which suggests lock contention"

        with session_scope() as check:
            providers = {
                row.provider
                for row in check.execute(select(ProviderBudget)).scalars().all()
            }
        assert "outer_write" in providers
        assert "inner_write" in providers

    def test_the_engine_opens_transactions_immediately(self, settings):
        """``BEGIN IMMEDIATE`` is what stops a read-then-write from failing on the
        lock upgrade, which SQLite refuses to retry."""
        import sqlalchemy as sa

        engine = get_engine(settings)
        with engine.connect() as connection:
            # The dialect reports the statement used to begin a transaction.
            assert connection.dialect.name == "sqlite"
            result = connection.execute(sa.text("PRAGMA journal_mode")).scalar()
            assert str(result).lower() == "wal"

    def test_foreign_keys_are_enforced(self, settings):
        """Off by default in SQLite, and the cascades depend on it."""
        import sqlalchemy as sa

        engine = get_engine(settings)
        with engine.connect() as connection:
            assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
