"""Locating a transcript: by video id, and by any URL that leads to it.

Written because a filename hashed from the download URL was proposed as the key. It was
not adopted, and these tests record why: the video id is already the URL's identity, and
a URL is *not* one value per video -- `watch?v=X&list=PL1` and `watch?v=X` are the same
video, while a playlist URL names a container that several videos share. What the
proposal was reaching for is kept: `url_key` makes a URL a lookup key for the file that
already exists, so a URL can be answered without a request.

Run: `.venv/Scripts/python.exe -m pytest ingest_youtube/test_locate.py -q -p no:cacheprovider
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
import fetch  # noqa: E402

SCRATCH = HERE / ".work"


@pytest.fixture()
def work() -> Path:
    path = SCRATCH / uuid.uuid4().hex[:12]
    (path / "transcripts").mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


VIDEO = "oFz94rZbc4c"

#: Every shape that leads to one video, plus two that lead to none.
SAME_VIDEO = [
    "https://www.youtube.com/watch?v=oFz94rZbc4c",
    "https://www.youtube.com/watch?v=oFz94rZbc4c&list=PLUkh9m2BorqlDJlnBXUaJaMRNE7UDckn6&index=4&t=930s",
    "https://www.youtube.com/watch?list=PLUkh9m2BorqlDJlnBXUaJaMRNE7UDckn6&v=oFz94rZbc4c",
    "https://youtu.be/oFz94rZbc4c",
    "https://youtu.be/oFz94rZbc4c?t=42",
    "https://www.youtube.com/shorts/oFz94rZbc4c",
    "https://www.youtube.com/embed/oFz94rZbc4c",
    "https://m.youtube.com/watch?v=oFz94rZbc4c&feature=share",
]

NO_VIDEO = [
    "https://www.youtube.com/playlist?list=PLUkh9m2BorqlDJlnBXUaJaMRNE7UDckn6",
    "https://www.youtube.com/@AswathDamodaranonValuation/videos",
    "",
]


@pytest.mark.parametrize("url", SAME_VIDEO)
def test_every_url_shape_for_one_video_gives_one_key(url):
    """Eight URLs, one key. The failure a raw-string hash would have: eight keys."""
    assert fetch.video_id_from_url(url) == VIDEO
    assert fetch.url_key(url) == fetch.url_key(SAME_VIDEO[0])


@pytest.mark.parametrize("url", NO_VIDEO)
def test_a_url_naming_no_video_has_no_key(url):
    """A playlist URL names a container. Inventing an id from it would key several
    videos to one name -- the reason a URL hash was rejected as the filename."""
    assert fetch.video_id_from_url(url) is None
    assert fetch.url_key(url) is None


def test_two_videos_do_not_share_a_key():
    a = fetch.url_key("https://www.youtube.com/watch?v=oFz94rZbc4c")
    b = fetch.url_key("https://www.youtube.com/watch?v=Eh5L52qcfnY")
    assert a and b and a != b


def test_an_indexed_url_resolves_to_the_file_on_disk(work):
    """The question the store could not answer: is this URL already downloaded?"""
    (work / "transcripts" / f"{VIDEO}.txt").write_text("x" * 500, encoding="utf-8")
    (work / "transcripts" / "index.json").write_text(
        json.dumps({VIDEO: {"id": VIDEO, "url": "https://www.youtube.com/watch?v=" + VIDEO,
                            "url_key": fetch.url_key("https://youtu.be/" + VIDEO)}}),
        encoding="utf-8",
    )
    by_url = fetch.url_index(work)
    assert by_url[fetch.url_key("https://www.youtube.com/watch?v=" + VIDEO)] == VIDEO
    assert VIDEO in fetch.held_ids(work)


def test_an_entry_without_a_url_is_skipped_not_guessed(work):
    """No URL, no key. Deriving one from the file name would be a guess."""
    (work / "transcripts" / "index.json").write_text(
        json.dumps({VIDEO: {"id": VIDEO, "title": "no url recorded"}}), encoding="utf-8"
    )
    assert fetch.url_index(work) == {}


def test_refresh_backfills_a_missing_key_from_the_url_already_recorded(work):
    """A field added after entries were written is invisible to them until backfilled.

    `url_index` derives its key from the recorded URL, so it always resolves; what
    `refresh_url_keys` does is *write the field down*, so the stored index and a URL
    lookup cannot disagree later. The test is therefore about the field appearing, not
    about lookup starting to work.
    """
    index = {VIDEO: {"id": VIDEO, "url": "https://www.youtube.com/watch?v=" + VIDEO}}
    (work / "transcripts" / "index.json").write_text(json.dumps(index), encoding="utf-8")

    assert "url_key" not in fetch.load_index(work)[VIDEO]
    assert fetch.refresh_url_keys(work) == 1
    assert fetch.load_index(work)[VIDEO]["url_key"] == fetch.url_key("https://youtu.be/" + VIDEO)
    assert fetch.refresh_url_keys(work) == 0, "a second pass should find nothing to do"


def test_refresh_leaves_an_entry_with_no_url_alone(work):
    """Nothing to derive a key from, so nothing is written -- no guessing."""
    (work / "transcripts" / "index.json").write_text(
        json.dumps({VIDEO: {"id": VIDEO, "title": "no url recorded"}}), encoding="utf-8"
    )
    assert fetch.refresh_url_keys(work) == 0
    assert "url_key" not in fetch.load_index(work)[VIDEO]


# -- integrity: is the file we hold the file we read? ----------------------------


def test_integrity_check_notices_a_damaged_transcript(work):
    """Present, counted as held, and the wrong bytes: the state that was undetectable.

    The measurement is the mismatch list: empty after extraction, containing the video
    once the file is truncated, empty again when it is restored.
    """
    (work / "transcripts" / f"{VIDEO}.txt").write_text("word " * 300, encoding="utf-8")
    (work / "transcripts" / "index.json").write_text(
        json.dumps({VIDEO: {"id": VIDEO, "url": "https://youtu.be/" + VIDEO}}), encoding="utf-8"
    )
    payload = distill.distill_store(work)
    assert distill.integrity_report(work, payload)["mismatched"] == []

    path = work / "transcripts" / f"{VIDEO}.txt"
    original = path.read_text(encoding="utf-8")
    path.write_text(original[:-200], encoding="utf-8")
    assert distill.integrity_report(work, payload)["mismatched"] == [VIDEO]

    path.write_text(original, encoding="utf-8")
    assert distill.integrity_report(work, payload)["mismatched"] == []


def test_integrity_check_reports_a_missing_file(work):
    payload = {"digests": {VIDEO: "0123456789abcdef"}}
    report = distill.integrity_report(work, payload)
    assert report == {"checked": 0, "mismatched": [VIDEO]}
