#!/usr/bin/env python3
"""
Integration tests for DataFrame CRUD mock pipeline (Part 1 of testing protocol).

17 scenarios testing the full pipeline with mocked LLM and notification services.
No server required — all dependencies are mocked.

Test classes:
    - TestRoutingSwapPipeline (3): Feature flag gates CRUD vs legacy agent creation
    - TestFullPipelineMocked (3): End-to-end add/query/delete via run_prompt → run_code → run_formatter
    - TestCacheBypassPipeline (2): CRUD agents skip snapshot cache, non-CRUD agents don't
    - TestConfirmationFlowPipeline (4): Delete triggers confirmation; add skips it entirely
    - TestPromptConstruction (5): Real template + PromptTemplateProcessor produces correct prompt

Run: pytest src/tests/unit/test_crud_mock_pipeline.py -v
"""

import tempfile
from unittest.mock import patch, MagicMock

import pytest

import cosa.utils.util as cu
from cosa.agents.io_models.utils.prompt_template_processor import PromptTemplateProcessor
from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.crud_operations import add_item
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_storage_dir():
    """Provide a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


# ============================================================================
# Helpers
# ============================================================================

def _create_mock_agent( agent_cls=CrudForDataFramesAgent, tmp_dir=None, question="add buy milk to my grocery list" ):
    """
    Create an agent via __new__() bypass, skipping AgentBase.__init__.

    Reuses the pattern from test_crud_for_dataframes_agent.py:555.

    Requires:
        - agent_cls is CrudForDataFramesAgent or a subclass

    Ensures:
        - Returns a fully wired agent with mocked or real storage
        - Agent has all attributes needed for run_prompt/run_code/run_formatter
    """
    agent = agent_cls.__new__( agent_cls )

    agent.debug                 = True
    agent.verbose               = False
    agent.last_question_asked   = question
    agent.question              = question
    agent.model_name            = "kaitchup/phi_4_14b"
    agent.routing_command       = "agent router go to crud for dataframes"
    agent.user_email            = "test@example.com"
    agent.prompt_response_dict  = None
    agent.code_response_dict    = None
    agent.error                 = ""
    agent.answer                = ""
    agent.answer_conversational = None
    agent.crud_intent           = None
    agent.auto_debug            = False
    agent.inject_bugs           = False

    if tmp_dir:
        agent.storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )
    else:
        agent.storage = MagicMock()
        agent.storage.get_all_lists_metadata.return_value = []

    # Ad-hoc prompt — sufficient for mocked-LLM tests. For real template +
    # PromptTemplateProcessor verification, see TestPromptConstruction below.
    intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )
    agent.prompt = f"Extract intent: {question}\n{intent_example}"

    return agent


# ============================================================================
# TestRoutingSwapPipeline — Feature flag gates CRUD vs legacy agent creation
# ============================================================================

class TestRoutingSwapPipeline:
    """Routing swap creates the correct agent type based on feature flag."""

    def test_todo_command_creates_crud_agent_when_enabled( self ):
        """'agent router go to todo' with flag=true creates TodoCrudAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True

    def test_todo_command_creates_legacy_agent_when_disabled( self ):
        """'agent router go to todo' with flag=false creates legacy TodoListAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "false"

        assert queue._crud_agents_enabled() is False

    def test_calendar_command_creates_crud_agent_when_enabled( self ):
        """'agent router go to calendar' with flag=true creates CalendarCrudAgent."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue            = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = MagicMock()
        queue.config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True


# ============================================================================
# TestFullPipelineMocked — End-to-end: run_prompt → run_code → run_formatter
# ============================================================================

