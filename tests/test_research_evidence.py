"""What a deep-dive is allowed to read, and how the news is ranked.

Two properties are worth more than the rest, and both are about *not* being fooled by the
shape of the data:

* **A story counts only where "What it concerns" names the subject.** `NewsItem.tickers` is
  set by the feed a story was fetched from, and a Google News search for one company returns
  pieces that merely print its name. The stored appraisal is the thing that says a story is
  *about* the subject, and it exists exactly when the concern entry is direct -- so the
  filter and "has an appraisal for this subject" are one predicate.
* **The ranking is shown, not trusted.** `relevance.priority` gives the unassessed default
  weight (0.6) more weight than the ceiling a single-source appraisal lands under (0.25), so
  a story nobody has judged outranks the same story judged single-source. Measured
  2026-10-09: 7,617 of 7,641 appraisals in a 30-day window were single-source. The digest
  keeps that order -- it is a sort order and the prompt is told so -- rather than quietly
  fixing it in one place and leaving the news page disagreeing.
"""

from __future__ import annotations

import datetime as dt

from awltux.db import Filing, FundamentalPeriod, NewsAnalysis, NewsItem, utcnow
from awltux.research import evidence as evidence_of
from tests.helpers import make_instrument

NOW = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.UTC)
TICKER = "TEST_US_EQ"
SECTOR = "Energy"


def _instrument(session, ticker: str = TICKER) -> None:
    session.add(make_instrument(ticker, name="Test Co"))
    session.flush()


def _story(
    session,
    *,
    title: str,
    url: str,
    published_at: dt.datetime | None = None,
    tickers: list[str] | None = None,
    sectors: list[str] | None = None,
    materiality: str | None = None,
    relevant: bool = True,
    title_key: str | None = None,
    relevance_reason: str | None = None,
) -> NewsItem:
    item = NewsItem(
        source="google_news",
        url=url,
        url_hash=f"hash-{url}",
        title=title,
        published_at=published_at or NOW,
        tickers=tickers if tickers is not None else [],
        sectors=sectors if sectors is not None else [],
        materiality=materiality,
        direction="negative",
        relevant=relevant,
        title_key=title_key,
        relevance_reason=relevance_reason,
    )
    session.add(item)
    session.flush()
    return item


def _appraisal(
    session,
    item: NewsItem,
    *,
    subject_type: str = "instrument",
    subject_id: str = TICKER,
    credibility: float | None = 0.4,
    flags: list[str] | None = None,
    carrier_count: int | None = 1,
) -> NewsAnalysis:
    row = NewsAnalysis(
        news_item_id=item.id,
        subject_type=subject_type,
        subject_id=subject_id,
        credibility=credibility,
        evidence_grade="weak",
        flags=flags or [],
        warnings=[],
        caveats=[],
        claims=[],
        omissions=[],
        techniques=[],
        source_biases=[],
        factors={},
        carrier_count=carrier_count,
        independent_sources=1,
        analysed_at=NOW,
    )
    session.add(row)
    session.flush()
    return row


