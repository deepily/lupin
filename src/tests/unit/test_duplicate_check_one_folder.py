"""
The daily duplicate check's writer and both readers name one folder.

The writer is the live run's data root joined with the check's folder name; the readers are the verdicts command and the weekly page.
Each test runs a reader with no --data-dir, in a temporary project root.
LUPIN_REUSE_DATA_DIR points somewhere else, as it did when the readers looked under the fleet data tree and found nothing.
"""
import datetime
import io
import json
import pathlib
import shutil

import pytest

from cosa.rest import job_registry as jr
from cosa.rest.routers import duplicate_check_status as router
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_history as hist
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp import duplicate_check_verdicts as dv
from lupin_mcp import reuse_behaviour as rb


REAL_ROOT = pathlib.Path( __file__ ).resolve().parents[ 3 ]


@pytest.fixture
def root( tmp_path, monkeypatch ):
    """A project root with a data-tree decoy that holds no duplicate-check folder."""
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path / "decoy-data" ) )
    ( tmp_path / "decoy-data" ).mkdir()
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    for name in ( "lupin-app.ini", "lupin-app-splainer.ini" ): shutil.copy( f"{REAL_ROOT}/src/conf/{name}", tmp_path / "src" / "conf" / name )
    return tmp_path


def test_the_writer_and_the_resolver_name_the_same_folder( root ):
    writer = pathlib.Path( daily.live_parts()[ "data_dir" ] ).joinpath( *daily.FOLDER )
    assert writer == dcs.folder_of( root )
    assert dcs.folder_of( root ) == root / "fleet-data" / root.name / "code-health" / "duplicate-check-daily"


def test_the_verdicts_command_writes_where_the_run_writes_with_no_data_dir( root ):
    out = io.StringIO()
    folder = dcs.folder_of( root )
    folder.mkdir( parents=True )
    ( folder / "2026-11-10-100000-cron.json" ).write_text( json.dumps( { "date": "2026-11-10", "trigger": "cron", "status": "carried", "judged": 1, "judge_calls": 1, "elapsed_seconds": 1.0, "findings": [ { "id": "d-1", "correlation_key": "epic:dupcheck-d-1" } ] } ), encoding="utf-8" )
    line = "DUPCHECK-VERDICT run=2026-11-10-100000-cron finding=d-1 verdict=EXTEND class=same-job by=cheech ts=2026-11-11T12:00:00Z"
    dv.main( [ line, "--file-only" ], out=out )
    assert ( dcs.folder_of( root ) / "verdicts.jsonl" ).is_file(), out.getvalue()
    assert not ( root / "decoy-data" / "duplicate-check-daily" ).exists()


def test_the_weekly_page_reads_the_folder_the_run_writes_with_no_data_dir( root, monkeypatch ):
    seen = []
    monkeypatch.setattr( rb, "read_check_runs", lambda folder, week: ( seen.append( pathlib.Path( folder ) ) or [], 0 ) )
    rb.main( [ "--end", "2026-11-08" ], out=io.StringIO(), store=object() )
    assert seen == [ dcs.folder_of( root ) ]


def test_the_history_command_status_page_and_jobs_page_agree_on_the_moved_records( root ):
    """The count and newest stamp are literals written beside the seeding."""
    folder = dcs.folder_of( root )
    for day in ( "04", "05", "06" ):
        hist.append_line( folder, hist.line_of( { "status": "carried", "trigger": "cron", "mode": "daily", "started_at": f"2026-11-{day}T19:06:59-05:00", "carried": [ 1 ], "owed": 1, "judged": 1, "judge_calls": 1, "elapsed_seconds": 5.0 }, f"2026-11-{day}-190659-cron.json" ) )
    said = []
    assert hist.main( [], said.append ) == 0
    rows = said[ 0 ].splitlines()
    assert len( rows ) == 1 + 3 and "2026-11-06 19:06" in rows[ -1 ], "a header and three runs, the newest last"
    page = dcs.snapshot( router.runs_folder(), datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=datetime.timezone( datetime.timedelta( hours=-5 ) ) ) )
    assert len( page[ "runs" ] ) == 3 and page[ "runs" ][ 0 ][ "started_at" ] == "2026-11-06T19:06:59-05:00"
    dcs.write_job_summary( folder, datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=datetime.timezone.utc ) )
    registry = json.load( open( f"{REAL_ROOT}/src/conf/job-registry.json", encoding="utf-8" ) )
    entry    = [ j for j in registry[ "jobs" ] if j[ "job" ] == "duplicate-check" ][ 0 ]
    summary  = json.loads( jr.resolve_path( entry[ "summary_path" ], str( root ), str( root / "decoy-data" ) ).read_text() )
    assert summary[ "last_attempt" ][ "started_at" ] == "2026-11-06T19:06:59-05:00" and len( summary[ "scan_debt" ][ "points" ] ) == 3
    assert summary[ "last_attempt" ][ "evidence" ] == "code-health/duplicate-check-daily/runs.jsonl:3"


def test_the_evidence_label_follows_the_folder_the_data_dir_gave_not_the_default_name( tmp_path ):
    folder = tmp_path / "elsewhere" / "duplicate-check-daily"
    hist.append_line( folder, hist.line_of( { "status": "carried", "trigger": "cron", "mode": "daily", "started_at": "2026-11-06T19:06:59-05:00", "carried": [ 1 ], "owed": 1, "judged": 1, "judge_calls": 1, "elapsed_seconds": 5.0 }, "r.json" ) )
    summary = dcs.job_summary( hist.read_lines( folder ), datetime.datetime( 2026, 11, 7, tzinfo=datetime.timezone.utc ), subdir=dcs.subdir_of( folder ) )
    assert summary[ "last_attempt" ][ "evidence" ] == "elsewhere/duplicate-check-daily/runs.jsonl:1"
    assert dcs.subdir_of( tmp_path / "other-name" ) == "code-health"


def elsewhere_folder( tmp_path ):
    """A runs folder whose parent is `elsewhere`, holding one run."""
    folder = tmp_path / "elsewhere" / "duplicate-check-daily"
    hist.append_line( folder, hist.line_of( { "status": "carried", "trigger": "cron", "mode": "daily", "started_at": "2026-11-06T19:06:59-05:00", "carried": [ 1 ], "owed": 1, "judged": 1, "judge_calls": 1, "elapsed_seconds": 5.0 }, "r.json" ) )
    return folder


NOW_UTC = datetime.datetime( 2026, 11, 7, 12, 0, tzinfo=datetime.timezone.utc )


def test_the_snapshot_cites_the_folder_it_was_given_in_its_evidence( tmp_path ):
    assert dcs.snapshot( elsewhere_folder( tmp_path ), NOW_UTC )[ "summary" ][ "last_attempt" ][ "evidence" ] == "elsewhere/duplicate-check-daily/runs.jsonl:1"


def test_the_written_summary_cites_the_folder_it_was_written_beside( tmp_path ):
    path = dcs.write_job_summary( elsewhere_folder( tmp_path ), NOW_UTC )
    assert json.loads( path.read_text() )[ "last_attempt" ][ "evidence" ] == "elsewhere/duplicate-check-daily/runs.jsonl:1"


def test_the_job_summary_endpoint_cites_the_folder_the_router_reads( tmp_path, monkeypatch ):
    folder = elsewhere_folder( tmp_path )
    monkeypatch.setattr( router, "runs_folder", lambda: folder )
    assert router.get_job_summary()[ "last_attempt" ][ "evidence" ] == "elsewhere/duplicate-check-daily/runs.jsonl:1"
