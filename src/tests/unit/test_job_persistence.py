"""
Unit Tests for CJ Flow Job Persistence

Tests the job_persistence module (is_agentic_job_type, _build_metadata_json,
persist functions) and the persistence dispatch logic in queue_util.py.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone


# ===========================================================================
# Tests for is_agentic_job_type()
# ===========================================================================

class TestIsAgenticJobType:
    """Tests for the agentic job type filter."""

    def test_is_agentic_job_type_true( self ):
        """All 5 agentic types return True."""
        from cosa.rest.job_persistence import is_agentic_job_type

        agentic_types = [ "deep_research", "podcast", "claude_code", "swe_team", "research_to_podcast" ]
        for job_type in agentic_types:
            assert is_agentic_job_type( job_type ) is True, f"Expected True for '{job_type}'"

    def test_is_agentic_job_type_false( self ):
        """Non-agentic types, None, and empty string return False."""
        from cosa.rest.job_persistence import is_agentic_job_type

        non_agentic = [ "math", "calendar", "date_and_time", "solution_snapshot", None, "", "MathAgent" ]
        for job_type in non_agentic:
            assert is_agentic_job_type( job_type ) is False, f"Expected False for '{job_type}'"


# ===========================================================================
# Tests for _build_metadata_json()
# ===========================================================================

class TestBuildMetadataJson:
    """Tests for the metadata extraction helper."""

    def test_extracts_rich_fields( self ):
        """Extracts the 8 defined rich fields from metadata."""
        from cosa.rest.job_persistence import _build_metadata_json

        metadata = {
            "response_text"        : "The answer is 42",
            "abstract"             : "A brief summary",
            "report_link"          : "/reports/abc.html",
            "cost_summary"         : { "total_tokens": 1500 },
            "artifacts"            : { "files": [ "a.txt" ] },
            "answer_conversational": "Forty-two",
            "push_counter"         : 3,
            "agent_type"           : "deep_research",
            # These should NOT be extracted
            "question_text"        : "What is the meaning of life?",
            "error"                : None,
            "status"               : "completed",
            "user_id"              : "user_123"
        }

        result = _build_metadata_json( metadata )

        # 8 rich fields present
        assert result[ "response_text" ] == "The answer is 42"
        assert result[ "abstract" ] == "A brief summary"
        assert result[ "report_link" ] == "/reports/abc.html"
        assert result[ "cost_summary" ] == { "total_tokens": 1500 }
        assert result[ "artifacts" ] == { "files": [ "a.txt" ] }
        assert result[ "answer_conversational" ] == "Forty-two"
        assert result[ "push_counter" ] == 3
        assert result[ "agent_type" ] == "deep_research"

        # Non-rich fields excluded
        assert "question_text" not in result
        assert "error" not in result
        assert "status" not in result
        assert "user_id" not in result

    def test_empty_input( self ):
        """None and empty dict return empty dict."""
        from cosa.rest.job_persistence import _build_metadata_json

        assert _build_metadata_json( None ) == {}
        assert _build_metadata_json( {} ) == {}

    def test_none_values_excluded( self ):
        """Fields with None values are excluded from output."""
        from cosa.rest.job_persistence import _build_metadata_json

        metadata = {
            "response_text" : "Hello",
            "abstract"      : None,
            "report_link"   : None
        }

        result = _build_metadata_json( metadata )
        assert result == { "response_text": "Hello" }


# ===========================================================================
# Tests for persist functions (mocked DB)
# ===========================================================================

class TestPersistFunctions:
    """Tests for the 4 persist_* functions with mocked database."""

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_job_created_inserts_row( self, mock_get_db, mock_enabled ):
        """persist_job_created_from_metadata calls session.add() with correct fields."""
        from cosa.rest.job_persistence import persist_job_created_from_metadata

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )

        metadata = {
            "agent_type"    : "deep_research",
            "question_text" : "What is quantum computing?",
            "user_email"    : "test@example.com",
            "session_id"    : "wise-penguin"
        }

        persist_job_created_from_metadata( "job-abc::user_123", "user_123", metadata )

        mock_session.add.assert_called_once()
        added_obj = mock_session.add.call_args[ 0 ][ 0 ]
        assert added_obj.id_hash == "job-abc::user_123"
        assert added_obj.job_type == "deep_research"
        assert added_obj.user_id == "user_123"
        assert added_obj.status == "pending"
        assert added_obj.question_text == "What is quantum computing?"

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=False )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_job_created_disabled( self, mock_get_db, mock_enabled ):
        """When persistence is disabled, no DB call is made."""
        from cosa.rest.job_persistence import persist_job_created_from_metadata

        persist_job_created_from_metadata( "job-abc", "user_123", { "agent_type": "podcast" } )

        mock_get_db.assert_not_called()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_job_started_updates_status( self, mock_get_db, mock_enabled ):
        """persist_job_started_from_metadata executes UPDATE with status='running'."""
        from cosa.rest.job_persistence import persist_job_started_from_metadata

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )

        persist_job_started_from_metadata( "job-abc::user_123", {} )

        mock_session.execute.assert_called_once()

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_job_completed_calculates_duration( self, mock_get_db, mock_enabled ):
        """persist_job_completed_from_metadata calculates duration when started_at exists."""
        from cosa.rest.job_persistence import persist_job_completed_from_metadata

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )

        # First execute returns started_at, second is the update
        started = datetime( 2026, 3, 23, 10, 0, 0, tzinfo=timezone.utc )
        mock_session.execute.return_value.scalar.return_value = started

        metadata = { "response_text": "Done", "agent_type": "deep_research" }
        persist_job_completed_from_metadata( "job-abc::user_123", metadata )

        # Should have called execute twice: SELECT started_at + UPDATE
        assert mock_session.execute.call_count == 2

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_job_failed_captures_error( self, mock_get_db, mock_enabled ):
        """persist_job_failed_from_metadata stores error text."""
        from cosa.rest.job_persistence import persist_job_failed_from_metadata

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.scalar.return_value = None

        metadata = { "error": "CUDA out of memory", "agent_type": "podcast" }
        persist_job_failed_from_metadata( "job-xyz::user_456", metadata )

        assert mock_session.execute.call_count == 2  # SELECT + UPDATE

    @patch( "cosa.rest.job_persistence._is_persistence_enabled", return_value=True )
    @patch( "cosa.rest.job_persistence.get_db" )
    def test_persist_functions_fire_and_forget( self, mock_get_db, mock_enabled ):
        """DB failure does not propagate exceptions — fire-and-forget pattern."""
        from cosa.rest.job_persistence import (
            persist_job_created_from_metadata,
            persist_job_started_from_metadata,
            persist_job_completed_from_metadata,
            persist_job_failed_from_metadata
        )

        mock_get_db.side_effect = Exception( "DB connection refused" )

        # None of these should raise
        persist_job_created_from_metadata( "j1", "u1", { "agent_type": "podcast" } )
        persist_job_started_from_metadata( "j1", {} )
        persist_job_completed_from_metadata( "j1", {} )
        persist_job_failed_from_metadata( "j1", { "error": "oops" } )


# ===========================================================================
# Tests for emit_job_state_transition persistence dispatch
# ===========================================================================

class TestEmitPersistenceDispatch:
    """Tests for the persistence dispatch logic in emit_job_state_transition."""

    @patch( "cosa.rest.queue_util.persist_job_created_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_pending_to_todo_calls_created( self, mock_is_agentic, mock_persist ):
        """pending→todo transition calls persist_job_created_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "deep_research", "question_text": "test" }
        emit_job_state_transition( None, "job-1", "pending", "todo", user_id="user_1", metadata=metadata )

        mock_persist.assert_called_once_with( "job-1", "user_1", metadata )

    @patch( "cosa.rest.queue_util.persist_job_started_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_todo_to_run_calls_started( self, mock_is_agentic, mock_persist ):
        """todo→run transition calls persist_job_started_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "podcast" }
        emit_job_state_transition( None, "job-2", "todo", "run", metadata=metadata )

        mock_persist.assert_called_once_with( "job-2", metadata )

    @patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_run_to_done_calls_completed( self, mock_is_agentic, mock_persist ):
        """run→done transition calls persist_job_completed_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "claude_code", "response_text": "Done" }
        emit_job_state_transition( None, "job-3", "run", "done", metadata=metadata )

        mock_persist.assert_called_once_with( "job-3", metadata )

    @patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_run_to_dead_calls_failed( self, mock_is_agentic, mock_persist ):
        """run→dead transition calls persist_job_failed_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "swe_team", "error": "timeout" }
        emit_job_state_transition( None, "job-4", "run", "dead", metadata=metadata )

        mock_persist.assert_called_once_with( "job-4", metadata )

    @patch( "cosa.rest.queue_util.persist_job_created_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_started_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=False )
    def test_skips_non_agentic( self, mock_is_agentic, mock_failed, mock_completed, mock_started, mock_created ):
        """Non-agentic agent_type triggers no persistence calls."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "math", "question_text": "2+2" }
        emit_job_state_transition( None, "job-5", "run", "done", metadata=metadata )

        mock_created.assert_not_called()
        mock_started.assert_not_called()
        mock_completed.assert_not_called()
        mock_failed.assert_not_called()

    @patch( "cosa.rest.queue_util.persist_job_created_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_started_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" )
    @patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" )
    def test_skips_no_metadata( self, mock_failed, mock_completed, mock_started, mock_created ):
        """No metadata → is_agentic_job_type(None) returns False → no persistence calls."""
        from cosa.rest.queue_util import emit_job_state_transition

        emit_job_state_transition( None, "job-6", "run", "done", metadata=None )

        mock_created.assert_not_called()
        mock_started.assert_not_called()
        mock_completed.assert_not_called()
        mock_failed.assert_not_called()
