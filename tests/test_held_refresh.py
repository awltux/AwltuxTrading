"""The hourly sweep that refreshes what the account holds.

The instrument page's Refresh button refreshes one company when somebody presses it. This is
the scheduled half: the same sequence, run for every holding in turn, so a position's filings,
news, valuation and decision are hours old rather than up to a day.

What these tests protect:

* **Nothing else is touched.** The sweep walks `is_held`, not the universe: refreshing 500
  companies hourly would spend the whole free tier on names the account does not own.
* **One instrument at a time, under that instrument's lease**, and the lease is released even
  when a step fails -- a held lease keeps the company out of every sweep until its TTL expires.
* **A company another refresh is already working on is skipped and named**, not waited for and
  not silently dropped.
* **A holding the pipeline does not analyse is counted, not quietly ignored.**
"""

from __future__ import annotations

import pytest

from awltux.ingest import lease, refresh
from awltux.ingest.jobs import refresh_held
from awltux.scheduler.jobs import JobResult
from tests.helpers import make_instrument


def _seed(session, ticker: str, *, held: bool = False, in_universe: bool = True, **overrides):
    row = make_instrument(ticker, in_universe=in_universe, **overrides)
    row.is_held = held
    session.add(row)
    session.flush()
    return row


def _recording_steps(monkeypatch, calls: list[tuple[str, ...]]):
    """Replace the refresh sequence with one step that records the scope it was given."""

    def step(scope):
        calls.append(tuple(scope))
        return JobResult(note="did it")

    monkeypatch.setattr(
        refresh, "_steps_from_registry", lambda: (refresh.Step("prices", "Prices", step),)
    )


def _failing_sequence(monkeypatch, calls: list[tuple[str, ...]], *, fails_on: str):
    """A refresh that raises out of the *sequence* -- not a step, which `run` contains."""

    def fake_run(session, ticker, *, token, **kwargs):
        calls.append((ticker,))
        if ticker == fails_on:
            raise RuntimeError("the session exploded")
        return {"steps_done": 1, "results": [{"step": "prices", "ok": True, "note": "did it"}]}

    monkeypatch.setattr(refresh, "run", fake_run)


class TestHowItIsScheduled:
    def test_it_is_daily_and_gated_on_the_account_key(self, settings):
        """`is_held` is set by the positions read inside `t212_instruments`.

        Without a key that can read positions nothing is held, so the job would run every day
        and do nothing -- disabled visibly, the way every credential-gated job is.
        """
        from awltux.scheduler.registry import build_job_specs

        spec = {row.id: row for row in build_job_specs(settings)}["held_refresh"]

        assert spec.interval_seconds == 86_400
        assert spec.depends_on == ("t212_instruments",)
        assert spec.enabled is False, "no T212 key is configured in tests"

    def test_a_stop_request_leaves_at_an_instrument_boundary(self, session, monkeypatch):
        """`awltux quiet` must not wait for a whole sweep, and must not leave a
        half-refreshed company behind: the checkpoint is between instruments, where the
        previous one is committed and its lease released.
        """
        from awltux.scheduler import progress

        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "BBB_US_EQ", held=True)
        session.commit()

        progress.request_stop()
        with pytest.raises(progress.Stopped):
            refresh_held()

        assert calls == [], "it leaves before refreshing the first holding"


class TestWhatTheSweepWalks:
    def test_every_held_instrument_is_refreshed_once(self, session, monkeypatch):
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "BBB_US_EQ", held=True)
        _seed(session, "CCC_US_EQ")
        session.commit()

        result = refresh_held()

        assert calls == [("AAA_US_EQ",), ("BBB_US_EQ",)]
        assert result.items_seen == 2
        assert result.items_written == 2
        assert result.detail["refreshed"] == ["AAA_US_EQ", "BBB_US_EQ"]

    def test_an_instrument_that_was_sold_is_not_refreshed(self, session, monkeypatch):
        """`is_held` is cleared by the positions read, so a sale stops the sweep reaching it."""
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "SOLD_US_EQ")
        session.commit()

        refresh_held()

        assert calls == [("AAA_US_EQ",)]

    def test_nothing_held_is_explained_rather_than_reported_as_zero(self, session, monkeypatch):
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ")
        session.commit()

        result = refresh_held()

        assert calls == []
        assert result.items_written == 0
        assert "nothing held" in (result.note or "")

    def test_a_holding_outside_the_universe_is_counted_and_named(self, session, monkeypatch):
        """The pipeline is not analysing something the account owns, and that is worth saying.

        Not refreshed: every scoped step filters on `in_universe`, so there is nothing for it
        to do -- the same rule the Refresh button applies.
        """
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "TINY_US_EQ", held=True, in_universe=False)
        session.commit()

        result = refresh_held()

        assert calls == []
        assert result.detail["outside_universe"] == 1
        assert "outside the analysed universe" in (result.note or "")

    def test_the_scope_narrows_the_walk(self, session, monkeypatch):
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "BBB_US_EQ", held=True)
        session.commit()

        refresh_held(["BBB_US_EQ"])

        assert calls == [("BBB_US_EQ",)]


