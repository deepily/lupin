"""The rules of design section 3, each against a fake clock."""
import datetime
import zoneinfo

import pytest

import cosa.rest.job_health as jh
from lupin_mcp import job_summary as js

NY   = zoneinfo.ZoneInfo( "America/New_York" )
TUNE = { "window_days": 7, "growth_min_items": 5, "growth_min_percent": 5, "lock_stale_seconds": 10800 }
BOOT = datetime.datetime( 2026, 11, 1, 8, 0, tzinfo=NY )


def at( d, h=0, m=0 ):
    """Ensures: returns an aware time in November 2026."""
    return datetime.datetime( 2026, 11, d, h, m, tzinfo=NY )


def entry( **over ):
    """Ensures: returns an effective registry entry for a daily 10:00 job."""
    base = { "job": "j", "title": "J", "owner": "cheech", "schedule": [ { "cron": "0 10 * * *", "mode": "daily" } ], "grace_minutes": 30, "notify_interval_minutes": 30 }
    return { **base, **over }


def record( outcome="clean", when=None, scan=None, fix=None, previous=None, **over ):
    """Ensures: returns a real summary built by the writer for one attempt at `when`."""
    when = when or at( 7, 10 )
    a = { "started_at": when.isoformat(), "finished_at": when.isoformat(), "trigger": "cron", "outcome": outcome, "mode": "daily", **over }
    return js.build_summary( "j", a, scan, fix, previous )


def run( ent, summary, now, **kw ):
    """Ensures: returns the assessed entry."""
    return jh.assess( ent, summary, now, kw.pop( "boot", BOOT ), TUNE, **kw )


def rules( got ):
    """Ensures: returns the rule names that are true."""
    return [ r[ "rule" ] for r in got[ "reasons" ] ]


def test_missing_summary_is_unknown_never_reported():
    got = run( entry(), None, at( 7, 11 ) )
    assert got[ "state" ] == "unknown" and got[ "unknown_reason" ] == "never reported" and got[ "reasons" ] == []


def test_a_job_past_due_with_no_attempt_since_is_silent():
    s = record( when=at( 6, 10 ) )                                     # last ran yesterday
    assert run( entry(), s, at( 7, 10, 29 ) )[ "state" ] == "healthy"   # inside grace
    got = run( entry(), s, at( 7, 10, 31 ) )
    assert got[ "state" ] == "silent" and rules( got ) == [ "silent" ] and got[ "schedule" ][ "last_due" ] == at( 7, 10 ).isoformat()


def test_a_skipped_run_is_not_silent():
    s = record( "skipped", at( 7, 10, 1 ), previous=record( when=at( 6, 10 ) ) )
    assert run( entry(), s, at( 7, 12 ) )[ "state" ] == "healthy"


def test_a_disabled_run_covers_the_due_time_so_a_switched_off_job_is_off_not_overdue():
    old = record( when=at( 6, 10 ) )
    assert run( entry(), old, at( 7, 12 ) )[ "state" ] == "silent", "control: with no run since, the same job is overdue"
    off = record( "disabled", at( 7, 10, 1 ), previous=old, evidence="INI key 'cron job j enabled' is false" )
    got = run( entry(), off, at( 7, 12 ) )
    assert got[ "state" ] == "healthy" and got[ "reasons" ] == [] and got[ "last_attempt" ][ "outcome" ] == "disabled"
    assert got[ "last_finished" ][ "started_at" ] == at( 6, 10 ).isoformat(), "a disabled run is not a finished run: the last finish stays the earlier one"
    assert got[ "consecutive_failures" ] == 0


def test_a_hand_run_after_the_due_time_covers_it_and_another_mode_does_not():
    s = record( "clean", at( 7, 10, 40 ), trigger="hand" ) if False else record( "clean", at( 7, 10, 40 ) )
    assert run( entry(), s, at( 7, 12 ) )[ "state" ] == "healthy"
    base = entry( schedule=[ { "cron": "0 10 * * *", "mode": "daily" }, { "cron": "7 11 * * *", "mode": "baseline" } ] )
    daily_only = record( "clean", at( 7, 11, 8 ), mode="daily" )
    assert run( base, daily_only, at( 7, 12 ) )[ "state" ] == "silent"      # the 11:07 baseline is not covered by a daily attempt
    assert run( base, record( "clean", at( 7, 11, 8 ), mode="baseline" ), at( 7, 12 ) )[ "state" ] == "healthy"
    assert run( base, record( "clean", at( 7, 11, 8 ), mode=None ), at( 7, 12 ) )[ "state" ] == "healthy"


