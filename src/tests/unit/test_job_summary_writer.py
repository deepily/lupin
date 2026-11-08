"""The shared job-summary/1 writer."""
import json

import pytest

from lupin_mcp import job_summary as js

T0 = "2026-11-06T19:06:59-05:00"
T1 = "2026-11-07T19:31:02-05:00"


def attempt( outcome="carried", at=T0, **over ):
    """Ensures: returns a valid attempt."""
    return { "started_at": at, "finished_at": at, "trigger": "cron", "outcome": outcome, "evidence": "runs.jsonl:1", **over }


def scan( count, drained=None, **over ):
    """Ensures: returns a scan-debt block as a job reports it."""
    return { "unit": "definitions", "count": count, "drained_last_run": drained, **over }


def test_a_finished_run_sets_last_finished_resets_failures_and_has_no_health_field():
    prev = js.build_summary( "j", attempt( "failed" ), now=None )
    got  = js.build_summary( "j", attempt( "clean", T1 ), previous=prev, work_found_last_run=3 )
    assert got[ "schema" ] == "job-summary/1" and "health" not in got
    assert got[ "last_finished" ] == { "started_at": T1, "outcome": "clean", "evidence": "runs.jsonl:1" }
    assert ( got[ "consecutive_failures" ], got[ "work_found_last_run" ] ) == ( 0, 3 )


def test_failed_runs_count_up_and_keep_last_finished_and_the_old_work_figure():
    one = js.build_summary( "j", attempt( "carried" ), work_found_last_run=9 )
    two = js.build_summary( "j", attempt( "failed", T1 ), previous=one )
    three = js.build_summary( "j", attempt( "failed", T1 ), previous=two )
    assert three[ "consecutive_failures" ] == 2
    assert three[ "last_finished" ][ "started_at" ] == T0 and three[ "work_found_last_run" ] == 9


def test_a_skipped_run_leaves_the_failure_count_alone_but_is_a_recent_attempt():
    one = js.build_summary( "j", attempt( "failed" ) )
    two = js.build_summary( "j", attempt( "skipped", T1 ), previous=one )
    assert two[ "consecutive_failures" ] == 1 and two[ "last_attempt" ][ "outcome" ] == "skipped"
    assert [ r[ "outcome" ] for r in two[ "recent" ] ] == [ "failed", "skipped" ]


def test_scan_debt_points_arrivals_are_derived_and_a_failed_run_carries_the_old_block():
    one = js.build_summary( "j", attempt( "carried" ), scan_debt=scan( 1030, 100 ) )
    two = js.build_summary( "j", attempt( "carried", T1 ), scan_debt=scan( 2124, 304 ), previous=one )
    assert two[ "scan_debt" ][ "arrived_last_interval" ] == 2124 - 1030 + 304
    assert [ p[ "count" ] for p in two[ "scan_debt" ][ "points" ] ] == [ 1030, 2124 ]
    assert two[ "scan_debt" ][ "points" ][ -1 ][ "drained" ] == 304
    three = js.build_summary( "j", attempt( "failed", "2026-11-08T10:00:00-05:00" ), previous=two )
    assert three[ "scan_debt" ] == two[ "scan_debt" ]


def test_a_job_that_gives_an_arrival_figure_keeps_it_and_a_null_count_adds_no_point():
    one = js.build_summary( "j", attempt(), scan_debt=scan( 10, 1 ) )
    two = js.build_summary( "j", attempt( at=T1 ), scan_debt=scan( None, 1, arrived_last_interval=7 ), previous=one )
    assert two[ "scan_debt" ][ "arrived_last_interval" ] == 7 and len( two[ "scan_debt" ][ "points" ] ) == 1
    none = js.build_summary( "j", attempt(), scan_debt=scan( 5, None ) )
    assert none[ "scan_debt" ][ "arrived_last_interval" ] is None


def test_points_keep_only_the_newest_fourteen():
    doc = None
    for i in range( 20 ): doc = js.build_summary( "j", attempt( at=f"2026-11-{i + 1:02d}T10:00:00-05:00" ), scan_debt=scan( i, 0 ), previous=doc )
    assert [ p[ "count" ] for p in doc[ "scan_debt" ][ "points" ] ] == list( range( 6, 20 ) ) and len( doc[ "recent" ] ) == 7


