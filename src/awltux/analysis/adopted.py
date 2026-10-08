"""Captions this app has adopted into a line, per filer, and the proof that put them there.

**Why a per-filer mapping and not a code change.** `ingest/xbrl.py`'s ``TAG_MAP`` is
global: `other_current_assets` is supplied by ``OtherAssetsCurrent`` or
``PrepaidExpenseAndOtherAssetsCurrent`` for *every* filer. A balance sheet is not global.
Measured 2026-10-08 over the 98 companyfacts payloads archived on the volume, adding two
captions that close `DAC_US_EQ` to the bucket line:

    candidate                          checks closed   worse   newly failing
    PrepaidExpenseCurrent                          8       0              15
    ContractWithCustomerLiabilityCurrent           5      14               4

Both are *parts of the residual caption we already read* for most filers --
``PrepaidExpenseAndOtherAssetsCurrent`` contains the prepayments -- so a global addition
double counts for them. The filer's own calculation linkbase says which it is, per filing,
and :func:`awltux.analysis.linkbase.provable` turns that into arithmetic: when the declared
leaves we do not hold add up to the residual to the pound, the declaration has said which
lines the total is short by.

**Keyed by CIK, not by accession.** The mapping is a fact about the *filer*: its next
year's filing declares the same lines, and re-proving it every year would be busywork. The
evidence names the accession each caption was proven from, so the adoption is checkable
and removable long after the run that made it.

Kept in `app_setting` like `analysis/metric_fields`' discovered vocabulary and the macro
module's observed rate -- a small record read whole and joined on by nothing.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from awltux.analysis.linkbase import Proven

logger = logging.getLogger(__name__)

#: One `app_setting` row per filer.
SETTING_PREFIX = "xbrl_adopted:"


def key(cik: str) -> str:
    return f"{SETTING_PREFIX}{str(cik).strip()}"


@dataclass(frozen=True, slots=True)
class Adoption:
    """One filer's adopted captions, and what proved each of them."""

    #: bucket metric -> the tags added to it.
    tags: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: ``{accession, side, residual, at}`` per proof, in the order they were made.
    evidence: tuple[Mapping[str, Any], ...] = ()


def load(session: Any, cik: str | None) -> dict[str, tuple[str, ...]]:
    """The captions adopted for one filer, as ``metric -> tags``.

    An unreadable or absent record is an empty mapping rather than an error: the mapper
    then reads exactly the tags `TAG_MAP` names, which is the behaviour before any of this
    existed.
    """
    from awltux.db import AppSetting

    if not cik:
        return {}
    row = session.get(AppSetting, key(cik))
    value = row.value if row is not None else None
    if not isinstance(value, dict):
        return {}
    return {
        str(metric): tuple(str(tag) for tag in tags)
        for metric, tags in (value.get("tags") or {}).items()
        if tags
    }


def read(session: Any, cik: str | None) -> Adoption:
    """The adoption and its evidence, for a page that has to show where it came from."""
    from awltux.db import AppSetting

    if not cik:
        return Adoption()
    row = session.get(AppSetting, key(cik))
    value = row.value if row is not None else None
    if not isinstance(value, dict):
        return Adoption()
    return Adoption(
        tags=load(session, cik),
        evidence=tuple(
            entry for entry in (value.get("evidence") or []) if isinstance(entry, dict)
        ),
    )


def record(session: Any, cik: str, proven: Iterable[Proven]) -> int:
    """Remember what a filing proved, and return how many captions were newly adopted.

    Merging rather than replacing: a filer files every year, and the second year's filing
    proving the same captions must not drop the first year's evidence -- that evidence is
    what says *when* a caption joined a line, and a mapping nobody can date is a mapping
    nobody can undo with confidence.
    """
    from awltux.db import AppSetting

    proofs = tuple(proven)
    if not proofs:
        return 0
    row = session.get(AppSetting, key(cik))
    value = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
    tags: dict[str, list[str]] = {
        str(metric): list(entry) for metric, entry in (value.get("tags") or {}).items()
    }
    evidence = [entry for entry in (value.get("evidence") or []) if isinstance(entry, dict)]

    added = 0
    for proof in proofs:
        for metric, proven_tags in proof.additions.items():
            existing = tags.setdefault(metric, [])
            for tag in proven_tags:
                if tag not in existing:
                    existing.append(tag)
                    added += 1
        evidence.append(
            {
                "accession": proof.accession,
                "side": proof.side,
                "residual": proof.residual,
                "additions": {
                    metric: list(entry) for metric, entry in proof.additions.items()
                },
                "at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )

    value["tags"] = tags
    value["evidence"] = evidence[-20:]
    if row is None:
        row = AppSetting(key=key(cik))
        session.add(row)
    row.value = value
    row.note = (
        f"{sum(len(entry) for entry in tags.values())} adopted caption(s) "
        f"from {len(evidence)} proof(s)"
    )
    session.flush()
    logger.info("adopted %d caption(s) for CIK %s", added, cik)
    return added


def forget(session: Any, cik: str | None) -> bool:
    """Drop a filer's adoptions, so a wrong proof is not permanent."""
    from awltux.db import AppSetting

    if not cik:
        return False
    row = session.get(AppSetting, key(cik))
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


__all__ = ["Adoption", "SETTING_PREFIX", "forget", "key", "load", "read", "record"]
