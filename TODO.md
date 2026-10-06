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

**Partly done.** The data prerequisite is closed and the first two markers are in:
`awltux/metrics.py` is now the single vocabulary (the extractor gate, the provider
mapping and the extraction prompt were three lists that had drifted — the prompt
omitted three names the gate accepted), and `analysis/accounting.py` computes the
accrual ratio and multi-year cash conversion with their inputs attached.

Still to build, in the order the note argues for:

1. Piotroski's nine tests, displayed as nine named checks rather than a score;
2. Altman Z'' inputs and a 5-variable Beneish M, as within-sector **rankings with
   their inputs shown** — never as a verdict, and never colour-coded;
3. receivables and inventory drift relative to revenue;
4. filing events: auditor change, restatement, going-concern, accounting-policy
   change — the extraction fields and prompt are in place, but `extract_filing`
   is **not called from anywhere**, so none of it runs;
5. ROIC against an explicitly stated WACC — the economic question the system
   currently cannot answer;
6. goodwill/intangibles intensity and a serial-acquirer flag;
7. Loughran-McDonald `litigious` and `uncertainty` counts on filing text.

Two cautions the note raises that belong with the implementation:

- **Do not port US-calibrated scores to UK accounts unmodified.** Beneish and
  Altman were fitted to US GAAP data; FRS 102 and IFRS differ on leases,
  development-cost capitalisation and goodwill. Recalibration or a stated caveat is
  required, not optional.
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
succeed, so nothing is lost — but 6.5k tokens of deliberation to emit a
150-character JSON object is not explainable by the task, and it is the same hidden
reasoning that made the original 500-token budget look adequate.

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

### `decision` has no batch limit, so no upgrade can ever be quiet

Measured on the live container: run #127 started 12:37:47, wrote **52 decisions in
12.8 minutes** — 4.1 per minute against a universe of 500, so roughly **110 minutes
remaining**. The container's stop grace period is 60 seconds.

Every other expensive job here is bounded, and for the same reason: `fundamentals`
rotates `fundamentals_rotation_per_day`, `symbol_resolution` takes
`symbol_resolution_per_run`, shareholder reports take `reports.per_run`,
`refresh_prices_eod` chunks at 40. `decision` sweeps the whole universe in one call.

The consequence is not that the job is slow — it is that `awltux quiet` cannot ever
report *idle* for it. The quiet step introduced for exactly this purpose returns
"waiting for decision", and the operator is left with two bad options: hold the
deploy for two hours, or accept the interruption the quiet was meant to prevent.
This item was found by running quiet, which is the tool doing its job.

**Next:** give the job a per-run limit and a least-recently-decided rotation, the
same shape as `fundamentals`, so a run is bounded by design rather than by the
universe happening to be small. A bounded run also makes the daily cadence honest:
at 4.1/min, 500 instruments cannot complete inside one interval.

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

## Deliberately not doing

### Day trading / intraday horizon

Trading 212 exposes no quote or candle endpoint and the free feeds are ~15 minutes
delayed, so the maths is built on daily bars and `short_term` is a 5–20 trading
day swing. An intraday horizon is only worth adding behind a paid real-time feed.

### Making the free-tier data authoritative

`yfinance` is an unofficial scrape and will break; UK iXBRL coverage from Companies
House is roughly 60–75%. Both are labelled in the UI, and neither should be
treated as a source of record.
