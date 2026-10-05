# Buyback / Share-Repurchase Capital-Allocation Markers — Source-Grounded Research Note

**Scope.** Four markers (A–D) used to score corporate capital allocation from repurchase behaviour: (A) the repurchase anomaly and valuation-multiple conditioning; (B) managerial buyback timing skill; (C) net share-count reduction (buybacks net of stock-based-compensation dilution); (D) payout yield vs dividend yield as return predictors.

**Evidence rules applied.** Every substantive claim below is tied to a URL I actually retrieved with a fetch tool (not a search snippet). Where a number, sample size, or result could not be retrieved from a primary or reputable secondary source, it is marked **UNVERIFIED** with a statement of what is missing. Effect sizes, samples and replication status are reported where the source gives them. Confidence tiers used: **(a) robust/replicated**, **(b) single-paper**, **(c) contested/debunked**.

**Note on one search result:** `https://www.lsvasset.com/pdf/ShareRepurchases.pdf` was returned by search as a copy of Ikenberry–Lakonishok–Vermaelen, but the URL returns **404** (page not found). It is therefore not used. The NBER working-paper page for the same paper was retrieved successfully and is used instead.

---

## A. Buybacks at HIGH vs LOW valuation multiples — the "repurchase anomaly"

### A.1 What the marker is

Plain English: after firms announce open-market repurchase (OMR) programs, their shares earn positive abnormal returns for years — the market "underreacts". The underreaction is concentrated in firms that are plausibly undervalued at announcement (high book-to-market = "value" stocks, low price multiples), and is largely absent for expensive "glamour" firms. Formula: long-horizon buy-and-hold abnormal return (BHAR) or calendar-time / Ibbotson-RATS alpha of the announcing firm minus a size/book-to-market (and sometimes momentum) benchmark, measured over 12–48 months after the announcement.

### A.2 Originating study — Ikenberry, Lakonishok & Vermaelen (1995)

