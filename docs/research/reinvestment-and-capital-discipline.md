# Reinvestment vs. Returning Cash / Capital-Discipline Markers — Source-Grounded Dossier

**Method note.** Every number below is quoted from a URL I actually retrieved with `web_fetch` (listed in
SOURCES FETCHED). Where a number could not be retrieved from a source I fetched, it is marked
**UNVERIFIED** with a statement of exactly what is missing. Numbers quoted from a *secondary* source that
itself reproduces a primary result are labelled as such. Where a claim is my own arithmetic derivation from
a retrieved definition, it is labelled **[derivation]**.

Confidence tiers used throughout:
- **(a) robust / replicated** — survived an independent replication with different portfolio-construction
  choices.
- **(b) single-paper** — original finding, not independently replicated in a source I could retrieve.
- **(c) contested / decayed** — a fetched source documents that the effect weakens, is specification-
  dependent, or fails out-of-sample / post-publication.

---

## A. The ROIC × reinvestment-rate framing of value creation, and growth destroying value when ROIC < WACC

### A1. Definitions and formulas

**Value-creation spread (economic profit / EVA).**
`Value creation spread = ROIC − WACC`; `Economic profit = Invested Capital × (ROIC − WACC)`.
Verified wording from Mauboussin & Callahan (Morgan Stanley Counterpoint Global, *The Math of Value and
Growth*, June 9, 2020):
> "A company creates value when its investments earn a return higher than the opportunity cost of capital."
> "Growth destroys value if investments earn a return below the cost of capital."
> "Growth is of no economic significance if a company's returns are equivalent to the firm's cost of capital."
Source: <https://www.strictlybiz.co.nz/wp-content/uploads/2022/12/themathofvalueandgrowth_us.pdf>

**Return on incremental invested capital (ROIIC).** Definition quoted verbatim:
> "ROIIC is defined as the change in NOPAT from this year to next year divided by this year's investment.
> For example, if NOPAT grows by $10 next year and the company invests $50 this year, the ROIIC is 20
> percent (10/50). Note that it does not matter if the investment is expensed or capitalized, save for some
> effect on taxes."
Same source.

**Reinvestment rate.** Mauboussin's document does not print the ratio as a single line, so:
**[derivation]** From `ROIIC = ΔNOPAT / Investment` and `g = ΔNOPAT / NOPAT`:
`Reinvestment rate = Investment / NOPAT = g / ROIIC`, hence `g = Reinvestment rate × ROIIC`. This identity
is a rearrangement of the definition quoted above, not a verbatim quotation.

**Sustainable value creation (the moat framing).** Mauboussin, Callahan & Majd (Credit Suisse Global
Financial Strategies, *Measuring the Moat*, November 1, 2016), Executive Summary, verbatim:
> "Sustainable value creation has two dimensions: the magnitude of the spread between a company's return
> on invested capital and the cost of capital and how long it can maintain a positive spread."
Retrieved from: <https://www.numerade.com/notes/directory/school/4677/courses/283359/files/4717857>
(the Credit Suisse report text as hosted there; the underlying report is a Credit Suisse publication).

### A2. Originating study / author / year

- Michael J. Mauboussin & Dan Callahan, **"Capital Allocation: Evidence, Analytical Methods, and Assessment
  Guidance," *Journal of Applied Corporate Finance* 26(4), 2014, pp. 48–74**; DOI 10.1111/jacf.12090.
  Publication metadata and full abstract verified at EconPapers:
  <https://econpapers.repec.org/article/blajacrfn/v_3a26_3ay_3a2014_3ai_3a4_3ap_3a48-74.htm>
  (The Wiley full text at <https://onlinelibrary.wiley.com/doi/10.1111/jacf.12090> returned a bot-check
  page, and the Wiley PDF was not retrievable — see UNVERIFIED note below.)
- Mauboussin, Callahan & Majd, *Measuring the Moat*, Credit Suisse, November 1, 2016 (originally
  2013; the July 2013 version is also in circulation).
- Mauboussin & Callahan, *The Math of Value and Growth*, Morgan Stanley Counterpoint Global
  (Consilient Observer), June 9, 2020.
- Mauboussin & Callahan, *Capital Allocation: Results, Analysis, and Assessment*, Morgan Stanley
  Counterpoint Global (Consilient Observer), November 5, 2025 — the updated successor to the 2014 JACF article.

### A3. Sample

- **JACF 2014 article:** verified from the abstract — the authors "examine the main sources and uses of
  capital by **the largest 1,500 U.S. companies during the last 30 years**," allocating capital across
  "seven important alternatives" (M&A, capex, R&D, dividends, buybacks, etc.).
- **Measured the Moat 2016:** conceptual/strategy framework paper; no single-panel regression sample.
- ***The Math of Value and Growth* (2020):** a calibrated DCF, not an empirical cross-section. Inputs/quotes:
  "NOPAT growth 10% per annum," "ROIIC of 20 percent," "cost of equity capital to be 6.7 percent"
  (risk-free 1.5% + ERP 5.2% as of February 1, 2020), "15 years" explicit forecast then perpetuity,
  "all equity financing."
- ***Capital Allocation* (2025):** Compustat/FactSet U.S. universe, "we extend most of the analysis back to
  1970, update the data through 2024, and discuss results for the first half of 2025."

### A4. Reported effect sizes (exact numbers as printed)

*The Math of Value and Growth* (2020), verbatim figures:
- Commodity P/E multiple = 1 / cost of equity. Baseline: "if the cost of equity is 8 percent, the commodity
  P/E multiple is 12.5 (1/.08 = 12.5)."
- "the commodity P/E multiple got as low as **5.1 in 1981** … and the multiple as of **June 1, 2020 is 16.7**.
  The baseline multiple … has **averaged 10.7 for the full period**."
- "The actual P/E multiple for the S&P 500 has been about **35 percent higher** than the commodity P/E
  multiple since 1961, with most observations between **20 and 65 percent higher**."
- Baseline model output: `NOPAT growth 10% / ROIIC 20% / cost of capital 6.7% → P/E 32.3`.
- Raise growth: `NOPAT growth 15% / ROIIC 20% / CoC 6.7% → P/E 52.2`.
- Growth cut: `10% → 7%` gives next-year earnings `$110 → $107` (−2.7%) but P/E `32.3 → 24.9` (−22.9%).
- Growth cut: `15% → 12%` gives `$115 → $112` (−2.6%) but P/E `52.2 → 39.0` (−25.3%).
- **The ROIC < WACC result is stated qualitatively and shown in Exhibit 4, not as a single number:**
  "an ROIIC below the cost of capital of 6.7 percent yields a P/E multiple below the commodity multiple" —
  and the exhibit's marked commodity P/E is "P/E: 14.9x, ROIC: 6.7%."
- Conclusion caveat, verbatim: "ROIICs eventually drift lower as a consequence of factors such as competition,
  maturation, obsolescence, and disruption."

*Capital Allocation* (2025), verbatim figures:
- Reallocation inertia: "only **38 of the 5,760 observations, or less than 1 percent**, were above that
  threshold" (the optimal degree of capital reallocation across business units); "Too Little Reallocation
  (98–99% of companies)."
- "The valuation quotient for U.S. companies **averaged 10 percent from 1970 through 2024**."
- "capital expenditures attributable to investment were **38 percent of total capital expenditures** over the
  full period" (the rest is maintenance).
- Debt-to-total capital: "**15 percent** [in 2024] versus the long-term average of **26 percent**."
- "companies in the universe we measure hold nearly **$2.1 trillion in excess cash**"; "one-quarter of total
  cash and short-term investments is held by 10 companies, one-third by the top 21, and one-half by 67 firms."
- Net working capital: "nearly **30 percent of assets in the 1970s** and … **less than 10 percent of assets
  today**"; NWC investment "averaged just **0.6 percent of sales**."
