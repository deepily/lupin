"""
Unit tests for the self_respin() verb core (WI-2 of row 9e0678f6).

Target: 100% lines + branches + functions on lupin_mcp/self_respin_core.py

The gates these tests enforce (Krishna + Cheech, standing):
  · a real human "no"/"neither" schedules NOTHING;
  · the confirmation ask is UNSKIPPABLE — no kwarg reaches the schedule without it;
  · the one-shot is rm'd INSIDE the injected command at the fire point;
  · wrap=False is proven at the CALL SITE — the argv carries verbatim "/clear",
    never a speakerphone-wrapped blob;
  · the memento is proven complete + fresh-this-cycle (nonce + ts window), not
    merely present — else the verb aborts rather than clearing into nothing.

Every side-effecting seam is injected, so no live tmux / MCP / subprocess runs.
"""

import datetime
import json
import os

import pytest

import lupin_mcp.self_respin_core as sr


UTC = datetime.timezone.utc


def _dt( minute, second=0 ):
    return datetime.datetime( 2026, 8, 14, 2, minute, second, tzinfo=UTC )


# ---------------------------------------------------------------------------
# gate_proceed — the confirmation-gate decision
# ---------------------------------------------------------------------------
def test_gate_default_used_proceeds():
    ok, _ = sr.gate_proceed( f"{sr.DEFAULT_USED_MARKER}yes" )
    assert ok is True


def test_gate_default_used_proceeds_even_if_value_is_no():
    """offline/timeout substitutes the default; that default is 'yes' → PROCEED,
    regardless of the substituted token's face value."""
    ok, _ = sr.gate_proceed( f"{sr.DEFAULT_USED_MARKER}no" )
    assert ok is True


def test_gate_real_yes_proceeds():
    assert sr.gate_proceed( "yes" )[ 0 ] is True


def test_gate_real_yes_with_comment_proceeds():
    assert sr.gate_proceed( "yes [comment: go for it]" )[ 0 ] is True


def test_gate_real_no_aborts():
    ok, reason = sr.gate_proceed( "no" )
    assert ok is False
    assert "declined" in reason


def test_gate_neither_aborts():
    assert sr.gate_proceed( "neither [comment: reframe]" )[ 0 ] is False


def test_gate_non_string_aborts_fail_safe():
    assert sr.gate_proceed( None )[ 0 ] is False


# ---------------------------------------------------------------------------
# build_nonce_line + verify_memento_content — the option-(b) freshness proof
# ---------------------------------------------------------------------------
def _memento_with_nonce( uuid, ts, extra="board state...\n" ):
    return f"# memento\n{extra}{sr.build_nonce_line( uuid, ts )}\n"


def test_build_nonce_line_shape():
    line = sr.build_nonce_line( "abc-123", _dt( 20 ) )
    assert line == "SELF-RESPIN-NONCE: abc-123 @ 2026-08-14T02:20:00+00:00"


def test_verify_ok_when_nonce_present_and_fresh():
    content = _memento_with_nonce( "u1", _dt( 20 ) )
    ok, _ = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )
    assert ok is True


def test_verify_fails_on_empty_memento():
    ok, reason = sr.verify_memento_content( "   ", "u1", _dt( 21 ) )
    assert ok is False
    assert "empty" in reason


