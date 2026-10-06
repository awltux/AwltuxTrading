"""Report where the code is hardest to change, so a refactor pass has a target.

Run from the repository root:

    python tools/refactor_report.py            # the whole tree
    python tools/refactor_report.py --diff      # only what is uncommitted

This is a *report*, not a gate. The gate is `ruff`, which knows one number
(complexity, `C90`) and fails the build when a function crosses it. What ruff cannot
see is the rest of the debt this stage exists to pay down: a function that is long
without branching, the same query written twice, a rule decided inside a route, a
literal whose reason is only in someone's head.

The thresholds below are deliberately lower than the point of failure. Complexity 15
fails the build; this prints from 10, because the useful moment to notice a function
is growing is while it is still small enough to split cheaply. A report that only
ever names functions already breaking the rule arrives too late to help.

Nothing here is authoritative about *whether* a function should be split. A flat
decision table and a tangle can score identically, and the codebase keeps four such
functions on purpose -- see the `noqa: C901` ledger printed at the end, and the
reason recorded against each.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCE = REPO / "src"

#: Report from here, even though the build only fails at
#: `[tool.ruff.lint.mccabe] max-complexity`. The gap is the point: it is a warning
#: with time to act on it.
REPORT_COMPLEXITY = 10

#: A rough eyeball limit, not a rule. Some functions are long because they are a
#: sequence of named steps, which is the readable form; this list is a place to
#: look, not a list of faults.
REPORT_LENGTH = 70

#: A section banner inside a comment block (`# ----- core`). Skipped when reading a
#: reason, because it belongs to the file's layout and not to the decision being
#: excused: read as part of the reason it answers the wrong question.
_BANNER = re.compile(r"^[-=~_*]{4,}")


def _functions(root: Path):
    """Every function in the tree, with its span and its branch count."""
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover - a broken file is ruff's job
            print(f"  could not parse {path}: {exc}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                yield path, node


def _span(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return (node.end_lineno or node.lineno) - node.lineno + 1


def _noqa_reason(path: Path, node: ast.FunctionDef) -> str:
    """The comment block written immediately above a `# noqa: C901` function.

    The reason is the whole value of the ledger. A bare `noqa` says "I gave up"; a
    reason says which rule was weighed and why the plain form won, which is the part
    a later reader needs and cannot reconstruct.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[node.lineno - 1] if node.lineno <= len(lines) else ""
    if "noqa: C901" not in header:
        return ""

    collected: list[str] = []
    index = node.lineno - 2
    while index >= 0 and lines[index].lstrip().startswith("#"):
        text = lines[index].strip().lstrip("#").strip()
        # A section banner (`# ---- core`) is a comment too, but it belongs to the
        # file's layout rather than to this decision, and reading it as part of the
        # reason turns "why is this excused" into "why is this section here".
        if text and not _BANNER.match(text):
            collected.append(text)
        index -= 1
    return " ".join(reversed(collected))


def _ruff_complexity() -> dict[str, int]:
    """Ask ruff for the complexity it measures, rather than measuring it again.

    A second implementation would eventually disagree with the one that fails the
    build, and the disagreement would be found by whoever trusted this report.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--output-format",
            "concise",
            "--ignore-noqa",  # excused functions are still worth seeing ranked
            "--select",
            "C90",
            "--config",
            f"lint.mccabe.max-complexity={REPORT_COMPLEXITY - 1}",
            "src",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    found: dict[str, int] = {}
    for line in completed.stdout.splitlines():
        # `src\awltux\decision\gate.py:172:5: C901 `evaluate` is too complex (22 > 9)`
        left, marker, right = line.partition(": C901 ")
        if not marker:
            continue
        where = left.rsplit(":", 2)[0].replace("\\", "/")
        name = right.partition("`")[2].partition("`")[0]
        score = right.rpartition("(")[2].partition(" >")[0].strip()
        if score.isdigit():
            found[f"{where}::{name}"] = int(score)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--diff",
        action="store_true",
        help="only files with uncommitted changes, for use inside a refactor pass",
    )
    args = parser.parse_args(argv)

    changed: set[str] | None = None
    if args.diff:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        changed = {
            line[3:].strip().replace("\\", "/")
            for line in completed.stdout.splitlines()
            if line.strip().endswith(".py")
        }
        if not changed:
            print("Nothing changed. The refactor pass has nothing of its own to review.")
            return 0

    complexity = _ruff_complexity()

    def selected(relative: str) -> bool:
        """Whether this file is in scope: all of `src`, or just the diff."""
        return changed is None or relative in changed

    long_functions: list[tuple[int, str]] = []
    for path, node in _functions(SOURCE):
        relative = path.resolve().relative_to(REPO).as_posix()
        if not selected(relative):
            continue
        span = _span(node)
        if span >= REPORT_LENGTH:
            long_functions.append((span, f"{relative}:{node.lineno} {node.name}"))
    long_functions.sort(reverse=True)

    print(f"=== functions over {REPORT_LENGTH} lines ===")
    if long_functions:
        for span, where in long_functions[:20]:
            print(f"{span:5d}  {where}")
    else:
        print("  none")

    print(f"\n=== complexity above {REPORT_COMPLEXITY} (build fails at 15) ===")
    scored = [
        (where, score)
        for where, score in sorted(complexity.items(), key=lambda item: -item[1])
        if selected(where.partition("::")[0])
    ]
    if scored:
        for where, score in scored[:20]:
            file, _, name = where.partition("::")
            print(f"{score:5d}  {file}::{name}")
    else:
        print("  none")

    print("\n=== noqa: C901 ledger -- this list only shrinks ===")
    entries = 0
    for path, node in _functions(SOURCE):
        reason = _noqa_reason(path, node)
        if reason:
            entries += 1
            print(f"  {path.relative_to(REPO)}:{node.lineno} {node.name}")
            print(f"      {reason}")
    if not entries:
        print("  empty -- every function is under the standard")

    print(
        f"\n{len(long_functions)} over {REPORT_LENGTH} lines, "
        f"{len(scored)} above complexity {REPORT_COMPLEXITY}, "
        f"{entries} excused (whole tree)."
    )
    print("Pick the one your diff touched. A refactor pass pays off its own change.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
