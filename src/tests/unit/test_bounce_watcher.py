"""
Behavioral test for src/scripts/bounce-watcher.sh (row 1b4211ac R2 — button path).

The watcher is the host-side half the endpoint hands off to. It must, without any
real Docker, prove three things the endpoint depends on:

  1. it stamps a FRESH heartbeat file continuously (the endpoint's liveness check),
  2. it CLAIMS a trigger file (deletes it) and runs the bounce script exactly once,
  3. it clears the in-progress marker when the bounce finishes.

We run the REAL watcher script against a throwaway LUPIN_ROOT whose
src/scripts/bounce-dev-server.sh is a STUB that records its invocation — so no
container is touched. bash + date only; no DB, no network.
"""

import os
import shutil
import subprocess
import tempfile
import time
import unittest


REPO_ROOT     = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
WATCHER       = os.path.join( REPO_ROOT, "src", "scripts", "bounce-watcher.sh" )
POLL_SECS     = 1
CONFIG_NAME   = "lupin-app" + ".ini"
SWITCH_KEY    = "cron job side-services " + "enabled"


def _wait_for( predicate, timeout=8.0, interval=0.1 ):
    """Poll predicate() until true or timeout; return its final truthiness."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep( interval )
    return predicate()


class TestBounceWatcher( unittest.TestCase ):

    def setUp( self ):
        self.root = tempfile.mkdtemp( prefix="watcher-test-" )
        scripts   = os.path.join( self.root, "src", "scripts" )
        os.makedirs( scripts, exist_ok=True )
        self.bounce_dir = os.path.join( self.root, "io", "bounce" )
        self.heartbeat  = os.path.join( self.bounce_dir, "watcher-heartbeat" )
        self.trigger    = os.path.join( self.bounce_dir, "bounce.trigger" )
        self.inprogress = os.path.join( self.bounce_dir, "bounce.inprogress" )
        self.ran_marker = os.path.join( self.root, "bounce-script-ran" )

        # Stub the sanctioned bounce script: append a line each time it runs, and
        # sleep briefly so the in-progress window is observable.
        stub = os.path.join( scripts, "bounce-dev-server.sh" )
        with open( stub, "w" ) as f:
            f.write(
                "#!/usr/bin/env bash\n"
                f"echo run >> {self.ran_marker}\n"
                "sleep 1\n"
                "exit 0\n"
            )
        os.chmod( stub, 0o755 )

        # The watcher reads the side-services switch through lupin_mcp.cron_switch_read, so the
        # throwaway root carries the real package (a link) and a config file that holds the key.
        os.symlink( os.path.join( REPO_ROOT, "src", "lupin_mcp" ), os.path.join( self.root, "src", "lupin_mcp" ) )
        self.config   = os.path.join( self.root, "src", "conf", CONFIG_NAME )
        self.log_file = os.path.join( self.root, "watcher.log" )
        os.makedirs( os.path.dirname( self.config ), exist_ok=True )
        self._set_switch( "true" )

        env = dict( os.environ )
        env[ "LUPIN_ROOT" ]                 = self.root
        env[ "BOUNCE_WATCHER_POLL_SECS" ]   = str( POLL_SECS )
        env[ "BOUNCE_WATCHER_SWITCH_SECS" ] = "1"
        self.log_handle = open( self.log_file, "w" )
        self.proc = subprocess.Popen(
            [ "bash", WATCHER ], env=env,
            stdout=self.log_handle, stderr=subprocess.STDOUT,
        )

    def tearDown( self ):
        self.proc.terminate()
        try:
            self.proc.wait( timeout=5 )
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log_handle.close()
        shutil.rmtree( self.root, ignore_errors=True )

    def _set_switch( self, value ):
        """Write the config file with the switch set to value, or without the key when value is None."""
        with open( self.config, "w" ) as f:
            f.write( "[Lupin: Development]\n" )
            if value is not None: f.write( f"{SWITCH_KEY} = {value}\n" )

    def _log( self ):
        with open( self.log_file ) as f:
            return f.read()

    def _run_count( self ):
        if not os.path.exists( self.ran_marker ):
            return 0
        with open( self.ran_marker ) as f:
            return len( [ ln for ln in f.read().splitlines() if ln.strip() ] )

    def test_heartbeat_is_stamped_and_stays_fresh( self ):
        self.assertTrue( _wait_for( lambda: os.path.exists( self.heartbeat ) ),
                         "watcher never stamped a heartbeat" )
        with open( self.heartbeat ) as f:
            first = int( f.read().strip() )
        # It must keep beating, not stamp once and die.
        self.assertTrue(
            _wait_for( lambda: _read_int( self.heartbeat ) > first, timeout=4.0 ),
            "heartbeat did not advance — watcher is not looping"
        )

    def test_trigger_is_claimed_and_bounce_runs_once( self ):
        self.assertTrue( _wait_for( lambda: os.path.exists( self.heartbeat ) ) )
        # Drop a trigger exactly as the endpoint would.
        with open( self.trigger, "w" ) as f:
            f.write( str( int( time.time() ) ) )

        # The watcher claims (deletes) the trigger...
        self.assertTrue( _wait_for( lambda: not os.path.exists( self.trigger ) ),
                         "trigger was never claimed" )
        # ...and runs the bounce script...
        self.assertTrue( _wait_for( lambda: self._run_count() >= 1 ),
                         "bounce script never ran" )
        # ...and clears the in-progress marker afterward.
        self.assertTrue( _wait_for( lambda: not os.path.exists( self.inprogress ) ),
                         "in-progress marker was left stranded" )

        # Exactly once — a single trigger must not re-run the bounce.
        time.sleep( POLL_SECS * 2 )
        self.assertEqual( self._run_count(), 1, "bounce ran more than once for one trigger" )

    def _assert_idle_while( self, value ):
        """With the switch at value: no heartbeat, a dropped trigger is discarded and no bounce runs."""
        self.assertTrue( _wait_for( lambda: os.path.exists( self.heartbeat ) ) )
        self._set_switch( value )
        needle = "is false" if value == "false" else "is missing or holds neither"
        self.assertTrue( _wait_for( lambda: needle in self._log(), timeout=6.0 ), self._log() )
        time.sleep( POLL_SECS + 0.5 )
        os.remove( self.heartbeat )
        with open( self.trigger, "w" ) as f: f.write( str( int( time.time() ) ) )
        self.assertTrue( _wait_for( lambda: not os.path.exists( self.trigger ) ), "trigger was left on disk" )
        time.sleep( POLL_SECS * 2 )
        self.assertFalse( os.path.exists( self.heartbeat ), "an idle watcher stamped a heartbeat" )
        self.assertEqual( self._run_count(), 0, "an idle watcher ran the bounce" )
        self.assertIn( "discarded a trigger", self._log() )

    def test_switch_false_stamps_no_heartbeat_and_discards_a_trigger_then_true_resumes( self ):
        self._assert_idle_while( "false" )
        self._set_switch( "true" )
        self.assertTrue( _wait_for( lambda: os.path.exists( self.heartbeat ), timeout=6.0 ), "the watcher did not resume" )
        self.assertIn( "is true, so the watcher runs again", self._log() )
        with open( self.trigger, "w" ) as f: f.write( str( int( time.time() ) ) )
        self.assertTrue( _wait_for( lambda: self._run_count() >= 1 ), "a trigger after resuming did not bounce" )

    def test_a_missing_key_idles_the_watcher_and_logs_one_error_line( self ):
        self._assert_idle_while( None )
        time.sleep( 2.5 )
        self.assertEqual( self._log().count( f"ERROR: INI key '{SWITCH_KEY}'" ), 1, "the error line repeated or was absent" )

    def test_a_word_that_is_neither_true_nor_false_idles_the_watcher( self ):
        self._assert_idle_while( "yes" )


class TestBounceWatcherWithNoConfigFile( unittest.TestCase ):

    def test_an_unreadable_config_path_never_reads_as_on( self ):
        root = tempfile.mkdtemp( prefix="watcher-test-noconfig-" )
        try:
            os.makedirs( os.path.join( root, "src", "scripts" ) )
            os.symlink( os.path.join( REPO_ROOT, "src", "lupin_mcp" ), os.path.join( root, "src", "lupin_mcp" ) )
            env  = dict( os.environ, LUPIN_ROOT=root, BOUNCE_WATCHER_POLL_SECS="1", BOUNCE_WATCHER_SWITCH_SECS="1" )
            proc = subprocess.Popen( [ "bash", WATCHER ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
            try:
                time.sleep( 3 )
                self.assertFalse( os.path.exists( os.path.join( root, "io", "bounce", "watcher-heartbeat" ) ) )
            finally:
                proc.terminate()
                proc.wait( timeout=5 )
        finally:
            shutil.rmtree( root, ignore_errors=True )


def _read_int( path ):
    try:
        with open( path ) as f:
            return int( f.read().strip() )
    except ( FileNotFoundError, ValueError ):
        return -1


if __name__ == "__main__":
    unittest.main()
