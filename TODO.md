# TODO

Open work on AwltuxTrading: bugs, gaps and decisions that are known and
deliberately deferred. This is the "found it, not fixing it now" list — not a
roadmap, and not a wish list.

**How this file is kept** — the full rule is `AGENTS.md` section 6. An item goes in
the moment it is found, with the evidence that found it, so nobody has to rediscover
it. Items are *deleted* when they are implemented rather than ticked off: git history
is the record of what was done, and a list of closed items stops being read. An entry
whose numbers have gone stale is corrected or deleted, because a stale item is
believed. Anything already decided against lives under **Deliberately not doing** with
the reason, so it is not re-litigated.

`tests/test_repo_hygiene.py` fails on a closed item left in place.

---

---

## Bugs

### `residual_income` compounds on a book value it has already grown, so `ok` valuations reach 1e61

Measured 2026-10-15, found while putting the fair value on the price chart: the valuation
model stores a base value **2.27e61** for `AAPL_US_EQ` against a share price of $342.96, with
`status='ok'`, `valuation_confidence` 0.70, and the range note. `BUDA_US_EQ` is 1.06e27
against $7.49 and `AREC_US_EQ` is 9.7e5 against $1.22. Three of the 73 instruments holding a
drawn valuation on that date.

`analysis/valuation.py::residual_income`, line 461:

```python
book *= 1.0 + residual / book_value if book_value else 1.0
```

`residual` is `(year_roe - ke) * book` (line 459), computed on the book value **the loop is
already growing**, and the growth factor divides by the *original* `book_value`. So the
factor is `1 + (year_roe - ke) * book / book_value`, which is itself a function of `book`:
the growth is quadratic in `book`, not linear, and ten years take it to 1e62.

The model output kept in `valuation_run.model_outputs` names the method and its inputs, which
is how this was found rather than guessed -- AAPL's last `ok` row (id 24914) holds

| method | value | inputs |
|---|---|---|
| `dcf` | 96.83 | discount 10.69%, terminal growth 2.5%, FCFF 98,767m |
| `epv` | 59.26 | normalised earnings 99,445m, ke 10.69% |
| `residual_income` | **1.21e62** | book 73,733m, starting ROE **1.519**, ke 10.69%, horizon 10 |
| `dividend_discount` | 12.77 | DPS 1.02, payout 13.7% |
| `graham` | 28.94 | excluded from the blend by weight |

The ROE is not the error: 112,010m of net income on 73,733m of book really is 152%, and
`starting_roe` records it faithfully. The arithmetic is. Dividing by `book` instead of
`book_value` grows the book at the residual *return*, which fades to the cost of equity at
the horizon; re-run outside the app with the same inputs, AAPL comes out at **$380.18** a
share against a $342.96 price (the current form reproduces the stored 1.21e62 exactly, which
is how the reading above was checked) and BUDA at 122.15 against 7.49.

**Not fixed here** because it changes every stored fair value and therefore every decision
that read one, and `blend` weights this method into the base. The chart feature that found it
refuses to *draw* a band more than 3x away from every price on the axis
(`MAX_OFFSCALE_BAND_RATIO`, `web/queries.py`) and says how many it left off, so the panel
stays readable in the meantime. Two things to check when fixing it: the `model_outputs`
recorded on the 25,393 stored rows are the evidence of what each method produced, and
repairing those rows has the same "recompute or re-derive" question
`repair_scaled_figures` answered for figures.

### Three LSE shells hold a stored close of ~1e-6, which is not a price either

Measured 2026-10-09 while fixing the unit bug that made `VWRLl_EQ` read 1.41 against a true
141.30, and **re-measured 2026-10-10** after `awltux repair-price-units` corrected the units:
these three are a different fault, and a correction of the unit does not make them right.

| ticker | broker unit | stored close before | after the repair | last fetched |
|---|---|---|---|---|
| `PFCl_EQ` (Petrofac) | GBX | 9.9999997e-06 | 9.9999997e-08 | 2026-10-05 |
| `RENEl_EQ` (ReNeuron) | GBX | 0.0011 | 1.1e-05 | 2026-10-05 |
| `SDXl_EQ` (SDX Energy) | GBX | 9.9999997e-05 | 9.9999997e-07 | 2026-10-05 |

All three are LSE names the broker says are quoted in pence, and each held 499 bars with
`raw_multiplier = 1.0` — the conversion was never applied. `repair-price-units` has now applied
it, so the rows agree with the instrument's currency, and the values are *still* not prices:
Petrofac at £0.0000001 is a suspended or delisted line, not a quotation. A uniform factor across
a whole series cancels out of every return and drawdown the markers compute, so nothing downstream
changed when the repair landed; what is missing is a check that a stored price is *plausible* at
all, which no part of the pipeline has.

Also unexplained: why the conversion was never applied on 2026-10-05, when every other LSE
instrument priced that day has `raw_multiplier = 0.01`. They have not been refreshed since — the
provider appears to return no bars for them now and `price_eod` records "the provider returned no
bars" — so the 2026-10-05 rows are the only record and they cannot be re-derived. The unit guard
refuses their bars now, so a refresh cannot make them worse.

### The news feed volume is not feed-reader traffic, and the daily ceiling now shows it

Added 2026-10-16 with the rate-limit work, and it is the *real* fix for the Google News
side rather than a rate limit. A full sweep of 500 instruments asks Google News for one
company per query — **one edition**, not two: `gather_for_instrument` picks GB or US from
`_is_uk` and does not ask both, so the "both a UK and a US edition" claim is wrong wherever
it still appears (`ingest/news.py:150` and its duplicate at `ingest/news.py:863`; the sector
poll is the one that takes both) — plus one Yahoo feed. That is about **1,000 requests**,
which is not what a feed reader does. Google publishes no quota, calls it "fair use" in its
own forum, and answers 4-digit automated volume with a 503 "automated queries" page or a
flat IP block rather than a 429.

The new budget paces that at one request every five seconds with a 2,000-a-day ceiling, so
a full sweep now takes about two hours and competes for the same day's allowance as the
eleven-sector poll (11 sectors × 2 editions × 24 runs = 528/day). **The ceiling is not what
starves the sweep** -- one sweep plus the sector poll is 1,528 of 2,000, so both fit. What
it cannot fund is the *hourly interval*: 24 sweeps a day would want 24,000 requests, so the
budget funds (2,000 − 528) / 1,000 ≈ **1.5 sweeps a day**, and coverage is that rather than
hourly.

**Measured 2026-10-08, from the other end of it.** The new hourly `held_refresh` refreshed
three holdings and every one came back with `news_rss` failed; the lease note is only
`Stopped: 1 of 1 instruments`. Asking the provider directly gives the reason --
`[rss] budget spent (2000 per 86400s); window resets in 37552s` -- so **the day's allowance
was already gone at 13:29 UTC** and nothing polls a feed again until midnight. Two things
follow that the arithmetic above does not say on its own:

- a *scoped* refresh cannot poll its instrument's feeds either, so the Refresh button's news
  step is refused for most of the day as well;
- the run is recorded as *stopped*, which is the same word a deploy produces, so the
  Operations page shows the day's news quietly ending and nothing distinguishes it from an
  upgrade. `README.md`'s "News headlines | 1–5 minutes" is likewise wrong after the ceiling
  is reached, which on this measurement is early afternoon.

**Pooling companies into one query does not work, measured 2026-10-07.** The plan above
was "twenty companies in one query, ~1,200 requests to ~60". Tried against the live
endpoint with real universe names, parenthesised `("A" OR "B") stock`:

| companies pooled | items returned | companies visible in them |
|---|---|---|
| 1 | 99 | 1/1 |
| 2 | 99 | 2/2 |
| 4 | 99 | 3/4 |
| 5 | 99 | 4/5 |
| 6 | 99 | 3/6 |
| 8 | 99 | 4/8 |
| **10** | **27** | **1/10** |
| **20** | **26** | **1/20** |

Two independent limits, and neither is the query syntax (dropping the parentheses gives
the same 26 items, and rotating the order moves *which* company survives rather than
fixing it):

- **Google News caps a response at ~100 items.** A single company already returns 99, so a
  pool of N shares that same 100 between N companies — pooling trades depth for breadth,
  it does not give N× the items.
- **At ten or more terms the query collapses to ~27 items with one company surviving**,
  which reads as Google refusing the expression rather than ranking it.

So the request count cannot be cut this way, and batching beyond ~5 companies would
silently destroy coverage rather than trade it. The other half of the cost was **the model
call per stored story**, and that has since been paid off rather than deferred: `43f517f`
reuses a verdict for a syndicated headline, and `724c935` asks about twenty headlines in one
call. What remains here is the request volume itself, which no longer has an obvious fix --
see the `robots.txt` entry below for why accepting the position may be the honest option.

**Two documents still carry the superseded plan** and were not corrected with this entry:
`config/config.yaml:144-146` repeats the "about 1,200 requests" figure and calls pooling
"the fix".

### `robots.txt` disallows three of the sources this app reads (a policy decision, not a rate limit)

Fetched 2026-10-16, verbatim:

| host | robots.txt | what we fetch |
|---|---|---|
| `news.google.com` | `User-agent: * / Disallow: /` with an allow-list that does **not** include `/rss/` | the per-company news query |
| `feeds.finance.yahoo.com` | `User-agent: * / Disallow: /` | the per-ticker feed |
| `query1.finance.yahoo.com` | `User-agent: * / Disallow: /` | every price, statement and search, through `yfinance` |
| `www.bankofengland.co.uk` | disallows `/boeapps/database/_iadb-FromShowColumns.asp` | exactly that path, for the gilt curve |
| `stooq.com` | allows only `Googlebot` and `Bingbot`; no longer keyless | nothing: no Stooq provider exists in the tree |

One more finding from the same pass, already true and not a rate limit:

* **`macro_rates` and `gilt` may be better served by a different endpoint** — the Treasury
  publishes the same par curve as an XML feed, which is allowed (`Allow: /`), and the BoE's
  disallowed path is only its CSV export.

**This is a decision, not a bug to fix silently**, which is why it is written here rather
than worked around. Nothing has been done to evade any of it: the client sends one honest,
declared User-Agent and no browser impersonation. The options are to accept the position in
writing, or to move off the endpoint. **The obvious move is closed**, and the entry above
used to point at it: pooling companies into one `q=` was measured on 2026-10-07 and does not
work — Google caps a response at ~100 items, so five companies share that window rather than
adding to it, and at ten or more terms the query collapses to ~27 items with one company
visible. Accepting the position is the honest option until a different source of
per-company coverage exists.

The two bugs before the above — a cache key that ignored the query string, and a
`uk_companies` walk that attempted the same eleven instruments on every run — were found
together in 2026-10-07 and are in the commit log.

### Two direction classes in the stylesheet match no value the column holds

The nine before those — `serve` not migrating, silent DeepSeek truncation, the
`universe_refresh` startup race, CLI/server write-lock contention, the unhelpful blank
dashboard, a stale container being indistinguishable from a code bug, SQLite's write lock
being held across model calls, a rate-limit counter failing the job it was counting, and
the refused embeddings model that meant no two stories were ever grouped — are also in
the commit log.

Two of them were not a bug at all, and are worth remembering. The missing Info
menu item and the `engine_label` template error were both the running container
being older than the image: `docker build` retags an image and does not touch a
running container. The README now says so, and the **Info** page reports the
revision a deployment was actually built from.

The write-lock family is worth remembering for a different reason. It was found
from a container log rather than a test, and it had three separate causes that all
looked correct on inspection: a release at the end of a loop body rather than
before the slow call inside it; the same mistake in a second loop added later; and
a 31-second bulk write in a job that makes no network call at all. The rule is in
`db/session.py`, and it is now enforced at the network boundary as well as by
hand, because remembering it had failed three times.

A ninth was self-inflicted rather than a code bug: an unanchored `.gitignore`
pattern (`research/`) also matched `docs/research/`, so nine research reports were
invisible to git while `git status` reported a clean tree.
`tests/test_repo_hygiene.py` now asserts the invariant that broke.

### Two direction classes in the stylesheet match no value the column holds

Found 2026-10-09 while building the news corpus page, which renders the same cell.

