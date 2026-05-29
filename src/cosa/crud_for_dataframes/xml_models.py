#!/usr/bin/env python3
"""
XML response model for DataFrame CRUD intent extraction.

Defines CRUDIntent as a BaseXMLModel subclass for LLM-extracted CRUD
operations. All fields are strings (LLM I/O convention). JSON-encoded
fields (match_fields, fields, filters) are parsed via convenience methods.

Pattern follows ExpeditorResponse in
src/cosa/agents/runtime_argument_expeditor/xml_models.py.
"""

import json
from typing import ClassVar, List, Optional

from pydantic import Field, field_validator

from cosa.agents.io_models.utils.util_xml_pydantic import BaseXMLModel


class CRUDIntent( BaseXMLModel ):
    """
    CRUD intent extracted from natural language by LLM.

    Handles XML responses for DataFrame CRUD operations:
    <intent>
        <operation>add</operation>
        <target_list>groceries</target_list>
        <schema_type>todo</schema_type>
        <confidence>0.95</confidence>
        <requires_confirmation>false</requires_confirmation>
        <item_id></item_id>
        <match_fields>{}</match_fields>
        <fields>{"todo_item": "buy milk", "priority": "high"}</fields>
        <filters>{}</filters>
        <sort_by></sort_by>
        <limit></limit>
        <raw_query>add buy milk to my groceries list with high priority</raw_query>
    </intent>

    Fields (all str per BaseXMLModel convention — LLM I/O is always text):
        operation: CRUD operation (add, delete, update, query, mark_done, create_list, delete_list, list_lists, get_schema_info)
        target_list: Name of the list to operate on
        schema_type: Schema type (todo, calendar, generic)
        confidence: Float-as-string confidence score (0.0-1.0)
        requires_confirmation: "true" or "false" for destructive ops
        item_id: UUID8 of specific item (for update/delete)
        match_fields: JSON string of fields to match for update/delete
        fields: JSON string of field values to set
        filters: JSON string of query filter conditions
        sort_by: Column name to sort results by
        limit: Max number of results as string
        raw_query: Original natural language query
    """

    operation             : str = Field( ..., description="CRUD operation: add, delete, update, query, mark_done, create_list, delete_list, list_lists, get_schema_info" )
    target_list           : str = Field( default="", description="Name of the target list" )
    schema_type           : str = Field( default="todo", description="Schema type: todo, calendar, generic" )
    confidence            : str = Field( default="0.0", description="Confidence score as string (0.0-1.0)" )
    requires_confirmation : str = Field( default="false", description="'true' if operation needs user confirmation" )
    item_id               : str = Field( default="", description="UUID8 of specific item for update/delete" )
    match_fields          : str = Field( default="{}", description="JSON string of fields to match for update/delete" )
    fields                : str = Field( default="{}", description="JSON string of field values to set" )
    filters               : str = Field( default="{}", description="JSON string of query filter conditions" )
    sort_by               : str = Field( default="", description="Column name to sort results by" )
    limit                 : str = Field( default="", description="Max number of results" )
    raw_query             : str = Field( default="", description="Original natural language query" )

    @field_validator( "*", mode="before" )
    @classmethod
    def _coerce_none_to_empty_string( cls, v, info ):
        """
        Coerce None values to empty strings.

        xmltodict returns None for empty XML tags like <item_id></item_id>.
        Pydantic str fields reject None, so we convert at the boundary.
        """
        if v is None and info.field_name != "operation":
            return ""
        return v

    # Valid operations (ClassVar to avoid Pydantic treating as fields)
    VALID_OPERATIONS: ClassVar[ List[ str ] ] = [
        "add", "delete", "update", "query", "mark_done",
        "create_list", "delete_list", "list_lists", "get_schema_info"
    ]

    # Operations that modify or destroy data
    DESTRUCTIVE_OPERATIONS: ClassVar[ List[ str ] ] = [ "delete", "delete_list", "update" ]

    def get_confidence_float( self ):
        """
        Parse confidence string to float.

        Requires:
            - self.confidence is a numeric string

        Ensures:
            - Returns float between 0.0 and 1.0
            - Returns 0.0 if parsing fails
        """
        try:
            return max( 0.0, min( 1.0, float( self.confidence ) ) )
        except ( ValueError, TypeError ):
            return 0.0

    def is_destructive( self ):
        """
        Check if this operation modifies or destroys data.

        Requires:
            - self.operation is a string

        Ensures:
            - Returns True for delete, delete_list, update operations
            - Returns False for read-only operations
        """
        return self.operation in self.DESTRUCTIVE_OPERATIONS

    def needs_confirmation( self ):
        """
        Check if this operation requires user confirmation.

        Requires:
            - self.requires_confirmation is a string

        Ensures:
            - Returns True if requires_confirmation is "true" (case-insensitive)
            - Also returns True for any destructive operation
        """
        explicit = self.requires_confirmation.strip().lower() == "true"
        return explicit or self.is_destructive()

    def get_match_dict( self ):
        """
        Parse match_fields JSON string to dict.

        Requires:
            - self.match_fields is a JSON string or empty

        Ensures:
            - Returns dict of match field key-value pairs
            - Returns empty dict if parsing fails or empty
        """
        return self._parse_json_field( self.match_fields )

    def get_fields_dict( self ):
        """
        Parse fields JSON string to dict.

        Requires:
            - self.fields is a JSON string or empty

        Ensures:
            - Returns dict of field key-value pairs
            - Returns empty dict if parsing fails or empty
        """
        return self._parse_json_field( self.fields )

    def get_filters_dict( self ):
        """
        Parse filters JSON string to dict.

        Requires:
            - self.filters is a JSON string or empty

        Ensures:
            - Returns dict of filter conditions
            - Returns empty dict if parsing fails or empty
        """
        return self._parse_json_field( self.filters )

    def get_limit_int( self ):
        """
        Parse limit string to integer.

        Requires:
            - self.limit is a numeric string or empty

        Ensures:
            - Returns positive integer if valid
            - Returns None if empty or invalid
        """
        if not self.limit or not self.limit.strip():
            return None
        try:
            val = int( self.limit.strip() )
            return val if val > 0 else None
        except ( ValueError, TypeError ):
            return None

    def _parse_json_field( self, value ):
        """
        Parse a JSON string field to dict.

        Requires:
            - value is a string (potentially JSON)

        Ensures:
            - Returns parsed dict if valid JSON object
            - Returns empty dict if empty, None, or invalid
        """
        if not value or not value.strip() or value.strip() == "{}":
            return {}
        try:
            parsed = json.loads( value )
            return parsed if isinstance( parsed, dict ) else {}
        except ( json.JSONDecodeError, TypeError ):
            return {}

    def to_xml( self, root_tag="intent", pretty=True ):
        """
        Serialize CRUDIntent to XML with <intent> as default root tag.

        Overrides BaseXMLModel default of "response" since CRUD intent
        extraction uses <intent> as its XML root element.

        Requires:
            - root_tag is a non-empty string

        Ensures:
            - Returns XML string with specified root tag (default: "intent")
        """
        return super().to_xml( root_tag=root_tag, pretty=pretty )

    @classmethod
    def get_example_for_template( cls ):
        """
        Get example instance with generic placeholder values for prompt templates.

        Returns a CRUDIntent with "serving suggestion" placeholders so the LLM
        sees the XML structure without interpreting concrete data as the answer.

        Requires:
            - None

        Ensures:
            - Returns CRUDIntent with generic placeholder values
            - Placeholders are descriptive but clearly not real data
        """
        return cls(
            operation             = "[operation name]",
            target_list           = "[target list name]",
            schema_type           = "[schema type: todo, calendar, or generic]",
            confidence            = "[confidence score between 0.0 and 1.0]",
            requires_confirmation = "[true or false]",
            item_id               = "[item UUID if applicable]",
            match_fields          = "[JSON object of fields to match]",
            fields                = '[JSON object of field values to set]',
            filters               = '[JSON object of filter conditions]',
            sort_by               = "[column name to sort by]",
            limit                 = "[max number of results]",
            raw_query             = "[original user query exactly as spoken]"
        )

    @classmethod
    def quick_smoke_test( cls, debug=False ):
        """
        Quick smoke test for CRUDIntent.

        Args:
            debug: Enable debug output

        Returns:
            True if all tests pass
        """
        if debug: print( f"Testing {cls.__name__}..." )

        try:
            # Test base functionality
            if not super().quick_smoke_test( debug=False ):
                return False

            # Test creation with all fields (generic placeholders)
            intent = cls.get_example_for_template()
            assert intent.operation == "[operation name]"
            assert intent.target_list == "[target list name]"
            if debug: print( "  ✓ Creation with all fields (generic placeholders)" )

            # Test confidence parsing (placeholder is non-numeric, returns 0.0)
            assert intent.get_confidence_float() == 0.0
            bad_conf = cls( operation="query", confidence="not_a_number" )
            assert bad_conf.get_confidence_float() == 0.0
            if debug: print( "  ✓ Confidence parsing" )

            # Test destructive detection
            assert not intent.is_destructive()
            delete_intent = cls( operation="delete" )
            assert delete_intent.is_destructive()
            if debug: print( "  ✓ Destructive detection" )

            # Test confirmation logic
            assert not intent.needs_confirmation()  # add is not destructive, requires_confirmation=false
            assert delete_intent.needs_confirmation()  # delete is always destructive
            if debug: print( "  ✓ Confirmation logic" )

            # Test JSON field parsing (placeholder returns empty dict)
            assert intent.get_fields_dict() == {}
            if debug: print( "  ✓ JSON field parsing (placeholder)" )

            # Test JSON field parsing with real data
            real_intent = cls( operation="add", fields='{"todo_item": "buy milk", "priority": "high"}' )
            fields_dict = real_intent.get_fields_dict()
            assert fields_dict[ "todo_item" ] == "buy milk"
            assert fields_dict[ "priority" ] == "high"
            if debug: print( "  ✓ JSON field parsing (real data)" )

            # Test empty JSON field parsing
            assert intent.get_match_dict() == {}
            assert intent.get_filters_dict() == {}
            if debug: print( "  ✓ Empty JSON parsing" )

            # Test limit parsing
            assert intent.get_limit_int() is None
            limited = cls( operation="query", limit="10" )
            assert limited.get_limit_int() == 10
            if debug: print( "  ✓ Limit parsing" )

            # Test XML round-trip (to_xml defaults to root_tag="intent")
            xml_str = intent.to_xml()
            assert "<operation>[operation name]</operation>" in xml_str
            parsed = cls.from_xml( xml_str, root_tag="intent" )
            assert parsed.operation == intent.operation
            assert parsed.target_list == intent.target_list
            assert parsed.raw_query == intent.raw_query
            if debug: print( "  ✓ XML round-trip" )

            if debug: print( f"✓ {cls.__name__} smoke test PASSED" )
            return True

        except Exception as e:
            if debug: print( f"✗ {cls.__name__} smoke test FAILED: {e}" )
            return False


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""
    return CRUDIntent.quick_smoke_test( debug=True )


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
