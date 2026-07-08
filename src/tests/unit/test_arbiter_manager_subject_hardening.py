#!/usr/bin/env python3
"""
Arbiter manager-subject hardening — completing the `ff91cff4` sweep (two gaps).

Both gaps trace to the same lineage (`ff91cff4` + `92c7ab1d`): the correct
PRINCIPLE was applied to ONE code path, leaving a sibling path uncovered.

  • Gap 1 — DETECTION (`e5e33795`). The bridge-fresh veto (`92c7ab1d`,
    `_session_bridge_fresh`) suppresses a false "stuck" flag on the `_auto_poke`
    path (arbiter_job.py:3801) but NOT the parallel stuck-manager ADVISORY path
    (`_tap_managers` → `_attention_workers` → `_format_stuck_manager_advisory`,
    ~2489). A manager working a long op (event-stale but bridge-FRESH) therefore
    false-fires a case-20 "STUCK/DEAD" advisory to Rick. Fix: apply the same
    subject-liveness veto before routing CASE_STUCK_MANAGER_RICK_ONLY.

  • Gap 2 — ROUTING (`f48f089d`). CASE_MANAGER_DONE_ADVISORY (17) routed
    TIER_RICK_AND_MANAGERS → fanned "consider reaping <manager>" to every active
    PEER manager. `ff91cff4` already ruled a manager-subject reap/replace
    escalation Rick-only (case 20); case 17 is its sibling. Fix: case 17 →
    TIER_RICK_ONLY (mirror case 20).

RED-first: the Gap-1 fresh-bridge test fires the advisory BEFORE the veto is
added (`fired == 1`) and suppresses it after (`fired == 0`); the Gap-2 behavior
test fans the reap directive to the peer manager before the tier change and goes
Rick-only after. Krishna's Phase-1 directive: Gap-1 RED MUST drive the
`_tap_managers` emit (NOT `_auto_poke`, which already vetoes @3801 → a test
through it would false-pass vacuously); `_should_tap` returns True on the
first-ever tap so the route WOULD fire absent the veto.

Design: src/rnd/v0.1.9/2026.07.08-arbiter-manager-subject-routing-hardening.md
Venue: :7999-eligible / local — pure + mocked, no server.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, CLASS_DONE
from cosa.agents.heartbeat_arbiter.arbiter_routing import (
    tier_for, CASE_MANAGER_DONE_ADVISORY, TIER_RICK_ONLY )
from lupin_mcp.persona_normalization import canonical_persona_key


NOW  = datetime.datetime( 2026, 7, 8, 21, 0, 0, tzinfo=datetime.timezone.utc )
LATE = NOW + datetime.timedelta( seconds=700 )        # past the default 600s ack window


def _bridge_key( persona ):
    # the arbiter keys bridge_mtimes by canonical_persona_key (bug 26dd3afb/92c7ab1d)
    return canonical_persona_key( persona ) or persona


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( gw=None, notify=None, log_fn=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify   or ( lambda *a, **k: None ),
        log_fn            = log_fn   or ( lambda *a, **k: None ),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _live_stuck( sid="tib", persona="Tiberius" ):
    return { sid: { "session_id": sid, "persona": persona, "state": "stuck",
                    "stuck": True, "holding_on": "none", "alive": True } }


def _advisory( escal ):
    return [ m for m in escal if "appears STUCK/DEAD" in m ]


# ══════════════════════════════════════════════════════════════════════════════
# Gap 1 — DETECTION (e5e33795): bridge-fresh veto on the _tap_managers advisory path
# ══════════════════════════════════════════════════════════════════════════════

def test_stuck_manager_advisory_vetoed_by_fresh_bridge():
    """RED→GREEN: a stuck-flagged MANAGER subject whose own session-bridge is FRESH
    (took a real turn recently) is demonstrably alive — event-stale but NOT wedged.
    The case-20 advisory is SUPPRESSED and one arbiter_stuck_bridge_veto event is
    logged (mirror of the _auto_poke veto @3801)."""
    gw, escal, logs = _GW(), [ ], [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                log_fn=lambda e, **f: logs.append( ( e, f ) ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet  = _live_stuck( sid="tib", persona="Tiberius" )
    graph  = { "edges": { }, "cycles": [ ] }
    bridge = { _bridge_key( "Tiberius" ): NOW.timestamp() - 15 }    # touched 15s ago → fresh
    fired  = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                                active_managers=[ "Mr. Radio" ], bridge_mtimes=bridge )
    assert fired == 0                                              # RED before fix: 1
    assert gw.sent == [ ]                                          # no peer DM either
    assert _advisory( escal ) == [ ]                              # RED before fix: 1 Rick advisory
    assert any( e == "arbiter_stuck_bridge_veto" for e, _f in logs )


def test_stuck_manager_advisory_not_vetoed_by_stale_bridge():
    """NOT-FRESH LEG: a stale bridge (2.5h old) is NOT ground-truth liveness → the
    veto does NOT fire → the true-positive case-20 advisory still reaches Rick
    (Rick-only — never a peer DM). No veto event is logged."""
    gw, escal, logs = _GW(), [ ], [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                log_fn=lambda e, **f: logs.append( ( e, f ) ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet  = _live_stuck( sid="tib", persona="Tiberius" )
    graph  = { "edges": { }, "cycles": [ ] }
    bridge = { _bridge_key( "Tiberius" ): NOW.timestamp() - 9000 }  # 2.5h old → stale
    fired  = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                                active_managers=[ "Mr. Radio" ], bridge_mtimes=bridge )
    assert fired == 1
    assert len( _advisory( escal ) ) == 1                         # Rick advised (true positive)
    assert gw.sent == [ ]                                         # still Rick-only, no peer DM
    assert not any( e == "arbiter_stuck_bridge_veto" for e, _f in logs )


def test_stuck_manager_advisory_bridge_none_is_inert():
    """FAIL-SAFE: bridge_mtimes None (seam unwired / read failed) → veto inert →
    today's behavior (the advisory fires). The pre-veto contract is preserved."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    graph = { "edges": { }, "cycles": [ ] }
    fired = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                               active_managers=[ "Mr. Radio" ], bridge_mtimes=None )
    assert fired == 1 and len( _advisory( escal ) ) == 1


