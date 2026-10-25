"""
Labelling items, blind packets and the label reader.
"""
import json

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk


def need_item( n=0 ):
    """Return a matched need item."""
    return it.make_item( "need_key", f"n-{n:03d}", { "need": f"A function that does job {n} in a loop.", "key_sources": [ f"def key{n}(): pass" ] } )


def none_item( n=0 ):
    """Return a nothing-exists item."""
    return it.make_item( "need_key", f"z-{n:03d}", { "need": f"A function that does job {n} in a loop.", "nothing_exists": True, "hits": [ "pkg.a.f() — Adds." ] } )


def pair_item( n=0 ):
    """Return a pair item."""
    return it.make_item( "semdup_pair", f"p-{n:03d}", { "a": "def a(): pass", "b": "def b(): pass" } )


def code_of( fn, *args ):
    """Return the code of the LabellingError that fn raises."""
    with pytest.raises( er.LabellingError ) as e: fn( *args )
    return e.value.code


def test_the_three_item_shapes_are_valid_and_carry_their_fields():
    assert need_item()[ "type" ] == "need_key" and none_item()[ "payload" ][ "nothing_exists" ] is True and pair_item()[ "payload" ][ "a" ] == "def a(): pass"
    assert none_item()[ "payload" ][ "hits" ] and it.make_item( "need_key", "z", { "need": "x", "nothing_exists": True, "hits": [] } )[ "payload" ][ "hits" ] == []


