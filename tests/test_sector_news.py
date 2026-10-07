"""Capturing news for industry sectors, where the subject is the sector.

Every other news feed this system polls is addressed by *ticker*, which is why the
store held 19,418 stories with no sector against 57 that had one -- measured 2026-10-07.
A sector page with nothing to show is the symptom, and it looks exactly like a sector
nobody writes about, so the capture has to be its own walk with its own coverage probe.

The subtle half is the subject line: a sector story has no ticker, so the per-company
classifier has nothing to answer *about* and would file every story as not about
anything. `classify_for_sector` asks the same questions with the industry as the subject.
"""

from __future__ import annotations

from sqlalchemy import select

from awltux.analysis.news_analysis import Subject, subjects_of
from awltux.analysis.sectors import SECTOR_NAMES, SECTOR_QUERIES, query_for
from awltux.db import NewsItem
from awltux.ingest.news import gather_for_sector, ingest_sector_news
from awltux.providers.news_rss import RawNewsItem


class FakeRss:
    """A feed provider that answers from a dict instead of the network.

    Keyed by *sector*, and matched by looking up that sector's real query in the URL,
    so a test cannot pass by inventing a search string the code would never send. That
    is the failure this would otherwise hide: the queries are what decide whether a
    sector has news at all, and a fake with its own vocabulary tests the fake.
    """

    def __init__(self, bodies: dict[str, list[RawNewsItem]] | None = None) -> None:
        self.bodies = bodies or {}
        self.urls: list[str] = []
        self.closed = False

    def google_news_url(self, query: str, *, region: str = "GB", language: str = "en") -> str:
        return f"https://news.google.test/rss?q={query}&region={region}"

    def fetch_feed(self, url: str, **_kwargs) -> list[RawNewsItem]:
        self.urls.append(url)
        for sector, items in self.bodies.items():
            if query_for(sector) not in url:
                continue
            # Fresh objects each time: `gather_for_sector` mutates what it is given, so
            # handing back the same items twice would make the second sector's
            # assertions read as the first sector's.
            return [
                RawNewsItem(
                    title=item.title,
                    url=item.url,
                    source=item.source,
                    summary=item.summary,
                    published_at=item.published_at,
                )
                for item in items
            ]
        return []

    def close(self) -> None:
        self.closed = True


def _item(title: str, url: str) -> RawNewsItem:
    return RawNewsItem(title=title, url=url, source="google_news", summary="s")


class TestTheQueries:
    def test_every_sector_has_a_query(self):
        """A sector added without one is still polled through the fallback rather than
        silently skipped -- a page with no news and no reason given is the failure this
        whole stage exists to remove."""
        assert set(SECTOR_QUERIES) == set(SECTOR_NAMES)

    def test_an_unknown_sector_still_gets_a_query(self):
        assert query_for("Vibes") == '"Vibes" sector'

    def test_a_sector_name_alone_is_not_the_query(self):
        """The names are ordinary English: a search for "Materials" returns the weather
        and a search for "Utilities" returns the water bill."""
        for name in ("Materials", "Utilities", "Energy"):
            assert query_for(name) != name
            assert name in query_for(name) or "sector" in query_for(name)


class TestGathering:
    def test_items_are_tagged_with_the_sector_and_never_with_a_ticker(self, settings):
        rss = FakeRss({"Health Care": [_item("Acme warns", "https://x.test/a")]})

        items = gather_for_sector("Health Care", settings=settings, rss=rss)

        assert items, "the fake should have matched its query"
        assert all(item.sectors == ["Health Care"] for item in items)
        assert all(item.tickers == [] for item in items)

    def test_both_editions_are_polled(self, settings):
        rss = FakeRss()
        gather_for_sector("Energy", settings=settings, rss=rss)
        assert any("region=GB" in url for url in rss.urls)
        assert any("region=US" in url for url in rss.urls)

    def test_a_sector_with_no_feed_returns_nothing_rather_than_raising(self, settings):
        assert gather_for_sector("Utilities", settings=settings, rss=FakeRss()) == []


