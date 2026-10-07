"""The pipeline that applies scepticism, and the weighting it produces.

The point of these tests is that the appraisal is not decorative. A story graded
weak must actually move the sentiment number less than a story graded strong --
otherwise the whole layer is a labelprinted on top of an unchanged model.
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from awltux.analysis import news_analysis, sentiment
from awltux.analysis.corroboration import Carrier, Corroboration
from awltux.analysis.rhetoric import RhetoricReport
from awltux.analysis.sources import lookup
from awltux.db import Instrument, NewsAnalysis, NewsItem, utcnow
from awltux.llm import news_sceptic
from awltux.llm.classify import normalise_classification


def make_item(
    session,
    title: str,
    *,
    url: str = "https://www.reuters.com/business/story",
    tickers: list[str] | None = None,
    materiality: str | None = "material",
    direction: str | None = "negative",
    sentiment_score: float | None = -0.7,
    hours_ago: float = 2.0,
    source: str = "google_news",
    event_type: str | None = "earnings",
) -> NewsItem:
    row = NewsItem(
        source=source,
        url=url,
        url_hash=f"{title[:20]}-{url[-12:]}",
        title=title,
        summary="Acme said trading weakened and full-year profit will be at the lower end.",
        published_at=utcnow() - dt.timedelta(hours=hours_ago),
        tickers=tickers or ["ACME_US_EQ"],
        materiality=materiality,
        direction=direction,
        sentiment_score=sentiment_score,
        relevance=0.8,
        event_type=event_type,
    )
    session.add(row)
    session.flush()
    return row


@pytest.fixture
def universe(session):
    instrument = Instrument(
        t212_ticker="ACME_US_EQ",
        name="Acme Corporation",
        instrument_type="STOCK",
        exchange_name="NASDAQ",
        yahoo_symbol="ACME",
        in_universe=True,
    )
    session.add(instrument)
    session.flush()
    return instrument


def fake_analyser(**kwargs):
    """A stand-in for the model that returns a well-formed appraisal."""
    return {
        "claims": [
            {
                "text": "Full-year profit will be at the lower end of guidance",
                "claim_type": "attributed_statement",
                "attribution": "company_statement",
                "primary_register": "Company filings",
                "where_to_check": "The company's own announcement",
                "support": 0.6,
                "checkable": True,
            }
        ],
        "techniques": [],
        "omissions": ["No comparison to the same guidance a quarter ago"],
        "headline_matches_body": True,
        "headline_overstates": None,
        "who_benefits": "Short sellers",
        "agenda_basis": "Incentives only, no accusation",
        "base_rate": "Most profit warnings are followed by a further downgrade",
        "what_would_change_my_mind": "The audited accounts showing margins unchanged",
        "primary_source": "The company's own announcement",
        "scepticism_summary": "A company statement about its own guidance.",
        "injection_suspected": False,
        "engine": "deepseek:test",
    }


class TestSelection:
    def test_material_news_qualifies(self, universe, settings):
        interesting, reason = news_analysis.is_interesting(
            _stub(materiality="material"),
            rhetoric=RhetoricReport(score=0.0),
            publisher_kind="wire",
            held=False,
            carrier_count=5,
            settings=settings,
        )
        assert interesting
        assert "material" in reason

    def test_shocking_framing_qualifies_even_when_materiality_is_low(self, settings):
        interesting, reason = news_analysis.is_interesting(
            _stub(materiality="mild"),
            rhetoric=RhetoricReport(score=0.6),
            publisher_kind="wire",
            held=False,
            carrier_count=5,
            settings=settings,
        )
        assert interesting
        assert "manipulation" in reason

    def test_held_names_get_attention_for_ordinary_news(self, settings):
        interesting, reason = news_analysis.is_interesting(
            _stub(materiality="mild"),
            rhetoric=RhetoricReport(score=0.0),
            publisher_kind="wire",
            held=True,
            carrier_count=5,
            settings=settings,
        )
        assert interesting
        assert "held" in reason

    def test_a_press_release_alone_qualifies_because_it_needs_checking(self, settings):
        interesting, reason = news_analysis.is_interesting(
            _stub(materiality="mild"),
            rhetoric=RhetoricReport(score=0.0),
            publisher_kind="press_release",
            held=False,
            carrier_count=1,
            settings=settings,
        )
        assert interesting
        assert "press release" in reason

    def test_dull_well_covered_routine_news_is_skipped_with_a_reason(self, settings):
        interesting, reason = news_analysis.is_interesting(
            _stub(materiality="mild"),
            rhetoric=RhetoricReport(score=0.0),
            publisher_kind="wire",
            held=False,
            carrier_count=9,
            settings=settings,
        )
        assert not interesting
        assert reason == ""


def _stub(**overrides):
    """A minimal object exposing what is_interesting reads."""
    row = NewsItem(
        source="google_news",
        url="https://www.reuters.com/x",
        url_hash="stub",
        title="Acme warns on profit",
        materiality=overrides.get("materiality"),
        direction="negative",
    )
    return row


#: The subject these appraisals are about. `appraise_item` requires one: whether the
#: subject is held is the one input that legitimately differs between two appraisals
#: of the same story, so a caller that cannot say which subject it means cannot call it.
SUBJECT = news_analysis.Subject("instrument", "TEST_US_EQ")


class TestAppraisal:
    def test_the_appraisal_records_source_framing_and_corroboration(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit as demand weakens")
        row = news_analysis.appraise_item(
            item,
            subject=SUBJECT,
            settings=settings,
            rhetoric=RhetoricReport(score=0.1),
            corroboration=Corroboration(origins=["reuters.com"], carriers=[
                Carrier("reuters.com", item.title, item.url, lookup(item.url))
            ]),
        )
        assert row.source_kind == "wire"
        assert row.source_assessed is True
        assert row.independent_sources == 1
        assert row.credibility is not None
        assert row.evidence_grade in ("unsupported", "weak", "mixed", "moderate", "strong")
        assert row.factors["source_weight"] > 0

    def test_the_model_supplies_claims_and_the_code_supplies_the_number(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit as demand weakens")
        row = news_analysis.appraise_item(
            item, subject=SUBJECT, settings=settings, analyser=fake_analyser
        )
        assert row.claims and row.claims[0]["claim_type"] == "attributed_statement"
        assert row.omissions
        assert row.what_would_change_my_mind
        # The credibility is computed here, never returned by the model.
        assert row.engine == "deepseek:test"
        assert isinstance(row.credibility, float)

    def test_a_model_failure_does_not_lose_the_appraisal(self, session, universe, settings):
        def exploding(**_kwargs):
            raise RuntimeError("model unavailable")

        item = make_item(session, "Acme warns on profit")
        row = news_analysis.appraise_item(item, subject=SUBJECT, settings=settings, analyser=exploding)
        assert row.credibility is not None
        assert row.engine == "deterministic"

    def test_an_event_type_routes_the_claim_to_its_register(self, session, universe, settings):
        item = make_item(session, "Acme reports results", event_type="earnings")
        row = news_analysis.appraise_item(item, subject=SUBJECT, settings=settings, analyser=fake_analyser)
        assert any("Company filings" in caveat for caveat in row.caveats)

    def test_a_rumour_has_no_primary_source_and_is_capped(self, session, universe, settings):
        def rumour_analyser(**_kwargs):
            return {
                "claims": [
                    {
                        "text": "Acme is being taken over",
                        "claim_type": "rumour",
                        "attribution": "market_rumour",
                    }
                ],
                "engine": "deepseek:test",
            }

        item = make_item(
            session,
            "Sources say Acme takeover rumour circulates",
            url="https://unknown-blog.example/acme",
            materiality="critical",
        )
        row = news_analysis.appraise_item(item, subject=SUBJECT, settings=settings, analyser=rumour_analyser)
        assert "no_primary_source" in row.flags
        assert row.credibility <= 0.3


class TestRunAnalysis:
    def test_only_interesting_items_are_appraised(self, session, universe, settings):
        make_item(session, "Acme hires a new regional manager", materiality="mild",
                  sentiment_score=-0.1, hours_ago=3, url="https://www.reuters.com/a")
        report = news_analysis.analyse_universe(session, settings=settings)
        assert report["examined"] == 1
        assert report["selected"] == 0
        assert report["appraised"] == 0

    def test_material_news_is_appraised_and_stored(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit")
        report = news_analysis.analyse_universe(session, settings=settings)
        assert report["appraised"] == 1
        stored = session.get(NewsAnalysis, 1)
        assert stored is not None
        assert stored.news_item_id == item.id

    def test_the_paid_half_is_rationed_but_the_free_half_still_runs(self, session, universe, settings):
        for index in range(3):
            make_item(
                session,
                f"Acme warns on profit number {index}",
                url=f"https://www.reuters.com/story-{index}",
            )
        report = news_analysis.analyse_universe(
            session, settings=settings, analyser=fake_analyser, limit=1
        )
        assert report["appraised"] == 3
        assert report["deep_analysed"] == 1

    def test_re_running_does_not_re_appraise_a_fresh_verdict(self, session, universe, settings):
        make_item(session, "Acme warns on profit")
        first = news_analysis.analyse_universe(session, settings=settings, analyser=fake_analyser)
        second = news_analysis.analyse_universe(session, settings=settings, analyser=fake_analyser)
        assert first["deep_analysed"] == 1
        assert second["deep_analysed"] == 0
        assert second["appraised"] == 1

    def test_a_stale_verdict_is_refreshed(self, session, universe, settings):
        make_item(session, "Acme warns on profit")
        news_analysis.analyse_universe(session, settings=settings, analyser=fake_analyser)
        stored = session.get(NewsAnalysis, 1)
        stored.analysed_at = utcnow() - dt.timedelta(days=30)
        session.flush()

        report = news_analysis.analyse_universe(
            session, settings=settings, analyser=fake_analyser, refresh_after_days=7
        )
        assert report["deep_analysed"] == 1
        assert session.query(NewsAnalysis).count() == 1

    def test_refreshing_updates_in_place_rather_than_duplicating(self, session, universe, settings):
        make_item(session, "Acme warns on profit")
        news_analysis.analyse_universe(session, settings=settings)
        stored = session.get(NewsAnalysis, 1)
        stored.analysed_at = utcnow() - dt.timedelta(days=30)
        session.flush()
        news_analysis.analyse_universe(session, settings=settings)
        assert session.query(NewsAnalysis).count() == 1

    def test_untagged_news_is_not_attributed_to_anything(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit", materiality="critical")
        item.tickers = []
        session.flush()
        report = news_analysis.analyse_universe(session, settings=settings)
        assert report["appraised"] == 0


class TestCorroborationIsMeasuredAgainstTheStory:
    """Corroboration used to be measured against the whole fortnight, not the story.

    `analyse_universe` handed the entire corroboration pool to `assess`, which counts
    the candidates it is given. So `carrier_count` was the pool size (400) and
    `independent_count` was the *window's* origins for every story alike -- measured on
    the live database, a headline about Apple and one about an unrelated micro-cap both
    returned `carrier_count=400, independent_count=7`.

    Two consequences, both wrong, and both asserted below: the single-source condition
    in `is_interesting` could never fire, so coverage from a press release or an
    aggregator was never selected; and every appraisal was told the story was carried by
    seven independent origins, which is what the credibility weighting reads.

    The same mistake was the whole of the cost. `assess` groups its candidates pairwise,
    so 400 candidates is about 80,000 title comparisons per story; over the live pool the
    per-story work fell from 5.8 seconds to 14 milliseconds once each story was measured
    against its own coverage.
    """

    def test_the_index_groups_by_every_ticker_a_row_names(self, session):
        """A story naming two companies is coverage for both.

        Rows carry a list of tickers, and a story about a deal names both parties; an
        index built on only the first would hide half of that story's coverage.
        """
        make_item(session, "Acme warns", tickers=["ACME_US_EQ", "OTHER_US_EQ"])

        pool = list(session.execute(select(NewsItem)).scalars())
        index = news_analysis._coverage_index(pool)

        assert len(index["ACME_US_EQ"]) == 1
        assert len(index["OTHER_US_EQ"]) == 1

    def test_a_story_is_measured_against_its_own_coverage_only(self, session):
        mine = [
            make_item(session, "Acme warns on profit", url=f"https://a{i}.example/x")
            for i in range(3)
        ]
        for index in range(40):
            make_item(
                session,
                f"Unrelated story {index}",
                url=f"https://b{index}.example/y",
                tickers=["ELSEWHERE_US_EQ"],
            )

        pool = list(session.execute(select(NewsItem)).scalars())
        index = news_analysis._coverage_index(pool)
        coverage = news_analysis.coverage_of(mine[0], index)

        assert {row.id for row in coverage} == {row.id for row in mine}
        assert len(coverage) == 3, "the 40 unrelated rows must not be carriers"

    def test_two_unrelated_stories_do_not_get_the_same_answer(self, session):
        """The measurement that exposed it: identical input gave identical output."""
        for index in range(5):
            make_item(
                session,
                "Acme warns on profit as demand weakens",
                url=f"https://acme{index}.example/a",
                tickers=["ACME_US_EQ"],
            )
        make_item(
            session,
            "Zenith wins a contract",
            url="https://zenith.example/b",
            tickers=["ZENITH_US_EQ"],
        )

        pool = list(session.execute(select(NewsItem)).scalars())
        index = news_analysis._coverage_index(pool)
        acme = news_analysis.coverage_of(
            next(r for r in pool if r.tickers == ["ACME_US_EQ"]), index
        )
        zenith = news_analysis.coverage_of(
            next(r for r in pool if r.tickers == ["ZENITH_US_EQ"]), index
        )

        assert len(acme) == 5
        assert len(zenith) == 1, "Zenith's story is single-source; Acme's is not"

    def test_a_story_the_pool_does_not_reach_still_has_itself(self, session):
        """Single-source is the honest answer with nothing to compare against -- and the
        alternative, an empty candidate list, would report no coverage at all."""
        lonely = make_item(session, "Acme warns", tickers=["ACME_US_EQ"])
        index = news_analysis._coverage_index([])

        assert news_analysis.coverage_of(lonely, index) == [lonely]

    def test_the_answer_no_longer_depends_on_how_big_the_window_is(self, session):
        """The pool used to be the unit of measurement, so a busier week changed every
        story's corroboration without any story changing."""
        story = make_item(session, "Acme warns on profit", tickers=["ACME_US_EQ"])
        index = news_analysis._coverage_index([story])

        assert len(news_analysis.coverage_of(story, index)) == 1

        # Bury it in a large, unrelated window.
        for position in range(200):
            make_item(
                session,
                f"Noise {position}",
                url=f"https://noise{position}.example/z",
                tickers=[f"T{position}_US_EQ"],
            )
        wide = list(session.execute(select(NewsItem)).scalars())
        wide_index = news_analysis._coverage_index(wide)

        assert len(news_analysis.coverage_of(story, wide_index)) == 1, (
            "a story's coverage must not grow with the size of the news window"
        )


