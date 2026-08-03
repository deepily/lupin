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


# ══════════════════════════════════════════════════════════════════════════════
# REAP-RECONCILE seam (d647b531) — on reap, auto-reconcile the worker's
# non-terminal store items so an orphaned "outstanding" task never survives the
# reap for the user to catch. Three arms:
#   (a) AUTO-CLOSE — ONLY when the item's LATEST audit event already carries
#       receipt_refs (the degenerate orphaned-receipt crash case: a ->done that
#       produced a receipt but didn't persist the status flip). Machine-checkable,
#       zero inference. No receipt → never close.
#   (b) REASSIGN — every other non-terminal item, with the orphan-guard precedence:
#       accountable_manager IF ALIVE (its slug NOT in the dead-set = every persona
#       reaped in this batch, which INCLUDES the reaped owner itself) → else the
#       REAPING MANAGER (persona resolved from manager_session_id via the bridge) →
#       else unclassifiable. Kills the self-owned-stub re-orphan (harness
#       TaskCreate hardcodes owner==accountable_manager==self) + the same-batch case.
#   (c) SURFACE — ALWAYS return {closed, reassigned, unclassifiable}; any error
#       lands the item in unclassifiable.
# Injectable seam (reconcile_items_fn) like emit_*/clear_hold; DEFAULTS TO None
# (skip) in session_spawner so unit reaps stay hermetic — the real
# _default_reconcile_store_items producer is wired by the MCP wrapper (the live
# reap entrypoint). FAIL-SAFE is load-bearing: a raising reconciler NEVER breaks
# the reap.
# ══════════════════════════════════════════════════════════════════════════════

def test_reap_invokes_reconcile_seam_once_per_session():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda ident, reason="": None, emit_reaped_fn=lambda ident: None,
            clear_hold_fn=lambda ident: True,
            reconcile_items_fn=lambda ident, dead, mgr_p, reason="": seen.append( ident ) or
                { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] },
        )
        assert len( seen ) == 1
        assert seen[ 0 ][ "session_id" ] == "abcd1234-aaaa-bbbb"           # captured pre-unlink
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] }


