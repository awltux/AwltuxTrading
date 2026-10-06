# Working agreement for this repository

**Read this before starting work.** It records process rules that are not visible
from the code, and every one of them exists because something went wrong without
it.

---

## 1. Commit and deploy at the end of every stage

**A stage is not finished when the tests pass. It is finished when it is committed
and the running container has been rebuilt from that commit.**

The rule:

```bash
pytest -q                       # must be green
ruff check src tests            # must be clean
git add -A && git commit        # the stage is only real once it is a commit
docker compose build            # rebuild from that commit
docker compose up -d            # replace the running container
# then VERIFY — see below. Do not skip this.
```

### Why this matters more than it looks

The container image bakes its build provenance at build time (`awltux.buildinfo`),
because the runtime image has no `.git` and no `git` binary. The **Info** page is
the only way to answer "which revision is actually running?", and it can only be
right if the image was built from a clean, committed tree.

Two ways it silently lies:

- **Built from a dirty tree.** The dirty-tree check covers `src`, `pyproject.toml`,
  `README.md`, `config` and `alembic.ini` — the things the image copies. Any
  uncommitted change to those makes the Info page print the *previous* commit plus
  **"has uncommitted changes"**, so the hash you read is not the code you are
  running.
- **Not rebuilt at all.** Then the container is simply older than the checkout, and
  nothing on the page says so.

`.gitattributes` is load-bearing here. The check runs `git status` **inside the
container**, where Git for Windows' system `core.autocrlf=true` does not exist, so
without a repository-level `text=auto` every CRLF working-tree file compares as
modified and *every* image is branded dirty. That is a false alarm that reads
exactly like a real one, which is why it must not be allowed back. The Dockerfile
`COPY`s it into the builder for this reason — if that line is ever dropped, the
warning comes back and nothing else will tell you.

Either way the symptom is the same: **the Info page hash does not match
`git rev-parse HEAD`.** That is a real defect, not cosmetic — every result the
dashboard shows becomes untraceable to the code that produced it.

### Verifying the deploy actually landed

```bash
git rev-parse --short HEAD                 # what you expect
curl -fsS "http://127.0.0.1:${AWLTUX_PORT:-8080}/info" | grep -i "running commit"
```

The two must agree, and the page must **not** say "has uncommitted changes". If
they disagree, the deploy did not happen — do not report the work as deployed.

### When the deploy silently does nothing

`docker compose` reads `.env` on every command and is strict about it: a single line
that is not `KEY=VALUE` or a comment makes **every** compose command fail, the build
included. It is easy to miss because compose writes the complaint to stderr while
the surrounding pipeline still looks like it ran — and because the old container
keeps serving, so the site never appears to break.

This happened: a terminal transcript (a curl command and its JSON response) was
pasted into the end of `.env`, and two rebuilds quietly did nothing while the
container went on serving a 12-hour-old image.

```bash
docker compose config --quiet && echo "compose can read .env"
```

Read the build's exit status and its output. "The command returned" is not the same
as "the image was rebuilt" — check the image's creation time or its baked
provenance, which is the thing the page reports anyway.

---

## 2. Never delete the database. Migrate it.

`data/awltux.db` (the `awltux-data` volume in Docker) holds every fact this system
has recorded: the instrument universe, price history, filings, news, decisions and
their scored outcomes. It is **not a cache**, and it is never deleted, reset or
recreated to pick up a schema change. A fresh database is not an upgrade — it
discards the only copy of the history.

When a model changes, the schema moves forward in place:

```bash
alembic revision -m "what changed"   # additive, inspection-guarded
awltux migrate                       # applies it to the existing file
```

- Migrations must be **additive and inspection-guarded** — `0004` adds
  `news_item.event_type` only if the column is absent — so `upgrade head` is
  correct for a fresh database, an old one, and one already migrated.
- `awltux migrate` **copies the database to `data/backups/` before rewriting
  anything**, and skips the copy when nothing is pending.
- The only things that destroy stored data are deleting the file and
  `awltux seed-demo --reset`. Neither is part of an upgrade.
- `alembic check` must report "No new upgrade operations detected" — that is how
  you know the models and the live database agree.

---

## 3. The test suite is offline, and must stay that way

`pytest` runs entirely offline: no network, no API keys. `conftest.py` forces every
credential to `None` and asserts that no provider is configured. Do not write a
test that needs a live provider — capture the real response shape as a fixture
instead (see `tests/test_symbol_identity.py`, where the candidates are verbatim
provider output).

Never run the app's `create_app()` against the live data directory just to look at
a page: its lifespan **starts the scheduler**, which performs real provider calls
and writes to the database. Render the template directly instead.

---

## 4. Comments explain *why*, and name the failure they prevent

This codebase records reasoning that is not recoverable from the code: what the
obvious implementation was, what it did wrong, and what the evidence was. A comment
that restates the code is noise; a comment that says "this used to return early on
fewer than two points, so an empty panel was indistinguishable from a broken one"
is the point of the file.

When a bug is found in the behaviour rather than the code — a wrong threshold, a
mistaken rule — write down what was measured. `TODO.md` holds the open ones and the
resolved ones that would otherwise be re-litigated.

---

## 5. What "good code" means here

