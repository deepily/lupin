"""Tests for the judge validation draw: the split, blinding, reader files and write-once."""

import json

import pytest

from cosa.research.judge_validation import draw
from cosa.utils.file_hash import file_sha256


def pair( n, predicted="a", actual="b", kind="yes_no" ):
    """One pair carrying a secret arm the draw must not copy."""
    return { "pair_id": f"p{n:03d}", "notification_id": f"c-{n}", "response_type": kind, "field_key": "", "predicted_text": predicted,
             "actual_text": actual, "arm": "secret-arm", "literal_mismatch": ( predicted or "" ).strip().lower() != ( actual or "" ).strip().lower() }


def population():
    """100 differing and 40 equal yes/no pairs, and 5 multiple-choice pairs that all differ."""
    return ( [ pair( n ) for n in range( 100 ) ] + [ pair( n, "Same ", "same" ) for n in range( 100, 140 ) ]
             + [ pair( n, "x", None, "multiple_choice" ) for n in range( 140, 145 ) ] )


def cards_file( path ):
    """One row per card of the population, each carrying an account field the draw must not copy."""
    rows = [ { "notification_id": p[ "notification_id" ], "response_type": p[ "response_type" ], "message": "Go?", "abstract": "why",
               "options": None, "answer": "yes", "answered_by": "private@example.com" } for p in population() ]
    path.write_text( "".join( json.dumps( row ) + "\n" for row in rows ), encoding="utf-8" )
    return str( path )


@pytest.mark.parametrize( "predicted, actual, pattern", [
    ( "A ", "a", "same" ), ( None, None, "same" ), ( "a", "", "only_predicted" ), ( None, "a", "only_actual" ), ( "a", "b", "differ" ) ] )
def test_the_pattern_says_how_the_texts_differ( predicted, actual, pattern ):
    assert draw.pattern_of( pair( 1, predicted, actual ) ) == pattern


@pytest.mark.parametrize( "mismatched, matched, expected", [
    ( 100, 100, ( 40, 40 ) ), ( 10, 100, ( 10, 70 ) ), ( 100, 10, ( 70, 10 ) ), ( 3, 4, ( 3, 4 ) ) ] )
def test_each_side_takes_up_what_the_other_cannot_fill( mismatched, matched, expected ):
    assert draw.split( mismatched, matched, 80 ) == expected


def test_the_sample_is_blind_repeatable_and_carries_inclusion():
    pairs           = population()
    sample, receipt = draw.draw_sample( pairs, seed=7 )
    assert draw.draw_sample( list( reversed( pairs ) ), seed=7 )[ 0 ] == sample
    assert draw.draw_sample( pairs, seed=8 )[ 0 ] != sample
    assert all( set( row ) == set( draw.BLIND_FIELDS ) | { "stratum", "pattern", "inclusion" } for row in sample )
    assert "secret-arm" not in json.dumps( sample )
    assert receipt[ "strata" ][ "yes_no/mismatch" ] == { "population": 100, "drawn": 40, "inclusion": 0.4 }
    assert receipt[ "strata" ][ "yes_no/match" ] == { "population": 40, "drawn": 40, "inclusion": 1.0 }
    assert receipt[ "strata" ][ "multiple_choice/mismatch" ][ "drawn" ] == 5 and "multiple_choice/match" not in receipt[ "strata" ]
    assert receipt[ "drawn" ] == 85 and len( { row[ "pair_id" ] for row in sample } ) == 85
    assert [ row[ "pair_id" ] for row in sample ] != sorted( row[ "pair_id" ] for row in sample )


def test_a_side_given_no_places_draws_nothing():
    _, receipt = draw.draw_sample( population(), seed=1, per_type=20, mismatch_share=1.0 )
    assert receipt[ "strata" ][ "yes_no/match" ] == { "population": 40, "drawn": 0, "inclusion": 0.0 }


@pytest.mark.parametrize( "pairs, words", [ ( [], "no pairs" ), ( [ pair( 1 ), pair( 1 ) ], "more than once" ) ] )
def test_a_bad_pair_list_is_refused( pairs, words ):
    with pytest.raises( ValueError, match=words ):
        draw.draw_sample( pairs, seed=1 )


def written( tmp_path, pairs=None ):
    """Write the pairs file and return the command's arguments."""
    source = tmp_path / "pairs.jsonl"
    source.write_text( "".join( json.dumps( p ) + "\n" for p in ( pairs or population() ) ), encoding="utf-8" )
    return source, [ "--pairs", str( source ), "--cards", cards_file( tmp_path / "cards.jsonl" ), "--out-dir", str( tmp_path / "out" ), "--seed", "7" ]


def test_the_files_are_written_once_with_their_hashes_and_readers_see_no_arm( tmp_path, capsys ):
    source, args = written( tmp_path )
    out          = tmp_path / "out"
    assert draw.main( args ) == 0
    receipt = json.loads( ( out / draw.DRAW_FILE ).read_text() )
    assert receipt[ "pairs_sha256" ] == file_sha256( str( source ) ) and receipt[ "cards_sha256" ] == file_sha256( args[ 3 ] )
    assert receipt[ "files" ] == { name: file_sha256( str( out / name ) ) for name in ( draw.SAMPLE_FILE, draw.ANSWERS_FILE, draw.FORECASTS_FILE ) }
    answers   = [ json.loads( l ) for l in ( out / draw.ANSWERS_FILE ).read_text().splitlines() ]
    forecasts = [ json.loads( l ) for l in ( out / draw.FORECASTS_FILE ).read_text().splitlines() ]
    assert len( answers ) == 85 and len( forecasts ) == 85
    assert set( answers[ 0 ] ) == { "notification_id", "response_type", "message", "abstract", "options", "answer" }
    assert set( forecasts[ 0 ] ) == { "pair_id", "notification_id", "field_key", "predicted_text" }
    assert answers[ 0 ][ "answer" ] == "yes" and "private@example.com" not in json.dumps( answers )
    before = ( out / draw.SAMPLE_FILE ).read_bytes()
    assert draw.main( args ) == draw.EXIT_REFUSED
    assert "drawn once" in capsys.readouterr().err and ( out / draw.SAMPLE_FILE ).read_bytes() == before


def test_a_card_missing_from_the_cards_file_writes_nothing( tmp_path, capsys ):
    _, args = written( tmp_path, [ pair( 999 ) ] )
    assert draw.main( args ) == draw.EXIT_REFUSED
    assert "not in the cards file" in capsys.readouterr().err and not ( tmp_path / "out" ).exists()
