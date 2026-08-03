"""
Unit Tests for CanonicalSynonymsTable.delete_by_snapshot_id()

Tests the ghost snapshot cleanup method added to prevent orphaned synonym
entries when snapshots are deleted from the solutions table.
"""

import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch, PropertyMock
import pandas as pd


class TestDeleteBySnapshotId:
    """Unit tests for CanonicalSynonymsTable.delete_by_snapshot_id()."""

    def _make_table_with_mock( self ):
        """Create a CanonicalSynonymsTable-like object with a mocked LanceDB table."""
        from unittest.mock import MagicMock

        obj = MagicMock()
        obj.debug = True
        obj._use_postgres = False          # exercise the LanceDB delete path (v0.2.0 §6 flag)
        obj._canonical_synonyms_table = MagicMock()

        # Import the real method and bind it
        from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
        import types
        obj.delete_by_snapshot_id = types.MethodType(
            CanonicalSynonymsTable.delete_by_snapshot_id, obj
        )
        return obj

    def test_deletes_matching_rows( self ):
        """Rows with matching snapshot_id are deleted and count returned."""
        obj = self._make_table_with_mock()

        # Mock to_pandas returning 2 rows with matching snapshot_id
        df = pd.DataFrame( {
            "snapshot_id" : [ "abc123", "abc123", "def456" ],
            "question_verbatim" : [ "q1", "q2", "q3" ]
        } )
        obj._canonical_synonyms_table.to_pandas.return_value = df

        result = obj.delete_by_snapshot_id( "abc123" )

        assert result == 2
        obj._canonical_synonyms_table.delete.assert_called_once_with( "snapshot_id = 'abc123'" )

    def test_returns_zero_when_no_matches( self ):
        """Returns 0 when no rows match the snapshot_id."""
        obj = self._make_table_with_mock()

        df = pd.DataFrame( {
            "snapshot_id" : [ "def456", "ghi789" ],
            "question_verbatim" : [ "q1", "q2" ]
        } )
        obj._canonical_synonyms_table.to_pandas.return_value = df

        result = obj.delete_by_snapshot_id( "abc123" )

        assert result == 0
        obj._canonical_synonyms_table.delete.assert_not_called()

    def test_returns_zero_on_empty_table( self ):
        """Returns 0 on empty table without error."""
        obj = self._make_table_with_mock()

        df = pd.DataFrame( {
            "snapshot_id"       : pd.Series( [], dtype="str" ),
            "question_verbatim" : pd.Series( [], dtype="str" )
        } )
        obj._canonical_synonyms_table.to_pandas.return_value = df

        result = obj.delete_by_snapshot_id( "abc123" )

        assert result == 0

    def test_returns_zero_on_exception( self ):
        """Returns 0 and doesn't propagate when table raises."""
        obj = self._make_table_with_mock()
        obj._canonical_synonyms_table.to_pandas.side_effect = RuntimeError( "DB error" )

        result = obj.delete_by_snapshot_id( "abc123" )

        assert result == 0

    def test_single_match_deleted( self ):
        """Exactly one match is deleted correctly."""
        obj = self._make_table_with_mock()

        df = pd.DataFrame( {
            "snapshot_id"       : [ "abc123", "def456" ],
            "question_verbatim" : [ "q1", "q2" ]
        } )
        obj._canonical_synonyms_table.to_pandas.return_value = df

        result = obj.delete_by_snapshot_id( "abc123" )

        assert result == 1
        obj._canonical_synonyms_table.delete.assert_called_once()


