"""Rate-limit budget behaviour, including under concurrency.

Three bugs lived here, none visible to a naive single-threaded test:

1. the read-modify-write spanned **two transactions**, so concurrent threads could
   each read ``requests_used = N`` and each write ``N + 1``, losing an increment
   against a provider with a hard quota;
2. a read-then-write could fail outright on SQLite's lock upgrade, which
   ``busy_timeout`` deliberately does not retry;
3. and the counter was stored **per request**, so a provider call wrote to the
   database while the caller already held one open -- which deadlocked against
   the ingest job's ``BEGIN IMMEDIATE`` write lock and killed the job with
   "database is locked" after exactly 15 seconds.

The counter now lives in memory and is checkpointed periodically, so the HTTP path
performs no database work at all. These tests pin down both the accounting and
that property.
"""

from __future__ import annotations

import datetime as dt
import threading
import time

import pytest
from sqlalchemy import select

from awltux.config import BudgetRule
from awltux.db import ProviderBudget, session_scope
from awltux.providers.http import BudgetExhausted, BudgetGuard


@pytest.fixture(autouse=True)
def clean_budget_registry(settings):
    """The registry is process-wide, so tests must not leak budgets into each other."""
    BudgetGuard.reset_cache()
    yield
    BudgetGuard.reset_cache()


def rule(requests: int = 3, window_seconds: float = 60.0) -> BudgetRule:
    return BudgetRule(requests=requests, window_seconds=window_seconds)


def checkpointed(provider: str) -> ProviderBudget | None:
    """Force a checkpoint, then read the persisted row."""
    BudgetGuard.flush_all()
    with session_scope() as session:
        return session.execute(
            select(ProviderBudget).where(ProviderBudget.provider == provider)
        ).scalar_one_or_none()


class TestBasicAccounting:
    def test_the_first_acquire_is_counted(self, settings):
        guard = BudgetGuard("probe", rule())
        guard.acquire()
        assert checkpointed("probe").requests_used == 1

    def test_repeated_acquires_within_a_window_increment(self, settings):
        guard = BudgetGuard("probe2", rule(requests=5))
        for _ in range(5):
            guard.acquire()
        assert checkpointed("probe2").requests_used == 5

    def test_a_second_guard_for_the_same_provider_shares_the_budget(self, settings):
        """Clients are constructed in several places; they must share one budget."""
        first = BudgetGuard("shared", rule(requests=3))
        second = BudgetGuard("shared", rule(requests=3))
        first.acquire()
        second.acquire()
        assert checkpointed("shared").requests_used == 2

    def test_exhausting_the_budget_without_waiting_raises(self, settings):
        guard = BudgetGuard("probe3", rule(requests=1, window_seconds=600))
        guard.acquire()
        with pytest.raises(BudgetExhausted):
            guard.acquire(max_wait=1.0)

    def test_an_expired_window_resets_the_counter(self, settings):
        guard = BudgetGuard("probe4", rule(requests=1, window_seconds=0.01))
        guard.acquire()
        time.sleep(0.05)
        guard.acquire()
        assert checkpointed("probe4").requests_used == 1

    def test_a_failure_records_the_reason_and_backs_off(self, settings):
        guard = BudgetGuard("probe5", rule())
        guard.note_failure("HTTP 500", block_seconds=30)
        row = checkpointed("probe5")
        assert row.consecutive_failures == 1
        assert "HTTP 500" in row.last_error
        assert row.blocked_until is not None

    def test_a_success_clears_the_failure_state(self, settings):
        guard = BudgetGuard("probe6", rule())
        guard.note_failure("boom")
        guard.note_success()
        row = checkpointed("probe6")
        assert row.consecutive_failures == 0
        assert row.last_error is None

    def test_a_blocked_provider_raises_rather_than_waiting_forever(self, settings):
        guard = BudgetGuard("probe7", rule())
        guard.note_failure("rate limited", block_seconds=600)
        with pytest.raises(BudgetExhausted):
            guard.acquire(max_wait=1.0)


