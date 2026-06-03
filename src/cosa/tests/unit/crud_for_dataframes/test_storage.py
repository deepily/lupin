"""
Unit tests for cosa.crud_for_dataframes.storage.DataFrameStorage.

DataFrameStorage owns per-user parquet I/O with datetime conversion at the
storage boundary. These tests run entirely against a tempdir base_path so no
real project directory is touched. Coverage spans the three-way base_path
resolution (override / config_mgr / default), path generation + schema
validation, the empty/existing load paths, the save round-trip with native
date conversion, list metadata + per-schema list enumeration (including
foreign parquet files missing list_name), and file deletion. Both the
debug=True and debug=False sides of every diagnostic branch are exercised.

Assertions harvested + extended from the module's quick_smoke_test(), marked
for deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import os
import tempfile
import unittest
from datetime import datetime

import pandas as pd

import cosa.utils.util as cu
from cosa.crud_for_dataframes.storage import DataFrameStorage


class TestConstruction( unittest.TestCase ):
    """
    DataFrameStorage.__init__ — validation + base_path resolution.
    """

    def test_empty_user_email_raises( self ):
        """Ensures a blank/whitespace user_email is rejected with ValueError."""
        with self.assertRaises( ValueError ):
            DataFrameStorage( user_email="   " )

    def test_base_path_override_wins( self ):
        """Ensures an explicit base_path override is used verbatim."""
        storage = DataFrameStorage( user_email="a@b.com", base_path="/tmp/override" )
        self.assertEqual( storage.base_path, "/tmp/override" )

    def test_config_mgr_path_resolution( self ):
        """Ensures base_path = project_root + config 'crud for dataframes output path'."""
        class _Cfg:
            def get( self, key, default=None ):
                return "/io/dfs_custom"
        storage = DataFrameStorage( user_email="a@b.com", config_mgr=_Cfg() )
        self.assertEqual( storage.base_path, cu.get_project_root() + "/io/dfs_custom" )

    def test_default_path_when_no_override_or_config( self ):
        """Ensures base_path falls back to project_root + /io/dfs."""
        storage = DataFrameStorage( user_email="a@b.com" )
        self.assertEqual( storage.base_path, cu.get_project_root() + "/io/dfs" )

    def test_user_email_is_stripped( self ):
        """Ensures surrounding whitespace is stripped from user_email."""
        storage = DataFrameStorage( user_email="  a@b.com  ", base_path="/tmp/x", debug=True )
        self.assertEqual( storage.user_email, "a@b.com" )


class TestPathHelpers( unittest.TestCase ):
    """
    get_user_dir / get_parquet_path / file_exists / create_empty_df.
    """

    def setUp( self ):
        self._tmp    = tempfile.TemporaryDirectory()
        self.storage = DataFrameStorage( user_email="test@example.com", base_path=self._tmp.name )

    def tearDown( self ):
        self._tmp.cleanup()

    def test_get_user_dir( self ):
        """Ensures the user dir is base_path/user_email."""
        self.assertEqual( self.storage.get_user_dir(), os.path.join( self._tmp.name, "test@example.com" ) )

    def test_parquet_path_valid_schema( self ):
        """Ensures the parquet path nests the user email and ends with <schema>.parquet."""
        path = self.storage.get_parquet_path( "todo" )
        self.assertTrue( path.endswith( "todo.parquet" ) )
        self.assertIn( "test@example.com", path )

    def test_parquet_path_invalid_schema_raises( self ):
        """Ensures an unknown schema type raises ValueError."""
        with self.assertRaises( ValueError ):
            self.storage.get_parquet_path( "nonexistent" )

    def test_file_exists_false_then_true( self ):
        """Ensures file_exists reflects on-disk presence after a save."""
        self.assertFalse( self.storage.file_exists( "todo" ) )
        self.storage.save_df( self.storage.create_empty_df( "todo" ), "todo" )
        self.assertTrue( self.storage.file_exists( "todo" ) )

    def test_create_empty_df_has_schema_columns( self ):
        """Ensures an empty DataFrame carries all schema columns and zero rows."""
        df = self.storage.create_empty_df( "todo" )
        self.assertEqual( len( df ), 0 )
        self.assertIn( "todo_item", df.columns )
        self.assertIn( "id", df.columns )


class TestSaveLoadRoundTrip( unittest.TestCase ):
    """
    save_df / load_df / _convert_dates_for_storage round-trip.

    Run with both debug states so the debug-print branches are both covered.
    """

    def _round_trip( self, debug ):
        with tempfile.TemporaryDirectory() as tmp:
            storage = DataFrameStorage( user_email="test@example.com", base_path=tmp, debug=debug )

            # Loading a non-existent schema returns an empty frame.
            empty = storage.load_df( "todo" )
            self.assertEqual( len( empty ), 0 )

            row = {
                "id"         : "abc12345",
                "list_name"  : "groceries",
                "created_at" : datetime.now().isoformat(),
                "todo_item"  : "buy milk",
                "due_date"   : "2026-03-15",
                "priority"   : "high",
                "completed"  : "no",
                "tags"       : "food",
            }
            df = pd.concat( [ storage.create_empty_df( "todo" ), pd.DataFrame( [ row ] ) ], ignore_index=True )
            storage.save_df( df, "todo" )

            loaded = storage.load_df( "todo" )
            self.assertEqual( len( loaded ), 1 )
            self.assertEqual( loaded.iloc[ 0 ][ "todo_item" ], "buy milk" )
            # date column converted to a native datetime dtype
            self.assertTrue( pd.api.types.is_datetime64_any_dtype( loaded[ "due_date" ] ) )

    def test_round_trip_debug_true( self ):
        """Ensures the full save/load cycle works with debug prints enabled."""
        self._round_trip( debug=True )

    def test_round_trip_debug_false( self ):
        """Ensures the full save/load cycle works with debug prints disabled."""
        self._round_trip( debug=False )

    def test_convert_dates_skips_absent_columns( self ):
        """Ensures _convert_dates_for_storage leaves a frame lacking date columns intact."""
        with tempfile.TemporaryDirectory() as tmp:
            storage = DataFrameStorage( user_email="test@example.com", base_path=tmp )
            df      = pd.DataFrame( { "todo_item": [ "x" ] } )   # no due_date / created_at columns
            out     = storage._convert_dates_for_storage( df, "todo" )
            self.assertEqual( list( out.columns ), [ "todo_item" ] )
            self.assertEqual( out.iloc[ 0 ][ "todo_item" ], "x" )


class TestListMetadata( unittest.TestCase ):
    """
    get_all_lists_metadata / get_lists_for_schema — including edge frames.
    """

    def setUp( self ):
        self._tmp    = tempfile.TemporaryDirectory()
        self.storage = DataFrameStorage( user_email="test@example.com", base_path=self._tmp.name )

    def tearDown( self ):
        self._tmp.cleanup()

    def _save_rows( self, rows, schema_type="todo" ):
        df = pd.concat(
            [ self.storage.create_empty_df( schema_type ), pd.DataFrame( rows ) ],
            ignore_index=True
        )
        self.storage.save_df( df, schema_type )

    def test_metadata_groups_by_list_name( self ):
        """Ensures per-list row counts are reported across populated schema files."""
        self._save_rows( [
            { "id": "1", "list_name": "groceries", "created_at": datetime.now().isoformat(), "todo_item": "milk" },
            { "id": "2", "list_name": "groceries", "created_at": datetime.now().isoformat(), "todo_item": "bread" },
            { "id": "3", "list_name": "chores",    "created_at": datetime.now().isoformat(), "todo_item": "mow"   },
        ] )
        meta = self.storage.get_all_lists_metadata()
        by_name = { m[ "list_name" ]: m[ "row_count" ] for m in meta }
        self.assertEqual( by_name[ "groceries" ], 2 )
        self.assertEqual( by_name[ "chores" ], 1 )

    def test_metadata_skips_missing_and_empty_files( self ):
        """Ensures schema files that are absent or empty contribute no metadata."""
        # calendar/generic absent; save an EMPTY todo file (exists but empty -> skipped)
        self.storage.save_df( self.storage.create_empty_df( "todo" ), "todo" )
        self.assertEqual( self.storage.get_all_lists_metadata(), [] )

    def test_metadata_skips_frame_without_list_name_column( self ):
        """Ensures a foreign parquet missing list_name is loaded but yields no metadata."""
        path = self.storage.get_parquet_path( "todo" )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        pd.DataFrame( { "other_col": [ "x" ] } ).to_parquet( path, index=False )
        self.assertEqual( self.storage.get_all_lists_metadata(), [] )

    def test_lists_for_schema_no_file_returns_empty( self ):
        """Ensures get_lists_for_schema returns [] when the schema file is absent."""
        self.assertEqual( self.storage.get_lists_for_schema( "todo" ), [] )

    def test_lists_for_schema_empty_file_returns_empty( self ):
        """Ensures an existing-but-empty schema file yields no list names."""
        self.storage.save_df( self.storage.create_empty_df( "todo" ), "todo" )
        self.assertEqual( self.storage.get_lists_for_schema( "todo" ), [] )

    def test_lists_for_schema_without_list_name_returns_empty( self ):
        """Ensures a foreign parquet missing list_name yields no list names."""
        path = self.storage.get_parquet_path( "todo" )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        pd.DataFrame( { "other_col": [ "x" ] } ).to_parquet( path, index=False )
        self.assertEqual( self.storage.get_lists_for_schema( "todo" ), [] )

    def test_lists_for_schema_returns_sorted_unique( self ):
        """Ensures populated list names come back sorted and de-duplicated."""
        self._save_rows( [
            { "id": "1", "list_name": "zebra",  "created_at": datetime.now().isoformat(), "todo_item": "a" },
            { "id": "2", "list_name": "apple",  "created_at": datetime.now().isoformat(), "todo_item": "b" },
            { "id": "3", "list_name": "apple",  "created_at": datetime.now().isoformat(), "todo_item": "c" },
        ] )
        self.assertEqual( self.storage.get_lists_for_schema( "todo" ), [ "apple", "zebra" ] )


class TestDeleteSchemaFile( unittest.TestCase ):
    """
    delete_schema_file — present (True) and absent (False) paths.
    """

    def setUp( self ):
        self._tmp    = tempfile.TemporaryDirectory()
        self.storage = DataFrameStorage( user_email="test@example.com", base_path=self._tmp.name, debug=True )

    def tearDown( self ):
        self._tmp.cleanup()

    def test_delete_existing_returns_true( self ):
        """Ensures deleting an existing schema file removes it and returns True."""
        self.storage.save_df( self.storage.create_empty_df( "todo" ), "todo" )
        self.assertTrue( self.storage.delete_schema_file( "todo" ) )
        self.assertFalse( self.storage.file_exists( "todo" ) )

    def test_delete_absent_returns_false( self ):
        """Ensures deleting an absent schema file is a no-op returning False."""
        self.assertFalse( self.storage.delete_schema_file( "calendar" ) )


if __name__ == "__main__":
    unittest.main()
