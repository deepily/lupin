"""
Integration test — R5 all-clear DEADLINE-EXPIRED path through the REAL lifespan wiring.

⚠️ VENUE :8000 / WRITE-ONLY. Author: Krishna 🦚 (Implementer), 2026-08-01, at Tiffany's
request. Do NOT run this from a dev seat — it belongs in Rachel's next :8000 pass; a second
runner collides with her in-flight sequence.

WHY THIS EXISTS beyond the unit tests: the unit suite
(`src/cosa/tests/unit/rest/test_managed_bounce_broadcast.py`) asserts `wait_for_recipients`
and `all_clear_fire_reason` in ISOLATION — it mocks the lifespan wiring out. But on real
traffic the all-clear has only ever been observed taking the THRESHOLD-MET branch: two live
`:7999` bounces on 2026-08-01 both fired at 0.0s with 7 sessions already present. The
deadline-expired branch is the one live traffic cannot produce on demand, so it is the one
worth exercising through the actual `main._managed_bounce_all_clear_blocking` — settle-gate
loop, reason label, and fire-time log formatting all REAL, only the I/O boundaries stubbed.

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
        # bridge roster (7) and plateau-fire instantly. If anyone reverts count_fn to
        # the bridge-file proxy, this goes RED: it would take the plateau branch, so
        # "DEADLINE EXPIRY" / "reached 0" / the named-missed list all vanish from the
        # log. A test that stays green on the bridge count would prove nothing — that
        # is exactly how the bug shipped.
        from lupin_app import main

        # ~0.1s deadline so the expiry path is reached fast; minimum 1, plateau 2.
        fake_cfg = mock.MagicMock()
        fake_cfg.get.side_effect = lambda key, default=None, return_type=None: {
            "managed bounce all-clear settle deadline seconds"      : 0.1,
            "managed bounce all-clear settle poll interval seconds" : 0.02,
            "managed bounce all-clear settle minimum recipients"    : 1,
            "managed bounce all-clear settle stable polls"          : 2,
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
            # REAL wiring: the actual plateau loop + reconnect curve + named-missed +
            # fire-time log run. Only the live-socket count, the roster, and _emit are
            # stubbed (the I/O edges).
            main._managed_bounce_all_clear_blocking(
                boot_id       = 99,
                boot_started  = "2026-08-01T00:00:00",
                startup_began = 0.0,
            )

        out = buf.getvalue()
        # It PROCEEDED (fired once) rather than hanging on the absent sockets.
        emit.assert_called_once()
        # Deadline branch — NOT plateau (the bridge proxy would have plateaued at 7).
        self.assertIn( "DEADLINE EXPIRY", out )
        self.assertIn( "boot #99", out )
        self.assertNotIn( "reconnect plateau", out )
        self.assertIn( "reached 0 recipient(s)", out )
        # Named-missed delivery LOSS: all 7 roster sessions, none present.
        self.assertIn( "7 session(s) NEVER rejoined", out )
        for s in ( "sessA", "sessG" ):
            self.assertIn( s, out )
        # The reconnect curve is present (all-zero here, since nothing reconnected).
        self.assertIn( "reconnect curve", out )


if __name__ == "__main__":
    unittest.main()
