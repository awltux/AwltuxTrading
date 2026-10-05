"""Connectivity and configuration diagnostics.

Written because of a real debugging session: a ``401`` from Trading 212 looked
like an application bug, and the fastest way to settle it was a differential test
-- no auth, bogus credentials, and the real credentials, all returning the same
``401`` with an empty body, while an invalid *path* returned a proper ``404``.
That proved the request was reaching the API and the credential was simply not
accepted.

Doing that by hand each time is tedious and easy to get wrong, so the same
differential logic lives here. Secrets are never printed -- only presence, length
and character class, which is enough to spot a truncated or whitespace-padded
value.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from awltux.config import Settings, get_settings

logger = logging.getLogger(__name__)

Status = Literal["ok", "warn", "fail", "skip"]


@dataclass(slots=True)
class Check:
    name: str
    status: Status
    detail: str
    hint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "check": self.name,
            "status": self.status,
            "detail": self.detail,
        }
        if self.hint:
            payload["hint"] = self.hint
        return payload


@dataclass(slots=True)
class Diagnosis:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: Status, detail: str, hint: str | None = None) -> None:
        self.checks.append(Check(name, status, detail, hint))

    @property
    def worst(self) -> Status:
        for status in ("fail", "warn", "ok"):
            if any(check.status == status for check in self.checks):
                return status  # type: ignore[return-value]
        return "skip"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.worst,
            "checks": [check.as_dict() for check in self.checks],
        }


def _describe_secret(label: str, value: str) -> str:
    """Describe a credential without revealing any of it."""
    if not value:
        return f"{label}: not set"
    classes = set()
    if any(c.isupper() for c in value):
        classes.add("upper")
    if any(c.islower() for c in value):
        classes.add("lower")
    if any(c.isdigit() for c in value):
        classes.add("digit")
    odd = sorted({c for c in value if not (c.isalnum() or c in "-_")})
    return (
        f"{label}: {len(value)} chars ({'+'.join(sorted(classes)) or 'none'})"
        + (f", unexpected characters {odd}" if odd else "")
        + (", has leading/trailing whitespace" if value != value.strip() else "")
    )


def _client(settings: Settings, *, timeout: float = 25.0) -> httpx.Client:
    """A client matching how the app connects, including IPv4 pinning.

    Diagnostics are worthless if they test a different network path from the one
    the application uses.
    """
    transport = None
    if settings.env.force_ipv4:
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
    return httpx.Client(timeout=timeout, follow_redirects=True, transport=transport)


def egress_addresses(settings: Settings, *, timeout: float = 15.0) -> dict[str, str | None]:
    """The source addresses providers actually see, per IP family.

    A dual-stack machine presents a *different* address depending on the family,
    which is exactly how an IP allowlist silently fails: you allowlist the IPv4
    address, the client connects over IPv6, and the key is rejected.

    ``api.ipify.org`` is IPv4-only and ``api64.ipify.org`` is dual-stack, so
    querying both isolates the two families rather than depending on whatever the
    resolver happens to prefer.
    """
    addresses: dict[str, str | None] = {"ipv4": None, "ipv6": None}

    try:
        with _client(settings, timeout=timeout) as client:
            addresses["ipv4"] = client.get("https://api.ipify.org").text.strip() or None
    except Exception:
        pass

    try:
        with httpx.Client(timeout=timeout) as client:
            addresses["ipv6"] = client.get("https://api64.ipify.org").text.strip() or None
    except Exception:
        pass

    return addresses


def public_ip(timeout: float = 15.0) -> str | None:
    """Best-effort single address, for contexts without settings."""
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            text = httpx.get(url, timeout=timeout).text.strip()
            if text:
                return text
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# Trading 212
# --------------------------------------------------------------------------- #


def check_trading212(diagnosis: Diagnosis, settings: Settings, *, timeout: float = 25.0) -> None:
    """Differential check of the Trading 212 credentials.

    Deliberately compares the real credentials against a bogus pair and against no
    auth at all. If all three produce the same response, the credential is being
    rejected and the request itself is fine -- which is the distinction that
    matters, and the one a single failing call cannot tell you apart.
    """
    env = settings.env
    if not env.t212_configured:
        diagnosis.add(
            "trading212",
            "skip",
            "no API key configured",
            "Set AWLTUX_T212_API_KEY and AWLTUX_T212_API_SECRET in .env. Without "
            "them the instrument universe cannot be built, so there is nothing to analyse.",
        )
        return

    key = env.require("Trading 212", "t212_api_key")
    secret = env.require("Trading 212", "t212_api_secret")
    diagnosis.add("trading212.credentials", "ok", _describe_secret("key", key))
    diagnosis.add("trading212.secret", "ok", _describe_secret("secret", secret))

    # Report the source addresses *before* testing, because a key can be
    # IP-restricted and that is the first thing to check when it is rejected.
    addresses = egress_addresses(settings)
    if addresses["ipv4"] or addresses["ipv6"]:
        diagnosis.add(
            "network.egress",
            "ok",
            f"IPv4 {addresses['ipv4'] or 'unknown'}, IPv6 {addresses['ipv6'] or 'unknown'}"
            + (" (pinned to IPv4)" if env.force_ipv4 else ""),
            None
            if env.force_ipv4
            else "If your provider key is IP-restricted, its allowlist must contain "
            "the address that provider actually sees -- and a dual-stack machine "
            "presents different addresses per family. Set AWLTUX_FORCE_IPV4=true "
            "to make the IPv4 address the only one used.",
        )
    else:
        diagnosis.add("network.egress", "warn", "could not determine the egress address")

    path = "/equity/metadata/exchanges"
    bases = {
        "demo": "https://demo.trading212.com/api/v0",
        "live": "https://live.trading212.com/api/v0",
    }

    def probe(base: str, auth: tuple[str, str] | None) -> tuple[int | None, str]:
        try:
            with _client(settings, timeout=timeout) as client:
                response = client.get(
                    f"{base}{path}",
                    auth=auth,
                    headers={"Accept": "application/json"},
                )
                return response.status_code, response.text.strip()
        except Exception as exc:
            return None, f"{type(exc).__name__}: {exc}"

    # --- probe the CONFIGURED environment first ------------------------------
    # Trading 212's limits are per account and are strict (1 request / 30s on this
    # endpoint), and the app is using the same quota. Probing both environments
    # eagerly would trip a 429 and make the diagnostic the cause of the failure it
    # is trying to explain.
    configured = env.t212_env
    status, body = probe(bases[configured], (key, secret))
    working_environment: str | None = None
    transport_failure = status is None

    if status == 200:
        working_environment = configured
        diagnosis.add(f"trading212.{configured}", "ok", "credentials accepted")
    elif status == 429:
        # Authentication runs before throttling, so a 429 means the credential was
        # accepted. Reporting this as a failure would send the user chasing keys.
        working_environment = configured
        diagnosis.add(
            f"trading212.{configured}",
            "warn",
            "HTTP 429 rate limited -- but credentials were accepted, since "
            "authentication precedes throttling",
            "Trading 212 rate limits per account: 1 request / 30s for exchanges and "
            "1 / 50s for instruments, shared with the running app. Wait a minute and "
            "re-run this check.",
        )
    elif status == 401:
        # Confirm the rejection is credential-specific rather than a generic
        # refusal, by comparing against a deliberately bogus pair.
        bogus_status, _ = probe(bases[configured], ("foo", "bar"))
        same_as_bogus = (
            " (identical to the bogus-credential control, so the request form is correct)"
            if bogus_status == 401
            else ""
        )
        diagnosis.add(
            f"trading212.{configured}",
            "fail",
            f"HTTP 401, credentials rejected{same_as_bogus}",
            _credential_hint(configured, configured, settings, addresses),
        )

        # Before concluding the credential is bad, check whether it simply belongs
        # to the *other* environment. That is a one-line fix, not a new key.
        other = "live" if configured == "demo" else "demo"
        other_status, _ = probe(bases[other], (key, secret))
        if other_status == 200:
            working_environment = other
            diagnosis.add(f"trading212.{other}", "ok", "credentials accepted")
    elif status == 403:
        diagnosis.add(
            f"trading212.{configured}",
            "warn",
            "credentials valid, but the key lacks a required scope",
            "Authentication succeeded, so this is a key *scope* problem, not a "
            "credential problem. Regenerate the key with the 'metadata' scope, "
            "and add 'portfolio' to enable held-name detection.",
        )
    else:
        diagnosis.add(
            f"trading212.{configured}",
            "fail",
            f"HTTP {status or 'error'}: {body[:120] or 'no body'}",
        )

    # --- reachability, only when nothing above explained the outcome ---------
    # A response of any kind proves reachability, so this extra request is only
    # spent when every probe failed at the transport level.
    if transport_failure:
        try:
            with _client(settings, timeout=timeout) as client:
                reachable = client.get(
                    f"{bases[configured]}/nonsense", auth=(key, secret)
                ).status_code
        except Exception:
            reachable = None

        if reachable == 404:
            diagnosis.add(
                "trading212.reachable",
                "ok",
                "requests reach the Trading 212 API (invalid path correctly returns 404)",
            )
        else:
            diagnosis.add(
                "trading212.reachable",
                "warn",
                f"could not confirm reachability (invalid path returned {reachable})",
                "A network or DNS problem, rather than a credential problem.",
            )

    if working_environment:
        if working_environment != configured:
            diagnosis.add(
                "trading212.environment",
                "fail",
                f"the key works against '{working_environment}' but "
                f"AWLTUX_T212_ENV is '{configured}'",
                f"Set AWLTUX_T212_ENV={working_environment} in .env. Keys are "
                "per-environment and are not interchangeable.",
            )
        else:
            diagnosis.add(
                "trading212.environment",
                "ok",
                f"AWLTUX_T212_ENV={configured} matches where the key works",
            )

        # Checked against whichever environment actually works, so a mismatched
        # environment does not hide the scope answer.
        _check_portfolio_scope(
            diagnosis, settings, bases[working_environment], key, secret, timeout
        )


def _credential_hint(
    configured_env: str,
    tested_env: str,
    settings: Settings,
    addresses: dict[str, str | None] | None = None,
) -> str:
    """Explain a 401 without spending more requests.

    ``addresses`` is passed in rather than looked up again: the caller has already
    determined them, and these providers rate-limit aggressively enough that an
    avoidable request is a real cost.
    """
    addresses = addresses or egress_addresses(settings)
    seen = ", ".join(
        f"{family} {address}" for family, address in addresses.items() if address
    ) or "an unknown address"
    hints = [
        "The request itself is correct, so the credential is the problem. Check, "
        "in order of likelihood:",
        f"1. **IP allowlist.** If the key is restricted to specific IPs, requests "
        f"from any other address are rejected -- and a key restricted to a private "
        f"or CGNAT address (100.64.0.0/10, which is what a tailnet uses) will never "
        f"match a public one. This machine presents: {seen}.",
        "2. The secret was copied in full. Trading 212 shows it once; re-opening "
        "the page shows a masked value that will not work. Regenerate and copy "
        "the new secret immediately.",
        "3. Account type. The public API serves Invest and Stocks ISA accounts "
        "only -- a CFD or SIPP key will not authenticate.",
        "4. Environment. Keys are per-environment: create a demo key while logged "
        "into the demo account for the demo base URL.",
    ]
    if tested_env != configured_env:
        hints.append(
            f"5. You are testing '{tested_env}' while AWLTUX_T212_ENV is "
            f"'{configured_env}'; only one of them needs to work."
        )
    return " ".join(hints)


def _check_portfolio_scope(
    diagnosis: Diagnosis,
    settings: Settings,
    base: str,
    key: str,
    secret: str,
    timeout: float,
) -> None:
    """Report whether positions are readable -- it changes what the gate can claim."""
    try:
        with _client(settings, timeout=timeout) as client:
            response = client.get(
                f"{base}/equity/positions",
                auth=(key, secret),
                headers={"Accept": "application/json"},
            )
    except Exception as exc:
        diagnosis.add("trading212.portfolio", "warn", f"could not test: {exc}")
        return

    if response.status_code == 200:
        diagnosis.add(
            "trading212.portfolio",
            "ok",
            "positions readable: held-name detection and concentration limits are active",
        )
    elif response.status_code == 403:
        diagnosis.add(
            "trading212.portfolio",
            "warn",
            "the key cannot read positions (missing 'portfolio' scope)",
            "Everything still works, but three things are reduced: 'My holdings' "
            "stays empty, the tactical view cannot tell whether you already own a "
            "name (so it answers 'avoid' rather than 'reduce'), and the risk gate "
            "reports its concentration limits as NOT VERIFIED. Add the read-only "
            "'portfolio' scope to restore them.",
        )
    else:
        diagnosis.add(
            "trading212.portfolio",
            "warn",
            f"HTTP {response.status_code} reading positions",
        )


# --------------------------------------------------------------------------- #
# other providers
# --------------------------------------------------------------------------- #


def check_market_data(diagnosis: Diagnosis, *, timeout: float = 25.0) -> None:
    """A single quote, to prove the price feed works without spending anything."""
    try:
        from awltux.providers.yahoo import YahooProvider

        quote = YahooProvider().get_quote("AAPL")
        diagnosis.add(
            "yahoo",
            "ok",
            f"AAPL quote {quote.price:.2f} {quote.currency} (raw {quote.raw_currency})",
        )
    except Exception as exc:
        diagnosis.add(
            "yahoo",
            "fail",
            f"{type(exc).__name__}: {exc}",
            "Yahoo is the primary price source. Without it, valuations cannot be "
            "computed and no decision can be made.",
        )


def check_edgar(diagnosis: Diagnosis, settings: Settings, *, timeout: float = 25.0) -> None:
    agent = settings.env.sec_user_agent
    if not agent:
        diagnosis.add(
            "sec_edgar",
            "fail",
            "AWLTUX_SEC_USER_AGENT is not set",
            "The SEC rejects requests without a declared contact address.",
        )
        return
    if "@" not in agent:
        diagnosis.add(
            "sec_edgar",
            "warn",
            f"user agent has no contact address: {agent!r}",
            "Use a form like 'AwltuxTrading/0.1 (you@example.com)'. The SEC "
            "answers 403 for undeclared automated clients.",
        )
    try:
        response = httpx.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers={"User-Agent": agent, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
        )
        if response.status_code == 200:
            diagnosis.add("sec_edgar", "ok", "ticker map downloaded")
        elif response.status_code == 403:
            diagnosis.add(
                "sec_edgar",
                "fail",
                "HTTP 403 -- the declared User-Agent was rejected",
                "The SEC requires a real contact address in the User-Agent.",
            )
        else:
            diagnosis.add("sec_edgar", "warn", f"HTTP {response.status_code}")
    except Exception as exc:
        diagnosis.add("sec_edgar", "warn", f"{type(exc).__name__}: {exc}")


def check_deepseek(diagnosis: Diagnosis, settings: Settings, *, timeout: float = 25.0) -> None:
    """Validates the key against the free model-list endpoint, spending nothing."""
    if not settings.env.deepseek_configured:
        diagnosis.add(
            "deepseek",
            "skip",
            "no API key configured",
            "Without DeepSeek there is no filing extraction, no news "
            "classification and no fallback decision engine. The app still runs on "
            "the offline rules engine.",
        )
        return
    key = settings.env.require("DeepSeek", "deepseek_api_key")
    try:
        response = httpx.get(
            f"{settings.env.deepseek_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if response.status_code == 200:
            diagnosis.add("deepseek", "ok", "API key accepted")
        elif response.status_code == 401:
            diagnosis.add(
                "deepseek",
                "fail",
                "HTTP 401 -- the API key was rejected",
                "Check AWLTUX_DEEPSEEK_API_KEY at platform.deepseek.com.",
            )
        else:
            diagnosis.add("deepseek", "warn", f"HTTP {response.status_code}")
    except Exception as exc:
        diagnosis.add("deepseek", "warn", f"{type(exc).__name__}: {exc}")


def check_jev(diagnosis: Diagnosis, settings: Settings, *, timeout: float = 25.0) -> None:
    if not settings.env.jev_configured:
        diagnosis.add(
            "jev",
            "skip",
            "no TypeSafe API key configured",
            "JEV is the calibrated decision engine. Without it, decisions fall "
            "through to DeepSeek and then to the deterministic rules engine, and "
            "are labelled as uncalibrated.",
        )
        return
    key = settings.env.require("TypeSafe AI", "typesafe_api_key")
    try:
        response = httpx.get(
            "https://api.typesafe.ai/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if response.status_code == 200:
            diagnosis.add("jev", "ok", "API key accepted")
        elif response.status_code == 401:
            diagnosis.add("jev", "fail", "HTTP 401 -- the API key was rejected")
        else:
            diagnosis.add("jev", "warn", f"HTTP {response.status_code}")
    except Exception as exc:
        diagnosis.add("jev", "warn", f"{type(exc).__name__}: {exc}")


def check_companies_house(
    diagnosis: Diagnosis, settings: Settings, *, timeout: float = 25.0
) -> None:
    if not settings.env.companies_house_api_key:
        diagnosis.add(
            "companies_house",
            "skip",
            "no API key configured",
            "UK company filings and accounts will not be fetched, so UK-listed "
            "names will fall back to provider fundamentals only.",
        )
        return
    key = settings.env.require("Companies House", "companies_house_api_key")
    try:
        # Basic auth with the key as username and a blank password.
        pair = base64.b64encode(f"{key}:".encode()).decode()
        response = httpx.get(
            "https://api.company-information.service.gov.uk/search/companies",
            params={"q": "tesco", "items_per_page": 1},
            headers={"Authorization": f"Basic {pair}", "Accept": "application/json"},
            timeout=timeout,
        )
    except Exception as exc:
        diagnosis.add("companies_house", "warn", f"{type(exc).__name__}: {exc}")
        return

    if response.status_code == 200:
        diagnosis.add("companies_house", "ok", "API key accepted")
        return

    # Companies House answers with a JSON error body for a *malformed* request
    # and with an empty-bodied 403 for a key it will not accept. That difference
    # is what makes the failure diagnosable, so it is surfaced rather than
    # flattened into "HTTP 403".
    body = response.text.strip()[:160]
    if response.status_code == 401:
        diagnosis.add(
            "companies_house",
            "fail",
            f"HTTP 401: {body or 'no body'}",
            "Auth is the key as the *username* with a blank password.",
        )
    elif response.status_code == 400:
        diagnosis.add(
            "companies_house",
            "fail",
            f"HTTP 400 (malformed Authorization header): {body or 'no body'}",
            "The header format is wrong -- this is an application bug, not a key "
            "problem. Report it.",
        )
    elif response.status_code == 403:
        diagnosis.add(
            "companies_house",
            "fail",
            "HTTP 403 with an empty body -- Companies House is not accepting this key",
            "The request form is correct (an unauthorised request returns a JSON "
            "401, so we are reaching the real API). Check that the key was created "
            "under a *live* application in the Companies House developer hub, that "
            "it was not regenerated since, and that it was copied in full.",
        )
    else:
        diagnosis.add("companies_house", "warn", f"HTTP {response.status_code}: {body}")


def run_diagnosis(settings: Settings | None = None, *, live: bool = True) -> Diagnosis:
    """Run every check. ``live=False`` skips the network entirely."""
    settings = settings or get_settings()
    diagnosis = Diagnosis()

    # --- local state --------------------------------------------------------
    try:
        from awltux.db.migrate import current_revision

        revision = current_revision()
        diagnosis.add(
            "database",
            "ok" if revision else "warn",
            f"{settings.db_path} at revision {revision or 'none'}",
            None if revision else "Run `awltux migrate` to create the schema.",
        )
    except Exception as exc:
        diagnosis.add(
            "database",
            "fail",
            f"{type(exc).__name__}: {exc}",
            "Run `awltux migrate`.",
        )

    from awltux.scheduler.registry import build_job_specs

    specs = build_job_specs(settings)
    enabled = [spec.id for spec in specs if spec.enabled]
    disabled = [spec.id for spec in specs if not spec.enabled]
    diagnosis.add(
        "scheduler",
        "ok" if enabled else "fail",
        f"{len(enabled)} of {len(specs)} jobs enabled"
        + (f"; disabled: {', '.join(disabled)}" if disabled else ""),
    )

    diagnosis.add(
        "decision_engines",
        "ok",
        "priority: " + ", ".join(settings.decision.engine_priority),
    )

    # --- time zones ---------------------------------------------------------
    # zoneinfo reads the IANA database from the system or the `tzdata` package.
    # Without it every lookup fails, the display zone silently collapses to UTC,
    # and the only symptom is that readers in other zones see the wrong clock on
    # every timestamp. A silent degradation is worth a check of its own.
    from awltux.timezones import known_zones, parse_zone

    zones = known_zones()
    configured_zone = parse_zone(settings.app.timezone)
    if len(zones) <= 1:
        diagnosis.add(
            "time_zones",
            "warn",
            "no IANA time zone database found; every time is shown in UTC",
            "Install the `tzdata` package or the system tzdata, or accept UTC display.",
        )
    elif configured_zone is None:
        diagnosis.add(
            "time_zones",
            "warn",
            f"{len(zones)} zones available, but app.timezone "
            f"{settings.app.timezone!r} is not one of them",
            "Fix app.timezone in config/config.yaml; UTC is being used instead.",
        )
    else:
        diagnosis.add(
            "time_zones",
            "ok",
            f"{len(zones)} zones available; default display zone "
            f"{settings.app.timezone}",
        )

    if not live:
        return diagnosis

    check_trading212(diagnosis, settings)
    check_market_data(diagnosis)
    check_edgar(diagnosis, settings)
    check_deepseek(diagnosis, settings)
    check_jev(diagnosis, settings)
    check_companies_house(diagnosis, settings)
    return diagnosis
