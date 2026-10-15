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


class TestADailyQuota:
    """A day-anchored window, which is what a provider's own daily quota is.

    Measured 2026-10-07: `provider_budget` held `marketaux used=100`, window started
    17:49 -- the full free allowance, spent by 20:00, against a provider that counts the
    day from midnight. A rolling 24-hour window of exactly the published limit can deliver
    two windows' worth inside one of their days, and the email said the daily request
    limit had been reached.
    """

    def _day_rule(self, requests: int = 3) -> BudgetRule:
        return BudgetRule(requests=requests, window_seconds=86400, reset="utc_day")

    def _spend_yesterday(self, provider: str, requests: int = 2) -> None:
        """Leave a spent window behind, started the previous day."""
        guard = BudgetGuard(provider, self._day_rule())
        for _ in range(requests):
            guard.acquire()
        guard.flush()
        with session_scope() as session_db:
            row = session_db.get(ProviderBudget, provider)
            row.window_started_at = dt.datetime.now(dt.UTC) - dt.timedelta(days=1)

    def test_a_window_from_yesterday_is_a_fresh_day(self, settings):
        """The counter belongs to the calendar day, not to a window that began whenever
        this process first asked."""
        self._spend_yesterday("daily")

        BudgetGuard.reset_cache()
        today = BudgetGuard("daily", self._day_rule())

        assert today.remaining() == 3
        today.acquire()
        assert today._state_locked().requests_used == 1

    def test_a_window_from_today_still_counts(self, settings):
        guard = BudgetGuard("daily_today", self._day_rule())
        guard.acquire()

        assert guard.remaining() == 2

    def test_remaining_is_the_allowance_left_in_the_window(self, settings):
        guard = BudgetGuard("daily_remaining", rule(requests=2, window_seconds=60))
        assert guard.remaining() == 2
        guard.acquire()
        assert guard.remaining() == 1

    def test_an_expired_window_has_the_whole_allowance_again(self, settings):
        guard = BudgetGuard("daily_expired", rule(requests=1, window_seconds=0.01))
        guard.acquire()
        time.sleep(0.05)

        assert guard.remaining() == 1

    def test_a_day_is_divided_across_its_runs(self, settings):
        """100 requests a day and 24 runs is three or four a run, not all of them in the
        first hour and none for the rest of the day."""
        guard = BudgetGuard("daily_paced", self._day_rule(requests=100))

        assert guard.per_run(runs_per_day=24) == 4

    def test_pacing_stops_at_what_is_left(self, settings):
        guard = BudgetGuard("daily_left", self._day_rule(requests=4))
        for _ in range(3):
            guard.acquire()

        assert guard.per_run(runs_per_day=24) == 1

    def test_the_last_request_of_a_spent_day_is_never_planned(self, settings):
        """A run that is allowed one request always sends one, or the backlog it exists
        to drain never drains."""
        guard = BudgetGuard("daily_spent", self._day_rule(requests=1))
        guard.acquire()

        assert guard.per_run(runs_per_day=24) == 0

    def test_a_per_minute_allowance_is_not_divided(self, settings):
        """It refills within the minute, so rationing it across the day would throttle a
        provider that is not scarce."""
        guard = BudgetGuard("minute", rule(requests=60, window_seconds=60))

        assert guard.per_run(runs_per_day=24) == 60

    def test_seconds_until_reset_is_the_end_of_the_provider_day(self, settings):
        moment = dt.datetime(2026, 10, 7, 18, 30, tzinfo=dt.UTC)
        guard = BudgetGuard("daily_reset", self._day_rule())
        guard.acquire()
        with session_scope() as session:
            session.get(ProviderBudget, "daily_reset").window_started_at = moment

        BudgetGuard.reset_cache()
        reloaded = BudgetGuard("daily_reset", self._day_rule())

        # 05:30 to midnight is five and a half hours.
        assert reloaded.seconds_until_reset(now=moment) == pytest.approx(19_800, abs=1)


class TestPacingInsideAWindow:
    def test_a_minimum_interval_spaces_the_calls_out(self, settings):
        """Marketaux keeps a per-60-second limiter whose number is not documented, and
        the only honest way to respect an unnumbered burst limit is to space the calls."""
        guard = BudgetGuard(
            "spaced",
            BudgetRule(requests=10, window_seconds=60, min_interval_seconds=0.2),
        )

        start = time.monotonic()
        guard.acquire()
        guard.acquire()
        guard.acquire()
        elapsed = time.monotonic() - start

        assert elapsed >= 0.4, "three calls at a 0.2s spacing cannot be instantaneous"

    def test_no_spacing_means_no_wait(self, settings):
        guard = BudgetGuard("unspaced", rule(requests=10, window_seconds=60))

        start = time.monotonic()
        for _ in range(5):
            guard.acquire()

        assert time.monotonic() - start < 0.4