def test_reap_reconcile_receives_batch_context():
    """The producer is handed the dead-owner slug set (this batch) + the resolved
    reaping-manager persona (from the manager bridge by manager_session_id)."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        # a manager bridge so manager_session_id resolves to a persona NAME
        ( sd / "cc-mgr.json" ).write_text( json.dumps( {
            "tmux_session": "cc-mgr", "stable_session_id": mgr,
            "voice_persona": { "name": "Mr Radio", "icon": "🦉" } } ) )
        got = {}
        def recon( ident, dead, mgr_p, reason="" ):
            got[ "dead" ] = dead
            got[ "mgr" ]  = mgr_p
            return { "closed": [], "reassigned": [], "unclassifiable": [] }
        ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=recon )
        assert "tiffany" in got[ "dead" ]          # the reaped owner's slug is in the dead-set
        assert got[ "mgr" ] == "Mr Radio"          # reaping-manager persona resolved from the bridge


def test_reap_reconcile_failure_never_breaks_reap():
    """FAIL-SAFE (load-bearing): a throwing reconciler is swallowed — the reap is
    still well-formed and the reconciliation block stays empty."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        def boom( ident, dead, mgr_p, reason="" ):
            raise RuntimeError( "store down" )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=boom )
        assert res[ "bridges_deleted" ] == 1
        assert bridge.exists() is False
        assert res[ "dismissed" ][ 0 ][ "status" ] == "killed"
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_reap_no_bridge_skips_reconcile():
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, _ = _setup( tmp, with_bridge=False )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            reconcile_items_fn=lambda *a, **k: seen.append( 1 ) or {} )
        assert seen == []                                                   # no identity → no reconcile call
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_reap_reconcile_default_none_skips_cleanly():
    """No reconcile_items_fn (the session_spawner default) → reconcile SKIPPED, no
    store reach, reconciliation block present-but-empty. Keeps unit reaps hermetic."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True )                                  # reconcile_items_fn omitted
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_reap_reconcile_none_default_makes_zero_store_calls( monkeypatch ):
    """CONTRACT LOCK: the default (reconcile_items_fn=None) path performs ZERO store
    mutation. Any task_store_tools call fails the test — a future edit can't silently
    flip the default ON and poison the 21 unit reap sites pointed at live :7999."""
    import lupin_mcp.task_store_tools as tst
    for fn in ( "task_query_impl", "task_transition_impl", "task_reassign_impl", "task_store_request" ):
        monkeypatch.setattr( tst, fn, lambda *a, **k: pytest.fail( f"default reap must not touch the store" ) )
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True )                                  # default → no reconcile
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_reap_reconcile_nondict_summary_ignored():
    """A reconciler returning a non-dict is ignored (not aggregated), never crashes."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=lambda *a, **k: None )
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_reap_reconcile_aggregates_across_sessions():
    """Two reaped sessions → their summaries merge into one reconciliation block."""
    with tempfile.TemporaryDirectory() as tmp:
        sd  = Path( tmp )
        mgr = "mgr-abc12345"
        ss._write_manifest( ss._manifest_path( mgr, sd ),
            [ { "session_name": "cc-a-1", "session_id": "s1" },
              { "session_name": "cc-b-2", "session_id": "s2" } ] )
        for tmux, sid8 in ( ( "cc-a-1", "aaaa1111" ), ( "cc-b-2", "bbbb2222" ) ):
            ( sd / f"cc-{sid8}.json" ).write_text( json.dumps( {
                "tmux_session": tmux, "stable_session_id": sid8,
                "voice_persona": { "name": "W" } } ) )
        def recon( ident, dead, mgr_p, reason="" ):
            if ident[ "session_id" ] == "aaaa1111":
                return { "closed": [ "c1" ], "reassigned": [ "r1" ], "unclassifiable": [] }
            return { "closed": [], "reassigned": [ "r2" ], "unclassifiable": [ "u1" ] }
        res = ss.dismiss_sessions(
            mgr, runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=recon )
        rc = res[ "reconciliation" ]
        assert sorted( rc[ "closed" ] )         == [ "c1" ]
        assert sorted( rc[ "reassigned" ] )     == [ "r1", "r2" ]
        assert sorted( rc[ "unclassifiable" ] ) == [ "u1" ]


# ── reap_stale_spawned threads the reconciler through to dismiss_sessions ──────

def test_reap_stale_spawned_forwards_reconcile_fn( monkeypatch ):
    """The idle-TTL backstop must NOT silently skip reconcile — it forwards its
    reconcile_items_fn to dismiss_sessions (default None = hermetic for its tests)."""
    captured = {}
    def fake_dismiss( manager_session_id, **kw ):
        captured.update( kw )
        return { "dismissed": [], "remaining": [] }
    monkeypatch.setattr( ss, "dismiss_sessions", fake_dismiss )
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ss._write_manifest( ss._manifest_path( "mgr-reap", sd ), [ { "session_name": "cc-x-1", "session_id": "s" } ] )
        sentinel = lambda *a, **k: {}
        ss.reap_stale_spawned( "mgr-reap", is_stale=lambda n: True, runner=_OK_RUNNER,
                               session_dir=sd, reconcile_items_fn=sentinel )
        assert captured[ "reconcile_items_fn" ] is sentinel


# ── _resolve_session_persona_name — reaping-manager persona by session_id ──────

def test_resolve_session_persona_name_found_dict():
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ( sd / "cc-1.json" ).write_text( json.dumps( {
            "stable_session_id": "mgr-9", "voice_persona": { "name": "Mr Radio" } } ) )
        assert ss._resolve_session_persona_name( sd, "mgr-9" ) == "Mr Radio"


