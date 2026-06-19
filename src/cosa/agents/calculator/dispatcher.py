#!/usr/bin/env python3
"""
Intent dispatch and voice formatting for Calculator operations.

Pure functions that bridge CalcIntent objects to calc_operations calls
and format results for TTS voice output.

Functions:
    dispatch: Routes CalcIntent → calc_operations function by operation name
    format_result_for_voice: Converts result dicts to TTS-friendly strings
    extract_calc_intent_xml: Regex extracts <calc_intent>...</calc_intent> from raw LLM response
"""

import re

from cosa.agents.calculator.xml_models import CalcIntent
from cosa.agents.calculator import calc_operations


def dispatch( intent, debug=False ):
    """
    Route a CalcIntent to the appropriate calc_operations function.

    Requires:
        - intent is a CalcIntent instance with a valid operation field

    Ensures:
        - Returns the result dict from the corresponding calc_operations function
        - Raises ValueError for unknown operations

    Raises:
        - ValueError if intent.operation is not in CalcIntent.VALID_OPERATIONS
    """
    op = intent.operation.strip().lower()

    if debug: print( f"calculator.dispatcher.dispatch: operation={op}" )

    if op == "convert":
        return calc_operations.convert(
            value     = intent.get_value_float(),
            from_unit = intent.from_unit,
            to_unit   = intent.to_unit
        )

    elif op == "compare_prices":
        return calc_operations.compare_prices(
            items = intent.get_items_list()
        )

    elif op == "mortgage":
        return calc_operations.mortgage(
            principal    = intent.get_principal_float(),
            annual_rate  = intent.get_annual_rate_float(),
            term_years   = intent.get_term_years_int(),
            down_payment = intent.get_down_payment_float()
        )

    else:
        raise ValueError( f"Unknown calc operation '{op}'. Valid: {CalcIntent.VALID_OPERATIONS}" )


def format_result_for_voice( result, operation ):
    """
    Convert a calculation result dict to a TTS-friendly conversational string.

    Requires:
        - result is a dict with at least a "status" key
        - operation is a string naming the calc operation

    Ensures:
        - Returns a natural language string suitable for voice output
        - Handles all status types: ok, error
    """
    status  = result.get( "status", "error" )
    message = result.get( "message", "" )

    if status == "error":
        return f"Sorry, there was a problem: {message}"

    if operation == "convert":
        return _format_convert_for_voice( result )

    elif operation == "compare_prices":
        return _format_compare_prices_for_voice( result )

    elif operation == "mortgage":
        return _format_mortgage_for_voice( result )

    # Fallback
    return message if message else f"Calculation completed with status {status}."


def _format_convert_for_voice( result ):
    """
    Format unit conversion result for TTS.

    Requires:
        - result contains from_value, from_unit, to_unit, result keys

    Ensures:
        - Returns natural phrasing like "10 kilometers is about 6.21 miles."
    """
    from_value = result[ "from_value" ]
    from_unit  = result[ "from_unit" ]
    to_unit    = result[ "to_unit" ]
    converted  = result[ "result" ]

    # Smart rounding for display
    if converted == int( converted ):
        display_value = f"{int( converted ):,}"
    elif abs( converted ) >= 100:
        display_value = f"{converted:,.0f}"
    elif abs( converted ) >= 10:
        display_value = f"{converted:,.1f}"
    else:
        display_value = f"{converted:,.2f}"

    # Format input value
    if from_value == int( from_value ):
        from_display = f"{int( from_value )}"
    else:
        from_display = f"{from_value}"

    # Pluralize units for display
    from_display_unit = _pluralize_unit( from_unit, from_value )
    to_display_unit   = _pluralize_unit( to_unit, converted )

    return f"{from_display} {from_display_unit} is about {display_value} {to_display_unit}."


def _format_compare_prices_for_voice( result ):
    """
    Format price comparison result for TTS.

    Requires:
        - result contains items (sorted by unit_price), cheapest, common_unit

    Ensures:
        - Returns natural phrasing identifying cheapest option with prices
    """
    items       = result[ "items" ]
    cheapest    = result[ "cheapest" ]
    common_unit = result[ "common_unit" ]

    display_unit = _pluralize_unit( common_unit, 1 )  # singular for "per X"

    parts = []
    for item in items:
        parts.append( f"{item[ 'name' ]} at ${item[ 'unit_price' ]:.3f} per {display_unit}" )

    if len( items ) == 2:
        return f"The {cheapest} is cheaper at ${items[ 0 ][ 'unit_price' ]:.3f} per {display_unit}, versus {parts[ 1 ]}."
    else:
        return f"The cheapest is {cheapest} at ${items[ 0 ][ 'unit_price' ]:.3f} per {display_unit}. " + ", ".join( parts[ 1: ] ) + "."


def _format_mortgage_for_voice( result ):
    """
    Format mortgage calculation result for TTS.

    Requires:
        - result contains monthly_payment, total_paid, total_interest, loan_amount

    Ensures:
        - Returns natural phrasing with monthly payment and total interest
    """
    monthly  = result[ "monthly_payment" ]
    interest = result[ "total_interest" ]
    loan     = result[ "loan_amount" ]

    return (
        f"Your monthly payment would be about ${monthly:,.0f}. "
        f"Over {result[ 'term_years' ]} years you'd pay about ${interest:,.0f} in total interest "
        f"on a ${loan:,.0f} loan."
    )


