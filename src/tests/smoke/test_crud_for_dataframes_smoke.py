#!/usr/bin/env python3
"""
End-to-end smoke test for DataFrame CRUD storage layer.

Tests the complete workflow:
    Schema → CRUDIntent round-trip → Storage → CRUD cycle with date fields.

No server required. Tabular output. Run directly or via pytest.

Run: python src/tests/smoke/test_crud_for_dataframes_smoke.py
"""

import tempfile
from datetime import datetime

import pandas as pd


def quick_smoke_test():
    """
    Full end-to-end smoke test for crud_for_dataframes package.

    Tests:
        1. Schema definitions and helpers
        2. CRUDIntent XML round-trip
        3. DataFrameStorage save/load with datetime conversion
        4. Full CRUD cycle (create → add → query → update → mark_done → delete)
        5. Calendar event with date/time fields
        6. Date round-trip verification
    """

    from cosa.crud_for_dataframes.schemas import (
        get_schema, get_columns, get_defaults,
        get_date_columns, get_time_columns, get_datetime_columns,
        validate_schema_type, VALID_SCHEMA_TYPES,
    )
    from cosa.crud_for_dataframes.xml_models import CRUDIntent
    from cosa.crud_for_dataframes.storage import DataFrameStorage
    from cosa.crud_for_dataframes.crud_operations import (
        create_list, delete_list, list_lists,
        add_item, delete_item, update_item, mark_done,
        query_items, get_schema_info,
    )

    results = []
    all_passed = True

    def record( test_name, passed, detail="" ):
        nonlocal all_passed
        status = "PASS" if passed else "FAIL"
        if not passed: all_passed = False
        results.append( ( test_name, status, detail ) )

    # ── 1. Schema definitions ──────────────────────────────────────────

    try:
        for st in [ "todo", "calendar", "generic" ]:
            schema = get_schema( st )
            assert "columns" in schema
            assert "defaults" in schema
        record( "Schema definitions", True, f"{len( VALID_SCHEMA_TYPES )} types" )
    except Exception as e:
        record( "Schema definitions", False, str( e ) )

    try:
        cols = get_columns( "todo" )
        assert "todo_item" in cols
        assert "id" in cols
        record( "Todo columns", True, f"{len( cols )} columns" )
    except Exception as e:
        record( "Todo columns", False, str( e ) )

    try:
        date_cols = get_date_columns( "calendar" )
        time_cols = get_time_columns( "calendar" )
        dt_cols   = get_datetime_columns( "calendar" )
        assert "start_date" in date_cols
        assert "start_time" in time_cols
        assert "created_at" in dt_cols
        record( "Column dtype helpers", True, f"dates={len( date_cols )}, times={len( time_cols )}, dt={len( dt_cols )}" )
    except Exception as e:
        record( "Column dtype helpers", False, str( e ) )

    # ── 2. CRUDIntent XML round-trip ───────────────────────────────────

    try:
        original = CRUDIntent.get_example_for_template()
        xml_str  = original.to_xml( root_tag="intent" )
        parsed   = CRUDIntent.from_xml( xml_str, root_tag="intent" )
        assert parsed.operation == original.operation
        assert parsed.target_list == original.target_list
        assert parsed.get_fields_dict() == original.get_fields_dict()
        record( "CRUDIntent XML round-trip", True, f"{len( xml_str )} chars" )
    except Exception as e:
        record( "CRUDIntent XML round-trip", False, str( e ) )

    try:
        intent = CRUDIntent( operation="delete", confidence="0.8" )
        assert intent.is_destructive()
        assert intent.needs_confirmation()
        assert intent.get_confidence_float() == 0.8
        record( "CRUDIntent methods", True, "destructive/confirmation/confidence" )
    except Exception as e:
        record( "CRUDIntent methods", False, str( e ) )

    # ── 3. Storage save/load with datetime conversion ──────────────────

    with tempfile.TemporaryDirectory() as tmp_dir:

        try:
            storage = DataFrameStorage( user_email="smoke@test.com", base_path=tmp_dir )
            assert storage.user_email == "smoke@test.com"
            record( "Storage constructor", True, f"base={tmp_dir}" )
        except Exception as e:
            record( "Storage constructor", False, str( e ) )

        try:
            # Add a todo with due_date
            result = add_item( storage, "groceries", "todo", {
                "todo_item" : "buy milk",
                "due_date"  : "2026-03-15",
                "priority"  : "high",
            } )
            assert result[ "status" ] == "added"
            item_id = result[ "item_id" ]
            record( "Add item with date", True, f"id={item_id}" )
        except Exception as e:
            record( "Add item with date", False, str( e ) )

        # ── 4. Date round-trip verification ────────────────────────────

        try:
            df = storage.load_df( "todo" )
            assert pd.api.types.is_datetime64_any_dtype( df[ "due_date" ] )
            due = df.iloc[ 0 ][ "due_date" ]
            assert due.year == 2026
            assert due.month == 3
            assert due.day == 15
            record( "Date round-trip", True, f"due_date={due.date()}" )
        except Exception as e:
            record( "Date round-trip", False, str( e ) )

        # ── 5. Full CRUD cycle ─────────────────────────────────────────

        try:
            # Create another list
            create_list( storage, "work", "todo" )

            # Add items
            add_item( storage, "work", "todo", { "todo_item": "finish report" } )
            add_item( storage, "groceries", "todo", { "todo_item": "buy bread" } )

            # Query
            result = query_items( storage, "todo" )
            assert result[ "total_count" ] == 3
            record( "CRUD query all", True, f"{result[ 'total_count' ]} items" )
        except Exception as e:
            record( "CRUD query all", False, str( e ) )

        try:
            # Update
            update_item( storage, "todo", { "priority": "low" }, item_id=item_id )
            updated = query_items( storage, "todo", filters={ "id": item_id } )
            assert updated[ "items" ][ 0 ][ "priority" ] == "low"
            record( "CRUD update", True, "priority → low" )
        except Exception as e:
            record( "CRUD update", False, str( e ) )

        try:
            # Mark done
            mark_done( storage, "todo", item_id=item_id )
            done = query_items( storage, "todo", filters={ "id": item_id } )
            assert done[ "items" ][ 0 ][ "completed" ] == "yes"
            record( "CRUD mark_done", True, "completed → yes" )
        except Exception as e:
            record( "CRUD mark_done", False, str( e ) )

        try:
            # List lists
            result = list_lists( storage, "todo" )
            assert result[ "total_lists" ] == 2
            record( "CRUD list_lists", True, f"{result[ 'total_lists' ]} lists" )
        except Exception as e:
            record( "CRUD list_lists", False, str( e ) )

        try:
            # Delete item
            delete_item( storage, "todo", item_id=item_id )
            remaining = query_items( storage, "todo", list_name="groceries" )
            assert remaining[ "total_count" ] == 1
            record( "CRUD delete_item", True, "1 item removed" )
        except Exception as e:
            record( "CRUD delete_item", False, str( e ) )

        try:
            # Delete list
            delete_list( storage, "work", "todo" )
            result = list_lists( storage, "todo" )
            assert result[ "total_lists" ] == 1
            record( "CRUD delete_list", True, "work list removed" )
        except Exception as e:
            record( "CRUD delete_list", False, str( e ) )

        # ── 6. Calendar event with date/time ───────────────────────────

        try:
            add_item( storage, "personal", "calendar", {
                "event"      : "Dentist appointment",
                "start_date" : "2026-03-15",
                "end_date"   : "2026-03-15",
                "start_time" : "14:30",
                "end_time"   : "15:30",
                "event_type" : "appointment",
                "location"   : "Downtown Dental",
            } )
            cal_items = query_items( storage, "calendar", list_name="personal" )
            assert cal_items[ "total_count" ] == 1
            assert cal_items[ "items" ][ 0 ][ "event" ] == "Dentist appointment"

            # Verify date conversion
            df = storage.load_df( "calendar" )
            assert pd.api.types.is_datetime64_any_dtype( df[ "start_date" ] )
            # Time stays as string
            assert df.iloc[ 0 ][ "start_time" ] == "14:30"
            record( "Calendar event", True, "date/time/location verified" )
        except Exception as e:
            record( "Calendar event", False, str( e ) )

        try:
            info = get_schema_info( "todo" )
            assert info[ "status" ] == "ok"
            assert info[ "total_columns" ] == 8
            record( "get_schema_info", True, f"{info[ 'total_columns' ]} columns" )
        except Exception as e:
            record( "get_schema_info", False, str( e ) )

    # ── Print results table ────────────────────────────────────────────

    print( "\n" + "=" * 70 )
    print( "DataFrame CRUD Storage Layer — Smoke Test Results" )
    print( "=" * 70 )
    print( f"{'Test':<35} {'Status':<8} {'Detail'}" )
    print( "-" * 70 )
    for test_name, status, detail in results:
        marker = "✓" if status == "PASS" else "✗"
        print( f"  {marker} {test_name:<33} {status:<8} {detail}" )
    print( "-" * 70 )

    passed = sum( 1 for _, s, _ in results if s == "PASS" )
    failed = sum( 1 for _, s, _ in results if s == "FAIL" )
    print( f"  Total: {passed} passed, {failed} failed, {len( results )} total" )
    print( "=" * 70 )

    if all_passed:
        print( "\n✓ ALL SMOKE TESTS PASSED\n" )
    else:
        print( "\n✗ SOME SMOKE TESTS FAILED\n" )

    return all_passed


def test_crud_for_dataframes():
    """Pytest entry point."""
    assert quick_smoke_test()


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
