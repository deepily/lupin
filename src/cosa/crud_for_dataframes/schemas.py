#!/usr/bin/env python3
"""
Schema definitions for DataFrame CRUD operations.

Defines column names, types, and defaults for todo, calendar, and generic
DataFrames. Column names are aligned with existing CSV conventions in
src/conf/long-term-memory/ (events.csv, todo.csv).

Each column has an explicit dtype ('str', 'date', 'time', 'datetime') so
the storage layer knows exactly which columns to convert — no pandas
inference needed.
"""

# Common columns present in ALL schemas
COMMON_COLUMNS = {
    "id"         : { "dtype": "str" },
    "list_name"  : { "dtype": "str" },
    "created_at" : { "dtype": "datetime" },
}

# Infrastructure columns that must not be used in match_fields
INFRASTRUCTURE_COLS = frozenset( { "id", "list_name", "created_at" } )

# Dedup keys per schema — columns that define "same item" for duplicate detection
DEDUP_KEYS = {
    "todo"     : [ "todo_item" ],
    "calendar" : [ "event", "start_date" ],
    "generic"  : [ "name" ],
}

# Schema definitions keyed by schema type name
SCHEMAS = {

    "todo": {
        "columns": {
            **COMMON_COLUMNS,
            "todo_item"  : { "dtype": "str" },
            "due_date"   : { "dtype": "date" },
            "priority"   : { "dtype": "str" },
            "completed"  : { "dtype": "str" },
            "tags"       : { "dtype": "str" },
        },
        "defaults": {
            "priority"  : "normal",
            "completed" : "no",
            "tags"      : "",
            "due_date"  : "",
        },
    },

    "calendar": {
        "columns": {
            **COMMON_COLUMNS,
            "event"               : { "dtype": "str" },
            "start_date"          : { "dtype": "date" },
            "end_date"            : { "dtype": "date" },
            "start_time"          : { "dtype": "time" },
            "end_time"            : { "dtype": "time" },
            "event_type"          : { "dtype": "str" },
            "recurrent"           : { "dtype": "str" },
            "recurrence_interval" : { "dtype": "str" },
            "priority_level"      : { "dtype": "str" },
            "name"                : { "dtype": "str" },
            "relationship"        : { "dtype": "str" },
            "location"            : { "dtype": "str" },
        },
        "defaults": {
            "start_date"          : "",
            "end_date"            : "",
            "start_time"          : "",
            "end_time"            : "",
            "event_type"          : "",
            "recurrent"           : "false",
            "recurrence_interval" : "",
            "priority_level"      : "none",
            "name"                : "",
            "relationship"        : "",
            "location"            : "",
        },
    },

    "generic": {
        "columns": {
            **COMMON_COLUMNS,
            "name"  : { "dtype": "str" },
            "value" : { "dtype": "str" },
        },
        "defaults": {
            "name"  : "",
            "value" : "",
        },
    },
}

# Valid schema type names
VALID_SCHEMA_TYPES = list( SCHEMAS.keys() )


def get_schema( schema_type ):
    """
    Get the full schema definition for a given type.

    Requires:
        - schema_type is a string matching a key in SCHEMAS

    Ensures:
        - Returns the schema dict with 'columns' and 'defaults' keys

    Raises:
        - ValueError if schema_type is not recognized
    """
    if schema_type not in SCHEMAS:
        raise ValueError( f"Unknown schema type '{schema_type}'. Valid types: {VALID_SCHEMA_TYPES}" )

    return SCHEMAS[ schema_type ]


def get_columns( schema_type ):
    """
    Get ordered list of column names for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns list of column name strings in definition order
    """
    return list( get_schema( schema_type )[ "columns" ].keys() )


def get_defaults( schema_type ):
    """
    Get default values dict for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns dict mapping column names to their default values
        - Only includes columns that have defaults
    """
    return dict( get_schema( schema_type )[ "defaults" ] )


def get_date_columns( schema_type ):
    """
    Get column names with dtype 'date' for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns list of column names whose dtype is 'date'
    """
    schema = get_schema( schema_type )
    return [ col for col, meta in schema[ "columns" ].items() if meta[ "dtype" ] == "date" ]


def get_time_columns( schema_type ):
    """
    Get column names with dtype 'time' for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns list of column names whose dtype is 'time'
    """
    schema = get_schema( schema_type )
    return [ col for col, meta in schema[ "columns" ].items() if meta[ "dtype" ] == "time" ]


def get_datetime_columns( schema_type ):
    """
    Get column names with dtype 'datetime' for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns list of column names whose dtype is 'datetime'
    """
    schema = get_schema( schema_type )
    return [ col for col, meta in schema[ "columns" ].items() if meta[ "dtype" ] == "datetime" ]


def validate_schema_type( schema_type ):
    """
    Validate that a schema type string is recognized.

    Requires:
        - schema_type is a string

    Ensures:
        - Returns True if schema_type is valid
        - Returns False otherwise
    """
    return schema_type in SCHEMAS


def get_dedup_keys( schema_type ):
    """
    Get the dedup key column names for a schema type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns list of column name strings that define "same item"
        - Returns empty list if no dedup keys defined for schema_type
    """
    return list( DEDUP_KEYS.get( schema_type, [] ) )


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing schemas module..." )
    passed = True

    try:
        # Test all schema types exist
        for st in [ "todo", "calendar", "generic" ]:
            schema = get_schema( st )
            assert "columns" in schema, f"Missing 'columns' in {st}"
            assert "defaults" in schema, f"Missing 'defaults' in {st}"
            print( f"  ✓ Schema '{st}' has columns and defaults" )

        # Test common columns present in all schemas
        for st in VALID_SCHEMA_TYPES:
            cols = get_columns( st )
            for common_col in [ "id", "list_name", "created_at" ]:
                assert common_col in cols, f"Common column '{common_col}' missing from {st}"
            print( f"  ✓ Schema '{st}' has all common columns" )

        # Test date column helpers
        todo_dates = get_date_columns( "todo" )
        assert "due_date" in todo_dates, "todo should have due_date as date column"
        print( f"  ✓ Todo date columns: {todo_dates}" )

        cal_dates = get_date_columns( "calendar" )
        assert "start_date" in cal_dates, "calendar should have start_date as date column"
        print( f"  ✓ Calendar date columns: {cal_dates}" )

        cal_times = get_time_columns( "calendar" )
        assert "start_time" in cal_times, "calendar should have start_time as time column"
        print( f"  ✓ Calendar time columns: {cal_times}" )

        dt_cols = get_datetime_columns( "todo" )
        assert "created_at" in dt_cols, "todo should have created_at as datetime column"
        print( f"  ✓ Todo datetime columns: {dt_cols}" )

        # Test validation
        assert validate_schema_type( "todo" ) is True
        assert validate_schema_type( "nonexistent" ) is False
        print( "  ✓ Schema validation works" )

        # Test invalid schema raises
        try:
            get_schema( "nonexistent" )
            passed = False
            print( "  ✗ Should have raised ValueError" )
        except ValueError:
            print( "  ✓ Invalid schema type raises ValueError" )

        # Test defaults
        defaults = get_defaults( "todo" )
        assert defaults[ "priority" ] == "normal"
        assert defaults[ "completed" ] == "no"
        print( f"  ✓ Todo defaults: priority={defaults['priority']}, completed={defaults['completed']}" )

        print( "✓ schemas module smoke test PASSED" )

    except Exception as e:
        print( f"✗ schemas module smoke test FAILED: {e}" )
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
