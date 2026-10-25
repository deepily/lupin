"""
Unit tests for restoring an agent from a serialized JSON state file.

Twin refactor slice agent-restore-state: three agents carried the same restore body.
"""

import json

import pytest

from cosa.agents.receptionist_agent import ReceptionistAgent
from cosa.agents.todo_list_agent import TodoListAgent
from cosa.agents.iterative_debugging_agent import IterativeDebuggingAgent


@pytest.fixture( autouse=True )
def no_model_server( monkeypatch ):
    # ReceptionistAgent sizes its memory block from the model server's window and tokenizer while it is built
    monkeypatch.setattr( "cosa.agents.model_window.get_context_window", lambda base_url, model_name, timeout=20: 8192 )
    monkeypatch.setattr( "cosa.agents.model_window.count_tokens", lambda base_url, model_name, text, timeout=20: ( 10, 8192 ) )


def _write( tmp_path, data ):
    path = tmp_path / "state.json"
    path.write_text( json.dumps( data ) )
    return str( path )


QUESTION_STATE = { "question": "what is up", "debug": True, "verbose": False, "auto_debug": True, "inject_bugs": False, "extra_field": 5 }


@pytest.mark.parametrize( "cls", [ ReceptionistAgent, TodoListAgent ] )
def test_question_agents_rebuild_from_constructor_keys_and_copy_the_rest( cls, tmp_path, capsys ):
    agent = cls.restore_from_serialized_state( _write( tmp_path, QUESTION_STATE ) )
    out   = capsys.readouterr().out

    assert isinstance( agent, cls )
    assert agent.question == "what is up"
    assert ( agent.debug, agent.verbose, agent.auto_debug, agent.inject_bugs ) == ( True, False, True, False )
    assert agent.extra_field == 5
    assert out.startswith( f"Restoring from {tmp_path / 'state.json'}..." )
    for key in ( "question", "debug", "verbose", "auto_debug", "inject_bugs" ):
        assert f"Skipping key [{key}], it's already been set" in out
    assert "Skipping key [extra_field]" not in out


def test_attributes_beyond_the_constructor_keys_overwrite_what_the_constructor_set( tmp_path ):
    agent = TodoListAgent.restore_from_serialized_state( _write( tmp_path, { **QUESTION_STATE, "push_counter": 41 } ) )
    assert agent.push_counter == 41


def test_a_missing_constructor_key_raises_keyerror( tmp_path ):
    state = { k: v for k, v in QUESTION_STATE.items() if k != "inject_bugs" }
    with pytest.raises( KeyError, match = "inject_bugs" ):
        ReceptionistAgent.restore_from_serialized_state( _write( tmp_path, state ) )


def test_iterative_debugging_agent_uses_its_own_constructor_keys( tmp_path, capsys ):
    # path_to_code is relative to the project root and must exist there; a tracked file stands in
    code  = "/CLAUDE.md"
    state = { "error_message": "ZeroDivisionError", "path_to_code": code, "debug": True, "verbose": True, "extra_field": 7 }

    agent = IterativeDebuggingAgent.restore_from_serialized_state( _write( tmp_path, state ) )
    out   = capsys.readouterr().out

    assert isinstance( agent, IterativeDebuggingAgent )
    assert agent.error_message == "ZeroDivisionError"
    assert agent.path_to_code == code
    assert ( agent.debug, agent.verbose ) == ( True, True )
    assert agent.extra_field == 7
    for key in ( "error_message", "path_to_code", "debug", "verbose" ):
        assert f"Skipping key [{key}], it's already been set" in out
    assert "Skipping key [extra_field]" not in out


class TestRestoreFromData:
    """The shared helper, with a stand-in class that records how it was built."""

    class _Fake:
        def __init__( self, *args, **kwargs ):
            self.args   = args
            self.kwargs = kwargs
            self.shadow = "from-ctor"

    def test_positional_keys_in_order_then_keyword_keys( self ):
        from cosa.agents.agent_base import AgentBase
        data = { "b": 2, "a": 1, "x": 10, "y": 20, "extra": 3 }
        obj  = AgentBase._restore_from_data( self._Fake, data, ( "a", "b" ), ( "x", "y" ) )
        assert obj.args   == ( 1, 2 )
        assert obj.kwargs == { "x": 10, "y": 20 }
        assert obj.extra  == 3

    def test_constructor_keys_are_not_set_again_and_are_reported( self, capsys ):
        from cosa.agents.agent_base import AgentBase
        AgentBase._restore_from_data( self._Fake, { "a": 1, "x": 2, "shadow": "from-file" }, ( "a", ), ( "x", ) )
        out = capsys.readouterr().out
        assert out == "Skipping key [a], it's already been set\nSkipping key [x], it's already been set\n"

    def test_other_keys_overwrite_what_the_constructor_set( self ):
        from cosa.agents.agent_base import AgentBase
        obj = AgentBase._restore_from_data( self._Fake, { "a": 1, "shadow": "from-file" }, ( "a", ), () )
        assert obj.shadow == "from-file"

    def test_missing_constructor_key_raises_keyerror( self ):
        from cosa.agents.agent_base import AgentBase
        with pytest.raises( KeyError, match = "'x'" ):
            AgentBase._restore_from_data( self._Fake, { "a": 1 }, ( "a", ), ( "x", ) )
