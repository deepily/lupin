"""
Unit tests of the run measurements.

They cover working days, container samples, subagent peaks and the real meter and clock.
The working-day tests use fixed moments in November 2026, a month that starts on a Sunday.
So each expected figure is a literal worked out by hand from the New York calendar.
"""
import datetime
import subprocess
import sys

import pytest

from lupin_mcp.reuse_harness import errors as err
from lupin_mcp.reuse_harness import measure

NEW_YORK = datetime.timezone( datetime.timedelta( hours=-5 ) )   # EST, the offset on the dates below


def at( day, hour=0, minute=0, second=0 ):
    """Return a November 2026 moment in New York standard time."""
    return datetime.datetime( 2026, 11, day, hour, minute, second, tzinfo=NEW_YORK )


def test_a_span_inside_one_weekday_counts_in_full():
    assert measure.working_seconds( at( 2, 9 ), at( 2, 17 ) ) == 8 * 3600


def test_a_span_over_a_weekend_loses_the_whole_weekend_and_keeps_the_nights():
    # Friday 6 Nov 18:00 to Monday 9 Nov 06:00: six hours of Friday, none of Saturday or Sunday, six hours of Monday
    assert measure.working_seconds( at( 6, 18 ), at( 9, 6 ) ) == 12 * 3600


def test_a_span_that_lies_inside_a_weekend_counts_nothing():
    assert measure.working_seconds( at( 7, 3 ), at( 8, 22 ) ) == 0


def test_a_span_over_the_end_of_summer_time_is_measured_in_real_hours():
    # Friday 30 Oct 20:00 EDT (00:00 UTC on the 31st) to Monday 2 Nov 04:00 EST: four hours of Friday, four of Monday
    start = datetime.datetime( 2026, 10, 30, 20, tzinfo=datetime.timezone( datetime.timedelta( hours=-4 ) ) )
    assert measure.working_seconds( start, at( 2, 4 ) ) == 8 * 3600


def test_a_span_given_in_utc_is_read_in_new_york():
    # 03:00 UTC on Saturday 7 Nov is still Friday evening in New York: 22:00 EST
    start = at( 6, 20 )
    end   = datetime.datetime( 2026, 11, 7, 3, tzinfo=datetime.timezone.utc )
    assert measure.working_seconds( start, end ) == 2 * 3600


def test_an_end_before_the_start_is_refused():
    with pytest.raises( err.HarnessError ) as caught: measure.working_seconds( at( 3 ), at( 2 ) )
    assert caught.value.code == err.BAD_SPEC


def test_working_days_are_days_of_twenty_four_hours():
    assert measure.working_days( at( 2, 12 ), at( 4 ) ) == 1.5


def test_the_guard_is_ten_working_days_and_is_reached_at_the_second_it_is_used_up():
    # Monday 2 Nov 00:00 to Saturday 14 Nov 00:00 is ten weekdays and one weekend
    assert measure.GUARD_WORKING_DAYS == 10
    assert measure.guard_reached( at( 2 ), at( 13, 23, 59, 59 ) ) is False
    assert measure.guard_reached( at( 2 ), at( 14 ) ) is True
    assert measure.guard_reached( at( 2 ), at( 20 ) ) is True


@pytest.mark.parametrize( "text, expected", [
    ( "123.4MiB / 31.3GiB|2.50%",    { "mem_bytes" : int( 123.4 * 1024 ** 2 ), "cpu_percent" : 2.5 } ),
    ( "1.5GiB / 2GiB|0.00%",         { "mem_bytes" : int( 1.5 * 1024 ** 3 ), "cpu_percent" : 0.0 } ),
    ( "900kB / 2GiB|10%",            { "mem_bytes" : 900000, "cpu_percent" : 10.0 } ),
    ( "512B / 2GiB|0.1%",            { "mem_bytes" : 512, "cpu_percent" : 0.1 } ),
    ( "  64MB / 1GB|3.00%  ",        { "mem_bytes" : 64 * 1000 ** 2, "cpu_percent" : 3.0 } ),
] )
def test_parse_stats_reads_memory_and_cpu_with_their_units( text, expected ):
    assert measure.parse_stats( text ) == expected


@pytest.mark.parametrize( "text", [ "", "not a stats line", "12XB / 1GiB|1%", "12MiB / 1GiB|--", "12MiB|1%" ] )
def test_parse_stats_answers_none_for_what_it_cannot_read( text ):
    assert measure.parse_stats( text ) is None


def calls( *names ):
    """Return an assistant event that makes the named tool calls in one message."""
    return { "type" : "assistant", "message" : { "content" : [ { "type" : "tool_use", "name" : name } for name in names ] } }


def test_peak_agents_is_the_most_subagent_calls_in_one_assistant_message_and_not_their_sum():
    assert measure.peak_agents( [ calls( "Agent" ), calls( "Agent", "Task", "Bash" ), calls( "Task" ) ] ) == 2


def test_peak_agents_ignores_other_tools_other_events_and_content_that_is_not_a_list():
    user   = { "type" : "user", "message" : { "content" : [ { "type" : "tool_use", "name" : "Agent" } ] } }
    text   = { "type" : "assistant", "message" : { "content" : "Agent" } }
    blocks = { "type" : "assistant", "message" : { "content" : [ "Agent", { "type" : "text", "name" : "Agent" } ] } }
    assert measure.peak_agents( [ user, text, blocks, calls( "Bash", "Read" ), { "type" : "system" } ] ) == 0
    assert measure.peak_agents( [] ) == 0


def test_the_meter_sees_the_cpu_and_largest_process_of_a_finished_command():
    before = measure.Meter().read()
    code   = "import time\nblock = bytearray( 80 * 1024 * 1024 )\nfor i in range( 0, len( block ), 4096 ): block[ i ] = 1\nend = time.process_time() + 0.3\nwhile time.process_time() < end: pass"
    subprocess.run( [ sys.executable, "-c", code ], check=True )
    after = measure.Meter().read()
    assert after[ "cpu_seconds" ] - before[ "cpu_seconds" ] >= 0.25
    assert after[ "peak_rss_bytes" ] >= 80 * 1024 * 1024 and after[ "peak_rss_bytes" ] % 1024 == 0


def test_the_clock_gives_the_current_moment_in_utc():
    low  = datetime.datetime.now( datetime.timezone.utc )
    now  = measure.Clock().now()
    high = datetime.datetime.now( datetime.timezone.utc )
    assert low <= now <= high and now.utcoffset() == datetime.timedelta( 0 )
