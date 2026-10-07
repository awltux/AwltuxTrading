"""The dashboard's chart script: every drawing path runs, and reads the stylesheet.

`app.js` had no test at all, and the gap was not theoretical. Moving the palette into a
cache put `muted` in `drawChart`'s scope while `drawEmptyChart` -- reached only when an
instrument has fewer than two stored bars -- still referenced it. The lone-point branch
is exactly the kind of path a normal page never takes: the instrument page has a full
series, so it drew correctly while the one-bar case would have thrown `ReferenceError`
and left a blank canvas. Nothing here is served by the browser, so `node --check`
passing is the only signal a script gives today, and it does not see a free variable.

`test_stylesheet_contrast.py` covers what the stylesheet *declares*; this covers what
the script *does* with it. The script is run under a stub DOM by
`tools/chart_harness.js`, which records the canvas calls, so the assertions can be
about the colours and font sizes actually drawn rather than about the source text.

Skipped when node is absent, the same way `test_repo_hygiene.py` skips without git:
the checkout is not a JavaScript project, so node is a tool this test borrows rather
than a dependency the application has.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "tools" / "chart_harness.js"
SCRIPT = REPO / "src" / "awltux" / "web" / "static" / "app.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="needs node to run the dashboard's client-side script",
)


def _run_harness() -> str:
    result = subprocess.run(
        ["node", str(HARNESS)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(REPO),
    )
    assert result.returncode == 0, (
        "the chart harness failed -- a drawing path threw, or it stopped reading the "
        f"stylesheet:\n{result.stdout}\n{result.stderr}"
    )
    return result.stdout


class TestTheChartScriptIsExercised:
    """The harness itself, and the two files it depends on."""

    def test_the_files_it_runs_exist(self) -> None:
        assert SCRIPT.exists(), f"missing {SCRIPT}"
        assert HARNESS.exists(), f"missing {HARNESS}"

    def test_every_drawing_path_completes(self) -> None:
        """The measurement: the lone-point branch is drawn, not merely parsed."""
        output = _run_harness()
        assert "All chart paths drew without throwing." in output, output

    def test_it_reports_each_shape_it_claims_to_cover(self) -> None:
        """A harness that silently stopped covering a path would still exit zero."""
        output = _run_harness()
        for shape in ("no stored bars", "one stored bar", "a real series"):
            assert f"ok    {shape}" in output, f"{shape!r} is no longer covered:\n{output}"


class TestTheScriptReadsTheStylesheet:
    """The chart's colours and type come from CSS, not from literals in the script.

    The regression this guards: the axis labels were the one place the palette and the
    font size were typed twice, so when the interface's text was enlarged and its greys
    brightened the chart kept drawing 11px in the old grey.
    """

    def test_every_check_the_harness_makes_passes(self) -> None:
        output = _run_harness()
        assert "FAIL" not in output, output
