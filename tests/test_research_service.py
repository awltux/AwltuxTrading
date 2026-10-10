"""Starting a deep-dive: the guards, the refresh, the model call, and the stored report.

The costs are why these tests exist. A deep-dive is the only thing in this application that
a person asks for by hand and waits on, it spends the expensive model, and it reads several
documents at once -- so the properties worth pinning are the ones that stop it being run
twice, run about nothing, or run over data nobody refreshed:

* **The row is the guard.** A second press while a run holds the subject is refused, and the
  refusal is a row that already exists rather than a second source of truth about "running".
* **A crash is not permanent.** A `running` row left by a dead process is closed at startup,
  and one older than the staleness window does not block the subject for ever.
* **The refresh is the only data acquisition, and it is not repeated for free.** Nothing here
  fetches: the run refreshes the instrument through the existing pipeline, skips it when a
  successful refresh finished minutes ago, and says which of the two happened.
* **The lease is not held across the model call.** The refresh owns the instrument's lease
  and releases it when the refresh ends, because a lease held for the minutes a deep model
  takes would keep the instrument out of every sweep and make the Refresh panel describe a
  run that is not happening.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import types
import xml.etree.ElementTree as ElementTree

import pytest

from awltux.db import (
    FundamentalPeriod,
    InstrumentRefresh,
    NewsAnalysis,
    NewsItem,
    ResearchReport,
    utcnow,
)
from awltux.llm.deepseek import Completion
from awltux.research import service
from tests.helpers import make_instrument

TICKER = "TEST_US_EQ"
SECTOR = "Energy"
HEADLINE = "Test Co warns on costs"


def _instrument(session, ticker: str = TICKER) -> None:
    session.add(make_instrument(ticker, name="Test Co"))
    session.flush()


def _story(session, *, headline: str = HEADLINE) -> NewsItem:
    item = NewsItem(
        source="google_news",
        url=f"https://x.test/{headline.replace(' ', '-')}",
        url_hash=f"hash-{headline}",
        title=headline,
        published_at=utcnow(),
        tickers=[TICKER],
        sectors=[],
        materiality="material",
        direction="negative",
        relevant=True,
        title_key=headline.lower(),
    )
    session.add(item)
    session.flush()
    session.add(
        NewsAnalysis(
            news_item_id=item.id,
            subject_type="instrument",
            subject_id=TICKER,
            credibility=0.3,
            evidence_grade="weak",
            flags=["single_source"],
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
    session.flush()
    return item


def _payload(**overrides) -> dict:
    """A model answer that survives every rule in `research.report.validate_result`."""
    payload = {
        "executive_summary": "A test company with thin evidence.",
        "verdict": "watch",
        "confidence": 0.4,
        "suitability": {"horizon": "long_term", "risk": "high", "reason": "Thin evidence."},
        "business": {"summary": "It makes things."},
        "management": {"assessment": "No long record held."},
        "strengths": [
            {
                "point": "Revenue is stated",
                "evidence": "Total revenue 1,000,000",
                "source": "10-K",
                "location": "Income statement",
            }
        ],
        "concerns": [],
        "news_themes": [
            {
                "theme": "Costs are rising",
                "direction": "negative",
                "basis": [HEADLINE],
                "corroboration": "one carrier",
            }
        ],
        "what_would_change_my_mind": "A filed set of accounts.",
        "sections": [{"heading": "What it does", "paragraphs": ["Prose."]}],
        "sources_seen": ["10-K"],
        "reporting_currency": "GBP",
        "units": "actual",
        "period_end": "2025-12-31",
        "period_type": "annual",
        "metrics": {
            "revenue": {
                "value": 1_000_000,
                "span": "Total revenue 1,000,000",
                "location": "Income statement",
            }
        },
        "injection_suspected": False,
    }
    payload.update(overrides)
    return payload


class StubClient:
    """A DeepSeek client that answers from memory and records what it was sent.

    ``probe`` runs *inside* the call, which is how a test can ask what the world looked like
    at the moment the model was asked -- the lease, for instance.
    """

    def __init__(self, payload: dict | None = None, error: Exception | None = None, probe=None):
        self.payload = payload if payload is not None else _payload()
        self.error = error
        self.probe = probe
        self.calls: list[dict] = []

    def complete(self, **kwargs) -> Completion:
        self.calls.append(kwargs)
        if self.probe is not None:
            self.probe()
        if self.error is not None:
            raise self.error
        return Completion(
            text=json.dumps(self.payload),
            model=kwargs.get("model") or "deepseek-reasoner",
            input_tokens=1_000,
            output_tokens=200,
            cost_usd=0.02,
            llm_call_id=7,
        )


class InlineThread:
    """A thread that runs its target now, so a test does not have to wait for one.

    Replaces the *module's* reference rather than `threading.Thread` itself: patching the
    real one would reach into pytest's own machinery for the duration of the test.
    """

    def __init__(self, target=None, args=(), name=None, daemon=None) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


@pytest.fixture
def inline(monkeypatch):
    monkeypatch.setattr(service, "threading", types.SimpleNamespace(Thread=InlineThread))


@pytest.fixture(autouse=True)
def _no_real_refresh(monkeypatch):
    """No test in this file may run the real refresh phase: its steps call providers.

    Autouse rather than per-test because the failure is silent and slow -- the first version
    of this file left the refresh un-stubbed in the plain `TestTheRun` cases, and the steps
    failed their way through HTTP retries with a 30-second backoff cap, so every run test
    took half a minute and none of them said why. A test that reaches a provider is a bug
    (`AGENTS.md` §3), and the guard belongs where the reaching happens.
    """

    def fake(ticker, token):
        from awltux.db.session import session_scope
        from awltux.ingest.lease import release

        with session_scope() as scope:
            # The real one gives the lease up when the sequence ends, and the tests that
            # care about *when* it is released depend on that being true here as well.
            release(scope, ticker, token=token, state="done", note="stubbed refresh")
            scope.commit()
        return {"steps_done": 0, "results": []}

    monkeypatch.setattr("awltux.ingest.refresh.run_under_lease", fake)


def _run(session, prompt: str = "Research Test Co", client=None) -> service.Started:
    """Start a deep-dive and let it finish, on this thread."""
    return service.start(
        subject_type="instrument",
        subject_id=TICKER,
        prompt=prompt,
        client=client or StubClient(),
    )


def _reports(session) -> list[ResearchReport]:
    from sqlalchemy import select

    return list(session.execute(select(ResearchReport)).scalars().all())


class TestStarting:
    def test_it_refuses_an_unknown_subject(self, session):
        started = service.start(subject_type="instrument", subject_id="NOPE_US_EQ", prompt="x")

        assert started.ok is False
        assert "not in this database" in started.message
        assert _reports(session) == []

    def test_it_refuses_a_subject_type_it_does_not_know(self, session):
        started = service.start(subject_type="portfolio", subject_id=TICKER, prompt="x")

        assert started.ok is False
        assert "not something research runs about" in started.message

    def test_it_refuses_an_empty_prompt(self, session, settings):
        _instrument(session)
        session.commit()

        started = service.start(
            subject_type="instrument", subject_id=TICKER, prompt="   ", client=StubClient()
        )

        assert started.ok is False
        assert "empty" in started.message

    def test_it_refuses_when_the_feature_is_off(self, session, settings):
        _instrument(session)
        session.commit()
        settings.research.enabled = False

        started = service.start(
            subject_type="instrument", subject_id=TICKER, prompt="x", client=StubClient()
        )

        assert started.ok is False
        assert "switched off" in started.message

    def test_it_refuses_without_a_configured_key(self, session, settings):
        """Refused before a row is written, not after a failed run: the reader should not
        be told a deep-dive is under way when nothing could read anything."""
        _instrument(session)
        session.commit()

        started = service.start(subject_type="instrument", subject_id=TICKER, prompt="x")

        assert started.ok is False
        assert "no DeepSeek API key" in started.message
        assert _reports(session) == []

    def test_a_second_run_of_the_same_subject_is_refused(self, session, settings, inline):
        _instrument(session)
        session.add(
            ResearchReport(
                subject_type="instrument",
                subject_id=TICKER,
                status="running",
                title="Test Co (TEST_US_EQ)",
                prompt="first",
                prompt_sha256="x",
                created_at=utcnow(),
            )
        )
        session.commit()

        started = _run(session)

        assert started.ok is False
        assert "already running" in started.message
        assert len(_reports(session)) == 1, "the running row is the guard; no second row"

    def test_a_stale_running_row_does_not_block_for_ever(self, session, settings, inline):
        """A process killed mid-run leaves `running` behind, and refusing every later run
        until somebody edits the database would make one crash permanent."""
        _instrument(session)
        session.add(
            ResearchReport(
                subject_type="instrument",
                subject_id=TICKER,
                status="running",
                title="Test Co (TEST_US_EQ)",
                prompt="stale",
                prompt_sha256="x",
                created_at=utcnow() - dt.timedelta(minutes=settings.research.stale_minutes + 5),
            )
        )
        session.commit()

        started = _run(session)

        assert started.ok is True
        statuses = sorted(row.status for row in _reports(session))
        assert statuses == ["done", "running"]


class TestTheRun:
    def test_the_report_is_stored_and_the_document_is_written(self, session, settings, inline):
        _instrument(session)
        _story(session)
        session.commit()

        started = _run(session, prompt="Judge Management's capital allocation")

        assert started.ok is True
        row = _reports(session)[0]
        assert row.status == "done"
        assert row.finished_at is not None
        assert row.verdict == "watch"
        assert row.confidence == 0.4
        assert row.exec_summary == "A test company with thin evidence."
        assert row.model
        assert row.llm_call_id == 7
        assert row.prompt == "Judge Management's capital allocation"
        assert row.prompt_sha256 == hashlib.sha256(row.prompt.encode("utf-8")).hexdigest()

        path = settings.research_dir / "instrument" / TICKER / f"{row.id}.xhtml"
        assert path.exists(), "the report has to be on disk for the list to link to it"
        assert row.bytes == path.stat().st_size > 0
        # `raw_path` is a *location*, relative to the data directory, the same shape a filing
        # stores. It was `path.name` until 2026-10-10 -- a bare `1.xhtml` -- which is not a
        # path at all, so joining it to the data directory named nothing and the first
        # deep-dive ever completed answered 404 while the page listed it as readable.
        assert row.raw_path == str(path.relative_to(settings.data_dir))
        # Parsed as XML, which is the only definition of "is XHTML" that is checkable.
        ElementTree.parse(path)

    def test_the_metrics_reach_the_result_set_in_the_stored_shape(self, session, settings, inline):
        """The result set is what makes a deep-dive *contribute* rather than sit beside the
        analysis database: same metric names, same provenance shape as a filing extraction."""
        _instrument(session)
        session.commit()

        _run(session)

        row = _reports(session)[0]
        assert row.result["metrics"] == {
            "revenue": {
                "value": 1_000_000.0,
                "span": "Total revenue 1,000,000",
                "location": "Income statement",
                "source": "llm_extraction",
            }
        }
        assert row.result["reporting_currency"] == "GBP"

    def test_the_documents_and_digest_are_the_cacheable_prefix(self, session, settings, inline):
        """`build_messages` puts the large stable part first so DeepSeek's prefix cache can
        hit on a re-run; the editable prompt goes last, where its variability is free."""
        _instrument(session)
        _story(session)
        session.commit()
        client = StubClient()

        _run(session, prompt="my edited prompt", client=client)

        messages = client.calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert "suitable investment" in messages[0]["content"]
        assert messages[1]["content"].startswith("<document>")
        assert HEADLINE in messages[1]["content"], "the digest is part of the evidence"
        assert messages[-1] == {"role": "user", "content": "my edited prompt"}
        assert client.calls[0]["json_mode"] is True
        assert client.calls[0]["max_tokens"] == settings.research.max_output_tokens

    def test_the_model_is_the_deep_one_and_overridable(self, session, settings, inline):
        """A deep-dive is judged work, so it routes to the far model -- and the config can
        name one explicitly, because that is the knob a reader will reach for."""
        _instrument(session)
        session.commit()
        client = StubClient()
        _run(session, client=client)
        assert client.calls[0]["model"] == settings.llm.model_deep

        settings.research.model = "deepseek-special"
        client = StubClient()
        _run(session, client=client)
        assert client.calls[0]["model"] == "deepseek-special"

    def test_a_model_failure_closes_the_row_rather_than_leaving_it_running(
        self, session, settings, inline
    ):
        _instrument(session)
        session.commit()

        started = _run(session, client=StubClient(error=RuntimeError("the model refused")))

        assert started.ok is True, "the run started; it failed inside"
        row = _reports(session)[0]
        assert row.status == "failed"
        assert "the model refused" in row.error
        assert row.finished_at is not None
        assert row.raw_path is None

    def test_a_failed_subject_can_be_tried_again(self, session, settings, inline):
        _instrument(session)
        session.commit()
        _run(session, client=StubClient(error=RuntimeError("transient")))

        started = _run(session)

        assert started.ok is True
        assert sorted(row.status for row in _reports(session)) == ["done", "failed"]

    def test_the_inventory_records_what_was_read(self, session, settings, inline):
        _instrument(session)
        _story(session)
        session.commit()

        _run(session)

        row = _reports(session)[0]
        assert row.inventory["news"]["total"] == 1
        assert row.inventory["news"]["appraised"] == 1
        assert row.inventory["documents"] == []
        assert row.inventory["document_chars"] == 0
        assert row.inventory["model"]


class TestTheRefreshPhase:
    def test_a_sector_run_never_refreshes(self, session, settings, inline, monkeypatch):
        """A sector has no refresh pipeline, and the report says so rather than implying a
        gap that is really an absence of machinery."""
        monkeypatch.setattr(
            "awltux.ingest.refresh.run_under_lease",
            lambda *_a, **_k: pytest.fail("a sector has no refresh pipeline"),
        )
        from awltux.analysis.sectors import SECTOR_NAMES

        sector = SECTOR_NAMES[0]
        session.add(
            NewsItem(
                source="google_news",
                url="https://x.test/sector",
                url_hash="sector-1",
                title="Refining margins compress",
                published_at=utcnow(),
                tickers=[],
                sectors=[sector],
                materiality="material",
                direction="negative",
                relevant=True,
            )
        )
        session.commit()

        started = service.start(
            subject_type="sector", subject_id=sector, prompt="research the sector", client=StubClient()
        )

        assert started.ok is True
        row = _reports(session)[0]
        assert row.refresh["state"] == "not_applicable"
        assert row.status == "done"

    def test_a_recent_successful_refresh_is_not_repeated(self, session, settings, inline, monkeypatch):
        """The button is pressed for a judgement, not to re-fetch what was fetched ten
        minutes ago."""
        _instrument(session)
        session.add(
            InstrumentRefresh(
                instrument_t212_ticker=TICKER,
                token="t",
                state="done",
                note="13 of 13 steps completed",
                started_at=utcnow() - dt.timedelta(minutes=5),
                finished_at=utcnow() - dt.timedelta(minutes=4),
                expires_at=utcnow() - dt.timedelta(minutes=4),
                steps=[],
            )
        )
        session.commit()
        monkeypatch.setattr(
            "awltux.ingest.refresh.run_under_lease",
            lambda *_a, **_k: pytest.fail("a four-minute-old refresh must not be repeated"),
        )

        _run(session)

        row = _reports(session)[0]
        assert row.refresh["state"] == "recent"
        assert "not refreshed again" in row.refresh["note"]
        assert row.status == "done"

    def test_a_stale_refresh_is_repeated(self, session, settings, inline, monkeypatch):
        _instrument(session)
        session.add(
            InstrumentRefresh(
                instrument_t212_ticker=TICKER,
                token="t",
                state="done",
                started_at=utcnow() - dt.timedelta(days=1),
                finished_at=utcnow() - dt.timedelta(days=1),
                expires_at=utcnow() - dt.timedelta(days=1),
                steps=[],
            )
        )
        session.commit()
        seen: list[str] = []

        def fake_run(ticker, token):
            seen.append(ticker)
            return {"steps_done": 0, "results": []}

        monkeypatch.setattr("awltux.ingest.refresh.run_under_lease", fake_run)

        _run(session)

        assert seen == [TICKER]
        assert _reports(session)[0].refresh["state"] == "refreshed"

    def test_a_running_refresh_is_not_fought_over(self, session, settings, inline, monkeypatch):
        """The lease belongs to whoever holds it. A deep-dive that waited for it, or took it
        over, would either stall or race a refresh that is already writing."""
        _instrument(session)
        session.add(
            InstrumentRefresh(
                instrument_t212_ticker=TICKER,
                token="someone-else",
                state="running",
                started_at=utcnow(),
                expires_at=utcnow() + dt.timedelta(minutes=10),
                steps=[],
            )
        )
        session.commit()
        monkeypatch.setattr(
            "awltux.ingest.refresh.run_under_lease",
            lambda *_a, **_k: pytest.fail("the lease is held by a refresh that is running"),
        )

        _run(session)

        row = _reports(session)[0]
        assert row.refresh["state"] == "skipped"
        assert "already running" in row.refresh["note"]
        assert row.status == "done"

    def test_the_lease_is_not_held_across_the_model_call(self, session, settings, inline, monkeypatch):
        """The measurement: the model call is minutes long, and a lease held across it keeps
        the instrument out of every sweep and makes the Refresh panel print "step 14 of 13".
        """
        _instrument(session)
        session.commit()
        observed: list[str | None] = []

        def fake_refresh(ticker, token):
            """The real one releases the lease when the sequence ends; this mimics that."""
            from awltux.db.session import session_scope
            from awltux.ingest.lease import release

            with session_scope() as scope:
                release(scope, ticker, token=token, state="done", note="fake refresh")
                scope.commit()
            return {"steps_done": 0, "results": []}

        monkeypatch.setattr("awltux.ingest.refresh.run_under_lease", fake_refresh)

        def probe() -> None:
            from awltux.db.session import session_scope

            with session_scope() as scope:
                observed.append(scope.get(InstrumentRefresh, TICKER).state)

        _run(session, client=StubClient(probe=probe))

        assert observed == ["done"], (
            "the model was asked while the instrument's lease was still running"
        )

    def test_a_refresh_that_fails_does_not_lose_the_deep_dive(self, session, settings, inline, monkeypatch):
        """A dead provider says nothing about whether the documents already held can be
        judged, and the report records the failure rather than hiding it."""
        _instrument(session)
        session.commit()

        def fake_refresh(ticker, token):
            from awltux.db.session import session_scope
            from awltux.ingest.lease import release

            with session_scope() as scope:
                release(scope, ticker, token=token, state="failed", note="EDGAR returned 503")
                scope.commit()
            return {"failed": "EDGAR returned 503", "results": []}

        monkeypatch.setattr("awltux.ingest.refresh.run_under_lease", fake_refresh)

        _run(session)

        row = _reports(session)[0]
        assert row.status == "done"
        assert row.refresh["state"] == "failed"
        assert "EDGAR returned 503" in row.refresh["note"]


class TestHousekeeping:
    def test_a_restart_closes_a_running_report(self, session, settings):
        """A `running` row is a subject-level guard, so left behind it would refuse every
        later run about that company until the staleness window passed."""
        _instrument(session)
        session.add(
            ResearchReport(
                subject_type="instrument",
                subject_id=TICKER,
                status="running",
                title="Test Co (TEST_US_EQ)",
                prompt="x",
                prompt_sha256="x",
                created_at=utcnow(),
            )
        )
        session.commit()

        closed = service.close_orphaned_research()

        assert closed == 1
        row = _reports(session)[0]
        assert row.status == "failed"
        assert row.error == "interrupted by a restart"
        assert row.finished_at is not None

    def test_it_leaves_finished_reports_alone(self, session, settings):
        _instrument(session)
        session.add(
            ResearchReport(
                subject_type="instrument",
                subject_id=TICKER,
                status="done",
                title="Test Co (TEST_US_EQ)",
                prompt="x",
                prompt_sha256="x",
                created_at=utcnow(),
                finished_at=utcnow(),
            )
        )
        session.commit()

        assert service.close_orphaned_research() == 0
        assert _reports(session)[0].status == "done"


class TestTheFiguresReachTheAnalysis:
    """A deep-dive *contributes* rather than sitting beside the analysis database.

    The result set's figures go through the same writer as a filing extraction -- the same
    scaling, the same refusal when the material did not say what units it was in, the same
    derived ratios -- and land as a `FundamentalPeriod` the valuation and every marker read.
    """

    def _periods(self, session, ticker: str = TICKER) -> list[FundamentalPeriod]:
        from sqlalchemy import select

        return list(
            session.execute(
                select(FundamentalPeriod).where(
                    FundamentalPeriod.instrument_t212_ticker == ticker
                )
            ).scalars().all()
        )

    def test_the_cited_figures_become_a_stored_period(self, session, settings, inline):
        _instrument(session)
        session.commit()

        _run(session)

        rows = self._periods(session)
        assert len(rows) == 1
        period = rows[0]
        assert period.source == "deep_research"
        assert period.period_end == dt.date(2025, 12, 31)
        assert period.period_type == "annual"
        # `units: actual` in the payload, so the scale is 1 and the figure is as quoted.
        assert period.metrics["revenue"] == 1_000_000.0
        assert _reports(session)[0].inventory["periods"]["outcome"] == "stored"

    def test_the_span_is_stamped_with_the_pipeline_that_read_it(self, session, settings, inline):
        """`ExtractedMetric.as_dict` writes `llm_extraction` because that was the only
        writer. A deep-dive's spans come from a different call, and a provenance map that
        named the filing extractor would be a lie in the column whose job is to say where a
        figure came from."""
        _instrument(session)
        session.commit()

        _run(session)

        stored = self._periods(session)[0].metric_sources["revenue"]
        assert stored["source"] == "deep_research"
        assert stored["span"] == "Total revenue 1,000,000"

    def test_units_the_material_never_stated_lose_the_period(self, session, settings, inline):
        """Storing an unscaled period from a source that outranks the providers would put a
        figure a million times too small at the top of the preference order, and no marker
        would notice: the ratios are scale-invariant."""
        _instrument(session)
        session.commit()

        _run(session, client=StubClient(payload=_payload(units="bananas")))

        assert self._periods(session) == []
        row = _reports(session)[0]
        assert row.status == "done", "the report is still worth keeping"
        assert row.inventory["periods"]["outcome"] == "unscaled"

    def test_a_report_with_no_figures_stores_no_period(self, session, settings, inline):
        """An empty `metrics` object is an acceptable answer, and it must not become a
        period full of nothing."""
        _instrument(session)
        session.commit()

        _run(session, client=StubClient(payload=_payload(metrics={})))

        assert self._periods(session) == []
        assert _reports(session)[0].inventory["periods"]["outcome"] == "unusable"

    def test_a_sector_run_stores_no_period(self, session, settings, inline):
        """There is no sector instrument to attach figures to, and inventing one would put
        a company's numbers under an industry."""
        from awltux.analysis.sectors import SECTOR_NAMES

        _instrument(session)
        session.commit()

        service.start(
            subject_type="sector",
            subject_id=SECTOR_NAMES[0],
            prompt="the sector",
            client=StubClient(),
        )

        assert self._periods(session) == []
        assert _reports(session)[0].inventory["periods"] == {}

    def test_the_report_ranks_below_a_filing_extraction(self):
        """Both read a document and both quote what they read, but the filing extractor's
        whole job is one document and its figures, while a deep-dive is a synthesis. When
        they disagree about the same period, the focused read is the one to trust."""
        from awltux.analysis.collate import SOURCE_RANK

        assert SOURCE_RANK["deep_research"] < SOURCE_RANK["llm_extraction"]
        # And above the scraped snapshots, because it quotes the document.
        assert SOURCE_RANK["deep_research"] > SOURCE_RANK["yahoo_statements"]


class TestTheDraftPrompt:
    def test_it_is_the_template_plus_what_the_run_will_read(self, session, settings):
        """What the reader approves is what the run reads: the inventory comes from the same
        builder, so the two cannot drift into describing different scopes."""
        _instrument(session)
        _story(session)
        session.flush()

        prompt = service.draft_prompt("instrument", TICKER, settings=settings, session=session)

        assert "Research Test Co (TEST_US_EQ)" in prompt
        assert "What this run will read:" in prompt
        assert "How to read the news digest:" in prompt
        assert "1 stories" in prompt
        assert "Return JSON:" in prompt

    def test_it_is_none_for_a_subject_this_database_does_not_hold(self, session, settings):
        assert service.draft_prompt("instrument", "NOPE_US_EQ", settings=settings, session=session) is None

    def test_it_is_sector_aware(self, session, settings):
        from awltux.analysis.sectors import SECTOR_NAMES

        prompt = service.draft_prompt("sector", SECTOR_NAMES[0], settings=settings, session=session)

        assert "sector" in prompt
        assert "news corpus only" in prompt
