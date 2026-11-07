"""The duplicate check run history: line writer, backfill, rising-backlog test, table."""
import json

import pytest

from lupin_mcp import duplicate_check_history as hist

KEYS = set( hist.line_of( { "status": "failed", "trigger": "hand", "started_at": "2026-11-06T19:06:59-05:00" }, "x.json" ) )


def ok_doc( **over ):
    """Ensures: returns a successful result document."""
    base = { "status": "carried", "trigger": "cron", "started_at": "2026-11-06T19:06:59-05:00", "elapsed_seconds": 1040.589, "cap": 300, "judge_calls": 300, "judged": 304,
             "window": { "start": "aaa", "end": "bbb", "commits": 65 }, "carried": [ "a", "b" ], "unreadable": [ { "id": "u" } ],
             "clusters": [ [ "x", "y" ], [ "p", "q", "r" ] ], "findings": [ { "commit": "c1" }, { "commit": "c1" }, { "commit": None } ],
             "filing": { "filed": [ 1, 2 ], "already_filed": [], "queued_for_retry": [ 1 ], "refused": [] } }
    return { **base, **over }


def line( carried, mode="daily", status="carried" ):
    """Ensures: returns a minimal history line."""
    return { "mode": mode, "status": status, "carried": carried }


def test_a_successful_run_flattens_to_one_line_with_counts_group_sizes_and_findings_by_commit():
    got = hist.line_of( ok_doc(), "2026-11-06-190659-cron.json" )
    assert got == { "schema_version": 1, "run_file": "2026-11-06-190659-cron.json", "started_at": "2026-11-06T19:06:59-05:00", "elapsed_seconds": 1040.589, "trigger": "cron",
                    "mode": "daily", "status": "carried", "failure": None, "window_start": "aaa", "window_end": "bbb", "commits": 65, "judged": 304, "carried": 2, "cap": 300,
                    "ceiling": None, "judge_calls": 300, "findings": 3, "groups": 2, "group_sizes": [ 2, 3 ], "findings_by_commit": { "c1": 2, "unknown": 1 },
                    "filed": 2, "already_filed": 0, "queued_for_retry": 1, "refused": 0, "unreadable": 1, "backfilled": False }


def test_a_failed_run_has_the_same_keys_and_none_for_what_it_never_measured():
    got = hist.line_of( { "status": "failed", "trigger": "hand", "started_at": "t", "stage": "judging", "error": "boom", "cap": 100, "judge_calls": 7 }, "f.json" )
    assert set( got ) == KEYS
    assert ( got[ "failure" ], got[ "carried" ], got[ "findings" ], got[ "group_sizes" ], got[ "window_start" ], got[ "filed" ], got[ "judge_calls" ] ) == ( "judging: boom", None, None, None, None, None, 7 )


@pytest.mark.parametrize( "doc,want", [ ( { "status": "ok" }, None ),
                                         ( { "status": "failed", "stage": "judging", "error": "e" }, "judging: e" ),
                                         ( { "status": "failed", "prerequisite": "claude_binary", "detail": "no version" }, "claude_binary: no version" ),
                                         ( { "status": "failed", "stage": "branch_guard", "refusal": "stale_branch" }, "branch_guard: stale_branch" ),
                                         ( { "status": "failed" }, "unknown" ) ] )
def test_the_failure_reason_names_the_stage_or_prerequisite_and_the_error_refusal_or_detail( doc, want ):
    assert hist.failure_of( doc ) == want


@pytest.mark.parametrize( "filing", [ None, { "error": "RuntimeError: x" } ] )
def test_a_run_with_no_filer_or_a_filer_that_raised_has_no_filing_counts( filing ):
    assert hist.counts_of( filing ) == { k: None for k in hist.FILING_KEYS }


def test_a_filing_count_may_be_a_list_a_number_or_missing():
    assert hist.counts_of( { "filed": [ 1 ], "refused": 4 } ) == { "filed": 1, "already_filed": None, "queued_for_retry": None, "refused": 4 }


def test_the_start_time_is_read_off_the_file_name_and_a_bad_name_is_refused():
    assert hist.started_from_name( "2026-11-06-190659-hand.json" ).startswith( "2026-11-06T19:06:59" )
    with pytest.raises( ValueError, match="not a result file name" ): hist.started_from_name( "last-success.json" )


