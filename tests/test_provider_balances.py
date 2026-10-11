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

import datetime as dt
import json
from pathlib import Path

import pytest

from awltux.db import utcnow
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

    def test_a_json_true_is_not_read_as_one_unit_of_currency(self):
        """`float(True)` is `1.0`, so a payload that put a boolean where the balance belongs
        would render as a real amount. "No balance readable" and "one unit left" are opposite
        conclusions on the credit banner, so the boolean has to read as missing."""
        payload = _fixture("deepseek_balance.json")["payload"]
        payload["balance_infos"][0]["total_balance"] = True

        assert balances.parse_deepseek(payload).amount is None

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


class TestProbingDeepSeek:
    """The reading is labelled with the key, and with what the figure actually covers.

    Asked for directly on 2026-10-09: *"I think the DeepSeek costs are for all keys? It
    would be preferable if it showed just for this key. I suspect you will need a key name
    to support that."* The suspicion is right about the mechanism and the scope cannot be
    fixed: `GET /user/balance` reports the whole account and DeepSeek publishes no per-key
    figure (the per-key breakdown is a console CSV export). So the name is a label, and
    these tests hold both halves -- the label is carried, and the note that says the figure
    is the account's is not optional.
    """

    @staticmethod
    def _answering(monkeypatch, payload):
        class Fake:
            def __init__(self, provider, **kwargs):
                pass

            def request(self, method, path, **kwargs):
                class Response:
                    @staticmethod
                    def json():
                        return payload

                return Response()

            def close(self):
                pass

        monkeypatch.setattr(balances, "HttpClient", Fake)

    def test_the_reading_carries_the_configured_key_name(self, settings, monkeypatch):
        self._answering(monkeypatch, _fixture("deepseek_balance.json")["payload"])
        monkeypatch.setattr(settings.env, "deepseek_api_key", "secret", raising=False)
        monkeypatch.setattr(settings.env, "deepseek_key_name", "awltux", raising=False)

        balance = balances.read_deepseek(settings)

        assert balance.key_name == "awltux"
        assert balance.amount == 21.76

    def test_the_note_says_the_figure_is_the_whole_account(self, settings, monkeypatch):
        """The half that stops the number being read as this project's own spend.

        Without it the strip shows a DeepSeek balance beside this app's name and the
        reader concludes the money is theirs alone -- which is the misreading that
        prompted the question.
        """
        self._answering(monkeypatch, _fixture("deepseek_balance.json")["payload"])
        monkeypatch.setattr(settings.env, "deepseek_api_key", "secret", raising=False)
        monkeypatch.setattr(settings.env, "deepseek_key_name", "awltux", raising=False)

        balance = balances.read_deepseek(settings)

        assert "whole DeepSeek account" in balance.note
        assert "per-key" in balance.note
        assert "llm_call" in balance.note, "and which figure *is* ours"

    def test_an_unnamed_key_leaves_the_name_empty_rather_than_inventing_one(
        self, settings, monkeypatch
    ):
        self._answering(monkeypatch, _fixture("deepseek_balance.json")["payload"])
        monkeypatch.setattr(settings.env, "deepseek_api_key", "secret", raising=False)
        monkeypatch.setattr(settings.env, "deepseek_key_name", "", raising=False)

        balance = balances.read_deepseek(settings)

        assert balance.key_name is None
        assert "whole DeepSeek account" in balance.note

    def test_a_failure_keeps_its_own_note_and_still_names_the_key(
        self, settings, monkeypatch
    ):
        """A failure note explains *that* reading; the scope sentence must not replace it."""
        from awltux.providers.http import ProviderError

        def refuse(self, method, path, **kwargs):
            raise ProviderError("deepseek", "HTTP 500", status=500)

        monkeypatch.setattr(balances.HttpClient, "request", refuse, raising=False)
        monkeypatch.setattr(settings.env, "deepseek_api_key", "secret", raising=False)
        monkeypatch.setattr(settings.env, "deepseek_key_name", "awltux", raising=False)

        balance = balances.read_deepseek(settings)

        assert "could not read the balance" in balance.note
        assert balance.key_name == "awltux"

    def test_the_scope_survives_a_round_trip_through_the_store(self, session):
        read = balances.Balance(
            "deepseek",
            amount=3.0,
            currency="USD",
            note="the whole account",
            key_name="awltux",
        )

        balances.store(session, [read])
        stored = balances.read_stored(session)

        assert stored[0].key_name == "awltux"

    def test_a_reading_stored_before_the_field_existed_still_reads(self, session):
        """Rows written by an older build have no `key_name` key at all.

        `.get` rather than `[...]`, because a missing label must not take out a reading
        that is otherwise perfectly good -- and this is read on every page render.
        """
        payload = {
            "provider": "deepseek",
            "available": True,
            "amount": 3.0,
            "currency": "USD",
            "note": "",
            "read_at": "2026-10-09T10:00:00+00:00",
        }

        restored = balances.Balance.from_dict(payload)

        assert restored.key_name is None
        assert restored.amount == 3.0


