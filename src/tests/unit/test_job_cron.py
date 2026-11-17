"""Cron text and schedule entries against a fake clock, with DST and day rules."""
import datetime
import zoneinfo

import pytest

import cosa.rest.job_cron as jc

NY = zoneinfo.ZoneInfo( "America/New_York" )


def at( y, mo, d, h=0, mi=0 ):
    """Ensures: returns an aware New York time."""
    return datetime.datetime( y, mo, d, h, mi, tzinfo=NY )


def test_daily_last_and_next():
    now = at( 2026, 11, 7, 10, 30 )
    assert jc.cron_last( "0 10 * * *", now ) == at( 2026, 11, 7, 10, 0 )
    assert jc.cron_last( "0 10 * * *", at( 2026, 11, 7, 9, 0 ) ) == at( 2026, 11, 6, 10, 0 )
    assert jc.cron_next( "0 10 * * *", now ) == at( 2026, 11, 8, 10, 0 )
    assert jc.cron_next( "0 10 * * *", at( 2026, 11, 7, 9, 0 ) ) == at( 2026, 11, 7, 10, 0 )


def test_steps_lists_ranges_and_weekday_seven_is_sunday():
    assert jc.parse_field( "9,19", 0, 59 ) == [ 9, 19 ] and jc.parse_field( "*/20", 0, 59 ) == [ 0, 20, 40 ] and jc.parse_field( "1-3", 0, 59 ) == [ 1, 2, 3 ]
    assert jc.parse_field( "10-20/5", 0, 59 ) == [ 10, 15, 20 ]
    sunday = at( 2026, 11, 8, 19, 0 )                                # a Sunday
    assert jc.cron_last( "0 19 * * 7", at( 2026, 11, 9, 8 ) ) == sunday and jc.cron_last( "0 19 * * 0", at( 2026, 11, 9, 8 ) ) == sunday


def test_when_both_day_fields_are_set_either_matches_but_one_restricted_field_must_match():
    assert jc.cron_next( "0 8 13 * 5", at( 2026, 11, 7 ) ) == at( 2026, 11, 13, 8 )                      # Friday the 13th both: the 13th is also a Friday
    assert jc.cron_next( "0 8 10 * 1", at( 2026, 11, 7 ) ) == at( 2026, 11, 9, 8 )                      # Monday the 9th beats the 10th: OR
    assert jc.cron_next( "0 8 * * 1", at( 2026, 11, 7 ) ) == at( 2026, 11, 9, 8 )                       # weekday alone
    assert jc.cron_next( "0 8 5 12 *", at( 2026, 11, 7 ) ) == at( 2026, 12, 5, 8 )                      # month restricts


def test_yearly_job_found_and_a_never_firing_line_is_none():
    assert jc.cron_last( "0 22 17 8 *", at( 2026, 11, 7 ) ) == at( 2026, 8, 17, 22 )
    assert jc.cron_next( "0 22 17 8 *", at( 2026, 11, 7 ) ) == at( 2027, 8, 17, 22 )
    assert jc.cron_last( "0 0 31 2 *", at( 2026, 11, 7 ) ) is None and jc.cron_next( "0 0 31 2 *", at( 2026, 11, 7 ) ) is None


def test_the_spring_forward_gap_does_not_lose_the_day():
    now = at( 2026, 3, 8, 12 )                                       # DST began 2026-03-08 02:00
    got = jc.cron_last( "30 2 * * *", now )
    assert got is not None and got.date() == datetime.date( 2026, 3, 8 )
    assert jc.cron_last( "0 10 * * *", at( 2026, 3, 8, 11 ) ).utcoffset() == datetime.timedelta( hours=-4 )


def test_cron_between_lists_the_window():
    got = jc.cron_between( "0 10 * * *", at( 2026, 11, 5, 10 ), at( 2026, 11, 7, 10 ) )
    assert got == [ at( 2026, 11, 6, 10 ), at( 2026, 11, 7, 10 ) ]


@pytest.mark.parametrize( "bad", [ "* * * *", "61 * * * *", "*/0 * * * *", "5-2 * * * *", "x * * * *" ] )
def test_bad_cron_text_raises(bad):
    with pytest.raises( ValueError ): jc.parse_cron( bad )


def test_entry_due_times_for_cron_boot_and_interval_entries():
    now, boot = at( 2026, 11, 7, 10, 30 ), at( 2026, 11, 7, 10, 20 )
    assert jc.entry_last_due( { "cron": "0 10 * * *" }, now, boot ) == at( 2026, 11, 7, 10 )
    assert jc.entry_last_due( { "after_boot_seconds": 300 }, now, boot ) == at( 2026, 11, 7, 10, 25 )
    assert jc.entry_last_due( { "after_boot_seconds": 3600 }, now, boot ) is None
    assert jc.entry_next_due( { "after_boot_seconds": 3600 }, now, boot ) == at( 2026, 11, 7, 11, 20 )
    assert jc.entry_next_due( { "after_boot_seconds": 300 }, now, boot ) is None
    assert jc.entry_next_due( { "cron": "0 11 * * *" }, now, boot ) == at( 2026, 11, 7, 11 )
    loop = { "every_seconds": 60 }
    assert jc.entry_last_due( loop, now, boot, None ) is None and jc.entry_next_due( loop, now, boot, None ) == now
    assert jc.entry_last_due( loop, now, boot, at( 2026, 11, 7, 10, 28 ) ) == at( 2026, 11, 7, 10, 29 )
    assert jc.entry_last_due( loop, now, boot, at( 2026, 11, 7, 10, 29, ) + datetime.timedelta( seconds=45 ) ) is None
    assert jc.entry_next_due( loop, now, boot, now - datetime.timedelta( seconds=10 ) ) == now + datetime.timedelta( seconds=50 )
    assert jc.entry_next_due( loop, now, boot, now - datetime.timedelta( seconds=500 ) ) == now


def test_entry_label_reads_in_plain_words():
    assert jc.entry_label( { "cron": "0 10 * * *", "mode": "daily" } ) == "cron 0 10 * * * (daily)"
    assert jc.entry_label( { "after_boot_seconds": 300 } ) == "300 s after boot"
    assert jc.entry_label( { "every_seconds": 30 } ) == "every 30 s"
