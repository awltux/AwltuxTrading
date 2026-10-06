# AwltuxTrading — working agreement

Process rules not derivable from the code. Each exists because something broke
without it.

## 1. A stage ends at a *deployed* commit

```bash
pytest -q && ruff check src tests
git add -A && git commit
docker compose build && docker compose up -d
```

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

## 5. Clean up

`git status` clean ≠ workspace clean: ignored scratch accumulates invisibly. When
pytest cannot write `.pytest_cache` it falls back to `pytest-cache-files-*` in the
CWD; 108 had piled up.

```bash
ls -d pytest-cache-files-* 2>/dev/null
```

Own scratch goes in `.tmp/` or `.tests-tmp/`. Anything a later step needs belongs in
the commit — if it is in `.tmp/`, it does not exist.
