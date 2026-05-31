"""
Unit tests for cosa.agents.calculator.dispatcher.

Pure routing + TTS-formatting functions. Tests cover dispatch routing (all ops +
unknown), format_result_for_voice (error / each op / fallback), the display-rounding
and pluralization branches (exercised directly), and extract_calc_intent_xml.

Created 2026-05-31 (CoSA coverage campaign, calculator package — Tiffany 💍). New file.
"""

import unittest

from cosa.agents.calculator import dispatcher as dp
from cosa.agents.calculator.xml_models import CalcIntent


class TestDispatch( unittest.TestCase ):
    """Unit tests for dispatch()."""

    def test_dispatch_convert( self ):
        """Test convert routing returns a conversion result (debug on)."""
        intent = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="miles" )
        r = dp.dispatch( intent, debug=True )
        self.assertEqual( r[ "status" ], "ok" )

    def test_dispatch_compare_prices( self ):
        """Test compare_prices routing returns a comparison result."""
        items = '[{"name":"A","price":1,"quantity":1,"unit":"oz"},{"name":"B","price":2,"quantity":1,"unit":"oz"}]'
        intent = CalcIntent( operation="compare_prices", items=items )
        r = dp.dispatch( intent )
        self.assertEqual( r[ "status" ], "ok" )

    def test_dispatch_mortgage( self ):
        """Test mortgage routing returns an amortization result."""
        intent = CalcIntent( operation="mortgage", principal="300000", annual_rate="6.5", term_years="30" )
        r = dp.dispatch( intent )
        self.assertEqual( r[ "status" ], "ok" )

    def test_dispatch_unknown_raises( self ):
        """Test an unrecognized operation raises ValueError."""
        intent = CalcIntent( operation="unsupported" )
        with self.assertRaises( ValueError ):
            dp.dispatch( intent )


class TestFormatResultForVoice( unittest.TestCase ):
    """Unit tests for format_result_for_voice() and the per-op formatters."""

    def test_error_status( self ):
        """Test an error result yields an apologetic message."""
        voice = dp.format_result_for_voice( { "status": "error", "message": "bad" }, "convert" )
        self.assertIn( "Sorry", voice )

    def test_convert_formatting( self ):
        """Test convert formatting produces a natural conversion phrase."""
        result = { "status": "ok", "from_value": 10, "from_unit": "km", "to_unit": "mile", "result": 6.21 }
        voice = dp.format_result_for_voice( result, "convert" )
        self.assertIn( "kilometers", voice )
        self.assertIn( "miles", voice )

    def test_compare_prices_formatting( self ):
        """Test compare_prices formatting names the cheapest option."""
        result = {
            "status": "ok", "common_unit": "ounce", "cheapest": "B",
            "items": [
                { "name": "B", "unit_price": 0.25 },
                { "name": "A", "unit_price": 0.29 },
            ],
        }
        voice = dp.format_result_for_voice( result, "compare_prices" )
        self.assertIn( "cheaper", voice )

    def test_mortgage_formatting( self ):
        """Test mortgage formatting reports payment + interest."""
        result = {
            "status": "ok", "monthly_payment": 1896.20, "total_interest": 382631.0,
            "loan_amount": 300000.0, "term_years": 30,
        }
        voice = dp.format_result_for_voice( result, "mortgage" )
        self.assertIn( "monthly payment", voice )

    def test_fallback_with_and_without_message( self ):
        """Test the fallback branch for an unrecognized op (message present vs absent)."""
        self.assertEqual(
            dp.format_result_for_voice( { "status": "ok", "message": "done" }, "weird-op" ),
            "done"
        )
        self.assertIn(
            "status ok",
            dp.format_result_for_voice( { "status": "ok" }, "weird-op" )
        )


