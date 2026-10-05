"""The pipeline that applies scepticism, and the weighting it produces.

The point of these tests is that the appraisal is not decorative. A story graded
weak must actually move the sentiment number less than a story graded strong --
otherwise the whole layer is a labelprinted on top of an unchanged model.
"""

from __future__ import annotations

import datetime as dt

import pytest

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


class TestAppraisal:
    def test_the_appraisal_records_source_framing_and_corroboration(self, session, universe, settings):
        item = make_item(session, "Acme warns on profit as demand weakens")
        row = news_analysis.appraise_item(
            item,
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
            item, settings=settings, analyser=fake_analyser
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
        row = news_analysis.appraise_item(item, settings=settings, analyser=exploding)
        assert row.credibility is not None
        assert row.engine == "deterministic"

    def test_an_event_type_routes_the_claim_to_its_register(self, session, universe, settings):
        item = make_item(session, "Acme reports results", event_type="earnings")
        row = news_analysis.appraise_item(item, settings=settings, analyser=fake_analyser)
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
        row = news_analysis.appraise_item(item, settings=settings, analyser=rumour_analyser)
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
