"""
The daily duplicate check's writer and both readers name one folder.

The writer is the live run's data root joined with the check's folder name; the readers are the verdicts command and the weekly page.
Each test runs a reader with no --data-dir, in a temporary project root.
LUPIN_REUSE_DATA_DIR points somewhere else, as it did when the readers looked under the fleet data tree and found nothing.
"""
import io
import json
import pathlib

import pytest

from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp import duplicate_check_verdicts as dv
from lupin_mcp import reuse_behaviour as rb


@pytest.fixture
def root( tmp_path, monkeypatch ):
    """A project root with a data-tree decoy that holds no duplicate-check folder."""
    monkeypatch.setenv( "LUPIN_ROOT", str( tmp_path ) )
    monkeypatch.setenv( "LUPIN_REUSE_DATA_DIR", str( tmp_path / "decoy-data" ) )
    ( tmp_path / "decoy-data" ).mkdir()
    return tmp_path


def test_the_writer_and_the_resolver_name_the_same_folder( root ):
    writer = pathlib.Path( daily.live_parts()[ "data_dir" ] ).joinpath( *daily.FOLDER )
    assert writer == dcs.folder_of( pathlib.Path( daily.live_parts()[ "data_dir" ] ).parent )
    assert dcs.folder_of( root ) == root / "io" / "duplicate-check-daily"


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
