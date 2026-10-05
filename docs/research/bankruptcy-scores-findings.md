# Bankruptcy-Prediction Accounting Scores — Source-Grounded Findings

**Status:** consolidated final. Every figure below was read from the source cited. Sources I could not open, and places where sources conflict, are flagged. Nothing is invented, rounded, or embellished beyond the source's own precision.

**Evidence tiers:** **[PRIMARY]** = the model author's own paper/workpaper read in full · **[PEER]** = peer-reviewed journal (full text) · **[PEER-abs]** = peer-reviewed, abstract/metadata verified only · **[THESIS]** = MSc/PhD thesis · **[REF]** = encyclopedia/secondary.

**Three corrections made during this research (carried forward honestly):**
1. **Wikipedia's Altman page misstates the original accuracy result** (see §1d).
2. **The DOI `10.1016/0882-6110(03)20004-3` is Grice & Dugan (2003), *not* Zmijewski (1984)** — an earlier draft of this report mis-attributed it. Zmijewski's own DOI remains **UNVERIFIED**.
3. **Hillegeist et al. (2004) benchmark against BSM-Prob (Black–Scholes–Merton), not a "Bharath-Riski" model.** Bharath & Shumway (2008) is a separate, later paper; "Riski" is not an author on either.

---

## 1. Altman Z-score (1968)

### (a) Exact original formula and inputs [PRIMARY]

`Z = 0.012X1 + 0.014X2 + 0.033X3 + 0.006X4 + 0.999X5`

| Ratio | Altman's exact definition |
|---|---|
| X1 | working capital / total assets |
| X2 | retained earnings / total assets |
| X3 | earnings before interest and taxes / total assets |
| X4 | market value equity / book value of total liabilities |
| X5 | sales / total assets |

Altman's own "A Clarification": *"Due to the original computer format arrangement, variables X1 through X4 must be calculated as absolute [percentages]… X1 should be included as 10.0% and not 0.10. Only variable X5 [is] expressed in a different manner: that is, a S/TA ratio of 200% should be included as 2.0."*

Convenient rescaled form (also given by Altman): `Z = 1.2X1 + 1.4X2 + 3.3X3 + 0.6X4 + 1.0X5` — *"The scores for individual firms and related group classification and cutoff scores remain identical."*

Zones: >2.99 safe; 1.81–2.99 grey / "zone of ignorance"; <1.81 distress. Altman's own preference: *"I advocate using the lower bound of the zone-of-ignorance"* (1.81) rather than 2.675, *"The latter resulted in the lowest overall error in the original tests."*

**Source:** Altman, *Predicting Financial Distress of Companies: Revisiting the Z-Score and ZETA Models*, July 2000, NYU Stern working paper. The live URL `pages.stern.nyu.edu/~ealtman/Zscores.pdf` returns **HTTP 500**; recovered from the [Wayback Machine](http://web.archive.org/web/20240717121208if_/https://pages.stern.nyu.edu/~ealtman/Zscores.pdf) (134,818 bytes). **[PRIMARY]** Zones also on [Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score) **[REF]**.

### (b) Origin

Altman (1968), *Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy*, Journal of Finance 23(4), 589–609, DOI [10.1111/j.1540-6261.1968.tb00843.x](https://doi.org/10.1111/j.1540-6261.1968.tb00843.x). **Closed access** ([OpenAlex](https://api.openalex.org/works/doi:10.1111/j.1540-6261.1968.tb00843.x): `is_oa:false`, `oa_status:"closed"`). The 1968 paper itself was **not opened**; all 1968 attributions below come from Altman's own 2000 paper, which reproduces the tables verbatim.

### (c) Original sample [PRIMARY]

- *"66 corporations with 33 firms in each of the two groups"* — 33 bankrupt + 33 non-bankrupt. **Matched pairs: yes.**
- Bankrupt group: **manufacturers** filing *"petition under Chapter X of the National Bankruptcy Act from **1946 through 1965**."*
- Controls *"stratified by **industry and by size**, with the asset size range restricted to between **$1 and $25 [million]**"*; Group 2 mean assets **$9.6m**.
- Data from *"financial statements dated one annual reporting period prior to bankruptcy"*; average lead time ≈ 7.5 months.
- 22 candidate variables across liquidity, profitability, leverage, solvency, activity → reduced to 5.

⚠️ Wikipedia says only *"small firms with assets of < $1 million were eliminated"* — it **omits the $25M upper bound** Altman's own text gives.

### (d) Altman's own reported accuracy [PRIMARY]

**Original sample (Table 2):**

| | Correct | % correct | % error | n |
|---|---|---|---|---|
| Type I (bankrupts) | 31 | **94%** | **6%** | 33 |
| Type II (non-bankrupts) | 32 | **97%** | **3%** | 33 |
| Total | 63 | **95%** | **5%** | 66 |

*"The model is extremely accurate in classifying 95% of the total sample correctly. The Type I error proved to be only 6% while the Type II error was even lower at 3%. The results, therefore, are encouraging, but the obvious upward bias should be kept in mind."*

Two statements prior (Table 3): Type I **72% correct / 28% error**; Type II **94% / 6%**; total **83% / 17%**.

⚠️ **Wikipedia's Altman page is wrong here.** It claims the initial test was *"72% accurate in predicting bankruptcy two years before the event, with a Type II error (false negatives) of 6%"*. Per Altman's own tables: 72% is the one-year Type I **accuracy** in the **two-year** test, and 6% is the Type I **error** in the **one-year** test. Wikipedia conflates the horizons and mislabels the error type.

⚠️ Group means: Altman 2000 gives **Group 1 = −0.29**, **Group 2 = +5.02**. Wikipedia gives −0.25 / +4.48. **Unresolved.**

**Table 5, "Classification & Prediction Accuracy, Z-Score (1968) Failure Model"** — Type I accuracy by sample, at the 2.67 cutoff (1.81 in parentheses):

| Years prior | Original (33) | Holdout (25) | 1969–75 (86) | 1976–95 (110) | 1997–99 (120) |
|---|---|---|---|---|---|
| **1** | 94% (88%) | 96% (92%) | 82% (75%) | 85% (78%) | **94% (84%)** |
| **2** | 72% | 80% | 68% | 75% | 74% |
| **3** | 48% | | | | |
| **4** | 29% | | | | |
| **5** | 36% | | | | |

*"the Type I accuracy using a cutoff score of 2.67 ranged from 82–94%"*; for 1997–99 *"the default prediction accuracy rate was 94% (113 out of 120)."*

**Altman's own admission of drift, verbatim [PRIMARY]:** *"We can, therefore, conclude that the Z-Score model has retained its reported high accuracy and is still robust despite its development over 30 years ago. In the last decade, however, the Type II accuracy, has increased to about **15–20%** of those manufacturing firms listed on Compustat."* (Altman writes "Type II accuracy" where the surrounding context indicates the Type II *error rate*; Wikipedia renders it as "Type II error … of approximately 15–20%". Quoted verbatim above, with the ambiguity noted.)

### Z', Z'' and Z''-EM — verified from Altman's own 2000 paper [PRIMARY]

**Z′ (private firms — book value of equity substituted in X4):**
> `Z' = 0.717(X1) + 0.847(X2) + 3.107(X3) + 0.420(X4) + 0.998(X5)`

**Z'' (private / non-manufacturing — X5 dropped):**
> `Z" = 6.56 (X1) + 3.26 (X2) + 6.72 (X3) + 1.05 (X4)`

**Z''-EM:** `Z"-EM = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4`

X1 = (current assets − current liabilities)/total assets; X2 = RE/TA; X3 = EBIT/TA; **X4 = book value of equity / total liabilities**; **X5 dropped in Z''.** Zones: **>2.6 safe · 1.1–2.6 grey · <1.1 distress** ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score) **[REF]**).