def test_a_failing_job_that_also_grows_is_both():
    first = record( "carried", at( 2, 10 ), scan={ "unit": "definitions", "count": 1030, "drained_last_run": 100 } )
    second = record( "carried", at( 6, 10 ), scan={ "unit": "definitions", "count": 2124, "drained_last_run": 304 }, previous=first )
    last = record( "failed", at( 7, 10 ), previous=second, stage="branch_guard", failure="stale_branch" )
    got = run( entry( scan_debt=True ), last, at( 7, 11 ) )
    assert got[ "state" ] == "failing" and rules( got ) == [ "failing", "scan_grew" ]
    assert "branch_guard" in got[ "reasons" ][ 0 ][ "text" ] and got[ "consecutive_failures" ] == 1
    assert got[ "scan_debt" ][ "clears_in" ] == { "kind": "never_at_this_rate", "days": None }


def test_silent_and_failing_and_behind_all_listed_and_silent_wins_the_badge():
    first = record( "carried", at( 2, 10 ), scan={ "unit": "u", "count": 100, "drained_last_run": 0 } )
    second = record( "failed", at( 3, 10 ), previous=first )
    got = run( entry( scan_debt=True ), second, at( 7, 12 ) )
    assert got[ "state" ] == "silent" and rules( got ) == [ "silent", "failing" ]


def test_failing_with_nothing_finished_says_so():
    got = run( entry(), record( "failed", at( 7, 10 ) ), at( 7, 11 ) )
    assert "never reported" in got[ "reasons" ][ 0 ][ "text" ] and "unnamed stage" in got[ "reasons" ][ 0 ][ "text" ]


def test_test_a_needs_five_items_and_five_percent_and_two_points_in_the_window():
    def grown( a, b ):
        first = record( "carried", at( 3, 10 ), scan={ "unit": "u", "count": a, "drained_last_run": 1 } )
        return run( entry( scan_debt=True ), record( "carried", at( 7, 10 ), scan={ "unit": "u", "count": b, "drained_last_run": 1 }, previous=first ), at( 7, 11 ) )
    assert rules( grown( 1000, 1049 ) ) == [] and rules( grown( 1000, 1050 ) ) == [ "scan_grew" ]       # 5 percent edge
    assert rules( grown( 10, 14 ) ) == [] and rules( grown( 10, 15 ) ) == [ "scan_grew" ]                # 5 item edge
    one = record( "carried", at( 7, 10 ), scan={ "unit": "u", "count": 9, "drained_last_run": 1 } )
    assert rules( run( entry( scan_debt=True ), one, at( 7, 11 ) ) ) == []
    old = record( "carried", at( 7, 10 ), scan={ "unit": "u", "count": 90, "drained_last_run": 1 },
                  previous=record( "carried", datetime.datetime( 2026, 10, 1, 10, tzinfo=NY ), scan={ "unit": "u", "count": 1, "drained_last_run": 1 } ) )
    assert rules( run( entry( scan_debt=True ), old, at( 7, 11 ) ) ) == []                              # the earlier point is outside the 7 days


