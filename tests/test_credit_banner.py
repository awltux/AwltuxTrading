"""The credit banner: what it says, and what it refuses to say.

Everything here is about the difference between **"there is no money"** and **"we cannot
see the money"**, because conflating them is the only way this feature can do harm:
a banner that tells someone their account is empty when it is merely unreadable is a
banner that gets ignored on the day it is right.

The other half is that it must be *silent* when nothing is wrong. A bar that is up on
every page is one nobody reads, so an unreadable balance -- which is the normal state for
fal without an Admin-scope key -- is stated in the strip and does not raise a warning.
"""

from __future__ import annotations

import datetime as dt

from awltux.db import LLMCall, utcnow
from awltux.providers import balances
from awltux.web import queries


def _store(session, *rows):
    balances.store(session, list(rows))
    session.commit()


def _call(session, *, provider: str, error: str | None, ok: bool, cost: float | None = 0.01):
    session.add(
        LLMCall(
            provider=provider,
            purpose="test",
            ok=ok,
            error=error,
            cost_usd=cost,
            created_at=utcnow(),
        )
    )
    session.commit()


def _row(status: dict, provider: str) -> dict:
    """One provider's line out of `provider_status`."""
    return next(row for row in status["balances"] if row["provider"] == provider)


class TestWhatItReports:
    def test_a_balance_is_shown_with_its_currency(self, session, settings):
        _store(session, balances.Balance("deepseek", available=True, amount=21.68, currency="USD"))

        status = queries.provider_status(session, settings=settings)

        deepseek = next(row for row in status["balances"] if row["provider"] == "deepseek")
        assert deepseek["amount"] == 21.68
        assert deepseek["currency"] == "USD"
        assert status["readable"] is True

    def test_the_strip_names_the_key_a_reading_was_taken_with(self, client, session, settings):
        """Because the balance is the account's, the key name is the only scoping there is.

        Asked for directly: *"the DeepSeek costs are for all keys ... it would be
        preferable if it showed just for this key."* It cannot show only this key -- the
        endpoint reports the account -- so it says which key it was read with and the
        tooltip says what the figure covers.
        """
        _store(
            session,
            balances.Balance(
                "deepseek",
                available=True,
                amount=21.68,
                currency="USD",
                note=balances.DEEPSEEK_BALANCE_SCOPE,
                key_name="awltux",
            ),
        )

        body = " ".join(client.get("/dashboard").text.split())

        assert "deepseek" in body
        assert "awltux" in body, "the key name is on the strip"
        assert "whole DeepSeek account" in body, "and the scope is in the tooltip"

    def test_an_unnamed_key_puts_nothing_extra_on_the_strip(self, client, session, settings):
        """A placeholder word would be noise; the absence of a name says it."""
        _store(
            session, balances.Balance("deepseek", available=True, amount=21.68, currency="USD")
        )

        body = " ".join(client.get("/dashboard").text.split())

        assert "unnamed" not in body
        assert "None" not in body

    def test_fal_gets_an_estimate_from_its_own_balance_going_down(self, client, session, settings):
        """The route suggested for fal, whose spend no ledger records.

        `llm_call` is written by `llm/deepseek.py` alone, so fal has no logged spend at all
        -- and its billing endpoint refuses a model key. The provider's own balance is the
        only evidence there is, so two readings are differenced and the result is labelled
        as the floor it is.
        """
        for amount, hours in ((11.10, 20), (9.60, 10), (8.10, 1)):
            _store(
                session,
                balances.Balance(
                    "fal",
                    amount=amount,
                    currency="USD",
                    read_at=utcnow() - dt.timedelta(hours=hours),
                ),
            )

        status = queries.provider_status(session, settings=settings)

        fal = next(row for row in status["balances"] if row["provider"] == "fal")
        assert fal["spent"] == 3.0
        assert fal["spent_source"] == "balance_delta"
        assert "floor" in fal["note"], "the tooltip says why the figure is a minimum"

        body = " ".join(client.get("/dashboard").text.split())
        assert "~3.00 USD spent / 30d" in body, "and the strip marks it approximate"

    def test_a_logged_provider_does_not_use_the_estimate(self, session, settings):
        """The ledger is a count of what happened; a balance difference is an inference.

        Both are available for DeepSeek here, and showing the estimate would replace a
        measured figure with a weaker one.
        """
        _store(
            session,
            balances.Balance("deepseek", amount=20.0, currency="USD", read_at=utcnow()),
        )
        session.add(
            LLMCall(
                provider="deepseek",
                purpose="test",
                ok=True,
                cost_usd=2.5,
                created_at=utcnow(),
            )
        )
        session.commit()

        status = queries.provider_status(session, settings=settings)

        deepseek = next(row for row in status["balances"] if row["provider"] == "deepseek")
        assert deepseek["spent"] == 2.5
        assert deepseek["spent_source"] == "ledger"

    def test_one_reading_is_not_an_estimate(self, session, settings):
        _store(session, balances.Balance("fal", amount=11.10, currency="USD", read_at=utcnow()))

        status = queries.provider_status(session, settings=settings)

        fal = next(row for row in status["balances"] if row["provider"] == "fal")
        assert fal["spent"] is None
        assert fal["spent_source"] is None

    def test_readings_too_close_together_do_not_produce_a_figure(self, session, settings):
        """A one-minute estimate would be printed under a "/ 30d" label it has not earned."""
        for amount, minutes in ((11.10, 2), (10.10, 1)):
            _store(
                session,
                balances.Balance(
                    "fal",
                    amount=amount,
                    currency="USD",
                    read_at=utcnow() - dt.timedelta(minutes=minutes),
                ),
            )

        status = queries.provider_status(session, settings=settings)

        fal = next(row for row in status["balances"] if row["provider"] == "fal")
        assert fal["spent"] is None
        assert fal["spent_source"] is None

    def test_a_stored_reading_from_a_future_build_still_reads(self, session, settings):
        """The series is append-only across releases; an old row must not break the page."""
        _store(session, balances.Balance("fal", amount=11.10, currency="USD"))

        status = queries.provider_status(session, settings=settings)

        assert status["readable"] is True

    def test_an_unreadable_provider_is_not_a_warning(self, session, settings):
        """fal without an Admin key answers 403 -- which is the state this project was in
        for its whole life. A warning here would have been permanently on."""
        _store(session, balances.Balance("fal", note="the key is not permitted"))

        status = queries.provider_status(session, settings=settings)

        assert status["warnings"] == []
        fal = next(row for row in status["balances"] if row["provider"] == "fal")
        assert fal["note"]
        assert fal["amount"] is None

    def test_below_the_floor_warns_and_says_the_figure(self, session, settings):
        settings.yaml.app.balance_warn_below_usd = 5.0
        _store(session, balances.Balance("fal", amount=1.10, currency="USD"))

        status = queries.provider_status(session, settings=settings)

        assert len(status["warnings"]) == 1
        assert "fal" in status["warnings"][0]
        assert "1.10" in status["warnings"][0]
        assert "5.00" in status["warnings"][0]

    def test_above_the_floor_is_silent(self, session, settings):
        settings.yaml.app.balance_warn_below_usd = 5.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))

        assert queries.provider_status(session, settings=settings)["warnings"] == []

    def test_a_provider_that_cannot_pay_warns_whatever_the_amount(self, session, settings):
        """`is_available: false` is the provider's own statement, and it outranks any
        number beside it."""
        _store(session, balances.Balance("deepseek", available=False, amount=12.0, currency="USD"))

        warnings = queries.provider_status(session, settings=settings)["warnings"]

        assert any("cannot pay" in warning for warning in warnings)

    def test_a_zero_floor_announces_only_a_provider_that_cannot_pay(self, session, settings):
        settings.yaml.app.balance_warn_below_usd = 0.0
        _store(session, balances.Balance("deepseek", amount=0.01, currency="USD"))

        assert queries.provider_status(session, settings=settings)["warnings"] == []


