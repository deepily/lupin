"""
Tests of the fit and check split of the labelled-pair run, drawn by twin group.

The split must be fixed before any call is made, so these tests pin what it promises.
A twin group is never cut across the two halves. The same seed gives the same halves whatever order
the manifest lists its groups in. The record carries the sha256 that goes into the plan.
"""
import hashlib
import json
import pathlib

import pytest

from cosa.repo.symindex import stage2_split as s2

SLICE = pathlib.Path( __file__ ).parent / "fixtures" / "stage2-manifest-slice.json"


def _m( *groups ):
    """Ensures: returns a minimal manifest from ( kind, [ids] ) pairs."""
    return { "exact": [ { "kind": "exact", "members": [ { "id": i } for i in ids ] } for kind, ids in groups if kind == "exact" ],
             "near" : [ { "kind": "near",  "members": [ { "id": i } for i in ids ] } for kind, ids in groups if kind == "near" ] }


def _many( n_exact, n_near ):
    """Ensures: returns n_exact exact groups and n_near near groups, two members each, all apart."""
    g  = [ ( "exact", [ f"e{k:03d}a", f"e{k:03d}b" ] ) for k in range( n_exact ) ]
    g += [ ( "near",  [ f"n{k:03d}a", f"n{k:03d}b" ] ) for k in range( n_near ) ]
    return _m( *g )


def _members( groups ): return sorted( i for g in groups for i in g[ "members" ] )


# --- the groups ----------------------------------------------------------------------------------------------------------

def test_a_member_in_an_exact_cluster_and_a_near_pair_joins_them_into_one_group():
    gs = s2.twin_groups( _m( ( "exact", [ "a", "b" ] ), ( "near", [ "b", "c" ] ), ( "near", [ "x", "y" ] ) ) )
    assert [ g[ "members" ] for g in gs ] == [ [ "a", "b", "c" ], [ "x", "y" ] ]


def test_a_group_with_any_exact_cluster_is_exact_and_a_near_only_group_is_near():
    gs = s2.twin_groups( _m( ( "exact", [ "a", "b" ] ), ( "near", [ "b", "c" ] ), ( "near", [ "x", "y" ] ) ) )
    assert [ g[ "stratum" ] for g in gs ] == [ "exact", "near" ]


def test_the_groups_do_not_depend_on_the_order_the_manifest_lists_them_in():
    a = _m( ( "exact", [ "a", "b" ] ), ( "near", [ "b", "c" ] ), ( "near", [ "x", "y" ] ) )
    b = _m( ( "near", [ "y", "x" ] ), ( "near", [ "c", "b" ] ), ( "exact", [ "b", "a" ] ) )
    assert s2.twin_groups( a ) == s2.twin_groups( b )


def test_the_real_manifest_slice_reads_as_twelve_groups_seven_of_them_exact():
    gs = s2.twin_groups( json.loads( SLICE.read_text() ) )
    assert ( len( gs ), sum( g[ "stratum" ] == "exact" for g in gs ) ) == ( 12, 7 )
    assert len( _members( gs ) ) == len( set( _members( gs ) ) )                                # no member sits in two groups


def test_a_group_of_one_member_is_refused_because_a_twin_group_needs_a_pair():
    with pytest.raises( ValueError, match="lone" ):
        s2.twin_groups( _m( ( "exact", [ "a" ] ) ) )


# --- the split -----------------------------------------------------------------------------------------------------------

def test_each_stratum_is_halved_and_the_fit_half_takes_the_odd_group():
    gs   = s2.twin_groups( _many( 88, 63 ) )
    half = s2.split_groups( gs, 7 )
    count = lambda h, st: sum( g[ "stratum" ] == st for g in half[ h ] )
    assert ( count( "fit", "exact" ), count( "check", "exact" ), count( "fit", "near" ), count( "check", "near" ) ) == ( 44, 44, 32, 31 )
    assert ( len( half[ "fit" ] ), len( half[ "check" ] ) ) == ( 76, 75 )


def test_every_group_lands_in_exactly_one_half_and_no_member_is_in_both():
    gs   = s2.twin_groups( _many( 20, 15 ) )
    half = s2.split_groups( gs, 7 )
    assert sorted( _members( half[ "fit" ] ) + _members( half[ "check" ] ) ) == _members( gs )
    assert not set( _members( half[ "fit" ] ) ) & set( _members( half[ "check" ] ) )


