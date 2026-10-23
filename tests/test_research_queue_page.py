"""The research queue page: what is waiting, in the order it will be served.

Asked for 2026-10-21: *"Add a page listing the queue"*, after the queue itself went in and its
per-subject position was the only place a request was visible. A reader with five names waiting
had no list of them anywhere -- the instrument page showed one, the sector page showed one.

Two properties are worth pinning, and they are the ones a queue page gets wrong:

* **the order shown is the order served.** The first column is enumerated from the queued rows in
  `id` order, which is what the consumer's claim orders by. A page that sorted by anything else
  would tell the reader a request is next when it is not.
* **a waiting request is distinguishable from a running one and from a dead one.** The status of
  every row comes from the same rule the subject pages use, so a `running` row left behind by a
  dead process reads `stale` here too.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse

from bs4 import BeautifulSoup

from awltux.db import ResearchReport, utcnow
from tests.helpers import make_instrument

TICKER = "QUEUE_US_EQ"
OTHER = "OTHER_US_EQ"
SECTOR = "Energy"


def _instrument(session, ticker: str = TICKER) -> None:
    session.add(make_instrument(ticker, name="Queue Co"))
    session.flush()


def _row(
    session,
    *,
    status: str,
    subject_type: str = "instrument",
    subject_id: str = TICKER,
    title: str | None = None,
    created_at: dt.datetime | None = None,
    started_at: dt.datetime | None = None,
    verdict: str | None = None,
    error: str | None = None,
) -> ResearchReport:
    row = ResearchReport(
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        title=title or f"{subject_id} report",
        prompt="Research this",
        prompt_sha256="x",
        verdict=verdict,
        error=error,
        created_at=created_at or utcnow(),
        started_at=started_at,
        finished_at=utcnow() if status in {"done", "failed"} else None,
    )
    session.add(row)
    session.flush()
    return row


def _text(html: str) -> str:
    """The page with its markup removed and its whitespace collapsed.

    Used where the assertion is about a sentence rather than about where a tag sits."""
    return " ".join(BeautifulSoup(html, "lxml").get_text(" ").split())


def _subjects(html: str, heading: str) -> list[str]:
    """The subject links of the table under one `<h2>`, in the order the page prints them.

    Selected by *href* rather than by column position: the three tables put the subject in
    different cells (the waiting list leads with its place in the queue), and a page that also
    links a live log must not have that log mistaken for a subject.
    """
    soup = BeautifulSoup(html, "lxml")
    section = soup.find("h2", string=lambda text: text and text.strip() == heading)
    if section is None:
        return []
    table = section.find_next("table")
    if table is None:
        return []
    return [
        anchor.get_text(strip=True)
        for anchor in table.select(
            "tbody tr td a[href^='/instrument/'], tbody tr td a[href^='/sectors/']"
        )
    ]


class TestTheWaitingList:
    def test_the_order_shown_is_the_order_they_will_be_served(self, client, session):
        """Enumerated by `id`, the key the consumer's claim orders by."""
        for ticker in (TICKER, OTHER):
            _instrument(session, ticker)
        _instrument(session, "THIRD_US_EQ")
        session.commit()
        # Deliberately out of chronological step with the ids: the claim takes the oldest id,
        # so a page that sorted by `created_at` would name the wrong run as next.
        first = _row(session, status="queued", created_at=utcnow() - dt.timedelta(minutes=5))
        second = _row(session, status="queued", subject_id=OTHER, created_at=utcnow())
        third = _row(
            session,
            status="queued",
            subject_id="THIRD_US_EQ",
            created_at=utcnow() - dt.timedelta(minutes=1),
        )
        session.commit()

        html = client.get("/research").text

        assert _subjects(html, "Waiting") == [
            first.title,
            second.title,
            third.title,
        ]
        # And the numbers are 1..N in that same order.
        positions = [
            cell.get_text(strip=True)
            for cell in BeautifulSoup(html, "lxml").select("table tbody tr td.num")
        ]
        assert positions[:3] == ["1", "2", "3"]

    def test_an_instrument_request_links_to_its_research_tab(self, client, session):
        _instrument(session)
        _row(session, status="queued")
        session.commit()

        hrefs = [
            anchor["href"]
            for anchor in BeautifulSoup(client.get("/research").text, "lxml").select(
                "table tbody tr td a"
            )
        ]

        assert f"/instrument/{TICKER}?tab=research" in hrefs

    def test_a_sector_request_links_to_its_page(self, client, session):
        """A sector has no tabs, so its block is addressed by fragment, not by `?tab=`."""
        _row(session, status="queued", subject_type="sector", subject_id=SECTOR)
        session.commit()

        hrefs = [
            anchor["href"]
            for anchor in BeautifulSoup(client.get("/research").text, "lxml").select(
                "table tbody tr td a"
            )
        ]

        assert f"/sectors/{urllib.parse.quote(SECTOR, safe='')}#research" in hrefs

    def test_nothing_waiting_says_so_rather_than_showing_an_empty_table(self, client, session):
        _instrument(session)
        session.commit()

        html = client.get("/research").text

        assert "Nothing is waiting" in _text(html)
        assert "Waiting" in _text(html), "the section is still named, so the page is not blank"


