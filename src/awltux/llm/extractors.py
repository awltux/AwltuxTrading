"""Filing extraction and summarisation.

The critical property here is **citation discipline**. A language model asked to
extract a revenue figure will produce one whether or not the document contains it,
so every metric is required to carry the quoted span and location it came from,
and anything uncited is discarded.

That is what lets the rest of the system treat extracted figures as evidence
rather than as model output. A number with a citation can be checked; a number
without one cannot, and in a valuation an unchecked number is worse than a
missing one because it is invisible.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from awltux.config import Settings, get_settings
from awltux.llm.deepseek import (
    BudgetExceeded,
    DeepSeekClient,
    DeepSeekError,
    build_messages,
    model_for_purpose,
)
from awltux.llm.prompts import (
    FILING_EXTRACTION_INSTRUCTION,
    FILING_EXTRACTION_SYSTEM,
    FILING_SUMMARY_INSTRUCTION,
    FILING_SUMMARY_SYSTEM,
    prompt_fingerprint,
)

logger = logging.getLogger(__name__)

#: Canonical metric names the valuation model reads. An extraction that invents a
#: key outside this set is discarded, because the model would read it as missing.
CANONICAL_METRICS = frozenset(
    {
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "ebitda",
        "eps_diluted",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "total_debt",
        "cash_and_equivalents",
        "operating_cash_flow",
        "capex",
        "free_cash_flow",
        "dividends_paid",
        "shares_outstanding",
        "dividend_per_share",
        "interest_expense",
        "current_liabilities",
        "current_assets",
    }
)

EXTRACTION_PURPOSE = "filing_extraction"
SUMMARY_PURPOSE = "filing_summary"

#: A span shorter than this is too short to verify the figure against.
MIN_SPAN_CHARS = 12


@dataclass(slots=True)
class ExtractedMetric:
    name: str
    value: float
    span: str
    location: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "span": self.span,
            "location": self.location,
            "source": "llm_extraction",
        }


@dataclass(slots=True)
class ExtractionResult:
    metrics: dict[str, ExtractedMetric] = field(default_factory=dict)
    quality_notes: list[str] = field(default_factory=list)
    risk_factors: list[str] = field(default_factory=list)
    accounting_policy_changes: list[str] = field(default_factory=list)
    going_concern_language: dict[str, Any] | None = None
    guidance: dict[str, Any] | None = None
    reporting_currency: str | None = None
    units: str | None = None
    period_end: str | None = None
    period_type: str | None = None
    injection_suspected: bool = False
    confidence: float = 0.0
    discarded: list[str] = field(default_factory=list)
    llm_call_id: int | None = None

    @property
    def metrics_for_storage(self) -> dict[str, dict[str, Any]]:
        """Metric-keyed provenance map, the shape ``metric_sources`` expects."""
        return {name: metric.as_dict() for name, metric in self.metrics.items()}

    @property
    def metric_values(self) -> dict[str, float]:
        return {name: metric.value for name, metric in self.metrics.items()}

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics_for_storage,
            "quality_notes": self.quality_notes,
            "risk_factors": self.risk_factors,
            "accounting_policy_changes": self.accounting_policy_changes,
            "going_concern_language": self.going_concern_language,
            "guidance": self.guidance,
            "reporting_currency": self.reporting_currency,
            "units": self.units,
            "period_end": self.period_end,
            "period_type": self.period_type,
            "injection_suspected": self.injection_suspected,
            "confidence": self.confidence,
            "discarded_uncited": self.discarded,
        }


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def validate_extraction(payload: dict[str, Any]) -> ExtractionResult:
    """Enforce citation discipline on a model response.

    Each metric must have a numeric value, a quoted span of at least
    :data:`MIN_SPAN_CHARS`, and a location. Anything else is dropped and its name
    recorded in ``discarded`` so the omission is visible rather than silent.
    """
    result = ExtractionResult()
    if not isinstance(payload, dict):
        return result

    result.reporting_currency = _text(payload.get("reporting_currency"))
    result.units = _text(payload.get("units"))
    result.period_end = _text(payload.get("period_end"))
    result.period_type = _text(payload.get("period_type"))
    result.injection_suspected = bool(payload.get("injection_suspected"))
    result.confidence = _clamp(payload.get("extraction_confidence"), 0.0, 1.0) or 0.0

    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        for name, entry in metrics.items():
            if name not in CANONICAL_METRICS:
                result.discarded.append(f"{name}: not a canonical metric name")
                continue
            if not isinstance(entry, dict):
                result.discarded.append(f"{name}: malformed entry")
                continue
            value = _as_float(entry.get("value"))
            span = _text(entry.get("span")) or ""
            location = _text(entry.get("location")) or ""

            if value is None:
                result.discarded.append(f"{name}: no numeric value")
                continue
            if len(span.strip()) < MIN_SPAN_CHARS:
                result.discarded.append(f"{name}: missing or too-short source span")
                continue
            if not location:
                result.discarded.append(f"{name}: no location given")
                continue

            result.metrics[name] = ExtractedMetric(
                name=name, value=value, span=span.strip()[:500], location=location[:200]
            )

    result.quality_notes = _string_list(payload.get("quality_notes"))
    result.risk_factors = _string_list(payload.get("risk_factors"))
    result.accounting_policy_changes = _string_list(payload.get("accounting_policy_changes"))

    going_concern = payload.get("going_concern_language")
    if isinstance(going_concern, dict):
        result.going_concern_language = {
            "present": bool(going_concern.get("present")),
            "span": _text(going_concern.get("span")),
        }

    guidance = payload.get("guidance")
    if isinstance(guidance, dict):
        result.guidance = {
            "stated": bool(guidance.get("stated")),
            "summary": _text(guidance.get("summary")),
        }

    if result.injection_suspected:
        logger.warning(
            "the extraction model reported a suspected prompt-injection attempt "
            "inside a filing"
        )
    if result.discarded:
        logger.info("discarded %d uncited metric(s)", len(result.discarded))
    return result


def extract_filing(
    document: str,
    *,
    company_name: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
    max_document_chars: int = 400_000,
) -> ExtractionResult | None:
    """Extract cited metrics from one filing.

    The document is truncated from the middle if it is enormous, keeping the
    front (where primary statements usually sit) and the back (notes and
    going-concern language) rather than blindly cutting the tail.
    """
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured or not document.strip():
        return None

    trimmed, was_truncated = _truncate_middle(document, max_document_chars)
    header = f"Company: {company_name}\n"
    if was_truncated:
        header += (
            "NOTE: the document was truncated in the middle for length. "
            "Only report figures you can see.\n"
        )

    messages = build_messages(
        system=FILING_EXTRACTION_SYSTEM,
        document=header + trimmed,
        instruction=FILING_EXTRACTION_INSTRUCTION,
    )

    try:
        completion = client.complete(
            purpose=EXTRACTION_PURPOSE,
            messages=messages,
            model=model_for_purpose(settings, EXTRACTION_PURPOSE),
            json_mode=True,
            prompt_hash=prompt_fingerprint(FILING_EXTRACTION_SYSTEM),
        )
        payload = completion.json_object()
    except BudgetExceeded as exc:
        logger.warning("filing extraction paused: %s", exc)
        return None
    except DeepSeekError as exc:
        logger.warning("filing extraction failed for %s: %s", company_name, exc)
        return None

    result = validate_extraction(payload)
    result.llm_call_id = completion.llm_call_id
    return result


def summarise_filing(
    document: str,
    *,
    company_name: str,
    client: DeepSeekClient | None = None,
    settings: Settings | None = None,
    max_document_chars: int = 300_000,
) -> dict[str, Any] | None:
    """Produce the analyst-facing summary that goes into the decision state."""
    settings = settings or get_settings()
    client = client or DeepSeekClient(settings)
    if not client.configured or not document.strip():
        return None

    trimmed, _ = _truncate_middle(document, max_document_chars)
    messages = build_messages(
        system=FILING_SUMMARY_SYSTEM,
        document=f"Company: {company_name}\n\n{trimmed}",
        instruction=FILING_SUMMARY_INSTRUCTION,
    )

    try:
        completion = client.complete(
            purpose=SUMMARY_PURPOSE,
            messages=messages,
            model=model_for_purpose(settings, SUMMARY_PURPOSE),
            json_mode=True,
            prompt_hash=prompt_fingerprint(FILING_SUMMARY_SYSTEM),
        )
        payload = completion.json_object()
    except BudgetExceeded as exc:
        logger.warning("filing summarisation paused: %s", exc)
        return None
    except DeepSeekError as exc:
        logger.warning("filing summarisation failed for %s: %s", company_name, exc)
        return None

    payload["llm_call_id"] = completion.llm_call_id
    return payload


def _truncate_middle(text: str, limit: int) -> tuple[str, bool]:
    """Keep the head and tail, drop the middle. Returns ``(text, was_truncated)``."""
    if len(text) <= limit:
        return text, False
    head = int(limit * 0.6)
    tail = limit - head
    return (
        text[:head]
        + "\n\n[... document truncated for length ...]\n\n"
        + text[-tail:],
        True,
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _text(item)
        if text:
            out.append(text[:500])
    return out


def _clamp(value: Any, low: float, high: float) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    return max(low, min(high, number))
