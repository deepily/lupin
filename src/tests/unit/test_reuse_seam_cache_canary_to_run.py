"""
Seam: the answer cache a canary writes and the run (and every later step) reads.

Two checks. The first drives the real canary and the real run on the stand-in with the driver's own asks.
It shows that a search the canary answered is answered again from its cache entries, with nothing sent.
The second reads two entries the live runs wrote, byte for byte, through the cache's own reader and the pack parsers.
A full run asks other members than the canary did, and the cache key holds the need.
So the two share no entry in a full run, and the first check reruns the canary's own members.
Nothing here sends a request.
"""
import hashlib
import json
import pathlib

import pytest

from lupin_mcp import reuse_e2e_run as run
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt

FIXTURE = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "jev-cache-entries-2-live-20261009.json"
WIDE    = 120
IDS     = [ f"cosa.wide.f{i:03d}" for i in range( WIDE ) ]


def make_repo( base ):
    """Ensures: writes a lupin-shaped tree of public functions and returns its root."""
    root = base / "lupin"
    ( root / "src" / "cosa" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" ).mkdir( parents=True )
    ( root / "src" / "lupin_mcp" / "tool.py" ).write_text( 'def serve( x ):\n    """Serve a thing."""\n    return x\n', encoding="utf-8" )
    body = "\n\n".join( f'def f{i:03d}( x ):\n    """Does the distinct job number {i} for a caller."""\n    return x + {i}' for i in range( WIDE ) )
    ( root / "src" / "cosa" / "wide.py" ).write_text( body + "\n", encoding="utf-8" )
    return root


class Scratch:
    """A scratch repo, data folder and ledger with a counting stand-in transport."""

    def __init__( self, tmp_path ):
        self.root, self.data, self.ledger_path, self.posts = make_repo( tmp_path ), tmp_path / "data", tmp_path / "ledger.jsonl", []
        rl.AccountLedger.create( self.ledger_path, 10 ** 9, "test", "scratch" )

    def env( self ):
        inner, posts = None, self.posts
        def factory( budget ):
            nonlocal inner
            inner = rr.StandIn( budget )
            class Counting:
                def post_with_meta( self, body ):
                    posts.append( len( body[ "questions" ] ) )
                    return inner.post_with_meta( body )
            return Counting()
        return run.E2EEnv( self.root, self.data, rl.AccountLedger( self.ledger_path ), { "old": run.ask_old, "new": run.ask_new }, transport_factory=factory, pack_size=50 )


def items_of( n ): return [ { "member": IDS[ i ], "need": f"A function number {i} that does a distinct job." } for i in range( n ) ]


def twins_of( n ): return { IDS[ i ]: { IDS[ ( i + 1 ) % WIDE ] } for i in range( n ) }


def test_a_canary_run_again_under_a_new_run_name_is_answered_from_its_own_cache_entries( tmp_path ):
    scratch = Scratch( tmp_path )
    canary  = run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 8 )
    first   = json.loads( ( scratch.data / "e2e-results" / "e2e-canary.json" ).read_text( encoding="utf-8" ) )[ "searches" ]
    sent    = len( scratch.posts )
    assert canary[ "requests" ] > 0 and sent == canary[ "requests" ] and ( scratch.data / "jev-cache" ).is_dir()
    again   = run.run_searches( scratch.env(), "e2e-canary-again", items_of( 5 ), twins_of( 5 ), 10 ** 8 )
    assert len( scratch.posts ) == sent                                                       # nothing more was sent
    assert [ s[ "tokens" ] for s in again[ "searches" ] ] == [ 0 ] * 10 and again[ "totals" ][ "spent_tokens" ] == 0
    assert [ ( s[ "member" ], s[ "question" ], s[ "receipt_id" ], s[ "read" ] ) for s in again[ "searches" ] ] == \
           [ ( s[ "member" ], s[ "question" ], s[ "receipt_id" ], s[ "read" ] ) for s in first ]
    assert sum( 1 for _ in ( scratch.data / "receipts" ).glob( "*.json" ) ) == 10                # the stored receipts are the canary's, not new ones


def test_the_full_run_after_an_approved_canary_does_not_rewrite_an_entry_the_canary_wrote( tmp_path ):
    scratch = Scratch( tmp_path )
    run.run_canary( scratch.env(), items_of( 100 ), twins_of( 100 ), 10 ** 8 )
    before  = { p: p.read_bytes() for p in ( scratch.data / "jev-cache" ).rglob( "*.json" ) }
    run.approve_canary( scratch.env(), "cheech", "tokens read" )
    rec     = run.run_full( scratch.env(), items_of( 100 ), twins_of( 100 ), 5 * 10 ** 8 )
    assert rec[ "totals" ][ "complete" ] == 190 and before
    assert all( p.read_bytes() == b for p, b in before.items() )                              # write-once: the run read or left them, never rewrote one


def load_entries():
    return json.loads( FIXTURE.read_text( encoding="utf-8" ) )[ "entries" ]


def put_entry( tmp_path, entry ):
    """Ensures: writes the live entry at the path the cache reads; returns ( cache, key )."""
    key  = json.loads( entry[ "text" ] )[ "request_hash" ]
    path = tmp_path / "jev-cache" / key[ :2 ] / f"{key}.json"
    path.parent.mkdir( parents=True )
    path.write_text( entry[ "text" ], encoding="utf-8" )
    return rt.JevCache( tmp_path ), key


def test_the_fixture_holds_the_live_files_byte_for_byte():
    for entry in load_entries().values(): assert hashlib.sha256( entry[ "text" ].encode( "utf-8" ) ).hexdigest() == entry[ "sha256" ]


def test_a_three_way_entry_the_live_run_wrote_reads_through_the_cache_and_the_answer_parser( tmp_path ):
    cache, key = put_entry( tmp_path, load_entries()[ "three_way" ] )
    probs = rt.parse_answer( cache.get( key ) )
    assert probs == { "extend": 0.29, "reuse": 0.71, "unrelated": 0.0 }


def test_a_pair_entry_the_live_run_wrote_reads_through_the_cache_and_the_pair_parser( tmp_path ):
    cache, key = put_entry( tmp_path, load_entries()[ "pair" ] )
    fit = rp._pair_hit( key, cache.get( key ) )
    assert set( fit ) == rp.PAIR_FIELDS and fit[ "provides" ] == 0.73 and fit[ "coverage" ] == 1.0 and fit[ "score" ] == 2.61


def test_a_three_way_entry_is_refused_by_the_pair_parser( tmp_path ):
    cache, key = put_entry( tmp_path, load_entries()[ "three_way" ] )
    with pytest.raises( rt.ReuseError, match="CACHE_CORRUPT" ): rp._pair_hit( key, cache.get( key ) )
