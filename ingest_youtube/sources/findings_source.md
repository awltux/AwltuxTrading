## What was read, and what it was worth

**Selection came before acquisition, and the two disagree about the corpus.** The
tiered inventory holds 181 videos and 42 playlists *selected* by title out of 1,233
videos and 387 playlists enumerated across the six channels — 220 items, not 1,600.
Thirteen transcripts were read for this pass: twelve that an earlier run fetched, and
one fetched through this POC's fetcher.

The twelve fetched earliest are all classified `entertainment` by
`distill.kind_of`, and none of them clears its method bar of four distinct concepts
across at least twelve mentions. Their titles are "The 5 Stocks Print MILLIONAIRES",
"Never Buy Stocks When The Market Is This Expensive" and "The Window To Build Real
Wealth Is Closing", and their text opens the same way. What vocabulary they do carry
is scattered and mostly numerical: across the twelve, 65 of their 119 extracted
passages are the meta category "a figure that would need a filing" — the tool noticing
a percentage, not a method — and the remainder are 20 mentions of returns on capital,
14 of multiples, 9 of moats and 11 others spread over three more concepts, none of
them defined. The one video that clears the bar, the Damodaran session, contributes 43
passages on 11 concepts by itself.

None of the twelve is in the saved selection, and none is in the tiered selection
either. The title selector was tuned precisely so that they would not be, and this
corpus is the measurement that it worked.

That leaves **one video of real method content** for this pass: Damodaran's
*Session 4: DCF Big Picture and First Steps in Riskfree Rates* (15,433 words, the
fifth orientation session of a 42-part course).

## 1. Returns on capital against the cost of capital — already covered

The lecture frames the DCF as one identity — cash flow, discounted at a rate that
matches it, with a terminal closure — and puts the cost of capital at the centre of
it. The repo already holds that argument in far more depth than a lecture can:
`docs/investment-markers.md` §3.1 and §3.3,
`docs/research/capital-allocation-synthesis.md` and
`docs/research/quality-capital-allocation-governance-markers.md` §1.1, the last with
the Morgan Stanley *Measuring the Moat* evidence behind it (top economic-profit decile
+$1.1tn, bottom decile −$400bn, 2019–2023 average).

**Disposition: already covered.** Nothing here to build.

## 2. Terminal value — already covered

The lecture's point is the constancy assumption: `TV = CFₙ₊₁ / (r − g)` is "just an
equation you plug numbers into", and it only means anything if g is constant forever.
The repo's treatment is stricter, because it has the XBRL constraints the lecture does
not: `docs/research/reinvestment-and-capital-discipline.md` carries the
`g = reinvestment rate × ROIC` link and the caveat that WACC and invested capital are
not tags at all.

**Disposition: already covered.**

## 3. The risk-free rate: currency, maturity, and inflation consistency — implement

**This is the gap, and it is the one the lecture is actually about.** Of 386
ninety-word units in the session, 90 concern the risk-free rate. Three claims survived
reading, all of them about *consistency* rather than about a number:

- **Currency.** The same company valued in Brazilian reais and in dollars must come
  out at the same value; the scenario put to the class is a 7.5% real risk-free rate
  against a 2.5% dollar rate, with everything else — cash flows, growth, discount rate
  — denominated consistently in the chosen currency.
- **Inflation.** "Inflation is the driver of risk-free rates" and of exchange rates;
  a nominal rate discounts nominal flows, a real rate discounts real flows, and
  negative risk-free rates are a statement about the country's deflation, not a broken
  model.
- **Maturity.** The session's own title calls the risk-free rate a *first step* that
  has to be settled before the discount rate means anything.

**What the app does today.** The currency rule is already the app's design and is
better documented than the lecture: `src/awltux/analysis/macro.py` states that "a USD
rate must not discount GBP flows", an unknown currency is explicitly **not** defaulted
to dollars, and `refresh_valuations` resolves a rate per cash-flow currency and
records which rate applied to which currency so "a run that silently priced sterling
off a dollar curve would look identical in every other counter here"
(`src/awltux/analysis/valuation.py`, and the note in `macro.py` that at the ~47bp
long-end spread within one month the error is not noise).

