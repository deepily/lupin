#!/usr/bin/env python3
"""
Unit tests for the reap PRODUCER added to `session_spawner.dismiss_sessions`
(2026-06-05): bridge-DELETE on reap + the injectable `session_reaped` emit seam.

Producer contract (locked with Sam, the consumer owner):
  - On reap, the session's bridge file is unlinked so the mtime-filtered
    `/api/commons/active-sessions` (broadcast send-to list) drops it immediately.
  - A `session_reaped` event fires with envelope sender_id = the REAPED worker's
    sender_id (→ SenderStore drops the focus-bar badge).
  - Producer is FAIL-SAFE: a bad unlink/emit never breaks the reap.

Venue: :7999-eligible / local — no server, no network (emit is injected).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_src = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src not in sys.path:
    sys.path.insert( 0, _src )

import lupin_mcp.session_spawner as ss


_OK_RUNNER = lambda argv, env=None: SimpleNamespace( returncode=0 )


def _setup( tmp, *, with_bridge=True, tmux="cc-author-x-1" ):
    """Create a manifest (one spawned session) + optionally its bridge file."""
    sd  = Path( tmp )
    mgr = "mgr-abc12345"
    ss._write_manifest( ss._manifest_path( mgr, sd ), [ { "session_name": tmux, "session_id": "sid-1" } ] )
    bridge = None
    if with_bridge:
        bridge = sd / "cc-99999.json"
        bridge.write_text( json.dumps( {
            "tmux_session"      : tmux,
            "stable_session_id" : "abcd1234-aaaa-bbbb",
            "voice_persona"     : { "name": "Tiffany", "icon": "💍", "color": "#FFD600" },
        } ) )
    return sd, mgr, bridge


def test_reap_deletes_bridge_and_emits():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        emitted = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": emitted.append( ident ),
            emit_reaped_fn=lambda ident: None,   # no-op tombstone seam (don't touch real fleet dir)
        )
        assert res[ "bridges_deleted" ] == 1
        assert bridge.exists() is False                      # bridge unlinked
        assert len( emitted ) == 1                            # emit fired once
        assert emitted[ 0 ][ "persona" ][ "name" ] == "Tiffany"
        assert emitted[ 0 ][ "sender_id" ].endswith( "#abcd1234" )   # REAPED worker's sender_id


def test_reap_captures_persona_before_unlink():
    """sender_id/persona derive from the bridge → must be captured pre-unlink."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        captured = {}
        def emit( ident, reason="" ):
            captured.update( ident )
            # by emit-time the bridge is already gone, but the identity survives
            assert not Path( ident[ "bridge_path" ] ).exists()
        ss.dismiss_sessions( mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER,
                             session_dir=sd, emit_reap_fn=emit, emit_reaped_fn=lambda ident: None )
        assert captured[ "persona" ][ "name" ] == "Tiffany"
        assert captured[ "sender_id" ] is not None


def test_reap_no_bridge_is_safe():
    """No bridge for the tmux session → no delete, no emit, reap still succeeds."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, _ = _setup( tmp, with_bridge=False )
        emitted = []
        res = ss.dismiss_sessions( mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER,
                                   session_dir=sd, emit_reap_fn=lambda i, reason="": emitted.append( i ) )
        assert res[ "bridges_deleted" ] == 0
        assert emitted == []
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"


def test_reap_emit_failure_never_breaks_reap():
    """A throwing emit_reap_fn is swallowed — the reap result is still well-formed."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        def boom( ident, reason="" ):
            raise RuntimeError( "server down" )
        res = ss.dismiss_sessions( mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER,
                                   session_dir=sd, emit_reap_fn=boom, emit_reaped_fn=lambda ident: None )
        assert res[ "bridges_deleted" ] == 1     # bridge still deleted despite emit blowup
        assert bridge.exists() is False
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"


def test_reap_already_gone_session_still_cleans_up():
    """tmux already dead (runner rc!=0) → bridge still deleted + emit still fires."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        dead_runner = lambda argv, env=None: SimpleNamespace( returncode=1 )
        emitted = []
        res = ss.dismiss_sessions( mgr, session_names=[ "cc-author-x-1" ], runner=dead_runner,
                                   session_dir=sd, emit_reap_fn=lambda i, reason="": emitted.append( i ),
                                   emit_reaped_fn=lambda ident: None )
        assert res[ "dismissed" ][ 0 ][ "status" ] == "already_gone"
        assert res[ "bridges_deleted" ] == 1
        assert len( emitted ) == 1
        assert bridge.exists() is False


def test_capture_reap_identity_unreadable_bridge_returns_none():
    """A cc-*.json that isn't valid JSON is skipped (no match) → None."""
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ( sd / "cc-bad.json" ).write_text( "{ not json" )
        assert ss._capture_reap_identity( sd, "cc-author-x-1" ) is None


