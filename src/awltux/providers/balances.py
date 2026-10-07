"""What each model provider says about the money left on the account.

Running out of credit is the one provider failure that is neither transient nor a bug, and
it currently presents exactly like both: the decision engine quietly falls back to the
deterministic rules, the embeddings job records a fatal error, and nothing anywhere says
*the account is empty*. This reads what the providers will actually tell us.

**Two providers, two different answers, and that is the honest shape of it.**

* **DeepSeek** publishes a balance endpoint. `GET /user/balance` answers with
  ``is_available`` and a ``balance_infos`` list per currency. Measured 2026-10-07:
  ``{"is_available": true, "balance_infos": [{"currency": "USD", "total_balance":
  "21.76", ...}]}``.
* **fal** publishes one too -- `GET https://api.fal.ai/v1/account/billing?expand=credits`
  -- and it **refuses the key this project has**: ``403 authorization_error: This API key
  is not permitted to perform this action``. fal's own documentation explains why, saying
  some Platform APIs "require **Admin scope** keys". So the endpoint exists, the number is
  real, and we cannot read it with a model-API key.

That second case is why :attr:`Balance.amount` is optional and why a missing number is
never rendered as zero. "No balance readable" and "no balance left" are opposite
conclusions, and a banner that conflated them would be worse than no banner.

**The third, provider-agnostic signal is usage**, and it is in
:mod:`awltux.monitoring.spend`: a call that failed *because of money* is direct evidence,
whatever the provider's API exposes. :func:`looks_like_payment_failure` is that classifier,
and it is deliberately a pure function of the error text so it can be tested against the
real strings rather than against a mock.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from awltux.config import Settings, get_settings
from awltux.db import AppSetting, utcnow
from awltux.providers.http import HttpClient, ProviderError

logger = logging.getLogger(__name__)

#: One key in `app_setting` holding every provider's most recent reading. The same shape
#: `analysis/macro.py` uses for the observed risk-free rate, and for the same reason: this
#: is a fact about the world observed at a moment, not a row anybody joins on.
SETTING_KEY = "provider_balance"

#: fal's Platform API, which is a different host and a different auth scope from the model
#: endpoint the embeddings client uses.
FAL_PLATFORM_BASE = "https://api.fal.ai/v1"

#: Read at the endpoint fal documents. Recorded rather than assembled inline because the
#: `expand` parameter is the part that decides whether a number comes back at all.
FAL_BILLING_PATH = "/account/billing?expand=credits"

#: Currency to report when a provider offers several. USD because every cost this project
#: records -- `llm_call.cost_usd`, the budget guards -- is in dollars, so a EUR balance
#: shown beside a dollar spend would be two units and no comparison.
PREFERRED_CURRENCY = "USD"


@dataclass(frozen=True, slots=True)
class Balance:
    """One provider's answer to "can you still work for us", and what it rests on."""

    provider: str
    #: The provider's own statement, where it makes one. ``None`` when it was not asked
    #: or could not be read -- which is not the same as ``False``.
    available: bool | None = None
    amount: float | None = None
    currency: str | None = None
    #: Why the amount is missing, or anything else the reader needs. Never empty when
    #: ``amount`` is ``None``: a blank cell reads as zero.
    note: str = ""
    read_at: dt.datetime | None = None

    @property
    def known(self) -> bool:
        return self.amount is not None or self.available is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "available": self.available,
            "amount": self.amount,
            "currency": self.currency,
            "note": self.note,
            "read_at": (self.read_at or utcnow()).isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Balance:
        """The inverse of :meth:`as_dict`, for a stored reading.

        Tolerant of a malformed entry by returning ``None`` rather than raising: this is
        read on every page render, and a corrupt row in `app_setting` must not take the
        whole dashboard down with it. The caller drops what it cannot read.
        """
        try:
            read_at = payload.get("read_at")
            return cls(
                provider=str(payload["provider"]),
                available=payload.get("available"),
                amount=payload.get("amount"),
                currency=payload.get("currency"),
                note=str(payload.get("note") or ""),
                read_at=dt.datetime.fromisoformat(read_at) if read_at else None,
            )
        except (KeyError, TypeError, ValueError):
            return None


