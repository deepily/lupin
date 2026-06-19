"""
Unit tests for cosa.memory.gist_cache_table.GistCacheTable with boundary mocking.

Exercises the LanceDB-backed gist cache against its CURRENT production contract:

- __init__                  — create-when-missing, open-when-present, corruption
                              detect + auto-recreate, debug count print
- _create_table             — schema build + FTS index creation + debug prints
- _is_table_corrupted       — healthy scan, "not found"/"lance" → corrupted,
                              unexpected error re-raise
- has_cached_gist           — exists / not-exists / error fallback
- get_cached_gist           — two-tier (verbatim hit, normalized hit, both miss)
                              + outer-exception fallback + debug+verbose timing
- _get_cached_by_verbatim   — hit / miss / error
- _get_cached_by_normalized — hit / miss / error
- cache_gist                — new insert / duplicate skip / error
- get_statistics            — populated sample / empty sample / error dict
- clear_cache               — debug no-op print / debug-off skip / error

All LanceDB access is mocked at the to_lance().scanner()...to_pylist() boundary;
Normalizer and lancedb.connect are patched. No network / model / storage I/O.

Created 2026-05-31 (CoSA coverage campaign, memory group — Tiffany 💍). New file;
the module previously had no dedicated unit-test coverage.
"""

import unittest
from unittest.mock import Mock, patch


