#!/usr/bin/env python3
"""
Intent dispatch and voice formatting for DataFrame CRUD operations.

Pure functions that bridge CRUDIntent objects to crud_operations calls
and format results for TTS voice output.

Functions:
    dispatch: Routes CRUDIntent → crud_operations function by operation name
    format_result_for_voice: Converts result dicts to TTS-friendly strings
    extract_intent_xml: Regex extracts <intent>...</intent> from raw LLM response
"""

import re

from cosa.crud_for_dataframes.xml_models import CRUDIntent
from cosa.crud_for_dataframes.storage import DataFrameStorage
from cosa.crud_for_dataframes import crud_operations


def dispatch( intent, storage, debug=False ):
    """
    Route a CRUDIntent to the appropriate crud_operations function.

    Requires:
        - intent is a CRUDIntent instance with a valid operation field
        - storage is a DataFrameStorage instance

    Ensures:
        - Returns the result dict from the corresponding crud_operations function
        - Raises ValueError for unknown operations

    Raises:
        - ValueError if intent.operation is not in CRUDIntent.VALID_OPERATIONS
    """
    op = intent.operation.strip().lower()

    if debug: print( f"dispatcher.dispatch: operation={op}, target_list={intent.target_list}, schema_type={intent.schema_type}" )

    if op == "add":
        return crud_operations.add_item(
            storage,
            list_name    = intent.target_list,
            schema_type  = intent.schema_type,
            field_values = intent.get_fields_dict()
        )

    elif op == "delete":
        return crud_operations.delete_item(
            storage,
            schema_type  = intent.schema_type,
            item_id      = intent.item_id if intent.item_id else None,
            match_fields = intent.get_match_dict() or None
        )

    elif op == "update":
        return crud_operations.update_item(
            storage,
            schema_type    = intent.schema_type,
            field_updates  = intent.get_fields_dict(),
            item_id        = intent.item_id if intent.item_id else None,
            match_fields   = intent.get_match_dict() or None
        )

    elif op == "query":
        return crud_operations.query_items(
            storage,
            schema_type = intent.schema_type,
            list_name   = intent.target_list if intent.target_list else None,
            filters     = intent.get_filters_dict() or None,
            sort_by     = intent.sort_by if intent.sort_by else None,
            limit       = intent.get_limit_int()
        )

    elif op == "mark_done":
        return crud_operations.mark_done(
            storage,
            schema_type  = intent.schema_type,
            item_id      = intent.item_id if intent.item_id else None,
            match_fields = intent.get_match_dict() or None
        )

    elif op == "create_list":
        return crud_operations.create_list(
            storage,
            list_name   = intent.target_list,
            schema_type = intent.schema_type
        )

    elif op == "delete_list":
        return crud_operations.delete_list(
            storage,
            list_name   = intent.target_list,
            schema_type = intent.schema_type
        )

    elif op == "list_lists":
        return crud_operations.list_lists(
            storage,
            schema_type = intent.schema_type if intent.schema_type else None
        )

    elif op == "get_schema_info":
        return crud_operations.get_schema_info(
            schema_type = intent.schema_type
        )

    else:
        raise ValueError( f"Unknown operation '{op}'. Valid: {CRUDIntent.VALID_OPERATIONS}" )


def format_result_for_voice( result, operation ):
    """
    Convert a CRUD result dict to a TTS-friendly conversational string.

    Requires:
        - result is a dict with at least a "status" key
        - operation is a string naming the CRUD operation

    Ensures:
        - Returns a natural language string suitable for voice output
        - Handles all status types: ok, added, created, deleted, updated, exists, not_found, error
    """
    status  = result.get( "status", "error" )
    message = result.get( "message", "" )

    if status == "error":
        return f"Sorry, there was a problem: {message}"

    if status == "not_found":
        return f"I couldn't find what you're looking for. {message}"

    if operation == "add" and status == "added":
        return f"Done. {message}"

    if operation == "add" and status == "duplicate":
        return "That item already exists in the list."

    if operation in ( "create_list", ) and status == "created":
        return f"Got it. {message}"

    if operation in ( "create_list", ) and status == "exists":
        return f"{message}"

    if operation in ( "delete", "delete_list" ) and status == "deleted":
        count = result.get( "deleted_count", "" )
        if count:
            return f"Done. Removed {count} item{'s' if count != 1 else ''}."
        return f"Done. {message}"

    if operation in ( "update", "mark_done" ) and status == "updated":
        count = result.get( "updated_count", "" )
        if count:
            return f"Done. Updated {count} item{'s' if count != 1 else ''}."
        return f"Done. {message}"

    if operation == "query" and status == "ok":
        items = result.get( "items", [] )
        total = result.get( "total_count", len( items ) )
        if total == 0:
            return "No items found."
        return _format_query_items_for_voice( items, total )

    if operation == "list_lists" and status == "ok":
        lists = result.get( "lists", [] )
        total = result.get( "total_lists", len( lists ) )
        if total == 0:
            return "You don't have any lists yet."
        names = [ entry[ "list_name" ] for entry in lists ]
        return f"You have {total} list{'s' if total != 1 else ''}: {', '.join( names )}."

    if operation == "get_schema_info" and status == "ok":
        schema_type = result.get( "schema_type", "unknown" )
        col_count   = result.get( "total_columns", 0 )
        return f"The {schema_type} schema has {col_count} columns."

    # Fallback
    return message if message else f"Operation {operation} completed with status {status}."


