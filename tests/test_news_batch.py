"""Answering many headlines in one call, and refusing to when the answer cannot be aligned.

The saving is not the property worth testing. The property is that **a verdict never
lands on the wrong headline**: `normalise_classification` drops keys it does not
recognise, so a batch that is off by one parses perfectly and files every judgement one
story out. Nothing downstream raises. These tests exist for that failure, and the one
that matters most is `test_a_short_batch_is_re_asked_one_at_a_time`.
"""

from __future__ import annotations

import pytest

from awltux.db import NewsItem
from awltux.ingest.news import NewsIngestReport, persist_items
from awltux.llm.classify import _aligned_verdicts
from awltux.providers.news_rss import RawNewsItem
from tests.helpers import make_instrument


class _Completion:
    """Just the fields `_aligned_verdicts` reads off a completion."""

    model = "test-model"
    llm_call_id = 7


def _classification(**overrides):
    base = {
        "materiality": "moderate",
        "direction": "positive",
        "relevance": 0.6,
        "reasoning": "a contract win",
        "is_about_this_company": True,
        "event_type": "product",
        "metric": "none",
    }
    base.update(overrides)
    return base


class TestAlignment:
    """`_aligned_verdicts` is the guard, so it is tested directly."""

    def test_a_well_formed_batch_is_matched_by_index(self):
        payload = [
            {"index": 0, "classification": _classification(materiality="critical")},
            {"index": 1, "classification": _classification(materiality="none")},
        ]
        verdicts = _aligned_verdicts(payload, 2, _Completion())
        assert verdicts is not None
        assert [v["materiality"] for v in verdicts] == ["critical", "none"]

    def test_a_short_batch_is_refused(self):
        payload = [{"index": 0, "classification": _classification()}]
        assert _aligned_verdicts(payload, 2, _Completion()) is None

    def test_a_long_batch_is_refused(self):
        payload = [
            {"index": 0, "classification": _classification()},
            {"index": 1, "classification": _classification()},
            {"index": 2, "classification": _classification()},
        ]
        assert _aligned_verdicts(payload, 2, _Completion()) is None

    def test_a_repeated_index_is_refused(self):
        """Two answers claiming one headline means one headline has none."""
        payload = [
            {"index": 0, "classification": _classification()},
            {"index": 0, "classification": _classification()},
        ]
        assert _aligned_verdicts(payload, 2, _Completion()) is None

    def test_an_out_of_range_index_is_refused(self):
        payload = [
            {"index": 0, "classification": _classification()},
            {"index": 9, "classification": _classification()},
        ]
        assert _aligned_verdicts(payload, 2, _Completion()) is None

    def test_a_missing_index_is_refused(self):
        payload = [_classification(), _classification()]
        assert _aligned_verdicts(payload, 2, _Completion()) is None

    def test_a_bare_object_is_refused(self):
        assert _aligned_verdicts({"classification": _classification()}, 2, _Completion()) is None

    def test_a_wrapped_list_is_accepted(self):
        payload = {
            "classifications": [
                {"index": 0, "classification": _classification(materiality="material")},
                {"index": 1, "classification": _classification(materiality="mild")},
            ]
        }
        verdicts = _aligned_verdicts(payload, 2, _Completion())
        assert verdicts is not None
        assert [v["materiality"] for v in verdicts] == ["material", "mild"]

    def test_the_engine_and_call_id_are_attached_to_every_verdict(self):
        payload = [
            {"index": 0, "classification": _classification()},
            {"index": 1, "classification": _classification()},
        ]
        verdicts = _aligned_verdicts(payload, 2, _Completion())
        assert all(v["engine"] == "deepseek:test-model" for v in verdicts)
        assert all(v["llm_call_id"] == 7 for v in verdicts)


