"""The only module that talks to YouTube. It asks :mod:`pace` before every request.

Transport is `youtube-transcript-api`, not yt-dlp: yt-dlp enumerates channels and
playlists happily, but its caption download answers `429` from the same address the
API serves, and switching player clients does not help. Do **not** read
`captionTracks[].baseUrl` off the watch page either -- it is present, looks correct,
and returns HTTP 200 with a zero-length body, because the signature is minted for
`ip=0.0.0.0`. A fetcher that reads "empty response" as "no captions" returns zero
transcripts and reports success.

Three states are recorded per video and they must not be merged:

* `ok` -- text on disk;
* `no_captions` -- YouTube answered, and there is no English caption track. This is
  **absent**, not failed: the video cannot contribute and no amount of retrying helps;
* `error` -- we asked and something else went wrong. Retryable, once.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.parse
from pathlib import Path

if __package__ in (None, ""):  # allow `python ingest_youtube/fetch.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from pace import Pacing, Refusal, looks_blocked  # noqa: E402

#: Written to disk shorter than this and the fetch is treated as a failure. Some
#: videos genuinely caption only a few seconds (a title card, a trailer), so this is
#: a floor against empty bodies, not a quality filter.
MIN_USEFUL_CHARS = 200

#: How a transcript is named on disk: the video id, and nothing else.
#:
#: The obvious alternative was the hash of the download URL, so a file could be found
#: from the URL alone. It was **not** taken, for reasons that are about this corpus
#: rather than about taste:
#:
#: * the video id *is* the URL's identity, already 11 characters against a hash's 32
#:   or 64, and it is readable -- a transcript can be found with `ls` or named in a
#:   commit message;
#: * a URL is not one value per video. `watch?v=X&list=PL1` and `watch?v=X` are the
#:   same video, and 18 of the 181 selected videos came from *playlist* URLs, where
#:   the URL names the container and several videos share it. Hashing the URL would
#:   key distinct videos to one name and put one video under two;
#: * MD5 is broken against collision, and a filename is where a collision would be
#:   silent.
#:
#: What the idea *was* reaching for is kept: :func:`url_key` still turns a URL into a
#: stable key, and the index records it, so a URL can locate a transcript on disk
#: without a request. Content integrity is answered by a digest of the text itself
#: (:func:`distill.transcript_digest`), not of where it came from.
FILENAME_KEY = "video id"

#: Statuses that mean the answer will not change, so the video is never asked again.
#:
#: `no_captions` is here because a video with no English track has none on the second
#: ask either, and each ask is a request against a rate-limited endpoint. `blocked` is
#: here because the run that follows a block must not re-ask the video that caused it.
#: `error` is deliberately absent: a transient failure is worth exactly one retry,
#: which `Policy.max_attempts_per_video` bounds.
SETTLED = ("ok", "no_captions", "blocked")

#: The http error names `youtube-transcript-api` uses for "this video has no track".
#: Matched by name rather than imported so a library rename does not silently turn an
#: absence into an error.
NO_CAPTION_MARKERS = (
    "NoTranscriptFound",
    "TranscriptsDisabled",
    "VideoUnavailable",
    "NoTranscript",
    "NotTranslatable",
)


def _load_api():
    """The transcript client, or a message explaining how to get it."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print(
            "youtube-transcript-api is not importable. Install it out of the project venv:\n"
            "  .venv/Scripts/pip install --target .tmp/libs youtube-transcript-api\n"
            "  PYTHONPATH=.tmp/libs python ingest_youtube/run.py fetch --live",
            file=sys.stderr,
        )
        return None
    return YouTubeTranscriptApi()


def fetch_text(api, video_id: str, languages: list[str]) -> str:
    """One transcript as flat prose, or raise.

    A block is raised as the library's own exception and classified by the caller
    through :func:`pace.looks_blocked`; nothing here retries anything.

    The text is **normalised** on the way out, and everything downstream hashes and
    compares this form rather than the raw snippets. Measured the hard way: a test that
    compared the MD5 of an input string against the MD5 of the stored file disagreed,
    because the file is the normalised text. One canonical form, applied here at the
    boundary, is what stops that class of bug reaching the duplicate detector.
    """
    fetched = api.fetch(video_id, languages=languages)
    # Auto-captions arrive as short unpunctuated snippets; joined because every
    # consumer wants prose, flattened because the raw form carries stray newlines
    # that make a word count wrong.
    return " ".join(" ".join(snippet.text.split()) for snippet in fetched.snippets).strip()


