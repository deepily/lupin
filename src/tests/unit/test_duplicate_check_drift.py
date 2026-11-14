#!/usr/bin/env python3
"""
duplicate_check_drift: the weekly drift report of the interim judge, and pair counts.

Venue: :7999-eligible / local, pure; every file is built under tmp_path and nothing is read from the live data folder.
"""
import io
import json
import os
import sys
import time

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import pytest

from cosa.repo import code_health_settings as chs
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_drift as dd
from lupin_mcp import duplicate_check_status as dcs

OPUS, FABLE = "model-a", "model-b"        # stand-ins; the module reads ids from its arguments and the INI, never a literal


def write_run( folder, name, started, pairs=None, findings=None ):
    doc = { "started_at": started, "pairs": pairs, "findings": findings }
    ( folder / name ).write_text( json.dumps( doc ), encoding="utf-8" )


def write_ledger( path, lines ):
    path.write_text( "\n".join( json.dumps( l ) for l in lines ) + "\n", encoding="utf-8" )


def ruled( model, *verdicts ):
    return { "key": f"semdup|old|new|v1|{model}|0", "value": { "rulings": [ { "candidate": f"d-{i}", "verdict": v, "reason": "r" } for i, v in enumerate( verdicts ) ] } }


def age( path, day ):
    stamp = time.mktime( time.strptime( day, "%Y-%m-%d" ) ) + 3600
    os.utime( path, ( stamp, stamp ) )


def test_week_of_text_names_the_monday_from_the_date_as_written():
    assert dd.week_of_text( "2026-11-14T23:59:59-05:00" ) == "2026-11-09"
    assert dd.week_of_text( "2026-11-09T00:00:00+14:00" ) == "2026-11-09"
    assert dd.week_of_text( "2026-11-15T01:00:00Z" ) == "2026-11-09"
    assert dd.week_of_text( "2026-11-16T01:00:00Z" ) == "2026-11-16"
    with pytest.raises( ValueError ): dd.week_of_text( "not a date" )


def test_run_documents_skip_other_files_and_name_the_unreadable_ones(tmp_path):
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00" )
    ( tmp_path / "2026-11-14-110000-cron.json" ).write_text( "{broken", encoding="utf-8" )
    ( tmp_path / "2026-11-14-120000-cron.json" ).write_text( "[1, 2]", encoding="utf-8" )
    ( tmp_path / "last-success.json" ).write_text( "{}", encoding="utf-8" )
    bad  = []
    docs = dd.run_documents( tmp_path, bad )
    assert [ name for name, _ in docs ] == [ "2026-11-14-100000-cron.json" ]
    assert bad == [ "2026-11-14-110000-cron.json", "2026-11-14-120000-cron.json" ]


def test_weekly_flags_sum_the_models_own_pairs_by_week(tmp_path):
    write_run( tmp_path, "2026-11-09-100000-cron.json", "2026-11-09T10:00:00-05:00", { OPUS: { "rows": 10, "flagged": 2 }, FABLE: { "rows": 99, "flagged": 99 } } )
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00", { OPUS: { "rows": 30, "flagged": 3 } } )
    write_run( tmp_path, "2026-11-16-100000-cron.json", "2026-11-16T10:00:00-05:00", { OPUS: { "rows": 5, "flagged": 1 } } )
    write_run( tmp_path, "2026-11-17-100000-cron.json", "2026-11-17T10:00:00-05:00", None )
    write_run( tmp_path, "2026-11-18-100000-cron.json", "2026-11-18T10:00:00-05:00", { FABLE: { "rows": 1, "flagged": 1 } } )
    got = dd.weekly_flags( tmp_path, OPUS, [] )
    assert got == { "2026-11-09": ( 40, 5 ), "2026-11-16": ( 5, 1 ) }
    assert list( got ) == [ "2026-11-09", "2026-11-16" ]
    assert dd.weekly_flags( tmp_path, "model-c", [] ) == {}


def test_ledger_counts_take_only_lines_whose_key_names_the_model(tmp_path):
    path = tmp_path / "ledger.jsonl"
    write_ledger( path, [ { "binding": "x" }, ruled( FABLE, "duplicate", "distinct", "related", "near_duplicate" ), ruled( OPUS, "duplicate", "duplicate" ),
                          { "key": f"semdup|a|b|v1|{FABLE}|0", "value": { "unreadable": { "code": "X" } } } ] )
    assert dd.ledger_counts( path, FABLE ) == ( 4, 2 )
    assert dd.ledger_counts( path, OPUS ) == ( 2, 2 )
    assert dd.ledger_counts( path, "model-c" ) == ( 0, 0 )