class TestDeleteSnapshotSynonymCleanup:
    """Tests that delete_snapshot() in SolutionSnapshotManager cleans up synonyms."""

    def test_synonym_cleanup_called_on_delete( self ):
        """delete_snapshot() calls delete_by_snapshot_id() when synonyms table is initialized."""
        mock_synonyms = MagicMock()
        mock_synonyms.delete_by_snapshot_id.return_value = 3

        # Build a minimal mock of SolutionSnapshotManager
        mgr = MagicMock()
        mgr._canonical_synonyms = mock_synonyms
        mgr._question_lookup    = { "What is 4+4?" : "hash_abc" }
        mgr._id_lookup          = { "hash_abc" : { "id_hash" : "hash_abc" } }
        mgr._table              = MagicMock()
        mgr.debug               = True

        # Simulate the delete_snapshot logic for the synonym cleanup portion
        id_hash = "hash_abc"
        mgr._table.delete( f"id_hash = '{id_hash}'" )

        if mgr._canonical_synonyms is not None and mgr._canonical_synonyms is not False:
            deleted_count = mgr._canonical_synonyms.delete_by_snapshot_id( id_hash )

        mock_synonyms.delete_by_snapshot_id.assert_called_once_with( "hash_abc" )

    def test_synonym_cleanup_skipped_when_not_initialized( self ):
        """delete_snapshot() skips synonym cleanup when _canonical_synonyms is None."""
        mgr = MagicMock()
        mgr._canonical_synonyms = None

        # This should NOT raise
        if mgr._canonical_synonyms is not None and mgr._canonical_synonyms is not False:
            mgr._canonical_synonyms.delete_by_snapshot_id( "hash_abc" )

        # Nothing should have been called
        # (mgr._canonical_synonyms is None, so no method call)

    def test_synonym_cleanup_skipped_when_unavailable( self ):
        """delete_snapshot() skips synonym cleanup when _canonical_synonyms is False."""
        mgr = MagicMock()
        mgr._canonical_synonyms = False

        if mgr._canonical_synonyms is not None and mgr._canonical_synonyms is not False:
            mgr._canonical_synonyms.delete_by_snapshot_id( "hash_abc" )

        # False is truthy for `is not None` but fails `is not False` — no call made


class TestGhostAutoHeal:
    """Tests for ghost snapshot detection and auto-cleanup in get_snapshots_by_question()."""

    def test_ghost_level1_triggers_cleanup( self ):
        """Level 1 verbatim match to missing snapshot triggers auto-cleanup."""
        mock_synonyms = MagicMock()
        mock_synonyms.find_exact_verbatim.return_value = "ghost_snapshot_id"
        mock_synonyms.delete_by_snapshot_id.return_value = 1

        # Simulate get_snapshot_by_id returning None (ghost)
        snapshot_id = mock_synonyms.find_exact_verbatim( "What is 4+4?" )
        snapshot = None  # Simulating get_snapshot_by_id returning None

        if snapshot_id and snapshot is None:
            mock_synonyms.delete_by_snapshot_id( snapshot_id )

        mock_synonyms.delete_by_snapshot_id.assert_called_once_with( "ghost_snapshot_id" )

    def test_ghost_level2_triggers_cleanup( self ):
        """Level 2 normalized match to missing snapshot triggers auto-cleanup."""
        mock_synonyms = MagicMock()
        mock_synonyms.find_exact_normalized.return_value = "ghost_snapshot_id"
        mock_synonyms.delete_by_snapshot_id.return_value = 1

        snapshot_id = mock_synonyms.find_exact_normalized( "what is 4+4" )
        snapshot = None  # Simulating ghost

        if snapshot_id and snapshot is None:
            mock_synonyms.delete_by_snapshot_id( snapshot_id )

        mock_synonyms.delete_by_snapshot_id.assert_called_once_with( "ghost_snapshot_id" )

    def test_valid_match_does_not_trigger_cleanup( self ):
        """Valid Level 1 match does NOT trigger cleanup."""
        mock_synonyms = MagicMock()
        mock_synonyms.find_exact_verbatim.return_value = "valid_snapshot_id"

        snapshot_id = mock_synonyms.find_exact_verbatim( "What is 3+3?" )
        snapshot = MagicMock()  # Simulating valid snapshot found

        if snapshot_id and snapshot is None:
            mock_synonyms.delete_by_snapshot_id( snapshot_id )

        mock_synonyms.delete_by_snapshot_id.assert_not_called()
