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

Priority: **P1** wrong or missing data, **P2** broken or fragile behaviour,
**P3** documentation and polish.

---

---

## Bugs

None open. The two before this one — a cache key that ignored the query string, and a
`uk_companies` walk that attempted the same eleven instruments on every run — were found
together in 2026-10-07 and are in the commit log.

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

---

## Correctness questions still open

### Not one decision in 1,495 has been allowed, and it is a data gap rather than a verdict

Measured 2026-10-07. `decision_run` holds **1,495** rows and `gate_allowed` is **0** on
every one. 1,344 are `avoid`, 146 `hold`, 4 `reduce`, 1 `buy`. The question was whether
the gate is too strict or the universe is genuinely unattractive; the answer is neither.

**What binds.** Two rules, and almost nothing else:

    982  confidence_below_floor   "confidence 25% is below the 55% floor"
    499  price_stale              "price data is 37h old (limit for long term is 36h)"
     13  (none)                   `avoid` produces no suggestion anyway
      1  probability_below_floor

**The scores are not being suppressed -- there is nothing to suppress.** Across the whole
universe the composite score runs 0.6 to **63.5**, median 32, and only **6 decisions
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

### `xbrl_statements` reports success when the payload yields no periods

A fetch that returns a payload we cannot extract anything from is recorded as a
*succeeding* run. Measured 2026-10-07 against the live database: of the **314**
in-universe instruments with a resolved SEC CIK, only **40** have a period from
`xbrl_companyfacts`. The other **274** have nothing, and nothing anywhere says whether
that is because the rotation has not reached them or because we asked, received a
payload, and took no figures out of it.

The two cases need different fixes -- waiting versus reading the tags differently -- and
they are currently indistinguishable. `_write_periods` returns `written == 0` for the
second case, and `_sync_one` treats it as success: it clears any blocker and moves on.

**Decide:** is "asked, received, extracted nothing" a *blocker* (stage `extract`), or is
it normal for filers whose statements live in tags `TAG_MAP` does not carry? The honest
answer is probably both, and the blocker would need to say which. Recording it is the
cheap half and it is the half that makes the case visible at all; it must **not** be
inferred from a missing period, because that would flag all 274 including the ones simply
not yet reached -- which is exactly the mistake the attention filter's level 2 avoids by
only firing when there is no other route to the accounts.

### The accounts come from `companyfacts`, not from the filing's own XBRL

Answered for a reader asking whether the tags in the Form 10-K are used. They are not,
and the distinction costs three things.

