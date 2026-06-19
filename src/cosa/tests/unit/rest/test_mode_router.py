"""
Unit tests for the mode-management router (`cosa.rest.routers.mode`).

Covers:
- `get_todo_queue` — pulls jobs_todo_queue off `lupin_app.main` (dual-key patched).
- `_get_display_name` — System (None), MODE_METADATA hit, title-cased fallback.
- `get_available_modes` / `get_mode` / `set_mode` / `clear_mode` endpoints,
  including the 400-on-ValueError arm and the system-mode (None) branches.

Zero external dependencies — the todo queue is boundary-mocked, the auth
dependency is bypassed by passing `current_user` explicitly, MODE_METADATA is
patched to a controlled dict, and `lupin_app.main` is dual-key patched.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.mode import (
    router,
    get_todo_queue,
    _get_display_name,
    get_available_modes,
    get_mode,
    set_mode,
    clear_mode,
    ModeSetRequest,
    ModeResponse,
    ModeChangeResponse,
    AvailableModesResponse,
)


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `lupin_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": mock_main } )


_FAKE_METADATA = { "math": { "display_name": "Math Agent" } }


class TestGetTodoQueue( unittest.TestCase ):
    """
    Ensures:
        - get_todo_queue returns main_module.jobs_todo_queue
    """

    def test_returns_main_module_todo_queue( self ):
        """Ensures: the dependency reads jobs_todo_queue off lupin_app.main."""
        mock_main = MagicMock()
        mock_main.jobs_todo_queue = "THE_QUEUE"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_todo_queue(), "THE_QUEUE" )


class TestGetDisplayName( unittest.TestCase ):
    """
    Unit tests for `_get_display_name`.

    Ensures:
        - None → "System"; known key → metadata display_name; unknown → title-cased
    """

    def test_none_returns_system( self ):
        """Ensures: None maps to 'System'."""
        self.assertEqual( _get_display_name( None ), "System" )

    def test_known_mode_returns_metadata_display_name( self ):
        """Ensures: a key in MODE_METADATA returns its display_name."""
        with patch( "cosa.rest.routers.mode.MODE_METADATA", _FAKE_METADATA ):
            self.assertEqual( _get_display_name( "math" ), "Math Agent" )

    def test_unknown_mode_title_cased( self ):
        """Ensures: a key absent from MODE_METADATA falls back to title()."""
        with patch( "cosa.rest.routers.mode.MODE_METADATA", _FAKE_METADATA ):
            self.assertEqual( _get_display_name( "unknown" ), "Unknown" )


class TestModeEndpoints( unittest.TestCase ):
    """
    Unit tests for the four mode endpoints.

    Requires:
        - todo_queue boundary-mocked

    Ensures:
        - available/current/set/clear return correctly-shaped responses
        - set_mode raises 400 on ValueError; None mode → system-mode branch
    """

    def setUp( self ):
        """Ensures: a fresh user + mocked todo queue per test."""
        self.user  = { "uid": "user_123" }
        self.queue = MagicMock()

    def test_get_available_modes( self ):
        """Ensures: queue.get_available_modes maps to ModeInfo list."""
        self.queue.get_available_modes.return_value = [
            { "key": "math", "display_name": "Math Agent", "description": "calc" },
        ]
        resp = asyncio.run( get_available_modes( current_user=self.user, todo_queue=self.queue ) )
        self.assertIsInstance( resp, AvailableModesResponse )
        self.assertEqual( resp.modes[ 0 ].key, "math" )

    def test_get_mode_active( self ):
        """Ensures: a non-None current mode reports is_system_mode False."""
        self.queue.get_user_mode.return_value = "math"
        with patch( "cosa.rest.routers.mode.MODE_METADATA", _FAKE_METADATA ):
            resp = asyncio.run( get_mode( current_user=self.user, todo_queue=self.queue ) )
        self.assertIsInstance( resp, ModeResponse )
        self.assertEqual( resp.mode, "math" )
        self.assertEqual( resp.display_name, "Math Agent" )
        self.assertFalse( resp.is_system_mode )

    def test_get_mode_system( self ):
        """Ensures: a None current mode reports is_system_mode True / 'System'."""
        self.queue.get_user_mode.return_value = None
        resp = asyncio.run( get_mode( current_user=self.user, todo_queue=self.queue ) )
        self.assertIsNone( resp.mode )
        self.assertEqual( resp.display_name, "System" )
        self.assertTrue( resp.is_system_mode )

    def test_set_mode_success( self ):
        """Ensures: set_mode returns previous mode + change message on success."""
        self.queue.set_user_mode.return_value = "calendar"
        with patch( "cosa.rest.routers.mode.MODE_METADATA", _FAKE_METADATA ):
            resp = asyncio.run( set_mode(
                request=ModeSetRequest( mode="math" ),
                current_user=self.user, todo_queue=self.queue,
            ) )
        self.assertIsInstance( resp, ModeChangeResponse )
        self.assertEqual( resp.mode, "math" )
        self.assertEqual( resp.previous_mode, "calendar" )
        self.assertEqual( resp.message, "Mode changed to Math Agent" )
        self.assertFalse( resp.is_system_mode )

    def test_set_mode_none_is_system( self ):
        """Ensures: setting mode=None reports the system-mode branch."""
        self.queue.set_user_mode.return_value = "math"
        resp = asyncio.run( set_mode(
            request=ModeSetRequest( mode=None ),
            current_user=self.user, todo_queue=self.queue,
        ) )
        self.assertIsNone( resp.mode )
        self.assertTrue( resp.is_system_mode )
        self.assertEqual( resp.display_name, "System" )

    def test_set_mode_value_error_raises_400( self ):
        """Ensures: a ValueError from the queue becomes HTTPException 400."""
        self.queue.set_user_mode.side_effect = ValueError( "bad mode" )
        with self.assertRaises( HTTPException ) as ctx:
            asyncio.run( set_mode(
                request=ModeSetRequest( mode="nope" ),
                current_user=self.user, todo_queue=self.queue,
            ) )
        self.assertEqual( ctx.exception.status_code, 400 )
        self.assertEqual( ctx.exception.detail, "bad mode" )

    def test_clear_mode( self ):
        """Ensures: clear_mode returns to system mode with previous captured."""
        self.queue.clear_user_mode.return_value = "math"
        resp = asyncio.run( clear_mode( current_user=self.user, todo_queue=self.queue ) )
        self.assertIsNone( resp.mode )
        self.assertTrue( resp.is_system_mode )
        self.assertEqual( resp.previous_mode, "math" )
        self.assertEqual( resp.message, "Returned to System mode" )


class TestModeRouterRegistration( unittest.TestCase ):
    """
    Ensures:
        - Router prefix + all mode routes are registered
    """

    def test_router_prefix_and_routes( self ):
        """Ensures: /api/mode prefix with available + current routes."""
        self.assertEqual( router.prefix, "/api/mode" )
        paths = { route.path for route in router.routes }
        self.assertIn( "/api/mode/available", paths )
        self.assertIn( "/api/mode/current", paths )


def isolated_unit_test():
    """
    Run the mode router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetTodoQueue, TestGetDisplayName, TestModeEndpoints, TestModeRouterRegistration,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL MODE ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME MODE ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 MODE ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Mode router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
