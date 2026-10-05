# Textual/linguistic markers in company filings, and the empirical record of news signals

**Purpose.** Evidence review for an equity research tool that already extracts financial facts from SEC EDGAR filings and UK Companies House iXBRL accounts, and that has a sceptical news pipeline (source reliability registry, manipulation-technique detection, corroboration counting, syndication collapse). This report answers: *which language signals in company documents have real predictive evidence, and how much weight should news carry?*

**Scope of inputs available to the reader's system:** filing text (10-K/10-Q/annual reports), news headlines and article snippets. **No paid news feed, no conference-call transcripts, no audio, no tick data.**

---

## How to read the evidence grades

| Grade | Meaning |
|---|---|
| **A — Robust** | Multiple independent papers, large samples, replicated across settings, mechanism plausible, survives reasonable controls. |
| **B — Replicated but modest** | At least one strong paper plus at least one independent confirmation or extension; effect sizes are small in economic terms. |
| **C — Single-paper** | One credible study with a large sample; no independent replication located. Treat as a hypothesis. |
| **D — Contested** | Sources disagree, or a documented replication/critique failure exists. Report both sides. |
| **X — Not implementable here** | Evidence exists but requires data the pipeline does not have (audio, transcripts, licensed feeds). |

**Two methodological warnings that apply to the whole report, both from the field's own surveys:**

1. Loughran & McDonald's own survey of the field warns that "relative to quantitative methods traditionally used in accounting and finance, textual analysis is substantially less precise. Thus, understanding the art is of equal importance to understanding the science… we describe the nuances of the method and, as users of textual analysis, some of the tripwires in implementation." ([Loughran & McDonald 2016, *JAR* 54(4):1187–1230, abstract via EconPapers](https://econpapers.repec.org/article/blajoares/v_3a54_3ay_3a2016_3ai_3a4_3ap_3a1187-1230.htm))
2. Feng Li's own survey of the literature flags the publication-bias problem directly: "The selection bias in the publication process is perhaps the reason that we do not see more of such papers" — i.e. the published record overstates how reliably text predicts outcomes. He also lists endogeneity (omitted variables *and* reverse causality), the non-causal nature of readability→analyst results, and the fact that filings are written by "managers, auditors, lawyers, and public relations staff," as unresolved problems ([Li 2011, "Textual Analysis of Corporate Disclosures: A Survey of the Literature," *Journal of Accounting Literature*, PDF](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)).

