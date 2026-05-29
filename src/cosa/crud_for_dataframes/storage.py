#!/usr/bin/env python3
"""
Per-user parquet I/O with datetime conversion at the storage boundary.

DataFrameStorage handles reading and writing parquet files for per-user
DataFrames. It converts ISO string date/time/datetime columns to native
pandas types before writing and provides native types on read.

Storage layout:
    {base_path}/{user_email}/{schema_type}.parquet
"""

import os
from datetime import datetime

import pandas as pd

import cosa.utils.util as cu
from cosa.crud_for_dataframes.schemas import (
    get_schema,
    get_columns,
    get_defaults,
    get_date_columns,
    get_time_columns,
    get_datetime_columns,
    validate_schema_type,
    VALID_SCHEMA_TYPES,
)


class DataFrameStorage:
    """
    Per-user parquet-backed DataFrame storage.

    Handles parquet I/O with automatic datetime conversion at the
    storage boundary. Each user gets their own directory under base_path,
    with one parquet file per schema type.

    Constructor args:
        user_email: User identifier for per-user isolation
        config_mgr: Optional ConfigurationManager instance
        base_path: Optional override for storage root (useful for testing)
        debug: Enable debug output
    """

    def __init__( self, user_email, config_mgr=None, base_path=None, debug=False ):
        """
        Initialize DataFrameStorage.

        Requires:
            - user_email is a non-empty string

        Ensures:
            - self.user_email is set
            - self.base_path is resolved from config or override
            - self.debug is set
        """
        if not user_email or not user_email.strip():
            raise ValueError( "user_email is required and cannot be empty" )

        self.user_email = user_email.strip()
        self.debug      = debug

        # Resolve base path: override > config > default
        if base_path is not None:
            self.base_path = str( base_path )
        elif config_mgr is not None:
            output_path = config_mgr.get( "crud for dataframes output path", default="/io/dfs" )
            self.base_path = cu.get_project_root() + output_path
        else:
            self.base_path = cu.get_project_root() + "/io/dfs"

        if self.debug: print( f"DataFrameStorage: base_path={self.base_path}, user={self.user_email}" )

    def get_user_dir( self ):
        """
        Get the user-specific storage directory path.

        Requires:
            - self.base_path and self.user_email are set

        Ensures:
            - Returns path string: {base_path}/{user_email}
        """
        return os.path.join( self.base_path, self.user_email )

    def get_parquet_path( self, schema_type ):
        """
        Get the parquet file path for a schema type.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Returns path string: {base_path}/{user_email}/{schema_type}.parquet
        """
        if not validate_schema_type( schema_type ):
            raise ValueError( f"Unknown schema type '{schema_type}'. Valid types: {VALID_SCHEMA_TYPES}" )

        return os.path.join( self.get_user_dir(), f"{schema_type}.parquet" )

    def file_exists( self, schema_type ):
        """
        Check if a parquet file exists for a schema type.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Returns True if the parquet file exists on disk
            - Returns False otherwise
        """
        return os.path.exists( self.get_parquet_path( schema_type ) )

    def create_empty_df( self, schema_type ):
        """
        Create an empty DataFrame with the correct columns for a schema type.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Returns an empty DataFrame with all columns from the schema
            - All columns are object (str) dtype initially
        """
        columns = get_columns( schema_type )
        return pd.DataFrame( columns=columns )

    def load_df( self, schema_type ):
        """
        Load a DataFrame from parquet, or return empty if file doesn't exist.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Returns DataFrame with native datetime types for date/time/datetime columns
            - Returns empty DataFrame with correct columns if file doesn't exist
        """
        path = self.get_parquet_path( schema_type )

        if not os.path.exists( path ):
            if self.debug: print( f"DataFrameStorage.load_df: No file at {path}, returning empty" )
            return self.create_empty_df( schema_type )

        if self.debug: print( f"DataFrameStorage.load_df: Reading {path}" )
        df = pd.read_parquet( path )
        return df

    def save_df( self, df, schema_type ):
        """
        Save a DataFrame to parquet with datetime conversion.

        Converts ISO string date/time/datetime columns to native pandas
        types before writing. This enables parquet delta encoding and
        predicate pushdown for range queries.

        Requires:
            - df is a pandas DataFrame
            - schema_type is a valid schema type string

        Ensures:
            - DataFrame is written to parquet at the correct path
            - User directory is created if it doesn't exist
            - Date/time/datetime columns are converted to native types
        """
        # Ensure user directory exists
        user_dir = self.get_user_dir()
        os.makedirs( user_dir, exist_ok=True )

        # Convert date/time columns before writing
        df = self._convert_dates_for_storage( df, schema_type )

        path = self.get_parquet_path( schema_type )
        if self.debug: print( f"DataFrameStorage.save_df: Writing {len( df )} rows to {path}" )

        df.to_parquet( path, index=False, coerce_timestamps="ms", allow_truncated_timestamps=True )

    def _convert_dates_for_storage( self, df, schema_type ):
        """
        Convert ISO string date/time/datetime columns to native pandas types.

        Requires:
            - df is a pandas DataFrame
            - schema_type is a valid schema type string

        Ensures:
            - Returns a copy of df with date columns as datetime64
            - Time columns are stored as strings (parquet has no native time-only type)
            - Datetime columns are converted to datetime64
            - Empty strings and None are preserved as NaT
        """
        df = df.copy()

        # Convert date columns (YYYY-MM-DD strings → datetime64)
        for col in get_date_columns( schema_type ):
            if col in df.columns:
                df[ col ] = pd.to_datetime( df[ col ], errors="coerce", format="mixed" )

        # Convert datetime columns (ISO timestamps → datetime64)
        for col in get_datetime_columns( schema_type ):
            if col in df.columns:
                df[ col ] = pd.to_datetime( df[ col ], errors="coerce", format="mixed" )

        # Time columns stay as strings — parquet has no native time-only type
        # They are stored as "HH:MM" or "HH:MM:SS" strings

        return df

    def get_all_lists_metadata( self ):
        """
        Get metadata about all lists across all schema types for this user.

        Requires:
            - self is initialized

        Ensures:
            - Returns list of dicts with schema_type, list_name, row_count
            - Returns empty list if no data exists
        """
        metadata = []

        for schema_type in VALID_SCHEMA_TYPES:
            if not self.file_exists( schema_type ):
                continue

            df = self.load_df( schema_type )
            if df.empty:
                continue

            # Group by list_name to get per-list counts
            if "list_name" in df.columns:
                for list_name, group in df.groupby( "list_name" ):
                    metadata.append( {
                        "schema_type" : schema_type,
                        "list_name"   : list_name,
                        "row_count"   : len( group ),
                    } )

        return metadata

    def get_lists_for_schema( self, schema_type ):
        """
        Get unique list names for a specific schema type.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Returns sorted list of unique list_name values
            - Returns empty list if no data exists
        """
        if not self.file_exists( schema_type ):
            return []

        df = self.load_df( schema_type )
        if df.empty or "list_name" not in df.columns:
            return []

        return sorted( df[ "list_name" ].unique().tolist() )

    def delete_schema_file( self, schema_type ):
        """
        Delete the parquet file for a schema type.

        Requires:
            - schema_type is a valid schema type string

        Ensures:
            - Parquet file is removed from disk if it exists
            - Returns True if file was deleted
            - Returns False if file did not exist
        """
        path = self.get_parquet_path( schema_type )

        if os.path.exists( path ):
            os.remove( path )
            if self.debug: print( f"DataFrameStorage.delete_schema_file: Deleted {path}" )
            return True

        return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    import tempfile

    print( "Testing storage module..." )
    passed = True

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:

            storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir, debug=True )
            print( f"  ✓ Constructor with base_path override" )

            # Test path generation
            path = storage.get_parquet_path( "todo" )
            assert path.endswith( "todo.parquet" )
            assert "test@example.com" in path
            print( f"  ✓ Path generation: {path}" )

            # Test empty df creation
            df = storage.create_empty_df( "todo" )
            assert len( df ) == 0
            assert "todo_item" in df.columns
            assert "id" in df.columns
            print( f"  ✓ Empty DataFrame creation: {list( df.columns )}" )

            # Test save/load round-trip
            df = storage.create_empty_df( "todo" )
            new_row = {
                "id"         : "abc12345",
                "list_name"  : "groceries",
                "created_at" : datetime.now().isoformat(),
                "todo_item"  : "buy milk",
                "due_date"   : "2026-03-15",
                "priority"   : "high",
                "completed"  : "no",
                "tags"       : "food",
            }
            df = pd.concat( [ df, pd.DataFrame( [ new_row ] ) ], ignore_index=True )
            storage.save_df( df, "todo" )
            assert storage.file_exists( "todo" )
            print( "  ✓ Save and file_exists" )

            loaded = storage.load_df( "todo" )
            assert len( loaded ) == 1
            assert loaded.iloc[ 0 ][ "todo_item" ] == "buy milk"
            print( "  ✓ Load round-trip" )

            # Test date conversion
            assert pd.api.types.is_datetime64_any_dtype( loaded[ "due_date" ] )
            print( "  ✓ Date column converted to datetime64" )

            # Test metadata
            meta = storage.get_all_lists_metadata()
            assert len( meta ) == 1
            assert meta[ 0 ][ "list_name" ] == "groceries"
            assert meta[ 0 ][ "row_count" ] == 1
            print( f"  ✓ Metadata: {meta}" )

            # Test lists for schema
            lists = storage.get_lists_for_schema( "todo" )
            assert "groceries" in lists
            print( f"  ✓ Lists for schema: {lists}" )

            # Test delete
            deleted = storage.delete_schema_file( "todo" )
            assert deleted is True
            assert not storage.file_exists( "todo" )
            print( "  ✓ Delete schema file" )

        print( "✓ storage module smoke test PASSED" )

    except Exception as e:
        print( f"✗ storage module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
