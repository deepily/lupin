"""
AC3 — 100% lines/branches/functions on src/tests/smoke/tmux_isolation.py,
the pure logic behind the smoke-suite fleet-socket guard.

Both restore branches are driven directly via pytest's monkeypatch idiom on
os.environ — no tmux involved (ratified AC3 disposition, fix plan §6).

Also pins the two ANTI-REUSE fences as executable guards (revision-handoff §4
latent invariant): the test-only strip keys must never join the production
launcher scrub set (MAX_PANE_UNSET_KEYS) nor the hermetic-config tracked set
(_HERMETIC_TRACKED_ENV_VARS) — either merge re-arms the fleet-killer.

Design: src/rnd/v0.1.9/2026.07.14-tmux-fleet-killer-vertex-taint-test-isolation-leak-fix-plan.md
"""

import os

from cosa.utils.vertex_env import MAX_PANE_UNSET_KEYS

from tests.conftest import _HERMETIC_TRACKED_ENV_VARS
from tests.smoke.tmux_isolation import (
    TMUX_ISOLATION_STRIP_KEYS,
    restore_tmux_context,
    strip_tmux_context,
)


def test_strip_pops_present_keys_and_snapshots_their_values( monkeypatch ):
    """
    All three tracked keys present: strip must pop TMUX/TMUX_PANE, leave
    TMUX_TMPDIR in place, and snapshot all three pre-strip values.
    """
    monkeypatch.setenv( "TMUX",        "/tmp/tmux-1001/default,349437,0" )
    monkeypatch.setenv( "TMUX_PANE",   "%7" )
    monkeypatch.setenv( "TMUX_TMPDIR", "/tmp/somewhere-prior" )

    snapshot = strip_tmux_context( os.environ )

    assert "TMUX"      not in os.environ
    assert "TMUX_PANE" not in os.environ
    assert os.environ[ "TMUX_TMPDIR" ] == "/tmp/somewhere-prior", "TMUX_TMPDIR is snapshotted, never stripped"
    assert snapshot == {
        "TMUX"        : "/tmp/tmux-1001/default,349437,0",
        "TMUX_PANE"   : "%7",
        "TMUX_TMPDIR" : "/tmp/somewhere-prior",
    }


def test_strip_with_all_keys_absent_snapshots_none( monkeypatch ):
    """
    Non-pane shell (the false-green state): nothing to pop, snapshot records
    absence as None so restore's pop branch knows to end-state-absent.
    """
    for key in ( "TMUX", "TMUX_PANE", "TMUX_TMPDIR" ):
        monkeypatch.delenv( key, raising=False )

    snapshot = strip_tmux_context( os.environ )

    assert snapshot == { "TMUX": None, "TMUX_PANE": None, "TMUX_TMPDIR": None }
    assert "TMUX"      not in os.environ
    assert "TMUX_PANE" not in os.environ


def test_restore_present_branch_puts_snapshot_values_back( monkeypatch ):
    """
    Keys present at snapshot time end at their snapshot value — even after
    mid-session deletion AND mutation (the guard's own TMUX_TMPDIR pin).
    """
    monkeypatch.setenv( "TMUX",        "/tmp/tmux-1001/default,349437,0" )
    monkeypatch.setenv( "TMUX_PANE",   "%7" )
    monkeypatch.setenv( "TMUX_TMPDIR", "/tmp/somewhere-prior" )
    snapshot = strip_tmux_context( os.environ )

    os.environ[ "TMUX_TMPDIR" ] = "/tmp/pinned-by-guard"     # the guard's pin
    os.environ.pop( "TMUX_PANE", None )                      # already gone; stays gone mid-session

    restore_tmux_context( os.environ, snapshot )

    assert os.environ[ "TMUX" ]        == "/tmp/tmux-1001/default,349437,0"
    assert os.environ[ "TMUX_PANE" ]   == "%7"
    assert os.environ[ "TMUX_TMPDIR" ] == "/tmp/somewhere-prior"


def test_restore_absent_branch_pops_even_if_set_in_between( monkeypatch ):
    """
    Keys absent at snapshot time end absent — even if something set them
    mid-session (byte-for-byte contract, delete arm).
    """
    for key in ( "TMUX", "TMUX_PANE", "TMUX_TMPDIR" ):
        monkeypatch.delenv( key, raising=False )
    snapshot = strip_tmux_context( os.environ )

    monkeypatch.setenv( "TMUX",        "/tmp/sneaky/default,1,0" )
    monkeypatch.setenv( "TMUX_TMPDIR", "/tmp/sneaky-tmpdir" )

    restore_tmux_context( os.environ, snapshot )

    assert "TMUX"        not in os.environ
    assert "TMUX_PANE"   not in os.environ
    assert "TMUX_TMPDIR" not in os.environ


def test_strip_keys_never_join_the_production_scrub_set():
    """
    ⚠️ ANTI-REUSE FENCE (fix plan §5.2 blockquote). MAX_PANE_UNSET_KEYS feeds
    the production launcher's SERVER_SCRUB; production panes legitimately
    carry $TMUX. If these sets ever intersect, the launcher would strip live
    pane context on the fleet server.
    """
    overlap = set( TMUX_ISOLATION_STRIP_KEYS ) & set( MAX_PANE_UNSET_KEYS )
    assert overlap == set(), (
        f"{overlap} appears in BOTH the test-only strip set and the production "
        f"launcher scrub set — the §5.2 anti-reuse fence is breached."
    )


def test_strip_keys_never_join_the_hermetic_tracked_set():
    """
    Latent invariant (revision-handoff §4 watch-pair): if the TMUX keys join
    _HERMETIC_TRACKED_ENV_VARS, the module-scoped restore would fight the
    session-scoped pin — restoring a pre-strip $TMUX mid-session re-arms the
    fleet-killer leak.
    """
    overlap = set( TMUX_ISOLATION_STRIP_KEYS ) & set( _HERMETIC_TRACKED_ENV_VARS )
    assert overlap == set(), (
        f"{overlap} appears in BOTH the tmux strip set and the hermetic-config "
        f"tracked set — the module-scoped restore would re-arm the leak mid-session."
    )
