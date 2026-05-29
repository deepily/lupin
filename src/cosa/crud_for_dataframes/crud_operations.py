#!/usr/bin/env python3
"""
Stateless CRUD functions operating on DataFrameStorage.

All functions take a DataFrameStorage instance and operate on the
underlying parquet files. Date-aware: accepts ISO string input and
lets the storage layer handle conversion.

Functions:
    create_list, delete_list, list_lists
    add_item, delete_item, update_item, mark_done
    query_items, get_schema_info
"""

import uuid
from datetime import datetime

import pandas as pd

from cosa.crud_for_dataframes.schemas import (
    get_columns,
    get_dedup_keys,
    get_defaults,
    get_schema,
    validate_schema_type,
    INFRASTRUCTURE_COLS,
    VALID_SCHEMA_TYPES,
)
from cosa.crud_for_dataframes.storage import DataFrameStorage


def _generate_id():
    """
    Generate a short UUID8 identifier.

    Ensures:
        - Returns 8-character hex string
    """
    return uuid.uuid4().hex[ :8 ]


def _validate_match_fields( match_fields, df_columns, schema_type ):
    """
    Validate that all match_fields keys exist in the DataFrame columns.

    Requires:
        - match_fields is a non-empty dict
        - df_columns is a pandas Index or list of column names
        - schema_type is a string for error messages

    Ensures:
        - Returns None if all keys are valid
        - Returns error dict if any key is invalid
    """
    # Reject infrastructure columns — they pass the "exists in df" check but must not be used
    infra_keys = [ k for k in match_fields if k in INFRASTRUCTURE_COLS ]
    if infra_keys:
        data_fields = sorted( [ c for c in df_columns if c not in INFRASTRUCTURE_COLS ] )
        return {
            "status"  : "error",
            "message" : f"Cannot match by infrastructure column(s) {infra_keys}. Use data fields: {data_fields}"
        }

    invalid_keys = [ k for k in match_fields if k not in df_columns ]
    if invalid_keys:
        valid_keys = sorted( [ c for c in df_columns if c not in INFRASTRUCTURE_COLS ] )
        return {
            "status"  : "error",
            "message" : f"Unknown field(s) {invalid_keys} for schema '{schema_type}'. Valid fields: {valid_keys}"
        }
    return None


def create_list( storage, list_name, schema_type="todo" ):
    """
    Create a new named list (or verify it can be created).

    Lists are implicit — they exist when items have that list_name.
    This function validates inputs and ensures the schema file exists.

    Requires:
        - storage is a DataFrameStorage instance
        - list_name is a non-empty string
        - schema_type is a valid schema type

    Ensures:
        - Returns dict with status and message
        - Schema file is initialized (empty) if it doesn't exist
    """
    if not list_name or not list_name.strip():
        return { "status": "error", "message": "list_name is required" }

    if not validate_schema_type( schema_type ):
        return { "status": "error", "message": f"Unknown schema type '{schema_type}'. Valid: {VALID_SCHEMA_TYPES}" }

    list_name = list_name.strip()

    # Check if list already has items
    df = storage.load_df( schema_type )
    existing_lists = df[ "list_name" ].unique().tolist() if not df.empty and "list_name" in df.columns else []

    if list_name in existing_lists:
        return { "status": "exists", "message": f"List '{list_name}' already exists with {len( df[ df['list_name'] == list_name ] )} items" }

    # Ensure the schema file exists (even if empty)
    if not storage.file_exists( schema_type ):
        empty_df = storage.create_empty_df( schema_type )
        storage.save_df( empty_df, schema_type )

    return { "status": "created", "message": f"List '{list_name}' ready (schema: {schema_type})" }


def delete_list( storage, list_name, schema_type="todo" ):
    """
    Delete all items in a named list.

    Requires:
        - storage is a DataFrameStorage instance
        - list_name is a non-empty string
        - schema_type is a valid schema type

    Ensures:
        - All rows with matching list_name are removed
        - Returns dict with status, message, and deleted_count
    """
    if not list_name or not list_name.strip():
        return { "status": "error", "message": "list_name is required" }

    list_name = list_name.strip()
    df = storage.load_df( schema_type )

    if df.empty:
        return { "status": "not_found", "message": f"No data exists for schema '{schema_type}'" }

    mask          = df[ "list_name" ] == list_name
    deleted_count = mask.sum()

    if deleted_count == 0:
        return { "status": "not_found", "message": f"List '{list_name}' not found" }

    df = df[ ~mask ].reset_index( drop=True )
    storage.save_df( df, schema_type )

    return { "status": "deleted", "message": f"Deleted list '{list_name}' ({deleted_count} items)", "deleted_count": int( deleted_count ) }


