"""
Unit tests for the multiplexer client-config router (`cosa.rest.routers.multiplexer_config`).

Covers:
- `get_multiplexer_config` endpoint — sources `multiplexer max meta display bytes`
  AND `tts preview fraction` (Lane E WP13/F6) from the injected ConfigurationManager
  and returns a MultiplexerConfigResponse.
- The default-value wiring (the endpoint passes `default=256000, return_type="int"`
  for the byte cap and `default=0.25, return_type="float"` for the preview fraction
  to `config_mgr.get`).
- `MultiplexerConfigResponse` model shape + router registration metadata.

Zero external dependencies — the ConfigurationManager is a boundary mock passed
explicitly to the endpoint (so the FastAPI `Depends(...)` default never surfaces
as a truthy FieldInfo on direct call). No real INI read, no network, no DB.
"""

import unittest
from unittest.mock import MagicMock
import asyncio
import time

from cosa.rest.routers.multiplexer_config import (
    router,
    get_multiplexer_config,
    MultiplexerConfigResponse,
)


class TestMultiplexerConfigRouter( unittest.TestCase ):
    """
    Unit tests for the multiplexer client-config endpoint.

    Requires:
        - cosa.rest.routers.multiplexer_config importable
        - A boundary-mock ConfigurationManager honoring .get(key, default, return_type)

    Ensures:
        - The endpoint returns the configured byte cap + TTS preview fraction
        - The default + return_type kwargs are threaded to config_mgr.get per key
        - The response model + router metadata match the contract
    """

    def setUp( self ):
        """
        Ensures:
            - A fresh MagicMock config manager is available per test, keyed to
              return per-INI-key values matching the live two-key contract
        """
        self.config_values = {
            "multiplexer max meta display bytes" : 512000,
            "tts preview fraction"               : 0.5
        }
        self.config_mgr     = MagicMock()
        self.config_mgr.get.side_effect = lambda key, default=None, return_type=None: self.config_values[ key ]

    # ---- endpoint behavior --------------------------------------------------

    def test_returns_configured_values( self ):
        """
        Ensures:
            - The per-key values returned by config_mgr.get are surfaced on the
              response model's `multiplexer_max_meta_display_bytes` and
              `tts_preview_fraction` fields
        """
        resp = asyncio.run( get_multiplexer_config( config_mgr=self.config_mgr ) )

        self.assertIsInstance( resp, MultiplexerConfigResponse )
        self.assertEqual( resp.multiplexer_max_meta_display_bytes, 512000 )
        self.assertEqual( resp.tts_preview_fraction, 0.5 )

    def test_threads_default_and_return_type_to_config_get( self ):
        """
        Ensures:
            - The endpoint queries BOTH INI keys with their documented fallback
              wiring: byte cap (default=256000, return_type="int") and preview
              fraction (default=0.25, return_type="float"), exactly one call each
        """
        from unittest.mock import call

        asyncio.run( get_multiplexer_config( config_mgr=self.config_mgr ) )

        self.config_mgr.get.assert_has_calls( [
            call(
                "multiplexer max meta display bytes",
                default     = 256000,
                return_type = "int"
            ),
            call(
                "tts preview fraction",
                default     = 0.25,
                return_type = "float"
            )
        ] )
        self.assertEqual( self.config_mgr.get.call_count, 2 )

    # ---- response model -----------------------------------------------------

    def test_response_model_stores_fields_verbatim( self ):
        """
        Ensures:
            - MultiplexerConfigResponse stores the int byte-cap and float
              preview-fraction fields verbatim (both required — no defaults)
        """
        model = MultiplexerConfigResponse(
            multiplexer_max_meta_display_bytes = 256000,
            tts_preview_fraction               = 0.25
        )
        self.assertEqual( model.multiplexer_max_meta_display_bytes, 256000 )
        self.assertEqual( model.tts_preview_fraction, 0.25 )

    # ---- router registration ------------------------------------------------

    def test_router_prefix_and_route_registered( self ):
        """
        Ensures:
            - The router carries the /api/multiplexer prefix
            - The /config GET route is registered
        """
        self.assertEqual( router.prefix, "/api/multiplexer" )
        paths = { route.path for route in router.routes }
        self.assertIn( "/api/multiplexer/config", paths )


def isolated_unit_test():
    """
    Run the multiplexer-config router unit tests in isolation.

    Ensures:
        - Executes the full TestCase and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        suite  = unittest.TestLoader().loadTestsFromTestCase( TestMultiplexerConfigRouter )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL MULTIPLEXER CONFIG ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME MULTIPLEXER CONFIG ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 MULTIPLEXER CONFIG ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Multiplexer config router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
