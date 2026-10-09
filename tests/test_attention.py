"""The "Needs attention" reasons: what counts, at which level, and why.

The filter exists because the dashboard renders a fair value for a company whose
accounts were never fetched, whose filings are unparsed, or whose balance sheet does not
add up -- all of them the same em-dash in the same column. These tests pin the two
things that make it usable rather than theatre:

* **Every reason names what it measured.** A reason that says only "accounts
  incomplete" is a verdict, and the docstring of the module says so; the detail has to
  carry the figure, the date or the provider's words.
* **The ladder is cumulative and the setting picks the rung.** The system is settling,
  so what counts as a problem changes; level 1 is the default because a filter selecting
  90% of the table discriminates nothing, and *that* is what a test has to protect.
  Measured on the live universe, 2026-10-07: level 1 flags 21 of 500, level 2 202, level
  3 478.
"""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from awltux.analysis import attention
from awltux.analysis.attention import assess, reasons_for
from awltux.config import AppConfig
from awltux.db import Filing, FundamentalPeriod, Instrument, InstrumentBlocker, utcnow


def _seed(session, ticker: str, **overrides) -> Instrument:
    """An instrument in the universe, flushed so dependents can reference it.

    ``sec_cik`` is set by default and deliberately: ``make_instrument`` leaves it null,
    which would make every instrument here qualify for the level-2 "no SEC CIK" reason
    and hide the reason each test is actually about.
    """
    from tests.helpers import make_instrument

    overrides.setdefault("sec_cik", "0000000001")
    instrument = make_instrument(ticker, **overrides)
    session.add(instrument)
    session.flush()
    return instrument


def _add_period(
    session,
    ticker: str,
    *,
    period_end: dt.date = dt.date(2025, 12, 31),
    metrics: dict | None = None,
    sources: dict | None = None,
) -> FundamentalPeriod:
    period = FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=period_end,
        period_type="annual",
        source="xbrl_companyfacts",
        currency="USD",
        metrics=(
            {"revenue": 1_000_000.0, "total_assets": 5_000_000.0}
            if metrics is None
            else metrics
        ),
        metric_sources=(
            {"revenue": {"span": "us-gaap:Revenues"}} if sources is None else sources
        ),
    )
    session.add(period)
    return period


def _add_blocker(session, ticker: str, **overrides) -> InstrumentBlocker:
    stamp = utcnow()
    blocker = InstrumentBlocker(
        instrument_t212_ticker=ticker,
        job=overrides.pop("job", "xbrl_statements"),
        stage=overrides.pop("stage", "statements"),
        reason=overrides.pop("reason", "[edgar] HTTP 403"),
        first_seen_at=stamp,
        last_seen_at=stamp,
        occurrences=overrides.pop("occurrences", 1),
        resolved_at=overrides.pop("resolved_at", None),
    )
    session.add(blocker)
    return blocker


def _facts(session, ticker: str):
    """The fact bundle for one instrument, gathered exactly as ``assess`` gathers it.

    Not a hand-built empty one: the rules read the period, the blockers and the filing
    counts off this object, so a test that skipped the gathering step would be asserting
    against an instrument that never has any accounts.
    """
    from awltux.analysis.attention import _gather

    return _gather(session, [session.get(Instrument, ticker)])[ticker]


def _codes(session, ticker: str, *, today: dt.date = dt.date(2026, 1, 5)) -> list[str]:
    return [reason.code for reason in reasons_for(_facts(session, ticker), today=today)]


