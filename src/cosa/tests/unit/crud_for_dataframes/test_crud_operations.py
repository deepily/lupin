"""
Unit tests for cosa.crud_for_dataframes.crud_operations.

Stateless CRUD functions over a DataFrameStorage. Every function and both
helpers (_generate_id, _validate_match_fields) are exercised across their
status branches: empty-input errors, invalid-schema errors, not-found,
dedup duplicate vs. distinct-add vs. new-list, single vs. multi match
guards, id-vs-match-field paths, field-update skip rules for infrastructure
columns, and query filter/sort/limit combinations. All I/O is tempdir-backed.

Assertions harvested + extended from the module's quick_smoke_test(), marked
for deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import os
import re
import tempfile
import unittest
from datetime import datetime

import pandas as pd

from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes import crud_operations as ops
from cosa.crud_for_dataframes.crud_operations import (
    _generate_id,
    _validate_match_fields,
    create_list,
    delete_list,
    list_lists,
    add_item,
    delete_item,
    update_item,
    mark_done,
    query_items,
    get_schema_info,
)


class _StorageFixture( unittest.TestCase ):
    """Shared tempdir-backed storage fixture."""

    def setUp( self ):
        self._tmp    = tempfile.TemporaryDirectory()
        self.storage = DataFrameStorage( user_email="test@example.com", base_path=self._tmp.name )

    def tearDown( self ):
        self._tmp.cleanup()


class TestHelpers( unittest.TestCase ):
    """
    _generate_id / _validate_match_fields.
    """

    def test_generate_id_is_8_hex_chars( self ):
        """Ensures the generated id is an 8-character lowercase hex string."""
        gen = _generate_id()
        self.assertEqual( len( gen ), 8 )
        self.assertTrue( re.fullmatch( r"[0-9a-f]{8}", gen ) )

    def test_generate_id_is_unique_enough( self ):
        """Ensures two consecutive ids differ."""
        self.assertNotEqual( _generate_id(), _generate_id() )

    def test_validate_match_fields_rejects_infrastructure_cols( self ):
        """Ensures matching by an infrastructure column returns an error dict."""
        cols  = [ "id", "list_name", "created_at", "todo_item" ]
        error = _validate_match_fields( { "id": "x" }, cols, "todo" )
        self.assertEqual( error[ "status" ], "error" )
        self.assertIn( "infrastructure", error[ "message" ] )

    def test_validate_match_fields_rejects_unknown_field( self ):
        """Ensures an unknown match field returns an error naming valid fields."""
        cols  = [ "id", "list_name", "created_at", "todo_item" ]
        error = _validate_match_fields( { "bogus": "x" }, cols, "todo" )
        self.assertEqual( error[ "status" ], "error" )
        self.assertIn( "bogus", error[ "message" ] )

    def test_validate_match_fields_accepts_valid_field( self ):
        """Ensures a valid data field returns None (no error)."""
        cols = [ "id", "list_name", "created_at", "todo_item" ]
        self.assertIsNone( _validate_match_fields( { "todo_item": "milk" }, cols, "todo" ) )


class TestCreateList( _StorageFixture ):
    """
    create_list — error / created / exists.
    """

    def test_empty_name_error( self ):
        """Ensures a blank list_name returns an error."""
        self.assertEqual( create_list( self.storage, "  ", "todo" )[ "status" ], "error" )

    def test_invalid_schema_error( self ):
        """Ensures an unknown schema type returns an error."""
        self.assertEqual( create_list( self.storage, "groceries", "bogus" )[ "status" ], "error" )

    def test_created_initializes_file( self ):
        """Ensures a brand-new list reports 'created' and initializes the schema file."""
        result = create_list( self.storage, "groceries", "todo" )
        self.assertEqual( result[ "status" ], "created" )
        self.assertTrue( self.storage.file_exists( "todo" ) )

    def test_existing_list_reports_exists( self ):
        """Ensures creating a list that already has items reports 'exists'."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        self.assertEqual( create_list( self.storage, "groceries", "todo" )[ "status" ], "exists" )

    def test_new_list_when_schema_file_already_exists( self ):
        """Ensures a new list name in an already-initialized schema file reports 'created'.

        Covers the branch where the schema parquet already exists (so it is NOT
        re-initialized) yet the requested list_name is new.
        """
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )   # file now exists
        result = create_list( self.storage, "chores", "todo" )
        self.assertEqual( result[ "status" ], "created" )


