"""The application version, derived from a git tag rather than typed.

    INTERFACE_BREAKING_COUNT . RELEASE_COUNT . BUILD_COUNT_FOR_RELEASE

**The tag is the source of truth.** A release tag is ``v<breaking>.<release>`` —
``v0.1``, ``v2.5`` — and the third component is whatever the build finds sitting on
top of it: the number of commits since that tag. Nothing anywhere is hand-typed, so
the five copies of ``"0.1.0"`` this module replaces cannot drift apart.

**What each component means, and when it moves.**

``INTERFACE_BREAKING_COUNT``
    Incremented when something a *consumer* depends on changes incompatibly. Here
    that means any of:
    the HTTP API's shape; the database schema in a way an old process could not
    tolerate; the configuration file's format; or the meaning of a field in the
    decision ledger. **Not** a change to the analysis, however large — a marker
    appearing or a threshold moving is a new release, not a broken interface,
    because a stored decision is still readable under the meaning it was written
    with.

``RELEASE_COUNT``
    Incremented for any release that a user would notice and no interface broke.
    New markers, a new page, a fixed bug, a changed default.

``BUILD_COUNT_FOR_RELEASE``
    Derived, never tagged. Commits since the release tag, so the very commit that
    carries the tag is build ``0`` and every commit after it is the next build of
    the same release. This is what makes an untagged deployment identifiable: two
    images built from the same release but different commits have different
    versions.

**Fallbacks, and why they announce themselves.** A source checkout has git; an
installed copy has the ``build_info.json`` the image build bakes in; a wheel
installed from a tarball has neither and falls back to the packaging metadata,
which is the one number here that can go stale. Rather than hide that,
:attr:`Version.source` records which route was taken and the Info page prints it —
``untagged`` or ``packaging`` on the page is a prompt to tag or rebuild, not a
detail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: A release tag: ``v2.5``. The leading ``v`` is optional, and a full three-part
#: tag is accepted so that ``git describe`` output pasted from elsewhere still
#: parses -- its third component is ignored, because the build count belongs to the
#: build and a tag cannot know it.
TAG_PATTERN = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")

#: Where a version can come from, worst to best. Recorded rather than inferred so
#: the page can say which one it used.
SOURCE_GIT = "git tag"
SOURCE_BUNDLED = "baked at build"
SOURCE_PACKAGING = "packaging metadata"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Version:
    """One version, three integers, and where it came from."""

    breaking: int
    release: int
    build: int
    source: str = SOURCE_UNKNOWN
    #: The tag the build count is measured from, when there is one.
    tag: str | None = None

    def __str__(self) -> str:
        return f"{self.breaking}.{self.release}.{self.build}"

    @property
    def is_release(self) -> bool:
        """Whether this commit is the tagged release itself, build ``0``."""
        return self.build == 0 and self.tag is not None

    def as_dict(self) -> dict[str, object]:
        return {
            "version": str(self),
            "breaking": self.breaking,
            "release": self.release,
            "build": self.build,
            "source": self.source,
            "tag": self.tag,
        }


def parse_tag(tag: str) -> tuple[int, int] | None:
    """``v2.5`` -> ``(2, 5)``. Anything else is not a release tag.

    Returning ``None`` rather than guessing is deliberate: a repository full of
    arbitrary tags (``backup``, ``wip``) must not silently produce a version.
    """
    match = TAG_PATTERN.match((tag or "").strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def version_from_parts(breaking: int, release: int, build: int, **kwargs) -> Version:
    """Guard against negative components, which no route should ever produce."""
    return Version(
        breaking=max(0, breaking), release=max(0, release), build=max(0, build), **kwargs
    )


# --------------------------------------------------------------------------- #
# the three routes
# --------------------------------------------------------------------------- #


def _git(args: list[str], root: Path) -> str | None:
    """Run git, returning stripped stdout or ``None``. Never raises."""
    import subprocess

    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def from_git(root: Path | None = None) -> Version | None:
    """Nearest reachable release tag, plus the commits sitting on top of it.

    ``git describe --tags --abbrev=0`` gives the closest tag that is an ancestor of
    HEAD, and ``rev-list --count`` gives the distance to it. A repository with no
    release tag at all yields ``None`` rather than a fabricated ``0.0.0`` -- the
    caller decides what to do about that, and :func:`current` says so on the page.
    """
    from awltux.buildinfo import repo_root

    base = root or repo_root()
    if base is None:
        return None

    tag = _git(["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], base)
    if tag is None:
        # No release tag reachable. Fall back to the total commit count so that an
        # untagged checkout is still distinguishable from another one, and label it
        # so nobody mistakes it for a release.
        total = _git(["rev-list", "--count", "HEAD"], base)
        if total is None or not total.isdigit():
            return None
        return version_from_parts(0, 0, int(total), source="untagged", tag=None)

    parts = parse_tag(tag)
    if parts is None:
        # A tag exists but is not a release tag -- `git describe` matched something
        # like `v2.5-rc1`. Say so rather than inventing a version from it.
        return None

    distance = _git(["rev-list", "--count", f"{tag}..HEAD"], base)
    build = int(distance) if distance and distance.isdigit() else 0
    return version_from_parts(*parts, build=build, source=SOURCE_GIT, tag=tag)


def from_build_info(path: Path | None = None) -> Version | None:
    """The version the image build baked in, if this is an installed copy.

    Read from the same ``build_info.json`` that carries the commit history, because
    both are facts about the build and splitting them across two files would let one
    be refreshed without the other.
    """
    import json

    from awltux.buildinfo import BUNDLED_PATH

    record = path or BUNDLED_PATH
    if not record.exists():
        return None
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None

    stored = payload.get("version")
    if not isinstance(stored, str):
        return None
    numbers = stored.split(".")
    if len(numbers) != 3 or not all(part.isdigit() for part in numbers):
        return None
    breaking, release, build = (int(part) for part in numbers)
    tag = payload.get("version_tag")
    return version_from_parts(
        breaking,
        release,
        build,
        source=SOURCE_BUNDLED,
        tag=tag if isinstance(tag, str) else None,
    )


def from_packaging() -> Version | None:
    """The last resort: the version in the installed package metadata.

    This is the one route that can go stale, because ``pyproject.toml`` is a static
    file while a tag is not. It exists so a wheel installed from a tarball -- no
    git, no baked file -- reports something rather than nothing, and
    :data:`SOURCE_PACKAGING` travels with it so the page can say which it was.
    """
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    try:
        stored = package_version("awltux-trading")
    except PackageNotFoundError:
        return None

    numbers = (stored or "").split(".")
    if len(numbers) != 3 or not all(part.isdigit() for part in numbers):
        return Version(0, 0, 0, source=SOURCE_PACKAGING, tag=None)
    return version_from_parts(*(int(part) for part in numbers), source=SOURCE_PACKAGING)


@lru_cache(maxsize=1)
def current() -> Version:
    """The running version, from the best route available.

    Cached because it is read on every request that renders the Info page and on
    every decision written, and none of the three routes can change while a process
    is alive.
    """
    for route in (from_build_info, from_git):
        found = route()
        if found is not None:
            return found
    return from_packaging() or Version(0, 0, 0, source=SOURCE_UNKNOWN, tag=None)


def describe() -> str:
    """One line for a log or a CLI, including how the number was arrived at."""
    found = current()
    tag = f" from {found.tag}" if found.tag else ""
    return f"{found} ({found.source}{tag})"