class TestSentimentWeighting:
    def test_a_weak_article_moves_the_needle_less_than_a_strong_one(self, session, universe, settings):
        weak = make_item(session, "Acme collapse wipes out investors",
                         url="https://unknown-blog.example/a", sentiment_score=-1.0)
        strong = make_item(session, "Acme warns on profit",
                           url="https://www.reuters.com/b", sentiment_score=-1.0)

        _, _, _ = sentiment.news_sentiment(
            [weak], credibility={weak.id: 0.05}, as_of=utcnow()
        )
        weak_score, weak_weight, _ = sentiment.news_sentiment(
            [weak], credibility={weak.id: 0.05}, as_of=utcnow()
        )
        strong_score, strong_weight, _ = sentiment.news_sentiment(
            [strong], credibility={strong.id: 0.9}, as_of=utcnow()
        )
        assert weak_weight < strong_weight
        # Scores are both -1, so the damping shows up in the weight, not the sign.
        assert weak_score == strong_score == pytest.approx(-1.0)

    def test_an_unappraised_article_is_discounted_not_ignored(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit", sentiment_score=-1.0)
        _, weight, _ = sentiment.news_sentiment([item], credibility={}, as_of=utcnow())
        _, assessed, _ = sentiment.news_sentiment(
            [item], credibility={item.id: 1.0}, as_of=utcnow()
        )
        assert 0 < weight < assessed

    def test_low_credibility_coverage_is_counted_and_explained(self, session, universe, settings):
        item = make_item(session, "Acme collapse wipes out investors", sentiment_score=-1.0)
        score, components = sentiment.compute_instrument_sentiment(
            items=[item], bars=[], credibility={item.id: 0.1}, as_of=utcnow()
        )
        assert components.low_credibility_articles == 1
        assert components.mean_credibility == pytest.approx(0.1)
        assert any("weak" in note for note in components.notes)

    def test_unconfirmed_articles_are_reported(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit", sentiment_score=-1.0)
        _, components = sentiment.compute_instrument_sentiment(
            items=[item], bars=[], credibility={item.id: 0.8},
            unconfirmed={item.id}, as_of=utcnow(),
        )
        assert components.unconfirmed_articles == 1
        assert any("single source" in note for note in components.notes)

    def test_an_unconfirmed_article_about_another_name_is_not_counted(self, session, universe, settings):
        mine = make_item(session, "Acme warns", sentiment_score=-1.0)
        other = make_item(session, "Other warns", url="https://www.reuters.com/c",
                          sentiment_score=-1.0)
        _, components = sentiment.compute_instrument_sentiment(
            items=[mine], bars=[], credibility={}, unconfirmed={other.id}, as_of=utcnow()
        )
        assert components.unconfirmed_articles == 0


class TestModelOutputValidation:
    def test_a_claim_whose_span_is_not_in_the_item_is_dropped(self, settings):
        document = "<document>\nHeadline: Acme warns on profit\n</document>"
        claims = news_sceptic.normalise_claims(
            [
                {"text": "Profit will fall", "span": "Acme warns on profit"},
                {"text": "The CEO resigned", "span": "the chief executive resigned today"},
            ],
            document,
        )
        assert len(claims) == 1
        assert claims[0].text == "Profit will fall"

    def test_a_long_span_may_be_trimmed_but_not_invented(self, settings):
        document = "the company said full year profit will be at the lower end of guidance"
        trimmed = news_sceptic.normalise_claims(
            [{"text": "x", "span": "the company said full year profit will be at the lower end"}],
            document,
        )
        assert len(trimmed) == 1
        invented = news_sceptic.normalise_claims(
            [{"text": "x", "span": "the company said full year losses were catastrophic"}],
            document,
        )
        assert invented == []

    def test_an_invented_technique_name_is_dropped(self, settings):
        techniques = news_sceptic.normalise_techniques(
            [
                {"name": "appeal_to_fear", "example": "bloodbath"},
                {"name": "vibes_based_persuasion", "example": "trust me"},
            ]
        )
        assert [t["technique"] for t in techniques] == ["appeal_to_fear"]

    def test_an_unknown_claim_type_and_attribution_are_coerced_not_stored(self, settings):
        document = "acme warns on profit"
        claims = news_sceptic.normalise_claims(
            [{"text": "x", "span": "acme warns on profit",
              "claim_type": "vibes", "attribution": "the universe"}],
            document,
        )
        assert claims[0].claim_type == "reported_fact"
        assert claims[0].attribution == "none"

    def test_the_claim_list_is_capped_so_padding_is_pointless(self, settings):
        document = "acme warns on profit and revenue fell and margins narrowed and debt rose"
        payload = [
            {"text": f"claim {index}", "span": "acme warns on profit"}
            for index in range(30)
        ]
        claims = news_sceptic.normalise_claims(payload, document)
        # Duplicates collapse as well, so this is well under the cap either way.
        assert len(claims) <= news_sceptic.MAX_CLAIMS

    def test_a_non_dict_response_is_ignored(self, settings):
        assert news_sceptic.normalise_analysis(["not", "a", "dict"], "x") is None

    def test_analysis_without_a_key_is_absent_rather_than_faked(self, settings):
        """No key must mean the step is skipped visibly, not stubbed."""
        assert news_sceptic.build_analyser(settings) is None

    def test_analyze_item_returns_none_when_unconfigured(self, settings):
        assert news_sceptic.analyse_item(title="x", summary=None, settings=settings) is None


class TestClassifierEventTypes:
    def test_a_known_event_type_is_kept(self, settings):
        result = normalise_classification({"materiality": "material", "event_type": "earnings"})
        assert result["event_type"] == "earnings"

    def test_an_invented_event_type_becomes_other(self, settings):
        result = normalise_classification({"materiality": "material", "event_type": "vibes"})
        assert result["event_type"] == "other"

    def test_a_missing_event_type_is_other_not_none(self, settings):
        result = normalise_classification({"materiality": "mild"})
        assert result["event_type"] == "other"


class TestClassifierIdentityKeys:
    """The three fields the same-event grouping compares and shows.

    ``metric`` is the one that was missing, and the failure it fixes is specific: on
    2026-10-07 the grouping joined "Golar LNG stock gains 1.65 percent in October 5
    trading" with "BTIG raises Golar LNG stock price target to $75" at 0.7599, and a
    genuine EasyJet takeover pair at 0.7925 -- so the false pair and the true pair were
    not separable by any threshold. They differ in exactly this field.
    """

    def test_a_known_metric_is_kept(self):
        result = normalise_classification({"metric": "price_target"})
        assert result["metric"] == "price_target"

    def test_an_invented_metric_becomes_none(self):
        result = normalise_classification({"metric": "vibes"})
        assert result["metric"] == "none"

    def test_metric_none_is_a_stated_answer_not_an_absent_one(self):
        """The grouping reads a falsy value as "not stated" and abstains. A story that
        was read and found to be about no number is a different state, and the literal
        string is what distinguishes them -- the same reason `news_item.relevant` is
        nullable rather than defaulting to false."""
        assert normalise_classification({"metric": "none"})["metric"] == "none"
        assert normalise_classification({})["metric"] == "none"

    def test_period_and_magnitude_are_kept_as_written(self):
        result = normalise_classification({"period": "FY26", "magnitude": "$7.7bn"})
        assert result["period"] == "FY26"
        assert result["magnitude"] == "$7.7bn"

    def test_an_unstated_period_is_absent_rather_than_a_word(self):
        """"unknown" stored literally would be a value two stories could agree on, and
        the grouping would then join them *by* the word."""
        for written in ("", "unknown", "n/a", "null", None):
            result = normalise_classification({"period": written, "magnitude": written})
            assert result["period"] is None, written
            assert result["magnitude"] is None, written

    def test_a_sentence_in_a_detail_field_is_truncated(self):
        """They are rendered beside a headline, not parsed, so a paragraph would be
        printed as a paragraph."""
        result = normalise_classification({"magnitude": "x" * 200})
        assert len(result["magnitude"]) == 32

    def test_the_classification_reaches_the_row_through_one_helper(self):
        """Both callers -- the ingest path and the relevance backfill -- assign through
        `apply_classification`, so a field added here reaches both."""
        from awltux.llm.classify import apply_classification

        class Row:
            pass

        row = Row()
        assert apply_classification(row, normalise_classification({"metric": "revenue"}))
        assert row.metric == "revenue"
        assert row.event_type == "other"

    def test_an_absent_classification_is_not_applied(self):
        from awltux.llm.classify import apply_classification

        class Row:
            metric = "share_price"

        row = Row()
        assert not apply_classification(row, None)
        assert row.metric == "share_price", "a failed call must not blank a stored answer"


def _bare_item(*, tickers=None, sectors=None) -> NewsItem:
    """An unpersisted row, for the tests that only exercise the subject arithmetic."""
    return NewsItem(
        source="google_news",
        url="https://x.test/subjects",
        url_hash="subjects-bare",
        title="Acme and Beta both warn",
        tickers=list(tickers or []),
        sectors=list(sectors or []),
    )


class TestOneAppraisalPerSubject:
    """A story is one observation; the appraisal is about a *subject*.

    The row count barely moves -- measured 2026-10-07, 19,369 of 19,475 stories name a
    single ticker -- so the point is not volume. It is that ``is_held`` is a fact about
    the subject and not about the story, and with one column per story a piece about a
    held company and an unheld one carried whichever answer happened to be written
    first. This is where that is pinned down.
    """

    def test_instruments_come_before_sectors_and_each_group_is_ordered(self):
        """`primary_subject` takes the first, and the sentiment weighting applies the
        same rule in SQL, so this order is a contract rather than a preference."""
        item = _bare_item(tickers=["ZZZ_US_EQ", "AAA_US_EQ"], sectors=["Technology", "Energy"])

        assert news_analysis.subjects_of(item) == [
            news_analysis.Subject("instrument", "AAA_US_EQ"),
            news_analysis.Subject("instrument", "ZZZ_US_EQ"),
            news_analysis.Subject("sector", "Energy"),
            news_analysis.Subject("sector", "Technology"),
        ]

    def test_the_primary_subject_is_an_instrument_when_there_is_one(self):
        item = _bare_item(tickers=["BBB_US_EQ"])
        assert news_analysis.primary_subject(item) == news_analysis.Subject(
            "instrument", "BBB_US_EQ"
        )
        item.tickers = []
        item.sectors = ["Utilities"]
        assert news_analysis.primary_subject(item) == news_analysis.Subject("sector", "Utilities")

    def test_a_story_about_nothing_has_no_primary_subject(self):
        assert news_analysis.primary_subject(_bare_item()) is None

    def test_a_sector_is_held_when_anything_in_it_is(self):
        """The one input that differs between two appraisals of one story."""
        held_tickers = {"ACME_US_EQ"}
        held_sectors = {"Industrials"}

        assert news_analysis.subject_is_held(
            news_analysis.Subject("instrument", "ACME_US_EQ"), held_tickers, held_sectors
        )
        assert not news_analysis.subject_is_held(
            news_analysis.Subject("instrument", "OTHER_US_EQ"), held_tickers, held_sectors
        )
        assert news_analysis.subject_is_held(
            news_analysis.Subject("sector", "Industrials"), held_tickers, held_sectors
        )

    def test_a_run_writes_one_row_per_subject(self, session, universe, settings):
        """Two instruments and a sector on one story is three appraisals, and the
        subject each was built for is recorded rather than inferred later."""
        item = make_item(
            session, "Acme and Beta both warn", tickers=["ACME_US_EQ", "BETA_US_EQ"]
        )
        item.sectors = ["Industrials"]
        session.flush()

        report = news_analysis.analyse_universe(session, settings=settings)

        assert report["subjects"] == 3
        assert report["appraised"] == 3
        stored = session.execute(
            select(NewsAnalysis).where(NewsAnalysis.news_item_id == item.id)
        ).scalars().all()
        assert {(row.subject_type, row.subject_id) for row in stored} == {
            ("instrument", "ACME_US_EQ"),
            ("instrument", "BETA_US_EQ"),
            ("sector", "Industrials"),
        }

    def test_two_subjects_of_one_story_can_be_appraised_differently(
        self, session, universe, settings
    ):
        """The whole point, and the only thing that makes the split more than
        bookkeeping: whether the subject is held decides whether the model is asked to
        read the piece, so the held subject's row carries the model's answer and the
        unheld one's does not."""
        calls: list[dict] = []

        def counting(**_kwargs):
            calls.append(_kwargs)
            # `engine` is how a row records that the paid half ran, so the fake has to
            # set it -- without it every row reads "deterministic" and the assertion
            # below cannot fail.
            return {"claims": [], "technique_counts": {}, "engine": "fake:model"}

        # "moderate", not the default "material": a material story is read deeply
        # whatever the subject, which would make the two rows agree and the test prove
        # nothing. Held-ness is the *only* thing deciding here, which is the point.
        item = make_item(
            session,
            "Acme and Beta both warn",
            tickers=["ACME_US_EQ", "BETA_US_EQ"],
            materiality="moderate",
        )
        universe.is_held = True
        session.flush()

        news_analysis.analyse_universe(session, settings=settings, analyser=counting)

        stored = {
            (row.subject_type, row.subject_id): row
            for row in session.execute(
                select(NewsAnalysis).where(NewsAnalysis.news_item_id == item.id)
            ).scalars().all()
        }
        held = stored[("instrument", "ACME_US_EQ")]
        unheld = stored[("instrument", "BETA_US_EQ")]
        assert held.engine == "fake:model", "the held subject got the model's reading"
        assert unheld.engine == "deterministic", "the unheld one did not need it"
        assert len(calls) == 1, "one model call, for the one subject that warranted it"

    def test_re_appraising_updates_in_place_per_subject(self, session, universe, settings):
        """Re-running must not accumulate a second row for the same subject -- and must
        not touch the *other* subject's row, which is what a key on the story alone
        would have done."""
        item = make_item(session, "Acme warns", tickers=["ACME_US_EQ", "BETA_US_EQ"])
        news_analysis.analyse_universe(session, settings=settings)
        first = session.execute(
            select(NewsAnalysis).where(NewsAnalysis.news_item_id == item.id)
        ).scalars().all()
        assert len(first) == 2

        # Age them past the refresh window so the second run appraises rather than skips.
        for row in first:
            row.analysed_at = utcnow() - dt.timedelta(days=30)
        session.flush()

        news_analysis.analyse_universe(session, settings=settings)
        second = session.execute(
            select(NewsAnalysis).where(NewsAnalysis.news_item_id == item.id)
        ).scalars().all()
        assert len(second) == 2, "one row per subject, not one more per run"

    def test_the_scoped_lookup_returns_the_subject_asked_for(self, session, universe, settings):
        """An instrument page must show *its* appraisal, not the story's first."""
        from awltux.db.news import appraisals_for

        item = make_item(session, "Acme and Beta both warn", tickers=["ACME_US_EQ", "BETA_US_EQ"])
        news_analysis.analyse_universe(session, settings=settings)

        unscoped = appraisals_for(session, [item])
        scoped = appraisals_for(session, [item], subject=("instrument", "BETA_US_EQ"))

        assert unscoped[item.id].subject_id == "ACME_US_EQ", "the primary by default"
        assert scoped[item.id].subject_id == "BETA_US_EQ"

    def test_the_scoped_lookup_is_empty_rather_than_wrong_for_an_unappraised_subject(
        self, session, universe, settings
    ):
        """A sector page whose stories were only appraised per instrument shows no
        appraisal, which is true. Showing the instrument's would be a different
        subject's verdict under the sector's heading."""
        from awltux.db.news import appraisals_for

        item = make_item(session, "Acme warns", tickers=["ACME_US_EQ"])
        news_analysis.analyse_universe(session, settings=settings)

        assert appraisals_for(session, [item], subject=("sector", "Industrials")) == {}