class TestAddItem( _StorageFixture ):
    """
    add_item — error / added / duplicate / dedup branch matrix.
    """

    def test_empty_name_error( self ):
        """Ensures a blank list_name returns an error."""
        self.assertEqual( add_item( self.storage, "", "todo", {} )[ "status" ], "error" )

    def test_invalid_schema_error( self ):
        """Ensures an unknown schema type returns an error."""
        self.assertEqual( add_item( self.storage, "g", "bogus", {} )[ "status" ], "error" )

    def test_added_first_item( self ):
        """Ensures the first add into an empty store succeeds with an item_id."""
        result = add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        self.assertEqual( result[ "status" ], "added" )
        self.assertEqual( len( result[ "item_id" ] ), 8 )

    def test_distinct_item_into_existing_list_added( self ):
        """Ensures a distinct item in a populated list passes the dedup guard."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        result = add_item( self.storage, "groceries", "todo", { "todo_item": "bread" } )
        self.assertEqual( result[ "status" ], "added" )

    def test_duplicate_item_rejected( self ):
        """Ensures an identical business item in the same list is rejected as duplicate."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        result = add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        self.assertEqual( result[ "status" ], "duplicate" )

    def test_same_item_different_list_added( self ):
        """Ensures the dedup guard is scoped per-list (same item, other list, added)."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        result = add_item( self.storage, "chores", "todo", { "todo_item": "milk" } )
        self.assertEqual( result[ "status" ], "added" )

    def test_dedup_skips_key_absent_from_legacy_frame( self ):
        """Ensures the dedup loop skips a dedup key missing from a legacy parquet.

        Simulates a pre-existing parquet that has list_name but lacks the
        todo_item dedup column. The dedup loop skips the absent key, leaving the
        all-True seed mask, so any same-list row is treated as a duplicate.
        Covers the loop's key-absent (skip-body) branch.
        """
        path = self.storage.get_parquet_path( "todo" )
        os.makedirs( os.path.dirname( path ), exist_ok=True )
        pd.DataFrame( {
            "id"         : [ "old00001" ],
            "list_name"  : [ "groceries" ],
            "created_at" : [ datetime.now().isoformat() ],
        } ).to_parquet( path, index=False )

        result = add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        self.assertEqual( result[ "status" ], "duplicate" )


class TestDeleteList( _StorageFixture ):
    """
    delete_list — error / not_found / deleted.
    """

    def test_empty_name_error( self ):
        """Ensures a blank list_name returns an error."""
        self.assertEqual( delete_list( self.storage, "" )[ "status" ], "error" )

    def test_no_data_not_found( self ):
        """Ensures deleting from an empty store reports not_found."""
        self.assertEqual( delete_list( self.storage, "groceries", "todo" )[ "status" ], "not_found" )

    def test_missing_list_not_found( self ):
        """Ensures deleting an absent list (other lists present) reports not_found."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        self.assertEqual( delete_list( self.storage, "chores", "todo" )[ "status" ], "not_found" )

    def test_deleted_with_count( self ):
        """Ensures deleting a populated list reports deleted and the row count."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        add_item( self.storage, "groceries", "todo", { "todo_item": "bread" } )
        result = delete_list( self.storage, "groceries", "todo" )
        self.assertEqual( result[ "status" ], "deleted" )
        self.assertEqual( result[ "deleted_count" ], 2 )


class TestListLists( _StorageFixture ):
    """
    list_lists — invalid / per-schema / all-schema / empty.
    """

    def test_invalid_schema_error( self ):
        """Ensures an unknown schema type returns an error."""
        self.assertEqual( list_lists( self.storage, "bogus" )[ "status" ], "error" )

    def test_per_schema_counts( self ):
        """Ensures a schema-scoped listing reports per-list counts."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        result = list_lists( self.storage, "todo" )
        self.assertEqual( result[ "total_lists" ], 1 )
        self.assertEqual( result[ "lists" ][ 0 ][ "list_name" ], "groceries" )

    def test_per_schema_empty( self ):
        """Ensures a schema-scoped listing with no data reports zero lists."""
        result = list_lists( self.storage, "todo" )
        self.assertEqual( result[ "total_lists" ], 0 )

    def test_all_schemas( self ):
        """Ensures schema_type=None aggregates metadata across all schemas."""
        add_item( self.storage, "groceries", "todo", { "todo_item": "milk" } )
        result = list_lists( self.storage, None )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertEqual( result[ "total_lists" ], 1 )


