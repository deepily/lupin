#!/usr/bin/env python3
"""
Unit conversion factor tables for the Everyday Calculator agent.

Hub-and-spoke model where each unit category normalizes to a base unit.
Temperature is handled via explicit formulas (not ratio-based).

No external libraries required — pure Python dicts.
"""

# ─────────────────────────────────────────────────────────────────────
# Length: base unit = meters
# ─────────────────────────────────────────────────────────────────────
LENGTH = {
    "meter"     : 1.0,
    "km"        : 1000.0,
    "mile"      : 1609.344,
    "foot"      : 0.3048,
    "inch"      : 0.0254,
    "yard"      : 0.9144,
    "cm"        : 0.01,
    "mm"        : 0.001,
}

# ─────────────────────────────────────────────────────────────────────
# Weight/Mass: base unit = grams
# ─────────────────────────────────────────────────────────────────────
MASS = {
    "gram"  : 1.0,
    "kg"    : 1000.0,
    "pound" : 453.592,
    "ounce" : 28.3495,
    "mg"    : 0.001,
    "ton"   : 907185.0,
}

# ─────────────────────────────────────────────────────────────────────
# Volume: base unit = liters
# ─────────────────────────────────────────────────────────────────────
VOLUME = {
    "liter"  : 1.0,
    "gallon" : 3.78541,
    "quart"  : 0.946353,
    "pint"   : 0.473176,
    "cup"    : 0.236588,
    "fl_oz"  : 0.0295735,
    "ml"     : 0.001,
}

# ─────────────────────────────────────────────────────────────────────
# Temperature: not ratio-based — handled via formulas
# This set exists only for alias resolution / category lookup
# ─────────────────────────────────────────────────────────────────────
TEMPERATURE = {
    "celsius"    : None,
    "fahrenheit" : None,
    "kelvin"     : None,
}

# ─────────────────────────────────────────────────────────────────────
# Category registry: maps canonical unit name → (category_dict, category_name)
# ─────────────────────────────────────────────────────────────────────
ALL_CATEGORIES = [
    ( LENGTH,      "length" ),
    ( MASS,        "mass" ),
    ( VOLUME,      "volume" ),
    ( TEMPERATURE, "temperature" ),
]

# ─────────────────────────────────────────────────────────────────────
# Alias map: spoken/plural/variant forms → canonical unit name
# ─────────────────────────────────────────────────────────────────────
ALIASES = {
    # Length
    "meters"      : "meter",
    "metre"       : "meter",
    "metres"      : "meter",
    "m"           : "meter",
    "kilometers"  : "km",
    "kilometre"   : "km",
    "kilometres"  : "km",
    "kms"         : "km",
    "miles"       : "mile",
    "mi"          : "mile",
    "feet"        : "foot",
    "ft"          : "foot",
    "inches"      : "inch",
    "in"          : "inch",
    "yards"       : "yard",
    "yd"          : "yard",
    "yds"         : "yard",
    "centimeters" : "cm",
    "centimetre"  : "cm",
    "centimetres" : "cm",
    "centimeter"  : "cm",
    "millimeters" : "mm",
    "millimetre"  : "mm",
    "millimetres" : "mm",
    "millimeter"  : "mm",

    # Mass
    "grams"       : "gram",
    "g"           : "gram",
    "kilograms"   : "kg",
    "kilogram"    : "kg",
    "kgs"         : "kg",
    "pounds"      : "pound",
    "lb"          : "pound",
    "lbs"         : "pound",
    "ounces"      : "ounce",
    "oz"          : "ounce",
    "milligrams"  : "mg",
    "milligram"   : "mg",
    "mgs"         : "mg",
    "tons"        : "ton",

    # Volume
    "liters"      : "liter",
    "litre"       : "liter",
    "litres"      : "liter",
    "l"           : "liter",
    "gallons"     : "gallon",
    "gal"         : "gallon",
    "gals"        : "gallon",
    "quarts"      : "quart",
    "qt"          : "quart",
    "qts"         : "quart",
    "pints"       : "pint",
    "pt"          : "pint",
    "pts"         : "pint",
    "cups"        : "cup",
    "fluid_ounce" : "fl_oz",
    "fluid_ounces": "fl_oz",
    "fluid ounce" : "fl_oz",
    "fluid ounces": "fl_oz",
    "fl oz"       : "fl_oz",
    "milliliters" : "ml",
    "milliliter"  : "ml",
    "millilitre"  : "ml",
    "millilitres" : "ml",
    "mls"         : "ml",

    # Temperature
    "c"           : "celsius",
    "f"           : "fahrenheit",
    "k"           : "kelvin",
    "centigrade"  : "celsius",
    "degrees c"   : "celsius",
    "degrees f"   : "fahrenheit",
    "degrees k"   : "kelvin",
    "deg c"       : "celsius",
    "deg f"       : "fahrenheit",
    "deg k"       : "kelvin",
}


def resolve_alias( unit_name ):
    """
    Resolve a unit name to its canonical form.

    Requires:
        - unit_name is a non-empty string

    Ensures:
        - Returns canonical unit name if alias found
        - Returns original lowered/stripped name if no alias exists
    """
    normalized = unit_name.strip().lower()
    return ALIASES.get( normalized, normalized )


def find_category( canonical_unit ):
    """
    Find which category a canonical unit belongs to.

    Requires:
        - canonical_unit is a string (should be canonical after resolve_alias)

    Ensures:
        - Returns (category_dict, category_name) tuple if found
        - Returns (None, None) if unit not found in any category
    """
    for category_dict, category_name in ALL_CATEGORIES:
        if canonical_unit in category_dict:
            return category_dict, category_name

    return None, None


def quick_smoke_test():
    """Module-level smoke test following CoSA convention."""

    print( "Testing conversion_tables module..." )
    passed = True

    try:
        # Test alias resolution
        assert resolve_alias( "kilometers" ) == "km"
        assert resolve_alias( "miles" ) == "mile"
        assert resolve_alias( "ounces" ) == "ounce"
        assert resolve_alias( "lbs" ) == "pound"
        assert resolve_alias( "celsius" ) == "celsius"
        assert resolve_alias( "METERS" ) == "meter"
        print( "  ✓ Alias resolution" )

        # Test category lookup
        cat_dict, cat_name = find_category( "km" )
        assert cat_name == "length"
        assert cat_dict is LENGTH
        print( "  ✓ Category lookup: km → length" )

        cat_dict, cat_name = find_category( "ounce" )
        assert cat_name == "mass"
        print( "  ✓ Category lookup: ounce → mass" )

        cat_dict, cat_name = find_category( "gallon" )
        assert cat_name == "volume"
        print( "  ✓ Category lookup: gallon → volume" )

        cat_dict, cat_name = find_category( "celsius" )
        assert cat_name == "temperature"
        print( "  ✓ Category lookup: celsius → temperature" )

        cat_dict, cat_name = find_category( "unknown_unit" )
        assert cat_dict is None
        assert cat_name is None
        print( "  ✓ Category lookup: unknown unit → None" )

        print( "✓ conversion_tables module smoke test PASSED" )

    except Exception as e:
        print( f"✗ conversion_tables module smoke test FAILED: {e}" )
        import traceback
        traceback.print_exc()
        passed = False

    return passed


if __name__ == "__main__":
    success = quick_smoke_test()
    exit( 0 if success else 1 )