class TestTheJoinKey:
    def test_a_story_that_only_mentions_the_ticker_is_still_evidence(self, session):
        """A direct concern entry is the filter, not the classifier's verdict.

        `relevance.assess` can judge a story "a mention rather than a connection" and the
        prompt tells the model to read that reason -- which is only possible if the story is
        in the digest.
        """
        item = _story(
            session,
            title="Test Co named in passing",
            url="https://x.test/mention",
            tickers=[TICKER],
            relevant=False,
            relevance_reason="fetched by a feed for Test Co but judged not about it",
        )

        digest = evidence_of.news_digest(
            session,
            subject_type="instrument",
            subject_id=TICKER,
            window_days=30,
            limit=12,
            now=NOW,
        )

        assert [entry.headline for entry in digest.entries] == ["Test Co named in passing"]
        assert item.id is not None

    def test_a_story_about_another_instrument_is_not_in_the_digest(self, session):
        _story(session, title="Other Co falls", url="https://x.test/other", tickers=["OTHER_US_EQ"])

        digest = evidence_of.news_digest(
            session,
            subject_type="instrument",
            subject_id=TICKER,
            window_days=30,
            limit=12,
            now=NOW,
        )

        assert digest.entries == []
        assert digest.total == 0

    def test_a_sector_digest_needs_a_direct_sector_entry(self, session):
        """A story about a company in the industry is not a story about the industry.

        The sector's appraisal only exists where the sector is in `sectors`, which
        `ingest.news.gather_for_sector` sets and nothing derives from the tickers.
        """
        _story(session, title="An oil major slides", url="https://x.test/oil", tickers=["X_US_EQ"])
        _story(
            session,
            title="Refining margins compress",
            url="https://x.test/margins",
            sectors=[SECTOR],
        )

        digest = evidence_of.news_digest(
            session,
            subject_type="sector",
            subject_id=SECTOR,
            window_days=30,
            limit=12,
            now=NOW,
        )

        assert [entry.headline for entry in digest.entries] == ["Refining margins compress"]

    def test_the_appraisal_shown_is_the_subjects_own(self, session):
        """A story naming a company and an industry has two appraisals, and they differ.

        The instrument page must read the instrument's, which is the whole reason the
        appraisal is per-subject rather than per-story.
        """
        item = _story(
            session,
            title="Test Co warns on costs",
            url="https://x.test/warns",
            tickers=[TICKER],
            sectors=[SECTOR],
        )
        _appraisal(session, item, subject_type="instrument", subject_id=TICKER, credibility=0.31)
        _appraisal(session, item, subject_type="sector", subject_id=SECTOR, credibility=0.72)

        instrument = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )
        sector = evidence_of.news_digest(
            session, subject_type="sector", subject_id=SECTOR, window_days=30, limit=12, now=NOW
        )

        assert instrument.entries[0].credibility == 0.31
        assert sector.entries[0].credibility == 0.72


class TestTheOrdering:
    def test_a_material_appraised_story_outranks_a_fresh_trivial_one(self, session):
        """Priority is materiality x credibility x recency, and the recency term is a
        three-day half-life -- so a critical story from yesterday beats a `none` from now."""
        _story(
            session,
            title="Trivial and new",
            url="https://x.test/trivial",
            tickers=[TICKER],
            materiality="none",
        )
        material = _story(
            session,
            title="Going concern warning",
            url="https://x.test/going-concern",
            tickers=[TICKER],
            materiality="critical",
            published_at=NOW - dt.timedelta(days=1),
        )
        _appraisal(session, material, credibility=0.9)

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        assert [entry.headline for entry in digest.entries] == [
            "Going concern warning",
            "Trivial and new",
        ]

    def test_an_unappraised_story_outranks_an_appraised_single_source_one(self, session):
        """The documented flaw in the weighting, kept and shown rather than corrected here.

        `UNASSESSED_WEIGHT` is 0.6 and `UNCONFIRMED_CEILING` is 0.25, so "nothing has judged
        this" ranks above "judged and found single-source". The prompt says so in those
        words, because a model handed a ranked list reads the ranking as a verdict on truth.
        If this test starts failing, the ordering changed and the prompt's news rules are
        now wrong.
        """
        appraised = _story(
            session,
            title="Judged and single-sourced",
            url="https://x.test/judged",
            tickers=[TICKER],
            materiality="mild",
        )
        _appraisal(session, appraised, credibility=0.05, flags=["single_source"])
        _story(
            session,
            title="Nobody has looked at this",
            url="https://x.test/unjudged",
            tickers=[TICKER],
            materiality="mild",
        )

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        assert [entry.headline for entry in digest.entries] == [
            "Nobody has looked at this",
            "Judged and single-sourced",
        ]
        assert digest.entries[0].assessed is False
        assert digest.entries[1].assessed is True

    def test_republication_collapses_into_one_entry(self, session):
        """Five rewrites of one wire story are one event, and twelve slots are worth having.

        `NewsItem.title_key` is the headline digest with the publisher suffix dropped, which
        is the part that differs when a story is syndicated.
        """
        for index in range(3):
            _story(
                session,
                title=f"Same wire story #{index}",
                url=f"https://x.test/wire-{index}",
                tickers=[TICKER],
                title_key="same-wire-story",
                materiality="material",
            )

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        assert len(digest.entries) == 1
        assert digest.entries[0].merged == 3
        assert digest.total == 3
        assert "2 further stories" in digest.text()

    def test_the_digest_is_capped_and_says_what_it_represents(self, session):
        for index in range(5):
            _story(
                session,
                title=f"Story {index}",
                url=f"https://x.test/s{index}",
                tickers=[TICKER],
                title_key=f"story-{index}",
            )

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=2, now=NOW
        )

        assert len(digest.entries) == 2
        assert "2 distinct stories (2 of 5" in digest.text()


