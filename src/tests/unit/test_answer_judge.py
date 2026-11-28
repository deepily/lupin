"""
Tests for the answer judge: booleans, quote check, identity and the request sent.

The model is stood in for by a query that builds its reply from the prompt it is given. It goes
through the real transport.
"""

import json
import re
import shutil

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

import cosa.utils.util as cu
from cosa.agents.prediction_engine import accuracy_comparators, answer_judge as aj


def reply_of( actual=(), predicted=() ):
    """Write a reply from ( atom, status, evidence ) triples."""
    rows = lambda items: [ { "atom": a, "status": s, "evidence": e } for a, s, e in items ]
    return json.dumps( { "actual_atoms": rows( actual ), "predicted_atoms": rows( predicted ) } )


def echo_query( seen ):
    """A model that reads both tagged texts: same words are covered, others are not."""
    async def query( prompt, options ):
        seen.append( ( prompt, options ) )
        texts     = { label: re.search( rf"<{label}_\w+>\n(.*?)\n</{label}_", prompt, re.S ).group( 1 ) for label in ( "actual", "predicted" ) }
        a, p      = texts[ "actual" ], texts[ "predicted" ]
        same      = a == p
        actual    = [] if a == aj.NO_TEXT else [ ( a, "covered" if same else "missing", p if same else None ) ]
        predicted = [] if p == aj.NO_TEXT else [ ( p, "supported" if same else "unsupported", a if same else None ) ]
        yield AssistantMessage( content=[ TextBlock( text="```json\n" + reply_of( actual, predicted ) + "\n```" ) ], model=options.model )
    return query


def test_booleans_come_from_every_atom_status():
    reply = reply_of( actual=[ ( "a", "covered", "x" ), ( "b", "missing", "ignored" ) ], predicted=[ ( "c", "supported", "A  B" ) ] )
    out   = aj.parse_verdict( reply, "x y", "a b" )
    assert out[ "keeps_every_restriction" ] is False and out[ "invents_nothing" ] is True
    assert out[ "actual_atoms" ][ 1 ][ "evidence" ] is None


@pytest.mark.parametrize( "status", [ "unsupported", "contradicted" ] )
def test_one_bad_predicted_atom_means_something_was_invented( status ):
    evidence = "a b" if status == "contradicted" else None
    out      = aj.parse_verdict( reply_of( actual=[ ( "a", "covered", "x" ) ], predicted=[ ( "c", status, evidence ) ] ), "x", "a b" )
    assert out[ "keeps_every_restriction" ] is True and out[ "invents_nothing" ] is False


@pytest.mark.parametrize( "reply, predicted, actual, words", [
    ( "no object here", "x", "a", "no JSON object" ),
    ( '{"actual_atoms": 1, "predicted_atoms": []}', "x", "a", "actual_atoms is not a list" ),
    ( reply_of(), "x", "a", "exactly when its text is not empty" ),
    ( reply_of( actual=[ ( "a", "missing", None ) ] ), "x", None, "exactly when its text is not empty" ),
    ( '{"actual_atoms": ["a"], "predicted_atoms": []}', "x", "a", "not an object" ),
    ( reply_of( actual=[ ( " ", "missing", None ) ] ), "x", "a", "no text" ),
    ( reply_of( actual=[ ( 3, "missing", None ) ] ), "x", "a", "no text" ),
    ( reply_of( actual=[ ( "a", "supported", "x" ) ] ), "x", "a", "unknown status" ),
    ( reply_of( actual=[ ( "a", "covered", None ) ] ), "x", "a", "does not quote" ),
    ( reply_of( actual=[ ( "a", "covered", "  " ) ] ), "x", "a", "does not quote" ),
    ( reply_of( actual=[ ( "a", "covered", "not there" ) ] ), "x", "a", "does not quote" ),
] )
def test_an_unreadable_reply_is_refused_and_kept( reply, predicted, actual, words ):
    with pytest.raises( aj.JudgeReplyError, match=words ) as caught:
        aj.parse_verdict( reply, predicted, actual )
    assert caught.value.raw_reply == reply


