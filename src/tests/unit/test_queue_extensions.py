"""
Unit tests for UserJobTracker (queue_extensions.py).

Tests register_scoped_job() atomic method and supporting methods.
"""

import pytest
from unittest.mock import patch


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture( autouse=True )
def fresh_tracker():
    """
    Reset UserJobTracker singleton state before each test.

    The singleton pattern means instance data persists across tests unless
    we explicitly clear it.
    """
    from cosa.rest.queue_extensions import UserJobTracker

    tracker = UserJobTracker()
    tracker.job_to_user.clear()
    tracker.user_jobs.clear()
    yield tracker


# ═══════════════════════════════════════════════════════════════════════════════
# register_scoped_job() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegisterScopedJob:
    """Tests for the atomic register_scoped_job() method."""

    def test_returns_scoped_id( self, fresh_tracker ):
        """register_scoped_job returns a properly formatted scoped ID."""
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc123", "user_42" )
        assert scoped_id == "dr-abc123::user_42"

    def test_indexes_job_for_user( self, fresh_tracker ):
        """After registration, get_jobs_for_user returns the scoped ID."""
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc123", "user_42" )
        jobs = fresh_tracker.get_jobs_for_user( "user_42" )
        assert scoped_id in jobs

    def test_job_to_user_mapping( self, fresh_tracker ):
        """After registration, job_to_user maps the scoped ID to user."""
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc123", "user_42" )
        assert fresh_tracker.job_to_user[ scoped_id ] == "user_42"

    def test_multiple_jobs_same_user( self, fresh_tracker ):
        """Multiple jobs for the same user are all indexed."""
        id1 = fresh_tracker.register_scoped_job( "dr-abc", "user_42" )
        id2 = fresh_tracker.register_scoped_job( "pg-def", "user_42" )
        id3 = fresh_tracker.register_scoped_job( "cc-ghi", "user_42" )

        jobs = fresh_tracker.get_jobs_for_user( "user_42" )
        assert len( jobs ) == 3
        assert id1 in jobs
        assert id2 in jobs
        assert id3 in jobs

    def test_different_users_get_different_ids( self, fresh_tracker ):
        """Same base hash for different users produces different scoped IDs."""
        id_a = fresh_tracker.register_scoped_job( "dr-abc", "user_a" )
        id_b = fresh_tracker.register_scoped_job( "dr-abc", "user_b" )

        assert id_a != id_b
        assert id_a == "dr-abc::user_a"
        assert id_b == "dr-abc::user_b"

        # Each user sees only their own job
        assert id_a in fresh_tracker.get_jobs_for_user( "user_a" )
        assert id_b not in fresh_tracker.get_jobs_for_user( "user_a" )
        assert id_b in fresh_tracker.get_jobs_for_user( "user_b" )

    def test_idempotent_scoping( self, fresh_tracker ):
        """Passing an already-scoped hash does not double-scope."""
        # First registration
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc", "user_42" )
        assert scoped_id == "dr-abc::user_42"

        # Passing scoped ID again should strip the old scope first
        re_scoped = fresh_tracker.register_scoped_job( scoped_id, "user_42" )
        assert re_scoped == "dr-abc::user_42"

    def test_remove_after_register( self, fresh_tracker ):
        """remove_job cleans up a registered scoped job."""
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc", "user_42" )
        assert len( fresh_tracker.get_jobs_for_user( "user_42" ) ) == 1

        fresh_tracker.remove_job( scoped_id )
        assert len( fresh_tracker.get_jobs_for_user( "user_42" ) ) == 0
        assert scoped_id not in fresh_tracker.job_to_user

    def test_session_id_ignored( self, fresh_tracker ):
        """session_id parameter is accepted but has no side effects."""
        # register_scoped_job no longer tracks sessions (Phase 4 removes session dicts)
        scoped_id = fresh_tracker.register_scoped_job( "dr-abc", "user_42", session_id="ws-session-1" )
        assert scoped_id == "dr-abc::user_42"
        assert scoped_id in fresh_tracker.get_jobs_for_user( "user_42" )


# ═══════════════════════════════════════════════════════════════════════════════
# generate_user_scoped_hash() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateUserScopedHash:
    """Tests for the hash generation method."""

    def test_basic_format( self, fresh_tracker ):
        """Returns {base}::{user} format."""
        result = fresh_tracker.generate_user_scoped_hash( "abc123", "user_1" )
        assert result == "abc123::user_1"

    def test_strips_existing_scope( self, fresh_tracker ):
        """Prevents double-scoping by stripping existing :: suffix."""
        result = fresh_tracker.generate_user_scoped_hash( "abc123::old_user", "new_user" )
        assert result == "abc123::new_user"

    def test_deterministic( self, fresh_tracker ):
        """Same inputs always produce same output."""
        r1 = fresh_tracker.generate_user_scoped_hash( "abc", "user" )
        r2 = fresh_tracker.generate_user_scoped_hash( "abc", "user" )
        assert r1 == r2


# ═══════════════════════════════════════════════════════════════════════════════
# get_jobs_for_user() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetJobsForUser:
    """Tests for the reverse-index lookup method."""

    def test_empty_for_unknown_user( self, fresh_tracker ):
        """Returns empty list for user with no jobs."""
        assert fresh_tracker.get_jobs_for_user( "nonexistent" ) == []

    def test_returns_copy( self, fresh_tracker ):
        """Returns a copy so external mutation doesn't affect internal state."""
        fresh_tracker.register_scoped_job( "dr-abc", "user_1" )
        jobs = fresh_tracker.get_jobs_for_user( "user_1" )
        jobs.append( "injected" )  # Mutate the copy

        # Internal state should be unaffected
        assert "injected" not in fresh_tracker.get_jobs_for_user( "user_1" )