def _number(value: Any) -> float | None:
    """A provider's amount as a float. Strings are what these APIs actually send."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_deepseek(payload: Any) -> Balance:
    """DeepSeek's ``/user/balance`` response.

    It reports one entry per currency and states ``is_available`` separately from the
    amount, which is worth preserving rather than deriving: a zero balance with
    ``is_available`` true is a different state from an account that has been cut off.
    """
    if not isinstance(payload, dict):
        return Balance("deepseek", note="the balance response was not an object")

    available = payload.get("is_available")
    infos = [row for row in (payload.get("balance_infos") or []) if isinstance(row, dict)]

    chosen = next(
        (row for row in infos if str(row.get("currency", "")).upper() == PREFERRED_CURRENCY),
        infos[0] if infos else None,
    )
    if chosen is None:
        return Balance(
            "deepseek",
            available=bool(available) if available is not None else None,
            note="the provider reported no balances",
        )
    return Balance(
        "deepseek",
        available=bool(available) if available is not None else None,
        amount=_number(chosen.get("total_balance")),
        currency=str(chosen.get("currency") or "") or None,
        read_at=utcnow(),
    )


def parse_fal(payload: Any) -> Balance:
    """fal's Platform API ``/account/billing?expand=credits`` response.

    Captured live 2026-10-07 with an Admin-scope key::

        {"username": "awltux", "credits": {"current_balance": 1.1, "currency": "USD"}}

    **The field is `current_balance`, and `expand=credits` is load-bearing.** Without the
    expansion the response is just ``{"username": ...}`` -- no credits object at all --
    which is why the path carries the parameter rather than leaving it to the caller. The
    first version of this parser guessed ``balance``/``available``/``amount`` and reported
    "the credits object carried no balance field" against a response that had one.
    """
    if not isinstance(payload, dict):
        return Balance("fal", note="the billing response was not an object")

    credits = payload.get("credits")
    if isinstance(credits, list):
        credits = next(
            (
                row
                for row in credits
                if isinstance(row, dict)
                and str(row.get("currency", "")).upper() == PREFERRED_CURRENCY
            ),
            credits[0] if credits else None,
        )
    if credits is None:
        return Balance(
            "fal",
            note=(
                "the billing response carried no credits object; the endpoint needs "
                "`expand=credits` or it answers with the account name alone"
            ),
        )
    if not isinstance(credits, dict):
        return Balance("fal", note="the credits field was not an object")

    amount = _number(credits.get("current_balance"))
    currency = str(credits.get("currency") or "") or None
    if amount is None:
        return Balance(
            "fal",
            currency=currency,
            note="the credits object carried no `current_balance`",
        )
    return Balance("fal", amount=amount, currency=currency, read_at=utcnow())


def read_deepseek(settings: Settings | None = None) -> Balance:
    """Ask DeepSeek for the balance. Never raises: an unreadable balance is a state."""
    settings = settings or get_settings()
    key = settings.env.deepseek_api_key
    if key is None:
        return Balance("deepseek", note="no DeepSeek credential is configured")

    secret = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
    client = HttpClient(
        "deepseek",
        settings=settings,
        base_url=f"{settings.env.deepseek_base_url.rstrip('/')}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        response = client.request("GET", "/user/balance", cache_ttl=0)
        return parse_deepseek(response.json())
    except ProviderError as exc:
        return Balance("deepseek", note=f"could not read the balance: {exc}")
    except ValueError as exc:
        return Balance("deepseek", note=f"the balance response was not JSON: {exc}")
    finally:
        client.close()


def read_fal(settings: Settings | None = None) -> Balance:
    """Ask fal for the balance, using the billing-scoped key when there is one.

    **Two keys, and the privileged one is used here and nowhere else.** `GET
    /account/billing` refuses the model key this project holds with a plain `403
    authorization_error`, because fal's Platform APIs need a key with the right scope
    (its documentation says some need an Admin key). `FAL_ADMIN_KEY` is read for this
    call alone, so the credential that can move money is never the credential that is
    spent a thousand times an hour on inference.

    When the admin key is absent the balance is *unreadable*, which is reported as such
    and never as zero -- "cannot see it" and "there is none left" are opposite
    conclusions, and only one of them should put a warning in front of a reader.
    """
    settings = settings or get_settings()
    admin = settings.env.falai_admin_key
    key = (
        (admin.get_secret_value() if hasattr(admin, "get_secret_value") else str(admin))
        if admin
        else settings.news.embeddings.credential(settings.env)
    )
    if not key:
        return Balance("fal", note="no fal credential is configured")

    client = HttpClient(
        "fal",
        settings=settings,
        base_url=FAL_PLATFORM_BASE,
        headers={"Authorization": f"Key {key}"},
    )
    try:
        response = client.request("GET", FAL_BILLING_PATH, cache_ttl=0)
        return parse_fal(response.json())
    except ProviderError as exc:
        status = getattr(exc, "status", None)
        if status in (401, 403):
            which = (
                "the FAL_ADMIN_KEY is set but refused"
                if admin
                else "no FAL_ADMIN_KEY is set, so this fell back to the model key"
            )
            return Balance(
                "fal",
                note=(
                    f"the key is not permitted to read billing ({which}, and fal answered "
                    f"{status}). fal's Platform APIs need a key with the right scope -- its "
                    "documentation says some need an Admin key. Spending is still counted "
                    "from our own call log."
                ),
            )
        return Balance("fal", note=f"could not read the balance: {exc}")
    except ValueError as exc:
        return Balance("fal", note=f"the balance response was not JSON: {exc}")
    finally:
        client.close()


#: Every provider this can be asked about, and the function that asks.
READERS = {
    "deepseek": read_deepseek,
    "fal": read_fal,
}


def read_all(settings: Settings | None = None) -> list[Balance]:
    """Every provider's balance, in a fixed order so the banner does not reshuffle."""
    settings = settings or get_settings()
    return [read(settings) for read in READERS.values()]