def test_resolve_session_persona_name_string_persona():
    """voice_persona stored as a bare string → returned verbatim (non-dict else branch)."""
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ( sd / "cc-2.json" ).write_text( json.dumps( {
            "session_id": "mgr-7", "voice_persona": "Clayton" } ) )
        assert ss._resolve_session_persona_name( sd, "mgr-7" ) == "Clayton"


def test_resolve_session_persona_name_not_found():
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ( sd / "cc-3.json" ).write_text( json.dumps( { "stable_session_id": "other" } ) )
        assert ss._resolve_session_persona_name( sd, "mgr-missing" ) is None


def test_resolve_session_persona_name_no_session_id_is_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert ss._resolve_session_persona_name( Path( tmp ), None ) is None


def test_resolve_session_persona_name_skips_buffer_and_unreadable():
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path( tmp )
        ( sd / "cc-buffer-x.json" ).write_text( json.dumps( {
            "stable_session_id": "mgr-5", "voice_persona": { "name": "Ghost" } } ) )  # skipped (buffer)
        ( sd / "cc-bad.json" ).write_text( "{ not json" )                              # skipped (unreadable)
        assert ss._resolve_session_persona_name( sd, "mgr-5" ) is None


def test_resolve_session_persona_name_glob_oserror_is_none():
    class _BoomDir:
        def glob( self, pat ):
            raise OSError( "fs down" )
    assert ss._resolve_session_persona_name( _BoomDir(), "mgr-1" ) is None


# ── _default_reconcile_store_items — the real producer (mocked store + config) ──

def _mock_store_config( monkeypatch, *, api_url="http://x:7999" ):
    import types
    monkeypatch.setitem( sys.modules, "cosa.utils.config_loader",
        types.SimpleNamespace(
            get_api_config = lambda env=None: { "api_url": api_url, "api_key_file": "__f__" },
            load_api_key   = lambda f: "KEY" ) )


def _no_receipt_events( monkeypatch, tst ):
    monkeypatch.setattr( tst, "task_store_request",
                         lambda method, path, api_url, api_key, **kw: { "events": [], "count": 0 } )


def test_default_reconcile_reassigns_to_alive_accountable_manager( monkeypatch ):
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    q = []
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw: q.append( kw ) or
            { "tasks": [ { "id": "t-1", "status": "in_progress", "accountable_manager": "mr radio" } ], "count": 1 } )
    _no_receipt_events( monkeypatch, tst )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, new_owner, reason, **kw:
            reassigns.append( ( task_id, new_owner, actor ) ) or { "item": {}, "event": {} } )
    monkeypatch.setattr( tst, "task_transition_impl",
        lambda *a, **k: pytest.fail( "must NOT close a no-receipt item" ) )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert q[ 0 ][ "owner_persona" ] == "tiffany"             # persona-slug-from-dict owner derivation
    assert len( reassigns ) == 1
    assert reassigns[ 0 ][ 0 ] == "t-1" and reassigns[ 0 ][ 1 ] == "mr radio"   # alive accountable_manager
    assert isinstance( reassigns[ 0 ][ 2 ], str ) and reassigns[ 0 ][ 2 ]       # non-empty actor
    assert summary == { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] }


def test_default_reconcile_self_owned_stub_goes_to_reaping_manager( monkeypatch ):
    """GUARD: accountable_manager == the reaped owner (self-created stub) → its slug
    is in the dead-set → reassign to the REAPING MANAGER, not the corpse."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "self-1", "status": "queued", "accountable_manager": "Tiffany" } ], "count": 1 } )
    _no_receipt_events( monkeypatch, tst )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, new_owner, reason, **kw:
            reassigns.append( ( task_id, new_owner ) ) or { "item": {}, "event": {} } )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ ( "self-1", "Mr Radio" ) ]          # escalated to the live reaping manager
    assert summary[ "reassigned" ] == [ "self-1" ]


def test_default_reconcile_accountable_in_batch_goes_to_reaping_manager( monkeypatch ):
    """GUARD: accountable_manager is ANOTHER session reaped in the same batch (also
    dead) → reassign to the reaping manager."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "x-1", "status": "blocked", "accountable_manager": "Rachel" } ], "count": 1 } )
    _no_receipt_events( monkeypatch, tst )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, new_owner, reason, **kw:
            reassigns.append( new_owner ) or { "item": {} } )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } },
        dead_owner_slugs={ "tiffany", "rachel" }, reaping_manager="Mr Radio" )   # rachel also reaped
    assert reassigns == [ "Mr Radio" ]
    assert summary[ "reassigned" ] == [ "x-1" ]