class TestWhatOurOwnCallsShow:
    def test_spend_is_totalled_per_provider(self, session, settings):
        _store(session, balances.Balance("deepseek", amount=21.0, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=0.25)
        _call(session, provider="deepseek", error=None, ok=True, cost=0.75)

        status = queries.provider_status(session, settings=settings)

        deepseek = next(row for row in status["balances"] if row["provider"] == "deepseek")
        assert deepseek["spent"] == 1.0
        assert deepseek["calls"] == 2

    def test_a_payment_failure_is_reported_the_moment_it_happens(self, session, settings):
        """This is the signal that works for a provider we cannot ask -- and it arrives
        at the call rather than at the next hourly probe."""
        _store(session, balances.Balance("deepseek", amount=21.0, currency="USD"))
        _call(session, provider="deepseek", error="HTTP 402: Insufficient Balance", ok=False)

        status = queries.provider_status(session, settings=settings)

        assert any("refused a call for payment" in warning for warning in status["warnings"])
        deepseek = next(row for row in status["balances"] if row["provider"] == "deepseek")
        assert "Insufficient Balance" in deepseek["payment_failure"]

    def test_an_entitlement_refusal_is_not_a_payment_failure(self, session, settings):
        """The embeddings refusal names an organization and is a *scope* problem. Showing
        "top up your account" for it would be wrong and would train the reader to
        distrust the bar."""
        _store(session, balances.Balance("deepseek", amount=21.0, currency="USD"))
        _call(
            session,
            provider="deepseek",
            error="HTTP 401: You do not have access to the organization tied to the API key.",
            ok=False,
        )

        status = queries.provider_status(session, settings=settings)

        assert status["warnings"] == []

    def test_an_old_failure_is_not_reported_for_ever(self, session, settings):
        """It is a statement about *now*: a 402 from last month is history, and the
        provider's own balance is the authority on whether it is still true."""
        _store(session, balances.Balance("deepseek", amount=21.0, currency="USD"))
        session.add(
            LLMCall(
                provider="deepseek",
                purpose="test",
                ok=False,
                error="HTTP 402: Insufficient Balance",
                created_at=utcnow() - dt.timedelta(days=30),
            )
        )
        session.commit()

        assert queries.provider_status(session, settings=settings)["warnings"] == []


class TestTheAppsOwnCeiling:
    """The ceiling is ours, and nothing else on the page could report it.

    `llm.monthly_budget_usd` is checked before every DeepSeek call, so at the ceiling that
    client refuses to make the call at all. The provider is untouched, its balance endpoint
    still reports money, and the refusal happens before the request so it writes no
    `llm_call` row either -- every signal the strip had was about the *provider* paying or
    being unreachable, and this is neither.

    Reported 2026-10-15: refusals kept arriving and the header said nothing was wrong.
    """

    def test_spend_at_the_ceiling_is_flagged_and_names_whose_limit_it_is(self, session, settings):
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["over_budget"] is True
        assert row["budget_usd"] == 1.0
        # The one reading that must not be available: a reader who thinks the provider cut
        # the account off goes and checks an account that is fine.
        assert "not blocked anything" in row["budget_note"]
        assert "not an outage" in row["budget_note"]
        assert "monthly_budget_usd" in row["budget_note"]

    def test_spend_below_the_ceiling_is_not_flagged(self, session, settings):
        settings.yaml.llm.monthly_budget_usd = 40.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["over_budget"] is False
        assert row["budget_note"] is None

    def test_spend_close_to_the_ceiling_warns_before_anything_is_refused(self, session, settings):
        """Before the cutoff, because at the cutoff it is already too late: the refusal has
        happened, every model-backed job is on its deterministic fallback, and the run that
        wanted a judgement did not get one. The warning is only worth anything while there is
        still a decision to make -- the same argument the provider balance floor makes."""
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=0.96)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["near_budget"] is True
        assert row["over_budget"] is False
        assert "Nothing is refused yet" in row["budget_note"]

    def test_spend_far_below_the_ceiling_is_quiet(self, session, settings):
        """The strip is silent when nothing is wrong, or it is a strip nobody reads."""
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=0.50)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["near_budget"] is False
        assert row["over_budget"] is False
        assert row["budget_note"] is None

    def test_the_two_states_do_not_both_apply(self, session, settings):
        """Red is the stronger claim, and a figure cannot be both."""
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["over_budget"] is True
        assert row["near_budget"] is False

    def test_a_call_that_failed_does_not_spend_the_ceiling(self, session, settings):
        """The rule `_check_budget` applies: a call that errored cost nothing, and counting
        it would spend the ceiling twice."""
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error="boom", ok=False, cost=5.00)

        assert _row(queries.provider_status(session, settings=settings), "deepseek")[
            "over_budget"
        ] is False

    def test_a_provider_with_no_ceiling_is_not_flagged_by_one(self, session, settings):
        """The ceiling is checked for one client. Putting the badge on a provider it does
        not govern would name the wrong cause, which is the whole failure being fixed."""
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(
            session,
            balances.Balance("deepseek", amount=21.68, currency="USD"),
            balances.Balance("fal", amount=11.10, currency="USD"),
        )
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        fal = _row(queries.provider_status(session, settings=settings), "fal")

        assert fal["over_budget"] is False
        assert fal["budget_usd"] is None

    def test_a_ceiling_of_zero_is_no_ceiling(self, session, settings):
        """`_check_budget` returns immediately at zero, so nothing is being refused."""
        settings.yaml.llm.monthly_budget_usd = 0.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=99.00)

        row = _row(queries.provider_status(session, settings=settings), "deepseek")

        assert row["over_budget"] is False
        assert row["budget_usd"] is None


