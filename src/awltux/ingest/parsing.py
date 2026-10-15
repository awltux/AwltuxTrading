"""Read the filings we have downloaded, so their figures and events are usable.

The acquisition side of this has existed for a while -- documents are fetched, hashed and
kept -- and nothing ever read them. `Filing.parsed` and `extractor_version` were columns
on the model that no code wrote, so every filing sat at ``fetched`` for ever and the
decision engine's `_extracted_facts` always received ``None``. Measured 2026-10-07: 4,958
filing rows, 601 documents held, **zero** parsed.

That matters because of what the extractor returns and who consumes it. A filing is the
one source that states *events* -- an auditor resigned, the accounts were restated,
there is going-concern language -- and ``decision/service.py`` already prompts with
``filing.parsed["extraction"]["filing_events"]``. Those sentences are the strongest
evidence the system can hold, because each is something a professional was obliged to
say rather than a ratio this codebase inferred, and the gate was reading a column that
was always empty.

**One attempt per document.** A parsed filing is not re-read (``status`` moves to
``parsed``), and a failure moves it to ``failed`` with the reason stored rather than
being retried every run: this is a paid model call over a document that can be hundreds
of thousands of characters, and a document that failed once will usually fail again.
Re-reading one is a deliberate act, not something a scheduler does hourly.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import Filing, FundamentalPeriod, Instrument
from awltux.llm.extractors import extract_filing, summarise_filing
from awltux.metrics import NON_MONETARY_METRICS
from awltux.scheduler import progress

logger = logging.getLogger(__name__)

#: The extensions we can turn into text. EDGAR's primary documents are HTML, and a
#: handful are plain text. **PDF is deliberately absent**: there is no PDF text
#: extractor in this project's dependencies, and guessing at one would be a silent
#: failure that looks like "this filing reported nothing".
TEXT_SUFFIXES = (".htm", ".html", ".txt", ".xml")

#: The word saved to `Filing.extractor_version`. Bump when the prompt or the validator
#: changes shape, so a stored extraction can be told from one made by older rules.
EXTRACTOR_VERSION = "filing-extraction/v1"

#: Documents to read in one scoped run. A refresh is about one company, which has one or
#: two annual reports on file, so this is a bound on a surprise rather than a ration.
PARSE_LIMIT = 4

#: Above this, a *scaled* share count is not a share count. The largest listed companies have
#: tens of billions of shares; a trillion is past any of them, and a scaled count that lands
#: there means the model had already stated the count in units. See `_scale_metric`.
MAX_PLAUSIBLE_SHARES = 1e12

#: A number in a quoted span, thousands separators and all.
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def document_text(path: Path) -> str | None:
    """The text of a downloaded document, or ``None`` if it cannot be read as text.

    ``None`` rather than raising, and rather than an empty string: "we hold no text
    extractor for this format" and "the document says nothing" are different findings,
    and collapsing them is how a PDF becomes a company with no disclosures.
    """
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 decodes every byte sequence
        return None
    if path.suffix.lower() == ".txt":
        return decoded
    # The markup is stripped because the extractor reads prose, and an inline-XBRL
    # document is mostly tags: leaving them in spends the model's context on attribute
    # names and, worse, on numbers that appear only as attribute values.
    soup = BeautifulSoup(decoded, "html.parser")
    # Inline XBRL keeps all of its taxonomy plumbing in one `ix:header`: the context, unit
    # and hidden-fact definitions. BeautifulSoup returns them as *text* because they are
    # elements rather than attributes, and they sit at the very *front* of the document --
    # which is the part `llm.extractors.truncate_middle` keeps first, so the waste is spent
    # before any prose is reached. Measured on Microsoft's FY2026 10-K: 34,137 of 357,714
    # characters, 9.5% of the whole document and 100% of its first 34,142; with the header
    # dropped the first prose is 5 characters in.
    for header in soup.find_all("ix:header"):
        header.decompose()
    text = soup.get_text(" ", strip=True)
    if text:
        return text
    # An unclosed `<ix:header>` swallows everything after it, and this parser is tolerant
    # because EDGAR serves documents that are not well-formed XML. Returning `""` there would
    # read as a company that disclosed nothing -- `_read_one` records exactly that as "the
    # stored document could not be read as text" -- so the fallback is the un-stripped text,
    # which is worse to read and better than a filing that looks empty.
    logger.warning("no text outside the ix:header in %s; keeping the header", path)
    return BeautifulSoup(decoded, "html.parser").get_text(" ", strip=True)


def _candidates(session: Session, tickers: list[str] | None, limit: int) -> list[Filing]:
    """Held documents nothing has read yet, newest filing first.

    ``status == "fetched"`` is exactly "downloaded and not parsed": the acquisition job
    sets it once the bytes are on disk, and this job moves it on. ``failed`` is excluded
    so a document that defeated the extractor is not attempted on every run.
    """
    statement = (
        select(Filing)
        .where(Filing.status == "fetched")
        .where(Filing.raw_path.is_not(None))
        # `IS NULL` first so a filing with no date sorts last, then newest first. The
        # same portable idiom `load_price_targets` uses rather than NULLS LAST, which
        # SQLite only gained in 3.30.
        .order_by(Filing.filed_at.is_(None), Filing.filed_at.desc())
        .limit(limit)
    )
    if tickers is not None:
        statement = statement.where(Filing.instrument_t212_ticker.in_(list(tickers)))
    return list(session.execute(statement).scalars().all())


def extract_held_filings(
    session: Session,
    *,
    tickers: list[str] | None = None,
    limit: int = PARSE_LIMIT,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Read each unparsed held filing, storing the extraction against its row.

    Returns a summary dict shaped like the other ingest reports, so the refresh can
    report it without a second vocabulary.
    """
    settings = settings or get_settings()
    report: dict[str, Any] = {
        "attempted": 0,
        "parsed": 0,
        "skipped_no_text": 0,
        "failed": 0,
        "errors": [],
        "events": 0,
    }

    filings = _candidates(session, tickers, limit)
    total = len(filings)
    # The vocabulary this run may ask for: the canonical names plus whatever earlier
    # filings have revealed. Loaded once, because nothing in this job adds to it -- the
    # gate and the prompt must agree, and they agree by being built from this mapping.
    from awltux.analysis.metric_fields import load as load_fields

    vocabulary = load_fields(session)
    report["vocabulary"] = len(vocabulary)
    for position, filing in enumerate(filings, start=1):
        report["attempted"] += 1
        progress.note(
            f"{position} of {total}: {filing.instrument_t212_ticker} {filing.filing_type}"
        )
        _read_one(session, filing, vocabulary=vocabulary, settings=settings, report=report)

    logger.info("filing extraction: %s", {k: v for k, v in report.items() if k != "errors"})
    return report


