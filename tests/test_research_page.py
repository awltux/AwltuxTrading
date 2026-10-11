"""The Research button, its dialog, the report list and the executive summary.

The feature is expensive and irreversible -- a press spends a provider refresh and a deep
model call -- so the properties worth pinning are the ones a reader relies on *before*
pressing it and *after* it has run:

* the latest finished report's executive summary is at the top of a *sector's* page -- an
  instrument's page describes the business from the same report instead, and shows the
  summary only on its Research tab, as the dated list;
* the report list is the dated series, newest first, with each finished one linked to the
  document on disk;
* the dialog carries the prompt the run will actually use, fetched on demand rather than on
  every page render -- building it reads the annual reports, measured at 8.4 seconds;
* a submission starts the run with the *edited* prompt, and a refusal says which refusal it
  was rather than failing silently.
"""

from __future__ import annotations

import datetime as dt
import urllib.parse

import pytest
from bs4 import BeautifulSoup

from awltux.db import NewsItem, ResearchReport, utcnow
from awltux.research.service import Started
from tests.helpers import make_instrument

TICKER = "TEST_US_EQ"
SECTOR = "Energy"


def _instrument(session, ticker: str = TICKER) -> None:
    session.add(make_instrument(ticker, name="Test Co"))
    session.flush()


def _news(session, *, url: str, title: str, sector: str | None = None) -> NewsItem:
    item = NewsItem(
        source="google_news",
        url=url,
        url_hash=f"hash-{url}",
        title=title,
        published_at=utcnow(),
        tickers=[] if sector else [TICKER],
        sectors=[sector] if sector else [],
        materiality="material",
        direction="negative",
        relevant=True,
    )
    session.add(item)
    session.flush()
    return item


def _report(
    session,
    *,
    status: str = "done",
    subject_type: str = "instrument",
    subject_id: str = TICKER,
    summary: str | None = "A test company with thin evidence but a sound balance sheet.",
    verdict: str | None = "watch",
    created_at: dt.datetime | None = None,
    error: str | None = None,
    raw_path: str | None = None,
    result: dict | None = None,
) -> ResearchReport:
    row = ResearchReport(
        subject_type=subject_type,
        subject_id=subject_id,
        status=status,
        title="Test Co (TEST_US_EQ)",
        prompt="Research Test Co",
        prompt_sha256="x",
        model="deepseek-v4-pro",
        exec_summary=summary if status == "done" else None,
        verdict=verdict if status == "done" else None,
        error=error,
        result=result if status == "done" else None,
        # Not written here, and the page does not read it: whether a report can be opened is
        # decided by the file, which a test that wants the link has to put there -- see
        # `test_each_finished_report_links_to_its_document`.
        raw_path=raw_path if status == "done" else None,
        bytes=4096,
        created_at=created_at or utcnow(),
        finished_at=utcnow() if status != "running" else None,
    )
    session.add(row)
    session.flush()
    return row


class _Start:
    """A stand-in for `research.service.start` that records what it was asked to do.

    Stood in for because the real one takes a process-wide permit and starts a thread that
    would read the live database and call a model. What is under test here is the route: what
    it passes on, and where it sends the reader afterwards.
    """

    def __init__(self, ok: bool = True, message: str = "research started") -> None:
        self.ok = ok
        self.message = message
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> Started:
        self.calls.append(kwargs)
        return Started(self.ok, self.message, 1 if self.ok else None)


@pytest.fixture
def started(monkeypatch) -> _Start:
    stub = _Start()
    monkeypatch.setattr("awltux.research.service.start", stub)
    return stub


@pytest.fixture
def refused(monkeypatch) -> _Start:
    stub = _Start(ok=False, message="a deep-dive of this subject is already running")
    monkeypatch.setattr("awltux.research.service.start", stub)
    return stub


