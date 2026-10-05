# Dividend Policy Capital‑Allocation Markers — Source‑Grounded Evidence Review

**Scope and rules used.** Every substantive claim below is tied to a URL I actually retrieved in this session (listed in *SOURCES FETCHED*). Where I could not retrieve the number, I write **UNVERIFIED** and say exactly what is missing. Abstract-level retrieval (via OpenAlex/SSRN/Semantic Scholar/NBER landing pages) gives authors, year, journal, volume/pages and verbatim abstract text, but **not** every table coefficient in the paper. Where the abstract contains the number, I quote it. Where it does not, I say so rather than inventing it.

**One important caveat up front on point (5) "did it hold up".** Full "post‑publication decay" replications (e.g. McLean & Pontiff‑style) were **not** retrieved for these specific markers in this session. What I *can* document is (a) direct academic re‑examinations and (b) explicit failure‑to‑replicate papers. Those are flagged per marker.

---

## A. Dividend initiations and omissions as signals

### A1. Marker name, definition, formula

**Dividend initiation / omission event signal.** A binary corporate event: a firm paying its first cash common dividend ("initiation") or suspending/eliminating a previously paid common dividend ("omission"). Inputs: the firm's common dividend per share history.

- `Initiation_t = 1 if DPS_t > 0 and DPS_{t-1..t-k} = 0`
- `Omission_t = 1 if DPS_t = 0 and DPS_{t-1} > 0`

Signal readings: initiations are read as management confidence about *permanent* earnings; omissions as distress. The tradable claim in the originating paper is **post‑announcement drift**, not merely the announcement reaction.

### A2. Originating study

Michaely, Thaler & Womack (1995), *"Price Reactions to Dividend Initiations and Omissions: Overreaction or Drift?"*, **Journal of Finance 50(2): 573–608**; working paper version NBER WP 4778 (June 1994), DOI 10.3386/w4778 — [NBER paper page](https://www.nber.org/papers/w4778).

### A3. Sample

The NBER abstract does not state the sample period or N in the retrieved page. The study uses the dividend‑event universe of US exchange‑listed firms with dividend history data. I did **not** retrieve the paper body, so the exact sample window and event counts are **UNVERIFIED** (missing: N of initiations and N of omissions, CRSP/COMPUSTAT sample years). What the retrieved abstract *does* confirm is that the drift test spans **"22 out of 25 years"**, implying a ~25‑year event calendar.

### A4. Reported effect sizes (verbatim from the NBER abstract page)

> "short run price reactions to omissions are greater than for initiations (**‑7.0% vs. +3.4% three day return**)."

> "when we control for the change in the magnitude of dividend yield (which is larger for omissions), the asymmetry shrinks or disappears, depending on the specification."

> "In the 12 months after the announcement (excluding the event calendar month), there is a significant **positive market‑adjusted return for firms initiating dividends of +7.5%** and a significant **negative market‑adjusted return for firms omitting dividends of ‑11.0%**."

> "A trading rule employing both samples (long in initiation stocks and short in omission stocks) earns **positive returns in 22 out of 25 years**."

Client effects:

> "we find little evidence for such a shift. Volume increases, but only slightly and briefly, and there are no important changes in institutional ownership."

### A5. Did it hold up out‑of‑sample / after publication?

**Partially — and the drift leg is the contested one.**

1. **Boehme & Sorescu (2002), *"The Long‑run Performance Following Dividend Initiations and Resumptions: Underreaction or Product of Chance?"*, Journal of Finance 57(2): 871–900** — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/1540-6261.00445). Sample: **1927 to 1998**. Verbatim abstract:
   > "postannouncement abnormal returns are significantly positive for **equally weighted** calendar time portfolios, but become **insignificant when the portfolios are value weighted**. Moreover, our results are **not robust across subsamples**."
   > "Cross‑sectionally, these [reductions in risk factor loadings] are negatively related to contemporaneous price drifts, suggesting that the drifts may be a **sample‑specific result of chance**."
   This is a direct methodological challenge: the +7.5% initiation drift of MTW1995 survives only in equal‑weighted portfolios.

2. **Liu, Szewczyk & Zantout (2008), *"Underreaction to Dividend Reductions and Omissions?"*, Journal of Finance 63(2): 987–1020** — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/j.1540-6261.2008.01337.x). Note: the paper frequently cited as "Boehme & Sorescu" for omissions is in fact this paper. Sample: **2,337 cash dividend reduction or omission announcements over 1927 to 1999**. Verbatim:
   > "this study reports significant negative post‑announcement long‑term abnormal returns, which **last 1 year only**. However, this performance is **driven by post‑earnings‑announcement drift**. After controlling for earnings and skewness of buy‑and‑hold abnormal returns, there is **no compelling evidence** of post‑dividend‑reduction or post‑dividend‑omission price drift."
   So the ‑11.0% omission drift is largely re‑attributed to earnings‑announcement drift, not a dividend‑specific anomaly.

