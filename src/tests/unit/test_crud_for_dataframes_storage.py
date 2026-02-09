#!/usr/bin/env python3
"""
Unit tests for the DataFrame CRUD storage layer.

Tests schemas, CRUDIntent XML model, DataFrameStorage, and CRUD operations.
~55 tests across 4 classes.

Run: pytest src/tests/unit/test_crud_for_dataframes_storage.py -v
"""

import json
import os
import tempfile
from datetime import datetime

import pandas as pd
import pytest

from cosa.crud_for_dataframes.schemas import (
    COMMON_COLUMNS,
    SCHEMAS,
    VALID_SCHEMA_TYPES,
    get_columns,
    get_date_columns,
    get_datetime_columns,
    get_defaults,
    get_schema,
    get_time_columns,
    validate_schema_type,
)
from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.crud_operations import (
    add_item,
    create_list,
    delete_item,
    delete_list,
    get_schema_info,
    list_lists,
    mark_done,
    query_items,
    update_item,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def tmp_storage_dir():
    """Provide a temporary directory for test storage."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield tmp_dir


@pytest.fixture
def storage( tmp_storage_dir ):
    """Provide a DataFrameStorage instance with temp directory."""
    return DataFrameStorage( user_email="test@example.com", base_path=tmp_storage_dir )


@pytest.fixture
def populated_storage( storage ):
    """Provide a storage with sample todo items."""
    add_item( storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )
    add_item( storage, "groceries", "todo", { "todo_item": "buy bread", "due_date": "2026-03-20" } )
    add_item( storage, "work", "todo", { "todo_item": "finish report", "priority": "high" } )
    return storage


# ============================================================================
# TestSchemas
# ============================================================================

class TestSchemas:
    """Tests for schema definitions and helper functions."""

    def test_all_schema_types_defined( self ):
        """Verify all expected schema types exist."""
        for st in [ "todo", "calendar", "generic" ]:
            assert st in SCHEMAS

    def test_valid_schema_types_list( self ):
        """VALID_SCHEMA_TYPES matches SCHEMAS keys."""
        assert set( VALID_SCHEMA_TYPES ) == set( SCHEMAS.keys() )

    def test_common_columns_in_all_schemas( self ):
        """All schemas include id, list_name, created_at."""
        for st in VALID_SCHEMA_TYPES:
            cols = get_columns( st )
            for common_col in [ "id", "list_name", "created_at" ]:
                assert common_col in cols, f"Missing '{common_col}' in {st}"

    def test_common_columns_dtypes( self ):
        """Common columns have correct dtypes."""
        assert COMMON_COLUMNS[ "id" ][ "dtype" ] == "str"
        assert COMMON_COLUMNS[ "list_name" ][ "dtype" ] == "str"
        assert COMMON_COLUMNS[ "created_at" ][ "dtype" ] == "datetime"

    def test_todo_columns( self ):
        """Todo schema has expected columns."""
        cols = get_columns( "todo" )
        expected = [ "id", "list_name", "created_at", "todo_item", "due_date", "priority", "completed", "tags" ]
        assert cols == expected

    def test_calendar_columns( self ):
        """Calendar schema has expected columns."""
        cols = get_columns( "calendar" )
        assert "event" in cols
        assert "start_date" in cols
        assert "start_time" in cols
        assert "location" in cols

    def test_generic_columns( self ):
        """Generic schema has name and value columns."""
        cols = get_columns( "generic" )
        assert "name" in cols
        assert "value" in cols

    def test_todo_defaults( self ):
        """Todo defaults match conventions from todo.csv."""
        defaults = get_defaults( "todo" )
        assert defaults[ "priority" ] == "normal"
        assert defaults[ "completed" ] == "no"
        assert defaults[ "tags" ] == ""

    def test_calendar_defaults( self ):
        """Calendar defaults match conventions from events.csv."""
        defaults = get_defaults( "calendar" )
        assert defaults[ "recurrent" ] == "false"
        assert defaults[ "priority_level" ] == "none"

    def test_date_columns_todo( self ):
        """Todo has due_date as date column."""
        date_cols = get_date_columns( "todo" )
        assert "due_date" in date_cols
        assert "created_at" not in date_cols  # datetime, not date

    def test_date_columns_calendar( self ):
        """Calendar has start_date and end_date as date columns."""
        date_cols = get_date_columns( "calendar" )
        assert "start_date" in date_cols
        assert "end_date" in date_cols

    def test_time_columns_calendar( self ):
        """Calendar has start_time and end_time as time columns."""
        time_cols = get_time_columns( "calendar" )
        assert "start_time" in time_cols
        assert "end_time" in time_cols

    def test_time_columns_todo_empty( self ):
        """Todo has no time columns."""
        time_cols = get_time_columns( "todo" )
        assert len( time_cols ) == 0

    def test_datetime_columns( self ):
        """All schemas have created_at as datetime column."""
        for st in VALID_SCHEMA_TYPES:
            dt_cols = get_datetime_columns( st )
            assert "created_at" in dt_cols

    def test_validate_schema_type_valid( self ):
        """Valid schema types return True."""
        assert validate_schema_type( "todo" ) is True
        assert validate_schema_type( "calendar" ) is True
        assert validate_schema_type( "generic" ) is True

    def test_validate_schema_type_invalid( self ):
        """Invalid schema types return False."""
        assert validate_schema_type( "nonexistent" ) is False
        assert validate_schema_type( "" ) is False

    def test_get_schema_invalid_raises( self ):
        """get_schema raises ValueError for unknown type."""
        with pytest.raises( ValueError, match="Unknown schema type" ):
            get_schema( "nonexistent" )


# ============================================================================
# TestCRUDIntent
# ============================================================================

class TestCRUDIntent:
    """Tests for CRUDIntent XML model."""

    def test_creation_with_required_field( self ):
        """CRUDIntent can be created with just operation."""
        intent = CRUDIntent( operation="query" )
        assert intent.operation == "query"

    def test_creation_with_all_fields( self ):
        """CRUDIntent accepts all fields."""
        intent = CRUDIntent.get_example_for_template()
        assert intent.operation == "[operation name]"
        assert intent.target_list == "[target list name]"
        assert intent.schema_type == "[schema type: todo, calendar, or generic]"

    def test_default_values( self ):
        """CRUDIntent has sensible defaults."""
        intent = CRUDIntent( operation="query" )
        assert intent.confidence == "0.0"
        assert intent.requires_confirmation == "false"
        assert intent.match_fields == "{}"
        assert intent.fields == "{}"

    def test_confidence_float_valid( self ):
        """get_confidence_float parses valid float."""
        intent = CRUDIntent( operation="query", confidence="0.85" )
        assert intent.get_confidence_float() == 0.85

    def test_confidence_float_clamped( self ):
        """get_confidence_float clamps to 0.0-1.0 range."""
        intent = CRUDIntent( operation="query", confidence="1.5" )
        assert intent.get_confidence_float() == 1.0

        intent2 = CRUDIntent( operation="query", confidence="-0.5" )
        assert intent2.get_confidence_float() == 0.0

    def test_confidence_float_invalid( self ):
        """get_confidence_float returns 0.0 for invalid input."""
        intent = CRUDIntent( operation="query", confidence="not_a_number" )
        assert intent.get_confidence_float() == 0.0

    def test_is_destructive_true( self ):
        """Destructive operations detected correctly."""
        for op in [ "delete", "delete_list", "update" ]:
            intent = CRUDIntent( operation=op )
            assert intent.is_destructive(), f"{op} should be destructive"

    def test_is_destructive_false( self ):
        """Non-destructive operations detected correctly."""
        for op in [ "add", "query", "mark_done", "create_list", "list_lists" ]:
            intent = CRUDIntent( operation=op )
            assert not intent.is_destructive(), f"{op} should not be destructive"

    def test_needs_confirmation_destructive( self ):
        """Destructive operations always need confirmation."""
        intent = CRUDIntent( operation="delete", requires_confirmation="false" )
        assert intent.needs_confirmation()

    def test_needs_confirmation_explicit( self ):
        """Explicit requires_confirmation="true" triggers confirmation."""
        intent = CRUDIntent( operation="add", requires_confirmation="true" )
        assert intent.needs_confirmation()

    def test_needs_confirmation_false( self ):
        """Non-destructive with false confirmation doesn't need confirmation."""
        intent = CRUDIntent( operation="add", requires_confirmation="false" )
        assert not intent.needs_confirmation()

    def test_get_fields_dict( self ):
        """JSON fields parsed correctly."""
        intent = CRUDIntent( operation="add", fields='{"todo_item": "buy milk", "priority": "high"}' )
        d = intent.get_fields_dict()
        assert d[ "todo_item" ] == "buy milk"
        assert d[ "priority" ] == "high"

    def test_get_fields_dict_empty( self ):
        """Empty JSON returns empty dict."""
        intent = CRUDIntent( operation="query", fields="{}" )
        assert intent.get_fields_dict() == {}

    def test_get_fields_dict_invalid_json( self ):
        """Invalid JSON returns empty dict."""
        intent = CRUDIntent( operation="query", fields="not json" )
        assert intent.get_fields_dict() == {}

    def test_get_match_dict( self ):
        """Match fields parsed correctly."""
        intent = CRUDIntent( operation="delete", match_fields='{"todo_item": "buy milk"}' )
        d = intent.get_match_dict()
        assert d[ "todo_item" ] == "buy milk"

    def test_get_filters_dict( self ):
        """Filters parsed correctly."""
        intent = CRUDIntent( operation="query", filters='{"priority": "high"}' )
        d = intent.get_filters_dict()
        assert d[ "priority" ] == "high"

    def test_get_limit_int_valid( self ):
        """Valid limit string parsed to int."""
        intent = CRUDIntent( operation="query", limit="10" )
        assert intent.get_limit_int() == 10

    def test_get_limit_int_empty( self ):
        """Empty limit returns None."""
        intent = CRUDIntent( operation="query", limit="" )
        assert intent.get_limit_int() is None

    def test_get_limit_int_negative( self ):
        """Negative limit returns None."""
        intent = CRUDIntent( operation="query", limit="-5" )
        assert intent.get_limit_int() is None

    def test_xml_round_trip( self ):
        """CRUDIntent survives XML serialization/deserialization."""
        original = CRUDIntent.get_example_for_template()
        xml_str  = original.to_xml()  # defaults to root_tag="intent"

        assert "<operation>[operation name]</operation>" in xml_str
        assert "<target_list>[target list name]</target_list>" in xml_str

        parsed = CRUDIntent.from_xml( xml_str, root_tag="intent" )
        assert parsed.operation == original.operation
        assert parsed.target_list == original.target_list
        assert parsed.schema_type == original.schema_type
        assert parsed.confidence == original.confidence
        assert parsed.raw_query == original.raw_query

    def test_xml_round_trip_with_json_fields( self ):
        """JSON-in-XML fields survive round-trip."""
        original = CRUDIntent(
            operation = "add",
            fields    = '{"todo_item": "buy milk", "priority": "high"}'
        )
        xml_str = original.to_xml( root_tag="intent" )
        parsed  = CRUDIntent.from_xml( xml_str, root_tag="intent" )

        assert parsed.get_fields_dict() == original.get_fields_dict()

    def test_example_for_template( self ):
        """Template example has generic placeholder values."""
        example = CRUDIntent.get_example_for_template()
        assert example.operation == "[operation name]"
        assert "[target list name]" in example.target_list
        assert "[original user query" in example.raw_query

    def test_valid_operations_list( self ):
        """VALID_OPERATIONS contains expected operations."""
        expected = { "add", "delete", "update", "query", "mark_done", "create_list", "delete_list", "list_lists", "get_schema_info" }
        assert set( CRUDIntent.VALID_OPERATIONS ) == expected


# ============================================================================
# TestDataFrameStorage
# ============================================================================

class TestDataFrameStorage:
    """Tests for DataFrameStorage parquet I/O."""

    def test_constructor_with_base_path( self, tmp_storage_dir ):
        """Constructor accepts base_path override."""
        storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_storage_dir )
        assert storage.user_email == "test@example.com"
        assert storage.base_path == tmp_storage_dir

    def test_constructor_empty_email_raises( self, tmp_storage_dir ):
        """Constructor raises for empty email."""
        with pytest.raises( ValueError, match="user_email is required" ):
            DataFrameStorage( user_email="", base_path=tmp_storage_dir )

    def test_constructor_whitespace_email_raises( self, tmp_storage_dir ):
        """Constructor raises for whitespace-only email."""
        with pytest.raises( ValueError, match="user_email is required" ):
            DataFrameStorage( user_email="   ", base_path=tmp_storage_dir )

    def test_get_user_dir( self, storage ):
        """User directory path includes email."""
        user_dir = storage.get_user_dir()
        assert "test@example.com" in user_dir

    def test_get_parquet_path( self, storage ):
        """Parquet path includes schema type."""
        path = storage.get_parquet_path( "todo" )
        assert path.endswith( "todo.parquet" )
        assert "test@example.com" in path

    def test_get_parquet_path_invalid_schema( self, storage ):
        """Invalid schema type raises ValueError."""
        with pytest.raises( ValueError, match="Unknown schema type" ):
            storage.get_parquet_path( "nonexistent" )

    def test_file_exists_no_file( self, storage ):
        """file_exists returns False when no file."""
        assert storage.file_exists( "todo" ) is False

    def test_create_empty_df( self, storage ):
        """create_empty_df returns DataFrame with correct columns."""
        df = storage.create_empty_df( "todo" )
        assert len( df ) == 0
        assert "todo_item" in df.columns
        assert "id" in df.columns
        assert "created_at" in df.columns

    def test_save_and_load_round_trip( self, storage ):
        """Data survives save/load cycle."""
        df = storage.create_empty_df( "todo" )
        row = {
            "id"         : "abc12345",
            "list_name"  : "test",
            "created_at" : datetime.now().isoformat(),
            "todo_item"  : "test item",
            "due_date"   : "2026-03-15",
            "priority"   : "high",
            "completed"  : "no",
            "tags"       : "",
        }
        df = pd.concat( [ df, pd.DataFrame( [ row ] ) ], ignore_index=True )
        storage.save_df( df, "todo" )

        loaded = storage.load_df( "todo" )
        assert len( loaded ) == 1
        assert loaded.iloc[ 0 ][ "todo_item" ] == "test item"

    def test_date_conversion_on_save( self, storage ):
        """Date columns converted to datetime64 after save/load."""
        df = storage.create_empty_df( "todo" )
        row = {
            "id"         : "abc12345",
            "list_name"  : "test",
            "created_at" : "2026-02-06T10:30:00",
            "todo_item"  : "test item",
            "due_date"   : "2026-03-15",
            "priority"   : "normal",
            "completed"  : "no",
            "tags"       : "",
        }
        df = pd.concat( [ df, pd.DataFrame( [ row ] ) ], ignore_index=True )
        storage.save_df( df, "todo" )

        loaded = storage.load_df( "todo" )
        assert pd.api.types.is_datetime64_any_dtype( loaded[ "due_date" ] )
        assert pd.api.types.is_datetime64_any_dtype( loaded[ "created_at" ] )

    def test_date_value_preserved( self, storage ):
        """Date values survive conversion round-trip."""
        df = storage.create_empty_df( "todo" )
        row = {
            "id"         : "abc12345",
            "list_name"  : "test",
            "created_at" : "2026-02-06T10:30:00",
            "todo_item"  : "test",
            "due_date"   : "2026-03-15",
            "priority"   : "normal",
            "completed"  : "no",
            "tags"       : "",
        }
        df = pd.concat( [ df, pd.DataFrame( [ row ] ) ], ignore_index=True )
        storage.save_df( df, "todo" )

        loaded = storage.load_df( "todo" )
        due = loaded.iloc[ 0 ][ "due_date" ]
        assert due.year == 2026
        assert due.month == 3
        assert due.day == 15

    def test_empty_date_becomes_nat( self, storage ):
        """Empty date strings become NaT (Not a Time)."""
        df = storage.create_empty_df( "todo" )
        row = {
            "id"         : "abc12345",
            "list_name"  : "test",
            "created_at" : datetime.now().isoformat(),
            "todo_item"  : "test",
            "due_date"   : "",
            "priority"   : "normal",
            "completed"  : "no",
            "tags"       : "",
        }
        df = pd.concat( [ df, pd.DataFrame( [ row ] ) ], ignore_index=True )
        storage.save_df( df, "todo" )

        loaded = storage.load_df( "todo" )
        assert pd.isna( loaded.iloc[ 0 ][ "due_date" ] )

    def test_load_nonexistent_returns_empty( self, storage ):
        """Loading nonexistent file returns empty DataFrame."""
        df = storage.load_df( "todo" )
        assert len( df ) == 0
        assert "todo_item" in df.columns

    def test_get_all_lists_metadata( self, populated_storage ):
        """Metadata lists all lists with counts."""
        meta = populated_storage.get_all_lists_metadata()
        assert len( meta ) == 2  # groceries, work

        by_name = { m[ "list_name" ]: m for m in meta }
        assert by_name[ "groceries" ][ "row_count" ] == 2
        assert by_name[ "work" ][ "row_count" ] == 1

    def test_get_lists_for_schema( self, populated_storage ):
        """get_lists_for_schema returns sorted unique names."""
        lists = populated_storage.get_lists_for_schema( "todo" )
        assert lists == [ "groceries", "work" ]

    def test_get_lists_for_schema_empty( self, storage ):
        """get_lists_for_schema returns empty for missing file."""
        lists = storage.get_lists_for_schema( "calendar" )
        assert lists == []

    def test_delete_schema_file( self, populated_storage ):
        """delete_schema_file removes parquet and returns True."""
        assert populated_storage.file_exists( "todo" )
        deleted = populated_storage.delete_schema_file( "todo" )
        assert deleted is True
        assert not populated_storage.file_exists( "todo" )

    def test_delete_schema_file_nonexistent( self, storage ):
        """delete_schema_file returns False when no file exists."""
        deleted = storage.delete_schema_file( "todo" )
        assert deleted is False


