# Ingest value-investing education YouTube into `docs/research/FINDINGS.md`

Scope: **it exists to populate `FINDINGS.md`.** Enumerate the six channels, fetch the
transcripts that matter, extract concepts, write findings.

Promoted out of `.tmp/` so the work is not lost. What is committed: the code, its tests,
the two selection inventories, and the transcripts the findings rest on. What is not:
acquisition state and extraction output, both of which a local run regenerates
(`.gitignore` beside this file says which and why).

Everything here is shaped by one measured fact: **this IP was locked out of YouTube's
caption endpoint once already**, and the run that did it was the run that *retried a
`429`*. See `.tmp/youtube-probe-report-20261007.md` for the post-mortem. So the rate
limiting is not a wrapper around the fetch — it is the deliverable that makes the
fetch safe to leave running unattended for days.

## Layout

| Path | Committed | Concern |
|---|---|---|
| `pace.py` | yes | the pacing policy: quota, spacing, cooldown, attempt state. All time injected |
| `fetch.py` | yes | the only module that talks to YouTube. Asks `pace` permission before each request |
| `distill.py` | yes | offline: transcripts in, concept candidates out |
| `report.py` | yes | offline: state + verdicts -> `docs/research/FINDINGS.md` |
| `run.py` | yes | CLI. `plan` / `fetch` / `distill` / `report` / `locate` / `quota` |
| `dummy.py` | yes | a fake YouTube + fake clock, so the policy is tested without the network |
| `test_*.py` | yes | 54 tests, all offline |
| `inventory/edu_*_tiered.json` | yes | the **selection**: 181 videos and 42 playlists chosen by title |
| `transcripts/*.txt` | yes | the **evidence** the findings rest on — 23 files, ~1.0 MB |
| `sources/findings_source.md` | yes | the hand-written verdicts; the one part of `FINDINGS.md` a generator does not own |
| `state/`, `out/` | **no** | local acquisition state and derived output |
| `transcripts/index.json` | regenerated | per-video title, URL, `url_key`; rebuilt by `fetch` |

The transcripts are committed deliberately, and the reason is that `FINDINGS.md` is
evidence-graded: its central `implement` row turns on specific passages, and it states
that twelve transcripts contain no method at all. Without the text, the next reader can
only re-check those claims by re-spending the requests that took a lockout to learn to
respect. Everything genuinely cheap to rebuild — the extraction, the candidate payload,
the state — is excluded instead.

## The policy, and where each number comes from

