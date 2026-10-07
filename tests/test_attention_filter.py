"""The "Needs attention" checkbox: the control, the URL, and what it selects.

The filter system declares a filter once and derives the control, the querystring and
the chips from it, so most of this is about the one new *kind* of control. A checkbox is
not a two-option dropdown because the parse rule differs: a URL that says
``?attention=0`` or ``?attention=banana`` is neither "on" nor a value the control can
produce, and reading either as "on" would show a filtered table the address bar did not
ask for -- the failure mode `web/filters.py` exists to prevent, and the reason the
ignored-value banner is asserted here rather than assumed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux.db import FundamentalPeriod, InstrumentBlocker, utcnow
from awltux.web import filters, queries
from tests.helpers import make_instrument


def _flags() -> filters.FilterSpec:
    return next(
        spec for spec in filters.recommendation_specs() if spec.name == "attention"
    )


def _seed(session, ticker: str, **overrides):
    overrides.setdefault("sec_cik", "0000000001")
    session.add(make_instrument(ticker, **overrides))
    session.flush()


def _period(session, ticker: str, metrics: dict | None = None) -> None:
    session.add(
        FundamentalPeriod(
            instrument_t212_ticker=ticker,
            period_end=dt.date(2025, 12, 31),
            period_type="annual",
            source="xbrl_companyfacts",
            currency="USD",
            metrics=metrics
            or {"revenue": 1_000_000.0, "total_assets": 5_000_000.0},
            metric_sources={"revenue": {"span": "us-gaap:Revenues"}},
        )
    )


class TestTheDeclaration:
    def test_it_is_a_flag(self):
        assert _flags().kind == "flag"

    def test_it_is_off_by_default(self):
        assert _flags().default == ""

    def test_it_gets_a_chip(self):
        """"Which filters are applied" is exactly the question a chip answers."""
        assert _flags().chip is True

    def test_it_explains_where_its_strictness_comes_from(self):
        """The reader has to be able to find out that the threshold is configurable."""
        assert "attention_level" in _flags().help


class TestParsing:
    def _parse(self, **params: str) -> filters.FilterSet:
        return filters.FilterSet.parse(filters.recommendation_specs(), params)

    def test_absent_means_off(self):
        assert self._parse().given("attention") is False

    def test_one_means_on(self):
        assert self._parse(attention="1").given("attention") is True

    def test_an_empty_value_means_off(self):
        assert self._parse(attention="").given("attention") is False

    @pytest.mark.parametrize("value", ["0", "false", "no", "banana", "2"])
    def test_anything_else_is_refused_and_reported(self, value):
        """Not coerced. A truthiness test reads `0` and `banana` as on, and the table
        would then be filtered by a URL that never asked for it."""
        spec = self._parse(attention=value)

        assert spec.given("attention") is False
        assert [bad.name for bad in spec.ignored] == ["attention"]

    def test_the_url_keeps_it_when_set_and_drops_it_when_not(self):
        assert self._parse(attention="1").query() == "?attention=1"
        assert self._parse().query() == ""

    def test_it_survives_a_link_that_changes_something_else(self):
        """Otherwise clicking a column header silently clears the filter."""
        assert self._parse(attention="1").query(sort="name") == "?attention=1&sort=name"

    def test_it_is_carried_as_a_hidden_field_by_the_form(self):
        """A `flag` control renders its own input, but the *state* still has to travel:
        the spec must not appear in `hidden` or the form would post it twice."""
        spec = self._parse(attention="1")

        assert "attention" not in {item.name for item in spec.hidden}

    def test_clearing_it_produces_a_link_without_it(self):
        spec = self._parse(attention="1")

        assert spec.query(attention=None) == ""


class TestThePage:
    def test_the_checkbox_is_rendered(self, client, session):
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        body = client.get("/dashboard").text

        assert 'type="checkbox" name="attention"' in body
        assert "Needs attention" in body

    def test_it_is_checked_when_set(self, client, session):
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        body = client.get("/dashboard?attention=1").text

        assert 'name="attention" value="1"\n                 checked' in body.replace(
            "\r\n", "\n"
        )

    def test_it_selects_only_the_flagged_instruments(self, client, session):
        _seed(session, "ODD_US_EQ")
        _seed(session, "FINE_US_EQ")
        _period(
            session,
            "ODD_US_EQ",
            metrics={
                "revenue": 1.0,
                "total_assets": 900_000.0,
                "total_liabilities": 400_000.0,
                "total_equity": 100_000.0,
            },
        )
        _period(session, "FINE_US_EQ")
        session.commit()

        body = client.get("/dashboard?attention=1").text

        assert "ODD_US_EQ" in body
        assert "FINE_US_EQ" not in body

    def test_the_row_says_how_many_issues_and_why(self, client, session):
        """A bare count would be the verdict this codebase refuses to render; the
        reasons travel in the tooltip and each names what it measured."""
        _seed(session, "ODD_US_EQ")
        _period(
            session,
            "ODD_US_EQ",
            metrics={
                "revenue": 1.0,
                "total_assets": 900_000.0,
                "total_liabilities": 400_000.0,
                "total_equity": 100_000.0,
            },
        )
        session.commit()

        body = client.get("/dashboard").text

        assert "issue" in body
        assert "Balance sheet does not balance" in body

    def test_a_bad_value_is_reported_rather_than_guessed(self, client, session):
        _seed(session, "CLEAN_US_EQ")
        session.commit()

        body = client.get("/dashboard?attention=banana")

        assert body.status_code == 200
        assert "attention=banana" in body.text
        assert "did not recognise" in body.text

    def test_the_filter_is_off_unless_it_is_asked_for(self, client, session):
        """The default has to be the unfiltered table.

        A reader who has never heard of this filter must not lose rows to it, which is
        what an "on by default" checkbox would do -- and the rows it would hide are
        exactly the trustworthy ones.
        """
        _seed(session, "FINE_US_EQ")
        _period(session, "FINE_US_EQ")
        session.commit()

        assert "FINE_US_EQ" in client.get("/dashboard").text
        # And when asked for, a clean instrument is not a match: that is the filter
        # working, not failing.
        assert "FINE_US_EQ" not in client.get("/dashboard?attention=1").text

    def test_it_combines_with_another_filter(self, client, session):
        _seed(session, "ODD_US_EQ", sector="Drugs")
        _seed(session, "OIL_US_EQ", sector="Oil")
        for ticker in ("ODD_US_EQ", "OIL_US_EQ"):
            _period(
                session,
                ticker,
                metrics={
                    "revenue": 1.0,
                    "total_assets": 900_000.0,
                    "total_liabilities": 400_000.0,
                    "total_equity": 100_000.0,
                },
            )
        session.commit()

        body = client.get("/dashboard?attention=1&sector=Drugs").text

        assert "ODD_US_EQ" in body
        assert "OIL_US_EQ" not in body


class TestTheQueryLayer:
    def test_attention_can_be_filtered_without_the_route(self, session, settings):
        _seed(session, "ODD_US_EQ")
        _seed(session, "FINE_US_EQ")
        _period(
            session,
            "ODD_US_EQ",
            metrics={
                "revenue": 1.0,
                "total_assets": 900_000.0,
                "total_liabilities": 400_000.0,
                "total_equity": 100_000.0,
            },
        )
        _period(session, "FINE_US_EQ")
        session.commit()

        rows, total = queries.recommendations(session, needs_attention=True)

        assert total == 1
        assert rows[0].ticker == "ODD_US_EQ"
        assert rows[0].attention_count >= 1

    def test_rows_carry_their_reasons_even_when_not_filtering(self, session):
        """So a reader can see why a row is suspect without switching the filter on
        to find out."""
        _seed(session, "ODD_US_EQ")
        _period(
            session,
            "ODD_US_EQ",
            metrics={
                "revenue": 1.0,
                "total_assets": 900_000.0,
                "total_liabilities": 400_000.0,
                "total_equity": 100_000.0,
            },
        )
        session.commit()

        rows, _ = queries.recommendations(session)

        assert rows[0].attention_count >= 1
        assert "Balance sheet does not balance" in rows[0].attention_summary

    def test_a_clean_row_has_no_reasons(self, session):
        _seed(session, "FINE_US_EQ")
        _period(session, "FINE_US_EQ")
        session.commit()

        rows, _ = queries.recommendations(session)

        assert rows[0].attention == ()
        assert rows[0].attention_summary == ""

    def test_a_blocker_surfaces_on_the_row(self, session):
        _seed(session, "BLOCKED_US_EQ")
        session.add(
            InstrumentBlocker(
                instrument_t212_ticker="BLOCKED_US_EQ",
                job="xbrl_statements",
                stage="statements",
                reason="[edgar] HTTP 403",
                first_seen_at=utcnow(),
                last_seen_at=utcnow(),
                occurrences=2,
            )
        )
        session.commit()

        rows, _ = queries.recommendations(session)

        assert "A job cannot proceed" in rows[0].attention_summary
        assert "HTTP 403" in rows[0].attention_summary
