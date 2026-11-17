"""Unit tests for cosa.utils.utc_stamp.utc_compact_stamp."""
import re
from datetime import datetime, timezone

import cosa.utils.utc_stamp as us
from cosa.utils.utc_stamp import utc_compact_stamp


def test_a_given_moment_is_formatted_as_year_month_day_t_hour_minute_second_z():
    assert utc_compact_stamp( datetime( 2026, 8, 29, 22, 15, 30, tzinfo=timezone.utc ) ) == "20260829T221530Z"


def test_a_given_moment_is_formatted_as_it_is_with_no_zone_conversion():
    naive = datetime( 2026, 1, 2, 3, 4, 5 )
    assert utc_compact_stamp( naive ) == "20260102T030405Z"


def test_with_no_argument_it_reads_the_clock_and_looks_like_a_stamp( monkeypatch ):
    class _Fixed:
        @staticmethod
        def now( tz ):
            return datetime( 2027, 12, 31, 23, 59, 58, tzinfo=tz )

    monkeypatch.setattr( us, "datetime", _Fixed )
    assert utc_compact_stamp() == "20271231T235958Z", "a hard-coded return value cannot pass"
    monkeypatch.undo()
    assert re.fullmatch( r"\d{8}T\d{6}Z", utc_compact_stamp() )
