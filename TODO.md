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

## Bugs

None open. The last eight — `serve` not migrating, silent DeepSeek truncation, the
`universe_refresh` startup race, CLI/server write-lock contention, the unhelpful
blank dashboard, a stale container being indistinguishable from a code bug,
SQLite's write lock being held across model calls, and a rate-limit counter
failing the job it was counting — were fixed and are in the commit log.

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

### A manual Run now can execute alongside the scheduled run of the same job

`SchedulerService.run_now` calls `execute_job(spec)` **directly** rather than
going through APScheduler, so it bypasses `max_instances=1` entirely. A manual run
of a job that is already running therefore executes concurrently with it.

The evidence is in the live `ingest_run` history: two `news_rss` runs overlapped
and the second died with `UNIQUE constraint failed: news_item.url_hash`. That
specific failure is now benign — the insert is wrapped in a savepoint and a stored
story counts as a duplicate (`tests/test_write_lock.py`) — but the general
condition is not fixed, and it is not only about news. Any two runs of one job can
interleave, and jobs that are not idempotent would corrupt rather than duplicate.

**Decide:** should `run_now` refuse with a clear "already running" rather than
returning zeros, or should it queue behind the scheduled run? Whatever is chosen,
the refusal has to be visible to the CLI and the Run now button, both of which
currently treat a `None` result as "nothing to do".

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

1. **Filing events** — auditor change, restatement, going-concern, accounting-policy
   change. The extraction fields and prompt are in place, but `extract_filing`
   (`llm/extractors.py:267`) is **not called from anywhere**, so none of it runs.
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

### A headline classification occasionally needs thousands of output tokens

The budget is now 2,000 with an 8,000 retry, and one call in the live log produced
**6,529 output tokens to classify one headline**. Raising the cap made these
graceful — but 6.5k tokens of deliberation to emit a 150-character JSON object is not
explainable by the task, and it is the same hidden reasoning that made the original
500-token budget look adequate.

**Re-measured 2026-10-06 17:06–17:55, during `news_rss` run #220.** The per-job
progress log is what made this visible at all: the five warnings were spread across a
45-minute run and previously sat in the container log among every other job's output.

- **1,402** `news_classification` calls in two hours, **344,124** output and **780,658**
  input tokens.
- **5** of them spent the whole 2,000-token budget and returned *no content at all* —
  10,000 output tokens, about **3%** of the window's output, for five headlines.
- **0** calls in the window exceeded 2,000 output tokens. So the "8,000 retry" does not
  show up as a large call; the retry produces a short answer, which means the *first*
  attempt is pure waste every time rather than a rare fallback.

The token share is small, which is why this looked minor. The wall-clock share is not:
the warnings land at 17:17:21, 17:21:47, 17:23:11, 17:29:18 and 17:31:37 — so single
headlines consumed **one to six minutes each** while the run classified the rest at
roughly 1–2 seconds per call (1,402 calls over 45 minutes). Five inputs account for a
disproportionate slice of a 45-minute run.

**Worth understanding before trusting the cost model:** either the prompt invites
much more deliberation than the schema requires, or the model loops on some inputs
(duplicates, very short summaries, non-English headlines). `llm_call` records
`input_tokens` and `output_tokens` for every call, so the inputs that trigger it can
be found rather than guessed at.

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

### The Fal embeddings route is refused by OpenRouter, not by us

**Not a code problem, and it has been investigated to the end.** Recorded so nobody
repeats the work, because the obvious diagnostics all point the wrong way.

The request is correct. Fal's own `llms.txt` documents exactly what we send —
`POST https://fal.run/openrouter/router/openai/v1/embeddings` with
`Authorization: Key $FAL_KEY` — and its OpenAPI schema declares
`apiKeyAuth: {type: apiKey, in: header, name: Authorization}`.

What the endpoint answers:

    401  "You do not have access to the organization tied to the API key."

Five findings that together rule out everything on this side:

1. **Fal accepts the key.** A deliberately bogus key gets a *different* error —
   "Cannot access application \"openrouter/router\". Authentication is required" —
   so Fal refuses the fake one and forwards ours. The refusal happens behind Fal.
2. **Two different keys fail identically**, one in each of Fal's formats
   (`fal_...`, and the older `<uuid>:<32 hex>` at 69 characters).
3. **Four model names fail identically**, including `text-embedding-3-large`
   *without* the `openai/` prefix, which does not exist on OpenRouter. A nonexistent
   model would give a model error if the request reached model selection, so it is
   refused earlier than that.
4. **There is no native Fal embeddings endpoint to switch to.** `fal.ai/llms.txt`
   lists no embeddings category; `fal-ai/any-llm` is the only language entry.
5. **The queue host looks like it works and does not.** `queue.fal.run` — which the
   OpenAPI `servers` field names — accepts the POST and reports `IN_QUEUE`, then
   `COMPLETED`, and only then returns the same 401 in the result body. A diagnostic
   that stops at "the submission was accepted" would conclude the opposite of the
   truth. `fal.run` is right for a synchronous OpenAI-compatible client and fails
   honestly; the queue hides the failure until execution.