3. **"Disappearing dividends" era.** Hobbs & Schneller (2012), *"Dividend signalling and sustainability"*, Applied Financial Economics 22(17): 1395–1408 — [OpenAlex record](https://api.openalex.org/works/doi:10.1080/09603107.2012.654909). Verbatim from the abstract:
   > "during the disappearing dividends era, dividends vanished **not only because they were less frequently initiated** – the oft‑cited reason – but also because, **once initiated, they were less likely to be sustained**."
   > "the market responded favourably to initiations **but did not distinguish ex‑ante between short‑run and long‑run payers**."
   > "**sustainability was in fact predictable out of sample**, using information strictly available to investors at the time of the announcement."
   > "[firms that] we predict to become permanent **significantly outperform** their counterparts in subsequent years."
   This is the closest thing I retrieved to the "disappearing dividend drift" literature, and it *softens* the MTW story: the market fails to price persistent‑payer vs temporary‑payer status at initiation.

4. **Fama & French (2001), *"Disappearing dividends: changing firm characteristics or lower propensity to pay?"*, Journal of Financial Economics 60(1): 3–43** — [OpenAlex record](https://api.openalex.org/works/doi:10.1016/S0304-405X(01)00038-1). The OpenAlex record returns no abstract text; the widely quoted "66.5% (1978) → 20.8% (1999)" payer proportions are **UNVERIFIED** here because I did not retrieve the paper body.

**Classification: (c) contested.** The announcement‑day reaction (+3.4% / ‑7.0%) is the robust part. The 12‑month drift (+7.5% / ‑11.0%) is **contested**: it is weighting‑dependent, subsample‑unstable, and substantially attributable to earnings drift.

### A6. Practical caveats

- **Sample is US exchange‑listed, largely 1960s–1990s; the payer base has since shrunk (Fama‑French 2001).** Event counts per year in the post‑2000 era are far smaller, so statistical power for a "drift" trade has fallen.
- **Equal‑ vs value‑weighting matters enormously** (Boehme & Sorescu 2002). Equal‑weighted long/short is heavily exposed to microcaps and to bid‑ask bounce.
- **Confounded with earnings announcements.** Much of the apparent dividend drift is post‑earnings‑announcement drift (Liu et al. 2008). If you screen dividend events you must control for contemporaneous earnings surprise.
- **Sector/regulatory:** financials and utilities have structurally different payout regimes; Fama & French exclude them in the disappearing‑dividends work.

### A7. XBRL/iXBRL computability

Event detection is straightforward from the annual/interim XBRL dividend facts. The **event date** is *not* in XBRL — you need the declaration/payment date from the filing (`dei:DocumentPeriodEndDate` is a proxy only) or an external event feed.

| Input | Tag |
|---|---|
| DPS declared (per share, per class) | `us-gaap:CommonStockDividendsPerShareDeclared` |
| DPS declared, other classes | `us-gaap:CommonStockDividendsPerShareDeclared` + class member; also `us-gaap:PreferredStockDividendsPerShareDeclared` |
| Cash dividends paid (total) | `us-gaap:PaymentsOfDividends` |
| Cash dividends paid (common) | `us-gaap:PaymentsOfDividendsCommonStock` |
| Dividends declared (income statement) | `us-gaap:DividendsCommonStockCash` / `us-gaap:PaymentsOfDividendsCommonStock` (cash‑flow) |

Pitfall: `us-gaap:PaymentsOfDividends` includes preferred dividends; `us-gaap:PaymentsOfDividendsCommonStock` is the common‑only line and is the right input for common‑initiation/omission events. Some filers report a single blended `us-gaap:PaymentsOfDividends` line and disaggregate only in the statement of stockholders' equity, which is tagged with `us-gaap:DividendsCommonStockCash` in the equity roll‑forward.

**UNVERIFIED:** I attempted to confirm these element names against SEC's live XBRL frames API (`data.sec.gov/api/xbrl/companyconcept/...`) four times in this session and received **HTTP 403 "Undeclared Automated Tool"** on every attempt. The tag names above are therefore stated from standard US‑GAAP taxonomy naming, **not** independently verified in this session. Before production use, resolve each tag against the SEC frames API with a declared User‑Agent, or against the current FASB US‑GAAP taxonomy.

---

## B. Dividend yield trap / high yield predicts LOW returns

### B1. Marker name, definition, formula

**Dividend‑yield trap.** The hypothesis that high trailing dividend yield (a) is a *value trap* — the high yield is a price‑decline artifact / distress signal rather than a return premium — and (b) predicts **low or negative** subsequent returns. Inputs:

- `DividendYield_t = DPS_{t-1} / P_t` (trailing) or indicated forward yield
- `PayoutRatio_t = DPS_t / EPS_t`
- `PayoutYield_t = (Dividends + NetRepurchases) / MarketCap`

This is the marker where the **evidence is genuinely mixed and the sign flips by era and by measure** — which is the usable finding.

### B2/B3/B4. Originating evidence and exact numbers

**(i) The original predictive result was POSITIVE, not negative.**
Fama & French (1988), *"Dividend yields and expected stock returns"*, Journal of Financial Economics 22(1): 3–25 — [OpenAlex record](https://api.openalex.org/works/doi:10.1016/0304-405X(88)90020-7). Sample: US, long‑horizon (multi‑decade) aggregate time series. **Exact regression coefficients and R² are UNVERIFIED** — OpenAlex returned a null abstract and I did not retrieve the paper body. The title and the literature consensus it established is that high aggregate dividend yield forecasts high expected returns.

**(ii) The positive predictability fails out‑of‑sample after the 1970s.**
Goyal & Welch (2008), *"A Comprehensive Look at the Empirical Performance of Equity Premium Prediction"*, Review of Financial Studies 21(4): 1455–1508 — [OpenAlex record](https://api.openalex.org/works/doi:10.1093/rfs/hhm014). Verbatim abstract:
> "We find that **many and large** of these models predicted **poorly both in‑sample (IS) and out‑of‑sample (OOS) for 30 years now**; these models seem **unstable** … and large … would **not have helped** an investor with access only to available information to profitably time the market."
Dividend yield is one of the canonical predictor variables in that horse race. This is the strongest single citation for "the dividend‑yield‑return relation weakened or turned unhelpful post‑1980s", though the paper is a joint test of many predictors and does not isolate a dividend‑yield‑only coefficient.

**(iii) Payout yield dominates dividend yield.**
Boudoukh, Michaely, Richardson & Roberts (2007), *"On the Importance of Measuring Payout Yield: Implications for Empirical Asset Pricing"*, Journal of Finance 62(2): 877–915 — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/j.1540-6261.2007.01226.x). Verbatim abstract:
> "We find statistically and economically significant predictability in the **time series when payout yield** (dividends plus repurchases) … **[is] used instead of** [dividend] yield. Similarly, we find that **(net payout) yield** contains information about the **cross section of expected stock returns exceeding** [that of dividend] yields, and … **high minus low payout portfolio is a priced factor**."
Implication for the marker: **dividend yield alone is a noisy/incomplete payout measure**; gross buybacks and net issuance are where the return information sits. Exact factor premia (basis points/month) are **UNVERIFIED** (not in the retrieved abstract).

**(iv) The mechanism that CAN make high yield predict LOW returns: the "free dividends fallacy".**
Hartzmark & Solomon, *"The Dividend Disconnect"*, Journal of Finance 74(5), Oct 2019; NBER conference draft retrieved — [NBER conference PDF](http://www2.nber.org/conferences/2017/BFs17/Hartzmark_Solomon.pdf), plus the [CFA Institute Research Foundation summary](https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4).

Verbatim from the retrieved draft:
> "Demand for dividends is systematically higher in periods of low interest rates and poor market performance, **leading to high valuations and lower future returns for dividend‑paying stocks**."
> "We regress this return gap on the difference in book‑to‑market ratios between dividend‑paying and non‑dividend‑paying firms. We find a **coefficient of 0.225 with a t‑statistic of 2.16** (with Newey West standard errors with a 12 month lag)."
> "a decrease of **0.1 is associated with expected returns of 2.3% lower** over the next twelve months and **0.2 is associated with expected returns about 4.6% lower**."
> "the costs of buying dividend‑paying stocks when dividend demand is especially high could lead to **lower expected returns of roughly 2–4% over the next year**, a substantial fraction of the equity premium itself."
Additional retrieved magnitudes from the same draft:
- Interim‑period (announcement→ex‑day) return regression on dividend change: **coefficient 0.0313** → "for every penny of additional dividends the interim period return increases by **3 basis points**".
- "consistently paying at least the same dividend amount over the prior year is associated with a higher interim period return by **12–13 basis points**".
- Market‑wide: "a day in the highest week of dividend payouts in a given year is associated with higher daily value‑weighted market returns of **16 basis points** (compared to a mean daily market return of **4 basis points**)".
- Dividend reinvestment by institutions/mutual funds is rare: "**2.3% as common as zero holdings changes for the case of mutual funds, and 9.6% as common for institutional investors**"; exact‑reinvestment probability **0.719%** (mutual funds) and **1.17%** (institutions).
The CFA Institute summary adds:
> "They find a correlation of **–0.50** between daily prices and dividend yields for individual stocks. … For dividend‑paying stocks, mutual funds demonstrate a **1.1% lower disposition effect**. Institutions display a **0.7% lower disposition effect**."
> "As a result, total return can be **2%–4% lower over the next year**."

**(v) Low‑quality emerging‑market "dividend trap" papers exist but are weak evidence.**
- Oktaviani Putri & Wijayanti (2025), *"The Effect of Dividend Yield, Dividend Payout Ratio, and Stock Volume on the Dividend Trap in IDXHIDIV20"* — [OpenAlex record](https://api.openalex.org/works?search=dividend%20yield%20trap). Sample: **IDXHIDIV20, 2023**, panel regression, Eviews 12. Abstract: "DY has a **negative significant effect** on dividend traps, while DPR and stock volume show **no** [significant] effect." Single country, one year, tiny N.
- Natalia & Kohardinata (2024), *"Dividend Trap: Impact of Yield, Volume, and Payout on Investments"* — **223 observations, 2022–2023**, panel regression in Stata 13. Abstract reports a **positive significant** effect of dividend yield and stock volume on the trap, and a **negative** effect of payout ratio. **Note this contradicts the other 2025 paper** — a useful illustration of how unstable this literature is.
These are single‑paper, short‑window, emerging‑market findings: **classification (b) single‑paper findings**, and mutually contradictory.

### B5. Held up?

- Dividend yield as a **positive** predictor: **weakened/failed OOS** (Goyal & Welch 2008).
- Dividend yield as a **negative** predictor via demand‑driven overvaluation: **single‑paper finding** (Hartzmark & Solomon 2019), with a reported t‑stat of 2.16 on the key coefficient — significant but not overwhelming.
- "Payout yield beats dividend yield": **reasonably robust, replicated direction** in the asset‑pricing literature; the JF paper is the canonical reference (Boudoukh et al. 2007).
- Emerging‑market "dividend trap" regressions: **contested / mutually contradictory**.

### B6. Practical caveats

- **Trailing vs indicated yield** are different variables and are not interchangeable; different papers use different definitions, which is a large part of why results conflict.
- **Dividends vs total payout**: buybacks now dominate US payout. A dividend‑yield‑only screen misses net issuance (Boudoukh et al. 2007).
- **Sector concentration**: high‑yield screens load on utilities, REITs, consumer staples, tobacco, financials — results are substantially a sector bet.
- **Tax and rate regime**: the demand‑for‑dividends channel (Hartzmark & Solomon) is explicitly conditioned on interest rates and recent market returns, so any "high yield underperforms" result is regime‑dependent.
- **Survivorship**: high‑yield screens that exclude cutters embed look‑ahead bias; the trap only bites ex post.

### B7. XBRL computability

| Input | Tag |
|---|---|
| DPS declared (trailing annual) | `us-gaap:CommonStockDividendsPerShareDeclared` |
| Dividends paid | `us-gaap:PaymentsOfDividendsCommonStock`, `us-gaap:PaymentsOfDividends` |
| Net income | `us-gaap:NetIncomeLoss` |
| Earnings per share | `us-gaap:EarningsPerShareBasic`, `us-gaap:EarningsPerShareDiluted` |
| Share repurchases | `us-gaap:PaymentsForRepurchaseOfCommonStock` |
| Equity issuances | `us-gaap:ProceedsFromIssuanceOfCommonStock` |
| Market cap | **Not an XBRL tag.** Needs month‑end close × `dei:EntityCommonStockSharesOutstanding` (cover page) — but cover‑page share counts are point‑in‑time and require the filing date, not period end. |
| Retail / institutional ownership (for the Hartzmark‑Solomon demand proxy) | **Not available in XBRL.** Requires 13F (institutional) or proprietary retail data. |

The biggest practical blocker: **price is not in XBRL**. Yield markers require joining XBRL payout facts to a price/market‑cap series.

---

## C. Dividend growth / dividend aristocrats and the information content of dividends

### C1. Marker name, definition, formula

**Dividend growth / streak marker.** A firm qualifies on the *consecutive‑years of maintained‑or‑increased* dividend criterion, then is weighted by indicated annual dividend yield.

- `Streak_t = number of consecutive fiscal years with DPS_f ≥ DPS_{f-1}`
- `DividendGrowth_f = DPS_f / DPS_{f-1} − 1`
- `IndicatedYield = (MostRecentDividend × NPayments) / Price` — explicitly defined as a *forward* yield, **not an analyst forecast**

### C2. Originating methodology

**S&P Dow Jones Indices** Dividend Aristocrats index family. The primary S&P DJI methodology PDF is **behind a 403 block** — `https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-dividend-aristocrats-indices.pdf` returned *"Access Denied … Reference #18.26c83017"* through the text proxy. **So the S&P DJI primary methodology is UNVERIFIED in this session.**

The construction rules below are, however, retrieved verbatim from an S&P‑DJI‑sourced third party document: State Street Global Advisors, *"SPDR Dividend Aristocrats strategies"* — [SSGA PDF](https://www.ssga.com/library-content/story/general/etf/emea/spdr-index-overview-dividend-aristocrats.pdf), which states "Source: S&P Dow Jones Indices as of January 2024".

### C3. Sample / construction rules (retrieved verbatim)

| Region | Selection universe | Min FMC / DVT / stability screen | Years / count | Reconstitution |
|---|---|---|---|---|
| USA | S&P Composite 1500 | $2bn / $5mn | **20+ years** / floating | quarterly (Jan.) |
| Eurozone | S&P Eurozone BMI | $1bn / $5mn / +EPS, 100% max payout, 10% max yield | **10+ years** / 40 stocks | quarterly (Jun.) |
| UK | S&P United Kingdom BMI | $1bn / $5mn / +EPS, 100% max payout, 10% max yield, +CF | **7+ years** / 40 stocks | quarterly (Jun.) |
| Global | S&P Global BMI | $1bn / $5mn / +EPS, 100% max payout, 10% max yield, +CF | **10+ years** / 100 stocks | semi‑annual (Jan.) |
| Pan Asia | S&P Pan Asia | $1bn / $3mn / +EPS, 100% max payout, 10% max yield | **7+ years** / 40–100 stocks | quarterly (Jan.) |
| EM | S&P EM Plus Large MidCap | no min / $2bn / +EPS, 100% max payout, 10% max yield | **5+ years** / floating (50 min) | semi‑annual (Jun.) |

Caps: e.g. Global 3% stock / 25% sector / ±10% country; EM 7.5% stock / ±10% sector / ±10% country. Weighting: **"Weight by indicated annual dividend yield, subject to Stock, Sector and Country exposure caps at rebalance."** Indicated yield "is computed as the **(Most recent dividend × number of dividend payments)/Stock Price**. It is not an analyst forecast but reflects a forward dividend yield."

Note the **100% max payout and 10% max yield screens** — these are the design's explicit guard against the yield trap in Marker B.

### C4. Reported effect sizes

**S&P Dow Jones Indices (Cheng & Srivastava), *"A Case for Dividend Growth Strategies"*, 2017**, retrieved via [Institutional Investor sponsored report](https://www.institutionalinvestor.com/article/2bsw1z1mtkf0f7vwxe4n4/innovation/a-case-for-dividend-growth-strategies). Verbatim:

> "Looking at the period from **Dec. 31, 1999, to Sept. 30, 2016**, when the market (as represented by the S&P Composite 1500 was down, the S&P High Yield Dividend Aristocrats outperformed the S&P Composite 1500, and the S&P 500 High Dividend Index by an average of **165 bps per month and 54 bps per month**, respectively."

> "While the hurdle for inclusion in the S&P High Yield Dividend Aristocrats index inclusion is **20 straight years** of increasing dividends, the index average is **34.5 years**. Additionally, there are **eight constituents with over 53 consecutive years** of dividend increases."

> "the performance of dividend growers is less driven by the value factor compared with the high dividend payers … unlike many pure yield strategies, which tend to be concentrated in sectors like utilities, consumer staples, and financials, dividend growth strategies tend to be **more diversified across sectors**."

**Caveat on this source:** this is S&P DJI research distributed as **sponsored content** in a trade publication. It reports conditional (down‑month) returns only, not full‑period risk‑adjusted alphas; no t‑statistics, no factor regressions are given in the retrieved text. Treat as marketing‑adjacent. **Classification: single‑source, vendor‑originated, unrefereed.**

### C5/C6. Information content of dividends — the academic core, with exact numbers

**(a) Benartzi, Michaely & Thaler (1997), *"Do Changes in Dividends Signal the Future or the Past?"*, Journal of Finance 52(3): 1007–1034** — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/j.1540-6261.1997.tb02723.x). Verbatim abstract:
> "we find **only limited support** for it. Firms that increase dividends in year 0 experienced significant increases in earnings in **years −1 and 0**, but show **no subsequent unexpected growth**. Also, the size of the dividend change **does not predict** earnings. **Cut** [firms] in year 0 … a reduction in [earnings in] year −1 … these firms go on to [experience] significant increases [in earnings] [in years] **1** [and later]. However, consistent with Lintner's model … firms that increase dividends are **less likely** than nonchanging firms to experience a **drop** in [earnings] … Thus, their concurrent [earnings increases] can be said to be **somewhat 'permanent.'** In spite of the lack of [earnings] growth, [there are] (though **modest**) **positive excess returns following three years**."
**Reading:** dividends are a *lagging* indicator. The significant earnings information is about the past and the present, not the future.

**(b) Nissim & Ziv (2001), *"Dividend Changes and Future Profitability"*, Journal of Finance 56(6)** — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/0022-1082.00400). Verbatim abstract:
> "Supporting 'the information content of dividends hypothesis,' we find that **dividend changes provide [information] about the level of profitability in subsequent years, incremental to market and accounting data**. [We] also document that [dividend changes] are **positively related** [to earnings changes] in each of the **two years after** the [dividend] change."
**Exact coefficients are UNVERIFIED.** The OpenAlex abstract contains no numbers, and I could not retrieve the paper body (Wiley 403, SSRN 403, Columbia Business School page 403). **Missing: the year t+1 and t+2 regression coefficients on dividend change, the earnings‑change specification, the sample period, and N.** Anyone quoting a specific Nissim‑Ziv coefficient should be required to produce the table.

**(c) The direct failure‑to‑replicate: Grullon, Michaely, Benartzi & Thaler (2005), *"Dividend Changes Do Not Signal Changes in Future Profitability"*, Journal of Business 78(5): 1659–1682** — [OpenAlex record](https://api.openalex.org/works/doi:10.1086/431438). The retrieved OpenAlex record returns only a title‑citation block, **no abstract**. **The paper's exact coefficients are UNVERIFIED here.** What is verified is the existence, venue, volume, pages, authors and date of a paper whose title is an explicit rejection of the Nissim & Ziv result — the standard citation for "the Nissim‑Ziv effect does not survive."

**(d) Grullon, Michaely & Swaminathan (2002), *"Are Dividend Changes a Sign of Firm Maturity?"*, Journal of Business 75(3): 387–424** — [OpenAlex record](https://api.openalex.org/works?search=Are%20Dividend%20Changes%20a%20Sign%20of%20Firm%20Maturity). Verbatim abstract:
> "Firms that increase (decrease) dividends experience a **significant decline (increase) in their systematic risk**. The dividend‑increasing firms **do not** [increase] capital expenditure and [do not increase] profitability in the years after the dividend change. The positive market reaction to [dividend increases] is **significantly related to the subsequent decline in systematic risk**. In the long run, dividend‑increasing firms with the **largest declines in systematic risk also price [increase] the most over the next three years**, suggesting [that] dividend changes may [not] incorporate the full extent of [the change in] cost of capital associated with [the] dividend changes."
**Interpretation:** the dividend increase is a *maturity* signal (falling beta, falling growth options), not a profitability signal.

**(e) DeAngelo, DeAngelo & Skinner (1996), *"Reversal of fortune: dividend signaling and the disappearance of sustained earnings growth"*, Journal of Financial Economics 40(3): 341–371** — [Semantic Scholar record](https://r.jina.ai/https://www.semanticscholar.org/paper/Reversal-of-fortune-dividend-signaling-and-the-of-DeAngelo-Deangelo/b3ced7305e39cbf146e15f57f4f4b2a69e222155). Verbatim:
> "Managers of **more than two‑thirds of 145 NYSE firms** responded to stalled earnings growth by **increasing dividends**, with most increases **at least as large as the dividend increase in the peak earnings year**. These dividend increases are difficult to reconcile with signalling models since (i) most firms' prior sustained earnings growth **evaporated**, and (ii) there is **essentially no relation** between favorable dividend signals and future earnings. The stock market recognized the reduced growth earnings…"
This is the cleanest statement that **dividend increases in a deteriorating earnings environment are not a growth signal**.

**(f) Ham, Kaplan & Utke (2021), *"Attention to dividends, inattention to earnings?"*, Review of Accounting Studies 28(1): 265–306** — [OpenAlex record](https://api.openalex.org/works/doi:10.1007/s11142-021-09642-4). Verbatim abstract:
> "**dividend paying firms have 11%–15% lower** [earnings‑response] **coefficients (ERCs)** than non‑payers."
> "We [find] more substitution when **the dividend is less likely to be cut**, [when] the firm **funds the dividend out of [cash] reserves rather than [operating cash flow]**, and [when] the **larger** [is the] dividend…"
> "**dividend payers have [lower] absolute returns, [lower] trading volume, and fewer analyst forecasts** at [the] earnings announcement (EA) … **[and] show [less] attention to their less informative EAs.**"
Also retrieved from the same record: dividend sustainability *is* predictable out of sample (Hobbs & Schneller abstract, above).

### C7. Practical caveats

- **Streak definitions differ materially**: 5 / 7 / 10 / 20 years by region (SSGA table above). A "dividend aristocrat" in EM is a 5‑year streak; in the US it is 20+.
- **Total‑return mixes with yield trap**: weighting by indicated yield re‑introduces yield‑trap exposure, partially mitigated by the 100% max payout / 10% max yield screens.
- **Backfill / survivorship**: the streak requirement is applied at reconstitution; the *announced* streak is a past fact, but index history is constructed with contemporaneous constituents only if the vendor publishes point‑in‑time membership. Whether S&P DJI membership files are point‑in‑time is **UNVERIFIED**.
- **Vendor‑report bias**: the 165 bps/month figure is conditional on down months and comes from S&P DJI's own sponsored report; no risk‑adjusted alpha or t‑stat is given.
- **Accounting‑standard issue**: "+EPS" and "100% max payout" screens require consistent EPS across jurisdictions (IFRS vs US GAAP), and EPS can be negative, making payout ratios meaningless or sign‑flipped.

### C8. XBRL/iXBRL computability

| Input | Tag |
|---|---|
| DPS declared per year (streak) | `us-gaap:CommonStockDividendsPerShareDeclared` |
| DPS paid per year | `us-gaap:CommonStockDividendsPerSharePaid` |
| Dividends declared (total) | `us-gaap:DividendsCommonStockCash` |
| Net income (for payout screen) | `us-gaap:NetIncomeLoss` |
| EPS (for +EPS screen) | `us-gaap:EarningsPerShareBasic`, `us-gaap:EarningsPerShareDiluted` |
| Free cash flow components | `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` |

Streaks require **at least 20 fiscal years of history per firm** for the US index — XBRL structured data only starts ~2009 for large filers (SEC phase‑in 2009–2011), so **a 20‑year US aristocrat screen cannot be built from XBRL alone**. You must back‑fill from pre‑XBRL filings (parsed text) or a vendor dividend history file. This is a hard, practical data limitation, not a rounding issue.

---

## D. Payout ratio sustainability markers

### D1. Marker name, definition, formula

**Payout sustainability / dividend‑cut risk markers.** A family of scalar screens for whether the current dividend can be maintained:

- `PayoutRatio = DPS / EPS` (or `DividendsPaid / NetIncome`)
- `DividendCoverage = NetIncome / DividendsPaid`
- `FCFCoverage = (CFO − Capex) / DividendsPaid` — the key one; below 1.0 means the dividend is not covered by internally generated free cash flow
- `DebtFundedDividend = 1 if (CFO − Capex) < DividendsPaid` (financed from balance sheet / issuance)
- `RetainedEarningsToAssets = RetainedEarnings / TotalAssets` (Altman‑style distress input)

### D2/D3/D4. Originating studies and exact numbers

**(a) DeAngelo & DeAngelo (1990), *"Dividend Policy and Financial Distress: An Empirical Investigation of Troubled NYSE Firms"*, Journal of Finance 45(5): 1415–1431** — [OpenAlex record](https://api.openalex.org/works/doi:10.1111/j.1540-6261.1990.tb03721.x). Verbatim abstract:
> "This paper studies the dividend policy adjustments of **80 NYSE firms** to protracted financial distress as evidenced by **multiple losses during 1980–1985**. **Almost all sample firms reduced dividends**, and **more than half apparently faced binding debt covenants** in years they did so. Absent debt covenants, dividends are **cut [less] often [than] omitted**, suggesting that **managerial reluctance is [greatest for] the omission** and not simply [for] the reduction of dividends. Moreover, managers **with long dividend histories appear particularly reluctant to omit dividends.** Finally, some reductions seem **strategically motivated**, e.g., designed to **enhance the firm's bargaining position with organized labor**."

**(b) DeAngelo, DeAngelo & Skinner (1992), *"Dividends and Losses"*, Journal of Finance 47(5)** — retrieved via [Semantic Scholar citation record](https://r.jina.ai/https://www.semanticscholar.org/paper/Reversal-of-fortune-dividend-signaling-and-the-of-DeAngelo-Deangelo/b3ced7305e39cbf146e15f57f4f4b2a69e222155). Verbatim:
> "An annual loss is essentially a **necessary condition for dividend reductions** in firms with established earnings and dividend records: **50.9 percent of 167 NYSE firms with losses during 1980–85 reduced** [dividends]…"
That 50.9% of 167 loss‑making NYSE firms cut is the single most concrete "cut predictor" number I retrieved: **the loss itself is the trigger**.

**(c) Gunasekarage, Hess & Power (2015), *"Financial Profiles, Dividends and Stock Returns"*, International Journal of Banking and Finance 11: 31–53** — [OpenAlex record](https://api.openalex.org/works/doi:10.32890/ijbf2014.11.2). This is a directly usable **predictive logit** design. Verbatim:
> "First, a **logit model** is developed to predict **one year‑ahead changes in dividends**. Second, the **buy‑and‑hold returns** for a trading strategy based on [those] dividend forecasts are calculated. [The logit] has **some success in predicting future [dividend] changes**. However, attempts to exploit these predictions **proved unsuccessful**; buying (selling) shares where dividends were predicted to increase (decrease) would earn [a] **negative abnormal return of −2.34% over 24 months**. This [is one of the] first studies to forecast [dividend] changes [in a] sample of **New Zealand** companies using [financial statement] data … "
So: **a financial‑statement‑based dividend‑change model works statistically but is not tradable** (‑2.34% over 24 months buying predicted increasers). Sample: New Zealand, single country.

**(d) Lie (2005), *"Operating performance following dividend decreases and omissions"*** — retrieved via the same Semantic Scholar citation record. Verbatim:
> "Using quarterly data and benchmarks based on past performance characteristics, I find **little evidence that earnings change following 661 dividend decreases and 484 dividend omissions** between…"
Exact sample years and coefficient magnitudes are **UNVERIFIED** (truncated abstract).

**(e) Das & Dhole (2024), *"Dividend cuts and a firm's investment opportunity set"*, Journal of Business Finance & Accounting 52(1): 91–126** — [OpenAlex record](https://doi.org/10.1111/jbfa.12801). Verbatim abstract:
> "despite the documented **average negative market response**, **many dividend‑cutting firms experience a positive [market] response**. We … document that the [market] responds **positively** to dividend cuts **when [the] firms have positive investment opportunity sets.**"
> "dividend‑cutting [firms] in the presence of investment opportunities do make **significant investments such as capital expenditures and merger and acquisition activities in future years**. Furthermore, we also find that **operating profitability is higher for dividend‑cutting firms with relatively [high] investment opportunities.**"
> "among [dividend‑cutting] firms, there is a **statistically significant difference in buy‑and‑hold returns up to 2 years, between [firms with] high versus low [investment opportunity sets]**."
Interpretation: **a dividend cut is not unconditionally a distress marker** — it is a signal whose sign depends on whether the retained cash is reinvested at positive NPV. This materially weakens simple "cut = sell" rules.

### D5. Held up?

- **Loss precedes cut** (DeAngelo/DeAngelo 1990, 1992; 80 and 167 NYSE firms, 1980–85): **robust for its sample**, but the sample is small, US‑only, and hand‑collected from a specific distressed cohort. Out‑of‑sample extension to modern large‑cap non‑distressed firms is **UNVERIFIED**.
- **Financial‑statement‑based cuts are predictable but not profitable** (Gunasekarage et al.: −2.34% over 24 months): **single‑paper, single‑country**, but an unusually honest negative result that should temper any "cut‑prediction alpha" pitch.
- **Cut sign depends on investment opportunities** (Das & Dhole 2024): **recent single‑paper finding**, in a good journal; not yet widely replicated.
- **Dividends are a lagging indicator** (Benartzi/Michaely/Thaler 1997): **robust and repeatedly cited**; the informational content is about the past.

### D6. Practical caveats

- **Payout ratio is undefined or sign‑flipped when EPS ≤ 0.** Nearly all distressed firms have negative EPS, which is exactly when you most want the screen. Use `DividendsPaid / CFO` or `DividendsPaid / FCF` instead, and handle negative denominators explicitly.
- **One‑off items inflate or deflate both EPS and CFO.** Asset impairments depress EPS (raising payout ratio) without affecting cash; working‑capital swings distort CFO. A single‑year payout ratio is very noisy.
- **Dividends on preferred stock** contaminate `us-gaap:PaymentsOfDividends`. Use the common‑only tag.
- **Share buybacks** are the other half of payout; a firm with a "safe" dividend may be returning far more cash via repurchases.
- **IFRS vs US GAAP**: cash‑flow statement classification (interest paid, dividends received) differs, so cross‑border payout coverage comparisons are not apples‑to‑apples.
- **Debt‑covenant interaction** (DeAngelo & DeAngelo 1990): the *timing* of a cut is often set by the covenant, not by economics — so a cut can be a technical trigger rather than new information.
- **Interim frequency**: most US and EU firms declare dividends quarterly or semi‑annually. Using only annual XBRL facts misses intra‑year cuts and accelerations.

### D7. XBRL/iXBRL computability

| Marker input | Tag | Notes |
|---|---|---|
| Dividends paid (common) | `us-gaap:PaymentsOfDividendsCommonStock` | Cash‑flow statement; common only |
| Dividends paid (all) | `us-gaap:PaymentsOfDividends` | Includes preferred |
| Dividends declared (equity roll‑forward) | `us-gaap:DividendsCommonStockCash` | Statement of stockholders' equity |
| DPS declared | `us-gaap:CommonStockDividendsPerShareDeclared` | Typically per share per quarter/period; must be annualised |
| Net income | `us-gaap:NetIncomeLoss` | Income statement |
| Net income available to common | `us-gaap:NetIncomeLossAvailableToCommonStockholdersBasic` | Needed when preferred dividends exist |
| EPS | `us-gaap:EarningsPerShareBasic`, `us-gaap:EarningsPerShareDiluted` | Denominator for payout ratio |
| Operating cash flow | `us-gaap:NetCashProvidedByUsedInOperatingActivities` | CFO |
| Capex | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` | Also `us-gaap:PaymentsToAcquireProductiveAssets` for some filers |
| Free cash flow proxy | derived: CFO − Capex | FCF is **not** a standard tag; must be computed |
| Retained earnings | `us-gaap:RetainedEarningsAccumulatedDeficit` | Distress input |
| Stockholders' equity | `us-gaap:StockholdersEquity` | Distress input; also `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| Total assets | `us-gaap:Assets` | Distress input |
| Long‑term debt | `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebt` | Debt‑funded‑dividend detection |
| Debt issuance proceeds | `us-gaap:ProceedsFromIssuanceOfLongTermDebt` | Pairs with the above to test debt‑funded payout |

**FCF coverage construction:** `FCFCoverage = (us-gaap:NetCashProvidedByUsedInOperatingActivities − us-gaap:PaymentsToAcquirePropertyPlantAndEquipment) / us-gaap:PaymentsOfDividendsCommonStock`.

**Debt‑funded‑dividend flag:** `((CFO − Capex) < DividendsPaid)` **and** `us-gaap:ProceedsFromIssuanceOfLongTermDebt > 0` in the same period.

**Again UNVERIFIED:** the SEC XBRL frames/companyconcept endpoints were **403‑blocked** on all four attempts in this session. Confirm each element against the current FASB US‑GAAP taxonomy before wiring a pipeline.

---

## Bottom line — what is actually usable

| Marker | Robustness | The number to carry forward |
|---|---|---|
| A. Initiation/omission **announcement** reaction | **Robust** | +3.4% / ‑7.0% 3‑day (MTW 1995) |
| A. Initiation/omission **12‑month drift** | **Contested** | +7.5% / ‑11.0% sign‑flipped by value weighting (Boehme & Sorescu 2002) and largely earnings drift (Liu et al. 2008) |
| B. High dividend yield → low returns | **Mixed / regime‑dependent** | 2–4% lower next‑year return when dividend demand is high (Hartzmark & Solomon; coefficient 0.225, t = 2.16) |
| B. Dividend yield as **aggregate** predictor | **Failed OOS** | Goyal & Welch 2008: "predicted poorly … for 30 years now" |
| B. Payout yield > dividend yield | **Reasonably robust** | Boudoukh et al. 2007 |
| C. Dividends signal the **future** | **Largely rejected** | Benartzi‑Michaely‑Thaler 1997, DeAngelo‑DeAngelo‑Skinner 1996, Grullon‑Michaely‑Benartzi‑Thaler 2005 |
| C. Dividends signal **firm maturity / falling beta** | **Supported** | Grullon‑Michaely‑Swaminathan 2002 |
| C. Dividend‑growth index defensive edge | **Vendor‑originated, unrefereed** | 165 bps/month in down months vs S&P 1500, Dec 1999–Sep 2016 |
| D. Loss precedes dividend cut | **Robust for its sample** | 50.9% of 167 loss‑making NYSE firms cut (DDS 1992) |
| D. Cut prediction from financials is **tradable** | **Explicitly rejected** | −2.34% over 24 months (Gunasekarage et al. 2015) |
| D. Cut sign depends on investment opportunities | **Single recent paper** | Das & Dhole 2024 |

### What remains UNVERIFIED and must be obtained before any production model

1. **Nissim & Ziv (2001) exact regression coefficients, sample period and N** — abstract retrieved, numbers not.
2. **Grullon, Michaely, Benartzi & Thaler (2005) exact coefficients** — citation verified, abstract not retrieved.
3. **Michaely, Thaler & Womack (1995) full sample (period, N of initiations/omissions)** — the NBER PDF returned empty through the proxy.
4. **Fama & French (1988) dividend‑yield regression coefficients and R².**
5. **Boehme & Sorescu (2002) exact abnormal return magnitudes** — abstract is qualitative.
6. **Fama & French (2001) payer proportions** (the "66.5% → 20.8%" figures).
7. **S&P DJI primary methodology document** — spglobal.com returns 403 to automated retrieval.
8. **SEC XBRL element verification** — data.sec.gov returns 403 without a declared User‑Agent.
9. **Post‑publication decay estimates (McLean‑Pontiff style) for these specific markers** — not searched, not retrieved.

---

## SOURCES FETCHED

Every URL below was successfully retrieved in this session and returned usable content. URLs that returned HTTP 403/429/404 or empty bodies are **not** listed here and are referred to as UNVERIFIED where relevant.

**Primary / near‑primary paper records**

1. https://www.nber.org/papers/w4778 — Michaely, Thaler & Womack, NBER WP 4778 / JF 1995 abstract
2. https://api.openalex.org/works/doi:10.1111/j.1540-6261.1997.tb02723.x — Benartzi, Michaely & Thaler (1997) JF 52(3)
3. https://api.openalex.org/works/doi:10.2307/2329514 — duplicate record of Benartzi, Michaely & Thaler (1997)
4. https://api.openalex.org/works/doi:10.1111/0022-1082.00400 — Nissim & Ziv (2001) JF 56(6)
5. https://api.openalex.org/works?search=Are%20Dividend%20Changes%20a%20Sign%20of%20Firm%20Maturity — Grullon, Michaely & Swaminathan (2002) JB 75(3)
6. https://api.openalex.org/works/doi:10.1086/431438 — Grullon, Michaely, Benartzi & Thaler (2005) JB 78(5)
7. https://api.openalex.org/works?search=Reversal%20of%20fortune%20dividend%20signaling%20disappearance%20sustained%20earnings%20growth — DeAngelo, DeAngelo & Skinner (1996) JFE 40(3) + Hobbs & Schneller (2012) record
8. https://r.jina.ai/https://www.semanticscholar.org/paper/Reversal-of-fortune-dividend-signaling-and-the-of-DeAngelo-Deangelo/b3ced7305e39cbf146e15f57f4f4b2a69e222155 — DDS (1996) abstract, DeAngelo/DeAngelo/Skinner (1992) "Dividends and Losses", Lie (2005)
9. https://api.openalex.org/works/doi:10.1111/j.1540-6261.1990.tb03721.x — DeAngelo & DeAngelo (1990) JF 45(5)
10. https://api.openalex.org/works/doi:10.1111/1540-6261.00445 — Boehme & Sorescu (2002) JF 57(2)
11. https://api.openalex.org/works/doi:10.1111/j.1540-6261.2008.01337.x — Liu, Szewczyk & Zantout (2008) JF 63(2)
12. https://api.openalex.org/works/doi:10.1080/09603107.2012.654909 — Hobbs & Schneller (2012) Applied Financial Economics 22(17)
13. https://api.openalex.org/works/doi:10.1111/jbfa.12801 — Das & Dhole (2024) JBFA 52(1)
14. https://api.openalex.org/works/doi:10.1007/s11142-021-09642-4 — Ham, Kaplan & Utke (2021) Review of Accounting Studies 28(1)
15. https://api.openalex.org/works/doi:10.32890/ijbf2014.11.2 — Gunasekarage, Hess & Power (2015) IJBF 11

**Dividend‑yield / payout / predictability**

16. https://api.openalex.org/works/doi:10.1016/0304-405X(88)90020-7 — Fama & French (1988) JFE 22(1)
17. https://api.openalex.org/works/doi:10.1016/S0304-405X(01)00038-1 — Fama & French (2001) JFE 60(1)
18. https://api.openalex.org/works/doi:10.1111/j.1540-6261.2007.01226.x — Boudoukh, Michaely, Richardson & Roberts (2007) JF 62(2)
19. https://api.openalex.org/works/doi:10.1093/rfs/hhm014 — Goyal & Welch (2008) RFS 21(4)
20. https://api.openalex.org/works/doi:10.1111/j.1540-6261.2004.00658.x — Baker & Wurgler (2004) JF 59(3)
21. https://api.openalex.org/works?search=dividend%20yield%20trap%20high%20dividend%20yield%20lower%20future%20returns — Oktaviani Putri & Wijayanti (2025); Natalia & Kohardinata (2024); Achmad et al. (2026)
22. https://api.openalex.org/works?search=Unsustainable%20dividends%20drift — Ham/Kaplan/Utke and related records

**Dividend disconnect / behavioural demand**

23. https://r.jina.ai/http://www2.nber.org/conferences/2017/BFs17/Hartzmark_Solomon.pdf — Hartzmark & Solomon, "The Dividend Disconnect" (NBER conference draft, March 2017)
24. https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4 — CFA Institute Research Foundation summary of Hartzmark & Solomon (JF 74(5), 2019)

**Index methodology and dividend growth**

25. https://www.ssga.com/library-content/story/general/etf/emea/spdr-index-overview-dividend-aristocrats.pdf — SPDR Dividend Aristocrats strategies (S&P DJI construction rules as of Jan 2024)
26. https://www.institutionalinvestor.com/article/2bsw1z1mtkf0f7vwxe4n4/innovation/a-case-for-dividend-growth-strategies — S&P DJI (Cheng & Srivastava), "A Case for Dividend Growth Strategies", 2017

**Failed retrievals (recorded for audit — NOT evidence)**

- `https://www.nber.org/system/files/working_papers/w4778/w4778.pdf` — HTTP 200 but empty body via text proxy
- `https://onlinelibrary.wiley.com/doi/...` (multiple) — HTTP 403
- `https://papers.ssrn.com/sol3/papers.cfm?abstract_id=535462` — HTTP 403
- `https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-dividend-aristocrats-indices.pdf` — HTTP 403
- `https://www.spglobal.com/spdji/en/research/article/a-case-for-dividend-growth-strategies/` — HTTP 403
- `https://www.sciencedirect.com/science/article/abs/pii/0304405X95900850E` — HTTP 404 (wrong PII)
- `https://business.columbia.edu/faculty/research/dividend-changes-and-future-profitability` — HTTP 403
- `https://data.sec.gov/api/xbrl/companyconcept/...` (4 requests) — HTTP 403, undeclared automated tool
- `https://r.jina.ai/...` on Wiley/JSTOR — repeated HTTP 429 rate limiting
