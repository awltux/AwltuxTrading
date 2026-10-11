"""Universe membership: seeding once, adding by hand, and removing for good.

The change under test replaces a screen with a decision. `refresh_universe` used to re-select
the top `universe.size` instruments by market cap on every run and set every other row back out
of the universe, so membership was a *derivation* that a reader could only influence by
pinning; it now seeds once and then adds nothing but positions the account has taken. What
follows from that, and is asserted here:

* **the size is a seed, not a cap** -- a second run changes nothing, a large new arrival is not
  added, and nothing is ever removed by the job;
* **a held position is always a member**, because what the account owns is a fact rather than a
  preference, and the app exists to say something about it;
* **removal deletes what was collected and keeps the listing**, so the search block offers the
  instrument again immediately;
* **the page's count is the delete's count.** The confirmation page and the deletion read one
  list (`ingest.universe._held_about`); two lists would let the page promise something the
  delete does not do, which is invisible in both directions after the fact.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select

from awltux.analysis import levers as lever_map
from awltux.db import (
    DecisionRun,
    Filing,
    FundamentalPeriod,
    Instrument,
    InstrumentBlocker,
    InstrumentLever,
    InstrumentRefresh,
    NewsAnalysis,
    NewsItem,
    PriceBar,
    ResearchReport,
    SentimentSeries,
    ValuationRun,
    utcnow,
)
from awltux.ingest import blockers, lease, universe
from awltux.ingest.documents import document_path, instrument_dir
from awltux.ingest.jobs import empty_universe_note
from awltux.research.report import report_path, subject_dir
from tests.helpers import make_bars, make_instrument, make_period

TICKER = "TEST_US_EQ"
OTHER = "OTHER_US_EQ"


def _with_size(settings, size: int):
    """The test settings with a small seed size.

    `Settings.universe` is a property over `Settings.yaml`, so the value is changed there --
    `model_copy(update={"universe": ...})` sets a key the property shadows and does nothing.
    """
    return settings.model_copy(
        update={
            "yaml": settings.yaml.model_copy(
                update={"universe": settings.universe.model_copy(update={"size": size})}
            )
        }
    )


def _instrument(session, ticker: str = TICKER, **overrides) -> Instrument:
    overrides.setdefault("market_cap", 1_000.0)
    row = make_instrument(ticker, **overrides)
    session.add(row)
    session.flush()
    return row


def _everything(session, settings, ticker: str = TICKER) -> None:
    """One row of every kind the removal is meant to take with it.

    Built through the same writers the application uses where one exists (`lease.acquire`,
    `blockers.record_blocker`, `lever_map.record`, the two path helpers), so the test is
    measuring the real rows rather than a hand-rolled approximation of them.
    """
    _instrument(session, ticker)
    session.add_all(make_bars(ticker, [1.0, 2.0, 3.0]))
    session.add(make_period(ticker, dt.date(2025, 12, 31), {"revenue": 1.0}))
    session.add(
        Filing(
            instrument_t212_ticker=ticker,
            source="edgar",
            filing_type="10-K",
            filed_at=dt.datetime(2025, 3, 1, tzinfo=dt.UTC),
            period_end=dt.date(2024, 12, 31),
            url=f"https://www.sec.gov/Archives/edgar/data/1/000000000125000001/{ticker}.htm",
            raw_path=None,
            status="fetched",
        )
    )
    session.add(DecisionRun(instrument_t212_ticker=ticker, state_sha256="t", engine="offline"))
    session.add(ValuationRun(instrument_t212_ticker=ticker, fair_value_base=10.0))
    session.add(
        SentimentSeries(
            scope_type="instrument",
            scope_id=ticker,
            date=dt.date(2025, 6, 1),
            score=0.1,
        )
    )
    lever_map.record(
        session, ticker, [lever_map.Exposure(lever="inflation", direction="negative")]
    )
    blockers.record_blocker(session, ticker, job="fundamentals", stage="fetch", reason="test")
    token = lease.acquire(session, ticker).token
    lease.release(session, ticker, token=token)

    story = NewsItem(
        source="test",
        url=f"https://x.test/{ticker}",
        url_hash=f"hash-{ticker}",
        title=f"{ticker} reports",
        published_at=utcnow(),
        tickers=[ticker, OTHER],
        sectors=[],
    )
    session.add(story)
    session.flush()
    session.add(
        NewsAnalysis(
            news_item_id=story.id,
            subject_type="instrument",
            subject_id=ticker,
            credibility=0.5,
            evidence_grade="weak",
            flags=[],
            warnings=[],
            caveats=[],
            claims=[],
            omissions=[],
            techniques=[],
            source_biases=[],
            factors={},
            carrier_count=1,
            independent_sources=1,
            analysed_at=utcnow(),
        )
    )
    session.add(
        ResearchReport(
            subject_type="instrument",
            subject_id=ticker,
            status="done",
            title=f"{ticker} deep dive",
            prompt="research it",
            prompt_sha256="x",
            model="test",
            exec_summary="A test company.",
            verdict="watch",
        )
    )
    session.flush()

    for path in (
        document_path(settings, ticker, f"https://www.sec.gov/Archives/edgar/data/1/0001/{ticker}.htm"),
        report_path(settings, subject_type="instrument", subject_id=ticker, report_id=1),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")


def _count(session, model, ticker: str = TICKER) -> int:
    column = getattr(model, "instrument_t212_ticker", None)
    return int(
        session.execute(
            select(func.count()).select_from(model).where(column == ticker)
        ).scalar_one()
    )


class TestSeeding:
    def test_the_first_run_takes_the_configured_size_and_records_that_it_did(
        self, session, settings
    ):
        for index, cap in enumerate((300.0, 200.0, 100.0)):
            _instrument(session, f"T{index}_US_EQ", market_cap=cap, in_universe=False)
        session.commit()

        stats = universe.refresh_universe(session, _with_size(settings, 2))

        members = {
            row.t212_ticker
            for row in session.execute(
                select(Instrument).where(Instrument.in_universe.is_(True))
            ).scalars()
        }
        assert stats["mode"] == "initialised"
        assert stats["selected"] == 2
        assert members == {"T0_US_EQ", "T1_US_EQ"}, "the largest two, by market cap"
        assert universe.initialisation(session) is not None

    def test_the_size_is_a_seed_and_not_a_cap(self, session, settings):
        """The property this stage exists for. A second run must not re-select: a name that
        lost its market cap does not fall out, and a larger arrival does not displace it."""
        for index, cap in enumerate((300.0, 200.0, 100.0)):
            _instrument(session, f"T{index}_US_EQ", market_cap=cap, in_universe=False)
        session.commit()
        tiny = _with_size(settings, 2)
        universe.refresh_universe(session, tiny)

        for row in session.execute(select(Instrument)).scalars():
            row.market_cap = 0.0
        _instrument(session, "HUGE_US_EQ", market_cap=1_000_000.0, in_universe=False)
        session.commit()

        stats = universe.refresh_universe(session, tiny)
        session.expire_all()

        assert stats["mode"] == "manual"
        assert stats["added_held"] == []
        members = {
            row.t212_ticker
            for row in session.execute(
                select(Instrument).where(Instrument.in_universe.is_(True))
            ).scalars()
        }
        assert members == {"T0_US_EQ", "T1_US_EQ"}, "nothing added, nothing removed"

    def test_a_database_populated_before_this_behaviour_is_treated_as_seeded(self, session, settings):
        """The live database has 500 members and no flag. It must not be re-seeded, and it must
        not be emptied either -- the membership that is there is the membership that stays."""
        _instrument(session, TICKER, market_cap=1.0)
        _instrument(session, OTHER, market_cap=1_000_000.0, in_universe=False)
        session.commit()

        stats = universe.refresh_universe(session, _with_size(settings, 500))

        assert stats["mode"] == "manual"
        assert universe.initialisation(session) is not None
        assert session.get(Instrument, TICKER).in_universe is True
        assert session.get(Instrument, OTHER).in_universe is False, "no re-selection"

    def test_a_held_position_is_added_however_the_universe_was_seeded(self, session, settings):
        """What the account owns is a fact, not a preference: the app follows it, and a
        purchase is not something to be re-added by hand."""
        _instrument(session, TICKER)
        universe.refresh_universe(session, _with_size(settings, 500))
        _instrument(session, OTHER, is_held=True, in_universe=False)
        session.commit()

        stats = universe.refresh_universe(session, _with_size(settings, 500))
        session.expire_all()

        assert stats["added_held"] == [OTHER]
        assert session.get(Instrument, OTHER).in_universe is True

    def test_nothing_is_ever_removed_by_the_job(self, session, settings):
        _instrument(session, TICKER)
        universe.refresh_universe(session, _with_size(settings, 500))
        _instrument(session, OTHER, market_cap=0.0, in_universe=False)
        session.commit()

        universe.refresh_universe(session, _with_size(settings, 500))
        session.expire_all()

        assert session.get(Instrument, OTHER).in_universe is False, "never a member"
        assert session.get(Instrument, TICKER).in_universe is True, "and never dropped"
        assert universe.initialisation(session)["selected"] == 1, "the flag is not re-stamped"


class TestWhatRemovalDeletes:
    def test_the_page_count_is_what_the_delete_removes(self, session, settings):
        """One list, two uses. If these could disagree, the confirmation page would be
        describing something other than what is about to happen."""
        _everything(session, settings)
        session.commit()

        counted = universe.footprint(session, TICKER)
        outcome = universe.remove(session, TICKER, settings)

        assert sorted(outcome["removed"]) == sorted(counted), "the same tables, in the same words"
        assert outcome["removed"] == counted

    def test_every_collected_row_goes_and_no_other_instrument_is_touched(self, session, settings):
        _everything(session, settings, TICKER)
        _everything(session, settings, OTHER)
        session.commit()

        universe.remove(session, TICKER, settings)
        session.expire_all()

        for model in (
            PriceBar,
            Filing,
            FundamentalPeriod,
            DecisionRun,
            ValuationRun,
            InstrumentLever,
            InstrumentBlocker,
            InstrumentRefresh,
        ):
            assert _count(session, model, TICKER) == 0, model.__name__
            assert _count(session, model, OTHER) > 0, f"{model.__name__} of another instrument"
        # The polymorphic ones are keyed by subject rather than by a foreign key.
        assert all(
            count == 0 for count in universe.footprint(session, TICKER).values()
        ), "one of the subject-keyed tables was left behind"
        other = universe.footprint(session, OTHER)
        assert other["news appraisals"] == 1
        assert other["sentiment series"] == 1
        assert other["research reports"] == 1

    def test_a_shared_news_story_is_not_deleted(self, session, settings):
        """A story names several instruments and is an observation about the world. Only the
        appraisal, which is per-subject, belongs to this instrument."""
        _everything(session, settings)
        session.commit()

        universe.remove(session, TICKER, settings)
        session.expire_all()

        assert session.execute(select(func.count()).select_from(NewsItem)).scalar_one() == 1
        assert session.execute(select(func.count()).select_from(NewsAnalysis)).scalar_one() == 0

    def test_the_files_go_with_the_rows(self, session, settings):
        _everything(session, settings)
        session.commit()
        assert instrument_dir(settings, TICKER).exists()
        assert subject_dir(settings, "instrument", TICKER).exists()

        outcome = universe.remove(session, TICKER, settings)

        assert outcome["files"] == 2
        assert not instrument_dir(settings, TICKER).exists()
        assert not subject_dir(settings, "instrument", TICKER).exists()

    def test_the_listing_stays_so_it_can_be_added_again(self, session, settings):
        """The row is Trading 212's listing, not our data. Deleting it would put the instrument
        out of reach of the search until the next daily sync recreated it."""
        _instrument(session, TICKER, yahoo_symbol="TEST", sector="Industrials", market_cap=5.0)
        session.add_all(make_bars(TICKER, [1.0, 2.0]))
        session.commit()

        universe.remove(session, TICKER, settings)
        session.expire_all()
        row = session.get(Instrument, TICKER)

        assert row is not None, "the listing is kept"
        assert row.in_universe is False
        assert row.pinned is False
        assert row.excluded is False, "removing is not a blocklist -- the search must offer it"
        assert row.yahoo_symbol == "TEST", "the resolved symbol is a derivation, not history"
        assert row.sector == "Industrials"
        assert row.market_cap is None, "derived from the price series that was deleted"

    def test_it_can_be_added_again_and_reappears_in_the_search(self, session, settings):
        _instrument(session, TICKER, in_universe=True)
        session.commit()
        universe.remove(session, TICKER, settings)
        session.commit()

        from awltux.web import queries

        found = queries.candidates_outside_universe(session, "TEST")
        assert [match["ticker"] for match in found["matches"]] == [TICKER]
        assert universe.include(session, TICKER) is True
        assert session.get(Instrument, TICKER).in_universe is True


class TestRefusals:
    def test_a_held_position_cannot_be_removed(self, session, settings):
        """`refresh_universe` would add it straight back, so allowing this would be a button
        that appears to work and is quietly undone by the next run."""
        _instrument(session, TICKER, is_held=True)
        session.commit()

        assert universe.removable(session, TICKER) == "held"
        assert universe.remove(session, TICKER, settings) == {"refused": "held"}
        assert session.get(Instrument, TICKER).in_universe is True

    def test_an_instrument_outside_the_universe_cannot_be_removed(self, session, settings):
        _instrument(session, TICKER, in_universe=False)
        session.commit()

        assert universe.removable(session, TICKER) == "not-in-universe"
        assert universe.remove(session, TICKER, settings) == {"refused": "not-in-universe"}

    def test_an_unknown_ticker_cannot_be_removed(self, session, settings):
        assert universe.removable(session, "NOPE_US_EQ") == "unknown"
        assert universe.remove(session, "NOPE_US_EQ", settings) == {"refused": "unknown"}

    def test_a_refresh_in_flight_blocks_removal(self, session, settings):
        """The run is mid-write for this instrument: deleting its rows under it would leave
        the run's own accounting gone and the instrument half-populated."""
        _instrument(session, TICKER)
        session.commit()
        lease.acquire(session, TICKER)
        session.commit()

        assert universe.removable(session, TICKER) == "busy"
        assert universe.remove(session, TICKER, settings) == {"refused": "busy"}


class TestTheExplanation:
    def test_an_unseeded_empty_universe_points_at_the_job(self, session):
        _instrument(session, OTHER, in_universe=False)
        session.flush()

        note = empty_universe_note(session)

        assert note is not None and "universe_refresh" in note

    def test_a_seeded_empty_universe_points_at_the_search_instead(self, session, settings):
        """The alternative is a job that does nothing: membership is manual once the universe
        has been populated, so an empty one is a reader who removed everything."""
        _instrument(session, TICKER)
        universe.refresh_universe(session, _with_size(settings, 500))
        session.get(Instrument, TICKER).in_universe = False
        session.flush()

        note = empty_universe_note(session)

        assert note is not None
        assert "universe_refresh" not in note
        assert "search on the Recommendations page" in note

    def test_a_populated_universe_needs_no_explanation(self, session):
        _instrument(session, TICKER)
        session.flush()

        assert empty_universe_note(session) is None
