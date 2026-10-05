# Machine-Analysable Company Documents: Evidence Review for an Equity Analysis System

**Scope.** What is actually documented about (1) annotating/enriching filings, (2) LLM/NLP extraction of qualitative signals, (3) the incremental information content of narrative over numbers.

**Method and honesty note.** Every claim below is tied to a page or document I actually retrieved and read. `web_fetch` refuses `application/pdf`, so for PDFs (ACL proceedings, arXiv preprints, open-access working papers) I downloaded the file over HTTPS and extracted text locally with a small stdlib extractor. Those documents were genuinely retrieved and read; the method is disclosed per-item in the Fetch Log so you can reproduce it. Where I could not retrieve a source, the claim is marked **UNVERIFIED** with exactly what is missing. Nothing here is inferred from a search-result snippet.

---

## 1. EVIDENCE-BASED PRACTICES FOR ANNOTATING/ENRICHING FILINGS

### 1.1 Financial PhraseBank — Malo, Sinha, Korhonen, Wallenius & Takala (2014)

**What it is.** Sentence-level polarity annotations (positive / negative / neutral) of financial news, released as a benchmark corpus.

**Source.** "Good debt or bad debt: Detecting semantic orientations in economic texts", *Journal of the American Society for Information Science and Technology*, 65 (2014); preprint arXiv:1307.5336. Retrieved: https://ar5iv.labs.arxiv.org/html/1307.5336 and https://arxiv.org/pdf/1307.5336.

**Sample and construction (verified from full text).**
- English news on **all listed companies on OMX Helsinki**, pulled from **LexisNexis**; **10,000 articles randomly sampled** for coverage across firm size, industry and news source.
- Sentences containing no recognised lexicon entity were dropped, leaving **53,400 sentences**; a random sample of **~5,000** was annotated. The released corpus is **4,840 sentences**.
- **16 annotators**: 3 researchers + 13 Aalto University School of Business master's students majoring mainly in finance, accounting and economics. Annotators judged sentiment **from an investor's viewpoint** ("whether the news may have positive, negative or neutral influence on the stock price").
- **5–8 overlapping annotations per sentence.**

**Inter-annotator agreement (IAA).** Measured on a **subset of 150 sentences tagged by all 16 annotators**. The paper reports intra-class correlation coefficient and other reliability measures **in the range 0.649–0.818**, and judges this "reasonable consistency and reliability". Average pairwise agreement was **lowest (75.2%) for positive-vs-neutral** — the authors attribute this to borderline cases and to "company glitter" being mistaken for positive news.

**Released agreement tiers (counts verified from Table 3).**

| Subset | n | % negative | % neutral | % positive |
|---|---|---|---|---|
| 100% agreement | 2,259 | 13.4 | 61.4 | 25.2 |
| ≥75% agreement | 3,448 | 12.2 | 62.1 | 25.7 |
| ≥66% agreement | 4,211 | 12.2 | 60.1 | 27.7 |
| ≥50% agreement | 4,840 | 12.5 | 59.4 | 28.2 |

