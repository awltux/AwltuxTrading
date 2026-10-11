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
        "On that engine's own scale, so it ranks shares within an engine and means "
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
        "A bigger number is safer, and negative means the shares trade above the "
        "estimate. It is a percentage of an estimate, not of a fact -- the valuation "
        "range above it is the honest part, and a large margin of safety built on a "
        "low-confidence valuation is not a bargain, it is an unknown quantity.",
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
    # -------------------------------------------------------------- deep-dive
    Field(
        "verdict",
        "Deep-dive verdict",
        "What a deep-dive concluded about the business: attractive, watch, "
        "unattractive, or insufficient evidence.",
        "'Insufficient evidence' is a stated answer rather than a failure -- it is the "
        "common and correct conclusion for a company nobody has filed much about, and it "
        "is not a judgement on the company. The report behind it reads the annual reports "
        "this system holds, the appraised news and the figures with their quotations, and "
        "it is a judgement: unlike the deterministic valuation beside it, it cannot be "
        "reproduced from the same inputs.",
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
        "The interesting case is the price sitting outside the range; inside it, the "
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
        "the real accounts, which is worth knowing before trusting a ratio from it. "
        "Only the lines that are built from other lines have one -- the subtotals, about "
        "four on each statement. A component line is an input to those sums rather than a "
        "sum of its own, so its Computed cell is empty; hover the dash to see which of the "
        "two it is.",
    ),
    Field(
        "filer_arithmetic",
        "The filer's own arithmetic",
        "The subtotals the filing itself declares, read from the calculation linkbase "
        "published beside it -- the machine-readable version of the additions a person "
        "does by eye when reconciling a 10-K.",
        "It is the stronger check of the two on this page: the table above measures our "
        "figures against our own account of how a balance sheet is built, and this one "
        "measures them against the filer's. So 'not computable' here is this project's "
        "coverage -- the filer declares lines we hold no figure for, named in the row -- "
        "and only a row where every declared line is held and the sum still disagrees is "
        "a contradiction between the filing's arithmetic and the figures we read.",
    ),
    Field(
        "corrected",
        "Corrections",
        "Lines a person has taken out of these accounts, or figures they have put in, "
        "because the automated extraction got them wrong.",
        "Each one changes the stored figures rather than only this page, so the ledger, "
        "the checks and every decision taken from these accounts see the corrected set. "
        "What the extractor had said is kept beside the change, which is what makes it "
        "undoable -- and what says how much of the automation needed a person.",
    ),
    Field(
        "business_profile",
        "What the business is",
        "The latest deep-dive's account of what the company does, how it makes money and "
        "what protects it.",
        "Read out of the stored report rather than copied onto the instrument, so the "
        "sentences a verdict rests on are the ones the report contains and there is one "
        "place to argue with. A company with no finished deep-dive shows nothing here, "
        "which is different from a report that had nothing to say.",
    ),
    Field(
        "levers",
        "Levers",
        "The things that move a business: rates, inflation, currencies, input costs, the "
        "demand it depends on, and the things that change its industry.",
        "Chosen from a fixed list, because the value of the feature is the question asked "
        "across instruments -- what is affected if rates rise -- and that cannot be put to "
        "free text. A record for one instrument gives the direction of the effect when the "
        "lever rises, whether the lever is primary or secondary to that business, and the "
        "reason, which is the part to argue with.",
    ),
    Field(
        "lever_direction",
        "When the lever rises",
        "Which way the business moves if the lever goes up, which is not the same question "
        "as whether the lever is good or bad.",
        "The same direction means the same thing for a bank, a housebuilder and a utility, "
        "which is what lets one page compare them. Cuts both ways is a real answer, not an "
        "undecided one: higher rates widen a bank's margin and worsen its credit losses.",
    ),
    # ------------------------------------------------------------ the counters
    Field(
        "universe_size",
        "In universe",
        "How many instruments are being analysed: seeded once from the full Trading 212 list "
        "at the configured size, and changed by hand since.",
        "The other counters are fractions of this one. Instruments are added from the search "
        "on this page and removed from an instrument's Refresh tab, so this is the size of "
        "the universe rather than a cap on it. A small universe makes every aggregate noisy, "
        "and an empty one explains a blank table.",
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
    # ------------------------------------------------------- the model's answers
    Field(
        "appraisal",
        "Scepticism appraisal",
        "The critical read of one story: who published it and what they stand to gain, how "
        "many independent sources carry it, what it actually claims, what it leaves out, and "
        "whether the wording is doing work the evidence is not.",
        "It exists because every headline is a claim by an interested party, and what "
        "comes out is a weight -- the fraction of the story's sentiment that survives it, "
        "and so how far the story is allowed to move anything -- plus a grade for that "
        "weight. The cheap half (the source registry, the wording scan and the "
        "corroboration count) always runs; the "
        "model's read adds the claims, the omissions and where the underlying fact would be "
        "recorded. A story judged weak is not deleted, hidden or flipped: it keeps its "
        "sentiment and loses most of its influence, which is the difference between "
        "scepticism and censorship.",
    ),
    Field(
        "evidence_grade",
        "Evidence grade",
        "The band the weight falls in: unsupported below 20%, weak to 35%, mixed to 50%, "
        "moderate to 70%, strong above it.",
        "It grades the *evidence*, not the truth of the story: 'unsupported' means nothing "
        "checkable was carrying the claim -- a company blog quoting itself, single-source "
        "coverage, no primary record -- which is a different statement from 'false'. The "
        "ceiling is deliberate: a single-source story from an unrated publisher written in "
        "shock language cannot exceed a low weight however favourable everything else looks.",
    ),
    Field(
        "credibility",
        "Weight",
        "How much of this story's sentiment survives its own appraisal, from 0% to 100%: the "
        "number the sentiment aggregate multiplies by.",
        "Read it as influence rather than as belief. A story at 2% still exists, is still "
        "shown and still counts as coverage; it simply stops moving the sentiment score, "
        "which is what a claim nobody independently carries should do. It is computed in "
        "code from the publisher, the corroboration, the framing and the claim types -- not "
        "asked of the model, which would be judging its own input.",
    ),
    Field(
        "answer_confidence",
        "Confidence",
        "The model's own certainty in the answer beside it, as it reported it.",
        "Self-reported certainty, and not a calibrated probability: a model saying 30% does "
        "not mean it is right 30% of the time. That is exactly why the gate declines these "
        "decisions -- every stored decision is uncalibrated, and the engine refuses to act "
        "below a confidence floor rather than issuing a weak call. A blank means the "
        "question was answered yes/no, which carries no confidence.",
    ),
    Field(
        "answer_distribution",
        "Distribution",
        "The model's probability for each possible answer to that row's question.",
        "Its own estimate, uncalibrated, and it will not always sum to exactly 100%. Read "
        "it as the shape of the model's uncertainty rather than as odds: a flat spread means "
        "it could not tell the options apart, and a blank means the question is numeric or "
        "yes/no rather than a choice between named options.",
    ),
    # -------------------------------------------------------------- the news list
    Field(
        "news_published",
        "Published",
        "When the publisher says the story went out, not when we fetched it.",
        "The two can differ by hours or days -- a feed hands over its backlog on the "
        "first run -- which is why the sort is on this and not on the row's id. A blank "
        "means the feed gave no timestamp at all; such a story sits at the bottom of "
        "every ordering rather than pretending to be from now.",
    ),
    Field(
        "news_headline",
        "Headline",
        "The title the publisher used, stored verbatim and never rewritten.",
        "It is also the doorway: the link opens this app's own page for the story, not "
        "the publisher's, because the article is the *input* to an assessment and may be "
        "paywalled, syndicated or gone by the time anyone clicks. Hover it for the "
        "classifier's reason when there is one.",
    ),
    Field(
        "news_source",
        "Source",
        "Who wrote the story, which is not the feed it arrived through.",
        "The two come apart for almost everything here. Google News supplies the great "
        "majority of the corpus and hands over a *redirect*, so the URL names Google, not "
        "the writer -- the publisher is read from the masthead the headline carries "
        "instead (\"… - Simply Wall Street\"). Where the feed gives the publisher's own "
        "address, that is used. A name in this column may well have no assessment on "
        "file; it is still the publisher, and the story page says whether it is rated. "
        "The feed is named beneath it on this list alone, because this is the page the "
        "Feed control is on and a filter whose value is invisible in every row is one "
        "nobody can check; on the story page and the event lists the column is the "
        "publisher and nothing else.",
    ),
    Field(
        "news_materiality",
        "Materiality",
        "How much the classifier judged the story matters *if it is true*: none, mild, "
        "moderate, material or critical.",
        "It is a judgement about significance, not about truth -- whether the claim is "
        "sound is the credibility weight's job, and the two multiply into priority. "
        "'none' is a stated answer and not a missing one: it is the largest single group "
        "in the corpus. A dash means nothing has classified the story yet.",
    ),
    Field(
        "news_relevance",
        "Relevance",
        "Whether there is a claim about a share price here at all: the story names an "
        "instrument or a sector, and carries a direction.",
        "Deliberately conjunctive, and deliberately not a judgement about quality. A "
        "story that names a company but says nothing about which way it points is not "
        "relevant at any priority, and neither is a market-wide move with nothing to "
        "attach it to. 'Unassessed' is a third state rather than a 'no', and one worth "
        "being able to filter for.",
    ),
    Field(
        "news_priority",
        "Priority",
        "Materiality x credibility x recency, the same score the flash ticker ranks by.",
        "Click the header to order by it: the whole corpus is ranked, not a recent window, "
        "so the top of this sort is genuinely the most important current story the system "
        "holds. Recency is an exponential decay with a three-day half-life, so it falls "
        "away fast and a month-old story cannot outrank today's however severe it was. "
        "Hover a figure for its three components, because a score that cannot be argued "
        "with is not worth trusting.",
    ),
)