**So it needs an account change**, which cannot be made from here: either enable the
OpenRouter route (or its credit) on the Fal account, or check the key was created
with the intended account selected — Fal's authentication docs warn that keys are
tied to the *account*, and that a team must be chosen in the dashboard *before* a key
is created.

**If it is never enabled**, the fallback is already in place and needs no code: the
`news.embeddings.base_url` setting accepts any OpenAI-compatible endpoint, so
OpenAI, Jina, Voyage or a local Ollama all work as-is. The banner reports
"not grouped by event" rather than implying stories were grouped.

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

`news_item.event_type` was always computed by the classifier and thrown away, so
rows written before migration `0004` are `NULL`. Primary-source routing falls back
to nothing for them. Re-classifying the last 30 days would fix it; nothing does so
automatically.

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

### The longest jobs outlast any deploy window, so no upgrade is ever quiet

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

The consequence is the same for both and it is not that the jobs are slow: **`awltux
quiet` can never report *idle* while either is running.** The step introduced for
exactly this purpose returns "waiting for decision" or "waiting for news_analysis",
and the operator chooses between holding a deploy for half an hour and accepting the
interruption quiet exists to prevent. The 60-second `stop_grace_period` and the
20-second drain budget are two orders of magnitude short of either job.

What catch-up changed: an interrupted run is no longer *lost work*, because an
unsuccessful run does not count and the job is repeated at the next start. What it
costs is the provider and model budget of doing the work twice, which for these two is
the expensive part.

**Next:** two changes, in order of how much they help.

1. **Make a run respect the drain budget.** A job should be able to see that the
   process is shutting down and stop at a batch boundary, rather than being killed
   mid-call. That converts a 39-minute interrupt into a clean partial run, and it
   helps every long job at once instead of one.
2. **Then bound `decision`** with a per-run limit and a least-recently-decided
   rotation, the shape `fundamentals` already uses. At 4.1/min, 500 instruments
   cannot complete inside one daily interval, so the daily cadence is not honest
   either.

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

### The universe news poll is the longest run and reports no progress

`ingest_rss_news` (`ingest/news.py:346`) loops over every instrument in the universe
with no `progress.note`, so the progress panel for it contains only what the logger
happens to emit. Observed 2026-10-06 during `news_rss` run #220: **55 minutes in,
~1,750 classification calls at a steady 30 per minute**, and the panel showed five
truncated-classification warnings and nothing else. The run looked stalled; it was
working normally the whole time.

Every comparable loop already reports its position — the decision sweep, news
appraisal, XBRL statements, fundamentals, price batches and symbol resolution all got
a note. This is the longest of them and the only one that does not.

**Next:** a `progress.note(f"{position} of {len(instruments)}: {instrument.t212_ticker}")`
on the loop, the shape the other seven use. It cannot be verified without a live run
of an hour or more, so it is worth doing alongside whatever bounds this job.

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

### The accounting equation does not hold for several stored periods

Found by the trial balance on the accounts page (`analysis/ledger.py`) the first time it
was run over the live data, on 2026-10-06. Of the 22 instruments with a computable
equation, **14 agree and 4 are out**; the rest cannot be attempted because the filing
does not state one of the three totals.

The equation is a fact about the filing -- a published balance sheet balances by
construction -- so a residual here is **our extraction, not the company**. Measured:

| ticker | period | out by | share of assets |
|---|---|---|---|
| DFPH_US_EQ | 2020-12-31 | 219,756,050 | **+95.0%** |
| AMBQ_US_EQ | 2024-12-31 | 378,150,000 | **+362.6%** |
| AMWL_US_EQ | 2024-12-31 | 11,472,000 | +2.6% |
| ACM_US_EQ | 2020-09-30 | 120,986,000 | +0.9% |
| AREC_US_EQ | 2024-12-31 | -1,561,666 | -0.8% |

DFPH and AMBQ are gross: DFPH reports 231m of assets against 11.6m of liabilities and
equity, and AMBQ reports -292m of equity against 104m of assets. Both look like a
figure taken from the wrong XBRL concept or the wrong period rather than a rounding
difference. ACM, AMWL and AREC are under 3% and are more likely a missing component
(AMWL's intangibles are 101m of 436m of assets, so a concept landing in the wrong year
would explain it).

**Next:** the four gross cases are worth tracing to the `xbrl_companyfacts` tag that
produced them, because a wrong `total_equity` is not only a broken equation -- `roe`,
`debt_to_equity` and the Altman Z'' input all divide by it. The check is the tool for
finding them; this is the list to work through.

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
spread over days rather than chained. The scripts enforce a 12-hour cooldown after a
block and refuse to run again before it expires; that gate is the reason this is a
background task rather than an afternoon's work.

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

### Current state: blocked, and the selection is already done

The IP is locked out of YouTube's caption endpoint by an earlier run that retried a
`429`. Enumeration still works — channels, playlists and titles all read fine — so
the selection is complete and only the transcripts are outstanding.

**Tomorrow's run does not need to re-enumerate.** The selected playlists and videos
are committed to `docs/research/education-sources.json` (42 playlists, 181 videos),
so the expensive part already survives. Start by expanding the selected playlists
into videos, then fetch. Re-walking six channels to rebuild a list that is already on
disk spends ~30 requests against an endpoint that has just banned this address.

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
