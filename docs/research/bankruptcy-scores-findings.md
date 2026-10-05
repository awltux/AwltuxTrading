# Bankruptcy-Prediction Accounting Scores — Source-Grounded Findings (v2, consolidated)

*All figures were read from the sources cited. Where a source could not be opened, or where sources conflict, that is stated. Nothing is rounded beyond the source's own precision.*

**Tiers:** **[PRIMARY]** author's own paper/workpaper read in full · **[PEER]** peer-reviewed journal · **[THESIS]** MSc/PhD thesis · **[REF]** encyclopedia/secondary.

---

## 1. Altman Z-score (1968)

### (a) Exact original formula and inputs [PRIMARY]

From Altman's own 2000 revisiting paper, quoting the 1968 function:

`Z = 0.012X1 + 0.014X2 + 0.033X3 + 0.006X4 + 0.999X5`

| Ratio | Altman's exact definition |
|---|---|
| X1 | working capital / total assets |
| X2 | retained earnings / total assets |
| X3 | EBIT / total assets |
| X4 | market value equity / book value of total liabilities |
| X5 | sales / total assets |

Altman's own "A Clarification": *"Due to the original computer format arrangement, variables X1 through X4 must be calculated as absolute [percentages]… X1 should be included as 10.0% and not 0.10. Only variable X5 [is] expressed in a different manner: that is, a S/TA ratio of 200% should be included as 2.0."*

Convenient rescaled form (also given by Altman): `Z = 1.2X1 + 1.4X2 + 3.3X3 + 0.6X4 + 1.0X5` — *"The scores for individual firms and related group classification and cutoff scores remain identical."*

Zones: >2.99 safe; 1.81–2.99 grey / "zone of ignorance"; <1.81 distress. Altman's own preference: *"I advocate using the lower bound of the zone-of-ignorance"* (1.81) rather than 2.675, *"The latter resulted in the lowest overall error in the original tests."*