class TestTheLadder:
    def test_level_one_is_the_default(self):
        """The system is settling, and a filter that selects everything discriminates
        nothing -- so the strict rung is what an unconfigured install gets."""
        assert AppConfig().attention_level == 1

    @pytest.mark.parametrize("bad", [0, 4, -1, 99])
    def test_a_level_outside_the_ladder_is_refused(self, bad):
        """Fail closed and say so. A silent clamp would show a filter the operator did
        not ask for while reporting the setting they did."""
        with pytest.raises(ValidationError):
            AppConfig(attention_level=bad)

    def test_a_reason_below_the_level_is_not_reported(self, session, settings):
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        at_one = assess(session, level=1, settings=settings)
        at_three = assess(session, level=3, settings=settings)

        assert at_one["CLEAN_US_EQ"].needed is False
        assert at_three["CLEAN_US_EQ"].needed is True
        assert at_three["CLEAN_US_EQ"].codes == ("no_accounts",)

    def test_the_configured_level_is_what_the_default_uses(self, session, settings):
        """`assess` with no level follows the setting, not a hard-coded rung."""
        _seed(session, "CLEAN_US_EQ")
        session.commit()
        settings.yaml.app.attention_level = 3

        found = assess(session, settings=settings)

        assert found["CLEAN_US_EQ"].needed is True
        assert found["CLEAN_US_EQ"].level == 3

    def test_an_explicit_level_overrides_the_setting(self, session, settings):
        _seed(session, "CLEAN_US_EQ")
        session.commit()
        settings.yaml.app.attention_level = 3

        assert assess(session, level=1, settings=settings)["CLEAN_US_EQ"].needed is False

    def test_a_level_outside_the_range_raises_rather_than_clamping(self, session, settings):
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        with pytest.raises(ValueError, match="1..3"):
            assess(session, level=9, settings=settings)

    def test_an_assessed_and_clean_instrument_is_still_returned(self, session, settings):
        """Otherwise a caller cannot tell "clean" from "not looked at"."""
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        found = assess(session, level=1, settings=settings)

        assert set(found) == {"CLEAN_US_EQ"}
        assert found["CLEAN_US_EQ"].reasons == ()


