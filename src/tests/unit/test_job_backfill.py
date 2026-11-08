"""The one-time backfill: each source turned into a summary through the shared writer."""
import datetime
import json
import os
import pathlib

import pytest

from lupin_mcp import job_backfill as bf
from lupin_mcp import job_summary as js


def stamp( path, when ):
    """Ensures: sets the file's last-write time to when (naive local) and returns the path."""
    t = when.timestamp()
    os.utime( path, ( t, t ) )
    return path


def put( path, text, when=None ):
    """Ensures: writes text, creating folders, and optionally dates the file."""
    path = pathlib.Path( path ); path.parent.mkdir( parents=True, exist_ok=True ); path.write_text( text )
    return stamp( path, when ) if when else path


T = datetime.datetime( 2026, 11, 7, 12, 12, 11 )


def read( path ):
    """Ensures: returns the written record."""
    return json.loads( pathlib.Path( path ).read_text() )


def test_the_librarian_after_a_failed_tick_gets_its_last_good_tick_then_the_failure(tmp_path):
    put( tmp_path / "librarian" / "librarian.log", 'noise\n{"ran": false, "reason": "export query failed: 200"}\n', T )
    put( tmp_path / "librarian" / "tick-state.json", json.dumps( { "last_run_date": "2026-10-20", "findings": 526, "deferred": 137, "created": 10, "cleared": 3 } ) )
    steps = bf.librarian_steps( tmp_path )
    assert [ s[ "attempt" ][ "outcome" ] for s in steps ] == [ "clean", "failed" ] and steps[ 1 ][ "attempt" ][ "failure" ] == "export query failed: 200" and steps[ 1 ][ "attempt" ][ "stage" ] == "tick"
    doc = bf.replay( tmp_path / "s.json", "wiki-librarian", steps )
    assert doc[ "last_finished" ][ "started_at" ].startswith( "2026-10-20T00:00:00" ) and doc[ "scan_debt" ][ "count" ] == 526 and doc[ "fix_debt" ][ "unfiled" ] == 137 and doc[ "consecutive_failures" ] == 1


def test_the_librarian_variants_finished_skipped_no_log_no_state(tmp_path):
    log = put( tmp_path / "librarian" / "librarian.log", '{"ran": true, "findings": 5, "cleared": 1, "deferred": 0, "created": 2}\n', T )
    assert [ s[ "attempt" ][ "outcome" ] for s in bf.librarian_steps( tmp_path ) ] == [ "clean" ]
    put( log, '{"ran": false, "reason": "not due"}\n', T )
    steps = bf.librarian_steps( tmp_path )                                                 # no tick-state.json: no earlier good tick
    assert [ s[ "attempt" ][ "outcome" ] for s in steps ] == [ "skipped" ] and steps[ 0 ][ "attempt" ][ "stage" ] is None
    put( log, 'no json here\n', T )
    assert bf.librarian_steps( tmp_path ) is None
    assert bf.librarian_steps( tmp_path / "nowhere" ) is None
    put( log, '{"ran": false, "reason": "x"}\n', T )
    put( tmp_path / "librarian" / "tick-state.json", json.dumps( { "findings": 1 } ) )     # state without a date adds nothing
    assert len( bf.librarian_steps( tmp_path ) ) == 1


def test_last_json_line_skips_bad_lines(tmp_path):
    p = put( tmp_path / "l", '{"a": 1}\n{broken\n  \n' )
    assert bf.last_json_line( p ) == { "a": 1 } and bf.last_json_line( put( tmp_path / "m", "x\n" ) ) is None


