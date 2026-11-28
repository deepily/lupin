"""Tests for the validation draw: the population, blinding, reader files and write-once."""

import json

import pytest

from cosa.research.judge_validation import draw
from cosa.utils.file_hash import file_sha256


def pair( n, predicted="a", actual="b", kind="yes_no", **extra ):
    """One pair; its texts decide the mismatch flag."""
    row = { "pair_id": f"p{n:03d}", "notification_id": f"c-{n}", "response_type": kind, "field_key": "", "predicted_text": predicted,
            "actual_text": actual, "arm": "secret-arm", "literal_mismatch": ( predicted or "" ).strip().lower() != ( actual or "" ).strip().lower() }
    row.update( extra )
    return row


def population():
    """100 yes/no and 5 multiple-choice pairs, all ones the judge would be asked about."""
    return [ pair( n ) for n in range( 100 ) ] + [ pair( n, "x", "y", "multiple_choice", option_mismatch=False ) for n in range( 100, 105 ) ]


def key_of( pairs, arm="answer_history" ):
    return { p[ "pair_id" ]: { "arm": arm, "model": "haiku" } for p in pairs }


def cards_file( path, pairs ):
    """One row per card, each carrying an account field the draw must not copy."""
    rows = [ { "notification_id": p[ "notification_id" ], "response_type": p[ "response_type" ], "message": "Go?", "abstract": "why",
               "options": None, "answer": "yes", "answered_by": "private@example.com" } for p in pairs ]
    path.write_text( "".join( json.dumps( row ) + "\n" for row in rows ), encoding="utf-8" )
    return str( path )


@pytest.mark.parametrize( "predicted, actual, pattern", [
    ( "A ", "a", "same" ), ( None, None, "same" ), ( "a", "", "only_predicted" ), ( None, "a", "only_actual" ), ( "a", "b", "differ" ) ] )
def test_the_pattern_says_how_the_texts_differ( predicted, actual, pattern ):
    assert draw.pattern_of( pair( 1, predicted, actual ) ) == pattern


@pytest.mark.parametrize( "row, arm, answer, reason", [
    ( pair( 1 ), "answer_history", "yes", None ),
    ( pair( 1 ), "B1-full", "yes", None ),
    ( pair( 1 ), "B1", "yes", "arm" ),
    ( pair( 1 ), "B1-opus", "yes", "arm" ),
    ( pair( 1, kind="open_ended" ), "C0", "text", None ),
    ( pair( 1, kind="open_ended_batch" ), "C0-full", "text", "arm" ),
    ( pair( 1 ), "answer_history", " [cancelled] ", "cancelled_or_empty" ),
    ( pair( 1 ), "answer_history", "  ", "cancelled_or_empty" ),
    ( pair( 1, "a", "[cancelled]" ), "answer_history", "yes", "cancelled_or_empty" ),
    ( pair( 1, "a", None, "open_ended" ), "answer_history", "text", "cancelled_or_empty" ),
    ( pair( 1, "a", None ), "answer_history", "yes", None ),
    ( pair( 1, "b", "B " ), "answer_history", "yes", "not_judged" ),
    ( pair( 1, kind="multiple_choice", option_mismatch=True ), "answer_history", "x", "not_judged" ),
    ( pair( 1, kind="multiple_choice", option_mismatch=False ), "answer_history", "x", None ),
] )
def test_only_pairs_the_judge_would_be_asked_about_are_in_the_population( row, arm, answer, reason ):
    assert draw.exclusion_of( row, arm, answer ) == reason


def test_eligible_counts_what_it_drops_and_adds_nothing_from_the_key():
    pairs = [ pair( 1 ), pair( 2, "b", "b" ) ]
    cards = { p[ "notification_id" ]: { "answer": "yes" } for p in pairs }
    kept, dropped = draw.eligible( pairs, key_of( pairs ), cards )
    assert kept == [ pairs[ 0 ] ] and dropped == { "arm": 0, "cancelled_or_empty": 0, "not_judged": 1 }
    with pytest.raises( ValueError, match="has no key" ):
        draw.eligible( pairs, {}, cards )
    unflagged = [ pair( 3, kind="multiple_choice" ) ]
    with pytest.raises( ValueError, match="option_mismatch" ):
        draw.eligible( unflagged, key_of( unflagged ), { "c-3": { "answer": "x" } } )