class TestLevelOne:
    """The figures we hold are wrong or incomplete."""

    def test_a_balance_sheet_that_does_not_add_up(self, session):
        """The one accounting check that is a contradiction rather than a gap: both
        sides are figures we hold, so nothing is explained by a line we failed to read."""
        _seed(session, "ODD_US_EQ")
        _add_period(
            session,
            "ODD_US_EQ",
            metrics={
                "revenue": 1_000_000.0,
                # Assets 900,000 against liabilities 400,000 + equity 100,000.
                "total_assets": 900_000.0,
                "total_liabilities": 400_000.0,
                "total_equity": 100_000.0,
            },
        )
        session.commit()

        reasons = reasons_for(_facts(session, "ODD_US_EQ"), today=dt.date(2026, 1, 5))

        codes = [reason.code for reason in reasons]
        assert "equation" in codes
        equation = next(reason for reason in reasons if reason.code == "equation")
        # The figures, not just the verdict.
        assert "400,000" in equation.detail
        assert "500,000" in equation.detail

    def test_a_period_missing_the_figures_everything_divides_by(self, session):
        _seed(session, "THIN_US_EQ")
        _add_period(session, "THIN_US_EQ", metrics={"total_assets": 5_000_000.0})
        session.commit()

        reasons = reasons_for(_facts(session, "THIN_US_EQ"), today=dt.date(2026, 1, 5))

        thin = next(reason for reason in reasons if reason.code == "missing_headlines")
        assert "revenue" in thin.detail
        assert "2025-12-31" in thin.detail

    def test_accounts_older_than_a_reporting_cycle(self, session):
        _seed(session, "OLD_US_EQ")
        _add_period(session, "OLD_US_EQ", period_end=dt.date(2023, 1, 31))
        session.commit()

        reasons = reasons_for(_facts(session, "OLD_US_EQ"), today=dt.date(2026, 1, 5))

        stale = next(reason for reason in reasons if reason.code == "stale_accounts")
        assert "2023-01-31" in stale.detail
        assert "days ago" in stale.detail

    def test_accounts_inside_the_cycle_are_not_stale(self, session):
        """The boundary has to be able to pass, or the reason means nothing."""
        _seed(session, "NEW_US_EQ")
        _add_period(session, "NEW_US_EQ", period_end=dt.date(2025, 12, 31))
        session.commit()

        codes = [r.code for r in reasons_for(_facts(session, "NEW_US_EQ"), today=dt.date(2026, 1, 5))]

        assert "stale_accounts" not in codes

    def test_a_period_that_cannot_be_traced_to_a_tag(self, session):
        _seed(session, "NOTAG_US_EQ")
        _add_period(session, "NOTAG_US_EQ", sources={})
        session.commit()

        reasons = reasons_for(_facts(session, "NOTAG_US_EQ"), today=dt.date(2026, 1, 5))

        unattributed = next(r for r in reasons if r.code == "unattributed")
        assert "2025-12-31" in unattributed.detail

    def test_a_recorded_job_failure(self, session):
        _seed(session, "BLOCKED_US_EQ")
        _add_blocker(
            session,
            "BLOCKED_US_EQ",
            job="xbrl_statements",
            stage="statements",
            reason="[edgar] HTTP 403",
            occurrences=4,
        )
        session.commit()

        reasons = reasons_for(_facts(session, "BLOCKED_US_EQ"), today=dt.date(2026, 1, 5))

        blocked = next(r for r in reasons if r.code == "blocked")
        assert "xbrl_statements" in blocked.detail
        assert "HTTP 403" in blocked.detail
        assert "4 times running" in blocked.detail

    def test_the_stage_reads_as_a_phrase_not_as_a_key(self, session):
        """The stored stage is part of a unique key, so it is a slug.

        The first live tooltip said *"fundamentals could not statements"*, which reads as
        a bug in the dashboard rather than as a fact about the company.
        """
        _seed(session, "BLOCKED_US_EQ")
        _add_blocker(session, "BLOCKED_US_EQ", stage="statements")
        session.commit()

        reasons = reasons_for(_facts(session, "BLOCKED_US_EQ"), today=dt.date(2026, 1, 5))

        detail = next(r for r in reasons if r.code == "blocked").detail
        assert "could not fetch the statements" in detail
        assert "could not statements" not in detail

    def test_an_undescribed_stage_is_still_reported(self, session):
        """A stage added by a job nobody has described here must not be dropped."""
        _seed(session, "ODDSTAGE_US_EQ")
        _add_blocker(session, "ODDSTAGE_US_EQ", stage="quantum")
        session.commit()

        reasons = reasons_for(_facts(session, "ODDSTAGE_US_EQ"), today=dt.date(2026, 1, 5))

        assert "could not quantum" in next(r for r in reasons if r.code == "blocked").detail

    def test_every_stage_a_job_writes_has_a_label(self):
        """Read out of the tree, not listed here, so a new stage cannot be added
        silently and read as a slug in a tooltip.

        Written as a scan because the alternative is a hand-maintained list of the
        stages jobs record -- which is the same second-source-of-truth problem the
        label map exists to avoid, one level up. Four of the ten stages were unwritten
        when this replaced the literal check, which is the drift it catches.
        """
        import re
        from pathlib import Path

        from awltux.analysis.attention import STAGE_LABELS

        repo = Path(__file__).resolve().parent.parent
        written = {
            match.group(1)
            for path in sorted((repo / "src").rglob("*.py"))
            for match in re.finditer(
                r'stage\s*=\s*"([a-z_]+)"', path.read_text(encoding="utf-8")
            )
        }

        assert written, "the scan found no stage at all, so it is not reading the tree"
        assert written <= set(STAGE_LABELS), (
            "a job records a blocker under a stage the attention check has no words for, "
            f"so the tooltip shows the slug: {sorted(written - set(STAGE_LABELS))}"
        )

    def test_a_resolved_blocker_does_not_count(self, session):
        """Otherwise the filter becomes a list of things that used to be broken."""
        _seed(session, "FIXED_US_EQ")
        _add_blocker(
            session,
            "FIXED_US_EQ",
            job="xbrl_statements",
            stage="statements",
            reason="[edgar] HTTP 403",
            occurrences=1,
            resolved_at=utcnow(),
        )
        session.commit()

        codes = [r.code for r in reasons_for(_facts(session, "FIXED_US_EQ"), today=dt.date(2026, 1, 5))]

        assert "blocked" not in codes


