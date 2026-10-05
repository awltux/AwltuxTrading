# Capital-Allocation Markers for Separating Durable Compounders from Value Destroyers
### Using only annual / interim accounting (XBRL / iXBRL) data — source-grounded evidence review

---

## 0. How to read this document — provenance and verification tiers

**What I retrieved and read directly in this session (`web_fetch`, full text):**

| Source | URL |
|---|---|
| Boudoukh, Michaely, Richardson & Roberts, *On the Importance of Measuring Payout Yield*, NBER WP 10651 (Aug 2004, rev. Feb 2006) | <https://r.jina.ai/https://www.nber.org/system/files/working_papers/w10651/revisions/w10651.rev0.pdf> |
| Titman, Wei & Xie, *Capital Investments and Stock Returns*, NBER WP 9951 (Sept 2003) | <https://r.jina.ai/https://www.nber.org/system/files/working_papers/w9951/w9951.pdf> |
| Moeller, Schlingemann & Stulz, *Do shareholders of acquiring firms gain from acquisitions?*, NBER WP 9523 — NBER Digest summary "Big Firms Lose Value in Acquisitions" | <http://www2.nber.org/digest/aug03/w9523.html>, <https://www.nber.org/papers/w9523> |
| Moeller, Schlingemann & Stulz, *Wealth Destruction on a Massive Scale?*, NBER WP 10200 | <https://dev.nber.org/papers/w10200> |
| Moeller, Schlingemann & Stulz, *Do Acquirers With More Uncertain Growth Prospects Gain Less From Acquisitions?*, NBER WP 10773 | <https://www.nber.org/papers/w10773> |
| Mauboussin & Callahan, *Measuring the Moat*, Morgan Stanley Counterpoint Global, 15 Oct 2024 | <https://r.jina.ai/https://forum.valuepickr.com/uploads/short-url/c14zEZZD6bUcbyhVMn36kdlhXwT.pdf> |
| Hartzmark & Solomon, *The Dividend Disconnect* (JF 74(5), Oct 2019) — CFA Institute Research Foundation Journal Review | <https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4> |
| MSCI, *Beware high dividend yield traps* (Katiyar, Ladure & Lodh, 25 Oct 2019) | <https://www.msci.com/research-and-insights/blog-post/beware-high-dividend-yield-traps> |
| FASB US GAAP Financial Reporting Taxonomy 2024 (element namespace authority) | <https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd> |

**What a delegated, source-grounded research pass retrieved** (full text, with URLs listed inside `docs/research/reinvestment-and-capital-discipline.md`, which is present in the workspace — originally written as `reinvestment_capital_discipline_dossier.md`): the Fama–French/Kahle/Bens–Nagar–Skinner–Wong buyback papers, Peyer–Vermaelen, Ikenberry–Lakonishok–Vermaelen, Dittmar–Field, Fu–Huang, Kahle, Benartzi–Michaely–Thaler, DeAngelo–DeAngelo–Skinner, Goyal–Welch, McLean–Pontiff, Cooper–Gulen–Schill (abstract only), Lipson–Mortal–Schill, Hou–Xue–Zhang, Cooper–Gulen–Ion, McKinsey, and the Morgan Stanley capital-allocation papers. Their URLs are reproduced inline below where the pass reported them.

**Two honest provenance caveats, stated up front:**

1. **Three of the four delegated research artifacts did not persist to disk.** Only `docs/research/reinvestment-and-capital-discipline.md` is present in `F:\git-clones\AwltuxTrading` (the workspace was consolidated by the parent agent during this run). The buyback, dividend and M&A write-ups were delivered as message summaries only, and many of those claims carry author/year/journal but **no retained URL**. Every such claim is tagged `[URL NOT RETAINED]` below and belongs in the UNVERIFIED register (§7). I did not fabricate URLs to fill these gaps.
2. **SEC's XBRL APIs returned HTTP 403 ("Undeclared Automated Tool" / rate threshold) in this session** for `data.sec.gov/api/xbrl/companyconcept/...` and `www.sec.gov/edgar/sec-api-documentation`. Tag names below are therefore grounded on the **FASB US GAAP taxonomy schema** (retrieved, HTTP 200), not on a live per-filing machine check.

Confidence tags used throughout: **(a) robust / replicated**, **(b) single-paper**, **(c) contested / failed to replicate / decayed**.

---

# PART 1 — BUYBACKS

## 1.1 The repurchase anomaly, conditioned on valuation multiple

**1. Definition.** Firms that announce open-market repurchase (OMR) programmes earn positive abnormal returns over the following 1–4 years, and the drift is concentrated in *value* (low price-to-book / high book-to-market) firms. Marker form: `BuybackAnnouncementDummy × ValueDummy → 1–4yr BHAR`.