# ── _default_emit_reap — pins the PRODUCER's real emit to the locked contract ──
# (Tier-C drift guard, 2026-06-05: my seam tests inject a fake emit_fn and never
# exercise the default POST. Without this, a typo'd type="reaped" would pass every
# unit test AND Sam's hardcoded Tier-A fixture, surfacing only in the :8000 E2E.)

def _mock_emit_deps( monkeypatch, posted ):
    """Patch requests + cosa.utils.config_loader (both imported INSIDE the fn) + target env."""
    import types
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "rick@example.com" )   # /api/notify target_user
    monkeypatch.setitem(
        sys.modules, "requests",
        types.SimpleNamespace( post=lambda url, params=None, headers=None, timeout=None:
                               posted.append( { "url": url, "params": params, "headers": headers } )
                               or types.SimpleNamespace( status_code=200 ) ),
    )
    monkeypatch.setitem(
        sys.modules, "cosa.utils.config_loader",
        types.SimpleNamespace(
            get_api_config=lambda env=None: { "api_url": "http://x:7999", "api_key_file": "__direct__" },
            load_api_key=lambda f: "KEY123",
        ),
    )


def test_default_emit_reap_posts_locked_contract( monkeypatch ):
    posted = []
    _mock_emit_deps( monkeypatch, posted )
    ss._default_emit_reap( { "sender_id": "claude.code@lupin.deepily.ai#abcd1234",
                             "persona": { "name": "Tiffany" } } )
    assert len( posted ) == 1
    p = posted[ 0 ][ "params" ]
    assert p[ "type" ]      == "session_reaped"                                # ← the locked type
    assert p[ "sender_id" ] == "claude.code@lupin.deepily.ai#abcd1234"          # ← REAPED worker
    assert p[ "message" ]     == "Tiffany reaped"
    assert p[ "priority" ]    == "low"
    assert p[ "target_user" ] == "rick@example.com"                # ← routes to the OWNER's UI (required by /api/notify)
    assert posted[ 0 ][ "url" ].endswith( "/api/notify" )
    assert posted[ 0 ][ "headers" ][ "X-API-Key" ] == "KEY123"


def test_default_emit_reap_no_target_user_is_noop( monkeypatch ):
    """No LUPIN_DEV_EMAIL + no configured recipient → can't route → skip (no POST)."""
    import types
    posted = []
    monkeypatch.delenv( "LUPIN_DEV_EMAIL", raising=False )
    monkeypatch.setitem( sys.modules, "requests",
                         types.SimpleNamespace( post=lambda *a, **k: posted.append( 1 ) ) )
    monkeypatch.setitem( sys.modules, "cosa.utils.config_loader",
                         types.SimpleNamespace( get_api_config=lambda env=None: { "api_url": "u", "api_key_file": "f" },
                                                load_api_key=lambda f: "k" ) )  # no global_notification_recipient
    ss._default_emit_reap( { "sender_id": "claude.code@lupin.deepily.ai#abcd1234", "persona": { "name": "X" } } )
    assert posted == []


def test_default_emit_reap_message_falls_back_when_no_persona_name( monkeypatch ):
    posted = []
    _mock_emit_deps( monkeypatch, posted )
    ss._default_emit_reap( { "sender_id": "claude.code@lupin.deepily.ai#abcd1234", "persona": { } } )
    assert posted[ 0 ][ "params" ][ "message" ] == "A worker reaped"


def test_default_emit_reap_no_sender_id_is_noop( monkeypatch ):
    posted = []
    _mock_emit_deps( monkeypatch, posted )
    ss._default_emit_reap( { "sender_id": None } )
    assert posted == []                                                         # best-effort: nothing to emit


def test_default_emit_reap_swallows_post_failure( monkeypatch ):
    import types
    monkeypatch.setenv( "LUPIN_DEV_EMAIL", "rick@example.com" )   # ensure we reach the POST (then it throws)
    monkeypatch.setitem( sys.modules, "requests",
                         types.SimpleNamespace( post=lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "down" ) ) ) )
    monkeypatch.setitem( sys.modules, "cosa.utils.config_loader",
                         types.SimpleNamespace( get_api_config=lambda env=None: { "api_url": "u", "api_key_file": "f" },
                                                load_api_key=lambda f: "k" ) )
    # must NOT raise
    ss._default_emit_reap( { "sender_id": "claude.code@lupin.deepily.ai#abcd1234", "persona": { "name": "X" } } )