# ============================================================================
# TestCRUDOperations
# ============================================================================

class TestCRUDOperations:
    """Tests for stateless CRUD operation functions."""

    def test_create_list( self, storage ):
        """create_list returns created status."""
        result = create_list( storage, "groceries", "todo" )
        assert result[ "status" ] == "created"

    def test_create_list_already_exists( self, populated_storage ):
        """create_list returns exists status for existing list."""
        result = create_list( populated_storage, "groceries", "todo" )
        assert result[ "status" ] == "exists"

    def test_create_list_empty_name( self, storage ):
        """create_list rejects empty name."""
        result = create_list( storage, "", "todo" )
        assert result[ "status" ] == "error"

    def test_create_list_invalid_schema( self, storage ):
        """create_list rejects invalid schema type."""
        result = create_list( storage, "test", "nonexistent" )
        assert result[ "status" ] == "error"

    def test_add_item( self, storage ):
        """add_item creates item with auto-generated id."""
        result = add_item( storage, "groceries", "todo", { "todo_item": "buy milk" } )
        assert result[ "status" ] == "added"
        assert len( result[ "item_id" ] ) == 8

    def test_add_item_with_defaults( self, storage ):
        """add_item applies schema defaults for missing fields."""
        result = add_item( storage, "groceries", "todo", { "todo_item": "buy milk" } )
        items  = query_items( storage, "todo", list_name="groceries" )
        item   = items[ "items" ][ 0 ]
        assert item[ "priority" ] == "normal"
        assert item[ "completed" ] == "no"

    def test_add_item_with_date( self, storage ):
        """add_item accepts ISO date strings."""
        result = add_item( storage, "groceries", "todo", {
            "todo_item" : "buy milk",
            "due_date"  : "2026-03-15"
        } )
        assert result[ "status" ] == "added"

        # Verify date stored correctly
        df = storage.load_df( "todo" )
        due = df.iloc[ 0 ][ "due_date" ]
        assert due.year == 2026
        assert due.month == 3
        assert due.day == 15

    def test_add_item_empty_list_name( self, storage ):
        """add_item rejects empty list name."""
        result = add_item( storage, "", "todo", { "todo_item": "test" } )
        assert result[ "status" ] == "error"

    def test_delete_item_by_id( self, populated_storage ):
        """delete_item removes item by id."""
        items = query_items( populated_storage, "todo", list_name="groceries" )
        item_id = items[ "items" ][ 0 ][ "id" ]

        result = delete_item( populated_storage, "todo", item_id=item_id )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1

    def test_delete_item_by_match_fields( self, populated_storage ):
        """delete_item removes item by field matching."""
        result = delete_item( populated_storage, "todo", match_fields={ "todo_item": "buy milk" } )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1

    def test_delete_item_not_found( self, populated_storage ):
        """delete_item returns not_found for missing item."""
        result = delete_item( populated_storage, "todo", item_id="nonexist" )
        assert result[ "status" ] == "not_found"

    def test_delete_item_no_criteria( self, storage ):
        """delete_item rejects call with no id or match_fields."""
        result = delete_item( storage, "todo" )
        assert result[ "status" ] == "error"

    def test_update_item_by_id( self, populated_storage ):
        """update_item modifies fields by id."""
        items   = query_items( populated_storage, "todo", list_name="groceries" )
        item_id = items[ "items" ][ 0 ][ "id" ]

        result = update_item( populated_storage, "todo", { "priority": "low" }, item_id=item_id )
        assert result[ "status" ] == "updated"

        updated = query_items( populated_storage, "todo", filters={ "id": item_id } )
        assert updated[ "items" ][ 0 ][ "priority" ] == "low"

    def test_update_item_no_updates( self, storage ):
        """update_item rejects empty updates."""
        result = update_item( storage, "todo", {}, item_id="abc" )
        assert result[ "status" ] == "error"

    def test_update_item_protects_id( self, populated_storage ):
        """update_item does not allow changing id or created_at."""
        items = query_items( populated_storage, "todo", list_name="groceries" )
        item_id = items[ "items" ][ 0 ][ "id" ]

        update_item( populated_storage, "todo", { "id": "hacked", "priority": "low" }, item_id=item_id )
        updated = query_items( populated_storage, "todo", filters={ "id": item_id } )
        # id should not have changed
        assert updated[ "items" ][ 0 ][ "id" ] == item_id

    def test_mark_done( self, populated_storage ):
        """mark_done sets completed='yes'."""
        items = query_items( populated_storage, "todo", list_name="groceries" )
        item_id = items[ "items" ][ 0 ][ "id" ]

        result = mark_done( populated_storage, "todo", item_id=item_id )
        assert result[ "status" ] == "updated"

        updated = query_items( populated_storage, "todo", filters={ "id": item_id } )
        assert updated[ "items" ][ 0 ][ "completed" ] == "yes"

    def test_query_items_all( self, populated_storage ):
        """query_items returns all items for schema."""
        result = query_items( populated_storage, "todo" )
        assert result[ "total_count" ] == 3

    def test_query_items_by_list( self, populated_storage ):
        """query_items filters by list_name."""
        result = query_items( populated_storage, "todo", list_name="groceries" )
        assert result[ "total_count" ] == 2

    def test_query_items_with_filter( self, populated_storage ):
        """query_items filters by field values."""
        result = query_items( populated_storage, "todo", filters={ "priority": "high" } )
        assert result[ "total_count" ] == 2  # buy milk + finish report

    def test_query_items_with_limit( self, populated_storage ):
        """query_items respects limit parameter."""
        result = query_items( populated_storage, "todo", limit=1 )
        assert len( result[ "items" ] ) == 1
        assert result[ "total_count" ] == 3  # total_count is pre-limit

    def test_query_items_with_sort( self, populated_storage ):
        """query_items sorts results."""
        result = query_items( populated_storage, "todo", list_name="groceries", sort_by="todo_item" )
        items = result[ "items" ]
        assert items[ 0 ][ "todo_item" ] == "buy bread"
        assert items[ 1 ][ "todo_item" ] == "buy milk"

    def test_query_items_empty( self, storage ):
        """query_items returns empty for no data."""
        result = query_items( storage, "todo" )
        assert result[ "total_count" ] == 0
        assert result[ "items" ] == []

    def test_query_items_invalid_schema( self, storage ):
        """query_items rejects invalid schema type."""
        result = query_items( storage, "nonexistent" )
        assert result[ "status" ] == "error"

    def test_delete_list( self, populated_storage ):
        """delete_list removes all items for a list."""
        result = delete_list( populated_storage, "groceries", "todo" )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 2

        remaining = query_items( populated_storage, "todo" )
        assert remaining[ "total_count" ] == 1  # only work list

    def test_delete_list_not_found( self, storage ):
        """delete_list returns not_found for empty storage."""
        result = delete_list( storage, "nonexistent", "todo" )
        assert result[ "status" ] == "not_found"

    def test_list_lists_all( self, populated_storage ):
        """list_lists returns all lists across schemas."""
        result = list_lists( populated_storage )
        assert result[ "total_lists" ] == 2
        names = [ l[ "list_name" ] for l in result[ "lists" ] ]
        assert "groceries" in names
        assert "work" in names

    def test_list_lists_by_schema( self, populated_storage ):
        """list_lists filters by schema type."""
        result = list_lists( populated_storage, schema_type="todo" )
        assert result[ "total_lists" ] == 2

        result = list_lists( populated_storage, schema_type="calendar" )
        assert result[ "total_lists" ] == 0

    def test_get_schema_info_todo( self ):
        """get_schema_info returns column details for todo."""
        result = get_schema_info( "todo" )
        assert result[ "status" ] == "ok"
        assert result[ "total_columns" ] == 8  # id + list_name + created_at + 5 todo columns

        col_names = [ c[ "name" ] for c in result[ "columns" ] ]
        assert "todo_item" in col_names
        assert "due_date" in col_names

    def test_get_schema_info_invalid( self ):
        """get_schema_info rejects invalid schema type."""
        result = get_schema_info( "nonexistent" )
        assert result[ "status" ] == "error"

    def test_full_crud_cycle( self, storage ):
        """Full create → add → query → update → mark_done → delete cycle."""
        # Create list
        create_list( storage, "test_list", "todo" )

        # Add items
        r1 = add_item( storage, "test_list", "todo", { "todo_item": "task 1", "priority": "high" } )
        r2 = add_item( storage, "test_list", "todo", { "todo_item": "task 2", "priority": "low" } )

        # Query all
        result = query_items( storage, "todo", list_name="test_list" )
        assert result[ "total_count" ] == 2

        # Update
        update_item( storage, "todo", { "priority": "normal" }, item_id=r1[ "item_id" ] )

        # Mark done
        mark_done( storage, "todo", item_id=r1[ "item_id" ] )

        # Verify
        done = query_items( storage, "todo", filters={ "id": r1[ "item_id" ] } )
        assert done[ "items" ][ 0 ][ "completed" ] == "yes"
        assert done[ "items" ][ 0 ][ "priority" ] == "normal"

        # Delete one
        delete_item( storage, "todo", item_id=r2[ "item_id" ] )
        remaining = query_items( storage, "todo", list_name="test_list" )
        assert remaining[ "total_count" ] == 1

        # Delete list
        delete_list( storage, "test_list", "todo" )
        final = query_items( storage, "todo", list_name="test_list" )
        assert final[ "total_count" ] == 0


