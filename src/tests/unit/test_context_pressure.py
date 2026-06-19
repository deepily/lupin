"""
Unit tests for the fleet context-pressure pure leaf.

Target: 100% lines + branches + functions on
    src/cosa/agents/heartbeat_arbiter/context_pressure.py

All fixtures are synthetic transcripts/bridges — no live fleet, no network.
Covers the expert-review corrections: 3-number model (next_prompt_estimate),
nested cache_creation drift fallback, server_tool_use ignored, cold-worker
UNKNOWN, pending-input-since-last-assistant, 3-state liveness via kill -0,
effective-ceiling math, parse-failure counting.
"""

import json
import os

import pytest

import cosa.agents.heartbeat_arbiter.context_pressure as cp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _assistant_line( *, input=0, cache_creation=None, cache_read=0, output=0,
                     nested_cc=None, server_tool_use=None, ts=None ):
    usage = { "input_tokens": input, "cache_read_input_tokens": cache_read, "output_tokens": output }
    if cache_creation is not None:
        usage[ "cache_creation_input_tokens" ] = cache_creation
    if nested_cc is not None:
        usage[ "cache_creation" ] = nested_cc
    if server_tool_use is not None:
        usage[ "server_tool_use" ] = server_tool_use
    obj = { "message": { "role": "assistant", "usage": usage } }
    if ts is not None:
        obj[ "timestamp" ] = ts
    return json.dumps( obj )


def _user_line( content ):
    return json.dumps( { "message": { "role": "user", "content": content } } )


def _write( tmp_path, name, lines ):
    p = tmp_path / name
    p.write_text( "\n".join( lines ) + "\n" )
    return str( p )


# ---------------------------------------------------------------------------
# _read_tail_lines
# ---------------------------------------------------------------------------
def test_read_tail_missing_file_returns_empty( tmp_path ):
    assert cp._read_tail_lines( str( tmp_path / "nope.jsonl" ) ) == []


def test_read_tail_empty_file_returns_empty( tmp_path ):
    p = tmp_path / "empty.jsonl"
    p.write_text( "" )
    assert cp._read_tail_lines( str( p ) ) == []


def test_read_tail_small_file_keeps_all_lines( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [ "a", "b", "c" ] )
    assert cp._read_tail_lines( path ) == [ "a", "b", "c" ]


def test_read_tail_large_file_drops_partial_first_line( tmp_path ):
    # max_bytes small enough that start > 0 → first (partial) line dropped
    lines = [ "x" * 100 for _ in range( 10 ) ]
    path  = _write( tmp_path, "big.jsonl", lines )
    out   = cp._read_tail_lines( path, max_bytes=150 )
    assert out                      # got something
    assert all( set( ln ) == { "x" } for ln in out )
    assert len( out ) < len( lines )  # dropped the leading partial + earlier lines


def test_read_tail_unreadable_open_returns_empty( tmp_path, monkeypatch ):
    path = _write( tmp_path, "t.jsonl", [ "a" ] )
    def _boom( *a, **k ):
        raise OSError( "denied" )
    monkeypatch.setattr( "builtins.open", _boom )
    assert cp._read_tail_lines( path ) == []


# ---------------------------------------------------------------------------
# _coerce_cache_creation
# ---------------------------------------------------------------------------
def test_coerce_flat_int():
    assert cp._coerce_cache_creation( { "cache_creation_input_tokens": 655 } ) == 655


def test_coerce_nested_fallback():
    usage = { "cache_creation": { "ephemeral_1h_input_tokens": 842, "ephemeral_5m_input_tokens": 0 } }
    assert cp._coerce_cache_creation( usage ) == 842


def test_coerce_nested_with_noninteger_values():
    usage = { "cache_creation": { "a": 10, "b": "x", "c": None } }
    assert cp._coerce_cache_creation( usage ) == 10


def test_coerce_absent_both_is_zero():
    assert cp._coerce_cache_creation( { } ) == 0
    assert cp._coerce_cache_creation( { "cache_creation": "notadict" } ) == 0


# ---------------------------------------------------------------------------
# read_last_usage
# ---------------------------------------------------------------------------
def test_read_last_usage_cold_worker_returns_none( tmp_path ):
    path = _write( tmp_path, "cold.jsonl", [ _user_line( "hi" ) ] )
    usage, failures, ts = cp.read_last_usage( path )
    assert usage is None and failures == 0 and ts is None


