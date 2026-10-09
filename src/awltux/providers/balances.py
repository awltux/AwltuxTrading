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
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import desc, select

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

#: What DeepSeek's balance figure actually covers, said once so every caller says it the
#: same way.
#:
#: The endpoint is ``GET /user/balance`` and it reports the **account**: every key on it,
#: and every tool using them. Asked for directly on 2026-10-09 -- *"I think the DeepSeek
#: costs are for all keys? It would be preferable if it showed just for this key"* -- and
#: the answer is that the provider cannot be asked that way. There is no per-key endpoint;
#: the per-key breakdown exists only in the console's monthly CSV export, which no job can
#: read. So the figure is labelled with the key it was read *with* and this sentence says
#: what it covers, because a number printed beside this project's name would otherwise
#: claim a scope it does not have.
DEEPSEEK_BALANCE_SCOPE = (
    "The whole DeepSeek account, shared by every key on it -- DeepSeek publishes no "
    "per-key balance. The spend beside it is this app's own calls, from llm_call."
)

#: How much of the window the balance readings must cover before a difference is shown.
#:
#: The strip labels every spend figure "/ 30d", so an estimate drawn from two readings taken
#: a second apart would be printed as a monthly total -- which is the "unreadable is not
#: zero" mistake in a new costume. Six hours is a quarter of a day: long enough that the
#: number means something, short enough that a fresh install shows one the same working day,
#: and well inside the hourly `provider_balance` cadence so a normal run of the job clears
#: it on the second reading.
MIN_ESTIMATE_SPAN = dt.timedelta(hours=6)


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
    #: The name of the key this reading was taken with, where the reader has given it one
    #: (``AWLTUX_DEEPSEEK_KEY_NAME``). Descriptive only -- see
    #: :data:`DEEPSEEK_BALANCE_SCOPE` for what the figure covers and why.
    key_name: str | None = None

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
            "key_name": self.key_name,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Balance:
        """The inverse of :meth:`as_dict`, for a stored reading.

        Tolerant of a malformed entry by returning ``None`` rather than raising: this is
        read on every page render, and a corrupt row in `app_setting` must not take the
        whole dashboard down with it. The caller drops what it cannot read.

        ``key_name`` is read with ``.get`` rather than by key: rows stored before the field
        existed have no such key, and a reading taken by an older build is still a reading.
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
                key_name=payload.get("key_name") or None,
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


def _labelled(reading: Balance, *, key_name: str | None) -> Balance:
    """Name the key a reading was taken with, and say what the figure covers.

    Every DeepSeek path goes through here so that no return can forget one half or the
    other: the key name is what the reader asked for, and the scope sentence is what stops
    the number being read as this project's own. A reading that already carries a note --
    "no credential", "could not read" -- keeps it; the scope sentence only fills the gap
    on a reading that worked, which is exactly the one that needs explaining.
    """
    return replace(reading, key_name=key_name, note=reading.note or DEEPSEEK_BALANCE_SCOPE)


def read_deepseek(settings: Settings | None = None) -> Balance:
    """Ask DeepSeek for the balance. Never raises: an unreadable balance is a state."""
    settings = settings or get_settings()
    key = settings.env.deepseek_api_key
    key_name = settings.env.deepseek_key_name or None
    if key is None:
        return _labelled(
            Balance("deepseek", note="no DeepSeek credential is configured"),
            key_name=key_name,
        )

    secret = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key)
    client = HttpClient(
        "deepseek",
        settings=settings,
        base_url=f"{settings.env.deepseek_base_url.rstrip('/')}",
        headers={"Authorization": f"Bearer {secret}"},
    )
    try:
        response = client.request("GET", "/user/balance", cache_ttl=0)
        return _labelled(parse_deepseek(response.json()), key_name=key_name)
    except ProviderError as exc:
        return _labelled(
            Balance("deepseek", note=f"could not read the balance: {exc}"),
            key_name=key_name,
        )
    except ValueError as exc:
        return _labelled(
            Balance("deepseek", note=f"the balance response was not JSON: {exc}"),
            key_name=key_name,
        )
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

    Readable readings are also **appended** to `provider_balance_reading`, which is what
    makes a spend estimate possible for a provider whose own spend we do not log -- see
    :func:`burn`. Unreadable ones are not: they have no amount to difference, and the
    merged entry above already carries their state and their reason.
    """
    row = session.get(AppSetting, SETTING_KEY)
    if row is None:
        row = AppSetting(key=SETTING_KEY)
        session.add(row)

    entries = dict(row.value) if isinstance(row.value, dict) else {}
    for balance in balances:
        entries[balance.provider] = balance.as_dict()
        _append_reading(session, balance)
    row.value = entries
    row.note = "; ".join(
        f"{name}: "
        + (f"{entry['amount']} {entry.get('currency') or ''}".strip() if entry.get("amount") is not None else "unreadable")
        for name, entry in sorted(entries.items())
    )
    session.flush()


