"""
Unit Tests for canonical-synonym cleanup on snapshot deletion.

Tests the ghost snapshot cleanup that prevents orphaned synonym entries when
snapshots are deleted from the solutions table.

TRIMMED 2026-08-17 by Pocholo (LanceDB total-removal sweep, Lane A, rows
5ff7b8f5 / 8098838f): TestDeleteBySnapshotId drove the LanceDB delete path by
pinning _use_postgres = False and mocking a LanceDB table. That path no longer
exists — delete_by_snapshot_id now delegates to CanonicalSynonymRepository, and
its coverage lives in
src/cosa/tests/unit/memory/test_canonical_synonyms_table.py. Deleted, not
skipped. The classes below are mock-only simulations of caller logic and are
untouched.
"""

from unittest.mock import MagicMock


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