# ============================================================================
# Calendar Schema Tests
# ============================================================================

class TestCalendarOperations:
    """Tests for calendar-specific CRUD operations."""

    def test_add_calendar_event( self, storage ):
        """Add a calendar event with date and time fields."""
        result = add_item( storage, "personal", "calendar", {
            "event"      : "Dentist appointment",
            "start_date" : "2026-03-15",
            "start_time" : "14:30",
            "end_time"   : "15:30",
            "event_type" : "appointment",
            "location"   : "Downtown Dental",
        } )
        assert result[ "status" ] == "added"

        # Verify
        items = query_items( storage, "calendar", list_name="personal" )
        assert items[ "total_count" ] == 1
        item = items[ "items" ][ 0 ]
        assert item[ "event" ] == "Dentist appointment"
        assert item[ "location" ] == "Downtown Dental"

    def test_calendar_date_conversion( self, storage ):
        """Calendar date columns survive storage round-trip as datetime64."""
        add_item( storage, "personal", "calendar", {
            "event"      : "Meeting",
            "start_date" : "2026-03-15",
            "end_date"   : "2026-03-15",
        } )

        df = storage.load_df( "calendar" )
        assert pd.api.types.is_datetime64_any_dtype( df[ "start_date" ] )
        assert pd.api.types.is_datetime64_any_dtype( df[ "end_date" ] )

        start = df.iloc[ 0 ][ "start_date" ]
        assert start.year == 2026
        assert start.month == 3
        assert start.day == 15

    def test_calendar_time_as_string( self, storage ):
        """Calendar time columns are stored as strings."""
        add_item( storage, "personal", "calendar", {
            "event"      : "Meeting",
            "start_time" : "14:30",
            "end_time"   : "15:30",
        } )

        df = storage.load_df( "calendar" )
        # Time columns stay as strings (parquet has no native time-only type)
        assert df.iloc[ 0 ][ "start_time" ] == "14:30"
        assert df.iloc[ 0 ][ "end_time" ] == "15:30"