def test_verify_fails_on_none_content():
    assert sr.verify_memento_content( None, "u1", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_uuid_blank():
    content = _memento_with_nonce( "u1", _dt( 20 ) )
    assert sr.verify_memento_content( content, "", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_absent():
    """A stale body carries an OLD uuid — this cycle's uuid is simply not there."""
    content = _memento_with_nonce( "old-uuid", _dt( 20 ) )
    ok, reason = sr.verify_memento_content( content, "this-cycle-uuid", _dt( 21 ) )
    assert ok is False
    assert "not found" in reason


def test_verify_fails_when_nonce_ts_naive():
    content = f"{sr.NONCE_LINE_PREFIX} u1 @ 2026-08-14T02:20:00\n"   # no offset
    assert sr.verify_memento_content( content, "u1", _dt( 21 ) )[ 0 ] is False


def test_verify_fails_when_nonce_ts_stale():
    """Right uuid, but stamped 8 days ago → outside the cycle window → abort."""
    old  = datetime.datetime( 2026, 8, 6, 2, 20, 0, tzinfo=UTC )
    content = _memento_with_nonce( "u1", old )
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )
    assert ok is False
    assert "stale" in reason


def test_verify_rejects_future_dated_nonce():
    """A stamp in the FUTURE (corrupt/forged) must not pass (Krishna nit 1)."""
    content = _memento_with_nonce( "u1", _dt( 30 ) )   # stamped at 02:30
    ok, reason = sr.verify_memento_content( content, "u1", _dt( 21 ), cycle_window_seconds=300 )  # now 02:21
    assert ok is False
    assert "future" in reason


# ---------------------------------------------------------------------------
# build_guarded_clear_argv — the fire-point one-shot + verbatim /clear
# ---------------------------------------------------------------------------
def test_guarded_argv_consumes_token_before_send_keys():
    argv = sr.build_guarded_clear_argv( "sess", "/data/.fire.token", 20 )
    script = argv[ 2 ]
    assert 'rm "$4"' in script
    assert script.index( 'rm "$4"' ) < script.index( "send-keys" )   # consume BEFORE typing


def test_guarded_argv_carries_verbatim_clear_and_token():
    argv = sr.build_guarded_clear_argv( "sess", "/data/.fire.token", 20 )
    assert argv[ 6 ] == "/clear"                 # $3 verbatim slash command
    assert argv[ 7 ] == "/data/.fire.token"      # $4 the one-shot
    # no speakerphone wrapper text anywhere in the argv
    assert not any( "system-reminder" in part for part in argv )


# ---------------------------------------------------------------------------
# build_wake_text + build_guarded_clear_argv WAKE path (row 275cb0b9, GAP 1)
# ---------------------------------------------------------------------------
def test_build_wake_text_names_memento_and_is_plain_english():
    txt = sr.build_wake_text( "/data/lupin/.claude-memento.md", "nonce-7", "/data/.wake-proof.marker" )
    assert "/data/lupin/.claude-memento.md" in txt
    assert "self-re-sp" in txt.lower()           # "self-re-spun"
    assert "memento" in txt.lower()
    assert "resume" in txt.lower()
    # consumer-proof instruction: the seat must write the nonce-echoing proof line
    assert "/data/.wake-proof.marker" in txt                       # names the proof artifact
    assert f"{sr._WAKE_PROOF_NONCE_LINE} nonce-7" in txt           # the exact line to echo
    assert "\n" not in txt                                         # single line (send-keys -l + one Enter)


def test_guarded_argv_wake_path_appends_wake_bridge_and_poll_args():
    argv = sr.build_guarded_clear_argv(
        "sess", "/data/.fire.token", 20,
        wake_text="READ YOUR MEMENTO", bridge_path="/s/cc-42.json",
        ready_timeout_polls=7, poll_interval_seconds=0.5,
    )
    # $1-$4 unchanged (existing index contract preserved), $5-$8 appended
    assert argv[ 6 ] == "/clear"
    assert argv[ 7 ] == "/data/.fire.token"
    assert argv[ 8 ] == "READ YOUR MEMENTO"      # $5 wake, typed -l
    assert argv[ 9 ] == "/s/cc-42.json"          # $6 bridge (readiness oracle)
    assert argv[ 10 ] == "7"                     # $7 bounded poll count
    assert argv[ 11 ] == "0.5"                   # $8 poll interval


def test_guarded_argv_wake_path_gates_on_bridge_mtime_not_send_keys_exit():
    """Ruling 1: readiness is the bridge-file rewrite (mtime change), never a
    send-keys exit code; ruling 3: ONE chain; ruling 4: literal wake keystroke."""
    script = sr.build_guarded_clear_argv(
        "sess", "/f.token", 20, wake_text="WAKE", bridge_path="/s/cc-42.json" )[ 2 ]
    assert 'date -r "$6" +%s%N' in script            # bridge mtime is the oracle
    assert '[ "$m" -gt "$m0" ]' in script            # strictly-greater (race-free) compare
    assert 'rm "$4" || exit 0' in script             # one-shot guard preserved
    assert 'send-keys -t "$2" -l -- "$5"' in script  # literal (-l) wake keystroke
    assert "exit 3" in script                        # loud, bounded give-up on timeout
    # the wake is typed AFTER the readiness gate, never before it
    assert script.index( 'date -r "$6"' ) < script.index( '-l -- "$5"' )


# ---------------------------------------------------------------------------
# perform_self_respin — over-budget grounds gate (row 275cb0b9, ruling 2)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize( "status", [ "within_budget", "unknown", "idle", None ] )
def test_perform_aborts_when_not_over_budget( tmp_path, status ):
    """No proven over_budget reading ⇒ no grounds to clear ⇒ abort. Covers the exact
    GAP-3 systemic case (status 'unknown' from a failed pressure fetch)."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    ask   = _Spy()
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status=status, pre_clear_pct=None,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=ask, schedule_fn=sched,
        base_dir=str( tmp_path ),
    )
    assert r.status == "aborted"
    assert "no grounds to clear" in r.reason
    assert ask.calls   == 0                                        # never asked
    assert sched.calls == 0                                        # never scheduled
    assert list( tmp_path.glob( ".self-respin-*" ) ) == []        # no marker/token written


# ---------------------------------------------------------------------------
# perform_self_respin — the WAKE go-path (row 275cb0b9, GAP 1)
# ---------------------------------------------------------------------------
def test_perform_schedules_wake_argv_when_bridge_resolves( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        wake_nonce="wn-1", resolve_bridge_path_fn=lambda sid: "/s/cc-42.json",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )
    assert r.status == "scheduled"
    argv = scheduled[ 0 ]
    # argv[8] is the FULL built wake text — it carries the proof instruction + nonce
    assert f"{sr._WAKE_PROOF_NONCE_LINE} wn-1" in argv[ 8 ]        # wake rode the SAME chain, nonce-bound
    assert argv[ 9 ] == "/s/cc-42.json"           # gated on this bridge's mtime
    # the marker records the wake_nonce the seat must echo; a stale proof was pre-removed
    marker = json.loads( ( tmp_path / ".self-respin-sid1.json" ).read_text() )
    assert marker[ "wake_nonce" ] == "wn-1"


def test_perform_falls_back_to_plain_clear_when_bridge_unresolvable( tmp_path ):
    """A wake was requested but the bridge path can't be resolved → schedule the
    plain clear anyway (never block the re-spin on an un-resolvable wake)."""
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        wake_nonce="wn-1", resolve_bridge_path_fn=lambda sid: None,
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )
    assert r.status == "scheduled"
    argv = scheduled[ 0 ]
    assert len( argv ) == 8                        # plain single-chain argv, no wake args
    assert argv[ 6 ] == "/clear"
    # no wake ⇒ no wake_nonce requirement recorded in the marker
    marker = json.loads( ( tmp_path / ".self-respin-sid1.json" ).read_text() )
    assert marker[ "wake_nonce" ] is None


# ---------------------------------------------------------------------------
# perform_self_respin — the full ordered decision tree
# ---------------------------------------------------------------------------
class _Spy:
    def __init__( self, ret="yes" ):
        self.calls = 0
        self.ret   = ret
    def __call__( self, *a, **k ):
        self.calls += 1
        return self.ret


def _seat( tmux="cheech-mgr" ):
    return lambda sid: tmux


def _write_memento( tmp_path, uuid, ts ):
    p = tmp_path / ".claude-memento.md"
    p.write_text( _memento_with_nonce( uuid, ts ) )
    return str( p )


def test_perform_aborts_when_no_tmux():
    ask = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path="/nope", memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=lambda sid: None, ask_fn=ask,
        schedule_fn=_Spy(), base_dir="/tmp",
    )
    assert r.status == "aborted"
    assert ask.calls == 0   # never asked — no seat to clear


def test_perform_aborts_on_bad_memento_without_asking( tmp_path ):
    """Memento verify runs BEFORE the ask; a stale memento aborts and never asks."""
    mp  = _write_memento( tmp_path, "old", _dt( 20 ) )
    ask = _Spy()
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="this-cycle",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=ask, schedule_fn=sched,
        base_dir=str( tmp_path ),
    )
    assert r.status == "aborted"
    assert ask.calls   == 0
    assert sched.calls == 0


def test_perform_declines_on_human_no_schedules_nothing( tmp_path ):
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "no", schedule_fn=sched,
        base_dir=str( tmp_path ),
    )
    assert r.status == "declined"
    assert sched.calls == 0
    # and no marker/token were written on a decline
    assert list( tmp_path.glob( ".self-respin-*" ) ) == []


def test_perform_scheduled_happy_path_writes_marker_and_token( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat( "cheech-mgr" ), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )
    assert r.status == "scheduled"
    # observer marker persists (it is NOT the file the injector rm's)
    marker = tmp_path / ".self-respin-sid1.json"
    assert marker.exists()
    assert json.loads( marker.read_text() )[ "pre_clear_status" ] == "over_budget"
    # fire token written separately
    assert ( tmp_path / ".self-respin-fire-sid1.token" ).exists()
    # scheduled argv carries verbatim /clear + the fire token, and rm's it first
    argv = scheduled[ 0 ]
    assert argv[ 6 ] == "/clear"
    assert argv[ 7 ] == str( tmp_path / ".self-respin-fire-sid1.token" )


def test_perform_proceeds_on_offline_default_used( tmp_path ):
    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: f"{sr.DEFAULT_USED_MARKER}yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )
    assert r.status == "scheduled"
    assert len( scheduled ) == 1


def test_perform_aborts_when_marker_readback_fails( tmp_path ):
    """If the marker cannot be read back durable, we refuse to clear (no record)."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()
    # write_json that silently drops the marker → read-back finds nothing
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes", schedule_fn=sched,
        base_dir=str( tmp_path ), write_json_fn=lambda path, data: None,
    )
    assert r.status == "aborted"
    assert sched.calls == 0