def test_test_b_two_zero_drains_with_debt_left():
    first = record( "carried", at( 5, 10 ), scan={ "unit": "u", "count": 50, "drained_last_run": 0 } )
    second = record( "carried", at( 6, 10 ), scan={ "unit": "u", "count": 50, "drained_last_run": 0 }, previous=first )
    assert "no_drain" in rules( run( entry( scan_debt=True ), second, at( 6, 11 ) ) )
    third = record( "carried", at( 6, 10 ), scan={ "unit": "u", "count": 50, "drained_last_run": 4 }, previous=first )
    assert "no_drain" not in rules( run( entry( scan_debt=True ), third, at( 6, 11 ) ) )
    earlier = record( "carried", at( 5, 10 ), scan={ "unit": "u", "count": 50, "drained_last_run": 4 } )
    only_last = record( "carried", at( 6, 10 ), scan={ "unit": "u", "count": 50, "drained_last_run": 0 }, previous=earlier )
    assert "no_drain" not in rules( run( entry( scan_debt=True ), only_last, at( 6, 11 ) ) )          # the older of the two drained something
    zero = record( "clean", at( 6, 10 ), scan={ "unit": "u", "count": 0, "drained_last_run": 0 }, previous=first )
    assert "no_drain" not in rules( run( entry( scan_debt=True ), zero, at( 6, 11 ) ) )
    unknown = record( "carried", at( 6, 10 ), scan={ "unit": "u", "count": 5, "drained_last_run": None }, previous=record( "carried", at( 5, 10 ), scan={ "unit": "u", "count": 5 } ) )
    assert "no_drain" not in rules( run( entry( scan_debt=True ), unknown, at( 6, 11 ) ) )


def test_test_c_rows_pile_up_and_it_is_skipped_without_the_store():
    fix = { "own_mark": "job:j", "unfiled": 3, "opened_in_run": 45 }
    s = record( "carried", at( 7, 10 ), fix=fix )
    piling = { "open_now": 40, "opened_in_window": 45, "closed_in_window": 5, "open_at_window_start": 0 }
    assert rules( run( entry( fix_debt=True ), s, at( 7, 11 ), store=piling ) ) == [ "fix_piling" ]
    assert rules( run( entry( fix_debt=True ), s, at( 7, 11 ), store=None ) ) == []
    for change in ( { "open_now": 0 }, { "closed_in_window": 45 }, { "open_at_window_start": 41 } ):
        assert rules( run( entry( fix_debt=True ), s, at( 7, 11 ), store={ **piling, **change } ) ) == []
    got = run( entry( fix_debt=True ), s, at( 7, 11 ), store=piling )
    assert got[ "fix_debt" ][ "open_now" ] == 40 and got[ "fix_debt" ][ "filed_total" ] == 45 and got[ "fix_debt" ][ "own_mark" ] == "job:j"
    none = run( entry( fix_debt=True, fix_debt_key="job:j" ), s, at( 7, 11 ) )
    assert none[ "fix_debt" ][ "open_now" ] is None and none[ "fix_debt" ][ "closed_in_window" ] is None


def test_test_d_a_refresh_is_stale_past_its_limit_and_the_age_is_computed_at_read_time():
    def fresh( built ):
        s = record( "clean", at( 7, 10 ), scan={ "unit": "hours", "count": None, "freshness": { "built_at": built.isoformat(), "stale_after_hours": 36 } } )
        return run( entry( scan_debt=True ), s, at( 7, 11 ) )
    ok = fresh( at( 6, 11 ) )
    assert ok[ "state" ] == "healthy" and ok[ "scan_debt" ][ "freshness" ][ "age_hours" ] == 24.0 and ok[ "scan_debt" ][ "clears_in" ] is None
    assert fresh( at( 6, 11 ) - datetime.timedelta( hours=12 ) )[ "state" ] == "healthy"             # exactly 36 hours old is not stale
    assert fresh( at( 6, 11 ) - datetime.timedelta( hours=12, minutes=1 ) )[ "state" ] == "behind"
    stale = fresh( at( 5, 10 ) )
    assert stale[ "state" ] == "behind" and rules( stale ) == [ "stale" ]
    broken = js.build_summary( "j", { "started_at": at( 7, 10 ).isoformat(), "trigger": "cron", "outcome": "clean" }, { "unit": "h", "count": None, "freshness": { "built_at": "garbage", "stale_after_hours": 36 } } )
    assert run( entry( scan_debt=True ), broken, at( 7, 11 ) )[ "scan_debt" ][ "freshness" ][ "age_hours" ] is None