def test_the_refresh_state_gives_freshness_and_a_failure_keeps_the_good_build_before_it(tmp_path):
    put( tmp_path / "refresh" / "refresh-state.json", json.dumps( { "built_at": "2026-11-07T17:16:08+00:00", "last_attempt_at": "2026-11-07T12:13:52", "last_outcome": "built", "rows": 13218 } ) )
    steps = bf.refresh_steps( tmp_path )
    assert len( steps ) == 1 and steps[ 0 ][ "scan" ][ "freshness" ] == { "built_at": "2026-11-07T17:16:08+00:00", "stale_after_hours": 36 } and steps[ 0 ][ "work" ] == 13218
    put( tmp_path / "refresh" / "refresh-state.json", json.dumps( { "built_at": "2026-11-06T10:00:00+00:00", "last_attempt_at": "2026-11-07T12:13:52", "last_outcome": "failed", "last_error": "OSError: x" } ) )
    failed = bf.refresh_steps( tmp_path )
    assert [ s[ "attempt" ][ "outcome" ] for s in failed ] == [ "clean", "failed" ] and failed[ 1 ][ "attempt" ][ "failure" ] == "OSError: x"
    put( tmp_path / "refresh" / "refresh-state.json", json.dumps( { "last_outcome": "failed", "last_error": "e" } ), T )                 # never built, no attempt time: file time
    assert [ s[ "attempt" ][ "outcome" ] for s in bf.refresh_steps( tmp_path ) ] == [ "failed" ]
    assert bf.refresh_steps( tmp_path / "nowhere" ) is None


def test_reuse_behaviour_reads_its_last_marker_line(tmp_path):
    log = tmp_path / "behaviour" / "weekly.log"
    put( log, "- Loading x\nREFUSING: CandidateError: DEPENDENCY_MISSING: no ConfigurationManager. Nothing was made.\n\n", T )
    got = bf.behaviour_steps( tmp_path )
    assert got[ 0 ][ "attempt" ][ "outcome" ] == "failed" and got[ 0 ][ "attempt" ][ "failure" ].startswith( "REFUSING" ) and got[ 0 ][ "attempt" ][ "stage" ] == "page"
    put( log, "REFUSING: x\nReuse behaviour, week of 2026-11-02\nrows\n", T )
    assert bf.behaviour_steps( tmp_path )[ 0 ][ "attempt" ][ "outcome" ] == "clean"
    put( log, "SKIPPED: the page for 2026-11-02 is already saved at x.\n", T )
    assert bf.behaviour_steps( tmp_path )[ 0 ][ "attempt" ][ "outcome" ] == "skipped"
    put( log, "nothing useful\n", T ); assert bf.behaviour_steps( tmp_path ) is None
    assert bf.behaviour_steps( tmp_path / "nowhere" ) is None


def test_shadow_audit_reads_its_json_line(tmp_path):
    log = put( tmp_path / "shadow-audit" / "shadow-audit.log", '{"audited": 7, "failed": 0, "stopped_by": null}\n', T )
    got = bf.shadow_steps( tmp_path )
    assert got[ 0 ][ "attempt" ][ "outcome" ] == "clean" and got[ 0 ][ "scan" ][ "drained_last_run" ] == 7 and got[ 0 ][ "work" ] == 7
    put( log, '{"audited": 1, "failed": 2}\n', T )
    assert bf.shadow_steps( tmp_path )[ 0 ][ "attempt" ][ "failure" ] == "2 audits failed"
    put( log, "x\n", T ); assert bf.shadow_steps( tmp_path ) is None and bf.shadow_steps( tmp_path / "nowhere" ) is None


def test_a_sweep_log_gives_debt_left_and_drained_and_a_report_log_only_counts_when_it_has_text(tmp_path):
    sweep = put( tmp_path / "sweep.log", "before : 1 files\neligible : 61,278 per-event files\nafter : 2\nreclaimed: 61,275 files\n", T )
    got = bf.sweep_steps( sweep )
    assert got[ 0 ][ "scan" ] == { "unit": "files", "count": 3, "drained_last_run": 61275 } and got[ 0 ][ "work" ] == 61278
    put( sweep, "eligible : 4 old\n", T )
    assert bf.sweep_steps( sweep )[ 0 ][ "scan" ] == { "unit": "files", "count": 4, "drained_last_run": 0 }
    put( sweep, "nothing\n", T ); assert bf.sweep_steps( sweep ) is None and bf.sweep_steps( tmp_path / "none.log" ) is None
    report = put( tmp_path / "r.log", "a report\n", T )
    assert bf.report_steps( report )[ 0 ][ "attempt" ][ "outcome" ] == "clean" and bf.report_steps( put( tmp_path / "empty.log", "" ) ) is None and bf.report_steps( tmp_path / "none.log" ) is None