def test_backlog_ledgers_are_the_version_files_closed_before_the_day(tmp_path):
    old, new, merged = tmp_path / "judge-ledger.claude-1.jsonl", tmp_path / "judge-ledger.claude-2.jsonl", tmp_path / "judge-ledger.jsonl"
    for p in ( old, new, merged ): write_ledger( p, [ ruled( FABLE, "duplicate", "distinct" ) ] )
    age( old, "2026-11-09" )
    age( new, "2026-11-11" )
    age( merged, "2026-11-01" )
    assert [ p.name for p in dd.backlog_ledgers( tmp_path, "2026-11-11" ) ] == [ "judge-ledger.claude-1.jsonl" ]
    assert dd.backlog_rate( tmp_path, FABLE, "2026-11-11" ) == ( 2, 1, [ "judge-ledger.claude-1.jsonl" ] )
    assert dd.backlog_rate( tmp_path, FABLE, "2026-11-01" ) == ( 0, 0, [] )


@pytest.mark.parametrize( "reference, flagged, judged, expected", [
    ( None, 5, 10, "n/a" ), ( 0.15, 0, 0, "n/a" ), ( 0.15, 15, 100, "within" ), ( 0.15, 90, 100, "above reference" ), ( 0.9, 1, 100, "below reference" ) ] )
def test_against_places_a_reference_rate_beside_the_weeks_interval( reference, flagged, judged, expected ):
    assert dd.against( reference, flagged, judged ) == expected


def test_shift_table_has_a_row_for_each_week_and_survives_a_missing_backlog(tmp_path):
    write_run( tmp_path, "2026-11-09-100000-cron.json", "2026-11-09T10:00:00-05:00", { OPUS: { "rows": 100, "flagged": 15 } } )
    text, backlog = dd.shift_table( tmp_path, OPUS, FABLE, "2026-11-11", [] )
    assert backlog == ( 0, 0, [] )
    lines = text.splitlines()
    assert len( lines ) == 3 and lines[ 2 ].startswith( "| 2026-11-09 | 100 | 15 | 15/100 (15.0%," )
    assert lines[ 2 ].endswith( "| within | n/a |" )
    empty, _ = dd.shift_table( tmp_path, "model-c", FABLE, "2026-11-11", [] )
    assert len( empty.splitlines() ) == 2


def test_finding_judges_read_each_finding_and_tolerate_runs_with_none(tmp_path):
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00", findings=[ { "id": "d-1", "judge_model": OPUS }, { "id": "d-2", "judge_model": f"{OPUS}+{FABLE}", "reused_from_model": FABLE }, { "id": "d-3" } ] )
    write_run( tmp_path, "2026-11-14-110000-cron.json", "2026-11-14T11:00:00-05:00", findings=None )
    bad = []
    assert dd.finding_judges( tmp_path, bad ) == { ( "2026-11-14-100000-cron", "d-1" ): ( OPUS, False ), ( "2026-11-14-100000-cron", "d-2" ): ( f"{OPUS}+{FABLE}", True ), ( "2026-11-14-100000-cron", "d-3" ): ( dd.NO_MODEL, False ) }
    assert bad == []


def test_triage_table_counts_each_finding_once_under_its_judge(tmp_path):
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00", findings=[
        { "id": "d-1", "judge_model": OPUS }, { "id": "d-2", "judge_model": OPUS }, { "id": "d-3", "judge_model": OPUS }, { "id": "d-4", "judge_model": FABLE, "reused_from_model": FABLE }, { "id": "d-5", "judge_model": FABLE }, { "id": "d-6" }, { "id": "d-7" } ] )
    verdicts = [ ( "d-1", "DUPLICATE" ), ( "d-2", "DISTINCT" ), ( "d-4", "EXTEND" ), ( "d-4", "DISTINCT" ), ( "d-6", "EXTEND" ), ( "d-9", "DUPLICATE" ) ]
    ( tmp_path / "verdicts.jsonl" ).write_text( "\n".join( json.dumps( { "run": "2026-11-14-100000-cron", "finding": f, "verdict": v } ) for f, v in verdicts ) + "\n", encoding="utf-8" )
    rows = dd.triage_table( tmp_path, [] ).splitlines()[ 2: ]
    assert rows[ 0 ].startswith( f"| {OPUS} | 3 | 1 | 0 | 1 | 1 | 1/2 (50.0%," ) and rows[ 0 ].endswith( "| 0 |" )
    assert rows[ 1 ].startswith( f"| {FABLE} | 2 | 0 | 0 | 1 | 1 | 0/1 (0.0%," ) and rows[ 1 ].endswith( "| 1 |" )
    assert rows[ 2 ].startswith( f"| {dd.NO_MODEL} | 2 | 0 | 1 | 0 | 1 | 1/1 (100.0%," )
    assert len( rows ) == 3


def test_triage_table_refuses_a_damaged_verdicts_file(tmp_path):
    ( tmp_path / "verdicts.jsonl" ).write_text( "{not a verdict\n", encoding="utf-8" )
    with pytest.raises( ValueError ): dd.triage_table( tmp_path, [] )


