"""A job's progress log: captured, tailed, and kept only for the most recent run.

Written against the two things that make this feature worth having rather than
theatre:

* **Progress must not depend on the log level.** The first version routed ``note``
  through ``logger.info``, so at ``--log-level WARNING`` the panel went blank while
  the job ran perfectly. The test fixture pins ``log_level="WARNING"``, so every
  progress assertion here is made under the level that broke it.
* **Jobs must actually say something.** Measured before this was built: `ingest/
  xbrl.py` logged once per run, at the end, and `ingest/jobs.py` had eight logger
  calls across all its jobs. A captured log with no progress in it would have shown
  a header and a footer forty minutes apart.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading

from awltux.db import ResearchReport, session_scope
from awltux.research import service as research_service
from awltux.scheduler import progress
from awltux.scheduler.jobs import JobSpec, execute_job


def _noop() -> None:
    pass


def _job(job_id: str = "probe", func=_noop, target: str | None = None) -> JobSpec:
    return JobSpec(id=job_id, func=func, interval_seconds=3600, target=target)


def _deep_dive(*, subject_type: str, subject_id: str) -> None:
    """The ``running`` report row a deep-dive writes before its thread starts.

    In its own `session_scope`, which commits on exit: the log page is served on its own
    session in another thread, so an uncommitted row is invisible to it. The ``session``
    fixture is deliberately *not* taken here -- holding it open puts `execute_job`'s own
    writes on the same connection, where the request thread never sees them, and the page
    renders "never run" for a run that is right there.
    """
    with session_scope() as session:
        session.add(
            ResearchReport(
                subject_type=subject_type,
                subject_id=subject_id,
                status="running",
                title=subject_id,
                prompt="research it",
                prompt_sha256="x",
                bytes=0,
            )
        )


class TestCapturing:
    def test_a_run_writes_a_header_and_a_footer(self):
        execute_job(_job())

        text, _, size = progress.read("probe")

        assert size > 0
        assert text.startswith("=== probe run")
        assert "===" in text.splitlines()[-1]
        assert "ok in" in text.splitlines()[-1]

    def test_a_targeted_run_names_its_instrument_in_the_header(self):
        """The header has to carry the target, because the heading does not travel.

        A scoped refresh writes fourteen jobs into one file under one job id
        (`instrument_refresh`), and the reader meets this text after copying it off the
        page -- the `<h1>` that said *for GWW_US_EQ* is left behind. Asked for: "this
        should be indicated at the head of the log if it is [about one instrument]".
        """
        execute_job(_job(func=lambda: progress.note("step 1 of 14: price_eod"), target="GWW_US_EQ"))

        text, _, _ = progress.read("probe")

        assert text.startswith("=== probe run"), text
        assert "for GWW_US_EQ ===" in text.splitlines()[0], text.splitlines()[0]

    def test_an_untargeted_run_says_nothing_about_a_target(self):
        """Absence is the honest form: a sweep is not about an instrument."""
        execute_job(_job())

        text, _, _ = progress.read("probe")

        assert " for " not in text.splitlines()[0], text.splitlines()[0]

    def test_progress_lines_are_recorded(self):
        def work() -> None:
            progress.note("1 of 3")
            progress.note("2 of 3")

        execute_job(_job(func=work))

        text, _, _ = progress.read("probe")

        assert "PROGRESS 1 of 3" in text
        assert "PROGRESS 2 of 3" in text

    def test_progress_survives_a_log_level_that_hides_info(self, settings):
        """The bug the fixture is shaped to catch.

        The test settings pin the log level to WARNING, so an INFO line is dropped by
        the logger before any handler sees it. Progress is written straight to the
        file for exactly this reason, and this asserts it survives.
        """
        assert settings.env.log_level == "WARNING", "the fixture is shaped for this"

        def work() -> None:
            logging.getLogger("awltux.somewhere").info("this INFO line is suppressed")
            progress.note("a line that must survive")

        # The level is set here rather than inherited: another test in the suite
        # configures logging for its own purposes, and a test that depends on the
        # ambient level passes alone and fails in company -- which is how this one
        # was caught, green on its own and red in the full run.
        root = logging.getLogger("awltux")
        previous = root.level
        root.setLevel(logging.WARNING)
        try:
            execute_job(_job(func=work))
        finally:
            root.setLevel(previous)

        text, _, _ = progress.read("probe")

        assert "a line that must survive" in text
        assert "this INFO line is suppressed" not in text, (
            "the captured-log path should follow the level; only progress ignores it"
        )

    def test_a_progress_line_is_not_written_twice(self, settings, monkeypatch):
        """It is written directly *and* emitted, so the capture handler must skip it.

        Without the skip, enabling INFO would put every progress line in the file
        twice -- which reads as a job doing each step twice.
        """
        monkeypatch.setattr(settings.env, "log_level", "INFO", raising=False)

        def work() -> None:
            progress.note("once only")

        root = logging.getLogger("awltux")
        previous = root.level
        root.setLevel(logging.INFO)
        try:
            execute_job(_job(func=work))
        finally:
            root.setLevel(previous)

        text, _, _ = progress.read("probe")
        assert text.count("PROGRESS once only") == 1

    def test_two_runs_at_once_do_not_write_into_each_others_logs(self):
        """Two open runs must not write into each other's logs.

        The scheduler runs one job at a time, but a manual `Run now`
        (`POST /api/jobs/{id}/run` -> `run_now(wait=True)`) executes the job on the
        web request thread and never touches the executor, so it overlaps whatever
        the single worker is doing. The first version of `_CaptureHandler` had every
        handler write to whichever run was active *on the emitting thread*, which is
        all of them -- so each line landed in every open file.

        Measured on the live container, 2026-10-06: run 317 (`shareholder_reports`,
        scheduled) and run 318 (`news_rss`, manual) overlapped between 22:48:31Z and
        22:49:12Z; 34 lines of 317's log were written twice (all logged inside that
        window) and 318's `job news_rss: start` appeared twice. Here the two runs are
        held open together by a barrier, so both handlers are attached before either
        logs -- without the barrier the test could pass by the two never overlapping.
        """
        started = dt.datetime.now(dt.UTC)
        both_open = threading.Barrier(2, timeout=10)

        def run(job_id: str) -> None:
            with progress.capture(job_id, None, started):
                both_open.wait()
                logging.getLogger("awltux.jobs").warning("line from %s", job_id)

        threads = [
            threading.Thread(target=run, args=(job_id,)) for job_id in ("alpha", "beta")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        first, _, _ = progress.read("alpha")
        second, _, _ = progress.read("beta")

        assert first.count("line from alpha") == 1, first
        assert "line from beta" not in first, first
        assert second.count("line from beta") == 1, second
        assert "line from alpha" not in second, second

    def test_the_log_is_replaced_not_appended(self):
        """The requirement: only the most recent run is kept."""
        execute_job(_job(func=lambda: progress.note("from the first run")))
        first, _, _ = progress.read("probe")

        execute_job(_job(func=lambda: progress.note("from the second run")))
        second, _, _ = progress.read("probe")

        assert "from the first run" in first
        assert "from the first run" not in second
        assert "from the second run" in second

    def test_a_skipped_run_says_so_in_its_log(self, monkeypatch):
        """A skip is a real outcome and the log should carry its reason."""
        from awltux.scheduler import jobs as jobs_module

        monkeypatch.setattr(jobs_module, "guard_reason", lambda spec: "waiting for news_rss")

        execute_job(_job())
        text, _, _ = progress.read("probe")

        assert "skipped: waiting for news_rss" in text
        assert "skipped" in text.splitlines()[-1]

    def test_a_failing_job_keeps_its_traceback(self):
        """The log's most valuable case: the run that broke."""
        def work() -> None:
            raise ValueError("provider said no")

        execute_job(_job(func=work))
        text, _, _ = progress.read("probe")

        assert "provider said no" in text
        assert "failed" in text.splitlines()[-1]

    def test_a_job_is_never_failed_by_its_own_log(self, monkeypatch):
        """An unwritable log directory must not take the job down with it."""
        monkeypatch.setattr(
            progress, "log_path", lambda _job_id: __import__("pathlib").Path("/nonexistent/x.log")
        )

        result = execute_job(_job(func=lambda: progress.note("still runs")))

        assert result is not None

    def test_progress_outside_a_run_does_not_raise(self):
        """A job called from a test or the CLI has no run to write to."""
        progress.note("no run active")  # must not raise


