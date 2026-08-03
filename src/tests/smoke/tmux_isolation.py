"""
Tmux fleet-socket isolation for the smoke suite — the fleet-killer CLASS fix.

WHY: a single shared user-level tmux server (socket /tmp/tmux-<uid>/default)
hosts every Claude Code session across three project trees. On tmux 3.2a an
inherited $TMUX BEATS TMUX_TMPDIR for socket selection (proven read-only —
plan §2.5), so a bare `tmux <verb>` from inside a Claude pane addresses the
FLEET socket no matter what TMUX_TMPDIR says. A smoke test that believed it
was isolated ran `tmux kill-server` in teardown and repeatedly killed the
whole fleet (three deaths positively attributed, 2026-07-14).

This module is the pure, unit-testable logic behind the session-scoped
autouse guard in src/tests/smoke/conftest.py (`tmux_fleet_socket_isolation`),
borrowing the snapshot/pop/restore shape of `hermetic_config_module_boundary`
( src/tests/conftest.py:46-89 ).

Design + forensics:
    src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md (§5.2)
Cascade closure record:
    src/rnd/v0.1.9/2026.07.15-cascade-tmux-fleet-killer-revision-handoff.md
"""

# SINGLE SOURCE for the test-only strip keys — the §5.1 test helpers and the
# smoke conftest guard import THIS constant; it is never restated elsewhere.
#
# ⚠️ ANTI-REUSE FENCE — do NOT fold these keys into MAX_PANE_UNSET_KEYS
# ( cosa.utils.vertex_env ): that constant feeds the production launcher's
# SERVER_SCRUB, and production panes legitimately carry $TMUX — widening it
# would make the launcher strip live pane context on the fleet server.
# Same fence-class: these keys must never join _HERMETIC_TRACKED_ENV_VARS
# ( src/tests/conftest.py ) — its module-scoped restore would fight the
# session-scoped pin, re-arming the leak mid-session.
TMUX_ISOLATION_STRIP_KEYS = ( "TMUX", "TMUX_PANE" )

# TMUX_TMPDIR is snapshotted (the guard overwrites it with the pinned dir)
# but never stripped — with $TMUX gone, TMUX_TMPDIR is what wins.
_SNAPSHOT_KEYS = TMUX_ISOLATION_STRIP_KEYS + ( "TMUX_TMPDIR", )


def strip_tmux_context( environ ):
    """
    Snapshot the tmux context ( strip keys + TMUX_TMPDIR ), pop the strip keys.

    Requires:
        - environ is a mutable str->str mapping (os.environ, or a plain dict
          under test)

    Ensures:
        - returns a snapshot dict covering TMUX, TMUX_PANE and TMUX_TMPDIR:
          value = the pre-strip value, or None where the key was absent
        - TMUX and TMUX_PANE are absent from environ on return
        - TMUX_TMPDIR is left untouched here — the caller pins it after

    Raises:
        - None
    """
    snapshot = { key : environ.get( key ) for key in _SNAPSHOT_KEYS }
    for key in TMUX_ISOLATION_STRIP_KEYS:
        environ.pop( key, None )
    return snapshot


def restore_tmux_context( environ, snapshot ):
    """
    Restore environ to the state strip_tmux_context snapshotted — byte-for-byte.

    Requires:
        - snapshot came from strip_tmux_context (keys per _SNAPSHOT_KEYS,
          values str or None)

    Ensures:
        - keys absent at snapshot time end absent (pop branch), even if
          something set them in between
        - keys present at snapshot time end at their snapshot value
          (restore branch), even if something changed or deleted them

    Raises:
        - None
    """
    for key, saved_value in snapshot.items():
        if saved_value is None:
            environ.pop( key, None )
        else:
            environ[ key ] = saved_value
