"""The duplicate check status: backlog by kind, rates, projected zero, health and the page."""
import datetime

import pytest

from lupin_mcp import duplicate_check_history as hist
from lupin_mcp import duplicate_check_status as st

TZ  = datetime.timezone( datetime.timedelta( hours=-5 ) )
NOW = datetime.datetime( 2026, 11, 8, 12, 5, tzinfo=TZ )


def at( day, hour, minute=0 ): return datetime.datetime( 2026, 11, day, hour, minute, tzinfo=TZ ).isoformat()


def row( day, hour, mode="daily", status="ok", carried=0, owed=None, judged=0, calls=0, secs=60.0, trigger="cron", usage=None, **more ):
    """Ensures: returns the history line of a run with the given measures."""
    doc = { "status": status, "trigger": trigger, "mode": mode, "started_at": at( day, hour ), "carried": [ 0 ] * carried if carried is not None else None, "owed": owed,
            "judged": judged, "judge_calls": calls, "elapsed_seconds": secs, "branch": "wip-x", "usage": usage, **more }
    return hist.line_of( doc, f"{day}-{hour}.json" )


def folder_with( tmp_path, *lines ):
    for l in lines: hist.append_line( tmp_path, l )
    return tmp_path


def test_the_baseline_remaining_is_the_newest_measured_baseline_carried_count_or_none():
    assert st.baseline_remaining( [] ) is None and st.baseline_remaining( [ row( 7, 10 ) ] ) is None
    assert st.baseline_remaining( [ row( 7, 10, mode="baseline", carried=900 ), row( 7, 11, mode="baseline", carried=700 ), row( 7, 12, mode="baseline", status="failed", carried=None ) ] ) == 700


def test_the_inflow_is_what_a_run_owed_beyond_the_carried_count_before_it_averaged_over_the_days_with_one():
    lines = [ row( 6, 10, carried=100, owed=100 ), row( 6, 11, carried=50, owed=100 ), row( 6, 12, carried=40, owed=250 ),       # arrivals 0 then 200
             row( 7, 10, carried=0, owed=40 ), row( 7, 11, carried=0, owed=0 ),                                                    # arrivals 0 then 0
             row( 7, 12, status="failed", carried=None ), row( 7, 13, carried=0, owed=30 ) ]                                       # a failed run is not a measurement; 30
    assert st.inflow_per_day( lines, NOW ) == 115, "day 6: 200, day 7: 30"
    assert st.inflow_per_day( [ row( 6, 10, carried=5 ), row( 6, 11, carried=5 ) ], NOW ) is None, "no owed count"
    assert st.inflow_per_day( [ row( 1, 10, carried=0, owed=0 ), row( 1, 11, carried=0, owed=9 ) ], NOW, days=2 ) is None, "older than the window"
    assert st.inflow_per_day( [ row( 7, 10, carried=10, owed=10 ), row( 7, 11, carried=0, owed=3 ) ], NOW ) == 0, "never below 0"


def test_the_clearing_rate_averages_the_judged_counts_of_both_modes_over_the_recent_days_with_a_run():
    lines = [ row( 1, 10, judged=999 ), row( 6, 10, judged=300 ), row( 6, 11, mode="baseline", judged=200 ), row( 7, 10, judged=100 ), row( 7, 11, status="failed", carried=None, judged=None ) ]
    assert st.judged_per_day( lines, NOW ) == 300, "day 6: 500, day 7: 100; day 1 is too old"
    assert st.judged_per_day( [], NOW ) is None


@pytest.mark.parametrize( "backlog,drain,inflow,want", [ ( 0, None, None, "2026-11-08" ), ( None, 500, 10, None ), ( 900, None, 10, None ), ( 900, 100, 100, None ),
                                                      ( 900, 100, 150, None ), ( 900, 400, 100, "2026-11-11" ), ( 901, 400, None, "2026-11-11" ), ( 600, 400, 100, "2026-11-10" ) ] )
def test_the_projected_zero_date_is_the_whole_days_the_backlog_needs_at_the_net_rate( backlog, drain, inflow, want ):
    assert st.projected_zero( backlog, drain, inflow, NOW.date() ) == want