class TestTheHigherLevels:
    """What counts once the system has settled."""

    def test_a_us_listing_with_no_cik_cannot_be_covered(self, session):
        _seed(session, "NOCIK_US_EQ", sec_cik=None, exchange_name="NASDAQ")
        session.commit()

        reasons = reasons_for(_facts(session, "NOCIK_US_EQ"), today=dt.date(2026, 1, 5))

        nos = next(r for r in reasons if r.code == "no_sec_cik")
        assert nos.level == 2
        assert "EDGAR" in nos.detail

    def test_a_uk_listing_with_no_company_number(self, session):
        _seed(session, "NOCHl_EQ", ch_company_number=None, exchange_name="LSE", yahoo_symbol="NOCH.L")
        session.commit()

        reasons = reasons_for(_facts(session, "NOCHl_EQ"), today=dt.date(2026, 1, 5))

        nos = next(r for r in reasons if r.code == "no_company_number")
        assert nos.level == 2
        assert "Companies House" in nos.detail

    def test_having_the_accounts_means_the_identifier_is_not_a_blocker(self, session):
        """We already hold figures for it, so "cannot obtain" is not true of it.

        The two are the same fact with and without a cause, and saying both reads as two
        problems -- so the level-3 reason is suppressed when a structural one fires, and
        a structural one never fires when there is a period.
        """
        _seed(session, "HASCIK_US_EQ", sec_cik=None)
        _add_period(session, "HASCIK_US_EQ")
        session.commit()

        codes = [r.code for r in reasons_for(_facts(session, "HASCIK_US_EQ"), today=dt.date(2026, 1, 5))]

        assert codes == []

    def test_no_accounts_at_all_is_the_level_three_reason(self, session):
        _seed(session, "EMPTY_US_EQ", sec_cik="0000000001")
        session.commit()

        reasons = reasons_for(_facts(session, "EMPTY_US_EQ"), today=dt.date(2026, 1, 5))

        assert [r.code for r in reasons] == ["no_accounts"]
        assert reasons[0].level == 3

    def test_documents_held_that_nothing_has_read(self, session):
        _seed(session, "UNREAD_US_EQ")
        _add_period(session, "UNREAD_US_EQ")
        for index in range(3):
            session.add(
                Filing(
                    instrument_t212_ticker="UNREAD_US_EQ",
                    source="edgar",
                    filing_type="10-K",
                    url=f"https://sec.test/{index}.htm",
                    status="pending",
                )
            )
        session.commit()

        reasons = reasons_for(_facts(session, "UNREAD_US_EQ"), today=dt.date(2026, 1, 5))

        unread = next(r for r in reasons if r.code == "unparsed_documents")
        assert unread.level == 3
        assert "3 filing(s) held" in unread.detail

    def test_one_parsed_document_clears_it(self, session):
        _seed(session, "READ_US_EQ")
        _add_period(session, "READ_US_EQ")
        session.add(
            Filing(
                instrument_t212_ticker="READ_US_EQ",
                source="edgar",
                filing_type="10-K",
                url="https://sec.test/read.htm",
                status="fetched",
            )
        )
        session.add(
            Filing(
                instrument_t212_ticker="READ_US_EQ",
                source="edgar",
                filing_type="10-Q",
                url="https://sec.test/pending.htm",
                status="pending",
            )
        )
        session.commit()

        codes = [r.code for r in reasons_for(_facts(session, "READ_US_EQ"), today=dt.date(2026, 1, 5))]

        assert "unparsed_documents" not in codes