def _format_query_items_for_voice( items, total ):
    """
    Format query result items into a voice-friendly summary.

    Requires:
        - items is a list of dicts (row records)
        - total is an integer count

    Ensures:
        - Returns a concise summary suitable for TTS
        - Limits detail to first 5 items for brevity
    """
    lines = [ f"Found {total} item{'s' if total != 1 else ''}." ]

    display_items = items[ :5 ]
    for item in display_items:
        # Try common descriptive fields in priority order
        desc = (
            item.get( "todo_item" ) or
            item.get( "event" ) or
            item.get( "name" ) or
            item.get( "value" ) or
            ""
        )
        if desc:
            priority = item.get( "priority", "" )
            completed = item.get( "completed", "" )
            suffix_parts = []
            if priority and priority != "medium":
                suffix_parts.append( f"{priority} priority" )
            if completed == "yes":
                suffix_parts.append( "completed" )
            suffix = f" ({', '.join( suffix_parts )})" if suffix_parts else ""
            lines.append( f"  {desc}{suffix}" )

    if total > 5:
        lines.append( f"  ...and {total - 5} more." )

    return "\n".join( lines )


def extract_intent_xml( raw_response ):
    """
    Extract <intent>...</intent> XML block from raw LLM response text.

    Handles common LLM response patterns:
    - Clean XML output
    - XML wrapped in markdown code fences
    - XML preceded by preamble text
    - XML followed by explanation text

    Requires:
        - raw_response is a string (may contain noise around XML)

    Ensures:
        - Returns the <intent>...</intent> XML string if found
        - Raises ValueError if no intent XML block is found
    """
    if not raw_response or not raw_response.strip():
        raise ValueError( "Empty response from LLM" )

    text = raw_response.strip()

    # Remove markdown code fences if present
    text = re.sub( r"```(?:xml)?\s*", "", text )
    text = re.sub( r"```\s*$", "", text, flags=re.MULTILINE )

    # Extract <intent>...</intent> block
    match = re.search( r"<intent\s*>.*?</intent>", text, re.DOTALL )
    if match:
        return match.group( 0 )

    raise ValueError( f"No <intent>...</intent> block found in LLM response. Response starts with: {raw_response[ :100 ]}" )


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    import tempfile

    print( "Testing dispatcher module..." )
    passed = True

    try:
        # Test extract_intent_xml — clean XML
        xml = '<intent><operation>add</operation><target_list>groceries</target_list></intent>'
        result = extract_intent_xml( xml )
        assert "<operation>add</operation>" in result
        print( "  ✓ extract_intent_xml: clean XML" )

        # Test extract_intent_xml — markdown fenced
        fenced = '```xml\n<intent><operation>query</operation></intent>\n```'
        result = extract_intent_xml( fenced )
        assert "<operation>query</operation>" in result
        print( "  ✓ extract_intent_xml: markdown fenced" )

        # Test extract_intent_xml — with preamble
        preamble = 'Here is the intent extraction:\n<intent><operation>add</operation></intent>'
        result = extract_intent_xml( preamble )
        assert "<operation>add</operation>" in result
        print( "  ✓ extract_intent_xml: with preamble" )

        # Test extract_intent_xml — missing intent
        try:
            extract_intent_xml( "No XML here" )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print( "  ✓ extract_intent_xml: missing intent raises ValueError" )

        # Test dispatch + format_result_for_voice with tempdir storage
        with tempfile.TemporaryDirectory() as tmp_dir:

            storage = DataFrameStorage( user_email="test@example.com", base_path=tmp_dir )

            # Test add via dispatch
            intent = CRUDIntent(
                operation   = "add",
                target_list = "groceries",
                schema_type = "todo",
                fields      = '{"todo_item": "buy milk", "priority": "high"}'
            )
            result = dispatch( intent, storage, debug=True )
            assert result[ "status" ] == "added"
            print( f"  ✓ dispatch add: {result[ 'message' ]}" )

            # Test voice formatting for add
            voice = format_result_for_voice( result, "add" )
            assert "Done" in voice
            print( f"  ✓ format_result_for_voice add: {voice}" )

            # Test query via dispatch
            query_intent = CRUDIntent(
                operation   = "query",
                target_list = "groceries",
                schema_type = "todo"
            )
            result = dispatch( query_intent, storage, debug=True )
            assert result[ "status" ] == "ok"
            assert result[ "total_count" ] == 1
            print( f"  ✓ dispatch query: {result[ 'total_count' ]} items" )

            # Test voice formatting for query
            voice = format_result_for_voice( result, "query" )
            assert "Found 1 item" in voice
            print( f"  ✓ format_result_for_voice query: {voice.split( chr( 10 ) )[ 0 ]}" )

            # Test list_lists via dispatch
            list_intent = CRUDIntent( operation="list_lists", schema_type="todo" )
            result = dispatch( list_intent, storage, debug=True )
            assert result[ "status" ] == "ok"
            voice = format_result_for_voice( result, "list_lists" )
            assert "groceries" in voice
            print( f"  ✓ dispatch list_lists + voice: {voice}" )

            # Test get_schema_info via dispatch
            schema_intent = CRUDIntent( operation="get_schema_info", schema_type="todo" )
            result = dispatch( schema_intent, storage, debug=True )
            assert result[ "status" ] == "ok"
            voice = format_result_for_voice( result, "get_schema_info" )
            assert "columns" in voice
            print( f"  ✓ dispatch get_schema_info + voice: {voice}" )

            # Test error formatting
            error_result = { "status": "error", "message": "Something went wrong" }
            voice = format_result_for_voice( error_result, "add" )
            assert "Sorry" in voice
            print( f"  ✓ format_result_for_voice error: {voice}" )

        print( "✓ dispatcher module smoke test PASSED" )

    except Exception as e:
        print( f"✗ dispatcher module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