class TestNoDatabaseWorkOnTheHotPath:
    """The property that fixes the deadlock: a request touches no database.

    A provider call inside an open transaction is unavoidable in the ingest jobs,
    so the budget must not need the database while it is being used. Checkpointing
    is deferred, not synchronous.
    """

    def test_acquiring_does_not_write_during_the_flush_interval(self, settings):
        guard = BudgetGuard("hotpath", rule(requests=100))
        guard.acquire()

        # Force the initial checkpoint, then note the window.
        guard.flush()
        with session_scope() as session:
            before = session.get(ProviderBudget, "hotpath")
            row_id = before.created_at

        for _ in range(10):
            guard.acquire()

        with session_scope() as session:
            after = session.get(ProviderBudget, "hotpath")
        assert after.requests_used == 1, "the counter should be deferred, not written"
        assert after.created_at == row_id

    def test_the_in_memory_counter_is_still_accurate(self, settings):
        guard = BudgetGuard("hotpath2", rule(requests=100))
        for _ in range(10):
            guard.acquire()
        # Authoritative in memory...
        assert guard._state_locked().requests_used == 10
        # ...and correct once checkpointed.
        assert checkpointed("hotpath2").requests_used == 10

    def test_state_is_loaded_from_the_database_on_first_use(self, settings):
        """A restart must resume the budget, not silently reset it."""
        first = BudgetGuard("persist", rule(requests=10))
        for _ in range(4):
            first.acquire()
        first.flush()

        BudgetGuard.reset_cache()
        second = BudgetGuard("persist", rule(requests=10))
        second.acquire()
        assert checkpointed("persist").requests_used == 5


class TestConcurrency:
    def test_concurrent_acquires_do_not_lose_increments(self, settings):
        """20 threads x 5 reservations must produce exactly 100."""
        guard = BudgetGuard("concurrent", rule(requests=1000, window_seconds=3600))
        threads, per_thread = 20, 5
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(per_thread):
                    guard.acquire()
            except Exception as exc:  # noqa: BLE001 - re-asserted below
                errors.append(exc)

        workers = [threading.Thread(target=worker) for _ in range(threads)]
        for thread in workers:
            thread.start()
        for thread in workers:
            thread.join(timeout=60)

        assert not errors, errors
        assert checkpointed("concurrent").requests_used == threads * per_thread

    def test_concurrent_budget_use_does_not_deadlock_against_a_writer(self, settings):
        """The original failure: budget writes racing an open transaction.

        Now that the hot path performs no database work, a writer holding
        ``BEGIN IMMEDIATE`` cannot block it.
        """
        guard = BudgetGuard("norace", rule(requests=1000, window_seconds=3600))
        errors: list[Exception] = []

        def budget_worker() -> None:
            try:
                for _ in range(50):
                    guard.acquire()
                    # Simulates the interleaving the jobs create: a provider call
                    # (which uses the budget) while a transaction stays open.
                    guard.note_success()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        def writer(tag: str) -> None:
            try:
                for index in range(20):
                    with session_scope() as session:
                        # A unique key per insert: two writers racing on the same
                        # primary key would fail on the constraint, not on locking.
                        session.add(
                            ProviderBudget(
                                provider=f"noise-{tag}-{index}", requests_used=1
                            )
                        )
                        session.flush()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=budget_worker) for _ in range(3)]
        threads += [
            threading.Thread(target=writer, args=(f"w{i}",)) for i in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert not errors, [str(error) for error in errors]

    def test_a_naive_utc_timestamp_does_not_break_comparisons(self, settings):
        """SQLite can return naive datetimes for a timezone-aware column, and
        comparing a naive value with an aware one raises TypeError."""
        guard = BudgetGuard("tzcheck", rule(requests=5))
        guard.acquire()
        with session_scope() as session:
            row = session.get(ProviderBudget, "tzcheck")
            row.window_started_at = dt.datetime.now(dt.UTC).replace(tzinfo=None)

        BudgetGuard.reset_cache()
        reloaded = BudgetGuard("tzcheck", rule(requests=5))
        # Would raise TypeError if the naive value were compared directly.
        reloaded.acquire()
        assert reloaded._state_locked().requests_used == 2