Every stored period is `source = "xbrl_companyfacts"` (92 of 92), fetched from
`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (`providers/edgar.py:373`).
That **is** the filer's own tagging — the SEC's aggregate of what they submitted — reached
through a different artefact, mapped to canonical names by a hand-maintained `TAG_MAP`
(`ingest/xbrl.py:82`) and filtered to annual forms, with the **earliest filed** fact
winning per period so a later restatement cannot leak hindsight backwards.

What is unused:

- **The calculation linkbase** (`_cal.xml`) — the filer declaring, machine-readably,
  which lines sum to which subtotal. That is the issuer publishing its own double-entry
  arithmetic, and it is precisely the cross-check the accounting-health tab does not
  have: today `ledger.composition` compares our components against our own assertions.
- **The presentation linkbase** (`_pre.xml`) — which statement and section a tag belongs
  to, instead of the order `TAG_MAP` asserts.
- **Inline XBRL in the document** — nothing in the repo parses `ix:nonFraction`, even
  though `shareholder_reports` downloads the 10-K bytes. `extract_filing`
  (`llm/extractors.py:267`) is the document-reading path and is still called from
  nowhere; it is the same gap listed under the marker queue.

**Why it matters now:** it is the most likely explanation for the accounting-equation
failures recorded under Operations (DFPH out by 95% of assets, AMBQ by 362%). Those are
a tag meaning something different for that filer — a different context, a restated
value, a concept whose definition moved — and the filer's own calculation linkbase is
what would settle it.

**Next:** fetch `_cal.xml` alongside the filing and check `ledger`'s subtotals against
the filer's declared sums, rather than against ours. Self-contained, and it upgrades a
plausible check into an authoritative one. Also worth knowing: `companyfacts` is the
undimensioned aggregate, so a figure that exists only per-segment or per-class-of-stock
is simply absent, and the linkbase path is the only route to it.

**Half of it is built and tested; the wiring is what is left.** `ingest/linkbase.py`
parses a `_cal.xml` into weighted parent/child declarations (pure; 20 tests in
`tests/test_linkbase.py` against `tests/fixtures/dfph_20251231_cal.xml`, DFPH's real
FY2025-12-31 linkbase, pinned by sha256). `analysis/linkbase.py` reconciles a stored
period against it and returns `ledger.Check`s, separating the three cases below. What
is *not* done: nothing fetches a linkbase from EDGAR, nothing stores one, and no page
passes one to `checks()` -- so the reconciliation runs only in tests today. The
remaining steps are (1) a provider call that resolves `*_cal.xml` from the accession
directory's `index.json`, (2) an additive column on `filing` to cache
`Linkbase.as_dict()` with its digest and source URL, (3) a bounded fetch step in the
`filings_edgar` or `xbrl_statements` job, and (4) routing it into the accounts page.

**And it would give the attention filter its second real signal.** Today the only
accounting reason `analysis/attention.py` can raise is the equation, because
`assets_composition` fails for 36 of the 43 instruments holding accounts and most of
those are our own missing lines. A stored linkbase turns that into
`reconciliation.contradictions` -- every declared line held and still not summing --
which is a genuine discrepancy and belongs at level 1 beside the equation.

**The route is now open.** `Filing.period_end` was populated on 0 of 4,958 rows and is
now set from EDGAR's `reportDate` (4,602 of 4,958 after one `filings_edgar` run; the
356 without it are S-1s and the forms whose `reportDate` EDGAR leaves empty). So a
stored `FundamentalPeriod` can be matched to the annual filing that reports it on
`period_end`, and `Filing.url` already carries the CIK and accession the linkbase path
is built from. Probed on DFPH's 10-K for FY2025-12-31
(`.../1799191/000179919126000007/toi-20251231.htm`): the accession directory's
`index.json` lists `toi-20251231_cal.xml`, 91,210 bytes, and it parses into 14 roles
with 28 arcs on the balance sheet alone -- including `us-gaap_Assets` as exactly six
declared children. Two things that probe settled: the filer also declares its *own*
extension tags (DFPH has `toi_DerivativeWarrantLiabilitiesNoncurrent`), which no
hand-maintained `TAG_MAP` can know, and the filer states subtotals we do not model at
all (`us-gaap_OperatingCostsAndExpenses`). So the check has to separate "the filer
declares a line we do not hold" from "we hold every declared line and it still does
not sum" -- only the second is a contradiction.

**Use `metric_sources`, not a reversed `TAG_MAP`.** `FundamentalPeriod.metric_sources`
already records, per metric, the exact tag the figure came from
(`span = "us-gaap:Assets"`, plus the accession and form), so the mapping from a
declared linkbase tag to the value we hold needs no guessing at all -- and it is the
*right* tag rather than the preferred one, which matters for exactly the filers whose
`TAG_MAP` entry is the unusual case. Verified on DFPH's FY2025-12-31 period: 27 of its
metrics carry provenance and every tag matches the linkbase's declared tag verbatim.
Linkbase `xlink:href` fragments are `us-gaap_Assets` (underscore), so the join key is
the fragment with its first `_` replaced by `:`.

**What the failures actually look like, before blaming the tags.** Re-measured
2026-10-07: DFPH's equation itself is `ok` (180,376,000 liabilities less 15,720,000
equity reconciles to 164,656,000 of assets). What fails is `composition` -- and the
stored period holds no `cash`, no `other_current_assets`, no `operating_lease_assets`
and no `other_noncurrent_assets` at all, while the linkbase declares each of them. A
component check that fails because we hold four lines fewer than the filer declares is
reporting our own coverage, not a filer error, and the current wording ("Components sum
to stated total assets") does not say which. That is the first thing the linkbase makes
sayable.

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

### Every long-term decision so far has failed its own gate

`decision_run` holds 81 rows and `sum(gate_allowed)` is **0**: no long-term call has
been actionable. Short term is not the same story — 2 of the 81 pass — so this is not
"the gate refuses everything", it is specifically the long-term checks.

The decisions look ordinary. 76 came from DeepSeek and 5 from the deterministic
engine, and no JEV key is configured, so every one is also uncalibrated. Of the 81,
77 answer `horizon_fit = neither` and 4 `short_term`; the binding rules are
`price_stale` (52) and `confidence_below_floor` (28).

Both of those are the gate doing its job on a universe with no accounts stored —
`fundamentals` coverage is the real constraint, and a stale price is a stale price.
The open question is whether the confidence floor is calibrated against that
universe or is a threshold nothing can clear. **Not investigated.**

**Next:** read one decision's `gate` JSON against its `answers`, and see which
check refused it. The gate reason strings are supposed to be specific enough to
answer that from the receipt alone, so if they are not, that is the bug.

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

### The identity keys are stored, but 5,800 existing rows do not carry them

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
and **every existing row is NULL**. The veto reads an absent key as "not stated" rather
than "different" -- the alternative would veto every join until the data caught up,
silently -- so the metric half is inert until rows are re-classified. `news_relevance`
backfills at **200 model calls per run** (`news.relevance_backfill_per_run`) against
5,800 rows, so roughly 29 runs.

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

**Re-measured 2026-10-07: 16,512 of 19,919 stories (83%) carry one**, so this is much
smaller than it was and much smaller than it reads. The 3,407 without are the sector
stories `news_sectors` captures -- a sector feed has no company to classify against, so
the classifier was never asked -- plus older rows. Worth correcting the framing rather
than the code.

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

---

## Operations

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

The add: record an `llm_call` row per embeddings *request* (not per story) with
`provider="fal"`, `purpose="embeddings"`, the token count fal returns in its usage block,
and `cost_usd` from the model's published per-million rate. It needs the rates in
`config.yaml` beside `news.embeddings`, because they are per model and the parser already
knows which model answered.

### Six sweeps still do not skip an instrument a refresh is working on

The one-instrument refresh takes a lease (`ingest/lease.py`) and the sweeps consult it so
the two cannot write the same company at once. Six of them do not yet: `filings_edgar`,
`shareholder_reports`, `uk_companies`, `news_relevance`, `news_analysis` and
`sentiment`. Wired: `price_eod`, `fundamentals`, `xbrl_statements`, `news_rss`,
`valuation` and `decision` — the six that call `lease.exclude_locked(...)` on their
instrument selection.

The add is one line each, and it must go on the *selection*, not inside the loop: a job
that has already loaded its instrument list would re-ask per item at best, and at worst
an instrument fetched before the lease was taken sails past a check placed after the load.
`decide_universe` is the worked example — it slices an in-memory list by `limit`
afterwards, so a post-load check would still spend one of the sweep's slots on an
instrument it must not touch.

Cost of the gap, measured rather than assumed: a collision is a *wait*, not a corrupted
figure, because SQLite serialises the writes either way — so this is worth doing and is
not an emergency. `refresh.py` does not pause the scheduler for its duration, which would
close the window completely, because a thread that died while holding the pause would
leave the whole scheduler stopped; the lease expires and that failure mode does not exist.

### Only two jobs record a per-instrument blocker

`instrument_blocker` exists so a *missing* figure is not mistaken for an answer, and
`fundamentals` and `xbrl_statements` write to it. Every other job that can fail one
instrument and succeed the rest still records nothing: `shareholder_reports` (a refused
download is in `download_errors` and nowhere else), `filings_edgar`, `uk_companies`,
`edgar_events`, `prices` and `symbol_resolution`.

Measured 2026-10-07, which is why this is a queue item and not a hypothetical: parsing
the per-instrument failure lists out of the last **400** `ingest_run.detail` payloads
found **5 instruments** in total. The lists are free text, each job words its own
differently, and `retention` prunes the detail away -- so the evidence exists in the log
and decays before anyone can act on it.

The add is mechanical: `record_blocker` where a job appends to its failure list,
`clear_blocker` where it succeeds. `uk_companies` is the one to do first, because the
level-2 reason for a UK listing is "no Companies House number" and a *rejected* lookup is
a different and more actionable problem with the same em-dash today.

### `decision` still sweeps the whole universe, and six jobs have no stopping point

Two jobs, one conclusion, and the second was found by being blocked twice in a row.

**`decision` has no batch limit at all.** Measured on the live container: run #127
started 12:37:47, wrote **52 decisions in 12.8 minutes** — 4.1 per minute against a
universe of 500, so roughly **110 minutes remaining**. Every other expensive job
here is bounded for the same reason: `fundamentals` rotates
`fundamentals_rotation_per_day`, `symbol_resolution` takes `symbol_resolution_per_run`,
shareholder reports take `reports.per_run`, `refresh_prices_eod` chunks at 40.
`decision` sweeps the whole universe in one call.

**`news_analysis` is bounded and still far too long.** It appraises at most
`news.scepticism.max_deep_per_run`, which is **40** — and at a model call per story
that is **14 to 39 minutes**: the three runs on record took 826s, 1831s and 2351s.

All three of those are recorded `ok=False` with *"interrupted: the process restarted
while this run was in progress"*, and that is the evidence, not a coincidence. Each
one was killed by a redeploy. Two of them were killed by deployments for this very
objective, after `awltux quiet --timeout 300` returned exit 3 and the rebuild went
ahead anyway.

Re-measured 2026-10-06 18:1x, and the pattern is now total rather than occasional:
**`decision` has 6 runs and 0 successes, `news_analysis` 5 and 0, `news_rss` 7 and 0.**
Every attempt at all three has failed, and the failures are interruptions rather than
logic errors. Two consequences worth stating, because both were inferred wrongly before
this was measured:

- The 184 decisions in the ledger were written by runs that never reported success.
  `decision` writes incrementally, so a killed run is a partial run and not an empty
  one -- which is also why "0 successes" is not evidence that nothing works.
- Catch-up (`AGENTS.md` §1) keys on the last **successful** run, so these three read as
  "never succeeded" and are deliberately not caught up at start. They keep the ordinary
  randomised first run, which lands within the hour. That is adequate, but it means the
  job that most needs restart resilience is the one job the restart rule does not
  cover -- if a restart ever lands inside the hour, one interval is lost.

What catch-up changed: an interrupted run is no longer *lost work*, because an
unsuccessful run does not count and the job is repeated at the next start. What it
costs is the provider and model budget of doing the work twice, which for these two is
the expensive part.

**A running job can now be asked to leave at its next item boundary**, which is the
first of the two changes this entry wanted and is described in `AGENTS.md` §1
(`progress.checkpoint` / `progress.barrier`, and the process-global stop request that
`quiet()` and `drain()` set). Correcting what this entry used to claim: `quiet` *can*
report `idle` while `decision` or `news_analysis` is running -- those two stop on
request now, as does `news_rss`. The claim that it never could is stale.

**Still owed, and the stop settles neither:**

1. **Bound `decision`** with a per-run limit and a least-recently-decided rotation, the
   shape `fundamentals` already uses. At 4.1/min, 500 instruments cannot complete inside
   one daily interval, so the daily cadence is not honest either. A job that can be
   asked to leave is not a job that finishes.
2. **Six jobs have no boundary to check.** `sentiment`, `shareholder_reports`,
   `symbol_resolution`, `filings_edgar`, `news_relevance` and `news_embeddings` have no
   `progress.note` inside their per-item loops at all, so a `quiet` still waits for the
   whole of them. Fixing it is two changes each -- add the note (itself owed, since a
   long job with no line in its log cannot be told from a hung one) and make it a
   `progress.barrier`. `fundamentals`, `xbrl_statements` and `refresh_prices_eod` do note
   per item and were left alone deliberately: each is rationed to a per-run limit of 2,
   60 and 40 batches, so the exposure is minutes rather than hours.

Lowering `max_deep_per_run` is not a fix: 40 stories is already a rationed batch,
and cutting it further only means the backlog grows instead.

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

`ingest_rss_news` (`ingest/news.py:346`) walks every instrument in the universe, up to
`news.max_items_per_feed_poll` (**50**) headlines each — 500 instruments, so a
**25,000-item** ceiling — and there is no per-run cap and no rotation. Measured
2026-10-06, `news_rss` run #220: **3,033 headlines classified in 97 minutes at a flat
31/minute**, with no decline in the 15-minute buckets from start to finish (273, 451,
488, 500, 428, 472, 421). At that rate the ceiling is about **13 hours**.

`news_rss` has **0 successful runs in 7 attempts**, and this is why: a run is a working
session long, so every session ends with it still going.

**Interrupting it is cheap, and that was worth checking rather than assuming.**
`release_write_lock` (`db/session.py:161`) *commits*, and this loop calls it after every
instrument (`news.py:378`); the model client commits at every network boundary too. So
the 3,033 rows were already durable — confirmed by reading them from a *second*
connection while the run was still going, which is only possible for committed data. A
kill loses at most the instrument in flight, and the next run skips everything already
stored (`url_hash` dedup in `persist_items`). The backlog drains across runs rather than
being redone.

So this is not the usual "killed mid-batch is lost work" case. It is worse in one way
and better in another: nothing is lost, but nothing completes either, so the job never
reports success, never enters the catch-up history (`AGENTS.md` §1) and never gets the
restart resilience every other job now has.

**Next:** the shape `fundamentals` already uses — a per-run item budget with a
least-recently-polled rotation over the universe. A poll that stops at, say, 300
headlines and records where it got to finishes *and reports success*, which is what
makes it eligible for catch-up. The loop also needs the `progress.note` above it before
either can be observed.

### The accounting checks fail on most stored periods, and the cause is the vocabulary

First found by the trial balance on the accounts page (`analysis/ledger.py`) on 2026-10-06,
when the entry said "of the 22 instruments with a computable equation, 14 agree and 4 are
out". **Re-measured 2026-10-07 against 187 stored periods**, and the equation turned out
to be the smallest part of it:

    187 fundamental periods
     23 fail the equation          (12%)   -- our extraction contradicts the filing
    166 fail a composition check   (89%)   -- a stated subtotal vs the parts we hold
    117 fail profit articulation   (63%)   -- profit, which every ratio divides by

The equation is still the sharpest signal, because a published balance sheet balances by
construction:

| ticker | period | out by | share of assets |
|---|---|---|---|
| DFPH_US_EQ | 2020-12-31 | 219,756,050 | **+95.0%** |
| AMBQ_US_EQ | 2024-12-31 | 378,150,000 | **+362.6%** |
| ACM_US_EQ | 2025-09-30 | 203,600,000 | +1.7% |

ACM is out on **six consecutive years** by 0.9–1.7% of assets, which is a systematically
missing caption rather than a one-off.

**The composition failures are the bigger and more tractable population, and they are
exactly attributable.** `MSFT_US_EQ` passes the equation with a residual of 0 and still
fails four checks. Adding up its own 10-K balance sheet:

    current assets      20,935 + [55,908] + 80,876 + 1,397 + 48,594 = 207,710  = stated
    total assets        ... + 313,076 + 24,177 + [36,348] + 119,651 + 18,609 + 38,805 = 758,376
    current liabilities 42,416 + 9,227 + 14,945 + [2,534] + [72,965] + 26,738 = 168,825  = stated

`current_assets_composition` is out by **exactly 55,908** -- that bracketed line -- and
`assets_composition` by **exactly 92,256 = 55,908 + 36,348**. The residual is the sum of
the captions we do not extract, and nothing about it is approximate.

**The cause is that the field vocabulary is frozen at 46 names.** `metrics.STATED_METRICS`
feeds both `prompt_metric_names()` -- which generates the extraction prompt -- and the
`validate_extraction` gate, so the model can only ever answer questions we already knew
to ask. A caption outside those 46 is discarded with `"<name>: not a canonical metric
name"`. MSFT's 2026 10-K returned exactly 43 metrics with cited spans; there was nothing
else it was permitted to return.

