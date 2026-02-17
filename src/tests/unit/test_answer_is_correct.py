"""
Unit tests for SolutionSnapshot.answer_is_correct tri-state field.

Tests the answer_is_correct field across SolutionSnapshot construction,
for_current_user preservation, get_copy preservation, and LanceDB round-trip
serialization/deserialization.
"""

import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from collections import OrderedDict

from cosa.memory.solution_snapshot import SolutionSnapshot


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_minimal_snapshot( answer_is_correct=None, **kwargs ):
    """Create a minimal SolutionSnapshot with mocked embeddings to avoid GPU/API calls."""
    defaults = {
        "question"           : "What is 2 + 2?",
        "question_normalized": "what is 2 + 2",
        "question_gist"      : "basic addition",
        "answer"             : "4",
        "answer_conversational" : "The answer is 4.",
        "routing_command"    : "agent router go to math",
        "agent_class_name"   : "MathAgent",
        "id_hash"            : "test_hash_abc123",
        "answer_is_correct"  : answer_is_correct,
        # Pre-supply embeddings to prevent regeneration
        "question_embedding"            : [ 0.1 ] * 768,
        "question_normalized_embedding" : [ 0.1 ] * 768,
        "question_gist_embedding"       : [ 0.1 ] * 768,
        "solution_embedding"            : [ 0.1 ] * 768,
        "code_embedding"                : [ 0.1 ] * 768,
        "thoughts_embedding"            : [ 0.1 ] * 768,
        "solution_gist_embedding"       : [ 0.1 ] * 768,
    }
    defaults.update( kwargs )
    return SolutionSnapshot( **defaults )


# ─── SolutionSnapshot field tests ───────────────────────────────────────────

class TestAnswerIsCorrectField:
    """Test the answer_is_correct field on SolutionSnapshot."""

    def test_default_is_none( self ):
        """SolutionSnapshot defaults to answer_is_correct=None."""
        snap = _make_minimal_snapshot()
        assert snap.answer_is_correct is None

    def test_accepts_true( self ):
        """SolutionSnapshot accepts answer_is_correct=True."""
        snap = _make_minimal_snapshot( answer_is_correct=True )
        assert snap.answer_is_correct is True

    def test_accepts_false( self ):
        """SolutionSnapshot accepts answer_is_correct=False."""
        snap = _make_minimal_snapshot( answer_is_correct=False )
        assert snap.answer_is_correct is False

    def test_for_current_user_preserves_none( self ):
        """for_current_user() preserves answer_is_correct=None."""
        snap = _make_minimal_snapshot( answer_is_correct=None )
        copy = snap.for_current_user( user_id="other_user", session_id="other_session" )
        assert copy.answer_is_correct is None

    def test_for_current_user_preserves_true( self ):
        """for_current_user() preserves answer_is_correct=True."""
        snap = _make_minimal_snapshot( answer_is_correct=True )
        copy = snap.for_current_user( user_id="other_user", session_id="other_session" )
        assert copy.answer_is_correct is True

    def test_for_current_user_preserves_false( self ):
        """for_current_user() preserves answer_is_correct=False."""
        snap = _make_minimal_snapshot( answer_is_correct=False )
        copy = snap.for_current_user( user_id="other_user", session_id="other_session" )
        assert copy.answer_is_correct is False

    def test_get_copy_preserves_value( self ):
        """get_copy() preserves answer_is_correct value."""
        snap = _make_minimal_snapshot( answer_is_correct=True )
        copy = snap.get_copy( user_email="test@example.com" )
        assert copy.answer_is_correct is True

    def test_get_copy_preserves_none( self ):
        """get_copy() preserves answer_is_correct=None."""
        snap = _make_minimal_snapshot( answer_is_correct=None )
        copy = snap.get_copy( user_email="test@example.com" )
        assert copy.answer_is_correct is None


# ─── LanceDB serialization round-trip tests ─────────────────────────────────

class TestAnswerIsCorrectLanceDB:
    """Test answer_is_correct round-trips through LanceDB serialization."""

    @pytest.fixture
    def manager( self ):
        """Create a LanceDBSolutionManager with a temporary database."""
        from cosa.memory.lancedb_solution_manager import LanceDBSolutionManager

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = {
                "storage_backend" : "local",
                "db_path"         : f"{tmp_dir}/test.lancedb",
                "table_name"      : "test_snapshots"
            }
            mgr = LanceDBSolutionManager( config, debug=False )
            mgr.initialize()
            yield mgr

    def _round_trip( self, manager, snapshot ):
        """Save a snapshot and retrieve it by question."""
        manager.save_snapshot( snapshot )
        results = manager.get_snapshots_by_question( snapshot.question )
        assert results and len( results ) > 0, "Expected at least one result from round-trip"
        _score, loaded = results[ 0 ]
        return loaded

    def test_round_trip_none( self, manager ):
        """LanceDB round-trip preserves answer_is_correct=None."""
        snap = _make_minimal_snapshot( answer_is_correct=None, id_hash="rt_none_001" )
        loaded = self._round_trip( manager, snap )
        assert loaded.answer_is_correct is None

    def test_round_trip_true( self, manager ):
        """LanceDB round-trip preserves answer_is_correct=True."""
        snap = _make_minimal_snapshot( answer_is_correct=True, id_hash="rt_true_001" )
        loaded = self._round_trip( manager, snap )
        assert loaded.answer_is_correct is True

    def test_round_trip_false( self, manager ):
        """LanceDB round-trip preserves answer_is_correct=False."""
        snap = _make_minimal_snapshot( answer_is_correct=False, id_hash="rt_false_001" )
        loaded = self._round_trip( manager, snap )
        assert loaded.answer_is_correct is False

    def test_update_none_to_true( self, manager ):
        """Saving a snapshot with updated answer_is_correct persists the change."""
        snap = _make_minimal_snapshot( answer_is_correct=None, id_hash="update_001" )
        manager.save_snapshot( snap )

        # Update the field and re-save
        snap.answer_is_correct = True
        manager.save_snapshot( snap )

        results = manager.get_snapshots_by_question( snap.question )
        assert results and len( results ) > 0
        _score, loaded = results[ 0 ]
        assert loaded.answer_is_correct is True