def test_default_reconcile_dead_target_no_reaping_manager_is_unclassifiable( monkeypatch ):
    """GUARD: target dead AND reaping-manager unresolvable → unclassifiable (never
    silently re-orphan onto a dead owner)."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "orphan-1", "status": "queued", "accountable_manager": "Tiffany" } ], "count": 1 } )
    _no_receipt_events( monkeypatch, tst )
    monkeypatch.setattr( tst, "task_reassign_impl", lambda *a, **k: pytest.fail( "no live target to reassign to" ) )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager=None )
    assert summary == { "closed": [], "reassigned": [], "unclassifiable": [ "orphan-1" ] }


def test_default_reconcile_empty_accountable_goes_to_reaping_manager( monkeypatch ):
    """Empty/absent accountable_manager → no-live-target → reaping manager."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "noacct-1", "status": "in_progress" } ], "count": 1 } )   # no accountable_manager
    _no_receipt_events( monkeypatch, tst )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, new_owner, reason, **kw:
            reassigns.append( new_owner ) or { "item": {} } )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ "Mr Radio" ]
    assert summary[ "reassigned" ] == [ "noacct-1" ]


def test_default_reconcile_closes_item_with_orphaned_receipt( monkeypatch ):
    """Arm (a): the LATEST audit event carries receipt_refs → close with those exact
    refs (machine-bound crash-recovery), never reassign."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-9", "status": "in_progress", "accountable_manager": "mr radio" } ], "count": 1 } )
    monkeypatch.setattr( tst, "task_store_request",
        lambda method, path, api_url, api_key, **kw:
            { "events": [ { "id": 1, "receipt_refs": None },
                          { "id": 2, "receipt_refs": { "commit": "abc1234" } } ], "count": 2 } )   # latest has it
    closes = []
    monkeypatch.setattr( tst, "task_transition_impl",
        lambda api_url, api_key, actor, task_id, to_status, receipt_refs=None, **kw:
            closes.append( ( task_id, to_status, receipt_refs ) ) or { "item": {}, "event": {} } )
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda *a, **k: pytest.fail( "latest event carries a receipt → close, not reassign" ) )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert closes == [ ( "t-9", "done", { "commit": "abc1234" } ) ]
    assert summary == { "closed": [ "t-9" ], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_latest_event_no_receipt_reassigns( monkeypatch ):
    """Events exist but the LATEST carries no receipt → reassign, not close."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-3", "status": "blocked", "accountable_manager": "mr radio" } ], "count": 1 } )
    monkeypatch.setattr( tst, "task_store_request",
        lambda method, path, api_url, api_key, **kw:
            { "events": [ { "id": 1, "receipt_refs": { "commit": "x" } },
                          { "id": 2, "receipt_refs": None } ], "count": 2 } )   # latest = None
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, *a, **k: reassigns.append( task_id ) or { "item": {} } )
    monkeypatch.setattr( tst, "task_transition_impl",
        lambda *a, **k: pytest.fail( "latest event has no receipt" ) )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ "t-3" ] and summary[ "reassigned" ] == [ "t-3" ]


