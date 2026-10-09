"""Corrections a reader has made to a period's accounts, and where each came from.

**Why a correction is recorded at all, rather than just edited in.** A stored period is what
a writer put there -- the SEC's tags, a Yahoo statement, a model's reading of a 10-K -- and
that is the *evidence* about what the source said. A reader who can see that a line was
misread needs to be able to fix it, but the fix must not destroy the record it contradicts:
the next reader wants to know that `depreciation_amortisation` was removed, from which
filing, when, and what the extractor had claimed. So the correction is its own record on the
row, and the corrected figures are written into ``metrics`` beside it -- one place to read,
one place to argue with.

**Written through, not overlaid.** The corrected values go into ``metrics`` and
``metric_sources`` so that every consumer -- the ledger, the hover working, the composition
checks, the snapshot markers, the valuation and the decisions -- sees the corrected accounts
without a new read path. That is the same argument `analysis/adopted.py` records for the
captions a filing proves: a correction that only the accounts page honoured would leave the
verdict resting on a figure the page had already rejected.

**Re-applied after every re-derive.** `ingest/fundamentals.py::_upsert_period` rewrites
``metrics`` wholesale from the payload, so a correction would otherwise vanish at the next
sync. It calls :func:`apply_to_row` after it writes, next to the carve-out it already has for
a figure an extractor sourced from the filed document.

**Two scopes, and one of them cannot carry a value.** A removal is a statement about a line
-- "this is not one of this period's accounts" -- and can reasonably apply to every period a
filer has, which is what the confirmation page's tick records in ``app_setting`` (see
`analysis/adopted.py` for why per-filer records live there). An added *value* cannot: a figure
belongs to the period it was stated for, so the value is recorded on the row and only the
tag-to-line mapping is worth carrying to other periods -- and that mapping arrives with the
filing picker, because until values can be clicked from a filing there is no tag to map.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from awltux.db import AppSetting, FundamentalPeriod, Instrument, utcnow
from awltux.metrics import DERIVED_METRICS, value_of

#: One `app_setting` row per filer, holding the rules that apply to every period it filed.
SETTING_PREFIX = "account_correction:"

#: The provenance `source` for a figure a person put there. Named rather than left empty so
#: the accounts page can mark it and a reader can tell it from an extractor's figure.
MANUAL = "manual"

#: The two sides of a ledger, as the chart names them.
DEBIT = "debit"
CREDIT = "credit"
SIDES = (DEBIT, CREDIT)

#: Why a line was removed, when the reader did not say. Not an empty string: the record is
#: evidence, and "no reason given" is itself the honest answer.
NO_REASON = "no reason given"


def key(cik: str) -> str:
    return f"{SETTING_PREFIX}{str(cik).strip()}"


@dataclass(slots=True)
class Correction:
    """A figure put on a line by hand, with the filing it was read from."""

    metric: str
    value: float | None = None
    side: str = CREDIT
    #: ``taxonomy:Tag`` when the value was clicked in a filing, empty when it was typed.
    tag: str = ""
    #: The filing it came from, so the reader can go back to the line they read.
    url: str = ""
    at: str = ""
    note: str = ""
    #: ``filing`` for a value clicked out of a filing, ``typed`` for one entered by hand.
    origin: str = "typed"
    #: What the line said before, and the provenance entry it came with. Both are kept
    #: because the correction *replaces* them: without them, undoing an addition could
    #: only be done by re-reading the filing, and a hand-typed figure has none to re-read.
    was: float | None = None
    was_source: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "side": self.side if self.side in SIDES else CREDIT,
            "tag": self.tag,
            "url": self.url,
            "at": self.at or stamp(),
            "note": self.note,
            "origin": self.origin,
            "was": self.was,
            "was_source": self.was_source,
        }

    @classmethod
    def from_dict(cls, metric: str, payload: Mapping[str, Any]) -> Correction:
        displaced = payload.get("was_source")
        return cls(
            metric=metric,
            value=value_of(payload, "value"),
            side=str(payload.get("side") or CREDIT),
            tag=str(payload.get("tag") or ""),
            url=str(payload.get("url") or ""),
            at=str(payload.get("at") or ""),
            note=str(payload.get("note") or ""),
            origin=str(payload.get("origin") or "typed"),
            was=value_of(payload, "was"),
            was_source=dict(displaced) if isinstance(displaced, dict) else None,
        )


@dataclass(slots=True)
class Removal:
    """A line a reader took out of a period's accounts, and what it had said."""

    metric: str
    at: str = ""
    reason: str = NO_REASON
    #: What the extractor had stored, kept because the record is the evidence for the edit.
    was: float | None = None
    tag: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at or stamp(),
            "reason": self.reason or NO_REASON,
            "was": self.was,
            "tag": self.tag,
        }

    @classmethod
    def from_dict(cls, metric: str, payload: Mapping[str, Any]) -> Removal:
        return cls(
            metric=metric,
            at=str(payload.get("at") or ""),
            reason=str(payload.get("reason") or NO_REASON),
            was=value_of(payload, "was"),
            tag=str(payload.get("tag") or ""),
        )