class TestTailing:
    def test_reading_from_an_offset_returns_only_what_is_new(self):
        """The property the live panel depends on: it sends what it has, gets back
        the delta, and never re-renders the whole file every second."""
        path = progress.log_path("probe")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("first\n", encoding="utf-8")

        whole, end, _ = progress.read("probe", 0)
        # Compared as content, not exact bytes: `write_text` normalises newlines to
        # the platform's, and this test is about offsets rather than line endings.
        assert whole.strip() == "first"

        with path.open("a", encoding="utf-8") as handle:
            handle.write("second\n")
        delta, new_end, _ = progress.read("probe", end)

        assert delta.strip() == "second"
        assert new_end > end
        assert progress.read("probe", new_end)[0] == ""

    def test_a_shrunk_file_restarts_from_the_beginning(self):
        """Which is what a new run looks like: the file is truncated, so an offset
        from the last run is meaningless and honouring it would return nothing."""
        path = progress.log_path("probe")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x" * 500, encoding="utf-8")
        _, end, _ = progress.read("probe", 0)

        path.write_text("new run\n", encoding="utf-8")
        text, _, _ = progress.read("probe", end)

        assert text.strip() == "new run", "a stale offset must not swallow the new run"

    def test_an_offset_beyond_the_end_restarts_rather_than_failing(self):
        execute_job(_job(func=lambda: progress.note("something")))
        text, offset, _ = progress.read("probe", 10_000)

        assert text
        assert offset > 0

    def test_a_missing_log_reads_as_empty_rather_than_raising(self):
        text, offset, size = progress.read("never_ran")

        assert (text, offset, size) == ("", 0, 0)

    def test_a_job_id_cannot_escape_the_log_directory(self):
        """The same rule as every other path in this codebase."""
        path = progress.log_path("../../etc/passwd")

        assert path.parent == progress.log_dir()
        assert ".." not in path.name

    def test_the_log_lives_under_the_configured_data_directory(self, settings):
        """It went to the developer's own `data/` during tests because a lazy
        `get_settings` import escaped the fixture's patching."""
        assert progress.log_dir().is_relative_to(settings.data_dir)