def test_perform_aborts_when_fire_token_readback_fails_and_removes_marker( tmp_path ):
    """The marker writes durably but the fire token does not (Krishna nit 2): the
    verb must abort AND remove the marker so it can't raise a false DEAD alarm."""
    mp    = _write_memento( tmp_path, "u1", _dt( 20 ) )
    sched = _Spy()

    def selective_write( path, data ):
        # key on the BASENAME — the pytest tmp dir name itself contains "fire"
        if os.path.basename( path ).startswith( sr.FIRE_TOKEN_PREFIX ):
            return                       # silently drop the fire token
        with open( path, "w" ) as f:     # write the marker durably
            json.dump( data, f )

    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes", schedule_fn=sched,
        base_dir=str( tmp_path ), write_json_fn=selective_write,
    )
    assert r.status == "aborted"
    assert sched.calls == 0
    assert not ( tmp_path / ".self-respin-sid1.json" ).exists()   # marker cleaned up


def test_best_effort_remove_swallows_missing_file( tmp_path ):
    sr._best_effort_remove( str( tmp_path / "nope" ) )            # must not raise


def test_perform_honors_grace_seconds_in_deadline( tmp_path ):
    mp = _write_memento( tmp_path, "u1", _dt( 20 ) )
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 20 ), delay_seconds=20, grace_seconds=100,
        resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: None, base_dir=str( tmp_path ),
    )
    # deadline = fired 02:20:00 + 20 + 100 = 02:22:00
    assert r.expected_return_by == _dt( 22 ).isoformat()


