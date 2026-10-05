# M&A Capital-Allocation Markers — Source-Grounded Evidence Pack

**Scope:** acquirer value destruction / creation markers, one subsection per marker, with
(a) definition + inputs, (b) originating study, (c) sample, (d) exact effect sizes,
(e) out-of-sample / post-publication status, (f) caveats, (g) XBRL computability.

**Method / access note (read this first).** Every claim below is tied to a URL I actually
retrieved with `web_fetch`. Where I could only retrieve the *publisher landing page, the
RePEc record, the OpenAlex record, or the Semantic Scholar/Unpaywall access record* rather
than full text, I say so and mark the specific numbers **UNVERIFIED**. The following classics
are confirmed **closed access with no repository copy** (verified via Unpaywall by DOI), so I
retrieved their bibliographic records but **not** their tables:
Agrawal/Jaffe/Mandelker 1992 (`10.1111/j.1540-6261.1992.tb04674.x`),
Loughran/Vijh 1997 (`10.1111/j.1540-6261.1997.tb02741.x`),
Rau/Vermaelen 1998 (`10.1016/S0304-405X(98)00023-3`),
Moeller/Schlingemann/Stulz 2004 (`10.1016/j.jfineco.2003.07.002`) — all returned
`"oa_status":"closed"`, `"has_repository_copy":false`. I did **not** invent any of their
effect sizes. Where a **different, retrievable version of the same research team's work**
exists (NBER working papers), I used it and say so.

---

## Marker A — Acquirer underperformance (short-window announcement + long-run post-merger)

### A.1 Definition and inputs

* **Announcement abnormal return (CAR)** = cumulative market-model (or market-adjusted)
  residual over a short window around the deal announcement, usually `CAR(-1,+1)` (3 days) or
  `CAR(-5,+5)`. Inputs: daily stock returns, a market index, an estimation window (typically
  `[-205,-6]`), deal announcement date, and deal materiality screens.
* **Dollar announcement return** = `CAR × acquirer equity market cap` (Malatesta 1983
  adjustment as used by Moeller et al.). This is the value-weighted quantity that actually
  drives aggregate wealth effects.
* **Long-run post-merger return** = 3–5 year buy-and-hold abnormal return (BHAR) versus a
  matched/benchmark firm, or calendar-time portfolio alpha (Fama-French / Carhart 4-factor).

### A.2 What I could verify with full text — Moeller, Schlingemann & Stulz