def test_the_sample_is_uniform_per_type_blind_and_repeatable():
    pairs           = population()
    sample, receipt = draw.draw_sample( pairs, seed=7 )
    assert draw.draw_sample( list( reversed( pairs ) ), seed=7 )[ 0 ] == sample
    assert draw.draw_sample( pairs, seed=8 )[ 0 ] != sample
    assert all( set( row ) == set( draw.BLIND_FIELDS ) | { "stratum", "pattern", "inclusion" } for row in sample )
    assert "secret-arm" not in json.dumps( sample )
    assert receipt[ "strata" ] == { "multiple_choice": { "population": 5, "drawn": 5, "inclusion": 1.0 },
                                    "yes_no": { "population": 100, "drawn": 80, "inclusion": 0.8 } }
    assert receipt[ "drawn" ] == 85 and len( { row[ "pair_id" ] for row in sample } ) == 85
    assert [ row[ "pair_id" ] for row in sample ] != sorted( row[ "pair_id" ] for row in sample )


@pytest.mark.parametrize( "pairs, words", [ ( [], "no pairs" ), ( [ pair( 1 ), pair( 1 ) ], "more than once" ) ] )
def test_a_bad_pair_list_is_refused( pairs, words ):
    with pytest.raises( ValueError, match=words ):
        draw.draw_sample( pairs, seed=1 )


def written( tmp_path, pairs=None, cards=None ):
    """Write the pairs, key and cards files and return them with the command's arguments."""
    pairs  = pairs or population()
    source = tmp_path / "pairs.jsonl"
    source.write_text( "".join( json.dumps( p ) + "\n" for p in pairs ), encoding="utf-8" )
    ( tmp_path / "key.json" ).write_text( json.dumps( key_of( pairs ) ) )
    held = cards_file( tmp_path / "cards.jsonl", pairs if cards is None else cards )
    return source, [ "--pairs", str( source ), "--key", str( tmp_path / "key.json" ), "--cards", held, "--out-dir", str( tmp_path / "out" ), "--seed", "7" ]


def test_the_files_are_written_once_with_their_hashes_and_readers_see_no_arm( tmp_path, capsys ):
    source, args = written( tmp_path )
    out          = tmp_path / "out"
    assert draw.main( args ) == 0
    receipt = json.loads( ( out / draw.DRAW_FILE ).read_text() )
    assert receipt[ "pairs_sha256" ] == file_sha256( str( source ) ) and receipt[ "key_sha256" ] == file_sha256( args[ 3 ] )
    assert receipt[ "cards_sha256" ] == file_sha256( args[ 5 ] ) and receipt[ "dropped" ][ "not_judged" ] == 0
    assert receipt[ "files" ] == { name: file_sha256( str( out / name ) ) for name in ( draw.SAMPLE_FILE, draw.ANSWERS_FILE, draw.FORECASTS_FILE ) }
    answers   = [ json.loads( l ) for l in ( out / draw.ANSWERS_FILE ).read_text().splitlines() ]
    forecasts = [ json.loads( l ) for l in ( out / draw.FORECASTS_FILE ).read_text().splitlines() ]
    assert len( answers ) == 85 and len( forecasts ) == 85
    assert { r[ "pair_id" ] for r in answers } == { r[ "pair_id" ] for r in forecasts } and "predicted_text" not in json.dumps( answers )
    assert set( answers[ 0 ] ) == { "pair_id", "notification_id", "field_key", "actual_text", "response_type", "message", "abstract", "options", "answer" }
    assert set( forecasts[ 0 ] ) == { "pair_id", "notification_id", "field_key", "predicted_text" }
    assert answers[ 0 ][ "answer" ] == "yes" and "private@example.com" not in json.dumps( answers )
    assert "answer_history" not in json.dumps( answers + forecasts ) + ( out / draw.SAMPLE_FILE ).read_text()
    before = ( out / draw.SAMPLE_FILE ).read_bytes()
    assert draw.main( args ) == draw.EXIT_REFUSED
    assert "drawn once" in capsys.readouterr().err and ( out / draw.SAMPLE_FILE ).read_bytes() == before


def test_a_card_missing_from_the_cards_file_writes_nothing( tmp_path, capsys ):
    _, args = written( tmp_path, [ pair( 999 ) ], cards=[] )
    assert draw.main( args ) == draw.EXIT_REFUSED
    assert "not in the cards file" in capsys.readouterr().err and not ( tmp_path / "out" ).exists()
