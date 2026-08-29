#!/usr/bin/env python3
"""
Unit tests for cosa/memory/postgres_solution_manager.py — the Postgres+pgvector
solution snapshot manager lifted out of the LanceDB-named class (store row 5ff7b8f5,
ruling 29e98243).

Every store touch is mocked: get_db / SolutionSnapshotRepository / the ORM row are
patched at their source modules (the manager imports them inside each method), and
the lifted search helpers are patched at the manager module's own names. Nothing here
opens a database connection.

Target: 100% line + branch coverage of postgres_solution_manager.py.
"""
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock, patch

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

_MODULE = "cosa.memory.postgres_solution_manager"


def _build_manager( config=None, debug=False, verbose=False ):
    """
    Construct a PostgresSolutionManager with its heavy collaborators stubbed.

    Requires:
        - config is a dict or None

    Ensures:
        - returns a manager whose QuestionEmbeddingsTable + ConfigurationManager are Mocks
    """
    from cosa.memory.postgres_solution_manager import PostgresSolutionManager

    cfg = Mock()
    cfg.get.side_effect = lambda key, default=None, **kw: { "embedding dimensions": "768" }.get( key, default )

    with patch( "cosa.memory.question_embeddings_table.QuestionEmbeddingsTable" ) as qet, \
         patch( f"{_MODULE}.ConfigurationManager", return_value=cfg ):
        qet.return_value = Mock( name="QuestionEmbeddingsTable" )
        return PostgresSolutionManager( config if config is not None else {}, debug=debug, verbose=verbose )


@contextmanager
def _fake_db( session ):
    """A get_db() stand-in yielding the supplied session."""
    yield session


def _patch_db( session ):
    """Patch get_db + SolutionSnapshotRepository at their source modules."""
    repo = MagicMock( name="SolutionSnapshotRepository" )
    return (
        patch( "cosa.rest.db.database.get_db", lambda: _fake_db( session ) ),
        patch( "cosa.rest.db.repositories.solution_snapshot_repository.SolutionSnapshotRepository", repo ),
        repo,
    )


class TestConstruction( unittest.TestCase ):
    """__init__ — defaults, overrides, and the debug-print arm."""

    def test_defaults_when_config_empty( self ):
        mgr = _build_manager( {} )
        self.assertEqual( mgr.table_name, "solution_snapshots" )
        self.assertEqual( mgr.storage_backend, "postgres" )
        self.assertIsNone( mgr.db_path )                 # decision 2b20a6d6: advertise no path
        self.assertIsNone( mgr._canonical_synonyms )
        self.assertIsNone( mgr._normalizer )
        self.assertFalse( mgr.is_initialized() )
        self.assertEqual( mgr._embedding_dim, 768 )

    def test_table_name_from_config( self ):
        mgr = _build_manager( { "table_name": "other_table" } )
        self.assertEqual( mgr.table_name, "other_table" )

    def test_save_lock_is_usable( self ):
        mgr = _build_manager()
        with mgr._save_lock:
            self.assertTrue( True )                      # acquiring the real lock is the assertion

    def test_debug_construction_prints( self ):
        import io, contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout( buffer ):
            _build_manager( {}, debug=True )
        out = buffer.getvalue()
        self.assertIn( "PostgresSolutionManager configured", out )
        self.assertIn( "postgres (pgvector)", out )


