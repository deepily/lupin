"""
Unit tests for SweTeamJob — Surface 2 of the SWE Team testing plan.

Tests job construction, last_question_asked formatting, dry_run execution,
error handling, QueueableJob protocol compliance, and factory registration.

All tests run without a server (pure unit tests).
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from cosa.agents.swe_team.job import SweTeamJob
from cosa.agents.agentic_job_base import AgenticJobBase
from cosa.rest.queue_protocol import QueueableJob
from cosa.rest.agentic_job_factory import create_agentic_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def basic_job():
    """
    Create a basic SweTeamJob with default parameters.

    Ensures:
        - Returns a pending SweTeamJob ready for testing
    """
    return SweTeamJob(
        task       = "Add a health check endpoint",
        user_id    = "user123",
        user_email = "test@example.com",
        session_id = "wise-penguin"
    )


@pytest.fixture
def dry_run_job():
    """
    Create a SweTeamJob configured for dry_run mode.

    Ensures:
        - Returns a SweTeamJob with dry_run=True
    """
    return SweTeamJob(
        task       = "Fix the authentication bug in login flow",
        user_id    = "user456",
        user_email = "dev@example.com",
        session_id = "clever-dolphin",
        dry_run    = True,
        debug      = True
    )


@pytest.fixture
def full_params_job():
    """
    Create a SweTeamJob with all optional parameters set.

    Ensures:
        - Returns a SweTeamJob with lead_model, worker_model, budget, timeout
    """
    return SweTeamJob(
        task         = "Refactor the database module",
        user_id      = "user789",
        user_email   = "admin@example.com",
        session_id   = "brave-hawk",
        dry_run      = False,
        lead_model   = "claude-opus-4-20250514",
        worker_model = "claude-sonnet-4-20250514",
        budget       = 5.00,
        timeout      = 1800,
        debug        = True,
        verbose      = True
    )


# ===========================================================================
# Job Construction Tests
# ===========================================================================

class TestJobConstruction:
    """Tests for SweTeamJob instantiation and class constants."""

    def test_job_type_and_prefix( self ):
        """JOB_TYPE should be 'swe_team' and JOB_PREFIX should be 'swe'."""
        assert SweTeamJob.JOB_TYPE == "swe_team"
        assert SweTeamJob.JOB_PREFIX == "swe"

    def test_id_hash_format( self, basic_job ):
        """id_hash should start with 'swe-' and be 12 chars total (swe- + 8 hex)."""
        assert basic_job.id_hash.startswith( "swe-" )
        assert len( basic_job.id_hash ) == 12  # "swe-" (4) + 8 hex chars

    def test_default_attributes( self, basic_job ):
        """Default status should be 'pending', dry_run False, error None."""
        assert basic_job.status == "pending"
        assert basic_job.dry_run is False
        assert basic_job.debug is False
        assert basic_job.error is None
        assert basic_job.started_at is None
        assert basic_job.completed_at is None
        assert basic_job.cost_summary is None

    def test_constructor_stores_params( self, basic_job ):
        """Constructor should store task, user_id, user_email, session_id."""
        assert basic_job.task == "Add a health check endpoint"
        assert basic_job.user_id == "user123"
        assert basic_job.user_email == "test@example.com"
        assert basic_job.session_id == "wise-penguin"

    def test_constructor_stores_optional_params( self, full_params_job ):
        """Constructor should store all optional parameters when provided."""
        assert full_params_job.lead_model == "claude-opus-4-20250514"
        assert full_params_job.worker_model == "claude-sonnet-4-20250514"
        assert full_params_job.budget == 5.00
        assert full_params_job.timeout == 1800
        assert full_params_job.debug is True
        assert full_params_job.verbose is True

    def test_inherits_from_agentic_job_base( self, basic_job ):
        """SweTeamJob should be a subclass of AgenticJobBase."""
        assert isinstance( basic_job, AgenticJobBase )


# ===========================================================================
# last_question_asked Tests
# ===========================================================================

class TestLastQuestionAsked:
    """Tests for the last_question_asked property."""

    def test_long_task_truncates( self ):
        """Tasks longer than 50 chars should be truncated with '...'."""
        long_task = "A" * 60
        job = SweTeamJob(
            task       = long_task,
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1"
        )
        lqa = job.last_question_asked
        assert lqa == f"[SWE Team] {'A' * 50}..."
        assert len( lqa ) == len( "[SWE Team] " ) + 50 + 3  # prefix + 50 chars + "..."

    def test_short_task_passthrough( self ):
        """Short tasks should pass through without truncation."""
        job = SweTeamJob(
            task       = "fix bug",
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1"
        )
        assert job.last_question_asked == "[SWE Team] fix bug"

    def test_exactly_50_chars_no_truncation( self ):
        """Tasks exactly 50 chars should not be truncated."""
        task_50 = "A" * 50
        job = SweTeamJob(
            task       = task_50,
            user_id    = "u1",
            user_email = "t@t.com",
            session_id = "s1"
        )
        assert job.last_question_asked == f"[SWE Team] {task_50}"
        assert "..." not in job.last_question_asked


# ===========================================================================
# do_all() with dry_run Tests
# ===========================================================================

class TestDryRun:
    """Tests for do_all() execution in dry_run mode."""

    @patch( "cosa.agents.swe_team.voice_io.notify", new_callable=AsyncMock )
    def test_dry_run_returns_result( self, mock_notify, dry_run_job ):
        """dry_run should return a non-empty result string."""
        result = dry_run_job.do_all()
        assert result is not None
        assert len( result ) > 0
        assert "Dry run complete" in result

    @patch( "cosa.agents.swe_team.voice_io.notify", new_callable=AsyncMock )
    def test_dry_run_sets_completed( self, mock_notify, dry_run_job ):
        """After dry_run do_all(), status should be 'completed'."""
        dry_run_job.do_all()
        assert dry_run_job.status == "completed"

    @patch( "cosa.agents.swe_team.voice_io.notify", new_callable=AsyncMock )
    def test_dry_run_sets_cost_summary( self, mock_notify, dry_run_job ):
        """After dry_run, cost_summary should be set with zero cost."""
        dry_run_job.do_all()
        assert dry_run_job.cost_summary is not None
        assert dry_run_job.cost_summary[ "total_cost_usd" ] == 0.0
        assert dry_run_job.cost_summary[ "total_input_tokens" ] == 0
        assert dry_run_job.cost_summary[ "total_output_tokens" ] == 0

    @patch( "cosa.agents.swe_team.voice_io.notify", new_callable=AsyncMock )
    def test_dry_run_sets_timestamps( self, mock_notify, dry_run_job ):
        """After dry_run, started_at and completed_at should be set."""
        dry_run_job.do_all()
        assert dry_run_job.started_at is not None
        assert dry_run_job.completed_at is not None

    @patch( "cosa.agents.swe_team.voice_io.notify", new_callable=AsyncMock )
    def test_dry_run_sends_notifications( self, mock_notify, dry_run_job ):
        """dry_run should send breadcrumb notifications."""
        dry_run_job.do_all()
        # 10 phase breadcrumbs + 1 completion = 11 total notify calls
        assert mock_notify.call_count == 11


# ===========================================================================
# Error Handling Tests
# ===========================================================================

class TestErrorHandling:
    """Tests for error handling during do_all() execution."""

    def test_error_sets_failed_status( self, basic_job ):
        """When _execute() raises, status should be 'failed'."""
        with patch.object( basic_job, "_execute", new_callable=AsyncMock, side_effect=RuntimeError( "test error" ) ):
            basic_job.do_all()
            assert basic_job.status == "failed"

    def test_error_stores_message( self, basic_job ):
        """When _execute() raises, error attribute should contain the message."""
        with patch.object( basic_job, "_execute", new_callable=AsyncMock, side_effect=ValueError( "something broke" ) ):
            basic_job.do_all()
            assert basic_job.error == "something broke"

    def test_error_sets_answer_conversational( self, basic_job ):
        """When _execute() raises, answer_conversational should contain the error."""
        with patch.object( basic_job, "_execute", new_callable=AsyncMock, side_effect=RuntimeError( "oops" ) ):
            result = basic_job.do_all()
            assert "failed" in result.lower()
            assert "oops" in result


# ===========================================================================
# QueueableJob Protocol Tests
# ===========================================================================

class TestQueueableJobProtocol:
    """Tests for QueueableJob protocol compliance."""

    def test_protocol_compliance( self, basic_job ):
        """SweTeamJob should pass isinstance check for QueueableJob."""
        assert isinstance( basic_job, QueueableJob )

    def test_all_protocol_attributes_present( self, basic_job ):
        """All QueueableJob protocol attributes should be accessible."""
        # Identity
        assert hasattr( basic_job, "id_hash" )
        assert hasattr( basic_job, "push_counter" )

        # Ownership/Routing
        assert hasattr( basic_job, "user_id" )
        assert hasattr( basic_job, "session_id" )
        assert hasattr( basic_job, "routing_command" )
        assert hasattr( basic_job, "user_email" )

        # Timestamps
        assert hasattr( basic_job, "run_date" )
        assert hasattr( basic_job, "created_date" )
        assert hasattr( basic_job, "started_at" )
        assert hasattr( basic_job, "completed_at" )

        # Question/Answer
        assert hasattr( basic_job, "question" )
        assert hasattr( basic_job, "last_question_asked" )
        assert hasattr( basic_job, "answer" )
        assert hasattr( basic_job, "answer_conversational" )

        # Type identification
        assert hasattr( basic_job, "job_type" )
        assert basic_job.job_type == "swe_team"

        # Status
        assert hasattr( basic_job, "is_cache_hit" )
        assert hasattr( basic_job, "status" )
        assert hasattr( basic_job, "error" )

        # Methods
        assert callable( basic_job.do_all )
        assert callable( basic_job.code_ran_to_completion )
        assert callable( basic_job.formatter_ran_to_completion )


# ===========================================================================
# Factory Registration Test
# ===========================================================================

class TestFactoryRegistration:
    """Tests for agentic_job_factory registration."""

    def test_factory_creates_swe_team_job( self ):
        """create_agentic_job with 'agent router go to swe team' should return SweTeamJob."""
        job = create_agentic_job(
            command    = "agent router go to swe team",
            args_dict  = { "task": "Implement feature X" },
            user_id    = "factory_user",
            user_email = "factory@example.com",
            session_id = "factory-session"
        )
        assert job is not None
        assert isinstance( job, SweTeamJob )
        assert job.task == "Implement feature X"
        assert job.user_id == "factory_user"

    def test_factory_accepts_prompt_key( self ):
        """Factory should accept 'prompt' as fallback for 'task' key."""
        job = create_agentic_job(
            command    = "agent router go to swe team",
            args_dict  = { "prompt": "Fix the bug" },
            user_id    = "u1",
            user_email = "u1@test.com",
            session_id = "s1"
        )
        assert job is not None
        assert job.task == "Fix the bug"

    def test_factory_passes_optional_params( self ):
        """Factory should pass through dry_run, budget, timeout, and model params."""
        job = create_agentic_job(
            command    = "agent router go to swe team",
            args_dict  = {
                "task"         : "Test task",
                "dry_run"      : True,
                "budget"       : "3.50",
                "timeout"      : "900",
                "lead_model"   : "test-lead",
                "worker_model" : "test-worker",
            },
            user_id    = "u1",
            user_email = "u1@test.com",
            session_id = "s1"
        )
        assert job.dry_run is True
        assert job.budget == 3.50
        assert job.timeout == 900
        assert job.lead_model == "test-lead"
        assert job.worker_model == "test-worker"
