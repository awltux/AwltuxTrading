"""DeepSeek layer: investigation and summarisation.

This package reads documents and produces cited, structured facts. It is
deliberately kept away from the arithmetic: no figure produced here reaches a
valuation unless it carries a source span and survives validation, because a
language model that is asked for a number will always supply one.
"""

from awltux.llm.deepseek import (
    BudgetExceeded,
    Completion,
    DeepSeekClient,
    DeepSeekError,
    build_messages,
    estimate_cost,
    month_to_date_spend,
    spend_report,
)

__all__ = [
    "BudgetExceeded",
    "Completion",
    "DeepSeekClient",
    "DeepSeekError",
    "build_messages",
    "estimate_cost",
    "month_to_date_spend",
    "spend_report",
]
