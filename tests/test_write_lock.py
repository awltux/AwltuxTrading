"""The SQLite write lock must not be held across a network call.

This is the rule in ``db/session.py``'s module docstring, and it has been broken
three times by code that looked correct. The third time was visible in production:
the container's log showed a ``decision`` job dying with ``database is locked``
after the full 15-second ``busy_timeout``, while the ``news_rss`` job held the lock
across one classifier call per headline.

So these tests are about the *property* rather than about the call sites. Two of
them take a real second connection and prove the lock is genuinely held before the
release and genuinely gone after it -- an assertion on ``in_transaction()`` alone
would pass even if the connection still held SQLite's write lock.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import func, select, text

from awltux.analysis import news_analysis
from awltux.db import NewsItem, ProviderBudget, release_before_network, session_scope, utcnow
from awltux.ingest.news import persist_items
from awltux.llm.deepseek import DeepSeekClient, DeepSeekError
from awltux.providers.http import ProviderError
from awltux.providers.news_rss import RawNewsItem


def _insert_via_second_connection(db_path) -> None:
    """Write from outside the ORM, failing fast rather than waiting 15 seconds.

    WAL allows exactly one writer, so this raises ``OperationalError`` while the
    session holds the lock and succeeds once it does not.
    """
    connection = sqlite3.connect(str(db_path), timeout=0.05)
    try:
        connection.execute(
            "INSERT INTO app_setting (key, value, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("probe", "1", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
        )
        connection.commit()
    finally:
        connection.close()


def _row(url_hash: str, title: str = "Acme warns on profit") -> NewsItem:
    return NewsItem(source="test", url="https://example.test/a", url_hash=url_hash, title=title)


def _raw(url: str, title: str = "Acme warns on profit") -> RawNewsItem:
    return RawNewsItem(title=title, url=url, source="test")


class TestTheLockIsReal:
    def test_a_flushed_write_genuinely_blocks_another_writer(self, settings):
        """Guards the guard: if this ever passes trivially, the rest of this file
        is proving nothing."""
        with session_scope() as session:
            session.add(_row("a"))
            session.flush()
            with pytest.raises(sqlite3.OperationalError):
                _insert_via_second_connection(settings.db_path)

    def test_releasing_lets_the_other_writer_through(self, settings):
        with session_scope() as session:
            session.add(_row("b"))
            session.flush()
            release_before_network()
            _insert_via_second_connection(settings.db_path)


class TestReleaseBeforeNetwork:
    def test_it_commits_an_open_transaction(self, settings):
        with session_scope() as session:
            session.add(_row("c"))
            session.flush()
            assert session.in_transaction()
            release_before_network()
            assert not session.in_transaction()

    def test_it_is_a_no_op_with_no_open_scope(self):
        """Ingest helpers are also reached from the web request path, where there
        is no job scope to commit."""
        release_before_network()

    def test_it_is_a_no_op_when_the_scope_has_written_nothing(self, settings):
        with session_scope():
            release_before_network()

    def test_a_committed_row_survives_the_scope_ending(self, settings):
        with session_scope() as session:
            session.add(_row("d"))
            session.flush()
            release_before_network()
        with session_scope() as session:
            count = session.execute(
                select(func.count()).select_from(NewsItem).where(NewsItem.url_hash == "d")
            ).scalar_one()
            assert count == 1


class TestTheModelClientReleasesBeforeItPosts:
    def test_the_release_happens_before_the_request(self, settings, monkeypatch):
        """Order, not just presence: releasing after the request would be useless."""
        from awltux.llm import deepseek as deepseek_module

        order: list[str] = []
        monkeypatch.setattr(
            deepseek_module, "release_before_network", lambda: order.append("release")
        )

        class Stub:
            def post(self, *args, **kwargs):
                order.append("post")
                raise ProviderError("stub refused")

        monkeypatch.setattr(DeepSeekClient, "client", lambda self: Stub())
        client = DeepSeekClient(settings)
        with pytest.raises(DeepSeekError):
            client.complete(
                purpose="news_classification",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert order[:2] == ["release", "post"]


class TestTheIngestLoopReleasesBeforeClassifying:
    def test_the_classifier_runs_with_no_open_transaction(self, settings):
        """The exact production bug. Without the release this is ``[False, True]``:
        the first item is clean, and the second is classified while the first
        item's insert still holds the write lock."""
        with session_scope() as session:
            seen: list[bool] = []

            def classifier(item, instrument):
                seen.append(session.in_transaction())
                return None

            persist_items(
                session,
                [_raw("https://example.test/1", "one"), _raw("https://example.test/2", "two")],
                classifier=classifier,
            )

            assert seen == [False, False]

    def test_a_classifier_failure_still_leaves_the_headline_stored(self, settings):
        """The release must not change the existing failure behaviour."""
        with session_scope() as session:

            def classifier(item, instrument):
                raise RuntimeError("model exploded")

            report = persist_items(
                session, [_raw("https://example.test/3", "three")], classifier=classifier
            )
            assert report.written == 1
            assert report.classified == 0