def _append_reading(session, balance: Balance) -> None:
    """Add one reading to the series, unless it is the one already at the end of it.

    The guard is on ``read_at`` rather than on the value: a balance that has not moved is
    still a reading, and it is the *same* reading being stored twice -- which happens
    whenever a caller re-stores what it just read -- that must not become two rows and a
    phantom zero-length interval.

    A reading with no ``read_at`` is stamped with now, which is the same thing
    :meth:`Balance.as_dict` already does with the merged entry. Both a probe and a
    hand-built reading mean "as of this moment"; a series entry has to have a time, and
    dropping the row instead would make a stored reading silently missing.
    """
    from awltux.db import ProviderBalanceReading

    if balance.amount is None:
        return
    read_at = balance.read_at or utcnow()
    latest = session.execute(
        select(ProviderBalanceReading)
        .where(ProviderBalanceReading.provider == balance.provider)
        .order_by(desc(ProviderBalanceReading.read_at))
        .limit(1)
    ).scalar_one_or_none()
    if latest is not None and _as_utc(latest.read_at) == _as_utc(read_at):
        return
    session.add(
        ProviderBalanceReading(
            provider=balance.provider,
            amount=float(balance.amount),
            currency=balance.currency,
            key_name=balance.key_name,
            read_at=read_at,
        )
    )


def _as_utc(moment: dt.datetime | None) -> dt.datetime | None:
    """A stored timestamp as UTC, so two of them can be compared across a round trip.

    SQLite hands back a naive datetime for a column that was written with one, and
    ``==`` against an aware one is then False for the same instant -- which would let the
    same reading be appended twice on every run.
    """
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)


def stored_readings(
    session, *, provider: str, since: dt.datetime
) -> list[Balance]:
    """One provider's readings inside a window, oldest first, plus the one before it.

    The boundary reading is included on purpose. Without it the first interval inside the
    window is lost -- the drop between the last reading before the window and the first one
    after it happened *during* the window, and leaving it out would under-count by exactly
    the spend the estimate exists to catch.
    """
    from awltux.db import ProviderBalanceReading

    inside = list(
        session.execute(
            select(ProviderBalanceReading)
            .where(ProviderBalanceReading.provider == provider)
            .where(ProviderBalanceReading.read_at >= since)
            .order_by(ProviderBalanceReading.read_at)
        ).scalars().all()
    )
    before = session.execute(
        select(ProviderBalanceReading)
        .where(ProviderBalanceReading.provider == provider)
        .where(ProviderBalanceReading.read_at < since)
        .order_by(desc(ProviderBalanceReading.read_at))
        .limit(1)
    ).scalar_one_or_none()

    rows = ([before] if before is not None else []) + inside
    return [
        Balance(
            provider=row.provider,
            amount=row.amount,
            currency=row.currency,
            key_name=row.key_name,
            read_at=row.read_at,
        )
        for row in rows
    ]


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


