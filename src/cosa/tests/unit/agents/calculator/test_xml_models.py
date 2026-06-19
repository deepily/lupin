"""
Unit tests for cosa.agents.calculator.xml_models.CalcIntent.

CalcIntent is a BaseXMLModel carrying LLM-extracted calculator intent as string
fields. Tests cover the None-coercion validator, every numeric/JSON getter (success
+ parse-failure branches), XML round-trip, and the template-example factory.

Created 2026-05-31 (CoSA coverage campaign, calculator package — Tiffany 💍). New file.
"""

import unittest

from cosa.agents.calculator.xml_models import CalcIntent


class TestCalcIntent( unittest.TestCase ):
    """
    Comprehensive unit tests for CalcIntent.

    Ensures:
        - None→"" coercion at the field boundary
        - Each getter parses valid input and degrades gracefully on bad input
        - to_xml / get_example_for_template behave per contract
    """

    def test_none_coercion_to_empty_string( self ):
        """Test None values on non-operation fields coerce to empty strings."""
        intent = CalcIntent( operation="convert", value=None, from_unit=None )
        self.assertEqual( intent.value, "" )
        self.assertEqual( intent.from_unit, "" )

    def test_non_none_values_pass_through( self ):
        """Test ordinary values pass through the validator unchanged."""
        intent = CalcIntent( operation="convert", value="10", from_unit="km" )
        self.assertEqual( intent.value, "10" )
        self.assertEqual( intent.from_unit, "km" )

    def test_get_confidence_float_valid_and_clamped( self ):
        """Test confidence parses and clamps to [0.0, 1.0]."""
        self.assertEqual( CalcIntent( operation="convert", confidence="0.5" ).get_confidence_float(), 0.5 )
        self.assertEqual( CalcIntent( operation="convert", confidence="5.0" ).get_confidence_float(), 1.0 )
        self.assertEqual( CalcIntent( operation="convert", confidence="-1" ).get_confidence_float(), 0.0 )

    def test_get_confidence_float_parse_failure( self ):
        """Test a non-numeric confidence returns 0.0."""
        self.assertEqual( CalcIntent( operation="convert", confidence="high" ).get_confidence_float(), 0.0 )

    def test_get_value_float_valid_and_failure( self ):
        """Test value parsing for numeric and non-numeric input."""
        self.assertEqual( CalcIntent( operation="convert", value="42.5" ).get_value_float(), 42.5 )
        self.assertEqual( CalcIntent( operation="convert", value="abc" ).get_value_float(), 0.0 )

    def test_get_items_list_branches( self ):
        """Test items parsing across empty, valid, non-list JSON, and invalid JSON."""
        self.assertEqual( CalcIntent( operation="compare_prices", items="" ).get_items_list(), [] )
        self.assertEqual( CalcIntent( operation="compare_prices", items="[]" ).get_items_list(), [] )

        valid = '[{"name": "A", "price": 1.0, "quantity": 2, "unit": "oz"}]'
        parsed = CalcIntent( operation="compare_prices", items=valid ).get_items_list()
        self.assertEqual( len( parsed ), 1 )
        self.assertEqual( parsed[ 0 ][ "name" ], "A" )

        # Valid JSON but not a list → []
        self.assertEqual( CalcIntent( operation="compare_prices", items='{"a": 1}' ).get_items_list(), [] )
        # Invalid JSON → []
        self.assertEqual( CalcIntent( operation="compare_prices", items="not json" ).get_items_list(), [] )

    def test_get_principal_and_rate_floats( self ):
        """Test principal / annual_rate parsing (valid + failure)."""
        self.assertEqual( CalcIntent( operation="mortgage", principal="300000" ).get_principal_float(), 300000.0 )
        self.assertEqual( CalcIntent( operation="mortgage", principal="x" ).get_principal_float(), 0.0 )
        self.assertEqual( CalcIntent( operation="mortgage", annual_rate="6.5" ).get_annual_rate_float(), 6.5 )
        self.assertEqual( CalcIntent( operation="mortgage", annual_rate="" ).get_annual_rate_float(), 0.0 )

    def test_get_term_years_int_branches( self ):
        """Test term_years parsing: positive, non-positive→0, and parse-failure→0."""
        self.assertEqual( CalcIntent( operation="mortgage", term_years="30" ).get_term_years_int(), 30 )
        self.assertEqual( CalcIntent( operation="mortgage", term_years="0" ).get_term_years_int(), 0 )
        self.assertEqual( CalcIntent( operation="mortgage", term_years="abc" ).get_term_years_int(), 0 )

    def test_get_down_payment_float_branches( self ):
        """Test down_payment parsing: empty→0.0, valid, and parse-failure→0.0."""
        self.assertEqual( CalcIntent( operation="mortgage", down_payment="" ).get_down_payment_float(), 0.0 )
        self.assertEqual( CalcIntent( operation="mortgage", down_payment="50000" ).get_down_payment_float(), 50000.0 )
        self.assertEqual( CalcIntent( operation="mortgage", down_payment="nope" ).get_down_payment_float(), 0.0 )

    def test_to_xml_uses_calc_intent_root( self ):
        """Test to_xml serializes with the <calc_intent> root and field tags."""
        xml = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="mile" ).to_xml()
        self.assertIn( "<calc_intent>", xml )
        self.assertIn( "<operation>convert</operation>", xml )

    def test_xml_round_trip( self ):
        """Test from_xml reconstructs the intent fields."""
        original = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="mile" )
        parsed   = CalcIntent.from_xml( original.to_xml(), root_tag="calc_intent" )
        self.assertEqual( parsed.operation, "convert" )
        self.assertEqual( parsed.value, "10" )
        self.assertEqual( parsed.from_unit, "km" )

    def test_get_example_for_template_has_placeholders( self ):
        """Test the template example carries descriptive placeholder values."""
        example = CalcIntent.get_example_for_template()
        self.assertTrue( example.operation.startswith( "[operation" ) )
        self.assertIn( "VALID_OPERATIONS", dir( CalcIntent ) )


if __name__ == "__main__":
    unittest.main()