class TestLongBulkWritesAreBatched:
    def test_the_instrument_sync_does_not_hold_one_transaction_for_the_list(self, settings, monkeypatch):
        """~18,000 instruments in a single flush measured 31 seconds holding the
        write lock -- long enough to fail every concurrent writer."""
        from awltux.ingest import universe as universe_module

        released: list[bool] = []
        monkeypatch.setattr(
            universe_module,
            "release_write_lock",
            lambda session: released.append(session.in_transaction()),
        )

        instruments = [
            {"ticker": f"T{index}_US_EQ", "name": f"Company {index}"} for index in range(1_200)
        ]
        with session_scope() as session:
            universe_module.synchronize_instruments(
                session, settings=settings, exchanges=[], instruments=instruments
            )

        assert len(released) == 2, "1200 instruments at 500 per batch is two releases"
        assert all(released), "a release with nothing pending would not bound anything"


class TestTheBudgetCheckpointCannotFailTheJob:
    def test_a_blocked_checkpoint_leaves_the_caller_usable(self, settings):
        """The failure as reported: the UPDATE to ``provider_budget`` could not get
        the lock, and because the checkpoint joined the caller's transaction the
        error surfaced at the *caller's* commit, outside the guard's ``try``, and
        took the whole job down with a PendingRollbackError.

        A rate-limit counter must not be able to fail the work it is counting.
        """
        import datetime as dt

        from awltux.providers.http import BudgetGuard, _BudgetState

        state = _BudgetState(requests_used=1, window_started_at=dt.datetime.now(dt.UTC))
        state.dirty = True
        state.last_flushed = 0.0
        guard = BudgetGuard("probe", rule=None)  # type: ignore[arg-type]

        holder = sqlite3.connect(str(settings.db_path), timeout=0.05)
        holder.execute("BEGIN IMMEDIATE")
        holder.execute(
            "INSERT INTO app_setting (key, value, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("holder", "1", "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
        )
        try:
            with session_scope() as session:
                # Fail fast instead of waiting out the real 15-second timeout.
                session.execute(text("PRAGMA busy_timeout=200"))
                guard._flush(state, force=True)
                assert state.dirty, "a checkpoint that did not land must stay dirty"
            # Exiting the scope must not raise: that is what killed the job.
        finally:
            holder.rollback()
            holder.close()

        # And the checkpoint is still writable once the lock is free.
        with session_scope() as session:
            guard._flush(state, force=True)
        assert not state.dirty

    def test_a_checkpoint_with_no_contention_still_writes(self, settings):
        import datetime as dt

        from awltux.providers.http import BudgetGuard, _BudgetState

        state = _BudgetState(requests_used=7, window_started_at=dt.datetime.now(dt.UTC))
        state.dirty = True
        state.last_flushed = 0.0
        guard = BudgetGuard("probe", rule=None)  # type: ignore[arg-type]

        with session_scope():
            guard._flush(state, force=True)

        assert not state.dirty
        with session_scope() as session:
            row = session.get(ProviderBudget, "probe")
            assert row is not None and row.requests_used == 7


class TestTheAppraisalLoopReleasesBeforeAppraising:
    def test_the_appraisal_runs_with_no_open_transaction(self, settings, monkeypatch):
        """``appraise_item`` is where the deep model call happens, and the release
        at the end of that loop body comes too late to help: the transaction opened
        by the previous item's flush is still held."""
        with session_scope() as session:
            session.add(
                NewsItem(
                    source="test",
                    url="https://example.test/9",
                    url_hash="z",
                    title="Acme wins a contract",
                    materiality="material",
                    tickers=["ACME_US_EQ"],
                    published_at=utcnow(),
                )
            )
            session.flush()
            assert session.in_transaction(), "the premise of this test is an open write"

            seen: list[bool] = []
            original = news_analysis.appraise_item

            def spy(item, **kwargs):
                seen.append(session.in_transaction())
                return original(item, **kwargs)

            monkeypatch.setattr(news_analysis, "appraise_item", spy)
            news_analysis.analyse_universe(
                session, settings=settings, analyser=None, limit=0
            )

        assert seen == [False], "the appraisal must run outside any transaction"