def _read_one(
    session: Session,
    filing: Filing,
    *,
    vocabulary: dict[str, Any],
    settings: Settings,
    report: dict[str, Any],
) -> None:
    """Read one filing's document and record what it says against the row.

    Its own function because the four outcomes -- no text, the call failed, the call
    returned nothing, parsed -- are each a different decision about the filing's status,
    and reading them in the loop that walks the batch hid the rule that they are *not* the
    same: only a parsed document is retired, and the rest must be retried.
    """
    name = _company_name(session, filing.instrument_t212_ticker)
    document = document_text(settings.data_dir / (filing.raw_path or ""))
    if not document:
        filing.status = "skipped"
        filing.error = (
            "no text extractor for this document"
            if (filing.raw_path or "").lower().endswith(".pdf")
            else "the stored document could not be read as text"
        )
        report["skipped_no_text"] += 1
        session.flush()
        return

    # The lock is released before the model call, for the same reason every other job
    # does it: this is a network round trip measured in seconds, and SQLite's single
    # writer must not be held across it.
    session.commit()
    try:
        result = extract_filing(
            document, company_name=name, settings=settings, vocabulary=vocabulary
        )
    except Exception as exc:  # noqa: BLE001 - one document must not stop the refresh
        filing.status = "failed"
        filing.error = f"{type(exc).__name__}: {exc}"
        report["failed"] += 1
        report["errors"].append(f"{filing.instrument_t212_ticker}: {exc}")
        session.flush()
        return

    if result is None:
        # No key configured, an empty document, or the budget refused the call. Left at
        # `fetched` rather than failed, because none of those is a property of the
        # document -- and marking it failed would retire it permanently.
        report["failed"] += 1
        report["errors"].append(
            f"{filing.instrument_t212_ticker}: the extractor returned nothing "
            "(no credential, no text, or the budget refused the call)"
        )
        session.flush()
        return

    # The analyst-facing summary, read from the same document on the *cheap* model --
    # `deepseek.model_for_purpose` routes `filing_summary` to `model_bulk`, because the
    # expensive one is justified only for the full-document extraction. This is what the
    # decision state's `filing_summary` slot has always expected and nothing ever wrote.
    summary = _summarise(document, name=name, settings=settings)
    _record_parsed(session, filing, result, summary=summary, report=report)