# ---------------------------------------------------------------------------
# _readback_ok + _default_read_text — the small IO helpers
# ---------------------------------------------------------------------------
def test_readback_ok_true_false_and_bad_json( tmp_path ):
    p = tmp_path / ".self-respin-sid1.json"
    p.write_text( json.dumps( { "session_id": "sid1" } ) )
    assert sr._readback_ok( sr._default_read_text, str( p ), "sid1" ) is True
    assert sr._readback_ok( sr._default_read_text, str( p ), "other" ) is False
    p.write_text( "{not json" )
    assert sr._readback_ok( sr._default_read_text, str( p ), "sid1" ) is False
    assert sr._readback_ok( sr._default_read_text, str( tmp_path / "missing.json" ), "sid1" ) is False


def test_default_read_text_missing_returns_none( tmp_path ):
    assert sr._default_read_text( str( tmp_path / "nope" ) ) is None


def test_default_read_text_reads_file( tmp_path ):
    p = tmp_path / "f.txt"
    p.write_text( "hello" )
    assert sr._default_read_text( str( p ) ) == "hello"


# ---------------------------------------------------------------------------
# self_respin_from_bridge — identity from the bridge, never from the caller
# ---------------------------------------------------------------------------
def test_from_bridge_aborts_when_no_session_id():
    called = []
    r = sr.self_respin_from_bridge(
        "/m", "u1",
        identity_fn = lambda: ( None, "cheech" ),
        pressure_fn = lambda p: ( "over_budget", 61.0 ),
        perform_fn  = lambda *a, **k: called.append( ( a, k ) ),
    )
    assert r.status == "aborted"
    assert called == []   # never reaches perform — no blind clear


