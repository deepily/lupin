"""
Unit tests for swe_team/state_files.py — cross-session persistence:
  - FeatureList : feature_list.json read/write/add/mark_complete/get_pending
  - ProgressLog : append-only claude-progress.txt log/read_recent/get_summary

Uses real tempfile.TemporaryDirectory for fs isolation (writes confined to tmp);
builtins.open is patched only to drive the IOError/JSONDecodeError error arcs.
No LLM/SDK/network.

Created 2026-05-31 by Extra 1 🪨 (CoSA coverage campaign, swe_team lane, mid tier).
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import cosa.agents.swe_team.state_files as sf
from cosa.agents.swe_team.state import TaskSpec


class TestFeatureList( unittest.TestCase ):

    def test_init_uses_tempdir_when_none( self ):
        fl = sf.FeatureList()
        self.assertIsNotNone( fl._tmpdir )
        self.assertTrue( os.path.isdir( fl.storage_dir ) )
        fl.cleanup()

    def test_init_creates_explicit_storage_dir( self ):
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join( d, "nested", "swe" )
            fl = sf.FeatureList( storage_dir=target )
            self.assertIsNone( fl._tmpdir )
            self.assertTrue( os.path.isdir( target ) )

    def test_load_missing_file_returns_empty( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            self.assertEqual( fl.load(), [] )

    def test_add_task_from_taskspec_then_load_roundtrip( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            fl.add_task( TaskSpec( title="t1", objective="o", output_format="f" ) )
            self.assertEqual( len( fl.tasks ), 1 )
            self.assertFalse( fl.tasks[ 0 ][ "completed" ] )
            # Reload via a fresh instance.
            fl2 = sf.FeatureList( storage_dir=d )
            loaded = fl2.load()
            self.assertEqual( loaded[ 0 ][ "title" ], "t1" )

    def test_add_task_from_dict( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            fl.add_task( { "title": "raw" } )   # non-TaskSpec → dict() path
            self.assertEqual( fl.tasks[ 0 ][ "title" ], "raw" )
            self.assertFalse( fl.tasks[ 0 ][ "completed" ] )

    def test_load_corrupt_json_returns_empty_and_warns( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            with open( fl.file_path, "w" ) as f:
                f.write( "{ not valid json" )
            self.assertEqual( fl.load(), [] )   # JSONDecodeError arc

    def test_save_ioerror_is_logged_not_raised( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            fl.tasks = [ { "title": "x" } ]
            with patch( "builtins.open", side_effect=IOError( "disk full" ) ):
                fl.save()   # must not raise

    def test_mark_complete_and_get_pending( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            fl.add_task( { "title": "a" } )
            fl.add_task( { "title": "b" } )
            fl.mark_complete( 0 )
            self.assertTrue( fl.tasks[ 0 ][ "completed" ] )
            pending = fl.get_pending()
            self.assertEqual( len( pending ), 1 )
            self.assertEqual( pending[ 0 ][ 0 ], 1 )

    def test_mark_complete_out_of_range_raises( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            with self.assertRaises( IndexError ):
                fl.mark_complete( 0 )
            fl.add_task( { "title": "a" } )
            with self.assertRaises( IndexError ):
                fl.mark_complete( 5 )

    def test_cleanup_noop_when_explicit_dir( self ):
        with tempfile.TemporaryDirectory() as d:
            fl = sf.FeatureList( storage_dir=d )
            fl.cleanup()   # _tmpdir is None → no-op, no raise


class TestProgressLog( unittest.TestCase ):

    def test_init_uses_tempdir_when_none( self ):
        pl = sf.ProgressLog()
        self.assertIsNotNone( pl._tmpdir )
        self.assertTrue( os.path.isdir( pl.storage_dir ) )
        pl.cleanup()

    def test_init_explicit_dir( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=os.path.join( d, "p" ) )
            self.assertIsNone( pl._tmpdir )
            self.assertTrue( os.path.isdir( pl.storage_dir ) )

    def test_log_and_read_recent( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            pl.log( "first", role="lead" )
            pl.log( "second", role="coder" )
            recent = pl.read_recent( 1 )
            self.assertEqual( len( recent ), 1 )
            self.assertIn( "[coder]", recent[ 0 ] )

    def test_log_invokes_on_log_callback( self ):
        seen = []
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d, on_log=lambda m, r: seen.append( ( m, r ) ) )
            pl.log( "msg", role="tester" )
        self.assertEqual( seen, [ ( "msg", "tester" ) ] )

    def test_log_callback_exception_is_swallowed( self ):
        def boom( m, r ): raise RuntimeError( "cb fail" )
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d, on_log=boom )
            pl.log( "msg" )   # must not raise

    def test_log_write_ioerror_logged_not_raised( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            with patch( "builtins.open", side_effect=IOError( "nope" ) ):
                pl.log( "msg" )   # must not raise

    def test_read_recent_missing_file_returns_empty( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            self.assertEqual( pl.read_recent(), [] )

    def test_read_recent_ioerror_returns_empty( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            pl.log( "x" )   # create the file
            with patch( "builtins.open", side_effect=IOError( "read fail" ) ):
                self.assertEqual( pl.read_recent(), [] )

    def test_get_summary_empty( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            self.assertEqual( pl.get_summary(), "No progress logged" )

    def test_get_summary_with_entries( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            pl.log( "a" )
            pl.log( "b" )
            summ = pl.get_summary()
            self.assertIn( "2 entries", summ )
            self.assertIn( "Last:", summ )

    def test_cleanup_noop_when_explicit_dir( self ):
        with tempfile.TemporaryDirectory() as d:
            pl = sf.ProgressLog( storage_dir=d )
            pl.cleanup()   # _tmpdir None → no-op


if __name__ == "__main__":
    unittest.main()
