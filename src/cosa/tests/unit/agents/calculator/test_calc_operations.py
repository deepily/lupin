"""
Unit tests for cosa.agents.calculator.calc_operations.

Pure calculation functions (no LLM): arithmetic / convert / _convert_temperature /
compare_prices / mortgage. Tested exhaustively across success + every error branch. The only mock is a
targeted patch of _convert_temperature to exercise convert()'s defensive None-guard
(unreachable with valid canonical temperature units).

Created 2026-05-31 (CoSA coverage campaign, calculator package — Tiffany 💍). New file.
Extended 2026-08-24 with TestArithmetic (row 11af54f8 — Krishna 🦚).
"""

import unittest
from unittest.mock import patch

from cosa.agents.calculator import calc_operations as ops


class TestArithmetic( unittest.TestCase ):
    """Unit tests for arithmetic() — the calculator's own plain-math operation."""

    def test_subtract_two( self ):
        """Test a two-operand subtraction."""
        r = ops.arithmetic( [ 789, 456 ], "subtract" )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertEqual( r[ "result" ], 333 )
        self.assertEqual( r[ "expression" ], "789 minus 456" )

    def test_add_nary( self ):
        """Test add folds over more than two operands."""
        self.assertEqual( ops.arithmetic( [ 34, 67, 129 ], "add" )[ "result" ], 230 )

    def test_multiply_nary( self ):
        """Test multiply folds over more than two operands."""
        self.assertEqual( ops.arithmetic( [ 2, 3, 4 ], "multiply" )[ "result" ], 24 )

    def test_divide( self ):
        """Test an exact division returns an int."""
        self.assertEqual( ops.arithmetic( [ 45, 9 ], "divide" )[ "result" ], 5 )

    def test_divide_fractional( self ):
        """Test a non-integral division keeps its fraction."""
        self.assertEqual( ops.arithmetic( [ 10, 4 ], "divide" )[ "result" ], 2.5 )

    def test_modulo( self ):
        """Test a remainder with a non-zero answer."""
        self.assertEqual( ops.arithmetic( [ 345, 22 ], "modulo" )[ "result" ], 15 )

    def test_power( self ):
        """Test exponentiation."""
        self.assertEqual( ops.arithmetic( [ 2, 10 ], "power" )[ "result" ], 1024 )

    def test_folds_left_to_right( self ):
        """Test subtraction folds left, so [100, 20, 5] is (100-20)-5."""
        self.assertEqual( ops.arithmetic( [ 100, 20, 5 ], "subtract" )[ "result" ], 75 )

    def test_operator_case_insensitive( self ):
        """Test the operator is trimmed and lowercased before lookup."""
        self.assertEqual( ops.arithmetic( [ 3, 4 ], "  ADD  " )[ "operator" ], "add" )

    def test_string_operands_coerced( self ):
        """Test numeric strings are accepted as operands."""
        self.assertEqual( ops.arithmetic( [ "789", "456" ], "subtract" )[ "result" ], 333 )

    def test_none_operator_errors( self ):
        """Test a missing operator errors."""
        self.assertEqual( ops.arithmetic( [ 1, 2 ], None )[ "status" ], "error" )

    def test_unknown_operator_errors( self ):
        """Test an operator outside the table errors."""
        self.assertEqual( ops.arithmetic( [ 1, 2 ], "frobnicate" )[ "status" ], "error" )

    def test_too_few_operands_errors( self ):
        """Test fewer than two operands errors."""
        self.assertEqual( ops.arithmetic( [ 5 ], "add" )[ "status" ], "error" )

    def test_empty_operands_errors( self ):
        """Test an empty operand list errors."""
        self.assertEqual( ops.arithmetic( [], "add" )[ "status" ], "error" )

    def test_non_numeric_operand_errors( self ):
        """Test a non-numeric operand errors."""
        self.assertEqual( ops.arithmetic( [ 1, "banana" ], "add" )[ "status" ], "error" )

    def test_divide_by_zero_errors( self ):
        """Test division by zero errors instead of raising."""
        r = ops.arithmetic( [ 45, 0 ], "divide" )
        self.assertEqual( r[ "status" ], "error" )
        self.assertIn( "divide by zero", r[ "message" ] )

    def test_modulo_by_zero_errors( self ):
        """Test a remainder modulo zero errors instead of raising."""
        r = ops.arithmetic( [ 45, 0 ], "modulo" )
        self.assertEqual( r[ "status" ], "error" )
        self.assertIn( "modulo zero", r[ "message" ] )

    def test_zero_to_negative_power_errors( self ):
        """Test 0 ** -1 is reported out of range, not raised."""
        self.assertEqual( ops.arithmetic( [ 0, -1 ], "power" )[ "status" ], "error" )

    def test_overflow_errors( self ):
        """Test an overflowing power is reported out of range, not raised."""
        self.assertEqual( ops.arithmetic( [ 10, 1000000 ], "power" )[ "status" ], "error" )

    def test_complex_result_errors( self ):
        """Test a negative base with a fractional exponent has no real answer."""
        r = ops.arithmetic( [ -8, 0.5 ], "power" )
        self.assertEqual( r[ "status" ], "error" )
        self.assertIn( "no real-number answer", r[ "message" ] )


