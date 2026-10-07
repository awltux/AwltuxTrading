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

**Units are normalised on the way in, and the docstring used to say the opposite.** It
said units are not normalised and must not be assumed -- a Yahoo statement states actual
currency units, a filing extraction states whatever the document used -- and that every
marker is therefore written as a ratio within a period. That held only while every stored
period came from a provider that states actual units. `analysis/fundamental.py` ranks
`llm_extraction` **first** among sources, so the first extracted period to be stored
unscaled would win every comparison and put MSFT's revenue at 331,839 rather than
331,839,012,864 -- a factor of a million, in the figures the dashboard and the valuation
both print. See :func:`unit_scale`, and `ingest/parsing.py` for where it is applied.

**Adding a name here is a deliberate act.** A name in the gate but not in the
prompt is never extracted. A name in the prompt but not in the gate is discarded
on arrival, which looks exactly like the model failing to find it. Both are
invisible at runtime, which is why the prompt is *generated* from
:func:`prompt_metric_names` rather than typed out beside it.
"""

from __future__ import annotations

import math
import re
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

#: Balance-sheet figures, in the order a balance sheet reads: what is owned, then what
#: is owed, then the equity that balances it. The order reaches the extraction prompt,
#: so it is also the order a model is least likely to skip a section of.
BALANCE_METRICS: tuple[str, ...] = (
    # current assets
    "cash_and_equivalents",
    "receivables",
    "inventory",
    "other_current_assets",
    "current_assets",
    # non-current assets
    "net_ppe",
    "operating_lease_assets",
    "goodwill",
    "intangible_assets",
    "other_noncurrent_assets",
    "total_assets",
    # current liabilities
    "payables",
    "compensation_and_benefits",
    "other_current_liabilities",
    "short_term_debt",
    "current_liabilities",
    # non-current liabilities
    "long_term_debt",
    "lease_liabilities",
    "other_noncurrent_liabilities",
    "total_liabilities",
    # memorandum and equity
    "total_debt",
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
    "operating_lease_assets": (
        "the right-of-use asset IFRS 16 and ASC 842 put on the balance sheet; the "
        "counterpart to `lease_liabilities`, and absent from any pre-2019 filing"
    ),
    "other_noncurrent_assets": (
        "the non-current assets that are not PP&E, goodwill or intangibles -- "
        "deferred tax, pensions, long-term investments"
    ),
    "other_current_assets": (
        "the current assets that are not cash, receivables or inventory -- prepayments, "
        "held-for-sale, short-term investments"
    ),
    "goodwill": "equity softness and the serial-acquirer flag",
    "intangible_assets": "equity softness; capitalisation drift",
    "total_assets": "every ratio's denominator, accrual ratio, gross profitability",
    "payables": "accruals (balance-sheet method)",
    "compensation_and_benefits": (
        "accrued payroll, bonuses and benefits -- the caption a US filer reports as "
        "'Compensation and related benefits' and most others as accrued liabilities"
    ),
    "other_current_liabilities": (
        "the current liabilities that are not payables, accruals or borrowings -- "
        "deferred revenue, taxes, the current portion of lease liabilities"
    ),
    "other_noncurrent_liabilities": (
        "the residual non-current liability caption; by construction it contains "
        "whatever the filer did not present as its own line, which for many filers "
        "includes the operating lease liability -- see `lease_liabilities`"
    ),
    "short_term_debt": "accruals; the debt maturity wall",
    "current_liabilities": "working capital, current ratio, Piotroski liquidity",
    "long_term_debt": "Piotroski's leverage test; the debt maturity wall",
    "lease_liabilities": "the IFRS 16 adjustment that makes cross-border debt comparable",    "total_debt": "net debt, WACC weights, invested capital",
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

#: Metrics stated as a **positive magnitude of outflow**, whatever sign a provider uses.
#:
#: The convention is not decoration: `analysis/ledger.py` subtracts these
#: (``explained = operating - capex - dividends``) and ``free_cash_flow`` is computed as
#: ``operating_cash_flow - capex``. A provider that reports them negatively -- as a
#: credit rather than a debit -- therefore flips a *plus* into a *minus* in every check
#: that reads them, and doubles the error.
#:
#: Measured 2026-10-07 on `MSFT_US_EQ`: `capex` is positive in both sources and
#: ``ocf - capex`` equals the stored ``free_cash_flow`` in all six stored periods, but
#: `dividends_paid` is stored **negative by `yahoo_statements` and positive by
#: `xbrl_companyfacts`** -- 16 periods against 1. The retained-earnings roll-forward was
#: consequently out by exactly twice the dividend, 52.9bn, which is the signature of a
#: sign error rather than a missing line.
OUTFLOW_METRICS: frozenset[str] = frozenset({"capex", "dividends_paid"})


def is_canonical(name: str) -> bool:
    return name in CANONICAL_METRICS


#: What a filing's stated units multiply to, to give actual currency units.
#:
#: Keyed on the word a document uses rather than on a fixed list of phrases, because a
#: filing writes "in millions", "USD millions", "($000s)" and "thousands of Canadian
#: dollars" for the same thing. Matched against whole words of the lowercased string.
UNIT_SCALES: tuple[tuple[str, float], ...] = (
    ("billions", 1e9),
    ("billion", 1e9),
    ("millions", 1e6),
    ("million", 1e6),
    ("thousands", 1e3),
    ("thousand", 1e3),
    ("000s", 1e3),
    ("000", 1e3),
    ("actual", 1.0),
    ("units", 1.0),
    ("ones", 1.0),
)

#: Splitting on anything that is not a letter or a digit is what makes ``($000's)`` and
#: ``US$'000`` both read as thousands.
_UNIT_WORD = re.compile(r"[a-z0-9]+")


def unit_scale(units: str | None) -> float | None:
    """The multiplier from a filing's stated units to actual currency units.

    ``None`` when the document did not say, or said something not recognised -- and the
    caller must refuse the period rather than store it. Getting this wrong is a silent
    factor of a million in every absolute figure the dashboard prints, and there is no
    later marker that would notice: the ratios are scale-invariant, so the analysis would
    look healthy while the numbers beside it were wrong.

    Whole words, largest first: whole words so that a hedge like "unstated" is not read as
    "stated units", and largest first so that a document naming two -- "in thousands of
    units" -- is read as thousands, with the vague "units"/"ones" catch-alls tried last.
    """
    if not units:
        return None
    words = _UNIT_WORD.findall(str(units).lower())
    if not words:
        return None
    for token, scale in UNIT_SCALES:
        if token in words:
            return scale
    return None


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
