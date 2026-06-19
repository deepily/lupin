#!/usr/bin/env python3
"""
Pure Python calculation functions for the Everyday Calculator agent.

Three domains, zero LLM involvement in the computation:
    - convert()        — Unit conversions (length, mass, volume, temperature)
    - compare_prices() — Unit price normalization + comparison
    - mortgage()       — Standard amortization formula

All functions return result dicts with "status" key for consistent handling.
"""

from cosa.agents.calculator.conversion_tables import (
    resolve_alias, find_category, TEMPERATURE
)


def convert( value, from_unit, to_unit ):
    """
    Convert a numeric value between two units in the same category.

    Requires:
        - value is a numeric (int or float)
        - from_unit and to_unit are non-empty strings

    Ensures:
        - Returns dict with status="ok" and result on success
        - Returns dict with status="error" on failure
        - Temperature handled via explicit formulas (F↔C↔K)
        - All other categories use hub-and-spoke ratio conversion

    Raises:
        - Nothing — errors returned in result dict
    """
    if value is None:
        return { "status": "error", "message": "No value provided for conversion." }

    from_canonical = resolve_alias( from_unit )
    to_canonical   = resolve_alias( to_unit )

    if from_canonical == to_canonical:
        return {
            "status"     : "ok",
            "result"     : round( value, 4 ),
            "from_value" : value,
            "from_unit"  : from_canonical,
            "to_unit"    : to_canonical
        }

    # Check if temperature
    from_cat, from_cat_name = find_category( from_canonical )
    to_cat, to_cat_name     = find_category( to_canonical )

    if from_cat is None:
        return { "status": "error", "message": f"Unknown unit: {from_unit}" }
    if to_cat is None:
        return { "status": "error", "message": f"Unknown unit: {to_unit}" }

    if from_cat_name != to_cat_name:
        return { "status": "error", "message": f"Cannot convert between {from_cat_name} and {to_cat_name}." }

    # Temperature: explicit formulas
    if from_cat_name == "temperature":
        result = _convert_temperature( value, from_canonical, to_canonical )
        if result is None:
            return { "status": "error", "message": f"Unsupported temperature conversion: {from_canonical} → {to_canonical}" }
        return {
            "status"     : "ok",
            "result"     : round( result, 2 ),
            "from_value" : value,
            "from_unit"  : from_canonical,
            "to_unit"    : to_canonical
        }

    # Hub-and-spoke: value_in_base = value * from_factor; result = value_in_base / to_factor
    from_factor = from_cat[ from_canonical ]
    to_factor   = from_cat[ to_canonical ]

    value_in_base = value * from_factor
    result        = value_in_base / to_factor

    return {
        "status"     : "ok",
        "result"     : round( result, 4 ),
        "from_value" : value,
        "from_unit"  : from_canonical,
        "to_unit"    : to_canonical
    }


def _convert_temperature( value, from_unit, to_unit ):
    """
    Convert temperature between celsius, fahrenheit, and kelvin.

    Requires:
        - value is a numeric
        - from_unit and to_unit are canonical temperature unit names

    Ensures:
        - Returns converted float value
        - Returns None if conversion pair is unsupported
    """
    # Normalize to celsius first, then convert to target
    if from_unit == "celsius":
        celsius = value
    elif from_unit == "fahrenheit":
        celsius = ( value - 32 ) * 5 / 9
    elif from_unit == "kelvin":
        celsius = value - 273.15
    else:
        return None

    if to_unit == "celsius":
        return celsius
    elif to_unit == "fahrenheit":
        return celsius * 9 / 5 + 32
    elif to_unit == "kelvin":
        return celsius + 273.15
    else:
        return None


def compare_prices( items ):
    """
    Normalize product prices to a common unit and determine which is cheaper.

    Requires:
        - items is a list of dicts, each with keys: name, price, quantity, unit
        - All items must have units in the same category (e.g., all mass or all volume)

    Ensures:
        - Returns dict with status="ok", items sorted by unit_price ascending
        - Each item dict includes computed unit_price and common_unit
        - Returns dict with status="error" on failure
    """
    if not items or len( items ) < 2:
        return { "status": "error", "message": "Need at least 2 items to compare prices." }

    # Resolve units and find common category
    resolved_items = []
    category_dict  = None
    category_name  = None

    for item in items:
        name     = item.get( "name", "Item" )
        price    = item.get( "price", 0 )
        quantity = item.get( "quantity", 0 )
        unit     = item.get( "unit", "" )

        try:
            price    = float( price )
            quantity = float( quantity )
        except ( ValueError, TypeError ):
            return { "status": "error", "message": f"Invalid price or quantity for {name}." }

        if quantity <= 0:
            return { "status": "error", "message": f"Quantity must be positive for {name}." }

        canonical_unit = resolve_alias( unit )
        cat_dict, cat_name = find_category( canonical_unit )

        if cat_dict is None:
            return { "status": "error", "message": f"Unknown unit: {unit}" }

        if cat_name == "temperature":
            return { "status": "error", "message": "Temperature units cannot be used for price comparison." }

        if category_name is None:
            category_dict = cat_dict
            category_name = cat_name
        elif cat_name != category_name:
            return { "status": "error", "message": f"Cannot compare {category_name} and {cat_name} units." }

        resolved_items.append( {
            "name"           : name,
            "price"          : price,
            "quantity"        : quantity,
            "unit"           : canonical_unit,
            "factor_to_base" : cat_dict[ canonical_unit ]
        } )

    # Use a sensible display unit per category for human-friendly price-per-unit
    DISPLAY_UNITS = {
        "length" : "foot",
        "mass"   : "ounce",
        "volume" : "fl_oz",
    }
    common_unit = DISPLAY_UNITS.get( category_name, list( category_dict.keys() )[ 0 ] )

    # Skip non-ratio categories (temperature already caught above)
    common_factor = category_dict[ common_unit ]

    # Compute unit price: price per 1 common_unit
    for item in resolved_items:
        quantity_in_base   = item[ "quantity" ] * item[ "factor_to_base" ]
        quantity_in_common = quantity_in_base / common_factor
        item[ "unit_price" ]          = round( item[ "price" ] / quantity_in_common, 4 )
        item[ "quantity_in_common" ]  = round( quantity_in_common, 2 )
        item[ "common_unit" ]         = common_unit

    # Sort by unit price ascending (cheapest first)
    resolved_items.sort( key=lambda x: x[ "unit_price" ] )

    # Clean up internal fields
    for item in resolved_items:
        del item[ "factor_to_base" ]

    return {
        "status"      : "ok",
        "items"       : resolved_items,
        "cheapest"    : resolved_items[ 0 ][ "name" ],
        "common_unit" : common_unit
    }


