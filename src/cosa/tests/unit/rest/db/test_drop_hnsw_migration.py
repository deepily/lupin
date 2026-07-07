"""
Unit tests for migration e1f2a3b4c5d6 (drop the input_and_output HNSW index —
exact-scan ruling, Rick 2026-07-07).

Mirrors the test_pgvector_migration.py pattern: revision-chain pins + mock-bind
coverage of the upgrade/downgrade bodies (no real DB). The behavioral proof that
exact scan serves `<#>` knn correctly lives in the repositories equivalence
tests + the 2026-07-07 swap-chain execution log §4.
"""
import glob
import importlib.util
import os
import re
import sys
import unittest
from unittest.mock import patch

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import cosa.utils.util as cu

_THIS_REVISION    = "e1f2a3b4c5d6"
_HEAD_BEFORE_THIS = "d0e1f2a3b4c5"
_INDEX_NAME       = "idx_input_and_output_input_embedding_hnsw"


def _versions_dir():
    return os.path.join( cu.get_project_root(), "src", "migrations", "versions" )


def _load_migration():
    path = os.path.join( _versions_dir(), f"{_THIS_REVISION}_drop_input_and_output_hnsw_exact_scan.py" )
    spec = importlib.util.spec_from_file_location( "drop_hnsw_migration", path )
    module = importlib.util.module_from_spec( spec )
    spec.loader.exec_module( module )
    return module


class TestRevisionChain( unittest.TestCase ):

    def setUp( self ):
        self.mig = _load_migration()

    def test_revision_id( self ):
        self.assertEqual( self.mig.revision, _THIS_REVISION )

    def test_down_revision_chains_to_prior_head( self ):
        self.assertEqual( self.mig.down_revision, _HEAD_BEFORE_THIS )

    def test_this_revision_is_a_head( self ):
        # No other migration may list this revision as its down_revision.
        for path in glob.glob( os.path.join( _versions_dir(), "*.py" ) ):
            with open( path ) as fh:
                src = fh.read()
            m = re.search( r"down_revision.*?=\s*['\"]([0-9a-f]+)['\"]", src )
            if m:
                self.assertNotEqual( m.group( 1 ), _THIS_REVISION, f"{path} chains off this head" )


class TestUpgradeDowngradeOps( unittest.TestCase ):
    """Cover the upgrade/downgrade bodies with a mocked op — no real DB."""

    def setUp( self ):
        self.mig = _load_migration()

    def test_upgrade_drops_the_index_if_exists( self ):
        with patch( "alembic.op.execute" ) as ex:
            self.mig.upgrade()
        ex.assert_called_once()
        sql = ex.call_args[ 0 ][ 0 ]
        self.assertIn( "DROP INDEX IF EXISTS", sql )
        self.assertIn( _INDEX_NAME, sql )

    def test_downgrade_recreates_hnsw_with_model_params( self ):
        from cosa.rest.db.vector_store_models import HNSW_M, HNSW_EF_CONSTRUCTION
        with patch( "alembic.op.execute" ) as ex:
            self.mig.downgrade()
        ex.assert_called_once()
        sql = ex.call_args[ 0 ][ 0 ]
        self.assertIn( f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME}", sql )
        self.assertIn( "USING hnsw (input_embedding vector_ip_ops)", sql )
        self.assertIn( f"m = {HNSW_M}", sql )
        self.assertIn( f"ef_construction = {HNSW_EF_CONSTRUCTION}", sql )


if __name__ == "__main__":
    unittest.main()
