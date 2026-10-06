# AwltuxTrading — working agreement

Process rules not derivable from the code. Each exists because something broke
without it.

## 1. A stage ends at a *deployed* commit

```bash
pytest -q && ruff check src tests
# refactor pass over your own diff -- step 5, then prove it changed nothing:
pytest -q && ruff check src tests
# queue what you found and did not fix; delete what you fixed -- step 6:
git add -A && git commit
docker compose exec awltux awltux quiet    # waits until nothing is running
docker compose build && docker compose up -d
```

**Quiet before you rebuild, and let it wait.** `up -d` sends SIGTERM and the
lifespan drains, but that drain is *bounded* (it must be — the container is going
regardless), so a long job is killed mid-batch and its run closes as *interrupted*
next boot. `awltux quiet` pauses scheduling and waits, with **no timeout by default**.
Do not pass one: a deadline shorter than the job you are waiting for is not a safety
valve, it is the failure on a timer. `news_analysis` is bounded at 40 model calls and
still runs 14–39 minutes; `decision` runs about two hours.

Exit 3 means you passed `--timeout` and it expired. **That is not permission to
rebuild** — it is the tool telling you a job is still writing. Re-run without the
timeout and wait, or accept in writing that the run will be interrupted.
`awltux unquiet` undoes the pause if the upgrade is called off.

Green tests are not a deployment. Verify it landed:

```bash
git rev-parse --short HEAD
curl -fsS "http://127.0.0.1:${AWLTUX_PORT:-8080}/info" | grep -i "running commit"
```

The hash must match and the page must **not** say *has uncommitted changes*.
Otherwise it did not deploy — do not report it as deployed.

The image bakes provenance (`awltux.buildinfo`) because the runtime image has no
`.git`. The dirty-tree check covers only the copied paths — `src`, `pyproject.toml`,
`README.md`, `config`, `alembic.ini` — so an uncommitted change to those makes the
Info page name the *previous* commit.

`.gitattributes` (`text=auto`) and the Dockerfile `COPY` of it are load-bearing: the
check runs `git status` **inside** the container, which has no Windows
`core.autocrlf`, so without it every CRLF file reads as modified and every image is
branded dirty.

### Silent no-ops

`docker compose` parses `.env` strictly. One line that is not `KEY=VALUE` or a
comment fails **every** compose command — build included — while the old container
keeps serving, so nothing looks wrong:

```bash
docker compose config --quiet && echo "compose can read .env"
```

Read the build's exit status and output. "The command returned" is not "the image
was rebuilt".

### A restart picks up what it missed

The scheduler's triggers are `IntervalTrigger`s anchored to process start and its job
store is in memory, so **nothing about a schedule survives a restart**. That turns a
trigger that came due while the process was down from *late* into *never*: on the next
start the interval is recomputed from *now*, so a daily job is next due a day after the
machine came back. This machine is switched off every night, so the daily jobs simply
never ran.

`awltux/scheduler/catchup.py` answers it at `start()`: for every job whose last
**successful** run is more than one interval old, the job is scheduled *at its first
missed trigger* with `misfire_grace_time=None`, and APScheduler's `coalesce` collapses
the backlog into **one** run.

- **Collated, not replayed.** However many triggers were missed, one run. Replaying an
  hourly job ten times spends ten times the provider budget for the same end state.
- **Successful, not merely attempted.** A run that failed, or that a restart killed
  mid-write, produced nothing, so the job is still behind and is picked up next start.
  Anchoring on the last *attempt* would count an interrupted run as work done — and
  deploys interrupt runs routinely here.
- **The run table is the source**, not a persisted APScheduler job store. `ingest_run`
  already survives the process; a second record could disagree with the schedule the
  Operations page prints from the registry.
- **It does not bootstrap.** A job that has never succeeded has missed nothing, so it
  keeps the randomised first run, and `run_on_start` stays how a fresh container
  declares which jobs must populate their dependencies immediately.
- **Overdue is shown, not hidden.** A catch-up waits behind the single worker, so the
  Operations page marks a past due time as *overdue* rather than printing a timestamp
  the reader has to compare against a clock.

Measured when this was added: `news_rss` has an hourly interval and had gone 23.7 hours
without a run, and 8 of 21 registered jobs were past their interval at that instant.

### What bumps the version

`INTERFACE_BREAKING_COUNT.RELEASE_COUNT.BUILD_COUNT_FOR_RELEASE`, derived from a git
tag at build time — never typed. A release is a tag `v<breaking>.<release>`; the
build counts the commits since it (`awltux/version.py`). The tagged commit is build
`0`, so two images from the same release but different commits are different
versions.

