"""
Unit tests for SolutionSnapshot.answer_is_correct tri-state field.

Tests the answer_is_correct field across SolutionSnapshot construction,
for_current_user preservation, get_copy preservation, and the Postgres
marshal round-trip.

Backend note: there is one storage backend. The round-trip class that pinned
the flag to exercise the second one went with that backend's manager on
2026-08-17 (row 8098838f) — it was testing deleted code.
"""

import json
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
        "question_gist_embedding"       : [],
        "solution_embedding"            : [ 0.1 ] * 768,
        "code_embedding"                : [ 0.1 ] * 768,
        "thoughts_embedding"            : [ 0.1 ] * 768,
        "solution_gist_embedding"       : [],
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


# ─── Postgres marshal round-trip tests ──────────────────────────────────────

class TestAnswerIsCorrectPostgresMarshal:
    """
    Test answer_is_correct survives the Postgres marshal pair, with NO database.

    Postgres is the only backend, so this is the path production takes. The pair
    under test is the whole read side:
    _pg_record_from_entity (ORM row -> record dict) then _record_to_snapshot
    (record dict -> SolutionSnapshot). _pg_get_snapshots_by_question and
    _pg_get_snapshot_by_id both funnel through exactly this pair, so covering it
    covers them without standing up pgvector.
    """

    def _bare_manager( self ):
        """
        Build a PostgresSolutionManager with NO __init__ side effects.

        __init__ constructs a QuestionEmbeddingsTable and reads config; none of that
        is needed to exercise the marshal helpers, and all of it would touch storage.
        Only _embedding_dim is consumed by _snapshot_to_record, so supply just that.
        """
        from cosa.memory.postgres_solution_manager import PostgresSolutionManager

        mgr                 = PostgresSolutionManager.__new__( PostgresSolutionManager )
        mgr._embedding_dim  = 768
        return mgr

    def _entity_for( self, manager, snapshot ):
        """
        Marshal a snapshot into a stub ORM row shaped like what Postgres returns.

        The record dict comes from _snapshot_to_record — the SAME builder
        _pg_save_snapshot writes with — so the stub carries the real written values;
        columns the builder does not populate read back as None, as they would.
        """
        from types import SimpleNamespace
        from cosa.memory.postgres_solution_manager import _SNAPSHOT_RECORD_COLUMNS

        record = manager._snapshot_to_record( snapshot )
        return SimpleNamespace( **{ column: record.get( column ) for column in _SNAPSHOT_RECORD_COLUMNS } )

    def _round_trip( self, answer_is_correct ):
        """Push a value through write-marshal -> ORM row -> read-marshal."""
        manager = self._bare_manager()
        snap    = _make_minimal_snapshot( answer_is_correct=answer_is_correct )
        entity  = self._entity_for( manager, snap )
        return manager._record_to_snapshot( manager._pg_record_from_entity( entity ) )

    def test_column_is_marshalled( self ):
        """answer_is_correct is in the column list both marshal helpers iterate."""
        from cosa.memory.postgres_solution_manager import _SNAPSHOT_RECORD_COLUMNS
        assert "answer_is_correct" in _SNAPSHOT_RECORD_COLUMNS

    def test_column_is_text_not_boolean( self ):
        """
        The ORM column is Text, which is what makes the round-trip work.

        _record_to_snapshot deserializes with json.loads inside a bare except. A
        native Boolean column would hand it a Python bool, json.loads would raise
        TypeError, and the except would silently yield None — see the negative
        control below. This asserts the schema does not have that shape.
        """
        from sqlalchemy import Text
        from cosa.rest.db.vector_store_models import SolutionSnapshot as PgRow

        column = PgRow.__table__.columns[ "answer_is_correct" ]
        assert isinstance( column.type, Text )

    def test_round_trip_none( self ):
        """Postgres marshal preserves answer_is_correct=None."""
        assert self._round_trip( None ).answer_is_correct is None

    def test_round_trip_true( self ):
        """Postgres marshal preserves answer_is_correct=True."""
        assert self._round_trip( True ).answer_is_correct is True

    def test_round_trip_false( self ):
        """Postgres marshal preserves answer_is_correct=False."""
        assert self._round_trip( False ).answer_is_correct is False

    def test_raw_bool_column_would_be_dropped( self ):
        """
        NEGATIVE CONTROL — the assertions above have teeth.

        Hand the read marshal a raw bool where it expects a JSON string (what a
        Boolean column would produce) and the value is silently lost. If this ever
        starts returning True, _record_to_snapshot stopped deserializing and the
        round-trip tests above are passing for the wrong reason.
        """
        manager        = self._bare_manager()
        snap           = _make_minimal_snapshot( answer_is_correct=True )
        entity         = self._entity_for( manager, snap )
        entity.answer_is_correct = True   # a bool, not the json.dumps'd "true"

        loaded = manager._record_to_snapshot( manager._pg_record_from_entity( entity ) )
        assert loaded.answer_is_correct is None
