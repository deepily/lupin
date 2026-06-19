"""
Unit tests for cosa.crud_for_dataframes.schemas.

schemas.py is a pure, dependency-free module defining column/dtype/default
metadata for the todo, calendar, and generic DataFrame schemas plus a set of
accessor helpers. These tests exercise every accessor across all three schema
types and both the happy path and the ValueError-raising unknown-type path.

Assertions harvested + extended from the module's quick_smoke_test() block,
which is marked for deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import unittest

from cosa.crud_for_dataframes import schemas
from cosa.crud_for_dataframes.schemas import (
    get_schema,
    get_columns,
    get_defaults,
    get_date_columns,
    get_time_columns,
    get_datetime_columns,
    validate_schema_type,
    get_dedup_keys,
    SCHEMAS,
    VALID_SCHEMA_TYPES,
    INFRASTRUCTURE_COLS,
    DEDUP_KEYS,
)


class TestSchemaConstants( unittest.TestCase ):
    """
    Module-level constant invariants.

    Ensures:
        - The three schema types are registered and self-consistent
        - Infrastructure columns are present in every schema
    """

    def test_valid_schema_types_matches_schemas_keys( self ):
        """Ensures VALID_SCHEMA_TYPES is exactly the SCHEMAS keys, all three present."""
        self.assertEqual( set( VALID_SCHEMA_TYPES ), set( SCHEMAS.keys() ) )
        self.assertEqual( set( VALID_SCHEMA_TYPES ), { "todo", "calendar", "generic" } )

    def test_every_schema_has_columns_and_defaults( self ):
        """Ensures each registered schema exposes both 'columns' and 'defaults'."""
        for st in VALID_SCHEMA_TYPES:
            self.assertIn( "columns", SCHEMAS[ st ] )
            self.assertIn( "defaults", SCHEMAS[ st ] )

    def test_common_columns_present_in_all_schemas( self ):
        """Ensures id / list_name / created_at appear in every schema's columns."""
        for st in VALID_SCHEMA_TYPES:
            cols = get_columns( st )
            for common in ( "id", "list_name", "created_at" ):
                self.assertIn( common, cols )

    def test_infrastructure_cols_is_frozenset( self ):
        """Ensures INFRASTRUCTURE_COLS holds exactly the three common columns."""
        self.assertEqual( INFRASTRUCTURE_COLS, frozenset( { "id", "list_name", "created_at" } ) )


class TestGetSchema( unittest.TestCase ):
    """
    get_schema — valid lookup + unknown-type raise.

    Ensures:
        - Returns the live schema dict for valid types
        - Raises ValueError naming the valid types for unknown input
    """

    def test_returns_schema_dict_for_each_valid_type( self ):
        """Ensures get_schema returns the same object stored in SCHEMAS."""
        for st in VALID_SCHEMA_TYPES:
            self.assertIs( get_schema( st ), SCHEMAS[ st ] )

    def test_unknown_type_raises_value_error( self ):
        """Ensures get_schema raises ValueError and lists valid types in the message."""
        with self.assertRaises( ValueError ) as ctx:
            get_schema( "nonexistent" )
        self.assertIn( "nonexistent", str( ctx.exception ) )
        self.assertIn( "todo", str( ctx.exception ) )


class TestColumnAndDefaultAccessors( unittest.TestCase ):
    """
    get_columns / get_defaults — order + content + copy semantics.
    """

    def test_get_columns_returns_definition_order( self ):
        """Ensures get_columns preserves declaration order, common cols first."""
        cols = get_columns( "todo" )
        self.assertEqual( cols[ :3 ], [ "id", "list_name", "created_at" ] )
        self.assertIn( "todo_item", cols )

    def test_get_defaults_returns_copy_not_alias( self ):
        """Ensures get_defaults returns a fresh dict (mutation does not leak back)."""
        defaults = get_defaults( "todo" )
        self.assertEqual( defaults[ "priority" ], "normal" )
        self.assertEqual( defaults[ "completed" ], "no" )
        defaults[ "priority" ] = "MUTATED"
        self.assertEqual( SCHEMAS[ "todo" ][ "defaults" ][ "priority" ], "normal" )


class TestDtypeColumnAccessors( unittest.TestCase ):
    """
    get_date_columns / get_time_columns / get_datetime_columns by dtype.
    """

    def test_date_columns( self ):
        """Ensures date-dtype columns are reported per schema."""
        self.assertIn( "due_date", get_date_columns( "todo" ) )
        self.assertIn( "start_date", get_date_columns( "calendar" ) )
        self.assertIn( "end_date", get_date_columns( "calendar" ) )

    def test_time_columns( self ):
        """Ensures time-dtype columns are reported for calendar and empty for todo."""
        self.assertIn( "start_time", get_time_columns( "calendar" ) )
        self.assertIn( "end_time", get_time_columns( "calendar" ) )
        self.assertEqual( get_time_columns( "todo" ), [] )

    def test_datetime_columns( self ):
        """Ensures created_at is the datetime-dtype column in every schema."""
        for st in VALID_SCHEMA_TYPES:
            self.assertEqual( get_datetime_columns( st ), [ "created_at" ] )


class TestValidateSchemaType( unittest.TestCase ):
    """
    validate_schema_type — boolean membership test.
    """

    def test_valid_returns_true( self ):
        """Ensures known schema types return True."""
        for st in VALID_SCHEMA_TYPES:
            self.assertTrue( validate_schema_type( st ) )

    def test_invalid_returns_false( self ):
        """Ensures an unknown type returns False (no raise)."""
        self.assertFalse( validate_schema_type( "nonexistent" ) )


class TestGetDedupKeys( unittest.TestCase ):
    """
    get_dedup_keys — known schema keys + unknown-type empty fallback.
    """

    def test_known_schema_dedup_keys( self ):
        """Ensures dedup keys match DEDUP_KEYS for each registered schema."""
        self.assertEqual( get_dedup_keys( "todo" ), [ "todo_item" ] )
        self.assertEqual( get_dedup_keys( "calendar" ), [ "event", "start_date" ] )
        self.assertEqual( get_dedup_keys( "generic" ), [ "name" ] )

    def test_unknown_schema_returns_empty_list( self ):
        """Ensures an unregistered schema type yields an empty dedup-key list."""
        self.assertEqual( get_dedup_keys( "nonexistent" ), [] )

    def test_returns_copy_not_alias( self ):
        """Ensures the returned list is a copy (mutation does not corrupt DEDUP_KEYS)."""
        keys = get_dedup_keys( "todo" )
        keys.append( "leaked" )
        self.assertEqual( DEDUP_KEYS[ "todo" ], [ "todo_item" ] )


if __name__ == "__main__":
    unittest.main()
