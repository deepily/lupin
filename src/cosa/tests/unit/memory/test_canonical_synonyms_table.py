"""
Unit tests for CanonicalSynonymsTable with comprehensive mocking.

Tests the CanonicalSynonymsTable class against its CURRENT production contract:
- Initialization (validate-dimensions + open-or-create chain)
- add_synonym( snapshot_id, question_verbatim, confidence_score, source ) — generates
  normalized/gist + three-level embeddings internally, dedup via find_exact_verbatim
- find_exact_verbatim / find_exact_normalized / find_exact_gist — pandas exact-match
  lookups via table.to_pandas()
- delete_by_snapshot_id — count + delete
- get_statistics — aggregate counts/usage/confidence

Zero external dependencies - lancedb, ConfigurationManager, Normalizer, and
EmbeddingManager are all mocked for isolated testing.

Rewritten 2026-05-30 (CoSA coverage campaign, memory group). The legacy file was
auto-generated against a fictional API (get_usage_stats / update_usage_count /
validation_method+embeddings params / search().where() lookups / _ensure_table_exists)
that does not exist in production; it has been replaced wholesale with tests that
exercise the real methods.

RULING (manager, 2026-05-30): CanonicalSynonymsTable.__init__ is FAIL-FAST on a
lancedb.connect failure — there is no try/except around the connect, so the
constructor RAISES. test_init_database_failure_is_fail_fast asserts assertRaises,
NOT graceful degradation.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch, call
from typing import List, Dict, Any, Optional

import pandas as pd

# Import test infrastructure
import sys
import os
sys.path.append( os.path.join( os.path.dirname( __file__ ), "..", "infrastructure" ) )
from mock_manager import MockManager
from unit_test_utilities import UnitTestUtilities

# Import the module under test
from cosa.memory.canonical_synonyms_table import CanonicalSynonymsTable


class TestCanonicalSynonymsTable( unittest.TestCase ):
    """
    Comprehensive unit tests for CanonicalSynonymsTable class.

    Requires:
        - MockManager for external dependency mocking
        - UnitTestUtilities for common test patterns

    Ensures:
        - All CanonicalSynonymsTable functionality tested in isolation
        - Exact-match lookups validated against the pandas-based implementation
        - add/delete/statistics behavior tested
    """

    def setUp( self ):
        """
        Setup for each test method.

        Ensures:
            - Clean state for each test
            - Mock manager is available
        """
        self.mock_manager   = MockManager()
        self.test_utilities = UnitTestUtilities()
        self.embedding_dim  = 768

    def tearDown( self ):
        """
        Cleanup after each test method.

        Ensures:
            - All mocks are reset
        """
        self.mock_manager.reset_mocks()

    def _build_table( self, table_mock=None, table_exists=True, db_path=None, debug=False, verbose=False ):
        """
        Construct a CanonicalSynonymsTable with the full __init__ dependency chain mocked.

        Patches (module-bound, where used): lancedb, ConfigurationManager, Normalizer,
        EmbeddingManager, and du.get_project_root.

        Args:
            table_mock   : optional pre-built Mock for the lancedb table
            table_exists : if True, db.table_names() reports the table (open path);
                           if False, reports empty (create path)
            db_path      : if provided, passed straight to the constructor (exercises
                           the explicit-path branch that bypasses config lookup)
            debug        : forwarded to the constructor (exercises debug-only branches)
            verbose      : forwarded to the constructor (exercises verbose-only branches)

        Returns:
            Tuple of (table_instance, mocks_dict)
        """
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type=None: {
            "embedding dimensions"     : "768",
            "path to database wo root" : "/test/db",
        }.get( key, default )

        mock_normalizer = Mock()
        mock_normalizer.normalize.side_effect = lambda q: q.lower()

        mock_embedding_mgr = Mock()
        mock_embedding_mgr.generate_embedding.return_value = [ 0.1 ] * self.embedding_dim

        mock_db    = Mock()
        the_table  = table_mock if table_mock is not None else Mock()
        mock_db.table_names.return_value  = [ "canonical_synonyms" ] if table_exists else []
        mock_db.open_table.return_value   = the_table
        mock_db.create_table.return_value = the_table
        # Schema dims match config → _validate_embedding_dimensions is a no-op (no drop)
        the_table.schema.field.return_value.type.list_size = self.embedding_dim

        with patch( "cosa.memory.canonical_synonyms_table.lancedb" ) as mock_lancedb, \
             patch( "cosa.memory.canonical_synonyms_table.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.canonical_synonyms_table.Normalizer", return_value=mock_normalizer ), \
             patch( "cosa.memory.canonical_synonyms_table.EmbeddingManager", return_value=mock_embedding_mgr ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_project_root", return_value="/root" ):

            mock_lancedb.connect.return_value = mock_db
            table = CanonicalSynonymsTable( db_path=db_path, debug=debug, verbose=verbose )

        mocks = {
            "table"         : the_table,
            "db"            : mock_db,
            "normalizer"    : mock_normalizer,
            "embedding_mgr" : mock_embedding_mgr,
            "config"        : mock_config,
        }
        return table, mocks

    def test_initialization_opens_existing_table( self ):
        """
        Test initialization when the table already exists.

        Ensures:
            - ConfigurationManager consulted for embedding dimensions
            - lancedb table opened (not created)
            - _canonical_synonyms_table wired to the opened table
        """
        table, mocks = self._build_table( table_exists=True )

        mocks["config"].get.assert_any_call( "embedding dimensions", default="768" )
        mocks["db"].open_table.assert_any_call( "canonical_synonyms" )
        mocks["db"].create_table.assert_not_called()
        self.assertIs( table._canonical_synonyms_table, mocks["table"] )
        self.assertFalse( table.debug )
        self.assertFalse( table.verbose )

    def test_initialization_creates_table_when_missing( self ):
        """
        Test initialization when the table does not yet exist.

        Ensures:
            - db.create_table invoked with the canonical_synonyms name
            - FTS indexes created on the new table
        """
        table, mocks = self._build_table( table_exists=False )

        mocks["db"].create_table.assert_called_once()
        create_args, create_kwargs = mocks["db"].create_table.call_args
        self.assertEqual( create_args[0], "canonical_synonyms" )
        self.assertEqual( create_kwargs.get( "mode" ), "overwrite" )
        # FTS indexes created on the three question levels
        self.assertGreaterEqual( mocks["table"].create_fts_index.call_count, 3 )

    def test_init_database_failure_is_fail_fast( self ):
        """
        Test that a lancedb.connect failure propagates from __init__ (FAIL-FAST).

        Per manager ruling 2026-05-30: __init__ has no try/except around the
        connect, so a connection error RAISES rather than degrading gracefully.

        Ensures:
            - Constructing the table raises when lancedb.connect fails
        """
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type=None: {
            "embedding dimensions"     : "768",
            "path to database wo root" : "/test/db",
        }.get( key, default )

        with patch( "cosa.memory.canonical_synonyms_table.lancedb" ) as mock_lancedb, \
             patch( "cosa.memory.canonical_synonyms_table.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.canonical_synonyms_table.Normalizer", return_value=Mock() ), \
             patch( "cosa.memory.canonical_synonyms_table.EmbeddingManager", return_value=Mock() ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_project_root", return_value="/root" ):

            mock_lancedb.connect.side_effect = Exception( "Database connection failed" )

            with self.assertRaises( Exception ):
                CanonicalSynonymsTable( debug=False, verbose=False )

    def test_find_exact_verbatim_match( self ):
        """
        Test find_exact_verbatim returns the snapshot_id on an exact match.

        Ensures:
            - Verbatim column filtered via pandas
            - Matching row's snapshot_id returned
        """
        table, mocks = self._build_table()

        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            {
                "question_verbatim"   : "What time is it?",
                "question_normalized" : "what time is it?",
                "question_gist"       : "what time is it?",
                "snapshot_id"         : "snap_verbatim",
            }
        ] )

        result = table.find_exact_verbatim( "What time is it?" )
        self.assertEqual( result, "snap_verbatim" )

    def test_find_exact_verbatim_no_match( self ):
        """
        Test find_exact_verbatim returns None when no row matches.

        Ensures:
            - Empty filter result yields None
        """
        table, mocks = self._build_table()
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "question_normalized", "question_gist", "snapshot_id" ]
        )

        result = table.find_exact_verbatim( "Unknown query" )
        self.assertIsNone( result )

    def test_find_exact_verbatim_exception_returns_none( self ):
        """
        Test find_exact_verbatim swallows errors and returns None.

        Ensures:
            - to_pandas failure is caught (the find_* methods ARE try/except-wrapped,
              unlike __init__)
            - None returned on error
        """
        table, mocks = self._build_table()
        mocks["table"].to_pandas.side_effect = Exception( "boom" )

        result = table.find_exact_verbatim( "anything" )
        self.assertIsNone( result )

    def test_find_exact_normalized_match( self ):
        """
        Test find_exact_normalized returns snapshot_id on a normalized match.

        Ensures:
            - Normalized column filtered via pandas (both debug modes)
            - Matching row's snapshot_id returned; debug=True exercises the "Found" trace
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.return_value = pd.DataFrame( [
                    {
                        "question_verbatim"   : "What time is it?",
                        "question_normalized" : "what time be it",
                        "question_gist"       : "time query",
                        "snapshot_id"         : "snap_normalized",
                    }
                ] )

                result = table.find_exact_normalized( "what time be it" )
                self.assertEqual( result, "snap_normalized" )

    def test_find_exact_gist_match( self ):
        """
        Test find_exact_gist returns snapshot_id on a gist match.

        Ensures:
            - Gist column filtered via pandas
            - Matching row's snapshot_id returned
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.return_value = pd.DataFrame( [
                    {
                        "question_verbatim"   : "What time is it?",
                        "question_normalized" : "what time be it",
                        "question_gist"       : "time query",
                        "snapshot_id"         : "snap_gist",
                    }
                ] )

                result = table.find_exact_gist( "time query" )
                self.assertEqual( result, "snap_gist" )

    def test_add_synonym_new( self ):
        """
        Test add_synonym inserts a new (non-duplicate) synonym.

        Ensures:
            - Dedup check via find_exact_verbatim (no match) allows insert
            - Normalizer + three embeddings generated
            - Row added with the full schema-aligned structure
            - Returns True
        """
        table, mocks = self._build_table()

        # No existing duplicate (find_exact_verbatim → empty df → None)
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "snapshot_id" ]
        )

        result = table.add_synonym(
            snapshot_id="snap_new",
            question_verbatim="How is the weather?",
            confidence_score=95.0,
            source="runtime"
        )

        self.assertTrue( result )
        mocks["table"].add.assert_called_once()

        row = mocks["table"].add.call_args[0][0][0]
        self.assertEqual( row["snapshot_id"], "snap_new" )
        self.assertEqual( row["question_verbatim"], "How is the weather?" )
        self.assertEqual( row["question_normalized"], "how is the weather?" )   # normalizer.lower()
        self.assertEqual( row["question_gist"], "how is the weather?" )         # gist == normalized
        self.assertEqual( row["confidence_score"], 95.0 )
        self.assertEqual( row["usage_count"], 0 )
        self.assertEqual( row["source"], "runtime" )
        self.assertEqual( len( row["embedding_verbatim"] ), self.embedding_dim )
        self.assertEqual( len( row["embedding_normalized"] ), self.embedding_dim )
        self.assertEqual( len( row["embedding_gist"] ), self.embedding_dim )

        # Three embeddings generated (verbatim, normalized, gist)
        self.assertEqual( mocks["embedding_mgr"].generate_embedding.call_count, 3 )

    def test_add_synonym_duplicate_skipped( self ):
        """
        Test add_synonym skips insertion when a verbatim duplicate exists.

        Ensures:
            - find_exact_verbatim match short-circuits the add
            - table.add NOT called
            - Returns False
        """
        table, mocks = self._build_table()

        # Existing duplicate found
        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            { "question_verbatim": "What time is it?", "snapshot_id": "existing_snap" }
        ] )

        result = table.add_synonym(
            snapshot_id="snap_dup",
            question_verbatim="What time is it?",
            confidence_score=100.0,
            source="runtime"
        )

        self.assertFalse( result )
        mocks["table"].add.assert_not_called()

    def test_add_synonym_error_handling( self ):
        """
        Test add_synonym handles a table.add failure gracefully.

        Ensures:
            - Exception during add is caught
            - Returns False (no propagation)
        """
        table, mocks = self._build_table()

        # No duplicate so we proceed to add()
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "snapshot_id" ]
        )
        mocks["table"].add.side_effect = Exception( "add failed" )

        with patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ):
            result = table.add_synonym(
                snapshot_id="snap_err",
                question_verbatim="Will fail",
                confidence_score=90.0,
                source="runtime"
            )

        self.assertFalse( result )

    def test_delete_by_snapshot_id( self ):
        """
        Test delete_by_snapshot_id removes matching rows and returns the count.

        Ensures:
            - Row count computed from pandas filter
            - table.delete invoked with the snapshot_id predicate
            - Returns the number of matched rows
        """
        table, mocks = self._build_table()

        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            { "snapshot_id": "snap_del", "question_verbatim": "q1" },
            { "snapshot_id": "snap_del", "question_verbatim": "q2" },
            { "snapshot_id": "other",    "question_verbatim": "q3" },
        ] )

        count = table.delete_by_snapshot_id( "snap_del" )

        self.assertEqual( count, 2 )
        mocks["table"].delete.assert_called_once_with( "snapshot_id = 'snap_del'" )

    def test_delete_by_snapshot_id_no_match( self ):
        """
        Test delete_by_snapshot_id returns 0 and skips delete when nothing matches.

        Ensures:
            - No table.delete call when count is 0
            - Returns 0
        """
        table, mocks = self._build_table()

        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            { "snapshot_id": "other", "question_verbatim": "q1" },
        ] )

        count = table.delete_by_snapshot_id( "missing" )

        self.assertEqual( count, 0 )
        mocks["table"].delete.assert_not_called()

    def test_get_statistics( self ):
        """
        Test get_statistics aggregates counts, usage, and confidence.

        Ensures:
            - total_synonyms from count_rows
            - total_usage summed across rows
            - average_confidence computed
            - top_used populated
        """
        table, mocks = self._build_table()

        mocks["table"].count_rows.return_value = 2

        mock_search = Mock()
        mock_search.limit.return_value.to_list.return_value = [
            { "question_verbatim": "q1", "usage_count": 10, "confidence_score": 100.0 },
            { "question_verbatim": "q2", "usage_count": 5,  "confidence_score": 90.0 },
        ]
        mocks["table"].search.return_value = mock_search

        stats = table.get_statistics()

        self.assertEqual( stats["total_synonyms"], 2 )
        self.assertEqual( stats["total_usage"], 15 )
        self.assertEqual( stats["average_confidence"], 95.0 )
        self.assertEqual( len( stats["top_used"] ), 2 )
        self.assertEqual( stats["top_used"][0]["question"], "q1" )
        self.assertEqual( stats["top_used"][0]["usage"], 10 )

    def test_get_statistics_error_returns_error_dict( self ):
        """
        Test get_statistics returns an error dict on failure.

        Ensures:
            - Exception during aggregation is caught
            - Returned dict carries an 'error' key
        """
        table, mocks = self._build_table()
        mocks["table"].count_rows.side_effect = Exception( "stats boom" )

        stats = table.get_statistics()
        self.assertIn( "error", stats )

    # ------------------------------------------------------------------ #
    # Initialization branches: explicit db_path, debug/verbose, create   #
    # path debug, validate-dimension mismatch, FTS-index failure.        #
    # ------------------------------------------------------------------ #

    def test_init_with_explicit_db_path_bypasses_config_lookup( self ):
        """
        Test that supplying db_path uses it directly and skips the config path lookup.

        Ensures:
            - The provided db_path is forwarded to lancedb.connect as the uri
            - 'path to database wo root' config key is NOT consulted (explicit branch)
        """
        table, mocks = self._build_table( table_exists=True, db_path="/explicit/db" )

        # Only the embedding-dimensions key should have been read; the path key is bypassed.
        consulted_keys = [ c.args[0] for c in mocks["config"].get.call_args_list ]
        self.assertIn( "embedding dimensions", consulted_keys )
        self.assertNotIn( "path to database wo root", consulted_keys )

    def test_init_debug_and_verbose_open_path( self ):
        """
        Test the debug + verbose open-existing-table branches in __init__.

        Ensures:
            - debug=True exercises the "Connecting to LanceDB" trace
            - verbose=True exercises the "Opened ... rows" trace (count_rows consulted)
            - Construction still wires the opened table
        """
        the_table = Mock()
        the_table.count_rows.return_value = 7
        the_table.schema.field.return_value.type.list_size = self.embedding_dim

        table, mocks = self._build_table( table_mock=the_table, table_exists=True, debug=True, verbose=True )

        self.assertTrue( table.debug )
        self.assertTrue( table.verbose )
        mocks["table"].count_rows.assert_called()

    def test_init_create_path_debug( self ):
        """
        Test the debug branches along the create-table path.

        Ensures:
            - debug=True exercises the "Table doesn't exist" + schema-banner + FTS-debug
              + "Created table" traces
            - create_table invoked and FTS indexes built
        """
        table, mocks = self._build_table( table_exists=False, debug=True, verbose=True )

        mocks["db"].create_table.assert_called_once()
        self.assertGreaterEqual( mocks["table"].create_fts_index.call_count, 3 )

    def test_init_create_path_fts_index_failure_is_swallowed( self ):
        """
        Test that an FTS-index creation failure during table creation is caught.

        Ensures:
            - create_fts_index raising does NOT abort construction (both debug modes)
            - The warning branch (debug=True) and its debug=False counterpart both run
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                the_table = Mock()
                the_table.schema.field.return_value.type.list_size = self.embedding_dim
                the_table.create_fts_index.side_effect = Exception( "no fts" )

                table, _ = self._build_table( table_mock=the_table, table_exists=False, debug=debug )

                self.assertIs( table._canonical_synonyms_table, the_table )

    def test_init_validate_dimension_mismatch_drops_table( self ):
        """
        Test _validate_embedding_dimensions drops a table whose dims disagree with config.

        Per the production contract: a schema dim that differs from the configured
        embedding dimension triggers a banner + db.drop_table so the table is
        recreated fresh.

        Ensures:
            - db.drop_table called for the mismatched table
            - After the drop, the (now-missing) table is recreated via create_table
        """
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default=None, return_type=None: {
            "embedding dimensions"     : "768",
            "path to database wo root" : "/test/db",
        }.get( key, default )

        the_table = Mock()
        # Existing schema reports 1536 dims while config wants 768 → mismatch.
        the_table.schema.field.return_value.type.list_size = 1536

        mock_db = Mock()
        # table_names: validate() sees it present; __init__ then sees it gone (post-drop) → create.
        mock_db.table_names.side_effect      = [ [ "canonical_synonyms" ], [] ]
        mock_db.open_table.return_value      = the_table
        mock_db.create_table.return_value    = the_table

        with patch( "cosa.memory.canonical_synonyms_table.lancedb" ) as mock_lancedb, \
             patch( "cosa.memory.canonical_synonyms_table.ConfigurationManager", return_value=mock_config ), \
             patch( "cosa.memory.canonical_synonyms_table.Normalizer", return_value=Mock() ), \
             patch( "cosa.memory.canonical_synonyms_table.EmbeddingManager", return_value=Mock() ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_project_root", return_value="/root" ):

            mock_lancedb.connect.return_value = mock_db
            CanonicalSynonymsTable( debug=False, verbose=False )

        mock_db.drop_table.assert_called_once_with( "canonical_synonyms" )
        mock_db.create_table.assert_called_once()

    # ------------------------------------------------------------------ #
    # find_exact_* debug + no-match + exception branches                 #
    # ------------------------------------------------------------------ #

    def test_find_exact_verbatim_match_debug( self ):
        """
        Test find_exact_verbatim debug branch + the _update_usage_stats debug trace.

        Ensures:
            - With debug=True a match still returns the snapshot_id
            - The usage-stats debug path is exercised on the match
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            {
                "question_verbatim"   : "What time is it?",
                "question_normalized" : "what time is it?",
                "question_gist"       : "what time is it?",
                "snapshot_id"         : "snap_dbg",
            }
        ] )

        self.assertEqual( table.find_exact_verbatim( "What time is it?" ), "snap_dbg" )

    def test_find_exact_verbatim_no_match_debug( self ):
        """
        Test find_exact_verbatim no-match debug branch.

        Ensures:
            - With debug=True an empty filter yields None (and the "No match" trace runs)
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "question_normalized", "question_gist", "snapshot_id" ]
        )

        self.assertIsNone( table.find_exact_verbatim( "missing" ) )

    def test_find_exact_verbatim_exception_debug( self ):
        """
        Test find_exact_verbatim exception debug branch.

        Ensures:
            - With debug=True a to_pandas failure is caught and None returned
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].to_pandas.side_effect = Exception( "boom" )

        self.assertIsNone( table.find_exact_verbatim( "anything" ) )

    def test_find_exact_normalized_no_match( self ):
        """
        Test find_exact_normalized returns None when no normalized row matches.

        Ensures:
            - Empty filter result yields None in both debug modes (both no-match branches)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.return_value = pd.DataFrame(
                    columns=[ "question_verbatim", "question_normalized", "question_gist", "snapshot_id" ]
                )

                self.assertIsNone( table.find_exact_normalized( "nope" ) )

    def test_find_exact_normalized_exception_returns_none( self ):
        """
        Test find_exact_normalized swallows errors and returns None.

        Ensures:
            - to_pandas failure is caught in both debug modes (both error branches)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.side_effect = Exception( "boom" )

                self.assertIsNone( table.find_exact_normalized( "anything" ) )

    def test_find_exact_gist_no_match( self ):
        """
        Test find_exact_gist returns None when no gist row matches.

        Ensures:
            - Empty filter result yields None in both debug modes (both no-match branches)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.return_value = pd.DataFrame(
                    columns=[ "question_verbatim", "question_normalized", "question_gist", "snapshot_id" ]
                )

                self.assertIsNone( table.find_exact_gist( "nope" ) )

    def test_find_exact_gist_exception_returns_none( self ):
        """
        Test find_exact_gist swallows errors and returns None.

        Ensures:
            - to_pandas failure is caught in both debug modes (both error branches)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.side_effect = Exception( "boom" )

                self.assertIsNone( table.find_exact_gist( "anything" ) )

    # ------------------------------------------------------------------ #
    # add_synonym debug/verbose branches                                 #
    # ------------------------------------------------------------------ #

    def test_add_synonym_new_debug_verbose( self ):
        """
        Test add_synonym new-insert debug + verbose branches.

        Ensures:
            - With debug=True the start/success timer traces are exercised
            - Row still added and True returned
        """
        table, mocks = self._build_table( debug=True, verbose=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "snapshot_id" ]
        )

        result = table.add_synonym(
            snapshot_id="snap_dbg",
            question_verbatim="How is the weather?",
            confidence_score=95.0,
            source="runtime"
        )

        self.assertTrue( result )
        mocks["table"].add.assert_called_once()

    def test_add_synonym_duplicate_debug_verbose( self ):
        """
        Test add_synonym duplicate-skip debug + verbose branches.

        Ensures:
            - With debug+verbose the "Duplicate" timer + verbose skip box are exercised
            - table.add NOT called; returns False
        """
        table, mocks = self._build_table( debug=True, verbose=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            { "question_verbatim": "What time is it?", "snapshot_id": "existing_snap" }
        ] )

        result = table.add_synonym(
            snapshot_id="snap_dup",
            question_verbatim="What time is it?",
            confidence_score=100.0,
            source="runtime"
        )

        self.assertFalse( result )
        mocks["table"].add.assert_not_called()

    def test_add_synonym_error_debug( self ):
        """
        Test add_synonym error debug branch.

        Ensures:
            - With debug=True the error timer trace is exercised on add failure
            - Returns False (no propagation)
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame(
            columns=[ "question_verbatim", "snapshot_id" ]
        )
        mocks["table"].add.side_effect = Exception( "add failed" )

        with patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ):
            result = table.add_synonym(
                snapshot_id="snap_err",
                question_verbatim="Will fail",
                confidence_score=90.0,
                source="runtime"
            )

        self.assertFalse( result )

    # ------------------------------------------------------------------ #
    # delete_by_snapshot_id debug + exception branches                   #
    # ------------------------------------------------------------------ #

    def test_delete_by_snapshot_id_debug( self ):
        """
        Test delete_by_snapshot_id debug branches on a successful delete.

        Ensures:
            - With debug=True the start/deleted timer traces are exercised
            - Returns the matched count and issues the delete predicate
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].to_pandas.return_value = pd.DataFrame( [
            { "snapshot_id": "snap_del", "question_verbatim": "q1" },
            { "snapshot_id": "snap_del", "question_verbatim": "q2" },
        ] )

        count = table.delete_by_snapshot_id( "snap_del" )

        self.assertEqual( count, 2 )
        mocks["table"].delete.assert_called_once_with( "snapshot_id = 'snap_del'" )

    def test_delete_by_snapshot_id_exception_returns_zero( self ):
        """
        Test delete_by_snapshot_id returns 0 on error.

        Ensures:
            - With debug=True a to_pandas failure is caught (error timer trace)
            - print_stack_trace invoked; returns 0
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, mocks = self._build_table( debug=debug )
                mocks["table"].to_pandas.side_effect = Exception( "del boom" )

                with patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ):
                    count = table.delete_by_snapshot_id( "snap_del" )

                self.assertEqual( count, 0 )

    # ------------------------------------------------------------------ #
    # _update_usage_stats + get_statistics debug branches                #
    # ------------------------------------------------------------------ #

    def test_update_usage_stats_debug_trace( self ):
        """
        Test _update_usage_stats debug trace fires without error.

        Ensures:
            - With debug=True the usage-stats print branch is exercised
            - Method returns None (no-op persistence stub)
        """
        table, _ = self._build_table( debug=True )

        self.assertIsNone( table._update_usage_stats( "What time is it?" ) )

    def test_update_usage_stats_exception_is_swallowed( self ):
        """
        Test _update_usage_stats catches an error raised while building its trace.

        Ensures:
            - A failure inside the try-block (here: truncate_string raising) is caught
            - The except-branch debug trace runs; method still returns None
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                table, _ = self._build_table( debug=debug )

                with patch( "cosa.memory.canonical_synonyms_table.du.truncate_string",
                            side_effect=Exception( "trunc boom" ) ):
                    self.assertIsNone( table._update_usage_stats( "boom question" ) )

    def test_get_statistics_error_debug( self ):
        """
        Test get_statistics error path with debug enabled.

        Ensures:
            - With debug=True the error print branch is exercised
            - Returned dict still carries an 'error' key
        """
        table, mocks = self._build_table( debug=True )
        mocks["table"].count_rows.side_effect = Exception( "stats boom" )

        stats = table.get_statistics()
        self.assertIn( "error", stats )


class TestPostgresBackend( unittest.TestCase ):
    """v0.2.0 §6 postgres backend: __init__ skips LanceDB; exact-match + add via repo."""

    def _make_pg( self, debug=False ):
        cfg = Mock()
        cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "embedding dimensions":     "768",
            "path to database wo root": "/test/db",
        }.get( key, default )
        normalizer = Mock()
        normalizer.normalize.side_effect = lambda q: q.lower()
        emb = Mock()
        emb.generate_embedding.return_value = [ 0.1 ] * 768
        with patch( "cosa.memory.canonical_synonyms_table.is_postgres_backend", return_value=True ), \
             patch( "cosa.memory.canonical_synonyms_table.ConfigurationManager", return_value=cfg ), \
             patch( "cosa.memory.canonical_synonyms_table.Normalizer", return_value=normalizer ), \
             patch( "cosa.memory.canonical_synonyms_table.EmbeddingManager", return_value=emb ), \
             patch( "cosa.memory.canonical_synonyms_table.lancedb.connect",
                    side_effect=AssertionError( "postgres ctor must not connect to LanceDB" ) ), \
             patch( "builtins.print" ):
            table = CanonicalSynonymsTable( debug=debug )
        return table, normalizer, emb

    @staticmethod
    def _patch_repo():
        import contextlib
        session   = MagicMock()
        repo_inst = MagicMock()

        @contextlib.contextmanager
        def fake_get_db():
            yield session

        ctx      = patch( "cosa.rest.db.database.get_db", fake_get_db )
        repo_ctx = patch( "cosa.rest.db.repositories.canonical_synonym_repository.CanonicalSynonymRepository",
                          return_value=repo_inst )
        return repo_inst, ctx, repo_ctx

    def test_init_uses_postgres( self ):
        table, _, _ = self._make_pg()
        self.assertTrue( table._use_postgres )

    def test_find_exact_verbatim_normalized_gist( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.return_value   = "snapV"
        repo.find_exact_normalized.return_value = "snapN"
        repo.find_exact_gist.return_value       = "snapG"
        with ctx, repo_ctx:
            self.assertEqual( table.find_exact_verbatim( "q" ), "snapV" )
            self.assertEqual( table.find_exact_normalized( "q" ), "snapN" )
            self.assertEqual( table.find_exact_gist( "q" ), "snapG" )

    def test_find_exact_error_returns_none( self ):
        table, _, _ = self._make_pg( debug=True )
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ):
            self.assertIsNone( table.find_exact_verbatim( "q" ) )

    def test_add_synonym_inserts_when_new( self ):
        table, normalizer, emb = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.return_value = None      # not a duplicate
        with ctx, repo_ctx, \
             patch( "cosa.memory.canonical_synonyms_table.du.get_current_datetime", return_value="TS" ), \
             patch( "cosa.memory.canonical_synonyms_table.du.get_timestamp_ms", return_value="NOW" ):
            self.assertTrue( table.add_synonym( "snap1", "How Are You?", confidence_score=90.0, source="test" ) )
        kw = repo.add_synonym.call_args.kwargs
        self.assertEqual( kw[ "snapshot_id" ], "snap1" )
        self.assertEqual( kw[ "question_normalized" ], "how are you?" )    # normalizer.lower()
        self.assertEqual( kw[ "embedding_verbatim" ], [ 0.1 ] * 768 )
        self.assertEqual( kw[ "id" ], "snap1_TS" )

    def test_add_synonym_skips_duplicate( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.return_value = "existing"    # duplicate
        with ctx, repo_ctx:
            self.assertFalse( table.add_synonym( "snap1", "q" ) )
        repo.add_synonym.assert_not_called()

    def test_add_synonym_error_returns_false( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.return_value = None
        repo.add_synonym.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ) as trace:
            self.assertFalse( table.add_synonym( "snap1", "q" ) )
        trace.assert_called_once()

    def test_delete_by_snapshot_id_delegates( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.delete_by_snapshot_id.return_value = 3
        with ctx, repo_ctx:
            self.assertEqual( table.delete_by_snapshot_id( "snap1" ), 3 )

    def test_delete_by_snapshot_id_error_returns_zero( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.delete_by_snapshot_id.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "cosa.memory.canonical_synonyms_table.du.print_stack_trace" ):
            self.assertEqual( table.delete_by_snapshot_id( "snap1" ), 0 )

    def test_get_statistics_maps_shape( self ):
        table, _, _ = self._make_pg()
        repo, ctx, repo_ctx = self._patch_repo()
        repo.get_statistics.return_value = { "total_synonyms": 5, "total_usage_count": 12 }
        with ctx, repo_ctx:
            stats = table.get_statistics()
        self.assertEqual( stats, { "total_synonyms": 5, "total_usage": 12, "top_used": [] } )

    def test_get_statistics_error_returns_error_dict( self ):
        table, _, _ = self._make_pg( debug=True )
        repo, ctx, repo_ctx = self._patch_repo()
        repo.get_statistics.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx, patch( "builtins.print" ):
            self.assertIn( "error", table.get_statistics() )

    def test_find_exact_error_debug_off_skips_log( self ):
        table, _, _ = self._make_pg( debug=False )      # covers the `if self.debug` False branch
        repo, ctx, repo_ctx = self._patch_repo()
        repo.find_exact_verbatim.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertIsNone( table.find_exact_verbatim( "q" ) )

    def test_get_statistics_error_debug_off_skips_log( self ):
        table, _, _ = self._make_pg( debug=False )      # covers the `if self.debug` False branch
        repo, ctx, repo_ctx = self._patch_repo()
        repo.get_statistics.side_effect = RuntimeError( "boom" )
        with ctx, repo_ctx:
            self.assertIn( "error", table.get_statistics() )


if __name__ == "__main__":
    unittest.main()
