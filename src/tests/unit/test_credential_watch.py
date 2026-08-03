"""
Unit tests for the container OAuth credential watcher's decision logic.

Row c7c60896 / Rick's 2026-08-01 request. The watcher restarts SHARED
infrastructure automatically, so the bar here is not "the happy path works" —
it is "every branch that could bounce the fleet for no reason, or restart onto
a dead token, is pinned."

Each guard carries a CONTROL: a case that must go red if the guard were
removed. A detector that passes by finding nothing is indistinguishable from a
blind one.
"""

import unittest

from cosa.utils.credential_watch import (
    should_restart_containers,
    container_is_busy,
    MIN_REMAINING_SECONDS,
)

NOW_MS   = 1_785_600_000_000.0
EIGHT_H  = 8 * 3600 * 1000
HEALTHY  = NOW_MS + EIGHT_H


class TestShouldRestartContainers( unittest.TestCase ):

    def test_control_a_real_refresh_DOES_fire( self ):
        # THE CONTROL for every "does not fire" test below. If this goes red the
        # watcher is blind and all the quiet-path greens mean nothing.
        act, why = should_restart_containers( 9437190, 9437189, HEALTHY, NOW_MS )
        self.assertTrue( act )
        self.assertIn( "9437190 -> 9437189", why )
        self.assertIn( "8.0h", why )

    def test_first_observation_does_not_fire( self ):
        # systemd restarts this service on failure. If a first observation acted,
        # every watcher restart would bounce the fleet's notify channel.
        act, why = should_restart_containers( None, 9437189, HEALTHY, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "baseline", why )

    def test_unchanged_inode_does_not_fire( self ):
        act, why = should_restart_containers( 9437189, 9437189, HEALTHY, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "unchanged", why )

    def test_unreadable_credential_does_not_fire( self ):
        act, why = should_restart_containers( 9437190, None, HEALTHY, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "unreadable", why )

    def test_changed_inode_with_no_expiry_does_not_fire( self ):
        # A file we cannot parse is not evidence of a healthy token.
        act, why = should_restart_containers( 9437190, 9437189, None, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "refusing", why )

    def test_already_expired_token_does_not_fire( self ):
        # The exact failure this watcher exists to prevent, in miniature:
        # restarting a container onto a credential that is already dead.
        act, why = should_restart_containers( 9437190, 9437189, NOW_MS - 1000, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "strand again", why )

    def test_token_expiring_inside_the_headroom_does_not_fire( self ):
        act, why = should_restart_containers( 9437190, 9437189, NOW_MS + 30_000, NOW_MS )
        self.assertFalse( act )
        self.assertIn( "30s left", why )

    def test_the_headroom_boundary_is_exclusive( self ):
        # Exactly at the threshold must NOT act (<=), one millisecond past it must.
        at_edge = NOW_MS + MIN_REMAINING_SECONDS * 1000
        act, _   = should_restart_containers( 1, 2, at_edge, NOW_MS )
        self.assertFalse( act )
        act, _   = should_restart_containers( 1, 2, at_edge + 1, NOW_MS )
        self.assertTrue( act )

    def test_every_outcome_states_a_reason( self ):
        # The log is the only forensic trail when this fires unattended at 3am.
        cases = [
            ( None, 2, HEALTHY ), ( 1, 1, HEALTHY ), ( 1, None, HEALTHY ),
            ( 1, 2, None ), ( 1, 2, NOW_MS - 1 ), ( 1, 2, HEALTHY ),
        ]
        for prev, cur, exp in cases:
            _, why = should_restart_containers( prev, cur, exp, NOW_MS )
            self.assertTrue( why.strip(), f"empty reason for {( prev, cur, exp )}" )


class TestContainerIsBusy( unittest.TestCase ):

    IDLE_PS = "UID  PID  PPID  C STIME TTY  TIME CMD\nrruiz  1  0  0 20:57 ?  00:00:00 python3 -m lupin_app.main\n"

    def test_control_an_idle_container_reads_idle( self ):
        # CONTROL for the busy tests: if this goes red, "busy" is being reported
        # for everything and the watcher would never restart :8000 at all.
        busy, why = container_is_busy( self.IDLE_PS )
        self.assertFalse( busy )
        self.assertEqual( why, "idle" )

    def test_pytest_in_flight_defers( self ):
        busy, why = container_is_busy( self.IDLE_PS + "rruiz 42 1 0 21:00 ? 00:00:01 python -m pytest src/tests/integration\n" )
        self.assertTrue( busy )
        self.assertIn( "pytest", why )

    def test_playwright_in_flight_defers( self ):
        busy, _ = container_is_busy( self.IDLE_PS + "rruiz 43 1 0 21:00 ? 00:00:01 npx playwright test\n" )
        self.assertTrue( busy )

    def test_named_suite_runners_defer( self ):
        for marker in ( "run-integration-tests", "run-e2e-ui-tests" ):
            busy, _ = container_is_busy( self.IDLE_PS + f"rruiz 44 1 0 21:00 ? 00:00:01 bash {marker}.sh\n" )
            self.assertTrue( busy, f"{marker} should defer a restart" )

    def test_unreadable_process_list_FAILS_SAFE( self ):
        # "I saw nothing" is not "there is nothing" — the whole c7c60896 family
        # is about not confusing those two. An unreadable ps must read as busy.
        for blank in ( "", "   ", "\n\n" ):
            busy, why = container_is_busy( blank )
            self.assertTrue( busy, f"empty ps ({blank!r}) must fail safe to busy" )
            self.assertIn( "fail-safe", why )


if __name__ == "__main__":
    unittest.main()
