"""
The kind-by-language table, the census, the seeded draw and the plan record.
"""
import json
import threading

import pytest

from cosa.repo.doc_lint.quota_split import quotas
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import quota

EXAMPLE = { "near_copy": 120, "work_alike": 120, "cross_language": 60 }


def margins( table ):
    """Return ( ts total, py total, matched total, none total ) of a plan_quota table."""
    ts = sum( row[ "ts" ] for row in table.values() )
    py = sum( row[ "py" ] for row in table.values() )
    none = sum( table[ "nothing" ].values() )
    return ts, py, ts + py - none, none


def test_the_example_split_gives_the_planned_cells_and_exact_margins():
    table = quota.plan_quota( 400, 300, 100, 0.6, EXAMPLE )
    assert table == { "near_copy": { "ts": 72, "py": 48 }, "work_alike": { "ts": 72, "py": 48 },
                      "cross_language": { "ts": 36, "py": 24 }, "nothing": { "ts": 60, "py": 40 } }
    assert margins( table ) == ( 240, 160, 300, 100 )


def test_any_split_keeps_the_language_margins():
    for split in ( { "near_copy": 101, "work_alike": 100, "cross_language": 99 }, { "near_copy": 300, "work_alike": 0, "cross_language": 0 },
                   { "near_copy": 7, "work_alike": 250, "cross_language": 43 } ):
        assert margins( quota.plan_quota( 400, 300, 100, 0.6, split ) ) == ( 240, 160, 300, 100 )
        for kind, row in quota.plan_quota( 400, 300, 100, 0.6, split ).items():
            if kind != "nothing": assert row[ "ts" ] + row[ "py" ] == split[ kind ]


def test_the_margins_hold_over_a_grid_of_small_totals_and_shares():
    for total in range( 0, 31 ):
        for none in range( 0, total + 1 ):
            for share in ( 0, 0.1, 0.25, 1 / 3, 0.5, 0.6, 2 / 3, 0.9, 1.0 ):
                split = { "near_copy": total - none, "work_alike": 0, "cross_language": 0 }
                table = quota.plan_quota( total, total - none, none, share, split )
                ts, py, matched, nothing = margins( table )
                assert ( ts, py ) == ( quotas( total, { "ts": share, "py": 1 - share } )[ "ts" ], total - quotas( total, { "ts": share, "py": 1 - share } )[ "ts" ] )
                assert ( matched, nothing ) == ( total - none, none )


def test_an_empty_plan_is_all_zeros():
    assert margins( quota.plan_quota( 0, 0, 0, 0.6, { "near_copy": 0, "work_alike": 0, "cross_language": 0 } ) ) == ( 0, 0, 0, 0 )


def test_no_kind_split_raises_and_no_default_exists():
    with pytest.raises( er.NeedsetError ) as e: quota.plan_quota( 400, 300, 100, 0.6 )
    assert e.value.code == er.KIND_SPLIT_UNSET
    with pytest.raises( er.NeedsetError ) as e: quota.plan_quota( 400, 300, 100, 0.6, None )
    assert e.value.code == er.KIND_SPLIT_UNSET


@pytest.mark.parametrize( "args, kind_split, message", [
    ( ( -1, 300, 100, 0.6 ),    EXAMPLE,                                                    "total must be a whole number" ),
    ( ( 400, 300.0, 100, 0.6 ), EXAMPLE,                                                    "matched must be a whole number" ),
    ( ( 400, 300, True, 0.6 ),  EXAMPLE,                                                    "none must be a whole number" ),
    ( ( 400, 300, 99, 0.6 ),    EXAMPLE,                                                    "is not total" ),
    ( ( 400, 300, 100, 1.5 ),   EXAMPLE,                                                    "ts_share must be" ),
    ( ( 400, 300, 100, "0.6" ), EXAMPLE,                                                    "ts_share must be" ),
    ( ( 400, 300, 100, 0.6 ),   { "near_copy": 300, "work_alike": 0 },                      "exactly the kinds" ),
    ( ( 400, 300, 100, 0.6 ),   { "near_copy": 120, "work_alike": 120, "cross_language": 59 }, "sums to 299" ),
    ( ( 400, 300, 100, 0.6 ),   { "near_copy": 320, "work_alike": -20, "cross_language": 0 }, "must be a whole number of 0 or more" ),
    ( ( 400, 300, 100, 0.6 ),   { "near_copy": 120.0, "work_alike": 120, "cross_language": 60 }, "must be a whole number of 0 or more" ),
] )
def test_an_invalid_plan_is_refused_by_name(args, kind_split, message):
    with pytest.raises( er.NeedsetError, match=message ) as e: quota.plan_quota( *args, kind_split=kind_split )
    assert e.value.code == er.QUOTA_INVALID


