"""The duplicate check run history: line writer, backfill, rising-backlog test, table."""
import json
import pathlib

import pytest

from lupin_mcp import duplicate_check_history as hist

KEYS = set( hist.line_of( { "status": "failed", "trigger": "hand", "started_at": "2026-11-06T19:06:59-05:00" }, "x.json" ) )


def ok_doc( **over ):
    """Ensures: returns a successful result document."""
    base = { "status": "carried", "trigger": "cron", "started_at": "2026-11-06T19:06:59-05:00", "elapsed_seconds": 1040.589, "cap": 300, "judge_calls": 300, "judged": 304,
             "window": { "start": "aaa", "end": "bbb", "commits": 65 }, "left_to_judge": [ "a", "b" ], "unreadable": [ { "id": "u" } ],
             "clusters": [ [ "x", "y" ], [ "p", "q", "r" ] ], "findings": [ { "commit": "c1" }, { "commit": "c1" }, { "commit": None } ],
             "filing": { "filed": [ 1, 2 ], "already_filed": [], "queued_for_retry": [ 1 ], "refused": [] } }
    return { **base, **over }


def line( left, mode="daily", status="carried" ):
    """Ensures: returns a minimal history line."""
    return { "mode": mode, "status": status, "left_to_judge": left }


def test_a_successful_run_flattens_to_one_line_with_counts_group_sizes_and_findings_by_commit():
    got = hist.line_of( ok_doc(), "2026-11-06-190659-cron.json" )
    assert got == { "schema_version": 3, "run_file": "2026-11-06-190659-cron.json", "started_at": "2026-11-06T19:06:59-05:00", "elapsed_seconds": 1040.589, "trigger": "cron",
                    "mode": "daily", "status": "carried", "failure": None, "window_start": "aaa", "window_end": "bbb", "commits": 65, "left_to_judge": 2, "judged": 304, "cap": 300,
                    "ceiling": None, "judge_calls": 300, "findings": 3, "groups": 2, "group_sizes": [ 2, 3 ], "findings_by_commit": { "c1": 2, "unknown": 1 },
                    "filed": 2, "already_filed": 0, "queued_for_retry": 1, "refused": 0, "unreadable": 1, "backfilled": False,
                    "branch": None, "judge_model": None, "backlog_total": None, "rate_limited": None, "backoff_until": None, "input_tokens": None, "output_tokens": None, "cache_creation_tokens": None,
                    "cache_read_tokens": None, "cost_usd": None, "usage_calls": None, "calls_per_hour": 1038 }


def test_a_run_that_recorded_usage_carries_the_branch_the_tokens_and_the_calls_an_hour():
    doc = { **ok_doc(), "branch": "wip-x", "backlog_total": 310, "rate_limited": 1, "backoff_until": "2026-11-07T21:00:00-05:00",
            "usage": { "calls": 300, "input_tokens": 600, "output_tokens": 1200, "cache_creation_input_tokens": 65460, "cache_read_input_tokens": 11382, "cost_usd": 3.9 } }
    got = hist.line_of( doc, "f.json" )
    assert ( got[ "branch" ], got[ "backlog_total" ], got[ "rate_limited" ], got[ "backoff_until" ] ) == ( "wip-x", 310, 1, "2026-11-07T21:00:00-05:00" )
    assert ( got[ "input_tokens" ], got[ "output_tokens" ], got[ "cache_creation_tokens" ], got[ "cache_read_tokens" ], got[ "cost_usd" ], got[ "usage_calls" ] ) == ( 600, 1200, 65460, 11382, 3.9, 300 )


def test_a_run_with_no_calls_or_no_time_has_no_calls_an_hour():
    assert hist.line_of( { **ok_doc(), "judge_calls": 0 }, "f.json" )[ "calls_per_hour" ] is None
    assert hist.line_of( { **ok_doc(), "elapsed_seconds": None }, "f.json" )[ "calls_per_hour" ] is None


def test_a_failed_run_has_the_same_keys_and_none_for_what_it_never_measured():
    got = hist.line_of( { "status": "failed", "trigger": "hand", "started_at": "t", "stage": "judging", "error": "boom", "cap": 100, "judge_calls": 7 }, "f.json" )
    assert set( got ) == KEYS
    assert ( got[ "failure" ], got[ "left_to_judge" ], got[ "findings" ], got[ "group_sizes" ], got[ "window_start" ], got[ "filed" ], got[ "judge_calls" ] ) == ( "judging: boom", None, None, None, None, None, 7 )


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
    hist.append_line( tmp_path / "f", { "n": 1, "started_at": "2026-11-01T10:00:00+00:00" } )
    path = hist.append_line( tmp_path / "f", { "n": 2, "started_at": "2026-11-02T10:00:00+00:00" } )
    assert path.name == "runs.jsonl" and [ l[ "n" ] for l in hist.read_lines( tmp_path / "f" ) ] == [ 1, 2 ]