class TestTheCap:
    def test_a_huge_log_is_capped_and_says_so(self, monkeypatch):
        """Bounded, and honest about being bounded: a truncated log that does not say
        so reads as a complete one."""
        monkeypatch.setattr(progress, "MAX_BYTES", 500)

        def work() -> None:
            for index in range(200):
                progress.note(f"line {index} " + "x" * 40)

        execute_job(_job(func=work))
        text, _, size = progress.read("probe")

        assert size <= 800, "the cap must actually hold"
        assert "log truncated" in text
        assert "still running" in text


class TestTheApi:
    def test_it_returns_the_text_and_an_offset(self, client):
        execute_job(_job("probe", lambda: progress.note("hello from the job")))

        body = client.get("/api/jobs/probe/log").json()

        assert "hello from the job" in body["text"]
        assert body["offset"] > 0
        assert body["exists"] is True

    def test_it_reports_the_run_state(self, client):
        """`running` comes from the run table, not from a flag in this process, so a
        panel opened after a restart still answers correctly."""
        execute_job(_job("probe"))

        body = client.get("/api/jobs/probe/log").json()

        assert body["running"] is False
        assert body["ok"] is True
        assert body["run_id"] is not None

    def test_a_job_that_never_ran_is_not_an_error(self, client):
        body = client.get("/api/jobs/nothing_here/log").json()

        assert body["text"] == ""
        assert body["exists"] is False
        assert "run_id" not in body