def test_read_last_usage_picks_newest_assistant( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [
        _assistant_line( input=1, cache_read=100, ts="t1" ),
        _user_line( "more" ),
        _assistant_line( input=2, cache_creation=5, cache_read=200, output=9, ts="t2" ),
    ] )
    usage, failures, ts = cp.read_last_usage( path )
    assert usage.input == 2 and usage.cache_read == 200 and usage.output == 9
    assert usage.last_prompt_size == 2 + 5 + 200
    assert ts == "t2" and failures == 0


def test_read_last_usage_counts_malformed_lines( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [ "{bad json", _assistant_line( input=1, cache_read=10 ) ] )
    usage, failures, ts = cp.read_last_usage( path )
    assert usage is not None and failures == 1


def test_read_last_usage_skips_non_dict_and_nonassistant_and_bad_usage( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [
        json.dumps( [ 1, 2, 3 ] ),                                  # valid json, not a dict
        json.dumps( { "message": "notadict" } ),                    # message not a dict
        _user_line( "hello" ),                                      # role != assistant
        json.dumps( { "message": { "role": "assistant" } } ),       # assistant, no usage
        json.dumps( { "message": { "role": "assistant", "usage": "x" } } ),  # usage not dict
    ] )
    usage, failures, ts = cp.read_last_usage( path )
    assert usage is None and failures == 0


def test_read_last_usage_nested_cache_creation_drift( tmp_path ):
    # cache_creation passed as None → flat field absent → forces the nested fallback
    line = _assistant_line( input=2, cache_read=100, nested_cc={ "ephemeral_1h_input_tokens": 50 } )
    assert "cache_creation_input_tokens" not in line   # guard: flat field really is absent
    path = _write( tmp_path, "t.jsonl", [ line ] )
    usage, _, _ = cp.read_last_usage( path )
    assert usage.cache_creation == 50


# ---------------------------------------------------------------------------
# estimate_pending_input  /  _estimate_message_tokens
# ---------------------------------------------------------------------------
def test_pending_zero_when_no_messages_after_assistant( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [ _user_line( "q" ), _assistant_line( input=1 ) ] )
    pending, failures = cp.estimate_pending_input( path )
    assert pending == 0 and failures == 0


def test_pending_sums_messages_after_last_assistant( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [
        _assistant_line( input=1 ),
        _user_line( "x" * 40 ),     # ~10 tokens
        _user_line( "y" * 80 ),     # ~20 tokens
    ] )
    pending, _ = cp.estimate_pending_input( path )
    assert pending == 30


def test_pending_all_lines_when_no_assistant_turn( tmp_path ):
    # last_assistant stays -1 → every line counts as pending
    path = _write( tmp_path, "t.jsonl", [ _user_line( "a" * 4 ) ] )
    pending, _ = cp.estimate_pending_input( path )
    assert pending == 1


def test_pending_counts_parse_failures_and_skips_none( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [ _assistant_line( input=1 ), "{broken", _user_line( "z" * 8 ) ] )
    pending, failures = cp.estimate_pending_input( path )
    assert failures == 1 and pending == 2     # the broken line skipped, "zzzzzzzz" ~2 tokens


def test_estimate_message_tokens_variants():
    assert cp._estimate_message_tokens( 123 ) == 0                                  # not a dict
    assert cp._estimate_message_tokens( { "message": { "content": None } } ) == 0   # content None
    assert cp._estimate_message_tokens( { "message": { "content": "abcd" } } ) == 1 # string content
    assert cp._estimate_message_tokens( { "content": "abcdefgh" } ) == 2            # top-level content
    structured = { "message": { "content": [ { "type": "text", "text": "hello world" } ] } }
    assert cp._estimate_message_tokens( structured ) > 0                            # serialized


# ---------------------------------------------------------------------------
# _pid_alive  /  assess_liveness
# ---------------------------------------------------------------------------
def test_pid_alive_none_and_noninteger():
    assert cp._pid_alive( None ) is False
    assert cp._pid_alive( "123" ) is False


def test_pid_alive_self_is_true():
    assert cp._pid_alive( os.getpid() ) is True


def test_pid_alive_dead_pid( monkeypatch ):
    def _gone( pid, sig ):
        raise ProcessLookupError()
    monkeypatch.setattr( os, "kill", _gone )
    assert cp._pid_alive( 999999 ) is False


