#!/usr/bin/env python3
"""
Guard for the backend-blind db_path defect (bug d621b111, decision 2b20a6d6).

THE DEFECT THIS GUARDS
----------------------
Classes in `cosa/memory/*` and `cosa/agents/decision_proxy/*` route on the ambient
`vector store backend` flag. Before 2026-07-27 they ACCEPTED a `db_path`, echoed it
back on the attribute, and then ignored it whenever the postgres path was active. A
caller — test or production — that believed it had redirected the store was in fact
reading and writing the SHARED one, silently. `vector store backend = postgres` has
been live in `[Lupin: Baseline]` with no per-block override since 2026-07-07, so this
was every venue, host included.

The remedy is `resolve_lancedb_path()` in vector_store_backend.py: the ONE seam every
path-taking store calls before storing or connecting. These tests pin that seam and
the four classes that consume it.

WHY A GUARD AND NOT JUST THE RAISE
----------------------------------
The raise fires at a caller's own call site, which is the right place. But nothing
stops someone re-ordering a constructor so the path is stored BEFORE the seam runs, or
adding a fifth path-taking class that never calls it. That regression would be silent
again — which is the whole shape of the original bug. These tests fail loudly instead.

Rick's ruling on decision 2b20a6d6 (2026-07-27):
    "I absolutely do not want any test touching a live dev data store! If it's not
     isolated then it needs to be removed or fixed."

Venue: :7999-eligible — no persistent-state mutation, no queue enqueues, sub-second.
Nothing here opens a database; every construction is either rejected before I/O or
runs against a mocked LanceDB boundary.
"""

import pytest
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories import vector_store_backend
from cosa.rest.db.repositories.vector_store_backend import resolve_lancedb_path


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _pin( backend ):
    """Pin the backend flag at its single definition site."""
    return patch.object( vector_store_backend, "get_vector_store_backend",
                         return_value=backend )


# --------------------------------------------------------------------------- #
# The seam itself                                                              #
# --------------------------------------------------------------------------- #

class TestResolveLancedbPath:
    """The three behaviors resolve_lancedb_path owes its callers."""

    def test_lancedb_passes_the_path_through_unchanged( self ):
        """Under lancedb the caller's path is honored — the OLD path stays first-class."""
        with _pin( vector_store_backend.LANCEDB ):
            assert resolve_lancedb_path( "/tmp/real.lancedb", "probe" ) == "/tmp/real.lancedb"
            assert resolve_lancedb_path( None, "probe" ) is None

    def test_postgres_with_no_path_returns_none( self ):
        """Nothing was promised under postgres, so nothing is broken."""
        with _pin( vector_store_backend.POSTGRES ):
            assert resolve_lancedb_path( None, "probe" ) is None

    def test_postgres_with_a_path_raises( self ):
        """
        The defect, made loud. A path that will not be honored must never be accepted.
        """
        with _pin( vector_store_backend.POSTGRES ):
            with pytest.raises( ValueError ) as exc:
                resolve_lancedb_path( "/tmp/ignored.lancedb", "MyStore" )

        msg = str( exc.value )
        assert "MyStore" in msg,                  "the message must name the offending caller"
        assert "/tmp/ignored.lancedb" in msg,     "the message must show the ignored path"
        assert "vector store backend" in msg,     "the message must name the config key to flip"

    def test_gcs_uri_is_rejected_under_postgres_too( self ):
        """A gs:// location is a location — postgres honors it no more than a local path."""
        with _pin( vector_store_backend.POSTGRES ):
            with pytest.raises( ValueError ):
                resolve_lancedb_path( "gs://bucket/db.lancedb", "SolutionSnapshotManager" )


# --------------------------------------------------------------------------- #
# Every path-taking class must consume the seam                                #
# --------------------------------------------------------------------------- #