def _record_parsed(
    session: Session,
    filing: Filing,
    result: Any,
    *,
    summary: dict[str, Any] | None,
    report: dict[str, Any],
) -> None:
    """Store what the document said against its row, and count it.

    The status is written in the same statement that stores the payload, which is what lets
    a reader ask "has this document been read" as one condition rather than as a property of
    a JSON column -- see `decision.service._last_read_filing` for why the obvious test is
    wrong.
    """
    filing.parsed = {
        "extraction": result.as_dict(),
        # `None` when the summariser is not configured or the call could not be made, which
        # the decision reads as "nothing to say" -- the same thing it reads for a payload
        # written before this key existed.
        "summary": summary,
        "extractor_version": EXTRACTOR_VERSION,
        "llm_call_id": result.llm_call_id,
    }
    filing.extractor_version = EXTRACTOR_VERSION
    filing.status = "parsed"
    filing.error = None
    report["parsed"] += 1
    report["events"] += len(result.filing_events)
    session.flush()

    _note_discoveries(session, filing.instrument_t212_ticker, result, report)
    _store_period(session, filing, result, report)


def _summarise(document: str, *, name: str, settings: Settings) -> dict[str, Any] | None:
    """The filing's analyst-facing summary, or ``None`` when it cannot be had.

    Never raises. `summarise_filing` already answers ``None`` for the two failures it
    expects -- no credential configured, and a budget refusal -- and anything else escaping
    from here would cost the *extraction*, which has been paid for already and is what every
    downstream marker runs on. Best-effort by construction rather than by accident.
    """
    try:
        return summarise_filing(document, company_name=name, settings=settings)
    except Exception:  # noqa: BLE001 - the extraction is already banked
        logger.exception("filing summary failed for %s", name)
        return None


def _store_period(
    session: Session, filing: Filing, result: Any, report: dict[str, Any]
) -> None:
    """Write one filing's extracted figures as a period. See :func:`store_cited_period`."""
    store_cited_period(session, filing.instrument_t212_ticker, result, report)


