#!/usr/bin/env python3
"""
Unit tests for Layer 3: Queue Integration + Voice Confirmation for DataFrame CRUD.

Tests covering:
    - TestCrudQueueRouting: Feature flag, agent creation for todo/calendar commands
    - TestCrudCacheBehavior: Cache skip for CRUD agents, serialization exclusion
    - TestCrudConfirmationFlow: Destructive ops trigger confirmation, yes/no/timeout/cancelled

Run: pytest src/tests/unit/test_crud_queue_integration.py -v
"""

import tempfile
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.agent import CrudForDataFramesAgent
from cosa.crud_for_dataframes.todo_crud_agent import TodoCrudAgent
from cosa.crud_for_dataframes.calendar_crud_agent import CalendarCrudAgent
from cosa.agents.agent_base import AgentBase
from cosa.rest.job_state import JobState


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_storage_dir():
    """Provide a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


@pytest.fixture
def mock_config_mgr():
    """Provide a mock ConfigurationManager."""
    mgr = MagicMock()
    mgr.get.return_value = "true"
    return mgr


def _create_mock_agent( tmp_dir=None, operation="add", needs_confirm=False ):
    """Helper: Create a CrudForDataFramesAgent with manually set attributes (no __init__)."""
    agent = CrudForDataFramesAgent.__new__( CrudForDataFramesAgent )

    agent.debug                 = True
    agent.verbose               = False
    agent.last_question_asked   = "delete buy milk from my grocery list"
    agent.question              = "delete buy milk from my grocery list"
    agent.model_name            = "kaitchup/phi_4_14b"
    agent.routing_command       = "agent router go to crud for dataframes"
    agent.user_id               = "test@example.com"
    agent.user_email            = "test@example.com"
    agent.prompt_response_dict  = None
    agent.code_response_dict    = None
    agent.error                 = ""
    agent.answer                = ""
    agent.answer_conversational = None
    agent.auto_debug            = False
    agent.inject_bugs           = False

    if tmp_dir:
        agent.storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )
    else:
        agent.storage = MagicMock()
        agent.storage.get_all_lists_metadata.return_value = []

    agent.crud_intent = CRUDIntent(
        operation             = operation,
        target_list           = "groceries",
        schema_type           = "todo",
        requires_confirmation = "true" if needs_confirm else "false",
        fields                = '{"todo_item": "buy milk", "priority": "high"}'
    )

    intent_example = CRUDIntent.get_example_for_template().to_xml( root_tag="intent" )
    agent.prompt = f"Extract intent: test\n{intent_example}"

    return agent


# ============================================================================
# TestCrudQueueRouting — Feature flag + agent creation
# ============================================================================

class TestCrudQueueRouting:
    """Tests for feature-flag-gated agent creation in todo_fifo_queue.py."""

    def test_crud_agents_enabled_true( self, mock_config_mgr ):
        """_crud_agents_enabled() returns True when flag is 'true'."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = mock_config_mgr
        mock_config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True

    def test_crud_agents_enabled_false( self, mock_config_mgr ):
        """_crud_agents_enabled() returns False when flag is 'false'."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = mock_config_mgr
        mock_config_mgr.get.return_value = "false"

        assert queue._crud_agents_enabled() is False

    def test_crud_agents_enabled_default( self, mock_config_mgr ):
        """_crud_agents_enabled() defaults to True when key missing."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = mock_config_mgr
        # Simulate missing key — default= param in get() returns "true"
        mock_config_mgr.get.return_value = "true"

        assert queue._crud_agents_enabled() is True

    def test_crud_agents_enabled_whitespace( self, mock_config_mgr ):
        """_crud_agents_enabled() handles whitespace around value."""
        from cosa.rest.todo_fifo_queue import TodoFifoQueue

        queue = TodoFifoQueue.__new__( TodoFifoQueue )
        queue.config_mgr = mock_config_mgr
        mock_config_mgr.get.return_value = "  True  "

        assert queue._crud_agents_enabled() is True

    def test_todo_crud_agent_is_agent_base( self ):
        """TodoCrudAgent inherits from AgentBase."""
        assert issubclass( TodoCrudAgent, AgentBase )
        assert issubclass( TodoCrudAgent, CrudForDataFramesAgent )

    def test_calendar_crud_agent_is_agent_base( self ):
        """CalendarCrudAgent inherits from AgentBase."""
        assert issubclass( CalendarCrudAgent, AgentBase )
        assert issubclass( CalendarCrudAgent, CrudForDataFramesAgent )

    def test_todo_crud_agent_same_constructor_args( self ):
        """TodoCrudAgent accepts same constructor kwargs as legacy TodoListAgent."""
        import inspect
        sig = inspect.signature( TodoCrudAgent.__init__ )
        params = list( sig.parameters.keys() )

        expected = [ "self", "question", "question_gist", "last_question_asked",
                     "push_counter", "routing_command", "user_id", "user_email",
                     "session_id", "debug", "verbose", "auto_debug", "inject_bugs" ]
        assert params == expected

    def test_calendar_crud_agent_same_constructor_args( self ):
        """CalendarCrudAgent accepts same constructor kwargs as legacy CalendaringAgent."""
        import inspect
        sig = inspect.signature( CalendarCrudAgent.__init__ )
        params = list( sig.parameters.keys() )

        expected = [ "self", "question", "question_gist", "last_question_asked",
                     "push_counter", "routing_command", "user_id", "user_email",
                     "session_id", "debug", "verbose", "auto_debug", "inject_bugs" ]
        assert params == expected


