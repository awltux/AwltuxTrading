"""The application icon and the favicon files a browser asks for.

The browser-facing half is easy to get wrong in a way nothing complains about: a
`<link>` pointing at a file that was never committed, or a set of sizes that drifted
away from the design because one PNG was edited by hand. Both render as a blank tab
icon, which nobody reports.

Everything here reads the files directly rather than going through an image library:
`cairosvg` and `Pillow` are used to *produce* these files and are deliberately not
dependencies of the application, so a test that needed them would be testing
something the deployment cannot run.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "src" / "awltux" / "web" / "static"
BASE_TEMPLATE = REPO / "src" / "awltux" / "web" / "templates" / "base.html"

#: Every file the page head asks for, and what it is for.
ICONS = (
    "icon.svg",
    "favicon.ico",
    "favicon-32.png",
    "favicon-16.png",
    "apple-touch-icon.png",
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class TestTheIconIsSquare:
    """The request was for a square icon, and it is a property of the drawing.

    A favicon is squashed or letter-boxed by the browser when the source is not
    square, which looks like a rendering fault rather than a design one.
    """

    def test_the_svg_viewbox_is_square(self):
        svg = (STATIC / "icon.svg").read_text(encoding="utf-8")
        viewbox = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
        assert viewbox, "the icon needs an explicit viewBox or it will not scale"
        width, height = (int(value) for value in viewbox.groups())
        assert width == height, f"the icon must be square, got {width}x{height}"

    def test_the_declared_width_and_height_match_the_viewbox(self):
        """A mismatched pair is what produces a stretched icon."""
        svg = (STATIC / "icon.svg").read_text(encoding="utf-8")
        width = int(re.search(r'\swidth="(\d+)"', svg).group(1))
        height = int(re.search(r'\sheight="(\d+)"', svg).group(1))
        assert width == height


class TestTheIconSetIsComplete:
    def test_every_referenced_file_exists_and_is_not_empty(self):
        for name in ICONS:
            path = STATIC / name
            assert path.exists(), f"{name} is referenced by the page but not committed"
            assert path.stat().st_size > 0, f"{name} is empty"

    def test_the_svg_is_the_design_and_the_rasters_are_named_for_their_size(self):
        """No size in the filename that the file does not have.

        The names are what a later reader trusts when deciding whether a size can be
        deleted, so a mismatch makes the set unattributable.
        """
        for name in ("favicon-16.png", "favicon-32.png"):
            size = int(re.search(r"-(\d+)\.png$", name).group(1))
            header = (STATIC / name).read_bytes()
            assert header.startswith(PNG_SIGNATURE), f"{name} is not a PNG"
            # IHDR width and height are big-endian 4-byte integers at offsets 16 and 20.
            width = int.from_bytes(header[16:20], "big")
            height = int.from_bytes(header[20:24], "big")
            assert (width, height) == (size, size), f"{name} is {width}x{height}"

    def test_the_ico_carries_more_than_one_size(self):
        """Windows picks a frame from the file; a single-size ICO defeats the point.

        Read from the header rather than through an image library: an ICO begins
        with a 6-byte directory, and the count is the third 16-bit field.
        """
        data = (STATIC / "favicon.ico").read_bytes()
        assert data[:4] == b"\x00\x00\x01\x00", "not an icon file"
        count = int.from_bytes(data[4:6], "little")
        assert count >= 2, f"the ICO carries {count} size(s); browsers need a choice"

    def test_no_file_in_the_set_is_an_orphan(self):
        """Every image in the directory is one the page asks for.

        A static directory accumulates assets nobody can date or delete, and an
        unreferenced icon is the easiest kind to leave behind.
        """
        present = {
            path.name
            for path in STATIC.iterdir()
            if path.is_file() and path.suffix.lower() in {".png", ".ico", ".svg"}
        }
        assert present == set(ICONS), f"unreferenced or missing: {present ^ set(ICONS)}"


class TestThePageDeclaresThem:
    def test_the_template_links_every_file(self):
        template = BASE_TEMPLATE.read_text(encoding="utf-8")
        for name in ICONS:
            assert f"/static/{name}" in template, f"base.html does not link {name}"

    def test_the_svg_is_offered_before_the_raster_fallbacks(self):
        """Preference order is how a browser chooses, so it is asserted, not assumed."""
        template = BASE_TEMPLATE.read_text(encoding="utf-8")
        svg = template.index('type="image/svg+xml"')
        ico = template.index('rel="icon" href="/static/favicon.ico"')
        assert svg < ico, "the scalable icon must be offered before the fixed one"

    def test_a_rendered_page_carries_the_links(self, client):
        body = client.get("/dashboard").text
        assert 'href="/static/icon.svg"' in body
        assert 'href="/static/favicon.ico"' in body

    def test_the_files_are_actually_served(self, client):
        """A link that 404s is the failure mode this whole file exists for."""
        for name in ICONS:
            response = client.get(f"/static/{name}")
            assert response.status_code == 200, name
            assert response.content, name


class TestItShipsInTheImage:
    def test_static_files_are_package_data(self):
        """The runtime image installs the package rather than copying `src/`.

        A new file under `static/` that is not covered by `package-data` would exist
        in the checkout and be missing from every deployment, so the icon would work
        locally and 404 in the container.
        """
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert "web/static/**/*" in pyproject, (
            "the icon is only in the image if static files are declared as package data"
        )
