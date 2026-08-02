"""
Integration test — R5 all-clear DEADLINE-EXPIRED path through the REAL lifespan wiring.

⚠️ VENUE :8000 / WRITE-ONLY. Author: Krishna 🦚 (Implementer), 2026-08-01, at Tiffany's
request. Do NOT run this from a dev seat — it belongs in Rachel's next :8000 pass; a second
runner collides with her in-flight sequence.

WHY THIS EXISTS beyond the unit tests: the unit suite
(`src/tests/unit/test_managed_bounce_broadcast.py` — moved there 2026-08-01 so the `unit`
test-type actually reaches it, row 663433a7) asserts `wait_for_roster_coverage` in
ISOLATION — it mocks the lifespan wiring out. The deadline-expired branch is the one live
traffic cannot produce on demand, so it is the one worth exercising through the actual
`main._managed_bounce_all_clear_blocking` — settle-gate loop, reason label, and fire-time
log formatting all REAL, only the I/O boundaries stubbed.

Updated 2026-08-02 for the roster-coverage predicate (bug 784d4a2e). It had ALSO gone stale
against cf07839a — it asserted "NEVER rejoined" while the shipped line had said "had NOT
rejoined" since that morning — which nobody caught because the `:8000` label kept it from
being run. Two staleness bugs in one file is the argument for routing it by the rubric.

The assertion is the behaviour Tiffany named: when nobody reconnects, the wiring logs
"deadline expired" and PROCEEDS to fire once (writing the durable broadcast) rather than
hanging. The ~0.1s settle deadline is what bounds it — a hang would blow the deadline, so a
completed run IS the no-hang proof.
"""

import io
import contextlib
import unittest
from unittest import mock