**Next:** make the field set dynamic -- a registry seeded from the 46 and grown at
runtime -- so a filing's own captions can be asked for and remembered. The gap gives the
test: a candidate field is right when it closes a composition residual *exactly*, which
makes discovery verifiable rather than a judgement call. `short_term_investments` and the
non-current investment line are MSFT's first two.

Two things settled while measuring this, so they are not re-opened:

* **The outflow sign convention.** `capex` and `dividends_paid` are positive magnitudes;
  the Yahoo adapter had normalised `capex` alone and left `dividends_paid` negative in 16
  periods, which put the retained-earnings roll-forward out by exactly twice the dividend.
  Fixed in `metrics.OUTFLOW_METRICS` and migration `0014`. Both sources now agree.
* **Which source is authoritative.** With the sign settled, the XBRL row is the better
  base -- 53 keys against Yahoo's 47, and all nine asset components -- so the merge target
  is no longer ambiguous.

### Three pagers still reload the whole page

The recommendations table on `/dashboard` swaps in place (`partials/recommendations.html`,
`/partials/recommendations`, and `wirePartialPaging` in `static/app.js`). The other three
still navigate, so a page change puts the reader back at the head of the document.

Each needs the same two steps the dashboard needed, and no new mechanism:

1. `src/awltux/web/templates/decisions.html` lines 86-169, `jobs.html` lines 215-287 and
   `instrument.html` lines 613-627 (the news list) extracted into `partials/*.html`
   wrapped in `<div id="..." data-partial="/partials/...">`.
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

