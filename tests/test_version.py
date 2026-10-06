"""The version is derived from a tag, and the copies in the tree cannot drift.

The scheme is ``INTERFACE_BREAKING_COUNT.RELEASE_COUNT.BUILD_COUNT_FOR_RELEASE``:
a release tag names the first two and the build derives the third from the commits
sitting on top of it. Before this, ``"0.1.0"`` was typed in **five** places --
``__init__.py``, ``pyproject.toml``, ``APP_VERSION`` in the decision service, the
``DecisionRun.app_version`` column default, and the compose image tag -- and no test
would have noticed them disagreeing.

That mattered most for the ledger: ``APP_VERSION`` is stamped on every decision row
so a later reader can tell whether the model or the code moved under them. Bumping
the page and forgetting the ledger would make that answer wrong silently, at the
point where it is supposed to be authoritative. So the tests below do two jobs:
prove the derivation, and assert that nothing in the tree holds its own copy.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from awltux import buildinfo, version
from awltux.version import (
    SOURCE_BUNDLED,
    SOURCE_GIT,
    SOURCE_PACKAGING,
    Version,
    parse_tag,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestTagParsing:
    @pytest.mark.parametrize(
        "tag,expected",
        [
            ("v2.5", (2, 5)),
            ("2.5", (2, 5)),
            ("v0.1", (0, 1)),
            ("v10.20", (10, 20)),
            # A full three-part tag is accepted, and its third component ignored:
            # the build count belongs to the build, and a tag cannot know it.
            ("v1.2.3", (1, 2)),
            (" v3.4 ", (3, 4)),
        ],
    )
    def test_a_release_tag_parses(self, tag, expected):
        assert parse_tag(tag) == expected

    @pytest.mark.parametrize(
        "tag", ["", "backup", "v", "v1", "v1.x", "release-2.5", "v1.2.3.4", "-1.2"]
    )
    def test_anything_else_is_refused_rather_than_guessed(self, tag):
        """A repository full of arbitrary tags must not silently produce a version.

        Returning `None` is what stops `wip` or `backup` becoming build 0 of release
        0, which would look exactly like a real release on the Info page.
        """
        assert parse_tag(tag) is None


class TestDerivingFromGit:
    """Simulated through `_git` rather than by building repositories, which is the
    pattern `test_buildinfo.py` already uses."""

    @pytest.fixture
    def fake_git(self, monkeypatch, temp_dir):
        def install(responses: dict[tuple[str, ...], str | None]):
            def fake(args, _root):
                return responses.get(tuple(args))

            monkeypatch.setattr(version, "_git", fake)
            monkeypatch.setattr(buildinfo, "repo_root", lambda *_, **__: temp_dir)
            return responses

        return install

    def test_the_commit_on_the_tag_is_build_zero(self, fake_git):
        fake_git({
            ("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"): "v2.5",
            ("rev-list", "--count", "v2.5..HEAD"): "0",
        })

        found = version.from_git()

        assert str(found) == "2.5.0"
        assert found.is_release, "the tagged commit is the release itself"
        assert found.tag == "v2.5"
        assert found.source == SOURCE_GIT

    def test_commits_after_the_tag_advance_the_build_count(self, fake_git):
        """This is what makes an untagged deployment identifiable: two images from
        the same release but different commits are different versions."""
        fake_git({
            ("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"): "v2.5",
            ("rev-list", "--count", "v2.5..HEAD"): "7",
        })

        found = version.from_git()

        assert str(found) == "2.5.7"
        assert not found.is_release

    def test_no_release_tag_is_labelled_untagged_rather_than_invented(self, fake_git):
        """A fabricated `0.0.0` would be indistinguishable from a real release."""
        fake_git({
            ("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"): None,
            ("rev-list", "--count", "HEAD"): "97",
        })

        found = version.from_git()

        assert str(found) == "0.0.97"
        assert found.source == "untagged"
        assert found.tag is None
        assert not found.is_release

    def test_a_tag_that_is_not_a_release_tag_yields_nothing(self, fake_git):
        """`v2.5-rc1` matched by describe is not a release, and saying so is better
        than deriving 2.5 from it."""
        fake_git({("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"): "v2.5-rc1"})

        assert version.from_git() is None

    def test_no_repository_yields_nothing(self, monkeypatch):
        monkeypatch.setattr(buildinfo, "repo_root", lambda *_, **__: None)

        assert version.from_git() is None

    def test_an_unreadable_distance_falls_back_to_build_zero(self, fake_git):
        """Better a release-tagged version with an uncertain build count than no
        version at all: the tag itself is the part a reader needs."""
        fake_git({
            ("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"): "v1.0",
            ("rev-list", "--count", "v1.0..HEAD"): None,
        })

        assert str(version.from_git()) == "1.0.0"


class TestTheBakedArtifact:
    def _write(self, path: Path, payload: dict) -> Path:
        target = path / "build_info.json"
        target.write_text(json.dumps(payload), encoding="utf-8")
        return target

    def test_the_baked_version_is_read(self, temp_dir):
        target = self._write(
            temp_dir, {"version": "3.4.12", "version_tag": "v3.4", "commits": []}
        )

        found = version.from_build_info(target)

        assert str(found) == "3.4.12"
        assert found.tag == "v3.4"
        assert found.source == SOURCE_BUNDLED

    def test_a_missing_artifact_is_not_an_error(self, temp_dir):
        """A source checkout has no baked file, and that is the normal case."""
        assert version.from_build_info(temp_dir / "absent.json") is None

    @pytest.mark.parametrize("stored", ["0.1", "1.2.3.4", "one.two.three", "", None, 12])
    def test_a_malformed_version_is_refused(self, temp_dir, stored):
        target = self._write(temp_dir, {"version": stored, "commits": []})

        assert version.from_build_info(target) is None

    def test_the_snapshot_bakes_the_version(self, temp_dir, monkeypatch):
        """The image build writes it, so an installed copy has no git to consult."""
        monkeypatch.setattr(buildinfo, "collect_from_git", lambda *_, **__: buildinfo.BuildInfo(
            source="git", generated_at=None, head="abc", dirty=False, commits=()
        ))
        monkeypatch.setattr(version, "from_git", lambda *_, **__: Version(4, 2, 9, tag="v4.2"))

        buildinfo.snapshot(temp_dir / "build_info.json")

        payload = json.loads((temp_dir / "build_info.json").read_text(encoding="utf-8"))
        assert payload["version"] == "4.2.9"
        assert payload["version_tag"] == "v4.2"

    def test_a_snapshot_without_git_still_writes_the_file(self, temp_dir, monkeypatch):
        """A failed build must leave its evidence behind rather than no file."""
        monkeypatch.setattr(
            buildinfo, "collect_from_git",
            lambda *_, **__: buildinfo.BuildInfo.unavailable(),
        )
        monkeypatch.setattr(version, "from_git", lambda *_, **__: None)

        buildinfo.snapshot(temp_dir / "build_info.json")

        payload = json.loads((temp_dir / "build_info.json").read_text(encoding="utf-8"))
        assert payload["version"] is None


class TestTheRoutesInOrder:
    def test_the_baked_artifact_is_preferred_over_git(self, monkeypatch):
        """An installed copy has no `.git`; a source checkout should use its own
        history. Both cannot win, so the order is asserted rather than assumed."""
        monkeypatch.setattr(version, "from_build_info", lambda *_, **__: Version(1, 0, 0))
        monkeypatch.setattr(
            version, "from_git", lambda *_, **__: pytest.fail("git should not be consulted")
        )
        version.current.cache_clear()

        try:
            assert str(version.current()) == "1.0.0"
        finally:
            version.current.cache_clear()

    def test_packaging_is_the_last_resort_and_says_so(self, monkeypatch):
        """It is the one route that can go stale, so it is labelled rather than
        passed off as a release."""
        monkeypatch.setattr(version, "from_build_info", lambda *_, **__: None)
        monkeypatch.setattr(version, "from_git", lambda *_, **__: None)
        monkeypatch.setattr(version, "from_packaging", lambda: Version(0, 1, 0, source=SOURCE_PACKAGING))
        version.current.cache_clear()

        try:
            found = version.current()
            assert found.source == SOURCE_PACKAGING
            assert "packaging" in version.describe()
        finally:
            version.current.cache_clear()


class TestNothingInTheTreeHoldsItsOwnCopy:
    """The five literals this module replaced, asserted gone.

    A test about drift is the only thing that catches drift: the previous version of
    this code had four copies of ``"0.1.0"`` and no test would have failed if one had
    been bumped and the others left.
    """

    def test_the_package_version_is_the_derived_one(self):
        import awltux

        assert awltux.__version__ == str(version.current())

    def test_the_ledger_stamps_the_derived_version(self):
        """`APP_VERSION` is written onto every decision row, so a copy here going
        stale makes the ledger's answer to "what produced this?" wrong."""
        from awltux.decision.service import APP_VERSION

        assert str(version.current()) == APP_VERSION

    def test_the_column_default_is_the_derived_version(self):
        """Read off the column, not off an instance.

        SQLAlchemy applies a column default at INSERT, so a freshly constructed
        ``DecisionRun()`` has ``app_version`` of ``None`` and asserting on it would
        test nothing. The default's callable is the thing that has to be right.
        """
        from awltux.db import DecisionRun

        default = DecisionRun.__table__.c.app_version.default
        assert default is not None, "the column lost its default"
        assert callable(default.arg), "a literal is back on the column"
        # SQLAlchemy wraps a callable default so it can pass an execution context;
        # the wrapped callable ignores it, which is the documented calling shape.
        assert default.arg(None) == str(version.current())

    def test_no_module_retains_a_hard_coded_app_version(self):
        """Searched rather than trusted: a re-added literal is exactly how this
        regresses, and it would look correct in every other test.

        Scoped to the names that must be derived. ``ENGINE_VERSION`` in
        ``analysis/valuation.py`` is deliberately *not* one of them -- it versions the
        valuation arithmetic on each ``ValuationRun``, so it moves when the formulas
        change rather than when the interface does. Flagging it would be a false
        positive that teaches the wrong lesson about what the app version means.
        """
        import re

        assigned = re.compile(
            r"""^(?P<name>__version__|APP_VERSION|VERSION)\s*=\s*['"]\d+\.\d+\.\d+['"]"""
        )
        offenders: list[str] = []
        for path in sorted((REPO_ROOT / "src").rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if assigned.match(line.strip()):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

        assert not offenders, (
            "the app version is typed in the tree again; it is derived from a git tag, "
            "so a literal here can silently disagree with every deployment:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_version_renders_as_three_integers(self):
        assert len(str(version.current()).split(".")) == 3
        assert str(version.current()).replace(".", "").isdigit()


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
class TestAgainstThisRepository:
    def test_the_live_checkout_derives_a_version(self):
        """The real one, so the simulated tests are not the only evidence."""
        found = version.from_git(REPO_ROOT)

        assert found is not None
        assert len(str(found).split(".")) == 3