def test_an_append_keeps_the_earlier_lines_and_a_missing_history_reads_as_empty( tmp_path ):
    assert hist.read_lines( tmp_path / "none" ) == []
    hist.append_line( tmp_path / "f", { "n": 1 } )
    path = hist.append_line( tmp_path / "f", { "n": 2 } )
    assert path.name == "runs.jsonl" and [ l[ "n" ] for l in hist.read_lines( tmp_path / "f" ) ] == [ 1, 2 ]


def test_the_backfill_adds_each_result_file_once_oldest_first_marks_it_and_skips_files_that_are_not_runs( tmp_path ):
    ( tmp_path / "2026-11-04-100406-hand.json" ).write_text( json.dumps( { "status": "failed", "trigger": "hand", "stage": "judging", "error": "E" } ) )
    ( tmp_path / "2026-11-02-211352-hand.json" ).write_text( json.dumps( { "status": "ok", "trigger": "hand", "started_at": "keep-me" } ) )
    ( tmp_path / "last-success.json" ).write_text( "{}" )
    first = hist.backfill( tmp_path )
    assert first == { "added": [ "2026-11-02-211352-hand.json", "2026-11-04-100406-hand.json" ], "skipped": [] }
    got = hist.read_lines( tmp_path )
    assert [ ( l[ "started_at" ][ :10 ], l[ "backfilled" ] ) for l in got ] == [ ( "keep-me"[ :10 ], True ), ( "2026-11-04", True ) ]
    assert hist.backfill( tmp_path ) == { "added": [], "skipped": [ "2026-11-02-211352-hand.json", "2026-11-04-100406-hand.json" ] }
    assert len( hist.read_lines( tmp_path ) ) == 2


def test_a_backlog_that_rose_on_each_of_the_last_runs_is_reported_with_its_series():
    lines = [ line( 5 ), line( 4 ), line( 6 ), line( 8 ), line( 9 ) ]
    assert hist.rising_run( lines, 3 ) == { "runs": 3, "series": [ 4, 6, 8, 9 ] }


def test_a_flat_or_falling_step_a_short_history_and_an_empty_one_report_nothing():
    assert hist.rising_run( [ line( 4 ), line( 6 ), line( 6 ) ], 2 ) is None
    assert hist.rising_run( [ line( 9 ), line( 4 ), line( 6 ) ], 2 ) is None
    assert hist.rising_run( [ line( 1 ), line( 2 ) ], 2 ) is None
    assert hist.rising_run( [], 1 ) is None


def test_failed_and_baseline_runs_are_skipped_not_counted_as_a_fall():
    lines = [ line( 4 ), line( None, status="failed" ), line( 1, mode="baseline" ), line( 6 ), line( None ), line( 9 ) ]
    assert hist.rising_run( lines, 2 ) == { "runs": 2, "series": [ 4, 6, 9 ] }


def test_the_table_has_a_header_one_row_per_run_a_dash_for_what_was_not_measured_and_pads_to_the_widest_cell():
    rows = hist.table( [ hist.line_of( ok_doc(), "a.json" ), hist.line_of( { "status": "failed", "trigger": "hand", "started_at": "2026-11-07T01:02:03-05:00" }, "b.json" ) ] ).splitlines()
    assert len( rows ) == 3 and rows[ 0 ].split() == [ "started", "mode", "trigger", "status", "calls", "judged", "carried", "findings", "groups", "filed", "secs" ]
    assert rows[ 1 ].split()[ :2 ] == [ "2026-11-06", "19:06" ] and rows[ 1 ].split()[ -1 ] == "1041"
    assert rows[ 2 ].split()[ -5: ] == [ "-", "-", "-", "-", "-" ]
    assert len( { len( r ) for r in rows } ) == 1


def test_an_empty_history_prints_a_plain_sentence():
    assert hist.table( [] ) == "no runs recorded"


def test_main_prints_the_table_by_default_and_backfills_on_request( tmp_path ):
    ( tmp_path / "2026-11-04-100406-hand.json" ).write_text( json.dumps( { "status": "ok", "trigger": "hand" } ) )
    said = []
    assert hist.main( [ "--folder", str( tmp_path ), "--backfill" ], said.append ) == 0
    assert said == [ "added 1, skipped 0", "  2026-11-04-100406-hand.json" ]
    said.clear()
    assert hist.main( [ "--folder", str( tmp_path ) ], said.append ) == 0 and "2026-11-04" in said[ 0 ]


def test_main_defaults_to_the_projects_duplicate_check_folder( tmp_path, monkeypatch ):
    monkeypatch.setattr( hist.cu, "get_project_root", lambda: str( tmp_path ) )
    said = []
    assert hist.main( [], said.append ) == 0 and said == [ "no runs recorded" ]
