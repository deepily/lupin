"""
The seed lists and the first two stage functions, run on fakes with no model call.

Fifty attribution seeds and a hundred yield seeds are drawn once, written before any call and read back by the stage functions.
"""
import asyncio
import json

import pytest

from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import hardness, loss_trace, stage_seeds, stages


# Measured once from the draw on the fixture below with seed 7. A change here means the seed recipe changed.
PIN_ATTRIBUTION_TS = [ "web.m111.fn", "web.m064.fn", "web.m126.fn" ]
PIN_YIELD_TS       = [ "web.m091.fn", "web.m047.fn", "web.m000.fn" ]


def records( n_ts=130, n_py=90 ):
    """Return eligible records sorted by id: n_ts script ones and n_py Python ones, all tracked."""
    out = [ { "id": f"web.m{n:03d}.fn", "file": f"src/web/m{n:03d}.js", "lang": "ts" } for n in range( n_ts ) ]
    out += [ { "id": f"cosa.m{n:03d}.fn", "file": f"src/cosa/m{n:03d}.py", "lang": "py" } for n in range( n_py ) ]
    return sorted( out, key=lambda r: r[ "id" ] )


def tracked_of( recs ): return { r[ "file" ] for r in recs }


def pairs_of( *ids ):
    """Return pairs whose originals carry a proof-space id, a file and a name."""
    return [ { "original": { "id": f"d-{i}", "file": f"src/web/{i}.js", "name": f"{i}.fn" }, "rewrite": { "id": f"d-{i}-rew" } } for i in ids ]


def draw( recs=None, seed=7, planted=frozenset(), tracked="all" ):
    recs = records() if recs is None else recs
    return stage_seeds.draw_lists( recs, seed, set( planted ), "abc123", tracked_of( recs ) if tracked == "all" else tracked )


def test_the_quotas_are_thirty_and_twenty_for_attribution_and_fifty_and_fifty_for_yield():
    assert stage_seeds.ATTRIBUTION_QUOTA == { "ts": 30, "py": 20 } and stage_seeds.YIELD_QUOTA == { "ts": 50, "py": 50 }
    r = draw()
    assert [ len( r[ "attribution" ][ k ] ) for k in ( "ts", "py", "order" ) ] == [ 30, 20, 50 ] and [ len( r[ "yield" ][ k ] ) for k in ( "ts", "py", "order" ) ] == [ 50, 50, 100 ]
    assert all( i.startswith( "web." ) for i in r[ "attribution" ][ "ts" ] ) and all( i.startswith( "cosa." ) for i in r[ "attribution" ][ "py" ] )


def test_the_two_lists_share_no_id_and_no_id_repeats_inside_a_list():
    r = draw()
    a, y = r[ "attribution" ][ "order" ], r[ "yield" ][ "order" ]
    assert len( set( a ) ) == 50 and len( set( y ) ) == 100 and not set( a ) & set( y )
    assert sorted( a ) == sorted( r[ "attribution" ][ "ts" ] + r[ "attribution" ][ "py" ] )


def test_a_planted_id_is_never_drawn_even_when_it_is_the_only_way_to_fill_a_list():
    recs    = records( n_ts=130, n_py=90 )
    planted = { r[ "id" ] for r in recs if r[ "lang" ] == "py" }
    with pytest.raises( er.NeedsetError ) as caught: draw( recs, planted=planted )
    assert caught.value.code == er.QUOTA_UNFILLABLE and "attribution/py" in caught.value.detail
    some = { r[ "id" ] for r in recs[ ::22 ] }
    assert not some & set( draw( recs, planted=some )[ "attribution" ][ "order" ] + draw( recs, planted=some )[ "yield" ][ "order" ] )


def test_planted_ids_cover_both_proof_ids_and_the_index_ids_found_by_file_and_name():
    recs = [ { "id": "src.web.m001.fn", "file": "src/web/m001.js", "name": "m001.fn" }, { "id": "src.web.m001.fn#2", "file": "src/web/m001.js", "name": "m001.fn" },
             { "id": "src.web.m002.fn", "file": "src/web/m002.js", "name": "m002.fn" } ]
    got = stage_seeds.planted_ids( pairs_of( "m001", "m009" ), recs )
    assert got == { "d-m001", "d-m001-rew", "d-m009", "d-m009-rew", "src.web.m001.fn", "src.web.m001.fn#2" }