`tests/test_partial_paging.py` carries the contract for the dashboard; adding a tuple to
`REGIONS` extends it to each one as it lands.

### `xbrl_statements` measures coverage, so a wrong extraction is never revisited

The job's coverage probe (`scheduler/dependencies.py::_probe_xbrl_statements`) counts
filers with a CIK that have **no** `xbrl_companyfacts` row at all. The job is
`backfill=True`, so once that count reaches zero `skip_reason` skips it.

That is the right test for "is there anything to fetch", and the wrong one for "is what
we stored correct". A period extracted with the wrong tags counts as covered, so a filer
whose statements we read wrongly is never read again -- and the gap can only be closed by
a code change nobody knows is needed.

Measured 2026-10-06: **314** US filers, **30** with stored periods, **284** without. The
rotation is `ORDER BY max(as_of) NULLS FIRST, ticker` with `reports.per_run: 60`, so the
284 drain first and the 30 already-extracted are re-read as runs 5-6. That ordering is
the only reason the ledger fixes of the same day reached stored rows at all; had those 30
been extracted last they would have been re-read first and then never again.

**This is the lag both fixes on 2026-10-06 ran into**, and neither reaches a stored row on
its own: `analysis/ledger.py` reads stored metrics, so a filer extracted before the fix
keeps the old figures until the job rotates back over it. The EBIT bridge, the
interest-income lines and the four balance-sheet components all share it.