- Cash conversion cycle 2024 medians: communication services **30 days** (lowest), healthcare **113 days**
  (highest); examples "**−33 days for Amazon** and **45 days for Macy's**."
- Buyback/dividend facts: "The standard deviation of the growth rate of dividends from 1970 to 2024 is
  **around one-sixth** that of buybacks." "Five years prior to the enactment of Rule 10b-18, the payout via
  buybacks was **five percent of earnings**. Five years after, it was **more than 40 percent**."
  "The gross total shareholder yield went from **27 percent of the cost of equity in 1970 to 38 percent in 2024**."
- Buyback golden rule (quoted by the authors as a rule, not an empirical estimate): "A company should
  repurchase its shares only when its stock is trading below its expected value and when no better
  investment opportunities are available."

*Capital Allocation* (2025) on the asset-growth factor itself, verbatim:
> "Asset growth is a blunt tool that predicts abnormal returns. Specifically, companies with high asset
> growth earn lower TSRs than companies with low asset growth. … But asset growth is ultimately a poor
> proxy for investment and neglects the rise of investments in internally-generated intangible assets."
- Morningstar Capital Allocation Rating coverage: "roughly **1,850 public companies in the U.S.**"; as of
  September 2025 "**16 percent** score high enough … to be deemed exemplary, **78 percent** are standard,
  and **5 percent** rate low enough to be considered poor."

### A5. Out-of-sample / post-publication status

- The 2014 JACF article is a **methodology + descriptive-statistics** contribution, not a return-predictive
  anomaly, so there is no "decay" test to run on it in the anomaly sense. The 2025 Morgan Stanley report is
  the authors' own update and confirms the descriptive facts (valuation quotient ~10%, 1970–2024).
- The one asset-pricing claim in the family — that asset growth predicts returns — **is explicitly walked
  back in degree** by the 2025 update ("a blunt tool," "a poor proxy for investment"). This is tier **(c)**
  as a *practitioner* claim even though the underlying empirical relation is real (see Section B).
- **UNVERIFIED:** the exact numerical tables inside the 2014 JACF article (e.g., dollar amounts allocated to
  each of the seven uses of capital by the top 1,500 U.S. companies). The Wiley version is behind a bot wall
  and a paywall; only the abstract was retrievable.

### A6. Practical caveats

- **ROIC is definition-sensitive.** Numerator (NOPAT vs. reported operating income) and denominator
  (invested capital net vs. gross of cash; including vs. excluding goodwill, operating leases, capitalized
  R&D) can move ROIC by hundreds of basis points for the same firm. HOLT-style ROIC uses a cash-flow-based
  invested capital and a proprietary cost of capital; Mauboussin's own numbers above are internally
  consistent illustrations, not firm-level estimates.
- **Internally-generated intangibles are expensed**, so ROIC for R&D/SG&A-heavy firms is biased *down* and
  the balance sheet looks smaller. Mauboussin flags this directly (2025 report; and Enache & Srivastava,
  *Management Science* 2018, cited at endnote 3 of *The Math of Value and Growth*).
- **ROIIC is a slope on a noisy series.** A single-year ΔNOPAT/Investment ratio is dominated by timing;
  Mauboussin's own model needs a 15-year horizon before the perpetuity term.
- **The ROIC < WACC rule is a long-run statement.** Over finite windows, growth with ROIC slightly below
  WACC can still raise value per share via optionality and scale; the rule bites over long horizons.

### A7. Computability from XBRL / iXBRL

Fundamentals needed, with concrete tags (SEC `us-gaap` taxonomy):

| Input | XBRL tag(s) |
|---|---|
| Operating profit (EBIT) | `us-gaap:OperatingIncomeLoss` |
| Tax rate | `us-gaap:IncomeTaxExpenseBenefit` ÷ `us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` |
| NOPAT | EBIT × (1 − effective tax rate) — **[derivation]** |
| Book equity | `us-gaap:StockholdersEquity`, `us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| Debt | `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebtCurrent`, `us-gaap:LongTermDebt`, `us-gaap:ShortTermBorrowings`, `us-gaap:OperatingLeaseLiabilityNoncurrent`, `us-gaap:OperatingLeaseLiabilityCurrent` |
| Cash (to net out of invested capital) | `us-gaap:CashAndCashEquivalentsAtCarryingValue`, `us-gaap:ShortTermInvestments` |
| Total assets (for asset-growth and asset-turn proxies) | `us-gaap:Assets` |
| R&D (to capitalize, or to report ROIC "as reported") | `us-gaap:ResearchAndDevelopmentExpense` |
| SG&A (the 30% organizational-capital convention) | `us-gaap:SellingGeneralAndAdministrativeExpense` |
| Capex, maintenance vs. growth | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:PaymentsToAcquireProductiveAssets`, `us-gaap:DepreciationDepletionAndAmortization` |
| Working capital | `us-gaap:AssetsCurrent`, `us-gaap:LiabilitiesCurrent`, `us-gaap:InventoryNet`, `us-gaap:AccountsReceivableNetCurrent` |
| Intangibles / goodwill | `us-gaap:Goodwill`, `us-gaap:IntangibleAssetsNetExcludingGoodwill` |
| Market cap (for WACC weights and P/E) | `dei:EntityCommonStockSharesOutstanding` × close (price is *not* in XBRL; use a price feed), or `us-gaap:CommonStockSharesOutstanding` |
| Payout | `us-gaap:PaymentsOfDividendsCommonStock`, `us-gaap:PaymentsForRepurchaseOfCommonStock` |
| Equity issuance (dilution check) | `us-gaap:ProceedsFromIssuanceOfCommonStock`, `us-gaap:ShareBasedCompensation` |

Practical route: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (all tags for one filer) and
`https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/OperatingIncomeLoss.json` (one tag,
all periods). Both are free JSON with no key. **WACC itself is not in XBRL** — the risk-free rate, ERP and
beta must be supplied externally, which is the single biggest replicability gap in this marker.

---

## B. Capital expenditure, asset growth, and the investment factor

### B1. Titman, Wei & Xie (2004) — "Capital Investments and Stock Returns"

**Marker.** Abnormal capital investment `CI`, i.e., the *increase* in capex scaled by sales relative to the
firm's own recent average. Formula quoted verbatim from the paper (eq. 1):

> `CI_{t-1} = (CE_{t-1} − (CE_{t-2} + CE_{t-3} + CE_{t-4})/3) / CE` — rendered in the source as
> "`CI_{t-1} = CE_{t-1} − 1/3(CE_{t-2}+CE_{t-3}+CE_{t-4})`" with `CE_{t-1}` = "a firm's capital expenditures
> (COMPUSTAT data item 128) scaled by its sales in year t-1."

A `CI` of zero means the formation year's investment equals the prior three-year average; positive means
unusually high investment.

**Origin.** Sheridan Titman, K.C. John Wei, Feixue Xie, "Capital Investments and Stock Returns,"
*Journal of Financial and Quantitative Analysis* 39(4), 2004, 677–700; NBER Working Paper No. 9951
(September 2003). Retrieved: <https://www.nber.org/system/files/working_papers/w9951/w9951.pdf>

**Sample.** All domestic primary NYSE/Amex/Nasdaq stocks, excluding closed-end funds, trusts, ADRs, REITs,
units of beneficial interest, and financials. "the sample period for financial data covers from **1969 to
1995**, the test period or the sample period for stock returns covers from **July 1973 to June 1996**."
Initial sample "58,880 industrial firm-years (an average of 2,560 firms a year)"; final sample
"an average of **1,635 firms a year**." Screens: sales ≥ US$10 million, non-negative book equity,
two years on COMPUSTAT.

