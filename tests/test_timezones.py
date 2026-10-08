"""Storing UTC and displaying the reader's clock.

Two separate guarantees, tested separately:

* a stored value is always UTC, and anything used as a storage key is derived from
  UTC rather than from the machine's local date;
* a displayed value is in the reader's zone and says which zone that is, because
  "14:32" without one is not a time.
"""

from __future__ import annotations

import datetime as dt

import pytest

from awltux import timezones
from awltux.timezones import (
    as_utc,
    current_zone_name,
    display_zone,
    format_iso,
    format_moment,
    parse_zone,
    resolve_zone,
    utc_today,
    zone_label,
)
from awltux.web.templating import fmt_age, fmt_ago, fmt_datetime

LONDON = "Europe/London"
NEW_YORK = "America/New_York"
KOLKATA = "Asia/Kolkata"


class TestUtcToday:
    def test_utc_today_is_the_utc_date_not_the_local_one(self):
        assert utc_today() == dt.datetime.now(dt.UTC).date()

    def test_utc_today_is_a_date(self):
        assert isinstance(utc_today(), dt.date)


class TestZoneParsing:
    @pytest.mark.parametrize("name", [LONDON, NEW_YORK, KOLKATA, "UTC"])
    def test_real_zones_are_accepted(self, name):
        assert parse_zone(name) is not None

    @pytest.mark.parametrize(
        "name",
        [
            None,
            "",
            "   ",
            "Not/AZone",
            "../../etc/passwd",
            "Europe/../../etc/passwd",
            "x" * 200,
            123,
            ["Europe/London"],
        ],
    )
    def test_anything_that_is_not_a_real_zone_is_rejected(self, name):
        assert parse_zone(name) is None

    def test_a_cookie_cannot_be_used_to_reach_the_filesystem(self):
        """ZoneInfo keys are paths, so the value is checked against the real set."""
        assert parse_zone("/etc/passwd") is None
        assert parse_zone("..\\..\\windows\\win.ini") is None


class TestZoneResolution:
    def test_the_reader_cookie_wins(self):
        assert resolve_zone(NEW_YORK, LONDON).key == NEW_YORK

    def test_the_configured_zone_is_the_fallback(self):
        assert resolve_zone(None, LONDON).key == LONDON

    def test_utc_is_the_last_resort(self):
        assert resolve_zone(None, None).key == "UTC"

    def test_a_nonsense_cookie_falls_back_rather_than_failing(self):
        assert resolve_zone("Mars/Olympus_Mons", LONDON).key == LONDON

    def test_a_nonsense_cookie_with_no_configuration_is_utc(self):
        assert resolve_zone("Mars/Olympus_Mons", "Also/NotReal").key == "UTC"


class TestFormatting:
    def test_a_time_is_rendered_in_the_requested_zone(self):
        moment = dt.datetime(2026, 6, 15, 12, 0, tzinfo=dt.UTC)
        assert format_moment(moment, "%H:%M", zone=parse_zone(NEW_YORK)).startswith("08:00")
        assert format_moment(moment, "%H:%M", zone=parse_zone(KOLKATA)).startswith("17:30")

    def test_daylight_saving_follows_the_date_not_a_fixed_offset(self):
        winter = dt.datetime(2026, 1, 15, 12, 0, tzinfo=dt.UTC)
        summer = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        london = parse_zone(LONDON)
        assert zone_label(winter, london) == "GMT"
        assert zone_label(summer, london) == "BST"

    def test_a_rendered_time_carries_its_zone(self):
        moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        assert format_moment(moment, zone=parse_zone(NEW_YORK)).endswith("EDT")

    def test_a_date_with_no_clock_is_not_labelled_with_a_zone(self):
        moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        rendered = format_moment(moment, "%Y-%m-%d", zone=parse_zone(NEW_YORK))
        assert rendered == "2026-07-15"

    def test_a_zone_without_an_abbreviation_gets_a_numeric_offset(self):
        moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        label = zone_label(moment, parse_zone(KOLKATA))
        assert label.startswith("+") or label.startswith("UTC+") or label == "IST"

    def test_a_missing_value_renders_as_a_placeholder_not_as_now(self):
        assert format_moment(None) == "—"

    def test_naive_values_are_treated_as_utc(self):
        """SQLite hand-back is naive; treating it as local would shift every time."""
        naive = dt.datetime(2026, 7, 15, 12, 0)
        assert as_utc(naive) == dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)

    def test_aware_values_are_converted_to_utc_not_relabelled(self):
        aware = dt.datetime(2026, 7, 15, 14, 0, tzinfo=parse_zone(LONDON))
        assert as_utc(aware) == dt.datetime(2026, 7, 15, 13, 0, tzinfo=dt.UTC)

    def test_iso_output_is_always_utc_with_an_offset(self):
        aware = dt.datetime(2026, 7, 15, 14, 0, tzinfo=parse_zone(LONDON))
        assert format_iso(aware) == "2026-07-15T13:00:00+00:00"

    def test_iso_of_nothing_is_nothing(self):
        assert format_iso(None) is None