def list_lists( storage, schema_type=None ):
    """
    List all named lists, optionally filtered by schema type.

    Requires:
        - storage is a DataFrameStorage instance
        - schema_type is None (all) or a valid schema type string

    Ensures:
        - Returns dict with status and lists metadata
    """
    if schema_type is not None and not validate_schema_type( schema_type ):
        return { "status": "error", "message": f"Unknown schema type '{schema_type}'" }

    if schema_type is not None:
        lists = storage.get_lists_for_schema( schema_type )
        metadata = []
        if lists:
            df = storage.load_df( schema_type )
            for ln in lists:
                count = len( df[ df[ "list_name" ] == ln ] )
                metadata.append( { "schema_type": schema_type, "list_name": ln, "row_count": count } )
    else:
        metadata = storage.get_all_lists_metadata()

    return { "status": "ok", "lists": metadata, "total_lists": len( metadata ) }


def add_item( storage, list_name, schema_type, field_values ):
    """
    Add a new item to a list.

    Accepts ISO string input for date fields — the storage layer handles
    conversion to native datetime types when saving.

    Requires:
        - storage is a DataFrameStorage instance
        - list_name is a non-empty string
        - schema_type is a valid schema type
        - field_values is a dict of column_name: value pairs

    Ensures:
        - New row is added with auto-generated id and created_at
        - Missing fields get defaults from schema
        - Returns dict with status, message, and the new item's id
    """
    if not list_name or not list_name.strip():
        return { "status": "error", "message": "list_name is required" }

    if not validate_schema_type( schema_type ):
        return { "status": "error", "message": f"Unknown schema type '{schema_type}'" }

    list_name = list_name.strip()

    # Build row from defaults + provided values
    defaults = get_defaults( schema_type )
    columns  = get_columns( schema_type )
    item_id  = _generate_id()

    row = { col: "" for col in columns }
    row.update( defaults )
    row.update( field_values )

    # Set auto-generated fields
    row[ "id" ]         = item_id
    row[ "list_name" ]  = list_name
    row[ "created_at" ] = datetime.now().isoformat()

    # Load existing DF once — reused for dedup check and concat
    df = storage.load_df( schema_type )

    # Dedup guard: reject if identical business data already exists in same list
    dedup_keys = get_dedup_keys( schema_type )
    if dedup_keys and not df.empty:
        same_list = df[ df[ "list_name" ] == list_name ]
        if not same_list.empty:
            mask = pd.Series( True, index=same_list.index )
            for key in dedup_keys:
                if key in same_list.columns and key in row:
                    mask = mask & ( same_list[ key ].astype( str ) == str( row[ key ] ) )
            if mask.any():
                return { "status": "duplicate", "message": f"Item already exists in '{list_name}'" }

    # Append and save
    df = pd.concat( [ df, pd.DataFrame( [ row ] ) ], ignore_index=True )
    storage.save_df( df, schema_type )

    return { "status": "added", "message": f"Added item to '{list_name}'", "item_id": item_id }


def delete_item( storage, schema_type, item_id=None, match_fields=None ):
    """
    Delete an item by id or by matching field values.

    Requires:
        - storage is a DataFrameStorage instance
        - schema_type is a valid schema type
        - At least one of item_id or match_fields must be provided

    Ensures:
        - Matching rows are removed
        - Returns dict with status, message, and deleted_count
    """
    if not item_id and not match_fields:
        return { "status": "error", "message": "Provide item_id or match_fields" }

    df = storage.load_df( schema_type )
    if df.empty:
        return { "status": "not_found", "message": "No data exists" }

    if item_id:
        mask = df[ "id" ] == item_id
    else:
        # Validate all match_fields exist before building mask
        validation_error = _validate_match_fields( match_fields, df.columns, schema_type )
        if validation_error:
            return validation_error

        mask = pd.Series( True, index=df.index )
        for field, value in match_fields.items():
            if field in df.columns:
                mask = mask & ( df[ field ].astype( str ) == str( value ) )

    deleted_count = mask.sum()
    if deleted_count == 0:
        return { "status": "not_found", "message": "No matching items found" }

    # Multi-delete guard: only applies to match_fields path (not item_id)
    if match_fields and deleted_count > 1:
        preview = df[ mask ][ list( match_fields.keys() ) ].head( 5 ).to_dict( orient="records" )
        return {
            "status"  : "error",
            "message" : f"Multiple items ({deleted_count}) match. Be more specific or use item_id.",
            "matched_preview" : preview,
        }

    df = df[ ~mask ].reset_index( drop=True )
    storage.save_df( df, schema_type )

    return { "status": "deleted", "message": f"Deleted {deleted_count} item(s)", "deleted_count": int( deleted_count ) }