class TestConvertDisplayRounding( unittest.TestCase ):
    """Unit tests for _format_convert_for_voice display-rounding branches."""

    def _voice( self, converted, from_value=2 ):
        result = { "from_value": from_value, "from_unit": "mile", "to_unit": "km", "result": converted }
        return dp._format_convert_for_voice( result )

    def test_integer_result( self ):
        """Test an integral result is rendered without decimals."""
        self.assertIn( "16", self._voice( 16.0 ) )

    def test_large_result_no_decimals( self ):
        """Test a result >= 100 is rendered with no decimals."""
        self.assertIn( "151", self._voice( 150.7 ) )

    def test_medium_result_one_decimal( self ):
        """Test a result >= 10 is rendered with one decimal."""
        self.assertIn( "50.7", self._voice( 50.7 ) )

    def test_small_result_two_decimals( self ):
        """Test a small result is rendered with two decimals."""
        self.assertIn( "6.21", self._voice( 6.214 ) )

    def test_integer_from_value_display( self ):
        """Test an integral from_value is rendered without a decimal point."""
        voice = self._voice( 6.21, from_value=10 )
        self.assertIn( "10 miles", voice )

    def test_float_from_value_display( self ):
        """Test a non-integral from_value keeps its decimal form."""
        voice = self._voice( 6.21, from_value=10.5 )
        self.assertIn( "10.5", voice )


class TestComparePricesFormatting( unittest.TestCase ):
    """Unit tests for _format_compare_prices_for_voice (2-item vs 3+-item paths)."""

    def test_two_items_versus_phrase( self ):
        """Test the 2-item comparison uses the 'versus' phrasing."""
        result = {
            "common_unit": "ounce", "cheapest": "B",
            "items": [ { "name": "B", "unit_price": 0.25 }, { "name": "A", "unit_price": 0.29 } ],
        }
        voice = dp._format_compare_prices_for_voice( result )
        self.assertIn( "versus", voice )

    def test_three_items_list_phrase( self ):
        """Test the 3+-item comparison lists the remaining options."""
        result = {
            "common_unit": "ounce", "cheapest": "C",
            "items": [
                { "name": "C", "unit_price": 0.20 },
                { "name": "B", "unit_price": 0.25 },
                { "name": "A", "unit_price": 0.29 },
            ],
        }
        voice = dp._format_compare_prices_for_voice( result )
        self.assertIn( "cheapest is C", voice )


class TestPluralizeUnit( unittest.TestCase ):
    """Unit tests for _pluralize_unit across all display branches."""

    def test_display_name_singular_and_plural( self ):
        """Test special display names pick singular vs plural by value."""
        self.assertEqual( dp._pluralize_unit( "km", 1 ), "kilometer" )
        self.assertEqual( dp._pluralize_unit( "km", 2 ), "kilometers" )

    def test_default_singular( self ):
        """Test a value of 1 returns the bare unit."""
        self.assertEqual( dp._pluralize_unit( "mile", 1 ), "mile" )

    def test_default_already_plural( self ):
        """Test a unit already ending in 's' is left unchanged when plural."""
        self.assertEqual( dp._pluralize_unit( "xs", 2 ), "xs" )

    def test_default_foot_to_feet( self ):
        """Test 'foot' pluralizes irregularly to 'feet'."""
        self.assertEqual( dp._pluralize_unit( "foot", 2 ), "feet" )

    def test_default_inch_to_inches( self ):
        """Test 'inch' pluralizes irregularly to 'inches'."""
        self.assertEqual( dp._pluralize_unit( "inch", 2 ), "inches" )

    def test_default_add_s( self ):
        """Test a regular unit gets a trailing 's' when plural."""
        self.assertEqual( dp._pluralize_unit( "mile", 2 ), "miles" )


class TestExtractCalcIntentXml( unittest.TestCase ):
    """Unit tests for extract_calc_intent_xml()."""

    def test_empty_raises( self ):
        """Test an empty/whitespace response raises ValueError."""
        with self.assertRaises( ValueError ):
            dp.extract_calc_intent_xml( "   " )

    def test_clean_xml( self ):
        """Test a clean XML block is returned verbatim."""
        xml = "<calc_intent><operation>convert</operation></calc_intent>"
        self.assertIn( "<operation>convert</operation>", dp.extract_calc_intent_xml( xml ) )

    def test_markdown_fenced_xml( self ):
        """Test XML wrapped in markdown fences is extracted."""
        fenced = "```xml\n<calc_intent><operation>mortgage</operation></calc_intent>\n```"
        self.assertIn( "<operation>mortgage</operation>", dp.extract_calc_intent_xml( fenced ) )

    def test_no_block_raises( self ):
        """Test a response without a calc_intent block raises ValueError."""
        with self.assertRaises( ValueError ):
            dp.extract_calc_intent_xml( "no xml here at all" )


if __name__ == "__main__":
    unittest.main()