class TestInitializeAndReload( unittest.TestCase ):
    """initialize / reload — cache bypass + the not-initialized guard."""

    def test_initialize_sets_flag_without_store_access( self ):
        mgr = _build_manager()
        mgr.initialize()
        self.assertTrue( mgr.is_initialized() )

    def test_initialize_debug_prints( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        buffer = io.StringIO()
        with contextlib.redirect_stdout( buffer ):
            mgr.initialize()
        self.assertIn( "cache bypass", buffer.getvalue() )

    def test_reload_before_initialize_raises( self ):
        mgr = _build_manager()
        with self.assertRaises( RuntimeError ):
            mgr.reload()

    def test_reload_after_initialize_is_noop( self ):
        mgr = _build_manager()
        mgr.initialize()
        self.assertIsNone( mgr.reload() )

    def test_reload_debug_prints( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        buffer = io.StringIO()
        with contextlib.redirect_stdout( buffer ):
            mgr.reload()
        self.assertIn( "no-op", buffer.getvalue() )


class TestEnsureList( unittest.TestCase ):
    """_ensure_list — every coercion arm."""

    def setUp( self ):
        self.mgr = _build_manager()

    def test_none_becomes_empty( self ):        self.assertEqual( self.mgr._ensure_list( None ), [] )
    def test_empty_string_becomes_empty( self ): self.assertEqual( self.mgr._ensure_list( "" ), [] )
    def test_string_wraps( self ):              self.assertEqual( self.mgr._ensure_list( "a" ), [ "a" ] )
    def test_list_passes_through( self ):       self.assertEqual( self.mgr._ensure_list( [ 1, 2 ] ), [ 1, 2 ] )
    def test_tuple_converts( self ):            self.assertEqual( self.mgr._ensure_list( ( 1, 2 ) ), [ 1, 2 ] )
    def test_unconvertible_becomes_empty( self ): self.assertEqual( self.mgr._ensure_list( 7 ), [] )


class TestMarshalling( unittest.TestCase ):
    """Record marshalling — delegation plus the entity walk."""

    def setUp( self ):
        self.mgr = _build_manager()

    def test_snapshot_to_record_delegates( self ):
        with patch( f"{_MODULE}.snapshot_to_pg_record", return_value={ "id_hash": "h" } ) as helper:
            self.assertEqual( self.mgr._snapshot_to_record( "snap" ), { "id_hash": "h" } )
        helper.assert_called_once_with( self.mgr, "snap" )

    def test_record_to_snapshot_delegates( self ):
        with patch( f"{_MODULE}.pg_record_to_snapshot", return_value="snapshot" ) as helper:
            self.assertEqual( self.mgr._record_to_snapshot( { "a": 1 } ), "snapshot" )
        helper.assert_called_once_with( self.mgr, { "a": 1 } )

    def test_update_canonical_synonyms_delegates( self ):
        with patch( f"{_MODULE}.update_canonical_synonyms", return_value=None ) as helper:
            self.assertIsNone( self.mgr._update_canonical_synonyms( "snap" ) )
        helper.assert_called_once_with( self.mgr, "snap" )

    def test_record_from_entity_covers_every_column( self ):
        from cosa.memory.postgres_solution_manager import _SNAPSHOT_RECORD_COLUMNS
        entity = Mock()
        for column in _SNAPSHOT_RECORD_COLUMNS:
            setattr( entity, column, f"v_{column}" )
        record = self.mgr._pg_record_from_entity( entity )
        self.assertEqual( set( record ), set( _SNAPSHOT_RECORD_COLUMNS ) )
        self.assertEqual( record[ "id_hash" ], "v_id_hash" )


class TestSaveSnapshot( unittest.TestCase ):
    """save_snapshot — guards, insert, dedup override, failure."""

    def setUp( self ):
        self.mgr = _build_manager()
        self.snapshot = Mock( question="what time is it", id_hash="hash-1" )

    def test_uninitialized_raises( self ):
        with self.assertRaises( RuntimeError ):
            self.mgr.save_snapshot( self.snapshot )

    def test_none_snapshot_raises( self ):
        self.mgr.initialize()
        with self.assertRaises( ValueError ):
            self.mgr.save_snapshot( None )

    def test_empty_question_raises( self ):
        self.mgr.initialize()
        with self.assertRaises( ValueError ):
            self.mgr.save_snapshot( Mock( question="" ) )

    def _run_save( self, existing ):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = existing
        db_patch, repo_patch, repo = _patch_db( session )
        with db_patch, repo_patch, \
             patch.object( self.mgr, "_snapshot_to_record", return_value={ "id_hash": "hash-1", "question": "q" } ), \
             patch.object( self.mgr, "_update_canonical_synonyms" ) as synonyms:
            result = self.mgr.save_snapshot( self.snapshot )
        return result, repo, synonyms

    def test_insert_when_no_existing_row( self ):
        self.mgr.initialize()
        result, repo, synonyms = self._run_save( existing=None )
        self.assertTrue( result )
        repo.return_value.upsert_snapshot.assert_called_once_with( "hash-1", question="q" )
        synonyms.assert_called_once_with( self.snapshot )

    def test_existing_row_overrides_id_hash( self ):
        self.mgr.initialize()
        result, repo, _ = self._run_save( existing=Mock( id_hash="db-hash" ) )
        self.assertTrue( result )
        repo.return_value.upsert_snapshot.assert_called_once_with( "db-hash", question="q" )

    def test_store_failure_returns_false( self ):
        self.mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ), \
             patch.object( self.mgr, "_snapshot_to_record", return_value={ "id_hash": "h" } ):
            self.assertFalse( self.mgr.save_snapshot( self.snapshot ) )

    def test_store_failure_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        buffer = io.StringIO()
        with contextlib.redirect_stdout( buffer ), \
             patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ), \
             patch.object( mgr, "_snapshot_to_record", return_value={ "id_hash": "h" } ):
            mgr.save_snapshot( self.snapshot )
        self.assertIn( "Failed to save snapshot", buffer.getvalue() )