def test_pid_alive_permission_error_means_exists( monkeypatch ):
    def _eperm( pid, sig ):
        raise PermissionError()
    monkeypatch.setattr( os, "kill", _eperm )
    assert cp._pid_alive( 1 ) is True


def test_pid_alive_other_oserror_is_false( monkeypatch ):
    def _oserr( pid, sig ):
        raise OSError()
    monkeypatch.setattr( os, "kill", _oserr )
    assert cp._pid_alive( 42 ) is False


def test_assess_liveness_three_states( monkeypatch ):
    # `None` must read as not-alive (real _pid_alive returns False on None), so
    # the default cc_pid=None doesn't accidentally revive the DEAD case.
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: pid not in ( 0, None ) )
    assert cp.assess_liveness( 0, 0, now=100, idle_mtime_seconds=10 ) == cp.Liveness.DEAD
    assert cp.assess_liveness( 5, 95, now=100, idle_mtime_seconds=10 ) == cp.Liveness.ACTIVE
    assert cp.assess_liveness( 5, 50, now=100, idle_mtime_seconds=10 ) == cp.Liveness.IDLE


def test_assess_liveness_cc_pid_or_matrix( monkeypatch ):
    """Decision #2: process-alive is the OR of listener_pid and cc_pid."""
    # Only pids 10 (listener) and 20 (cc_pid) are alive; everything else dead.
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: pid in ( 10, 20 ) )

    # listener alive → OR short-circuits on the LEFT (cc_pid never consulted) → ACTIVE
    assert cp.assess_liveness( 10, 95, now=100, cc_pid=None, idle_mtime_seconds=10 ) == cp.Liveness.ACTIVE
    # listener DEAD but cc_pid alive (left-False, right-True) → still alive → ACTIVE
    assert cp.assess_liveness( 0, 95, now=100, cc_pid=20, idle_mtime_seconds=10 ) == cp.Liveness.ACTIVE
    # alive-via-cc_pid but stale mtime → IDLE (mtime branch reached through the right side)
    assert cp.assess_liveness( 0, 50, now=100, cc_pid=20, idle_mtime_seconds=10 ) == cp.Liveness.IDLE
    # BOTH dead (left-False, right-False) → DEAD
    assert cp.assess_liveness( 0, 95, now=100, cc_pid=0, idle_mtime_seconds=10 ) == cp.Liveness.DEAD
    # listener DEAD + cc_pid omitted (defaults to None ⇒ not-alive) → DEAD
    assert cp.assess_liveness( 0, 95, now=100, idle_mtime_seconds=10 ) == cp.Liveness.DEAD


def test_assess_liveness_cc_pid_revives_none_listener( monkeypatch ):
    """False-DEAD protection: a missing listener_pid (None) is rescued by a live cc_pid."""
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: pid == 20 )
    assert cp.assess_liveness( None, 95, now=100, cc_pid=20, idle_mtime_seconds=10 ) == cp.Liveness.ACTIVE


# ---------------------------------------------------------------------------
# assess_context_pressure
# ---------------------------------------------------------------------------
def test_assess_unknown_on_cold_worker( tmp_path ):
    path = _write( tmp_path, "cold.jsonl", [ _user_line( "hi" ) ] )
    cpr = cp.assess_context_pressure( path )
    assert cpr.state == cp.PressureState.UNKNOWN
    assert cpr.next_prompt_estimate == 0 and cpr.pct == 0.0


def test_assess_ok_warn_critical( tmp_path ):
    # effective ceiling = 1000 - 0 - 0 = 1000
    common = dict( window_size=1000, reserve=0, max_response=0, warn_pct=70, critical_pct=85 )

    ok = _write( tmp_path, "ok.jsonl", [ _assistant_line( input=100, cache_read=100 ) ] )       # 200 → 20%
    assert cp.assess_context_pressure( ok, **common ).state == cp.PressureState.OK

    warn = _write( tmp_path, "warn.jsonl", [ _assistant_line( input=700, cache_read=50 ) ] )     # 750 → 75%
    assert cp.assess_context_pressure( warn, **common ).state == cp.PressureState.WARN

    crit = _write( tmp_path, "crit.jsonl", [ _assistant_line( input=800, cache_read=100, output=20 ) ] )  # 920 → 92%
    r = cp.assess_context_pressure( crit, **common )
    assert r.state == cp.PressureState.CRITICAL
    assert r.last_output_tokens == 20 and r.next_prompt_estimate == 920