**The gap, measured.** `CURRENCY_CURVES` in `src/awltux/analysis/macro.py` holds
**USD and GBP only** — `{"USD": "treasury", "GBP": "gilt"}`. Every other currency
resolves through the fallback path in `resolve_risk_free_rate`, returning the
configured constant with a note. So a euro-, yen- or real-denominated instrument is
discounted at a USD-shaped constant while the app's own stated rule says a rate has to
match the currency of the flows it discounts. The fallback is honest — the note reaches
`risk_free_rate_note` and the instrument page prints it — but the *number* is not a
Eurozone or Brazilian rate, and nothing downstream distinguishes "this instrument's
rate" from "the world rate in the config file".

**What to build.** Wire at least one curve for the material non-USD/GBP currencies in
the universe (the macro job already takes a currency and a provider per
`CURRENCY_CURVES`), and — separately — make the maturity a function of the cash flows
being discounted rather than one global `risk_free_rate_tenor: "10 Yr"`. The second is
the weaker recommendation: the config knob exists, no per-instrument policy uses it,
and a company whose value sits in the terminal years is discounted off the ten-year
point while the app holds no view about that.

**Primary sources to rest this on, before any of it is built.**

- Aswath Damodaran, *Estimating Inputs: Discount Rates* — the "extending the
  consistency rule" material, at
  [pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/dcfrates.pdf](https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/dcfrates.pdf).
- The companion session slides the lecture follows,
  [session4slides.pdf](https://pages.stern.nyu.edu/~adamodar/podcasts/valUGspr20/session4slides.pdf).
- Country risk and the country risk premium, for the currency part, from the same
  author's published notes.

**Confidence:** the video is Tier D by construction and the primary sources above were
**not** opened in this pass — both URLs are PDFs this session could not fetch, and
only their titles are verified. The three claims are stated in the transcript in the
lecturer's own words, but a transcript is machine-recognised and cannot be the
evidence for anything. **This finding is a pointer, not a proof, and must be
re-graded against the papers before it is acted on.**

## 4. Worked examples are not method — deliberately not doing

The inventory's `example` tier (24 videos: "MCD Stock Intrinsic Value", "Google Stock
Intrinsic Value") applies a technique to one ticker. Their numbers are stale within a
year and the ticker may not be in the universe, so they cannot teach the app anything.
The one narrow use the task note allows — checking our arithmetic against somebody
else's worked case — needs the *same* company on the *same* date, and no video in the
set is guaranteed to line up with a stored `FundamentalPeriod`. Reading them is a
per-example, per-date decision made when a disagreement is found, not a corpus to
ingest. **Nothing further proposed.**

## 5. What would have to be true for this corpus to change a marker

Nothing in one 42-part course will. The literature base in `docs/research/` is
source-graded with effect sizes; a lecture is one person's summary, frequently of a
paper that has since been challenged, and it arrives already agreeing with us. The
honest output of this pass is therefore small on purpose:

- no new marker, and no marker changed;
- one code-level gap confirmed by reading rather than by watching: **the risk-free
  rate is wired for two currencies and the universe holds more than two**;
- one candidate the video cannot settle: **discount-rate maturity against cash-flow
  duration**;
- and a selection result worth keeping: **the twelve videos fetched earliest are
  absent from the selection and contain no method**, which is the selector working.

## Still to acquire

The budget is the binding constraint, not the reading. At 15 requests per 24 hours the
100 core videos that remain are about seven days of elapsed time; the 42 selected
playlists have not been expanded into their videos at all, and expanding them is what
the task note says carries the method. Anything fetched later is graded by the same
rule as above: it can suggest a marker, it cannot be the evidence for one.

The next pass should spend its requests on the *Valuation MBA* and *Valuation
Undergraduate* course sessions, which are the pure-method material, and on expanding
the selected playlists — not on the `context` tier, which is 48 videos about moats and
buybacks where the repo is already stronger than YouTube.