def test_from_bridge_passes_resolved_identity_and_pressure_to_perform():
    seen = {}
    def fake_perform( session_id, **k ):
        seen[ "session_id" ] = session_id
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )

    r = sr.self_respin_from_bridge(
        "/memento", "nonce-9", delay_seconds=30, cycle_window_seconds=120,
        identity_fn = lambda: ( "sid-self", "cheech" ),
        pressure_fn = lambda persona: ( "over_budget", 62.4 ),
        perform_fn  = fake_perform,
    )
    assert r.status == "scheduled"
    assert seen[ "session_id" ]       == "sid-self"      # from the bridge, not a caller arg
    assert seen[ "persona" ]          == "cheech"
    assert seen[ "pre_clear_status" ] == "over_budget"
    assert seen[ "pre_clear_pct" ]    == 62.4
    assert seen[ "memento_path" ]     == "/memento"
    assert seen[ "memento_nonce" ]    == "nonce-9"
    assert seen[ "delay_seconds" ]    == 30
    assert seen[ "cycle_window_seconds" ] == 120


def test_from_bridge_mints_and_passes_wake_nonce():
    seen = {}
    def fake_perform( session_id, **k ):
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )
    sr.self_respin_from_bridge(
        "/data/.claude-memento.md", "n1",
        identity_fn = lambda: ( "sid-self", "cheech" ),
        pressure_fn = lambda persona: ( "over_budget", 61.0 ),
        perform_fn  = fake_perform,
    )
    # from_bridge mints the consumer-proof nonce (default uuid) and hands it to perform;
    # perform builds the wake TEXT internally (proof is consumer-side, not caller-supplied)
    assert isinstance( seen[ "wake_nonce" ], str ) and seen[ "wake_nonce" ]
    assert "wake_text" not in seen                               # no longer a from_bridge arg


def test_from_bridge_uses_injected_wake_nonce_fn():
    """The nonce seam is injectable — a supplied wake_nonce_fn is used verbatim."""
    seen = {}
    def fake_perform( session_id, **k ):
        seen.update( k )
        return sr.SelfRespinResult( status="scheduled", reason="ok" )
    sr.self_respin_from_bridge(
        "/m", "n1",
        identity_fn   = lambda: ( "sid-self", "cheech" ),
        pressure_fn   = lambda persona: ( "over_budget", 61.0 ),
        wake_nonce_fn = lambda: "fixed-nonce-42",
        perform_fn    = fake_perform,
    )
    assert seen[ "wake_nonce" ] == "fixed-nonce-42"


def test_from_bridge_default_perform_fn_is_the_real_verb():
    """The default perform_fn is perform_self_respin — the seam is wired, not stubbed."""
    assert sr.self_respin_from_bridge.__defaults__ is None  # keyword-only signature
    # exercised end-to-end via the aborts-early path (no session id → no perform call)
    r = sr.self_respin_from_bridge(
        "/m", "u1",
        identity_fn = lambda: ( "", "" ),
        pressure_fn = lambda p: ( "over_budget", None ),
    )
    assert r.status == "aborted"


# ---------------------------------------------------------------------------
# resolve_identity_from_cc_meta — the pure bridge-precedence helper
# ---------------------------------------------------------------------------
def test_resolve_identity_prefers_stable_and_reads_persona_name():
    sid, persona = sr.resolve_identity_from_cc_meta(
        { "stable_session_id": "stable1", "session_id": "plain1", "voice_persona": { "name": "cheech" } },
        "FALLBACK",
    )
    assert sid == "stable1"
    assert persona == "cheech"


