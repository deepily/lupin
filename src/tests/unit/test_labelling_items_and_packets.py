"""
Labelling items, blind packets and the label reader.
"""
import json

import pytest

from cosa.repo.labelling import errors as er
from cosa.repo.labelling import items as it
from cosa.repo.labelling import packets as pk


PROV = { "source_commit": "a" * 40, "index_generation": "gen-0123456789" }


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
    paths = pk.export_packets( items, [ "rick", "sam" ], 7, tmp_path, PROV )
    rows  = { r: [ json.loads( l ) for l in p.read_text().splitlines() ] for r, p in paths.items() }
    ids   = { r: [ x[ "item_id" ] for x in v ] for r, v in rows.items() }
    assert set( ids[ "rick" ] ) == set( ids[ "sam" ] ) == { i[ "item_id" ] for i in items } and ids[ "rick" ] != ids[ "sam" ]
    assert pk.export_packets( items, [ "rick", "sam" ], 7, tmp_path / "again", PROV )[ "rick" ].read_text() == paths[ "rick" ].read_text()
    assert pk.export_packets( items, [ "rick", "sam" ], 8, tmp_path / "other", PROV )[ "rick" ].read_text() != paths[ "rick" ].read_text()
    assert paths[ "rick" ] == pk.packet_path( tmp_path, "rick" )
    assert all( set( x ) == { "item_id", "type", "payload" } for v in rows.values() for x in v )


def test_one_item_can_still_be_given_to_two_reviewers( tmp_path ):
    paths = pk.export_packets( [ need_item() ], [ "a", "b" ], 1, tmp_path, PROV )
    assert paths[ "a" ].read_text() == paths[ "b" ].read_text()


@pytest.mark.parametrize( "field, where", [ ( "verdict", "payload" ), ( "checker_note", "payload" ), ( "selection_route", "payload" ), ( "check", "item" ), ( "reason", "item" ) ] )
def test_an_item_that_carries_a_verdict_or_a_reason_is_a_packet_leak_and_nothing_is_written( tmp_path, field, where ):
    item = need_item()
    ( item[ "payload" ] if where == "payload" else item )[ field ] = "agree"
    assert code_of( pk.export_packets, [ item, need_item( 1 ) ], [ "a", "b" ], 1, tmp_path, PROV ) == er.PACKET_LEAK
    assert not list( tmp_path.glob( "packet-*" ) )


def test_a_leak_found_in_the_bytes_written_removes_the_packets( tmp_path, monkeypatch ):
    monkeypatch.setattr( pk, "seeded_order", lambda items, seed, taken: [ dict( i, verdict="agree" ) for i in items ] )
    assert code_of( pk.export_packets, [ need_item(), need_item( 1 ) ], [ "a", "b" ], 1, tmp_path, PROV ) == er.PACKET_LEAK
    assert not list( tmp_path.glob( "packet-*" ) )


@pytest.mark.parametrize( "items, reviewers", [ ( [ need_item(), need_item() ], [ "a", "b" ] ), ( [ need_item() ], [ "a" ] ), ( [ need_item() ], [ "a", "a" ] ), ( [ need_item() ], [ "a", "../b" ] ),
                                               ( [ need_item() ], [ "a", "" ] ), ( [ { "item_id": "x" } ], [ "a", "b" ] ) ] )
def test_duplicate_ids_a_bad_item_and_bad_reviewer_lists_are_refused( tmp_path, items, reviewers ):
    assert code_of( pk.export_packets, items, reviewers, 1, tmp_path, PROV ) == er.BAD_ITEM


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


def test_a_file_with_two_reviewers_is_refused_by_both_readers( tmp_path ):
    path = write_labels( tmp_path / "a.jsonl", [ label( "n-000" ), label( "n-001", reviewer="sam" ) ] )
    assert code_of( pk.read_labels, path ) == er.BAD_LABEL and code_of( pk.read_history, path ) == er.BAD_LABEL


def test_an_item_answered_again_counts_once_at_its_latest_answer_and_the_history_keeps_every_answer( tmp_path ):
    rows = [ label( "n-000" ), label( "n-001" ), label( "n-000", choice="NONE", note="second thought" ), label( "n-000", note="third thought" ) ]
    path = write_labels( tmp_path / "l.jsonl", rows )
    assert pk.read_history( path ) == rows
    assert pk.read_labels( path ) == [ rows[ 3 ], rows[ 1 ] ]
    assert pk.latest_labels( [] ) == []


# ---- export_subset_packet ----------------------------------------------------------------------------------------

