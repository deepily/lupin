"""
Unit tests for the managed dev-server bounce endpoint (POST /api/system/bounce).

The endpoint is the web-client button path for row 1b4211ac R2. It never restarts
the server itself — it drops a trigger file the host-side watcher acts on — so these
tests pin the ONE job it does own: refusing to lie. A press must return

    409  when a bounce is already in progress   (in-progress marker fresh)
    503  when the watcher is not running        (heartbeat missing or stale)
    202  and write the trigger                   (watcher alive, nothing running)

Every arm has its negative control in the same run: the 503-on-stale test is paired
with a 202-on-fresh test over the SAME heartbeat file, so a bug that ignored the
heartbeat entirely could not pass both. Filesystem only — no server, no network.
"""

import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

import cosa.rest.routers.system as system
from cosa.rest.routers.system import (
    bounce_dev_server,
    _bounce_paths,
    _read_epoch,
    _BOUNCE_HEARTBEAT_STALE_SECS,
    _BOUNCE_INPROGRESS_MAX_SECS,
)


def _call( ):
    """Invoke the async endpoint and return (status_code, parsed_body)."""
    resp = asyncio.run( bounce_dev_server( current_user={ "uid": "test" } ) )
    return resp.status_code, json.loads( resp.body )


class TestBouncePaths( unittest.TestCase ):

    def test_paths_are_rooted_under_io_bounce( self ):
        with patch.object( system.du, "get_project_root", return_value="/var/lupin" ):
            base, heartbeat, trigger, inprogress = _bounce_paths()
        self.assertEqual( base,       "/var/lupin/io/bounce" )
        self.assertEqual( heartbeat,  "/var/lupin/io/bounce/watcher-heartbeat" )
        self.assertEqual( trigger,    "/var/lupin/io/bounce/bounce.trigger" )
        self.assertEqual( inprogress, "/var/lupin/io/bounce/bounce.inprogress" )

    def test_read_epoch_missing_file_is_none( self ):
        self.assertIsNone( _read_epoch( "/no/such/file/anywhere" ) )

    def test_read_epoch_garbage_is_none( self ):
        with tempfile.NamedTemporaryFile( "w", suffix=".hb", delete=False ) as f:
            f.write( "not-a-number" )
            path = f.name
        try:
            self.assertIsNone( _read_epoch( path ) )
        finally:
            os.unlink( path )

    def test_read_epoch_reads_integer( self ):
        with tempfile.NamedTemporaryFile( "w", suffix=".hb", delete=False ) as f:
            f.write( "  1754000000  \n" )
            path = f.name
        try:
            self.assertEqual( _read_epoch( path ), 1754000000 )
        finally:
            os.unlink( path )


class TestBounceEndpoint( unittest.TestCase ):

    def setUp( self ):
        self.tmp  = tempfile.mkdtemp( prefix="bounce-test-" )
        self.base = os.path.join( self.tmp, "io", "bounce" )
        os.makedirs( self.base, exist_ok=True )
        # get_project_root() + "/io/bounce" must equal self.base.
        self._patch = patch.object( system.du, "get_project_root", return_value=self.tmp )
        self._patch.start()

    def tearDown( self ):
        self._patch.stop()
        import shutil
        shutil.rmtree( self.tmp, ignore_errors=True )

    def _write( self, name, epoch ):
        with open( os.path.join( self.base, name ), "w" ) as f:
            f.write( str( int( epoch ) ) )

    def _trigger_exists( self ):
        return os.path.exists( os.path.join( self.base, "bounce.trigger" ) )

    # ── watcher-not-running ⇒ 503 ────────────────────────────────────
    def test_missing_heartbeat_returns_503_and_writes_no_trigger( self ):
        code, body = _call()
        self.assertEqual( code, 503 )
        self.assertEqual( body[ "status" ], "watcher_unavailable" )
        self.assertIn( "not running", body[ "reason" ] )
        self.assertFalse( self._trigger_exists() )

    def test_stale_heartbeat_returns_503( self ):
        # One second past the staleness threshold ⇒ watcher considered dead.
        self._write( "watcher-heartbeat", time.time() - ( _BOUNCE_HEARTBEAT_STALE_SECS + 1 ) )
        code, body = _call()
        self.assertEqual( code, 503 )
        self.assertFalse( self._trigger_exists() )

    # ── watcher alive ⇒ 202 + trigger written (control for the stale test) ──
    def test_fresh_heartbeat_returns_202_and_writes_trigger( self ):
        self._write( "watcher-heartbeat", time.time() )
        code, body = _call()
        self.assertEqual( code, 202 )
        self.assertEqual( body[ "status" ], "triggered" )
        self.assertTrue( self._trigger_exists() )

    def test_heartbeat_exactly_at_threshold_is_still_alive( self ):
        # now - hb == threshold is NOT "> threshold", so it must still be accepted.
        self._write( "watcher-heartbeat", time.time() - _BOUNCE_HEARTBEAT_STALE_SECS )
        code, _ = _call()
        self.assertEqual( code, 202 )

    # ── already bouncing ⇒ 409, checked before the heartbeat ─────────
    def test_fresh_inprogress_returns_409_even_with_fresh_heartbeat( self ):
        self._write( "watcher-heartbeat", time.time() )
        self._write( "bounce.inprogress", time.time() )
        code, body = _call()
        self.assertEqual( code, 409 )
        self.assertEqual( body[ "status" ], "in_progress" )
        self.assertFalse( self._trigger_exists() )

    def test_inprogress_takes_precedence_over_stale_heartbeat( self ):
        # A heartbeat goes stale DURING a bounce (the watcher is busy). The endpoint
        # must answer 409 "already bouncing", not 503 "watcher dead".
        self._write( "watcher-heartbeat", time.time() - ( _BOUNCE_HEARTBEAT_STALE_SECS + 5 ) )
        self._write( "bounce.inprogress", time.time() )
        code, body = _call()
        self.assertEqual( code, 409 )

    def test_stale_inprogress_is_ignored_so_a_new_bounce_can_run( self ):
        # A crash could strand the in-progress marker; past the max it must not block
        # a real bounce forever.
        self._write( "watcher-heartbeat", time.time() )
        self._write( "bounce.inprogress", time.time() - ( _BOUNCE_INPROGRESS_MAX_SECS + 1 ) )
        code, _ = _call()
        self.assertEqual( code, 202 )
        self.assertTrue( self._trigger_exists() )


if __name__ == "__main__":
    unittest.main()