class TestTheRunningRun:
    def test_a_running_deep_dive_is_shown_with_its_log(self, client, session):
        _instrument(session)
        _row(session, status="running", started_at=utcnow())
        session.commit()

        html = client.get("/research").text

        assert _subjects(html, "Running now") == [f"{TICKER} report"]
        assert "/jobs/research_report/log" in html

    def test_a_stranded_run_reads_as_stale_not_as_work_in_progress(self, client, session):
        """The same rule the subject pages apply: a `running` row whose process is gone is not
        a run in progress, and the queue page must not imply that it is."""
        _instrument(session)
        _row(
            session,
            status="running",
            started_at=utcnow() - dt.timedelta(hours=6),
        )
        session.commit()

        text = _text(client.get("/research").text)

        assert "stale" in text
        assert "running" not in text.replace("Running now", ""), (
            "a stranded row must not also be called running"
        )

    def test_nothing_running_leaves_the_section_out(self, client, session):
        """A heading with nothing under it is noise on a page opened to check the queue."""
        _instrument(session)
        _row(session, status="queued")
        session.commit()

        assert "Running now" not in _text(client.get("/research").text)


class TestTheRecentRuns:
    def test_the_last_finished_deep_dives_are_listed_newest_first(self, client, session):
        _instrument(session)
        _instrument(session, OTHER)
        _row(
            session,
            status="done",
            subject_id=OTHER,
            title="older report",
            verdict="watch",
            created_at=utcnow() - dt.timedelta(hours=2),
        )
        _row(
            session,
            status="done",
            title="newer report",
            verdict="attractive",
            created_at=utcnow() - dt.timedelta(minutes=5),
        )
        session.commit()

        assert _subjects(client.get("/research").text, "Recently finished") == [
            "newer report",
            "older report",
        ]

    def test_a_failed_run_is_listed_with_its_reason(self, client, session):
        _instrument(session)
        _row(session, status="failed", error="RuntimeError: provider down")
        session.commit()

        text = _text(client.get("/research").text)

        assert "failed" in text
        assert "RuntimeError: provider down" in text

    def test_a_queued_row_is_not_in_the_recent_list(self, client, session):
        """It has not run: the two lists are the present and the past, and a row in both would
        read as a finished run and a waiting one at the same time."""
        _instrument(session)
        _row(session, status="queued", subject_id=OTHER)
        session.commit()

        assert _subjects(client.get("/research").text, "Recently finished") == []


class TestThePageIsReachable:
    def test_the_navigation_links_to_it(self, client, session):
        """A page nobody can find is the state this replaced."""
        html = client.get("/dashboard").text

        assert 'href="/research"' in html

    def test_the_instrument_page_offers_it_beside_a_queued_request(self, client, session):
        """Where the reader is standing when they wonder where their press went.

        Asserted on the notice's own words rather than on `href="/research"`, which the
        navigation already provides on every page -- the link that matters here is the one in the
        block that just said the request is waiting."""
        _instrument(session)
        _row(session, status="queued")
        session.commit()

        text = _text(client.get(f"/instrument/{TICKER}?tab=research").text)

        assert "See the whole queue" in text

    def test_it_is_not_offered_when_nothing_is_queued(self, client, session):
        _instrument(session)
        session.commit()

        text = _text(client.get(f"/instrument/{TICKER}?tab=research").text)

        assert "See the whole queue" not in text
