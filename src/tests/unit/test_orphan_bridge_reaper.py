#!/usr/bin/env python3
"""
Unit tests for the orphan-session-bridge reaper (bug ee59d5ed, Change 2).

Target: 100% line + branch + function coverage of
    cosa.agents.shared.orphan_bridge_reaper

The reaper sweeps ~/.claude/sessions/cc-*.json and reaps CONFIRMED-dead orphan
bridges (host PID confirmed-dead AND tmux gone AND dead across N debounce polls),
reusing session_spawner's reap emitters. Every IO/decision/emit seam is injected,
so these tests drive pure in-memory fakes — no real tmux, no real notify POST, no
real bridge files touched.
"""
import json

import pytest

from cosa.agents.shared import orphan_bridge_reaper as obr
from cosa.agents.shared.orphan_bridge_reaper import (
    reconcile_orphan_bridges,
    _default_list_bridges,
    _default_read_bridge,
    _default_tmux_alive,
    _bridge_pids,
    _REAPED_SENTINEL,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _bridge( session_id="s-abc12345", tmux="cc-review-1", listener_pid=None, cc_pid=None ):
    data = { "stable_session_id": session_id, "tmux_session": tmux, "voice_persona": { "name": "Rio" } }
    if listener_pid is not None: data[ "listener_pid" ] = listener_pid
    if cc_pid is not None:       data[ "cc_pid" ]       = cc_pid
    return data


class _Path:
    """Minimal stand-in for a bridge Path with a .name (filename carries the PID)."""
    def __init__( self, name ): self.name = name
    def __str__( self ): return self.name


def _seams( *, pid_dead=True, tmux_alive=False, identity=None, captures=None ):
    """Build the injected seam kwargs for reconcile_orphan_bridges."""
    captures = captures if captures is not None else {}
    captures.setdefault( "reap", [] ); captures.setdefault( "tomb", [] )
    captures.setdefault( "hold", [] ); captures.setdefault( "unlink", [] )
    return dict(
        trust_host_pids_fn    = lambda: True,
        pid_confirmed_dead_fn = lambda pid: pid_dead,
        extract_pid_fn        = lambda name: 99999,
        tmux_alive_fn         = lambda t: tmux_alive,
        capture_identity_fn   = lambda sd, t: identity,
        emit_reap_fn          = lambda ident, reason="": captures[ "reap" ].append( ( ident, reason ) ),
        emit_tombstone_fn     = lambda ident: captures[ "tomb" ].append( ident ),
        clear_hold_fn         = lambda ident: captures[ "hold" ].append( ident ) or True,
        unlink_fn             = lambda p: captures[ "unlink" ].append( p ),
    ), captures


# ── _default_list_bridges ─────────────────────────────────────────────────────

def test_list_bridges_missing_dir_returns_empty( tmp_path ):
    assert _default_list_bridges( tmp_path / "nope" ) == []


def test_list_bridges_filters_sidecars( tmp_path ):
    ( tmp_path / "cc-123.json" ).write_text( "{}" )
    ( tmp_path / "cc-buffer.json" ).write_text( "{}" )
    ( tmp_path / "cc-listener.json" ).write_text( "{}" )
    names = sorted( p.name for p in _default_list_bridges( tmp_path ) )
    assert names == [ "cc-123.json" ]


# ── _default_read_bridge ──────────────────────────────────────────────────────

def test_read_bridge_parses_json( tmp_path ):
    f = tmp_path / "cc-1.json"
    f.write_text( json.dumps( { "session_id": "x" } ) )
    assert _default_read_bridge( f ) == { "session_id": "x" }


# ── _default_tmux_alive ───────────────────────────────────────────────────────

def test_tmux_alive_no_session_is_false():
    assert _default_tmux_alive( None ) is False
    assert _default_tmux_alive( "" ) is False


def test_tmux_alive_returncode_zero_is_alive():
    runner = lambda argv: type( "R", (), { "returncode": 0 } )()
    assert _default_tmux_alive( "cc-x", runner=runner ) is True


def test_tmux_alive_returncode_nonzero_is_gone():
    runner = lambda argv: type( "R", (), { "returncode": 1 } )()
    assert _default_tmux_alive( "cc-x", runner=runner ) is False


def test_tmux_alive_probe_exception_biases_alive():
    def boom( argv ): raise RuntimeError( "tmux exploded" )
    assert _default_tmux_alive( "cc-x", runner=boom ) is True


def test_tmux_alive_default_runner_on_bogus_session():
    # Exercises the production default runner lambda. A clearly-nonexistent session
    # → tmux returns nonzero → False; if tmux is absent → exception → True (alive).
    # Either outcome is a valid, side-effect-free probe.
    result = _default_tmux_alive( "cc-nonexistent-ee59d5ed-probe-xyz" )
    assert result in ( True, False )


# ── _bridge_pids ──────────────────────────────────────────────────────────────

def test_bridge_pids_collects_all_sources():
    pids = _bridge_pids( _Path( "cc-555.json" ), _bridge( listener_pid=777, cc_pid=888 ),
                         extract_pid_fn=lambda name: 555 )
    assert sorted( pids ) == [ 555, 777, 888 ]


def test_bridge_pids_skips_missing_filename_pid_and_non_int():
    pids = _bridge_pids( _Path( "cc-x.json" ), { "listener_pid": "notanint", "cc_pid": 42 },
                         extract_pid_fn=lambda name: None )
    assert pids == [ 42 ]


# ── reconcile_orphan_bridges — gate, guards, reap, debounce, idempotency ───────

def test_container_gate_noops_and_leaves_state( ):
    state = { "s-1": 1 }
    out = reconcile_orphan_bridges(
        state, trust_host_pids_fn=lambda: False,
        list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(),
    )
    assert out == { "reaped": [], "skipped": [], "errors": [] }
    assert state == { "s-1": 1 }                          # untouched


def test_unreadable_bridge_to_errors():
    def boom( p ): raise ValueError( "corrupt json" )
    seams, _ = _seams()
    out = reconcile_orphan_bridges( {}, list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=boom, **seams )
    assert len( out[ "errors" ] ) == 1 and "corrupt json" in out[ "errors" ][ 0 ]
    assert out[ "reaped" ] == []


def test_no_session_id_skipped():
    seams, _ = _seams()
    out = reconcile_orphan_bridges(
        {}, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: { "tmux_session": "cc-x" }, **seams )
    assert out[ "skipped" ] == [ { "path": "cc-1.json", "reason": "no session_id" } ]


def test_already_reaped_sentinel_is_idempotent():
    state = { "s-abc12345": _REAPED_SENTINEL }
    seams, caps = _seams( pid_dead=True, tmux_alive=False )
    out = reconcile_orphan_bridges(
        state, list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(), **seams )
    assert out[ "reaped" ] == []
    assert caps[ "reap" ] == []                           # NOT re-emitted
    assert out[ "skipped" ][ 0 ][ "reason" ] == "already reaped"
    assert state[ "s-abc12345" ] == _REAPED_SENTINEL


def test_live_pid_rearms_counter():
    state = { "s-abc12345": 1 }
    seams, _ = _seams( pid_dead=False, tmux_alive=False )       # PID alive
    out = reconcile_orphan_bridges(
        state, list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(), **seams )
    assert out[ "reaped" ] == []
    assert "s-abc12345" not in state                     # re-armed (popped)


def test_live_tmux_not_reaped():
    seams, caps = _seams( pid_dead=True, tmux_alive=True )      # tmux still alive
    out = reconcile_orphan_bridges(
        {}, list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(), **seams )
    assert out[ "reaped" ] == [] and caps[ "reap" ] == []


def test_no_pids_not_reaped():
    # A bridge carrying NO resolvable PIDs cannot be confirmed dead.
    seams, _ = _seams( pid_dead=True, tmux_alive=False )
    seams[ "extract_pid_fn" ] = lambda name: None              # no filename PID
    out = reconcile_orphan_bridges(
        {}, list_fn=lambda: [ _Path( "cc-x.json" ) ],
        read_fn=lambda p: _bridge( listener_pid=None, cc_pid=None ), **seams )
    assert out[ "reaped" ] == []


def test_no_tmux_field_not_reaped():
    seams, _ = _seams( pid_dead=True, tmux_alive=False )
    out = reconcile_orphan_bridges(
        {}, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge( tmux=None ), **seams )
    assert out[ "reaped" ] == []


def test_dead_below_threshold_increments_not_reaped():
    state = {}
    seams, caps = _seams( pid_dead=True, tmux_alive=False )
    out = reconcile_orphan_bridges(
        state, debounce_threshold=2, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge(), **seams )
    assert out[ "reaped" ] == [] and caps[ "reap" ] == []
    assert state[ "s-abc12345" ] == 1
    assert "dead 1/2 polls" in out[ "skipped" ][ 0 ][ "reason" ]


def test_dead_at_threshold_reaps_all_seams():
    ident = { "bridge_path": "/x/cc-1.json", "persona": { "name": "Rio" },
              "sender_id": "claude.code@lupin.deepily.ai#abc12345", "session_id": "s-abc12345" }
    state = { "s-abc12345": 1 }                           # already dead once
    seams, caps = _seams( pid_dead=True, tmux_alive=False, identity=ident )
    out = reconcile_orphan_bridges(
        state, debounce_threshold=2, session_dir="/tmp/fake-session-dir",   # covers the provided-path branch
        list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge(), **seams )
    assert len( out[ "reaped" ] ) == 1
    assert out[ "reaped" ][ 0 ][ "sender_id" ] == "claude.code@lupin.deepily.ai#abc12345"
    assert len( caps[ "reap" ] ) == 1 and caps[ "reap" ][ 0 ][ 0 ] == ident
    assert caps[ "tomb" ] == [ ident ]
    assert caps[ "unlink" ] == [ "/x/cc-1.json" ]
    assert caps[ "hold" ] == [ ident ]
    assert state[ "s-abc12345" ] == _REAPED_SENTINEL     # idempotency guard set


def test_identity_none_at_reap_marks_sentinel():
    state = { "s-abc12345": 5 }                           # past threshold
    seams, caps = _seams( pid_dead=True, tmux_alive=False, identity=None )   # capture returns None
    out = reconcile_orphan_bridges(
        state, debounce_threshold=2, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge(), **seams )
    assert out[ "reaped" ] == [] and caps[ "reap" ] == []
    assert out[ "skipped" ][ 0 ][ "reason" ] == "identity gone at reap"
    assert state[ "s-abc12345" ] == _REAPED_SENTINEL


def test_capture_raises_to_errors():
    state = { "s-abc12345": 5 }
    seams, _ = _seams( pid_dead=True, tmux_alive=False, identity=None )
    def boom( sd, t ): raise RuntimeError( "capture boom" )
    seams[ "capture_identity_fn" ] = boom
    out = reconcile_orphan_bridges(
        state, debounce_threshold=2, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge(), **seams )
    assert any( "capture boom" in e for e in out[ "errors" ] )
    assert out[ "reaped" ] == []


def test_seam_raises_swallowed_but_still_reaps():
    ident = { "bridge_path": "/x/cc-1.json", "sender_id": "s#1", "session_id": "s-abc12345" }
    state = { "s-abc12345": 5 }
    seams, caps = _seams( pid_dead=True, tmux_alive=False, identity=ident )
    def boom( ident, reason="" ): raise RuntimeError( "emit down" )
    seams[ "emit_reap_fn" ] = boom
    out = reconcile_orphan_bridges(
        state, debounce_threshold=2, list_fn=lambda: [ _Path( "cc-1.json" ) ],
        read_fn=lambda p: _bridge(), **seams )
    assert any( "emit_reap failed" in e for e in out[ "errors" ] )
    assert len( out[ "reaped" ] ) == 1                   # sweep still completes the reap
    assert caps[ "tomb" ] == [ ident ]                   # later seams still fire
    assert state[ "s-abc12345" ] == _REAPED_SENTINEL


def test_stale_counter_pruned():
    # A key in state whose bridge is gone this poll must be pruned (bounded state).
    state = { "s-gone": 1, "s-abc12345": 1 }
    seams, _ = _seams( pid_dead=False, tmux_alive=True )        # present bridge is alive
    out = reconcile_orphan_bridges(
        state, list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(), **seams )
    assert "s-gone" not in state                          # pruned — not seen this poll
    assert "s-abc12345" not in state                      # re-armed (alive)


def test_debounce_two_polls_reaps_on_second():
    ident = { "bridge_path": "/x/cc-1.json", "sender_id": "s#1", "session_id": "s-abc12345" }
    state = {}
    seams, caps = _seams( pid_dead=True, tmux_alive=False, identity=ident )
    kw = dict( debounce_threshold=2, list_fn=lambda: [ _Path( "cc-1.json" ) ],
               read_fn=lambda p: _bridge(), **seams )
    out1 = reconcile_orphan_bridges( state, **kw )        # poll 1: dead 1/2
    assert out1[ "reaped" ] == [] and state[ "s-abc12345" ] == 1
    out2 = reconcile_orphan_bridges( state, **kw )        # poll 2: reap
    assert len( out2[ "reaped" ] ) == 1
    assert len( caps[ "reap" ] ) == 1                     # emitted exactly ONCE across both polls


def test_all_production_defaults_bind( tmp_path, monkeypatch ):
    # Cover the `if <seam> is None: import <real>` default-binding branches by
    # calling with NO seam args, monkeypatching the real helpers to safe fakes and
    # an EMPTY session dir so nothing is actually reaped (loop body never runs).
    import lupin_cli.claude_code.hooks.lib.session_bridge as sb
    import lupin_mcp.session_spawner as ss
    monkeypatch.setattr( sb, "SESSION_DIR", tmp_path / "empty", raising=False )
    monkeypatch.setattr( sb, "_can_trust_host_pids", lambda: True )
    monkeypatch.setattr( sb, "_pid_confirmed_dead", lambda pid: True )
    monkeypatch.setattr( sb, "_extract_pid_from_filename", lambda name: 1 )
    monkeypatch.setattr( ss, "_capture_reap_identity", lambda sd, t: None )
    monkeypatch.setattr( ss, "_default_emit_reap", lambda ident, reason="": None )
    monkeypatch.setattr( ss, "_default_emit_reaped_tombstone", lambda ident: None )
    monkeypatch.setattr( ss, "_default_clear_hold", lambda ident: True )
    out = reconcile_orphan_bridges( {} )                  # every seam binds to a real (patched) default
    assert out == { "reaped": [], "skipped": [], "errors": [] }


def test_debug_prints_do_not_raise( capsys ):
    # Cover the debug=True print branches (gate + reap).
    reconcile_orphan_bridges( {}, trust_host_pids_fn=lambda: False, debug=True )
    ident = { "bridge_path": "/x/cc-1.json", "sender_id": "s#1", "session_id": "s-abc12345" }
    seams, _ = _seams( pid_dead=True, tmux_alive=False, identity=ident )
    reconcile_orphan_bridges(
        { "s-abc12345": 5 }, debounce_threshold=2, debug=True,
        list_fn=lambda: [ _Path( "cc-1.json" ) ], read_fn=lambda p: _bridge(), **seams )
    assert "orphan-bridge-reaper" in capsys.readouterr().out


if __name__ == "__main__":
    raise SystemExit( pytest.main( [ __file__, "-v" ] ) )
