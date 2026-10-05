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

### P2 — `awltux serve` does not migrate, so a local run breaks on an older database

The container runs `python -m awltux.cli migrate && python -m awltux.cli serve`, but
`serve` on its own only calls `init_db`, which creates missing tables and never
alters existing ones. Running it against a database from a previous version
therefore fails at the first query with a raw
``no such column: news_item.event_type`` — an error that names the symptom and not
the cause, and one that the deployment path never sees.

**Done when:** `serve` either migrates on startup like the container does, or
refuses to start with a message saying the schema is behind and naming the
command that fixes it.

### P2 — A DeepSeek classification response was truncated and failed to parse

Observed on 2026-10-05 in the demo database's decision narrative:

```
deepseek: model did not return valid JSON: Unterminated string starting at: line 1 column 4146
```

The degradation is correct — the item was stored unclassified and the decision
fell back — but `classify_headline` asks for `max_tokens=500` while a verbose
`reasoning` field can overrun it, and a truncated response is thrown away whole.
Worth either raising the cap, or asking for less prose, or retrying once with the
`reasoning` field dropped.

### P1 — A stale container is indistinguishable from a code bug

**Diagnosed 2026-10-05, and it was never a code bug.** The recommendation page's
`'engine_label' is undefined` and the missing Info menu item had the same cause and
it was not in the source: the running container predated both fixes.

```
container awltux-trading  image 496a71dc5da1  created 12:30:12  up 2 hours
image     awltux-trading:0.1.0                built   13:59:55  (different ID)

GET /dashboard on the running container -> {"ok":false,"error":"UndefinedError",
                                            "detail":"'engine_label' is undefined"}
GET /info      on the running container -> 404

same image as a throwaway container, with demo rows seeded:
GET /dashboard -> 200, renders, Info link present
GET /info      -> 200
```

`docker build` retags an image. It does not touch a running container, and
`docker compose up -d` without `--build` reuses whatever image was already local —
so the sequence "build four times, report 'image rebuilt', never recreate the
container" leaves the user on old code while every check I ran passed, because
those checks ran against the *image*, not the *deployment*.

**Why it matters more than the two symptoms:** the failure mode is silent and it
cost two separate investigations, one of which I recorded as a suspected template
bug. Any future "that's fixed" claim is worthless if the process being looked at is
older than the fix.

**Done when:** the deploy step is explicit rather than implied. At minimum,
`docker compose up -d --build` becomes the documented way to deploy, and the
README says outright that building does not restart anything. Preferably the
running container's image ID is compared against the current one somewhere the
reader will see it — the **Info** page already reports its own commit, which is the
detection mechanism; it simply has to be *deployed* before it can report that it
was not deployed.

**And note the irony worth remembering:** the first thing the Info page would have
told us is that the deployment did not have the Info page.

### P1 — `universe_refresh` races `t212_instruments` at startup and selects nothing

Both jobs are `run_on_start=True` (`src/awltux/scheduler/registry.py`) and there
is no ordering between them, so on a fresh database they run concurrently:
`t212_instruments` fetches from the network and only commits at the end, while
`universe_refresh` reads the instrument table before that commit lands. It sees
zero rows, selects zero instruments, and writes `in_universe = 0` for nothing —
leaving every instrument outside the analysed universe.

**Evidence** (the live database, 2026-10-05):

```
ingest_run:  t212_instruments  11:54:05.075  seen 18483  written 18483
             universe_refresh   11:54:05.077  seen 0      written 0     <- 2ms later
instrument:  18483 rows, 17434 with a Yahoo symbol, 0 with in_universe = 1
```

Both timestamps are the *start* of each job. Nothing re-runs `universe_refresh`
until its next interval, so the empty universe persists and the dashboard has
nothing to show.

**Why it matters:** the app looks broken for no visible reason, and the failure
is silent — `eligible = 0` produces a run record identical to a legitimate "no
instruments qualified" outcome.

**Done when:** the startup chain is ordered (`t212_instruments` → `universe_refresh`,
or the refresh waits for a non-empty instrument table), and a zero-eligible run
records a `note` saying which filter emptied it, the way the other empty jobs now
do.