def update_item( storage, schema_type, field_updates, item_id=None, match_fields=None ):
    """
    Update an item's fields by id or by matching field values.

    Requires:
        - storage is a DataFrameStorage instance
        - schema_type is a valid schema type
        - field_updates is a non-empty dict of column_name: new_value
        - At least one of item_id or match_fields must be provided

    Ensures:
        - Matching rows are updated with new field values
        - Returns dict with status, message, and updated_count
    """
    if not field_updates:
        return { "status": "error", "message": "field_updates is required" }

    if not item_id and not match_fields:
        return { "status": "error", "message": "Provide item_id or match_fields" }

    df = storage.load_df( schema_type )
    if df.empty:
        return { "status": "not_found", "message": "No data exists" }

    if item_id:
        mask = df[ "id" ] == item_id
    else:
        # Validate all match_fields exist before building mask
        validation_error = _validate_match_fields( match_fields, df.columns, schema_type )
        if validation_error:
            return validation_error

        mask = pd.Series( True, index=df.index )
        for field, value in match_fields.items():
            if field in df.columns:
                mask = mask & ( df[ field ].astype( str ) == str( value ) )

    updated_count = mask.sum()
    if updated_count == 0:
        return { "status": "not_found", "message": "No matching items found" }

    for col, val in field_updates.items():
        if col in df.columns and col not in ( "id", "created_at" ):
            df.loc[ mask, col ] = val

    storage.save_df( df, schema_type )

    return { "status": "updated", "message": f"Updated {updated_count} item(s)", "updated_count": int( updated_count ) }


def mark_done( storage, schema_type, item_id=None, match_fields=None ):
    """
    Mark a todo item as completed.

    Convenience wrapper around update_item that sets completed="yes".

    Requires:
        - storage is a DataFrameStorage instance
        - schema_type is a valid schema type (typically "todo")
        - At least one of item_id or match_fields must be provided

    Ensures:
        - Matching rows have completed set to "yes"
        - Returns dict with status, message, and updated_count
    """
    return update_item(
        storage,
        schema_type,
        field_updates={ "completed": "yes" },
        item_id=item_id,
        match_fields=match_fields
    )


def query_items( storage, schema_type, list_name=None, filters=None, sort_by=None, limit=None ):
    """
    Query items with optional filtering, sorting, and limiting.

    Requires:
        - storage is a DataFrameStorage instance
        - schema_type is a valid schema type

    Ensures:
        - Returns dict with status, items (list of dicts), and total_count
        - Filters are applied as exact string matches
        - Results are sorted if sort_by is provided
        - Results are limited if limit is provided
    """
    if not validate_schema_type( schema_type ):
        return { "status": "error", "message": f"Unknown schema type '{schema_type}'" }

    df = storage.load_df( schema_type )

    if df.empty:
        return { "status": "ok", "items": [], "total_count": 0 }

    # Filter by list_name if provided
    if list_name:
        df = df[ df[ "list_name" ] == list_name ]

    # Apply additional filters
    if filters:
        for col, val in filters.items():
            if col in df.columns:
                df = df[ df[ col ].astype( str ) == str( val ) ]

    total_count = len( df )

    # Sort
    if sort_by and sort_by in df.columns:
        df = df.sort_values( sort_by, na_position="last" )

    # Limit
    if limit is not None and limit > 0:
        df = df.head( limit )

    # Convert to list of dicts, handling NaT/NaN for JSON compatibility
    items = df.where( df.notna(), "" ).astype( str ).to_dict( orient="records" )

    return { "status": "ok", "items": items, "total_count": total_count }


