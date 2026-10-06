# TODO

Open work on AwltuxTrading: bugs, gaps and decisions that are known and
deliberately deferred. This is the "found it, not fixing it now" list — not a
roadmap, and not a wish list.

**How this file is kept.** An item goes in the moment it is found, with the
evidence that found it, so nobody has to rediscover it. Items are *deleted* when
they are fixed rather than ticked off: git history is the record of what was
done, and a list of closed items stops being read. Anything already decided
against lives under **Deliberately not doing** with the reason, so it is not
re-litigated.

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

### The classifier's output budget was sized to the answer, not to the call

**Fixed and worth recording, because the diagnosis took three attempts.** A
headline classification was truncated on 6.7% of calls (165 of 2,474) and the log
said the response was incomplete JSON. It was not: the body was **empty**. The
`max_tokens` cap was 500, the *content* of a successful call is about 120 tokens,
and the rest of the recorded output was reasoning the API does not return in
`message.content` — so the budget was sized to the answer when it had to cover the
thinking.

`news.classify_max_tokens` is now 2,000 with the retry at `llm.max_output_tokens`.
Raising a `max_tokens` cap is close to free: it is a cap, not a reservation, so an
ordinary call generates exactly what it did before. Five calls had also burned
their retry at 1,500 and were lost entirely.

The lesson is in `Completion.json_object`, which now names this cause when it sees
an empty body, because "the JSON is incomplete" sent three people looking for a
truncation point that did not exist.

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

### Every decision so far has failed its own gate

`decision_run` holds 17 rows and `sum(gate_allowed)` is **0**: not one decision has
been actionable. The decisions themselves look ordinary — 12 came from DeepSeek,
5 from the deterministic engine — so this is either the gate working exactly as
intended on a universe with no accounts stored (`fundamentals` is 0 of 500
covered) or a threshold that nothing can clear. **Not investigated.**

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

### 13 instruments have no listing a search can find

**The wrong-symbol problem is fixed.** The 92 instruments that failed every price
run had a symbol *derived* from a Trading 212 ticker, and T212's tickers are
frequently former ones. `instrument_alias` was already the translation table -- it
had `confidence`, `method` (`isin | name | manual | ticker`), `is_manual` and a note
-- but its only producer was the derivation itself.

The `symbol_resolution` job now looks the company up by **ISIN**, which survives a
rename. Against the 92: **74 resolved**, 5 refused, 13 with no match. Examples:
`AHAC_US_EQ -> HUMA` (Humacyte), `BSN_US_EQ -> EVTL` (Vertical Aerospace),
`CNCTl_EQ -> SNWS.L` (Smiths News), `AURC_US_EQ -> BETR` (Better Home & Finance).

**Two rules were added after reading the first run rather than its count**, and both
were found in the output rather than by design:

- **5 cross-listings were refused.** An ISIN identifies the *company*, and a company
  can be listed in several places. `DOOO_US_EQ` came back as `DOO.TO` (Toronto) and
  `EVTCY_US_EQ` as `EVTA.F` (Frankfurt) -- the venue decides price, currency and
  liquidity, so a Toronto price on a Nasdaq row is a plausible number that is simply
  not the right one. Those five need a human to choose the listing, which is the
  correct outcome rather than a silent wrong one.
- **One placeholder was refused.** `BIOK_US_EQ` resolved to `DUMY0001134`, Yahoo's
  stand-in for a company with no live listing.

**The 13 are honest, not a bug.** They have no listing a search can find:
`AFAR_US_EQ` (a SPAC that appears to have completed), `BLVNl_EQ`, `HGENl_EQ`,
`HMSGl_EQ`, `INXl_EQ`, `NGHTl_EQ`, `PODPl_EQ`, `PPCl_EQ`, `SAL_US_EQ`, `STAF_US_EQ`
and the three others in the run detail. Most are suspended or delisted UK small-caps.
Checked against the live endpoint: `AFAR_US_EQ` and `BLVNl_EQ` return **zero**
candidates by ISIN *and* by name. No rule can find a listing that does not exist.

**The 5 cross-listings were a bug, and are fixed.** The venue penalty refused the
foreign listing correctly, and then the job stopped: it fell back to a name search
only when the ISIN search returned *nothing*, and an ISIN search for a company listed
in several places returns the foreign ones rather than nothing. BRP's
`CA05577W2004` comes back as `DOO.TO` and `CA05577W2004.SG`; the Nasdaq `DOO` is
never in that list. The right listing sat one name search away, unasked. The
fallback now runs whenever the ISIN match is not good enough to apply, and prefers a
usable name match to a refused ISIN one. Verified live: `DOO` at 0.907, exchange
agrees, applied -- while `AFAR_US_EQ` and `BLVNl_EQ` still resolve to nothing, so the
rule does not manufacture matches.

**Known gap: nothing shows these to a human, and they are retried for ever.** An
earlier version of this note claimed the failures were "visible as needing review
rather than silently retried". Neither is true. `stuck` is defined purely as "in the
universe with no stored bar", so all 13 are looked up again every run, for ever,
whatever their alias says -- 26 requests a day that cannot change the answer. And no
page lists aliases needing review: the note and the `is_manual` flag exist and are
honoured, but the only place either surfaces is the instrument page, one ticker at a
time. A reviewer has no list to work from.

**Next, if it matters:** the same lookup should be applied to `sec_cik` and
`ch_company_number`, which are resolved by name matching today and have the same
weakness. And the 13 need either a retry backoff -- stop re-asking a question whose
answer cannot change -- or a review queue where a human can set the symbol by hand.

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

### Finish building the live data

The deployment has the reference data and the prices — 500 instruments in
universe over 17,553 bars, and 3,555 stored news items — but no decisions yet
(`decision_run` 0), so the Recommendations table has nothing to rank.

An earlier version of this item claimed the universe, prices and news were all
empty. That was read from `data/awltux.db` on the host, which the container does
not use; it mounts the named volume `awltux-data` at `/data`. The lesson is the
one this file keeps recording: check which artifact the claim is about.

**Next:** let `price_eod` and `fundamentals` rotate through the universe, then
`news_analysis` (new, and so far unrun on real data), `sentiment`, `valuation`
and `decision`. Expect `price_eod` to take a while and to be rate-limited.

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