def _pluralize_unit( unit, value ):
    """
    Return a human-friendly display name for a unit, pluralized if needed.

    Requires:
        - unit is a canonical unit string
        - value is a numeric for singular/plural decision

    Ensures:
        - Returns display-friendly unit name (e.g., "miles" not "mile")
    """
    # Special display names
    DISPLAY_NAMES = {
        "celsius"    : ( "degree Celsius",    "degrees Celsius" ),
        "fahrenheit" : ( "degree Fahrenheit",  "degrees Fahrenheit" ),
        "kelvin"     : ( "kelvin",            "kelvin" ),
        "fl_oz"      : ( "fluid ounce",       "fluid ounces" ),
        "km"         : ( "kilometer",         "kilometers" ),
        "cm"         : ( "centimeter",        "centimeters" ),
        "mm"         : ( "millimeter",        "millimeters" ),
        "mg"         : ( "milligram",         "milligrams" ),
        "ml"         : ( "milliliter",        "milliliters" ),
        "kg"         : ( "kilogram",          "kilograms" ),
    }

    if unit in DISPLAY_NAMES:
        singular, plural = DISPLAY_NAMES[ unit ]
        return singular if abs( value ) == 1 else plural

    # Default: add "s" for plural
    if abs( value ) == 1:
        return unit
    else:
        if unit.endswith( "s" ):
            return unit
        elif unit.endswith( "foot" ):
            return "feet"
        elif unit.endswith( "inch" ):
            return "inches"
        else:
            return unit + "s"


def extract_calc_intent_xml( raw_response ):
    """
    Extract <calc_intent>...</calc_intent> XML block from raw LLM response text.

    Handles common LLM response patterns:
    - Clean XML output
    - XML wrapped in markdown code fences
    - XML preceded by preamble text
    - XML followed by explanation text

    Requires:
        - raw_response is a string (may contain noise around XML)

    Ensures:
        - Returns the <calc_intent>...</calc_intent> XML string if found
        - Raises ValueError if no calc_intent XML block is found
    """
    if not raw_response or not raw_response.strip():
        raise ValueError( "Empty response from LLM" )

    text = raw_response.strip()

    # Remove markdown code fences if present
    text = re.sub( r"```(?:xml)?\s*", "", text )
    text = re.sub( r"```\s*$", "", text, flags=re.MULTILINE )

    # Extract <calc_intent>...</calc_intent> block
    match = re.search( r"<calc_intent\s*>.*?</calc_intent>", text, re.DOTALL )
    if match:
        return match.group( 0 )

    raise ValueError( f"No <calc_intent>...</calc_intent> block found in LLM response. Response starts with: {raw_response[ :100 ]}" )


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing calculator dispatcher module..." )
    passed = True

    try:
        # Test dispatch — convert
        intent = CalcIntent( operation="convert", value="10", from_unit="km", to_unit="miles" )
        result = dispatch( intent, debug=True )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 6.2137 ) < 0.001
        print( f"  ✓ dispatch convert: 10 km → {result[ 'result' ]} miles" )

        # Test voice formatting — convert
        voice = format_result_for_voice( result, "convert" )
        assert "6.21" in voice
        assert "kilometers" in voice
        print( f"  ✓ format convert: {voice}" )

        # Test dispatch — compare_prices
        items_json = '[{"name": "Small", "price": 3.49, "quantity": 12, "unit": "oz"}, {"name": "Large", "price": 5.99, "quantity": 24, "unit": "oz"}]'
        intent = CalcIntent( operation="compare_prices", items=items_json )
        result = dispatch( intent, debug=True )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "Large"
        print( f"  ✓ dispatch compare_prices: cheapest = {result[ 'cheapest' ]}" )

        # Test voice formatting — compare_prices
        voice = format_result_for_voice( result, "compare_prices" )
        assert "Large" in voice
        assert "cheaper" in voice
        print( f"  ✓ format compare_prices: {voice[ :80 ]}..." )

        # Test dispatch — mortgage
        intent = CalcIntent( operation="mortgage", principal="300000", annual_rate="6.5", term_years="30" )
        result = dispatch( intent, debug=True )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 1896.20 ) < 1.0
        print( f"  ✓ dispatch mortgage: ${result[ 'monthly_payment' ]}/mo" )

        # Test voice formatting — mortgage
        voice = format_result_for_voice( result, "mortgage" )
        assert "1,896" in voice
        print( f"  ✓ format mortgage: {voice[ :80 ]}..." )

        # Test extract_calc_intent_xml
        xml = '<calc_intent><operation>convert</operation><value>10</value></calc_intent>'
        extracted = extract_calc_intent_xml( xml )
        assert "<operation>convert</operation>" in extracted
        print( "  ✓ extract_calc_intent_xml: clean XML" )

        fenced = '```xml\n<calc_intent><operation>mortgage</operation></calc_intent>\n```'
        extracted = extract_calc_intent_xml( fenced )
        assert "<operation>mortgage</operation>" in extracted
        print( "  ✓ extract_calc_intent_xml: markdown fenced" )

        try:
            extract_calc_intent_xml( "No XML here" )
            assert False, "Should have raised ValueError"
        except ValueError:
            pass
        print( "  ✓ extract_calc_intent_xml: missing intent raises ValueError" )

        # Test error formatting
        error_result = { "status": "error", "message": "Something went wrong" }
        voice = format_result_for_voice( error_result, "convert" )
        assert "Sorry" in voice
        print( f"  ✓ format error: {voice}" )

        print( "✓ calculator dispatcher module smoke test PASSED" )

    except Exception as e:
        print( f"✗ calculator dispatcher module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