class TestOneInstrumentAtATime:
    def test_the_lease_is_released_after_each_instrument(self, session, monkeypatch):
        """Held here would keep the company out of every sweep until the TTL expired."""
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        session.commit()

        refresh_held()

        session.expire_all()
        row = lease.current(session, "AAA_US_EQ")
        assert row is not None
        assert row.state == "done"
        assert lease.locked_tickers(session) == set()

    def test_an_exception_out_of_the_sequence_still_releases_the_lease(
        self, session, monkeypatch
    ):
        """The failure the lease cannot recover from on its own.

        A *step* raising is not this: `refresh.run` records it and carries on, so the
        sequence still completes. This is the sequence itself failing.
        """
        calls: list[tuple[str, ...]] = []
        _failing_sequence(monkeypatch, calls, fails_on="AAA_US_EQ")
        _seed(session, "AAA_US_EQ", held=True)
        session.commit()

        result = refresh_held()

        session.expire_all()
        assert lease.current(session, "AAA_US_EQ").state == "failed"
        assert result.detail["failed"], "the run must say which holding failed"
        assert lease.locked_tickers(session) == set()

    def test_the_second_instrument_is_still_refreshed_after_the_first_fails(
        self, session, monkeypatch
    ):
        """One broken company must not cost the sweep the other holdings."""
        calls: list[tuple[str, ...]] = []
        _failing_sequence(monkeypatch, calls, fails_on="AAA_US_EQ")
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "BBB_US_EQ", held=True)
        session.commit()

        result = refresh_held()

        assert calls == [("AAA_US_EQ",), ("BBB_US_EQ",)]
        assert result.detail["failed"] and result.detail["refreshed"] == ["BBB_US_EQ"]

    def test_a_step_that_failed_is_counted_without_failing_the_instrument(
        self, session, monkeypatch
    ):
        """`refresh.run` contains a step failure by design, and the instrument's own page
        shows which step it was. The sweep must not call that instrument unrefreshed -- nor
        report the run as clean."""

        def step(scope):
            return JobResult(items_seen=1, items_written=0)

        def broken(scope):
            raise RuntimeError("provider said no")

        monkeypatch.setattr(
            refresh,
            "_steps_from_registry",
            lambda: (
                refresh.Step("prices", "Prices", step),
                refresh.Step("filings_edgar", "Filings", broken),
            ),
        )
        _seed(session, "AAA_US_EQ", held=True)
        session.commit()

        result = refresh_held()

        assert result.detail["refreshed"] == ["AAA_US_EQ"]
        assert result.detail["failed"] == []
        assert result.detail["failed_steps"] == ["AAA_US_EQ/filings_edgar"]

    def test_an_instrument_another_refresh_holds_is_skipped_and_named(
        self, session, monkeypatch
    ):
        """The button's refresh takes the same lease, and a ten-minute-old run is not a lock
        worth blocking the hourly sweep behind."""
        calls: list[tuple[str, ...]] = []
        _recording_steps(monkeypatch, calls)
        _seed(session, "AAA_US_EQ", held=True)
        _seed(session, "BBB_US_EQ", held=True)
        lease.acquire(session, "AAA_US_EQ", note="refresh requested")
        session.commit()

        result = refresh_held()

        assert calls == [("BBB_US_EQ",)]
        assert result.detail["skipped"] == ["AAA_US_EQ"]
        assert result.items_written == 1