class _BatchClassifier:
    """A classifier that answers a batch, recording how it was asked."""

    def __init__(self, verdict_for):
        self.batches: list[list[str]] = []
        self.singles: list[str] = []
        self._verdict_for = verdict_for

    def __call__(self, item, _instrument):
        self.singles.append(item.title)
        return _classification(materiality="mild")

    def many(self, items, _instrument):
        self.batches.append([i.title for i in items])
        return [self._verdict_for(i.title) for i in items]


def _raw(index: int, title: str, ticker: str = "AAPL_US_EQ") -> RawNewsItem:
    return RawNewsItem(title=title, url=f"https://example.test/{index}", source="test",
                       tickers=[ticker])


class TestTheIngestAsksOnceForTheBatch:
    def test_one_call_covers_every_headline(self, session):
        instrument = make_instrument("AAPL_US_EQ")
        session.add(instrument)
        session.flush()

        classifier = _BatchClassifier(lambda title: _classification())
        titles = [f"Apple announces something material number {n} - Yahoo Finance" for n in range(5)]

        report = NewsIngestReport()
        persist_items(
            session,
            [_raw(n, t) for n, t in enumerate(titles)],
            classifier=classifier,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert len(classifier.batches) == 1, "one batch expected"
        assert len(classifier.batches[0]) == 5
        assert classifier.singles == [], "no per-headline calls once the batch works"
        assert report.classified == 5

    def test_each_row_gets_the_verdict_for_its_own_headline(self, session):
        """The failure this whole change risks: a verdict one story out."""
        instrument = make_instrument("AAPL_US_EQ")
        session.add(instrument)
        session.flush()

        materials = ["critical", "none", "mild", "material", "moderate"]
        classifier = _BatchClassifier(
            lambda title: _classification(
                materiality=materials[int(title.rsplit(" ", 1)[-1])]
            )
        )
        titles = [f"Apple announces something material number {n}" for n in range(5)]

        persist_items(
            session,
            [_raw(n, t) for n, t in enumerate(titles)],
            classifier=classifier,
            report=NewsIngestReport(),
            instrument=instrument,
        )
        session.flush()

        stored = {
            row.title: row.materiality
            for row in session.query(NewsItem).all()
        }
        for n, title in enumerate(titles):
            assert stored[title] == materials[n], f"{title} got the wrong verdict"

    def test_a_classifier_without_many_is_called_per_headline(self, session):
        """The sector classifier has no `many`, and must keep working unchanged."""
        instrument = make_instrument("AAPL_US_EQ")
        session.add(instrument)
        session.flush()

        asked: list[str] = []

        def plain(item, _instrument):
            asked.append(item.title)
            return _classification()

        report = NewsIngestReport()
        persist_items(
            session,
            [_raw(n, f"Apple announces something number {n}") for n in range(3)],
            classifier=plain,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert len(asked) == 3
        assert report.classified == 3

    def test_a_short_batch_from_many_is_refused_rather_than_paired(self, session):
        """Defence in depth, for a classifier that breaks its own `many` contract.

        `NewsBatchClassifier.many` already re-asks when the model misaligns, so this
        covers the layer above it: if a list ever arrives short, `persist_items` refuses
        the whole batch instead of pairing the answers it did get with the wrong rows.
        """
        instrument = make_instrument("AAPL_US_EQ")
        session.add(instrument)
        session.flush()

        class ShortBatch:
            def __init__(self):
                self.singles: list[str] = []

            def __call__(self, item, _instrument):
                self.singles.append(item.title)
                return _classification(materiality="material")

            def many(self, items, _instrument):
                # One answer short, as a miscounting model would return.
                return [_classification(materiality="material") for _ in items[:-1]]

        classifier = ShortBatch()
        titles = [f"Apple announces something number {n}" for n in range(4)]

        report = NewsIngestReport()
        persist_items(
            session,
            [_raw(n, t) for n, t in enumerate(titles)],
            classifier=classifier,
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert classifier.singles == [], "persist_items does not re-ask; it refuses"
        assert report.classified == 0, "a refused batch is not counted as classified"

        stored = session.query(NewsItem).all()
        assert len(stored) == 4, "no headline is lost"
        assert all(row.relevant is None for row in stored), "left for the backfill, not guessed"


class TestMissingVerdictsAreNotGuesses:
    def test_an_unanswered_headline_is_stored_with_no_verdict(self, session):
        instrument = make_instrument("AAPL_US_EQ")
        session.add(instrument)
        session.flush()

        class HalfBatch:
            def __call__(self, item, _instrument):
                return None

            def many(self, items, _instrument):
                return [None for _ in items]

        report = NewsIngestReport()
        persist_items(
            session,
            [_raw(n, f"Apple announces something number {n}") for n in range(3)],
            classifier=HalfBatch(),
            report=report,
            instrument=instrument,
        )
        session.flush()

        assert report.classified == 0
        stored = session.query(NewsItem).all()
        assert len(stored) == 3
        assert all(row.materiality is None for row in stored)


class TestManyItself:
    """The real `NewsBatchClassifier.many`, with the network call stubbed out.

    An earlier version of this test subclassed `many` and asserted on the subclass --
    which tested the test. These call the shipped method and watch which calls it makes.
    """

    def _classifier(self):
        from awltux.llm.classify import NewsBatchClassifier

        return NewsBatchClassifier(settings=object(), client=object())

    def test_the_batch_size_bounds_the_request(self, monkeypatch):
        from awltux.llm import classify as module

        sizes: list[int] = []
        monkeypatch.setattr(
            module, "classify_headlines", lambda items, **kw: (sizes.append(len(items)), [None for _ in items])[1]
        )
        monkeypatch.setattr(module, "classify_headline", lambda item, **kw: None)

        instrument = make_instrument("AAPL_US_EQ")
        items = [_raw(n, f"Apple announces something number {n}") for n in range(45)]
        verdicts = self._classifier().many(items, instrument)

        assert sizes == [20, 20, 5], f"expected 20/20/5, got {sizes}"
        assert all(size <= 20 for size in sizes)
        assert len(verdicts) == 45, "one verdict per headline, whatever the split"

    def test_a_lone_headline_skips_the_batch_envelope(self, monkeypatch):
        from awltux.llm import classify as module

        batched: list[int] = []
        singles: list[int] = []
        monkeypatch.setattr(module, "classify_headlines", lambda items, **kw: batched.append(len(items)))
        monkeypatch.setattr(
            module, "classify_headline", lambda item, **kw: (singles.append(1), None)[1]
        )

        self._classifier().many([_raw(0, "Apple announces something")], make_instrument("AAPL_US_EQ"))

        assert batched == [] and singles == [1]

    def test_an_unaligned_batch_falls_back_to_one_call_per_headline(self, monkeypatch):
        """The safety net that makes batching safe to ship.

        `classify_headlines` returning `None` means the model's answer could not be
        matched to the headlines. The response is to ask again one at a time, not to
        guess which answer belonged to which story.
        """
        from awltux.llm import classify as module

        singles: list[str] = []
        monkeypatch.setattr(module, "classify_headlines", lambda items, **kw: None)
        monkeypatch.setattr(
            module,
            "classify_headline",
            lambda item, **kw: (singles.append(item.title), _classification(materiality="mild"))[1],
        )

        instrument = make_instrument("AAPL_US_EQ")
        items = [_raw(n, f"Apple announces something number {n}") for n in range(4)]
        verdicts = self._classifier().many(items, instrument)

        assert len(singles) == 4, "every headline re-asked individually"
        assert [v["materiality"] for v in verdicts] == ["mild"] * 4, "and each got its own answer"

    def test_no_instrument_means_no_calls(self, monkeypatch):
        from awltux.llm import classify as module

        monkeypatch.setattr(module, "classify_headlines", lambda items, **kw: pytest.fail("called"))
        monkeypatch.setattr(module, "classify_headline", lambda item, **kw: pytest.fail("called"))

        assert self._classifier().many([_raw(0, "Apple announces something")], None) == [None]
