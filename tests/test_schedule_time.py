"""The daily trigger time: the field, the stored override, and the catch-up it feeds.

Asked for 2026-10-23: *"Add a validated time 24hr input field to the Operations page for the
daily trigger time. Populate with the default trigger time. Set default trigger time as 06:00.
Ensure the trigger is caught up if the app wasnt running at the trigger time and the event wasnt
fired."*

Four properties, and the fourth is the one that matters after a night off:

* the field is a 24-hour time, populated with the value in force (the override, else the file's
  default of 06:00);
* a bad value is refused and changes nothing -- the server validates, not only the browser;
* a saved value is what the scheduler computes its anchors from, without a restart;
* a cycle that was missed while nothing was running is caught up on the next start, which is
  `scheduler/catchup.py`'s existing answer and is asserted here against the new anchor.
"""

from __future__ import annotations

import datetime as dt

import pytest
from bs4 import BeautifulSoup

from awltux import schedule_time
from awltux.scheduler.jobs import JobSpec
from awltux.scheduler.service import SchedulerService


def _noop() -> None:
    pass


class TestTheValueItself:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("06:00", "06:00"),
            ("6:00", "06:00"),
            (" 23:59 ", "23:59"),
            ("00:00", "00:00"),
            ("9:05", "09:05"),
        ],
    )
    def test_a_time_is_normalised_to_24_hour(self, raw, expected):
        """``6:00`` is unambiguous and accepted; the rest of the format is stated once."""
        assert schedule_time.normalise(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["", None, "6", "24:00", "06:60", "06:00:00", "six", "06.00", "-1:00"]
    )
    def test_anything_else_is_refused(self, raw):
        with pytest.raises(ValueError):
            schedule_time.normalise(raw)

    def test_the_default_is_six_in_the_morning(self, settings):
        """Asked for exactly this, and asserted here so a change to it is a decision."""
        assert settings.schedule.daily_at == "06:00"

    def test_the_configured_default_is_validated_when_it_loads(self):
        """A bad value in the file stops the process rather than producing a schedule nobody
        can reason about -- the one failure that is better at startup than at the first run."""
        from awltux.config import ScheduleConfig

        assert ScheduleConfig(daily_at="7:30").daily_at == "07:30"
        with pytest.raises(ValueError):
            ScheduleConfig(daily_at="25:00")

    def test_the_anchor_is_the_next_occurrence_in_the_configured_zone(self):
        """A time of day, not an offset: 06:00 stays 06:00 across a clock change."""
        from zoneinfo import ZoneInfo

        london = ZoneInfo("Europe/London")
        # 2026-10-24 is BST (UTC+1), so 06:00 London is 05:00 UTC.
        now = dt.datetime(2026, 10, 24, 3, 0, tzinfo=london)
        assert schedule_time.next_anchor(now, "06:00", london) == dt.datetime(
            2026, 10, 24, 5, 0, tzinfo=dt.UTC
        )
        # After it has passed, the next one is tomorrow.
        later = dt.datetime(2026, 10, 24, 9, 0, tzinfo=london)
        assert schedule_time.next_anchor(later, "06:00", london) == dt.datetime(
            2026, 10, 25, 6, 0, tzinfo=dt.UTC
        )

    def test_the_anchor_is_a_wall_clock_across_a_dst_boundary(self):
        """The one day a year the gap is 23 hours, and the other when it is 25."""
        from zoneinfo import ZoneInfo

        london = ZoneInfo("Europe/London")
        # Clocks go back on 2026-10-25 at 02:00 BST -> 01:00 GMT: 06:00 that day is 06:00 UTC.
        before = dt.datetime(2026, 10, 24, 12, 0, tzinfo=london)
        assert schedule_time.next_anchor(before, "06:00", london) == dt.datetime(
            2026, 10, 25, 6, 0, tzinfo=dt.UTC
        )


