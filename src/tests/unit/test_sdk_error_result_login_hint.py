#!/usr/bin/env python3
"""
Tests for the sentence a job adds when its Claude login has expired.

The fixture is the stored error of a podcast job that met the expired login on the dev server.
The sentence is added in raise_error_result and never in error_result_text.
The in-process writer also calls error_result_text, possibly on the host, where "this server's container" is false.
"""

import os
from types import SimpleNamespace

import pytest

import cosa.utils.util as cu
from cosa.agents.shared import sdk_error_result as ser

FIXTURE = os.path.join( cu.get_project_root(), "src/tests/unit/fixtures/job_history_pg_10774ba0_error.txt" )
WRAPPER = "Podcast generation failed while analyzing the research document: "
CLI_TEXT = "Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."


def _stored_error():
    with open( FIXTURE, encoding="utf-8" ) as f: return f.read().strip()


def _login_message():
    return SimpleNamespace( subtype="success", result=CLI_TEXT, errors=None, is_error=True )


class _Log:
    def __init__( self ): self.lines = []
    def error( self, line ): self.lines.append( line )


def test_the_fixture_is_the_stored_error_and_the_message_shape_reproduces_its_inner_text():
    stored = _stored_error()
    assert stored.startswith( WRAPPER ) and CLI_TEXT in stored
    assert ser.error_result_text( _login_message() ) == stored[ len( WRAPPER ): ]


def test_error_result_text_never_carries_the_login_sentence():
    assert "claude /login" not in ser.error_result_text( _login_message() )


def test_raise_error_result_appends_the_login_sentence_on_the_401_line_and_logs_it():
    log = _Log()
    with pytest.raises( RuntimeError ) as raised:
        ser.raise_error_result( _login_message(), "PodcastAPIClient script", log )
    text = str( raised.value )
    assert text.startswith( _stored_error()[ len( WRAPPER ): ] )
    assert "docker exec -it lupin-rest-dev claude /login" in text and "lupin-rest-test" in text
    assert log.lines == [ "[PodcastAPIClient script] " + text ]


def test_raise_error_result_leaves_other_errors_exactly_as_they_were():
    message = SimpleNamespace( subtype="success", result="Your credit balance is too low", errors=None, is_error=True )
    with pytest.raises( RuntimeError ) as raised:
        ser.raise_error_result( message, "x", _Log() )
    assert str( raised.value ) == "Claude Code returned an error result: success: Your credit balance is too low"


def test_error_result_text_with_no_result_and_an_errors_list_keeps_its_form():
    message = SimpleNamespace( subtype="error_max_turns", result=None, errors=[ "ran out", "disk full" ], is_error=True )
    assert ser.error_result_text( message ) == "Claude Code returned an error result: error_max_turns: no text (errors: ran out; disk full)"


def test_login_hint_matches_only_the_401_marker():
    assert ser.login_hint( "x API Error: 401 y" ) == "x API Error: 401 y" + ser.LOGIN_HINT
    assert ser.login_hint( "API Error: 500 overloaded" ) == "API Error: 500 overloaded"


def test_only_the_dispatcher_and_the_in_process_writer_call_error_result_text_directly():
    root     = os.path.join( cu.get_project_root(), "src/cosa" )
    direct   = set()
    raisers  = set()
    for here, dirs, files in os.walk( root ):
        dirs[ : ] = [ d for d in dirs if d not in ( ".venv", "node_modules", "site-packages", "__pycache__", "tests" ) ]
        for name in files:
            if not name.endswith( ".py" ): continue
            path = os.path.join( here, name )
            text = open( path, encoding="utf-8" ).read()
            rel  = os.path.relpath( path, root )
            if "error_result_text(" in text and not rel.endswith( "shared/sdk_error_result.py" ): direct.add( rel )
            if "raise_error_result(" in text and not rel.endswith( "shared/sdk_error_result.py" ): raisers.add( rel )
    assert raisers, "the sweep found no raise_error_result caller: the walk is broken"
    assert direct == { "orchestration/claude_code/dispatcher.py", "repo/symindex/need_writer.py" }, direct