def test_fix_debt_totals_run_and_default_kind_is_rows_and_none_given_carries_forward():
    one = js.build_summary( "j", attempt(), fix_debt={ "own_mark": "job:j", "opened_in_run": 28 } )
    two = js.build_summary( "j", attempt( at=T1 ), fix_debt={ "own_mark": "job:j", "opened_in_run": 45, "kind": "reported" }, previous=one )
    assert [ p[ "opened_total" ] for p in two[ "fix_debt" ][ "points" ] ] == [ 28, 73 ] and one[ "fix_debt" ][ "kind" ] == "rows" and two[ "fix_debt" ][ "kind" ] == "reported"
    three = js.build_summary( "j", attempt( at="2026-11-09T10:00:00-05:00" ), previous=two )
    assert three[ "fix_debt" ] == two[ "fix_debt" ]
    blank = js.build_summary( "j", attempt(), fix_debt={ "own_mark": "m" } )
    assert blank[ "fix_debt" ][ "points" ] == []


@pytest.mark.parametrize( "bad", [ { "outcome": "ok" }, { "trigger": "robot" }, { "started_at": None } ] )
def test_a_malformed_attempt_is_refused(bad):
    with pytest.raises( ValueError ): js.check_attempt( { **attempt(), **bad } )


def test_write_summary_writes_whole_by_rename_and_read_summary_round_trips(tmp_path):
    path = tmp_path / "deep" / "job-summary.json"
    doc  = js.write_summary( path, "j", attempt(), scan_debt=scan( 3, 1 ) )
    assert js.read_summary( path ) == json.loads( path.read_text() ) == doc
    assert [ p.name for p in path.parent.iterdir() ] == [ "job-summary.json" ]
    again = js.write_summary( path, "j", attempt( at=T1 ), scan_debt=scan( 2, 1 ) )
    assert [ p[ "count" ] for p in again[ "scan_debt" ][ "points" ] ] == [ 3, 2 ]


def test_read_summary_refuses_missing_garbage_and_foreign_schema(tmp_path):
    assert js.read_summary( tmp_path / "nope.json" ) is None
    ( tmp_path / "a.json" ).write_text( "{not json" ); assert js.read_summary( tmp_path / "a.json" ) is None
    ( tmp_path / "b.json" ).write_text( json.dumps( { "schema": "other/1" } ) ); assert js.read_summary( tmp_path / "b.json" ) is None
    ( tmp_path / "c.json" ).write_text( "[1]" ); assert js.read_summary( tmp_path / "c.json" ) is None


def test_a_write_failure_returns_none_and_says_why_but_a_bad_attempt_still_raises(tmp_path, capsys):
    blocker = tmp_path / "file"; blocker.write_text( "x" )
    assert js.write_summary( blocker / "sub" / "s.json", "j", attempt() ) is None
    assert "could not write" in capsys.readouterr().err
    import io
    sink = io.StringIO()
    assert js.write_summary( blocker / "sub" / "s.json", "j", attempt(), err=sink ) is None and "could not write" in sink.getvalue()
    with pytest.raises( ValueError ): js.write_summary( tmp_path / "x.json", "j", attempt( "bogus" ) )


def test_append_run_adds_one_line_per_run_and_reports_false_on_io_failure(tmp_path):
    path = tmp_path / "d" / "runs.jsonl"
    assert js.append_run( path, attempt(), { "findings": 4 } ) and js.append_run( path, attempt( "failed" ) )
    lines = [ json.loads( x ) for x in path.read_text().splitlines() ]
    assert [ l[ "outcome" ] for l in lines ] == [ "carried", "failed" ] and lines[ 0 ][ "findings" ] == 4 and lines[ 0 ][ "schema_version" ] == 1
    blocker = tmp_path / "f"; blocker.write_text( "x" )
    assert js.append_run( blocker / "r.jsonl", attempt() ) is False


def test_iso_now_and_trigger_from_env():
    import datetime
    assert js.iso_now( datetime.datetime( 2026, 11, 7, 10, 0, 0, 5, tzinfo=datetime.timezone.utc ) ) == "2026-11-07T10:00:00+00:00"
    assert js.iso_now().endswith( ( "+00:00", ) ) or "-" in js.iso_now()[ 10: ] or "+" in js.iso_now()
    assert js.trigger_from_env( "cron", { "LUPIN_JOB_TRIGGER": "hand" } ) == "hand"
    assert js.trigger_from_env( "cron", { "LUPIN_JOB_TRIGGER": "weird" } ) == "cron" and js.trigger_from_env( "boot", {} ) == "boot"
    import os
    assert js.trigger_from_env( "cron" ) in js.TRIGGERS and os is not None
