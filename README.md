# AwltuxTrading

A self-hosted background service that continuously assesses whether the shares
tradeable on **Trading 212** are under- or over-valued, tracks market sentiment
towards each stock and sector, and shows the result on a live dashboard with a
news flash ticker.

Every decision it produces is **explained and reproducible**: the inputs, the
model that answered, its probabilities, and the rule that permitted (or blocked)
the call are all written to an append-only ledger.

> **Advisory only.** AwltuxTrading does not place live orders. It is not
> financial advice. See [Safety](#safety).

---

## How it works

Three things are deliberately kept apart, because they are good at different
things and conflating them is how a plausible-but-wrong number reaches a user:

```
INGEST      Trading 212 · Yahoo Finance · SEC EDGAR · Companies House · RSS/Finnhub/Marketaux/GDELT
   │
ANALYSE     deterministic Python — every number in the system is produced here
   │        DCF · EPV · residual income · peer multiples · DDM · Graham
   │
COMPRESS    DeepSeek reads filings and headlines, returns cited structured facts
   │
DECIDE      JEV answers typed questions (falling back to DeepSeek, then to rules)
   │
GATE        deterministic risk rules decide whether the call is actionable
   │
LEDGER      immutable record: state hash, questions, answers, model id, gate verdict
```

**The division of labour is enforced, not just intended.** DeepSeek never
supplies a number that reaches the valuation — it extracts figures *with a quoted
source span*, and anything uncited is discarded. JEV sets the verdict but never
computes. Code owns all arithmetic, thresholds and permissions.

### Why it works this way

| Constraint | Consequence |
|---|---|
| JEV caps `state` at ~32k tokens and cannot read a 200-page report | DeepSeek compresses filings into a compact, cited state first |
| Trading 212 has **no quote or candle endpoint** | Prices come from Yahoo Finance, with Stooq as fallback |
| Free tiers are licensed for personal, non-commercial use | Local storage, source attribution, no redistribution |
| A language model's "probability" is not a calibrated frequency | Fallback decisions are labelled and held to a stricter confidence floor |

---

## Quick start

```bash
git clone <this repo> && cd AwltuxTrading
cp .env.example .env          # then fill in your keys (all optional to start)
docker compose up -d
open http://localhost:8080
```

The dashboard is bound to `127.0.0.1` only. It shows your holdings and has no
authentication, so it must not be exposed on a network.

### Updating a running deployment

```bash
docker compose exec awltux awltux quiet --timeout 1800   # wait for in-flight jobs
docker compose up -d --build                             # rebuild AND recreate
```

**Quiet it first.** Rebuilding sends the container SIGTERM, and on SIGTERM the app
stops scheduling and waits — but only briefly, because the container is going whether
the wait finishes or not. A job that outruns that window is killed part-way through
writing its batch; the run row is closed as *interrupted* on the next start, which is
honest but is still work lost and a database left mid-transaction. `awltux quiet`
asks *before* the rebuild instead: it pauses scheduling and waits for as long as it
takes. Exit code `3` means a job outran the timeout and it is **not** safe to rebuild
yet. `awltux unquiet` resumes, if you decide not to upgrade after all; the state is
also cleared by any restart.

**`docker build` on its own does not update a running container, and neither does
`docker compose up -d` without `--build`** — the latter reuses whatever image is
already tagged locally. Rebuilding four times and restarting nothing leaves the
dashboard on old code while every check against the *image* passes. That is not
hypothetical: it produced two separate bug investigations here, one of which was
recorded as a template error that had in fact been fixed a version earlier.

To tell what you are actually running, open **Info** in the navigation: it reports
the commit the *running process* was built from, and whether the tree was clean
when it was captured. If the page is not there, the deployment is older than the
page — which is itself the answer.

### It works with no API keys at all

With an empty `.env` the app still runs: it ingests whatever is available without
credentials (Yahoo prices, SEC filings, RSS headlines) and makes decisions using
the **deterministic offline engine**, clearly labelled as such. Add keys to
improve it:

| Key | Enables | Notes |
|---|---|---|
| `AWLTUX_T212_API_KEY` / `_SECRET` | The instrument universe, your holdings, paper trading | Required for universe selection |
| `AWLTUX_DEEPSEEK_API_KEY` | Filing extraction, report summaries, news classification, fallback decisions | Strongly recommended |
| `AWLTUX_TYPESAFE_API_KEY` | **JEV**, the calibrated decision engine | Gated early access |
| `AWLTUX_COMPANIES_HOUSE_API_KEY` | UK company filings and accounts | Free |
| `AWLTUX_FINNHUB_API_KEY` / `AWLTUX_MARKETAUX_API_KEY` | Real-time US news, sentiment-scored news | Free tiers |

`AWLTUX_SEC_USER_AGENT` must contain a **real contact address** — the SEC rejects
requests without one with an HTTP 403.

---

## The decision engines

The engines are interchangeable because they answer the same typed questions.
Which one answered is recorded on every decision and shown in the UI.

| Engine | Type | Probabilities | When it is used |
|---|---|---|---|
| **JEV** (`typesafe.ai`) | Calibrated decision model | Calibrated | Primary, when a key is set |
| **DeepSeek** | Language model emulating the same contract | Self-reported, **uncalibrated** | Fallback when JEV is unavailable |
| **Offline** | Deterministic threshold rules | None reported | No keys, replay, and as a control |

Confidence floors differ **per engine**, because three different quantities are
called "confidence" here and treating them as one number would either overstate
the rule engine or hobble it:

| Engine | Floor | Why |
|---|---|---|
| JEV | `0.70` | Calibrated probabilities — the ordinary bar applies |
| DeepSeek | `0.80` | Self-reported certainty, **not** calibrated — held to a stricter bar |
| Offline | `0.55` | Reports no probability at all; its number describes *evidence quality*, so it is judged on its own scale |

That last distinction is not pedantry. The rule engine's evidence score tops out
at 0.65, so judging it against the 0.80 fallback floor made the no-keys mode
silently incapable of ever suggesting anything — a failure that no test of the
gate alone would have caught, because a hand-built response always supplies a
confidence.

A fallback decision is never presented as though JEV produced it.

### The questions asked

Asked together in a single fan-out request ([TypeSafe's recommended pattern][fanout]),
because many atomic questions are cheaper and more inspectable than one broad one:

`valuation_verdict` · `margin_of_safety` · `business_quality` ·
`balance_sheet_risk` · `earnings_trend` · `news_materiality` ·
`sentiment_regime` · `going_concern` · `dilution_risk` ·
`accounting_red_flags` · **`long_term_action`** · **`short_term_action`** ·
**`short_term_setup`** · **`short_term_drawdown_risk`** · **`horizon_fit`**

The answers are blended into a composite score used to sort the dashboard.
The deterministic margin of safety carries the largest weight in the long-term
score, so the ranking is anchored to arithmetic rather than judgement. When an
action contradicts its own composite, the decision is **flagged as a conflict**
and shown — not silently averaged away.

[fanout]: https://docs.typesafe.ai/patterns/fan-out

---

## Two horizons, not one

The dashboard gives **two independent verdicts**, because they answer different
questions from different evidence and can legitimately disagree:

| | Long term | Short term |
|---|---|---|
| **Horizon** | 12–36 months | 5–20 trading days |
| **Driven by** | Valuation, business quality, balance sheet | Trend, momentum, volume, news direction |
| **Composite weights** | Margin of safety dominant (0.34) | Tactical setup dominant (0.35) |
| **Judged over** | 30 / 90 / 180 days | 5 / 10 / 20 days |
| **Requires** | A fresh valuation | A fresh price and a measured setup |

They are scored with **different weights** and gated with **different
requirements**, and that is the point. A single collapsed verdict would hide the
case a reader most wants to see:

- cheap for years but tactically broken — `long_term: BUY`, `short_term: AVOID`
- nothing for years but a clean setup now — `long_term: REDUCE`, `short_term: BUY`

The `horizon_fit` answer states plainly which horizon the evidence actually
supports (`long_term`, `short_term`, `both`, `neither`), independently of either
call. If the two used the same weights they would produce the same ranking and the
second would be decoration; tests assert they diverge in both directions.

### Short term is a swing, not day trading

**Day trading is deliberately out of scope**, and the app says so rather than
implying otherwise. There is no supported intraday path because the data cannot
carry one:

- Trading 212's public API has **no quote endpoint at all** — verified against the
  full OpenAPI bundle.
- The free price feed is **delayed ~15 minutes**. Trading intraday on a
  15-minute-stale price is worse than not trading.
- The maths is built on **daily bars**, which is the resolution the momentum and
  valuation models assume.

"Short term" therefore means a swing horizon of days to weeks on daily bars. A
true intraday engine needs a licensed real-time feed; the tactical layer is
structured so one could be added behind the same verdict contract.

## The risk gate

The gate is a separate layer from the decision, so a model cannot widen its own
mandate. It checks, in order, and **names the single binding rule** when it
refuses:

1. engine trust meets the configured minimum
2. price freshness — plus a fresh valuation **only on the long-term horizon**
3. confidence clears the floor for that engine
4. the chosen option carries enough probability mass
5. the action is actionable at all — `HOLD` and `AVOID` never execute
6. **a measured tactical setup, only on the short-term horizon**
7. liquidity is known and sufficient
8. portfolio limits: max positions, per-name and per-sector concentration

Two asymmetries are deliberate. A tactical call does **not** need a fresh
discounted cash flow — refusing it for that would refuse it for an irrelevant
reason — but it does need actual momentum evidence, because a tactical call
resting on nothing but an opinion is not a tactical call. And `HOLD`/`AVOID` are
recorded as decisions but never become trade suggestions.

---

## News is a claim, not a measurement

Financial news is written by organisations with interests, to be read by people in
a hurry. Most of it is honest and still not evidence. So a headline is never fed
straight into sentiment: it is **appraised** first, and the appraisal decides how
much weight it may carry.

**Who is speaking.** Every item is resolved to a publisher, and the publisher to a
curated assessment: what kind of document it is (the regulatory record, the company
speaking about itself, a wire, an outlet with its own reporting, an aggregator, a
press-release distributor, opinion), its track record for financial accuracy, and
its **independence** — freedom from a stake in the story. Bias and ownership are
recorded with the basis for each judgement, because a judgement with no stated
basis is indistinguishable from a prejudice. The table is dated; unknown publishers
are *unrated*, which is not the same as disreputable.

Self-interest does not push credibility one way. A company announcing good news
about itself is discounted hard; the same company announcing a profit warning is
not, because nobody says that against their own interest casually.

**How it is written.** A pattern scan detects the recognisable manipulation
techniques — appeal to fear, shock language, manufactured urgency, unnamed
authority, anonymous sourcing, absolute claims, loaded language, bandwagon
appeals, "analysts say" consensus, clickbait construction — and records the words
that triggered each one. This runs in code, not in a prompt, for a specific reason:
a model asked "is this manipulative?" is judging its own input, and a confidently
written article reads as confidently written. The scan cannot be talked out of it.
It also notes alarming claims that are hedged into unfalsifiability, percentages
with no base, and headlines more extreme than the text beneath them.

**How many sources.** "Multiple outlets are reporting it" is the most common
defence of a story and one of the weakest. A wire story appears on dozens of
domains. Carriers are counted separately from **origins**, near-identical
headlines collapse, and wire credits in the text are followed. Twelve domains
carrying one Reuters story is one source, and the UI says so.

**What it actually claims.** For stories worth the cost, the model restates each
claim without the article's framing, tags its type and attribution, and names
where the underlying fact would be *recorded* — the filing, the register, the
court docket, the statistical agency. Each claim must quote a verbatim span from
the item or it is dropped. A claim about results routes to the filings register; a
rumour has no primary source and is recorded as having none, rather than being
routed to the filings register because its subject happens to be results.

It also records what a complete account would have included and this did not, who
benefits if it is believed (incentives only — never an accusation), the base rate,
and **what would change the assessment**.

**The arithmetic is ours.** The credibility weight — source × corroboration ×
framing × claim support — is computed in code, with explicit ceilings: a
single-source story from an unrated publisher written in shock language cannot
exceed a low weight however favourable the rest looks, and severe framing caps an
article even from a wire. A model persuaded by the article never gets to vote on
how persuasive it was.

A weak story is not deleted or hidden. It keeps its score, loses most of its
influence, and carries the reasons why on the instrument page and in the flash
ticker. That is the difference between scepticism and censorship.

---

## Provability

Every decision stores: the canonical state and its SHA-256, the exact questions,
the raw engine response, the versioned model id, the composite, the gate verdict
with every check, and the evidence with source citations.

- **`/api/decisions/{id}/receipt`** returns the whole chain.
- **Replay** (`POST /api/decisions/{id}/replay`) re-runs the stored state through
  the recorded engine and reports whether it reproduces. Because the state is
  canonicalised (sorted keys, rounded floats, pruned nulls), the same inputs
  always hash identically — so "the same state" is a checkable claim.
- **Ledger verification** re-hashes stored states and reports any that no longer
  match, along with any decision missing a model id or gate verdict.
- **Calibration** tracks realised outcomes and reports hit rate by confidence
  bucket and by engine — on **different windows per horizon**: 30/90/180 days for
  long term, 5/10/20 days for short term. Scoring a tactical call over 90 days
  would measure noise rather than skill, so the two are never blended. A
  **calibration inversion** — higher confidence not outperforming lower — is
  surfaced prominently.
- Every figure in the UI carries its source and as-of time.

A confidence score is only meaningful if it is measured. That page is what
measures it.

### Times: stored UTC, shown in your zone

Every timestamp is **stored in UTC** — that is what `utcnow()` writes, and anything
used as a storage key or a cutoff is derived from UTC too, because `date.today()`
is today *here* and is wrong by a day for part of every day.

Everything is **displayed in the reader's zone**. A timestamp rendered in UTC is
correct and, for anyone not on UTC, misleading: "observed at 08:30" is a different
fact in London and in New York. The browser reports its own zone once, in the
`awltux_tz` cookie, and the server renders in it — including after the reader
travels or the clocks change. With JavaScript off, the configured `app.timezone`
is used.

Every rendered time carries its zone label (`14:32 BST`, `09:32 EDT`, `14:32 UTC`),
the footer states which zone the page is using, and no zone is ever guessed from an
IP address or a language header. The JSON API returns ISO-8601 with an explicit
offset, so a consumer can localise for itself.

The IANA database is a declared dependency (`tzdata`) rather than an assumption
about the host: a slim image without it would resolve no zones at all and quietly
show UTC to everyone. `awltux doctor` reports the zone database and the configured
zone so that failure is visible rather than silent.

---

## Dashboard

| Page | What it shows |
|---|---|
| **Recommendations** | Sortable table with **both verdicts side by side**, plus a `Suits` column showing which horizon the evidence actually supports. Filters follow a selected horizon. Views for *actionable only*, *my holdings*, and *suits long/short term* |
| **Instrument** | Decision receipt with **a card per horizon**: verdict, composite, confidence, gate checks, and the tactical setup/drawdown scores. Plus fair-value range, per-method breakdown, model answers with probabilities, narrative, filings, accounts, news |
| **Sectors** | Sector sentiment heatmap, drill-down to constituents |
| **Calibration** | Per-horizon tabs; realised hit rate and return by confidence and by engine; high-confidence misses |
| **Operations** | Job status and history, provider health, LLM spend, ledger verification; run any job by hand |
| **Info** | The commit this process is running, whether the tree was clean when it was captured, the database revision, and the last ten commits with their hashes |

The **API** link in the navigation opens the OpenAPI docs in a new tab rather
than navigating away from the dashboard.

The **news flash ticker** streams over Server-Sent Events, colour-coded by
materiality, tagged with affected tickers and sectors, linking to the source.

The API exposes both horizons explicitly (`long_term` / `short_term` objects per
item) rather than flattening them, so a consumer can see them disagree:

```bash
curl -s localhost:8080/api/recommendations?horizon=short_term | jq '.items[0]'
```

### Honest latency

"Realtime" here means *continuously updating*, not tick-by-tick — free-tier
sources cannot support that:

| Data | Latency |
|---|---|
| US filings (SEC EDGAR Atom) | under a minute |
| News headlines | 1–5 minutes |
| Prices | 15-minute delayed, or end-of-day |
| UK regulatory news | best-effort only — real-time RNS is a paid licence |

---

## Configuration

Secrets live in `.env`. Tunables live in `config/config.yaml`: universe size,
polling cadences, per-provider rate-limit budgets, valuation weights and
assumptions, **per-horizon composite weights and gate requirements**, LLM spend
ceiling, and the horizon labels and indicative holding periods shown in the UI.

Holding periods are configuration, not model output. A language model asked for a
holding period will invent a plausible number; a documented range you can edit is
honest and checkable.

```bash
docker compose exec awltux awltux settings   # effective config, secrets redacted
docker compose exec awltux awltux jobs       # the job registry
docker compose exec awltux awltux job price_eod   # run one job now
docker compose exec awltux awltux quiet      # pause and wait, before a rebuild
docker compose exec awltux awltux unquiet    # resume after an abandoned upgrade
```

### Running the app outside Docker

```bash
awltux migrate          # bring an existing database up to the current schema
awltux serve            # dashboard + scheduler (migrates on start, like the image)
awltux seed-demo        # five synthetic instruments, so the UI works with no keys
awltux doctor           # diagnose configuration and provider connectivity
awltux job <id>         # run one job now, on the server if one is running
```

`seed-demo` writes into the real database rather than mocking the UI: it seeds
instruments and then runs the actual valuation, sentiment and decision pipelines,
so what you see is real dashboard behaviour. Remove it with
`awltux seed-demo --reset --no-analysis` or a fresh database.

`job` asks a **running server** to execute the job and falls back to running it in
this process only when nothing is listening — two processes writing one SQLite file
contend for the write lock, and a job that sleeps inside a rate-limit guard holds
it longer than any sane timeout. Pass `--direct` to force a local run.

### The database is never recreated

`data/awltux.db` holds every fact this system has recorded: the instrument
universe, price history, filings, news, decisions and their scored outcomes. It is
not a cache, and it is never deleted or rebuilt to pick up a schema change. A
fresh database is not an upgrade — it discards the only copy of the history.

When a model changes, the schema moves forward in place:

```bash
alembic revision -m "what changed"   # write the migration
awltux migrate                       # apply it to the existing file
```

Two rules make that safe. Migrations are **additive and inspection-guarded** —
`0004` adds `news_item.event_type` only if the column is absent — so `upgrade head`
is correct for a fresh database, an old one, and one already migrated. And
`awltux migrate` **copies the database to `data/backups/` before it rewrites
anything**, skipping the copy when there is nothing pending so that no-op runs on
container start do not bury the backups that matter.

The only things that destroy stored data are deleting the file and
`awltux seed-demo --reset`, which removes the demo-marked rows and leaves provider
data alone. Neither is part of an upgrade.

### Diagnosing a rejected key

```bash
docker compose exec awltux awltux doctor            # full connectivity check
docker compose exec awltux awltux doctor --offline  # local state only, no network
```

`doctor` reports credentials by length and character class (never the value),
tests every provider against the free endpoints, and compares a failing call
against a **bogus-credential control**. That comparison is the point: if your key
and a deliberately wrong key produce the same response, the credential is the
problem; if they differ, the request is. It also confirms reachability with an
invalid path, which distinguishes an auth failure from an edge block.

It exits non-zero on failure, so it works as a preflight step.

**IP-restricted keys and dual-stack hosts.** If a provider key is restricted to an
IP allowlist, note that a machine with both IPv4 and IPv6 presents a *different*
source address per family. Allowlisting your IPv4 address achieves nothing if the
client then connects over IPv6 — and IPv6 privacy extensions rotate the address,
making an IPv6 allowlist fragile. Set `AWLTUX_FORCE_IPV4=true` to make the address
a provider sees predictable, and run `doctor` to see both addresses reported.

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate    # or activate per your shell
pip install -e ".[dev]"
pytest -q
ruff check .
python tools/refactor_report.py --diff           # what in your change is hardest to change
alembic upgrade head
```

`ruff` enforces a complexity ceiling (`C90`, 15 paths through a function), and
`tools/refactor_report.py` shows where the rest of the debt sits: the longest
functions, the most branchy, and the small ledger of functions excused from the
ceiling by name with the reason recorded against each. The convention is that the
ledger only shrinks — a `noqa` is a decision to be argued, not a way past the check.
See *Refactor before you commit* in `AGENTS.md`.

The test suite runs **entirely offline** — no network, no API keys — and covers
the currency normalisation, symbol resolution, valuation methods, sentiment,
canonical state hashing, every gate refusal path, engine answer parsing, the full
pipeline end to end, ledger integrity, replay, and the HTTP layer.

### Build provenance

An installed copy has no `.git` and no `git`, so the commit history the **Info**
page shows has to be recorded while both are still available. `docker build` does
that: it copies `.git` into the builder stage, runs

```bash
PYTHONPATH=src python -m awltux.buildinfo --write src/awltux/build_info.json \
    --paths src pyproject.toml README.md config alembic.ini
```

and fails the build if no commits were captured. `--paths` exists because the
builder holds only part of the tree: a whole-tree `git status` reports every
uncopied file as deleted, which would mark every image a dirty build. The list
must cover everything the image copies.

The file is gitignored, which is what keeps the *"was the tree clean?"* flag on
the page honest — commit first, then build, and the image can name the exact
revision it came from. A source checkout ignores the artifact and reads `git log`
live.

### Layout

```
src/awltux/
├─ providers/    one module per external API; the only place that uses the network
├─ ingest/       provider responses → provenance-tagged rows
├─ analysis/     deterministic maths; produces every number
├─ llm/          DeepSeek extraction and summarisation, with citations
├─ decision/     engines, questions, composite, gate, replay
├─ audit/        the immutable ledger and calibration
├─ scheduler/    job registry and the background runner
└─ web/          FastAPI routes, Jinja templates, SSE
```

Known bugs, open questions and deferred work live in [`TODO.md`](TODO.md), each
with the evidence that found it. The research behind the marker set — what the
accounting, quality, language and news literature actually supports, and what it
does not — is in [`docs/investment-markers.md`](docs/investment-markers.md).

---

## Safety

- **Advisory only.** No live order path exists. Order placement refuses to run
  unless `AWLTUX_T212_ENV=live` **and** `AWLTUX_ALLOW_LIVE_ORDERS=true` are both
  set deliberately.
- Paper trading against the Trading 212 **demo** environment is opt-in.
- The dashboard binds to loopback and is unauthenticated — do not expose it.
- Secrets are read from the environment, never logged, and scrubbed from log
  output by a redaction filter. Request bodies are stored with credentials
  removed.
- **Filings and headlines are untrusted input.** Prompts delimit them as data and
  instruct the model to ignore embedded instructions; a suspected injection is
  recorded on the extraction.

## Licensing and data sources

The free tiers this project relies on are licensed for **personal,
non-commercial use**, with no redistribution. The application therefore stores
data locally for private research and links back to publishers rather than
republishing content. If you intend to publish or monetise this, you need
licensed feeds.

| Source | Covers | Licence |
|---|---|---|
| Yahoo Finance (`yfinance`) | US + LSE prices, history, profiles | Unofficial scrape; personal use |
| SEC EDGAR | US filings and XBRL financials | Public domain |
| Companies House | UK company filings | Open Government Licence |
| Stooq | EOD prices, US + UK | Free, unofficial |
| Marketaux / Finnhub | News, sentiment | Free tier, personal use |
| GDELT | News tone | Open |
| Google News / Yahoo RSS | Headlines | Personal, non-commercial |

`yfinance` is a scrape of an undocumented API and **will break eventually**. It
sits behind a provider interface with a Stooq fallback, a disk cache, and a
staleness gate that suppresses decisions rather than acting on old prices.

### Known limitations

- **UK fundamentals are the weak spot.** Companies House exposes filings, not
  financial line items; the structured route is iXBRL, of which only ~60–75% of
  accounts are electronically filed. Some UK names will report
  `insufficient_data` rather than a fabricated valuation, which is the intended
  behaviour.
- **UK entity resolution is fuzzy.** LSE ticker → Companies House company number
  is name-matched and scored; anything below the confidence floor is excluded
  from decisions until confirmed.
- **Sector classification is derived**, not licensed (SEC SIC for US, provider
  industry fields for UK), so sector sentiment is approximate.
- **No free real-time UK RNS.** UK event detection is best-effort.

## Licence

MIT.
