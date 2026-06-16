#!/usr/bin/env python3
"""
Thread C+D (2026-06-16) — the arbiter manager-poke WAKE SURFACE: a host-side
tmux-inject hop that wakes a dormant pane, BYPASSING the listener's EVENT_IDLE
buffer gate (the non-wake root cause), runtime-selected by the
`arbiter poke wake mechanism` INI key (default "tmux").

Covers the full changed surface for 100% lines/branches/functions:
  • arbiter_live_notify.make_tmux_push_fn — dispatched / push_unavailable
    (no bridge, no tmux_session, resolve raises, inject raises), never-raises,
    default-seam selection, framing + wrap=False, log emission.
  • ArbiterConsumerJob.__init__ — poke_wake_mechanism validation + malformed
    coercion to the default "tmux" with a loud log.
  • ArbiterConsumerJob._emit_dm — the mechanism branch matrix: tmux dispatched
    (no DM fallback), tmux push_unavailable → DM fallback, tmux push_unavailable
    with no DM seam, tmux seam blow-up, tmux disabled by no-seam / no-session_id,
    mechanism=dm (tmux never called), disabled, DM blow-up; the durable board
    write is UNCONDITIONAL in every path (rider b).
  • fleet_arbiter_loop.build_fleet_arbiter_job_factory + app.assemble_app —
    the two new params thread into the recycled job.

Venue: :7999-eligible / local — pure + seam-injected (no IO, no persistent state).
Design: src/rnd/v0.1.8/2026.06.16-arbiter-tmux-wake-thread-cd-design.md.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from lupin_arbiter_app.arbiter_live_notify import make_tmux_push_fn


NOW = datetime.datetime( 2026, 6, 16, 14, 0, 0, tzinfo=datetime.timezone.utc )


# ── minimal fakes (mirrors test_arbiter_outreach_receipts._GW/_Log/_FixedClock) ─

class _GW:
    """Fake gateway: records board sends; send_boom forces a post_error."""
    def __init__( self ):
        self.sent      = [ ]               # ( recipient, body, metadata )
        self.send_boom = False
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ):
        if self.send_boom: raise RuntimeError( "store down" )
        self.sent.append( ( r, b, metadata ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class _Log:
    def __init__( self ):
        self.events = [ ]
    def __call__( self, event, **fields ):
        self.events.append( ( event, fields ) )
    def of( self, name ):
        return [ f for e, f in self.events if e == name ]


class _FixedClock:
    def __init__( self, t=NOW ):
        self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, seconds ): return None


def _job( gw=None, log=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = lambda m: [ { "channel": "live", "outcome": "queued" } ],
        log_fn            = log if log is not None else _Log(),
        clock             = _FixedClock(),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _push_results( log ):
    return [ f for f in log.of( "arbiter_outreach_result" ) if f[ "channel" ] == "dm_push" ]


def _dm_results( log ):
    return [ f for f in log.of( "arbiter_outreach_result" ) if f[ "channel" ] == "dm" ]


# ═══════════════════════════════════════════════════════════════════════════
#  A. make_tmux_push_fn — the host-side wake seam
# ═══════════════════════════════════════════════════════════════════════════

def _seamed_tmux_push( resolve, inject=None, reminder=None, log=None ):
    """A make_tmux_push_fn with all seams injected (no real IO)."""
    sink = log if log is not None else _Log()
    calls = { }
    def _inject( sid, text, wrap ): calls.update( sid=sid, text=text, wrap=wrap )
    def _reminder( body, persona, icon, msg_id, thread_id ):
        calls.update( persona=persona, icon=icon, msg_id=msg_id, thread_id=thread_id )
        return f"[FRAMED {persona}]{body}"
    fn = make_tmux_push_fn(
        resolve_fn  = resolve,
        inject_fn   = inject   or _inject,
        reminder_fn = reminder or _reminder,
        log_fn      = sink,
    )
    return fn, calls, sink


def test_tmux_push_dispatched_frames_and_injects_verbatim():
    """Resolvable bridge WITH a tmux_session → framed (wrap=False) + injected → dispatched."""
    fn, calls, sink = _seamed_tmux_push( resolve=lambda s: { "tmux_session": "cc-mgr-1" } )
    out = fn( "sess-1", "qid-9", "WAKE UP" )
    assert out == { "channel": "dm_push", "outcome": "dispatched" }
    assert calls[ "sid" ] == "sess-1" and calls[ "wrap" ] is False
    assert calls[ "text" ].startswith( "[FRAMED heartbeat-arbiter]" )   # default sender persona
    assert calls[ "icon" ] == "🛰️"                                      # default sender icon
    assert calls[ "msg_id" ] == "qid-9" and calls[ "thread_id" ] == "qid-9"
    assert sink.of( "tmux_push_attempted" )[ 0 ][ "outcome" ] == "dispatched"


def test_tmux_push_no_tmux_session_is_push_unavailable():
    """Bridge present but no tmux_session → push_unavailable (the DM-fallback signal)."""
    fn, _calls, sink = _seamed_tmux_push( resolve=lambda s: { "other": "x" } )
    out = fn( "s", "q", "b" )
    assert out[ "outcome" ] == "push_unavailable" and out[ "detail" ] == "no tmux_session in bridge"
    assert sink.of( "tmux_push_attempted" )[ 0 ][ "outcome" ] == "push_unavailable"


def test_tmux_push_no_bridge_is_push_unavailable():
    """resolve → None (no live bridge) → isinstance(None) False branch → push_unavailable."""
    fn, _calls, _sink = _seamed_tmux_push( resolve=lambda s: None )
    assert fn( "s", "q", "b" )[ "outcome" ] == "push_unavailable"


def test_tmux_push_non_dict_bridge_is_push_unavailable():
    """resolve → a non-dict → isinstance False branch → push_unavailable (never .get on a str)."""
    fn, _calls, _sink = _seamed_tmux_push( resolve=lambda s: "notadict" )
    assert fn( "s", "q", "b" )[ "outcome" ] == "push_unavailable"


def test_tmux_push_resolve_raises_never_raises():
    """A bridge-read blow-up degrades to push_unavailable, never propagates."""
    def _boom( s ): raise RuntimeError( "bridge read failed" )
    fn, _calls, _sink = _seamed_tmux_push( resolve=_boom )
    out = fn( "s", "q", "b" )
    assert out[ "outcome" ] == "push_unavailable" and "bridge read failed" in out[ "detail" ]


def test_tmux_push_inject_raises_never_raises():
    """A tmux send-keys blow-up degrades to push_unavailable, never propagates."""
    def _boom_inject( sid, text, wrap ): raise RuntimeError( "tmux socket gone" )
    fn, _calls, _sink = _seamed_tmux_push(
        resolve=lambda s: { "tmux_session": "cc-1" }, inject=_boom_inject )
    out = fn( "s", "q", "b" )
    assert out[ "outcome" ] == "push_unavailable" and "tmux socket gone" in out[ "detail" ]


def test_tmux_push_default_seams_selected_when_unset():
    """make_tmux_push_fn() with NO seams returns a callable (exercises the
    else-branches that assign the real host-side defaults) — construction only,
    not invoked (the defaults are real IO boundaries, pragma'd no-cover)."""
    fn = make_tmux_push_fn()
    assert callable( fn )


# ═══════════════════════════════════════════════════════════════════════════
#  B. ArbiterConsumerJob.__init__ — mechanism validation + coercion
# ═══════════════════════════════════════════════════════════════════════════

def test_mechanism_default_is_tmux():
    assert _job()._poke_wake_mechanism == "tmux"


def test_mechanism_dm_accepted():
    assert _job( poke_wake_mechanism="dm" )._poke_wake_mechanism == "dm"


def test_mechanism_case_and_whitespace_tolerant():
    assert _job( poke_wake_mechanism="  TMUX " )._poke_wake_mechanism == "tmux"
    assert _job( poke_wake_mechanism="DM" )._poke_wake_mechanism == "dm"


def test_mechanism_malformed_coerces_to_tmux_with_loud_log():
    log = _Log()
    job = _job( log=log, poke_wake_mechanism="bogus" )
    assert job._poke_wake_mechanism == "tmux"
    coerced = log.of( "poke_wake_mechanism_coerced" )
    assert coerced and coerced[ 0 ][ "requested" ] == "bogus" and coerced[ 0 ][ "coerced_to" ] == "tmux"


def test_mechanism_none_coerces_to_tmux():
    log = _Log()
    job = _job( log=log, poke_wake_mechanism=None )
    assert job._poke_wake_mechanism == "tmux"
    assert log.of( "poke_wake_mechanism_coerced" )


def test_tmux_push_fn_default_is_none():
    assert _job()._tmux_push_fn is None


# ═══════════════════════════════════════════════════════════════════════════
#  C. _emit_dm — the mechanism branch matrix (board write UNCONDITIONAL)
# ═══════════════════════════════════════════════════════════════════════════

def _recording_push( outcome ):
    """A push seam returning a fixed outcome and recording its call args."""
    calls = [ ]
    def fn( *args ):
        calls.append( args )
        return dict( outcome )
    return fn, calls


def test_emit_dm_tmux_dispatched_no_dm_fallback():
    """mechanism=tmux + tmux_fn + session_id → tmux dispatched; DM hop NOT called."""
    gw, log = _GW(), _Log()
    tmux_fn, tmux_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    dm_fn,   dm_calls   = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( gw=gw, log=log, tmux_push_fn=tmux_fn, dm_push_fn=dm_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "manager_stale_poke", "Tiberius", "body", session_id="sess-1" )
    assert tmux_calls == [ ( "sess-1", "oid1", "body" ) ]               # session_id, qid, body
    assert dm_calls == [ ]                                              # dispatched → no fallback
    assert _push_results( log )[ 0 ][ "outcome" ] == "dispatched"
    assert gw.sent and gw.sent[ 0 ][ 0 ] == "Tiberius"                  # durable board write happened
    assert _dm_results( log )[ 0 ][ "outcome" ] == "posted"


def test_emit_dm_tmux_unavailable_falls_back_to_dm():
    """Rider (a): tmux push_unavailable + a dm_push_fn → degrade to the DM hop."""
    log = _Log()
    tmux_fn, _tc = _recording_push( { "channel": "dm_push", "outcome": "push_unavailable" } )
    dm_fn,   dm_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( log=log, tmux_push_fn=tmux_fn, dm_push_fn=dm_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "manager_stale_poke", "Tiberius", "body", session_id="sess-1" )
    assert dm_calls == [ ( "Tiberius", "oid1", "body" ) ]               # fell back to DM
    assert _push_results( log )[ 0 ][ "outcome" ] == "dispatched"


def test_emit_dm_tmux_unavailable_no_dm_seam_stays_unavailable():
    """tmux push_unavailable with NO dm_push_fn → no fallback; outcome stays push_unavailable."""
    log = _Log()
    tmux_fn, _tc = _recording_push( { "channel": "dm_push", "outcome": "push_unavailable" } )
    job = _job( log=log, tmux_push_fn=tmux_fn, dm_push_fn=None, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "manager_stale_poke", "Tiberius", "body", session_id="sess-1" )
    assert _push_results( log )[ 0 ][ "outcome" ] == "push_unavailable"


def test_emit_dm_tmux_seam_blowup_degrades_then_falls_back():
    """A tmux_push_fn exception is caught (push_unavailable) → DM fallback; never raises."""
    log = _Log()
    def boom( *a ): raise RuntimeError( "tmux explode" )
    dm_fn, dm_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( log=log, tmux_push_fn=boom, dm_push_fn=dm_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )   # must not raise
    assert dm_calls == [ ( "Tiberius", "oid1", "body" ) ]
    assert _push_results( log )[ 0 ][ "outcome" ] == "dispatched"


def test_emit_dm_tmux_selected_but_no_seam_uses_dm():
    """mechanism=tmux but tmux_push_fn None → falls through to the DM hop."""
    log = _Log()
    dm_fn, dm_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( log=log, tmux_push_fn=None, dm_push_fn=dm_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )
    assert dm_calls == [ ( "Tiberius", "oid1", "body" ) ]


def test_emit_dm_tmux_selected_but_no_session_id_uses_dm():
    """mechanism=tmux + tmux_fn but session_id None → tmux can't resolve → DM hop."""
    log = _Log()
    tmux_fn, tmux_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    dm_fn,   dm_calls   = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( log=log, tmux_push_fn=tmux_fn, dm_push_fn=dm_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id=None )
    assert tmux_calls == [ ] and dm_calls == [ ( "Tiberius", "oid1", "body" ) ]


def test_emit_dm_mechanism_dm_never_calls_tmux():
    """mechanism=dm → DM hop even when a tmux_fn + session_id are present; tmux untouched."""
    log = _Log()
    tmux_fn, tmux_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    dm_fn,   dm_calls   = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( log=log, tmux_push_fn=tmux_fn, dm_push_fn=dm_fn, poke_wake_mechanism="dm" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )
    assert tmux_calls == [ ] and dm_calls == [ ( "Tiberius", "oid1", "body" ) ]


def test_emit_dm_no_push_seams_is_disabled():
    """mechanism=dm with NO dm_push_fn → outcome 'disabled' (board write still happened)."""
    gw, log = _GW(), _Log()
    job = _job( gw=gw, log=log, tmux_push_fn=None, dm_push_fn=None, poke_wake_mechanism="dm" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )
    assert _push_results( log )[ 0 ][ "outcome" ] == "disabled"
    assert gw.sent                                                      # board write unconditional


def test_emit_dm_dm_seam_blowup_in_bottom_path_degrades():
    """A dm_push_fn exception in the bottom (mechanism=dm) path → push_unavailable; never raises."""
    log = _Log()
    def boom( *a ): raise RuntimeError( "notify-peer down" )
    job = _job( log=log, dm_push_fn=boom, poke_wake_mechanism="dm" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )   # must not raise
    out = _push_results( log )[ 0 ]
    assert out[ "outcome" ] == "push_unavailable" and "notify-peer down" in out[ "detail" ]


def test_emit_dm_board_write_unconditional_even_on_post_error():
    """Rider (b): the durable board write runs FIRST; a post_error still lets the
    wake push hop run (the poke is never lost)."""
    gw, log = _GW(), _Log()
    gw.send_boom = True
    tmux_fn, tmux_calls = _recording_push( { "channel": "dm_push", "outcome": "dispatched" } )
    job = _job( gw=gw, log=log, tmux_push_fn=tmux_fn, poke_wake_mechanism="tmux" )
    job._emit_dm( "oid1", "stall", "Tiberius", "body", session_id="sess-1" )
    assert _dm_results( log )[ 0 ][ "outcome" ] == "post_error"         # board write attempted + failed
    assert tmux_calls == [ ( "sess-1", "oid1", "body" ) ]              # push hop STILL ran


# ═══════════════════════════════════════════════════════════════════════════
#  D. factory + assemble_app — the two new params thread into the job
# ═══════════════════════════════════════════════════════════════════════════

def test_factory_threads_tmux_seam_and_mechanism_into_job():
    from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
    from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore
    sentinel = lambda *a: { "channel": "dm_push", "outcome": "dispatched" }
    job = build_fleet_arbiter_job_factory(
        _GW(), LocalSnapshotStore(), log_fn=lambda *a, **k: None,
        manager_on_duty="dut", tmux_push_fn=sentinel, poke_wake_mechanism="dm" )()
    assert job._tmux_push_fn is sentinel and job._poke_wake_mechanism == "dm"


def test_factory_default_mechanism_is_tmux_and_no_seam():
    from lupin_arbiter_app.fleet_arbiter_loop import build_fleet_arbiter_job_factory
    from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore
    job = build_fleet_arbiter_job_factory(
        _GW(), LocalSnapshotStore(), log_fn=lambda *a, **k: None, manager_on_duty="dut" )()
    assert job._tmux_push_fn is None and job._poke_wake_mechanism == "tmux"


class _WakeCfg:
    """Fake cfg for assemble_app: health/context disabled (skip those loops);
    `arbiter poke wake mechanism` overridable; all else → the caller's default."""
    def __init__( self, mechanism="tmux" ):
        self._mechanism = mechanism
    def get( self, key, default=None, return_type="string" ):
        if key in ( "arbiter health watch enabled", "arbiter context watch enabled" ):
            return False
        if key == "arbiter poke wake mechanism":
            return self._mechanism
        return default


def test_assemble_app_reads_mechanism_key_into_job( monkeypatch ):
    import lupin_arbiter_app.app as app_module
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    sentinel = lambda *a: { "channel": "dm_push", "outcome": "dispatched" }
    app = app_module.assemble_app( _WakeCfg( mechanism="dm" ), _GW(),
                                   tmux_push_fn=sentinel, log_fn=lambda *a, **k: None )
    job = app.state.fleet_arbiter_loop._job_factory()
    assert job._poke_wake_mechanism == "dm" and job._tmux_push_fn is sentinel


def test_assemble_app_default_mechanism_is_tmux( monkeypatch ):
    import lupin_arbiter_app.app as app_module
    monkeypatch.setattr( "cosa.agents.utils.sender_id.detect_project", lambda: "lupin" )
    app = app_module.assemble_app( _WakeCfg( mechanism="tmux" ), _GW(), log_fn=lambda *a, **k: None )
    job = app.state.fleet_arbiter_loop._job_factory()
    assert job._poke_wake_mechanism == "tmux"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
