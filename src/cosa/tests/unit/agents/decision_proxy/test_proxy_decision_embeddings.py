#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.proxy_decision_embeddings.

REWRITTEN 2026-08-17 by Pocholo 📣 (LanceDB total-removal sweep, Lane A —
the seventh module the spec's count missed, rows 5ff7b8f5 / 8098838f). The
LanceDB path is gone, and with it db_path, nprobes, _get_schema, _ensure_table
and the whole `.search().metric().nprobes()` chain. The tests that covered them
were testing deleted code and were DELETED, not skipped.

What remains is the Postgres path, which was already the only one running in
every INI section: five methods that open a short-lived get_db() session and
delegate to PredictionDecisionRepository, every one of them best-effort — a
failure is logged under debug and never propagates. NO real index is ever
opened, NO embedding API is ever called. Zero spend.
"""

import contextlib
from unittest.mock import patch, MagicMock

from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings


_EMB = [ 0.1 ] * 768


@contextlib.contextmanager
def _repo():
    """Patch get_db (ctx mgr) + PredictionDecisionRepository; yield the repo mock."""
    session   = MagicMock()
    repo_inst = MagicMock()

    @contextlib.contextmanager
    def fake_get_db():
        yield session

    with patch( "cosa.rest.db.database.get_db", fake_get_db ), \
         patch( "cosa.rest.db.repositories.prediction_decision_repository.PredictionDecisionRepository",
                return_value=repo_inst ):
        yield repo_inst


# ===========================================================================
# __init__
# ===========================================================================

def test_init_stores_config():
    store = ProxyDecisionEmbeddings( table_name="t", embedding_dim=128, debug=True )
    assert store.table_name    == "t"
    assert store.embedding_dim == 128
    assert store.debug is True


def test_init_defaults():
    store = ProxyDecisionEmbeddings()
    assert store.table_name    == "proxy_decisions"
    assert store.embedding_dim == 768
    assert store.debug is False


# ===========================================================================
# add_decision
# ===========================================================================

def test_add_decision_delegates():
    store = ProxyDecisionEmbeddings()
    with _repo() as repo:
        store.add_decision( "id1", "q", "cat", "yes", "pending", _EMB, "2026-07-01",
                            data_origin="organic", response_type="yes_no" )
    kw = repo.add_decision.call_args.kwargs
    assert kw[ "id" ] == "id1" and kw[ "question_embedding" ] == _EMB
    assert kw[ "data_origin" ] == "organic"
    assert kw[ "response_type" ] == "yes_no"


def test_add_decision_default_origin_is_organic():
    store = ProxyDecisionEmbeddings()
    with _repo() as repo:
        store.add_decision( "id1", "q", "cat", "yes", "pending", _EMB, "2026-07-01" )
    kw = repo.add_decision.call_args.kwargs
    assert kw[ "data_origin" ] == "organic"
    assert kw[ "response_type" ] == ""


def test_add_decision_logs_on_success_under_debug( capsys ):
    store = ProxyDecisionEmbeddings( debug=True )
    with _repo():
        store.add_decision( "id1", "q", "c", "v", "s", _EMB, "t" )
    assert "Added decision: id1" in capsys.readouterr().out


def test_add_decision_non_fatal( capsys ):
    store = ProxyDecisionEmbeddings( debug=True )
    with _repo() as repo:
        repo.add_decision.side_effect = RuntimeError( "boom" )
        store.add_decision( "id1", "q", "c", "v", "s", _EMB, "t" )   # must not raise
    assert "non-fatal" in capsys.readouterr().out


# ===========================================================================
# find_similar
# ===========================================================================

def test_find_similar_maps_pct_and_clean_record():
    store = ProxyDecisionEmbeddings()
    entity = MagicMock( id="id1", question="q", category="c", decision_value="yes",
                        ratification_state="pending", data_origin="organic",
                        response_type="yes_no", question_embedding=[ 0.2 ] * 768, created_at="t" )
    with _repo() as repo:
        repo.find_similar.return_value = [ ( 88.0, entity ) ]
        out = store.find_similar( [ 0.2 ] * 768, category="c", limit=5, threshold=0.75 )
    assert out[ 0 ][ 0 ] == 88.0
    rec = out[ 0 ][ 1 ]
    assert rec[ "id" ] == "id1" and rec[ "question_embedding" ] == [ 0.2 ] * 768
    assert not any( k.startswith( "_" ) for k in rec )      # clean record


def test_find_similar_forwards_every_filter():
    store = ProxyDecisionEmbeddings()
    with _repo() as repo:
        repo.find_similar.return_value = []
        store.find_similar( _EMB, category="c", limit=9, threshold=0.5,
                            data_origin="organic", response_type="yes_no" )
    kw = repo.find_similar.call_args.kwargs
    assert kw[ "category" ] == "c" and kw[ "limit" ] == 9 and kw[ "threshold" ] == 0.5
    assert kw[ "data_origin" ] == "organic" and kw[ "response_type" ] == "yes_no"


def test_find_similar_null_embedding_and_non_fatal( capsys ):
    store = ProxyDecisionEmbeddings( debug=True )
    entity = MagicMock( id="id1", question="q", category="c", decision_value="v",
                        ratification_state="s", data_origin="o", response_type="r",
                        question_embedding=None, created_at="t" )
    with _repo() as repo:
        repo.find_similar.return_value = [ ( 90.0, entity ) ]
        out = store.find_similar( [ 0.2 ] * 768 )
    assert out[ 0 ][ 1 ][ "question_embedding" ] is None

    with _repo() as repo:
        repo.find_similar.side_effect = RuntimeError( "boom" )
        assert store.find_similar( [ 0.2 ] * 768 ) == []
    assert "non-fatal" in capsys.readouterr().out


# ===========================================================================
# exists
# ===========================================================================

def test_exists_true_false_and_error():
    store = ProxyDecisionEmbeddings( debug=True )
    with _repo() as repo:
        repo.exists.return_value = True
        assert store.exists( "id1" ) is True
    with _repo() as repo:
        repo.exists.return_value = False
        assert store.exists( "id1" ) is False
    with _repo() as repo:
        repo.exists.side_effect = RuntimeError( "boom" )
        assert store.exists( "id1" ) is False


# ===========================================================================
# update_ratification_state
# ===========================================================================

def test_update_ratification_found_missing_and_error( capsys ):
    store = ProxyDecisionEmbeddings( debug=True )
    with _repo() as repo:
        repo.update_ratification_state.return_value = MagicMock()      # found
        store.update_ratification_state( "id1", "ratified" )
    assert "Updated ratification state: id1 -> ratified" in capsys.readouterr().out

    with _repo() as repo:
        repo.update_ratification_state.return_value = None             # missing
        store.update_ratification_state( "id1", "ratified" )
    assert "Record not found for update: id1" in capsys.readouterr().out

    with _repo() as repo:
        repo.update_ratification_state.side_effect = RuntimeError( "boom" )
        store.update_ratification_state( "id1", "ratified" )
    assert "non-fatal" in capsys.readouterr().out


def test_ops_quiet_when_debug_off( capsys ):
    """debug=False → every branch takes the no-log arc (success, missing, and error)."""
    store = ProxyDecisionEmbeddings( debug=False )
    with _repo() as repo:
        repo.add_decision.side_effect = RuntimeError( "boom" )
        store.add_decision( "id1", "q", "c", "v", "s", _EMB, "t" )
        repo.update_ratification_state.return_value = MagicMock()
        store.update_ratification_state( "id1", "new" )
        repo.find_similar.side_effect = RuntimeError( "boom" )
        store.find_similar( _EMB )
        repo.exists.side_effect = RuntimeError( "boom" )
        store.exists( "id1" )
    assert capsys.readouterr().out == ""


def test_add_decision_success_quiet( capsys ):
    store = ProxyDecisionEmbeddings( debug=False )
    with _repo():
        store.add_decision( "id1", "q", "c", "v", "s", _EMB, "t" )
    assert capsys.readouterr().out == ""


# ===========================================================================
# The removal itself
# ===========================================================================

def test_module_does_not_import_lancedb():
    from cosa.agents.decision_proxy import proxy_decision_embeddings as mod
    assert not hasattr( mod, "lancedb" )
    assert not hasattr( mod, "pa" )


def test_lancedb_only_members_are_gone():
    for name in ( "_get_schema", "_ensure_table", "_pg_add_decision", "_pg_find_similar" ):
        assert not hasattr( ProxyDecisionEmbeddings, name ), f"{name} should be deleted"


def test_ctor_takes_no_db_path_or_nprobes():
    import inspect
    params = list( inspect.signature( ProxyDecisionEmbeddings.__init__ ).parameters )
    assert "db_path" not in params
    assert "nprobes" not in params


def test_write_lock_is_still_shared_and_reentrant():
    """PredictionEngine.record_hint_vote holds this across an exists()→(update|add) compound."""
    a = ProxyDecisionEmbeddings()
    b = ProxyDecisionEmbeddings()
    assert a._write_lock is b._write_lock
    with a._write_lock:
        with a._write_lock:      # re-entrant: must not deadlock
            pass