class TestBeforeItHasEverRun:
    def test_nothing_stored_names_both_providers_and_says_why(self, session, settings):
        """The job runs on start, so this is the first seconds of a fresh container --
        and saying so beats an empty strip that reads as "all fine"."""
        status = queries.provider_status(session, settings=settings)

        assert {row["provider"] for row in status["balances"]} == {"deepseek", "fal"}
        assert all("no reading yet" in (row["note"] or "") for row in status["balances"])
        assert status["readable"] is False
        assert status["warnings"] == [], "not knowing is not a warning"


class TestTheBannerOnAPage:
    def test_it_shows_a_balance(self, client, session, settings):
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))

        body = client.get("/dashboard").text

        assert "status-banner" in body
        assert "deepseek" in body
        assert "21.68" in body

    def test_a_low_balance_is_outlined_rather_than_described(self, client, session, settings):
        """The figure itself carries the warning.

        This replaced a sentence above the strip naming the provider, the figure and the
        floor -- accurate, and a paragraph on every page to say one word. What has to
        survive is that the reader can still tell *which* provider is short, so the
        assertion is on the class being on fal's chip and not on deepseek's.
        """
        settings.yaml.app.balance_warn_below_usd = 5.0
        _store(
            session,
            balances.Balance("deepseek", amount=21.68, currency="USD"),
            balances.Balance("fal", amount=1.10, currency="USD"),
        )

        body = client.get("/dashboard").text

        assert "balance low" in body
        assert "1.10" in body
        assert "Model provider credit" not in body, "the prose is gone"
        low = body.split("balance low", 1)[1].split("</span>", 1)[0]
        assert "fal" in low and "deepseek" not in low, "the outline is on the short one"

    def test_a_spent_ceiling_is_a_red_figure_that_says_whose_limit_it_is(self, client, session, settings):
        """The badge and the tooltip, on the page.

        Red rather than amber because the reader's next action is different from the one a
        low balance asks for: nothing needs topping up, a number in `config.yaml` needs
        changing. The tooltip is what stops the provider's name beside a red figure reading
        as "they cut us off".
        """
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        body = client.get("/dashboard").text

        assert "spent / 30d" in body
        # The tooltip exists only on the over-budget path, so locating the badge as the span
        # that precedes the spend figure is the assertion that it landed on *that* figure
        # rather than on something else red on the page.
        before = body.split("spent / 30d", 1)[0]
        assert 'class="bad"' in before[before.rindex("<span") :]
        assert "not an outage" in body
        assert "monthly_budget_usd" in body

    def test_a_healthy_ceiling_leaves_the_strip_unalarmed(self, client, session, settings):
        settings.yaml.llm.monthly_budget_usd = 40.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=1.25)

        body = client.get("/dashboard").text

        assert "not an outage" not in body
        assert "Nothing is refused yet" not in body

    def test_a_ceiling_that_is_nearly_spent_is_amber_before_it_is_red(self, client, session, settings):
        settings.yaml.llm.monthly_budget_usd = 1.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))
        _call(session, provider="deepseek", error=None, ok=True, cost=0.96)

        body = client.get("/dashboard").text

        before = body.split("spent / 30d", 1)[0]
        assert 'class="warn"' in before[before.rindex("<span") :]
        assert "Nothing is refused yet" in body

    def test_a_full_balance_is_not_outlined(self, client, session, settings):
        settings.yaml.app.balance_warn_below_usd = 5.0
        _store(
            session,
            balances.Balance("deepseek", amount=21.68, currency="USD"),
            balances.Balance("fal", amount=1.10, currency="USD"),
        )

        deepseek = client.get("/dashboard").text.split("balance low", 1)[0]
        assert "21.68" in deepseek, "the threshold is per provider, not per banner"

    def test_it_says_nothing_alarming_when_nothing_is_wrong(self, client, session, settings):
        settings.yaml.app.balance_warn_below_usd = 5.0
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))

        body = client.get("/dashboard").text

        assert "status-banner" in body
        assert "Model provider credit" not in body
        assert "balance low" not in body

    def test_it_is_on_every_page(self, client, session, settings):
        """Not only the dashboard: the failure it reports is invisible from *any* page,
        which is why it is a global rather than part of a route's context."""
        _store(session, balances.Balance("fal", amount=1.10, currency="USD"))
        settings.yaml.app.balance_warn_below_usd = 5.0

        for path in ("/dashboard", "/jobs", "/info", "/calibration"):
            assert "status-banner" in client.get(path).text, path


