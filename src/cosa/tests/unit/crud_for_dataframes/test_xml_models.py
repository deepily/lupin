"""
Unit tests for cosa.crud_for_dataframes.xml_models.CRUDIntent.

CRUDIntent is a BaseXMLModel subclass holding an LLM-extracted CRUD intent.
Every field is a string (LLM I/O convention); JSON-encoded fields are parsed
via convenience methods. These tests cover the None→"" boundary coercion, the
numeric parsers (confidence/limit) on valid + invalid + clamp inputs, the
destructive/confirmation predicates, JSON-field parsing on all branches, the
<intent>-rooted XML round-trip, and the prompt-template example factory.

Assertions harvested + extended from CRUDIntent.quick_smoke_test(), marked for
deletion once this replacement is green.

Created 2026-06-03 (CoSA coverage campaign — Cheech 🌿). New file.
"""

import unittest

from cosa.crud_for_dataframes.xml_models import CRUDIntent


class TestNoneCoercion( unittest.TestCase ):
    """
    _coerce_none_to_empty_string before-validator.

    Ensures:
        - None on a non-operation field becomes "" (xmltodict empty-tag contract)
        - Non-None values pass through unchanged
    """

    def test_none_on_non_operation_field_becomes_empty_string( self ):
        """Ensures item_id=None is coerced to '' rather than rejected."""
        intent = CRUDIntent( operation="query", item_id=None )
        self.assertEqual( intent.item_id, "" )

    def test_non_none_value_passes_through( self ):
        """Ensures a supplied value is not altered by the coercion validator."""
        intent = CRUDIntent( operation="query", item_id="abc12345" )
        self.assertEqual( intent.item_id, "abc12345" )

    def test_defaults_applied_when_field_omitted( self ):
        """Ensures omitted fields fall back to their declared defaults."""
        intent = CRUDIntent( operation="add" )
        self.assertEqual( intent.schema_type, "todo" )
        self.assertEqual( intent.match_fields, "{}" )
        self.assertEqual( intent.requires_confirmation, "false" )


class TestConfidenceParsing( unittest.TestCase ):
    """
    get_confidence_float — parse, clamp, and failure fallback.
    """

    def test_valid_in_range( self ):
        """Ensures an in-range numeric string parses to the same float."""
        self.assertAlmostEqual( CRUDIntent( operation="query", confidence="0.95" ).get_confidence_float(), 0.95 )

    def test_clamps_above_one( self ):
        """Ensures confidence above 1.0 clamps down to 1.0."""
        self.assertEqual( CRUDIntent( operation="query", confidence="2.5" ).get_confidence_float(), 1.0 )

    def test_clamps_below_zero( self ):
        """Ensures negative confidence clamps up to 0.0."""
        self.assertEqual( CRUDIntent( operation="query", confidence="-3" ).get_confidence_float(), 0.0 )

    def test_non_numeric_returns_zero( self ):
        """Ensures an unparseable confidence string returns 0.0 (ValueError path)."""
        self.assertEqual( CRUDIntent( operation="query", confidence="not_a_number" ).get_confidence_float(), 0.0 )


class TestDestructiveAndConfirmation( unittest.TestCase ):
    """
    is_destructive / needs_confirmation predicates.
    """

    def test_destructive_operations( self ):
        """Ensures delete, delete_list, and update are flagged destructive."""
        for op in ( "delete", "delete_list", "update" ):
            self.assertTrue( CRUDIntent( operation=op ).is_destructive() )

    def test_non_destructive_operations( self ):
        """Ensures read/add operations are not flagged destructive."""
        for op in ( "add", "query", "list_lists" ):
            self.assertFalse( CRUDIntent( operation=op ).is_destructive() )

    def test_needs_confirmation_explicit_true( self ):
        """Ensures requires_confirmation='true' forces confirmation on a safe op."""
        self.assertTrue( CRUDIntent( operation="add", requires_confirmation="TRUE" ).needs_confirmation() )

    def test_needs_confirmation_false_for_safe_op( self ):
        """Ensures a safe op with requires_confirmation='false' needs no confirmation."""
        self.assertFalse( CRUDIntent( operation="add", requires_confirmation="false" ).needs_confirmation() )

    def test_needs_confirmation_true_for_destructive_even_when_flag_false( self ):
        """Ensures destructive ops always need confirmation regardless of the flag."""
        self.assertTrue( CRUDIntent( operation="delete", requires_confirmation="false" ).needs_confirmation() )