⚠️ **Z′ cutoff inconsistency inside Altman's own paper:** the body text says *"the lower boundary is now 1.23 as opposed to 1.81"*, while the Table 6 note says *"Z'<1.21 = Zone I"*. Flagged, not resolved.

**The EM constant, in Altman's own words [PRIMARY]:** *"In the emerging market model, we added a constant term of **+3.25** so as to standardize the scores with a score of zero (0) equated to a **D (default) rated bond**."* Origin: *"Altman, Hartzell, and Peck (1995) have modified the original Altman Z-Score model to create the emerging market scoring (EMS) model"* — Salomon Brothers, *Emerging Markets Corporate Bonds: A Scoring System*.

**Why the coefficients differ — Altman's own statement [PRIMARY]:** *"I advocate a **complete reestimation** of the model, substituting the book values of equity for the Market Value in X4. One expects that **all of the coefficients will change (not only the new variable's parameter)** and that the classification criterion and related cutoff scores would also change. That is exactly what happens."* For Z'': *"All of the coefficients for variables X1 to X4 are changed as are the group means and cutoff scores."* So the change is a genuine re-estimation on a different population, not merely the ×100 rescaling of the original.

**Directly relevant to the lease caveat [PRIMARY]:** Altman states Z'' *"is also useful within an industry where the type of financing of assets differs greatly among firms and important adjustments, **like lease capitalization, are not made**."* — i.e. he explicitly recommends Z'' for exactly the pre-IFRS 16 situation (§6.3).

**Z′ classification (Table 6) [PRIMARY]:** bankrupt 30/33 = **90.9%**; non-bankrupt 32/33 = **97.0%**; group means 0.15 / 4.14. *"Type I accuracy is only slightly less impressive than the model utilizing market value of equity (91% vs. 94%) but the Type II accuracy is identical (97%)."*

**EM bond-rating calibration [PRIMARY]:** AAA 8.15 … CCC− 1.75, D 0 (*"In-depth Data Corp. Average based on over 750 U.S. Corporates with rated debt outstanding: 1994 data"*).

**ZETA benchmark [PRIMARY]:** ZETA sample = manufacturers *and retailers*, average asset size two periods prior ≈ **$100 million**, **no firm under $20 million**. Year 1: ZETA 96.2% vs Z-Score 93.9%. *"by the fifth year, the ZETA model is still about 70% accurate but the Z-Score's accuracy falls to 36%."*

### (e) Out-of-sample and post-publication evidence — see §7 for the full literature review

**Headline:** the durable, replicated finding is that **Z's coefficients are unstable out-of-sample, its useful horizon is about two years, and on broad modern populations it misclassifies heavily in both directions.** Altman's own tests show 82–94% one year prior; independent work on *populations* (rather than matched pairs) is far less flattering.

### (f) Practical caveats

- **Not for financials:** *"Neither the Altman models nor other balance sheet-based models are recommended for use with financial companies. This is because of the opacity of financial companies' balance sheets and their frequent use of off-balance sheet items."* ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score))
- **X5 varies widely by industry** — Altman explicitly drops it in Z'' *"in order to minimize the potential industry effect."*
- **Size:** original sample restricted to $1–25M assets; ZETA deliberately moved up-market (~$100m average, nothing under $20m) *"because the average size of bankrupt firms had increased dramatically."*
- **RE manipulation:** retained earnings *"is subject to 'manipulation' via corporate quasi-reorganizations and stock dividend declarations."*
- **Young firms structurally penalised** via X2 (low accumulated RE).
- **Cutoff choice changes the answer materially** (1.81 vs 2.675 vs 2.99).
- **Accounting-standard changes:** see §6.3.

### (g) Computability from SEC EDGAR XBRL / UK Companies House iXBRL

**See §6.** Workable for most US filers but not plug-and-play; **structurally undefined for UK small/micro filers.**

---

## 2. Ohlson O-score (1980)

### (a) Exact formula

Verbatim from the LaTeX source of the Wikipedia article (which cites the original paper) **[REF]**:

```
O = −1.32 − 0.407·log(TA_t / GNP)
        + 6.03·(TL_t / TA_t) − 1.43·(WC_t / TA_t) + 0.0757·(CL_t / CA_t)
        − 1.72·X − 2.37·(NI_t / TA_t) − 1.83·(FFO_t / TL_t)
        + 0.285·Y − 0.521·(NI_t − NI_{t−1}) / (|NI_t| + |NI_{t−1}|)
```

