"""The typed question set put to the decision model.

Following TypeSafe's own guidance, the judgement is decomposed into **atomic
questions asked together in one request** rather than one broad question. A
fan-out is both cheaper and faster than separate calls, and -- more importantly --
it makes the reasoning inspectable: you can see that the model called the balance
sheet risky while still calling the business high quality, which a single
"should I buy" answer would hide.

Wording rules followed throughout:

* ``instructions`` states the whole question, because the question *name* is
  never sent to the model.
* ``criteria`` describes each option, so the options are comparable rather than
  merely labelled. An undescribed option invites the model to guess its meaning.
* Scales run in one direction only, documented in the criteria, so a 4 always
  means the same thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

QuestionType = Literal["choice", "noul", "score"]


@dataclass(frozen=True, slots=True)
class QuestionDef:
    """A typed question, in a form both JEV and the fallback engines understand."""

    name: str
    type: QuestionType
    instructions: str
    criteria: dict[str, str] | list[str] | dict[str, str] | None = None
    #: Plain-language meaning of the answer, used in the UI and in the narrative.
    meaning: str = ""

    def to_wire(self) -> dict[str, Any]:
        """Serialise into the TypeSafe ``questions`` map entry shape."""
        payload: dict[str, Any] = {"type": self.type, "instructions": self.instructions}
        if self.criteria is not None:
            payload["criteria"] = self.criteria
        return payload

    @property
    def levels(self) -> int:
        if self.type == "score" and isinstance(self.criteria, list):
            return len(self.criteria)
        if self.type == "choice" and isinstance(self.criteria, dict):
            return len(self.criteria)
        return 2

    def options(self) -> list[str]:
        if isinstance(self.criteria, list):
            return list(self.criteria)
        if isinstance(self.criteria, dict):
            return list(self.criteria)
        return ["true", "false"]


# --------------------------------------------------------------------------- #
# the question set
# --------------------------------------------------------------------------- #

VALUATION_VERDICT = QuestionDef(
    name="valuation_verdict",
    type="choice",
    meaning="Is the share under- or over-valued against the evidence provided?",
    instructions=(
        "Given the deterministic valuation range, the quality of the accounts and "
        "the current price, how would you characterise this share's valuation?"
    ),
    criteria={
        "deeply_undervalued": "Price is far below a defensible estimate of intrinsic value, with a large margin of safety and no obvious reason for the discount.",
        "undervalued": "Price is meaningfully below intrinsic value, with a reasonable margin of safety.",
        "fairly_valued": "Price is close to intrinsic value; the margin of safety is thin or absent in either direction.",
        "overvalued": "Price is meaningfully above intrinsic value.",
        "deeply_overvalued": "Price is far above any defensible estimate of intrinsic value.",
    },
)

MARGIN_OF_SAFETY = QuestionDef(
    name="margin_of_safety",
    type="score",
    meaning="How much cushion exists between price and value?",
    instructions=(
        "How much margin of safety does the current price offer relative to a "
        "realistic estimate of intrinsic value? Level 0 means none or negative, "
        "level 4 means unusually large."
    ),
    criteria=[
        "None or negative — price is at or above fair value.",
        "Thin — a small discount that a modest disappointment would erase.",
        "Adequate — a real discount of roughly a fifth to a third.",
        "Large — a substantial discount, but not an extreme one.",
        "Exceptional — price is far below value on conservative assumptions.",
    ],
)

BUSINESS_QUALITY = QuestionDef(
    name="business_quality",
    type="score",
    meaning="How durable and profitable is the underlying business?",
    instructions=(
        "How would you rate the quality of this business, considering returns on "
        "capital, margin stability, competitive position and the durability of its "
        "earnings? Level 0 is a poor business, level 4 is an excellent one."
    ),
    criteria=[
        "Poor — low or negative returns on capital, unstable margins, no evident advantage.",
        "Weak — returns around the cost of capital, cyclical or easily competed away.",
        "Average — decent returns and a stable franchise, without a strong moat.",
        "Good — consistently high returns on capital and evidence of a durable advantage.",
        "Excellent — exceptional, persistent returns on capital and a wide, defensible moat.",
    ],
)

BALANCE_SHEET_RISK = QuestionDef(
    name="balance_sheet_risk",
    type="score",
    meaning="How much financial risk sits on the balance sheet?",
    instructions=(
        "How much balance-sheet risk does this company carry? Consider leverage, "
        "interest cover, liquidity and refinancing exposure. Level 0 is minimal "
        "risk, level 4 is severe risk."
    ),
    criteria=[
        "Minimal — net cash or negligible debt, ample liquidity.",
        "Low — modest debt, comfortable interest cover.",
        "Moderate — meaningful debt that is serviceable but leaves little slack.",
        "High — leverage that would strain the company in a downturn.",
        "Severe — solvency or refinancing risk is a live concern.",
    ],
)

EARNINGS_TREND = QuestionDef(
    name="earnings_trend",
    type="choice",
    meaning="Which way are earnings going?",
    instructions="What is the direction and consistency of this company's earnings trend?",
    criteria={
        "improving": "Earnings are growing and the direction is consistent.",
        "stable": "Earnings are broadly flat and predictable.",
        "deteriorating": "Earnings are declining, or margins are compressing steadily.",
        "volatile": "Earnings swing widely with no clear direction.",
    },
)

NEWS_MATERIALITY = QuestionDef(
    name="news_materiality",
    type="choice",
    meaning="Do recent headlines change the investment case?",
    instructions=(
        "Considering the recent headlines provided, what is their likely net effect "
        "on this company's value?"
    ),
    criteria={
        "material_positive": "News that plausibly changes the outlook for the better in a lasting way.",
        "mild_positive": "Mildly favourable news without a durable effect on value.",
        "neutral": "Nothing in the news that should move the share price durably.",
        "mild_negative": "Mildly adverse news without lasting consequence.",
        "material_negative": "News that plausibly impairs value or the outlook durably.",
    },
)

SENTIMENT_REGIME = QuestionDef(
    name="sentiment_regime",
    type="choice",
    meaning="How is the market currently disposed towards this name and its sector?",
    instructions=(
        "What is the prevailing market sentiment towards this instrument and its "
        "sector? Consider the sentiment score, price momentum and the tone of news."
    ),
    criteria={
        "euphoric": "Sentiment is extremely positive and may be detached from fundamentals.",
        "positive": "Sentiment is clearly positive.",
        "neutral": "Sentiment is balanced or indifferent.",
        "negative": "Sentiment is clearly negative.",
        "fearful": "Sentiment is extremely negative, with evidence of capitulation.",
    },
)

GOING_CONCERN = QuestionDef(
    name="going_concern",
    type="noul",
    meaning="Is there doubt the company can continue as a going concern?",
    instructions=(
        "Is there credible evidence that this company faces a going-concern risk, "
        "such as insolvency warnings, covenant breaches or an inability to meet "
        "near-term obligations?"
    ),
    criteria={
        "true": "There is evidence of a real threat to continued operation.",
        "false": "There is no credible evidence of a going-concern threat.",
    },
)

DILUTION_RISK = QuestionDef(
    name="dilution_risk",
    type="noul",
    meaning="Are existing shareholders likely to be diluted?",
    instructions=(
        "Is there evidence that existing shareholders face material dilution, such "
        "as a rising share count, an equity raise, or a heavily share-based pay "
        "policy?"
    ),
    criteria={
        "true": "Material dilution is likely or under way.",
        "false": "No material dilution is evident.",
    },
)

ACCOUNTING_RED_FLAGS = QuestionDef(
    name="accounting_red_flags",
    type="noul",
    meaning="Do the accounts show signs of aggressive or opaque reporting?",
    instructions=(
        "Do the accounts show signs of aggressive accounting, poor cash conversion, "
        "unexplained adjustments, or unusual related-party activity?"
    ),
    criteria={
        "true": "There are identifiable red flags in the reported accounts.",
        "false": "The accounts appear clean on the evidence provided.",
    },
)

LONG_TERM_ACTION = QuestionDef(
    name="long_term_action",
    type="choice",
    meaning="What should a long-term (months to years) investor do?",
    instructions=(
        "Consider a holding period of one to three years. For a long-only private "
        "investor, what is the most appropriate action on this instrument? Weigh "
        "the margin of safety, business quality, balance-sheet strength and the "
        "durability of earnings. Do NOT let short-term price movements dominate "
        "this judgement: a temporary drawdown in a sound, cheap business is not a "
        "reason to sell, and momentum in an expensive one is not a reason to buy."
    ),
    criteria={
        "strong_buy": "A high-conviction long-term purchase: undervalued, sound, and well evidenced.",
        "buy": "Attractive over one to three years at this price; worth building a position in.",
        "hold": "A sound long-term holding, but not attractively priced right now.",
        "reduce": "Trim long-term exposure: the valuation or the fundamentals have weakened durably.",
        "sell": "Exit: the long-term investment case has broken.",
        "avoid": "Do not invest on a long-term view: the risks or the price make it unsuitable.",
    },
)

SHORT_TERM_ACTION = QuestionDef(
    name="short_term_action",
    type="choice",
    meaning="What should a short-term (days to weeks) trader do?",
    instructions=(
        "Now consider a completely separate question: a swing horizon of roughly "
        "five to twenty trading days, judged on daily bars. For that horizon, what "
        "is the most appropriate action? Weigh trend alignment, momentum, recent "
        "volume, how extended the move is, the 52-week position, and the direction "
        "of recent news and sentiment. Ignore whether the business is good value "
        "over years -- that is a different question and the answer may differ."
    ),
    criteria={
        "strong_buy": "A well-aligned tactical setup with momentum and confirming news behind it.",
        "buy": "A favourable tactical setup for the next few weeks.",
        "hold": "No tactical edge either way; the setup is unclear or the move is exhausted.",
        "reduce": "Momentum or news has turned against the position over a swing horizon.",
        "sell": "A tactical exit: the setup has broken down.",
        "avoid": "Do not initiate a short-term position: the setup is poor or too risky.",
    },
)

SHORT_TERM_SETUP = QuestionDef(
    name="short_term_setup",
    type="score",
    meaning="How good is the tactical setup for the next few weeks?",
    instructions=(
        "How favourable is the current technical and news setup for a swing trade "
        "over the next five to twenty trading days? Consider trend alignment across "
        "the moving averages, momentum, volume confirmation, and whether price is "
        "breaking out or breaking down. Level 0 is a poor setup, level 4 is an "
        "unusually clean one."
    ),
    criteria=[
        "Poor — price is working against the trend with no supporting catalyst.",
        "Weak — mixed signals; nothing one would act on.",
        "Fair — a modest edge, but nothing that stands out.",
        "Good — trend, momentum and volume broadly agree.",
        "Excellent — a clean, well-confirmed setup with news support.",
    ],
)

SHORT_TERM_DRAWDOWN_RISK = QuestionDef(
    name="short_term_drawdown_risk",
    type="score",
    meaning="How likely is an adverse move over the next few weeks?",
    instructions=(
        "How much risk is there of a sharp adverse move in the next few weeks? "
        "Consider how far and how fast the price has already run, overbought "
        "conditions, realised volatility, thin liquidity, and any scheduled event "
        "such as results. Level 0 is minimal risk, level 4 is severe."
    ),
    criteria=[
        "Minimal — nothing unusual; the move has room to continue.",
        "Low — ordinary market risk for this instrument.",
        "Moderate — somewhat extended, but no specific hazard.",
        "High — materially extended, volatile, or facing a known event.",
        "Severe — extremely extended or a binary event is imminent.",
    ],
)

HORIZON_FIT = QuestionDef(
    name="horizon_fit",
    type="choice",
    meaning="Which horizon does the opportunity actually suit?",
    instructions=(
        "Considering everything above, on which horizon -- if any -- does this "
        "instrument currently offer something worth acting on? Answer 'neither' "
        "when the honest answer is that there is no edge on either timescale."
    ),
    criteria={
        "long_term": "The case rests on value and business quality over years; the short-term setup is unattractive or irrelevant.",
        "short_term": "There is a tactical opportunity over weeks, but the long-term valuation does not support a position.",
        "both": "Attractive on value over years and tactically well set up now.",
        "neither": "No edge on either horizon; nothing here is worth acting on.",
    },
)


#: Sent as a single fan-out request. Order is for readability only; the model
#: evaluates every question independently.
QUESTION_DEFS: tuple[QuestionDef, ...] = (
    VALUATION_VERDICT,
    MARGIN_OF_SAFETY,
    BUSINESS_QUALITY,
    BALANCE_SHEET_RISK,
    EARNINGS_TREND,
    NEWS_MATERIALITY,
    SENTIMENT_REGIME,
    GOING_CONCERN,
    DILUTION_RISK,
    ACCOUNTING_RED_FLAGS,
    LONG_TERM_ACTION,
    SHORT_TERM_ACTION,
    SHORT_TERM_SETUP,
    SHORT_TERM_DRAWDOWN_RISK,
    HORIZON_FIT,
)

QUESTIONS_BY_NAME: dict[str, QuestionDef] = {q.name: q for q in QUESTION_DEFS}

#: Which questions feed which horizon's composite. Kept here, next to the
#: questions themselves, so a new question cannot be added without a decision
#: about which verdict it informs.
LONG_TERM_QUESTIONS: tuple[str, ...] = (
    "margin_of_safety",
    "valuation_verdict",
    "business_quality",
    "balance_sheet_risk",
    "earnings_trend",
    "news_materiality",
    "sentiment_regime",
)

SHORT_TERM_QUESTIONS: tuple[str, ...] = (
    "short_term_setup",
    "short_term_drawdown_risk",
    "valuation_verdict",
    "news_materiality",
    "sentiment_regime",
)


def build_questions() -> dict[str, dict[str, Any]]:
    """The wire-format question map for a JEV request."""
    return {question.name: question.to_wire() for question in QUESTION_DEFS}


def question_metadata() -> list[dict[str, Any]]:
    """Descriptions for the UI and for the stored decision record."""
    return [
        {
            "name": question.name,
            "type": question.type,
            "instructions": question.instructions,
            "options": question.options(),
            "meaning": question.meaning,
        }
        for question in QUESTION_DEFS
    ]
