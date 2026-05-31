"""
Unit tests for cosa.memory.question_embeddings_table.QuestionEmbeddingsTable.

REWRITTEN 2026-05-31 by Sam 🎙️ (memory takeover, CoSA coverage campaign). The
prior tests left `get_embedding_provider` UNMOCKED in the construction helper
(so __init__ did real config/model-server I/O → the
"/project/root/src/conf/lupin-app.ini" sanity-check failure), used a scalar
config mock (so `int(config.get("embedding dimensions"))` broke), and asserted a
stale embedding call (`generate_embedding(q, normalize_for_cache=True)` on the
manager — the real path is `_embedding_provider.generate_embedding(q,
content_type="prose")`). The debug-timing test also forgot that the Stopwatch
arc is gated on debug AND verbose.

The full construction dependency chain (ConfigurationManager [per-key
side_effect], EmbeddingManager, get_embedding_provider, lancedb.connect) is
mocked so no real DB / embedding I/O occurs. Reviewed by Mr. Radio (no
self-audit).
"""
import unittest
from unittest.mock import Mock, MagicMock, patch

from cosa.memory.question_embeddings_table import QuestionEmbeddingsTable


_EMBEDDING = [ 0.1 ] * 768


def _cfg_get( key, default=None, **kwargs ):
    return {
        "embedding dimensions":       "768",
        "path to database wo root":   "/test/db",
    }.get( key, default )


def _make_table( debug=False, verbose=False ):
    """
    Build a QuestionEmbeddingsTable with its full ctor dep chain mocked.
    Returns (table, mock_table, mock_provider).
    """
    cfg = Mock()
    cfg.get.side_effect = _cfg_get
    provider = Mock()
    provider.generate_embedding.return_value = _EMBEDDING

    mock_db = MagicMock()
    mock_db.table_names.return_value = []          # validate no-op + create path
    mock_table = MagicMock()
    mock_db.create_table.return_value = mock_table
    mock_db.open_table.return_value = mock_table

    with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=cfg ), \
         patch( "cosa.memory.question_embeddings_table.EmbeddingManager" ), \
         patch( "cosa.memory.question_embeddings_table.get_embedding_provider", return_value=provider ), \
         patch( "cosa.memory.question_embeddings_table.lancedb.connect", return_value=mock_db ), \
         patch( "builtins.print" ):
        table = QuestionEmbeddingsTable( debug=debug, verbose=verbose )
    return table, mock_table, provider