def _store_paths(root: Path) -> tuple[Path, Path]:
    store = root / "transcripts"
    store.mkdir(parents=True, exist_ok=True)
    return store, store / "index.json"


def video_id_from_url(url: str) -> str | None:
    """The video id inside any YouTube URL shape, or ``None`` if there is not one.

    Handles `watch?v=`, `youtu.be/`, `/shorts/`, `/embed/` and `/live/`. A *playlist*
    URL yields ``None`` on purpose: it names a container, and inventing an id from it
    would key several videos to one name -- the failure mode that ruled out naming
    files after a URL hash in the first place.
    """
    parsed = urllib.parse.urlparse(url or "")
    host = (parsed.netloc or "").lower().removeprefix("www.")
    query = urllib.parse.parse_qs(parsed.query)

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0] in ("shorts", "embed", "live") and len(parts) > 1:
            candidate = parts[1]
        else:
            candidate = (query.get("v") or [""])[0]
    else:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate or "") else None


def url_key(url: str) -> str | None:
    """A stable key for a video URL, or ``None`` for a URL that names no video.

    The point is a lookup key that survives the noise in real URLs: `list=`,
    `index=`, `t=` and tracking parameters all vary between the URLs that lead to one
    video, and two of them must not become two keys. So the key is derived from the
    *video id* -- the one part of a YouTube URL that is stable and unique -- rather
    than from the raw string.
    """
    video_id = video_id_from_url(url)
    if video_id is None:
        return None
    return hashlib.sha256(f"youtube:{video_id}".encode()).hexdigest()[:16]


def url_index(root: Path) -> dict[str, str]:
    """``url_key -> video id`` for everything in the store, for locating a transcript.

    Read from the index rather than recomputed from filenames: entries adopted from an
    earlier run recorded a *canonicalised* URL, so the file name cannot be recovered
    from it and the mapping has to be stored. An entry with no URL is skipped rather
    than guessed at.
    """
    index: dict[str, str] = {}
    for video_id, entry in load_index(root).items():
        key = url_key((entry or {}).get("url") or "")
        if key:
            index[key] = video_id
    return index


def content_hash(text: str) -> str:
    """MD5 of a transcript's text, for **duplicate detection**.

    This is where a checksum does earn its place, and the difference from naming a file
    after a URL is the point. A filename has to be unique for ever and stable across
    corrections, and MD5 is unsuited to both -- which is why the filename is the video
    id. Detecting that two transcripts are the *same words* is a different question:
    MD5 is fast, the input is one we control, and a collision here would have to be
    constructed deliberately. The repo's own rule applies -- a checksum is a
    duplicate-detection tool, not a security boundary.

    The same talk appears on several of these channels and channels re-upload, so the
    same lecture under a second video id is expected rather than surprising. Without
    this, the corpus pays twice for text it already has and counts it as two sources.
    """
    return hashlib.md5(text.encode()).hexdigest()


def duplicate_index(root: Path) -> dict[str, list[str]]:
    """``content hash -> video ids`` for every transcript on disk.

    Built from the files rather than from a stored map: a stored map can disagree with
    the store, and this is the thing that decides whether a download is redundant.
    """
    found: dict[str, list[str]] = {}
    for path in sorted((root / "transcripts").glob("*.txt")):
        digest = content_hash(path.read_text(encoding="utf-8"))
        found.setdefault(digest, []).append(path.stem)
    return {digest: ids for digest, ids in found.items() if len(ids) > 1}


def load_duplicates(root: Path) -> dict:
    path = root / "state" / "duplicates.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_duplicates(root: Path, payload: dict) -> None:
    path = root / "state" / "duplicates.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


