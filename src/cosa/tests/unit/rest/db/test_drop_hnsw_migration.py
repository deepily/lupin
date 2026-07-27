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

    def test_no_two_migrations_share_a_down_revision( self ):
        """
        The chain must not FORK — no two migrations may declare the same parent.

        WHAT THIS REPLACED, AND WHY (2026-07-27, row 5bf28e07)
        -----------------------------------------------------
        This assertion used to be `test_this_revision_is_a_head`: it walked every
        migration and required that NONE list this revision as its down_revision.
        That is stale by construction — it holds only until the next migration
        lands on top, which is the normal, correct thing for a migration to do.

        It went red on 2026-07-15 when `f2a3b4c5d6e7` chained off this revision,
        and stayed red for twelve days without anyone noticing, because
        `src/cosa/tests/**` is referenced by no gate. Had the tree been gated it
        would have blocked EVERY migration ever added — the assertion was a
        tripwire across the path the project has to walk.

        A hash bump would only move the expiry date. The durable invariant is a
        FORK: two siblings claiming one parent produces two alembic heads, which
        is a real defect and does not become true merely because the chain grew.
        """
        parents = {}
        for path in sorted( glob.glob( os.path.join( _versions_dir(), "*.py" ) ) ):
            with open( path ) as fh:
                src = fh.read()
            m = re.search( r"down_revision.*?=\s*['\"]([0-9a-f]+)['\"]", src )
            if not m: continue                      # `down_revision = None` — the base
            parents.setdefault( m.group( 1 ), [] ).append( os.path.basename( path ) )

        forks = { parent: kids for parent, kids in parents.items() if len( kids ) > 1 }
        self.assertEqual(
            forks, {},
            f"migration chain FORKS — these parents have more than one child, which "
            f"produces multiple alembic heads: {forks}"
        )

    def test_the_fork_check_can_actually_see_a_fork( self ):
        """
        CONTROL. The check above passes on a healthy tree, and a check that passes
        because it never looks is indistinguishable from one that passes because
        the tree is clean. This drives the same grouping over a synthetic fork and
        requires it to be caught.
        """
        sources = {
            "0001_base.py"  : "revision = 'aaa1'\ndown_revision = None\n",
            "0002_left.py"  : "revision = 'bbb2'\ndown_revision = 'aaa1'\n",
            "0003_right.py" : "revision = 'ccc3'\ndown_revision = 'aaa1'\n",   # the fork
        }
        parents = {}
        for name, src in sorted( sources.items() ):
            m = re.search( r"down_revision.*?=\s*['\"]([0-9a-f]+)['\"]", src )
            if not m: continue
            parents.setdefault( m.group( 1 ), [] ).append( name )

        forks = { p: k for p, k in parents.items() if len( k ) > 1 }
        self.assertEqual( forks, { "aaa1": [ "0002_left.py", "0003_right.py" ] } )


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
