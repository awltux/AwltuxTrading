# Textual & Vocal Signals in Earnings Calls, MD&A and Forward-Looking Statements
### A source-grounded review, with verified citations and an explicit UNVERIFIED list

**Method note (read first).** Every citation, sample figure and effect size below is taken from a page this session actually retrieved with the fetch tool, and each is tied to a URL in the FETCH LOG. Where the fetch tool could not reach a source (Wiley, ScienceDirect, AAA, SSRN, SciSpace and EBSCO all returned 403/CAPTCHA), I say so and mark the missing detail **UNVERIFIED** rather than filling it from memory. PDFs are not directly fetchable by the tool, so PDFs were retrieved through the `r.jina.ai` text-extraction proxy; that works on ordinary web PDFs but **not** on Cloudflare-protected publisher pages (Wiley).

Two consequences for the reader:
- **Abstract-level evidence** is labelled as such. Several core papers are closed access, so their exact regression tables could not be read. What is cited from them is what the publisher/RePEc abstract states.
- Numbers that a published abstract reports (e.g. "11% better than chance") are reproduced as the authors' reported numbers; they are not independently recomputed here.

---

## 0. Corrections to the premises in the research brief (accuracy-critical)

These matter because the reader will follow the links.

| Brief said | Verified fact | Source |
|---|---|---|
| Davis, Piger & Sedor (2012) "Beyond the Numbers" — *Accounting Review* | Published in **Contemporary Accounting Research**, 29(3), 845–868 (online 2011; issue 2012). | OpenAlex W2334959554; Unpaywall record for 10.1111/j.1911-3846.2011.01130.x |
| Mayew & Venkatachalam (2012) "The Power of Voice" — *Accounting Review* | Published in **The Journal of Finance**, 67(1), 1–43 (2012). DOI 10.1111/j.1540-6261.2011.01705.x. (RePEc lists page range 1–44.) | OpenAlex W2075051605; RePEc handle `bla:jfinan:v:67:y:2012:i:1:p:1-44` |
| "Hirst, Koonce & Venkatachaman (2008) review of forward-looking statements" | Actual title: **"Management Earnings Forecasts: A Review and Framework"**, *Accounting Horizons*, 22(3), 315–338. It is a review of **management earnings forecasts**, not of forward-looking statements generally. | OpenAlex W3122154355 |
| Larcker & Zakolyukina (2012) effect "AUC/classification accuracy" | The published paper reports **accuracy relative to a random guess (6–16%)**, not an AUC. The working-paper version reports 4–6% and "50%–65% accuracy". Do not attribute an AUC to this paper. | EconPapers abstracts (WP and published) |

Also note: the working-paper and published abstracts of **Mayew & Venkatachalam** differ in emphasis. The 2008 working paper (which I read in full) studies a 615-call sample and a 180-day hedge portfolio. The published *Journal of Finance* abstract instead emphasises analysts' forecast revisions and stock-recommendation changes. Both are reported below in the relevant section.

---

## 1. Management tone in earnings releases / calls / MD&A and future performance

### 1.1 Davis, Piger & Sedor — "Beyond the Numbers"

