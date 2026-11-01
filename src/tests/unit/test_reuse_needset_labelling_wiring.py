"""
Run-check rulings and call sites wired from the draw to the packets, with a fake judge.

No model is called: the drafter and the checker are scripted fakes, and the run-check runs real child processes on small made-up functions.
"""
import json

import pytest

from cosa.repo.doc_lint import harness_runner
from cosa.repo.labelling import packets as pk
from cosa.repo.labelling import run_check as rc
from lupin_mcp.reuse_needset import check, finalize, run
from lupin_mcp.reuse_needset import errors as er
from tests.unit.test_reuse_needset_run import SENTENCE, make_env, table
from tests.unit.test_reuse_needset_run import build_world

CHECKER = "claude-opus-5-5"
GOOD    = ( "def add( a: int, b: int ) -> int:\n    return a + b\n", "def total( a: int, b: int ) -> int:\n    return b + a\n" )
BAD     = ( "def add( a: int, b: int ) -> int:\n    return a + b\n", "def total( a: int, b: int ) -> int:\n    return a - b\n" )
UNKNOWN = ( "def add( self, a ):\n    return a\n", "def total( a ):\n    return a\n" )


class FakeJudge:
    """A scripted second model that agrees with every need."""

    def __init__( self ):
        """Start with no prompts seen."""
        self.prompts = []

    def __call__( self, prompt ):
        """Return an agree reply."""
        self.prompts.append( prompt )
        return json.dumps( { "result": "agree", "note": "the key does the job" } )


@pytest.fixture
def world( tmp_path ):
    """Return the checked needs of the made-up world, a source tree that calls them and helpers."""
    got        = run.run_needset( make_env( tmp_path ), table(), tmp_path )
    by_id      = build_world()[ 0 ]
    tree       = tmp_path / "tree"
    ( tree / "pkg" ).mkdir( parents=True )
    ( tree / "pkg" / "callers.py" ).write_text( "".join( f"x{n} = {name}( {n} )\n" for n, name in enumerate( sorted( r[ "name" ] for r in by_id.values() if r[ "lang" ] == "py" ) ) ) )
    judge      = FakeJudge()
    book       = harness_runner.Ledger( str( tmp_path / "check.jsonl" ), binding="test" )
    source_of  = lambda i: f"def body_of_{i.replace( '.', '_' )}(): pass"
    material   = lambda n: { "lines": [] } if n[ "kind" ] == "nothing" else { "key_texts": [ source_of( i ) for i in n[ "key" ][ "symbols" ] ] }
    checked    = [ check.second_check( n, judge, book, CHECKER, **material( n ) ) for n in got[ "needs" ] ]
    return { "needs": checked, "by_id": by_id, "tree": tree, "files": [ "pkg/callers.py" ], "source_of": source_of, "judge": judge, "out": tmp_path / "packets" }


def py_matched( needs, by_id ):
    """Return the checked matched needs whose first key symbol is Python, in id order."""
    return sorted( [ n for n in needs if n[ "kind" ] != "nothing" and by_id[ n[ "key" ][ "symbols" ][ 0 ] ][ "lang" ] == "py" ], key=lambda n: n[ "id" ] )


def rulings( w ):
    """Return three needs and their rulings: accepted, rejected and not runnable."""
    a, b, c = py_matched( w[ "needs" ], w[ "by_id" ] )[ :3 ]
    return a, b, c, finalize.run_check_needs( w[ "needs" ], { a[ "id" ]: GOOD, b[ "id" ]: BAD, c[ "id" ]: UNKNOWN }, 1 )


def test_the_fake_judge_end_to_end_a_rejected_key_never_reaches_a_packet_a_person_check_need_always_does_and_call_sites_show( world ):
    a, b, c, checks = rulings( world )
    assert [ checks[ x[ "id" ] ][ "route" ] for x in ( a, b, c ) ] == [ "accept", "reject", "person_check" ]
    kept, rejected, person = finalize.screen_needs( world[ "needs" ], checks )
    assert [ r[ "id" ] for r in rejected ] == [ b[ "id" ] ] and "returned differs" in rejected[ 0 ][ "reason" ] and person == { c[ "id" ] }
    assert b[ "id" ] not in { n[ "id" ] for n in kept } and len( kept ) == len( world[ "needs" ] ) - 1
    picked = finalize.select_for_labelling( kept, 7, run_checks=checks )
    assert { "id": c[ "id" ], "reason": "run_check" } in picked and picked == finalize.select_for_labelling( kept, 7, person_check_ids=person )
    by_id  = world[ "by_id" ]
    items  = finalize.labelling_items( kept, picked, world[ "source_of" ], lambda n: [ "pkg.a.f() — Adds." ], lambda n: finalize.key_call_sites( n, by_id, world[ "tree" ], world[ "files" ] ), checks )
    assert [ i[ "item_id" ] for i in items ] == [ p[ "id" ] for p in picked ] and b[ "id" ] not in { i[ "item_id" ] for i in items }
    pk.export_packets( items, [ "r1", "r2" ], 7, world[ "out" ] )
    shown  = { r[ "item_id" ]: r for r in ( json.loads( l ) for l in pk.packet_path( world[ "out" ], "r1" ).read_text().splitlines() ) }
    assert c[ "id" ] in shown and "run_check" not in json.dumps( shown[ c[ "id" ] ] ), "a reviewer never sees the run-check ruling"
    py_item = shown[ c[ "id" ] ][ "payload" ]
    assert py_item[ "call_sites" ] and all( "pkg/callers.py:" in s for s in py_item[ "call_sites" ] ) and len( py_item[ "call_sites" ] ) <= 5
    ts = [ r for r in shown.values() if "key_sources" in r[ "payload" ] and by_id[ next( n for n in kept if n[ "id" ] == r[ "item_id" ] )[ "key" ][ "symbols" ][ 0 ] ][ "lang" ] == "ts" ]
    assert ts and all( "call_sites" not in r[ "payload" ] for r in ts ), "a TypeScript key shows no call-site claim"
    assert world[ "judge" ].prompts, "the fake judge was the only judge asked"