def load_index(root: Path) -> dict:
    _, index_path = _store_paths(root)
    if not index_path.exists():
        return {}
    try:
        return json.loads(index_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_index(root: Path, index: dict) -> None:
    _, index_path = _store_paths(root)
    index_path.write_text(json.dumps(index, indent=1, sort_keys=True), encoding="utf-8")


def held_ids(root: Path) -> set[str]:
    """Video ids already on disk with usable text, straight from the store."""
    store, _ = _store_paths(root)
    return {
        path.stem
        for path in store.glob("*.txt")
        if path.stat().st_size >= MIN_USEFUL_CHARS
    }


def fetch_batch(
    root: Path,
    videos: list[dict],
    pacing: Pacing,
    *,
    languages: list[str] | None = None,
    dry_run: bool = True,
    api=None,
    verbose=print,
) -> dict:
    """Walk ``videos``, spending at most one run's quota, and return a summary.

    ``dry_run`` is the default everywhere in this POC: the safe thing to do with a
    fetch tool pointed at an address that has been blocked before is to show what it
    *would* do until someone says otherwise.

    ``api`` is injected so the policy can be tested against :mod:`dummy` rather than
    against YouTube. It is the only seam that matters here.
    """
    languages = languages or ["en"]
    store, _ = _store_paths(root)
    index = load_index(root)
    held = held_ids(root)
    summary = {"fetched": 0, "skipped": 0, "absent": 0, "failed": 0, "refused": None,
               "requests": 0, "capped": False, "duplicate": 0}

    # Content already on disk, keyed by MD5 of the text. Seeded from the store so a
    # re-upload is caught even when the original arrived in an earlier run.
    by_content: dict[str, str] = {}
    for path in sorted(store.glob("*.txt")):
        by_content.setdefault(content_hash(path.read_text(encoding="utf-8")), path.stem)
    duplicates = load_duplicates(root)

    planned = 0
    for video in videos:
        video_id = video["id"]
        if video_id in held or pacing.status(video_id) in SETTLED:
            summary["skipped"] += 1
            continue

        if dry_run and planned >= pacing.policy.max_per_run:
            # A plan is not a refusal: nothing was denied by the far end, the listing
            # was simply cut short. Reported as `capped`, not as a stop -- if this set
            # `refused`, `plan --max-this-run 3` would exit 3, which means "a request
            # was refused" everywhere else in this POC.
            summary["capped"] = True
            verbose(
                f"\n  ... {len(videos) - summary['fetched'] - summary['skipped']} more "
                f"would follow; this plan is capped at {pacing.policy.max_per_run}"
            )
            break

        verdict = pacing.ask(video_id, video.get("url", ""))
        if isinstance(verdict, Refusal):
            if verdict.reason not in ("attempts_exhausted",):
                # A run-level stop. Report it; the caller decides whether that is a
                # clean end of run or a problem.
                summary["refused"] = verdict
                verbose(f"\n  STOP ({verdict.reason}): {verdict.detail}")
                break
            summary["skipped"] += 1
            continue

        if dry_run:
            # A dry run counts what it *would* do in a counter of its own: advancing
            # `pacing.run_calls` here made the plan stop after the live run cap and
            # report one item of a hundred, which reads as "the plan is one video".
            planned += 1
            summary["fetched"] += 1
            verbose(
                f"  WOULD FETCH {video_id}  after {verdict.delay:.1f}s  "
                f"[{verdict.day_calls + planned}/{pacing.policy.max_per_day} in 24h]  "
                f"{(video.get('title') or '')[:60]}"
            )
            continue

        if api is None:
            api = _load_api()
            if api is None:
                return summary

        if verdict.delay > 0:
            pacing.sleeper(verdict.delay)

        attempts = pacing.attempts(video_id) + 1
        try:
            text = fetch_text(api, video_id, languages)
        except Exception as exc:  # noqa: BLE001 - each library raises its own type
            detail = f"{type(exc).__name__}: {exc}"
            if looks_blocked(detail):
                record = pacing.blocked(video_id, detail)
                verbose(
                    f"\n  BLOCKED at {video_id}. Run stopped, nothing retried; "
                    f"cooldown written to {record}."
                )
                summary["refused"] = Refusal("blocked", detail)
                pacing.spend(video_id, video.get("url", ""))
                summary["requests"] = pacing.run_calls
                return summary
            _record_failure(pacing, video, video_id, detail, attempts, verbose, summary)
            pacing.spend(video_id, video.get("url", ""))
            continue

        if len(text) < MIN_USEFUL_CHARS:
            pacing.record(video_id, status="error",
                          error=f"only {len(text)} chars", attempts=attempts,
                          title=video.get("title"))
            pacing.spend(video_id, video.get("url", ""))
            summary["failed"] += 1
            verbose(f"  EMPTY {video_id}: {len(text)} chars")
            continue

        # Duplicate detection, asked *after* the text is in hand and *before* it is
        # written: the request is already spent either way, so the only thing left to
        # decide is whether to keep a second copy of the same words. It is not kept.
        digest = content_hash(text)
        original = by_content.get(digest)
        if original is not None:
            _record_duplicate(root, pacing, duplicates, video, video_id, digest,
                              original, len(text.split()), attempts, verbose, summary)
            pacing.spend(video_id, video.get("url", ""))
            continue

        (store / f"{video_id}.txt").write_text(text, encoding="utf-8")
        by_content[digest] = video_id
        pacing.record(video_id, status="ok", attempts=attempts, words=len(text.split()),
                      title=video.get("title"), channel=video.get("channel"),
                      content_md5=digest, source=video.get("url"))
        pacing.spend(video_id, video.get("url", ""))
        index[video_id] = {
            "id": video_id,
            "title": video.get("title"),
            "tier": video.get("tier"),
            "source": video.get("source"),
            "url": video.get("url"),
            "url_key": url_key(video.get("url") or ""),
            "words": len(text.split()),
            "content_md5": digest,
        }
        save_index(root, index)
        save_duplicates(root, duplicates)
        summary["fetched"] += 1
        verbose(
            f"  {video_id}  {len(text.split()):6d} words  "
            f"{(video.get('title') or '')[:60]}"
        )

    summary["requests"] = pacing.run_calls
    return summary


def _record_failure(
    pacing: Pacing,
    video: dict,
    video_id: str,
    detail: str,
    attempts: int,
    verbose,
    summary: dict,
) -> None:
    """Record a non-block failure as absence or as an error -- never as one thing.

    The distinction is the whole point: `no_captions` means YouTube answered and there
    is no English track, which no retry will change; `error` means we asked and
    something else went wrong, which is worth exactly one retry. Merging them turns a
    fetch failure into a silent gap in the corpus.
    """
    absent = any(marker in detail for marker in NO_CAPTION_MARKERS)
    pacing.record(
        video_id,
        status="no_captions" if absent else "error",
        error=detail[:200],
        attempts=attempts,
        title=video.get("title"),
    )
    if absent:
        summary["absent"] += 1
        verbose(f"  no captions: {video_id}")
    else:
        summary["failed"] += 1
        verbose(f"  ERROR {video_id}: {detail.split(':')[0]}")


def _record_duplicate(
    root: Path,
    pacing: Pacing,
    duplicates: dict,
    video: dict,
    video_id: str,
    digest: str,
    original: str,
    words: int,
    attempts: int,
    verbose,
    summary: dict,
) -> None:
    """Record a re-fetched transcript as a duplicate of one already stored.

    The text is deliberately **not** written to a second file: two copies of one lecture
    would be counted as two sources by everything downstream, which is the opposite of
    what the corpus needs. The ledger keeps the mapping so the request is auditable, and
    `by_content` is left pointing at the original.
    """
    duplicates.setdefault(digest, []).append(video_id)
    save_duplicates(root, duplicates)
    pacing.record(
        video_id,
        status="duplicate",
        attempts=attempts,
        title=video.get("title"),
        url=video.get("url"),
        words=words,
        content_md5=digest,
        duplicate_of=original,
    )
    summary["duplicate"] += 1
    verbose(
        f"  DUPLICATE {video_id} is the same text as {original} "
        f"(md5 {digest[:12]}), not stored twice"
    )


def refresh_url_keys(root: Path) -> int:
    """Add a `url_key` to any index entry that lacks one. Returns how many were fixed.

    The index is metadata this POC owns, and a field added after entries were written
    is invisible to them -- an entry from before `url_key` existed cannot be found by
    URL, which is the whole point of the field. Backfilled from the URL the entry
    already records, and skipped when it records none: inventing one from the file name
    would be a guess, and this module is not allowed to guess.
    """
    index = load_index(root)
    fixed = 0
    for entry in index.values():
        if not isinstance(entry, dict) or entry.get("url_key"):
            continue
        key = url_key(entry.get("url") or "")
        if key:
            entry["url_key"] = key
            fixed += 1
    if fixed:
        save_index(root, index)
    return fixed


def _legacy_video_id(stem: str) -> str:
    """Recover the video id from a legacy file name, which carries an ordinal prefix.

    `01_KU_DR9PFFpc` -> `KU_DR9PFFpc`, `05_-0z0_kMqItY` -> `-0z0_kMqItY`. Split once,
    not on every underscore: ids contain them.
    """
    head, _, rest = stem.partition("_")
    if rest and head.isdigit():
        return rest
    return stem


def adopt_existing(root: Path, legacy_dir: Path, inventory: list[dict]) -> int:
    """Move transcripts already fetched into the store, without a single request.

    Written because this box already holds twelve transcripts from an earlier run.
    Fetching them again would spend twelve requests against a rate-limited endpoint
    for text that is already on disk -- the most expensive possible mistake here.

    Those twelve are **not** in the saved inventory: they came from a walk that was
    never persisted, and they are absent from the tiered selection because their
    titles are clickbait rather than method (measured: `distill.kind_of` classes all
    twelve as `entertainment`). So the index entry says where it came from instead of
    pretending a tier it never had, and the ledger is not touched -- an adopted
    transcript did not cost a request and must not count as one.
    """
    store, _ = _store_paths(root)
    index = load_index(root)
    by_id = {video["id"]: video for video in inventory}
    adopted = 0
    if not legacy_dir.exists():
        return 0
    for path in sorted(legacy_dir.glob("*.txt")):
        stem = path.stem
        video_id = _legacy_video_id(stem)
        target = store / f"{video_id}.txt"
        video = by_id.get(video_id)
        sidecar = _legacy_sidecar(legacy_dir, stem)
        url = (video or {}).get("url") or f"https://www.youtube.com/watch?v={video_id}"

        if target.exists():
            # Already copied by an earlier run. The entry is still refreshed, because
            # the index is metadata and this function is the only path that can add to
            # it: an entry written before `url_key` existed would otherwise stay
            # unfindable by URL for ever, and re-copying the text would gain nothing.
            if _needs_refresh(index.get(video_id), url):
                index[video_id] = _entry_for(video, sidecar, url, text=None, source_path=path,
                                             words=_word_count(target))
            continue

        text = path.read_text(encoding="utf-8")
        target.write_text(text, encoding="utf-8")
        index[video_id] = _entry_for(video, sidecar, url, text=text, source_path=path)
        adopted += 1
    save_index(root, index)
    return adopted


def _needs_refresh(entry: dict | None, url: str) -> bool:
    """Whether a stored entry is missing something this version of the index records."""
    if not entry:
        return True
    return not entry.get("url_key") or entry["url_key"] != url_key(url)


def _word_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").split())


def _entry_for(
    video: dict | None, sidecar: dict, url: str, *, text: str | None, source_path: Path,
    words: int | None = None,
) -> dict:
    """One index record, for a video that may or may not be in the saved selection.

    Records `url_key` so a URL can locate the file without a request, and says where an
    out-of-selection transcript came from rather than pretending it had a tier.
    """
    return {
        "id": (video or {}).get("id") or _legacy_video_id(source_path.stem),
        "title": (video or {}).get("title") or sidecar.get("title"),
        "tier": (video or {}).get("tier") or "unselected",
        "source": (video or {}).get("source") or "legacy run (not in the saved inventory)",
        "url": url,
        "url_key": url_key(url),
        "words": words if words is not None else len((text or "").split()),
        "adopted_from": str(source_path),
        # The URL above is a *canonicalisation*: the earlier run's sidecar holds no URL
        # at all, so the file name cannot be recovered from it and the mapping has to be
        # stored rather than derived.
        "in_selection": video is not None,
        "duration_seconds": sidecar.get("duration"),
    }


def _legacy_sidecar(legacy_dir: Path, stem: str) -> dict:
    """The metadata an earlier run wrote beside the text, if it is still there."""
    sidecar = legacy_dir / f"{stem}.json"
    if not sidecar.exists():
        return {}
    try:
        return json.loads(sidecar.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