class TestEstimatingSpendFromTheBalance:
    """The fal spend estimate: derived from the provider's own balance going down.

    Suggested directly on 2026-10-09: *"the fal costs could be roughly calculated by storing
    the balance each time it's updated and comparing it to the next balance update. It's not
    key specific, but it's useful."* It is the only figure that exists for fal -- its billing
    endpoint refuses a model key and no ledger records an embeddings request's cost -- so the
    tests here are mostly about the ways it must **refuse to guess**:

    * a balance that went *up* hides the spending in that interval, so those intervals
      contribute nothing rather than a negative;
    * readings in different currencies, or taken with differently-named keys, are not
      comparable and must not be differenced at all;
    * one reading is not an estimate.
    """

    @staticmethod
    def _reading(amount, *, minutes, currency="USD", key_name=None):
        return balances.Balance(
            "fal",
            amount=amount,
            currency=currency,
            key_name=key_name,
            read_at=dt.datetime(2026, 10, 9, 12, tzinfo=dt.UTC) + dt.timedelta(minutes=minutes),
        )

    def test_a_falling_balance_is_what_was_spent(self):
        readings = [self._reading(10.0, minutes=0), self._reading(7.5, minutes=60)]

        result = balances.burn(readings)

        assert result.spent_at_least == 2.5
        assert result.intervals == 1
        assert result.known

    def test_a_rising_balance_hides_that_intervals_spending(self):
        """The structural reason this is a floor rather than a total, stated as a test.

        10.00 -> 50.00 with 50.00 added means 10.00 was spent and is invisible. Counting the
        increase as negative spend would be worse than useless -- it would subtract real
        spending from the estimate -- so the interval is recorded and contributes nothing.
        """
        readings = [
            self._reading(10.0, minutes=0),
            self._reading(50.0, minutes=60),
            self._reading(45.0, minutes=120),
        ]

        result = balances.burn(readings)

        assert result.spent_at_least == 5.0, "only the fall after the top-up is measurable"
        assert result.topped_up == 40.0
        assert result.intervals == 2, "both intervals are counted, one just proves nothing"
        assert "floor" in result.sentence()

    def test_a_currency_change_is_not_differenced(self):
        """Different units, possibly a different account: the delta would be meaningless."""
        readings = [
            self._reading(10.0, minutes=0, currency="USD"),
            self._reading(4.0, minutes=60, currency="EUR"),
        ]

        result = balances.burn(readings)

        assert result.spent_at_least == 0.0
        assert result.breaks == 1
        assert result.intervals == 0
        assert not result.known, "nothing was comparable, so there is no estimate"

    def test_a_change_of_key_is_not_differenced(self):
        readings = [
            self._reading(10.0, minutes=0, key_name="awltux"),
            self._reading(4.0, minutes=60, key_name="something-else"),
        ]

        assert balances.burn(readings).breaks == 1

    def test_one_reading_is_not_an_estimate(self):
        assert not balances.burn([self._reading(10.0, minutes=0)]).known

    def test_readings_that_span_too_little_time_are_not_usable(self):
        """The strip labels the figure "/ 30d", so two readings a minute apart is a lie.

        The arithmetic is fine: one interval, and a real fall of a penny. What is not fine
        is printing it under a 30-day heading, so `usable` gates it and the caller shows
        nothing until the readings cover enough time to mean something.
        """
        too_short = balances.burn(
            [self._reading(10.0, minutes=0), self._reading(9.99, minutes=1)]
        )
        long_enough = balances.burn(
            [self._reading(10.0, minutes=0), self._reading(9.99, minutes=60 * 7)]
        )

        assert too_short.spent_at_least == 0.01
        assert not too_short.usable, "one minute is not a 30-day estimate"
        assert long_enough.usable

    def test_the_tooltip_says_how_long_the_readings_cover(self):
        """Otherwise "estimated from 1 change" reads the same for a minute and for a month."""
        result = balances.burn(
            [self._reading(10.0, minutes=0), self._reading(9.0, minutes=60 * 30)]
        )

        assert "30 hours" in result.sentence()

    def test_no_readings_at_all_is_not_a_crash(self):
        result = balances.burn([])

        assert not result.known
        assert result.spent_at_least == 0.0

    def test_an_unreadable_reading_is_skipped_rather_than_counted_as_zero(self):
        """A `None` amount is "we could not see it", and differencing it would invent a
        drop of the whole balance."""
        readings = [
            self._reading(10.0, minutes=0),
            balances.Balance("fal", amount=None, currency="USD", note="403"),
            self._reading(9.0, minutes=120),
        ]

        result = balances.burn(readings)

        assert result.spent_at_least == 1.0
        assert result.intervals == 1

    def test_flat_readings_are_counted_and_cost_nothing(self):
        """"Eleven readings, no movement" is information; the counters have to say it."""
        readings = [self._reading(10.0, minutes=index * 60) for index in range(11)]

        result = balances.burn(readings)

        assert result.intervals == 10
        assert result.spent_at_least == 0.0
        assert result.known