class TestRefreshingIt:
    """Clicking the strip re-reads the balances.

    This spends provider calls, so the two things worth asserting are that it is a POST
    -- a GET would be followed by any prefetcher that saw the URL -- and that the page it
    returns to is one on this site rather than whatever `next` said.
    """

    def test_the_strip_is_a_post_form(self, client, session, settings):
        _store(session, balances.Balance("deepseek", amount=21.68, currency="USD"))

        body = client.get("/dashboard").text

        assert 'method="post"' in body
        assert "/credit/refresh" in body
        assert "<button" in body, "the strip itself is the control"

    def test_a_get_is_not_allowed(self, client, session, settings):
        """The route is a POST and only a POST, so a crawler cannot spend the calls."""
        assert client.get("/credit/refresh").status_code == 405

    def test_it_stores_a_fresh_reading_and_returns_to_the_same_page(self, client, session, settings):
        seen: list[str] = []

        def fake_read_all(_settings=None):
            seen.append("read")
            return [balances.Balance("deepseek", amount=99.0, currency="USD")]

        original = balances.read_all
        balances.read_all = fake_read_all
        try:
            response = client.post(
                "/credit/refresh", params={"next": "/jobs?page=2"}, follow_redirects=False
            )
        finally:
            balances.read_all = original

        assert response.status_code == 303
        assert response.headers["location"] == "/jobs?page=2"
        assert seen == ["read"], "the click is what spends the calls"
        session.expire_all()
        stored = {row.provider: row.amount for row in balances.read_stored(session)}
        assert stored["deepseek"] == 99.0

    def test_an_offsite_target_is_refused(self, client, session, settings):
        """`next` comes from the page the strip was rendered on, so it is a redirect
        target a caller controls. An unchecked one turns every page into a phishing
        primitive, which is a worse outcome than the dashboard losing its query string."""
        original = balances.read_all
        balances.read_all = lambda _settings=None: []
        try:
            for hostile in ("https://evil.test/x", "//evil.test", "/\\evil.test", ""):
                response = client.post(
                    "/credit/refresh", params={"next": hostile}, follow_redirects=False
                )
                assert response.headers["location"] == "/dashboard", hostile
        finally:
            balances.read_all = original