**Recovery in the meantime:** with the server stopped, `python -m awltux.cli job
universe_refresh` re-selects from the instruments already stored. Prices,
valuations and decisions still need their own jobs after that.

### P2 — CLI job runs contend with the running server for SQLite's write lock

`awltux job <id>` opens its own connection while the server's scheduler is
writing, and the loser gets `database is locked` (observed with `price_eod`).
`busy_timeout` covers short waits; a job that holds the lock across rate-limit
sleeps is longer than any sane timeout.

**Done when:** the CLI asks the running server to execute the job instead of
opening its own connection — `POST /api/jobs/{job_id}/run` already exists
(`src/awltux/web/routes/api.py`) and uses the identical code path — falling back
to a direct run only when nothing is listening.

### P2 — the dashboard's empty state does not name `universe_refresh`

`src/awltux/web/templates/dashboard.html` tells the reader to run
`t212_instruments` then `price_eod`, then `valuation` and `decision`. The step it
omits is exactly the one that silently emptied the universe above. Add it, and
say that an empty universe is why the table is blank rather than leaving the
reader to guess.

---

## Correctness questions still open

### Build the accounting-quality markers from `docs/investment-markers.md`

The research note ranks the markers worth having. The first dependency is data,
not code: `CANONICAL_METRICS` in `llm/extractors.py` is a closed set, so any figure
the extractor is not asked for does not exist downstream. Most of the accounting
markers need: receivables, inventory, payables, depreciation and amortisation,
stock-based compensation, goodwill, intangibles, short-term debt, EBIT, pretax
income, tax expense, R&D and lease liabilities.

Then, in the order the note argues for:

1. multi-year cash conversion and accrual ratio (the strongest diagnostic, two
   figures, and the current version is a single-period check where the evidence
   calls for a trend);
2. Piotroski's nine tests, displayed as nine named checks rather than a score;
3. Altman Z'' and a 5-variable Beneish M, as within-sector **rankings with their
   inputs shown** — never as a verdict, and never colour-coded;
4. receivables and inventory drift relative to revenue;
5. filing events: auditor change, restatement, going-concern, accounting-policy
   change (rare, discrete, unambiguous, and cheap once the text is read);
6. ROIC against an explicitly stated WACC — the economic question the system
   currently cannot answer;
7. goodwill/intangibles intensity and a serial-acquirer flag;
8. Loughran-McDonald `litigious` and `uncertainty` counts on filing text — the
   finance-specific lexicon, not a general-purpose one.

Two cautions the note raises that belong with the implementation:

- **Do not port US-calibrated scores to UK accounts unmodified.** Beneish and
  Altman were fitted to US GAAP data; FRS 102 and IFRS differ on leases,
  development-cost capitalisation and goodwill. Recalibration or a stated caveat is
  required, not optional.
- **Every score must show its inputs.** The failure mode of these tools is a number
  that reads as a verdict; the note's recommendation is that a flag means "read
  this" and never "this is fraud".

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

### Rebuild the live data

The stored universe currently has no prices, valuations, decisions or news
(`price_bar` 0, `decision_run` 0, `news_item` 0). After the P1 fix above, the
whole chain needs running: `universe_refresh` → `price_eod` → `fundamentals` /
`news_rss` → `sentiment` → `valuation` → `decision`. Expect `price_eod` to take a
while and to be rate-limited.

### `awltux doctor` and `awltux seed-demo` are missing from the README command list

`doctor` is documented under Configuration, but neither command appears in the
command list in **Development**, which is where someone looks for "what can I run".

---

## Test gaps

### The container's Info page is never tested end to end

`tests/test_buildinfo.py` and `TestInfoPage` cover the reader and the page against
a fixture. The Dockerfile asserts `build_info.json` is installed, but nothing
checks that a *built image* actually names its commit — the path that has no
`.git` and cannot be tested on the host. A build-time smoke check (`docker run …
curl /info | grep <sha>`) would close it.

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