**Next:** the probe needs a second notion of outstanding -- a period written by an older
version of the mapper. Everything needed is derivable rather than needing new state: the
row carries `as_of`, and `metric_sources` records the tag each figure came from, so
"extracted before tag X existed" is answerable. A mapper version stamped on the row would
make it exact. Cheap, and it turns a silent staleness into a queue entry the job drains.

### Every page is only tested against seeded data

The `engine_label` failure and the empty-universe failure were both invisible to a
green suite because the tests never had rows. Templates and pages are now covered
with a populated database, but the *empty* states are mostly asserted only for a
200.

### The build's `--paths` list and the image's `COPY` list can drift

`--paths` is what stops the builder calling itself dirty, so it has to name
everything the runtime image copies. Adding a directory to the image without
adding it to `--paths` fails quietly in the wrong direction: the check simply
stops covering that path, and a modified file in it will not be reported. The
Dockerfile says so in a comment, which is not a test.

---

## Ingest Education Videos on Value Investment

A long-running background task: read six value-investing channels, extract the
concepts that could improve the rating app, and merge them into
`docs/research/FINDINGS.md` alongside the existing literature.
First find the Youtube terms and conditions on rate limiting when downloading transcripts. 
This IP address has been locked out previously, I'd like to avoid that in future.
Rate limiting should be an integral part of the solution. 

