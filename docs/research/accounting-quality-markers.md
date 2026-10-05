# Accounting-Quality and Earnings-Manipulation Markers

**Scope.** Markers that can be computed from annual/interim financial statements (SEC EDGAR XBRL, UK Companies House iXBRL) for a personal equity research tool. No intraday data, no analyst estimates, no text analytics.

**Sourcing standard used throughout.** Every substantive claim carries a link to a page that was actually retrieved. Paywalled originals are marked **UNVERIFIED** where the underlying number could not be read, even when a secondary source quotes it. Where sources disagree, both are given. Findings are labelled:

- **[A] Robust / replicated** — survived independent replication or multi-decade out-of-sample testing.
- **[B] Published once** — credible origin but no independent replication found.
- **[C] Contested / decayed** — replication found weaker or absent effects.
- **[D] Practitioner construct** — no academic validation found; mechanical hypothesis only.

---

## Summary table

| # | Marker | What it predicts | Evidence strength | Implementation cost |
|---|---|---|---|---|
| 1 | Cash-flow-statement accruals (NI − CFO)/avg assets | Earnings persistence; return underperformance; restatement risk | **[A]** direction; **[C]** return magnitude today | **Low** — 3 XBRL tags |
| 2 | Balance-sheet total accruals (Sloan original) | Same, but noisier | **[A]** direction; **[C]** magnitude; measured measurement-error critique | **Medium** — ~7 tags, M&A contamination |
| 3 | Beneish M-score (8 variables) | SEC enforcement / discovered earnings manipulation | **[B]** own holdout (50% manipulator miss); **[C]** as an alpha signal | **Low–Medium** — 8 ratios, 2 years |
| 4 | Altman Z / Z′ / Z″-EM | Bankruptcy, mainly at 1-year horizon | **[A]** ~80–90% at 1 yr on 1960s–90s US manufacturers; **[C]** today, and asymmetric (good at clearing, poor at catching) | **Low formula, Medium–High coverage** — X1 missing for ~21% of US filers; X3/X5 legally absent for UK small/micro filers (§3a, §3b) |
| 5 | Ohlson O-score | Bankruptcy probability (logit) | **[B]** in-sample; **[C]** out-of-sample AUC ~0.70–0.74 | **Low–Medium** — needs GNP deflator; FFO proxy |
| 6 | Zmijewski probit | Bankruptcy | **[B]**/**[C]** — original coefficients from one thesis; critics call it effectively one-variable | **Low** |
| 7 | Dechow F-score | Material misstatement (AAER/restatement) | **[B]** in-sample; **[C]** out-of-sample (AUC 0.554) | **Low–Medium** — 7 variables, 1 subtle |
| 8 | Piotroski F-score (9 signals) | "Fundamental momentum" within high book-to-market stocks | **[A]** in original setting and internationally (EW); **[C]** US value-weighted post-1997 | **Low** — 2 years of data |
| 9 | Cash conversion: OCF vs NI, multi-year | Earnings quality / accrual build-up | **[A]** as accrual proxy; **[D]** as a bare "<1" threshold | **Low** |
| 10 | DSO drift / DSRI | Revenue-recognition inflation | **[A]** as part of accruals; **[B]** standalone (+3.1%, t = 2.23) | **Low–Medium** — revenue tag ambiguity |
| 11 | Inventory build (ΔINV/assets) | Near-term underperformance | **[A]** — strongest single accrual component (+9.1%, t = 7.02 discretionary) | **Low** |
| 12 | Goodwill load / economic impairment | Impairment is overdue; slow write-off risk | **[A]** untimeliness (75–80% not written down); **[B]** prediction models | **Low–Medium** |
| 13 | Non-GAAP vs statutory gap | SEC comment letters, Reg G violations | **[A]** for exclusion *quality*; magnitude does **not** predict | **High** — not in XBRL at all |
| 14 | Restatement (8-K 4.02) | Returns −2% to −14%; fraud tail | **[A]** | **Low** once filing metadata is ingested |
| 15 | Auditor change (8-K 4.01) | Restatement, ~2.6× lift | **[B]** backward-conditional only | **Low** once filing metadata is ingested |
| 16 | Late filing (NT 10-K / 10-Q) | SEC scrutiny, management turnover (OR 1.40) | **[B]** for regulatory stress; **[C]** for returns | **Low** once filing metadata is ingested |
| 17 | Going-concern opinion | Bankruptcy within 1 yr | **[B]** — ~60% sensitivity, ~2% precision | **High** — text only |
| 18 | Operating leases (IFRS 16 / ASC 842) | Comparability break, not a predictor | **[A]** — 22–45% pre-2019 liability understatement; +21–25% D/E post-adoption | **Low** post-2019; **High** for a consistent series |
| 19 | SPVs / off-balance-sheet entities | Concealed leverage | **[B]** case-based; no validated screen | **High** — notes parsing |
| 20 | Receivables factoring / supply-chain finance | Flattered OCF and DSO | **[B]** mechanism + Carillion (FRC); **[D]** as a screen | **High** — disclosure-dependent |

**Cross-cutting result that governs everything below:** published anomalies decay. McLean & Pontiff, studying 97 predictors, report average monthly returns of 0.582% in-sample, 0.402% out-of-sample pre-publication, and 0.264% post-publication — a 26-percentage-point drop out-of-sample and 58 ppts post-publication, with the extra 32 ppts attributed to informed trading ([CFA Institute digest of McLean & Pontiff 2016](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary)). Hou, Xue & Zhang replicate 447 anomalies: 286 (64%) are insignificant at 5%, rising to 380 (85%) at a t-cutoff of three, and "even for the 161 significant anomalies, their magnitudes are often much lower than originally reported" ([NBER w23394](https://www.nber.org/papers/w23394)).

**Design implication:** treat all of these as *risk flags and ranking inputs*, not as standalone return factors.

---

## 1. Accruals and the accruals anomaly (Sloan 1996)

**Definition.** Accruals are the non-cash component of earnings. High accruals mean reported profit is running ahead of cash generation and is therefore less persistent.

**Originating paper.** Richard G. Sloan, "Do Stock Prices Fully Reflect Information in Accruals and Cash Flows about Future Earnings?", *The Accounting Review* 71(3), July 1996, pp. 289–315 ([JSTOR record](https://www.jstor.org/stable/248290)).

**Sample.** 40,679 US non-financial firm-year observations, 1962–1991, Compustat + CRSP, financial firms excluded. Confirmed from two independent retellings of the paper ([Erasmus University thesis appendix, Table 2](https://thesis.eur.nl/pub/53963/368420kf-19952.pdf); [course slide deck reproduction of the paper](https://www.renrendoc.com/paper/209447697.html)).

**Formulas.**

*Cash-flow-statement approach (use this one):*
```
Accruals_t = (NetIncomeLoss_t − NetCashProvidedByUsedInOperatingActivities_t) / average(TotalAssets_t, TotalAssets_{t−1})
```
*Balance-sheet approach (Sloan's original):*
```
Accruals = (ΔCurrentAssets − ΔCash) − (ΔCurrentLiabilities − ΔCurrentMaturitiesOfLTD − ΔIncomeTaxPayable) − DepreciationAndAmortisation
```
scaled by average total assets. This is the version implemented in Ball et al. (2016) replications and reproduced, with the SAS code, in [Du, Wang & Wei (2021, *Pacific-Basin Finance Journal*)](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf).

**Reported effect size.** Sloan's own hedge-portfolio magnitude is widely quoted as roughly 10% per year, but I could **not** open the primary paper (JSTOR paywall) and the only sources I could reach that state the figure are a secondary teaching reproduction and a machine-generated blog. **Treat the ~10% number as UNVERIFIED against the primary source.**

What I *can* verify with numbers is the replication-era spread. Chan, Chan, Jegadeesh & Lakonishok (NBER w8308), using NYSE/AMEX/Nasdaq 1971–1995 with financials (SIC 6000–6999) excluded and annual sorts at end-April, report accrual decile 1 earning **+2.6%** abnormal in year +1 and decile 10 **−4.7%**, a **spread of +7.4% (t = 3.83)**; +4.4% (t = 2.97) in year +2 and +4.3% (t = 2.48) in year +3, with a raw spread of +8.8%. Decile-10 firms showed earnings equal to 17.6% of assets but operating cash flow of **−1.3%** (as extracted from [Du, Wang & Wei's replication](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf), which itself reproduces the Ball et al. Fama-MacBeth coefficient on accruals of **−1.05, t = −3.55**).

**Did it hold up?**

This is the single most important disagreement in the literature, and both sides are credible.

- **Decayed.** Green, Hand & Soliman, *Management Science* 57(5), 2011, pp. 797–816, state that hedge returns to the accruals anomaly "appear to have decayed in U.S. stock markets to the point that they are, on average, no longer reliably positive," attributing this "in part [to] an increase in the amount of capital invested by hedge funds into exploiting it" ([EconPapers abstract](https://econpapers.repec.org/article/inmormnsc/v_3a57_3ay_3a2011_3ai_3a5_3ap_3a797-816.htm)). A 2021 replication finds that when restricted to recent sample periods "the slope coefficients on ACC become insignificant, which is consistent with the decaying trend of the accruals anomaly in recent years (Green et al., 2011)" ([Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)).
- **Persisted.** Lev & Nissim, "The Persistence of the Accruals Anomaly," *Contemporary Accounting Research* 23(1), 2006, pp. 193–226, reach the opposite conclusion: "We show that the accruals anomaly still persists and, even more strikingly, its magnitude has not declined over time," arguing that institutions shun extreme-accrual firms because they are small, unprofitable and risky, and that information and transaction costs deter retail investors ([Tel Aviv University CRIS record](https://cris.tau.ac.il/en/publications/la-persistance-de-lanomalie-des-ajustements-comptables/)).
- **Subsumed.** Ball, Gerakos, Linnainmaa & Nikolaev (2016, *JFE*) find cash-based operating profitability subsumes both accruals and operating profitability in US returns; the replication in Du, Wang & Wei confirms this for the US but finds the reverse ordering in China ([link](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)).
- **Cross-market.** The anomaly is weaker or absent outside the US: in China, portfolio sorts on accruals produce no significant hedge returns over July 1999–December 2018 ([Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)).

**Caveats.**
- **Measurement error.** Hribar & Collins (2002, *JAR* 40(1) 105–134) show balance-sheet accruals are contaminated by M&A, discontinued operations and reclassifications, and systematically misclassify "extreme accrual" firms. Use the cash-flow-statement approach (cited in [Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)).
- **Sector.** Exclude banks, insurers and REITs. Accruals are not meaningful for financial firms.
- **Size.** Extreme accruals concentrate in small, risky, low-profitability firms ([Lev & Nissim](https://cris.tau.ac.il/en/publications/la-persistance-de-lanomalie-des-ajustements-comptables/)).
- **Standard changes.** Leases moving on-balance-sheet under ASC 842 / IFRS 16 mechanically lift reported operating cash flow for lessees, which breaks accrual comparability across the 2019 boundary. **UNVERIFIED** against a standard-setter document — test on your own data rather than assuming the sign or size.

**XBRL difficulty: Low.** `NetIncomeLoss`, `NetCashProvidedByUsedInOperatingActivities`, `Assets`. The balance-sheet version needs `AssetsCurrent`, `CashAndCashEquivalentsAtCarryingValue`, `LiabilitiesCurrent`, `LongTermDebtCurrent`, `AccruedIncomeTaxesCurrent`, `DepreciationDepletionAndAmortization`. IFRS/UK filers use a different family (`ProfitLoss`, cash-flow-from-operating-activities elements) — pin exact element names from real filed instance documents before coding.

---

## 2. Beneish M-score

**Definition.** An eight-variable probit model that discriminates firms later found to have manipulated earnings from industry-matched non-manipulators.

**Originating paper.** Messod D. Beneish, "The Detection of Earnings Manipulation," *Financial Analysts Journal* 55(5), 1999, pp. 24–36. I read the full June-1999 working-paper text, which contains the estimation tables and the sample construction ([working paper text](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)). Formula confirmed against [Wikipedia's Beneish M-score entry](https://en.wikipedia.org/wiki/Beneish_M-score).

**Formula.**
```
M = −4.84 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI
        + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI
```
| Variable | Definition |
|---|---|
| DSRI | (Receivables_t / Sales_t) ÷ (Receivables_{t−1} / Sales_{t−1}) |
| GMI | [Gross margin_{t−1}] ÷ [Gross margin_t] (margin expressed as (Sales − COGS)/Sales) |
| AQI | [1 − (CurrentAssets + PPE + Securities)/TotalAssets]_t ÷ [same]_{t−1} |
| SGI | Sales_t / Sales_{t−1} |
| DEPI | [Depreciation_{t−1}/(Depreciation_{t−1}+PPE_{t−1})] ÷ [Depreciation_t/(Depreciation_t+PPE_t)] |
| SGAI | (SG&A_t / Sales_t) ÷ (SG&A_{t−1} / Sales_{t−1}) |
| LVGI | [(LongTermDebt + CurrentLiabilities)/TotalAssets]_t ÷ [same]_{t−1} |
| TATA | (Income from continuing operations_t − Cash flow from operations_t) / TotalAssets_t |

Flag threshold: **M > −1.78**.

**Sample.** 74 earnings manipulators — 49 from SEC AAERs #132–502 (issued 1987–1993) and 25 from a LEXIS/NEXIS news search — plus 2,332 Compustat non-manipulators matched on 2-digit SIC and year, spanning 1982–1992. Estimation sample: 50 manipulators and 1,708 controls, 1982–1988. Holdout: 24 manipulators and 624 controls, 1989–1992 ([working paper](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)).

**Reported effect sizes (from the paper's own tables).**

| Metric | Estimation sample | Holdout sample |
|---|---|---|
| Pseudo-R² | 30.6% (WESML) / 37.1% (unweighted probit) | — |
| Manipulator-years correctly classified | 58–76% | **37.5–56%** |
| Non-manipulator-years misclassified | 7.6–17.5% | 3.5–9.1% |
| At error-cost ratio 20:1 to 30:1 (M > −1.78) | misses 26% of manipulators, 13.8% of non-manipulators | **misses 50% of manipulators**, 7.2% of non-manipulators |

The model's expected misclassification cost is 0.58–0.62 of a naive "call every firm clean" rule ([working paper](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)).

Two further numbers that matter for economic interpretation, both from the same paper: sample manipulators' **median sales growth was 34.4% versus 9.4%** for controls, and the typical manipulator loses **about 40% of market value on a risk-adjusted basis in the quarter the manipulation is discovered**.

**Component significance.** In the unweighted probit, DSRI carries the second-largest t-statistic (0.920, t = 6.02) after SGI, and the median DSRI is 1.281 for manipulators versus 0.996 for controls (p = .000). Critically, **Beneish's own accruals-to-total-assets coefficient is insignificant** (−0.327, t = −1.22) — the revenue-side variable, not the accrual variable, does the work in his model.

**Did it hold up?**
- Beneish's own holdout test passed but with a **50% miss rate on manipulators** ([working paper](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)).
- Out-of-sample in a non-US setting, it is close to useless. A 2022–2024 study of 50 Indonesian Stock Exchange infrastructure/construction/property/real-estate firms (150 firm-years, 57 flagged as fraud-risk on restatement/sanction/observation criteria) reports Beneish M-score accuracy **58.67%**, sensitivity **40.35%**, precision **45.10%**, F1 **42.59%**, and **AUC 0.513** — indistinguishable from a coin flip ([Haryadi, Nurmalasari & Yanti, *E-Jurnal Akuntansi* 36(2)](https://ejournal1.unud.ac.id/index.php/akuntansi/article/download/3488/2119)).
- A published critique exists: Beneish, Lee & Nichols (2013, *FAJ* 69(2) 57–82) drew an "Author Response" in *FAJ* 69(5) p.14. Both are paywalled and I could not resolve the dispute. **UNVERIFIED — do not ship an M-score return factor without reading both.**

**Caveats.**
- **Sector.** Financial institutions were excluded from the original sample because sales and receivables are not meaningful for them ([Wikipedia](https://en.wikipedia.org/wiki/Beneish_M-score)). Do not apply to banks or insurers.
- **Base rate.** Roughly half a percent of Compustat firms are subject to a manipulation-year AAER in a given year ([Dechow's own CARE Conference slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf)). At that base rate, the precision of any flag is dominated by the false-positive rate.
- **Threshold drift.** Practitioner sources use −2.22 as well as −1.78 (the Indonesian study above uses −2.22 while citing −1.78-era coefficients). Pick one and hold it.
- **Standard changes.** ASC 606 / IFRS 15 changed the revenue-to-receivables mapping structurally — see §10.

**XBRL difficulty: Low–Medium.** Eight ratios, two consecutive years. Requires a reliable `Revenues` choice (see §10) and `SellingGeneralAndAdministrativeExpense`, which many filers tag irregularly or not at all. Beneish's own convention was to set SGAI and DEPI to the neutral value 1 when the input was missing — replicate that, or you will drop a large share of the universe.

---

## 3. Altman Z-score and its variants

**Definition.** A discriminant function combining five accounting ratios to predict bankruptcy within two years.

**Originating paper.** Edward I. Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy," *Journal of Finance* 23(4), September 1968, pp. 189–209.

**Original formula (Altman's own 2000 restatement).** Altman gives the 1968 function in its original scaling:
```
Z = 0.012·X1 + 0.014·X2 + 0.033·X3 + 0.006·X4 + 0.999·X5
```
with X1 = working capital / total assets; X2 = retained earnings / total assets; X3 = EBIT / total assets; X4 = market value of equity / book value of total liabilities; X5 = sales / total assets.

**The "1.2 / 1.4 / 3.3 / 0.6 / 1.0" form is the same model, rescaled.** X1–X4 are entered as *percentages* (10.0%, not 0.10) while X5 is entered as a plain ratio (200% as 2.0). Multiplying the original coefficients by 100 for X1–X4 yields 1.2, 1.4, 3.3, 0.6; X5 keeps its 0.999 ≈ 1.0. Altman states the two forms give identical scores, classifications and cutoffs. **This matters because most secondary sources present only the rescaled form without the inputs convention — mixing the two produces nonsense.**

Zones: **Z > 2.99 safe; 1.81–2.99 "zone of ignorance"; Z < 1.81 distress.** Altman's own stated preference is to use the lower bound of the grey zone, 1.81, rather than 2.675, because "the latter resulted in the lowest overall error in the original tests."

Source for the formula, the rescaling note, the zone guidance and the tables below: Altman, "Predicting Financial Distress of Companies: Revisiting the Z-Score and ZETA Models," NYU Stern working paper, July 2000 ([archived PDF](http://web.archive.org/web/20240717121208if_/https://pages.stern.nyu.edu/~ealtman/Zscores.pdf)). This paper reproduces the 1968 estimation tables, so the 1968 attributions below rest on Altman's own later restatement of them; the 1968 *Journal of Finance* article itself (23(4), 589–609) is closed access and was not opened.

**Original sample.** **66 corporations — 33 bankrupt and 33 non-bankrupt, as matched pairs.** The bankrupt firms filed petitions under Chapter X of the National Bankruptcy Act **between 1946 and 1965**. The control group was "a paired sample of manufacturing firms chosen on a stratified random basis… stratified by **industry and by size**, with the asset size range restricted to between **$1 and $25 [million]**." Data came from financial statements dated one annual reporting period prior to bankruptcy, an average lead time of about 7.5 months. 22 candidate variables were reduced to 5 ([Altman 2000](http://web.archive.org/web/20240717121208if_/https://pages.stern.nyu.edu/~ealtman/Zscores.pdf)).

**Correcting the record: Wikipedia is wrong about Altman's accuracy.** The Wikipedia article states the Z-score "was found to be 72% accurate in predicting bankruptcy two years before the event, with a Type II error (false negatives) of 6%." Altman's own tables say otherwise. His Table 2, "Classification Results, Original Sample":

| | Correct | % correct | % error | n |
|---|---|---|---|---|
| Type I (bankrupts) | 31 | **94%** | **6%** | 33 |
| Type II (non-bankrupts) | 32 | **97%** | **3%** | 33 |
| Total | 63 | **95%** | **5%** | 66 |

The 72% figure comes from Altman's Table 3 — a **one-year-prior** test in which Type I was 23/32 = 72% correct (28% error) and Type II 31/33 = 94% correct (6% error), 54/65 = 83% overall. Wikipedia has conflated the two tables and mislabelled which quantity is 6%. **Use Altman's Table 2/3.**

Two additional original-sample tests from the same paper: a fresh sample of **25 bankrupt firms was classified 24 correct (96%)**, and a sample of **66 loss-making manufacturers** saw 14 of 66 classified bankrupt (52 correct = 79%, t = 4.8, p < 0.001).

**Group means disagree across sources.** Altman (2000) gives Group 1 = **−0.29**, Group 2 = **+5.02** (F = 20.7); Wikipedia gives −0.25 and +4.48. **Unresolved — I report both.**

**Variants.** All three are now **verified against Altman's own 2000 text**, not secondary sources:

| Variant | Formula | Zones |
|---|---|---|
| **Z′ (private manufacturing)** | **0.717·X1 + 0.847·X2 + 3.107·X3 + 0.420·X4 + 0.998·X5** | Z′ > 2.90 safe; 1.23–2.90 grey; < 1.23 distress |
| **Z″ (private / non-manufacturing)** | **6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4** | Z″ > 2.6 safe; 1.1–2.6 grey; < 1.1 distress |
| **Z″-EM (emerging markets)** | **3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4** | same zones as Z″ |

with X1 = (current assets − current liabilities) / total assets; X2 = retained earnings / total assets; X3 = EBIT / total assets; **X4 = book value of equity / total liabilities** — book, not market — and **X5 dropped entirely in Z″**. Z′ retains X5 but switches X4 to book equity.

**Verification status — upgraded from "Wikipedia only" to primary.** The leading **6.56** coefficient for Z″ is now confirmed from Altman's own paper, not just Wikipedia. The earlier caveat in this report (that 6.56 rested on Wikipedia because both accessible PDFs lost it to subset-font extraction failure) is **withdrawn**.

**The Z″-EM constant's purpose is now sourced rather than inferred.** Altman's own words: *"In the emerging market model, we added a constant term of +3.25 so as to standardize the scores with a score of zero (0) equated to a D (default) rated bond."* The model originates with **Altman, Hartzell & Peck (1995), Salomon Brothers** — it is not part of the 1968 or 2000 papers proper.

**Why the coefficients differ — Altman's own words, and they matter more than the specific numbers.** "I advocate a complete reestimation… One expects that **all of the coefficients will change (not only the new variable's parameter)**." That is the general principle: removing a variable or changing the sample re-estimates every weight, so the variants are not rescalings of one another and their coefficients are not interchangeable across populations.

**A lease tie-in worth noting.** Altman explicitly recommends Z″ for exactly the pre-IFRS 16 problem: it *"is also useful within an industry where the type of financing of assets differs greatly among firms and important adjustments, **like lease capitalization, are not made**."* In other words, Z″ was designed to tolerate un-capitalised leases — which is an argument for preferring Z″ over the original Z on any pre-2019 or cross-border data (see §14).

**Altman's own post-publication accuracy.**

| Test | Result |
|---|---|
| Post-1968 distressed samples: 86 firms 1969–1975, 110 bankrupts 1976–1995, 120 from 1997–1999 | "the Z-Score model, using a cutoff score of 2.675, was between **82% and 94% accurate**" |
| Summary statement | "the predictive accuracy of the Z-Score model on samples of distressed firms has been in the vicinity of **80–90%**, based on data from one financial reporting period prior to bankruptcy" |
| Aggregate score distribution | "In 1999, the proportion of U.S. industrial firms, comprised in the Compustat data tapes, that had Z-Scores below 1.81 was over 20%" |

**Altman's Table 5, Type I accuracy at the 2.675 cutoff** (his own numbers):

| Sample | Original | Holdout | 1969–75 | 1976–95 | 1997–99 |
|---|---|---|---|---|---|
| Type I accuracy | 94% | **96%** | 82% | 85% | **94%** (113 of 120) |

**And his own admission of drift, verbatim:** *"In the last decade, however, the Type II accuracy, has increased to about **15–20%** of those manufacturing firms listed on Compustat."* This is important because it cuts against the simple "the model has decayed" story: Altman's *Type I* accuracy in 1997–99 was as good as in 1968, while the false-positive problem worsened. **The failure mode is over-flagging healthy firms, not missing failures.**

**The horizon table that actually matters.** Altman's Table 9 applies the 1968 Z to the ZETA sample by years prior to bankruptcy:

| Years prior | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Bankrupt-firm accuracy | **93.9%** | **71.9%** | **48.3%** | **28.6%** | **36.0%** |
| Non-bankrupt-firm accuracy | 97.0% | 93.9% | n.a. | n.a. | n.a. |

Altman's own gloss: "by the fifth year, the ZETA model is still about 70% accurate but the Z-Score's accuracy falls to 36%." He also warns that the original 95% is upward-biased ([Altman 2000](http://web.archive.org/web/20240717121208if_/https://pages.stern.nyu.edu/~ealtman/Zscores.pdf)).

**Out-of-sample performance on modern data is much weaker than the headline** — but note the class-imbalance distortion in every "accuracy" figure:

| Source | Sample | In-sample overall | % of *bankrupts* caught | Out-of-sample AUC |
|---|---|---|---|---|
| Bouwmeester (Univ. of Twente, 2020) | Dutch & Belgian public and large private firms | Altman (1983) variant **93.47%** | **only 32.39%** | — |
| Same, Ohlson variables | same | 95.01% | 47.89% | **0.696 / 0.738 / 0.717** (MDA / logit / probit) |
| Same, Zmijewski variables | same | 94.37% | 38.03% | **0.683 / 0.697 / 0.690** |
| Haryadi et al. (2026) | Indonesian listed infrastructure/construction/property, 2022–2024, n = 150 | accuracy **68.00%**, F1 62.50% | sensitivity 70.18% | **0.742** |

([Bouwmeester thesis](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf); [Haryadi et al.](https://ejournal1.unud.ac.id/index.php/akuntansi/article/download/3488/2119)).

**The arithmetic that destroys every headline "accuracy" number.** A Tilburg thesis spells it out for Ohlson's sample: "even when the model predicts bankruptcy in all cases, the percentage correctly classified is 2058/(2058+105) = **95.15%**" ([PDF](http://arno.uvt.nl/show.cgi?fid=135794)). At a 5% bankruptcy base rate, a model that classifies everything as healthy scores 95%. **Always report Type I and Type II separately; never accept a single accuracy percentage.**

**Did it hold up?**
- **Long-standing methodological criticism, never rebutted:** Johnson (1970), *Journal of Finance* 25(5) 1166–1168, called such work "largely descriptive statements devoid of predictive content… Altman demonstrates that failed and non-failed firms have dissimilar ratios, not that ratios have predictive power. But the crucial problem is to make an inference in the reverse direction, i.e., from ratios to failures."
- **Modern default prediction has moved on:** "Modern academic default and bankruptcy prediction models rely heavily on market-based data rather than the accounting ratios predominant in the Altman Z-score" ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score), citing Shumway 2001, Campbell/Hilscher/Szilagyi 2008, Li & Faff 2019).
- **Peer-reviewed replication finds the asymmetry matters more than the average.** Daskalakis et al. (2022), Greek listed firms 2010–2019 (n = 52): "the original models are significantly biased against viable companies, but predict with almost perfect accuracy non-viable companies' bankruptcy"; re-estimating coefficients locally "significantly impro[ves] results as regards correctly predicting viable companies, at the expense of slightly decreased, but still high, non-viable companies' bankruptcy prediction rates."
- **The honest verdict.** The durable, replicated claim is **~80–90% accuracy one financial year prior, on 1960s–1990s US manufacturers, collapsing beyond two years**. Altman's own later tests (82–94%) do *not* show monotonic decline, so the popular claim that "Z has decayed over time" is **partially supported, not established**. What *is* established is that out-of-sample the model is far better at clearing healthy firms than at catching failures — the exact opposite of what a red-flag screen needs.

---

### 3c. The out-of-sample test that settles the question

**Hillegeist, Keating, Cram & Lundstedt (2004)** is the most damaging single study, and it is the one to cite. Sample: **78,100 firm-years and 756 bankruptcies, 1980–2000** ([full text read](https://www.hbs.edu/ris/Publication%20Files/00-038_4894cd0b-2f13-4b31-a1d3-5f9a5f0e5f5f.pdf) — see also the report's own citation).

Explanatory power, measured as pseudo-R²:

| Model | Pseudo-R² |
|---|---|
| Altman Z-Score | **0.07** |
| Altman Z-Score, re-estimated | 0.06 |
| Ohlson O-Score | 0.09 |
| Ohlson O-Score, re-estimated | 0.10 |
| **BSM-Prob** (market-based, Black–Scholes–Merton) | **0.12** |

"BSM-Prob outperforms the original Z-Score and O-Score by **71% and 33%**."

Two findings from that paper matter more than the ranking:

1. **Most of Altman's variables are statistically insignificant out-of-sample.** "only two of the Altman variables, VE/TL and EBIT/TA, are statistically significant… **WC/TA, RE/TA, and S/TA, are insignificant**." That is X1, X2 and X5 — three of the five inputs — failing to carry information in a modern sample. For Ohlson, "**five of the eight significant coefficients have different signs**."
2. **Re-estimating made Z worse.** "Z-Score outperforms Z-Score_u." This directly contradicts the intuitive fix of recalibrating coefficients on newer data.

**Agarwal & Taffler (2007)** supply the cleanest population-level datum. Applying Altman's 1968 model to US non-financial NYSE/AMEX/NASDAQ firms, 1988–2003: **"almost half of these firms (47%) have a z-score less than Altman's optimal cut-off of 2.675. In addition, 19% of the firms entering Chapter 11 during this period had z-scores greater than 2.675."** A screen that flags 47% of the population while missing 19% of actual failures is not usable as a filter.

Their methodological criticism is the sharpest in the literature and explains *why* the original 95% was never a forecast: matched-pair studies "**do not provide a true test of ex ante forecasting ability as the key issue of type II error rates… is not addressed.**"

**Begley, Ming & Watts (1996)** found the models "do not perform as well in more recent periods (in particular, the 1980s), even when the coefficients are re-estimated," and that "**Ohlson's original model displays the strongest overall performance**." Their exact error-rate pairs (Altman 18.5%/25.1%; Ohlson 10.8%/26.6%) are second-hand via an Agarwal & Taffler footnote and appear nowhere else — **treat as once-only.**

**Altman et al. (2017, JIFMA)** — the natural primary source for the international Z″ — reports, per its 2014 SSRN working-paper abstract, "prediction accuracy levels (AUC) of about **75%**, and exceptionally well for some (above 90%)", across 31 European plus 3 non-European countries, primarily **private non-financial** firms using the original Z″. Sample period, firm counts and country-level AUCs are **UNVERIFIED**.

**Where the literature genuinely disagrees — preserve both sides.**
- **Market-based dominance is contested.** Hillegeist et al. find BSM-Prob dominates decisively; **Agarwal & Taffler (2008) find "little difference in their predictive ability in the UK."** This is unresolved, not settled.
- **Whether re-estimation helps is contested.** Begley et al. and Hillegeist et al. both find the **original** coefficients beat updated ones, while Grice & Dugan (2003) argue for re-estimation.

**A trap worth flagging.** A widely circulated thesis table lists **AUC 0.851** against a specification labelled "Shumway (2001)." That figure is **the thesis's own German replication, not Shumway's reported number.** Shumway's actual accuracy figures remain **UNVERIFIED** — the paper could not be accessed. Do not attribute 0.851 to him.

**Bottom line for a screening tool.** On broad modern populations, Z (a) misclassifies heavily in both directions, (b) has three of five inputs statistically insignificant, (c) cannot be fixed by re-estimation, and (d) has a useful horizon of about two years. That is a reasonable final display metric and a poor ranking input.

**Corrections carried forward from the underlying review, for anyone citing this work.**
- A DOI previously attached to Zmijewski (1984) in the underlying report — `10.1016/0882-6110(03)20004-3` — actually belongs to **Grice & Dugan (2003), *Advances in Accounting* 20, 77–93**, a paper *about* Zmijewski and Ohlson. **Zmijewski's own DOI remains UNVERIFIED.**
- Hillegeist et al. benchmark against **BSM-Prob (Black–Scholes–Merton)**. There is no "Bharath-Riski" model; Bharath & Shumway (2008) is a separate paper and "Riski" is not an author on either.

**Caveats.**
- **Sector.** Never use on financial companies: "Neither the Altman models nor other balance sheet-based models are recommended for use with financial companies. This is because of the opacity of financial companies' balance sheets and their frequent use of off-balance sheet items" ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score)).
- **The Z″-EM constant is an intercept.** Adding 3.25 shifts every score; compare firms only under the same variant.
- **Sector, structurally.** X5 (sales/total assets) "varies widely from industry to industry" — which is precisely why Z″ drops it. Using the original Z across sectors loads an industry bet into the score.
- **Size.** The original sample was restricted to firms with assets between **$1m and $25m**; firms below $1m were excluded outright. Altman asserts the model is robust to large firms, but that is an assertion, not a test.
- **Retained earnings are manipulable.** Altman himself notes X2 "is subject to 'manipulation' via corporate quasi-reorganizations and stock dividend declarations." Young firms are structurally penalised by a low X2 regardless of health.
- **X2 is not a proxy for equity, and this matters for buyback-heavy firms.** Buybacks reduce treasury stock, not retained earnings. At 2025-12-31 Boeing shows retained earnings of **$17,252m**, total equity of **$5,454m** and treasury stock of **$28,029m** — the two diverge by more than 3×. `us-gaap:RetainedEarningsAccumulatedDeficit` is also **signed** (American Airlines: **−$6,732m** at 2025-12-31). Do not substitute one for the other.
- **Cutoff choice changes the answer materially** — 1.81 vs 2.675 vs 2.99 give very different classification behaviour on the same firm.
- **Leases.** ASC 842 / IFRS 16 move operating lease liabilities on-balance-sheet. That raises total liabilities (hurting X4) and can raise or lower working capital depending on classification. Pre-2019 vs post-2019 Z-scores for the same firm are **not** directly comparable. Direction is mechanical; see §14 for the verified magnitudes.
- **Market capitalisation dependency.** X4 in the original and Z′ forms needs market cap. For UK Companies House iXBRL filers, market cap is not in the accounts at all.

---

### 3a. Altman Z: what it actually costs to compute (verified against the live EDGAR API)

**A "one tag fits all" extractor fails on day one.** Every tag name below was confirmed by a live `companyconcept` API call, not inferred. `us-gaap:StockholdersEquity` returns **404 for Caterpillar but 200 for Deere**. Worse, `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` — the tag most often recommended post-ASC 606 — **404s for both Caterpillar and Deere**, which both use `us-gaap:Revenues`. Any extractor with a single hard-coded tag will silently drop large, healthy filers.

| Z input | US-GAAP tag | Note |
|---|---|---|
| Working capital (X1) | `us-gaap:AssetsCurrent` − `us-gaap:LiabilitiesCurrent` | **not always present — see below** |
| Retained earnings (X2) | `us-gaap:RetainedEarningsAccumulatedDeficit` | signed; not a substitute for equity |
| Total liabilities | `us-gaap:Liabilities` | |
| Total assets | `us-gaap:Assets` | |
| Sales (X5) | `us-gaap:Revenues` / `…RevenueFromContractWithCustomerExcludingAssessedTax` / `us-gaap:SalesRevenueNet` | precedence chain required |
| Market value of equity (X4) | `dei:EntityCommonStockSharesOutstanding` × price | external price join |
| EBIT (X3) | **no such tag** — `us-gaap:Ebit` 404s | use `us-gaap:OperatingIncomeLoss` as a proxy |

**Pitfall (a) — X1 is not computable for a substantial minority of US filers.** Reg S-X § 210.5-02 requires a current/non-current split only "when appropriate." **Deere is a US public manufacturer whose latest 10-K contains the strings "Current assets" and "Current liabilities" zero times.** A verified frames count for CY2024Q4I gives `Assets` **6,271** entities, `AssetsCurrent` **4,963**, `LiabilitiesCurrent` **4,962** — so roughly **21% of entities reporting total assets report no current-asset split.** For those filers X1 cannot be computed, and defaulting missing `AssetsCurrent` to zero silently biases X1 downward.

*Caveat on that 21%:* it is a reproducible frames-API measure assembled for this review, **not an SEC statistic**, and the population it is drawn from includes banks, insurers and funds, for which unclassified presentation is normal. Treat it as a floor-level warning about coverage, not a precise manufacturer-level rate.

**Pitfall (b) — revenue tag churn is severe and still moving.** Frames counts:

| Tag | CY2016 | CY2024 |
|---|---|---|
| `SalesRevenueNet` | 1,915 | **404 — tag gone** |
| `Revenues` | 3,630 | 2,505 |
| `RevenueFromContractWithCustomerExcludingAssessedTax` | 1,412 | 2,970 |

**In CY2024 no single revenue tag covers even half the universe, and the majority tag flipped between 2016 and 2024.** X5 needs a documented precedence fallback chain, plus logging of which tag was used.

**Pitfall (c) — a widely repeated claim that is wrong.** The assertion that segment (dimensioned) facts contaminate the Company Facts API is **not true for the modern APIs** — the SEC filters to facts that "Apply to the entire filing entity." The contamination risk lives in **raw/bulk** data: the SEC's December 2024 reprocessing moved the Financial Statement Data Sets from non-dimensional-only to rendering-based and added a new **`segments`** field to the NUM file ([FSDS page](https://www.sec.gov/dera/data/financial-statement-data-sets)). If you build on bulk FSDS, handle `segments`; if you build on the Company Facts API, you do not have this problem.

**Pitfall (d) — the X4 as-of date trap.** Share counts on the 10-K cover page are dated differently from the balance sheet. Apple's FY2025 10-K cover-date share count is **2025-10-17** while the balance-sheet date is **2025-09-27**. Assemble X4 as (shares on *their own* `end` date) × (closing price on that same date), or you will silently mix dates.

**Pitfall (e) — EBIT is a definitional choice, not a fact.** There is no EBIT tag. `OperatingIncomeLoss` is the usual proxy but is **optional and not filed every year** (Deere's latest annual fact is FY2024). Caterpillar has **no `us-gaap:InterestExpense*` fact at all**, so the pre-tax-plus-interest alternative also fails. Mixing EBIT definitions across a panel moves X3 by accounting-policy choice rather than credit quality.

### 3b. UK Companies House: for small and micro filers the Z-score is structurally undefined

This is a **statutory** limitation, not a technical one, and it is the single most important constraint for the UK half of the system.

- **No structured financial-statement API exists.** The Companies House Public Data API has **34 operations and none for accounts**; filing history returns only metadata. The Free Accounts Data Product is the only route to financial content (iXBRL/XML instances) and covers only **"about 75% of the 2.2 million accounts … filed each year"** ([Public Data API reference](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference); [Free Accounts Data Product](http://download.companieshouse.gov.uk/en_accountsdata.html)).
- **Small companies do not have to file a profit and loss account.** Companies Act 2006 **s.444(5)(a)** provides that small-company directors "do not deliver to the registrar a copy of the company's profit and loss account"; micro-entities are carved into **s.443A**, and GOV.UK confirms a micro-entity may "send only your balance sheet" ([s.444](https://www.legislation.gov.uk/ukpga/2006/46/section/444); [s.443A](https://www.legislation.gov.uk/ukpga/2006/46/section/443A); [GOV.UK](https://www.gov.uk/annual-accounts/microentities-small-and-dormant-companies)).

**Consequence: X3 (EBIT/total assets) and X5 (sales/total assets) are legally absent for UK small and micro-entity filers.** X2 survives only if retained earnings is tagged on the filed balance sheet. **X1 and X4 are the only reliably recoverable inputs.** Any tool that reports an Altman Z-score for such a company is either imputing data or silently substituting a different model — and it should say so.

**Taxonomy note.** UK iXBRL uses the FRC Taxonomy Suite. The FRC's own tagging guide warns that companies "may apply varying definitions to … **revenue**," so taxonomy summations will not always reconcile ([FRC XBRL Tagging Guide](https://www.frc.org.uk/docs/8912/html/)).

**Overall XBRL difficulty for Altman: Low for the formula, Medium-to-High for coverage.** The arithmetic is trivial; the hard part is that X1 is missing for ~1 in 5 US filers and X3/X5 are legally missing for most UK small/micro filers. **Report computability per firm, and refuse to emit a Z-score where the inputs are absent.**

---

## 4. Ohlson O-score

**Definition.** A nine-variable logit model estimating the probability of bankruptcy within two years, proposed as an alternative to Altman's discriminant approach.

**Originating paper.** James A. Ohlson, "Financial Ratios and the Probabilistic Prediction of Bankruptcy," *Journal of Accounting Research* **18(1), 109–131, Spring 1980**, DOI [10.2307/2490395](https://doi.org/10.2307/2490395). Volume and pages confirmed from the JSTOR cover page in the archived scan.

**Formula.**
```
O = −1.32
    − 0.407·log(TA_t / GNP)
    + 6.03·(TL_t / TA_t)
    − 1.43·(WC_t / TA_t)
    + 0.0757·(CL_t / CA_t)
    − 1.72·X
    − 2.37·(NI_t / TA_t)
    − 1.83·(FFO_t / TL_t)
    + 0.285·Y
    − 0.521·(NI_t − NI_{t−1}) / (|NI_t| + |NI_{t−1}|)
```
TA = total assets; GNP = GNP price-level index (USD, 1968 = 100); TL = total liabilities; WC = working capital; CL = current liabilities; CA = current assets; **X = OENEG = 1 if TL > TA else 0**; NI = net income; FFO = funds from operations; **Y = INTWO = 1 if a net loss in each of the last two years else 0**. Probability = exp(O) / (1 + exp(O)).

**Formula verification status — a live source conflict.** The coefficients above come from Wikipedia's LaTeX source (which cites the original paper) and are corroborated by two independent theses. But a Queen's University Belfast working paper reproduces the same model with **0.603** instead of 6.03 on the leverage term and an inverted liquidity ratio (**CA/CL** instead of CL/CA). Two other sources give 6.03 and CL/CA. **My assessment is that 6.03 with CL/CA is correct and the QUB version is a transcription error — but the original paper could not be read, so this is not settled.** Any implementation must pick a side and document it.

**Why the original could not be read.** The only free copy is a **JSTOR scan with no OCR text layer** (23 CCITTFax images; extractable text on the cover page only). **Ohlson's actual reported Type I/Type II error rates, and the cutoff at which they were measured, are therefore UNVERIFIED from the primary source.**

**Sample.** **105 bankrupt and 2,058 non-bankrupt firms, 1970–1976**, exchange-traded industrial firms only — small and privately held firms were excluded. Ohlson estimated three logit models using three years of data prior to bankruptcy: Model 1 predicts bankruptcy within one year, Model 2 within two years conditional on not failing in the first, Model 3 within one or two years ([Bouwmeester thesis](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)).

**Reported accuracy — and a warning.** Two theses report figures that **cannot both be right**:

| Source | Reported |
|---|---|
| Twente thesis | Optimal cutoff minimising total errors is **0.038**; at that cutoff **87.6% of bankrupts** and **82.6% of non-bankrupts** correctly classified |
| Tilburg thesis | First model **96.12%** of observations correctly predicted overall; the same source notes the naive all-negative baseline is **95.15%** |
| Twente thesis, citing Ohlson | **96%** estimation sample, **85%** hold-out |

87.6%×105 + 82.6%×2,058 = 1,792 correct = **82.8%**, not 96.12%. The figures are mutually inconsistent; the likely resolution (different cutoffs on the same sample) is **UNVERIFIED**.

**Two practical consequences.** The error-minimising cutoff is **0.038, not 0.5** — the popular "O > 0.5" rule does not minimise total errors at Ohlson's 105:2,058 imbalance. And the 96% headline sits barely above the 95.15% naive baseline. **Report Type I and Type II separately.**

**Did it hold up?**
- Out-of-sample on Dutch and Belgian firms, Ohlson variables scored **95.01% overall but caught only 47.89% of bankrupts**, with **out-of-sample AUC 0.696 / 0.738 / 0.717** (MDA / logit / probit). Re-estimating with logit rather than MDA did not significantly improve AUC ([Bouwmeester thesis](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)).
- **Wikipedia's claim that the O-score is "significantly more accurate" than the Z-score is unsupported.** The page carries a "needs more citations" banner, and the one same-sample comparison I could open shows Ohlson, Zmijewski and Altman variables all landing in a similar AUC band of roughly 0.68–0.74. **Treat the superiority claim as unsupported.**

**Practical caveats.**
- **The GNP deflator is a live input.** The SIZE term is log(total assets / GNP price level, 1968 = 100). Any implementation must carry a historical deflator series; using a constant silently distorts the score.
- **Class imbalance dominates every headline accuracy figure** — at a ~5% base rate, always-negative scores 95%.
- **FFO is not a standard modern XBRL or IFRS line item.** It needs a cash-flow proxy, which introduces definitional drift.
- Ohlson deliberately excluded small and private firms; SME application is extrapolation.
- Lease capitalisation shifts TL/TA, WC/TA and CL/CA. Direction mechanical; **magnitude UNVERIFIED** (see §14).

**XBRL difficulty: Low–Medium, but not specifically verified.** Firm-level inputs are standard tags; the GNP price-level deflator must be sourced externally, and **FFO is not a standard modern XBRL or IFRS line item**, so it needs a cash-flow proxy. **The computability of the Ohlson inputs was not separately probed against the live EDGAR API** — unlike the Altman inputs in §3a, which were. Given the Altman findings (X1 missing for ~21% of filers, no EBIT tag, severe revenue-tag churn), assume Ohlson will hit similar or worse coverage problems, particularly on the `CL/CA` term and FFO. **Probe before committing to it.**

---

## 5. Zmijewski probit (1984)

**Definition.** A three-variable probit model of bankruptcy.

**Originating paper.** Mark E. Zmijewski, "Methodological Issues Related to the Estimation of Financial Distress Prediction Models," *Journal of Accounting Research* 22 (Supplement), 1984, pp. 59–82. The reference is independently confirmed in Beneish's own bibliography ([Beneish working paper](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)), which notes that Beneish borrowed Zmijewski's weighted-probit approach. **A DOI circulating for this paper is unconfirmed — treat the citation as verified at journal/volume/page level only.**

**Formula.**
```
Zmijewski = −4.3 − 4.5·X1 + 5.7·X2 + 0.004·X3
X1 = Net income / Total assets
X2 = Total liabilities / Total assets
X3 = Current assets / Current liabilities
```
Probit form: probability = Φ(index); most secondary sources classify as distressed when the index ≥ 0. **The exact transform was not verifiable from the source opened.** The more precise coefficients sometimes quoted (−4.336, −4.513, 5.679, 0.004) appeared only in a search snippet and are **UNVERIFIED**.

**Sample.** **40 bankrupt and 800 non-bankrupt firms** in the estimation sample; a hold-out of **41 bankrupt and 800 non-bankrupt**. Population: all firms listed on the American and New York Stock Exchanges between **1972 and 1978** with SIC codes below 6000 — finance, service and public administration firms excluded ([Gerritsen thesis](http://essay.utwente.nl/68211/1/Gerritsen%20P.L._MA%20BA_Behavioural%2C%20Management%20and%20Social%20sciences%20%28BMS%29.pdf)).

**Reported accuracy.** **99% on the estimation sample**; the hold-out accuracy was **not reported**. Note the 20:1 imbalance: the naive all-negative baseline is 800/840 = **95.2%**, so 99% is a 3.8-point improvement over trivially predicting "no bankruptcy." Out-of-sample on Dutch/Belgian firms, Zmijewski variables scored **94.37% overall but caught only 38.03% of bankrupts**, with **out-of-sample AUC 0.683 / 0.697 / 0.690** ([Bouwmeester thesis](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)).

**Did it hold up? — contested.** Published criticisms as quoted in the Gerritsen thesis:
- Shumway (2001, p.120) argues the model is effectively a **one-variable model**, because the three ratios are highly correlated, and therefore has "no strong predictive power."
- Platt & Platt (2002, p.186): Zmijewski "could not test the individual estimated coefficients for bias against the population parameter since Zmijewski ran only one regression for each sample size."
- Grice & Dugan (2003): the ratios "were not selected on a theoretical basis, but rather on the basis of their performance in prior studies."

**Why it is still worth knowing.** Zmijewski's real contribution is methodological: he showed that choice-based (oversampled) samples bias probit estimates. That is exactly the problem Beneish later addressed with weighted exogenous sample maximum likelihood, and the same bias that inflates the 95%/99% accuracy figures above. **If you build your own logistic distress model on oversampled bad-outcome data, you inherit this bias unless you weight it.**

**XBRL difficulty: Low** (three ratios) — but the coefficients rest on a single MSc thesis and the original paper was not opened. **Verify before shipping.** Do not use this as a scored marker.

---

## 6. Dechow F-score (predicting material misstatement)

**Definition.** A scaled probability that a firm is misstating its financial statements, built from accrual-quality, performance, non-financial and off-balance-sheet indicators.

**Originating paper.** Patricia M. Dechow, Weili Ge, Chad R. Larson & Richard G. Sloan, "Predicting Material Accounting Misstatements," *Contemporary Accounting Research* 28(1), 2011, pp. 17–82.

**Sample.** The authors examined the **2,190 AAERs issued between 1982 and 2005** and identified **676 unique firms** that misstated at least one quarterly or annual financial statement ([Dechow et al. summary text](https://www.valuewalk.com/predicting-material-accounting-misstatements/)). The authors note the SEC has a limited budget and selects cases with strong evidence, so the Type I error rate is low but many manipulators go unidentified.

**Formula.**
```
Predicting Value = −7.893
                 + 0.790·RSST_accruals
                 + 2.518·ΔREC
                 + 1.191·ΔINV
                 + 1.979·SOFT_ASSETS
                 + 0.171·ΔCASHSALES
                 − 0.932·ΔROA
                 + 1.029·ISSUE

Probability = e^(Predicting Value) / (1 + e^(Predicting Value))
F-score     = Probability / 0.0037        (0.0037 = unconditional misstatement rate)
```
Flag: **F-score > 1** means the model's estimated misstatement probability exceeds the unconditional rate ([Haryadi et al., *E-Jurnal Akuntansi* 36(2)](https://ejournal1.unud.ac.id/index.php/akuntansi/article/download/3488/2119), which reproduces the model and its variable definitions from Aghghaleh et al. 2016).

| Variable | Definition |
|---|---|
| RSST accruals | (ΔWC + ΔNCO + ΔFIN) / average total assets |
| ΔREC | ΔAccounts receivable / average total assets |
| ΔINV | ΔInventory / average total assets |
| SOFT_ASSETS | (Total assets − PP&E − cash & equivalents) / total assets |
| ΔCASHSALES | % change in cash sales (Sales − ΔAccounts receivable) |
| ΔROA | ROA_t − ROA_{t−1} |
| ISSUE | 1 if the firm issued securities during year t |

**Reported effect size.** Dechow et al. report their F-score correctly classifies a substantial majority of misstating firm-years **in sample**, but the specific accuracy/AUC from the primary paper is **UNVERIFIED** — the paper is paywalled, and Dechow's own conference slides present the classification tables as images that the text-extraction route could not decode ([slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf)). A search snippet from those slides suggests a "68.6% / 31.4% / 0.4%" split, but I could not confirm what those columns are. **Do not cite that number.**

**Did it hold up? — This is the key finding.**
- Out-of-sample in a non-US setting, the F-score is weak. The 2022–2024 Indonesian study reports Dechow F-score accuracy **62.00%**, sensitivity **29.82%**, specificity **81.72%**, precision 50.00%, F1 **37.36%**, and **AUC 0.554** ([Haryadi et al.](https://ejournal1.unud.ac.id/index.php/akuntansi/article/download/3488/2119)). It is a low-recall screen: it is good at clearing firms and poor at catching fraud.
- **Base rate problem, quantified.** "About half a percent of firms commit fraud each year," per Dechow's own slide dividing AAER manipulation-years by Compustat firm counts ([Dechow slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf)). At a 0.5% base rate, even a model with AUC 0.75 produces more false positives than true positives for most cut-offs.
- **Dechow's own caveat, from the same deck:** "Models detect fraud firms, but a lot of firms classified as fraud firms do not end up in the SEC sample."
- **It remains the academic benchmark.** Huang, Kraft & Wang (2023, *The Accounting Review* 98(7) 347–376) use "the F-score model by Dechow et al. (2011) as the primary benchmark because it is the most widely used fraud prediction model in the accounting literature" ([paper PDF](https://www.allenhuang.org/uploads/2/6/5/5/26555246/huang_kraft_and_wang_2023_tar.pdf)). Using it as a *baseline* is defensible; treating its output as a probability is not.

**Caveats.**
- **Selection bias is generic.** Dechow et al. are explicit that AAER, litigation, SOX-violation and restatement samples all share selection problems, and that discretionary-accrual measures do too.
- **Fit, not forecasting.** The model was estimated on the *misstating* year, so it is best understood as a contemporaneous screen for "does this year look wrong," not a forecast.
- **ISSUE requires share-issuance detection**, which is easy in XBRL (`StockIssuedDuringPeriodValueNewIssues`, or share-count change) but noisy with buybacks and option exercises.
- **Survivorship.** Misstated years that were never detected are labelled as clean in training.

**XBRL difficulty: Low–Medium.** Six of seven variables come straight from XBRL; `ISSUE` needs care. This is one of the better cost/value ratios on this list *as a flag*, despite the weak standalone AUC.

---

## 7. Piotroski F-score (fundamental momentum)

**Definition.** A 0–9 integer score summing nine binary accounting signals, designed to separate financially strong from financially weak **high book-to-market** firms.

**Originating paper.** Joseph D. Piotroski, "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers," *Journal of Accounting Research* 40 (Supplement), 2002. I read the full 42-page paper ([University of Chicago Selected Paper 84 PDF](http://www.chicagobooth.edu/~/media/FE874EE65F624AAEBD0166B1974FD74D.pdf)).

**Sample.** High book-to-market firms, **1976–1996**, **14,043 firm-years** (12,426 with earnings-announcement data).

**The nine signals.** Grouped into profitability, leverage/liquidity/funding, and operating efficiency. Confirmed against both the paper and [Wikipedia](https://en.wikipedia.org/wiki/Piotroski_F-score):

*Profitability (4)*
1. **F_ROA** = 1 if ROA > 0 (ROA = net income before extraordinary items / beginning-of-year total assets)
2. **F_CFO** = 1 if operating cash flow > 0
3. **F_ΔROA** = 1 if ΔROA > 0
4. **F_ACCRUAL** = 1 if CFO > ROA (i.e. cash flow exceeds earnings — the Sloan accrual test embedded in the score)

*Leverage, liquidity, source of funds (3)*
5. **F_ΔLEVER** = 1 if the long-term-debt-to-average-total-assets ratio **fell**
6. **F_ΔLIQUID** = 1 if the current ratio **rose**
7. **F_EQ_OFFER** = 1 if the firm did **not** issue common equity in the year before portfolio formation

*Operating efficiency (2)*
8. **F_ΔMARGIN** = 1 if gross margin rose year-on-year
9. **F_ΔTURN** = 1 if asset turnover (net sales / average total assets) rose year-on-year

The paper's own footnote on the ROA/CFO benchmarks is worth noting: 41.6% of high-BM firms had a loss in the prior two fiscal years, so "positive earnings realisations are nontrivial events for these firms."

**Reported effect sizes (all from the paper).**
- Mean return to a high-BM investor can be increased by **at least 7.5% annually** by selecting financially strong high-BM firms, and "the entire distribution of realized returns is shifted to the right."
- A long-winners / short-losers strategy generates a **23% annual return between 1976 and 1996**.
- The cleanest headline number is in the paper's Appendix 1: the market-adjusted hedge portfolio (long F_SCORE ≥ 5, short F_SCORE < 5) earned an average **+9.7% market-adjusted per year, t = 5.059**, with strong firms at +10.6% (t = 3.360) and weak firms at +0.9% (t = 0.243).
- Table 7 portfolio statistics: strong firms mean market-adjusted return 0.107, weak 0.005, difference 0.102 (t = 5.683); % positive 46.9% vs 40.2%.
- **For delisting:** low F_SCORE firms were **more than five times as likely** to delist for performance-related reasons within two years (7.0% versus roughly 2%; high−low difference significant at 1%, binomial test).
- **Announcement concentration:** high-minus-low announcement-period return over the following four quarters was **0.041 (t = 3.461)**, and approximately three-quarters of the total annual return difference was earned over just 12 trading days.
- **Where it works:** the benefits are concentrated in small and medium-sized firms, firms with low share turnover, and firms with no analyst following. For small firms the four-quarter announcement return difference was 5.1%; for large firms it was not significant.

**Did it hold up?**
- Piotroski himself flags the risk: "One limitation of this study is the existence of a potential data-snooping bias," because the signals were chosen partly on the basis of previously documented results.
- It remains a widely used and commercially packaged factor. A 2024 study evaluating the formula on the US market from **1963 to 2022** finds that the F-score and three other formulas (Magic Formula, Conservative Formula, Acquirer's Multiple) "generate significant raw and risk-adjusted returns, primarily by providing efficient exposure to well-established style factors. However, no single formula consistently outperforms across all performance metrics" ([Schwartz & Hanauer 2024, SSRN 5043197, as cited on Wikipedia](https://en.wikipedia.org/wiki/Piotroski_F-score)). That is a material reframing: the F-score may be **repackaged quality/value beta** rather than an independent anomaly.
- **It replicates internationally — this is the strongest evidence for it.** Walkshäusl (*Journal of Asset Management* 21(2), 106–118, open access), covering **20 developed non-US markets plus 15 emerging markets, July 2000 – June 2018**, finds an F-score premium of **0.79% per month in developed markets (≈9.9% per year)** and **0.95% per month in emerging markets (≈12.0% per year)**; value-weighted, **0.55% and 0.60% per month**. The profitability-gap component contributed 3.1 and 2.3 percentage points respectively. The same paper's Table 1 compiles other independent results: Piotroski & So (2012) 10.03%/yr; Hyde (2018) Australia **1.31%/mo equal-weighted but only 0.52%/yr value-weighted and not significant**; Tikkanen & Äijö 8.00–17.33%/yr; Ng & Shen 0.83%/mo; Turtle & Wang 6.73%/yr ([Walkshäusl PDF](https://epub.uni-regensburg.de/44019/1/Walksh%C3%A4usl2020_Article_PiotroskiSFSCOREInternationalE.pdf)).
- **But there is direct decay evidence for the US.** Woodley, Jones & Reburn found that for **1997–2008 the results were "exactly reversed"**, later attributed to VIX and investor sentiment ([AEF Vol. 43, pp. 66–67](https://economics-finance.org/AEF/wp-content/uploads/2024/09/2019_AEF_PP_V43.pdf)). Combined with the Myers & Shen and Hyde value-weighted results, the honest summary is: the F-score is **robust in equal-weighted international samples and fragile in US value-weighted samples after the late 1990s**. That is precisely the signature of a small-cap/illiquidity effect rather than a durable anomaly.
- **A further caution from the 2024 formula study:** the formulas' returns come "primarily by providing efficient exposure to well-established style factors." If your system already uses value and quality screens, the F-score may add less than its headline suggests.

**Caveats.**
- **The sample is the strategy.** The F-score was designed for and validated on *high book-to-market* firms. Applying it to the whole universe changes what it is measuring. The Wikipedia entry notes the average score varies by sector.
- **One-year lookback only.** "It is a strategy that only compares a company's results in one year to those of the previous year. This makes it difficult to apply in cyclical sectors or during particular periods such as... the COVID-19 pandemic in 2020" ([Wikipedia](https://en.wikipedia.org/wiki/Piotroski_F-score)).
- **Equity issuance detection (signal 7)** is noisy for firms with heavy option exercise.
- **Items already in your system.** Your tool already computes ROE, ROCE, net debt/EBITDA and interest cover. F_ΔLEVER and F_ROA overlap with those; the genuinely additive pieces are F_ACCRUAL, F_ΔMARGIN and F_ΔTURN.

**XBRL difficulty: Low.** Two consecutive years; all nine signals are standard tags. `F_CFO > ROA` reuses the accrual computation in §1.

---

## 8. Cash conversion: operating cash flow versus net income

**Definition.** The gap between accrual earnings and cash generation, used as an earnings-quality indicator.

**The honest finding first.** There is **no literature on the literal screen "cumulative OCF/NI < 1".** What is tested and replicated is *asset-scaled accruals*, never a bare ratio with a threshold at 1.0. A "cash conversion below 1 for N years" flag is an undocumented composite and should be labelled as such in any UI.

**What has been validated.**

*The accrual formulation* — `(NetIncomeLoss − NetCashProvidedByUsedInOperatingActivities) / average total assets` — is §1 above, and it is the replicated construct ([Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf); [Sloan 1996 abstract](https://www.jstor.org/stable/248290)).

*The nearest practitioner formulation* is the Georgia Tech Financial Analysis Lab's **Earnings Quality Indicator**:
```
EQI = (OCF − NI) / Revenue = operating cash margin − net margin
```
with both OCF and NI adjusted for non-recurring and non-operating items first (Mulford & Misra, May 2016; Compustat; quarterly March 2000 – September 2015; medians for 20 non-financial GICS groups).

*The EQI level is not comparable across industries.* Median EQI by industry group, September 2015: Energy 26.62%, Telecom 16.97%, Utilities 16.53%, Pharma/Biotech 13.99%, Transportation 12.16%, Software 12.10%, Media 8.96%, Materials 8.26%, Tech Hardware 5.60%, Food & Beverage 4.45%, Capital Goods 3.45%, Autos 3.45%, Retailing 2.50%, Food & Staples Retailing 2.17%, Consumer Durables 1.81%. The all-industry median moved from 4.55% pre-recession (June 2007) to 11.17% at the recession high (September 2009) to 8.04% (September 2015). **A single cross-market threshold is indefensible.**

*The Lab's own rule is about trend, not level*: "Stable" means within ±15% year-on-year change. They publish no good/bad threshold.

**UNVERIFIED.** I found no credible source for a distribution of the bare OCF/NI ratio or for any threshold such as "<0.8 for three years." The bare ratio also breaks when NI is near zero or negative — precisely the population of interest.

**Recommended implementation.** Rank within GICS industry group on `(OCF − NI)/Revenue`, require the trend to be stable or rising against the firm's own three-year history (±15% band), and cross-check against cash-flow-statement accruals from §1. Do not ship a global ratio threshold.

**XBRL difficulty: Low** for the ratio; **Medium** for the industry-relative and trend components, which need a peer universe.

---

## 9. Receivables growing faster than revenue (DSO drift)

**Definition.** Revenue recognised ahead of collection shows up as receivables rising faster than sales.

**Best-evidenced formulation — Beneish's DSRI, a ratio of ratios:**
```
DSRI = (Receivables_t / Sales_t) ÷ (Receivables_{t−1} / Sales_{t−1})
```
This needs no day-count assumption and is directly the variable tested in Beneish (1999). It was the **second-largest t-statistic in his model** (coefficient 0.920, t = 6.02 unweighted; 0.789, t = 6.40 WESML), with median DSRI 1.281 for manipulators versus 0.996 for controls (p = .000) ([working paper](https://studyres.com/doc/7995257/the-detection-of-earnings-manipulation-messod-d.-beneish-...?page=6)).

Alternative practitioner forms: `DSO = AccountsReceivable / (Revenue/365)`, and the growth gap `ΔAR% − ΔRevenue%`.

**Standalone effect size.** The change-in-receivables decile spread in Chan, Chan, Jegadeesh & Lakonishok is **+3.1% (t = 2.23)** in year +1, **+2.8% (t = 2.10)** in year +2, and **+1.8% (t = 1.17, not significant)** in year +3. The discretionary component spread is **+3.5% (t = 2.99)** versus **+0.7% (t = 0.51)** for the non-discretionary component ([Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)). So: real but modest, and it fades within two years.

**Regulatory corroboration.** Improper revenue recognition is the **most common** SEC fraud scheme, accounting for **43%** of schemes across 531 AAERs from 2014–2019 (CAQ / Anti-Fraud Collaboration, January 2021). Reserves manipulation was 24%, inventory misstatement 11%, loan impairment 11%. CFOs were charged in 54% of cases and CEOs in 31%; 39% of AAERs were against issuers with market cap under $250m.

**ASC 606 / IFRS 15 changed the mapping.** Per the IASB's own staff literature review (March 2023):
- Only 48% of a STOXX Europe 50 sample disclosed non-immaterial effects of adoption; mean retained-earnings change was 1.88% of equity (median 0.05%, maximum 57.31%); mean revenue change 0.72% of revenue (maximum 13.12%).
- Of 3,019 US entities, 68% reported no material impact; average cumulative retained-earnings adjustment was 2.7% of market cap, revenue 2.3%, net income 0.6%; 88.5% used the modified retrospective method.
- **The average revenue cycle shortened from 24 to 18.7 months at adoption** (long-cycle industries 28.8 → 14.7 months).
- Two papers find managers used the transition discretion opportunistically (higher revenue growth without matching COGS growth; more meet-or-beat behaviour), with discretionary revenue measured as the unexplained portion of accrued receivables — i.e. a DSO-drift-like construct.

The practical consequence: **DSO computed across the 2018/2019 boundary is not a like-for-like series.**

**Caveats.**
- **Factoring inverts the signal.** Selling receivables lowers DSO while leaving the credit risk in place. This is a real mechanical effect; I did **not** find a source that measures how often it distorts screens, so treat it as **[D]** — an untested hypothesis to control for, not a documented finding.
- **Payment mix moves DSO with no accounting problem.** A shift from card to invoice sales, or a change in customer mix, moves DSO without any manipulation.
- **The `Revenues` tag is unreliable.** Filers variously use `Revenues`, `RevenueFromContractWithCustomerExcludingAssessedTax`, `RevenueFromContractWithCustomerIncludingAssessedTax`, or `SalesRevenueNet`. This is a genuine build risk and a common cause of silent errors.
- **Sector.** Trivially different for subscription software, construction, and retail.

**XBRL difficulty: Low–Medium.** `AccountsReceivableNetCurrent` (but also `ReceivablesNetCurrent` and `AccountsAndOtherReceivablesNetCurrent`; the allowance may or may not be netted), plus a deliberate revenue-tag policy. UK/IFRS filers use the `TradeAndOtherReceivables` family — pin exact element names from real instances.

---

## 10. Inventory build versus sales growth

**Definition.** Inventory rising faster than sales signals either weakening demand or margin pressure; under accrual accounting it also inflates earnings.

**Best-evidenced formulation.** `ΔInventory / average total assets` — this is exactly the tested measure in the accrual decomposition, and it sidesteps revenue and COGS denominator problems entirely.

**Effect sizes.** Chan, Chan, Jegadeesh & Lakonishok decile sorts on ΔINV/assets: abnormal spread **+7.2% (t = 4.34)** in year +1, **+3.3% (t = 2.34)** in year +2, **+1.6% (t = 0.84, not significant)** in year +3; raw spread +9.5% (t = 4.63). The sharpest result in that paper is the decomposition: the **discretionary** ΔINV spread is **+9.1% (t = 7.02)** while the **non-discretionary** spread is **−1.5% (t = −0.71)**. The authors conclude that "changes in inventory are by far the most important component of accruals for predicting future returns." Top-decile accrual firms had average trailing three-year sales growth of 22.8% versus 7.2% for the bottom decile — high-inventory firms are **decelerating** growers ([Du, Wang & Wei](https://ira.lib.polyu.edu.hk/bitstream/10397/90052/1/PBFJ_Accrual_PolyU.pdf)).

**Decay.** 7.2% → 3.3% → 1.6%: this is **a one-year signal**. Whether it survives Hou, Xue & Zhang's NYSE-breakpoint / value-weighted protocol is **UNVERIFIED** — that is an inference from their general finding, not a sourced result.

**Originating literature.** Thomas & Zhang, "Inventory Changes and Future Returns," *Review of Accounting Studies* 7(2–3), 2002, pp. 163–187. **Thomas & Zhang's own reported effect sizes are UNVERIFIED** — the paper is paywalled and no source I opened quoted its numbers. The verifiable numbers above come from the Chan et al. replication path.

**Caveats.**
- **Sector dispersion in inventory days is enormous** (grocery and autos versus software). Days-based screens are meaningless across sectors — use the asset-scaled ΔINV instead.
- **LIFO liquidations and LIFO-to-FIFO changes** revalue the entire inventory base in a single year, producing a spurious one-off margin jump.
- **Write-downs shrink inventory in the very year things deteriorate**, flipping the sign of the signal precisely when it matters most.
- **Legitimate growth-phase builds exist.** That is what the discretionary/non-discretionary decomposition is for; the raw measure cannot distinguish them.
- **The decomposition needs five years of history per firm** to estimate the "normal" inventory–sales relation.

**XBRL difficulty: Low.** `ΔInventoryNet / average(Assets)` — two tags, exactly the tested measure.

---

## 11. Goodwill, intangibles and serial-acquirer balance sheets

**Definition.** Goodwill is the premium paid over fair value of net assets acquired. Under ASC 350 / IAS 36 it is not amortised and must be tested for impairment at least annually. A large goodwill balance relative to assets or equity is unrecognised impairment risk.

**Base rate and timeliness — the key evidence.** André, Filip & Paugam, "Examining the Patterns of Goodwill Impairments in Europe and the US," *Accounting in Europe* 13(3), 2016, pp. 329–352, study **more than 35,000 firm-year observations from 2006 to 2015** across Europe and the US ([IDEAS record with full abstract](https://ideas.repec.org/a/taf/acceur/v13y2016i3p329-352.html)).

The headline result is about **untimeliness**, not frequency. The authors define three indicators of *economic* impairment:
1. equity market value minus equity book value < goodwill;
2. market-to-book < 1;
3. negative EBITDA.

Against those indicators, **only 20–25% of firms that showed evidence of economic impairment actually recognised an accounting impairment**, "depending on the measure of economic impairment. This has often been interpreted by academics as a sign of untimely write-offs."

Magnitude when it does happen differs sharply by regime: during the financial crisis the median US impairment was **63% of opening goodwill in 2008 and 40% in 2009**, versus only **6% and 7%** for European firms. The authors caution that accounting differences between US GAAP and IFRS are "unlikely to explain" the gap, and that they cannot distinguish conditional conservatism from big-bath behaviour.

**The practically useful indicator.** Indicators 1 and 2 above are **directly computable and point the same way**: a firm carrying large goodwill whose market-to-book is below 1 and whose market capitalisation minus book equity is less than its goodwill balance is, by the authors' own definition, showing evidence of economic impairment — and there is roughly a **75–80% chance it has not been written down yet.**

**Important scope limit on that indicator.** André et al. use market-to-book < 1 as a *contemporaneous indicator of economic impairment*, not as a validated *predictor* of a future write-off. The literature that actually predicts impairment uses different variables — see Gu & Lev below, which uses relative P/E, not M/B. **Treat "M/B < 1 plus large goodwill" as "impairment is overdue," not as "impairment will be announced next year."**

**How often does a write-off actually happen?** Two independent estimates:

| Source | Sample | Impairment base rate |
|---|---|---|
| Hayn & Hughes (2006) | 1,276 acquisitions, 1988–1998, tracked to 2001/2004 | **180 acquisitions = 14.1% ended in a write-off**; 180 of 7,916 firm-years = **2.3% per year** ([PDF](https://anderson.ucla.edu/documents/areas/fac/accounting/goodwill_06.pdf)) |
| Kroll US Goodwill Impairment Study (2025) | US listed companies, 2024 | **$96bn impaired in 2024, +16% on 2023's $83bn**; the top 10 impairments alone were $51bn = **53% of the total**; Communication Services, Consumer Staples and Healthcare accounted for **67%** ([Kroll](https://www.kroll.com/en/publications/valuation/2025-us-goodwill-impairment-study)) |

The Kroll concentration figures are the practically useful part: impairment is dominated by a handful of very large write-offs in specific sectors, not spread evenly.

**What predicts a write-off — with effect sizes.**

*Hayn & Hughes (2006)*, comparing write-off firms to non-write-off acquirers ([PDF](https://anderson.ucla.edu/documents/areas/fac/accounting/goodwill_06.pdf)):
- acquisition premium **47.6% vs 40.8%**;
- goodwill as a share of purchase price **58.4% vs 44.8%**;
- stock-financed deals **41.6% vs 34.5%**;
- acquirer announcement-window return **−3.3% vs −1.2%**.

Their predictive model reached only a **42.4% hit rate** in the top two deciles at one year ahead (39.3% / 36.0% / 32.3% / 31.2% at two through five years), with **Type I error ~30% and Type II error 58%**, and a recognition lag of 3–4 years (a third took up to 10 years). The authors' own conclusion is that disclosures "do not provide… information to adequately predict future write-offs."

*Gu & Lev (2011, The Accounting Review 86(6), 1990–2006, 54,218 firm-years)* find a monotonic dose–response between share overpricing and goodwill write-offs ([PDF](https://pages.stern.nyu.edu/blev/accfin/Overpriced%20Shares,%20Ill-Advised%20Acquisitions,%20and%20Goodwill%20Impairment.pdf)). Write-offs as a share of total assets rise across overpricing quintiles from **0.38% to 5.07%** for all firms, **0.69% to 10.56%** for acquirers, and **2.63% to 21.83%** for firms that actually recorded an impairment. Their logit impairment classifier achieved **69.14% correct classification, pseudo-R² 18.02%, Type I 24.80%, Type II 37.29%**, with the goodwill variable carrying a 50.67% marginal effect. Impaired firms' abnormal return since acquisition averaged **−54.28%** versus **−8.27%** for non-impairing acquirers.

**Do acquisitions destroy value on average?** The best available answer is a meta-analysis rather than a single study. King, Dalton, Daily & Covin (2004, *Strategic Management Journal* 25(2)) conclude that acquirer performance "does not positively change… and is negatively affected to a modest extent" ([Crossref record](https://api.crossref.org/works/10.1002/smj.371)). Malmendier & Tate (2008, *Journal of Financial Economics* 89(1)), using Forbes 500 firms 1980–1994, find the market discounts overconfident-CEO bids by **60–100 basis points over the three-day window**, with CARs roughly 100bp below rational bids against a −50bp baseline ([NBER w10813 PDF](https://www.nber.org/system/files/working_papers/w10813/w10813.pdf)).

**Did it hold up?** The untimeliness result is the robust one, and it replicates across jurisdictions. The *prediction* models are weaker: Hayn & Hughes predates SFAS 142 (the impairment-only regime) and Gu & Lev's classifier has not been shown to work on post-2011 data. Treat impairment *prediction* as **[B]**, and impairment *untimeliness* as **[A]**.

**Caveats.**
- The market-based indicators need a market capitalisation, which UK Companies House iXBRL does not provide. For UK filers, only the goodwill-to-assets and goodwill-to-equity ratios are available without a price feed.
- Impairment is discretionary and lumpy; a big-bath year is not the same signal as a gradual write-down.
- IFRS 3 / ASC 805 permit measurement-period adjustments, so recently acquired goodwill may still be provisional.
- The Hayn & Hughes lag structure (3–4 years, sometimes 10) means this is a **slow** signal. It is a portfolio-quality and risk input, not a timing signal.

**XBRL difficulty: Low** for the balance ratios (`us-gaap:Goodwill`, `us-gaap:IntangibleAssetsNetExcludingGoodwill`, `us-gaap:FiniteLivedIntangibleAssetsNet`, `us-gaap:Assets`; IFRS equivalents `ifrs-full:Goodwill`, `ifrs-full:IntangibleAssetsOtherThanGoodwill`, `ifrs-full:Assets`); **Medium** for the market-based indicators (`EntityCommonStockSharesOutstanding` plus a price source); **High** for anything requiring the notes (reporting-unit headroom, discount rates). Acquisition activity is partly taggable via `us-gaap:BusinessCombinationRecognizedIdentifiableAssetsAcquiredAndLiabilitiesAssumedGoodwill` and `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`.

---

## 12. Non-GAAP / adjusted earnings versus statutory earnings

**Definition.** Companies report "adjusted", "pro forma", "underlying" or "core" earnings that exclude items management deems non-recurring. The size of the gap between that number and the statutory number is the signal.

**Originating paper.** Jeffrey T. Doyle, Russell J. Lundholm & Mark T. Soliman, "The Predictive Value of Expenses Excluded from Pro Forma Earnings," *Review of Accounting Studies* 8(2), 2003, pp. 145–174 ([IDEAS record with full abstract](https://ideas.repec.org/a/taf/acceur/v13y2016i3p329-352.html) — note: the DLS abstract is at [this EconPapers record](https://EconPapers.repec.org/article/sprreaccs/v_3a8_3ay_3a2003_3ai_3a2_3ad_3a10.1023_5fa_3a1024472210359.htm)).

**Reported finding (verbatim from the abstract).** "Higher levels of exclusions lead to predictably lower future cash flows. We also find that investors do not fully appreciate the lower cash flow implications at the time of the earnings announcement. A trading strategy based on the excluded expenses yields a large positive abnormal return in the years following the announcement, and persists after controlling for various risk factors and other anomalies." ([EconPapers](https://EconPapers.repec.org/article/sprreaccs/v_3a8_3ay_3a2003_3ai_3a2_3ad_3a10.1023_5fa_3a1024472210359.htm)).

**The exact return spread and sample: UNVERIFIED.** The paper is paywalled and no source I could open quoted the magnitude or the sample period — a Wayback PDF renders in-browser but exposes no extractable text layer, and every open mirror was behind a bot wall. What is verified is the *direction and robustness claim*: higher exclusions predict lower future cash flows, and the market underreacts. **Do not quote a hedge return for DLS.**

**How big is the gap, and does size matter?** Two more recent sources answer this directly, and the second one overturns the naive design.

*Calcbench / Suffolk University, FY2024 S&P 500* ([report PDF](https://www.calcbench.com/home/pdf?name=CB-2025-NONGAAP.pdf)):
- **351 of 500 companies (71%) reported a non-GAAP measure**;
- **89% of them adjusted earnings upward**;
- adjusted net income exceeded GAAP net income by an average of **$870m, roughly +30%** of average GAAP net income;
- **2,249 reconciling items, averaging $135m each; $304bn of total adjustments; 6.4 items per company**;
- composition: amortisation 31%, restructuring 19%, impairments 17%, stock-based compensation ~17%.

*Dechow, Loh & Wang (2025, Review of Accounting Studies 30:1037–1098, open access)*, S&P 500 2013–2017, 1,676 firm-years ([PDF](https://link.springer.com/content/pdf/10.1007/s11142-024-09855-3.pdf)):
- non-GAAP reporting prevalence rose from **55% (2003) to about 80% (2020)**; average exclusions per firm rose from 4.6 to 5.3;
- **median total exclusions ≈ 39% of GAAP earnings**;
- examining **171 SEC comment letters**, a one-unit *decline* in the **quality** of the exclusions raised the likelihood of receiving an SEC comment letter by **17%** (coefficient −0.190, z = −2.19) and raised the odds of a Regulation G violation by **30%** (coefficient −0.362, z = −2.66).

**The design-relevant finding: it is exclusion *quality*, not exclusion *magnitude*, that predicts regulatory trouble.** A screen that flags "large non-GAAP gap" is therefore measuring the wrong thing. The right construct is **recurring items excluded** — e.g. depreciation and amortisation (excluded by 46% of firms), net interest expense (30%), or stock-based compensation. Related evidence from the same paper: 43% of low-quality non-GAAP reporters present a non-GAAP figure above EBITDA, versus 3% of high-quality reporters.

**SEC rules (read in full at [sec.gov non-GAAP C&DIs](https://www.sec.gov/divisions/corpfin/guidance/nongaapinterp.htm)).** The C&DIs state that excluding "normal, recurring, cash operating expenses" can be misleading; that an expense occurring "repeatedly or occasionally, including at irregular intervals" is "recurring"; that presenting only charges and never gains can render a measure misleading under Rule 100(b); at Q100.06 that extensive disclosure does **not** cure a materially misleading measure; and at Q102.10(c) that a "non-GAAP income statement" constitutes undue prominence. Then-SEC Chief Accountant Wesley Bricker stated on 4 April 2018 that non-GAAP "may supplement but is not a substitute for GAAP," and that controls must prevent "error, manipulation, or mischief with the numbers" ([speech](https://www.sec.gov/newsroom/speeches-statements/speech-bricker-040318)).

The 2016 enforcement wave is documented too: SEC staff issued "a significant number of comments" on filings potentially non-compliant with Regulation G and/or Item 10(e) of Regulation S-K, focused on **prominence** (non-GAAP presented more prominently than GAAP, "particularly in the highlights section of an earnings release"), **reconciliation** failures, and inadequate explanation of **usefulness and purpose**. Chair Mary Jo White said in June 2016 that use of these measures extends "too far and beyond what is intended and allowed by [SEC] rules," and the Division of Enforcement sent inquiries about earnings releases predating the C&DIs ([Sullivan & Cromwell memo, 4 October 2016](https://www.sullcrom.com/SullivanCromwell/_Assets/PDFs/Memos/SC_Publication_Non_GAAP_Financial_Measures_10_04_16.pdf)).

**One more slide-level claim.** Dechow's conference deck lists "Firms that use non-GAAP earnings are more likely to restate," citing Audit Analytics via the *Wall Street Journal* of 4 August 2016 ([Dechow slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf)). This is a slide citation, not a paper — treat the specific claim as **[B]** and weak, though it is directionally consistent with Dechow, Loh & Wang.

**The implementation problem, stated plainly.** **Non-GAAP figures are not in XBRL.** They appear in earnings press releases (8-K Exhibit 99.1) as free text or as inline XBRL only if the company chooses to tag them — and most do not. XBRL contains the statutory number. Therefore:
- The *gap* cannot be computed from XBRL alone.
- The system would need to fetch 8-K exhibits, extract the reconciliation table, and parse it. That is a text-extraction problem with a long tail of formats, not a data problem.
- A partial XBRL-only proxy exists: `EarningsPerShareDiluted` versus any separately tagged adjusted figure is unreliable; but a **higher-quality, XBRL-only substitute** is to flag firms whose *statutory* results are deteriorating while they also have a history of large special items — i.e. use the accrual, DSO and inventory markers above instead.

**Caveats.**
- Excluding genuine one-offs (a legal settlement, a divestment gain) is legitimate and informative. DLS's result is about the *average* predictive content of exclusions, not proof that any specific exclusion is abusive.
- Since the 2016 C&DI crackdown, presentation has become more standardised, so the *size* of the gap in recent years is not comparable to the 1990s/2000s sample.

**XBRL difficulty: High / not really feasible.** This is the single worst cost-to-value ratio on the list for an XBRL-only system. **Recommend deprioritising** unless the system already ingests 8-K exhibits.

---

## 13. Auditor changes, restatements, late filings, going-concern language

This cluster is qualitatively different from the others: **almost none of it is in XBRL.** These are filing *events* and *text disclosures*, not tagged facts.

### 13a. Restatements — well-evidenced

**Base rate (verified).** The PCAOB's October 2025 Data Point on financial restatements and auditor turnover reports that "Big R" restatements — the serious kind filed on **8-K Item 4.02** — "occurred at a rate of around **3% per year**" over 2005–2024 ([PCAOB Data Point 04-2025](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf)).

**Announcement reaction — magnitude depends heavily on restatement *type*.**

| Study | Sample | Reaction |
|---|---|---|
| GAO-06-678 | 1,390 restatements by 1,121 companies, Jul 2002 – Sep 2005 (1,061 in the event study) | Immediate 3-day market-adjusted market-cap loss **$36.5bn = 0.25%** of $14,662bn total; **average stock decline "almost 2 percent"**; 20-day **−1.7% / −$78.6bn**; 60-day **−1.7% / −$126.3bn** ([GAO PDF](https://www.gao.gov/assets/gao-06-678.pdf)) |
| Hennes, Leone & Miller (2008), *TAR* 83(6) 1487–1519 | Restatements split into irregularities vs errors | Market reaction **−14% for irregularity restatements vs −2% for error restatements**; most irregularities were followed by fraud class actions, versus **one** lawsuit in the error group |
| Palmrose, Richardson & Scholz (2001) | 403 restatements of quarterly and annual statements, 1995–1999 | mean **(median) −9.2% (−4.6%)** over the 2-day announcement window ([via Agrawal & Chadha](https://pages.stern.nyu.edu/~rengle/Agrawal.pdf)) |
| Anderson & Yohn (2002) | 161 firms restating audited annual statements, 1997–1999 | mean **(median) −3.5% (−3.8%)** over days (−3, +3); for **revenue-recognition problems about −11% (−8%)** ([via Agrawal & Chadha](https://pages.stern.nyu.edu/~rengle/Agrawal.pdf)) |

GAO's by-reason immediate market-adjusted returns: related-party **−3.76%**, restructuring −2.13%, **revenue recognition −2.05%**, cost/expense −1.25%, securities −0.77%, M&A −0.49%, reclassification **+0.04%**.

**The critical caution.** GAO's average reaction is only about **2%**, against Palmrose's −9.2%, because GAO's 1,390-restatement sample is dominated by routine error-type restatements rather than fraud. Hennes, Leone & Miller's −14% versus −2% split explains the gap. **"Restatement" is not a single signal** — the −14% tail is real but rare, and a screen that flags all restatements will mostly flag −2% events.

**Governance result worth noting:** in Agrawal & Chadha's 159 restating firms (2000–2001) and 159 industry-size matched controls, an independent director with an accounting/finance background was associated with a **0.31 lower probability of restating** on the board and **0.23 lower** on the audit committee. Of their 159 restatements, **130 reduced earnings**, 21 increased them, the median absolute earnings change was **38.61%**, and the median number of quarters restated was **4** ([PDF](https://pages.stern.nyu.edu/~rengle/Agrawal.pdf)).

### 13b. Auditor changes — a real ~2.6× lift

**Effect size (verified).** The PCAOB reports that **29% of companies with a Big-R restatement had reported an auditor change in the year preceding the restatement**, against a broader-population auditor-change rate of **8% to 13%, averaging 11%** ([PCAOB Data Point 04-2025](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf)). That is roughly a **2.6× lift**.

**Read it correctly.** This is a *backward* conditional — P(auditor change | restatement) — not P(restatement | auditor change), which is what a screen needs. Given a ~3% restatement base rate and an ~11% auditor-change base rate, the forward probability remains low even at 2.6× lift. Use it as a **weight**, not a trigger.

### 13c. Late filings — modest, and the headline effect is fragile

**Statutory mechanics (read in full).** Form 12b-25 (EDGAR types **NT 10-K** and **NT 10-Q**) must be filed "no later than one business day after the due date" of the report, and grants **15 calendar days for a 10-K and 5 calendar days for a 10-Q**. A late filer also loses S-3 short-form registration eligibility until the report is actually filed ([17 CFR 240.12b-25](https://www.law.cornell.edu/cfr/text/17/240.12b-25)).

**Effect sizes — and the caveat that matters.**
- In the ANU study of **17,951 SEC filing reviews (46,708 comment letters, 2005–2019)**, a prior-year late-filing indicator carried an **odds ratio of 1.401 (p < 0.01)** for CEO/CFO turnover during the review, with prior-year restatement and adverse SOX 404 opinions also positive (ICW odds ratio 1.237, p < 0.05). Late filing had a sample mean of 11.7% ([Ma, ANU doctoral thesis, 2024](https://openresearch-repository.anu.edu.au/server/api/core/bitstreams/d287b802-8069-4e55-ad48-95bb7d1dab8b/content)).
- In a study of **37,319 10-K filings**, **5,655 (15%) were late**; late filing significantly predicted restatement and delisting, with a delisting × late interaction of **−0.46**. **However, the effect was driven by about 51 small notifier-delisters, and "once these extreme delisters are removed… the remaining sample of the late filers does not appear to under-perform."** Also, **91% of non-notifiers file within 15 days**, so most "late" filings are trivially late (Pevzner working paper, as reported in the [PCAOB Data Point](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf) summary of the late-filing literature).

**Verdict: [C] for the underperformance claim, [B] for the regulatory-stress signal.** Late filing predicts management turnover and SEC attention, not returns.
- Note also that SEC enforcement has been applied to the **content** of the NT form: in August 2023 five companies and in April 2021 eight companies were charged for omitting anticipated-restatement reasons from Form 12b-25, with restatements announced 3–21 days after the NT, penalties of $35k–$60k, and **strict liability** (reported in the [PCAOB Data Point](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf)).

### 13d. Going-concern opinions — the two-sided number

**Effect sizes (verified as reported).** The *CPA Journal* (February 2016), paraphrasing Carson et al. (2013), states that **"40% of public company bankruptcies are not preceded by audit reports modified for going concern uncertainties"** and that **"98.3% of bankrupt firms survive for at least one year from the issuance of a going concern audit report"** ([CPA Journal](https://www.cpajournal.com/2016/02/02/going-concern-gap-u-s-gaap/)).

Read together: a going-concern paragraph catches roughly **60%** of firms that subsequently go bankrupt within a year, but **98% of firms receiving one survive that year**. So it is simultaneously a *meaningful* signal (60% sensitivity beats most accounting models) and a *terrible* classifier (a ~2% one-year bankruptcy rate among flagged firms makes precision very low). **UNVERIFIED at primary source** — Carson et al.'s own figures were not opened; the CPA Journal is a secondary paraphrase.

### 13e. What this cluster costs to build

**None of §13 is in XBRL.** The relevant artefacts are:

| Signal | Where it lives | Encoding |
|---|---|---|
| Auditor change | **8-K Item 4.01** + Reg S-K Item 304 disclosure | Filing event + text |
| Restatement / non-reliance | **8-K Item 4.02** (due within 4 business days, **no** 12b-25 extension) | Filing event + text |
| Late filing | **Form 12b-25** = EDGAR types **NT 10-K / NT 10-Q** | Filing event |
| Going-concern opinion | Audit report **narrative** inside the 10-K | Text only |

**Recommendation.** Treat this cluster as an **event-feed layer**, not a scored accounting marker. Three EDGAR form/item codes — 4.01, 4.02, NT 10-K/NT 10-Q — give you high-signal, low-ambiguity flags for near-zero compute once filing metadata is ingested. Going-concern detection requires full-text search and should be a human-review trigger.


---

## 14. Operating leases and the IFRS 16 / ASC 842 break

**Definition.** Before 2019, most lessees kept operating leases off-balance-sheet, disclosing only future minimum lease payments in the notes. Both major frameworks now require capitalisation.

**Verified primary source.** IFRS 16 "Leases" is **effective for annual reporting periods beginning on or after 1 January 2019**, with earlier application permitted only if IFRS 15 is also applied. It "introduces a single lessee accounting model and requires a lessee to recognise assets and liabilities for all leases with a term of more than 12 months, unless the underlying asset is of low value. A lessee is required to recognise a right-of-use asset representing its right to use the underlying leased asset and a lease liability representing its obligation to make lease payments." IFRS 16 replaced IAS 17, IFRIC 4, SIC-15 and SIC-27 ([IFRS Foundation, IFRS 16 standard page](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/)).

US GAAP equivalent: ASC 842, effective for public business entities for fiscal years beginning after 15 December 2018.

**Why it matters for this system — the comparability break.** The change is mechanical and large for lease-heavy businesses (retail, airlines, restaurants, logistics):
- **Leverage rises.** A lease liability appears that did not exist before, so net debt/EBITDA, debt/assets and Altman's X4 all move for reasons unrelated to the business.
- **Reported operating cash flow rises**, because lease payments are reclassified out of operating and into financing. This directly contaminates the accruals measure in §1 and the cash-conversion ratio in §8 across the 2018/2019 boundary.
- **EBITDA rises** (rent expense is replaced by depreciation and interest), flattering net debt/EBITDA even as debt increases.
- **Working capital and current ratio shift** depending on whether the lease liability is classified current or non-current.

**How big was the hidden obligation? (verified, from the standard-setter's own analysis.)** The IASB's IFRS 16 *Effects Analysis* (January 2016) reports that for the heaviest users of off-balance-sheet leases, **long-term liabilities were understated by 22% in North America, 26% in Europe, 32% in Asia/Pacific, 45% in Latin America and 27% in Africa/Middle East**. For failed retailers the ratio of discounted off-balance-sheet lease commitments to on-balance-sheet long-term debt was extreme:

| Company | Off-B/S leases vs on-B/S long-term debt |
|---|---|
| Circuit City | **65.86×** ($3,293m vs $50m) |
| Woolworths UK | 10.90× |
| Clinton Cards | 9.05× |
| HMV | 7.03× |
| Borders | 5.68× |
| Praktiker | 3.69× |

The IASB's summary: "the present value of off balance sheet lease commitments of these companies range from approximately 4 times to more than 65 times higher than the long-term debt that they reported on balance sheet." The policy trigger was the SEC's 2005 estimate that US public companies carried roughly **US$1.25 trillion** of off-balance-sheet leases ([IASB Effects Analysis](https://www.ifrs.org/content/dam/ifrs/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf)).

**How big was the reported impact after adoption? (three independent samples.)**
- Heese, Shin & Wang (2023), ~2,900 unique US firms FY2014–2021: "book debt-to-equity ratios increase significantly (about **21–25%**)" after ASC 842 adoption; equity betas rise **1.7–5%**; credit ratings fall **1.5–3.5%** ([PDF](https://business.columbia.edu/sites/default/files-efs/imce-uploads/ADP/Heese%20Shin%20Wang%202023.pdf)).
- Ferreira, Landsman & Roundtree (2024), US sample n = **2,822** entities, 2018–2020: entities "reduced their liabilities unrelated to leases by **7% ± 10%** as their lease-related liabilities increased by **5%**" — substituting equity for debt and re-adjusting to target leverage under covenant pressure ([IFRS staff paper 7F, March 2025](https://www.ifrs.org/content/dam/ifrs/meetings/2025/march/iasb/ap7f-review-academic-literature.pdf)). **The interpretation matters:** because firms actively unwound non-lease debt as lease debt came on, the *reported* post-adoption leverage change **understates** the true economic change. Cross-sectional comparability across the 2018/19 transition is worse than a naive "just capitalise the leases" adjustment implies.
- Cheng, Geng & Zhao, 22,201 firm-year observations across 3,028 US companies FY2011–2020: "This change **drastically increases** firms' reported leverages"; measured operating-lease leverage averaged 0.0475, and reported leverage exceeded what footnote-based estimates implied. The finance-lease share of total lease leverage rose from 0.0620 to 0.1149 ([PDF](https://business.columbia.edu/sites/default/files-efs/imce-uploads/ADP/Agnes%20Cheng%20Geng%20Zhao%20202209.pdf)).

**The residual hole — and it is large.** Heese et al. find firms shifted toward **variable** leases to stay off-balance-sheet. Recognising variable leases "would add a total of **$281 billion** in total debt", an average **+7.7%** debt increase (over 10% in consumer durables, food & staples retailing and transportation; over 13% in retailing and pharmaceuticals). Variable-lease liabilities are roughly **25% mean / 17% median** of reported operating-lease liabilities, and 51% of firms reported variable-lease expenses by 2021 ([Heese et al.](https://business.columbia.edu/sites/default/files-efs/imce-uploads/ADP/Heese%20Shin%20Wang%202023.pdf)). **However, Heese et al. explicitly reject the incentive hypothesis** for the operating-lease decline — distressed firms do not show larger declines, and they favour a compliance/measurement explanation. So "firms deliberately hid leases via variable contracts" is **contested, not established.**

**Analyst adjustment before 2019 — the popular story is half right.** The IASB found that "Most investors and analysts that the IASB consulted used that information to estimate assets and liabilities arising from off balance sheet leases. Some tried to estimate the present value of future lease payments. However, because of the limited information that was available, **many others used techniques such as multiplying the annual lease expense by 8**," and that adjustments "would not have been comparable." Moody's revised its own capitalisation methodology, extending the debt adjustment to "many more companies" ([Effects Analysis](https://www.ifrs.org/content/dam/ifrs/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf)). So the accurate statement is "adjusted inconsistently and with limited information," **not** "failed to adjust."

**IFRS 16 is not the same as ASC 842 — a cross-listing trap, and it breaks X3 specifically.** "applying the FASB model, differences arise between the measurement of lease assets and lease liabilities for former off balance sheet leases if, for example, the lease asset is impaired" ([Effects Analysis, fn.69](https://www.ifrs.org/content/dam/ifrs/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf)). More importantly for Altman, **FASB's dual model keeps the entire lease cost in operating expense, whereas IFRS 16 splits it into depreciation and interest.** An IFRS 16 filer and an ASC 842 filer with economically identical leases therefore **diverge on EBIT/total assets (X3)** while showing the same X4 denominator effect. **Any cross-border use of the Z-score mixes two different X3 treatments.** Transition timing compounds this: 87.1% of Cheng et al.'s firms adopted in FY2019 and 0.23% early, so the comparability window is wider than a single year.

**The honest position.** The direction and rough magnitude of the pre-2019 understatement, and of the post-adoption leverage increase, are now well evidenced. What is **not** verified is the exact correction factor for any specific ratio in your pipeline. **Do not assume one — rebuild the series on a consistent basis.**

**Practical implementation.**
- Post-2019 tags exist: `OperatingLeaseRightOfUseAsset`, `OperatingLeaseLiabilityCurrent`, `OperatingLeaseLiabilityNoncurrent`, `FinanceLeaseRightOfUseAsset`, plus `OperatingLeaseCost` / `OperatingLeasePayments`.
- For pre-2019 comparability you must either (a) restrict ratio history to post-2018, (b) capitalise the disclosed future minimum lease payments yourself using the old IAS 17 / ASC 840 note disclosure (a text/notes problem), or (c) accept the break and flag it in the UI.
- **Recommended: (c) plus (a).** Show the ratio with an explicit "accounting basis changed in 2019" marker and do not compute trend deltas across the break.

**XBRL difficulty: Low** to read the post-2019 tags; **High** to construct a consistent pre/post series.

---

## 15. SPVs, off-balance-sheet entities and the Enron lesson

**Definition.** Special purpose vehicles and structured entities can hold debt or risky assets outside the consolidated group, so reported leverage understates economic leverage.

**The accounting framework, and a correction to a common premise.** The question is whether the sponsor consolidates the vehicle. The pre-Enron international rule was **SIC-12**, a risks-and-rewards test that in practice meant computing whether the investor was exposed to risks and rewards "to the extent of **50% or more**. With this bright-line test…" **IFRS 10** (issued May 2011) replaced SIC-12 and IAS 27 with a single control model requiring **all three** of power, exposure to variable returns, and a link between them; an entity acting as agent consolidates for its principal. "The introduction of IFRS 10 **removes the 'bright lines'** that were earlier pertinent under SIC 12" ([Kothari, "Securitisation vehicles: does unconsolidated status become easier under IFRS 10 and IFRS 12?"](https://vinodkothari.com/wp-content/uploads/2014/01/Consolidation-of-Securitized-Vehicles-under-IFRS.pdf)).

**Correction worth noting:** the bright-line tests in this area were in the **accounting standards**, not in SEC policy. The SEC's documented contribution was its 2005 estimate of ~$1.25tn of off-balance-sheet leases and its 2005 report to Congress on off-balance-sheet arrangements and SPEs.

**Evidence status: [B] case-based; no validated screen.** I did **not** find a quantitative marker of SPV exposure with reported predictive performance. **UNVERIFIED.**

**Enron specifics are UNVERIFIED and deliberately not asserted.** No primary source could be opened — the US Senate PSI report is a scanned image PDF with no text layer, and FASB, SEC, ISDA and law-review sources were blocked or unreadable. **Do not repeat the widely circulated "3% outside equity" test or Chewco/JEDI mechanics on the strength of this report.** The general *pattern* — SPEs used to keep debt and losses off the sponsor's balance sheet while the sponsor retained economic risk, followed by tightened consolidation rules — is safe; the mechanics are not verified here.

**Why it resists XBRL.** Consolidated statements contain only consolidated figures by construction. SPV exposure lives in the notes: IFRS 12 requires disclosure of the nature and extent of interests in **unconsolidated structured entities** and the nature of risks, including maximum exposure to loss — precisely because exposure can be significant without consolidation. These are narrative and tabular disclosures with no single standard tag and little cross-filer consistency. Consolidation is itself a judgement under IFRS 10's three-element gate, so identical exposure can be presented differently by different issuers.

**Practical substitute.** Where off-balance-sheet risk is *partly* visible in XBRL: `GuaranteesGuarantorObligation`-type tags where filers tag guarantees; a large gap between reported debt and total interest expense (implied hidden debt); and the presence of a `CommitmentsAndContingencies` disclosure, which is a boolean signal with no magnitude.

**Recommendation: deprioritise.** High implementation cost (notes mining), thin evidence base, and no clean tag. This is a human-review trigger when other flags fire, not an automated score.

---

## 16. Receivables factoring and supply-chain finance

**Definition.** Selling receivables to a bank (factoring) or extending supplier payment terms via a bank-funded reverse-factoring programme (supply-chain finance) moves cash earlier and payables later, flattering operating cash flow and lowering DSO without changing the underlying economics.

**The exact mechanism, in the standard-setter's own words.** Under a supplier-finance arrangement "the company as the buyer (1) purchases and receives goods or services… A finance provider (2) offers to pay amounts the company owes to its supplier. The company (3) agrees to pay the finance provider at the same date as, or a date later than, the supplier is paid." The cash-flow effect is three-part: "**(1) a cash flow benefit in operating activities when the trade payable is recognised; (2) a non-cash transfer in cash flows from financing activities when the trade payable is derecognised and a new class of financial liability is recognised; and (3) a cash outflow in financing activities when the new liability is settled with the finance provider**" ([IASB Investor Perspectives: Supplier Finance Arrangements, November 2021](https://www.ifrs.org/content/dam/ifrs/project/supplier-finance-arrangements/investorperspectives-sfa-nov2021.pdf)). That is the mechanical reason operating cash flow looks better than it is.

**The direction of the bias, which is what matters for a screen:**
- **Factoring lowers DSO.** A company that factors looks *better* on the DSO-drift screen in §10 while carrying the same credit risk. The signal is **inverted**, not merely noisy. This is the single most important reason not to treat a low DSO as automatically good.
- **Reverse factoring moves trade payables into a financial liability.** Presentation is optional and inconsistent: "The size, nature or function of financial liabilities that are part of a supplier finance arrangement (1) will determine whether the company presents the liabilities separately in its balance sheet and (2) help in determining whether to present the related cash flows in operating or financing activities… **Different arrangements may result in different presentations.**" The IASB's own worked example shows SCF liabilities falling due **85–90 days after invoice** versus **60–70 days** for ordinary trade payables — so a blended payables caption can look far worse than the economics, while reclassifying them out of trade payables can flatter a revenue-denominated DSO while worsening debt. **Both directions of error are possible.**

**The strongest verified case evidence: Carillion (FRC).** Carillion operated an Early Payment Facility — "a reverse factoring (or supply chain finance) facility under which invoices raised by Carillion's suppliers were paid by participating banks, with Carillion repaying the banks at a later date." The FRC's findings:
- "The total value of invoices on the EPF platform at any one time was substantial and **rose from £35 million as at 31 December 2012 to £472 million as at 31 December 2016**."
- "liabilities to banks under the EPF were **not included in reported debt**. **There was no disclosure explaining this treatment** and the amounts were **not identified as owed to banks**."
- "Carillion's internal estimates of the impact on reported debt in 2016 **varied widely, from £100 million to over £300 million**."
- There was "a very significant disparity between net borrowing at the year end of **£218 million**… and the amount both in the months immediately before the year end and in the months immediately following, which was **in excess of £700 million**" — movements KPMG's partner recognised were "strongly suggestive of manipulation of borrowing at year end - for example, by delaying payments to creditors."
- Carillion announced provisions totalling **£1.045 billion** in 2017.

([FRC, Annual Enforcement Review 2024, pp. 37–39 and ~63–64](https://media.frc.org.uk/documents/Annual_Enforcement_Review_2024_PrjyJ48.pdf)).

**Greensill is UNVERIFIED.** Only the report's identity could be confirmed — Treasury Committee, *Lessons from Greensill Capital*, HC 723, published 24 September 2021 ([parliament record](https://api.parliament.uk/committees/publications/7430)). The document itself sits behind a Cloudflare challenge on every route tried. **No Greensill figures or findings are asserted here.**

**The new disclosure regime — and its scope limit.** The IASB issued amendments to **IAS 7 and IFRS 7, "Supplier Finance Arrangements," on 25 May 2023, effective 1 January 2024**. They require disclosure of the terms and conditions, the carrying amount of in-scope liabilities (breaking out amounts for which suppliers have already been paid by finance providers), **where those liabilities sit on the balance sheet**, ranges of payment due dates, and liquidity risk ([IASB announcement](https://www.ifrs.org/news-and-events/news/2023/05/iasb-increases-transparency-of-companies-supplier-finance/)). Critically, the **scope excludes receivables factoring**: asked "Do the proposals include arrangements that finance receivables (for example factoring) or inventories?", the IASB's answer is "**No**" ([Investor Perspectives, p.3](https://www.ifrs.org/content/dam/ifrs/project/supplier-finance-arrangements/investorperspectives-sfa-nov2021.pdf)). Classic receivables factoring therefore remains largely undetectable from standardised data.

**A caution on sufficiency the IASB itself concedes:** for some arrangements "companies do not currently obtain information about the carrying amount of financial liabilities for which suppliers have already received payment." So even post-2024 the disclosure may be incomplete. **No verified large-sample estimate of how much supply-chain finance flatters OCF or DSO market-wide was found.**

**Workable proxies available today:**
1. **The year-end pattern.** Carillion's £218m year-end net borrowing against >£700m in adjacent months is more diagnostic than the stock of SCF, and is computable from ordinary data. Flag a persistent, large year-end dip in net debt that reverses within a quarter.
2. **Payables days rising faster than COGS**, or DPO decoupling from inventory days.
3. **Divergence between the "trade and other payables" caption and the cash-flow-statement change in payables.** If the balance sheet shows a shrinking payables balance while the cash flow statement shows a large payables inflow, the liability has probably been reclassified rather than settled.
4. **Cash-flow-statement vs balance-sheet accruals divergence.** If `(NI − CFO)` says accruals are low but the balance-sheet measure says receivables have ballooned, something is being financed off the operating line.

**Verdict: [B] for the mechanism and the Carillion facts (an FRC enforcement document, not an academic estimate); [D] for any market-wide screen.** Adjust both sides if you adjust at all — add financed amounts to debt *and* reclassify the associated cash flows from operating to financing; doing only one flatters either leverage or cash conversion.

**XBRL difficulty: High** for direct detection pre-2024 and for US GAAP filers at any date; the proxies above are Low/Medium. Whether the 2023 amendments create dedicated taxonomy elements or only narrative text blocks is **UNVERIFIED** — check the IFRS taxonomy before building.

---

## Cross-cutting caveats that apply to every marker

1. **Post-publication decay is the base case, not the exception.** 26 ppts of the drop happens out-of-sample and a further 32 ppts after publication across 97 predictors ([McLean & Pontiff digest](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary)); 64–85% of 447 anomalies fail replication thresholds ([Hou, Xue & Zhang](https://www.nber.org/papers/w23394)). Budget for the possibility that any factor you build from these markers has already been arbitraged.
2. **Base rates govern usefulness.** Every one of these markers is a rare-event classifier, and the base rates are now verifiable:

| Event | Base rate | Source |
|---|---|---|
| Fraud / manipulation-year AAER | **~0.5% of Compustat firms per year** | [Dechow slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf) |
| Performance-related delisting | **~3% of firms per year** | [Dechow slides](https://care-mendoza.nd.edu/assets/213211/dechow_slides.pdf) |
| Big-R restatement (8-K Item 4.02) | **~3% per year, 2005–2024** | [PCAOB Data Point 04-2025](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf) |
| Auditor change | **8–13%, averaging 11%** | same |
| Late 10-K filing | **15% of 10-K filings** | Pevzner, via [PCAOB](https://pcaobus.org/economicandriskanalysis/data-points/dp04-2025-financial-restatements-auditor-turnover.pdf) |
| Goodwill impairment, firm-year | **~2.3% per year; 14.1% of acquisitions eventually** | [Hayn & Hughes](https://anderson.ucla.edu/documents/areas/fac/accounting/goodwill_06.pdf) |
| Economic impairment not yet written down | **75–80% of firms showing economic impairment** | [André, Filip & Paugam](https://ideas.repec.org/a/taf/acceur/v13y2016i3p329-352.html) |
| S&P 500 firms reporting non-GAAP | **71%** | [Calcbench](https://www.calcbench.com/home/pdf?name=CB-2025-NONGAAP.pdf) |

At a 0.5% base rate, precision collapses for any model with AUC below roughly 0.9. **Rank, don't classify.**
3. **Never apply these to financial firms.** Explicitly excluded from Sloan's, Beneish's, Altman's and Chan et al.'s samples, and repeated as a caution for Dechow's.
4. **Sector-relative, not absolute.** The Georgia Tech EQI medians range from 1.81% (Consumer Durables) to 26.62% (Energy) — a 15× spread. Any absolute threshold is wrong for most of the universe.
5. **Accounting-standard breaks create false signals.** ASC 606 / IFRS 15 (revenue, 2018/2019), ASC 842 / IFRS 16 (leases, 2019), and the 2024 supplier-finance disclosure amendments all break time-series comparability. Flag the break; do not silently difference across it.
6. **XBRL restatement hazard.** XBRL data reflects the *restated* figures in later filings. A naive historical pull will show a clean history for a firm that restated. Keep a filing-date-aware, point-in-time view if you intend to backtest.
7. **Tag choice is a silent source of error.** `Revenues` vs `RevenueFromContractWithCustomerExcludingAssessedTax` vs `SalesRevenueNet`, and `AccountsReceivableNetCurrent` vs `ReceivablesNetCurrent`, will each change your numbers. Pin a documented fallback ladder and log which tag was used.

---

## Recommended shortlist

**Ranked by predictive value per unit of implementation cost, for an XBRL-only system with annual/interim statements and no intraday data.**

| Rank | Marker | Why it earns its place |
|---|---|---|
| 1 | **Cash-flow-statement accruals** (NI − CFO)/avg assets, ranked within industry | The most replicated accounting signal in the literature (Sloan 1996 → Chan et al. 7.4%, t = 3.83 → Ball et al. replication). Three XBRL tags. Sector-relative ranking avoids the EQI threshold trap. Its return-predictive magnitude has decayed, but the *earnings-persistence* result has not. |
| 2 | **ΔInventory / average total assets** | The sharpest verified number in the accrual decomposition: discretionary spread +9.1% (t = 7.02) versus non-discretionary −1.5%. Two tags. Deliberately avoids revenue and COGS denominators entirely. |
| 3 | **DSO drift via Beneish's DSRI** — a ratio of ratios | Largest single t-statistic behind Beneish's own manipulation model (0.920, t = 6.02), median 1.281 for manipulators vs 0.996 for controls. Needs no day-count assumption. Corroborated by SEC enforcement data (43% of schemes are revenue recognition). |
| 4 | **Dechow F-score** (as a ranked flag) | Built on 2,190 AAERs and 676 firms; still the accounting literature's standard benchmark. Six of seven variables come straight from XBRL. Standalone AUC is weak out-of-sample (0.554 in the Indonesian test), so use it to *rank*, never to classify. |
| 5 | **Goodwill / market-to-book economic-impairment indicator** | Genuinely additive and rarely used by retail tools: 75–80% of firms showing economic impairment have not written it down (André, Filip & Paugam, >35,000 firm-years). Also directly surfaces serial-acquirer balance sheets. Low XBRL cost if you have market cap. |
| 6 | **Piotroski F-score, computed only for high-book-to-market names** | Strong primary evidence (+9.7% market-adjusted hedge, t = 5.059; low-score firms >5× more likely to delist), and it replicates internationally (0.79%/mo developed ≈9.9%/yr; 0.95%/mo emerging). The caveats are that the setting *is* the strategy, and it is fragile in US value-weighted samples after 1997 and may be repackaged style-factor beta. |
| 7 | **Cash conversion trend: (OCF − NI)/Revenue, industry-relative, with a stability band** | The closest thing to a documented practitioner formulation (Georgia Tech EQI), and the trend rule is theirs, not invented. Use trend and industry rank, **not** a global "<1" threshold, which has no evidentiary support. |
| 8 | **Filing-event flags: 8-K Item 4.01 (auditor change), 8-K Item 4.02 (non-reliance/restatement), NT 10-K/NT 10-Q (late filing)** | Not XBRL, but the cheapest high-signal flags available: three unambiguous EDGAR form/item codes. Restatements occur at ~3% per year; announcement reactions run from ~−2% (error-type) to −14% (irregularity-type); 29% of Big-R restatements were preceded by an auditor change against an 11% base rate (~2.6× lift); late filing carries odds ratio 1.401 for management turnover. Near-zero compute once you ingest filing metadata. |

**Deliberately excluded, and why:**

- **Altman Z-score, Ohlson O-score and Zmijewski probit.** Low to build, but the evidence does not support them as *screen inputs*. The single most damaging number is Hillegeist et al. (2004): on 78,100 firm-years and 756 bankruptcies, the Z-Score's pseudo-R² is **0.07** against **0.12** for a market-based alternative — and **three of Z's five inputs (X1, X2, X5) are statistically insignificant**, with re-estimation making it *worse*. Agarwal & Taffler add the population-level datum: applied to US non-financial listed firms 1988–2003, **47% sat below the 2.675 cutoff while 19% of firms entering Chapter 11 were above it**. Altman's headline 95% is in-sample on 66 manufacturers from 1946–65 with assets of $1–25m, and his own horizon table falls to 72% at two years and 48% at three; out-of-sample the models are **asymmetric in the wrong direction** — 93–95% overall accuracy but only **32–48% of bankrupts caught**. Note also that the failure mode changed over time: Altman's Type I accuracy in 1997–99 was still 94%, while he concedes Type II error rose to "about 15–20%". That is a machine for over-flagging healthy firms. Ohlson is not better: its headline 96% sits barely above the 95.15% naive all-negative baseline, its two circulating error-rate figures are mutually inconsistent, and Hillegeist found "five of the eight significant coefficients have different signs" out-of-sample. Zmijewski's coefficients rest on a single MSc thesis and critics call it effectively a one-variable model. Your system already computes net debt/EBITDA and interest cover, which capture much of the same distress information with fewer vintage assumptions. If you display one, use **Altman Z″** (book equity, so no price feed needed, and Altman recommends it precisely where "lease capitalization… [is] not made") — but do not rank on it.
- **Beneish M-score as an alpha signal.** Its own holdout misses 50% of manipulators, and it scores AUC 0.513–0.554 in independent non-US tests. Its *components* (DSRI, TATA) are worth extracting — the composite is not.
- **Non-GAAP gap as a magnitude screen.** Two independent findings kill the naive version: exclusion **magnitude** does not predict SEC comment letters or Reg G violations, and the data is not in XBRL at all. If you ever ingest 8-K exhibits, screen on exclusion **quality** (recurring items excluded), which does predict (+17% comment-letter likelihood, +30% Reg G violation odds per unit decline).
- **SPVs.** Real mechanism, no validated screen, high notes-parsing cost.
- **Going-concern opinions.** ~60% sensitivity for one-year bankruptcy, but only ~2% precision, and the signal is text-only. Human-review trigger.

**One architectural point that should shape the build.** Three of the most valuable signals on this list — auditor change, restatement and late filing — are **SEC filing-event data, not XBRL facts**. So are non-GAAP figures and audit-report text. A system that tries to derive them from XBRL facts will silently return nothing:

| Signal | Encoding |
|---|---|
| Non-GAAP / adjusted earnings, Reg G reconciliation | 8-K **Item 2.02**, Exhibit 99.1 (text). **Not in XBRL.** |
| Auditor identity / change | 8-K **Item 4.01** + Reg S-K Item 304 |
| Restatement / non-reliance | 8-K **Item 4.02** (4 business days, no 12b-25 extension) |
| Late filing | Form **12b-25** = EDGAR form types **NT 10-K / NT 10-Q** |
| Auditor's going-concern opinion | Audit-report **narrative** |
| Management's going-concern disclosure | `us-gaap:SubstantialDoubtAboutGoingConcernTextBlock` (a text block, not a value) |

**UK-specific limit.** A UKSEF report uses Inline XBRL with **multiple target documents** — a default ESEF/IFRS target plus a `UKFRS` target using FRC taxonomy prefixes (`bus:`, `core:`, `direp:`, `aurep:`) ([FRC UKSEF 2025 Tagging Guide v2.1](https://media.frc.org.uk/documents/UKSEF_2025_Tagging_Guide_v2.1.pdf)). **Companies House's mandatory tag list contains no goodwill element** — it mandates identifiers, dates, `core:ProfitLoss`, audit status/type and, for group audited accounts, `aurep:OpinionAuditorsOnEntity`. So for a UK company you can obtain `ifrs-full:Goodwill` from the ESEF target but **the going-concern paragraph is not machine-readable**, and UK building society / micro-entity filings may have no P&L at all.

**Two design rules that follow from the evidence:**

1. **Rank, never classify.** With a 0.5% fraud base rate, every one of these models produces more false positives than true positives at any useful sensitivity. Output a percentile within industry, not a binary flag. And never accept a single "accuracy" number: at a 5% base rate, always-predict-healthy scores 95%.
2. **Trend beats level, and industry-relative beats absolute.** The Georgia Tech EQI medians span 1.81% to 26.62% across industries, and the Lab's own stability rule is a ±15% year-on-year band rather than a threshold. This is the most under-appreciated practical finding in the whole review.
3. **Refuse to compute when inputs are absent — and say so in the UI.** The verified coverage findings in §3a and §3b are the sharpest engineering lesson in this report: roughly 21% of US filers report total assets with no current-asset split (so X1 is undefined), and UK small and micro filers are *statutorily* exempt from filing a profit and loss account (so X3 and X5 cannot exist). Silently defaulting a missing input to zero — the natural behaviour of most extractors — produces a confidently wrong score for a large minority of the universe. Emit "not computable" instead.

---

## Methodology and known gaps

**How sources were retrieved.** Direct HTTP retrieval was blocked by Cloudflare or bot checks at SSRN, Wiley, ScienceDirect, Springer, INFORMS, Taylor & Francis, SAGE, tandfonline and SEC.gov. Paywalled PDFs were read through the `r.jina.ai` text-extraction proxy against the original publisher/author URL. In every case the link given is the **original source URL**, so it can be independently checked. Where a PDF rendered in a browser but not in the text extractor, page images were inspected directly.

**Note for anyone reproducing the EDGAR work.** `sec.gov` and `data.sec.gov` reject the plain fetch tool ("Undeclared Automated Tool"), but the JSON APIs respond normally to a scripted `fetch` carrying a browser User-Agent. That is how the tag-coverage and frames counts in §3a were produced, and it is the route to use for any further EDGAR verification.

**Load-bearing claims I could NOT verify (restated for the reader):**

1. **Sloan (1996)'s own hedge-portfolio return** — commonly quoted near 10% per year. The paper is paywalled and the only reachable sources quoting the figure are a teaching reproduction and a machine-generated blog. **Treat as UNVERIFIED.** The Chan et al. replication spread (+7.4%, t = 3.83) is verified and is the number to rely on.
2. **Ohlson (1980)'s actual reported Type I/Type II error rates and the cutoff they were measured at** — the only free copy is a JSTOR scan with no OCR text layer. The two secondary figures I found (87.6%/82.6% at cutoff 0.038 versus 96.12% overall) are mutually inconsistent. The **CLCA direction (CL/CA vs CA/CL) and the leverage coefficient (6.03 vs 0.603) also conflict across sources.**
3. **Zmijewski (1984)'s precise coefficients (−4.336/−4.513/5.679), the probit transform, and even a confirmed DOI** — all rest on a single MSc thesis.
4. **Dechow et al. (2011)'s own reported classification accuracy** — paywalled; the conference-slide tables are images that did not decode. The out-of-sample AUC of 0.554 is verified from an independent study.
5. **Doyle, Lundholm & Soliman (2003)'s return spread and sample period** — direction and robustness verified from the abstract; magnitudes not. Every open mirror was behind a bot wall, and the Wayback PDF renders without an extractable text layer.
6. **Thomas & Zhang (2002)'s own effect sizes** — paywalled; the verified numbers are from the Chan et al. replication path.
7. **Altman (1968) itself** — closed access. All 1968 attributions come from Altman's own 2000 revisiting paper, which reproduces the tables. The group-mean discrepancy (−0.29/+5.02 vs −0.25/+4.48) is unresolved.
8. **Altman, Iwanicz-Drozdowska, Laitinen & Suvas (2017, JIFMA 28(2)) — RESOLVED at the coefficient level, still unverified for its own results.** The Z′/Z″/Z″-EM coefficient sets and the +3.25 constant's stated purpose are **now primary-verified from Altman's own 2000 text** (see §3). The 2017 paper itself remains closed access, so its **sample period, firm counts and country-level AUCs are UNVERIFIED**; only its abstract-level claim of "AUC of about 75%, and exceptionally well for some (above 90%)" is available.
9. **Shumway (2001)'s own accuracy figures** — the paper could not be accessed. Note the trap recorded in §3c: an AUC of 0.851 circulating against a "Shumway (2001)" label belongs to a thesis's own German replication. **Do not attribute it to Shumway.**
10. **Begley, Ming & Watts (1996)'s exact error-rate pairs** (Altman 18.5%/25.1%; Ohlson 10.8%/26.6%) — second-hand via an Agarwal & Taffler footnote, found nowhere else. **Once-only.**
11. **Beneish, Lee & Nichols (2013) versus its published critique** — both paywalled, dispute unresolved. **Do not ship an M-score return factor without reading both.**
12. **All Greensill content** — only the report's identity (HC 723, 24 September 2021) is confirmed; the source sits behind a Cloudflare challenge.
13. **All Enron SPE specifics**, including the widely repeated "3% outside equity" test and Chewco/JEDI mechanics, and the US-GAAP lease bright lines (~75% useful life / 90% fair value). Primary sources were blocked or were scans without text layers.
14. **XBRL/iXBRL element-name strings — now partially RESOLVED, and the resolution is a warning.** The **Altman input tags were verified against the live EDGAR `companyconcept` API** (see §3a): `AssetsCurrent` and `LiabilitiesCurrent` return 404 for Deere, `RevenueFromContractWithCustomerExcludingAssessedTax` returns 404 for both Caterpillar and Deere, and `us-gaap:Ebit` does not exist at all. Tag names for the **other** markers in this report were assembled from source documents and prior knowledge and are **not yet verified** — `xbrl.fasb.org` returns HTTP 403 (Cloudflare) and `data.sec.gov` refuses plain automated fetches ("Undeclared Automated Tool"). **Validate each remaining tag against a live taxonomy before shipping.**
15. **No measurable Z-score impact from IFRS 16** — the one on-topic paper that could be located was unreachable (DOAJ HTTP 403, journal host timed out), and the IFRS 16 literature measures leverage, assets and liabilities rather than Z. **No numeric Z-impact claim is made anywhere in this report.**
16. **FASB primary sources** — `fasb.org` and `xbrl.fasb.org` return HTTP 403 to every request.
17. **No source quantifying ASC 606's effect on revenue *levels* or on X5** — only tag churn (verified, §3a) and taxonomy-definition evidence.
18. **No source quantifying IFRS 16's effect on Altman Z-scores specifically** — see item 15.
19. **The Ohlson input tags were never probed** against the live API, so Ohlson's coverage is unknown — unlike Altman's, which is now measured.
20. **No official UK rate of abridged or micro-entity filings** — so the share of UK filers for whom X3/X5 are legally absent (§3b) is characterised qualitatively, not quantified.
21. **Whether the 2023 IAS 7 / IFRS 7 supplier-finance amendments create dedicated taxonomy elements** or only narrative text blocks.
22. **A market-wide estimate of how much supply-chain finance flatters OCF or DSO**, and the frequency of the receivables-factoring distortion. Mechanism verified; magnitude not.
23. **Any validated screen for SPV / unconsolidated structured-entity exposure.**
24. **Richardson, Sloan, Soliman & Tuna (2005)'s coefficients** (the RSST accrual decomposition) and **Hirshleifer et al.'s NOA magnitude** — direction and sample confirmed, numbers not.
25. **Hillegeist et al. (2004)'s own BSM-Prob specification** is not reproduced here — only its relative performance (pseudo-R² 0.12 vs 0.07 for Z). The market-based model is **not implementable from annual XBRL data anyway**, since it requires equity volatility and debt structure, which is precisely the point of the comparison.

**Note on the RSST accrual specification**, since it is often confused with Sloan's: Sloan (1996) uses the **balance-sheet** form `Oa = (ΔCA − ΔCash) − (ΔCL − ΔSTDebt − ΔTaxPayable) − Depreciation`. Richardson et al. (2005) use a **broader, three-part** form `Ta = ΔWc + ΔNco + ΔFin`, where `Coa = CA − Cash`, `Col = CL − DebtInCurrentLiabilities`, `Nca = TotalAssets − CA − InvestmentsAndAdvances`, `Ncl = TotalLiabilities − CL − LongTermDebt`, `Fna = ShortTermInvestments + LongTermInvestments`, `Fnl = LongTermDebt + DebtInCurrentLiabilities + PreferredStock`. **The two are not interchangeable** — the RSST version captures long-term operating accruals that Sloan's omits, and that is why it is the specification used in the Dechow F-score.

**Suggested follow-ups, in priority order:** (a) obtain Ohlson (1980) and Altman et al. (2017) via library/ILL — the two coefficient sets that currently rest on secondary transcription; (b) obtain Richardson, Sloan, Soliman & Tuna (2005) and Thomas & Zhang (2002), both load-bearing and unverified; (c) read Beneish, Lee & Nichols (2013) *and* the published response before shipping any M-score feature; (d) pin exact IFRS/UK iXBRL element names from real filed instance documents rather than from memory; (e) backtest the decay claims on your own universe rather than trusting in-sample magnitudes, since that is where McLean & Pontiff and Hou, Xue & Zhang both say the effect lives or dies; (f) if you want the strongest single upgrade to the non-GAAP work, get Doyle, Lundholm & Soliman (2003) in full.

**Companion files.** Three detailed sub-reports sit alongside this one in the same directory: `earnings-quality-markers.md` (accruals, DSO, inventory, EQI), `accounting-red-flags-source-grounded.md` (goodwill, non-GAAP, auditor/restatement/NT/going-concern, plus the XBRL-vs-not architecture), and `accounting_markers_research.md` (leases, supply-chain finance, SPVs, Piotroski international replications).