@dataclass(frozen=True, slots=True)
class Burn:
    """What a series of balance readings says about spending, and where it stops saying it.

    ``spent_at_least`` is a floor, never a total -- :func:`burn` explains why every interval
    containing a top-up is unmeasurable. The counters exist so a reader can tell an estimate
    drawn from eleven hours of readings apart from one drawn from a month.
    """

    provider: str
    currency: str | None = None
    spent_at_least: float = 0.0
    #: Money that went *in*, which is what makes the intervals around it unmeasurable.
    topped_up: float = 0.0
    #: Consecutive pairs actually differenced. Zero means no estimate at all.
    intervals: int = 0
    #: Pairs skipped because the currency or the key changed between them.
    breaks: int = 0
    first_at: dt.datetime | None = None
    last_at: dt.datetime | None = None

    @property
    def known(self) -> bool:
        return self.intervals > 0

    @property
    def span(self) -> dt.timedelta:
        """How much time the readings actually cover."""
        if self.first_at is None or self.last_at is None:
            return dt.timedelta()
        return _as_utc(self.last_at) - _as_utc(self.first_at)

    @property
    def usable(self) -> bool:
        """Whether this is worth putting in front of a reader at all.

        The window is not the series' own length: two readings taken a second apart have an
        interval, and a figure derived from it would be printed under a ``/ 30d`` label it
        does not deserve. See :data:`MIN_ESTIMATE_SPAN`.
        """
        return self.known and self.span >= MIN_ESTIMATE_SPAN

    def sentence(self) -> str:
        """Why the figure is "at least", in one line, for a tooltip.

        The "floor" half is unconditional. A window in which nothing was topped up still
        gives a floor rather than a total, because the arithmetic can only see net movement
        -- saying so only when an increase happened would make the caveat look like a
        footnote about this month rather than the nature of the estimate.
        """
        parts = [
            f"Estimated from {self.intervals} change(s) in the provider's own balance "
            f"over {_span_words(self.span)}, because no ledger records this provider's "
            "calls. It is a floor and not a total: spending in an interval where the "
            "balance rose is invisible."
        ]
        if self.topped_up:
            parts.append(f"{self.topped_up:,.2f} was added to the account during the window.")
        if self.breaks:
            parts.append(f"{self.breaks} change(s) could not be compared at all.")
        parts.append("Account-wide: it counts anything else using the same account.")
        return " ".join(parts)


def _span_words(span: dt.timedelta) -> str:
    """A length of time as a reader would say it, for the estimate's tooltip."""
    hours = span.total_seconds() / 3600
    if hours < 1:
        return f"{int(span.total_seconds() // 60)} minutes"
    if hours < 48:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.0f} days"


def burn(readings: Sequence[Balance]) -> Burn:
    """Derive a provider's spend from its balance going down between readings.

    Asked for on 2026-10-09: *"The fal costs could be roughly calculated by storing the
    balance each time it's updated and comparing it to the next balance update. It's not key
    specific, but it's useful."* Both halves of that are right, and this is the arithmetic.

    **It is a lower bound, and the reason is structural rather than a missing input.** Three
    cases, and each is handled by refusing to guess:

    * A reading lower than the last is spending: nothing else takes money out.
    * A reading *higher* than the last is a top-up -- and it hides whatever was spent in
      that interval. If the balance went 10.00 to 50.00 and 50.00 was added, 10.00 was
      spent and is unobservable; if 41.00 was added, 1.00 was. Those intervals contribute
      nothing and are counted, so the caller can say so rather than presenting the sum as
      a total.
    * Two readings that disagree on currency, or that were taken with differently-named
      keys, may not even be the same account, so they are not differenced at all.

    Readings must be in time order and carry an amount; the caller does that filtering
    because it is the one holding the query.
    """
    usable = [row for row in readings if row.amount is not None and row.read_at is not None]
    if not usable:
        return Burn(provider=readings[0].provider if readings else "")

    out = Burn(
        provider=usable[0].provider,
        currency=usable[0].currency,
        first_at=usable[0].read_at,
        last_at=usable[-1].read_at,
    )
    spent = 0.0
    topped_up = 0.0
    intervals = 0
    breaks = 0

    for previous, current in zip(usable, usable[1:], strict=False):
        if previous.currency != current.currency or previous.key_name != current.key_name:
            breaks += 1
            continue
        delta = float(current.amount) - float(previous.amount)
        if delta < 0:
            spent += -delta
        elif delta > 0:
            topped_up += delta
        # A delta of exactly zero is an interval that proves nothing and costs nothing to
        # count, so it is counted -- "eleven readings, no movement" is information.
        intervals += 1

    return replace(
        out,
        spent_at_least=round(spent, 4),
        topped_up=round(topped_up, 4),
        intervals=intervals,
        breaks=breaks,
    )


__all__ = [
    "FAL_BILLING_PATH",
    "FAL_PLATFORM_BASE",
    "PAYMENT_MARKERS",
    "READERS",
    "SETTING_KEY",
    "Balance",
    "Burn",
    "burn",
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
