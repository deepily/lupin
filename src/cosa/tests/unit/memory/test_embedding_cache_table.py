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


def _make_open( debug=False, list_size=768, corrupted=False, count_raises=False ):
    """Build via the OPEN path (table present). Returns (table, mock_db, mock_table)."""
    mock_db = MagicMock()
    mock_db.table_names.return_value = [ "embedding_cache_tbl" ]   # open (not create) path
    mock_table = MagicMock()
    mock_db.open_table.return_value = mock_table
    mock_db.create_table.return_value = MagicMock()               # for corruption-recreate
    mock_table.schema.field.return_value.type.list_size = list_size
    probe = mock_table.to_lance.return_value.scanner.return_value.to_table.return_value.to_pylist
    if corrupted:
        probe.side_effect = RuntimeError( "lance: data fragment not found" )
    else:
        probe.return_value = [ ]                                  # healthy
    if count_raises:
        mock_table.count_rows.side_effect = RuntimeError( "count boom" )
    with patch( "cosa.memory.embedding_cache_table.ConfigurationManager", return_value=_cfg() ), \
         patch( "cosa.memory.embedding_cache_table.lancedb.connect", return_value=mock_db ), \
         patch( "builtins.print" ):
        table = EmbeddingCacheTable( debug=debug )
    return table, mock_db, mock_table


class TestInitPaths( unittest.TestCase ):
    """__init__ create/open/corruption + _validate + _is_table_corrupted + init_tbl."""

    def test_create_path_debug_prints( self ):
        # debug=True create path hits the create-path debug prints (57, 157, 168-169).
        table, mock_table = _make_table( debug=True )
        self.assertIsNotNone( table._embedding_cache_tbl )

    def test_count_rows_failure_warns( self ):
        # count_rows raising is caught + warned, not propagated (72-73).
        mock_db = MagicMock()
        mock_db.table_names.return_value = [ ]
        mock_created = MagicMock()
        mock_created.count_rows.side_effect = RuntimeError( "count boom" )
        mock_db.create_table.return_value = mock_created
        with patch( "cosa.memory.embedding_cache_table.ConfigurationManager", return_value=_cfg() ), \
             patch( "cosa.memory.embedding_cache_table.lancedb.connect", return_value=mock_db ), \
             patch( "builtins.print" ):
            table = EmbeddingCacheTable()                         # must not raise
        self.assertIs( table._embedding_cache_tbl, mock_created )

    def test_open_path_healthy_table( self ):
        # Open path, dims match, probe healthy → no drop, no recreate.
        table, mock_db, mock_table = _make_open()
        mock_db.open_table.assert_called_with( "embedding_cache_tbl" )
        mock_db.drop_table.assert_not_called()

    def test_open_path_corrupted_recreates( self ):
        # Corruption probe raises a lance "not found" → drop + recreate.
        table, mock_db, mock_table = _make_open( corrupted=True )
        mock_db.drop_table.assert_called_once_with( "embedding_cache_tbl" )
        mock_db.create_table.assert_called_once()

    def test_validate_drops_on_dimension_mismatch( self ):
        # Existing table whose embedding dim != config → _validate drops it (132-137).
        table, mock_db, mock_table = _make_open( list_size=999 )
        mock_db.drop_table.assert_called_with( "embedding_cache_tbl" )

    def test_is_table_corrupted_reraises_unexpected_error( self ):
        # A non-lance/non-"not found" error is re-raised, not swallowed (104-105).
        table, mock_db, mock_table = _make_open()
        mock_table.to_lance.return_value.scanner.return_value.to_table.return_value.to_pylist.side_effect = \
            RuntimeError( "permission denied" )
        with self.assertRaises( RuntimeError ):
            table._is_table_corrupted()

    def test_init_tbl_creates_schema_and_index( self ):
        # init_tbl() connects, creates the table + FTS index, prints row count (284-301).
        table, _ = _make_table()
        mock_db2 = MagicMock()
        mock_new = MagicMock()
        mock_db2.create_table.return_value = mock_new
        with patch( "cosa.memory.embedding_cache_table.lancedb.connect", return_value=mock_db2 ), \
             patch( "cosa.memory.embedding_cache_table.du.print_banner" ), \
             patch( "builtins.print" ):
            table.init_tbl()
        mock_db2.create_table.assert_called_once()
        mock_new.create_fts_index.assert_called_once()


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