def test_an_original_in_proof_space_is_excluded_from_the_draw_through_its_index_id():
    recs  = records()
    gone  = recs[ 5 ]
    pair  = { "original": { "id": "d-063e2b6b4c", "file": gone[ "file" ], "name": gone[ "id" ] + ".name" }, "rewrite": { "id": "d-rew" } }
    named = [ { **r, "name": r[ "id" ] + ".name" } for r in recs ]
    planted = stage_seeds.planted_ids( [ pair ], named )
    assert gone[ "id" ] in planted and "d-063e2b6b4c" in planted
    r = stage_seeds.draw_lists( [ x for x in recs ], 7, planted, "abc123", tracked_of( recs ) )
    assert gone[ "id" ] not in r[ "attribution" ][ "order" ] + r[ "yield" ][ "order" ]
    unmapped = stage_seeds.draw_lists( recs, 7, { "d-063e2b6b4c" }, "abc123", tracked_of( recs ) )
    assert unmapped[ "pool" ][ "excluded_planted" ] == 0


def test_only_tracked_files_are_used():
    recs = records()
    gone = { r[ "file" ] for r in recs if r[ "lang" ] == "ts" and r[ "file" ] < "src/web/m040.js" }
    r    = draw( recs, tracked=tracked_of( recs ) - gone )
    used = set( r[ "attribution" ][ "order" ] + r[ "yield" ][ "order" ] )
    assert not {x[ "id" ] for x in recs if x[ "file" ] in gone} & used and r[ "pool" ][ "tracked" ] == len( recs ) - len( gone )
    assert draw( recs, tracked=None )[ "pool" ][ "tracked" ] == len( recs )


def test_the_draw_is_the_same_for_the_same_seed_whatever_the_input_order_and_differs_for_another():
    recs = records()
    a, b = draw( recs ), draw( list( reversed( recs ) ) )
    assert a == b
    assert draw( recs, seed=8 )[ "attribution" ][ "order" ] != a[ "attribution" ][ "order" ]


def test_the_order_alternates_languages_so_a_stopped_run_holds_both():
    order = draw()[ "yield" ][ "order" ]
    assert [ i.split( "." )[ 0 ] for i in order[ :6 ] ] == [ "web", "cosa", "web", "cosa", "web", "cosa" ]
    mixed = stage_seeds.interleave( { "ts": [ "t1", "t2", "t3" ], "py": [ "p1" ] } )
    assert mixed == [ "t1", "p1", "t2", "t3" ]


def test_the_record_names_the_seed_commit_reader_and_pool_and_carries_a_matching_sha():
    recs = records()
    r    = draw( recs, planted={ recs[ 0 ][ "id" ] } )
    assert ( r[ "format" ], r[ "seed" ], r[ "source_commit" ], r[ "reader" ] ) == ( stage_seeds.FORMAT, 7, "abc123", "read_searchable" )
    assert r[ "pool" ] == { "kept": 220, "tracked": 220, "excluded_planted": 1, "ts_available": 130, "py_available": 89 }
    assert r[ "sha" ] == stage_seeds.lists_sha( r ) and stage_seeds.lists_sha( { **r, "seed": 8 } ) != r[ "sha" ]


def test_a_language_with_too_few_seeds_is_refused_by_name_before_anything_is_written():
    with pytest.raises( er.NeedsetError ) as caught: draw( records( n_ts=79, n_py=90 ) )
    assert caught.value.code == er.QUOTA_UNFILLABLE and "yield/ts" in caught.value.detail


def test_the_lists_are_written_once_and_a_different_list_is_refused( tmp_path ):
    r    = draw()
    path = stage_seeds.write_lists( tmp_path, r )
    assert path == tmp_path / stage_seeds.LISTS_FILE and json.loads( path.read_text( encoding="utf-8" ) ) == r
    assert stage_seeds.write_lists( tmp_path, r ) == path
    with pytest.raises( er.NeedsetError ) as caught: stage_seeds.write_lists( tmp_path, draw( seed=9 ) )
    assert caught.value.code == er.PLAN_ALREADY_WRITTEN


def test_a_missing_edited_or_foreign_file_is_refused_when_read_back( tmp_path ):
    path = stage_seeds.write_lists( tmp_path, draw() )
    assert stage_seeds.load_lists( path )[ "seed" ] == 7
    edited = json.loads( path.read_text( encoding="utf-8" ) )
    edited[ "yield" ][ "order" ][ 0 ] = "swapped"
    path.write_text( json.dumps( edited ), encoding="utf-8" )
    foreign = tmp_path / "other.json"
    foreign.write_text( json.dumps( { "format": "something-else" } ), encoding="utf-8" )
    for bad in ( path, foreign, tmp_path / "gone.json" ):
        with pytest.raises( er.NeedsetError ) as caught: stage_seeds.load_lists( bad )
        assert caught.value.code == er.MANIFEST_MISMATCH


def matched_need( seed_id ): return { "id": f"n-{seed_id}", "kind": "work_alike", "seed": seed_id }


def trace_records( needs ):
    """Return one record per need: the first lost at a named stage, the rest found."""
    return [ { "kind": "work_alike", "write_lang": "py", "members": { f"k{n}": loss_trace.NOT_READ if n == 0 else loss_trace.FOUND } } for n, _ in enumerate( needs ) ]