| Knob | Value | Where it comes from |
|---|---|---|
| spacing | 6 s ± 30 % | ~12 transcripts at 2 s were fine, then a block; 6 s on a jittered interval is wider than the run that failed |
| per run | 12 | `youtube-transcript-api` issue #467 reports a ~2–3 request limit; 12 is the skill's measured-safe zone at 5 s, rounded down |
| per day | 15 | the same ceiling held across a *day* instead of a burst, so one forgotten cron cannot spend the budget in an hour |
| cooldown | 24 h | the only measurement is ">1 h". 12 h (the skill's number) is a project default, not YouTube's; for a multi-day run, 24 h is the cheap side of the bet |
| retries on a block | 0 | **this is the fix.** Never re-ask after a stop signal |
| concurrency | 1 | serial, always |

`pace.py` refuses rather than warns. Quota exhausted, cooldown active, or a block
recorded all mean *no request leaves the machine*, and the refusal says which.

## State: three stores, three questions

The pipeline has three states, and they are held in three different places on purpose —
conflating them is what once made the coverage report claim 1 video held out of 100
while 13 were on disk. `run.py plan` prints all three.

| Question | Store | Rule |
|---|---|---|
| *what is still to do?* | `inventory/edu_*_tiered.json` (committed) | selection is re-derived fresh every run, so it cannot go stale |
| *what have we downloaded?* | `transcripts/*.txt` | a file with >= 200 characters is held; `index.json` carries its title, URL and `url_key` |
| *what is fully processed?* | `out/candidates.json` | a `digests` entry keyed by `sha256(text)` |
| *is the file we hold the file we read?* | the same `digests` | `distill.integrity_report` — a count and one example, not an exercise |

## The record, and re-running at any time

The requirement this answers: *the script can be re-run at any moment without causing a
rate limit.* That is two separate properties, and only the first is automatic.

1. **Enforcement.** A request past the rolling cap is refused before it is made, so a
   re-run cannot over-spend, and a re-run of a run that just happened spends nothing.
2. **Answerability.** `run.py quota` prints the log by day and the **next available
   request slots as timestamps**, so "wait or go?" is answered rather than tested.
   Trying again to see what happens is what caused the original block.

```bash
$PY ingest_youtube/run.py quota
```

```
  in the window 11/15   spendable now: 4
  by day (local):
    date          reqs     first      last  videos
    2026-10-07      11     18:26     18:57  oFz94rZbc4c, coS6TXtKfV0, ...
  next available request slots:
    #1   2026-10-07 18:57:51   (now)
    ...
    #5   2026-10-08 18:26:17   (in 23.5h)
```

The schedule is **derived, not stored**: the Nth future slot is when the Nth-oldest
logged request falls 24 h into the past, so it is recomputed from the log every time and
cannot drift from the window the caps actually enforce. The same log is the only source
for both the caps and the record — a separate counter would be a second source of truth
and would eventually disagree with the one doing the limiting.

`FINDINGS.md` carries the same table inside its generated block, so the record travels
with the findings rather than living only in a command.

**A block is not a slot.** `slots()` returns nothing while a cooldown is active: the far
end has said stop, and there is no schedule through that.

## Duplicate detection: MD5 of the content, which is where a checksum earns its place

MD5 was proposed for *filenames* and rejected (below). It is exactly right for
*content*: the same talk appears on several of these channels and channels re-upload, so
one lecture under two video ids is expected rather than surprising.

`fetch.content_hash` is MD5 of the **normalised** transcript text (whitespace collapsed
by `fetch_text`, so the hash covers the canonical form rather than the raw snippets).
When a fetch returns text whose hash is already in the store:

- the text is **not** written a second time — two copies of one lecture would be counted
  as two sources by everything downstream;
- the ledger records `status: duplicate` with `duplicate_of` and `content_md5`, so the
  request stays auditable;
- `state/duplicates.json` and the report's coverage table record the group;
- the request is still counted. A duplicate saves **storage, not quota.**

This is why the duplicate-numbered course sessions did not need a judgement call: the
selection holds `Session 8` twice and `Session 12` three times, and rather than guess
whether they are re-uploads or different years, the fetch compares the text. Measured on
the first 10: **zero duplicate groups**, so they are genuinely different lectures.

## Why files are named after the video id, not a hash of the URL

Hashing the download URL into the filename was proposed, so a URL could find the file.
It was not adopted. The video id *is* the URL's identity — 11 characters against a
hash's 32 or 64, readable, and greppable. A URL is **not one value per video**:
`watch?v=X&list=PL1` and `watch?v=X` are the same video, and 18 of the 181 selected
videos came from *playlist* URLs, which name the container rather than the video, so
several videos would share one hash. And MD5 is broken against collision, which a
filename cannot survive silently.

What the proposal was reaching for is kept:

- `fetch.url_key(url)` gives a stable key from the **video id** inside any URL shape
  (`watch?v=`, `youtu.be/`, `/shorts/`, `/embed/`, `/live/`), discarding `list=`,
  `index=`, `t=` and tracking parameters. A playlist URL yields `None` rather than an
  invented key.
- `fetch.url_index(root)` maps `url_key -> video id`, and the index records `url_key`
  per entry, so a URL resolves to the file already on disk without a request.
- `run.py locate <id-or-url>` is the command that answers it.
- `distill.transcript_digest` hashes the **content**, so integrity is checked
  independently of where the text came from. It is deliberately not folded together
  with `EXTRACTOR_VERSION`: "the rules changed" and "the text changed" need different
  responses and one digest cannot tell them apart.

`state/`, four files. Local, gitignored, and cheap to lose — but losing them means
forgetting which videos have already been asked for:

- `requests.jsonl` — one line per request, and the log the rate limits are enforced
  from. Nothing else is authoritative.
- `ledger.json` — per video: `status` (`todo` / `ok` / `no_captions` / `error` /
  `blocked` / `duplicate`), attempts, when, why. `no_captions` and `error` are kept
  distinct: a video without captions is **absent**, not **failed**, and merging them is
  how a gap in the corpus becomes invisible. **This is a record of requests, not of
  coverage** — the twelve transcripts adopted from disk cost no request and are
  deliberately not in it.
- `cooldown.json` — a block and its expiry, so it survives the process *and* the
  session. The process that gets blocked is not the process that has to remember it.
- `duplicates.json` — content MD5 -> ids, for re-uploads already recognised.

**The extraction watermark.** `distill` records one digest per transcript. A transcript
whose digest is unchanged is **skipped**, not re-read, and its candidates are carried
forward verbatim; `--force` overrides. Two consequences worth knowing:

- bumping `distill.EXTRACTOR_VERSION` makes every transcript outstanding again, which is
  the only way "never distilled" stays distinguishable from "distilled by older rules";
- a transcript that is re-fetched and differs — captions get revised — changes its
  digest and is re-read, which a `done: true` flag could not notice.

## Commands

```bash
PY=.venv/Scripts/python.exe

# where everything is: acquired, outstanding, extracted — spends nothing
$PY ingest_youtube/run.py plan

# fetch. refuses without --live, because the default has to be the safe one
$PY ingest_youtube/run.py fetch --live --max-this-run 1 --only <video-id>

# is this URL already downloaded?
$PY ingest_youtube/run.py locate <video-id-or-url>

# the download record, and when the next request is permitted
$PY ingest_youtube/run.py quota

# offline: concepts, by transcript. skips transcripts already extracted
$PY ingest_youtube/run.py distill --out ingest_youtube/out/candidates.json

# regenerate FINDINGS.md from state + sources/findings_source.md
$PY ingest_youtube/run.py report --out docs/research/FINDINGS.md
```

`--only` names a video explicitly and ignores the tier filter: naming it is the
selection decision. `--tiers` is repeatable (`--tiers core --tiers example`); it is not
`nargs="*"`, because that would swallow the next `--flag`. `distill --force` re-extracts
transcripts whose digest is unchanged, which is normally wrong.

## Acquisition spent to date

**Eleven requests**, all recorded in `state/requests.jsonl`: one approved probe
(`oFz94rZbc4c`, Damodaran *Session 4: DCF Big Picture and First Steps in Riskfree
Rates*, 15,433 words) and then the first batch of ten course sessions. No block, no
cooldown file. The twelve transcripts an earlier run had already fetched were
**adopted from disk, not re-requested**.

State at that point: 23 transcripts, 23 extracted, 23 verified, 0 duplicate groups, 83
core videos still outstanding — about six days at 15 requests per 24 hours. That elapsed
time is the point of the pacing, not an obstacle to it.

## Tests

```bash
$PY -m pytest ingest_youtube/ -q -p no:cacheprovider
```

`dummy.py` substitutes a fake API and a fake clock, so the invariants that matter —
never two requests inside the interval, never a second request after a block, no
request at all once the daily quota is spent — are asserted without a network call.

`-p no:cacheprovider` and the `.work/` scratch directory are both concessions to the
file sandbox this project runs under: the system temp directory and the repo's
`.pytest_cache` are not writable, and pytest's own `tmp_path` fixture fails there. One
side effect is left behind and cannot be removed — `.pytest-tmp`, an empty directory
this sandbox denies `rmdir`, `Remove-Item` and `shutil.rmtree` alike. It is harmless
and ignored by git; delete it from a shell outside the sandbox if it is doing damage to
anyone's feelings.