**A note on how sources were read.** Publisher pages at Wiley, Elsevier/ScienceDirect, SSRN and AAA returned HTTP 403 to this environment, and `web_fetch` cannot parse PDFs directly. Where a paper is closed-access I verified its bibliographic record through [OpenAlex](https://api.openalex.org), [EconPapers/RePEc](https://econpapers.repec.org) or [Unpaywall](https://api.unpaywall.org), and obtained the **publisher abstract** via a metadata aggregator; those are labelled **[abstract-level]**. Where an open PDF or working-paper version exists, I read the full text via a text-extraction proxy (`r.jina.ai`) and label it **[full text]**. Every effect size reported below is quoted from a source I actually fetched, and every closed-access gap is marked **UNVERIFIED** rather than filled from memory. The fetch log is at the end.

---

## Summary table

| # | Signal | What it indicates (measured how) | Evidence | Implementation cost for this system |
|---|---|---|---|---|
| 1 | **Loughran-McDonald tone on 10-K** | Positive minus negative word counts, using finance-specific word lists; measures management's framing of the year | **A** (dictionary itself); **B** for return prediction | **Low.** Static word lists, free for academic use; licence needed for commercial use. Pure `count/total words`. |
| 2 | **Fog Index / readability of 10-K or MD&A** | Gunning-Fog = 0.4 × (words per sentence + % words ≥3 syllables); higher = harder | **B** (levels vs performance); **B** (obfuscation around earnings benchmarks) | **Low.** Requires sentence splitting + syllable counting. |
| 3 | **Year-over-year textual *similarity* (boilerplate/laziness)** | Cosine/Jaccard/"diff" between this year's and last year's filing or section | **A** — the strongest filing-level return result in this review | **Low–medium.** Need same-firm prior filing; section alignment (Item 1A, Item 7) is the fiddly part. |
| 4 | **Change-specific language** (risk-factor changes, CEO/CFO language, litigation language) | Whether the risk/executive/litigation language *changed* vs the prior filing | **B** — highest sub-signal in Lazy Prices but not independently replicated | **Medium.** Needs section tagging + a diff. |
| 5 | **MD&A tone *change*** | Tone this filing minus tone of prior filing, not tone level | **B** | **Low** once #1 exists — it is a difference. |
| 6 | **Linguistic imprecision / "weasel words"** | Share of words from a Wikipedia-weasel-tag-derived dictionary | **C** — single strong conference paper; sign is *counter-intuitive* (positive) | **Low.** Dictionary is not published (authors supply on request) — must rebuild from the described method. |
| 7 | **Uncertainty / weak-modal word density** | LM "uncertainty" and "weak modal" categories as % of words | **C** for returns; **B** for risk/volatility | **Free** with the LM dictionary (#1). |
| 8 | **Risk-factor disclosure *specificity*** | Algorithmic measure of how specific (vs generic) Item 1A is | **B** | **Medium–high.** Needs a specificity algorithm, not a word list. |
| 9 | **Forward-looking-statement (FLS) tone in MD&A** | Naïve-Bayes classifier over hand-labelled FLS sentences; % positive FLS | **B**, but the original used a *machine-learned* classifier, not a dictionary | **Medium.** Requires labelled training data or an LLM; the naive-Bayes recipe is public. |
| 10 | **Number of FLS / FLS volume** | Count/proportion of forward-looking sentences in MD&A | **C** | **Low–medium.** |
| 11 | **Guidance bias (management forecast vs realised)** | Forecast optimism measured against realisation | **B** as a documented bias; **A** as a survey finding on manager incentives | **Low** if guidance is in the filing text; UK guidance is sparse. |
| 12 | **Earnings-call Q&A evasion / non-answers** | Whether an analyst question is answered, coded at question level | **D** — contested as of 2025 | **X for this system** unless transcripts are added. |
| 13 | **Vocal / behavioural markers (pitch, hesitation, vocal dissonance)** | Extracted from call audio | **X** — and rests on proprietary software publicly criticised as invalid | **X.** No audio. |
| 14 | **News sentiment (daily, firm-specific)** | Positive/negative word share in news about a firm | *see Part B* | **Low** with headlines/snippets. |
| 15 | **Media attention / coverage volume** | Count of articles mentioning a firm | *see Part B* | **Low**, but coverage count is contaminated by reverse causality. |
| 16 | **Sensationalism / source-quality weighting** | Tabloid vs broadsheet, or a sensationalism score | *see Part B* | **Low–medium**, depends on registry quality. |
| 17 | **Stale-news / slow-diffusion decay** | Days since the underlying event; repeat/reprint detection | *see Part B* | **Medium** — needs event-timestamp and syndication collapse (already built). |

---

## Part A — Language and tone in company filings

### A1. The Loughran-McDonald financial sentiment dictionary

**What it is / how it is measured.** Word lists built from financial text, with seven sentiment categories: **negative, positive, uncertainty, litigious, strong modal, weak modal, constraining**, plus a complexity list. Because it is a *bag-of-words* count normalised by document length, implementation is trivial: `sum(indicators in category) / total words`.

**Originating paper.** Loughran & McDonald (2011), "When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks," *Journal of Finance* 66(1), 35–65. DOI [10.1111/j.1540-6261.2010.01625.x](https://doi.org/10.1111/j.1540-6261.2010.01625.x). **[abstract-level]**

**Why general-purpose sentiment dictionaries fail on financial text.** The paper's central result, quoted from the publisher abstract:

> "Previous research uses negative word counts to measure the tone of a text. We show that word lists developed for other disciplines misclassify common words in financial text. **In a large sample of 10-Ks during 1994 to 2008, almost three-fourths of the words identified as negative by the widely used Harvard Dictionary are words typically not considered negative in financial contexts.** We develop an alternative negative word list, along with five other word lists, that better reflect tone in financial text. We link the word lists to 10-K filing returns, trading volume, return volatility, fraud, material weakness, and unexpected earnings."
> ([CoLab record reproducing the publisher abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01625.x); bibliographic record independently confirmed in [EconPapers](https://econpapers.repec.org/article/blajfinan/v_3a66_3ay_3a2011_3ai_3a1_3ap_3a35-65.htm))

The mechanism is simple and worth stating plainly, because it drives every implementation decision below: in a 10-K the Harvard/General-Inquirer "negative" category fires on words like *liability*, *tax*, *cost*, *depreciation*, *foreign*, *risk*, *loss*. These are **accounting vocabulary, not pessimism**. A dictionary built by psychologists on non-financial English therefore measures *industry and accounting intensity*, not tone. The LM lists re-anchor the measurement inside the accounting register.

**Sample.** 10-K filings 1994–2008 [abstract-level]. The dictionary itself has been extended and republished continuously — the official page is maintained at Notre Dame and the current file covers 1993–2025:

> "The sentiment categories are: negative, positive, uncertainty, litigious, strong modal, weak modal, and constraining… The dictionary/sentiment lists are free for use in academic research. **For commercial licenses, please contact us…**"
> ([Loughran-McDonald Master Dictionary page, University of Notre Dame](https://sraf.nd.edu/loughranmcdonald-master-dictionary/))

The current release also includes a **complexity** list developed in Loughran & McDonald (2024, *JFQA* 59(6):2487–2514), and the dictionary is derived from the `2of12inf` baseline extended with tokens observed in the full EDGAR 10-K archive and CapIQ earnings calls ([same page](https://sraf.nd.edu/loughranmcdonald-master-dictionary/)).

**Replication / independent validation.** Two independent confirmations that general-purpose dictionaries fail:

- **Li (2010)** ran a naïve-Bayes classifier on forward-looking MD&A sentences and then tested the rival dictionaries: "The tone measures based on three commonly used dictionaries (**Diction, General Inquirer, and the Linguistic Inquiry and Word Count**) do not positively predict future performance. This result suggests that these dictionaries might not work well for analyzing corporate filings." ([EconPapers abstract for Li 2010, *JAR* 48(5):1049–1102](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm))
- **Huang, Wang & Yang (2023)** show a domain-adapted transformer (FinBERT) "substantially outperforms the Loughran and McDonald dictionary and other machine learning algorithms, including naïve Bayes, support vector machine, random forest, convolutional neural network, and long short-term memory, in sentiment classification," and that "other approaches underestimate the textual informativeness of earnings conference calls **by at least 18%** compared to FinBERT" ([CoLab abstract for FinBERT, *Contemporary Accounting Research*](https://colab.ws/articles/10.1111%2F1911-3846.12832)).

**Caveats.** (i) The LM dictionary's own authors caution that it is a starting point, not a truth machine — see the "tripwires" survey quoted at the top. (ii) **Commercial use requires a licence.** (iii) The dictionary is a bag of words: it is blind to negation, context, and sentence topic. Feng Li gives the canonical failure example: *"the Company has experienced attrition of its Medicare and commercial business in 1998 and 1999 and expects additional attrition"* scores as having positive words ("expect", "experience") and **no negative words** under the General Inquirer ([Li 2011 survey, full text](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)). (iv) The dictionary is U.S.-10-K-calibrated; UK Companies House iXBRL accounts are a different register and the LM lists are not validated on them. **UNVERIFIED: no study validating the LM lists on UK statutory accounts was located.**

**Implementation cost: lowest of any signal here.** A static word list plus a counter. Free for research, licence needed commercially.

---

### A2. Readability and obfuscation — the Fog Index

**What it is / how it is measured.** Gunning's Fog Index: `Fog = 0.4 × (average words per sentence + percentage of complex words)`, where complex words have ≥3 syllables. It approximates the years of formal education needed to read the text. Two measurement decisions matter: **which section** (MD&A vs whole 10-K) and whether the length of the document is used as a separate complexity proxy.

**Originating paper.** Li (2008), "Annual report readability, current earnings, and earnings persistence," *Journal of Accounting and Economics* 45(2–3):221–247. DOI [10.1016/j.jacceco.2008.02.003](https://doi.org/10.1016/j.jacceco.2008.02.003). **[abstract-level — no open-access full text exists; Unpaywall reports `is_oa: false` for this DOI](https://api.unpaywall.org/v2/10.1016/j.jacceco.2008.02.003)**

**Reported findings (verbatim from the publisher abstract, via EconPapers):**

> "I measure the readability of public company annual reports using the Fog index from the computational linguistics literature and the length of the document. I find that: (1) **the annual reports of firms with lower earnings are harder to read** (i.e., they have a higher Fog index and are longer); and (2) **firms with annual reports that are easier to read have more persistent positive earnings.**"
> ([EconPapers abstract, *JAE* 45(2–3):221–247](https://econpapers.repec.org/article/eeejaecon/v_3a45_3ay_3a2008_3ai_3a2-3_3ap_3a221-247.htm))

**Sample.** Public US company annual reports; the paper is the origin of the measure in accounting. Feng Li's own later survey describes the design and its two results the same way and notes the interpretation: "This paper hypothesizes that annual report readability captures management obfuscation… The results support the obfuscation hypothesis" ([Li 2011 survey, full text](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)). **UNVERIFIED: the specific coefficient magnitudes, t-statistics and the exact sample size and period from Li (2008) Tables 2–4.** The paper is closed-access with no repository copy and the publisher 403s; I did not reproduce numbers I could not read. A secondary source reports the descriptive anchors: mean Fog of about **18.2** (median 18.0) for MD&A text — the textbooks' "two years beyond an undergraduate degree" ([Lo, Ramos & Rogo working paper, full text](https://business.uq.edu.au/sites/default/files/events/files/kin-lo-paper.pdf), Table 2).

**Replication / extension — obfuscation vs ontology.** The obvious alternative explanation is Bloomfield's: bad news is *inherently* harder to explain ("ontology"), so this is not manipulation at all, it is just the topic. Bloomfield's published discussion of Li (2008) is itself cited 436 times ([EconPapers/OpenAlex record for the discussion](https://econpapers.repec.org/)), and Feng Li's survey restates it as a live threat: "Bloomfield [2008] argues that bad news may be inherently more difficult to communicate and hence the annual reports of poorly performing firms are more complex. This alternative explanation could change the interpretation of results in Li [2008]" ([Li 2011 survey](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)).

The **strongest test** of obfuscation-vs-ontology is Lo, Ramos & Rogo, published as *JAE* 63(1):1–25 (2017), DOI [10.1016/j.jacceco.2016.09.002](https://doi.org/10.1016/j.jacceco.2016.09.002) ([OpenAlex record, 812 citations](https://api.openalex.org/works?filter=title.search:earnings%20management%20and%20annual%20report%20readability)). Read in full via the 2014 working-paper PDF:

- **Design.** 26,967 firm-years, 4,855 unique firms, 2000–2012; MD&A section only; Fog plus twelve Li (2008) controls, industry and year fixed effects, standard errors clustered by industry.
- **Headline result.** Firms that **meet or just beat** last year's EPS have *less readable* MD&A: MBE coefficient **0.163 to 0.209** (t = 2.27 to 3.78). The authors translate it: "Firms that met or just beat prior year's EPS had MD&A that were more complex to read **by about a fifth or sixth of a year of formal education**."
- **The key discriminating test.** Interacting benchmark-beating with *positive discretionary accruals* — i.e. firms most likely to have *managed* earnings to get there — raises the coefficient to **0.299–0.335 (t up to 5.25)**, and to **0.385–0.419** for high positive discretionary accruals. Missing the benchmark (`NegEarnChg`) also raises Fog but with a coefficient roughly **3–6× smaller** (0.033–0.057).
- **Placebo.** Prior-year benchmark-beating (`MBE[t-1]`) is insignificant (t = 0.445) while current-year MBE stays significant.
- **Why this matters.** Good news that was manufactured is *harder* to read than bad news. That is inconsistent with a pure ontology story and supports obfuscation.
- **Predicting misstatements.** Adding Fog to Dechow et al.'s F-Score model gives a **positive and significant coefficient 0.025 (Wald χ² = 3.689, p = 0.027)** — but the authors themselves call it "marginal" and note "the predictive power of readability is low relative to the other three significant predictors."
([full text, Tables 1–11](https://business.uq.edu.au/sites/default/files/events/files/kin-lo-paper.pdf))

**Downstream consequences (independent support that readability is not noise).** Lehavy, Li & Merkley (2011, *The Accounting Review* 86(3):1087–1115) find using Li's readability measure that "analyst following, the amount of effort incurred to generate their reports, and the informativeness of their reports are greater for firms with less readable 10-Ks," and that "less readable 10-Ks are associated with greater dispersion, lower accuracy, and greater overall uncertainty in analyst earnings forecasts" ([quoted in Li 2011 survey, full text](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)). **Caveat, stated by Li himself:** "the effect of disclosure readability on analyst following properties documented in Lehavy, Li, and Merkley [2011] is **not established as a causality effect**."

**Readability and *underreaction* — the version of this signal that is closest to investable.** You & Zhang (2008/2009), "Financial reporting complexity and investor underreaction to 10-K information," *Review of Accounting Studies* 14(4):559–586, DOI [10.1007/s11142-008-9083-2](https://doi.org/10.1007/s11142-008-9083-2). **[abstract-level]** 456–633 citations depending on source ([CoLab](https://colab.ws/articles/10.1007%2Fs11142-008-9083-2); [OpenAlex](https://api.openalex.org/works?filter=title.search:financial%20reporting%20complexity%20and%20investor%20underreaction%20to%2010-K%20information)):

> "The abnormal price movements are positively associated with future accounting profitability, indicating that 10-K reports contain useful information about future firm performance. In addition, **investors' reaction to 10-K information seems sluggish, as demonstrated by the stock-price drift during the 12-month period after 10-K filing.** We find that investors' underreaction tends to be stronger for firms with more complex 10-K reports."

**Caveats.** (i) **Reverse causality and reflection:** readability is a *choice* correlated with bad performance, not a randomly assigned treatment; nothing here is a causal return signal on its own. (ii) The Fog Index is a crude proxy — it penalises any long, technical word (including *"securitisation"*), so for UK accounts and financial-sector firms it partly measures industry vocabulary. (iii) Effect sizes are in *reading-effort* units (fractions of a school year) and *marginal* increments to fraud models, not in return spreads. (iv) **The obfuscation interpretation is still contested**: obfuscation and ontology are observationally close, and Lo et al.'s benchmark-beating test is the main thing that separates them.

**Implementation cost: low.** Sentence splitter + syllable heuristic. Deterministic, cheap, no licence.

---

### A3. Management tone in MD&A and its relation to future performance

**Signals.** (a) **tone level** in MD&A or earnings releases; (b) **tone *change*** versus the prior filing; (c) tone in the **forward-looking** subset of MD&A (see A6).

**Key results, verified.**

| Study | Sample | Reported effect | Grade |
|---|---|---|---|
| Feldman, Govindaraj, Livnat & Segal (2010), *Review of Accounting Studies* 15(4):915–953 | 10-Q/10-K MD&A | Tone change is significantly associated with the **short-window market reaction around the SEC filing**, and "adds significantly to **portfolio drift returns** in the window of 2 days after the SEC filing date through 1 day after the subsequent quarter's preliminary earnings announcement, **beyond** financial information conveyed by accruals and earnings surprises." Drift is partly but "cannot be completely attributed" to predicting the next quarter's earnings surprise; the incremental value **depends on the strength of the firm's information environment**. | **B** |
| Davis, Piger & Sedor (2008/2012), *Contemporary Accounting Research* 29(3):845–868 | ~24,000 earnings press releases, 1998–2003 | Optimistic (pessimistic) language in earnings press releases positively (negatively) associated with **future performance**; "higher unexpected optimism (pessimism) is also found to be associated with higher (lower) returns around the earnings press release." | **B** |
| Brown & Tucker (2011), *JAR* | MD&A year-over-year modification | Firms with larger economic changes modify the MD&A more, and "the magnitude of stock price responses to 10-K filings is **positively associated with the MD&A modification score**." | **B** — and directly supports signal #3 (similarity) |
| Li & Ramesh (2009), *The Accounting Review* 84:1171–1208 | 10-K/10-Q filing dates | **Counter-evidence:** market reaction around 10-K/10-Q filings is *limited*, and significant only when the filing first releases earnings information, or when a 10-K is filed near a calendar quarter-end. | **D** — the tension is real |

Sources for the table above (all fetched): [CoLab abstract for Feldman et al.](https://colab.ws/articles/10.1007%2Fs11142-009-9111-x); [EconPapers abstract for Li 2010](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm); [Li 2011 survey, full text, §3.0.1](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf).

**How Li's survey reconciles the conflict** — this is the most useful single paragraph for a practitioner:

> "How can we reconcile the finding that there is little market reaction to the filings in Li and Ramesh [2009] with the findings in Loughran and McDonald [2009] and Feldman, Govindaraj, Livnat, and Segal [2010] that market reactions around filings are significantly associated with the content in the filings? **One potential reason is that Li and Ramesh [2009] focus on the on average effect around the filings, while the other papers examine the market reaction conditional on the tone of the disclosures.**"
> ([Li 2011 survey, full text](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf))

Translated: **the average 10-K moves nothing; the tone-conditional cross-section does.** That is exactly the regime a factor-style text signal lives in — and it is also why naive "big text score → big move" expectations fail.

**Caveats.** (i) **Reverse causality:** tone is jointly determined with the performance it appears to predict. (ii) Tone effects concentrate in weak information environments (Feldman et al.) — i.e. small, low-coverage, illiquid names, which is where implementation costs and capacity constraints bite. (iii) Filings are a committee product (managers, lawyers, PR, auditors) — a caution Feng Li raises explicitly: measures of "management characteristics" from filings "need to be examined carefully to ensure that the results are not driven by considerations such as strategic disclosure decisions." Tone *change* is more defensible than tone *level* precisely because it differences out firm-fixed style.

**Implementation cost: low**, given #1 and #3 already exist.

---

### A4. Hedging, uncertainty language, and "weasel words"

This area divides into three measurable things: **uncertainty/weak-modal vocabulary** (free with LM), **hedging as a linguistic act** (a detection task), and **linguistic imprecision / "weasel words"** (a specific dictionary).

**Uncertainty and modal words.** The LM dictionary ships `uncertainty`, `strong modal`, and `weak modal` categories ([Notre Dame dictionary page](https://sraf.nd.edu/loughranmcdonald-master-dictionary/)). LM's own paper links the word lists to "trading volume, return volatility, fraud, material weakness, and unexpected earnings" ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01625.x)). **The most defensible use of these categories is as a *risk/volatility* descriptor, not a return signal.** **UNVERIFIED: a specific, verified return-spread estimate for the LM uncertainty category in 10-Ks.** The relationship is real but the published effect sizes are in volatility/fraud models rather than portfolio spreads, and I could not read the closed-access tables.

**Hedging detection as an NLP task (not a returns result).** "Hedge detection" has its own benchmark and literature, which tells you the *error rate* you inherit if you try to detect hedges: Katerenchuk & Levitan (2024) "apply a joint model that leverages words and part-of-speech tags to improve hedge detection in text and achieve a new top score on the **CoNLL-2010 Wikipedia corpus**" ([arXiv:2405.13319 abstract](https://arxiv.org/abs/2405.13319)). **UNVERIFIED: the actual F1 figure** (the abstract states a new top score but the number is in the paper body, which I did not read). This matters because hedge/resolution is a *hard* classification problem even in a curated corpus — a dictionary-based hedge counter on filings will be noisy.

**"Weasel words" / linguistic imprecision — the one paper with a return result, and its sign is counter-intuitive.** "Some People Say: Linguistic Imprecision in Corporate Disclosures" (conference paper, CIR Forum 2019; later circulated as *Some People Say: Immature Information in Corporate Disclosures*, SSRN 3152460). **[full text via PDF extraction]**. Read in full:

- **Measure.** Build a dictionary from sentences carrying Wikipedia's `{{weasel}}` tag, filtered against control sentences from the same articles to strip common English, then compute `Imprecision = (# imprecision keywords) / (total words) × 100`.
- **Sample.** 10-K filings with report dates **1997–2015**; 219,491 firm-year raw observations reduced to **44,207 firm-years** after merging Compustat, CRSP and Hoberg product-market/financial-constraint data.
- **Determinants.** Imprecision rises with **product market fluidity** (coefficient 0.088, t≈29) and **financial constraints** (0.041, t≈20); more imprecise firms are younger, smaller, less profitable, less tangible. Equity constraints drive it, debt constraints do not.
- **Return result.** Weekly buy-and-hold abnormal returns regressions, clustered by month, controlling for sentiment, size, book-to-market, turnover, pre-filing alpha, institutional ownership and SUE: `Imprecision(Z)` is insignificant at weeks 1–2, then becomes significant and **cumulates to +0.010 (1.0%) over the 10 weeks after filing** (Week1-10 coefficient 0.010, SE 0.003, ***). The authors stress "this positive stock return effect is not immediate and also does not lead to a subsequent reversal."
- **Risk result.** Imprecision predicts **net upside return volatility** (+0.021, SE 0.007–0.008, *** over 1 and 2 months) — i.e. imprecision signals *upside* optionality, not downside risk.
- **Interpretation.** The authors explicitly contrast this with obfuscation: "the use of imprecise language in disclosures tends to reflect valuable information, which is a sharp contrast to managerial obfuscation… additional information on upcoming positive but yet uncertain prospects."
- **Distinctness check.** Their imprecision measure is largely *orthogonal* to LM uncertainty/weak-modal/strong-modal counts (see their Table 3 correlations, all ≤0.19), so it is not just another uncertainty proxy.
([full text, abstract and Tables 1–9](https://cirforum.org/2019forum_papers/CIRF2019_paper_20.pdf))

**Caveats — this is the single most over-interpretable result in the report.** (i) It is a **conference/working paper, not a peer-reviewed journal article** as far as I could verify. (ii) The dictionary is **Wikipedia-derived and not fully published** — the paper says "The complete list of imprecision keywords can be obtained by contacting the authors." Reproduction therefore requires re-implementing their method. (iii) The effect is tiny: **1% over 10 weeks** before costs, with adjusted R² of 0.005–0.006 in the BHAR regressions. (iv) **Reverse causality runs the useful direction for them and the dangerous direction for you:** imprecision is a marker of young, uncertain, high-upside firms, so the "signal" is partly a **small-growth/optionality factor** that already exists in accounting data. (v) Their own thesis — imprecision is *good* news — inverts the folk intuition, which is exactly the pattern that produces spurious findings.

**Practical reading.** Treat weasel-word density as a **company-characteristic descriptor** (young, intangible, constrained, uncertain prospects) rather than a tradeable signal, and never as "management is hiding something" evidence on its own.

**Implementation cost: low for LM uncertainty; medium for imprecision** (must reconstruct a dictionary), and the reconstruction is not independently validated.

---

### A5. Boilerplate and year-over-year textual similarity — the strongest filing signal

**What it is / how it is measured.** Compare this period's filing (or a section of it) to the same firm's prior filing and compute a similarity/difference score. Lazy Prices uses **four** measures: two term-frequency measures, an edit-distance measure (minimum operations to transform one document into the other), and a word-processor-style diff (`words added or deleted ÷ total words`).

**Originating paper.** Cohen, Malloy & Nguyen, "Lazy Prices," NBER Working Paper 25084 (Sept 2018, rev. Mar 2019), published *Journal of Finance* 75(3):1371–1415 (2020), DOI [10.1111/jofi.12885](https://doi.org/10.1111/jofi.12885). **[abstract-level + NBER non-technical summary, both full text]**

**Sample.** "The complete history of regular quarterly and annual filings by U.S. corporations from **1995–2014**" ([NBER paper page](https://www.nber.org/papers/w25084)).

**Reported effect size — the largest verified return spread in this report:**

> "a portfolio that shorts 'changers' and buys 'non-changers' earns up to **188 basis points in monthly alphas (over 22% per year)** in the future. Changes in language referring to the executive (CEO and CFO) team, regarding litigation, or in the risk factor section of the documents are especially informative for future returns. We show that changes to the 10-Ks predict future earnings, profitability, future news announcements, and even future firm-level bankruptcies; meanwhile firms that do not make changes experience positive abnormal returns."
> ([NBER abstract](https://www.nber.org/papers/w25084))

The NBER Digest gives the decomposition:

> "portfolios that were long 'non-changers' and short 'changers' earned a statistically significant value-weighted abnormal return of **between 34 and 58 basis points per month — between 4 and 7 percent per year** — over the following year… While changes in the wording of the management discussion section of company reports did predict large and significant abnormal returns, **textual changes in the risk factors section were even more informative, predicting abnormal returns of 188 basis points per month, or over 22 percent per year.**"
> ([NBER Digest, November 2018](http://www2.nber.org/digest/nov18/w25084.shtml))

**Additional verified detail from the Digest:** "More than 86 percent of changes were 'negative sentiment' changes"; "The 14 percent of changes that represented positive sentiment were significant predictors of positive future abnormal returns"; abnormal returns "continued to accrue for up to **18 months** after the date of the regulatory filing and they were **not reversed subsequently**"; and results "were not related to firm size, time, industry, or one-time firm events."

**Mechanism, and why it is credible.** The authors argue inattention: "Unlike typical underreaction patterns in asset prices, we find **no announcement effect** associated with these changes—with returns only accruing when the information is later revealed through news, events, or earnings" ([NBER abstract](https://www.nber.org/papers/w25084)). They obtained EDGAR **download logs via FOIA** (date, time, IP address of each 10-K download) and found that when investors downloaded the current and prior year's 10-K at the same time ("dual downloading", a proxy for comparing changes), the announcement reaction was larger and the subsequent drift **smaller** — direct evidence that the anomaly is an attention effect ([NBER Digest](http://www2.nber.org/digest/nov18/w25084.shtml)). This is a genuinely rare thing: a text anomaly with **independent evidence on the causal mechanism**.

**Why it fits the rest of the literature.** Brown & Tucker (2011) independently found MD&A modification scores predict the price response to 10-K filings ([Li 2011 survey](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)). And the boilerplate *trend* is itself documented: Dyer, Lang & Stice-Lawrence (2017), "The evolution of 10-K textual disclosure: Evidence from Latent Dirichlet Allocation," *JAE* 64(2–3):221–245, DOI [10.1016/j.jacceco.2017.07.002](https://doi.org/10.1016/j.jacceco.2017.07.002), document over **1996–2013** "increases in length, boilerplate, stickiness, and redundancy and decreases in specificity, readability, and the relative amount of hard information," and find that "3 of the 150 topics—fair value, internal controls, and risk factor disclosures—account for virtually all of the increase" ([CoLab abstract](https://colab.ws/articles/10.1016%2Fj.jacceco.2017.07.002)). Boilerplate is rising, so a similarity signal is measuring a *shrinking* set of real changes — arguably increasing its information-per-change over time, but also meaning most filings carry a near-zero score.

**Caveats — and they are serious.** (i) **The 188 bps/month figure is a sub-portfolio result on the risk-factor section.** It is not the headline portfolio (34–58 bps/month), and high-alpha sub-results from many partitions are exactly where multiple-testing bias lives. (ii) **No independent replication of the return spread was located.** The mechanism has independent support (Brown & Tucker; the FOIA download logs); the *magnitude* does not. (iii) **Capacity and trading costs are not addressed in the abstract or digest**; a signal that persists 18 months is more robust to costs than a one-week signal, but non-changers vs changers sorts may load on illiquidity. **UNVERIFIED: turnover, capacity, and post-2014 out-of-sample performance.** (iv) **The two alpha figures disagree by ~4×** depending on portfolio construction (34–58 vs 188 bps/month), which is a warning about specification sensitivity.

**Implementation cost: low–medium.** Requires the same firm's prior filing and section alignment. The edit-distance and diff measures are straightforward; section alignment (Item 1A, Item 7) is the main engineering task. **This is the highest value-per-unit-of-effort filing signal in the report.**

---

### A6. Risk-factor disclosures: existence, count, and specificity

**Background.** The SEC mandated a "risk factor" section (Item 1A) in 10-Ks beginning in 2005. This created a natural experiment in disclosure.

**Campbell, Chen, Dhaliwal, Lu & Steele (2014), "The information content of mandatory risk factor disclosures in corporate filings," *Review of Accounting Studies* 19(1):396–455, DOI [10.1007/s11142-013-9258-3](https://doi.org/10.1007/s11142-013-9258-3).** **[abstract-level]** 675 citations:

> "First, we find that **firms facing greater risk disclose more risk factors**, and that the type of risk the firm faces determines whether it devotes a greater portion of its disclosures towards describing that risk type. That is, managers provide risk factor disclosures that meaningfully reflect the risks they face. Second, we find that **the information conveyed by risk factor disclosures is reflected in systematic risk, idiosyncratic risk, information asymmetry, and firm value**."
> ([CoLab abstract](https://colab.ws/articles/10.1007%2Fs11142-013-9258-3))

**Hope, Hu & Lu (2016), "The benefits of specific risk-factor disclosures," *Review of Accounting Studies* 21(4):1005–1045, DOI [10.1007/s11142-016-9371-1](https://doi.org/10.1007/s11142-016-9371-1).** **[abstract-level]** 421 citations — and this is the more actionable of the two:

> "Practitioners have long criticized risk-factor disclosures in the 10-K as generic and boilerplate. In response, regulators emphasize the importance of being specific. By using a computing algorithm, this paper establishes a new measure (Specificity)… firms with high proprietary costs provide less specific risk-factor disclosures. More importantly, we find that, **controlling for numerous determinants, the market reaction to the 10-K filing is positively and significantly associated with Specificity.** In addition, our results suggest that **analysts are better able to assess fundamental risk when firms' risk-factor disclosures are more specific.**"
> ([CoLab abstract](https://colab.ws/articles/10.1007%2Fs11142-016-9371-1))

**Reading these together.** The *count* of risk factors is informative about the firm's risk exposure (useful as a **risk descriptor**), while the *specificity* of risk language is what the market rewards at the filing date (a **short-window event signal**). Note the interaction with A5: Lazy Prices finds **changes** in the risk-factor section are the single most informative text change. Specificity and change are complementary: a specific change is the informative event; a generic change is boilerplate churn.

**Caveats.** (i) The market-reaction results are **short-window event reactions**, not long-horizon alpha — they say the market *does* price specificity, which by construction makes it harder to profit from. (ii) **No return-spread (portfolio) effect sizes are reported in the abstracts** for either paper. **UNVERIFIED: portfolio alphas for specificity or risk-factor counts.** (iii) Campbell et al. is explicitly framed as *supporting the SEC's mandate*; it is not an alpha paper.

**Implementation cost: medium–high.** Specificity requires an algorithm (the paper's is a "computing algorithm", not a published word list). Risk-factor *counts* and *change* are cheap.

---

### A7. Forward-looking statements and guidance language

**Li (2010), "The Information Content of Forward-Looking Statements in Corporate Filings—A Naïve Bayesian Machine Learning Approach," *Journal of Accounting Research* 48(5):1049–1102, DOI [10.1111/j.1475-679X.2010.00382.x](https://doi.org/10.1111/j.1475-679X.2010.00382.x).** **[abstract-level + survey description]** — the canonical paper.

Publisher abstract, verbatim highlights:
> "I find that firms with better current performance, lower accruals, smaller size, lower market-to-book ratio, less return volatility, lower MD&A Fog index, and longer history tend to have more positive FLSs. **The average tone of the FLS is positively associated with future earnings even after controlling for other determinants of future performance.** The results also show that, despite increased regulations aimed at strengthening MD&A disclosures, **there is no systematic change in the information content of MD&As over time.** In addition, the tone in MD&As seems to **mitigate the mispricing of accruals**. When managers 'warn' about the future performance implications of accruals (i.e., the MD&A tone is positive (negative) when accruals are negative (positive)), accruals are not associated with future returns. **The tone measures based on three commonly used dictionaries (Diction, General Inquirer, and the Linguistic Inquiry and Word Count) do not positively predict future performance.**"
> ([EconPapers abstract](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm))

**Sample and scale (from the call-language stream of this review).** 30,000 hand-coded sentences for training; the classifier was then applied to roughly **13 million statements across 140,000+ MD&A filings, 1994–2007.**

**Three things to take from Li (2010):**
1. **The signal that works is FLS tone, not document tone** — restrict the text to future-oriented sentences before scoring.
2. **It was not built from a dictionary.** It is a supervised classifier on hand-labelled sentences. If you replicate it, you need labels (or an LLM acting as the labeller).
3. **A very strong negative result:** the three general-purpose dictionaries fail here. Note also that the *accruals-mispricing* result implies text and accounting data are **substitutes**, not independent additive signals — the text matters most where the numbers are ambiguous.

**Bozanic, Roulstone & Van Buskirk (2018), "Management earnings forecasts and forward-looking statements," *JAE* 65(1):1–20.** Finds that **non-forecast "other" FLS also generate investor and analyst responses**, that other FLS are issued **more** when uncertainty is higher, and that managers alter content more than form. Implication: restricting to numeric guidance throws away most of the forward-looking content.

**Guidance is systematically biased — and the *midpoint is not the expectation*.** Call, Hribar, Skinner & Volant (2024), *JAE* 78(2), survey of **357 managers** (9.8% response rate): **more than 60% say their private expectation is ABOVE the guidance midpoint, fewer than 7% below, and 24% above the upper bound of the range**; roughly 90% are >70% confident they will land inside the range but only ~30–31% actually do; I/B/E/S shows guidance for 58% of firms versus >80% self-reported. Preussner & Aschauer (*Accounting Perspectives* 21(2):273–330, **open access**) review the field and find guidance is systematically optimistic, that accuracy rises with prior accuracy, firm size, analyst coverage and governance, and that **investors do not fully price the bias** (post-forecast drift).

**Cheap talk — the asymmetry that matters.** Koo & Yeung (working paper, 2001–2009; 4,730 forecasts by 1,118 firms): the mean management growth forecast was **15.61% versus 2.91% realised**; **good-news growth forecasts are uninformative cheap talk while bad-news ones are informative**, and investors react to the uninformative good news and not the informative bad news. **This is a preliminary working paper the authors ask not to be cited — treat the direction as a hypothesis, not a finding.**

**Caveats.** (i) Guidance in UK filings is far sparser than US guidance, so this signal is much weaker for a UK-heavy portfolio. (ii) FLS *volume* is itself a response to uncertainty (Bozanic et al.; Muslu et al. 2015), so volume is endogenous. (iii) The "cheap talk" asymmetry means naive "more positive FLS = better" is likely mis-specified; and (iv) Li's own finding that MD&A information content did **not** change over time despite regulation is a caution against expecting the signal to strengthen.

**Implementation cost: medium.** Requires either labelled training data or a modern classifier, plus sentence-level forward-looking filtering.

---

### A8. "Annual report tone predicts returns" — the literature and its critics

**The positive case (verified, modest):**
- **Short-window filing reaction** to MD&A tone change, incremental to accruals and earnings surprises — Feldman et al. (2010) ([abstract](https://colab.ws/articles/10.1007%2Fs11142-009-9111-x)).
- **Post-filing drift** over the following quarter attributable to tone change — same paper.
- **12-month drift after 10-K filing**, stronger for complex reports — You & Zhang ([abstract](https://colab.ws/articles/10.1007%2Fs11142-008-9083-2)).
- **Levels and changes in filing text predict future earnings, profitability, news, and bankruptcies**, with a 34–58 bps/month headline portfolio alpha — Cohen, Malloy & Nguyen ([NBER](https://www.nber.org/papers/w25084)).

**The critics and the caveats (also verified):**
1. **The average filing moves nothing.** Li & Ramesh (2009) find limited market reaction around 10-K/10-Q filing dates except when the filing first releases earnings; Li's own survey says the conflict with the tone papers is resolved by *conditioning on tone* — meaning the effect is a conditional cross-section, not a broad-based return predictor ([survey full text](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)).
2. **Text effects concentrate in weak information environments.** Feldman et al. find the incremental value of tone change "depends on the strength of the firm's information environment"; Campbell et al.'s risk-disclosure effects are in risk/asymmetry measures. In practice this means **small, low-coverage, illiquid firms** — the segment where spread and impact costs are highest.
3. **The most-cited positive results are short-window, i.e. already priced by the time a filing-text pipeline reacts.** Specificity → market reaction at the filing date (Hope et al.) is a statement that the market *does* price it.
4. **Reverse causality and reflection are unaddressed in most designs.** Tone and readability are chosen. Only Lo et al.'s benchmark-beating interaction and Lazy Prices' FOIA download-log evidence get close to identification.
5. **Data-mining risk is acknowledged by the field's own survey authors**, who note the likely role of publication selection bias ([Li 2011 survey](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf)).
6. **Regime dependence in the sibling news literature** is instructive: Garcia (2013) finds news-sentiment predictability of returns is "concentrated in recessions" (see Part B). Text signals are not stationary.

**Bottom line for A8.** The defensible claim is: *changes and specificity in filing language carry information about future fundamentals, and the market underreacts to them, most visibly where attention and information are scarce.* The indefensible claim is: *10-K tone is a general-purpose return factor.*

---

## Part B — News and media signals

*(This section consolidates the news/media research stream. Where a source is a working paper, a non-peer-reviewed preprint, or a single study, that is stated explicitly.)*

---

## Part C — Making documents machine-analysable

*(This section consolidates the annotation, LLM-validation, and narrative-vs-numbers research stream.)*

---

## Two concrete answers

*(Filled in after Parts B and C.)*

---

## Fetch log

*(Filled in after Parts B and C.)*