class TestTheProvidersOwnWordForASpentQuota:
    """HTTP 402 is what a spent *daily* allowance looks like at Marketaux.

    Its documentation lists `402 usage_limit_reached` for the daily cap and `429
    rate_limit_reached` for the per-minute one, and the difference matters: a 429 is a
    pace and can be retried in seconds, while a 402 does not clear until their day turns
    over. Retrying inside the window is a wasted request -- and the email saying the daily
    limit had been reached is what this whole change answers.
    """

    def _client(self, settings, body: bytes, status: int):
        import httpx

        from awltux.providers.http import HttpClient

        def responder(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, content=body, headers={"content-type": "application/json"})

        return HttpClient(
            "marketaux",
            settings=settings,
            base_url="https://api.marketaux.test/v1",
            client=httpx.Client(transport=httpx.MockTransport(responder)),
        )

    def test_a_spent_quota_stops_the_provider_until_its_day_turns_over(self, settings):
        from awltux.providers.http import BudgetExhausted, ProviderError

        client = self._client(settings, b'{"error":{"code":"usage_limit_reached"}}', 402)

        with pytest.raises(ProviderError) as caught:
            client.request("GET", "/news/all")

        assert caught.value.status == 402
        assert "quota spent" in str(caught.value)
        # And the next call is refused locally rather than sent again.
        with pytest.raises(BudgetExhausted):
            client.request("GET", "/news/all")

    def test_the_block_lasts_until_the_end_of_the_day_not_a_retry_interval(self, settings):
        """Asserted against the day boundary, not against a duration.

        This read `(blocked_until - now) > 3600`, which is a statement about the *clock*:
        it holds from midnight until 23:00 UTC and fails after that. Measured 2026-10-15 at
        23:07 UTC, the full suite failed here with 3,147 seconds remaining -- the block was
        right and the assertion was wrong, and it would have failed every night between
        23:00 and midnight for a reason nobody could see in the code.
        """
        import datetime as dt

        from awltux.providers.http import ProviderError

        client = self._client(settings, b"{}", 402)
        with pytest.raises(ProviderError):
            client.request("GET", "/news/all")

        blocked_until = client.budget._state_locked().blocked_until
        now = dt.datetime.now(dt.UTC)
        assert blocked_until is not None
        # A minute would be a retry interval; this is the rest of the provider's day, so
        # the block lands on the next UTC midnight however much of today is left. Within a
        # second of it: the deadline is built by adding a float number of seconds, which
        # lands 114 microseconds past midnight rather than exactly on it.
        next_midnight = now.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + dt.timedelta(days=1)
        assert abs((blocked_until - next_midnight).total_seconds()) < 1


class TestEveryProviderHasABudget:
    """No host is called without a local ceiling.

    Found the hard way. The keyless news feeds had no `budgets` entry, and `HttpClient`
    read that as "no limit" -- `self.budget = None` -- so Google News and Yahoo's
    per-ticker feed were called roughly a thousand times a sweep with nothing counting
    them. Then Marketaux emailed that its daily request limit had been reached.

    Read out of the tree rather than listed here, so a provider added without a rule fails
    the build instead of failing at the provider.
    """

    def test_every_provider_named_in_the_tree_is_budgeted(self, settings):
        import re
        from pathlib import Path

        repo = Path(__file__).resolve().parent.parent
        named: set[str] = set()
        unresolved: list[tuple[Path, str]] = []
        for path in sorted((repo / "src").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            # Resolved per file, not accumulated across the tree: `SOURCE` names a
            # different provider in every module, and one shared dictionary picked up
            # `xbrl_companyfacts` -- a *period* source in `ingest/xbrl.py` -- and
            # demanded a budget for something that is not a provider at all. Every value
            # a name takes in its own file is required, because `news_rss.py` declares
            # four classes that each call `HttpClient(self.SOURCE, ...)`.
            constants: dict[str, set[str]] = {}
            for name, value in re.findall(
                r'^\s*([A-Z][A-Z0-9_]*)\s*=\s*"([a-z0-9_]+)"', text, re.M
            ):
                constants.setdefault(name, set()).add(value)
            # Trading 212 addresses one budget per endpoint through a `scope` parameter,
            # so its `SCOPE_*` constants are provider names by construction.
            named.update(
                value
                for name, values in constants.items()
                if name.startswith("SCOPE_")
                for value in values
            )
            for token in re.findall(r"HttpClient\(\s*([^,\n)]+)", text):
                token = token.strip()
                if token.startswith('"'):
                    named.add(token.strip("\"'"))
                elif token.split(".")[-1] in constants:
                    named.update(constants[token.split(".")[-1]])
                else:
                    unresolved.append((path, token))

        assert named, "the scan found no HttpClient call at all, so it is not reading"
        missing = sorted(name for name in named if name not in settings.budget)
        assert not missing, (
            "these providers are called without a local rate limit, so their hosts' "
            "limits are ours to guess: " + ", ".join(missing)
        )
        # A name the scan cannot resolve is a name nothing checks. The one that exists is
        # `T212Provider.client(scope)`, whose values are the `SCOPE_*` constants required
        # to be budgeted above -- so an unresolved token is only acceptable in a file
        # that declares them, which is a stated reason rather than an allowlist.
        for path, token in unresolved:
            assert "SCOPE_" in path.read_text(encoding="utf-8"), (
                f"{path.name}: HttpClient({token}) names its provider dynamically, so "
                "nothing checks that it has a budget"
            )