def test_without_a_ruling_nothing_changes_for_a_need( world ):
    kept, rejected, person = finalize.screen_needs( world[ "needs" ], {} )
    assert kept == world[ "needs" ] and rejected == [] and person == set()


def test_labelling_items_refuses_a_need_whose_key_was_rejected_if_the_caller_skipped_the_screen( world ):
    a, b, c, checks = rulings( world )
    with pytest.raises( er.NeedsetError ) as e: finalize.labelling_items( world[ "needs" ], [ { "id": b[ "id" ], "reason": "sample" } ], world[ "source_of" ], lambda n: [], lambda n: None, checks )
    assert e.value.code == er.KEY_REJECTED


def test_a_duplicate_pair_in_the_selection_is_skipped_and_a_nothing_need_gets_its_hits( world ):
    nothing_need = next( n for n in world[ "needs" ] if n[ "kind" ] == "nothing" )
    picked       = [ { "id": "pair-x", "reason": "semdup_pair" }, { "id": nothing_need[ "id" ], "reason": "nothing" } ]
    items        = finalize.labelling_items( world[ "needs" ], picked, world[ "source_of" ], lambda n: [ "pkg.a.f() — Adds." ], lambda n: None, {} )
    assert len( items ) == 1 and items[ 0 ][ "payload" ][ "hits" ] == [ "pkg.a.f() — Adds." ] and items[ 0 ][ "payload" ][ "nothing_exists" ] is True


def test_key_call_sites_spans_key_symbols_stops_at_five_and_skips_typescript_keys( world ):
    by_id, tree, files = world[ "by_id" ], world[ "tree" ], world[ "files" ]
    py_ids = sorted( i for i, r in by_id.items() if r[ "lang" ] == "py" )
    two    = { "key": { "symbols": py_ids[ :2 ] } }
    got    = finalize.key_call_sites( two, by_id, tree, files )
    assert len( got ) == 2 and got[ 0 ].startswith( "pkg/callers.py:" ) and got[ 0 ] != got[ 1 ]
    ( tree / "pkg" / "more.py" ).write_text( "".join( f"{by_id[ py_ids[ 0 ] ][ 'name' ]}( {n} )\n" for n in range( 8 ) ) )
    many   = finalize.key_call_sites( { "key": { "symbols": py_ids[ :3 ] } }, by_id, tree, files + [ "pkg/more.py" ] )
    assert len( many ) == 5, "the limit holds across all key symbols"
    ts_id  = next( i for i, r in by_id.items() if r[ "lang" ] == "ts" )
    assert finalize.key_call_sites( { "key": { "symbols": [ ts_id ] } }, by_id, tree, files ) is None
    mixed  = finalize.key_call_sites( { "key": { "symbols": [ ts_id, py_ids[ 0 ] ] } }, by_id, tree, files )
    assert mixed and len( mixed ) == 1


def test_run_check_needs_checks_each_pair_handed_in_and_refuses_a_stray_need_id( world ):
    a, b, c, checks = rulings( world )
    assert list( checks ) == [ a[ "id" ], b[ "id" ], c[ "id" ] ]
    seen = []
    finalize.run_check_needs( world[ "needs" ], { a[ "id" ]: GOOD }, 9, checker=lambda o, r, seed: seen.append( ( o, r, seed ) ) or {} )
    assert seen == [ ( GOOD[ 0 ], GOOD[ 1 ], 9 ) ]
    with pytest.raises( er.NeedsetError ) as e: finalize.run_check_needs( world[ "needs" ], { "n-0000000000": GOOD }, 1 )
    assert e.value.code == er.BAD_NEED
    assert finalize.run_check_needs( world[ "needs" ], {}, 1 ) == {}


def test_a_person_check_route_alone_selects_the_need_and_a_record_without_that_route_does_not( world ):
    a, b, c, checks = rulings( world )
    kept, _, _ = finalize.screen_needs( world[ "needs" ], checks )
    with_route = finalize.select_for_labelling( kept, 7, run_checks=checks )
    without    = finalize.select_for_labelling( kept, 7, run_checks={ a[ "id" ]: checks[ a[ "id" ] ] } )
    assert [ p[ "id" ] for p in with_route if p[ "reason" ] == "run_check" ] == [ c[ "id" ] ]
    assert "run_check" not in { p[ "reason" ] for p in without }