class TestGetSnapshotById( unittest.TestCase ):
    """get_snapshot_by_id — uninitialized, found, missing, error."""

    def setUp( self ):
        self.mgr = _build_manager()

    def test_uninitialized_returns_none( self ):
        self.assertIsNone( self.mgr.get_snapshot_by_id( "abc" ) )

    def test_uninitialized_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        buffer = io.StringIO()
        with contextlib.redirect_stdout( buffer ):
            mgr.get_snapshot_by_id( "abc" )
        self.assertIn( "not initialized", buffer.getvalue() )

    def test_found_marshals_inside_session( self ):
        self.mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_snapshot_by_id.return_value = Mock()
        snapshot = Mock( question="a question that is long enough to slice" )
        with db_patch, repo_patch, \
             patch.object( self.mgr, "_pg_record_from_entity", return_value={ "id_hash": "h" } ), \
             patch.object( self.mgr, "_record_to_snapshot", return_value=snapshot ):
            self.assertIs( self.mgr.get_snapshot_by_id( "h" ), snapshot )

    def test_found_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_snapshot_by_id.return_value = Mock()
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, db_patch, repo_patch, \
             patch.object( mgr, "_pg_record_from_entity", return_value={} ), \
             patch.object( mgr, "_record_to_snapshot", return_value=Mock( question="q" * 60 ) ):
            mgr.get_snapshot_by_id( "h" )
        self.assertIn( "Found snapshot", buffer.getvalue() )

    def test_missing_returns_none( self ):
        self.mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_snapshot_by_id.return_value = None
        with db_patch, repo_patch:
            self.assertIsNone( self.mgr.get_snapshot_by_id( "nope" ) )

    def test_missing_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_snapshot_by_id.return_value = None
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, db_patch, repo_patch:
            mgr.get_snapshot_by_id( "nope" )
        self.assertIn( "No snapshot found", buffer.getvalue() )

    def test_error_returns_none( self ):
        self.mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            self.assertIsNone( self.mgr.get_snapshot_by_id( "h" ) )

    def test_error_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, \
             patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            mgr.get_snapshot_by_id( "h" )
        self.assertIn( "Error retrieving snapshot", buffer.getvalue() )


