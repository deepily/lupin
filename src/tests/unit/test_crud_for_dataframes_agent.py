#!/usr/bin/env python3
"""
Unit tests for Phase 2: CrudForDataFramesAgent, dispatcher, and intent_extractor.

Tests covering:
    - Dispatcher: dispatch() all 9 operations, format_result_for_voice(), extract_intent_xml()
    - Agent: constructor (mocked), run_prompt(), run_code(), run_formatter()
    - Error-based fallback: dispatch error → Claude Code mock → success
    - CodeGenerationFailedException: both paths fail → exception raised
    - Subclasses: TodoCrudAgent/CalendarCrudAgent default schema types
    - XML parsing: CRUDIntent.from_xml() edge cases

Run: pytest src/tests/unit/test_crud_for_dataframes_agent.py -v
"""

import json
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.crud_operations import add_item, create_list
from cosa.crud_for_dataframes.dispatcher import (
    dispatch,
    format_result_for_voice,
    extract_intent_xml,
)
from cosa.crud_for_dataframes.intent_extractor import (
    extract_intent_via_claude_code,
    build_claude_prompt,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_storage_dir():
    """Provide a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


@pytest.fixture
def storage( tmp_storage_dir ):
    """Provide a DataFrameStorage instance with temp directory."""
    return DataFrameStorage( user_email="test@example.com", base_path=tmp_storage_dir )


@pytest.fixture
def populated_storage( storage ):
    """Provide a storage with sample todo items."""
    add_item( storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )
    add_item( storage, "groceries", "todo", { "todo_item": "buy bread", "due_date": "2026-03-20" } )
    add_item( storage, "work", "todo", { "todo_item": "finish report", "priority": "high" } )
    return storage


@pytest.fixture
def sample_intent():
    """Provide a sample CRUDIntent for add operation."""
    return CRUDIntent(
        operation   = "add",
        target_list = "groceries",
        schema_type = "todo",
        confidence  = "0.95",
        fields      = '{"todo_item": "buy eggs", "priority": "medium"}'
    )


# ============================================================================
# TestExtractIntentXml
# ============================================================================

class TestExtractIntentXml:
    """Tests for extract_intent_xml() — regex extraction from raw LLM response."""

    def test_clean_xml( self ):
        """Extract from clean XML output."""
        xml = '<intent><operation>add</operation><target_list>groceries</target_list></intent>'
        result = extract_intent_xml( xml )
        assert "<operation>add</operation>" in result
        assert "<target_list>groceries</target_list>" in result

    def test_markdown_fenced( self ):
        """Extract from markdown code-fenced XML."""
        fenced = '```xml\n<intent><operation>query</operation><target_list>work</target_list></intent>\n```'
        result = extract_intent_xml( fenced )
        assert "<operation>query</operation>" in result

    def test_with_preamble( self ):
        """Extract from XML with preamble text."""
        text = 'Here is the extracted intent:\n\n<intent><operation>delete</operation></intent>\n\nI parsed the query.'
        result = extract_intent_xml( text )
        assert "<operation>delete</operation>" in result

    def test_multiline_xml( self ):
        """Extract from multi-line indented XML."""
        xml = """Some preamble text.

<intent>
    <operation>add</operation>
    <target_list>groceries</target_list>
    <schema_type>todo</schema_type>
    <fields>{"todo_item": "buy milk"}</fields>
</intent>

Some trailing text."""
        result = extract_intent_xml( xml )
        assert "<operation>add</operation>" in result
        assert "<fields>" in result

    def test_empty_response_raises( self ):
        """Empty response raises ValueError."""
        with pytest.raises( ValueError, match="Empty response" ):
            extract_intent_xml( "" )

    def test_whitespace_only_raises( self ):
        """Whitespace-only response raises ValueError."""
        with pytest.raises( ValueError, match="Empty response" ):
            extract_intent_xml( "   \n\t  " )

    def test_no_intent_block_raises( self ):
        """Response without <intent> raises ValueError."""
        with pytest.raises( ValueError, match="No <intent>" ):
            extract_intent_xml( "I could not understand your request." )

    def test_partial_intent_tag_raises( self ):
        """Incomplete intent tag raises ValueError."""
        with pytest.raises( ValueError, match="No <intent>" ):
            extract_intent_xml( "<intent><operation>add</operation>" )

    def test_double_fenced( self ):
        """Extract from doubly-fenced markdown."""
        text = '```\n```xml\n<intent><operation>update</operation></intent>\n```\n```'
        result = extract_intent_xml( text )
        assert "<operation>update</operation>" in result


# ============================================================================
# TestDispatch
# ============================================================================

class TestDispatch:
    """Tests for dispatch() — routing CRUDIntent to crud_operations."""

    def test_dispatch_add( self, storage ):
        """Add operation dispatches to add_item."""
        intent = CRUDIntent(
            operation   = "add",
            target_list = "groceries",
            schema_type = "todo",
            fields      = '{"todo_item": "buy milk", "priority": "high"}'
        )
        result = dispatch( intent, storage )
        assert result[ "status" ] == "added"
        assert "item_id" in result

    def test_dispatch_query_empty( self, storage ):
        """Query on empty storage returns ok with 0 items."""
        intent = CRUDIntent( operation="query", schema_type="todo" )
        result = dispatch( intent, storage )
        assert result[ "status" ] == "ok"
        assert result[ "total_count" ] == 0

    def test_dispatch_query_populated( self, populated_storage ):
        """Query on populated storage returns items."""
        intent = CRUDIntent(
            operation   = "query",
            target_list = "groceries",
            schema_type = "todo"
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "ok"
        assert result[ "total_count" ] == 2

    def test_dispatch_query_with_filters( self, populated_storage ):
        """Query with filters returns matching items."""
        intent = CRUDIntent(
            operation   = "query",
            schema_type = "todo",
            filters     = '{"priority": "high"}'
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "ok"
        assert result[ "total_count" ] == 2  # buy milk + finish report

    def test_dispatch_query_with_limit( self, populated_storage ):
        """Query with limit returns limited items."""
        intent = CRUDIntent(
            operation   = "query",
            schema_type = "todo",
            limit       = "1"
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "ok"
        assert len( result[ "items" ] ) == 1

    def test_dispatch_create_list( self, storage ):
        """Create list dispatches correctly."""
        intent = CRUDIntent(
            operation   = "create_list",
            target_list = "shopping",
            schema_type = "todo"
        )
        result = dispatch( intent, storage )
        assert result[ "status" ] == "created"

    def test_dispatch_delete_list( self, populated_storage ):
        """Delete list removes all items for that list."""
        intent = CRUDIntent(
            operation   = "delete_list",
            target_list = "groceries",
            schema_type = "todo"
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 2

    def test_dispatch_list_lists( self, populated_storage ):
        """List lists returns all lists metadata."""
        intent = CRUDIntent( operation="list_lists", schema_type="todo" )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "ok"
        assert result[ "total_lists" ] == 2  # groceries + work

    def test_dispatch_delete_item_by_id( self, populated_storage ):
        """Delete item by ID removes specific item."""
        # First query to get an item_id
        query_result = dispatch(
            CRUDIntent( operation="query", target_list="groceries", schema_type="todo" ),
            populated_storage
        )
        item_id = query_result[ "items" ][ 0 ][ "id" ]

        intent = CRUDIntent(
            operation   = "delete",
            schema_type = "todo",
            item_id     = item_id
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1

    def test_dispatch_update_item( self, populated_storage ):
        """Update item changes field values."""
        query_result = dispatch(
            CRUDIntent( operation="query", target_list="groceries", schema_type="todo" ),
            populated_storage
        )
        item_id = query_result[ "items" ][ 0 ][ "id" ]

        intent = CRUDIntent(
            operation   = "update",
            schema_type = "todo",
            item_id     = item_id,
            fields      = '{"priority": "low"}'
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "updated"
        assert result[ "updated_count" ] == 1

    def test_dispatch_mark_done( self, populated_storage ):
        """Mark done sets completed field."""
        query_result = dispatch(
            CRUDIntent( operation="query", target_list="work", schema_type="todo" ),
            populated_storage
        )
        item_id = query_result[ "items" ][ 0 ][ "id" ]

        intent = CRUDIntent(
            operation   = "mark_done",
            schema_type = "todo",
            item_id     = item_id
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "updated"

    def test_dispatch_get_schema_info( self, storage ):
        """Get schema info returns column metadata."""
        intent = CRUDIntent( operation="get_schema_info", schema_type="todo" )
        result = dispatch( intent, storage )
        assert result[ "status" ] == "ok"
        assert result[ "total_columns" ] > 0

    def test_dispatch_unknown_operation_raises( self, storage ):
        """Unknown operation raises ValueError."""
        intent = CRUDIntent( operation="explode" )
        with pytest.raises( ValueError, match="Unknown operation" ):
            dispatch( intent, storage )

    def test_dispatch_delete_match_fields( self, populated_storage ):
        """Delete item by match_fields removes matching items."""
        intent = CRUDIntent(
            operation    = "delete",
            schema_type  = "todo",
            match_fields = '{"todo_item": "buy milk"}'
        )
        result = dispatch( intent, populated_storage )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1


# ============================================================================
# TestFormatResultForVoice
# ============================================================================

class TestFormatResultForVoice:
    """Tests for format_result_for_voice() — TTS string generation."""

    def test_add_success( self ):
        """Added status produces 'Done' message."""
        result = { "status": "added", "message": "Added item to 'groceries'" }
        voice = format_result_for_voice( result, "add" )
        assert "Done" in voice

    def test_create_list_success( self ):
        """Created status produces 'Got it' message."""
        result = { "status": "created", "message": "List 'shopping' ready (schema: todo)" }
        voice = format_result_for_voice( result, "create_list" )
        assert "Got it" in voice

    def test_create_list_exists( self ):
        """Exists status returns the message."""
        result = { "status": "exists", "message": "List 'groceries' already exists with 3 items" }
        voice = format_result_for_voice( result, "create_list" )
        assert "already exists" in voice

    def test_delete_with_count( self ):
        """Delete with count produces counted message."""
        result = { "status": "deleted", "message": "Deleted 2 items", "deleted_count": 2 }
        voice = format_result_for_voice( result, "delete" )
        assert "2 items" in voice

    def test_delete_singular( self ):
        """Delete with count=1 uses singular 'item'."""
        result = { "status": "deleted", "message": "Deleted 1 item", "deleted_count": 1 }
        voice = format_result_for_voice( result, "delete" )
        assert "1 item" in voice
        assert "items" not in voice

    def test_update_with_count( self ):
        """Update with count produces counted message."""
        result = { "status": "updated", "message": "Updated 1 item", "updated_count": 1 }
        voice = format_result_for_voice( result, "update" )
        assert "1 item" in voice

    def test_mark_done_with_count( self ):
        """Mark done uses update formatting."""
        result = { "status": "updated", "message": "Updated 1 item", "updated_count": 1 }
        voice = format_result_for_voice( result, "mark_done" )
        assert "Done" in voice

    def test_query_empty( self ):
        """Query with 0 items returns 'No items found'."""
        result = { "status": "ok", "items": [], "total_count": 0 }
        voice = format_result_for_voice( result, "query" )
        assert "No items found" in voice

    def test_query_with_items( self ):
        """Query with items returns formatted summary."""
        result = {
            "status"      : "ok",
            "total_count" : 2,
            "items"       : [
                { "todo_item": "buy milk", "priority": "high", "completed": "no" },
                { "todo_item": "buy bread", "priority": "medium", "completed": "no" },
            ]
        }
        voice = format_result_for_voice( result, "query" )
        assert "Found 2 items" in voice
        assert "buy milk" in voice

    def test_query_with_completed_items( self ):
        """Query shows completed status."""
        result = {
            "status"      : "ok",
            "total_count" : 1,
            "items"       : [
                { "todo_item": "buy milk", "priority": "medium", "completed": "yes" },
            ]
        }
        voice = format_result_for_voice( result, "query" )
        assert "completed" in voice

    def test_query_many_items_truncated( self ):
        """Query with >5 items shows truncation message."""
        items = [ { "todo_item": f"item {i}" } for i in range( 8 ) ]
        result = { "status": "ok", "total_count": 8, "items": items }
        voice = format_result_for_voice( result, "query" )
        assert "3 more" in voice

    def test_list_lists_empty( self ):
        """List lists with 0 lists."""
        result = { "status": "ok", "lists": [], "total_lists": 0 }
        voice = format_result_for_voice( result, "list_lists" )
        assert "don't have any lists" in voice

    def test_list_lists_with_entries( self ):
        """List lists with entries shows names."""
        result = {
            "status"      : "ok",
            "total_lists" : 2,
            "lists"       : [
                { "list_name": "groceries", "schema_type": "todo", "row_count": 3 },
                { "list_name": "meetings", "schema_type": "calendar", "row_count": 5 },
            ]
        }
        voice = format_result_for_voice( result, "list_lists" )
        assert "2 lists" in voice
        assert "groceries" in voice
        assert "meetings" in voice

    def test_get_schema_info( self ):
        """Schema info returns column count."""
        result = { "status": "ok", "schema_type": "todo", "total_columns": 8, "columns": [] }
        voice = format_result_for_voice( result, "get_schema_info" )
        assert "8 columns" in voice
        assert "todo" in voice

    def test_error_status( self ):
        """Error status returns 'Sorry' message."""
        result = { "status": "error", "message": "list_name is required" }
        voice = format_result_for_voice( result, "add" )
        assert "Sorry" in voice
        assert "list_name" in voice

    def test_not_found_status( self ):
        """Not found status returns appropriate message."""
        result = { "status": "not_found", "message": "No matching items found" }
        voice = format_result_for_voice( result, "delete" )
        assert "couldn't find" in voice

    def test_fallback_message( self ):
        """Unknown status uses fallback message."""
        result = { "status": "unknown", "message": "Something happened" }
        voice = format_result_for_voice( result, "add" )
        assert "Something happened" in voice


# ============================================================================
# TestBuildClaudePrompt
# ============================================================================

class TestBuildClaudePrompt:
    """Tests for build_claude_prompt() — Claude Code fallback prompt building."""

    def test_includes_query( self ):
        """Prompt includes the user's query."""
        prompt = build_claude_prompt( "add buy milk to groceries", "- groceries (todo, 3 items)" )
        assert "add buy milk to groceries" in prompt

    def test_includes_available_lists( self ):
        """Prompt includes the user's list context."""
        prompt = build_claude_prompt( "add item", "- groceries (todo, 3 items)" )
        assert "groceries" in prompt

    def test_empty_lists( self ):
        """Prompt handles empty lists text."""
        prompt = build_claude_prompt( "add item", "" )
        assert "(no lists yet)" in prompt

    def test_includes_operations( self ):
        """Prompt includes valid operations."""
        prompt = build_claude_prompt( "test", "" )
        assert "add" in prompt
        assert "delete" in prompt
        assert "query" in prompt

    def test_includes_xml_example( self ):
        """Prompt includes an XML intent example."""
        prompt = build_claude_prompt( "test", "" )
        assert "<intent>" in prompt
        assert "</intent>" in prompt
        assert "<operation>" in prompt


# ============================================================================
# TestExtractIntentViaClaudeCode
# ============================================================================

class TestExtractIntentViaClaudeCode:
    """Tests for extract_intent_via_claude_code() with mocked subprocess."""

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_success( self, mock_run ):
        """Successful Claude Code call returns CRUDIntent."""
        mock_run.return_value = MagicMock(
            returncode = 0,
            stdout     = '<intent><operation>add</operation><target_list>groceries</target_list><schema_type>todo</schema_type><fields>{"todo_item": "buy milk"}</fields></intent>'
        )
        result = extract_intent_via_claude_code( "add buy milk to groceries", "" )
        assert result is not None
        assert result.operation == "add"
        assert result.target_list == "groceries"

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_nonzero_return_code( self, mock_run ):
        """Non-zero return code returns None."""
        mock_run.return_value = MagicMock( returncode=1, stdout="" )
        result = extract_intent_via_claude_code( "test query", "" )
        assert result is None

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_empty_stdout( self, mock_run ):
        """Empty stdout returns None."""
        mock_run.return_value = MagicMock( returncode=0, stdout="" )
        result = extract_intent_via_claude_code( "test query", "" )
        assert result is None

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_timeout( self, mock_run ):
        """Timeout returns None."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired( cmd="claude", timeout=30 )
        result = extract_intent_via_claude_code( "test query", "" )
        assert result is None

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_invalid_xml( self, mock_run ):
        """Invalid XML response returns None."""
        mock_run.return_value = MagicMock(
            returncode = 0,
            stdout     = "Sorry, I cannot parse that query."
        )
        result = extract_intent_via_claude_code( "???", "" )
        assert result is None

    @patch( "cosa.crud_for_dataframes.intent_extractor.subprocess.run" )
    def test_with_preamble( self, mock_run ):
        """Response with preamble before XML is handled."""
        mock_run.return_value = MagicMock(
            returncode = 0,
            stdout     = 'Here is the intent:\n<intent><operation>query</operation><schema_type>todo</schema_type></intent>'
        )
        result = extract_intent_via_claude_code( "show my lists", "" )
        assert result is not None
        assert result.operation == "query"


# ============================================================================
# TestCrudForDataFramesAgentMocked
# ============================================================================

class TestCrudForDataFramesAgentMocked:
    """Tests for CrudForDataFramesAgent with mocked dependencies."""

    def _create_agent( self, tmp_dir=None ):
        """Helper: Create an agent with manually set attributes (no AgentBase.__init__)."""
        from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent

        agent = CrudForDataFramesAgent.__new__( CrudForDataFramesAgent )

        # Manually set attributes that __init__ would set
        agent.debug                = True
        agent.verbose              = False
        agent.last_question_asked  = "add buy milk to my grocery list"
        agent.question             = "add buy milk to my grocery list"
        agent.model_name           = "kaitchup/phi_4_14b"
        agent.routing_command      = "agent router go to crud for dataframes"
        agent.user_email           = "test@example.com"
        agent.prompt_response_dict = None
        agent.code_response_dict   = None
        agent.error                = ""
        agent.answer               = ""
        agent.answer_conversational = None
        agent.crud_intent          = None
        agent.auto_debug           = False
        agent.inject_bugs          = False

        # Create real storage in tmp_dir
        if tmp_dir:
            agent.storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )
        else:
            agent.storage = MagicMock()
            agent.storage.get_all_lists_metadata.return_value = []

        # Build a simple prompt
        intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )
        agent.prompt = f"Extract intent: add buy milk to my grocery list\n{intent_example}"

        return agent

    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_run_prompt_parses_intent( self, mock_factory_cls ):
        """run_prompt() extracts and parses CRUDIntent from LLM response."""
        agent = self._create_agent()

        # Mock LLM response
        mock_llm = MagicMock()
        mock_llm.run.return_value = '<intent><operation>add</operation><target_list>groceries</target_list><schema_type>todo</schema_type><confidence>0.95</confidence><fields>{"todo_item": "buy milk"}</fields></intent>'
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        result = agent.run_prompt()

        assert agent.crud_intent is not None
        assert agent.crud_intent.operation == "add"
        assert agent.crud_intent.target_list == "groceries"
        assert result[ "operation" ] == "add"

    def test_run_code_dispatches_intent( self, tmp_storage_dir ):
        """run_code() dispatches CRUDIntent to storage operations."""
        agent = self._create_agent( tmp_dir=tmp_storage_dir )

        agent.crud_intent = CRUDIntent(
            operation   = "add",
            target_list = "groceries",
            schema_type = "todo",
            fields      = '{"todo_item": "buy milk", "priority": "high"}'
        )

        result = agent.run_code()
        assert result[ "return_code" ] == 0
        assert result[ "output" ][ "status" ] == "added"
        assert agent.error is None

    def test_run_code_error_triggers_fallback( self, tmp_storage_dir ):
        """run_code() falls back to Claude Code when dispatch fails."""
        agent = self._create_agent( tmp_dir=tmp_storage_dir )

        # Set an intent that will fail (delete with no id or match_fields)
        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            schema_type = "todo"
        )

        # Mock Claude Code fallback to succeed
        fallback_intent = CRUDIntent(
            operation   = "add",
            target_list = "groceries",
            schema_type = "todo",
            fields      = '{"todo_item": "buy milk"}'
        )

        with patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=fallback_intent ):
            result = agent.run_code()
            assert result[ "return_code" ] == 0
            assert result[ "output" ][ "status" ] == "added"

    def test_run_code_both_fail_raises( self, tmp_storage_dir ):
        """run_code() raises CodeGenerationFailedException when both paths fail."""
        from cosa.agents.agent_base import CodeGenerationFailedException
        agent = self._create_agent( tmp_dir=tmp_storage_dir )

        # Set an intent that will fail
        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            schema_type = "todo"
        )

        # Mock Claude Code fallback to return None
        with patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=None ):
            with pytest.raises( CodeGenerationFailedException, match="CRUD dispatch failed" ):
                agent.run_code()

    def test_run_code_fallback_also_fails_raises( self, tmp_storage_dir ):
        """run_code() raises CodeGenerationFailedException when fallback dispatch also fails."""
        from cosa.agents.agent_base import CodeGenerationFailedException
        agent = self._create_agent( tmp_dir=tmp_storage_dir )

        # Set an intent that will fail
        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            schema_type = "todo"
        )

        # Mock Claude Code fallback to return another bad intent
        bad_fallback = CRUDIntent(
            operation   = "delete",
            schema_type = "todo"
        )

        with patch( "cosa.crud_for_dataframes.agent.extract_intent_via_claude_code", return_value=bad_fallback ):
            with pytest.raises( CodeGenerationFailedException, match="after Phi-4 and Claude Code" ):
                agent.run_code()

    def test_run_formatter( self, tmp_storage_dir ):
        """run_formatter() produces TTS-friendly string."""
        agent = self._create_agent( tmp_dir=tmp_storage_dir )

        agent.crud_intent = CRUDIntent( operation="add", target_list="groceries", schema_type="todo" )
        agent.code_response_dict = {
            "return_code" : 0,
            "output"      : { "status": "added", "message": "Added item to 'groceries'", "item_id": "abc12345" }
        }

        result = agent.run_formatter()
        assert "Done" in result
        assert agent.answer_conversational == result
        assert agent.answer == result

    def test_format_lists_for_prompt_empty( self ):
        """_format_lists_for_prompt handles empty metadata."""
        from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
        result = CrudForDataFramesAgent._format_lists_for_prompt( None, [] )
        assert result == "(no lists yet)"

    def test_format_lists_for_prompt_with_data( self ):
        """_format_lists_for_prompt formats metadata as bullet list."""
        from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
        metadata = [
            { "schema_type": "todo", "list_name": "groceries", "row_count": 3 },
            { "schema_type": "calendar", "list_name": "meetings", "row_count": 5 },
        ]
        result = CrudForDataFramesAgent._format_lists_for_prompt( None, metadata )
        assert "groceries" in result
        assert "meetings" in result
        assert "3 items" in result
        assert "5 items" in result

    def test_restore_from_serialized_raises( self ):
        """restore_from_serialized_state raises NotImplementedError."""
        agent = self._create_agent()
        with pytest.raises( NotImplementedError ):
            agent.restore_from_serialized_state( "/tmp/test.json" )


# ============================================================================
# TestSubclasses
# ============================================================================

class TestSubclasses:
    """Tests for TodoCrudAgent and CalendarCrudAgent thin subclasses."""

    def test_todo_crud_agent_schema_type( self ):
        """TodoCrudAgent has DEFAULT_SCHEMA_TYPE='todo'."""
        from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
        assert TodoCrudAgent.DEFAULT_SCHEMA_TYPE == "todo"

    def test_calendar_crud_agent_schema_type( self ):
        """CalendarCrudAgent has DEFAULT_SCHEMA_TYPE='calendar'."""
        from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
        assert CalendarCrudAgent.DEFAULT_SCHEMA_TYPE == "calendar"

    def test_todo_inherits_from_base( self ):
        """TodoCrudAgent inherits from CrudForDataFramesAgent."""
        from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
        from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
        assert issubclass( TodoCrudAgent, CrudForDataFramesAgent )

    def test_calendar_inherits_from_base( self ):
        """CalendarCrudAgent inherits from CrudForDataFramesAgent."""
        from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
        from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
        assert issubclass( CalendarCrudAgent, CrudForDataFramesAgent )


# ============================================================================
# TestCRUDIntentXmlParsing
# ============================================================================

class TestCRUDIntentXmlParsing:
    """Tests for CRUDIntent.from_xml() edge cases."""

    def test_clean_xml_round_trip( self ):
        """Clean XML round-trips through from_xml/to_xml."""
        original = CRUDIntent.get_example_for_template()
        xml_str  = original.to_xml( root_tag="intent" )
        parsed   = CRUDIntent.from_xml( xml_str, root_tag="intent" )

        assert parsed.operation == original.operation
        assert parsed.target_list == original.target_list
        assert parsed.schema_type == original.schema_type
        assert parsed.confidence == original.confidence
        assert parsed.raw_query == original.raw_query

    def test_minimal_xml( self ):
        """Parse XML with only required operation field."""
        xml = '<intent><operation>list_lists</operation></intent>'
        intent = CRUDIntent.from_xml( xml, root_tag="intent" )
        assert intent.operation == "list_lists"
        assert intent.target_list == ""
        assert intent.schema_type == "todo"  # default

    def test_empty_tags_coerced( self ):
        """Empty XML tags are coerced to empty strings (not None)."""
        xml = '<intent><operation>query</operation><target_list></target_list><item_id></item_id></intent>'
        intent = CRUDIntent.from_xml( xml, root_tag="intent" )
        assert intent.target_list == ""
        assert intent.item_id == ""

    def test_json_fields_preserved( self ):
        """JSON strings in fields are preserved through XML."""
        fields_json = '{"todo_item": "buy milk", "priority": "high"}'
        xml = f'<intent><operation>add</operation><fields>{fields_json}</fields></intent>'
        intent = CRUDIntent.from_xml( xml, root_tag="intent" )
        fields = intent.get_fields_dict()
        assert fields[ "todo_item" ] == "buy milk"
        assert fields[ "priority" ] == "high"

    def test_malformed_xml_raises( self ):
        """Malformed XML raises XMLParsingError."""
        from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
        with pytest.raises( XMLParsingError ):
            CRUDIntent.from_xml( "not xml at all" )

    def test_missing_required_operation( self ):
        """Missing required operation field raises error."""
        from cosa.agents.io_models.utils.util_xml_pydantic import XMLParsingError
        xml = '<intent><target_list>groceries</target_list></intent>'
        with pytest.raises( XMLParsingError ):
            CRUDIntent.from_xml( xml, root_tag="intent" )

    def test_xml_with_whitespace( self ):
        """XML with lots of whitespace parses correctly."""
        xml = """
        <intent>
            <operation>  add  </operation>
            <target_list>  groceries  </target_list>
            <schema_type>todo</schema_type>
        </intent>
        """
        intent = CRUDIntent.from_xml( xml, root_tag="intent" )
        # Note: BaseXMLModel preserves whitespace, operation matching should be case-insensitive and stripped
        assert intent.operation.strip() == "add"
        assert intent.target_list.strip() == "groceries"


# ============================================================================
# TestDispatchIntegration
# ============================================================================

class TestDispatchIntegration:
    """Integration-style tests: full cycle from CRUDIntent through dispatch to voice."""

    def test_add_query_delete_cycle( self, storage ):
        """Full CRUD lifecycle: add → query → delete."""
        # Add
        add_intent = CRUDIntent(
            operation   = "add",
            target_list = "test_list",
            schema_type = "todo",
            fields      = '{"todo_item": "test item", "priority": "high"}'
        )
        add_result = dispatch( add_intent, storage )
        assert add_result[ "status" ] == "added"
        item_id = add_result[ "item_id" ]

        add_voice = format_result_for_voice( add_result, "add" )
        assert "Done" in add_voice

        # Query
        query_intent = CRUDIntent(
            operation   = "query",
            target_list = "test_list",
            schema_type = "todo"
        )
        query_result = dispatch( query_intent, storage )
        assert query_result[ "total_count" ] == 1
        assert query_result[ "items" ][ 0 ][ "todo_item" ] == "test item"

        query_voice = format_result_for_voice( query_result, "query" )
        assert "Found 1 item" in query_voice

        # Delete
        delete_intent = CRUDIntent(
            operation   = "delete",
            schema_type = "todo",
            item_id     = item_id
        )
        delete_result = dispatch( delete_intent, storage )
        assert delete_result[ "status" ] == "deleted"

        delete_voice = format_result_for_voice( delete_result, "delete" )
        assert "Done" in delete_voice

        # Verify empty
        query_result = dispatch( query_intent, storage )
        assert query_result[ "total_count" ] == 0

    def test_mark_done_and_query( self, storage ):
        """Add item, mark done, verify completed."""
        # Add
        add_intent = CRUDIntent(
            operation   = "add",
            target_list = "work",
            schema_type = "todo",
            fields      = '{"todo_item": "finish report"}'
        )
        add_result = dispatch( add_intent, storage )
        item_id = add_result[ "item_id" ]

        # Mark done
        done_intent = CRUDIntent(
            operation   = "mark_done",
            schema_type = "todo",
            item_id     = item_id
        )
        done_result = dispatch( done_intent, storage )
        assert done_result[ "status" ] == "updated"

        # Query and verify completed
        query_intent = CRUDIntent(
            operation   = "query",
            schema_type = "todo",
            filters     = '{"completed": "yes"}'
        )
        query_result = dispatch( query_intent, storage )
        assert query_result[ "total_count" ] == 1
        assert query_result[ "items" ][ 0 ][ "completed" ] == "yes"
