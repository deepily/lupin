#!/usr/bin/env python3
"""
Unit tests for the Everyday Calculator agent.

Tests all three domains:
    - Unit conversions (length, mass, volume, temperature)
    - Price comparison (unit price normalization)
    - Mortgage calculation (amortization formula)

Also tests:
    - CalcIntent XML model (parsing, round-trip, field extraction)
    - Dispatcher (routing, voice formatting, XML extraction)
    - Conversion tables (alias resolution, category lookup)
"""

import json
import math
import pytest

from cosa.agents.calculator.conversion_tables import (
    resolve_alias, find_category, LENGTH, MASS, VOLUME, TEMPERATURE, ALIASES
)
from cosa.agents.calculator.calc_operations import (
    arithmetic, ARITHMETIC_OPERATORS,
    convert, compare_prices, mortgage, _convert_temperature
)
from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.calculator.dispatcher import (
    dispatch, format_result_for_voice, extract_calc_intent_xml, _pluralize_unit
)


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Conversion Tables
# ═════════════════════════════════════════════════════════════════════════

class TestConversionTables:
    """Tests for conversion_tables.py — alias resolution and category lookup."""

    def test_alias_resolution_length( self ):
        assert resolve_alias( "kilometers" ) == "km"
        assert resolve_alias( "miles" ) == "mile"
        assert resolve_alias( "feet" ) == "foot"
        assert resolve_alias( "inches" ) == "inch"
        assert resolve_alias( "yards" ) == "yard"
        assert resolve_alias( "centimeters" ) == "cm"
        assert resolve_alias( "millimeters" ) == "mm"
        assert resolve_alias( "metres" ) == "meter"

    def test_alias_resolution_mass( self ):
        assert resolve_alias( "grams" ) == "gram"
        assert resolve_alias( "kilograms" ) == "kg"
        assert resolve_alias( "pounds" ) == "pound"
        assert resolve_alias( "lbs" ) == "pound"
        assert resolve_alias( "ounces" ) == "ounce"
        assert resolve_alias( "oz" ) == "ounce"

    def test_alias_resolution_volume( self ):
        assert resolve_alias( "liters" ) == "liter"
        assert resolve_alias( "gallons" ) == "gallon"
        assert resolve_alias( "cups" ) == "cup"
        assert resolve_alias( "fluid ounces" ) == "fl_oz"
        assert resolve_alias( "milliliters" ) == "ml"

    def test_alias_resolution_temperature( self ):
        assert resolve_alias( "celsius" ) == "celsius"
        assert resolve_alias( "fahrenheit" ) == "fahrenheit"
        assert resolve_alias( "centigrade" ) == "celsius"
        assert resolve_alias( "c" ) == "celsius"
        assert resolve_alias( "f" ) == "fahrenheit"

    def test_alias_case_insensitive( self ):
        assert resolve_alias( "KILOMETERS" ) == "km"
        assert resolve_alias( "Miles" ) == "mile"
        assert resolve_alias( "CELSIUS" ) == "celsius"

    def test_alias_unknown_returns_lowered( self ):
        assert resolve_alias( "unknown_unit" ) == "unknown_unit"
        assert resolve_alias( "FOOBAR" ) == "foobar"

    def test_category_lookup_length( self ):
        cat_dict, cat_name = find_category( "km" )
        assert cat_name == "length"
        assert cat_dict is LENGTH

    def test_category_lookup_mass( self ):
        cat_dict, cat_name = find_category( "ounce" )
        assert cat_name == "mass"
        assert cat_dict is MASS

    def test_category_lookup_volume( self ):
        cat_dict, cat_name = find_category( "gallon" )
        assert cat_name == "volume"
        assert cat_dict is VOLUME

    def test_category_lookup_temperature( self ):
        cat_dict, cat_name = find_category( "celsius" )
        assert cat_name == "temperature"
        assert cat_dict is TEMPERATURE

    def test_category_lookup_unknown( self ):
        cat_dict, cat_name = find_category( "unknown" )
        assert cat_dict is None
        assert cat_name is None


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Unit Conversions — Known Facts
# ═════════════════════════════════════════════════════════════════════════