def test_resolve_identity_falls_back_through_plain_then_fallback_and_unknown():
    assert sr.resolve_identity_from_cc_meta( { "session_id": "plain1" }, "FB" ) == ( "plain1", "unknown" )
    assert sr.resolve_identity_from_cc_meta( {}, "FB" ) == ( "FB", "unknown" )
    # a present-but-empty voice_persona still yields "unknown"
    assert sr.resolve_identity_from_cc_meta( { "session_id": "s", "voice_persona": None }, "FB" )[ 1 ] == "unknown"


def test_resolve_own_identity_success():
    got = sr.resolve_own_identity(
        lambda: { "stable_session_id": "stable1", "voice_persona": { "name": "cheech" } }, "FB"
    )
    assert got == ( "stable1", "cheech" )


def test_resolve_own_identity_falls_back_when_metadata_raises():
    """The wrapper's old try/except lives HERE now and is tested directly:
    a raising bridge read must fall back to the SESSION_ID prefix, not crash."""
    def _boom():
        raise RuntimeError( "bridge unavailable" )
    assert sr.resolve_own_identity( _boom, "FALLBACK_SID" ) == ( "FALLBACK_SID", "unknown" )


# ---------------------------------------------------------------------------
# wrap=False is proven where it could bite: the speakerphone rider is NEVER
# applied by the scheduling path (Krishna's gate — the core builds the argv
# directly, never through inject_qualifier_via_tmux)
# ---------------------------------------------------------------------------
def test_schedule_path_never_applies_speakerphone_rider( tmp_path, monkeypatch ):
    import lupin_cli.claude_code.hooks.lib.hook_common as hook_common
    wraps = []
    monkeypatch.setattr( hook_common, "speakerphone_wrap",
                         lambda *a, **k: wraps.append( a ) or "WRAPPED!!" )

    mp        = _write_memento( tmp_path, "u1", _dt( 20 ) )
    scheduled = []
    r = sr.perform_self_respin(
        "sid1", persona="cheech", memento_path=mp, memento_nonce="u1",
        pre_clear_status="over_budget", pre_clear_pct=61.0,
        now=_dt( 21 ), resolve_tmux_fn=_seat(), ask_fn=lambda: "yes",
        schedule_fn=lambda argv: scheduled.append( argv ), base_dir=str( tmp_path ),
    )
    assert r.status == "scheduled"
    assert wraps == []                              # the rider was NEVER applied
    assert scheduled[ 0 ][ 6 ] == "/clear"          # verbatim slash command, not a wrapped blob
    assert not any( "WRAPPED" in part for part in scheduled[ 0 ] )


# ---------------------------------------------------------------------------
# parse_own_pressure — the pure parse lifted out of _live_own_pressure's pragma
# (R1: the logic that held a wrong default for a day is now covered, both arms)
# ---------------------------------------------------------------------------
def test_parse_own_pressure_present_persona_returns_status_and_pct():
    section = { "personas": { "cheech": { "status": "over_budget", "consumption_pct_of_window": 61.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "over_budget", 61.0 )


def test_parse_own_pressure_absent_persona_is_unknown_none():
    section = { "personas": { "someone_else": { "status": "within_budget" } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "unknown", None )


def test_parse_own_pressure_missing_status_is_unknown_but_keeps_pct():
    # a record present without a status must NOT manufacture over_budget
    section = { "personas": { "cheech": { "consumption_pct_of_window": 42.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "unknown", 42.0 )


def test_parse_own_pressure_blank_status_is_unknown():
    section = { "personas": { "cheech": { "status": "", "consumption_pct_of_window": 5.0 } } }
    assert sr.parse_own_pressure( section, "cheech" ) == ( "unknown", 5.0 )


def test_parse_own_pressure_personas_not_a_dict_is_unknown_none():
    assert sr.parse_own_pressure( { "personas": None }, "cheech" ) == ( "unknown", None )
    assert sr.parse_own_pressure( { "personas": [ "not", "a", "dict" ] }, "cheech" ) == ( "unknown", None )


def test_parse_own_pressure_section_not_a_dict_is_unknown_none():
    # the fetch-failure path feeds {} (or a stray non-dict) — must be unknown, never over_budget
    assert sr.parse_own_pressure( {}, "cheech" ) == ( "unknown", None )
    assert sr.parse_own_pressure( None, "cheech" ) == ( "unknown", None )