def store_cited_period(
    session: Session,
    ticker: str,
    result: Any,
    report: dict[str, Any] | None = None,
    *,
    source: str = "llm_extraction",
) -> str:
    """Write cited figures as a `FundamentalPeriod` the analysis can read.

    Returns ``stored``, ``unusable`` or ``unscaled`` so the caller can record which of the
    three happened; the counters in ``report`` are the same three outcomes for a job that
    reports in numbers.

    **The extraction went nowhere before this.** `filing.parsed` held 38-41 cited metrics
    per filing and no period source was `llm_extraction`, so the whole 10-K pipeline was a
    dead end: nothing read those figures, and the metric-field discovery loop had nothing
    to learn from. `analysis/fundamental.py::SOURCE_PREFERENCE` already ranks
    `llm_extraction` **first** among sources, so the consumer was built and only the
    writer was missing.

    **Two callers now.** The filing pipeline reads one document and stores `llm_extraction`;
    a deep-dive reads several and stores `deep_research`, ranked below it so a filing's own
    extraction still wins a tie. The rules are the same for both, which is the point of the
    shared function: the scaling, the unit refusal and the derived ratios must not differ
    between a figure read from one document and a figure read from three.

    **Scaled to actual units, and refused when the document did not say.** The figures
    arrive in whatever the filing used -- MSFT's income statement is in millions, so its
    revenue extracts as 331,839 where the provider sources hold 331,839,012,864. Since
    this source outranks them, storing it unscaled would put a figure a million times too
    small at the top of the preference order, and *no marker would notice*: the ratios are
    scale-invariant, so the analysis would read healthy while the numbers printed beside
    it were wrong. An unrecognised or absent `units` therefore loses the period and is
    counted, rather than being stored on the assumption that it is probably actual.
    """
    report = report if report is not None else {}
    # `fundamentals` owns the period key and the period-end parser; the import is local
    # because that module reaches for providers, exactly as `ingest/xbrl.py` does it.
    from awltux.ingest.fundamentals import _upsert_period, derive_metrics

    outcome, instrument, period_end, scale = _prepare_period(session, ticker, result, report, source)
    if outcome != "stored":
        return outcome

    metrics = {
        name: _scale_metric(name, value, scale, result)
        for name, value in result.metric_values.items()
    }
    # The derived ratios are ours, not the company's, so they are computed from the
    # scaled figures rather than scaled themselves -- and they are added without a
    # citation, exactly as `ingest/xbrl.py` does it. The extraction cannot supply one
    # anyway: `validate_extraction` gates on `EXTRACTABLE_METRICS`, which excludes them.
    metrics.update(derive_metrics(metrics))

    _upsert_period(
        session,
        instrument,
        period_end=period_end,
        period_type=result.period_type or "annual",
        metrics=metrics,
        source=source,
        confidence=result.confidence,
        # Stamped with the pipeline that produced them. `ExtractedMetric.as_dict` writes
        # `llm_extraction` because that was the only writer; a deep-dive's spans come from
        # a different call, and a provenance map that named the filing extractor for them
        # would be a lie in the one column whose job is to say where a figure came from.
        metric_sources={
            name: {**entry, "source": source}
            for name, entry in result.metrics_for_storage.items()
        },
    )
    # Flushed where the other two `_upsert_period` call sites flush. A pending row is
    # invisible to a query on the same session, and the next filing's flush is what made
    # the second of MSFT's two periods disappear from a probe that read them back.
    session.flush()
    report["periods_stored"] = report.get("periods_stored", 0) + 1
    return "stored"


def _scale_metric(name: str, value: float, scale: float, result: Any) -> float:
    """One extracted figure in actual units.

    **A document's "in millions" does not apply to a price per share or a share count.** See
    `metrics.NON_MONETARY_METRICS`: a per-share amount is a price, and the scale made MSFT's
    EPS 17,950,000 rather than 17.95 in all ten stored extraction periods.

    ``shares_outstanding`` is a count, and a filer may state it in millions -- MSFT's balance
    sheet prints "outstanding 7,427 and 7,434" -- in which case the scale is right. What
    separates that from a filer printing the count itself is the number's own magnitude: no
    listed company has a trillion shares, so a scaled count past
    ``MAX_PLAUSIBLE_SHARES`` is a count the model had already given in units. Measured against
    the four live filers whose extraction rows carried a count: MSFT 7,427 (scale, 7.4bn),
    GWW 47,418,781, DAC 18,264,294 and ATMU 83,403,813 (no scale). All four come out right, and
    a wrong answer here is caught anyway by the accounts page, where the filer's own tagged
    count outranks this one.
    """
    if name in NON_MONETARY_METRICS:
        if name != "shares_outstanding":
            return value
        scaled = value * scale
        return value if scaled > MAX_PLAUSIBLE_SHARES else scaled
    return value * scale