**Scope, measured rather than assumed** (enumerated 2026-10-06 with
`yt_enumerate.py --playlists` and `--limit 150`):

| Channel | playlists | videos listed |
|---|---|---|
| @Value-Investing | 287 | 301 |
| @ThePlainBagel | 11 | 160 |
| @BenFelixCSI | 7 | 159 |
| @AswathDamodaranonValuation | 26 | 150 (hit the cap) |
| @CstewartCFA | 9 | 306 |
| @PBoyle | 47 | 157 |
| **total** | **387** | **1,233** |

Selecting by title narrows that to **42 playlists and 181 videos** — about 220 items,
not 1,600. That is the difference between a task and an infinite one.

### Read the core tier first, and prefer playlists for method

The selector ranks by how much a title bears on the subject rather than including or
excluding it, because a flat list was the first attempt and it rated *"40 QUOTES BY
CHARLIE MUNGER"* level with *"Intrinsic Value Calculation Examples"*. Tiers, and what
they are for:

| Tier | Count (playlists / videos) | Use |
|---|---|---|
| **core** — intrinsic value, DCF, discount rates, cost of capital, margin of safety | 37 / 100 | the concepts this task exists to find |
| **supporting** — accounting quality, filings, fraud markers | 1 / 9 | corroboration; the app already holds a literature base on this |
| **context** — moats, capital allocation, buybacks, risk | 4 / 48 | worth reading, weaker bearing on the arithmetic |
| **example** — one company analysed | — / ~24 | *checking*, not teaching: a worked valuation to compare the app's own against |

Damodaran's `Valuation MBA` and `Valuation Undergraduate` courses (2016–2025) are
pure method and are the highest-value material in the set.

**Prefer playlists over raw video titles for method.** A curated course playlist is a
syllabus; a channel's individual uploads are mostly company commentary. Title
heuristics are a first pass and not a classifier — they still admit "Costco's
Explosive Free Cash Flow Growth", because nothing in that title distinguishes it from
a lecture on cash flow. Read the selection rather than trusting it.

### How to run it

The `youtube-transcripts` skill does the work; its scripts are at
`~/.agents/skills/youtube-transcripts/scripts/`.

