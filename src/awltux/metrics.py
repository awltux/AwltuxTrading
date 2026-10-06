"""The canonical metric vocabulary.

Every financial figure in this system travels through one duct: it is a key in a
``FundamentalPeriod.metrics`` dict. Providers write into it, the LLM extractor
writes into it, and the analysis layer reads out of it.

**Why this is one module and not three lists.** It used to be three lists that
had to agree: the extractor's gate in ``llm/extractors.py``, the provider mapping
in ``ingest/fundamentals.py``, and the prose list inside the extraction prompt.
They did not agree -- the prompt omitted ``interest_expense``,
``current_liabilities`` and ``current_assets``, which the other two had. A figure
the prompt never asks for is a figure that does not exist, so the two ends of the
pipeline disagreed about what the system could know, silently.

**Adding a name here is a deliberate act.** A name in the gate but not in the
prompt is never extracted. A name in the prompt but not in the gate is discarded
on arrival, which looks exactly like the model failing to find it. Both are
invisible at runtime, which is why the prompt is *generated* from
:func:`prompt_metric_names` rather than typed out beside it.

**Units are not normalised and must not be assumed.** A Yahoo statement states
actual currency units; a filing extraction states whatever the document used,
which for a UK annual report is usually thousands or millions. Ratios *inside* a
period are therefore safe and cross-period additions are not. Every marker built
on these metrics is written to be a ratio within a period, or a comparison of
ratios across periods, for that reason.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

#: Income-statement figures.
INCOME_METRICS: tuple[str, ...] = (
    "revenue",
    "cost_of_goods_sold",
    "gross_profit",
    "research_and_development",
    "sga_expense",
    "operating_income",
    "ebit",
    "ebitda",
    "depreciation_amortisation",
    "interest_expense",
    "interest_income",
    "other_nonoperating_income",
    "pretax_income",
    "tax_expense",
    "net_income",
    "eps_diluted",
    "dividend_per_share",
)

#: Balance-sheet figures.
BALANCE_METRICS: tuple[str, ...] = (
    "cash_and_equivalents",
    "receivables",
    "inventory",
    "current_assets",
    "net_ppe",
    "goodwill",
    "intangible_assets",
    "total_assets",
    "payables",
    "short_term_debt",
    "current_liabilities",
    "long_term_debt",
    "lease_liabilities",
    "total_debt",
    "total_liabilities",
    "retained_earnings",
    "total_equity",
    "shares_outstanding",
    "stock_based_compensation",
)

#: Cash-flow figures.
CASH_METRICS: tuple[str, ...] = (
    "operating_cash_flow",
    "capex",
    "free_cash_flow",
    "dividends_paid",
)

#: Derived ratios computed by :func:`awltux.ingest.fundamentals.derive_metrics`
#: rather than stated by any provider. They are canonical too -- the analysis
#: layer reads them by name -- but no extractor is ever asked for them, because
#: asking a model to divide two numbers is how a citation stops meaning anything.
DERIVED_METRICS: tuple[str, ...] = (
    "gross_margin",
    "operating_margin",
    "net_margin",
    "ebitda_margin",
    "net_debt",
    "roe",
    "roa",
    "roce",
    "debt_to_equity",
    "interest_cover",
    "payout_ratio",
)

#: Presentation order for the extraction prompt: the order a set of accounts
#: reads in, which is the order a model is least likely to skip a section of.
STATED_METRICS: tuple[str, ...] = INCOME_METRICS + BALANCE_METRICS + CASH_METRICS

#: Why each stated metric is collected, and what consumes it. This exists so that
#: a future reader can tell whether a name is load-bearing before removing it.
METRIC_NOTES: dict[str, str] = {
    "revenue": "scale for every margin; DSO and asset turnover denominators",
    "cost_of_goods_sold": "fallback when gross profit is not stated directly",
    "gross_profit": "gross margin, Beneish GMI, gross profitability",
    "research_and_development": "capitalisation drift; a discretionary cost",
    "sga_expense": "Beneish SGAI in the eight-variable variant",
    "operating_income": "ROCE, interest cover, margin trend",
    "ebit": "NOPAT and Altman Z''; distinct from operating income when there is non-operating income",
    "ebitda": "net debt / EBITDA",
    "depreciation_amortisation": "accruals (balance-sheet method), reinvestment rate",
    "interest_expense": "interest cover and the cost of debt in WACC",
    "interest_income": (
        "the other half of net interest, and what separates operating profit from "
        "profit before tax; without it the P&L cannot articulate"
    ),
    "other_nonoperating_income": (
        "the residual between operating profit and profit before tax that is neither "
        "interest nor tax -- disposals, FX, associates; signed"
    ),
    "pretax_income": "effective tax rate for NOPAT",
    "tax_expense": "effective tax rate for NOPAT",
    "net_income": "ROE, ROA, payout, cash conversion",
    "eps_diluted": "payout ratio; earnings per share trend",
    "dividend_per_share": "payout ratio, dividend cover",
    "cash_and_equivalents": "net debt, Altman inputs, invested capital",
    "receivables": "DSO and its trend; Beneish DSRI; accruals",
    "inventory": "inventory drift against revenue; accruals",
    "current_assets": "working capital, current ratio, Piotroski liquidity",
    "net_ppe": "Beneish AQI; the operating definition of invested capital",
    "goodwill": "equity softness and the serial-acquirer flag",
    "intangible_assets": "equity softness; capitalisation drift",
    "total_assets": "every ratio's denominator, accrual ratio, gross profitability",
    "payables": "accruals (balance-sheet method)",
    "short_term_debt": "accruals; the debt maturity wall",
    "current_liabilities": "working capital, current ratio, Piotroski liquidity",
    "long_term_debt": "Piotroski's leverage test; the debt maturity wall",
    "lease_liabilities": "the IFRS 16 adjustment that makes cross-border debt comparable",
    "total_debt": "net debt, WACC weights, invested capital",
    "total_liabilities": "Altman Z''; liabilities-to-equity",
    "retained_earnings": "Altman Z'' -- an input the score needs and the accounts state",
    "total_equity": "ROE, book value, invested capital",
    "shares_outstanding": "Piotroski's dilution test; buyback-versus-dilution",
    "stock_based_compensation": "the cash cost that never appears in cash flow",
    "operating_cash_flow": "cash conversion and accruals -- the two strongest diagnostics",
    "capex": "free cash flow, reinvestment rate",
    "free_cash_flow": "cash generation after maintenance of the asset base",
    "dividends_paid": "capital allocation; a dividend funded by borrowing",
}

#: Every key a ``FundamentalPeriod.metrics`` dict may legitimately carry: what a
#: provider or extractor stated, plus what we derived from it.
CANONICAL_METRICS: frozenset[str] = frozenset(STATED_METRICS) | frozenset(DERIVED_METRICS)

#: The extraction gate, and deliberately narrower than :data:`CANONICAL_METRICS`.
#: A metric key outside this set is discarded by
#: :func:`awltux.llm.extractors.validate_extraction` and the discard is recorded,
#: so an invented key is visible rather than silently stored.
#:
#: The derived ratios are excluded on purpose. They are ours: ``roce`` has a
#: definition in this codebase, and a model that returns its own ``roce`` with a
#: citation would be storing a figure the analysis layer then reads as if it had
#: computed it. A model may report the two numbers; only this code may divide
#: them.
EXTRACTABLE_METRICS: frozenset[str] = frozenset(STATED_METRICS)


def prompt_metric_names() -> str:
    """The canonical names, formatted for the extraction prompt.

    Generated rather than typed, so the prompt cannot quietly fall behind the
    gate. See the module docstring: that is exactly the bug this file was written
    to end.
    """
    lines: list[str] = []
    for label, group in (
        ("income statement", INCOME_METRICS),
        ("balance sheet", BALANCE_METRICS),
        ("cash flow", CASH_METRICS),
    ):
        lines.append(f"{label}: " + ", ".join(group))
    return "\n".join(lines)


def is_canonical(name: str) -> bool:
    return name in CANONICAL_METRICS


def value_of(metrics: Mapping[str, Any] | None, key: str) -> float | None:
    """Read one metric as a usable number.

    Every marker in the analysis layer reads its inputs through this, because the
    failure it prevents is specific: a ``NaN`` or an ``inf`` from a provider is a
    perfectly good float as far as Python is concerned, and it propagates through
    a ratio into a ranking without ever raising. A value that cannot be used is
    returned as missing, which the markers treat as a reason to say nothing.
    """
    if not metrics:
        return None
    raw = metrics.get(key)
    if raw is None:
        return None
    try:
        number = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number
