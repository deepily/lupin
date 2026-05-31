"""
Unit tests for cosa.agents.deep_research.search_cache.

NEW FILE 2026-05-31 by Rio ⚡ (CoSA coverage campaign, deep_research lane). The
module is pure local file-cache logic. Tests run against an isolated
tempfile.TemporaryDirectory with cu.get_project_root patched to it — real (but
sandboxed) filesystem I/O, NO network/LLM. IOError/corrupt-JSON arms are driven
by patching open/os.remove at the boundary.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from cosa.agents.deep_research import search_cache as sc


_SC = "cosa.agents.deep_research.search_cache"


class _CacheBase( unittest.TestCase ):
    def setUp( self ):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup( self.tmp.cleanup )
        p = patch( f"{_SC}.cu.get_project_root", return_value=self.tmp.name )
        self.mock_root = p.start()
        self.addCleanup( p.stop )
        self.email = "test@example.com"


class TestNormalizeQuery( unittest.TestCase ):

    def test_lowercase_sorted_dedup_order( self ):
        self.assertEqual( sc.normalize_query( "AI coding assistants" ), "search-ai-assistants-coding" )
        # word ORDER does not matter — sorted → same key
        self.assertEqual( sc.normalize_query( "coding assistants AI" ), "search-ai-assistants-coding" )

    def test_punctuation_stripped( self ):
        self.assertEqual( sc.normalize_query( "What are the BEST tools?" ), "search-are-best-the-tools-what" )

    def test_capped_at_six_words( self ):
        key = sc.normalize_query( "alpha bravo charlie delta echo foxtrot golf hotel" )
        # 8 words → sorted, first 6 only
        self.assertEqual( key, "search-alpha-bravo-charlie-delta-echo-foxtrot" )


class TestGetCacheDir( _CacheBase ):

    def test_explicit_date_creates_dir( self ):
        d = sc.get_cache_dir( self.email, date="2026.05.31" )
        self.assertTrue( os.path.isdir( d ) )
        self.assertIn( self.email, d )
        self.assertTrue( d.endswith( "2026.05.31" ) )

    def test_default_date_is_today( self ):
        with patch( f"{_SC}.datetime" ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026.01.02"
            d = sc.get_cache_dir( self.email )
        self.assertTrue( d.endswith( "2026.01.02" ) )
        self.assertTrue( os.path.isdir( d ) )


class TestSaveLoadExists( _CacheBase ):

    def test_save_then_load_roundtrip( self ):
        path = sc.save_to_cache( self.email, "my query", { "content": "abc", "n": 1 } )
        self.assertTrue( os.path.exists( path ) )
        loaded = sc.load_cached_result( self.email, "my query" )
        self.assertEqual( loaded[ "query" ], "my query" )
        self.assertEqual( loaded[ "results" ][ "content" ], "abc" )
        self.assertEqual( loaded[ "normalized_key" ], sc.normalize_query( "my query" ) )

    def test_cache_exists_true_false( self ):
        sc.save_to_cache( self.email, "present query", { "x": 1 } )
        self.assertTrue( sc.cache_exists( self.email, "present query" ) )
        self.assertFalse( sc.cache_exists( self.email, "absent query zzz" ) )

    def test_load_miss_returns_none( self ):
        self.assertIsNone( sc.load_cached_result( self.email, "never cached" ) )

    def test_load_corrupt_json_returns_none( self ):
        # write a corrupt cache file at the exact path load expects
        cache_dir = sc.get_cache_dir( self.email )
        path = f"{cache_dir}/{sc.normalize_query( 'broken query' )}.json"
        with open( path, "w" ) as f:
            f.write( "{not valid json" )
        self.assertIsNone( sc.load_cached_result( self.email, "broken query" ) )

    def test_save_ioerror_still_returns_path( self ):
        # open() raising IOError is caught + logged; the path is still returned
        with patch( f"{_SC}.open", side_effect=IOError( "disk full" ) ):
            path = sc.save_to_cache( self.email, "doomed query", { "x": 1 } )
        self.assertTrue( path.endswith( ".json" ) )
        self.assertFalse( os.path.exists( path ) )           # write never succeeded


class TestListAndFormat( _CacheBase ):

    def test_list_empty_when_no_dir( self ):
        # never created any cache for an explicit far-past date
        self.assertEqual( sc.list_cached_queries( self.email, date="2000.01.01" ), [] )

    def test_list_returns_query_tuples( self ):
        sc.save_to_cache( self.email, "first query", { "x": 1 } )
        sc.save_to_cache( self.email, "second query", { "y": 2 } )
        listed = sc.list_cached_queries( self.email )
        queries = [ q for _, q in listed ]
        self.assertIn( "first query", queries )
        self.assertIn( "second query", queries )

    def test_list_corrupt_file_falls_back_to_filename( self ):
        cache_dir = sc.get_cache_dir( self.email )
        bad = f"{cache_dir}/search-corrupt.json"
        with open( bad, "w" ) as f:
            f.write( "{broken" )
        listed = sc.list_cached_queries( self.email )
        # corrupt file → (filename, filename) fallback
        self.assertIn( ( "search-corrupt.json", "search-corrupt.json" ), listed )

    def test_list_ignores_non_json_files( self ):
        sc.save_to_cache( self.email, "kept query", { "x": 1 } )
        cache_dir = sc.get_cache_dir( self.email )
        with open( f"{cache_dir}/stray.txt", "w" ) as f:     # non-.json → endswith False arc
            f.write( "ignore me" )
        listed = sc.list_cached_queries( self.email )
        names = [ fn for fn, _ in listed ]
        self.assertNotIn( "stray.txt", names )
        self.assertIn( "kept query", [ q for _, q in listed ] )

    def test_list_default_date_today( self ):
        with patch( f"{_SC}.datetime" ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026.03.03"
            # no dir for that date → empty
            self.assertEqual( sc.list_cached_queries( self.email ), [] )

    def test_format_empty( self ):
        self.assertEqual( sc.format_cache_listing( [] ), "" )

    def test_format_populated( self ):
        out = sc.format_cache_listing( [ ( "search-a.json", "query a" ), ( "search-b.json", "query b" ) ] )
        self.assertIn( "Available cached searches from today:", out )
        self.assertIn( '- search-a.json ("query a")', out )
        self.assertIn( '- search-b.json ("query b")', out )


class TestClearCache( _CacheBase ):

    def test_clear_deletes_json_files( self ):
        sc.save_to_cache( self.email, "q1", { "x": 1 } )
        sc.save_to_cache( self.email, "q2", { "y": 2 } )
        deleted = sc.clear_cache( self.email )
        self.assertEqual( deleted, 2 )
        self.assertEqual( sc.list_cached_queries( self.email ), [] )

    def test_clear_ignores_non_json_files( self ):
        sc.save_to_cache( self.email, "q1", { "x": 1 } )
        cache_dir = sc.get_cache_dir( self.email )
        with open( f"{cache_dir}/keep.txt", "w" ) as f:      # non-.json → endswith False arc
            f.write( "stays" )
        deleted = sc.clear_cache( self.email )
        self.assertEqual( deleted, 1 )                       # only the .json removed
        self.assertTrue( os.path.exists( f"{cache_dir}/keep.txt" ) )

    def test_clear_no_dir_returns_zero( self ):
        self.assertEqual( sc.clear_cache( self.email, date="1999.12.31" ), 0 )

    def test_clear_remove_ioerror_is_swallowed( self ):
        sc.save_to_cache( self.email, "q1", { "x": 1 } )
        with patch( f"{_SC}.os.remove", side_effect=IOError( "locked" ) ):
            deleted = sc.clear_cache( self.email )
        self.assertEqual( deleted, 0 )                       # removal failed → not counted, warning logged

    def test_clear_default_date_today( self ):
        with patch( f"{_SC}.datetime" ) as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "2026.04.04"
            self.assertEqual( sc.clear_cache( self.email ), 0 )   # no dir for that date


if __name__ == "__main__":
    unittest.main()