class TestGistCacheTable( unittest.TestCase ):
    """
    Comprehensive unit tests for the GistCacheTable class.

    Ensures:
        - Initialization handles create / open / corruption-recovery paths
        - Two-tier cached lookups + write + stats behave per contract
        - All error branches degrade gracefully (or re-raise where documented)
    """

    def _build_cache( self, table_exists=False, debug=False, verbose=False,
                      table_name="gist_cache", corrupted_init=False ):
        """
        Construct a GistCacheTable with lancedb + Normalizer mocked at the boundary.

        For method-level tests prefer the default table_exists=False (create path):
        it does NOT invoke _is_table_corrupted during __init__, so the scan-mock
        (mocks["pylist"]) stays pristine for the test body to configure.

        Args:
            table_exists    : if True, db.table_names() reports the table (open path)
            debug / verbose : forwarded to the constructor
            table_name      : cache table name
            corrupted_init  : if True (with table_exists), the in-__init__ corruption
                              scan raises a "not found" error → recreate path

        Returns:
            Tuple of (cache_instance, mocks_dict). mocks_dict["pylist"] is the
            terminal .to_pylist mock of the scan chain — set its return_value or
            side_effect to drive query results.
        """
        mock_normalizer = Mock()
        mock_normalizer.normalize.side_effect = lambda q: q.lower()

        mock_tbl = Mock()
        pylist   = mock_tbl.to_lance.return_value.scanner.return_value.to_table.return_value.to_pylist
        if corrupted_init:
            pylist.side_effect = Exception( "Dataset not found" )
        else:
            pylist.return_value = []
        mock_tbl.count_rows.return_value = 0

        mock_db = Mock()
        mock_db.table_names.return_value  = [ table_name ] if table_exists else []
        mock_db.open_table.return_value   = mock_tbl
        mock_db.create_table.return_value = mock_tbl

        with patch( "cosa.memory.gist_cache_table.lancedb" ) as mock_lancedb, \
             patch( "cosa.memory.gist_cache_table.Normalizer", return_value=mock_normalizer ):

            mock_lancedb.connect.return_value = mock_db
            from cosa.memory.gist_cache_table import GistCacheTable
            cache = GistCacheTable( "/db/uri", table_name=table_name, debug=debug, verbose=verbose )

        mocks = {
            "db"         : mock_db,
            "tbl"        : mock_tbl,
            "normalizer" : mock_normalizer,
            "pylist"     : pylist,
            "scanner"    : mock_tbl.to_lance.return_value.scanner,
        }
        return cache, mocks

    # ------------------------------------------------------------------ #
    # __init__ / _create_table                                            #
    # ------------------------------------------------------------------ #

    def test_init_creates_table_when_missing( self ):
        """
        Test initialization creates the table (with FTS indexes) when absent.

        Ensures:
            - create_table invoked; two FTS indexes built
            - debug=True exercises the create + count traces
        """
        cache, mocks = self._build_cache( table_exists=False, debug=True )

        mocks["db"].create_table.assert_called_once()
        self.assertEqual( mocks["tbl"].create_fts_index.call_count, 2 )
        mocks["db"].open_table.assert_not_called()

    def test_init_opens_existing_healthy_table( self ):
        """
        Test initialization opens an existing, healthy table without recreating.

        Ensures:
            - open_table invoked; corruption check returns healthy → no drop
        """
        cache, mocks = self._build_cache( table_exists=True, debug=False )

        mocks["db"].open_table.assert_called_once_with( "gist_cache" )
        mocks["db"].drop_table.assert_not_called()
        mocks["db"].create_table.assert_not_called()

    def test_init_recreates_on_corruption( self ):
        """
        Test initialization auto-recreates a corrupted existing table.

        Ensures:
            - A "not found" scan error during the corruption check triggers
              drop_table + a fresh _create_table
        """
        cache, mocks = self._build_cache( table_exists=True, corrupted_init=True, debug=True )

        mocks["db"].drop_table.assert_called_once_with( "gist_cache" )
        mocks["db"].create_table.assert_called_once()

    # ------------------------------------------------------------------ #
    # _is_table_corrupted                                                 #
    # ------------------------------------------------------------------ #

    def test_is_table_corrupted_healthy( self ):
        """
        Test _is_table_corrupted reports healthy when a scan succeeds.

        Ensures:
            - A successful limit(1) scan returns False
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].side_effect = None
        mocks["pylist"].return_value = [ { "question_verbatim": "x" } ]

        self.assertFalse( cache._is_table_corrupted() )

    def test_is_table_corrupted_not_found( self ):
        """
        Test a "not found" scan error is classified as corruption.

        Ensures:
            - Error string containing 'not found' → True
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].side_effect = Exception( "Fragment file Not Found on disk" )

        self.assertTrue( cache._is_table_corrupted() )

    def test_is_table_corrupted_lance_error( self ):
        """
        Test a lance-specific scan error is classified as corruption.

        Ensures:
            - Error string containing 'lance' → True
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].side_effect = Exception( "Lance IO error reading fragment" )

        self.assertTrue( cache._is_table_corrupted() )

    def test_is_table_corrupted_unexpected_error_reraises( self ):
        """
        Test an unexpected (non-corruption) scan error is re-raised.

        Ensures:
            - An error string without 'not found'/'lance' propagates
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].side_effect = RuntimeError( "permission denied" )

        with self.assertRaises( RuntimeError ):
            cache._is_table_corrupted()

    # ------------------------------------------------------------------ #
    # has_cached_gist                                                     #
    # ------------------------------------------------------------------ #

    def test_has_cached_gist_true_with_quote_escaping( self ):
        """
        Test has_cached_gist returns True and escapes single quotes in the filter.

        Ensures:
            - A non-empty scan result yields True
            - The apostrophe is doubled in the SQL-style filter predicate
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].return_value = [ { "question_verbatim": "it's hot" } ]

        self.assertTrue( cache.has_cached_gist( "it's hot" ) )
        used_filter = mocks["scanner"].call_args.kwargs["filter"]
        self.assertIn( "it''s hot", used_filter )

    def test_has_cached_gist_false_when_empty( self ):
        """
        Test has_cached_gist returns False when no rows match.

        Ensures:
            - An empty scan result yields False
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["pylist"].return_value = []

        self.assertFalse( cache.has_cached_gist( "missing" ) )

    def test_has_cached_gist_error_returns_false( self ):
        """
        Test has_cached_gist swallows scan errors and returns False.

        Ensures:
            - A scan exception is caught and False returned in both debug modes
              (both arms of the except-side debug guard)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug )
                mocks["pylist"].side_effect = Exception( "scan boom" )

                self.assertFalse( cache.has_cached_gist( "boom" ) )

    # ------------------------------------------------------------------ #
    # get_cached_gist — two-tier                                          #
    # ------------------------------------------------------------------ #

    def test_get_cached_gist_verbatim_hit( self ):
        """
        Test get_cached_gist returns a tier-1 verbatim match.

        Ensures:
            - A verbatim hit short-circuits before normalization
            - Both arms of the debug+verbose timer guard are exercised
        """
        for debug, verbose in ( ( True, True ), ( False, False ) ):
            with self.subTest( debug=debug, verbose=verbose ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug, verbose=verbose )
                mocks["pylist"].return_value = [ { "question_gist": "verbatim gist" } ]

                self.assertEqual( cache.get_cached_gist( "what time is it" ), "verbatim gist" )
                mocks["normalizer"].normalize.assert_not_called()

    def test_get_cached_gist_normalized_hit( self ):
        """
        Test get_cached_gist falls back to a tier-2 normalized match.

        Ensures:
            - Verbatim miss → normalize → normalized hit returns the gist
            - Both arms of the debug+verbose timer guard are exercised
        """
        for debug, verbose in ( ( True, True ), ( False, False ) ):
            with self.subTest( debug=debug, verbose=verbose ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug, verbose=verbose )
                mocks["pylist"].side_effect = [ [], [ { "question_gist": "normalized gist" } ] ]

                self.assertEqual( cache.get_cached_gist( "what time is it" ), "normalized gist" )
                mocks["normalizer"].normalize.assert_called_once_with( "what time is it" )

    def test_get_cached_gist_both_tiers_miss( self ):
        """
        Test get_cached_gist returns None when both tiers miss.

        Ensures:
            - Verbatim miss + normalized miss → None
            - Both arms of the debug+verbose MISS-trace guard are exercised
        """
        for debug, verbose in ( ( True, True ), ( False, False ) ):
            with self.subTest( debug=debug, verbose=verbose ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug, verbose=verbose )
                mocks["pylist"].side_effect = [ [], [] ]

                self.assertIsNone( cache.get_cached_gist( "what time is it" ) )

    def test_get_cached_gist_outer_exception_returns_none( self ):
        """
        Test get_cached_gist catches an error between the two tiers.

        Ensures:
            - With verbatim missing, a normalizer failure is caught and None returned
            - Both arms of the except-side debug guard are exercised
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug )
                mocks["pylist"].return_value = []
                mocks["normalizer"].normalize.side_effect = Exception( "norm boom" )

                self.assertIsNone( cache.get_cached_gist( "what time is it" ) )

    # ------------------------------------------------------------------ #
    # _get_cached_by_verbatim / _get_cached_by_normalized                 #
    # ------------------------------------------------------------------ #

    def test_get_cached_by_verbatim_hit_miss_error( self ):
        """
        Test the verbatim helper across hit, miss, and error.

        Ensures:
            - Row present → its question_gist
            - No rows → None
            - Scan error → None (debug trace)
        """
        cache, mocks = self._build_cache( table_exists=False, debug=True )

        mocks["pylist"].return_value = [ { "question_gist": "g" } ]
        self.assertEqual( cache._get_cached_by_verbatim( "q" ), "g" )

        mocks["pylist"].return_value = []
        self.assertIsNone( cache._get_cached_by_verbatim( "q" ) )

        mocks["pylist"].side_effect = Exception( "verb boom" )
        self.assertIsNone( cache._get_cached_by_verbatim( "q" ) )

        # debug=False arm of the except-side guard
        cache_nd, mocks_nd = self._build_cache( table_exists=False, debug=False )
        mocks_nd["pylist"].side_effect = Exception( "verb boom" )
        self.assertIsNone( cache_nd._get_cached_by_verbatim( "q" ) )

    def test_get_cached_by_normalized_hit_miss_error( self ):
        """
        Test the normalized helper across hit, miss, and error.

        Ensures:
            - Row present → its question_gist
            - No rows → None
            - Scan error → None (debug trace)
        """
        cache, mocks = self._build_cache( table_exists=False, debug=True )

        mocks["pylist"].return_value = [ { "question_gist": "n" } ]
        self.assertEqual( cache._get_cached_by_normalized( "qn" ), "n" )

        mocks["pylist"].return_value = []
        self.assertIsNone( cache._get_cached_by_normalized( "qn" ) )

        mocks["pylist"].side_effect = Exception( "norm boom" )
        self.assertIsNone( cache._get_cached_by_normalized( "qn" ) )

        # debug=False arm of the except-side guard
        cache_nd, mocks_nd = self._build_cache( table_exists=False, debug=False )
        mocks_nd["pylist"].side_effect = Exception( "norm boom" )
        self.assertIsNone( cache_nd._get_cached_by_normalized( "qn" ) )

    # ------------------------------------------------------------------ #
    # cache_gist                                                          #
    # ------------------------------------------------------------------ #

    def test_cache_gist_new_entry_inserts( self ):
        """
        Test cache_gist inserts a new row when the question is not cached.

        Ensures:
            - has_cached_gist (empty scan) → not duplicate
            - A row with the full schema is added; debug trace exercised
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug )
                mocks["pylist"].return_value = []   # has_cached_gist → False

                cache.cache_gist( "what time is it", "time gist", normalized="what time is it" )

                mocks["tbl"].add.assert_called_once()
                row = mocks["tbl"].add.call_args[0][0][0]
                self.assertEqual( row["question_verbatim"], "what time is it" )
                self.assertEqual( row["question_gist"], "time gist" )
                self.assertEqual( row["question_normalized"], "what time is it" )
                self.assertEqual( row["access_count"], 0 )

    def test_cache_gist_duplicate_skips_insert( self ):
        """
        Test cache_gist skips insertion when the question is already cached.

        Ensures:
            - has_cached_gist (non-empty scan) → duplicate → no add (debug trace)
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug )
                mocks["pylist"].return_value = [ { "question_verbatim": "dup" } ]

                cache.cache_gist( "dup", "gist" )

                mocks["tbl"].add.assert_not_called()

    def test_cache_gist_error_is_swallowed( self ):
        """
        Test cache_gist catches an insert failure.

        Ensures:
            - A table.add error is caught (debug trace); no propagation
        """
        for debug in ( False, True ):
            with self.subTest( debug=debug ):
                cache, mocks = self._build_cache( table_exists=False, debug=debug )
                mocks["pylist"].return_value = []          # not a duplicate
                mocks["tbl"].add.side_effect = Exception( "add boom" )

                # Should not raise
                cache.cache_gist( "what time is it", "gist" )

    # ------------------------------------------------------------------ #
    # get_statistics                                                      #
    # ------------------------------------------------------------------ #

    def test_get_statistics_with_sample( self ):
        """
        Test get_statistics aggregates a non-empty sample.

        Ensures:
            - total_entries from count_rows
            - avg_access_count = mean of sample access counts
            - sample_size + table_name reported
        """
        cache, mocks = self._build_cache( table_exists=False, table_name="gc" )
        mocks["tbl"].count_rows.return_value = 5
        mocks["pylist"].return_value = [ { "access_count": 2 }, { "access_count": 4 } ]

        stats = cache.get_statistics()

        self.assertEqual( stats["total_entries"], 5 )
        self.assertEqual( stats["avg_access_count"], 3.0 )
        self.assertEqual( stats["sample_size"], 2 )
        self.assertEqual( stats["table_name"], "gc" )

    def test_get_statistics_empty_sample( self ):
        """
        Test get_statistics handles an empty sample without dividing by zero.

        Ensures:
            - avg_access_count is 0 and sample_size is 0 when no rows exist
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["tbl"].count_rows.return_value = 0
        mocks["pylist"].return_value = []

        stats = cache.get_statistics()

        self.assertEqual( stats["avg_access_count"], 0 )
        self.assertEqual( stats["sample_size"], 0 )

    def test_get_statistics_error_returns_error_dict( self ):
        """
        Test get_statistics returns an error dict on failure.

        Ensures:
            - A count_rows exception is caught and surfaced under 'error'
        """
        cache, mocks = self._build_cache( table_exists=False )
        mocks["tbl"].count_rows.side_effect = Exception( "stats boom" )

        stats = cache.get_statistics()
        self.assertIn( "error", stats )

    # ------------------------------------------------------------------ #
    # clear_cache                                                         #
    # ------------------------------------------------------------------ #

    def test_clear_cache_debug_logs_not_implemented( self ):
        """
        Test clear_cache logs its not-implemented notice under debug.

        Ensures:
            - debug=True exercises the count_rows + warning print branch
        """
        cache, mocks = self._build_cache( table_exists=False, debug=True )
        mocks["tbl"].count_rows.return_value = 9

        cache.clear_cache()   # no-op; should not raise
        mocks["tbl"].count_rows.assert_called()

    def test_clear_cache_debug_off_is_silent_noop( self ):
        """
        Test clear_cache is a silent no-op when debug is off.

        Ensures:
            - debug=False skips the count_rows print branch entirely
        """
        cache, mocks = self._build_cache( table_exists=False, debug=False )
        mocks["tbl"].count_rows.reset_mock()

        cache.clear_cache()
        mocks["tbl"].count_rows.assert_not_called()

    def test_clear_cache_error_is_swallowed( self ):
        """
        Test clear_cache catches an error raised while logging.

        Ensures:
            - A count_rows failure inside the debug branch is caught (no propagation)
        """
        cache, mocks = self._build_cache( table_exists=False, debug=True )
        mocks["tbl"].count_rows.side_effect = Exception( "clear boom" )

        cache.clear_cache()   # should not raise


if __name__ == "__main__":
    unittest.main()