def build_world( tmp_path ):
    """Ensures: returns ( root, data, home ) with a registry and a record for every source."""
    root, data, home = tmp_path / "root", tmp_path / "data", tmp_path / "home"
    jobs = [ { "job": j, "title": j, "owner": "cheech", "summary_path": f"{{root}}/s/{j}.json" } for j in
             ( "duplicate-check", "wiki-librarian", "vector-refresh", "reuse-behaviour", "shadow-audit", "io-tmp-sweep", "hook-log-sweep", "disk-report", "worktree-census", "context-tick" ) ]
    put( root / "src/conf/job-registry.json", json.dumps( { "schema": "job-registry/1", "defaults": {}, "jobs": jobs } ) )
    put( data / "librarian/librarian.log", '{"ran": true, "findings": 1}\n', T )
    put( data / "refresh/refresh-state.json", json.dumps( { "last_outcome": "built", "last_attempt_at": "2026-11-07T12:13:52", "built_at": "2026-11-07T17:16:08+00:00" } ) )
    put( data / "behaviour/weekly.log", "Reuse behaviour, x\n", T )
    put( data / "shadow-audit/shadow-audit.log", '{"audited": 0, "failed": 0}\n', T )
    logs = root / "io/claude_code_hooks/logs"
    put( logs / "io-tmp-sweep.log", "eligible : 0\nreclaimed: 0\n", T )
    put( logs / "disk-hygiene-sweep.log", "eligible : 5\nreclaimed: 5\n", T )
    put( logs / "disk-hygiene-report.log", "report\n", T )
    put( home / ".lupin/logs/worktree-hygiene-report.log", "report\n", T )
    put( root / "s/duplicate-check-ledger", "" )
    return root, data, home


def test_backfill_writes_every_source_skips_what_has_a_summary_and_force_rewrites(tmp_path):
    root, data, home = build_world( tmp_path )
    ( root / "s" / "duplicate-check.json" ).parent.mkdir( parents=True, exist_ok=True )
    calls = []
    first = dict( ( j, s ) for j, s, _ in bf.backfill( root, data, home, now=T.astimezone(), duplicate_writer=lambda folder, now: calls.append( folder ) ) )
    assert first == { "disk-report": "written", "duplicate-check": "no-record", "hook-log-sweep": "written", "io-tmp-sweep": "written", "reuse-behaviour": "written", "shadow-audit": "written",
                      "vector-refresh": "written", "wiki-librarian": "written", "worktree-census": "written" } and calls == []                     # no runs.jsonl in the world yet
    assert read( root / "s" / "wiki-librarian.json" )[ "schema" ] == "job-summary/1"
    assert not ( root / "s" / "context-tick.json" ).exists()                                                                                     # no record: left unknown
    again = dict( ( j, s ) for j, s, _ in bf.backfill( root, data, home ) )
    assert set( again.values() ) == { "skipped", "no-record" } and again[ "wiki-librarian" ] == "skipped"
    forced = dict( ( j, s ) for j, s, _ in bf.backfill( root, data, home, force=True ) )
    assert forced[ "wiki-librarian" ] == "written"


