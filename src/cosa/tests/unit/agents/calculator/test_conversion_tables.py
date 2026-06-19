"""
Unit tests for cosa.agents.calculator.conversion_tables.

Pure dict-backed helpers — no mocking required:

- resolve_alias  — alias hit, and lowercase/strip passthrough when no alias exists
- find_category  — each of the four categories, plus the not-found path

Created 2026-05-31 (CoSA coverage campaign, calculator package — Tiffany 💍). New file.
"""

import unittest

from cosa.agents.calculator.conversion_tables import (
    resolve_alias, find_category, LENGTH, MASS, VOLUME, TEMPERATURE,
)


class TestConversionTables( unittest.TestCase ):
    """
    Unit tests for the conversion-table helpers.

    Ensures:
        - Aliases resolve to canonical names; unknown names pass through normalized
        - Category lookup maps canonical units to the right (dict, name) pair
    """

    def test_resolve_alias_hits( self ):
        """Test known aliases resolve to their canonical form (case-insensitive)."""
        self.assertEqual( resolve_alias( "kilometers" ), "km" )
        self.assertEqual( resolve_alias( "LBS" ), "pound" )
        self.assertEqual( resolve_alias( "  Miles " ), "mile" )

    def test_resolve_alias_passthrough( self ):
        """Test an unknown unit is returned stripped + lowercased (no alias)."""
        self.assertEqual( resolve_alias( "  WIDGET " ), "widget" )

    def test_find_category_each_domain( self ):
        """Test find_category maps a canonical unit to its (dict, name) pair."""
        self.assertEqual( find_category( "km" ), ( LENGTH, "length" ) )
        self.assertEqual( find_category( "ounce" ), ( MASS, "mass" ) )
        self.assertEqual( find_category( "gallon" ), ( VOLUME, "volume" ) )
        self.assertEqual( find_category( "celsius" ), ( TEMPERATURE, "temperature" ) )

    def test_find_category_unknown_returns_none_pair( self ):
        """Test an unknown unit yields (None, None)."""
        self.assertEqual( find_category( "parsec" ), ( None, None ) )


if __name__ == "__main__":
    unittest.main()