class TestTheExecutiveSummary:
    """Where the report's executive summary is shown, and where it deliberately is not.

    It was at the top of *every* instrument tab until 2026-10-10, when the reader removed it:
    `partials/_business.html` now describes the company from the same report, and for a company
    the model can describe the two panels were the same answer twice. A sector keeps it, because
    a sector has no business panel -- there is no business, only a news corpus.
    """

    def test_the_instrument_page_does_not_repeat_it(self, client, session):
        _instrument(session)
        _report(session)
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text

        assert "A test company with thin evidence but a sound balance sheet." not in body
        assert BeautifulSoup(body, "lxml").select_one(".research-summary") is None

    def test_the_report_is_still_one_click_away_from_every_instrument_tab(self, client, session):
        """What the removed panel carried that was *not* a description: the way to the
        document. The business panel holds it now, and this checks it is there on every tab."""
        _instrument(session)
        row = _report(
            session,
            result={"business": {"summary": "It distributes maintenance supplies."}},
        )
        session.commit()

        for tab in ("decision", "valuation", "price", "reports", "accounts", "news", "position"):
            soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab={tab}").text, "lxml")
            anchors = soup.select(".business-profile a[href^='/research/']")
            links = [a["href"] for a in anchors]
            assert f"/research/{row.id}" in links, tab
            # The report is a sandboxed document with no link back to the application, so it
            # opens in its own tab rather than replacing the instrument page -- the rule the
            # filing "read" link already follows.
            assert anchors and anchors[0].get("target") == "_blank", tab

    def test_the_caveat_about_what_a_deep_dive_is_moved_with_the_description(
        self, client, session
    ):
        """The one sentence the removed panel carried that was not a description: a report is
        the model's judgement, not a price target. It belongs beside the sentences it
        qualifies, so it moved into the panel that replaced the summary."""
        _instrument(session)
        _report(session, result={"business": {"summary": "It distributes supplies."}})
        session.commit()

        body = client.get(f"/instrument/{TICKER}").text

        assert "the model's judgement of the whole business, not a price target" in body

    def test_the_verdict_sits_between_the_description_and_its_provenance(
        self, client, session
    ):
        """What the removed panel carried that *was* wanted back, asked for directly: the
        deep-dive's current verdict, beside the description rather than on the Research tab.

        Position is the assertion, not just presence: "after the title and before the 'from
        the deep-dive' line" is the layout, and a receipt head is a flex row of title, badge,
        provenance.
        """
        _instrument(session)
        _report(session, verdict="watch", result={"business": {"summary": "It distributes."}})
        session.commit()

        head = BeautifulSoup(client.get(f"/instrument/{TICKER}").text, "lxml").select_one(
            ".business-profile .receipt-head"
        )

        badge = head.select_one(".badge")
        assert badge is not None and badge.get_text(strip=True) == "watch"
        assert "badge" in badge.get("class", [])
        order = head.get_text(" ", strip=True)
        assert order.index("What the business is") < order.index("watch") < order.index("from")

    def test_a_finished_report_that_reached_no_verdict_says_so(self, client, session):
        """A report that declined to reach a verdict is a different answer from a report that
        has not been run, and the panel shows two different things for them."""
        _instrument(session)
        _report(session, verdict=None, result={"business": {"summary": "It distributes."}})
        session.commit()

        head = BeautifulSoup(client.get(f"/instrument/{TICKER}").text, "lxml").select_one(
            ".business-profile .receipt-head"
        )

        assert head.select_one(".badge").get_text(strip=True) == "no verdict"

    def test_no_report_means_no_verdict_badge(self, client, session):
        _instrument(session)
        session.commit()

        head = BeautifulSoup(client.get(f"/instrument/{TICKER}").text, "lxml").select_one(
            ".business-profile .receipt-head"
        )

        assert head.select_one(".badge") is None

    def test_a_sector_still_carries_it_at_the_top_of_its_page(self, client, session):
        """The half of the feature that stayed: a sector has no other answer to show."""
        _report(session, subject_type="sector", subject_id=SECTOR, summary="Margins compress.")
        session.commit()

        soup = BeautifulSoup(client.get(f"/sectors/{SECTOR}").text, "lxml")

        block = soup.select_one(".research-summary")
        assert block is not None
        assert "Margins compress." in block.get_text(" ")

    def test_a_sector_summary_links_to_the_report_itself(self, client, session):
        row = _report(session, subject_type="sector", subject_id=SECTOR)
        session.commit()

        soup = BeautifulSoup(client.get(f"/sectors/{SECTOR}").text, "lxml")

        block = soup.select_one(".research-summary")
        assert block is not None
        assert block.select_one("a")["href"] == f"/research/{row.id}"
        assert block.select_one("a").get("target") == "_blank"

    def test_a_running_report_is_not_a_summary(self, client, session):
        """The executive summary is the answer of a *finished* run. Showing the previous one
        is right; showing nothing at all next to a run in progress would be wrong, and this
        checks the page distinguishes the two."""
        _report(
            session,
            subject_type="sector",
            subject_id=SECTOR,
            status="done",
            created_at=utcnow() - dt.timedelta(days=2),
            summary="The older answer.",
        )
        _report(
            session,
            subject_type="sector",
            subject_id=SECTOR,
            status="running",
            created_at=utcnow(),
        )
        session.commit()

        body = client.get(f"/sectors/{SECTOR}").text

        assert "The older answer." in body, "the last finished report is still the answer"
        assert "already running" in body

    def test_a_failed_report_shows_its_reason_and_no_link(self, client, session):
        _instrument(session)
        _report(session, status="failed", error="DeepSeekError: the model refused")
        session.commit()

        soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab=research").text, "lxml")

        assert "failed" in soup.select_one("#research").get_text(" ")
        assert "the model refused" in str(soup)
        assert not soup.select("#research a[href^='/research/']")

    def test_no_reports_means_no_summary_block(self, client, session):
        soup = BeautifulSoup(client.get(f"/sectors/{SECTOR}").text, "lxml")

        assert soup.select_one(".research-summary") is None
        assert "No deep-dive has been run about this subject yet." in soup.select_one("#research").get_text(" ")


