#!/usr/bin/env python3
"""
Unit tests for cosa.agents.decision_proxy.proxy_decision_embeddings.

ProxyDecisionEmbeddings is a LanceDB vector store. The LanceDB boundary is
fully mocked — lancedb.connect is patched for _ensure_table tests, and the
table handle is injected directly (so _ensure_table short-circuits via its
cached branch) for the add/search/update tests. NO real index is ever
opened, NO embedding API is ever called. _get_schema uses real pyarrow
(pure, no I/O). Zero spend.
"""

from unittest.mock import patch, MagicMock

from cosa.agents.decision_proxy import proxy_decision_embeddings as pde
from cosa.agents.decision_proxy.proxy_decision_embeddings import ProxyDecisionEmbeddings


def _ready_store( **kwargs ):
    """Store with an injected table mock → _ensure_table returns True (cached)."""
    store = ProxyDecisionEmbeddings( "/db", **kwargs )
    store._table = MagicMock()
    return store


def _chain_search( records ):
    """A chainable LanceDB search mock whose terminal .to_list() yields records."""
    s = MagicMock()
    s.metric.return_value   = s
    s.nprobes.return_value  = s
    s.limit.return_value    = s
    s.where.return_value    = s
    s.to_list.return_value  = records
    return s


# ============================================================================
# __init__ / _get_schema
# ============================================================================
def test_init_stores_config():
    store = ProxyDecisionEmbeddings( "/db", table_name="t", embedding_dim=128, nprobes=10, debug=True )
    assert store.db_path == "/db"
    assert store.table_name == "t"
    assert store.embedding_dim == 128
    assert store.nprobes == 10
    assert store.debug is True
    assert store._db is None
    assert store._table is None


def test_get_schema_has_expected_fields():
    store = ProxyDecisionEmbeddings( "/db" )
    names = store._get_schema().names
    for f in ( "id", "question", "category", "decision_value", "ratification_state",
               "data_origin", "response_type", "question_embedding", "created_at" ):
        assert f in names


# ============================================================================
# _ensure_table
# ============================================================================
def test_ensure_table_cached_skips_connect():
    store = ProxyDecisionEmbeddings( "/db" )
    store._table = MagicMock()
    with patch.object( pde.lancedb, "connect" ) as conn:
        assert store._ensure_table() is True
    conn.assert_not_called()


def test_ensure_table_creates_new_when_absent( capsys ):
    store = ProxyDecisionEmbeddings( "/db", debug=True )
    db = MagicMock()
    db.table_names.return_value = []
    created = MagicMock()
    db.create_table.return_value = created
    with patch.object( pde.lancedb, "connect", return_value=db ):
        assert store._ensure_table() is True
    assert store._table is created
    db.create_table.assert_called_once()
    assert "Created new table" in capsys.readouterr().out


def test_ensure_table_creates_new_quiet():
    store = ProxyDecisionEmbeddings( "/db", debug=False )
    db = MagicMock()
    db.table_names.return_value = []
    with patch.object( pde.lancedb, "connect", return_value=db ):
        assert store._ensure_table() is True


def test_ensure_table_opens_existing_matching_schema( capsys ):
    store = ProxyDecisionEmbeddings( "/db", debug=True )
    expected = list( store._get_schema().names )
    db = MagicMock()
    db.table_names.return_value = [ store.table_name ]
    tbl = MagicMock()
    tbl.schema.names = expected
    db.open_table.return_value = tbl
    with patch.object( pde.lancedb, "connect", return_value=db ):
        assert store._ensure_table() is True
    assert store._table is tbl
    assert "Opened existing table" in capsys.readouterr().out


def test_ensure_table_opens_existing_quiet():
    store = ProxyDecisionEmbeddings( "/db", debug=False )
    expected = list( store._get_schema().names )
    db = MagicMock()
    db.table_names.return_value = [ store.table_name ]
    tbl = MagicMock()
    tbl.schema.names = expected
    db.open_table.return_value = tbl
    with patch.object( pde.lancedb, "connect", return_value=db ):
        assert store._ensure_table() is True