def test_report_holds_both_tables_the_references_and_the_unreadable_files(tmp_path):
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00", { OPUS: { "rows": 20, "flagged": 3 } } )
    ( tmp_path / "2026-11-14-110000-cron.json" ).write_text( "{broken", encoding="utf-8" )
    ledger = tmp_path / "judge-ledger.claude-1.jsonl"
    write_ledger( ledger, [ ruled( FABLE, *( [ "duplicate" ] * 10 + [ "distinct" ] * 90 ) ) ] )
    age( ledger, "2026-11-01" )
    text = dd.report( tmp_path, OPUS, FABLE, "2026-11-11" )
    assert f"# Interim judge drift report: {OPUS}" in text
    assert "| 2026-11-09 | 20 | 3 | 3/20 (15.0%," in text
    assert f"Fable's rate on the proof: 15/100 (15.0%" in text
    assert f"{FABLE} before 2026-11-11, from 1 version ledger(s) (judge-ledger.claude-1.jsonl): 10/100 (10.0%," in text
    assert "## Triage outcomes by judge model" in text
    assert f"{dd.NO_RUN_FILE}: 2026-11-14-110000-cron.json" in text
    assert text.count( "2026-11-14-110000-cron.json" ) == 1
    assert dd.NO_MODEL not in text
    with pytest.raises( ValueError ): dd.report( tmp_path, OPUS, FABLE, "11 Nov" )


def test_report_names_no_version_ledger_when_none_closed_before_the_day(tmp_path):
    assert "from 0 version ledger(s) (none): 0/0 (n/a)" in dd.report( tmp_path, OPUS, FABLE, "2026-11-11" )


def test_main_prints_the_report_for_a_given_folder_and_model(tmp_path):
    out = io.StringIO()
    code = dd.main( [ "--baseline-model", FABLE, "--model", OPUS, "--check-dir", str( tmp_path ) ], out=out )
    assert code == 0 and "# Interim judge drift report: model-a" in out.getvalue()


def test_main_reads_the_judge_model_and_folder_from_the_ini_and_the_project_root(tmp_path, monkeypatch):
    class Config:
        def get_required( self, key, silent=False ):
            assert key == chs.JUDGE_MODEL_KEY
            return OPUS
    monkeypatch.setattr( dcs, "folder_of", lambda root: tmp_path )
    out = io.StringIO()
    assert dd.main( [ "--baseline-model", FABLE ], out=out, config=Config() ) == 0
    assert f"report: {OPUS}" in out.getvalue()


def test_main_refuses_with_exit_3_and_writes_nothing(tmp_path, capsys):
    out  = io.StringIO()
    assert dd.main( [ "--baseline-model", FABLE, "--model", OPUS, "--check-dir", str( tmp_path / "missing" ) ], out=out ) == dd.EXIT_NOT_MADE
    assert "REFUSING: FileNotFoundError" in out.getvalue()
    out  = io.StringIO()
    assert dd.main( [ "--baseline-model", FABLE, "--model", OPUS, "--check-dir", str( tmp_path ), "--before", "soon" ], out=out ) == dd.EXIT_NOT_MADE
    assert "REFUSING: ValueError" in out.getvalue()
    class NoKey:
        def get_required( self, key, silent=False ):
            from cosa.config.configuration_manager import MissingConfigKeyError
            raise MissingConfigKeyError( key, "block", "path" )
    out  = io.StringIO()
    assert dd.main( [ "--baseline-model", FABLE, "--check-dir", str( tmp_path ) ], out=out, config=NoKey() ) == dd.EXIT_NOT_MADE
    assert "REFUSING: CodeHealthSettingError" in out.getvalue()
    assert list( tmp_path.iterdir() ) == []


def test_main_prints_to_stdout_by_default(tmp_path, capsys):
    assert dd.main( [ "--baseline-model", FABLE, "--model", OPUS, "--check-dir", str( tmp_path ) ] ) == 0
    assert "Interim judge drift report" in capsys.readouterr().out


def test_pair_counts_count_a_models_own_rows_and_leave_reused_ones_out():
    rows = [ { "model": OPUS, "verdict": "duplicate" }, { "model": OPUS, "verdict": "distinct" }, { "model": OPUS, "verdict": "near_duplicate" }, { "model": OPUS, "verdict": "related" },
             { "model": FABLE, "verdict": "duplicate", "reused_from_model": FABLE }, { "model": FABLE, "verdict": "distinct" } ]
    assert daily.pair_counts( rows ) == { OPUS: { "rows": 4, "flagged": 2 }, FABLE: { "rows": 1, "flagged": 0 } }
    assert daily.pair_counts( [ rows[ 4 ] ] ) == {}
    assert daily.pair_counts( [] ) == {}
    assert "pairs" in daily.UNREACHED


def test_report_says_so_when_findings_name_no_model(tmp_path):
    write_run( tmp_path, "2026-11-14-100000-cron.json", "2026-11-14T10:00:00-05:00", findings=[ { "id": "d-1" } ] )
    text = dd.report( tmp_path, OPUS, FABLE, "2026-11-11" )
    assert f"| {dd.NO_MODEL} | 1 |" in text and f"The row '{dd.NO_MODEL}' holds the findings written before result files named their judge" in text