class TestDeleteItem( _StorageFixture ):
    """
    delete_item — argument guard / not_found / id / match / multi-match guard.
    """

    def test_requires_id_or_match( self ):
        """Ensures delete with neither id nor match_fields returns an error."""
        self.assertEqual( delete_item( self.storage, "todo" )[ "status" ], "error" )

    def test_no_data_not_found( self ):
        """Ensures delete against an empty store reports not_found."""
        self.assertEqual( delete_item( self.storage, "todo", item_id="x" )[ "status" ], "not_found" )

    def test_delete_by_id( self ):
        """Ensures deleting by item_id removes exactly that row."""
        item_id = add_item( self.storage, "g", "todo", { "todo_item": "milk" } )[ "item_id" ]
        result  = delete_item( self.storage, "todo", item_id=item_id )
        self.assertEqual( result[ "status" ], "deleted" )
        self.assertEqual( result[ "deleted_count" ], 1 )

    def test_delete_by_id_no_match_not_found( self ):
        """Ensures deleting by an unknown id reports not_found."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        self.assertEqual( delete_item( self.storage, "todo", item_id="ffffffff" )[ "status" ], "not_found" )

    def test_delete_by_match_single( self ):
        """Ensures deleting by a uniquely-matching field removes one row."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        result = delete_item( self.storage, "todo", match_fields={ "todo_item": "milk" } )
        self.assertEqual( result[ "status" ], "deleted" )

    def test_delete_by_match_validation_error( self ):
        """Ensures match_fields with an infrastructure column is rejected."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        result = delete_item( self.storage, "todo", match_fields={ "id": "x" } )
        self.assertEqual( result[ "status" ], "error" )

    def test_delete_by_match_multi_guard( self ):
        """Ensures a multi-row match is refused with a preview, not deleted."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk",  "priority": "high" } )
        add_item( self.storage, "g", "todo", { "todo_item": "bread", "priority": "high" } )
        result = delete_item( self.storage, "todo", match_fields={ "priority": "high" } )
        self.assertEqual( result[ "status" ], "error" )
        self.assertIn( "matched_preview", result )

    def test_delete_by_match_no_match_not_found( self ):
        """Ensures a match that hits no rows reports not_found."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        self.assertEqual(
            delete_item( self.storage, "todo", match_fields={ "todo_item": "absent" } )[ "status" ],
            "not_found"
        )


class TestUpdateAndMarkDone( _StorageFixture ):
    """
    update_item / mark_done — guards / id / match / skip-rules.
    """

    def test_requires_field_updates( self ):
        """Ensures update with no field_updates returns an error."""
        self.assertEqual( update_item( self.storage, "todo", {}, item_id="x" )[ "status" ], "error" )

    def test_requires_id_or_match( self ):
        """Ensures update with neither id nor match returns an error."""
        self.assertEqual( update_item( self.storage, "todo", { "priority": "low" } )[ "status" ], "error" )

    def test_no_data_not_found( self ):
        """Ensures update against an empty store reports not_found."""
        self.assertEqual(
            update_item( self.storage, "todo", { "priority": "low" }, item_id="x" )[ "status" ],
            "not_found"
        )

    def test_update_by_id_applies_change( self ):
        """Ensures update by id changes a data field."""
        item_id = add_item( self.storage, "g", "todo", { "todo_item": "milk", "priority": "high" } )[ "item_id" ]
        result  = update_item( self.storage, "todo", { "priority": "low" }, item_id=item_id )
        self.assertEqual( result[ "status" ], "updated" )
        rows = query_items( self.storage, "todo", filters={ "id": item_id } )[ "items" ]
        self.assertEqual( rows[ 0 ][ "priority" ], "low" )

    def test_update_skips_infrastructure_and_unknown_columns( self ):
        """Ensures id/created_at and unknown columns are skipped during update."""
        item_id  = add_item( self.storage, "g", "todo", { "todo_item": "milk" } )[ "item_id" ]
        original = query_items( self.storage, "todo", filters={ "id": item_id } )[ "items" ][ 0 ]
        result   = update_item(
            self.storage, "todo",
            { "id": "HACKED", "created_at": "HACKED", "bogus_col": "x", "priority": "low" },
            item_id=item_id
        )
        self.assertEqual( result[ "status" ], "updated" )
        row = query_items( self.storage, "todo", filters={ "id": item_id } )[ "items" ][ 0 ]
        self.assertEqual( row[ "id" ], item_id )                     # id untouched
        self.assertEqual( row[ "created_at" ], original[ "created_at" ] )  # created_at untouched
        self.assertEqual( row[ "priority" ], "low" )                 # data field applied

    def test_update_by_match_validation_error( self ):
        """Ensures update match_fields with an unknown field is rejected."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        result = update_item( self.storage, "todo", { "priority": "low" }, match_fields={ "bogus": "x" } )
        self.assertEqual( result[ "status" ], "error" )

    def test_update_by_match_no_match_not_found( self ):
        """Ensures an update matching no rows reports not_found."""
        add_item( self.storage, "g", "todo", { "todo_item": "milk" } )
        self.assertEqual(
            update_item( self.storage, "todo", { "priority": "low" }, match_fields={ "todo_item": "absent" } )[ "status" ],
            "not_found"
        )

    def test_mark_done_sets_completed_yes( self ):
        """Ensures mark_done flips completed to 'yes' via update_item."""
        item_id = add_item( self.storage, "g", "todo", { "todo_item": "milk" } )[ "item_id" ]
        result  = mark_done( self.storage, "todo", item_id=item_id )
        self.assertEqual( result[ "status" ], "updated" )
        row = query_items( self.storage, "todo", filters={ "id": item_id } )[ "items" ][ 0 ]
        self.assertEqual( row[ "completed" ], "yes" )