def test_default_reconcile_events_read_error_treated_as_no_receipt( monkeypatch ):
    """An events read returning a store-error dict → treated as no receipt → reassign
    (fail-safe-toward-reassign: never wrongly auto-close on an unreadable trail)."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-4", "status": "queued", "accountable_manager": "mr radio" } ] } )
    monkeypatch.setattr( tst, "task_store_request",
        lambda *a, **k: { "status": "error", "http_status": 404 } )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, *a, **k: reassigns.append( task_id ) or { "item": {} } )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ "t-4" ] and summary[ "reassigned" ] == [ "t-4" ]


def test_default_reconcile_events_nondict_treated_as_no_receipt( monkeypatch ):
    """An events read returning a non-dict → no receipt → reassign."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-5", "status": "queued", "accountable_manager": "mr radio" } ] } )
    monkeypatch.setattr( tst, "task_store_request", lambda *a, **k: None )       # non-dict
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, *a, **k: reassigns.append( task_id ) or { "item": {} } )
    ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ "t-5" ]


def test_default_reconcile_events_read_raises_treated_as_no_receipt( monkeypatch ):
    """A raising events read is swallowed → no receipt → reassign."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-6", "status": "queued", "accountable_manager": "mr radio" } ] } )
    monkeypatch.setattr( tst, "task_store_request",
        lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "events GET down" ) ) )
    reassigns = []
    monkeypatch.setattr( tst, "task_reassign_impl",
        lambda api_url, api_key, actor, task_id, *a, **k: reassigns.append( task_id ) or { "item": {} } )
    ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert reassigns == [ "t-6" ]


def test_default_reconcile_close_store_error_is_unclassifiable( monkeypatch ):
    """A close that returns a store-error dict → unclassifiable (not closed)."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "t-7", "status": "in_progress", "accountable_manager": "mr radio" } ] } )
    monkeypatch.setattr( tst, "task_store_request",
        lambda *a, **k: { "events": [ { "id": 1, "receipt_refs": { "commit": "z" } } ] } )
    monkeypatch.setattr( tst, "task_transition_impl",
        lambda *a, **k: { "status": "error", "http_status": 422, "errors": [ "bad receipt" ] } )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert summary == { "closed": [], "reassigned": [], "unclassifiable": [ "t-7" ] }


def test_default_reconcile_reassign_store_error_is_unclassifiable( monkeypatch ):
    """A reassign that returns a store-error dict → unclassifiable; OTHER items still process."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "ok-1",  "status": "queued", "accountable_manager": "mr radio" },
                         { "id": "bad-1", "status": "queued", "accountable_manager": "mr radio" } ], "count": 2 } )
    _no_receipt_events( monkeypatch, tst )
    def reassign( api_url, api_key, actor, task_id, new_owner, reason, **kw ):
        if task_id == "bad-1":
            return { "status": "error", "http_status": 422, "errors": [ "boom" ] }
        return { "item": {}, "event": {} }
    monkeypatch.setattr( tst, "task_reassign_impl", reassign )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert summary[ "reassigned" ]     == [ "ok-1" ]
    assert summary[ "unclassifiable" ] == [ "bad-1" ]
    assert summary[ "closed" ]         == []


def test_default_reconcile_reassign_exception_is_unclassifiable( monkeypatch ):
    """A reassign that RAISES → that item is unclassifiable; the loop continues."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "boom-1", "status": "queued", "accountable_manager": "mr radio" },
                         { "id": "ok-2",   "status": "queued", "accountable_manager": "mr radio" } ], "count": 2 } )
    _no_receipt_events( monkeypatch, tst )
    def reassign( api_url, api_key, actor, task_id, new_owner, reason, **kw ):
        if task_id == "boom-1":
            raise RuntimeError( "transport blew up" )
        return { "item": {} }
    monkeypatch.setattr( tst, "task_reassign_impl", reassign )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert summary[ "unclassifiable" ] == [ "boom-1" ]
    assert summary[ "reassigned" ]     == [ "ok-2" ]


