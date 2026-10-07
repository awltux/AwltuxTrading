"""Grouping stories that cover the same event, by meaning rather than wording.

A profit warning reaches this system five or six times from different outlets,
rewritten each time. Word-overlap comparison — which is what the corroboration
layer already does — collapses syndication and misses that case entirely: the same
event in different words reads as different stories.

The tests are mostly about the two ways this can be wrong rather than about
arithmetic. Joining two different events tells a reader one thing happened when
two did; that is a lie, and it is why the threshold is high and why every cluster
carries its members. Failing to join is a nuisance. The asymmetry decides the
design, so it is what is tested.
"""

from __future__ import annotations

from awltux.analysis.embeddings import (
    IDENTITY_FIELDS,
    Event,
    Identity,
    cluster,
    embed_text,
    group_events,
    identity_of,
    text_fingerprint,
)


def _vector(*values: float):
    import numpy as np

    return np.asarray(values, dtype=np.float32)


def _unit(np, *values):
    """A unit vector, so cosine similarity is just the dot product."""
    array = np.asarray(values, dtype=np.float32)
    return array / np.linalg.norm(array)


def _items(session, titles: list[str], *, ticker: str | None = None, fields=None):
    """Real rows, because vectors are stored against `news_item.id` by foreign key.

    ``fields`` is one dict of extra columns per title, for the tests that need the
    rows to *differ* in the keys the grouping compares.
    """
    from awltux.db import NewsItem, utcnow

    overrides = fields or [{} for _ in titles]
    rows = []
    for index, title in enumerate(titles):
        row = NewsItem(
            source="google_news",
            url=f"https://news.test/{index}",
            url_hash=f"hash-{index}-{title[:40]}",
            title=title,
            published_at=utcnow(),
            tickers=[ticker] if ticker else [],
            sectors=[],
            created_at=utcnow(),
            **overrides[index],
        )
        session.add(row)
        rows.append(row)
    session.commit()
    return rows


def _store(session, rows, settings, vectors):
    """Vectors under the model the *code* will look them up by.

    Not a name of the test's choosing: `queries.instrument_detail` groups without
    passing settings, so `embeddings.get_settings()` resolves the application's own
    configuration and a made-up model name would store vectors nothing ever finds --
    which is exactly the failure this test would then be reporting as a feature bug.
    """
    from awltux.analysis.embeddings import store_vectors

    store_vectors(
        [row.id for row in rows],
        [embed_text(row) for row in rows],
        vectors,
        settings.news.embeddings.model,
    )
    # Committed, not flushed. `session_scope` is re-entrant per thread, so
    # `store_vectors` joined this test's transaction and only the outermost scope
    # commits -- and a page is served on its own thread in another session, so a
    # flushed-but-uncommitted vector is invisible to it. The same trap `AGENTS.md`
    # records for a seeded page test.
    session.commit()


