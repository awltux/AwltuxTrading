"""The comparison page: several instruments in one request.

Asked for as the answer to *"multiple windows for 10 or so instruments"* — ten tabs was how a
reader compared names, and ten tabs is what made the interface crawl before the web tier had
workers. The rows come from `queries.recommendations(tickers=...)`, so this page and the
recommendations table cannot disagree about what the engine said.

What these tests pin, and why each one: the **order** is part of the question (a comparison that
reorders itself is a different answer), an **unknown name is reported** rather than silently
dropped (a comparison missing a company reads as one that company was not in), and the **cap**
counts what it left out instead of truncating.
"""

from __future__ import annotations

import datetime as dt

from awltux.web.routes.dashboard import MAX_COMPARE, _compare_set
from tests.helpers import make_bars, make_instrument


def _instrument(session, ticker: str, *, close: float | None = None) -> None:
    session.add(make_instrument(ticker, name=f"{ticker} Holdings", isin=f"ISIN{ticker}"))
    session.flush()
    if close is not None:
        session.add_all(
            make_bars(ticker, [close - 1.0, close], start=dt.date.today() - dt.timedelta(days=3))
        )
        session.flush()


class TestReadingTheSet:
    def test_commas_and_spaces_both_separate_names(self):
        assert _compare_set(" DAC_US_EQ,GWW_US_EQ  MSFT_US_EQ ") == (
            ["DAC_US_EQ", "GWW_US_EQ", "MSFT_US_EQ"],
            0,
        )

    def test_case_does_not_matter_and_order_is_kept(self):
        assert _compare_set("gww_us_eq,dac_us_eq") == (["GWW_US_EQ", "DAC_US_EQ"], 0)

    def test_a_repeated_name_is_compared_once(self):
        assert _compare_set("DAC_US_EQ,DAC_US_EQ,dac_us_eq") == (["DAC_US_EQ"], 0)

    def test_the_cap_counts_what_it_dropped_rather_than_truncating_silently(self):
        names = ",".join(f"T{index}_US_EQ" for index in range(MAX_COMPARE + 3))

        wanted, overflow = _compare_set(names)

        assert len(wanted) == MAX_COMPARE
        assert overflow == 3


class TestThePage:
    def test_it_compares_the_names_given(self, client, session):
        _instrument(session, "DAC_US_EQ", close=158.0)
        _instrument(session, "GWW_US_EQ", close=1331.0)
        session.commit()

        body = client.get("/compare?tickers=DAC_US_EQ,GWW_US_EQ").text

        assert "DAC_US_EQ" in body and "GWW_US_EQ" in body
        # `number` puts thousands separators in, so the figure is what the page shows.
        assert "158.00" in body and "1,331.00" in body

    def test_it_keeps_the_order_it_was_given(self, client, session):
        """A comparison that reorders itself is a different answer to the question asked."""
        _instrument(session, "AAA_US_EQ", close=10.0)
        _instrument(session, "ZZZ_US_EQ", close=20.0)
        session.commit()

        body = client.get("/compare?tickers=ZZZ_US_EQ,AAA_US_EQ").text

        assert body.index("ZZZ_US_EQ") < body.index("AAA_US_EQ")

    def test_an_unknown_name_is_reported_and_the_rest_still_shown(self, client, session):
        _instrument(session, "DAC_US_EQ", close=158.0)
        session.commit()

        body = client.get("/compare?tickers=DAC_US_EQ,NOPE_US_EQ").text

        assert "No instrument in the analysed universe is called" in body
        assert "NOPE_US_EQ" in body
        assert "158.00" in body, "the name that does exist is still compared"

    def test_a_name_outside_the_universe_is_treated_as_unknown(self, client, session):
        """The comparison reads the same scope the table does, so it cannot show a row the
        table would refuse to list."""
        _instrument(session, "DAC_US_EQ", close=158.0)
        session.add(
            make_instrument("OUT_US_EQ", name="Outside", isin="ISINOUT", in_universe=False)
        )
        session.commit()

        body = client.get("/compare?tickers=OUT_US_EQ").text

        assert "No instrument in the analysed universe is called" in body

    def test_no_names_shows_the_form_and_an_invitation(self, client):
        body = client.get("/compare").text

        assert 'name="tickers"' in body
        assert "Give one or more tickers above to compare them" in body

    def test_too_many_names_are_capped_and_said_so(self, client, session):
        for index in range(MAX_COMPARE + 2):
            _instrument(session, f"T{index:02d}_US_EQ", close=10.0 + index)
        session.commit()

        names = ",".join(f"T{index:02d}_US_EQ" for index in range(MAX_COMPARE + 2))
        body = client.get(f"/compare?tickers={names}").text

        assert "2 more names were given than this page compares at once" in body
        shown = sum(1 for index in range(MAX_COMPARE + 2) if f"T{index:02d}_US_EQ" in body)
        # The first twelve are in the table; the last two appear only in the input's value.
        assert body.count("<tr class=") == MAX_COMPARE
        assert shown >= MAX_COMPARE

    def test_removing_a_name_keeps_the_others_in_order(self, client, session):
        """The remove link is built from the rows, not from the raw query string."""
        _instrument(session, "AAA_US_EQ", close=10.0)
        _instrument(session, "BBB_US_EQ", close=20.0)
        _instrument(session, "CCC_US_EQ", close=30.0)
        session.commit()

        body = client.get("/compare?tickers=AAA_US_EQ,BBB_US_EQ,CCC_US_EQ").text

        assert "tickers=AAA_US_EQ%2CBBB_US_EQ" in body, "removing CCC keeps A and B, in order"