# ── reap TOMBSTONE seam (reap-tombstone roster-eviction fix, 2026-06-15) ───────
# dismiss_sessions also appends a kind="reaped" heartbeat tombstone per reaped
# session so the arbiter force-offlines the roster row in ~1 poll. Injectable seam
# (emit_reaped_fn) like emit_reap_fn; fail-safe — a raising emitter never breaks
# the reap.

def test_reap_emits_tombstone_seam():
    """The injected emit_reaped_fn fires once per reaped session, post-capture."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        tombstoned = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None,
            emit_reaped_fn=lambda ident: tombstoned.append( ident ),
        )
        assert res[ "bridges_deleted" ] == 1
        assert len( tombstoned ) == 1
        # session_id was captured pre-unlink; persona dict survives for the audit line
        assert tombstoned[ 0 ][ "session_id" ] == "abcd1234-aaaa-bbbb"
        assert tombstoned[ 0 ][ "persona" ][ "name" ] == "Tiffany"


def test_reap_tombstone_failure_never_breaks_reap():
    """A throwing emit_reaped_fn is swallowed — the reap result is still well-formed."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        def boom( ident ):
            raise RuntimeError( "fleet dir read-only" )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None, emit_reaped_fn=boom,
        )
        assert res[ "bridges_deleted" ] == 1            # bridge still deleted despite tombstone blowup
        assert bridge.exists() is False
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"


def test_reap_no_bridge_emits_no_tombstone():
    """No captured identity (no bridge) → no tombstone seam call."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, _ = _setup( tmp, with_bridge=False )
        tombstoned = []
        ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reaped_fn=lambda ident: tombstoned.append( ident ),
        )
        assert tombstoned == []


def test_reap_default_tombstone_path_calls_emit_reaped( monkeypatch ):
    """With NO injected seam, the DEFAULT path fires the real emit_reaped (covers
    the default-selection branch + _default_emit_reaped_tombstone integration)."""
    import lupin_cli.claude_code.hooks.lib.heartbeat_events as he
    calls = []
    monkeypatch.setattr( he, "emit_reaped",
                         lambda session_id, persona=None: calls.append( ( session_id, persona ) ) or True )
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None,   # only the tombstone path is default here
        )
        assert calls == [ ( "abcd1234-aaaa-bbbb", "Tiffany" ) ]   # session_id + persona NAME


# ── _default_emit_reaped_tombstone — the real producer, in isolation ──────────

def test_default_tombstone_dict_persona_extracts_name( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_events as he
    calls = []
    monkeypatch.setattr( he, "emit_reaped",
                         lambda session_id, persona=None: calls.append( ( session_id, persona ) ) )
    ss._default_emit_reaped_tombstone( { "session_id": "sid-1", "persona": { "name": "Rachel", "icon": "🌹" } } )
    assert calls == [ ( "sid-1", "Rachel" ) ]


def test_default_tombstone_string_persona_passthrough( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_events as he
    calls = []
    monkeypatch.setattr( he, "emit_reaped",
                         lambda session_id, persona=None: calls.append( ( session_id, persona ) ) )
    ss._default_emit_reaped_tombstone( { "session_id": "sid-2", "persona": "Clayton" } )
    assert calls == [ ( "sid-2", "Clayton" ) ]


def test_default_tombstone_no_session_id_is_noop( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_events as he
    calls = []
    monkeypatch.setattr( he, "emit_reaped", lambda *a, **k: calls.append( 1 ) )
    ss._default_emit_reaped_tombstone( { "session_id": None, "persona": { "name": "X" } } )
    assert calls == []   # best-effort: no id → fall back to the ~60-min age-out


def test_default_tombstone_swallows_emit_failure( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_events as he
    monkeypatch.setattr( he, "emit_reaped",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "down" ) ) )
    # persona None exercises the non-dict (else) branch; must NOT raise
    ss._default_emit_reaped_tombstone( { "session_id": "sid-3", "persona": None } )


# ── HOLD-CLEAR-ON-REAP seam (ping-storm durable Fix 1, 2026-06-24) ────────────
# dismiss_sessions ALSO clears the reaped session's `.heartbeat-hold-<sid>.json`
# so the arbiter stops re-deriving phantom "X is blocking Y" edges from an
# orphaned hold every poll (the bridge was already deleted; the hold — a SEPARATE
# dotfile the arbiter's read_hold polls — lingered until TTL+6h). Injectable seam
# (clear_hold_fn) like emit_reap_fn/emit_reaped_fn; fail-safe — a raising clearer
# never breaks the reap. The captured session_id (from the bridge, pre-unlink)
# names the hold; base_dir default = cu.get_project_root = what read_hold sees.

def test_reap_clears_hold_seam():
    """The injected clear_hold_fn fires once per reaped session with the captured identity."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        cleared = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None,
            emit_reaped_fn=lambda ident: None,
            clear_hold_fn=lambda ident: cleared.append( ident ) or True,
        )
        assert res[ "holds_cleared" ] == 1
        assert len( cleared ) == 1
        assert cleared[ 0 ][ "session_id" ] == "abcd1234-aaaa-bbbb"   # captured pre-unlink, from the bridge