def test_the_backfill_adds_each_result_file_once_oldest_first_marks_it_and_skips_files_that_are_not_runs( tmp_path ):
    ( tmp_path / "2026-11-04-100406-hand.json" ).write_text( json.dumps( { "status": "failed", "trigger": "hand", "stage": "judging", "error": "E" } ) )
    ( tmp_path / "2026-11-02-211352-hand.json" ).write_text( json.dumps( { "status": "ok", "trigger": "hand", "started_at": "2026-11-02T21:13:52-05:00" } ) )
    ( tmp_path / "last-success.json" ).write_text( "{}" )
    first = hist.backfill( tmp_path )
    assert first == { "added": [ "2026-11-02-211352-hand.json", "2026-11-04-100406-hand.json" ], "skipped": [] }
    got = hist.read_lines( tmp_path )
    assert [ ( l[ "started_at" ][ :10 ], l[ "backfilled" ] ) for l in got ] == [ ( "2026-11-02", True ), ( "2026-11-04", True ) ]
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
    assert len( rows ) == 3 and rows[ 0 ].split() == [ "started", "mode", "trigger", "status", "calls", "left", "to", "judge", "judged", "findings", "groups", "filed", "secs" ]
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


def test_main_defaults_to_the_code_health_folder_and_reads_the_moved_records( tmp_path ):
    said = []
    assert hist.main( [], said.append ) == 0 and said == [ "no runs recorded" ]
    moved = tmp_path / "fleet-data" / "lupin" / "code-health" / "duplicate-check-daily"
    hist.append_line( moved, hist.line_of( ok_doc(), "2026-11-06-190659-cron.json" ) )
    said.clear()
    assert hist.main( [], said.append ) == 0 and "2026-11-06" in said[ 0 ]


def test_a_backfill_after_newer_runs_reads_back_in_time_order_so_the_rising_test_sees_the_real_series( tmp_path ):
    hist.append_line( tmp_path, { **line( 7 ), "run_file": "new.json", "started_at": "2026-11-09T10:00:00+00:00" } )
    for day, carried in ( ( "05", 3 ), ( "06", 5 ) ): ( tmp_path / f"2026-11-{day}-100000-hand.json" ).write_text( json.dumps( { "status": "carried", "trigger": "hand", "carried": [ 0 ] * carried } ) )
    hist.backfill( tmp_path )
    assert [ l[ "run_file" ] for l in hist.read_lines( tmp_path ) ] == [ "2026-11-05-100000-hand.json", "2026-11-06-100000-hand.json", "new.json" ], "the file has the new run first"
    assert hist.rising_run( hist.read_lines( tmp_path ), 2 ) == { "runs": 2, "series": [ 3, 5, 7 ] }


def test_a_line_that_is_not_json_an_object_or_dated_is_skipped_and_counted_not_fatal( tmp_path ):
    good = json.dumps( { **line( 1 ), "started_at": "2026-11-01T10:00:00+00:00" } )
    ( tmp_path / hist.RUNS_FILE ).write_text( "\n".join( [ good, "{broken", "", "[1, 2]", "\"text\"", json.dumps( { "mode": "daily" } ), json.dumps( { "started_at": "yesterday" } ), json.dumps( { "started_at": 5 } ), good ] ) + "\n" )
    got = hist.read_history( tmp_path )
    assert len( got[ "lines" ] ) == 2 and got[ "bad" ] == [ 2, 4, 5, 6, 7, 8 ], "line 3 is blank, which is not a fault"
    assert len( hist.read_lines( tmp_path ) ) == 2 and hist.rising_run( hist.read_lines( tmp_path ), 1 ) is None


def test_the_table_reader_prints_the_series_and_then_the_numbers_of_the_lines_it_skipped( tmp_path ):
    ( tmp_path / hist.RUNS_FILE ).write_text( json.dumps( hist.line_of( ok_doc(), "a.json" ) ) + "\nnot json\n" )
    said = []
    assert hist.main( [ "--folder", str( tmp_path ) ], said.append ) == 0
    assert said[ 0 ].count( "\n" ) == 1 and said[ 1 ] == "skipped 1 unreadable line(s) of runs.jsonl: 2"


def test_append_line_writes_to_the_named_file_when_given_one(tmp_path):
    assert hist.append_line( tmp_path, { "a": 1 }, "own.jsonl" ) == tmp_path / "own.jsonl" and not ( tmp_path / hist.RUNS_FILE ).exists()
    assert ( tmp_path / "own.jsonl" ).read_text() == '{"a": 1}\n'