def test_the_same_seed_gives_the_same_split_whatever_order_the_groups_come_in():
    gs = s2.twin_groups( _many( 20, 15 ) )
    assert s2.split_groups( gs, 7 ) == s2.split_groups( list( reversed( gs ) ), 7 )


def test_a_different_seed_gives_a_different_split():
    gs = s2.twin_groups( _many( 20, 15 ) )
    assert s2.split_groups( gs, 7 ) != s2.split_groups( gs, 8 )


def test_the_seed_is_required_and_has_no_default():
    with pytest.raises( TypeError ):
        s2.split_groups( s2.twin_groups( _many( 2, 2 ) ) )


def test_a_stratum_with_one_group_puts_it_in_the_fit_half_and_leaves_the_check_half_without_that_stratum():
    half = s2.split_groups( s2.twin_groups( _many( 1, 0 ) ), 7 )
    assert ( len( half[ "fit" ] ), len( half[ "check" ] ) ) == ( 1, 0 )


def test_within_a_half_the_groups_are_listed_in_member_order():
    half = s2.split_groups( s2.twin_groups( _many( 20, 15 ) ), 7 )
    for h in ( "fit", "check" ):
        firsts = [ g[ "members" ][ 0 ] for g in half[ h ] ]
        assert firsts == sorted( firsts )


# --- the record that goes into the plan ----------------------------------------------------------------------------------

def test_the_record_names_the_seed_the_manifest_sha_the_counts_and_both_halves():
    r = s2.split_record( _many( 4, 3 ), "ab" * 32, 7 )
    assert ( r[ "seed" ], r[ "manifest_sha256" ] ) == ( 7, "ab" * 32 )
    assert ( r[ "groups" ], r[ "members" ] ) == ( 7, 14 )
    assert ( len( r[ "fit" ] ), len( r[ "check" ] ) ) == ( 4, 3 )
    assert r[ "fit" ][ 0 ][ "members" ] and r[ "unit" ] == "twin group"


def test_the_record_sha_is_the_sha_of_its_canonical_text_and_moves_when_one_group_moves():
    r = s2.split_record( _many( 4, 3 ), "ab" * 32, 7 )
    assert s2.record_sha256( r ) == hashlib.sha256( json.dumps( r, sort_keys=True, separators=( ",", ":" ) ).encode() ).hexdigest()
    moved = json.loads( json.dumps( r ) ); moved[ "fit" ].append( moved[ "check" ].pop() )
    assert s2.record_sha256( moved ) != s2.record_sha256( r )


def test_half_by_member_gives_every_member_its_half():
    r = s2.split_record( _many( 4, 3 ), "ab" * 32, 7 )
    h = s2.half_by_member( r )
    assert len( h ) == 14 and set( h.values() ) == { "fit", "check" }
    for g in r[ "fit" ]:   assert all( h[ i ] == "fit" for i in g[ "members" ] )
    for g in r[ "check" ]: assert all( h[ i ] == "check" for i in g[ "members" ] )


# --- the command line ----------------------------------------------------------------------------------------------------

def test_the_command_writes_the_record_and_prints_its_sha(tmp_path, capsys):
    out = tmp_path / "split.json"
    rc  = s2.main( [ "--manifest", str( SLICE ), "--seed", "7", "--out", str( out ) ] )
    r   = json.loads( out.read_text() )
    assert rc == 0
    assert r[ "manifest_sha256" ] == hashlib.sha256( SLICE.read_bytes() ).hexdigest()
    assert r[ "groups" ] == 12 and ( len( r[ "fit" ] ), len( r[ "check" ] ) ) == ( 7, 5 )
    assert s2.record_sha256( r ) in capsys.readouterr().out


def test_the_command_refuses_to_overwrite_a_record_that_already_exists(tmp_path):
    out = tmp_path / "split.json"; out.write_text( "{}" )
    with pytest.raises( FileExistsError, match="already exists" ):
        s2.main( [ "--manifest", str( SLICE ), "--seed", "7", "--out", str( out ) ] )
    assert out.read_text() == "{}"


def test_the_command_needs_a_seed():
    with pytest.raises( SystemExit ):
        s2.main( [ "--manifest", str( SLICE ), "--out", "x.json" ] )