class TestThePage:
    def test_the_log_page_renders_the_log(self, client):
        execute_job(_job("probe", lambda: progress.note("visible in the panel")))

        response = client.get("/jobs/probe/log")

        assert response.status_code == 200
        assert "visible in the panel" in response.text
        assert 'data-log-url="/api/jobs/probe/log"' in response.text

    def test_the_log_page_renders_before_a_job_has_ever_run(self, client):
        response = client.get("/jobs/never_ran/log")

        assert response.status_code == 200
        assert "No log yet" in response.text

    def test_the_log_page_opens_for_a_run_that_is_still_going(self, client, session):
        """The live failure, reported from the browser: the panel 500s for exactly the
        job you want to watch.

        `dashboard.py` subtracted `run.started_at`, which SQLite returns naive, from an
        aware `now`, and the global handler turned the page into
        ``{"ok": false, "error": "TypeError"}``. It only fires while a job is running --
        then `finished_at` is None, so the aware half of the `finished or now` branch is
        taken. Every finished-run test passed, which is why this one exists.
        """
        from awltux.db import IngestRun

        session.add(
            IngestRun(
                job="probe",
                started_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=20),
                finished_at=None,
                ok=None,
            )
        )
        session.commit()

        response = client.get("/jobs/probe/log")

        assert response.status_code == 200, response.text[:200]
        assert "running" in response.text
        # The elapsed stat only has a value on this branch, so its presence is the
        # assertion that the subtraction actually ran rather than being skipped.
        assert "stat-value" in response.text

    def test_the_back_link_is_the_instrument_a_refresh_is_working_on(self, client):
        """Every refresh writes to the same log file under the same job id.

        So the page could not tell which company it was showing and sent a reader who had
        pressed "Refresh now" on an instrument back to the Operations list (reported
        2026-10-08). The run row names its target from the moment it starts, which is also
        the moment this page is read.
        """
        execute_job(
            JobSpec(
                id="instrument_refresh",
                func=_noop,
                interval_seconds=3600,
                target="GWW_US_EQ",
            )
        )

        body = client.get("/jobs/instrument_refresh/log").text

        assert 'href="/instrument/GWW_US_EQ"' in body
        # Named in the heading too: a reader arriving from a bookmark has to be able to see
        # which company's refresh this log is.
        assert "for GWW_US_EQ" in body
        # And Operations stays one click away for a reader who came from there.
        assert 'href="/jobs"' in body

    def test_a_run_that_is_about_nothing_still_returns_to_operations(self, client):
        execute_job(_job("probe"))

        body = client.get("/jobs/probe/log").text

        assert 'href="/jobs"' in body
        assert "/instrument/" not in body

    def test_the_back_link_is_the_instrument_a_deep_dive_is_researching(self, client):
        """Asked for: following a deep-dive's live log from an instrument gave no way back.

        One log file serves every subject a deep-dive can be about, so the job id cannot say
        which one is running -- the refresh's problem, one level up. The run records the
        subject's id when it starts and the *kind* comes from the subject's own report row,
        which is there before the run's thread starts.
        """
        _deep_dive(subject_type="instrument", subject_id="GWW_US_EQ")

        execute_job(
            JobSpec(
                id=research_service.RESEARCH_JOB,
                func=_noop,
                interval_seconds=3600,
                target="GWW_US_EQ",
            )
        )

        body = client.get(f"/jobs/{research_service.RESEARCH_JOB}/log").text

        assert 'href="/instrument/GWW_US_EQ"' in body
        assert "for GWW_US_EQ" in body
        # And Operations stays one click away for a reader who came from there.
        assert 'href="/jobs"' in body

    def test_a_deep_dive_of_a_sector_returns_to_the_sector(self, client):
        """The other half of the same job. The two subjects live at different paths, so a
        page that assumed `/instrument/` would put a 404 behind the breadcrumb on every
        sector run -- and a sector deep-dive is the only thing the sector page's live log
        link is ever watching."""
        _deep_dive(subject_type="sector", subject_id="Energy")

        execute_job(
            JobSpec(
                id=research_service.RESEARCH_JOB,
                func=_noop,
                interval_seconds=3600,
                target="Energy",
            )
        )

        body = client.get(f"/jobs/{research_service.RESEARCH_JOB}/log").text

        assert 'href="/sectors/Energy"' in body
        assert 'href="/instrument/Energy"' not in body