class TestTheReportList:
    def test_reports_are_listed_newest_first(self, client, session):
        _instrument(session)
        for index, label in enumerate(("oldest", "middle", "newest")):
            _report(
                session,
                summary=f"{label} answer",
                created_at=utcnow() - dt.timedelta(days=10 - index * 5),
            )
        session.commit()

        rows = BeautifulSoup(
            client.get(f"/instrument/{TICKER}?tab=research").text, "lxml"
        ).select("#research table tbody tr")

        assert len(rows) == 3
        dates = [row.select_one("td").get_text(strip=True) for row in rows]
        assert dates == sorted(dates, reverse=True)

    def test_each_finished_report_links_to_its_document(self, client, session, settings):
        """The link is offered because the file is there, not because a column says so.

        Until 2026-10-10 the page read `raw_path`, which the writer filled with a bare file
        name, so this list offered a link to a document the route could not open. The test
        writes the file now, because that is what the answer depends on.
        """
        from awltux.research import report as research_report

        _instrument(session)
        row = _report(session)
        session.commit()
        research_report.write_report(
            research_report.report_path(
                settings,
                subject_type="instrument",
                subject_id=TICKER,
                report_id=row.id,
            ),
            "<html><body>stored</body></html>",
        )

        soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab=research").text, "lxml")

        link = soup.select_one("#research table a[href^='/research/']")
        assert link is not None and link["href"] == f"/research/{row.id}"
        assert link.get("target") == "_blank"

    def test_a_report_with_no_document_on_disk_is_not_offered_as_readable(
        self, client, session
    ):
        """The other half of the same bug: a link that 404s is worse than no link, and the row
        alone cannot tell the two apart -- the volume can be rebuilt without it."""
        _instrument(session)
        _report(session)
        session.commit()

        soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab=research").text, "lxml")

        assert soup.select_one("#research table a[href^='/research/']") is None

    def test_a_stale_running_report_is_shown_as_stale(self, client, session):
        """A run whose process went away leaves `running` behind. The page says stale rather
        than showing work that is not happening."""
        _instrument(session)
        _report(session, status="running", created_at=utcnow() - dt.timedelta(hours=6))
        session.commit()

        soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab=research").text, "lxml")

        assert "stale" in soup.select_one("#research").get_text(" ")