Six properties. Each rule below is already followed somewhere in this tree, and the
example is named so the standard is a thing you can go and read rather than an
adjective.

### Clean — say what the thing is, and never guess

- **Names describe the domain, not the type.** `load_price_targets`,
  `price_history_waiting_note`, `APPLY_FLOOR` — not `get_data`, `handle`, `THRESH`.
- **An unknown value is rendered as visible, never as a plausible number.** A
  missing figure shows `—`; it never becomes `0`, because `0` is a real value and a
  reader cannot tell the two apart. `templating.py` exists to be the one place that
  rule lives.
- **A wrong answer is worse than a visible gap.** Where a match is uncertain — a
  symbol, a company, a venue — the code refuses to apply it and records why, rather
  than picking the best of a bad set. See `APPLY_FLOOR` and the venue penalty in
  `ingest/identity.py`.
- **Nothing is inferred silently.** Configuration is explicit; a missing credential
  is reported as missing rather than producing an unauthenticated request that
  fails somewhere else entirely.

### Efficient — the network and the write lock are the expensive things

- **Never hold SQLite's write lock across a network call.** Release it first
  (`release_write_lock`), as every provider-touching job does.
- **Alternate network and database phases per batch** rather than wrapping a whole
  run in one transaction. `refresh_prices_eod` chunks at 40 for exactly this
  reason: one transaction across hundreds of provider calls locks the dashboard out
  for its duration.
- **Bound every bulk operation.** `INSTRUMENT_FLUSH_EVERY`,
  `RELEVANCE_BACKFILL_ROWS`, `RELEVANCE_FLUSH_EVERY` exist so a large import cannot
  balloon memory or the lock.
- **Respect the provider's budget.** `BudgetGuard` is acquired before every paid or
  rate-limited call; do not add a call that bypasses it.
- **Do work only where it is needed.** The symbol lookup considers only instruments
  with no stored bar, and the universe refresh rations itself across the day. A job
  that re-does settled work every run is a bug even when it is correct.

### Modular — separate what decides from what fetches

- **A decision is a pure function.** `ingest/identity.py` takes candidates and an
  instrument and returns a scored result, so the scoring rules can be tested against
  real provider output with no network. Its docstring states the split: *this module
  decides; the provider only proposes.* Prefer that shape for any new judgement.
- **The provider's output is untrusted data, returned as-is.** Adapters parse and
  stop. They do not decide, and they do not silently drop a candidate the caller
  might need to explain a refusal.
- **One concern per module.** SQL lives in `web/queries.py` so the templates never
  build their own; formatting lives in `web/templating.py`; timezone handling lives
  in `timezones.py`. If you are about to write SQL or a format string in a template,
  the function you actually want belongs in one of those.
- **No circular convenience.** A module may import the layers beneath it, not its
  siblings' internals.

### Secure — this dashboard shows holdings and has no login

- **Secrets never enter the repository or the image.** `.env` is gitignored *and*
  `.dockerignore`d; `.dockerignore` keeps it out even though no `COPY` would have
  taken it. Never print a credential: `redacted_dump` reports presence, and `doctor`
  reports length and character class.
- **The service is bound to loopback and is not authenticated.** `docker-compose.yml`
  binds `127.0.0.1` deliberately. Do not move it onto a network interface, and do
  not add an endpoint that assumes a trusted caller.
- **Trading stays gated.** `allow_live_orders` must remain false by default and must
  be checked at the point of action, not only in configuration.
- **Validate anything that becomes a path or a query.** `parse_zone` checks a cookie
  value against the real tz database before it reaches `ZoneInfo`, because zone keys
  are filesystem paths. Use bound parameters, never string-built SQL, and treat
  every provider string as untrusted input.
- **Fail closed on access, and say so.** A refusal is reported as a refusal; it is
  never softened into an empty success.

### Testable — offline, deterministic, and about the property that broke

- **The suite is offline and must stay that way** (section 3). If a behaviour needs
  a real provider, capture its response as a fixture and assert against that — the
  captured candidates in `tests/test_symbol_identity.py` are verbatim provider
  output, which is why the rule they test is trustworthy.
- **Test the property, not the implementation.** `test_the_chart_attributes_are_parseable_json`
  parses the attribute as the browser would; it does not grep for a string that
  happens to be there today.
- **A regression test names the failure it prevents,** in its docstring, with the
  measurement. A test whose reason is lost gets deleted by the next person who finds
  it inconvenient.
- **Assertions must be things that can fail.** No `assert True`, no asserting a
  helper you just wrote returns what you just made it return.

### Maintainable — leave the reasoning where the next person will find it

- **Migrations are additive and inspection-guarded** (section 2), so `upgrade head`
  is correct for a fresh database, an old one and one already migrated.
- **Comments carry the *why*, including what was tried and rejected** (section 4).
  This is the single highest-value habit in this repository: the reasoning is not
  recoverable from the code, and without it someone re-litigates the same decision.
- **Open questions have a home.** `TODO.md` records what is unresolved *and the
  evidence*, so the next session starts from measurement rather than from scratch.
- **Correct the record when it turns out to be wrong.** A claim in a document that
  is no longer true is a bug; fix it in the same change that invalidates it.
- **The build can always name itself** (section 1). Code that cannot say which
  revision is running cannot have its results trusted or reproduced.
