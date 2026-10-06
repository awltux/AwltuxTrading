"""The refactor standard is enforced, not remembered.

Section 5 of `AGENTS.md` asks for a refactor pass on every change. A pass nobody can
fail is a pass nobody does: `pyproject.toml` selects `C90`, and these tests are what
keep that selection honest. Without them, deleting one string from `select` would turn
the whole standard back into prose, and nothing would say so.

The probe below is deliberately not a file in the tree. A committed file that must
fail the linter cannot be committed at all, so it is piped to ruff through stdin with
a filename that puts it inside the package -- which is what makes ruff apply the
project's configuration to it rather than its defaults.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "src"

#: The complexity a new function may not exceed. Mirrors
#: `[tool.ruff.lint.mccabe] max-complexity`; a test asserts the two still agree rather
#: than trusting that they do.
COMPLEXITY_CEILING = 15

#: How many functions are excused by name. A ratchet, not a target: lowering it means
#: refactoring one, raising it means arguing for one. Either is a decision, which is
#: the entire point -- the number cannot drift while nobody is looking.
MAX_EXCUSED = 4

#: 14 paths through a function is under the ceiling, so passing this would prove
#: nothing. This scores 18.
TANGLED = '''\
def tangled(a, b, c, d, e):
    if a:
        if b:
            if c:
                return 1
        elif d:
            return 2
    for _ in range(3):
        if e:
            if a and b:
                return 3
        elif c or d:
            return 4
    while a:
        if b:
            break
        if c:
            continue
    if d and e:
        return 5
    if a or not b:
        return 6
    if a:
        return 8
    if b:
        return 9
    if c:
        return 10
    if d:
        return 11
    return 7
'''

#: A section banner inside a comment block. Skipped when reading a reason: it belongs
#: to the file's layout rather than to the decision being excused.
_BANNER = re.compile(r"^[-=~_*]{4,}")

#: `src\awltux\gate.py:172:5: C901 ...` on any platform.
_RUFF_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+):\d+: C901")


def _ruff(source: str) -> subprocess.CompletedProcess[str]:
    """Lint a string as though it were `src/awltux/probe.py`, under the real config."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "concise",
            "--stdin-filename",
            "src/awltux/probe.py",
            "-",
        ],
        cwd=REPO,
        input=source,
        capture_output=True,
        text=True,
    )


def _config() -> dict:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))