def test_assess_includes_output_and_pending( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [
        _assistant_line( input=100, cache_read=100, output=50 ),
        _user_line( "p" * 40 ),     # ~10 pending
    ] )
    r = cp.assess_context_pressure( path, window_size=10000, reserve=0, max_response=0 )
    assert r.last_prompt_size == 200
    assert r.pending_input_estimate == 10
    assert r.next_prompt_estimate == 200 + 50 + 10


def test_assess_effective_ceiling_floored_at_one( tmp_path ):
    path = _write( tmp_path, "t.jsonl", [ _assistant_line( input=1, cache_read=1 ) ] )
    r = cp.assess_context_pressure( path, window_size=10, reserve=100, max_response=100 )
    assert r.effective_ceiling == 1            # floored, no ZeroDivision
    assert r.state == cp.PressureState.CRITICAL


# ---------------------------------------------------------------------------
# recommend
# ---------------------------------------------------------------------------
def test_recommend_all_branches():
    assert "sweep" in cp.recommend( cp.Liveness.DEAD, cp.PressureState.OK )
    assert "idle" in cp.recommend( cp.Liveness.IDLE, cp.PressureState.OK )
    assert "harvest" in cp.recommend( cp.Liveness.ACTIVE, cp.PressureState.CRITICAL )
    assert "compact soon" in cp.recommend( cp.Liveness.ACTIVE, cp.PressureState.WARN )
    assert "unknown" in cp.recommend( cp.Liveness.ACTIVE, cp.PressureState.UNKNOWN )
    assert cp.recommend( cp.Liveness.ACTIVE, cp.PressureState.OK ) == ""


# ---------------------------------------------------------------------------
# assess_fleet_context_pressure  (mock session_bridge)
# ---------------------------------------------------------------------------
def _install_fake_bridge( monkeypatch, sessions ):
    """
    Patch the REAL session_bridge.find_active_voice_persona_sessions.

    Patching the function on the imported module (rather than swapping
    sys.modules) is import-order-robust: `from ... import session_bridge`
    resolves the same module object whether or not another test already
    imported it.

    sessions: list of (path, session_id, persona_dict-or-str).
    """
    import importlib
    sb = importlib.import_module( "lupin_cli.claude_code.hooks.lib.session_bridge" )
    monkeypatch.setattr( sb, "find_active_voice_persona_sessions", lambda **k: sessions )
    return sb


def test_fleet_active_worker( tmp_path, monkeypatch ):
    transcript = _write( tmp_path, "tr.jsonl", [ _assistant_line( input=100, cache_read=100 ) ] )
    bridge = tmp_path / "cc-1.json"
    bridge.write_text( json.dumps( {
        "transcript_path": transcript, "listener_pid": os.getpid(),
        "tmux_session": "sesh", "window_size": 1000,
    } ) )
    _install_fake_bridge( monkeypatch, [ ( bridge, "s1", { "name": "Tiffany" } ) ] )
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: True )

    workers = cp.assess_fleet_context_pressure( reserve=0, max_response=0, idle_mtime_seconds=10**9 )
    assert len( workers ) == 1
    w = workers[ 0 ]
    assert w.persona == "Tiffany" and w.liveness == cp.Liveness.ACTIVE
    assert w.pressure is not None and w.pressure.window_size == 1000


def test_fleet_dead_and_idle_and_persona_as_string( tmp_path, monkeypatch ):
    transcript = _write( tmp_path, "tr.jsonl", [ _assistant_line( input=1, cache_read=1 ) ] )
    dead = tmp_path / "cc-dead.json"
    dead.write_text( json.dumps( { "transcript_path": transcript, "listener_pid": 0 } ) )
    idle = tmp_path / "cc-idle.json"
    idle.write_text( json.dumps( { "transcript_path": transcript, "listener_pid": 7, "window_size": 500 } ) )

    _install_fake_bridge( monkeypatch, [
        ( dead, "d", "PersonaString" ),          # persona as a bare string
        ( idle, "i", { "name": "Krishna" } ),
    ] )
    # dead pid → DEAD; idle pid alive but we force stale mtime via idle window 0.
    # `None` (a bridge with no cc_pid) must read as not-alive so the OR doesn't
    # revive the dead worker (Step 1.2 BOTH-pid OR).
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: pid not in ( 0, None ) )

    workers = cp.assess_fleet_context_pressure( idle_mtime_seconds=0 )
    by_id = { w.session_id: w for w in workers }
    assert by_id[ "d" ].liveness == cp.Liveness.DEAD and by_id[ "d" ].pressure is None
    assert by_id[ "d" ].persona == "PersonaString"
    assert by_id[ "i" ].liveness == cp.Liveness.IDLE and by_id[ "i" ].pressure is None