BY_KEY: dict[str, Field] = {field.key: field for field in FIELDS}


def _scale_sentence(question) -> str:
    """How to read one question's answer, from the question's own option definitions."""
    criteria = question.criteria
    if question.type == "score" and isinstance(criteria, list):
        levels = "; ".join(
            f"{index} {text.rstrip('.')}" for index, text in enumerate(criteria)
        )
        return f"Rated 0 to {len(criteria) - 1}: {levels}."
    if isinstance(criteria, dict):
        options = "; ".join(
            f"{key.replace('_', ' ')} — {text.rstrip('.')}" for key, text in criteria.items()
        )
        if question.type == "noul":
            return (
                "Answered as the model's probability between 0 and 1 rather than as a "
                "verdict, so 0.03 is a judgement of about 3% — the deterministic rules, when "
                f"they answer it instead, say yes or no: {options}."
            )
        return f"One of: {options}."
    return ""


def _question_fields() -> dict[str, Field]:
    """A tooltip for every question put to the decision model, derived from the question set.

    **Read from `decision/questions.py` rather than written again here**, and this is the one
    entry group that does. That module already states each question's meaning and what every
    level of every option means -- it has to, because `criteria` is what the model is given --
    so a second copy in this file would be a second answer to "what does 3 mean on this row",
    and the two would drift the first time a scale changed.

    The table's whole problem was that a reader saw `short_term_setup 1.0` and had no way to
    know whether 1 was good: the answer is in the scale, and the scale is here.

    **Keyed with an `answer_` prefix, deliberately.** The dashboard already explains
    `margin_of_safety` as *the percentage column on the recommendations table*, which is a
    different thing from the model's 0-4 score for the same question -- one key cannot be
    both, and quietly overwriting the dashboard's text would have been the collision rather
    than the fix.
    """
    from awltux.decision.questions import QUESTION_DEFS

    return {
        f"answer_{question.name}": Field(
            key=f"answer_{question.name}",
            label=question.name.replace("_", " ").title(),
            what=question.meaning,
            reading=_scale_sentence(question),
        )
        for question in QUESTION_DEFS
    }


QUESTION_FIELDS: dict[str, Field] = _question_fields()


def explanation(key: str) -> str:
    """The tooltip text for a field, or an empty string for an unknown one.

    Empty rather than a placeholder: a tooltip reading "no description" is worse than
    no tooltip, and an unknown key here is a template referring to something this file
    has not been told about, which is a real gap rather than a state to display.
    """
    field = BY_KEY.get(key) or QUESTION_FIELDS.get(key)
    if field is None:
        return ""
    return f"{field.what} {field.reading}".strip()


def label(key: str, fallback: str = "") -> str:
    """The field's display label, for a page that would rather read it from here."""
    field = BY_KEY.get(key) or QUESTION_FIELDS.get(key)
    return field.label if field else fallback