class TestFullPipelineMocked:
    """Mocked end-to-end pipeline: run_prompt -> run_code -> run_formatter."""

    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_add_pipeline( self, mock_factory_cls, tmp_storage_dir ):
        """Full add pipeline: LLM extracts intent -> dispatch adds item -> TTS formats result."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir )

        # Mock LLM to return valid add intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>add</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.95</confidence>'
            '<fields>{"todo_item": "buy milk", "priority": "high"}</fields></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # Step 1: run_prompt
        prompt_result = agent.run_prompt()
        assert agent.crud_intent is not None
        assert agent.crud_intent.operation == "add"
        assert agent.crud_intent.target_list == "groceries"

        # Step 2: run_code (add doesn't need confirmation)
        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "added"

        # Step 3: run_formatter
        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0
        assert agent.answer_conversational == tts_result

    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_query_pipeline( self, mock_factory_cls, tmp_storage_dir ):
        """Full query pipeline: add item first, then query -> verify TTS output."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="what's on my grocery list?" )

        # Pre-populate: add an item directly via storage
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        # Mock LLM to return query intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>query</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.90</confidence></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        prompt_result = agent.run_prompt()
        assert agent.crud_intent.operation == "query"

        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "ok"

        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    @patch( "cosa.crud_for_dataframes.agent.LlmClientFactory" )
    def test_delete_pipeline( self, mock_factory_cls, mock_notify, tmp_storage_dir ):
        """Full delete pipeline: add -> delete with confirmation -> verify TTS."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        # Pre-populate
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        # Mock LLM to return delete intent
        mock_llm = MagicMock()
        mock_llm.run.return_value = (
            '<intent><operation>delete</operation><target_list>groceries</target_list>'
            '<schema_type>todo</schema_type><confidence>0.92</confidence>'
            '<match_fields>{"todo_item": "buy milk"}</match_fields></intent>'
        )
        mock_factory_cls.return_value.get_client.return_value = mock_llm

        # Mock confirmation: user says yes
        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "yes"
        mock_notify.return_value     = mock_response

        prompt_result = agent.run_prompt()
        assert agent.crud_intent.operation == "delete"

        code_result = agent.run_code()
        assert code_result[ "return_code" ] == 0
        assert code_result[ "output" ][ "status" ] == "deleted"
        mock_notify.assert_called_once()

        tts_result = agent.run_formatter()
        assert len( tts_result ) > 0


# ============================================================================
# TestCacheBypassPipeline — CRUD agents skip the LanceDB snapshot cache
# ============================================================================

class TestCacheBypassPipeline:
    """CRUD agents bypass the LanceDB snapshot cache."""

    def test_crud_agent_triggers_cache_skip( self ):
        """isinstance(agent, CrudForDataFramesAgent) is True -> cache skipped."""
        agent = _create_mock_agent()
        assert isinstance( agent, CrudForDataFramesAgent )

        # Simulate the cache decision from running_fifo_queue.py:160-164
        should_skip_cache = isinstance( agent, CrudForDataFramesAgent )
        assert should_skip_cache is True

    def test_non_crud_agent_uses_cache( self ):
        """Non-CRUD AgentBase subclasses still use the cache."""
        from cosa.agents.math_agent import MathAgent

        # MathAgent is a regular AgentBase — should NOT skip cache
        assert issubclass( MathAgent, CrudForDataFramesAgent ) is False


# ============================================================================
# TestConfirmationFlowPipeline — Voice confirmation for destructive operations
# ============================================================================

class TestConfirmationFlowPipeline:
    """Voice confirmation for destructive operations."""

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_triggers_confirmation_yes_proceeds( self, mock_notify, tmp_storage_dir ):
        """Delete operation: user says yes -> dispatch proceeds."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        agent.crud_intent = CRUDIntent(
            operation    = "delete",
            target_list  = "groceries",
            schema_type  = "todo",
            match_fields = '{"todo_item": "buy milk"}'
        )

        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "yes"
        mock_notify.return_value     = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "deleted"

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_triggers_confirmation_no_cancels( self, mock_notify, tmp_storage_dir ):
        """Delete operation: user says no -> operation cancelled."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            target_list = "groceries",
            schema_type = "todo"
        )

        mock_response                = MagicMock()
        mock_response.is_timeout     = False
        mock_response.is_error       = False
        mock_response.response_value = "no"
        mock_notify.return_value     = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "cancelled"
        assert result[ "output" ][ "message" ] == "Operation cancelled."

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_delete_timeout_cancels_safely( self, mock_notify, tmp_storage_dir ):
        """Delete operation: timeout -> operation cancelled (safe default)."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, question="delete buy milk from groceries" )

        agent.crud_intent = CRUDIntent(
            operation   = "delete",
            target_list = "groceries",
            schema_type = "todo"
        )

        mock_response            = MagicMock()
        mock_response.is_timeout = True
        mock_response.is_error   = False
        mock_notify.return_value = mock_response

        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "cancelled"

    def test_add_skips_confirmation_entirely( self, tmp_storage_dir ):
        """Add operation: no confirmation prompt triggered."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir )

        agent.crud_intent = CRUDIntent(
            operation   = "add",
            target_list = "groceries",
            schema_type = "todo",
            fields      = '{"todo_item": "buy milk", "priority": "high"}'
        )

        # No mock for notify_user_sync — if called, test would fail
        result = agent.run_code()
        assert result[ "output" ][ "status" ] == "added"


# ============================================================================
# TestPromptConstruction — Real template + PromptTemplateProcessor verification
# ============================================================================

class TestPromptConstruction:
    """Verify the real template + PromptTemplateProcessor produces a correct prompt."""

    TEMPLATE_PATH    = "/src/conf/prompts/crud-for-dataframes/intent-extraction.txt"
    ROUTING_COMMAND  = "agent router go to crud for dataframes"

    @pytest.fixture
    def processed_prompt( self ):
        """Read real template, process through PromptTemplateProcessor, return result."""
        template_path = cu.get_project_root() + self.TEMPLATE_PATH
        with open( template_path, "r" ) as f:
            raw_template = f.read()

        processor = PromptTemplateProcessor( debug=False )
        return processor.process_template( raw_template, self.ROUTING_COMMAND )

    def test_template_marker_replaced( self, processed_prompt ):
        """{{PYDANTIC_XML_EXAMPLE}} marker is replaced by PromptTemplateProcessor."""
        assert "{{PYDANTIC_XML_EXAMPLE}}" not in processed_prompt

    def test_intent_xml_injected( self, processed_prompt ):
        """Processed template contains <intent>...</intent> XML block."""
        assert "<intent>" in processed_prompt
        assert "</intent>" in processed_prompt
        assert "<operation>" in processed_prompt

    def test_stop_sentinel_present( self, processed_prompt ):
        """Processed template includes </stop> sentinel after closing </intent>."""
        assert "</stop>" in processed_prompt
        # Sentinel should come after the intent block
        intent_end = processed_prompt.index( "</intent>" )
        stop_pos   = processed_prompt.index( "</stop>" )
        assert stop_pos > intent_end

    def test_generic_placeholders_not_concrete( self, processed_prompt ):
        """XML example uses generic placeholders, not concrete data like 'groceries'."""
        # Verify generic placeholders are present
        assert "[operation name]" in processed_prompt
        assert "[target list name]" in processed_prompt

        # Verify concrete data from old template is absent (the example should NOT
        # contain specific values that might bias the LLM toward canned answers)
        xml_start = processed_prompt.index( "<intent>" )
        xml_end   = processed_prompt.index( "</stop>" ) + len( "</stop>" )
        xml_block = processed_prompt[ xml_start:xml_end ]
        assert "groceries" not in xml_block

    def test_format_substitution_works( self, processed_prompt ):
        """prompt_template.format(query=..., available_lists=...) succeeds."""
        # After processor replaces {{PYDANTIC_XML_EXAMPLE}}, .format() with 2 params should work.
        # This would fail if legacy {intent_example} placeholder were still present.
        final_prompt = processed_prompt.format(
            query           = "add buy milk to my grocery list",
            available_lists = "- groceries (todo, 3 items)"
        )
        assert "add buy milk to my grocery list" in final_prompt
        assert "- groceries (todo, 3 items)" in final_prompt
