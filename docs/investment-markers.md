# Investment markers: what the evidence actually supports

A research note on how to read company reports, accounts and news to separate a
good business from a bad one — and, just as importantly, on which of the popular
"signals" should not be trusted.

It exists because the obvious failure mode in a project like this is to accumulate
plausible-sounding ratios. Almost every marker below has a paper behind it. Most
of those papers have been challenged, and a large fraction of the findings do not
survive replication. A marker list assembled without that context is a
sophisticated way of losing money.

**How to read the tiers.** Every claim is tagged:

| Tag | Meaning |
|---|---|
| **A** | Replicated out-of-sample, or a mechanical fact about an accounting identity |
| **B** | Published with real evidence, not independently replicated, or weaker than first reported |
| **C** | Plausible, widely used, but the evidence is thin, contested, or from a single paper |
| **D** | Popular and largely unsupported — listed so it is not added by accident |

**And the distinction that matters most.** Three different questions get conflated
in most write-ups, and they have very different answers:

1. **Diagnostic** — does this tell me something true about the business? (Accruals
   really do indicate earnings quality.)
2. **Predictive of trouble** — does it forecast bankruptcy, restatement or fraud?
   (Beneish, Altman, Ohlson: modest accuracy, severe base-rate problems.)
3. **Predictive of returns** — does it make money? (Almost everything here decays,
   and this is where the replication crisis bites hardest.)

This matters because this system is a **long-horizon advisory tool**, not a
trading strategy. Question 1 is the one worth the most here: a marker that
reliably identifies weak earnings quality is valuable even if trading on it earns
nothing, because it changes whether a valuation should be believed at all. Most of
the published alpha decay is irrelevant to that use — and most of the hype is
about the use that does not matter here.

---

## Part 1 — The evidence problem

Any list of markers has to start here, because the base rate of false findings in
this literature is high enough to change how everything else is read.

Hou, Xue and Zhang replicated the **entire** anomalies literature in finance and
accounting — 447 anomaly variables — with microcaps alleviated and value-weighted
returns:

