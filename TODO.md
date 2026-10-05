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

### The classifier's first attempt is truncated on about 5% of headlines

Measured from the container's `llm_call` records: 56 of 1037 `news_classification`
calls ended at exactly the 500-token limit. The retry at 1500 succeeds, so nothing
is lost — but 5% of headlines cost two calls instead of one.

What those responses actually contain is worth knowing: the message the model
returns is `Expecting value at char 0`, meaning the body was **empty**. The output
budget was spent before the answer began, so raising the first-attempt budget may
fix it entirely rather than merely widening the retry. `Completion.json_object`
now says this instead of claiming the JSON was incomplete.

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
