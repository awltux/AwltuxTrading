"""DeepSeek client: investigation and summarisation, plus decision fallback.

DeepSeek is used for the work JEV cannot do -- reading a 200-page annual report,
summarising it, and classifying a headline -- because it has a 1M-token context
and accepts text. It is *not* used to produce valuation numbers: it extracts
figures with citations and code decides what to do with them.

Two cost behaviours are built in, because this is the part of the system that
spends real money:

* **Prefix-cache discipline.** DeepSeek's cached input is roughly 50x cheaper than
  a cache miss, so large documents must sit at the *start* of the prompt as a
  stable prefix and the instructions after them. :func:`build_messages` enforces
  that ordering.
* **A hard monthly ceiling.** Before each call the running monthly spend is read
  from ``llm_call``; if the next call would breach the configured budget the
  client raises instead of spending. The decision layer degrades to a weaker
  engine rather than quietly running up a bill.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select

from awltux.config import Settings, get_settings
from awltux.db import LLMCall, release_before_network, session_scope
from awltux.providers.http import HttpClient, ProviderError, ProviderNotConfigured

logger = logging.getLogger(__name__)

SOURCE = "deepseek"


class DeepSeekError(RuntimeError):
    """A DeepSeek call failed."""


class BudgetExceeded(DeepSeekError):
    """The configured monthly spend ceiling would be breached."""


class TruncatedResponse(DeepSeekError):
    """The model hit its output limit, so the response is incomplete.

    Distinct from a generic parse failure because it is *actionable*: the caller
    can retry with a larger budget, and the log can say what actually happened.
    Without this, a truncated JSON body surfaced as "Unterminated string
    starting at..." -- a message that describes a symptom and hides the cause,
    which is how it reached a decision narrative instead of a diagnosis.
    """


@dataclass(slots=True)
class Completion:
    """A model response plus the accounting needed to attribute its cost."""

    text: str
    model: str
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    llm_call_id: int | None = None
    raw: dict[str, Any] | None = None
    finish_reason: str | None = None

    def json_object(self) -> dict[str, Any]:
        """Parse the completion as JSON, tolerating a fenced code block.

        Models occasionally wrap JSON in ```json fences even in JSON mode, and
        failing the whole extraction over that would be wasteful.
        """
        text = self.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            if self.finish_reason == "length":
                # Say the useful thing. The JSON error names the character offset,
                # which tells the reader nothing about why there is nothing after it.
                if not text:
                    # Observed in production: `Expecting value at char 0` means the
                    # response body was empty, not that the JSON was cut short.
                    #
                    # Measured, the tokens went somewhere the caller never sees: over
                    # 2,474 classification calls the mean *output* was 235 tokens
                    # while the returned content was about 120, and the calls that
                    # produced nothing had burned their entire budget. So the message
                    # names the likely cause rather than only the symptom -- the
                    # budget was spent on reasoning, and sizing it to the answer is
                    # sizing it to the wrong thing.
                    raise TruncatedResponse(
                        f"the model returned no content at all before reaching the "
                        f"{self.output_tokens or '?'}-token output limit. The budget was "
                        "spent before the answer began, which usually means reasoning "
                        "the API does not return in `content`: raise max_tokens well "
                        "above the length of the answer, or ask for a shorter one"
                    ) from exc
                raise TruncatedResponse(
                    f"response was cut off at the {self.output_tokens or '?'}-token output "
                    f"limit, so the JSON is incomplete ({exc.msg} at char {exc.pos}); "
                    "raise max_tokens or ask for a shorter answer"
                ) from exc
            raise DeepSeekError(f"model did not return valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise DeepSeekError("model returned JSON that was not an object")
        return parsed


def estimate_cost(model: str, input_tokens: int, output_tokens: int, cached: int = 0) -> float:
    """Cost in USD, using the configured per-million-token prices.

    Cached input tokens are billed at the cache-hit rate; the remainder at the
    cache-miss rate. Prices are configured rather than hardcoded so a vendor
    change is a config edit.
    """
    from awltux.config import get_settings as _get

    prices = _get().llm.prices.get(model)
    if not prices:
        # Unknown model: fall back to the dearest configured rate so an
        # unrecognised name cannot silently under-report spend.
        worst = max(
            (p.get("input", 0.0) for p in _get().llm.prices.values()), default=0.0
        )
        prices = {"input": worst, "input_cached": worst, "output": worst}

    uncached = max(input_tokens - cached, 0)
    return (
        uncached / 1_000_000 * prices.get("input", 0.0)
        + cached / 1_000_000 * prices.get("input_cached", 0.0)
        + output_tokens / 1_000_000 * prices.get("output", 0.0)
    )


def month_to_date_spend() -> float:
    """Total recorded spend in the current calendar month (UTC)."""
    now = dt.datetime.now(dt.UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as session:
        total = session.execute(
            select(func.coalesce(func.sum(LLMCall.cost_usd), 0.0))
            .where(LLMCall.created_at >= start)
            .where(LLMCall.ok.is_(True))
        ).scalar_one()
    return float(total or 0.0)


def build_messages(
    *,
    system: str,
    document: str | None,
    instruction: str,
    examples: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Order the prompt so the large, stable part is a cacheable prefix.

    The system message and the document come first and are byte-identical across
    calls about the same filing, so DeepSeek's prefix cache can hit. The
    per-call instruction comes last, where its variability costs nothing.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if document:
        messages.append(
            {"role": "user", "content": f"<document>\n{document}\n</document>"}
        )
    for example in examples or []:
        messages.append({"role": example.get("role", "user"), "content": example.get("content", "")})
    messages.append({"role": "user", "content": instruction})
    return messages


class DeepSeekClient:
    """Thin OpenAI-compatible client with accounting and a spend ceiling."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: HttpClient | None = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.env.deepseek_api_key)

    def client(self) -> HttpClient:
        if self._client is None:
            if not self.configured:
                raise ProviderNotConfigured("DeepSeek", "deepseek_api_key")
            key = self.settings.env.require("DeepSeek", "deepseek_api_key")
            self._client = HttpClient(
                SOURCE,
                settings=self.settings,
                base_url=self.settings.env.deepseek_base_url,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    # -------------------------------------------------------------- spending
    def _check_budget(self, estimated_cost: float) -> None:
        ceiling = self.settings.llm.monthly_budget_usd
        if ceiling <= 0:
            return
        spent = month_to_date_spend()
        if spent + estimated_cost > ceiling:
            raise BudgetExceeded(
                f"monthly DeepSeek budget of ${ceiling:.2f} would be exceeded "
                f"(spent ${spent:.2f}, next call ~${estimated_cost:.4f})"
            )

    # ------------------------------------------------------------------ call
    def complete(
        self,
        *,
        purpose: str,
        messages: list[dict[str, str]],
        model: str | None = None,
        json_mode: bool = True,
        max_tokens: int | None = None,
        temperature: float | None = None,
        prompt_hash: str | None = None,
    ) -> Completion:
        """Run one chat completion, recording tokens and cost either way."""
        settings = self.settings
        chosen_model = model or settings.llm.model_bulk

        # Conservative pre-flight: assume the whole prompt is a cache miss and a
        # full-length completion, so the ceiling cannot be breached by a surprise.
        prompt_chars = sum(len(message.get("content", "")) for message in messages)
        estimated_input = int(prompt_chars / 3.4)
        estimated_output = max_tokens or settings.llm.max_output_tokens
        self._check_budget(estimate_cost(chosen_model, estimated_input, estimated_output))

        body: dict[str, Any] = {
            "model": chosen_model,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None else settings.llm.temperature
            ),
            "max_tokens": max_tokens or settings.llm.max_output_tokens,
            "stream": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        started = time.perf_counter()
        # Give up this thread's SQLite write lock before the request. A model call
        # takes seconds to tens of seconds, and a job that holds the write lock
        # across one fails every other writer with "database is locked" after
        # busy_timeout -- including the insert that records this very call.
        release_before_network()
        try:
            result = self.client().post(
                "/chat/completions",
                json_body=body,
                retries=settings.llm.max_retries,
            )
            payload = result.json()
        except ProviderError as exc:
            self._record_failure(purpose, chosen_model, messages, exc, prompt_hash)
            raise DeepSeekError(str(exc)) from exc
        except Exception as exc:
            self._record_failure(purpose, chosen_model, messages, exc, prompt_hash)
            raise DeepSeekError(f"unexpected failure: {exc}") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._record_success(
            purpose, chosen_model, payload, latency_ms, prompt_hash, messages
        )

    # ------------------------------------------------------------- accounting
    def _record_success(
        self,
        purpose: str,
        model: str,
        payload: Any,
        latency_ms: int,
        prompt_hash: str | None,
        messages: list[dict[str, str]],
    ) -> Completion:
        if not isinstance(payload, dict):
            raise DeepSeekError("unexpected response shape from DeepSeek")

        choices = payload.get("choices") or []
        if not choices:
            raise DeepSeekError("DeepSeek returned no choices")

        message = choices[0].get("message") or {}
        text = str(message.get("content") or "")
        finish_reason = choices[0].get("finish_reason")

        usage = payload.get("usage") or {}
        input_tokens = _int_or_none(usage.get("prompt_tokens"))
        output_tokens = _int_or_none(usage.get("completion_tokens"))
        cached_tokens = _int_or_none(
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
            or usage.get("prompt_cache_hit_tokens")
        )

        cost = None
        if input_tokens is not None and output_tokens is not None:
            cost = estimate_cost(model, input_tokens, output_tokens, cached_tokens or 0)

        call_id = self._write_call(
            purpose=purpose,
            model=model,
            prompt_hash=prompt_hash,
            ok=True,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            error=None,
            # Truncate the prompt: it is the document, and the document is already
            # archived under data/raw. Keeping it here would bloat the table.
            request_json=_excerpt(messages),
            response_json=text[:4000],
        )

        if finish_reason == "length":
            logger.warning(
                "DeepSeek completion for %s hit the token limit; output is truncated",
                purpose,
            )

        return Completion(
            text=text,
            model=model,
            input_tokens=input_tokens,
            cached_input_tokens=cached_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            llm_call_id=call_id,
            raw=payload,
            finish_reason=finish_reason,
        )

    def _record_failure(
        self,
        purpose: str,
        model: str,
        messages: list[dict[str, str]],
        exc: Exception,
        prompt_hash: str | None,
    ) -> None:
        self._write_call(
            purpose=purpose,
            model=model,
            prompt_hash=prompt_hash,
            ok=False,
            input_tokens=None,
            cached_input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            latency_ms=None,
            error=str(exc)[:1000],
            request_json=_excerpt(messages),
            response_json=None,
        )

    @staticmethod
    def _write_call(**fields: Any) -> int | None:
        """Persist one call. Never raises, and never poisons the caller.

        Two things this gets right:

        * ``provider`` is supplied here rather than by each caller, because it is
          NOT NULL on the model and a caller that forgot it crashed the whole
          accounting path.
        * The insert runs inside a **savepoint**. ``session_scope`` is re-entrant,
          so this joins the caller's transaction -- meaning a failed insert would
          otherwise roll back the very decision it was trying to record and leave
          the session unusable for everything after it, which is exactly what a
          missing ``provider`` did.
        """
        try:
            with session_scope() as session:
                with session.begin_nested():
                    row = LLMCall(provider=SOURCE, **fields)
                    session.add(row)
                    session.flush()
                return row.id
        except Exception:  # pragma: no cover - accounting is best-effort
            logger.exception("failed to record DeepSeek call")
            return None


def _excerpt(messages: list[dict[str, str]], limit: int = 2000) -> dict[str, Any]:
    return {
        "messages": [
            {"role": m.get("role"), "content": (m.get("content") or "")[:limit]}
            for m in messages
        ],
        "truncated": True,
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def model_for_purpose(settings: Settings, purpose: str) -> str:
    """Route work to the cheap model unless the purpose needs deep reading.

    Full-document filing extraction is the only task that justifies the expensive
    model: everything else is classification or summarisation where the cheap
    model performs comparably for a fraction of the cost.
    """
    deep_purposes = {"filing_extraction", "account_analysis"}
    return settings.llm.model_deep if purpose in deep_purposes else settings.llm.model_bulk


@dataclass(slots=True)
class SpendReport:
    """Spend summary for the operations page."""

    month_to_date_usd: float = 0.0
    ceiling_usd: float = 0.0
    calls: int = 0
    by_purpose: dict[str, float] = field(default_factory=dict)

    @property
    def remaining_usd(self) -> float:
        return max(self.ceiling_usd - self.month_to_date_usd, 0.0)

    @property
    def fraction_used(self) -> float:
        if self.ceiling_usd <= 0:
            return 0.0
        return min(self.month_to_date_usd / self.ceiling_usd, 1.0)


def spend_report(settings: Settings | None = None) -> SpendReport:
    settings = settings or get_settings()
    now = dt.datetime.now(dt.UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    with session_scope() as session:
        rows = session.execute(
            select(LLMCall.purpose, func.sum(LLMCall.cost_usd), func.count())
            .where(LLMCall.created_at >= start)
            .group_by(LLMCall.purpose)
        ).all()

    report = SpendReport(ceiling_usd=settings.llm.monthly_budget_usd)
    for purpose, cost, count in rows:
        report.by_purpose[purpose or "unknown"] = float(cost or 0.0)
        report.calls += int(count or 0)
    report.month_to_date_usd = sum(report.by_purpose.values())
    return report
