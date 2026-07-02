#!/usr/bin/env python3
"""
ff91cff4 — Arbiter mis-routes a stuck/dead MANAGER's escalation to a PEER manager.

Root cause B (the misroute): when the SUBJECT of a stuck/dead escalation is itself
a declared MANAGER, the case-7 manager-tap ("owning manager") and the case-13
auto-poke reap-recommendation ("Rick + all managers") route the nudge to a PEER
manager (a manager can't own itself → the OTHER declared manager) — the observed
"arbiter keeps tapping Mr. Radio about Tiberius". Managers answer to RICK, not to
each other: a manager-subject escalation must be RICK-ONLY (new case 20 →
TIER_RICK_ONLY), excluding BOTH the subject manager AND peer managers.

RED-first: the two behavior tests below FAIL before the fix (the reap-rec fans to
the peer manager; the tap DMs the peer manager) and pass after. Regression pins
assert the WORKER-subject paths are byte-identical (no behavior change).

Design: src/rnd/v0.1.9/2026.06.30-arbiter-stuck-manager-peer-misroute-bug.md
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

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


NOW = datetime.datetime( 2026, 6, 30, 21, 0, 0, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( gw=None, notify=None, **overrides ):
    cfg = dict(
        commons           = gw or _GW(),
        poll_seconds      = 5,
        manager_recipient = "DeclaredMgr",
        notify_fn         = notify or ( lambda *a, **k: None ),
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _live_stuck( sid="s1", persona="Stuckie" ):
    return { sid: { "session_id": sid, "persona": persona, "state": "stuck",
                    "stuck": True, "holding_on": "none", "alive": True } }


def _reap_dms( gw ):
    return [ s for s in gw.sent if "REAP-RECOMMENDATION" in s[ 1 ] ]


# ── Fix B, site 1: _auto_poke reap-recommendation (case 13 → 20 for a manager) ──

def test_stuck_manager_reap_rec_routes_rick_only():
    """RED→GREEN: a stuck LIVE session whose persona is a DECLARED MANAGER escalates
    its reap-recommendation to RICK ONLY — never fanned to the peer manager."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ],
                poke_stall_threshold_seconds=0, poke_max_per_episode=1 )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    job._auto_poke( fleet, NOW, active_managers=[ "Mr. Radio" ] )                          # poke 1
    job._auto_poke( fleet, NOW + datetime.timedelta( seconds=60 ), active_managers=[ "Mr. Radio" ] )  # escalate
    reap = [ m for m in escal if "REAP-RECOMMENDATION" in m ]
    assert len( reap ) == 1                                    # Rick advised (notify)
    assert _reap_dms( gw ) == [ ]                              # RED before fix: [("Mr. Radio", ...)]


def test_stuck_worker_reap_rec_still_fans_to_managers():
    """REGRESSION PIN: a WORKER subject's reap-rec is unchanged — Rick + all active
    managers (byte-identical to the pre-fix TIER_RICK_AND_MANAGERS fan-out)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ],
                poke_stall_threshold_seconds=0, poke_max_per_episode=1 )
    fleet = _live_stuck( sid="rio", persona="Rio" )            # a worker, not a declared manager
    job._auto_poke( fleet, NOW, active_managers=[ "Mr. Radio" ] )
    job._auto_poke( fleet, NOW + datetime.timedelta( seconds=60 ), active_managers=[ "Mr. Radio" ] )
    assert [ s[ 0 ] for s in _reap_dms( gw ) ] == [ "Mr. Radio" ]
    assert len( [ m for m in escal if "REAP-RECOMMENDATION" in m ] ) == 1


# ── Fix B, site 2: _tap_managers manager-tap (case 7 → 20 for a manager) ───────

def test_stuck_manager_tap_routes_rick_only_not_peer():
    """RED→GREEN: a stuck MANAGER subject is NOT grouped under a peer/owning manager
    for a case-7 tap — it escalates Rick-only, so no manager DM is emitted."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    graph = { "edges": { }, "cycles": [ ] }
    job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ "Mr. Radio" ] )
    assert gw.sent == [ ]                                      # RED before fix: [("Mr. Radio", tap_body)]
    assert any( "Tiberius" in m for m in escal )              # Rick advised about the stuck manager


def test_stuck_worker_tap_still_dms_owning_manager():
    """REGRESSION PIN: a WORKER subject's tap still DMs its resolved owning manager
    (case-7 TIER_OWNING_MANAGER) — no behavior change."""
    gw = _GW()
    job = _job( gw, declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet = _live_stuck( sid="rio", persona="Rio" )           # a worker
    graph = { "edges": { }, "cycles": [ ] }
    fired = job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ "Mr. Radio" ] )
    assert fired == 1
    assert [ s[ 0 ] for s in gw.sent ] == [ "Mr. Radio" ]


def test_mixed_fleet_partitions_manager_subject_from_worker_group():
    """A poll with BOTH a stuck worker (→ owning-manager DM) and a stuck manager
    (→ Rick-only) routes each correctly and independently in one call."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet = { }
    fleet.update( _live_stuck( sid="rio", persona="Rio" ) )       # worker → Mr. Radio DM
    fleet.update( _live_stuck( sid="tib", persona="Tiberius" ) )  # manager → Rick only
    graph = { "edges": { }, "cycles": [ ] }
    job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ "Mr. Radio" ] )
    # the worker tap DMs Mr. Radio; NO tap DM names the stuck MANAGER Tiberius
    assert [ s[ 0 ] for s in gw.sent ] == [ "Mr. Radio" ]
    assert all( "Tiberius" not in b for _r, b in gw.sent )
    assert any( "Tiberius" in m for m in escal )                  # Rick advised about Tiberius


# ── contract + predicate leaves ───────────────────────────────────────────────

def test_stuck_manager_tap_throttled_on_unchanged_signature():
    """The Rick-only manager-subject advisory is throttled: a second poll over the
    SAME stuck manager (unchanged signature) does NOT re-fire — at most one advisory
    per unchanged stuck-episode (anti-storm, mirroring the crew-tap _should_tap)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ] )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    graph = { "edges": { }, "cycles": [ ] }
    assert job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ ] ) == 1
    assert job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ ] ) == 0  # throttled
    assert len( [ m for m in escal if "appears STUCK/DEAD" in m ] ) == 1