def test_a_subset_packet_holds_only_the_named_items_in_an_order_no_earlier_packet_used( tmp_path ):
    items = [ need_item( n ) for n in range( 8 ) ]
    pk.export_packets( items, [ "rick", "sam" ], 7, tmp_path, PROV )
    named = [ i[ "item_id" ] for i in items[ :5 ] ]
    path  = pk.export_subset_packet( tmp_path, named, "third", 7 )
    got   = [ json.loads( l ) for l in path.read_text().splitlines() ]
    seen  = [ [ x for x in ( json.loads( l )[ "item_id" ] for l in pk.packet_path( tmp_path, r ).read_text().splitlines() ) if x in named ] for r in ( "rick", "sam" ) ]
    assert path == pk.packet_path( tmp_path, "third" ) and sorted( g[ "item_id" ] for g in got ) == sorted( named )
    assert [ g[ "item_id" ] for g in got ] not in seen and all( set( g ) == { "item_id", "type", "payload" } for g in got )


@pytest.mark.parametrize( "named, reviewer", [ ( [], "third" ), ( [ "n-099" ], "third" ), ( [ "n-000" ], "rick" ), ( [ "n-000" ], "../x" ) ] )
def test_a_subset_packet_refuses_no_items_an_unknown_item_and_a_used_or_bad_name( tmp_path, named, reviewer ):
    pk.export_packets( [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, PROV )
    assert code_of( pk.export_subset_packet, tmp_path, named, reviewer, 7 ) == er.BAD_ITEM
    assert not pk.packet_path( tmp_path, "third" ).exists()


def test_a_subset_packet_needs_earlier_packets_to_draw_from( tmp_path ):
    assert code_of( pk.export_subset_packet, tmp_path, [ "n-000" ], "third", 7 ) == er.BAD_ITEM


def test_a_leak_found_in_the_subset_bytes_written_removes_the_packet( tmp_path, monkeypatch ):
    pk.export_packets( [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, PROV )
    monkeypatch.setattr( pk, "seeded_order", lambda items, seed, taken: [ dict( i, verdict="agree" ) for i in items ] )
    assert code_of( pk.export_subset_packet, tmp_path, [ "n-000" ], "third", 7 ) == er.PACKET_LEAK
    assert not pk.packet_path( tmp_path, "third" ).exists()
    assert not pk._provenance_path( pk.packet_path( tmp_path, "third" ) ).exists()


# ---- a duplicate answer that save_label could not have written ---------------------------------------------------

def test_an_answer_stamped_earlier_than_the_answer_it_replaces_is_refused_as_not_written_by_save_label( tmp_path ):
    path = write_labels( tmp_path / "l.jsonl", [ label( "n-000", ts="2026-10-31T12:00:00+00:00" ), label( "n-000", choice="NONE", ts="2026-10-31T11:59:59+00:00" ) ] )
    for read in ( pk.read_history, pk.read_labels ):
        with pytest.raises( er.LabellingError ) as e: read( path )
        assert e.value.code == er.BAD_LABEL and f"{path}:2:" in e.value.detail and "earlier" in e.value.detail


def test_a_duplicate_answer_whose_time_cannot_be_read_is_refused_and_a_single_odd_time_is_not( tmp_path ):
    odd = write_labels( tmp_path / "odd.jsonl", [ label( "n-000", ts="2026-10-31T12:00:00+00:00" ), label( "n-000", choice="NONE", ts="yesterday" ) ] )
    with pytest.raises( er.LabellingError ) as e: pk.read_history( odd )
    assert e.value.code == er.BAD_LABEL and f"{odd}:2:" in e.value.detail and "time" in e.value.detail
    single = write_labels( tmp_path / "single.jsonl", [ label( "n-000", ts="yesterday" ), label( "n-001", ts="today" ) ] )
    assert len( pk.read_history( single ) ) == 2


def test_a_re_answer_in_the_same_second_or_later_is_accepted_whatever_the_zone_or_a_missing_one( tmp_path ):
    rows = [ label( "n-000", ts="2026-10-31T12:00:00+00:00" ), label( "n-000", choice="NONE", ts="2026-10-31T12:00:00+00:00" ),
             label( "n-000", ts="2026-10-31T08:00:01-04:00" ), label( "n-000", choice="NONE", ts="2026-10-31T12:00:02" ) ]
    assert pk.read_labels( write_labels( tmp_path / "l.jsonl", rows ) ) == [ rows[ 3 ] ]


def test_a_repeat_whose_earlier_time_cannot_be_read_is_refused_too( tmp_path ):
    path = write_labels( tmp_path / "l.jsonl", [ label( "n-000", ts="yesterday" ), label( "n-000", choice="NONE", ts="2026-10-31T12:00:00+00:00" ) ] )
    with pytest.raises( er.LabellingError ) as e: pk.read_history( path )
    assert e.value.code == er.BAD_LABEL and f"{path}:2:" in e.value.detail and "cannot be read" in e.value.detail


def test_a_repeat_is_compared_with_the_answer_just_before_it_and_not_with_the_first( tmp_path ):
    rows = [ label( "n-000", ts="2026-10-31T12:00:00+00:00" ), label( "n-000", choice="NONE", ts="2026-10-31T12:05:00+00:00" ),
             label( "n-000", ts="2026-10-31T12:03:00+00:00" ) ]
    path = write_labels( tmp_path / "l.jsonl", rows )
    with pytest.raises( er.LabellingError ) as e: pk.read_history( path )
    assert e.value.code == er.BAD_LABEL and f"{path}:3:" in e.value.detail and "earlier" in e.value.detail


# ---- provenance: the commit and index generation a packet was cut from --------------------------------------------

def test_every_packet_carries_the_commit_and_index_generation_it_was_cut_from( tmp_path ):
    paths = pk.export_packets( [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, PROV )
    for path in paths.values():
        assert pk._provenance_path( path ).name == path.name.replace( ".jsonl", ".provenance.json" )
        assert pk.read_provenance( path ) == PROV
    assert sorted( p.name for p in tmp_path.glob( "packet-*.jsonl" ) ) == [ "packet-rick.jsonl", "packet-sam.jsonl" ]


@pytest.mark.parametrize( "bad", [ { }, { "source_commit": "a" * 40 }, { "index_generation": "gen-1" }, { "source_commit": "", "index_generation": "gen-1" },
                                   { "source_commit": "main", "index_generation": "gen-1" }, { "source_commit": "A" * 40, "index_generation": "gen-1" },
                                   { "source_commit": "a" * 6, "index_generation": "gen-1" }, { "source_commit": "a" * 41, "index_generation": "gen-1" },
                                   { "source_commit": None, "index_generation": "gen-1" }, { "source_commit": "a" * 40, "index_generation": " " },
                                   { "source_commit": "a" * 40, "index_generation": None }, { "source_commit": "a" * 40, "index_generation": 7 }, "a" * 40, None ] )
def test_a_packet_without_a_commit_or_an_index_generation_is_refused_and_nothing_is_written( tmp_path, bad ):
    assert code_of( pk.export_packets, [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, bad ) == er.PROVENANCE_MISSING
    assert not list( tmp_path.glob( "packet-*" ) )


def test_the_packet_writer_drops_a_field_that_is_not_provenance_and_names_the_missing_commit( tmp_path ):
    assert pk.check_provenance( { **PROV, "note": "x" } ) == PROV
    with pytest.raises( er.LabellingError ) as e: pk.check_provenance( { "index_generation": "gen-1" }, "key.json" )
    assert e.value.code == er.PROVENANCE_MISSING and "key.json" in e.value.detail and "source_commit" in e.value.detail
    with pytest.raises( er.LabellingError ) as e: pk.check_provenance( { "source_commit": "a" * 40 } )
    assert "index_generation" in e.value.detail


def test_a_packet_cut_before_the_commit_was_recorded_has_no_provenance_to_read( tmp_path ):
    old = tmp_path / "packet-rick.jsonl"
    old.write_text( "", encoding="utf-8" )
    with pytest.raises( er.LabellingError ) as e: pk.read_provenance( old )
    assert e.value.code == er.PROVENANCE_MISSING and "before the commit was recorded" in e.value.detail
    pk._provenance_path( old ).write_text( "not json", encoding="utf-8" )
    assert code_of( pk.read_provenance, old ) == er.PROVENANCE_MISSING
    pk._provenance_path( old ).write_text( json.dumps( { "source_commit": "a" * 40 } ), encoding="utf-8" )
    assert code_of( pk.read_provenance, old ) == er.PROVENANCE_MISSING


def test_a_leak_found_in_the_bytes_written_removes_the_provenance_files_too( tmp_path, monkeypatch ):
    monkeypatch.setattr( pk, "seeded_order", lambda items, seed, taken: [ dict( i, verdict="agree" ) for i in items ] )
    assert code_of( pk.export_packets, [ need_item(), need_item( 1 ) ], [ "a", "b" ], 1, tmp_path, PROV ) == er.PACKET_LEAK
    assert not list( tmp_path.iterdir() )


def test_a_subset_packet_inherits_the_provenance_of_the_packets_it_draws_from( tmp_path ):
    pk.export_packets( [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, PROV )
    path = pk.export_subset_packet( tmp_path, [ "n-000" ], "third", 7 )
    assert pk.read_provenance( path ) == PROV


def test_a_subset_packet_is_refused_when_an_earlier_packet_has_no_provenance_or_they_disagree( tmp_path ):
    paths = pk.export_packets( [ need_item( 0 ), need_item( 1 ) ], [ "rick", "sam" ], 7, tmp_path, PROV )
    pk._write_provenance( paths[ "sam" ], { **PROV, "source_commit": "b" * 40 } )
    assert code_of( pk.export_subset_packet, tmp_path, [ "n-000" ], "third", 7 ) == er.PROVENANCE_MISSING
    pk._provenance_path( paths[ "sam" ] ).unlink()
    assert code_of( pk.export_subset_packet, tmp_path, [ "n-000" ], "third", 7 ) == er.PROVENANCE_MISSING
    assert not pk.packet_path( tmp_path, "third" ).exists()
