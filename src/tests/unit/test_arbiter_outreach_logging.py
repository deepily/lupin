#!/usr/bin/env python3
"""
Post-game F1 receipts (2026-06-11) — structured outreach + gate-evaluation logging.

Rick's verbatim ask: "make sure that the arbiter service is creating a log so
that we can see when it's attempting to reach out and communicate." The
2026-06-10 journal carried exactly 3 event types all day (health_obs,
context_pressure_written, fleet_arbiter_render) — zero outreach visibility.
Receipts:
  • `arbiter_outreach` fires at EVERY emission path — each _route tier, the
    stuck-tier poke, the staleness poke, the decision cc, the poll-error
    escalation — with recipients mirroring the actual pushes.
  • `arbiter_poke_gate` (why-not-poked) emits on CHANGE + the periodic dump +
    the eviction event — silence is diagnosable.
  • `arbiter_poll_activity` promotes the poll summary iff any outreach counter
    is nonzero.
  • the _log seam swallows a log_fn blow-up (telemetry never kills a poll);
    the module default log fn prints one JSON line.

Venue: :7999-eligible / local — pure + mocked.
Design: src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §3.1.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    ArbiterConsumerJob, GATE_DUMP_INTERVAL_POLLS, OUTREACH_SUMMARY_MAXLEN,
    _default_log_fn, _fmt_eastern, _fmt_minutes,
)


NOW = datetime.datetime( 2026, 6, 11, 18, 0, 0, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class _Log:
    def __init__( self ):
        self.events = [ ]
    def __call__( self, event, **fields ):
        self.events.append( ( event, fields ) )
    def of( self, name ):
        return [ f for e, f in self.events if e == name ]


def _job( gw=None, log=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify or ( lambda *a, **k: None ),
        log_fn            = log if log is not None else _Log(),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


# ── module helpers: default log fn + EDT/minutes formatters ──────────────────

def test_default_log_fn_emits_one_json_line( capsys ):
    _default_log_fn( "arbiter_outreach", kind="stuck_poke", recipients=[ "P" ] )
    line = json.loads( capsys.readouterr().out.strip() )
    assert line[ "service" ] == "heartbeat-arbiter" and line[ "event" ] == "arbiter_outreach"
    assert line[ "kind" ] == "stuck_poke" and line[ "recipients" ] == [ "P" ] and "ts" in line


def test_fmt_eastern_labels_zone_and_degrades():
    out = _fmt_eastern( NOW )
    assert out.endswith( "EDT" ) or out.endswith( "EST" )            # zone-labeled, never bare
    assert _fmt_eastern( None ) == "unknown"
    assert _fmt_eastern( "not-a-datetime" ) == "unknown"             # exception → degrade


def test_fmt_minutes():
    assert _fmt_minutes( 2700 ) == "45m" and _fmt_minutes( 59 ) == "0m"
    assert _fmt_minutes( None ) == "unknown"


def test_log_seam_swallows_log_fn_blowup():
    def _boom( event, **fields ): raise RuntimeError( "log sink down" )
    job = _job( log=_boom )
    job._log( "arbiter_outreach", kind="stuck_poke" )                      # must not raise


# ── arbiter_outreach: every emission path is journaled ───────────────────────

def test_route_tiers_log_actual_recipients():
    """The S3 accounting contract at the _route layer — RESTATED by the
    2026.06.11 receipts design: `recipients` is the PLANNED set; per-hop reality
    lives in arbiter_outreach_result events (test_arbiter_outreach_receipts).
    No-emission routes still log nothing."""
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._route( 5, "deadlock!", active_managers=[ "M1", "M2" ] )     # RICK_AND_MANAGERS
    job._route( 1, "infra", active_managers=[ "MX" ] )               # RICK_ONLY ignores managers
    job._route( 7, "tap", owning_manager="MgrX" )                    # OWNING_MANAGER
    job._route( 7, "tap", owning_manager=None )                      # no emission → no log
    job._route( 4, "ping", blocker="Blk", owning_manager="MgrB", cc_message="cc" )
    job._route( 6, "roster" )                                        # DROP → no log
    out = log.of( "arbiter_outreach" )
    assert [ f[ "recipients" ] for f in out ] == [
        [ "rick", "M1", "M2" ], [ "rick" ], [ "MgrX" ], [ "Blk", "MgrB" ] ]
    # kinds ride the CASE_KINDS vocabulary; case 1 has no entry → generic fallback
    assert out[ 0 ][ "kind" ] == "deadlock" and out[ 0 ][ "case" ] == 5
    assert out[ 1 ][ "kind" ] == "case_1"                            # health cases route via the app, not here
    assert out[ 2 ][ "kind" ] == "tap" and out[ 3 ][ "kind" ] == "ping"


def test_stuck_poke_logs_outreach_with_session_fields():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, poke_stall_threshold_seconds=0 )
    fleet = { "s1": { "session_id": "s1", "persona": "Stuckie", "state": "stuck",
                      "stuck": True, "holding_on": "none", "alive": True } }
    job._auto_poke( fleet, NOW, [ ] )
    pokes = [ f for f in log.of( "arbiter_outreach" ) if f[ "kind" ] == "stuck_poke" ]
    assert len( pokes ) == 1
    assert pokes[ 0 ][ "recipients" ] == [ "Stuckie" ] and pokes[ 0 ][ "session_id" ] == "s1"
    assert pokes[ 0 ][ "via" ] == "send_to" and "STUCK" in pokes[ 0 ][ "summary" ]


def test_summary_is_truncated():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._route( 5, "x" * 500, active_managers=[ ] )
    assert len( log.of( "arbiter_outreach" )[ 0 ][ "summary" ] ) == OUTREACH_SUMMARY_MAXLEN


def test_decision_cc_and_poll_error_escalation_log_outreach():
    gw, log, notes = _GW(), _Log(), [ ]
    job = _job( gw, log=log, notify=notes.append, poll_error_escalate_threshold=2,
                resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrD", "source": "lineage" } )
    job._cc_decision_manager( { "sender_session_id": "s1", "body": "scope?" } )
    job._on_poll_error( RuntimeError( "boom1" ) )                    # below threshold → render-sink only
    job._on_poll_error( RuntimeError( "boom2" ) )                    # threshold → Rick escalation
    out = log.of( "arbiter_outreach" )
    assert [ f[ "kind" ] for f in out ] == [ "decision_cc", "poll_error_escalation" ]
    assert out[ 0 ][ "recipients" ] == [ "MgrD" ]
    assert out[ 1 ][ "recipients" ] == [ "rick" ] and out[ 1 ][ "via" ] == "notify"
    assert notes and "ARBITER POLL-ERROR persistent" in notes[ 0 ]


# ── arbiter_poke_gate: on-change + periodic dump + eviction ──────────────────

def _view( sid, *, alive=True, stuck=False, persona=None ):
    return { sid: { "session_id": sid, "persona": persona or sid, "state": "working",
                    "stuck": stuck, "holding_on": "none", "alive": alive } }


def _snap_rows( *rows ):
    return { "sessions": list( rows ) }


def test_gate_emits_on_first_sight_change_and_eviction():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._poll_count = 1                                              # off the dump cadence
    fleet = _view( "s1" )
    snap  = _snap_rows( { "session_id": "s1", "role": "worker",
                          "liveness": { "freshest_age_s": 60 } } )
    job._emit_poke_gates( fleet, snap, NOW )                         # first sight → emit
    job._emit_poke_gates( fleet, snap, NOW )                         # unchanged → silent
    gates = log.of( "arbiter_poke_gate" )
    assert len( gates ) == 1
    assert gates[ 0 ][ "stuck_pokeable" ] is False
    assert gates[ 0 ][ "stuck_why_not" ] == [ "not_stuck" ]          # alive worker, not stuck
    assert gates[ 0 ][ "stale_why_not" ] == [ "not_manager" ]
    # change: the worker becomes stuck → re-emit with the new vector
    job._emit_poke_gates( _view( "s1", stuck=True ), snap, NOW )
    gates = log.of( "arbiter_poke_gate" )
    assert len( gates ) == 2 and gates[ 1 ][ "stuck_why_not" ] == [ ]
    assert gates[ 1 ][ "stuck_pokeable" ] is True
    # eviction: the session leaves the fleet view → one evicted event
    job._emit_poke_gates( { }, _snap_rows(), NOW )
    gates = log.of( "arbiter_poke_gate" )
    assert len( gates ) == 3 and gates[ 2 ] == { "session_id": "s1", "evicted": True }
    assert job._gate_state == { }


def test_gate_dump_poll_reemits_unchanged_vectors():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    fleet = _view( "s1" )
    snap  = _snap_rows( { "session_id": "s1", "role": "worker",
                          "liveness": { "freshest_age_s": 60 } } )
    job._poll_count = 1
    job._emit_poke_gates( fleet, snap, NOW )                         # first sight
    job._poll_count = GATE_DUMP_INTERVAL_POLLS                       # the hourly dump poll
    job._emit_poke_gates( fleet, snap, NOW )                         # unchanged BUT dump → re-emit
    assert len( log.of( "arbiter_poke_gate" ) ) == 2


def test_gate_vectors_cover_threshold_cap_and_disabled():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, poke_stall_threshold_seconds=600, poke_max_per_episode=1 )
    job._poll_count = 1
    stuck = _view( "s1", stuck=True )
    snap  = _snap_rows( { "session_id": "s1", "role": "worker",
                          "liveness": { "freshest_age_s": 60 } } )
    job._auto_poke( stuck, NOW, [ ] )                                # seeds the episode (no poke yet)
    job._emit_poke_gates( stuck, snap, NOW )
    assert log.of( "arbiter_poke_gate" )[ -1 ][ "stuck_why_not" ] == [ "below_threshold" ]
    # past the threshold + capped: poke once, then the gate reads capped
    later = NOW + datetime.timedelta( seconds=600 )
    job._auto_poke( stuck, later, [ ] )                              # fires the 1 allowed poke
    job._emit_poke_gates( stuck, snap, later )
    assert log.of( "arbiter_poke_gate" )[ -1 ][ "stuck_why_not" ] == [ "capped" ]
    # after the reap-rec escalation the vector reads already_escalated
    job._auto_poke( stuck, later + datetime.timedelta( seconds=60 ), [ ] )
    job._emit_poke_gates( stuck, snap, later + datetime.timedelta( seconds=60 ) )
    assert log.of( "arbiter_poke_gate" )[ -1 ][ "stuck_why_not" ] == [ "already_escalated" ]


def test_gate_disabled_and_tier_disabled_and_mgr_capped_and_not_stale():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, auto_poke_enabled=False,
                manager_stale_poke_threshold_seconds=0 )
    job._poll_count = 1
    fleet = _view( "m1", alive=False )
    snap  = _snap_rows( { "session_id": "m1", "role": "manager",
                          "liveness": { "freshest_age_s": 9999 } } )
    job._emit_poke_gates( fleet, snap, NOW )
    g = log.of( "arbiter_poke_gate" )[ 0 ]
    assert g[ "stuck_why_not" ] == [ "disabled", "not_alive", "not_stuck" ]
    assert g[ "stale_why_not" ] == [ "tier_disabled" ]
    # a live manager below the threshold reads not_stale; a poke-capped one mgr_capped
    job2  = _job( _GW(), log=( log2 := _Log() ), poke_max_per_episode=1 )
    job2._poll_count = 1
    snap_fresh = _snap_rows( { "session_id": "m1", "role": "manager",
                               "liveness": { "freshest_age_s": 60 } } )
    job2._emit_poke_gates( _view( "m1" ), snap_fresh, NOW )
    assert log2.of( "arbiter_poke_gate" )[ -1 ][ "stale_why_not" ] == [ "not_stale" ]
    snap_stale = _snap_rows( { "session_id": "m1", "role": "manager",
                               "liveness": { "freshest_age_s": 5000 } } )   # in [threshold, max_age]
    job2._check_manager_staleness( snap_stale, NOW, [ ] )            # poke 1 → capped
    job2._emit_poke_gates( _view( "m1" ), snap_stale, NOW )
    assert log2.of( "arbiter_poke_gate" )[ -1 ][ "stale_why_not" ] == [ "mgr_capped" ]
    # liveness-malformed manager row: age None → no_signal (corpse-ceiling flip
    # 2026-06-11; was eligible/no-why_not). The same emission also EVICTS m1 (it
    # left the fleet view), so select m2's gate event.
    snap_bad = _snap_rows( { "session_id": "m2", "role": "manager", "liveness": "bad" } )
    job2._emit_poke_gates( _view( "m2" ), snap_bad, NOW )
    m2_gates = [ g for g in log2.of( "arbiter_poke_gate" )
                 if g.get( "session_id" ) == "m2" and not g.get( "evicted" ) ]
    assert m2_gates[ -1 ][ "stale_why_not" ] == [ "no_signal" ]
    evictions = [ g for g in log2.of( "arbiter_poke_gate" ) if g.get( "evicted" ) ]
    assert evictions == [ { "session_id": "m1", "evicted": True } ]


def test_gate_skips_non_dict_views():
    gw, log = _GW(), _Log()
    job = _job( gw, log=log )
    job._poll_count = 1
    job._emit_poke_gates( { "bad": "not-a-dict" }, _snap_rows(), NOW )
    assert log.of( "arbiter_poke_gate" ) == [ ]


# ── arbiter_poll_activity: summary promoted iff outreach happened ────────────

def test_poll_activity_logged_only_when_counters_nonzero( tmp_path ):
    gw, log = _GW(), _Log()
    job = _job( gw, log=log, events_dir=str( tmp_path ),
                bridge_discovery_fn=lambda: { },
                bridge_mtime_fn=lambda sid: None,
                render_sink=lambda s: None, snapshot_sink=lambda s: None )
    summary = job._poll_once()                                       # empty fleet → zero counters
    assert summary[ "manager_stale_pokes" ] == 0 and summary[ "fleet_dark" ] == 0
    assert log.of( "arbiter_poll_activity" ) == [ ]
    # force a counter: a stale MANAGER in the fleet via a bridge + manifest role
    job2 = _job( _GW(), log=( log2 := _Log() ), events_dir=str( tmp_path ),
                 bridge_discovery_fn=lambda: { "m1-full-uuid": "Tiberius" },
                 bridge_mtime_fn=lambda sid: ( NOW - datetime.timedelta( seconds=3000 ) ).timestamp(),
                 list_managers_fn=lambda: { "m1-full-uuid" },
                 resolve_manager_fn=lambda sid, declared_manager=None: {
                     "manager_persona": None, "source": "unresolved" },
                 clock=_FixedClock( NOW ),
                 render_sink=lambda s: None, snapshot_sink=lambda s: None )
    summary2 = job2._poll_once()
    assert summary2[ "manager_stale_pokes" ] == 1
    assert len( log2.of( "arbiter_poll_activity" ) ) == 1
    assert log2.of( "arbiter_poll_activity" )[ 0 ][ "manager_stale_pokes" ] == 1


class _FixedClock:
    """now_iso pinned; monotonic/sleep inert (poll loop not exercised)."""
    def __init__( self, t ): self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, s ): return None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