**2. Originating study.** Ikenberry, Lakonishok & Vermaelen (1995), *Market underreaction to open market share repurchases*, JFE 39(2–3):181–208; NBER WP 4965 (`[URL NOT RETAINED]` for the abstract text quoted below; NBER WP landing page is <https://www.nber.org/papers/w4965>, not fetched).

**3. Sample.** US open-market repurchase announcements, 1980–1990. **N of announcements UNVERIFIED** (the working-paper PDF OCR was garbled and no clean abstract was retrievable) `[URL NOT RETAINED]`.

**4. Effect size.** Average 4-year buy-and-hold abnormal return **+12.1%**; for value stocks **+45.3%**; glamour stocks show **no positive drift** `[URL NOT RETAINED]`.

**5. Replication / out-of-sample.** **Replicated on fresh data with a different methodology:** Peyer & Vermaelen (2009), RFS 22(4):1693–1745 — 3,481 US OMRs 1991–2001 plus 141 self-tenders 1987–2001. Self-tender expiry +8.6% mean (t = 5.5), 84% positive. OMR 4-year CAR (IRATS/FF3): full sample **+20.49% (t = 8.97)**; value (highest BM) **+28.89%** vs glamour **+14.87%**; announcement day value **+5.27%** vs glamour **−3.97%**; undervaluation-index top quintile ≈ **+50%** 4-year excess return vs bottom **6–13%**. 10 of 11 annual 1991–2001 portfolios significant at 48 months `[URL NOT RETAINED]`.

**Decay — tier (c).** Fu & Huang (2016), *Management Science* 62(4):964–984: long-run abnormal returns **"disappear for the events in 2003–2012"** (3-year avg BHAR −2.52%, RATS CAR −2.94% significant at 5%, VW calendar-time −1.89%, EW +5.32%). Lee, Park & Pearson, *Journal of Corporate Finance* 62:101552 ("Repurchases Have Changed"), 10,546 US OMRs 1994–2011: 3-year BHAR **+17.33%** and RATS CAR **+25.63%** in 1994–2001, versus BHAR **+0.74% (n.s., only 44.9% positive)** in 2002–2006; prior-year AR −13.32% → −6.01%; repeat repurchasers rose from <10% of announcements (1994) to >50% (post-2002). The two papers disagree on the cause (improved price efficiency vs changed repurchase motives) `[URL NOT RETAINED]`.

**6. Caveats.** Effect is a *value × repurchase interaction*, not a repurchase main effect — a naive gross-buyback factor will be contaminated by glamour-firm buybacks. Also `[URL NOT RETAINED]`: Ben-Rephael, Oded & Wohl (2014), *Review of Finance* 18(4):1299–1340 find the execution discount is **negative with size and positive with market-to-book**, and Stephens & Weisbach (1998), JF 53(1):313–333 find firms complete only **74–82%** of announced targets (450 programs, 1981–1990).

**7. XBRL computability.** Partially. Gross buyback yield = `us-gaap:PaymentsForRepurchaseOfCommonStock` ÷ market cap. **Market cap is not in XBRL** — needs an external price feed, or the cover-page `dei:EntityCommonStockSharesOutstanding` × close (point-in-time, filing-date stamped, not period-end). Repurchase *announcement* dates are **not** in XBRL at all; only cash settled in the period. So the announcement-drift version of this marker is not XBRL-computable; the *realised buyback intensity* version is.

---

## 1.2 Buyback timing skill

**1. Definition.** Whether managers systematically repurchase when their own stock is cheap, and whether that timing is persistent and return-predictive. Requires **actual repurchase prices**, i.e. `VWAP of shares bought back in period t ÷ price at period end`.

**2. Originating study.** Dittmar & Field (2015), JFE 115(2):261–282 (also JACF 28(4):73–85).

**3. Sample.** **All 2,237 US repurchasing firms, 2004–2011**, using actual repurchase price data (US Item 703 / Reg S-K free-form tables) `[URL NOT RETAINED]`.

**4. Effect size.** Infrequent repurchasers (≤4×/yr) earn an annual alpha **2.4% greater** than frequent repurchasers (≥9×/yr) over a six-month holding period; once-a-year repurchasers show **5.9%**; whole sample alphas ≈ **+0.3%/month** over 3–6-year windows; infrequent-minus-frequent **0.3%–0.6%/month**. Some JACF units are ambiguous `[URL NOT RETAINED]`.

**5. Replication.** **Tier (b).** Cook, Krigman & Leach (2004), RFS 17(2):463–498 — 64 US firms' actual trades 1993–94: **NYSE firms beat their benchmarks, NASDAQ firms do not**; trades cluster around news days `[URL NOT RETAINED]`. Brockman & Chung (2001), JFE 61(3):417–448 (Hong Kong, daily disclosure) — citation verified, **effect sizes UNVERIFIED**. Chan, Ikenberry & Lee (2007), *JBF* 31(9):2673–2694 — citation verified, **effect sizes UNVERIFIED**. Insider channel: Babenko, Tserlukevich & Vedrashko (2012), 5,827 US OMRs 1993–2008 — announcement returns positively related to pre-repurchase net insider buys `[URL NOT RETAINED]`.

**6. Caveats.** Very data-hungry. Post-2004 US only (Item 703). Sampling frequency mechanically confounds "skill" with trade size and liquidity provision.

**7. XBRL computability.** **Not computable from XBRL.** XBRL gives period *cash totals* and *share counts*, never execution prices. This marker needs the Item 703 monthly repurchase table (free-form, non-tagged) or a vendor file.

---

## 1.3 Net share-count reduction (buybacks net of SBC dilution) vs gross buybacks

**1. Definition.** `NetShareReduction = ΔSharesOutstanding` (or Δ weighted-average diluted shares) taken against `GrossBuyback = us-gaap:PaymentsForRepurchaseOfCommonStock`. **Net payout yield** = (dividends + net repurchases) ÷ market cap, where the two canonical repurchase measures are (i) *total repurchases* = cash-flow-statement purchases (Compustat #115 minus preferred reduction, #56) and (ii) *net repurchases* = change in treasury stock (Compustat #226), the Fama–French (2001) construction.

**2. Originating studies.** Fama & French (2001), *Disappearing dividends*, JFE 60(1):3–43; Boudoukh, Michaely, Richardson & Roberts (2007), JF 62(2):877–915.

**3. Sample.** Boudoukh et al.: aggregate time series **1926–2002**; cross-section = non-financial COMPUSTAT ∩ CRSP, repurchase data 1971–2002, treasury-stock measure 1984–2002, yield portfolios July 1985 – Dec 2002 (**210 months**). Directly retrieved (NBER WP 10651).

**4. Effect size** *(figures below are from the NBER WP 10651 revision I fetched verbatim)*:

| Horizon | Dividend yield | Total payout (CF) yield | Total payout (TS) yield |
|---|---|---|---|
| 1-yr β (t) | 0.133 (1.522) | **0.200 (2.699)** | 0.197 (2.241) |
| 1-yr R² | 4.1% | **7.2%** | 7.1% |
| 5-yr β (t) | 0.491 (1.780) | **0.683 (2.772)** | 0.665 (2.611) |
| 5-yr R² | **13.2%** | **19.2%** | 18.9% |

Joint regression (Panel D): dividend yield coefficient collapses to **−0.087 (t = −0.596)** while total payout carries **0.288 (t = 2.106)** (R² = 7.6%). Fama–MacBeth b₄ (7/85–12/02): dividend yield **−0.00 (t = −0.01)**; total payout (CF) **+0.07 (t = 2.17)**; total payout (TS) **+0.05 (t = 1.45)**. Decile average monthly returns (1/5/10): dividend **0.89 / 1.15 / 0.90**; payout CF **0.95 / 1.17 / 1.42**; payout TS **0.92 / 1.09 / 1.28**.

**Version discrepancy to note:** the *published* JF 2007 version is reported by the delegated pass as dividend R² 5.5% (coef 0.116, t = 2.240) vs payout 8.0–9.1% vs **net payout 26%**, with trading-strategy annual returns dividend +2.16%, payout +3.36%, net payout **+4.44%** `[URL NOT RETAINED]`. The NBER WP and the JF version therefore do differ; use one version consistently.

**The SBC-offset claim — tier (c), contested.** The *motive* is well replicated: Kahle (2002), JFE 63(2):235–261 — 712 US OMRs 1992–96, firms with more exercisable options are more likely to announce and complete buybacks; Bens, Nagar, Skinner & Wong (2003), JAE 36(1–3):51–90 — 357 S&P 500 Industrials 1996–99, repurchase decisions track **GAAP-defined dilution, not actual option exercise** `[URL NOT RETAINED]`. **But the popular claim that gross buybacks are "largely offset" by SBC issuance is not supported as an aggregate statement by any peer-reviewed source retrieved.** Lazonick (2014, INET — advocacy, not peer-reviewed) states buyback volume is *"generally a multiple of the volume of options that employees exercise"* — the opposite of the folk claim `[URL NOT RETAINED]`. Treat "buybacks are mostly SBC offset" as **CONTESTED / unsupported**.

**Measurement error.** Banyi, Dyl & Kahle (2008), JCF 14(4):460–474: Compustat annual share-repurchase estimates misstate actual shares by **≥10% in 48% of cases** (34% quarterly) `[URL NOT RETAINED]`.

**Real effects.** Almeida, Fos & Kronlund (2016), JFE 119(1):168–185 — regression-discontinuity evidence that EPS-motivated buybacks are associated with **reductions in employment and investment** `[URL NOT RETAINED]`.

**5. Replication.** Net-payout yield is **tier (a) in-sample**. Post-2003 out-of-sample replication of the payout-yield factor: **UNVERIFIED — not found**.

**6. Caveats.** The two repurchase measures disagree materially (Figure 1 of WP 10651 shows the CF-minus-TS gap growing over time). Boudoukh et al. explicitly note the TS measure suffers "lack of synchronicity between the repurchase program and employee stock distribution" and that its measurement error "may be significantly greater than total repurchases."

**7. XBRL computability.** Good. Required tags: `us-gaap:PaymentsForRepurchaseOfCommonStock`; `us-gaap:PaymentsOfDividendsCommonStock`; `us-gaap:ShareBasedCompensation`; `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`; `dei:EntityCommonStockSharesOutstanding`. Note the **treasury-stock (TS) measure is largely unavailable** — `us-gaap:TreasuryStockCommonValue` / `TreasuryStockValueAcquiredCostMethod` are optional and frequently absent; `us-gaap:StockRepurchaseProgramAuthorizedAmount1` is a *program authorisation*, not cash spent. **Best XBRL-only dilution proxy** = year-over-year change in weighted-average diluted shares.

---

## 1.4 Do buybacks predict returns better than dividends?

**1. Definition.** Compare `DividendYield`, `TotalPayoutYield`, and `NetPayoutYield` as return predictors, time-series and cross-sectionally.

**2. Originating study.** Boudoukh, Michaely, Richardson & Roberts (2007), JF 62(2):877–915 (NBER WP 10651).

**3. Sample.** As in §1.3.

**4. Effect size.** See the table in §1.3. Headline: total payout raises 1-year R² from **4.1% → 7.2%** and 5-year R² from **13.2% → 19.2%**; in a horse race the dividend coefficient is **statistically zero (−0.087, t = −0.60)** while payout survives at **t = 2.11**. The paper's Chow test finds a structural break in the dividend-yield AR(1) process (F = 3.616, p = 0.032) and predictive regression (F = 3.115, p = 0.051) but **not** in the total-payout CF yield (AR(1) F = 0.364, p = 0.696; predictive F = 1.851, p = 0.165) — i.e. the "disappearing dividend predictability" is largely an artefact of measuring dividends instead of payouts. The delegated pass additionally reports the HML payout-yield factor is priced and the model restrictions cannot be rejected with it, but can with a dividend-yield factor `[URL NOT RETAINED]`.

**5. Replication.** Authors report robustness to the payout-measurement method and to Goyal–Welch-type out-of-sample tests. **Independent post-2003 out-of-sample replication: UNVERIFIED.**

**6. Caveats.** Time-series market-timing evidence, not a cross-sectional stock-selection factor — much weaker for a single-name compounder screen. Pre-1971, payout yield is *assumed* equal to dividend yield (negligible repurchases), which mechanically ties the two series in the early sample.

**7. XBRL computability.** Same as §1.3; add `us-gaap:PaymentsOfDividendsCommonStock` and require an external market-cap series.

---

# PART 2 — DIVIDEND POLICY

## 2.1 Dividend initiations and omissions: announcement reaction vs post-announcement drift

**1. Definition.** Three-day announcement abnormal return, and 12-month post-announcement market-adjusted drift, around first-time dividend payments (initiations) and dividend cessations (omissions).

**2. Originating study.** Michaely, Thaler & Womack (1995), *Price Reactions to Dividend Initiations and Omissions: Overreaction or Drift?*, JF 50(2):573–608; NBER WP 4778 — <https://www.nber.org/papers/w4778> (landing page retrieved by the delegated pass; the PDF body returned empty through the text proxy).

**3. Sample.** **UNVERIFIED** — the working-paper PDF was not readable; period and event counts were not confirmed.

**4. Effect size.** Three-day announcement: omissions **−7.0%**, initiations **+3.4%**. Twelve months post-announcement (excluding the event month), market-adjusted: initiations **+7.5%**, omissions **−11.0%**. A long/short trading rule was positive in **22 of 25 years** `[URL NOT RETAINED]`. Critically, the authors themselves report the asymmetry **"shrinks or disappears"** once the magnitude of the dividend-yield change is controlled for.

**5. Replication — tier (c) for the drift, tier (a) for the announcement reaction.**
- Boehme & Sorescu (2002), JF 57(2):871–900, sample **1927–1998**: post-announcement abnormal returns are "significantly positive for equally weighted calendar time portfolios, but become insignificant when the portfolios are value weighted"; results are "not robust across subsamples"; drifts "may be a sample-specific result of chance" `[URL NOT RETAINED]`.
- Liu, Szewczyk & Zantout (2008), JF 63(2):987–1020, **N = 2,337** reductions/omissions 1927–1999: the negative drift **"last[s] 1 year only"** and is **"driven by post-earnings-announcement drift"**; after controlling for earnings and skewness "there is no compelling evidence" of a dividend-specific drift `[URL NOT RETAINED]`.
- Hobbs & Schneller (2012), *Applied Financial Economics* 22(17):1395–1408: in the "disappearing dividends era" the market "did not distinguish ex-ante between short-run and long-run payers," but **dividend sustainability was predictable out-of-sample** and predicted permanent payers outperform `[URL NOT RETAINED]`.

**Actionable read:** the **announcement-day reaction is robust**; the famous **12-month drift is NOT**. Do not build a compounder screen on equal-weighted drift.

**6. Caveats.** Equal- vs value-weighting is decisive. Omission drift overlaps with post-earnings-announcement drift and with distress. Small-cap concentration.

**7. XBRL computability.** Initiations/omissions require a **dividend history**; you can derive them from `us-gaap:CommonStockDividendsPerShareDeclared` / `us-gaap:PaymentsOfDividendsCommonStock` across consecutive periods and across **interim** filings. **Structured XBRL only starts ~2009–2011 for large filers** — a long dividend history must be back-filled from pre-XBRL data or a vendor file. Announcement *dates* are not in XBRL.

---

## 2.2 Dividend yield trap: does high yield predict low returns?

**1. Definition.** `DividendYield = DPS_t / Price_t`. The "trap" hypothesis is that the highest-yield names are disproportionately distressed, so realised yield (and total return) falls short of trailing yield.

**2. Baseline (positive predictability).** Fama & French (1988), *Dividend yields and expected stock returns*, JFE 22(1):3–25 — **coefficients and R² UNVERIFIED** (abstract contains no numbers, full text not retrieved) `[URL NOT RETAINED]`.

**3. Out-of-sample failure — tier (a) for the failure.** Goyal & Welch (2008), RFS 21(4):1455–1508: predictive models "predicted poorly both in-sample (IS) and out-of-sample (OOS) for 30 years now… would not have helped an investor with access only to available information to profitably time the market." Dividend yield is a canonical variable in that horse race `[URL NOT RETAINED]`.

**4. The negative-prediction mechanism — Hartzmark & Solomon, *The Dividend Disconnect*, JF 74(5), Oct 2019.** Retrieved two ways: NBER 2017 draft (<http://www2.nber.org/conferences/2017/BFs17/Hartzmark_Solomon.pdf> `[URL NOT RETAINED for the draft itself]`) and the **CFA Institute Research Foundation Journal Review, which I fetched directly** (<https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4>):
- Investors treat price changes and dividends separately ("free dividends fallacy"); the CFA review states the consequence directly: **"total return can be 2%–4% lower over the next year."**
- **Correlation of −0.50 between daily prices and dividend yields** for individual stocks (CFA review, verbatim).
- Mutual funds show a **1.1% lower** disposition effect on dividend-paying positions; institutions **0.7% lower** (CFA review, verbatim).
- From the NBER draft (delegated pass): B/M-gap coefficient **0.225, t = 2.16** (Newey–West, 12-month lag); a 0.1 decrease in the dividend-payer/non-payer B/M ratio → **2.3% lower** expected returns over the next 12 months (0.2 → 4.6%); interim-period return on dividend change **0.0313** (≈3 bp per extra penny of dividends); "No Div. Cut in Prior Year" +12–13 bp; highest-payout week days +16 bp daily VW market return vs 4 bp mean. Exact dividend reinvestment is rare: mutual funds 0.719%, institutions 1.17%; MF 43.1× and institutions 15.6× more likely to leave holdings unchanged than to reinvest `[URL NOT RETAINED]`.

**5. Measurement matters — tier (a).** Use payout yield, not dividend yield (§1.3/§1.4).

**6. Vendor research with published methodology (non-peer-reviewed).** MSCI, *Beware high dividend yield traps* (retrieved): MSCI World, ~1,600 constituents, 20 years to 2019. Simple "high trailing yield" selection returned **+64 bps/yr** over MSCI World with **15.1% volatility**. Adding screens for unsustainable/non-persistent payouts, broken technicals and low quality raised the combined approach to **7.3%/yr vs 5.6%** for the parent index while cutting volatility from **15.0% → 13.7%**. In the highest-volatility regime the *simple* yield strategy's realised-to-trailing yield ratio **dropped 15%**, whereas the screened approach delivered **96%** of trailing yield. **Caveat:** index-provider simulation, not a peer-reviewed regression; no t-statistics or factor alphas.

**7. Contradictory evidence.** Two emerging-market "dividend trap" studies point in opposite directions (Oktaviani Putri & Wijayanti 2025, IDXHIDIV20 2023: negative significant DY effect; Natalia & Kohardinata 2024, 223 obs 2022–2023: **positive** significant DY effect). Treat the EM "trap" literature as noise `[URL NOT RETAINED]`.

**8. XBRL computability.** Payout ratio and yield are computable (`PaymentsOfDividendsCommonStock`, `CommonStockDividendsPerShareDeclared`, `NetIncomeLoss`, `EarningsPerShareBasic/Diluted`, `NetCashProvidedByUsedInOperatingActivities`, `PaymentsToAcquirePropertyPlantAndEquipment`). **Price is not in XBRL.** Distress inputs are: `StockholdersEquity`, `RetainedEarningsAccumulatedDeficit`, `LongTermDebtNoncurrent`, `ProceedsFromIssuanceOfLongTermDebt`.

---

## 2.3 Dividend growth, "aristocrats", and the information content of dividends

**1. Definition.** Return premium to dividend *growers* (and to long dividend streaks), and whether dividend changes predict **future** earnings.

**2. Originating studies and effect sizes — information content is largely REJECTED for "future":**
- Benartzi, Michaely & Thaler (1997), JF 52(3):1007–1034: "only limited support"; earnings increases are concentrated in years **−1 and 0**, with "no subsequent unexpected growth"; the **size of the dividend change does not predict earnings**; dividends are a **lagging** indicator `[URL NOT RETAINED]`.
- DeAngelo, DeAngelo & Skinner (1996), JFE 40(3):341–371: **145 NYSE firms** that increased dividends after stalled earnings growth — "most firms' prior sustained earnings growth evaporated, and there is **essentially no relation** between favorable dividend signals and future earnings" `[URL NOT RETAINED]`.
- Grullon, Michaely & Swaminathan (2002), *Journal of Business* 75(3):387–424: dividend increases are a **maturity** signal — significant decline in systematic risk, **no increase in capex or profitability**; the market reaction is "significantly related to the subsequent decline in systematic risk" `[URL NOT RETAINED]`.
- Ham, Kaplan & Utke (2021), *Review of Accounting Studies* 28(1):265–306: dividend-paying firms have **11%–15% lower earnings response coefficients** than non-payers `[URL NOT RETAINED]`.
- **Counter-evidence:** Nissim & Ziv (2001), JF 56(6) — abstract confirms dividend changes "provide [information] about the level of profitability in subsequent years," positive in each of the two years after the change; but the **direct rebuttal** is Grullon, Michaely, Benartzi & Thaler (2005), *Dividend Changes Do Not Signal Changes in Future Profitability*, JB 78(5):1659–1682 (OpenAlex record retrieved: <https://api.openalex.org/works/doi:10.1086/431438>). **Exact coefficients for both: UNVERIFIED** (bodies 403-blocked).

**3. Index construction (aristocrats) — retrieved from an SSGA PDF citing S&P DJI methodology as of Jan 2024** `[URL NOT RETAINED]`; the S&P DJI primary methodology PDF was 403-blocked. US S&P Dividend Aristocrats: S&P Composite 1500 universe, **20+ consecutive years** of increases, ≥$2bn float-adjusted market cap, ≥$5mn daily value traded, float-adjusted shares, quarterly (January) reconstitution. Eurozone 10+ years / 40 stocks; UK 7+ / 40; Global 10+ / 100; Pan Asia 7+ / 40–100; EM 5+ / floating. **All non-US variants additionally require positive EPS growth, ≤100% maximum payout ratio, and ≤10% maximum yield.** Weighting = indicated annual dividend yield, "(Most recent dividend × number of dividend payments) / Stock Price".

**4. Effect size for growth strategies.** S&P DJI (Cheng & Srivastava), *A Case for Dividend Growth Strategies* (2017), retrieved via a sponsored report: **31 Dec 1999 – 30 Sep 2016**; in down months the S&P High Yield Dividend Aristocrats beat the S&P Composite 1500 by **165 bps/month** and the S&P 500 High Dividend Index by **54 bps/month**. Index average streak **34.5 years**; 8 constituents with >53 consecutive years. **Caveat: vendor-sponsored, conditional on down months only, no t-statistics or factor alphas — tier (b)/single-source, unrefereed** `[URL NOT RETAINED]`.

**5. XBRL computability.** Streak detection requires a multi-year DPS series (`us-gaap:CommonStockDividendsPerShareDeclared`, plus split-adjustment). The **Aristocrats screens' two quantitative gates are directly XBRL-computable**: payout ratio (`DividendsPaid ÷ NetIncomeLoss`) ≤100% and yield ≤10% (yield needs price). Note `PayoutRatio = DPS/EPS` is **undefined or sign-flipped for loss-makers** — prefer `PaymentsOfDividendsCommonStock ÷ NetCashProvidedByUsedInOperatingActivities` with explicit negative-denominator handling. A **20-year streak cannot be built from XBRL alone** (structured data starts ~2009–2011).

---

## 2.4 Payout-ratio sustainability markers

**1. Definition.** `PayoutRatio = Dividends ÷ NetIncome`; coverage `= (CFO − Capex) ÷ DividendsPaid`; plus a **debt-funded-dividend flag** = `(CFO − Capex) < DividendsPaid` **and** `ProceedsFromIssuanceOfLongTermDebt > 0`.

**2. Originating studies.**
- DeAngelo & DeAngelo (1990), JF 45(5):1415–1431: **80 NYSE firms** with multiple losses, 1980–1985 — **"almost all sample firms reduced dividends, and more than half apparently faced binding debt covenants"**; omission is resisted more than reduction; managers with long dividend histories are "particularly reluctant to omit." Here the **loss and the debt covenant are the predictors**, not the payout ratio `[URL NOT RETAINED]`.
- DeAngelo, DeAngelo & Skinner (1992), *Dividends and Losses*: **"An annual loss is essentially a necessary condition for dividend reductions"**; **50.9% of 167 NYSE firms** with losses during 1980–85 reduced dividends. **This is the single most concrete cut-predictor number retrieved** `[URL NOT RETAINED]`.

**3. Is cut-prediction tradable? No — tier (c).** Gunasekarage, Hess & Power (2015), *International Journal of Banking and Finance* 11:31–53, New Zealand: the one-year-ahead logit dividend-change model "has some success," but trading it **"proved unsuccessful"** — buying predicted increasers and selling predicted decreasers earned **−2.34% abnormal over 24 months** `[URL NOT RETAINED]`.

**4. "Cut = distress" is not unconditional.** Das & Dhole (2024), *Journal of Business Finance & Accounting* 52(1):91–126: dividend cuts receive a **positive** market response when the firm has a positive investment opportunity set; those firms do increase capex and M&A and show higher subsequent operating profitability; significant BHAR difference over 2 years between high- and low-IOS cutters `[URL NOT RETAINED]`. Also Lie (2005): "little evidence that earnings change following 661 dividend decreases and 484 dividend omissions" `[URL NOT RETAINED]`.

**5. XBRL computability.** Good, and this is one of the most XBRL-friendly markers. `us-gaap:PaymentsOfDividendsCommonStock` (common only — excludes preferred; prefer this over the broader `us-gaap:PaymentsOfDividends`), `us-gaap:NetIncomeLoss`, `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:LongTermDebtNoncurrent`, `us-gaap:ProceedsFromIssuanceOfLongTermDebt`, `us-gaap:RetainedEarningsAccumulatedDeficit`, `us-gaap:StockholdersEquity`. **FCF is not a standard tag** — must be computed. **Interim cash-flow tags are year-to-date**, so they must be differenced, not summed, to get quarterly flows.

**6. Caveats.** Payout ratio is undefined for loss-makers — precisely the population of interest; use cash coverage. Sector: exclude/dummy financials and utilities; high-yield screens are largely a utilities/staples/REITs/financials sector bet.

---

# PART 3 — M&A

## 3.1 Acquirer underperformance

**1. Definition.** Announcement-window CAR(−1,+1) to the acquirer and 3–5-year post-merger BHAR/calendar-time alpha.

**2. Originating studies.** Agrawal, Jaffe & Mandelker (1992), JF 47(4):1605–1621; Loughran & Vijh (1997), JF 52(5):1765–1790; Rau & Vermaelen (1998), JFE 49(2):223–253; Moeller, Schlingemann & Stulz (2004), JFE 73(2):201–228 and (2005), JF 60(2):757–782.

**3. Access reality (material for citation discipline).** Four of these classics — Agrawal/Jaffe/Mandelker 1992, Loughran/Vijh 1997, Rau/Vermaelen 1998, Moeller/Schlingemann/Stulz 2004 — were confirmed **closed access with no open-access copy** (Unpaywall check by DOI). **No effect size has been reported for them here.** Instead, the NBER working-paper versions of the same authors' work were retrieved and are reported below, labelled as such.

**4. Effect sizes (retrieved).**
- **Moeller, Schlingemann & Stulz, NBER WP 9523** — sample **12,023 acquisitions by public firms, 1980–2001** (SDC + CRSP + Compustat, ≥$1mn, completed): 5,583 private-target, 3,798 subsidiary, 2,642 public-target deals. Mean CAR(−1,+1): **all 1.103%**; private **+1.496%**; **public −1.020%**; subsidiary **+2.003%**. Shareholders lost **$218 billion** in aggregate; **−5.9 cents per dollar spent** acquiring a public firm; aggregate public-target losses ≈ **$257bn**. Small firms **+$8bn**, large firms **−$226bn**. The NBER Digest summary (fetched directly) states: **"An acquisition made by a small firm — regardless of funding and the nature of the target — has an announcement return that is 1.55 percent higher than a comparable acquisition made by a large firm."** The delegated pass read **2.24%** from a different WP specification — treat the precise magnitude as **specification-dependent** and prefer the digest's 1.55% unless the WP table is re-checked.
- **Moeller, Schlingemann & Stulz, NBER WP 10200** (fetched directly): acquirer shareholders **"lost 12 cents at the announcement of acquisitions for every dollar spent… for a total loss of $240 billion from 1998 through 2001, whereas they lost $7 billion in all of the 1980s, or 1.6 cents per dollar spent."** Bidder losses exceeded target gains by **$134 billion** over 1998–2001. The delegated pass adds: 1998–2001 mean CAR **+0.69%** while aggregate loss was **−$239,954m** — i.e. the loss is driven by **87 large-loss deals out of 4,136** (avg CAR **−10.6%**, avg loss **$2.31 per dollar spent**), and the skewness coefficient went from **−1.76 (1980–97) to −6.99 (1998–2001)**. **"Firms that announce acquisitions with large dollar losses perform poorly afterwards."**
- **King, Dalton, Daily & Covin (2004), *Strategic Management Journal* 25(2):187–200** (abstract fetched): acquiring-firm performance **"does not positively change as a function of their acquisition activity, and is negatively affected to a modest extent."** Numeric effect size **UNVERIFIED**.

**5. Replication / robustness — the long-run result is METHOD-DEPENDENT even inside one paper.** In the WP 9523 sample the **calendar-time monthly alpha is −0.041% and statistically INSIGNIFICANT**, while the **event-time 3-year BHAR** shows acquirers performing poorly `[URL NOT RETAINED]`. Fama (1998) is the standard critique of long-horizon BHAR. Treat "acquirers underperform for 3–5 years" as **tier (c) contested**; treat the **announcement-day** public-target loss as **tier (a)**.

**6. Caveats.** Dollar-weighted vs equal-weighted changes the conclusion entirely (aggregate losses are a handful of mega-deals). Target type (public/private/subsidiary) dominates payment method. Disclosed deal values are not in XBRL.

**7. XBRL computability.** Announcement CAR: **not computable**. Post-merger operating performance: computable (`us-gaap:OperatingIncomeLoss`, `us-gaap:Assets`). Deal-level identification requires `us-gaap:BusinessCombinationConsiderationTransferred1` / `PaymentsToAcquireBusinessesNetOfCashAcquired`, which are **materiality-filtered** — so any XBRL deal-count screen is **biased toward large acquirers, exactly the population MSS find destroys value** (small +$8bn vs large −$226bn).

---

## 3.2 Empire building / free-cash-flow hypothesis

**1. Definition.** Jensen (1986): firms with **free cash flow** (cash flow in excess of that required to fund all positive-NPV projects) and **low growth options (Tobin's q < 1)** are the ones that make value-destroying acquisitions.

**2. Originating study.** Jensen, *Agency Costs of Free Cash Flow, Corporate Finance, and Takeovers*, AER 76(2):323–329. Full text retrieved verbatim: **"Free cash flow is cash flow in excess of that required to fund all projects that have positive net present values…"** **It is a theory/ Presidential-Address essay — it contains NO effect sizes.**

**3. Critical empirical caveat.** In the 12,023-deal MSS sample, **the Lang, Stulz & Walkling (1991) measure of free cash flow — cash flow interacted with q < 1 — IS NOT SIGNIFICANT.** The low-q × CASH-acquisition effect is **−0.87%** `[URL NOT RETAINED]`. Lang, Stulz & Walkling and Harford (1999) full texts were **not retrievable** — **UNVERIFIED**.

**4. XBRL computability.** FCF proxy computable: `NetCashProvidedByUsedInOperatingActivities − PaymentsToAcquirePropertyPlantAndEquipment`. Tobin's q needs market value (external price feed) plus `us-gaap:Assets` and liabilities.

---

## 3.3 Acquisition intensity as a value-destruction marker

**1. Definition.** Acquisition (and total investment) spend scaled by assets, sales or cash flow, tested against subsequent returns. TWX's capital-investment measure is `CI_{t−1} = [CE_{t−1} − (CE_{t−2}+CE_{t−3}+CE_{t−4})/3] ÷ Sales`, where `CE` = capital expenditure.

**2. Originating study.** Titman, Wei & Xie (2004), JFQA 39(4):677–700 (NBER WP 9951) — retrieved in full **by me**.

**3. Sample.** NYSE/Amex/Nasdaq domestic primary stocks; financials, closed-end funds, trusts, ADRs, REITs excluded; **financial data 1969–1995, returns July 1973 – June 1996**; final sample ≈ **1,635 firms/year**.

**4. Effect size (value-weighted, characteristic-adjusted, % per month).** Lowest CI quintile **+0.042**; quintile 2 **+0.083**; 3 **+0.055**; 4 **−0.083**; highest **−0.127**. **CI-spread (long bottom 2 / short top 2) = +0.168%/month** (significant, p < 0.01); **Carhart four-factor alpha +0.192%/month**. Year-by-year spreads: +2.02, +2.26, +1.91, +1.85, +1.64% (t = 2.86, 2.88, 2.46, 2.10, 1.81); **5-year cumulative +8.10% (t = 2.55)**. Fama–MacBeth CI coefficient **−0.79 (t = −2.80)** all years. **23.78% of the year-1 spread accrues in 3-day earnings windows** (0.792% vs 3.330%), supporting a mispricing rather than risk explanation.

**5. Replication / regime dependence — tier (b), with an in-sample failure.** The effect is **stronger where managers have investment discretion**: high-CF spread +0.227 (alpha +0.256) vs low-CF +0.078; low-leverage +0.225 (alpha +0.286) vs high-leverage +0.099. **In the 1984–89 hostile-takeover years the spread is −0.144%/month (alpha −0.124) and insignificant**; Fama–MacBeth CI coefficient −0.02 (t = −0.06). The authors attribute this to the disciplinary role of the takeover market. A single-paper US result whose sign **flipped in a 6-year sub-period**.

**Acquisition-specific intensity:** **no academic paper linking acquisition intensity to subsequent returns was verified** — acquisition intensity is covered by the broader asset-growth/investment factor below.

**6. XBRL computability.** Good. `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` (fallback `PaymentsToAcquireProductiveAssets`), `us-gaap:Revenues` / `RevenueFromContractWithCustomerExcludingAssessedTax`, `us-gaap:Assets`. Note **capex is one line of a much broader investment bundle** (see §4.2 on off-balance-sheet and intangible investment).

---

## 3.4 Goodwill build-up and goodwill impairment

**1. Definition.** `Goodwill / TotalAssets`, annual goodwill growth, and `GoodwillImpairmentLoss / Goodwill`.

**2. Originating / key studies.**
- Gu & Lev (2011), *The Accounting Review* — abstract: the **"root cause of many goodwill write-offs is the buyers' overpriced shares at acquisition"**; overpricing predicts write-offs **and their magnitude**. Sample/N/coefficients **UNVERIFIED** `[URL NOT RETAINED]`.
- Li, Shroff, Venkataraman & Zhang (2011), *Review of Accounting Studies* — abstract: impairment is followed by **downward revisions by investors and analysts**, is a **leading indicator of profitability decline**, is predicted by overpayment proxies, and managers exercise discretion to **AVOID** impairment losses `[URL NOT RETAINED]`.
- Hayn & Hughes (2006): **"goodwill impairments lag behind the economic impairment by an average of three to four years. For one-third of the companies examined, the delay can extend up to ten years."** `[URL NOT RETAINED]`

**3. The specific claim "goodwill-to-assets predicts lower future returns" is NOT VERIFIED.** Liu, Yin & Zheng, "The invisible burden," *Journal of Financial Markets* 52:100561 is closed access and the conference PDF 404s. Do **not** cite that claim.

**4. Caveats.** The 3–4-year recognition lag means an XBRL goodwill screen is a **lagging** signal by construction; impairments are also discretionary. Under ASC 350 (post-2001) goodwill is not amortised, so `Goodwill/Assets` mechanically trends up in serial acquirers until a write-off.

**5. XBRL computability — one of the two BEST markers.** `us-gaap:Goodwill`, `us-gaap:GoodwillImpairmentLoss`, `us-gaap:AssetImpairmentCharges`, `us-gaap:Assets`, `us-gaap:IntangibleAssetsNetExcludingGoodwill`, `us-gaap:BusinessCombinationConsiderationTransferred1`, `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`. Interim `GoodwillImpairmentLoss` is YTD. Segment-level goodwill requires the `us-gaap:StatementBusinessSegmentsAxis` dimension (patchy).

---

## 3.5 Serial acquirers — BOTH sides

**1. Definition.** A firm that makes acquisitions repeatedly (e.g. ≥1 deal/year for 3 consecutive years), tested against one-off acquirers.

**2. Evidence FOR outperformance.**
- Fuller, Netter & Stegemoller (2002), JF 57(4):1763–1793 — abstract (fetched): **bidder shareholders GAIN on acquisitions of private firms and subsidiaries and LOSE on public firms**; N and coefficients **UNVERIFIED** `[URL NOT RETAINED]`.
- **L.E.K. Consulting, *Keys to M&A Success: How Serial Acquirers Drive Outperformance*** (full PDF retrieved): **5,400+ US public companies, 2016–2025**, TSR basis; serial acquirer = **≥1 acquisition every year for 3 consecutive years** (only **8%** of companies). Serial acquirers "outperformed those companies that only engage in M&A occasionally by more than **11%** and organic-only companies by more than **14%** on a weighted-average TSR basis." **Caveats: TSR, not alpha; no factor adjustment; and the report itself concedes "there may be correlated factors between serial acquirers and prior financial success… our experience suggests it is causal, not incidental" — i.e. no causal identification. Tier (b), single-source consultancy claim.**
- Aktas, de Bodt & Roll (2011), *Journal of Corporate Finance* (full text retrieved; **568–630 deals, 152–164 CEOs, 1992–2007**): **"In reaction to a decrease of one standard deviation in abnormal returns after their previous deal announcement, CEOs reduce their bids by 4.27% in the subsequent deal… a bid premium percentage change of −12%."** Raw CARs: **−1.10%** (deal *d*) vs **−0.12%** (deal *d−1*), N = 381, **p = 0.24** — the raw decline is **NOT significant**; the authors caution against generalising.

**3. Evidence AGAINST / mixed.** The **declining-CAR-within-a-programme pattern is corroborated by five independent papers** per Aktas et al. **King et al. (2004)** (see §3.1) find acquiring-firm performance does not improve with acquisition frequency.

**4. XBRL computability.** Deal-level counting requires `us-gaap:BusinessCombinationConsiderationTransferred1` / `PaymentsToAcquireBusinessesNetOfCashAcquired`, which are **materiality-filtered** — a deal-count screen built on XBRL will **systematically miss small deals and therefore misclassify genuine serial acquirers**. Use the **acquisition-spend intensity ratio** instead, or supplement with non-XBRL deal data.

---

# PART 4 — REINVESTMENT vs RETURNING CASH / CAPITAL DISCIPLINE

*(All figures in this Part come from `reinvestment_capital_discipline_dossier.md`, whose full "SOURCES FETCHED" list of 17 retrieved URLs is reproduced in §8.)*

## 4.1 The ROIC × reinvestment-rate framing

**1. Definition.** `ROIC = NOPAT ÷ Invested Capital`; value creation = **ROIC − WACC spread**, scaled by how much capital can be invested at that spread and for how long. `ROIIC = ΔNOPAT ÷ prior-year investment`; reinvestment rate = `g ÷ ROIIC` *(this last is a derivation from the ROIIC definition, not a verbatim quote — flagged as such in the dossier)*.

**2. Originating studies.**
- Mauboussin & Callahan, *The Math of Value and Growth*, Morgan Stanley Counterpoint Global, 9 Jun 2020 (<https://www.strictlybiz.co.nz/wp-content/uploads/2022/12/themathofvalueandgrowth_us.pdf>).
- Mauboussin & Callahan, *Capital Allocation: Evidence, Analytical Methods, and Assessment Guidance*, JACF 26(4) 2014, 48–74, DOI 10.1111/jacf.12090 — **Wiley full text blocked by bot wall**; abstract retrieved via EconPapers (<https://econpapers.repec.org/article/blajacrfn/v_3a26_3ay_3a2014_3ai_3a4_3ap_3a48-74.htm>): sample = **"the largest 1,500 U.S. companies during the last 30 years"**; five principles including zero-based capital allocation, fund strategies not projects, no capital rationing, **zero tolerance for bad growth**.
- Mauboussin & Callahan, *Measuring the Moat*, Morgan Stanley Counterpoint Global, 15 Oct 2024 (retrieved **by me**): **"A company creates value when it makes investments… that generate cash flows over time that exceed their cost… including the opportunity cost of capital"**; ROIC = NOPAT ÷ invested capital; Morningstar moat definitions (>20 years wide, 10–20 narrow).

**3. Effect sizes / calibrated numbers** (from *The Math of Value and Growth*, per the dossier): commodity P/E = `1 ÷ cost of equity` (≈14.9× at a 6.7% cost of equity); baseline NOPAT growth 10%, ROIIC 20%, cost of equity 6.7% → **P/E 32.3**; growth 15% → **52.2**; cutting growth from 10%→7% reduces next-year EPS by only **2.7%** but cuts P/E **32.3 → 24.9 (−22.9%)**; 15%→12% → P/E **52.2 → 39.0 (−25.3%)**. **An ROIIC below the 6.7% cost of capital yields a P/E below the commodity multiple.** Commodity P/E averaged **10.7** since 1961 (5.1 in 1981; 16.7 on 1 Jun 2020); the S&P 500 P/E was ~35% above the commodity P/E at that date.

From *Measuring the Moat* (2024): S&P 500 steady-state value has averaged **two-thirds of price** with anticipated value creation the other **one-third** (1961 – mid-2024); **ROICs revert substantially** over a decade (quintile medians regress toward the universe median, 2013–2023).

**4. Replication.** This is a **methodology/valuation identity, not a return anomaly** — post-publication decay does not apply. **UNVERIFIED:** the JACF 2014 article's internal dollar tables (paywalled).

**5. Caveats.** ROIC must be adjusted for **internally-generated intangibles**, or R&D-heavy compounders look capital-light and the spread is overstated (the 2024 Morgan Stanley report explicitly adjusts for this). WACC requires a market-based cost of equity — **not derivable from XBRL**.

**6. XBRL computability.** `us-gaap:OperatingIncomeLoss`, `us-gaap:NetIncomeLoss`, `us-gaap:IncomeTaxExpenseBenefit`, `us-gaap:Assets`, `us-gaap:StockholdersEquity`, `us-gaap:LongTermDebtNoncurrent`/`Current`, `us-gaap:CashAndCashEquivalentsAtCarryingValue`, `us-gaap:PropertyPlantAndEquipmentNet`, `us-gaap:IntangibleAssetsNetExcludingGoodwill`, `us-gaap:Goodwill`. **Invested capital is not a tag** — it must be constructed (debt + equity − excess cash, or operating assets − operating liabilities), and the choice materially changes ROIC. **WACC is not in XBRL at all.**

---

## 4.2 Capital expenditure and asset growth → future returns

**1. Definition.** `AssetGrowth = ΔTotalAssets_t ÷ TotalAssets_{t−1}`; capex-based `CI` as in §3.3.

**2. Originating studies.** Titman, Wei & Xie (2004), JFQA 39(4):677–700 (see §3.3 for full effect sizes, retrieved by me); Cooper, Gulen & Schill (2008), *Asset Growth and the Cross-Section of Stock Returns*, JF 63(4):1609–1651.

**3. CGS sample and effect size — PARTIALLY UNVERIFIED.** The JF paper is behind both a Wiley and an SSRN bot wall; the **abstract was verified via EconPapers** (<https://econpapers.repec.org/article/blajfinan/v_3a63_3ay_3a2008_3ai_3a4_3ap_3a1609-1651.htm>): **"Asset growth rates are strong predictors of future abnormal returns. Asset growth retains its forecasting ability even on large capitalization stocks."** The **original Table III lowest-minus-highest decile spread, t-statistic and 3-factor alpha, and the paper's own N, are UNVERIFIED.** Verified substitutes:
- Chen, Yao, Yu & Zhang, *Asset Growth and Stock Returns: Evidence from the Pacific-Basin Markets* (<https://www.cass.city.ac.uk/__data/assets/pdf_file/0011/76916/Yu-141-REVISED.pdf>): CGS **"during the period from 1968 to 2003, firms ranked in the top decile of asset growth underperform firms ranked in the bottom decile by more than 20% in stock returns during the year after ranking."**
- Lipson, Mortal & Schill, *Unraveling the Asset Growth Effect* (<http://faculty.bus.olemiss.edu/rvanness/speakers/2009-2010/Mortal-Asset%20Growth%20Effect.pdf>): bottom CGS quintile mean **22.6%/yr** vs top **6.9%/yr** = **15.7%** zero-investment return, 1968–2006; CGS low−high quintile **1.3%/month EW (t = 8.42)** / **0.7%/month VW (t = 4.11)**.

**4. Related factor evidence.**
- **FF5 CMA** — Fama & French's own printed number **not retrieved** (mirrors blocked/404). Hou, Xue & Zhang's replication over Jan 1967 – Dec 2014 using Ken French's published factors: **RMW 0.27% (t = 2.58), CMA 0.34% (t = 3.63)** (<https://www.nber.org/system/files/working_papers/w23394/w23394.pdf>).
- **HXZ q-factor investment factor:** **0.44%/month (t = 4.73)**, Jan 1972 – Dec 2011; **0.43%/month (t = 5.08)**, Jan 1967 – Dec 2014 (<https://www.nber.org/system/files/working_papers/w18435/w18435.pdf>).

**5. Replication / decay — tier (a) for existence, (c) for original magnitude.**
- **Hou, Xue & Zhang, *Replicating Anomalies*, NBER WP 23394 / RFS 33(5) 2020.** Jan 1967 – Dec 2014, **447 anomalies**, NYSE breakpoints + value weights: **286 (64%) insignificant at 5%; 380 (85%) at t = 3.** **CGS asset growth is explicitly named as an anomaly whose magnitude is "much lower than originally reported."** Microcaps are 61% of stocks but only 3.3% of market cap — a key driver of inflated original estimates.
- **Lipson, Mortal & Schill, JFQA, "On the Scope and Drivers of the Asset Growth Effect"** (<https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/on-the-scope-and-drivers-of-the-asset-growth-effect/B8CFCF68A82E273E979221EF26A77096>): all 7 asset-growth measures negatively predict returns (t from −3.60 to −9.09; CGS **−0.012, t = −9.09**), 1968–2006, 468 months. The effect **"applies quite strongly to stocks of all sizes"** with total-asset growth (big-stock low−highest 0.67%, t = 4.04), but **"there appears to be no asset growth effect in firms with low idiosyncratic volatility"** (lowest IVOL quintile spread **0.1%, t = 1.02**). The published abstract adds the effect is **"concentrated around earnings announcements."**
- **Cooper, Gulen & Ion (2024), JFE 151:103746** (<https://fairmodel.econ.yale.edu/ec439/ansh.pdf>): FF5 and HXZ **both use CGS asset growth as their investment measure**; swapping in capex/PPE or intangible-inclusive measures significantly degrades both models; **"growth in inventory (INVT) and growth in accounts receivable (AREC)… contain the bulk of the pricing information."** Decisively: the advantage **"is present only in high overextrapolation periods"** — below-median DOX, HXZ ≈ Carhart and FF5F ≈ FF3F/Carhart (high-DOX HXZ vs C4F ΔmaxSR² = −0.091, p = 0.010; low-DOX = −0.013, p = 0.823). **34–54% of firms' total capital is off-balance-sheet.**
- **International:** Watanabe, Xu, Yao & Yu (2013), JFE 108:529–563 — abstract verified (<https://www.semanticscholar.org/paper/The-Asset-Growth-Effect%3A-Insights-from-Equity-Watanabe-Xu/5e515c94c4e972e85e37bc7adb4fe54f3a8c771a>): the negative effect is **"stronger in more developed capital markets and markets where stocks are more efficiently priced, but… unrelated to country characteristics representing limits to arbitrage, investor protection, and accounting quality."** Per-country magnitudes **UNVERIFIED**. A Pacific-Basin set gives pooled **D10−D1 = −0.64%/month (t = −3.94)**, US **−1.96%/month (t = −9.54)**, US 3-factor alpha **−1.20% (t = −4.88)**; annualised PACAP **−7.42%** vs US **−21.14%**; Taiwan the only insignificant market (**−0.16%, t = −0.28**).

**6. Caveats.** The asset-growth effect is (i) partly a small-cap/microcap effect, (ii) absent in low-idiosyncratic-volatility stocks, (iii) regime-dependent (high-overextrapolation periods only), (iv) sensitive to which growth component you use (inventory and receivables dominate), and (v) built on a definition of "investment" that ignores 34–54% of capital. **Morgan Stanley (5 Nov 2025) explicitly walks it back:** *"Asset growth is a blunt tool that predicts abnormal returns… ultimately a poor proxy for investment."*

**7. XBRL computability.** Good. `us-gaap:Assets`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:InventoryNet`, `us-gaap:AccountsReceivableNetCurrent`, `us-gaap:PropertyPlantAndEquipmentNet`/`Gross`, `us-gaap:IntangibleAssetsNetExcludingGoodwill`, `us-gaap:Goodwill`, `us-gaap:Revenues`. **Idiosyncratic volatility and WACC are NOT in XBRL** — the biggest replicability gap for the IVOL-conditioned version. Market cap requires an external price feed.

---

## 4.3 "Capital discipline" studies

**1. Definition.** Economic profit `EP = Invested Capital × (ROIC − WACC)`; plus process measures of capital-allocation quality.

**2. Effect sizes (retrieved).**
- **McKinsey, *The strategic yardstick you can't afford to ignore*, McKinsey on Finance No. 49, Winter 2014** (<https://www.mckinsey.com/~/media/mckinsey/dotcom/client_service/corporate%20finance/mof/issue%2049/mof49_strategicyardstick.ashx>): **2,875 large nonfinancial companies, 2007–11, 128 industries**, flat 9% global cost of capital. Top EP quintile **+$677bn**; middle three quintiles **+$29.4bn** (~10% of total); bottom quintile **−$411bn** — the top creates ~**70×** the middle. **Industry explains 40% of a company's EP, company effect 60%.** ROIC converges only partially while valuation multiples converge fully; top-quintile 1997–2001 firms invested **2.6×** more fresh capital over the next decade; **~half of top-quintile firms dropped out within 10 years and one in eight fell to the bottom**; **79% of middle-quintile firms stayed middle, only 11% reached the top**; of 37 breakout firms, 33 were in improving industries and **75% of their EP increase came from industry improvement**.
- **McKinsey on Finance No. 86, July 2024** (<https://www.mckinsey.com/~/media/mckinsey/business%20functions/strategy%20and%20corporate%20finance/our%20insights/mckinsey%20on%20finance%20number%2086/mckinsey-on-finance-number-86.pdf>) — resource-allocation survey fielded 3–13 Oct 2023, **n = 617 executives** at firms with revenue ≥$500m: only ~half say budgets align with strategy; 53% fully fund priorities; an influential FP&A/strategy leader → **1.8×** more likely to report revenue-growth outperformance and **1.9×** return-on-capital outperformance (51% vs 28%; 51% vs 36%); in-year reallocation incentive → 1.8×/1.7×; only 28% almost always rank their top 10–30 programmes on financial metrics (those who do: 55%/50% outperform vs 41%/35%); plans approved in ≤3 months → 50% vs 33% on return on capital; budgets in ≤2 months → 51% vs 26%. **"Big moves" benchmark: shift >60% of annual capex to different business units every ten years.** **All self-reported outperformance — cannot establish causality.**
- **Morgan Stanley, *Capital Allocation: Results, Analysis, and Assessment*, 5 Nov 2025** (<https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf>): valuation quotient averaged **10% over 1970–2024**; only **"38 of the 5,760 observations, or less than 1 percent"** exceeded the optimal reallocation threshold (**98–99% of firms reallocate too little**); capex attributable to investment = **38%** of total capex; debt/total capital **15% (2024)** vs **26%** long-run average; **$2.1T** excess cash; net working capital fell from ~30% of assets (1970s) to **<10%**; Morningstar Capital Allocation Rating covers ~**1,850** US companies (**16% exemplary / 78% standard / 5% poor**, Sept 2025). Market-reaction ranking (positive → negative): spinoffs/divestitures, dividend initiations, buybacks, debt prepayments, capex; R&D value-neutral; **M&A value-neutral for the buyer**; equity issuance negative. M&A synergies: **36%** hit cost-synergy targets, only **17%** beat revenue synergies. R&D: ~1/3 of firms underspend vs optimal, ~**2/3 overspend**, 5% near optimal.

**3. Critical sign tension.** The **verified academic evidence says aggressive reinvestors earn LOWER returns on average** (the investment/asset-growth factor). That is the **opposite** of a naive "disciplined capital allocators earn more" reading. A "capital discipline" screen must therefore be built as **low asset growth / high ROIC−WACC spread**, not as high reinvestment.

**4. UNVERIFIED — explicit.** **No peer-reviewed paper titled "Capital allocation and the cross-section of stock returns" appears to exist**; the delegated pass searched and did not find one — **do not cite such a title.** Also **UNVERIFIED: any return spread for the Morningstar Capital Allocation Rating.**

**5. XBRL computability.** Dividends/buybacks vs `NetCashProvidedByUsedInOperatingActivities` and `PaymentsToAcquirePropertyPlantAndEquipment`; leverage from `LongTermDebt*` + short-term borrowings + lease liabilities ÷ `StockholdersEquity`; M&A from `PaymentsToAcquireBusinessesNetOfCashAcquired`; divestitures from `ProceedsFromDivestitureOfBusinesses`. **Segment-level reallocation requires the `us-gaap:StatementBusinessSegmentsAxis` dimension (patchy coverage).**

---

# PART 5 — POST-PUBLICATION DECAY (cross-cutting)

**McLean & Pontiff (2016), *Does Academic Research Destroy Stock Return Predictability?*, JF 71(1):5–32.** Full text blocked (Wiley); verified via the **CFA Institute Research Foundation digest** (<https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary>). **97 predictors**, three periods. Verbatim: **"portfolio returns are 26 percentage points (pps) lower when a new study is commenced after the completion of the original study… and 58 pps lower after publication."** The extra 32 pp is attributed to informed trading. Average monthly return: in-sample **0.582%** → out-of-sample pre-publication **0.402%** → post-publication **0.264%**. Noisy/long-horizon anomalies (e.g. value/growth) decay slowly and "can take decades to play out." **UNVERIFIED:** whether the 26/58 figures are percentages of the in-sample return or percentage points — the digest says pps; the original wording was not retrievable.

**Anomaly-specific decay evidence:** (i) HXZ *Replicating Anomalies* — magnitudes "often much lower than originally reported," CGS asset growth named explicitly; (ii) Lipson–Mortal–Schill — the asset-growth effect is real but **zero in low-IVOL stocks** (§4.2); (iii) Cooper–Gulen–Ion (2024) — the FF5/HXZ factor payoff exists **only in high-overextrapolation periods**; (iv) repurchase anomaly — Fu & Huang (2016) and Lee–Park–Pearson find the long-run drift **vanishes after ~2002**.

**Tier summary:** McLean–Pontiff decay = **(a) robust**; CGS/capex anomaly existence = **(a)**; CGS/capex original magnitude = **(c) contested**; factor-model attribution = **(b)/(c)**; TWX capex effect = **(b)**, single-paper US with an in-sample regime failure (1984–89).

---

# PART 6 — CONSOLIDATED XBRL / iXBRL COMPUTABILITY

**Authority.** Tag names are US-GAAP Financial Reporting Taxonomy concepts. The 2024 taxonomy schema was retrieved (<https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd>, HTTP 200) and confirms the `us-gaap` namespace and element declarations (e.g. `us-gaap_Goodwill`, `us-gaap_OperatingIncomeLoss`, `us-gaap_Revenues`). **SEC's machine APIs returned HTTP 403 in this session** (`data.sec.gov/api/xbrl/companyconcept/...` → "Undeclared Automated Tool"; `www.sec.gov/edgar/sec-api-documentation` → rate threshold). A delegated pass reports confirming four tags live against the SEC XBRL API with a declared User-Agent — **treat entity-level tag availability as requiring per-filing validation.**

| Marker | Primary XBRL tags | XBRL-only? |
|---|---|---|
| Gross buyback yield | `us-gaap:PaymentsForRepurchaseOfCommonStock` | Needs market cap |
| Net share reduction / SBC dilution | `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding`, `dei:EntityCommonStockSharesOutstanding`, `us-gaap:ShareBasedCompensation` | **Yes** |
| Net payout yield | + `us-gaap:PaymentsOfDividendsCommonStock` | Needs market cap |
| Total payout yield | `us-gaap:PaymentsForRepurchaseOfCommonStock` + `us-gaap:PaymentsOfDividendsCommonStock` | Needs market cap |
| Dividend yield / payout ratio | `us-gaap:CommonStockDividendsPerShareDeclared`, `us-gaap:PaymentsOfDividendsCommonStock`, `us-gaap:NetIncomeLoss`, `us-gaap:EarningsPerShareBasic`/`Diluted` | Ratio yes; yield no |
| Dividend streak / aristocrat gates | `us-gaap:CommonStockDividendsPerShareDeclared` (multi-year), payout ≤100%, yield ≤10% | Streak needs pre-XBRL back-fill |
| Payout sustainability / coverage | `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:ProceedsFromIssuanceOfLongTermDebt`, `us-gaap:LongTermDebtNoncurrent`, `us-gaap:RetainedEarningsAccumulatedDeficit`, `us-gaap:StockholdersEquity` | **Yes** |
| Capex / asset growth | `us-gaap:Assets`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:InventoryNet`, `us-gaap:AccountsReceivableNetCurrent` | **Yes** |
| Acquisition intensity | `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`, `us-gaap:BusinessCombinationConsiderationTransferred1` | Yes, but **materiality-biased** |
| Goodwill build-up / impairment | `us-gaap:Goodwill`, `us-gaap:GoodwillImpairmentLoss`, `us-gaap:AssetImpairmentCharges`, `us-gaap:IntangibleAssetsNetExcludingGoodwill` | **Yes** |
| ROIC / EP | `us-gaap:OperatingIncomeLoss`, `us-gaap:IncomeTaxExpenseBenefit`, `us-gaap:Assets`, `us-gaap:StockholdersEquity`, `us-gaap:LongTermDebt*`, `us-gaap:CashAndCashEquivalentsAtCarryingValue` | Invested capital must be constructed; **WACC not available** |
| Buyback timing skill | — | **No — requires actual repurchase prices (Item 703)** |
| Announcement event studies | — | **No — event dates are not in XBRL** |

**Hard technical caveats for any XBRL pipeline:**
1. **Price is not in XBRL.** Every yield/payout-yield marker needs an external price or market-cap series. `dei:EntityCommonStockSharesOutstanding` × month-end close is the only XBRL-only route, and it is **point-in-time with a filing-date stamp, not period-end**.
2. **Goodwill and impairment are the only markers where XBRL is strictly superior** to Compustat-era proxies (§3.4).
3. **Interim cash-flow elements are year-to-date** — they must be **differenced, not summed**, to obtain quarterly flows.
4. **XBRL has a materiality floor.** Deal-level M&A screens built on XBRL tags will systematically miss small deals and are **biased toward large acquirers** — the population where the M&A evidence finds value destruction.
5. **Structured XBRL only begins ~2009–2011 for large filers.** Any 20-year dividend streak, long-horizon anomaly backtest, or pre-2002 repurchase tape requires pre-XBRL back-fill or a vendor file.
6. **FCF, invested capital, WACC and idiosyncratic volatility are not tags** and must be constructed; the construction choices materially change every marker built on them.

---

# PART 7 — UNVERIFIED REGISTER (what is missing, precisely)

1. **Agrawal/Jaffe/Mandelker (1992), Loughran/Vijh (1997), Rau/Vermaelen (1998), Moeller/Schlingemann/Stulz (2004, JFE)** — closed access, no open-access copy (Unpaywall-verified by DOI). **No effect size reported for them anywhere in this document.**
2. **Ikenberry/Lakonishok/Vermaelen (1995) sample N** — period (1980–1990) confirmed; number of announcements not confirmed.
3. **Brockman & Chung (2001)** and **Chan, Ikenberry & Lee (2007)** — citations verified; **effect sizes UNVERIFIED** (closed access, no retrievable abstract).
4. **Cooper, Gulen & Schill (2008)** — abstract verified; **original decile spread, t-statistic, 3-factor alpha and N UNVERIFIED** (Wiley + SSRN bot walls).
5. **Fama & French's own FF5 CMA return** — not retrieved; the 0.34% (t = 3.63) figure is HXZ's replication.
6. **Michaely/Thaler/Womack (1995) sample period and N** — not confirmed (the NBER PDF returned empty through the text proxy).
7. **Boehme & Sorescu (2002)** and **Liu/Szewczyk/Zantout (2008)** — the qualitative replication failures are quoted; **exact abnormal-return magnitudes UNVERIFIED**.
8. **Nissim & Ziv (2001)** t+1/t+2 coefficients, sample period and N, and **Grullon/Michaely/Benartzi/Thaler (2005)** coefficients — **UNVERIFIED** (bodies 403-blocked at Wiley/SSRN/Columbia).
9. **Fama & French (1988)** dividend-yield regression coefficients and R² — **UNVERIFIED**.
10. **Fama & French (2001)** payer proportions ("66.5% → 20.8%") — retrieved only via a secondary CFA digest, not the primary paper.
11. **The specific claim that `Goodwill/Assets` predicts lower future returns** — **NOT VERIFIED**; the relevant paper (Liu, Yin & Zheng, *J. Financial Markets* 52:100561) is closed access with a 404 conference copy. **Do not cite it.**
12. **No paper titled "Capital allocation and the cross-section of stock returns" appears to exist** — do not cite such a title.
13. **Any return spread for the Morningstar Capital Allocation Rating** — **UNVERIFIED**.
14. **S&P DJI primary methodology document** — spglobal.com 403s automated retrieval; arithmetic retrieved second-hand via an SSGA PDF.
15. **Watanabe/Xu/Yao/Yu (2013)** per-country magnitudes — abstract only; HKU full text bot-walled.
16. **King, Dalton, Daily & Covin (2004)** numeric effect size — abstract only.
17. **Lang/Stulz/Walkling (1991)**, **Harford (1999)**, **Haleblian et al. (2009)**, **Andrade/Mitchell/Stafford (2001)** — **not retrievable at all**.
18. **SEC XBRL element-level verification** — `data.sec.gov` returned HTTP 403 without a declared User-Agent; tag names rest on the FASB taxonomy schema.
19. **Post-2003 out-of-sample replication of the payout-yield factor** — not found.

---

# PART 8 — SOURCES FETCHED

### 8A. Retrieved directly in this session (full text read)
1. <https://r.jina.ai/https://www.nber.org/system/files/working_papers/w10651/revisions/w10651.rev0.pdf> — Boudoukh, Michaely, Richardson & Roberts, NBER WP 10651.
2. <https://r.jina.ai/https://www.nber.org/system/files/working_papers/w9951/w9951.pdf> — Titman, Wei & Xie, NBER WP 9951.
3. <https://www.nber.org/papers/w9951> and <https://www.nber.org/papers/w9523> and <https://www.nber.org/papers/w10773> and <https://dev.nber.org/papers/w10200> and <https://www.nber.org/papers/w10651> — NBER abstract pages.
4. <http://www2.nber.org/digest/aug03/w9523.html> — NBER Digest, "Big Firms Lose Value in Acquisitions."
5. <https://r.jina.ai/https://forum.valuepickr.com/uploads/short-url/c14zEZZD6bUcbyhVMn36kdlhXwT.pdf> — Mauboussin & Callahan, *Measuring the Moat*, Morgan Stanley, 15 Oct 2024.
6. <https://rpc.cfainstitute.org/research/cfa-digest/2020/05/dig-v5-n5-4> — CFA Institute review of Hartzmark & Solomon, *The Dividend Disconnect*.
7. <https://www.msci.com/research-and-insights/blog-post/beware-high-dividend-yield-traps> — MSCI.
8. <https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd> — FASB US GAAP taxonomy schema.

### 8B. Retrieved by the delegated capital-discipline pass (dossier in workspace)
9. <https://www.nber.org/system/files/working_papers/w9951/w9951.pdf> · 10. <https://www.strictlybiz.co.nz/wp-content/uploads/2022/12/themathofvalueandgrowth_us.pdf> · 11. <https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf> · 12. <https://www.numerade.com/notes/directory/school/4677/courses/283359/files/4717857> · 13. <https://econpapers.repec.org/article/blajacrfn/v_3a26_3ay_3a2014_3ai_3a4_3ap_3a48-74.htm> · 14. <http://faculty.bus.olemiss.edu/rvanness/speakers/2009-2010/Mortal-Asset%20Growth%20Effect.pdf> · 15. <https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/on-the-scope-and-drivers-of-the-asset-growth-effect/B8CFCF68A82E273E979221EF26A77096> · 16. <https://econpapers.repec.org/article/blajfinan/v_3a63_3ay_3a2008_3ai_3a4_3ap_3a1609-1651.htm> · 17. <https://www.cass.city.ac.uk/__data/assets/pdf_file/0011/76916/Yu-141-REVISED.pdf> · 18. <https://www.semanticscholar.org/paper/The-Asset-Growth-Effect%3A-Insights-from-Equity-Watanabe-Xu/5e515c94c4e972e85e37bc7adb4fe54f3a8c771a> · 19. <https://www.nber.org/system/files/working_papers/w18435/w18435.pdf> · 20. <https://www.nber.org/system/files/working_papers/w23394/w23394.pdf> · 21. <https://fairmodel.econ.yale.edu/ec439/ansh.pdf> · 22. <https://www.mckinsey.com/~/media/mckinsey/dotcom/client_service/corporate%20finance/mof/issue%2049/mof49_strategicyardstick.ashx> · 23. <https://www.mckinsey.com/~/media/mckinsey/business%20functions/strategy%20and%20corporate%20finance/our%20insights/mckinsey%20on%20finance%20number%2086/mckinsey-on-finance-number-86.pdf> · 24. <https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary>

### 8C. Confirmed NOT retrievable (do not mistake for sources)
Wiley/JF and JACF DOIs (bot check): `10.1111/jacf.12090`, `10.1111/j.1540-6261.2008.01370.x`, `10.1111/jofi.12365`. SSRN (bot check). Columbia GSB (redirect to homepage). ScienceDirect (403). `academic.oup.com/rfs/article-abstract/22/4/1693/1567717` (403). SEC `data.sec.gov` and `www.sec.gov/edgar/sec-api-documentation` (403). `hub.hku.hk`, `spglobal.com`, `fa-mag`, `studocu`, Tulane/TTU mirrors (bot check / 404).