class TestConvert( unittest.TestCase ):
    """Unit tests for convert() and _convert_temperature()."""

    def test_convert_none_value_errors( self ):
        """Test a None value short-circuits to an error result."""
        self.assertEqual( ops.convert( None, "km", "mile" )[ "status" ], "error" )

    def test_convert_same_unit_identity( self ):
        """Test converting between identical units returns the rounded value."""
        r = ops.convert( 5, "meter", "meter" )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertEqual( r[ "result" ], 5 )

    def test_convert_ratio_category( self ):
        """Test hub-and-spoke ratio conversion (km → mile)."""
        r = ops.convert( 10, "kilometers", "miles" )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertAlmostEqual( r[ "result" ], 6.2137, places=3 )

    def test_convert_unknown_from_unit( self ):
        """Test an unknown source unit errors."""
        self.assertEqual( ops.convert( 1, "bogus", "meter" )[ "status" ], "error" )

    def test_convert_unknown_to_unit( self ):
        """Test an unknown target unit errors."""
        self.assertEqual( ops.convert( 1, "meter", "bogus" )[ "status" ], "error" )

    def test_convert_cross_category_errors( self ):
        """Test converting across categories (length → volume) errors."""
        self.assertEqual( ops.convert( 1, "km", "gallon" )[ "status" ], "error" )

    def test_convert_temperature_ok( self ):
        """Test a temperature conversion (100°F → ~37.78°C)."""
        r = ops.convert( 100, "fahrenheit", "celsius" )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertAlmostEqual( r[ "result" ], 37.78, places=2 )

    def test_convert_temperature_none_guard( self ):
        """
        Test convert()'s defensive guard when temperature conversion returns None.

        _convert_temperature is patched to None (unreachable with valid canonical
        temperature units) to exercise the error branch.
        """
        with patch( "cosa.agents.calculator.calc_operations._convert_temperature", return_value=None ):
            self.assertEqual( ops.convert( 0, "celsius", "kelvin" )[ "status" ], "error" )

    def test_private_temperature_all_pairs( self ):
        """Test _convert_temperature across every supported from/to pair."""
        self.assertEqual( ops._convert_temperature( 0, "celsius", "celsius" ), 0 )
        self.assertAlmostEqual( ops._convert_temperature( 0, "celsius", "fahrenheit" ), 32 )
        self.assertAlmostEqual( ops._convert_temperature( 0, "celsius", "kelvin" ), 273.15 )
        self.assertAlmostEqual( ops._convert_temperature( 32, "fahrenheit", "celsius" ), 0 )
        self.assertAlmostEqual( ops._convert_temperature( 273.15, "kelvin", "celsius" ), 0 )

    def test_private_temperature_unsupported_units_return_none( self ):
        """Test _convert_temperature returns None for unsupported from/to units."""
        self.assertIsNone( ops._convert_temperature( 0, "rankine", "celsius" ) )
        self.assertIsNone( ops._convert_temperature( 0, "celsius", "rankine" ) )