Source: Altman, *Predicting Financial Distress of Companies: Revisiting the Z-Score and ZETA Models*, July 2000, NYU Stern working paper — [archived PDF](http://web.archive.org/web/20240717121208if_/https://pages.stern.nyu.edu/~ealtman/Zscores.pdf) **[PRIMARY]**. Zones also on [Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score) **[REF]**.

### (b) Origin

Altman (1968), *Financial Ratios, Discriminant Analysis and the Prediction of Corporate Bankruptcy*, Journal of Finance 23(4), 589–609, DOI [10.1111/j.1540-6261.1968.tb00843.x](https://doi.org/10.1111/j.1540-6261.1968.tb00843.x). Closed access ([OpenAlex](https://api.openalex.org/works/doi:10.1111/j.1540-6261.1968.tb00843.x): `is_oa:false`, `oa_status:"closed"`).

### (c) Original sample [PRIMARY]

- 66 corporations, **33 bankrupt + 33 non-bankrupt → matched pairs, yes**.
- Bankrupts filed *"petition under Chapter X of the National Bankruptcy Act from **1946 through 1965**."*
- *"Group 2 consists of a paired sample of manufacturing firms chosen on a stratified random basis. The firms are stratified by **industry and by size**, with the asset size range restricted to between **$1 and $25 [million]**."*
- Data from *"financial statements dated one annual reporting period prior to bankruptcy"*; average lead time ≈ 7.5 months.
- *"a list of 22 [variables] potentially helpful was compiled for evaluation"*, spanning liquidity, profitability, leverage, solvency, activity → reduced to 5.

⚠️ Wikipedia says only *"small firms with assets of < $1 million were eliminated"* — it **omits the $25M upper bound** Altman's own text gives.

### (d) Altman's own reported accuracy [PRIMARY — Table 2]

| | Correct | % correct | % error | n |
|---|---|---|---|---|
| Type I (bankrupts) | 31 | **94%** | **6%** | 33 |
| Type II (non-bankrupts) | 32 | **97%** | **3%** | 33 |
| Total | 63 | **95%** | **5%** | 66 |

Altman: *"The model is extremely accurate in classifying 95% of the total sample correctly. The Type I error proved to be only 6% while the Type II error was even lower at 3%. The results, therefore, are encouraging, but the obvious upward bias should be kept in mind."*

Two statements prior (Table 3): Type I 23/32 = **72% correct / 28% error**; Type II 31/33 = **94% / 6%**; total 54/65 = **83% / 17%**.

Secondary samples: new sample of **25 bankrupt firms → 24 correct = 96% (4% error)**. A sample of **66 loss-making manufacturers → 14 of 66 classified bankrupt, 52 correct = 79%** (t = 4.8, p < 0.001).

Altman's own post-publication tests: *"I examined 86 distressed companies from 1969–1975, 110 bankrupts from 1976–1995 and 120 from 1997–1999. I found that the Z-Score model, using a cutoff score of 2.675, was between **82% and 94% accurate**."* And: *"the predictive accuracy of the Z-Score model on samples of distressed firms has been in the vicinity of **80–90%**, based on data from one financial reporting period prior to bankruptcy."* Also: *"In 1999, the proportion of U.S. industrial firms, comprised in the Compustat data tapes, that had Z-Scores below 1.81 was over 20%."*

⚠️ **Wikipedia's Altman page is wrong here.** It claims the initial test was *"72% accurate in predicting bankruptcy two years before the event, with a Type II error (false negatives) of 6%"*. Per Altman's own tables: 72% is the one-year Type I **accuracy** in the **two-year** test, and 6% is the Type I **error** in the **one-year** test. Wikipedia conflates the horizons and mislabels the error type.

⚠️ Group means: Altman 2000 gives Group 1 = **−0.29**, Group 2 = **+5.02** (F = 20.7). Wikipedia gives −0.25 / +4.48. **Unresolved.**

### Z''-score and Z''-EM

```
Z''    = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
Z''-EM = 3.25 + 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4
```
X1 = (current assets − current liabilities)/total assets; X2 = RE/TA; X3 = EBIT/TA; **X4 = book value of equity / total liabilities** (not market value); **X5 dropped**. Zones: **>2.6 safe · 1.1–2.6 grey · <1.1 distress**. [(Wikipedia)](https://en.wikipedia.org/wiki/Altman_Z-score) **[REF]**

**Corroboration [PEER]:** Daskalakis, Aggelakis & Filos (2022), *Applying, Updating and Comparing Bankruptcy Forecasting Models. The Case of Greece*, J. Accounting & Management Information Systems 21(3), 335–354, DOI [10.24818/jamis.2022.03002](https://doi.org/10.24818/jamis.2022.03002) — [PDF](https://www.econstor.eu/bitstream/10419/310834/1/21_3_02.pdf) — reproduces *"3.26 (retained earnings/total assets) + 6.72 (earnings before interest and taxes/total assets) + 1.05 (book value of equity/book value of total debt)"* and the 1.10 / 2.60 cutoffs. Metadata via [EconStor](https://www.econstor.eu/handle/10419/310834).

**The +3.25 EM constant:** *"Stating that this model, which is valid for companies in the USA, may yield deviant results in developing countries, Altman obtained the emerging market model by adding a constant term (+3.25) to equation (2) in order to standardize the scores obtained"* — cited there to **Altman (2013: 27)** — Delice (2022), *Sosyal ve Beşeri Bilimler Araştırmaları Dergisi* 24(42), 387–414 — [PDF](https://dergipark.org.tr/tr/download/issue-full-file/70427).

**Why the coefficients differ (sourced):**
1. **X5 removed.** *"since the fifth variable (X5) gives high values for non-manufacturing companies, a new model was created for non-manufacturing sectors… Since this model was created by removing X5, the weights of the remaining four variables had to be changed"* (Altman 2002: 22, via the dergipark PDF). Altman's own 1968 rationale: *"X5 is the standard measure for total asset turnover (varying widely from industry to industry)."* **[PRIMARY]**
2. **X4 switches market→book equity** so private firms with no observable price can be scored ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score); [Economia Aziendale Online PDF](http://riviste.paviauniversitypress.it/index.php/ea/article/download/557/2019): *"For private firms Altman substituted the book values of equity for their market values"*).
3. **It is a genuine re-estimation, not the ×100 rescaling:** 6.56/3.26/6.72/1.05 are not 100× the originals 1.2/1.4/3.3/0.6 — the relative weights changed.

⚠️ **The leading `6.56` is confirmed only by Wikipedia.** Both PDF sources I extracted dropped it (font-subset extraction loss). High confidence, but **not primary-verified**.

### (e) Out-of-sample / after publication

- **[PRIMARY]** Altman's Table 9 — 1968 Z applied to the ZETA sample, by years prior: **bankrupt-firm accuracy 93.9% (yr1) → 71.9% (yr2) → 48.3% (yr3) → 28.6% (yr4) → 36.0% (yr5)**; non-bankrupt 97.0% → 93.9% → n.a. *"by the fifth year, the ZETA model is still about 70% accurate but the Z-Score's accuracy falls to 36%."*
- **[THESIS]** Bouwmeester (Univ. of Twente, 2020), Dutch & Belgian public and large private firms — [PDF](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf): Altman (1983) variant in-sample **93.47% overall but only 32.39% of bankrupts** correctly classified (99.58% of non-bankrupts). Ohlson variables: 95.01% overall / 47.89% of bankrupts. Zmijewski variables: 94.37% / 38.03%. **Out-of-sample AUC: Ohlson 0.696/0.738/0.717 (MDA/logit/probit); Zmijewski 0.683/0.697/0.690.**
- **[THESIS]** The arithmetic that destroys the headline numbers: *"even when the model predicts bankruptcy in all cases, the percentage correctly classified is 2058/(2058+105) = 95.15%"* — [PDF](http://arno.uvt.nl/show.cgi?fid=135794).
- **Published critique (contested, not debunked):** Johnson (1970), J. Finance 25(5) 1166–1168: *"largely descriptive statements devoid of predictive content… Altman demonstrates that failed and non-failed firms have dissimilar ratios, not that ratios have predictive power. But the crucial problem is to make an inference in the reverse direction, i.e., from ratios to failures."* (quoted on [Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score)).
- **[PEER]** Daskalakis et al. (2022), Greek listed firms 2010–2019 (n = 52): *"the original models are significantly biased against viable companies, but predict with almost perfect accuracy non-viable companies' bankruptcy"*; re-estimating coefficients locally *"significantly impro[ves] results as regards correctly predicting viable companies, at the expense of slightly decreased, but still high, non-viable companies' bankruptcy prediction rates."*

**Verdict:** the 95% original-sample figure is in-sample and upward-biased by Altman's own admission. Durable replicated claim: **~80–90% one year prior, collapsing past two years**, on 1960s–1990s US manufacturers. Altman's later tests (82–94%) do **not** show monotonic decline, so "Z has decayed over time" is **partially supported, not established**.

### (f) Practical caveats

- **Not for financials:** *"Neither the Altman models nor other balance sheet-based models are recommended for use with financial companies. This is because of the opacity of financial companies' balance sheets and their frequent use of off-balance sheet items."* ([Wikipedia](https://en.wikipedia.org/wiki/Altman_Z-score))
- **X5 varies widely by industry** — the reason it is dropped in Z''.
- **Size:** original sample restricted to $1–25M assets; small (<$1M) and large firms excluded.
- **RE manipulation:** Altman notes retained earnings *"is subject to 'manipulation' via corporate quasi-reorganizations and stock dividend declarations."*
- **Young firms structurally penalised** via X2.
- **Cutoff choice changes the answer materially** (1.81 vs 2.675 vs 2.99).
- **Accounting-standard changes:** see §6.3.

### (g) Computability from SEC EDGAR XBRL / UK Companies House iXBRL

**See §6.** Short version: workable for most US filers but not plug-and-play; **structurally undefined for UK small/micro filers**.

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

TA = total assets; GNP = GNP price-level index (USD, 1968 = 100); TL = total liabilities; WC = working capital; CL = current liabilities; CA = current assets; **X = OENEG** = 1 if TL > TA else 0; NI = net income; FFO = funds from operations; **Y = INTWO** = 1 if net loss for the last two years else 0.
Probability: `P = exp(O) / (1 + exp(O))`. [(Wikipedia raw wikitext)](https://en.wikipedia.org/w/index.php?title=Ohlson_O-score&action=raw) · [(Wikipedia)](https://en.wikipedia.org/wiki/Ohlson_O-score)

**⚠️ SOURCE CONFLICT.** A QUB working paper gives `−1.32 − 0.407·log(assets) + 0.603·(TL/assets) − 1.43·(WC/assets) + 0.0757·(current assets/current liabilities) − 2.37·(NI/assets) − 1.83·(FFO/TL) + 0.285·dummy − 1.72·dummy − 0.521·ΔNI` — [PDF](https://pureadmin.qub.ac.uk/ws/portalfiles/portal/586396214/TalkWalk.pdf). Two other sources give **6.03** (not 0.603) and **CL/CA** (not CA/CL): the Wikipedia LaTeX above, and Bouwmeester's list *"x4 = Current liabilities/Current assets"* ([PDF](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)). **My assessment: 6.03 with CL/CA is correct; QUB looks like a transcription error — but the original paper was unreadable, so this is not settled.**

### (b) Origin

James A. Ohlson (1980), *Financial Ratios and the Probabilistic Prediction of Bankruptcy*, **Journal of Accounting Research 18(1), 109–131 (Spring 1980)** — volume/pages confirmed from the JSTOR cover page in the archived scan. <https://www.jstor.org/stable/2490395>, DOI [10.2307/2490395](https://doi.org/10.2307/2490395) ([OpenAlex](https://api.openalex.org/works/doi:10.2307/2490395)).

⚠️ The only free copy ([Wayback/Ryerson](https://web.archive.org/web/20210805133803if_/https://math.ryerson.ca/ramlab/projects/crd/ohlson1980.pdf)) is a **JSTOR scan with no OCR text layer** (23 CCITTFax images; text layer only on the cover page). **The body could not be read.**

### (c) Sample [THESIS]

*"the sample consisted of **105 bankrupt firms and 2,058 non-bankrupt firms** in the period from **1970 to 1976**. The sample excludes small or privately held firms, because the firms in the sample had to be traded on some stock exchange or over-the-counter market. The firms also must be classified as an industrial… Ohlson obtained three years of data prior to the date of bankruptcy and developed three logit models. Model 1 predicts bankruptcy within one year, model 2 within two years given that the company did not fail within the subsequent year, and model 3 within one or two years."* — [PDF](http://essay.utwente.nl/82525/1/Bouwmeester_MA_BMS.pdf)

### (d) Reported accuracy — **read the caveat**

- [THESIS, Twente] *"The optimal cut-off point which minimizes the sum of errors is **0.038**"*; *"Using this cut-off point, **82.6% of the non-bankrupt firms and 87.6% of the bankrupt firms** were correctly classified."*; *"The overall accuracy rate of the estimation-sample was **96%** and for the hold-out sample **85%** (Ohlson, 1980)."*
- [THESIS, UVT/Tilburg] *"The percentage of correctly predicted observations of the first model is **96.12%**, but this number should be interpreted with caution… even when the model predicts bankruptcy in all cases, the percentage correctly classified is 2058/(2058+105) = **95.15%**."*; optimal cutoff minimising Type I+Type II = **0.038**; *"…[87.6% of bankrupt] firms and **82.6% of the non-bankrupt firms** correctly at t−1."* — [PDF](http://arno.uvt.nl/show.cgi?fid=135794)

**⚠️ These are mutually inconsistent.** 87.6%×105 + 82.6%×2,058 = 1,792 correct = **82.8%**, not 96.12%; conversely 96.12% implies ~84 total misclassifications. Both cannot hold at the same cutoff on the same sample. **All three are reported as-is, unmatched to a verified cutoff.** The likely resolution (different cutoffs) is **UNVERIFIED**. No source I opened gives clean Type I/Type II error rates from the original paper.

### (e) Out-of-sample / after publication

- [THESIS, Twente] Ohlson variables on Dutch/Belgian firms: in-sample 95.01% overall but only **47.89% of bankrupts**; **out-of-sample AUC 0.696 (MDA) / 0.738 (logit) / 0.717 (probit)**. Re-estimating with logit instead of MDA did **not** significantly improve AUC.
- **[PEER]** Daskalakis et al. (2022) find the same near-perfect-on-failures / biased-against-viable asymmetry.
- ⚠️ **Wikipedia's claim that the O-score is "significantly more accurate" than Z is an unsourced assertion** on a page flagged "needs more citations". No opened source supports it; the one same-sample comparison I opened shows Ohlson and Zmijewski variables performing very similarly to Altman's out-of-sample. **Treat the superiority claim as unsupported.**

### (f)/(g) Caveats and computability

- **GNP price-level index (1968 = 100)** must be sourced historically — awkward today, classic implementation error.
- **Class imbalance dominates headline accuracy** — require Type I and Type II separately.
- **0.038 optimal cutoff vs. the 0.5 rule of thumb** behave very differently.
- **FFO is not a standard modern XBRL/IFRS line item.**
- Ohlson deliberately excluded small and private firms.
- XBRL/iXBRL: **see §6** (the §6 research covered Altman Z inputs; the O-score-specific input set — GNP index, FFO — was **not** researched and remains **UNVERIFIED**).

---

## 3. Zmijewski (1984) probit

### (a)/(b) Formula and origin

Zmijewski (1984), *Methodological Issues Related to the Estimation of Financial Distress Prediction Models*, Journal of Accounting Research 22 (Supplement), 59–82. ⚠️ **The DOI I have ([10.1016/0882-6110(03)20004-3](https://doi.org/10.1016/s0882-6110(03)20004-3)) came from a search result and was not independently confirmed.**

Formula as reproduced in Gerritsen (Twente MSc thesis) — [PDF](http://essay.utwente.nl/68211/1/Gerritsen%20P.L._MA%20BA_Behavioural%2C%20Management%20and%20Social%20sciences%20%28BMS%29.pdf) **[THESIS]**:
```
Zmijewski = −4.3 − 4.5·X1 + 5.7·X2 + 0.004·X3
X1 = Net income / Total assets
X2 = Total liabilities / Total assets
X3 = Current assets / Current liabilities
```
Probit ⇒ probability = Φ(index). The thesis text says only that *"the outcome of this probit model lies between 0 and 1"* — the exact transform is **UNVERIFIED**. **Commonly cited precise coefficients (−4.336, −4.513, 5.679, 0.004): UNVERIFIED** (search snippet only).

### (c) Sample [THESIS]

*"The estimation sample of Zmijewski's study contained **40 bankrupt and 800 non-bankrupt firms**, and the **hold-out sample consisted of 41 bankrupt and 800 non-bankrupt firms**. The population of his study consists of all firms listed on the American and New York Stock Exchanges between **1972 and 1978** with SIC-codes below 6000. This means that finance, service and public administration firms were excluded from the research."*

### (d) Reported accuracy

- [THESIS] *"The accuracy rate of the Zmijewski (1984) model for the estimation sample was **99%**, while the accuracy rate of the hold-out sample was **not reported**."*
- [THESIS, Bouwmeester] Dutch/Belgian firms: in-sample 94.37% overall but only **38.03% of bankrupts** (100.00% of non-bankrupts); **out-of-sample AUC 0.683 / 0.697 / 0.690 (MDA/logit/probit)**.

### (e) Post-publication — **contested**

- *"Shumway (2001, p. 120) argues that Zmijewski's model is in fact only a **one-variable model** because the selected variables are highly correlated to each other. Shumway (2001) even claims that because of this correlation the model has **no strong predictive power** for bankruptcy."*
- *"Platt and Platt (2002, p. 186) state that Zmijewski (1984) could not test the individual estimated coefficients for bias against the population parameter since Zmijewski ran only one regression for each sample size."*
- *"Grice and Dugan (2003)… claim that the ratios were not selected on a theoretical basis, but rather on the basis of their performance in prior studies."*

The 99% is **in-sample with 20:1 imbalance** (naive all-negative = 800/840 = **95.2%**), so it is not comparable to an out-of-sample AUC of ~0.69.

### (f)/(g)

Same structural caveats. XBRL/iXBRL: the §6 research covered Altman Z inputs, not Zmijewski's — **UNVERIFIED** for this model, though the tag set is a subset of Altman's.

---

## 4. Robust / not robust

| Claim | Status |
|---|---|
| Altman 1968 formula `0.012X1+0.014X2+0.033X3+0.006X4+0.999X5`; 66 firms (33/33); 1946–65 US manufacturers; $1–25M assets; matched industry+size | **Robust — Altman's own text [PRIMARY]** |
| Altman original: Type I 6% error, Type II 3% error, 95% overall | **Robust — Altman's own Table 2 [PRIMARY]** |
| Altman later: 82–94% one year prior; "in the vicinity of 80–90%"; collapses after 2 years | **Robust — Altman's own text [PRIMARY]** |
| Wikipedia's "72% / Type II 6%" account of the original test | **Contested/wrong — contradicts Altman's own tables** |
| Z'' = 6.56X1+3.26X2+6.72X3+1.05X4; Z''-EM adds +3.25 | **Partly verified — 3.26/6.72/1.05 + cutoffs corroborated [PEER]; 6.56 and full EM string only via Wikipedia** |
| Ohlson 9 coefficients (−1.32, −0.407, 6.03, −1.43, 0.0757, −1.72, −2.37, −1.83, 0.285, −0.521) | **Verified via Wikipedia LaTeX + corroborated in two theses; original unreadable; QUB conflicts on 6.03 and CL/CA** |
| Ohlson sample 105/2,058, 1970–76 exchange-traded industrials | **Replicated across two theses** |
| Ohlson reported error rates | **CONTESTED — three mutually inconsistent figures; unresolved** |
| Ohlson hold-out 85% | **Single-source [THESIS], uncorroborated** |
| Ohlson "more accurate than Z" | **Unsupported — Wikipedia assertion, no source** |
| Zmijewski formula/sample/99% | **Single MSc thesis; not independently corroborated** |
| Zmijewski effectively one-variable | **Published critique quoted via a thesis; Shumway not opened** |
| Headline accuracy inflated by ~20:1 class imbalance | **Robust — arithmetic shown explicitly in two independent theses** |
| US Z-inputs obtainable from EDGAR XBRL with fallback chains | **Verified by live SEC API probes (§6.1)** |
| UK small/micro Z-score is structurally undefined | **Verified from Companies Act 2006 s.444(5)(a) + GOV.UK (§6.2)** |

---

## 6. Supplement — practical computation from filings, and lease-accounting effects

*(Closes the (g) and lease items left open in the first pass. Load-bearing claims independently re-probed by me — see §6.5.)*

### 6.1 SEC EDGAR / US-GAAP XBRL

Endpoints documented on the [EDGAR Application Programming Interfaces page](https://www.sec.gov/search-filings/edgar-application-programming-interfaces). `data.sec.gov/api/xbrl/companyconcept/`, `.../companyfacts/`, `.../frames/` return XBRL facts; no API key. The APIs aggregate only facts that (i) *"Use a non-custom taxonomy (e.g. us-gaap, ifrs-full, dei, or srt)"* and (ii) *"Apply to the entire filing entity"*, which *"ensures that facts have a consistent context and meaning across companies and between filings"*.

**Verified tag map** (each element name confirmed via the SEC `companyconcept` API, reading the returned `tag`/`label`):

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

Probe URLs: [AssetsCurrent](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/AssetsCurrent.json) · [RetainedEarningsAccumulatedDeficit](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/RetainedEarningsAccumulatedDeficit.json) · [dei:EntityCommonStockSharesOutstanding](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/dei/EntityCommonStockSharesOutstanding.json) · [SalesRevenueNet](https://data.sec.gov/api/xbrl/companyconcept/CIK0000018230/us-gaap/SalesRevenueNet.json)

**A naive "one tag fits all" extractor fails immediately:** `us-gaap:StockholdersEquity` 404s for Caterpillar, and the tag most often recommended post-ASC 606 — `RevenueFromContractWithCustomerExcludingAssessedTax` — 404s for *both* Caterpillar and Deere, which use `us-gaap:Revenues`.

**Pitfall (a) — unclassified balance sheets.** Reg S-X Art. 5 § 210.5-02 does **not** mandate a current/non-current split: the caption list reads *"Current Assets, when appropriate"*, *"Total current assets, when appropriate"*, *"Total current liabilities, when appropriate"* ([17 CFR 210.5-02](https://www.ecfr.gov/current/title-17/chapter-II/part-210/subject-group-ECFR6a2b6c0d0b4e4b7/section-210.5-02)). Verified: **Berkshire Hathaway** (CIK 0001067983) `AssetsCurrent` 404; **Deere** — a US public *manufacturer* — `AssetsCurrent`/`LiabilitiesCurrent` 404, and its [most recent 10-K](https://www.sec.gov/Archives/edgar/data/315189/000110465925122321/de-20251102x10k.htm) contains the strings "Current assets", "Total current assets", "Current liabilities", "Total current liabilities" **zero times**. `frames` count for CY2024Q4I: `us-gaap:Assets` **6,271** vs `AssetsCurrent` **4,963** vs `LiabilitiesCurrent` **4,962** → **~21% of entities reporting total assets report no current-asset split** ([Assets frame](https://data.sec.gov/api/xbrl/frames/us-gaap/Assets/USD/CY2024Q4I.json), [AssetsCurrent frame](https://data.sec.gov/api/xbrl/frames/us-gaap/AssetsCurrent/USD/CY2024Q4I.json)). Caveat: a reproducible point-in-time coverage measure, not an SEC statistic; the population includes banks/insurers/funds where unclassified presentation is normal. **Consequence: X1 is not computable for these filers; treating missing `AssetsCurrent` as zero silently biases X1 downward.**

**Pitfall (b) — revenue tag churn.**

| Frame | `SalesRevenueNet` | `Revenues` | `RevenueFromContractWithCustomerExcludingAssessedTax` |
|---|---|---|---|
| CY2016 | 1,915 | 3,630 | 1,412 |
| CY2024 | **404 — tag absent** | 2,505 | 2,970 |

In CY2024 **no single revenue tag covers even half** the 6,271-entity asset universe, and the majority tag flipped between 2016 and 2024. X5 requires an explicit tag-precedence fallback chain.

**Pitfall (c) — dimensions.** The common claim that segment facts contaminate `companyfacts` is **wrong for the modern APIs**: the SEC filters to facts that *"Apply to the entire filing entity"*. Contamination risk is in **raw/bulk** data — the [Financial Statement Data Sets page](https://www.sec.gov/dera/data/financial-statement-data-sets) states that in December 2024 reprocessed sets *"used rendering data to determine which data points were presented on the primary financial statements… apart from the NUM file where a new field 'segments' has been added"*, whereas previously they held only *"non-dimensional"* data.

**Pitfall (d) — market value of equity.** No US-GAAP element carries a share price. [17 CFR § 232.406](https://www.ecfr.gov/current/title-17/chapter-II/part-232/section-232.406) requires filers to iXBRL-tag *"all of the information … required on the cover page"*; `dei:EntityCommonStockSharesOutstanding` is `periodType="instant"` in the [SEC DEI taxonomy schema](https://xbrl.sec.gov/dei/2025/dei-2025.xsd) under presentation group "995100 – Document – Cover". **The trap is the as-of date ≠ balance-sheet date.** Apple's FY2025 10-K cover-date share count is `2025-10-17` vs balance-sheet date `2025-09-27` ([dei probe](https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/dei/EntityCommonStockSharesOutstanding.json)). X4 must be assembled as (share count on *its own* `end` date) × (closing price on that same date).

**Pitfall (e) — EBIT is not a tag.** `us-gaap:Ebit` 404s; `us-gaap:OperatingIncomeLoss` is the usual proxy but is **optional and not reported every year** (Deere's most recent annual `OperatingIncomeLoss` fact is FY2024). Caterpillar has **no** `us-gaap:InterestExpense*` fact at all (404s), so the pre-tax-plus-interest alternative also breaks. Mixing EBIT definitions across a panel changes X3 partly by accounting-policy choice rather than credit quality.

### 6.2 UK Companies House iXBRL

**No structured financial-statement API exists.** The [Public Data API reference](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/reference) enumerates **34 operations** — registered office, profile, search, officers, registers, charges, filing history, insolvency, exemptions, UK establishments, PSCs — **none for accounts**. [Filing history](https://developer-specs.company-information.service.gov.uk/companies-house-public-data-api/resources/filinghistorylist?v=latest) items carry only `category`, `type`, `date`, `description`, `pages`, `barcode`, `paper_filed`, `annotations` and a `links.document_metadata` pointer. The [Document API](https://developer-specs.company-information.service.gov.uk/document-api/reference/document-metadata) returns metadata plus file downloads. Actual financial content is in the [Free Accounts Data Product](http://download.companieshouse.gov.uk/en_accountsdata.html) — iXBRL/XML instance documents — which covers only *"about **75% of the 2.2 million accounts we expect to be filed each year**"*.

**The critical gap is statutory, not technical.** **Companies Act 2006 s.444(5)(a)**: directors of a company subject to the small companies regime *"do not deliver to the registrar a copy of the company's profit and loss account"* ([legislation.gov.uk s.444](https://www.legislation.gov.uk/ukpga/2006/46/section/444)); micro-entities are carved into [s.443A](https://www.legislation.gov.uk/ukpga/2006/46/section/443A). GOV.UK: small companies can *"send abridged accounts"*; a micro-entity can *"send only your balance sheet"* ([GOV.UK](https://www.gov.uk/annual-accounts/microentities-small-and-dormant-companies)).

**Consequence:** for UK small/micro filers, **X3 (EBIT/TA) and X5 (Sales/TA) are structurally undefined** — the data is legally absent, not a parsing failure. X2 survives only if retained earnings is tagged on the filed balance sheet. X1 and X4 are the only reliably recoverable inputs. Any tool reporting a UK Z-score for such a company is imputing data or silently substituting a different model.

**Taxonomy:** FRC Taxonomy Suite, common "core" schema extended by IFRS / FRS 101 / FRS 102 entry points ([FRC Taxonomies](https://xbrl.frc.org.uk/); [FRC XBRL Tagging Guide](https://www.frc.org.uk/docs/8912/html/)). The guide warns companies *"may apply varying definitions to what is contained within sections such as operating income, non-operating income and **revenue**"*, so *"the summation implied in a taxonomy will not match that used in some specific accounts."* HMRC publishes [Corporation Tax technical specifications in XBRL and iXBRL](https://www.gov.uk/government/publications/corporation-tax-technical-specifications-xbrl-and-ixbrl), including "Joint filing validation checks".

### 6.3 Lease accounting (IFRS 16 / ASC 842)

[IFRS 16](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-16-leases/) requires a lessee to recognise a right-of-use asset and a lease liability; effective for periods beginning on or after 1 January 2019.

| Z input | Direction | Mechanism |
|---|---|---|
| Total assets | ↑ | ROU asset added |
| Total liabilities | ↑ | Lease liability added |
| Current liabilities | ↑ | Current portion of lease liability |
| Working capital | ↓ (usually) | CL addition exceeds any CA effect |
| EBIT | ↑ | Rent removed from operating expense; replaced by D&A/interest below the EBIT line |
| **X4 = MVE/TL** | **↓** | Denominator rises, numerator unchanged |

**Sourced magnitudes — [IASB, *IFRS 16 Leases — Effects Analysis*](https://www.ifrs.org/content/dam/ifrs/project/leases/ifrs/published-documents/ifrs16-effects-analysis.pdf):** estimated **understatement of long-term liabilities** for heavy off-balance-sheet lease users: **North America 22%, Europe 26%, Asia/Pacific 32%, Latin America 45%, Africa/Middle East 27%**. For distressed/insolvent retailers, discounted off-balance-sheet lease PV as a multiple of *reported* long-term debt: **Circuit City 65.86×** ($3,293M vs $50M), **Woolworths 10.90×**, **Clinton Cards 9.05×**, **HMV 7.03×**, **Borders 5.68×**, **Praktiker 3.69×** (5% discount rate).

**Post-adoption evidence — [IASB staff literature review, AP7F, March 2025](https://www.ifrs.org/content/dam/ifrs/meetings/2025/march/iasb/ap7f-review-academic-literature.pdf):** IFRS 16 *"significantly increased entities' assets and liabilities affecting entities' financial ratios (mainly leverage and profitability ratios)"*, and *"users initially reacted negatively to the capitalisation of operating leases because of the increase in leverage ratios."* **Ferreira, Landsman & Roundtree (2024)**, US sample of **2,822 entities 2018–2020**: entities *"reduced their liabilities unrelated to leases by 7% ± 10% as their lease-related liabilities increased by 5%"*. **Kim & Xie (2023)**, **24,945 entity-years 2012–2020**: faster adjustment to target leverage post-Topic 842. **Implication: reported post-adoption leverage *understates* the economic change, because firms actively re-contracted non-lease debt under covenant pressure — so cross-sectional comparability across the 2018/19 transition is worse than a naive "capitalise the leases" adjustment implies.**

**ASC 842 divergence:** FASB's **dual** model keeps the entire operating-lease cost in operating expense rather than splitting into depreciation + interest, so **the level and trend of EBIT differs between an IFRS 16 filer and an ASC 842 filer holding identical leases**, even though both capitalise the liability and so both show the same X4 denominator effect. Any cross-border Z-score is mixing two X3 treatments.

**Other items.** `RetainedEarningsAccumulatedDeficit` is signed: American Airlines reports **−6,732,000,000** at 2025-12-31 ([probe](https://data.sec.gov/api/xbrl/companyconcept/CIK0000006201/us-gaap/RetainedEarningsAccumulatedDeficit.json)). Buybacks deplete equity via treasury stock, not retained earnings: Boeing at 2025-12-31 shows RE **17,252,000,000**, `StockholdersEquity` **5,454,000,000**, `TreasuryStockCommonValue` **28,029,000,000** ([probe](https://data.sec.gov/api/xbrl/companyconcept/CIK0000012927/us-gaap/RetainedEarningsAccumulatedDeficit.json)) — so **X2 and equity-based ratios are not interchangeable proxies for buyback-heavy firms**.

### 6.4 Sub-agent UNVERIFIED list

1. **No accessible study quantifying IFRS 16 (or ASC 842) effects specifically on Altman Z-scores.** The one on-topic paper (Damascus University Journal, Arabic, Syrian telecom) was unreachable — [DOAJ](https://doaj.org/article/45cfed07359c4ce894ff6e23409f9149) returned HTTP 403 (Cloudflare) and the journal host timed out. The reported magnitudes are about **leverage/assets/liabilities**, not Z-scores.
2. **FASB primary sources unreachable:** `fasb.org` and `xbrl.fasb.org` returned HTTP 403 (Cloudflare). US-GAAP element names are therefore cited to SEC-hosted artefacts.
3. **No source quantifying ASC 606's distortion of revenue *levels* or of X5** (only tag churn and taxonomy-definition evidence).
4. **The ~21% unclassified figure is a `frames`-API computation, not an SEC statistic.**
5. **No official UK statement of what proportion of accounts are filed abridged/micro.**
6. **No Companies House API key**, so no live company responses were exercised.

### 6.5 Independent spot-check of §6

Re-probed live from my own session: Deere (CIK 0000315189) `AssetsCurrent` → **404**, `LiabilitiesCurrent` → **404**, `Assets` → **200** ✓ · `frames` `us-gaap/Assets/USD/CY2024Q4I` → **HTTP 200, n = 6,271** ✓ · Caterpillar `SalesRevenueNet` → 200 with `label` = **"Revenue, Net (Deprecated 2018-01-31)"** ✓. My Apple `dei` probe returned a newer as-of date (2026-07-17) than the FY2025 figure (2025-10-17) simply because I fetched the *latest* fact rather than the FY2025 filing — **consistent, not contradictory**.

**Note:** SEC.gov returns HTTP 403 to the plain `web_fetch` tool; SEC pages/APIs must be retrieved via Node `fetch` with a browser User-Agent.

---

## 5. Confidence and gaps

**Could not verify (explicit):**

1. **Altman (1968) journal paper — not opened.** Closed access. All 1968 attributions come from Altman's own 2000 revisiting paper, which reproduces the tables. Group-mean discrepancy (−0.29/+5.02 vs −0.25/+4.48) unresolved.
2. **Ohlson (1980) paper — not readable** (scanned image PDF, no OCR text layer). Ohlson's **actual Type I/Type II error rates and the cutoff at which they were measured are UNVERIFIED**; the **CLCA direction and the 6.03 coefficient** rest on secondary transcription with one source disagreeing.
3. **Zmijewski (1984) — nothing beyond one MSc thesis.** Original paper not opened; precise coefficients unverified; the JAR DOI only partially confirmed.
4. **Altman, Iwanicz-Drozdowska, Laitinen & Suvas (2017), JIFMA 28(2) 131–171** — the natural primary source for Z''/Z''-EM — is **closed access**, Cloudflare-blocked at Wiley, no OA repository copy per OpenAlex. **Z''-EM is not verified from a primary source.**
5. **The "declining accuracy" literature** — Begley/Ming/Watts (1996), Grice & Ingram (2001), Grice & Dugan (2003), Shumway (2001), Hillegeist et al. (2004), Agarwal & Taffler (2008) — a dedicated subagent was **still running** when this revision was written; findings are not included. Everything attributed to those authors above is quoted *via* other sources and marked as such.
6. **Ohlson O-score inputs from XBRL/iXBRL — not researched.** §6 covers only Altman Z inputs. The GNP price-level index and FFO remain **UNVERIFIED** for computability.
7. **IFRS 16 / ASC 842 effect on Z-scores specifically — UNVERIFIED.** Magnitudes for leverage/assets are sourced; no Z-score-specific number exists in the opened literature.
8. **Tooling limitation:** `web_fetch` cannot parse PDFs; I downloaded and text-extracted PDFs directly (Node + custom LZW/Flate/ASCII85 decoders). Subset-font PDFs yield scrambled or dropped text (this is why the leading `6.56` is missing from both Z'' PDF sources); scanned PDFs with no text layer are unreadable; where extracted numbers looked implausible (`0.603`), I flagged the conflict rather than silently correcting it.

**Suggested next steps:** (i) obtain Altman et al. (2017) JIFMA via library/ILL to settle Z''-EM from primary source; (ii) obtain Ohlson (1980) and Zmijewski (1984) via library/ILL for true error rates and coefficients; (iii) collect the outstanding out-of-sample-evidence subagent report.
