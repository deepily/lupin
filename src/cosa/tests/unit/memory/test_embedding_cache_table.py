"""
Unit tests for cosa.memory.embedding_cache_table.EmbeddingCacheTable.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign). The
prior tests asserted on a `.search().where()...` chain — but the current methods
query via `_tbl.to_lance().scanner(filter=, limit=, columns=).to_table()
.to_pylist()` (filter-only scan, no vector search). They also left
lancedb.table_names() returning a Mock. Both fixed: the to_lance scanner chain
is wired, and the ctor uses table_names()=[] (the create path, which avoids the
corruption probe).

The full ctor chain (ConfigurationManager [per-key], lancedb.connect → mock db)
is mocked so no real DB I/O occurs. Reviewed by Mr. Radio (no self-audit).
"""
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.embedding_cache_table import EmbeddingCacheTable

_EMB = [ 0.1 ] * 768


def _cfg():
    m = Mock()
    m.get.side_effect = lambda key, default=None, **kw: {
        "embedding dimensions":      "768",
        "path to database wo root":  "/test/db",
    }.get( key, default )
    return m


def _make_table( debug=False ):
    """Build an EmbeddingCacheTable with config + lancedb mocked; return (table, mock_table)."""
    mock_db = MagicMock()
    mock_db.table_names.return_value = []                   # create path (skips corruption probe)
    mock_table = MagicMock()
    mock_db.create_table.return_value = mock_table
    with patch( "cosa.memory.embedding_cache_table.ConfigurationManager", return_value=_cfg() ), \
         patch( "cosa.memory.embedding_cache_table.lancedb.connect", return_value=mock_db ), \
         patch( "builtins.print" ):
        table = EmbeddingCacheTable( debug=debug )
    return table, mock_table


def _wire_scan( mock_table, pylist ):
    """Wire _tbl.to_lance().scanner(...).to_table().to_pylist() → pylist."""
    mock_table.to_lance.return_value.scanner.return_value.to_table.return_value.to_pylist.return_value = pylist


class TestHasCachedEmbedding( unittest.TestCase ):
    """has_cached_embedding() — scan filter, escape, error fallback."""

    def test_true_when_found( self ):
        table, mock_table = _make_table()
        _wire_scan( mock_table, [ { "normalized_text": "x" } ] )
        self.assertTrue( table.has_cached_embedding( "what time is it" ) )

    def test_false_when_absent( self ):
        table, mock_table = _make_table()
        _wire_scan( mock_table, [] )
        self.assertFalse( table.has_cached_embedding( "nope" ) )

    def test_escapes_single_quotes_in_filter( self ):
        table, mock_table = _make_table()
        _wire_scan( mock_table, [] )
        table.has_cached_embedding( "what's up" )
        scanner_kwargs = mock_table.to_lance.return_value.scanner.call_args.kwargs
        self.assertEqual( scanner_kwargs[ "filter" ], "normalized_text = 'what''s up'" )

    def test_error_returns_false( self ):
        table, mock_table = _make_table()
        mock_table.to_lance.side_effect = RuntimeError( "lance boom" )
        with patch( "cosa.memory.embedding_cache_table.du.print_stack_trace" ):
            self.assertFalse( table.has_cached_embedding( "q" ) )


class TestGetCachedEmbedding( unittest.TestCase ):
    """get_cached_embedding() — hit returns embedding, miss → None, error → None."""

    def test_returns_embedding_on_hit( self ):
        table, mock_table = _make_table()
        _wire_scan( mock_table, [ { "embedding": _EMB } ] )
        self.assertEqual( table.get_cached_embedding( "q" ), _EMB )

    def test_returns_none_on_miss( self ):
        table, mock_table = _make_table()
        _wire_scan( mock_table, [] )
        self.assertIsNone( table.get_cached_embedding( "q" ) )

    def test_returns_none_on_error( self ):
        table, mock_table = _make_table()
        mock_table.to_lance.side_effect = RuntimeError( "lance boom" )
        with patch( "cosa.memory.embedding_cache_table.du.print_stack_trace" ):
            self.assertIsNone( table.get_cached_embedding( "q" ) )


class TestCacheEmbedding( unittest.TestCase ):
    """cache_embedding() — add row, error swallowed-and-logged."""

    def test_adds_row( self ):
        table, mock_table = _make_table()
        table.cache_embedding( "what time is it", _EMB )
        mock_table.add.assert_called_once_with(
            [ { "normalized_text": "what time is it", "embedding": _EMB } ]
        )

    def test_add_error_is_logged_not_raised( self ):
        table, mock_table = _make_table()
        mock_table.add.side_effect = RuntimeError( "write failed" )
        with patch( "cosa.memory.embedding_cache_table.du.print_stack_trace" ) as trace:
            table.cache_embedding( "q", _EMB )      # must not raise
        trace.assert_called_once()
        self.assertEqual( trace.call_args.kwargs[ "explanation" ], "cache_embedding() failed" )


if __name__ == "__main__":
    unittest.main()
