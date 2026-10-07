"""What each provider says about the money left, and what that is allowed to mean.

Running out of credit is the one provider failure that is neither transient nor a bug, and
it presents like both: the decision engine quietly falls back to the deterministic rules
and nothing says the account is empty. The banner exists to say it, so the tests here are
mostly about the thing that would make it *lie*:

* **Unreadable is not zero.** fal's billing endpoint refuses a model key, and the banner
  must not turn that into "you have run out of money". The two are opposite conclusions and
  only one of them should stop work.
* **A payment failure is not an entitlement failure.** `openai/*` embeddings are refused
  with a 401 naming an organization, which is a *scope* problem; DeepSeek answers
  `402 Insufficient Balance`, which is money. A classifier that matched both would put a
  "top up your account" bar in front of someone whose account is fine.
* **The parsers are measured, not guessed.** Both fixtures are real captured responses, and
  fal's real field is `current_balance` -- the first version of the parser guessed
  `balance`/`available`/`amount` and reported "no balance field" against a body that had
  one.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from awltux.providers import balances

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class TestParsingDeepSeek:
    def test_the_captured_response_reads(self):
        balance = balances.parse_deepseek(_fixture("deepseek_balance.json")["payload"])

        assert balance.available is True
        assert balance.amount == pytest.approx(21.76)
        assert balance.currency == "USD"
        assert balance.note == ""

    def test_amounts_arrive_as_strings_and_become_numbers(self):
        """The API sends `"total_balance": "21.76"` — a string. Returning it as-is would
        make the floor comparison a string comparison, where `"9.00" > "10.00"`."""
        balance = balances.parse_deepseek(_fixture("deepseek_balance.json")["payload"])

        assert isinstance(balance.amount, float)

    def test_being_cut_off_is_reported_separately_from_the_amount(self):
        """`is_available: false` with a zero balance and a positive balance with
        `is_available: true` are different states, and only one is an outage."""
        payload = _fixture("deepseek_balance.json")["unavailable"]

        balance = balances.parse_deepseek(payload)

        assert balance.available is False
        assert balance.amount == 0.0

    def test_several_currencies_report_usd(self):
        """Every cost this project records is in dollars, so a CNY balance beside a
        dollar spend would be two units and no comparison."""
        payload = _fixture("deepseek_balance.json")["several_currencies"]

        assert balances.parse_deepseek(payload).currency == "USD"

    def test_a_response_with_no_balances_says_so(self):
        balance = balances.parse_deepseek({"is_available": True, "balance_infos": []})

        assert balance.amount is None
        assert "no balances" in balance.note

    def test_something_that_is_not_an_object_is_not_a_zero(self):
        assert balances.parse_deepseek(["nonsense"]).amount is None


class TestParsingFal:
    def test_the_captured_response_reads(self):
        """The real field is `current_balance`, and the path must carry `expand=credits`."""
        balance = balances.parse_fal(_fixture("fal_billing.json")["payload"])

        assert balance.amount == pytest.approx(1.1)
        assert balance.currency == "USD"
        assert balance.note == ""

    def test_the_unexpanded_response_names_the_missing_parameter(self):
        """`/account/billing` without `expand=credits` answers with the account name and
        no credits at all. That must read as a shape the caller got wrong, not as a
        balance of zero."""
        balance = balances.parse_fal(_fixture("fal_billing.json")["without_expansion"])

        assert balance.amount is None
        assert "expand=credits" in balance.note

    def test_a_refusal_body_is_not_a_balance(self):
        balance = balances.parse_fal(_fixture("fal_billing.json")["refused_with_a_model_key"])

        assert balance.amount is None
        assert balance.available is None


class TestProbingFal:
    def test_a_403_is_reported_as_a_scope_problem(self, settings, monkeypatch):
        """The expected outcome for a model key, and it must not say "no money"."""
        from awltux.providers.http import ProviderError

        monkeypatch.setattr(
            settings.env, "falai_admin_key", None, raising=False
        )
        settings.news.embeddings.api_key = None
        monkeypatch.setattr(
            settings.env, "falai_key", type("S", (), {"get_secret_value": lambda self: "k"})(),
            raising=False,
        )

        def refuse(self, method, path, **kwargs):
            raise ProviderError("fal", "HTTP 403: not permitted", status=403)

        monkeypatch.setattr("awltux.providers.balances.HttpClient.request", refuse, raising=False)

        balance = balances.read_fal(settings)

        assert balance.amount is None
        assert balance.available is None
        assert "not permitted to read billing" in balance.note
        assert "no FAL_ADMIN_KEY is set" in balance.note

    def test_the_admin_key_is_what_is_sent_when_it_exists(self, settings, monkeypatch):
        """And it is used for this call alone: the model key stays the one that is spent."""
        sent: dict = {}

        class Fake:
            def __init__(self, provider, **kwargs):
                sent["headers"] = kwargs.get("headers")

            def request(self, method, path, **kwargs):
                sent["path"] = path

                class Response:
                    @staticmethod
                    def json():
                        return {"username": "x", "credits": {"current_balance": 4.0, "currency": "USD"}}

                return Response()

            def close(self):
                pass

        monkeypatch.setattr(balances, "HttpClient", Fake)
        monkeypatch.setattr(settings.env, "falai_admin_key", "admin-secret", raising=False)

        balance = balances.read_fal(settings)

        assert sent["headers"]["Authorization"] == "Key admin-secret"
        assert "expand=credits" in sent["path"], "the number only comes back expanded"
        assert balance.amount == 4.0


class TestWhatCountsAsAWarning:
    def test_below_the_floor_warns(self):
        assert balances.warned(balances.Balance("x", amount=1.10), below=5.0) is True

    def test_above_the_floor_does_not(self):
        assert balances.warned(balances.Balance("x", amount=21.68), below=5.0) is False

    def test_unreadable_is_not_a_warning(self):
        """A bar that is always up is a bar nobody reads, and several providers cannot be
        asked at all with the credential this project holds."""
        assert balances.warned(balances.Balance("x", note="403"), below=5.0) is False

    def test_the_provider_saying_it_cannot_pay_always_warns(self):
        assert balances.warned(balances.Balance("x", available=False), below=0.0) is True

    def test_a_zero_floor_still_warns_on_unavailable(self):
        assert balances.warned(
            balances.Balance("x", available=False, amount=0.0), below=0.0
        ) is True


class TestPaymentFailures:
    @pytest.mark.parametrize(
        "text",
        [
            "HTTP 402: Insufficient Balance",
            "[deepseek] HTTP 402 Payment Required",
            "you exceeded your current quota",
            "quota exceeded for this key",
            "insufficient_balance",
        ],
    )
    def test_money_problems_are_matched(self, text):
        assert balances.looks_like_payment_failure(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            # The one that would be a false positive, and the most likely: an
            # entitlement refusal naming an organization, not an empty account.
            "HTTP 401: You do not have access to the organization tied to the API key.",
            "HTTP 429: rate limit reached, waiting 0.9s",
            "connection reset by peer",
            "",
            None,
        ],
    )
    def test_everything_else_is_not(self, text):
        assert balances.looks_like_payment_failure(text) is False


class TestStoring:
    def test_a_reading_round_trips_through_the_store(self, session):
        balances.store(
            session,
            [balances.Balance("deepseek", available=True, amount=21.68, currency="USD")],
        )
        session.commit()

        stored = balances.read_stored(session)

        assert [row.provider for row in stored] == ["deepseek"]
        assert stored[0].amount == pytest.approx(21.68)

    def test_an_unreadable_provider_does_not_erase_a_previous_reading(self, session):
        """A run that could read one provider and not the other must not delete the
        other's last known figure."""
        balances.store(session, [balances.Balance("fal", amount=9.0, currency="USD")])
        session.commit()

        balances.store(session, [balances.Balance("deepseek", amount=3.0, currency="USD")])
        session.commit()

        stored = {row.provider: row for row in balances.read_stored(session)}

        assert stored["fal"].amount == pytest.approx(9.0)
        assert stored["deepseek"].amount == pytest.approx(3.0)

    def test_stored_readings_come_back_in_a_fixed_order(self, session):
        """So the banner does not reshuffle between renders."""
        balances.store(
            session,
            [
                balances.Balance("fal", amount=1.0, currency="USD"),
                balances.Balance("deepseek", amount=2.0, currency="USD"),
            ],
        )
        session.commit()

        assert [row.provider for row in balances.read_stored(session)] == ["deepseek", "fal"]

    def test_a_corrupt_entry_is_dropped_rather_than_raising(self, session):
        """This is read on every page render; a bad row must not take the dashboard down."""
        from awltux.db import AppSetting

        session.add(AppSetting(key=balances.SETTING_KEY, value={"deepseek": "not a dict"}))
        session.commit()

        assert balances.read_stored(session) == []


