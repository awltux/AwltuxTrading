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
    Event,
    cluster,
    embed_text,
    text_fingerprint,
)


def _vector(*values: float):
    import numpy as np

    return np.asarray(values, dtype=np.float32)


def _unit(np, *values):
    """A unit vector, so cosine similarity is just the dot product."""
    array = np.asarray(values, dtype=np.float32)
    return array / np.linalg.norm(array)


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
        assert text_fingerprint("a") != text_fingerprint("b")