| Component | Bump when |
|---|---|
| breaking | The HTTP API's shape, the schema in a way an old process could not tolerate, the config format, or the *meaning* of a decision-ledger field. Not an analysis change, however large. |
| release | Anything a user would notice and no interface broke: a marker, a page, a fix, a changed default. |
| build | Never — it is derived. |

```bash
git tag v0.2 && git push --tags     # a release is a tag, and nothing else
```

The version reaches the running process through `build_info.json`, which the image
build writes and which is also where the commit history lives — both are facts about
the build, so one cannot be refreshed without the other. A checkout with no tag
reports `untagged`, and a wheel with neither git nor the baked file falls back to
`pyproject.toml`; **the Info page prints which route was used**, because a fallback
that cannot be seen is a fallback nobody fixes. `tests/test_version.py` fails if a
version literal reappears anywhere under `src/`.

## 2. The database is never deleted, only migrated

`data/awltux.db` (the `awltux-data` volume) is the only copy of the universe,
prices, filings, news, decisions and their outcomes. It is **not a cache**; a fresh
database is not an upgrade.

- Migrations are **additive and inspection-guarded** — add a column only
  `if "x" not in _columns(table)` — so `upgrade head` is correct on fresh, old and
  already-migrated databases alike.
- `awltux migrate` copies the DB to `data/backups/` before rewriting anything, and
  skips the copy when nothing is pending.
- Destructive, and not part of any upgrade: deleting the file, `awltux seed-demo
  --reset`.
- `alembic check` must report *No new upgrade operations detected*.

## 3. Tests are offline

`conftest.py` forces every credential to `None`; a test that reaches a provider is a
bug. Capture the real response as a fixture instead — the provider output in
`tests/test_symbol_identity.py` is verbatim.

Stub **every** provider a job touches. Stubbing one and not the other reaches the
live host.

Never call `create_app()` to look at a page: the lifespan starts the scheduler, which
calls providers and writes. Render the template directly.

A registered job needs a `PROBES` entry (`scheduler/dependencies.py`) and a
`SUMMARISERS` entry (`scheduler/outcomes.py`). Tests enforce both.

## 4. Code standards

Six properties, each with a live example.

**Clean** — names describe the domain (`load_price_targets`, `APPLY_FLOOR`). An
unknown renders as `—`, never `0` (`web/templating.py`). An uncertain match is
refused and recorded, not guessed (`APPLY_FLOOR`, venue penalty, `ingest/identity.py`).
Nothing is inferred silently.

**Efficient** — never hold SQLite's write lock across a network call
(`release_write_lock`). Alternate network and DB phases per batch
(`refresh_prices_eod` chunks at 40). Bound bulk writes (`INSTRUMENT_FLUSH_EVERY`,
`RELEVANCE_BACKFILL_ROWS`). Every provider call goes through `BudgetGuard`. Re-doing
settled work every run is a bug even when it is correct.

**Modular** — decide in a pure function, fetch in an adapter: `ingest/identity.py`
takes candidates and returns a score, so its rules are testable with no network.
Providers parse and return; they never decide. One concern per module — SQL in
`web/queries.py`, formatting in `web/templating.py`, time in `timezones.py`.

**Secure** — this dashboard shows holdings and has no login. Secrets stay out of the
repo and the image; never print one (`redacted_dump`, `doctor`). Loopback-bound in
`docker-compose.yml`. `allow_live_orders` stays false and is checked at the point of
action, not only in config. Validate anything that becomes a path or a query
(`parse_zone`); bound parameters only. Fail closed, and say so.

**Testable** — assert the property, not the implementation. A regression test names
the failure it prevents and the measurement, in its docstring. Assertions must be
able to fail.

**Maintainable** — migrations additive (above). A comment explains the *why*: what the
obvious implementation was, what it did wrong, what was measured. Unresolved questions
go in `TODO.md` with their evidence. Correct a document the change invalidates, in the
same commit.

### Template traps

Both have caused silent bugs.

- `pct(v, digits, already_percent=True)` treats `v` as a percentage *number*. A
  fraction needs `pct(0.053, 2, false)`, or 5.3% renders as `+0.05%`.
- `tojson` emits raw `"` and escapes only `'`, so JSON in an HTML attribute must be
  **single-quoted** — otherwise the attribute ends at the first inner quote and
  `JSON.parse` throws.

## 5. Refactor before you commit

The last step of a stage, after the change works and before `git commit`. It is not
optional and it is not a rewrite: **it is a pass over your own diff.**

```bash
python tools/refactor_report.py --diff   # the worst thing your diff touched
ruff check src tests                     # the gate, C901
```