@pytest.mark.parametrize( "before,after,want", [ ( None, "2026-11-20", False ), ( "2026-11-10", None, True ), ( "2026-11-10", "2026-11-11", False ), ( "2026-11-10", "2026-11-12", True ),
                                                ( "2026-11-10", "2026-11-09", False ) ] )
def test_a_projection_slips_when_it_moves_more_than_a_day_later_or_disappears( before, after, want ):
    assert st.slipped( before, after ) is want


@pytest.mark.parametrize( "last,want", [ ( at( 8, 12, 5 ), at( 8, 13, 30 ) ), ( at( 8, 22, 5 ), at( 9, 10, 30 ) ), ( at( 8, 3, 0 ), at( 8, 10, 30 ) ), ( None, at( 8, 13, 30 ) ) ] )
def test_the_next_run_is_expected_at_the_next_hourly_slot_with_half_an_hour_of_grace( last, want ):
    assert st.expected_by( datetime.datetime.fromisoformat( last ) if last else None, NOW ) == want


def test_the_days_total_the_calls_and_tokens_and_leave_none_where_nothing_was_recorded():
    usage = { "input_tokens": 5, "output_tokens": 7, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 11, "cost_usd": 0.5 }
    days  = st.per_day_usage( [ row( 7, 10, calls=10, usage=usage ), row( 7, 11, calls=20, usage=usage ), row( 6, 10, calls=None ) ] )
    assert [ d[ "day" ] for d in days ] == [ "2026-11-06", "2026-11-07" ]
    assert days[ 1 ] == { "day": "2026-11-07", "runs": 2, "judge_calls": 30, "cost_usd": 1.0, "input_tokens": 10, "output_tokens": 14, "cache_creation_tokens": 200, "cache_read_tokens": 22 }
    assert days[ 0 ][ "judge_calls" ] is None and days[ 0 ][ "input_tokens" ] is None


def test_the_health_is_silent_failing_falling_behind_or_healthy_in_that_order():
    ok = row( 8, 11 )
    assert st.health_of( [], 0, None, None, NOW ) == st.SILENT
    assert st.health_of( [ row( 8, 9 ) ], 0, None, None, NOW ) == st.SILENT, "the 10:00 slot was due by 10:30"
    assert st.health_of( [ row( 8, 11, status="failed", carried=None ) ], 5, 1, 9, NOW ) == st.FAILING
    assert st.health_of( [ ok ], 5, 100, 100, NOW ) == st.FALLING_BEHIND and st.health_of( [ ok ], 5, 100, None, NOW ) == st.HEALTHY
    assert st.health_of( [ ok ], 0, 0, 5, NOW ) == st.HEALTHY and st.health_of( [ ok ], 5, None, None, NOW ) == st.HEALTHY


def test_the_median_seconds_a_call_takes_uses_the_latest_sizeable_runs_that_did_not_fail():
    lines = [ row( 6, 10, calls=100, secs=300.0 ), row( 6, 11, calls=10, secs=999.0 ), row( 6, 12, status="failed", carried=None, calls=100, secs=9999.0 ), row( 6, 13, calls=100, secs=500.0 ),
              row( 6, 14, calls=100, secs=None ) ]
    assert st.median_seconds_per_call( lines ) == 4.0, "3 and 5 seconds a call"
    assert st.median_seconds_per_call( [ row( 6, 10, calls=1, secs=1.0 ) ] ) is None


def snapshot_of( tmp_path ):
    lines = [ row( 7, 10, carried=800, owed=800, judged=0, calls=0 ), row( 7, 11, carried=300, owed=800, judged=500, calls=500, secs=1750.0, usage={ "input_tokens": 1500, "output_tokens": 900, "cache_creation_input_tokens": 90, "cache_read_input_tokens": 80, "cost_usd": 2.5 } ),
             row( 7, 12, mode="baseline", carried=1000, owed=1500, judged=500, calls=500, secs=1750.0, trigger="reboot" ), row( 8, 10, carried=0, owed=450, judged=300, calls=300, secs=1050.0 ), row( 8, 11, mode="baseline", carried=700, owed=1000, judged=300, calls=300, secs=1000.0 ) ]
    return st.snapshot( folder_with( tmp_path, *lines ), NOW )