class TestInitialization( unittest.TestCase ):
    """__init__ wires config + deps and opens the table."""

    def test_init_wires_dependencies( self ):
        cfg = Mock()
        cfg.get.side_effect = _cfg_get
        mock_db = MagicMock()
        mock_db.table_names.return_value = []
        mock_db.open_table.return_value = MagicMock()

        with patch( "cosa.memory.question_embeddings_table.ConfigurationManager", return_value=cfg ) as cfg_cls, \
             patch( "cosa.memory.question_embeddings_table.EmbeddingManager" ) as em_cls, \
             patch( "cosa.memory.question_embeddings_table.get_embedding_provider" ) as gep, \
             patch( "cosa.memory.question_embeddings_table.lancedb.connect", return_value=mock_db ), \
             patch( "builtins.print" ):
            table = QuestionEmbeddingsTable( debug=True, verbose=True )

        cfg_cls.assert_called_once_with( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
        em_cls.assert_called_once_with( debug=True, verbose=True )
        gep.assert_called_once_with( debug=True, verbose=True )
        self.assertEqual( table._embedding_dim, 768 )
        self.assertTrue( table.debug )
        mock_db.open_table.assert_called_once_with( "question_embeddings_tbl" )


class TestHas( unittest.TestCase ):
    """has() — existence check with SQL-quote escaping."""

    def _wire_search( self, mock_table, to_list_result ):
        chain = mock_table.search.return_value.where.return_value.limit.return_value.select.return_value
        chain.to_list.return_value = to_list_result

    def test_returns_true_when_found( self ):
        table, mock_table, _ = _make_table()
        self._wire_search( mock_table, [ { "question": "q" } ] )
        self.assertTrue( table.has( "What is 2+2?" ) )
        mock_table.search.return_value.where.assert_called_once_with( "question = 'What is 2+2?'" )

    def test_returns_false_when_absent( self ):
        table, mock_table, _ = _make_table()
        self._wire_search( mock_table, [] )
        self.assertFalse( table.has( "nope" ) )

    def test_escapes_single_quotes( self ):
        table, mock_table, _ = _make_table()
        self._wire_search( mock_table, [] )
        table.has( "What's up'; DROP TABLE x; --" )
        mock_table.search.return_value.where.assert_called_once_with(
            "question = 'What''s up''; DROP TABLE x; --'"
        )


class TestGetEmbedding( unittest.TestCase ):
    """get_embedding() — table hit, generate-on-miss, error fallback."""

    def _wire_search( self, mock_table, to_list_result=None, side_effect=None ):
        sel = mock_table.search.return_value.where.return_value.limit.return_value.select.return_value
        if side_effect is not None:
            mock_table.search.side_effect = side_effect
        else:
            sel.to_list.return_value = to_list_result

    def test_returns_table_embedding_without_generating( self ):
        table, mock_table, provider = _make_table()
        self._wire_search( mock_table, [ { "embedding": _EMBEDDING } ] )
        result = table.get_embedding( "What is 2+2?" )
        self.assertEqual( result, _EMBEDDING )
        provider.generate_embedding.assert_not_called()

    def test_generates_on_miss( self ):
        table, mock_table, provider = _make_table()
        self._wire_search( mock_table, [] )
        result = table.get_embedding( "What is 2+2?" )
        self.assertEqual( result, _EMBEDDING )
        provider.generate_embedding.assert_called_once_with( "What is 2+2?", content_type="prose" )

    def test_search_error_falls_back_to_generate( self ):
        table, mock_table, provider = _make_table()
        self._wire_search( mock_table, side_effect=RuntimeError( "db down" ) )
        with patch( "cosa.memory.question_embeddings_table.du.print_stack_trace" ) as trace:
            result = table.get_embedding( "What is 2+2?" )
        self.assertEqual( result, _EMBEDDING )
        provider.generate_embedding.assert_called_once_with( "What is 2+2?", content_type="prose" )
        trace.assert_called_once()


class TestAddEmbedding( unittest.TestCase ):
    """add_embedding() — happy path + error swallowed-and-logged."""

    def test_adds_row( self ):
        table, mock_table, _ = _make_table()
        table.add_embedding( "What is 2+2?", _EMBEDDING )
        mock_table.add.assert_called_once_with(
            [ { "question": "What is 2+2?", "embedding": _EMBEDDING } ]
        )

    def test_add_error_is_logged_not_raised( self ):
        table, mock_table, _ = _make_table()
        mock_table.add.side_effect = RuntimeError( "write failed" )
        with patch( "cosa.memory.question_embeddings_table.du.print_stack_trace" ) as trace:
            table.add_embedding( "q", _EMBEDDING )      # must not raise
        trace.assert_called_once()
        self.assertEqual( trace.call_args.kwargs[ "explanation" ], "add() failed" )
        self.assertEqual( trace.call_args.kwargs[ "caller" ], "QuestionEmbeddingsTable.add_embedding()" )


class TestDebugTiming( unittest.TestCase ):
    """The Stopwatch arc in has() fires only under debug AND verbose."""

    def test_stopwatch_used_when_debug_and_verbose( self ):
        table, mock_table, _ = _make_table( debug=True, verbose=True )
        chain = mock_table.search.return_value.where.return_value.limit.return_value.select.return_value
        chain.to_list.return_value = []
        with patch( "cosa.memory.question_embeddings_table.Stopwatch" ) as sw_cls, \
             patch( "cosa.memory.question_embeddings_table.du.print_banner" ):
            sw = Mock()
            sw_cls.return_value = sw
            table.has( "What is 2+2?" )
        sw_cls.assert_called_once_with( msg="has( 'What is 2+2?' )" )
        sw.print.assert_called_once_with( "Done!", use_millis=True )


if __name__ == "__main__":
    unittest.main()
