"""The dashboard's text is readable: every foreground clears WCAG 2.2 AA on its surface.

The failure this prevents is not a crash. It is a stylesheet whose *comment* claims a
contrast floor that nothing enforces, which is how `--chip-tint` at `.2` shipped with
the `sell` chip measuring **4.45:1** -- under the 4.5:1 floor the change existed to
clear -- while the comment beside it read "all above 5.5:1". A chip is text in a hue
on a translucent wash of the *same* hue, so raising the wash alpha moves the
background toward the text and *lowers* the ratio; the intuitive fix makes it worse,
and nothing in the suite noticed.

So the property is asserted against the file that actually ships, and the numbers are
computed from the declared palette rather than restated here. A test that hardcoded
"5.16" would agree with the comment instead of with the stylesheet.

Rewriting `:root`, brightening a wash, or adding a chip colour with too little
headroom fails these, with the measured ratio in the message.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
STYLESHEET = REPO / "src" / "awltux" / "web" / "static" / "style.css"

#: WCAG 2.2 AA for body text, and AAA, which is the target for the small grey text
#: that carries most of this interface's labels and captions.
AA = 4.5
AAA = 7.0


def _channel(value: float) -> float:
    """One sRGB channel, linearised as WCAG defines it."""
    value = value / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    text = hex_colour.lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    r, g, b = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    """The WCAG contrast ratio between two opaque colours."""
    a, b = luminance(fg), luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def composite(fg: str, alpha: float, bg: str) -> str:
    """`fg` at `alpha` over `bg`, as the opaque colour the eye actually receives.

    A translucent chip is not read against the panel -- it is read against itself at
    that alpha, which is why this exists rather than a plain `contrast(fg, panel)`.
    """
    text, under = fg.lstrip("#"), bg.lstrip("#")
    channels = [
        round(int(text[i : i + 2], 16) * alpha + int(under[i : i + 2], 16) * (1 - alpha))
        for i in (0, 2, 4)
    ]
    return f"#{channels[0]:02x}{channels[1]:02x}{channels[2]:02x}"


def _stylesheet() -> str:
    assert STYLESHEET.exists(), f"missing stylesheet at {STYLESHEET}"
    return STYLESHEET.read_text(encoding="utf-8")


def _root_block(css: str) -> str:
    match = re.search(r":root\s*\{(.*?)\}", css, re.S)
    assert match, "style.css has no :root block to read the palette from"
    return match.group(1)


def palette() -> dict[str, str]:
    """Every custom property declared in `:root`, by name."""
    return {
        name: value.strip()
        for name, value in re.findall(r"--([\w-]+):\s*([^;]+);", _root_block(_stylesheet()))
    }


def _hex_or_fail(name: str, value: str) -> str:
    assert re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value), (
        f"--{name} is {value!r}; these checks need a hex colour to measure"
    )
    return value


#: The surfaces text is rendered on, worst (lightest) last. `--panel-2` is the lightest
#: of the backgrounds, so it is the binding case for anything drawn on all three.
SURFACE_NAMES = ("bg", "panel", "panel-2")


def surfaces() -> dict[str, str]:
    props = palette()
    missing = [name for name in SURFACE_NAMES if name not in props]
    assert not missing, f"style.css no longer declares these surfaces: {missing}"
    return {name: _hex_or_fail(name, props[name]) for name in SURFACE_NAMES}


#: Palette entries that are used as text, and the floor each must clear. `--line` is
#: absent on purpose: it draws borders and is never read as a foreground.
TEXT_TARGETS = {
    "fg": AA,
    "muted": AAA,
    "good": AA,
    "bad": AA,
    "warn": AA,
    "link": AA,
    "buy": AA,
    "sell": AA,
    "hold": AA,
}


class TestPaletteTextClearsTheFloor:
    """Every colour the interface uses for text, on every surface it can appear on."""

    @pytest.mark.parametrize("name", sorted(TEXT_TARGETS))
    def test_each_text_colour_clears_its_floor_on_every_surface(self, name: str) -> None:
        props = palette()
        assert name in props, f"--{name} is gone from :root"
        colour = _hex_or_fail(name, props[name])
        target = TEXT_TARGETS[name]

        for surface_name, surface in surfaces().items():
            ratio = contrast(colour, surface)
            assert ratio >= target, (
                f"--{name} ({colour}) on --{surface_name} ({surface}) is {ratio:.2f}:1, "
                f"below the {target}:1 this stylesheet claims"
            )


class TestBadgeTextClearsTheFloorOnItsOwnWash:
    """The chips, measured against their own translucent background, not the panel."""

    #: `.badge.x { background: rgba(r,g,b,<alpha>); color: var(--y); }` -- the alpha
    #: may be the shared `--chip-tint` or a literal, and both are resolved below so
    #: either form is measured rather than assumed.
    _RULE = re.compile(r"\.badge(?:\.(?P<variant>[\w-]+))?\s*\{(?P<body>[^}]*)\}")
    _WASH = re.compile(
        r"background:\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*"
        r"(var\(--[\w-]+\)|[\d.]+)\s*\)"
    )

    def _chip_rules(self) -> list[tuple[str, str, float]]:
        props = palette()
        found: list[tuple[str, str, float]] = []

        for match in self._RULE.finditer(_stylesheet()):
            body = match.group("body")
            background = self._WASH.search(body)
            colour = re.search(r"color:\s*(var\(--[\w-]+\)|#[0-9a-fA-F]{3,6})", body)
            if not background or not colour:
                continue

            alpha_raw = background.group(4).strip()
            var = re.fullmatch(r"var\(--([\w-]+)\)", alpha_raw)
            if var:
                assert var.group(1) in props, f"--{var.group(1)} is not declared"
                alpha_raw = props[var.group(1)]
            alpha = float(alpha_raw)
            assert 0 < alpha <= 1, f"alpha {alpha} is not a usable wash"

            raw_colour = colour.group(1)
            colour_var = re.fullmatch(r"var\(--([\w-]+)\)", raw_colour)
            variant = match.group("variant") or "(base)"
            assert colour_var is None or colour_var.group(1) in props, (
                f".badge.{variant} uses undeclared {raw_colour}"
            )
            text = props[colour_var.group(1)] if colour_var else raw_colour

            found.append((variant, _hex_or_fail(f"badge.{variant}", text), alpha))

        return found

    def test_it_finds_the_chips_it_is_supposed_to_measure(self) -> None:
        """A regex that stopped matching would make every check below vacuous."""
        variants = {variant for variant, _, _ in self._chip_rules()}
        assert {"buy", "sell", "hold", "avoid", "unknown"} <= variants, (
            f"expected the verdict chips, found {sorted(variants)}"
        )

    def test_every_translucent_chip_clears_aa_on_the_worst_surface(self) -> None:
        rules = self._chip_rules()
        assert rules, "no translucent .badge rule found to measure"

        # The wash is drawn on the panel or inside a panel-2 card; panel-2 is lighter,
        # so it is the worse case and the one that binds.
        worst_surface = surfaces()["panel-2"]

        failures = []
        for variant, text, alpha in rules:
            chip = composite(text, alpha, worst_surface)
            ratio = contrast(text, chip)
            if ratio < AA:
                failures.append(f".badge.{variant}: {text} on its {alpha} wash ({chip}) is {ratio:.2f}:1")

        assert not failures, (
            f"badge text is below the {AA}:1 floor on --panel-2 -- a chip is text on a wash "
            "of its own hue, so *lower* the wash alpha (--chip-tint) to raise the ratio, "
            "not higher:\n  " + "\n  ".join(failures)
        )


class TestTheSharedWashIsTheSingleSource:
    """One alpha for every chip, which is the reason there is only one to measure."""

    def test_the_wash_alpha_is_declared_once_and_used_everywhere(self) -> None:
        css = _stylesheet()
        props = palette()
        assert "chip-tint" in props, "--chip-tint is gone; the chip washes are literals again"

        literal_washes = re.findall(r"\.badge[^{]*\{[^}]*background:\s*rgba\([^)]*?,\s*(0?\.\d+)\s*\)", css)
        assert not literal_washes, (
            "these chip washes hardcode an alpha instead of using --chip-tint, so the "
            f"measured floor no longer covers them: {literal_washes}"
        )

        # The base `.badge` rule paints an opaque panel, which is not a wash.
        assert "var(--chip-tint)" in css, "--chip-tint is declared but never used"
