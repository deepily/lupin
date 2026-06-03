"""
Unit tests for cosa.crud_for_dataframes.dispatcher.

Three pure functions: dispatch (CRUDIntent → crud_operations by operation),
format_result_for_voice (result dict → TTS string across every status), and
extract_intent_xml (regex carve-out of <intent>...</intent> from noisy LLM
text). dispatch is driven against real tempdir storage; the voice formatter is
driven with crafted result dicts to reach every status + count + item-shape
branch; the extractor is exercised on clean / fenced / preamble / empty /
missing inputs.

Assertions harvested + extended from the module's quick_smoke_test(), marked
for deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import tempfile
import unittest

from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.dispatcher import (
    dispatch,
    format_result_for_voice,
    extract_intent_xml,
    _format_query_items_for_voice,
)


class TestDispatch( unittest.TestCase ):
    """
    dispatch — routes every operation, raises on unknown.
    """

    def setUp( self ):
        self._tmp    = tempfile.TemporaryDirectory()
        self.storage = DataFrameStorage( user_email="test@example.com", base_path=self._tmp.name )

    def tearDown( self ):
        self._tmp.cleanup()

    def test_dispatch_add_then_query( self ):
        """Ensures add and query operations route and return ok results."""
        add_intent = CRUDIntent(
            operation="add", target_list="groceries", schema_type="todo",
            fields='{"todo_item": "buy milk", "priority": "high"}'
        )
        self.assertEqual( dispatch( add_intent, self.storage, debug=True )[ "status" ], "added" )

        query_intent = CRUDIntent( operation="query", target_list="groceries", schema_type="todo" )
        result = dispatch( query_intent, self.storage )
        self.assertEqual( result[ "status" ], "ok" )
        self.assertEqual( result[ "total_count" ], 1 )

    def test_dispatch_create_and_delete_list( self ):
        """Ensures create_list and delete_list operations route correctly."""
        self.assertEqual(
            dispatch( CRUDIntent( operation="create_list", target_list="g", schema_type="todo" ), self.storage )[ "status" ],
            "created"
        )
        dispatch( CRUDIntent( operation="add", target_list="g", schema_type="todo", fields='{"todo_item": "x"}' ), self.storage )
        self.assertEqual(
            dispatch( CRUDIntent( operation="delete_list", target_list="g", schema_type="todo" ), self.storage )[ "status" ],
            "deleted"
        )

    def test_dispatch_update_delete_markdone_by_id_and_match( self ):
        """Ensures update/mark_done (by id) and delete (by match) all route."""
        item_id = dispatch(
            CRUDIntent( operation="add", target_list="g", schema_type="todo", fields='{"todo_item": "milk"}' ),
            self.storage
        )[ "item_id" ]

        upd = dispatch(
            CRUDIntent( operation="update", schema_type="todo", item_id=item_id, fields='{"priority": "low"}' ),
            self.storage
        )
        self.assertEqual( upd[ "status" ], "updated" )

        done = dispatch( CRUDIntent( operation="mark_done", schema_type="todo", item_id=item_id ), self.storage )
        self.assertEqual( done[ "status" ], "updated" )

        deleted = dispatch(
            CRUDIntent( operation="delete", schema_type="todo", match_fields='{"todo_item": "milk"}' ),
            self.storage
        )
        self.assertEqual( deleted[ "status" ], "deleted" )

    def test_dispatch_list_lists_and_schema_info( self ):
        """Ensures list_lists and get_schema_info operations route correctly."""
        self.assertEqual( dispatch( CRUDIntent( operation="list_lists", schema_type="todo" ), self.storage )[ "status" ], "ok" )
        # schema_type empty -> list_lists across all schemas (None branch)
        self.assertEqual( dispatch( CRUDIntent( operation="list_lists", schema_type="" ), self.storage )[ "status" ], "ok" )
        self.assertEqual( dispatch( CRUDIntent( operation="get_schema_info", schema_type="todo" ), self.storage )[ "status" ], "ok" )

    def test_dispatch_query_with_filters_sort_limit( self ):
        """Ensures the query branch threads filters, sort_by, and limit through."""
        for item in ( "milk", "bread", "eggs" ):
            dispatch(
                CRUDIntent( operation="add", target_list="g", schema_type="todo", fields=f'{{"todo_item": "{item}", "priority": "low"}}' ),
                self.storage
            )
        q = CRUDIntent(
            operation="query", target_list="g", schema_type="todo",
            filters='{"priority": "low"}', sort_by="todo_item", limit="2"
        )
        result = dispatch( q, self.storage )
        self.assertEqual( result[ "total_count" ], 3 )
        self.assertEqual( len( result[ "items" ] ), 2 )   # limited

    def test_dispatch_unknown_operation_raises( self ):
        """Ensures an unrecognized operation raises ValueError."""
        with self.assertRaises( ValueError ):
            dispatch( CRUDIntent( operation="frobnicate" ), self.storage )


class TestFormatResultForVoice( unittest.TestCase ):
    """
    format_result_for_voice — every status / operation / count branch.
    """

    def test_error_and_not_found( self ):
        """Ensures error and not_found statuses produce apologetic phrasing."""
        self.assertIn( "Sorry", format_result_for_voice( { "status": "error", "message": "boom" }, "add" ) )
        self.assertIn( "couldn't find", format_result_for_voice( { "status": "not_found", "message": "nope" }, "delete" ) )

    def test_add_added_and_duplicate( self ):
        """Ensures add reports done on success and a friendly message on duplicate."""
        self.assertIn( "Done", format_result_for_voice( { "status": "added", "message": "ok" }, "add" ) )
        self.assertIn( "already exists", format_result_for_voice( { "status": "duplicate" }, "add" ) )

    def test_create_list_created_and_exists( self ):
        """Ensures create_list reports created and exists distinctly."""
        self.assertIn( "Got it", format_result_for_voice( { "status": "created", "message": "ready" }, "create_list" ) )
        self.assertIn( "here", format_result_for_voice( { "status": "exists", "message": "is here" }, "create_list" ) )

    def test_delete_with_and_without_count( self ):
        """Ensures delete phrasing covers the count and no-count branches."""
        self.assertIn( "Removed 2 items", format_result_for_voice( { "status": "deleted", "deleted_count": 2 }, "delete" ) )
        self.assertIn( "Removed 1 item", format_result_for_voice( { "status": "deleted", "deleted_count": 1 }, "delete_list" ) )
        self.assertIn( "Done", format_result_for_voice( { "status": "deleted", "message": "gone" }, "delete" ) )

    def test_update_with_and_without_count( self ):
        """Ensures update/mark_done phrasing covers the count and no-count branches."""
        self.assertIn( "Updated 3 items", format_result_for_voice( { "status": "updated", "updated_count": 3 }, "update" ) )
        self.assertIn( "Updated 1 item", format_result_for_voice( { "status": "updated", "updated_count": 1 }, "mark_done" ) )
        self.assertIn( "Done", format_result_for_voice( { "status": "updated", "message": "ok" }, "update" ) )

    def test_query_zero_and_nonzero( self ):
        """Ensures query reports 'no items' on zero and a summary otherwise."""
        self.assertEqual( format_result_for_voice( { "status": "ok", "items": [], "total_count": 0 }, "query" ), "No items found." )
        voice = format_result_for_voice(
            { "status": "ok", "items": [ { "todo_item": "milk" } ], "total_count": 1 }, "query"
        )
        self.assertIn( "Found 1 item", voice )

    def test_list_lists_zero_and_nonzero( self ):
        """Ensures list_lists reports the empty case and a name roll-up."""
        self.assertIn( "don't have any", format_result_for_voice( { "status": "ok", "lists": [], "total_lists": 0 }, "list_lists" ) )
        voice = format_result_for_voice(
            { "status": "ok", "lists": [ { "list_name": "groceries" }, { "list_name": "chores" } ], "total_lists": 2 },
            "list_lists"
        )
        self.assertIn( "2 lists", voice )
        self.assertIn( "groceries", voice )

    def test_schema_info_and_fallback( self ):
        """Ensures get_schema_info phrasing and the generic fallbacks both work."""
        self.assertIn( "todo schema has 8 columns", format_result_for_voice(
            { "status": "ok", "schema_type": "todo", "total_columns": 8 }, "get_schema_info"
        ) )
        # Fallback with a message
        self.assertEqual( format_result_for_voice( { "status": "weird", "message": "huh" }, "noop" ), "huh" )
        # Fallback with no message
        self.assertIn( "completed with status", format_result_for_voice( { "status": "weird" }, "noop" ) )


class TestFormatQueryItemsForVoice( unittest.TestCase ):
    """
    _format_query_items_for_voice — desc fallback chain, suffixes, overflow.
    """

    def test_desc_fallback_chain( self ):
        """Ensures the description falls back across todo_item/event/name/value."""
        items = [
            { "todo_item": "milk" },
            { "event": "standup" },
            { "name": "alice" },
            { "value": "42" },
        ]
        out = _format_query_items_for_voice( items, 4 )
        for token in ( "milk", "standup", "alice", "42" ):
            self.assertIn( token, out )

    def test_priority_and_completed_suffixes( self ):
        """Ensures non-medium priority and completed=yes add parenthetical suffixes."""
        out = _format_query_items_for_voice(
            [ { "todo_item": "milk", "priority": "high", "completed": "yes" } ], 1
        )
        self.assertIn( "high priority", out )
        self.assertIn( "completed", out )

    def test_medium_priority_has_no_suffix( self ):
        """Ensures medium priority is suppressed from the suffix."""
        out = _format_query_items_for_voice( [ { "todo_item": "milk", "priority": "medium" } ], 1 )
        self.assertNotIn( "priority", out )

    def test_item_without_description_is_skipped( self ):
        """Ensures an item with no recognizable description contributes no line."""
        out = _format_query_items_for_voice( [ { "irrelevant": "x" } ], 1 )
        self.assertEqual( out.strip(), "Found 1 item." )

    def test_overflow_more_line( self ):
        """Ensures more than five items appends an '...and N more' line."""
        items = [ { "todo_item": f"item{i}" } for i in range( 8 ) ]
        out   = _format_query_items_for_voice( items, 8 )
        self.assertIn( "...and 3 more", out )


class TestExtractIntentXml( unittest.TestCase ):
    """
    extract_intent_xml — clean / fenced / preamble / empty / missing.
    """

    def test_clean_xml( self ):
        """Ensures a clean <intent> block is returned verbatim-enough."""
        xml = "<intent><operation>add</operation></intent>"
        self.assertIn( "<operation>add</operation>", extract_intent_xml( xml ) )

    def test_markdown_fenced( self ):
        """Ensures markdown code fences around the XML are stripped."""
        fenced = "```xml\n<intent><operation>query</operation></intent>\n```"
        self.assertIn( "<operation>query</operation>", extract_intent_xml( fenced ) )

    def test_with_preamble( self ):
        """Ensures preamble text before the XML is ignored."""
        text = "Here is the intent:\n<intent><operation>add</operation></intent>"
        self.assertIn( "<operation>add</operation>", extract_intent_xml( text ) )

    def test_empty_raises( self ):
        """Ensures empty/whitespace input raises ValueError."""
        with self.assertRaises( ValueError ):
            extract_intent_xml( "   " )

    def test_missing_block_raises( self ):
        """Ensures text with no <intent> block raises ValueError."""
        with self.assertRaises( ValueError ):
            extract_intent_xml( "no xml here at all" )


if __name__ == "__main__":
    unittest.main()
