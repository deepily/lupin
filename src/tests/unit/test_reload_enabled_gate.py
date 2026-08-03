"""
Unit tests for the R1 reload gate `lupin_app.bootstrap_helpers.reload_enabled`.

The gate decides whether uvicorn `--reload` arms on `:7999`. Extracted to a pure
helper (Tiffany, 2026-08-01) so its truth table is a TESTED decision, not a
string-equality accident: an exact `== "1"` silently ignored `true`/`yes`/`"1 "`,
loud only to whoever set the var, silent to anyone who inherited it from a compose
or env file. Design: src/rnd/v0.1.9/2026.08.01-managed-bounce-for-7999.md §3.1.
"""

import unittest

from lupin_app.bootstrap_helpers import reload_enabled


class ReloadEnabledGateTests( unittest.TestCase ):

    def test_canonical_one_enables_in_dev( self ):
        self.assertTrue( reload_enabled( "1", is_prod_or_test=False ) )

    def test_true_and_yes_any_case_enable_in_dev( self ):
        for v in ( "true", "TRUE", "Yes", "yes" ):
            self.assertTrue( reload_enabled( v, is_prod_or_test=False ), v )

    def test_surrounding_whitespace_tolerated( self ):
        self.assertTrue( reload_enabled( "1 ", is_prod_or_test=False ) )
        self.assertTrue( reload_enabled( "  true\n", is_prod_or_test=False ) )

    def test_unset_or_empty_or_none_is_off( self ):
        for v in ( "", None, "0", "off", "no", "enable" ):
            self.assertFalse( reload_enabled( v, is_prod_or_test=False ), repr( v ) )

    def test_prod_or_test_forces_off_even_when_opted_in( self ):
        self.assertFalse( reload_enabled( "1",    is_prod_or_test=True ) )
        self.assertFalse( reload_enabled( "true", is_prod_or_test=True ) )


if __name__ == "__main__":
    unittest.main()