class TestDeleteSnapshot( unittest.TestCase ):
    """delete_snapshot — guards, missing row, synonym cascade, error."""

    def setUp( self ):
        self.mgr = _build_manager()

    def test_uninitialized_raises( self ):
        with self.assertRaises( RuntimeError ):
            self.mgr.delete_snapshot( "q" )

    def test_empty_question_raises( self ):
        self.mgr.initialize()
        with self.assertRaises( ValueError ):
            self.mgr.delete_snapshot( "" )

    def _run_delete( self, existing, synonyms_table, debug=False ):
        mgr = _build_manager( {}, debug=debug )
        mgr.initialize()
        mgr._canonical_synonyms = synonyms_table
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = existing
        db_patch, repo_patch, repo = _patch_db( session )
        with db_patch, repo_patch:
            result = mgr.delete_snapshot( "what time is it" )
        return result, repo

    def test_missing_row_returns_false( self ):
        result, repo = self._run_delete( existing=None, synonyms_table=None )
        self.assertFalse( result )
        repo.return_value.delete_snapshot.assert_not_called()

    def test_missing_row_prints_when_debug( self ):
        import io, contextlib
        with contextlib.redirect_stdout( io.StringIO() ) as buffer:
            self._run_delete( existing=None, synonyms_table=None, debug=True )
        self.assertIn( "Snapshot not found", buffer.getvalue() )

    def test_found_deletes_and_cascades_synonyms( self ):
        synonyms = Mock()
        synonyms.delete_by_snapshot_id.return_value = 3
        result, repo = self._run_delete( existing=Mock( id_hash="db-hash-1234" ), synonyms_table=synonyms )
        self.assertTrue( result )
        repo.return_value.delete_snapshot.assert_called_once_with( "db-hash-1234" )
        synonyms.delete_by_snapshot_id.assert_called_once_with( "db-hash-1234" )

    def test_found_skips_cascade_when_synonyms_unavailable( self ):
        for unavailable in ( None, False ):
            result, repo = self._run_delete( existing=Mock( id_hash="db-hash-1234" ), synonyms_table=unavailable )
            self.assertTrue( result )
            repo.return_value.delete_snapshot.assert_called_once_with( "db-hash-1234" )

    def test_found_prints_when_debug( self ):
        import io, contextlib
        synonyms = Mock()
        synonyms.delete_by_snapshot_id.return_value = 1
        with contextlib.redirect_stdout( io.StringIO() ) as buffer:
            self._run_delete( existing=Mock( id_hash="db-hash-1234" ), synonyms_table=synonyms, debug=True )
        out = buffer.getvalue()
        self.assertIn( "Cleaned up 1 canonical synonym", out )
        self.assertIn( "Deleted snapshot", out )

    def test_error_returns_false( self ):
        self.mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            self.assertFalse( self.mgr.delete_snapshot( "q" ) )

    def test_error_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, \
             patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            mgr.delete_snapshot( "q" )
        self.assertIn( "Failed to delete snapshot", buffer.getvalue() )


class TestSearchDelegation( unittest.TestCase ):
    """The search surface forwards to the lifted, LanceDB-free helpers."""

    def setUp( self ):
        self.mgr = _build_manager()
        self.mgr.initialize()

    def test_get_snapshots_by_question_forwards( self ):
        with patch( f"{_MODULE}.pg_hierarchical_search", return_value=[ ( 100.0, "snap" ) ] ) as helper:
            result = self.mgr.get_snapshots_by_question( "q", "gist", 91.0, 92.0, 5, True )
        self.assertEqual( result, [ ( 100.0, "snap" ) ] )
        helper.assert_called_once_with( self.mgr, "q", "gist", 91.0, 92.0, 5, True )

    def test_internal_question_name_is_preserved_for_the_helpers( self ):
        # two_tier_question_search re-enters the manager by this exact name.
        self.assertTrue( callable( self.mgr._pg_get_snapshots_by_question ) )
        with patch( f"{_MODULE}.pg_hierarchical_search", return_value=[] ) as helper:
            self.mgr._pg_get_snapshots_by_question( "q" )
        helper.assert_called_once_with( self.mgr, "q", None, 90.0, 90.0, 7, False )

    def test_code_similarity_uses_code_embedding( self ):
        with patch( f"{_MODULE}.pg_similarity_search", return_value=[] ) as helper:
            self.mgr.get_snapshots_by_code_similarity( "exemplar", 80.0, 5, False, False, True )
        helper.assert_called_once_with( self.mgr, "exemplar", "code_embedding",
                                        "get_snapshots_by_code_similarity", 80.0, 5, False, False )

    def test_solution_similarity_uses_solution_embedding( self ):
        with patch( f"{_MODULE}.pg_similarity_search", return_value=[] ) as helper:
            self.mgr.get_snapshots_by_solution_similarity( "exemplar" )
        helper.assert_called_once_with( self.mgr, "exemplar", "solution_embedding",
                                        "get_snapshots_by_solution_similarity", 85.0, 20, True, True )


class TestGetGists( unittest.TestCase ):
    """get_gists — guard, dedup, error."""

    def test_uninitialized_raises( self ):
        with self.assertRaises( RuntimeError ):
            _build_manager().get_gists()

    def _run_gists( self, raw, debug=False ):
        mgr = _build_manager( {}, debug=debug )
        mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_gists.return_value = raw
        with db_patch, repo_patch:
            return mgr.get_gists()

    def test_dedups_and_drops_empties_preserving_order( self ):
        self.assertEqual( self._run_gists( [ "b", "a", "b", "", None, "c" ] ), [ "b", "a", "c" ] )

    def test_debug_prints_count( self ):
        import io, contextlib
        with contextlib.redirect_stdout( io.StringIO() ) as buffer:
            self._run_gists( [ "a" ], debug=True )
        self.assertIn( "unique question gists", buffer.getvalue() )

    def test_error_returns_empty( self ):
        mgr = _build_manager()
        mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            self.assertEqual( mgr.get_gists(), [] )

    def test_error_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, \
             patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            mgr.get_gists()
        self.assertIn( "Failed to get gists", buffer.getvalue() )