class TestTheDialog:
    def test_the_button_carries_the_prompt_url(self, client, session):
        _instrument(session)
        session.commit()

        soup = BeautifulSoup(client.get(f"/instrument/{TICKER}?tab=research").text, "lxml")
        holder = soup.select_one("#research-prompt-holder")

        assert soup.select_one(".research-open") is not None
        assert holder["data-prompt-url"] == f"/instrument/{TICKER}/research/prompt"

    def test_the_prompt_fragment_is_the_template_plus_the_scope(self, client, session):
        _instrument(session)
        session.commit()

        response = client.get(f"/instrument/{TICKER}/research/prompt")
        soup = BeautifulSoup(response.text, "lxml")
        box = soup.select_one("textarea[name=prompt]")

        assert response.status_code == 200
        assert box is not None
        assert "Research Test Co (TEST_US_EQ)" in box.get_text()
        assert "What this run will read:" in box.get_text()
        assert "How to read the news digest:" in box.get_text()

    def test_the_prompt_fragment_says_what_is_not_available(self, client, session):
        """The reader is approving a spend, and the gaps are the part they cannot see."""
        _instrument(session)
        session.commit()

        text = BeautifulSoup(
            client.get(f"/instrument/{TICKER}/research/prompt").text, "lxml"
        ).get_text(" ")

        assert "Not available, and not asked for" in text
        assert "No stored filing text" in text

    def test_the_suggested_prompt_lists_every_news_url(self, client, session):
        """Asked for directly: *"The suggested research prompt should contain a list of all
        the news article URL's."*

        The reader approving a spend can see exactly which stories the run has, in the box
        they can edit -- so one they judge irrelevant can be struck out, and the model is
        told whose words it is working from.
        """
        _instrument(session)
        _news(session, url="https://x.test/one", title="Costs are rising")
        _news(session, url="https://news.google.test/rss/articles/ABRIDGED", title="Margins compress")
        session.commit()

        text = BeautifulSoup(
            client.get(f"/instrument/{TICKER}/research/prompt").text, "lxml"
        ).select_one("textarea[name=prompt]").get_text()

        assert "News URLs, highest priority first (2):" in text
        assert "https://x.test/one" in text
        assert "https://news.google.test/rss/articles/ABRIDGED" in text
        # Headline beside the address, because a bare list of URLs says nothing about which
        # story is which.
        assert "Costs are rising -- https://x.test/one" in text

    def test_the_prompt_says_nothing_can_open_those_urls(self, client, session):
        """A URL the model cannot fetch is a citation, not a page. Without this the report
        could describe an article's contents as though it had read it."""
        _instrument(session)
        _news(session, url="https://x.test/one", title="Costs are rising")
        session.commit()

        text = BeautifulSoup(
            client.get(f"/instrument/{TICKER}/research/prompt").text, "lxml"
        ).select_one("textarea[name=prompt]").get_text()

        assert "nothing here can open one" in text

    def test_the_sector_prompt_lists_its_own_stories(self, client, session):
        _news(session, url="https://x.test/sector", title="Refining margins", sector=SECTOR)
        session.commit()

        text = BeautifulSoup(
            client.get(f"/sectors/{SECTOR}/research/prompt").text, "lxml"
        ).select_one("textarea[name=prompt]").get_text()

        assert "https://x.test/sector" in text

    def test_an_unknown_subject_is_a_404_not_an_empty_prompt(self, client):
        assert client.get("/instrument/NOPE_US_EQ/research/prompt").status_code == 404
        assert client.get("/sectors/Vibes/research/prompt").status_code == 404