class TestTheOperationsField:
    def test_it_is_populated_with_the_default(self, client):
        """The page shows what the scheduler will do, and before any edit that is the file."""
        soup = BeautifulSoup(client.get("/jobs").text, "lxml")
        field = soup.select_one("input[name='daily_at']")

        assert field is not None
        assert field["type"] == "time", "a 24-hour input, not a free-text box"
        assert field["value"] == "06:00"
        assert field["step"] == "60"
        assert "Next cycle" in soup.get_text(" ")

    def test_a_saved_time_is_shown_back(self, client, settings, session):
        response = client.post(
            "/jobs/daily-at", data={"daily_at": "7:30"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/jobs?schedule=saved"
        assert schedule_time.effective(settings) == "07:30"

        soup = BeautifulSoup(client.get("/jobs?schedule=saved").text, "lxml")
        assert soup.select_one("input[name='daily_at']")["value"] == "07:30"
        assert "Daily trigger time saved" in soup.get_text(" ")
        assert "Overriding the configured 06:00" in " ".join(soup.get_text(" ").split())

    def test_an_unusable_time_changes_nothing_and_says_so(self, client, settings):
        response = client.post(
            "/jobs/daily-at", data={"daily_at": "25:00"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == "/jobs?schedule=bad"
        assert schedule_time.effective(settings) == "06:00", "a bad value was stored"

        soup = BeautifulSoup(client.get("/jobs?schedule=bad").text, "lxml")
        assert "a 24-hour time like 06:00" in soup.get_text(" ")
        assert soup.select_one("input[name='daily_at']")["value"] == "06:00"

    def test_the_default_can_be_restored(self, client, settings, session):
        client.post("/jobs/daily-at", data={"daily_at": "21:45"})

        response = client.post("/jobs/daily-at/reset", follow_redirects=False)

        assert response.status_code == 303
        assert schedule_time.effective(settings) == "06:00"


class TestTheSchedulerUsesIt:
    def test_a_saved_time_moves_the_triggers(self, client, settings, session):
        """The scheduler runs in another process, so the page cannot call into it -- it re-reads.

        What matters is the *effective* value the scheduler reads, which is the one the page
        wrote; `_maybe_reschedule` is what turns that into a rebuilt trigger.
        """
        from awltux import schedule_time as clock

        schedule_time.set_stored(session, "22:15")
        session.commit()

        service = SchedulerService(
            [JobSpec(id="j", func=_noop, interval_seconds=86_400)], settings=settings
        )
        service.start()
        try:
            before = service.status()[0]["next_run"]
            assert service.scheduled_daily_at() == "22:15"

            # A *later* edit, as the page would make it, is picked up on the next re-check.
            schedule_time.set_stored(session, "22:45")
            session.commit()
            service._maybe_reschedule()
            after = service.status()[0]["next_run"]
        finally:
            service.shutdown(wait=False)

        assert before != after, "the trigger did not move with the saved time"
        anchor = clock.next_anchor(
            dt.datetime.now(dt.UTC), "22:45", clock.zone_for(settings)
        )
        assert abs((dt.datetime.fromisoformat(after) - anchor).total_seconds()) <= 1

    def test_a_run_puts_the_job_back_on_the_anchor(self, settings, monkeypatch):
        """A trigger advances from when it last fired, so an off-anchor run drags it away.

        Measured on the deployed build the first time the anchor went in: `news_rss` was caught
        up at 09:59 and `sector_index` started at 11:08, and both were then scheduled a day on
        from *that* instant rather than from 06:00. The trigger is forced off-anchor here for the
        same reason -- `add_job(replace_existing=True)` *preserves* the next run time, so only a
        genuine reschedule puts it back.
        """
        import time

        import awltux.scheduler.service as service_module

        ran: list[str] = []
        monkeypatch.setattr(
            service_module, "execute_job", lambda spec, cause=None: ran.append(spec.id)
        )

        service = SchedulerService(
            [JobSpec(id="j", func=_noop, interval_seconds=86_400)], settings=settings
        )
        service.start()
        try:
            service._armed_at = 0.0
            # A catch-up: due now, whatever the anchor says, as the scheduler makes one.
            service._scheduler.modify_job("j", next_run_time=dt.datetime.now(dt.UTC))
            deadline = time.monotonic() + 5
            while not ran and time.monotonic() < deadline:
                time.sleep(0.02)
            next_run = dt.datetime.fromisoformat(service.status()[0]["next_run"])
        finally:
            service.shutdown(wait=False)

        assert ran == ["j"]
        anchor = schedule_time.next_anchor(
            dt.datetime.now(dt.UTC),
            schedule_time.effective(settings),
            schedule_time.zone_for(settings),
        )
        assert abs((next_run - anchor).total_seconds()) <= 1, (
            f"the run left the job at {next_run}, not at the {anchor} anchor"
        )

    def test_a_missed_cycle_is_caught_up_on_the_next_start(self, session, monkeypatch):
        """The fourth requirement: off at 06:00, back at 09:00, the cycle still runs.

        The trigger time only decides *when* a cycle is due. Whether one was missed is the run
        history's answer -- a job whose last success is more than a day old is due now, whatever
        the anchor says -- and that is what makes an overnight outage cheap.
        """
        import time

        import awltux.scheduler.service as service_module
        from awltux.db import IngestRun

        ran: list[tuple] = []
        monkeypatch.setattr(
            service_module, "execute_job", lambda spec, cause=None: ran.append((spec.id, cause))
        )

        stale = dt.datetime.now(dt.UTC) - dt.timedelta(days=1, hours=3)
        session.add(IngestRun(job="missed", started_at=stale, finished_at=stale, ok=True))
        session.commit()

        spec = JobSpec(id="missed", func=_noop, interval_seconds=86_400)
        service = SchedulerService([spec])
        service.start()
        try:
            deadline = time.monotonic() + 5
            while not ran and time.monotonic() < deadline:
                time.sleep(0.02)
        finally:
            service.shutdown(wait=False)

        assert ran, "a cycle missed while the app was off was not caught up"
        assert "catching up" in ran[0][1]

    def test_a_job_inside_its_day_is_not_caught_up_by_a_restart(self, session, monkeypatch):
        """The other half: restarting an hour after the cycle must not run it again."""
        import time

        import awltux.scheduler.service as service_module
        from awltux.db import IngestRun

        ran: list[str] = []
        monkeypatch.setattr(
            service_module, "execute_job", lambda spec, cause=None: ran.append(spec.id)
        )

        recent = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
        session.add(IngestRun(job="fresh", started_at=recent, finished_at=recent, ok=True))
        session.commit()

        service = SchedulerService(
            [JobSpec(id="fresh", func=_noop, interval_seconds=86_400)]
        )
        service.start()
        try:
            time.sleep(0.5)
        finally:
            service.shutdown(wait=False)

        assert ran == [], f"a job that ran an hour ago was run again on restart: {ran}"
