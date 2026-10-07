"""Normalise outflows to positive magnitudes, in the rows already stored.

Revision ID: 0014_outflow_signs
Revises: 0013_news_subject
Create Date: 2026-10-07

`analysis/ledger.py` subtracts outflows -- ``explained = operating - capex -
dividends`` and ``free_cash_flow = operating_cash_flow - capex`` -- so `capex` and
`dividends_paid` have to be stored as positive magnitudes whatever sign the provider
used. The Yahoo adapter normalised `capex` alone, because that was the one a check
happened to trip over, and left `dividends_paid` with Yahoo's own sign: a *credit*, and
therefore negative.

Measured 2026-10-07 on `MSFT_US_EQ`: `capex` is positive in both sources and
``ocf - capex`` equals the stored ``free_cash_flow`` in all six stored periods, while
`dividends_paid` is stored **negative in 16 `yahoo_statements` periods against 1
`xbrl_companyfacts` period**. The retained-earnings roll-forward was out by exactly
twice the dividend -- 52.9bn on a 26.4bn dividend -- which is the signature of a sign
error and not of a missing line, and it is what made two sources disagree about the same
filing.

Fixed at the adapter from now on. This rewrites the rows already stored, because a
period is not re-fetched until the rotation reaches it and until then the checks would
keep reading the old sign.

Guarded, because the value is JSON and a row may hold either a bare number or an object
with a ``value`` key -- both shapes are in the database.
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "0014_outflow_signs"
down_revision = "0013_news_subject"
branch_labels = None
depends_on = None

_TABLE = "fundamental_period"


def upgrade() -> None:
    from awltux.metrics import OUTFLOW_METRICS

    bind = op.get_bind()
    rows = bind.execute(sa.text(f"SELECT id, metrics FROM {_TABLE}")).all()  # noqa: S608
    updates = []
    for row_id, raw in rows:
        if not raw:
            continue
        metrics = raw if isinstance(raw, dict) else _loads(raw)
        if not isinstance(metrics, dict):
            continue
        changed = False
        for key in OUTFLOW_METRICS:
            entry = metrics.get(key)
            if isinstance(entry, dict):
                value = entry.get("value")
                if isinstance(value, (int, float)) and value < 0:
                    entry["value"] = abs(value)
                    changed = True
            elif isinstance(entry, (int, float)) and entry < 0:
                metrics[key] = abs(entry)
                changed = True
            elif isinstance(entry, str):
                try:
                    number = float(entry)
                except ValueError:
                    continue
                if number < 0:
                    metrics[key] = abs(number)
                    changed = True
        if changed:
            updates.append({"id": row_id, "metrics": json.dumps(metrics)})
    if updates:
        bind.execute(
            sa.text(f"UPDATE {_TABLE} SET metrics = :metrics WHERE id = :id"),  # noqa: S608
            updates,
        )


def _loads(raw: object) -> object:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", "ignore")
    if not isinstance(raw, str):
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def downgrade() -> None:
    """Not reversible, and deliberately not pretended.

    The migration discards information -- which rows held the provider's sign -- and
    there is nothing to restore: the sign was wrong. A downgrade that invented a
    negative value again would be re-creating the bug it removed.
    """