def test_backfill_dry_run_writes_nothing_and_the_duplicate_check_uses_its_own_writer(tmp_path):
    root, data, home = build_world( tmp_path )
    put( root / "s" / "runs.jsonl", "" )
    dry = bf.backfill( root, data, home, dry_run=True )
    assert not ( root / "s" / "wiki-librarian.json" ).exists() and [ s for j, s, _ in dry if j == "duplicate-check" ] == [ "would-write" ] and {s for _, s, _ in dry} == { "would-write" }
    calls = []
    got = bf.backfill( root, data, home, now=T.astimezone(), duplicate_writer=lambda folder, now: calls.append( ( folder, now ) ) )
    assert calls == [ ( root / "s", T.astimezone() ) ] and [ s for j, s, _ in got if j == "duplicate-check" ] == [ "written" ]


def test_the_real_duplicate_writer_is_used_by_default(tmp_path, monkeypatch):
    root, data, home = build_world( tmp_path )
    put( root / "s" / "runs.jsonl", "" )
    from lupin_mcp import duplicate_check_status as st
    seen = []
    monkeypatch.setattr( st, "write_job_summary", lambda folder, now: seen.append( folder ) )
    bf.backfill( root, data, home )
    assert seen == [ root / "s" ]


def test_a_source_that_cannot_be_written_reports_no_record(tmp_path):
    root, data, home = build_world( tmp_path )
    ( root / "s" ).mkdir( exist_ok=True )
    ( root / "s" / "wiki-librarian.json" ).mkdir()                                                   # a folder where the file should go
    got = { j: ( s, d ) for j, s, d in bf.backfill( root, data, home, force=True ) }
    assert got[ "wiki-librarian" ] == ( "no-record", "could not write" )


def test_main_prints_one_line_per_job(tmp_path, monkeypatch):
    root, data, home = build_world( tmp_path )
    lines = []
    assert bf.main( [ "--dry-run", "--root", str( root ) ], { "LUPIN_REUSE_REVIEW_DATA_ROOT": str( data ), "HOME": str( home ) }, lines.append ) == 0
    assert any( l.startswith( "wiki-librarian" ) and "would-write" in l for l in lines ) and len( lines ) == 9
    import cosa.repo.symindex.paths as paths
    monkeypatch.setattr( paths, "data_dir", lambda r: data )
    lines.clear()
    assert bf.main( [ "--dry-run" ], { "LUPIN_ROOT": str( root ) }, lines.append ) == 0 and len( lines ) == 9
    monkeypatch.chdir( root )
    assert bf.main( [ "--dry-run" ], { }, lines.append ) == 0


def test_a_folder_this_process_may_not_enter_reads_as_no_file(tmp_path, monkeypatch):
    def denied( self ): raise PermissionError( "no" )
    monkeypatch.setattr( pathlib.Path, "is_file", denied )
    assert bf.is_file( tmp_path / "x" ) is False


def test_the_failed_librarian_names_both_sources_in_its_evidence(tmp_path):
    put( tmp_path / "librarian" / "librarian.log", '{"ran": false, "reason": "boom"}\n', T )
    put( tmp_path / "librarian" / "tick-state.json", json.dumps( { "last_run_date": "2026-10-20", "findings": 1 } ) )
    good, failed = bf.librarian_steps( tmp_path )
    assert good[ "attempt" ][ "evidence" ] == "tick-state.json last_run_date (midnight); trigger not recorded"
    assert failed[ "attempt" ][ "evidence" ] == "librarian.log (dated by the file's last write); trigger not recorded"


def test_a_dry_run_never_calls_the_duplicate_check_writer(tmp_path):
    root, data, home = build_world( tmp_path )
    put( root / "s" / "runs.jsonl", "" )
    calls = []
    bf.backfill( root, data, home, dry_run=True, duplicate_writer=lambda folder, now: calls.append( folder ) )
    assert calls == []


def test_a_sweep_log_with_several_runs_uses_the_last_one_and_never_goes_below_zero(tmp_path):
    sweep = put( tmp_path / "sweep.log", "eligible : 100\nreclaimed: 90\n\neligible : 4\nreclaimed: 3\n", T )
    assert bf.sweep_steps( sweep )[ 0 ][ "scan" ] == { "unit": "files", "count": 1, "drained_last_run": 3 }
    put( sweep, "eligible : 3\nreclaimed: 5\n", T )
    assert bf.sweep_steps( sweep )[ 0 ][ "scan" ][ "count" ] == 0


