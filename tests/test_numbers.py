"""The one rule for reading a number out of a provider's or a model's payload.

These pin a *policy* rather than an implementation. `as_finite_float` exists because the same
coercion was written six times under three different answers -- two modules rejected NaN and
kept infinity, two accepted both, and one rejected both -- so which answer a caller got
depended on which module it reached for, and nothing said so.

The last case guards the consolidation itself: a seventh private copy is how this comes back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from awltux.numbers import as_finite_float


class TestItReadsWhatIsThere:
    def test_a_number_is_returned_as_a_float(self):
        assert as_finite_float(3) == 3.0
        assert as_finite_float("3.5") == 3.5
        assert isinstance(as_finite_float("3.5"), float)

    def test_zero_and_a_negative_survive(self):
        """Zero is a reading, not an absence: the marker layer says nothing on an absent
        metric and something on a zero one, so collapsing the two loses a real answer."""
        assert as_finite_float(0) == 0.0
        assert as_finite_float("0") == 0.0
        assert as_finite_float("-0.5") == -0.5


class TestItRefusesWhatIsNotANumber:
    def test_nan_is_none(self):
        """What this prevents: `nan != nan`, so a NaN passes every filter written as
        `value == stored` and the row disappears from a comparison instead of looking
        wrong -- and it survives arithmetic into a ranking without ever raising."""
        assert as_finite_float(float("nan")) is None
        assert as_finite_float("nan") is None

    @pytest.mark.parametrize("infinity", ["inf", "-inf", float("inf"), float("-inf")])
    def test_infinity_is_none(self, infinity):
        """An infinity is not a large number, it is a broken one: it turns every ratio it
        reaches into another infinity and still formats like a figure."""
        assert as_finite_float(infinity) is None

    @pytest.mark.parametrize(
        "value", [None, "", "   ", "n/a", "—", {}, [], object()]
    )
    def test_something_unparseable_is_none(self, value):
        assert as_finite_float(value) is None


class TestThereIsOnlyOneCopy:
    def test_no_module_coerces_a_float_to_itself_again(self):
        """Every private `_as_float` and every inlined `number != number` was a second
        answer to the same question. A new one fails here rather than quietly restoring the
        divergence this consolidation removed."""
        source = Path(__file__).resolve().parent.parent / "src"
        offenders = []
        for path in sorted(source.rglob("*.py")):
            if path.name == "numbers.py":
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in ("def _as_float", "number != number", "number == number"):
                if pattern in text:
                    offenders.append(f"{path.relative_to(source)}: {pattern}")
        assert offenders == [], (
            "these reimplement awltux.numbers.as_finite_float: " + ", ".join(offenders)
        )
