"""The research result set, and the XHTML document it is kept as.

**The metrics half is not a new schema.** A research report is asked for cited figures, and
they are validated by :func:`awltux.llm.extractors.validate_extraction` -- the same function,
the same canonical vocabulary and the same "a number is cited or absent" rule that every
filing extraction already passes through. That is what makes the result set *compatible with
the analysis database* rather than merely similar to it: the figures reach
:class:`~awltux.db.FundamentalPeriod` through the same writer, with the same provenance and
the same refusal when the document did not say what units it used.

**The document is ours, not the model's.** The model returns structured sections and we render
the XHTML around them. A model-authored document would be an injection surface in a file this
application serves from its own origin, and there is no sanitiser in the dependency list to
strip one with; structured fields plus autoescaping make the question moot rather than
answered. The file is written as XHTML and *is* XHTML -- `tests/test_research.py` parses it
with an XML parser, which is the only definition that is checkable.

**A qualitative claim without a quotation is dropped.** The same rule as a figure without a
citation, and for the same reason: "this management is candid" that cannot point at anything
is an impression, and an impression in a document that looks like evidence is worse than an
absence. Every strength and every concern carries a verbatim span and where it came from, or
it does not go in.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from awltux.config import Settings
from awltux.llm.extractors import ExtractionResult, validate_extraction

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"

#: The verdict vocabulary. `insufficient_evidence` is a *stated answer* rather than a
#: failure -- "the material does not settle this" is the common and correct conclusion for a
#: company nobody has filed much about, and it must be sayable.
VERDICTS = ("attractive", "watch", "unattractive", "insufficient_evidence")
DEFAULT_VERDICT = "insufficient_evidence"
HORIZONS = ("long_term", "short_term", "both", "neither")
RISKS = ("low", "moderate", "high", "very_high")
DIRECTIONS = ("positive", "negative", "mixed", "neutral")

#: The shortest span a strength or a concern may rely on. Below this it is a word or two, which
#: is enough to be quoted out of context and not enough to be checkable -- the same reasoning
#: `llm.extractors.MIN_SPAN_CHARS` records for figures.
MIN_POINT_SPAN_CHARS = 12


@dataclass(slots=True)
class Point:
    """One strength or concern, with the words it rests on."""

    point: str
    evidence: str
    source: str = ""
    location: str = ""

    def as_dict(self) -> dict[str, Any]:
        """The stored shape, written out rather than derived from the fields.

        Spelled out because this crosses an interface: it is what the result set holds and
        what the API returns, so a rename above should be a decision here, not a side effect
        of the rename.
        """
        return {
            "point": self.point,
            "evidence": self.evidence,
            "source": self.source,
            "location": self.location,
        }


@dataclass(slots=True)
class NewsTheme:
    """What the news is collectively saying, and which stories say it."""

    theme: str
    direction: str
    basis: list[str] = field(default_factory=list)
    corroboration: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "theme": self.theme,
            "direction": self.direction,
            "basis": self.basis,
            "corroboration": self.corroboration,
        }


@dataclass(slots=True)
class Section:
    """One prose section of the report, as the model structured it."""

    heading: str
    paragraphs: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.paragraphs or self.bullets or self.rows)

    def as_dict(self) -> dict[str, Any]:
        """The stored shape. The table nests because a column heading belongs to its rows."""
        return {
            "heading": self.heading,
            "paragraphs": self.paragraphs,
            "bullets": self.bullets,
            "table": {"columns": self.columns, "rows": self.rows},
        }


@dataclass(slots=True)
class ResearchResult:
    """A validated report. Everything here survived its own rule or is not here."""

    executive_summary: str | None = None
    verdict: str = DEFAULT_VERDICT
    confidence: float | None = None
    suitability: dict[str, Any] = field(default_factory=dict)
    business: dict[str, Any] = field(default_factory=dict)
    management: dict[str, Any] = field(default_factory=dict)
    strengths: list[Point] = field(default_factory=list)
    concerns: list[Point] = field(default_factory=list)
    news_themes: list[NewsTheme] = field(default_factory=list)
    what_would_change_my_mind: str = ""
    sections: list[Section] = field(default_factory=list)
    sources_seen: list[str] = field(default_factory=list)
    extraction: ExtractionResult = field(default_factory=ExtractionResult)
    injection_suspected: bool = False
    #: Everything the model sent that this module refused, named. Reported in the document's
    #: provenance section, because a silent drop is indistinguishable from a model that never
    #: answered.
    discarded: list[str] = field(default_factory=list)

    @property
    def metrics(self) -> dict[str, float]:
        """The cited figures, in the shape `FundamentalPeriod` stores."""
        return dict(self.extraction.metric_values)

    def as_dict(self) -> dict[str, Any]:
        """The result set as stored on the row, which is also what the API returns."""
        return {
            "executive_summary": self.executive_summary,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "suitability": self.suitability,
            "business": self.business,
            "management": self.management,
            "strengths": [point.as_dict() for point in self.strengths],
            "concerns": [point.as_dict() for point in self.concerns],
            "news_themes": [theme.as_dict() for theme in self.news_themes],
            "what_would_change_my_mind": self.what_would_change_my_mind,
            "sections": [section.as_dict() for section in self.sections],
            "sources_seen": self.sources_seen,
            "reporting_currency": self.extraction.reporting_currency,
            "units": self.extraction.units,
            "period_end": self.extraction.period_end,
            "period_type": self.extraction.period_type,
            "metrics": self.extraction.metrics_for_storage,
            "unlisted_metrics": self.extraction.unlisted_for_storage,
            "injection_suspected": self.injection_suspected,
            "discarded": self.discarded,
        }


def _text(value: Any) -> str | None:
    """A string from whatever the model sent, or ``None``."""
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [text for text in (_text(item) for item in value) if text]
    return out


def _clamp(value: Any, low: float, high: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return min(max(number, low), high)


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def _cites_a_headline(basis: list[str], known: list[str]) -> bool:
    """Whether any of the theme's claims appears in a headline the digest carried.

    Substring rather than equality because the model cites a headline from memory and drops a
    word or a trailing clause; equality would refuse a correct citation for punctuation.
    """
    return any(
        _normalise(item) in known_headline for item in basis for known_headline in known
    )


def _points(raw: Any, label: str, discarded: list[str]) -> list[Point]:
    """Strengths or concerns, each dropped unless it quotes something.

    The span rule is enforced here rather than described in the prompt alone, for the reason
    the extraction layer records: a rule that is only asked for is a rule that is sometimes
    not followed, and the failure is invisible afterwards because the document looks complete.
    """
    if not isinstance(raw, list):
        return []
    out: list[Point] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            discarded.append(f"{label} {index}: not an object")
            continue
        point = _text(entry.get("point"))
        evidence = _text(entry.get("evidence"))
        if not point:
            discarded.append(f"{label} {index}: no point stated")
            continue
        if not evidence or len(evidence) < MIN_POINT_SPAN_CHARS:
            discarded.append(f"{label} {index}: no quoted evidence ({point[:60]})")
            continue
        out.append(
            Point(
                point=point,
                evidence=evidence,
                source=_text(entry.get("source")) or "",
                location=_text(entry.get("location")) or "",
            )
        )
    return out


def _themes(raw: Any, headlines: list[str], discarded: list[str]) -> list[NewsTheme]:
    """News themes, each dropped unless it cites a headline the digest actually contained.

    Asked for directly: *"use critical thinking and use news analysis results to guide their
    importance and relevance."* The theme is the model's synthesis; the basis is what makes it
    checkable, and a theme whose basis appears nowhere in the digest is a summary of something
    the model brought with it.
    """
    if not isinstance(raw, list):
        return []
    known = [_normalise(headline) for headline in headlines]
    out: list[NewsTheme] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            discarded.append(f"news theme {index}: not an object")
            continue
        theme = _text(entry.get("theme"))
        if not theme:
            discarded.append(f"news theme {index}: no theme stated")
            continue
        basis = _strings(entry.get("basis"))
        if not basis or not _cites_a_headline(basis, known):
            discarded.append(f"news theme {index}: cites no headline from the digest ({theme[:60]})")
            continue
        direction = (_text(entry.get("direction")) or "neutral").lower()
        out.append(
            NewsTheme(
                theme=theme,
                direction=direction if direction in DIRECTIONS else "neutral",
                basis=basis,
                corroboration=_text(entry.get("corroboration")) or "",
            )
        )
    return out


def _sections(raw: Any, discarded: list[str]) -> list[Section]:
    """The prose body. A section with nothing in it is not rendered and not an error."""
    if not isinstance(raw, list):
        return []
    out: list[Section] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            discarded.append(f"section {index}: not an object")
            continue
        heading = _text(entry.get("heading"))
        if not heading:
            discarded.append(f"section {index}: no heading")
            continue
        table = entry.get("table") if isinstance(entry.get("table"), dict) else {}
        columns = _strings(table.get("columns"))
        rows: list[list[str]] = []
        for row in table.get("rows") or []:
            cells = _strings(row) if isinstance(row, list) else []
            if len(cells) != len(columns):
                discarded.append(f"section {index} ('{heading[:40]}'): a row does not match its columns")
                continue
            rows.append(cells)
        section = Section(
            heading=heading,
            paragraphs=_strings(entry.get("paragraphs")),
            bullets=_strings(entry.get("bullets")),
            columns=columns if rows else [],
            rows=rows,
        )
        if not section.empty:
            out.append(section)
    return out


def validate_result(
    payload: Any, *, vocabulary: Any = None, headlines: list[str] | None = None
) -> ResearchResult:
    """Turn a model answer into a result set, dropping whatever does not meet its rule.

    Never raises on a bad field: a report with three good sections and a missing verdict is
    worth keeping, and the alternative -- refusing the whole document over one field -- throws
    away the model call that produced it. What is dropped is named in ``discarded`` and
    printed in the report's own provenance section, so an omission is visible rather than
    silent.

    ``vocabulary`` is the metric vocabulary this call was asked with
    (`analysis/metric_fields.load`), passed straight to :func:`validate_extraction` so the
    gate and the prompt agree -- the failure that function's docstring records.
    """
    result = ResearchResult()
    if not isinstance(payload, dict):
        result.discarded.append("the response was not a JSON object")
        return result

    result.executive_summary = _text(payload.get("executive_summary"))
    if not result.executive_summary:
        result.discarded.append("no executive summary")

    verdict = (_text(payload.get("verdict")) or "").lower()
    if verdict in VERDICTS:
        result.verdict = verdict
    else:
        result.discarded.append(f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")

    result.confidence = _clamp(payload.get("confidence"), 0.0, 1.0)

    suitability = payload.get("suitability")
    if isinstance(suitability, dict):
        horizon = (_text(suitability.get("horizon")) or "").lower()
        risk = (_text(suitability.get("risk")) or "").lower()
        result.suitability = {
            "horizon": horizon if horizon in HORIZONS else None,
            "risk": risk if risk in RISKS else None,
            "reason": _text(suitability.get("reason")),
        }
    else:
        result.discarded.append("no suitability block")

    for name in ("business", "management"):
        block = payload.get(name)
        if isinstance(block, dict):
            setattr(
                result,
                name,
                {
                    key: (value if isinstance(value, list) else _text(value))
                    for key, value in block.items()
                    if value not in (None, "", [])
                },
            )
        elif block is not None:
            result.discarded.append(f"{name} was not an object")

    result.strengths = _points(payload.get("strengths"), "strength", result.discarded)
    result.concerns = _points(payload.get("concerns"), "concern", result.discarded)
    result.news_themes = _themes(payload.get("news_themes"), headlines or [], result.discarded)
    result.what_would_change_my_mind = _text(payload.get("what_would_change_my_mind")) or ""
    result.sections = _sections(payload.get("sections"), result.discarded)
    result.sources_seen = _strings(payload.get("sources_seen"))
    result.injection_suspected = bool(payload.get("injection_suspected"))

    # The metrics half, through the validator every filing extraction already passes through.
    result.extraction = validate_extraction(
        payload, allowed=vocabulary if vocabulary is not None else None
    )
    result.discarded.extend(result.extraction.discarded)
    return result


#: One environment for the process. `autoescape` is the whole safety story for the document:
#: every field above is text the model wrote, and it is escaped on the way into the markup.
_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_xhtml(
    result: ResearchResult,
    *,
    subject_label: str,
    prompt: str,
    model: str | None,
    created: dt.datetime,
    inventory: dict[str, Any] | None = None,
    refresh: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    problems: list[str] | None = None,
) -> str:
    """The report as a well-formed XHTML document.

    Everything the reader needs to argue with the report is in the provenance footer: the
    prompt's hash so the wording can be identified, the model, whether the data was refreshed
    and what that refresh did, how much news there was and how much of it carried an
    appraisal, what was read, what was missing, and what was discarded on the way in.
    """
    template = _ENV.get_template("report.xhtml")
    return template.render(
        result=result,
        subject_label=subject_label,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        model=model or "unknown",
        created=created.strftime("%Y-%m-%d %H:%M UTC"),
        created_iso=created.isoformat(),
        inventory=inventory or {},
        refresh=refresh or {},
        news=news or {},
        problems=list(problems or []),
        generation="AwltuxTrading deep-dive research",
    )


def report_path(
    settings: Settings, *, subject_type: str, subject_id: str, report_id: int
) -> Path:
    """Where one report lives on disk.

    Nested by subject so a company's history reads in one place, and keyed by the row id --
    which is unique and stable, unlike a title or a date. Written under the data volume, which
    is also what keeps it out of git: `docs/research/` is a different thing and is asserted to
    be tracked.
    """
    safe_type = subject_type if subject_type in ("instrument", "sector") else "other"
    safe_id = "".join(char for char in subject_id if char.isalnum() or char in "-_") or "unknown"
    return settings.research_dir / safe_type / safe_id / f"{report_id}.xhtml"


def write_report(path: Path, document: str) -> int:
    """Write the document and return its size in bytes.

    Created with an explicit UTF-8 encoding, because the report is prose and the container's
    locale is not a thing to leave a document's encoding to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = document.encode("utf-8")
    path.write_bytes(data)
    return len(data)