def test_ensure_table_schema_mismatch_recreates( capsys ):
    store = ProxyDecisionEmbeddings( "/db" )
    db = MagicMock()
    db.table_names.return_value = [ store.table_name ]
    stale = MagicMock()
    stale.schema.names = [ "id" ]            # missing columns → mismatch
    db.open_table.return_value = stale
    recreated = MagicMock()
    db.create_table.return_value = recreated
    with patch.object( pde.lancedb, "connect", return_value=db ):
        assert store._ensure_table() is True
    db.drop_table.assert_called_once_with( store.table_name )
    assert store._table is recreated
    assert "Schema mismatch" in capsys.readouterr().out


def test_ensure_table_failure_returns_false( capsys ):
    store = ProxyDecisionEmbeddings( "/db", debug=True )
    with patch.object( pde.lancedb, "connect", side_effect=RuntimeError( "no db" ) ):
        assert store._ensure_table() is False
    assert "Failed to initialize" in capsys.readouterr().out


def test_ensure_table_failure_quiet():
    store = ProxyDecisionEmbeddings( "/db", debug=False )
    with patch.object( pde.lancedb, "connect", side_effect=RuntimeError( "x" ) ):
        assert store._ensure_table() is False


# ============================================================================
# add_decision
# ============================================================================
def test_add_decision_success_builds_record( capsys ):
    store = _ready_store( debug=True )
    store.add_decision( id="x", question="q", category="c", decision_value="v",
                        ratification_state="pending", question_embedding=[ 0.1, 0.2 ],
                        created_at="ts" )
    args, _ = store._table.add.call_args
    rec = args[ 0 ][ 0 ]
    assert rec[ "id" ] == "x"
    assert rec[ "data_origin" ] == "organic"      # default
    assert rec[ "response_type" ] == ""           # default
    assert rec[ "question_embedding" ] == [ 0.1, 0.2 ]
    assert "Added decision: x" in capsys.readouterr().out


def test_add_decision_success_quiet():
    store = _ready_store( debug=False )
    store.add_decision( id="x", question="q", category="c", decision_value="v",
                        ratification_state="p", question_embedding=[], created_at="t" )
    store._table.add.assert_called_once()


def test_add_decision_returns_when_table_unavailable():
    store = ProxyDecisionEmbeddings( "/db" )
    store._ensure_table = MagicMock( return_value=False )
    store.add_decision( id="x", question="q", category="c", decision_value="v",
                        ratification_state="p", question_embedding=[], created_at="t" )
    store._ensure_table.assert_called_once()      # early return, no crash


def test_add_decision_exception_swallowed_debug( capsys ):
    store = _ready_store( debug=True )
    store._table.add.side_effect = RuntimeError( "boom" )
    store.add_decision( id="x", question="q", category="c", decision_value="v",
                        ratification_state="p", question_embedding=[], created_at="t" )
    assert "add_decision failed" in capsys.readouterr().out


def test_add_decision_exception_swallowed_quiet( capsys ):
    store = _ready_store( debug=False )
    store._table.add.side_effect = RuntimeError( "boom" )
    store.add_decision( id="x", question="q", category="c", decision_value="v",
                        ratification_state="p", question_embedding=[], created_at="t" )
    assert capsys.readouterr().out == ""


# ============================================================================
# find_similar
# ============================================================================
def test_find_similar_returns_empty_when_table_unavailable():
    store = ProxyDecisionEmbeddings( "/db" )
    store._ensure_table = MagicMock( return_value=False )
    assert store.find_similar( [ 0.1 ] ) == []


def test_find_similar_basic_no_filters_strips_internal_fields():
    store = _ready_store()
    search = _chain_search( [ { "id": "a", "_distance": 0.1, "_rowid": 7, "category": "c" } ] )
    store._table.search.return_value = search
    out = store.find_similar( [ 0.1, 0.2 ], threshold=0.75 )
    assert len( out ) == 1
    sim, rec = out[ 0 ]
    assert sim == 90.0                             # (1 - 0.1) * 100
    assert "_distance" not in rec and "_rowid" not in rec
    assert rec[ "id" ] == "a"
    search.where.assert_not_called()               # no filters → no where clause


