# Accounting Red Flags for an EDGAR-XBRL / Companies House-iXBRL Equity Tool

**Source-grounded research brief.** Every substantive claim below carries a URL that was actually opened during this research (directly or through the `r.jina.ai` text proxy for bot-walled PDFs). Numbers are quoted from the source, not paraphrased from search snippets. Where full text was unreachable, the claim is marked **UNVERIFIED** with the reason. Where sources disagree, both are given.

Three corrections to the brief we were given:
1. **Doyle, Lundholm & Soliman (2003) is in *Review of Accounting Studies* 8(2–3):145–174, not the *Journal of Accounting and Economics*.** ([EconPapers](https://econpapers.repec.org/article/sprreaccs/v_3a8_3ay_3a2003_3ai_3a2_3ad_3a10.1023_5fa_3a1024472210359.htm), [OpenAlex W3121262606](https://api.openalex.org/works?filter=doi:10.1023/A:1024472210359))
2. **DeFond & Subramanyam (1998) is *Journal of Accounting and Economics* 25(1):35–67, not JAPP.**
3. **"Do auditor resignations reduce uncertainty about the quality of firms' financial reporting?" is by Beneish, Hopkins, Jansen & Martin (2005, *JAPP* 24(5):357–390) — not Carey & Simnett.** No Carey & Simnett paper with that title exists.

---

## 1. Goodwill impairment risk and serial-acquirer balance sheets

### 1.1 Plain-English definition and inputs

Goodwill = purchase price − fair value of identifiable net assets acquired. Under **ASC 350** (US, successor to SFAS 142, effective for acquisitions after 30 June 2001) and **IFRS 3 / IAS 36** goodwill is **not amortised**; it is tested for impairment at least annually. Impairment is recognised when the carrying amount of the reporting unit (or cash-generating unit) exceeds its recoverable/fair value.

Core signals for a tool:

```
GoodwillIntensity      = Goodwill / TotalAssets
IntangibleIntensity    = (Goodwill + IntangibleAssetsExcludingGoodwill) / TotalAssets
GoodwillToEquity       = Goodwill / StockholdersEquity
ImpairmentRate         = GoodwillImpairmentLoss / AverageGoodwill (or / TotalAssets)
AcquisitionIntensity   = PaymentsToAcquireBusinesses / TotalAssets   (rolling 3y)
GoodwillGrowth         = ΔGoodwill / TotalAssets                     (rolling 3y)
```

### 1.2 How often do impairments occur? (base rates)

**Kroll (2025 US Goodwill Impairment Study), calendar 2024, >8,000 US-listed companies** — [kroll.com (opened via text proxy)](https://www.kroll.com/en/publications/valuation/2025-us-goodwill-impairment-study):

- "In 2024, the total amount of goodwill impaired in the U.S. increased by approximately 16% from $83 billion to $96 billion."
- "The top ten impairments taken in the U.S. in 2024 totaled approximately $51 billion, which represented approximately 53% of total goodwill impaired in the U.S."
- 2024 impairments concentrated in Communication Services, Consumer Staples and Healthcare — "approximately 67% of the total goodwill impaired in the year."
- Kroll notes the FASB/IASB both retained the impairment-only model in 2022, IASB voted against revisiting it in Feb 2025.

**Kroll 2021 European Goodwill Impairment Study (STOXX Europe 600, 2016–2020)** — [kroll.com](https://www.kroll.com/en/publications/valuation/2021-european-goodwill-impairment-study): "Goodwill impairment rose 49% to €54.1 billion (bn) in 2020"; "the number of goodwill impairment events increased for a third consecutive year, rising from 126 in 2019 to 152 in 2020, or 21%"; average impairment per event €289m → €356m (+23%).

**Firm-level base rate, academic.** Hayn & Hughes — [UCLA working paper PDF](https://www.anderson.ucla.edu/documents/areas/fac/accounting/goodwill_06.pdf) (published as *Journal of Accounting, Auditing & Finance* 21(3):223–265, 2006):

- Sample: acquisitions **1988–1998**, acquirers tracked forward to 2001/2004; initial screen 2,852 acquisitions → final sample **1,276 acquisitions** after eliminating cases where the goodwill amount (38%) or its host segment (17.4%) could not be traced.
- **"of the 1,276 acquisitions in the final sample, 180 or 14.1% resulted in a write-off. Considering the 7,916 firm-year observations in the sample, the 180 write-offs represent a write-off frequency of 2.3% per year."**

**Gu & Lev (2011), *The Accounting Review* 86(6):1995–**, [NYU Stern PDF](https://pages.stern.nyu.edu/blev/accfin/Overpriced%20Shares,%20Ill-Advised%20Acquisitions,%20and%20Goodwill%20Impairment.pdf) footnote 2: "The number of firms reporting goodwill write-offs between 2004 and 2008 are 447, 480, 475, 533, and 1,283, respectively. The median ratios of goodwill write-off to equity over those years are 5.5%, 6.8%, 4.7%, 6.9%, and 15.2%, respectively."

### 1.3 Do high goodwill / prior acquisitions predict future impairment? Yes — but modestly

**Hayn & Hughes (2006)** — the classic prediction study, and the most candid about weakness:

- Acquisition characteristics beat post-acquisition performance data as predictors: the write-off group paid a **47.6% premium vs 40.8%**; goodwill was **58.4% of the acquisition price vs 44.8%**; stock financing **41.6% vs 34.5%** of deals.
- Acquirer announcement-period returns: **−3.3% (write-off group) vs −1.2% (no write-off)** — the market partly anticipates.
- Out-of-sample prediction: "of acquisitions in the top two deciles of the write-off probability distribution estimated by the one-year-ahead full model, **42.4% actually have a goodwill write-off**. The comparable percentage for the full model for two-, three-, four- and five-year ahead forecasts are, respectively, **39.3%, 36.0%, 32.3% and 31.2%**. The equivalent numbers for the performance-only model are **35%** for the one-year ahead forecast and somewhat lower values for the longer horizon predictions (**33.0%, 29.4%, 28.9% and 25.8%**)."
- Errors: "the model correctly predicts over 42% of the write-off cases, generating a type II error for the remaining 58% of these cases. At the same time, the model emits 'false write-off alarms' … for about 30% of the cases, a type I error."
- **Timing lag: "goodwill write-offs lag behind the economic impairment of goodwill by an average of three to four years. For a third of the companies examined, the delay can extend up to ten years."**
- The paper's own conclusion is that mandated disclosures "do not provide financial statement users with information to adequately predict future write-offs of goodwill."

**Gu & Lev (2011)** — market mispricing as the root cause and a stronger classifier. Sample 1990–2006; 54,218 firm-years; 7,055 firm-years with acquisition activity. Overpricing index = first principal component of (industry-adjusted P/E, discretionary accruals, equity issuance).

Goodwill write-offs deflated by total assets, by overpricing quintile (lowest→highest):

| Group | LL | LM | MM | MH | HH |
|---|---|---|---|---|---|
| All firms with overpricing data | 0.0038 | 0.0064 | 0.0168 | 0.0207 | **0.0507** |
| Firms with acquisition activity 1990–2000 | 0.0069 | 0.0198 | 0.0306 | 0.0593 | **0.1056** |
| All firms with impairment 2001–2006 | 0.0263 | 0.0546 | 0.0879 | 0.0901 | **0.2183** |
| Acquisition + impairment | 0.0167 | 0.0595 | 0.0931 | 0.1026 | **0.2154** |
| % sued (inflated-stock acquisitions, 1996–2006) | 0.00% | 4.46% | 7.97% | 11.11% | **13.86%** |
| % sued *and* reported a write-off | 0.00% | 6.87% | 17.72% | 34.29% | **39.86%** |

Logistic prediction of impairment (single-acquisition firms, N = 243): overpricing factor 1 raises the probability by **38.19%**, overpricing factor 2 by **18.15%**, goodwill acquired by **50.67%**; **pseudo R² 18.02%**; **69.14% correctly classified**; **Type I error 24.80%, Type II error 37.29%**.

Post-acquisition performance for firms that later impaired vs those that never did (mean / median abnormal return since acquisition): **−54.28% / −47.12%** vs **−8.27% / −23.1%** for non-impairing acquirers.

*Practical caveat:* both papers pre-date the modern goodwill stock of mega-cap tech; Gu & Lev's impairment sub-sample is 2001–2006, which is the SFAS 142 adoption window and may not generalise.

### 1.4 Do acquisitions destroy value on average?

- **King, Dalton, Daily & Covin (2004), *Strategic Management Journal* 25(2):187–200**, meta-analysis — [Crossref record with abstract](https://api.crossref.org/works/10.1002/smj.371): "We find robust results indicating that, on average and across the most commonly studied variables, **acquiring firms' performance does not positively change as a function of their acquisition activity, and is negatively affected to a modest extent**. More importantly, our results indicate that unidentified variables may explain significant variance in post-acquisition performance."
- **Malmendier & Tate (2008), *JFE* 89(1):20–43** (NBER WP 10813, Sept 2004) — [NBER PDF](https://www.nber.org/system/files/working_papers/w10813/w10813.pdf). Sample: Forbes 500 firms, 1980–1994 (477 sample firms). Overconfidence = holding options to the last year before expiration. **"The market discounts overconfident bids by 60 to 100 basis points over the three day window relative to the average merger of a non-overconfident CEO. Given a baseline negative announcement effect of 50 basis points, the additional discount for mergers of overconfident CEOs is large."** Conclusion: "cumulative abnormal returns around overconfident bids are roughly **100 basis points lower** on average than for rational bids." Their literature review states: "There is a significant positive gain in target value upon the announcement of a bid, and **a significant loss to the acquiror**."
- **Serial-acquirer / overpricing hedge.** Gu & Lev Table 1: monthly characteristic-adjusted abnormal returns, long lowest-overpricing quintile / short highest quintile = **+1.18% per month (t = 9.17)** at t+1, **+1.09%** at t+2, **+0.85%** at t+3; four-factor alpha +1.16%/month (t = 9.37) at t+1. Interpretation: overpriced serial acquirers underperform going forward.
- **Disagreement to flag.** Practitioner M&A literature (BCG-type "serial acquirer outperformance" studies) cuts the other way. We did **not** verify any of those studies to a primary source, so treat the "serial acquirers outperform" claim as **UNVERIFIED** and do not average it with the above.

### 1.5 Documented predictors, ranked by evidence strength

| Predictor | Evidence | Strength |
|---|---|---|
| Share overpricing (high relative P/E + high accruals + equity issuance) at acquisition | Gu & Lev 2011; monotonic dose–response; predicts both write-off and lawsuits | Strong, published once, not replicated out-of-sample post-2011 |
| Prior premium paid and stock-financed deals | Hayn & Hughes 2006 (47.6% vs 40.8%; 58.4% vs 44.8%) | Strong but dated (1988–98 acquisitions) |
| High goodwill-to-assets / goodwill-to-equity | Gu & Lev Table 7 (goodwill raises impairment probability 50.67%); Kroll concentration data | Moderate |
| Prior impairment / repeated write-offs | Elliott & Hanna (1996) "Repeated Accounting Write-offs" is cited throughout but **UNVERIFIED** here | Not verified |
| Market-to-book below 1 | **UNVERIFIED as a goodwill-impairment predictor.** Gu & Lev use *relative P/E*, not M/B. Do not claim M/B < 1 predicts impairment from these sources. |
| Declining segment ROA / operating losses | Hayn & Hughes: WO host segments show lower ROA 2 years post-acquisition, but performance-only model is the *weaker* predictor (35% vs 42.4%) | Weak-to-moderate |

---

## 2. Non-GAAP / adjusted earnings gaps vs statutory earnings

### 2.1 Definition, formula and — critically — provenance

```
NonGAAPGap       = (NonGAAPNetIncome − GAAPNetIncome) / |GAAPNetIncome|
NonGAAPGap_abs   = |NonGAAPNetIncome − GAAPNetIncome| / TotalAssets
ExclusionShare   = Σ|IndividualExclusions| / |GAAPNetIncome|
CountExclusions  = number of reconciling items in the Reg G / Item 10(e) reconciliation
RecurringShare   = Σ|exclusions rated "recurring"| / Σ|all exclusions|
```

**Inputs are NOT in XBRL.** Adjusted EPS / adjusted EBITDA and the Reg G reconciliation live in the **earnings press release filed as exhibit 99.1 to Form 8-K Item 2.02** (or furnished on Form 6-K for FPIs). No XBRL tag exists for a non-GAAP figure. Any tool must scrape Item 2.02 exhibits (EDGAR full-text search on `EX-99` + `Item 2.02`), or license Audit Analytics' non-GAAP database (which is what Dechow, Loh & Wang use). There is no free, complete machine-readable feed.

### 2.2 How large is the gap? (verified magnitudes)

**Calcbench / Suffolk University, 2025 Non-GAAP Reconciliations Study (FY2024, S&P 500)** — [calcbench.com PDF](https://www.calcbench.com/home/pdf?name=CB-2025-NONGAAP.pdf):

- "we … identified **351 companies — 71 percent of the entire S&P 500** — that reported either non-GAAP net income or non-GAAP EPS."
- "Among the 351 firms we identified as reporting non-GAAP numbers, **89 percent reported non-GAAP adjustments that led to higher earnings** compared to GAAP net income." (2023: 86% upward; 2022: 83%.)
- "Adjusted net income exceeded GAAP net income by an average of **$870 million per company, roughly 30 percent higher than average GAAP net income**."
- "We found a total of **2,249 individual reconciling items** … with an average value of **$135 million per item** … The total value of all non-GAAP adjustments was **$304 billion**."
- "Companies had an average of **6.4 reconciling items** per company in 2024, up only slightly from 6.3 adjustments in 2023."
- Composition: "amortization of intangible assets accounted for roughly **31 percent** of the total adjusted amount"; restructuring **19%**; impairments **17%**; stock-based compensation "almost 17%"; litigation/legal fell 13% → 5%; tax adjustments −13%.
- Sector: manufacturing firms "+31 percent" average upward adjustment; wholesale/retail "+47 percent."
- Extreme tail: seven firms adjusted GAAP net income upward by **731% to 2,077%** (CrowdStrike 731%, Willis Towers Watson 2,077%).

**Dechow, Loh & Wang (2025), "A rating system to evaluate non-GAAP exclusion quality," *Review of Accounting Studies* 30:1037–1098** — [Springer PDF (open access)](https://link.springer.com/content/pdf/10.1007/s11142-024-09855-3.pdf). Sample: S&P 500 annual non-GAAP earnings, **2013–2017, 1,676 firm-years, 8,435 individual exclusions**:

- Prevalence: "In 2003, **55% of S&P 500 firms reported non-GAAP earnings**, whereas by 2020, **close to 80%** of firms did so." Average exclusions per firm rose "from **4.6 to 5.3**."
- "For our sample firms, the **median magnitude of total exclusions is large, accounting for approximately 39% of GAAP earnings**."
- Average exclusion-quality score **2.7** (scale 1–5), interquartile range **1.9 to 3.6**; "over **43% of firms stay in the same exclusion quality score category for two consecutive years**."
- The four most common exclusions are **Depreciation & Amortization, Net Interest Expense, Stock Compensation Expense, Impairment on PPE and Intangible Assets** — the first three are rated *low quality*. "of all sample firms that report Depreciation and Amortization, **46% exclude it**"; "**30%** of sample firms that report net interest expense exclude it."
- Low-quality firms' "total exclusions are almost twice the size of absolute GAAP earnings"; **43%** of low-quality firms report non-GAAP earnings greater than EBITDA, vs **3%** of high-quality firms.

### 2.3 Does a large / growing gap predict restatements or underperformance?

**(a) Direct SEC-scrutiny evidence (the strongest number we verified).** Dechow, Loh & Wang find "The firms in our sample have received **171 SEC comment letters between 2013 and 2017**." Topics: **56.73%** presentation/prominence, **47.37%** reconciliation, **31.58%** specific exclusions, **15.79%** adjusted EBITDA. Logit results: "a **one-unit decrease in the exclusion quality score is associated with a 17% (= 1 – e^–0.190) increase in the likelihood of receiving SEC comment letters**"; "a one-unit decrease in the exclusion quality score is associated with a **30% (= 1 – e^–0.362) increase in the odds of having Regulation G violations**."

**Crucial nuance:** "**the magnitude of non-GAAP exclusions relative to GAAP earnings does not explain future regulatory outcomes**… it is the economic nature or the **quality** of exclusions, rather than their magnitude, that attracts more regulatory scrutiny." Same for analyst forecast dispersion (coefficient −0.023, t = −2.20) — driven by quality, not size. So **a naive "big GAAP–non-GAAP gap" flag is weaker than a "recurring items excluded" flag.**

**(b) Future cash flows / returns. Doyle, Lundholm & Soliman (2003), *Review of Accounting Studies* 8(2–3):145–174** — [EconPapers abstract](https://econpapers.repec.org/article/sprreaccs/v_3a8_3ay_3a2003_3ai_3a2_3ad_3a10.1023_5fa_3a1024472210359.htm), [Springer reference record](https://link.springer.com/article/10.1023/A:1024472210359). Verified abstract text:

> "We find, however, that these expenses are far from unimportant. **Higher levels of exclusions lead to predictably lower future cash flows.** We also find that **investors do not fully appreciate the lower cash flow implications at the time of the earnings announcement. A trading strategy based on the excluded expenses yields a large positive abnormal return in the years following the announcement, and persists after controlling for various risk factors and other anomalies.**"

**The specific effect sizes (hedge-portfolio abnormal return, regression coefficients, decile spreads, sample period and N) are UNVERIFIED.** Reason: the full text was unreachable from this network — Deep Blue (University of Michigan) returns Cloudflare 500/challenge, SciSpace returns 403, Paperzz returns a bot wall, Springer is paywalled, and the Wayback Machine copy of the Deep Blue PDF renders in a browser but the PDF viewer exposes no text layer and no page-navigation handle, so it could not be read. A research subagent read the paper via a third-party scan at `idoc.pub`, but that host was down when we re-opened it. **Do not quote a numeric hedge return for DLS (2003).**

**(c) Restatement linkage.** **Palmrose & Scholz (2004), "The Circumstances and Legal Consequences of Non-GAAP Reporting: Evidence from Restatements," *Contemporary Accounting Research* 21(1):139–180** — [OpenAlex record + reconstructed abstract](https://api.openalex.org/works?search=Non-GAAP%20Reporting%20and%20Accounting%20Restatement&per-page=5). Verified abstract confirms sample and scope: "**492 U.S. companies that announced restatements from 1995 to 1999**… analyze the occurrence and resolution of litigation over restatements… provide evidence on the pervasiveness of accounting misstatements, describe their nature, and show how, if at all, they affect our assessment of the nature of restatements in determining whether regular, recurring earnings from primary operations (core) or other components (noncore) are misstated." **All effect sizes (litigation rates, core vs noncore split) are UNVERIFIED** — the paper is closed access.

**(d) Short-selling response.** Dechow et al. cite Christensen, Drake & Thornock (2014), "Optimistic Reporting and Pessimistic Investing: Do Pro Forma Earnings Disclosures Attract Short Sellers?", *Contemporary Accounting Research* 31(1):67–102: "short sellers exploit the market's lagged response to low-quality non-GAAP earnings disclosures to profit from subsequent negative stock returns." Effect sizes **UNVERIFIED** (Wiley blocked).

**(e) Black & Christensen (2009), "US Managers' Use of 'Pro Forma' Adjustments to Meet Strategic Earnings Targets," *Journal of Business Finance & Accounting* 36(3–4):297–326.** Cited by Dechow et al. as evidence that "managers have discretion over what to exclude, when to exclude, and the level of detail to provide… This discretion gives managers flexibility to manage expectations without having to engage in accrual or real earnings management." **The paper's own effect sizes are UNVERIFIED** — Wiley's site is bot-walled.

### 2.4 SEC scrutiny: what the rules actually say

**Regulation G / Item 10(e) of Regulation S-K Compliance & Disclosure Interpretations** (Corp Fin guidance, questions last updated **13 December 2022**) — [sec.gov, opened in full](https://www.sec.gov/divisions/corpfin/guidance/nongaapinterp.htm). Verbatim highlights:

- **Q100.01:** "Presenting a non-GAAP performance measure that excludes **normal, recurring, cash operating expenses necessary to operate a registrant's business** is one example of a measure that could be misleading… The staff would view an operating expense that **occurs repeatedly or occasionally, including at irregular intervals, as recurring**."
- **Q100.02:** a measure can be misleading if "presented inconsistently between periods."
- **Q100.03:** "a non-GAAP measure that is adjusted only for non-recurring charges when there were non-recurring gains that occurred during the same period could violate Rule 100(b)."
- **Q100.06:** "a non-GAAP measure could mislead investors to such a degree that **even extensive, detailed disclosure about the nature and effect of each adjustment would not prevent** the non-GAAP measure from being materially misleading."
- **Q102.10(a):** examples of undue prominence include "Presenting an income statement of non-GAAP measures", "Presenting a non-GAAP measure before the most directly comparable GAAP measure or omitting the comparable GAAP measure altogether, including in an earnings release headline", and describing a non-GAAP measure as "record performance" without equally prominent GAAP characterization.
- **Q102.10(c):** "The staff considers a **non-GAAP income statement** to be one that is comprised of non-GAAP measures and includes all or most of the line items and subtotals found in a GAAP income statement."
- **Q102.11:** tax effects "should not be presented 'net of tax'. Rather, income taxes should be shown as a separate adjustment and clearly explained."
- **Q103.01:** "'Earnings' means net income as presented in the statement of operations under GAAP. Measures that are calculated differently… should not be characterized as 'EBIT' or 'EBITDA'."

**SEC Chief Accountant Wesley Bricker, Remarks before the 2018 Baruch College Financial Reporting Conference (3 April 2018)** — [sec.gov](https://www.sec.gov/newsroom/speeches-statements/speech-bricker-040318): "to be absolutely clear, **non-GAAP reporting may supplement but is not a substitute for GAAP reporting**"; companies "must have disclosure controls and procedures, which typically would include appropriate governance practices regarding the measures and policies and controls that **prevent error, manipulation, or mischief with the numbers**."

**Comment-letter volume (empirical):** 171 comment letters on non-GAAP across 1,676 S&P 500 firm-years, 2013–2017 (Dechow et al., above) — roughly a 10% firm-year comment rate in that sample.

### 2.5 How it must be computed from filings (and what is impossible)

| Signal | Where it lives | XBRL? |
|---|---|---|
| Non-GAAP EPS / net income | 8-K Item 2.02 Ex-99.1 press release | **No** |
| Reg G reconciliation table | same exhibit | **No** (In some filings the reconciliation is tagged as a text block only) |
| Individual exclusion amounts | same exhibit | **No** |
| GAAP net income | 10-K/10-Q financial statements | Yes (`us-gaap:NetIncomeLoss`) |
| Operating cash flow | 10-K/10-Q | Yes (`us-gaap:NetCashProvidedByUsedInOperatingActivities`) |

Practical build: (i) EDGAR full-text search restricted to form `8-K` and the phrase "reconciliation of" / "non-GAAP"; (ii) parse Exhibit 99.1 HTML tables; (iii) normalise against `us-gaap:NetIncomeLoss` from the XBRL filing for the same period. Accuracy is materially worse than for XBRL facts — expect manual-review load. Calcbench and Audit Analytics both sell this as a curated dataset.

---

## 3. Auditor changes, restatements, late filings, going-concern

### 3.1 Auditor change — base rate and lift (strongest verified number in this brief)

**PCAOB Office of Economic and Risk Analysis, "Data Point: Financial Restatements and Auditor Turnover," October 2025** — [pcaobus.org PDF, opened in full](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf). Sample: US SEC registrants, 2005–2024, Audit Analytics data; excludes 1940 Act filers, benefit plans, and SPAC-warrant restatements.

> "From 2005 to 2024, **Big R financial restatements occurred at a rate of around 3% per year**. On average, **just under 30% of these restatements followed an auditor change in the previous year**. As a point of reference, the average annual auditor-change rate across the broader population, which includes companies without Big R restatements, was **11%**."
>
> "over the 2005 to 2024 period, an average of **29% of companies with Big R restatements reported an auditor change in the year preceding the restatement**."
>
> "over 2005 to 2024, the auditor-change rate across the broader population **ranged from 8% to 13% (averaging 11%)**, which is below the auditor-change rate of 29% among companies with Big R restatements."

Footnote: "A Big R restatement refers to a restatement disclosed in an SEC Form 8-K, **Item 4.02**."

**Implied lift ≈ 29% / 11% ≈ 2.6×.** Caveat: this is a **backward conditional** (auditor change in the year *before* the restatement), not a forward-looking probability. It bounds signal value, it does not give you P(restatement | auditor change) directly.

**Menon & Williams (2008), "Management Turnover Following Auditor Resignations," *Contemporary Accounting Research* 25(2):567–604** — [OpenAlex abstract](https://api.openalex.org/works?search=Auditor%20resignations%20clientele%20effects%20and%20legal%20liability&per-page=3): "…We find frequency of CEO and CFO turnover increases following auditor resignations. The likelihood of CEO or CFO change is even greater when there is a reportable event." The same abstract concedes the literature is mixed. **Effect sizes UNVERIFIED.**

**UNVERIFIED, do not cite numbers:** Shu (2000), *JAE* 29(2):173–205 (closed access); DeFond & Subramanyam (1998), *JAE* 25(1):35–67 (RePEc: "No abstract is available for this item"); Beneish, Hopkins, Jansen & Martin (2005), *JAPP* 24(5):357–390 (closed access). Resignation-vs-dismissal counts and litigation rates could not be obtained.

### 3.2 Restatements — magnitude and the error/fraud split

**GAO-06-678, "Financial Restatements: Update of Public Company Trends, Market Impacts, and Regulatory Enforcement Activities" (July 2006; reissued 5 March 2007)** — [gao.gov PDF, opened in full](https://www.gao.gov/assets/gao-06-678.pdf):

- Sample: "**1,390 restatements announced by 1,121 public companies** — 984 of which were listed companies on the NYSE, Nasdaq, and American Stock Exchange — from **July 1, 2002, to September 30, 2005**"; event study on **1,061** of them.
- Immediate (t−1 to t+1), market-adjusted: "the stock prices of the restating companies **decreased by an average of almost 2 percent**, compared with an average decline of nearly **10 percent** in our 2002 report"; aggregate adjusted market-cap decline **$36.5 billion** = **0.25%** of the $14,662bn total market cap of listed companies. In the 2002 report the comparable figure was ~$100bn.
- Intermediate (20 trading days either side): "**declined by nearly 2 percent on average**, and their market capitalization declined by over **$78 billion** in aggregate" (unadjusted $5.2bn).
- Longer-term (60 trading days): "**decreased by less than 2 percent on average** and their market capitalization decreased by over **$126 billion** in aggregate" (unadjusted **+$34.1bn**).
- Reasons: "**cost- or expense-related reasons accounted for 35 percent** of the restatements, including lease accounting issues, followed in frequency by revenue recognition issues"; most restatements (**58 percent**) were prompted by an internal party.
- **Item 4.02 compliance failure:** "between August 2004–September 2005, about **17 percent of the companies GAO identified as restating did not appear to file the proper disclosure** when they announced their intention to restate." *(Note: the body of the report also states "about 30 percent of restating companies (34 companies)… failed to file a Form 8-K disclosing their restatements" — the report is internally inconsistent; quote both if you use this.)*
- Immediate market-adjusted impact as % of restating company's own market cap, by reason (GAO Figure 6): related-party transactions **−3.76%**, "Other" **−2.87%**, restructuring/assets/inventory **−2.13%**, revenue recognition **−2.05%**, cost or expense **−1.25%**, securities-related **−0.77%**, acquisitions and mergers **−0.49%**, reclassification **+0.04%**.

**Hennes, Leone & Miller (2008), "The Importance of Distinguishing Errors from Irregularities in Restatement Research: The Case of Restatements and CEO/CFO Turnover," *The Accounting Review* 83(6):1487–1519** — **abstract only** (closed access; verified via OpenAlex abstract): "…we show that most restatements we classify as irregularities are followed by fraud-related class action lawsuits compared to **only one lawsuit** in the group of restatements classified as errors… **the market reaction for our irregularity sample (−14 percent) is also more negative than it is for our error sample (−2 percent)**." **Sample period, N, and the CEO/CFO turnover odds ratios are UNVERIFIED.**

**Synthesis (ours, derived):** the blended "restatement = sell" reaction is only ≈ −2% because error-type restatements dominate. The damage is concentrated in the irregularity/fraud tail (−14%). A tool that treats all restatements alike will be mostly noise.

**Palmrose, Richardson & Scholz (2004), "Determinants of market reactions to restatement announcements," *JAE* 37(1):59–89 — ALL NUMBERS UNVERIFIED.** The frequently-quoted "≈ −9%" two-day return could not be confirmed (RePEc: "No abstract is available"; ScienceDirect returned a captcha). Do not attribute GAO's "nearly 10 percent" (which refers to GAO's own 2002 report) to Palmrose et al.

### 3.3 Late filings (Form 12b-25 / NT 10-K, NT 10-Q)

**Rule 12b-25, 17 CFR §240.12b-25** — [Cornell LII, opened in full](https://www.law.cornell.edu/cfr/text/17/240.12b-25):

> "(a) If all or any required portion of an annual or transition report on Form 10-K, 20-F or 11-K … or a quarterly or transition report on Form 10-Q … is not filed within the time period prescribed for such report, the registrant, **no later than one business day after the due date** for such report, shall file a Form 12b-25 … which shall contain disclosure of its inability to file the report timely and **the reasons therefore in reasonable detail**."
>
> "(b)(2)(ii) The subject annual report … will be filed **no later than the fifteenth calendar day** following the prescribed due date; or the subject quarterly report … **no later than the fifth calendar day**…"
>
> "(d) … a registrant **will not be eligible to use any registration statement form** under the Securities Act of 1933 the use of which is predicated on timely filed reports **until the subject report is actually filed**."

**Pevzner, "Abnormal stock performance of late filing firms: additional investigation" (working paper, SSRN 1144767)** — [full text, opened via text proxy](https://api.mdsoar.org/server/api/core/bitstreams/a60dd6ee-5397-4ae7-947d-da8967d9af39/content). Sample 1993–2004: "Timely filings 31,664 85% … Late filings 5,655 15% … 37,319 100%". Findings: "late filing events are **more likely to restate** than the timely filing firms"; "late filing dummy variable is a **significant predictor of future delisting**"; and the NT notification itself matters: "The variable NT=1 if the late filer notifies the SEC of the impending late filing… is also significant, suggesting that the **notifiers face much higher probability of delisting** than non-notifiers." Delisting × late interaction "**−0.46**". **But**: "The delisting firms in the portfolio of notifying small firms (MVE<200, NT=1, DELIST=1) is −0.65. This portfolio is only made up of **51 firms**… Once these extreme delisters are removed from the sample, **the remaining sample of the late filers does not appear to under-perform**." Working paper, not peer-reviewed. Also: "**91% of non-notifiers file within 15 days** of the deadline," i.e. they look like timely filers.

**SEC enforcement on NT narratives** (Goodwin Procter / Public Company Advisory, Sept 2023) — [PDF](http://www.publiccompanyadvisoryblog.com/wp-content/uploads/sites/13/2023/09/SEC-Enforcement-of-Form-NT-Disclosure-Requirements.pdf): "On **August 22, 2023**, the SEC… instituted and settled proceedings against **five public companies** for failing to disclose in Form 12b-25 that their request for a delayed filing was caused by an anticipated restatement… In **April 2021**, the Commission identified and charged **eight companies** for similar violations"; "the SEC orders found that each of the companies **announced restatements or corrections within 3–21 days of their Form NT filings** but failed to provide details that anticipated restatements were among the principal reasons"; penalties "$35,000 to $60,000", "**strict liability** violations." Sample is enforcement-selected, not random.

**SSRN 6932478, "Reading the Late-Filing Notification: Form NT Body Narratives Predict Subsequent SEC Restatement Disclosures" — ENTIRELY UNVERIFIED.** SSRN returned HTTP 403 via direct fetch, via the text proxy, and via the headless browser (Elsevier content protection). Only the title was confirmed.

### 3.4 Going-concern opinions

**CPA Journal, "The Going Concern Gap in U.S. GAAP," Feb 2016** — [cpajournal.com, opened in full](https://www.cpajournal.com/2016/02/02/going-concern-gap-u-s-gaap/). This is a *secondary* paraphrase of Carson et al. (2013), which is paywalled:

> "**Academic research suggests that 40% of public company bankruptcies are not preceded by audit reports modified for going concern uncertainties.**"
>
> "Research indicates that **98.3% of bankrupt firms survive for at least one year from the issuance of a going concern audit report** (Carson et al. 2013)."

Derived (ours, not the source's): a going-concern opinion issued *within a year* of filing is followed by bankruptcy only ~1.7% of the time; the **one-year Type II miss rate is ~40%**. These two facts are in tension and both matter: the GCO is a weak *precision* signal over a 1-year horizon but a meaningful *recall* signal over multi-year horizons.

**Carson, Fargher, Geiger, Lennox, Raghunandan & Willekens (2013), "Audit Reporting for Going-Concern Uncertainty: A Research Synthesis," *Auditing: A Journal of Practice & Theory* 32(Suppl 1):353–384 — primary figures UNVERIFIED** (closed access).

**Altman (1968), "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," *Journal of Finance* 23(4):589–609** — bibliographic record verified at [Crossref](https://api.crossref.org/works/10.1111/j.1540-6261.1968.tb00843.x).

> Z = .012·X1 + .014·X2 + .033·X3 + .006·X4 + .999·X5, where X1 = working capital/total assets, X2 = retained earnings/total assets, X3 = EBIT/total assets, X4 = market value of equity/total liabilities, X5 = sales/total assets. Zone of ignorance: **1.81 < Z < 2.99**.

**Accuracy figures — 95% (1st year), 72% (2nd), 48% (3rd), 29% (4th), 36% (5th); 94%/95% in-sample on 66 firms (33 bankrupt manufacturers 1946–1965, mean assets $6.4m) — are SECONDARY/unverified by the author of this brief.** They were read by a research subagent from a third-party scan (`idoc.pub`) that could not be re-opened; the Wiley original is paywalled. **Note that the headline "94%/95%" is a one-year, in-sample, tiny-sample figure and decays fast — do not present it as a modern predictive accuracy.**

**UNVERIFIED:** Kausar, Shroff & White (title/journal and all numbers); Geiger & Rama type I/II rates; Scholz (2008).

### 3.5 SEC filing-event mechanics (verified primary/authoritative)

| Event | Form / item | Verified detail | Source |
|---|---|---|---|
| Non-reliance on previously issued financials (restatement) | **8-K Item 4.02** | Created by SEC Release 33-8400, 69 FR 15593 (25 Mar 2004), effective 23 Aug 2004. Required when the board/committee/authorized officer concludes previously issued statements "no longer should be relied upon because of an error… as addressed in APB Opinion No. 20." 8-K due "**within four business days** of a triggering event", with "**no provision for extension under Rule 12b-25**". | [govinfo, 69 FR 15593](https://www.govinfo.gov/content/pkg/FR-2004-03-25/html/04-6332.htm) |
| Auditor change | **8-K Item 4.01 + Reg S-K Item 304 (17 CFR 229.304)** | "requiring disclosure of the resignation, dismissal or engagement of an independent accountant". Item 304(a)(1) requires stating "whether the former accountant resigned, declined to stand for re-election or was dismissed and the date thereof"; reportable events (a)(1)(v)(A)–(D) cover inadequate internal controls, inability to rely on management representations, need to expand audit scope, and information materially impacting a previously issued audit report. | [Cornell LII 17 CFR 229.304](https://www.law.cornell.edu/cfr/text/17/229.304); [69 FR 15593](https://www.govinfo.gov/content/pkg/FR-2004-03-25/html/04-6332.htm) |
| Late filing | **Form 12b-25 (NT 10-K / NT 10-Q)** | 1 business day after due date; 15 calendar days (10-K) / 5 calendar days (10-Q); S-3 eligibility lost until actually filed. | [Cornell LII 17 CFR 240.12b-25](https://www.law.cornell.edu/cfr/text/17/240.12b-25) |

---

## 4. What is and is NOT available in XBRL / iXBRL

### 4.1 Available as XBRL facts (US GAAP and IFRS taxonomies)

| Concept | US GAAP element | IFRS element (used in UKSEF/ESEF default target) |
|---|---|---|
| Goodwill (instant) | `us-gaap:Goodwill` | `ifrs-full:Goodwill` |
| Goodwill impairment (duration) | `us-gaap:GoodwillImpairmentLoss` | `ifrs-full:ImpairmentLossRecognisedInProfitOrLossGoodwill` |
| Intangibles excl. goodwill | `us-gaap:IntangibleAssetsNetExcludingGoodwill` | `ifrs-full:IntangibleAssetsOtherThanGoodwill` |
| Finite-lived intangibles | `us-gaap:FiniteLivedIntangibleAssetsNet` | `ifrs-full:IntangibleAssetsOtherThanGoodwill` (with dimensions) |
| Total assets | `us-gaap:Assets` | `ifrs-full:Assets` |
| Goodwill recognised in a business combination | `us-gaap:BusinessCombinationRecognizedIdentifiableAssetsAcquiredAndLiabilitiesAssumedGoodwill` | `ifrs-full:Goodwill` (with acquisition dimension) |
| Cash paid for acquisitions | `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` | `ifrs-full:CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinessesClassifiedAsInvestingActivities` |
| Management going-concern disclosure (ASC 205-40) | `us-gaap:SubstantialDoubtAboutGoingConcernTextBlock` | *no direct IFRS equivalent; IAS 1 going-concern disclosure is narrative only* |

**Verification status of the tag strings above: the *element names* are standard and widely used, but this brief could NOT re-verify them against a taxonomy listing in this session** — `xbrl.fasb.org` timed out, `data.sec.gov/api/xbrl/frames/...` returned HTTP 403 ("Your Request Originates from an Undeclared Automated Tool"), and the rendered SEC XBRL instance lost its element names in text conversion. `us-gaap:SubstantialDoubtAboutGoingConcernTextBlock` was seen inside a real SEC Inline XBRL instance filename (`..._eus-gaap--SubstantialDoubtAboutGoingConcernTextBlock_...` in `form10-q_htm.xml` for CIK 0000932021) but only via an indexed reference, not by opening the taxonomy. **Treat the exact strings as needing a one-time validation against the current taxonomy before shipping.**

**UK / Companies House specifics (verified).** Companies House does **not** operate its own separate taxonomy for this; per the FRC's **UKSEF 2025 Tagging Guide v2.1** ([FRC PDF, opened in full](https://media.frc.org.uk/documents/UKSEF_2025_Tagging_Guide_v2.1.pdf)):

- A UKSEF report uses Inline XBRL **multiple target documents**: the **default target** carries the ESEF/IFRS tagging of the consolidated statements; a second target named **`UKFRS`** carries FRC-taxonomy tagging of UK-specific data.
- The FRC taxonomy uses prefixes `bus:`, `core:`, `direp:`, `aurep:` (e.g. `bus:UKCompaniesHouseRegisteredNumber`, `core:ProfitLoss`, `aurep:OpinionAuditorsOnEntity`).
- **Companies House's mandatory tag list contains no goodwill element.** Mandatory items are identifiers, dates, entity name, accounting-standard applied, audit status/type, average employees, `core:ProfitLoss`, and auditor's/directors' report items — plus, for group audited accounts, `aurep:OpinionAuditorsOnEntity`. Tagging beyond that "is discretionary."
- **Consequence for a UK tool:** for a UK company you can reliably get `ifrs-full:Goodwill` / `ifrs-full:ImpairmentLossRecognisedInProfitOrLossGoodwill` from the ESEF-tagged consolidated balance sheet and note, but you **cannot** assume the auditor's opinion or going-concern paragraph is machine-readable — only `aurep:OpinionAuditorsOnEntity` (the opinion *type* on the entity) is mandated for group audited accounts, and that is an FRC-taxonomy concept in the `UKFRS` target, not the ESEF target.

### 4.2 NOT in XBRL at all — these are filing events or free text

| Signal | Mechanism | How to get it |
|---|---|---|
| **Non-GAAP / adjusted earnings and the Reg G reconciliation** | 8-K **Item 2.02** Exhibit 99.1 (or 6-K for FPIs). *No XBRL concept exists.* | EDGAR full-text search + exhibit parsing, or a licensed dataset |
| **Auditor change (resignation vs dismissal)** | 8-K **Item 4.01** + Reg S-K Item 304; four-business-day deadline | EDGAR submissions/`8-K` feed by item number; the resignation/dismissal distinction is in the *text* of the item |
| **Restatement / non-reliance** | 8-K **Item 4.02** | EDGAR form feed; the restated *numbers* only become XBRL in the amended filing |
| **Late filing** | Form **12b-25** = EDGAR form types `NT 10-K`, `NT 10-Q` | EDGAR form-type query (event, no XBRL) |
| **Going-concern *opinion* (auditor)** | Narrative in the audit report | Not machine-readable; the *management* ASC 205-40 disclosure is a text block, present/absent only |
| **Auditor identity / resignation language** | Narrative; not a financial-statement fact | Text/filing-event extraction |

**Architectural implication:** the tool needs two data planes — (i) **XBRL numerical facts** (`companyconcept` / `companyfacts` / `frames`, or the Financial Statement Data Sets) for goodwill, intangibles, assets, impairments; and (ii) an **EDGAR filing-event index** (submissions API + full-text search) keyed on form type and 8-K item 4.01 / 4.02 / NT 10-K / NT 10-Q, plus 8-K Exhibit 99.1 parsing for non-GAAP. Attempting to derive signals 4–7 from XBRL facts alone will silently return nothing.

---

## 5. Confidence and gaps

**High confidence (multiple independent or primary sources, numbers verified verbatim):**
- Base rate of Big-R restatements (~3%/yr) and auditor turnover (~11%/yr), and the ~2.6× lift of prior-year auditor change before a Big-R restatement — PCAOB OERA 2025, read in full.
- GAO-06-678 restatement market impact and reason breakdown — read in full.
- Rule 12b-25 mechanics — read in full at Cornell LII.
- SEC Reg G C&DI content — read in full at sec.gov.
- Calcbench FY2024 non-GAAP magnitudes (71% of S&P 500; +$870m / ~+30%; $304bn total) — read in full.
- Dechow, Loh & Wang (2025) exclusion-quality numbers, including the 17%/30% regulatory-scrutiny effects and the finding that *magnitude* of exclusions does not predict regulatory outcomes — read in full (open access).
- Gu & Lev (2011) goodwill tables and classifier accuracy — read in full.
- Hayn & Hughes (2006) base rate, predictors, 3–4 year lag, and modest predictive power — read in full.
- Malmendier & Tate (2008) 60–100bp announcement discount — read in full.
- UKSEF/Companies House mandatory tag list — read in full.

**Medium confidence (single source, or abstract-only, or dated):**
- King et al. (2004) meta-analysis — abstract only (Crossref).
- Palmrose & Scholz (2004) — abstract only.
- Menon & Williams (2008) — abstract only.
- Pevzner late-filing paper — full text read, but working paper, and its own robustness test removes the entire effect.
- Hennes, Leone & Miller (2008) — abstract only; the −14% vs −2% figure is real but the sample and turnover odds are unknown.

**Explicitly UNVERIFIED — do not quote numbers:**
- **Doyle, Lundholm & Soliman (2003) effect sizes.** The abstract's directional claims are verified; the hedge-portfolio return, coefficients, sample period and N are not. This is the single biggest gap in the brief and it is a *sourcing* failure, not a research failure — the paper is paywalled and every open mirror was bot-walled from this network.
- Shu (2000); DeFond & Subramanyam (1998); Beneish, Hopkins, Jansen & Martin (2005) — auditor resignation/dismissal effect sizes.
- Palmrose, Richardson & Scholz (2004) — all numbers.
- Carson et al. (2013) — primary figures (only the two CPA Journal paraphrases are verified).
- Kausar, Shroff & White — could not even confirm title/journal.
- Geiger & Rama — type I/II rates.
- Altman (1968) accuracy table — secondary scan only.
- SSRN 6932478 (NT narratives) — entire paper.
- Black & Christensen (2009) and Christensen, Drake & Thornock (2014) effect sizes.
- Any "serial acquirers outperform" practitioner claim.
- **XBRL element name strings** — not re-verified against a taxonomy listing in this session.

**Known source disagreements:**
1. GAO-06-678 is internally inconsistent on the Item 4.02 non-filing rate (17% in the highlights vs 30% in the body).
2. Alford, Jones & Zmijewski (1994) find late filers underperform; Pevzner's post-EDGAR replication finds the underperformance vanishes once ~51 small notifier-delister firms are removed.
3. Hennes et al. (−14% for irregularities) vs GAO (−2% blended) — reconcilable, but only if you split the population.
4. Academic acquirer-return evidence (King et al.: no gain, modest negative) vs practitioner "serial acquirer alpha" claims — unresolved here; the practitioner side is unverified.
5. Going-concern: 40% of bankruptcies have no prior GCO (recall failure) *and* 98.3% of GCO firms survive a year (precision failure) — the signal is real but weak on both margins.

**Recommended next steps to close the gaps (all require access this session did not have):** institutional access to *RAST*, *JAE*, *TAR*, *CAR* and *AJPT* for the six paywalled papers above; a licensed SSRN/Audit Analytics session for SSRN 6932478 and the non-GAAP dataset; and a one-time programmatic validation of every `us-gaap:`/`ifrs-full:`/FRC element string against the live taxonomy with a declared SEC user-agent.