class TestPathTakingClassesRejectUnhonoredPaths:
    """
    The four classes that accept a caller-supplied location must ALL refuse one under
    postgres. A new class that takes a path and skips the seam belongs in this list —
    if you are reading this because you added one, add it here too.

    The other flag-routing classes (EmbeddingCacheTable, QuestionEmbeddingsTable,
    InputAndOutputTable, QueryLogTable) accept NO location at all and so cannot be
    lied to; they are deliberately absent.
    """

    def test_proxy_decision_embeddings_rejects( self ):
        from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings

        with _pin( vector_store_backend.POSTGRES ):
            with pytest.raises( ValueError ):
                ProxyDecisionEmbeddings( db_path="/tmp/ignored.lancedb" )

    def test_gist_cache_table_rejects( self ):
        from cosa.memory.gist_cache_table import GistCacheTable

        with _pin( vector_store_backend.POSTGRES ):
            with pytest.raises( ValueError ):
                GistCacheTable( "/tmp/ignored.lancedb" )

    def test_canonical_synonyms_table_rejects( self ):
        from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable

        with _pin( vector_store_backend.POSTGRES ):
            with pytest.raises( ValueError ):
                CanonicalSynonymsTable( db_path="/tmp/ignored.lancedb" )

    def test_solution_snapshot_manager_rejects_db_path( self ):
        from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager

        with _pin( vector_store_backend.POSTGRES ), \
             patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ):
            with pytest.raises( ValueError ):
                SolutionSnapshotManager( {
                    "table_name" : "t",
                    "db_path"    : "/tmp/ignored.lancedb"
                } )

    def test_solution_snapshot_manager_rejects_gcs_uri( self ):
        from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager

        with _pin( vector_store_backend.POSTGRES ), \
             patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ):
            with pytest.raises( ValueError ):
                SolutionSnapshotManager( {
                    "table_name" : "t",
                    "gcs_uri"    : "gs://bucket/db.lancedb"
                } )


# --------------------------------------------------------------------------- #
# The postgres path must remain constructible                                  #
# --------------------------------------------------------------------------- #

class TestPostgresPathStaysConstructible:
    """
    The raise must not make the CORRECT postgres config unbuildable.

    This is the regression that broke server startup on 2026-07-27: main.py stopped
    building a LanceDB path under postgres (correctly), and a factory gate then
    rejected the only valid config. Both halves are pinned here.
    """

    def test_manager_builds_with_table_name_only( self ):
        from cosa.memory.lancedb_solution_manager import SolutionSnapshotManager

        with _pin( vector_store_backend.POSTGRES ), \
             patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ):
            mgr = SolutionSnapshotManager( { "table_name" : "solution_snapshots" } )

        assert mgr._use_postgres is True
        assert mgr.db_path is None, "no path may be advertised on the postgres path"

    def test_factory_accepts_location_free_config_under_postgres( self ):
        from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory

        with _pin( vector_store_backend.POSTGRES ), \
             patch( "cosa.memory.lancedb_solution_manager.QuestionEmbeddingsTable" ):
            mgr = SolutionSnapshotManagerFactory.create_manager(
                "lancedb", { "table_name" : "solution_snapshots" }, debug=False, verbose=False
            )

        assert mgr is not None

    def test_proxy_decision_embeddings_builds_without_a_path( self ):
        from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings

        with _pin( vector_store_backend.POSTGRES ):
            store = ProxyDecisionEmbeddings( table_name="proxy_decisions" )

        assert store._use_postgres is True
        assert store.db_path is None


# --------------------------------------------------------------------------- #
# The LanceDB path must remain first-class                                     #
# --------------------------------------------------------------------------- #

class TestLancedbPathStaysFirstClass:
    """
    Feature-flag doctrine: BOTH paths stay first-class so the cutover can be rolled
    back. A guard that only proved postgres works would let the lancedb path rot.
    """

    def test_factory_still_demands_a_location_under_lancedb( self ):
        import cosa.memory.solution_manager_factory as smf

        with _pin( vector_store_backend.LANCEDB ), \
             patch.object( smf, "is_postgres_backend", return_value=False ):
            with pytest.raises( KeyError ):
                smf.SolutionSnapshotManagerFactory._create_lancedb_manager(
                    { "table_name" : "t" }, False, False
                )

    def test_gist_cache_table_uses_the_path_under_lancedb( self ):
        from cosa.memory.gist_cache_table import GistCacheTable

        mock_db = MagicMock()
        mock_db.table_names.return_value = []

        with _pin( vector_store_backend.LANCEDB ), \
             patch( "cosa.memory.gist_cache_table.lancedb" ) as mock_lancedb, \
             patch( "cosa.memory.gist_cache_table.Normalizer" ):
            mock_lancedb.connect.return_value = mock_db
            cache = GistCacheTable( "/tmp/honored.lancedb" )

        assert cache._use_postgres is False
        mock_lancedb.connect.assert_called_once_with( "/tmp/honored.lancedb" )