def test_clears_in_three_answers():
    pts = lambda *c: [ { "at": at( 3 + i, 10 ).isoformat(), "count": n } for i, n in enumerate( c ) ]
    assert jh.clears_in( pts( 5 ) ) == { "kind": "not_enough_runs", "days": None }
    same = [ { "at": at( 3, 10 ).isoformat(), "count": 5 }, { "at": at( 3, 10 ).isoformat(), "count": 4 } ]
    assert jh.clears_in( same )[ "kind" ] == "not_enough_runs"
    assert jh.clears_in( pts( 100, 80 ) ) == { "kind": "days", "days": 4.0 }
    assert jh.clears_in( pts( 100, 100 ) )[ "kind" ] == "never_at_this_rate" and jh.clears_in( pts( 10, 0 ) ) == { "kind": "days", "days": 0.0 }


def test_machine_off_at_the_due_time_is_a_sub_reason_and_a_boot_entry_defers_lateness():
    boot_late = at( 7, 10, 40 )                                       # booted after the 10:00 due time
    s = record( when=at( 6, 10 ) )
    got = run( entry(), s, at( 7, 11 ), boot=boot_late )
    assert got[ "state" ] == "silent" and got[ "machine_was_off" ] and "machine was off" in got[ "reasons" ][ 0 ][ "text" ]
    with_boot = entry( schedule=[ { "cron": "0 10 * * *", "mode": "daily" }, { "after_boot_seconds": 300, "mode": "daily" } ] )
    assert run( with_boot, s, at( 7, 10, 44 ), boot=boot_late )[ "state" ] == "healthy"      # catch-up not yet due
    assert run( with_boot, s, at( 7, 12 ), boot=boot_late )[ "state" ] == "silent"           # catch-up came due at 10:45 and never ran
    ran = record( "clean", at( 7, 10, 46 ), previous=s )
    assert run( with_boot, ran, at( 7, 12 ), boot=boot_late )[ "state" ] == "healthy"


def test_a_live_lock_is_running_not_silent_until_it_goes_stale():
    s = record( when=at( 6, 10 ) )
    got = run( entry(), s, at( 7, 12 ), lock_age=600 )
    assert got[ "state" ] == "healthy" and got[ "running" ]
    assert run( entry(), s, at( 7, 12 ), lock_age=999999 )[ "state" ] == "silent"


def test_no_schedule_is_unscheduled_and_never_silent_and_a_future_only_entry_is_not_late():
    got = run( entry( schedule=[] ), record( when=at( 1, 10 ) ), at( 7, 12 ) )
    assert got[ "unscheduled" ] and got[ "state" ] == "healthy" and got[ "schedule" ][ "next_due" ] is None
    soon = entry( schedule=[ { "after_boot_seconds": 99999 } ] )
    assert run( soon, record( when=at( 1, 10 ) ), at( 7, 12 ), boot=at( 7, 11 ) )[ "state" ] == "healthy"


def test_a_looping_job_is_silent_when_no_attempt_within_the_interval_plus_its_grace_seconds():
    loop = entry( schedule=[ { "every_seconds": 30 } ], grace_seconds=20 )
    s = record( when=at( 7, 11, 0 ) )
    assert run( loop, s, at( 7, 11, 0 ) + datetime.timedelta( seconds=49 ) )[ "state" ] == "healthy"
    assert run( loop, s, at( 7, 11, 0 ) + datetime.timedelta( seconds=51 ) )[ "state" ] == "silent"
    got = run( loop, s, at( 7, 11, 0 ) + datetime.timedelta( seconds=10 ) )
    assert got[ "schedule" ][ "grace_seconds" ] == 20 and got[ "schedule" ][ "entries" ] == [ "every 30 s" ]


def test_liveness_only_jobs_are_up_down_or_not_loaded():
    live = entry( schedule=[], liveness={ "kind": "systemd", "unit": "u.service" } )
    up, down, gone = ( run( live, None, at( 7, 11 ), unit_state=s ) for s in ( "active", "inactive", "not-loaded" ) )
    assert ( up[ "state" ], up[ "running" ], up[ "liveness" ][ "up" ] ) == ( "healthy", True, True ) and not up[ "unscheduled" ]
    assert ( down[ "state" ], rules( down ) ) == ( "silent", [ "silent" ] ) and gone[ "state" ] == "unknown" and "not loaded" in gone[ "unknown_reason" ]