def test_the_prompt_shows_a_missing_text_as_none_inside_unforgeable_tags():
    prompt = aj.build_user_prompt( "  ", "only staging", "ab12" )
    assert prompt.index( "<actual_ab12>" ) < prompt.index( "<predicted_ab12>" )
    assert aj.NO_TEXT in prompt and "only staging" in prompt


def test_the_judge_sends_the_rubric_and_reads_the_request_it_sent():
    seen    = []
    judge   = aj.make_judge( "model-x", query_fn=echo_query( seen ) )
    verdict = judge( "only staging", "only staging" )
    assert verdict[ "keeps_every_restriction" ] and verdict[ "invents_nothing" ]
    prompt, options = seen[ 0 ]
    assert options.system_prompt == cu.get_file_as_string( cu.get_project_root() + aj.RUBRIC_PATH )
    assert options.tools == [] and options.model == "model-x"
    assert verdict[ "request_settings" ] == { "model": "model-x", "max_turns": 1, "tools": [], "permission_mode": "default", "sampling": {} }
    assert "temperature" not in { f for f in verdict[ "request_settings" ][ "sampling" ] }
    assert verdict[ "identity" ] == aj.judge_identity( "model-x" ) and verdict[ "raw_reply" ].startswith( "```json" )


def test_request_settings_reads_a_temperature_the_options_class_has():
    import dataclasses
    options = dataclasses.make_dataclass( "Options", [ "model", "max_turns", "tools", "permission_mode", "temperature" ] )( "m", 1, [], "default", 0 )
    assert aj.request_settings( options )[ "sampling" ] == { "temperature": 0 }


def test_the_model_is_read_from_the_ini_file():
    assert aj.judge_identity()[ "model" ] == aj.judge_model() == "claude-opus-5-5"


def test_two_empty_texts_pass_without_a_model_call():
    def never( *args, **kwargs ): raise AssertionError( "called" )
    verdict = aj.make_judge( complete=never )( None, "  " )
    assert verdict[ "keeps_every_restriction" ] and verdict[ "invents_nothing" ] and verdict[ "raw_reply" ] is None


def test_a_complete_that_sends_no_request_leaves_the_settings_empty():
    judge = aj.make_judge( complete=lambda model, system, user, query_fn=None: reply_of( predicted=[ ( "x", "unsupported", None ) ] ) )
    assert judge( "x", None )[ "request_settings" ] is None


def test_the_comparator_takes_the_judge_for_two_different_conditions():
    judge         = aj.make_judge( query_fn=echo_query( [] ) )
    match, detail = accuracy_comparators.compare_complete_action_open_ended( { "value": "on staging" }, { "value": "on production" }, judge=judge )
    assert match is False and detail[ "judge" ][ "keeps_every_restriction" ] is False


def test_changing_one_character_of_the_rubric_is_refused( tmp_path ):
    rubric = tmp_path / "rubric.txt"
    shutil.copy( cu.get_project_root() + aj.RUBRIC_PATH, rubric )
    recorded = aj.judge_identity( rubric_path=str( rubric ) )
    aj.make_judge( rubric_path=str( rubric ), expected_identity=recorded )
    rubric.write_text( rubric.read_text( encoding="utf-8" ).replace( "must", "Must", 1 ), encoding="utf-8" )
    with pytest.raises( aj.JudgeHashMismatch, match="rubric_sha256, prompt_sha256" ):
        aj.make_judge( rubric_path=str( rubric ), expected_identity=recorded )


def test_another_model_is_refused():
    with pytest.raises( aj.JudgeHashMismatch, match="in model$" ):
        aj.make_judge( "model-y", expected_identity=aj.judge_identity( "model-x" ) )


def test_smoke_test_prints_its_verdict( capsys ):
    aj.quick_smoke_test()
    assert "keeps=True invents_nothing=True" in capsys.readouterr().out