class TestStarting:
    def test_a_submitted_prompt_is_the_one_that_runs(self, client, session, started):
        """The whole point of the dialog: the wording that reaches the run is the wording the
        reader approved, edited or not."""
        _instrument(session)
        session.commit()

        response = client.post(
            f"/instrument/{TICKER}/research",
            data={"prompt": "Judge Management's capital allocation above all."},
            follow_redirects=False,
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/instrument/{TICKER}?tab=research&research=started"
        assert started.calls == [
            {
                "subject_type": "instrument",
                "subject_id": TICKER,
                "prompt": "Judge Management's capital allocation above all.",
            }
        ]

    def test_an_empty_prompt_falls_back_to_the_template(self, client, session, started):
        """Without JavaScript the reader never sees the box, so an empty submission is what
        that path sends -- and it has to start the run rather than fail."""
        _instrument(session)
        session.commit()

        client.post(f"/instrument/{TICKER}/research", data={"prompt": ""}, follow_redirects=False)

        prompt = started.calls[0]["prompt"]
        assert "Research Test Co (TEST_US_EQ)" in prompt
        assert "How to read the news digest:" in prompt

    def test_a_refusal_says_which_refusal_it_was(self, client, session, refused):
        _instrument(session)
        session.commit()

        response = client.post(
            f"/instrument/{TICKER}/research", data={"prompt": "x"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert "research=refused" in response.headers["location"]
        assert "already running" in urllib.parse.unquote(response.headers["location"])

        page = client.get(response.headers["location"]).text
        assert "a deep-dive of this subject is already running" in page

    def test_an_unknown_sector_cannot_start_a_paid_run(self, client, session):
        """The sector name is validated against the same list the sector page uses: a
        hand-typed URL must not start a run about an industry nothing here knows."""
        _instrument(session)
        session.commit()

        response = client.post(
            "/sectors/Vibes/research", data={"prompt": "x"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert "research=refused" in response.headers["location"]
        assert "not in this database" in urllib.parse.unquote(response.headers["location"])

    def test_the_sector_page_has_the_same_block(self, client, session):
        session.add(
            NewsItem(
                source="google_news",
                url="https://x.test/sector",
                url_hash="sector-1",
                title="Refining margins compress",
                published_at=utcnow(),
                tickers=[],
                sectors=[SECTOR],
                materiality="material",
                direction="negative",
                relevant=True,
            )
        )
        _report(session, subject_type="sector", subject_id=SECTOR, summary="Margins are compressing.")
        session.commit()

        body = client.get(f"/sectors/{SECTOR}").text
        soup = BeautifulSoup(body, "lxml")

        assert "Margins are compressing." in body, "the sector's own summary, at the top"
        assert soup.select_one("#research .research-open") is not None
        assert soup.select_one("#research-prompt-holder")["data-prompt-url"] == (
            f"/sectors/{SECTOR}/research/prompt"
        )

    def test_a_sector_submission_returns_to_the_section(self, client, session, started):
        response = client.post(
            f"/sectors/{SECTOR}/research", data={"prompt": "the sector"}, follow_redirects=False
        )

        assert response.status_code == 303
        assert response.headers["location"] == f"/sectors/{SECTOR}?research=started#research"
        assert started.calls[0]["subject_type"] == "sector"

    def test_the_sector_prompt_is_about_the_sector(self, client, session):
        text = BeautifulSoup(
            client.get(f"/sectors/{SECTOR}/research/prompt").text, "lxml"
        ).get_text(" ")

        assert "Energy" in text
        assert "news corpus only" in text