def test_find_similar_with_all_filters_builds_escaped_where( capsys ):
    store = _ready_store( debug=True )
    search = _chain_search( [ { "id": "a", "_distance": 0.0, "category": "c" } ] )
    store._table.search.return_value = search
    store.find_similar( [ 0.1 ], category="c'x", data_origin="organic",
                        response_type="yes_no", threshold=0.5 )
    where_arg = search.where.call_args[ 0 ][ 0 ]
    assert "category = 'c''x'" in where_arg         # single-quote escaped
    assert "data_origin = 'organic'" in where_arg
    assert "response_type = 'yes_no'" in where_arg
    assert " AND " in where_arg
    assert "find_similar:" in capsys.readouterr().out


def test_find_similar_excludes_below_threshold():
    store = _ready_store()
    store._table.search.return_value = _chain_search( [ { "id": "a", "_distance": 0.9 } ] )  # sim 10
    assert store.find_similar( [ 0.1 ], threshold=0.75 ) == []


def test_find_similar_missing_distance_treated_as_zero():
    store = _ready_store()
    store._table.search.return_value = _chain_search( [ { "id": "a" } ] )   # no _distance → sim 100
    out = store.find_similar( [ 0.1 ], threshold=0.5 )
    assert out[ 0 ][ 0 ] == 100.0


def test_find_similar_sorts_descending():
    store = _ready_store()
    recs = [ { "id": "low", "_distance": 0.4 }, { "id": "high", "_distance": 0.0 } ]
    store._table.search.return_value = _chain_search( recs )
    out = store.find_similar( [ 0.1 ], threshold=0.5 )
    assert [ r[ "id" ] for _, r in out ] == [ "high", "low" ]


def test_find_similar_exception_returns_empty():
    store = _ready_store()
    store._table.search.side_effect = RuntimeError( "boom" )
    assert store.find_similar( [ 0.1 ] ) == []


# ============================================================================
# update_ratification_state
# ============================================================================
def test_update_returns_when_table_unavailable():
    store = ProxyDecisionEmbeddings( "/db" )
    store._ensure_table = MagicMock( return_value=False )
    store.update_ratification_state( "x", "new" )     # no crash
    store._ensure_table.assert_called_once()


def test_update_record_not_found_debug( capsys ):
    store = _ready_store( debug=True )
    search = MagicMock()
    search.where.return_value = search
    search.limit.return_value = search
    search.to_list.return_value = []
    store._table.search.return_value = search
    store.update_ratification_state( "x", "new" )
    assert "Record not found" in capsys.readouterr().out


def test_update_success_merges( capsys ):
    store = _ready_store( debug=True )
    search = MagicMock()
    search.where.return_value = search
    search.limit.return_value = search
    search.to_list.return_value = [ { "id": "x", "ratification_state": "old",
                                      "category": "c", "_distance": 0.1 } ]
    store._table.search.return_value = search
    merge = MagicMock()
    merge.when_matched_update_all.return_value = merge
    store._table.merge_insert.return_value = merge
    store.update_ratification_state( "x", "new" )
    store._table.merge_insert.assert_called_once_with( "id" )
    merge.execute.assert_called_once()
    assert "Updated ratification state" in capsys.readouterr().out


def test_update_exception_swallowed_debug( capsys ):
    store = _ready_store( debug=True )
    store._table.search.side_effect = RuntimeError( "boom" )
    store.update_ratification_state( "x", "new" )
    assert "update_ratification_state failed" in capsys.readouterr().out


def test_update_exception_swallowed_quiet( capsys ):
    store = _ready_store( debug=False )
    store._table.search.side_effect = RuntimeError( "boom" )
    store.update_ratification_state( "x", "new" )
    assert capsys.readouterr().out == ""