**Retrieved full text (NBER WP versions):**
[w10200, *Wealth Destruction on a Massive Scale?*](https://www.nber.org/system/files/working_papers/w10200/w10200.pdf) and
[w9523, *Do Shareholders of Acquiring Firms Gain From Acquisitions?*](https://www.nber.org/system/files/working_papers/w9523/w9523.pdf).
These are the working-paper versions of MSS (2005, JF 60(2):757-782) and MSS (2004,
JFE 73(2):201-228). The published JFE 2004 record is closed access
([RePEc record](https://ideas.repec.org/a/eee/jfinec/v73y2004i2p201-228.html): `"No abstract is
available for this item"`), so treat the w9523 numbers below as the retrievable version of the
same sample rather than the JF/JFE page proofs.

**Sample (w9523):** `12,023` completed acquisitions by US public acquirers, 1980–2001, deal
value ≥ $1m and ≥ 1% of acquirer market value of assets; SDC + CRSP + Compustat; targets =
private firms (5,583), public firms (2,642), subsidiaries (3,798).

**Sample (w10200):** same 12,023; the 1998–2001 sub-period contains 4,136 acquisitions.

**Exact effect sizes, short window (w9523, Table 3):**

> "The table reports that the average abnormal return for an acquisition is **1.103%**."

| Target type | Mean CAR(−1,+1) | Mean %NPV per $100 spent |
|---|---|---|
| All (N=12,023) | **1.103%** | **5.796%** |
| Private (N=5,583) | **1.496%** | 8.104% |
| Public (N=2,642) | **−1.020%** | −5.900% |
| Subsidiary (N=3,798) | **2.003%** | 10.538% |

Aggregate: `"the aggregate net present value of acquisitions is −$218.593 billion"`.

**The single most important cross-sectional result (size):**

> "An acquisition made by a small firm, regardless of form of payment and regardless of the
> organizational form of the assets acquired, has an announcement return that is **2.24%
> higher** than a comparable acquisition made by a large firm."

Table 4 Panel A confirms the small-minus-not-small difference as **2.240%** (significant at 1%).
Aggregate split: `"shareholders from small firms earn $8 billion from the acquisitions they
made from 1980 to 2001, whereas the shareholders from large firms lose $226 billion."`

**Free-cash-flow / low-q test inside the same sample (directly relevant to Marker B):**

> "when we consider separately the sample of large firms, we find that firms with q less than
> one have lower abnormal returns. This is especially the case for cash acquisitions. These
> acquisitions have abnormal returns lower by **0.87%** when undertaken by low q firms."
>
> "However, the Lang, Stulz, and Walking (1991) measure of free cash flow (cash flow if q is
> lower than one) **is not significant**."

**Exact effect sizes, late-1990s skewness and "large loss deals" (w10200):**

> "Acquiring-firm shareholders lost **12 cents** at the announcement of acquisitions for every
> dollar spent on acquisitions for a total loss of **$240 billion** from 1998 through 2001,
> whereas they lost **$7 billion** in all of the 1980s, or **1.6 cents** per dollar spent."

> "From 1998 through 2001, the average abnormal return across all acquisitions is **0.69%** and
> shareholders lose $240 billion; from 1987 through 1990, the average abnormal return across all
> acquisitions is **0.76%** and shareholders gain $121 million."

> "Out of the **4,136** acquisitions from 1998 through 2001, **87** are large loss deals. The
> aggregate wealth loss associated with these acquisitions is **$397 billion**, while all other
> acquisitions made a total gain of $157 billion."
>
> "On average, large loss deals have a negative abnormal return of **−10.6%**."

> "On average, shareholders lose **$2.31** per dollar spent on the acquisition. The median loss
> is **$0.73** per dollar spent."

> "the fraction of the total amount spent on acquisitions accounted for by the acquisitions in
> the first percentile of the distribution of dollar returns increases from **13.68%** for
> 1980-1997 to **32.74%** for 1998-2001."

Aggregate table values: `1980-1990: −$4,244m`; `1991-2001: −$216,316m`; `1998-2001: −$239,954m`;
`1980-2001: −$220,560m`. Average dollar loss per acquisition `$1.945m` (1980–1990) vs
`$21.981m` (1991–2001); loss per $100 spent `$0.88` vs `$7.38`.

### A.3 Long-run / post-merger performance and the replication question

From w9523 (retrieved):

> "For the whole sample, the monthly abnormal return is **−0.041%** and insignificant. There is
> therefore no evidence that acquirers have poor long-term performance."

Using event-time 3-year BHARs instead: `"We find there that acquiring firms perform poorly."`
So **the long-run result is method-dependent even inside one paper** — a key caveat.

The same paper states the replication split explicitly (this is the cleanest
"held-up-or-not" statement I could retrieve):

> "Some of the existing studies that examine long-term returns following acquisitions of public
> firms suggest that shareholders fare poorly following acquisitions paid for with equity (for
> instance, **Loughran and Vijh (1997)**), but other studies do not find poor returns following
> such acquisitions (for instance, **Mitchell and Stafford (2000)** and **Dong, Hirshleifer,
> Richardson, and Teoh (2002)**)."

From w10200 on the after-the-fact performance of worst-deal acquirers:

> "Firms that announce acquisitions with large dollar losses perform poorly afterwards."

### A.4 The papers I could only verify bibliographically — effect sizes UNVERIFIED

| Study | Access status I verified | Effect sizes |
|---|---|---|
| Agrawal, Jaffe & Mandelker (1992), JF 47(4):1605-1621 | [Semantic Scholar record](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/j.1540-6261.1992.tb04674.x?fields=title,year,abstract,openAccessPdf,externalIds) returns `"openAccessPdf": {"url": "", "status": "CLOSED"}` and `"abstract": null`; [Unpaywall](https://api.unpaywall.org/v2/10.1111/j.1540-6261.1992.tb04674.x?email=awltux.research@gmail.com) confirms `"is_oa":false`, `"has_repository_copy":false` | **UNVERIFIED.** I could not retrieve the paper's post-merger abnormal-return tables. Do not quote a number for this paper from this pack. |
| Loughran & Vijh (1997), JF 52(5):1765-1790 | [Semantic Scholar record](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/j.1540-6261.1997.tb02741.x?fields=title,year,abstract,openAccessPdf,externalIds) returns `status: CLOSED`, abstract elided | **UNVERIFIED** for its 5-year BHARs by payment method. Its *existence and direction* are corroborated only indirectly by MSS w9523 (quoted above). |
| Rau & Vermaelen (1998), JFE 49(2):223-253 | [Semantic Scholar record](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/S0304-405X(98)00023-3?fields=title,year,abstract,openAccessPdf,externalIds) `status: CLOSED`; [Unpaywall](https://api.unpaywall.org/v2/10.1016/S0304-405X(98)00023-3?email=awltux.research@gmail.com) `"oa_status":"closed"` | **UNVERIFIED.** The glamour/value acquirer split numbers could not be retrieved. |
| Moeller, Schlingemann & Stulz (2004), JFE 73(2):201-228 | RePEc record fetched — no abstract; Unpaywall `"oa_status":"closed"` | Size-effect numbers **approximated by w9523 above**, not the JFE page proofs. Treat as **partially verified**. |
| Andrade, Mitchell & Stafford (2001), JEP 15(2):103-120 | Not retrievable (AQR page 429; NYU-hosted PDF returned 404; publisher page behind bot check). Citation confirmed indirectly from the reference list of w9523 and [RePEc](https://ideas.repec.org/a/bla/jfinan/v57y2002i4p1763-1793.html) | **UNVERIFIED** — I did not retrieve it. |

### A.5 Meta-analyses (abstract-level only, retrieved)

**King, Dalton, Daily & Covin (2004)**, *Strategic Management Journal* 25(2):187-200 —
[RePEc record fetched](https://ideas.repec.org/a/bla/stratm/v25y2004i2p187-200.html). Abstract,
retrieved verbatim:

> "We find robust results indicating that, on average and across the most commonly studied
> variables, acquiring firms' performance does not positively change as a function of their
> acquisition activity, and is negatively affected to a modest extent. More importantly, our
> results indicate that unidentified variables may explain significant variance in
> post-acquisition performance."

The **numeric mean effect size is UNVERIFIED** (paywalled; I did not retrieve the tables).

**Haleblian, Devers, McNamara, Carpenter & Davison (2009)**, *Journal of Management* —
**UNVERIFIED.** I could not retrieve full text; Google Scholar/RePEc-indexed copies I found
were not reachable (SAGE page, institutional resolvers). No sample, no effect size verified.

### A.6 Caveats (all supported by the retrieved sources)

1. **Equally-weighted CAR and aggregate dollar loss give opposite signs in the same data.**
   w10200: mean CAR is positive in almost every year while aggregate dollar returns are negative
   in 11 of 21 years. Any marker must declare whether it is equal- or value-weighted.
2. **The result is driven by a handful of mega-deals.** 87 of 4,136 deals (2.1%) account for
   43.4% of dollars spent and a −$397bn loss in 1998–2001 (w10200). A screen that cannot
   isolate these will look like noise.
3. **Long-run results flip with method** (calendar-time alpha ≈ 0 and insignificant vs.
   event-time BHAR "acquiring firms perform poorly") — w9523.
4. **Announcement returns conflate deal NPV with revaluation of the standalone bidder**
   (w10200 discusses this explicitly), so a negative CAR is not automatically evidence of a
   bad deal.
5. **Firm size dominates** (2.24% advantage for small acquirers, w9523) — an unadjusted
   cross-sectional screen will mostly be picking up size, not M&A behaviour.

### A.7 XBRL computability

The announcement-return markers (A) are **not computable from XBRL at all** — they need daily
prices and announcement dates (CRSP/SDC-type data). XBRL can only supply the *denominators*
and the *deal materiality screen*:

* Deal size: `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` or
  `us-gaap:BusinessCombinationConsiderationTransferred1` (or the `...IncludingEquityInterest...`
  variants) for the period of the deal.
* Materiality denominator: `us-gaap:Assets` and/or acquirer equity market cap (needs price data).
* Post-deal long-run performance: not XBRL-derivable.

See the consolidated XBRL table at the end, including the verification caveat.

---

## Marker B — Empire building / free-cash-flow hypothesis

### B.1 Definition and inputs

Jensen's marker is: **firms with high free cash flow and poor growth opportunities (low
Tobin's q / low market-to-book) are more likely to make value-destroying acquisitions.**
Formula/inputs:

* `FCF ≈ OperatingCashFlow − CapitalExpenditures` (accounting proxy), often scaled by assets.
* `Q = (Book assets − Book equity + Market equity) / Book assets` (or market-to-book).
* Interaction `FCF × (Q < 1)` — the Lang, Stulz & Walkling construction.

### B.2 The originating text — retrieved in full

Jensen, M. C. (1986), "Agency Costs of Free Cash Flow, Corporate Finance, and Takeovers",
*AER* 76(2):323-329. Retrieved full text via the
[IDOCPUB reproduction of the JSTOR scan](https://idoc.pub/documents/jensen-free-cash-flows-aer86-k5460xpy6x48).

Definition, verbatim:

> "**Free cash flow is cash flow in excess of that required to fund all projects that have
> positive net present values when discounted at the relevant cost of capital.**"

The takeover prediction, verbatim:

> "Acquisitions are one way managers spend cash instead of paying it out to shareholders.
> Therefore, the theory implies **managers of firms with unused borrowing power and large free
> cash flows are more likely to undertake low-benefit or even value-destroying mergers.
> Diversification programs generally fit this category, and the theory predicts they will
> generate lower total gains.**"

> "In declining industries, mergers within the industry will create value, and mergers outside
> the industry are more likely to be low- or even negative-return projects."

**Sample / N:** this is a theory-and-evidence essay, not a regression study. There is no N. It
is a Papers-and-Proceedings piece; the "evidence" is a literature synthesis. **Any claim that
Jensen (1986) estimated an effect size is false.**

Quantities Jensen does quote (retrieved):

* Leverage-increasing transactions: `"The 2-day gains range from 21.9 percent (debt for common)
  to 2.2 percent (debt or income bonds for preferred)."`; leverage-reducing:
  `"The 2-day losses range from -9.9 percent (common for debt) to -.4 percent"`.
* Oil industry: `"1984 cash flows of the ten largest oil companies were $48.5 billion, 28
  percent of the total cash flows of the top 200 firms"`.
* Oil E&D returns: `"even a 10% return on its pretax outlays"` (Picchi) and
  `"less than 60 to 90 cents on every dollar invested"`.
* `"Total gains to shareholders in the Gulf/Chevron, Getty/Texaco, and Dupont/Conoco mergers,
  for example, were over $17 billion."`
* `"the voluntary Arco restructuring resulted in stockholder gains ranging from 20 to 35 percent
  of market value (totaling $6.6 billion)"`.

### B.3 The empirical tests — what held up

**Lang, Stulz & Walkling (1989/1991)** — **UNVERIFIED as primary text.** I could not retrieve
either paper. The 1989 JFE 24(1):137-154 paper is listed in the reference list of the
[RePEc record for MSS 2004](https://ideas.repec.org/a/eee/jfinec/v73y2004i2p201-228.html), and
the 1991 FCF measure is described (and rejected) inside the retrievable
[w9523 text](https://www.nber.org/system/files/working_papers/w9523/w9523.pdf):

> "However, the Lang, Stulz, and Walking (1991) measure of free cash flow (cash flow if q is
> lower than one) **is not significant**."

**This is the most important single fact for Marker B:** in a 12,023-deal 1980–2001 US sample,
the classic LSW free-cash-flow interaction **did not** survive as a significant predictor of
announcement returns, while the *low-q × cash-acquisition* effect did (`−0.87%`).

**Harford (1999)**, "Corporate Cash Reserves and Acquisitions", *JF* 54(6):1969-1997 —
**UNVERIFIED.** I retrieved only the citation (from the w9523 and
[MSS 2004 RePEc reference lists](https://ideas.repec.org/a/eee/jfinec/v73y2004i2p201-228.html)).
I did not retrieve the paper, so I will not state its effect sizes.

### B.4 Caveats

1. **The FCF marker is a theory before it is a fact.** Jensen (1986) offers no test; the
   empirical support is mixed and, on the retrievable evidence, the specific LSW interaction is
   not significant in the largest 1980–2001 sample I could read.
2. **FCF is not directly observable in XBRL.** Any screen is a proxy and the proxy choice
   materially changes results (Jensen's own definition is "cash in excess of positive-NPV
   projects", which is not an accounting quantity).
3. **Endogeneity:** high cash flow and low q correlate with size, industry and merger-wave
   timing; the low-q effect in w9523 appears *only* in the large-firm and cash-acquisition
   subsamples.

### B.5 XBRL computability — **high**

| Input | us-gaap element | Notes |
|---|---|---|
| Operating cash flow | `us-gaap:NetCashProvidedByUsedInOperatingActivities` | Annual + interim (YTD) |
| Capex | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment` | Cash-flow statement |
| FCF proxy | OCF − capex | Derived |
| Scale | `us-gaap:Assets` | Instantaneous |
| q numerator | `us-gaap:Assets` − `us-gaap:StockholdersEquity` + market cap | Needs price data for market cap |
| Growth option proxy | market-to-book (`StockholdersEquity` + price) | Needs price data |

All five elements above are standard, widely-filed `us-gaap` cash-flow and balance-sheet
concepts. **Caveat: I could not machine-verify the element names in this session** — the SEC
XBRL API returned
[HTTP 403 ("Your Request Originates from an Undeclared Automated Tool")](https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/Goodwill.json)
because the fetch did not carry a declared user agent. Verify against
`https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<Tag>.json` from a client
that sets a `User-Agent` header.

---

## Marker C — Acquisition intensity / investment intensity as a value-destruction marker

### C.1 Definition and inputs

**Abnormal capital investment (CI)** — Titman, Wei & Xie:

`CI(t−1) = CE(t−1)/Sales(t−1) − [ CE(t−2) + CE(t−3) + CE(t−4) ] / (3 × Sales)`

i.e. formation-year capex intensity minus the prior 3-year average capex intensity. Firms are
sorted into quintiles; the tested portfolio is long the two lowest CI quintiles and short the
two highest (a zero-investment "CI-spread"), value-weighted, rebalanced each July.

**Acquisition-intensity analogue (practitioner form):** `AcquisitionSpend / TotalAssets` or
`AcquisitionSpend / OperatingCashFlow`, computable directly from XBRL.

### C.2 Full text retrieved — Titman, Wei & Xie

Retrieved: [NBER WP 9951, *Capital Investments and Stock Returns*](https://www.nber.org/system/files/working_papers/w9951/w9951.pdf)
(published as JFQA 39(4):677-700, 2004).

**Sample:** all domestic primary NYSE/Amex/Nasdaq stocks; financial statement data 1969–1995;
test-period returns **July 1973 – June 1996**; initial `58,880` industrial firm-years, final
sample averaging **1,635 firms a year** after data screens. Financial and utility firms,
ADR/fund/REIT excluded.

**Exact effect sizes (retrieved tables):**

* CI-spread mean characteristic-adjusted return: `"the mean excess return (0.168% per month)"`,
  p < 0.01; median 0.119%.
* Carhart 4-factor alpha of the CI-spread: **0.192% per month** (all years); **0.312%** in
  non-takeover years; **−0.124%** in takeover years 1984–1989.
* Extreme quintiles: lowest CI quintile mean `0.042%`, alpha `−0.012%`; **highest CI quintile
  mean `−0.127%`, alpha `−0.173%`**.
* Year-by-year CI-spread returns: `Year 1 2.02%`, `Year 2 2.26%`, `Year 3 1.91%`,
  `Year 4 1.85%`, `Year 5 1.64%`, `Cumulative 8.10%`.
* Fama-MacBeth: CI coefficient `λ1 = −0.79` (t = −2.80) with cash-flow interaction, and
  `−0.95` (t = −2.76) in the triple-interaction model.

**The agency / empire-building claim, verbatim from the retrieved abstract:**

> "The negative abnormal capital investment/return relation is shown to be **stronger for firms
> that have greater investment discretion, i.e., firms with higher cash flows and lower debt
> ratios**, and is shown to be **significant only in time periods when hostile takeovers were
> less prevalent**."

> "Firms that substantially increase capital investments subsequently achieve negative
> benchmark-adjusted returns."

**Earnings-announcement test (a mechanism check, retrieved):** the CI-spread's 3-day
earnings-announcement returns in year 1 are `0.792%` vs annual `3.330%`, i.e.
`"Ratio (%) 23.78"` — about 24% of the annual abnormal return arrives in 12 quarterly
announcement windows, which the authors use to argue against a pure benchmark-error story.

### C.3 Asset growth (the broader, better-known "investment intensity" marker)

**Cooper, Gulen & Schill (2008)**, "Asset Growth and the Cross-Section of Stock Returns",
*JF* 63(4):1609-1651 — [RePEc record fetched](https://ideas.repec.org/a/bla/jfinan/v63y2008i4p1609-1651.html);
[OpenAlex record fetched](https://api.openalex.org/works?filter=doi:10.1111/j.1540-6261.2008.01370.x&select=id,doi,title,publication_year,best_oa_location,abstract_inverted_index)
confirms `"best_oa_location": null` (no open copy).

Abstract, retrieved verbatim:

> "Asset growth rates are strong predictors of future abnormal returns. Asset growth retains its
> forecasting ability even on large capitalization stocks. ... a firm's annual asset growth rate
> emerges as an economically and statistically significant predictor of the cross-section of
> U.S. stock returns."

**The exact high-minus-low decile spread is UNVERIFIED** — the paper is paywalled with no
repository copy and I did not retrieve its tables. Do not attribute a specific basis-point
number to Cooper-Gulen-Schill from this pack.

**Post-publication / out-of-sample status: UNVERIFIED.** I did not retrieve any replication,
decay, or international out-of-sample study for the asset-growth effect. (Search hits included
a Liverpool repository working paper and a *JFE* "asset growth effect: Insights from
international equity markets" article, but I did not fetch and read either.)

### C.4 Caveats

1. **Different markers, different signs.** TWX's CI measure is *abnormal* capex (deviation from
   own 3-year norm, scaled by sales); Cooper-Gulen-Schill use *total asset growth*. These are
   not the same signal and should not be conflated.
2. **The TWX effect is period-dependent by the authors' own admission**: it is significant
   *only* outside the 1984–1989 hostile-takeover window.
3. **Data-vendor mismatch:** both studies use Compustat + CRSP. XBRL-derived capex/asset growth
   will differ (restatements, YTD-vs-quarter handling, tag changes), so historical effect sizes
   do not transfer mechanically to an XBRL backtest.
4. **No acquisition-specific intensity study verified.** I did not find and retrieve a
   peer-reviewed paper whose *primary* variable is `acquisition spend / assets` predicting
   returns. Treat "acquisition intensity" as an extension of the capex/asset-growth evidence,
   not as separately established.

### C.5 XBRL computability — **high**

| Marker | Formula | us-gaap elements |
|---|---|---|
| Capex intensity (level) | capex / revenue | `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:Revenues` (or `us-gaap:SalesRevenueNet`) |
| Abnormal capex (TWX) | CE_t/Sales_t − mean(CE_{t−1..t−3}/Sales) | same, 4 consecutive annual periods |
| Acquisition intensity | acq. spend / assets | `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`, `us-gaap:Assets` |
| Acquisition intensity vs cash flow | acq. spend / OCF | `us-gaap:NetCashProvidedByUsedInOperatingActivities` |
| Asset growth | ΔTotalAssets / TotalAssets_{t−1} | `us-gaap:Assets` (current and prior year, same accession's comparative facts) |

Practical note: `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` is a cash-flow-statement
element and is **YTD** in interim filings (Q2 = 6 months, Q3 = 9 months) — you must difference
consecutive interim periods, not sum them.

---

## Marker D — Goodwill build-up and goodwill impairment

### D.1 Definition and inputs

* **Goodwill intensity** = `Goodwill / TotalAssets` (or `Goodwill / MarketCap`, or
  `Goodwill / BookEquity`) at fiscal year end.
* **Goodwill build-up** = YoY change in goodwill attributable to acquisitions:
  `GoodwillAcquiredDuringPeriod` or `ΔGoodwill` net of impairment and FX.
* **Impairment** = `GoodwillImpairmentLoss` (ASC 350-20), optionally merged with
  `AssetImpairmentCharges`.
* Prediction test: classify firm-years into `impair(t+1) = 1` from acquisition-time and
  firm-time covariates.

### D.2 Gu & Lev (2011) — the core "goodwill as a value-destruction marker" paper

Gu, F. & Lev, B., "Overpriced Shares, Ill-Advised Acquisitions, and Goodwill Impairment",
*The Accounting Review* 86(6):1995-2022 (2011).
[OpenAlex record + abstract fetched](https://api.openalex.org/works?search=Overpriced%20shares%20ill-advised%20acquisitions%20and%20goodwill%20impairment&per-page=3).
DOI `10.2308/accr-10131`. Status: `"is_oa": false`.

Abstract, verbatim:

> "We establish that the **root cause of many goodwill write-offs is the buyers' overpriced
> shares at acquisition**. Overpriced shares provide managers with strong incentives to exploit
> the overpricing by acquiring businesses, often paying more than the acquisition's synergies,
> setting the stage for subsequent goodwill write-offs. In particular, we document the following
> patterns: (1) **Share overpricing is strongly and positively associated with the intensity of
> corporate acquisitions and the growth of accounting goodwill.** (2) **Share overpricing
> predicts goodwill write-offs and their magnitude.** (3) Acquisitions by overpriced
> companies—a strategy often recommended by investment bankers and some academics—are often
> ill-advised (overpaid and/or strategic misfit), exacerbating the post-acquisition negative
> returns of buyers beyond the reversal of the overpricing."

**Sample, period, N: UNVERIFIED** (full text paywalled; OpenAlex record carries no sample
fields). **Exact coefficients: UNVERIFIED.** The working-paper version
([SSRN abstract_id=1130940](https://api.openalex.org/works?search=Overpriced%20shares%20ill-advised%20acquisitions%20and%20goodwill%20impairment&per-page=3))
is listed as green OA, but I did not manage to retrieve its PDF.

### D.3 Li, Shroff, Venkataraman & Zhang (2011) — impairment as a leading indicator

*Review of Accounting Studies* 16(4):745-778.
[Abstract retrieved in full from the Springer article page](https://link.springer.com/article/10.1007/s11142-011-9167-2).

Abstract, verbatim:

> "Our evidence suggests that **both investors and financial analysts revise their expectations
> downward on the announcement of an impairment loss**. We find that the negative impact of the
> loss is significant under different reporting regimes, that is, pre-SFAS-142, transition
> period and post-SFAS-142, **though it is lower in the post period**. We further show that
> **goodwill impairment serves as a leading indicator of a decline in future profitability**.
> Our tests also reveal that **proxies for overpayment for targets can predict the subsequent
> goodwill impairment**. Indirect evidence suggests that **firms with potentially impaired
> goodwill that did not report an impairment loss may have used their managerial discretion to
> avoid taking the loss**."

**Sample, period, N and exact coefficients: UNVERIFIED** (abstract only; the article is
paywalled behind Springer's institution login). What *is* verified from the page: the sample
splits into pre-SFAS-142 / transition / post-SFAS-142 regimes, and the post-SFAS-142 impairment
period they discuss covers **2003–2006** with `Compustat` item #250 for the after-tax goodwill
impairment loss.

### D.4 Hayn & Hughes (2006) — impairment *timeliness*

*Journal of Accounting, Auditing & Finance* 21(3):223-265.
[Abstract retrieved via OpenAlex](https://api.openalex.org/works?search=Leading%20indicators%20of%20goodwill%20impairment&per-page=3).

Abstract, verbatim (the two most important sentences):

> "we find that **available disclosures do not provide financial statement users with information
> to adequately predict future write-offs of goodwill.**"
>
> "We also find that **goodwill impairments lag behind the economic impairment by an average of
> three to four years. For one-third of the companies examined, the delay can extend up to ten
> years.**"

Also: `"the original acquisitions are more powerful predictors of the eventual write-off event
than those based on segment disclosures."`

**Sample: UNVERIFIED in detail** — the Springer citation note in Li et al. (retrieved) states
Hayn & Hughes "develop an impairment prediction model using **acquisitions made during 1988
through 1998**". Use that as the period with the citation-source caveat.

### D.5 "Goodwill and the cross-section of stock returns" — the returns claim

Liu, X., Yin, C. & Zheng, W., "The invisible burden", *Journal of Financial Markets* 52:100561
(2020/2021). DOI `10.1016/j.finmar.2020.100561`.
[OpenAlex record fetched](https://api.openalex.org/works?search=invisible%20burden%20goodwill%20cross-section%20of%20stock%20returns&per-page=3);
`"open_access": {"is_oa": false, "oa_status": "closed"}`, `"best_oa_location": null`.
A conference draft exists at a University of Bath / Renmin / HKU author set; the FMA-hosted PDF
returned `404 Not Found` when fetched through the text proxy.

**Findings, effect sizes, sample, period, N: UNVERIFIED.** I retrieved only the bibliographic
record and confirmed the paper is closed access. I will not state that goodwill-to-assets
predicts lower returns with any specific magnitude — **the "goodwill predicts lower returns"
claim is NOT verified in this pack.**

Related metadata verified: the paper is indexed with keywords including *goodwill*, *intangible
assets*, *asset pricing*, *stock returns*, *CEO overconfidence*, *market underreaction*, which is
consistent with (but does not prove) a returns-prediction result.

### D.6 Caveats

1. **Impairments are lagged and discretionary.** Hayn & Hughes: 3–4 year average lag, up to
   10 years for a third of firms; Li et al. find indirect evidence of discretion to *avoid*
   taking losses. Any marker that waits for the impairment print is late by construction.
2. **The mechanism is overpricing, not goodwill per se.** Gu & Lev attribute write-offs to
   overpriced acquirer shares, which couples Marker D back to valuation/market-timing, and is
   hard to separate from the asset-growth and issuance effects.
3. **Reporting-regime breaks.** SFAS 142 (2001/2002) abolished amortisation; Li et al. find the
   announcement reaction is *lower* post-SFAS-142. Long-window backtests straddling 2002 mix two
   regimes.
4. **Post-publication replication status: UNVERIFIED** for all of D. I did not retrieve a
   replication study for any of these papers.

### D.7 XBRL computability — **high (the best of all five markers)**

| Marker | Formula | us-gaap elements |
|---|---|---|
| Goodwill-to-assets | Goodwill / Assets | `us-gaap:Goodwill`, `us-gaap:Assets` |
| Goodwill build-up from deals | Goodwill acquired in period | `us-gaap:GoodwillAcquiredDuringPeriod` (fallback: `ΔGoodwill` + `GoodwillImpairmentLoss`) |
| Impairment (goodwill only) | — | `us-gaap:GoodwillImpairmentLoss` |
| Impairment (broader) | — | `us-gaap:AssetImpairmentCharges` (also `us-gaap:ImpairmentOfIntangibleAssetsExcludingGoodwill`, `us-gaap:ImpairmentOfIntangibleAssetsIncludingGoodwill`) |
| Deal consideration (to test overpayment) | — | `us-gaap:BusinessCombinationConsiderationTransferred1` / `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` |
| Net assets acquired (for the goodwill residual) | — | `us-gaap:BusinessCombinationRecognizedIdentifiableAssetsAcquiredAndLiabilitiesAssumedNet` |

Practical notes, all of which are standard XBRL/EDGAR behaviour rather than sourced claims:
`Goodwill` and `Assets` are *instantaneous* facts (as-of dates); `GoodwillImpairmentLoss` is a
*duration* fact and is YTD in interim filings. `GoodwillAcquiredDuringPeriod` is **not**
universally tagged — many filers only disclose acquired goodwill in the business-combination
note, so a large fraction of firms must fall back to `ΔGoodwill + GoodwillImpairmentLoss ± FX`.

**Verification blocked:** the SEC XBRL API request I attempted returned
[HTTP 403](https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/Goodwill.json)
(SEC automated-tool policy). Element names above should be confirmed against
`https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/<Tag>.json` with a declared
`User-Agent`, or against the SEC's Financial Statement Data Sets. **UNVERIFIED at the
machine level in this session.**

---

## Marker E — Serial acquirers (both sides)

### E.1 Definition

There is **no single definition** in the literature. Two are used in the sources I retrieved:

* **Academic (deal-count):** firms that acquire **five or more** public, private and/or
  subsidiary targets within a short time period (Fuller, Netter & Stegemoller 2002).
* **Practitioner (cadence):** "**serial acquirers** (i.e., made **at least one acquisition every
  year for three consecutive years**)" (L.E.K. Consulting).

### E.2 Negative / mixed evidence

**(i) Fuller, Netter & Stegemoller (2002)**, "What Do Returns to Acquiring Firms Tell Us?
Evidence from Firms That Make Many Acquisitions", *JF* 57(4):1763-1793.
[Semantic Scholar](https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/1540-6261.00477?fields=title,year,abstract,openAccessPdf)
confirms `"openAccessPdf": {"url": "", "status": "CLOSED"}`; the abstract was retrieved from
[RePEc](https://ideas.repec.org/a/bla/jfinan/v57y2002i4p1763-1793.html), verbatim:

> "We study shareholder returns for firms that acquired **five or more** public, private, and/or
> subsidiary targets within a short time period. Since the same bidder chooses different types
> of targets and methods of payment, any variation in returns must be due to the characteristics
> of the target and the bid. Results indicate **bidder shareholders gain when buying a private
> firm or subsidiary but lose when purchasing a public firm**. Further, **the return is greater
> the larger the target and if the bidder offers stock.**"

**Exact coefficients / sample period / N: UNVERIFIED** (paywalled, no repository copy). What is
verified is the *design* (5+ acquisitions, single-bidder within-firm comparison) and the
*directions*.

**(ii) The declining-CAR stylised fact.** From the retrieved full text of
Aktas, de Bodt & Roll ([CaltechAUTHORS copy](https://authors.library.caltech.edu/records/0st3a-r6494/files/SSRN-id1483595.pdf)),
verbatim:

> "Several recent articles devoted to serial acquisitions note a commonly reported stylized
> fact, namely, **the declining trend in acquirers' cumulative abnormal returns (CARs) during
> mergers and acquisitions (M&A) programs** (Fuller et al., 2002; Conn et al., 2004; Croci,
> 2005; Ahern, 2008; Ismail, 2008), **even after controlling for CEO effects** (Billett and
> Qian, 2008)."

**(iii) Aktas, de Bodt & Roll (2011)** — this is the key "learning vs hubris" paper, and I
retrieved the **full working-paper text**.

* Citation: *Journal of Corporate Finance* 17(1):18-32 (2011), DOI
  `10.1016/j.jcorpfin.2010.07.002`. [CaltechAUTHORS record](https://authors.library.caltech.edu/records/0st3a-r6494);
  [EconPapers record](https://econpapers.repec.org/paper/haljournl/hal-02312633.htm).
* **Sample (verbatim):** "a sample of CEOs of U.S. firms who have undertaken **two successive
  deals with sizeable U.S. public targets within a 12-month period between 1992 and 2007**. The
  total number of deals ranges from **568 to 630**, and the CEO sample ranges from **152 to 164**
  persons". (The paper states aggregate deal value "ranges from $453 to $589 trillion" — this is
  an obvious unit error in the draft; I quote it exactly rather than "fixing" it.)
* **Exact effect size, verbatim:**

  > "This dynamic adjustment is economically significant: **In reaction to a decrease of one
  > standard deviation in abnormal returns after their previous deal announcement, CEOs reduce
  > their bids by 4.27% in the subsequent deal. This shift corresponds to a bid premium
  > percentage change of –12% from one deal to the next.**"
* Regression detail (Table 3): persistence coefficient on lagged premium `0.224` (p = 0.00);
  `Premium(d−1) × SCAR(d−1) = 0.169` (p = 0.00); marginal effect of SCAR `4.27%` (p = 0.04);
  N = 194, adjusted R² = 26.81%.
* **Raw CAR levels (Table 1, Panel D, N = 381):** mean acquirer CAR **−1.10%** on deal *d* vs
  **−0.12%** on deal *d−1* (p = 0.24); median **−1.31%** vs **−0.78%**. So the *deal-to-deal
  decline* is visible in raw CARs but not statistically significant in this sample.
* **Conclusion, verbatim:** "Our results are consistent with learning; CEOs appear to
  acknowledge the signals that investors send and dynamically adjust their bidding from deal to
  deal." And: "**both rational and hubristic CEOs learn on average from market signals.**"
* **Authors' own caveat, verbatim:** "**Netter et al. (2010) uncover a different pattern of the
  global M&A market activity in their sample of 250,000 deals in comparison to a sub-sample
  focusing on large transactions between listed firms; therefore, the composition of our M&A
  samples ... suggests the need for caution before generalizing the results to an overall CEO
  population.**"

**(iv) Broad counter-evidence to acquirer value creation** — from the retrievable Moeller et al.
NBER papers (Marker A above): 12,023 acquisitions, 1980–2001, aggregate dollar NPV
`−$218.593 billion`, driven by large acquirers; and `−$239,954m` for 1998–2001 alone. Also,
per w9523, the **long-run** calendar-time alpha for all acquirers is `−0.041%`/month and
insignificant.

### E.3 Positive / skilled-acquirer evidence

**(i) L.E.K. Consulting (2026)** — *Keys to M&A Success: How Serial Acquirers Drive
Outperformance*, Executive Insights.
[Full PDF retrieved via text proxy](https://www.lek.com/sites/default/files/2026-08/keys-to-m%26a-success-how-serial-acquirers-drive-outperformance-ei.pdf)
(the [HTML landing page](https://www.lek.com/insights/post-merger-integration/keys-ma-success-how-serial-acquirers-drive-outperformance)
truncates before the numbers).

* **Methodology as disclosed (verbatim):** source is "CapIQ; company websites; L.E.K. M&A and
  synergy database". **Sample: "more than 5,400 publicly traded companies over the period"**,
  US-based, **2016–2025**, annualized total shareholder return.
* **Definition:** "**only 8% of companies qualified as 'serial acquirers' (i.e., made at least
  one acquisition every year for three consecutive years)**".
* **Exact effect sizes (verbatim):**

  > "From 2016 to 2025, companies that engaged in M&A outperformed companies that pursued an
  > organic-only growth agenda by **4%** in terms of average total shareholder return (TSR)."

  > "Serial acquirers ... outperformed those companies that only engage in M&A occasionally by
  > **more than 11%** and organic-only companies by **more than 14%** on a weighted-average TSR
  > basis."

  > "Serial acquirers executing bolt-on transactions that did not announce synergies
  > outperformed serial acquirers that did announce synergies."

  > "serial acquirers that publicly committed to synergy targets delivered **1.4% higher TSR** on
  > average".
* **Deal-size breakdown (verbatim):** bolt-on / significant investment / MOE, and
  "**serial acquirers and non-serial acquirers alike struggle to consistently deliver value in
  larger, more-transformative deals**", with MOE TSR outcomes "from **(18%) to +28%** for serial
  acquirers and **(40%+) to 30%** for non-serial acquirers".
* **The study's own identification caveat, verbatim — this is decisive:**

  > "Note: TSR=total shareholder returns; **while there may be correlated factors between serial
  > acquirers and prior financial success (strong underlying growth and profitability enables
  > M&A and could, in theory, mask value destruction via M&A)**, the impact of disciplined
  > corporate development and integration execution on overall value creation success remains
  > apparent; **our experience suggests it is causal, not incidental**"

  → i.e. **no causal identification, and the caveat now cited is admitted by the authors
  themselves.** Also note this is **TSR, not risk-adjusted alpha**: high-beta / growth-tilted
  acquirers would show higher raw TSR in a bull decade without any abnormal performance.

**(ii) "Extraordinary acquirers"** — a conference draft was surfaced
([NTU conference proceedings PDF](http://www.fin.ntu.edu.tw/~conference/conference2012/proceedings/files/A103_Extraordinary%20acquirers%20prelim%2012.pdf))
but I did not retrieve it. **UNVERIFIED.**

**(iii) Any academic "serial acquirer factor" with reported alphas — UNVERIFIED.** I found no
retrieved academic paper constructing a serial-acquirer portfolio and reporting an alpha. The
positive side of the ledger in this pack rests entirely on the L.E.K. study, which is a
consultancy study without causal identification, and on Aktas et al.'s *learning* mechanism
(which is about bidding behaviour, not about abnormal returns to shareholders).

### E.4 Verdict table

| Claim | Status |
|---|---|
| Acquirers of public firms earn negative announcement CARs; private/subsidiary targets positive | **Robust across independent samples** (MSS w9523 12,023 deals 1980–2001: public `−1.020%`; FNS 2002 abstract agrees) |
| Acquirer CARs decline deal-to-deal in acquisition programmes | **Robust as a stylised fact** (Aktas et al. list five independent papers + Billett & Qian) but **raw decline is insignificant in Aktas et al.'s own N=381** |
| Serial acquirers outperform on TSR | **Single-source consultancy claim**, no causal identification, TSR not alpha (L.E.K.) |
| CEOs learn and reduce bids after bad market reactions | **Single-paper finding** (Aktas, de Bodt & Roll 2011), authors caution against generalising from 568–630 deals |
| "Five or more acquisitions" is a value-destructive marker per se | **Not supported** — FNS find gains on private/subsidiary targets; the loss is concentrated in public-target acquisitions |

### E.5 Caveats

1. **Definition risk is the whole ballgame.** "5+ deals" (FNS) and "≥1 deal/year for 3 years"
   (L.E.K.) select different firms; results are not comparable.
2. **L.E.K.'s serial-acquirer group is a survivorship-and-success-selected set.** The study
   concedes reverse causality may operate.
3. **Aktas et al. use only *large US public targets* and *two successive deals within 12
   months*** — not the same population as a mid-market bolt-on programme.
4. **Sign convention trap:** the same stylised fact (declining CARs) is used by FNS/Croci as
   evidence of hubris and by Aktas et al. as consistent with rational learning. The data cannot
   distinguish them without a structural model.

### E.6 XBRL computability — **medium**

| Input | us-gaap element | Notes |
|---|---|---|
| Deal count | `us-gaap:BusinessCombinationConsiderationTransferred1` (as a **fact count** across accessions) | Counting distinct business-combination disclosures per year approximates deal count, but **materiality thresholds** mean small deals are simply not tagged — this **understates** serial-acquirer status vs. SDC |
| Deal size for cadence thresholds | same element, plus `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` | Cash-flow element (YTD in interims) |
| Acquisition frequency ratio | `AcquisitionSpend / us-gaap:Assets` | Derived |
| Post-deal performance | — | Not XBRL-derivable (needs returns) |

**Bottom line for XBRL:** you can build a defensible "acquisition cadence" screen from XBRL
(years with a material business-combination tag), but you **cannot** reproduce either the FNS
"5+ deals" sample or the L.E.K. serial-acquirer universe, because both rely on deal-level
databases (SDC/CapIQ) with no XBRL materiality floor.

---

## Consolidated XBRL tag map

| Marker | Computable? | Core tags |
|---|---|---|
| **A. Announcement CAR / long-run BHAR** | **No** | Only denominators: `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`, `us-gaap:BusinessCombinationConsiderationTransferred1`, `us-gaap:Assets` |
| **B. FCF × low-q empire building** | **Yes** | `us-gaap:NetCashProvidedByUsedInOperatingActivities`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:Assets`, `us-gaap:StockholdersEquity` (+ market cap from prices) |
| **C. Acquisition / capex / asset intensity** | **Yes** | `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired`, `us-gaap:PaymentsToAcquirePropertyPlantAndEquipment`, `us-gaap:Assets`, `us-gaap:Revenues` |
| **D. Goodwill build-up and impairment** | **Yes** | `us-gaap:Goodwill`, `us-gaap:Assets`, `us-gaap:GoodwillImpairmentLoss`, `us-gaap:AssetImpairmentCharges`, `us-gaap:GoodwillAcquiredDuringPeriod`, `us-gaap:BusinessCombinationConsiderationTransferred1`, `us-gaap:OperatingIncomeLoss` (for post-deal operating performance) |
| **E. Serial-acquirer cadence** | **Partial** | `us-gaap:BusinessCombinationConsiderationTransferred1` (fact counts), `us-gaap:PaymentsToAcquireBusinessesNetOfCashAcquired` |

**Two operational XBRL warnings, both structural:**
1. **Interim periods are YTD.** Cash-flow elements (`PaymentsToAcquireBusinessesNetOfCashAcquired`,
   `PaymentsToAcquirePropertyPlantAndEquipment`, `NetCashProvidedByUsedInOperatingActivities`)
   must be differenced across consecutive interim periods, never summed.
2. **Materiality floor.** XBRL only contains what the filer deemed material enough to tag. A
   deal-count screen built from XBRL is systematically biased toward large acquirers relative to
   SDC/CapIQ-based academic samples — which is exactly the population where Moeller et al. find
   the value destruction (w9523: small firms `+$8bn`, large firms `−$226bn`).

**UNVERIFIED at machine level:** I could not query the SEC XBRL API from this session
([HTTP 403](https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/Goodwill.json),
SEC automated-tool policy). The tag names above are the standard `us-gaap` element names; confirm
them against `data.sec.gov` with a declared `User-Agent` before building a production pipeline.

---

## SOURCES FETCHED

Every URL below was successfully retrieved with `web_fetch` (HTTP 200) in this session.

**Primarily retrieved full-text / PDF sources**
1. https://www.nber.org/system/files/working_papers/w10200/w10200.pdf — Moeller, Schlingemann & Stulz, NBER WP 10200 (pub. JF 2005)
2. https://www.nber.org/system/files/working_papers/w9523/w9523.pdf — Moeller, Schlingemann & Stulz, NBER WP 9523 (pub. JFE 2004)
3. https://www.nber.org/system/files/working_papers/w9951/w9951.pdf — Titman, Wei & Xie, NBER WP 9951 (pub. JFQA 2004)
4. https://idoc.pub/documents/jensen-free-cash-flows-aer86-k5460xpy6x48 — Jensen (1986) AER 76(2):323-329 full text
5. https://authors.library.caltech.edu/records/0st3a-r6494/files/SSRN-id1483595.pdf — Aktas, de Bodt & Roll (2011) JCF working paper, full text
6. https://www.lek.com/sites/default/files/2026-08/keys-to-m%26a-success-how-serial-acquirers-drive-outperformance-ei.pdf — L.E.K. Executive Insights (serial acquirers)
7. https://link.springer.com/article/10.1007/s11142-011-9167-2 — Li, Shroff, Venkataraman & Zhang (2011) RAST abstract

**Metadata / abstract records retrieved**
8. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/j.1540-6261.1992.tb04674.x?fields=title,year,abstract,openAccessPdf,externalIds
9. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/j.1540-6261.1997.tb02741.x?fields=title,year,abstract,openAccessPdf,externalIds
10. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1016/S0304-405X(98)00023-3?fields=title,year,abstract,openAccessPdf,externalIds
11. https://api.semanticscholar.org/graph/v1/paper/DOI:10.1111/1540-6261.00477?fields=title,year,abstract,openAccessPdf
12. https://api.unpaywall.org/v2/10.1111/j.1540-6261.1992.tb04674.x?email=awltux.research@gmail.com
13. https://api.unpaywall.org/v2/10.1016/S0304-405X(98)00023-3?email=awltux.research@gmail.com
14. https://api.unpaywall.org/v2/10.1016/j.jfineco.2003.07.002?email=awltux.research@gmail.com
15. https://api.unpaywall.org/v2/10.1111/j.1540-6261.1997.tb02741.x?email=awltux.research@gmail.com
16. https://api.openalex.org/works?search=invisible%20burden%20goodwill%20cross-section%20of%20stock%20returns&per-page=3
17. https://api.openalex.org/works?search=Causes%20and%20consequences%20of%20goodwill%20impairment%20losses&per-page=3
18. https://api.openalex.org/works?search=Overpriced%20shares%20ill-advised%20acquisitions%20and%20goodwill%20impairment&per-page=3
19. https://api.openalex.org/works?search=Leading%20indicators%20of%20goodwill%20impairment&per-page=3
20. https://api.openalex.org/works?filter=doi:10.1111/j.1540-6261.2008.01370.x&select=id,doi,title,publication_year,best_oa_location,abstract_inverted_index
21. https://ideas.repec.org/a/bla/jfinan/v57y2002i4p1763-1793.html — Fuller, Netter & Stegemoller (2002) record + abstract
22. https://ideas.repec.org/a/bla/stratm/v25y2004i2p187-200.html — King, Dalton, Daily & Covin (2004) record + abstract
23. https://ideas.repec.org/a/bla/jfinan/v63y2008i4p1609-1651.html — Cooper, Gulen & Schill (2008) record + abstract
24. https://ideas.repec.org/a/eee/jfinec/v73y2004i2p201-228.html — Moeller, Schlingemann & Stulz (2004) record (no abstract)
25. https://econpapers.repec.org/paper/haljournl/hal-02312633.htm — Aktas, de Bodt & Roll (2011) record
26. https://authors.library.caltech.edu/records/0st3a-r6494 — Aktas et al. CaltechAUTHORS record
27. https://research.dial.uclouvain.be/entities/publication/bb1496c9-94ba-4c48-ac7b-3c1038c716a5 — Aktas et al. (learning hypothesis) record
28. https://www.lek.com/insights/post-merger-integration/keys-ma-success-how-serial-acquirers-drive-outperformance — L.E.K. landing page (truncated)
29. https://researchcommons.waikato.ac.nz/bitstreams/b3966644-26e8-4525-a7e4-4156e7c550c1/download — Yaghoubi (2014) PhD thesis, M&A literature review (secondary)

**Fetched but returned an error / blocked (recorded so they are not mistaken for sources)**
30. https://data.sec.gov/api/xbrl/companyconcept/CIK0000789019/us-gaap/Goodwill.json — HTTP 403 (SEC automated-tool policy)
31. https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1992.tb04674.x — bot check (no content)
32. https://hub.hku.hk/handle/10722/278792 — HTTP 403
33. https://www.fmaconferences.org/Vietnam/Papers/The%20Invisible%20Burden%20Goodwill%20and%20the%20Cross-Section%20of%20Stock%20Returns.pdf — HTTP 404
34. https://pages.stern.nyu.edu/~eofek/InvBank/papers/PerspectivesOnMergers_JEP.pdf — HTTP 404
35. https://www.business.unsw.edu.au/About-Site/Schools-Site/Accounting-Site/Documents/Ross%20Watts_paper.pdf — rate-limited (429), not retrieved

---

## Explicit UNVERIFIED register

| Item | What is missing |
|---|---|
| Agrawal, Jaffe & Mandelker (1992) post-merger abnormal returns | Full text paywalled, no OA copy (Unpaywall-confirmed). **No effect size stated anywhere in this pack.** |
| Loughran & Vijh (1997) 5-year BHARs by payment method | Full text paywalled; abstract elided by publisher. |
| Rau & Vermaelen (1998) glamour/value split | Full text paywalled, no OA copy. |
| Moeller, Schlingemann & Stulz (2004) JFE page proofs | Substituted with the NBER w9523 working-paper numbers. |
| Andrade, Mitchell & Stafford (2001) | Not retrievable. |
| Lang, Stulz & Walkling (1989, 1991) | Not retrievable; only MSS's report that the 1991 FCF measure is insignificant in their sample. |
| Harford (1999) | Not retrievable. |
| Haleblian et al. (2009) | Not retrievable; no sample, no effect size. |
| King et al. (2004) numeric mean effect size | Abstract retrieved; tables paywalled. |
| Cooper, Gulen & Schill (2008) decile spread and any post-publication decay | Full text paywalled; no replication study retrieved. |
| Gu & Lev (2011) sample, period, N, coefficients | Full text paywalled; abstract only. |
| Li et al. (2011) sample, period, N, coefficients | Abstract only; full text behind Springer login. |
| Hayn & Hughes (2006) sample construction and prediction-model statistics | Abstract only; period (1988–1998) comes from a citation in Li et al. (2011), not from the paper. |
| Liu, Yin & Zheng, "The invisible burden" (2020) — the **goodwill-to-assets → lower returns** claim | Bibliographic record only; **this specific claim is NOT verified in this pack.** |
| Any academic serial-acquirer alpha / "extraordinary acquirers" | Not retrievable. |
| SEC XBRL element-name verification | SEC API returned HTTP 403 in this session. |