def _prepare_period(    session: Session, ticker: str, result: Any, report: dict[str, Any], source: str
) -> tuple[str, Any, Any, float]:
    """``(outcome, instrument, period_end, scale)`` -- everything the caller needs to store.

    The two ways a result set cannot become a period, both of which are *counted rather than
    raised* because neither is an error: nothing to attach the figures to or date them by,
    and material that never says what units its figures are in. ``outcome`` is ``stored``,
    ``unusable`` or ``unscaled``; the other three values are meaningless unless it is
    ``stored``, and the caller returns the outcome unchanged when it is not.
    """
    from awltux.ingest.fundamentals import _parse_period_end
    from awltux.metrics import unit_scale

    instrument = session.get(Instrument, ticker)
    period_end = _parse_period_end(result.period_end)
    if instrument is None or period_end is None or not result.metric_values:
        # Nothing to attach a period to, nothing to date it, or no figures at all. One
        # counter, because none of the three is a reading of the document's units.
        report["unusable_period"] = report.get("unusable_period", 0) + 1
        return "unusable", instrument, period_end, 1.0

    scale = unit_scale(result.units)
    if scale is None:
        # The citations arrive in whatever the source stated -- millions, usually -- and a
        # mis-scaled period from a source that outranks the providers would win every
        # comparison it took part in. Refusing is the only safe answer when the material
        # does not say what its figures are in.
        logger.info(
            "%s for %s states units %r, which is not usable; the period is not stored",
            source,
            ticker,
            result.units,
        )
        report["unscaled_period"] = report.get("unscaled_period", 0) + 1
        return "unscaled", instrument, period_end, 1.0

    return "stored", instrument, period_end, scale


def repair_scaled_figures(session: Session, *, dry_run: bool = False) -> dict[str, Any]:
    """Correct the stored extraction figures that a document's unit scale should not touch.

    The write-time fix in :func:`_scale_metric` stops new periods carrying a price per share
    multiplied by the statement's "in millions", but the rows already written keep the wrong
    number -- measured 2026-10-09: **10 extraction periods**, MSFT's EPS stored as 17,950,000
    and GWW's share count as 47,418,781,000,000. Re-extracting would cost a model call per
    filing and could change figures for unrelated reasons; the correct value is already
    recorded, because every one of those figures carries the span it was quoted from.

    So the repair reads the evidence rather than re-deriving it:

    * a **price per share** is the number printed in its span, always -- the span says
      ``Diluted $ 17.95`` and no document presents that in millions;
    * a **share count** is repaired only when the stored figure is past
      ``MAX_PLAUSIBLE_SHARES``, in which case the span's number is the count the filer printed.

    Idempotent, and it touches nothing whose span does not support the correction: a figure
    whose span cannot be read is left exactly as it is and counted, because a repair that
    guesses is worse than the defect it is repairing.
    """
    rows = list(
        session.execute(
            select(FundamentalPeriod)
            .where(FundamentalPeriod.source.in_(("llm_extraction", "deep_research")))
        ).scalars().all()
    )
    changed: list[dict[str, Any]] = []
    unreadable = 0

    for period in rows:
        metrics = dict(period.metrics or {})
        sources = period.metric_sources or {}
        touched = False
        for name in NON_MONETARY_METRICS:
            value = metrics.get(name)
            if value is None:
                continue
            printed = _printed_number(str((sources.get(name) or {}).get("span") or ""))
            if printed is None:
                unreadable += 1
                continue
            if name == "shares_outstanding":
                if abs(value) <= MAX_PLAUSIBLE_SHARES:
                    continue
                corrected = printed
            else:
                if _same_figure(value, printed):
                    continue
                corrected = printed
            changed.append(
                {
                    "period_id": period.id,
                    "ticker": period.instrument_t212_ticker,
                    "period_end": period.period_end.isoformat() if period.period_end else None,
                    "metric": name,
                    "was": value,
                    "now": corrected,
                }
            )
            metrics[name] = corrected
            touched = True
        if touched and not dry_run:
            # Reassigned rather than mutated: SQLAlchemy tracks a JSON column by identity.
            period.metrics = metrics

    if not dry_run:
        session.flush()
    return {"checked": len(rows), "changed": changed, "unreadable": unreadable}