class TestTheCoverageCounts:
    def test_the_window_is_the_window(self, session):
        """A story older than the window is not evidence about now, and counting it would
        overstate how much news this company has."""
        _story(session, title="Recent", url="https://x.test/recent", tickers=[TICKER])
        _story(
            session,
            title="Old",
            url="https://x.test/old",
            tickers=[TICKER],
            published_at=NOW - dt.timedelta(days=45),
        )

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        assert digest.total == 1
        assert [entry.headline for entry in digest.entries] == ["Recent"]

    def test_the_counts_cover_the_whole_window_not_the_shown_rows(self, session):
        """The inventory tells the reader how much news there is; a figure taken from the
        top few rows would understate exactly the instruments that have the most."""
        for index in range(6):
            item = _story(
                session,
                title=f"Story {index}",
                url=f"https://x.test/c{index}",
                tickers=[TICKER],
                title_key=f"c-{index}",
            )
            if index < 4:
                _appraisal(session, item, credibility=0.2)

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=1, now=NOW
        )

        assert len(digest.entries) == 1
        assert digest.total == 6
        assert digest.appraised_total == 4
        assert digest.unappraised_total == 2

    def test_single_source_is_counted_from_the_flags(self, session):
        """A substring test on the JSON would count `capped_unconfirmed` too, and the two
        are different findings -- "no other carrier" against "material and uncorroborated"."""
        for index, flags in enumerate([["single_source"], ["capped_unconfirmed"], []]):
            item = _story(
                session,
                title=f"Story {index}",
                url=f"https://x.test/f{index}",
                tickers=[TICKER],
                title_key=f"f-{index}",
            )
            _appraisal(session, item, credibility=0.1, flags=flags)

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        assert digest.appraised_total == 3
        assert digest.single_source_total == 1

    def test_an_unappraised_story_is_marked_as_unjudged(self, session):
        _story(session, title="Nobody judged this", url="https://x.test/u", tickers=[TICKER])

        digest = evidence_of.news_digest(
            session, subject_type="instrument", subject_id=TICKER, window_days=30, limit=12, now=NOW
        )

        entry = digest.entries[0]
        assert entry.assessed is False
        assert entry.credibility is None
        # Not "credibility 0.000", which would read as a judgement that the story is worthless.
        assert "unappraised (nothing has judged this story)" in digest.text()
        assert entry.components["credibility_assessed"] is False


