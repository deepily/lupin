"""
Unit tests for the speakerphone router (`cosa.rest.routers.speakerphone`).

Covers:
- `get_notification_queue` — pulls jobs_notification_queue off fastapi_app.main.
- `get_speakerphone_endpoint` — 404 (no bridge) + 200 read.
- `set_speakerphone_endpoint` — 404, solo activate (displace loop: success,
  displace-write-fail skip, displace-notify push failure, displace-action push
  failure), solo self-write 500, chorus activate (success + 500), deactivate
  (success + 500), broadcast failure, and self-disable action push failure.

Zero external dependencies — the session-bridge helpers, tts-mode helper, and
the notification queue are all boundary-mocked. No real bridge files, no WS, no
disk. Auth bypassed by passing authenticated_user_id explicitly.
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import asyncio
import sys
import time

from fastapi import HTTPException

from cosa.rest.routers.speakerphone import (
    get_notification_queue,
    get_speakerphone_endpoint,
    set_speakerphone_endpoint,
    SpeakerphoneBody,
)

SP = "cosa.rest.routers.speakerphone"


def _patch_fastapi_main( mock_main ):
    """Dual-key patch for `fastapi_app.main` (Gotcha 1)."""
    pkg = Mock()
    pkg.main = mock_main
    return patch.dict( sys.modules, { "fastapi_app": pkg, "fastapi_app.main": mock_main } )


def _json_body( response ):
    """Extract the dict payload from a Starlette JSONResponse."""
    import json
    return json.loads( bytes( response.body ).decode() )


class TestGetNotificationQueue( unittest.TestCase ):
    """
    Ensures:
        - get_notification_queue returns main_module.jobs_notification_queue
    """

    def test_returns_main_module_notification_queue( self ):
        """Ensures: dependency reads jobs_notification_queue off fastapi_app.main."""
        mock_main = MagicMock()
        mock_main.jobs_notification_queue = "NQ"
        with _patch_fastapi_main( mock_main ):
            self.assertEqual( get_notification_queue(), "NQ" )


class TestGetSpeakerphoneEndpoint( unittest.TestCase ):
    """
    Unit tests for the GET speakerphone endpoint.

    Ensures:
        - 404 when no bridge matches; 200 + flag when it does
    """

    def test_not_found_404( self ):
        """Ensures: missing bridge raises 404."""
        with patch( f"{SP}.find_session_path_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                asyncio.run( get_speakerphone_endpoint( session_id="s1", authenticated_user_id="u" ) )
        self.assertEqual( ctx.exception.status_code, 404 )

    def test_found_returns_flag( self ):
        """Ensures: an existing bridge returns the speakerphone flag."""
        with patch( f"{SP}.find_session_path_by_id", return_value="/p/s1.json" ), \
             patch( f"{SP}.get_speakerphone", return_value=True ):
            resp = asyncio.run( get_speakerphone_endpoint( session_id="s1", authenticated_user_id="u" ) )
        body = _json_body( resp )
        self.assertEqual( body, { "session_id": "s1", "on": True } )


class TestSetSpeakerphoneEndpoint( unittest.TestCase ):
    """
    Unit tests for the POST speakerphone endpoint across all mode + best-effort arms.

    Requires:
        - bridge helpers, tts-mode, notification queue boundary-mocked

    Ensures:
        - 404, solo displace variants, chorus, deactivate, write-fail 500s, and
          best-effort push failures are all exercised
    """

    SELF = "self_sid"

    def setUp( self ):
        """Ensures: bridge helpers default to found + writable; chorus mode default."""
        self.queue = MagicMock()
        p = patch( f"{SP}.find_session_path_by_id", return_value="/p/self.json" )
        p.start(); self.addCleanup( p.stop )
        p = patch( f"{SP}.build_sender_id_for_cc", side_effect=lambda sid: f"sender-{sid}" )
        p.start(); self.addCleanup( p.stop )
        p = patch( f"{SP}.find_active_speakerphone_sessions", return_value=[] )
        self.mock_find_active = p.start(); self.addCleanup( p.stop )
        p = patch( f"{SP}.set_speakerphone", return_value=True )
        self.mock_set = p.start(); self.addCleanup( p.stop )
        p = patch( f"{SP}.cu.get_tts_interaction_mode", return_value="chorus" )
        self.mock_mode = p.start(); self.addCleanup( p.stop )

    def _post( self, on ):
        return asyncio.run( set_speakerphone_endpoint(
            session_id            = self.SELF,
            body                  = SpeakerphoneBody( on=on ),
            authenticated_user_id = "user_1",
            notification_queue    = self.queue,
        ) )

    # ---- 404 -----------------------------------------------------------------

    def test_not_found_404( self ):
        """Ensures: missing bridge raises 404 before any write."""
        with patch( f"{SP}.find_session_path_by_id", return_value=None ):
            with self.assertRaises( HTTPException ) as ctx:
                self._post( on=True )
        self.assertEqual( ctx.exception.status_code, 404 )

    # ---- solo activation -----------------------------------------------------

    def test_solo_activate_displaces_others( self ):
        """Ensures: solo activate displaces other active sessions and activates self."""
        self.mock_mode.return_value = "solo"
        self.mock_find_active.return_value = [ ( "/p/other.json", "other_sid" ) ]
        resp = self._post( on=True )
        body = _json_body( resp )
        self.assertTrue( body[ "on" ] )
        self.assertEqual( body[ "displaced_sessions" ], [ "other_sid" ] )
        self.assertTrue( body[ "broadcast_delivered" ] )
        # set_speakerphone called for the other (False) then self (True)
        self.mock_set.assert_any_call( "other_sid", False )
        self.mock_set.assert_any_call( self.SELF, True )

    def test_solo_displace_write_fail_skips_session( self ):
        """Ensures: a failed displace write skips that session (not appended)."""
        self.mock_mode.return_value = "solo"
        self.mock_find_active.return_value = [ ( "/p/other.json", "other_sid" ) ]
        # other write fails (False), self write ok (True)
        self.mock_set.side_effect = lambda sid, val: sid != "other_sid"
        resp = self._post( on=True )
        body = _json_body( resp )
        self.assertEqual( body[ "displaced_sessions" ], [] )   # other skipped
        self.assertTrue( body[ "on" ] )

    def test_solo_displace_notify_push_failure_is_swallowed( self ):
        """Ensures: a failed displace speakerphone_changed push does not abort displacement."""
        self.mock_mode.return_value = "solo"
        self.mock_find_active.return_value = [ ( "/p/other.json", "other_sid" ) ]

        def push( **kw ):
            if kw.get( "payload", {} ).get( "displaced" ):
                raise RuntimeError( "ws down" )
            return None
        self.queue.push_notification.side_effect = push

        resp = self._post( on=True )
        body = _json_body( resp )
        self.assertEqual( body[ "displaced_sessions" ], [ "other_sid" ] )   # still displaced

    def test_solo_displace_action_push_failure_is_swallowed( self ):
        """Ensures: a failed displace action push does not abort displacement."""
        self.mock_mode.return_value = "solo"
        self.mock_find_active.return_value = [ ( "/p/other.json", "other_sid" ) ]

        def push( **kw ):
            if kw.get( "title" ) == "action:disable_speakerphone":
                raise RuntimeError( "listener down" )
            return None
        self.queue.push_notification.side_effect = push

        resp = self._post( on=True )
        body = _json_body( resp )
        self.assertEqual( body[ "displaced_sessions" ], [ "other_sid" ] )

    def test_solo_self_write_fail_500( self ):
        """Ensures: a failed self write in solo mode raises 500."""
        self.mock_mode.return_value = "solo"
        self.mock_find_active.return_value = []
        self.mock_set.return_value = False    # self write fails
        with self.assertRaises( HTTPException ) as ctx:
            self._post( on=True )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- chorus activation ---------------------------------------------------

    def test_chorus_activate_success( self ):
        """Ensures: chorus activate writes self with no displacement."""
        self.mock_mode.return_value = "chorus"
        resp = self._post( on=True )
        body = _json_body( resp )
        self.assertTrue( body[ "on" ] )
        self.assertEqual( body[ "displaced_sessions" ], [] )
        self.mock_find_active.assert_not_called()   # no scan in chorus

    def test_chorus_self_write_fail_500( self ):
        """Ensures: a failed self write in chorus mode raises 500."""
        self.mock_mode.return_value = "chorus"
        self.mock_set.return_value = False
        with self.assertRaises( HTTPException ) as ctx:
            self._post( on=True )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- deactivation --------------------------------------------------------

    def test_deactivate_success_pushes_self_action( self ):
        """Ensures: deactivate writes self off, broadcasts, and pushes the self-disable action."""
        resp = self._post( on=False )
        body = _json_body( resp )
        self.assertFalse( body[ "on" ] )
        self.assertEqual( body[ "displaced_sessions" ], [] )
        self.assertTrue( body[ "broadcast_delivered" ] )
        # a self-disable action push happened (title set)
        titles = [ c.kwargs.get( "title" ) for c in self.queue.push_notification.call_args_list ]
        self.assertIn( "action:disable_speakerphone", titles )

    def test_deactivate_write_fail_500( self ):
        """Ensures: a failed deactivate write raises 500."""
        self.mock_set.return_value = False
        with self.assertRaises( HTTPException ) as ctx:
            self._post( on=False )
        self.assertEqual( ctx.exception.status_code, 500 )

    # ---- best-effort broadcast / action failures -----------------------------

    def test_broadcast_failure_sets_delivered_false( self ):
        """Ensures: a failed final broadcast yields broadcast_delivered False (not an error)."""
        self.mock_mode.return_value = "chorus"
        self.queue.push_notification.side_effect = RuntimeError( "ws down" )
        resp = self._post( on=True )   # chorus on → only the final broadcast push
        body = _json_body( resp )
        self.assertFalse( body[ "broadcast_delivered" ] )
        self.assertTrue( body[ "on" ] )

    def test_self_disable_action_failure_is_swallowed( self ):
        """Ensures: a failed self-disable action push does not fail the deactivate."""
        def push( **kw ):
            if kw.get( "title" ) == "action:disable_speakerphone":
                raise RuntimeError( "listener down" )
            return None
        self.queue.push_notification.side_effect = push
        resp = self._post( on=False )
        body = _json_body( resp )
        self.assertFalse( body[ "on" ] )
        self.assertTrue( body[ "broadcast_delivered" ] )   # broadcast still ok


def isolated_unit_test():
    """
    Run the speakerphone router unit tests in isolation.

    Ensures:
        - Executes all TestCases and reports (success, duration, message)
    """
    import cosa.utils.util as du

    start_time = time.time()
    try:
        loader = unittest.TestLoader()
        suite  = unittest.TestSuite()
        for tc in (
            TestGetNotificationQueue, TestGetSpeakerphoneEndpoint, TestSetSpeakerphoneEndpoint,
        ):
            suite.addTests( loader.loadTestsFromTestCase( tc ) )
        result = unittest.TextTestRunner( verbosity=2 ).run( suite )

        duration  = time.time() - start_time
        tests_run = result.testsRun
        failures  = len( result.failures )
        errors    = len( result.errors )

        success = failures == 0 and errors == 0
        if success:
            du.print_banner( "✅ ALL SPEAKERPHONE ROUTER TESTS PASSED", prepend_nl=True )
            message = f"All {tests_run} tests passed successfully in {duration:.3f}s"
        else:
            du.print_banner( "❌ SOME SPEAKERPHONE ROUTER TESTS FAILED", prepend_nl=True )
            message = f"{failures} failures, {errors} errors out of {tests_run} tests"

        return success, duration, message

    except Exception as e:
        duration  = time.time() - start_time
        error_msg = f"Unit test execution failed: {str(e)}"
        du.print_banner( f"💥 SPEAKERPHONE ROUTER TEST ERROR: {error_msg}", prepend_nl=True )
        return False, duration, error_msg


if __name__ == "__main__":
    success, duration, message = isolated_unit_test()
    status = "✅ PASS" if success else "❌ FAIL"
    print( f"\n{status} Speakerphone router unit tests completed in {duration:.3f}s" )
    print( f"Result: {message}" )