def test_fleet_cc_pid_rescues_dead_listener( tmp_path, monkeypatch ):
    """The fleet helper reads `cc_pid` from the bridge and the OR rescues a
    worker whose listener_pid is dead but whose claude-CLI pid still answers."""
    transcript = _write( tmp_path, "tr.jsonl", [ _assistant_line( input=100, cache_read=100 ) ] )
    bridge = tmp_path / "cc-rescue.json"
    bridge.write_text( json.dumps( {
        "transcript_path": transcript, "listener_pid": 0, "cc_pid": 4242,
        "window_size": 1000,
    } ) )
    _install_fake_bridge( monkeypatch, [ ( bridge, "r", { "name": "Tiffany" } ) ] )
    # listener_pid 0 is dead; only the cc_pid (4242) is alive.
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: pid == 4242 )

    workers = cp.assess_fleet_context_pressure( reserve=0, max_response=0, idle_mtime_seconds=10**9 )
    assert len( workers ) == 1
    assert workers[ 0 ].liveness == cp.Liveness.ACTIVE      # rescued via cc_pid, not DEAD
    assert workers[ 0 ].pressure is not None


def test_fleet_skips_unreadable_bridge( tmp_path, monkeypatch ):
    missing = tmp_path / "cc-missing.json"   # never created → open raises
    _install_fake_bridge( monkeypatch, [ ( missing, "x", { "name": "Ghost" } ) ] )
    workers = cp.assess_fleet_context_pressure()
    assert workers == []


def test_fleet_active_missing_transcript_key( tmp_path, monkeypatch ):
    bridge = tmp_path / "cc-no-tr.json"
    bridge.write_text( json.dumps( { "listener_pid": os.getpid() } ) )   # no transcript_path
    _install_fake_bridge( monkeypatch, [ ( bridge, "s", { "name": "Rio" } ) ] )
    monkeypatch.setattr( cp, "_pid_alive", lambda pid: True )
    workers = cp.assess_fleet_context_pressure( idle_mtime_seconds=10**9 )
    assert workers[ 0 ].liveness == cp.Liveness.ACTIVE and workers[ 0 ].pressure is None


# ---------------------------------------------------------------------------
# render_fleet_table  /  quick_smoke_test
# ---------------------------------------------------------------------------
def test_render_table_with_and_without_pressure():
    pr = cp.ContextPressure(
        last_prompt_size=200, last_output_tokens=0, pending_input_estimate=5,
        next_prompt_estimate=205, window_size=1000, effective_ceiling=1000,
        pct=20.5, state=cp.PressureState.OK,
    )
    active = cp.WorkerContextPressure( "s1", "Tiffany", "sesh", cp.Liveness.ACTIVE, pr, 1.0, "" )
    dead   = cp.WorkerContextPressure( "s2", "Ghost", None, cp.Liveness.DEAD, None, 99.0, "sweep dead bridge" )
    out    = cp.render_fleet_table( [ active, dead ] )
    assert "Tiffany" in out and "20.5%" in out
    assert "Ghost" in out and "DEAD" in out


def test_quick_smoke_test_empty( monkeypatch, capsys ):
    monkeypatch.setattr( cp, "assess_fleet_context_pressure", lambda **k: [] )
    cp.quick_smoke_test()
    assert "no active persona sessions" in capsys.readouterr().out


def test_quick_smoke_test_nonempty( monkeypatch, capsys ):
    w = cp.WorkerContextPressure( "s", "Rio", "t", cp.Liveness.ACTIVE, None, 1.0, "" )
    monkeypatch.setattr( cp, "assess_fleet_context_pressure", lambda **k: [ w ] )
    cp.quick_smoke_test()
    assert "Rio" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Usage dataclass
# ---------------------------------------------------------------------------
def test_usage_last_prompt_size_excludes_output():
    u = cp.Usage( input=10, cache_creation=20, cache_read=30, output=999 )
    assert u.last_prompt_size == 60