class TestTheHeldDocuments:
    def _document(self, settings, name: str, body: str) -> str:
        path = settings.data_dir / "raw" / "filings" / TICKER
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(body.encode("utf-8"))
        return f"raw/filings/{TICKER}/{name}"

    def _filing(self, session, *, raw_path: str | None, filed_at: dt.datetime, url: str) -> Filing:
        row = Filing(
            instrument_t212_ticker=TICKER,
            source="edgar",
            filing_type="10-K",
            filed_at=filed_at,
            period_end=dt.date(2025, 12, 31),
            url=url,
            raw_path=raw_path,
            status="parsed",
        )
        session.add(row)
        session.flush()
        return row

    def test_the_stored_file_is_read_as_text(self, session, settings):
        _instrument(session)
        raw = self._document(settings, "report.htm", "<p>Revenue was 1,234</p>")
        self._filing(session, raw_path=raw, filed_at=NOW, url="https://x.test/a")

        documents, problems = evidence_of.held_documents(
            session, settings, TICKER, limit=3, max_document_chars=10_000, max_total_chars=10_000
        )

        assert problems == []
        assert len(documents) == 1
        assert "Revenue was 1,234" in documents[0].text
        assert documents[0].truncated is False
        assert "10-K" in documents[0].label

    def test_the_newest_filings_come_first(self, session, settings):
        _instrument(session)
        old = self._document(settings, "old.htm", "old annual report")
        new = self._document(settings, "new.htm", "new annual report")
        self._filing(session, raw_path=old, filed_at=NOW - dt.timedelta(days=400), url="https://x.test/old")
        self._filing(session, raw_path=new, filed_at=NOW, url="https://x.test/new")

        documents, _ = evidence_of.held_documents(
            session, settings, TICKER, limit=3, max_document_chars=10_000, max_total_chars=10_000
        )

        assert "new annual report" in documents[0].text

    def test_the_total_budget_bounds_what_is_sent(self, session, settings):
        """The prompt is a bill. Three filings of a megabyte each is a bill nobody agreed to,
        so the cap is spent newest-first and each document is cut in the middle."""
        _instrument(session)
        for index in range(3):
            raw = self._document(settings, f"doc{index}.htm", "x" * 5_000)
            self._filing(
                session,
                raw_path=raw,
                filed_at=NOW - dt.timedelta(days=index),
                url=f"https://x.test/{index}",
            )

        documents, _ = evidence_of.held_documents(
            session, settings, TICKER, limit=3, max_document_chars=1_000, max_total_chars=1_500
        )

        assert sum(document.chars for document in documents) <= 1_500 + 200
        assert all(document.truncated for document in documents)

    def test_a_document_that_cannot_be_read_is_a_stated_problem(self, session, settings):
        """Not a silent omission: the reader is being asked to accept a conclusion drawn
        without it, and "no annual reports held" is a different claim."""
        _instrument(session)
        self._filing(session, raw_path="raw/filings/TEST_US_EQ/missing.htm", filed_at=NOW, url="u")

        documents, problems = evidence_of.held_documents(
            session, settings, TICKER, limit=3, max_document_chars=10_000, max_total_chars=10_000
        )

        assert documents == []
        assert len(problems) == 1 and "could not be read as text" in problems[0]

    def test_a_pdf_is_a_problem_rather_than_an_empty_document(self, session, settings):
        _instrument(session)
        raw = self._document(settings, "accounts.pdf", "not really a pdf")
        self._filing(session, raw_path=raw, filed_at=NOW, url="p")

        documents, problems = evidence_of.held_documents(
            session, settings, TICKER, limit=3, max_document_chars=10_000, max_total_chars=10_000
        )

        assert documents == []
        assert len(problems) == 1


class TestTheStoredFigures:
    def _period(self, session, *, period_end: dt.date, metrics: dict, sources: dict, source="llm_extraction"):
        row = FundamentalPeriod(
            instrument_t212_ticker=TICKER,
            period_end=period_end,
            period_type="annual",
            currency="USD",
            source=source,
            metrics=metrics,
            metric_sources=sources,
            confidence=0.8,
        )
        session.add(row)
        session.flush()
        return row

    def test_each_figure_carries_the_words_it_came_from(self, session):
        """The report has to be able to quote, and the quotation already exists: it is the
        span the extraction gate recorded when the figure was stored."""
        _instrument(session)
        self._period(
            session,
            period_end=dt.date(2025, 12, 31),
            metrics={"revenue": 1_000_000.0, "net_income": 100_000.0},
            sources={
                "revenue": {"value": 1_000_000.0, "span": "Total revenue 1,000,000", "location": "Income statement"},
                "net_income": {"value": 100_000.0, "span": "Net income 100,000", "location": "Income statement"},
            },
        )

        text = evidence_of.stored_figures(session, TICKER)

        assert 'quoted: "Total revenue 1,000,000"' in text
        assert "(Income statement)" in text

    def test_a_figure_nobody_can_quote_is_not_offered(self, session):
        """A number without a span is one this system cannot show its work for, and offering
        it to a model required to quote its evidence invites a quotation to be invented."""
        _instrument(session)
        self._period(
            session,
            period_end=dt.date(2025, 12, 31),
            metrics={"revenue": 1_000_000.0},
            sources={},
        )

        assert evidence_of.stored_figures(session, TICKER) == ""

    def test_a_period_with_no_spans_does_not_take_a_slot(self, session):
        """Three slots of "no quoted figures" would push out the annual reports the reader
        came for -- and the provider-sourced periods are the ones that land there."""
        _instrument(session)
        self._period(
            session,
            period_end=dt.date(2026, 6, 30),
            metrics={"revenue": 2_000_000.0},
            sources={},
            source="yahoo_statements",
        )
        self._period(
            session,
            period_end=dt.date(2025, 12, 31),
            metrics={"revenue": 1_000_000.0},
            sources={"revenue": {"value": 1.0, "span": "Total revenue 1,000,000", "location": "IS"}},
        )

        text = evidence_of.stored_figures(session, TICKER, periods=1)

        assert "2025-12-31" in text
        assert "2026-06-30" not in text

    def test_a_multiline_span_is_collapsed_to_one_line(self, session):
        """A span can be a table row torn out with its newlines intact, and a quotation that
        runs over five lines reads as five quotations when the model cites it back."""
        _instrument(session)
        self._period(
            session,
            period_end=dt.date(2025, 12, 31),
            metrics={"revenue": 1_000_000.0},
            sources={"revenue": {"value": 1.0, "span": "Total\n  revenue   1,000,000", "location": "IS"}},
        )

        text = evidence_of.stored_figures(session, TICKER)

        assert 'quoted: "Total revenue 1,000,000"' in text