def test_the_snapshot_reports_the_backlog_by_kind_the_rates_the_projection_and_the_runs_newest_first( tmp_path ):
    snap = snapshot_of( tmp_path )
    assert snap[ "backlog" ] == { "carried": 0, "baseline_remaining": 700, "total": 700, "inflow_per_day": 75 }
    assert snap[ "drain" ][ "judged_per_day" ] == 800 and snap[ "projected_zero" ] == "2026-11-09" and snap[ "health" ] == st.HEALTHY
    assert [ r[ "started_at" ][ 5:13 ] for r in snap[ "runs" ] ][ 0 ] == "11-08T11" and snap[ "runs" ][ 3 ][ "input_tokens" ] == 1500 and snap[ "runs" ][ 4 ][ "calls_per_hour" ] is None
    assert snap[ "days" ][ -1 ][ "day" ] == "2026-11-08" and snap[ "unreadable_lines" ] == []


def test_the_summary_is_the_fleets_v1_record_with_a_null_for_what_the_ledger_cannot_give( tmp_path ):
    s = snapshot_of( tmp_path )[ "summary" ]
    assert ( s[ "schema" ], s[ "job" ], s[ "target" ], s[ "written_at" ], "health" in s ) == ( "job-summary/1", "duplicate-check", None, NOW.isoformat(), False )
    assert s[ "last_attempt" ] == { "started_at": at( 8, 11 ), "finished_at": datetime.datetime.fromisoformat( at( 8, 11 ) ).replace( minute=16, second=40 ).isoformat(), "trigger": "cron",
                                    "outcome": "clean", "stage": None, "failure": None, "evidence": "io/duplicate-check-daily/runs.jsonl:5" }
    assert s[ "last_finished" ] == { "started_at": at( 8, 11 ), "outcome": "clean", "evidence": "io/duplicate-check-daily/runs.jsonl:5" } and s[ "consecutive_failures" ] == 0
    assert s[ "scan_debt" ][ "count" ] == 0 and s[ "scan_debt" ][ "never_checked" ] == 700 and s[ "scan_debt" ][ "drained_last_run" ] == 300 and s[ "scan_debt" ][ "arrived_last_interval" ] == 150
    assert s[ "scan_debt" ][ "unit" ] == "definitions" and s[ "scan_debt" ][ "freshness" ] is None and s[ "scan_debt" ][ "as_of" ] == s[ "last_attempt" ][ "finished_at" ]
    assert s[ "scan_debt" ][ "points" ] == [ { "at": at( 7, 10 ), "count": 800 }, { "at": at( 7, 11 ), "count": 300 }, { "at": at( 8, 10 ), "count": 0 } ]
    assert s[ "fix_debt" ] == { "unit": "rows", "kind": "rows", "own_mark": "created_by:duplicate-check-daily", "unfiled": None, "opened_in_run": None, "points": [ { "at": l, "opened_total": 0 } for l in ( at( 7, 10 ), at( 7, 11 ), at( 7, 12 ), at( 8, 10 ), at( 8, 11 ) ) ] }
    assert s[ "work_found_last_run" ] is None, "the fixture's runs recorded no findings"


def test_a_failure_after_a_finished_run_names_its_stage_its_cause_and_the_count_of_failures_since():
    first = row( 8, 9, carried=5, owed=5, findings=[ {}, {} ], filing={ "filed": [ "a", "b", "c" ], "queued_for_retry": [ "d" ] } )
    guard = row( 8, 10, trigger="reboot", status="failed", carried=None, stage="branch_guard", refusal="stale_branch" )
    plain = row( 8, 11, status="failed", carried=None )
    s     = st.job_summary( [ first, guard, plain ], NOW )
    assert s[ "consecutive_failures" ] == 2 and s[ "last_attempt" ][ "stage" ] == "unknown" and s[ "last_attempt" ][ "failure" ] is None and s[ "last_attempt" ][ "outcome" ] == "failed"
    assert s[ "last_finished" ][ "evidence" ].endswith( ":1" ) and s[ "work_found_last_run" ] == 2 and s[ "fix_debt" ][ "unfiled" ] == 1 and s[ "fix_debt" ][ "opened_in_run" ] == 3
    named = st.job_summary( [ first, guard ], NOW )[ "last_attempt" ]
    assert ( named[ "stage" ], named[ "failure" ], named[ "trigger" ] ) == ( "branch_guard", "stale_branch", "boot" )