def test_the_attribution_stage_reads_the_written_file_makes_a_need_per_seed_in_order_and_reports( tmp_path ):
    path, asked, traced = stage_seeds.write_lists( tmp_path, draw() ), [], []
    async def make_need( seed_id ):
        asked.append( seed_id )
        return None if len( asked ) == 3 else matched_need( seed_id )
    async def trace_fn( needs ):
        traced.append( needs )
        return trace_records( needs )
    out = asyncio.run( stage_seeds.attribution_stage( path, make_need, trace_fn )() )
    assert asked == draw()[ "attribution" ][ "order" ] and out[ "seeds" ] == 50 and out[ "needs" ] == 49 and out[ "skipped" ] == [ asked[ 2 ] ]
    assert len( traced ) == 1 and [ n[ "seed" ] for n in traced[ 0 ] ] == [ i for i in asked if i != asked[ 2 ] ] and out[ "lists_sha" ] == draw()[ "sha" ]
    assert out[ "can_name_a_stage" ] is True and out[ "stop" ] is False and out[ "members" ] == 49 and out[ "lost" ] == 1


def test_the_attribution_stage_stops_without_a_trace_when_no_seed_gives_a_need( tmp_path ):
    path, traced = stage_seeds.write_lists( tmp_path, draw() ), []
    async def make_need( seed_id ): return None
    async def trace_fn( needs ):
        traced.append( needs )
        return []
    out = asyncio.run( stage_seeds.attribution_stage( path, make_need, trace_fn )() )
    assert out[ "stop" ] is True and out[ "reason" ] == "no seed gave a need" and out[ "needs" ] == 0 and len( out[ "skipped" ] ) == 50 and traced == []


def test_a_stage_built_on_a_missing_file_fails_by_name_when_it_runs_and_not_before( tmp_path ):
    stage = stage_seeds.attribution_stage( tmp_path / "gone.json", None, None )
    with pytest.raises( er.NeedsetError ) as caught: asyncio.run( stage() )
    assert caught.value.code == er.MANIFEST_MISMATCH


def entry( i, name, doc="" ): return { "id": i, "module": "m", "name": name, "sig": "()", "doc": doc }


def test_the_yield_stage_walks_the_written_order_and_reports_each_language_with_its_denominator( tmp_path ):
    path   = stage_seeds.write_lists( tmp_path, draw() )
    index  = hardness.build_index( [ entry( "m.easy", "banana_easy", "banana banana" ), entry( "m.hidden", "hidden", "turns one text into another" ) ] )
    asked  = []
    async def prepare( seed_id ):
        asked.append( seed_id )
        lang = "ts" if seed_id.startswith( "web." ) else "py"
        return { "seed": seed_id, "need": "banana", "targets": [ "m.hidden" if lang == "ts" else "m.easy" ], "lang": lang }
    out = asyncio.run( stage_seeds.yield_stage( path, prepare, index )() )
    assert asked == draw()[ "yield" ][ "order" ] and out[ "seeds" ] == 100 and out[ "drawn" ] == { "ts": 50, "py": 50 } and out[ "lists_sha" ] == draw()[ "sha" ]
    assert out[ "by_lang" ][ "ts" ] == { "seeds": 50, "hard": 50, "per_100": 100.0 } and out[ "by_lang" ][ "py" ] == { "seeds": 50, "hard": 0, "per_100": 0.0 }
    assert out[ "stop" ] is False and out[ "short" ] == [ "py", "ts" ]


def test_the_stage_functions_slot_into_the_runner( tmp_path ):
    import os
    from lupin_mcp.reuse_needset import call_cap
    path = stage_seeds.write_lists( tmp_path, draw() )
    cap  = call_cap.CallCap( os.path.join( tmp_path, "calls.jsonl" ) )
    async def make_need( seed_id ): return matched_need( seed_id )
    async def trace_fn( needs ): return trace_records( needs )
    async def prepare( seed_id ): return None
    async def nothing(): return {}
    funcs = { "attribution": stage_seeds.attribution_stage( path, make_need, trace_fn ), "yield": stage_seeds.yield_stage( path, prepare, hardness.build_index( [ entry( "m.a", "a" ) ] ) ),
              "control": nothing, "remainder": nothing }
    with cap.installed(): out = asyncio.run( stages.run_stages( cap, funcs ) )
    assert [ s[ "status" ] for s in out[ "stages" ].values() ] == [ "done" ] * 4 and out[ "stages" ][ "attribution" ][ "report" ][ "needs" ] == 50


def test_the_draw_is_pinned_so_a_change_to_the_seed_recipe_is_seen():
    r = draw()
    assert r[ "attribution" ][ "ts" ][ :3 ] == PIN_ATTRIBUTION_TS and r[ "yield" ][ "ts" ][ :3 ] == PIN_YIELD_TS