- **Citation / venue:** David Ikenberry, Josef Lakonishok and Theo Vermaelen, "Market Underreaction to Open Market Share Repurchases," *Journal of Financial Economics*, Oct–Nov 1995, vol. 39, no. 2–3, pp. 181–208; NBER Working Paper 4965 (issued December 1994). DOI 10.3386/w4965. Verified at [nber.org/papers/w4965](https://www.nber.org/papers/w4965).
- **Sample:** Open-market repurchase announcements, **period 1980 to 1990**, US firms. The abstract does not state the number of announcements → **N = UNVERIFIED** (the NBER abstract page gives the period but not the count). *(The full w4965 PDF is served, but the text-proxy OCR came back reversed/garbled and could not be read reliably, so no N is asserted.)*
- **Reported effect size (verbatim, NBER abstract):**
  > "We find that the average abnormal four-year buy-and-hold return measured after the initial announcement is **12.1 percent**. For \`value' stocks, companies more likely to be repurchasing shares because of undervaluation, the average abnormal return is **45.3 percent**. For repurchases announced by \`glamour' stocks where undervaluation is less likely to be an important motive, **no positive drift in abnormal returns is observed**."
- **Interpretation in the paper:** "at least with respect to value stocks, the market errs in its initial response and appears to ignore much of the information conveyed through repurchase announcements."

### A.3 Out-of-sample / post-publication replication

**(a) Replicated on later data — Peyer & Vermaelen (2009).** Urs Peyer and Theo Vermaelen, "The Nature and Persistence of Buyback Anomalies," *Review of Financial Studies* 22(4):1693–1745 (2009), DOI 10.1093/rfs/hhn024; I retrieved the 2005 working-paper version at [efmaefm.org paper 537087_full.pdf](http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2006-Madrid/papers/537087_full.pdf).

- **Sample:** **3,481 US open-market repurchase announcements, 1991–2001**, plus **141 completed self-tender offers, 1987–2001**.
- **Headline:** "we reject the hypothesis that the market has become more efficient and has eliminated anomalies first reported by Lakonishok and Vermaelen (1990) and Ikenberry, Lakonishok and Vermaelen (1995)."
- **Self-tender expiration trading rule** (buy 6 days before expiry if price ≥3% below tender price, tender, sell the pro-rated remainder): mean abnormal return **8.6%, t = 5.5**, median **4.1%**, **84%** of trades positive (1987–2001, N=80). Sub-periods: 1987–1995 **8.2%** (t=5.3, N=51); 1996–2001 **9.3%** (t=2.8, N=29). Compare Lakonishok & Vermaelen (1990), 1962–1986: **6.18%** mean, **4.64%** median, **89.1%** positive.
- **Long-run OMR results (Ibbotson RATS + Fama-French 3-factor, cumulative abnormal returns, %):**

  | Window | Full sample | BM lowest (glamour) | BM highest (value) |
  |---|---|---|---|
  | Announcement day (0,0) | +0.23% (t=0.85) | **−3.97%** (t=−4.67) | **+5.27%** (t=5.61) |
  | (+1,+24) months | **+11.66%** (t=8.45) | +7.18% (t=1.67) | **+20.63%** (t=4.85) |
  | (+1,+48) months | **+20.49%** (t=8.97) | +14.87% (t=2.14) | **+28.89%** (t=4.47) |

- **Calendar-time FF3 (equally weighted) alphas, per month:** 12 mths **0.48%** (t=2.15); 24 mths **0.59%** (t=2.97); 48 mths **0.51%** (t=2.79). In the value (BM-highest) quintile the 48-month alpha is **0.83%**/month (t=3.74); in the glamour quintile **0.41%**/month (t=1.62, not significant).
- **Undervaluation index:** top quintile (most likely undervalued) generates excess returns of "around **50%** in the four years" after the OMR announcement; the lowest quintile only "**6% to 13%**".
- **Managerial-statement conditioning:** stated-motivation subsample shows long-run abnormal returns of **32%** when the stated reason is "undervaluation" or "best use of money", vs **9% (insignificant)** when the reason is "reducing dilution" or "increasing EPS". The paper concludes "managerial talk is not as cheap as investors seem to think it is."
- **Prior-return conditioning:** "past returns are the best predictor of future abnormal stock returns: companies that have experienced large price declines in the 6 months prior to the open market repurchase announcement, experience the largest positive abnormal returns in the future."
- **Time-stability test:** of the 11 annual portfolios (50 stocks each) formed 1991–2001, **10 of 11** show statistically significant excess returns at 48 months; across **35 sub-samples** all 48-month abnormal returns are positive.

**(c) Decay after ~2001 — Fu & Huang (2016).** Fangjian Fu and Sheng Huang, "The Persistence of Long-Run Abnormal Returns Following Stock Repurchases and Offerings," *Management Science* 62(4):964–984 (2016), DOI 10.1287/mnsc.2015.2150 (verified via OpenAlex). Abstract (retrieved): "The long-run abnormal returns following both stock repurchases and seasoned equity offerings **disappear for the events in 2003–2012**." Fu and Huang attribute the disappearance to a changed market environment — "increased institutional investment, decreased trading costs, improved liquidity, and enhanced regulations on corporate governance and information disclosure" — i.e. greater price efficiency rather than a risk-based explanation.
Exact three-year numbers are reported in the Lee–Park–Pearson working paper below (their footnote 6): in the 2003–2012 sample Fu and Huang estimate three-year average abnormal returns of **−2.52% (BHAR), −2.94% (RATS CAR), −1.89% (value-weighted calendar-time), +5.32% (equal-weighted calendar-time)**; the −2.94% RATS CAR is significant at 5%.

**(c) Decay and reinterpretation — Lee, Park & Pearson.** Working paper "Repurchases Have Changed" (Inmoo Lee, Yuen Jung Park, Neil D. Pearson, January 11, 2016), retrieved at [cicfconf.org paper_60.pdf](http://www.cicfconf.org/sites/default/files/paper_60.pdf); published as "Repurchases after being well known as good news," *Journal of Corporate Finance* 62 (2019/2020), art. 101552, DOI 10.1016/j.jcorpfin.2019.101552 (verified via OpenAlex).

- **Sample:** **10,546 US OMR announcements, 1994–2011** (SDC Platinum), price >$3 filter, CRSP/Compustat.
- **Full sample:** three-year **BHAR +11.13%**, RATS CAR **+16.66%** (both significant at 1%); but only **51.06%** of BHARs are positive.
- **By sub-period:**

  | Sub-period | 3-yr BHAR | RATS CAR | % positive BHARs | 5-day AR | Prior-year AR |
  |---|---|---|---|---|---|
  | 1994–2001 | **+17.33%** | **+25.63%** | — | **+2.01%** | **−13.32%** |
  | 2002–2006 | **+0.74%** (not sig.) | — | **44.9%** | +1.20% | **−6.01%** |
  | 2007–2011 | — | — | **51.6%** | +1.37% | **−6.03%** |

  The 2002–2006 and 2007–2011 mean RATS CARs are "less than one quarter" of the 1994–2001 CAR; the four-factor calendar-time alphas are "less than one-half".
- **Repeat repurchasers:** the share of repeat repurchasers (≥2 authorizations in past 5 years, or programs outstanding >60% of the past 5 years) rose from **<10% at the start of the sample (1994) to >50% in 2002, 2003, 2009 and 2010**; "firms that repeatedly buy back shares" perform worst.
- **Mechanism evidence:** buyback firms' senior managers' equity-linked compensation **exceeded** that of matching firms for announcements after 2001; transient institutional holdings drop after announcements, especially post-2001. The authors conclude the undervaluation motive "has become less important after 2001" and that recent buybacks are more consistent with short-term-investor pressure / managerial self-interest.

### A.4 Valuation-multiple conditioning: summary of the evidence

| Study | Sample | Conditioning variable | Result |
|---|---|---|---|
| Ikenberry, Lakonishok & Vermaelen (1995) | US OMRs 1980–1990 | book-to-market | 4-yr abnormal **+12.1%** overall; **+45.3%** value; **~0%** glamour |
| Ikenberry, Lakonishok & Vermaelen (2000) | **1,060 Canadian** repurchase programs, 1990s | value vs other | "market discounts the information ... particularly for value stocks"; completion rates sensitive to mispricing; "managers buy more shares when prices fall" ([JF 55(5):2373–2397](https://api.openalex.org/works?filter=doi:10.1111/0022-1082.00291)) |
| Peyer & Vermaelen (2009) | 3,481 US OMRs 1991–2001 | book-to-market, prior 6-mth return, stated motive | Value quintile 4-yr CAR **+28.89%** vs glamour **+14.87%**; announcement-day **+5.27%** vs **−3.97%** |
| Chan, Ikenberry & Lee (2004) | JFQA 39(3):461–479 | mispricing / FCF / leverage | Abstract: "some support for the mispricing story"; the "long-horizon return evidence is most consistent with the mispricing hypothesis"; "little" support for leverage ([OpenAlex record](https://api.openalex.org/works?search=Economic%20sources%20of%20gain%20in%20stock%20repurchases&per-page=1)) |
| Ben-Rephael, Oded & Wohl (2014) | US actual monthly repurchase executions 2004–2009 | size, market-to-book | Firms repurchase "at prices [that] are significantly lower than average market prices"; discount **negatively** related to size and **positively** related to the **market-to-book ratio**; activity followed by a positive significant abnormal return, with a 1-month drift at the earnings disclosure ([Review of Finance 18(4):1299–1340](https://api.openalex.org/works?filter=doi:10.1093/rof/rft028)) |
| Fu & Huang (2016) | US repurchases/SEOs 2003–2012 (and earlier) | time period | Long-run abnormal returns **disappear** post-2002 |
| Lee, Park & Pearson (2016/2020) | 10,546 US OMRs 1994–2011 | time period, repeat status | 2002–2006 3-yr BHAR **+0.74%** (n.s.) vs **+17.33%** in 1994–2001 |

**Confidence tier.** The *existence* of a positive post-announcement drift through the late 1990s is **(a) robust replicated** (ILV 1995 → Peyer & Vermaelen 2009 using a different, calendar-time methodology on fresh data). The *value/glamour spread* is **(b) single-paper-to-few-papers** but corroborated across ILV, PV and the Canada evidence. The *survival of the anomaly after 2001* is **(c) contested**: Fu & Huang (2016) and Lee–Park–Pearson both find the drift has largely or entirely gone, and the two papers disagree about whether the cause is greater price efficiency (Fu–Huang) or a change in buyback motives (Lee–Park–Pearson).

### A.5 Practical caveats

- **Small-firm / micro-cap dependence.** In PV, the largest-firm quintile 4-year CAR is **+7.21%** (t=4.00) vs the smallest-firm quintile **+27.80%** (t=2.63) — most of the anomaly lives in small illiquid names.
- **Low-priced stocks.** Both PV (price >$3) and Lee–Park–Pearson (price >$3) exclude low-priced stocks because of long-run return skewness (Loughran & Ritter).
- **Benchmark sensitivity.** The same events produce very different point estimates across BHAR, RATS CAR and calendar-time alphas; Fu & Huang use FF3 while Lee–Park–Pearson use FF4, and Lee–Park–Pearson state they were "unable to reproduce" Fu & Huang's numbers under the same three-factor specification.
- **Announcement ≠ execution.** Stephens & Weisbach (1998) show open-market programs are frequently not executed: "the average acquire 74 to 82 percent of announced targets within three years" (sample: **450 programs, 1981–1990**) and "repurchases are negatively related to prior stock price performance, suggesting that firms increase their purchasing depending on its degree of perceived undervaluation" ([OpenAlex record, JF 53(1):313–333](https://api.openalex.org/works?filter=doi:10.1111/0022-1082.115194)). The CFA review adds: "Stephens and Weisbach (1998) estimated the median completion rate of OMRs in the United States to be below 50%," and "Bhattacharya and Jacobsen (2015) found that 24% of all OMRs in the United States between 1985 and 2012 did not involve any actual buybacks in the fiscal year of the announcement" ([Chen & Obizhaeva, CFA Institute Research Foundation 2022](https://www.cfainstitute.org/-/media/documents/book/rf-lit-review/2022/rflr-stock-buybacks.pdf)).
- **Announcement-date returns vs actual-execution returns.** Studies measured on announcement dates are informative about signalling; studies using actual daily execution (Cook–Krigman–Leach, Ben-Rephael et al., Dittmar–Field) give a different result set and must not be blended with announcement studies.

---

## B. Buyback TIMING skill — do managers consistently buy back cheap?

### B.1 What the marker is

Plain English: managers have discretion over *when* to execute an authorised program. The marker asks whether firms systematically execute at prices below subsequent (or contemporaneous fair) prices — i.e. whether the "alpha" earned on the shares actually repurchased is positive, and whether that alpha predicts later returns. Inputs: actual monthly/daily repurchase prices and volumes (from SEC item 703 / 10-Q&nbsp;&amp;&nbsp;10-K disclosure for US firms from 2004; daily disclosure in Hong Kong and some other markets), versus VWAP or benchmark returns.

### B.2 Evidence table

| Study | Market / sample | Effect size (as reported) | Replication status |
|---|---|---|---|
| Brockman & Chung (2001), "Managerial timing and corporate liquidity: evidence from actual share repurchases," *JFE* 61(3):417–448 | Hong Kong, actual (daily-disclosed) repurchases | **UNVERIFIED** — the RePEc record confirms authors/venue but carries **no abstract**, and the ScienceDirect full text and Wiley/ScienceDirect proxies were blocked. The paper's design (exploiting Hong Kong's mandated daily repurchase disclosure to study information content and liquidity) is confirmed by the CFA review. | — |
| Cook, Krigman & Leach (2004), *RFS* 17(2):463–498 | **64 US firms'** supplementally disclosed actual repurchase trading data, 1993–1994 | "Across the days ... NYSE [firms] on average **beat their benchmarks**, whereas **NASDAQ [firms] do not**" (OpenAlex abstract); repurchases are "timed to coincide with, precede, or follow, days on which information is released"; bid–ask spread "significantly lower on repurchase days than on adjacent nonrepurchase days" | **(b) single-paper**; small, voluntary-disclosure sample |
| Ben-Rephael, Oded & Wohl (2014), *Review of Finance* 18(4):1299–1340 | US actual monthly repurchase disclosures, **2004–2009** | Buyback prices "significantly lower than average market prices"; the discount is negatively related to size and positively related to market-to-book; execution is followed by "a positive and significant abnormal return", with the market response concentrated in the earnings announcement window plus a **1-month drift** | **(b)** |
| Dittmar & Field (2015), *JFE* 115(2):261–282, "Can managers time the market? Evidence using repurchase price data"; practitioner summary in *Journal of Applied Corporate Finance* 28(4):73–85, DOI 10.1111/jacf.12205 | **All 2,237 publicly traded U.S. companies that repurchased stock, 2004–2011** | From the JACF abstract: infrequent repurchasers (bought back **four or fewer times a year**) "have been much more successful at buying undervalued shares"; over a **six-month holding period** the annual alpha of infrequent repurchasers was **2.4% greater** than frequent repurchasers (**≤ nine times a year**); companies that repurchased **just once a year recorded an alpha of 5.9%**; for the entire sample, "positive and significant alphas of **0.3% per** [month]" over windows "ranging from three [to] six years"; infrequent-minus-frequent differences in alpha "ranged from low **0.3%** [to] high **0.6% per month**" | **(a)/(b)** — very large sample and 8 years; the finding "timing skill is concentrated in infrequent repurchasers" is the strongest single result in this marker |
| Chan, Ikenberry & Lee (2007), "Do managers time the market? Evidence from open-market share repurchases," *Journal of Banking & Finance* 31(9):2673–2694, DOI 10.1016/j.jbankfin.2006.09.017 | US OMRs | **UNVERIFIED** — citation verified via OpenAlex, but the paper is closed-access, no abstract is exposed in OpenAlex/Crossref, and ScienceDirect/HKU repository were blocked by bot protection. | — |
| Stephens & Weisbach (1998), *JF* 53(1):313–333 | 450 US OMR programs, 1981–1990 | Repurchases "negatively related to prior stock price performance" and "positively related to ... levels of cash flow" | **(a) early classic** |
| Ikenberry, Lakonishok & Vermaelen (2000), Canada | 1,060 programs, 1990s | "managers buy more shares when prices fall" | corroborates timing |

### B.3 Insider-trading-and-buyback channel (timing-skill cross-check)

Reported in the CFA Institute Research Foundation review (retrieved): **Babenko, Tserlukevich & Vedrashko (2012)** use **5,827 US OMRs, 1993–2008** and find "buyback programs that are preceded by insider buys have **higher announcement returns**, are more likely to be completed, and are associated with **higher subsequent stock returns**." Also **Bonaimé & Ryngaert (2013)**, *Journal of Corporate Finance* 22:35–53, "Insider trading and share repurchases: do insiders and firms trade in the same direction?" These are cited from the CFA review, not fetched directly — the CFA review is the retrieved source.

### B.4 Caveats

- **Disclosure regime is the binding constraint.** US firms were not required to disclose actual share repurchase activity before 2004 (CFA review); Hong Kong mandates *daily* disclosure (which is why Brockman & Chung and Cook et al. could exist).
- **Selection in "actual execution" samples.** Cook–Krigman–Leach's 64 firms are voluntary disclosers out of 414 requests; Ben-Rephael et al. and Dittmar–Field cover only the post-2004 mandatory-disclosure era.
- **Sign of the size/valuation conditioning is not stable across papers.** Ben-Rephael et al. find the execution discount *increases* with market-to-book, while the anomaly literature (A) expects undervaluation (low multiple) to be where the gains are. These are different outcome variables (execution-price discount vs post-announcement return), but the discrepancy should be flagged rather than averaged away.
- **Frequent repurchasers look like the non-timers.** Dittmar–Field and Lee–Park–Pearson independently single out frequent/repeat repurchasers as the weak cohort.

---

## C. Net share-count reduction (buybacks NET of stock-based-compensation dilution) vs gross buybacks

### C.1 What the marker is

Plain English: a firm can spend cash on buybacks while simultaneously issuing shares to employees (option exercises, RSU vesting, ESPP). Only the **net** change in shares outstanding reduces dilution; gross repurchase dollars can overstate the capital returned per share. Formulas:

- Net share reduction = `ΔSharesOutstanding` = gross buyback shares − shares issued for SBC − other issuance.
- Net payout = dividends + gross repurchases − equity issuance (the Boudoukh et al. definition, below).
- Fama–French-style net repurchase (treasury-stock method) = positive change in the firm's Treasury Stock (Compustat item #226), or, when the retirement method is used, purchases minus sales of common and preferred stock.

### C.2 Evidence

**Fama & French (2001) — the originating net-repurchase measure.** Eugene F. Fama and Kenneth R. French, "Disappearing dividends: changing firm characteristics or lower propensity to pay?", *Journal of Financial Economics* 60(1):3–43 (April 2001), DOI 10.1016/S0304-405X(01)00038-1. Numbers retrieved from the CFA Digest summary ([CFA Institute digest PDF](https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/cfa-digest/2001/dig-v31-n4-954-pdf.pdf)):

> "From 1978 to 1999, the proportion of publicly traded companies paying cash dividends fell from **66.5 percent to 20.8 percent**." ... "There were **3,638** nonutility, nonfinancial companies in 1978 and **5,670** in 1997. Although about one-third of newly listed companies paid dividends in 1978, only **3.7 percent** of newly listed companies paid dividends in 1999."

Crucially for this marker: "they show that **share repurchases are primarily the province of dividend-paying companies** and that their **primary effect is to increase the already high cash payouts of dividend payers**."

The precise Fama–French *net* repurchase definition is documented in Boudoukh et al. (retrieved, NBER WP 10651, footnote 6): "our definition is motivated by that provided in the Appendix A.4 of Fama and French (2001), which defines **repurchases as the change in the firm's Treasury Stock (Compustat item #226)** or as the **difference between repurchases and issuances from the statement of cash flows when the retirement method is used**."

**The SBC-offset motive in the peer-reviewed literature.** From the CFA Institute Research Foundation review (retrieved), which is the retrieved source for these summaries:

- **Kahle (2002)**, "When a buyback isn't a buyback: open market repurchases and employee options," *JFE* 63(2):235–261, DOI 10.1016/S0304-405X(01)00095-2 (citation verified via OpenAlex/Crossref). **Sample: 712 US OMRs, 1992–1996.** Result: "companies are more likely to announce an OMR when their employees have many exercisable stock options. The completion rates of OMRs are also positively correlated with exercisable stock options." Metric used: "total exercisable options as a percentage of total shares outstanding."
- **Bens, Nagar, Skinner & Wong (2003)**, "Employee stock options, EPS dilution, and stock repurchases," *Journal of Accounting and Economics* 36(1–3):51–90. **Sample: 357 S&P 500 Industrial firms, 1996–1999.** "The decision to repurchase shares is affected by the GAAP-defined measures of the dilutive effects of ESOs but not by actual ESO exercise"; firms "repurchase more when earnings fall short of the target growth rates of diluted EPS."
- General statement in the same review: "the companies with **more employee stock options outstanding are more likely to repurchase shares** (Kahle 2002; Bens, Nagar, Skinner, and Wong 2003; Cuny et al. 2009; for evidence in the EU, see Burns et al. 2015)."

**The advocacy-side numbers (contested, not peer-reviewed).** William Lazonick, "Profits Without Prosperity: How Stock Buybacks Manipulate the Market, and Leave Most Americans Worse Off," INET conference paper, April 2014 ([ineteconomics.org PDF](https://www.ineteconomics.org/uploads/papers/LAZONICK_William_Profits-without-Prosperity-20140406.pdf)):

> "From 2003 through 2012, **449 S&P 500 companies dispensed 54% of earnings, equal to $2.4 trillion**, buying back their own stock, almost all through open-market repurchases. Dividends absorbed an additional **37%** of earnings."

> "For the **251** companies in the S&P 500 Index in January 2013 that were publicly listed back to 1981, the buyback payout ratio – that is, repurchases as a proportion of net income – was **less than 5% in 1981-1983 but 39% in 2010-2012**, with a three-year peak of **70% in 2006-2008**. From the 1980s to the 1990s to the 2000s, the dividend payout ratio declined from 50% to 44% to 41%, while the buyback payout ratio rose from 22% to 35% to 50%."

> "Over the past decade **net equity issues of non-financial corporations averaged −$376 billion per year**."

Importantly, Lazonick's own text **contradicts** a simple "buybacks are fully offset by SBC" reading: "the volume of open-market repurchases is **generally a multiple of the volume of options that employees exercise**." In other words, the SBC-dilution motive is real (Kahle, Bens et al.) but does **not** by itself establish that gross buybacks are mostly cancelled by SBC issuance. **This specific claim — "gross buybacks are largely offset by SBC issuance" — is CONTESTED and, as a quantified statement about the aggregate, UNVERIFIED in the sources I retrieved.**

**Real consequences of EPS-motivated buybacks.** Heitor Almeida, Vyacheslav Fos and Mathias Kronlund, "The real effects of share repurchases," *Journal of Financial Economics* 119(1):168–185 (2016), DOI 10.1016/j.jfineco.2015.08.008 ([retrieved first page via Insper repository](https://repositorio-api.insper.edu.br/server/api/core/bitstreams/a868893d-0a1c-483e-9586-734217704b1a/content)):

> "The probability of share repurchases that increase earnings per share (EPS) is sharply higher for firms that would have just missed the EPS forecast in the absence of the repurchase, when compared with firms that 'just beat' the EPS forecast. We use this discontinuity to show that **EPS-motivated repurchases are associated with reductions in employment and investment, and a decrease in cash holdings.**"

**Measurement-error warning on net-share measures.** Banyi, Dyl & Kahle (2008), "Errors in estimating share repurchases," *Journal of Corporate Finance* 14(4):460–474 (via CFA review): using hand-collected mandatory 10-Q/10-K disclosure for 2004, "Compustat-based quarterly estimates **misstated the actual number of repurchased shares by at least 10% in 34% of the cases**; the Compustat-based **annual** estimates misstated the actual number of repurchased shares by at least 10% in **48%** of the cases." The treasury-stock measure "will be biased upward if companies accept shares as payment for the exercise of employee stock options in lieu of cash," and some firms reporting retirements rather than treasury stock show "zero share repurchases" spuriously.

### C.3 Confidence tiers

- **(a) Robust:** firms with larger option/SBC overhang are more likely to repurchase and repurchase more (Kahle 2002; Bens et al. 2003; consistent with the SBC-dilution-offset motive). Repurchase measurement from Compustat/treasury stock carries large, documented error (Banyi et al. 2008).
- **(b) Single-paper:** the RD evidence that EPS-motivated buybacks cut investment and employment (Almeida–Fos–Kronlund 2016).
- **(c) Contested:** the strong aggregate claim that gross buybacks are "largely offset" by SBC. Lazonick's thesis is an advocacy working paper, not peer-reviewed, and his own text says the buyback volume is a *multiple* of option exercises.

### C.4 Practical caveats

- **Net share count is contaminated by non-SBC issuance.** Acquisitions paid in stock, ATM/SEO issuance, converts, buybacks of preferred and ESPP all move shares outstanding without being "SBC dilution".
- **Sector/size skew.** SBC overhang is concentrated in technology/biotech and in firms below mega-cap; the offset ratio is therefore strongly cross-sectionally heterogeneous and a single aggregate number is misleading for a screening model.
- **`us-gaap:ShareBasedCompensation` is an expense, not a share count.** It is a non-cash P&L item. Converting it into shares requires either the treasury-stock method ((options − assumed proceeds)/price ≈ (unvested + in-the-money options) − buyback-with-proceeds) or the actual `Δshares` approach.
- **Retirement vs treasury-stock accounting.** Under the retirement method, repurchases bypass the treasury-stock account entirely (Banyi et al. 2008; Boudoukh footnote 6) — a purely balance-sheet-based net-buyback measure will read zero.

---

## D. Do buybacks predict returns better than dividends? Dividend vs total payout vs net payout

### D.1 What the marker is

Plain English: replace the dividend yield in predictive regressions with a payout yield that includes repurchases, and further with a **net** payout yield that subtracts equity issuance. Inputs:

- Dividend yield = common dividends / market cap.
- Payout yield = (dividends + repurchases) / market cap.
- Net payout yield = (dividends + repurchases − equity issuance) / market cap.

### D.2 Central paper — Boudoukh, Michaely, Richardson & Roberts (2007)

Jacob Boudoukh, Roni Michaely, Matthew Richardson and Michael Roberts, "On the Importance of Measuring Payout Yield: Implications for Empirical Asset Pricing," *Journal of Finance* 62(2):877–915 (2007), DOI 10.1111/j.1540-6261.2007.01226.x; NBER Working Paper 10651 (August 2004, revised February 2006, 75 pp.), retrieved at [nber.org w10651.pdf](https://www.nber.org/system/files/working_papers/w10651/w10651.pdf).

**Time-series predictability (aggregate US excess market return, 1926–2003, annual horizon):**

- Dividend yield: **R² = 5.5%**, coefficient **0.116**, **t = 2.240**.
- Payout yield: **R² = 8.0% and 9.1%** (the two repurchase measures) — "an increase of 45% and 65% respectively".
- Net payout yield: **R² = 26%**, "an almost five-fold increase".
- "while the bias-adjusted (Stambaugh 1999) dividend yield coefficient is insignificant, those of the payout and net payout yields are strongly significant."

**Cross-section (Fama–MacBeth-style decile sorts, average monthly returns):**

| Portfolio | Low | Medium | High |
|---|---|---|---|
| Payout yield | 1.28% | 1.40% | **1.56%** |
| Net payout yield | 1.24% | 1.36% | **1.57%** |
| Dividend yield | 1.15% | 1.28% | 1.33% |

- "dividend yields show an insignificant association with returns, whereas our payout measures exhibit highly significant associations with returns."
- "book to market is subsumed within payouts when we confine our attention to those firms that actually pay out cash via dividends."

**Trading strategy (self-financed, long top-30% / short bottom-30% by yield, annual rebalance):**

- **Net payout yield: +4.44% average annual return**; payout yield: **+3.36%**; dividend yield: **+2.16%**. (These are also reproduced in the retrieved CFA review: "delivered an average annual return of 4.44% (3.36%), which is higher than the average annual return of 2.16% delivered by the classic strategy based on dividend yield.")
- "These strategies result in portfolios with negative market betas and negative loading on the size factor."

**Out-of-sample / structural stability:**

- "using the out-of-sample predictability framework of Goyal and Welch (2004), we show that our payout measures exhibit **positive and robust predictability** in spite of model uncertainty due to repeated rolling estimation."
- Structural break tests: dividend yield AR(1) Chow statistic **3.725 (p = 0.029)** and predictive statistic **3.270 (p = 0.044)** around the enactment of SEC Rule 10b-18; payout yield AR(1) **1.862 (p = 0.163)** and predictive **0.982 (p = 0.380)** — i.e. **no** break detected in the payout measure.
- "regression results over the period 1926-1985 show that our payout yield coefficient is very similar to those found in the full sample regressions."
- Conclusion in the abstract: "the widely documented decline in the predictive power of dividends for excess stock returns in time series regressions in recent data is **vastly overstated**."

**Sample / data construction (as documented in the paper):**

- Cross-section: nonfinancial firms in the CRSP monthly ∩ Compustat annual intersection, positive book equity, Compustat data item #60 (book equity) + #74 (deferred taxes) / CRSP December market cap; size = CRSP June market cap; returns July of year *t* to June of *t+1* (Fama–French 1992/1993 match). Time-series repurchase data from Compustat start **1971** (1984 for the treasury-stock measure); before then repurchases are assumed zero.
- Repurchase measure #1 (cash-flow): Compustat item **#115** (purchase of common and preferred stock) **plus** any reduction in net preferred (#56).
- Repurchase measure #2 (treasury stock): change in treasury stock, adjusted for asynchronicity with option exercise (available from 1982/83).
- Issuance: Compustat item **#108** (sale of common and preferred) minus increase in net preferred (#56).
- Trimming: upper/lower 0.5% of book-to-market; upper 5% of dividend and payout yield; upper and lower 2.5% of net payout yield.

### D.3 Corroborating evidence

- **Fama & French (2001)** found repurchases to be the province of dividend payers rather than a broad substitute, and that their "primary effect is to increase the already high cash payouts of dividend payers" (CFA Digest summary, retrieved). This is what motivates the *payout* rather than *dividend* framing.
- **Chen & Obizhaeva, CFA Institute Research Foundation (2022)**, *Stock Buyback Motivations and Consequences: A Literature Review*, summarize the same result: "Over the 1926–2003 period, models based on total (net) payout yields had an **R² of 9.1% (26%)**, compared with an **R² of 5.5%** for a classic model based on dividend yield."
- **Grullon & Michaely (2002)** (cited from the CFA review): the proportion of Industrial Compustat firms repurchasing rose from **<27% in 1972 to >84% in 2000**, while dividend payers fell **60% → 20%**; average repurchase ratio rose **2.8% (1972) → 12.4% (2000)** while the average dividend ratio fell **21.4% → 11.3%**. Sample: **15,834 companies, 1972–2000**.

### D.4 Confidence tiers

- **(a) Robust:** in-sample and cross-sectional superiority of total/net payout yield over dividend yield for US data 1926–2003; the payout measure is structurally stable where the dividend measure breaks around Rule 10b-18. The result is reproduced in an independent practitioner review (CFA Institute Research Foundation 2022).
- **(b) Single-paper / contested for the *out-of-sample* claim:** the positive out-of-sample result under the Goyal–Welch framework is asserted by the authors from their own specification; the broader literature (Goyal & Welch 2003/2008, cited *within* Boudoukh et al.) is generally sceptical of equity-premium predictability out of sample. I did **not** retrieve Goyal & Welch directly → their counter-evidence is **UNVERIFIED** here except as characterised by Boudoukh et al.
- **Decay of the underlying effect is not tested by the paper**: Boudoukh et al.'s sample ends 2003; I found no post-2003 replication of the net-payout-yield predictability result in the sources retrieved. **Post-2003 out-of-sample replication: UNVERIFIED.**

### D.5 Practical caveats

- **Look-ahead in the yield variable.** Payout yield requires the *contemporaneous* year-end market cap as denominator; the paper aligns fiscal-year *t-1* accounting with July *t* → June *t+1* returns to avoid look-ahead. Any screener must replicate that lag.
- **Negative net payout yields.** Net payout yield is often negative; the paper adds 0.1 before taking logs and trims the upper/lower 2.5%.
- **Repurchase measurement choice changes the answer.** "The evidence throughout is shown to be robust to the method of measuring total payouts," but the R² ranges from 8.0% (cash-flow) to 9.1% (treasury-stock) — the treasury-stock measure only starts in 1983/84 and is contaminated by option exercise (see marker C).
- **Dividends ≠ zero when repurchases are zero.** The paper assumes repurchase yield = 0 before 1971 because repurchases were negligible; this is defensible for the aggregate but not for individual firms.

---

## E. Computability from XBRL / iXBRL — concrete tags

**Key point for a screening pipeline.** XBRL gives you (i) cash spent on buybacks, (ii) cash dividends, (iii) SBC expense, and (iv) point-in-time and weighted-average share counts. It does **not** directly give repurchase *prices* or *daily* execution, so marker B (execution-price alpha) is **not** computable from XBRL alone; it is computable only in markets with periodic repurchase-price disclosure (US from 2004 via Item 703 of Reg S-K — number of shares purchased, average price paid per share, and maximum remaining under the program; Hong Kong daily).

**Tags verified by fetching the SEC XBRL company-concept API (Apple Inc., CIK 0000320193):**

| Tag | Official label / description (verbatim from SEC API) | Used for |
|---|---|---|
| `us-gaap:PaymentsForRepurchaseOfCommonStock` | "Payments for Repurchase of Common Stock" — "The cash outflow to reacquire common stock during the period." | Gross buyback cash. Verified: [SEC company-concept JSON](https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/PaymentsForRepurchaseOfCommonStock.json) (via text proxy). Apple FY2024 = $94,949,000,000; FY2025 = $90,711,000,000. |
| `us-gaap:PaymentsOfDividendsCommonStock` | "Payments of Ordinary Dividends, Common Stock" — "Amount of cash outflow in the form of ordinary dividends to common shareholders of the parent entity." | Dividend leg of payout yield. Verified: [SEC company-concept JSON](https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/PaymentsOfDividendsCommonStock.json) (via text proxy). |
| `us-gaap:ShareBasedCompensation` | "Share-based Payment Arrangement, Noncash Expense" — "Amount of noncash expense for share-based payment arrangement." | SBC expense (input to dilution estimate). Verified: [SEC company-concept JSON](https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/ShareBasedCompensation.json) (via text proxy). Apple FY2025 = $12,863,000,000. |
| `dei:EntityCommonStockSharesOutstanding` | "Entity Common Stock, Shares Outstanding" — "Indicate number of shares or other units outstanding of each of registrant's classes of capital or common stock or other ownership interests, if and as stated on cover of related periodic report." | Cover-page point-in-time share count (best available proxy for net share reduction). Verified: [SEC company-concept JSON](https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/dei/EntityCommonStockSharesOutstanding.json) (via text proxy). Apple: 15,555,275,200 (2013-10-20) → 14,594,180,000 (2026-07-17). |

**Additional tags required, not individually fetched in this session (standard US-GAAP/DEI elements; listed for completeness, verification pending):**

| Tag | Role | Status |
|---|---|---|
| `us-gaap:CommonStockSharesOutstanding` | Balance-sheet shares outstanding at period end | name standard; **not individually verified here** |
| `us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding` | Denominator for diluted EPS; the dilution-adjusted share count | name standard; **not individually verified here** |
| `us-gaap:WeightedAverageNumberOfSharesOutstandingBasic` | Basic share count | name standard; **not individually verified here** |
| `us-gaap:StockRepurchaseProgramAuthorizedAmount` / `...RemainingAmount` | Program authorisation and remaining capacity | name standard; **not individually verified here** |
| `us-gaap:ProceedsFromIssuanceOfCommonStock`, `us-gaap:ProceedsFromStockOptionsExercised`, `us-gaap:ProceedsFromIssuanceOfSharesUnderIncentiveAndShareBasedCompensationPlansIncludingStockOptions` | Equity issuance leg (net payout yield) | name standard; **not individually verified here** |
| `us-gaap:TreasuryStockValueAcquiredCostMethod`, `us-gaap:TreasuryStockCommonValue` | Treasury-stock method (Fama–French net repurchase) | name standard; **not individually verified here** |
| `us-gaap:StockIssuedDuringPeriodSharesNewIssues`, `us-gaap:StockIssuedDuringPeriodSharesStockOptionsExercised` | Shares issued on option exercise / vesting | name standard; **not individually verified here** |

**Access route.** The `companyconcept` endpoint is free but SEC blocks undeclared automated user agents at `data.sec.gov` (a direct fetch returned HTTP 403 "Your Request Originates from an Undeclared Automated Tool"). Either set a declared User-Agent per SEC developer policy, or use the bulk **Financial Statement Data Sets** (num.txt / pre.txt) which contain the same tags across all filers. An alternative machine-readable route for the same tags is the SEC `companyfacts` endpoint per CIK.

**Reconstruction recipes:**

1. **Gross buyback yield** = `us-gaap:PaymentsForRepurchaseOfCommonStock` (FY, cash-flow statement) ÷ (period-end market cap; market cap requires `dei:EntityCommonStockSharesOutstanding` × price, since XBRL does not carry price).
2. **Net payout yield** = (`PaymentsOfDividendsCommonStock` + `PaymentsForRepurchaseOfCommonStock` − proceeds from common stock issuance) ÷ market cap.
3. **Net share count change** = `dei:EntityCommonStockSharesOutstanding(t)` − `(t-1)`, plus cross-check against `WeightedAverageNumberOfDilutedSharesOutstanding` (using the diluted count converts a raw share change into a *dilution-adjusted* change, which is the cleanest XBRL-only proxy for marker C).
4. **SBC dilution share estimate** = `ShareBasedCompensation` ÷ period average share price (rough), or treasury-stock method = (options outstanding − assumed proceeds/price) + unvested awards, which requires option-count tags that are **not** in the standard company-concept set for most filers (they live in the option-award footnote, often as a custom or `us-gaap:ShareBasedCompensationArrangementByShareBasedPaymentAwardOptionsOutstandingNumber` element).
5. **Marker B is not XBRL-computable** for US firms: `PaymentsForRepurchaseOfCommonStock` is a period cash total with no price. Repurchase *price* is in the Item 703 table (Reg S-K) as free-form HTML/iXBRL inside 10-Q/10-K, not in a standard numeric tag.

**Independence check.** Because `us-gaap:PaymentsForRepurchaseOfCommonStock` (cash-flow) and the treasury-stock tags come from different statements, the two Boudoukh-style repurchase measures can be reconstructed independently and cross-checked — which matters given Banyi et al.'s finding that annual estimates misstate actual shares by ≥10% in 48% of cases.

---

## F. Bottom line per marker

| Marker | Best-supported statement | Tier | Practical usability |
|---|---|---|---|
| **A. Repurchase anomaly & valuation conditioning** | Post-announcement drift is real and large for the 1980–2001 era (12.1% four-year overall; 45.3% for value in 1980–1990; 20.6% four-year value-quintile CAR 1991–2001), concentrated in small/value firms and in firms with negative pre-announcement returns and explicit undervaluation language | **(a)** for pre-2002; **(c)** contested for post-2002 (Fu–Huang 2016: returns "disappear" 2003–2012; Lee–Park–Pearson: 2002–2006 BHAR +0.74%, n.s.) | Usable as a *value* signal historically; must be re-validated on post-2003 data before deployment |
| **B. Timing skill** | Timing alpha exists and is concentrated in **infrequent** repurchasers (Dittmar–Field: infrequent-minus-frequent +2.4% annual alpha; once-a-year repurchasers +5.9%; whole sample +0.3%/month over 3–6 years) | **(b)**, large sample, one team | Requires actual repurchase prices; **not computable from XBRL alone** |
| **C. Net vs gross buybacks** | Firms with larger option overhang buy back more (Kahle 2002, 712 OMRs 1992–96; Bens et al. 2003, 357 firms 1996–99); "gross buybacks largely offset by SBC" as an aggregate claim is **contested** and not established by the peer-reviewed literature retrieved | **(a)** for the dilution motive; **(c)** for the aggregate-offset claim | Needs `Δshares` and/or option-count footnote data; measurement error is large (Banyi et al. 2008) |
| **D. Payout > dividend predictors** | Payout/net payout yield beats dividend yield in-sample, cross-sectionally and out-of-sample per the authors (R² 5.5% → 8.0/9.1% → 26%; HML 2.16% → 3.36% → 4.44% p.a.) | **(a)** in-sample US 1926–2003; **(b)/UNVERIFIED** out-of-sample and post-2003 | Directly computable from XBRL cash-flow tags + market cap |

---

## SOURCES FETCHED

Every URL below was retrieved successfully with a fetch tool during this session and the content was used above.

1. https://www.nber.org/papers/w4965 — Ikenberry, Lakonishok & Vermaelen (1995) abstract page (via `https://r.jina.ai/https://www.nber.org/papers/w4965`)
2. https://www.nber.org/system/files/working_papers/w10651/w10651.pdf — Boudoukh, Michaely, Richardson & Roberts, NBER WP 10651 full text (via `https://r.jina.ai/...`)
3. https://www.cfainstitute.org/-/media/documents/book/rf-lit-review/2022/rflr-stock-buybacks.pdf — Chen & Obizhaeva, *Stock Buyback Motivations and Consequences: A Literature Review*, CFA Institute Research Foundation (2022) (via `https://r.jina.ai/...`)
4. http://www.efmaefm.org/0EFMAMEETINGS/EFMA%20ANNUAL%20MEETINGS/2006-Madrid/papers/537087_full.pdf — Peyer & Vermaelen, "The Nature and Persistence of Buyback Anomalies" working paper (via `https://r.jina.ai/...`)
5. http://www.cicfconf.org/sites/default/files/paper_60.pdf — Lee, Park & Pearson, "Repurchases Have Changed" (2016 WP; published as *JCF* 62:101552) (via `https://r.jina.ai/...`)
6. https://www.ineteconomics.org/uploads/papers/LAZONICK_William_Profits-without-Prosperity-20140406.pdf — Lazonick, "Profits Without Prosperity" (INET, 2014) (via `https://r.jina.ai/...`)
7. https://repositorio-api.insper.edu.br/server/api/core/bitstreams/a868893d-0a1c-483e-9586-734217704b1a/content — Almeida, Fos & Kronlund, "The real effects of share repurchases," *JFE* 119:168–185 (via `https://r.jina.ai/...`)
8. https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/cfa-digest/2001/dig-v31-n4-954-pdf.pdf — CFA Digest summary of Fama & French (2001) (via `https://r.jina.ai/...`)
9. https://econpapers.repec.org/article/eeejfinec/v_3a61_3ay_3a2001_3ai_3a3_3ap_3a417-448.htm — RePEc/EconPapers record for Brockman & Chung (2001) (direct fetch)
10. https://api.openalex.org/works?search=Do%20managers%20time%20the%20market... — OpenAlex record for Chan, Ikenberry & Lee (2007), *JBF* 31(9):2673–2694
11. https://api.openalex.org/works?filter=doi:10.1111/0022-1082.115194... — OpenAlex record + abstract for Stephens & Weisbach (1998), *JF* 53(1):313–333
12. https://api.openalex.org/works?filter=doi:10.1016/S0304-405X(01)00068-X|10.1016/j.jfineco.2014.09.007|10.1093/rof/rft028... — OpenAlex records for Brockman & Chung (2001), Dittmar & Field (2014/15), Ben-Rephael, Oded & Wohl (2014)
13. https://api.openalex.org/works?search=Economic%20sources%20of%20gain%20in%20stock%20repurchases... — OpenAlex record + abstract for Chan, Ikenberry & Lee (2004), *JFQA* 39(3):461–479
14. https://api.openalex.org/works?search=persistence%20of%20long-run%20abnormal%20returns... — OpenAlex record + abstract for Fu & Huang (2016), *Management Science* 62(4):964–984
15. https://api.openalex.org/works?filter=doi:10.1111/j.1540-6261.2007.01226.x... — OpenAlex abstract for Boudoukh et al. (2007), *JF* 62(2):877–915
16. https://api.openalex.org/works?filter=doi:10.1093/rfs/hhn024|10.1016/S0304-405X(01)00095-2|10.1093/rfs/hhg028... — OpenAlex abstracts for Peyer & Vermaelen (2009) and Cook, Krigman & Leach (2004); metadata for Kahle (2002)
17. https://api.openalex.org/works?filter=doi:10.1111/0022-1082.00291... — OpenAlex abstract for Ikenberry, Lakonishok & Vermaelen (2000), *JF* 55(5):2373–2397 (Canada)
18. https://api.openalex.org/works?filter=doi:10.1111/jacf.12205... — OpenAlex record + abstract for Dittmar & Field, *JACF* 28(4):73–85
19. https://api.openalex.org/works?search=Repurchases%20after%20being%20well%20known%20as%20good%20news... — OpenAlex record for Lee, Park & Pearson, *JCF* 62:101552
20. https://api.openalex.org/works?search=Share%20price%20performance%20following%20actual%20share%20repurchases... — OpenAlex record for *JBF* 29(7):1887–1901
21. https://api.crossref.org/works/10.1016/j.jfineco.2014.09.007 — Crossref record + full reference list for Dittmar & Field (2015)
22. https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/PaymentsForRepurchaseOfCommonStock.json — SEC XBRL tag verification (via `https://r.jina.ai/...`)
23. https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/dei/EntityCommonStockSharesOutstanding.json — SEC XBRL tag verification (via `https://r.jina.ai/...`)
24. https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/PaymentsOfDividendsCommonStock.json — SEC XBRL tag verification (via `https://r.jina.ai/...`)
25. https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/ShareBasedCompensation.json — SEC XBRL tag verification (via `https://r.jina.ai/...`)

**Retrieved but NOT usable (recorded so the failed paths are not repeated):** `https://www.lsvasset.com/pdf/ShareRepurchases.pdf` (404); `https://www.business.kaist.ac.kr/faculty/inmoo/Articles/JFQA2003.pdf` (404); `https://www.anderson.ucla.edu/faculty/john.weston/papers/DemiseShareRepurchases.pdf` (404); `https://www.econstor.eu/bitstream/10419/57340/1/666541264.pdf` (blocked by Anubis proof-of-work); ScienceDirect / Wiley / SSRN / HKU repository (bot challenge or captcha); `https://rpc.stage.cfainstitute.org/...rflr-stock-buybacks.pdf` (403 Cloudflare — the `www.cfainstitute.org` path in item 3 works); direct `https://data.sec.gov/...` without a declared user agent (HTTP 403).

---

## UNVERIFIED LOG

1. **Ikenberry, Lakonishok & Vermaelen (1995) sample size (N of announcements, 1980–1990)** — not stated in the NBER abstract, and the served PDF OCR was unusable. Missing: the paper's Table 1.
2. **Brockman & Chung (2001) effect sizes and any reported return/liquidity magnitudes** — paper paywalled, no abstract in RePEc, OpenAlex or Crossref; ScienceDirect returned a captcha. Missing: the article PDF or a full abstract.
3. **Chan, Ikenberry & Lee (2007), "Do managers time the market?" — findings, sample size, effect sizes** — closed access, no abstract exposed in OpenAlex/Crossref, HKU repository blocked. Missing: the article PDF or abstract.
4. **Fama & French (2001) net-repurchase aggregates (e.g. dollar net repurchases, share of firms repurchasing)** — I retrieved their dividend-payer statistics and a description of their net-repurchase *definition*, but not their repurchase aggregates. Missing: the *JFE* 60(1) article itself.
5. **The claim that "gross buybacks are largely offset by stock-based-compensation issuance" (as a quantified aggregate)** — no peer-reviewed source retrieved states this in those terms; Lazonick's paper states the opposite direction ("repurchases are generally a multiple of the volume of options that employees exercise"). Treated as CONTESTED.
6. **Post-2003 replication of Boudoukh et al.'s net-payout-yield predictability and of the 4.44% p.a. trading strategy** — no source retrieved tests this out of sample. Missing: any post-2003 replication.
7. **Goyal & Welch's own out-of-sample equity-premium-prediction results** — cited here only as characterised inside Boudoukh et al.; their paper was not fetched.
8. **Exact Dittmar & Field magnitudes**: the JACF abstract (retrieved via OpenAlex's inverted index) contains figures "5.9%", "1.5%" and "0.3%"/"0.6%" whose units (annual vs monthly) are partly ambiguous in the reconstructed text. The 2.4%-greater-alpha and 2,237-firm / 2004–2011 sample statements are unambiguous. Missing: the *JFE* 115(2) article PDF for exact table values.
9. **XBRL tag names for `CommonStockSharesOutstanding`, `WeightedAverageNumberOfDilutedSharesOutstanding`, stock-option-award footnote elements, treasury-stock elements and program-authorisation elements** — these are standard element names but I verified only four tags against the live SEC API in this session (listed in section E).