def _printed_number(span: str) -> float | None:
    """The first number a span states, or ``None``.

    The first, because a span quoting a statement line reads "Diluted $ 17.95" and one quoting
    a table row reads "outstanding 7,427 and 7,434" -- the figure is the leading number in both,
    and taking the last or the largest would pick a comparative column.
    """
    for raw in _NUMBER.findall(span or ""):
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            continue
    return None


def _same_figure(left: float, right: float) -> bool:
    """To within rounding: the span states the figure as printed, not as stored."""
    if left == right:
        return True
    return abs(left - right) <= 0.01 * max(abs(left), abs(right))


def _note_discoveries(session: Session, ticker: str, result: Any, report: dict[str, Any]) -> None:
    """Let a filing's own captions close the gaps its own subtotals expose.

    This is the loop the dynamic vocabulary exists for. The extractor reports the lines
    a filing presents that the prompt did not name; the ledger says how far the
    components we hold fall short of each stated subtotal; and a caption is *proved* to
    belong on the list when its value closes that residual exactly.

    Arithmetic rather than the model's opinion, and that is the whole safeguard: a
    caption that closes a gap to the pound is the missing line, and one that does not is
    not -- which is why the vocabulary can be allowed to grow on its own.

    The composition checks are reused rather than re-implemented. They run on an
    unpersisted period built from just-extracted figures, so the reading the discovery
    is based on is the same code that will later judge the stored period.
    """
    from awltux.analysis import gap, ledger
    from awltux.analysis.metric_fields import BALANCE, record
    from awltux.db import FundamentalPeriod

    if not result.unlisted:
        return

    probe = FundamentalPeriod(
        instrument_t212_ticker=ticker,
        period_end=None,
        period_type=None,
        source="extraction_probe",
        # `metric_values`, not `metrics_for_storage`: a stored period holds plain
        # numbers and keeps its provenance in the separate `metric_sources` column, and
        # `metrics.value_of` does `float(raw)` -- so the provenance map reads as *no
        # value at all* and every check would come back "not computable".
        metrics=result.metric_values,
    )
    for check in ledger.composition(probe):
        if not check.failed or check.residual is None:
            continue
        # Only captions from the statement the residual is *on*. The first run of this
        # had no such filter and promoted a pair made of a balance-sheet line and a
        # revenue line, whose total happened to land on the residual -- two unrelated
        # statements summing to a number is a coincidence, and it would have gone into
        # the prompt for every later filing.
        candidates = {
            metric.name: metric.value
            for metric in result.unlisted.values()
            if _on_balance_sheet(metric.location)
        }
        found = gap.best(check.residual, candidates)
        if found is None:
            continue
        for label in found.labels:
            if record(session, label, group=BALANCE, reason=found.describe(), discovered_for=ticker):
                report["discovered"] = report.get("discovered", 0) + 1


def _on_balance_sheet(location: str | None) -> bool:
    """Whether a caption was found on the balance sheet.

    By the model's own ``location``, which the prompt requires it to give. Loose on
    purpose -- filers and the model between them write "Balance Sheets", "Consolidated
    balance sheets", "Statement of financial position" -- but not so loose that an
    income-statement line passes, which is the false positive it exists to stop.
    """
    text = (location or "").lower()
    return "balance sheet" in text or "financial position" in text


def _company_name(session: Session, ticker: str) -> str:
    """The filer's name, for the extractor's header.

    Its own function so the missing-row case is explicit: the prompt names the company
    and an unnamed document invites the model to guess whose accounts it is reading.
    """
    instrument = session.get(Instrument, ticker)
    return instrument.name if instrument is not None else ticker


__all__ = [
    "EXTRACTOR_VERSION",
    "PARSE_LIMIT",
    "TEXT_SUFFIXES",
    "document_text",
    "extract_held_filings",
    "repair_scaled_figures",
    "store_cited_period",
]
