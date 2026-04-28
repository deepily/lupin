"""
Unit Tests for CJ Flow Job Persistence

Tests the job_persistence module (is_agentic_job_type, _build_metadata_json,
persist functions) and the persistence dispatch logic in queue_util.py.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime, timezone

from cosa.rest.job_state import JobState


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
        emit_job_state_transition( None, "job-1", JobState.PENDING, JobState.QUEUED, user_id="user_1", metadata=metadata )

        mock_persist.assert_called_once_with( "job-1", "user_1", metadata )

    @patch( "cosa.rest.queue_util.persist_job_started_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_todo_to_run_calls_started( self, mock_is_agentic, mock_persist ):
        """todo→run transition calls persist_job_started_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "podcast" }
        emit_job_state_transition( None, "job-2", JobState.QUEUED, JobState.RUNNING, metadata=metadata )

        mock_persist.assert_called_once_with( "job-2", metadata )

    @patch( "cosa.rest.queue_util.persist_job_completed_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_run_to_done_calls_completed( self, mock_is_agentic, mock_persist ):
        """run→done transition calls persist_job_completed_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "claude_code", "response_text": "Done" }
        emit_job_state_transition( None, "job-3", JobState.RUNNING, JobState.COMPLETED, metadata=metadata )

        mock_persist.assert_called_once_with( "job-3", metadata )

    @patch( "cosa.rest.queue_util.persist_job_failed_from_metadata" )
    @patch( "cosa.rest.queue_util.is_agentic_job_type", return_value=True )
    def test_run_to_dead_calls_failed( self, mock_is_agentic, mock_persist ):
        """run→dead transition calls persist_job_failed_from_metadata."""
        from cosa.rest.queue_util import emit_job_state_transition

        metadata = { "agent_type": "swe_team", "error": "timeout" }
        emit_job_state_transition( None, "job-4", JobState.RUNNING, JobState.FAILED, metadata=metadata )

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
        emit_job_state_transition( None, "job-5", JobState.RUNNING, JobState.COMPLETED, metadata=metadata )

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

        emit_job_state_transition( None, "job-6", JobState.RUNNING, JobState.COMPLETED, metadata=None )

        mock_created.assert_not_called()
        mock_started.assert_not_called()
        mock_completed.assert_not_called()
        mock_failed.assert_not_called()


# ===========================================================================
# Tests for delete_job_history()
# ===========================================================================

class TestDeleteJobHistory:
    """Tests for the delete_job_history function."""

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_delete_existing_row( self, mock_get_db ):
        """delete_job_history returns True when a row is deleted (rowcount > 0)."""
        from cosa.rest.job_persistence import delete_job_history

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.rowcount = 1

        result = delete_job_history( "job-abc::user_123" )

        assert result is True
        mock_session.commit.assert_called_once()

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_delete_nonexistent_row( self, mock_get_db ):
        """delete_job_history returns False when no row is found (rowcount == 0)."""
        from cosa.rest.job_persistence import delete_job_history

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.rowcount = 0

        result = delete_job_history( "nonexistent-id" )

        assert result is False

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_delete_fires_and_forgets( self, mock_get_db ):
        """DB failure does not propagate — returns False instead of raising."""
        from cosa.rest.job_persistence import delete_job_history

        mock_get_db.side_effect = Exception( "DB connection refused" )

        result = delete_job_history( "job-abc" )

        assert result is False


# ===========================================================================
# Tests for query_job_history() — days and exclude_ids filters
# ===========================================================================

class TestQueryJobHistoryFilters:
    """Tests for the new days and exclude_ids filters in query_job_history."""

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_days_filter_applies_cutoff( self, mock_get_db ):
        """days=7 adds a created_at >= cutoff filter to the query."""
        from cosa.rest.job_persistence import query_job_history

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        result = query_job_history( days=7 )

        assert result[ "total" ] == 0
        assert result[ "jobs" ] == []
        # The query should have been called with filters (2 execute calls: count + query)
        assert mock_session.execute.call_count == 2

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_exclude_ids_filter( self, mock_get_db ):
        """exclude_ids parameter filters out specified job IDs."""
        from cosa.rest.job_persistence import query_job_history

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        result = query_job_history( exclude_ids=[ "id-a", "id-b" ] )

        assert result[ "total" ] == 0
        assert result[ "jobs" ] == []
        assert mock_session.execute.call_count == 2

    @patch( "cosa.rest.job_persistence.get_db" )
    def test_days_none_no_time_filter( self, mock_get_db ):
        """days=None does not add a time cutoff filter (same as before)."""
        from cosa.rest.job_persistence import query_job_history

        mock_session = MagicMock()
        mock_get_db.return_value.__enter__ = MagicMock( return_value=mock_session )
        mock_get_db.return_value.__exit__ = MagicMock( return_value=False )
        mock_session.execute.return_value.scalar.return_value = 0
        mock_session.execute.return_value.scalars.return_value.all.return_value = []

        result = query_job_history( days=None, exclude_ids=None )

        assert result[ "total" ] == 0
        assert result[ "jobs" ] == []
        assert mock_session.execute.call_count == 2


# ===========================================================================
# Tests for _unpack_metadata_json() — flattens metadata_json into top-level
# fields matching /api/get-queue/done shape (Phase 1 / 2026-04-26)
# ===========================================================================

class TestUnpackMetadataJson:
    """Tests for the metadata_json → flat-shape unpacker."""

    def test_unpacks_full_metadata( self ):
        from cosa.rest.job_persistence import _unpack_metadata_json
        md = {
            "response_text"             : "The answer",
            "abstract"                  : "Summary text",
            "report_path"               : "/reports/r.html",
            "remediation_snapshot_path" : "/snapshots/s.json",
            "yaml_path"                 : "/yaml/y.yaml",
            "pptx_path"                 : "/decks/d.pptx",
            "cost_summary"              : { "total": 0.42 },
            "scheduled_at"              : "2026-04-26T10:00:00",
            "monopolize"                : True
        }
        result = _unpack_metadata_json( md )
        assert result[ "response_text" ]             == "The answer"
        assert result[ "abstract" ]                  == "Summary text"
        assert result[ "report_path" ]               == "/reports/r.html"
        assert result[ "remediation_snapshot_path" ] == "/snapshots/s.json"
        assert result[ "yaml_path" ]                 == "/yaml/y.yaml"
        assert result[ "pptx_path" ]                 == "/decks/d.pptx"
        assert result[ "cost_summary" ]              == { "total": 0.42 }
        assert result[ "scheduled_at" ]              == "2026-04-26T10:00:00"
        assert result[ "monopolize" ]                is True

    def test_handles_none_metadata( self ):
        """metadata_json = None → all fields default to None / False."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        result = _unpack_metadata_json( None )
        assert result[ "response_text" ]             is None
        assert result[ "abstract" ]                  is None
        assert result[ "report_path" ]               is None
        assert result[ "remediation_snapshot_path" ] is None
        assert result[ "yaml_path" ]                 is None
        assert result[ "pptx_path" ]                 is None
        assert result[ "cost_summary" ]              is None
        assert result[ "scheduled_at" ]              is None
        assert result[ "monopolize" ]                is False

    def test_handles_empty_dict( self ):
        """metadata_json = {} → all fields default to None / False."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        result = _unpack_metadata_json( {} )
        assert all( result[ k ] is None for k in [
            "response_text", "abstract", "report_path",
            "remediation_snapshot_path", "yaml_path", "pptx_path",
            "cost_summary", "scheduled_at"
        ] )
        assert result[ "monopolize" ] is False

    def test_handles_partial_metadata( self ):
        """Some keys present → others default."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        md     = { "abstract": "Only abstract" }
        result = _unpack_metadata_json( md )
        assert result[ "abstract" ]      == "Only abstract"
        assert result[ "response_text" ] is None
        assert result[ "report_path" ]   is None

    def test_aligns_report_link_to_report_path( self ):
        """Legacy `report_link` key surfaces as `report_path`."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        md     = { "report_link": "/legacy/r.html" }
        result = _unpack_metadata_json( md )
        assert result[ "report_path" ] == "/legacy/r.html"

    def test_report_path_takes_precedence_over_report_link( self ):
        """Newer `report_path` key wins over legacy `report_link` when both present."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        md     = { "report_path": "/new/r.html", "report_link": "/old/r.html" }
        result = _unpack_metadata_json( md )
        assert result[ "report_path" ] == "/new/r.html"

    def test_response_text_falls_back_to_answer_conversational( self ):
        """When response_text missing, use legacy answer_conversational."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        md     = { "answer_conversational": "Conversational answer" }
        result = _unpack_metadata_json( md )
        assert result[ "response_text" ] == "Conversational answer"

    def test_response_text_takes_precedence_over_legacy( self ):
        """Newer response_text wins over answer_conversational when both present."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        md     = { "response_text": "New answer", "answer_conversational": "Old answer" }
        result = _unpack_metadata_json( md )
        assert result[ "response_text" ] == "New answer"

    def test_monopolize_coerced_to_bool( self ):
        """monopolize value is coerced through bool() for safety."""
        from cosa.rest.job_persistence import _unpack_metadata_json
        assert _unpack_metadata_json( { "monopolize": True  } )[ "monopolize" ] is True
        assert _unpack_metadata_json( { "monopolize": False } )[ "monopolize" ] is False
        assert _unpack_metadata_json( { "monopolize": 1     } )[ "monopolize" ] is True
        assert _unpack_metadata_json( { "monopolize": 0     } )[ "monopolize" ] is False
        assert _unpack_metadata_json( { "monopolize": None  } )[ "monopolize" ] is False


# ===========================================================================
# Tests for _build_history_row() — assembles flat dict matching done-bucket shape
# ===========================================================================

class TestBuildHistoryRow:
    """Tests for the history-row → flat-dict builder."""

    def _make_row( self, **overrides ):
        """Build a mock JobHistory row with sensible defaults."""
        row = MagicMock()
        # ISO-string fields use real datetime so .isoformat() works
        row.created_at      = datetime( 2026, 4, 26, 10, 0, 0, tzinfo=timezone.utc )
        row.started_at      = datetime( 2026, 4, 26, 10, 1, 0, tzinfo=timezone.utc )
        row.completed_at    = datetime( 2026, 4, 26, 10, 2, 0, tzinfo=timezone.utc )
        row.updated_at      = datetime( 2026, 4, 26, 10, 2, 0, tzinfo=timezone.utc )
        # Plain attributes
        row.id_hash         = overrides.get( "id_hash",         "test-job-1" )
        row.job_type        = overrides.get( "job_type",        "deep_research" )
        row.user_id         = overrides.get( "user_id",         "user-uuid-1" )
        row.user_email      = overrides.get( "user_email",      "u@example.com" )
        row.session_id      = overrides.get( "session_id",      "sess-1" )
        row.routing_command = overrides.get( "routing_command", "agent router go to deep research" )
        row.status          = overrides.get( "status",          "completed" )
        row.question_text   = overrides.get( "question_text",   "What is X?" )
        row.error           = overrides.get( "error",           None )
        row.is_cache_hit    = overrides.get( "is_cache_hit",    False )
        row.duration_seconds= overrides.get( "duration_seconds",60.0 )
        row.metadata_json   = overrides.get( "metadata_json",   {
            "response_text" : "Answer",
            "abstract"      : "Summary",
            "report_path"   : "/reports/r.html",
            "cost_summary"  : { "total": 1.23 },
            "scheduled_at"  : "2026-04-26T10:00:00",
            "monopolize"    : True
        } )
        return row

    def test_top_level_fields_match_done_shape( self ):
        from cosa.rest.job_persistence import _build_history_row
        row    = self._make_row()
        result = _build_history_row( row, has_interactions=True )
        # Identity + parity aliases
        assert result[ "id_hash" ]          == "test-job-1"
        assert result[ "job_id" ]           == "test-job-1"   # parity alias
        assert result[ "job_type" ]         == "deep_research"
        assert result[ "agent_type" ]       == "deep_research"  # parity alias
        # Column fields
        assert result[ "user_id" ]          == "user-uuid-1"
        assert result[ "user_email" ]       == "u@example.com"
        assert result[ "session_id" ]       == "sess-1"
        assert result[ "status" ]           == "completed"
        assert result[ "question_text" ]    == "What is X?"
        assert result[ "is_cache_hit" ]     is False
        assert result[ "duration_seconds" ] == 60.0
        # Flattened metadata
        assert result[ "response_text" ]    == "Answer"
        assert result[ "abstract" ]         == "Summary"
        assert result[ "report_path" ]      == "/reports/r.html"
        assert result[ "cost_summary" ]     == { "total": 1.23 }
        assert result[ "scheduled_at" ]     == "2026-04-26T10:00:00"
        assert result[ "monopolize" ]       is True

    def test_has_interactions_passed_through( self ):
        from cosa.rest.job_persistence import _build_history_row
        row = self._make_row()
        assert _build_history_row( row, has_interactions=True  )[ "has_interactions" ] is True
        assert _build_history_row( row, has_interactions=False )[ "has_interactions" ] is False

    def test_paused_always_false( self ):
        """History is terminal — paused is always False regardless of metadata."""
        from cosa.rest.job_persistence import _build_history_row
        row    = self._make_row( metadata_json={ "paused": True } )  # even if metadata says True
        result = _build_history_row( row, has_interactions=False )
        assert result[ "paused" ] is False

    def test_metadata_json_retained_for_backward_compat( self ):
        """Top-level fields unpacked AND metadata_json still in response."""
        from cosa.rest.job_persistence import _build_history_row
        md     = { "response_text": "X", "abstract": "Y" }
        row    = self._make_row( metadata_json=md )
        result = _build_history_row( row, has_interactions=False )
        assert result[ "metadata_json" ] == md
        # And top-level too:
        assert result[ "response_text" ] == "X"
        assert result[ "abstract" ]      == "Y"

    def test_handles_none_metadata_json( self ):
        from cosa.rest.job_persistence import _build_history_row
        row    = self._make_row( metadata_json=None )
        result = _build_history_row( row, has_interactions=False )
        # All flattened fields should be defaults
        assert result[ "response_text" ] is None
        assert result[ "report_path" ]   is None
        assert result[ "monopolize" ]    is False
        assert result[ "metadata_json" ] is None

    def test_timestamp_field_prefers_completed_at( self ):
        """`timestamp` (parity alias) prefers completed_at, falls back to created_at."""
        from cosa.rest.job_persistence import _build_history_row
        row    = self._make_row()
        result = _build_history_row( row, has_interactions=False )
        # completed_at is set, so timestamp should match it (ISO)
        assert result[ "timestamp" ] == row.completed_at.isoformat()

    def test_timestamp_falls_back_when_no_completed( self ):
        from cosa.rest.job_persistence import _build_history_row
        row    = self._make_row()
        row.completed_at = None
        result = _build_history_row( row, has_interactions=False )
        assert result[ "timestamp" ] == row.created_at.isoformat()


# ===========================================================================
# Tests for _count_notifications_for_jobs() — bulk count helper
# ===========================================================================

class TestCountNotificationsForJobs:
    """Tests for the bulk notification-count helper."""

    def test_empty_input_returns_empty_dict_no_query( self ):
        from cosa.rest.job_persistence import _count_notifications_for_jobs
        mock_session = MagicMock()
        result = _count_notifications_for_jobs( mock_session, [] )
        assert result == {}
        # No query should have been issued
        mock_session.query.assert_not_called()

    def test_returns_zero_for_unknown_job_ids( self ):
        """Even when DB returns no rows, every input id is in the result with 0."""
        from cosa.rest.job_persistence import _count_notifications_for_jobs
        mock_session = MagicMock()
        # Configure query chain to return no rows
        mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = []

        result = _count_notifications_for_jobs( mock_session, [ "id-a", "id-b" ] )
        assert result == { "id-a": 0, "id-b": 0 }

    def test_returns_actual_counts( self ):
        from cosa.rest.job_persistence import _count_notifications_for_jobs
        mock_session = MagicMock()
        # Mock DB rows: each row has .job_id and .count attributes
        row_a = MagicMock(); row_a.job_id = "id-a"; row_a.count = 3
        row_b = MagicMock(); row_b.job_id = "id-b"; row_b.count = 7
        mock_session.query.return_value.filter.return_value.group_by.return_value.all.return_value = [ row_a, row_b ]

        result = _count_notifications_for_jobs( mock_session, [ "id-a", "id-b", "id-c" ] )
        assert result == { "id-a": 3, "id-b": 7, "id-c": 0 }

    def test_returns_empty_dict_on_db_error( self ):
        """Database failure is logged and returns empty dict (caller treats as all-zero)."""
        from cosa.rest.job_persistence import _count_notifications_for_jobs
        mock_session = MagicMock()
        mock_session.query.side_effect = Exception( "DB error" )

        result = _count_notifications_for_jobs( mock_session, [ "id-a", "id-b" ] )
        assert result == {}
