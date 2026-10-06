"""Rasterise the application icon into the files a browser asks for.

`src/awltux/web/static/icon.svg` is the design; everything else in that directory
is a downscale of it. Run from the repository root:

    python tools/render_icons.py

The outputs are committed rather than generated at build time. The application
serves its static files directly and has no asset pipeline of its own, so adding
one for six small files would be more machinery than the problem deserves -- but it
does mean this script is how they are *regenerated*, and that a size changed in the
SVG has to be re-rendered here rather than fixed in the PNG.

Requires two packages that are deliberately not runtime dependencies, because the
application never rasterises anything:

    pip install cairosvg pillow

`cairosvg` needs the cairo shared library, which is present on most Linux desktops
and is a one-line install on macOS. It is not needed to *use* the application.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "src" / "awltux" / "web" / "static"
SVG = STATIC / "icon.svg"

#: What each file is for. Keeping the reason beside the size is the only way to
#: know later whether a size can be dropped.
#:
#: There is deliberately no 192/512 pair here. Those exist for a web app manifest,
#: and this dashboard is bound to loopback and is not installable -- generating
#: them would leave two files nothing asks for, which is how a static directory
#: fills up with assets nobody can date or delete.
PNGS = {
    # iOS home screen. Apple asks for 180x180 and applies its own rounding, so
    # this one is drawn without transparency.
    "apple-touch-icon.png": 180,
    # The tab icon for browsers that will not take an SVG. 32 is what a modern
    # desktop tab uses; 16 is the legacy Windows fallback.
    "favicon-32.png": 32,
    "favicon-16.png": 16,
}

#: The sizes packed into favicon.ico. Windows picks the best fit from these.
ICO_SIZES = (16, 32, 48)


def main() -> int:
    try:
        import cairosvg
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - a missing dev tool, not a bug
        print(
            f"error: {exc.name} is required to render the icons.\n"
            "       pip install cairosvg pillow",
            file=sys.stderr,
        )
        return 1

    source = SVG.read_text(encoding="utf-8").encode("utf-8")

    for name, size in PNGS.items():
        target = STATIC / name
        cairosvg.svg2png(
            bytestring=source,
            write_to=str(target),
            output_width=size,
            output_height=size,
        )
        print(f"  {name:<24} {size}x{size}  {target.stat().st_size:>6} bytes")

    # The ICO is built by Pillow from the PNG already written, so every frame in it
    # is a downscale of the same drawing rather than a second interpretation of it.
    ico = STATIC / "favicon.ico"
    with Image.open(STATIC / "favicon-32.png") as image:
        image.convert("RGBA").save(ico, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"  {'favicon.ico':<24} {ICO_SIZES}  {ico.stat().st_size:>6} bytes")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