class TestGetStats( unittest.TestCase ):
    """get_stats — guard, happy shape, error shape."""

    def test_uninitialized_raises( self ):
        with self.assertRaises( RuntimeError ):
            _build_manager().get_stats()

    def test_reports_postgres_shape( self ):
        mgr = _build_manager()
        mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_stats.return_value = { "total_snapshots": 12 }
        with db_patch, repo_patch:
            stats = mgr.get_stats()
        self.assertEqual( stats[ "total_snapshots" ], 12 )
        self.assertEqual( stats[ "storage_size_mb" ], 0.0 )     # no per-manager footprint
        self.assertEqual( stats[ "backend_type" ], "postgres" )
        self.assertIsNone( stats[ "database_path" ] )
        self.assertIn( "last_updated", stats )

    def test_debug_prints_total( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_stats.return_value = { "total_snapshots": 7 }
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, db_patch, repo_patch:
            mgr.get_stats()
        self.assertIn( "7 snapshots (postgres)", buffer.getvalue() )

    def test_error_returns_error_shape( self ):
        mgr = _build_manager()
        mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            stats = mgr.get_stats()
        self.assertEqual( stats[ "status" ], "error" )
        self.assertEqual( stats[ "total_snapshots" ], 0 )
        self.assertIn( "boom", stats[ "error" ] )

    def test_error_prints_when_debug( self ):
        import io, contextlib
        mgr = _build_manager( {}, debug=True )
        mgr.initialize()
        with contextlib.redirect_stdout( io.StringIO() ) as buffer, \
             patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            mgr.get_stats()
        self.assertIn( "Failed to get stats", buffer.getvalue() )


class TestHealthCheck( unittest.TestCase ):
    """health_check — healthy, degraded, unhealthy; never raises."""

    def _run_health( self, initialized ):
        mgr = _build_manager()
        if initialized: mgr.initialize()
        session = MagicMock()
        db_patch, repo_patch, repo = _patch_db( session )
        repo.return_value.get_stats.return_value = { "total_snapshots": 4 }
        with db_patch, repo_patch:
            return mgr.health_check()

    def test_healthy_when_initialized( self ):
        health = self._run_health( initialized=True )
        self.assertEqual( health[ "status" ], "healthy" )
        self.assertEqual( health[ "connection_status" ], "connected" )
        self.assertEqual( health[ "snapshot_count" ], 4 )
        self.assertEqual( health[ "backend_type" ], "postgres" )
        self.assertEqual( health[ "errors" ], [] )

    def test_degraded_when_reachable_but_uninitialized( self ):
        self.assertEqual( self._run_health( initialized=False )[ "status" ], "degraded" )

    def test_unhealthy_when_store_unreachable( self ):
        mgr = _build_manager()
        mgr.initialize()
        with patch( "cosa.rest.db.database.get_db", side_effect=RuntimeError( "boom" ) ):
            health = mgr.health_check()
        self.assertEqual( health[ "status" ], "unhealthy" )
        self.assertEqual( health[ "connection_status" ], "disconnected" )
        self.assertIn( "boom", health[ "errors" ][ 0 ] )


class TestImportGraph( unittest.TestCase ):
    """The module's OWN imports carry no lancedb — the claim the docstring makes."""

    def test_module_source_has_no_top_level_lancedb_import( self ):
        import cosa.memory.postgres_solution_manager as module
        with open( module.__file__.replace( ".pyc", ".py" ), "r" ) as handle:
            lines = handle.read().splitlines()
        # Only the module docstring may mention lancedb; no import statement may.
        offenders = [ line for line in lines
                      if line.startswith( ( "import ", "from " ) ) and "lancedb" in line ]
        self.assertEqual( offenders, [] )

    def test_module_does_not_expose_lancedb_attribute( self ):
        import cosa.memory.postgres_solution_manager as module
        self.assertFalse( hasattr( module, "lancedb" ) )


if __name__ == "__main__":
    unittest.main()