def test_reap_hold_clear_failure_never_breaks_reap():
    """A throwing clear_hold_fn is swallowed — the reap result is still well-formed."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        def boom( ident ):
            raise RuntimeError( "hold dir read-only" )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None, emit_reaped_fn=lambda ident: None,
            clear_hold_fn=boom,
        )
        assert res[ "bridges_deleted" ] == 1            # bridge still deleted despite hold-clear blowup
        assert res[ "holds_cleared" ]  == 0
        assert bridge.exists() is False
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"


def test_reap_clear_hold_returns_false_cleanly_counts_zero():
    """Covers the FALSE branch of `if do_clear_hold( ident ):` (session_spawner:669):
    a clearer that returns False WITHOUT raising (e.g. hold already absent / nothing
    to clear) → holds_cleared stays 0, and the reap is still well-formed (bridge
    deleted, dismissed list intact). Distinct from the throwing-clearer test (except
    path) and the True-return test (increment path)."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        calls = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None, emit_reaped_fn=lambda ident: None,
            clear_hold_fn=lambda ident: calls.append( ident ) or False,   # clean False (no raise)
        )
        assert calls and len( calls ) == 1                   # the clearer WAS invoked (669 evaluated)
        assert res[ "holds_cleared" ] == 0                   # ...but its False return did not increment
        assert res[ "bridges_deleted" ] == 1                 # reap still well-formed: bridge deleted
        assert bridge.exists() is False
        assert res[ "dismissed" ][ 0 ] == { "session_name": "cc-author-x-1", "status": "killed" }


def test_reap_no_bridge_clears_no_hold():
    """No captured identity (no bridge) → no clear_hold seam call."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, _ = _setup( tmp, with_bridge=False )
        cleared = []
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            clear_hold_fn=lambda ident: cleared.append( ident ) or True,
        )
        assert cleared == []
        assert res[ "holds_cleared" ] == 0


def test_reap_default_hold_clear_path_calls_clear_hold( monkeypatch ):
    """With NO injected seam, the DEFAULT path fires the real clear_hold with the
    captured session_id (covers the default-selection branch + _default_clear_hold)."""
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    calls = []
    monkeypatch.setattr( hh, "clear_hold",
                         lambda session_id, base_dir=None: calls.append( session_id ) )
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None,
            emit_reaped_fn=lambda ident: None,   # only the hold-clear path is default here
        )
        assert calls == [ "abcd1234-aaaa-bbbb" ]      # captured session_id, base_dir default
        assert res[ "holds_cleared" ] == 1


# ── _default_clear_hold — the real clearer, in isolation ──────────────────────

def test_default_clear_hold_calls_clear_hold( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    calls = []
    monkeypatch.setattr( hh, "clear_hold", lambda session_id, base_dir=None: calls.append( session_id ) )
    assert ss._default_clear_hold( { "session_id": "sid-9" } ) is True
    assert calls == [ "sid-9" ]


def test_default_clear_hold_no_session_id_is_noop( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    calls = []
    monkeypatch.setattr( hh, "clear_hold", lambda *a, **k: calls.append( 1 ) )
    assert ss._default_clear_hold( { "session_id": None } ) is False   # nothing to clear
    assert calls == []


def test_default_clear_hold_swallows_failure( monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.heartbeat_hold as hh
    monkeypatch.setattr( hh, "clear_hold",
                         lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "down" ) ) )
    # must NOT raise; returns False on a swallowed error
    assert ss._default_clear_hold( { "session_id": "sid-3" } ) is False