def mortgage( principal, annual_rate, term_years, down_payment=0 ):
    """
    Calculate monthly mortgage payment using standard amortization formula.

    Formula: M = P[r(1+r)^n] / [(1+r)^n - 1]
    Where:
        P = loan amount (principal - down_payment)
        r = monthly interest rate (annual_rate / 100 / 12)
        n = total number of payments (term_years * 12)

    Requires:
        - principal is a positive number
        - annual_rate is a positive number (percentage, e.g. 6.5)
        - term_years is a positive integer
        - down_payment is a non-negative number < principal

    Ensures:
        - Returns dict with status="ok" and monthly_payment, total_paid, total_interest
        - Returns dict with status="error" on invalid inputs
    """
    if principal is None or principal <= 0:
        return { "status": "error", "message": "Principal must be a positive number." }

    if annual_rate is None or annual_rate <= 0:
        return { "status": "error", "message": "Annual rate must be a positive number." }

    if term_years is None or term_years <= 0:
        return { "status": "error", "message": "Term must be a positive number of years." }

    if down_payment is None:
        down_payment = 0

    if down_payment < 0:
        return { "status": "error", "message": "Down payment cannot be negative." }

    loan_amount = principal - down_payment

    if loan_amount <= 0:
        return { "status": "error", "message": "Down payment exceeds or equals principal." }

    # Monthly interest rate
    r = annual_rate / 100 / 12

    # Total number of payments
    n = term_years * 12

    # Amortization formula: M = P[r(1+r)^n] / [(1+r)^n - 1]
    factor          = ( 1 + r ) ** n
    monthly_payment = loan_amount * ( r * factor ) / ( factor - 1 )

    total_paid    = monthly_payment * n
    total_interest = total_paid - loan_amount

    return {
        "status"          : "ok",
        "monthly_payment" : round( monthly_payment, 2 ),
        "total_paid"      : round( total_paid, 2 ),
        "total_interest"  : round( total_interest, 2 ),
        "loan_amount"     : round( loan_amount, 2 ),
        "principal"       : round( principal, 2 ),
        "down_payment"    : round( down_payment, 2 ),
        "annual_rate"     : annual_rate,
        "term_years"      : term_years
    }


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing calc_operations module..." )
    passed = True

    try:
        # ── Unit Conversion Tests ──
        result = convert( 10, "kilometers", "miles" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 6.2137 ) < 0.001
        print( f"  ✓ convert: 10 km → {result[ 'result' ]} miles" )

        result = convert( 100, "fahrenheit", "celsius" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 37.78 ) < 0.01
        print( f"  ✓ convert: 100°F → {result[ 'result' ]}°C" )

        result = convert( 1, "pound", "ounce" )
        assert result[ "status" ] == "ok"
        assert abs( result[ "result" ] - 16.0 ) < 0.01
        print( f"  ✓ convert: 1 lb → {result[ 'result' ]} oz" )

        # Same unit
        result = convert( 5, "meter", "meter" )
        assert result[ "status" ] == "ok"
        assert result[ "result" ] == 5
        print( f"  ✓ convert: same unit → identity" )

        # Cross-category error
        result = convert( 1, "km", "gallon" )
        assert result[ "status" ] == "error"
        print( f"  ✓ convert: cross-category error" )

        # ── Price Comparison Tests ──
        items = [
            { "name": "Brand A", "price": 3.49, "quantity": 12, "unit": "oz" },
            { "name": "Brand B", "price": 5.99, "quantity": 24, "unit": "oz" },
        ]
        result = compare_prices( items )
        assert result[ "status" ] == "ok"
        assert result[ "cheapest" ] == "Brand B"
        print( f"  ✓ compare_prices: cheapest = {result[ 'cheapest' ]}" )

        # ── Mortgage Tests ──
        result = mortgage( 300000, 6.5, 30 )
        assert result[ "status" ] == "ok"
        assert abs( result[ "monthly_payment" ] - 1896.20 ) < 1.0
        print( f"  ✓ mortgage: $300k @ 6.5% × 30yr → ${result[ 'monthly_payment' ]}/mo" )

        result = mortgage( 300000, 6.5, 30, down_payment=50000 )
        assert result[ "status" ] == "ok"
        assert result[ "loan_amount" ] == 250000.0
        print( f"  ✓ mortgage: with $50k down → loan ${result[ 'loan_amount' ]}" )

        # Invalid inputs
        result = mortgage( 0, 6.5, 30 )
        assert result[ "status" ] == "error"
        print( f"  ✓ mortgage: zero principal → error" )

        print( "✓ calc_operations module smoke test PASSED" )

    except Exception as e:
        print( f"✗ calc_operations module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
