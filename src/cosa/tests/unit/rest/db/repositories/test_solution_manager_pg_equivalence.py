"""
RIDER-1 equivalence harness — SolutionSnapshotManager postgres backend on a REAL,
disposable pgvector database (inherits the Lane-B conftest: db_session / pg_engine,
honest-skip when no pgvector Postgres is reachable).

WHAT THIS PROVES (v0.2.0 Lane C batch 3b, cache-BYPASS design):
  In postgres mode the manager DELIBERATELY does NOT build the in-memory
  _question_lookup / _id_lookup caches the LanceDB path used. This harness proves
  the caller-visible cache-hit SEMANTICS survive that bypass:

    1. initialize() builds NO caches (both lookups stay {}).
    2. save_snapshot() persists WITHOUT populating any cache.
    3. get_snapshot_by_id() round-trips a saved snapshot marshalled off REAL pgvector.
    4. get_snapshots_by_question() returns the SAME snapshot for the SAME question
       (top hit, ~100%) via the pgvector dot tier — the cache-hit equivalent —
       while the caches stay empty throughout.

The unit-mock suite (test_lancedb_solution_manager.py TestPg*) owns branch coverage;
THIS file is the behavioral contract on real infrastructure.
"""

import os
import sys

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from cosa.rest.db.vector_store_models import EMBEDDING_DIM
from cosa.memory.solution_snapshot import SolutionSnapshot


def _vec( *first ):
    """A dim-EMBEDDING_DIM vector with `first` values up front, zero-padded."""
    v = list( first ) + [ 0.0 ] * ( EMBEDDING_DIM - len( first ) )
    return v[ :EMBEDDING_DIM ]


def _make_pg_manager( db_session, monkeypatch ):
    """
    Build a SolutionSnapshotManager flipped into postgres mode, with get_db routed to
    the test's transactional db_session and QuestionEmbeddingsTable stubbed (no I/O).
    """
    from cosa.memory import lancedb_solution_manager as lsm

    # Flip the backend flag the manager reads in __init__.
    monkeypatch.setattr( lsm, "is_postgres_backend", lambda *a, **k: True )

    # Route every `with get_db()` in the _pg_* helpers at the test session (no commit,
    # no close — the conftest fixture owns lifecycle and rolls back at teardown).
    @contextmanager
    def _fake_get_db():
        yield db_session
    monkeypatch.setattr( "cosa.rest.db.database.get_db", _fake_get_db )

    # No db_path (decision 2b20a6d6): this fixture builds the POSTGRES manager, which
    # honors no LanceDB location — passing one asserted a redirection that never
    # existed, and resolve_lancedb_path now raises on it. `storage backend` is dropped
    # with it; under postgres nothing consults it either.
    config = { "table_name": "solution_snapshots" }
    with patch.object( lsm, "QuestionEmbeddingsTable" ):
        mgr = lsm.SolutionSnapshotManager( config, debug=False )

    # Control: the postgres flip must actually have taken, and no path may survive.
    assert mgr._use_postgres is True, "postgres flip failed — this fixture tests the wrong path"
    assert mgr.db_path is None,       "a db_path survived on the postgres path"
    return mgr


def _snap( id_hash, question, embedding ):
    """A SolutionSnapshot with an explicit id_hash + question_embedding (no regeneration)."""
    return SolutionSnapshot(
        question           = question,
        id_hash            = id_hash,
        answer             = f"answer for {question}",
        question_embedding = embedding,
    )


def test_initialize_builds_no_caches( db_session, monkeypatch ):
    mgr = _make_pg_manager( db_session, monkeypatch )
    assert mgr._use_postgres is True
    mgr.initialize()
    assert mgr.is_initialized() is True
    # BYPASS PROOF: no in-memory lookups built.
    assert mgr._question_lookup == {}
    assert mgr._id_lookup == {}


def test_save_does_not_populate_cache( db_session, monkeypatch ):
    mgr = _make_pg_manager( db_session, monkeypatch )
    mgr.initialize()

    assert mgr.save_snapshot( _snap( "hash_A", "What is A?", _vec( 1.0, 0.0 ) ) ) is True
    assert mgr.save_snapshot( _snap( "hash_B", "What is B?", _vec( 0.0, 1.0 ) ) ) is True

    # Caches STILL empty after two saves — every lookup queries pgvector directly.
    assert mgr._question_lookup == {}
    assert mgr._id_lookup == {}


def test_get_snapshot_by_id_round_trips( db_session, monkeypatch ):
    mgr = _make_pg_manager( db_session, monkeypatch )
    mgr.initialize()
    mgr.save_snapshot( _snap( "hash_A", "What is A?", _vec( 1.0, 0.0 ) ) )

    fetched = mgr.get_snapshot_by_id( "hash_A" )
    assert fetched is not None
    assert fetched.id_hash == "hash_A"
    assert fetched.question == "What is A?"
    assert fetched.answer == "answer for What is A?"
    # Missing id → None (no exception).
    assert mgr.get_snapshot_by_id( "does_not_exist" ) is None


def test_same_question_returns_same_snapshot_cache_free( db_session, monkeypatch ):
    mgr = _make_pg_manager( db_session, monkeypatch )
    mgr.initialize()
    mgr.save_snapshot( _snap( "hash_A", "What is A?", _vec( 1.0, 0.0 ) ) )
    mgr.save_snapshot( _snap( "hash_B", "What is B?", _vec( 0.0, 1.0 ) ) )

    # Force straight to the pgvector Level-4 tier (the cache-hit equivalent); the
    # exact-match L1/L2 tiers go through canonical_synonyms, tested separately.
    mgr._canonical_synonyms = False
    mgr._normalizer = False
    # The query embedding for "What is A?" — the same vector snap_A was saved with.
    mgr._question_embeddings_tbl.get_embedding = lambda q: _vec( 1.0, 0.0 )

    results = mgr.get_snapshots_by_question( "What is A?" )
    assert len( results ) >= 1
    top_pct, top_snap = results[ 0 ]
    # Same question → same snapshot, at ~100% (dot of identical unit vectors).
    assert top_snap.id_hash == "hash_A"
    assert top_pct == pytest.approx( 100.0, abs=0.5 )

    # BYPASS still holds after a query.
    assert mgr._question_lookup == {}
    assert mgr._id_lookup == {}