def test_stuck_manager_advisory_absent_bridge_entry_does_not_veto():
    """FAIL-SAFE: a bridge map that has NO entry for the subject persona → no
    positive liveness evidence → no veto → the advisory fires."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet  = _live_stuck( sid="tib", persona="Tiberius" )
    graph  = { "edges": { }, "cycles": [ ] }
    bridge = { _bridge_key( "SomeoneElse" ): NOW.timestamp() - 15 }
    fired  = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                                active_managers=[ "Mr. Radio" ], bridge_mtimes=bridge )
    assert fired == 1 and len( _advisory( escal ) ) == 1


def test_stuck_manager_advisory_future_bridge_does_not_veto():
    """FAIL-SAFE (bug 097778b8): a FUTURE bridge mtime (clock skew ⇒ negative age)
    is NOT ground-truth liveness → no veto → the advisory fires (fail toward
    escalating, the safe direction)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet  = _live_stuck( sid="tib", persona="Tiberius" )
    graph  = { "edges": { }, "cycles": [ ] }
    bridge = { _bridge_key( "Tiberius" ): NOW.timestamp() + 60 }    # future → age -60
    fired  = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                                active_managers=[ "Mr. Radio" ], bridge_mtimes=bridge )
    assert fired == 1 and len( _advisory( escal ) ) == 1


def test_stuck_worker_advisory_never_vetoed_by_bridge():
    """SCOPE PIN: the bridge-veto is a MANAGER-SUBJECT guard only. A stuck WORKER
    (not a declared manager) is grouped under its owning manager (case-7 tap) and is
    NEVER touched by the veto, even with a fresh bridge."""
    gw = _GW()
    job = _job( gw, declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet  = _live_stuck( sid="rio", persona="Rio" )               # a worker
    graph  = { "edges": { }, "cycles": [ ] }
    bridge = { _bridge_key( "Rio" ): NOW.timestamp() - 15 }        # fresh, but irrelevant for a worker
    fired  = job._tap_managers( fleet, graph, roster=[ ], now=NOW,
                                active_managers=[ "Mr. Radio" ], bridge_mtimes=bridge )
    assert fired == 1 and [ s[ 0 ] for s in gw.sent ] == [ "Mr. Radio" ]


# ══════════════════════════════════════════════════════════════════════════════
# Gap 2 — ROUTING (f48f089d): CASE_MANAGER_DONE_ADVISORY (17) → Rick-only
# ══════════════════════════════════════════════════════════════════════════════

def test_case_manager_done_advisory_tier_is_rick_only():
    """f48f089d (2026-07-08): a MANAGER-DONE advisory carries an actionable
    manager-lifecycle directive ("consider reaping it") — only Rick reaps, so it is
    RICK-ONLY (mirror ff91cff4 case 20), never fanned to peer managers."""
    assert CASE_MANAGER_DONE_ADVISORY == 17
    assert tier_for( CASE_MANAGER_DONE_ADVISORY ) == TIER_RICK_ONLY


def test_manager_done_advisory_acks_path_is_rick_only_no_peer_fanout():
    """RED→GREEN (acks emitter, arbiter_job.py:3128): a DONE manager past its tap
    window emits its MANAGER-DONE advisory to RICK ONLY — the "consider reaping it"
    directive does NOT reach any active PEER manager."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    job._last_tap_at[ "Tiberius" ] = NOW
    down = job._check_manager_acks( LATE, [ ], None, [ "Mr. Radio" ],
                                    owed_class={ "Tiberius": CLASS_DONE } )
    assert down == 0
    done = [ m for m in escal if "MANAGER-DONE" in m and "reaping" in m.lower() ]
    assert len( done ) == 1                                       # Rick advised exactly once
    assert gw.sent == [ ]                                         # RED before fix: [("Mr. Radio", <reap body>)]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