# ============================================================================
# TestMatchFieldsValidation — Critical delete/update safety guard
# ============================================================================

class TestMatchFieldsValidation:
    """Tests for match_fields validation in delete_item and update_item.

    Regression tests for the bug where unknown field names in match_fields
    silently produced an ALL TRUE mask, deleting/updating every row.
    """

    def test_delete_with_invalid_field_returns_error( self, populated_storage ):
        """delete_item with unknown field name returns error, zero rows deleted."""
        result = delete_item( populated_storage, "todo", match_fields={ "name": "buy milk" } )
        assert result[ "status" ] == "error"
        assert "Unknown field(s)" in result[ "message" ]
        assert "name" in result[ "message" ]

        # Verify ALL rows are still present (nothing deleted)
        remaining = query_items( populated_storage, "todo" )
        assert remaining[ "total_count" ] == 3

    def test_delete_with_valid_field_deletes_only_match( self, populated_storage ):
        """delete_item with correct field name deletes only the matching row."""
        result = delete_item( populated_storage, "todo", match_fields={ "todo_item": "buy milk" } )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1

        remaining = query_items( populated_storage, "todo" )
        assert remaining[ "total_count" ] == 2
        items = [ i[ "todo_item" ] for i in remaining[ "items" ] ]
        assert "buy milk" not in items
        assert "buy bread" in items

    def test_update_with_invalid_field_returns_error( self, populated_storage ):
        """update_item with unknown match field returns error, zero rows updated."""
        result = update_item(
            populated_storage, "todo",
            field_updates={ "priority": "low" },
            match_fields={ "name": "buy milk" }
        )
        assert result[ "status" ] == "error"
        assert "Unknown field(s)" in result[ "message" ]

        # Verify nothing was changed
        items = query_items( populated_storage, "todo", filters={ "todo_item": "buy milk" } )
        assert items[ "items" ][ 0 ][ "priority" ] == "high"

    def test_delete_preserves_data_on_field_mismatch( self, populated_storage ):
        """Original DataFrame is UNCHANGED after error return from invalid match_fields."""
        # Snapshot row count before
        before = query_items( populated_storage, "todo" )
        before_count = before[ "total_count" ]

        # Attempt delete with wrong field
        result = delete_item( populated_storage, "todo", match_fields={ "item": "buy milk" } )
        assert result[ "status" ] == "error"

        # Verify data is identical
        after = query_items( populated_storage, "todo" )
        assert after[ "total_count" ] == before_count
        assert [ i[ "todo_item" ] for i in after[ "items" ] ] == [ i[ "todo_item" ] for i in before[ "items" ] ]

    def test_delete_by_id_still_works( self, populated_storage ):
        """delete_item by item_id path is unaffected by validation guard."""
        items   = query_items( populated_storage, "todo", list_name="groceries" )
        item_id = items[ "items" ][ 0 ][ "id" ]

        result = delete_item( populated_storage, "todo", item_id=item_id )
        assert result[ "status" ] == "deleted"
        assert result[ "deleted_count" ] == 1

    def test_mark_done_with_invalid_field_returns_error( self, populated_storage ):
        """mark_done (via update_item) with unknown match field returns error."""
        result = mark_done( populated_storage, "todo", match_fields={ "name": "buy milk" } )
        assert result[ "status" ] == "error"
        assert "Unknown field(s)" in result[ "message" ]

    def test_error_message_lists_valid_fields( self, populated_storage ):
        """Error message includes valid field names for user guidance."""
        result = delete_item( populated_storage, "todo", match_fields={ "wrong_field": "value" } )
        assert result[ "status" ] == "error"
        assert "todo_item" in result[ "message" ]
        assert "priority" in result[ "message" ]
