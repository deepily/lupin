"""
Unit tests for cosa.config.cache_registry.

A process-lifetime cache-invalidation registry. Tests cover registration
validation, idempotent replacement, invalidate_all()'s success/failure
isolation, and the test-only inspection helpers. The registry is cleared in
tearDown to prevent cross-test pollution.
"""

import unittest

import cosa.config.cache_registry as cr


class TestCacheRegistry( unittest.TestCase ):
    """register_invalidator + invalidate_all + inspection helpers."""

    def setUp( self ):
        cr._clear_for_tests()

    def tearDown( self ):
        cr._clear_for_tests()

    def test_register_rejects_empty_name( self ):
        with self.assertRaises( ValueError ):
            cr.register_invalidator( "", lambda: None )

    def test_register_rejects_non_callable( self ):
        with self.assertRaises( TypeError ):
            cr.register_invalidator( "x", 123 )

    def test_register_and_list_names( self ):
        cr.register_invalidator( "a", lambda: None )
        cr.register_invalidator( "b", lambda: None )
        self.assertEqual( set( cr._registered_names() ), { "a", "b" } )

    def test_reregistration_replaces( self ):
        calls = []
        cr.register_invalidator( "dup", lambda: calls.append( "old" ) )
        cr.register_invalidator( "dup", lambda: calls.append( "new" ) )
        cr.invalidate_all()
        self.assertEqual( calls, [ "new" ] )                 # only the replacement ran
        self.assertEqual( cr._registered_names(), [ "dup" ] )

    def test_invalidate_all_returns_succeeded_names( self ):
        ran = []
        cr.register_invalidator( "one", lambda: ran.append( 1 ) )
        cr.register_invalidator( "two", lambda: ran.append( 2 ) )
        succeeded = cr.invalidate_all()
        self.assertEqual( set( succeeded ), { "one", "two" } )
        self.assertEqual( len( ran ), 2 )

    def test_invalidate_all_isolates_failures( self ):
        def boom():
            raise RuntimeError( "kaboom" )

        ok = []
        cr.register_invalidator( "good", lambda: ok.append( 1 ) )
        cr.register_invalidator( "bad", boom )
        succeeded = cr.invalidate_all()
        # The good invalidator still runs despite the bad one raising.
        self.assertIn( "good", succeeded )
        self.assertNotIn( "bad", succeeded )
        failures = cr._last_run_failures()
        self.assertEqual( len( failures ), 1 )
        self.assertEqual( failures[ 0 ][ 0 ], "bad" )
        self.assertIsInstance( failures[ 0 ][ 1 ], RuntimeError )

    def test_clear_for_tests_empties_registry_and_ledger( self ):
        cr.register_invalidator( "x", lambda: ( _ for _ in () ).throw( ValueError() ) )
        cr.invalidate_all()
        cr._clear_for_tests()
        self.assertEqual( cr._registered_names(), [] )
        self.assertEqual( cr._last_run_failures(), [] )


if __name__ == "__main__":
    unittest.main()
