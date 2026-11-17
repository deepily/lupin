"""Known-miss audits queued for the daily check's duplicates, with fakes only."""
import json

import pytest

from cosa.repo.symindex.candidates import shadow_audit as sa
from lupin_mcp import duplicate_check_audit as da
from lupin_mcp import reuse_tools as rt

DAY = "2026-11-03"


def receipt( tool="check_exists", **over ):
    """Ensures: returns a stored lookup receipt of a shortlist answer, changed by over."""
    base = { "tool": tool, "query": "find a thing", "language": "py", "index_sha": "idx1", "verdict": "NEW",
             "candidate_stage": { "ids": [ "a", "b" ], "manifest_hash": "gen1" } }
    return { **base, **over }


def tie_of( table ):
    """Ensures: returns a tie finder answering from the table by finding id."""
    def find( finding ):
        got = table[ finding[ "id" ] ]
        if isinstance( got, Exception ): raise got
        return got
    return find


def receipts_of( table ):
    """Ensures: returns a receipt reader over the table; a missing id raises ReuseError."""
    def read( rid ):
        if rid not in table: raise rt.ReuseError( "RECEIPT_MISSING", rid )
        return table[ rid ]
    return read


def queued( data_dir ):
    """Ensures: returns the queue files' items by queue id."""
    return { p.stem: json.loads( p.read_text() ) for p in ( data_dir / "shadow-pending" ).glob( "*.json" ) }


def ruling( rid, tool="check_exists" ): return { "tie": "ruling", "receipt_id": rid, "session": "s", "tool": tool }
def heuristic( rid ): return { "tie": "heuristic", "receipt_id": rid, "session": "s", "tool": "check_exists", "persona": "pocholo" }


def indexed( finding ):
    """Ensures: names a finding "idx." plus its own id, so an exclude_id shows which id was used."""
    return f"idx.{finding[ 'id' ]}"


def test_a_ruling_tie_to_a_check_exists_receipt_queues_one_known_miss_item_that_excludes_the_duplicate( tmp_path ):
    out = da.queue_audits( [ { "id": "pkg.new_fn" } ], tie_of( { "pkg.new_fn": ruling( "r1" ) } ), receipts_of( { "r1": receipt() } ), tmp_path, DAY, indexed )
    items = list( queued( tmp_path ).values() )
    assert len( items ) == 1 and out[ "counters" ][ da.QUEUED ] == 1 and out[ "counters" ][ da.HEURISTIC_QUEUED ] == 0 and out[ "reasons" ] == {}
    assert ( items[ 0 ][ "known_miss" ], items[ 0 ][ "exclude_id" ], items[ 0 ][ "tie" ], items[ 0 ][ "attempts" ] ) == ( True, "idx.pkg.new_fn", "ruling", 0 )
    assert ( items[ 0 ][ "need" ], items[ 0 ][ "generation" ], items[ 0 ][ "index_sha" ], items[ 0 ][ "queued_on" ] ) == ( "find a thing", "gen1", "idx1", DAY )
    assert items[ 0 ][ "live" ] == { "verdict": "NEW", "candidate_ids": [ "a", "b" ] }
    assert not ( tmp_path / "receipts" ).exists(), "no lookup count was added"


def test_a_heuristic_tie_is_marked_in_the_item_and_counted_separately( tmp_path ):
    out = da.queue_audits( [ { "id": "d1" } ], tie_of( { "d1": heuristic( "r1" ) } ), receipts_of( { "r1": receipt() } ), tmp_path, DAY, indexed )
    assert list( queued( tmp_path ).values() )[ 0 ][ "tie" ] == "heuristic"
    assert ( out[ "counters" ][ da.QUEUED ], out[ "counters" ][ da.HEURISTIC_QUEUED ] ) == ( 1, 1 )


def test_a_fetch_similar_tie_is_counted_as_no_need_text_without_reading_the_receipt( tmp_path ):
    def read( rid ): pytest.fail( "the receipt must not be read" )
    out = da.queue_audits( [ { "id": "d1" } ], tie_of( { "d1": ruling( "r1", tool="fetch_similar" ) } ), read, tmp_path, DAY, indexed )
    assert out[ "counters" ][ da.NO_NEED_TEXT ] == 1 and "fetch_similar" in out[ "reasons" ][ "d1" ] and queued( tmp_path ) == {}


