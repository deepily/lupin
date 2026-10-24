"""
The kind-by-language table, the census, the seeded draw and the plan record.
"""
import json

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


def test_an_id_taken_as_a_primary_by_one_cell_is_not_offered_to_the_next():
    table = { k: { "ts": 0, "py": 0 } for k in quota.ALL_KINDS }
    table[ "near_copy" ][ "ts" ] = 2
    table[ "work_alike" ][ "ts" ] = 2
    pool = { ( "near_copy", "ts" ): [ "a", "b", "c" ], ( "work_alike", "ts" ): [ "a", "b", "c" ] }
    with pytest.raises( er.NeedsetError, match="work_alike/ts has 1" ): quota.draw( pool, table, 3 )


def test_the_plan_record_carries_seed_table_split_commit_reader_and_who_set_it(tmp_path):
    table  = quota.plan_quota( 400, 300, 100, 0.6, EXAMPLE )
    record = quota.plan_record( 20261024, table, EXAMPLE, "abc123", "read_symbols", "rick", "2026-10-25T09:00:00-04:00" )
    assert record[ "format" ] == "needset-plan-1" and record[ "quota" ][ "near_copy/ts" ] == 72 and record[ "kind_split" ] == EXAMPLE
    assert record[ "pool_reader" ] == "read_symbols" and record[ "kind_split_set_by" ] == "rick" and record[ "source_commit" ] == "abc123"
    path = tmp_path / "plan.json"
    quota.write_plan( path, record )
    assert json.loads( path.read_text( encoding="utf-8" ) ) == record


def test_the_plan_is_written_once_and_a_second_write_leaves_the_first_untouched(tmp_path):
    path = tmp_path / "plan.json"
    quota.write_plan( path, { "seed": 1 } )
    before = path.read_bytes()
    with pytest.raises( er.NeedsetError ) as e: quota.write_plan( path, { "seed": 2 } )
    assert e.value.code == er.PLAN_ALREADY_WRITTEN and path.read_bytes() == before