class TestJsonFieldParsing( unittest.TestCase ):
    """
    get_match_dict / get_fields_dict / get_filters_dict and _parse_json_field.
    """

    def test_valid_fields_dict( self ):
        """Ensures a valid JSON object string parses into a dict."""
        intent = CRUDIntent( operation="add", fields='{"todo_item": "buy milk", "priority": "high"}' )
        self.assertEqual( intent.get_fields_dict(), { "todo_item": "buy milk", "priority": "high" } )

    def test_empty_brace_string_returns_empty_dict( self ):
        """Ensures the default '{}' string yields an empty dict."""
        self.assertEqual( CRUDIntent( operation="query" ).get_match_dict(), {} )

    def test_blank_string_returns_empty_dict( self ):
        """Ensures a whitespace-only JSON field yields an empty dict."""
        self.assertEqual( CRUDIntent( operation="query", filters="   " ).get_filters_dict(), {} )

    def test_non_dict_json_returns_empty_dict( self ):
        """Ensures valid JSON that is not an object (a list) yields an empty dict."""
        self.assertEqual( CRUDIntent( operation="query", fields="[1, 2, 3]" ).get_fields_dict(), {} )

    def test_invalid_json_returns_empty_dict( self ):
        """Ensures malformed JSON yields an empty dict (JSONDecodeError path)."""
        self.assertEqual( CRUDIntent( operation="query", filters="{not valid json}" ).get_filters_dict(), {} )


class TestLimitParsing( unittest.TestCase ):
    """
    get_limit_int — empty / positive / non-positive / invalid.
    """

    def test_empty_returns_none( self ):
        """Ensures an empty limit string returns None."""
        self.assertIsNone( CRUDIntent( operation="query", limit="" ).get_limit_int() )

    def test_whitespace_returns_none( self ):
        """Ensures a whitespace-only limit returns None."""
        self.assertIsNone( CRUDIntent( operation="query", limit="  " ).get_limit_int() )

    def test_positive_returns_int( self ):
        """Ensures a positive numeric string parses to that int."""
        self.assertEqual( CRUDIntent( operation="query", limit="10" ).get_limit_int(), 10 )

    def test_zero_or_negative_returns_none( self ):
        """Ensures a non-positive limit returns None."""
        self.assertIsNone( CRUDIntent( operation="query", limit="0" ).get_limit_int() )
        self.assertIsNone( CRUDIntent( operation="query", limit="-5" ).get_limit_int() )

    def test_non_numeric_returns_none( self ):
        """Ensures an unparseable limit returns None (ValueError path)."""
        self.assertIsNone( CRUDIntent( operation="query", limit="lots" ).get_limit_int() )


class TestXmlSerialization( unittest.TestCase ):
    """
    to_xml default root tag + from_xml round-trip + example factory.
    """

    def test_to_xml_uses_intent_root( self ):
        """Ensures to_xml defaults to the <intent> root element."""
        xml = CRUDIntent( operation="add", target_list="groceries" ).to_xml()
        self.assertIn( "<intent>", xml )
        self.assertIn( "<operation>add</operation>", xml )

    def test_round_trip_preserves_fields( self ):
        """Ensures to_xml → from_xml preserves operation, target_list, and raw_query."""
        original = CRUDIntent( operation="add", target_list="groceries", raw_query="add milk" )
        parsed   = CRUDIntent.from_xml( original.to_xml(), root_tag="intent" )
        self.assertEqual( parsed.operation, "add" )
        self.assertEqual( parsed.target_list, "groceries" )
        self.assertEqual( parsed.raw_query, "add milk" )

    def test_example_for_template_has_placeholder_values( self ):
        """Ensures the template example carries descriptive, non-data placeholders."""
        example = CRUDIntent.get_example_for_template()
        self.assertEqual( example.operation, "[operation name]" )
        self.assertEqual( example.get_confidence_float(), 0.0 )
        self.assertEqual( example.get_fields_dict(), {} )


if __name__ == "__main__":
    unittest.main()