class TestComparePrices( unittest.TestCase ):
    """Unit tests for compare_prices()."""

    def test_too_few_items_errors( self ):
        """Test fewer than two items errors."""
        self.assertEqual( ops.compare_prices( [ { "name": "A" } ] )[ "status" ], "error" )

    def test_invalid_price_errors( self ):
        """Test a non-numeric price errors."""
        items = [
            { "name": "A", "price": "abc", "quantity": 1, "unit": "oz" },
            { "name": "B", "price": 2.0,   "quantity": 1, "unit": "oz" },
        ]
        self.assertEqual( ops.compare_prices( items )[ "status" ], "error" )

    def test_non_positive_quantity_errors( self ):
        """Test a non-positive quantity errors."""
        items = [
            { "name": "A", "price": 1.0, "quantity": 0, "unit": "oz" },
            { "name": "B", "price": 2.0, "quantity": 1, "unit": "oz" },
        ]
        self.assertEqual( ops.compare_prices( items )[ "status" ], "error" )

    def test_unknown_unit_errors( self ):
        """Test an unknown unit errors."""
        items = [
            { "name": "A", "price": 1.0, "quantity": 1, "unit": "bogus" },
            { "name": "B", "price": 2.0, "quantity": 1, "unit": "oz" },
        ]
        self.assertEqual( ops.compare_prices( items )[ "status" ], "error" )

    def test_temperature_unit_errors( self ):
        """Test temperature units are rejected for price comparison."""
        items = [
            { "name": "A", "price": 1.0, "quantity": 1, "unit": "celsius" },
            { "name": "B", "price": 2.0, "quantity": 1, "unit": "celsius" },
        ]
        self.assertEqual( ops.compare_prices( items )[ "status" ], "error" )

    def test_mismatched_categories_error( self ):
        """Test mixing categories (mass + volume) errors."""
        items = [
            { "name": "A", "price": 1.0, "quantity": 1, "unit": "oz" },
            { "name": "B", "price": 2.0, "quantity": 1, "unit": "liter" },
        ]
        self.assertEqual( ops.compare_prices( items )[ "status" ], "error" )

    def test_success_sorts_by_unit_price( self ):
        """
        Test a valid comparison returns items sorted cheapest-first with unit prices.

        Ensures:
            - The cheaper per-unit item is reported as 'cheapest'
            - Internal factor_to_base is stripped from the result items
        """
        items = [
            { "name": "Brand A", "price": 3.49, "quantity": 12, "unit": "oz" },
            { "name": "Brand B", "price": 5.99, "quantity": 24, "unit": "oz" },
        ]
        r = ops.compare_prices( items )

        self.assertEqual( r[ "status" ], "ok" )
        self.assertEqual( r[ "cheapest" ], "Brand B" )
        self.assertEqual( r[ "common_unit" ], "ounce" )
        self.assertNotIn( "factor_to_base", r[ "items" ][ 0 ] )
        self.assertIn( "unit_price", r[ "items" ][ 0 ] )


class TestMortgage( unittest.TestCase ):
    """Unit tests for mortgage()."""

    def test_invalid_principal( self ):
        """Test a non-positive principal errors."""
        self.assertEqual( ops.mortgage( 0, 6.5, 30 )[ "status" ], "error" )

    def test_invalid_rate( self ):
        """Test a non-positive annual rate errors."""
        self.assertEqual( ops.mortgage( 300000, 0, 30 )[ "status" ], "error" )

    def test_invalid_term( self ):
        """Test a non-positive term errors."""
        self.assertEqual( ops.mortgage( 300000, 6.5, 0 )[ "status" ], "error" )

    def test_negative_down_payment_errors( self ):
        """Test a negative down payment errors."""
        self.assertEqual( ops.mortgage( 300000, 6.5, 30, down_payment=-1 )[ "status" ], "error" )

    def test_down_payment_none_defaults_zero( self ):
        """Test a None down payment defaults to zero and computes normally."""
        r = ops.mortgage( 300000, 6.5, 30, down_payment=None )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertEqual( r[ "down_payment" ], 0 )

    def test_down_payment_exceeds_principal_errors( self ):
        """Test a down payment >= principal errors (non-positive loan)."""
        self.assertEqual( ops.mortgage( 100000, 6.5, 30, down_payment=100000 )[ "status" ], "error" )

    def test_success_amortization( self ):
        """Test a standard amortization computes the expected monthly payment."""
        r = ops.mortgage( 300000, 6.5, 30 )
        self.assertEqual( r[ "status" ], "ok" )
        self.assertAlmostEqual( r[ "monthly_payment" ], 1896.20, delta=1.0 )
        self.assertEqual( r[ "loan_amount" ], 300000.0 )


if __name__ == "__main__":
    unittest.main()
