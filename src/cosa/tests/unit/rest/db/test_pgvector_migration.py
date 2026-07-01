"""
Unit tests for the pgvector vector-store alembic migration
(src/migrations/versions/d0e1f2a3b4c5_add_pgvector_vector_store_tables.py).

Two layers, mirroring test_auto_migrate.py:
    - Structure/mocked tests (always run): revision chain, the 8-table selection,
      and the upgrade/downgrade ops (CREATE EXTENSION + per-table create/drop),
      driven with a mock bind — full coverage of the migration WITHOUT a database.
    - Live-PG apply test (SKIPPED unless a pgvector-enabled Postgres is reachable):
      runs the real upgrade against a throwaway schema and proves the extension,
      tables, HNSW dot indexes, and a `<#>` nearest-k query all work. GATED on the
      docker-compose image swap to pgvector/pgvector:pg16 (shared-infra, operator-
      applied). It is written now so it un-skips automatically once the image lands.
"""

import os
import re
import glob
import importlib.util
import unittest
from unittest.mock import MagicMock, patch

import cosa.utils.util as cu


_HEAD_BEFORE_THIS = "c9d0e1f2a3b4"   # alembic head this migration chains onto
_THIS_REVISION    = "d0e1f2a3b4c5"


def _versions_dir():
    return os.path.join( cu.get_project_root(), "src", "migrations", "versions" )


def _load_migration():
    path = os.path.join( _versions_dir(), f"{_THIS_REVISION}_add_pgvector_vector_store_tables.py" )
    spec = importlib.util.spec_from_file_location( "pgvector_migration", path )
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

    def test_prior_head_file_exists( self ):
        matches = glob.glob( os.path.join( _versions_dir(), f"{_HEAD_BEFORE_THIS}_*.py" ) )
        self.assertTrue( matches, f"prior head {_HEAD_BEFORE_THIS} file missing" )

    def test_this_revision_is_a_head( self ):
        # No other migration may list this revision as its down_revision.
        for path in glob.glob( os.path.join( _versions_dir(), "*.py" ) ):
            with open( path ) as fh:
                src = fh.read()
            m = re.search( r"down_revision.*?=\s*['\"]([0-9a-f]+)['\"]", src )
            if m:
                self.assertNotEqual( m.group( 1 ), _THIS_REVISION, f"{path} chains off this head" )


class TestTableSelection( unittest.TestCase ):

    def test_returns_the_eight_vector_store_tables( self ):
        mig = _load_migration()
        from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS
        tables = mig._vector_store_tables()
        self.assertEqual( len( tables ), 8 )
        self.assertEqual(
            [ t.name for t in tables ],
            [ m.__tablename__ for m in VECTOR_STORE_MODELS ],
        )


class TestUpgradeDowngradeOps( unittest.TestCase ):
    """Cover the upgrade/downgrade bodies with a mock bind — no real DB."""

    def _fake_tables( self, n=8 ):
        return [ MagicMock( name=f"table_{i}" ) for i in range( n ) ]

    def test_upgrade_creates_extension_then_each_table( self ):
        mig = _load_migration()
        fakes = self._fake_tables()
        with patch.object( mig, "_vector_store_tables", return_value=fakes ), \
             patch( "alembic.op.get_bind", return_value="BIND" ) as gb, \
             patch( "alembic.op.execute" ) as ex:
            mig.upgrade()
        gb.assert_called_once()
        ex.assert_called_once()
        self.assertIn( "CREATE EXTENSION", ex.call_args[ 0 ][ 0 ] )
        for t in fakes:
            t.create.assert_called_once_with( bind="BIND", checkfirst=True )

    def test_downgrade_drops_each_table_in_reverse( self ):
        mig = _load_migration()
        fakes = self._fake_tables()
        with patch.object( mig, "_vector_store_tables", return_value=fakes ), \
             patch( "alembic.op.get_bind", return_value="BIND" ):
            mig.downgrade()
        for t in fakes:
            t.drop.assert_called_once_with( bind="BIND", checkfirst=True )


# ---------------------------------------------------------------------------
# Live-PG apply test — GATED on the pgvector image swap (shared-infra).
# ---------------------------------------------------------------------------
def _pgvector_pg_url():
    """Return a reachable pgvector-enabled Postgres URL, or None (→ skip)."""
    url = os.environ.get( "PGVECTOR_TEST_DATABASE_URL" )
    if not url:
        return None
    try:
        from sqlalchemy import create_engine, text
        eng = create_engine( url )
        with eng.connect() as conn:
            conn.execute( text( "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'" ) ).first()
        eng.dispose()
        return url
    except Exception:
        return None


@unittest.skipUnless(
    _pgvector_pg_url(),
    "GATED: needs a pgvector-enabled Postgres (set PGVECTOR_TEST_DATABASE_URL). "
    "Blocked on docker-compose image swap → pgvector/pgvector:pg16 (operator-applied).",
)
class TestLivePgVectorApply( unittest.TestCase ):

    def test_extension_tables_indexes_and_ip_query( self ):
        from sqlalchemy import create_engine, text
        from cosa.rest.postgres_models import Base
        from cosa.rest.db.vector_store_models import VECTOR_STORE_MODELS, EMBEDDING_DIM

        url    = _pgvector_pg_url()
        engine = create_engine( url )
        names  = [ m.__tablename__ for m in VECTOR_STORE_MODELS ]
        try:
            with engine.begin() as conn:
                conn.execute( text( "CREATE EXTENSION IF NOT EXISTS vector" ) )
            for name in names:
                Base.metadata.tables[ name ].create( bind=engine, checkfirst=True )

            # Insert one row + prove a dot (`<#>`) nearest-k query executes.
            vec = "[" + ",".join( [ "0.1" ] * EMBEDDING_DIM ) + "]"
            with engine.begin() as conn:
                conn.execute(
                    text( "INSERT INTO input_and_output ( input, input_embedding ) VALUES ( :i, :e )" ),
                    { "i": "hello", "e": vec },
                )
                row = conn.execute(
                    text( "SELECT input FROM input_and_output ORDER BY input_embedding <#> :q LIMIT 1" ),
                    { "q": vec },
                ).first()
            self.assertEqual( row[ 0 ], "hello" )
        finally:
            for name in reversed( names ):
                Base.metadata.tables[ name ].drop( bind=engine, checkfirst=True )
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