class TestCurrentZone:
    def test_the_default_is_utc(self):
        assert current_zone_name() == "UTC"

    def test_a_context_manager_scopes_the_zone(self):
        with display_zone(parse_zone(NEW_YORK)):
            assert current_zone_name() == NEW_YORK
        assert current_zone_name() == "UTC"

    def test_the_zone_is_restored_even_when_the_body_raises(self):
        with pytest.raises(RuntimeError), display_zone(parse_zone(NEW_YORK)):
            raise RuntimeError("boom")
        assert current_zone_name() == "UTC"

    def test_nested_scopes_restore_the_outer_one(self):
        with display_zone(parse_zone(LONDON)):
            with display_zone(parse_zone(NEW_YORK)):
                assert current_zone_name() == NEW_YORK
            assert current_zone_name() == LONDON


class TestTemplateFilters:
    def test_the_datetime_filter_renders_in_the_requested_zone(self):
        moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        with display_zone(parse_zone(NEW_YORK)):
            assert "08:00" in fmt_datetime(moment)
            assert "EDT" in fmt_datetime(moment)

    def test_the_datetime_filter_falls_back_for_unparseable_input(self):
        assert fmt_datetime("not a date") == "not a date"

    def test_the_datetime_filter_handles_iso_strings(self):
        with display_zone(parse_zone(NEW_YORK)):
            assert "08:00" in fmt_datetime("2026-07-15T12:00:00+00:00")

    def test_a_date_only_format_is_not_labelled(self):
        moment = dt.datetime(2026, 7, 15, 12, 0, tzinfo=dt.UTC)
        with display_zone(parse_zone(NEW_YORK)):
            assert fmt_datetime(moment, "%Y-%m-%d") == "2026-07-15"

    def test_age_is_zone_independent(self):
        """An elapsed duration is the same number of seconds wherever it is read."""
        recent = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        with display_zone(parse_zone(NEW_YORK)):
            in_new_york = fmt_ago(recent)
        with display_zone(parse_zone(KOLKATA)):
            in_kolkata = fmt_ago(recent)
        assert in_new_york == in_kolkata == "5m ago"

    def test_age_of_a_future_timestamp_does_not_go_negative(self):
        assert fmt_ago(dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)) == "just now"

    def test_age_of_a_naive_timestamp_is_not_treated_as_local(self):
        naive = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(hours=3)
        assert fmt_ago(naive) == "3h ago"

    def test_age_beyond_a_month_falls_back_to_a_date_in_the_view_zone(self):
        old = dt.datetime.now(dt.UTC) - dt.timedelta(days=90)
        with display_zone(parse_zone(KOLKATA)):
            rendered = fmt_ago(old)
        assert rendered.startswith("20")
        assert ":" not in rendered


class TestTheAgeThatMayNotRepeatADate:
    """`fmt_age` is for places where the timestamp is already on screen.

    `fmt_ago` ends in a bare `%Y-%m-%d` past a month, so the instrument page's opened date
    read "2025-01-31 17:29 GMT · 2025-01-31" -- the same day twice, and the second copy
    told the reader nothing (reported from the page, 2026-10-08).
    """

    def test_a_short_age_reads_like_fmt_ago(self):
        recent = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=5)
        assert fmt_age(recent) == fmt_ago(recent) == "5m ago"

    def test_an_old_value_is_never_rendered_as_a_date(self):
        for days in (40, 90, 400, 3000):
            rendered = fmt_age(dt.datetime.now(dt.UTC) - dt.timedelta(days=days))
            assert not rendered.startswith("20"), f"{days}d rendered as a date: {rendered}"
            assert rendered.endswith(" ago"), rendered

    def test_months_and_years_are_the_units_past_a_month(self):
        assert fmt_age(dt.datetime.now(dt.UTC) - dt.timedelta(days=60)).endswith("mo ago")
        assert fmt_age(dt.datetime.now(dt.UTC) - dt.timedelta(days=800)).endswith("y ago")

    def test_a_future_timestamp_does_not_go_negative(self):
        assert fmt_age(dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)) == "just now"


class TestKnownZones:
    def test_the_zone_database_is_actually_available(self):
        """Without tzdata, every zone silently collapses to UTC.

        That would look like the feature working while every reader saw UTC, so it
        is asserted rather than assumed.
        """
        zones = timezones.known_zones()
        assert "Europe/London" in zones
        assert "America/New_York" in zones
        assert len(zones) > 100

    def test_the_cache_returns_the_same_object(self):
        assert timezones.known_zones() is timezones.known_zones()