```bash
python yt_enumerate.py --playlists --out lists.json --append "<channel>/playlists"
python yt_enumerate.py --out videos.json --limit 150 --append "<channel>"
python yt_select.py --in lists.json  --out want_lists.json
python yt_select.py --in videos.json --out want_videos.json
python yt_transcripts.py --in want_videos.json --out-dir transcripts --max-per-run 40
```

Expand the selected **playlists** into videos before fetching — the playlist inventory
names the courses, and the videos inside them are what carry the method.

**Ration it.** At the scripts' defaults — 5s spacing, serial — 220 items is well over
two hours of wall time and 220 caption requests. `--max-per-run 40` means six runs,
spread over days rather than chained. The scripts refuse to run again for 12 hours after
a block; that gate is the reason this is a background task rather than an afternoon's
work. **The 12 hours is this project's own conservative default, not YouTube's
number** — see the state note below.

### Edge cases that will bite

**A video can *suggest* a marker; it cannot be the evidence for one.** The
companion reports carry a tier system (A/B/C/D) and an appendix of verified primary
sources. A YouTube lecture is Tier D by construction — it is one person's summary,
frequently of a paper that has since been challenged. Anything FINDINGS records must
name the primary source and be graded on that, with the video recorded as *where the
idea was noticed*. Otherwise this becomes the "sophisticated way of losing money"
that `investment-markers.md` opens by warning against.

**Separate method from worked example.** "Valuation MBA Spring 2025" teaches a
technique; "MCD Stock Intrinsic Value" applies one to a ticker whose numbers are
stale within a year and which may not be in the universe. Concepts come from the
first. The second is worth keeping separately, as a way to check the app's own
arithmetic against a worked case someone else did.

**Expect promotional bias.** Value-investing YouTube runs on sponsorships and
affiliate links, and titles are optimised for clicks. A concept that arrives attached
to a product recommendation is suspect, and the transcript will usually say so
somewhere.

**Time-sensitivity cuts both ways.** Method ages slowly; examples, rates, tax rules
and named tickers age fast. A 2019 valuation lecture predates IFRS 16 and its
treatment of leases — record the video's date with every concept and do not carry a
pre-2019 accounting assumption into the app.

**No track record.** "I called the crash" is hindsight, not evidence, and a channel
that posts ten predictions a year will be right sometimes. Nothing here is a
performance claim.

**Transcripts are machine-recognised.** Unpunctuated, no speaker labels, and numbers
and ticker symbols are the least reliable part — "fifteen" and "50" are one
mishearing apart. A figure taken from a transcript must never enter FINDINGS as a
fact; find it in a filing or a paper or leave it out.

**Duplicates and re-uploads.** The same talk appears on several of these channels,
and channels re-upload. Dedupe on video id during enumeration and keep an eye on
near-identical titles across channels.

**Absent is not failed.** Some videos have no English captions at all. The manifest
records `failed` with a reason so "no transcript exists" stays distinct from "we were
blocked" — merging them turns a fetch failure into a silent gap in the research.

**Attribution.** Many videos are interviews; the view expressed may be the guest's,
not the channel's. Record who actually said it.

**Copyright.** Quote briefly and link. Do not reproduce transcripts, and treat
videos that read a book aloud (there is a Seth Klarman *Margin of Safety* reading in
this set) as a copyright surface: analyse the ideas, do not copy the text.

### What "done" looks like

Every concept gets a **disposition**, not just a paragraph:

| Disposition | Meaning |
|---|---|
| **implement** | worth building, with the primary source that justifies it and a tier |
| **already covered** | link to where the app or `investment-markers.md` already does it |
| **rejected** | with the reason, so it is not re-proposed |

A FINDINGS entry with no disposition is a wish list, which is what the marker note
and `TODO.md` section 6 both exist to prevent. Merge against
`docs/investment-markers.md` rather than duplicating it: where a video and the
literature describe the same marker, the literature entry is the record and the video
becomes a citation on it.

Where FINDINGS lives: `docs/research/FINDINGS.md`, next to the reports it grades
against, so its claims sit beside the evidence base rather than apart from it.

### Current state: the block has lifted, and the selection is already done

**Re-probed once, 2026-10-07 09:58:40 +01:00, and it succeeded** — one caption request
(`--max-per-run 1 --attempts 1`), `PRfXq-NlJqo` returned 775 words in 3.96s with no
`429` and no bot check. Enumeration always worked; the transcripts are what was blocked,
and they are not any more.