@dataclass(slots=True)
class Record:
    """One period's own corrections."""

    added: dict[str, Correction] = field(default_factory=dict)
    removed: dict[str, Removal] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.added or self.removed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": {name: entry.as_dict() for name, entry in self.added.items()},
            "removed": {name: entry.as_dict() for name, entry in self.removed.items()},
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Record:
        if not isinstance(payload, dict):
            return cls()
        return cls(
            added={
                str(name): Correction.from_dict(str(name), entry)
                for name, entry in (payload.get("added") or {}).items()
                if isinstance(entry, dict)
            },
            removed={
                str(name): Removal.from_dict(str(name), entry)
                for name, entry in (payload.get("removed") or {}).items()
                if isinstance(entry, dict)
            },
        )


@dataclass(slots=True)
class Rules:
    """What a filer's periods all have in common, as far as a reader has said so.

    Removals only, for now: a *value* is a fact about one period, and the mapping half of
    this record arrives with the filing picker, which is what gives a tag something to map.
    """

    removed: dict[str, Removal] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.removed)

    def as_dict(self) -> dict[str, Any]:
        return {"removed": {name: entry.as_dict() for name, entry in self.removed.items()}}

    @classmethod
    def from_dict(cls, payload: Any) -> Rules:
        if not isinstance(payload, dict):
            return cls()
        return cls(
            removed={
                str(name): Removal.from_dict(str(name), entry)
                for name, entry in (payload.get("removed") or {}).items()
                if isinstance(entry, dict)
            }
        )


def stamp() -> str:
    """When a correction was made, in the format the rest of the app's records use."""
    return utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def load_period(period: FundamentalPeriod) -> Record:
    """A row's own corrections, or an empty record."""
    return Record.from_dict(getattr(period, "corrections", None))


def save_period(session: Any, period: FundamentalPeriod, record: Record) -> None:
    """Store a row's corrections as its record, or clear the column when there are none."""
    period.corrections = record.as_dict() if record else None
    session.flush()


def load_filer(session: Any, cik: str | None) -> Rules:
    """The rules recorded against a filer, or none."""
    if not cik:
        return Rules()
    row = session.get(AppSetting, key(cik))
    value = row.value if row is not None else None
    return Rules.from_dict(value)


def save_filer(session: Any, cik: str, rules: Rules) -> None:
    """Write the filer's rules, deleting the record when the last one is forgotten."""
    row = session.get(AppSetting, key(cik))
    if not rules:
        if row is not None:
            session.delete(row)
        session.flush()
        return
    if row is None:
        row = AppSetting(key=key(cik))
        session.add(row)
    row.value = rules.as_dict()
    row.note = f"{len(rules.removed)} line(s) removed for this filer"
    session.flush()