def get_schema_info( schema_type ):
    """
    Get schema information for a given type.

    Requires:
        - schema_type is a valid schema type string

    Ensures:
        - Returns dict with schema columns, defaults, and type metadata
    """
    if not validate_schema_type( schema_type ):
        return { "status": "error", "message": f"Unknown schema type '{schema_type}'" }

    schema  = get_schema( schema_type )
    columns = get_columns( schema_type )

    column_info = []
    for col in columns:
        meta = schema[ "columns" ][ col ]
        default = schema[ "defaults" ].get( col, "(required)" )
        column_info.append( {
            "name"    : col,
            "dtype"   : meta[ "dtype" ],
            "default" : default,
        } )

    return {
        "status"      : "ok",
        "schema_type" : schema_type,
        "columns"     : column_info,
        "total_columns" : len( columns ),
    }


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    import tempfile

    print( "Testing crud_operations module..." )
    passed = True

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:

            storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )

            # Test create_list
            result = create_list( storage, "groceries", "todo" )
            assert result[ "status" ] == "created"
            print( f"  ✓ create_list: {result[ 'message' ]}" )

            # Test add_item
            result = add_item( storage, "groceries", "todo", { "todo_item": "buy milk", "priority": "high" } )
            assert result[ "status" ] == "added"
            item_id = result[ "item_id" ]
            print( f"  ✓ add_item: id={item_id}" )

            # Add another item
            result2 = add_item( storage, "groceries", "todo", { "todo_item": "buy bread", "due_date": "2026-03-20" } )
            assert result2[ "status" ] == "added"
            print( f"  ✓ add_item (second): id={result2[ 'item_id' ]}" )

            # Test query_items
            result = query_items( storage, "todo", list_name="groceries" )
            assert result[ "status" ] == "ok"
            assert result[ "total_count" ] == 2
            print( f"  ✓ query_items: {result[ 'total_count' ]} items" )

            # Test query with filter
            result = query_items( storage, "todo", filters={ "priority": "high" } )
            assert result[ "total_count" ] == 1
            assert result[ "items" ][ 0 ][ "todo_item" ] == "buy milk"
            print( f"  ✓ query_items with filter: {result[ 'total_count' ]} item(s)" )

            # Test query with limit
            result = query_items( storage, "todo", list_name="groceries", limit=1 )
            assert len( result[ "items" ] ) == 1
            print( f"  ✓ query_items with limit=1" )

            # Test update_item
            result = update_item( storage, "todo", { "priority": "low" }, item_id=item_id )
            assert result[ "status" ] == "updated"
            print( f"  ✓ update_item: {result[ 'message' ]}" )

            # Verify update
            result = query_items( storage, "todo", filters={ "id": item_id } )
            assert result[ "items" ][ 0 ][ "priority" ] == "low"
            print( "  ✓ update verified" )

            # Test mark_done
            result = mark_done( storage, "todo", item_id=item_id )
            assert result[ "status" ] == "updated"
            print( f"  ✓ mark_done: {result[ 'message' ]}" )

            # Verify mark_done
            result = query_items( storage, "todo", filters={ "id": item_id } )
            assert result[ "items" ][ 0 ][ "completed" ] == "yes"
            print( "  ✓ mark_done verified" )

            # Test list_lists
            result = list_lists( storage, "todo" )
            assert result[ "status" ] == "ok"
            assert result[ "total_lists" ] == 1
            print( f"  ✓ list_lists: {result[ 'total_lists' ]} list(s)" )

            # Test delete_item
            result = delete_item( storage, "todo", item_id=item_id )
            assert result[ "status" ] == "deleted"
            assert result[ "deleted_count" ] == 1
            print( f"  ✓ delete_item: {result[ 'message' ]}" )

            # Test delete_list
            result = delete_list( storage, "groceries", "todo" )
            assert result[ "status" ] == "deleted"
            print( f"  ✓ delete_list: {result[ 'message' ]}" )

            # Test get_schema_info
            result = get_schema_info( "todo" )
            assert result[ "status" ] == "ok"
            assert result[ "total_columns" ] > 0
            print( f"  ✓ get_schema_info: {result[ 'total_columns' ]} columns" )

            # Test error cases
            result = add_item( storage, "", "todo", {} )
            assert result[ "status" ] == "error"
            print( "  ✓ Error: empty list_name" )

            result = get_schema_info( "nonexistent" )
            assert result[ "status" ] == "error"
            print( "  ✓ Error: invalid schema_type" )

        print( "✓ crud_operations module smoke test PASSED" )

    except Exception as e:
        print( f"✗ crud_operations module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
