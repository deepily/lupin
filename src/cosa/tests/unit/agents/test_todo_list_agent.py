"""
Unit tests for cosa.agents.todo_list_agent.TodoListAgent.

TodoListAgent is an AgentBase subclass. These tests stub AgentBase.__init__ with a
lightweight seeder (small real pandas DataFrame + format-able prompt template + a
config mock for the serialize flags), and mock the parent run_prompt/run_code +
serialize_to_json so the subclass's own logic runs in isolation:

- __init__                      — super delegation, prompt build, XML tags, serialize flags
- _get_prompt / _get_df_metadata— template formatting + (columns, list_names, CSV sample)
- run_prompt / run_code         — parent delegation + conditional JSON serialization
- restore_from_serialized_state — JSON load → reconstruct → set/skip attributes

No real AgentBase init, config, LLM, code-exec, or file I/O.

Created 2026-05-31 (CoSA coverage campaign, user-facing agents lane — Tiffany 💍). New file.
"""

import json
import unittest
from unittest.mock import Mock, patch, mock_open

import pandas as pd

from cosa.agents.todo_list_agent import TodoListAgent
from cosa.agents.agent_base import AgentBase


def _seed_df():
    """Return a small todo-list DataFrame with the required list_name column."""
    return pd.DataFrame( {
        "list_name" : [ "work", "home", "work", "home" ],
        "task"      : [ "standup", "dishes", "review", "laundry" ],
        "done"      : [ False, True, False, True ],
    } )


def _fake_agent_base_init( serialize_prompt=False, serialize_code=False ):
    """
    Build an AgentBase.__init__ stub that seeds the attributes TodoListAgent needs.

    Returns the stub function; the serialize flags steer the config mock the subclass
    reads in its own __init__.
    """
    def fake_init( self_inner, *args, **kwargs ):
        self_inner.df                  = _seed_df()
        self_inner.prompt_template     = "Q={question}|C={column_names}|L={list_names}|H={head}"
        self_inner.last_question_asked = kwargs.get( "last_question_asked", "" )
        self_inner.debug               = kwargs.get( "debug", False )
        self_inner.verbose             = kwargs.get( "verbose", False )

        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "agent todo list serialize prompt to json" : serialize_prompt,
            "agent todo list serialize code to json"   : serialize_code,
        }.get( key, default )
        self_inner.config_mgr = cfg

    return fake_init


class TestTodoListAgent( unittest.TestCase ):
    """
    Comprehensive unit tests for TodoListAgent.

    Ensures:
        - Construction builds the prompt + tags + serialize flags
        - Metadata extraction reflects the DataFrame
        - run_prompt/run_code delegate and conditionally serialize
        - restore_from_serialized_state rebuilds an instance from JSON
    """

    def _make_agent( self, serialize_prompt=False, serialize_code=False, question="what is on my list?" ):
        """Construct a TodoListAgent with AgentBase.__init__ stubbed."""
        with patch.object( AgentBase, "__init__", _fake_agent_base_init( serialize_prompt, serialize_code ) ):
            agent = TodoListAgent( question=question, last_question_asked=question )
        return agent

    def test_init_builds_prompt_tags_and_flags( self ):
        """
        Test construction wires the prompt, XML tags, and serialize flags.

        Ensures:
            - The prompt embeds question + columns + list names + CSV head
            - xml_response_tag_names matches the todo contract
            - serialize flags reflect config (both False here)
        """
        agent = self._make_agent( question="what is due today?" )

        self.assertIn( "what is due today?", agent.prompt )
        self.assertIn( "list_name", agent.prompt )
        self.assertIn( "work", agent.prompt )
        self.assertEqual(
            agent.xml_response_tag_names,
            [ "thoughts", "code", "example", "returns", "explanation" ]
        )
        self.assertFalse( agent.serialize_prompt_to_json )
        self.assertFalse( agent.serialize_code_to_json )

    def test_get_df_metadata_returns_columns_lists_and_csv( self ):
        """
        Test _get_df_metadata returns columns, unique list names, and a CSV sample.

        Ensures:
            - column_names lists every DataFrame column
            - list_names are de-duplicated from list_name
            - The head sample is CSV (contains a comma-joined header)
        """
        agent = self._make_agent()

        column_names, list_names, head = agent._get_df_metadata()

        self.assertEqual( column_names, [ "list_name", "task", "done" ] )
        self.assertCountEqual( list_names, [ "work", "home" ] )
        self.assertIn( "list_name,task,done", head )

    def test_run_prompt_without_serialize( self ):
        """
        Test run_prompt delegates to the parent and skips serialization when disabled.

        Ensures:
            - The parent result is returned
            - serialize_to_json is NOT called
        """
        agent = self._make_agent( serialize_prompt=False )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_prompt", return_value={ "ok": 1 } ) as parent:
            result = agent.run_prompt()

        self.assertEqual( result, { "ok": 1 } )
        parent.assert_called_once()
        agent.serialize_to_json.assert_not_called()

    def test_run_prompt_with_serialize( self ):
        """
        Test run_prompt serializes the prompt when the flag is enabled.

        Ensures:
            - serialize_to_json is called with 'prompt'
        """
        agent = self._make_agent( serialize_prompt=True )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_prompt", return_value={ "ok": 1 } ):
            agent.run_prompt()

        agent.serialize_to_json.assert_called_once_with( "prompt" )

    def test_run_code_without_serialize( self ):
        """
        Test run_code delegates to the parent and skips serialization when disabled.

        Ensures:
            - The parent result is returned; serialize_to_json NOT called
        """
        agent = self._make_agent( serialize_code=False )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_code", return_value={ "return_code": 0 } ) as parent:
            result = agent.run_code( auto_debug=True, inject_bugs=False )

        self.assertEqual( result, { "return_code": 0 } )
        parent.assert_called_once()
        agent.serialize_to_json.assert_not_called()

    def test_run_code_with_serialize( self ):
        """
        Test run_code serializes the code when the flag is enabled.

        Ensures:
            - serialize_to_json is called with 'code'
        """
        agent = self._make_agent( serialize_code=True )
        agent.serialize_to_json = Mock()

        with patch.object( AgentBase, "run_code", return_value={ "return_code": 0 } ):
            agent.run_code()

        agent.serialize_to_json.assert_called_once_with( "code" )

    def test_restore_from_serialized_state_rebuilds_instance( self ):
        """
        Test restore_from_serialized_state reconstructs an agent and applies extra attrs.

        Ensures:
            - JSON is loaded; constructor params consumed; extra keys set via setattr
            - The known constructor keys are skipped (not re-applied)
        """
        data = {
            "question"    : "restored question",
            "debug"       : False,
            "verbose"     : False,
            "auto_debug"  : False,
            "inject_bugs" : False,
            "answer"      : "the answer is 42",
            "prompt"      : "restored prompt body",
        }

        with patch.object( AgentBase, "__init__", _fake_agent_base_init() ), \
             patch( "cosa.agents.todo_list_agent.open", mock_open(), create=True ), \
             patch( "cosa.agents.todo_list_agent.json.load", return_value=data ):
            restored = TodoListAgent.restore_from_serialized_state( "/tmp/todo_state.json" )

        self.assertIsInstance( restored, TodoListAgent )
        self.assertEqual( restored.answer, "the answer is 42" )           # set via setattr
        self.assertEqual( restored.prompt, "restored prompt body" )       # overwrote __init__ prompt


if __name__ == "__main__":
    unittest.main()