def test_a_ruling_whose_receipt_is_not_in_the_call_log_is_read_and_a_fetch_similar_one_is_no_need_text( tmp_path ):
    out = da.queue_audits( [ { "id": "d1" }, { "id": "d2" } ], tie_of( { "d1": ruling( "r1", tool=None ), "d2": ruling( "r2", tool=None ) } ),
                           receipts_of( { "r1": receipt(), "r2": receipt( tool="fetch_similar" ) } ), tmp_path, DAY, indexed )
    assert ( out[ "counters" ][ da.QUEUED ], out[ "counters" ][ da.NO_NEED_TEXT ] ) == ( 1, 1 ) and list( out[ "reasons" ] ) == [ "d2" ]


def test_no_tie_a_tie_error_an_unreadable_receipt_and_a_measurement_receipt_are_counted_with_their_reasons( tmp_path ):
    table = { "d1": { "tie": "none", "reason": "no persona" }, "d2": ValueError( "abc is not a commit" ), "d3": ruling( "missing" ),
              "d4": ruling( "r4" ), "d5": ruling( "r5" ) }
    reads = { "r4": receipt( sweep_only=True ), "r5": receipt( candidate_stage={ "error": "x", "ids": [], "manifest_hash": "g" } ) }
    out   = da.queue_audits( [ { "id": f"d{n}" } for n in range( 1, 6 ) ], tie_of( table ), receipts_of( reads ), tmp_path, DAY, indexed )
    assert out[ "counters" ] == { da.QUEUED: 0, da.HEURISTIC_QUEUED: 0, da.NOT_IN_INDEX: 0, da.NO_TIE: 1, da.NO_NEED_TEXT: 0, da.NO_SHORTLIST: 2, da.UNREADABLE: 1, da.TIE_ERROR: 1 }
    assert out[ "reasons" ][ "d1" ] == "no persona" and "not a commit" in out[ "reasons" ][ "d2" ] and "RECEIPT_MISSING" in out[ "reasons" ][ "d3" ]
    assert queued( tmp_path ) == {}


def test_two_duplicates_behind_one_lookup_queue_two_items_and_the_same_duplicate_twice_queues_once( tmp_path ):
    find, read = tie_of( { "d1": ruling( "r1" ), "d2": ruling( "r1" ) } ), receipts_of( { "r1": receipt() } )
    da.queue_audits( [ { "id": "d1" }, { "id": "d2" } ], find, read, tmp_path, DAY, indexed )
    da.queue_audits( [ { "id": "d1" } ], find, read, tmp_path, DAY, indexed )
    assert sorted( i[ "exclude_id" ] for i in queued( tmp_path ).values() ) == [ "idx.d1", "idx.d2" ]


def test_the_known_miss_item_keeps_its_own_queue_slot_beside_the_random_sample_of_the_same_lookup( tmp_path ):
    sa.enqueue_pending( tmp_path, "find a thing", "py", "gen1", "idx1", { "verdict": "NEW", "candidate_ids": [] }, DAY )
    da.queue_audits( [ { "id": "d1" } ], tie_of( { "d1": ruling( "r1" ) } ), receipts_of( { "r1": receipt() } ), tmp_path, DAY, indexed )
    assert sorted( i[ "known_miss" ] for i in queued( tmp_path ).values() ) == [ False, True ]


def test_the_drain_sweeps_the_known_miss_item_without_the_duplicate_and_stores_a_receipt_with_the_tie( tmp_path ):
    da.queue_audits( [ { "id": "d1" } ], tie_of( { "d1": heuristic( "r1" ) } ), receipts_of( { "r1": receipt() } ), tmp_path, DAY, indexed )
    sa.enqueue_pending( tmp_path, "other", "py", "gen1", "idx1", { "verdict": "NEW", "candidate_ids": [] }, DAY )
    calls = []
    def sweep( need, language, **extra ):
        calls.append( ( need, extra ) )
        return { "verdict": "REUSE", "causal_ids": [ "z" ] }
    out = sa.run_pending( tmp_path, sweep, DAY, pass_language=True )
    assert calls == [ ( "find a thing", { "exclude_id": "idx.d1" } ), ( "other", {} ) ], "known-miss first, and only it excludes an id"
    known = [ r for r in out[ "receipts" ] if r[ "known_miss" ] ]
    assert len( known ) == 1 and known[ 0 ][ "exclude_id" ] == "idx.d1" and known[ 0 ][ "tie" ] == "heuristic" and known[ 0 ][ "outcome" ] == "miss"
    receipts = sa.load_receipts( tmp_path )
    assert sa.tally( receipts, "py", "gen1" )[ "audits" ] == 1, "the random-sample bound sees only its own audit"
    assert sa.tally( receipts, "py", "gen1", known_miss=True )[ "misses" ] == 1
    assert sa.tally( receipts, "py", "gen1", known_miss=True, tie="heuristic" )[ "audits" ] == 1
    assert sa.tally( receipts, "py", "gen1", known_miss=True, tie="ruling" )[ "audits" ] == 0