def test_a_run_with_no_recorded_time_has_no_finish_and_the_as_of_falls_back_to_its_start():
    s = st.job_summary( [ row( 8, 9, secs=None ) ], NOW )
    assert s[ "last_attempt" ][ "finished_at" ] is None and s[ "scan_debt" ][ "as_of" ] == at( 8, 9 ) and s[ "scan_debt" ][ "arrived_last_interval" ] is None


def test_the_summary_is_written_whole_beside_the_ledger_and_leaves_no_temporary_file( tmp_path ):
    import json
    hist.append_line( tmp_path, row( 8, 11, carried=3, owed=3 ) )
    path = st.write_job_summary( tmp_path, NOW )
    assert path == tmp_path / "job-summary.json" and json.loads( path.read_text() )[ "scan_debt" ][ "count" ] == 3
    assert sorted( p.name for p in tmp_path.iterdir() ) == [ "job-summary.json", "runs.jsonl" ]


def test_an_empty_history_gives_a_snapshot_of_nothing_known( tmp_path ):
    snap = st.snapshot( tmp_path, NOW )
    assert snap[ "backlog" ][ "total" ] is None and snap[ "projected_zero" ] is None and snap[ "health" ] == st.SILENT and snap[ "runs" ] == []
    assert snap[ "summary" ][ "last_attempt" ] is None and snap[ "summary" ][ "last_finished" ] is None and snap[ "summary" ][ "scan_debt" ][ "count" ] is None and snap[ "summary" ][ "work_found_last_run" ] is None


def test_the_note_says_what_a_run_did_and_is_none_for_a_quiet_one( tmp_path ):
    snap = snapshot_of( tmp_path )
    busy = row( 8, 11, calls=300, judged=290 )
    assert st.note_of( busy, snap ) == "Duplicate check daily run: 290 judged in 300 calls; 700 left; zero by 2026-11-09."
    assert st.note_of( row( 8, 12 ), { **snap, "backlog": { **snap[ "backlog" ], "total": 0 } } ) is None, "no calls and nothing left"
    quiet_but_owing = st.note_of( row( 8, 12 ), snap )
    assert quiet_but_owing is not None and "0 judged in 0 calls" in quiet_but_owing
    unknown = st.note_of( row( 8, 12, status="failed", carried=None ), { **snap, "backlog": { **snap[ "backlog" ], "total": None }, "projected_zero": None } )
    assert "unknown left; zero by not at the present rates" in unknown


def test_the_page_shows_the_backlog_by_kind_the_runs_and_the_days_and_escapes_what_the_history_says( tmp_path ):
    snap = snapshot_of( tmp_path )
    snap[ "runs" ][ 0 ][ "branch" ] = "<script>x</script>"
    snap[ "runs" ][ 1 ][ "branch" ] = None
    page = st.render_html( snap )
    assert page.startswith( "<!DOCTYPE html>" ) and "<script>" not in page and "&lt;script&gt;" in page
    assert "Projected zero: <b>2026-11-09</b>" in page and "<td>700</td>" in page and "baseline remaining" in page and "2026-11-08" in page and "1,500" in page
    none = st.render_html( st.snapshot( tmp_path / "nothing", NOW ) )
    assert "not at the present rates" in none and "<td>-</td>" in none


def test_the_folder_of_a_root_is_the_runs_folder():
    assert str( st.folder_of( "/r" ) ) == "/r/io/duplicate-check-daily"