def test_default_reconcile_skips_terminal_items( monkeypatch ):
    """done/dropped rows (the query returns all statuses for the owner) are ignored."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw:
            { "tasks": [ { "id": "d-1", "status": "done",    "accountable_manager": "mr radio" },
                         { "id": "x-1", "status": "dropped", "accountable_manager": "mr radio" } ], "count": 2 } )
    monkeypatch.setattr( tst, "task_store_request", lambda *a, **k: pytest.fail( "terminal items need no event read" ) )
    monkeypatch.setattr( tst, "task_transition_impl", lambda *a, **k: pytest.fail( "no close on terminal" ) )
    monkeypatch.setattr( tst, "task_reassign_impl",   lambda *a, **k: pytest.fail( "no reassign on terminal" ) )
    summary = ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" )
    assert summary == { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_no_persona_name_is_noop( monkeypatch ):
    import lupin_mcp.task_store_tools as tst
    monkeypatch.setattr( tst, "task_query_impl", lambda *a, **k: pytest.fail( "no query without an owner" ) )
    empty = { "closed": [], "reassigned": [], "unclassifiable": [] }
    assert ss._default_reconcile_store_items( { "persona": {} },   dead_owner_slugs=set(), reaping_manager=None ) == empty
    assert ss._default_reconcile_store_items( { "persona": None }, dead_owner_slugs=set(), reaping_manager=None ) == empty


def test_default_reconcile_string_persona_used_as_owner( monkeypatch ):
    """voice_persona as a bare string → its slug is the owner-query key (non-dict else)."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    q = []
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw: q.append( kw ) or { "tasks": [], "count": 0 } )
    ss._default_reconcile_store_items( { "persona": "Clayton" }, dead_owner_slugs={ "clayton" }, reaping_manager=None )
    assert q[ 0 ][ "owner_persona" ] == "clayton"


def test_default_reconcile_no_items_empty_summary( monkeypatch ):
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl", lambda api_url, api_key, **kw: { "tasks": [], "count": 0 } )
    monkeypatch.setattr( tst, "task_transition_impl", lambda *a, **k: pytest.fail() )
    monkeypatch.setattr( tst, "task_reassign_impl",   lambda *a, **k: pytest.fail() )
    assert ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" ) == \
        { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_query_nondict_empty( monkeypatch ):
    """task_query returning a non-dict → no tasks → empty summary (no crash)."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl", lambda api_url, api_key, **kw: [ "unexpected" ] )
    assert ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" ) == \
        { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_query_error_dict_empty( monkeypatch ):
    """task_query returning a store-error dict → no 'tasks' key → empty summary."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda api_url, api_key, **kw: { "status": "error", "http_status": 500, "detail": "x" } )
    assert ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" ) == \
        { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_query_raises_swallowed( monkeypatch ):
    """A raising task_query → swallowed → empty summary, never raises."""
    import lupin_mcp.task_store_tools as tst
    _mock_store_config( monkeypatch )
    monkeypatch.setattr( tst, "task_query_impl",
        lambda *a, **k: ( _ for _ in () ).throw( RuntimeError( "GET /api/tasks down" ) ) )
    assert ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" ) == \
        { "closed": [], "reassigned": [], "unclassifiable": [] }


def test_default_reconcile_config_failure_is_noop( monkeypatch ):
    """Store-config unavailable → best-effort empty summary, no store calls, no raise."""
    import types, lupin_mcp.task_store_tools as tst
    monkeypatch.setitem( sys.modules, "cosa.utils.config_loader",
        types.SimpleNamespace(
            get_api_config = lambda env=None: ( _ for _ in () ).throw( RuntimeError( "no config" ) ),
            load_api_key   = lambda f: "KEY" ) )
    monkeypatch.setattr( tst, "task_query_impl", lambda *a, **k: pytest.fail( "no query if config failed" ) )
    assert ss._default_reconcile_store_items(
        { "persona": { "name": "Tiffany" } }, dead_owner_slugs={ "tiffany" }, reaping_manager="Mr Radio" ) == \
        { "closed": [], "reassigned": [], "unclassifiable": [] }