class AllClearDeadlineExpiredLiveWiringTest( unittest.TestCase ):

    def test_deadline_expiry_uses_live_sockets_not_bridge_files_and_names_missed( self ):
        # REGRESSION against the 2026-08-01 bug (Rio's requirement): the bridge-file
        # ROSTER says 7 sessions exist, but ZERO live sockets have reconnected. The
        # gate MUST read the live sockets (0) and ride to the deadline — NOT read the
        # bridge roster (7) and declare itself covered instantly. If anyone points the
        # PRESENT side back at the bridge-file proxy, this goes RED: coverage would
        # complete on the first poll, so
        # "DEADLINE EXPIRY" / "reached 0" / the named-missed list all vanish from the
        # log. A test that stays green on the bridge count would prove nothing — that
        # is exactly how the bug shipped.
        from lupin_app import main

        # ~0.1s deadline so the expiry path is reached fast.
        # The `settle minimum recipients` / `settle stable polls` keys this test used to
        # stub are RETIRED (bug 784d4a2e, 2026-08-02): the gate no longer waits for a
        # plateau at or above a floor, it waits for live sockets to COVER the roster.
        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "managed bounce all-clear settle deadline seconds"      : 0.1,
            "managed bounce all-clear settle poll interval seconds" : 0.02,
        }.get( key, default )

        # Roster (bridge files) says 7 exist; live sockets say 0 are back.
        roster = [ ( f"/p/{s}", s, s ) for s in ( "sessA", "sessB", "sessC", "sessD", "sessE", "sessF", "sessG" ) ]

        buf = io.StringIO()
        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ), \
             mock.patch.object( main.websocket_manager, "get_connection_count", return_value=0 ), \
             mock.patch.object( main.websocket_manager, "active_connections", { } ), \
             mock.patch(
                 "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                 return_value=roster,
             ), \
             mock.patch.object( main, "_emit_managed_bounce", return_value={ "recipients": 0 } ) as emit, \
             contextlib.redirect_stderr( buf ):
            # REAL wiring: the actual coverage loop + reconnect curve + named-missed +
            # fire-time log run. Only the live-socket set, the roster, and _emit are
            # stubbed (the I/O edges).
            main._managed_bounce_all_clear_blocking(
                boot_id       = 99,
                boot_started  = "2026-08-01T00:00:00",
                startup_began = 0.0,
            )

        out = buf.getvalue()
        # It PROCEEDED (fired once) rather than hanging on the absent sockets.
        emit.assert_called_once()
        # Deadline branch — NOT coverage. The bridge roster lists 7; if anyone points
        # the PRESENT side back at bridge files, coverage completes instantly and
        # "DEADLINE EXPIRY" / "reached 0" / the named list all vanish from the log.
        self.assertIn( "DEADLINE EXPIRY", out )
        self.assertIn( "boot #99", out )
        self.assertNotIn( "roster COVERED", out )
        self.assertIn( "reached 0 recipient(s)", out )
        # Named-missed delivery LOSS: all 7 roster sessions, none present.
        self.assertIn( "7 session(s) had NOT rejoined", out )
        for s in ( "sessA", "sessG" ):
            self.assertIn( s, out )
        # The reconnect curve is present (all-zero here, since nothing reconnected).
        self.assertIn( "reconnect curve", out )

    def test_wiring_reaches_coverage_with_the_REAL_id_shapes_on_both_sides( self ):
        # 🔴 THE CALL-SITE TEST THAT DID NOT EXIST, and its absence is why a blind
        # gate shipped with 51 green tests and 100% module coverage behind it
        # (Arnold 🪨, review 2026-08-02, attack #4). The unit tests inject roster_fn
        # and present_fn as matching abstract lists, so they pin the pure function
        # perfectly and say NOTHING about the two real sources agreeing.
        #
        # The two sources do not speak the same strings:
        #   roster (bridge files)      "0768c103-eb8d-459f-8e0e-0380fba88792"
        #   active_connections key     "cc-listener-0768c103"
        # Raw comparison never matches, so coverage was unreachable and every roster
        # session was named as missing on every bounce — a constant printed as a
        # measurement. Reconciled against the live 00:25 receipt: one socket was up
        # and `missing` still held the whole roster of 10.
        #
        # PREDICTED FAILURE if socket_match_key is removed from missed_sessions: this
        # rides to the 0.1s deadline instead, so the assertion on "roster COVERED"
        # fails and the log carries "2 session(s) had NOT rejoined" naming two
        # sessions whose sockets are, in this very test, both live.
        from lupin_app import main

        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "managed bounce all-clear settle deadline seconds"      : 0.1,
            "managed bounce all-clear settle poll interval seconds" : 0.02,
        }.get( key, default )

        full_ids = ( "0768c103-eb8d-459f-8e0e-0380fba88792", "a7cf035f-19f1-4531-9087-0ff01d638a4e" )
        roster   = [ ( f"/p/{s}", s, "persona" ) for s in full_ids ]
        # Exactly what websocket_manager holds after both listeners reconnect, plus a
        # browser tab that is on nobody's roster and must not affect the verdict.
        live     = { "cc-listener-0768c103": object(), "cc-listener-a7cf035f": object(),
                     "foolish goat": object() }

        buf = io.StringIO()
        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ), \
             mock.patch.object( main.websocket_manager, "active_connections", live ), \
             mock.patch(
                 "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                 return_value=roster,
             ), \
             mock.patch.object( main, "_emit_managed_bounce", return_value={ "recipients": 2 } ) as emit, \
             contextlib.redirect_stderr( buf ):
            main._managed_bounce_all_clear_blocking(
                boot_id       = 100,
                boot_started  = "2026-08-02T00:00:00",
                startup_began = 0.0,
            )

        out = buf.getvalue()
        emit.assert_called_once()
        # Fired because the roster was COVERED — not because the clock ran out.
        self.assertIn( "roster COVERED", out )
        self.assertNotIn( "DEADLINE EXPIRY", out )
        # Nobody named as missing: both roster sessions have a live socket.
        self.assertIn( "all 2 session(s) on the roster had a live socket", out )
        self.assertNotIn( "had NOT rejoined", out )

    def test_empty_roster_says_it_cannot_tell_why_rather_than_claiming_success( self ):
        # An empty roster is AMBIGUOUS: find_active_sessions returns [] both when
        # nobody is expected back and when the bridge directory is missing or
        # unreadable (Arnold 🪨, attack #2). Coverage is satisfied vacuously and the
        # all-clear fires into nobody. The log must not report the flattering reading
        # as fact.
        #
        # PREDICTED FAILURE if the wording reverts to "nobody was expected back, so
        # this reached nobody by design": the assertion on "could not be read" fails,
        # because that phrasing asserts a cause the gate cannot observe.
        from lupin_app import main

        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "managed bounce all-clear settle deadline seconds"      : 0.1,
            "managed bounce all-clear settle poll interval seconds" : 0.02,
        }.get( key, default )

        buf = io.StringIO()
        with mock.patch.object( main, "config_mgr", fake_cfg, create=True ), \
             mock.patch.object( main.websocket_manager, "active_connections", { } ), \
             mock.patch(
                 "lupin_cli.claude_code.hooks.lib.session_bridge.find_active_voice_persona_sessions",
                 return_value=[ ],
             ), \
             mock.patch.object( main, "_emit_managed_bounce", return_value={ "recipients": 0 } ), \
             contextlib.redirect_stderr( buf ):
            main._managed_bounce_all_clear_blocking(
                boot_id       = 101,
                boot_started  = "2026-08-02T00:00:00",
                startup_began = 0.0,
            )

        out = buf.getvalue()
        self.assertIn( "the roster was EMPTY", out )
        self.assertIn( "could not be read", out )
        self.assertIn( "cannot tell those two apart", out )


if __name__ == "__main__":
    unittest.main()
