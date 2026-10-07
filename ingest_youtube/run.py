"""One CLI for the whole ingest: plan, fetch, distill, report.

    python ingest_youtube/run.py plan
    python ingest_youtube/run.py fetch --live --max-this-run 1 --only <id>
    python ingest_youtube/run.py distill
    python ingest_youtube/run.py report --out docs/research/FINDINGS.md

Promoted out of `.tmp/` so the work is kept: the code, its tests, the selection
inventories and the transcripts are tracked, while acquisition state and extraction
output stay local (see `.gitignore` beside this file).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The checkout root. `parents[1]` while this lived in `.tmp/ingest_youtube`; one level
#: up now, and left as a named constant so the report path below reads from the root
#: rather than from wherever the process happens to have been started.
REPO = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import distill  # noqa: E402
import fetch  # noqa: E402
import report  # noqa: E402
from pace import Pacing, Policy  # noqa: E402

#: The tiered selection produced by `yt_select.py` over the six channels.
#:
#: Committed, not read from `.tmp/`: a promoted tool that depends on untracked scratch
#: cannot be run by anyone else, and this file is the *selection judgement* -- which
#: videos are about valuation -- so it is a record rather than an intermediate.
#: Enumeration is not repeated here because it costs YouTube requests to do it.
INVENTORIES = (
    (HERE / "inventory" / "edu_videos_tiered.json", "videos"),
    (HERE / "inventory" / "edu_lists_tiered.json", "playlists"),
)

#: Transcripts fetched by an earlier run, under numbered names in `.tmp/transcripts`.
#: Adopted rather than re-fetched: twelve requests saved against the endpoint that
#: blocked this IP once. Optional -- when the directory is absent, adoption is skipped
#: and nothing else changes, so a fresh clone does not need it.
LEGACY_TRANSCRIPTS = REPO / ".tmp" / "transcripts"

#: Methods come from curated courses, not from a channel's individual uploads.
#: `example` is a worked valuation of one ticker -- useful for checking the app's own
#: arithmetic, not a source of technique.
DEFAULT_TIERS = ("core",)

#: Titles from the crowded numbering scheme, held back from the default queue.
#:
#: Measured 2026-10-07, and the first version of this got it backwards, so the
#: correction is the note. The channel publishes two runs that both number lectures
#: with a bare "Session N", and the numbers collide: Session 8 twice, Session 12 three
#: times, up to Session 18. A *default* queue keyed on "Session" alone therefore offers
#: two candidates for one step and pays twice for one lecture.
#:
#: The marker is **not** the discriminator -- the installed run's own ids (`coS6TXtKfV0`
#: Session 5, `C4zBohJ_Pts` Session 11, `JE55w2FLL1A` Session 13) carry "(of 42)" too,
#: so excluding on it would have dropped the course this task exists to read. What is
#: excluded instead is the *subject overlap*: titles about pricing, life-cycle and
#: sector-specific valuation, which the frontier-session list duplicates under
#: different numbers. Everything else stays in the queue.
#:
#: Whether two same-numbered sessions are one lecture re-uploaded or two different
#: years is **not** decided here. It does not need to be: `fetch.content_hash` compares
#: the text and refuses to store the same words twice, so the answer costs storage
#: logic rather than a guess in the selection.
OVERLAPPING_TOPICS = (
    r"pricing closure",
    r"asset-based valuation",
    r"across the life cycle",
    r"valuing the market",
    r"emerging market",
    r"financial service",
)


def load_inventory(tiers: tuple[str, ...], *, include_other_course: bool = False) -> list[dict]:
    """The selected videos worth a caption request, deduplicated by id.

    Dedupe matters more than it looks: the same talk appears on several of these
    channels and channels re-upload, so without it the corpus pays twice for one video.
    Two further exclusions keep the same lecture out of the queue twice -- see
    :data:`PHILOSOPHY_OR_OTHER_COURSE` and :data:`OVERLAPPING_TOPICS`.
    """
    seen: dict[str, dict] = {}
    overlap = re.compile("|".join(OVERLAPPING_TOPICS), re.IGNORECASE)
    for path, key in INVENTORIES:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload.get(key) or []:
            if key == "playlists":
                continue  # a playlist must be expanded to videos before it is fetched
            if tiers and item.get("tier") not in tiers:
                continue
            if not include_other_course and overlap.search(item.get("title") or ""):
                continue
            seen.setdefault(item["id"], item)
    return list(seen.values())


def inventory_by_id() -> dict[str, dict]:
    """Every selected video, whatever its tier -- for ``--only`` lookups."""
    return {video["id"]: video for video in load_inventory(())}


def called_tiers(args) -> tuple[str, ...]:
    """The tiers a command was asked for, defaulting to the method-bearing ones."""
    return tuple(args.tiers or DEFAULT_TIERS)


def cmd_plan(args) -> int:
    """Where every item in the pipeline is, and what the next run would spend.

    Three states, printed as three lines, because they are three different stores and
    conflating them is what made the coverage report claim one video out of a hundred
    while thirteen were on disk.
    """
    tiers = called_tiers(args)
    pacing = Pacing(HERE, Policy())
    videos = load_inventory(tiers)
    held = fetch.held_ids(HERE)
    todo = [video for video in videos if video["id"] not in held]
    selected_ids = inventory_by_id()
    store = set(held)

    extracted = distill.load_previous(HERE / "out" / "candidates.json")
    digests = extracted.get("digests") or {}
    processed = {video_id for video_id in store if video_id in digests}
    stale = {
        video_id
        for video_id in processed
        if digests[video_id]
        != distill.transcript_digest(
            (HERE / "transcripts" / f"{video_id}.txt").read_text(encoding="utf-8")
        )
    }

    print("acquire :")
    print(f"  selected      {len(selected_ids):4d}   videos in the tiered inventory")
    print(f"  held          {len(held):4d}   transcripts on disk")
    print(f"  outstanding   {len(todo):4d}   no transcript yet, this tier")
    print(f"  budget        {pacing.next_run_hint()}")
    print(
        f"                {pacing.policy.max_per_run}/run, {pacing.policy.max_per_day}/24h, "
        f"{pacing.policy.min_interval:g}s spacing -> "
        f"{_days(len(todo), pacing.policy.max_per_day):.0f} days for this tier"
    )
    print("\nextract :")
    print(f"  distilled     {len(processed):4d}   transcripts a candidates payload accounts for")
    print(f"  not distilled {len(store - processed):4d}   held but never extracted")
    if stale:
        print(f"  re-extract    {len(stale):4d}   transcript changed since it was extracted")
    print(f"  extractor     v{distill.EXTRACTOR_VERSION}")

    print("\nnext to acquire :")
    for video in todo[: args.show]:
        print(f"  {video['id']}  [{video.get('tier')}]  {video['title'][:78]}")
    if len(todo) > args.show:
        print(f"  ... {len(todo) - args.show} more")
    return 0


def _days(count: int, per_day: int) -> float:
    return count / per_day if per_day else float("inf")


def cmd_fetch(args) -> int:
    policy = Policy(max_per_run=args.max_this_run)
    pacing = Pacing(HERE, policy)
    videos = load_inventory(called_tiers(args))
    if args.only:
        # An explicitly named video is fetched whatever its tier: the operator has
        # already made the selection judgement by naming it.
        by_id = inventory_by_id()
        wanted = list(dict.fromkeys(args.only))
        videos = [by_id[video_id] for video_id in wanted if video_id in by_id]
        missing = [video_id for video_id in wanted if video_id not in by_id]
        if missing:
            print(f"not in the selected inventory: {', '.join(missing)}", file=sys.stderr)
            return 1

    repaired = fetch.refresh_url_keys(HERE)
    if repaired:
        print(f"backfilled url_key on {repaired} index entr(ies) -- no requests spent\n")

    adopted = fetch.adopt_existing(HERE, LEGACY_TRANSCRIPTS, videos)
    if adopted:
        print(f"adopted {adopted} transcript(s) already on disk -- no requests spent\n")

    dry = not args.live
    if dry:
        print("DRY RUN: nothing will be requested. Pass --live to spend real requests.\n")
    else:
        # A preflight that cannot alter anything it inspects: the run counter is not
        # advanced, because this is a question about the gate, not a request.
        if pacing.cooldown_remaining() > 0:
            print(
                f"REFUSED before any request (cooldown): blocked run still cooling down, "
                f"{pacing.cooldown_remaining() / 3600:.1f}h left",
                file=sys.stderr,
            )
            return 3
        print(f"live run: up to {policy.max_per_run} request(s)\n")

    summary = fetch.fetch_batch(HERE, videos, pacing, dry_run=dry)

    print(
        f"\n{summary['fetched']} fetched, {summary['skipped']} skipped, "
        f"{summary.get('duplicate', 0)} duplicate (same text, not stored twice), "
        f"{summary['absent']} absent (no captions), {summary['failed']} failed, "
        f"{summary['requests']} request(s) this run"
    )
    if summary["refused"] is not None:
        refusal = summary["refused"]
        print(f"stopped: [{refusal.reason}] {refusal.detail}", file=sys.stderr)
        return 3
    print(f"next: {pacing.next_run_hint()}")
    return 0


def cmd_distill(args) -> int:
    out = Path(args.out)
    previous = distill.load_previous(out)
    payload = distill.distill_store(HERE, previous, only_outstanding=not args.force)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(
        f"{payload['transcripts']} transcripts on disk: "
        f"{payload['extracted_this_run']} extracted this run, "
        f"{payload['already_extracted']} unchanged since the last run "
        f"(extractor v{payload['extractor_version']})"
    )
    print(f"{len(payload['candidates'])} candidates")
    for name, ids in sorted(payload["genres"].items(), key=lambda kv: -len(kv[1])):
        print(f"  {name:14s} {len(ids):3d}  {', '.join(sorted(ids)[:4])}")
    if payload["by_concept"]:
        print("\nconcepts seen:")
        for concept, count in sorted(payload["by_concept"].items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {concept}")
    if payload["outstanding"]:
        print(f"\nstill to extract: {', '.join(payload['outstanding'][:6])}"
              + (" ..." if len(payload["outstanding"]) > 6 else ""))
    print(f"\n-> {out}")
    return 0


def cmd_report(args) -> int:
    source = Path(args.source)
    written, carried = report.write_findings(HERE, source, Path(args.out))
    print(f"wrote {args.out} ({written} chars, {carried} chars carried forward)")
    return 0


def cmd_locate(args) -> int:
    """Where one video stands, by video id **or by any URL that leads to it**.

    The question the store could not answer: given a URL, is the transcript already
    here? Answered from the index's `url_key`, not by hashing the URL into a filename
    -- `watch?v=X&list=PL1` and `watch?v=X` are one video and must resolve to one file.
    Spends nothing.
    """
    index = fetch.load_index(HERE)
    by_url = fetch.url_index(HERE)
    extracted = distill.load_previous(HERE / "out" / "candidates.json")
    digests = extracted.get("digests") or {}
    store = HERE / "transcripts"
    held = fetch.held_ids(HERE)
    status = 0
    report = distill.integrity_report(HERE, extracted)
    broken = set(report["mismatched"])

    for query in args.videos:
        key = fetch.url_key(query)
        video_id = by_url.get(key) if key else None
        video_id = video_id or (query if query in index or query in held else None)
        if video_id is None:
            # A playlist URL names no video, which is exactly why it cannot be a key.
            note = (
                "a playlist URL names a container, not a video"
                if "list=" in query and not fetch.video_id_from_url(query)
                else "not in the store"
            )
            print(f"{query}\n  MISSING — {note}")
            status = 1
            continue

        entry = index.get(video_id) or {}
        path = store / f"{video_id}.txt"
        print(f"{query}\n  video id   {video_id}")
        print(f"  transcript {path if path.exists() else 'MISSING'}")
        print(f"  url key    {key or '—'}  ({'resolved' if key else 'no url recorded'})")
        print(f"  held       {'yes' if video_id in held else 'no'}")
        print(f"  extracted  {'yes' if video_id in digests else 'no'}")
        if video_id in digests:
            print(f"  intact     {'no — content differs from what was extracted' if video_id in broken else 'yes'}")
        print(f"  title      {entry.get('title') or '—'}")
        print()
    return status


def cmd_quota(args) -> int:
    """The download record and the schedule: when the script may safely run again.

    Written because "run it whenever" needs an answer that is a fact rather than a
    hope. The caps are a rolling window read from the request log, so the next run's
    earliest moment is derivable; a re-run inside the window is refused, never queued,
    which is what keeps a forgotten cron from becoming a lockout.
    """
    from pace import day_stamp

    pacing = Pacing(HERE, Policy())
    state = pacing.availability()

    print("YouTube caption requests — the log the caps are enforced from")
    print(f"  log file      {pacing.log_path}")
    print(f"  policy        {state['per_run']}/run, {state['per_day']} per rolling 24h, "
          f"{pacing.policy.min_interval:g}s spacing (jittered upward)")
    if state["cooldown_seconds"] > 0:
        print(f"  COOLDOWN      {state['cooldown_seconds'] / 3600:.1f}h remaining — a block "
              f"stops everything; nothing runs until it expires")
    print(f"  in the window {state['in_window']}/{state['per_day']}   "
          f"spendable now: {state['free']}")

    history = pacing.history()
    if not history:
        print("\n  no requests recorded yet")
    else:
        print("\n  by day (local):")
        print(f"    {'date':<12} {'reqs':>5}  {'first':>8}  {'last':>8}  videos")
        for record in history[-14:]:
            first = day_stamp(record["first"])[11:16]
            last = day_stamp(record["last"])[11:16]
            videos = ", ".join(v for v in record["videos"] if v)
            print(f"    {record['date']:<12} {record['requests']:>5}  {first:>8}  "
                  f"{last:>8}  {videos[:64]}")

    slots = state["slots"]
    print("\n  next available request slots:")
    if not slots:
        print("    none — a cooldown is active; delete state/cooldown.json only if you "
              "know the block has lifted")
    for instant, nth in slots:
        when = day_stamp(instant)
        wait = instant - state["now"]
        label = "now" if wait < 1 else f"in {wait / 3600:.1f}h"
        print(f"    #{nth:<3} {when}   ({label})")
    if slots:
        day = day_stamp(slots[-1][0])[:10]
        print(f"\n  {len(slots)} slots shown; the last is on {day}.")
    print("\n  Re-running the fetch at any moment is safe: requests beyond the caps are "
          "refused before they are made.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    # `nargs="*"` would swallow a following `--flag`, so tiers are named explicitly
    # and repeated: `--tiers core --tiers example`.
    def add_tiers(target) -> None:
        target.add_argument(
            "--tiers",
            action="append",
            choices=["core", "supporting", "context", "example"],
            default=None,
            help="selection tier to acquire; repeatable (default: core)",
        )

    plan = sub.add_parser("plan", help="what a fetch would do, without requesting anything")
    add_tiers(plan)
    plan.add_argument("--show", type=int, default=15)
    plan.set_defaults(func=cmd_plan)

    do_fetch = sub.add_parser("fetch", help="paced transcript acquisition")
    add_tiers(do_fetch)
    do_fetch.add_argument("--live", action="store_true", help="actually make requests")
    do_fetch.add_argument("--max-this-run", type=int, default=1, help="cap for this run")
    do_fetch.add_argument("--only", nargs="*", default=None, help="restrict to these video ids")
    do_fetch.set_defaults(func=cmd_fetch)

    do_distill = sub.add_parser("distill", help="offline: candidates from the transcript store")
    do_distill.add_argument("--out", default=str(HERE / "out" / "candidates.json"))
    do_distill.add_argument(
        "--force",
        action="store_true",
        help="re-extract transcripts whose digest is unchanged (normally skipped)",
    )
    do_distill.set_defaults(func=cmd_distill)

    do_report = sub.add_parser("report", help="write FINDINGS.md")
    do_report.add_argument("--out", default=str(REPO / "docs" / "research" / "FINDINGS.md"))
    do_report.add_argument("--source", default=str(HERE / "sources" / "findings_source.md"))
    do_report.set_defaults(func=cmd_report)

    do_locate = sub.add_parser(
        "locate", help="is this video already downloaded? accepts an id or any URL"
    )
    do_locate.add_argument("videos", nargs="+", help="video ids or YouTube URLs")
    do_locate.set_defaults(func=cmd_locate)

    do_quota = sub.add_parser(
        "quota", help="the download record by day, and when the next run may safely happen"
    )
    do_quota.set_defaults(func=cmd_quota)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
