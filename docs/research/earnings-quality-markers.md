# Earnings-Quality Markers for an XBRL/iXBRL Equity Screener
### Source-grounded findings on (1) cash conversion, (2) DSO drift, (3) inventory build, (4) the OCF/NI ratio

**Method note.** Every URL cited below was actually opened with a fetch during this session. Where a paper is paywalled I say so and mark the claim **UNVERIFIED**. Abstracts obtained from the Crossref REST API (`api.crossref.org`) are treated as opened sources and are quoted verbatim; I mark them as `[Crossref abstract]` so the reader knows the provenance. Two structural access failures constrained this work and should be understood as gaps, not absences: **SEC.gov and data.sec.gov returned HTTP 403 to this session** (automated-tool block), so I could not open the SEC's own taxonomy viewer, EDGAR APIs, or AAER text; and **SSRN, Wiley, ScienceDirect, Springer full text, and Informatics/INFORMS returned 403 or CAPTCHA**. PDFs were readable only through a text-extraction proxy (`r.jina.ai`), which works on publicly reachable PDFs.

---

## 0. The headline finding first (please read before using any threshold)

There is **no well-known academic literature on the literal screen "cumulative operating cash flow ÷ net income < 1."** What exists — and what is heavily replicated — is the *accruals* literature, in which the OCF-vs-NI gap is the raw material but is always **scaled by assets or revenue**, never taken as a bare ratio, and never thresholded at 1.0. The practitioner formulation closest to the prompt's "cumulative OCF/NI accrual proxy" is the Georgia Tech **Earnings Quality Indicator**, EQI = (OCF − NI)/Revenue ([Georgia Tech Financial Analysis Lab, 2016](https://www.scheller.gatech.edu/_files/pdf-pages/centers-initiatives/FinLab/gatechlab_eqi_05.07.2016.pdf)). Anyone building a "cash conversion < 1 for N years" flag is building an *undocumented composite*; the documented, tested signals are the ones below. I flag this explicitly because the difference matters for how much weight the flag deserves.

---

## 1. Cash conversion / earnings quality: OCF vs net income over multiple years

### (a) Plain-English definition and exact formulas

**The underlying identity.** Earnings = cash flow + accruals. So "OCF persistently below NI" is an accruals signal seen through the cash-flow statement.

Three documented operationalisations, in increasing order of what the source actually tested:

1. **Working-capital accruals (Sloan's original construction, as re-stated by Chan et al.)**
   ```
   Accruals = ΔCA − ΔCL − DEP
            = (ΔAR + ΔINV + ΔOCA) − (ΔAP + ΔOCL) − DEP
   ```
   where ΔCA = change in non-cash current assets; ΔCL = change in current liabilities **excluding** short-term debt and taxes payable; DEP = depreciation and amortisation. Every term is scaled by **average total assets** (average of beginning and end of fiscal year). Earnings is operating income after depreciation; **cash flow = earnings − accruals**, not the cash-flow-statement number.
   *Source: [Chan, Chan, Jegadeesh & Lakonishok, NBER WP 8308](https://www.nber.org/system/files/working_papers/w8308/w8308.pdf), eq. (1) and Table 3 definitions.*

2. **Cash-flow-statement accruals.** `Accruals = (NetIncomeLoss − NetCashProvidedByUsedInOperatingActivities) / average total assets`. This is the version a XBRL pipeline should use. It is the cleanest because it bypasses balance-sheet articulation errors — see Hribar & Collins in (e) below.

3. **Beneish's balance-sheet accrual term** (his 8-variable M-score input):
   ```
   Accruals to Total Assets =
     [(ΔCurrentAssets − ΔCash) − (ΔCurrentLiabilities − ΔCurrentMaturitiesLTD
       − ΔIncomeTaxPayable) − DepreciationAndAmortisation] / TotalAssets
   ```
   *Source: [Beneish, "The Detection of Earnings Manipulation"](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...), Table 2 variable definitions.*

4. **Multi-year / cumulative version (the prompt's signal).** Sum NI and sum OCF over N years and compare, or cumulate `NI − OCF` and scale by assets. This is mechanistically equivalent to a low-frequency accruals measure. **UNVERIFIED as a named, tested signal** — I found no paper that tests "cumulative OCF/NI" as its own predictor. The nearest tested analogue is the **net operating assets (NOA)** measure, which *is* cumulative: see Hirshleifer et al. in (c).

### (b) Originating work

- **Originating paper:** Richard G. Sloan, "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows About Future Earnings?", *The Accounting Review* 71(3), 289–315 (July 1996), DOI [10.2308/tar-9608042309](https://api.crossref.org/works?query.bibliographic=Do+Stock+Prices+Fully+Reflect+Information+in+Accruals+and+Cash+Flows+About+Future+Earnings+Sloan&rows=2&select=title,author,container-title,issued,DOI,abstract,page,volume).
- **Lineage / extensions:** Richardson, Sloan, Soliman & Tuna (2005), *JAE* 39(3), 437–485, DOI [10.1016/j.jacceco.2005.04.005](https://api.crossref.org/works?query.bibliographic=Accrual+reliability+earnings+persistence+and+stock+prices&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume); Dechow & Dichev (2002), *TAR* 77(s-1), 35–59, DOI [10.2308/accr.2002.77.s-1.35](https://api.crossref.org/works?query.bibliographic=The+quality+of+accruals+and+earnings+the+role+of+accrual+estimation+errors+Dechow+Dichev&rows=2); Hirshleifer, Hou, Teoh & Zhang (2004), *JAE* 38, 297–331, DOI [10.1016/j.jacceco.2004.10.002](https://api.crossref.org/works?query.bibliographic=Do+Investors+Overvalue+Firms+with+Bloated+Balance+Sheets&rows=3).

### (c) Samples used

| Study | Market / sample | Period | N |
|---|---|---|---|
| Sloan (1996) | NYSE + AMEX, CRSP + Compustat annual industrial/research | 1962–1991 (30 years) | 40,679 firm-years |
| Chan, Chan, Jegadeesh & Lakonishok (NBER w8308; publ. *Journal of Business* 79(3), 2006) | NYSE + AMEX + Nasdaq, CRSP ∩ Compustat, domestic primaries only; closed-end funds, trusts, units, foreign issuers and **financials (SIC 6000–6999) excluded**; stocks priced <$5 in the bottom three size deciles excluded | 1971–1995, ranked each end-April (4-month reporting lag) | all available firm-years |
| Hirshleifer, Hou, Teoh & Zhang (2004) | US | 1964–2002 | — |
| Beneish & Vargus (2002) | US | — | — |

*Sloan sample figures come from a course presentation summarising the paper (secondary — see the note in (d)). Chan et al. figures are from the primary NBER PDF.*

### (d) Reported effect sizes — quoted, not rounded

**Chan, Chan, Jegadeesh & Lakonishok (NBER WP 8308), decile sorts on accruals scaled by average total assets.** Equally-weighted buy-and-hold abnormal returns (size- and book-to-market-matched control portfolios):

| Portfolio | Year +1 abnormal return |
|---|---|
| Decile 1 (lowest accruals) | **+2.6%** |
| Decile 10 (highest accruals) | **−4.7%** |
| **Spread (1 − 10)** | **+7.4%, t = 3.83** |
| Spread, year +2 | +4.4%, t = 2.97 |
| Spread, year +3 | +4.3%, t = 2.48 |
| Raw return spread, year +1 | +8.8%, t = 3.79 |

Supporting detail from the same tables: mean accruals in decile 1 = **−0.162** and in decile 10 = **+0.189** of average total assets. Decile-10 firms show **earnings of 17.6% of assets but cash flow of −1.3%**. Total accruals have a cross-sectional standard deviation of **10.2%**, "close in magnitude to the average level of earnings (as a percent of total assets)."

The authors' own framing: *"the marginal contribution of accruals in predicting returns exceeds the contribution of earnings surprises."* Quantitatively, the earnings-surprise quintile spread averaged **4.2%** per year versus an accruals quintile spread of **6.2%**. In a Fama-MacBeth regression the raw accruals coefficient is **−0.2627 (t = −4.14)**; with all accrual components entered together, accruals (−0.1490, t = −1.69) and ΔINV (−0.2661, t = −2.83) carry the load, while ΔAP is insignificant (−0.0120, t = −0.08).

**Sloan (1996) itself.** The well-known magnitude is a hedge portfolio long low-accruals / short high-accruals earning about **10.4%** in the year after formation, with negative returns in only 2 of 30 years. **I could not open the original article (JSTOR/AAA paywall), and no open-access copy exists (Unpaywall reports `oa_status: closed`) — so treat 10.4% as SECONDARY.** The only source I opened that states it is a student presentation of the paper hosted by Washington University in St. Louis ([Cao, 2018](https://dybfin.olin.wustl.edu/teaching/topicsquantfin18-3/tqf3slides/FIN%20500R%20Topics%20in%20Quantitative%20Finance_CAO%20Hongwen.pdf)), which also gives Sloan's definitions and sample. The direction and existence of the effect are independently confirmed by Chan et al.'s replication; the exact 10.4% figure is flagged.

**Beneish & Vargus (2002), *TAR* 77(4), 755–791** — refining accruals with insider trading: *"The extent of the mispricing and the magnitude of the one-year ahead returns **(14.7 to 22 percent)** to a trading strategy based on positive accruals and abnormal selling suggests that these accruals arise from opportunistic earnings management..."* `[Crossref abstract]` ([DOI 10.2308/accr.2002.77.4.755](https://api.crossref.org/works?query.bibliographic=Insider+Trading+Earnings+Quality+and+Accrual+Mispricing+Beneish+Vargus&rows=2&select=title,author,container-title,issued,DOI,abstract,page,volume)). Also relevant: *"the accrual mispricing phenomenon observed in previous work is largely due to the mispricing of positive accruals."*

**Hirshleifer, Hou, Teoh & Zhang (2004)** — the cumulative measure. *"In our 1964-2002 sample, net operating assets scaled by beginning total assets is a strong negative predictor of long-run stock returns. Predictability is robust with respect to an extensive set of controls and testing methods."* `[Crossref abstract]` **No numeric spread is given in the abstract and I could not open the paper** — effect size **UNVERIFIED**.

**Richardson, Sloan, Soliman & Tuna (2005)** — the reliability-ranking result. Bibliographic record verified ([Cookie](https://api.crossref.org/works?query.bibliographic=Accrual+reliability+earnings+persistence+and+stock+prices&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume)); abstract elided by the publisher, effect sizes **UNVERIFIED**. However, **it has been independently replicated**: Dey & Lim (2015), *American Journal of Business* 30(1), 22–48, DOI [10.1108/ajb-07-2014-0041](https://api.crossref.org/works?query.bibliographic=Accrual+reliability+earnings+persistence+and+stock+prices&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume) — *"The results corroborate Richardson et al.'s (2005) conclusions that lower reliability of total accrual (accrual components) leads to lower earnings persistence... less reliable accruals lead to lower earnings persistence"* using more recent US data. This is a genuine out-of-sample corroboration.

**Dechow & Dichev (2002)** — the accrual-quality measure, on which much of the later work rests: accrual quality is the residual from **firm-specific regressions of changes in working capital on past, present and future operating cash flows**; the paper documents *"a strong positive relation between accrual quality and earnings persistence"* and that accrual quality is negatively related to the magnitude of total accruals, length of the operating cycle, and volatility of sales/cash flows/earnings, and positively related to firm size. `[Crossref abstract]`

### (e) Did it hold up out-of-sample / after publication? — **Partially. This is the most important caveat in the report.**

- **Sloan's anomaly has decayed to statistical irrelevance in US markets.** Green, Hand & Soliman (2011), *Management Science* 57(5), 797–816, DOI [10.1287/mnsc.1110.1320](https://api.crossref.org/works?query.bibliographic=Going+Going+Gone+Apparent+Demise+of+the+Accruals+Anomaly&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume) — verbatim from the published abstract: *"the hedge returns to Sloan's... accruals anomaly **appear to have decayed in U.S. stock markets to the point that they are, on average, no longer reliably positive.**"* The authors attribute this *"in part from an increase in the amount of capital invested by hedge funds into exploiting it, as measured by hedge fund assets under management and trading volume in extreme accrual firms"*, and, more weakly, to *"a decline in the size of the accrual mispricing signal."* Unpaywall confirms this paper is closed-access, so I could not read the decay magnitudes.
- **Generic post-publication decay across 82 characteristics.** McLean & Pontiff (2014 symposium version of the paper published in *Journal of Finance*, DOI 10.1111/jofi.12365) — opened full text at [ivey.uwo.ca](https://www.ivey.uwo.ca/media/2827306/bengraham3rdsymposium-pontiff-paper-2014.pdf): average **out-of-sample, pre-publication decay ≈ 10%** (not statistically different from zero); average **post-publication decay ≈ 35%** (statistically different from both 0% and 100%). *"Thus, an in-sample alpha of 5% is expected to decay to 3.25% post-publication."* In their scaled-coefficient table the average characteristic retains **0.51** of its in-sample return post-publication (t = −4.91), and **0.47** on the quintile specification (t = −3.62). **Note: these are the 2013/2014 working-paper numbers; the 2016 published version's headline decay figure is materially larger in some tellings, and I could not open the published version to confirm which numbers were finalised — treat the published-version figure as UNVERIFIED.**
- **Replication at scale.** Hou, Xue & Zhang, "Replicating Anomalies," NBER WP 23394 / *Review of Financial Studies* 33(5), 2020, 2019–2133 ([NBER page](https://www.nber.org/papers/w23394)): across **447 anomaly variables**, **286 (64%) are insignificant at the 5% level** once microcaps are alleviated via NYSE breakpoints and value-weighted returns; *"Imposing the cutoff t-value of three raises the number of insignificance to 380 (85%). Even for the 161 significant anomalies, their magnitudes are often much lower than originally reported."* I did **not** verify whether accruals specifically is among the insignificant 286 — **UNVERIFIED** on that specific point.

**Net position:** the *predictive relationship* (high accruals → lower future earnings persistence and lower future returns) is one of the most replicated results in accounting. The *tradable return spread* is largely gone in US large/mid caps and must not be assumed in a live screen. The surviving, defensible use is **as a risk/quality flag on fundamental deterioration**, not as a return factor.

### (f) Practical caveats

- **Financials must be excluded.** Chan et al. drop SIC 6000–6999; Beneish's sample construction explicitly eliminates financial institutions. For banks and insurers, "operating cash flow" is not a meaningful construct (deposit flows and trading assets swamp it), and accruals definitions break down. Georgia Tech's EQI report covers only *"the 20 GICS **non-financial** industry groups."* **Do not compute OCF/NI or accruals for banks or insurers.**
- **Utilities and energy look structurally different.** In the Georgia Tech EQI table (Sep 2015 medians): Energy **26.62%**, Utilities **16.53%**, Telecommunication Services **16.97%**, Pharmaceuticals/Biotech **13.99%**, Software & Services **12.10%** — versus Consumer Durables & Apparel **1.81%**, Food & Staples Retailing **2.17%**, Retailing **2.50%**, Capital Goods **3.45%**. A single cross-market threshold on EQI or OCF/NI is therefore indefensible; industry-relative ranking is required. (These are *sustainable*/adjusted measures and industry medians drawn from different companies, which the report itself flags.)
- **Size effect.** Chan et al. found accruals are U-shaped in size: *"the extreme portfolios contain the smaller, more risky stocks."* Post-publication decay (McLean & Pontiff) is *greater* for characteristics that are *cheaper* to arbitrage — i.e. large, liquid, low-idiosyncratic-risk, dividend-paying names — which is the opposite of where a small-cap screen would be operating.
- **Which accruals definition you use changes the answer.** Hribar & Collins (2002), *JAR* 40(1), 105–134, DOI [10.1111/1475-679X.00041](https://api.crossref.org/works/10.1111/1475-679X.00041): *"studies using a balance sheet approach to test for earnings management are potentially contaminated by measurement error in accruals estimates. In particular, if the partitioning variable... is correlated with the occurrence of mergers and acquisitions or discontinued operations, tests are biased... Moreover, we demonstrate that tests of market mispricing of accruals will be understated due to erroneous classification of 'extreme' accruals firms."* `[Crossref abstract]` **Operational consequence: compute accruals from the cash-flow statement (`NetIncomeLoss − NetCashProvidedByUsedInOperatingActivities`), not from balance-sheet deltas.** This single choice removes M&A/discontinued-operations contamination that otherwise creates false "extreme accrual" firms.
- **Non-recurring items.** Every credible construction strips them. Sloan's earnings measure is *"operating income after depreciation, excluding non-recurring items."* Georgia Tech: *"before its use in the EQI calculations, operating cash flow measured under GAAP is first adjusted for nonrecurring and non-operating items. Net Income measured under GAAP is similarly adjusted."* A naive XBRL pull of `NetIncomeLoss` will not do this.
- **Standard-change distortions (flagged UNVERIFIED against a primary source in this session).** IFRS 16 (and to a much lesser extent ASC 842) mechanically raises reported operating cash flow for lessees by reclassifying the principal element of lease payments into financing activities. Any OCF/NI series spanning an IFRS 16 transition (2019 for IFRS filers; ASC 842 effective 2019 for US public filers, with operating-lease payments largely remaining in operating cash flow) is **not comparable across the break** for lease-heavy sectors (retail, airlines, hospitality). I could not verify this against a standard-setter document in this session because sec.gov and ifrs.org's standard text were unavailable/paywalled; **treat as an untested mechanical hypothesis to validate on your own data** before putting it in a model.

### (g) How hard is this to compute from XBRL / iXBRL?

**Easy in principle.** The cash-flow-statement route needs only two elements per year for three-to-five years:
- `NetCashProvidedByUsedInOperatingActivities` (US-GAAP) — the cash-flow-statement line
- `NetIncomeLoss` (US-GAAP) — but see the non-recurring caveat; for a cleaner version use `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, or reconcile from the income statement yourself

Then `Accruals = NetIncomeLoss − NetCashProvidedByUsedInOperatingActivities`, scaled by `Assets` (average of opening and closing).

**UK iXBRL / IFRS equivalents** use different local names — IFRS-taxonomy-based filers report the operating cash flow under a `CashFlowsFromUsedInOperatingActivities*` family rather than `NetCashProvidedByUsedInOperatingActivities`, and net income as `ProfitLoss`. **I could not verify the exact IFRS element names against a taxonomy browser in this session (SEC and IFRS taxonomy detail pages were blocked/paywalled); the IFRS Foundation does confirm the general point** that the *"IFRS Accounting Taxonomy includes elements for tagging financial statements prepared in accordance with IFRS Accounting Standards"* ([ifrs.org](https://www.ifrs.org/issued-standards/ifrs-taxonomy/)). **Action for the build: pin the exact element names from a real filed instance document for each jurisdiction before writing parsers** — do not assume US-GAAP names carry over.

The **hard part is not the tags, it is the taxonomy extension problem**: filers routinely create custom extension elements for adjusted cash flow, and the "operating cash flow" line may be tagged as an extension rather than the standard element. Also, `Revenues` is a *subtotal* choice (see §2g).

---

## 2. Revenue recognition red flags: DSO drift / receivables growing faster than revenue

### (a) Definition and formulas

```
DSO (period-end)       = AccountsReceivable / (Revenue / 365)
DSO (average)          = AverageAccountsReceivable / (Revenue / 365)
DSO drift              = DSO_t − DSO_{t−1}
Receivables-vs-revenue = ΔAR% − ΔRevenue%        (growth gap, > 0 is the red flag)
```

**Beneish's Days Sales in Receivables Index (DSRI)** — the version with published coefficients:
```
DSRI = (Receivables_t / Sales_t) ÷ (Receivables_{t−1} / Sales_{t−1})
```
Note this is a **ratio of ratios, not a days figure** — algebraically DSRI > 1 when receivable-days have risen. Beneish's stated rationale: *"This is consistent with disproportionate increases in receivables raising the likelihood that a firm has inflated revenues."*

### (b) Originating work

Messod D. Beneish, "The Detection of Earnings Manipulation," *Financial Analysts Journal* 55(5), 24–36 (1999), DOI [10.2469/faj.v55.n5.2296](https://api.unpaywall.org/v2/10.2469/faj.v55.n5.2296?email=earnings.quality.research@gmail.com). DSRI is one of eight variables in the M-score. Fuller production-model version: Beneish, Lee & Nichols, "Earnings Manipulation and Expected Returns," *Financial Analysts Journal* 69(2), 57–82 (2013), DOI [10.2469/faj.v69.n2.1](https://api.unpaywall.org/v2/10.2469/faj.v69.n2.1?email=earnings.quality.research@gmail.com) — there is also a published **"Author Response"** in *FAJ* 69(5), 14 ([DOI 10.2469/faj.v69.n5.8](https://api.crossref.org/works?query.bibliographic=The+Detection+of+Earnings+Manipulation+Financial+Analysts+Journal+Beneish+1999&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume)), which indicates the 2013 paper drew a published critique. **Neither the 2013 paper nor the critique is open-access; I could not open either. Effect sizes UNVERIFIED and the dispute is unresolved in this report.**

### (c) Sample (Beneish 1999)

- **74 earnings manipulators** (49 from SEC AAERs #132–502 issued 1987–1993; 25 from a LEXIS/NEXIS news search Jan 1987–Apr 1993), each requiring ex-post restatement to comply with GAAP.
- **2,332 COMPUSTAT non-manipulators** matched by **2-digit SIC industry and year**.
- 63 different four-digit SIC codes; manufacturing (SIC 30–39) + business/personal services (SIC 70–79) = 45% of the sample.
- **Estimation sample 1982–1988:** 50 manipulators, 1,708 controls. **Holdout 1989–1992:** 24 manipulators, 624 controls.
- Constants from the paper: median sales growth of manipulators **34.4%** vs controls **9.4%**; in the year before the manipulation year, **29.4%** vs **10.6%**. Manipulators are *"smaller..., less profitable, and more levered."*

### (d) Reported effect sizes — quoted

**DSRI coefficient in the manipulation probit:**

| Estimation | DSRI coefficient | t-statistic |
|---|---|---|
| Unweighted probit | **0.920** | **6.02** |
| WESML probit (prior prob. .0069) | **0.789** | **6.40** |

DSRI is the second-largest t-statistic in the model. Model fit: **pseudo-R² 30.6% (WESML) and 37.1% (unweighted probit)**; likelihood-ratio χ² = 34.50 and 129.20 respectively (p = .00).

**Univariate separation:** median DSRI for treatment firms **1.281** vs controls **0.996**; means 1.465 vs 1.031 (Wilcoxon and median-test p = .000).

**Classification performance, unweighted probit:**
- At relative error costs of 20:1 or 30:1, the model flags a firm when estimated probability > **.0376**, i.e. **M-score > −1.78**.
- **Estimation sample:** misclassifies **26% of manipulators** and **13.8% of non-manipulators**.
- **Holdout sample:** misclassifies **50% of manipulators** and **7.2% of non-manipulators**.
- Holdout correctly-classified manipulators range **37.5% to 56%**; incorrectly-classified non-manipulators range **3.5% to 9.1%**.
- The model's expected misclassification cost is **.623 and .582** of a "classify everyone as non-manipulator" naive strategy at 20:1 and 30:1 cost ratios (holdout), i.e. a **38–42% cost reduction**, not a dramatic one.
- **Cost anchor:** *"the typical manipulator loses approximately 40% of its market value on a risk-adjusted basis in the quarter containing the discovery of the manipulation."* Hence the investor-relevant Type I : Type II cost ratio of 20:1 to 40:1.

**Receivables as a standalone return predictor — Chan et al.** Decile sorts on ΔAccountsReceivable / average total assets: year +1 abnormal spread **+3.1% (t = 2.23)**; year +2 **+2.8% (t = 2.10)**; year +3 **+1.8% (t = 1.17, insignificant)**. On the *discretionary* component: year +1 **+3.5% (t = 2.99)**; the *non-discretionary* component is **+0.7% (t = 0.51)**. Chan et al. explicitly rank the components: *"changes in inventory are by far the most important component of accruals for predicting future returns, with changes in accounts receivable and accounts payable tied for second place."*

**Important caveat on the accruals-model coefficient for DSRI-adjacent items:** in Beneish's own 1999 table the accruals-to-total-assets coefficient is **−0.327 (t = −1.22)** — *not significant*. DSRI carries the revenue-side signal; the aggregate accrual term does not, in that sample.

### (e) Out-of-sample / after publication

- **Beneish's DSRI survives his own holdout** (coefficients estimated 1982–88, evaluated 1989–92), but with a **50% miss rate on manipulators** in the holdout. That is a genuinely out-of-sample test, and it is the strongest thing that can be said for DSRI.
- **The M-score as a trading signal (Beneish, Lee & Nichols 2013) is exactly where the dispute lies, and I could not resolve it.** The existence of a published author response to a critique is strong evidence that the return evidence is **contested**. Do not describe the M-score as a return factor without reading both the 2013 paper and its critique.
- **Base rate problem.** The prior probability of manipulation used in estimation is **.0069** (50/7,231). At that base rate, even a 56%-hit-rate screen produces mostly false positives in absolute terms; Beneish himself concedes *"its large rate of classification errors makes further investigation of the results an important element to the model's implementation."*

### (f) Practical caveats

- **Receivables factoring / supply-chain finance inverts the signal.** Selling or factoring receivables removes them from the balance sheet and *lowers* DSO while leaving the underlying credit risk with the firm. This makes a deteriorating receivable book look like improving DSO. **UNVERIFIED against a source in this session** — I found no academic paper quantifying the distortion; it is a known structural limitation, not a measured one. Practical handling: cross-check against cash collected from customers (direct-method disclosure, rarely available in the US), against the notes for factoring/SPE disclosure, and against any jump in "other" or financing cash flows.
- **The same distortion applies to receivables securitisation**, which is common in consumer finance and retail.
- **DSO is a revenue-mix artifact.** A shift toward longer-payment customers (government, OEM, export) raises DSO without any accounting problem; conversely a shift to card/cash retail lowers it. Industry-relative comparison is mandatory — which is exactly why Beneish matched on 2-digit SIC.
- **The `Revenues` tag is unreliable as a denominator.** US-GAAP has `Revenues` (a subtotal), `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, and `SalesRevenueNet`. Different filers use different ones and the choice changed materially with ASC 606 adoption. Compute revenue from a hierarchy and validate against `us-gaap:Revenues` where present. **Flagged as a build risk, not a sourced finding.**
- **ASC 606 / IFRS 15 changes comparability at the transition break.** The IASB's own staff review (below) documents reclassifications of contract assets/liabilities, changes in timing of revenue recognition (12% of a 68-entity construction sample), and changes of >10% of equity in 19% of cases. Any DSO series spanning adoption will contain artifacts.

### (g) SEC enforcement focus on revenue recognition — verified numbers

**Anti-Fraud Collaboration / Center for Audit Quality, January 2021** ([CAQ press release](https://www.thecaq.org/news/new-report-reveals-common-themes-in-sec-enforcement-of-financial-statement-fraud/)), reviewing **531 Accounting and Auditing Enforcement Releases filed 2014–2019**, identifying **140 financial statement fraud schemes across 204 enforcement actions**:

- **Improper revenue recognition: 43%** — the single most common scheme.
- Reserves manipulation: **24%**
- **Inventory misstatement: 11%**
- Loan impairment issues: **11%**
- Most-charged industries: technology services **17%**, finance **13%**, energy **11%**, manufacturing **9%**
- Most-charged individuals: **CFO 54%**, CEO 31%
- **39% of AAERs (79 actions) were against issuers with less than $250 million market capitalisation**

This is the single most useful enforcement statistic for a screener: the disclosure-quality failure mode is overwhelmingly revenue recognition, and it is concentrated in small caps. **I could not open SEC.gov's own AAER database or the SEC's Section 704 study in this session (HTTP 403, automated-tool block); the earlier, widely cited "704 study" figures are therefore UNVERIFIED here.**

### (h) ASC 606 / IFRS 15 effects — verified from the standard-setter's own literature review

Source: IASB Staff Paper 6F, March 2023, *Post-implementation Review of IFRS 15 — Review of academic literature* ([IFRS Foundation PDF](https://www.ifrs.org/content/dam/ifrs/resources-for/academics/research-citations/post-implementation-review-of-ifrs-15-march-2023.pdf)). This is the IASB's own synthesis of 21 papers; it is unusually authoritative and unusually candid about disagreement.

**Magnitude of the transition (STOXX Europe 50 sample of 48 entities, Napier & Stadler 2020):**

| Change on adoption, scaled | Mean | Median | Min | Max | # entities >0 / =0 / <0 |
|---|---|---|---|---|---|
| Retained earnings ÷ shareholders' equity | **1.88%** | 0.05% | 0% | **57.31%** | 11 / 17 / 20 |
| Revenue ÷ IFRS 15 revenue | **0.72%** | 0% | 0% | **13.12%** | 5 / 33 / 10 |
| Profit ÷ IFRS 15 revenue | **0.16%** | 0% | 0% | 1.61% | 4 / 38 / 6 |

**48% of those entities disclosed immaterial effects.** In a larger US sample of **3,019 entities** transitioning to Topic 606: **68% reported no material impact**; average cumulative adjustment to opening retained earnings **2.7% of market capitalisation**, average revenue adjustment **2.3%**, average adjustment to net income **0.6%**. **88.5% chose modified retrospective** vs 11.5% full retrospective. Most-affected industries: computers **27.6%** materially affected, fabricated products 18.2%, communication 18.1%, business services 17.9%, electronic equipment 17.8%.

**Does revenue information get better? The literature disagrees, and the IASB says so:**
- *Improvement:* analyst revenue forecast accuracy **+3.7%** and dispersion **−1.7%** (Ferreira et al.); **+8%** accuracy / **−12%** dispersion for materially impacted S&P 500 entities and **+5% / −11%** for those increasing disaggregation (Goldman et al.); **+12.5%** accuracy / **−8%** dispersion for disaggregating entities (Hinson et al.).
- *Deterioration:* one paper finds analyst revenue predictability **decreased** and information asymmetry (bid-ask spread, volatility) **increased**, with the accuracy decline explaining **8%** of the asymmetry increase (Billings et al.). Another finds **cost of debt rose by 6.5% / 22 basis points**, dissipating over time (Sadka et al.).
- *Reconciliation:* the accuracy decline **dissipated after the second quarter** post-adoption (learning), while the dispersion increase **persisted** (Hao & Pham).
- The IASB's own gloss: *"These mixed findings may be due to the sensitivity of the analyses to choices made by the researchers like sample size and type and empirical model specification."*

**Is there more discretion to manipulate revenue after 606? Yes — two papers say so.** Castro, Erdogan & Folsom (1,543 Russell 3000 entities, 2017–2020): significantly affected entities reported **higher revenue growth without higher COGS growth**, **lower changes in deferred revenue**, and were **more likely to meet-or-beat analyst targets** post-adoption — *"managers used the discretion in revenue recognition opportunistically."* Hubbard (1,271 US entities, 2016–2019): firms with meet-or-beat incentives (by ≤2 cents) reported **higher discretionary revenues**, measured as *"the unexplained portion of accrued receivables"* — i.e. **a rising-receivables metric is exactly the construct used to detect post-606 revenue management.**

**Timing effect on the revenue cycle** (Ali & Tseng, 2,226 US entities 2013–2020): the average revenue cycle **shortened from 24 to 18.7 months**; long-cycle industries (energy, real estate, auto supply chains) **28.8 → 14.7 months**; short-cycle (consumer goods) **19.6 → 19.1 months**. **This is the single most important ASC 606 fact for a DSO screen: the mapping from revenue to receivables changed structurally at adoption.**

### (i) XBRL computability (§2)

Moderate. Tags needed:
- `AccountsReceivableNetCurrent` (US-GAAP) — **note the very common issue that filers use `AccountsReceivableNetCurrent` vs `ReceivablesNetCurrent` vs `AccountsAndOtherReceivablesNetCurrent`, and that "current" receivables may be reported only in the notes.** Allowance for doubtful accounts (`AllowanceForDoubtfulAccountsReceivableCurrent`) is separately tagged and may or may not be netted.
- `Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax` (see 2f — the denominator is the risky part)
- `Assets` / `AssetsCurrent` for scaling
- For IFRS/UK filers, the receivables element is a `TradeAndOtherReceivables`-family element, not `AccountsReceivableNetCurrent`. **Unverified in-session; pin from a real instance document.**

**Compute DSO drift as the ratio-of-ratios (DSRI form) rather than a days figure** — it needs no assumption about days-per-year, no averaging convention, and it matches the only version with published coefficients.

---

## 3. Inventory build vs sales growth

### (a) Definition and formulas

```
Inventory days        = Inventory / (COGS / 365)          [or / (Revenue/365)]
Inventory growth gap  = ΔInventory% − ΔRevenue%
Inventory accrual     = ΔInventory / AverageTotalAssets
```
Chan et al.'s measure is the third form: `ΔINV` scaled by average total assets, where ΔINV is the change in inventories (Compustat item 3). Beneish's DSRI analogue for inventory is not in the 8-variable model; his inventory signals appear as *"recording fictitious inventory"* in the sample narrative rather than as a scored variable.

### (b) Originating work

Jacob K. Thomas and Huai Zhang, "Inventory Changes and Future Returns," *Review of Accounting Studies* 7(2–3), 163–187 (June 2002), DOI [10.1023/A:1020221918065](https://api.unpaywall.org/v2/10.1023/A:1020221918065?email=earnings.quality.research@gmail.com) (Unpaywall confirms `is_oa: true` at the publisher, but the Springer PDF is actually gated behind a paywall page — I could not open it). Discussion: Paul Hribar, "Discussion of 'Inventory Changes and Future Returns'," *RAS* 7, 189–193, DOI 10.1023/A:1020274002135. **No abstract is deposited in Crossref and the full text is inaccessible — Thomas & Zhang's specific effect sizes are UNVERIFIED in this report.** Related: Alan, Gaur & Gao, "Does Inventory Turnover Predict Future Stock Returns?", SSRN 2011, DOI [10.2139/ssrn.1971774](https://api.crossref.org/works?query.bibliographic=Inventory+Changes+and+Future+Returns+Thomas+Zhang&rows=3&select=title,author,container-title,issued,DOI,abstract,page,volume) — bibliographic record only, **effect sizes UNVERIFIED**.

### (c)–(d) Sample and effect sizes (from the source I *could* open)

The strongest verified inventory evidence is the **component analysis in Chan, Chan, Jegadeesh & Lakonishok**, same sample as §1 (NYSE/AMEX/Nasdaq, 1971–1995, financials excluded, annual end-April sorts). Decile sorts on **ΔInventory / average total assets**:

| | Year +1 | Year +2 | Year +3 |
|---|---|---|---|
| Raw return spread, decile 1 − decile 10 | **+9.5% (t = 4.63)** | +5.5% (t = 3.45) | +3.8% (t = 2.06) |
| **Abnormal return spread** | **+7.2% (t = 4.34)** | **+3.3% (t = 2.34)** | +1.6% (t = 0.84, insignificant) |
| Decile 10 abnormal return | **−4.3%** | −3.2% | −1.7% |
| Decile 1 abnormal return | +2.9% | +0.1% | −0.1% |

The **discretionary vs non-discretionary decomposition is the sharpest result in the whole paper**:

| Ranked by change in inventory | ΔINV discretionary, Y+1 | ΔINV non-discretionary, Y+1 |
|---|---|---|
| Raw return spread (1)−(10) | **+9.3% (t = 7.17)** | +0.8% (t = 0.33) |
| **Abnormal return spread** | **+9.1% (t = 7.02)** | **−1.5% (t = −0.71)** |

Discretionary inventory accruals — the part above what a firm's own 5-year accrual-to-sales ratio would predict — predict returns with a **7.02 t-statistic**; the non-discretionary part predicts nothing. By comparison, the discretionary ΔAR spread is +3.5% (t = 2.99) and the discretionary ΔAP spread is +4.1% (t = 4.95). Chan et al. state the conclusion directly: *"changes in inventory are by far the most important component of accruals for predicting future returns."*

Context for the inventory build: the top decile of the accruals sort shows ΔINV of **+0.134** of average total assets versus **−0.029** for the bottom decile, and top-decile firms had **average annual sales growth of 22.8% over the prior three years** versus 7.2% for the bottom decile. High inventory-accrual firms are exactly the high-growth firms whose growth is decelerating.

**The competing interpretation, from Chan et al. themselves:** the non-discretionary result rejects the pure "extrapolation" hypothesis, and the authors note the components do not fit a single story — *"the predictive power of one accrual item, changes in accounts payable, does not fit the manipulation hypothesis."* The inventory result is consistent with either (i) manipulation or (ii) delayed investor reaction to a genuine business-condition signal. Chan et al. do not resolve it.

**Sloan (1996) on inventory specifically:** the presentation of Sloan's paper that I opened does not report an inventory-component spread, so **no Sloan-specific inventory number is available here — UNVERIFIED.**

### (e) Out-of-sample / after publication

- Chan et al.'s inventory spread decays fast: **7.2% → 3.3% → 1.6%** over years +1/+2/+3, with the year-3 spread statistically indistinguishable from zero. **This is a one-year signal, not a persistent one.**
- Thomas & Zhang has not, to my verified knowledge, been subjected to the systematic replication treatment that Hou/Xue/Zhang applied to the broader library; **whether inventory-changes specifically survives their NYSE-breakpoint/value-weighted protocol is UNVERIFIED.**
- Given that inventory changes are *a component of* accruals, and the accruals anomaly has decayed to unreliability (Green/Hand/Soliman), the prudent prior is that the *tradable* inventory spread has also decayed. **This is inference, not a sourced finding — flagged.**

### (f) Practical caveats

- **Sector effects are extreme.** Inventory days for grocery retail, auto dealers, and distributors differ by an order of magnitude from software or services. Raw inventory-days levels are meaningless across sectors. Beneish's industry matching (2-digit SIC) and Chan et al.'s ΔINV/*assets* scaling are both attempts to neutralise this — neither neutralises a *days*-based screen.
- **LIFO/FIFO transitions distort ΔInventory within a firm.** Under US GAAP a voluntary LIFO liquidation or a LIFO-to-FIFO change revalues the entire inventory base in one year, producing a ΔInventory that has nothing to do with demand. **UNVERIFIED against a source in this session**; it is a mechanical accounting fact, not a measured effect.
- **Inventory write-downs and lower-of-cost-or-market charges** reduce inventory in the year they occur, making a deteriorating situation look like an improving one in the ΔInventory metric. The *right* signal (a write-down) is the opposite sign from the *screened* signal.
- **Inventory build in a genuinely growth-capex phase is not a red flag.** Chan et al.'s data show top-decile inventory-accrual firms had 22.8% trailing 3-year sales growth; some of that inventory is legitimate anticipation. The Discretionary/non-discretionary split — the part unexplained by the firm's own historical accrual-to-sales ratio — is designed precisely to separate these, and is what should be used.
- **Supply-chain / channel-inventory effects** mean a manufacturer's inventory build can be a *customer's* signal, or a deliberate strategic build against a known shortage. Not screenable from XBRL alone.

### (g) XBRL computability (§3)

Moderate-to-harder. Tags: `InventoryNet` (US-GAAP; but filers also use `InventoryFinishedGoodsNetOfReserves`, `InventoryWorkInProcess`, etc., and some report only components), `CostOfGoodsAndServicesSold` (for the days denominator — note a large taxonomy change with ASC 606's presentation of "cost of goods and services sold"), and `Revenues`/`RevenueFromContractWithCustomerExcludingAssessedTax`.

**Simplest robust construction for a screener:** use `ΔInventory / average TotalAssets` — it is *exactly* the tested measure (Chan et al.), requires only two tags (`InventoryNet`, `Assets`), and avoids the `Revenues`/`COGS` denominator problem entirely. To reproduce the discretionary decomposition you additionally need 5 years of history per firm, which is reasonable from EDGAR/Companies House filings but requires careful handling of tag changes over time.

---

## 4. The "operating cash flow to net income" ratio: documented distribution and meaningful thresholds

### What I found

**The best-documented practitioner treatment is the Georgia Tech Earnings Quality Indicator**, and it is *not* a bare OCF/NI ratio — it is a scaled difference:

```
EQI = (Operating Cash Flow − Net Income) / Revenue
    = (Operating Cash Flow / Revenue) − (Net Income / Revenue)
    = Operating Cash Margin − Net Margin
```
with **both** OCF and NI adjusted first *"for nonrecurring and non-operating items."*
Source: [Georgia Tech Financial Analysis Lab, "Earnings Quality Trends: Stabilization (Quarter 3, 2015)", May 2016, Mulford & Misra](https://www.scheller.gatech.edu/_files/pdf-pages/centers-initiatives/FinLab/gatechlab_eqi_05.07.2016.pdf). Data from S&P Capital IQ Compustat; medians for 20 GICS non-financial industry groups, quarterly data March 2000 – September 2015.

**Reported distribution (medians, all non-financial industries combined):**

| Period | Median EQI |
|---|---|
| Pre-recession, June 2007 | **4.55%** |
| Recession high, September 2009 | **11.17%** |
| September 2015 | **8.04%** |

**Industry medians, September 2015** (this table *is* the distributional evidence, and it is the reason no single threshold works):

| Industry group | Sep 2014 | Sep 2015 |
|---|---|---|
| Energy | 16.41% | **26.62%** |
| Telecommunication Services | 13.81% | **16.97%** |
| Utilities | 14.22% | **16.53%** |
| Pharmaceuticals, Biotech & Life Sciences | 11.49% | **13.99%** |
| Transportation | 8.01% | **12.16%** |
| Software & Services | 11.36% | **12.10%** |
| Semiconductor & Equipment | 9.76% | 9.30% |
| Media | 8.93% | 8.96% |
| Materials | 5.16% | 8.26% |
| Consumer Services | 7.50% | 7.56% |
| Health Care Equipment & Services | 6.12% | 5.61% |
| Technology Hardware & Equipment | 5.10% | 5.60% |
| Household & Personal Products | 4.59% | 5.33% |
| Commercial & Professional Services | 4.85% | 4.71% |
| Food, Beverage & Tobacco | 2.78% | 4.45% |
| Capital Goods | 2.58% | 3.45% |
| Automobiles & Components | 2.65% | 3.45% |
| Retailing | 3.04% | 2.50% |
| Food & Staples Retailing | 2.03% | 2.17% |
| Consumer Durables & Apparel | 0.75% | 1.81% |

**Interpretation guidance, verbatim:** *"Significant decreases in the ratio over time are of particular concern and indicate that operating cash flow is either growing slower or declining faster than net income, leading to a build-up of non-cash balance sheet accounts and warning of possible operational difficulties or of aggressive practices in the measurement of earnings... A steady to slightly increasing ratio over time indicates an equilibrium relationship."* The Lab's "Stable" band is defined as within **±15%** change year-on-year.

**Critically, the Lab's own interpretive rule is about the TREND, not the LEVEL.** They do not publish a threshold above or below which a firm is "bad." They publish a *stability* criterion. This is the honest state of the art.

### What is UNVERIFIED

**I could not find any credible source documenting a distribution of the bare ratio OCF/NI, nor any sourced threshold (e.g. "< 0.8 for three years").** The search surfaced only vendor/blog material — [metricduck.com](https://www.metricduck.com/blog/earnings-quality-complete-framework), [pomegra.io](https://pomegra.io/learn/library/track-b-stock-sales-core/fundamental-analysis/chapter-11-earnings-quality/cash-conversion-ratio), [nzxplorer.co.nz](https://nzxplorer.co.nz/insights/earnings-quality), [accaw.com](https://www.accaw.com/accounting_qa/cash-flow-earnings-quality-assessment.php) — which the brief correctly tells me to treat as blogspam/vendor marketing. **I did not open them and I cite them here only to record that they exist and were excluded.** The bare-ratio threshold is **UNVERIFIED** and, on the evidence above, likely to be harmful: the ratio blows up when NI is near zero or negative, which is precisely the population of interest.

**Recommended substitute, grounded in what is verified:** rank firms within GICS industry group on `(OCF − NI)/Revenue` (EQI), require that it be *stable or rising* against the firm's own 3-year trend (the ±15% band the Georgia Tech Lab uses), and cross-check against the accruals measure in §1 computed from the cash-flow statement. Do not use a bare OCF/NI < 1 threshold.

---

## 5. Cross-cutting: how much should you trust any of this?

Ranked by evidentiary strength:

**(a) Robust and replicated**
- Accruals predict lower future earnings persistence and lower future returns; cash flow is more persistent than accruals (Sloan 1996; independently reproduced by Chan et al. with a 7.4% decile spread at t = 3.83; reproduced in Richardson et al. 2005 → Dey & Lim 2015; the mechanism is confirmed at scale).
- Accrual *reliability* matters: less reliable accruals → lower persistence (Richardson et al. 2005, replicated by Dey & Lim 2015 with newer US data).
- Improper revenue recognition is the most common SEC financial-statement fraud scheme (43% of 140 schemes across 204 actions, 2014–2019).
- ASC 606 / IFRS 15 changed the revenue-to-receivables mapping (average revenue cycle 24 → 18.7 months) and created discretion that managers used (two independent papers).

**(b) Published, credible, but not independently replicated here**
- Beneish's DSRI and M-score: real holdout test (coefficients 1982–88, holdout 1989–92), but a 50% manipulator miss rate in holdout and a disputed subsequent return-prediction claim (Beneish/Lee/Nichols 2013 drew a published author response).
- Chan et al.'s discretionary-inventory result (AR spread +9.1%, t = 7.02) — striking, but it is one paper's decomposition, and the decomposition method matters.
- Georgia Tech EQI — a single lab's series; methodologically careful, but descriptive rather than predictive (no return tests published in the report I opened).

**(c) Contested or substantially decayed**
- **Trading returns to the accruals anomaly in US markets.** Green/Hand/Soliman: *"no longer reliably positive."* McLean & Pontiff: ~35% average post-publication decay across 82 characteristics. Hou/Xue/Zhang: 64% of 447 anomalies insignificant at 5%, 85% at t = 3. **Use accruals as a quality flag, not a factor.**
- Beneish M-score as an alpha signal — contested, unresolved here.

**(d) Not verified at all (do not cite internally)**
- Sloan's exact 10.4% hedge return (secondary source only).
- Thomas & Zhang's specific effect sizes (paywalled, no abstract).
- Hirshleifer et al.'s NOA spread magnitude (abstract confirms direction and 1964–2002 sample; no number).
- Beneish/Lee/Nichols 2013 effect sizes.
- Richardson et al. 2005 specific coefficients.
- The published (2016) McLean & Pontiff decay figures.
- The IFRS 16 / ASC 842 effect on OCF comparability, and the receivables-factoring distortion of DSO — both are mechanical claims I have reasoned through but could not source in this session.
- Exact IFRS/UK iXBRL element names.
- Any SEC.gov or data.sec.gov content (HTTP 403 throughout).

---

## 6. Confidence and gaps

**Confidence: moderate-high on direction, low on magnitudes and thresholds.**

What I am confident about: the accruals/earnings-quality *direction* is among the most replicated results in accounting; DSO drift and inventory build are documented components with published coefficients; the SEC's enforcement concentration in revenue recognition is quantified; and the post-publication decay of the tradable accruals spread is documented by the anomaly's own discoverers.

What I could not do, and why:
1. **SEC.gov and data.sec.gov blocked this session (HTTP 403, "automated tool").** I could not open the SEC's taxonomy viewer, EDGAR XBRL APIs, the Section 704 study, or any AAER text. SEC enforcement evidence here comes from the CAQ/Anti-Fraud Collaboration summary, not from the SEC directly.
2. **SSRN, Wiley, ScienceDirect, Springer, INFORMS and Semantic Scholar full text all blocked (403/CAPTCHA).** This is why Sloan, Thomas & Zhang, Richardson et al., Hirshleifer et al. and Beneish/Lee/Nichols are represented by publisher abstracts and bibliographic records rather than full text. Where an abstract is silent on effect size, I have said so rather than estimating.
3. **No open-access copy of Sloan (1996) exists** (Unpaywall: `oa_status: closed`). The 10.4% figure rests on a secondary course presentation. Everything else about Sloan's method and sample is corroborated by Chan et al.'s independent replication.
4. **"Cumulative OCF/NI" as a named screen does not appear to exist in the literature.** I searched for it directly and found nothing. The nearest tested constructs are asset-scaled accruals and net operating assets. If the product needs this flag, it is an untested composite and should be labelled as such in the UI.
5. **I found no credible source for a bare OCF/NI ratio distribution or threshold.** Only excluded vendor blogs. The Georgia Tech EQI is the defensible substitute.

**Highest-value next steps for whoever picks this up:**
- Obtain Richardson, Sloan, Soliman & Tuna (2005) and Thomas & Zhang (2002) through an institutional subscription; both are load-bearing and currently UNVERIFIED.
- Obtain the Beneish/Lee/Nichols (2013) FAJ paper **and** the published critique it drew (DOI 10.2469/faj.v69.n5.8) before shipping any M-score feature.
- Confirm the exact IFRS/UK iXBRL element names from real filed instance documents (SEC and IFRS taxonomy browsers were unreachable here).
- Backtest the decay claims on your own universe and period — the entire point of Green/Hand/Soliman and Hou/Xue/Zhang is that in-sample magnitudes do not survive.