- **Signal / measure:** Level of optimistic and pessimistic language in the **earnings press release**, measured with textual-analysis software (DICTION, per their own and Mayew & Venkatachalam's description of the paper).
- **Origin:** Davis, A. K., Piger, J. M., & Sedor, L. M. Working paper 2006-005, Federal Reserve Bank of St. Louis (January 2006), DOI 10.20955/wp.2006.005; published as *Beyond the Numbers: Measuring the Information Content of Earnings Press Release Language*, **Contemporary Accounting Research 29(3), 845–868**.
- **Sample (verified from the abstract):** **approximately 24,000 earnings press releases, 1998–2003** (US).
- **Reported effect (verified, abstract-level):** "a positive (negative) association between optimistic (pessimistic) language usage and future firm performance and a significant incremental market response to optimistic and pessimistic language usage in earnings press releases." The authors' conclusion is that managers use language to convey **credible** information, not cheap talk.
- **Effect size:** the specific coefficient / return spread is in the body of the paper, which is closed access. **UNVERIFIED at numeric level** — I could read only the FRASER item page (a page-image viewer, no OCR text layer) and the RePEc abstract.
- **Replication / decay:** no formal replication located in this session. **UNVERIFIED.**
- **Caveats:** (i) the frequently cited "24,000 press releases, 1998–2003" figure belongs to the 2006 working paper; the CAR version's sample window should be checked against the published article; (ii) endogeneity — good language and good future performance may both be driven by managers' private information, so "language causes returns" is not established.

### 1.2 Price, Doran, Peterson & Bliss — conference-call tone and returns

- **Signal / measure:** Conference-call **linguistic tone** via computer-aided content analysis, with a **context-specific (finance-tailored) dictionary** benchmarked against the general **Harvard IV-4 Psychosocial** dictionary. Separates the presentation from the **Q&A** section.
- **Origin:** Price, S. M., Doran, J. S., Peterson, D. R., & Bliss, B. A. (2012), *Journal of Banking & Finance* **36(4), 992–1011**.
- **Sample:** not stated in the abstract. **UNVERIFIED** (period/N).
- **Reported effect (verified, abstract-level):**
  - Call linguistic tone is a **significant predictor of abnormal returns and trading volume**.
  - **Tone dominates earnings surprise over the 60 trading days following the call** (i.e. it helps explain post-earnings-announcement drift).
  - The **Q&A portion has incremental explanatory power for PEAD**, and this significance is "primarily concentrated in firms that do not pay dividends" (interpreted as differences in cash-flow uncertainty).
  - A **context-specific dictionary is more powerful than Harvard IV-4**.
- **Numeric effect size:** **UNVERIFIED** (closed access).
- **Replication / decay:** useful modern evidence exists. An arXiv preprint (Sidhu, Fan & Pishgar, 14 Apr 2026) parses **6.5 million sentences from 16,428 S&P 500 quarterly earnings call transcripts, 2015–2025** with **FinBERT** and reports that "FinBERT section-weighted sentiment **entirely subsumes the Loughran–McDonald dictionary approach** (FinBERT t = 5.90; LM t = 0.86 in the combined specification)." This is consistent with Price et al.'s dictionary point, extended to transformer models. **Caveat: this is a non-peer-reviewed preprint with only 16 references; treat as provisional.**
- **Caveats:** dictionary choice materially changes results; reverse causality (tone responding to the same information that moves prices) is the standard identification worry; the authors' own dictionary is not the Loughran–McDonald list, so results are not directly comparable across studies.

### 1.3 Larcker & Zakolyukina — detecting deception in calls

- **Signal / measure:** **Linguistic-based classification models** of the **Q&A section** of quarterly calls, built on word categories from prior psychology/linguistics deception research (LIWC-family categories). Calls are labelled "truthful" or "deceptive" using **subsequent financial restatements** plus severity criteria.
- **Origin:** Larcker, D. F., & Zakolyukina, A. A. (2012), *Detecting Deceptive Discussions in Conference Calls*, **Journal of Accounting Research 50(2), 495–540**. Working paper: Stanford GSB Research Paper 2060 (July 2010).
- **Reported effect (verified):**
  - **Working paper (2010):** out-of-sample performance "significantly better than random by **4%–6%** (with **50%–65% accuracy**)" and a significant improvement over a model based on **discretionary accruals** and traditional controls.
  - **Published version (2012):** out-of-sample performance "significantly better than a random guess by **6–16%**", "at least equivalent to models based on financial and accounting variables", and — the headline economic result — "a portfolio formed from firms with the highest deception scores from **CFO** narratives produces an **annualized alpha of between −4% and −11%**."
  - **Language markers:** deceptive executives use more **references to general knowledge**, fewer **non-extreme positive emotions**, fewer **references to shareholder value**; deceptive CEOs use more **extreme positive emotion** and fewer **anxiety words** (published version). The WP adds fewer self-references, more third-person plural/impersonal pronouns, fewer extreme negative emotions, and fewer certainty/hesitation words.
- **Caveats (important):**
  - **Labels come from restatements**, which are a noisy and partial proxy for deception; the paper's own framing is "accuracy better than chance", i.e. modest classification performance, not a reliable lie detector.
  - **Reverse causality / selection:** firms that restate differ from firms that do not on many dimensions.
  - The 4–6% vs 6–16% divergence between WP and published version shows how sensitive the metric is to specification — do **not** quote one without the other.
- **Replication:** there is a published **discussion** of the paper in JAR (found in search results at `onlinelibrary.wiley.com/doi/10.1111/j.1475-679X.2012.00448.x`) but it is behind Cloudflare and I could not fetch it. **UNVERIFIED.**
- **Citation counts (as fetched):** the two RePEc records list **9 citations** (2010 WP) and **138 citations** (2012 article). These are RePEc-counted only, not total citations.

### 1.4 Related tone work located but not fully read

- **Huang, Teoh & Zhang "Tone management" (TAR 2014)** — referenced in the Bozanic et al. reference list (Huang, X. et al., TAR 89(6), 2151, "Evidence on the information content of text in analyst reports" is the item actually listed; a separate "tone management" paper was **not** verified here). **UNVERIFIED.**
- **Muslu, Radhakrishnan, Subramanyam & Lim (2015)**, *Forward-Looking MD&A Disclosures and the Information Environment*, **Management Science 61(5), 931–948** — see §4.

---

## 2. Q&A dynamics — analyst question evasion / management "dodge"

### 2.1 Hollander, Pronk & Roelofsen (2010) — the foundational evasion measure

- **Signal / measure:** Whether the manager **fails to answer an analyst's question** during the Q&A portion of the conference call — i.e. **silence / evasion** rather than the wording of the answer.
- **Origin:** Hollander, S., Pronk, M., & Roelofsen, E. (2010), *Does Silence Speak? An Empirical Analysis of Disclosure Choices During Conference Calls*, **Journal of Accounting Research 48(3), 531–563**.
- **Sample:** not given in the abstract. **UNVERIFIED.**
- **Reported effect (verified from the abstract):**
  - "managers regularly leave participants on the conference call in the dark by not answering their questions";
  - best predictors of an unanswered question: **firm size, CEO stock-price-based incentives, company age, firm performance, litigation risk, and whether analysts are actively involved during Q&A**;
  - "**strong support for the assumption maintained in the literature that investors interpret silence negatively. That is, investors seem to interpret no news as bad news.**"
- **Numeric effect size (return spread, t-stat):** **UNVERIFIED** — closed access; not in the abstract.
- **Citations (as fetched):** RePEc/CitEc counts **109** citations.
- **Follow-up / partial challenge:**
  - **Gow, Larcker & Zakolyukina (2021)**, *Non-Answers During Conference Calls*, **JAR 59(4), 1349–1384** — a *linguistic* non-answer measure at the **question level** (not the call level). Verified from the abstract: **about 11% of analyst questions elicit non-answers**, a rate "stable over time and similar across industries"; non-answers are more likely when the analyst's **question tone is negative**, and when the question has **greater uncertainty, greater complexity, or requests more detail**; performance-related questions trigger more non-answers, but **this association is weaker when performance news is favourable**; questions about **proprietary information** trigger non-answers, more so when **competition is more intense**. The WP version adds: firms disclose less when competition is more intense but **more prior to raising capital**; and firms are **less** likely to answer future-performance questions shortly before equity/debt offerings when legal liability is higher. RePEc lists **14 citations** for the published article and **1** for the WP — i.e. a relatively young literature.
  - **Bamber & Nappert (2025)**, *Can we explain managerial non-answers during conference call Q&As?*, **Contemporary Accounting Research 42(2), 1079–1105** — a **conceptual/social-interactionist critique**. Verified abstract: accounting scholars have suggested that avoiding answers "is ill-advised and that non-answers signal to investors the suppression of bad news"; the authors "demonstrate that this argument lacks nuance" and argue "answers and non-answers are not necessarily **mutually exclusive**… they are **codependent**", proposing three explanations for non-answers — **defensive, reflective, and negotiative**. They highlight a **communication gap** between management, the intermediary (the analyst) and the investor, implying that the "silence = bad news" reading is not universally warranted.
- **Effect sizes / returns:** no return-predictability effect size for evasion was verified in this session (Hollander et al.'s own market test is the only one located, and it is closed access). **UNVERIFIED.**
- **Verdict on survival:** the *existence* of the evasion phenomenon replicates strongly (Hollander 2010 at call level; Gow et al. 2021 at question level, with a stable ~11% base rate). The *interpretation* that silence is a clean bad-news signal is **actively contested** as of 2025. Any pipeline treating non-answers as a bearish signal should be calibrated to the 11% base rate, not 50%, and should expect a large false-positive population.

### 2.2 Analyst-question tone and management linguistic behaviour

- The Gow et al. (2021) result that **negative-toned analyst questions predict non-answers** is the cleanest verified link between analyst question tone and management response behaviour (abstract-level).
- **Bushee & Huang (2024)**, *Do Analysts and Investors Efficiently Respond to Managerial Linguistic Complexity during Conference Calls?*, **The Accounting Review 99(4), 143–168**. Verified abstract: managerial **Fog** during the call is a signal of private information transmitted through the manager's **willingness to engage with analyst questions**; informative (obfuscatory) Fog predicts **positive (negative) future earnings growth**; analysts revise for both signals, but **investors correctly interpret only obfuscation on the call**, with a **delayed price reaction to informative Fog**; when **buy-side** investors ask the questions, the price reaction is efficient. This is a *text-only, filings-and-transcripts-feasible* signal — relevant to your pipeline constraint.
- **"Linguistic style matching" between analysts and managers:** I did **not** locate and verify a specific peer-reviewed paper on analyst–manager language style matching in this session. **UNVERIFIED — no source cited.**

---

## 3. Vocal / behavioural markers (audio) — and the feasibility flag

**Feasibility flag up front:** every result in this section requires the **conference-call audio file**, not the transcript. They are therefore **out of reach for a pipeline limited to filing text, news headlines and article snippets**, unless audio is separately licensed (e.g. from call-transcript vendors that also supply recordings). Additionally, both studies below use **proprietary, closed-source vocal-emotion software (Nemesysco Layered Voice Analysis, "LVA")**, which one published critique argues is scientifically invalid (see §3.3).

### 3.1 Mayew & Venkatachalam — "The Power of Voice"

- **Signal / measure:** **Positive affect (PAFF)** and **negative affect (NAFF)**, measured as the percentage of CEO/CFO spoken audio with LVA Emotion Level above 110 (PAFF) and Cognition Level above 120 (NAFF), applied to **conference-call audio**.
- **Origin:** Mayew, W. J., & Venkatachalam, M. (2012), **The Journal of Finance 67(1), 1–43**. (Working paper dated 21 July 2008, which I read in full.)
- **Sample (verified from the working-paper text and Table 1):** **615 fiscal-year-2006 Q4 earnings conference calls occurring between 1 January and 31 March 2007**. Table 1 Panel B benchmarks the industry composition against **22,633 Compustat firms**. The authors describe their evidence as based on "a small sample of firms".
- **Reported effects (verified, working-paper version):**
  - **NAFF → future earnings news:** in logistic regressions of meeting/beating one quarter ahead, the NAFF coefficient is **−2.83 (p<0.05, SE 1.41)** for the analyst benchmark and **−2.73 (p<0.05)** for the seasonal-earnings benchmark; **−2.64 (p<0.05, two quarters ahead)** and **−3.89 (p<0.01, three quarters ahead)**. Pseudo-R² 5.2%–11.6%. **PAFF is statistically insignificant throughout.**
  - **Corrected**: controls include the negative-word percentage (NEGWORDS) from the transcript, so the vocal effect is incremental to linguistic content.
  - **Hedge portfolio:** "A hedge strategy based on decile ranks of negative affect generates **abnormal returns of about 9% over 180 trading days**, which is incremental to and statistically equivalent to the hedge returns generated using linguistic content."
  - Contemporaneous 3-day CAR is **positively** associated with negative affect (the authors call this "a puzzling finding").
  - Analysts do **not** revise next-quarter forecasts in response to NAFF.
- **Published version abstract (verified separately, from OpenAlex):** "when managers are scrutinized by analysts during conference calls, positive and negative affects displayed by managers are informative about the firm's financial future. Analysts do not incorporate this information when forecasting near-term earnings. When making stock recommendation changes, however, [analysts respond to] positive but not negative affect." **The published framing is about analysts' recommendation changes, not the 180-day hedge return** — a genuine discrepancy between the WP and the published paper that the reader should know about before citing "9% in 180 days".
- **Citations (as fetched):** OpenAlex reports **683** citing works.
- **Replication:** none located. **UNVERIFIED.**

### 3.2 Hobson, Mayew & Venkatachalam — speech and financial misreporting

- **Signal / measure:** **Vocal markers of cognitive dissonance** generated by automated vocal-emotion software applied to **CEO speech during earnings conference calls**.
- **Origin:** Hobson, J. L., Mayew, W. J., & Venkatachalam, M. (2012), *Analyzing Speech to Detect Financial Misreporting*, **Journal of Accounting Research 50(2), 349–392**.
- **Sample:** not stated in the abstract. **UNVERIFIED (N and period).**
- **Reported effect (verified, abstract-level):**
  - Construct validity: software dissonance markers are **positively associated** with four laboratory-obtained dissonance-from-misreporting proxies.
  - Applied to CEO speech, vocal dissonance markers are **positively associated with the likelihood of "irregularity" restatements**.
  - **"The diagnostic accuracy levels are 11% better than chance"**, and of **similar magnitude to models based solely on financial accounting information**.
  - The association **survives controls for financial-accounting and linguistic-based predictors**.
- **Caveats:** (i) audio required; (ii) **proprietary LVA software** — the authors declare no financial interest in the software manufacturer, which is worth noting given §3.3; (iii) "11% better than chance" is a modest classification gain, not a forensic-grade detector; (iv) a JAR **discussion** of the paper exists (`onlinelibrary.wiley.com/doi/abs/10.1111/j.1475-679X.2012.00451.x`) but is closed. **UNVERIFIED.**
- **Citations (as fetched):** RePEc/CitEc counts **89**.

### 3.3 The published scientific critique of the LVA measure (do not omit this)

- **Lacerda, F. P. (2012)**, *Money Talks: The Power of Voice — A critical review of Mayew and Venkatachalam's "The Power of Voice: Managerial Affective States and Future Firm Performance"* (Stockholm University; OpenAlex W75960191).
- **Verified abstract:** the paper "argues that the results presented by Mayew and Venkatachalam … **are void because the authors used an irrelevant technology (LVA technology, Nemesysco) that cannot measure emotions conveyed by voice and therefore does not produce valid results**. The paper explains why LVA cannot work for this problem and suggests that subscribing to this methodology **damages the reputation of finance and banking research**. The authors are encouraged to reanalyze their speech materials using appropriate scientific methods to measure meaningful acoustic correlates of speakers' voices."
- **Implication:** any downstream use of LVA-derived "vocal affect" or "vocal dissonance" numbers should carry this critique. The independent, acoustically-validated route (pitch, jitter, speech rate, pauses) is the alternative the critique points to — but I did **not** verify a replication using such features here. **UNVERIFIED.**
- Note the original Stockholm University PDF URL returned **404**; the abstract above is from the OpenAlex record.

---

## 4. Forward-looking statements and guidance language

### 4.1 Li (2010) — naive Bayesian classification of FLS

- **Signal / measure:** **Forward-looking statements (FLS)** in the **MD&A** of **10-K and 10-Q** filings, classified by (1) **tone** (positive vs negative) and (2) **content** (profitability, operations, liquidity, etc.) using a **Naïve Bayesian machine-learning algorithm** trained on hand-coded sentences.
- **Origin:** Li, F. (2010), *The Information Content of Forward-Looking Statements in Corporate Filings — A Naïve Bayesian Machine Learning Approach*, **Journal of Accounting Research 48(5), 1049–1102**.
- **Sample (verified from the abstract):** **30,000 randomly-selected FLS sentences manually categorised** as training data; the classifier is then applied to classify the tone/content of **"about 13 million [sentences/statements] … more than 140,000 [filings] between 1994 and 2007."** (The exact referent of "13 million" vs "140,000" is ambiguous in the inverted abstract text — **the split should be confirmed against the paper before quoting.**)
- **Reported effects (verified, abstract-level):**
  - **Determinants:** positive FLS are more frequent for firms with **better current performance, lower accruals, smaller size, lower market-to-book, less return volatility, lower MD&A Fog index, and longer history.**
  - **Predictive content:** "The **average tone of FLS is positively associated with future earnings** even after controlling for other determinants of future performance."
  - **Mispricing:** FLS tone "seems to **mitigate the mispricing of accruals**"; in particular, when managers "**warn**" about future performance implications of accruals, the accrual mispricing is weaker.
  - **Regulation:** despite increased regulation of MD&A disclosures, "there is **no systematic change in the information content of MD&As over time**."
  - **Dictionary benchmark (a negative result worth citing):** tone measures based on the three commonly used dictionaries (**Diction, General Inquirer, LIWC**) "**do not predict future returns**", which the author says suggests these dictionaries "might not work as well" for corporate filings.
- **Effect size (incremental R², accuracy):** **UNVERIFIED.** Semantic Scholar's record had the abstract elided by the publisher and returned only a TLDR confirming the determinants; Unpaywall confirms the article is **closed** with **no OA repository copy**. Do not quote an R² or accuracy figure for this paper.
- **Citation counts (as fetched):** OpenAlex reports **1,433** citing works; Semantic Scholar reports **1,184**. Cite the source of whichever number you use.
- **Replication / decay:** the "no systematic change over time" finding is itself a within-sample statement, not a post-publication replication. No replication located. **UNVERIFIED.**

### 4.2 Bozanic, Roulstone & Van Buskirk (2018) — how much guidance is in the *text* vs the *numbers*

- **Signal / measure:** FLS identified in firms' disclosures and split into **"forecast-like"** (quantitative statements about earnings) and **"other", non-forecast-like FLS**.
- **Origin:** Bozanic, Z., Roulstone, D. T., & Van Buskirk, A. (2018), *Management earnings forecasts and other forward-looking statements*, **Journal of Accounting and Economics 65(1), 1–20** (Crossref prints issue 1, pages 1–20).
- **Reported effects (verified, abstract-level):**
  - Like earnings forecasts, **other FLS generate significant investor and analyst responses**.
  - **Unlike** earnings forecasts, other FLS are **issued more frequently when uncertainty is higher**.
  - Earnings-related FLS are **more sensitive to uncertainty** than quantitative statements, "suggesting that managers are more likely to alter the **content** than the **form** of FLS when uncertainty is higher."
  - Conclusion: "incorporating other FLS into empirical measures provides a more comprehensive proxy for firms' voluntary disclosures."
- **How much of guidance is textual?** The Call et al. (2024) survey (below) supplies the verified benchmark: using the **Bozanic–Roulstone–Van Buskirk approach** to count FLS sentences in earnings-announcement press releases, **51.9% of surveyed firms have more FLS than the maximum number of self-reported guidance metrics**; firms that report issuing **no** guidance still have a mean of **6.0 FLS**; and the count of self-reported guidance metrics is **essentially uncorrelated with the number of FLS (correlation 0.02, p = 0.79)**. The authors' conclusion: "**FLS and guidance are distinct measures.**"
- **Effect size:** the underlying market-reaction coefficients are in the paper (closed). **UNVERIFIED numerically.**
- **Citations (as fetched):** Crossref reports **254** references-by-count (i.e. cited-by 254); OpenAlex reports **271**; RePEc/CitEc reports **44**. Use one and name it.

### 4.3 Hirst, Koonce & Venkataraman (2008) — the framework review

- **Origin:** Hirst, D. E., Koonce, L., & Venkataraman, S. (2008), *Management Earnings Forecasts: A Review and Framework*, **Accounting Horizons 22(3), 315–338**.
- **Reported content (verified, abstract-level; OpenAlex abstract field):** the paper categorises management forecasts as having **three components — antecedents, characteristics, and consequences**. Three conclusions: (1) **forecast characteristics are the least understood** component in both theory and empirics, even though they are the component **managers control most**; (2) prior research typically studies **one antecedent or characteristic at a time** and ignores **interactions among components**; (3) prior research **ignores the iterative nature** of forecasts, i.e. current-period consequences influence the antecedents and characteristics chosen in **subsequent** periods. Implications are drawn for researchers, educators, managers, investors and regulators.
- **Citation count (as fetched):** OpenAlex reports **611**.
- **Effect size:** it is a review, so none. Paywalled at AAA (403). **Abstract-level evidence only.**

### 4.4 Muslu, Radhakrishnan, Subramanyam & Lim (2015) — FLS in MD&A and information environment

- **Origin:** *Forward-Looking MD&A Disclosures and the Information Environment*, **Management Science 61(5), 931–948** (published online 2014).
- **Reported effects (verified, abstract-level):** firms make **more forward-looking MD&A disclosures when their stock prices have lower efficiency**, i.e. when prices poorly reflect future earnings information; **greater levels of FLS help improve price efficiency yet are unable to completely mitigate it** for such firms; these findings are **stronger for operations-related FLS** and for disclosures **made prior to 2000**.
- **Use for your purposes:** this is a *text-only* signal (10-K MD&A) with a clear interpretation — FLS volume proxies for management's attempt to remedy poor price informativeness, and it is **partially, not fully, effective**.
- **Citation count (as fetched):** OpenAlex reports **407**.

### 4.5 Thomas, Wang & Zhang (2024) — a caution on FLS usefulness over time

- **Origin:** *Algorithmic Trading and Forward-Looking MD&A Disclosures*, **Journal of Accounting Research 62(4), 1533–1569** (2024).
- **Reported effect (verified, abstract-level):** **algorithmic trading (AT) relates negatively to year-over-year modifications in forward-looking MD&A disclosures**. Interpretation: AT **reduces investors' demand for fundamental information**, which reduces managers' incentives to supply costly forward-looking disclosure. The relation is **more pronounced for firms with larger earnings surprises and for loss firms**, and is robust to using the **SEC's Tick Size Pilot Program** as an exogenous shock.
- **Relevance:** evidence that the *supply* of forward-looking narrative is endogenous to the market microstructure — i.e. FLS volume is not a stable, structural signal through time.

---

## 5. Is forward-looking language "cheap talk"? Guidance reliability and the guidance game

### 5.1 Koo & Yeung — direct cheap-talk test on long-horizon growth forecasts

- **Origin:** Koo, D. S. (Illinois), & Yeung, P. E. (Cornell), *Managers' Forecasts of Long-Term Growth in Earnings: New Information or Cheap Talk?* — **working paper** ("Very preliminary. Please do not circulate or cite without permission."). This status must be disclosed if cited.
- **Sample (verified from Table 1):** management forecasts of **annual EPS issued 2001–2009** by Compustat/CRSP firms: 10,267 unbundled forecasts from 1,996 firms, narrowing to **4,730 press releases from 1,118 firms** in the final sample; **748 of those contain a growth forecast (15.81%)** and **344 contain an EPS growth forecast (7.27%)**. **Critically, only 15% of sample firms have more than one growth forecast in the sample.**
- **Reported effects (verified, from the paper's tables and text):**
  - **Bias:** mean management growth forecast **MFG = 15.61%** vs mean **realised future growth RFG = 2.91%** — the forecast is about **five times** realised growth. Mean bias (MFG − RFG) = **12.70% (significant)**; mean absolute error 18.94%.
  - **News:** **234 good-news vs 107 bad-news forecasts** out of 341 (68.62% good news).
  - **Informativeness:** regressing (RFG − AFG) on forecast news gives **MFGNews coefficient 0.508, t = 3.59**, adjusted R² 6.62% — i.e. growth forecasts do carry incremental information.
  - **But the average masks the split:** **good-news forecasts are uninformative cheap talk**; **bad-news forecasts remain informative** despite also being optimistically biased.
  - **Investor response:** investors react significantly to **good-news** growth forecasts (the uninformative ones) and **not** to **bad-news** forecasts (the informative ones); mispricing **is not corrected until year +2**, when the projected growth fails to materialise. Analysts partially, but not fully, understand the asymmetry (they over-react to good news, under-react to bad news).
  - Managers appear to **overweight historical growth**, which is **negatively** associated with realised future growth (HG coefficient on RFG = −0.091, t = −4.14).
- **Caveats:** hand-collected, small (344 obs), preliminary, one 9-year US window; the good/bad-news split reduces power further. But this is the cleanest *direct* cheap-talk test located.

### 5.2 Call, Hribar, Skinner & Volant (2024) — what managers themselves say

- **Origin:** *Corporate managers' perspectives on forward-looking guidance: Survey evidence*, **Journal of Accounting and Economics 78(2)** (2024). The version I read is the September 2023 working paper (MIT Sloan PDF).
- **Sample:** **357 corporate managers surveyed** (launched 2–3 June 2021, closed 25 June 2021), **response rate 9.8%**, from a subject pool of **3,643 email addresses at 3,606 US-listed firms**; plus **nine in-depth interviews**.
- **Verified findings relevant to reliability and expectations management:**
  - **Conservative guidance is the norm:** **over 60% of managers say their internal projection lies ABOVE the midpoint of the published range**, and **fewer than 7% say it lies below**; a further **24%** say their internal expectation is above the **upper bound** of the range. This directly supports the "walk-down / beatable target" story and undercuts treating the guidance midpoint as the manager's expectation.
  - **Managers are miscalibrated:** almost **90%** say they are at least **70% confident** reported earnings will fall inside the initial range — yet historical data show reported earnings fall **inside the range only ~30% of the time** (Jensen & Plumlee 2020; Hribar et al. 2021 as cited by the authors), and **31%** for the surveyed firms themselves.
  - **Guidance is undercounted in databases:** **over 80% of respondents** say their firm guides, but **I/B/E/S reports guidance for only 58%** of those firms; median respondent guides **three metrics** vs a median of **one** in I/B/E/S.
  - **Motives:** the most-cited reasons are **satisfying analyst and investor demand** and **managing analysts' expectations** — i.e. expectations management is explicit, not inferred.
  - **Costs:** only **13%** of guiding managers worry about proprietary information leakage (only **6%** say proprietary costs would cause them to stop); only **9%** are "very much" concerned about shareholder litigation, versus **47%** of non-guiding managers.
  - **Benchmark hierarchy:** **79%** say it is very important to meet their **most recently issued guidance**, versus **62%** for the analyst consensus and **59%** for prior-year same-quarter earnings.
  - **Short-termism beliefs:** 41% (investor) and 37% (analyst) are very much concerned about short-termism *in others*, but only **9%** worry guidance distorts their own operating/investment decisions.
- **Caveats stated by the authors and worth repeating:** survey responses reflect **perceptions, not reality**; managers may answer to look good; question ordering may over-emphasise guidance; generalisability to the full population is not guaranteed.

### 5.3 Preussner & Aschauer (2022) — what the guidance literature as a whole says about accuracy

- **Origin:** Preussner, N. A., & Aschauer, E. (2022), *The Accuracy and Informativeness of Management Earnings Forecasts: A Review and Unifying Framework*, **Accounting Perspectives 21(2), 273–330**. **Open access (CC BY-NC-ND).**
- **Reported findings (verified from the full Crossref abstract):**
  - "Earnings forecasts tend to be **optimistically biased**, with a positive correlation with **forecast uncertainty, earnings flexibility, financial distress, investor sentiment, and the share-price dependency of managers' remuneration**."
  - "**Firm growth, legal liability, and litigation risk are significantly associated with forecast pessimism.**"
  - "MF **accuracy increases with previous forecast accuracy, firm size, analyst coverage, analyst agreement, management qualifications, and corporate governance level**."
  - "Investors **do not anticipate the full extent of predictable forecast bias**, leading to **systematic share price drifts** after the announcement of earnings forecasts and actual earnings."
  - Credibility can be enhanced by issuing **precise, bundled, and disaggregated** forecasts, but users "should carefully analyse forecast antecedents and characteristics to assess the direction and magnitude of expected MF bias."
- **Use:** this is the single best citable, open-access warrant for "guidance is systematically biased and the bias is not fully priced" — and it is a review, so it aggregates rather than adds a new point estimate.

### 5.4 Related guidance-game material located but not verified

- **Richardson, Teoh & Wysocki (2004)**, *The Walk-down to Beatable Analyst Forecasts: The Role of Equity Issuance and Insider Trading Incentives*, **Contemporary Accounting Research 21(4), 885–924** — located only via search-result metadata and the Call et al. reference list. Wiley page is Cloudflare-blocked. **Abstract not fetched; UNVERIFIED.**
- **Cotter, Tuna & Wysocki (2006)**, *Expectations Management and Beatable Targets*, **CAR 23(3), 593–624** — cited in Call et al. and Bozanic et al. reference lists with these page numbers; **not independently fetched. UNVERIFIED.**
- **Chen, Matsumoto & Rajgopal (2011)**, *Is silence golden? An empirical analysis of firms that stop giving quarterly earnings guidance*, **JAE 51(1–2), 134–150** — cited in the Bozanic et al. and Call et al. reference lists with these page numbers; **not independently fetched. UNVERIFIED.**

---

## 6. What this implies for a text-only pipeline (filings + headlines + article snippets)

1. **Feasible with your data:** press-release tone (Davis et al.), 10-K/10-Q MD&A FLS tone and content (Li 2010), FLS counts and forecast-like vs other FLS (Bozanic et al.), MD&A FLS volume (Muslu et al.), linguistic complexity/Fog in transcripts **if** you have transcripts (Bushee & Huang), and non-answer flags **if** you have transcripts (Gow et al.).
2. **Not feasible without audio:** all of §3 (Mayew & Venkatachalam; Hobson et al.). Speaker-identity/section weighting (arXiv 2604.13260) needs transcripts with speaker labels, not audio.
3. **Direction-of-sign warnings:**
   - Tone→future performance is reported as **positive** (good language, better future performance) — but the dictionary matters enormously, and Li (2010) finds **Diction / General Inquirer / LIWC tone do not predict future returns** at all.
   - Evasion/non-answers are **not** a clean bearish signal: the base rate is ~11% of questions, and the 2025 CAR critique argues the bad-news interpretation is theoretically under-specified.
   - **Guidance is conservative relative to the manager's own expectation** (>60% above midpoint), so the *midpoint* is a biased proxy for expectations — the upper bound is arguably better.
4. **Realistic effect sizes to build expectations around:** classification gains of **6–16% better than chance** (deception) and **11% better than chance** (vocal dissonance); a **2.03% monthly** long-short alpha (t = 6.49) in a 2026 preprint from section-weighted transformer sentiment; **~9% over 180 trading days** from a 615-call vocal-affect decile hedge (working-paper version only). These are small-to-moderate, and the preprint and the WP figures are **not peer-reviewed at the level quoted**.

---

## 7. Explicitly UNVERIFIED — what I could not confirm, and exactly what is missing

| Item | What is missing | Why |
|---|---|---|
| Davis, Piger & Sedor — numeric return spread / regression coefficient | Effect size for language→market reaction | Paper closed; FRASER copy is page images with no text layer |
| Hollander, Pronk & Roelofsen — sample size and return effect size | Market-reaction magnitude to unanswered questions | JAR closed access; only abstract reachable |
| Li (2010) — classifier accuracy, incremental R² | All numeric performance metrics | Closed; Semantic Scholar has abstract elided by publisher; no OA repository copy (Unpaywall) |
| Price, Doran, Peterson & Bliss — sample period/N and coefficient magnitudes | Sample and effect sizes | JBF closed access (ScienceDirect 403) |
| Hobson, Mayew & Venkatachalam — sample N and period | Sample size | JAR closed; only abstract reachable |
| Hirst, Koonce & Venkataraman (2008) | Any quantitative content | It is a review; AAA site returns Cloudflare 403; abstract obtained via OpenAlex only |
| Any formal post-publication **replication** of tone→returns | Replication study | None located in this session; do not assert that a replication exists |
| "Linguistic style matching" between analysts and managers | Any specific paper | No verified source located |
| Lacerda (2012) critique — full argument | Full text | Original Stockholm URL 404; DiVA redirect blocked; abstract obtained via OpenAlex |
| Discussion pieces (JAR discussions of Larcker & Zakolyukina 2012 and of Hobson et al. 2012) | Content | Wiley Cloudflare 403 |
| Richardson, Teoh & Wysocki (2004); Cotter et al. (2006); Chen et al. (2011) | Abstract-level confirmation | Only seen as reference-list entries in other papers' metadata; not independently fetched |

---

## FETCH LOG

Every URL below was successfully retrieved with the fetch tool during this session. (Wiley, ScienceDirect, AAA, SSRN, EBSCO, SciSpace and any CAPTCHA-gated page **failed** and are therefore excluded — no claim in this review rests on them.)

**Publisher-neutral metadata and abstract services**
1. `https://api.openalex.org/works?search=Information%20Content%20of%20Forward-Looking%20Statements%20in%20Corporate%20Filings&per-page=3` — confirmed Li (2010) is JAR 48(5) 1049–1102, 1,433 citations, and supplied his full abstract (30,000 coded sentences; 13M/140,000 filings; FLS tone predicts future earnings; Diction/General Inquirer/LIWC do not predict returns).
2. `https://api.openalex.org/works?filter=doi:10.1111/j.1911-3846.2011.01130.x|10.1016/j.jbankfin.2011.10.013|10.2308/accr-10169|10.1111/j.1475-679X.2011.00433.x|10.1016/j.jacceco.2017.11.008|10.2308/acch.2008.22.3.315|10.1111/1475-679X.12371&per-page=10&select=...` — confirmed bibliographic details for Davis (CAR 29(3) 845–868), Price (JBF 36(4) 992–1011), Hirst (Accounting Horizons 22(3) 315–338), Hobson (JAR 50(2) 349–392), Bozanic (JAE 65(1) 1–20), Gow (JAR 59(4) 1349–1384); note DOI `10.2308/accr-10169` returned **no** record, which is how the Mayew & Venkatachalam journal error surfaced.
3. `https://api.openalex.org/works?search=The%20Power%20of%20Voice%20Managerial%20Affective%20States%20and%20Future%20Firm%20Performance&per-page=2&select=...` — confirmed "The Power of Voice" is **The Journal of Finance 67(1), 1–43 (2012)**, gave the published abstract, and returned the Lacerda (2012) critique with its full abstract.
4. `https://api.openalex.org/works?search=Can%20we%20explain%20managerial%20non-answers%20during%20conference%20call&per-page=3&select=...` — confirmed Bamber & Nappert (2025) CAR 42(2) 1079–1105 with abstract, and Bushee & Huang (2024) TAR 99(4) 143–168 with abstract.
5. `https://api.openalex.org/works/doi:10.2308/acch.2008.22.3.315?select=...` — supplied the Hirst, Koonce & Venkataraman (2008) abstract and the 611 citation count.
6. `https://api.openalex.org/works?search=Forward-looking%20MD%26A%20disclosures%20and%20the%20information%20environment&per-page=2&select=...` — supplied the Muslu et al. (2015) abstract (Management Science 61(5) 931–948) and the Thomas, Wang & Zhang (2024) JAR abstract on algorithmic trading.
7. `https://api.crossref.org/works/10.1111/1911-3838.12294` — supplied the full open-access abstract of Preussner & Aschauer (2022), Accounting Perspectives 21(2) 273–330, including the bias/accuracy correlates and the post-forecast drift finding.
8. `https://api.crossref.org/works/10.1016/j.jacceco.2017.11.008` — confirmed Bozanic et al. page range 1–20 and its 48-item reference list (used only for locating other works).
9. `https://api.unpaywall.org/v2/10.1111/j.1475-679X.2011.00433.x?email=research@example.org` — established that Hobson et al. is **closed** with no repository copy.
10. `https://api.unpaywall.org/v2/10.1111/j.1911-3846.2011.01130.x?email=research@example.org` — established that the Davis et al. CAR article is **closed** and names the journal as Contemporary Accounting Research.
11. `https://api.unpaywall.org/v2/10.1111/j.1475-679X.2010.00365.x?email=research@example.org` — established that Hollander et al. is **closed** and confirmed author affiliations (Tilburg; Erasmus).
12. `https://api.unpaywall.org/v2/10.1111/j.1475-679X.2010.00382.x?email=research@example.org` — established that Li (2010) is **closed** with no OA copy.
13. `https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/j.1475-679X.2010.00382.x?fields=...` — returned a TLDR confirming Li (2010)'s determinants and confirmed the publisher **elided the abstract** and the PDF is CLOSED.

**RePEc / EconPapers / IDEAS abstract pages (used for verified abstracts)**
14. `https://ideas.repec.org/p/fip/fedlwp/2006-005.html` — Davis, Piger & Sedor (2006) WP abstract and full reference list; source of the "≈24,000 press releases, 1998–2003" sample.
15. `https://econpapers.repec.org/paper/eclstabus/2060.htm` — Larcker & Zakolyukina Stanford WP abstract (4–6% better than random; 50–65% accuracy).
16. `https://econpapers.repec.org/article/blajoares/v_3a50_3ay_3a2012_3ai_3a2_3ap_3a495-540.htm` — published Larcker & Zakolyukina abstract (6–16% better than random; CFO-portfolio alpha −4% to −11%); 138 RePEc citations.
17. `https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a3_3ap_3a531-563.htm` — Hollander, Pronk & Roelofsen abstract and 109 RePEc citations.
18. `https://econpapers.repec.org/paper/eclstabus/3760.htm` — Gow, Larcker & Zakolyukina working-paper abstract (11% non-answer rate; competition/offering effects).
19. `https://econpapers.repec.org/article/blajoares/v_3a59_3ay_3a2021_3ai_3a4_3ap_3a1349-1384.htm` — published Gow et al. abstract (question-tone, uncertainty, complexity, proprietary-information predictors); 14 RePEc citations.
20. `https://econpapers.repec.org/article/blajoares/v_3a50_3ay_3a2012_3ai_3a2_3ap_3a349-392.htm` — Hobson, Mayew & Venkatachalam abstract ("11% better than chance"); 89 RePEc citations.
21. `https://econpapers.repec.org/article/eeejaecon/v_3a65_3ay_3a2018_3ai_3a1_3ap_3a1-20.htm` — Bozanic et al. abstract (forecast-like vs other FLS).
22. `https://econpapers.repec.org/article/eeejbfina/v_3a36_3ay_3a2012_3ai_3a4_3ap_3a992-1011.htm` — Price, Doran, Peterson & Bliss abstract (tone dominates earnings surprise over 60 days; Q&A incremental for PEAD; non-dividend payers; custom dictionary beats Harvard IV-4); 169 RePEc citations.

**Full texts retrieved through the `r.jina.ai` text proxy**
23. `https://r.jina.ai/https://w4.stern.nyu.edu/emplibrary/thepowerofvoice.pdf` — the Mayew & Venkatachalam 2008 working paper in full: 615 FY2006-Q4 calls (1 Jan–31 Mar 2007), NAFF logit coefficients (−2.83**, −2.64**, −3.89***), insignificant PAFF, ~9% 180-day hedge return, and Table 1/2/3 details.
24. `https://r.jina.ai/https://www.stern.nyu.edu/sites/default/files/assets/documents/Eric%20Yeung.pdf` — the Koo & Yeung cheap-talk working paper in full: 4,730 forecasts from 1,118 firms (2001–2009), 344 growth forecasts, MFG 15.61% vs RFG 2.91%, MFGNews coefficient 0.508 (t = 3.59), good-news cheap talk vs informative bad news.
25. `https://r.jina.ai/http://mitsloan.mit.edu/sites/default/files/inline-files/Call_Hribar_Skinner_Volant.pdf` — the Call, Hribar, Skinner & Volant survey in full: 357 managers, 9.8% response rate, >60% guide above the midpoint, <7% below, 24% above the upper bound, ~30–31% of results land inside the range, 80% vs 58% database undercount, 79% guidance benchmark.
26. `https://r.jina.ai/https://fraser.stlouisfed.org/title/working-papers-federal-reserve-bank-st-louis-9029/beyond-numbers-analysis-optimistic-pessimistic-language-earnings-press-releases-716332` — rendered the FRASER landing page for the Davis et al. WP: confirmed the abstract, the January 2006 date, DOI 10.20955/wp.2006.005, and that the item is a **42-page page-image viewer with no text layer** (hence the UNVERIFIED effect size).
27. `https://r.jina.ai/https://care-mendoza.nd.edu/assets/152191/feng.pdf` — Feng Li's CARE 2010 conference presentation, "Financial Analysis and Forecasting Using Textual Data": documents the DICTION/General Inquirer dictionary weaknesses ("Downgrade is not a negative word in GI"), the naive-Bayes vs SVM trade-off and the over-fitting warning, and a worked press-release tone example (Ford 2000 10-K, "tone" = −0.62).

**Other direct HTML fetches**
28. `https://fraser.stlouisfed.org/title/.../beyond-numbers-analysis-optimistic-pessimistic-language-earnings-press-releases-716332` — the FRASER item page (direct, un-proxied), confirming the citation, authors (Davis, Sedor, Piger), January 2006 date and the "≈24,000 press releases 1998–2003" abstract.
29. `https://arxiv.org/abs/2604.13260` — abstract of "Which Voices Move Markets? Speaker Identity and the Cross-Section of Post-Earnings Returns" (Sidhu, Fan & Pishgar, 14 Apr 2026): 6.5M sentences, 16,428 S&P 500 call transcripts 2015–2025, out-of-sample Spearman IC 0.142 vs 0.115 in-sample, monthly long-short alpha 2.03% (t = 6.49), FinBERT t = 5.90 vs LM t = 0.86. Non-peer-reviewed preprint.