The block began with a run at 2026-10-06 16:52:10 +01:00 that retried a `429`, so the
next successful request was **17h 06m** later. That does *not* measure the block: the
local gate is 12 hours, so any block shorter than 12 hours would have produced the same
result. One probe cannot measure a duration and a second was not made, deliberately —
the post-mortem in the skill names repeated probing as what caused the ban.

**The 12-hour figure belongs to this project, not to YouTube.** `yt_common.py` has
`DEFAULT_COOLDOWN_HOURS = 12.0` with the comment *"The measured block outlived the
process that caused it by more than an hour"* — the measured fact is "> 1 hour", and 12
is a conservative local default the comment does not derive from anything.
`TODO.md` had been repeating it as though it were YouTube's behaviour.

What the sources actually say, for the next reader:

- **Official YouTube/Google terms state no duration.** [YouTube ToS](https://www.youtube.com/t/terms)
  forbids automated access (*"robots, botnets or scrapers"*) and circumventing limits;
  [YouTube API Services ToS](https://developers.google.com/youtube/terms/api-services-terms-of-service)
  §15 "Usage and Quotas" lets YouTube set quotas and forbids exceeding them. Neither
  gives a cooldown, a retry interval or a penalty period. That silence is the finding.
- **The maintainer's own reading** ([youtube-transcript-api#467](https://github.com/jdepoix/youtube-transcript-api/issues/467)):
  YouTube *"started to roll out much stricter rate limits on the endpoint needed to
  fetch the transcripts"*, hit after roughly **2–3 caption requests**, with rotating
  residential proxies as the only reliable workaround. The vendored README's "Working
  around IP bans" section gives no retry interval, and its `IpBlocked` text warns that
  cookie auth risks a *permanent* ban of the account used — so do not reach for
  credentials to get past a block.
- Community claims of "a few minutes", "an hour", "12–24 hours" and "permanent" are
  mutually contradictory and unsourced. Treat them as folklore.

**So the budget is 2–3 requests before a block, which is the number to design around.**
Proceed at the scripts' defaults (5s spacing, serial, `--max-per-run 40`, six runs over
days) and, if a run exits 3, wait the local 12 hours before the *next single* probe —
do not health-check with repeated probes. **The selection is already done and does not
need re-enumerating:** the playlists and videos are committed to
`docs/research/education-sources.json` (42 playlists, 181 videos), so re-walking six
channels would spend ~30 requests against an endpoint that blocks after 2–3. Start by
expanding the selected playlists into videos, then fetch. The probe left
`.tmp\probe-out\PRfXq-NlJqo.txt` fetched; move it into the run's transcript directory or
the next run spends one of its few requests re-fetching it.

### The channels

1. https://www.youtube.com/@Value-Investing
2. https://www.youtube.com/@ThePlainBagel
3. https://www.youtube.com/@BenFelixCSI
4. https://www.youtube.com/@AswathDamodaranonValuation
5. https://www.youtube.com/@CstewartCFA
6. https://www.youtube.com/@PBoyle

---

## Deliberately not doing

### Day trading / intraday horizon

Trading 212 exposes no quote or candle endpoint and the free feeds are ~15 minutes
delayed, so the maths is built on daily bars and `short_term` is a 5–20 trading
day swing. An intraday horizon is only worth adding behind a paid real-time feed.

### Making the free-tier data authoritative

`yfinance` is an unofficial scrape and will break; UK iXBRL coverage from Companies
House is roughly 60–75%. Both are labelled in the UI, and neither should be
treated as a source of record.

### Splitting the long functions the cooperative stop had to reach into

`python tools/refactor_report.py --diff` after that change, 2026-10-07:
`decision/service.py::decide_instrument` 185 lines, `news_analysis.py::
analyse_universe` 138, `ingest/news.py::persist_items` 112, `news_analysis.py::
appraise_item` 106, `decision/service.py::decide_universe` 87. All five were already
over the 70-line report before the change; the two this work *grew* materially --
`ingest_rss_news` (77 → 99 with the stop logic, then split back to 62 via
`_poll_instrument` / `_finish_instrument` / `_Feeds`) and `_execute_captured` (60 → 85
with the stopped branch, split back via `_invoke` / `_Outcome`) -- were paid off in the
same commit. The five above are a separate pass with its own reason, and the enforced
gate is complexity at 15, which they pass: the largest is 14. `persist_items` is the
one to do first, since it is the loop the stop checks most often and it carries the
per-article prefilter, dedup and classification inline.