def test_the_strip_draws_a_hole_where_a_run_was_due_and_absent():
    first = record( "clean", at( 3, 10 ) )
    third = record( "clean", at( 5, 10, 5 ), previous=first )
    got = run( entry(), third, at( 5, 11 ) )
    assert [ s[ "outcome" ] for s in got[ "strip" ] ] == [ "clean", "missed", "clean" ] and got[ "strip" ][ 1 ][ "at" ] == at( 4, 10 ).isoformat()
    fresh = run( entry(), record( "clean", at( 5, 10, 5 ) ), at( 5, 11 ) )
    assert [ s[ "outcome" ] for s in fresh[ "strip" ] ] == [ "clean" ]
    boot_only = entry( schedule=[ { "after_boot_seconds": 60 } ] )
    assert [ s[ "outcome" ] for s in run( boot_only, third, at( 5, 11 ), boot=at( 5, 9 ) )[ "strip" ] ] == [ "clean", "clean" ]


def test_old_records_without_recent_fall_back_to_the_last_attempt():
    s = record( when=at( 7, 10, 5 ) ); del s[ "recent" ]
    assert run( entry(), s, at( 7, 12 ) )[ "state" ] == "healthy"
    assert jh.parse_time( "no" ) is None and jh.parse_time( "2026-11-07T10:00:00" ) is None and jh.parse_time( None ) is None


def test_parse_time_is_the_memento_reaper_parser_and_freshness_reads_through_it():
    from lupin_mcp import reap_memento as rm
    assert jh.parse_time is rm._parse_iso_aware
    east = zoneinfo.ZoneInfo( "America/New_York" )
    now = datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=east )                     # 17:00 UTC
    block = jh.freshness_of( { "built_at": "2026-11-07T10:00:00+00:00", "stale_after_hours": 24 }, now )
    assert block == { "built_at": "2026-11-07T10:00:00+00:00", "stale_after_hours": 24, "age_hours": 7.0 }
    assert jh.freshness_of( { "built_at": "2026-11-07T10:00:00" }, now )[ "age_hours" ] is None
    assert jh.freshness_of( None, now ) is None


def test_output_carries_the_registry_facts_the_page_needs():
    ent = entry( audience=[ "rick" ], rows=[ { "id": "350d43c8", "title": "T", "href": None } ], detail_link="/app/x", run={ "argv": [ "x" ] }, notify_interval_minutes=45 )
    got = run( ent, record(), at( 7, 11 ) )
    assert got[ "audience" ] == [ "rick" ] and got[ "notify_interval_seconds" ] == 2700 and got[ "runnable" ] and got[ "detail_link" ] == "/app/x" and got[ "rows" ][ 0 ][ "title" ] == "T"
    assert got[ "schedule" ][ "entries" ] == [ "cron 0 10 * * * (daily)" ] and got[ "schedule" ][ "next_due" ] == at( 8, 10 ).isoformat() and got[ "applies" ] == { "scan_debt": False, "fix_debt": False }


def test_grace_and_lock_age_boundaries_are_inclusive():
    s = record( when=at( 6, 10 ) )
    assert run( entry(), s, at( 7, 10, 30 ) )[ "state" ] == "healthy"                      # exactly the grace after the due time
    assert run( entry(), s, at( 7, 10, 30 ) + datetime.timedelta( seconds=1 ) )[ "state" ] == "silent"
    assert run( entry(), s, at( 7, 12 ), lock_age=10800 )[ "running" ] and not run( entry(), s, at( 7, 12 ), lock_age=10801 )[ "running" ]


def test_the_strip_keeps_only_the_newest_fourteen_entries():
    first = record( "clean", at( 1, 10 ) )
    hourly = entry( schedule=[ { "cron": "0 * * * *" } ] )
    got = run( hourly, record( "clean", at( 5, 10, 1 ), previous=first ), at( 5, 12 ) )
    assert len( got[ "strip" ] ) == jh.STRIP_MAX == 14 and got[ "strip" ][ -1 ][ "at" ] > got[ "strip" ][ 0 ][ "at" ]