def pool_of( per_cell ):
    """Build a pool with per_cell ids in every cell, different in every cell."""
    return { ( kind, lang ): [ f"{kind}.{lang}.sym{i:03d}" for i in range( per_cell ) ] for kind in quota.ALL_KINDS for lang in quota.LANGS }


def test_census_counts_distinct_ids_per_cell_and_treats_a_missing_cell_as_zero():
    pool = { ( "near_copy", "ts" ): [ "a", "a", "b" ], ( "nothing", "py" ): [ "f1" ] }
    got  = quota.census( pool )
    assert got[ "near_copy" ] == { "ts": 2, "py": 0 } and got[ "nothing" ] == { "ts": 0, "py": 1 } and got[ "work_alike" ] == { "ts": 0, "py": 0 }
    assert set( got ) == set( quota.ALL_KINDS )


def test_the_draw_takes_the_quota_from_each_cell_with_spares_and_no_shared_primary():
    table = quota.plan_quota( 40, 30, 10, 0.6, { "near_copy": 12, "work_alike": 12, "cross_language": 6 } )
    got   = quota.draw( pool_of( 12 ), table, 20261024 )
    primaries = [ s for cell in got.values() for s in cell[ "primary" ] ]
    assert len( primaries ) == len( set( primaries ) ) == 40
    for ( kind, lang ), cell in got.items():
        assert len( cell[ "primary" ] ) == table[ kind ][ lang ]
        assert not set( cell[ "spares" ] ) & set( primaries )
        assert not set( cell[ "spares" ] ) & set( cell[ "primary" ] )


def test_the_draw_is_the_same_for_the_same_seed_whatever_order_the_pool_lists_its_ids():
    table = quota.plan_quota( 40, 30, 10, 0.6, { "near_copy": 12, "work_alike": 12, "cross_language": 6 } )
    pool  = pool_of( 16 )
    again = { cell: list( reversed( ids ) ) for cell, ids in pool.items() }
    assert quota.draw( pool, table, 7 ) == quota.draw( again, table, 7 )
    assert quota.draw( pool, table, 7 ) != quota.draw( pool, table, 8 )


def test_a_cell_one_short_raises_with_the_cell_named():
    table = quota.plan_quota( 40, 30, 10, 0.6, { "near_copy": 12, "work_alike": 12, "cross_language": 6 } )
    pool  = pool_of( 12 )
    pool[ ( "cross_language", "ts" ) ] = pool[ ( "cross_language", "ts" ) ][ : 3 ]
    with pytest.raises( er.NeedsetError ) as e: quota.draw( pool, table, 1 )
    assert e.value.code == er.QUOTA_UNFILLABLE and "cross_language/ts" in str( e.value ) and "has 3" in str( e.value )


def two_cell_table( a, b ):
    """Return a quota of a near_copy and b work_alike ts seeds, and nothing elsewhere."""
    table = { k: { "ts": 0, "py": 0 } for k in quota.ALL_KINDS }
    table[ "near_copy" ][ "ts" ]  = a
    table[ "work_alike" ][ "ts" ] = b
    return table