class TestUnitConversions:
    """Tests for calc_operations.convert() — known reference values."""

    def test_km_to_miles( self ):
        """1 km = 0.621371 miles (known fact)."""
        result = convert( 1, "km", "miles" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 0.6214 ) < 0.001

    def test_miles_to_km( self ):
        """1 mile = 1.60934 km (known fact)."""
        result = convert( 1, "miles", "km" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 1.6093 ) < 0.001

    def test_10_km_to_miles( self ):
        """10 km ≈ 6.2137 miles."""
        result = convert( 10, "kilometers", "miles" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 6.2137 ) < 0.001

    def test_inch_to_cm( self ):
        """1 inch = 2.54 cm (exact definition)."""
        result = convert( 1, "inch", "cm" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 2.54 ) < 0.01

    def test_foot_to_meters( self ):
        """1 foot = 0.3048 meters (exact definition)."""
        result = convert( 1, "foot", "meter" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 0.3048 ) < 0.001

    def test_pound_to_ounces( self ):
        """1 pound = 16 ounces (known fact)."""
        result = convert( 1, "pound", "ounce" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 16.0 ) < 0.01

    def test_kg_to_pounds( self ):
        """1 kg ≈ 2.2046 pounds (known fact)."""
        result = convert( 1, "kg", "pounds" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 2.2046 ) < 0.001

    def test_gallon_to_liters( self ):
        """1 gallon ≈ 3.7854 liters (known fact)."""
        result = convert( 1, "gallon", "liter" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 3.7854 ) < 0.001

    def test_cup_to_ml( self ):
        """1 cup ≈ 236.588 ml (known fact)."""
        result = convert( 1, "cup", "ml" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 236.588 ) < 1.0

    def test_500g_to_pounds( self ):
        """500 grams ≈ 1.1023 pounds."""
        result = convert( 500, "grams", "pounds" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 1.1023 ) < 0.01

    def test_same_unit_identity( self ):
        """Converting a unit to itself should return the same value."""
        result = convert( 42, "meter", "meter" )
        assert result[ "status" ] == "ok"
        assert result[ "result" ] == 42

    def test_cross_category_error( self ):
        """Cannot convert between different categories."""
        result = convert( 1, "km", "gallon" )
        assert result[ "status" ] == "error"
        assert "Cannot convert" in result[ "message" ]

    def test_unknown_unit_error( self ):
        """Unknown unit should return error."""
        result = convert( 1, "furlongs", "miles" )
        assert result[ "status" ] == "error"
        assert "Unknown unit" in result[ "message" ]

    def test_none_value_error( self ):
        """None value should return error."""
        result = convert( None, "km", "miles" )
        assert result[ "status" ] == "error"


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Temperature Conversions — Known Facts
# ═════════════════════════════════════════════════════════════════════════

class TestTemperatureConversions:
    """Tests for temperature conversions — well-known reference points."""

    def test_boiling_point_c_to_f( self ):
        """100°C = 212°F (boiling point of water)."""
        result = convert( 100, "celsius", "fahrenheit" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 212.0 ) < 0.01

    def test_freezing_point_c_to_f( self ):
        """0°C = 32°F (freezing point of water)."""
        result = convert( 0, "celsius", "fahrenheit" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 32.0 ) < 0.01

    def test_body_temp_f_to_c( self ):
        """98.6°F ≈ 37°C (human body temperature)."""
        result = convert( 98.6, "fahrenheit", "celsius" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 37.0 ) < 0.01

    def test_72f_to_c( self ):
        """72°F ≈ 22.22°C (room temperature)."""
        result = convert( 72, "fahrenheit", "celsius" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 22.22 ) < 0.01

    def test_absolute_zero_k_to_c( self ):
        """0 K = -273.15°C (absolute zero)."""
        result = convert( 0, "kelvin", "celsius" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - ( -273.15 ) ) < 0.01

    def test_c_to_k( self ):
        """0°C = 273.15 K."""
        result = convert( 0, "celsius", "kelvin" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 273.15 ) < 0.01

    def test_minus_40_same_cf( self ):
        """-40°C = -40°F (the crossover point)."""
        result = convert( -40, "celsius", "fahrenheit" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - ( -40.0 ) ) < 0.01

    def test_f_to_k( self ):
        """32°F = 273.15 K (freezing via Kelvin)."""
        result = convert( 32, "fahrenheit", "kelvin" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 273.15 ) < 0.01


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Price Comparison
# ═════════════════════════════════════════════════════════════════════════

