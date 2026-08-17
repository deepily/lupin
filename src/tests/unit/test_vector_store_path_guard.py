#!/usr/bin/env python3
"""
Guard for the backend-blind db_path defect (bug d621b111, decision 2b20a6d6).

THE DEFECT THIS GUARDS
----------------------
Classes in `cosa/memory/*` and `cosa/agents/decision_proxy/*` used to ACCEPT a
caller-supplied store location, echo it back on an attribute, and then ignore it.
A caller — test or production — that believed it had redirected the store was in
fact reading and writing the SHARED one, silently.

HOW THE REMEDY CHANGED, AND WHY THIS FILE CHANGED WITH IT
---------------------------------------------------------
The first remedy was a raise: `resolve_lancedb_path()` rejected a location that
would not be honored, at the caller's own call site. That was the right fix while
two backends existed and a constructor still had a location parameter to lie with.

There is one backend now, and the constructors no longer take a location at all.
So the guard moves up a level: instead of proving each class REFUSES a bad path,
it proves each class CANNOT BE OFFERED one. A signature that has no location
parameter cannot be lied to, and no ordering of statements inside a constructor
can reintroduce the defect. Checking the shape beats checking the behaviour,
because the shape cannot regress quietly.

WHAT WOULD STILL BE SILENT
--------------------------
A constructor that swallows `**kwargs` accepts `db_path=` without complaint. That
is the original defect's exact shape, so the swallowers are probed directly: they
may accept the word, but they must not keep it.

Rick's ruling on decision 2b20a6d6 (2026-07-27):
    "I absolutely do not want any test touching a live dev data store! If it's not
     isolated then it needs to be removed or fixed."

Venue: :7999-eligible — no persistent-state mutation, no queue enqueues, sub-second.
Nothing here opens a database.

Rewritten 2026-08-17 (row 8098838f, Rachel 🕊️) — the cache-layer lane removed the
location parameters, which turned every `pytest.raises( ValueError )` here into a
DID NOT RAISE.
"""

import inspect

import pytest
from unittest.mock import patch

from cosa.rest.db.repositories import vector_store_backend
from cosa.rest.db.repositories.vector_store_backend import resolve_lancedb_path


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _pin( backend ):
    """Pin the backend flag at its single definition site."""
    return patch.object( vector_store_backend, "get_vector_store_backend",
                         return_value=backend )


# Every spelling a store location has ever gone by in this codebase. A new one
# belongs here the day it is invented.
_LOCATION_PARAM_NAMES = ( "db_path", "gcs_uri", "db_uri", "uri", "path", "location" )


def _store_classes():
    """
    The flag-routing stores, imported lazily so a collection error names the class.

    Ensures:
        - returns [(label, class)] for every store that routes on the backend flag
    """
    from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings
    from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable
    from cosa.memory.embedding_cache_table import EmbeddingCacheTable
    from cosa.memory.gist_cache_table import GistCacheTable
    from cosa.memory.input_and_output_table import InputAndOutputTable
    from cosa.memory.query_log_table import QueryLogTable
    from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable

    return [
        ( "ProxyDecisionEmbeddings", ProxyDecisionEmbeddings ),
        ( "CanonicalSynonymsTable",  CanonicalSynonymsTable  ),
        ( "EmbeddingCacheTable",     EmbeddingCacheTable     ),
        ( "GistCacheTable",          GistCacheTable          ),
        ( "InputAndOutputTable",     InputAndOutputTable     ),
        ( "QueryLogTable",           QueryLogTable           ),
        ( "QuestionEmbeddingsTable", QuestionEmbeddingsTable ),
    ]


# --------------------------------------------------------------------------- #
# The seam itself                                                              #
# --------------------------------------------------------------------------- #

class TestResolveLancedbPath:
    """The three behaviors resolve_lancedb_path owes its callers."""

    def test_lancedb_passes_the_path_through_unchanged( self ):
        """Under the on-disk backend the caller's path is honored, unchanged."""
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
                resolve_lancedb_path( "gs://bucket/db.lancedb", "SnapshotStore" )