def apply(
    metrics: Mapping[str, Any],
    sources: Mapping[str, Any] | None,
    record: Record,
    rules: Rules | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The corrected figures and provenance, from the stored ones plus the corrections.

    Pure: nothing is read from the database and nothing is written. Order matters and is part
    of the contract -- **removals first, then additions** -- so a metric a filer rule removes
    can still be put back by hand in one period, which is the only reading that lets a reader
    override a rule they made earlier.

    Derived ratios are dropped and recomputed rather than left alone: a marker computed from
    a component that has just been removed is a stale figure claiming to describe the
    corrected accounts, and the ratios are ours anyway -- `ingest/fundamentals.derive_metrics`
    computes them from whatever the row holds.
    """
    from awltux.ingest.fundamentals import derive_metrics

    corrected = dict(metrics or {})
    provenance = {name: dict(entry) for name, entry in (sources or {}).items() if isinstance(entry, dict)}
    # Every marker is rebuilt from the removals in force, so a line that has since been put
    # back cannot keep saying it was taken out -- `apply` is the one place that decides, and
    # it decides from the record every time rather than trusting the row.
    for entry in provenance.values():
        entry.pop("removed", None)

    removed: dict[str, Removal] = dict(rules.removed) if rules else {}
    removed.update(record.removed)
    for name, removal in removed.items():
        displaced = corrected.pop(name, None)
        if name in provenance:
            # The provenance stays and says the line was taken out. It is what ties the
            # removal to the filing it came from, and `accession`/`tag_index` still read it
            # for exactly that reason.
            provenance[name]["removed"] = removal.as_dict()
        elif displaced is not None:
            # A period whose writer stored no provenance -- a Yahoo statement -- would
            # otherwise leave the removal with nowhere to record the figure it displaced, and
            # the row's own figures no longer hold that figure. So the entry is made here.
            provenance[name] = {"value": displaced, "removed": removal.as_dict()}

    for name, addition in record.added.items():
        if addition.value is None:
            continue
        corrected[name] = addition.value
        provenance[name] = {
            "value": addition.value,
            "source": MANUAL,
            "span": addition.tag,
            "url": addition.url,
            "side": addition.side,
            "at": addition.at or stamp(),
            "note": addition.note,
            "origin": addition.origin,
        }

    for name in DERIVED_METRICS:
        corrected.pop(name, None)
    corrected.update(derive_metrics(corrected))
    return corrected, provenance


def apply_to_row(
    period: FundamentalPeriod, rules: Rules | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rewrite a row's figures and provenance from its own corrections and the filer's rules.

    The row is mutated in place -- this is the write-through every consumer depends on -- and
    the corrected pair is returned so a caller can report what changed. With no corrections
    and no rules this is still the place the derived ratios are recomputed, which is what
    keeps them consistent with whatever the caller just wrote.
    """
    record = load_period(period)
    metrics, sources = apply(period.metrics or {}, period.metric_sources, record, rules)
    period.metrics = metrics
    period.metric_sources = sources
    return metrics, sources


def _copy_sources(sources: Any) -> dict[str, Any]:
    """Provenance as a mutable copy, so a caller can edit a line without touching the row."""
    return {
        name: dict(entry)
        for name, entry in (sources or {}).items()
        if isinstance(entry, dict)
    }


def restore(
    period: FundamentalPeriod,
    metric: str,
    *,
    value: float | None = None,
    source: Mapping[str, Any] | None = None,
) -> bool:
    """Put back on the row what a correction displaced, before the figures are recomputed.

    The row holds the *corrected* figures -- that is the write-through -- so undoing a
    correction cannot read them back from where they were: a removal deleted the line from
    ``metrics``, and an addition overwrote both the figure and the provenance entry beside
    it. The displaced pair is therefore recorded when the correction is made, and this writes
    it back. ``value`` falls back to the figure the row's own provenance records for the line,
    which is what a *filer-wide* rule needs: the value it displaced is a different figure in
    every period, so only that period's own evidence can restore it.

    Returns whether anything was restored. ``False`` is a real answer and is left visible rather
    than papered over -- a line whose original figure was never recorded stays absent, and the
    checks above it say they have not enough stated.
    """
    metrics = dict(period.metrics or {})
    sources = _copy_sources(period.metric_sources)
    entry = sources.get(metric)
    if source is not None:
        # An addition replaced the provenance too, so the record of where the line came from
        # has to go back with the figure -- not only the number.
        sources[metric] = dict(source)
        entry = sources[metric]
    elif entry is not None:
        entry.pop("removed", None)
    if value is None and entry is not None:
        value = value_of(entry, "value")
    if value is None:
        return False
    metrics[metric] = value
    period.metrics = metrics
    period.metric_sources = sources
    return True


def add(
    period: FundamentalPeriod,
    metric: str,
    *,
    value: float,
    side: str = CREDIT,
    tag: str = "",
    url: str = "",
    note: str = "",
    origin: str = "typed",
    rules: Rules | None = None,
) -> Correction:
    """Put a figure on a line by hand, and return the correction it recorded.

    The value is a fact about *this period* and is recorded on the row: see the module
    docstring for why it cannot be carried to the filer's other periods the way a removal can.
    """
    entry = (period.metric_sources or {}).get(metric)
    correction = Correction(
        metric=metric,
        value=value,
        side=side if side in SIDES else CREDIT,
        tag=tag,
        url=url,
        at=stamp(),
        note=note,
        origin=origin,
        was=value_of(period.metrics, metric),
        was_source=dict(entry) if isinstance(entry, dict) else None,
    )
    record = load_period(period)
    # The later act on a line supersedes the earlier one. A figure put on a line and then taken
    # out again is not both, and the panel would otherwise show two rows for one line with
    # nothing to say which of them the arithmetic obeyed.
    record.removed.pop(metric, None)
    record.added[metric] = correction
    period.corrections = record.as_dict()
    apply_to_row(period, rules)
    return correction


def remove(
    period: FundamentalPeriod,
    metric: str,
    *,
    reason: str = NO_REASON,
    scope: str = "period",
    rules: Rules | None = None,
) -> Removal:
    """Take a line out of a period's accounts, and return the removal it recorded.

    ``scope`` is ``"filer"`` when the reader asked for it to apply to every period this filer
    has, and then the *rule* is the record: the removal is kept once against the filer rather
    than once per period, because that is what it is -- one decision about one line -- and a
    copy on the row the reader happened to be looking at would be undone from that row's page
    while the other periods kept the line out.
    """
    entry = (period.metric_sources or {}).get(metric) or {}
    removal = Removal(
        metric=metric,
        at=stamp(),
        reason=reason or NO_REASON,
        was=value_of(period.metrics, metric),
        tag=str(entry.get("span") or ""),
    )
    record = load_period(period)
    if scope == "filer" and rules is not None:
        rules.removed[metric] = removal
        # A figure this period holds by hand goes with it: the reader has just said the line is
        # not one of this company's accounts at all.
        if record.added.pop(metric, None) is not None:
            period.corrections = record.as_dict() if record else None
        apply_to_row(period, rules)
        return removal
    record.added.pop(metric, None)
    record.removed[metric] = removal
    period.corrections = record.as_dict()
    apply_to_row(period, rules)
    return removal


def forget(period: FundamentalPeriod, metric: str, *, rules: Rules | None = None) -> bool:
    """Undo *this period's* correction to a line, and return whether there was one.

    Both halves are dropped together, because to the reader there is one thing on the page --
    a line that is not what the source said -- and having to know whether a mistake was made by
    adding or by removing in order to undo it would be the page explaining its own bookkeeping
    rather than the accounts.

    A filer-wide removal is *not* forgotten here: the rule was made once for every period, and
    undoing it from one period's page would silently change the others. The rule has its own
    undo, on the same panel.
    """
    record = load_period(period)
    addition = record.added.pop(metric, None)
    removal = record.removed.pop(metric, None)
    if addition is None and removal is None:
        return False
    period.corrections = record.as_dict() if record else None
    if addition is not None:
        restore(period, metric, value=addition.was, source=addition.was_source)
    elif removal is not None:
        restore(period, metric, value=removal.was)
    apply_to_row(period, rules)
    return True


def forget_rule(rules: Rules, metric: str) -> bool:
    """Drop a filer-wide removal, and report whether there was one."""
    return rules.removed.pop(metric, None) is not None


def filer_periods(session: Any, cik: str | None) -> list[FundamentalPeriod]:
    """Every period stored for a filer, oldest first."""
    if not cik:
        return []
    rows = session.execute(
        select(FundamentalPeriod)
        .join(
            Instrument,
            Instrument.t212_ticker == FundamentalPeriod.instrument_t212_ticker,
        )
        .where(Instrument.sec_cik == cik)
        .order_by(FundamentalPeriod.period_end)
    ).scalars()
    return list(rows)


def reapply_filer(
    session: Any, cik: str | None, rules: Rules, *, restoring: str | None = None
) -> int:
    """Apply a filer's rules to every period it has, and say how many rows were rewritten.

    A rule is a statement about every period the filer filed, and the accounts page reads a
    *row* rather than the rule, so recording one and waiting for each period's next sync would
    leave the other periods of the same filer disagreeing with the one the reader was looking
    at. It is a database walk with no provider call: the figures being corrected are stored.
    ``restoring`` names a line to restore from each row's own evidence first, which is what
    undoing a rule needs -- the rule took the line out of every row it applied to.
    """
    rows = filer_periods(session, cik)
    for row in rows:
        if restoring is not None:
            restore(row, restoring)
        apply_to_row(row, rules)
    return len(rows)


def corrections_for(period: FundamentalPeriod, rules: Rules | None = None) -> list[dict[str, Any]]:
    """Everything a reader has changed about this period, as plain rows for the page.

    One list for one panel: an addition and a removal are the same kind of thing to the
    reader -- a line that is no longer what the source said -- and two panels would make them
    hunt for which one a mistake is in.

    A filer-wide removal is listed once, marked with its scope and with its own undo, unless
    this period also removed the same metric by itself: then the period's own entry is the one
    shown, because that is the one whose undo is on this page.
    """
    record = load_period(period)
    out: list[dict[str, Any]] = []
    for name, addition in sorted(record.added.items()):
        out.append(
            {
                "metric": name,
                "action": "added",
                "value": addition.value,
                "side": addition.side,
                "tag": addition.tag,
                "url": addition.url,
                "at": addition.at,
                "note": addition.note,
                "origin": addition.origin,
                "scope": "period",
                # The rule removes this line everywhere and this period holds a figure for it
                # anyway, because an addition is applied after the rules. The page says so
                # rather than printing two rows that appear to contradict each other.
                "overrides_rule": bool(rules and name in rules.removed),
            }
        )
    for name, removal in sorted(record.removed.items()):
        out.append(
            {
                "metric": name,
                "action": "removed",
                "value": removal.was,
                "side": "",
                "tag": removal.tag,
                "url": "",
                "at": removal.at,
                "note": removal.reason,
                "origin": "",
                "scope": "period",
                "overrides_rule": False,
            }
        )
    for name, removal in sorted((rules.removed if rules else {}).items()):
        if name in record.removed or name in record.added:
            # This period has its own decision about the line, and its decision is the one the
            # arithmetic obeyed.
            continue
        out.append(
            {
                "metric": name,
                "action": "removed",
                "value": removal.was,
                "side": "",
                "tag": removal.tag,
                "url": "",
                "at": removal.at,
                "note": removal.reason,
                "origin": "",
                "scope": "filer",
                "overrides_rule": False,
            }
        )
    return out


__all__ = [
    "CREDIT",
    "DEBIT",
    "MANUAL",
    "NO_REASON",
    "SETTING_PREFIX",
    "Correction",
    "Record",
    "Removal",
    "Rules",
    "add",
    "apply",
    "apply_to_row",
    "corrections_for",
    "filer_periods",
    "forget",
    "forget_rule",
    "key",
    "load_filer",
    "load_period",
    "reapply_filer",
    "remove",
    "restore",
    "save_filer",
    "save_period",
    "stamp",
]