# ============================================================================
# TestCrudCacheBehavior — Cache skip + serialization exclusion
# ============================================================================

class TestCrudCacheBehavior:
    """Tests for CRUD agent cache skip and serialization exclusion in running_fifo_queue.py."""

    def test_crud_agent_is_instance_of_agent_base( self ):
        """CrudForDataFramesAgent is an AgentBase subclass (for isinstance checks)."""
        assert issubclass( CrudForDataFramesAgent, AgentBase )

    def test_crud_agent_isinstance_check( self, tmp_storage_dir ):
        """isinstance(agent, CrudForDataFramesAgent) works for CRUD agents."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir )
        assert isinstance( agent, CrudForDataFramesAgent )
        assert isinstance( agent, AgentBase )

    def test_todo_crud_agent_isinstance_check( self ):
        """isinstance(agent, CrudForDataFramesAgent) returns True for TodoCrudAgent."""
        agent = TodoCrudAgent.__new__( TodoCrudAgent )
        assert isinstance( agent, CrudForDataFramesAgent )
        assert isinstance( agent, AgentBase )

    def test_calendar_crud_agent_isinstance_check( self ):
        """isinstance(agent, CrudForDataFramesAgent) returns True for CalendarCrudAgent."""
        agent = CalendarCrudAgent.__new__( CalendarCrudAgent )
        assert isinstance( agent, CrudForDataFramesAgent )
        assert isinstance( agent, AgentBase )

    def test_serialization_exclusion_pattern( self ):
        """CrudForDataFramesAgent matches the serialization exclusion isinstance pattern."""
        from cosa.agents.receptionist_agent import ReceptionistAgent
        from cosa.agents.weather_agent import WeatherAgent

        agent = CrudForDataFramesAgent.__new__( CrudForDataFramesAgent )

        # Simulate the exclusion pattern from running_fifo_queue.py
        serialize_snapshot = (
            not isinstance( agent, ReceptionistAgent ) and
            not isinstance( agent, WeatherAgent ) and
            not isinstance( agent, CrudForDataFramesAgent )
        )
        assert serialize_snapshot is False, "CRUD agents should be excluded from serialization"


# ============================================================================
# TestCrudConfirmationFlow — Voice confirmation for destructive operations
# ============================================================================

class TestCrudConfirmationFlow:
    """Tests for voice confirmation of destructive CRUD operations."""

    def test_delete_needs_confirmation( self ):
        """CRUDIntent with delete operation needs confirmation."""
        intent = CRUDIntent( operation="delete", schema_type="todo", target_list="groceries" )
        assert intent.needs_confirmation() is True

    def test_delete_list_needs_confirmation( self ):
        """CRUDIntent with delete_list operation needs confirmation."""
        intent = CRUDIntent( operation="delete_list", schema_type="todo", target_list="groceries" )
        assert intent.needs_confirmation() is True

    def test_update_needs_confirmation( self ):
        """CRUDIntent with update operation needs confirmation."""
        intent = CRUDIntent( operation="update", schema_type="todo", target_list="groceries" )
        assert intent.needs_confirmation() is True

    def test_add_no_confirmation( self ):
        """CRUDIntent with add operation does NOT need confirmation."""
        intent = CRUDIntent( operation="add", schema_type="todo", target_list="groceries" )
        assert intent.needs_confirmation() is False

    def test_query_no_confirmation( self ):
        """CRUDIntent with query operation does NOT need confirmation."""
        intent = CRUDIntent( operation="query", schema_type="todo", target_list="groceries" )
        assert intent.needs_confirmation() is False

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_confirm_destructive_yes( self, mock_notify, tmp_storage_dir ):
        """_confirm_destructive_operation() returns True when user says yes."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        mock_response = MagicMock()
        mock_response.is_timeout = False
        mock_response.is_error   = False
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response

        result = agent._confirm_destructive_operation()
        assert result is True
        mock_notify.assert_called_once()

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_confirm_destructive_no( self, mock_notify, tmp_storage_dir ):
        """_confirm_destructive_operation() returns False when user says no."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        mock_response = MagicMock()
        mock_response.is_timeout = False
        mock_response.is_error   = False
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response

        result = agent._confirm_destructive_operation()
        assert result is False

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_confirm_destructive_timeout( self, mock_notify, tmp_storage_dir ):
        """_confirm_destructive_operation() returns False on timeout (safe default)."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        mock_response = MagicMock()
        mock_response.is_timeout = True
        mock_response.is_error   = False
        mock_response.response_value = None
        mock_notify.return_value = mock_response

        result = agent._confirm_destructive_operation()
        assert result is False

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_confirm_destructive_error( self, mock_notify, tmp_storage_dir ):
        """_confirm_destructive_operation() returns False on error (safe default)."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        mock_response = MagicMock()
        mock_response.is_timeout = False
        mock_response.is_error   = True
        mock_response.response_value = None
        mock_notify.return_value = mock_response

        result = agent._confirm_destructive_operation()
        assert result is False

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_run_code_cancels_on_denial( self, mock_notify, tmp_storage_dir ):
        """run_code() returns cancelled status when user denies destructive operation."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        mock_response = MagicMock()
        mock_response.is_timeout = False
        mock_response.is_error   = False
        mock_response.response_value = "no"
        mock_notify.return_value = mock_response

        result = agent.run_code()
        assert result[ "return_code" ] == 0
        assert result[ "output" ][ "status" ] == "cancelled"
        assert result[ "output" ][ "message" ] == "Operation cancelled."

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_run_formatter_cancelled_status( self, mock_notify, tmp_storage_dir ):
        """run_formatter() handles cancelled status from denied destructive operation."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        # Simulate a cancelled run_code result
        agent.code_response_dict = {
            "return_code" : 0,
            "output"      : { "status": "cancelled", "message": "Operation cancelled." }
        }

        result = agent.run_formatter()
        assert result == "Operation cancelled."
        assert agent.answer_conversational == "Operation cancelled."
        assert agent.answer == "Operation cancelled."

    @patch( "cosa.crud_for_dataframes.agent.notify_user_sync" )
    def test_run_code_proceeds_on_confirmation( self, mock_notify, tmp_storage_dir ):
        """run_code() proceeds with dispatch when user confirms destructive operation."""
        from cosa.crud_for_dataframes.crud_operations import add_item

        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="delete" )

        # First add an item so delete has something to match
        add_item( agent.storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )

        # Set up intent to delete by match
        agent.crud_intent = CRUDIntent(
            operation    = "delete",
            target_list  = "groceries",
            schema_type  = "todo",
            match_fields = '{"todo_item": "buy milk"}'
        )

        mock_response = MagicMock()
        mock_response.is_timeout = False
        mock_response.is_error   = False
        mock_response.response_value = "yes"
        mock_notify.return_value = mock_response

        result = agent.run_code()
        assert result[ "return_code" ] == 0
        assert result[ "output" ][ "status" ] == "deleted"

    def test_add_operation_skips_confirmation( self, tmp_storage_dir ):
        """run_code() skips confirmation for non-destructive add operation."""
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="add" )

        # No mock for notify_user_sync — if it were called, test would fail
        result = agent.run_code()
        assert result[ "return_code" ] == 0
        assert result[ "output" ][ "status" ] == "added"


# ============================================================================
# TestCrudQueueCompletion — Bug fix: emit_job_state_transition + done queue
# ============================================================================

class TestCrudQueueCompletion:
    """Tests verifying the CRUD agent completion bug fix (Session 158).

    Bug: emit_job_state_transition() and jobs_done_queue.push() were gated
    behind `if serialize_snapshot:`, which is False for CRUD agents. This
    caused UI cards to stay stuck in 'running' state forever.

    Fix: Moved emit_job_state_transition() and jobs_done_queue.push() outside
    the serialize_snapshot gate so they fire for ALL agents.
    """

    def _create_queue_and_agent( self, tmp_storage_dir ):
        """Helper: Create a minimal RunningFifoQueue + CRUD agent for completion tests."""
        import threading
        from collections import OrderedDict
        from cosa.rest.running_fifo_queue import RunningFifoQueue

        queue = RunningFifoQueue.__new__( RunningFifoQueue )
        queue.debug           = True
        queue.verbose         = False
        queue.websocket_mgr   = MagicMock()
        queue.snapshot_mgr    = MagicMock()
        queue.jobs_done_queue = MagicMock()
        queue.jobs_dead_queue = MagicMock()
        queue.io_tbl          = MagicMock()
        queue.gist_normalizer = MagicMock()
        queue.user_job_tracker = MagicMock()
        # Phase 1 (RLock) + Phase 2 (pool) require these attributes normally set
        # by FifoQueue.__init__ / RunningFifoQueue.__init__. Since the test uses
        # __new__ to skip __init__, set them manually here.
        queue._lock           = threading.RLock()
        queue.queue_list      = [ ]
        queue.queue_dict      = OrderedDict()
        queue.push_counter    = 0
        queue.last_queue_size = 0
        queue._blocking_object = None
        queue._accepting_jobs  = True
        queue._agentic_futures      = { }
        queue._agentic_futures_lock = threading.RLock()

        # Create a CRUD agent that has already completed do_all()
        agent = _create_mock_agent( tmp_dir=tmp_storage_dir, operation="add" )

        # Simulate successful pipeline completion (code_ran_to_completion + formatter_ran_to_completion)
        agent.code_response_dict = { "return_code": 0, "output": { "status": "added", "message": "Added item" } }
        agent.answer_conversational = "I added buy milk to your grocery list."
        agent.answer                = "I added buy milk to your grocery list."
        agent.id_hash               = "test-hash-123"
        agent.run_date              = "2026-02-09"
        agent.push_counter          = 1
        agent.routing_command       = "agent router go to crud for dataframes"
        agent.is_cache_hit          = False
        agent.started_at            = "2026-02-09T22:00:00"
        agent.session_id            = "test-session"

        # Mock do_all() to skip real LLM pipeline — agent attributes already set to final state
        agent.do_all                      = MagicMock( return_value="I added buy milk to your grocery list." )
        agent.code_ran_to_completion      = MagicMock( return_value=True )
        agent.formatter_ran_to_completion = MagicMock( return_value=True )

        return queue, agent

    @patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" )
    def test_crud_agent_emits_job_state_transition( self, mock_emit, tmp_storage_dir ):
        """CRUD agent triggers emit_job_state_transition with 'run' -> 'done' after completion."""
        queue, agent = self._create_queue_and_agent( tmp_storage_dir )

        # Mock pop() to avoid queue internals
        queue.pop = MagicMock()

        # Mock _notify to avoid notification service
        queue._notify = MagicMock()

        timer = MagicMock()
        timer.print = MagicMock()

        result = queue._handle_base_agent( agent, "add buy milk...", timer )

        # Verify emit was called with 'run' -> 'done'
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[ 0 ][ 0 ] == queue.websocket_mgr     # websocket_mgr
        assert call_args[ 0 ][ 1 ] == "test-hash-123"          # job_id
        assert call_args[ 0 ][ 2 ] == JobState.RUNNING            # from_state
        assert call_args[ 0 ][ 3 ] == JobState.COMPLETED        # to_state
        assert call_args[ 0 ][ 4 ] == "test@example.com"       # user_id

        # Verify metadata contains expected fields
        metadata = call_args[ 0 ][ 5 ]
        assert metadata[ 'status' ] == 'completed'
        assert metadata[ 'response_text' ] == "I added buy milk to your grocery list."
        assert metadata[ 'agent_type' ] is not None

    @patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" )
    def test_crud_agent_answer_not_overwritten( self, mock_emit, tmp_storage_dir ):
        """CRUD agent's real answer is preserved, not replaced with canned 'no code executed...' string."""
        queue, agent = self._create_queue_and_agent( tmp_storage_dir )
        queue.pop    = MagicMock()
        queue._notify = MagicMock()

        timer = MagicMock()
        timer.print = MagicMock()

        original_answer = agent.answer

        result = queue._handle_base_agent( agent, "add buy milk...", timer )

        # The answer should still be the CRUD agent's real answer, not the canned string
        assert result.answer == original_answer
        assert "no code executed" not in result.answer

    @patch( "cosa.rest.running_fifo_queue.emit_job_state_transition" )
    def test_crud_agent_pushed_to_done_queue( self, mock_emit, tmp_storage_dir ):
        """CRUD agent is pushed to jobs_done_queue after completion."""
        queue, agent = self._create_queue_and_agent( tmp_storage_dir )
        queue.pop    = MagicMock()
        queue._notify = MagicMock()

        timer = MagicMock()
        timer.print = MagicMock()

        queue._handle_base_agent( agent, "add buy milk...", timer )

        # Verify the agent was pushed to done queue
        queue.jobs_done_queue.push.assert_called_once()
        pushed_job = queue.jobs_done_queue.push.call_args[ 0 ][ 0 ]
        assert isinstance( pushed_job, CrudForDataFramesAgent )
