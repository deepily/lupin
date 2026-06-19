"""
Unit tests for the pages router (`cosa.rest.routers.pages`).

The pages router maps clean `/app/*` URLs to static HTML files via FileResponse.
Each endpoint is a thin wrapper that looks up its relative path in `_ROUTE_TABLE`
and delegates to `_serve_file`.

Covers:
- `_serve_file` — builds a FileResponse with media_type text/html and a
  `Cache-Control: no-cache` header, rooted under the resolved static dir.
- Every registered `/app/*` endpoint — invoked through the router's route table
  so each one-line handler is exercised and asserted against `_ROUTE_TABLE`.
- `/app/notifications` cutover redirect — all branches of the
  `legacy notifications redirect enabled` flag × `?classic` escape hatch,
  plus an HTTP-layer 302 assertion through TestClient.

Zero external dependencies — `FileResponse` is boundary-mocked so no file is
read from disk; we assert the construction arguments, not real I/O.
"""

import unittest
from unittest.mock import patch, MagicMock
import asyncio
import os
import time

from fastapi.routing import APIRoute

from cosa.rest.routers import pages
from cosa.rest.routers.pages import router, _serve_file, _ROUTE_TABLE, _static_dir


class TestServeFile( unittest.TestCase ):
    """
    Unit tests for the `_serve_file` helper.

    Requires:
        - cosa.rest.routers.pages importable
        - FileResponse boundary-mocked

    Ensures:
        - FileResponse is built with the joined static path, text/html media type,
          and the no-cache revalidation header
    """

    def test_builds_file_response_with_no_cache_header( self ):
        """
        Ensures:
            - _serve_file joins relative_path under _static_dir
            - media_type is text/html and Cache-Control: no-cache is set
        """
        with patch( "cosa.rest.routers.pages.FileResponse" ) as mock_fr:
            mock_fr.return_value = "RESPONSE"
            result = _serve_file( "html/landing.html" )

        self.assertEqual( result, "RESPONSE" )
        mock_fr.assert_called_once_with(
            os.path.join( _static_dir, "html/landing.html" ),
            media_type = "text/html",
            headers    = { "Cache-Control": "no-cache" },
        )


class TestPagesEndpoints( unittest.TestCase ):
    """
    Unit tests for every `/app/*` page endpoint.

    Requires:
        - The router exposes one APIRoute per `_ROUTE_TABLE` entry

    Ensures:
        - Each endpoint serves the file mapped to its path in `_ROUTE_TABLE`
        - The full route table is registered (no missing/extra routes)
    """

    def test_every_endpoint_serves_its_mapped_file( self ):
        """
        Ensures:
            - Invoking each registered endpoint calls FileResponse with the
              static path that `_ROUTE_TABLE` maps its URL to
        """
        config_off = MagicMock()
        config_off.get.return_value = False

        with patch( "cosa.rest.routers.pages.FileResponse" ) as mock_fr:
            mock_fr.side_effect = lambda path, **kw: path

            served = {}
            for route in router.routes:
                if not isinstance( route, APIRoute ):
                    continue
                if route.path == "/app/notifications":
                    returned_path = asyncio.run( route.endpoint( classic=False, config_mgr=config_off ) )
                else:
                    returned_path = asyncio.run( route.endpoint() )
                served[ route.path ] = returned_path

        # Every route in _ROUTE_TABLE was served with the correct static path
        self.assertEqual( set( served.keys() ), set( _ROUTE_TABLE.keys() ) )
        for url, relative in _ROUTE_TABLE.items():
            self.assertEqual( served[ url ], os.path.join( _static_dir, relative ) )

    def test_route_table_count_matches_registered_routes( self ):
        """
        Ensures:
            - The number of registered API routes equals the route-table size
              (guards against an endpoint added without a table entry)
        """
        api_routes = [ r for r in router.routes if isinstance( r, APIRoute ) ]
        self.assertEqual( len( api_routes ), len( _ROUTE_TABLE ) )

    def test_static_dir_is_normalized_absolute( self ):
        """
        Ensures:
            - The import-time static dir resolved to a normalized absolute path
              ending in lupin_app/static
        """
        self.assertTrue( os.path.isabs( _static_dir ) )
        self.assertTrue( _static_dir.endswith( os.path.join( "lupin_app", "static" ) ) )


