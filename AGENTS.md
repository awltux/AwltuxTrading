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