class TestTheJob:
    def test_it_reports_each_provider_even_when_unreadable(self, session, monkeypatch):
        from awltux.ingest import jobs

        monkeypatch.setattr(
            balances,
            "read_all",
            lambda settings=None: [
                balances.Balance("deepseek", available=True, amount=21.68, currency="USD"),
                balances.Balance("fal", note="403"),
            ],
        )

        result = jobs.refresh_provider_balances()

        assert result.items_seen == 2
        assert result.items_written == 1, "one provider reported a number"
        assert result.detail["unreadable"] == ["fal"]
        assert result.detail["balances"]["deepseek"]["amount"] == pytest.approx(21.68)

    def test_the_summariser_says_which_and_how_much(self):
        from awltux.scheduler.outcomes import _provider_balance

        summary = _provider_balance(
            {
                "balances": {
                    "deepseek": {"amount": 21.68, "currency": "USD"},
                    "fal": {"amount": None, "available": None},
                }
            }
        )

        assert "deepseek 21.68 USD" in summary
        assert "fal not readable" in summary

    def test_the_summariser_distinguishes_empty_from_unreadable(self):
        from awltux.scheduler.outcomes import _provider_balance

        summary = _provider_balance(
            {"balances": {"x": {"amount": None, "available": False}}}
        )

        assert "reports it cannot pay" in summary