class TestTheWalk:
    def test_it_stores_a_story_per_sector_with_the_sector_as_its_subject(self, session, settings):
        rss = FakeRss(
            {
                "Energy": [_item("Oil majors slide", "https://x.test/oil")],
                "Health Care": [_item("Drugmaker wins approval", "https://x.test/drug")],
            }
        )

        report = ingest_sector_news(
            session, settings=settings, sectors=["Energy", "Health Care"], rss=rss
        )

        assert report.written == 2
        assert rss.closed is False, "an injected provider is the caller's to close"
        rows = {
            row.title: row
            for row in session.execute(select(NewsItem)).scalars().all()
        }
        assert rows["Oil majors slide"].sectors == ["Energy"]
        assert rows["Drugmaker wins approval"].sectors == ["Health Care"]
        assert rows["Oil majors slide"].tickers == []

    def test_a_sector_whose_feed_raises_does_not_stop_the_walk(self, session, settings):
        """Eleven feeds, one walk: a dead query must cost one sector, not the run."""

        class Exploding(FakeRss):
            def fetch_feed(self, url, **kwargs):
                if "energy" in url:
                    raise RuntimeError("feed is down")
                return super().fetch_feed(url, **kwargs)

        rss = Exploding({"Health Care": [_item("Drugmaker wins", "https://x.test/drug")]})

        report = ingest_sector_news(
            session, settings=settings, sectors=["Energy", "Health Care"], rss=rss
        )

        assert report.written == 1
        assert len(report.errors) == 1 and "Energy" in report.errors[0]

    def test_the_classifier_is_told_the_sector(self, session, settings):
        """Not the ticker: a sector story has none, and a classifier asked about a
        company it cannot name files everything as not about anything."""
        seen: list[tuple[str, list[str]]] = []

        def classifier(item, _instrument):
            seen.append((item.title, list(item.sectors)))
            return {"materiality": "material", "direction": "negative", "metric": "none"}

        rss = FakeRss({"Energy": [_item("Oil majors slide", "https://x.test/oil")]})

        ingest_sector_news(
            session, settings=settings, sectors=["Energy"], rss=rss, classifier=classifier
        )

        assert seen == [("Oil majors slide", ["Energy"])]

    def test_stored_sector_news_produces_a_sector_subject(self, session, settings):
        """The join to the per-subject analysis: this is what makes a `sector` row
        exist at all, and until it does a sector page has nothing appraised."""
        rss = FakeRss({"Energy": [_item("Oil majors slide", "https://x.test/oil")]})
        ingest_sector_news(session, settings=settings, sectors=["Energy"], rss=rss)

        item = session.execute(
            select(NewsItem).where(NewsItem.title == "Oil majors slide")
        ).scalar_one()
        assert subjects_of(item) == [Subject("sector", "Energy")]

    def test_a_second_run_does_not_store_the_same_story_twice(self, session, settings):
        """The feed is a rolling window, so every run sees the previous run's stories."""
        bodies = {"Energy": [_item("Oil majors slide", "https://x.test/oil")]}

        ingest_sector_news(session, settings=settings, sectors=["Energy"], rss=FakeRss(bodies))
        second = ingest_sector_news(
            session, settings=settings, sectors=["Energy"], rss=FakeRss(bodies)
        )

        assert second.written == 0
        assert second.duplicates == 2, "both editions carry it, and both are recognised"
        assert len(session.execute(select(NewsItem)).scalars().all()) == 1


class TestTheJob:
    def test_the_registered_job_reports_a_note_when_every_feed_is_empty(
        self, monkeypatch, settings
    ):
        """`written=0` and `fetched=0` look identical to a quiet news day, and only one
        of them means the queries are wrong."""
        from awltux.ingest import jobs
        from awltux.ingest.news import NewsIngestReport

        monkeypatch.setattr(
            "awltux.ingest.news.ingest_sector_news",
            lambda *_a, **_k: NewsIngestReport(),
        )
        result = jobs.ingest_sector_news_job()

        assert result.items_seen == 0
        assert result.note is not None and "eleven sectors" in result.note