def stamped( day, calls, model ): return hist.line_of( { "status": "ok", "trigger": "cron", "started_at": f"{day}T08:00:00-05:00", "judge_calls": calls, "judge_model": model }, "x.json" )


def test_a_line_copies_the_model_its_calls_went_to_and_none_when_the_run_never_named_one():
    assert hist.line_of( { **ok_doc(), "judge_model": "claude-opus-5-5" }, "f.json" )[ "judge_model" ] == "claude-opus-5-5"
    assert hist.line_of( ok_doc(), "f.json" )[ "judge_model" ] is None


def test_calls_on_sums_one_days_calls_for_one_model_and_charges_unnamed_lines_to_every_model():
    lines = [ stamped( "2026-11-13", 100, "opus" ), stamped( "2026-11-13", 30, "opus" ), stamped( "2026-11-13", 7, "sonnet" ), stamped( "2026-11-12", 900, "opus" ),
              stamped( "2026-11-13", 5, None ), stamped( "2026-11-13", None, "opus" ) ]
    assert hist.calls_on( lines, "2026-11-13", "opus" ) == 135, "100 + 30 + the 5 of the unnamed line; None calls add 0; yesterday and sonnet do not count"
    assert hist.calls_on( lines, "2026-11-13", "sonnet" ) == 12
    assert hist.calls_on( lines, "2026-11-14", "opus" ) == 0 and hist.calls_on( [], "2026-11-13", "opus" ) == 0


REAL_SCHEMA_2 = pathlib.Path( __file__ ).parent.parent / "fixtures" / "duplicate-check" / "runs-schema-2.jsonl"       # three lines copied byte for byte from the live runs.jsonl: the 9 Nov daily, the 14 Nov 14:50 baseline, the 14 Nov 20:00 daily


def test_real_schema_2_lines_read_under_the_new_names_with_the_arithmetic_intact( tmp_path ):
    lines_in = [ json.loads( t ) for t in REAL_SCHEMA_2.read_text( encoding="utf-8" ).splitlines() ]
    assert len( lines_in ) == 3 and all( l[ "schema_version" ] == 2 and "owed" in l and "carried" in l for l in lines_in ), "the fixture is real schema 2 lines, not rewritten ones"
    ( tmp_path / hist.RUNS_FILE ).write_text( REAL_SCHEMA_2.read_text( encoding="utf-8" ), encoding="utf-8" )
    got = hist.read_history( tmp_path )
    assert got[ "bad" ] == [] and len( got[ "lines" ] ) == 3
    assert [ ( l[ "mode" ], l[ "backlog_total" ], l[ "judged" ], l[ "left_to_judge" ] ) for l in got[ "lines" ] ] == [ ( "daily", 487, 485, 2 ), ( "baseline", 12347, 5412, 6935 ), ( "daily", 283, 283, 0 ) ]
    assert all( "owed" not in l and "carried" not in l for l in got[ "lines" ] )
    assert all( l[ "backlog_total" ] - l[ "judged" ] == l[ "left_to_judge" ] for l in got[ "lines" ] ), "the 14 Nov measurement: 12,347 - 5,412 = 6,935"


def test_either_reads_the_new_name_first_then_the_old_one_then_none():
    assert hist.either( { "left_to_judge": 4, "carried": 9 }, "left_to_judge" ) == 4
    assert hist.either( { "carried": 9 }, "left_to_judge" ) == 9
    assert hist.either( { "owed": 7 }, "backlog_total" ) == 7
    assert hist.either( { }, "backlog_total" ) is None


def test_upgraded_renames_the_old_names_adds_none_that_are_absent_and_leaves_a_new_line_alone():
    old = { "owed": 5, "carried": 2, "status": "ok" }
    assert hist.upgraded( old ) == { "backlog_total": 5, "left_to_judge": 2, "status": "ok" } and old == { "owed": 5, "carried": 2, "status": "ok" }, "a copy, never the caller's line"
    assert hist.upgraded( { "carried": 2 } ) == { "left_to_judge": 2 }, "a line from before owed existed gets no backlog_total"
    new = { "backlog_total": 5, "left_to_judge": 2 }
    assert hist.upgraded( new ) == new


def test_a_pre_schema_3_result_file_is_flattened_to_the_new_names():
    got = hist.line_of( { **{ k: v for k, v in ok_doc().items() if k != "left_to_judge" }, "carried": [ "a", "b", "c" ], "owed": 310 }, "old.json" )
    assert got[ "left_to_judge" ] == 3 and got[ "backlog_total" ] == 310 and "owed" not in got and "carried" not in got
