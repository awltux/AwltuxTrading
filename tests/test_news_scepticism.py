"""The scepticism layer: sources, rhetoric, corroboration, claim grading.

These tests are the argument for the feature. They pin the behaviour that
distinguishes sceptical analysis from a sentiment score with extra adjectives:

* a shocking story from an unrated publisher carried by one domain cannot be
  treated as strong evidence, no matter how confident it reads;
* twelve domains carrying one wire story is one source, not twelve;
* a company's good news about itself is discounted far harder than its bad news,
  because self-interest cuts differently in each direction;
* a story that asserts nothing checkable is recorded as such instead of being
  quietly averaged in with everything else.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.analysis import corroboration as corr
from awltux.analysis import news_scepticism as scepticism
from awltux.analysis import rhetoric, sources
from awltux.analysis.news_scepticism import Claim
from awltux.db import NewsItem, utcnow

# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #


class TestDomainResolution:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("https://www.reuters.com/markets/x?utm=1", "reuters.com"),
            ("http://markets.ft.com/content/abc", "markets.ft.com"),
            ("https://finance.yahoo.com/quote/AAPL", "finance.yahoo.com"),
            ("https://www.gov.uk/government/news/thing", "gov.uk"),
            ("https://news.sky.com/story/x", "news.sky.com"),
            ("https://example.co.uk/a/b", "example.co.uk"),
            (None, None),
            ("", None),
            ("not a url", None),
        ],
    )
    def test_domain_extraction(self, url, expected):
        assert sources.domain_of(url) == expected

    def test_domain_extraction_strips_port_and_credentials(self):
        assert sources.domain_of("http://user:pw@reuters.com:8443/x") == "reuters.com"

    def test_a_subdomain_resolves_to_the_organisation_that_owns_it(self):
        """Display keeps the precise host; publisher resolution walks up to the owner."""
        assert sources.lookup("https://markets.ft.com/content/x").domain == "ft.com"
        assert sources.lookup("https://uk.news.yahoo.com/x").domain == "yahoo.com"

    def test_a_subdomain_the_registry_knows_exactly_is_not_collapsed(self):
        publisher = sources.lookup("https://finance.yahoo.com/x")
        assert publisher.domain == "finance.yahoo.com"
        assert publisher.kind == "aggregator"


class TestRegistryLookup:
    def test_known_publisher_is_found_through_a_subdomain(self):
        publisher = sources.lookup("https://markets.ft.com/content/x")
        assert publisher.domain == "ft.com"
        assert publisher.kind == "quality"

    def test_unlisted_publisher_is_unrated_not_disreputable(self):
        publisher = sources.lookup("https://some-unknown-blog.example/post")
        assert publisher.assessed is False
        assert publisher.kind == "unknown"
        assert "not the same as a bad assessment" in publisher.basis

    def test_an_unlisted_domain_is_not_silently_assumed_reputable(self):
        """The whole point: no entry must not mean a free pass."""
        assert sources.lookup("https://some-unknown-blog.example").label == "unrated"
        assert sources.lookup("https://some-unknown-blog.example").reliability < 0.6

    def test_press_release_distributors_are_recognised_by_platform_hint(self):
        publisher = sources.lookup("https://www.globenewswire.com/news-release/123")
        assert publisher.kind == "press_release"

    def test_a_government_register_is_a_primary_record(self):
        publisher = sources.lookup("https://www.sec.gov/edgar/search")
        assert publisher.is_primary
        assert publisher.label == "high"

    def test_every_registry_entry_has_a_stated_basis(self):
        """A judgement with no basis is indistinguishable from a prejudice."""
        for domain, publisher in sources.REGISTRY.items():
            assert publisher.basis, f"{domain} has no stated basis"
            assert len(publisher.basis) > 20, f"{domain}'s basis is too thin to review"

    def test_bias_tags_are_drawn_from_the_closed_vocabulary(self):
        for domain, publisher in sources.REGISTRY.items():
            assert set(publisher.biases) <= sources.BIAS_TAGS, domain

    def test_an_invented_bias_tag_is_rejected_at_definition_time(self):
        with pytest.raises(ValueError):
            sources._p("x.com", "X", "quality", "basis", biases=("definitely_evil",))


class TestSelfInterestAsymmetry:
    """Self-interest does not push credibility in one direction."""

    def test_good_news_from_an_interested_party_is_discounted_hard(self):
        company = sources.lookup("https://www.globenewswire.com/x")
        assert sources.source_weight(company, direction="positive") < 0.25

    def test_bad_news_from_an_interested_party_keeps_most_of_its_weight(self):
        company = sources.lookup("https://www.globenewswire.com/x")
        positive = sources.source_weight(company, direction="positive")
        negative = sources.source_weight(company, direction="negative")
        assert negative > positive * 2

    def test_an_independent_wire_is_unaffected_by_direction(self):
        wire = sources.lookup("https://www.reuters.com/x")
        assert sources.source_weight(wire, direction="positive") == pytest.approx(
            sources.source_weight(wire, direction="negative")
        )

    def test_no_source_ever_exceeds_full_weight(self):
        for publisher in sources.REGISTRY.values():
            for direction in ("positive", "negative", None):
                assert 0.0 <= sources.source_weight(publisher, direction=direction) <= 1.0


# --------------------------------------------------------------------------- #
# rhetoric
# --------------------------------------------------------------------------- #


class TestRhetoric:
    def test_plain_factual_copy_scores_low(self):
        report = rhetoric.analyse_text(
            "The company reported revenue of 4.2bn for the year, up from 3.9bn, "
            "and said it expects margins to be unchanged.",
            headline="Company reports annual results",
        )
        assert report.score < 0.25
        assert not report.is_suspicious

    def test_fear_language_is_detected_with_its_evidence(self):
        report = rhetoric.analyse_text(
            "Investors are fleeing as the stock faces a bloodbath that could wipe out "
            "retirement savings, analysts say."
        )
        assert "appeal_to_fear" in report.techniques
        finding = next(f for f in report.findings if f.technique == "appeal_to_fear")
        assert finding.evidence
        assert report.score > 0.4

    def test_unnamed_authority_is_flagged(self):
        report = rhetoric.analyse_text("Sources said the deal is close, people familiar with the matter said.")
        assert "anonymous_sourcing" in report.techniques

    def test_an_alarming_hedged_claim_is_called_out(self):
        """The classic construction: the headline asserts what the wording only speculates."""
        report = rhetoric.analyse_text(
            "Shares may be wiped out in a catastrophic meltdown, analysts warn.",
            headline="Shares may be wiped out",
        )
        assert report.hedged
        assert any("hedged claim" in note for note in report.notes)

    def test_a_percentage_with_no_base_is_noted(self):
        report = rhetoric.analyse_text("Revenue fell 40%, a devastating collapse.")
        assert any("no base" in note for note in report.notes)

    def test_a_headline_more_extreme_than_its_text_is_noted(self):
        report = rhetoric.analyse_text(
            "The company said trading was in line with expectations for the period.",
            headline="SHOCKING meltdown wipes out investors",
        )
        assert any("Headline is more extreme" in note for note in report.notes)

    def test_technique_names_are_validated_against_the_taxonomy(self):
        assert rhetoric.identify_technique("Appeal to Fear") == "appeal_to_fear"
        assert rhetoric.identify_technique("appeal-to-fear") == "appeal_to_fear"
        assert rhetoric.identify_technique("vibes_based_persuasion") is None
        assert rhetoric.identify_technique(None) is None

    def test_a_fearful_story_about_a_real_event_is_still_flagged(self):
        """Presentation is measured, not truth: shouting about a real bank run is shouting."""
        report = rhetoric.analyse_text("Bank collapse sparks panic and carnage across markets.")
        assert report.is_suspicious

    def test_empty_input_is_handled(self):
        report = rhetoric.analyse_text("")
        assert report.score == 0.0
        assert report.notes == ["no text to analyse"]

    def test_the_report_decomposes_into_readable_reasons(self):
        report = rhetoric.analyse_text("SHOCKING collapse wipes out investors")
        payload = report.as_dict()
        assert payload["score"] >= 0
        for finding in payload["findings"]:
            assert finding["label"]
            assert finding["technique"] in rhetoric.TECHNIQUE_LABELS


# --------------------------------------------------------------------------- #
# corroboration
# --------------------------------------------------------------------------- #


def item(title: str, url: str, *, hours_ago: float = 1.0, source: str = "test") -> NewsItem:
    return NewsItem(
        source=source,
        url=url,
        url_hash=url[-40:],
        title=title,
        published_at=utcnow() - dt.timedelta(hours=hours_ago),
    )


class TestCorroboration:
    def test_one_wire_story_across_many_domains_is_one_source(self):
        """The most common way "multiple outlets" is overstated."""
        headline = "Acme warns on full-year profit amid weak demand"
        rows = [
            item(headline, "https://www.reuters.com/business/acme-warns"),
            item(headline, "https://finance.yahoo.com/news/acme-warns"),
            item(headline, "https://www.msn.com/en-us/money/acme-warns"),
            item(headline, "https://www.localpaper.co.uk/acme-warns"),
            item(headline, "https://www.investing.com/news/acme-warns"),
        ]
        result = corr.assess(headline, rows)

        assert result.carrier_count == 5
        assert result.independent_count == 1
        assert result.syndicated is True
        assert result.is_single_source
        assert any("republication is not corroboration" in note for note in result.notes)

    def test_genuinely_separate_reporting_counts_as_separate_sources(self):
        rows = [
            item("Acme warns on profit as demand weakens", "https://www.reuters.com/x"),
            item("Acme cuts guidance after poor quarter", "https://www.ft.com/y"),
            item("Acme shares fall on profit warning", "https://www.bbc.co.uk/z"),
        ]
        result = corr.assess("Acme warns on profit as demand weakens", rows)
        assert result.independent_count == 3
        assert result.syndicated is False

    def test_a_rewritten_copy_attributing_reuters_collapses_to_reuters(self):
        rows = [
            item("Acme profit warning hits shares", "https://www.smallpaper.example/a"),
            item("Acme profit warning hits shares", "https://www.otherpaper.example/b"),
        ]
        result = corr.assess("Acme profit warning hits shares", rows)
        # No wire credited in the text, and neither is an aggregator, so the
        # near-identical pair still collapses to a single origin by similarity.
        assert result.independent_count == 1

    def test_wire_attribution_in_the_text_is_credited(self):
        rows = [
            item("Acme warns", "https://www.paper.example/a"),
            item("Acme warns, Reuters reports", "https://www.other.example/b"),
        ]
        result = corr.assess("Acme warns", rows)
        assert result.attributed_origin == "reuters.com"

    def test_only_a_press_release_is_called_out_as_a_statement_not_a_report(self):
        headline = "Acme announces breakthrough contract"
        rows = [item(headline, "https://www.globenewswire.com/news-release/1")]
        result = corr.assess(headline, rows)
        assert any("statement, not an independent report" in note for note in result.notes)

    def test_the_best_publisher_ignores_aggregators(self):
        headline = "Acme wins contract"
        rows = [
            item(headline, "https://finance.yahoo.com/news/acme"),
            item(headline, "https://www.reuters.com/acme"),
        ]
        result = corr.assess(headline, rows)
        assert result.best_publisher is not None
        assert result.best_publisher.domain == "reuters.com"

    def test_items_outside_the_window_are_excluded(self):
        headline = "Acme warns"
        rows = [
            item(headline, "https://www.reuters.com/a", hours_ago=1),
            item(headline, "https://www.ft.com/b", hours_ago=200),
        ]
        result = corr.assess(headline, rows, window_hours=72)
        assert result.carrier_count == 1

    def test_no_coverage_is_reported_as_such_rather_than_as_a_pass(self):
        result = corr.assess("Acme warns", [])
        assert result.carrier_count == 0
        assert result.is_single_source
        assert any("no surrounding coverage" in note for note in result.notes)

    def test_the_factor_saturates_so_republication_adds_nothing(self):
        one = corr.Corroboration(origins=["a"])
        two = corr.Corroboration(origins=["a", "b"])
        five = corr.Corroboration(origins=["a", "b", "c", "d", "e"])
        assert corr.corroboration_factor(one) < corr.corroboration_factor(two)
        assert corr.corroboration_factor(five) >= corr.corroboration_factor(two)
        assert corr.corroboration_factor(five) <= 1.0

    def test_the_method_is_stated_so_a_reader_can_argue_with_it(self):
        result = corr.assess("x", [item("x", "https://www.reuters.com/a")])
        assert "heuristic" in result.as_dict()["method"]

    def test_similarity_is_symmetric_and_bounded(self):
        a = "Acme warns on profit as demand weakens"
        b = "Acme cuts guidance after poor quarter"
        assert corr.similarity(a, b) == corr.similarity(b, a)
        assert 0.0 <= corr.similarity(a, b) <= 1.0
        assert corr.similarity("", a) == 0.0


# --------------------------------------------------------------------------- #
# claim grading
# --------------------------------------------------------------------------- #


def publisher_for(url: str) -> sources.Publisher:
    return sources.lookup(url)


class TestClaimModel:
    def test_an_uncheckable_attribution_halves_the_support(self):
        checkable = Claim("x", "reported_fact", "filing")
        uncheckable = Claim("x", "reported_fact", "unnamed_source")
        assert checkable.checkable
        assert not uncheckable.checkable
        assert uncheckable.support < checkable.support

    def test_a_filed_record_is_worth_more_than_a_prediction(self):
        assert (
            Claim("x", "filed_record", "filing").support
            > Claim("x", "prediction", "journalist_inference").support
        )

    def test_primary_registers_are_named_for_the_claim_that_needs_them(self):
        register, where = scepticism.resolve_primary_source("financial_result")
        assert "filing" in register.lower()
        assert where

    def test_speculation_has_no_primary_source_and_says_so(self):
        register, _ = scepticism.resolve_primary_source("rumour_or_speculation")
        assert register == "None exists"

    def test_an_unknown_category_resolves_to_nothing(self):
        assert scepticism.resolve_primary_source("nonsense") == (None, None)


class TestGrading:
    def test_a_regulator_statement_from_the_regulator_is_strong(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.sec.gov/edgar/x"),
            claims=[Claim("x", "filed_record", "filing")],
            materiality="material",
        )
        assert assessment.grade in ("strong", "moderate")
        assert assessment.credibility > 0.5

    def test_a_shocking_single_source_from_nowhere_is_capped(self):
        """The exact shape of a story that spreads because it is shocking."""
        assessment = scepticism.grade(
            publisher=publisher_for("https://unknown-blog.example/post"),
            rhetoric=rhetoric.analyse_text(
                "SHOCKING: investors flee as bloodbath wipes out savings, sources say"
            ),
            corroboration=corr.Corroboration(
                carriers=[corr.Carrier("unknown-blog.example", "SHOCKING", None, sources.lookup("https://unknown-blog.example"))],
                origins=["unknown-blog.example"],
            ),
            claims=[Claim("x", "rumour", "unnamed_source")],
            direction="negative",
            materiality="critical",
        )
        assert assessment.credibility <= scepticism.UNCONFIRMED_CEILING
        assert "capped_unconfirmed" in assessment.flags
        assert assessment.grade in ("unsupported", "weak")

    def test_republication_does_not_raise_credibility(self):
        headline = "Acme warns on profit"
        carriers = [
            corr.Carrier("finance.yahoo.com", headline, None, sources.lookup("https://finance.yahoo.com")),
            corr.Carrier("msn.com", headline, None, sources.lookup("https://www.msn.com")),
        ]
        syndicated = corr.Corroboration(carriers=carriers, origins=["reuters.com"], syndicated=True)
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            corroboration=syndicated,
        )
        assert "syndicated" in assessment.flags
        assert any("illusion" in warning for warning in assessment.warnings)

    def test_a_material_single_source_story_is_marked_unconfirmed(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            corroboration=corr.Corroboration(origins=["reuters.com"]),
            materiality="material",
        )
        assert "unconfirmed" in assessment.flags
        assert not assessment.is_confirmed

    def test_an_allegation_is_recorded_as_unverifiable(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            claims=[Claim("x", "allegation", "unnamed_source")],
        )
        assert "unverifiable_claims" in assessment.flags

    def test_nothing_checkable_is_stated_plainly(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            claims=[
                Claim("x", "inference", "journalist_inference"),
                Claim("y", "prediction", "journalist_inference"),
            ],
        )
        assert "nothing_checkable" in assessment.flags
        assert any("can be checked against a primary source" in w for w in assessment.warnings)

    def test_a_prospectus_style_claim_with_no_primary_source_is_capped(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            source_category="rumour_or_speculation",
        )
        assert "no_primary_source" in assessment.flags
        assert assessment.credibility <= 0.3
        assert any("No primary source exists" in caveat for caveat in assessment.caveats)

    def test_a_self_serving_positive_claim_is_flagged(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.globenewswire.com/x"),
            direction="positive",
        )
        assert "self_serving_positive" in assessment.flags
        assert any("good news" in warning for warning in assessment.warnings)

    def test_an_against_interest_admission_is_noted_as_more_credible(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.globenewswire.com/x"),
            direction="negative",
        )
        assert "against_interest" in assessment.flags
        assert any("against its own interest" in caveat for caveat in assessment.caveats)

    def test_severe_rhetoric_caps_credibility_however_good_the_source(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            rhetoric=rhetoric.analyse_text(
                "SHOCKING bloodbath wipeout: act now before it's too late, experts say, "
                "everyone is fleeing and savings are obliterated in a catastrophic meltdown"
            ),
            corroboration=corr.Corroboration(origins=["reuters.com", "ft.com", "bbc.co.uk"]),
        )
        assert "capped_rhetoric" in assessment.flags
        assert assessment.credibility <= scepticism.RHETORIC_HARD_CEILING

    def test_credibility_is_always_a_proportion(self):
        for url in ("https://www.sec.gov/x", "https://unknown.example/y", None):
            assessment = scepticism.grade(publisher=sources.lookup(url))
            assert 0.0 <= assessment.credibility <= 1.0

    def test_the_assessment_explains_itself(self):
        assessment = scepticism.grade(
            publisher=publisher_for("https://www.reuters.com/x"),
            rhetoric=rhetoric.analyse_text("Bloodbath wipes out investors"),
            corroboration=corr.Corroboration(origins=["reuters.com"]),
        )
        payload = assessment.as_dict()
        # A numeric score with no stated reasons is indistinguishable from a vibe,
        # so every route to a low number must leave a sentence behind.
        assert payload["warnings"], "a discounted article must say why"
        assert payload["rhetoric_score"] == assessment.rhetoric_score
        assert payload["source_kind"] == "wire"
        assert set(payload) >= {"credibility", "grade", "warnings", "caveats", "flags"}


class TestSentimentShrinking:
    def test_a_weak_article_is_damped_not_inverted(self):
        weak = scepticism.NewsAssessment(
            credibility=0.2, grade="weak", source_reliability=0.5, source_independence=0.2,
            source_kind="unknown", source_weight=0.3, corroboration_factor=0.35,
            rhetoric_score=0.6, claim_support=0.2,
        )
        assert scepticism.apply_to_sentiment(-1.0, weak) == pytest.approx(-0.2)
        assert scepticism.apply_to_sentiment(1.0, weak) == pytest.approx(0.2)

    def test_a_strong_article_is_barely_touched(self):
        strong = scepticism.NewsAssessment(
            credibility=0.95, grade="strong", source_reliability=0.97, source_independence=0.9,
            source_kind="primary_record", source_weight=0.9, corroboration_factor=1.0,
            rhetoric_score=0.0, claim_support=1.0,
        )
        assert scepticism.apply_to_sentiment(-1.0, strong) == pytest.approx(-0.95)

    def test_no_score_stays_no_score(self):
        assert scepticism.apply_to_sentiment(None, None) is None