The Hugging Face distribution exposes exactly these four configurations (`sentences_allagree`, `_75agree`, `_66agree`, `_50agree`), 5–8 annotators per sentence, licence CC BY-NC-SA 3.0 (https://huggingface.co/datasets/takala/financial_phrasebank and its `financial_phrasebank.py`).

**Reported effect sizes** (10-fold CV; the authors' own Linearized Phrase-Structure model, "LPS"):

| Subset | Class | Accuracy | F1 |
|---|---|---|---|
| 100% agreement | positive | 0.869 | **0.739** |
| 100% agreement | neutral | 0.828 | **0.861** |
| 100% agreement | negative | 0.951 | **0.813** |
| ≥50% agreement | positive | 0.786 | 0.585 |
| ≥50% agreement | neutral | 0.735 | 0.735 (approx.) |

Baselines were far worse: a word-frequency "W-Loughran" model scored **F1 0.204 on positive sentences** (100%-agreement subset). **This is the single most important number for a practitioner**: even a well-engineered dictionary model was near-useless at recovering *positive* financial sentiment from this corpus.

**Documented error modes (LPS, % of errors).** Need for more context **43.0%**; inability to recognise the significance of events **26.7%**; company talking in advertising-like tone **10.0%**; mismatched lexicon items **9.0%**; polysemy **8.7%**; positive convention of talking about something **6.3%**; expressions missing from the lexicon **6.0%**; inability to understand magnitude/value **5.3%**; **inability to detect changes in numbers 4.3%**; **inability to detect roles 4.0%**; inability to detect time expressions **3.3%**; wrong training label **1.0%**.

**Replication / out-of-sample validity.** None in this paper. The corpus is a *classification* benchmark. **No downstream predictive validity (returns, earnings) is established by Malo et al.** Any claim that FinancialPhraseBank-validated models add alpha is unsupported by this source.

**Caveats.** Single small market (OMX Helsinki), news/press releases only (not 10-K narrative), a 2014-era lexicon pipeline, and the labels are "investor-viewpoint polarity", not a return-realised outcome.

### 1.2 FiQA (2018) — **partially verified only**

I could **not** retrieve a primary FiQA source: the ACM full-text page returned **HTTP 403** (bot gate) and the author PDF at `andrefreitas.org/papers/www_fiqa_2018.pdf` was not retrievable. What I *can* verify is the description in a paper I did read (Araci 2019, full text): "FiQA ... is a dataset that was created for WWW'18 conference financial opinion mining and question answering challenge. We use the data for Task 1, which includes **1,174 financial news headlines and tweets** with their corresponding sentiment score. Unlike Financial Phrasebank, the targets for this dataset are **continuous ranging between [-1,1]** with 1 being the most positive. Each example also has information regarding **which financial entity is targeted** in the sentence."

**UNVERIFIED for FiQA:** original URL, exact task definitions, annotation protocol, number of annotators, and any IAA statistic. The 1,174 figure and the aspect/target structure come from a secondary source that cites FiQA, not from FiQA itself.

### 1.3 FinCausal 2020 — Mariko, Abi-Akl, Labidurie, Durfort, De Mazancourt & El-Haj

**Source.** "The Financial Document Causality Detection Shared Task (FinCausal 2020)", *Proceedings of the 1st Joint Workshop on Financial Narrative Processing and MultiLing Financial Summarisation* (FNP-FNS @ COLING 2020), pp. 23–32. Landing page: https://aclanthology.org/2020.fnp-1.3/ ; full text: https://aclanthology.org/2020.fnp-1.3.pdf.

**What is annotated.** Cause→effect spans in financial news, at two levels: **Task 1** binary "does this text section contain a causal scheme"; **Task 2** cause/effect chunk extraction. Annotation scheme also tags *QFact* (quantitative causal chunk containing numerical entities) vs *Fact*, and a *Discard* class for non-financial text.

**Sample (verified).** Corpus of 2019 financial news supplied by Qwam, collected from **14,000 economics and finance websites**; released under CC0.
- Task 1: **29,444 text sections** (8,580 trial / 13,478 practice / 7,386 evaluation); **2,136 causal (7.24%)** — deliberately unbalanced to mirror real news.
- Task 2: **641 / 1,109 / 638** sections (mean 796); mean unicausal 621.67, multicausal 174.33; mean cause chunk 111.78 characters, effect chunk 104.08.

**Annotation process / IAA.** Annotation was **iterative on a BRAT annotation server**: a first annotator proposed annotations, then **two others revised until agreement**; those sessions were used to define and iterate the scheme. **No kappa, alpha or percentage-agreement statistic is reported.** Four named annotators are acknowledged. This is a real methodological weakness: agreement is asserted procedurally, not quantified.

**Reported effect sizes.** Task 1 weighted F1: LIORI **97.75**, UPB 97.55, ProsperAMNet 97.23, FiNLP 96.99, DOMINO 96.12, …, ISIKUN 93.09; **provided baseline 95.23**. Transformer systems span [95.78, 97.75]; non-neural systems [93.09, 95.00]. Task 2: NTUNLPL **94.72**, GBe 94.66, then a large drop to ProsperAMNet 83.71, LIORI 82.60, DOMINO 79.60.

**Caveats.** Task 1 being ~7% positive and news-derived makes very high F1 easy to obtain and hard to interpret as "understanding causality". The organisers themselves note the CRF baseline was "kept deliberately low". **No test that causal annotations predict returns, volatility, or earnings.** Treat the 97% as a ceiling-driven classification number, not evidence of usable causal signal.

### 1.4 FinSBD-2020 (sentence/list boundary detection in prospectus PDFs) — Au, Chong, Ait Azzi & Valsamou-Stanislawski

**Source.** "FinSBD-2020: The 2nd Shared Task on Sentence Boundary Detection in Unstructured Text in the Financial Domain", *Proceedings of the Second Workshop on Financial Technology and Natural Language Processing* (FinNLP @ IJCAI-PRICAI 2020), pp. 47–54. Landing: https://aclanthology.org/2020.finnlp-1.8/ ; full text: https://aclanthology.org/2020.finnlp-1.8.pdf.

**Why it matters for your system.** This is direct, documented evidence that **narrative sections of financial PDFs are not machine-analysable at the sentence level without specialised work**. The task is to find boundaries of sentences, lists and list items (hierarchy levels 1–4) in text extracted from **financial prospectuses**, in English and French, with character-offset outputs.

**Sample and annotation (verified).** **41 documents** annotated. Each document was **annotated independently by two analysts, then reviewed and corrected by a third**. **No IAA statistic is reported.** The paper lists five concrete ambiguity classes that drove disagreement: lists with no visual bullet markers; bullet groups with no semantic relation; title-vs-list-item confusion; inconsistent colon usage; and human errors (missing/incorrect punctuation) requiring interpretation.

**Results (verified).** 5 teams from 4 countries, 4 system papers. Ranking by mean F1 across subtasks and languages (Table 6): PublishInCovid19 **0.445**, aiai 0.359, Daniel 0.145, baseline 0.092, Subtl.ai 0.054, Anuj 0.038. French subtask 1: aiai 0.471, Daniel 0.232, baseline 0.161; French subtask 2: aiai 0.350, all others 0. **The best system recovers well under half of the structure.** English Table 4 values were not captured in my extraction — **UNVERIFIED**.

**Caveats.** Prospectuses, not 10-Ks; very small document count; no downstream test.

### 1.5 FinNum (NTCIR-14) — Chen, Huang, Takamura & Chen

**Source.** "Overview of the NTCIR-14 FinNum Task: Fine-Grained Numeral Understanding in Financial Social Media Data". Full text: https://research.nii.ac.jp/ntcir/workshop/OnlineProceedings14/pdf/ntcir/01-NTCIR14-OV-FINNUM-ChenC.pdf.

**What is annotated.** Every **numeral** in a financial tweet (each tweet contains ≥1 cashtag such as `$AAPL`) is assigned a category from a **7-category taxonomy**, with the most important category *Monetary* extended into **8 subcategories** (e.g. selling price, stop loss, support/resistance, exercise price, maturity date). Subtask 1 = numeral category; subtask 2 = fine-grained subcategory.

**Sample (verified).** Corpus **FinNum 2.0**: **4,072 train / 457 development / 753 test tweets**; **8,868 annotated numerals**. Critically, the dataset "**contains only the numerals in full agreement**" — disagreements were discarded, so agreement is not quantified and the retained set is biased toward easy cases.

**Reported effect sizes.** Best micro-F1: **93.94** (Fortia1-1, subtask 1) and **87.17** (Fortia1-2, subtask 2). Per-category accuracy shows where it breaks: selling price **50%**, stop loss **50%**, support or resistance **70%**, exercise price **71%**, maturity date **62%**, Indicator **81%**; a word-based CNN baseline reached only 55.90 micro-F1 / 51.67 macro-F1.

**Documented error modes.** Quantity confused with Monetary/Temporal; Option subcategories confused with Monetary (exercise price) and Temporal (maturity date); Indicator parameters confused with Temporal; out-of-vocabulary numerals.

**Caveats.** Social media, not filings. **No predictive-validity test** linking numeral categories to returns.

### 1.6 SEC XBRL / structured data — evidence, and the limits

**What was standardised.** From Blankespoor, Miller & White: "**In 2009, the SEC mandated that financial statements be filed using eXtensible Business Reporting Language (XBRL).** The SEC contends that this new search-facilitating technology will reduce informational barriers that separate smaller, less-sophisticated investors from larger, more-sophisticated investors, thereby reducing information asymmetry." Source: *Review of Accounting Studies*, 2014, 19(4):1468–1503, "Initial evidence on the market impact of the XBRL mandate" — abstract retrieved from https://econpapers.repec.org/article/sprreaccs/v_3a19_3ay_3a2014_3ai_3a4_3ad_3a10.1007_5fs11142-013-9273-4.htm. Note the scope as stated: **financial statements**.

**Evidence on whether structured data improved analysis — this is the key finding, and it is negative-to-mixed.**

1. **Blankespoor, Miller & White (2014)** — difference-in-differences around the mandate. They find **higher abnormal bid-ask spreads for XBRL-adopting firms around 10-K filings in the year after the mandate**, "consistent with increased concerns of adverse selection"; **a reduction in abnormal liquidity**; and **a decrease in abnormal trading volume, particularly for small trades**. Additional analyses suggest the effects "may be declining somewhat in more recent years". Their conclusion: "a reduction in investors' data aggregation costs may not have served its intended purpose of leveling the informational playing field, at least during the initial years after mandatory adoption." (Reproduced from the abstract I fetched; I did not read the full paper — **effect sizes and standard errors are UNVERIFIED**.)

2. **ESEF tagging quality and analyst forecast accuracy in Finland** (Jonas Hyvönen, master's thesis, Department of Accounting, Hanken School of Economics, 2025/2026; retrieved from helda.helsinki.fi). Firm-year panel of Finnish issuers **2017–2024**, LSEG I/B/E/S annual EPS consensus, pre-post panel with firm fixed effects, plus a two-way fixed-effects model within the ESEF era. **Principal finding: "there is no statistically significant improvement in analyst forecast accuracy after ESEF adoption"**, and the association between the **number of custom extensions** and forecast errors is **positive but statistically non-significant**. The thesis also notes the literature is not unanimous: "focused studies find increased following and better forecast accuracy after XBRL, particularly with experience (Liu et al., 2014)", while tagging practices vary and customisation/weak anchoring "can impair comparability".

**Where evidence conflicts.** Blankespoor et al. (2014) and Hyvönen (2025/26) find no improvement in the intended market/analyst outcomes; the pre-XBRL/tagging-quality literature cited *within* Hyvönen (e.g. Liu et al. 2014) reportedly finds improvements, particularly as users gain experience. **Both sides are reported; do not read "XBRL improved analysis" as settled.** Note that the Finnish evidence is a **non-peer-reviewed master's thesis in a single market** and should be weighted accordingly.

**Limits of XBRL for your purposes — what I could and could not verify.**
- **VERIFIED:** the SEC mandate as described concerns **financial statements**; the *principal* documented effect is on market microstructure and analyst outcomes, not on the qualitative sections.
- **UNVERIFIED (could not retrieve):** I was unable to fetch SEC.gov directly — `https://www.sec.gov/structureddata` and `https://www.sec.gov/education/smallbusiness/xbrl` both returned **HTTP 403 "Request Rate Threshold Exceeded"** (SEC.gov blocks automated access). I therefore **cannot cite an official SEC page** stating that MD&A, Item 1A risk factors, or footnotes are outside the tagged data set. **The commonly made claim that qualitative MD&A/risk-factor text is NOT in XBRL is, in this review, UNVERIFIED against a primary SEC source.** It is strongly *suggested* by the fact that a separate research literature exists for extracting risk categories from Item 1A text (see §1.7) and by the existence of a whole shared task for parsing unstructured prospectus PDF text (FinSBD, §1.4) — but that is inference, not a fetched statement of scope. **Flag this for direct verification against SEC.gov / 17 CFR Part 232 (Regulation S-T) before you rely on it.**
- **Also UNVERIFIED:** the "XBRL's impact on analyst forecast behavior" study (Journal of Accounting and Public Policy) and "Comparability over time: XBRL tag changes and analyst forecast behavior" — both surfaced on ScienceDirect, which I could not retrieve.

### 1.7 Risk-factor taxonomies and section-level risk classification

**Campbell, Chen, Dhaliwal, Lu & Steele (2014), "The information content of mandatory risk factor disclosures in corporate filings."** Abstract retrieved via Ágora/Dialnet: https://agora.edu.es/servlet/articulo?codigo=4607641&info=resumen. (Journal/serials detail, *Review of Accounting Studies* 19(1):396–455, is taken from the reference list of the fetched GRAB paper.)

- **What.** Starting in **2005** the SEC mandated a "risk factor" section in Form 10-K discussing "the most significant factors that make the company speculative or risky".
- **Findings.** (i) **Firms facing greater risk disclose more risk factors**, and the *type* of risk faced determines whether a greater portion of disclosure is devoted to that risk type — i.e. managers' risk disclosures "meaningfully reflect the risks they face". (ii) The information in risk factor disclosures **is reflected in systematic risk, idiosyncratic risk, information asymmetry, and firm value**. Conclusion: evidence supports the SEC's decision to mandate them.
- **Caveats.** **Effect sizes, regression coefficients and R² are UNVERIFIED** (abstract only; the journal article is paywalled and I could not access it). Endogeneity is a live concern: risk disclosure and risk exposure are jointly determined.

**GRAB: A Risk Taxonomy–Grounded Benchmark for Unsupervised Topic Discovery in Financial Disclosures** — Ying Li & Tiejun Ma, arXiv:2509.21698, NeurIPS 2025 Workshop on Generative AI in Finance. Full text: https://ar5iv.labs.arxiv.org/html/2509.21698.

- **What / how annotated.** **1.61M sentences** from **Item 1A (Risk Factors)** of **8,247 annual 10-K filings** of S&P 500 firms, **2001–2025**. Labels are **weak / span-grounded — no manual annotation**: a blend of FinBERT CLS-attention, YAKE keyphrase importance, and taxonomy-aware collocation matching (λ=0.8 attention weight, top-10 tokens/sentence, unigram boost 1.5, collocation boost 1.2). Taxonomy: **193 curated terms mapped to 21 fine-grained risk types nested under 5 macro classes** (Hofeditz taxonomy). Evaluation is at the **5 macro classes**. Fixed **chronological split** (train ≤2022, dev 2023, test 2024–25) explicitly "to avoid look-ahead".
- **Reported effect sizes (test split).**

| Method | Accuracy | Macro-F1 | Topic BERTScore |
|---|---|---|---|
| CTM (BoW + SBERT) | **0.38** | **0.41** | 0.84 |
| LDA (BoW/TF-IDF) | 0.37 | 0.36 | 0.84 |
| SentenceLDA | 0.36 | 0.32 | 0.84 |
| GLDA (Word2Vec) | 0.35 | 0.23 | 0.84 |
| BERTopic | 0.35 | 0.22 | 0.82 |
| SenClu (SBERT) | 0.24 | 0.18 | 0.82 |

- **Documented failure modes.** (i) **Boilerplate induces spurious topics that dilute category signals**; (ii) **polysemous tokens** (e.g. "short", "term") shift meaning across market/credit/accounting contexts; (iii) **long-tail but material categories remain under-recovered** by frequency-driven approaches. Notably, **Topic BERTScore is uniformly 0.82–0.84** — topic *coherence* does not discriminate risk-category recovery, so do not use coherence-style metrics as a proxy for usefulness.
- **Caveat that matters most.** The labels are **weak, not human**, so the ~0.41 Macro-F1 is a *lower bound on a proxy task*, and the paper explicitly wanted to avoid the annotation cost. Also relevant to your ambitions: the paper notes manual coding does not scale — Mirakur hand-labelled 29 risk categories for **122 firms**, "far below 1% of annual 10-K filings".

### 1.8 Section-level vs whole-document analysis

Direct head-to-head evidence I could verify:

- **Section identity matters for returns.** Lazy Prices (below, §3) finds that **"changes in language referring to the executive (CEO and CFO) team, regarding litigation, or in the risk factor section of the documents are especially informative for future returns"** — i.e. signal is concentrated in specific sections, not spread evenly across the document.
- **Section matters for fundamentals.** Li (2010, §3) analyses **MD&A forward-looking statements specifically**, not the whole 10-K.
- **Whole-document/metrics are insufficient for numeric reasoning.** FinQA's ablation (§2.4) reports **table-only inference 45.81%** vs **text-only 15.80%** execution accuracy (FinQANet, RoBERTa-large) — with the combination at 61.22% — evidence that *both* structured and narrative content carry non-redundant signal, and that text alone is far weaker than tables alone for numerical questions.

**UNVERIFIED / gaps.** I could not retrieve Brown & Tucker (2011) "Large-sample evidence on firms' year-over-year MD&A modifications" (JAR) — Wiley returned HTTP 403, no open copy found. I could not retrieve Feldman, Govindaraj, Livnat & Segal (2010) "Management's tone change, post-earnings announcement drift and accruals" (only a Mendeley record and a ScienceDirect-blocked AAA page). Huang, Teoh & Zhang (2014) "Tone Management" also could not be retrieved (AAAHQ page gated; no open copy). **No claim in this review rests on those three papers.**

---

## 2. LLM / NLP EXTRACTION OF QUALITATIVE SIGNALS — PUBLISHED VALIDATION

### 2.1 FinBERT — two different papers; only one verified

**IMPORTANT: there are at least two distinct "FinBERT" papers, and they are routinely conflated.**
- **Araci (2019)**, arXiv:1908.10063 — a BERT model further pre-trained on financial text. **I verified this one** (full text retrieved).
- **Huang, Wang & Yang (2023)**, "FinBERT: A Large Language Model for Extracting Information from Financial Text", *Contemporary Accounting Research* 40(2):806–841. **I could NOT retrieve this paper.** Wiley returned HTTP 403 on both the `/doi/` and `/doi/full-xml/` URLs; the HKUST institutional repository record entered a redirect loop; SSRN returned HTTP 403 "Content Blocked". **I therefore cannot report its benchmark scores, datasets, or error modes. Treat any specific number attributed to "FinBERT (Huang, Wang & Yang 2023)" as UNVERIFIED unless you obtain the paper.** The citation (CAR 40(2):806–841) is corroborated by the reference list of the fetched GRAB paper, but the *content* is not.

**Araci (2019), "FinBERT: Financial Sentiment Analysis with Pre-trained Language Models" — verified results.**

- **On Financial PhraseBank** (10-fold CV): FinBERT **accuracy 0.86, F1 0.84** on all sentences; **0.97 / 0.95** on the 100%-agreement subset.
- Comparison table from the same paper: LPS (Malo et al.'s model) **0.71 acc / 0.71 F1** (all data) and **0.79 / 0.80** (100% agreement); HSC **0.71 / 0.76** and **0.83 / 0.86**; FinSSLX **0.91 / 0.88** (100% agreement only). The paper notes it recomputed LPS/HSC overall accuracy from their per-class recalls because those papers did not report it.
- **On FiQA sentiment Task 1**: FinBERT **MSE 0.07, R² 0.55**, versus Yang et al. **MSE 0.08, R² 0.40** and Piao & Breslin **MSE 0.09, R² 0.41**. **Methodological caveat the authors state themselves:** the competing numbers are on the **official test set**, whereas FinBERT's are **10-fold cross-validation because the authors lacked test-set access** — so this is not a like-for-like comparison.
- **Negative result that matters:** further in-domain pre-training was **not** significantly better than vanilla BERT (vanilla 0.85/0.84 vs FinBERT-domain 0.86/0.84 vs FinBERT-task 0.86/0.85). The authors' likely explanation is a **ceiling effect** — on the all-agree subset vanilla BERT already scores **0.96 accuracy**. Their own conclusion: "More experiments with another financial labelled dataset is necessary to conclude that the effect of further pre-training on domain corpus is not significant."

### 2.2 ChatGPT vs FinBERT on financial sentiment — Fatouros, Soldatos, Kouroumali, Makridis & Kyriazis (2023)

**Source.** "Transforming Sentiment Analysis in the Financial Domain with ChatGPT", *Machine Learning with Applications*; arXiv:2308.07935. Retrieved: https://ar5iv.labs.arxiv.org/html/2308.07935.

**Sample.** **2,291 unique forex news headlines** scraped from ForexLive and FXstreet over **86 days, January–May 2023**, covering AUDUSD, EURCHF, EURUSD, GBPUSD, USDJPY. **Manually annotated** positive/negative/neutral by the **potential short-term impact on the linked forex pair**. Mean headline length 11.69 tokens (SD 2.82); mean article length 262.58 (SD 158.99). **No IAA statistic is reported** — a material weakness.

**Reported effect sizes (author-reported).**

| Model | Accuracy | Precision | Recall | F1 | S-MAE |
|---|---|---|---|---|---|
| FinBERT (baseline) | 0.561 | 0.560 | 0.562 | 0.556 | 0.540 |
| GPT-3.5, prompt P1 | 0.730 | 0.760 | 0.730 | 0.725 | 0.300 |
| GPT-3.5, prompt P2 | **0.790** | 0.797 | **0.790** | **0.790** | 0.227 |
| GPT-3.5, prompt P3 | 0.735 | 0.780 | 0.735 | 0.737 | 0.282 |
| GPT-3.5, prompt P4 | 0.784 | **0.804** | 0.784 | 0.789 | **0.221** |

Headline claim: ChatGPT showed **~35% better sentiment classification** and **~36% higher correlation with market returns** than FinBERT.

**Documented error modes / fragilities.**
- **Prompt sensitivity is large and measured.** Accuracy swings from **0.730 (P1)** to **0.790 (P2)** purely from prompt framing — a ~6pp gap; framing as "sentiment analysis model" (P3, 0.735) was worse than framing as a domain expert who sees the ticker.
- **Entity-mention dependence.** **75.6%** of headlines name the relevant forex pair at the start; on the subset that does **not**, GPT-P2 falls to **0.711 accuracy / 0.714 F1**, and FinBERT falls to 0.543.
- **Domain-specific inversion.** The paper's motivating examples show that sentiment must be resolved *relative to the instrument* (positive for a currency can be negative for its pair). FinBERT "primarily consider[s] the perspective of the experts that annotated the training data", limiting this flexibility.
- **Cost/latency acknowledged as first-class constraints** — the authors track token counts and API latency explicitly.

**Caveats.** One 86-day window, one asset class, one author-annotated dataset, no IAA, no peer-reviewed replication identified. The "35%/36%" headline should be treated as a single-sample result, not an established effect size.

### 2.3 LLM return prediction from news — Lopez-Lira & Tang

**Source.** "Can ChatGPT Forecast Stock Price Movements? Return Predictability and Large Language Models", arXiv:2304.07619 (v6, 28 October 2025), also SSRN 4412788. Retrieved: https://arxiv.org/abs/2304.07619.

**Verified claims (from the v6 abstract).** Using **post-knowledge-cutoff headlines**, GPT-4 captures initial market responses, achieving **approximately 90% portfolio-day hit rates for the non-tradable initial reaction**. GPT-4 scores also significantly predict **subsequent drift, especially for small stocks and negative news**. Forecasting ability **generally increases with model size**. **Strategy returns decline as LLM adoption rises**, consistent with improved price efficiency.

**Caveats.**
- The ~90% hit rate is for the **initial reaction**, and the authors explicitly label it **non-tradable**. Do not quote 90% as a trading result.
- v6 is a substantially revised version (six revisions) and the abstract now emphasises declining returns; **earlier versions' magnitudes should not be mixed with this one**. **Precise return spreads, t-statistics and sample sizes are UNVERIFIED** (abstract only; I did not read the full paper).
- The design choice of restricting to post-cutoff headlines is itself an admission of the contamination problem addressed next.

### 2.4 Look-ahead bias and training-data contamination — Glasserman & Lin (2023)

**This is the most directly actionable paper in this review for backtesting.**

**Source.** Paul Glasserman (Columbia Business School) & Caden Lin (Columbia, Mathematics), "Assessing Look-Ahead Bias in Stock Return Predictions Generated By GPT Sentiment Analysis", arXiv:2309.17322, September 2023. Full text: https://ar5iv.labs.arxiv.org/html/2309.17322.

**Data.** CRSP daily open/close/shares/market cap. Two headline sets: **scraped** — **129,431 headlines, 6,723 companies** (median market cap **$2.59bn**); **Thomson Reuters** — **181,908 headlines, 678 S&P 500 companies** (median market cap **$56.74bn**). **In-sample Jan 2015 – Sep 2021** (GPT-3.5-Turbo's training window per OpenAI); **out-of-sample Oct 2021 – Dec 2022**. Temperature set to **0** to maximise reproducibility.

**Method (the practical de-biasing tool).** Anonymise the company by fuzzy-matching the cleaned official name (InDel similarity > 80) and replacing it with the string `"Blahblahblah"`, plus replacing up to **20 products/services** per company from the Google Knowledge Graph (Apple, Microsoft, Amazon examples given). The algorithm modified **100,401 / 129,431** scraped headlines and **180,237 / 181,908** TR headlines. spaCy NER was tried and rejected as too inaccurate.

**Reported effect sizes (long–short, equal-weighted, one-day holding, no costs).**

| | Scraped original | Scraped replaced | TR original | TR replaced |
|---|---|---|---|---|
| In-sample mean (bps/day) | 25.08 | **30.97** | 10.74 | **13.84** |
| p-value of difference | | **0.066** | | **0.017** |
| Out-of-sample mean (bps) | 16.32 | 11.09 | 6.07 | 12.23 |
| p-value of difference | | 0.23 | | **0.064** |

**The central finding is counter-intuitive and important: anonymising the company made the strategy *better* in-sample.** Since look-ahead bias can only be positive, the authors conclude the **"distraction effect"** — the LLM's general knowledge about the company — does **more harm than good**, and outweighs look-ahead bias. The effect is **strongest for larger companies**, about which GPT has more general knowledge.

**Overconfidence / error magnitude.** In-sample (scraped), the original response was wrong **17.6%** of the time vs **38.95%** for replaced — yet when the original was wrong and the replaced was neutral, the original strategy lost **242 bps** on average, versus only **97 bps** in the reverse case. Out-of-sample the corresponding losses were **289 bps vs 130 bps**. The authors: "GPT-3.5 would do better by better recognizing what it does not know."

**Verbatim illustrative failures (Table 4).** Headline "Facebook not planning to extend European privacy law globally": original response **YES** (good) with a reasoned justification, replaced response **NO** — the stock fell 0.6% next period, so the *anonymised* answer was right. Headline "Pfizer to buy Allergan in 160 billion deal": original **NO** for Allergan, replaced **YES**; the stock rose 6% short term, so the anonymised answer was right again. In both cases the only change was the presence of the company name.

**Caveats the authors state.** The strategies are "not intended to be feasible"; in-sample versions clearly are not, and even out-of-sample versions ignore **transaction costs and short-sale constraints**. Out-of-sample differences are **not significant** except borderline for large caps. This is a working paper (arXiv), 2023, GPT-3.5-era.

**Practical implication for your system: any LLM-derived feature backtested on data inside the model's training window is contaminated in a direction that is not even reliably favourable.** Either restrict to post-cutoff text, or property-test with entity anonymisation.

### 2.5 LLM/NLP information extraction from filings — FinQA

**Source.** Zhiyu Chen, Wenhu Chen, Charese Smiley, Sameena Shah, Iana Borova, Dylan Langdon, Reema Moussa, Matt Beane, Ting-Hao Huang, Bryan Routledge, William Yang Wang, "FinQA: A Dataset of Numerical Reasoning over Financial Data", EMNLP 2021. arXiv:2109.00122. Full text retrieved from the PDF.

**Sample and annotation (verified).** **8,281 question–answer pairs** over **earnings reports of S&P 500 companies, 1999–2019**, built on FinTabNet. Authored by **11 US-based finance experts** (CPAs, MBAs) hired on Upwork, screened by interview and trained; payment **~$2.00/question**, average **$35/hour**, data collection **~8 weeks**. Each example includes a **gold reasoning program** in a DSL of **6 mathematical operations** (add, subtract, multiply, divide, greater, exp) and **4 table operations** (table-max/min/sum/average) — i.e. **full explainability of the intended reasoning path**.

**Reported effect sizes.**

| System | Execution accuracy | Program accuracy |
|---|---|---|
| Best model (abstract) | **65.05%** | — |
| FinQANet (RoBERTa-large), validation | 61.22 | 58.05 |
| FinQANet (BERT-large) | 53.86 | 50.95 |
| FinQANet (FinBERT encoder) | 46.64 | 44.11 |
| Pre-trained Longformer, end-to-end (no retriever) | 23.83 | 22.56 |
| Retriever + direct generation | 0.87 | — |
| TF-IDF + single op | 1.65 | 1.65 |
| **Expert humans** | **91.16%** | — |
| **Non-expert crowd** | **50.68%** | — |

**Ablations and documented error modes (the useful part).**
- **Modality:** table-only inference **45.81%** exec / 43.62% prog; **text-only 15.80% / 15.33%**; full 61.24% / 58.86%. **The narrative text alone is a weak carrier of the numerical signal; the two are complementary.**
- **Question type:** table-only questions 67.38%, text-only questions 54.86%, **table+text questions 43.80%** — cross-modal questions are hardest.
- **Reasoning depth collapses:** 1-step programs 67.61%; 2-step 59.08%; **>2 steps 22.78%**.
- **Constants:** programs requiring constants (e.g. converting "1.5 billion" to "1,500 million") drop to **43.88%**.
- Named error cases include unit conversion between billion and million, and multi-step financial definitions ("credit lines that have been drawn").

**Caveats.** Baselines are **pre-LLM** (BERT/RoBERTa/Longformer), so this is **not** a GPT-era evaluation. Questions are human-written by finance experts, which may be harder than naturally occurring analyst questions. **No test of return or forecast predictive validity.** For a summary of a 2026 LLM-based risk-extraction benchmark I surfaced but did not fetch (`arXiv:2601.15247`, "Taxonomy-Aligned Risk Extraction from 10-K Filings with Autonomous Improvement Using LLMs") — **UNVERIFIED; not read.**

### 2.6 Summary of documented error modes across sources

| Error mode | Evidence source | Concrete measurement |
|---|---|---|
| Look-ahead bias / training-data contamination | Glasserman & Lin 2023 | In-sample vs post-cutoff comparison; anonymisation changes results by 5.89 bps/day (p=0.066) and 4.37 (p=0.017) |
| "Distraction" from entity knowledge | Glasserman & Lin 2023 | Effect stronger for larger caps; better *without* the company name in-sample |
| Overconfidence | Glasserman & Lin 2023 | Wrong less often but loses 242 bps vs 97 bps when wrong |
| Prompt sensitivity | Fatouros et al. 2023 | Accuracy 0.730 → 0.790 across prompt framings |
| Multi-step numerical reasoning failure | FinQA 2021 | 67.61% (1 step) → 22.78% (>2 steps) |
| Unit/scale conversion failure | FinQA 2021 | 43.88% on programs with constants |
| Text-only insufficiency | FinQA 2021 | 15.80% exec accuracy from text alone |
| Generic-dictionary failure | Li 2010 | Diction, General Inquirer, LIWC tone do **not** positively predict future performance |
| Dictionary failure on positive tone | Malo et al. 2014 | W-Loughran F1 **0.204** on positive sentences |
| Negation / polarity-shifter and context resolution | Malo et al. 2014 | 43.0% of errors were "need for more context"; 8.7% polysemy; 4.3% changes in numbers |
| Boilerplate, polysemy, long-tail categories | GRAB 2025 | Macro-F1 ≤0.41; coherence metrics non-discriminative (0.82–0.84) |
| Domain-specific category confusion | FinNum NTCIR-14 | 50% on selling price / stop loss; 62% maturity date |
| Structure extraction from PDFs | FinSBD-2020 | Best mean F1 **0.445** |

**Note on inconsistency across runs**: I did **not** find a fetched source that directly measures run-to-run output variance on financial text. Glasserman & Lin set temperature 0 "to maximize reproducibility", which implies the concern but is not a measurement. **UNVERIFIED — no direct study of LLM run-to-run inconsistency on filings was verified in this review.**

---

## 3. THE "NARRATIVE VS NUMBERS" QUESTION

### 3.1 Li (2010) — forward-looking statements in MD&A

**Source.** Feng Li, "The Information Content of Forward-Looking Statements in Corporate Filings—A Naïve Bayesian Machine Learning Approach", *Journal of Accounting Research* 48(5):1049–1102, December 2010. DOI 10.1111/j.1475-679X.2010.00382.x. **Abstract retrieved from IDEAS/RePEc: https://ideas.repec.org/a/bla/joares/v48y2010i5p1049-1102.html**. The publisher page (Wiley) returned HTTP 403 and **the full text could not be retrieved.**

**What the signal is.** Tone of **forward-looking statements (FLS)** in the **MD&A** of 10-K and 10-Q filings, scored with a **Naïve Bayesian machine learning algorithm** trained on manually labelled FLS sentences (rather than a dictionary).

**Verified findings (abstract level).**
1. **Determinants:** firms with better current performance, lower accruals, smaller size, lower market-to-book, less return volatility, lower MD&A Fog index, and longer history tend to have **more positive FLSs**.
2. **Incremental content:** "The **average tone of the FLS is positively associated with future earnings even after controlling for other determinants of future performance**." ← This is the core incremental-information result.
3. **Interacts with accruals:** "the tone in MD&As seems to **mitigate the mispricing of accruals**. When managers 'warn' about the future performance implications of accruals (i.e., the MD&A tone is positive (negative) when accruals are negative (positive)), **accruals are not associated with future returns.**"
4. **Regulation had no effect:** despite increased regulation aimed at strengthening MD&A, "there is **no systematic change in the information content of MD&As over time**".
5. **Dictionaries fail:** tone measures built on **Diction, General Inquirer, and LIWC** "**do not positively predict future performance**", suggesting "these dictionaries might not work well for analyzing corporate filings."

**Reported effect size.** **UNVERIFIED.** The paper is behind a Wiley paywall and I retrieved only the abstract. **The specific incremental R² / coefficient magnitudes are NOT verified here.** This is an important gap: the abstract establishes *direction and incremental significance*, not magnitude. Obtain the JAR article before quoting an R².

**Caveats.** Naïve Bayes on 1990s–2000s US filings; the tone measure is model-specific and not distributed as a standard; "association with future earnings" is not the same as tradable alpha; the accruals-mitigation result is a conditioning/interaction claim that is easy to over-read.

### 3.2 Lazy Prices — text *change* as the strongest verified alpha evidence

**Source.** Lauren Cohen, Christopher Malloy & Quoc Nguyen, "Lazy Prices", **NBER Working Paper 25084** (September 2018, revised March 2019), DOI 10.3386/w25084. Retrieved: https://www.nber.org/papers/w25084. Published version: *Journal of Finance* 75(3):1371–1415, 2020 (stated on the same page).

**What the signal is.** **Year-over-year change in the language and construction of 10-Ks and 10-Qs** — textual similarity between consecutive filings, not a sentiment score. Sample: **the complete history of regular quarterly and annual filings by U.S. corporations, 1995–2014.**

**Reported effect sizes.**
- A portfolio that **shorts "changers" and buys "non-changers" earns up to 188 basis points in monthly alphas (over 22% per year)**.
- **"Changes in language referring to the executive (CEO and CFO) team, regarding litigation, or in the risk factor section of the documents are especially informative for future returns."**
- Changes to 10-Ks predict **future earnings, profitability, future news announcements, and even future firm-level bankruptcies**; firms that do *not* change earn positive abnormal returns.
- **No announcement effect**: "returns only accruing when the information is later revealed through news, events, or earnings — suggesting that **investors are inattentive** to these simple changes across the universe of public firms."

**Why this is the best available "text beats numbers" evidence.** The alphas are computed as *abnormal* returns (i.e. after standard factor adjustment), which is precisely the incremental-over-accounting-test you asked for, and the signal is a cheap, deterministic, reproducible computation — no LLM, no contamination risk, no annotation cost.

**Caveats — read these carefully.**
- **188 bps/month is a long-short decile-portfolio alpha on U.S. micro/small caps over 1995–2014**, before realistic transaction costs, borrow costs, and capacity limits. Turnover is annual-ish, which helps, but the trade is concentrated in small, illiquid, distressed names.
- **The signal is partly distress/boilerplate-removal**, not "narrative insight": firms in trouble rewrite their filings.
- **Inattention interpretation is contestable**; the absence of an announcement effect is consistent with limited attention but also with the signal being about slow-moving fundamentals.
- I read the **NBER abstract**, not the full paper: **factor model specification, decile breakpoints, cost assumptions and the exact weighting are UNVERIFIED.**

### 3.3 Ke, Kelly & Xiu (2019) — supervised sentiment designed for return prediction

**Source.** Zheng Tracy Ke, Bryan T. Kelly & Dacheng Xiu, "Predicting Returns With Text Data", **NBER Working Paper 26186** (August 2019, revised November 2019), DOI 10.3386/w26186. Retrieved: https://www.nber.org/papers/w26186.

**What the signal is.** A sentiment score **constructed to be optimal for return prediction**, rather than borrowed from a lexicon or a generic classifier. Three steps: (1) isolate sentiment terms by **predictive screening**; (2) assign sentiment **weights via topic modelling**; (3) aggregate to an article-level score via **penalized likelihood**. Theoretical guarantees on estimate accuracy are derived under minimal assumptions.

**Sample.** **Dow Jones Newswires** — described as one of the most actively monitored news streams in the financial system.

**Reported effect size.** **UNVERIFIED — the abstract reports that the supervised model "excels at extracting return-predictive signals" but gives no Sharpe ratio, alpha, R² or IC.** This is a genuine gap; the full paper would be needed. The paper's *conceptual* contribution is nonetheless the relevant one for your design: **a sentiment score optimised for return prediction is not the same object as a sentiment score optimised for classification accuracy**, and the two should not be expected to rank models the same way.

### 3.4 Direct horse-races and the relative-weighting question

**What I can support.**
- **Text adds information beyond accounting variables**, in direction and significance, in Li (2010) ("positively associated with future earnings **even after controlling for other determinants of future performance**") and in Lazy Prices (abnormal-return alphas on a text-change signal).
- **Text and numbers are complementary, not substitutes, and numbers dominate for numerical questions**: FinQA text-only 15.80% vs table-only 45.81% vs combined 61.22% execution accuracy.
- **Generic sentiment dictionaries are a poor baseline**: Li (2010) finds Diction/General Inquirer/LIWC tone do not positively predict future performance; Malo et al. (2014) report F1 0.204 for a Loughran word-count model on positive sentences.
- **A specific 10-K section can dominate the document** for return predictiveness (CEO/CFO language, litigation, risk factors — Lazy Prices).

**What I could NOT verify — and you should treat as an open question.**
- **No study found, retrieved, or verified that quantifies the optimal weight to place on text versus accounting data in a decision rule.** There is no "text should get X% of the weight" result in the sources I read. **Mark this UNVERIFIED.** Do not let anyone supply a number for it without a primary source.
- **No verified incremental R² or information coefficient from text beyond value/profitability/accruals factors.** Li (2010)'s magnitude is paywalled; Ke-Kelly-Xiu's is not in the abstract; Lazy Prices reports portfolio alphas, not incremental R². **This is the single biggest evidence gap in this review**, and it is exactly the number your system needs.
- **Loughran & McDonald (2011)**, "When Is a Liability Not a Liability? Textual Analysis, Dictionaries, and 10-Ks", *Journal of Finance* 66(1):35–65: I verified the **existence, citation and scope of the word lists** from the authors' official repository (University of Notre Dame SRAF, https://sraf.nd.edu/loughranmcdonald-master-dictionary/ — retrieved; it lists the seven categories **negative, positive, uncertainty, litigious, strong modal, weak modal, constraining**, plus a complexity list, and the 2011 JF citation). **I could not retrieve the 2011 paper itself** (Wiley 403; SSRN 403 "Content Blocked"), so **its reported effect sizes and its famous statistics about Harvard-IV misclassification are UNVERIFIED here.** What *is* independently verified, from Li (2010)'s abstract and Malo et al.'s results, is that generic dictionaries underperform domain-specific measures on filing text.

---

## 4. WHAT THIS MEANS FOR THE SYSTEM (evidence-grounded only)

1. **Do not use generic sentiment dictionaries as the qualitative engine.** Two independent verified results (Li 2010; Malo et al. 2014) show they fail on financial/10-K text, and Malo's positive-class F1 of 0.204 is a hard floor.
2. **Section segmentation is not optional.** FinSBD-2020 shows state-of-the-art structure recovery from financial PDFs at **mean F1 0.445**; the signal-bearing text must be located before it can be scored, and Lazy Prices shows the informative content is concentrated in specific sections.
3. **The strongest verified, uncontaminated text signal is textual *change* year-over-year in 10-K/10-Q, not tone** (Lazy Prices: up to 188 bps/month, 1995–2014). It is deterministic, cheap, requires no annotation, and has no LLM contamination exposure.
4. **Treat every LLM-derived feature backtest inside the model's training window as contaminated.** Glasserman & Lin show the bias is real but *not even reliably positive* — entity knowledge actively hurt in-sample. Anonymise entity names as a property test, or restrict to post-cutoff text.
5. **LLMs are strong at sentence-level polarity and weak at numbers.** FinQA: text-only execution accuracy 15.80%, >2-step programs 22.78%, unit conversions 43.88%. Do not route numerical reasoning through a language model.
6. **Prompt framing and entity resolution change results by ~6pp** (Fatouros), so any LLM feature needs prompt-robustness testing and stored prompts.
7. **Documented IAA is thin across the field.** FinCausal, FinSBD, FinNum (full-agreement-only), and the Forex annotation all fail to report kappa/alpha. Only FinancialPhraseBank reports reliability statistics (ICC 0.649–0.818 on 150 sentences). Assume label noise unless a source shows otherwise.
8. **XBRL evidence for "structured data improved analysis" is not established.** The one retrieved market study finds *worse* liquidity and *higher* spreads post-mandate; a Finnish thesis finds no significant analyst-accuracy improvement. Report both sides.

---

## FETCH LOG

Method key: **[fetch]** = retrieved with the `web_fetch` tool. **[pdf]** = retrieved by HTTPS download and local stdlib PDF text extraction (disclosed because `web_fetch` rejects `application/pdf`). Every document below was actually retrieved and read; search-engine snippets were used only to *locate* candidates.

**Successfully retrieved and read**

1. https://ar5iv.labs.arxiv.org/html/1307.5336 — **[fetch]** Full text of Malo et al., *Good Debt or Bad Debt*: confirmed the OMX Helsinki/LexisNexis construction, 10,000 articles → 53,400 sentences, 16 annotators, 5–8 annotations per sentence, and the investor-viewpoint annotation instruction.
2. https://arxiv.org/pdf/1307.5336 — **[pdf]** Same paper; confirmed the exact IAA range (ICC/reliability **0.649–0.818** on 150 sentences), 75.2% pairwise agreement on positive-vs-neutral, the four agreement tiers with counts (2,259 / 3,448 / 4,211 / 4,840), the LPS per-class results (positive F1 0.739 / neutral 0.861 / negative 0.813 at 100% agreement; positive 0.585 at ≥50%), and the full error-type table (43.0% need for more context, 26.7% significance of events, 4.3% changes in numbers).
3. https://huggingface.co/datasets/takala/financial_phrasebank — **[fetch]** Confirmed the released corpus is 4,840 sentences, "divided by agreement rate of 5-8 annotators", and the CC BY-NC-SA 3.0 licence; the dataset viewer is broken so no data split was read here.
4. https://huggingface.co/datasets/takala/financial_phrasebank/raw/main/financial_phrasebank.py — **[fetch]** Confirmed the exact four builder configs (`sentences_allagree`, `_75agree`, `_66agree`, `_50agree`), the 5–8 overlapping annotations per sentence, and the JASIST 2014 citation with volume 65.
5. https://aclanthology.org/2020.fnp-1.3/ — **[fetch]** Landing page for FinCausal 2020: confirmed authors, FNP@COLING 2020 venue, pages 23–32, 16 teams / 13 system papers, and the two-subtask structure.
6. https://aclanthology.org/2020.fnp-1.3.pdf — **[pdf]** FinCausal 2020 full text: confirmed the Qwam 2019 news corpus from 14,000 sites, CC0 licence, Task 1 counts (8,580/13,478/7,386 = 29,444; 2,136 causal = 7.24%), Task 2 counts (641/1,109/638), the BRAT-based iterative annotation with two revisers, the absence of any agreement statistic, and the full results tables (Task 1 best 97.75 LIORI vs baseline 95.23; Task 2 best 94.72).
7. https://aclanthology.org/2020.finnlp-1.8/ — **[fetch]** Landing page for FinSBD-2020: confirmed authors, FinNLP@IJCAI-PRICAI 2020 venue, pages 47–54.
8. https://aclanthology.org/2020.finnlp-1.8.pdf — **[pdf]** FinSBD-2020 full text: confirmed 41 documents, two independent analysts plus a third reviewer, the five documented ambiguity classes, 5 teams from 4 countries, and the ranking table (best mean F1 **0.445**; French subtask 1 best 0.471).
9. https://econpapers.repec.org/article/sprreaccs/v_3a19_3ay_3a2014_3ai_3a4_3ad_3a10.1007_5fs11142-013-9273-4.htm — **[fetch]** Blankespoor, Miller & White (2014) XBRL study: confirmed the 2009 SEC XBRL mandate, the difference-in-differences design, higher abnormal bid-ask spreads and lower liquidity/volume post-mandate, and the authors' own "may not have served its intended purpose" conclusion.
10. https://ar5iv.labs.arxiv.org/html/2309.17322 — **[fetch]** Glasserman & Lin look-ahead-bias paper: confirmed the in/out-of-sample windows, both headline datasets and their sizes and median market caps, the "Blahblahblah"/Knowledge-Graph anonymisation algorithm and its hit counts, the mean-return table with p-values (30.97 vs 25.08 bps, p=0.066; 13.84 vs 10.74, p=0.017), the 242 vs 97 bps overconfidence asymmetry, and the two verbatim failure examples.
11. https://www.nber.org/papers/w25084 — **[fetch]** Lazy Prices: confirmed the 1995–2014 complete filing history, the up-to-188 bps monthly alpha (>22%/yr), that CEO/CFO, litigation and risk-factor language changes are "especially informative", the predictability of earnings/profitability/news/bankruptcies, the absence of an announcement effect, and the *Journal of Finance* 75(3):1371–1415 (2020) published version.
12. https://www.nber.org/papers/w26186 — **[fetch]** Ke, Kelly & Xiu, *Predicting Returns With Text Data*: confirmed the three-step supervised sentiment construction, the theoretical guarantees, and that the empirical work uses Dow Jones Newswires; the abstract reports predictive success **without numbers**.
13. https://ideas.repec.org/a/bla/joares/v48y2010i5p1049-1102.html — **[fetch]** Li (2010) abstract: confirmed author, JAR 48(5):1049–1102, the Naïve Bayesian FLS approach, all five findings including the accruals-mispricing mitigation and the explicit negative result for Diction/General Inquirer/LIWC.
14. https://sraf.nd.edu/loughranmcdonald-master-dictionary/ — **[fetch]** Official University of Notre Dame repository: confirmed the seven sentiment categories (negative, positive, uncertainty, litigious, strong modal, weak modal, constraining), the 2of12inf baseline and 10-K/earnings-call extension, the master-dictionary coverage 1993–2025, the commercial-licence requirement, and the 2011 *Journal of Finance* 66(1):35–65 citation.
15. https://ar5iv.labs.arxiv.org/html/2308.07935 — **[fetch]** Fatouros et al. ChatGPT sentiment paper: confirmed the 2,291 forex headlines / 86-day window / manual annotation, the full FinBERT-vs-GPT results table (FinBERT 0.561 acc; GPT-P2 0.790, GPT-P4 0.784, GPT-P1 0.730, GPT-P3 0.735), the ~35%/36% headline claims, the prompt table, the 75.6% entity-mention statistic and the 0.711 degraded subset accuracy.
16. https://arxiv.org/abs/2304.07619 — **[fetch]** Lopez-Lira & Tang abstract (v6): confirmed the ~90% **non-tradable** portfolio-day hit rate, drift predictability for small stocks and negative news, model-size scaling, and declining returns with LLM adoption.
17. https://arxiv.org/pdf/1908.10063 — **[pdf]** Araci (2019) FinBERT full text: confirmed FPB results (0.86/0.84 all data; 0.97/0.95 at 100% agreement), the LPS/HSC/FinSSLX comparison numbers, FiQA Task 1 (1,174 examples, continuous targets, entity labels; FinBERT MSE 0.07 / R² 0.55 vs 0.08/0.40 and 0.09/0.41) including the authors' own 10-fold-CV-vs-test-set caveat, the non-significance of further pre-training, and the 0.96 vanilla-BERT ceiling on the all-agree subset.
18. https://arxiv.org/pdf/2109.00122 — **[pdf]** FinQA full text: confirmed 8,281 expert-written QA pairs over S&P 500 reports 1999–2019, the 11 Upwork experts and pay/timing, the DSL operations, the whole results table (best 65.05%; FinQANet RoBERTa-large 61.22/58.05), the expert-human 91.16% and crowd 50.68% baselines, and the ablations (table-only 45.81, text-only 15.80, >2-step 22.78, constants 43.88) plus the named error cases.
19. https://research.nii.ac.jp/ntcir/workshop/OnlineProceedings14/pdf/ntcir/01-NTCIR14-OV-FINNUM-ChenC.pdf — **[pdf]** FinNum NTCIR-14 overview: confirmed the 7-category/8-Monetary-subcategory taxonomy, FinNum 2.0 (4,072/457/753 tweets; 8,868 numerals; **full-agreement-only**), best micro-F1 93.94 and 87.17, the per-subcategory accuracy breakdown (selling price 50%, stop loss 50%, support/resistance 70%, exercise price 71%, maturity date 62%), and the word-based CNN baseline of 55.90.
20. https://ar5iv.labs.arxiv.org/html/2509.21698 — **[fetch]** GRAB benchmark: confirmed 1.61M Item 1A sentences from 8,247 10-Ks (2001–2025), the 193-term → 21-subcategory → 5-macro-class Hofeditz taxonomy, the weakly-supervised (non-human) labelling recipe, the chronological split rationale, the full baseline results table (CTM best Acc 0.38 / Macro-F1 0.41; LDA 0.37/0.36; SenClu 0.24/0.18; BERTopic 0.35/0.22), the near-invariant Topic BERTScore (0.82–0.84), and the three named failure modes.
21. https://agora.edu.es/servlet/articulo?codigo=4607641&info=resumen — **[fetch]** Campbell, Chen, Dhaliwal, Lu & Steele (2014) risk-factor-disclosure abstract: confirmed the 2005 SEC risk-factor mandate, that firms facing greater risk disclose more risk factors and the risk type shapes the disclosure, and that the information is reflected in systematic risk, idiosyncratic risk, information asymmetry and firm value.
22. https://helda.helsinki.fi/server/api/core/bitstreams/957e3226-8587-458c-b662-add43ce4fb86/content — **[pdf]** Hyvönen, *ESEF Tagging Quality and Analyst Forecast Accuracy in Finland* (Hanken master's thesis): confirmed the 2017–2024 Finnish firm-year panel, the LSEG I/B/E/S EPS-consensus design, the **no statistically significant improvement in analyst forecast accuracy after ESEF adoption**, the positive-but-non-significant custom-extension association, and the thesis's own report of contrary pre-existing findings (Liu et al. 2014).

**Attempted and FAILED (recorded so the reader knows what remains unverified)**

23. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1475-679X.2010.00382.x — **[fetch]** HTTP 403 bot gate. Li (2010) full text **not** obtained; incremental R² remains unverified.
24. https://onlinelibrary.wiley.com/doi/10.1111/1911-3846.12832 — **[fetch]** HTTP 403. **Huang, Wang & Yang (2023) FinBERT content NOT verified.**
25. https://wol-prod-cdn.literatumonline.com/doi/10.1111/j.1540-6261.2010.01625.x — **[pdf]** HTTP 403. **Loughran & McDonald (2011) full text not obtained.**
26. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1331573 — **[fetch]** HTTP 403 "Content Blocked". LM 2011 abstract not obtained either.
27. https://www.sec.gov/structureddata and https://www.sec.gov/education/smallbusiness/xbrl — **[fetch]** HTTP 403 "Request Rate Threshold Exceeded" (SEC.gov automated-access block). **No official SEC statement on XBRL scope was retrieved**; the claim that MD&A/risk factors are outside XBRL is therefore unverified against a primary SEC source.
28. https://repository.hkust.edu.hk/ir/Record/1783.1-124956 — **[fetch]** redirect loop; no content.
29. https://dl.acm.org/doi/fullHtml/10.1145/3184558.3192301 — **[fetch]** HTTP 403 bot gate. FiQA primary source **not** obtained.
30. https://andrefreitas.org/papers/www_fiqa_2018.pdf — **[pdf attempt]** HTTP 404. FiQA primary source still not obtained.
31. https://www.federalregister.gov/documents/2009/02/10/E9-742/interactive-data-to-improve-financial-reporting — **[fetch]** cross-origin redirect to an interstitial; the SEC's XBRL final rule text was not retrieved.
32. https://damore-mckim.northeastern.edu/wp-content/uploads/2022/05/5_NarrativeAssetPricing.pdf — **[pdf attempt]** HTTP 404. Bybee, Kelly & Su *Narrative Asset Pricing* **not** retrieved.
33. https://www.conftool.com/efa2024/.../EFA2024_1446_NBS_Expected_Returns_and_Large_Language_Models.pdf — **[pdf attempt]** HTTP 404. Chen, Kelly & Xiu *Expected Returns and Large Language Models* **not** retrieved; treat the SSRN 4416687 citation as unverified in this review.
34. https://openaccess.nhh.no/.../no.nhh:wiseflow:7041862:57768611.pdf — **[pdf attempt]** returned 0 extractable characters; the apparent LM-dictionary/MNIR/GPT comparison study referenced in search results was **not** read.
35. https://eftconference.business-school.ed.ac.uk/sites/eft_conference/files/2022-06/Garcia%20paper.pdf — **[pdf attempt]** DNS resolution failure.

**Sources named in search results but never fetched — explicitly NOT cited as evidence:** Brown & Tucker (2011); Feldman, Govindaraj, Livnat & Segal (2010); Huang, Teoh & Zhang (2014) *Tone Management*; Bao & Datta (2014) *Management Science*; Huang & Li (2011) *ACM TMIS*; Liu et al. (2014) on XBRL and analyst following (known only via a thesis that cites it); arXiv:2601.15247 (LLM risk extraction); arXiv:2602.17234 / arXiv:2603.11838 (contamination and DATEDGPT).
