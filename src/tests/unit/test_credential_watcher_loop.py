"""
Unit tests for the credential watcher's MAIN LOOP — the half that restarts things.

Krishna 🦚 finding #3, pre-commit review 2026-08-01: the decision module was at
100% lines+branches while the script holding the loop, the docker calls and the
`previous_inode` bookkeeping had ZERO coverage. The 100% was measuring the half
that cannot hurt anyone. "A green tier cannot vouch for an ungated twin."

Everything here mocks the I/O boundary, so no container is touched.
"""

import importlib.util
import os
import sys
import unittest
from unittest.mock import patch

_ROOT = os.environ.get( "LUPIN_ROOT" ) or os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
os.environ.setdefault( "LUPIN_ROOT", _ROOT )

_spec = importlib.util.spec_from_file_location(
    "credential_refresh_watcher",
    os.path.join( _ROOT, "src", "scripts", "credential-refresh-watcher.py" ),
)
watcher = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( watcher )

EIGHT_H_MS = 8 * 3600 * 1000


def _healthy( now_ms ):
    return now_ms + EIGHT_H_MS


class TestMainLoopActuation( unittest.TestCase ):
    """(a)-(d) from the review: when does the loop actually pull the trigger?"""

    def _run_once( self, reads ):
        """Drive main() through len(reads) cycles, returning the act_on_refresh call count."""
        with patch.object( watcher, "read_credential_state", side_effect=reads ), \
             patch.object( watcher, "act_on_refresh" ) as act, \
             patch.object( watcher, "time" ) as fake_time:
            fake_time.time.return_value       = 1_785_600_000.0
            fake_time.sleep.return_value      = None
            fake_time.strftime.return_value   = "TEST"
            argv = sys.argv
            try:
                sys.argv = [ "watcher", "--once" ] if len( reads ) == 1 else [ "watcher" ]
                if len( reads ) == 1:
                    watcher.main()
                else:
                    # Exhaust the side_effect list, then StopIteration ends the loop.
                    with self.assertRaises( StopIteration ):
                        watcher.main()
            finally:
                sys.argv = argv
            return act.call_count

    def test_a_first_observation_does_not_act( self ):
        now = 1_785_600_000.0 * 1000
        self.assertEqual( self._run_once( [ ( 111, _healthy( now ) ) ] ), 0 )

    def test_b_unchanged_inode_does_not_act( self ):
        now = 1_785_600_000.0 * 1000
        h   = _healthy( now )
        self.assertEqual( self._run_once( [ ( 111, h ), ( 111, h ), ( 111, h ) ] ), 0 )

    def test_c_changed_inode_acts_exactly_once( self ):
        now = 1_785_600_000.0 * 1000
        h   = _healthy( now )
        self.assertEqual( self._run_once( [ ( 111, h ), ( 222, h ) ] ), 1 )

    def test_d_a_settled_inode_does_not_re_fire( self ):
        # THE ANTI-STORM TEST. After acting, the loop must not act again on the
        # same inode — otherwise a single host refresh becomes a restart loop on
        # the fleet's notify channel every 60s.
        now = 1_785_600_000.0 * 1000
        h   = _healthy( now )
        reads = [ ( 111, h ), ( 222, h ), ( 222, h ), ( 222, h ), ( 222, h ) ]
        self.assertEqual( self._run_once( reads ), 1 )

    def test_two_separate_refreshes_act_twice( self ):
        # CONTROL for test_d: if the anti-storm guard were over-tight and simply
        # never fired again, this would read 1 instead of 2 and test_d's green
        # would be meaningless.
        now = 1_785_600_000.0 * 1000
        h   = _healthy( now )
        reads = [ ( 111, h ), ( 222, h ), ( 222, h ), ( 333, h ), ( 333, h ) ]
        self.assertEqual( self._run_once( reads ), 2 )

    def test_unreadable_credential_does_not_act_and_keeps_the_baseline( self ):
        # A transient read failure must not be mistaken for a change, and must not
        # wipe the baseline into None (which would make the NEXT read a "first
        # observation" and silently skip a real refresh).
        now = 1_785_600_000.0 * 1000
        h   = _healthy( now )
        reads = [ ( 111, h ), ( None, None ), ( 111, h ) ]
        self.assertEqual( self._run_once( reads ), 0 )


class TestTestContainerIsNeverRestarted( unittest.TestCase ):
    """
    Krishna finding #1 — the blocker. The watcher must REPORT on :8000 and never
    restart it. This is the test that keeps the fix from silently regressing.
    """

    def test_act_on_refresh_never_issues_a_docker_restart( self ):
        calls = []
        with patch.object( watcher, "bounce_dev", return_value=True ), \
             patch.object( watcher, "probe_container", return_value=( True, "PONG" ) ), \
             patch.object( watcher, "docker_ps", return_value="idle ps" ), \
             patch.object( watcher.subprocess, "run", side_effect=lambda *a, **k: calls.append( a ) ):
            watcher.act_on_refresh()
        self.assertEqual( calls, [], f"watcher shelled out during act_on_refresh: {calls}" )

    def test_no_restart_helper_survives_in_the_module( self ):
        # The arm was a named function. If someone reintroduces it, say so loudly.
        self.assertFalse( hasattr( watcher, "restart_test" ),
                          "restart_test() is back — :8000 must not be restarted unattended" )

    def test_a_stranded_test_container_is_REPORTED_not_fixed( self ):
        logs = []
        with patch.object( watcher, "bounce_dev", return_value=True ), \
             patch.object( watcher, "docker_ps", return_value="idle ps" ), \
             patch.object( watcher, "log", side_effect=lambda m: logs.append( m ) ), \
             patch.object( watcher, "probe_container" ) as probe:
            probe.side_effect = [ ( True, "PONG" ), ( False, "401 revoked" ) ]   # dev ok, test stranded
            watcher.act_on_refresh()
        joined = " ".join( logs )
        self.assertIn( "STRANDED", joined )
        self.assertIn( "NOT restarting", joined )
        self.assertIn( "docker restart lupin-rest-test", joined, "the human remedy must be named in the log" )

    def test_control_a_healthy_test_container_is_not_reported_as_stranded( self ):
        # CONTROL: if the report fired regardless of state, the test above would
        # pass while the watcher cried wolf 3x a day.
        logs = []
        with patch.object( watcher, "bounce_dev", return_value=True ), \
             patch.object( watcher, "log", side_effect=lambda m: logs.append( m ) ), \
             patch.object( watcher, "probe_container", return_value=( True, "PONG" ) ):
            watcher.act_on_refresh()
        joined = " ".join( logs )
        self.assertNotIn( "STRANDED", joined )
        self.assertIn( "nothing to do", joined )


if __name__ == "__main__":
    unittest.main()