class TestPriceComparison:
    """Tests for calc_operations.compare_prices()."""

    def test_same_unit_different_quantity( self ):
        """12 oz at $3.49 vs 24 oz at $5.99 — larger is cheaper per oz."""
        items = [
            { "name": "Small", "price": 3.49, "quantity": 12, "unit": "oz" },
            { "name": "Large", "price": 5.99, "quantity": 24, "unit": "oz" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "Large"

    def test_gallon_vs_half_gallon( self ):
        """Gallon at $4.29 vs half gallon at $2.89 — gallon is cheaper per unit."""
        items = [
            { "name": "Gallon",      "price": 4.29, "quantity": 1.0, "unit": "gallon" },
            { "name": "Half gallon", "price": 2.89, "quantity": 0.5, "unit": "gallon" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "Gallon"

    def test_mixed_units_same_category( self ):
        """1 kg at $5 vs 1 lb at $3 — compare mass across different units."""
        items = [
            { "name": "Kg pack",  "price": 5.0,  "quantity": 1, "unit": "kg" },
            { "name": "Lb pack",  "price": 3.0,  "quantity": 1, "unit": "lb" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "ok"
        # 1 kg = ~35.27 oz → $5/35.27 = $0.1418/oz
        # 1 lb = 16 oz → $3/16 = $0.1875/oz
        # Kg pack should be cheaper
        assert result[ "cheapest" ] == "Kg pack"

    def test_three_items( self ):
        """Three items should be sorted by unit price."""
        items = [
            { "name": "A", "price": 10.0, "quantity": 10, "unit": "oz" },
            { "name": "B", "price": 5.0,  "quantity": 10, "unit": "oz" },
            { "name": "C", "price": 8.0,  "quantity": 10, "unit": "oz" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "B"
        assert result[ "items" ][ 0 ][ "name" ] == "B"
        assert result[ "items" ][ 1 ][ "name" ] == "C"
        assert result[ "items" ][ 2 ][ "name" ] == "A"

    def test_single_item_error( self ):
        """Need at least 2 items to compare."""
        items = [ { "name": "Only", "price": 5.0, "quantity": 10, "unit": "oz" } ]
        result = compare_prices( items )
        assert result[ "status" ] == "error"

    def test_cross_category_error( self ):
        """Cannot compare mass vs volume."""
        items = [
            { "name": "A", "price": 5.0, "quantity": 10, "unit": "oz" },
            { "name": "B", "price": 5.0, "quantity": 10, "unit": "ml" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "error"
        assert "Cannot compare" in result[ "message" ]

    def test_zero_quantity_error( self ):
        """Zero quantity should return error."""
        items = [
            { "name": "A", "price": 5.0, "quantity": 0,  "unit": "oz" },
            { "name": "B", "price": 5.0, "quantity": 10, "unit": "oz" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "error"

    def test_temperature_units_error( self ):
        """Temperature units cannot be used for price comparison."""
        items = [
            { "name": "A", "price": 5.0, "quantity": 10, "unit": "celsius" },
            { "name": "B", "price": 5.0, "quantity": 10, "unit": "celsius" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "error"
        assert "Temperature" in result[ "message" ]


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Mortgage Calculator
# ═════════════════════════════════════════════════════════════════════════

class TestMortgage:
    """Tests for calc_operations.mortgage()."""

    def test_standard_30yr( self ):
        """$300k at 6.5% for 30 years ≈ $1896.20/month."""
        result = mortgage( 300000, 6.5, 30 )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 1896.20 ) < 1.0
        assert result[ "loan_amount" ] == 300000.0

    def test_with_down_payment( self ):
        """$300k with $50k down = $250k loan."""
        result = mortgage( 300000, 6.5, 30, down_payment=50000 )
        assert result[ "status" ] == "ok"
        assert result[ "loan_amount" ] == 250000.0
        assert result[ "monthly_payment" ] < 1896.20  # Less than without down payment

    def test_15yr_higher_payment( self ):
        """15-year mortgage should have higher monthly but less total interest."""
        result_30 = mortgage( 300000, 6.5, 30 )
        result_15 = mortgage( 300000, 6.5, 15 )
        assert result_15[ "monthly_payment" ] > result_30[ "monthly_payment" ]
        assert result_15[ "total_interest" ] < result_30[ "total_interest" ]

    def test_total_interest_calculation( self ):
        """Total interest = total paid - loan amount."""
        result = mortgage( 300000, 6.5, 30 )
        expected_interest = result[ "total_paid" ] - result[ "loan_amount" ]
        assert abs( result[ "total_interest" ] - expected_interest ) < 0.01

    def test_total_paid_calculation( self ):
        """Total paid = monthly payment × number of payments (rounding tolerance for 2-decimal monthly)."""
        result = mortgage( 300000, 6.5, 30 )
        expected_total = result[ "monthly_payment" ] * 360
        assert abs( result[ "total_paid" ] - expected_total ) < 2.0  # Rounding accumulates over 360 payments

    def test_zero_principal_error( self ):
        result = mortgage( 0, 6.5, 30 )
        assert result[ "status" ] == "error"

    def test_negative_principal_error( self ):
        result = mortgage( -100000, 6.5, 30 )
        assert result[ "status" ] == "error"

    def test_zero_rate_error( self ):
        result = mortgage( 300000, 0, 30 )
        assert result[ "status" ] == "error"

    def test_zero_term_error( self ):
        result = mortgage( 300000, 6.5, 0 )
        assert result[ "status" ] == "error"

    def test_down_payment_exceeds_principal( self ):
        result = mortgage( 300000, 6.5, 30, down_payment=400000 )
        assert result[ "status" ] == "error"

    def test_negative_down_payment_error( self ):
        result = mortgage( 300000, 6.5, 30, down_payment=-10000 )
        assert result[ "status" ] == "error"

    def test_small_loan( self ):
        """$10k at 5% for 5 years — sanity check."""
        result = mortgage( 10000, 5.0, 5 )
        assert result[ "status" ] == "ok"
        # Known: ~$188.71/month
        assert abs( result[ "monthly_payment" ] - 188.71 ) < 1.0


# ═════════════════════════════════════════════════════════════════════════
# Test Class: CalcIntent XML Model
# ═════════════════════════════════════════════════════════════════════════

class TestCalcIntentModel:
    """Tests for CalcIntent XML model (xml_models.py)."""

    def test_create_convert_intent( self ):
        intent = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="miles" )
        assert intent.operation == "convert"
        assert intent.get_value_float() == 10.0
        assert intent.from_unit == "km"
        assert intent.to_unit == "miles"

    def test_create_mortgage_intent( self ):
        intent = CalcIntent( operation="mortgage", principal="300000", annual_rate="6.5", term_years="30" )
        assert intent.get_principal_float() == 300000.0
        assert intent.get_annual_rate_float() == 6.5
        assert intent.get_term_years_int() == 30
        assert intent.get_down_payment_float() == 0.0

    def test_items_list_parsing( self ):
        items_json = '[{"name": "A", "price": 3.49, "quantity": 12, "unit": "oz"}]'
        intent = CalcIntent( operation="compare_prices", items=items_json )
        items = intent.get_items_list()
        assert len( items ) == 1
        assert items[ 0 ][ "name" ] == "A"
        assert items[ 0 ][ "price" ] == 3.49

    def test_empty_items_list( self ):
        intent = CalcIntent( operation="convert" )
        assert intent.get_items_list() == []

    def test_none_coercion( self ):
        """None values should be coerced to empty strings."""
        intent = CalcIntent( operation="convert", value=None, from_unit=None )
        assert intent.value == ""
        assert intent.from_unit == ""

    def test_confidence_parsing( self ):
        intent = CalcIntent( operation="convert", confidence="0.95" )
        assert intent.get_confidence_float() == 0.95

    def test_confidence_bad_value( self ):
        intent = CalcIntent( operation="convert", confidence="bad" )
        assert intent.get_confidence_float() == 0.0

    def test_xml_round_trip( self ):
        intent = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="miles", confidence="0.9" )
        xml_str = intent.to_xml()
        assert "<calc_intent>" in xml_str
        assert "<operation>convert</operation>" in xml_str
        parsed = CalcIntent.from_xml( xml_str, root_tag="calc_intent" )
        assert parsed.operation == "convert"
        assert parsed.value == "10"
        assert parsed.from_unit == "km"

    def test_template_example( self ):
        example = CalcIntent.get_example_for_template()
        assert example.operation.startswith( "[" )
        xml = example.to_xml()
        assert "<calc_intent>" in xml

    def test_valid_operations( self ):
        assert "convert" in CalcIntent.VALID_OPERATIONS
        assert "compare_prices" in CalcIntent.VALID_OPERATIONS
        assert "mortgage" in CalcIntent.VALID_OPERATIONS

    def test_unsupported_in_valid_operations( self ):
        """'unsupported' is a recognized valid operation."""
        assert "unsupported" in CalcIntent.VALID_OPERATIONS

    def test_create_unsupported_intent( self ):
        """CalcIntent accepts operation='unsupported' with minimal fields."""
        intent = CalcIntent( operation="unsupported", confidence="0.95", raw_query="What is 2 plus 2?" )
        assert intent.operation == "unsupported"
        assert intent.get_confidence_float() == 0.95
        assert intent.raw_query == "What is 2 plus 2?"
        assert intent.value == ""
        assert intent.from_unit == ""
        assert intent.to_unit == ""


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Arithmetic
# ═════════════════════════════════════════════════════════════════════════

class TestArithmetic:
    """Tests for arithmetic() — the calculator's own plain-math operation."""

    # ── happy paths, drawn from the calculator-routed eval corpus ──

    def test_subtract_two( self ):
        result = arithmetic( [ 789, 456 ], "subtract" )
        assert result[ "status" ] == "ok"
        assert result[ "result" ] == 333
        assert result[ "expression" ] == "789 minus 456"

    def test_add_nary( self ):
        result = arithmetic( [ 98, 134, 201 ], "add" )
        assert result[ "result" ] == 433
        assert result[ "expression" ] == "98 plus 134 plus 201"

    def test_multiply( self ):
        result = arithmetic( [ 64, 23 ], "multiply" )
        assert result[ "result" ] == 1472

    def test_multiply_nary( self ):
        result = arithmetic( [ 2, 3, 4 ], "multiply" )
        assert result[ "result" ] == 24

    def test_divide( self ):
        result = arithmetic( [ 45, 9 ], "divide" )
        assert result[ "result" ] == 5

    def test_divide_non_integral( self ):
        result = arithmetic( [ 1000, 40 ], "divide" )
        assert result[ "result" ] == 25

    def test_divide_fractional_result( self ):
        result = arithmetic( [ 10, 4 ], "divide" )
        assert result[ "result" ] == 2.5

    def test_modulo_non_zero_remainder( self ):
        result = arithmetic( [ 345, 22 ], "modulo" )
        assert result[ "result" ] == 15

    def test_modulo_exact_division( self ):
        result = arithmetic( [ 345, 23 ], "modulo" )
        assert result[ "result" ] == 0

    def test_power( self ):
        result = arithmetic( [ 2, 10 ], "power" )
        assert result[ "result" ] == 1024

    def test_left_fold_order_is_left_to_right( self ):
        # ( 100 - 20 ) - 5, not 100 - ( 20 - 5 )
        result = arithmetic( [ 100, 20, 5 ], "subtract" )
        assert result[ "result" ] == 75

    def test_operator_is_case_and_space_tolerant( self ):
        result = arithmetic( [ 3, 4 ], "  ADD  " )
        assert result[ "status" ] == "ok"
        assert result[ "result" ] == 7
        assert result[ "operator" ] == "add"

    def test_string_operands_are_coerced( self ):
        result = arithmetic( [ "789", "456" ], "subtract" )
        assert result[ "result" ] == 333

    def test_operands_echoed_as_floats( self ):
        result = arithmetic( [ 3, 4 ], "add" )
        assert result[ "operands" ] == [ 3.0, 4.0 ]

    def test_fractional_operands_in_expression( self ):
        result = arithmetic( [ 1.5, 2.25 ], "add" )
        assert result[ "result" ] == 3.75
        assert result[ "expression" ] == "1.5 plus 2.25"

    def test_thousands_separator_in_expression( self ):
        result = arithmetic( [ 1000000, 1 ], "add" )
        assert result[ "expression" ] == "1,000,000 plus 1"

    def test_result_rounded_to_six_places( self ):
        result = arithmetic( [ 1, 3 ], "divide" )
        assert result[ "result" ] == 0.333333

    # ── error paths ──

    def test_none_operator( self ):
        result = arithmetic( [ 1, 2 ], None )
        assert result[ "status" ] == "error"
        assert "No arithmetic operator" in result[ "message" ]

    def test_unknown_operator( self ):
        result = arithmetic( [ 1, 2 ], "frobnicate" )
        assert result[ "status" ] == "error"
        assert "Unknown arithmetic operator" in result[ "message" ]

    def test_empty_operands( self ):
        result = arithmetic( [], "add" )
        assert result[ "status" ] == "error"
        assert "at least two numbers" in result[ "message" ]

    def test_none_operands( self ):
        result = arithmetic( None, "add" )
        assert result[ "status" ] == "error"

    def test_single_operand( self ):
        result = arithmetic( [ 5 ], "add" )
        assert result[ "status" ] == "error"
        assert "at least two numbers" in result[ "message" ]

    def test_non_numeric_operand( self ):
        result = arithmetic( [ 1, "banana" ], "add" )
        assert result[ "status" ] == "error"
        assert "must be numbers" in result[ "message" ]

    def test_divide_by_zero( self ):
        result = arithmetic( [ 45, 0 ], "divide" )
        assert result[ "status" ] == "error"
        assert "divide by zero" in result[ "message" ]

    def test_modulo_by_zero( self ):
        result = arithmetic( [ 45, 0 ], "modulo" )
        assert result[ "status" ] == "error"
        assert "modulo zero" in result[ "message" ]

    def test_zero_to_negative_power_is_out_of_range( self ):
        result = arithmetic( [ 0, -1 ], "power" )
        assert result[ "status" ] == "error"
        assert "out of range" in result[ "message" ]

    def test_overflowing_power_is_out_of_range( self ):
        result = arithmetic( [ 10, 1000000 ], "power" )
        assert result[ "status" ] == "error"
        assert "out of range" in result[ "message" ]

    def test_negative_base_fractional_power_has_no_real_answer( self ):
        result = arithmetic( [ -8, 0.5 ], "power" )
        assert result[ "status" ] == "error"
        assert "no real-number answer" in result[ "message" ]

    def test_operator_table_matches_intent_model( self ):
        # The prompt, the model and the operations must agree on the operator set
        assert sorted( ARITHMETIC_OPERATORS.keys() ) == sorted( CalcIntent.VALID_OPERATORS )


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Arithmetic Intent + Dispatch
# ═════════════════════════════════════════════════════════════════════════

class TestArithmeticIntent:
    """Tests for the operands/operator fields on CalcIntent and their dispatch."""

    def test_arithmetic_is_a_valid_operation( self ):
        assert "arithmetic" in CalcIntent.VALID_OPERATIONS

    def test_get_operands_list( self ):
        intent = CalcIntent( operation="arithmetic", operator="add", operands="[34, 67, 129]" )
        assert intent.get_operands_list() == [ 34.0, 67.0, 129.0 ]

    def test_get_operands_list_floats( self ):
        intent = CalcIntent( operation="arithmetic", operator="add", operands="[1.5, 2.25]" )
        assert intent.get_operands_list() == [ 1.5, 2.25 ]

    def test_get_operands_list_numeric_strings( self ):
        intent = CalcIntent( operation="arithmetic", operator="add", operands='["3", "4"]' )
        assert intent.get_operands_list() == [ 3.0, 4.0 ]

    def test_get_operands_list_empty_field( self ):
        assert CalcIntent( operation="arithmetic" ).get_operands_list() == []

    def test_get_operands_list_whitespace_only( self ):
        assert CalcIntent( operation="arithmetic", operands="   " ).get_operands_list() == []

    def test_get_operands_list_empty_array( self ):
        assert CalcIntent( operation="arithmetic", operands="[]" ).get_operands_list() == []

    def test_get_operands_list_bad_json( self ):
        assert CalcIntent( operation="arithmetic", operands="not json" ).get_operands_list() == []

    def test_get_operands_list_not_a_list( self ):
        assert CalcIntent( operation="arithmetic", operands='{"a": 1}' ).get_operands_list() == []

    def test_get_operands_list_non_numeric_member( self ):
        assert CalcIntent( operation="arithmetic", operands='["banana"]' ).get_operands_list() == []

    def test_get_operands_list_null_member( self ):
        assert CalcIntent( operation="arithmetic", operands='[1, null]' ).get_operands_list() == []

    def test_operator_defaults_empty( self ):
        assert CalcIntent( operation="convert" ).operator == ""

    def test_arithmetic_xml_round_trip( self ):
        intent = CalcIntent( operation="arithmetic", operator="subtract", operands="[789, 456]" )
        xml    = intent.to_xml()
        assert "<operation>arithmetic</operation>" in xml
        assert "<operator>subtract</operator>" in xml
        parsed = CalcIntent.from_xml( xml, root_tag="calc_intent" )
        assert parsed.operator == "subtract"
        assert parsed.get_operands_list() == [ 789.0, 456.0 ]

    def test_dispatch_arithmetic( self ):
        intent = CalcIntent( operation="arithmetic", operator="subtract", operands="[789, 456]" )
        result = dispatch( intent )
        assert result[ "status" ] == "ok"
        assert result[ "result" ] == 333

    def test_dispatch_arithmetic_missing_operands_errors( self ):
        intent = CalcIntent( operation="arithmetic", operator="add" )
        result = dispatch( intent )
        assert result[ "status" ] == "error"

    def test_format_arithmetic_voice_integral( self ):
        result = arithmetic( [ 789, 456 ], "subtract" )
        voice  = format_result_for_voice( result, "arithmetic" )
        assert voice == "789 minus 456 is 333."

    def test_format_arithmetic_voice_fractional( self ):
        result = arithmetic( [ 10, 4 ], "divide" )
        voice  = format_result_for_voice( result, "arithmetic" )
        assert voice == "10 divided by 4 is 2.5."

    def test_format_arithmetic_voice_large_number_grouped( self ):
        result = arithmetic( [ 1000, 1000 ], "multiply" )
        voice  = format_result_for_voice( result, "arithmetic" )
        assert "1,000,000" in voice

    def test_format_arithmetic_voice_error( self ):
        result = arithmetic( [ 45, 0 ], "divide" )
        voice  = format_result_for_voice( result, "arithmetic" )
        assert voice.startswith( "Sorry" )


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Dispatcher
# ═════════════════════════════════════════════════════════════════════════

class TestDispatcher:
    """Tests for dispatcher.py — routing and voice formatting."""

    def test_dispatch_convert( self ):
        intent = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="miles" )
        result = dispatch( intent )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 6.2137 ) < 0.001

    def test_dispatch_compare_prices( self ):
        items_json = '[{"name": "S", "price": 3.49, "quantity": 12, "unit": "oz"}, {"name": "L", "price": 5.99, "quantity": 24, "unit": "oz"}]'
        intent = CalcIntent( operation="compare_prices", items=items_json )
        result = dispatch( intent )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "L"

    def test_dispatch_mortgage( self ):
        intent = CalcIntent( operation="mortgage", principal="300000", annual_rate="6.5", term_years="30" )
        result = dispatch( intent )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 1896.20 ) < 1.0

    def test_dispatch_unknown_operation( self ):
        intent = CalcIntent( operation="unknown_op" )
        with pytest.raises( ValueError, match="Unknown calc operation" ):
            dispatch( intent )

    def test_format_convert_voice( self ):
        result = { "status": "ok", "result": 6.21, "from_value": 10, "from_unit": "km", "to_unit": "mile" }
        voice = format_result_for_voice( result, "convert" )
        assert "10" in voice
        assert "6.21" in voice
        assert "kilometers" in voice
        assert "miles" in voice

    def test_format_mortgage_voice( self ):
        result = {
            "status"          : "ok",
            "monthly_payment" : 1896.20,
            "total_interest"  : 382633.0,
            "loan_amount"     : 300000,
            "term_years"      : 30
        }
        voice = format_result_for_voice( result, "mortgage" )
        assert "1,896" in voice
        assert "interest" in voice

    def test_format_error_voice( self ):
        result = { "status": "error", "message": "Something went wrong" }
        voice = format_result_for_voice( result, "convert" )
        assert "Sorry" in voice

    def test_extract_xml_clean( self ):
        xml = '<calc_intent><operation>convert</operation></calc_intent>'
        result = extract_calc_intent_xml( xml )
        assert "<operation>convert</operation>" in result

    def test_extract_xml_fenced( self ):
        xml = '```xml\n<calc_intent><operation>mortgage</operation></calc_intent>\n```'
        result = extract_calc_intent_xml( xml )
        assert "<operation>mortgage</operation>" in result

    def test_extract_xml_preamble( self ):
        xml = 'Here is the result:\n<calc_intent><operation>convert</operation></calc_intent>'
        result = extract_calc_intent_xml( xml )
        assert "<operation>convert</operation>" in result

    def test_extract_xml_missing_raises( self ):
        with pytest.raises( ValueError, match="No <calc_intent>" ):
            extract_calc_intent_xml( "No XML here at all" )

    def test_extract_xml_empty_raises( self ):
        with pytest.raises( ValueError, match="Empty response" ):
            extract_calc_intent_xml( "" )


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Pluralization
# ═════════════════════════════════════════════════════════════════════════

class TestPluralization:
    """Tests for _pluralize_unit() helper."""

    def test_singular( self ):
        assert _pluralize_unit( "mile", 1 ) == "mile"

    def test_plural( self ):
        assert _pluralize_unit( "mile", 2 ) == "miles"

    def test_foot_feet( self ):
        assert _pluralize_unit( "foot", 2 ) == "feet"

    def test_inch_inches( self ):
        assert _pluralize_unit( "inch", 2 ) == "inches"

    def test_celsius_display( self ):
        assert _pluralize_unit( "celsius", 1 ) == "degree Celsius"
        assert _pluralize_unit( "celsius", 72 ) == "degrees Celsius"

    def test_fahrenheit_display( self ):
        assert _pluralize_unit( "fahrenheit", 1 ) == "degree Fahrenheit"
        assert _pluralize_unit( "fahrenheit", 100 ) == "degrees Fahrenheit"

    def test_km_display( self ):
        assert _pluralize_unit( "km", 1 ) == "kilometer"
        assert _pluralize_unit( "km", 10 ) == "kilometers"


# ═════════════════════════════════════════════════════════════════════════
# Test Class: Known Facts Smoke Test (10+ verifiable real-world facts)
# ═════════════════════════════════════════════════════════════════════════

class TestKnownFactsSmokeTest:
    """
    10+ verifiable real-world known facts to validate calculator accuracy.

    These are facts you can verify with any calculator or reference:
    - Marathon distance
    - International avoirdupois conversions
    - Water boiling/freezing points
    - Standard mortgage calculations
    """

    def test_fact_1_marathon_miles( self ):
        """A marathon is 42.195 km ≈ 26.2188 miles."""
        result = convert( 42.195, "km", "miles" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 26.2188 ) < 0.01

    def test_fact_2_five_feet_in_cm( self ):
        """5 feet = 152.4 cm (exact)."""
        result = convert( 5, "feet", "cm" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 152.4 ) < 0.1

    def test_fact_3_one_yard_in_feet( self ):
        """1 yard = 3 feet (exact definition)."""
        result = convert( 1, "yard", "feet" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 3.0 ) < 0.01

    def test_fact_4_one_ton_in_pounds( self ):
        """1 US ton = 2000 pounds."""
        result = convert( 1, "ton", "pounds" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 2000.0 ) < 1.0

    def test_fact_5_one_liter_in_ml( self ):
        """1 liter = 1000 ml (exact definition)."""
        result = convert( 1, "liter", "ml" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 1000.0 ) < 0.1

    def test_fact_6_one_quart_in_pints( self ):
        """1 quart ≈ 2 pints."""
        result = convert( 1, "quart", "pint" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 2.0 ) < 0.01

    def test_fact_7_water_boiling_f( self ):
        """Water boils at 100°C = 212°F."""
        result = convert( 100, "celsius", "fahrenheit" )
        assert abs( result[ "result" ] - 212.0 ) < 0.01

    def test_fact_8_water_freezing_f( self ):
        """Water freezes at 0°C = 32°F."""
        result = convert( 0, "celsius", "fahrenheit" )
        assert abs( result[ "result" ] - 32.0 ) < 0.01

    def test_fact_9_absolute_zero_c( self ):
        """Absolute zero = 0 K = -273.15°C."""
        result = convert( 0, "kelvin", "celsius" )
        assert abs( result[ "result" ] - ( -273.15 ) ) < 0.01

    def test_fact_10_mortgage_10k_5yr( self ):
        """$10,000 at 5% for 5 years ≈ $188.71/month (verifiable with any mortgage calc)."""
        result = mortgage( 10000, 5.0, 5 )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 188.71 ) < 0.50

    def test_fact_11_standard_mortgage( self ):
        """$200,000 at 7% for 30 years ≈ $1,330.60/month."""
        result = mortgage( 200000, 7.0, 30 )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 1330.60 ) < 1.0

    def test_fact_12_100_yards_in_meters( self ):
        """100 yards = 91.44 meters (exact)."""
        result = convert( 100, "yards", "meters" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 91.44 ) < 0.01


def quick_smoke_test():
    """Module-level smoke test: run all known facts."""

    print( "Testing calculator known facts smoke test..." )
    test_instance = TestKnownFactsSmokeTest()
    tests = [
        ( "Marathon km→miles",   test_instance.test_fact_1_marathon_miles ),
        ( "5 feet→cm",          test_instance.test_fact_2_five_feet_in_cm ),
        ( "1 yard→feet",        test_instance.test_fact_3_one_yard_in_feet ),
        ( "1 ton→pounds",       test_instance.test_fact_4_one_ton_in_pounds ),
        ( "1 liter→ml",         test_instance.test_fact_5_one_liter_in_ml ),
        ( "1 quart→pints",      test_instance.test_fact_6_one_quart_in_pints ),
        ( "Water boiling F",    test_instance.test_fact_7_water_boiling_f ),
        ( "Water freezing F",   test_instance.test_fact_8_water_freezing_f ),
        ( "Absolute zero C",    test_instance.test_fact_9_absolute_zero_c ),
        ( "Mortgage $10k/5yr",  test_instance.test_fact_10_mortgage_10k_5yr ),
        ( "Mortgage $200k/30yr", test_instance.test_fact_11_standard_mortgage ),
        ( "100 yards→meters",   test_instance.test_fact_12_100_yards_in_meters ),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            print( f"  ✓ {name}" )
            passed += 1
        except AssertionError as e:
            print( f"  ✗ {name}: {e}" )
            failed += 1

    print( f"\n{'─' * 50}" )
    print( f"  Known Facts: {passed} passed, {failed} failed, {len( tests )} total" )
    print( f"{'─' * 50}" )

    return failed == 0


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
