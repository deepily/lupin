"""
The labelled-set loader: it joins pairs and keys, maps linked_doc to design, and refuses the gate split.
"""

import json

import pytest

from cosa.repo.doc_lint import labelled_pairs


def write_set( tmp_path, pairs, keys, split="dev" ):
    base = tmp_path / split
    base.mkdir( exist_ok=True )
    ( base / "pairs.jsonl" ).write_text( "\n".join( json.dumps( p ) for p in pairs ) + "\n\n" )
    ( base / "keys.jsonl" ).write_text( "\n".join( json.dumps( k ) for k in keys ) + "\n" )
    return str( base / "pairs.jsonl" ), str( base / "keys.jsonl" )


PAIRS = [
    { "id": "p0", "old": "It never raises when parked. It returns none.", "new": "It returns none.", "linked_doc": "" },
    { "id": "p1", "old": "Returns the count. Raises on blank.", "new": "Returns the count.", "linked_doc": "Raises on blank." },
    { "id": "p2", "old": "Returns a list.", "new": "Gives back a list.", "linked_doc": "" },
]
KEYS = [
    { "id": "p0", "seeded_positive": True,  "x_span_in_old": "It never raises when parked." },
    { "id": "p1", "seeded_positive": False, "x_span_in_old": "Raises on blank." },
    { "id": "p2", "seeded_positive": False, "x_span_in_old": "" },
]


def test_linked_doc_becomes_design_and_an_empty_one_becomes_none( tmp_path ):
    loaded = labelled_pairs.load_pairs( *write_set( tmp_path, PAIRS, KEYS ) )
    assert [ p[ "design" ] for p in loaded ] == [ None, "Raises on blank.", None ]
    assert all( "linked_doc" not in p for p in loaded )


def test_only_a_seeded_positive_gets_a_span_located_in_the_old_text( tmp_path ):
    loaded = labelled_pairs.load_pairs( *write_set( tmp_path, PAIRS, KEYS ) )
    assert loaded[ 0 ][ "seed_span" ] == ( 0, len( "It never raises when parked." ) )
    assert loaded[ 0 ][ "old" ][ slice( *loaded[ 0 ][ "seed_span" ] ) ] == "It never raises when parked."
    assert loaded[ 1 ][ "seed_span" ] is None and loaded[ 2 ][ "seed_span" ] is None


def test_a_span_not_in_the_old_text_is_refused( tmp_path ):
    keys = [ dict( KEYS[ 0 ], x_span_in_old="not there" ) ] + KEYS[ 1: ]
    with pytest.raises( ValueError, match="p0.*not in the old text" ):
        labelled_pairs.load_pairs( *write_set( tmp_path, PAIRS, keys ) )


def test_ids_must_match_one_to_one( tmp_path ):
    with pytest.raises( ValueError, match="do not match" ):
        labelled_pairs.load_pairs( *write_set( tmp_path, PAIRS, KEYS[ :2 ] ) )


def test_file_order_is_kept( tmp_path ):
    loaded = labelled_pairs.load_pairs( *write_set( tmp_path, PAIRS, list( reversed( KEYS ) ) ) )
    assert [ p[ "id" ] for p in loaded ] == [ "p0", "p1", "p2" ]


@pytest.mark.parametrize( "path", [ "/data/labelled/gate/pairs.jsonl", "gate/pairs.jsonl", "/data/labelled/keys/gate-keys.jsonl", "gate-keys.jsonl" ] )
def test_a_path_naming_the_gate_split_is_refused( path ):
    with pytest.raises( ValueError, match="gate split" ):
        labelled_pairs.refuse_gate_path( path )


@pytest.mark.parametrize( "path", [ "/data/labelled/dev/pairs.jsonl", "/data/labelled/keys/dev-keys.jsonl", "/data/gated/pairs.jsonl", "/data/gate_notes/pairs.jsonl" ] )
def test_a_dev_path_and_look_alike_names_are_not_refused( path ):
    labelled_pairs.refuse_gate_path( path )


def test_the_loader_refuses_a_gate_path_before_opening_anything( tmp_path ):
    pairs, keys = write_set( tmp_path, PAIRS, KEYS, split="gate" )
    with pytest.raises( ValueError, match="gate split" ):
        labelled_pairs.load_pairs( pairs, keys )
    dev_pairs, dev_keys = write_set( tmp_path, PAIRS, KEYS, split="dev" )
    with pytest.raises( ValueError, match="gate split" ):
        labelled_pairs.load_pairs( dev_pairs, str( tmp_path / "gate-keys.jsonl" ) )
