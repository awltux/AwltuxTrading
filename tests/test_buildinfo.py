"""Build provenance: reading the git history, and reading the baked artifact.

The point of this module is that an installed copy with no ``.git`` can still
name the commit it is running, and that it says "unknown" rather than inventing
an answer when it cannot. Both halves are tested here, plus the failure mode the
Docker build relies on: a snapshot with no commits must fail loudly instead of
producing an image whose provenance is silently blank.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from awltux import buildinfo
from awltux.buildinfo import FIELD, RECORD, BuildInfo, Commit, parse_git_log

REPO_ROOT = Path(__file__).resolve().parent.parent
HASH_A = "a" * 40
HASH_B = "b" * 40


def git_record(
    full: str,
    short: str,
    author: str,
    date: str,
    subject: str,
    *,
    leading_newline: bool = True,
) -> str:
    """One commit exactly as ``git log --pretty=format:`` emits it."""
    prefix = "\n" if leading_newline else ""
    return f"{prefix}{full}{FIELD}{short}{FIELD}{author}{FIELD}{date}{FIELD}{subject}{RECORD}"


class TestParseGitLog:
    def test_reads_every_field_of_every_record(self):
        text = git_record(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", "First", leading_newline=False)
        text += git_record(HASH_B, "bbbbbbb", "Grace", "2026-02-03T04:05:06+00:00", "Second")

        commits = parse_git_log(text)

        assert [commit.hash for commit in commits] == [HASH_A, HASH_B]
        assert commits[0] == Commit(
            hash=HASH_A,
            short_hash="aaaaaaa",
            author="Ada",
            date="2026-01-02T03:04:05+00:00",
            subject="First",
        )
        assert commits[1].author == "Grace"

    def test_a_subject_may_contain_anything_but_the_separators(self):
        subject = 'Fix "quotes", commas, | pipes and \u2014 em dashes'
        commits = parse_git_log(git_record(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", subject))
        assert commits[0].subject == subject

    def test_a_missing_message_is_not_rendered_as_blank(self):
        commits = parse_git_log(git_record(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", ""))
        assert commits[0].subject == "(no message)"

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "\n",
            f"{RECORD}\n{RECORD}",
            # Wrong field count: half a commit is not evidence of anything.
            f"{HASH_A}{FIELD}aaaaaaa{FIELD}Ada{RECORD}",
            # No hash at all.
            f"{FIELD}aaaaaaa{FIELD}Ada{FIELD}2026-01-02{FIELD}First{RECORD}",
        ],
    )
    def test_records_that_are_not_whole_commits_are_dropped(self, text):
        assert parse_git_log(text) == []


class TestCollectFromGit:
    def test_no_repository_is_unavailable_rather_than_empty(self, monkeypatch):
        monkeypatch.setattr(buildinfo, "repo_root", lambda *_, **__: None)
        info = buildinfo.collect_from_git()
        assert info.source == "unavailable"
        assert info.commits == ()
        assert not info.is_known

    def test_a_failing_git_command_is_unavailable(self, monkeypatch, temp_dir):
        """A ``.git`` this process cannot read is not an empty history."""
        monkeypatch.setattr(buildinfo, "_run_git", lambda *_, **__: None)
        info = buildinfo.collect_from_git(root=temp_dir)
        assert info.source == "unavailable"

    def test_reads_the_log_head_and_dirty_flag(self, monkeypatch, temp_dir):
        log = git_record(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", "First")

        def fake_run_git(args, cwd):
            if args[0] == "log":
                return log
            if args[0] == "rev-parse":
                return f"{HASH_A}\n"
            if args[0] == "status":
                return ""
            raise AssertionError(f"unexpected git command: {args}")

        monkeypatch.setattr(buildinfo, "_run_git", fake_run_git)
        info = buildinfo.collect_from_git(root=temp_dir)

        assert info.source == "git"
        assert info.head == HASH_A
        assert info.head_short == "aaaaaaa"
        assert info.dirty is False
        assert info.generated_at is None

    def test_a_failed_status_check_does_not_claim_a_clean_tree(self, monkeypatch, temp_dir):
        def fake_run_git(args, cwd):
            if args[0] == "log":
                return git_record(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", "First")
            if args[0] == "rev-parse":
                return HASH_A
            return None  # status failed

        monkeypatch.setattr(buildinfo, "_run_git", fake_run_git)
        info = buildinfo.collect_from_git(root=temp_dir)

        assert info.is_known
        assert info.dirty is None, "unknown is not the same as clean"
        assert info.is_dirty is False

    def test_this_checkout_reports_its_own_history(self):
        """The local-development path, against the real repository."""
        if buildinfo.repo_root(REPO_ROOT) is None or shutil.which("git") is None:
            pytest.skip("no git checkout available")
        info = buildinfo.collect_from_git(3, root=REPO_ROOT)
        assert len(info.commits) == 3
        assert info.head
        assert all(len(commit.hash) == 40 for commit in info.commits)


class TestBundledArtifact:
    def write(self, path: Path, **overrides) -> Path:
        payload = {
            "generated_at": "2026-03-04T05:06:07+00:00",
            "head": HASH_A,
            "dirty": False,
            "commits": [
                Commit(HASH_A, "aaaaaaa", "Ada", "2026-01-02T03:04:05+00:00", "First").to_dict(),
                Commit(HASH_B, "bbbbbbb", "Grace", "2026-02-03T04:05:06+00:00", "Second").to_dict(),
            ],
        }
        payload.update(overrides)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_a_written_artifact(self, temp_dir):
        info = buildinfo.read_bundled(self.write(temp_dir / "build_info.json"))
        assert info is not None
        assert info.source == "bundled"
        assert info.generated_at == "2026-03-04T05:06:07+00:00"
        assert [commit.subject for commit in info.commits] == ["First", "Second"]

    @pytest.mark.parametrize("content", ["", "not json", "[]", '{"commits": []}', '{"commits": [{}]}'])
    def test_anything_that_is_not_a_usable_artifact_is_none(self, temp_dir, content):
        path = temp_dir / "build_info.json"
        path.write_text(content, encoding="utf-8")
        assert buildinfo.read_bundled(path) is None

    def test_a_missing_artifact_is_none(self, temp_dir):
        assert buildinfo.read_bundled(temp_dir / "absent.json") is None

    def test_an_unknown_dirty_flag_stays_unknown(self, temp_dir):
        info = buildinfo.read_bundled(self.write(temp_dir / "b.json", dirty=None))
        assert info is not None
        assert info.dirty is None


class TestLoadBuildInfo:
    def test_the_live_checkout_wins_over_the_artifact(self, monkeypatch):
        live = BuildInfo("git", None, HASH_B, False, (Commit(HASH_B, "bbbbbbb", "x", "d", "live"),))
        monkeypatch.setattr(buildinfo, "collect_from_git", lambda *_, **__: live)
        monkeypatch.setattr(buildinfo, "read_bundled", lambda *_, **__: pytest.fail("should not be read"))
        assert buildinfo.load_build_info().source == "git"

    def test_the_artifact_is_used_when_there_is_no_checkout(self, monkeypatch, temp_dir):
        bundled = BuildInfo(
            "bundled", "2026-03-04T05:06:07+00:00", HASH_A, False,
            (Commit(HASH_A, "aaaaaaa", "Ada", "2026-01-02", "First"),),
        )
        monkeypatch.setattr(buildinfo, "collect_from_git", lambda *_, **__: BuildInfo.unavailable())
        monkeypatch.setattr(buildinfo, "read_bundled", lambda *_, **__: bundled)
        assert buildinfo.load_build_info(10) is bundled

    def test_neither_source_is_reported_as_unavailable(self, monkeypatch):
        monkeypatch.setattr(buildinfo, "collect_from_git", lambda *_, **__: BuildInfo.unavailable())
        monkeypatch.setattr(buildinfo, "read_bundled", lambda *_, **__: None)
        info = buildinfo.load_build_info()
        assert info.source == "unavailable"
        assert info.head_short is None

    def test_the_requested_number_of_commits_is_honoured(self, monkeypatch, temp_dir):
        commits = tuple(
            Commit(f"{n:040d}", f"{n:07d}", "Ada", "2026-01-02T03:04:05+00:00", f"# {n}")
            for n in range(1, 6)
        )
        bundled = BuildInfo("bundled", None, commits[0].hash, False, commits)
        monkeypatch.setattr(buildinfo, "collect_from_git", lambda *_, **__: BuildInfo.unavailable())
        monkeypatch.setattr(buildinfo, "read_bundled", lambda *_, **__: bundled)
        assert len(buildinfo.load_build_info(3).commits) == 3


class TestSnapshotAndCli:
    def test_snapshot_records_the_history_it_read(self, temp_dir):
        path = temp_dir / "build_info.json"
        info = buildinfo.snapshot(path, 2, root=REPO_ROOT)
        assert info.is_known, "the test checkout must have at least two commits"

        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["head"] == info.head
        assert written["dirty"] is False or written["dirty"] is True
        assert len(written["commits"]) == 2
        assert written["generated_at"]

    def test_the_artifact_survives_a_round_trip(self, temp_dir):
        path = temp_dir / "build_info.json"
        written = buildinfo.snapshot(path, 2, root=REPO_ROOT)
        read_back = buildinfo.read_bundled(path)
        assert read_back is not None
        assert read_back.commits == written.commits
        assert read_back.head == written.head

    def test_the_writer_exits_zero_when_it_captured_history(self, temp_dir, capsys):
        path = temp_dir / "build_info.json"
        assert buildinfo.main(["--write", str(path), "--root", str(REPO_ROOT), "-n", "2"]) == 0
        assert "captured 2 commits" in capsys.readouterr().out

    def test_the_writer_fails_a_build_that_cannot_name_its_revision(self, temp_dir, capsys):
        """The Docker build depends on this: no history must not ship a blank page."""
        path = temp_dir / "build_info.json"
        empty = temp_dir / "empty"

        code = buildinfo.main(["--write", str(path), "--root", str(empty)])

        assert code == 1
        assert "no git history captured" in capsys.readouterr().err
        # Written anyway, so a failed build leaves the evidence behind.
        assert path.exists()
        assert json.loads(path.read_text(encoding="utf-8"))["commits"] == []

    def test_without_write_it_prints_json(self, capsys):
        assert buildinfo.main(["-n", "1", "--root", str(REPO_ROOT)]) == 0
        printed = json.loads(capsys.readouterr().out)
        assert len(printed) == 1
        assert printed[0]["hash"]