class TestWhichInstrumentARunWasAbout:
    """`_target_of`, the rule that decides the way back from a refresh's log.

    Tested directly rather than through the page, because the page reads *the newest*
    `instrument_refresh` run and every lease in the database -- so a test that seeds its own
    run is at the mercy of whatever another test left behind. Measured: the first version of
    these two asserted on the rendered page, passed all afternoon, and then failed once the
    wall clock passed a fixed date it used, because a sibling test's lease now spanned it.
    """

    @staticmethod
    def _run(*, started, finished=None, target=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            detail={"target": target} if target else None,
            started_at=started,
            finished_at=finished,
        )

    def test_a_run_that_says_what_it_is_about_needs_no_lease(self):
        from awltux.web.routes.dashboard import _target_of

        started = dt.datetime(2026, 10, 8, 11, 38, 40, tzinfo=dt.UTC)

        assert _target_of(self._run(started=started, target="GWW_US_EQ"), []) == "GWW_US_EQ"

    def test_a_run_from_before_targets_existed_falls_back_to_the_lease_it_held(self):
        """The live shape, to the millisecond: run 797 started 11:38:40.837739 and its
        lease spans 11:38:40.834055 to 11:40:24.185767.

        The lease *ends before the run closes* -- `release` happens at the end of the work
        and the run row is closed after it -- so the rule asks whether the lease contains the
        run's *start*, not its end.
        """
        from awltux.web.routes.dashboard import _target_of

        started = dt.datetime(2026, 10, 8, 11, 38, 40, 837739, tzinfo=dt.UTC)
        leases = [
            (
                dt.datetime(2026, 10, 8, 11, 38, 40, 834055, tzinfo=dt.UTC),
                dt.datetime(2026, 10, 8, 11, 40, 24, 185767, tzinfo=dt.UTC),
                "GWW_US_EQ",
            )
        ]

        assert _target_of(self._run(started=started), leases) == "GWW_US_EQ"

    def test_a_lease_that_ended_before_the_run_started_is_refused(self):
        """The shape of the interrupted run: its own lease was overwritten by a later
        refresh of the same instrument, so the only lease left ended hours earlier.

        Refused rather than matched by nearness -- a company named wrongly is worse than a
        link to Operations, which is at least true.
        """
        from awltux.web.routes.dashboard import _target_of

        started = dt.datetime(2026, 10, 8, 14, 46, 35, tzinfo=dt.UTC)
        leases = [
            (started - dt.timedelta(hours=3), started - dt.timedelta(hours=2), "GWW_US_EQ")
        ]

        assert _target_of(self._run(started=started), leases) is None

    def test_a_lease_taken_after_the_run_belongs_to_a_later_refresh(self):
        from awltux.web.routes.dashboard import _target_of

        started = dt.datetime(2026, 10, 8, 14, 46, 35, tzinfo=dt.UTC)
        leases = [(started + dt.timedelta(minutes=5), None, "GWW_US_EQ")]

        assert _target_of(self._run(started=started), leases) is None

    def test_the_newest_containing_lease_wins(self):
        """Two leases can span one start when a refresh was taken over after its TTL
        expired; the later one is the attempt whose log is on screen."""
        from awltux.web.routes.dashboard import _target_of

        started = dt.datetime(2026, 10, 8, 14, 46, 35, tzinfo=dt.UTC)
        leases = [
            (started - dt.timedelta(minutes=30), None, "OLD_US_EQ"),
            (started - dt.timedelta(minutes=1), None, "NEW_US_EQ"),
        ]

        assert _target_of(self._run(started=started), leases) == "NEW_US_EQ"

    def test_the_job_name_on_the_operations_page_links_to_its_log(self, client, session):
        """The entry point. A panel nobody can reach is not a feature."""
        from tests.helpers import make_instrument

        session.add(make_instrument("TEST_US_EQ", name="Test", sector="Industrials"))
        session.commit()

        body = client.get("/jobs").text

        assert 'href="/jobs/news_rss/log"' in body
        assert 'href="/jobs/valuation/log"' in body
