"""The shared HTTP layer: response cache, rate-limit budget and retry policy.

The cache had no test coverage at all, and it was broken in a way that only shows
up when a real request succeeds: :meth:`ResponseCache.key` returned
``provider/digest`` while the path helpers also inserted the provider as a
directory, so every write targeted ``cache/<provider>/<provider>/...`` and raised
``FileNotFoundError``. Nothing caught it because the only code paths that touch
:class:`HttpClient` are the ones that talk to real providers.

These tests pin the layout down, because a cache that silently never stores
anything is worse than no cache: it defeats the conditional-request logic that
protects the free-tier quotas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from awltux.providers.http import CachedResponse, ResponseCache, _parse_retry_after


@pytest.fixture
def cache(temp_dir: Path) -> ResponseCache:
    return ResponseCache(temp_dir / "cache", raw_root=temp_dir / "raw")


class TestKeyLayout:
    def test_the_key_does_not_repeat_the_provider(self, cache: ResponseCache):
        """The exact bug: the provider is a directory, not part of the filename."""
        key = ResponseCache.key("t212_exchanges", "https://example.test/x")
        assert "/" not in key
        assert "t212_exchanges" not in key

    def test_the_same_url_in_different_providers_gets_different_keys(self):
        a = ResponseCache.key("yahoo", "https://example.test/x")
        b = ResponseCache.key("stooq", "https://example.test/x")
        assert a != b

    def test_the_same_url_in_the_same_provider_is_stable(self):
        first = ResponseCache.key("yahoo", "https://example.test/x")
        second = ResponseCache.key("yahoo", "https://example.test/x")
        assert first == second

    def test_different_urls_get_different_keys(self):
        assert ResponseCache.key("yahoo", "https://example.test/a") != ResponseCache.key(
            "yahoo", "https://example.test/b"
        )

    def test_different_params_get_different_keys(self):
        """The bug that made `uk_companies` report `matched=0` for eight runs.

        The URL handed to `key` is the *path* -- `params` travels separately to httpx --
        so before this every request to `/search/companies` shared one entry, and the
        first company name searched answered for all of them for 24 hours.
        """
        companies_house = "https://api.company-information.service.gov.uk/search/companies"

        hays = ResponseCache.key("companies_house", companies_house, {"q": "Hays"})
        morgan = ResponseCache.key("companies_house", companies_house, {"q": "Morgan Sindall"})

        assert hays != morgan

    def test_the_order_of_params_does_not_change_the_key(self):
        """Two spellings of one query are one request, or the cache misses half the
        time and doubles the provider traffic it exists to halve."""
        url = "https://example.test/search"
        first = ResponseCache.key("x", url, {"q": "a", "limit": 20})
        second = ResponseCache.key("x", url, {"limit": 20, "q": "a"})

        assert first == second

    def test_no_params_still_keys_on_the_url_alone(self):
        """Unchanged for the callers that pass none, so their entries survive."""
        url = "https://example.test/x"
        assert ResponseCache.key("x", url) == ResponseCache.key("x", url, None)
        assert ResponseCache.key("x", url) == ResponseCache.key("x", url, {})

    def test_a_value_cannot_impersonate_two_parameters(self):
        """The pairs are urlencoded, so a value containing `&` or `=` stays one value."""
        url = "https://example.test/x"
        sneaky = ResponseCache.key("x", url, {"q": "a&b=1"})
        split = ResponseCache.key("x", url, {"q": "a", "b": "1"})

        assert sneaky != split


class TestRoundTrip:
    def test_a_write_can_be_read_back(self, cache: ResponseCache):
        key = ResponseCache.key("t212_exchanges", "https://example.test/exchanges")
        response = CachedResponse(
            url="https://example.test/exchanges",
            status=200,
            body=b'[{"id": 1}]',
            headers={"etag": 'W/"abc"'},
            fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        )

        cache.write("t212_exchanges", key, response)
        restored = cache.read("t212_exchanges", key)

        assert restored is not None
        assert restored.status == 200
        assert restored.body == b'[{"id": 1}]'
        assert restored.headers["etag"] == 'W/"abc"'

    def test_the_file_lands_under_a_single_provider_directory(
        self, cache: ResponseCache, temp_dir: Path
    ):
        """Guards the layout that regressed, not just the round trip."""
        key = ResponseCache.key("edgar", "https://example.test/a")
        cache.write(
            "edgar",
            key,
            CachedResponse(
                url="https://example.test/a",
                status=200,
                body=b"{}",
                headers={},
                fetched_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            ),
        )

        body = temp_dir / "cache" / "edgar" / f"{key}.body"
        assert body.is_file()
        # And specifically not a doubled directory.
        assert not (temp_dir / "cache" / "edgar" / "edgar").exists()

    def test_a_missing_entry_reads_as_none(self, cache: ResponseCache):
        assert cache.read("edgar", "0123456789abcdef") is None

    def test_a_corrupt_metadata_file_is_discarded_not_raised(
        self, cache: ResponseCache, temp_dir: Path
    ):
        """A half-written cache entry must degrade to a cache miss."""
        key = ResponseCache.key("edgar", "https://example.test/a")
        directory = temp_dir / "cache" / "edgar"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{key}.body").write_bytes(b"{}")
        (directory / f"{key}.json").write_text("{not json", encoding="utf-8")

        assert cache.read("edgar", key) is None


class TestFreshness:
    def test_a_recent_entry_is_fresh(self, cache: ResponseCache):
        import datetime as dt

        entry = CachedResponse(
            url="x",
            status=200,
            body=b"",
            headers={},
            fetched_at=dt.datetime.now(dt.UTC),
        )
        assert cache.is_fresh(entry, 3600) is True

    def test_an_old_entry_is_not_fresh(self, cache: ResponseCache):
        import datetime as dt

        entry = CachedResponse(
            url="x",
            status=200,
            body=b"",
            headers={},
            fetched_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=2),
        )
        assert cache.is_fresh(entry, 3600) is False

    def test_a_naive_timestamp_is_treated_as_utc(self, cache: ResponseCache):
        """SQLite and JSON round-trips can drop tzinfo; that must not crash."""
        import datetime as dt

        entry = CachedResponse(
            url="x",
            status=200,
            body=b"",
            headers={},
            fetched_at=dt.datetime.now(dt.UTC).replace(tzinfo=None),
        )
        assert cache.is_fresh(entry, 3600) is True


class TestArchive:
    def test_raw_payloads_are_written_under_a_dated_directory(
        self, cache: ResponseCache, temp_dir: Path
    ):
        import datetime as dt

        day = dt.date(2026, 2, 3)
        path = cache.archive("edgar", "submissions.json", b'{"cik": 1}', day=day)
        assert path.is_file()
        assert path.read_bytes() == b'{"cik": 1}'
        assert "2026-02-03" in str(path)

    def test_a_dangerous_filename_cannot_escape_its_directory(
        self, cache: ResponseCache, temp_dir: Path
    ):
        """Filenames come from URLs, so traversal must be impossible.

        The separators become ``_``, which is what actually contains it -- the
        property worth asserting is that the result stays inside the dated
        directory, not that the string is free of dots.
        """
        raw_root = temp_dir / "raw"
        path = cache.archive("edgar", "../../etc/passwd", b"x")

        assert path.is_file()
        assert path.resolve().is_relative_to(raw_root.resolve())
        assert path.parent.parent == raw_root / "edgar"

    def test_a_name_of_only_dots_is_replaced(self, cache: ResponseCache):
        """``..`` would resolve to the parent directory if it were kept as-is."""
        path = cache.archive("edgar", "..", b"x")
        assert path.is_file()
        assert path.name == "payload"

    def test_text_payloads_are_supported(self, cache: ResponseCache):
        path = cache.archive("sec", "page.html", "<html></html>")
        assert path.read_text(encoding="utf-8") == "<html></html>"


class TestRetryAfter:
    def test_seconds_form(self):
        assert _parse_retry_after("30") == pytest.approx(30.0)

    def test_missing_value(self):
        assert _parse_retry_after(None) is None

    def test_garbage_value(self):
        assert _parse_retry_after("not-a-date") is None

    def test_http_date_form(self):
        import datetime as dt
        from email.utils import format_datetime

        future = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=45)
        parsed = _parse_retry_after(format_datetime(future))
        assert parsed is not None and 30 < parsed <= 46

    def test_a_past_http_date_clamps_to_zero(self):
        import datetime as dt
        from email.utils import format_datetime

        past = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=60)
        assert _parse_retry_after(format_datetime(past)) == pytest.approx(0.0)
