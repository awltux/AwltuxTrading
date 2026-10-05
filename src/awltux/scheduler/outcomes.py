"""Say what a job run achieved, and -- more usefully -- why it achieved nothing.

The Operations page showed `seen 500` and `written 0` next to the word "ok". Both
numbers were true and the pair was useless: the run had done nothing and nothing on
the page said why. The reason was almost always sitting in the run's ``detail``,
unread, because ``detail`` is a JSON blob written for the API rather than for a
person.

The deployment's own history shows the shape of the problem:

    valuation      seen=500  written=0   insufficient_data=500, no_peers=408
    uk_companies   seen=12   written=0   matched=0, unmatched=12
    fundamentals   seen=2    written=0   failures: no statements available for ...
    filings_edgar  seen=4529 written=0   filings_written=0

Each of those has a plain answer. None of them said it.

**Why a per-job table rather than a generic key dump.** A dump of `detail` is what
the API already returns, and it is not an explanation. "insufficient_data 500" is a
field name, not a sentence. Each entry here knows which of its job's numbers mean
"and here is why nothing happened", which is knowledge about that job and cannot be
derived from a dict of unknown keys.

**Why it is derived at render rather than stored.** The history is long and the
wording will improve. Deriving from the stored ``detail`` means every past run
benefits from a better explanation, instead of each row being frozen at the wording
that happened to be current when it ran. A job's own ``note`` -- where it wrote one,
with knowledge the summariser does not have -- always wins.

``SUMMARISERS`` is asserted complete against the registry by a test, so adding a job
without saying what it achieves fails the suite rather than producing a blank cell.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from awltux.scheduler.jobs import JobResult

Summariser = Callable[[dict[str, Any]], str]


def _n(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def _get(detail: dict[str, Any], key: str, default: Any = 0) -> Any:
    value = detail.get(key)
    return default if value is None else value


def _first_names(values: Any, limit: int = 3) -> str:
    if not isinstance(values, list):
        return ""
    names = [str(value).split(":")[0].strip() for value in values[:limit]]
    extra = len(values) - len(names)
    joined = ", ".join(names)
    return f"{joined} and {extra} more" if extra > 0 else joined


def _nothing(seen: int, what: str, because: str) -> str:
    return f"{_n(seen)} {what}, none written: {because}"


def _t212_instruments(detail: dict[str, Any]) -> str:
    seen = _get(detail, "instruments_seen")
    created = _get(detail, "instruments_created")
    updated = _get(detail, "instruments_updated")
    mapped = _get(detail, "mapped")
    unmapped = _get(detail, "unmapped")
    line = (
        f"{_n(seen)} instruments synced ({_n(created)} new, {_n(updated)} updated); "
        f"{_n(mapped)} mapped to a price symbol"
    )
    if unmapped:
        line += f", {_n(unmapped)} not mapped (no symbol derived from the ticker)"
    return line


def _universe_refresh(detail: dict[str, Any]) -> str:
    selected = _get(detail, "selected")
    eligible = _get(detail, "eligible")
    cap = _get(detail, "size_cap")
    if not selected:
        return _nothing(
            eligible,
            "instruments were eligible",
            "none passed the size and liquidity screen",
        )
    line = f"{_n(selected)} of {_n(eligible)} eligible instruments selected"
    if cap:
        line += f" (capped at the largest {_n(cap)} by turnover)"
    filtered = _get(detail, "filtered_out")
    if filtered:
        line += f"; {_n(filtered)} filtered out"
    return line


def _price_eod(detail: dict[str, Any]) -> str:
    requested = _get(detail, "tickers_requested")
    returned = _get(detail, "tickers_returned")
    bars = _get(detail, "bars_written")
    if not bars:
        return _nothing(
            requested,
            f"tickers requested, {_n(returned)} returned history",
            "the provider had no bars for them (delisted, suspended, or the symbol "
            "is not the one the provider uses)",
        )
    line = (
        f"{_n(bars)} daily bars written for {_n(returned)} of {_n(requested)} tickers"
    )
    skipped = _get(detail, "bars_skipped_lower_rank")
    if skipped:
        line += f"; {_n(skipped)} bars skipped as a lower-ranked source"
    return line


def _price_intraday(detail: dict[str, Any]) -> str:
    requested = _get(detail, "tickers_requested")
    returned = _get(detail, "tickers_returned")
    if not returned:
        return _nothing(
            requested,
            "tickers requested",
            "no quotes came back (markets closed, or the provider refused)",
        )
    return f"{_n(returned)} quotes stored for {_n(requested)} held or pinned tickers"


def _fundamentals(detail: dict[str, Any]) -> str:
    attempted = _get(detail, "tickers_attempted")
    periods = _get(detail, "periods_written")
    failures = detail.get("failures") or []
    if not periods:
        if failures:
            return _nothing(
                attempted,
                "tickers attempted",
                f"the provider returned no statements -- {_first_names(failures)}",
            )
        return _nothing(
            attempted,
            "tickers attempted",
            "the provider returned no statements for any of them",
        )
    line = f"{_n(periods)} reporting periods written for {_n(attempted)} tickers"
    if failures:
        line += f"; {_n(len(failures))} failed ({_first_names(failures)})"
    return line


def _filings_edgar(detail: dict[str, Any]) -> str:
    seen = _get(detail, "filings_seen")
    written = _get(detail, "filings_written")
    resolution = detail.get("cik_resolution") or {}
    resolved = resolution.get("resolved", _get(detail, "resolved"))
    unresolved = resolution.get("unresolved_count", _get(detail, "unresolved_count"))
    if not written:
        # The job's own detail cannot distinguish "nothing new" from "failed to
        # store", so this says what it does know and no more.
        return _nothing(
            seen,
            f"filings seen, none new for {_n(resolved)} resolved filers",
            f"every one was already stored, or their CIK could not be resolved "
            f"({_n(unresolved)} unresolved)",
        )
    line = f"{_n(written)} filings stored from {_n(seen)} seen"
    if unresolved:
        line += f"; {_n(unresolved)} instruments have no resolvable CIK"
    return line


def _edgar_events(detail: dict[str, Any]) -> str:
    written = _get(detail, "events_written")
    seen = _get(detail, "events_seen", _get(detail, "filings_seen"))
    if not written:
        return _nothing(
            seen or _get(detail, "errors_count", 0),
            "events seen in the current-events feed",
            "none concerned a company in the universe, which is what the feed is "
            "filtered on",
        )
    return f"{_n(written)} filing events matched to universe instruments"


def _uk_companies(detail: dict[str, Any]) -> str:
    attempted = _get(detail, "attempted")
    matched = _get(detail, "matched")
    if not attempted:
        return "no UK listings were waiting for a company number"
    if not matched:
        return _nothing(
            attempted,
            "UK listings searched on Companies House",
            "no candidate name matched closely enough to be trusted; a wrong match "
            "would attach another company's accounts to the ticker",
        )
    confident = _get(detail, "confident")
    return (
        f"{_n(matched)} of {_n(attempted)} UK listings matched a company number"
        f" ({_n(confident)} at high confidence)"
    )


def _news_rss(detail: dict[str, Any]) -> str:
    fetched = _get(detail, "fetched")
    written = _get(detail, "written")
    duplicates = _get(detail, "duplicates")
    prefiltered = _get(detail, "prefiltered_out")
    if not written:
        parts = []
        if duplicates:
            parts.append(f"{_n(duplicates)} already stored")
        if prefiltered:
            parts.append(f"{_n(prefiltered)} rejected by the prefilter")
        because = ", ".join(parts) if parts else "every feed returned nothing"
        return _nothing(fetched, "stories fetched", because)
    line = f"{_n(written)} new stories from {_n(fetched)} fetched"
    if duplicates:
        line += f"; {_n(duplicates)} already stored"
    if prefiltered:
        line += f"; {_n(prefiltered)} rejected by the prefilter"
    classified = _get(detail, "classified")
    if classified:
        line += f"; {_n(classified)} classified"
    return line


def _news_analysis(detail: dict[str, Any]) -> str:
    examined = _get(detail, "examined")
    selected = _get(detail, "selected")
    appraised = _get(detail, "appraised")
    if not appraised:
        if not examined:
            return "no stories in the lookback window to appraise"
        return _nothing(
            examined,
            "stories examined",
            f"none of the {_n(selected)} that cleared the interest threshold needed "
            "re-appraising, or none cleared it at all",
        )
    line = f"{_n(appraised)} stories appraised from {_n(examined)} examined"
    deep = _get(detail, "deep_analysed")
    if deep:
        line += f" ({_n(deep)} with a model, the rest deterministically)"
    return line


def _news_relevance(detail: dict[str, Any]) -> str:
    assessed = _get(detail, "assessed")
    classified = _get(detail, "classified")
    structural = _get(detail, "decided_structurally")
    if not assessed:
        return "no stored story was waiting for a relevance verdict"
    return (
        f"{_n(assessed)} stories given a verdict "
        f"({_n(structural)} from a direction already stored, {_n(classified)} newly "
        "classified)"
    )


def _news_embeddings(detail: dict[str, Any]) -> str:
    embedded = _get(detail, "embedded")
    errors = detail.get("errors") or []
    if not embedded:
        return _nothing(
            _get(detail, "pending", 0),
            "stories were waiting for a vector",
            "; ".join(str(e) for e in errors[:2]) or "the provider returned nothing",
        )
    return f"{_n(embedded)} stories vectorised with {detail.get('model', 'the model')}"


def _sentiment(detail: dict[str, Any]) -> str:
    seen = _get(detail, "instruments_seen")
    rows = _get(detail, "rows_written")
    if not rows:
        return _nothing(
            seen,
            "instruments considered",
            f"{_n(_get(detail, 'skipped_no_data'))} had no news in the window to "
            "aggregate",
        )
    line = f"{_n(rows)} sentiment rows written across {_n(seen)} instruments"
    appraised = _get(detail, "articles_appraised")
    if appraised:
        line += f"; {_n(appraised)} articles carried a scepticism weight"
    return line


def _valuation(detail: dict[str, Any]) -> str:
    attempted = _get(detail, "attempted")
    valued = _get(detail, "valued")
    if not valued:
        insufficient = _get(detail, "insufficient_data")
        peers = _get(detail, "no_peers")
        because = f"{_n(insufficient)} lacked enough inputs to value"
        if peers:
            because += f" and {_n(peers)} of those had no comparable peers"
        return _nothing(attempted, "instruments attempted", because)
    line = f"{_n(valued)} valuations from {_n(attempted)} attempted"
    insufficient = _get(detail, "insufficient_data")
    if insufficient:
        line += f"; {_n(insufficient)} skipped for insufficient data"
    return line


def _decision(detail: dict[str, Any]) -> str:
    attempted = _get(detail, "attempted")
    decided = _get(detail, "decided")
    skipped = _get(detail, "skipped")
    failures = detail.get("failures") or []
    if not decided:
        because = f"{_n(skipped)} had unchanged inputs since their last decision"
        if failures:
            because += f"; {_n(len(failures))} failed, starting with {failures[0]}"
        return _nothing(attempted, "instruments attempted", because)
    engines = detail.get("by_engine") or {}
    engine_text = ", ".join(f"{name} {_n(count)}" for name, count in engines.items())
    line = f"{_n(decided)} decisions from {_n(attempted)} attempted"
    if engine_text:
        line += f" ({engine_text})"
    if failures:
        line += f"; {_n(len(failures))} failed"
    return line


def _calibration(detail: dict[str, Any]) -> str:
    scored = _get(detail, "scored")
    skipped = _get(detail, "skipped_no_price")
    if not scored:
        return _nothing(
            skipped,
            "elapsed decisions were ready to score",
            "no price was stored at their horizon yet, so there is nothing to "
            "compare against",
        )
    return f"{_n(scored)} elapsed decisions scored against their horizon price"


def _retention(detail: dict[str, Any]) -> str:
    removed = detail.get("removed")
    if isinstance(removed, dict):
        total = sum(int(v) for v in removed.values() if isinstance(v, (int, float)))
        if not total:
            return "nothing had aged past its retention window"
        parts = ", ".join(f"{_n(v)} {k}" for k, v in removed.items() if v)
        return f"{_n(total)} rows pruned ({parts})"
    return f"{_n(removed)} rows pruned" if removed else "nothing had aged past its retention window"


SUMMARISERS: dict[str, Summariser] = {
    "t212_instruments": _t212_instruments,
    "universe_refresh": _universe_refresh,
    "price_eod": _price_eod,
    "price_intraday": _price_intraday,
    "fundamentals": _fundamentals,
    "filings_edgar": _filings_edgar,
    "edgar_events": _edgar_events,
    "uk_companies": _uk_companies,
    "news_rss": _news_rss,
    "news_analysis": _news_analysis,
    "news_relevance": _news_relevance,
    "news_embeddings": _news_embeddings,
    "sentiment": _sentiment,
    "valuation": _valuation,
    "decision": _decision,
    "calibration": _calibration,
    "retention": _retention,
}


def outcome(
    *,
    job: str,
    detail: dict[str, Any] | None,
    error: str | None = None,
) -> str:
    """One sentence: what this run achieved, or why it achieved nothing.

    A job's own ``note`` wins where it wrote one -- it knows things the summariser
    does not, such as which dependency was missing. Otherwise the summariser reads
    the stored ``detail``. Where a job has no summariser the result is empty rather
    than invented, because a plausible wrong reason is worse than a blank cell.
    """
    if error:
        return error
    stored = (detail or {}).get("note")
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    summariser = SUMMARISERS.get(job)
    if summariser is None:
        return ""
    try:
        return summariser(detail or {})
    except Exception:  # pragma: no cover - a malformed detail must not break the page
        return ""


def outcome_for(run: Any) -> str:
    """``outcome`` for an ``IngestRun`` row."""
    return outcome(job=run.job, detail=run.detail, error=run.error)


def summarise_result(job: str, result: JobResult | None) -> str:
    """``outcome`` for a result that has not been stored yet (used by tests)."""
    detail = result.detail if result else None
    return outcome(job=job, detail=detail)
