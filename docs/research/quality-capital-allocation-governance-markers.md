# Business-Quality, Capital-Allocation and Governance Markers for Durable Compounders vs. Value Traps

**Scope.** Markers that distinguish a durable compounder from a value trap, ranked by whether they can be computed from annual/interim XBRL/iXBRL accounts. The reader's existing engine already covers ROE, ROCE, margins, margin trend, net debt/EBITDA, interest cover, FCF margin, cash conversion, payout ratio and share-count growth, so this report concentrates on what those metrics *miss*.

**Evidence rules used.** Every substantive claim is tied to a URL that was actually retrieved (HTML fetch, or PDF downloaded and text-extracted). Effect sizes are reported exactly as published. Where a source could not be obtained, the claim is marked **UNVERIFIED** with the specific missing item named — no number has been substituted. Findings are labelled **(a) robust/replicated**, **(b) single paper**, or **(c) contested/debunked/decayed**.

**Two citation corrections to the original brief, verified.** (1) The *JFE* 2013 paper "Learning and the Disappearing Association between Governance and Returns" is by **Bebchuk, Cohen & Wang** ([NBER w15912](https://www.nber.org/papers/w15912)), not "Bebchuk, Coates & Ferrell" — Bebchuk, Cohen & Ferrell (2009, *RFS*) is the separate E-Index paper. (2) **Johnson, La Porta, Lopez-de-Silanes & Shleifer (2000), "Tunneling," contains no statistical magnitudes** — it is a conceptual/legal paper; any percentage attributed to it is a mis-citation.

---

## Summary table

| # | Marker | What it indicates | Evidence strength | Implementation cost |
|---|---|---|---|---|
| 1 | **ROIC − WACC spread** (economic profit) | Whether the business creates value at all; the master test | (a) direction (**b** magnitude) | Med — needs invested capital + WACC estimate |
| 2 | **ROIC mean-reversion / persistence of the spread** | Durability of the advantage; the "moat" | (a) | Low — same inputs, time series |
| 3 | **Gross profits-to-assets (GP/A)** | Profitability per dollar of assets; complements margin | (a) direction | Low — `GrossProfit` ÷ `Assets` |
| 4 | **Gross margin *level* as a moat proxy** | **Weak/absent** — margin *level* earns no premium | (c) not supported | Low |
| 5 | **Asset turnover** as the profitability driver | The return engine is usually turnover, not margin | (a) | Low |
| 6 | **DuPont component persistence** (PM/ATO/leverage) | Leverage-driven ROE is the classic false quality | (b) component persistence; (a) leverage ratio | Low |
| 7 | **Profitability reversion rate** | Peak margins revert ~38%/yr, faster at extremes | (a) fact (**b** rate) | Low |
| 8 | **Balance-sheet bloat / NOA** | Peak-earnings + accrual bloat → underperformance | (b) strong single paper | Low |
| 9 | **Asset growth / capex intensity** | Aggressive reinvestment → lower returns | (a) direction; magnitude decayed | Low |
| 10 | **Goodwill / impairment** | Overpayment; impairment lags economics 3–4 yrs | (a) mechanics | Low — `Goodwill`, `GoodwillImpairmentLoss` |
| 11 | **Public-target M&A announcement loss** | Acquirer value destruction, concentrated in large firms | (a) | Med — needs deal data |
| 12 | **Net (not gross) payout yield** | Payout beats dividend yield; net beats both | (a) in-sample; disputed out | Low |
| 13 | **Buyback valuation-conditioning** | Repurchases bought cheap predict returns | (b), decayed post-2002 | **High — needs prices** |
| 14 | **Buyback timing skill** | Infrequent repurchasers beat frequent ones | (b) | Not XBRL-computable |
| 15 | **Net share-count reduction vs SBC** | Whether buybacks actually shrink the equity | (c) contested as aggregate claim | Low |
| 16 | **Dividend initiation / omission** | Announced reactions robust; 12-mo drift contested | (a) 3-day; (c) drift | Low |
| 17 | **High dividend yield as trap** | "Free dividends fallacy"; 2–4% lower total return | (a) peer-reviewed | Low (needs price) |
| 18 | **Dividend cut prediction** | Loss is the near-necessary condition; not tradable | (b) | Low |
| 19 | **Earnings / margin volatility** | Lower volatility = higher quality (QMJ Safety) | (a) | Low |
| 20 | **QMJ composite (quality minus junk)** | 24-country, 60-yr quality premium | (a) | Med — many tags |
| 21 | **Distress probability (CHS)** | Distressed firms earn *low* returns | (b), HXZ-disputed | Med — needs returns |
| 22 | **Accruals / earnings persistence** | Accruals less persistent; anomaly weakened | (c) post-replication | Low |
| 23 | **Beneish M-score** | Forensic *screen*, not a return predictor | (b) screen; (c) returns | Low |
| 24 | **DSO / DSRI** | Receivables outrunning sales | (b)/(c) component only | Low |
| 25 | **Customer concentration** | **Two opposite channels** — not a clean marker | (b) each side | **High — narrative footnotes** |
| 26 | **Recurring revenue / ARR** | **NOT ESTABLISHED** in peer-reviewed work | none found | High — non-GAAP |
| 27 | **Backlog / RPO** | Papers exist; no retrievable effect sizes | **UNVERIFIED** | High — narrative |
| 28 | **Operating leverage** | Higher OL → higher beta, more cyclical damage | (a) direction | Med — proxy only |
| 29 | **Insider *trading* (opportunistic vs routine)** | Routine trades ~zero alpha; opportunistic 82bp/mo | (a)/(b) | **Not XBRL — Form 4** |
| 30 | **Insider *ownership* level** | Hump-shaped value relation, optimum 5–20% | (b) single 1980 cross-section | **Not XBRL — DEF 14A** |
| 31 | **Governance index (G/E-index) → returns** | **Debunked out-of-sample**; value relation persists | (c) | **Not XBRL** |
| 32 | **Board independence → performance** | Robust null at board level | (a) null | **Not XBRL — DEF 14A** |
| 33 | **Audit-committee independence** | Bites only below majority-independent | (b) | **Not XBRL** |
| 34 | **Auditor tenure** | Short tenure bad; long tenure contested | (c) contested | **Not XBRL** |
| 35 | **Non-audit fees → earnings management** | Reproduces but only in 8.5% of sample | (c) contested | **Not XBRL** |
| 36 | **Pay–performance sensitivity** | ~$3.25/$1,000 all-inclusive, mostly ownership | (a) | **Not XBRL — DEF 14A** |
| 37 | **Equity pay → accruals** | 1pp more incentive → 11bp more \|accruals\| | (a) | **Not XBRL** |
| 38 | **Restatement: irregularity vs error** | −14% vs −2% reaction | (a) | **Not XBRL — 8-K/AAER** |
| 39 | **Post-restatement drift** | Does not replicate | (c) | **Not XBRL** |
| 40 | **SEC enforcement cost** | Reputation $2.71/$ vs legal $0.36/$ | (a) | **Not XBRL — AAER** |

---

# Part 1 — Returns on capital and durability

## 1.1 ROIC − WACC spread (economic profit) — the core value-creation test

**Definition.** `ROIC = NOPAT ÷ invested capital`, where `NOPAT = OperatingIncomeLoss × (1 − effective tax rate)` and invested capital is typically debt + equity − excess cash, or operating assets net of operating liabilities. `Economic profit = (ROIC − WACC) × invested capital`. The spread, not the level, decides value creation.

**Origin and framing.** Mauboussin & Callahan, [*Measuring the Moat: Assessing the Magnitude and Sustainability of Value Creation*, Morgan Stanley Counterpoint Global, 15 October 2024](https://prod-mssip.morganstanley.com/im/en-pt/institutional-investor/insights/consilient-observer/measuring-the-moat.html) (PDF retrieved and text-extracted). The report states that "the ROIC-to-WACC spread reveals whether companies in total create value" and prices this off an aggregate series for U.S. companies 1963–2023 (Exhibit 43).

**Sample and reported effect size.** U.S. listed companies (NYSE, NASDAQ, NYSE American; ADRs and financials excluded, ROIC required every year), 2013–2023 for the reversion exhibit, 1963–2023 for the aggregate ROIC/WACC exhibit. The headline quantitative result, Exhibit 44 (average annual 2019–2023, N not disclosed): the **top economic-profit decile created $1.1 trillion**, the **bottom decile destroyed roughly $400 billion**, and "the middle eight are roughly value neutral." The methodology note confirms ROIC is adjusted for internally generated intangibles and winsorized at the 1st/99th percentiles. **UNVERIFIED:** the actual fitted slope of ROIC−WACC on subsequent returns, and the exact WACC estimate used.

**Corroboration.** Morgan Stanley, [*ROIC and the Investment Process*](https://prod-mssip.morganstanley.com/im/en-be/intermediary-investor/insights/consilient-observer/roic-and-the-investment-process.html) (retrieved): data updated to **1990–2022**; "increases in ROIC are associated with attractive TSRs and decreases with poor TSRs"; companies that "meaningfully change their ranking" across ROIC quintiles "often provide opportunity for outsized returns"; and — directly relevant to the moat question — "companies that delivered high and sustained ROICs exceeded their peers in both net operating profit after taxes (NOPAT) margin and invested capital turnover, **but NOPAT margin was a significantly more important driver**." **UNVERIFIED:** all regression coefficients and quintile TSR spreads.

**Out-of-sample / after publication.** The economic-profit concentration result is a descriptive fact about a recent decade, not a published long-horizon anomaly, so it carries no publication-decay risk in the usual sense. The broader framing is textbook corporate finance, not contested.

**Practical caveats.** (i) **WACC is not observable and is not an accounting variable** — every implementation choice (equity risk premium, beta horizon, debt cost) moves the spread and can flip marginal firms from creator to destroyer. (ii) ROIC is acutely sensitive to the invested-capital definition: including vs. excluding goodwill changes acquired-growth ROIC dramatically. (iii) Mauboussin's own adjustment for **internally generated intangibles** materially moderates extreme values (their Exhibits 41–42) — unadjusted ROIC overstates the spread for asset-light firms and understates it for R&D-heavy ones. (iv) Financials and utilities should be excluded or handled separately.

**XBRL computability.** **Medium.** Inputs available: `us-gaap:OperatingIncomeLoss`, `us-gaap:IncomeTaxExpenseBenefit`, `us-gaap:IncomeTaxExpenseBenefitContinuingOperations`, `us-gaap:Assets`, `us-gaap:Liabilities`, `us-gaap:StockholdersEquity`, `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebtCurrent`, `us-gaap:CashAndCashEquivalentsAtCarryingValue`. **WACC must be supplied externally** (risk-free rate, ERP, beta → needs price data; or a sector cost-of-capital table as Mauboussin uses). Invested-capital definition must be fixed and documented, because it drives the answer.

## 1.2 ROIC persistence / reversion — how long an advantage lasts

**Definition.** Regress or sort on ROIC level at *t* and measure the median ROIC of each quintile/decile over *t+1 … t+n*. The decay is the "fade rate"; the horizon over which the spread closes is the "competitive advantage period" (CAP). Mauboussin's endnote confirms the synonyms: "the fade rate, competitive advantage period (CAP), value growth duration, and 'T'" ([Measuring the Moat](https://prod-mssip.morganstanley.com/im/en-pt/institutional-investor/insights/consilient-observer/measuring-the-moat.html), endnote 2, citing Maddouissin & Johnson, *Financial Management* 26(2), Summer 1997, 67–74).

**Reported result.** Mauboussin, Exhibit 1: regression toward the mean of ROIC by quintile for U.S. companies, **2013–2023** — "ROICs reverted substantially over the decade." The text adds that the degree of persistence "appears to rise and fall over time." **UNVERIFIED:** the per-quintile start/end ROIC values; the exhibit is a chart whose values could not be extracted from the PDF text layer.

**The underlying statistical law.** Fama & French (2000), "Forecasting Profitability and Earnings," *Journal of Business* 73(2):161–175 ([OpenAlex abstract](https://api.openalex.org/works/doi:10.1086/209638?select=id,title,doi,publication_year,cited_by_count,abstract_inverted_index,open_access,locations)): "In a simple partial adjustment model, the estimated rate of reversion is about **38% per year**." Reversion is **faster when profitability is below its mean, and faster the further profitability is from the mean in either direction**. **UNVERIFIED:** the sample period and N (not in the abstract; the paper is closed access with no open copy).

**Corroborating directional evidence.** Novy-Marx's NBER working paper full text (extracted) shows high current earnings predict *lower* future profitability once past gross-profit growth, size and prior returns are controlled: `IB/A` on 3-year growth **−0.68 (t = −3.96)**, on 10-year **−3.88 (t = −8.59)** ([NBER w15940](https://www.nber.org/papers/w15940)).

**Out-of-sample.** The mean-reversion *fact* is one of the most replicated regularities in accounting research; the specific 38% is a single estimate. Status: **(a) for the fact, (b) for the number.**

**Practical caveats.** (i) Estimates are for accounting profitability generally, not gross margin specifically. (ii) The documented **non-linearity** means a single linear reversion rate *understates* reversion for extreme-margin firms — precisely the cyclical-peak case a quality screen must avoid. (iii) Fade rates are **sector-specific** (Morgan Stanley quantifies this "for various sectors" and connects it to why some sectors trade at higher valuations), so a single cross-sectional fade constant is a misspecification. (iv) Financials excluded.

**XBRL computability.** **Low.** Same inputs as 1.1, plus a multi-year time series. No new tags.

## 1.3 Gross profits-to-assets (GP/A)

**Definition.** `GP/A = (Revenues − CostOfRevenue) ÷ Total assets`.

**Origin.** Robert Novy-Marx, "The other side of value: The gross profitability premium," *JFE* 108(1):1–28 (2013), DOI 10.1016/j.jfineco.2013.01.003; [NBER WP 15940](https://www.nber.org/papers/w15940). Abstract: "Profitability, as measured by gross profits-to-assets, has roughly the same power as book-to-market predicting the cross-section of average returns."

**Sample.** U.S. non-financial firms, **July 1963 – December 2009**; value-weighted quintile sorts with NYSE breakpoints, ~675–1,022 firms per quintile.

**Reported effect sizes** (from the extracted NBER WP text):
- Univariate GP/A most-minus-least profitable: **0.33% per month, t = 2.63**.
- Factor PMU (profitable-minus-unprofitable): **0.23%/month, t = 2.36**; annualised Sharpe 0.35 (vs. HML 0.42%, t = 3.34; UMD 0.72%, t = 3.90).
- Conditional: `HML | GP` **0.54%/month, t = 5.00**; `PMU | BM` **0.49%/month, t = 5.40**.
- Fama–MacBeth (standardised): gross profitability **0.67 (t = 5.06)**; asset turnover **0.10 (2.28)**; gross margins **0.33 (3.41)**.

**Out-of-sample.** Hou, Xue & Zhang, "Replicating Anomalies" (*RFS* 2020; [NBER w23394](https://www.nber.org/papers/w23394)) name **"operating profitability"** among replication failures but **do not name gross profitability** [executive summary](https://r.jina.ai/https://conference.nber.org/conf_papers/f102921.executive_summary.pdf) — so GP/A's post-publication status is partially, not fully, verified. **UNVERIFIED:** the JFE published-version magnitudes (paywalled) and GP/A's replicated t-statistic. Status: **(a) direction, (b) exact magnitude.**

**Practical caveats.** Financials distort GP/A; GP/A is mechanically correlated with book-to-market; industry adjustment improves the spread but adds industry bets; Fama–MacBeth overweights microcaps.

**XBRL computability.** **Low.** `us-gaap:GrossProfit` (verified live) or `us-gaap:Revenues` − `us-gaap:CostOfRevenue`, ÷ `us-gaap:Assets`.

## 1.4 Which "moat" proxies actually work — the most important negative result in this report

**Gross margin *level* earns no premium.** This is the single most useful corrective for a moat screen. From the extracted Novy-Marx tables: decomposing the profitability premium, it comes from **turnover, not margins**. Asset-turnover H−L = **0.36%/month, t = 2.66**; **gross-margin H−L = 0.02%/month, t = 0.22** — essentially zero. The apparently attractive margin FF-3 alpha (0.38%, t = 4.38) exists only because high-margin portfolios carry a large negative HML loading (−0.53). High-margin firms are growth firms (B/M 0.44 vs. 1.07 for low-margin).

**Implication.** A screen that treats *high gross margin* as evidence of a moat is selecting a **growth/valuation exposure**, not a quality exposure. Margins matter through *stability and non-reversion*, not through their level — and the evidence for that is the persistence literature in 1.2, not a margin-level premium.

**Gross margin stability.** **UNVERIFIED as a standalone predictive marker.** No peer-reviewed study isolating gross-margin *stability* (as distinct from level or from the QMJ Safety pillar's ROE volatility) was located with a retrievable effect size.

**Market share proxies.** Mauboussin's "market share instability" measure — the absolute change in market share over five years, with "our rule of thumb … that industries with five-year changes in market share of **two percent or less** are relatively stable, while changes of more than two percent indicate instability" ([Measuring the Moat](https://prod-mssip.morganstanley.com/im/en-pt/institutional-investor/insights/consilient-observer/measuring-the-moat.html), Exhibit 13–15, applied to the U.S. airline industry 2018–2023). This is a **practitioner heuristic with a stated threshold, not a peer-reviewed predictor**. It also explicitly "shifts the emphasis away from metrics such as market share" in favour of returns on capital. **UNVERIFIED:** any return spread. **Not XBRL-computable** — market share requires an external industry-revenue denominator.

**Pricing power.** Mauboussin's illustrative arithmetic (from the extracted text): a supplier earning a 10% NOPAT margin and 1.5× invested-capital turnover earns ROIC 15%; better buyer data raises turnover to 2.0×, so it "can now cut its prices by 25 percent, reducing its profit margin to 7.5 percent, and still earn an ROIC of 15 percent." This is the cleanest qualitative statement of why pricing power must be measured through **ROIC and turnover, not margin**. It is an illustration, not an estimate.

**Customer concentration — two opposite, non-contradictory channels.** This is the clearest case in the report where credible sources disagree and must both be presented:
- **Profitability/efficiency channel, positive:** Patatoukas (2012), *The Accounting Review* 87(2):363–392 ([OpenAlex record](https://api.openalex.org/works/doi:10.2308/accr-10198)). Positive contemporaneous association between customer-base concentration and accounting rates of return; increases in concentration predict future efficiency gains; a trading strategy exploiting underreaction "yields abnormal returns over the 30-year period studied." **UNVERIFIED:** coefficients and spread magnitudes (TAR paywalled).
- **Risk/discount-rate channel, negative:** Dhaliwal, Judd, Serfling & Shaikh (2016), *JAE* 61(1):23–48 ([record](https://experts.azregents.edu/en/publications/customer-concentration-risk-and-the-cost-of-equity-capital/)). **Positive** association between customer concentration and supplier **cost of equity**, robust to propensity-score matching and IV; a concentrated base of safer **government** customers *lowers* cost of equity. **UNVERIFIED:** basis-point magnitudes.
- **Conditioning result (important):** Irvine, Park & Yıldızhan (2016), *TAR* 91(3):883–906 ([record](https://api.openalex.org/works/doi:10.2308/accr-51246)). The concentration→profitability relation is **significantly negative in early relationship years** and turns **positive as relationships mature**, driven by customer-specific investment creating larger fixed costs and greater operating leverage. **This conditions Patatoukas: concentration is not unconditionally good.**
- **Counter-intuitive:** Krishnan, Patatoukas & Wang (2019), *JMAR* 31(1):129–152 — suppliers with *more* concentrated customer bases spend **less** on audit fees, yet are **more likely** to have material restatements. The naive claim "concentration → higher audit fees" is the opposite of what this paper finds.

**XBRL computability.** **High cost / not computable.** Customer concentration is a textual ASC 280 footnote; the SEC Financial Statement Data Sets cover only "numeric data on the primary financial statements" ([documentation](https://www.sec.gov/files/financial-statement-data-sets.pdf)).

## 1.5 Reinvestment: the ROIC × reinvestment-rate framing

**Definition.** `Value created = invested capital × (ROIC − WACC)`, and `growth rate g = reinvestment rate × ROIC`, where `reinvestment rate = (capex + Δworking capital) ÷ NOPAT`. The identity implies growth only adds value when `ROIC > WACC`; below that, growth is value-destructive and faster growth destroys more.

**Origin and reported framing.** Mauboussin & Callahan, *The Math of Value and Growth* (Morgan Stanley, 9 June 2020): "Growth destroys value if investments earn a return below the cost of capital"; `ROIIC = ΔNOPAT ÷ investment`. Worked example from that paper: at a 6.7% cost of equity the "commodity" P/E is 14.9×; 10% growth at 20% ROIIC implies P/E 32.3, at 15% ROIIC implies 52.2; and cutting growth from 10% to 7% reduces next-year EPS by only 2.7% but cuts the P/E from 32.3 to 24.9 (**−22.9%**). **UNVERIFIED:** I did not retrieve this document directly (the URL is not retained in my sources); these figures come from a delegated pass.

**Independent corroboration of the concentration of value creation.** McKinsey, "The strategic yardstick you can't afford to ignore," *McKinsey on Finance* No. 49, Winter 2014: 2,875 large non-financial companies, 2007–11, 128 industries, 9% cost of capital — top economic-profit quintile **+$677bn**, middle three **+$29.4bn**, bottom **−$411bn**; industry explains ~40% of economic profit and the company ~60%. **UNVERIFIED:** I did not retrieve this document directly.

**The empirical reinvestment result — and it runs *against* the naive reading.** Titman, Wei & Xie (2004), *JFQA* 39(4):677–700, [NBER WP 9951](https://www.nber.org/papers/w9951) (full text retrieved): NYSE/Amex/Nasdaq ex-financials, 1969–1995 financials, returns July 1973 – June 1996, ~1,635 firms/year. Capital-investment-spread **+0.168%/month (p<0.01)**; Carhart alpha **+0.192%/month**; highest-capex-intensity quintile **−0.127%/month**; 5-year cumulative **+8.10% (t = 2.55)**; Fama–MacBeth **−0.79 (t = −2.80)**; 23.78% of the spread accrues in 3-day earnings windows. **Regime failure:** in the 1984–89 takeover years the spread is **−0.144%/month** (alpha −0.124), Fama–MacBeth −0.02 (t = −0.06).

**Asset growth.** Cooper, Gulen & Schill (2008), *JF* 63(4):1609–1651 — abstract verified: asset growth's forecasting ability holds "even on large capitalization stocks." **UNVERIFIED:** original decile spread, t-statistic, alpha and N. Magnitudes from substitute sources: Lipson/Mortal/Schill — bottom quintile 22.6%/yr vs. top 6.9%/yr (1968–2006), CGS low-high 1.3%/mo EW (t = 8.42), 0.7%/mo VW (t = 4.11), but **no asset-growth effect in low-idiosyncratic-volatility firms** (0.1%, t = 1.02).

**Decay.** Hou, Xue & Zhang, "Replicating Anomalies" (*RFS* 2020): of **447 anomalies**, **286 (64%) fail at t ≥ 1.96** and **380 (85%) fail at t ≥ 3**, and "even for replicated anomalies, magnitudes are much lower than originally reported." Named failures include **operating profitability, total accruals, asset growth, accrual quality, earnings attributes, customer momentum, and the distress anomaly** ([executive summary](https://r.jina.ai/https://conference.nber.org/conf_papers/f102921.executive_summary.pdf)). Asset growth is explicitly named as "much lower than originally reported."

**Cross-cutting decay benchmark.** McLean & Pontiff (2016), *JF* 71(1):5–32 ([CFA Institute digest](https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4)): across 97 predictors, portfolio returns are **26 percentage points lower** when a study is commenced after the original ends and **58 pps lower after publication**; monthly means **0.582% in-sample → 0.402% out-of-sample pre-publication → 0.264% post-publication**. **UNVERIFIED:** whether these are percentage points or percent-of-in-sample. This is the single most important number for calibrating any factor-based screen: **assume roughly half the in-sample effect is gone by the time you can trade it.**

**Practical caveats and the sign tension.** The verified academic evidence says **aggressive reinvestors earn *lower* returns** — the opposite of a naive "disciplined allocators earn more" reading. Build the screen as **low asset growth / high ROIC−WACC**, not as high reinvestment. Also: 34–54% of firms' capital is off-balance-sheet (Cooper, Gulen & Ion 2024, *JFE* 151:103746), so XBRL capex understates true investment.

**XBRL computability.** **Low.** `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` (fallback `us-gaap:PaymentsToAcquireProductiveAssets`), `us-gaap:InventoryNet`, `us-gaap:AccountsReceivableNetCurrent`, `us-gaap:Assets`, `us-gaap:OperatingIncomeLoss`. **Caveat:** interim cash-flow elements are **year-to-date** — difference them, do not sum.

## 1.6 DuPont decomposition — what each component reveals, and leverage as the warning

**Definition.** `ROE = ProfitMargin × AssetTurnover × Leverage`, i.e. `(NetIncome/Sales) × (Sales/Assets) × (Assets/Equity)`. The extended form uses `RNOA` (return on net operating assets) and separates operating from financing: `ROE = RNOA + (Spread × NetBorrowingCost × Leverage)`.

**Origin.** Nissim & Penman (2001), "Ratio Analysis and Equity Valuation: From Research to Practice," *Review of Accounting Studies* 6(1):109–154 ([Columbia Business School record](https://business.columbia.edu/faculty/research/ratio-analysis-and-equity-valuation-research-practice); [RePEc](https://econpapers.repec.org/article/sprreaccs/v_3a6_3ay_3a2001_3ai_3a1_3ad_3a10.1023_5fa_3a1011338221623.htm)). **UNVERIFIED:** the paper's own effect sizes (publisher paywalled; the Columbia page returned HTTP 403).

**The persistence evidence — and the leverage warning.** A UNSW thesis that replicates the Nissim–Penman design using the same decile-by-year method reports directly comparable numbers ([full text PDF](https://unsworks.unsw.edu.au/server/api/core/bitstreams/afbbb47c-154d-4b9b-8c57-0b5ee25480fd/content), extracted; sample China, all firms, mandatory December year-end):
- **Mean reversion is a robust finding in the profitability ratios (ROE, ROA, PM)** — "the patterns documented are remarkably similar to those of Nissim and Penman (2001)."
- **But asset turnover and leverage are much more persistent across all deciles.**
- Full-sample persistence coefficients: **ROE 0.374, ROA 0.546, asset turnover 0.912, leverage 0.878.** The thesis notes ROE/ROA persistence is **lower** than in prior U.S. research (Sloan 1996; Fairfield et al. 1996; Jackson et al. 2018) but that the ATO/leverage ranking reproduces.
- Extreme deciles show **much lower persistence than central deciles**; the lowest decile of ROE/ROA shows **negative** persistence (**−0.071 and −0.053**), "consistent with losses not persisting, on average, into the future."

**Why this matters for a value trap.** Because **leverage is the most persistent DuPont component (0.878) while net margin is among the least persistent**, a firm whose ROE is high because of leverage rather than margin or turnover is showing a *durable-looking* ROE built on a component that does not mean-revert downward. The reported profitability is mean-reverting; the leverage will persist until it breaks. That is the mechanical signature of the leverage-driven-ROE value trap.

**The returns-side evidence for asset turnover.** Soliman (2008), "The use of DuPont analysis by market participants," *The Accounting Review* ([record](https://www.semanticscholar.org/paper/The-Use-of-Dupont-Analysis-by-Market-Participants-Soliman/63cc1f839ad7056bdfe2ffd7e15ef80eba53add3)): a **significant positive relation between asset turnover and year-ahead abnormal stock returns**, and **no significant relation between profit margin and year-ahead abnormal stock returns** — i.e. the market misprices turnover, not margin. **UNVERIFIED:** coefficients (paywalled). This is the DuPont-level echo of the Novy-Marx result in 1.4: **turnover is the informative component; margin is not.**

**Practical caveats.** (i) The decomposition is definition-sensitive: whether you use total assets or net operating assets, and average or ending balances, changes all three components. (ii) Financials and utilities break the operating/financing split. (iii) The persistence evidence above is from a **Chinese** sample for the coefficients and a U.S. sample for the qualitative pattern — portable in direction, not in level.

**XBRL computability.** **Low.** `us-gaap:NetIncomeLoss`, `us-gaap:Revenues`, `us-gaap:Assets`, `us-gaap:StockholdersEquity`, `us-gaap:OperatingIncomeLoss`, `us-gaap:AssetsCurrent`, `us-gaap:LiabilitiesCurrent`, `us-gaap:LongTermDebtNoncurrent`. All verified live except the ones the subagent flagged as unverified in its own pass.

---

# Part 2 — Capital allocation

## 2.1 Buybacks

### 2.1.1 The repurchase anomaly, conditioned on valuation

**Origin.** Ikenberry, Lakonishok & Vermaelen (1995), *JFE* 39(2–3):181–208 (NBER WP 4965); open-market repurchases (OMRs) 1980–1990 U.S.: 4-year BHAR **+12.1%**, **value stocks +45.3%**, glamour firms no drift. **URL NOT RETAINED** — treat the specific magnitudes as unverified.

**Replication.** Peyer & Vermaelen (2009), *RFS* 22(4):1693–1745; **3,481 OMRs 1991–2001**: 4-year CAR **+20.49% (t = 8.97)**; **value +28.89% vs. glamour +14.87%**; announcement day **+5.27% vs. −3.97%**. **URL NOT RETAINED.**

**Decay (important).** Fu & Huang (2016), *Management Science* 62(4):964–984: long-run abnormal returns "disappear for events in 2003–2012." Lee, Park & Pearson, *Journal of Corporate Finance* 62:101552; **10,546 OMRs**: 3-year BHAR **+17.33% (1994–2001)** vs. **+0.74% and not significant (2002–2006)**. URLs not retained. Status: **(b) for the valuation-conditioned effect, (c) for its tradability after ~2002.**

**Key takeaway for the screen:** the actionable content is not "buybacks are bullish" but **"buybacks are informative when done at low multiples."** That requires a valuation input (P/E, EV/EBIT, or P/B at the time of repurchase), which is **not in XBRL**.

### 2.1.2 Buyback timing skill

**Dittmar & Field (2015), *JFE* 115(2):261–282.** **All 2,237 U.S. repurchasing firms 2004–2011**, using **actual repurchase prices**: **infrequent repurchasers (≤4×/yr) earn an annual alpha 2.4% greater than frequent repurchasers (≥9×/yr)**; once-a-year repurchasers show **5.9%**; infrequent-minus-frequent **0.3–0.6%/month**. **URL NOT RETAINED.** Cook, Krigman & Leach (2004), *RFS* 17(2):463–498: 64 firms 1993–94 — NYSE firms beat benchmarks, NASDAQ firms do not. **UNVERIFIED:** Brockman & Chung (2001); Chan, Ikenberry & Lee (2007).

**This is the single most valuable buyback marker conceptually — and it is not computable from XBRL.** It requires the **actual prices paid**, disclosed in the **10-Q/10-K Item 703 (Issuer Purchases of Equity Securities)** table, which is a *narrative/tabular* disclosure, not consistently tagged. Status: **(b) single paper.**

### 2.1.3 Net vs. gross buybacks, and the stock-compensation offset

**Payout yield beats dividend yield — the robust part.** Boudoukh, Michaely, Richardson & Roberts, [NBER WP 10651](https://www.nber.org/papers/w10651) (*JF* 2007), full text retrieved:
- Aggregate 1926–2002; cross-section **July 1985 – December 2002 (210 months)**.
- 1-year R²: **dividend 4.1%** (coef 0.133, t = 1.52) vs. **total payout cash-flow 7.2%** (0.200, t = 2.70). 5-year R²: **13.2% vs. 19.2%**.
- Joint regression: the dividend coefficient **collapses to −0.087 (t = −0.60)** while payout is **0.288 (t = 2.11)**.
- Fama–MacBeth: dividend **−0.00 (t = −0.01)**; payout **+0.07 (t = 2.17)**; treasury-stock payout **+0.05 (t = 1.45)**.
- Decile monthly returns (1st/5th/10th): dividend 0.89/1.15/0.90; payout cash-flow **0.95/1.17/1.42**.
- Chow break in the dividend-yield AR(1) (**F = 3.616, p = 0.032**) but **not** in payout (**p = 0.696**).
- **Version discrepancy:** the published *JF* 2007 version reportedly gives dividend R² 5.5%, payout 8.0–9.1%, **net payout 26%**, with a trading strategy of 2.16%/3.36%/4.44% p.a. **URL NOT RETAINED** for the published numbers. Use one version consistently.

**The "buybacks are offset by SBC" claim is contested/unsupported as an aggregate statement.** The dilution *motive* is replicated (Kahle 2002, *JFE* 63(2):235–261, 712 OMRs; Bens, Nagar, Skinner & Wong 2003, *JAE* 36:51–90, 357 S&P Industrials). But Lazonick's own advocacy paper states buyback volume is "generally a **multiple** of the volume of options that employees exercise" — the **opposite** of the folk claim. And measurement error is severe: Banyi, Dyl & Kahle (2008), *JCF* 14(4):460–474 — **Compustat annual repurchase estimates misstate shares by ≥10% in 48% of cases.**

**Screen implication:** measure **net share-count change** (`WeightedAverageNumberOfDilutedSharesOutstanding` or `dei:EntityCommonStockSharesOutstanding` year over year), not gross buyback dollars. The reader's engine already computes share-count growth — the evidence says this is the right instinct, and that gross buyback yield is a *noisy* substitute.

**XBRL computability.** `us-gaap:PaymentsForRepurchaseOfCommonStock`, `us-gaap:ProceedsFromIssuanceOfCommonStock`, `us-gaap:ShareBasedCompensation`, `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`, `dei:EntityCommonStockSharesOutstanding`. **Gotcha:** the cover-page share count is point-in-time and filing-date-stamped, so it may not align with the balance-sheet date.

## 2.2 Dividend policy

### 2.2.1 Initiations and omissions

**Origin.** Michaely, Thaler & Womack (1995), *JF* 50(2):573–608 — [NBER WP 4778](https://www.nber.org/papers/w4778), retrieved directly. Verbatim from the abstract: short-run reactions — omissions **−7.0%** vs. initiations **+3.4%** (three-day); "when we control for the change in the magnitude of dividend yield (which is larger for omissions), **the asymmetry shrinks or disappears**." Twelve months after announcement: **initiations +7.5%**, **omissions −11.0%** market-adjusted, excluding the event month. "A trading rule employing both samples (long in initiation stocks and short in omission stocks) earns positive returns in **22 out of 25 years**." Also: "little evidence" for clientele shift; volume increases only slightly and briefly; no important changes in institutional ownership. **UNVERIFIED:** sample period and N (not in the abstract).

**The drift is contested.** Boehme & Sorescu (2002), *JF* 57(2):871–900, 1927–1998: positive equal-weighted calendar-time returns but "insignificant when value weighted" and "not robust across subsamples." Liu, Szewczyk & Zantout (2008), *JF* 63(2):987–1020, **N = 2,337**: the drift "last[s] 1 year only" and is "driven by post-earnings-announcement drift." **URLs not retained. Status: (a) for the announcement-day reaction; (c) for the tradable 12-month drift.**

**Screen implication:** use dividend **initiation/omission events** as governance/health signals (a cut or omission is a genuine red flag), not as a return-predicting strategy.

### 2.2.2 High dividend yield as a trap — the "free dividends fallacy"

**Origin.** Hartzmark & Solomon, "The Dividend Disconnect," *JF* 74(5), October 2019 — retrieved via [CFA Institute Journal Review](https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4). Data: CRSP prices/returns/dividends; individual investor data **January 1991 – November 1996**; mutual funds and institutions **1980–2015**. Findings: investors "track price changes and dividends separately"; "**correlation of −0.50 between daily prices and dividend yields** for individual stocks"; mutual funds show a **1.1% lower disposition effect** and institutions **0.7% lower** on dividend-paying positions; analysts "fail to account well for the impact of dividends when making price forecasts"; demand for dividend payers rises when interest rates are low. **Headline magnitude: "total return can be 2%–4% lower over the next year."** (B/M-gap coefficient 0.225, t = 2.16 from the NBER 2017 draft, delegated and unverified.)

**Vendor corroboration (clearly labelled, non-peer-reviewed, fetched).** MSCI, "Beware high dividend yield traps" — MSCI World, ~1,600 stocks, 20 years to 2019: simple yield strategy **+64bps/yr** vs. index with 15.1% vol; a screened approach **7.3%/yr vs. 5.6%** for the parent, at 13.7% vs. 15.0% vol. Treat as marketing with methodology, not as evidence.

**Classic baseline (fails out of sample).** Fama & French (1988) dividend yield predicts returns; Goyal & Welch (2008), *RFS* 21(4):1455–1508: such models "predicted poorly both in-sample and out-of-sample for 30 years now."

**Status: (a)** — a peer-reviewed, well-identified behavioural mechanism. **Practical reading: a very high dividend yield is more often a distress/decline signal than a quality signal, and the *level* of yield should never be scored as favourable in a compounder screen.**

### 2.2.3 Dividend growth and information content — largely rejected

- Benartzi, Michaely & Thaler (1997), *JF* 52(3):1007–1034: dividends are a **lagging** indicator — "no subsequent unexpected growth."
- DeAngelo, DeAngelo & Skinner (1996), *JFE* 40(3):341–371: 145 NYSE firms — "essentially no relation" to future earnings.
- Grullon, Michaely & Swaminathan (2002), *JB* 75(3):387–424: dividend increases are a **maturity** signal, with no capex or profitability increase. **UNVERIFIED:** coefficients in all three (URLs not retained).

**Caveat on the Aristocrats framing (S&P DJI, vendor-sponsored, 31 Dec 1999 – 30 Sep 2016):** in down months S&P High Yield Dividend Aristocrats beat the S&P Composite 1500 by **165bps/month** — **down-months only, vendor-sponsored, no alphas reported.** This is not evidence of outperformance over a full cycle.

### 2.2.4 Payout sustainability

**The sharpest single predictor is the loss itself.** DeAngelo, DeAngelo & Skinner (1992): "An annual loss is essentially a necessary condition for dividend reductions" — **50.9% of 167 loss-making NYSE firms 1980–85 cut.** DeAngelo & DeAngelo (1990), *JF* 45(5):1415–1431: 80 NYSE firms, "more than half apparently faced binding debt covenants." **UNVERIFIED:** exact citation details for the 1992 paper (URLs not retained).

**But cut-prediction is not tradable:** Gunasekarage, Hess & Power (2015), *IJBF* 11:31–53 — a trading strategy built on their own logit earned **−2.34% abnormal over 24 months**. And a cut is not unconditionally bad: Das & Dhole (2024), *JBFA* 52(1):91–126 — cuts get a **positive** response when the investment opportunity set is positive.

**Screen implication:** combine payout ratio with a **loss/marginal-profitability flag** and a **covenant-proximity proxy** (interest cover, net debt/EBITDA — both already in the reader's engine). The evidence says the loss flag is the dominant term.

## 2.3 M&A

**Access reality first.** Agrawal/Jaffe/Mandelker (1992), Loughran/Vijh (1997), Rau/Vermaelen (1998) and the *JFE* version of Moeller/Schlingemann/Stulz (2004) are **all closed access with no open copy** (Unpaywall by DOI). **No effect size is reported for them in this report.**

### 2.3.1 The acquirer underperformance record

**Moeller, Schlingemann & Stulz, [NBER WP 9523](https://www.nber.org/papers/w9523)** (full text retrieved). Sample: **12,023 acquisitions, 1980–2001**. Mean CAR(−1,+1): **all +1.103%**; private targets **+1.496%**; **public targets −1.020%**; subsidiary **+2.003%**. Aggregate acquirer loss **−$218bn**; **−5.9 cents per dollar** spent on public targets; ~**$257bn** of public-target losses; **small firms +$8bn vs. large firms −$226bn**.

**Moeller, Schlingemann & Stulz, [NBER WP 10200](https://www.nber.org/papers/w10200)** (retrieved): in **1998–2001** acquirers "lost **12 cents** … for every dollar spent … total loss of **$240 billion**", vs. **$7bn / 1.6 cents** in the 1980s; bidder losses exceeded target gains by **$134bn**.

**Long-run results are method-dependent *inside a single paper*:** calendar-time alpha **−0.041%/month, insignificant**, vs. event-time 3-year BHAR "perform poorly." The [NBER Digest](https://www.nber.org/digest/oct04/w9523.html) (retrieved) reports the small-firm acquisition announcement return as "**1.55 percent higher**" than comparable large-firm deals.

**King, Dalton, Daily & Covin (2004), *SMJ* 25(2):187–200** — abstract: acquirer performance "does not positively change as a function of their acquisition activity."

### 2.3.2 The free-cash-flow / empire-building hypothesis — weaker than commonly assumed

**Jensen (1986), *AER* 76(2):323–329** — full text retrieved: this is **pure theory with no effect sizes**. The critical empirical caveat: in the 12,023-deal MSS sample the **Lang/Stulz/Walkling free-cash-flow measure (cash flow × q<1) is NOT significant**; only the low-q × cash interaction appears, at **−0.87%**. **UNVERIFIED:** Lang/Stulz/Walkling (1991) and Harford (1999).

### 2.3.3 Acquisition intensity

Covered in 1.5 via Titman, Wei & Xie (2004): capital-investment spread **+0.168%/month**, 5-year cumulative **+8.10% (t = 2.55)**, but **fails in the 1984–89 takeover regime**. **UNVERIFIED:** any acquisition-*specific* intensity paper (as distinct from capex intensity).

### 2.3.4 Goodwill and impairment — the best XBRL-native M&A marker

**The claim "goodwill-to-assets predicts lower future returns" is NOT VERIFIED.** Liu, Yin & Zheng (*Journal of Financial Markets* 52:100561) is closed access with a 404 conference copy. **Do not cite it.**

**What is verified:**
- **Gu & Lev (2011), *The Accounting Review***: overpriced shares are the "root cause of many goodwill write-offs."
- **Li, Shroff, Venkataraman & Zhang (2011), *RAST***: impairment **precedes** profitability decline and analyst downgrades.
- **Hayn & Hughes (2006)**: impairments "lag behind the economic impairment by an average of **three to four years**", up to **ten years** for one-third of cases.

**Screen implication:** goodwill plus impairment history is one of the **two best XBRL-native markers** (with payout coverage). A rising goodwill/assets ratio financed by equity issuance is the classic serial-acquirer value-destruction signature; the impairment that follows arrives 3–4 years late, so the ratio is the *leading* indicator.

**XBRL:** `us-gaap:Goodwill`, `us-gaap:GoodwillImpairmentLoss`, `us-gaap:AssetImpairmentCharges`, `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`, `us-gaap:BusinessCombinationConsiderationTransferred1`, `us-gaap:IntangibleAssetsNetExcludingGoodwill`.

### 2.3.5 Serial acquirers — both sides

**For (they can be skilled).** Fuller, Netter & Stegemoller (2002), *JF* 57(4):1763–1793: bidders **gain** on private/subsidiary targets and **lose** on public targets. L.E.K. Consulting (full PDF retrieved): 5,400+ U.S. public companies, 2016–2025, TSR — serial acquirers (≥1 deal/yr for 3 consecutive years; only **8%** of companies) "outperformed … occasionally by more than **11%** and organic-only companies by more than **14%**." **But this is TSR, not alpha**, and L.E.K. itself concedes possible reverse causality.

**Against.** King et al. (2004); the declining-CAR-within-programme stylised fact is corroborated by five independent papers per Aktas, de Bodt & Roll (2011), *JCF*, 568–630 deals, 1992–2007 — whose own bid reaction is **−4.27%** and premium **−12%** to a 1-SD prior CAR decline, but whose raw CARs are **−1.10% vs. −0.12% with p = 0.24 (NOT significant)**.

**XBRL caveat:** deal-count screens are **materiality-biased toward large acquirers** — exactly where Moeller et al. find the destruction.

## 2.4 Reinvestment vs. returning cash — the capital-discipline evidence

See 1.5 for the ROIC × reinvestment framing. The capital-discipline numbers:
- **McKinsey, "The strategic yardstick"** (*McKinsey on Finance* No. 49, Winter 2014): 2,875 large non-financials, 2007–11 — top economic-profit quintile **+$677bn**, middle three **+$29.4bn**, bottom **−$411bn**; **~half of top-quintile firms drop out within 10 years, and only 11% of middle-quintile firms reach the top.** **UNVERIFIED** (not retrieved directly).
- **McKinsey *MoF* No. 86 (July 2024), n = 617 executives:** an influential FP&A/strategy leader → **1.8× revenue-growth and 1.9× return-on-capital outperformance** — self-reported, no causality.
- **Morgan Stanley (5 Nov 2025):** the valuation quotient averaged **10% over 1970–2024**; only **38 of 5,760 observations** exceeded the optimal reallocation threshold. **UNVERIFIED** (delegated).

**No paper titled "Capital allocation and the cross-section of stock returns" appears to exist — do not cite such a title.** No verified return spread for the Morningstar Capital Allocation Rating was found.

**The decisive sign tension, restated:** the verified evidence is that **aggressive reinvestment predicts lower returns** (Titman/Wei/Xie; Cooper/Gulen/Schill), while the value-creation identity says growth is only good above the cost of capital. Reconciling them: **most growth is below the cost of capital**, so the screen should be **high ROIC−WACC with LOW asset growth**, not high reinvestment.

---

# Part 3 — Earnings quality of the business

## 3.1 Earnings stability and volatility

### 3.1.1 Quality Minus Junk (QMJ) — the canonical quality composite

**Definition.** Quality = "characteristics that investors should be willing to pay a higher price for, everything else equal" ([Asness, Frazzini & Pedersen, *Review of Accounting Studies* 2019, 24:34–112](https://link.springer.com/article/10.1007/s11142-018-9470-2)). Variables are ranked and z-scored: `z(x) = (r − μ_r)/σ_r`.

**⚠ Correction:** the commonly quoted **four pillars (profitability, growth, safety, payout)** is the **2013 working-paper** framing. The **published 2019 paper uses THREE pillars** — Profitability, Growth, Safety — with payout relegated to a robustness variant (Table 23) and idiosyncratic volatility dropped from Safety.

- **Profitability** = `z(z_gpoa + z_roe + z_roa + z_cfoa + z_gmar + z_acc)`; **ACC = −(ΔWC − DP)/AT**; `WC = ACT − LCT − CHE + DLC + TXP`.
- **Growth** = `z(z_Δgpoa + z_Δroe + z_Δroa + z_Δcfoa + z_Δgmar)` — **five-year** growth, computed **per share** to neutralize issuance.
- **Safety** = `z(z_bab + z_lev + z_o + z_z + z_evol)`; **bab** = −beta (Frazzini–Pedersen); **z** = Altman Z; **o** = Ohlson O; **evol** = **standard deviation of quarterly ROE over up to 60 quarters (min 12)**.

**Sample.** **54,616 stocks, 24 developed markets, June 1957 – December 2016.** *Internal inconsistency to footnote:* Table 4's global column header reads "7/1998 – 12/2016" while the text and figure captions say June 1989.

**Reported effect sizes** (monthly %, t in brackets; Table 4):

| | US Long Sample | Global Broad Sample |
|---|---|---|
| Excess return | **0.29** (3.62) | **0.38** (3.33) |
| CAPM alpha | **0.39** (5.43) | **0.51** (5.76) |
| 3-factor alpha | **0.51** (8.90) | **0.61** (8.75) |
| 4-factor alpha | **0.60** (9.95) | **0.61** (8.07) |
| Sharpe | 0.47 | 0.64 |
| Information ratio | 1.40 | 1.70 |

Also: positive in **23 of 24 countries** (exception New Zealand); 4-factor alphas significant in **18 of 24**; five-year cumulative 4-factor alpha **20.85% (US) / 22.04% (global)**. **Quality is persistent:** the P10-minus-P1 score spread is **3.07** at formation and still **1.31** at t+120 months.

**Out-of-sample.** The design is itself out-of-sample across 24 countries and ~60 years, which is why this is **(a)**. AQR publishes a live [Quality Minus Junk Factors Monthly](https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Monthly) dataset; **post-2016 performance was not verified — UNVERIFIED**. The authors' own hedge: the returns "must be either an anomaly, data mining … or a still-to-be-identified risk factor."

**Caveats.** Financials distort GPOA/CFOA; **ACC and EVOL require long histories (EVOL up to 60 quarters) and so exclude young firms** — biasing against precisely the high-growth names a compounder screen cares about; the score is a within-industry, within-size *relative* ranking; component weights are equal and unestimated.

**XBRL computability.** Largely computable. Verified live: `us-gaap:Revenues`, `us-gaap:GrossProfit`, `us-gaap:AccountsReceivableNetCurrent`, `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:InventoryNet`, `dei:EntityCommonStockSharesOutstanding`. **Beta/BAB is not an accounting variable** — needs daily returns. **Share counts must be split-adjusted** or equity issuance is meaningless.

### 3.1.2 Low-volatility / idiosyncratic volatility

**Origin.** Ang, Hodrick, Xing & Zhang, NBER WP 10852 (Oct 2004), *JF* 61(1):259–299 (2006). IVOL = standard deviation of the residual from a FF-3 regression on daily returns.

**Effect sizes** (from the WP full text): IVOL quintile **5−1 = −1.06%/month**; **FF-3 alpha −1.31%/month, t = −7.00**; quintile 5 total return **−0.02%/month**. Robustness: NYSE-only −0.66% (t = −4.85); 1980s **−2.23%**, 1970s −0.77%; NBER expansions −1.25%, recessions −1.79%. **The highest-IVOL quintile is only 1.9% of market capitalisation** — a critical capacity caveat.

**Out-of-sample: genuinely contested.** Fu, Fangjian (2009), *JFE* 91(1):24–37 ([RePEc](https://ideas.repec.org/a/eee/jfinec/v91y2009i1p24-37.html)) finds the **opposite** sign using exponential-GARCH *expected* idiosyncratic volatilities, and concludes "Ang et al.'s findings are **largely explained by the return reversal of a subset of small stocks** with high idiosyncratic volatilities." **Status: (c) contested.** The realised sort is real and large; the interpretation is not settled. **Not XBRL-computable.**

### 3.1.3 Earnings volatility → distress

**Campbell, Hilscher & Szilagyi (2008)**, "In Search of Distress Risk," *JF* 63(6):2899–2939, [NBER w12362](https://www.nber.org/papers/w12362). Sample: US **1963–2003**; **1,695,036 firm-months**; **1,614 failures** (797 bankruptcies).

**Effect sizes** (best logit; coefficient with |z|): NIMTAAVG **−29.672** (23.37); TLMTA **+3.36** (27.80); EXRETAVG **−7.35** (14.03); **SIGMA +1.482 (13.54)** — higher equity volatility raises failure probability; RSIZE +0.082 (2.62); CASHMTA **−2.401** (8.64); MB +0.054 (4.87); PRICE −0.937 (14.77). Pseudo-R² 0.312 in-sample; out-of-sample **0.310 (contemporaneous), 0.108 (12-month), 0.039 (36-month)** — the model predicts *incidence*, not *timing*.

**The return result that matters most.** Distressed stocks earn **anomalously LOW** returns: annualised mean excess return in the highest fitted-probability bucket **−16.30% (t = 1.98)**. Long safe minus distressed: mean excess **+10.20%**, CAPM alpha **+12.60%**, **FF-3 alpha +22.89% (t = 6.15)**, 4-factor **+12.18% (3.45)**. Distressed stocks have *higher* betas and value loadings. **Status: (b), and HXZ list "the distress anomaly" among replication failures.** The accounting-only parts are computable; SIGMA and EXRETAVG need returns.

## 3.2 Revenue quality

### 3.2.1 Recurring vs. one-off revenue / ARR — NOT ESTABLISHED

**No peer-reviewed study was found showing that recurring-revenue share, ARR, or subscription mix predicts durability, valuation, or returns.** The nearest anchors: Jegadeesh & Livnat (2006), *JAE* 41(1-2):147–171 (record verified; **abstract and effect sizes UNVERIFIED**); "On the Market Reaction to Revenue and Earnings Surprises," *JBFA* 36(1-2):31–50 (2009) — revenue surprises matter more and earnings surprises less in R&D-intensive firms, so context differs from full-sample studies.

**Verdict: present the recurring-revenue claim as a hypothesis, not a finding.** ARR is a company-defined non-GAAP metric with no standard definition; SaaS "ARR surveys" are vendor marketing. **XBRL:** no dedicated tag; splits live in MD&A or segment tables with filer-defined classification.

### 3.2.2 Customer concentration

Covered in 1.4. Summarising the disagreement: **Patatoukas (2012) finds concentration → higher returns on capital and positive abnormal returns**; **Dhaliwal et al. (2016) find concentration → higher cost of equity**; **Irvine et al. (2016) find the profitability sign flips with relationship maturity**; **Krishnan et al. (2019) find *lower* audit fees but *more* restatements.** These are not contradictions — they are different channels — but they mean **customer concentration is not a clean directional marker** and should be used as a risk flag, not a score. **Not XBRL-computable.**

### 3.2.3 Backlog / RPO

Peer-reviewed papers exist with verified bibliographic records, but **every effect size is UNVERIFIED** (paywalled): Rajgopal, Shevlin & Venkatachalam (2003), *RAST* 8(4):461–492; Chang, Chen, Hsu & Mashruwala (2018), *CAR* 35(2):1140–1165; Banker, Barber, Hollie & Park (2024), *RQFA* 62(4):1733–1753; Barber & Hollie (2021), *Advances in Accounting* 53:100526; Feldman, Govindaraj, Livnat & Suslava (2021), *JAPP* 40:106897; Gilliam, Heflin & Paterson (2024), *RQFA*. **No peer-reviewed evidence on RPO specifically (post-2017) was found.** Treat "RPO predicts revenue/returns" as unproven. **XBRL:** candidate tags `us-gaap:RevenueRemainingPerformanceObligation`, `us-gaap:ContractWithCustomerLiabilityCurrent` — **not verified against a live filing**; in practice RPO is often narrative.

### 3.2.4 DSO as a red flag

**No separately established, robust standalone "DSO anomaly" was retrievable.** DSO appears as **DSRI inside the Beneish M-score** (coefficient 0.920, t = 6.02), in the accruals literature (receivables are an accrual component), and in Hirshleifer, Hou, Teoh & Zhang (2004), who argue "high levels of lingering, unpaid receivables will increase the cumulative accruals component of net operating assets" ([full text](https://r.jina.ai/http://www2.nber.org/conferences/2004/bfs04/hou.pdf)). **Status: (b)/(c)** — useful as a *component*, unproven standalone. **XBRL:** fully computable — `us-gaap:AccountsReceivableNetCurrent` ÷ revenue, at *t* and *t−1*. **Tag-continuity warning (verified live):** Apple's `us-gaap:Revenues` series ends at frame **CY2018Q3**; post-ASC 606 filers migrate to `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`. **Any revenue time series must stitch multiple tags.**

### 3.2.5 Beneish M-score

**Model.** `M = −4.840 + 0.920·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI` (t-stats 6.02, 2.20, 3.20, 5.39, 0.70, −0.71, 3.73, −1.22). Inputs: **DSRI** = YoY receivables/revenue index; **GMI** = prior ÷ current gross margin; **AQI** = `[1−(CA+PPE)/AT]_t ÷ [1−(CA+PPE)/AT]_{t−1}`; **SGI** = sales growth; **DEPI** = depreciation-rate index; **SGAI** = SG&A/sales index; **LVGI** = leverage index; **TATA** = total accruals ÷ total assets.

**Origin.** Beneish, "The Detection of Earnings Manipulation," *FAJ* 55(5):24–36 (1999), DOI 10.2469/faj.v55.n5.2296 (Crossref-verified).

**Sample.** **74 manipulators** (49 SEC AAERs + 25 from a news search requiring an ex-post restatement) and **2,332 SIC-matched non-manipulators, 1982–1992**. Holdout **1989–1992: 24 manipulators + 624 controls.**

**Reported detection rates.** At investor-relevant error-cost ratios **20:1 / 30:1**, the flag threshold is probability > **0.0376**, i.e. **M-score > −1.78**. (The **−2.22 cutoff widely quoted in practitioner sources is UNVERIFIED** in the original.) Estimation sample misclassifies **26% of manipulators and 13.8% of non-manipulators**. **Holdout: 50% of manipulators and 7.2% of non-manipulators.** The model "identifies approximately **half** of the companies involved in earnings manipulation prior to public discovery." **The original paper reports NO trading-strategy return — it is a classification model.**

**Out-of-sample.** Beneish, Lee & Nichols (2013), *FAJ* 69(2):57–82, claim out-of-sample return prediction, but the same volume contains a **formal Comment** (*FAJ* 69(5):14, DOI 10.2469/faj.v69.n5.7) and **Author Response** (DOI 10.2469/faj.v69.n5.8). The stronger competing model is Dechow, Ge, Larson & Sloan (2011), *CAR* 28(1):17–82 — **findings UNVERIFIED**. **Verdict: (b) as a forensic screen; (c) as a return predictor.**

**Caveats.** Estimated on *discovered* manipulators (selection bias, acknowledged by the author); large classification error at investor-relevant cost ratios; two years of annual data required; **detects overstatement only**; acquisitions, strategy shifts and industry shocks trigger the same distortions; AQI/DEPI/SGAI rely on frequently-missing items (the author substitutes a neutral value of 1).

**XBRL.** Fully computable in principle from `us-gaap:AccountsReceivableNetCurrent`, revenue tags, `us-gaap:CostOfRevenue`, `us-gaap:GrossProfit`, `us-gaap:AssetsCurrent`, `us-gaap:LiabilitiesCurrent`, `us-gaap:Assets`, `us-gaap:PropertyPlantAndEquipmentNet`, `us-gaap:DepreciationDepletionAndAmortization`, `us-gaap:SellingGeneralAndAdministrativeExpense`, `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebtCurrent`.

## 3.3 Cyclicality and cycle position

### 3.3.1 The core "peak margin" evidence

**Origin.** Fama & French (2000) — reversion of **~38% per year**, faster below the mean and **faster the further from the mean in either direction** (see 1.2).

**Why the non-linearity is the whole point.** A single linear reversion rate **understates** reversion for extreme-margin firms. The firms a naive quality screen flags as best — the ones at the top of the margin distribution — are the ones whose margins are most strongly expected to revert. This is the mechanical answer to "is peak margin a trap?": **yes, and the trap is worst exactly at the top of the distribution.**

**Corroborating peak-earnings evidence.** Hirshleifer, Hou, Teoh & Zhang (2004), "Do investors overvalue firms with bloated balance sheets?" ([full text](https://r.jina.ai/http://www2.nber.org/conferences/2004/bfs04/hou.pdf)). Sample: NYSE/AMEX/Nasdaq, **July 1964 – December 2002**; ~**1.63 million firm-months**. **NOA** = net operating assets ÷ lagged total assets. Hedge (long lowest NOA decile, short highest), characteristic-matched abnormal returns: **1.24%/month year 1 (t = 10.31)**, 0.83% year 2 (7.66), 0.57% year 3 (5.44); value-weighted **0.69% (5.24), 0.60% (4.34), 0.49% (3.73)**; FF-3 alpha EW **1.34% (t = 11.17)**; **profitable in 35 of 38 years**. **The direct peak-earnings pattern:** the highest-NOA decile has the **best past earnings** (0.117 ROA) and the **poorest future change** (ΔEarnings t+1 = **−0.001** vs. **+0.041** for the lowest decile). **Status: (b) strong single paper, microcap-sensitive.**

### 3.3.2 Operating leverage

**Origin.** Lev (1974), "On the Association Between Operating Leverage and Risk," *JFQA* 9(4):627, DOI 10.2307/2329764 — "other things equal, **higher operating leverage … [is associated with] larger overall systematic risk of stocks**." Novy-Marx (2011), "Operating Leverage," *Review of Finance* 15(1):103–134: an operating-leverage measure "predicts returns in the cross-section" and **explains why the value premium is weak and non-monotonic across industries but strong and monotonic within them**. **UNVERIFIED:** coefficients.

**The caveat that matters.** **Cost stickiness** — asymmetric cost behaviour (Anderson, Banker & Jakinaraman 2003, *JAR* 41(1):47–63) — means costs fall less when sales fall, which **amplifies downside** for high-fixed-cost firms. Irvine et al. (2016) provide the concrete mechanism linking customer-specific investment to higher fixed costs.

**Measurement limit, not a data limit.** The fixed/variable split is **not observable**; PP&E/sales, SG&A/sales and time-series DOL proxies disagree. This is an inherent measurement problem. **XBRL:** `us-gaap:SellingGeneralAndAdministrativeExpense` ÷ `us-gaap:Revenues`; `us-gaap:PropertyPlantAndEquipmentNet` ÷ `us-gaap:Assets`.

### 3.3.3 Value-trap / earnings-illusion evidence

**⚠ Sign warning.** Hirshleifer, Hou & Teoh (2009), "Accruals, cash flows, and aggregate stock returns," *JFE* 91(3):389–406 ([full text](https://r.jina.ai/https://escholarship.org/content/qt9d1148bj/qt9d1148bj.pdf)). Sample: **1965–2005 (41 annual observations)**. Aggregate **ACCRUALS POSITIVELY predict** next-year aggregate returns — **0.068 (t = 3.33)** on CRSPRET; one s.d. of aggregate accruals ⇒ **≈ +7% next-year market return**. Aggregate **CASH FLOWS NEGATIVELY predict** (−0.052, p = 0.006). **This is the OPPOSITE sign to the firm-level accrual anomaly, and the paper explicitly concludes it is "inconsistent with the earnings-fixation hypothesis." Using it as evidence that accruals predict negative returns inverts its stated result.** Status: **(b) single paper, (c) contested across aggregation levels.**

**Extrapolation support.** Alti & Tetlock (2014), *JF* 69(1):325–361 ([full text](https://r.jina.ai/https://business.columbia.edu/sites/default/files-efs/pubfiles/4575/Alti%20Tetlock%20Biased%20Beliefs.pdf)): sample US public firms **1968–2006**, SMM — a model with overconfidence + overextrapolation "closely match[es] empirical data on asset pricing and firm behavior," while models without the biases "fail to match observed return predictability."

**Contrarian evidence.** Lakonishok, Shleifer & Vishny (1994), *JF* 49(5):1541–1578 — abstract verified: value strategies "yield higher returns because these strategies **exploit the suboptimal behavior of the typical investor** and not because these strategies are fundamentally riskier." **UNVERIFIED:** all numbers (scanned image PDF, no text layer).

**"Do high-margin firms underperform?"** — the claim is **not supported**. What *is* established: gross margins *alone* earn H−L **0.02%/month (t = 0.22)**; the profitability premium is contested at the margins (HXZ name "operating profitability" a failure); but **high-quality** firms do outperform risk-adjusted (QMJ). The correct statement is narrower: **margin level is not a quality marker; margin stability and non-reversion are.**

---

# Part 4 — Governance and ownership

## 4.1 Insider ownership and insider buying/selling

### 4.1.1 Insider *trading* — what predicts

**Lakonishok & Lee (2001), "Are Insider Trades Informative?" *RFS* 14(1):79–111** ([NBER WP 6656](https://www.nber.org/papers/w6656)). Firm-level signal: `NPR = (buys − sells)/(buys + sells)` over the prior 6 months; "strong" signals require ≥3 insiders, NPR ≥0.95 (≤−0.95), and dollar volume in the top 25% of the size group. **Sample: all NYSE/AMEX/Nasdaq, 1975–1995.** Abstract (verified): "Insiders in aggregate are contrarian investors. However, they predict market movements better than simple contrarian strategies. … the result … is driven by the insider's ability to predict returns in **smaller firms**." Critically: the informativeness comes **from purchases**, while "**selling appears to have no predictive ability**." Effect sizes (delegated full-text retrieval): extensive purchases outperform extensive sales by **7.8% in year 1**, **2.3% in year 2**, ~0 in year 3; after adjusting for B/M and size the first-year spread falls to **4.8%**; "for large companies, even strong buy signals convey almost no information."

**Jeng, Metrick & Zeckhauser (2003), *Review of Economics and Statistics* 85(2):453–471** ([NBER w6913](https://www.nber.org/papers/w6913)). Sample **1975–1996**. Published: purchases earn **>6%/year** abnormal; **sales earn no significant abnormal returns**; expected cost to non-insiders **~10 cents per $10,000** transaction. The NBER version reports **~40 bps/month**, the Wharton version **>50 bps/month**. **Note the three versions of the same paper report materially different magnitudes — version choice matters when citing.** Small- vs. large-firm abnormal returns are **not** significantly different; top executives do **not** earn higher returns.

**Cohen, Malloy & Pomorski (2012), "Decoding Inside Information," *JF* 67(3):1009–1044** ([NBER w16454](https://www.nber.org/papers/w16454)) — **the most useful refinement.** Classify each insider **ex ante each January** as **routine** (traded in the same calendar month ≥3 consecutive years) or **opportunistic** (everyone else). Sample: Thomson Reuters Form 4, **January 1986 – December 2007**; ~**45% opportunistic / 55% routine**; regression N = 52,444 firm-months. Effect sizes: opportunistic long-short **value-weighted 82 bps/month (≈9.8%/yr), t = 2.15**; **equal-weighted 180 bps/month (≈21.6%/yr), t = 6.07**. Routine long-short **VW −20 bps/month (t = −0.57)**, EW 43 bps (t = 1.73) — "essentially zero." 1 s.d. more opportunistic buys → **+35 bps/month (t = 4.56)**; 1 s.d. more sells → **−29 bps/month (t = 4.97)**. Returns rise for ~6 months then level off **with no reversal**; **over half the improvement comes from opportunistic sells**. **UNVERIFIED:** post-2012 decay; note the sample ends **December 2007** and the VW alpha is marginal at t = 2.15.

**Seyhun — UNVERIFIED.** No Seyhun paper's own text or abstract with numbers was retrievable; the [JFE 1986 record](https://ideas.repec.org/a/eee/jfinec/v16y1986i2p189-212.html) states "No abstract is available." **Do not cite a Seyhun number.**

### 4.1.2 Insider *ownership* level — hump-shaped, not monotonic

**Morck, Shleifer & Vishny (1988), *JFE* 20:293–315** ([NBER WP 2055 full text](https://dash.harvard.edu/server/api/core/bitstreams/7312037e-08f4-6bd4-e053-0100007fdf3b/content)). **Sample: 371 of the Fortune 500, 1980**; mean board stake **10.6%**, median **3.4%**. **The paper's own cutoffs are 0/5/20% — not the popular 5/25%.** Table 2 with controls: 0–5% **+0.201*** **; 5–20% **+0.286*** **; >20% **+0.156** ** (but t vs. the 5–20% bucket is only **1.61, not significant**). Robustness text: "there is **no support for an increase in Q as ownership rises from 7.5% to 20%**"; a "significant decline in Q as board ownership increases from somewhere between **15–20% to about 25%**"; "the decline seems essentially complete when board ownership reaches **25%**." Officer holdings are **not** reliably related to Q; outside-board holdings show the hump. The authors' own linear replication reproduces Demsetz & Lehn's (1985) null — the nonlinearity does all the work.

**Answer to the question posed:** on the retrieved evidence, **insider *trading* (specifically opportunistic purchases) is the better-specified predictor**; **insider *ownership* level has an estimated optimum around 5–20% with entrenchment emerging between ~15–20% and ~25%.** Status: **(b) single 1980 cross-section.**

**Both are NOT XBRL-computable.** Insider trades: **SEC Forms 3/4/5** (Section 16(a)). Ownership: **DEF 14A** beneficial-ownership tables and **Schedule 13D/13G**.

## 4.2 Governance indices, controlling shareholders, dual-class

### 4.2.1 The governance-and-returns relation **failed out of sample** — the most important governance finding

**Origin.** Gompers, Ishii & Metrick (2003), *QJE* 118(1):107–155 ([NBER w8449](https://www.nber.org/papers/w8449)). **G-Index = count of 24 provisions** weakening shareholder rights. Sample ~**1,500 firms/year, 1990–1999**; **dual-class firms excluded**. Legendary results: long lowest-G / short highest-G earned **8.5%/year abnormal**; a one-point higher index → **2.4 pp lower Tobin's Q in 1990**, rising to **8.9 pp lower by 1999**.

**The debunking, from two independent teams:**

**Core, Guay & Rusticus (2006), "Does Weak Governance Cause Weak Stock Returns?" *JF* 61(2):655–687** ([full WP PDF](https://users.nber.org/~confer/2004/si2004/cg/core.pdf)). Sample: **9,917 firm-years, 1991–1999**. **The governance–performance relation is real:** G-index on industry-adjusted ROA **−0.10 (t = −5.53)**; Dictatorship vs. Democracy **−0.52 (t = −2.99)**. **But the market was not surprised:** analyst forecast errors show the *opposite* sign to the mispricing hypothesis (**+0.01, t = 2.07**). **Returns reverse:** 1990–1999 Democracy **23.3%** vs. Dictatorship **14.1%** (+9.2%); **2000–2002 −14.1% vs. −2.1% (−12.0%)**. Four-factor hedge intercepts: **0.71%/month (t = 2.73)** original; **−0.05 (t = −0.08) for 2000–2002**. Results are "**sensitive to the exclusion of technology firms**." Conclusion: "Our results **do not support the hypothesis that weak governance causes poor stock returns.**"

**Bebchuk, Cohen & Wang (2013), *JFE* 108(2):323–348** ([NBER w15912](https://www.nber.org/papers/w15912); [Harvard corpgov summary](https://corpgov.law.harvard.edu/2012/04/17/learning-and-the-disappearing-association-between-governance-and-returns/)). Re-running GIM's exact methods, the G-Index and E-Index "were no longer associated with abnormal returns during the period of **2000–2008, or any sub-periods within it**." Mechanism: attention to governance "exploded in the beginning of the 2000s"; until ~2000, but not after, good-governance firms had more positive earnings-announcement reactions. **Crucially: "the negative association with Tobin's Q persists."**

**Verdict: (c) debunked.** **For the reader's system: governance indices are a *quality/fundamentals* marker, not a return signal. A high G-index predicts lower Q and worse operating performance, but has not predicted returns since 1999.**

### 4.2.2 Dual-class structures — contested

**For the incentive view.** Gompers, Ishii & Metrick, "Extreme Governance," *RFS* 23(3):1051–1084 ([NBER w10240](https://www.nber.org/papers/w10240)). Insiders hold a mean **26.7% of cash-flow rights but 50.7% of voting rights**. Firm value is **positive and concave in cash-flow rights, negative and convex in voting rights**, rising until insider cash-flow ownership reaches **~33%**. Median debt/assets **0.21 (dual-class) vs. 0.09 (single-class)**. Dual-class firms raise capital less, invest less, grow more slowly, and carry lower valuations.

**Against.** Masulis, Wang & Xie (2009), *JF* 64(4) ([HLS Forum summary](https://corpgov.law.harvard.edu/2008/12/29/agency-problems-at-dual-class-companies/)). US dual-class, **1994–2002**: the marginal value of cash **decreases** in the voting–cash-flow divergence; **excess CEO pay is significantly higher** where the wedge is wider; acquirers with wider wedges have lower announcement returns and are **less likely** to withdraw value-destroying deals. **Exact coefficients NOT retrieved — UNVERIFIED at effect-size level.**

**UNVERIFIED entirely:** Bebchuk/Grinstein dual-class evidence; Chemmanur & Jiao.

### 4.2.3 Tunneling and minority expropriation

**Johnson, La Porta, Lopez-de-Silanes & Shleifer (2000), "Tunneling," *AER* 90(2):22–27** ([NBER w7523](https://wwwtest.nber.org/papers/w7523)) — **conceptual/legal paper, case studies of duty-of-care and duty-of-loyalty doctrines in France, Belgium and Italy. NO statistical magnitudes.** Its contribution is the definition: "the transfer of assets and profits out of firms for the benefit of their controlling shareholders." **Any percentage attributed to this paper is a mis-citation.**

**The paper to cite for a magnitude:** Bertrand, Mehta & Mullainathan (2002), "Ferreting Out Tunneling," *QJE* 117(1):121–148 ([WP PDF](https://www.nber.org/system/files/working_papers/w7952/w7952.pdf)). Method: trace propagation of industry performance shocks through the ownership pyramid. Sample: **Indian firms, 1989–1999**; average group ~**15 firms**. Magnitude: "group firms are on average only **70% sensitive to their shock**, while … group firms at the top of their pyramid are completely sensitive" — roughly **30% of a marginal shock leaks out** of the average group firm, concentrated in lower-pyramid, low-cash-flow-rights firms ("Own Shock × Group" coefficient **0.26**). **Status: (b) single study, no independent replication retrieved.**

## 4.3 Board independence, audit quality, auditor tenure, non-audit fees

### 4.3.1 Board independence — a robust null at the board level

**Bhagat & Black (2002), *Journal of Corporation Law* 27(2):231–274** ([record](https://api.openalex.org/works?search=Non-Correlation%20Between%20Board%20Independence%20and%20Long-Term%20Firm%20Performance&per-page=5)). Sample: the **934 largest US firms, 1985–1995**. Firms with more independent directors "**do not perform better than other firms**"; "**low-profitability firms increase their board independence**"; conclusion: there is **"no strategy … works."** **UNVERIFIED:** coefficients.

**Meta-analytic corroboration.** Dalton, Daily, Ellstrand & Johnson (1998), *SMJ* 19(3):269–290 ([record](https://api.openalex.org/works?filter=title.search:Meta-analytic%20reviews%20of%20board%20composition%20leadership%20structure%20and%20financial%20performance&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). **54 studies of board composition (159 samples, n = 40,160)** and 31 studies of leadership structure. Verbatim: "**neither board composition nor leadership structure has been consistently linked to firm financial performance.**" **Pooled effect size: UNVERIFIED. Verdict: (a) robust replicated null.**

**But audit-committee-level independence DOES bite.** Klein (2002), *JAE* 33(3):375–400 ([full WP text](https://r.jina.ai/http://archive.nyu.edu/bitstream/2451/27450/2/SSRN-id246674.pdf)). Sample: **687 firms — the S&P 500 as of 31 March 1992 and 1993**. Absolute Jones discretionary accruals, ML (χ² in brackets): majority-outside board **−0.15 (1.23), NOT significant**; % outside directors 0.34 (0.82), NOT significant; **audit committee majority-independent −0.39 (5.60), p<.05**; audit committee **100% independent 0.04 (0.10), NOT significant**; CEO on the compensation committee **+0.38 (3.01)**; CEO shareholdings **+4.22 (6.04)**. **The relation is non-linear — it appears only where the audit committee is *less than* majority independent.** The stricter "100% independent" standard does nothing.

**Fraud evidence.** Beasley (1996), *TAR* 71(4):443–465 ([record](https://api.openalex.org/works?filter=title.search=An%20empirical%20analysis%20of%20the%20relation%20between%20the%20board%20of%20director%20composition%20and%20financial%20statement%20fraud&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). **75 fraud firms and 75 matched no-fraud firms**: no-fraud firms have **significantly higher percentages of outside directors**. **Surprisingly, the presence of an audit committee does NOT significantly affect fraud likelihood.** Abbott, Parker & Peters (2004), *AJPT* 23(1):69–87: **88 restatements without fraud allegations, 1991–1999** — audit committee **independence**, **activity level** and **at least one financial expert** each show a **significant negative association** with restatement. **Counterweight:** DeFond & Francis (2005), *AJPT* 24(Supplement):5–30 — demonstrated audit failures "approach an annual rate of close to zero," and many SOX "solutions" "may well have serious unintended negative consequences."

### 4.3.2 Auditor tenure — contested, and the contest is methodological

**Longer tenure is worse:** Carey & Simnett (2006), *TAR* 81(3):653–676 (Australia; partner tenure) — long-tenure partners **less likely to issue a going-concern opinion**, but **NO association** with abnormal working-capital accruals. Davis, Soo & Trompeter (2009), *CAR* 26(2):517–548 ([record](https://stars.library.ucf.edu/facultybib2000/1457)) — **both short AND long tenure** firms are more likely to use discretionary accruals to meet/beat forecasts (**U-shape**), but **the positive relation exists pre-SOX and is ABSENT post-SOX**.

**Longer tenure is fine or better:** Johnson, Khurana & Reynolds (2002), *CAR* 19(4):637–660 — "Short tenures (3 years) are associated with **lower-quality** financial reports"; "**no evidence of reduced … quality for longer [9+] audit-firm tenures**." Myers, Myers & Omer (2003), *TAR* 78(3):779–799 — "generally suggest **higher** earnings quality with **longer** auditor tenure." Geiger & Raghunandan (2002), *AJPT* 21(1):67–78 — companies entering bankruptcy **1996–1998** show **significantly MORE audit reporting failures in EARLIER years** of the relationship; explicitly **does not support** mandatory rotation.

**Synthesis.** **Short tenure is bad on essentially every measure.** Whether *long* tenure is bad depends on measure and country. **Verdict: (c) contested.**

### 4.3.3 Mandatory audit firm rotation — no demonstrated benefit, demonstrated costs

**US GAO-04-216 (21 Nov 2003)**, mandated by SOX §207 ([full PDF](https://r.jina.ai/https://www.gao.gov/assets/gao-04-216.pdf)). Average auditor-of-record tenure **≈22 years** for Fortune 1000 companies; **~79%** believe changing firms **increases early-year audit-failure risk**; **~85% of Tier-1 firms, 92% of Fortune 1000 companies and 89% of their audit-committee chairs believed costs would exceed benefits**. First-year cost estimates: aggregate **+43% to +128%**. **~59% of Tier-1 firms said they would likely move their most knowledgeable staff off the engagement as tenure approached**, which they acknowledged raises audit-failure risk. GAO conclusion: mandatory rotation "**may not be the most efficient way**" to strengthen audit quality; benefits are "harder to predict and quantify, though GAO is **fairly certain that there will be additional costs**."

**EU Regulation (EU) No 537/2014** ([EUR-Lex](https://r.jina.ai/https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32014R0537)). **Article 17:** maximum engagement duration **10 years**, extendable to **20** with public tender or **24** with joint audit; **key audit partners rotate after seven years**. Recital (21) justifies the mandate by the "**familiarity threat**" — **not** by demonstrated audit-quality failure.

**The Italian natural experiment.** Cameran, Francis, Marra & Pettinicchio, *AJPT* 34(1):1–24 ([record](https://api.openalex.org/works?filter=title.search=Are%20there%20adverse%20consequences%20of%20mandatory%20auditor%20rotation%20Italian&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). Italy has had mandatory rotation **since 1975** — the only mature regime. Outgoing auditors **do not shirk**, but **final-year fees are 7 percent higher**; **incoming auditors are discounted 16 percent** despite **abnormally high first-year engagement hours (17 percent)** — "suggestive of lowballing." **Decisive: "audit quality of audited earnings is lower in the first three years following rotation."** Conclusion: the evidence "**does not support** the case for mandatory auditor rotation." **Bottom line: (c) contested policy.**

### 4.3.4 Non-audit fees — the weakest famous result in accounting

**Frankel, Johnson & Nelson (2002), *TAR* 77(Supplement):71–105**, DOI 10.2308/accr.2002.77.s-1.71. Abstract verified verbatim: "**nonaudit fees are positively associated with small earnings surprises and the magnitude of discretionary accruals**, while audit fees are negatively associated with these earnings management indicators. We also find a **negative association between nonaudit fees and share values** on the date the fees were disclosed, although the effect is small in economic terms." **Sample (N, year, screens) and all coefficients: UNVERIFIED.** **Do not print a coefficient for FJN.**

**Replications — both sides.**
- **Ashbaugh, LaFond & Mayhew (2003), *TAR* 78(3):611–639.** "This paper **challenges the findings of Frankel et al. (2002)**": results differ once current discretionary accruals are adjusted for firm performance; "**in contrast to FJN, we find no statistically significant association between firms meeting analyst forecasts and auditor fees**"; "**FJN's results are sensitive to research design choices**, and we find **no systematic evidence supporting their claim that auditors violate their independence**."
- **Larcker & Richardson (2004), *JAR* 42(3):625–658** — the most damaging quantitative replication. "Using our pooled sample, we find that the ratio of total fees to [auditor revenue] has a positive relation with the absolute value of accruals, similar to Frankel, Johnson, and Nelson." **"However, using latent class mixture models …, this association only occurs for about 8.5% of the sample."** In contrast, the **level** of fees shows a consistent **negative** relation with |accruals|, strongest for **firms with weak governance**. "Overall, our results are most consistent with auditor behavior being constrained by **reputation effects**."
- **Chung & Kallapur (2003), *TAR* 78(4):931–955.** **1,871 clients of Big 5 firms**: "We do not find a statistically significant association between [Jones abnormal accruals] and any [client] importance measures."

**Verdict: (c) contested / partially debunked.** **Caveat:** fee data are **post-SOX censored** (SOX §201 and EU Art. 5 prohibit many non-audit services), so post-2002 variation is a different economic object. **Not XBRL** — DEF 14A "Principal Accountant Fees and Services."

## 4.4 Executive pay structure and incentives

### 4.4.1 Jensen & Murphy (1990) — fully verified, and routinely misquoted

**Origin.** *JPE* 98(2):225–264, DOI 10.1086/261677 ([full text](https://r.jina.ai/http://faculty.ndhu.edu.tw/~sywang/a7.pdf)). **Sample: all 2,213 CEOs in the *Forbes* Executive Compensation Surveys 1974–1986, 1,295 corporations, 10,400 CEO-years**; final estimation sample **7,750 yearly first differences**.

**Effect sizes:** all-inclusive pay–performance sensitivity **$3.25 per $1,000**; cash comp contemporaneous **1.35¢ per $1,000 (t = 8.0)**; total pay incl. options **3.3¢ per $1,000**; option-portfolio value change **15¢**; dismissal-related wealth change **30¢**; **median CEO stock ownership 0.25% → stock wealth changes $2.50 per $1,000**. By firm size: **large firms $1.85; small firms $8.05**. **1934–38 top-quartile NYSE: 17.5¢ vs. 1974–86: 1.9¢ — a factor-of-ten decline.** Median CEO ownership in the largest 120 firms: **0.30% (1938) → 0.05% (1974) → 0.03% (1984)**.

**⚠ The "$3.25" is routinely misused.** It is an **upper-bound, all-inclusive** number that **includes the value of stock the CEO already owns** ($2.50 of the $3.25). The **compensation-contract** component is only about **$0.75 per $1,000**. The authors' own reading: the relation "is **small for an occupation in which incentive pay is expected to play an important role**"; their hypothesis is **implicit regulation**. **Status: (a) robust.**

### 4.4.2 Equity pay → earnings management — the strongest pay marker

**Bergstresser & Philippon (2006), *JFE* 80(3):511–529** ([full WP text](https://r.jina.ai/http://archive.nyu.edu/bitstream/2451/26408/2/FIN-05-007.pdf)). Constructs: `ONEPCT = 0.01 × PRICE × (SHARES + OPTIONS)`; `INCENTIVE_RATIO = ONEPCT/(ONEPCT + Salary + Bonus)`. Sample: **4,671 observations below $1bn assets; 4,199 above**; option-exercise data 1993–2000.

**Effect sizes:** a **1 percentage-point increase in INCENTIVE_RATIO → an 11 basis-point increase in |accruals|/assets**; moving from the **25th percentile (8.3%) to the 75th (34.5%)** implies a **300 bp increase** in |accruals| without controls and **200 bp** with controls. Table 2a coefficient: **0.1164 (SE 0.0398)**; 0.0768 (0.0287); 0.0743 (0.0280); 0.1038 (0.0657) for cash-flow-statement accruals. Insider trading around high-accrual periods (top 10%): CEO option exercise **+3.82 bp** of firm equity market value (no controls); **1.74 with SE 1.05 — NOT significant** with B/M dummies; **gross CEO share sales +19 bp**, **+14.7 bp** with full controls. Robust across Jones discretionary accruals, Hribar–Collins cash-flow accruals, and Core–Guay option deltas. **Status: (a) robust.**

**Effect sizes UNVERIFIED:** Burns & Kedia (2006), *JFE* 79(1):35–67; Efendi, Srivastava & Swanson (2007), *JFE* 85(3):667–708. Only a secondary directional statement is sourced: "earnings restatements are more common at firms where CEOs have larger options portfolios."

### 4.4.3 Managerial power vs. optimal contracting

**Bebchuk & Fried (2003), "Executive Compensation as an Agency Problem," *JEP* 17(3):71–92** ([AEA](https://www.aeaweb.org/articles?id=10.1257/089533003769204362)): "the design of compensation arrangements is **also partly a product of this same agency problem**." The optimal-contracting position is grounded indirectly via Jensen & Murphy (1990). **UNVERIFIED:** a dedicated optimal-contracting rebuttal with its own numbers; any say-on-pay evidence.

### 4.4.4 Inside debt

**Sundaram & Yermack (2007), *JF* 62(4):1551–1588** ([record](https://api.openalex.org/works?filter=title.search:Pay%20me%20later%20inside%20debt%20managerial%20compensation&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). **Sample: 237 large-capitalisation firms.** "Annual increases in pension entitlements represent about **10% of overall compensation**, **13% for CEOs aged 61–65**"; "CEOs with high inside debt incentives **manage their firms conservatively**." **Status: (b).**

## 4.5 Restatements and enforcement actions

### 4.5.1 Palmrose, Richardson & Scholz (2004) — **the effect size is UNVERIFIED**

*JAE* 37(1):59–89, DOI 10.1016/j.jacceco.2003.06.003 ([EconPapers record](https://econpapers.repec.org/article/eeejaecon/v_3a37_3ay_3a2004_3ai_3a1_3ap_3a59-89.htm) — confirms authors/journal/volume/pages, **carries no abstract text**). **⚠ Missing: the mean and median three-day market reaction, the sample period and N, and the cross-sectional determinants.** **In particular, the widely circulated "≈ −9% three-day reaction" is UNVERIFIED — no primary text stating it could be retrieved. Do not print −9% for Palmrose et al.**

**Verified substitutes (labelled as substitutes):**
- **Hennes, Leone & Miller (2008), *TAR* 83(6):1487–1519** ([record](https://api.openalex.org/works?filter=title.search:The%20importance%20of%20distinguishing%20errors%20from%20irregularities%20in%20restatement%20research&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). **Irregularities** = intentional misstatements; **errors** = unintentional. Effect sizes: the market reaction for the **irregularity sample is −14 percent** versus **−2 percent** for the **error sample**; "most [restatements] we classify as irregularities are followed by fraud-related class action lawsuits (compared to only one lawsuit in the group … classified as errors)." **Sample counts: UNVERIFIED. Status: (a) robust and now standard practice.**
- **US Treasury press release HP-914 (9 Apr 2008)** ([home.treasury.gov](https://home.treasury.gov/news/press-releases/hp914)), on the Treasury-commissioned study by Prof. Susan Scholz: restatements grew **nearly eighteen-fold, from 90 (1997) to 1,577 (2006)**, accelerating in **2001 — before SOX**; **fraud was a factor in 29% of 1997 restatements but only 2% of 2006 restatements**; revenue-related restatements fell from 41% to 11%; "**Market reactions to the restatements dampened over the decade**"; "more than half of restating companies reported a net loss" the year before.
- A secondary literature review ([JKU Linz thesis, D. Maier, March 2017](https://r.jina.ai/https://epub.jku.at/obvulihs/content/titleinfo/1960097/full.pdf)) reports studies from the GAO database measuring "negative Überrenditen von **5,40% bis 11,20%**" (**5.40% to 11.20%**).

**Verdict:** the negative average short-window reaction is **(a) robust in sign** but **(c) sharply decaying and composition-dependent**.

### 4.5.2 Karpoff, Lee & Martin (2008) — enforcement is not the binding cost

*JFQA* 43(3):581–611 ([record](https://api.openalex.org/works?filter=title.search:The%20Cost%20to%20Firms%20of%20Cooking%20the%20Books&select=id,doi,title,publication_year,open_access,best_oa_location,cited_by_count,biblio,abstract_inverted_index&per-page=1)). **Sample: 585 firms targeted by SEC enforcement for financial misrepresentation, 1978–2002**, tracked through 15 Nov 2005. **Legal penalties average only $23.5 million per firm.** The **reputational penalty** is **"over 7.5 times the sum of all penalties."** "For each dollar that a firm misleadingly inflates its market value, on average, it loses this dollar when its misconduct is revealed, **plus an additional $3.08. Of this additional loss, $0.36 is due to expected legal penalties and $2.71 is due to lost reputation.**" **Status: (a) robust.** Caveats: point estimates of expected losses; selected on **detected** enforcement.

### 4.5.3 The "restatement anomaly" / post-restatement drift — does not replicate

**Kravet & Shevlin (2010), *RAST* 15(2):264–294** ([record](https://econpapers.repec.org/article/sprreaccs/v_3a15_3ay_3a2010_3ai_3a2_3ad_3a10.1007_5fs11142-009-9103-x.htm)): a significant **increase in the loading on a discretionary information-risk factor** after a restatement, hence a higher estimated cost of capital. **Exact loadings: UNVERIFIED.**

**Drift magnitudes (from the secondary review, labelled):** Richardson, Tuna & Wu **−25% at six months** (N = 225); Wu (2002) **−10%** (N = 1,221); Demirkan & Platt **−5.1% at one year**; Bardos, Golec & Harding BHAR **−0.328%, −0.317%, −0.307%** in years 1–3; **Hirschey, Palmrose & Scholz find a slightly negative one-year effect that is statistically insignificant across three models**; **Xu, Jin & Li (2009) use CAR, BHAR and calendar-time approaches and find neither under- nor over-performance one year after**. Germany (Hitz, Ernstberger & Stich, 2005–2009): CAR **−0.50% announcement day, −1.2% three days, −0.40% five days** — an order of magnitude smaller than US reactions.

**Verdict: (c) contested and largely failing to replicate.** When multiple estimation methods are used, the drift **disappears**. **Do not treat "the restatement anomaly" as a replicated, tradable effect.**

### 4.5.4 AAER data as a marker

The SEC publishes numbered Accounting and Auditing Enforcement Releases; the authoritative index is retrievable ([SEC AAER index via proxy](https://r.jina.ai/https://www.sec.gov/enforcement-litigation/accounting-auditing-enforcement-releases); the direct SEC URL returns 403 to automated access). AAER firms are the standard *detected-fraud* sample — Karpoff/Lee/Martin use exactly this population. **Coverage limitations:** (i) **detection bias**; (ii) enforcement intensity is **policy-driven**, so AAER counts are not a constant-detection-probability sample; (iii) AAERs **mix issuers and auditors** and mix fraud with technical violations, so they are **not equivalent** to Hennes/Leone/Miller's "irregularity" construct; (iv) confounded by the **29% → 2%** collapse in fraud-related restatements; (v) **latency** — enforcement lags misconduct, so AAER-dated samples mis-time the event.

---

# Part 5 — XBRL/iXBRL implementability

## 5.1 The infrastructure (verified)

- **SEC EDGAR APIs** ([documentation](https://www.sec.gov/edgar/sec-api-documentation)): `data.sec.gov/api/xbrl/companyconcept/{CIK}/{taxonomy}/{tag}.json`, `companyfacts`, and cross-sectional `frames`. XBRL required since **2009**. **Critically: only facts using a non-custom taxonomy (us-gaap, ifrs-full, dei, srt) *and* applying to the entire filing entity are aggregated.** Bulk: `companyfacts.zip`, `submissions.zip`.
- **SEC Financial Statement Data Sets** ([landing](https://www.sec.gov/dera/data/financial-statement-data-sets); [documentation](https://www.sec.gov/files/financial-statement-data-sets.pdf)), from **15 April 2009**, quarterly ZIPs with **SUB / TAG / NUM / PRE**. Scope is limited to **"numeric data on the primary financial statements"**, not full footnote detail. The **TAG file's `custom`/`version` fields** are the only way to detect filer extensions. The SEC explicitly disclaims accuracy.
- **Practical access note:** `data.sec.gov/api/xbrl/companyconcept/...` returned **HTTP 403 ("Undeclared Automated Tool")** to one subagent, while `www.sec.gov` archived filings were reachable with a browser user agent. **Rate-limit and UA-identify.**

## 5.2 Tag-continuity warning (verified live)

**Apple's `us-gaap:Revenues` series terminates at frame CY2018Q3.** Post-ASC 606 filers migrate to `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax`. **Any revenue-based time series must stitch multiple tags**, and code should read the TAG `version` field to detect custom extensions.

## 5.3 Tags verified with live API responses (Apple Inc., CIK 0000320193)

`us-gaap:Revenues`; `us-gaap:GrossProfit`; `us-gaap:AccountsReceivableNetCurrent`; `us-gaap:NetCashProvidedByUsedInOperatingActivities`; `us-gaap:InventoryNet`; `dei:EntityCommonStockSharesOutstanding`.

## 5.4 Marker-by-marker computability

**Fully computable from XBRL alone:** GP/A, gross margin, asset turnover, accruals (balance-sheet method) and TATA, DSO/DSRI, margin level and level-vs-own-history reversion, Altman Z and Ohlson O *from their accounting terms*, QMJ's profitability pillar, leverage (LEV) and ROE volatility (EVOL), goodwill and impairment, payout coverage, asset growth.

**Partially computable — needs market data:** QMJ Safety (BAB needs daily returns; Z needs market equity), the CHS distress model (SIGMA, EXRETAVG, NIMTAAVG), QMJ size sorts, **every yield/payout-yield marker**, and every return-based claim in this report. Market equity ≈ price × `dei:EntityCommonStockSharesOutstanding` (a cover-page count that is point-in-time and filing-date-stamped).

**Not computable from XBRL at all:**

| Marker | Required non-XBRL source |
|---|---|
| Insider trades, routine vs. opportunistic | **SEC Forms 3/4/5** (Section 16(a)) |
| Insider ownership level; controller stakes | **DEF 14A** beneficial-ownership tables; **Schedule 13D/13G** |
| Board independence, committees, financial expertise | **DEF 14A** |
| Dual-class structure | **DEF 14A**, charter/bylaws, cover-page share-class sorting |
| G-Index / E-Index (24 provisions) | IRRC-era governance data; charters, bylaws, 10-K/10-Q |
| Audit and non-audit fees | **DEF 14A** "Principal Accountant Fees and Services" |
| Executive pay, option portfolios, inside debt | **DEF 14A** Item 402 tables |
| Restatement events | **Form 8-K Item 4.02**, amended filings, SEC **AAER** releases |
| Customer concentration, backlog/RPO, recurring-revenue mix | Narrative footnotes and MD&A |

**Six hard implementation caveats.** (1) **Price is not in XBRL** — every yield needs an external market-cap feed. (2) **Interim cash-flow elements are year-to-date** — difference them, don't sum. (3) **XBRL has a materiality floor**, so deal-count M&A screens are biased toward large acquirers. (4) Structured XBRL only starts **~2009–2011** for large filers — 20-year dividend streaks and pre-2002 repurchase tapes need back-fill. (5) **FCF, invested capital, WACC and idiosyncratic volatility are not tags.** (6) **`PayoutRatio = DPS/EPS` is undefined or sign-flipped for loss-makers** — use `DividendsPaid/CFO` or `/FCF` with explicit negative-denominator handling. Also exclude or dummy financials and utilities throughout.

---

# Recommended shortlist — compounding vs. value trap from accounting data only

The evidence supports a **two-gate design**: gate 1 asks *is this a real business?*; gate 2 asks *is the market's implied durability cheap relative to that?* The markers below are ordered by evidence strength × XBRL implementability.

## Tier 1 — build these first (robust evidence, low implementation cost)

**1. `ROIC − WACC` spread, and above all its *direction of travel* over 5 years.**
This is the master marker, and the Morgan Stanley evidence is explicit that **increases** in ROIC are associated with attractive TSRs and **decreases** with poor TSRs, and that companies which "meaningfully change their ranking" across quintiles "often provide opportunity for outsized returns" ([ROIC and the Investment Process](https://prod-mssip.morganstanley.com/im/en-be/intermediary-investor/insights/consilient-observer/roic-and-the-investment-process.html)). The economic-profit dispersion is extreme: top decile **+$1.1tn**, bottom decile **−$400bn**, middle eight **roughly neutral** ([Measuring the Moat](https://prod-mssip.morganstanley.com/im/en-pt/institutional-investor/insights/consilient-observer/measuring-the-moat.html)). **Value-trap signature:** a positive spread that is *narrowing*, or a spread that exists only because you excluded goodwill.

**2. DuPont decomposition with leverage flagged as the suspect component.**
This is the highest-value item the reader's engine is *missing*, because it is nearly free. The evidence: **leverage is the most persistent DuPont component (0.878) while net margin is among the least persistent**, with asset turnover also highly persistent (0.912) ([UNSW replication of Nissim–Penman](https://unsworks.unsw.edu.au/server/api/core/bitstreams/afbbb47c-154d-4b9b-8c57-0b5ee25480fd/content)). And **asset turnover predicts year-ahead abnormal returns while profit margin does not** ([Soliman 2008](https://www.semanticscholar.org/paper/The-Use-of-Dupont-Analysis-by-Market-Participants-Soliman/63cc1f839ad7056bdfe2ffd7e15ef80eba53add3)). **Value-trap signature:** ROE that looks stable but whose stability comes from the leverage term. Reported profitability is expected to revert; the leverage will persist until it breaks.

**3. Margin and profitability *reversion* against the firm's own history — not margin level.**
Fama & French (2000): profitability reverts at **~38% per year**, and **faster the further it is from the mean in either direction** ([abstract](https://api.openalex.org/works/doi:10.1086/209638?select=id,title,doi,publication_year,cited_by_count,abstract_inverted_index,open_access,locations)). The non-linearity is the mechanism of the peak-margin trap. Reinforced by HHTZ (2004): the highest-NOA decile has the **best past earnings (0.117 ROA) and the worst future change (−0.001 vs. +0.041)** ([full text](https://r.jina.ai/http://www2.nber.org/conferences/2004/bfs04/hou.pdf)). **Value-trap signature:** margins at a historical high that cannot be explained by a structural change (mix, capacity, regulation) — the more extreme, the faster the expected reversion.

**4. Goodwill / assets and impairment history — the best XBRL-native M&A marker.**
Gu & Lev (2011): overpriced shares are the "root cause of many goodwill write-offs." Li et al. (2011): impairment **precedes** profitability decline. Hayn & Hughes (2006): impairments lag the economic impairment by **3–4 years** on average, up to ten for a third of cases. **Value-trap signature:** rising goodwill/assets financed by issuance, with no impairment yet — the recognition is still ahead. Note the explicit negative finding: **"goodwill-to-assets predicts lower future returns" is NOT VERIFIED** and must not be claimed.

**5. Net share-count change (already in the engine) — keep it, and de-emphasise gross buyback yield.**
The evidence favours measuring dilution properly: Boudoukh et al. show **payout yield dominates dividend yield**, with the dividend coefficient collapsing to −0.087 (t = −0.60) when payout is included ([NBER WP 10651](https://www.nber.org/papers/w10651)); and Compustat's own repurchase estimates **misstate shares by ≥10% in 48% of cases** (Banyi, Dyl & Kahle 2008). The folk claim that buybacks are largely offset by stock compensation is **contested** — Lazonick's own paper says buyback volume is "generally a multiple" of option exercises. So the honest metric is the **net share count**, not the gross buyback dollar.

**6. Asset growth and capex intensity — as a *penalty*, not a reward.**
This is the finding most likely to invert a naive screen. Titman, Wei & Xie (2004): the **highest-capex-intensity quintile earns −0.127%/month** ([NBER WP 9951](https://www.nber.org/papers/w9951)); Cooper, Gulen & Schill (2008) find asset growth predicts low returns "even on large capitalization stocks." **Screen as: low asset growth + high ROIC − WACC.** Do **not** reward a high reinvestment rate.

**7. Payout coverage with a loss/marginal-profitability flag.**
DeAngelo, DeAngelo & Skinner (1992): "An annual loss is essentially a necessary condition for dividend reductions" — **50.9% of 167 loss-making NYSE firms 1980–85 cut**. But cut-prediction is not tradable (Gunasekarage et al.: **−2.34%** abnormal over 24 months), so use this as a **red-flag generator, not a strategy.** And a **high dividend yield should be scored negatively, not positively**: Hartzmark & Solomon's "free dividends fallacy" implies total return can be **2–4% lower over the next year**, with a **−0.50** correlation between daily prices and dividend yields ([CFA Institute review](https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4)).

**8. Earnings/margin volatility (QMJ Safety-style) and the QMJ composite.**
QMJ earns a **4-factor alpha of 60 bps/month (t = 9.95)** in the US and **61 bps (t = 8.07)** globally across **24 countries and ~60 years**, and quality is strongly persistent (score spread 3.07 → 1.31 over ten years) ([RAST 2019](https://link.springer.com/article/10.1007/s11142-018-9470-2)). Two implementation notes: the **published paper has three pillars, not four** (payout is a robustness variant), and **EVOL/ACC need long histories and so exclude young firms** — a real limitation for a compounder screen.

## Tier 2 — strong but costlier or weaker

**9. Beneish M-score as a *forensic screen*, never as a return predictor.** Useful as a flag — it identifies "approximately **half**" of manipulators pre-discovery, with a **holdout false-negative rate of 50%** — but it is a classification model with no trading return, and the one paper claiming return prediction drew a **formal Comment and Author Response**.

**10. Insider trading classification (Form 4) — high value, outside XBRL.** Cohen, Malloy & Pomorski's **routine vs. opportunistic** distinction is the most useful insider finding: routine trades are >half of all trades and carry **essentially zero alpha**, while opportunistic portfolios earn **82 bps/month VW (t = 2.15)** ([NBER w16454](https://www.nber.org/papers/w16454)). Note the sample ends 2007 and the VW alpha is marginal — prefer the equal-weighted direction as a signal and treat the magnitude with caution. **Insider ownership level should be scored as a hump (optimum ~5–20%), not monotonically** ([Morck, Shleifer & Vishny](https://dash.harvard.edu/server/api/core/bitstreams/7312037e-08f4-6bd4-e053-0100007fdf3b/content)).

**11. Governance quality as a fundamentals marker — and *only* that.** The G-index/E-index predicted returns **1991–1999 but not 2000–2008 in any subperiod** ([Bebchuk, Cohen & Wang/NBER w15912](https://www.nber.org/papers/w15912)), and Core, Guay & Rusticus report the hedge intercept collapsing to **−0.05%/month (t = −0.08)** for 2000–2002 ([full text](https://users.nber.org/~confer/2004/si2004/cg/core.pdf)). **Meanwhile the association with Tobin's Q and operating performance persisted.** So governance belongs in the quality score, **not** in the expected-return model — and results are "sensitive to the exclusion of technology firms."

**12. Auditor/fee/board markers — treat as low-signal.** Board independence is a **robust null** at the board level (Bhagat & Black; Dalton et al., n = 40,160) but **audit-committee independence bites below a majority-independent threshold** (Klein 2002). Non-audit fees reproduce only in **8.5% of the sample** (Larcker & Richardson). Mandatory rotation has **no verified benefit and verified cost** (GAO; the Italian natural experiment). **Do not build a screen on these.**

## The markers to *not* build on

- **Recurring revenue / ARR** — no peer-reviewed support found. Hypothesis, not finding.
- **Backlog / RPO** — papers exist, **no retrievable effect sizes**.
- **Customer concentration** — two opposite channels; contradictory-direction sign across Patatoukas vs. Dhaliwal; use only as a risk flag.
- **Gross margin level** — earns **0.02%/month (t = 0.22)**. It is a growth exposure, not a quality signal.
- **Post-restatement drift** — does not replicate.
- **"Goodwill-to-assets predicts returns"** — NOT VERIFIED.
- **Buyback *timing skill*** — real (Dittmar & Field) but **not XBRL-computable**; requires actual prices paid.

## The direct answer to the question

**The markers that best separate a durable compounder from a value trap, using only accounting data, are:**

**(1) A wide ROIC − WACC spread that has been *stable or widening* for five or more years, financed without a heavy leverage contribution.** This is the joint answer: ROIC−WACC establishes that value is being created at all (top decile +$1.1tn vs. bottom −$400bn); persistence establishes that it is a moat rather than a cycle (reversion ~38%/yr, faster at extremes); and the DuPont leverage term distinguishes *earned* returns from *borrowed* ones (leverage persistence 0.878 vs. margin persistence among the lowest). **A high, stable ROE whose stability comes from the leverage term is the single most reliable accounting signature of a value trap.**

**(2) Low asset growth paired with that high spread.** The verified evidence is that aggressive reinvestment predicts *lower* returns (−0.127%/month for the top capex-intensity quintile; asset growth predicts low returns even among large caps), so a compounder is a firm that earns high returns on capital and *does not need to grow the balance sheet fast to do it*. A firm reporting high growth and a high ROIC−WACC spread should be scrutinised for whether the growth is being bought — which shows up in **goodwill/assets rising faster than NOPAT**.

**(3) A clean capital-allocation record: net share count flat or falling, payout covered by free cash flow, no large public-target acquisition programme, no rising goodwill.** Byrnes' caveat: this is where the accounting evidence is most decisive on the *negative* side — public-target acquisitions destroy acquirer value (−1.020% announcement CAR; −5.9 cents per dollar; −$218bn aggregate), and losses concentrate in **large** firms (+$8bn small vs. −$226bn large). **A large-cap serial acquirer with rising goodwill is the archetypal accounting-visible value destroyer.**

**(4) Earnings and margin stability, scored against the firm's own history rather than against peers' levels.** Low volatility is the core of QMJ's Safety pillar and part of a composite with a 60 bps/month 4-factor alpha across 24 countries.

**(5) Negative screens for the specific trap signatures:** margin at a historical extreme with no structural explanation; goodwill build-up without impairment; high dividend yield; a loss or marginal profitability alongside a high payout ratio; ROE rising while turnover falls and leverage rises.

**The honest calibration.** McLean & Pontiff (2016) find portfolio returns fall **26 pps** when a study is begun after the original sample ends and **58 pps** after publication, and Hou, Xue & Zhang find **64–85% of 447 anomalies fail** stricter replication. So these markers should be used to **classify and to avoid** — to build a quality ranking and to trigger research — rather than as a stand-alone long-short signal expected to reproduce published alphas. The highest-conviction uses are the **avoidance** decisions (leverage-driven ROE, goodwill bloat, public-target M&A, high-yield traps, peak margins), because on those the evidence is about *mechanism* — mean reversion, dilution, overpayment — rather than about a market-beating spread that may have decayed.

---

## Explicit UNVERIFIED register

**Effect sizes not retrievable — do not print numbers for these:** Sloan (1996) accruals anomaly; Dechow & Dichev (2002) model and coefficients; Altman (1968) accuracy and Type I/II error rates; Ohlson (1980) originals; Zmijewski (1984); Shumway (2001); Bali & Cakici (2008); Stambaugh-Yu-Yuan (2015); AHXZ (2009) international effect sizes; Lev & Nissim (2006); Ball et al. (2016) cash-based operating profitability; Green-Hand-Soliman (2016); **Seyhun returns**; **Palmrose/Richardson/Scholz mean reaction, N and sample period (the −9% figure)**; Hennes/Leone/Miller sample counts; Dechow/Ge/Larson/Sloan AAER sample and F-score; Bhagat & Black coefficients; Dalton et al. pooled effect size; **Frankel/Johnson/Nelson sample and coefficients**; Ashbaugh/LaFond/Mayhew, Chung/Kallapur, Carey/Simnett, Davis/Soo/Trompeter coefficients; Burns & Kedia and Efendi et al. samples and coefficients; GAO-04-216 Appendix V country findings; Weisbach (1988); Rosenstein & Wyatt (1990); QMJ post-2016 performance; a sourced optimal-contracting rebuttal to Bebchuk & Fried; any say-on-pay or pay-duration evidence; Masulis/Wang/Xie and Gompers/Ishii/Metrick "Extreme Governance" coefficients; Fama–French (2000) sample and N; Nissim & Penman (2001) own effect sizes; Novy-Marx JFE published-version magnitudes.

**Claims that are NOT verified at all and should not be asserted:** goodwill-to-assets predicts lower future returns (Liu/Yin/Zheng closed access, 404 conference copy); recurring-revenue share predicts durability; an independent "DSO anomaly"; RPO/backlog as a validated predictor; customer concentration raising audit fees (verified evidence is the **opposite** on fees); "buybacks are offset by SBC" as an aggregate statement; the −9% restatement reaction; any paper titled "Capital allocation and the cross-section of stock returns" (does not appear to exist); a verified return spread for the Morningstar Capital Allocation Rating.

**Sign warning:** Hirshleifer, Hou & Teoh (2009) find aggregate accruals **POSITIVELY** predict next-year aggregate returns (**+0.068, t = 3.33**) — the opposite of the firm-level accrual anomaly. Using it as a value-trap citation inverts its stated result.