# --------------------------------------------------------------------------- #
# No store may accept a location at all                                        #
# --------------------------------------------------------------------------- #

class TestNoStoreAcceptsALocation:
    """
    The structural form of the guard: a constructor with no location parameter
    cannot be handed a location it will not honor.

    This replaces the older "each class must RAISE on a bad path" tests. Those
    became DID NOT RAISE the moment the cache-layer lane deleted the parameters —
    a green-to-red flip that meant the defect had been designed out, not that the
    guard had broken. A class added later that takes a path fails here loudly.
    """

    @pytest.mark.parametrize( "label,cls", _store_classes(),
                              ids=[ label for label, _ in _store_classes() ] )
    def test_constructor_takes_no_location_parameter( self, label, cls ):
        params = inspect.signature( cls.__init__ ).parameters
        offenders = [ name for name in params if name in _LOCATION_PARAM_NAMES ]
        assert not offenders, (
            f"{label}.__init__ accepts {offenders} — a caller can hand it a store "
            f"location that nothing honors. There is one backend; the location "
            f"belongs in configuration, not in a constructor argument."
        )

    @pytest.mark.parametrize( "label,cls", _store_classes(),
                              ids=[ label for label, _ in _store_classes() ] )
    def test_a_kwargs_swallowing_constructor_keeps_no_location( self, label, cls ):
        """
        `**kwargs` accepts `db_path=` silently — that IS the original defect's shape.

        A swallower is allowed (it keeps old call sites working), but it must not
        retain what it swallowed: no location may end up on the instance.
        """
        params = inspect.signature( cls.__init__ ).parameters
        swallows = any( p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values() )
        if not swallows:
            pytest.skip( f"{label} does not swallow **kwargs — nothing to probe" )

        instance = cls( db_path="/tmp/ignored.lancedb", gcs_uri="gs://bucket/db.lancedb" )
        for name in _LOCATION_PARAM_NAMES:
            assert getattr( instance, name, None ) is None, (
                f"{label} swallowed {name!r} through **kwargs and kept it — the caller "
                f"now believes it redirected a store that never moved."
            )


# --------------------------------------------------------------------------- #
# The postgres path must remain constructible                                  #
# --------------------------------------------------------------------------- #

class TestPostgresPathStaysConstructible:
    """
    Designing the location out must not make the CORRECT config unbuildable.

    This is the regression that broke server startup on 2026-07-27: main.py stopped
    building a store path under postgres (correctly), and a factory gate then
    rejected the only valid config. Both halves are pinned here.
    """

    def test_manager_builds_with_table_name_only( self ):
        from cosa.memory.postgres_solution_manager import PostgresSolutionManager

        with patch( "cosa.memory.question_embeddings_table.QuestionEmbeddingsTable" ):
            mgr = PostgresSolutionManager( { "table_name" : "solution_snapshots" } )

        assert mgr.db_path is None, "no path may be advertised on the postgres path"

    def test_manager_advertises_no_path_even_when_the_config_carries_one( self ):
        """
        A stale config key must not resurface as an attribute callers trust.

        The manager honors no location, so publishing one back would recreate the
        original lie through the config dict instead of the constructor signature.
        """
        from cosa.memory.postgres_solution_manager import PostgresSolutionManager

        with patch( "cosa.memory.question_embeddings_table.QuestionEmbeddingsTable" ):
            mgr = PostgresSolutionManager( {
                "table_name" : "solution_snapshots",
                "db_path"    : "/tmp/ignored.lancedb",
            } )

        assert mgr.db_path is None

    def test_factory_accepts_location_free_config_under_postgres( self ):
        from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory

        with patch( "cosa.memory.question_embeddings_table.QuestionEmbeddingsTable" ):
            mgr = SolutionSnapshotManagerFactory.create_manager(
                "postgres", { "table_name" : "solution_snapshots" }, debug=False, verbose=False
            )

        assert mgr is not None

    def test_proxy_decision_embeddings_builds_without_a_path( self ):
        from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings

        store = ProxyDecisionEmbeddings( table_name="proxy_decisions" )

        assert store is not None
        assert getattr( store, "db_path", None ) is None