**Reported effect sizes (all from the paper's tables):**
- Table 1, Panel A — value-weighted *characteristic-benchmark-adjusted* monthly returns by CI quintile:
  Lowest **0.042%**, 2 **0.083%** (sig.), 3 **0.055%**, 4 **−0.083%** (sig.), Highest **−0.127%** (sig.).
  **CI-spread (long lowest two, short highest two): mean excess return 0.168% per month
  (median 0.119%), "significantly different from zero with a p-value of less than 0.01."**
- Table 1, Panel B — CI-spread by year after formation (benchmark-adjusted, annualised):
  Year 1 **2.02%** (t = 2.86), Year 2 **2.26%** (t = 2.88), Year 3 **1.91%** (t = 2.46),
  Year 4 **1.85%** (t = 2.10), Year 5 **1.64%** (t = 1.81),
  **five-year cumulative 8.10% (t = 2.55)**.
- Table 2 — Carhart four-factor intercepts (`FF alpha`):
  Lowest quintile −0.012%, 2 **+0.119%**, 3 +0.058%, 4 **−0.103%**, Highest **−0.173%**;
  **CI-spread FF alpha +0.192% per month** (median +0.202%).
  Sub-periods: non-takeover years CI-spread **+0.277%** mean / **+0.312%** alpha;
  takeover years (1984–1989) **−0.144%** mean / **−0.124%** alpha; difference **+0.421%** /
  **+0.436%** (both significant). The abstract states the relation "is shown to be significant only in
  time periods when hostile takeovers were less prevalent."
- Investment-discretion conditioning (abstract + Tables 4–5): the effect is *stronger* for firms with
  "greater investment discretion, i.e., firms with higher cash flows and lower debt ratios."
  High-CF CI-spread **+0.227%** mean / **+0.256%** alpha vs. low-CF **+0.078%** / **+0.059%**
  (H−L difference **+0.149%** / **+0.197%**, alpha significant at 10%).
  Low-DA (low leverage) CI-spread **+0.225%** / **+0.286%** vs. high-DA **+0.099%** / **+0.080%**
  (H−L **−0.126%** / **−0.206%**).
- Table 6 — Fama–MacBeth coefficients on CI: **−0.79% (t = −2.80)** in Model 1 all years;
  **−1.06% (t = −2.96)** in non-takeover years; **−0.02 (t = −0.06)** in takeover years.
- Table 3 — share of the effect around earnings announcements: year-1 announcement return on the CI-spread
  **0.792%** vs. annual return **3.330%**, i.e. **ratio 23.78%** (rising to 16.64% by year 5 for
  non-takeover years).
- Robustness (abstract): "the negative abnormal capital investment/return relation is independent of the
  previously documented long-term return reversal and secondary equity issue anomalies."

**Out-of-sample / post-publication.** The paper itself shows the effect **vanishes in 1984–1989** (the
takeover era), which is an in-sample regime failure. Independent post-publication evidence:
- Lipson, Mortal & Schill relate the *capex-based* measures to a narrower, size-concentrated effect:
  "we also demonstrate that the explanatory power of capital expenditures is **restricted to smaller
  firms**" (Unraveling the Asset Growth Effect, Sept 2009; JFQA-published version is "On the Scope and
  Drivers of the Asset Growth Effect"). Retrieved:
  <http://faculty.bus.olemiss.edu/rvanness/speakers/2009-2010/Mortal-Asset%20Growth%20Effect.pdf>
- Hou, Xue & Zhang's large replication documents that "the **Cooper-Gulen-Schill (2008) asset growth**"
  anomaly is among those whose "magnitudes are often much lower than originally reported" once
  microcaps are alleviated with NYSE breakpoints and value weights (sample **January 1967 – December 2014**;
  447 anomalies; 286 / 64% insignificant at 5%; 380 / 85% insignificant at t = 3).
  Retrieved: <https://www.nber.org/system/files/working_papers/w23394/w23394.pdf>
Tier: **(b) single-paper** for the 2004 US result; **(c)** for its modern-magnitude claims.

### B2. Cooper, Gulen & Schill (2008) — "Asset Growth and the Cross-Section of Stock Returns"

**Marker.** Total asset growth `AG_t = (TotalAssets_{t-1} − TotalAssets_{t-2}) / TotalAssets_{t-2}`
(definition quoted from the PACAP replication: "AG_t = (Total Assets_{t−1} − Total Assets_{t−2}) /
Total Assets_{t−2}", "Total assets are … Data Item 6 in Compustat for the U.S. market").

**Origin.** Michael J. Cooper, Huseyin Gulen, Michael J. Schill, *Journal of Finance* 63(4), 2008,
1609–1651; DOI 10.1111/j.1540-6261.2008.01370.x. SSRN working-paper version: 10.2139/ssrn.760967.

**Sample.** **UNVERIFIED** as an exact N and firm-year count: I could not retrieve the full text (Wiley
paywall + bot wall; SSRN bot wall). The published abstract is retrievable and states only that the test is
of "the cross-sectional relation between firm asset growth and subsequent stock returns" in U.S. stocks.
Verified abstract text (EconPapers mirror):
> "Asset growth rates are strong predictors of future abnormal returns. Asset growth retains its forecasting
> ability even on large capitalization stocks. When we compare asset growth rates with the previously
> documented determinants of the cross-section of returns (i.e., book-to-market ratios, firm capitalization,
> lagged returns, accruals, and other growth measures), we find that a firm's annual asset growth rate
> emerges as an economically and statistically significant predictor of the cross-section of U.S. stock returns."
Source: <https://econpapers.repec.org/article/blajfinan/v_3a63_3ay_3a2008_3ai_3a4_3ap_3a1609-1651.htm>

**Reported effect sizes — what I could verify, and from where:**
- **Original decile spread and 3-factor alpha: UNVERIFIED.** The exact lowest-minus-highest decile monthly
  return, t-statistic and three-factor alpha printed in CGS Table III could not be retrieved from any
  source I fetched. The paper is paywalled and no open PDF was reachable.
- **Verified, from a peer-reviewed paper that replicates CGS (Chen, Yao, Yu & Zhang, "Asset Growth and Stock
  Returns: Evidence from the Pacific-Basin Markets," April 2008), verbatim:**
  > "Cooper, Gulen, and Schill (2008, hereafter CGS) … show that in the U.S. market during the period from
  > **1968 to 2003**, firms ranked in the top decile of asset growth underperform firms ranked in the bottom
  > decile by **more than 20% in stock returns during the year after ranking**."
  Same paper's own US decile sort, **1981–2004**, equal-weighted:
  monthly D10−D1 **−1.96% (t = −9.54)**; three-factor alpha spread **−1.20% (t = −4.88)**;
  D1 monthly return 2.76% vs. D10 0.80%. Annualised US spread **−21.14% per year**.
  Retrieved: <https://www.cass.city.ac.uk/__data/assets/pdf_file/0011/76916/Yu-141-REVISED.pdf>
- **Verified, from Lipson, Mortal & Schill (2009) reproducing CGS quintiles over 1968–2006, verbatim:**
  > "if one sorted U.S. stocks based on the percentage change in total assets each June 30th from **1968 to
  > 2006** and sold short an equal-weighting of the top asset growth quintile (**mean subsequent annual
  > return of 6.9%**) and purchased an equal-weighting of the bottom asset growth quintile (**mean subsequent
  > return of 22.6%**), the zero investment portfolio would earn a **15.7% mean return**."
  Their own Table 1 Panel B/C: CGS low−high quintile spread **1.3% per month equal-weighted**
  (t = 8.416) and **0.7% per month value-weighted** (t = 4.113), 1968–2006.

**Does it hold out-of-sample? — Tier (c).**
- Lipson, Mortal & Schill show the effect is **specification-dependent**: the headline result "applies only
  to small firms" is an artifact of Fama–French's (2008) share-adjusted measure, which "dampens the asset
  growth effect by excluding growth that is associated with equity issues." Using total asset growth,
  "the asset growth effect is pervasive." But they also find **the effect is concentrated in
  high-idiosyncratic-volatility stocks**: "In general, there appears to be **no asset growth effect in firms
  with low idiosyncratic volatility**." Their IVOL-quintile low-minus-high spreads run
  1.02, 4.48, 6.67, 7.72, 7.47 (t-stats) from lowest to highest IVOL — significant only from IVOL 2 upward.
  Also: "the alpha on the low-minus-high growth portfolio return is unusually negative prior to the asset
  growth sorting date and unusually positive subsequently and then declines to zero" — a reversal pattern.
- Hou, Xue & Zhang list the CGS asset growth anomaly among those with "magnitudes … often much lower than
  originally reported" (1967–2014, NYSE breakpoints, value weights).
- Cooper, Gulen & Ion (2024, JFE 151:103746) show the pricing power of the asset-growth factor is
  **confined to high-overextrapolation regimes**: "in the subsample with below-median overextrapolation,
  the HXZ model does not perform significantly better than the Carhart (1997) four-factor model, and the
  FF5F model does not perform significantly better than the Fama and French (1993) model, or the
  Carhart (1997) model." Table 9: high-DOX Δ(maxSR²) vs C4F = **−0.091*** (p = 0.010); low-DOX
  Δ(maxSR²) vs C4F = **−0.013** (p = 0.823).
  Retrieved: <https://fairmodel.econ.yale.edu/ec439/ansh.pdf>

### B3. The investment factor in factor models

**Fama & French (2015) five-factor model, CMA (conservative-minus-aggressive investment).**
Definition: CMA is the difference between the average return on the two conservative-investment portfolios
(Small Conservative and Big Conservative) and the two aggressive-investment portfolios; "conservative" =
low growth in total assets; constructed 2×3 on size and investment (annual, June re-sort), NYSE breakpoints.

**Reported size (verified from a top-journal replication, 1967–2014):**
> "In the five-factor model, the average **RMW** and **CMA** returns are **0.27% (t = 2.58)** and
> **0.34% (t = 3.63)**, but their q-factor alphas are only 0.04% and 0.01% (t = 0.42 and 0.32), respectively."
Hour, Xue & Zhang, Replicating Anomalies, NBER WP 23394 (sample Jan 1967–Dec 2014; data "from Kenneth
French's Web site"). Retrieved: <https://www.nber.org/system/files/working_papers/w23394/w23394.pdf>
*(Note: this is a replication using the published data rather than the FF5 paper's own Table 1; I could
not retrieve the FF5 full text — the SSRN, Wiley and ScienceDirect versions were all blocked, and the
one open mirror I found returned 404.)* **UNVERIFIED:** the FF5 paper's own printed Table 1 CMA averages.

**Hou, Xue & Zhang q-factor model investment factor (`r_{I/A}`, "low-minus-high" investment-to-assets).**
- Sample **January 1972 – December 2011**: "E[r_{A/A}] **0.44% per month (t = 4.73)**";
  size factor 0.31% (t = 2.09); ROE factor 0.60% (t = 4.85). Construction: independent 2×3×3 sort on
  size, investment-to-assets and ROE; the investment factor is the average of the six low-`I/A` portfolios
  minus the average of the six high-`I/A` portfolios.
  Retrieved: <https://www.nber.org/system/files/working_papers/w18435/w18435.pdf>
- Extended sample **Jan 1967 – Dec 2014**: "the size, investment, and Roe factors in the q-factor model earn
  on average **0.32%, 0.43%, and 0.56% per month (t = 2.42, 5.08, and 5.24)**"; q-factor investment-factor
  alpha vs. the FF five-factor model **0.12% (t = 3.35)**.
- **Critical methodological point (Cooper, Gulen & Ion 2024):** "both papers use 'asset growth' (i.e., the
  year-on-year percentage change in the book value total assets) from Cooper et al. (2008) as a measure of
  investment." The pricing ability is **not** about physical investment:
  "The models using an investment factor based on more traditional measures of investment such as growth in
  PPE or growth in balance-sheet intangibles significantly underperform the original AG-based models," and
  "growth in inventory (INVT) and growth in accounts receivable (AREC) … contain the bulk of the pricing
  information." They further report "a large portion (**34% to 54%**) of firms' total capital is not on the
  balance sheet, and the correlation between AG and off-balance-sheet capital investment is quite low
  (around **0.16 to 0.30**)."

### B4. Critiques and international evidence

**Lipson, Mortal & Schill — "Unraveling the Asset Growth Effect" / "On the Scope and Drivers of the Asset
Growth Effect" (JFQA).**
- Sample: all nonfinancial firms on Compustat + CRSP, **1968–2006**, 468 monthly observations.
- Seven asset-growth measures compared: CGS, FF (Fama–French 2008), LSZ (Lyandres–Sun–Zhang), XING, TWX,
  PS (Polk–Sapienza), AGF (Anderson–Garcia-Feijóo).
- "The low-minus-high quintile return differences range from **0.7 to 1.3 percent a month for the
  equal-weighted portfolios and from 0.4 to 0.7 percent for the value-weighted portfolios**."
- Fama–MacBeth coefficients: "all of the measures of asset growth are significantly negatively related to
  returns with large t-statistics ranging from **−3.60 to −9.09**"; CGS coefficient **−0.012 (t = −9.09)**;
  PS −0.002 (−3.60); TWX −0.002 (−5.86).
- **Size interaction (CGS, equal-weighted, 1968–2006):** micro low−high **1.37% (t = 9.40)**;
  small **0.77% (t = 5.19)**; **big 0.67% (t = 4.04)**. Note: unlike Fama–French (2008), LMS find the
  big-stock effect survives *with the CGS measure*.
- **IVOL is the key conditioning variable:** low-IVOL quintile low−high spread **0.1% (t = 1.02)** —
  insignificant. This is their central "limits to arbitrage" result.
- Verdict: "the asset growth effect is pervasive and evidence to the contrary arises due to specification
  choices; that one measure of asset growth, the change in total assets, largely subsumes the explanatory
  power of the numerous other measures; and that the asset growth effect arises from firm growth itself and
  not from its sensitivity to an asset growth risk factor." Interpreted as mispricing with arbitrage costs.
- JFQA published abstract adds: "the return effect is concentrated around earnings announcements; and …
  analyst forecasts are systematically higher than realized earnings for faster growing firms."
  Retrieved: <https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/on-the-scope-and-drivers-of-the-asset-growth-effect/B8CFCF68A82E273E979221EF26A77096>

**International evidence — Watanabe, Xu, Yao & Yu (2013), *Journal of Financial Economics* 108, 529–563.**
Verified metadata and abstract (full text not retrievable — HKU repository returned a bot wall):
> "Firms with higher asset growth rates subsequently experience lower stock returns in international equity
> markets, consistent with the U.S. evidence. This negative effect of asset growth on returns is **stronger
> in more developed capital markets and markets where stocks are more efficiently priced**, but is
> **unrelated to country characteristics representing limits to arbitrage, investor protection, and
> accounting quality**."
Retrieved: <https://www.semanticscholar.org/paper/The-Asset-Growth-Effect%3A-Insights-from-Equity-Watanabe-Xu/5e515c94c4e972e85e37bc7adb4fe54f3a8c771a>
**UNVERIFIED:** the paper's exact per-country spread magnitudes, sample country count and period. The
abstract does not print them and the JFE full text is paywalled.

**Independent international replication I did retrieve — Chen, Yao, Yu & Zhang, Pacific-Basin markets
(nine markets, 1981–2004/2007), monthly D10−D1 equal-weighted raw returns:**
- All PACAP **−0.64% (t = −3.94)**; PACAP ex-Japan **−0.56% (t = −3.10)**; US **−1.96% (t = −9.54)**.
- By market: Japan −0.66 (−2.76), China −0.75 (−1.82), Hong Kong −1.12 (−2.09),
  **Taiwan −0.16 (−0.28, insignificant)**, Malaysia −0.92 (−1.88), Korea −1.03 (−2.78),
  Singapore −1.01 (−2.47), Thailand −1.63 (−2.94), Indonesia −1.12 (−2.03).
- Three-factor alphas: All PACAP **−0.67% (t = −3.84)**; US **−1.20% (t = −4.88)**.
- Annualised: **−7.42%** pooled PACAP, **−21.14%** US. Their abstract: "the relation is weaker relative to
  the U.S. market," and "Taiwan is the only market with an insignificant relation."
- Panel B shows the pre-formation run-up: US D10−D1 is **+1.17% (t = 3.88)** in year −1, then
  **−1.96%** in year +1 — the classic "investment follows good returns" pattern.

**Post-2000 / large-cap weakness.** Fama & French (2008), quoted inside the Lipson–Mortal–Schill working
paper: "there is an asset growth anomaly in average returns on microcaps and small stocks, but it is
**absent for big stocks … that account for more than 90% of total market cap**." This is the sharpest
statement of the large-cap caveat; note that LMS dispute its generality for the total-asset-growth measure.

### B5. Practical caveats for using these as live signals

- **Microcap contamination is the dominant specification risk.** Hou–Xue–Zhang: microcaps are "**61% of the
  total number of NYSE-Amex-NASDAQ stocks, but only 3.3% of the total market capitalization**"; their
  t-statistic triple-check (t ≥ 3) leaves 85% of 447 anomalies insignificant.
- **Direction of the investment factor is contentious after 2024.** Cooper–Gulen–Ion show the "investment"
  factor in the two leading models is really an *asset-growth / financing-shock* factor, and that the
  explanatory gain "is present only in high overextrapolation periods."
- **Capex ≠ asset growth.** Asset growth includes working capital, cash, acquisitions and equity issuance;
  a firm can be a heavy capex investor with zero asset growth (funded from cash). Any "capital discipline"
  screen must state which it is using.
- **Timing/look-ahead.** Tests must lag accounting data by at least the filing date. Hou–Xue–Zhang impose
  "a four-month lag between the fiscal quarter end and subsequent stock returns" for non-earnings quarterly
  items, citing a median 10-K/10-Q reporting lag of 46 days (NYSE/Amex) and 52 days (Nasdaq).
- **Transaction costs.** Hou–Xue–Zhang's benchmark uses NYSE breakpoints and value weights precisely to
  remove the illiquid microcap portion of the spread.

### B6. Computability from XBRL / iXBRL

| Marker input | XBRL tag(s) |
|---|---|
| Capital expenditure (TWX `CE`) | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`; fallback `us-gaap:PaymentsToAcquireProductiveAssets` |
| Sales deflator (TWX) | `us-gaap:Revenues`, `us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax` |
| Total assets (CGS `AG`) | `us-gaap:Assets` |
| PPE growth (traditional investment) | `us-gaap:PropertyPlantAndEquipmentNet`, `us-gaap:PropertyPlantAndEquipmentGross` |
| Inventory growth (CGI 2024: the real driver) | `us-gaap:InventoryNet`, `us-gaap:InventoryFinishedGoodsNetOfReserves`, `us-gaap:InventoryRawMaterialsNetOfReserves` |
| Receivables growth (CGI 2024) | `us-gaap:AccountsReceivableNetCurrent`, `us-gaap:ReceivablesNetCurrent` |
| Intangibles / goodwill (off-balance-sheet capital) | `us-gaap:Goodwill`, `us-gaap:IntangibleAssetsNetExcludingGoodwill` |
| Intangible investment proxies | `us-gaap:ResearchAndDevelopmentExpense`, `us-gaap:SellingGeneralAndAdministrativeExpense` (30% convention) |
| Equity issuance (CGS financing decomposition) | `us-gaap:ProceedsFromIssuanceOfCommonStock`, `us-gaap:ProceedsFromIssuanceOrSaleOfEquity`, `us-gaap:StockIssuedDuringPeriodValueNewIssues` |
| Debt issuance | `us-gaap:LongTermDebtNoncurrent`, `us-gaap:LongTermDebtCurrent`, `us-gaap:LongTermDebt`, `us-gaap:ProceedsFromIssuanceOfLongTermDebt` |
| Financing cash flows (Pontiff–Woodgate-style issuance factor) | `us-gaap:NetCashProvidedByUsedInFinancingActivities`, `us-gaap:PaymentsForRepurchaseOfCommonStock`, `us-gaap:PaymentsOfDividends` |
| Idiosyncratic volatility (LMS conditioning) | **Not in XBRL** — needs daily/monthly returns outside the filing |

A usable pipeline: pull `us-gaap:Assets` for consecutive 10-K periods from
`data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/Assets.json`, align to fiscal-year end, compute
`AG_t = (AT_{t-1} − AT_{t-2}) / AT_{t-2}`, then lag by filing date (`dei:DocumentPeriodEndDate` +
`dei:DocumentType`) before any return test. `frame=` queries
(`.../us-gaap/Assets.json?frame=CY2024Q4I`) allow cross-sectional pulls.

---

## C. "Capital discipline" studies — disciplined allocators, cash returned vs. reinvested, payout + leverage

### C1. McKinsey — "The strategic yardstick you can't afford to ignore"

**Marker.** Economic profit `EP = Invested Capital × (ROIC − WACC)`, decomposed into four drivers:
"revenues, margins, asset turns, and the tangible-capital ratio (TCR)," where TCR "is the ratio of physical
to total capital, including goodwill."

**Origin.** Chris Bradley, Angus Dawson & Sven Smit, *McKinsey on Finance* No. 49, Winter 2014.
Retrieved: <https://www.mckinsey.com/~/media/mckinsey/dotcom/client_service/corporate%20finance/mof/issue%2049/mof49_strategicyardstick.ashx>

**Sample.** "a large-scale analysis of economic profit for **nearly 3,000 large nonfinancial companies** in
McKinsey's proprietary corporate-performance database"; "**Actual sample = 2,875**; excludes outliers and
companies with insufficient data"; "Average economic profit for top 3,000 companies by FY2011 revenues …
**2007–11**"; cohort analysis n = 2,160 (1997–2001 base) and n = 2,240 (mobility); 128 global industries.
"we use a **global average cost of capital of 9 percent**."

**Reported effect sizes (exact):**
- EP distribution, 2007–11: top quintile **+$677 billion**; middle three quintiles **+$29.4 billion**
  ("around $17 million each — only 10 percent of the total pie"); bottom quintile **−$411 billion**.
  Top-quintile companies create "almost **70 times** more economic profit" than the middle three.
- "**40 percent** of a company's economic profit [is explained] by the industry in which it competes";
  "the remaining **60 percent** (the company effect) represents other drivers of value."
- Reversion: the valuation multiple "converges rapidly and completely"; ROIC "partially converge[s], but the
  gap never fully closes." "ROIC convergence reduces the gap … by **$409 million**, while diverging capital
  flows increase the gap by **$593 million**." Top-quintile 1997–2001 firms "invested **2.6 times more fresh
  capital** than bottom-quintile businesses did over the subsequent decade."
- Mobility: "Nearly **half dropped out of the top quintile** over a ten-year period, and **one in eight slid
  all the way to the bottom**." "**79 percent** of the companies that started [in the middle] remained a
  decade later"; "only **11 percent** of companies in the middle make the leap to the top league."
- Breakouts: of the **37** middle-quintile companies that rose to the top, "**33** compete in industries that
  have improved their economic-profit ranking"; "**75 percent** of the increased economic profit of the 37
  companies came from improvements in their markets or industries"; average industry rank improvement
  **39 places**; average revenue growth **+21%** and ROIC **+18 percentage points**.

**Status.** Descriptive/consulting study; tier **(b) single-paper** with a proprietary database.
**UNVERIFIED:** the underlying firm-level data are not published, so the EP figures are not independently
reproducible.

### C2. McKinsey — resource-allocation survey (*McKinsey on Finance* No. 86, July 2024)

**Origin.** Andy West & Tim Koller with Rishabh Bhargava, "Tying short-term decisions to long-term
strategy," *McKinsey on Finance* Number 86, July 2024.
Retrieved: <https://www.mckinsey.com/~/media/mckinsey/business%20functions/strategy%20and%20corporate%20finance/our%20insights/mckinsey%20on%20finance%20number%2086/mckinsey-on-finance-number-86.pdf>

**Sample.** "The online survey was in the field from **October 3 to October 13, 2023**, and garnered
responses from **617 participants** … midlevel-manager, senior-manager, and C-level positions at companies
with reported revenues of **$500 million or more**." Weighted by nation/GDP contribution.

**Reported effect sizes (exact, all self-reported outperformance):**
- "only about **half of the 617 executives** … say their companies effectively align their budgets with
  their corporate strategies"; "just **53 percent** say their organizations are in the habit of fully funding
  the priorities they've identified."
- Influential FP&A/strategy leader: "**1.8 times** more likely … to report that their organizations
  outperform on revenue growth, and … **1.9 times** more likely to report … outperform on return on capital."
  Raw figures: **51% vs. 28%** on revenue growth and **51% vs. 36%** on return on capital.
- Influential throughout the organization: **1.4×** revenue growth, **1.7×** return on capital
  (45% vs 24%; 44% vs 26%).
- In-year reallocation incentives: **1.8×** revenue growth, **1.7×** return on capital.
- Ranking the top 10–30 strategic programs on financial metrics "**almost always**": only **28%** of all
  respondents. Those who do: **55% / 50%** report outperformance vs **41% / 35%** for "almost never,
  seldom, or sometimes."
- Faster planning: plans in ≤3 months vs ≥5 months → return-on-capital outperformance **50% vs 33%**;
  budgets in ≤2 months vs ≥5 months → **51% vs 26%**.
- "Big moves" benchmark (verbatim): "CFOs should think in terms of **shifting more than 60 percent of annual
  capital expenditure to different business units every ten years**"; also "gross margin improvements that
  place your business within the top 30 percent of its industry, SG&A productivity improvements within the
  top 40 percent, and labor productivity improvements within the top 30 percent of peers."

**Status.** Self-reported cross-sectional survey; no return-predictive test. Cannot establish causality.
Tier **(b)**.

### C3. Mauboussin & Callahan, *Capital Allocation* (JACF 2014)

The 2014 article's verified abstract gives the **five principles of thoughtful capital allocation**:
"(1) zero-based capital allocation; (2) funding of strategies, not projects; (3) no capital rationing;
(4) **zero tolerance for bad growth**; and (5) continuous monitoring of the value of all assets and business,
and willingness to take action if and when such values are larger outside than inside the firm."
It also states as a premise: "the goal of corporate capital allocation is to build **long-term value per
share**," and flags that "incentive programs that focus on meeting earnings per share often encourage
behavior that is not in the best interests of long-term shareholders." Source:
<https://econpapers.repec.org/article/blajacrfn/v_3a26_3ay_3a2014_3ai_3a4_3ap_3a48-74.htm>

### C4. Evidence on cash returned vs. reinvested (payout / buyback discipline)

From the 2025 Morgan Stanley *Capital Allocation* update (all verbatim quotes in SOURCES):
- "Buying stock below its intrinsic value is a surefire way to increase value per share. But companies
  should prioritize internal investment opportunities **if they have higher returns than buybacks**."
- The market's average reaction ranking: "Spin-offs, divestitures, dividend initiations, share buybacks,
  debt prepayments, capital expenditures, and some intangible investments are associated with positive
  excess TSRs. … R&D tends to be value-neutral, as is M&A for the buyer. And equity issuance, including
  initial public offerings and seasoned equity offerings, predicts negative excess returns on average."
- M&A discipline: "Thirty six percent of companies reported reaching or exceeding their anticipated cost
  synergies. … Only 17 percent of companies said they surpassed their revenue synergy forecasts."
  (attributed to a McKinsey survey, endnote 54/55 of the report).
- R&D discipline: citing Knott, "about **one-third of companies spend below the optimal level of R&D** and
  have the opportunity to create value by spending more. **Nearly two-thirds spend too much** and can cut
  costs without jeopardizing value. She deems **five percent** of her sample to be close to optimal."
- Buyback mis-calibration: "**50–80 percent** of [CFOs] say the stock of their company is undervalued when
  surveyed in a typical quarter"; "The most common method that CFOs cite for valuing the stock of their
  company is 'current price relative to historic highs and lows.'"
- Divestitures: "divestitures have averaged **2.3 percent of sales**" for U.S. companies, 1980–2024.

### C5. "Capital allocation quality and future returns" — academic work

**Status: UNVERIFIED as a specific named study.** I searched for academic work under titles such as
"Capital allocation and the cross-section of stock returns" and did not retrieve a peer-reviewed paper by
that name. What does exist and is verified in sources I fetched:

1. **The value premium of disciplined allocators is not directly tested in any source I retrieved.** The
   closest verified academic evidence is *indirect*: the investment/asset-growth factor (Section B) —
   i.e., the market pays **lower** returns to firms that reinvest aggressively, on average, which is the
   opposite sign to "disciplined allocators earn more."
2. **The Morningstar Capital Allocation Rating** is a commercial rating (balance-sheet strength, investment
   acumen, distributions) applied to "roughly 1,850 public companies in the U.S."; the 2025 Morgan Stanley
   report cites the rating distribution (16% exemplary / 78% standard / 5% poor as of September 2025) but
   **does not report a return spread for high- vs. low-rated allocators**. **UNVERIFIED:** any predictive
   return test of the Morningstar Capital Allocation Rating.
3. **Divestiture and spinoff studies** are the closest thing to a "discipline pays" literature:
   "A meta-analysis of nearly 100 studies on divestitures concludes: 'In the broadest possible terms, our
   results suggest that on average, divestiture actions are associated with positive performance outcomes
   for the parent firm.'" and "spin-offs, conglomerates, and stockholders benefit from tax-free divestiture
   and subsequent refocusing by the companies." (both quoted in the 2025 Morgan Stanley report.)
4. The **free-cash-flow / Jensen (1986) agency hypothesis** — that excess cash invites value-destroying
   investment — is stated in the 2025 report: "managers who have excess cash will be tempted to invest in
   projects that have a negative net present value. Disbursing cash, whether through a buyback or a
   dividend, lessens the risk that management will deploy the funds foolishly." This is a **hypothesis
   statement, not a reported effect size** in the sources I retrieved.

### C6. Practical caveats for marker C

- **Self-reported outperformance ≠ measured outperformance.** The McKinsey 2024 survey's "1.8×/1.9×"
  figures are respondents' own assessments of whether their firm beats competitors — a well-known source of
  common-method bias.
- **Economic profit depends on a WACC you cannot observe.** McKinsey uses a flat 9% global cost of capital;
  changing that single assumption reorders quintiles, especially near the middle.
- **Industry explains ~40% of EP.** A capital-discipline screen that ignores industry will mostly rank
  industries, not managers.
- **Payout is not automatically disciplined.** The same 2025 report notes the *golden rule* condition
  (buy back only below intrinsic value) and that CFOs systematically claim undervaluation, which makes
  "buybacks = discipline" a weak inference.
- **Intangible-heavy firms look undisciplined under accounting-based screens** because their investment is
  expensed (this is Mauboussin's own stated caveat, and Cooper–Gulen–Ion's critique of asset growth).

### C7. Computability from XBRL / iXBRL

| Discipline marker | XBRL tag(s) |
|---|---|
| Economic profit / ROIC vs. WACC | See A7 (WACC external) |
| Cash returned vs. retained | `us-gaap:PaymentsOfDividendsCommonStock`, `us-gaap:PaymentsForRepurchaseOfCommonStock`, `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` |
| Payout ratio | Dividends ÷ `us-gaap:NetIncomeLoss` |
| Leverage discipline | (`us-gaap:LongTermDebtNoncurrent` + `us-gaap:LongTermDebtCurrent` + `us-gaap:ShortTermBorrowings` + lease liabilities) ÷ `us-gaap:StockholdersEquity` (book) or ÷ market cap |
| Capital reallocation across segments | Segment tags are **not** uniformly in `us-gaap` (they come from the `srt`/`us-gaap` segment axis on facts, e.g. `us-gaap:Assets` with `us-gaap:StatementBusinessSegmentsAxis`); coverage is patchy and requires parsing dimension members |
| M&A spend | `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` |
| Divestiture proceeds | `us-gaap:ProceedsFromDivestitureOfBusinesses` |
| Maintenance vs. growth capex | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` minus `us-gaap:DepreciationDepletionAndAmortization` (a proxy, not a filed figure) |

---

## D. Post-publication decay and replication

### D1. McLean & Pontiff (2016) — "Does Academic Research Destroy Stock Return Predictability?"

**Origin.** R. David McLean & Jeffrey Pontiff, *Journal of Finance* 71(1), February 2016, 5–32;
DOI 10.1111/jofi.12365.

**Sample / design.** Verified from the CFA Institute Research Foundation digest: "the authors study the
return predictability of **97 variables** shown to predict cross-sectional stock returns *outside* each
study's original sample," comparing three periods: "(1) the original study's sample period, (2) the period
after the original sample but before publication, and (3) the post-publication period."
Retrieved: <https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary>

**Reported effect sizes (exact, verbatim):**
> "The authors discover that portfolio returns are **26 percentage points (pps) lower** when a new study is
> commenced after the completion of the original study (referred to as 'out of sample') and **58 pps lower
> after publication**. The authors estimate that this additional **32 pp (58% − 26%)** reduction in the return
> after publication is because of other investors taking advantage of what they have learned
> (i.e., 'informed trading')."
> "For the 97 portfolios, the average monthly in-sample return is **0.582%**, the average out-of-sample
> pre-publication return is **0.402%**, and the average post-publication return is **0.264%**."

Note the arithmetic: 0.582 − 0.402 = 0.180 pp ≈ the "26%" decay of 0.582; 0.582 − 0.264 = 0.318 pp ≈ the
"58%" figure. The CFA digest labels these as *percentage-point declines relative to the in-sample level*.
**UNVERIFIED:** the original paper's own wording of "26%" and "58%" (whether percentages of in-sample return
or percentage points). The JF full text was not retrievable; only the CFA Institute digest was.

**Conditioning result (verified from the same digest):** "an anomaly is more easily accepted (and returns
decline quickly) when the pattern of returns is not too noisy and the payoff horizon is short (e.g., the
small-firm effect in January). A noisy anomaly, such as the value/growth distinction, can take **decades**
to play out, so it is not quickly arbitraged away."
Also: "They examine increases in trading volume and short interest that are consistent with the notion that
academic research draws attention to predictors."

### D2. Specific replication of the asset growth / capex effects

The three largest independent replication efforts I retrieved all find the effects **survive statistically
but shrink materially in magnitude**, and one finds the *factor-model* performance is regime-dependent:

1. **Hou, Xue & Zhang, "Replicating Anomalies"** (NBER WP 23394; published *RFS* 33(5), 2020, 2019–2133).
   Sample **January 1967 – December 2014**, 447 anomalies, NYSE breakpoints, value-weighted decile sorts.
   - "**286 anomalies (64%) … are insignificant at the conventional 5% level**. Imposing the cutoff t-value
     of three … raises the number of insignificance to **380 (85%)**."
   - "Even for significant anomalies, such as price momentum and operating accruals, their magnitudes are
     often much lower than originally reported." The **Cooper-Gulen-Schill (2008) asset growth** anomaly is
     named in the abstract's list of "prominent examples" of exactly this.
   - Reason: "Most published anomaly profits are greatly exaggerated" because studies overweight microcaps.
   - Interpretation caution: "the investment and Roe factors in the q-factor model are not entirely immune
     to data mining"; they cite Linnainmaa & Roberts (2016) showing the FF5 operating-profitability premium
     is insignificant in the pre-Compustat sample.
2. **Lipson, Mortal & Schill** — the effect is real and pervasive but is concentrated in high-IVOL stocks;
   "there appears to be no asset growth effect in firms with low idiosyncratic volatility" (1968–2006).
3. **Cooper, Gulen & Ion (2024), *JFE* 151:103746** — the *factor* payoff is regime-dependent:
   - "the superior performance of HXZ and FF5F over their analogues based on more traditional measures of
     investment is present **only in high overextrapolation periods**."
   - "In fact, in the subsample with below-median overextrapolation, the HXZ model does not perform
     significantly better than the Carhart (1997) four-factor model, and the FF5F model does not perform
     significantly better than the Fama and French (1993) model, or the Carhart (1997) model."
   - Table 9 high-DOX FF5F vs. C4F: Δ(maxSR²) = **−0.088** (p = 0.030); low-DOX FF5F vs. C4F:
     **+0.053** (p = 0.342). High-DOX HXZ vs. C4F: **−0.091** (p = 0.010); low-DOX HXZ vs. C4F:
     **−0.013** (p = 0.823).
   - Footnote-level count: "when DOX is high, using HXZ (FF5F) we can explain **all but one (four)** out of
     our 35 anomalies, whereas the best we can do using the traditional models is with the Carhart (1997)
     model (C4F), which explains **all but 12** anomalies. However, when DOX is low, the HXZ (FF5F) model
     explains **all but 10 (22)** anomalies, while the C4F model explains all but 14 anomalies."
   - Ownership/self-report caveat: two of the three authors are the original CGS authors, so this is a
     *self*-revision, which is a strength (they could not retrieve the original magnitudes either) but also
     means it is not fully independent.

### D3. Tier summary for marker D

| Finding | Tier |
|---|---|
| McLean–Pontiff 26% / 58% post-publication decay, 97 predictors | **(a) robust** — widely replicated and cited; the specific decays are the paper's headline |
| CGS asset growth anomaly *exists* | **(a) robust** — replicated in 9 international markets and in multiple US replications |
| CGS asset growth anomaly *magnitude as originally reported* | **(c) contested** — HXZ find it materially smaller under NYSE/value-weighted conventions |
| FF5/HXZ factor performance attributable to asset growth | **(b)/(c)** — Cooper–Gulen–Ion show it is asset growth (not capex/PPE) and that it is confined to high-DOX periods |
| TWX capex effect | **(b) single-paper in the US**, with an in-sample regime failure (1984–1989) and a demonstrated size dependence in LMS |

---

## What I could NOT verify (explicit UNVERIFIED list)

1. **CGS (2008) Table III exact numbers** — the lowest-minus-highest asset-growth decile monthly return,
   its t-statistic, and the three-factor alpha. The JF article is paywalled (Wiley bot wall on both the DOI
   page and `pdfdirect`), SSRN returned a bot wall, no open PDF reachable. Only the abstract and
   second-hand replications were retrievable.
2. **CGS (2008) exact sample period end and firm-year count** — the abstract does not state it; the
   Chen–Yao–Yu–Zhang replication states the CGS sample is 1968–2003, and LMS state 1968–2006 for their own
   quintile reproduction. I could not confirm the paper's own stated N.
3. **Fama & French (2015) five-factor model's own printed CMA average return** — all versions of the paper
   (SSRN, ScienceDirect, Wiley, one open mirror) were blocked or 404. The 0.34% (t = 3.63) figure is from
   Hou–Xue–Zhang's replication using Ken French's published factor data.
4. **Watanabe, Xu, Yao & Yu (2013) exact magnitudes, country count and sample period** — only the abstract
   was retrievable (HKU repository bot wall; JFE paywall).
5. **The full numerical content of the 2014 JACF "Capital Allocation" article** (the dollar amounts allocated
   to each of the seven uses of capital by the top 1,500 U.S. companies). Wiley paywall + bot wall.
6. **A published academic paper titled "Capital allocation and the cross-section of stock returns."** I
   searched for it and did not find one; do not cite such a title.
7. **Any return spread for the Morningstar Capital Allocation Rating** (exemplary vs. poor).
8. **"Measuring the Moat" (Credit Suisse) page-level numbers** — I retrieved the title page, table of
   contents and executive summary only; the body of the report was not readable through the accessible host.
9. **The Pacific-Basin paper's own sample-period endpoint** — the paper says "1981 to 2004" in the text but
   the later published version (Yao, Yu, Zhang & Chen 2011) covers 1981–2007; I verified 1981–2004 from the
   working-paper text I fetched.

## SOURCES FETCHED

Every URL below was retrieved with `web_fetch` and its content is the basis for the quotes above.

1. <https://www.nber.org/system/files/working_papers/w9951/w9951.pdf> — Titman, Wei & Xie, *Capital
   Investments and Stock Returns*, NBER WP 9951 (Sept 2003) / JFQA 39(4) 2004.
2. <https://www.strictlybiz.co.nz/wp-content/uploads/2022/12/themathofvalueandgrowth_us.pdf> — Mauboussin &
   Callahan, *The Math of Value and Growth*, Morgan Stanley Counterpoint Global, June 9, 2020.
3. <https://www.morganstanley.com/im/publication/insights/articles/article_capitalallocation.pdf> —
   Mauboussin & Callahan, *Capital Allocation: Results, Analysis, and Assessment*, Morgan Stanley
   Counterpoint Global, November 5, 2025.
4. <https://www.numerade.com/notes/directory/school/4677/courses/283359/files/4717857> — Mauboussin, Callahan
   & Majd, *Measuring the Moat*, Credit Suisse Global Financial Strategies, November 1, 2016 (hosted text of
   the report's front matter and Executive Summary).
5. <https://econpapers.repec.org/article/blajacrfn/v_3a26_3ay_3a2014_3ai_3a4_3ap_3a48-74.htm> — Mauboussin &
   Callahan, "Capital Allocation: Evidence, Analytical Methods, and Assessment Guidance," *JACF* 26(4) 2014,
   48–74; abstract and metadata.
6. <http://faculty.bus.olemiss.edu/rvanness/speakers/2009-2010/Mortal-Asset%20Growth%20Effect.pdf> — Lipson,
   Mortal & Schill, *Unraveling the Asset Growth Effect*, September 2009 (Tables 1–7 and appendix).
7. <https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/on-the-scope-and-drivers-of-the-asset-growth-effect/B8CFCF68A82E273E979221EF26A77096>
   — Lipson, Mortal & Schill, "On the Scope and Drivers of the Asset Growth Effect," *JFQA*; published abstract.
8. <https://econpapers.repec.org/article/blajfinan/v_3a63_3ay_3a2008_3ai_3a4_3ap_3a1609-1651.htm> — Cooper,
   Gulen & Schill, "Asset Growth and the Cross-Section of Stock Returns," *JF* 63(4) 2008, 1609–1651;
   abstract and metadata.
9. <https://www.cass.city.ac.uk/__data/assets/pdf_file/0011/76916/Yu-141-REVISED.pdf> — Chen, Yao, Yu &
   Zhang, *Asset Growth and Stock Returns: Evidence from the Pacific-Basin Markets*, April 2008
   (Tables 1–6; also reports the CGS 1968–2003 "more than 20%" figure).
10. <https://r.jina.ai/http://hub.hku.hk/bitstream/10722/188473/1/content.pdf> — attempted retrieval of
    Watanabe, Xu, Yao & Yu (2013) full text; returned a bot-check page (content NOT obtained).
11. <https://www.semanticscholar.org/paper/The-Asset-Growth-Effect%3A-Insights-from-Equity-Watanabe-Xu/5e515c94c4e972e85e37bc7adb4fe54f3a8c771a>
    — Watanabe, Xu, Yao & Yu, "The Asset Growth Effect: Insights from International Equity Markets,"
    *JFE* 108 (2013), 529–563; metadata and abstract.
12. <https://www.nber.org/system/files/working_papers/w18435/w18435.pdf> — Hou, Xue & Zhang, *Digesting
    Anomalies: An Investment Approach*, NBER WP 18435 (Oct/Nov 2012) / *RFS* 2015.
13. <https://www.nber.org/system/files/working_papers/w23394/w23394.pdf> — Hou, Xue & Zhang, *Replicating
    Anomalies*, NBER WP 23394 / *RFS* 33(5) 2020 (447 anomalies; FF5 CMA 0.34% t = 3.63; q-factor premiums).
14. <https://fairmodel.econ.yale.edu/ec439/ansh.pdf> — Cooper, Gulen & Ion, "The use of asset growth in
    empirical asset pricing models," *JFE* 151 (2024) 103746 (Tables 1, 8, 9 and DOX conditioning).
15. <https://www.mckinsey.com/~/media/mckinsey/dotcom/client_service/corporate%20finance/mof/issue%2049/mof49_strategicyardstick.ashx>
    — Bradley, Dawson & Smit, "The strategic yardstick you can't afford to ignore," *McKinsey on Finance*
    No. 49, Winter 2014.
16. <https://www.mckinsey.com/~/media/mckinsey/business%20functions/strategy%20and%20corporate%20finance/our%20insights/mckinsey%20on%20finance%20number%2086/mckinsey-on-finance-number-86.pdf>
    — West & Koller with Bhargava, "Tying short-term decisions to long-term strategy," *McKinsey on Finance*
    No. 86, July 2024 (617-respondent resource-allocation survey).
17. <https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary>
    — CFA Institute Research Foundation digest of McLean & Pontiff (2016), "Does Academic Research Destroy
    Stock Return Predictability?", *JF* 71(1) 2016, 5–32.

### Additional URLs attempted but NOT successfully retrieved (blocked / paywalled / bot-check)

- <https://onlinelibrary.wiley.com/doi/10.1111/jacf.12090> — bot check.
- <https://onlinelibrary.wiley.com/doi/10.1111/j.1540-6261.2008.01370.x> and `.../pdfdirect/...` — bot check.
- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=760967> and `.../abstract_id=2287202` — bot check.
- <https://www8.gsb.columbia.edu/valueinvesting/.../13-Summary%20of%20'Asset%20Growth...'.pdf> — bot check.
- `kipdf.com` mirror of Fama–French (2015) — bot check; `breese7160.tulane.edu` mirror — 404.
- <https://www.depts.ttu.edu/.../cooper_gulen_ion_2017.pdf> — 404 (later obtained the JFE version at #14).
- `hub.hku.hk` Watanabe full text — bot check.
- `virtusinterpress.org`, `fa-mag.com`, `studocu.com` — bot checks.
- `mba.tuck.dartmouth.edu` Fama–French 5-factor data zip — **network egress from the shell was blocked**
  (`curl` schannel `SEC_E_NO_CREDENTIALS`), so the CMA average could not be recomputed from the raw data;
  the HXZ-replicated figure is used instead and labelled as such.
