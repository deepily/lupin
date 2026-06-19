"""
Unit tests for cosa.crud_for_dataframes.agent.CrudForDataFramesAgent.

CrudForDataFramesAgent is an AgentBase subclass that wires the COSA voice
pipeline to Phase-1 CRUD operations. These tests stub the heavy
AgentBase.__init__ (config / prompt-template / LLM boundary) with a lightweight
seeder and patch DataFrameStorage so construction is hermetic. Every overridden
method is then driven directly:

- __init__              — builds the prompt from the template + list metadata
- run_prompt            — LLM call → <intent> carve-out → CRUDIntent (raw on/off)
- run_code              — confirm-gate, dispatch success, and the full Claude
                          Code fallback matrix (fallback ok / None / error / raise)
- run_formatter         — cancelled passthrough + normal voice formatting
- _confirm_destructive_operation — yes / no / timeout / error / None responses
- _format_lists_for_prompt — empty + populated metadata
- restore_from_serialized_state — always NotImplementedError

No real AgentBase init, config, LLM, parquet, or notification I/O.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from cosa.agents.agent_base import AgentBase, CodeGenerationFailedException
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.crud_for_dataframes.xml_models import CRUDIntent


def _make_agent( metadata=None, debug=False ):
    """
    Construct a CrudForDataFramesAgent with AgentBase.__init__ stubbed.

    Requires:
        - metadata is None or a list of list-metadata dicts

    Ensures:
        - Returns ( agent, mock_storage ); agent.storage is the mock
        - The seeded prompt_template exposes {query} and {available_lists}
    """
    mock_storage = MagicMock()
    mock_storage.get_all_lists_metadata.return_value = metadata if metadata is not None else []

    def fake_init( self_inner, *args, **kwargs ):
        self_inner.config_mgr          = MagicMock()
        self_inner.prompt_template     = "Q={query}|LISTS={available_lists}"
        self_inner.last_question_asked = kwargs.get( "last_question_asked", "" )
        self_inner.model_name          = "fake-model"
        self_inner.user_email          = kwargs.get( "user_email", "test@example.com" )
        self_inner.debug               = kwargs.get( "debug", False )
        self_inner.verbose             = kwargs.get( "verbose", False )

    with patch.object( AgentBase, "__init__", fake_init ), \
         patch( "cosa.crud_for_dataframes.agent.DataFrameStorage", return_value=mock_storage ):
        agent = CrudForDataFramesAgent(
            last_question_asked = "add buy milk to groceries",
            user_email          = "test@example.com",
            debug               = debug,
        )
    return agent, mock_storage


class TestConstruction( unittest.TestCase ):
    """
    __init__ — prompt assembly + initial state.
    """

    def test_prompt_embeds_query_and_empty_lists( self ):
        """Ensures the prompt embeds the query and the no-lists placeholder."""
        agent, _ = _make_agent( metadata=[], debug=True )
        self.assertIn( "add buy milk to groceries", agent.prompt )
        self.assertIn( "(no lists yet)", agent.prompt )
        self.assertIsNone( agent.crud_intent )

    def test_prompt_embeds_populated_lists( self ):
        """Ensures populated list metadata is formatted into the prompt."""
        agent, _ = _make_agent( metadata=[
            { "schema_type": "todo", "list_name": "groceries", "row_count": 3 },
        ] )
        self.assertIn( "groceries", agent.prompt )
        self.assertIn( "3 items", agent.prompt )


class TestFormatListsForPrompt( unittest.TestCase ):
    """
    _format_lists_for_prompt — empty + populated.
    """

    def test_empty_metadata( self ):
        """Ensures empty metadata renders the no-lists placeholder."""
        self.assertEqual( CrudForDataFramesAgent._format_lists_for_prompt( None, [] ), "(no lists yet)" )

    def test_populated_metadata( self ):
        """Ensures each list renders a name/schema/count bullet line."""
        out = CrudForDataFramesAgent._format_lists_for_prompt( None, [
            { "schema_type": "todo",     "list_name": "groceries", "row_count": 3 },
            { "schema_type": "calendar", "list_name": "meetings",  "row_count": 5 },
        ] )
        self.assertIn( "groceries", out )
        self.assertIn( "meetings", out )
        self.assertIn( "3 items", out )


class TestRunPrompt( unittest.TestCase ):
    """
    run_prompt — LLM response → CRUDIntent + protocol dict.
    """

    _XML = "<intent><operation>add</operation><target_list>groceries</target_list><schema_type>todo</schema_type><confidence>0.9</confidence></intent>"

    def _run( self, include_raw ):
        agent, _ = _make_agent()
        llm      = MagicMock()
        llm.run.return_value = self._XML
        factory  = MagicMock()
        factory.get_client.return_value = llm
        with patch( "cosa.crud_for_dataframes.agent.LlmClientFactory", return_value=factory ):
            result = agent.run_prompt( include_raw_response=include_raw )
        return agent, result

    def test_parses_intent_and_sets_protocol_dict( self ):
        """Ensures run_prompt parses the intent and fills prompt_response_dict."""
        agent, result = self._run( include_raw=False )
        self.assertEqual( agent.crud_intent.operation, "add" )
        self.assertEqual( result[ "operation" ], "add" )
        self.assertEqual( result[ "target_list" ], "groceries" )
        self.assertIsNone( result[ "raw_response" ] )

    def test_include_raw_response( self ):
        """Ensures include_raw_response=True attaches the raw LLM text."""
        _, result = self._run( include_raw=True )
        self.assertIn( "<intent>", result[ "raw_response" ] )


class TestRunCode( unittest.TestCase ):
    """
    run_code — confirm gate + dispatch + Claude Code fallback matrix.
    """

    def _agent_with_intent( self, intent ):
        agent, _ = _make_agent()
        agent.crud_intent = intent
        return agent

    def test_non_destructive_dispatch_success( self ):
        """Ensures a non-destructive op dispatches and stores an ok result."""
        agent = self._agent_with_intent( CRUDIntent( operation="add", target_list="g", schema_type="todo" ) )
        with patch( "cosa.crud_for_dataframes.agent.dispatch", return_value={ "status": "added", "message": "ok" } ):
            result = agent.run_code()
        self.assertEqual( result[ "return_code" ], 0 )
        self.assertEqual( result[ "output" ][ "status" ], "added" )
        self.assertIsNone( agent.error )

    def test_destructive_confirmation_denied_cancels( self ):
        """Ensures a denied destructive confirmation short-circuits to cancelled."""
        agent = self._agent_with_intent( CRUDIntent( operation="delete", schema_type="todo", item_id="abc" ) )
        with patch.object( agent, "_confirm_destructive_operation", return_value=False ):
            result = agent.run_code()
        self.assertEqual( result[ "output" ][ "status" ], "cancelled" )
        self.assertIsNone( agent.error )

    def test_destructive_confirmation_granted_dispatches( self ):
        """Ensures a granted destructive confirmation proceeds to dispatch."""
        agent = self._agent_with_intent( CRUDIntent( operation="delete", schema_type="todo", item_id="abc" ) )
        with patch.object( agent, "_confirm_destructive_operation", return_value=True ), \
             patch( "cosa.crud_for_dataframes.agent.dispatch", return_value={ "status": "deleted", "deleted_count": 1 } ):
            result = agent.run_code()
        self.assertEqual( result[ "output" ][ "status" ], "deleted" )

    def test_dispatch_error_then_fallback_success( self ):
        """Ensures a primary dispatch error falls back to Claude Code and succeeds."""
        agent = self._agent_with_intent( CRUDIntent( operation="add", target_list="g", schema_type="todo" ) )
        fallback_intent = CRUDIntent( operation="add", target_list="g", schema_type="todo" )
        with patch( "cosa.crud_for_dataframes.agent.dispatch",
                    side_effect=[ { "status": "error", "message": "phi-4 bad" }, { "status": "added" } ] ), \
             patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=fallback_intent ):
            result = agent.run_code()
        self.assertEqual( result[ "output" ][ "status" ], "added" )
        self.assertIsNone( agent.error )

    def test_dispatch_raises_then_fallback_none_raises( self ):
        """Ensures a dispatch exception with a None fallback raises CodeGenerationFailed."""
        agent = self._agent_with_intent( CRUDIntent( operation="add", target_list="g", schema_type="todo" ) )
        with patch( "cosa.crud_for_dataframes.agent.dispatch", side_effect=RuntimeError( "boom" ) ), \
             patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=None ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    def test_fallback_dispatch_error_raises( self ):
        """Ensures a fallback dispatch that returns error raises CodeGenerationFailed."""
        agent = self._agent_with_intent( CRUDIntent( operation="add", target_list="g", schema_type="todo" ) )
        fallback_intent = CRUDIntent( operation="add", target_list="g", schema_type="todo" )
        with patch( "cosa.crud_for_dataframes.agent.dispatch",
                    side_effect=[ { "status": "error", "message": "bad" }, { "status": "error", "message": "still bad" } ] ), \
             patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=fallback_intent ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()

    def test_fallback_dispatch_raises_wrapped( self ):
        """Ensures a fallback dispatch exception is wrapped in CodeGenerationFailed."""
        agent = self._agent_with_intent( CRUDIntent( operation="add", target_list="g", schema_type="todo" ) )
        fallback_intent = CRUDIntent( operation="add", target_list="g", schema_type="todo" )
        with patch( "cosa.crud_for_dataframes.agent.dispatch",
                    side_effect=[ { "status": "error", "message": "bad" }, RuntimeError( "fallback boom" ) ] ), \
             patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=fallback_intent ):
            with self.assertRaises( CodeGenerationFailedException ):
                agent.run_code()


class TestRunFormatter( unittest.TestCase ):
    """
    run_formatter — cancelled passthrough + normal voice formatting.
    """

    def test_cancelled_passthrough( self ):
        """Ensures a cancelled result returns its message verbatim."""
        agent, _ = _make_agent()
        agent.crud_intent       = CRUDIntent( operation="delete", schema_type="todo" )
        agent.code_response_dict = { "return_code": 0, "output": { "status": "cancelled", "message": "Operation cancelled." } }
        self.assertEqual( agent.run_formatter(), "Operation cancelled." )
        self.assertEqual( agent.answer, "Operation cancelled." )

    def test_normal_formatting( self ):
        """Ensures a normal result is formatted for voice and mirrored to answer."""
        agent, _ = _make_agent()
        agent.crud_intent        = CRUDIntent( operation="add", schema_type="todo" )
        agent.code_response_dict = { "return_code": 0, "output": { "status": "added", "message": "Added item to 'g'" } }
        voice = agent.run_formatter()
        self.assertIn( "Done", voice )
        self.assertEqual( agent.answer, voice )


class TestConfirmDestructiveOperation( unittest.TestCase ):
    """
    _confirm_destructive_operation — yes / no / timeout / error / None.
    """

    def _confirm( self, response ):
        agent, _ = _make_agent()
        agent.crud_intent = CRUDIntent( operation="delete", target_list="groceries", schema_type="todo" )
        with patch( "cosa.crud_for_dataframes.agent.notify_user_sync", return_value=response ):
            return agent._confirm_destructive_operation()

    def test_yes_confirms( self ):
        """Ensures a 'yes' response confirms the destructive op."""
        self.assertTrue( self._confirm( SimpleNamespace( is_timeout=False, is_error=False, response_value="yes" ) ) )

    def test_no_denies( self ):
        """Ensures a 'no' response denies the destructive op."""
        self.assertFalse( self._confirm( SimpleNamespace( is_timeout=False, is_error=False, response_value="no" ) ) )

    def test_timeout_denies( self ):
        """Ensures a timeout safely defaults to denial."""
        self.assertFalse( self._confirm( SimpleNamespace( is_timeout=True, is_error=False, response_value=None ) ) )

    def test_error_denies( self ):
        """Ensures an error safely defaults to denial."""
        self.assertFalse( self._confirm( SimpleNamespace( is_timeout=False, is_error=True, response_value=None ) ) )

    def test_none_value_denies( self ):
        """Ensures a None response value is treated as denial."""
        self.assertFalse( self._confirm( SimpleNamespace( is_timeout=False, is_error=False, response_value=None ) ) )


class TestRestoreFromSerializedState( unittest.TestCase ):
    """
    restore_from_serialized_state — explicitly unimplemented.
    """

    def test_raises_not_implemented( self ):
        """Ensures the restore hook fails loudly with NotImplementedError."""
        agent, _ = _make_agent()
        with self.assertRaises( NotImplementedError ):
            agent.restore_from_serialized_state( "/tmp/state.json" )


if __name__ == "__main__":
    unittest.main()