@pytest.mark.parametrize( "item", [
    None, [], {}, { "item_id": "a", "type": "need_key" }, { "item_id": "", "type": "need_key", "payload": {} }, { "item_id": "a", "type": "odd", "payload": {} },
    { "item_id": "a", "type": "need_key", "payload": [] }, { "item_id": "a", "type": "semdup_pair", "payload": { "a": "x" } },
    { "item_id": "a", "type": "semdup_pair", "payload": { "a": "x", "b": " " } },
    { "item_id": "a", "type": "need_key", "payload": { "key_sources": [ "x" ] } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n" } }, { "item_id": "a", "type": "need_key", "payload": { "need": "n", "key_sources": [] } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "key_sources": [ "" ] } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "key_sources": "x" } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "key_sources": [ "x" ], "hits": [ "h" ] } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "key_sources": [ "x" ], "nothing_exists": False } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "nothing_exists": True } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "nothing_exists": True, "hits": "x" } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "nothing_exists": True, "hits": [ "h" ] * 11 } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "nothing_exists": True, "hits": [ "" ] } },
    { "item_id": "a", "type": "need_key", "payload": { "need": "n", "nothing_exists": True, "hits": [], "key_sources": [ "x" ] } } ] )
def test_a_malformed_item_is_refused_by_name( item ):
    assert code_of( it.validate_item, item ) == er.BAD_ITEM


def test_the_error_carries_its_code_and_detail():
    e = er.LabellingError( er.BAD_ITEM, "why" )
    assert str( e ) == "BAD_ITEM: why" and e.code == "BAD_ITEM" and e.detail == "why" and str( er.LabellingError( er.PACKET_LEAK ) ) == "PACKET_LEAK"


def test_two_reviewers_get_the_same_items_in_different_seeded_orders( tmp_path ):
    items = [ need_item( n ) for n in range( 8 ) ] + [ none_item( 1 ), pair_item( 2 ) ]
    paths = pk.export_packets( items, [ "rick", "sam" ], 7, tmp_path )
    rows  = { r: [ json.loads( l ) for l in p.read_text().splitlines() ] for r, p in paths.items() }
    ids   = { r: [ x[ "item_id" ] for x in v ] for r, v in rows.items() }
    assert set( ids[ "rick" ] ) == set( ids[ "sam" ] ) == { i[ "item_id" ] for i in items } and ids[ "rick" ] != ids[ "sam" ]
    assert pk.export_packets( items, [ "rick", "sam" ], 7, tmp_path / "again" )[ "rick" ].read_text() == paths[ "rick" ].read_text()
    assert pk.export_packets( items, [ "rick", "sam" ], 8, tmp_path / "other" )[ "rick" ].read_text() != paths[ "rick" ].read_text()
    assert paths[ "rick" ] == pk.packet_path( tmp_path, "rick" )
    assert all( set( x ) == { "item_id", "type", "payload" } for v in rows.values() for x in v )


def test_one_item_can_still_be_given_to_two_reviewers( tmp_path ):
    paths = pk.export_packets( [ need_item() ], [ "a", "b" ], 1, tmp_path )
    assert paths[ "a" ].read_text() == paths[ "b" ].read_text()


@pytest.mark.parametrize( "field, where", [ ( "verdict", "payload" ), ( "checker_note", "payload" ), ( "selection_route", "payload" ), ( "check", "item" ), ( "reason", "item" ) ] )
def test_an_item_that_carries_a_verdict_or_a_reason_is_a_packet_leak_and_nothing_is_written( tmp_path, field, where ):
    item = need_item()
    ( item[ "payload" ] if where == "payload" else item )[ field ] = "agree"
    assert code_of( pk.export_packets, [ item, need_item( 1 ) ], [ "a", "b" ], 1, tmp_path ) == er.PACKET_LEAK
    assert not list( tmp_path.glob( "packet-*" ) )


def test_a_leak_found_in_the_bytes_written_removes_the_packets( tmp_path, monkeypatch ):
    monkeypatch.setattr( pk, "seeded_order", lambda items, seed, taken: [ dict( i, verdict="agree" ) for i in items ] )
    assert code_of( pk.export_packets, [ need_item(), need_item( 1 ) ], [ "a", "b" ], 1, tmp_path ) == er.PACKET_LEAK
    assert not list( tmp_path.glob( "packet-*" ) )


@pytest.mark.parametrize( "items, reviewers", [ ( [ need_item(), need_item() ], [ "a", "b" ] ), ( [ need_item() ], [ "a" ] ), ( [ need_item() ], [ "a", "a" ] ), ( [ need_item() ], [ "a", "../b" ] ),
                                               ( [ need_item() ], [ "a", "" ] ), ( [ { "item_id": "x" } ], [ "a", "b" ] ) ] )
def test_duplicate_ids_a_bad_item_and_bad_reviewer_lists_are_refused( tmp_path, items, reviewers ):
    assert code_of( pk.export_packets, items, reviewers, 1, tmp_path ) == er.BAD_ITEM


def label( item="n-000", reviewer="rick", choice="AS_PROPOSED", symbols=(), note="", ts="2026-10-24T20:00:00-04:00" ):
    """Return a label record."""
    return { "item_id": item, "reviewer": reviewer, "choice": choice, "symbols": list( symbols ), "note": note, "ts": ts }


def write_labels( path, labels ):
    """Write labels as JSON lines."""
    path.write_text( "".join( ( l if isinstance( l, str ) else json.dumps( l ) ) + "\n" for l in labels ), encoding="utf-8" )
    return path


def test_labels_are_read_in_file_order_for_all_three_choices( tmp_path ):
    rows = [ label( "n-000" ), label( "n-001", choice="OTHER", symbols=[ "pkg.a.f" ], note="the other one" ), label( "n-002", choice="NONE" ) ]
    assert pk.read_labels( write_labels( tmp_path / "l.jsonl", rows ) ) == rows
    assert pk.read_labels( write_labels( tmp_path / "e.jsonl", [] ) ) == []


@pytest.mark.parametrize( "bad", [
    "not json", "[]", json.dumps( dict( label( "n-001" ), extra=1 ) ), json.dumps( { k: v for k, v in label( "n-001" ).items() if k != "ts" } ), json.dumps( dict( label( "n-001" ), item_id="" ) ),
    json.dumps( dict( label( "n-001" ), reviewer=3 ) ), json.dumps( dict( label( "n-001" ), note=None ) ), json.dumps( dict( label( "n-001" ), choice="MAYBE" ) ), json.dumps( dict( label( "n-001" ), choice="OTHER" ) ),
    json.dumps( dict( label( "n-001" ), symbols=[ "x" ] ) ), json.dumps( dict( label( "n-001" ), choice="OTHER", symbols=[ "" ] ) ), json.dumps( dict( label( "n-001" ), choice="OTHER", symbols="x" ) ) ] )
def test_a_malformed_label_is_refused_with_its_line( tmp_path, bad ):
    path = write_labels( tmp_path / "l.jsonl", [ label( "n-000" ), bad ] )
    with pytest.raises( er.LabellingError ) as e: pk.read_labels( path )
    assert e.value.code == er.BAD_LABEL and f"{path}:2:" in e.value.detail


def test_a_file_with_two_reviewers_or_one_item_twice_is_refused( tmp_path ):
    assert code_of( pk.read_labels, write_labels( tmp_path / "a.jsonl", [ label( "n-000" ), label( "n-001", reviewer="sam" ) ] ) ) == er.BAD_LABEL
    assert code_of( pk.read_labels, write_labels( tmp_path / "b.jsonl", [ label( "n-000" ), label( "n-000", choice="NONE" ) ] ) ) == er.BAD_LABEL