> "286 anomalies (64%) including 95 out of 102 liquidity variables (93%) are
> insignificant at the conventional 5% level. Imposing the cutoff t-value of three
> raises the number of insignificance to 380 (85%). Even for the 161 significant
> anomalies, their magnitudes are often much lower than originally reported."
> — [NBER WP 23394, *Replicating Anomalies*](https://www.nber.org/papers/w23394),
> published as *Review of Financial Studies* 33(5), 2020

Harvey, Sancetta and Zhao go further on the threshold itself:

> "[Our framework] yields a lower bound on valid significance thresholds —
> implying that researchers should employ a t-statistic cutoff of at least 3.0."
> — [NBER WP 34898, *What Threshold Should be Applied to Tests of Factor Models?*](https://www.nber.org/papers/w34898), 2026

**What follows from this for a personal research tool.** Roughly two-thirds of the
markers a diligent person would find by reading the literature do not survive a
careful replication, and five-sixths do not survive a multiple-testing correction.
So the useful posture is not "collect signals" but:

- prefer markers with a **mechanical or causal story** over ones that merely
  correlate in a backtest;
- prefer markers that are **diagnostic of the business** over ones claiming return
  prediction;
- treat any single marker as a **reason to look**, never as a verdict;
- never let a marker that requires an estimate the accounts do not contain drive a
  number in a valuation.

A marker that survives all four is worth having. A marker that fails the last one
is worse than nothing, because it is invisible.

---

## Part 2 — Accounting-quality markers

These are the highest-value group for this product: they are computable from the
accounts alone, they have the clearest causal stories (accruals are an accounting
artefact, not a market prediction), and they answer "should I believe this
profit?" rather than "will this go up?".

### 2.1 Accruals — the strongest case in the whole list

**Tier A as a diagnostic; B as a trading signal.**

*What it is.* Profit is an accrual; cash is a fact. Accruals are the difference
between reported earnings and cash flow from operations, and a large positive
accrual component means reported profit is running ahead of the cash that
supports it.

```
Total accruals (balance-sheet method)
    = (ΔCurrent Assets − ΔCash) − (ΔCurrent Liabilities − ΔShortTermDebt − ΔTaxPayable)
      − Depreciation & Amortisation

Total accruals (cash-flow method, simpler and preferred when available)
    = Net income − Cash flow from operations

Accrual ratio = Total accruals / Average total assets
```

*Why it is credible.* This is an accounting identity, not a discovered pattern. A
company whose profits persistently exceed its operating cash flow is, by
construction, recognising value it has not collected. That is a description of the
business, and it holds regardless of what returns it predicts.

*The honest caveat.* The **return** anomaly attached to it (Sloan 1996) has decayed
substantially. The evidence on its decline is contested — some of it points to
arbitrage and greater scrutiny, some to the anomaly being weaker than reported once
small illiquid names are handled properly — and it is a live literature, not a
settled one. It is cited here as a caution, not as a resolved fact.

*What to do with it*: treat a persistently positive accrual ratio as a reason to
distrust the earnings number, which should then change the confidence on any
valuation built from it. Do **not** treat it as a short signal.

*Caveats that matter.* Working-capital swings make this noisy in isolation: a
growing business legitimately absorbs cash into receivables and inventory. The
signal is the **persistence and direction over three to five years**, not one
year's number. Sector matters enormously — a lease-heavy retailer and a software
firm have structurally different accrual profiles. Compare within sector, and
prefer the cash-flow method because it needs only two figures already extracted.

### 2.2 Cash conversion — the plainest test there is

**Tier A as a diagnostic.**

```
Cash conversion = Cash flow from operations / Net income     (multi-year average)
```

Consistently below 1.0 over several years, in a business that is not growing
working capital sharply, is the single most legible sign that reported profit is
not real. It is already half-implemented here as a one-period check; the useful
version is the **multi-year average and its trend**, because a single year is
easily distorted.

This is the marker to weight most heavily in a long-horizon tool, precisely because
it needs no model, no forecast and no market data. Note that it is also the marker
most often ignored, because a serial acquirer or a capitalised-cost business can
show good conversion while quietly deteriorating underneath.

### 2.3 The bankruptcy and misconduct scores

**Tier B — useful as rankings, badly misused as verdicts.**

These are the most commonly cited formulas in the field and the most commonly
misapplied. They are all *classifiers fitted to a specific historical sample*, and
their published accuracy figures are in-sample or near-out-of-sample on that
sample. Deployed on a different market, a different era, or a different sector mix,
their precision falls — and the base rate dominates: even a test with 90%
sensitivity and 90% specificity for a 1%-incidence event produces mostly false
positives.

**Altman Z-score** (1968, manufacturing firms):
```
Z = 1.2·(Working capital / Total assets)
  + 1.4·(Retained earnings / Total assets)
  + 3.3·(EBIT / Total assets)
  + 0.6·(Market value of equity / Total liabilities)
  + 1.0·(Sales / Total assets)
```
Original cut-offs: below 1.81 = distress zone, above 2.99 = safe. Later variants
exist for private firms (Z'), non-manufacturers (Z'') and emerging markets. For a
modern, service-heavy, lease-heavy listed company the original Z is a poor fit —
it needs market capitalisation, it was fitted to manufacturers, and it predates
IFRS 16 by fifty years.

**Beneish M-score** (1999, eight variables, predicting earnings manipulation):
```
M = −4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
        + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI

DSRI  Days sales in receivables index    GMI  Gross margin index
AQI   Asset quality index                SGI  Sales growth index
DEPI  Depreciation index                 SGAI SG&A index
TATA  Total accruals to total assets     LVGI Leverage index
```
The threshold in common use is −1.78 (higher = more likely manipulator). Its
inputs are all accounting ratios — which is why it is attractive here — but it was
fitted to a small sample of US firms, and the honest reading of the replication
work is that it flags *aggressive accounting*, not fraud. Independent evaluations
are mixed, with several finding the five-variable version performs about as well as
the eight-variable one — a useful signal in itself about how much of the apparatus
is doing real work.

**Ohlson O-score** and **Dechow F-score** are worth knowing: the O-score is a
logistic bankruptcy model, and the Dechow F-score predicts material misstatement
and SEC enforcement actions rather than bankruptcy. The F-score's target is
arguably closer to what an investor wants to avoid, but it is fitted to
enforcement actions, which are rare, US-specific and lag reality by years — so its
practical value here is as a checklist of the *inputs* (accruals, receivables,
inventory, soft assets, sales growth, issuance) rather than as a probability.

**How to use any of these.** As a **rank within a sector**, shown with its inputs,
never as a colour-coded verdict. A company scoring −1.5 on the M-score is not
committing fraud; it is a company whose accounting is worth reading closely. The
distance between those two statements is where most retail use of these tools goes
wrong.

### 2.4 The Piotroski F-score — the best-known quality composite

**Tier B.** Nine binary tests across profitability, leverage/liquidity and
operating efficiency:

```
Profitability   ROA > 0 ; CFO > 0 ; ΔROA > 0 ; CFO > ROA (accruals check)
Leverage        ΔLong-term debt/Assets < 0 ; ΔCurrent ratio > 0 ; No new shares issued
Efficiency      ΔGross margin > 0 ; ΔAsset turnover > 0
```
Its appeal is that it is transparent, additive and needs nothing but accounts. Its
documented performance was on US non-financial firms from 1976, and subsequent work
has found it weaker in later periods and in some international samples — the same
decay pattern as everything else in this section. It remains a reasonable
**checklist**, which is how it should be presented: nine named questions, each of
which a reader can verify against the accounts, rather than an opaque score out of
nine.

### 2.5 Revenue quality and receivables drift

**Tier B.** Receivables growing materially faster than revenue, i.e. days sales
outstanding rising persistently:

```
DSO = (Receivables / Revenue) × days in period
```
A rising DSO means revenue is being recognised faster than it is being collected.
It can be entirely innocent (a large customer negotiating longer terms, a shift in
customer mix) and is often the *first* visible symptom of channel stuffing or
aggressive recognition. The diagnostic value is high; the false-positive rate is
also high, so it belongs in a "look here" list, not a score.

### 2.6 Inventory and margin signals

**Tier B.** Inventory growing faster than sales, and gross margin deteriorating
while revenue grows. Both are the classic warning shapes: unsold goods and
discounting. Both are noisy, both are sector-specific, and both are more useful
when combined with the cash-flow evidence than on their own.

### 2.7 Goodwill and acquisition accounting

**Tier B.** A large goodwill and intangible balance relative to net assets means
the balance sheet is largely made of past acquisition prices rather than
identifiable assets. Two consequences worth flagging: the equity figure is soft,
and any future impairment hits earnings without touching cash. Serial acquirers
with growing goodwill and rising leverage are a recognisable failure pattern —
the acquisitions consume cash, the reported earnings look fine, and the cash
conversion quietly deteriorates until it does not.

### 2.8 Auditor and filing red flags

**Tier B, and unusually cheap to detect.** Auditor resignation or change,
restatement of prior accounts, late filing, a qualified opinion, or going-concern
language in the audit report. These are rare, discrete and unambiguous — they are
statements *by a professional obliged to make them*, which makes them much
stronger evidence than any ratio. Where this system holds the filing text, these
are worth extracting explicitly and surfacing prominently rather than folding into
a score.

---

## Part 3 — Business-quality and capital-allocation markers

The question here is different: not "is the profit real?" but "is this a business
worth owning?"

### 3.1 Returns on capital against the cost of capital

**Tier A as an economic identity, B as a measured persistence claim.**

A business creates value only when the return on the capital it employs exceeds
what that capital costs. Below that line, growth *destroys* value — the faster it
grows, the worse. This is arithmetic, not a finding:

```
Economic profit = Invested capital × (ROIC − WACC)
ROIC            = NOPAT / Invested capital
Invested capital = Total debt + Total equity − Cash  (or operating approach:
                   net PP&E + net working capital + other operating assets)
```

*The persistence question.* How long an above-cost return lasts is the empirical
question. The most concrete published numbers found for this note are practitioner
rather than academic, and are labelled as such: TD Epoch, analysing **every company
in the MSCI World Index every year since 1990** in ROIC quintiles, reports that a
company in the top quintile had a **75% chance of staying there the next year** and
only a 2% chance of falling to the bottom quintile; bottom-quintile companies had a
62% chance of staying in the bottom and a 1% chance of reaching the top. — [TD
Epoch, *A Conversation With Steven Bleiberg*](https://www.td.com/us/en/asset-management/investment-management/perspectives)
(the interview text was extracted and read directly; it is an asset manager's own
analysis, **not peer-reviewed**, and the exact methodology is not published).

Read that as a direction rather than a constant: returns on capital are
substantially persistent year to year, and the extremes are stickier than the
middle. Treat any specific half-life quoted without its sample as marketing.

*Why it matters here.* ROIC is already partly present as ROCE. What is missing is
(i) a cost-of-capital comparison, so the number has a reference point, and
(ii) the **level and stability over time** rather than one year. A company earning
25% on capital for eight years is a different proposition from one that earned 25%
once — and the persistence evidence above is what makes that statement more than a
platitude.

*Caveat that bites hardest.* ROIC is sensitive to how invested capital is defined
(goodwill included or not, leases capitalised or not, cash netted or not). Any
implementation must state its definition, because a 10-point ROIC difference
between two analysts is usually a definitional difference, not a disagreement about
the business. For low-return or loss-making companies ROIC is close to meaningless
and should be suppressed rather than shown.

### 3.1a Gross profitability — the quality measure with the least friction

**Tier B, and unusually strong for how easy it is to compute.**

Novy-Marx showed that **gross profits to total assets** predicts the cross-section
of returns about as well as book-to-market, that profitable firms earn higher
average returns despite being larger and having lower book-to-market, and that
controlling for profitability substantially improves value strategies — "especially
among the largest, most liquid stocks". He reports an annualised Sharpe ratio of
0.90 for the profitability strategy against 0.32 for the value strategy it is
compared with. — [Novy-Marx, *The Other Side of Value: Good Growth and the Gross
Profitability Premium*, NBER WP 15940](https://www.nber.org/papers/w15940)
(extracted text read directly).

```
Gross profitability = (Revenue − Cost of goods sold) / Total assets
```

**Why this deserves a place in the shortlist despite being a return-prediction
claim.** It uses *gross* profit deliberately: it sits above the line where
management discretion over SG&A, R&D capitalisation, restructuring and one-offs is
greatest. That makes it harder to manipulate than net income, and it makes it
computable from two figures this system already extracts plus total assets. Where
ROIC needs a capital definition and a WACC estimate — several ways to be wrong —
gross profitability needs neither.

*Honest caveats.* It is a **return** claim, and therefore subject to the decay
discussed in Part 1; it is defined on US data; and gross profitability is
structurally different between, say, a software firm and a distributor, so it is
only meaningful **within** an industry. Use it as a cross-sectional ranking inside
a sector, not as a threshold.

### 3.2 Margin stability and durability

**Tier B.** Stable or rising gross margins over a full cycle are the most
quantifiable evidence of pricing power. Volatile margins suggest a commodity
business; steadily declining margins suggest competition winning. The trend over
5–10 years is more informative than the level, and the level is only meaningful
against close peers.

### 3.3 Reinvestment and the growth/value-creation split

**Tier B.** Growth is only worth paying for when incremental returns are
attractive:
```
Value created ≈ (ROIC − WACC) × Reinvestment
Reinvestment rate = (Capex + ΔWorking capital − D&A) / NOPAT
```
A company with high ROIC and a long reinvestment runway compounds. A company with
low ROIC growing fast consumes capital. A company with high ROIC and no
reinvestment runway should be returning cash — and what it does with that cash
(3.4) then matters more than its growth.

### 3.4 Capital allocation

**Tier B, with more heat than light in the popular literature.**

- **Buybacks.** The mechanical fact is that a buyback at a price below intrinsic
  value transfers value to remaining holders, and above it transfers value away.
  Whether managements are good at this timing is contested; the evidence is mixed
  and the effect is modest. What is unambiguous and worth flagging is buybacks
  that merely **offset dilution** — gross repurchase with a flat or rising share
  count means the cash went to employees, not shareholders. Net share count change
  is the honest measure, and this system already computes it.
- **Dividends.** A payout ratio above earnings, or a dividend paid out of
  borrowing, is a clear warning. A cut is not automatically bad — it can be the
  honest response — but a cut after a period of increases is informative. Dividend
  yield as a *quality* signal is weak and is a classic value-trap doorway.
- **M&A.** The acquirer-underperformance finding is old, widely replicated and
  still true on average: acquisitions destroy acquirer value more often than they
  create it, with cash-and-goodwill-heavy deals and diversifying deals faring
  worst. Treat acquisition announcements as a reason to look harder at the price
  paid and the strategic logic, not as automatic bad news.

### 3.5 Earnings stability and cyclicality

**Tier B.** Volatile earnings are lower quality than stable ones, all else equal —
they make forecasting unreliable and valuation inputs unstable. But the specific
trap is mistaking a cyclical peak for quality: peak margins, peak ROIC and a low
multiple on peak earnings is the classic way a cyclical looks like a bargain
immediately before it de-rates. Any quality assessment must ask where in the cycle
the evidence was measured.

---

## Part 4 — Governance and ownership

**Tier C overall** — real effects, but small, hard to measure, and heavily
confounded. Included because the downside cases are catastrophic and cheap to
flag, not because they are reliable predictors.

| Marker | Evidence | Note |
|---|---|---|
| Restatements, enforcement actions | **B** | Rare, discrete, unambiguous. Treat as a hard flag. |
| Related-party transactions | **C** | The mechanism behind many small-cap disasters. Needs the notes, not the ratios. |
| Controlling shareholder / low free float | **C** | Alignment cuts both ways; minority expropriation is real. |
| Dual-class structures | **C** | Evidence is mixed and mostly about specific governance outcomes. |
| Insider **buying** | **C** | The most-cited insider signal; open-market purchases are informative, sales are mostly noise (diversification, tax, pre-planned). |
| Insider ownership level | **C** | Non-linear; both very low and very high can be problems. |
| Auditor tenure and non-audit fees | **C** | Long tenure and high non-audit fees are the conventional concerns; evidence is weaker than the convention. |
| Pay structure and incentives | **C** | Hard to reduce to data; metric-gaming risk is real but not mechanical. |

**The Carillion lesson, as a concrete UK anchor:** the FRC found misconduct in
financial reporting by senior finance executives ahead of the collapse, and the
regulator's own framing was that this was not a single bad actor but a failure of
culture, internal controls and challenge. — [Chartered Governance Institute, on the
FRC's Carillion sanctions](https://www.cgi.org.uk/about-us/cgi-news/2026/carillion-sanctions-show-how-governance-failures-can-have-lasting-personal-consequences/).
The practical implication is that governance failure tends to show up **first in
the numbers** (cash conversion, contract accounting, receivables) — which is an
argument for weighting the accounting markers above the governance metadata.

**And the single best illustration of this note's central distinction.** Bebchuk,
Cohen and Wang found that the relation between governance indices and *returns*
held from 1991 to 1999 but was **absent from 2000 to 2008** — while the relation
between governance and *operating performance and firm value* persisted
throughout. — Bebchuk, Cohen & Wang, "Learning and the Disappearing Association
between Governance and Returns", *Journal of Financial Economics*, 2013 (reported
to this note by a research subagent, verified against Crossref author metadata;
not independently fetched here).

Governance still told you something true about the companies. It stopped telling
you what the market would pay. That is the whole argument for grading markers by
*which question they answer*, and it is why this system should carry governance as
a description of a business rather than as a reason to expect a return.

---

## Part 5 — Language and text markers

The system already reads filing text and news. What does the evidence say is worth
extracting from it?

### 5.1 Use a finance-specific dictionary, not a general one

**Tier A for the finding.** Loughran and McDonald showed that general-purpose
sentiment dictionaries mislabel financial text badly — words that read as negative
in ordinary English ("liability", "tax", "cost", "risk", "foreign") are neutral in
a 10-K. They published a finance-specific lexicon of 4,150 words in six categories:
**negative, positive, litigious, uncertainty, constraining, superfluous**. — [Loughran
& McDonald (2011), *Journal of Finance* 66:35–65](https://doi.org/10.1111/j.1540-6261.2010.01625.x),
dictionary available from [Notre Dame SRAF](https://sraf.nd.edu/loughranmcdonald-master-dictionary/).

The two categories most relevant to a red-flag system are **uncertainty** and
**litigious** — neither is captured by a positive/negative sentiment score, and
both are closer to what an investor wants to detect than tone is. This is a direct,
concrete improvement available to this codebase: the current news pipeline scores
direction, but nothing measures uncertainty or litigious language in filings.

**Domain-specific models beat general ones, consistently.** FinBERT (Araci, 2019)
found that "general-purpose models are not effective enough because of the
specialized language used in a financial context", and that pre-training on
financial text improved every measured metric on two financial sentiment datasets.
— [arXiv:1908.10063](https://arxiv.org/abs/1908.10063), abstract read directly.
That is the same lesson as the LM dictionary reached a different way, and it applies
to the model this system already uses: a general model asked to read a 10-K is
working outside its training distribution. That is a reason to keep extraction
strict and cited, not a reason to trust its judgement more.

### 5.2 Readability and obfuscation

**Tier C.** The finding that less readable annual reports are associated with worse
earnings persistence and worse subsequent performance is one of the most-cited
results in the area (Li, 2008, *Journal of Accounting and Economics*, on the Fog
Index). It is plausible, it has a causal story (managers obscure bad news), and it
has been challenged — including work arguing the effect is weaker or partly a proxy
for complexity rather than intent. Treat length and complexity as a **reason to
read more carefully**, not as a score.

### 5.3 Tone, hedging and boilerplate

**Tier C.** Management tone in MD&A and earnings calls, hedging language, evasion
in Q&A, and year-over-year similarity of risk disclosures have all been studied and
all show *some* relation to outcomes. Effect sizes are small, the measures are
hard to reproduce, and the data-mining risk is high. The defensible use is
qualitative: surface the extracted passages and let a human judge, rather than
converting them into a number that then feeds a decision.

**One finding in this area is strong enough to act on, and it is not a sentiment
score.** Guidance is systematically biased: in a survey of managers, **more than
60% said their private expectation was *above* the guidance midpoint they
published, and fewer than 7% said it was below** — so the midpoint is not the
expectation. This was reported to this note by a research pass over Call, Hribar,
Skinner & Volant (*Journal of Accounting and Economics*, 2024); it is a survey
result rather than a return prediction, which is why it is usable, and the paper
should be read before the figure is shown to a reader. (Source: research subagent
interim report; not independently fetched here.)

*The practical consequence:* when a filing extraction captures guidance, store the
**midpoint as the company's published figure** and say so — never relabel it as
"management's expectation".

### 5.3a Vocal and behavioural markers are out of scope, and some are discredited

**Tier D — do not build.** A popular literature claims that voice pitch, vocal
dissonance and similar paralinguistic markers in earnings calls reveal deception.
Three reasons this system should not go near it:

1. Every such marker needs **call audio**, which this pipeline does not have and
   cannot get from the free feeds it uses.
2. The two headline results rest on **proprietary Nemesysco LVA** software, whose
   scientific basis was the subject of a published critique (Lacerda, 2012)
   describing it as void.
3. Even the softer text-based version is weak: roughly **11% of analyst questions
   receive non-answers** (Gow, Larcker & Zakolyukina, *Journal of Accounting
   Research*, 2021), and the reading that non-answers signal bad-news suppression
   has been directly contested. Not a basis for a bearish signal on its own.

(Reported by the research subagent with the critiques attached; not independently
fetched here.)

### 5.4 The "decorate the document" question

What is genuinely worth attaching to a filing, in priority order:

1. **Cited figures** — every number with its quoted span and location (already
   implemented here; this is the foundation and it is right).
2. **Accounting-policy changes and estimate changes** — a change in revenue
   recognition, depreciation life, or provisioning assumptions is a discrete,
   checkable event with a clear direction of travel. This is under-exploited.
3. **Going-concern and qualification language** — rare, unambiguous, high value.
4. **Litigious and uncertainty language** — LM categories, cheap, directional.
5. **Related-party and non-recurring items** — needs note-level reading.
6. **Readability and boilerplate drift** — lowest priority, weakest evidence.

Note the ordering principle: **discrete, checkable events first; continuous
text scores last.** A policy change either happened or did not. A readability
score is an opinion with a number attached.

**A practical warning about the input itself.** The "decorate the document" step
fails at the extraction layer before it fails at the analysis layer, and this is
measurable rather than hypothetical: the FinSBD shared task on sentence-boundary
detection in financial PDFs found an off-the-shelf parser (spaCy) scoring a macro-F1
of **0.208** on English prospectuses, with the best system reaching 0.937 — and the
hard cases were lists, tables and page furniture rather than prose. — [FinSBD-2020,
*The 2nd Shared Task on Sentence Boundary Detection in Unstructured Text in the
Financial Domain*](https://aclanthology.org/2020.finnlp-1.8/) (extracted text read
directly; the anthology record was checked).

The design consequence is that **a structured feed beats a PDF** every time. This
system is right to prefer XBRL and iXBRL over parsing annual-report PDFs, and any
future work that adds PDF reading is adding a measured 20–90% error surface on the
text segmentation before any analysis begins. That is an argument for keeping the
figures on the structured path and using PDF text only for the qualitative items
(3–5 above), where a mis-split sentence degrades a human read rather than a number.

---

## Part 6 — News and media

The scepticism layer already built into this system is well-supported by the
literature, and the research says something more uncomfortable than expected.

**Coverage follows price at least as much as price follows coverage.** This is the
central methodological problem in the media-sentiment literature: journalists write
about what has already moved. Much of the apparent predictive power of news
sentiment is momentum, liquidity or attention in disguise. Any news signal must
therefore be validated with the price move controlled for — and a system that
weights news heavily without that control is likely measuring yesterday's return
and calling it sentiment.

**Asymmetry is the more robust finding.** Negative news appears to carry more
information than positive news, and the effect of sentiment appears stronger in
small, illiquid, low-attention stocks — which is exactly where this system's data
is weakest and its models are least reliable. That combination argues for
restraint, not for a bigger news weight.

**What this means here.** The existing design — news modulates sentiment, sentiment
is one component with a modest weight, and weak stories are damped rather than
deleted — is the right shape. The research does not support increasing the weight
of news relative to accounting evidence, and it does support the corroboration and
source-quality work already done.

---

## Part 7 — UK-specific notes

Half this universe is LSE-listed and the data situation is materially different.

- **Reporting frequency.** No quarterly reporting for most UK issuers, so
  interims and annuals carry more weight and the time between observations is
  longer. Point-in-time signals decay differently.
- **Accounting framework.** FRS 102 and IFRS differ from US GAAP on leases,
  development-cost capitalisation, and goodwill amortisation. A Beneish or Altman
  score calibrated on US GAAP data is being applied to different accounting — this
  is a first-order problem, not a technicality.
- **Small-cap and AIM disclosure.** Practitioner analysis of LSE and AIM
  announcements identifies a recognisable **pre-fundraising sequence**: repeated
  cash-preservation and cost-reduction language, contract delays and revenue
  deferral, softening guidance across consecutive statements, declining cash
  balances, and acquisition activity without a stated funding source. — [Investegate,
  *Early Warning Signals of Fundraisings*](https://www.investegate.co.uk/index.php/content/early-warning-signals-of-fundraisings).
  **This is a practitioner article, not peer-reviewed research**; treat it as a
  source of hypotheses (and note that dilution is a real, mechanical loss to a
  holder) rather than as evidence. It is testable against this system's own RNS and
  price history.
- **Coverage quality.** UK smaller companies have far less analyst coverage and far
  more promotional commentary. The source-reliability work matters more here than
  it does for US large caps.

---

## Part 8 — What this system already has, and the gaps

**Already computed** (`analysis/fundamental.py`, `analysis/valuation.py`): revenue
CAGR, margin levels and trend, ROE, ROCE, net debt/EBITDA, interest cover, debt/equity,
current ratio, FCF margin, one-period cash conversion, payout ratio, share-count
growth, and simple threshold red flags for each.

**The honest assessment of what exists:** the *levels* are covered and the
*quality* is not. Almost every threshold in `_flag_risks` is conventional rather
than evidence-based, and several are one-period checks where the evidence calls for
multi-year. Specifically missing:

| Gap | Marker | Tier | Cost |
|---|---|---|---|
| Earnings quality | Multi-year accrual ratio (cash-flow method) | A/B | Low |
| Earnings quality | Cash conversion average and trend, not one year | A | Low |
| Distress | Altman Z'' (non-manufacturer variant) | B | Low |
| Manipulation | Beneish M-score, 5-variable variant, sector-ranked | B | Medium |
| Quality | Piotroski F-score as nine named checks | B | Low |
| Revenue quality | DSO and its trend vs revenue growth | B | Low |
| Balance sheet | Goodwill + intangibles as % of assets; serial-acquirer flag | B | Low |
| Return on capital | ROIC with a stated definition, vs an estimated WACC | A/B | Medium |
| Growth quality | Reinvestment rate and incremental ROIC | B | Medium |
| Cash returns | Net buybacks vs gross; buybacks offsetting dilution | B | Low |
| Filing events | Auditor change, restatement, going-concern, policy change | B | Medium |
| Filing language | LM uncertainty and litigious counts | C | Low |
| UK specific | Pre-fundraising language and cash-runway sequence | C | Medium |

**Data prerequisites.** Several of these need figures the extractor does not yet
request: receivables, inventory, payables, depreciation and amortisation,
stock-based compensation, goodwill, intangibles, short-term debt, EBIT, pretax
income, tax expense, R&D, and lease liabilities. `CANONICAL_METRICS` in
`llm/extractors.py` is the gate — nothing outside it survives extraction, so this
list is the first dependency for most of the accounting markers.

---

## Part 9 — Recommended shortlist

Ordered by evidence strength per unit of implementation cost, for a long-horizon
tool with annual/interim accounts and no paid data.

1. **Multi-year cash conversion and accrual ratio.** The strongest diagnostic in
   the list, both computable from two figures already extracted, both describing
   the business rather than predicting the market. Add the trend, and compare
   within sector.
2. **Piotroski's nine checks, displayed as nine checks.** Not a score out of nine —
   the individual answers are the value, and they are all verifiable against the
   accounts by the reader.
3. **Altman Z'' and Beneish M (5-variable), as within-sector rankings with their
   inputs shown.** Never colour-coded, never a verdict, always with the caveat that
   a flag means "read this" and not "this is fraud".
4. **Receivables and inventory drift relative to revenue.** Cheap, diagnosis-first,
   and the earliest visible symptom of the failure mode that matters.
5. **Filing events: auditor change, restatement, going-concern, policy change.**
   Rare, discrete, unambiguous and cheap once the text is already being read.
6. **ROIC against an explicit WACC, with the definition stated.** The economic
   question the system currently cannot answer: is this business creating value at
   all?
6a. **Gross profitability (gross profits / total assets), ranked within sector.**
   The cheapest quality measure with real evidence behind it — two figures already
   extracted plus total assets, and no capital definition or WACC estimate to get
   wrong. Ranked, never thresholded.
7. **Goodwill/intangibles intensity and a serial-acquirer flag.** Cheap, and it
   changes how much the equity figure should be trusted.
8. **LM litigious and uncertainty counts.** Low cost once a finance-specific
   lexicon is in place, and it measures something the current sentiment model does
   not.

**Explicitly not recommended.** Dividend yield as a quality signal; insider selling
as a signal; readability scores feeding a decision; **vocal and paralinguistic
"deception" markers** (no audio, and the headline results rest on discredited
software); Q&A evasion as a standalone bearish signal (weak and contested); and any
composite that hides its inputs or is used as a trade trigger rather than as
evidence attached to a decision.

---

## Appendix — verified sources used

- Hou, Xue & Zhang, *Replicating Anomalies*, NBER WP 23394 / RFS 33(5) —
  https://www.nber.org/papers/w23394
- Harvey, Sancetta & Zhao, *What Threshold Should be Applied to Tests of Factor
  Models?*, NBER WP 34898 — https://www.nber.org/papers/w34898
- Loughran & McDonald, *When Is a Liability Not a Liability?*, Journal of Finance
  66:35–65 — https://doi.org/10.1111/j.1540-6261.2010.01625.x
- Loughran-McDonald Master Dictionary, Notre Dame SRAF —
  https://sraf.nd.edu/loughranmcdonald-master-dictionary/
- Chartered Governance Institute on the FRC's Carillion sanctions —
  https://www.cgi.org.uk/about-us/cgi-news/2026/carillion-sanctions-show-how-governance-failures-can-have-lasting-personal-consequences/
- Investegate, *Early Warning Signals of Fundraisings* (practitioner, not
  peer-reviewed) —
  https://www.investegate.co.uk/index.php/content/early-warning-signals-of-fundraisings
- Novy-Marx, *The Other Side of Value: Good Growth and the Gross Profitability
  Premium*, NBER WP 15940 — https://www.nber.org/papers/w15940
- TD Epoch, *A Conversation With Steven Bleiberg* on ROIC persistence
  (practitioner, not peer-reviewed, methodology unpublished)
- Au, Chong, Ait Azzi & Valsamou-Stanislawski, *FinSBD-2020* —
  https://aclanthology.org/2020.finnlp-1.8/
- Araci, *FinBERT: Financial Sentiment Analysis with Pre-trained Language Models*,
  2019 — https://arxiv.org/abs/1908.10063

**Reported by research subagents and not independently fetched here.** Bebchuk,
Cohen & Wang (JFE 2013) on governance and returns; Call, Hribar, Skinner & Volant
(JAE 2024) on guidance midpoints; Gow, Larcker & Zakolyukina (JAR 2021) on Q&A
non-answers and the Bamber & Nappert (CAR 2025) reply; Lacerda (2012) on Nemesysco
LVA; the Loughran & McDonald dictionary provenance.

**Sources that could not be verified here.** Several foundational papers sit behind
publisher paywalls and were not independently confirmed for this note — notably
Sloan (1996) on accruals, Altman (1968), Beneish (1999), Ohlson (1980), Piotroski
(2000), Dechow et al. on the F-score, Li (2008) on readability, and the
post-publication-decay and accruals-demise literature. Their formulas and claims
are reported above as the standard statements of those models. **Effect sizes
attributed to them in the accounting-marker sections should be treated as
unverified until a source is fetched.** This is exactly the discipline the rest of
the system applies to figures, and it applies to this document too.