def test_cells_that_need_the_same_ids_raise_and_name_the_cell_when_the_ids_run_out():
    pool = { ( "near_copy", "ts" ): [ "a", "b", "c" ], ( "work_alike", "ts" ): [ "a", "b", "c" ] }
    with pytest.raises( er.NeedsetError ) as e: quota.draw( pool, two_cell_table( 2, 2 ), 3 )
    assert e.value.code == er.QUOTA_UNFILLABLE and "work_alike/ts" in str( e.value ) and "other cells need the same ones" in str( e.value )


def test_a_valid_assignment_is_found_when_a_scarce_cell_shares_its_only_seeds_with_an_earlier_cell():
    pool = { ( "cross_language", "ts" ): [ "a", "b" ], ( "work_alike", "ts" ): [ "a" ] }
    table = { k: { "ts": 0, "py": 0 } for k in quota.ALL_KINDS }
    table[ "cross_language" ][ "ts" ] = 1
    table[ "work_alike" ][ "ts" ]     = 1
    for seed in range( 60 ):
        got = quota.draw( pool, table, seed )
        assert got[ ( "work_alike", "ts" ) ][ "primary" ] == [ "a" ] and got[ ( "cross_language", "ts" ) ][ "primary" ] == [ "b" ]


def test_a_chain_of_shared_ids_is_untangled_by_moving_earlier_picks():
    pool = { ( "cross_language", "ts" ): [ "a", "b" ], ( "near_copy", "ts" ): [ "b", "c" ], ( "work_alike", "ts" ): [ "c" ] }
    table = { k: { "ts": 0, "py": 0 } for k in quota.ALL_KINDS }
    for kind in ( "cross_language", "near_copy", "work_alike" ): table[ kind ][ "ts" ] = 1
    for seed in range( 40 ):
        got = quota.draw( pool, table, seed )
        assert [ got[ ( k, "ts" ) ][ "primary" ] for k in ( "cross_language", "near_copy", "work_alike" ) ] == [ [ "a" ], [ "b" ], [ "c" ] ]


def test_a_cell_short_on_its_own_says_so_and_does_not_blame_the_others():
    pool = { ( "near_copy", "ts" ): [ "a" ] }
    with pytest.raises( er.NeedsetError ) as e: quota.draw( pool, two_cell_table( 2, 0 ), 3 )
    assert "near_copy/ts has 1 eligible seeds, needs 2" in str( e.value ) and "other cells" not in str( e.value )


def test_every_spare_belongs_to_one_cell_and_is_never_a_primary_anywhere():
    table = quota.plan_quota( 40, 30, 10, 0.6, { "near_copy": 12, "work_alike": 12, "cross_language": 6 } )
    shared = [ f"shared{i}" for i in range( 30 ) ]
    pool   = { cell: ids + shared for cell, ids in pool_of( 12 ).items() }
    for seed in range( 10 ):
        got       = quota.draw( pool, table, seed )
        primaries = [ s for cell in got.values() for s in cell[ "primary" ] ]
        spares    = [ s for cell in got.values() for s in cell[ "spares" ] ]
        assert len( primaries ) == len( set( primaries ) ) == 40
        assert len( spares ) == len( set( spares ) ) and not set( spares ) & set( primaries )
        for cell, row in got.items():
            assert set( row[ "primary" ] + row[ "spares" ] ) <= set( pool[ cell ] )
        assert set( spares ) | set( primaries ) == { s for ids in pool.values() for s in ids }


def test_the_draw_with_shared_ids_is_the_same_for_the_same_seed_and_pool_order_does_not_matter():
    pool  = { ( "near_copy", "ts" ): [ "a", "b", "c", "d" ], ( "work_alike", "ts" ): [ "c", "d", "e", "f" ] }
    table = two_cell_table( 2, 2 )
    again = { cell: list( reversed( ids ) ) for cell, ids in pool.items() }
    assert quota.draw( pool, table, 11 ) == quota.draw( again, table, 11 )


