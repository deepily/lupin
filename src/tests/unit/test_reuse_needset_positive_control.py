"""
The positive control: plant 20 pairs in memory, find them, remove them.
"""
import hashlib
import json
import pathlib

import pytest

import cosa.utils.util as cu
from cosa.repo.symindex.candidates import candidate_stage as cs
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import positive_control as pc

REAL_PLANTED = pathlib.Path( cu.get_project_root() + "/io/semdup-labelling/2026.10.25-run5/key/planted.json" )
WORDS        = [ "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet" ]


def record( i, name=None ):
    """Return an index record whose words are its own."""
    return { "id": f"d-orig{i:02d}", "file": f"src/a{i}.py", "module": f"a{i}", "name": name or f"{WORDS[ i % 10 ]}Thing{i}", "sig": "()", "doc": f"{WORDS[ i % 10 ]} routine number {i}", "pin": f"pin{i:02d}" }


def pool():
    """
    Return a pool of 31 records.

    The last id sorts after every rewrite id, so a planted copy is in index order only if it was sorted.
    """
    return [ record( i ) for i in range( 30 ) ] + [ { **record( 30 ), "id": "d-zzlast" } ]


def pair( i ):
    """Return one synthetic pair: an original in the pool and a rewrite with words of its own."""
    return { "stratum": pc.STRATUM, "original": record( i ),
             "rewrite": { "id": f"d-rew{i:02d}", "file": f"src/new{i}.py", "name": f"zq{i}wrapper", "sig": "()", "text": "def x(): pass", "lang": "py", "calls": [ "x" ] } }


def pairs():
    """Return twenty pairs."""
    return [ pair( i ) for i in range( 20 ) ]


def need_of( p ):
    """Return the need text for a pair: the rewrite's own name."""
    return p[ "rewrite" ][ "name" ]


def finder():
    """Return the zero-call word-stage find function over the pool it is given."""
    return pc.lexical_find( need_of, 10, cs.build_stage, cs.shortlist )


def planted_file( tmp_path, extra=0, other=0 ):
    """Write a planted.json of control pairs and others; return ( path, sha256 )."""
    items = [ *pairs()[ :20 - extra ], *[ { **pair( 40 + i ), "stratum": "fable-planted" } for i in range( other ) ] ]
    path  = tmp_path / "planted.json"
    path.write_text( json.dumps( { "failed": [], "planted": items } ), encoding="utf-8" )
    return path, hashlib.sha256( path.read_bytes() ).hexdigest()


def test_the_checker_finds_every_planted_pair_and_the_pool_is_as_it_was():
    records = pool()
    rep     = pc.run_control( records, pairs(), finder(), cs.build_stage )
    assert rep[ "pairs" ] == 20 and rep[ "found" ] == 20 and rep[ "missed" ] == [] and rep[ "stage_ids_equal" ] is True
    assert rep[ "digest_before" ] == rep[ "digest_after" ] == pc.pool_digest( pool() ) and len( records ) == 31


def test_a_checker_that_cannot_see_the_planted_pool_misses_all_twenty():
    blind = lambda planted, p: cs.shortlist( need_of( p ), cs.build_stage( pool() ), 10 )[ "shortlist" ]
    rep   = pc.run_control( pool(), pairs(), blind, cs.build_stage )
    assert rep[ "found" ] == 0 and sorted( rep[ "missed" ] ) == sorted( p[ "rewrite" ][ "id" ] for p in pairs() ) and len( rep[ "missed" ] ) == 20


def test_the_planted_copy_holds_the_rewrites_and_leaves_the_pool_alone():
    records = pool()
    before  = pc.pool_digest( records )
    planted = pc.plant( records, pairs() )
    assert len( planted ) == 51 and {p[ "rewrite" ][ "id" ] for p in pairs()} <= {r[ "id" ] for r in planted} and pc.pool_digest( records ) == before
    assert all( set( r ) == set( pc.INDEX_FIELDS ) for r in planted if r[ "id" ].startswith( "d-rew" ) )
    planted[ 0 ][ "name" ] = "changed"
    assert pc.pool_digest( records ) == before and planted == sorted( planted, key=lambda r: r[ "id" ] )


