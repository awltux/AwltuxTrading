"""A guard on what git is actually ignoring, and on the state of the TODO queue.

Written after a `.gitignore` pattern silently excluded nine of thirteen research
reports from version control. The failure was invisible in the way that matters:
`git status` reported a clean tree, because an ignored file is clean — clean
because ignored, not because committed. Two commits of mine claimed to add those
files and did not.

So this asserts the property directly rather than trusting the tree to look right.
The TODO checks at the end are the same idea applied to AGENTS.md section 6: the
file is a queue of outstanding work, and an item left in it after it was implemented
reads as work still owed.
"""

from __future__ import annotations

import re
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


def test_no_source_file_carries_mojibake() -> None:
    """Text decoded with the wrong codec and written back is unrecoverable.

    This happened: a PowerShell `Get-Content` (which reads as the ANSI code page) piped
    into `Set-Content -Encoding utf8` re-encoded every non-ASCII character, so an em
    dash became three characters and a black up-pointing triangle became a dagger. It
    was committed and deployed -- the pages rendered the damage -- and it was **lossy**:
    a stray C1 control character appeared where bytes could not round-trip, so no
    transform could put the file back.

    The guard is the same shape as the line-ending one above, and for the same reason:
    the damage is invisible to `git status`, survives review, and is only ever found by
    a person noticing that a page looks wrong. Edit text with a tool that writes UTF-8;
    never round-trip it through a shell that guesses the codec.

    Tracked files only. A generated file in the working tree with a BOM is not this
    repository's content, and failing on it would make the guard about the workspace
    rather than about what is committed.
    """
    suffixes = {".py", ".html", ".css", ".js", ".md", ".yaml", ".yml", ".toml", ".json"}
    # What a UTF-8 string looks like once its bytes have been read as cp1252. Written as
    # escapes, because a literal here would be the very thing this test forbids.
    markers = ("\u00e2\u20ac", "\u00c3\u00a2", "\u00c2\u00b7")
    tracked = _git("ls-files").stdout.split()

    offenders: list[str] = []
    for name in tracked:
        path = REPO / name
        if path.suffix not in suffixes or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Not valid UTF-8 is the same failure one step earlier.
            offenders.append(f"{name}: not valid UTF-8")
            continue
        if path.read_bytes().startswith(b"\xef\xbb\xbf"):
            offenders.append(f"{name}: has a UTF-8 BOM")
        if any(marker in text for marker in markers):
            offenders.append(f"{name}: contains cp1252-decoded UTF-8")

    assert not offenders, (
        "these committed files carry encoding damage, which no transform can undo:\n  "
        + "\n  ".join(offenders)
    )


def test_no_committed_text_carries_a_control_character() -> None:
    """The other half of the same failure, and the half nothing was checking.

    Found 2026-10-09 in `TODO.md`, committed and deployed: three literal `0x07` bytes where
    a replacement string's `\\a` escape had been interpreted instead of written, so
    `\\analysis` became BEL + "nalysis" and `\\reconciliation` became BEL + "econciliation" --
    the first letter of the word, silently gone. The mojibake guard above did not catch it
    because nothing was mis-decoded; the text was *shortened*, which no marker list can see.

    Tabs, newlines and carriage returns are excluded because they are ordinary in a
    repository that has CRLF files on a Windows checkout; every other C0 control, and DEL, is
    a sign that something interpreted an escape rather than copying the bytes.
    """
    allowed = {0x09, 0x0A, 0x0D}
    suffixes = {".py", ".html", ".css", ".js", ".md", ".yaml", ".yml", ".toml", ".json"}

    offenders: list[str] = []
    for name in _git("ls-files").stdout.split():
        path = REPO / name
        if path.suffix not in suffixes or not path.is_file():
            continue
        data = path.read_bytes()
        found = sorted(
            {
                byte
                for byte in data
                if (byte < 0x20 and byte not in allowed) or byte == 0x7F
            }
        )
        if found:
            offenders.append(
                f"{name}: " + ", ".join(f"0x{byte:02x}" for byte in found)
            )

    assert not offenders, (
        "these committed files carry control characters, which usually means an escape "
        "was interpreted by whatever wrote them:\n  " + "\n  ".join(offenders)
    )


def test_the_dockerfile_copies_the_line_ending_attributes() -> None:
    """The attribute only helps if it reaches the place the check runs.

    `git status` reads `.gitattributes` from the working tree, and the dirty-tree
    check runs in the builder stage, which copies an explicit list of paths rather
    than the whole repository. The attribute and the `COPY` are two halves of one
    invariant: with either missing, every image is branded a dirty build again and
    the Info page's warning goes back to meaning nothing.
    """
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY .gitattributes" in dockerfile, (
        "the builder stage must copy .gitattributes, or its `git status` has no "
        "text=auto and reports every CRLF file as modified"
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