def store(session, balances: list[Balance]) -> None:
    """Persist the readings, one entry per provider, merging over any already there.

    Merged rather than replaced, for the reason `analysis/macro.py` gives for its own
    cached observation: a run that could read DeepSeek and not fal must not delete fal's
    last known figure. Each entry carries its own ``read_at``, so a stale one is visible
    as stale rather than being presented as current.
    """
    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)

    entries = dict(row.value) if isinstance(row.value, dict) else {}
    for balance in balances:
        entries[balance.provider] = balance.as_dict()
    row.value = entries
    row.note = "; ".join(
        f"{name}: "
        + (f"{entry['amount']} {entry.get('currency') or ''}".strip() if entry.get("amount") is not None else "unreadable")
        for name, entry in sorted(entries.items())
    )
    session.flush()


def read_stored(session) -> list[Balance]:
    """The stored readings, in :data:`READERS` order, skipping anything unreadable."""
    row = session.get(AppSetting, SETTING_KEY)
    entries = row.value if row is not None and isinstance(row.value, dict) else {}
    out: list[Balance] = []
    for name in READERS:
        entry = entries.get(name)
        if isinstance(entry, dict):
            parsed = Balance.from_dict(entry)
            if parsed is not None:
                out.append(parsed)
    return out


#: Phrases that mean "the account cannot pay", across the providers this uses. DeepSeek
#: answers `402 Insufficient Balance`; OpenRouter-through-fal answers a 401/403 naming an
#: organization, which is an entitlement rather than a payment, so it is deliberately *not*
#: matched here -- an entitlement refusal does not mean the account is empty.
PAYMENT_MARKERS = (
    "insufficient balance",
    "insufficient_balance",
    "insufficient funds",
    "quota exceeded",
    "exceeded your current quota",
    "payment required",
    "402",
)


def looks_like_payment_failure(text: str | None) -> bool:
    """Whether an error message means the account could not pay.

    A pure function of the text, so it can be tested against the real strings a provider
    sends rather than against a hand-made one. Kept narrow on purpose: a false positive
    puts a "you have run out of money" banner in front of someone who has not, and the
    cost of a false negative is that the banner appears when the next probe runs.
    """
    haystack = (text or "").lower()
    return any(marker in haystack for marker in PAYMENT_MARKERS)


def warned(balance: Balance, *, below: float) -> bool:
    """Whether this reading deserves a banner.

    Unreadable is not a warning: several providers cannot be asked at all with the
    credential this project holds, and a bar that is always up is one nobody reads.
    """
    if balance.available is False:
        return True
    return balance.amount is not None and balance.amount < below


__all__ = [
    "FAL_BILLING_PATH",
    "FAL_PLATFORM_BASE",
    "PAYMENT_MARKERS",
    "READERS",
    "SETTING_KEY",
    "Balance",
    "looks_like_payment_failure",
    "parse_deepseek",
    "parse_fal",
    "read_all",
    "read_deepseek",
    "read_fal",
    "read_stored",
    "store",
    "warned",
]