def _over_ceiling() -> set[str]:
    """`path:line` for every function ruff scores above the ceiling.

    `--ignore-noqa` because the excused functions are precisely the ones suppressed
    from the ordinary run -- asking without it returns an empty set every time, which
    would make the staleness check below pass no matter what.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "concise",
            "--ignore-noqa",
            "--select",
            "C90",
            "src",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    found = set()
    for line in result.stdout.splitlines():
        match = _RUFF_LINE.match(line)
        if match:
            found.add(f"{match.group('path').replace(chr(92), '/')}:{match.group('line')}")
    return found


def _excused(root: Path | None = None) -> list[tuple[Path, int, str]]:
    """Every `# noqa: C901` under `root`, with the comment block above it."""
    found: list[tuple[Path, int, str]] = []
    for path in sorted((root or SOURCE).rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if "noqa: C901" not in line:
                continue

            reason: list[str] = []
            index = number - 2
            while index >= 0 and lines[index].lstrip().startswith("#"):
                text = lines[index].strip().lstrip("#").strip()
                if text and not _BANNER.match(text):
                    reason.append(text)
                index -= 1
            found.append((path, number, " ".join(reversed(reason))))
    return found


class TestTheGateIsSwitchedOn:
    def test_complexity_is_selected(self):
        """`select` containing `C90` is the whole enforcement.

        Ruff is happy to be configured with a ceiling it never applies, so a rewrite
        of this list -- or a typo in it -- silently retires the rule.
        """
        select = _config()["tool"]["ruff"]["lint"]["select"]
        assert "C90" in select, f"the complexity rule is no longer selected: {select}"

    def test_the_ceiling_matches_what_this_file_asserts(self):
        configured = _config()["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"]
        assert configured == COMPLEXITY_CEILING

    def test_a_newly_tangled_function_fails_the_build(self):
        """The regression this prevents: a gate that passes everything.

        Measured, not assumed -- ruff is asked about a function with 18 paths. If the
        rule, the selector or the ceiling were wrong, the probe would come back clean
        and this fails.
        """
        result = _ruff(TANGLED)

        assert result.returncode == 1, (
            "ruff accepted a function with 18 paths, so the complexity gate is not "
            f"being applied:\n{result.stdout}{result.stderr}"
        )
        assert "18 > 15" in result.stdout, result.stdout

    def test_a_function_under_the_ceiling_passes(self):
        """The other direction: a gate that fails everything is equally useless."""
        result = _ruff("def tidy(a):\n    return a\n")

        assert result.returncode == 0, result.stdout + result.stderr


class TestTheExcusedLedger:
    def test_it_only_shrinks(self):
        """A bare `noqa` that quietly becomes five, then ten, is how a standard dies."""
        excused = _excused()
        assert len(excused) <= MAX_EXCUSED, (
            f"{len(excused)} functions are excused from the complexity ceiling, more "
            f"than the {MAX_EXCUSED} on record. Refactor one, or raise MAX_EXCUSED "
            f"deliberately:\n"
            + "\n".join(f"  {p.relative_to(REPO)}:{n}" for p, n, _ in excused)
        )

    def test_every_excused_function_states_why(self):
        """The reason is the value of the ledger.

        A bare `noqa` says *I gave up*: it leaves the next reader unable to tell a
        deliberate exception from an oversight, and so unable to remove it. Every
        entry therefore argues its case in prose above the `def`.
        """
        silent = [
            f"{path.relative_to(REPO)}:{number}"
            for path, number, reason in _excused()
            if len(reason) < 40
        ]
        assert not silent, (
            "these functions are excused without a reason saying which rule was "
            "weighed and why the plain form won:\n  " + "\n  ".join(silent)
        )

    def test_the_excused_are_actually_over_the_ceiling(self):
        """A stale exception is debt nobody can see.

        Refactor a function below the ceiling and leave its `noqa` behind, and the
        ledger overstates the problem -- while the leftover silently lets that
        function grow complex again for free.
        """
        over = _over_ceiling()
        stale = [
            f"{path.relative_to(REPO)}:{number}"
            for path, number, _ in _excused()
            if f"{path.relative_to(REPO).as_posix()}:{number}" not in over
        ]
        assert not stale, (
            "these carry a `noqa: C901` that is no longer needed, so remove it and "
            "shrink the ledger:\n  " + "\n  ".join(stale)
        )


class TestTheReasonReader:
    """`_excused` is the measurement, so it has to be able to be wrong."""

    def _tree(self, tmp_path: Path, body: str) -> Path:
        module = tmp_path / "sample.py"
        module.write_text(body, encoding="utf-8")
        return tmp_path

    def test_it_reads_the_block_above_the_def(self, tmp_path):
        root = self._tree(
            tmp_path,
            "# The first line of the reason.\n"
            "# And the second, which together clear the length.\n"
            "def wide(  # noqa: C901\n"
            "    a,\n"
            "):\n"
            "    return a\n",
        )

        excused = _excused(root)

        assert len(excused) == 1
        _, _, reason = excused[0]
        assert reason.startswith("The first line of the reason.")
        assert "clear the length" in reason

    def test_a_bare_noqa_yields_no_reason(self, tmp_path):
        """Which is what `test_every_excused_function_states_why` rejects."""
        root = self._tree(tmp_path, "def wide(  # noqa: C901\n    a,\n):\n    return a\n")

        assert _excused(root)[0][2] == ""

    def test_a_section_banner_is_not_a_reason(self, tmp_path):
        """Or the ledger would report why a *section* exists, not why this is excused."""
        root = self._tree(
            tmp_path,
            "# ------------------------------------------------------------ core\n"
            "def wide(  # noqa: C901\n"
            "    a,\n"
            "):\n"
            "    return a\n",
        )

        assert _excused(root)[0][2] == ""


class TestTheReportTool:
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "tools/refactor_report.py", *args],
            cwd=REPO,
            capture_output=True,
            text=True,
        )

    def test_it_runs_and_shows_the_ledger(self):
        """`AGENTS.md` tells a session to run this, so it has to work.

        A documented command that crashes is worse than no command: the pass it
        belongs to gets skipped, and the reason is a stack trace nobody reads.
        """
        result = self._run()

        assert result.returncode == 0, result.stdout + result.stderr
        assert "noqa: C901 ledger" in result.stdout
        for path, _, _ in _excused():
            assert path.name in result.stdout, f"{path.name} missing from the report"

    def test_the_diff_view_reports_no_more_than_the_whole_tree(self):
        """The filter has to filter.

        `--diff` is what the pass actually runs, and a version that quietly ignored the
        `changed` set would report the whole tree while appearing to scope the work --
        the exact opposite of the pass's premise.
        """
        everything = re.search(r"(\d+) over \d+ lines", self._run().stdout)
        scoped = re.search(r"(\d+) over \d+ lines", self._run("--diff").stdout)

        assert everything, "the report no longer prints its summary line"
        # A clean tree short-circuits before the summary, which is also correct.
        if scoped:
            assert int(scoped.group(1)) <= int(everything.group(1)), (
                "--diff reported more functions than the whole tree, so the changed "
                "set is not being applied"
            )