# ══════════════════════════════════════════════════════════════════════════════
# RE-SPIN RETENTION (4dfb2f3b) — a re-spin must NOT un-assign the worker's rows.
#
# WHAT THE RECONCILIATION WAS PROTECTING (d647b531, established before narrowing
# it): a reaped worker's non-terminal rows orphaning on a persona that no longer
# has a live session — outstanding work owned by nobody alive, reported by
# nothing. That case is REAL and stays reconciled; the control tests below prove
# it still fires.
#
# WHY A RE-SPIN IS THE EXCEPTION: the persona comes straight back, so the premise
# ("owner has no live session") is FALSE. Reassigning anyway makes the lane read
# as un-owned — indistinguishable from a lane nobody is working — and it is
# SELF-CONCEALING, because the rows land on the manager who ordered the reap, so
# his board only looks fuller. Measured twice on 2026-07-21 (Cheech, Rio).
#
# THE CALLER KNOWS WHICH IT IS; the tool could not express it. `respin_personas`
# is that expression. It is SURFACED, never silent: `retained_owner_personas`
# echoes what was actually skipped and `retained_unmatched` names a request that
# matched no reaped persona (a typo protects nothing — old behaviour still runs,
# which is fail-safe, but it must be VISIBLE, not inferred).
#
# DELIBERATELY NOT WIDENED: a re-spun persona STAYS in `dead_owner_slugs`. That
# set answers a different question — "may another worker's row be reassigned TO
# this persona right now?" — and at reconcile time the answer is still no. The
# conservative direction preserves today's escalate-to-manager behaviour for
# OTHER workers' rows; widening it would let rows land on a seat that is not yet
# sitting.
# ══════════════════════════════════════════════════════════════════════════════

def test_respin_persona_is_not_reconciled_and_is_surfaced():
    """THE DEFECT: reaping a persona that is coming straight back must NOT touch
    its rows — and the retention must be visible in the result."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True,
            reconcile_items_fn=lambda ident, dead, mgr_p, reason="": seen.append( ident ) or
                { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] },
            respin_personas=[ "Tiffany" ] )
        assert seen == []                                        # reconciler never ran for a re-spin
        assert res[ "reconciliation" ] == { "closed": [], "reassigned": [], "unclassifiable": [] }
        assert res[ "retained_owner_personas" ] == [ "tiffany" ] # surfaced, not silent
        assert res[ "retained_unmatched" ]      == []


def test_respin_persona_matching_is_slug_tolerant():
    """A manager types the persona as displayed ("Tiffany 💍") — resolution is the
    same accent/punctuation-tolerant slug used everywhere else."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True,
            reconcile_items_fn=lambda *a, **k: seen.append( 1 ) or {},
            respin_personas=[ "  TIFFANY  " ] )
        assert seen == []
        assert res[ "retained_owner_personas" ] == [ "tiffany" ]


def test_respin_retention_is_per_persona_not_per_batch():
    """A mixed batch is the normal case: some seats come back, some do not. Only
    the named persona is retained; the other is still reconciled."""
    with tempfile.TemporaryDirectory() as tmp:
        sd  = Path( tmp )
        mgr = "mgr-abc12345"
        ss._write_manifest( ss._manifest_path( mgr, sd ),
            [ { "session_name": "cc-a-1", "session_id": "s1" },
              { "session_name": "cc-b-2", "session_id": "s2" } ] )
        for tmux, sid8, who in ( ( "cc-a-1", "aaaa1111", "Cheech" ), ( "cc-b-2", "bbbb2222", "Rachel" ) ):
            ( sd / f"cc-{sid8}.json" ).write_text( json.dumps( {
                "tmux_session": tmux, "stable_session_id": sid8,
                "voice_persona": { "name": who } } ) )
        seen = []
        def recon( ident, dead, mgr_p, reason="" ):
            seen.append( ident[ "persona" ][ "name" ] )
            return { "closed": [], "reassigned": [ "r-1" ], "unclassifiable": [] }
        res = ss.dismiss_sessions(
            mgr, runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=recon,
            respin_personas=[ "Cheech" ] )
        assert seen == [ "Rachel" ]                              # ONLY the true reap reconciled
        assert res[ "reconciliation" ][ "reassigned" ] == [ "r-1" ]
        assert res[ "retained_owner_personas" ] == [ "cheech" ]