def test_a_rewrite_whose_id_is_already_in_the_pool_is_refused():
    taken = pool() + [ { **record( 99 ), "id": "d-rew03" } ]
    with pytest.raises( er.NeedsetError ) as e: pc.plant( taken, pairs() )
    assert e.value.code == er.CONTROL_ID_COLLIDES
    with pytest.raises( er.NeedsetError ) as e: pc.plant( pool(), [ pair( 1 ), pair( 1 ) ] )
    assert e.value.code == er.CONTROL_ID_COLLIDES


def test_a_run_that_leaves_a_trace_in_the_pool_is_refused_by_name():
    records = pool()

    def dirty( planted, p ):
        records[ 0 ][ "doc" ] = "left behind"
        return []

    with pytest.raises( er.NeedsetError ) as e: pc.run_control( records, pairs(), dirty, cs.build_stage )
    assert e.value.code == er.CONTROL_NOT_RESTORED


def test_a_run_that_changes_only_the_stage_ids_is_refused_too():
    records = pool()
    same    = pc.pool_digest( records )
    calls   = []

    def build( recs ):
        calls.append( 1 )
        stage = cs.build_stage( recs )
        return type( "S", ( ), { "ids": stage.ids + ( ( "extra", ) if len( calls ) > 1 else ( ) ) } )

    with pytest.raises( er.NeedsetError ) as e: pc.run_control( records, pairs(), finder(), build )
    assert e.value.code == er.CONTROL_NOT_RESTORED and pc.pool_digest( records ) == same


def test_the_pairs_load_only_from_the_file_with_the_named_hash_and_count( tmp_path ):
    path, sha = planted_file( tmp_path, other=5 )
    got       = pc.load_pairs( path, sha )
    assert len( got ) == 20 and {p[ "stratum" ] for p in got} == { pc.STRATUM }
    with pytest.raises( er.NeedsetError ) as e: pc.load_pairs( path, "0" * 64 )
    assert e.value.code == er.CONTROL_INPUT_CHANGED
    path2 = tmp_path / "short.json"
    path2.write_text( json.dumps( { "failed": [], "planted": pairs()[ :19 ] } ), encoding="utf-8" )
    with pytest.raises( er.NeedsetError ) as e: pc.load_pairs( path2, hashlib.sha256( path2.read_bytes() ).hexdigest() )
    assert e.value.code == er.CONTROL_INPUT_CHANGED


@pytest.mark.skipif( not REAL_PLANTED.exists(), reason="io/ is not tracked, so a worktree has no copy of the proof's evidence" )
def test_the_real_planted_file_has_the_twenty_pairs_with_the_recorded_hash():
    got = pc.load_pairs( REAL_PLANTED )
    assert len( got ) == 20 and sorted( p[ "rewrite" ][ "lang" ] for p in got ).count( "ts" ) == 12


def test_a_snapshot_taken_before_earlier_work_catches_what_that_work_changed():
    records = pool()
    before  = pc.snapshot( records, cs.build_stage )
    records[ 3 ][ "name" ] = "changed"
    with pytest.raises( er.NeedsetError ) as e: pc.run_control( records, pairs(), finder(), cs.build_stage, before )
    assert e.value.code == er.CONTROL_NOT_RESTORED


def test_the_planted_copy_is_in_index_order_with_a_rewrite_before_a_pool_id():
    ids = [ r[ "id" ] for r in pc.plant( pool(), pairs() ) ]
    assert ids == sorted( ids ) and ids.index( "d-rew00" ) < ids.index( "d-zzlast" ) and ids[ -1 ] == "d-zzlast"


def test_the_copy_without_the_planted_ids_is_the_pool_and_a_run_writes_nothing( monkeypatch ):
    records = pool()
    planted = pc.plant( records, pairs() )
    gone    = { p[ "rewrite" ][ "id" ] for p in pairs() }
    assert pc.pool_digest( [ r for r in planted if r[ "id" ] not in gone ] ) == pc.pool_digest( sorted( records, key=lambda r: r[ "id" ] ) )
    real_open = open

    def read_only( file, mode="r", *a, **k ):
        if set( mode ) & set( "wax+" ): pytest.fail( f"a write was attempted: {file!r} mode {mode!r}" )
        return real_open( file, mode, *a, **k )

    for name in ( "write_text", "write_bytes" ): monkeypatch.setattr( pathlib.Path, name, lambda *a, **k: pytest.fail( "a Path write was attempted" ) )
    monkeypatch.setattr( "builtins.open", read_only )
    rep = pc.run_control( records, pairs(), finder(), cs.build_stage )
    assert rep[ "found" ] == 20