class TestNotificationsRedirect( unittest.TestCase ):
    """
    Unit tests for the `/app/notifications` Saturday-cutover redirect.

    Requires:
        - page_notifications gates on the `legacy notifications redirect enabled`
          INI key (boundary-mocked ConfigurationManager)

    Ensures:
        - Flag OFF serves the legacy file
        - Flag ON returns a 302 RedirectResponse to /app/multiplexer
        - Flag ON + classic=True serves the legacy file (escape hatch)
        - The HTTP layer surfaces the 302 + Location header end-to-end
    """

    def _config_returning( self, enabled ):
        config_mgr = MagicMock()
        config_mgr.get.return_value = enabled
        return config_mgr

    def test_flag_off_serves_legacy_file( self ):
        """
        Ensures:
            - With the flag False, the legacy notifications.html path is served
            - The flag is read with the documented key, default, and type
        """
        config_mgr = self._config_returning( False )
        with patch( "cosa.rest.routers.pages.FileResponse" ) as mock_fr:
            mock_fr.side_effect = lambda path, **kw: path
            result = asyncio.run( pages.page_notifications( classic=False, config_mgr=config_mgr ) )

        self.assertEqual( result, os.path.join( _static_dir, "html/notifications.html" ) )
        config_mgr.get.assert_called_once_with(
            "legacy notifications redirect enabled", default=False, return_type="boolean"
        )

    def test_flag_on_redirects_to_multiplexer( self ):
        """
        Ensures:
            - With the flag True and no classic escape, a 302 RedirectResponse
              targeting /app/multiplexer is returned
        """
        from fastapi.responses import RedirectResponse

        config_mgr = self._config_returning( True )
        result     = asyncio.run( pages.page_notifications( classic=False, config_mgr=config_mgr ) )

        self.assertIsInstance( result, RedirectResponse )
        self.assertEqual( result.status_code, 302 )
        self.assertEqual( result.headers[ "location" ], "/app/multiplexer" )

    def test_flag_on_classic_escape_serves_legacy_file( self ):
        """
        Ensures:
            - With the flag True but classic=True, the legacy page is still
              served (E2E-suite / "Classic UI" escape hatch)
        """
        config_mgr = self._config_returning( True )
        with patch( "cosa.rest.routers.pages.FileResponse" ) as mock_fr:
            mock_fr.side_effect = lambda path, **kw: path
            result = asyncio.run( pages.page_notifications( classic=True, config_mgr=config_mgr ) )

        self.assertEqual( result, os.path.join( _static_dir, "html/notifications.html" ) )

    def test_redirect_via_http_layer( self ):
        """
        Ensures:
            - A real GET /app/notifications through TestClient returns 302 with
              Location: /app/multiplexer when the flag is on
            - Adding ?classic=1 suppresses the redirect (200, text/html)
        """
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cosa.rest.dependencies.config import get_config_manager

        app = FastAPI()
        app.include_router( router )
        app.dependency_overrides[ get_config_manager ] = lambda: self._config_returning( True )

        client   = TestClient( app )
        redirect = client.get( "/app/notifications", follow_redirects=False )
        self.assertEqual( redirect.status_code, 302 )
        self.assertEqual( redirect.headers[ "location" ], "/app/multiplexer" )

        classic = client.get( "/app/notifications?classic=1", follow_redirects=False )
        self.assertEqual( classic.status_code, 200 )
        self.assertTrue( classic.headers[ "content-type" ].startswith( "text/html" ) )


def isolated_unit_test():
    """
    Run the pages router unit tests in isolation.

    Ensures:
        - Executes both TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        suite.addTests( loader.loadTestsFromTestCase( TestServeFile ) )
        suite.addTests( loader.loadTestsFromTestCase( TestPagesEndpoints ) )
        suite.addTests( loader.loadTestsFromTestCase( TestNotificationsRedirect ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL PAGES ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME PAGES ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 PAGES ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Pages router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