class TestTheWholeEvidenceSet:
    def test_an_instrument_gets_documents_figures_and_its_last_decision(self, session, settings):
        _instrument(session)

        built = evidence_of.build_evidence(
            session, settings, subject_type="instrument", subject_id=TICKER, now=NOW
        )

        assert built.label == "Test Co (TEST_US_EQ)"
        assert built.subject_type == "instrument"
        # Nothing held, and the evidence says so rather than reading as a company with a
        # short history.
        assert "No stored filing text" in built.inventory()
        assert "None held" in built.text()

    def test_the_inventory_names_what_is_not_available(self, session, settings):
        """The reader is being asked to approve a spend, and the gaps are the part they
        cannot see from the outside."""
        _instrument(session)

        inventory = evidence_of.build_evidence(
            session, settings, subject_type="instrument", subject_id=TICKER, now=NOW
        ).inventory()

        assert "Not available, and not asked for" in inventory
        assert "broker research" in inventory
        assert "news" in inventory.lower()

    def test_a_sector_run_says_it_reads_the_corpus_only(self, session, settings):
        _story(session, title="Refining margins compress", url="https://x.test/m", sectors=[SECTOR])

        built = evidence_of.build_evidence(
            session, settings, subject_type="sector", subject_id=SECTOR, now=NOW
        )

        assert built.documents == []
        assert built.figures == ""
        assert "no refresh pipeline" not in built.inventory(), "that belongs to the run, not here"
        assert "Sector runs read the news corpus only" in built.inventory()
        assert built.label == "Energy sector"
        assert built.news.total == 1

    def test_the_decision_note_reads_the_last_decision(self, session):
        from awltux.db import DecisionRun

        _instrument(session)
        session.add(
            DecisionRun(
                instrument_t212_ticker=TICKER,
                created_at=utcnow(),
                state={},
                state_sha256="x",
                engine="offline",
                answers={},
                long_term_action="hold",
                confidence=0.4,
                gate_allowed=False,
                gate={"reason": "evidence thin"},
            )
        )
        session.flush()

        note = evidence_of.decision_note(session, TICKER)

        assert "hold" in note
        assert "refused by the risk gate" in note
        # Named as the system's own view rather than as an input document, because a
        # deep-dive that treats it as evidence would just agree with it.
        assert "not an input document" in note

    def test_no_decision_yet_is_an_empty_note(self, session):
        _instrument(session)
        assert evidence_of.decision_note(session, TICKER) == ""


