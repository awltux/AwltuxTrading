"""Build provenance: which revision of this code is actually running.

The Info page has to be able to name the commit a running process came from, and
there are two very different situations to cover:

* a source checkout, where ``git log`` answers the question directly;
* a container image, which has no ``.git`` and no ``git`` binary, so the answer
  has to have been recorded *at image build time*.

So the history is either read live or read from ``build_info.json`` baked into
the installed package by ``python -m awltux.buildinfo --write <path>``. The
distinction is surfaced (:attr:`BuildInfo.source`) rather than hidden: "this
came from the checkout" and "this came from whatever the image was built from"
are different claims, and the second one is only as trustworthy as the build.

Nothing here is allowed to guess. A missing history renders as *unavailable*,
never as an empty list that would read like a clean success, and a build that
cannot capture a commit fails instead of shipping an anonymous image.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

DEFAULT_COMMIT_COUNT = 10

# Baked into the package at image build time; absent in a source checkout.
BUNDLED_PATH = Path(__file__).with_name("build_info.json")

# git's own output has to survive commit subjects containing anything, so the
# record and field separators are control characters rather than spaces.
FIELD = "\x1f"
RECORD = "\x1e"
GIT_FORMAT = f"%H{FIELD}%h{FIELD}%an{FIELD}%aI{FIELD}%s{RECORD}"

GIT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Commit:
    """One commit, as shown on the Info page."""

    hash: str
    short_hash: str
    author: str
    date: str
    subject: str

    def to_dict(self) -> dict[str, str]:
        return {
            "hash": self.hash,
            "short_hash": self.short_hash,
            "author": self.author,
            "date": self.date,
            "subject": self.subject,
        }

    @classmethod
    def from_dict(cls, data: Any) -> Commit | None:
        if not isinstance(data, dict):
            return None
        values = {key: data.get(key) for key in ("hash", "short_hash", "author", "date", "subject")}
        if not all(isinstance(value, str) for value in values.values()):
            return None
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class BuildInfo:
    """What the running process can prove about where it came from."""

    #: "git" (live checkout), "bundled" (recorded at image build time) or
    #: "unavailable" (neither).
    source: str
    #: When the bundled artifact was written; ``None`` when read live.
    generated_at: str | None
    #: Full hash of the newest commit, when one is known.
    head: str | None
    #: Whether the tree had uncommitted changes when the snapshot was taken.
    #: ``None`` means "not established", which is not the same as "clean".
    dirty: bool | None
    commits: tuple[Commit, ...]

    @property
    def is_known(self) -> bool:
        return bool(self.commits)

    @property
    def head_short(self) -> str | None:
        if not self.commits:
            return None
        short = self.commits[0].short_hash or self.commits[0].hash
        return short[:7] if short else None

    @property
    def is_dirty(self) -> bool:
        return self.dirty is True

    def limited(self, count: int) -> BuildInfo:
        if len(self.commits) <= count:
            return self
        return replace(self, commits=self.commits[:count])

    @classmethod
    def unavailable(cls) -> BuildInfo:
        return cls(source="unavailable", generated_at=None, head=None, dirty=None, commits=())


def parse_git_log(text: str) -> list[Commit]:
    """Turn ``git log --pretty=format:...`` output into commits.

    Malformed records are dropped rather than rendered as blanks: half a commit
    is not evidence of anything.
    """
    commits: list[Commit] = []
    for record in text.split(RECORD):
        record = record.lstrip("\r\n")
        if not record:
            continue
        fields = record.split(FIELD)
        if len(fields) != 5:
            continue
        full, short, author, date, subject = (field.strip() for field in fields)
        if not full:
            continue
        commits.append(
            Commit(
                hash=full,
                short_hash=short or full[:7],
                author=author,
                date=date,
                subject=subject or "(no message)",
            )
        )
    return commits


def repo_root(start: Path | None = None) -> Path | None:
    """Nearest ancestor containing a ``.git`` entry, or ``None``.

    Also true for a worktree or a submodule, where ``.git`` is a file.
    """
    here = (start or Path(__file__)).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _run_git(args: Iterable[str], cwd: Path) -> str | None:
    """Run one git command, returning ``None`` for any failure at all.

    Failure is expected in the container (no ``git`` binary), so it is not an
    error path to distinguish -- the caller falls back to the bundled artifact.
    """
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def collect_from_git(count: int = DEFAULT_COMMIT_COUNT, root: Path | None = None) -> BuildInfo:
    """Read the history out of a checkout. Returns *unavailable* if it cannot."""
    root = repo_root() if root is None else root
    if root is None:
        return BuildInfo.unavailable()

    log = _run_git(["log", f"-n{count}", f"--pretty=format:{GIT_FORMAT}"], root)
    if log is None:
        return BuildInfo.unavailable()
    commits = parse_git_log(log)
    if not commits:
        return BuildInfo.unavailable()

    head = (_run_git(["rev-parse", "HEAD"], root) or "").strip() or None
    status = _run_git(["status", "--porcelain"], root)
    return BuildInfo(
        source="git",
        generated_at=None,
        head=head,
        # A failed status check leaves this unknown rather than claiming clean.
        dirty=None if status is None else bool(status.strip()),
        commits=tuple(commits),
    )


def read_bundled(path: Path | None = None) -> BuildInfo | None:
    """Load the artifact baked in at image build time.

    Any problem -- missing, unreadable, wrong shape -- yields ``None`` so the
    caller can report an honest "unavailable" instead of a traceback in a page.
    """
    path = BUNDLED_PATH if path is None else path
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None

    commits = [Commit.from_dict(item) for item in raw.get("commits") or []]
    present = tuple(commit for commit in commits if commit is not None)
    if not present:
        return None

    generated_at = raw.get("generated_at")
    head = raw.get("head")
    dirty = raw.get("dirty")
    return BuildInfo(
        source="bundled",
        generated_at=generated_at if isinstance(generated_at, str) else None,
        head=head if isinstance(head, str) else None,
        dirty=dirty if isinstance(dirty, bool) else None,
        commits=present,
    )


def load_build_info(count: int = DEFAULT_COMMIT_COUNT) -> BuildInfo:
    """Provenance for display: the live checkout first, the baked artifact second.

    A checkout wins because it is the running code; the artifact exists for
    installs that have no checkout to read.
    """
    live = collect_from_git(count)
    if live.is_known:
        return live
    bundled = read_bundled()
    if bundled is None:
        return BuildInfo.unavailable()
    return bundled.limited(count)


def snapshot(
    path: Path, count: int = DEFAULT_COMMIT_COUNT, root: Path | None = None
) -> BuildInfo:
    """Write the artifact for a build to bake in, and return what was captured.

    The file is written even when nothing was captured, so a failed build leaves
    the evidence behind, but the caller is expected to treat an empty result as a
    failed build.
    """
    info = collect_from_git(count, root=root)
    payload: dict[str, Any] = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "head": info.head,
        "dirty": info.dirty,
        "commits": [commit.to_dict() for commit in info.commits],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m awltux.buildinfo",
        description="Record the git history so an installed copy can name its revision.",
    )
    parser.add_argument("-n", "--count", type=int, default=DEFAULT_COMMIT_COUNT)
    parser.add_argument("--write", type=Path, default=None, help="write the artifact here")
    parser.add_argument("--root", type=Path, default=None, help="repository root to read")
    args = parser.parse_args(argv)

    count = max(args.count, 1)
    if args.write is None:
        info = collect_from_git(count, root=args.root)
        print(json.dumps([commit.to_dict() for commit in info.commits], indent=2))
        return 0 if info.is_known else 1

    # --root is only there for testing and for building from somewhere other
    # than the checkout the module lives in; a Docker build needs neither.
    info = snapshot(args.write, count, root=args.root)

    if not info.is_known:
        print(
            f"error: no git history captured; {args.write} carries no commits, "
            "so the image could not name the revision it was built from",
            file=sys.stderr,
        )
        return 1

    dirty = " (tree was dirty)" if info.is_dirty else ""
    print(f"captured {len(info.commits)} commits at {info.head_short}{dirty} -> {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