`static/style.css:166-167` defines `.dir-up` and `.dir-down`. Every template that
prints a direction writes `class="dir dir-{{ item.direction }}"`
(`partials/news_ticker.html:34`, `news_item.html:73`, `instrument.html:719`), and
`news_item.direction` holds **neutral, positive or negative** — measured 2026-10-09 on
27,884 rows: 16,079 neutral, 7,263 positive, 4,496 negative, 57 null. So the class
emitted is `dir-positive` / `dir-negative` / `dir-neutral`, none of which the sheet
styles, and `.dir-up` / `.dir-down` are dead rules nothing applies.

The visible effect is small — the direction word renders unstyled rather than coloured —
which is why it has survived. The fix is two renamed selectors, or the three real values
coloured; the reason to be careful is that the `.dir-*` class is shared by the ticker,
the instrument list, the sector list and the story page, so correction changes four
surfaces at once rather than one.

`analysis/relevance.py:111` is the source of truth for the vocabulary
(`DIRECTIONAL = ("positive", "negative")`), so the stylesheet should name those.

---

## Correctness questions still open

### Not one decision in 1,614 has been allowed, and it is a data gap rather than a verdict

Measured 2026-10-08. `decision_run` holds **1,614** rows and `gate_allowed` is **0** on
every one. 1,451 are `avoid`, 158 `hold`, 4 `reduce`, 1 `buy`. The question was whether
the gate is too strict or the universe is genuinely unattractive; the answer is neither.

**What binds.** Two rules, and almost nothing else:

  1,079  confidence_below_floor   "confidence 25% is below the 55% floor"
    516  price_stale              "price data is 37h old (limit for long term is 36h)"
     15  (none)                   `avoid` produces no suggestion anyway
      1  probability_below_floor

**Short term is not the same story, and it is the control.** 7 of the 1,614 pass its gate
-- all seven of the `strong_buy` calls -- against **0** for long term. So this is
specifically the long-term checks rather than a gate that refuses everything, which is
what the entry this replaced had established at 81 decisions and could not explain.
`horizon_fit` agrees: 1,597 `neither`, 16 `short_term`, 1 `long_term`.

**The scores are not being suppressed -- there is nothing to suppress.** Across the whole
universe the composite score runs 0.6 to **63.5**, median 33, and only **6 decisions
clear 60**. A gate refusing good opportunities would leave a pile of them at the door;
there is no pile.

**The cause is that most decisions are made with no accounts at all.**

    482 instruments have a decision;  59 of them have a fundamental period
    WITH fundamentals      n=59   mean confidence 0.52   median 0.50   23 at/above the floor
    WITHOUT fundamentals   n=423  mean confidence 0.42   median 0.40   83 at/above the floor
    376 instruments sit below the floor, and 340 of them have no fundamentals

    500 in-universe instruments, 60 with any fundamental period
    314 in-universe instruments with a resolved SEC CIK, 53 with a period

So `avoid` for 423 instruments says nothing about those businesses -- the model was asked
to judge them without their accounts. That is the coverage failure in the entry below,
and it is *upstream* of the gate: the gate is refusing decisions that rest on nothing,
which is the behaviour it exists for.

**And coverage alone will not fix it.** The 59 instruments that *do* have accounts still
show a median confidence of 0.50 against a 0.55 floor -- 36 of the 59 are below it. The
floor was presumably set against an expectation the model does not meet even when given
the figures, so the threshold and the coverage need looking at together rather than one
after the other.

**Next:** raise fundamental coverage first (see the `xbrl_statements` coverage entry),
then re-measure the confidence distribution *with* accounts before touching the floor.
Raising the floor's headroom without the coverage would only make the two failure modes
harder to tell apart.

`price_stale` is separate and mechanical: 499 decisions refused for data one hour past a
36-hour limit, which is a refresh cadence question rather than a judgement.

### The accounts come from `companyfacts`, not from the filing's own XBRL

Answered for a reader asking whether the tags in the Form 10-K are used. They are not,
and the distinction costs three things.

Every stored period comes from `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`
(`providers/edgar.py:373`) or from a Yahoo statement, never from the document: **394 periods
on 2026-10-09 split 228 `xbrl_companyfacts`, 123 `yahoo_statements`, 33 `yahoo_info`, 10
`llm_extraction`** (the entry read "277 periods, 226, 41 and 10" when written). The
`companyfacts` route **is** the filer's own tagging — the SEC's aggregate of what they
submitted — reached through a different artefact, mapped to canonical names by a
hand-maintained `TAG_MAP` (`ingest/xbrl.py:82`) and filtered to annual forms, with the
**earliest filed** fact winning per period so a later restatement cannot leak hindsight
backwards. `llm_extraction` is a fourth source since the extraction began writing periods.
**Corrected 2026-10-09:** this entry used to end "and it outranks all three", which is no
longer true and was the wrong rule — the filer's own tagged accounts now outrank our reading
of the document (`analysis/collate.py::SOURCE_RANK`), which is what the accounts page is
built on.

What is unused:

- **The presentation linkbase** (`_pre.xml`) — which statement and section a tag belongs
  to, instead of the order `TAG_MAP` asserts. 647 KB for `DAC_US_EQ`'s 20-F against the
  calculation linkbase's 68 KB, so it is the expensive one; the label linkbase (`_lab.xml`,
  928 KB) is what would print the filer's own line names.
- **The document's own inline XBRL** — nothing in the *Python* parses `ix:nonFraction`, even
  though `shareholder_reports` downloads the 10-K bytes. The document *is* read, by the
  model: `extract_filing` (`llm/extractors.py:267`) is called from
  `ingest/parsing.py::extract_held_filings`, which stores what it reads as an
  `llm_extraction` period. So the figures come from a machine-readable aggregate or from
  a model's reading of the prose and tables, and never from the tags embedded in the
  document the model was given.
  **Corrected 2026-10-09:** the *browser* now reads them —
  `web/static/filing-picker.js` is served by `/filing/{id}/pick` and reads the `name`,
  `scale`, `sign`, `format`, `unitRef` and `contextRef` of a figure the reader clicks, plus
  the row's caption and the context's date. That is not a parse of the document: it extracts
  nothing on its own, no fact is stored from it without a person pressing a button, and
  Python still has no reader for the tags. What it changes is that a figure can now be put
  on a line *from the tags in the document the model was given* rather than only from the
  aggregate — one figure at a time, by a reader who is looking at it.

**The half of the calculation linkbase that is still owed.** The linkbase is now fetched
(`ingest/linkbase.py`), parsed, stored and reconciled against a stored period
(`analysis/linkbase.py`), and the accounting-health tab prints the filer's declared
subtotals beside our own component check. What has not changed is `ledger.composition`
itself: it still sums `CURRENT_ASSET_KEYS` and its siblings — a hand-written list in this
codebase — so the page shows two verdicts where the filer's declaration should be the one
that binds, and the "out by" on a statement line is still partly our vocabulary rather
than entirely the children we failed to read. That is the next stage, and the entry below
records why it cannot be done by widening the key list.

**Why it matters:** the accounting-equation failures recorded under Operations (DFPH out
by 95% of assets, AMBQ by 362%) are now *classified* rather than explained away --
`analysis/linkbase.py` separates "the filer declares lines we do not hold" from "we hold
every declared line and it still does not sum", and only the second is a contradiction
between the filing's arithmetic and the figures we read. DFPH turns out to be the first
kind. Which filers are the second kind is not yet measured, and cannot be until the
composition check itself reads the declaration.

### A forgotten line can leave a stored figure that nothing prints

Added 2026-10-10, found in the live database while fixing the tag lookup that follows from it.
`filer-lines/forget` says the value "stays on the period it was written to, where it can be taken
off in the usual way" -- and there is no usual way once the line is gone, because the ledger
prints the lines it is *offered*: `_corrected_accounts` builds `extra` from the filer's learned
lines, so a figure left under a key the filer no longer has is in `metrics`, in `metric_sources`,
counted by nothing and shown on no row. Measured on `DAC_US_EQ` period 256 that day:
`dac:VoyageExpenses` held 63,061,000 in `metrics` with a `span` in its provenance, the filer's
learned lines were empty, and the profit and loss printed no such row.

