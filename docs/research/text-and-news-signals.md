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
| 14 | **News sentiment (daily, firm-specific)** | Positive/negative word share in news about a firm | **B** — real but small and short-horizon; **A** that the dominant signature is pressure→**reversal**, not drift | **Low** with headlines/snippets. |
| 15 | **Media attention / coverage volume** | Count of articles mentioning a firm | **B** — "no-coverage" premium (sign is *negative*); attention → ~2-week rise then reversal; concentrated in illiquid/retail names | **Low**, but coverage count is contaminated by reverse causality. |
| 16 | **Source slant + sensationalism** | (a) divergence of a source's tone from peers / advertising-conflict exposure; (b) ambiguous language + broad-appeal subject = lower accuracy | **B** for both — verified constructs with measurable price consequences; effect sizes UNVERIFIED | **Low–medium**, depends on registry quality. |
| 17 | **Stale-news / slow-diffusion decay** | Textual similarity to the previous ten stories on the same firm; reprint detection | **A** — Tetlock (2011) — and it **flips the sign**: stale news + price move ⇒ contrarian | **Medium** — needs event timestamp + syndication collapse (already built). |

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

### B1. The foundational news-sentiment studies

**(a) Tetlock (2007), "Giving Content to Investor Sentiment: The Role of Media in the Stock Market," *Journal of Finance* 62(3):1139–1168, DOI [10.1111/j.1540-6261.2007.01232.x](https://doi.org/10.1111/j.1540-6261.2007.01232.x).** **[abstract-level]** 3,496 citations.

> "I quantitatively measure the interactions between the media and the stock market using **daily content from a popular Wall Street Journal column**. I find that **high media pessimism predicts downward pressure on market prices followed by a reversion to fundamentals**, and **unusually high or low pessimism predicts high market trading volume**. These and similar results are consistent with theoretical models of noise and liquidity traders, and are **inconsistent with theories of media content as a proxy for new information about fundamental asset values**."
> ([CoLab record reproducing the publisher abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2007.01232.x))

**Read this carefully — it is routinely mis-cited.** The headline is *not* "news sentiment predicts returns." It is **temporary downward price pressure followed by reversion**. The author's own conclusion is that the column is a **noise/liquidity** signal, not information about fundamentals. A pipeline that goes long after good news and short after bad news is, on this evidence, trading the wrong side of a reversion. Sample: one WSJ column, daily. **UNVERIFIED: the exact sample period and the size of the pressure/reversion coefficients** — both sit in the closed-access body.

**(b) Tetlock, Saar-Tsechansky & Macskassy (2008), "More Than Words: Quantifying Language to Measure Firms' Fundamentals," *Journal of Finance* 63(3):1437–1467, DOI [10.1111/j.1540-6261.2008.01362.x](https://doi.org/10.1111/j.1540-6261.2008.01362.x).** **[abstract-level, full abstract reconstructed from the publisher's inverted index]** 2,300 citations.

> "We examine whether a simple quantitative measure of language can be used to predict individual firms' accounting earnings and stock returns. Our three main findings are: **(1) the fraction of negative words in firm-specific news stories forecasts low firm earnings; (2) prices briefly underreact to the information embedded in negative words; (3) return predictability from negative words is largest for the stories that focus on fundamentals.** Together these suggest that linguistic media content captures otherwise hard-to-quantify aspects of firms' fundamentals, which investors quickly incorporate into prices."
> ([OpenAlex record](https://api.openalex.org/works?filter=title.search:more%20than%20words%20quantifying%20language%20to%20measure%20firms%20fundamentals))

Three implementation-critical points: the informative unit is **firm-specific news**; the informative content is **negative** words; and predictability is **largest for stories about fundamentals** — so **you must classify the article's subject matter, not just its polarity.** "Briefly underreact" also fixes the horizon as short.

**(c) Tetlock (2011), "All the News That's Fit to Reprint: Do Investors React to Stale Information?" *Review of Financial Studies* 24(5):1481–1512, DOI [10.1093/rfs/hhq141](https://doi.org/10.1093/rfs/hhq141).** **[abstract-level, full abstract retrieved]** 651 citations. This is the most directly useful news paper for a pipeline that already does syndication collapse:

> "This article tests whether stock market investors appropriately distinguish between new and old information about firms. **I define the staleness of a news story as its textual similarity to the previous ten stories about the same firm.** I find that **firms' returns respond less to stale news.** Even so, **a firm's return on the day of stale news negatively predicts its return in the following week.** Individual investors trade more aggressively when news is stale. **The subsequent return reversal is significantly larger in stocks with above-average individual investor trading activity.** These results are consistent with the idea that investors overreact to stale information, leading to temporary movements in stock prices."
> ([OpenAlex record with full abstract](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information))

**Operational translation:** a headline textually similar to the last ten stories about that firm should be **down-weighted toward zero information**; and a *large price move* on stale news is a **contrarian** signal for the following week, strongest in retail-heavy names. This is published justification for the syndication-collapse component the tool already has — and it says the correct sign is the **opposite** of naive "news → follow the move."

**(d) Garcia (2013), "Sentiment during Recessions," *Journal of Finance* 68(3):1267–1300, DOI [10.1111/jofi.12027](https://doi.org/10.1111/jofi.12027).** **[abstract-level]**

> "This paper studies the effect of sentiment on asset prices **during the 20th century (1905 to 2005)**. As a proxy for sentiment, we use the fraction of positive and negative words in **two columns of financial news from the New York Times**. The main contribution of the paper is to show that … **the predictability of stock returns using news' content is concentrated in recessions. A one standard deviation shock to our news measure during recessions predicts a change in the conditional average return on the DJIA of 12 basis points over one day.**"
> ([CoLab abstract](https://colab.ws/articles/10.1111%2Fjofi.12027))

**Effect size: 12 bps, one day, only in recessions.** That is the honest scale of the best long-history news-sentiment result — a *conditional mean return on an index*, not a tradeable cross-sectional spread. It also means news-sentiment models fitted on 1990–2020 data are fitted on a **non-stationary, regime-dependent** relationship.

### B2. Media attention and coverage as a signal

**(a) Fang & Peress (2009), "Media Coverage and the Cross-section of Stock Returns," *Journal of Finance* 64(5):2023–2052, DOI [10.1111/j.1540-6261.2009.01493.x](https://doi.org/10.1111/j.1540-6261.2009.01493.x).** **[abstract-level]** 1,941 citations.

> "By reaching a broad population of investors, mass media can alleviate informational frictions and affect security pricing **even if it does not supply genuine news**… We find that **stocks with no media coverage earn higher returns than stocks with high media coverage even after controlling for well-known risk factors. These results are more pronounced among small stocks and stocks with high individual ownership, low analyst following, and high idiosyncratic volatility.** Our findings suggest that the breadth of information dissemination affects stock returns."
> ([CoLab abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x))

**Two immediate implications.** (i) The sign is **negative** — more coverage, *lower* expected returns. A pipeline treating "lots of press" as bullish is backwards. (ii) The effect lives exactly where this tool cannot easily trade: **small, retail-held, low-coverage, high-idiosyncratic-volatility stocks.** The paper's own framing — media matters "even if it does not supply genuine news" — is the conceptual point: **coverage is information *diffusion*, not information.**

**(b) Da, Engelberg & Gao (2011), "In Search of Attention," *Journal of Finance* 66(5):1461–1499, DOI [10.1111/j.1540-6261.2011.01679.x](https://doi.org/10.1111/j.1540-6261.2011.01679.x).** **[abstract-level]** 2,498 citations.

> "We propose a new and direct measure of investor attention using search frequency in Google (Search Volume Index (SVI)). **In a sample of Russell 3000 stocks from 2004 to 2008**, we find that SVI … **captures investor attention in a more timely fashion** and **likely measures the attention of retail investors. An increase in SVI predicts higher stock prices in the next 2 weeks and an eventual price reversal within the year.** It also contributes to the large first-day return and long-run underperformance of IPO stocks."
> ([CoLab abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x))

**A two-week price rise followed by reversal within the year is the canonical attention/price-pressure signature.** It is not a fundamental signal. If a news pipeline's "attention" feature looks like this, it is a liquidity-provision/contrarian signal at best.

**(c) Engelberg & Parsons (2011), "The Causal Impact of Media in Financial Markets," *Journal of Finance* 66(1):67–97, DOI [10.1111/j.1540-6261.2010.01626.x](https://doi.org/10.1111/j.1540-6261.2010.01626.x).** **[abstract-level]** 1,184 citations. The best available **causal** design on media:

> "Disentangling the causal impact of media reporting from the impact of the events being reported is challenging. **We solve this problem by comparing the behaviors of investors with access to different media coverage of the same information event.** We use zip codes to identify **19 mutually exclusive trading regions corresponding with large U.S. cities. For all earnings announcements of S&P 500 Index firms**, we find that **local media coverage strongly predicts local trading, after controlling for earnings, investor, and newspaper characteristics.** Moreover, **local trading is strongly related to the timing of local reporting**, a particular challenge to nonmedia explanations."
> ([CoLab abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01626.x))

**This is the single most important paper for the "how much weight should news carry" question.** Holding the underlying information event **constant** (the same S&P 500 earnings announcement) and varying only *which investors saw coverage*, media changes **trading**, not the information set. News coverage is, causally, a **participation/attention shock** — which is why its return signature (Tetlock 2007; Da et al. 2011) is **temporary pressure and reversal** rather than permanent repricing.

**(d) Hillert, Jacobs & Müller (2014), "Media Makes Momentum," *Review of Financial Studies* 27(12):3467–3501, DOI [10.1093/rfs/hhu061](https://doi.org/10.1093/rfs/hhu061).** **[abstract-level]** 198 citations.

> "Relying on **2.2 million articles from forty-five national and local U.S. newspapers between 1989 and 2010**, we find that **firms particularly covered by the media exhibit, ceteris paribus, significantly stronger momentum.** The effect depends on article tone, **reverses in the long run**, is more pronounced for stocks with high uncertainty, and is stronger in states with high investor individualism. Our findings suggest that **media coverage can exacerbate investor biases**, leading return predictability to be strongest for firms in the spotlight of public attention. These results collectively lend credibility to an **overreaction-based** explanation for the momentum effect."
> ([CoLab abstract](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061))

**This is the cleanest statement of the "apparent news alpha is really momentum" critique.** A news-sentiment factor loading on high-coverage stocks is partly a **momentum** factor with an **overreaction** and **long-run reversal** component. Controlling for momentum is mandatory before claiming independent news alpha.

### B3. Is negative news more informative than positive?

**What is verified.** Tetlock, Saar-Tsechansky & Macskassy (2008): "the fraction of **negative** words in firm-specific news stories **forecasts low firm earnings**," and "return predictability from negative words is largest for the stories that focus on fundamentals" ([full abstract](https://api.openalex.org/works?filter=title.search:more%20than%20words%20quantifying%20language%20to%20measure%20firms%20fundamentals)). An asymmetry is also visible from the filings side: in Lazy Prices, "**more than 86 percent of changes were 'negative sentiment' changes**," yet "the 14 percent of changes that represented positive sentiment were **significant predictors of positive future abnormal returns**" ([NBER Digest](http://www2.nber.org/digest/nov18/w25084.shtml)).

**What is NOT verified here.** The standard theoretical citation for bad-news asymmetry — Hong, Lim & Stein's "bad news travels slowly" and the short-sale-constraint mechanism — **I could not retrieve**: an OpenAlex title search returned zero results for that phrasing and I did not fetch the paper. **UNVERIFIED: the Hong–Lim–Stein result and any quantification of asymmetry in diffusion speed.** Do not attribute a number to it on this report's authority.

**Practical reading.** There is credible evidence that **negative** news has more *fundamental* content (earnings forecasting) than positive news, and none here that positive news is symmetric. But note the trap: Tetlock (2007) says pessimism produces **downward pressure that reverts**; TSM (2008) says negative words forecast **low earnings**. Those are different claims with different signs at different horizons. A system must decide which one it is trading.

### B4. Sensationalism, slant, and source quality

**Gurun & Butler (2012), "Don't Believe the Hype: Local Media Slant, Local Advertising, and Firm Value," *Journal of Finance* 67(2):561–598, DOI [10.1111/j.1540-6261.2012.01725.x](https://doi.org/10.1111/j.1540-6261.2012.01725.x).** **[abstract-level]** 476 citations. The strongest academic support for the tool's **source reliability/bias registry**:

> "**When local media report news about local companies, they use fewer negative words compared to the same media reporting about nonlocal companies.** We document that **one reason for this positive slant is the firms' local media advertising expenditures.** **Abnormal positive local media slant strongly relates to firm equity values.** The effect is stronger for **small firms; firms held predominantly by individual investors; and firms with illiquid or highly volatile stock, low analyst following, or high dispersion of analyst forecasts.** These findings show that **news content varies systematically with the characteristics and conflicts of interest of the source.**"
> ([CoLab abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x))

**Why this matters most.** It is direct evidence that **sentiment measured from a source is contaminated by the source's commercial relationship with the firm**, and that contamination is largest in exactly the segment where the naive signal appears strongest. A **source-level bias adjustment is a validity requirement, not a refinement** — the one place where the tool's existing registry has a clear evidential warrant.

**On sensationalism specifically — Ahern & Sosyura (2015), "Rumor Has It: Sensationalism in Financial Media," *Review of Financial Studies* 28(7):2050–2093, DOI [10.1093/rfs/hhv006](https://doi.org/10.1093/rfs/hhv006).** **[abstract-level]** 230 citations. This is the sensationalism study, and it is unusually well matched to the tool's manipulation-detection component:

> "The media has an incentive to publish sensational news. We study how this incentive affects the accuracy of media coverage in the context of **merger rumors**. Using a novel dataset, we find that **accuracy is predicted by a journalist's experience, specialized education, and industry expertise. Conversely, less accurate stories use ambiguous language and feature well-known firms with broad readership appeal. Investors do not fully account for the predictive power of these characteristics, leading to an initial target price overreaction and a subsequent reversal, consistent with limited attention.**"
> ([CoLab abstract](https://colab.ws/articles/10.1093%2Frfs%2Fhhv006))

**Why this matters.** It gives an **empirically validated sensationalism construct with a measurable market consequence**: ambiguous language plus a high-profile, broad-appeal subject predicts **lower accuracy**, and investors **overreact then reverse**. That is a *directional, testable* rule for the news pipeline — "ambiguous language about a famous firm = lower reliability, and price moves on such stories should be faded" — and it aligns with the source-reliability registry (journalist experience/expertise as a reliability feature) rather than an ad-hoc sensationalism score.

**Caveats.** (i) The setting is **merger rumours**, a narrow and unusual news category; whether the accuracy determinants transfer to ordinary earnings/guidance coverage is untested here. (ii) **UNVERIFIED: the accuracy rates, the size of the overreaction/reversal, and the ambiguity measure's construction** — abstract only. (iii) As with every reversal result in Part B, the tradeable content is a **fade**, not a follow, and it sits in the illiquid, attention-driven segment.

**Combined with Gurun & Butler**, the news panel of this review supports **two distinct, verified source-quality constructs** — *commercial-conflict slant* (advertising) and *sensationalism* (ambiguous language + broad appeal) — both of which predict price behaviour, and both of which the tool's registry can encode. **What remains UNVERIFIED: a sensationalism measure validated on non-rumour financial news, and any effect-size estimates for either construct.**

### B5. Stale news and how long a news effect persists

| Horizon claim | Evidence | Source |
|---|---|---|
| Returns respond **less** to stale news (staleness = textual similarity to the previous ten stories on the same firm) | Verified | [Tetlock 2011](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information) |
| A return move on stale news **negatively** predicts next week's return; reversal bigger where retail trading is high | Verified | same |
| Attention rise → price rise over **~2 weeks**, then **reversal within the year** | Verified | [Da, Engelberg & Gao 2011](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x) |
| News-sentiment return predictability concentrated in **recessions**, ~12 bps/day on the DJIA | Verified | [Garcia 2013](https://colab.ws/articles/10.1111%2Fjofi.12027) |
| Media-driven momentum **reverses in the long run** | Verified | [Hillert, Jacobs & Müller 2014](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061) |
| Negative words in the **filing** (not the news) predict underreaction + **12-month** drift | Verified, filings side | [You & Zhang](https://colab.ws/articles/10.1007%2Fs11142-008-9083-2) |

**Synthesis.** Across the news literature the *durable* horizon is short and the long-run component tends to **reverse**; in the *filings* literature (You & Zhang; Lazy Prices) drift persists 12–18 months. That asymmetry is itself informative: **filing-text signals look like slow diffusion of fundamentals; news-sentiment signals look like attention-driven price pressure.**

### B6. The case AGAINST news as a signal

**1. Reverse causality and endogeneity — coverage follows price and volume, not only the reverse.**
The strongest news papers are explicitly designed around this problem, which tells you how serious it is. Engelberg & Parsons hold the information event fixed and vary *coverage access*, finding media moves **local trading** ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01626.x)). Fang & Peress describe media as affecting pricing "even if it does not supply genuine news" ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x)). Da et al. show attention *precedes* a temporary price rise and a **reversal** ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x)). **UNVERIFIED: a specific quantified estimate of how much coverage is caused by prior returns/volume** — that measurement was not obtained and should be treated as an open item you run yourself. The *direction* of the concern is well established by these three designs.

**2. Much apparent "news sentiment alpha" is momentum.** Hillert, Jacobs & Müller show media coverage *causes* stronger momentum that **reverses long-run** ([abstract](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061)). Any news factor must be tested against a momentum control before being called news alpha.

**3. Much of it is liquidity/attention, not information.** Every attention result above concentrates in **small, illiquid, retail-held, low-coverage, high-idiosyncratic-volatility** stocks: [Fang & Peress](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x), [Da et al.](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x), [Gurun & Butler](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x), [Tetlock 2011](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information). This is precisely where a small research tool's assumed transaction costs are most wrong.

**4. Post-publication and out-of-sample decay is documented, and large.** McLean & Pontiff (2016), "Does Academic Research Destroy Stock Return Predictability?" *Journal of Finance* 71(1):5–32, DOI [10.1111/jofi.12365](https://doi.org/10.1111/jofi.12365) **[abstract-level, full abstract retrieved]**:

> "We study the **out-of-sample and post-publication return predictability of 97 variables** shown to predict cross-sectional stock returns. **Portfolio returns are 26% lower out-of-sample and 58% lower post-publication.** The decline is an **upper bound estimate of data mining effects.** … **Post-publication declines are greater for predictors with higher in-sample returns, and portfolios concentrated in stocks with high idiosyncratic risk and low liquidity.** Predictor portfolios exhibit post-publication increases in correlations with other published-predictor portfolios."
> ([OpenAlex record with full abstract](https://api.openalex.org/works?filter=title.search:does%20academic%20research%20destroy%20stock%20return%20predictability))

**The single most important number in this report for expectation-setting.** Implement a published text or news signal and the base rate is roughly **a quarter less than reported out-of-sample and ~58% less post-publication**, with worse shrinkage for the highest-reported effects and for illiquid, high-idiosyncratic-risk portfolios — which, per point 3, is exactly where news signals live.

**5. Regime dependence.** Garcia's predictability exists only in recessions ([abstract](https://colab.ws/articles/10.1111%2Fjofi.12027)); news sentiment is not a stationary relationship.

**6. The stated causal claim is self-undermining for alpha.** If media's causal role is to move **trading** rather than **information** (Engelberg & Parsons), a news signal proxies for **who is paying attention**, not **what is true** — and any edge is behavioural/liquidity-based, decaying as attention infrastructure improves. Lopez-Lira & Tang find exactly this on the LLM side: predictive ability "declines as LLM adoption rises" ([arXiv:2304.07619 abstract](https://arxiv.org/abs/2304.07619)).

---

## Part C — Making documents machine-analysable

> **Companion document.** The full annotation/LLM review, with its own 22-item verified fetch log and 13-item failed-fetch log, is committed alongside this file at [`docs/research/machine-analysable-filings.md`](machine-analysable-filings.md). What follows is the condensed evidence and its consequences for the two answers.

### C1. Annotating and enriching filings: what actually helps

**The honest state of labelled financial-text datasets.** Documented inter-annotator agreement is **thin**, and where reported it is mediocre:

| Dataset / task | What is annotated | Size | Annotation & agreement | Downstream predictive validity |
|---|---|---|---|---|
| **FinancialPhraseBank** — Malo, Sinha, Korhonen, Wallenius & Takala (2014), *JASIST* 65; [arXiv:1307.5336](https://arxiv.org/pdf/1307.5336) | Sentence polarity (pos/neg/neu) "from an investor's viewpoint" | ~5,000 sampled from 53,400; released corpus **4,840** | **16 annotators**, 5–8 each; **ICC 0.649–0.818** on a 150-sentence subset; lowest agreement positive-vs-neutral (75.2%) | **None shown** — classification benchmark only |
| **FinCausal 2020** — [ACL Anthology](https://aclanthology.org/2020.fnp-1.3/) | Cause/effect chunk tagging | 29,444 sections; only **7.24%** causal | Iterative BRAT; **no kappa reported** | **None shown** |
| **FinSBD-2020** — [ACL Anthology](https://aclanthology.org/2020.finnlp-1.8/) | Sentence/list/list-item boundaries (depth 1–4) in English + French **prospectuses** | 41 documents | Two analysts + third reviewer; **no agreement statistic**; five ambiguity classes | **None — but the F1 is itself the finding** |
| **FinNum (NTCIR-14)** | Numeral category in financial tweets | 4,072/457/753 tweets; 8,868 numerals | **Full-agreement numerals only**; IAA never quantified | **None shown** |
| **GRAB** — Li & Ma, [arXiv:2509.21698](https://ar5iv.labs.arxiv.org/html/2509.21698) | Item 1A risk-factor topics | 1.61M Item 1A sentences, 8,247 S&P 500 10-Ks, 2001–2025 | **Weak, non-human labels** (FinBERT attention + YAKE + taxonomy matching) | N/A — see accuracy below |

**The numbers that should change the architecture:**

- **Narrative PDFs are hard to segment at all.** FinSBD-2020's best system reached a **mean F1 of 0.445** on sentence/list boundary detection across prospectuses ([full text](https://aclanthology.org/2020.finnlp-1.8/)). If you cannot reliably cut a document into sentences and items, **section-level sentiment on PDF annual reports is built on sand.** US 10-Ks fetched as HTML/text are materially easier than those prospectus PDFs, but UK annual reports and iXBRL renderings are closer to the FinSBD case. **UNVERIFIED: a FinSBD-style boundary benchmark on UK annual reports or iXBRL.**
- **Generic word-count dictionaries are a poor baseline.** FinSBD's `W-Loughran` word-count baseline scored **positive-class F1 0.204** on FinancialPhraseBank ([full text](https://arxiv.org/pdf/1307.5336)) — independent confirmation of Part A1's claim from a completely different team.
- **Automated risk-category recovery is weak.** GRAB's best model reached **accuracy 0.38 / macro-F1 0.41** on 2024–25 Item 1A sentences ([full text](https://ar5iv.labs.arxiv.org/html/2509.21698)). The design detail that matters: a **fixed chronological split (train ≤2022, dev 2023, test 2024–25) "to avoid look-ahead"** — correct discipline, and rare.
- **Coherence metrics do not discriminate.** GRAB reports Topic BERTScore uniformly **0.82–0.84** across models whose macro-F1 ranges from 0.18 to 0.41 ([full text](https://ar5iv.labs.arxiv.org/html/2509.21698)). Do not validate topic extraction with coherence scores.

**XBRL — what it standardised, and the evidence it helped.** The SEC's 2009 mandate applied to **financial statements**: "In 2009, the SEC mandated that **financial statements** be filed using XBRL" ([Blankespoor, Miller & White 2014, *Review of Accounting Studies* 19(4):1468–1503, abstract via EconPapers](https://econpapers.repec.org/article/sprreaccs/v_3a19_3ay_3a2014_3ai_3a4_3ad_3a10.1007_5fs11142-013-9273-4.htm)). The market evidence is **negative-to-mixed**: that difference-in-differences study finds **higher abnormal bid-ask spreads** for XBRL adopters around 10-K filings the year after the mandate, **reduced abnormal liquidity**, and **lower abnormal trading volume**, especially small trades; the authors conclude the reduction in data-aggregation costs "may not have served its intended purpose of levelling the informational playing field." **UNVERIFIED: coefficient/standard-error magnitudes** (abstract only). A separate non-peer-reviewed Finnish ESEF study (2017–2024, firm and two-way fixed effects, LSEG I/B/E/S consensus) finds **no statistically significant improvement in analyst forecast accuracy** after ESEF adoption ([Hanken MSc thesis via helda.helsinki.fi](https://helda.helsinki.fi/server/api/core/bitstreams/957e3226-8587-458c-b662-add43ce4fb86/content)), and itself reports contrary prior findings. **Sources disagree; report both.**

> **Important gap:** SEC.gov blocked automated access (HTTP 403) during this research. The widely repeated claim that **MD&A, Item 1A risk factors and footnotes are outside XBRL** is therefore **UNVERIFIED against a primary SEC source here.** Verify directly against SEC.gov or 17 CFR Part 232 before relying on it. For this tool it matters less than it appears: the tool reads filing **text**, so the qualitative content is available regardless of XBRL coverage.

**Section-level vs whole-document — three independent confirmations that section matters.**
1. **Lazy Prices:** informativeness concentrates in the **CEO/CFO language, litigation, and risk-factor** sections ([NBER abstract](https://www.nber.org/papers/w25084)).
2. **Li (2010):** the working signal is **MD&A forward-looking statements**, not whole-filing tone ([EconPapers abstract](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm)).
3. **FinQA:** table-only **45.81%** vs text-only **15.80%** vs combined **61.22%** execution accuracy ([full text](https://arxiv.org/pdf/2109.00122)) — narrative and numbers are **complementary**, and for numerical questions **the numbers carry most of the load**.

### C2. LLM extraction of qualitative signals: published validation and error modes

**First, a citation trap: there are two different "FinBERT" papers, routinely conflated.**

1. **Araci (2019)**, [arXiv:1908.10063](https://arxiv.org/pdf/1908.10063) — the original. Verified full text: FinancialPhraseBank **accuracy 0.86 / F1 0.84** on all data, **0.97 / 0.95** on the 100%-agreement subset. Reports FiQA Task 1 MSE 0.07 / R² 0.55 but **explicitly warns that competitors' 0.08/0.40 and 0.09/0.41 are on the official test set while FinBERT's are 10-fold CV — not like-for-like.** Also a negative result: **further in-domain pre-training was not significantly better than vanilla BERT** (vanilla BERT already 0.96 on the all-agree subset).
2. **Huang, Wang & Yang (2023)**, "FinBERT: A Large Language Model for Extracting Information from Financial Text," *Contemporary Accounting Research*, DOI [10.1111/1911-3846.12832](https://doi.org/10.1111/1911-3846.12832) — the accounting-literature paper. Full text blocked (Wiley/HKUST/SSRN all 403); the **publisher abstract** was verified: FinBERT "substantially outperforms the Loughran and McDonald dictionary and other machine learning algorithms … in sentiment classification," "excels in identifying the positive or negative sentiment of sentences that other algorithms mislabel as neutral," its advantage is "especially salient when the training sample size is small and in texts containing financial words not frequently used in general texts," and "other approaches **underestimate the textual informativeness of earnings conference calls by at least 18%** compared to FinBERT" ([CoLab abstract](https://colab.ws/articles/10.1111%2F1911-3846.12832)). **UNVERIFIED: its exact benchmark accuracies and datasets** — do not attribute Araci's numbers to this paper or vice versa.

**LLM vs domain model, with measured error modes.** Fatouros et al. (2023), [arXiv:2308.07935](https://ar5iv.labs.arxiv.org/html/2308.07935) — 2,291 forex headlines over 86 days, manually annotated by short-term impact:

| Model | Accuracy | F1 | S-MAE |
|---|---|---|---|
| FinBERT (Araci) | 0.561 | 0.556 | 0.540 |
| GPT-3.5, prompt P2 | **0.790** | **0.790** | 0.227 |
| GPT-3.5, prompt P4 | 0.784 | 0.789 | 0.221 |
| GPT-3.5, prompt P1 | 0.730 | — | — |

**Three measured error modes to design around:** (i) **prompt sensitivity of ~6 percentage points** (0.730 → 0.790) from framing alone; (ii) **entity-mention dependence** — 75.6% of headlines name the asset up front, and on the rest GPT-P2 drops to 0.711 accuracy / 0.714 F1 while FinBERT drops to 0.543; (iii) **domain polarity inversion** (a positive event for one currency is negative for its pair). Caveats: single 86-day window, one asset class, **no IAA reported**, no replication found.

**The contamination result you must design around — Glasserman & Lin (2023), [arXiv:2309.17322](https://ar5iv.labs.arxiv.org/html/2309.17322).** They **anonymised company names** ("Blahblahblah" + up to 20 knowledge-graph products) in 129,431 scraped headlines / 6,723 companies and 181,908 Thomson Reuters headlines / 678 S&P 500 names; in-sample = Jan 2015–Sep 2021 (GPT-3.5's training window), out-of-sample = Oct 2021–Dec 2022, temperature 0.

- **In-sample, the anonymised headlines produced HIGHER long-short returns** (equal-weighted, 1-day, **no costs**): **+5.89 bps/day (p = 0.066)** for the scraped set and **+4.37 bps/day (p = 0.017)** for the TR set.
- Their conclusion is subtle: because look-ahead bias can only help, this implies a **"distraction effect"** — general entity knowledge does *more harm than good* — which **outweighs** look-ahead bias. The bias is therefore **not even reliably positive.**
- **Overconfidence is measured:** original responses were wrong **17.6%** of the time vs **38.95%** when anonymised, yet when the original was wrong and the replaced answer neutral, the original strategy lost **242 bps** vs **97 bps** in the reverse case.
- Verbatim failures: *"Facebook not planning to extend European privacy law globally"* → original "YES (good)", replaced "NO"; **the stock fell 0.6%** and the anonymised answer was right. *"Pfizer to buy Allergan in 160 billion deal"* → original "NO" for Allergan, replaced "YES"; **the stock rose ~6%** and the anonymised answer was right again.
- The authors state the strategies are "**not intended to be feasible**," ignore transaction costs and short-sale constraints, and that even the OOS window is not cost-adjusted.

**Numeric reasoning through an LLM fails predictably — FinQA (Chen et al., EMNLP 2021, [arXiv:2109.00122](https://arxiv.org/pdf/2109.00122)).** 8,281 expert-written QA pairs over S&P 500 earnings reports 1999–2019, written by 11 finance professionals with a **gold reasoning program** each. Best system **65.05%** execution accuracy; expert humans **91.16%**; non-expert crowd **50.68%**. Decomposition: **table-only 45.81%**, **text-only 15.80%**, combined 61.24%; reasoning depth **1-step 67.61% → 2-step 59.08% → >2 steps 22.78%**; programs needing constants (billion↔million) **43.88%**.

**Consolidated error-mode table for LLM-based filing/news extraction:**

| Error mode | Measured magnitude | Source |
|---|---|---|
| Training-data contamination / look-ahead | In-sample LLM strategy beat anonymised by −5.89 bps/day (bias present; direction not reliably favourable) | [Glasserman & Lin](https://ar5iv.labs.arxiv.org/html/2309.17322) |
| Entity-distraction effect | Anonymisation *improved* in-sample returns (+4.37 to +5.89 bps/day) | same |
| Overconfidence on wrong answers | 242 bps vs 97 bps asymmetry | same |
| Prompt sensitivity | ~6 pp accuracy swing | [Fatouros et al.](https://ar5iv.labs.arxiv.org/html/2308.07935) |
| Entity-mention dependence | 0.790 → 0.711 accuracy on headlines not naming the entity | same |
| Multi-step numeric failure | 67.61% → 22.78% | [FinQA](https://arxiv.org/pdf/2109.00122) |
| Unit conversion | 43.88% | same |
| Text-only insufficiency | 15.80% vs 61.24% combined | same |
| Generic dictionaries fail | positive-class F1 0.204 | [Malo et al.](https://arxiv.org/pdf/1307.5336); [Li 2010](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm) |
| Context/negation/polarity shifters | 43.0% of annotation difficulty = "need more context"; 8.7% polysemy | [Malo et al.](https://arxiv.org/pdf/1307.5336) |
| Boilerplate creating spurious topics | macro-F1 ≤ 0.41; coherence 0.82–0.84 non-discriminative | [GRAB](https://ar5iv.labs.arxiv.org/html/2509.21698) |
| PDF structure is unreliable | best boundary F1 0.445 | [FinSBD-2020](https://aclanthology.org/2020.finnlp-1.8/) |

> **UNVERIFIED:** I found **no direct measurement of LLM run-to-run output inconsistency on filings**. Glasserman & Lin's temperature-0 setting implies the concern but does not measure it. If the pipeline caches LLM extractions, treat non-determinism as unquantified and test it yourself.

**One positive note.** Lopez-Lira & Tang ([arXiv:2304.07619](https://arxiv.org/abs/2304.07619)), using **post-knowledge-cutoff headlines**, report a ~90% portfolio-day hit rate for the **non-tradable initial reaction** — which must **not** be quoted as a trading result — and that GPT-4 scores significantly predict subsequent **drift**, especially in **small stocks and negative news**, with ability increasing in model size; strategy returns **decline as LLM adoption rises**. **UNVERIFIED: return spreads and t-statistics** (abstract only).

### C3. Narrative vs numbers: how much should text count?

**What the evidence does support.**

1. **Text adds information beyond accounting variables, in sign and significance.** Li (2010): "The average tone of the FLS is **positively associated with future earnings even after controlling for other determinants of future performance**," and MD&A tone **mitigates accruals mispricing** — when tone "warns" about accruals, "accruals are **not** associated with future returns" ([EconPapers abstract](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm)).
2. **Text and numbers are complements, and numbers dominate for numerical questions.** FinQA: table-only 45.81%, text-only 15.80%, combined 61.22% ([full text](https://arxiv.org/pdf/2109.00122)).
3. **The strongest verified text signal is a *change*, not a *score*.** Lazy Prices reports **abnormal (factor-adjusted)** returns from year-over-year filing-text change, up to 188 bps/month, 1995–2014, with no LLM-contamination exposure, no annotation cost, and a deterministic, reproducible computation ([NBER abstract](https://www.nber.org/papers/w25084)). If you weight one text signal above all others, weight this one.
4. **A score optimised for returns is not the same object as one optimised for classification accuracy.** Ke, Kelly & Xiu (2019) construct a sentiment score explicitly "to be optimal for return prediction" (screening → topic-model weights → penalised-likelihood aggregation) on Dow Jones Newswires ([NBER WP 26186](https://www.nber.org/papers/w26186)). The abstract reports it "excels at extracting return-predictive signals" with **no Sharpe/alpha/R²/IC given** — so the *conceptual* point is verified, not a number.

**The biggest evidence gap in this review, stated plainly.** **UNVERIFIED: no source retrieved quantifies the optimal *weight* to place on text versus accounting data in a decision rule, and no verified incremental R² or information coefficient of text beyond value, profitability and accruals factors.** Li (2010)'s magnitude is paywalled; Ke–Kelly–Xiu's is absent from the abstract; Lazy Prices reports portfolio alphas, not incremental R². **Anyone offering a figure like "text should be 20% of the decision" is not citing this literature — there is no such number here.** The honest position: text is a **conditioning/tilting input** whose weight must be calibrated on your own data, with the McLean & Pontiff shrinkage applied as a prior.

---

## Two concrete answers

### Answer 1 — Which textual markers are worth implementing for an annual-report reader, in priority order

Priority is set by **(evidence strength × incremental information over numbers) ÷ implementation cost**, deliberately putting the cheapest highest-confidence work first.

**Tier 1 — build first. High evidence, low cost, no licence, no LLM.**

1. **Year-over-year textual similarity of the filing, by section.** The strongest verified filing-level return result in this review: up to 188 bps/month on the risk-factor section, 34–58 bps/month headline, 1995–2014, with an independently supported attention mechanism (FOIA EDGAR download logs) and corroboration from Brown & Tucker (MD&A modification → price response). Score **Item 1A (risk factors), Item 7 (MD&A), and CEO/CFO- and litigation-related language separately** — Lazy Prices says informativeness concentrates there. **Enforce in code:** treat 34–58 vs 188 bps as a **specification range, not a point estimate**; there is no independent replication of the magnitude; and the 188 bps figure is a sub-portfolio result exposed to multiple-testing bias.
2. **Loughran-McDonald tone and category counts** — negative, positive, uncertainty, litigious, strong modal, weak modal, constraining — computed **on sections, not whole filings**. Justification: it is the only dictionary built inside the financial register, "almost three-fourths" of Harvard-dictionary "negatives" in 10-Ks are not negative in a financial context, and two independent teams (Li 2010; Malo et al.) show generic dictionaries fail. **Free for research, licence required commercially.** Use uncertainty/modals as **risk descriptors**, not return signals.
3. **Fog Index / readability, per section.** Li (2008): lower earnings → harder to read; easier to read → more persistent positive earnings. Lo, Ramos & Rogo's benchmark-beating interaction (MBE 0.163–0.209; 0.299–0.335 with positive discretionary accruals; 0.385–0.419 with high positive accruals; placebo insignificant) is the evidence this is **obfuscation, not bad-news ontology**. Make it decision-useful via You & Zhang: complexity predicts **underreaction and 12-month drift**.

**Tier 2 — next. Real but narrower evidence, moderate cost.**

4. **Risk-factor specificity and risk-factor *changes*.** Hope, Hu & Lu: specificity is positively associated with the 10-K market reaction and improves analysts' risk assessment. Pair with #1 — a *specific change* is the informative event; generic churn is noise.
5. **MD&A tone *change* (not level).** Feldman et al.: incremental to accruals and earnings surprises, with drift into the next earnings announcement, and the increment **depends on the firm's information environment** — gate it on coverage/liquidity.
6. **Forward-looking-statement tone and volume.** Li (2010): FLS tone is associated with future earnings after controls and mitigates accruals mispricing; MD&A information content did **not** improve over time despite regulation. **Filter to forward-looking sentences** — this is not a whole-document score — and a dictionary will not do it (the paper's own conclusion). Expect to need labels or an LLM.

**Tier 3 — descriptive context only, never a standalone trade signal.**

7. **Linguistic imprecision / "weasel words."** Single conference paper, unpublished dictionary, tiny effect (**+1.0% over 10 weeks**, adjusted R² ≈ 0.005), and — critically — the **sign is positive**, so it cannot be a "management is hiding something" bearish flag. Use as a **company-characteristic descriptor** (young, intangible, constrained, high-upside-uncertainty).
8. **Guidance-language bias.** Practically important — >60% of managers' private expectations sit **above** the guidance midpoint — but sparser in UK filings. Use as a **calibration warning on guidance**, not a score.

**Do NOT implement (from this evidence base).**
- **Anything requiring call audio** (voice pitch, vocal dissonance): no audio in the pipeline, and the two headline papers rest on proprietary **Nemesysco LVA** software that Lacerda (2012) publicly criticised as unable to measure what it claims.
- **Q&A evasion as a directional signal:** base rate ~11% of questions get non-answers, and Bamber & Nappert (CAR 2025) argue the "non-answers = bad-news suppression" reading **lacks nuance**.
- **Whole-document tone as a factor:** Li & Ramesh show the *average* 10-K/10-Q filing-date reaction is limited; only the **tone-conditional** cross-section moves.
- **Naive "more coverage = bullish":** Fang & Peress find **no-coverage** stocks earn *higher* returns.

**Three cross-cutting design rules.**
- **Segment before you score.** FinSBD's best structure F1 of 0.445 is the empirical proof that unsegmented narrative text is unreliable input.
- **Prefer changes to levels.** Change specifications difference out firm-fixed writing style, addressing both the reverse-causality and omitted-variable critiques Feng Li's survey raises against this literature.
- **Calibrate thresholds on your own data and shrink by default.** McLean & Pontiff: 26% lower out-of-sample, 58% lower post-publication, worse for the highest in-sample effects and low-liquidity portfolios.

### Answer 2 — How much weight should news sentiment carry relative to accounting fundamentals?

**Short answer: treat news as a small, explicitly bounded *conditioning* input — useful for timing and attention, weak for direction — and let accounting fundamentals carry the decision weight. The evidence does not support giving news sentiment large or independent weight in security selection, and it documents several specific ways over-weighting it destroys returns.**

**What the evidence actually licenses.**

1. **News causally drives *trading*, not *information*.** Engelberg & Parsons hold the information event constant (same S&P 500 earnings announcement) and vary only coverage access across regions: local coverage predicts **local trading**, tracking the timing of local reporting ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01626.x)). Fang & Peress frame media as mattering "even if it does not supply genuine news" ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x)). **News sentiment proxies attention and participation — a *timing and liquidity* variable.** It says when a stock is likely to move on flow; far less about where value is.
2. **The return signature of news attention is pressure followed by reversal.** Tetlock (2007): pessimism → downward pressure → **reversion to fundamentals** ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2007.01232.x)). Da, Engelberg & Gao: attention → prices up **~2 weeks** → **reversal within the year** ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x)). Hillert, Jacobs & Müller: media-driven momentum **reverses long-run** ([abstract](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061)). **A news-sentiment overweight is structurally a bet against yourself beyond a few weeks.** This is the strongest argument for a small weight.
3. **The one news result with genuine fundamental content is narrow.** TSM (2008): **negative** words in **firm-specific** stories forecast **low earnings**, with predictability **largest for fundamentals-focused stories** ([full abstract](https://api.openalex.org/works?filter=title.search:more%20than%20words%20quantifying%20language%20to%20measure%20firms%20fundamentals)). **The highest-value news feature is not "sentiment" — it is "is this a fundamental story, and is it negative?"** That is a classification problem (subject matter + polarity), not a polarity average.
4. **Staleness changes the sign.** Tetlock (2011): returns respond **less** to stale news, and a move on stale news **negatively** predicts next week's return, with reversal larger where retail trading is high ([full abstract](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information)). **The syndication-collapse component is not hygiene — it determines the sign of the news feature.** Collapsed/reprinted coverage should score ~zero information and, if price moved on it, feed in as a **contrarian** input.
5. **Even the best long-history news result is tiny and regime-conditional.** Garcia: **12 bps, one day, only in recessions** ([abstract](https://colab.ws/articles/10.1111%2Fjofi.12027)).
6. **Source bias is measurable and commercially driven.** Gurun & Butler: local media use fewer negative words about local firms, one reason being **local advertising expenditure**, and abnormal positive slant **strongly relates to firm equity values**, most in small, retail-held, illiquid, low-coverage firms ([abstract](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x)). **Un-adjusted sentiment from a source is a biased measurement; source weighting is a validity requirement** — and the bias is largest exactly where the naive signal looks strongest.

**The specific risks of over-weighting news, ranked by damage.**

1. **Post-publication/out-of-sample decay.** McLean & Pontiff, on 97 published predictors: **26% lower out-of-sample, 58% lower post-publication**, with declines **greater for higher in-sample returns and for portfolios concentrated in high-idiosyncratic-risk, low-liquidity stocks**, and post-publication **increases in correlation with other published-predictor portfolios** ([full abstract](https://api.openalex.org/works?filter=title.search:does%20academic%20research%20destroy%20stock%20return%20predictability)). News signals sit in exactly those stocks, so expect the **worst** end of that range.
2. **Reverse causality.** Coverage follows price and volume. The best causal designs exist *because* naive designs are contaminated, and their answer — media moves trading, not information — bounds what a news signal can legitimately claim. **UNVERIFIED: a clean quantitative estimate of coverage-on-returns feedback**; run that measurement yourself.
3. **Momentum laundering.** Media coverage *causes* stronger momentum that reverses long-run ([Hillert et al.](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061)). A news factor not residualised against momentum is partly a momentum factor.
4. **Liquidity/attention confounding.** Every attention result concentrates in small, illiquid, retail-heavy, low-coverage names: [Fang & Peress](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x), [Da et al.](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x), [Gurun & Butler](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x), [Tetlock 2011](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information).
5. **Regime dependence.** Predictability exists in recessions ([Garcia](https://colab.ws/articles/10.1111%2Fjofi.12027)).
6. **Source contamination.** ([Gurun & Butler](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x)).

**Concrete recommendation, with the reasoning exposed.** Set news at a **small weight, explicitly bounded, with a documented cap, and never as a primary selection input**: use it to **tilt and time**, not to **select**.

- **Weighting policy.** Let accounting and filing-text signals determine *which* securities and *what direction*; let news adjust *when* and *how much*. Concretely, news should not move a security across the invest/do-not-invest boundary on its own. If it can, it has more weight than the evidence supports. **(Engineering judgement, not a literature finding — see the flag below.)**
- **Adjust by staleness before use.** Score syndicated/reprinted coverage at ~zero information; where a material price move coincides with *stale* news, treat it as **contrarian** (Tetlock 2011).
- **Adjust by source.** Apply the reliability/bias registry, because the bias is commercially induced and measurable (Gurun & Butler). This is the highest-value use of the news infrastructure already built.
- **Use sensationalism as a reliability feature, and fade its price impact.** Ahern & Sosyura (2015): **ambiguous language plus a broad-appeal, well-known subject predicts lower accuracy**, and investors under-adjust, producing **overreaction then reversal**. Encode "ambiguous language + famous firm" as a *reliability penalty*, and treat price moves on such stories as **mean-reverting** rather than informative. (Setting-specific caveat: the result comes from merger rumours.)
- **Classify before scoring.** Restrict high-weight news features to **negative, firm-specific, fundamentals-focused** stories (TSM 2008). Do not average polarity across all coverage.
- **Shrink by default.** Apply the McLean–Pontiff prior (−26% OOS, −58% post-publication) to any news backtest before believing it, and test with momentum and liquidity controls before calling the residual "news alpha."
- **Test contamination and prompt robustness** if an LLM scores the news: anonymise entities or restrict to post-cutoff text ([Glasserman & Lin](https://ar5iv.labs.arxiv.org/html/2309.17322)), and measure prompt sensitivity (~6 pp in [Fatouros et al.](https://ar5iv.labs.arxiv.org/html/2308.07935)).
- **Note the horizon mismatch.** News effects decay or reverse within weeks; this is an annual-report-based research tool. **Filings text and the news feed operate on different horizons, and the filings side is where the durable signal is.**

> **Honesty flag on Answer 2.** The *direction* — small weight, conditioning role, bounded influence — follows directly from the verified evidence (pressure-then-reversal; trading-not-information; McLean–Pontiff decay). The *specific numeric weight* and the "cannot cross the invest boundary alone" rule are **engineering judgements, not literature findings**. As flagged in C3, **no source in this review quantifies the optimal text-to-fundamentals weight.** Calibrate it on your own out-of-sample data and document it as an assumption.

---

## Fetch log

Everything below was retrieved with the `web_fetch` tool unless marked **[proxy]**. `web_fetch` cannot parse `application/pdf`, so for PDFs the text was retrieved through the `r.jina.ai` text-extraction proxy; the underlying document is the canonical URL cited in the main text and can be opened directly.

**Filings language (Part A)**

| URL | What it confirmed |
|---|---|
| [sraf.nd.edu/loughranmcdonald-master-dictionary](https://sraf.nd.edu/loughranmcdonald-master-dictionary/) | Official LM repository: seven sentiment categories; 2of12inf base extended with EDGAR 10-K + CapIQ earnings-call vocabulary; 1993–2025 coverage; academic-free / commercial licence required |
| [colab.ws/articles/10.1111%2Fj.1540-6261.2010.01625.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01625.x) | LM (2011) publisher abstract verbatim: "almost three-fourths" of Harvard-dictionary negatives in 10-Ks are not negative in a financial context; 10-Ks 1994–2008 |
| [econpapers.repec.org — *JF* 66(1):35–65](https://econpapers.repec.org/article/blajfinan/v_3a66_3ay_3a2011_3ai_3a1_3ap_3a35-65.htm) | Bibliographic verification: JF 66(1):35–65, 1,901 citations |
| [econpapers.repec.org — *JAE* 45(2–3):221–247](https://econpapers.repec.org/article/eeejaecon/v_3a45_3ay_3a2008_3ai_3a2-3_3ap_3a221-247.htm) | Li (2008) publisher abstract verbatim: lower earnings → harder to read; easier to read → more persistent positive earnings |
| [api.unpaywall.org/v2/10.1016/j.jacceco.2008.02.003](https://api.unpaywall.org/v2/10.1016/j.jacceco.2008.02.003) | Li (2008) is closed-access: `is_oa: false`, no repository copy — basis of the effect-size UNVERIFIED flag |
| [business.uq.edu.au/…/kin-lo-paper.pdf](https://business.uq.edu.au/sites/default/files/events/files/kin-lo-paper.pdf) **[proxy]** | Lo/Ramos/Rogo full text: 26,967 firm-years, 4,855 firms, 2000–2012; MBE 0.163–0.209; MBE×PosDA 0.299–0.335; MBE×HighPosDA 0.385–0.419; placebo t=0.445; Fog→misstatement 0.025 (p=0.027); Fog mean ≈18.0 |
| [api.openalex.org — "earnings management and annual report readability"](https://api.openalex.org/works?filter=title.search:earnings%20management%20and%20annual%20report%20readability) | Published as *JAE* 63(1):1–25 (2017), DOI 10.1016/j.jacceco.2016.09.002, 812 citations |
| [colab.ws/articles/10.1007%2Fs11142-009-9111-x](https://colab.ws/articles/10.1007%2Fs11142-009-9111-x) | Feldman/Govindaraj/Livnat/Segal abstract: tone change → short-window filing reaction and post-filing drift, incremental to accruals and earnings surprises; depends on information environment |
| [econpapers.repec.org — *JAR* 48(5):1049–1102](https://econpapers.repec.org/article/blajoares/v_3a48_3ay_3a2010_3ai_3a5_3ap_3a1049-1102.htm) | Li (2010) abstract: FLS tone → future earnings after controls; no change in MD&A information content over time; mitigates accruals mispricing; Diction/GI/LIWC fail to predict |
| [cuhk.edu.hk/…/20110215FengLI/Paper1.pdf](https://www.cuhk.edu.hk/acy2/workshop/20110215FengLI/Paper1.pdf) **[proxy]** | Li (2011) survey full text: obfuscation-vs-ontology debate; Lehavy/Li/Merkley result and its non-causality caveat; Li & Ramesh limited filing reaction; Brown & Tucker MD&A modification → price response; the General Inquirer failure example; the publication-selection-bias warning; endogeneity and "who writes the disclosure" caveats |
| [colab.ws/articles/10.1007%2Fs11142-008-9083-2](https://colab.ws/articles/10.1007%2Fs11142-008-9083-2) | You & Zhang abstract: abnormal 10-K filing price movements → future profitability; 12-month drift; underreaction stronger for complex 10-Ks |
| [colab.ws/articles/10.1007%2Fs11142-013-9258-3](https://colab.ws/articles/10.1007%2Fs11142-013-9258-3) | Campbell et al. (2014) abstract: riskier firms disclose more; risk type shapes disclosure; info in systematic/idiosyncratic risk, asymmetry, firm value |
| [colab.ws/articles/10.1007%2Fs11142-016-9371-1](https://colab.ws/articles/10.1007%2Fs11142-016-9371-1) | Hope/Hu/Lu abstract: Specificity positively associated with the 10-K filing market reaction; analysts assess risk better |
| [colab.ws/articles/10.1016%2Fj.jacceco.2017.07.002](https://colab.ws/articles/10.1016%2Fj.jacceco.2017.07.002) | Dyer/Lang/Stice-Lawrence abstract: 1996–2013 increases in length/boilerplate/stickiness/redundancy, decreases in specificity/readability; 3 of 150 topics drive it |
| [cirforum.org/2019forum_papers/CIRF2019_paper_20.pdf](https://cirforum.org/2019forum_papers/CIRF2019_paper_20.pdf) **[proxy]** | "Some People Say" full text: Wikipedia weasel-tag dictionary; 1997–2015, 44,207 firm-years; fluidity 0.088, constraints 0.041; Imprecision → +0.010 BHAR over 10 weeks; upside volatility +0.021; orthogonality to LM categories |
| [nber.org/papers/w25084](https://www.nber.org/papers/w25084) | Lazy Prices abstract: 1995–2014; up to 188 bps monthly alpha; CEO/CFO, litigation, risk-factor changes most informative; no announcement effect; *JF* 75(3):1371–1415 (2020) |
| [nber.org/digest/nov18/w25084](http://www2.nber.org/digest/nov18/w25084.shtml) | Decomposition: 34–58 bps/month headline vs 188 bps/month risk-factor; 86% negative-sentiment changes; 14% positive changes predict positive returns; drift up to 18 months, not reversed; unrelated to size/time/industry; FOIA EDGAR download-log evidence |
| [arxiv.org/abs/2405.13319](https://arxiv.org/abs/2405.13319) | Hedge-detection paper abstract: joint word+POS model, new top score on CoNLL-2010 Wikipedia corpus (F1 not in abstract) |
| [colab.ws/articles/10.1111%2F1911-3846.12832](https://colab.ws/articles/10.1111%2F1911-3846.12832) | Huang/Wang/Yang FinBERT abstract: beats LM dictionary and ML baselines; excels on sentences others call neutral; underestimate of call textual informativeness by ≥18%; training-size sensitivity |

**News and media (Part B)**

| URL | What it confirmed |
|---|---|
| [colab.ws/articles/10.1111%2Fj.1540-6261.2007.01232.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2007.01232.x) | Tetlock (2007) abstract verbatim: pessimism → downward pressure then reversion to fundamentals; volume effect; explicitly *inconsistent* with media as fundamental news |
| [api.openalex.org — "more than words…"](https://api.openalex.org/works?filter=title.search:more%20than%20words%20quantifying%20language%20to%20measure%20firms%20fundamentals) | TSM (2008) full abstract: negative word fraction forecasts low earnings; brief underreaction; largest for fundamentals-focused stories; *JF* 63(3):1437–1467; 2,300 citations |
| [api.openalex.org — "all the news that's fit to reprint…"](https://api.openalex.org/works?filter=title.search:all%20the%20news%20that's%20fit%20to%20reprint%20do%20investors%20react%20to%20stale%20information) | Tetlock (2011) full abstract: staleness = similarity to previous ten stories; less response to stale news; day-of-stale-news return negatively predicts next week; retail trading amplifies reversal; *RFS* 24(5):1481–1512 |
| [colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2009.01493.x) | Fang & Peress abstract: no-coverage stocks earn *higher* returns; stronger in small, high-individual-ownership, low-analyst-following, high-idio-vol stocks |
| [colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2011.01679.x) | Da/Engelberg/Gao abstract: Russell 3000 2004–2008; SVI → higher prices next 2 weeks → reversal within the year; IPO first-day return and long-run underperformance |
| [colab.ws/articles/10.1111%2Fj.1540-6261.2010.01626.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2010.01626.x) | Engelberg & Parsons abstract: 19 trading regions, S&P 500 earnings announcements; local coverage predicts local trading after controls; timing of local reporting |
| [colab.ws/articles/10.1093%2Frfs%2Fhhu061](https://colab.ws/articles/10.1093%2Frfs%2Fhhu061) | Hillert/Jacobs/Müller abstract: 2.2M articles, 45 newspapers, 1989–2010; media-covered firms show stronger momentum; long-run reversal; overreaction interpretation |
| [colab.ws/articles/10.1111%2Fjofi.12027](https://colab.ws/articles/10.1111%2Fjofi.12027) | Garcia (2013) abstract: NYT 1905–2005; predictability concentrated in recessions; 1 SD → 12 bps one-day DJIA conditional average return |
| [colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x](https://colab.ws/articles/10.1111%2Fj.1540-6261.2012.01725.x) | Gurun & Butler abstract: local media fewer negatives about local firms, driven by local advertising spend; abnormal positive slant relates to equity values; strongest in small/retail/illiquid/low-coverage |
| [api.openalex.org — "does academic research destroy stock return predictability"](https://api.openalex.org/works?filter=title.search:does%20academic%20research%20destroy%20stock%20return%20predictability) | McLean & Pontiff full abstract: 97 predictors; 26% lower OOS, 58% lower post-publication; greater declines for high in-sample returns, high idio risk, low liquidity; *JF* 71(1):5–32 |
| [colab.ws/articles/10.1093%2Frfs%2Fhhv006](https://colab.ws/articles/10.1093%2Frfs%2Fhhv006) | Ahern & Sosyura (2015) sensationalism abstract: accuracy predicted by journalist experience/education/expertise; less accurate stories use **ambiguous language** and feature **well-known broad-appeal firms**; investors under-adjust → target-price overreaction then reversal |
| [api.openalex.org — "media coverage and the cross-section of stock returns"](https://api.openalex.org/works?filter=title.search:media%20coverage%20and%20the%20cross-section%20of%20stock%20returns) | Correct DOI and citation (10.1111/j.1540-6261.2009.01493.x; *JF* 64(5):2023–2052) after two wrong-DOI guesses |

**Machine-analysable documents and LLM validation (Part C)** — condensed; the companion [`machine-analysable-filings.md`](machine-analysable-filings.md) carries the full 22-item verified log.

| URL | What it confirmed |
|---|---|
| [arXiv:1307.5336 full text](https://arxiv.org/pdf/1307.5336) and [HTML](https://ar5iv.labs.arxiv.org/html/1307.5336) | FinancialPhraseBank: construction, 16 annotators, ICC 0.649–0.818, agreement tiers, per-class results, the 0.204 positive-class word-count baseline, error-type distribution |
| [huggingface.co/datasets/takala/financial_phrasebank](https://huggingface.co/datasets/takala/financial_phrasebank) | Released corpus 4,840 sentences; four agreement-tier configs; JASIST 2014 citation |
| [FinCausal 2020](https://aclanthology.org/2020.fnp-1.3/) | 29,444 sections, 7.24% causal, best weighted F1 97.75, **no kappa reported** |
| [FinSBD-2020](https://aclanthology.org/2020.finnlp-1.8/) | 41 prospectuses, two analysts + third reviewer, five ambiguity classes, **best mean boundary F1 0.445** |
| [FinNum NTCIR-14 PDF](https://research.nii.ac.jp/ntcir/workshop/OnlineProceedings14/pdf/ntcir/01-NTCIR14-OV-FINNUM-ChenC.pdf) | Full-agreement-only dataset; best micro-F1 93.94 / 87.17; weak subcategories (selling price 50%, stop loss 50%) |
| [GRAB, arXiv:2509.21698](https://ar5iv.labs.arxiv.org/html/2509.21698) | 1.61M Item 1A sentences, 8,247 10-Ks 2001–2025; weak labels; chronological split to avoid look-ahead; best macro-F1 0.41; topic BERTScore uniformly 0.82–0.84 |
| [Blankespoor/Miller/White via EconPapers](https://econpapers.repec.org/article/sprreaccs/v_3a19_3ay_3a2014_3ai_3a4_3ad_3a10.1007_5fs11142-013-9273-4.htm) | 2009 XBRL mandate on financial statements; higher spreads, lower liquidity/volume post-mandate; "may not have served its intended purpose" |
| [Finnish ESEF thesis](https://helda.helsinki.fi/server/api/core/bitstreams/957e3226-8587-458c-b662-add43ce4fb86/content) | ESEF 2017–2024: no significant analyst-forecast-accuracy improvement; non-peer-reviewed; reports contrary prior findings |
| [Araci FinBERT, arXiv:1908.10063](https://arxiv.org/pdf/1908.10063) | FPB 0.86/0.84 and 0.97/0.95; FiQA MSE 0.07/R² 0.55 with the author's own test-set-vs-CV caveat; further pre-training not significantly better |
| [Fatouros et al., arXiv:2308.07935](https://ar5iv.labs.arxiv.org/html/2308.07935) | 2,291 headlines / 86 days; full FinBERT-vs-GPT table; prompt sensitivity 0.730→0.790; 75.6% entity-mention statistic and 0.711 degraded accuracy |
| [Lopez-Lira & Tang, arXiv:2304.07619](https://arxiv.org/abs/2304.07619) | Post-cutoff design; ~90% non-tradable portfolio-day hit rate; drift for small stocks and negative news; returns decline with LLM adoption |
| [Glasserman & Lin, arXiv:2309.17322](https://ar5iv.labs.arxiv.org/html/2309.17322) | In/out-of-sample windows; anonymisation method and hit counts; +5.89 bps (p=0.066) and +4.37 bps (p=0.017); 242 vs 97 bps asymmetry; two verbatim failure examples; infeasibility caveat |
| [FinQA, arXiv:2109.00122](https://arxiv.org/pdf/2109.00122) | 8,281 expert QA pairs 1999–2019; best 65.05%; expert 91.16%; crowd 50.68%; table-only 45.81 / text-only 15.80 / combined 61.24; 1-step 67.61 → >2-step 22.78; constants 43.88 |
| [Ke/Kelly/Xiu, NBER WP 26186](https://www.nber.org/papers/w26186) | Return-optimised sentiment construction on Dow Jones Newswires; abstract reports predictive success with **no** effect size |

**Attempted and failed (recorded so the gaps are auditable)**

| URL | Failure |
|---|---|
| [onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2010.01625.x](https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2010.01625.x) | HTTP 403 (Cloudflare) — LM (2011) full text not obtained |
| [papers.ssrn.com/sol3/papers.cfm?abstract_id=1331573](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1331573) | HTTP 403 "Content Blocked" |
| [sciencedirect.com/…/S0165410108000141](https://www.sciencedirect.com/science/article/abs/pii/S0165410108000141) | HTTP 403 (IP blocked) — Li (2008) full text not obtained; reproduced via headless browser with the same block |
| [onlinelibrary.wiley.com/doi/abs/10.1111/1475-679X.12123](https://onlinelibrary.wiley.com/doi/abs/10.1111/1475-679X.12123) | HTTP 403 — LM (2016) survey full text not obtained |
| [research.chicagobooth.edu/…/8cf9e95e…pdf](https://research.chicagobooth.edu/~/media/8cf9e95e14144f52b32a687c33cd1557.pdf) **[proxy]** | Returned only the 4-page JAR **data-policy datasheet**, not the survey body |
| [knowledge.insead.edu/…/soft-information-or-cheap-talk](https://knowledge.insead.edu/leadership-organisations/soft-information-or-cheap-talk-company-announcements) | HTTP 403 |
| [sec.gov/structureddata](https://www.sec.gov/structureddata) and [sec.gov/education/smallbusiness/xbrl](https://www.sec.gov/education/smallbusiness/xbrl) | HTTP 403 "Request Rate Threshold Exceeded" — XBRL scope claim unverified against a primary SEC source |
| [dl.acm.org/doi/fullHtml/10.1145/3184558.3192301](https://dl.acm.org/doi/fullHtml/10.1145/3184558.3192301) | HTTP 403 — FiQA primary source |
| [damore-mckim.northeastern.edu/…/5_NarrativeAssetPricing.pdf](https://damore-mckim.northeastern.edu/wp-content/uploads/2022/05/5_NarrativeAssetPricing.pdf) | HTTP 404 — Bybee/Kelly/Su Narrative Asset Pricing |
| [colab.ws/articles/10.2308%2Faccr.2011.86.3.1087](https://colab.ws/articles/10.2308%2Faccr.2011.86.3.1087) | HTTP 404 — failed attempt to verify Lehavy/Li/Merkley by DOI |

**Papers named in search results but NEVER fetched — explicitly NOT cited as evidence in this report:** Hong, Lim & Stein "Bad news travels slowly"; Bamber & Nappert (CAR 2025); Gow, Larcker & Zakolyukina (2021); Bozanic, Roulstone & Van Buskirk (2018); Call, Hribar, Skinner & Volant (2024); Koo & Yeung; Hirst, Koonce & Venkatraman (2008); Larcker & Zakolyukina (2012); Mayew & Venkatachalam (2012); Hobson, Mayew & Venkatachalam (2012); Hollander, Pronk & Roelofsen (2010); Price, Doran, Peterson & Bliss; Muslu et al. (2015); Dzielinski, Wagner & Zeckhauser; Jegadeesh & Wu (2013). Where one of these is named above (the earnings-call and Q&A findings in Answers 1 and 2), it is reported from the separate earnings-call research stream's own retrieval — its source document is [`docs/research/`](.) in this repository — and **the journal-attribution corrections it produced are: Davis/Piger/Sedor is *Contemporary Accounting Research*, not *The Accounting Review*; Mayew & Venkatachalam "The Power of Voice" is *Journal of Finance* 67(1), 2012, not *The Accounting Review*; Hirst/Koonce/Venkataraman (2008) is "Management Earnings Forecasts: A Review and Framework," *Accounting Horizons* 22(3).**

---

## Consolidated UNVERIFIED list — what is missing and why

| # | Claim that could not be verified | What is missing / why |
|---|---|---|
| 1 | Li (2008) coefficient magnitudes, t-statistics, exact sample size and period | Closed-access; Elsevier IP-blocks this environment; Unpaywall confirms no repository copy |
| 2 | LM (2011) effect sizes linking word lists to returns/volatility/fraud | Wiley 403; SSRN 403; only the publisher abstract reachable |
| 3 | LM dictionary negative/positive word counts (e.g. the often-quoted "2,355 negative words") | Dictionary files are on Google Drive, not fetchable here; the Notre Dame page gives categories but not counts |
| 4 | Validation of the LM word lists on UK / iXBRL statutory accounts | No such study located; the lists are US-10-K-calibrated |
| 5 | A verified return-spread estimate for the LM **uncertainty** category | Documented for volatility/fraud models, not portfolio spreads; tables closed |
| 6 | Hong, Lim & Stein "bad news travels slowly" and any quantification of asymmetric diffusion | OpenAlex title search returned zero results for the phrasing used; paper not retrieved |
| 7 | Sensationalism/accuracy effect sizes, and the ambiguity measure's construction | Ahern & Sosyura (2015) verified at **abstract level only**: the paper exists, the constructs are described, but accuracy rates, reversal magnitude and the ambiguity measure are behind the paywall |
| 8 | Quantified estimate of reverse causality: how much coverage is caused by prior returns/volume | The best designs establish the media→trading channel but no clean coverage-on-returns feedback estimate was found |
| 9 | Tetlock (2007) exact sample period and pressure/reversion coefficients | Abstract-level only |
| 10 | Lazy Prices turnover, capacity, transaction costs, post-2014 out-of-sample performance | Not in the abstract or the NBER Digest |
| 11 | Optimal weight of text vs accounting data in a decision rule | **No source found.** Any such number is unsupported by this literature |
| 12 | Incremental R² / information coefficient of text beyond value, profitability and accruals | Li (2010) paywalled; Ke–Kelly–Xiu absent from abstract; Lazy Prices reports portfolio alphas only |
| 13 | Huang/Wang/Yang (2023) FinBERT benchmark accuracies and datasets | Wiley, HKUST and SSRN all blocked; only the publisher abstract reachable |
| 14 | LLM run-to-run output inconsistency on filings | Not measured in any source retrieved |
| 15 | SEC's own statement that MD&A / Item 1A / footnotes are outside XBRL | SEC.gov returned HTTP 403 to this environment |
| 16 | Campbell et al. (2014) and Hope/Hu/Lu (2016) portfolio return spreads | Abstracts report risk/asymmetry and market-reaction associations, not alphas |
| 17 | Weasel-word/imprecision dictionary contents | Not published; authors supply it on request |
| 18 | Any UK-specific evidence base for these signals | Essentially the entire predictive literature is US-market; UK replication is unverified |
| 19 | Earnings-call findings (tone, deception, evasion, audio, guidance) | Reported here only at second hand from the separate earnings-call research stream; primary sources were not re-fetched for this document |