def test_true_reap_still_reconciles_control():
    """CONTROL — the orphan case the reconciliation exists for MUST still fire.
    Same reap, no respin_personas: the reconciler runs and reassigns. If this
    ever goes green-by-skipping, the narrowing has eaten the guard it narrowed."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True,
            reconcile_items_fn=lambda ident, dead, mgr_p, reason="": seen.append( ident ) or
                { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] } )
        assert len( seen ) == 1                                  # reconcile STILL fires on a true reap
        assert res[ "reconciliation" ][ "reassigned" ] == [ "t-1" ]
        assert res[ "retained_owner_personas" ] == []


def test_respin_naming_a_persona_not_in_this_batch_is_surfaced_not_silent():
    """A typo/stale name protects nothing — the reap reconciles exactly as before
    (fail-safe toward the old behaviour), but the miss is NAMED rather than left
    for the manager to infer from an absence."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        seen = []
        res  = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True,
            reconcile_items_fn=lambda ident, dead, mgr_p, reason="": seen.append( ident ) or
                { "closed": [], "reassigned": [ "t-1" ], "unclassifiable": [] },
            respin_personas=[ "Nobody" ] )
        assert len( seen ) == 1                                  # unchanged: still reconciled
        assert res[ "reconciliation" ][ "reassigned" ] == [ "t-1" ]
        assert res[ "retained_owner_personas" ] == []
        assert res[ "retained_unmatched" ]      == [ "nobody" ]  # the miss is loud


def test_respin_persona_stays_in_dead_owner_slugs():
    """NOT WIDENED: `dead_owner_slugs` answers a DIFFERENT question — may another
    worker's row be reassigned TO this persona right now — and the answer for a
    seat that is not yet re-sitting is still no. A retained persona must remain in
    the dead set so other rows keep escalating to the manager."""
    with tempfile.TemporaryDirectory() as tmp:
        sd  = Path( tmp )
        mgr = "mgr-abc12345"
        ss._write_manifest( ss._manifest_path( mgr, sd ),
            [ { "session_name": "cc-a-1", "session_id": "s1" },
              { "session_name": "cc-b-2", "session_id": "s2" } ] )
        for tmux, sid8, who in ( ( "cc-a-1", "aaaa1111", "Cheech" ), ( "cc-b-2", "bbbb2222", "Rachel" ) ):
            ( sd / f"cc-{sid8}.json" ).write_text( json.dumps( {
                "tmux_session": tmux, "stable_session_id": sid8,
                "voice_persona": { "name": who } } ) )
        got = {}
        def recon( ident, dead, mgr_p, reason="" ):
            got[ "dead" ] = dead
            return { "closed": [], "reassigned": [], "unclassifiable": [] }
        ss.dismiss_sessions(
            mgr, runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True, reconcile_items_fn=recon,
            respin_personas=[ "Cheech" ] )
        assert "cheech" in got[ "dead" ]                         # retained ≠ alive-as-a-target
        assert "rachel" in got[ "dead" ]


def test_respin_default_none_changes_nothing():
    """Default (no respin_personas) is byte-identical to the pre-fix contract."""
    with tempfile.TemporaryDirectory() as tmp:
        sd, mgr, bridge = _setup( tmp )
        res = ss.dismiss_sessions(
            mgr, session_names=[ "cc-author-x-1" ], runner=_OK_RUNNER, session_dir=sd,
            emit_reap_fn=lambda i, reason="": None, emit_reaped_fn=lambda i: None,
            clear_hold_fn=lambda i: True )
        assert res[ "retained_owner_personas" ] == []
        assert res[ "retained_unmatched" ]      == []