class TestFittingTheContextWindow:
    """Measured 2026-10-09: the evidence for MSFT is 410,826 characters, about 120,800 tokens,
    against a 128,000-token window with a 16,000-token answer requested. The bounds in
    `research.*` are what the caller asked for; the window is what refuses them."""

    def _document(self, settings, name: str, words: int) -> str:
        path = settings.data_dir / "raw" / "filings" / TICKER
        path.mkdir(parents=True, exist_ok=True)
        (path / name).write_bytes(("word " * words).encode("utf-8"))
        return f"raw/filings/{TICKER}/{name}"

    def _filing(self, session, *, raw_path: str, filed_at: dt.datetime, url: str) -> None:
        session.add(
            Filing(
                instrument_t212_ticker=TICKER,
                source="edgar",
                filing_type="10-K",
                filed_at=filed_at,
                url=url,
                raw_path=raw_path,
                status="parsed",
            )
        )
        session.flush()

    def _tokens(self, built) -> int:
        from awltux.analysis.state import estimate_tokens

        return estimate_tokens(built.text())

    def test_a_huge_evidence_set_is_cut_to_the_window(self, session, settings):
        _instrument(session)
        self._filing(
            session,
            raw_path=self._document(settings, "big.htm", 60_000),
            filed_at=NOW,
            url="https://x.test/big",
        )
        for index in range(6):
            _story(
                session,
                title=f"Story {index}",
                url=f"https://x.test/w{index}",
                tickers=[TICKER],
                title_key=f"w-{index}",
            )
        session.flush()
        settings.research.context_tokens = 40_000

        built = evidence_of.build_evidence(
            session, settings, subject_type="instrument", subject_id=TICKER, now=NOW
        )

        budget = 40_000 - settings.research.max_output_tokens - settings.research.reserve_tokens
        assert self._tokens(built) <= budget
        assert built.dropped, "the report has to be able to say what it did not read"

    def test_a_window_with_no_room_for_the_answer_is_refused(self):
        """The trimmer is asked to fit ``context - output - reserve`` tokens, so an output
        budget larger than the window leaves it fitting nothing -- and it would send the model
        an empty question for the price of a full run. A config mistake, refused where made."""
        import pytest as pytest_module
        from pydantic import ValidationError

        from awltux.config import ResearchConfig

        with pytest_module.raises(ValidationError, match="must exceed"):
            ResearchConfig(context_tokens=10_000, max_output_tokens=16_000)

        # The shipped configuration is a valid one, which is the half that matters.
        assert ResearchConfig().context_tokens > (
            ResearchConfig().max_output_tokens + ResearchConfig().reserve_tokens
        )

    def test_the_documents_are_cut_before_the_news_is_thrown_away(self, session, settings):
        """The regression this pairing exists for.

        The first version shed the decision, then the figures, then every headline, and only
        then touched the documents -- which are 95% of the prompt, so it deleted a whole input
        to save a per cent and still had to cut. Removing 5,000 characters to save 1,500
        tokens, at the cost of the news the prompt has a section about, is the wrong trade
        however low the block ranks.
        """
        _instrument(session)
        self._filing(
            session,
            raw_path=self._document(settings, "big.htm", 60_000),
            filed_at=NOW,
            url="https://x.test/big",
        )
        for index in range(6):
            _story(
                session,
                title=f"Story {index}",
                url=f"https://x.test/n{index}",
                tickers=[TICKER],
                title_key=f"n-{index}",
            )
        session.flush()
        settings.research.context_tokens = 40_000

        built = evidence_of.build_evidence(
            session, settings, subject_type="instrument", subject_id=TICKER, now=NOW
        )

        assert len(built.news.entries) == 6, "the digest is not what paid for the document"
        assert built.news.entries[0].headline == "Story 5" or built.news.entries[0].headline
        assert built.figures is not None
        assert any("cut to fit" in entry for entry in built.dropped)
        assert not any("headline" in entry for entry in built.dropped)

    def test_a_small_block_is_dropped_when_the_documents_cannot_help(self):
        """With nothing left to cut, the least load-bearing material goes -- in that order.

        Asserted on the order rather than the outcome because with a budget small enough to
        shed a small block, everything after it goes too: what this pins is that the figures
        are sacrificed before the decision, and the decision before a headline.
        """
        import types

        built = evidence_of.Evidence(
            subject_type="instrument",
            subject_id=TICKER,
            label="Test Co",
            figures="f" * 200,
            decision="d" * 200,
            news=evidence_of.NewsDigest(
                entries=[
                    evidence_of.NewsEntry(
                        headline=f"Headline {index}",
                        published_at=None,
                        priority=1.0 - index / 10,
                        components={},
                        materiality="material",
                        credibility=None,
                        assessed=False,
                        flags=[],
                        carrier_count=None,
                        independent_sources=None,
                        publisher=None,
                        source=None,
                        relevance_reason=None,
                    )
                    for index in range(3)
                ],
                window_days=30,
                total=3,
            ),
        )
        window = types.SimpleNamespace(
            context_tokens=1_000, max_output_tokens=900, reserve_tokens=50
        )

        evidence_of._fit_to_context(built, window)

        assert built.dropped == [
            "the quoted figures, which the documents already contain",
            "the previous decision, to fit the context window",
            "the lowest-priority headline: Headline 2",
            "the lowest-priority headline: Headline 1",
            "the lowest-priority headline: Headline 0",
        ]
        assert built.news.entries == []