class TestClustering:
    def test_stories_with_the_same_meaning_join(self):
        np = __import__("numpy")
        # Two near-identical directions: the same event, different words.
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.08)
        events = cluster([1, 2], {1: a, 2: b}, threshold=0.86)
        assert len(events) == 1
        assert events[0].members == [1, 2]

    def test_different_events_stay_apart(self):
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 0.0, 1.0)
        events = cluster([1, 2], {1: a, 2: b}, threshold=0.86)
        assert [event.members for event in events] == [[1], [2]]

    def test_the_threshold_is_what_keeps_them_apart(self):
        """The knob has to actually do something, or the asymmetry argument is
        decoration. ``(1, 0.8)`` sits about 39 degrees off ``(1, 0)``, which is
        0.78 cosine -- inside a loose threshold and well outside a tight one."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.8)
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.86)) == 2
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.70)) == 1

    def test_order_is_preserved_so_the_lead_is_the_best_story(self):
        np = __import__("numpy")
        a, b, c = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.05), _unit(np, 1.0, 0.1)
        # Caller passes best-first; the lead must stay first.
        events = cluster([7, 8, 9], {7: a, 8: b, 9: c}, threshold=0.86)
        assert events[0].members[0] == 7

    def test_a_story_with_no_vector_stands_alone(self):
        """No vector is no basis for comparison. Merging on a guess would be the
        wrong kind of error."""
        np = __import__("numpy")
        a = _unit(np, 1.0, 0.0)
        events = cluster([1, 2], {1: a}, threshold=0.86)
        assert [event.members for event in events] == [[1], [2]]

    def test_membership_is_one_comparison_from_the_lead(self):
        """Anchoring on the representative rather than the cluster mean: a mean
        drifts as members are added, and can absorb a story that resembles the
        average and none of the members."""
        np = __import__("numpy")
        anchor = _unit(np, 1.0, 0.0)
        far = _unit(np, 0.5, 1.0)  # closer to the mean of the two than to either
        events = cluster([1, 2, 3], {1: anchor, 2: _unit(np, 1.0, 0.05), 3: far}, threshold=0.86)
        assert events[0].members == [1, 2]
        assert [3] in [event.members for event in events]

    def test_the_weakest_link_in_a_cluster_is_reported(self):
        """A group held together by one marginal match should say so."""
        np = __import__("numpy")
        events = cluster(
            [1, 2, 3],
            {1: _unit(np, 1.0, 0.0), 2: _unit(np, 1.0, 0.2), 3: _unit(np, 1.0, 0.35)},
            threshold=0.86,
        )
        assert events[0].similarity is not None
        assert 0.86 <= events[0].similarity <= 1.0

    def test_a_single_story_reports_no_similarity(self):
        np = __import__("numpy")
        events = cluster([1], {1: _unit(np, 1.0, 0.0)}, threshold=0.86)
        assert events[0].similarity is None

    def test_a_zero_vector_does_not_divide_by_zero(self):
        np = __import__("numpy")
        events = cluster([1, 2], {1: _vector(0.0, 0.0), 2: _unit(np, 1.0, 0.0)}, threshold=0.5)
        assert [event.members for event in events] == [[1], [2]]

    def test_no_stories_is_no_events(self):
        assert cluster([], {}, threshold=0.86) == []

    def test_the_event_serialises_for_the_api(self):
        payload = Event(members=[1, 2], similarity=0.91).as_dict()
        assert payload == {"members": [1, 2], "size": 2, "similarity": 0.91}


class TestTheIdentityVeto:
    """Similarity says two stories resemble each other; it cannot say they are one event.

    Measured 2026-10-07 over the 1,000 embedded stories at the threshold then in force:
    of the 672 joins the cosine made, **439 (65%) contradicted their own group on the
    stored event type or direction** -- "Canadian National Railway stock falls Wednesday"
    grouped with the identical headline saying "rises", and one Claritev margin story
    grouped with an insider share sale, a buyback launch and a DOJ probe. Those pairs
    score high precisely because they are the same company on the same day in the same
    register, which is the one thing a cosine cannot see past.

    These tests assert the veto, and the veto's own limit: it may only refuse a join on
    a field the story actually states.
    """

    def test_the_measured_pair_is_split_by_direction(self):
        """The pair that broke the threshold: two near-identical headlines for CN Rail,
        one saying the shares fell and one saying they rose. Their vectors are close
        enough to clear any threshold a duplicate-detector would ship."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.02)
        identities = {
            1: Identity(event_type="other", direction="negative", metric="share_price"),
            2: Identity(event_type="other", direction="positive", metric="share_price"),
        }
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.70)) == 1, "the vector joins them"
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.70, identities=identities)) == 2

    def test_a_different_event_type_is_refused(self):
        """A share moving and a broker changing its target on it: one company, one day,
        two events the classifier already labelled differently."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.01)
        identities = {
            1: Identity(event_type="analyst", direction="positive", metric="price_target"),
            2: Identity(event_type="macro", direction="positive", metric="share_price"),
        }
        events = cluster([1, 2], {1: a, 2: b}, threshold=0.70, identities=identities)
        assert [event.members for event in events] == [[1], [2]]

    def test_a_story_the_classifier_agrees_with_still_joins(self):
        """The veto must not be a blanket refusal, or it is just a tighter threshold
        wearing a different name."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.02)
        identities = {
            1: Identity(event_type="m_and_a", direction="positive", metric="share_price"),
            2: Identity(event_type="m_and_a", direction="positive", metric="share_price"),
        }
        events = cluster([1, 2], {1: a, 2: b}, threshold=0.70, identities=identities)
        assert [event.members for event in events] == [[1, 2]]

    def test_an_unstated_key_abstains_rather_than_disagreeing(self):
        """The rows classified before 0011 carry NULL, and the backfill is rationed.
        Reading "no metric recorded" as "a different metric" would veto every join
        until it caught up -- a silent regression caused by having no data, which is
        the worst kind."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.02)
        half = {1: Identity(direction="positive"), 2: Identity()}
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.70, identities=half)) == 1

    def test_no_identities_leaves_the_grouping_as_it_was(self):
        """`cluster` is called directly by the API layer and by these tests; the
        argument has to be optional or every existing caller acquires the rule."""
        np = __import__("numpy")
        a, b = _unit(np, 1.0, 0.0), _unit(np, 1.0, 0.02)
        assert len(cluster([1, 2], {1: a, 2: b}, threshold=0.70)) == 1

    def test_the_conflicting_fields_are_named(self):
        left = Identity(event_type="earnings", direction="positive", metric="revenue")
        right = Identity(event_type="earnings", direction="negative", metric="share_price")
        assert left.conflicts(right) == ("direction", "metric")
        assert not left.agrees(right)
        assert left.agrees(Identity(event_type="earnings"))

    def test_identity_is_read_off_a_row(self):
        class Row:
            event_type = "guidance"
            direction = "negative"
            metric = "earnings"

        assert identity_of(Row()) == Identity("guidance", "negative", "earnings")
        assert identity_of(object()) == Identity()

    def test_the_compared_fields_are_the_fields_the_identity_holds(self):
        """`IDENTITY_FIELDS` is what makes `conflicts` complete. A field added to the
        dataclass and not to it would be stored, shown on the page, and silently
        ignored by the only rule that reads it."""
        import dataclasses

        assert set(IDENTITY_FIELDS) == {field.name for field in dataclasses.fields(Identity)}

    def test_the_veto_reaches_the_page(self, session, settings):
        """The instrument page groups through `group_events`, so a rule wired only into
        `cluster` would be a rule the reader never sees."""
        rows = _items(
            session,
            [
                "Canadian National Railway stock falls Wednesday, underperforms",
                "Canadian National Railway stock rises Wednesday, outperforms",
            ],
            ticker="CNI_US_EQ",
            fields=[
                {"event_type": "other", "direction": "negative", "metric": "share_price"},
                {"event_type": "other", "direction": "positive", "metric": "share_price"},
            ],
        )
        _store(session, rows, settings, [[1.0, 0.0, 0.0], [1.0, 0.01, 0.0]])

        groups, note = group_events(list(rows), settings=settings)

        assert note is None
        assert [group.size for group in groups] == [1, 1], (
            "opposite directions are two events however alike the headlines read"
        )


class TestTheEmbeddedText:
    def test_the_headline_leads(self):
        class Row:
            title = "Acme warns on profit"
            summary = "The company cut its full-year outlook."

        text = embed_text(Row())
        assert text.startswith("Acme warns on profit")
        assert "full-year outlook" in text

    def test_the_summary_is_included_because_it_carries_the_signal(self):
        """'Acme wins a contract' and 'Acme wins a contract worth 10m, shares up 4%'
        are the same event and very different stories. The headline alone cannot
        tell them apart."""
        class Bare:
            title = "Acme wins a contract"
            summary = None

        class Full:
            title = "Acme wins a contract"
            summary = "Worth 10m, sending the shares up 4%"

        assert embed_text(Bare()) != embed_text(Full())

    def test_a_missing_summary_still_produces_text(self):
        class Row:
            title = "Acme warns"
            summary = None

        assert embed_text(Row()) == "Acme warns"

    def test_the_fingerprint_is_stable_and_sensitive(self):
        assert text_fingerprint("a") == text_fingerprint("a")


class TestThePageFacingGrouping:
    """`group_events` speaks in rows, because a template has to render a headline.

    The banner's JSON wants story ids; a news list wants the stories. Both must agree
    about what one event is, so the second is derived from the first rather than
    clustering again with its own rule.
    """

    def test_it_groups_rows_and_leads_with_the_first_member(self, session, settings):
        rows = _items(
            session, ["Acme warns on profit", "Acme cuts its outlook", "Acme wins a contract"]
        )
        _store(
            session, rows, settings, [[1.0, 0.0, 0.0], [0.99, 0.05, 0.0], [0.0, 1.0, 0.0]]
        )

        groups, note = group_events(list(rows), settings=settings)

        assert note is None
        assert [group.lead.id for group in groups] == [rows[0].id, rows[2].id]
        assert [other.id for other in groups[0].others] == [rows[1].id]
        assert groups[0].size == 2
        assert groups[1].others == ()

    def test_without_vectors_every_story_stands_alone_and_it_says_so(self, session, settings):
        """`no stored vectors` and `one entry per event` look identical on a page, so
        the note is the only thing that tells the reader which one they are seeing."""
        rows = _items(session, ["one", "two"])

        groups, note = group_events(list(rows), settings=settings)

        assert len(groups) == 2
        assert note == "no stored vectors for these stories yet"

    def test_grouping_reaches_the_instrument_page(self, client, session, settings):
        """The reader's own company page was where the duplicates were certain to show:
        a profit warning arrives five or six times and this list showed all of them."""
        from tests.helpers import make_instrument

        session.add(make_instrument("TEST_US_EQ", sec_cik="0000000001"))
        session.flush()
        rows = _items(
            session,
            ["Acme warns on profit", "Acme cuts its outlook", "Acme wins a contract"],
            ticker="TEST_US_EQ",
        )
        _store(
            session, rows, settings, [[1.0, 0.0, 0.0], [0.99, 0.05, 0.0], [0.0, 1.0, 0.0]]
        )

        body = client.get("/instrument/TEST_US_EQ").text

        assert "1 similar report" in body
        assert "Acme cuts its outlook" in body, "the member is shown, not hidden"
        assert "weakest match" in body, "a wrong join has to be visible"
        assert "of this event" not in body, (
            "measured on real stories the similarity cannot tell one event reported twice "
            "from one company on two days, so the page must not assert that it can"
        )
        assert text_fingerprint("a") != text_fingerprint("b")

    def test_the_keys_are_shown_beside_the_headline(self, client, session, settings):
        """The keys are the evidence for the grouping, so they have to be readable --
        otherwise a reader is asked to trust a rule they cannot see. `metric` especially:
        it is the field that separates a share moving from a broker changing its target
        on it, and no amount of similarity can show that."""
        from tests.helpers import make_instrument

        session.add(make_instrument("KEY_US_EQ", sec_cik="0000000002"))
        session.flush()
        keys = {
            "event_type": "earnings",
            "direction": "positive",
            "metric": "revenue",
            "period": "FY26",
            "magnitude": "3.1%",
        }
        rows = _items(
            session,
            ["Acme reports 3.1% FY26 sales growth", "Acme posts FY26 sales growth"],
            ticker="KEY_US_EQ",
            fields=[dict(keys), dict(keys)],
        )
        _store(session, rows, settings, [[1.0, 0.0, 0.0], [0.99, 0.05, 0.0]])

        body = client.get("/instrument/KEY_US_EQ").text

        for shown in ("earnings", "revenue", "positive", "FY26", "3.1%"):
            assert shown in body, f"{shown} is a key the grouping compared and must be visible"
