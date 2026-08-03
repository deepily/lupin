"""
AC2 — no smoke test can reach the fleet default socket.

This regression test lives INSIDE the smoke suite because it must run UNDER
the session-scoped guard to observe it. It requests the guard fixture BY
NAME — if `tmux_fleet_socket_isolation` is ever removed from the smoke
conftest, this test fails at COLLECTION ("fixture not found") instead of
silently passing. That loud-fail is the point.

VENUE: :7999-eligible / AI-discretionary — read-only env assertions, no tmux
invoked, no persistent state.

Design: src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md (§6 AC2)
"""

import os

from tests.smoke.tmux_isolation import TMUX_ISOLATION_STRIP_KEYS


def test_guard_pins_private_tmpdir_and_strips_pane_context( tmux_fleet_socket_isolation ):
    """
    Under the armed guard: TMUX_TMPDIR must equal the pinned private dir the
    fixture yields, and the pane-context keys must be absent — so any bare
    `tmux` from any smoke test resolves to the private socket dir, never to
    /tmp/tmux-<uid>/default.
    """
    pinned = tmux_fleet_socket_isolation

    assert os.environ[ "TMUX_TMPDIR" ] == str( pinned ), (
        f"the guard's TMUX_TMPDIR pin is not in effect — expected {pinned}, "
        f"got {os.environ.get( 'TMUX_TMPDIR' )!r}. A bare tmux may resolve to "
        f"the fleet default socket."
    )
    for key in TMUX_ISOLATION_STRIP_KEYS:
        assert key not in os.environ, (
            f"{key} survived the guard strip — on tmux 3.2a it BEATS "
            f"TMUX_TMPDIR for socket selection, so a bare tmux would address "
            f"the fleet default socket (the 2026-07-14 fleet-killer)."
        )