# ── de3c5b87 + 33949e83 ROOT (12:18 ground truth): 'stuck-mgr:' prefix pollution ──
#
# The 12:18 diagnostic captured fed_label='stuck-mgr:Tiberius', label_is_canonical=
# FALSE, owed_read_ok=TRUE, store_row_count=0, owed_class=unknown. ROOT: the
# stuck-manager advisory throttled itself on a 'stuck-mgr:<persona>' key stored in
# _last_tap_at — but that dict feeds eval_personas + the owed-read + _check_manager_acks
# as CLEAN manager personas. canonical('stuck-mgr:Tiberius')='stuckmgrtiberius' ≠ store
# owner 'tiberius' → 0-row read → UNKNOWN (first poll → MANAGER-DOWN) / DONE (later
# polls, once the owed-read returns the prefixed key with an empty list → MANAGER-DONE).
# ONE root, BOTH the 33949e83 false-DOWN and de3c5b87 false-DONE storms. Fix-at-source:
# the throttle lives in DEDICATED state so _last_tap_at stays pure clean personas.

def test_stuck_manager_throttle_key_does_not_pollute_last_tap_at():
    """ROOT GUARD: after a stuck-manager tap, _last_tap_at carries NO 'stuck-mgr:'
    key — the throttle is isolated in dedicated state, so eval_personas + the owed
    read + _check_manager_acks only ever see clean manager personas."""
    job = _job( declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    graph = { "edges": { }, "cycles": [ ] }
    assert job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ "Mr. Radio" ] ) == 1
    assert all( not str( k ).startswith( "stuck-mgr:" ) for k in job._last_tap_at )
    assert job._last_tap_at == { }                             # a manager subject makes NO clean crew-tap either
    # the dedicated throttle DID record the tap (so the anti-storm still holds)
    assert any( str( k ).startswith( "stuck-mgr:" ) for k in job._last_stuck_tap_at )


def test_stuck_manager_tap_does_not_false_fire_manager_down():
    """END-TO-END: a stuck-manager tap must not later manufacture a MANAGER-DOWN on
    the prefixed key. Past the ack window, _check_manager_acks emits ZERO downs — the
    polluted 'stuck-mgr:Tiberius' key is gone from _last_tap_at (RED before fix: 1)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                declared_managers=[ "Tiberius", "Mr. Radio" ],
                resolve_manager_fn=lambda sid, declared_manager=None: { "manager_persona": "Mr. Radio" } )
    fleet = _live_stuck( sid="tib", persona="Tiberius" )
    graph = { "edges": { }, "cycles": [ ] }
    job._tap_managers( fleet, graph, roster=[ ], now=NOW, active_managers=[ "Mr. Radio" ] )
    later = NOW + datetime.timedelta( seconds=700 )           # past the 600s ack window
    down  = job._check_manager_acks( later, [ ], fleet, [ "Mr. Radio" ], owed_class={ } )
    assert down == 0
    assert not any( "MANAGER-DOWN" in m for m in escal )


def test_format_stuck_manager_advisory_persona_then_session_id():
    """Leaf coverage of the advisory body: persona preferred, session_id fallback,
    and the F1 one-source-of-truth pin — the opening clause is derived from the
    shared ARBITER_POKE_SENTINEL (b33c8e96), not a drift-prone literal."""
    from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import ARBITER_POKE_SENTINEL
    job = _job( declared_managers=[ "Tiberius" ] )
    named = job._format_stuck_manager_advisory( { "persona": "Tiberius", "session_id": "s" }, 4 )
    assert named.startswith( ARBITER_POKE_SENTINEL )
    assert "Tiberius" in named and "MANAGER" in named and "I do not reap" in named and "4 free" in named
    fallback = job._format_stuck_manager_advisory( { "persona": None, "session_id": "sid-x" }, 0 )
    assert "sid-x" in fallback


def test_case_stuck_manager_rick_only_tier():
    from cosa.agents.heartbeat_arbiter.arbiter_routing import (
        tier_for, CASE_STUCK_MANAGER_RICK_ONLY, TIER_RICK_ONLY )
    assert tier_for( CASE_STUCK_MANAGER_RICK_ONLY ) == TIER_RICK_ONLY


def test_subject_is_manager_predicate_branches():
    """Leaf coverage of _subject_is_manager across every branch."""
    job = _job( declared_managers=[ "Tiberius", "Mr. Radio" ] )
    assert job._subject_is_manager( { "persona": "Tiberius" } ) is True
    assert job._subject_is_manager( { "persona": "mr radio" } ) is True    # canonical persona key
    assert job._subject_is_manager( { "persona": "Rio" } )      is False
    assert job._subject_is_manager( { "persona": None } )       is False
    assert job._subject_is_manager( { } )                       is False
    assert job._subject_is_manager( "not-a-dict" )              is False
    job_no_mgrs = _job()                                                    # no declared managers
    assert job_no_mgrs._subject_is_manager( { "persona": "Tiberius" } ) is False


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