def test_the_plan_record_carries_seed_table_split_commit_reader_and_who_set_it(tmp_path):
    table  = quota.plan_quota( 400, 300, 100, 0.6, EXAMPLE )
    record = quota.plan_record( 20261024, table, EXAMPLE, "abc123", "read_searchable", "rick", "2026-10-25T09:00:00-04:00" )
    assert record[ "format" ] == "needset-plan-1" and record[ "quota" ][ "near_copy/ts" ] == 72 and record[ "kind_split" ] == EXAMPLE
    assert record[ "pool_reader" ] == "read_searchable" and record[ "kind_split_set_by" ] == "rick" and record[ "source_commit" ] == "abc123"
    path = tmp_path / "plan.json"
    quota.write_plan( path, record )
    assert json.loads( path.read_text( encoding="utf-8" ) ) == record


def test_the_plan_is_written_once_and_a_second_write_leaves_the_first_untouched(tmp_path):
    path = tmp_path / "plan.json"
    quota.write_plan( path, { "seed": 1 } )
    before = path.read_bytes()
    with pytest.raises( er.NeedsetError ) as e: quota.write_plan( path, { "seed": 2 } )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN and path.read_bytes() == before


def test_of_many_writers_racing_for_one_path_exactly_one_succeeds_and_the_file_is_whole(tmp_path):
    path    = tmp_path / "plan.json"
    barrier = threading.Barrier( 16 )
    results = {}

    def writer( n ):
        barrier.wait()
        try:
            quota.write_plan( path, { "seed": n, "pad": "x" * 5000 } )
            results[ n ] = "ok"
        except er.NeedsetError as e:
            results[ n ] = e.code

    threads = [ threading.Thread( target=writer, args=( n, ) ) for n in range( 16 ) ]
    for th in threads: th.start()
    for th in threads: th.join()
    winners = [ n for n, r in results.items() if r == "ok" ]
    assert len( winners ) == 1 and sorted( r for r in results.values() if r != "ok" ) == [ er.PLAN_ALREADY_WRITTEN ] * 15
    assert json.loads( path.read_text( encoding="utf-8" ) )[ "seed" ] == winners[ 0 ]
    assert sorted( p.name for p in tmp_path.iterdir() ) == [ "plan.json" ]


def test_a_failed_link_leaves_no_plan_and_no_temporary_file(tmp_path, monkeypatch):
    def broken( src, dst ): raise OSError( "disk full" )
    monkeypatch.setattr( quota.os, "link", broken )
    with pytest.raises( OSError, match="disk full" ): quota.write_plan( tmp_path / "plan.json", { "seed": 1 } )
    assert list( tmp_path.iterdir() ) == []


def test_spares_come_out_in_the_seeded_shuffle_not_in_id_order():
    table = quota.plan_quota( 40, 30, 10, 0.6, { "near_copy": 12, "work_alike": 12, "cross_language": 6 } )
    pool  = pool_of( 30 )
    orders = []
    for seed in range( 8 ):
        got = quota.draw( pool, table, seed )
        orders.append( got[ ( "near_copy", "ts" ) ][ "spares" ] )
    assert any( o != sorted( o ) for o in orders ), "every spares list was in id order"
    assert len( { tuple( o ) for o in orders } ) > 1, "the spares order did not change with the seed"
    assert quota.draw( pool, table, 3 )[ ( "near_copy", "ts" ) ][ "spares" ] == quota.draw( pool, table, 3 )[ ( "near_copy", "ts" ) ][ "spares" ]


def test_a_plan_record_refuses_a_reader_the_pool_does_not_use():
    table = quota.plan_quota( 400, 300, 100, 0.6, EXAMPLE )
    with pytest.raises( er.NeedsetError ) as e: quota.plan_record( 1, table, EXAMPLE, "abc123", "read_symbols", "rick", "2026-10-25T09:00:00-04:00" )
    assert e.value.code == er.QUOTA_INVALID and "read_searchable" in e.value.detail
