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
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from awltux.config import Settings, get_settings
from awltux.db import Filing, Instrument
from awltux.llm.extractors import extract_filing
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

    filing.parsed = {
        "extraction": result.as_dict(),
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


def _store_period(
    session: Session, filing: Filing, result: Any, report: dict[str, Any]
) -> None:
    """Write the extracted figures as a `FundamentalPeriod` the analysis can read.

    **The extraction went nowhere before this.** `filing.parsed` held 38-41 cited metrics
    per filing and no period source was `llm_extraction`, so the whole 10-K pipeline was a
    dead end: nothing read those figures, and the metric-field discovery loop had nothing
    to learn from. `analysis/fundamental.py::SOURCE_PREFERENCE` already ranks
    `llm_extraction` **first** among sources, so the consumer was built and only the
    writer was missing.

    **Scaled to actual units, and refused when the document did not say.** The figures
    arrive in whatever the filing used -- MSFT's income statement is in millions, so its
    revenue extracts as 331,839 where the provider sources hold 331,839,012,864. Since
    this source outranks them, storing it unscaled would put a figure a million times too
    small at the top of the preference order, and *no marker would notice*: the ratios are
    scale-invariant, so the analysis would read healthy while the numbers printed beside
    it were wrong. An unrecognised or absent `units` therefore loses the period and is
    counted, rather than being stored on the assumption that it is probably actual.
    """
    # `fundamentals` owns the period key and the period-end parser; the import is local
    # because that module reaches for providers, exactly as `ingest/xbrl.py` does it.
    from awltux.ingest.fundamentals import _parse_period_end, _upsert_period, derive_metrics
    from awltux.metrics import unit_scale

    instrument = session.get(Instrument, filing.instrument_t212_ticker)
    period_end = _parse_period_end(result.period_end)
    if instrument is None or period_end is None or not result.metric_values:
        # Nothing to attach a period to, nothing to date it, or no figures at all. One
        # counter, because none of the three is a reading of the document's units.
        report["unusable_period"] = report.get("unusable_period", 0) + 1
        return

    scale = unit_scale(result.units)
    if scale is None:
        # `source="llm_extraction"` outranks every provider, so an unscaled period would
        # win every comparison it took part in. Refusing is the only safe answer when the
        # document does not say what its figures are in.
        logger.info(
            "filing extraction for %s states units %r, which is not usable; the period "
            "is not stored",
            filing.instrument_t212_ticker,
            result.units,
        )
        report["unscaled_period"] = report.get("unscaled_period", 0) + 1
        return

    metrics = {name: value * scale for name, value in result.metric_values.items()}
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
        source="llm_extraction",
        confidence=result.confidence,
        metric_sources=result.metrics_for_storage,
    )
    # Flushed where the other two `_upsert_period` call sites flush. A pending row is
    # invisible to a query on the same session, and the next filing's flush is what made
    # the second of MSFT's two periods disappear from a probe that read them back.
    session.flush()
    report["periods_stored"] = report.get("periods_stored", 0) + 1


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
]