class TestTheReadingSeries:
    def test_storing_a_readable_reading_appends_to_the_series(self, session):
        balances.store(session, [balances.Balance("fal", amount=11.1, currency="USD")])

        stored = balances.stored_readings(
            session, provider="fal", since=utcnow() - dt.timedelta(days=1)
        )

        assert [row.amount for row in stored] == [11.1]

    def test_an_unreadable_reading_is_not_appended(self, session):
        """It has no amount to difference, and the merged entry already carries its state."""
        balances.store(session, [balances.Balance("fal", note="the key is not permitted")])

        assert balances.stored_readings(
            session, provider="fal", since=utcnow() - dt.timedelta(days=1)
        ) == []

    def test_storing_the_same_reading_twice_does_not_make_two_rows(self, session):
        """A phantom zero-length interval, otherwise -- and the job re-stores on every run.

        The same *object*, which is the real shape: a probe carries its own ``read_at`` and
        the job hands the same list over. Two readings built without a timestamp are two
        different instants and are two rows, which is why this asserts on one object.
        """
        reading = balances.Balance(
            "fal", amount=11.1, currency="USD", read_at=utcnow()
        )

        balances.store(session, [reading])
        balances.store(session, [reading])

        stored = balances.stored_readings(
            session, provider="fal", since=utcnow() - dt.timedelta(days=1)
        )
        assert len(stored) == 1

    def test_the_reading_before_the_window_is_included(self, session):
        """Without it the first in-window drop is lost -- and that drop is in the window.

        The balance fell from 10.00 to 7.00 between the last reading before the window and
        the first one inside it. Excluding the boundary reading would report 0.00 spent.
        """
        balances.store(
            session,
            [
                balances.Balance(
                    "fal",
                    amount=10.0,
                    currency="USD",
                    read_at=utcnow() - dt.timedelta(days=10),
                )
            ],
        )
        balances.store(
            session, [balances.Balance("fal", amount=7.0, currency="USD", read_at=utcnow())]
        )

        readings = balances.stored_readings(
            session, provider="fal", since=utcnow() - dt.timedelta(days=2)
        )

        assert [row.amount for row in readings] == [10.0, 7.0]
        assert balances.burn(readings).spent_at_least == 3.0

    def test_a_reading_for_another_provider_is_not_returned(self, session):
        balances.store(session, [balances.Balance("deepseek", amount=20.0, currency="USD")])

        assert balances.stored_readings(
            session, provider="fal", since=utcnow() - dt.timedelta(days=1)
        ) == []


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
