"""
Unit tests for cosa.utils.util_pandas.

Covers cast_to_datetime(), the module-level read_csv() helper, and the
DeepilyDataFrame subclass (path-aware read_csv + save with .csv guard and
chmod). Uses real in-memory DataFrames and tempfiles — no mocking needed.

Assertions strengthened from the module's __main__ demo block (now superseded).
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import cosa.utils.util_pandas as dup
from cosa.utils.util_pandas import cast_to_datetime, read_csv, DeepilyDataFrame


class TestCastToDatetime( unittest.TestCase ):
    """cast_to_datetime() converts only object columns ending in '_date'."""

    def test_date_column_converted( self ):
        df = pd.DataFrame( { "start_date": [ "2026-01-01", "2026-02-02" ], "name": [ "a", "b" ] } )
        out = cast_to_datetime( df )
        self.assertTrue( pd.api.types.is_datetime64_any_dtype( out[ "start_date" ] ) )

    def test_non_date_column_unchanged( self ):
        df = pd.DataFrame( { "name": [ "a", "b" ], "count": [ 1, 2 ] } )
        out = cast_to_datetime( df, debug=True )
        self.assertFalse( pd.api.types.is_datetime64_any_dtype( out[ "name" ] ) )

    def test_date_column_non_string_dtype_left_unconverted( self ):
        # An object column ending '_date' that is NOT string-typed is skipped
        # (the is_string_dtype False branch).
        df = pd.DataFrame( { "start_date": [ "2026-01-01" ] } )
        with patch( "cosa.utils.util_pandas.pd.api.types.is_string_dtype", return_value=False ):
            out = cast_to_datetime( df )
        self.assertFalse( pd.api.types.is_datetime64_any_dtype( out[ "start_date" ] ) )


class TestDeepilyDataFrame( unittest.TestCase ):
    """Path-aware DataFrame subclass: read_csv, _constructor, save."""

    def _tmp_csv( self, df ):
        path = tempfile.NamedTemporaryFile( suffix=".csv", delete=False ).name
        df.to_csv( path, index=False )
        self.addCleanup( lambda: os.path.exists( path ) and os.unlink( path ) )
        return path

    def test_read_csv_helper_returns_deepily_frame( self ):
        path = self._tmp_csv( pd.DataFrame( { "a": [ 1, 2 ] } ) )
        ddf = read_csv( path )
        self.assertIsInstance( ddf, DeepilyDataFrame )
        self.assertEqual( ddf._path, path )

    def test_constructor_propagates_subclass( self ):
        path = self._tmp_csv( pd.DataFrame( { "a": [ 1, 2 ], "b": [ 3, 4 ] } ) )
        ddf = DeepilyDataFrame.read_csv( path )
        # A column selection should still yield a DeepilyDataFrame via _constructor.
        self.assertIsInstance( ddf[ [ "a" ] ], DeepilyDataFrame )

    def test_save_to_original_path( self ):
        path = self._tmp_csv( pd.DataFrame( { "a": [ 1 ] } ) )
        ddf = read_csv( path )
        saved = ddf.save()
        self.assertEqual( saved, path )
        self.assertEqual( os.stat( path ).st_mode & 0o666, 0o666 )

    def test_save_to_explicit_path( self ):
        src = self._tmp_csv( pd.DataFrame( { "a": [ 1 ] } ) )
        ddf = read_csv( src )
        dest = tempfile.NamedTemporaryFile( suffix=".csv", delete=False ).name
        self.addCleanup( lambda: os.path.exists( dest ) and os.unlink( dest ) )
        self.assertEqual( ddf.save( dest ), dest )

    def test_save_without_path_raises( self ):
        ddf = DeepilyDataFrame( pd.DataFrame( { "a": [ 1 ] } ) )   # no _path set
        with self.assertRaises( ValueError ):
            ddf.save()

    def test_save_non_csv_path_raises( self ):
        ddf = DeepilyDataFrame( pd.DataFrame( { "a": [ 1 ] } ), path="/tmp/x.txt" )
        with self.assertRaises( ValueError ):
            ddf.save()


if __name__ == "__main__":
    unittest.main()
