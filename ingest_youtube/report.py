"""Assemble `docs/research/FINDINGS.md` from the ledger, the corpus and the verdicts.

The rule this module exists to keep: **machine facts are generated, judgements are
written.** Coverage counts, which video is in which tier, what has been fetched and
what a block cost come from the state on disk, so they are always true and always
regenerated. What a concept *means* and what to do about it is written by hand in
`sources/findings_source.md`, because a script that invents verdicts is a script that
invents a wish list, which is exactly what the task note says a finding with no
disposition is.

Everything outside the two sentinel lines belongs to the generator. Everything inside
`sources/findings_source.md` belongs to a human and is never overwritten.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import distill

BEGIN = "<!-- BEGIN GENERATED -->"
END = "<!-- END GENERATED -->"

#: Heading the generator puts above text it did **not** source from
#: `sources/findings_source.md`. It is also how the generator recognises its own
#: earlier output: without this, each run treated the previous run's carry block as
#: new hand-written text and appended it again -- measured at 10k -> 19k -> 29k -> 38k
#: characters over four runs, which is a generator that eats its own tail.
CARRIED_HEADING = "## Carried forward from the previous file"

#: What each disposition means, per the task note. Repeated in the output so a reader
#: does not have to find the convention elsewhere to read the table.
DISPOSITIONS = (
    ("implement", "worth building, with the primary source that justifies it and a tier"),
    ("already covered", "the app or `investment-markers.md` already does this; link to it"),
    ("rejected", "with the reason, so it is not re-proposed"),
)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def coverage_table(root: Path) -> str:
    """The pipeline's three states, from the three stores that actually hold them.

    Written after the two stores disagreed and this table reproduced the disagreement:
    it counted *ledger* entries as coverage, but the twelve transcripts adopted from an
    earlier run are deliberately not in the ledger -- they cost no request -- so it
    reported 1 of 100 held while 13 were on disk. Selection comes from the tiered
    inventory, acquisition from the transcript store, extraction from the candidates
    payload and its digests. The ledger is read only for request outcomes.
    """
    ledger = load_json(root / "state" / "ledger.json", {})
    candidates = load_json(root / "out" / "candidates.json", {})
    store = {path.stem for path in (root / "transcripts").glob("*.txt")}
    statuses: dict[str, int] = {}
    for entry in ledger.values():
        statuses[entry.get("status", "todo")] = statuses.get(entry.get("status", "todo"), 0) + 1

    genres = candidates.get("genres") or {}
    processed = sorted(set(candidates.get("digests") or {}) & store)
    trace = _locatable(root, store)
    integrity = _integrity(root, candidates)
    lines = [
        "| Stage | Measure | Count |",
        "|---|---|---|",
        f"| selected | videos + playlists in the tiered inventory | {_inventory_size(root)} |",
        f"| **acquired** | transcripts on disk | **{len(store)}** |",
        f"| acquired | still to acquire (core tier) | {_outstanding(root, store)} |",
        f"| acquired | locatable from a URL (`url_key` recorded) | {trace} |",
        f"| **extracted** | transcripts distilled | **{len(processed)}** |",
        f"| extracted | extractor version that wrote them | "
        f"v{candidates.get('extractor_version')} |",
        f"| **verified** | transcripts matching what was extracted | **{len(processed) - len(integrity)}** |",
    ]
    if integrity:
        lines.append(
            f"| verified | **content differs from the extraction** — re-read or re-fetch | "
            f"{len(integrity)} |"
        )
    if candidates:
        lines.append(
            f"| extracted | extracted on the last run | "
            f"{candidates.get('extracted_this_run', 0)} |"
        )
        lines.append(
            f"| extracted | skipped as unchanged on the last run | "
            f"{candidates.get('already_extracted', 0)} |"
        )
    lines.append(
        f"| requests | ledger entries (**not** the same as transcripts on disk) | {len(ledger)} |"
    )
    for name in ("ok", "no_captions", "error", "blocked", "duplicate", "todo"):
        if statuses.get(name):
            lines.append(f"| requests | ledger: `{name}` | {statuses[name]} |")
    # Re-uploads are expected on these channels, so the count is stated rather than
    # left to be discovered: a duplicate costs one request and zero storage, and both
    # halves matter when deciding whether a channel is worth walking again.
    duplicates = _duplicate_groups(root)
    lines.append(f"| duplicates | content groups with more than one id | {len(duplicates)} |")
    for digest, ids in list(duplicates.items())[:5]:
        lines.append(f"| duplicates | `{digest[:10]}` | {', '.join(ids)} |")
    for name in ("method", "example", "mixed", "entertainment"):
        if genres.get(name):
            lines.append(f"| reading | genre census: **{name}** | {len(genres[name])} |")
    return "\n".join(lines)


def _outstanding(root: Path, store: set[str]) -> int:
    """Core-tier videos with no transcript on disk, by the rule `run.py plan` uses."""
    payload = load_json(root.parent / "edu_videos_tiered.json", {})
    core = [video for video in payload.get("videos") or [] if video.get("tier") == "core"]
    return sum(1 for video in core if video["id"] not in store)


def _locatable(root: Path, store: set[str]) -> int:
    """Held transcripts whose index entry records a `url_key`, so a URL finds them.

    Counted rather than assumed: a field added to the index after entries were written
    is invisible to those entries, so "every transcript has a key" is a fact to check,
    not a property of the code.
    """
    index = load_json(root / "transcripts" / "index.json", {})
    return sum(
        1
        for video_id in store
        if (index.get(video_id) or {}).get("url_key")
    )


def _integrity(root: Path, candidates: dict) -> list[str]:
    """Videos whose stored transcript no longer hashes to what was extracted from it."""
    return distill.integrity_report(root, candidates)["mismatched"]


def _duplicate_groups(root: Path) -> dict[str, list[str]]:
    """Content MD5 -> ids, for transcripts that are the same words as another."""
    import fetch

    return fetch.duplicate_index(root)


def _inventory_size(root: Path) -> int:
    """Selected videos and playlists, read from the committed selection files."""
    total = 0
    for name, key in (
        ("edu_videos_tiered.json", "videos"),
        ("edu_lists_tiered.json", "playlists"),
    ):
        payload = load_json(root / "inventory" / name, {})
        total += len(payload.get(key) or [])
    return total


def quota_section(root: Path) -> str:
    """What the pacing gate has cost, what it will allow next, and when.

    Read from the request log rather than from anyone's memory of the run: this is the
    section that has to be right, because it is the one that decides whether the next
    request is safe. The schedule is the answer to "may I run it now?" -- a timestamp
    rather than an experiment, because trying again to find out is what caused the
    original block.
    """
    from pace import Pacing, day_stamp

    pacing = Pacing(root)
    state = pacing.availability()
    cooldown = load_json(pacing.cooldown_path, {})
    lines = [
        f"- requests on record: **{state['in_window']}** in the last 24 h "
        f"(cap {state['per_day']}); **{state['free']} spendable now**",
        f"- spacing: {pacing.policy.min_interval:g}s, jittered upward up to "
        f"{pacing.policy.jitter:.0%}; per-run cap {pacing.policy.max_per_run}",
        "- retries after a block: **0 by construction** "
        "(`pace.Pacing.blocked` stops the run and writes the cooldown)",
    ]
    if cooldown.get("until"):
        lines.append(
            f"- **cooldown active**: started {day_stamp(cooldown['started'])}, "
            f"until {day_stamp(cooldown['until'])} ({cooldown.get('detail', '')[:120]})"
        )
    elif state["free"] == 0:
        lines.append(
            f"- the window is full; the next request is possible at "
            f"**{day_stamp(state['next_at'])}**"
        )
    else:
        lines.append("- cooldown: none")

    history = pacing.history()
    if history:
        lines += [
            "",
            "| Day (local) | Requests | First | Last |",
            "|---|---|---|---|",
        ]
        for record in history[-10:]:
            lines.append(
                f"| {record['date']} | {record['requests']} | "
                f"{day_stamp(record['first'])[11:16]} | {day_stamp(record['last'])[11:16]} |"
            )
    return "\n".join(lines)


def disposition_table(root: Path) -> str:
    lines = ["| Disposition | Meaning |", "|---|---|"]
    lines += [f"| **{name}** | {meaning} |" for name, meaning in DISPOSITIONS]
    return "\n".join(lines)


def build(root: Path, verdicts: str) -> str:
    """The generated preamble, followed verbatim by the hand-written verdicts."""
    return "\n".join(
        [
            BEGIN,
            "# Findings: what value-investing YouTube adds, and what it does not",
            "",
            "_Populated by `ingest_youtube/`. Machine-generated facts sit inside the "
            "`BEGIN/END GENERATED` sentinels and are safe to regenerate; everything after "
            "them is hand-written and is never overwritten._",
            "",
            "This file exists to answer one question: **does the education corpus change "
            "any marker the app already uses?** It is graded against "
            "`docs/investment-markers.md` and the reports in this directory, not against "
            "the channels' own authority. A video is where an idea was **noticed**; the "
            "primary source is what the finding rests on, and a video that names no "
            "primary source produces no finding.",
            "",
            "## Acquisition and quota",
            "",
            quota_section(root),
            "",
            "## Coverage",
            "",
            coverage_table(root),
            "",
            "## How a row is graded",
            "",
            disposition_table(root),
            "",
            "A row with no disposition is a wish list. A row whose only evidence is a "
            "transcript is refused: auto-captions mis-hear numbers and tickers, so any "
            "figure has to be found in a filing or a paper or left out.",
            "",
            END,
            "",
            verdicts.rstrip(),
            "",
        ]
    )


def write_findings(root: Path, source: Path, out: Path) -> tuple[int, int]:
    """Write ``out``, carrying forward any hand-written text the source does not hold.

    Both counts are returned so the caller can report what it did. ``carried`` is the
    length of text that already sat beyond the sentinel and is **not** the current
    source: an earlier run appended something by hand, or the source was edited since.
    Regenerating must not silently drop it, because losing a hand-written verdict to a
    generator run is the one failure this module must not have. The source of truth is
    `source`; anything else is preserved under a heading that says where it came from.
    """
    fresh = build(
        root,
        source.read_text(encoding="utf-8") if source.exists() else (
            "_No verdicts written yet: create `sources/findings_source.md`._"
        ),
    )
    source_text = source.read_text(encoding="utf-8").strip() if source.exists() else ""
    carried = ""
    if out.exists():
        existing = out.read_text(encoding="utf-8")
        if END in existing:
            tail = existing[existing.index(END) + len(END):]
            # Only text that is not the source *and* not a previous carry is new.
            if CARRIED_HEADING in tail:
                tail = tail[: tail.index(CARRIED_HEADING)]
            carried = tail.strip()
    keep = bool(carried) and carried.strip() != source_text.strip()
    if keep:
        fresh = fresh.rstrip() + (
            f"\n\n---\n\n{CARRIED_HEADING} (not in the generator's source)\n\n"
            + carried
            + "\n"
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(fresh, encoding="utf-8")
    # Only text that actually went into the file: a count of text that was *checked*
    # and discarded reads as a change that did not happen.
    return len(fresh), (len(carried) if keep else 0)


def main(argv: list[str] | None = None) -> int:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=here)
    parser.add_argument("--source", type=Path, default=here / "sources" / "findings_source.md")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    written, carried = write_findings(args.root, args.source, args.out)
    print(f"wrote {args.out} ({written} chars, {carried} chars carried forward)")
    return 0


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
