"""
Tests for src/scripts/filter_stop_hook_cards.py.

The database is a double. The committed files are checked against literals from the live read of
24 Nov 2026. A changed file or a changed filter fails a named test.
"""

import contextlib
import hashlib
import json
import sys

import pytest

import cosa.utils.util as cu
from cosa.research.phi4_flash_lite_study import freeze_corpus as fc

sys.path.insert( 0, cu.get_project_root() + "/src/scripts" )
import filter_stop_hook_cards as fsh   # noqa: E402

ROOT = cu.get_project_root()


class Session:
    """A session double that records its statements and returns the given Stop-hook ids."""

    def __init__( self, ids, fail=False ):
        self.ids, self.fail, self.statements, self.params, self.rolled_back = ids, fail, [], [], 0

    def execute( self, statement, params=None ):
        self.statements.append( str( statement ) )
        self.params.append( params )
        if self.fail and params is not None: raise RuntimeError( "the read failed" )
        return [ ( one, ) for one in self.ids ] if params is not None else None

    def rollback( self ):
        self.rolled_back += 1


def write_cohort( path, ids ):
    path.write_text( "".join( json.dumps( { "id": one } ) + "\n" for one in ids ) )


def test_the_query_runs_read_only_for_the_exact_title_and_lowers_the_ids_and_rolls_back():
    session = Session( [ "AAAA-1", "bbbb-2" ] )
    assert fsh.stop_hook_ids( session ) == { "aaaa-1", "bbbb-2" }
    assert session.statements[ 0 ] == "SET TRANSACTION READ ONLY"
    assert session.params[ 1 ] == { "title": "Stop hook: Anything else?" } and "title = :title" in session.statements[ 1 ]
    assert session.rolled_back == 1


def test_a_failed_read_still_rolls_the_transaction_back():
    session = Session( [], fail=True )
    with pytest.raises( RuntimeError ): fsh.stop_hook_ids( session )
    assert session.rolled_back == 1


def test_split_cohort_keeps_the_order_of_both_halves_and_loses_nothing():
    kept, dropped = fsh.split_cohort( [ "c", "a", "d", "b", "e" ], { "a", "b", "z" } )
    assert kept == [ "c", "d", "e" ] and dropped == [ "a", "b" ]


def test_build_writes_the_filtered_cohort_its_manifest_and_the_dropped_ids_and_leaves_the_source_alone( tmp_path ):
    cohort = tmp_path / "cohort.jsonl"
    write_cohort( cohort, [ "id-3", "id-1", "id-2", "id-4" ] )
    before  = cohort.read_bytes()
    receipt = fsh.build( str( cohort ), str( tmp_path / "f.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "d.txt" ), { "id-1", "id-4", "outside" } )
    assert cohort.read_bytes() == before
    assert [ json.loads( line )[ "id" ] for line in ( tmp_path / "f.jsonl" ).read_text().splitlines() ] == [ "id-3", "id-2" ]
    assert ( tmp_path / "d.txt" ).read_text() == "id-1\nid-4\n"
    manifest = json.loads( ( tmp_path / "m.json" ).read_text() )
    assert set( manifest ) == { "minimum_rows", "snapshot_row_count", "snapshot_sha256" } and manifest[ "snapshot_row_count" ] == 2
    assert fc.verify_snapshot( str( tmp_path / "f.jsonl" ), str( tmp_path / "m.json" ) )[ 0 ]
    assert manifest[ "snapshot_sha256" ] == hashlib.sha256( ( tmp_path / "f.jsonl" ).read_bytes() ).hexdigest()
    assert receipt == { "source_rows": 4, "kept": 2, "dropped": 2, "stop_hook_cards_not_in_cohort": 1, "filtered_sha256": manifest[ "snapshot_sha256" ],
                        "source_sha256": hashlib.sha256( cohort.read_bytes() ).hexdigest() }


def test_build_refuses_a_filter_that_would_change_nothing( tmp_path ):
    write_cohort( tmp_path / "cohort.jsonl", [ "a", "b" ] )
    with pytest.raises( RuntimeError, match="would change nothing" ):
        fsh.build( str( tmp_path / "cohort.jsonl" ), str( tmp_path / "f.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "d.txt" ), { "x" } )
    assert not ( tmp_path / "f.jsonl" ).exists()


def test_build_refuses_when_the_new_manifest_does_not_verify( tmp_path, monkeypatch ):
    write_cohort( tmp_path / "cohort.jsonl", [ "a", "b" ] )
    monkeypatch.setattr( fc, "verify_snapshot", lambda snapshot, manifest: ( False, "sha differs" ) )
    with pytest.raises( RuntimeError, match="sha differs" ):
        fsh.build( str( tmp_path / "cohort.jsonl" ), str( tmp_path / "f.jsonl" ), str( tmp_path / "m.json" ), str( tmp_path / "d.txt" ), { "a" } )


def test_main_reads_the_ids_from_the_database_writes_the_files_and_prints_the_receipt( tmp_path, monkeypatch, capsys ):
    write_cohort( tmp_path / "cohort.jsonl", [ "a", "b", "c" ] )
    session = Session( [ "B" ] )
    import cosa.rest.db.database as database
    monkeypatch.setattr( database, "get_db", lambda: contextlib.nullcontext( session ) )
    code = fsh.main( [ "--cohort", str( tmp_path / "cohort.jsonl" ), "--out", str( tmp_path / "f.jsonl" ), "--manifest", str( tmp_path / "m.json" ), "--dropped", str( tmp_path / "d.txt" ) ] )
    printed = json.loads( capsys.readouterr().out )
    assert code == 0 and printed[ "kept" ] == 2 and printed[ "dropped" ] == 1 and ( tmp_path / "d.txt" ).read_text() == "b\n"


# ---------------------------------------------------------------- the committed files

def _ids( path ):
    with open( path, encoding="utf-8" ) as handle: return [ json.loads( line )[ "id" ] for line in handle if line.strip() ]


def _sha( path ):
    with open( path, "rb" ) as handle: return hashlib.sha256( handle.read() ).hexdigest()


def test_the_current_cohort_file_is_unchanged_and_the_filtered_one_is_its_order_without_the_89_dropped_ids():
    cohort, filtered = ROOT + fsh.COHORT, ROOT + fsh.FILTERED
    assert _sha( cohort ) == "5faab7b3dc7f343cfc228a6424ef7206cba7d794a8c1f84e096b915122e5fd06"
    with open( ROOT + fsh.DROPPED, encoding="utf-8" ) as handle: dropped = handle.read().split()
    assert len( dropped ) == 89 == len( set( dropped ) ) and set( dropped ) <= set( _ids( cohort ) )
    assert _ids( filtered ) == [ one for one in _ids( cohort ) if one not in set( dropped ) ] and len( _ids( filtered ) ) == 3519
    assert _sha( filtered ) == "c185d796b7f2ff892def72d580e97741d14219d139f83efc40e4c9251142199d"
    assert _sha( ROOT + fsh.DROPPED ) == "c61dc874ab19708ff8103bcf3c5956b146cf61baeaaf2f83ee04682bf72759e5"


def test_the_filtered_cohort_verifies_against_its_own_manifest():
    ok, detail = fc.verify_snapshot( ROOT + fsh.FILTERED, ROOT + fsh.MANIFEST )
    assert ok, detail