def entry( rid, file, name, line ): return { "id": rid, "file": file, "name": name, "line": line }
def finding( fid, file, name, line ): return { "id": fid, "file": file, "name": name, "line": line }


def test_the_index_finder_names_a_finding_by_its_file_and_name_and_never_by_the_daily_checks_own_id():
    find = da.index_id_finder( [ entry( "lupin_mcp.refile.regroup", "src/lupin_mcp/refile.py", "regroup", 69 ),
                                 entry( "lupin_mcp.other.regroup", "src/lupin_mcp/other.py", "regroup", 69 ) ] )
    assert find( finding( "d-269016efde", "src/lupin_mcp/refile.py", "regroup", 69 ) ) == "lupin_mcp.refile.regroup"
    assert find( finding( "d-269016efde", "src/lupin_mcp/refile.py", "regroup", 80 ) ) == "lupin_mcp.refile.regroup", "a moved line still finds the one entry of that name"
    assert find( finding( "lupin_mcp.refile.missing", "src/lupin_mcp/refile.py", "missing", 1 ) ) is None, "an id that looks like an index id is not trusted"
    assert find( finding( "d-1", "src/tests/unit/test_x.py", "regroup", 69 ) ) is None, "a test definition is not in the index"


def test_the_index_finder_takes_the_entry_at_the_findings_line_then_the_nearest_then_the_earlier():
    find = da.index_id_finder( [ entry( "m.f", "a.py", "f", 10 ), entry( "m.f#2", "a.py", "f", 50 ), entry( "m.f#3", "a.py", "f", 90 ) ] )
    assert [ find( finding( "d", "a.py", "f", n ) ) for n in ( 50, 85, 30 ) ] == [ "m.f#2", "m.f#3", "m.f" ]


def test_a_queued_item_excludes_the_index_id_and_not_the_daily_checks_id( tmp_path ):
    find = da.index_id_finder( [ entry( "lupin_mcp.refile.regroup", "src/lupin_mcp/refile.py", "regroup", 69 ) ] )
    da.queue_audits( [ finding( "d-269016efde", "src/lupin_mcp/refile.py", "regroup", 69 ) ], tie_of( { "d-269016efde": ruling( "r1" ) } ),
                     receipts_of( { "r1": receipt() } ), tmp_path, DAY, find )
    assert [ i[ "exclude_id" ] for i in queued( tmp_path ).values() ] == [ "lupin_mcp.refile.regroup" ]


def test_a_finding_the_index_does_not_hold_is_counted_not_in_index_and_is_neither_tied_nor_queued( tmp_path ):
    def tie( f ): pytest.fail( "a finding the sweep cannot exclude must not be tied" )
    out = da.queue_audits( [ finding( "d-2429627f02", "src/tests/unit/test_x.py", "_no_real_crash_alert", 129 ) ], tie,
                           receipts_of( {} ), tmp_path, DAY, da.index_id_finder( [] ) )
    assert out[ "counters" ][ da.NOT_IN_INDEX ] == 1 and out[ "counters" ][ da.QUEUED ] == 0 and queued( tmp_path ) == {}
    assert "src/tests/unit/test_x.py _no_real_crash_alert" in out[ "reasons" ][ "d-2429627f02" ]


def test_a_duplicate_queued_from_the_daily_check_is_audited_by_a_sweep_that_refuses_ids_it_does_not_know( tmp_path ):
    index = [ entry( "lupin_mcp.refile.regroup", "src/lupin_mcp/refile.py", "regroup", 69 ) ]
    known = { e[ "id" ] for e in index }
    def sweep( need, language, exclude_id=None ):
        if exclude_id is not None and exclude_id not in known: raise sa.CandidateError( "AUDIT_SWEEP_REFUSED", sa.UNKNOWN_ENTRY )
        return { "verdict": "REUSE", "causal_ids": [ "z" ] }
    da.queue_audits( [ finding( "d-269016efde", "src/lupin_mcp/refile.py", "regroup", 69 ) ], tie_of( { "d-269016efde": heuristic( "r1" ) } ),
                     receipts_of( { "r1": receipt() } ), tmp_path, DAY, da.index_id_finder( index ) )
    out = sa.run_pending( tmp_path, sweep, DAY, pass_language=True )
    assert ( out[ "audited" ], out[ "failed" ], out[ "dropped" ] ) == ( 1, 0, 0 )
