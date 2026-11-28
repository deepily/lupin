"""Tests for the minimal-pair runner: the set, what counts as a flip, and one run per judge."""

import json

import pytest

from cosa.agents.prediction_engine import answer_judge as aj
from cosa.research.judge_validation import flips, scoring

IDENTITY = { "model": "m", "rubric_sha256": "r", "prompt_sha256": "p" }


def make_pairs():
    """Four pairs of each kind."""
    return [ { "id": f"{kind}-{n}", "kind": kind, "actual_text": f"{kind} {n}", "matching_text": f"{kind} {n}", "altered_text": f"not {kind} {n}",
               "source_card": "extra" } for kind in flips.KINDS for n in range( flips.PER_KIND ) ]


def write_set( path, pairs ):
    path.write_text( json.dumps( { "pairs": pairs, "extra_cases": [ { "id": "ignored" } ] } ) )
    return path


def judge( predicted, actual ):
    """Pass equal texts, fail others."""
    return { "keeps_every_restriction": predicted == actual, "invents_nothing": True }


def test_a_full_set_is_read_without_the_extra_cases( tmp_path ):
    assert len( flips.read_pairs( write_set( tmp_path / "s.json", make_pairs() ) ) ) == 24


@pytest.mark.parametrize( "change, words", [
    ( lambda p: p[ 0 ].pop( "altered_text" ), "altered_text is missing" ),
    ( lambda p: p[ 0 ].update( actual_text=" " ), "actual_text is missing" ),
    ( lambda p: p[ 1 ].update( id=p[ 0 ][ "id" ] ), "more than once" ),
    ( lambda p: p[ 0 ].update( kind="must_may" ), "needs 4 pairs" ),
    ( lambda p: p.append( dict( p[ 0 ], id="x", kind="other" ) ), "needs 4 pairs" ),
] )
def test_a_malformed_set_is_refused( tmp_path, change, words ):
    pairs = make_pairs()
    change( pairs )
    with pytest.raises( ValueError, match=words ):
        flips.read_pairs( write_set( tmp_path / "s.json", pairs ) )


@pytest.mark.parametrize( "matching, altered, flipped", [ ( True, False, True ), ( True, True, False ), ( False, False, False ), ( False, True, False ) ] )
def test_only_pass_then_fail_is_a_flip( matching, altered, flipped ):
    answers = { "m": matching, "z": altered }
    row     = flips.run_pair( lambda p, a: { "keeps_every_restriction": answers[ p ], "invents_nothing": True },
                              { "id": "i", "kind": "k", "actual_text": "a", "matching_text": "m", "altered_text": "z" } )
    assert row[ "flipped" ] is flipped


def test_an_unreadable_reply_is_not_a_flip():
    def garbled( *args ): raise aj.JudgeReplyError( "unreadable", "?" )
    row = flips.run_pair( garbled, make_pairs()[ 0 ] )
    assert row[ "flipped" ] is False and row[ "error" ] == "unreadable"


def test_the_set_runs_once_per_judge( tmp_path ):
    source = write_set( tmp_path / "s.json", make_pairs() )
    calls  = []
    def counting( p, a ):
        calls.append( p )
        return judge( p, a )
    result = flips.run_set( source, tmp_path / "v", counting, IDENTITY )
    assert result[ "passed" ] is True and result[ "flipped" ] == 24 and len( calls ) == 48
    with pytest.raises( FileExistsError ):
        flips.run_set( source, tmp_path / "v", counting, IDENTITY )
    assert len( calls ) == 48
    assert flips.run_set( source, tmp_path / "v", counting, dict( IDENTITY, prompt_sha256="p2" ) )[ "passed" ]


def test_an_outage_releases_the_claim( tmp_path ):
    source = write_set( tmp_path / "s.json", make_pairs() )
    def down( *args ): raise RuntimeError( "outage" )
    with pytest.raises( RuntimeError ):
        flips.run_set( source, tmp_path / "v", down, IDENTITY )
    assert list( ( tmp_path / "v" ).iterdir() ) == []
    assert flips.run_set( source, tmp_path / "v", judge, IDENTITY )[ "passed" ]


def test_the_command_reports_the_misses_and_refuses_a_second_run( tmp_path, capsys ):
    source = write_set( tmp_path / "s.json", make_pairs() )
    maker  = lambda model, expected_identity: ( lambda p, a: judge( a, a ) if p.startswith( "not must_may 0" ) else judge( p, a ) )
    args   = [ "--pairs", str( source ), "--folder", str( tmp_path / "v" ) ]
    assert flips.main( args, make_judge=maker ) == flips.EXIT_FAILED
    assert "flipped 23 of 24; missed: ['must_may-0']" in capsys.readouterr().out
    assert scoring.read_identity( tmp_path / "v" ) == aj.judge_identity()
    assert flips.main( args, make_judge=maker ) == flips.EXIT_REFUSED
    clean = [ "--pairs", str( source ), "--folder", str( tmp_path / "w" ) ]
    assert flips.main( clean, make_judge=lambda model, expected_identity: judge ) == 0
