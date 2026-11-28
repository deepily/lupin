"""Tests for settling the truth labels from two readers and Rick's export."""

import json

import pytest

from cosa.research.judge_validation import labels

IDS     = [ "agree", "dispute", "blind", "settled", "unsure" ]
READERS = { "one": { "agree": True, "dispute": True, "blind": True, "settled": True, "unsure": False },
            "two": { "agree": True, "dispute": False, "blind": True, "settled": False, "unsure": False } }


def line( pair_id, section, answer, ts="2026-11-27T10:00:00Z" ):
    return { "pair_id": pair_id, "section": section, "material_error": answer, "ts": ts }


EXPORT = [ line( "blind", "A", "no" ), line( "settled", "A", "yes" ), line( "settled", "B", "yes", "2026-11-27T09:00:00Z" ),
           line( "settled", "B", "no", "2026-11-27T11:00:00Z" ), line( "unsure", "A", "cant_tell" ) ]


def write( tmp_path, export=EXPORT, readers=READERS, ids=IDS ):
    """Lay out a sample, two readers and an export, and return the command's arguments."""
    ( tmp_path / "sample.jsonl" ).write_text( "".join( json.dumps( { "pair_id": i } ) + "\n" for i in ids ) )
    args = [ "--sample", str( tmp_path / "sample.jsonl" ), "--rick", str( tmp_path / "rick.json" ), "--out", str( tmp_path / "labels.jsonl" ) ]
    for name, held in readers.items():
        ( tmp_path / f"{name}.jsonl" ).write_text( "".join( json.dumps( { "pair_id": i, "material_error": v } ) + "\n" for i, v in held.items() ) )
        args += [ "--reader", f"{name}={tmp_path / name}.jsonl" ]
    ( tmp_path / "rick.json" ).write_text( json.dumps( export ) )
    return args


def test_rick_decides_then_agreement_and_only_blind_answers_count_as_his_reading( tmp_path, capsys ):
    args = write( tmp_path )
    assert labels.main( args ) == 0
    rows = { r[ "pair_id" ]: r for r in map( json.loads, ( tmp_path / "labels.jsonl" ).read_text().splitlines() ) }
    assert { i: ( rows[ i ][ "material_error" ], rows[ i ][ "settled_by" ] ) for i in IDS } == {
        "agree": ( True, "readers_agreed" ), "dispute": ( None, "unresolved" ), "blind": ( False, "rick_blind" ),
        "settled": ( False, "rick_dispute" ), "unsure": ( None, "unresolved" ) }
    assert rows[ "blind" ][ "readers" ] == { "one": True, "two": True, "rick": False }
    assert rows[ "settled" ][ "readers" ][ "rick" ] is True and "rick" not in rows[ "unsure" ][ "readers" ]
    assert '"unresolved": 2' in capsys.readouterr().out
    before = ( tmp_path / "labels.jsonl" ).read_bytes()
    assert labels.main( args ) == labels.EXIT_REFUSED and ( tmp_path / "labels.jsonl" ).read_bytes() == before


@pytest.mark.parametrize( "change, words", [
    ( dict( export=[ line( "other", "A", "no" ) ] ), "not in the sample" ),
    ( dict( export=[ line( "agree", "C", "no" ) ] ), "unknown section or answer" ),
    ( dict( export=[ line( "agree", "A", True ) ] ), "unknown section or answer" ),
    ( dict( readers={ "one": READERS[ "one" ] } ), "two readers are needed" ),
    ( dict( readers={ "one": READERS[ "one" ], "rick": READERS[ "two" ] } ), "two readers are needed" ),
    ( dict( readers={ "one": READERS[ "one" ], "two": dict( READERS[ "two" ], agree="no" ) } ), "not true or false" ),
    ( dict( readers={ "one": READERS[ "one" ], "two": { "agree": True } } ), "differ on 4 ids" ),
] )
def test_a_bad_input_writes_nothing( tmp_path, capsys, change, words ):
    assert labels.main( write( tmp_path, **change ) ) == labels.EXIT_REFUSED
    assert words in capsys.readouterr().err and not ( tmp_path / "labels.jsonl" ).exists()


def test_a_reader_who_labels_a_pair_twice_is_refused( tmp_path ):
    path = tmp_path / "r.jsonl"
    path.write_text( ( json.dumps( { "pair_id": "a", "material_error": True } ) + "\n" ) * 2 )
    with pytest.raises( ValueError, match="labelled twice" ):
        labels.read_reader_labels( path, [ "a" ] )