class TestQueryItems( _StorageFixture ):
    """
    query_items — invalid / empty / list filter / extra filters / sort / limit.
    """

    def _seed( self ):
        add_item( self.storage, "g", "todo", { "todo_item": "milk",  "priority": "high" } )
        add_item( self.storage, "g", "todo", { "todo_item": "bread", "priority": "low"  } )
        add_item( self.storage, "g", "todo", { "todo_item": "eggs",  "priority": "low"  } )

    def test_invalid_schema_error( self ):
        """Ensures an unknown schema type returns an error."""
        self.assertEqual( query_items( self.storage, "bogus" )[ "status" ], "error" )

    def test_empty_store_returns_no_items( self ):
        """Ensures querying an empty store yields zero items."""
        result = query_items( self.storage, "todo" )
        self.assertEqual( result[ "total_count" ], 0 )
        self.assertEqual( result[ "items" ], [] )

    def test_filter_by_list_name( self ):
        """Ensures list_name narrows the result set."""
        self._seed()
        add_item( self.storage, "other", "todo", { "todo_item": "soap" } )
        result = query_items( self.storage, "todo", list_name="g" )
        self.assertEqual( result[ "total_count" ], 3 )

    def test_extra_filters_including_unknown_column( self ):
        """Ensures known filters apply and unknown filter columns are ignored."""
        self._seed()
        result = query_items( self.storage, "todo", filters={ "priority": "low", "bogus": "x" } )
        self.assertEqual( result[ "total_count" ], 2 )

    def test_sort_by_known_and_unknown_column( self ):
        """Ensures sort_by orders results for a real column and ignores an unknown one."""
        self._seed()
        sorted_res = query_items( self.storage, "todo", sort_by="todo_item" )
        descs      = [ r[ "todo_item" ] for r in sorted_res[ "items" ] ]
        self.assertEqual( descs, sorted( descs ) )
        # unknown sort column is a no-op (does not raise)
        self.assertEqual( query_items( self.storage, "todo", sort_by="bogus" )[ "total_count" ], 3 )

    def test_limit_positive_and_nonpositive( self ):
        """Ensures a positive limit truncates and a non-positive limit is ignored."""
        self._seed()
        self.assertEqual( len( query_items( self.storage, "todo", limit=2 )[ "items" ] ), 2 )
        self.assertEqual( len( query_items( self.storage, "todo", limit=0 )[ "items" ] ), 3 )


class TestGetSchemaInfo( unittest.TestCase ):
    """
    get_schema_info — invalid / column metadata incl. required fallback.
    """

    def test_invalid_schema_error( self ):
        """Ensures an unknown schema type returns an error."""
        self.assertEqual( get_schema_info( "bogus" )[ "status" ], "error" )

    def test_reports_columns_and_required_default( self ):
        """Ensures column metadata includes dtype + default, '(required)' when absent."""
        result = get_schema_info( "todo" )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertEqual( result[ "total_columns" ], len( result[ "columns" ] ) )
        by_name = { c[ "name" ]: c for c in result[ "columns" ] }
        self.assertEqual( by_name[ "id" ][ "default" ], "(required)" )   # no default declared
        self.assertEqual( by_name[ "priority" ][ "default" ], "normal" ) # default declared
        self.assertEqual( by_name[ "created_at" ][ "dtype" ], "datetime" )


if __name__ == "__main__":
    unittest.main()