class TestTheDeepDiveConflict:
    """The one place two *judgements* about a company disagree in public.

    The deep-dive read the annual reports and the appraised news; the engine read the
    deterministic valuation and the figures. Neither is a measurement, so neither wins --
    what the reader gets is the disagreement, at level 3, which is the rung for a reason
    that is rare and worth a look rather than common and worth a filter.
    """

    def _decision(self, session, ticker: str, action: str | None) -> None:
        from awltux.db import DecisionRun

        session.add(
            DecisionRun(
                instrument_t212_ticker=ticker,
                created_at=utcnow(),
                state={},
                state_sha256="x",
                engine="offline",
                answers={},
                long_term_action=action,
                gate_allowed=False,
            )
        )
        session.flush()

    def _report(self, session, ticker: str, verdict: str | None, *, status: str = "done") -> None:
        from awltux.db import ResearchReport

        session.add(
            ResearchReport(
                subject_type="instrument",
                subject_id=ticker,
                status=status,
                title=ticker,
                prompt="x",
                prompt_sha256="x",
                verdict=verdict,
                created_at=utcnow(),
            )
        )
        session.flush()

    def test_a_directional_disagreement_is_reported(self, session):
        _seed(session, "CLASH_US_EQ")
        _add_period(session, "CLASH_US_EQ")
        self._decision(session, "CLASH_US_EQ", "avoid")
        self._report(session, "CLASH_US_EQ", "attractive")
        session.commit()

        reason = next(
            r for r in reasons_for(_facts(session, "CLASH_US_EQ"), today=dt.date(2026, 1, 5))
            if r.code == "research_conflict"
        )

        assert reason.level == 3
        assert "attractive" in reason.detail and "avoid" in reason.detail
        assert "neither is a measurement" in reason.detail

    def test_each_direction_of_disagreement_fires(self, session):
        _seed(session, "CLASH2_US_EQ")
        _add_period(session, "CLASH2_US_EQ")
        self._decision(session, "CLASH2_US_EQ", "buy")
        self._report(session, "CLASH2_US_EQ", "unattractive")
        session.commit()

        assert "research_conflict" in _codes(session, "CLASH2_US_EQ")

    def test_watching_is_not_a_conflict(self, session):
        """`watch` and `insufficient_evidence` contradict nothing: "this needs watching"
        agrees with a hold and with a reduce, and treating "no conclusion" as a conflict
        with every action would put most of the table into the level-3 filter."""
        for index, verdict in enumerate(("watch", "insufficient_evidence")):
            ticker = f"WATCH{index}_US_EQ"
            _seed(session, ticker)
            _add_period(session, ticker)
            self._decision(session, ticker, "hold")
            self._report(session, ticker, verdict)
        session.commit()

        assert "research_conflict" not in _codes(session, "WATCH0_US_EQ")
        assert "research_conflict" not in _codes(session, "WATCH1_US_EQ")

    def test_agreement_is_not_a_conflict(self, session):
        _seed(session, "AGREE_US_EQ")
        _add_period(session, "AGREE_US_EQ")
        self._decision(session, "AGREE_US_EQ", "buy")
        self._report(session, "AGREE_US_EQ", "attractive")
        session.commit()

        assert "research_conflict" not in _codes(session, "AGREE_US_EQ")

    def test_one_side_alone_is_not_a_conflict(self, session):
        """Nothing here says which is right, so a verdict with no decision to disagree with
        is not a finding."""
        _seed(session, "ONLY_US_EQ")
        _add_period(session, "ONLY_US_EQ")
        self._report(session, "ONLY_US_EQ", "attractive")
        session.commit()

        assert "research_conflict" not in _codes(session, "ONLY_US_EQ")

    def test_a_failed_or_running_report_is_not_a_verdict(self, session):
        """Only a finished report is an answer. A run that failed left its verdict null
        anyway, and one still going has none to read."""
        _seed(session, "RUNNING_US_EQ")
        _add_period(session, "RUNNING_US_EQ")
        self._decision(session, "RUNNING_US_EQ", "avoid")
        self._report(session, "RUNNING_US_EQ", "attractive", status="running")
        session.commit()

        assert "research_conflict" not in _codes(session, "RUNNING_US_EQ")


class TestTheReasonsAreUsableText:
    def test_every_reason_has_a_label_and_names_what_it_measured(self, session):
        """A reason without a detail is a verdict, and a verdict is not a finding."""
        _seed(session, "MANY_US_EQ", sec_cik=None)
        _add_period(
            session,
            "MANY_US_EQ",
            period_end=dt.date(2023, 1, 31),
            metrics={"total_assets": 900_000.0},
            sources={},
        )
        session.commit()

        reasons = reasons_for(_facts(session, "MANY_US_EQ"), today=dt.date(2026, 1, 5))

        assert len(reasons) >= 3
        for reason in reasons:
            assert reason.label and reason.label[0].isupper()
            assert reason.detail, f"{reason.code} states no evidence"
            assert 1 <= reason.level <= attention.MAX_LEVEL

    def test_the_summary_names_every_reason(self, session):
        found = assess(session, level=1)

        assert found == {}

    def test_a_ticker_filter_narrows_the_work(self, session, settings):
        _seed(session, "ONE_US_EQ")
        _seed(session, "TWO_US_EQ")
        session.commit()

        found = assess(session, tickers=["ONE_US_EQ"], level=1, settings=settings)

        assert set(found) == {"ONE_US_EQ"}

    def test_an_empty_ticker_list_asks_nothing(self, session, settings):
        _seed(session, "ONE_US_EQ")
        session.commit()

        assert assess(session, tickers=[], level=1, settings=settings) == {}