TA = total assets; GNP = GNP price-level index (USD, 1968 = 100); TL = total liabilities; WC = working capital; CL = current liabilities; CA = current assets; **X = OENEG** = 1 if TL > TA else 0; NI = net income; FFO = funds from operations; **Y = INTWO** = 1 if net loss for the last two years else 0. Probability: `P = exp(O) / (1 + exp(O))`. [(Wikipedia raw wikitext)](https://en.wikipedia.org/w/index.php?title=Ohlson_O-score&action=raw) · [(Wikipedia)](https://en.wikipedia.org/wiki/Ohlson_O-score)

**⚠️ SOURCE CONFLICT.** A QUB working paper gives `−1.32 − 0.407·log(assets) + **0.603**·(TL/assets) − 1.43·(WC/assets) + 0.0757·(**current assets/current liabilities**) − 2.37·(NI/assets) − 1.83·(FFO/TL) + 0.285·dummy − 1.72·dummy − 0.521·ΔNI` — [PDF](https://pureadmin.qub.ac.uk/ws/portalfiles/portal/586396214/TalkWalk.pdf). Two other sources give **6.03** (not 0.603) and **CL/CA** (not CA/CL): the Wikipedia LaTeX above, and Bouwmeester's list *"x4 = Current liabilities/Current assets"* ([PDF](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)). **Assessment: 6.03 with CL/CA is correct; QUB appears to be a transcription error — but the original paper was unreadable, so this is not settled.**

### (b) Origin

James A. Ohlson (1980), *Financial Ratios and the Probabilistic Prediction of Bankruptcy*, **Journal of Accounting Research 18(1), 109–131 (Spring 1980)** — volume/pages confirmed from the JSTOR cover page in the archived scan. <https://www.jstor.org/stable/2490395>, DOI [10.2307/2490395](https://doi.org/10.2307/2490395) ([OpenAlex](https://api.openalex.org/works/doi:10.2307/2490395)).

⚠️ The only free copy ([Wayback/Ryerson](https://web.archive.org/web/20210805133803if_/https://math.ryerson.ca/ramlab/projects/crd/ohlson1980.pdf)) is a **JSTOR scan with no OCR text layer** — 23 CCITTFax images; a text layer exists only on the cover page. **The body could not be read.**

### (c) Sample [THESIS]

*"the sample consisted of **105 bankrupt firms and 2,058 non-bankrupt firms** in the period from **1970 to 1976**. The sample excludes small or privately held firms, because the firms in the sample had to be traded on some stock exchange or over-the-counter market. The firms also must be classified as an industrial… Ohlson obtained three years of data prior to the date of bankruptcy and developed three logit models. Model 1 predicts bankruptcy within one year, model 2 within two years given that the company did not fail within the subsequent year, and model 3 within one or two years."* — [PDF](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)

### (d) Reported accuracy — **read the caveat**

- [THESIS, Twente] *"The optimal cut-off point which minimizes the sum of errors is **0.038**"*; *"Using this cut-off point, **82.6% of the non-bankrupt firms and 87.6% of the bankrupt firms** were correctly classified."*; *"The overall accuracy rate of the estimation-sample was **96%** and for the hold-out sample **85%** (Ohlson, 1980)."*
- [THESIS, UVT/Tilburg] *"The percentage of correctly predicted observations of the first model is **96.12%**, but this number should be interpreted with caution… even when the model predicts bankruptcy in all cases, the percentage correctly classified is 2058/(2058+105) = **95.15%**."*; optimal cutoff minimising Type I+Type II = **0.038**; *"…[87.6% of bankrupt] firms and **82.6% of the non-bankrupt firms** correctly at t−1."* — [PDF](http://arno.uvt.nl/show.cgi?fid=135794)

**⚠️ These are mutually inconsistent.** 87.6%×105 + 82.6%×2,058 = 1,792 correct = **82.8%**, not 96.12%; conversely 96.12% implies ~84 total misclassifications. Both cannot hold at the same cutoff on the same sample. **All three are reported as-is, unmatched to a verified cutoff.** The likely resolution (different cutoffs) is **UNVERIFIED**. No source I opened gives clean Type I / Type II error rates from the original paper.

### (e) Out-of-sample / after publication

- [THESIS, Twente] Ohlson variables on Dutch/Belgian firms: in-sample 95.01% overall but only **47.89% of bankrupts**; **out-of-sample AUC 0.696 (MDA) / 0.738 (logit) / 0.717 (probit)**. Re-estimating with logit instead of MDA did **not** significantly improve AUC.
- **[PEER]** Hillegeist et al. (2004): Ohlson's O-Score is the *best* of the accounting-based models they test (pseudo-R² 0.10 for O-Score_u vs 0.07 for Z-Score), but is still dominated by BSM-Prob — see §7.4.
- **[PEER-abs]** Begley, Ming & Watts (1996): *"we find that **Ohlson's original model displays the strongest overall performance**"* among the models tested on 1980s data (§7.1).
- ⚠️ **Wikipedia's claim that the O-score is "significantly more accurate" than Z is an unsourced assertion** on a page flagged "needs more citations". **Treat the superiority claim as unsupported** — the independent evidence is more nuanced: Hillegeist et al. and Begley et al. both favour O-score *relative to Z*, but Hillegeist et al. find both are beaten by a market-based model.

### (f)/(g) Caveats and computability

- **GNP price-level index (1968 = 100)** must be sourced historically — awkward today, classic implementation error.
- **Class imbalance dominates headline accuracy** — require Type I and Type II separately.
- **0.038 optimal cutoff vs. the 0.5 rule of thumb** behave very differently.
- **FFO is not a standard modern XBRL/IFRS line item.**
- Ohlson deliberately excluded small and private firms.
- XBRL/iXBRL: **§6 covers Altman Z inputs only**; the O-score-specific input set (GNP index, FFO) was **not researched — UNVERIFIED**.

---

## 3. Zmijewski (1984) probit

### (a)/(b) Formula and origin

Zmijewski, *Methodological Issues Related to the Estimation of Financial Distress Prediction Models*, **Journal of Accounting Research 22 (Supplement), 59–82** (1984). ⚠️ **DOI UNVERIFIED** — an earlier draft of this report mis-attributed `10.1016/0882-6110(03)20004-3` to this paper; that DOI is in fact **[Grice & Dugan (2003), *Advances in Accounting* 20, 77–93](https://doi.org/10.1016/S0882-6110(03)20004-3)** (see §7.2).

Formula as reproduced in Gerritsen (Twente MSc thesis) — [PDF](http://essay.utwente.nl/68211/1/Gerritsen%20P.L._MA%20BA_Behavioural%2C%20Management%20and%20Social%20sciences%20%28BMS%29.pdf) **[THESIS]**:
```
Zmijewski = −4.3 − 4.5·X1 + 5.7·X2 + 0.004·X3
X1 = Net income / Total assets
X2 = Total liabilities / Total assets
X3 = Current assets / Current liabilities
```
Probit ⇒ probability = Φ(index). The thesis says only that *"the outcome of this probit model lies between 0 and 1"*; the exact transform is **UNVERIFIED**. **Commonly cited precise coefficients (−4.336, −4.513, 5.679, 0.004): UNVERIFIED** (search snippet only).

### (c) Sample [THESIS]

*"The estimation sample of Zmijewski's study contained **40 bankrupt and 800 non-bankrupt firms**, and the **hold-out sample consisted of 41 bankrupt and 800 non-bankrupt firms**. The population of his study consists of all firms listed on the American and New York Stock Exchanges between **1972 and 1978** with SIC-codes below 6000. This means that finance, service and public administration firms were excluded from the research."*

### (d) Reported accuracy

- [THESIS] *"The accuracy rate of the Zmijewski (1984) model for the estimation sample was **99%**, while the accuracy rate of the hold-out sample was **not reported**."*
- [THESIS, Bouwmeester] Dutch/Belgian firms: in-sample 94.37% overall but only **38.03% of bankrupts** (100.00% of non-bankrupts); **out-of-sample AUC 0.683 / 0.697 / 0.690 (MDA/logit/probit)**.

### (e) Post-publication — **contested**

- *"Shumway (2001, p. 120) argues that Zmijewski's model is in fact only a **one-variable model** because the selected variables are highly correlated to each other. Shumway (2001) even claims that because of this correlation the model has **no strong predictive power** for bankruptcy."*
- *"Platt and Platt (2002, p. 186) state that Zmijewski (1984) could not test the individual estimated coefficients for bias against the population parameter since Zmijewski ran only one regression for each sample size."*
- **[PEER-abs]** Grice & Dugan (2003): *"researchers who use the Zmijewski and Ohlson models using recent data should **re-estimate** the models' coefficients to improve the predictive accuracy of the models."*

The 99% is **in-sample with 20:1 imbalance** (naive all-negative = 800/840 = **95.2%**), so it is not comparable to an out-of-sample AUC of ~0.69.

### (f)/(g)

Same structural caveats. §6 covers Altman Z inputs only; Zmijewski's tag set is a subset of Altman's, but was **not independently researched — UNVERIFIED**.

---

## 4. Robust / not robust

| Claim | Status |
|---|---|
| Altman 1968 formula `0.012X1+0.014X2+0.033X3+0.006X4+0.999X5`; 66 firms (33/33); 1946–65 US manufacturers; $1–25M assets; matched industry+size | **Robust — Altman's own text [PRIMARY]** |
| Altman original: Type I 6% error, Type II 3% error, 95% overall | **Robust — Altman's own Table 2 [PRIMARY]** |
| Altman later: 82–94% one year prior; collapses after 2 years | **Robust — Altman's own Tables 5/9 [PRIMARY]** |
| Wikipedia's "72% / Type II 6%" account of the original test | **Contested/wrong — contradicts Altman's own tables** |
| Z′ = 0.717/0.847/3.107/0.420/0.998; Z'' = 6.56/3.26/6.72/1.05; Z''-EM adds +3.25 (score 0 = D-rated) | **Robust — Altman's own 2000 paper [PRIMARY]** |
| Ohlson 9 coefficients (−1.32, −0.407, 6.03, −1.43, 0.0757, −1.72, −2.37, −1.83, 0.285, −0.521) | **Verified via Wikipedia LaTeX + corroborated in two theses; original unreadable; QUB conflicts on 6.03 and CL/CA** |
| Ohlson sample 105/2,058, 1970–76 exchange-traded industrials | **Replicated across two theses** |
| Ohlson reported error rates | **CONTESTED — three mutually inconsistent figures; unresolved** |
| Zmijewski formula/sample/99% | **Single MSc thesis; not independently corroborated** |
| Zmijewski effectively one-variable | **Published critique quoted via a thesis; Shumway full text not opened** |
| Headline accuracy inflated by ~20:1 class imbalance | **Robust — arithmetic shown explicitly in two independent theses** |
| US Z-inputs obtainable from EDGAR XBRL with fallback chains | **Verified by live SEC API probes (§6.1)** |
| UK small/micro Z-score is structurally undefined | **Verified from Companies Act 2006 s.444(5)(a) + GOV.UK (§6.2)** |
| Altman's 1968 coefficients are unstable out-of-sample; re-estimation changes them materially | **ROBUST — multiply replicated (§7)** |
| On broad modern populations Z misclassifies heavily both ways | **ROBUST (§7.6)** |
| Z's useful horizon is ~2 years | **ROBUST — Altman's own tables + independent work (§7)** |
| Market-based models dominate accounting-based models | **CONTESTED — Hillegeist et al. yes; Agarwal & Taffler (2008) find "little difference" in the UK (§7.4, §7.5)** |
| Re-estimating coefficients improves accuracy | **CONTESTED — Begley and Hillegeist find ORIGINAL coefficients outperform updated ones; Grice & Dugan argue for re-estimation** |

---

## 5. Confidence and gaps

**Could not verify (explicit):**
1. **Altman (1968) journal paper — not opened** (closed access). All 1968 attributions come from Altman's own 2000 paper. Group-mean discrepancy (−0.29/+5.02 vs −0.25/+4.48) unresolved.
2. **Ohlson (1980) paper — not readable** (scanned image PDF, no OCR text layer). Ohlson's **actual Type I/Type II error rates and the cutoff at which they were measured are UNVERIFIED**; the **CLCA direction and the 6.03 coefficient** rest on secondary transcription with one source disagreeing.
3. **Zmijewski (1984) — nothing beyond one MSc thesis.** Original paper not opened; precise coefficients and DOI unverified.
4. **Altman et al. (2017) JIFMA 28(2), 131–171** — closed access, Wiley Cloudflare-blocked, no OA mirror. Only abstract-level verification obtained (§7.7). *(Z''-EM itself was ultimately verified from Altman's own 2000 paper instead — see §1.)*
5. **Begley et al. (1996) full tables** — only second-hand via an Agarwal & Taffler footnote (§7.1). **No numbers from Grice & Ingram (2001) or Grice & Dugan (2003). No Shumway (2001) own accuracy figures. No Agarwal & Taffler (2008) specific AUCs.**
6. **Ohlson O-score inputs from XBRL/iXBRL — not researched.** The GNP price-level index and FFO remain UNVERIFIED for computability.
7. **IFRS 16 / ASC 842 effect on Z-scores specifically — UNVERIFIED.** Magnitudes for leverage/assets are sourced; no Z-score-specific number exists in the opened literature.
8. **No size-stratified or tech-sector Z-accuracy study could be opened.**
9. **Tooling limitation:** `web_fetch` cannot parse PDFs. PDFs were downloaded and text-extracted directly (Node + custom LZW/Flate/ASCII85 decoders). Subset-font PDFs yield scrambled or dropped text; scanned PDFs with no text layer (Ohlson 1980) are unreadable; where extracted numbers looked implausible (`0.603`), the conflict was flagged rather than silently corrected. **`pages.stern.nyu.edu` returns HTTP 500 and SEC.gov returns HTTP 403 to the plain fetcher** — both need Wayback mirrors or Node `fetch` with a browser User-Agent.

---

## 6. Practical computation from filings, and lease-accounting effects

*(Load-bearing claims independently re-probed by me — see §6.5.)*

### 6.1 SEC EDGAR / US-GAAP XBRL

Endpoints documented on the [EDGAR Application Programming Interfaces page](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). `data.sec.gov/api/xbrl/companyconcept/`, `.../companyfacts/`, `.../frames/` return XBRL facts; no API key. The APIs aggregate only facts that (i) *"Use a non-custom taxonomy (e.g. us-gaap, ifrs-full, dei, or srt)"* and (ii) *"Apply to the entire filing entity."*

**Verified tag map** (each element name confirmed via the SEC `companyconcept` API):

| Z input | Tag(s) | Caterpillar (CIK 0000018230) | Deere (CIK 0000315189) |
|---|---|---|---|
| Working capital | `us-gaap:AssetsCurrent`, `us-gaap:LiabilitiesCurrent` | 200 / 200 | **404 / 404** |
| Retained earnings | `us-gaap:RetainedEarningsAccumulatedDeficit` | 200 | 200 |
| EBIT | *no US-GAAP tag* | `us-gaap:OperatingIncomeLoss` 200; **`us-gaap:Ebit` 404** | `us-gaap:OperatingIncomeLoss` 200 |
| Market value of equity | `dei:EntityCommonStockSharesOutstanding` × external price | 200 | 200 |
| Total liabilities | `us-gaap:Liabilities` | 200 | 200 |
| Sales | `us-gaap:Revenues` | 200 | 200 |
| Total assets | `us-gaap:Assets` | 200 | 200 |
| (equity) | `us-gaap:StockholdersEquity` | **404** | 200 |
| (equity alt.) | `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` | 200 | — |
| (revenue post-ASC 606) | `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` | **404** | **404** |
| (revenue legacy) | `us-gaap:SalesRevenueNet` | 200, label **"Revenue, Net (Deprecated 2018-01-31)"** | 200, same label |

Probes: [AssetsCurrent](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/AssetsCurrent.json) · [RetainedEarningsAccumulatedDeficit](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/RetainedEarningsAccumulatedDeficit.json) · [dei:EntityCommonStockSharesOutstanding](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/dei/EntityCommonStockSharesOutstanding.json) · [SalesRevenueNet](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/SalesRevenueNet.json)

**A naive "one tag fits all" extractor fails immediately:** `us-gaap:StockholdersEquity` 404s for Caterpillar; `RevenueFromContractWithCustomerExcludingAssessedTax` — the tag most often recommended post-ASC 606 — 404s for **both** Caterpillar and Deere, which use `us-gaap:Revenues`.

**(a) Unclassified balance sheets.** Reg S-X Art. 5 § 210.5-02 does **not** mandate a current/non-current split: the caption list reads *"Current Assets, when appropriate"*, *"Total current assets, when appropriate"*, *"Total current liabilities, when appropriate"* ([17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/chapter-II/part-210/subject-group-ECFR6a2b6c0d0b4e4b7/section-210.5-02)). Verified: **Berkshire Hathaway** (CIK 0001067983) `AssetsCurrent` 404; **Deere** — a US public *manufacturer* — `AssetsCurrent`/`LiabilitiesCurrent` 404, and its [most recent 10-K](https://www.sec.gov/Archives/edgar/data/315189/000110465925122321/de-20251102x10k.htm) contains the strings "Current assets", "Total current assets", "Current liabilities", "Total current liabilities" **zero times**. `frames` for CY2024Q4I: `Assets` **6,271** vs `AssetsCurrent` **4,963** vs `LiabilitiesCurrent` **4,962** → **~21% of entities reporting total assets report no current-asset split**. Caveat: a reproducible point-in-time measure, **not an SEC statistic**; the population includes banks/insurers/funds where unclassified presentation is normal. **Consequence: X1 is not computable for those filers; treating missing `AssetsCurrent` as zero silently biases X1 downward.**

**(b) Revenue tag churn.**

| Frame | `SalesRevenueNet` | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` |
|---|---|---|---|
| CY2016 | 1,915 | 3,630 | 1,412 |
| CY2024 | **404 — tag absent** | 2,505 | 2,970 |

In CY2024 **no single revenue tag covers even half** the 6,271-entity asset universe, and the majority tag flipped between 2016 and 2024. X5 needs an explicit tag-precedence fallback chain.

**(c) Dimensions.** The common claim that segment facts contaminate `companyfacts` is **wrong for the modern APIs** (the SEC filters to entity-wide facts). Contamination risk is in **raw/bulk** data: the SEC's [Financial Statement Data Sets](https://www.sec.gov/dera/data/financial-statement-data-sets) page notes that December 2024 reprocessed sets *"used rendering data to determine which data points were presented on the primary financial statements… apart from the NUM file where a new field 'segments' has been added"*, whereas previously they held only *"non-dimensional"* data.

**(d) Market value of equity.** No US-GAAP element carries a share price. [17 CFR § 232.406](https://www.ecfr.gov/current/title-17/chapter-II/part-232/section-232.406) requires filers to iXBRL-tag *"all of the information … required on the cover page"*; `dei:EntityCommonStockSharesOutstanding` is `periodType="instant"` in the [SEC DEI taxonomy](https://xbrl.sec.gov/dei/2025/dei-2025.xsd). **Trap: the as-of date ≠ balance-sheet date.** Apple's FY2025 10-K cover date is `2025-10-17` vs balance-sheet date `2025-09-27`. Assemble X4 as (shares on *their own* `end` date) × (closing price that same date).

**(e) EBIT is not a tag.** `us-gaap:Ebit` 404s. `OperatingIncomeLoss` is the usual proxy but is **optional and not filed every year** (Deere's latest annual fact is FY2024). Caterpillar has **no `us-gaap:InterestExpense*` fact at all** (all 404s), so the pre-tax-plus-interest alternative also breaks. Mixing EBIT definitions across a panel moves X3 by accounting-policy choice, not credit quality.

### 6.2 UK Companies House iXBRL

**No structured financial-statement API exists.** The [Public Data API reference](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference) enumerates **34 operations, none for accounts**; filing history returns only metadata. The [Document API](https://developer-specs.company-information.service.gov.uk/document-api/reference/document-metadata) returns metadata plus downloads. Financial content is only in the [Free Accounts Data Product](http://download.companieshouse.gov.uk/en_accountsdata.html) — iXBRL/XML instances — covering *"about **75% of the 2.2 million accounts we expect to be filed each year**."*

**The blocker is statutory.** [Companies Act 2006 s.444(5)(a)](https://www.legislation.gov.uk/ukpga/2006/46/section/444): small-company directors *"do not deliver to the registrar a copy of the company's profit and loss account"*; micro-entities carved into [s.443A](https://www.legislation.gov.uk/ukpga/2006/46/section/443A); [GOV.UK](https://www.gov.uk/annual-accounts/microentities-small-and-dormant-companies) confirms a micro-entity may *"send only your balance sheet."*

→ **X3 (EBIT/TA) and X5 (Sales/TA) are legally absent for UK small/micro filers.** X2 survives only if retained earnings is tagged on the filed balance sheet; **X1 and X4 are the only reliably recoverable inputs.** Any tool reporting a UK Z-score for such a company is imputing data or silently substituting a different model.

Taxonomy: FRC Taxonomy Suite (common "core" schema + IFRS/FRS 101/FRS 102 entry points; [FRC Taxonomies](https://xbrl.frc.org.uk/), [FRC XBRL Tagging Guide](https://www.frc.org.uk/docs/8912/html/)). The guide warns companies *"may apply varying definitions to what is contained within sections such as operating income, non-operating income and **revenue**"*, so *"the summation implied in a taxonomy will not match that used in some specific accounts."* HMRC publishes [Corporation Tax technical specifications in XBRL and iXBRL](https://www.gov.uk/government/publications/corporation-tax-technical-specifications-xbrl-and-ixbrl).

### 6.3 Lease accounting (IFRS 16 / ASC 842)

[IFRS 16](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/) requires recognition of a right-of-use asset and a lease liability; effective for periods beginning on or after 1 January 2019.

| Z input | Direction | Mechanism |
|---|---|---|
| Total assets | ↑ | ROU asset added |
| Total liabilities | ↑ | Lease liability added |
| Current liabilities | ↑ | Current portion of lease liability |
| Working capital | ↓ (usually) | CL addition exceeds any CA effect |
| EBIT | ↑ | Rent removed from operating expense; replaced by D&A/interest below the EBIT line |
| **X4 = MVE/TL** | **↓** | Denominator rises, numerator unchanged |

**Magnitudes ([IASB, *IFRS 16 Leases — Effects Analysis*](https://www.ifrs.org/content/dam/ifrs/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf)):** long-term liabilities understated by **North America 22%, Europe 26%, Asia/Pacific 32%, Latin America 45%, Africa/Middle East 27%**. Distressed retailers' discounted off-BS lease PV as a multiple of *reported* long-term debt: **Circuit City 65.86×** ($3,293M vs $50M), **Woolworths 10.90×**, **Clinton Cards 9.05×**, **HMV 7.03×**, **Borders 5.68×**, **Praktiker 3.69×** (5% discount rate).

**Post-adoption ([IASB AP7F literature review, March 2025](https://www.ifrs.org/content/dam/ifrs/meetings/2025/march/iasb/ap7f-review-academic-literature.pdf)):** IFRS 16 *"significantly increased entities' assets and liabilities affecting entities' financial ratios (mainly leverage and profitability ratios)"*; users *"initially reacted negatively to the capitalisation of operating leases because of the increase in leverage ratios."* **Ferreira, Landsman & Roundtree (2024)**, US n = 2,822 (2018–2020): entities *"reduced their liabilities unrelated to leases by **7% ± 10%** as their lease-related liabilities increased by **5%**."* **Kim & Xie (2023)**, 24,945 entity-years (2012–2020): faster adjustment to target leverage post-Topic 842. **Implication: reported post-adoption leverage *understates* the economic change** (firms re-contracted non-lease debt under covenant pressure), so cross-sectional comparability across the 2018/19 transition is worse than a naive capitalise-the-leases adjustment implies.

**ASC 842 divergence for X3:** FASB's **dual** model keeps the whole operating-lease cost in operating expense (vs IFRS 16's depreciation + interest split), so **an IFRS 16 filer and an ASC 842 filer with identical leases diverge on EBIT/TA** while both show the same X4 denominator effect. Any cross-border Z-score mixes two X3 treatments.

**Altman's own view [PRIMARY]:** he recommends Z'' precisely for situations where *"important adjustments, **like lease capitalization, are not made**"* (§1).

**Other items.** `RetainedEarningsAccumulatedDeficit` is signed: American Airlines reports **−6,732,000,000** at 2025-12-31. Buybacks hit treasury stock, not RE — Boeing at 2025-12-31 has RE **17,252,000,000**, equity **5,454,000,000**, treasury stock **28,029,000,000** — so **X2 and equity-based ratios are not interchangeable for buyback-heavy firms.**

### 6.4 UNVERIFIED list for §6

1. **No accessible study quantifies IFRS 16's effect on Altman Z-scores specifically.** The one on-topic paper (Damascus Univ. Journal, Arabic) was unreachable (DOAJ HTTP 403; host timed out). **No numeric Z-impact claim is made.**
2. **FASB primary sources unreachable** — `fasb.org` / `xbrl.fasb.org` return HTTP 403 (Cloudflare). US-GAAP names are cited to SEC-hosted artefacts.
3. **No source quantifying ASC 606's effect on revenue *levels* or X5.**
4. **The ~21% unclassified figure is a `frames`-API computation, not an SEC statistic.**
5. **No official UK rate of abridged/micro filings**; no Companies House API key, so no live company responses exercised.

### 6.5 Independent spot-check of §6

Re-probed live: Deere `AssetsCurrent` → **404**, `LiabilitiesCurrent` → **404**, `Assets` → **200** ✓ · `frames` `us-gaap/Assets/USD/CY2024Q4I` → **200, n = 6,271** ✓ · Caterpillar `SalesRevenueNet` → 200, `label` = **"Revenue, Net (Deprecated 2018-01-31)"** ✓. My Apple `dei` probe returned a newer as-of date (2026-07-17) than the FY2025 figure (2025-10-17) because I fetched the *latest* fact rather than the FY2025 filing — **consistent, not contradictory**.

---

## 7. Out-of-sample / post-publication literature review

**Access note:** SSRN, Wiley, ScienceDirect and Springer full texts were Cloudflare-blocked or paywalled. Full primary text was obtained for **Altman (2000)**, **Hillegeist et al. (2004)** and **Agarwal & Taffler (2007 working paper)**. The rest is verified publisher/repository abstracts + metadata (Crossref, OpenAIRE, BYU ScholarsArchive, Warwick WRAP). **Second-hand numbers are labelled.**

### 7.1 Begley, Ming & Watts (1996) **[PEER-abs]** + second-hand figures

*Bankruptcy classification errors in the 1980s: An empirical analysis of Altman's and Ohlson's models*, **Review of Accounting Studies 1, 267–284** (Dec 1996), DOI [10.1007/BF00570833](https://doi.org/10.1007/BF00570833). Verified abstract, exact: *"While these models performed relatively well when they were estimated, we show that they **do not perform as well in more recent periods (in particular, the 1980s), even when the coefficients are re-estimated**… we find that **Ohlson's original model displays the strongest overall performance**."*

**⚠️ SECOND-HAND — could not corroborate:** [Agarwal & Taffler (2007) working paper](https://cer.business-school.ed.ac.uk/wp-content/uploads/sites/55/2017/02/workingpaper07-5.pdf), fn. 27: *"Begley et al. (1996) report out-of-sample type I and type II error rates of **18.5% and 25.1%** for the Altman (1968) model and **10.8% and 26.6%** for the Ohlson (1980) model using small samples of bankrupt and non-bankrupt firms."* These four numbers appear nowhere else in what I could open. **Treat as once-only/second-hand.**

**Counter-evidence within the literature [PRIMARY]:** Hillegeist et al. (2004) note their own result *"is inconsistent with Begley et al. (1996), who find that the original Ohlson coefficients perform better in their prediction tests compared to their updated coefficients."*

### 7.2 Grice & Ingram (2001) and Grice & Dugan (2003) **[PEER-abs]** — no numbers obtained

**Grice & Ingram (2001)**, *Journal of Business Research* **54, 53–61**, DOI [10.1016/S0148-2963(00)00126-0](https://doi.org/10.1016/S0148-2963(00)00126-0). Verified abstract, exact: *"…it is likely that model is not as effective in classifying firms in more recent studies as it was when it was developed by Altman… Our results are consistent with **NEGATIVE** answers to questions one and two and a **POSITIVE** answer to question three."* (Q1 = is Z as useful in recent periods; Q2 = non-manufacturers vs manufacturers; Q3 = other distress conditions vs bankruptcy.) → **Z is less accurate in recent periods and less accurate for non-manufacturers, but generalises to non-bankruptcy distress.** **NO NUMBERS OBTAINED — UNVERIFIED.**

**Grice & Dugan (2003)**, *Advances in Accounting* **20, 77–93**, DOI [10.1016/S0882-6110(03)20004-3](https://doi.org/10.1016/S0882-6110(03)20004-3). Verified abstract, exact: *"researchers who use the Zmijewski and Ohlson models using recent data should **re-estimate** the models' coefficients to improve the predictive accuracy of the models."* ⚠️ **This paper is about Zmijewski and Ohlson, NOT Altman's Z.** **No numbers obtained.**

### 7.3 Shumway (2001) **[PEER-abs]**

*Forecasting Bankruptcy More Accurately: A Simple Hazard Model*, **The Journal of Business 74(1), 101–124** (Jan 2001), DOI [10.1086/209665](https://doi.org/10.1086/209665). ⚠️ The often-cited `10.1086/209696` resolves to an unrelated "Books Received". Closed access; Unpaywall/OpenAlex report no OA copy; SSRN Cloudflare-blocked.

Verified abstract ([BYU ScholarsArchive author deposit](https://scholarsarchive.byu.edu/facpub/9280/)), exact criticisms: *"Single-period bankruptcy models give biased and inconsistent probability estimates while hazard models produce consistent estimates"*; *"about half of the accounting ratios that have been used in previous models are not statistically significant bankruptcy predictors"*; market-driven variables include *"market size, past stock returns, and the idiosyncratic standard deviation of stock returns"*; his model *"produce[s] more accurate out-of-sample forecasts than alternative models."*

**⚠️ HIS ACCURACY FIGURES ARE UNVERIFIED — could not access the paper.** **TRAP TO AVOID:** Huettemann's Cologne thesis lists AUCs of 0.851 for a spec labelled "Shumway (2001)", 0.675 "Altman (1968)", 0.731 "Ohlson", 0.854 "Bharath & Shumway" — **those are the thesis's own German-data replications, NOT Shumway's reported figures. Do not attribute them to Shumway.**

### 7.4 Hillegeist, Keating, Cram & Lundstedt (2004) — **full primary text read** **[PEER]**

*Assessing the Probability of Bankruptcy* — [archived Harvard PDF](https://web.archive.org/web/20040929035551/http://ksghome.harvard.edu:80/~ekeatin/HILLEG~1.PDF).

**Sample, exact:** *"**78,100 firm-year observations and 756 initial bankruptcies** during the **1980–2000** period."*

**Headline, exact:** *"BSM-Prob **outperforms the original Z-Score and O-Score by 71% and 33%**, respectively. BSM-Prob's pseudo-R² is **20% larger** than the pseudo-R² for the best accounting-based model, O-Score_u."*

**Table 5 (log-likelihood / pseudo-R²):**

| Model | Log-likelihood | Pseudo-R² |
|---|---|---|
| Z-Score | 3,972 | **0.07** |
| Z-Score_u (updated) | 4,024 | 0.06 |
| O-Score | 3,881 | 0.09 |
| O-Score_u (updated) | 3,831 | **0.10** |
| BSM-Score | 3,728 | **0.12** |

*"the difference between the two measures' log likelihood statistics is **103** (3831 vs. 3728)… significant at the 1% level."* BSM pseudo-R² (0.12) is *"twice as large as"* the worst model, Z-Score_u (0.06).

**Coefficient instability, exact:** *"only two of the Altman variables, VE/TL and EBIT/TA, are statistically significant, while the remaining three accounting-based variables, **WC/TA, RE/TA, and S/TA, are insignificant**."* For Ohlson: *"eight of the nine updated coefficients are statistically significant… **five of the eight significant coefficients have different signs**."*

**Re-estimation HURT:** *"Z-Score outperforms Z-Score_u"* (0.07 vs 0.06 pseudo-R²). They also explicitly reject classification-error testing on the grounds that it assumes equal error costs.

### 7.5 Agarwal & Taffler (2007 working paper; 2008 JBF) — **full primary text read** **[PEER]**

*(2008)*: *Comparing the performance of market-based and accounting-based bankruptcy prediction models*, **Journal of Banking & Finance 32(8), 1541–1551**, DOI [10.1016/j.jbankfin.2007.07.014](https://doi.org/10.1016/j.jbankfin.2007.07.014). Abstract verified from [Warwick WRAP](https://wrap.warwick.ac.uk/id/eprint/49199/), exact: *"We find the two approaches **capture different aspects of bankruptcy risk**, and while there is **little difference in their predictive ability in the UK**, the z-score approach leads to significantly greater bank profitability in conditions of differential decision error costs and competitive pricing regime."* **Specific AUC/error numbers UNVERIFIED.**

*(2007)*: *Twenty-five years of the Taffler z-score model* — [Edinburgh CER working paper](https://cer.business-school.ed.ac.uk/wp-content/uploads/sites/55/2017/02/workingpaper07-5.pdf). **Note: Taffler's UK model, not Altman's Z**, but it carries the strongest true *ex ante* evidence and explicit Altman benchmarks:

- **Altman (1968) applied to US non-financial NYSE/AMEX/NASDAQ firms, 1988–2003:** *"almost half of these firms (**47%**) have a z-score less than Altman's optimal cut-off of 2.675. In addition, **19%** of the firms entering Chapter 11 during this period had z-scores greater than 2.675."*
- **Methodological criticism of matched-pair studies:** Begley et al. *"typically use samples of failed and non-failed firms… rather than testing the respective models on the underlying population. This… does not provide a true test of ex ante forecasting ability as the key issue of type II error rates… is not addressed."*
- **Taffler model, full UK population 1979–2003:** 232 failures; **223 (96.1%)** had z < 0 on last accounts; 7,325 firm-years (**27%**) with z < 0; base failure rate **0.85%** (232/27,243); conditional P(failure | z < 0) = **3.04%**; χ² = 570.5; *"The area under the ROC curve when using z-score quintiles is **0.90** and the corresponding accuracy ratio (Gini coefficient) is **0.80**."*
- **UK drift:** at-risk z-scores *"increases dramatically from around **26% in 1997 to 41% by 2003**"*, attributed partly to *"the growth in the services sector associated with contraction in the number of industrial firms listed"*, a doubling of loss-making firms 1997–2002, and increased kurtosis of ratio distributions.
- **Cut-off sensitivity:** a −1.0 adjustment from 1997 leaves Type I unchanged but *"the average type II error rate falls from 35% to 29%"*; at −2.0 the *"type I error rate to 15.5% from 11.3%"* and type II *"to 24%."*
- **Explicit, exact:** *"Begley et al. (1996) and Hillegeist et al. (2004) recalculate Altman's original 1968 model updating his ratio coefficients on new data; however, **both papers find that their revised models perform less well than the original model**."*

### 7.6 Large firms / services / post-1990

**Supported:**
- **Horizon decay is intrinsic** — Altman 2000 original sample: 94% → 72% → 48% → 29% → 36% for years 1–5.
- **Altman built ZETA because firm size had shifted** — *"The average size of bankrupt firms had increased dramatically"*; ZETA used a ≈$100m-asset sample (no firm < $20m) and beat Z from year 2 (~70% vs 36% by year 5).
- **Sector shift is a named driver** — Z'' drops the industry-sensitive sales/TA ratio *"in order to minimize the potential industry effect"*; Agarwal & Taffler link rising UK at-risk scores to services-sector growth.
- **Broad post-1990 populations** — 47% of US non-financial listed firms below the 2.675 cut-off (1988–2003); Altman's own 15–20% Type II figure on Compustat manufacturers.

**UNVERIFIED:** no opened study isolates Z accuracy **by firm size** or for **tech firms specifically**, and none reports post-1990 accuracy in a form comparable to Altman's Table 5.

### 7.7 Altman, Iwanicz-Drozdowska, Laitinen & Suvas (2017) **[PEER-abs]**

*Financial Distress Prediction in an International Context: A Review and Empirical Analysis of Altman's Z-Score Model*, **Journal of International Financial Management & Accounting 28(2), 131–171**, DOI [10.1111/jifm.12053](https://doi.org/10.1111/jifm.12053). **CLOSED** — Wiley Cloudflare-blocked; OpenAlex reports `is_oa:false`, no repository copy. **This is why Z''-EM could not be sourced from the 2017 paper** (it was ultimately verified from Altman's own 2000 paper instead — see §1).

Verified 2017 abstract (Crossref): *"firms from **31 European and three non-European countries**"*; sample *"primarily private"*, *"non-financial companies across all industrial sectors"*; uses *"the original Z″-Score model developed by Altman, Corporate Financial Distress (1983)."*

**Verified accuracy**, from the 2014 SSRN working-paper abstract ([archived page](http://web.archive.org/web/20260829040839/https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2536340)): *"a general international model works reasonably well, for most countries, with **prediction accuracy levels (AUC) of about 75%**, and exceptionally well for some (**above 90%**)"*; the literature review is *"based on an analysis of **33 scientific papers published from the year 2000**."*

**UNVERIFIED:** sample period, firm counts, bankrupt count, and the country-specific AUCs (closed full text, no mirror found). The 2017 typeset article and the 2014 working paper **may differ** — this was not checked.

### 7.8 Verdict

**ROBUST (multiply replicated):**
1. **Altman's 1968 coefficients are unstable out-of-sample; re-estimation changes them materially.**
2. **On broad recent populations, Z misclassifies heavily in both directions.**
3. **Z's useful horizon is ~2 years.**

**ONCE-ONLY (not replicated in anything I could open):** Begley et al.'s exact 18.5%/25.1% and 10.8%/26.6% error-rate pairs; Altman et al. (2017)'s country-level AUCs.

**CONTESTED:**
- **Market-based vs accounting-based dominance.** Hillegeist et al. (2004) say BSM-Prob dominates decisively (pseudo-R² 0.12 vs 0.07/0.10, Vuong-significant, LL gap 103). Agarwal & Taffler (2008) say there is *"little difference in their predictive ability in the UK"* and a z-score advantage on bank profitability.
- **Whether re-estimating helps.** Begley et al. and Hillegeist et al. both find the **original** coefficients outperform updated ones; Grice & Dugan (2003) argue for re-estimation (for Zmijewski/Ohlson). Altman's own Z' work argues for "complete reestimation."

**Added UNVERIFIED list:** (1) Begley et al. full text/tables; (2) any numbers from Grice & Ingram (2001); (3) any numbers from Grice & Dugan (2003); (4) Shumway's own reported Z-vs-hazard accuracy; (5) Altman et al. (2017) sample period/firm counts/bankrupt count and country AUCs; (6) Agarwal & Taffler (2008) specific AUC/error numbers; (7) any size-stratified or tech-sector Z accuracy study; (8) whether the 2017 typeset article's numbers match the 2014 working paper's.
