# AwltuxTrading

A self-hosted background service that continuously assesses whether the shares
tradeable on **Trading 212** are under- or over-valued, tracks market sentiment
towards each stock and sector, and shows the result on a live dashboard with a
news flash ticker.

Every decision it produces is **explained and reproducible**: the inputs, the
model that answered, its probabilities, and the rule that permitted (or blocked)
the call are all written to an append-only ledger.

> **Advisory only.** AwltuxTrading does not place live orders. It is not
> financial advice. See [Safety](#safety).

---

## How it works

Three things are deliberately kept apart, because they are good at different
things and conflating them is how a plausible-but-wrong number reaches a user:

```
INGEST      Trading 212 · Yahoo Finance · SEC EDGAR · Companies House · RSS/Finnhub/Marketaux/GDELT
   │
ANALYSE     deterministic Python — every number in the system is produced here
   │        DCF · EPV · residual income · peer multiples · DDM · Graham
   │
COMPRESS    DeepSeek reads filings and headlines, returns cited structured facts
   │
DECIDE      JEV answers typed questions (falling back to DeepSeek, then to rules)
   │
GATE        deterministic risk rules decide whether the call is actionable
   │
LEDGER      immutable record: state hash, questions, answers, model id, gate verdict
```

**The division of labour is enforced, not just intended.** DeepSeek never
supplies a number that reaches the valuation — it extracts figures *with a quoted
source span*, and anything uncited is discarded. JEV sets the verdict but never
computes. Code owns all arithmetic, thresholds and permissions.

### Why it works this way

| Constraint | Consequence |
|---|---|
| JEV caps `state` at ~32k tokens and cannot read a 200-page report | DeepSeek compresses filings into a compact, cited state first |
| Trading 212 has **no quote or candle endpoint** | Prices come from Yahoo Finance, through `yfinance` |
| Free tiers are licensed for personal, non-commercial use | Local storage, source attribution, no redistribution |
| A language model's "probability" is not a calibrated frequency | Fallback decisions are labelled and held to a stricter confidence floor |

---

## Quick start

```bash
git clone <this repo> && cd AwltuxTrading
cp .env.example .env          # then fill in your keys (all optional to start)
docker compose up -d
open http://localhost:8080
```

The dashboard is bound to `127.0.0.1` only. It shows your holdings and has no
authentication, so it must not be exposed on a network.

### Updating a running deployment

```bash
docker compose exec awltux awltux quiet --timeout 1800   # wait for in-flight jobs
docker compose up -d --build                             # rebuild AND recreate
```

**Quiet it first.** Rebuilding sends the container SIGTERM, and on SIGTERM the app
stops scheduling and waits — but only briefly, because the container is going whether
the wait finishes or not. A job that outruns that window is killed part-way through
writing its batch; the run row is closed as *interrupted* on the next start, which is
honest but is still work lost and a database left mid-transaction. `awltux quiet`
asks *before* the rebuild instead: it pauses scheduling and waits for as long as it
takes. Exit code `3` means a job outran the timeout and it is **not** safe to rebuild
yet. `awltux unquiet` resumes, if you decide not to upgrade after all; the state is
also cleared by any restart.

**`docker build` on its own does not update a running container, and neither does
`docker compose up -d` without `--build`** — the latter reuses whatever image is
already tagged locally. Rebuilding four times and restarting nothing leaves the
dashboard on old code while every check against the *image* passes. That is not
hypothetical: it produced two separate bug investigations here, one of which was
recorded as a template error that had in fact been fixed a version earlier.

To tell what you are actually running, open **Info** in the navigation: it reports
the commit the *running process* was built from, and whether the tree was clean
when it was captured. If the page is not there, the deployment is older than the
page — which is itself the answer.

### It works with no API keys at all

With an empty `.env` the app still runs: it ingests whatever is available without
credentials (Yahoo prices, SEC filings, RSS headlines) and makes decisions using
the **deterministic offline engine**, clearly labelled as such. Add keys to
improve it:

| Key | Enables | Notes |
|---|---|---|
| `AWLTUX_T212_API_KEY` / `_SECRET` | The instrument universe, your holdings, paper trading | Required for universe selection |
| `AWLTUX_DEEPSEEK_API_KEY` | Filing extraction, report summaries, news classification, fallback decisions | Strongly recommended |
| `AWLTUX_TYPESAFE_API_KEY` | **JEV**, the calibrated decision engine | Gated early access |
| `AWLTUX_COMPANIES_HOUSE_API_KEY` | UK company filings and accounts | Free |
| `AWLTUX_FINNHUB_API_KEY` / `AWLTUX_MARKETAUX_API_KEY` | Real-time US news, sentiment-scored news | Free tiers |
| `FAL_KEY` | Embeddings, so several outlets reporting one event show as one entry | The `openai/*` embedding models are refused by this route; see `news.embeddings.model` |
| `FAL_ADMIN_KEY` | Reading the fal account balance for the credit banner | Optional, and used only for that call — a model key is refused with a 403 |

`AWLTUX_SEC_USER_AGENT` must contain a **real contact address** — the SEC rejects
requests without one with an HTTP 403.

---

## The decision engines

The engines are interchangeable because they answer the same typed questions.
Which one answered is recorded on every decision and shown in the UI.

| Engine | Type | Probabilities | When it is used |
|---|---|---|---|
| **JEV** (`typesafe.ai`) | Calibrated decision model | Calibrated | Primary, when a key is set |
| **DeepSeek** | Language model emulating the same contract | Self-reported, **uncalibrated** | Fallback when JEV is unavailable |
| **Offline** | Deterministic threshold rules | None reported | No keys, replay, and as a control |

Confidence floors differ **per engine**, because three different quantities are
called "confidence" here and treating them as one number would either overstate
the rule engine or hobble it:

| Engine | Floor | Why |
|---|---|---|
| JEV | `0.70` | Calibrated probabilities — the ordinary bar applies |
| DeepSeek | `0.80` | Self-reported certainty, **not** calibrated — held to a stricter bar |
| Offline | `0.55` | Reports no probability at all; its number describes *evidence quality*, so it is judged on its own scale |

That last distinction is not pedantry. The rule engine's evidence score tops out
at 0.65, so judging it against the 0.80 fallback floor made the no-keys mode
silently incapable of ever suggesting anything — a failure that no test of the
gate alone would have caught, because a hand-built response always supplies a
confidence.

A fallback decision is never presented as though JEV produced it.

### The questions asked

Asked together in a single fan-out request ([TypeSafe's recommended pattern][fanout]),
because many atomic questions are cheaper and more inspectable than one broad one:

`valuation_verdict` · `margin_of_safety` · `business_quality` ·
`balance_sheet_risk` · `earnings_trend` · `news_materiality` ·
`sentiment_regime` · `going_concern` · `dilution_risk` ·
`accounting_red_flags` · **`long_term_action`** · **`short_term_action`** ·
**`short_term_setup`** · **`short_term_drawdown_risk`** · **`horizon_fit`**

The answers are blended into a composite score used to sort the dashboard.
The deterministic margin of safety carries the largest weight in the long-term
score, so the ranking is anchored to arithmetic rather than judgement. When an
action contradicts its own composite, the decision is **flagged as a conflict**
and shown — not silently averaged away.

[fanout]: https://docs.typesafe.ai/patterns/fan-out

---

## Two horizons, not one

The dashboard gives **two independent verdicts**, because they answer different
questions from different evidence and can legitimately disagree:

| | Long term | Short term |
|---|---|---|
| **Horizon** | 12–36 months | 5–20 trading days |
| **Driven by** | Valuation, business quality, balance sheet | Trend, momentum, volume, news direction |
| **Composite weights** | Margin of safety dominant (0.34) | Tactical setup dominant (0.35) |
| **Judged over** | 30 / 90 / 180 days | 5 / 10 / 20 days |
| **Requires** | A fresh valuation | A fresh price and a measured setup |

They are scored with **different weights** and gated with **different
requirements**, and that is the point. A single collapsed verdict would hide the
case a reader most wants to see:

- cheap for years but tactically broken — `long_term: BUY`, `short_term: AVOID`
- nothing for years but a clean setup now — `long_term: REDUCE`, `short_term: BUY`

The `horizon_fit` answer states plainly which horizon the evidence actually
supports (`long_term`, `short_term`, `both`, `neither`), independently of either
call. If the two used the same weights they would produce the same ranking and the
second would be decoration; tests assert they diverge in both directions.

### Short term is a swing, not day trading

**Day trading is deliberately out of scope**, and the app says so rather than
implying otherwise. There is no supported intraday path because the data cannot
carry one:

- Trading 212's public API has **no quote endpoint at all** — verified against the
  full OpenAPI bundle.
- The free price feed is **delayed ~15 minutes**. Trading intraday on a
  15-minute-stale price is worse than not trading.
- The maths is built on **daily bars**, which is the resolution the momentum and
  valuation models assume.

"Short term" therefore means a swing horizon of days to weeks on daily bars. A
true intraday engine needs a licensed real-time feed; the tactical layer is
structured so one could be added behind the same verdict contract.

## The risk gate

The gate is a separate layer from the decision, so a model cannot widen its own
mandate. It checks, in order, and **names the single binding rule** when it
refuses:

1. engine trust meets the configured minimum
2. price freshness — plus a fresh valuation **only on the long-term horizon**
3. confidence clears the floor for that engine
4. the chosen option carries enough probability mass
5. the action is actionable at all — `HOLD` and `AVOID` never execute
6. **a measured tactical setup, only on the short-term horizon**
7. liquidity is known and sufficient
8. portfolio limits: max positions, per-name and per-sector concentration

Two asymmetries are deliberate. A tactical call does **not** need a fresh
discounted cash flow — refusing it for that would refuse it for an irrelevant
reason — but it does need actual momentum evidence, because a tactical call
resting on nothing but an opinion is not a tactical call. And `HOLD`/`AVOID` are
recorded as decisions but never become trade suggestions.

---

## News is a claim, not a measurement

Financial news is written by organisations with interests, to be read by people in
a hurry. Most of it is honest and still not evidence. So a headline is never fed
straight into sentiment: it is **appraised** first, and the appraisal decides how
much weight it may carry.

**Who is speaking.** Every item is resolved to a publisher, and the publisher to a
curated assessment: what kind of document it is (the regulatory record, the company
speaking about itself, a wire, an outlet with its own reporting, an aggregator, a
press-release distributor, opinion), its track record for financial accuracy, and
its **independence** — freedom from a stake in the story. Bias and ownership are
recorded with the basis for each judgement, because a judgement with no stated
basis is indistinguishable from a prejudice. The table is dated; unknown publishers
are *unrated*, which is not the same as disreputable.

Resolving that publisher is not the same as reading `news_item.source`, which is the
*feed*. Google News supplies the great majority of the corpus and hands over a redirect
URL, so the URL names Google rather than the writer; the publisher is read from the
masthead the headline carries ("… - Simply Wall Street") instead, and from the URL where
the feed stores the publisher's own address. Measured on 2026-10-09: 26,591 of the 27,895
stories then held carried a Google News URL, and **6,700 of the 6,974 appraisals recorded
their source as "Google News"** — the scepticism layer was grading claims against the pipe
for 96% of the corpus. Re-rating them (`awltux news-publishers`, no model calls) named
1,175 distinct publishers across 28,174 stories and left 2,423 appraisals on a genuinely
aggregator source.

The registry is smaller than the corpus: of those 1,175 named publishers it can rate 54,
so most appraisals now say "unrated — no assessment on file", which is the honest state
and not a failure of the resolution.

Self-interest does not push credibility one way. A company announcing good news
about itself is discounted hard; the same company announcing a profit warning is
not, because nobody says that against their own interest casually.

**How it is written.** A pattern scan detects the recognisable manipulation
techniques — appeal to fear, shock language, manufactured urgency, unnamed
authority, anonymous sourcing, absolute claims, loaded language, bandwagon
appeals, "analysts say" consensus, clickbait construction — and records the words
that triggered each one. This runs in code, not in a prompt, for a specific reason:
a model asked "is this manipulative?" is judging its own input, and a confidently
written article reads as confidently written. The scan cannot be talked out of it.
It also notes alarming claims that are hedged into unfalsifiability, percentages
with no base, and headlines more extreme than the text beneath them.

**How many sources.** "Multiple outlets are reporting it" is the most common
defence of a story and one of the weakest. A wire story appears on dozens of
domains. Carriers are counted separately from **origins**, near-identical
headlines collapse, and wire credits in the text are followed. Twelve domains
carrying one Reuters story is one source, and the UI says so.

**What it actually claims.** For stories worth the cost, the model restates each
claim without the article's framing, tags its type and attribution, and names
where the underlying fact would be *recorded* — the filing, the register, the
court docket, the statistical agency. Each claim must quote a verbatim span from
the item or it is dropped. A claim about results routes to the filings register; a
rumour has no primary source and is recorded as having none, rather than being
routed to the filings register because its subject happens to be results.

It also records what a complete account would have included and this did not, who
benefits if it is believed (incentives only — never an accusation), the base rate,
and **what would change the assessment**.

**The arithmetic is ours.** The credibility weight — source × corroboration ×
framing × claim support — is computed in code, with explicit ceilings: a
single-source story from an unrated publisher written in shock language cannot
exceed a low weight however favourable the rest looks, and severe framing caps an
article even from a wire. A model persuaded by the article never gets to vote on
how persuasive it was.

A weak story is not deleted or hidden. It keeps its score, loses most of its
influence, and carries the reasons why on the instrument page and in the flash
ticker. That is the difference between scepticism and censorship.

---

## One set of accounts per year

A company has one set of accounts for a financial year, and every source describes a view
of it. This system stores a row per source — the SEC's own tagged submission
(`xbrl_companyfacts`), a Yahoo statement, our model's reading of the filed 10-K
(`llm_extraction`) — so one year can arrive three times over. Measured 2026-10-09: 394
stored rows formed 333 accounting years, and **12 of those years held more than one
source**.

`analysis/collate.py` chooses the one row that stands for each year and reports the ones
it displaced. **Chosen, not merged**: filling a figure the filer's row does not state
from whichever other source does produces a set of accounts no filer ever published —
across those 12 years Yahoo's `total_debt` runs about 10% above the filer's on four of
them because it includes lease liabilities, `net_ppe` differs by 2.5x on two and
`receivables` by 3.6x.

- **Basis first, then source.** The full year's accounts stand for the year; an interim
  populates the slot until they arrive, and says so. Within that, the filer's own tagged
  accounts outrank our reading of the document, which outranks a synthesis, which
  outranks a scraped provider. Then the later period end, then the row id, so the choice
  is total rather than query-ordered.
- **The accounting year comes from the filings, not a calendar.** A fixed month and day
  cannot work: Apple's year ends drift (2024-09-28, then 2025-09-27) and a `(9, 27)` rule
  files the first under the following year. The boundaries are the annual period ends
  actually held, and a period after all of them belongs to the year the next annual will
  cover.
- **A rolling twelve months is never a year.** `ttm` is dated when it was read rather than
  at a period end, so it never occupies a slot.
- **Disagreements are qualified at 1%.** Of 99 live figure collisions, 8 agree within 1%
  — the same figure rounded, or converted at a slightly different rate — and calling
  those a disagreement would train the reader to ignore the panel.

The Accounts tab lists one row per financial year; a year's page lays out the chosen
accounts and a "where these figures came from" panel naming each displaced source, why it
was not used, the figures only it stated, and every disagreement with both values. **Hover a
figure in the Computed column** — or an "out by" in the accounting-health table — for the
calculation behind it: the stated total, every component with its sign, the sum, and the
lines left out of it. The analysis reads the same collated set, so the page and the verdict
cannot disagree about what a year's figures are. Nothing is stored: the collated set is
derived on read, and the rows stay exactly as the writers left them, because they are the
record of what each source said.

A price per share and a share count are not magnitudes of a statement's currency, so a
10-K presented "in millions" does not multiply them — see `metrics.NON_MONETARY_METRICS`.
`awltux repair-scaled` corrects rows written before that rule existed, reading each
correction out of the span the figure was quoted from rather than re-extracting.

### Correcting the accounts by hand

Automated extraction is wrong often enough that a reader who can see the mistake has to be
able to fix it. On a year's page every stated line carries a **remove** link, each section
heading an **add a line**, and both go to a confirmation page that asks what the line itself
cannot say: which side a figure is posted on, and whether a removal is for this period or for
every period the filer has.

**What has been changed is recorded at the foot of the tab, minimised.** Every correction is a
line that is not what the source said, so the record has to be findable from the figures it
corrects — but it is a record a reader consults *while editing* rather than a figure they came to
read, so it is a closed heading carrying a count ("3 changes · 1 learned line") and it opens
itself when a change has just been made. A period nobody has corrected shows no panel at all.

**The side is asked for only where nothing else knows it.** A figure is a magnitude; which way it
moves a total is a property of the *line*. A line the chart already carries is posted where the
chart posts it — the ledger sums it with that weight whatever the form says — so the form states
that side instead of offering a choice it would ignore. A line created from the filing's caption
is the one nothing else can decide, and there the reader is asked.

**A correction reaches the stored figures, not the display of them.** The corrected values are
written into `fundamental_period.metrics` and `metric_sources`, so the ledger, the hover
working, the composition checks, the markers, the valuation and the decisions all read the
corrected accounts rather than one page honouring them. What was changed is recorded beside
them, in a `corrections` column: the figure a removal displaced, the tag a clicked value came
from, the filing it was read out of, when, and why. `ingest/fundamentals._upsert_period`
re-applies it after it rewrites a row, so a `companyfacts` re-derive cannot quietly undo it.

- **A removal can apply to every period the filer has**, recorded once against the CIK in
  `app_setting`, and it reaches all of them at once — two years of one company disagreeing on
  screen about one line is a page nobody can use. A value cannot: a figure belongs to the period
  it was stated for.
- **Undoing puts back what the correction displaced**, which is why each one records it. A
  hand-typed figure has no filing to re-read, and a provider that stores no provenance still gets
  an entry written for the removal so the line can come back.
- **The later act on a line supersedes the earlier one**, and a hand-typed figure is applied
  after the filer-wide rules, so a period can override a rule its own page cannot undo.

### A line the filing names that this project does not

The chart of accounts is this project's vocabulary, and a 10-K has its own. Where a filing states
a caption the chart does not carry — Microsoft's current liabilities are stated at 168,825
against the 93,326 our key list holds, and the difference is captions like "Short-term unearned
revenue" — the confirmation page offers **the filing's own header as a line to create**, beside
the chart's lines, with the heading it is to be printed under.

- **The tag is the line's name.** Not a slug of the caption: it is the identity the *filing* gives
  the caption, so next year's 10-K answers to the same key without anything having to remember a
  label, and a subtotal the filer declares asks for it by tag.
- **Learned once, offered everywhere.** The line is recorded against the filer's CIK, so every
  later period offers it under the same heading instead of being taught again. Only the line is
  carried — the *figure* stays on the period it was stated for.
- **The heading is what makes it count.** A learned line joins the group its heading feeds, so a
  figure put under "Current liabilities" is added to current liabilities *and* to total
  liabilities, and the residual it was added to fix moves. It is printed **above** the subtotal it
  feeds rather than after it, because under the total it would read as a memorandum. `Equity` and
  `Memorandum` are printed and summed by nothing, and the statement says so rather than leaving a
  reader to assume.
- **On the profit and loss the heading says *where* and the side says *which way*.** The income
  statement's subtotals are a formula rather than a key list, so a learned line joins at the stage
  its heading names — "Revenue" from gross profit down, "Operating expenses" from operating income
  down, "Finance and tax" from profit before tax down — and moves the result by its side: a credit
  adds, a debit takes away. That is the convention the chart's own income lines follow and the
  trial balance posts by, the sign is in the working shown beside the figure, and the health check
  that audits reported profit reads the same cascade, so the row and the statement cannot disagree.
  **The figure keeps the sign the filing printed** — a deduction the filer brackets stays negative
  on the page — and it is its *size* the side then moves, so a deduction posted as a debit takes
  away rather than adding itself back.
- **A tag that already feeds a line is not offered as a new one.** `us-gaap:InventoryNet` is the
  Inventory line; a second line for one caption would be two figures that disagree the first time
  one of them is corrected. The form opens on the chart's line instead.
- **The form opens on what was clicked, not on what was being investigated.** A residual is what
  sent the reader looking; the clicked figure is tagged with the line it belongs to. The page says
  so when the two differ.
- **A learned line yields to the chart.** The mapping grows, and a caption taught to the page one
  year may be one the chart carries the next — at which point the learned copy is the same money
  again, because the extractor fills the chart's line from the payload while the reader's figure
  still sits under the tag. It is then printed by neither twice nor in silence: the statement drops
  the copy, and the corrections panel names it as superseded and says how to take the stored figure
  off. Where the chart's line holds *nothing*, the learned line keeps its place, because nothing
  else is holding that figure.

The balance sheet used to print one heading, "Non-current liabilities and equity", holding two
subtotals. That heading cannot say which of the two a first-time line feeds, so the statement now
prints "Non-current liabilities" and "Equity" separately — which is what the chart always
distinguished, and what makes every heading mean one total.

### Reading a value out of the filing

Where a year's accounts are the filer's own XBRL (`xbrl_companyfacts`) *and* the document is
stored, the **"out by" figure becomes a link** into the filing, in a new tab, carrying the
period and the line it is against. The accounting-health rows for the four composition subtotals
link the same way, because each audits one caption; the accounting equation, the roll-forward
and the cash movement measure the accounts rather than one line and stay plain. The link is
offered only where the accounts are the filer's own submission and the bytes are held — a link
into a copy, or into an EDGAR fetch on the reader's click, is a different offer.

`/filing/{id}/pick` serves the stored document with a script that makes its tagged figures
clickable. It is a URL of its own so that the ordinary `/filing/{id}/document` keeps its bare
`sandbox` policy, and the difference is a whole route rather than a flag: this one needs
`allow-scripts`, the filing's own `<script>` elements are stripped, `script-src` names this
application's origin so the filing's inline handlers cannot run, and `allow-same-origin` is
absent. `allow-popups-to-escape-sandbox` is what makes the click work at all — without it the
confirmation page opened from here would inherit the sandbox and load in an opaque origin.

Clicking a figure reads it the way the stored one was read: the printed text through its `format`
transform, times `10^scale`, negated by `sign="-"`, with a nil or continued fact refused rather
than read as zero. **Brackets are the accounting negative, and they are read on either side of the
tag** — filings print `(1,234)` with the brackets inside the tagged element and, far more often,
around it, as `(<ix:nonFraction>1,234</ix:nonFraction>)`. Measured 2026-10-10 across the stored
documents: **130,527 of 962,078** tagged figures in **497 of the 601** documents are printed the
second way, and before this they all read as positive. One negation per figure: a figure the
filing brackets twice is not a credit. Two things come from around it, and both are measured on Microsoft's 2026
10-K — 1,583 tagged figures, of which 1,465 sit inside a table row and 454 of the 476 rows that
hold one are captioned. The row's first cell names the line in the filer's own words (the "Total
assets" row is captioned exactly that), and the `contextRef` dates it, which matters because that
row carries `us-gaap:Assets` twice, 758,376 and 619,003, under the one caption. A figure clicked
out of the prior-year column is marked as the wrong period rather than written onto the line as
if it were this year's.

**A click never writes anything.** It builds a link to the confirmation page with the metric, the
figure, the tag and the filing's caption for the line, in a new tab of this application; a person
chooses the side and presses the button there. The picker runs in an opaque origin with nothing
but its own document, which is exactly the position from which it should not be trusted with a
write.

**Every heading has a way in, not only a broken subtotal.** A residual link is the *only* route
into the filing for a set of accounts that reconciles — and a reader adding a line the extractor
never had has no residual to follow. So each heading on the accounts page also offers *read a
figure from the 10-K*, which opens the same picker with nothing attached: the reader clicks the
number, and the confirmation form asks which line it belongs on.

**And a filing with no tagged figures is still readable.** 601 of the 603 stored filing documents
are inline XBRL (measured 2026-10-10); for the two that are not — `AREC_US_EQ`'s 10-K and
`BMM_US_EQ`'s 40-F — the picker reads the numbers out of the tables instead. A row is captioned
by its first cell that holds a word, and every readable figure after it becomes clickable, with
the figure read the way a table prints one (`$ 604,485`, `(1,347,784 )`) and anything else —
a percentage, a footnote marker, a bare year, a dash — refused rather than guessed at.

The row's caption is then matched against this project's own labels for the statement the reader
came from, and a match pre-selects that line on the confirmation form. The match is on the whole
set of words, so *Cash and cash equivalents* finds *Cash and equivalents* while *Total assets*
does **not** find *Total current assets*. A caption that matches nothing costs nothing: the form
still asks. What such a figure cannot do is become a line of its own — a line this project learns
is remembered by the filing's tag, and this filing has none — and the confirmation page says so.

**Finding them in the document.** A filing is up to 8MB of somebody else's HTML and Microsoft's
2026 10-K holds 1,583 tagged figures, so the tray carries the navigation: **‹ Previous** and
**Next ›** walk every readable figure in document order and wrap at the ends, with a counter
saying where in that list the reader is; each picked figure has a **show in the report** button
that scrolls back to it and flashes it; and a row is outlined when the reader is on it. The
figures themselves are marked loudly — an amber wash and a solid underline — because a mark that
has to be hunted for is not an affordance, with a **Highlight: on/off** toggle beside the
navigation for reading a document rather than picking out of it, and a picked figure turning blue
so "which have I taken" is a glance.

---

## Deep-dive research

The **Research** button on an instrument or sector page asks the deep model to judge
whether that thing is a suitable investment — what the business is and how it earns,
whether it has a durable advantage, how management allocates capital, what could go
wrong — and writes the answer as an XHTML report kept on disk. Nothing runs on a
schedule: it is the most expensive call this application makes, and a person presses
a button for it.

**Nothing is fetched live.** A run refreshes the instrument through the existing
pipeline first — unless a successful refresh finished within
`research.refresh_within_minutes`, which the report records — and then reads what
that left behind:

- the annual reports held, as text, bounded per document and in total;
- the appraised news, filtered on the subject's own **"What it concerns"** entry
  rather than on "the story mentions the ticker": a Google News search for one company
  returns pieces that only print its name. Each story carries the priority score
  `materiality × credibility × recency` and its components, and the prompt is told the
  known inversion — an unappraised story outranks the same story judged single-source,
  because the unassessed default weight is above the cap a single-source appraisal
  lands on — so the ranking is not read as a verdict on truth;
- the figures already extracted, each with the words it was quoted from;
- the last decision this system made, named as its own view rather than as an input.

Sectors read the news corpus only: there is no sector filing and no sector refresh,
and the report says so rather than implying a gap.

**The prompt is yours.** The dialog fetches the template — a scope inventory plus the
rules and the JSON schema — and shows it in an editable box. What is submitted is what
runs, and the report stores it verbatim with its SHA-256, so the conclusions stay
arguable. With JavaScript off, the form starts the run with the template unchanged.

**The result set is not a separate island.** The cited figures go through the same
`validate_extraction` gate as every filing extraction — canonical names, a quoted span
of at least twelve characters, a location, and a refusal when the document did not say
what units it used — and then through the *same writer*: a deep-dive's figures become a
stored `FundamentalPeriod` under `deep_research`, which the valuation, the markers and
every accounting check read. It ranks just below `llm_extraction`: both read a document
and both quote what they read, but the filing extractor's whole job is one document and
its figures while a deep-dive is a synthesis, so when the two disagree about the same
period the focused read wins.

**And the decision can see it.** The newest finished report goes into the decision state
as `deep_research` — the verdict, the confidence and the executive summary, named as a
judgement rather than as a measurement — so the engine can weigh it or disagree with it.
An instrument nobody has researched has no such key, and its state hash is unchanged.
When the two *do* disagree directionally — an `attractive` deep-dive against an action of
`reduce` or worse, or the reverse — the row carries a `research_conflict` reason at
attention level 3, which says both are judgements and neither is a measurement. `watch`
and `insufficient_evidence` contradict nothing and never raise it.

**What it will not do.** It never predicts a price, a target or a return; every figure
it states must be one it was given and quoted, and an empty `metrics` object is an
acceptable answer. The model never authors markup either: the report is rendered from
structured fields with autoescaping, because a model-written document would be an
injection surface served from this application's own origin.

**What it costs.** One refresh plus one call to the deep model over up to three
documents. Measured 2026-10-09, a company with two annual reports on file produces
410,826 characters of evidence — about 120,800 tokens — against a 128,000-token
context window with a 16,000-token answer requested, so the evidence is trimmed to fit
and the report's footer lists what was dropped. One deep-dive runs at a time, one per
subject at a time, and the subject's own row is the guard.

---

## Levers: what moves a business

A deep-dive answers whether the *business* is worth owning. Two shorter answers sit above
the tabs on every instrument page, because they are what a reader wants before choosing a
tab: **what the company is**, and **what moves it**.

**What the business is** is the latest finished deep-dive's own account — what it does, how
it makes money, the advantage it believes it has, who it competes with. It is read out of the
stored report (`business` in the report's result set) rather than copied onto the instrument,
so the sentences a verdict rests on are the ones the report contains and there is one place to
argue with. A company no one has run a deep-dive for shows nothing there, and says so.

**Levers** are the things that move the business: `interest_rates`, `inflation`,
`exchange_rates`, `economic_growth`, `energy_costs`, `raw_material_costs`, `labour_costs`,
`consumer_demand`, `corporate_spending`, `government_spending`, `technology_change`,
`regulation`, `competition` and `weather_and_climate` — fourteen, in four groups, each with a
sentence in `analysis/levers.py` saying how it reaches a business.

The vocabulary is fixed rather than free text, and that is the whole design. The value of the
feature is the question asked *across* instruments — **what is affected if rates rise, or the
pound falls, or energy gets dearer** — and nobody can join on prose. So a lever is a key, and:

- **`/levers`** lists the vocabulary with how many in-universe instruments each is recorded
  against, and how much of the universe carries any record at all;
- **`/levers/{key}`** lists the instruments recorded against one lever, with the direction of
  the effect for each.

**A direction is read against a *rise* in the lever**, which is what makes a bank, a
housebuilder and a utility comparable on one page: `positive` means the business does better
when the lever goes up, `negative` that it does worse, `mixed` that it cuts both ways — a real
answer, not an undecided one — and `unknown` that the direction has not been established. Each
record also says whether the lever is **primary** (it moves the earnings on its own) or
**secondary**, and carries the **reason** in the recorder's words. A record with no reason says
"no reason given" rather than carrying a sentence nobody wrote.

One row per instrument and lever, upserted: recording again replaces the judgement rather than
appending a second opinion, because the question is what the exposure *is*. Table
`instrument_lever`, owned by `analysis/levers.py`.

**Recording one.** On the instrument page, under *What moves it*, or:

```bash
awltux levers list
awltux levers set AAPL_US_EQ interest_rates=negative:primary exchange_rates=mixed \
  --reason "sells worldwide, borrows at floating rates"
awltux levers show AAPL_US_EQ
awltux levers forget AAPL_US_EQ interest_rates
```

**Nothing generates them yet.** The obvious source is the deep-dive, which already reads the
whole company — so a `levers` block would spend output tokens on a call that is made anyway,
not another call — but the mechanism came first and `TODO.md` carries the prompt change and
the shape to read. Until then the pages fill in only as exposures are written down, and they
say so rather than leaving an empty table to be read as "nothing moves this business".

---

## Provability

Every decision stores: the canonical state and its SHA-256, the exact questions,
the raw engine response, the versioned model id, the composite, the gate verdict
with every check, and the evidence with source citations.

- **`/api/decisions/{id}/receipt`** returns the whole chain.
- **Replay** (`POST /api/decisions/{id}/replay`) re-runs the stored state through
  the recorded engine and reports whether it reproduces. Because the state is
  canonicalised (sorted keys, rounded floats, pruned nulls), the same inputs
  always hash identically — so "the same state" is a checkable claim.
- **Ledger verification** re-hashes stored states and reports any that no longer
  match, along with any decision missing a model id or gate verdict.
- **Calibration** tracks realised outcomes and reports hit rate by confidence
  bucket and by engine — on **different windows per horizon**: 30/90/180 days for
  long term, 5/10/20 days for short term. Scoring a tactical call over 90 days
  would measure noise rather than skill, so the two are never blended. A
  **calibration inversion** — higher confidence not outperforming lower — is
  surfaced prominently.
- Every figure in the UI carries its source and as-of time.

A confidence score is only meaningful if it is measured. That page is what
measures it.

### Times: stored UTC, shown in your zone

Every timestamp is **stored in UTC** — that is what `utcnow()` writes, and anything
used as a storage key or a cutoff is derived from UTC too, because `date.today()`
is today *here* and is wrong by a day for part of every day.

Everything is **displayed in the reader's zone**. A timestamp rendered in UTC is
correct and, for anyone not on UTC, misleading: "observed at 08:30" is a different
fact in London and in New York. The browser reports its own zone once, in the
`awltux_tz` cookie, and the server renders in it — including after the reader
travels or the clocks change. With JavaScript off, the configured `app.timezone`
is used.

Every rendered time carries its zone label (`14:32 BST`, `09:32 EDT`, `14:32 UTC`),
the footer states which zone the page is using, and no zone is ever guessed from an
IP address or a language header. The JSON API returns ISO-8601 with an explicit
offset, so a consumer can localise for itself.

The IANA database is a declared dependency (`tzdata`) rather than an assumption
about the host: a slim image without it would resolve no zones at all and quietly
show UTC to everyone. `awltux doctor` reports the zone database and the configured
zone so that failure is visible rather than silent.

---

## Dashboard

| Page | What it shows |
|---|---|
| **Recommendations** | Sortable table with **both verdicts side by side**, plus a `Suits` column showing which horizon the evidence actually supports. Filters follow a selected horizon. Views for *actionable only*, *my holdings*, and *suits long/short term* |
| **Instrument** | Decision receipt with **a card per horizon**: verdict, composite, confidence, gate checks, and the tactical setup/drawdown scores. Plus fair-value range, per-method breakdown, model answers with probabilities, narrative, filings, **one set of accounts per financial year**, news, and — above the tabs — **what the business is and what moves it**, both from the latest deep-dive. **Refresh now** runs the pipeline stages for this company alone — prices, filings, statements, the annual reports and what they disclose, news, sentiment, valuation, and a fresh decision — so a call can be checked against data the sweeps have not reached yet. **Research** runs a one-off deep-dive of the business and keeps the report, listed under the tab |
| **Sectors** | A sector's own **equal-weighted price index** (each instrument rebased to 100, so a 3,000p share and a £30 one contribute the same), its sentiment heatmap, drill-down to constituents, and the same **Research** block, with the latest executive summary above it |
| **Calibration** | Per-horizon tabs; realised hit rate and return by confidence and by engine; high-confidence misses |
| **Operations** | Job status and history, provider health, LLM spend, ledger verification; run any job by hand |
| **Info** | The commit this process is running, whether the tree was clean when it was captured, the database revision, and the last ten commits with their hashes |

The **API** link in the navigation opens the OpenAPI docs in a new tab rather
than navigating away from the dashboard.

The **news flash ticker** streams over Server-Sent Events, colour-coded by
materiality, tagged with affected tickers and sectors, linking to the source.

The API exposes both horizons explicitly (`long_term` / `short_term` objects per
item) rather than flattening them, so a consumer can see them disagree:

```bash
curl -s localhost:8080/api/recommendations?horizon=short_term | jq '.items[0]'
```

### Honest latency

"Realtime" here means *continuously updating*, not tick-by-tick — free-tier
sources cannot support that:

| Data | Latency |
|---|---|
| US filings (SEC EDGAR Atom) | under a minute |
| News headlines | up to a day: the poll is daily, and it was hourly until 2026-10-16 — one sweep of the universe spends the feeds' own daily allowance, so the runs in between had nothing to fetch |
| Prices | 15-minute delayed, or end-of-day |
| UK regulatory news | best-effort only — real-time RNS is a paid licence |
| Everything you **hold** | the whole pipeline — filings, news, valuation, decision — re-run hourly (`held_refresh`), rather than waiting for each stage's own sweep to reach it |

---

## Configuration

Secrets live in `.env`. Tunables live in `config/config.yaml`: universe size,
polling cadences, per-provider rate-limit budgets, valuation weights and
assumptions, **per-horizon composite weights and gate requirements**, LLM spend
ceiling, and the horizon labels and indicative holding periods shown in the UI.

Holding periods are configuration, not model output. A language model asked for a
holding period will invent a plausible number; a documented range you can edit is
honest and checkable.

```bash
docker compose exec awltux awltux settings   # effective config, secrets redacted
docker compose exec awltux awltux jobs       # the job registry
docker compose exec awltux awltux job price_eod   # run one job now
docker compose exec awltux awltux quiet      # pause and wait, before a rebuild
docker compose exec awltux awltux unquiet    # resume after an abandoned upgrade
```

### Running the app outside Docker

```bash
awltux migrate          # bring an existing database up to the current schema
awltux serve            # dashboard + scheduler (migrates on start, like the image)
awltux seed-demo        # five synthetic instruments, so the UI works with no keys
awltux doctor           # diagnose configuration and provider connectivity
awltux job <id>         # run one job now, on the server if one is running
```

`seed-demo` writes into the real database rather than mocking the UI: it seeds
instruments and then runs the actual valuation, sentiment and decision pipelines,
so what you see is real dashboard behaviour. Remove it with
`awltux seed-demo --reset --no-analysis` or a fresh database.

`job` asks a **running server** to execute the job and falls back to running it in
this process only when nothing is listening — two processes writing one SQLite file
contend for the write lock, and a job that sleeps inside a rate-limit guard holds
it longer than any sane timeout. Pass `--direct` to force a local run.

### The database is never recreated

`data/awltux.db` holds every fact this system has recorded: the instrument
universe, price history, filings, news, decisions and their scored outcomes. It is
not a cache, and it is never deleted or rebuilt to pick up a schema change. A
fresh database is not an upgrade — it discards the only copy of the history.

When a model changes, the schema moves forward in place:

```bash
alembic revision -m "what changed"   # write the migration
awltux migrate                       # apply it to the existing file
```

Two rules make that safe. Migrations are **additive and inspection-guarded** —
`0004` adds `news_item.event_type` only if the column is absent — so `upgrade head`
is correct for a fresh database, an old one, and one already migrated. And
`awltux migrate` **copies the database to `data/backups/` before it rewrites
anything**, skipping the copy when there is nothing pending so that no-op runs on
container start do not bury the backups that matter.

The only things that destroy stored data are deleting the file and
`awltux seed-demo --reset`, which removes the demo-marked rows and leaves provider
data alone. Neither is part of an upgrade.

### Diagnosing a rejected key

```bash
docker compose exec awltux awltux doctor            # full connectivity check
docker compose exec awltux awltux doctor --offline  # local state only, no network
```

`doctor` reports credentials by length and character class (never the value),
tests every provider against the free endpoints, and compares a failing call
against a **bogus-credential control**. That comparison is the point: if your key
and a deliberately wrong key produce the same response, the credential is the
problem; if they differ, the request is. It also confirms reachability with an
invalid path, which distinguishes an auth failure from an edge block.

It exits non-zero on failure, so it works as a preflight step.

**IP-restricted keys and dual-stack hosts.** If a provider key is restricted to an
IP allowlist, note that a machine with both IPv4 and IPv6 presents a *different*
source address per family. Allowlisting your IPv4 address achieves nothing if the
client then connects over IPv6 — and IPv6 privacy extensions rotate the address,
making an IPv6 allowlist fragile. Set `AWLTUX_FORCE_IPV4=true` to make the address
a provider sees predictable, and run `doctor` to see both addresses reported.

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate    # or activate per your shell
pip install -e ".[dev]"
pytest -q
ruff check .
python tools/refactor_report.py --diff           # what in your change is hardest to change
alembic upgrade head
```

`ruff` enforces a complexity ceiling (`C90`, 15 paths through a function), and
`tools/refactor_report.py` shows where the rest of the debt sits: the longest
functions, the most branchy, and the small ledger of functions excused from the
ceiling by name with the reason recorded against each. The convention is that the
ledger only shrinks — a `noqa` is a decision to be argued, not a way past the check.
See *Refactor before you commit* in `AGENTS.md`.

The test suite runs **entirely offline** — no network, no API keys — and covers
the currency normalisation, symbol resolution, valuation methods, sentiment,
canonical state hashing, every gate refusal path, engine answer parsing, the full
pipeline end to end, ledger integrity, replay, and the HTTP layer.

### Build provenance

An installed copy has no `.git` and no `git`, so the commit history the **Info**
page shows has to be recorded while both are still available. `docker build` does
that: it copies `.git` into the builder stage, runs

```bash
PYTHONPATH=src python -m awltux.buildinfo --write src/awltux/build_info.json \
    --paths src pyproject.toml README.md config alembic.ini
```

and fails the build if no commits were captured. `--paths` exists because the
builder holds only part of the tree: a whole-tree `git status` reports every
uncopied file as deleted, which would mark every image a dirty build. The list
must cover everything the image copies.

The file is gitignored, which is what keeps the *"was the tree clean?"* flag on
the page honest — commit first, then build, and the image can name the exact
revision it came from. A source checkout ignores the artifact and reads `git log`
live.

### Layout

```
src/awltux/
├─ providers/    one module per external API; the only place that uses the network
├─ ingest/       provider responses → provenance-tagged rows
├─ analysis/     deterministic maths; produces every number
├─ llm/          DeepSeek extraction and summarisation, with citations
├─ decision/     engines, questions, composite, gate, replay
├─ audit/        the immutable ledger and calibration
├─ scheduler/    job registry and the background runner
└─ web/          FastAPI routes, Jinja templates, SSE
```

Known bugs, open questions and deferred work live in [`TODO.md`](TODO.md), each
with the evidence that found it. The research behind the marker set — what the
accounting, quality, language and news literature actually supports, and what it
does not — is in [`docs/investment-markers.md`](docs/investment-markers.md).

---

## Safety

- **Advisory only.** No live order path exists. Order placement refuses to run
  unless `AWLTUX_T212_ENV=live` **and** `AWLTUX_ALLOW_LIVE_ORDERS=true` are both
  set deliberately.
- Paper trading against the Trading 212 **demo** environment is opt-in.
- The dashboard binds to loopback and is unauthenticated — do not expose it.
- Secrets are read from the environment, never logged, and scrubbed from log
  output by a redaction filter. Request bodies are stored with credentials
  removed.
- **Filings and headlines are untrusted input.** Prompts delimit them as data and
  instruct the model to ignore embedded instructions; a suspected injection is
  recorded on the extraction.

## Licensing and data sources

The free tiers this project relies on are licensed for **personal,
non-commercial use**, with no redistribution. The application therefore stores
data locally for private research and links back to publishers rather than
republishing content. If you intend to publish or monetise this, you need
licensed feeds.

| Source | Covers | Licence |
|---|---|---|
| Yahoo Finance (`yfinance`) | US + LSE prices, history, profiles | Unofficial scrape; personal use |
| SEC EDGAR | US filings and XBRL financials | Public domain |
| Companies House | UK company filings | Open Government Licence |
| Marketaux / Finnhub | News, sentiment | Free tier, personal use |
| GDELT | News tone | Open |
| Google News / Yahoo RSS | Headlines | Personal, non-commercial |

`yfinance` is a scrape of an undocumented API and **will break eventually**. It
sits behind a provider interface with a disk cache and a staleness gate that
suppresses decisions rather than acting on old prices.

**Every source above is rate-limited locally**, because several of them enforce
undocumented quotas and answer a breach with a block rather than a 429. The rules
live in `config/config.yaml` under `budgets`, and `tests/test_rate_limit.py` fails
if a provider in the tree has no rule. Two shapes matter: a *pace*
(`min_interval_seconds`) for a provider that also keeps an unnumbered per-minute
limit, and `reset: utc_day` for one whose quota is counted against the calendar day.

That table used to list Stooq as a price fallback. It is not one: **there is no
Stooq adapter in this tree**, and since 2026 the endpoint needs an API key and
answers a plain HTTP client with a browser-verification page.

### Known limitations

- **UK fundamentals are the weak spot.** Companies House exposes filings, not
  financial line items; the structured route is iXBRL, of which only ~60–75% of
  accounts are electronically filed. Some UK names will report
  `insufficient_data` rather than a fabricated valuation, which is the intended
  behaviour.
- **UK entity resolution is fuzzy.** LSE ticker → Companies House company number
  is name-matched and scored; anything below the confidence floor is excluded
  from decisions until confirmed.
- **Sector classification is derived**, not licensed (SEC SIC for US, provider
  industry fields for UK), so sector sentiment is approximate.
- **No free real-time UK RNS.** UK event detection is best-effort.
- **An instrument whose unit cannot be reconciled is left unpriced rather than priced wrong.**
  Prices are normalised out of the provider's unit into the broker's, and the unit used is the
  instrument's own `currencyCode` — an LSE line is usually quoted in pence but not always
  (`VWRLl_EQ` is quoted in pounds). When the provider's bars come back at a different unit from
  the one the instrument's code implies, they are refused and recorded as a blocker instead of
  stored: the two differ by a factor of 100, the result still looks plausible, and an instrument
  visibly missing from a run is better than one carrying a confident wrong price. Measured
  2026-10-09: 482 of the 488 priced instruments agreed, and six did not. `awltux repair-price-units`
  corrects rows an earlier version stored the wrong way round — a refresh does not always reach
  them, because the row the page reads is the newest and the provider's live row for the current
  day carries a null close until the session settles.

## Licence

MIT.
