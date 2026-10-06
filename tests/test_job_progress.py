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

from awltux.scheduler import progress
from awltux.scheduler.jobs import JobSpec, execute_job


def _noop() -> None:
    pass


def _job(job_id: str = "probe", func=_noop) -> JobSpec:
    return JobSpec(id=job_id, func=func, interval_seconds=3600)


class TestCapturing:
    def test_a_run_writes_a_header_and_a_footer(self):
        execute_job(_job())

        text, _, size = progress.read("probe")

        assert size > 0
        assert text.startswith("=== probe run")
        assert "===" in text.splitlines()[-1]
        assert "ok in" in text.splitlines()[-1]

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

    def test_the_job_name_on_the_operations_page_links_to_its_log(self, client, session):
        """The entry point. A panel nobody can reach is not a feature."""
        from tests.helpers import make_instrument

        session.add(make_instrument("TEST_US_EQ", name="Test", sector="Industrials"))
        session.commit()

        body = client.get("/jobs").text

        assert 'href="/jobs/news_rss/log"' in body
        assert 'href="/jobs/valuation/log"' in body
