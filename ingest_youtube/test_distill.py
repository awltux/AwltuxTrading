"""Extraction state: what has been distilled, what has not, and what changed.

The failure these pin: the pipeline could not answer "which transcripts are fully
processed?" at all. `held_ids` knew what was *acquired*, and nothing knew what had been
*read* -- so every run re-extracted every transcript (measured: byte-identical output
across two runs), and the coverage report counted the ledger, which deliberately omits
the transcripts adopted from an earlier run, and so claimed one video held out of a
hundred while thirteen were on disk.

Run: `.venv/Scripts/python.exe -m pytest ingest_youtube/test_distill.py -q -p no:cacheprovider
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import distill  # noqa: E402
import report  # noqa: E402

SCRATCH = HERE / ".work"


@pytest.fixture()
def work() -> Path:
    path = SCRATCH / uuid.uuid4().hex[:12]
    (path / "transcripts").mkdir(parents=True)
    (path / "out").mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def write_transcript(root: Path, video_id: str, text: str, title: str = "") -> None:
    (root / "transcripts" / f"{video_id}.txt").write_text(text, encoding="utf-8")
    index_path = root / "transcripts" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    index[video_id] = {"id": video_id, "title": title}
    index_path.write_text(json.dumps(index), encoding="utf-8")


def method_text(marker: str) -> str:
    """Text that clears the method bar, with `marker` as its only variable part."""
    return " ".join(
        f"{marker} the discount rate and the cost of capital set the hurdle, "
        "and the free cash flow has to be matched to it"
        for _ in range(4)
    )


def round_trip(root: Path, previous: dict | None = None) -> dict:
    """What `run.py distill` does: read the last payload, extract, write."""
    payload = distill.distill_store(root, previous)
    (root / "out" / "candidates.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


# -- the watermark --------------------------------------------------------------


def test_a_transcript_is_extracted_once_and_then_skipped(work):
    """Unchanged input is not re-read. Measured as `extracted_this_run` on the second pass.

    The bug this prevents: re-doing settled work every run. It was invisible because the
    output was byte-identical, so the only way to see it is to count what was extracted.
    """
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    write_transcript(work, "bbbbbbbbbbb", method_text("second"))

    first = round_trip(work)
    assert first["extracted_this_run"] == 2
    assert first["already_extracted"] == 0

    second = round_trip(work, first)
    assert second["extracted_this_run"] == 0, "settled work was redone"
    assert second["already_extracted"] == 2
    assert [c["video_id"] for c in second["candidates"]] == [
        c["video_id"] for c in first["candidates"]
    ]


def test_a_changed_transcript_becomes_outstanding_again(work):
    """A revised transcript must be re-read, which a `done: true` flag could not notice."""
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    write_transcript(work, "bbbbbbbbbbb", method_text("second"))
    first = round_trip(work)

    write_transcript(work, "aaaaaaaaaaa", method_text("REVISED"))
    second = round_trip(work, first)

    assert second["outstanding"] == ["aaaaaaaaaaa"]
    assert second["already_extracted"] == 1


def test_a_new_transcript_is_picked_up_without_touching_the_others(work):
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    first = round_trip(work)
    write_transcript(work, "ccccccccccc", method_text("third"))
    second = round_trip(work, first)

    assert second["outstanding"] == ["ccccccccccc"]
    assert second["already_extracted"] == 1
    assert {c["video_id"] for c in second["candidates"]} == {"aaaaaaaaaaa", "ccccccccccc"}


def test_the_extractor_version_is_part_of_the_watermark(work):
    """A payload written by older rules leaves its transcripts outstanding.

    Kept separate from the content digest on purpose: this hash was once folded into
    the digest, which conflated "the rules changed" with "the text changed". They call
    for different responses, and one digest could not tell them apart.
    """
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    first = round_trip(work)
    assert round_trip(work, first)["already_extracted"] == 1

    first["extractor_version"] = first["extractor_version"] + 1
    again = round_trip(work, first)
    assert again["extracted_this_run"] == 1, "an extractor upgrade did not invalidate anything"
    assert again["restated_by_extractor"] == ["aaaaaaaaaaa"]
    assert again["changed_since_extraction"] == [], "a rule change is not a content change"


def test_an_edited_transcript_is_reported_as_changed_not_restated(work):
    """A transcript whose bytes differ is a different event from a rules upgrade."""
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    first = round_trip(work)
    write_transcript(work, "aaaaaaaaaaa", method_text("EDITED"))
    again = round_trip(work, first)

    assert again["changed_since_extraction"] == ["aaaaaaaaaaa"]
    assert again["restated_by_extractor"] == []


def test_force_re_extracts_everything(work):
    """The escape hatch, for when the watermark itself is suspected of being wrong."""
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    first = round_trip(work)
    forced = distill.distill_store(work, first, only_outstanding=False)
    assert forced["extracted_this_run"] == 1
    assert forced["already_extracted"] == 0


# -- the three states, in the report --------------------------------------------


def test_coverage_counts_the_store_not_the_ledger(work):
    """Acquisition is read from the transcripts on disk, never from the ledger.

    The bug: the ledger holds only what *this* fetcher requested, so the twelve
    transcripts adopted from an earlier run were invisible to a coverage table built on
    it -- reported as 0 acquired while 13 sat on disk.
    """
    for number, video_id in enumerate(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]):
        write_transcript(work, video_id, method_text(f"v{number}"))
    round_trip(work)

    table = report.coverage_table(work)
    assert "| **acquired** | transcripts on disk | **3** |" in table
    assert "| **extracted** | transcripts distilled | **3** |" in table
    # An empty ledger must not be read as "nothing acquired".
    assert "| requests | ledger entries (**not** the same as transcripts on disk) | 0 |" in table


def test_coverage_separates_held_from_distilled(work):
    """A transcript on disk with no extraction is held, not processed."""
    write_transcript(work, "aaaaaaaaaaa", method_text("first"))
    write_transcript(work, "bbbbbbbbbbb", method_text("second"))
    round_trip(work)
    write_transcript(work, "ccccccccccc", method_text("third"))

    table = report.coverage_table(work)
    assert "| **acquired** | transcripts on disk | **3** |" in table
    assert "| **extracted** | transcripts distilled | **2** |" in table