def test_a_naive_time_is_the_hosts_local_time_not_utc(tmp_path):
    naive = datetime.datetime( 2026, 10, 20 )
    assert bf.aware( naive ).isoformat() == naive.astimezone().isoformat() and bf.aware( naive ).utcoffset() == naive.astimezone().utcoffset()
    put( tmp_path / "librarian" / "librarian.log", '{"ran": false, "reason": "x"}\n', T )
    put( tmp_path / "librarian" / "tick-state.json", json.dumps( { "last_run_date": "2026-10-20" } ) )
    assert bf.librarian_steps( tmp_path )[ 0 ][ "attempt" ][ "started_at" ] == naive.astimezone().replace( microsecond=0 ).isoformat()


def test_a_report_log_that_shows_an_error_reads_as_failed(tmp_path):
    for text, outcome in ( ( "fine\nnotify: HTTP 200\n", "clean" ), ( "Traceback (most recent call last)\n", "failed" ), ( "notify: HTTP 503\n", "failed" ), ( "An Error happened\n", "failed" ), ( "terror\n", "clean" ) ):
        got = bf.report_steps( put( tmp_path / "r.log", text, T ) )[ 0 ][ "attempt" ]
        assert got[ "outcome" ] == outcome
    assert bf.report_steps( tmp_path / "r.log" )[ 0 ][ "attempt" ][ "outcome" ] == "clean" and got[ "stage" ] is None
    assert "the log mentions: " in bf.report_steps( put( tmp_path / "e.log", "Traceback x\n", T ) )[ 0 ][ "attempt" ][ "failure" ]


def test_one_corrupt_record_is_reported_and_the_others_still_run(tmp_path):
    root, data, home = build_world( tmp_path )
    put( data / "refresh/refresh-state.json", "{corrupt" )
    put( data / "librarian/tick-state.json", "{corrupt" )
    put( data / "librarian/librarian.log", '{"ran": false, "reason": "x"}\n', T )
    got = { j: ( s, d ) for j, s, d in bf.backfill( root, data, home ) }
    assert got[ "vector-refresh" ][ 0 ] == "no-record" and got[ "vector-refresh" ][ 1 ].startswith( "unreadable: JSONDecodeError" ) and got[ "wiki-librarian" ][ 0 ] == "no-record"
    assert got[ "shadow-audit" ][ 0 ] == "written" and got[ "io-tmp-sweep" ][ 0 ] == "written"


def test_a_refresh_state_with_no_attempt_time_is_dated_by_the_file(tmp_path):
    put( tmp_path / "refresh" / "refresh-state.json", json.dumps( { "last_outcome": "built", "built_at": "2026-11-07T17:16:08+00:00" } ), T )
    assert bf.refresh_steps( tmp_path )[ 0 ][ "attempt" ][ "started_at" ] == T.astimezone().replace( microsecond=0 ).isoformat()


def test_a_failed_report_has_the_report_stage(tmp_path):
    assert bf.report_steps( put( tmp_path / "e.log", "Traceback x\n", T ) )[ 0 ][ "attempt" ][ "stage" ] == "report"


def test_records_of_the_wrong_type_are_reported_not_raised(tmp_path):
    root, data, home = build_world( tmp_path )
    put( data / "refresh/refresh-state.json", json.dumps( { "last_outcome": "built", "last_attempt_at": 5 } ) )              # a number where a time belongs: TypeError
    put( data / "librarian/tick-state.json", "[1]" )                                                                            # a list where an object belongs: AttributeError
    put( data / "librarian/librarian.log", '{"ran": false, "reason": "x"}\n', T )
    got = { j: d for j, s, d in bf.backfill( root, data, home ) }
    assert got[ "vector-refresh" ].startswith( "unreadable: TypeError" ) and got[ "wiki-librarian" ].startswith( "unreadable: AttributeError" )
