"""
Unit tests for cosa.memory.query_log_table.QueryLogTable.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign). The
prior tests left lancedb unmocked-as-a-list (db.table_names() returned a Mock →
"argument of type 'Mock' is not iterable" at __init__) and asserted a stale
get_cache_hit_stats shape ({total_queries, verbatim_hit_rate, ...}). The current
API returns {"verbatim": pct, "normalized": pct, "total_queries": n} on data,
or {"verbatim": 0.0, "normalized": 0.0} when empty / on error, and log_query
returns a datetime-string id (or "" on failure) after a single
_query_log_table.add([row]).

The full ctor chain (ConfigurationManager [per-key], lancedb.connect → mock db
with table_names()=["query_log"]) is mocked so no real DB I/O occurs. Reviewed
by Mr. Radio (no self-audit).
"""
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.query_log_table import QueryLogTable


def _cfg():
    m = Mock()
    m.get.side_effect = lambda key, default=None, **kw: {
        "normalization version":                "v2.0",
        "llm spec key for gist generation":     "gpt-x",
        "path to database wo root":             "/test/db",
    }.get( key, default )
    return m


def _make_table( debug=False ):
    """Build a QueryLogTable with config + lancedb mocked; return (table, mock_table)."""
    mock_db = MagicMock()
    mock_db.table_names.return_value = [ "query_log" ]      # open (not create) path
    mock_table = MagicMock()
    mock_db.open_table.return_value = mock_table
    with patch( "cosa.memory.query_log_table.ConfigurationManager", return_value=_cfg() ), \
         patch( "cosa.memory.query_log_table.lancedb.connect", return_value=mock_db ), \
         patch( "builtins.print" ):
        table = QueryLogTable( debug=debug )
    return table, mock_table


class TestLogQuery( unittest.TestCase ):
    """log_query() — row construction + add + id return, error swallowed."""

    def test_logs_row_and_returns_id( self ):
        table, mock_table = _make_table()
        qid = table.log_query(
            query_verbatim="What time is it?",
            query_normalized="what time is it",
            query_gist="time request",
            user_id="user-1",
            session_id="sess-1",
            embeddings={ "verbatim": [ 0.1 ], "normalized": [ 0.2 ] },
            match_result={ "snapshot_id": "snap-9", "type": "verbatim", "confidence": 0.99 },
            cache_hits={ "verbatim": True, "normalized": False },
        )
        self.assertIsInstance( qid, str )
        self.assertNotEqual( qid, "" )
        mock_table.add.assert_called_once()
        # The single positional arg is a one-row list whose row carries the inputs.
        row = mock_table.add.call_args.args[ 0 ][ 0 ]
        self.assertEqual( row[ "query_verbatim" ], "What time is it?" )
        self.assertEqual( row[ "matched_snapshot_id" ], "snap-9" )
        self.assertTrue( row[ "cache_hit_verbatim" ] )
        self.assertEqual( row[ "embedding_normalized" ], [ 0.2 ] )

    def test_defaults_when_optionals_omitted( self ):
        table, mock_table = _make_table()
        table.log_query( "v", "n", "g", "user-1" )
        row = mock_table.add.call_args.args[ 0 ][ 0 ]
        self.assertEqual( row[ "embedding_verbatim" ], [] )
        self.assertEqual( row[ "match_type" ], "none" )
        self.assertFalse( row[ "cache_hit_normalized" ] )

    def test_add_error_returns_empty_string( self ):
        table, mock_table = _make_table()
        mock_table.add.side_effect = RuntimeError( "db write failed" )
        with patch( "cosa.memory.query_log_table.du.print_stack_trace" ) as trace:
            qid = table.log_query( "v", "n", "g", "user-1" )
        self.assertEqual( qid, "" )
        trace.assert_called_once()


class TestGetRecentQueries( unittest.TestCase ):
    """get_recent_queries() — filter, sort-desc, error fallback."""

    def test_returns_sorted_descending( self ):
        table, mock_table = _make_table()
        rows = [ { "timestamp": "2026-05-16", "id": "a" }, { "timestamp": "2026-05-18", "id": "b" } ]
        mock_table.search.return_value.limit.return_value.to_list.return_value = list( rows )
        result = table.get_recent_queries( limit=10 )
        self.assertEqual( [ r[ "id" ] for r in result ], [ "b", "a" ] )   # most-recent first

    def test_user_id_filter_applies_where( self ):
        table, mock_table = _make_table()
        chain = mock_table.search.return_value
        chain.where.return_value.limit.return_value.to_list.return_value = []
        table.get_recent_queries( limit=5, user_id="user-1" )
        chain.where.assert_called_once_with( "user_id = 'user-1'" )

    def test_error_returns_empty_list( self ):
        table, mock_table = _make_table()
        mock_table.search.side_effect = RuntimeError( "boom" )
        self.assertEqual( table.get_recent_queries(), [] )


class TestGetCacheHitStats( unittest.TestCase ):
    """get_cache_hit_stats() — empty, computed rates, error fallback."""

    def _wire( self, mock_table, to_list ):
        mock_table.search.return_value.where.return_value.to_list.return_value = to_list

    def test_empty_returns_zero_rates( self ):
        table, mock_table = _make_table()
        self._wire( mock_table, [] )
        self.assertEqual( table.get_cache_hit_stats(), { "verbatim": 0.0, "normalized": 0.0 } )

    def test_computes_hit_rates( self ):
        table, mock_table = _make_table()
        self._wire( mock_table, [
            { "cache_hit_verbatim": True,  "cache_hit_normalized": False },
            { "cache_hit_verbatim": True,  "cache_hit_normalized": True  },
            { "cache_hit_verbatim": False, "cache_hit_normalized": False },
            { "cache_hit_verbatim": False, "cache_hit_normalized": True  },
        ] )
        stats = table.get_cache_hit_stats( days=7 )
        self.assertEqual( stats[ "total_queries" ], 4 )
        self.assertEqual( stats[ "verbatim" ], 50.0 )      # 2/4
        self.assertEqual( stats[ "normalized" ], 50.0 )    # 2/4

    def test_error_returns_zero_rates( self ):
        table, mock_table = _make_table()
        mock_table.search.side_effect = RuntimeError( "boom" )
        self.assertEqual( table.get_cache_hit_stats(), { "verbatim": 0.0, "normalized": 0.0 } )


if __name__ == "__main__":
    unittest.main()