def test_no_template_names_a_jinja_test_in_capitals() -> None:
    """Jinja's tests are lower-case: ``is none``, ``is true``, ``is defined``.

    A capitalised one is not a comparison, it is a lookup of a test that does not exist, and it
    raises ``TemplateRuntimeError: No test named 'None' found.`` -- at *render* time, and only on
    the branch it sits in. Reported 2026-10-25: `calibration?horizon=short_term` returned
    ``{"ok":false,"error":"TemplateRuntimeError"}`` while the long-term view was fine, because the
    broken expression sat inside a ``{% for %}`` whose table happened to be empty there. Two lines
    had been copied with ``is not None`` and the suite was green, because no test seeded a
    calibration row.

    So this is a source check: the page only fails when the loop has a row, which is exactly the
    state a test fixture is least likely to be in. Jinja comments and HTML comments are excluded --
    prose is allowed to capitalise a word.
    """
    templates = REPO / "src" / "awltux" / "web" / "templates"
    expression = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
    capitalised = re.compile(r"\bis\s+(?:not\s+)?([A-Z][A-Za-z_]*)")

    offences: list[str] = []
    for path in sorted(templates.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        for match in expression.finditer(source):
            for test in capitalised.finditer(match.group(0)):
                line = source.count("\n", 0, match.start() + test.start()) + 1
                offences.append(f"{path.relative_to(REPO)}:{line}: is {test.group(1)}")

    assert not offences, (
        "these name a Jinja test in capitals, which raises at render time and only on the branch "
        f"it sits in: {offences}"
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


# --------------------------------------------------------------------------- #
# TODO.md is a queue, not a graveyard -- AGENTS.md section 6
# --------------------------------------------------------------------------- #

#: The sections a TODO item may live under. A subset check, not equality: adding a
#: section is free, renaming one away from AGENTS.md is not.
TODO_SECTIONS = (
    "Bugs",
    "Correctness questions still open",
    "Operations",
    "Deliberately not doing",
)

#: How a completed item gets left behind instead of deleted. `git log -S` and
#: `git blame` are the record of what was done; the file is only what is still owed,
#: so a closed item costs the next reader the work of disproving it.
#:
#: Deliberately narrow. Two attempts to widen it produced false positives on
#: legitimate prose: "rather than **failing closed**" is a domain term, and
#: "**Done when:** a JEV key is configured" states an item's acceptance criterion.
#: A guard that makes people reword honest entries is worse than the drift it
#: prevents, so "fixed" and "resolved" are matched as closure clauses while "done",
#: "closed" and "completed" are only caught as a bold status lede, where they cannot
#: be anything else.
CLOSED_MARKERS = (
    r"- \[[xX]\]",  # a ticked checkbox
    r"~~\S.*?\S~~",  # struck through
    r"^\*\*(Fixed|Resolved|Completed|Implemented)\b",  # a status lede
    r"\b(is|are|was|were)\s+(now\s+)?(fixed|resolved)\b",  # "...are fixed."
)


def _todo_lines() -> list[str]:
    path = REPO / "TODO.md"
    if not path.exists():
        pytest.skip("TODO.md is not present")
    return path.read_text(encoding="utf-8").splitlines()


def _todo_items() -> list[tuple[int, str, list[str]]]:
    """Each `###` entry as ``(first line number, heading, its lines including it)``.

    The unit of the rule is an *entry*, which is why this is parsed rather than
    scanned line by line over the whole file. The preamble states the rule ("items
    are deleted when they are fixed") and the `## Bugs` narrative records what past
    fixes turned out to be, and both legitimately use the vocabulary a closed item
    would. Checking those would make the file's own explanation of its rule illegal.
    """
    items: list[tuple[int, str, list[str]]] = []
    current: tuple[int, str, list[str]] | None = None

    for number, line in enumerate(_todo_lines(), start=1):
        if line.startswith("### "):
            current = (number, line.strip(), [line])
            items.append(current)
        elif line.startswith("## "):
            current = None
        elif current is not None:
            current[2].append(line)

    return items


def test_no_todo_item_is_marked_closed() -> None:
    """Implementing an item deletes it, in the same commit.

    The rule is not merely style. A list that accumulates its finished entries stops
    being a list of what is owed, and the reader can no longer tell an open item from
    one that was dealt with a fortnight ago -- which is the only question the file
    exists to answer.

    The markers are narrow on purpose: this catches a status written *in place* -- a
    tick, a strikethrough, "**Fixed**", "... is fixed" -- and does not try to judge
    whether an entry's subject matter still holds. That is a reading task, and it is
    the reason the same section of AGENTS.md tells you to re-measure.
    """
    found: list[str] = []
    for number, _heading, lines in _todo_items():
        for offset, line in enumerate(lines):
            if any(re.search(marker, line) for marker in CLOSED_MARKERS):
                found.append(f"{number + offset}: {line.strip()}")

    assert not found, (
        "these TODO.md entries are marked as finished. Delete them instead -- the "
        "commit that implements an item is the record of it, and a queue that keeps "
        "its closed items is one nobody reads:\n  " + "\n  ".join(found)
    )


def test_every_todo_item_sits_under_a_known_section() -> None:
    """An entry with no section is one nobody will scan past.

    AGENTS.md names the sections; this asserts they still exist and that nothing has
    drifted out from under them.
    """
    sections: list[str] = []
    orphans: list[str] = []

    for number, line in enumerate(_todo_lines(), start=1):
        if line.startswith("## "):
            sections.append(line[3:].strip())
        elif line.startswith("### ") and not sections:
            orphans.append(f"{number}: {line.strip()}")

    assert not orphans, (
        "these TODO.md entries appear before any `##` section, so they are filed "
        "under nothing:\n  " + "\n  ".join(orphans)
    )

    missing = [name for name in TODO_SECTIONS if name not in sections]
    assert not missing, (
        f"AGENTS.md section 6 names these TODO.md sections and they are gone: {missing}. "
        f"Found instead: {sections}"
    )