The reader is not stuck -- the confirmation form offers the caption again since the same day's
fix, and re-creating the line prints the figure that is already stored -- but the state exists
and only the panel's own Undo leads out of it. Worth deciding: refuse to forget a line whose
figure is still stored, or keep printing a learned line that still holds a figure (which is what
`_learned_lines` already does for a learned line the *chart* has since taken over: "where the
chart's line holds nothing, the learned line keeps its place, because nothing else is holding
that figure").

### The attention filter still cannot see a filer whose declared lines hold and do not sum

The linkbase work is now wired: ingest/linkbase.py fetches and parses the calculation,
presentation and label linkbases, analysis/linkbase.py reconciles a stored period
against the filer's declaration, and the accounts page shows the declared subtotals with
the lines we do not hold named, valued and labelled in the filer's own words. A caption the
declaration *proves* belongs on a line (the absent leaves account for the whole residual)
is adopted into that line **for that filer only** and the period re-derived -- measured on
DAC_US_EQ FY2025-12-31, all four composition checks went from out by 484,596,000 /
39,243,000 / 2,093,000 / 36,625,000 to **agrees, out by 0**, with the provenance naming
every tag summed in.

What is still owed is the reader: analysis/attention.py raises a level for exactly one
accounting reason, ledger.equation_check (line 237). 
econciliation.contradictions --
a subtotal where **every** declared line is held and it still does not sum -- is the
genuine discrepancy the ledger's own composition checks cannot express, and it belongs
beside the equation at level 1. The measurement that makes it worth doing is in that
module's docstring: 36 of the 43 instruments holding accounts fail assets_composition,
and most of those failures are our missing lines rather than the filer's arithmetic --
which is exactly the confusion the declaration separates.
### Four of GWW's annual reports would be stored as index pages, not reports

Measured 2026-10-08, once the older-submissions fix made deep history reachable:
`get_annual_filings("0000277135", since=1990-01-01)` now returns **28 10-Ks back to
1994-03-28** (it stopped at the recent window's ten before), and **4 of them have no
`primaryDocument`** -- 1999-03-26, 1996-03-25, 1995-03-27, 1994-03-28. EDGAR leaves that
field empty for the pre-HTML-era filings, so `EdgarProvider.document_url` falls back to
`<accession>-index.htm`, which is the filing *index*, and `Document.is_document` accepts it:
`text/html`, non-empty, not a refusal page. A backfill past about 2001 would therefore store
four index pages as shareholders' reports, and the accounts pipeline would read a table of
links out of them.

**Not reachable today**: `deepen_annual_history` asks for two years, which the recent window
already covers, which is also why the older pages are not requested for it at all. This is a
constraint on raising `years`, not a live fault. Paying it means reading the accession
directory listing (`/Archives/edgar/data/<cik>/<accession-without-dashes>/`) for the
accessions with no primary document and choosing the file that is the report, or refusing
the row and recording why -- the fallback URL is the one thing that must not be stored.

### A manual Run now executes outside the scheduler's one-worker limit

`SchedulerService.run_now` calls `execute_job(spec)` **directly** rather than
going through APScheduler, so it bypasses `max_instances=1` entirely. A manual run
of a job that is already running therefore executes concurrently with it.

**It also bypasses `MAX_CONCURRENT_JOBS`, which is the wider half.** That limit is
a property of the scheduler's executor (`scheduler/service.py:74`, one worker),
and the manual path never reaches the executor -- so a manual run overlaps a
*different* job as readily as its own, and the "one job at a time" reading the
Operations page invites is not true of it. Measured 2026-10-06: run 318
(`news_rss`, manual, started 22:48:31Z) ran concurrently with run 317
(`shareholder_reports`, scheduled catch-up, 22:48:27Z -> 22:49:12Z) and died at
22:52:14Z with `OperationalError: database is locked` on an `INSERT INTO news_item`
-- the second write to SQLite is what fails, and no amount of single-worker
scheduling prevents it while this path exists. One consequence was already fixed
rather than queued: the two runs' progress-capture handlers cross-wrote each
other's lines, so 317's log carried 34 duplicated lines and 318's `: start` line
appeared twice (`scheduler/progress.py`).

The evidence is in the live `ingest_run` history: two `news_rss` runs overlapped
and the second died with `UNIQUE constraint failed: news_item.url_hash`. That
specific failure is now benign — the insert is wrapped in a savepoint and a stored
story counts as a duplicate (`tests/test_write_lock.py`) — but the general
condition is not fixed, and it is not only about news. Any two runs of one job can
interleave, and jobs that are not idempotent would corrupt rather than duplicate.

**Decide:** should `run_now` refuse with a clear "already running" rather than
returning zeros, or should it queue behind the scheduled run? Whatever is chosen,
the refusal has to be visible to the CLI and the Run now button, both of which
currently treat a `None` result as "nothing to do". Submitting to the executor
instead of calling `execute_job` would answer both halves at once, at the cost of
`wait=True` no longer meaning "wait" — the button currently reports the run's
result, so it would have to poll the run table instead.

**Measured again 2026-10-08, and this time it wedged the deploy path.** Run 886
(`decision`, a *scheduled catch-up* the container restart had just fired, 13:29:38Z)
overlapped run 887 (`held_refresh`, manual, 13:30:09Z -> 13:33:06Z, the new hourly
sweep) and died at 13:30:15Z with `database is locked` — first on the `llm_call`
insert, then on `decision_run`. Two consequences the earlier measurement did not
show:

* **A paid model call that is recorded nowhere.** The DeepSeek call completed; the
  `llm_call` row is the write that failed, and `deepseek._write_call` logs the error
  and carries on. The spend exists at the provider and not in the ledger the
  Operations page adds up.
* **The close-out hit the same lock, so run 886 stayed open** with `ok=NULL` — the
  Operations page showed `decision` *running* with no thread behind it, and
  `awltux quiet` waited on it indefinitely rather than reporting idle. That is the
  part that matters beyond one lost decision: a lock collision can block the next
  deploy, because the deploy path waits for quiet. A restart clears it through
  `close_orphaned_runs`, but that writes "the process restarted", which is not what
  happened; the row was closed by hand with the real reason.

**And the on-demand repair makes the bypass its only path.** Added 2026-10-16 with
`filing_summaries` (`scheduler/registry.py`), a job with no interval at all: every run
of it is a `run_now` from the Operations button, which posts `wait=True`
(`web/routes/api.py:395`) and therefore never reaches the executor. So this is no
longer a state a manual press can accidentally enter -- it is the design, and what it
overlaps is whatever scheduled job holds the single worker at that moment. Its writes
are one `llm_call` row plus one `filing.parsed` update per filing, and the `llm_call`
insert is the write that failed in run 886. Either this entry is dealt with before the
backlog is worked through, or the repair is run with the scheduler quiet and nothing
else in flight.

### Build the accounting-quality markers from `docs/investment-markers.md`

**Mostly done.** Re-measured 2026-10-06: this entry still listed Piotroski, the
Beneish indices, the receivables and inventory drift and goodwill intensity as "still
to build", and all of them had been built. `analyse()` returns nine markers.

In place: `awltux/metrics.py` is the single vocabulary; `analysis/accounting.py`
computes the accrual ratio, multi-year cash conversion, Piotroski's nine named checks,
gross profitability, receivables drift, inventory drift, goodwill intensity, the
Beneish indices (no composite -- its five-variable coefficients are not in this
project's evidence base) and the Altman Z'' inputs. `ingest/fundamentals.py` bridges
`ebit`, which no provider states: 0 of 88 stored periods had it, and 74 do once the
bridge is applied.

Still to build, in the order the note argues for:

1. **Filing events, on a schedule.** `extract_filing` *is* called now: the
   one-instrument refresh reads the held documents and stores the cited metrics and the
   filing events (`ingest/parsing.py`), and `decision/service.py` already prompts with
   `filing.parsed["extraction"]["filing_events"]`. What is still missing is anything that
   does it **unattended** — 601 documents are held and the only route to reading one is a
   button press on a single instrument. A job would need a per-run ration (this is a
   model read over a document that can be hundreds of thousands of characters) and a
   coverage probe, since `Filing.status == "fetched"` is exactly "downloaded and unread".
2. **ROIC against an explicitly stated WACC** — the economic question the system
   cannot currently answer. `valuation.py::wacc` exists; the denominator definition
   is the part that has to be stated rather than assumed.
3. **A serial-acquirer flag** — `goodwill_intensity_marker` measures the share;
   nothing yet reads it *across* years for repeated acquisition.
4. **Loughran-McDonald `litigious` and `uncertainty` counts** on filing text.

One follow-up created by the EBIT bridge: it applies when a period is written, so the
88 existing rows gain EBIT only as `fundamentals` and `xbrl_statements` rotate over
them. `_upsert_period` replaces `metrics` on re-fetch, so it is self-healing rather
than permanently stale -- but at the current rotation that is days. A one-off
re-derivation pass would close it immediately and would be needed again by the next
derived metric; it is not urgent enough to interrupt the markers.

Two cautions the note raises that belong with the implementation:

- **Do not port US-calibrated scores to UK accounts unmodified.** Beneish and
  Altman were fitted to US GAAP data; FRS 102 and IFRS differ on leases,
  development-cost capitalisation and goodwill. Recalibration or a stated caveat is
  required, not optional. The Altman marker carries the caveat in `ALTMAN_DEMOTION_CAVEAT`.
- **Every score must show its inputs.** The failure mode of these tools is a number
  that reads as a verdict; the note's recommendation is that a flag means "read
  this" and never "this is fraud".

### `symbol_resolution`'s ISIN answer is discarded by the next instrument sync

Measured against the live database, and it contradicts what this item used to claim.

**18** instruments in the universe have an ISIN and no price bar. They are the
residue of the 92 whose Yahoo symbol was *derived* from a Trading 212 ticker, and
T212's tickers are frequently former ones. `symbol_resolution` looks those up by
**ISIN** — which survives a rename — and reports them resolved. It writes the answer
to `instrument_alias`, provider `yahoo`, `is_manual=False`.

**Nothing reads that row.** `ingest/prices.py` builds its work from
`Instrument.yahoo_symbol` (`prices.py:128,143`), never from the alias table. The only
path from an alias into `yahoo_symbol` is `universe.py::_resolve_mapping`, which
copies across aliases where `is_manual IS TRUE` (lines 213–225) — so a non-manual
result is not merely unused, it is skipped by design.

The same function then **overwrites the alias** with the derived symbol (lines
247–259). That is why `DOOO_US_EQ` carries alias `DOOO`, `method='us_bare'` — the
derived guess — where this file previously recorded `DOO` at confidence 0.907 as
"applied, verified live". `t212_instruments` has run 51 times since. The resolution
is destroyed, not just ignored.

So the residue growing from 13 to 18 is one cause, not drift: names go stale, the
job re-resolves them, and the answer is thrown away on the next sync.

**A cut of them are honest, not a bug.** `AFAR_US_EQ` (a SPAC that appears to have
completed) and `BLVNl_EQ` were checked against the live endpoint and return **zero**
candidates by ISIN *and* by name. `BIOK_US_EQ` resolved to `DUMY0001134`, Yahoo's
stand-in for a company with no live listing, and was refused. Most of the rest are
suspended or delisted UK small-caps. No rule can find a listing that does not exist.

**Next:** decide which side owns the symbol. Either the price job reads
`instrument_alias` where `provider='yahoo'` — making the derivation one producer
among several — or resolution sets `is_manual=True`, which is a smaller change but
marks a machine's guess as a human's decision, and that distinction is the reason the
flag exists. Then the 18 need either a retry backoff, so a question whose answer
cannot change stops being asked daily, or a review queue: there are **no** manual
aliases at all (`is_manual` count is 0), and the only place one surfaces is the
instrument page, one ticker at a time. A reviewer has no list to work from.

### The identity keys are stored, but 19,474 existing rows do not carry the third one

The same-event grouping used to be one cosine threshold and nothing else. Measured
2026-10-07 through the deployed container against the 1,000 embedded stories, of the
**672 joins** it made at 0.70, **439 (65%) contradicted their own group on the stored
`event_type` or `direction`** -- 374 on event type, 173 on direction:

    "Claritev (CTEV) Stock Jumps On Margin Strength Despite Ongoi..."    joined with
      "...Douglas Michael Garis Sells 9,025 Shares of Claritev"
      "...Claritev (CTEV) Is Down 42.1% After Launching $75 Million Bu..."
      "Claritev drops on report DOJ expanding antitrust probe (CTEV..."
    "Canadian National Railway stock falls Wednesday, underperforms"    joined with
      "Canadian National Railway stock rises Wednesday, outperforms"      (0.8578)

Every one of those pairs scores high *because* it is one company on one day in one
register, which is the one thing a cosine cannot see past.

`analysis/embeddings.Identity` and migration `0011` now require that a story not
contradict its group's lead on event type, direction or metric before the similarity is
consulted, and `same_event_threshold` went back to **0.70**: it is a tie-break among
stories that already agree on what kind of thing happened, not the decision.
`event_type` and `direction` are populated on every embedded row, so that half is live
and vetoes 439 of those 672 joins today.

**What is missing is the third key.** `metric`, `period` and `magnitude` are new columns
and most rows are still NULL. Re-measured 2026-10-08 against **26,301** stored stories --
the entry said 5,800 when first written and 20,168 when last corrected, so this needed
re-measuring again:

    metric     6,827 set (26%)    19,474 null
    period     1,180 set (4%)     25,121 null
    magnitude  1,526 set (6%)     24,775 null

**The metric half is no longer inert.** It was 3% when this was written; every story
classified since carries a metric, so 26% do now and the veto is doing real work on new
rows while the 19,474 older ones stay "not stated". `news_relevance` backfills at **200
model calls per run** (`news.relevance_backfill_per_run`), which against 19,474 rows is
still roughly 97 runs. `event_type` and `direction` are separate and much further along:
22,894 (87%) and 26,244 (100%).

`metric` is the one that matters and the reason the columns exist at all. On the five
pairs that decided the threshold, the *true* EasyJet takeover pair scores **0.7925** and
the *false* Golar pair **0.7599**, so similarity orders them wrongly, and the two differ
in exactly this field (`share_price` against `price_target`). Same shape for Expedia (a
raised target against "up 60% this year") and Dunelm (FY26 sales growth against a pre-open
slip).

`period` and `magnitude` are stored and shown beside the headline but **deliberately not
compared**. The period that separates "falls Wednesday" from "rises Friday" is free text
exactly as the story writes it, and comparing "2026-10-05" against an absent value vetoes
a real join -- the failure this whole rule exists to prevent. Normalising it into
something comparable is its own job.

**The question this leaves open.** With the veto running, is 0.70 still the right
tie-break? The measurement that made 0.70 look wrong was taken *without* it. Re-measure
once the metric backfill has run: if the surviving joins are genuine, the threshold can
be loosened to catch the duplicates it is currently missing.

The probes are scratch under `.tmp/probe_keys.py` and `.tmp/probe_keyed.py`, and will not
survive; the numbers are restated here and in the `same_event_threshold` comment.

### The news-to-fundamentals weighting is an assumption, not a finding

News currently enters sentiment with a 0.55 component weight. The research note
finds no support for *increasing* it, and a specific methodological hazard: coverage
follows price at least as much as price follows coverage, so much apparent news
signal is momentum or attention in disguise. Worth testing this system's own
sentiment scores against forward returns **with the trailing price move controlled
for**, which the calibration page is already positioned to do — and worth saying so
on the calibration page if the control is not possible.

### The news appraisal only ever sees the headline and the snippet

RSS gives a title and a short summary; Finnhub and Marketaux give little more. So
the claim extraction, the omissions list and the technique detection all work from
a few sentences, and the appraisal says so. Fetching the article body would make
the analysis substantially better, and is deliberately not done: publisher terms,
paywalls and robots rules are a legal surface this project is not going to take on
unilaterally.

**Consider instead:** following the *free* primary documents we already hold — EDGAR
filings, Companies House accounts — and matching them to a claim, which would let
"the filing says otherwise" be a checkable outcome rather than a suggestion.

### The appraisal guard asks a narrower question than the job it guards

`news_analysis` is skipped when `_probe_news_analysis` reports nothing outstanding, and
the probe counts only **unappraised `material`/`critical` stories inside the window**. The
job selects on `is_interesting`, which is four branches — materiality, rhetoric markers
above the attention threshold, a *held* name with non-`none` materiality, or single-source
coverage from a needs-checking publisher kind — and it also re-appraises anything whose
appraisal is older than `refresh_after_days` (7). None of the three non-materiality
branches is in the probe.

**Measured 2026-10-08, and today the two agree** — so this is latent, not live. Run 815
appraised the window hours earlier, and re-deriving the job's own selection over the same
14 days from the live database gives:

    7,025 stories in the window, 295 of them material/critical
    probe: 0 pending
    is_interesting selection: 5,070, of which never appraised 0, appraisal stale 0
    931 stories in the window are unappraised and *declined* (646 none, 236 mild, 49 moderate)

The permanent case is the one that matters: a story interesting **only** by rhetoric or
single-source coverage pushes the probe's count to 0, so the job is skipped — and because
the probe is narrow rather than wrong, nothing ever goes back for it. It ages out of the
window unappraised. 295 material stories in 14 days currently keep the gate open often
enough to sweep those branches up incidentally, which is why this has never bitten.

**The fix has a trap in it.** Widening the probe to count *every* unappraised in-window
story makes the guard true and useless: the 931 declined stories never acquire appraisals,
so the job would run every hour for ever, re-examining 7,000 stories to write nothing.
Counting staleness is the same trap (most of the window is stale by construction, and
`max_deep_per_run` is 40, so that is 40 model calls an hour). Either **record the decline**
so the probe can subtract it — an `is_interesting` verdict stored on the row — or accept
the narrow probe and say so in the probe's reason text. Do not simply widen the count.

### A story missed while it is inside the appraisal window is never appraised

`analyse_universe` loads `published_at >= now - lookback_days` (14). The window slides
forward and nothing ever looks behind it, so a story the sweep did not reach while it was
inside — the guard skipped that hour, the container was down, the RSS allowance was spent —
stays unappraised permanently, at the "unassessed default" weight, for ever.

**Measured 2026-10-08, against the live database:**

    news_item rows                                  27,526
    distinct stories with any appraisal              6,457
    unappraised material/critical, all time          1,685
      of those, 14-30 days old                         102   (90 material, 12 critical)
      of those, 30-90 days old                         708
      of those, over 90 days old                       875
    unappraised in-window (0-14 days)                  931   -- all declined by is_interesting

The 875 over 90 days mostly predate the appraisal feature, so the recoverable population is
roughly the **810 in the 14-90 day band** — stories that were material, were inside a window
this job was running against at the time, and were not reached. `_probe_news_analysis`
already documents the boundary as deliberate ("older material stories are not this job's
outstanding work; they are history"), which is a defensible line for the *queue* but not for
the *record*: an unappraised material story is still weighted at the unassessed default
wherever news sentiment is aggregated.

Decide one of: widen `lookback_days` (14 → 30 recovers the 102 that are 14-30 days old),
add a one-off backfill that appraises material stories older than the window, or state in
the appraisal section of the news page that a story older than 14 days the sweep missed will
never be appraised. The window is a spend decision — the deterministic pass is ~24s for 7,000
stories and the model calls are rationed at 40 — so it is not a change to make silently.

### Cross-domain corroboration does not use GDELT yet

`analysis/corroboration.py` counts origins by clustering what is already in our
database, so it can only see coverage we happened to ingest for that ticker. GDELT
is already integrated and keyless, and its DOC API can be searched for an exact
headline to find syndicated copies we never fetched. That would make the carrier
count evidence rather than inference.

### `unconfirmed` material claims do not reach the decision gate

The appraisal flags a material story carried by a single source, and the flag is
stored and shown. Nothing in `decision/gate.py` reads it yet, so an unconfirmed
story can still contribute to a `news_materiality` answer. Decide whether an
unconfirmed material claim should block a short-term suggestion, or merely be
shown — and if it blocks, make the refusal reason name the flag.

### News ingested before this change has no event type

`news_item.event_type` was always computed by the classifier and thrown away, so rows
written before migration `0004` are `NULL`, and primary-source routing falls back to
nothing for them.

**Re-measured 2026-10-08: 22,894 of 26,301 stories (87%) carry one**, so this is much
smaller than it was and much smaller than it reads. The **3,405** without are **not** the
sector stories this entry used to blame: **there is no `news_sectors` source in the live
database at all**, and sector feeds are classified like any other (`llm/classify.py:532`).
Re-counted by source the nulls are **google_news 3,196, yahoo_rss 198, marketaux 12,
finnhub 1** — the classifier simply never returned an event type for them, or they predate
the field. Worth correcting the framing rather than the code.

### Which stories are one event depends on which one anchors it

Measured 2026-10-08 on the four reports of Great Southern Copper's £2m raise (news ids
27291, 27293, 27294, 27295). All four agree on `event_type=capital_raise`,
`direction=positive`, `metric=none`, so the identity veto refuses nothing; the cosines are
0.9623, 0.7993 and 0.6329. `analysis/embeddings.py::cluster` compares each story against its
cluster's **anchor** -- the first one handed over -- and nothing else, so:

- best-first (the banner's priority order, and id-ascending) → **one event of four**;
- newest-first → **three**, because 27295 anchors and 27294 is 0.6329 from it, under the 0.7
  threshold, while it is 0.7993 from the best-ranked report of the same event.

That is what the ticker's "4 stories cover this event" over a news page listing two was
(27291). The page now groups the banner's population in the banner's order, so those two
agree -- but the rule is still order-sensitive, and a third caller with its own population can
split the same set again. `group_events` on the instrument page does exactly that today (it
claims only "N similar reports", which is the weaker and safer sentence).

Neither fix is free: single-linkage -- compare against every member rather than the anchor --
makes membership a property of the *set* (the connected components of a ≥threshold graph are
unique, so no order can change it), at O(n·members) comparisons and with chaining, which the
anchor rule exists to prevent; or keep the anchor and require every caller to hand over a
canonical order. The chaining rate under the identity veto is the measurement that decides
it, and it has not been taken.

### A story from a loose feed is still attributed to the instrument that fed it

The *accumulation* half of this no longer happens: a symbol-addressed feed cannot add a
ticker to a story another feed already stored (`SYMBOL_POOLED_SOURCES`, migration `0016`),
which took the 21 `yahoo_rss` rows carrying more than three tickers down to one each.

What is left is the first attribution. A Yahoo `?s=` feed returns a shared pool, so the
*fetching* instrument is not the subject either -- and it is the one ticker that survives:

    id=6572  feed=s=PET.L  tickers=[PETl_EQ]
      "Fidelity Asian Values Plc - Transaction in Own Shares"

That story is on Petrofac's page, and it is about neither Petrofac nor PET's feed. The
same is true of the 48 other `yahoo_rss` rows that were over-attributed, and of any
single-ticker row a pooled feed stored.

**Why it is not simply deleted.** The row is `relevant=False`, so relevance-filtered
views already exclude it -- but `db.news_for_ticker` does not filter on relevance, so
`/instrument/PETl_EQ` lists it under its news. That is the visible wrongness, and it is a
question about what an instrument's news list should require: the feed's say-so, or the
classifier's `is_about_this_company`.

The classifier already answers that per item and `apply_classification` already stores
it; nothing consults it when deciding what an instrument's news list contains. Worth
deciding deliberately, because filtering the list on relevance would also hide the rows
that are merely *unassessed*.


### Sentiment aggregation loads the whole news window per run

`aggregate_all` loads every item in a 30-day window once, then filters by ticker in
Python because the tickers column is JSON. That is correct and portable, and it is
also the slowest part of the job. Worth revisiting only if the window grows.

### Portfolio limits are reported NOT VERIFIED rather than failing closed

The gate reports the portfolio-limits check as **NOT VERIFIED** (non-blocking)
when holdings are unknown, instead of refusing the suggestion. That is the honest
answer to "we could not check this", but it also means a position-size breach can
be shown as actionable.

**Decide:** should an unknown portfolio block a *buy* suggestion, or stay
advisory? Whatever is chosen, the gate reason string must keep saying which it is.

### Fallback decisions are all uncalibrated

No TypeSafe/JEV key is configured, so every decision comes from DeepSeek and then
the deterministic rule engine, and every one is labelled `(uncalibrated)`.
Confidence from those engines is not a measured hit rate, and the calibration
page cannot say anything about them until outcomes accumulate.

**Done when:** a JEV key is in `.env` and decisions record a calibrated engine —
or the limitation is stated on the dashboard rather than only in the model
column.

### Three UK listings now sit at attention level 1 for ever

Measured 2026-10-16, the first run after `uk_companies` began recording blockers:
`JELl_EQ` (Jersey Electricity — registered in Jersey, so absent from the UK register by
construction), `SMIFl_EQ` (TwentyFour Select Monthly Income Fund) and `TBLDl_EQ`
(Tinybuild) record `no Companies House record matched "…" (20 candidate(s) searched)`,
and `analysis/attention.py::_blocked` turns any open blocker into a **level-1** "A job
cannot proceed" reason. Nothing will ever clear them, and `_probe_uk_companies` keeps
reporting a coverage gap, so the hourly backfill keeps attempting all three and bumping
`occurrences` — a run that costs 3 Companies House searches an hour to relearn a fact
that cannot change.

Two questions, and they are separate:

1. **Is "no record exists" a blocker at all, or a stated gap?** A blocker is re-checked
   and cleared on success; this one can only be cleared by a human writing the number
   by hand. The alternative is a terminal state that says so.
2. **Should the level depend on the reason?** Level 1 is right for a provider refusing,
   which may well work next run. It is misleading for "this company is not on the
   register", which the reader can neither fix nor wait out.

The evidence for the first is the `occurrences` count after a day of hourly runs; for
the second, the three rows above are the only level-1 blockers in the live table that no
run can clear.

---
### Every currency but USD and GBP is valued at the wrong risk-free rate

`analysis/macro.py:58` `CURRENCY_CURVES` maps only `USD -> treasury` and `GBP -> gilt`, and
`curve_for_currency` (`macro.py:127`) is `CURRENCY_CURVES.get(...)` -- so any other currency
returns `None` and `resolve_risk_free_rate` falls back to the single configured constant.
That constant is USD-shaped, and the function's own default argument is `currency="USD"`.

Measured 2026-10-08 on the live universe: **384 USD, 114 GBX, 1 GBP, 1 EUR**. GBX aliases to
GBP (`CURRENCY_ALIASES`, `macro.py:66`), so the exposure today is one EUR instrument valued
off a dollar-shaped number -- small, but silent, and the map is the documented place for the
coupling to be visible ("adding a currency means adding a provider that can read its curve").

Found in `docs/research/FINDINGS.md` section 3 and filed here because it was queued nowhere:
`grep -n 'CURRENCY_CURVES\|risk-free' TODO.md` returned nothing. Not urgent on one
instrument; it becomes wrong-by-default the moment a non-USD listing is added, which is a
data change nobody would connect to this map.

### The characters-per-token ratio is written twice, and now it decides two things

`analysis/state.py:38` owns `CHARS_PER_TOKEN = 3.4` and `estimate_tokens`, and
`llm/deepseek.py:301` writes the same number inline as `int(prompt_chars / 3.4)` for the
pre-flight budget check. Both read 3.4 today, so nothing is wrong yet.

What changed on 2026-10-09 is that the ratio acquired a second consumer that acts on it:
`research/evidence.py::_fit_to_context` trims the deep-dive's evidence to
`context_tokens - max_output_tokens - reserve_tokens` using `estimate_tokens`, while the
request's size check uses the inline copy. A change to one and not the other would make the
trimmer fit a prompt the client then refuses, or the reverse — and the failure lands after a
refresh has been paid for, which is the whole reason the trimmer exists.

**The fix is a move, not an edit:** the constant belongs to the `llm` layer (it is a fact about
the provider's tokeniser), so `analysis/state.py` should import it from there rather than
`llm` importing it from `analysis` — importing upward into `analysis` from `llm` would invert
the layering the whole tree keeps. Its own commit, because it touches the decision state's
sizing on a deployed path.


### The levers a deep-dive records have never been read against a real answer

Added 2026-10-10 with the block itself. `llm/prompts.py::_RESEARCH_LEVER_RULES` asks the
deep-dive for `levers`, `research/report.py::_levers` resolves what comes back through
`analysis.levers.resolve` and drops a name that does not resolve, and
`research/service.py::_record_levers` writes the survivors while leaving every lever a person
recorded alone. All of it is tested offline against a fixture, and **no live deep-dive has run
with the block in the prompt**, so three things are assumed rather than measured:

- that the model uses the vocabulary's keys rather than inventing names. If it does not, the
  field is a token cost that records nothing, and the fix is the prompt's wording rather than
  the reader -- the reader is right to refuse a lever it cannot resolve.
- that its `reason` is about the company rather than the label restated. Nothing gates it: a
  reason is prose the report attributes to itself, the same standing as `management.assessment`
  and `suitability.reason`, and the span rule `strengths` and `concerns` carry would need a
  quoted span the schema does not ask the model for.
- that `secondary` is used at all, rather than every lever arriving `primary`.

What to read from the first live answer: `result["levers"]` and the `discarded` list, both in
the stored report (`ResearchReport.result`) and in the document's provenance footer. The run
does not have to be repeated to check it.


## Operations

### The balance banner cannot show one key's spend, because nothing records which key paid

Asked for 2026-10-09: *"I think the DeepSeek costs are for all keys? It would be preferable
if it showed just for this key. I suspect you will need a key name to support that."* The
name is now in place -- `AWLTUX_DEEPSEEK_KEY_NAME`, shown on the strip beside the figure --
and it is a **label, not a filter**. What is owed is the scoping, and it has two halves that
need different answers.

**The balance cannot be scoped by anyone.** `GET /user/balance`
(`providers/balances.py:220`) answers with `is_available` and a `balance_infos` list per
currency: the whole account, every key on it. Checked 2026-10-09, the per-key breakdown
exists only as a **monthly CSV export from the platform console** -- every third-party
DeepSeek usage dashboard is built by dragging that CSV into a page, e.g.
[deepseek-api-usage-analysis](https://github.com/GavinCnod/deepseek-api-usage-analysis) and
[deepseek-usage](https://github.com/shajanjp/deepseek-usage) -- which no job can read. So
this half is a limitation to state, not a bug to fix, and the strip says it in its tooltip.

**The spend *can* be scoped, and is not.** The `17.07 USD spent / 30d` figure is our own
`llm_call` ledger (`web/queries.py::_credit_spend`) grouped by `provider`, which is the whole
installation rather than one key. That only separates two keys if two keys have ever been
used from this database -- it cannot, today, because **`llm_call` has no column naming the
key**. Measured 2026-10-09: the table's columns are `provider`, `purpose`, `model_id`,
`ok`, `error`, `cost_usd`, `created_at` and the token counts; no credential is recorded.
Adding `key_name` (an additive migration) and writing the configured label at
`llm/deepseek.py::_write_call` would make the 30-day figure attributable, and it starts
empty -- every existing row would read "unknown key", which is the honest answer and worth
showing rather than backfilling a guess.

Do the second half only if more than one DeepSeek key is ever really in play; with one key
the label already answers the question, and a column that is the same value on every row is
a column that has stopped carrying information.

### fal embedding spend is recorded nowhere, so only the balance constrains it

`llm_call` is written by exactly one module -- `llm/deepseek.py:438` -- so it holds
DeepSeek chat spend and nothing else. `EmbeddingClient` goes out through `HttpClient` and
records no cost, and `store_vectors` stores vectors and a `text_hash` with no money
against them. Measured 2026-10-07: `select provider, count(*), sum(cost_usd) from llm_call
group by 1` returns `deepseek` only.

What that means for the credit banner, which reads spend from that table: DeepSeek gets a
"spent / 30d" figure and fal does not. So the only thing bounding fal is the balance
itself — which is now readable (`FAL_ADMIN_KEY` + `GET /account/billing?expand=credits`),
and stood at **$1.10** when this was written. A balance with no burn rate beside it cannot
say *how long* is left, which is the question a near-empty account actually raises.

**A rough burn rate now exists, and it is still not this.** Suggested 2026-10-09: *"the fal
costs could be roughly calculated by storing the balance each time it's updated and
comparing it to the next balance update."* Built: `provider_balance_reading` keeps every
readable reading (36/hour x 24 = ~48 rows a day, pruned at `retention.balance_days`), and
`providers/balances.py::burn` sums the falls between consecutive readings. The strip shows
it for fal as `~X USD spent / 30d` with the caveat in the tooltip.

It is a **floor, not a measurement**, for a structural reason worth remembering: an interval
in which the balance *rose* hides whatever was spent in it. Measured shape on a two-point
example: 10.00 -> 50.00 with 50.00 added means 10.00 was spent and is invisible. So the
figure under-reports, always, and by an unknown amount.

The add this entry is about is therefore still owed and is the *better* answer: record an
`llm_call` row per embeddings *request* (not per story) with `provider="fal"`,
`purpose="embeddings"`, the token count fal returns in its usage block, and `cost_usd` from
the model's published per-million rate. It needs the rates in `config.yaml` beside
`news.embeddings`, because they are per model and the parser already knows which model
answered. That would give an exact figure, per request, that no top-up can hide — and the
balance difference would remain useful as a cross-check against it.

### One worker means a 39-minute job delays every other job

Re-measured 2026-10-16, after the two changes the previous version of this entry asked
for. The worse half was `decision`, and that half is answered: measured 2026-10-07 it
wrote **52 decisions in 12.8 minutes** — 4.1 a minute against a universe of 500, so a
full sweep is about 110 minutes, longer than the daily interval that asked for it and
killed by every deploy (`decision` had 6 runs and 0 successes). It now decides 20 an
hour, ordered by least recently decided, and every long job has a `progress.barrier`
inside its per-item loop, so `awltux quiet` no longer waits for the whole of one.

What is left is not about stopping.

`news_analysis` is bounded at `news.scepticism.max_deep_per_run` = **40** model calls, and
at one call per story that is **14 to 39 minutes** — the three runs on record took 826s,
1831s and 2351s. `MAX_CONCURRENT_JOBS` is **1**, so while it runs no other job starts: an
hourly job whose trigger falls inside that window does not queue, it waits for the next
interval, which is a two-hour gap in prices, news or sentiment for no reason other than
one job's length. Lowering `max_deep_per_run` is not a fix — 40 stories is already a
rationed batch and cutting it only grows the backlog — and the per-story work is already
persisted, so a *stopped* run loses nothing.

That is the thing to decide: whether the answer is a second worker for jobs that make
model calls rather than CPU (see the entry below for why more CPU cannot help), or a
per-run time budget rather than a call budget. Both are bigger than a fix, so this stays
here with the measurement.

**Correcting what the entry this replaces used to claim:** `quiet` *can* report `idle`
while `decision` or `news_analysis` is running — those two stop on request, as do all six
jobs that had no boundary before 2026-10-16. The claim that it never could is stale.

### A CPU-bound job still starves the web UI, and one worker only halves it

Capping the job pool at one worker (`MAX_CONCURRENT_JOBS`) stopped five jobs running
together and took `/dashboard` from 164 seconds to 14. **It is a mitigation, not a
cure**, and the dose-response is clear enough to say why.

Measured on the live container by loading the same pages at each level:

| jobs running | `/dashboard` | `/jobs` | process CPU |
|---|---|---|---|
| none | 0.95s | 0.20s | 0.16% |
| one (`news_analysis`) | **14.1s** | **31.2s** | 110% |
| five | **164s** | timed out at 180s | 112% |

One job is enough to hold the process at a full core and take the interface from
instant to unusable-for-refresh. The container is not short of CPU — 1.1 of 8 cores
used, no quota set — so this is CPython's GIL: one thread runs Python at a time, and
the web request thread waits its turn behind a job that does not yield it.

That also answers the obvious guess. **Giving the container more CPU cannot fix
this**, because the limit is a single interpreter lock, not the number of cores. The
five-job freeze was the same mechanism with more queueing in front of it.

Two things follow, and they are different sizes of change:

1. **Cheap, and worth doing first:** the heavy jobs are pure-Python loops over a few
   thousand rows (`valuation`, `price_eod`, `universe_refresh`). Yielding the GIL at
   a batch boundary — `time.sleep(0)` every N rows — costs nothing and hands the
   interpreter back often enough for a web request to be served.
2. **The real fix:** run the web server and the scheduler in separate processes.
   They have no reason to share an interpreter, and nothing in the API calls into the
   scheduler's threads. Until that happens, "the dashboard is slow" and "a job is
   running" are the same statement.

**Until then:** check `/api/quiet` before concluding the interface has broken. It
answers in under 0.2s even with a job running, which distinguishes "the app is down"
from "the app is busy" — the distinction missing when this was first reported as a
freeze.

**See also** *`decision` still sweeps the whole universe, and six jobs have no stopping
point*: the same single process is why a job that has no boundary to check cannot be
asked to leave, and one that can be asked still holds the interpreter for the batch it is
inside. That entry is the job-side half of this one, and the two have different fixes.

**Re-measured 2026-10-11**, reported as "the web interface is very slow to respond", with
the pauses blamed on *selecting an instrument and clicking the Accounts tab*. Two things
came out of it, and the second is new.

*The tab is innocent.* `queries.instrument_detail(sections=("fundamentals",))`, which is
all the Accounts tab fetches, is **5–10 ms**, and `analysis.collate` over the same rows is
**0.2–0.7 ms** — measured for the six instruments with the most stored periods (GWW and AIT
13 each, DAC 12, ATMU/MSFT 9), GWW resolving to 4 accounting years. `/instrument/GWW_US_EQ`
is 0.26 s and `?tab=accounts` **0.19 s** warm. The tab was where the reader happened to be
standing when the interpreter was busy.

*The contention reproduces, and the shape is now sampled rather than inferred.* Sampling
`/proc/9/stat` and the page together, 20 windows of 3 s, with a network-bound job
(`news_sectors`) running:

| process CPU | `/dashboard` | `/api/quiet` |
|---|---|---|
| 0.42–0.61 of a core | 0.98–1.55 s | 0.004–0.005 s |
| 1.08 of a core | 1.84 s | 0.005 s |

and with no requests at all the background job holds only **0.06–0.29 of a core**, which is
why an idle-looking container is not evidence that nothing is running. The 4–7 s pauses
were sampled at `docker stats` reading ~100%: the first measurements of the day,
`/dashboard` **5.85 s** and `/jobs` **4.55 s**, were taken in the minute `price_eod` ended
(2026-10-10 21:36:20 → 2026-10-11 09:25:07, **11 h 49 m**) with `held_refresh` and
`news_analysis` starting behind it, and 40 minutes later the same two pages were 0.45 s and
1.3 s. Trivial requests are served throughout — `/api/quiet` never exceeded 22 ms in 20
samples — so this is a request that needs a second of interpreter time queued behind a job
that is holding it, not an event loop that has stopped.

*And the baseline is worth its own entry.* Even idle, `/dashboard` is ~1.2 s, and
`queries.recommendations()` is **841 ms** of it, apportioned by timing each phase:

| phase | cost |
|---|---|
| `_recent_bars()` | **425 ms** |
| latest decision rows (500 full rows, JSON columns and all) | 217 ms |
| `attention.assess` (four queries) | 95 ms |
| latest valuation rows | 38 ms |
| `_instruments_in_scope` | 9 ms |

`_recent_bars()` ranks **every one of the 236,819 `price_bar` rows** with `row_number()
over (partition by ticker order by date desc)` to keep `rn <= 2`, and the plan confirms
`SCAN price_bar ... USE TEMP B-TREE FOR LAST TERM OF ORDER BY`. Narrowing it by ticker
cannot help — the table holds 488 tickers and every row is one we want — so the *shape* has
to change: the last two bars per ticker is a per-ticker index seek, not a rank of the
whole table. The same is true of the 217 ms: the page needs about twenty columns from
`decision_run` and materialises five hundred whole objects to read them.

**Locks are not the mechanism, and the dates say so.** Asked directly ("could that cause
it, DB locks?") after the same report. The database is in **WAL** — `PRAGMA
journal_mode=wal`, read from the live file — which is the mode `db/session.py` chose for
exactly this reason ("so the scheduler's writes do not block dashboard reads"): a reader
takes the last committed snapshot and a writer never blocks it. A lock therefore surfaces
as a **job failing**, not as a slow page, and there are exactly **8** such failures on
record: `news_rss` 2026-10-05 15:20, `decision` 10-05 15:30, `news_rss` 10-06 22:48,
`news_relevance` 10-07 20:40, `decision` 10-08 13:29, `instrument_refresh` 10-08 16:39,
`price_eod` 10-08 16:41 — every one of them the *second writer* losing, on an `INSERT INTO
news_item` or an `UPDATE`. None since 2026-10-08 16:41, and zero `database is locked` in
24 h of container logs.

**That era is the "lots of jobs running" one, and it is mostly closed.** Counting runs
whose interval overlaps another run's: `news_rss` on 2026-10-05 overlapped **12** jobs,
`price_eod` 11, and the ten worst overlaps are all 2026-10-05 to 10-08.
`MAX_CONCURRENT_JOBS = 1` (63d2a10, 2026-10-06 16:35) is the mitigation that took
`/dashboard` from 164 s to 14 s; since 2026-10-09 only 13 runs have overlapped anything,
nearly all of them sub-second hand-offs between two jobs. **The remaining hole is the
manual path**, which is already its own entry: `run_now` calls `execute_job` directly and
never reaches the executor, which is how `decision` still died of a lock on 10-08 while
overlapping a hand-started `held_refresh`.

What the reader saw at 09:25 that morning was the catch-up burst: `price_eod` ended after
**11 h 49 m**, and `news_analysis`, `news_embeddings` and `held_refresh` started inside the
same second behind it, with `news_sectors` three minutes later. Serial, not concurrent —
one at a time is enough.

### `json_each` cannot use an index, so per-instrument news is a table scan

The tickers on a news item are a JSON array column, so "stories naming this
instrument" is `json_each` on SQLite — which no index can serve. Every
per-instrument news read is therefore a scan of `news_item`.

Measured: 6,555 rows, 0.02–0.06s per instrument page. Fine now, and the fix that made
it correct (see `awltux/db/news.py`) is worth far more than the scan costs. It is
recorded because the shape of the growth is known: news is the fastest-growing table
in the schema, and the decision engine calls this per instrument per run.

**Next:** a `news_item_ticker` join table, written on ingest alongside the JSON
column, with an index on `(ticker, published_at)`. The column stays — it is what the
extractor returns and what the paid feeds are matched against — but reads move to the
join. Do it when a page crosses ~100ms or the table crosses ~100k rows, not before.

**Measured 2026-10-09, and the join table now has a second caller and a second shape.**
`research/evidence.py::news_digest` ranks a subject's news by priority, which needs the
appraisal *and* the age decay, so it reads a bounded window and sorts in Python: **210–290ms**
for an instrument with ~150 in-window stories, of which the ranking itself is most of it. Its
`_coverage` count is the worse shape — a correlated `json_each` over `NewsAnalysis.flags` per
appraisal row, inside a `COUNT`, to answer "how many of these are single-source" — and it is
the reason a `news_item_ticker` join table wants a `news_analysis.subject_id` index beside it.
It fires once per deep-dive rather than once per page, so it is inside the same budget as the
8-second document read above and is not worth fixing on its own.

### `run_on_start` jobs redo their whole work on every restart

Measured while auditing the run history for repeated work, after it was noticed that
several jobs leave a trail of identical rows.

`t212_instruments` has **62 runs against a daily interval** — 2.08 an hour — and
`macro_rates` 25 against six hours (3.41/h). Neither is the scheduler mis-firing. Both
are `run_on_start`, so every process start schedules them immediately whatever their
interval says, and one afternoon of rebuilding produced seven restarts. Each
`t212_instruments` run pulls and rewrites **18,480 instruments**. `universe_refresh` is
the third, at 22 runs against a daily interval.

So most of the duplicated history is restart-driven rather than scheduler-driven.
The other apparent offenders are not the scheduler either: `xbrl_statements` shows
4.55 runs an hour against an hourly interval, but those are manual
`awltux job ... --direct` invocations made while testing it.

Bootstrapping on a *first* start is right — a fresh database needs the universe. On
the seventh restart of an afternoon it is a full upstream sync to rewrite rows that
have not changed.

**Next:** the interval-aware machinery now exists, so this is a registry decision
rather than new code. Catch-up (`AGENTS.md` §1, `scheduler/catchup.py`) gives any job
whose last *successful* run is past its interval an immediate run at start, which is
exactly what `run_on_start` was approximating. All three `run_on_start` jobs are the
genuine bootstrap set, though, and catch-up deliberately does not fire a job that has
never succeeded — so on a fresh database it would not populate the universe.

The open question is therefore only about the *repeat* starts: whether
`t212_instruments` should bootstrap on "no instruments stored" rather than on "process
started", which would keep the first-start behaviour and drop the other 61 runs. The
guard in `scheduler/jobs.py` is where a "ran recently" reason would go, and
`job_statuses` already knows when each job last succeeded.

### The universe news poll needs hours and never finishes

`ingest_rss_news` (`ingest/news.py:766`) walks every instrument in the universe, up to
`news.max_items_per_feed_poll` (**50**) headlines each — 500 instruments, so a
**25,000-item** ceiling — and there is no per-run cap. **There *is* a rotation, and this
entry wrongly claimed otherwise**: `_instruments_to_poll` orders by
`Instrument.news_polled_at` (`ingest/news.py:568-610`, migration `0008_news_poll_cursor`)
with the stamp written per instrument, so a run resumes where the last stopped rather than
restarting at row 0. Measured 2026-10-06, `news_rss` run #220: **3,033 headlines classified
in 97 minutes at a flat 31/minute**, with no decline in the 15-minute buckets from start to
finish (273, 451, 488, 500, 428, 472, 421). At that rate the ceiling is about **13 hours**.

`news_rss` has **0 successful runs in 25 attempts** (re-counted 2026-10-08; the entry said
7), and this is why: a run is a working session long, so every session ends with it still
going.

**Interrupting it is cheap, and that was worth checking rather than assuming.**
`release_write_lock` (`db/session.py:161`) *commits*, and this loop calls it after every
instrument (`news.py:763`); the model client commits at every network boundary too. So
the 3,033 rows were already durable — confirmed by reading them from a *second*
connection while the run was still going, which is only possible for committed data. A
kill loses at most the instrument in flight, and the next run skips everything already
stored (`url_hash` dedup in `persist_items`). The backlog drains across runs rather than
being redone.

So this is not the usual "killed mid-batch is lost work" case. It is worse in one way
and better in another: nothing is lost, but nothing completes either, so the job never
reports success, never enters the catch-up history (`AGENTS.md` §1) and never gets the
restart resilience every other job now has.

**Next:** the rotation is already there, so what is missing is only the per-run item budget
— the shape `fundamentals` uses. A poll that stops at, say, 300
headlines and records where it got to finishes *and reports success*, which is what
makes it eligible for catch-up. The loop also needs the `progress.note` above it before
either can be observed.


### The source registry rates 54 of the 1,175 publishers the corpus actually names

Measured 2026-10-09, after `awltux news-publishers` resolved every stored story to its
writer (`analysis/sources.identify`): **28,174 stories name 1,175 distinct publishers**,
and `analysis/sources._REGISTRY` holds **54**. So 4,205 of the 6,974 stored appraisals now
carry `source_assessed = False` and the grade's "unrated source" caveat — named honestly
and rated not at all, which is the correct state and also a large blind spot.

The head is small and would be cheap to cover. Stories, not appraisals:

    Yahoo Finance        7,642   (rated: aggregator)
    Stock Titan          1,760   unrated
    Investing.com        1,432   (rated)
    TradingView          1,362   unrated
    Simply Wall St       1,318   (rated via the `simplywall.st` domain, not by name)
    MarketBeat           1,118   unrated
    AD HOC NEWS            937   unrated
    Seeking Alpha          937   (rated: opinion)
    The Motley Fool        513   unrated
    dars.gov.et            512   unrated

**Two things to weigh before adding entries.** The registry is editorial judgement with a
stated basis and a `REVIEWED_ON` date, so 20 entries is 20 judgements someone has to stand
behind -- and several of the unrated names are aggregators that republish rather than
report, which is a `kind` decision and not just a name. Second, the tail is not all
publishers, and `dars.gov.et` at 512 rows shows why: sampled 2026-10-09, those headlines
carry *two* suffixes -- "… Shares Test Key Support Levels - Zero Gamma Level -
dars.gov.et" -- with the middle one varying per row (Zero Gamma Level, ETF Flow, Elliott
Wave Entry, Dividend ETF) over a handful of tickers. That reads as machine-generated
content wearing a masthead rather than an outlet, and it is the clearest case of the ~12%
of suffixes that are a bare domain. `identify` cannot tell the two apart on shape, because
a great many real mastheads *are* domains (`finance.yahoo.com`, `kalkine.ca`) and those
resolve correctly through `lookup`. Sample the tail before believing the head.

`tests/test_news_publisher.py` pins the parse; nothing pins the registry's coverage.

### Four pagers still reload the whole page

The recommendations table on `/dashboard` swaps in place (`partials/recommendations.html`,
`/partials/recommendations`, and `wirePartialPaging` in `static/app.js`). The other four
still navigate, so a page change puts the reader back at the head of the document.

Each needs the same two steps the dashboard needed, and no new mechanism:

1. `src/awltux/web/templates/decisions.html` lines 86-169, `jobs.html` lines 215-287,
   `instrument.html` lines 613-627 (the news list) and `news.html` (the whole table, added
   with the corpus page on 2026-10-09) extracted into `partials/*.html` wrapped in
   `<div id="..." data-partial="/partials/...">`.
2. A fragment route beside the page route, rendering that partial.

The one thing to get right is **what the region context includes**, because the fragment
is fetched on every page click and anything page-only is recomputed for nothing. The
dashboard's split is the pattern: `_recommendations_region` returns the rows and the
pager, and `_recommendations_context` adds the summary strip on top. Applied here that
means:

- **`/decisions`** -- the region needs `predictions`, `horizon_windows`, `page`, `pages`,
  `total`, `per_page`, `filters`. It must **not** drag in `reports`, which runs
  `calibration_report` per horizon.
- **`/jobs`** -- the region needs the runs and its own pager state; `stats` and the other
  three tables on that page are page-level.
- **`/instrument/{ticker}`** -- this one needs a new narrow query. `queries.instrument_detail`
  fetches bars, filings, fundamentals, the decision and the valuation, and a news page
  click must not re-run all of that; extract the news block into
  `queries.instrument_news(session, ticker, page, per_page)` and have `instrument_detail`
  call it, so there is one definition.
- **`/news`** -- the region needs `entries`, `total`, `page`, `pages`, `per_page`,
  `filters`. The *filter form* is page-level only because it sits above the table in the
  markup; moving it inside the region would be wrong, since the swappable part is the
  table and its pager. `news_page` currently reads the source and materiality option
  lists from the database to build the filter set, and the region must not repeat that
  read -- `filters.news_specs` needs no options to *parse* a URL (an unrecognised value is
  recorded as ignored), so the fragment can parse with the empty option lists and the page
  keeps the authoritative ones.

`tests/test_partial_paging.py` carries the contract for the dashboard; adding a tuple to
`REGIONS` extends it to each one as it lands.

### `xbrl_statements` coverage counts rows, so a wrongly-read filer is never revisited

`_probe_xbrl_statements` counts CIK-having filers with **no** `xbrl_companyfacts` row at
all, and the job is `backfill=True`, so once that count reaches zero `skip_reason` skips
it. A period extracted with the wrong tags counts as covered. Measured 2026-10-08: of the
**314** in-universe filers with a resolved SEC CIK, **93** have a `xbrl_companyfacts`
period and **221** do not (the entry read 40 and 274). The rotation is
`ORDER BY max(as_of) NULLS FIRST, ticker` with `reports.per_run: 60`, so the 221 drain
first and the 93 already-extracted are re-read as runs 5-6. That ordering is the only
reason the ledger fixes of the same day reached stored rows at all; had those 93 been
extracted last they would have been re-read first and then never again.

**This is the lag both 2026-10-06 fixes ran into**, and neither reaches a stored row on its
own: `analysis/ledger.py` reads stored metrics, so a filer extracted before the fix keeps
the old figures until the job rotates back over it. The EBIT bridge, the interest-income
lines and the four balance-sheet components all share it -- and so does every discovery
the new metric-field registry makes, because a caption learned from one filing reaches
another only when that filing is next read.

**Decide:** is "asked, received, extracted nothing" a *blocker* (stage `extract`), or is it
normal for filers whose statements live in tags `TAG_MAP` does not carry? The honest
answer is probably both, and the blocker would need to say which. It must **not** be
inferred from a missing period, because that would flag all 274 including the ones simply
not yet reached -- the mistake the attention filter's level 2 avoids by only firing when
there is no other route to the accounts.

**Next:** the probe needs a second notion of outstanding -- a period written by an older
version of the mapper. Everything needed is derivable rather than needing new state: the
row carries `as_of`, and `metric_sources` records the tag each figure came from, so
"extracted before tag X existed" is answerable. A mapper version stamped on the row would
make it exact, and it would turn both silent staleness *and* silent emptiness into a queue
entry the job drains.

### Every page is only tested against seeded data

The `engine_label` failure and the empty-universe failure were both invisible to a
green suite because the tests never had rows. Templates and pages are now covered
with a populated database, but the *empty* states are mostly asserted only for a
200.

### The filing picker's tray and its pointer event have no test

Added 2026-10-09. `tests/js/filing_picker.test.mjs` runs under `node --test` from
`tests/test_filing_picker.py`, and covers everything from `transform` (the value rule) through
`pick` (which fact a click found, what it says, the filing's caption for its line, its context's
date) to `confirmUrl` (the query string the confirmation page receives). The seam between those
and the page — `addFigure`'s DOM assembly, the `document.addEventListener("click", …, true)`
registration, and `mount()` — is not covered by anything; a typo there reads as "clicking a
figure does nothing" with nothing in any log.

**Re-measured 2026-10-10**, when the untagged-table fallback was added: the gap is the same
seam and it is now wider. `printedNumber`, `rowFigures`, `markTableFigures`, `matchLabel` and
`step` are exported and driven by the node suite (49 tests), but what runs them on a real
document — `mount()`'s choice between the facts and the tables, the click on a marked `<td>`,
the previous/next buttons, the highlight toggle and `reveal`'s scroll-and-flash — is still
hand-verified only. `mount()` also picks up an account list off the script tag now, and a
malformed one is caught and ignored rather than tested.

The navigation added the same day (`step` is tested; the buttons that call it are not) is the
part that would fail quietly: a mistyped class name in `reveal` reads as "the *show in the
report* button does nothing", and nothing in any log says why.

Verified by hand instead, on 2026-10-09: the tray mounts on the live picker page for filing 278
(Microsoft's 2026 10-K) through the `sandbox allow-scripts` policy, so `document.createElement`,
`appendChild` and the injected `<style>` all work there. The click itself was not driven — the
browser tooling available in that session could not target an `ix:nonFraction` element, because
the accessibility tree gives refs to rows and controls and these carry neither. On 2026-10-10 the
tray was confirmed to mount the same way for filing 1890 (Danaos' 20-F), which is the document
that prompted the fallback and which *does* carry 2,558 tagged facts.

Closing it needs either a click-targeting browser harness or a small DOM stand-in. The second is
~60 lines of stub and was judged not worth it while the logic above it is exported and tested;
that judgement is the thing to revisit, not the tests.

### The build's `--paths` list and the image's `COPY` list can drift

`--paths` is what stops the builder calling itself dirty, so it has to name
everything the runtime image copies. Adding a directory to the image without
adding it to `--paths` fails quietly in the wrong direction: the check simply
stops covering that path, and a modified file in it will not be reported. The
Dockerfile says so in a comment, which is not a test.

### An image built from a dirty `src/` recorded `dirty: false`, so the Info page can name the wrong commit

The evidence, measured 2026-10-07 against the image `awltux-trading:local` created at
`20:36:28Z`, whose provenance artifact was written at `20:35:15Z`:

- The baked `/opt/venv/lib/python3.12/site-packages/awltux/build_info.json` holds
  `"head": 23a6ee0…`, `"dirty": false`, `"version": "0.15.17"`.
- That image's own installed `.../web/static/style.css` is 21336 bytes and contains
  `html { font-size: 17px; }`. It does not contain `--chip-tint`.
- `git log --all -S 'font-size: 17px' -- src/awltux/web/static/style.css` returns only
  `7128f78`, the commit that resolved it. No earlier commit ever contained that text.
- `git show 23a6ee0:src/awltux/web/static/style.css` is 19831 bytes and does not
  contain it, and `git reflog` shows no reset between `23a6ee0` (21:30:03) and the
  build.

So the build consumed a working tree that differed from its own `head` under `src/`
and recorded the tree as clean — the one case the flag exists to catch, and the case
AGENTS.md §1 leans on when it says the Info page must not read *has uncommitted
changes*. The running container was therefore asserting `23a6ee0` while serving code
that was never in it.

Ruled out, each measured rather than assumed:

- **The check works on the host.** `snapshot(paths=[...])` with an untracked file
  under `src/` returns `dirty=True`, and the underlying
  `git status --porcelain -- src pyproject.toml README.md config alembic.ini` lists it.
- **No source bind mount.** `docker inspect` shows only the `awltux-data` volume at
  `/data`, so the stylesheet is the image's own and not the host's.
- **Not a whole-tree status artifact.** The invocation already passes `--paths`, and
  `.git`, `.gitignore` and `.gitattributes` are all copied into the builder before it
  runs (Dockerfile lines 49-60).

**Not isolated.** Reproduce it deliberately next: build with a known uncommitted edit
under `src/`, read `dirty` back out of the image, then bisect with
`docker compose build --no-cache` to separate a stale-cache explanation from a
checking one. Until that is done, the `/info` running-commit check should not be
trusted alone — what actually caught this was comparing the image's own files against
the commit, which is worth doing in the deploy verification regardless.

### `icon.svg` names the UI's palette as its own, and two of those colours moved

The icon's comment says it is "built from the same colours as the UI: the panel
gradient, the divider grey, and the two greens the price sparkline uses". Enlarging
the interface's text moved two of them, so the comment is now false and the mark is
subtly off-brand:

| Where in `icon.svg` | Holds | UI now says |
|---|---|---|
| line 28 `#3fb950`, line 45 `#3fb950` | `--good`/`--buy` before this | `#4fd35f` |
| line 37 `#2a323c`, line 40 `#2a323c` | `--line` before this | `#39434f` |

The panel gradient (`#1e242c` → `#0f1216`, lines 24-25) still matches `--panel-2`
and `--bg`, which did not change. Nothing detects the drift: `tests/test_app_icon.py`
checks the files exist, are square and are linked, and no test couples the SVG to
`style.css`.

Not done because the four raster files are regenerated, not edited --
`tools/render_icons.py` needs `cairosvg` *and* `pillow`, and neither is installed.
`pip install cairosvg` was attempted in `.venv` and failed, so editing the SVG alone
would put the SVG and the committed PNGs out of step, which is the failure the
script's own docstring warns about. **Pay this off with the two packages present:**
change the four hex values, run `python tools/render_icons.py`, and commit the SVG
with the regenerated PNGs/ICO together.


### The value-investing education ingest has 83 core videos left to acquire

The tooling is built and lives in `ingest_youtube/` (`run.py plan|fetch|distill|report|quota`,
54 offline tests, its policy and pacing in `ingest_youtube/README.md`). The remaining work is
acquisition, not construction:

    23 transcripts held of a 94-video core tier (100 raw, 6 dropped as duplicates/overlap)
    83 core videos outstanding;  15/day at a 24h cooldown -> about six days

Two things it needs before the next run, both measured 2026-10-08:

* **`.tmp/probe-out/PRfXq-NlJqo.txt` is a transcript the ledger cannot see.**
  `PRfXq-NlJqo` is `core` in the inventory and is absent from `ingest_youtube/transcripts`,
  but `fetch.adopt_existing` only reads `.tmp/transcripts` (`fetch.py:49`, `fetch.py:506`), so
  the next fetch spends a request re-fetching a transcript already on disk. Move it into
  `ingest_youtube/transcripts` or it is paid for twice.
* **The 42 selected playlists have never been expanded into their videos.** They are the
  larger half of the coverage the plan describes, and expanding them may change what "core"
  means before the remaining 83 are fetched -- cheaper to decide first than to re-fetch.

`docs/research/education-sources.json` (42 playlists / 181 videos) is read by no code; the
tool reads `ingest_youtube/inventory/edu_*_tiered.json` (`run.py:40-43`). Two records of the
same selection, so one should go.

### The ticker cannot group events, because the stories it shows are the ones without vectors

Measured 2026-10-08, after the ticker was floored by materiality and collapsed by headline:
one event was still two entries -- "McKesson, CD&R to buy Option Care Health for $5.8
billion" and "CD&R and McKesson Corporation Sign Agreement to Acquire Option Care Health",
both `critical`. The exact-headline collapse cannot see them (different sentences) and the
embedding grouping could not run:

    ranking window (600 rows)          280 of 600 have a vector
    the newest 15 by id                  0 of 15
    the top 15 by the app's own ranking  1 of 15

**Why the top of the banner is the worst-served part.** `news_embeddings` runs hourly
(`config.py:265`, `schedule.news_embeddings = 3_600`) and its pending set is
`relevant IS TRUE`, ordered by **`id DESC`**, `limit=max_per_run` (1000). The ticker picks by
**materiality x credibility x recency**, which is a different set: a `critical` story stays
at the top of the banner for hours, while the embedding ration goes on the thousand newest
relevant stories -- most of them `mild` or `none`, which the materiality floor now excludes
from the banner entirely. So the allowance is spent where the grouping is not needed.

The gap is visible in the ids: newest vectorised story 26,201 against newest story 27,231.

**Next:** order the embedding pending set the way the banner ranks -- materiality first, then
recency -- or embed only stories that clear `ticker_min_materiality`. Both are a change to
`embed_news`'s selection. Check first whether the same-event grouping in the decision
pipeline (`Identity.conflicts`) depends on the newest-first order before changing it; if it
does, the selection needs two queues rather than one reordering.

### The order-history cursor repeats itself, and a truncated backfill never resumes

Two properties of `/equity/history/orders`, measured 2026-10-08 while landing the trades
table:

- **The cursor is a timestamp and several fills share one, so pages overlap.** Walked with
  `limit=200`: 200 items, **148 distinct ids** -- 28 ids repeated, some six times -- and the
  id sequence not strictly descending. `_paginate` now drops ids it has already seen, so the
  repeats cost requests rather than correctness. The whole history is 263 distinct orders in
  367 items over eight requests, from 2024-03-18.
- **A backfill that hits `ORDERS_PER_RUN` cannot be resumed.** The walk starts from the
  newest and stops at the newest id already stored (`since_order_id`), so it only ever moves
  *forward*: whatever the first run does not reach is unreachable for every later run.
  `ORDERS_PER_RUN` is now 1,000 (the paginator caps at 40 pages of 50 either way), which
  covers this account with room to spare, and a ceiling hit is reported in the run's note
  instead of claiming "more will arrive next run".

What is owed: an account whose history exceeds 2,000 raw items silently keeps only the
newest slice. Resuming means walking from the newest while *skipping* everything at or above
the oldest stored id, which re-reads the newest pages every run until the backfill closes;
worth doing only if a real account ever needs it, and it needs a `since_order_id`-shaped
parameter that filters rather than stops.

---

### More of the Trading 212 account is readable than is stored: dividends, cash and pies

The positions and order-history work put two endpoints on the graph. Probing the same key on
2026-10-08 showed four more, all reachable and none stored:

| endpoint | carries | probed |
|---|---|---|
| `/equity/history/dividends` | `paidOn`, `amount`, `grossAmountPerShare`, `quantity`, `ticker`, `type` (ORDINARY / BONUS / DEMERGER) | 5 items, e.g. `VWRLl_EQ` £250.49 paid 2026-09-30 |
| `/equity/history/transactions` | cash movements in and out of the account | not read |
| `/equity/pies`, `/equity/pies/{id}` | which pie an instrument sits in, its weight and target | not read |
| `/equity/history/exports` | async CSV report generation | not read |

**Dividends are the one worth doing next**, and they are not just a page row: a dividend is
a realised return that the calibration work currently cannot see, so `decision_outcome`'s
`return_pct` omits cash actually received. That makes it a correctness question about the
performance figures rather than a display one -- measure what the ledger currently reports
against the dividend history before adding a table, because the two should agree and today
nothing checks.

`/equity/pies` is the cheapest of the four and the most decorative: it would let the
instrument page say "this is 4% of your Tech pie", which is context rather than analysis.

Both `get_dividends` and the pie endpoints need provider methods; `get_dividends` already
exists (`providers/t212.py:240`) and has no callers, the same way `get_order_history` had none
before this work.

### Reading a deep-dive's documents costs 8 seconds, and it pays it on every run

Measured 2026-10-09 while building the evidence builder, against the live corpus: building the
whole evidence set for MSFT takes **8.4–10.9 seconds**, and `research/evidence.py` itself is
not the cost -- the two `news_digest` queries together are 0.45s. The rest is
`ingest.parsing.document_text` running BeautifulSoup over two 8.5MB inline-XBRL 10-Ks
(357,714 and 322,000 characters of text out).

That is acceptable *where it is*: a deep-dive is a once-per-subject, button-pressed run that
then spends minutes on a model call, so eight seconds is noise inside it. It is recorded
because the same helper is on the filing-extraction path (`ingest/parsing.py::_read_one`),
which reads up to `PARSE_LIMIT = 4` documents per instrument per refresh, and because the
answer is already on disk: `Filing.doc_hash` identifies the bytes, so the extracted text could
be cached beside the raw file and re-read instead of re-parsed. Do it when a refresh's parsing
phase shows up in a job's duration, not before -- the parse is not currently anyone's
bottleneck, and a cache keyed on a hash that a re-issued document changes is a cache that can
serve the wrong filing's text.

The other number from the same measurement: the evidence for MSFT came to **410,826
characters, about 120,800 tokens**, against a 128,000-token window and a 16,000-token answer.
That is now bounded by `research.context_tokens` -- the trimmer cut it to 91,434 tokens by
halving the older 10-K -- and the trim is recorded in the report's footer and in
`Evidence.dropped`. Raising `research.max_total_document_chars` above 400,000 therefore does
*not* raise what the model is sent; it only changes which end of the documents gets cut.

### A subject with more than 25 deep-dives loses the older ones from the page

`research.list_limit` caps the report list at 25 and the list is not paged -- `web/queries.py::
research_reports` takes the newest `limit` rows and the template renders them all. So past 25
reports about one company the older ones are still in the database, still on disk, and
unreachable from the page. Nothing is lost; it is invisible, which is the failure mode
`TODO.md`'s own queue rule calls the quieter one.

Cheap to fix when it matters: the same `partials/_pager.html` the news list uses, and the
search-param plumbing `instrument_page` already has for `news_page`. It is not fixed now
because a subject reaching 25 deep-dives means 25 deliberate button presses, and the honest
fix at that point is a filter (by verdict, by date) rather than a second page of identical
rows. Measure how the reports are actually distributed before choosing.

### The reports list does not say whether the newest decision saw a report

Added 2026-10-11. The entry this replaces recorded that a finished deep-dive never reached the
decision: `research.service` wrote the report and returned, and `decision` is on its own
interval. That gap has since been addressed -- `research/service.py::_follow_up` re-runs
`valuation` and `decision` for the instrument at the end of the research run, which is option 1
of the three that entry weighed and the one that costs a model call per report. It is also why
`RESEARCH_FOLLOW_UP` exists as a named constant rather than a derived list: no `JobSpec.depends_on`
declares it, because research is an amendment to the pipeline rather than an input to it.

What is still owed is the reader-facing half. When two judgements about one company sit on one
page, the question is *did the decision see this report*, and nothing answers it: the only way
today is to expand the decision's canonical state and search it for `deep_research`.

Measured 2026-10-11 on the live database: report 4 (SCHW_US_EQ) finished 15:25:49, and decision
run 2123 at 15:42:06 carries `deep_research` in its state while runs 2122 (15:25:15) and 2110
(14:47:54) do not. So the field distinguishes the two cases, and the marker needs no new query:
`ResearchReport.run_id` is already stored, and `web/queries.py::research_reports` already reads
the report rows the Research tab lists. The wording has to separate "a decision has run since
this report" from "the newest decision read it" -- those coincide only because the two now run
in sequence, and a report whose follow-up was skipped for a lease has the first without the
second.

### The rolling twelve months is now visible nowhere

Found 2026-10-09 while keying the accounts by financial year. `yahoo_info` writes a `ttm`
row per instrument -- **33 rows across 29 instruments**, and `FundamentalPeriod.period_type`
has carried `ttm` since the schema was written -- dated at the moment it was read rather than
at a period end (MSFT's is 2026-10-07, mid-quarter). It is not an account of a year, so
`analysis/collate.py` excludes it from the financial-year slots and the Accounts tab no longer
lists it; a direct link to one still opens, and the page says what it is.

Nothing is lost from the database, and the analysis is unaffected -- `build_snapshot` uses
`ttm` only when a company has fewer than two annual periods, and no instrument has only a
`ttm` row. What is lost is *visibility*: the freshest figures held for 29 instruments are no
longer on any page, so a reader cannot see that a rolling snapshot exists or what it says.

Two honest answers, and the choice depends on what the row is for: show it as a labelled
footnote on the year list ("rolling twelve months to 2026-10-07, not a financial year"), or
stop writing it and retire the `period_type` value. The second is defensible -- a trailing
twelve months is derivable from the quarters -- but it would remove the only figure held for
a company that has filed nothing yet, which is exactly when a reader wants one.

### The accounts page mixes the filer's declaration with another source's figures

Found 2026-10-09, visible on Microsoft's FY2026 page: the ledger lays out the filer's own
tagged accounts while the Computed column and the composition checks come from the *filing's*
declaration, read from the row our model extracted (`accounts_detail` returns `filing_period`
for `_filer_arithmetic`). And the figures those checks add up are the chosen row's. So
"Operating income 155,237,000,000, out by -26,710,000,000" is partly a difference between two
sources rather than a contradiction inside the filer's own arithmetic -- in that case the
extracted SG&A line differs from the filer's by 70%.

The residual is not wrong to *show*; it is wrong to attribute to the filer's arithmetic. Two
ways out: run the checks against the row the declaration came from and label the panel with
which source it describes, or reconcile the declaration against the chosen row's own tag index
so the comparison is inside one source. The first is smaller and keeps the declaration's
figures adjacent to the lines they add up. Either way the panel has to say which source it is
measuring, because a reader cannot currently tell.

**Partly mitigated 2026-10-09, not fixed.** The "out by" figures on that page are now links into
the filing (see the README), so the mixed-source residual on Microsoft's FY2026 page can be
followed to the figure the filer actually tagged — which is what makes it visible that the
extracted SG&A line, not the filer's arithmetic, is the problem. That is a way to *repair* one
line by hand; the page still does not say which source it is measuring.

---

## Deliberately not doing

### A per-instrument blocker for `edgar_events`

Re-measured 2026-10-16, when blockers were wired into the other five jobs that were
missing them. `edgar_events` has no per-instrument failure to record: its only failure
path is the current-events request itself (`edgar.py::ingest_current_events` catches
`ProviderError` once, before the loop, and returns), which fails for every instrument at
once and is not a fact about one company. Entries whose CIK matches no instrument are
dropped rather than guessed at, and those CIKs are by definition not instruments we hold.
A blocker here would have to invent a per-instrument failure for a feed-level fact.

### Day trading / intraday horizon

Trading 212 exposes no quote or candle endpoint and the free feeds are ~15 minutes
delayed, so the maths is built on daily bars and `short_term` is a 5–20 trading
day swing. An intraday horizon is only worth adding behind a paid real-time feed.

### Making the free-tier data authoritative

`yfinance` is an unofficial scrape and will break; UK iXBRL coverage from Companies
House is roughly 60–75%. Both are labelled in the UI, and neither should be
treated as a source of record.

### Splitting the long functions the cooperative stop had to reach into

`python tools/refactor_report.py`, re-measured 2026-10-16 after the boundary checks were
added to the last six jobs: `decision/service.py::decide_instrument` 185 lines,
`analysis/news_analysis.py::analyse_universe` 121, `analysis/news_analysis.py::
appraise_item` 114, `ingest/news.py::persist_items` 102, `decision/service.py::
decide_universe` 78. The numbers moved since this was written and only downward for the
first and last of them (`analyse_universe` was 138 and `decide_universe` 87, both split
partly in the meantime); `appraise_item` grew by 8.

The six loops the boundary work touched are the same family and belong in the same pass:
`ingest/jobs.py::assess_news_relevance` 171 lines, `ingest/jobs.py::resolve_symbols` 135,
`ingest/jobs.py::embed_news` 116, `analysis/sentiment.py::aggregate_all` 116,
`ingest/documents.py::deepen_annual_history` 112. Each gained one `progress.checkpoint`
or two, and none of them grew materially for it -- the point is that they are the loops a
reader reaches for when asking where a job can be left, so they are the ones worth
splitting.

`ingest/news.py::ingest_rss_news` joins them, re-measured 2026-10-16 at **87 lines** after
the rate-limit work: the marketaux ration added the slice, the allowance and the
translate-an-exhausted-budget-into-a-clean-stop branch. It had been split to 62 for the
cooperative stop, so this is the second time it has grown past 70, and the honest next
move is a walk-context object (`session`, `feeds`, `settings`, `prefilter`, `classifier`,
`report`, `total`) rather than a nine-argument helper -- `_Feeds` is already the first half
of that idea. `persist_items` is still the one to do first.

The enforced gate is complexity at 15 and all of these pass it. The two functions the stop
logic *did* grow materially -- `ingest_rss_news` (77 → 99, then split back to 62 via
`_poll_instrument` / `_finish_instrument` / `_Feeds`) and `_execute_captured` (60 → 85,
split back via `_invoke` / `_Outcome`) -- were paid off in that same commit.

### A figure clicked out of an untagged table cannot become a line of its own

Added 2026-10-10 with the table fallback in `filing-picker.js`. A figure clicked out of a
document with no `ix:` elements carries no taxonomy tag, and a learned line's identity *is* its
tag (`analysis/corrections.py`: "the identity the filing gives the caption"), so the
confirmation page offers it on an existing line or a previously learned one and says why it
cannot offer the caption as a new line.

What it would take is an identity that survives next year's filing, and none of the obvious
candidates is one: the caption verbatim is the filer's presentation ("Total current assets" one
year, "Total current assets:" the next), and a hash of it is the same string with the same
problem. The honest version is a per-filer *name* the reader gives once -- the learned-line
machinery with the tag column empty and a stable key the reader chose -- which is a feature, not
a fix, and is worth building only when a filer without XBRL actually needs a line this project's
chart lacks. Measured 2026-10-10: 2 of the 603 stored documents have no `ix:` elements at all
(`AREC_US_EQ`'s 10-K, `BMM_US_EQ`'s 40-F), and neither has been read by hand yet.

### Reading the tables of a *partly* tagged document

Added 2026-10-10. The table fallback runs only when a document has **no** `ix:nonFraction`
elements. A filing that tags its statements but not, say, a note, would get the tagged half and
nothing from the tables -- which is the right default, because a second reading of the same
table could only disagree with the filer's own tags, but it is a judgement rather than a
measurement. What would settle it: a count of stored documents that hold both tagged and
untagged numbers in the same table, which nothing measures today. Two documents of 603 have no
tags at all and 601 have tags; the mixed case is assumed to be rare and has not been counted.

### A `TypedDict` over the instrument page's context

Added 2026-10-11, from a QA pass that flagged `_instrument_context`
(`web/routes/dashboard.py`) as a ~40-key untyped dict whose own docstring records the failure
mode: "a key the route forgets renders as nothing at all, which is how the trades table and the
event grouping were both lost for a commit each".

It is not made one because the annotation could not be honest. Two groups of keys do not arrive
as literals -- `**detail["research"]` and `**_lever_context(detail, request)` -- and `detail`
comes from `queries.instrument_detail`, which returns `dict[str, Any]`. A `TypedDict` would
therefore have to *declare* keys it cannot *check*, so it would read like a guarantee while
enforcing nothing. There is also no type checker in the gate (ruff's selected rules are
`E, F, I, UP, B, SIM, C90`), so even a sound annotation would not fail a build.

What actually guards the failure mode is `tests/test_instrument_tabs.py`, which renders every
tab and asserts its topic is present. One gap in that guard was closed in the same pass: the
`research` tab was missing from `test_each_tab_renders_its_own_topic`, and it is the tab whose
content is one of the two `**`-splats.

The residual cost is small but real: adding a context key means editing one large dict literal
with no help from the tooling. Revisit if a type checker is ever added to the gate, at which
point the sound fix is to type `instrument_detail`'s return first, not to annotate the context
on its own.
