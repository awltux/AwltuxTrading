"""A guard on what git is actually ignoring.

Written after a `.gitignore` pattern silently excluded nine of thirteen research
reports from version control. The failure was invisible in the way that matters:
`git status` reported a clean tree, because an ignored file is clean — clean
because ignored, not because committed. Two commits of mine claimed to add those
files and did not.

So this asserts the property directly rather than trusting the tree to look right.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (REPO / ".git").exists(),
    reason="needs a git checkout",
)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(REPO), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


@pytest.mark.parametrize(
    "candidate",
    [
        # The one that broke: an unanchored `research/` pattern also matched
        # `docs/research/`, so the whole directory went untracked.
        "docs/investment-markers.md",
        "docs/research/accounting-quality-markers.md",
        "README.md",
        "TODO.md",
        "pyproject.toml",
        "Dockerfile",
        "src/awltux/cli.py",
        "tests/test_api.py",
    ],
)
def test_source_documents_are_not_ignored(candidate: str) -> None:
    path = REPO / candidate
    if not path.exists():
        pytest.skip(f"{candidate} is not present")

    result = _git("check-ignore", "-v", candidate)
    assert result.returncode != 0, (
        f"{candidate} is gitignored by: {result.stdout.strip()}\n"
        "A file that is ignored is invisible to `git add` and to `git status`, so "
        "this is how content gets silently lost."
    )


def test_line_endings_are_normalised_by_the_repository() -> None:
    """The container's dirty-tree check must not depend on the host's git config.

    `awltux.buildinfo` decides whether an image can be tied to a commit by asking
    `git status`, and the Docker build runs that inside a container with no
    `core.autocrlf`. On Windows, Git for Windows sets `core.autocrlf=true` in its
    *system* config -- not the repository's -- so CRLF files compare equal to LF
    blobs on the host and modified in the container. Six files did exactly that,
    which branded **every** image a dirty build however carefully the work was
    committed: the Info page printed the correct commit next to "has uncommitted
    changes", so the warning meant nothing.

    A `text=auto` attribute in the repository is what makes the comparison the same
    in both places, and `check-attr` is the only honest way to assert it -- reading
    `.gitattributes` by hand would not prove git applies it.
    """
    for candidate in (
        "src/awltux/cli.py",
        # One of the six that were CRLF on disk and LF in the commit.
        "src/awltux/analysis/news_analysis.py",
        "src/awltux/scheduler/dependencies.py",
    ):
        result = _git("check-attr", "text", candidate)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip().endswith("text: auto"), (
            f"{candidate} is not normalised by a repository attribute, so its "
            "line endings decide the dirty-tree check on whichever machine runs "
            f"it. git check-attr said: {result.stdout.strip()!r}"
        )


def test_the_research_reports_are_tracked() -> None:
    """Not merely present on disk — actually in the index."""
    on_disk = {path.name for path in (REPO / "docs" / "research").glob("*.md")}
    if not on_disk:
        pytest.skip("no research reports present")

    tracked = _git("ls-files", "docs/research").stdout.split()
    tracked_names = {Path(name).name for name in tracked}

    missing = on_disk - tracked_names
    assert not missing, (
        "these reports exist on disk but are not tracked by git, so a clone would "
        f"not contain them: {sorted(missing)}"
    )


def test_no_tracked_file_is_matched_by_an_ignore_pattern() -> None:
    """The invariant the unanchored `research/` rule actually broke.

    Not "anchor everything" — `__pycache__/` and `.venv/` are *meant* to match at
    any depth. The rule is narrower and checkable: a pattern must never match a
    file git is already tracking. Git keeps tracking such a file, so the damage is
    that nobody can see the pattern has started swallowing the tree.

    This is the assertion that would have caught it: four `docs/research/` files
    were already tracked when `research/` was added, and all four matched.
    """
    listed = _git("ls-files").stdout.splitlines()
    if not listed:
        pytest.skip("nothing tracked")

    # check-ignore reads paths on stdin and prints the ones that match.
    result = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "--stdin"],
        input="\n".join(listed),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    matched = [line for line in result.stdout.splitlines() if line.strip()]
    assert not matched, (
        "these tracked files are matched by .gitignore, which means an ignore "
        f"pattern has started covering real content: {matched[:10]}"
    )