**Behaviour does not change.** Tests green before the pass, green after it. If the
pass changes what the code does, it is a feature — commit that on its own first, then
refactor on top. A move mixed with a change is unreviewable, and `git blame` cannot
tell them apart afterwards either.

**Scope is the diff.** The functions you changed, and the ones you had to read to
change them. The 55 functions over 70 lines are not this pass's business; touching
them is a separate commit with its own reason. Debt is created in the diff and paid
off in the diff.

What the pass looks for, in this codebase's idiom:

| Smell | The move |
|---|---|
| A function that grew a branch | Extract the *named* step — `_leverage_ratios`, not `_part_2` |
| The same query, date window or retry shape twice | One helper beside its siblings (`web/queries.py`, `providers/http.py`) |
| A rule decided inline in a route, job or provider | A pure function: candidates in, verdict out (`ingest/identity.py`) |
| A literal carrying a reason | A named constant beside what it constrains (`MIN_INTERVAL_SECONDS`, `APPLY_FLOOR`) |
| A second source of truth for a derivable value | Delete it and derive (`fmt_duration`, `outcome_for`) |
| Formatting in a template, SQL in a router, date maths outside `timezones.py` | Move it to the module that owns the concern |
| An `except Exception` that swallows the cause | Narrow it, or log the exception *and* the stated fallback (`scheduler/jobs.py`) |
| A branch reachable only in production | A test that fails without the fix; name the measurement in its docstring |

**Length is not the measure.** `decision/gate.py::evaluate` is 241 lines and is the
clearest form it has: an ordered list of checks where the order *is* the policy, and
the first failure binds. `analysis/news_scepticism.py::grade` is a flat table of
independent observations. Both are excused by name in `pyproject.toml`. A 40-line
function interleaving three concerns is worse than either — complexity, not line
count, is what makes a function hard to change, because every branch is a case the
reader must hold at once.

**Enforced, not remembered.** `pyproject.toml` selects `C90` at
`max-complexity = 15`, so a new function past that fails the build. Four are above it
and carry `# noqa: C901` with the reason above them:

```bash
python tools/refactor_report.py    # ends with the ledger and each reason
```

That ledger **only shrinks**. Adding an entry is a decision to be argued, not a
workaround — and the reason is the whole value of it: a bare `noqa` says *I gave up*,
a reason says which rule was weighed and why the plain form won, which is the part a
later reader cannot reconstruct. `fundamentals.py::derive_metrics` was the fifth and
was split into five named families rather than excused; that is the pass working.

Debt that cannot be paid in this commit goes in `TODO.md` with its evidence, never
in a lowered standard.

## 6. `TODO.md` is the queue, not a graveyard

Mid-task you will find something that is not your task: a bug two files away, a
missing case, a provider that lies, a decision that needs making later. Do not chase
it and do not lose it. Write it in `TODO.md` and carry on — a discovery you have not
measured yet does not belong in the diff you are halfway through.

**An entry is the evidence, not the title.** What you already know and would
otherwise have to rediscover: the measurement, the file and line, the command, the
run id, what you ruled out. *Payment endpoints are flaky* is not an entry; a status
code, an instant and the condition that produced it is. The next reader is a session
with none of your context, and the evidence is the part it cannot reconstruct — which
is also the only thing that stops the same investigation being run twice.

**Implementing an entry deletes it, in the same commit.** The file lists what is
still owed, so an item left behind after the fix costs the next reader the work of
disproving it. A ticked checkbox, a `**Fixed**` heading or struck-through text is the
same lie with extra steps: `git log -S` and `git blame` are the record of what was
done, and this file is only the queue. A queue that accumulates its closed items is
one nobody reads.

**Stale is the quieter failure.** An entry whose numbers were right when written and
are wrong now is worse than a missing one, because it is believed. Re-measure and
correct it, or delete it. `decision_run` was still described here as holding nothing
to rank for a stage after it held 81 decisions and every pipeline job had run.

```bash
grep -n '^### ' TODO.md          # everything still open
```

The sections are **Bugs**, **Correctness questions still open**, **Operations** and
**Deliberately not doing** — the last for a decision *against* acting, with its
reason, so it stops being re-proposed. `tests/test_repo_hygiene.py` fails on a closed
item left in place, so the rule is not merely remembered.

## 7. Clean up

`git status` clean ≠ workspace clean: ignored scratch accumulates invisibly. When
pytest cannot write `.pytest_cache` it falls back to `pytest-cache-files-*` in the
CWD; 108 had piled up.

```bash
ls -d pytest-cache-files-* 2>/dev/null
```

Own scratch goes in `.tmp/` or `.tests-tmp/`. Anything a later step needs belongs in
the commit — if it is in `.tmp/`, it does not exist.
