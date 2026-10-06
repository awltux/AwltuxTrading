"""What each field on the dashboard is, and how to read it.

Asked for by a reader: *"I don't understand what they represent and how to read them."*
That is a failure of the interface rather than of the analysis, and the fix belongs in
one place rather than in four templates.

**Two sentences per field, and the second is the one that matters.** ``what`` says what
the number is; ``reading`` says which direction is good and what it is not, because
"margin of safety 12%" is unreadable without knowing that bigger is safer and that it is
a percentage of an estimate rather than of a fact. The failure mode this avoids is the
one the marker work already names: a figure that reads as a verdict.

**The text lives here, not in the templates.** The same field appears on the dashboard
and on an instrument page, and two copies of an explanation drift the same way two
copies of a rule do. `web/templating.py` owns formatting for the same reason.

Nothing here is invented: every entry describes what the code actually computes, and
where a figure is a model's statement rather than arithmetic, it says so.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Field:
    """One explainable field."""

    key: str
    label: str
    #: What the number is.
    what: str
    #: How to read it -- direction, scale, and what it is not.
    reading: str


#: Every field with an explanation, keyed by the name the templates use.
FIELDS: tuple[Field, ...] = (
    # ------------------------------------------------------------ the shares
    Field(
        "name",
        "Instrument",
        "The share you would trade, by its Trading 212 ticker, with the issuer's name "
        "underneath and its sector beside it.",
        "The sector is clickable: it filters the table to that industry, which is how "
        "you compare a company against its actual peers rather than the whole market.",
    ),
    Field(
        "price",
        "Price",
        "The last end-of-day close we hold, in the instrument's own currency.",
        "From a free feed, so it is delayed and unofficial. Every ratio below is "
        "computed from this figure, and the 'Updated' column says how old the "
        "underlying decision is.",
    ),
    # -------------------------------------------------------------- the verdict
    Field(
        "horizon_fit",
        "Suits",
        "Which horizon the evidence actually supports: both, long term only, short "
        "term only, or neither.",
        "Derived from the two verdicts rather than scored. 'Neither' is the common and "
        "correct answer -- most shares are not interesting at either horizon, and a "
        "table where everything says 'both' would be a table that had stopped "
        "discriminating.",
    ),
    Field(
        "long_term_action",
        "Long term",
        "The 12-36 month verdict: buy, hold, sell or avoid.",
        "A blank is not a failure. The engine refuses to answer when its confidence "
        "falls below a floor, and it reports a refusal rather than issuing a weak call "
        "-- hover the reason beside it to see which check refused.",
    ),
    Field(
        "short_term_action",
        "Short term",
        "The 5-20 trading day verdict.",
        "Deliberately able to disagree with the long-term column: a share can be a poor "
        "business trading well, or a good one that has run ahead of itself. When the "
        "two disagree the row is worth reading rather than dismissing.",
    ),
    Field(
        "composite_score",
        "L score",
        "The long-term engine's own score for this share.",
        "On that engine's own scale, so it ranks shares **within** an engine and means "
        "nothing across engines. It is not a probability and not a percentage.",
    ),
    Field(
        "short_term_score",
        "S score",
        "The short-term engine's own score.",
        "Same caveat as the L score: an engine's own scale, comparable only with other "
        "rows from the same engine.",
    ),
    Field(
        "confidence",
        "L conf.",
        "How sure the engine says it is, from 0 to 1.",
        "Three different quantities are called 'confidence' in this system. This one is "
        "the engine's own statement, and it is compared against a per-engine floor "
        "before a verdict is allowed. Where the engine label says 'uncalibrated', the "
        "accuracy of that scale has not been measured yet -- so read it as the engine's "
        "claim, not as a probability.",
    ),
    Field(
        "short_term_confidence",
        "S conf.",
        "How sure the short-term engine says it is, from 0 to 1.",
        "Same reading as L conf., and the same floor: below it the call is refused "
        "rather than downgraded to a 'hold'.",
    ),
    Field(
        "margin_of_safety",
        "Margin of safety",
        "How far the price sits below the estimated value of the business: the "
        "discount, as a percentage of that estimate.",
        "**Bigger is safer**, and negative means the shares trade above the estimate. "
        "It is a percentage of an estimate, not of a fact -- the valuation range above "
        "it is the honest part, and a large margin of safety built on a low-confidence "
        "valuation is not a bargain, it is an unknown quantity.",
    ),
    Field(
        "sentiment",
        "Sentiment",
        "What the news coverage looks like, aggregated across this share's recent "
        "stories and weighted by how sceptically each one was appraised.",
        "A reading of the coverage, not of the business. Single-source stories from "
        "weak publishers count for less, and a share can be rising on nothing but "
        "republication -- which is what the credibility weighting is there to detect.",
    ),
    Field(
        "setup",
        "Setup / risk",
        "The quality of the tactical setup, from 0 (poor) to 4 (excellent).",
        "A short-horizon judgement about the chart and the entry, not about the "
        "company. It pairs with 'Short term': a good setup with no fundamental support "
        "is a trade, not an investment.",
    ),
    Field(
        "engine",
        "Engine",
        "Which engine produced the verdict: a language model, or the deterministic "
        "rules used when no model key is configured.",
        "The label matters more than it looks. A deterministic verdict is reproducible "
        "and auditable; a model verdict is neither, which is why every decision is "
        "stored with the prompt and state that produced it.",
    ),
    Field(
        "freshness",
        "Updated",
        "When the decision for this row was made.",
        "A stale verdict is not wrong, it is old: prices move and accounts are "
        "restated. Sort by it to find the rows nothing has looked at recently.",
    ),
    # --------------------------------------------------------------- valuation
    Field(
        "fair_value_base",
        "Fair value (base)",
        "The single-point estimate of what one share is worth, from the base case.",
        "One number from a range of methods. Read it with its range and its confidence "
        "rather than on its own.",
    ),
    Field(
        "fair_value_range",
        "Range",
        "Low to high across the valuation methods and the assumptions each used.",
        "The price sitting **outside** the range is the interesting case; inside it, the "
        "market and the model broadly agree. A very wide range means the methods "
        "disagree, which is information about the business rather than a failure of the "
        "arithmetic.",
    ),
    Field(
        "methods_applied",
        "Methods applied",
        "Which valuation methods produced a defensible number for this company.",
        "Each method needs inputs not every company has, so the set differs by filer. "
        "A single method means a single assumption is carrying the whole estimate -- "
        "open the per-method table to see which.",
    ),
    # ---------------------------------------------------------------- accounts
    Field(
        "stated",
        "Stated",
        "The figure the filing itself reports.",
        "Compared against 'Computed'. Where the two differ, the difference is the "
        "accounts this project does not extract rather than an error in the filing.",
    ),
    Field(
        "computed",
        "Computed",
        "What this project's arithmetic makes of the component lines it holds.",
        "It uses fewer lines than the filing does, so it will usually differ from "
        "'Stated'. A large difference means the statement is built on a small part of "
        "the real accounts, which is worth knowing before trusting a ratio from it.",
    ),
    # ------------------------------------------------------------ the counters
    Field(
        "universe_size",
        "In universe",
        "How many instruments are being analysed: the shares selected by size and "
        "liquidity from the full Trading 212 list.",
        "The other counters are fractions of this one. A small universe makes every "
        "aggregate noisy, and an empty one explains a blank table.",
    ),
    Field(
        "mapped",
        "Price-mapped",
        "How many of the universe have a price feed mapped to them.",
        "The gap between this and 'in universe' is instruments whose provider symbol "
        "could not be resolved. They cannot be valued, so they cannot be decided.",
    ),
    Field(
        "decided",
        "Decided",
        "How many have a stored decision.",
        "Below 'price-mapped' means the pipeline has not reached them yet; the "
        "Operations page shows which job is behind.",
    ),
)

BY_KEY: dict[str, Field] = {field.key: field for field in FIELDS}


def explanation(key: str) -> str:
    """The tooltip text for a field, or an empty string for an unknown one.

    Empty rather than a placeholder: a tooltip reading "no description" is worse than
    no tooltip, and an unknown key here is a template referring to something this file
    has not been told about, which is a real gap rather than a state to display.
    """
    field = BY_KEY.get(key)
    if field is None:
        return ""
    return f"{field.what} {field.reading}"


def label(key: str, fallback: str = "") -> str:
    """The field's display label, for a page that would rather read it from here."""
    field = BY_KEY.get(key)
    return field.label if field else fallback
