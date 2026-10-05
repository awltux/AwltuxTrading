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

### P1 — Recommendations page returns `'engine_label' is undefined`

Reported from a running instance:

```json
{"ok":false,"error":"UndefinedError","detail":"'engine_label' is undefined"}
```

`src/awltux/web/templating.py` registers `engine_label` in **both**
`env.filters` and `env.globals` (the global is the one that matters — it is called
as a two-argument function at `dashboard.html:220`, and filter syntax cannot reach
it). `tests/test_api.py::TestTemplatesRenderWithData` asserts exactly that and
passes. So the source is correct, and something about the *running process* is not.

**Why it was not caught:** the helper is only reached inside the row loop. With an
empty database the `{% else %}` branch renders and the call never happens — which
is how the original bug survived a green suite, and why the container check in
this session did not catch it either (that container had no decisions to show).

**Most likely cause:** the process under test predates the fix. Confirm before
changing anything.

**Discipline:** this is the second time a template error has been invisible to the
suite, so fix the *detection* as well as the symptom.

**Done when:** the failing instance's revision is identified from `/info`, the
error is reproduced against a seeded database through uvicorn (not `TestClient`),
and either the stale process is replaced or the real second code path is fixed.
Add a regression test that renders every page with rows **and** without.

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
