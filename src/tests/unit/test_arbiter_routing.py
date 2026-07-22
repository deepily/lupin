#!/usr/bin/env python3
"""
2b-2 receipts — recipient routing (Part-6 table) + the active-managers-on-duty
resolver.

Three receipt families:
  (a) PARAMETRIZED 12-case routing matrix — asserts CASE_TIERS mirrors the Part-6
      table cell-for-cell (incl. the negatives: #6 DROP, #12 LOG_THEN_RICK) AND
      the _route executor emits exactly each tier's recipients.
  (b) active-managers resolver on a MIXED fleet (managers + workers + phantoms) →
      the correct manager set, PHANTOMS EXCLUDED (commons-recent but bridge-absent).
  (c) #4 blocker → DM the blocker AND cc its owning manager (both asserted); plus
      #5/#8/#9/#11 Rick+managers fanout, #10 decision cc, and the #12 streak.

Venue: :7999-eligible / local — pure + fully mocked (no server, no real I/O).
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter import arbiter_routing as R
from cosa.agents.heartbeat_arbiter.arbiter_routing import (
    CASE_TIERS, tier_for, TIER_RICK_ONLY, TIER_RICK_AND_MANAGERS,
    TIER_OWNING_MANAGER, TIER_BLOCKER_AND_MANAGER, TIER_DROP, TIER_LOG_THEN_RICK,
    CASE_AUTO_POKE_REAP_REC, CASE_MANAGER_STALE_ADVISORY, CASE_FLEET_DARK,
    CASE_MANAGER_AWAITING_USER, CASE_MANAGER_DONE_ADVISORY,
    CASE_USER_GATE_RESURFACE, CASE_OPERATOR_GATE, CASE_STUCK_MANAGER_RICK_ONLY,
)
from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob
from cosa.agents.heartbeat_arbiter import manager_resolver as MR
from cosa.agents.heartbeat_arbiter.manager_resolver import (
    list_manager_session_ids, resolve_active_managers,
)
from lupin_mcp.session_spawner import _manifest_path


NOW = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )

# Item B (2026-06-24): every outreach message is prefixed with "[YYYY.MM.DD at
# HH:MM:SS] ". These routing receipts assert WHO receives WHAT (routing), not the
# stamp itself (covered by the dedicated Item-B tests), so they strip the prefix.
import re as _re
_STAMP_RE = _re.compile( r"^\[\d{4}\.\d{2}\.\d{2} at \d{2}:\d{2}:\d{2}\] " )

def _unstamp( s ):
    return _STAMP_RE.sub( "", s )

def _unstamp_sent( sent ):
    return [ ( r, _unstamp( b ) ) for r, b in sent ]

def _unstamp_notes( notes ):
    return [ _unstamp( n ) for n in notes ]


class _GW:
    """Captures send_to + post; who/read inert."""
    def __init__( self ):
        self.sent, self.posts = [ ], [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
    def post( self, t, b ): self.posts.append( ( t, b ) )
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


# ════════════════════════════════════════════════════════════════════════════
# (a) the Part-6 table — CASE_TIERS mirrors the ratified routing cell-for-cell
# ════════════════════════════════════════════════════════════════════════════

# The Part-6 table, transcribed independently of the source (the receipt: the two
# must agree). case → (tier, short description).
PART6_TABLE = {
    1  : ( TIER_RICK_ONLY,            "container enter-unhealthy → Rick only" ),
    2  : ( TIER_RICK_ONLY,            "container flapping → Rick only" ),
    3  : ( TIER_RICK_ONLY,            "health-watch BLIND → Rick only" ),
    4  : ( TIER_BLOCKER_AND_MANAGER,  "blocker → DM blocker + cc manager" ),
    5  : ( TIER_RICK_AND_MANAGERS,    "deadlock → Rick + all managers" ),
    6  : ( TIER_DROP,                 "roster → DROP (pull-state)" ),
    7  : ( TIER_OWNING_MANAGER,       "manager tap → owning manager" ),
    8  : ( TIER_RICK_AND_MANAGERS,    "orphan worker → Rick + all managers" ),
    9  : ( TIER_RICK_AND_MANAGERS,    "manager-down → Rick + all managers" ),
    10 : ( TIER_RICK_ONLY,            "decision-needed → Rick" ),
    11 : ( TIER_RICK_AND_MANAGERS,    "whole-fleet-stall → Rick + all managers" ),
    12 : ( TIER_LOG_THEN_RICK,        "poll-error → log; Rick if persistent" ),
}


@pytest.mark.parametrize( "case", sorted( PART6_TABLE ) )
def test_case_tiers_mirror_part6_table( case ):
    """RECEIPT (a): CASE_TIERS matches the Part-6 table for every case 1..12."""
    expected_tier, _desc = PART6_TABLE[ case ]
    assert tier_for( case ) == expected_tier == CASE_TIERS[ case ]


def test_case_tiers_is_exhaustive_part6_plus_2b3_reap_rec():
    # Part-6 outputs 1..12 + the 2b-3 auto-poke reap-recommendation (case 13)
    # + the post-game cases (14 manager-stale advisory, 15 fleet-dark — 2026-06-11)
    # + the L1 store-aware advisories (16 manager-awaiting-user, 17 manager-done — 2026-06-17)
    # + the 6929f4ac user-gate resurface (18 — 2026-06-22)
    # + the A2/A3 operator-gate urgency routing (19 — fcb5dbc0)
    # + the ff91cff4 stuck/dead-MANAGER Rick-only case (20 — 2026-06-30)
    assert set( CASE_TIERS ) == set( range( 1, 21 ) )


def test_stuck_manager_subject_routes_rick_only():
    """ff91cff4 (2026-06-30): a stuck/dead MANAGER subject escalates to RICK ONLY —
    a manager can't own itself, so routing it to a peer/owning manager was the
    Mr.-Radio-tapped-about-Tiberius misroute. Mirrors the human-domain Rick-only
    cases (1-3/10/15/18/19)."""
    assert CASE_STUCK_MANAGER_RICK_ONLY == 20
    assert tier_for( CASE_STUCK_MANAGER_RICK_ONLY ) == TIER_RICK_ONLY


def test_user_gate_resurface_routes_rick_only():
    """6929f4ac (2026-06-22): a dark session's aged, unanswered user-gate is
    surfaced to RICK ONLY — a direct user-gate is the human's to answer (mirrors
    #10 decision-needed); a dark session has no manager fan-out value."""
    assert CASE_USER_GATE_RESURFACE == 18
    assert tier_for( CASE_USER_GATE_RESURFACE ) == TIER_RICK_ONLY


def test_operator_gate_routes_rick_only():
    """A2/A3 (fcb5dbc0): operator-gate urgency routing surfaces to RICK ONLY — an
    operator gate is the human/operator's to answer (mirrors #18/#10); urgent
    interrupts, normal digests, low is pull-only, all Rick-bound."""
    assert CASE_OPERATOR_GATE == 19
    assert tier_for( CASE_OPERATOR_GATE ) == TIER_RICK_ONLY


def test_l1_store_aware_advisory_cases_route_per_design():
    """L1 (2026-06-17) + f48f089d (2026-07-08): BOTH store-aware manager-subject
    advisories are RICK-ONLY. An AWAITING-USER manager is alive and still OWNS its
    crew — only Rick unblocks it, so a peer manager has zero action (unlike the
    case-14 orphaned-crew adopt path). The MANAGER-DONE advisory's "consider reaping
    it" directive is likewise a manager-lifecycle action only Rick actuates. Both
    mirror ff91cff4 case 20 (stuck/dead MANAGER subject → Rick only)."""
    assert CASE_MANAGER_AWAITING_USER == 16 and CASE_MANAGER_DONE_ADVISORY == 17
    assert tier_for( CASE_MANAGER_AWAITING_USER ) == TIER_RICK_ONLY
    assert tier_for( CASE_MANAGER_DONE_ADVISORY ) == TIER_RICK_ONLY


def test_auto_poke_reap_rec_routes_rick_and_managers():
    """2b-3: the auto-poke reap-RECOMMENDATION routes to Rick + all active
    managers (same tier as the fleet crises) — recommendation, never a reap."""
    assert CASE_AUTO_POKE_REAP_REC == 13
    assert tier_for( CASE_AUTO_POKE_REAP_REC ) == TIER_RICK_AND_MANAGERS


def test_postgame_cases_route_per_design():
    """Post-game (2026-06-11) + mini-plan 04 (2026-07-21): the manager-stale
    advisory is RICK-ONLY. The 2026-06-11 peer fan-out ("the dark manager's crew
    is leaderless-in-waiting") was REVERSED by Rick's ruling: case 14 fires on
    inferred SILENCE, not measured ABSENCE — four false-positive suppressors exist
    precisely because "silent past threshold" kept meaning "alive and working" — so
    the subject's crew is OWNED and ALIVE, the one thing a peer manager has zero
    action on (completing ff91cff4 case 20 / f48f089d cases 16-17). The fleet-dark
    advisory is Rick-ONLY too (no managers remain by definition)."""
    assert CASE_MANAGER_STALE_ADVISORY == 14 and CASE_FLEET_DARK == 15
    assert tier_for( CASE_MANAGER_STALE_ADVISORY ) == TIER_RICK_ONLY
    assert tier_for( CASE_FLEET_DARK )             == TIER_RICK_ONLY


def test_case14_flip_did_not_widen_the_fleet_crisis_tier():
    """AC-4 (mini-plan 04): the case-14 flip must not quietly drag its neighbours
    with it. Cases 5 (deadlock), 8 (orphan WORKER), 9 (manager-down + HOLD),
    11 (fleet-stall) and 13 (auto-poke reap-rec) ALL stay on Rick + managers.
    Case 9 is the load-bearing one: it is case 14's near-twin in wording and was
    put to Rick as a direct yes/no on 2026-07-21 — answer NO, do not flip. Its
    basis is the DETECTOR, not the rationale: case 9 fires on a manager that is
    DOWN and holding (measured absence, a genuine orphan), case 14 on 45m of
    silence from a manager still in the roster (inferred, and wrong often enough
    that four guards exist). Flipping 9 needs NEW evidence that its subject is
    inferred too — not a re-reading of the two rationales."""
    for case in ( 5, 8, 9, 11, CASE_AUTO_POKE_REAP_REC ):
        assert tier_for( case ) == TIER_RICK_AND_MANAGERS, f"case {case} must NOT have flipped"


def test_tier_for_unknown_case_raises():
    with pytest.raises( KeyError ):
        tier_for( 99 )


def test_arbiter_routing_quick_smoke():
    assert R.quick_smoke_test() is True


# ════════════════════════════════════════════════════════════════════════════
# (a) the _route executor — each tier emits exactly its recipients
# ════════════════════════════════════════════════════════════════════════════

def test_route_rick_only_notifies_no_managers():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 1, "infra alert", active_managers=[ "M1", "M2" ] )   # RICK_ONLY ignores managers
    assert _unstamp_notes( notes ) == [ "infra alert" ] and gw.sent == [ ]


def test_route_rick_and_managers_fans_out():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 5, "deadlock!", active_managers=[ "M1", "M2" ] )
    assert _unstamp_notes( notes ) == [ "deadlock!" ]                # Rick (notify)
    assert _unstamp_sent( gw.sent ) == [ ( "M1", "deadlock!" ), ( "M2", "deadlock!" ) ]   # + each manager


def test_route_rick_and_managers_empty_set_is_rick_only():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 11, "stall!", active_managers=[ ] )                  # no managers on duty
    assert _unstamp_notes( notes ) == [ "stall!" ] and gw.sent == [ ]   # degrades to Rick-only


# ── bug b9911943: exclude_persona drops the named subject from its OWN fan-out ──

def test_route_exclude_persona_drops_named_subject():
    """bug b9911943: a manager advisory ABOUT a manager (cases 14/16/17) must NOT
    fan out to that subject. exclude_persona removes it from the
    TIER_RICK_AND_MANAGERS active-managers set; Rick + every PEER manager keep it."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 5, "deadlock!", active_managers=[ "M1", "M2" ], exclude_persona="M1" )
    assert _unstamp_notes( notes ) == [ "deadlock!" ]                # Rick unaffected
    assert _unstamp_sent( gw.sent ) == [ ( "M2", "deadlock!" ) ]     # M1 dropped, M2 kept


def test_route_exclude_persona_matches_by_canonical_key():
    """The subject match is by canonical persona key — case + punctuation tolerant:
    a display 'Mr. Radio' in the fan-out is dropped by exclude_persona='mr radio'."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 5, "deadlock!", active_managers=[ "Mr. Radio", "OtherMgr" ],
                exclude_persona="mr radio" )
    assert _unstamp_sent( gw.sent ) == [ ( "OtherMgr", "deadlock!" ) ]   # punct/case-variant dropped


def test_route_exclude_persona_falsy_excludes_nothing():
    """Default (None) AND any falsy-key exclude_persona leave the fan-out
    byte-identical — every pre-existing caller is unaffected (the b9911943 guard)."""
    # default None → no filter
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 5, "x", active_managers=[ "M1", "M2" ] )
    assert _unstamp_sent( gw.sent ) == [ ( "M1", "x" ), ( "M2", "x" ) ]
    # explicit empty string (falsy) → excluded_key None → no filter
    gw2, notes2 = _GW(), [ ]
    job2 = _job( gw2, notify=notes2.append )
    job2._route( 5, "x", active_managers=[ "M1", "M2" ], exclude_persona="" )
    assert _unstamp_sent( gw2.sent ) == [ ( "M1", "x" ), ( "M2", "x" ) ]
    # punctuation-only subject → canonical key "" → the `excluded_key and` guard
    # short-circuits → no filter (never accidentally drops a real manager)
    gw3, notes3 = _GW(), [ ]
    job3 = _job( gw3, notify=notes3.append )
    job3._route( 5, "x", active_managers=[ "M1", "M2" ], exclude_persona="!!!" )
    assert _unstamp_sent( gw3.sent ) == [ ( "M1", "x" ), ( "M2", "x" ) ]


def test_route_owning_manager_dm_only():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 7, "tap body", owning_manager="MgrX" )
    assert _unstamp_sent( gw.sent ) == [ ( "MgrX", "tap body" ) ] and notes == [ ]   # no Rick on the per-worker nudge


def test_route_owning_manager_none_is_noop():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 7, "tap body", owning_manager=None )
    assert gw.sent == [ ] and notes == [ ]


def test_route_blocker_and_manager_dms_both():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 4, "ping", blocker="Blk", owning_manager="MgrB", cc_message="cc" )
    assert _unstamp_sent( gw.sent ) == [ ( "Blk", "ping" ), ( "MgrB", "cc" ) ] and notes == [ ]


def test_route_blocker_only_when_no_manager():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 4, "ping", blocker="Blk", owning_manager=None, cc_message=None )
    assert _unstamp_sent( gw.sent ) == [ ( "Blk", "ping" ) ]


def test_route_blocker_and_manager_cc_only_when_no_blocker():
    """Edge: BLOCKER_AND_MANAGER with no blocker → only the manager cc fires."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 4, "ping", blocker=None, owning_manager="MgrB", cc_message="cc" )
    assert _unstamp_sent( gw.sent ) == [ ( "MgrB", "cc" ) ] and notes == [ ]


def test_route_drop_emits_nothing():
    """RECEIPT (a) negative: #6 DROP → no push at all (pull-state)."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append )
    job._route( 6, "roster" )
    assert gw.sent == [ ] and gw.posts == [ ] and notes == [ ]


# ════════════════════════════════════════════════════════════════════════════
# (c) per-detector routing — the cases drive _route end-to-end
# ════════════════════════════════════════════════════════════════════════════

def test_deadlock_routes_rick_and_managers():
    """#5: deadlock → Rick (notify) + each active manager (send_to)."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append, deadlock_dwell_seconds=0 )
    store_edges = { "a": { "b" }, "b": { "a" } }                   # corroborates A↔B (canonical lower)
    job._escalate_deadlocks( [ [ "A", "B" ] ], store_edges, NOW, active_managers=[ "M1" ] )
    assert notes and "DEADLOCK" in notes[ 0 ]
    assert gw.sent == [ ( "M1", notes[ 0 ] ) ]


def test_fleet_stall_routes_rick_and_managers():
    """#11: stall → Rick + all active managers (extends the 2b-1 calibration)."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append, fleet_stall_window_seconds=600 )
    live = { "s1": { "session_id": "s1", "persona": "s1", "state": "stuck",
                     "stuck": True, "holding_on": "none", "alive": True } }
    assert job._check_fleet_stall( live, NOW, active_managers=[ "M1", "M2" ] ) == 0   # baseline
    assert job._check_fleet_stall( live, NOW + datetime.timedelta( seconds=700 ),
                                   active_managers=[ "M1", "M2" ] ) == 1
    assert "WHOLE-FLEET-STALL" in notes[ 0 ]
    assert gw.sent == [ ( "M1", notes[ 0 ] ), ( "M2", notes[ 0 ] ) ]


def test_manager_down_routes_rick_and_managers():
    """#9: manager-down → Rick + all active managers."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append, manager_ack_window_seconds=600 )
    job._last_tap_at = { "GoneMgr": NOW }                          # tapped, never acked
    down = job._check_manager_acks( NOW + datetime.timedelta( seconds=700 ),
                                    who_rows=[ ], active_managers=[ "M1" ] )
    assert down == 1 and "MANAGER-DOWN" in notes[ 0 ]
    assert gw.sent == [ ( "M1", notes[ 0 ] ) ]


def test_orphan_worker_routes_rick_and_managers():
    """#8: a stuck worker whose manager does NOT resolve → Rick + all managers."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append,
                resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": None, "source": "unresolved" } )
    fleet_view = { "s1": { "session_id": "s1", "persona": "Orphan", "stuck": True,
                           "state": "stuck", "holding_on": "none", "alive": True } }
    graph = { "edges": { }, "cycles": [ ] }
    fired = job._tap_managers( fleet_view, graph, roster=[ ], now=NOW,
                               active_managers=[ "M1", "M2" ] )
    assert fired == 0                                              # no resolved manager tapped
    assert notes and "Unresolved manager" in notes[ 0 ]
    assert gw.sent == [ ( "M1", notes[ 0 ] ), ( "M2", notes[ 0 ] ) ]


def test_manager_tap_routes_owning_manager_only():
    """#7: a stuck worker WITH a resolved manager → owning-manager DM, no Rick."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=notes.append,
                resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrX", "source": "lineage" } )
    fleet_view = { "s1": { "session_id": "s1", "persona": "Worker", "stuck": True,
                           "state": "stuck", "holding_on": "none", "alive": True } }
    graph = { "edges": { }, "cycles": [ ] }
    fired = job._tap_managers( fleet_view, graph, roster=[ ], now=NOW, active_managers=[ "M1" ] )
    assert fired == 1 and gw.sent and gw.sent[ -1 ][ 0 ] == "MgrX"
    assert notes == [ ]                                            # #7 does NOT escalate to Rick


def test_blocker_ping_dms_blocker_and_ccs_manager():
    """RECEIPT (c) #4: the ping DMs the BLOCKER and cc's the blocker's owning manager."""
    gw = _GW()
    job = _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrB", "source": "lineage" } if sid == "bob-sid" else {
                    "manager_persona": None, "source": "unresolved" } )
    # edge Alice→Bob: Alice is BLOCKED waiting on Bob (the blocker); Bob's sid resolves to MgrB
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid={ "Bob": "bob-sid" } )
    assert gw.sent[ 0 ][ 0 ] == "Bob" and "blocking worker Alice" in gw.sent[ 0 ][ 1 ]
    assert gw.sent[ 1 ][ 0 ] == "MgrB" and "blocking worker Alice" in gw.sent[ 1 ][ 1 ]   # cc
    assert "chase if they stay silent" in gw.sent[ 1 ][ 1 ]
    # e8eee4c4 (family-close): the blocker-cc opening clause derives from the shared
    # ARBITER_POKE_SENTINEL (b33c8e96 one-source-of-truth), not a drift-prone literal.
    from lupin_cli.claude_code.hooks.lib.heartbeat_work_owed import ARBITER_POKE_SENTINEL
    assert ARBITER_POKE_SENTINEL in gw.sent[ 1 ][ 1 ]   # sentinel-derived clause (after the _stamp timestamp)


def test_blocker_ping_no_cc_when_manager_unresolved():
    """#4 degrade: blocker pinged, NO cc when the blocker has no known session/manager."""
    gw = _GW()
    job = _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": None, "source": "unresolved" } )
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid={ } )    # no sid for Bob
    assert len( gw.sent ) == 1 and gw.sent[ 0 ][ 0 ] == "Bob"


def test_blocker_cc_skipped_when_manager_is_the_blocker():
    """#4 guard: never cc a 'manager' that resolves to the blocker itself."""
    gw = _GW()
    job = _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "Bob", "source": "lineage" } )   # resolves to the blocker
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid={ "Bob": "bob-sid" } )
    assert len( gw.sent ) == 1 and gw.sent[ 0 ][ 0 ] == "Bob"        # no self-cc


def test_blocker_cc_resolver_exception_degrades_to_no_cc():
    gw = _GW()
    def _boom( sid, declared_manager=None ): raise RuntimeError( "resolver down" )
    job = _job( gw, resolve_manager_fn=_boom )
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid={ "Bob": "bob-sid" } )
    assert len( gw.sent ) == 1 and gw.sent[ 0 ][ 0 ] == "Bob"        # ping fired, no cc, no raise


# ── bug ce13b134: blocker-cc idempotency (the manager cc must not re-fire per ping) ──

def _cc_job( gw, **overrides ):
    """A #4 job whose blocker 'bob-sid' resolves to owning manager MgrB (else none)."""
    return _job( gw, resolve_manager_fn=lambda sid, declared_manager=None: {
                     "manager_persona": "MgrB", "source": "lineage" } if sid == "bob-sid" else {
                     "manager_persona": None, "source": "unresolved" }, **overrides )


def test_blocker_cc_deduped_within_cooldown_window():
    """bug ce13b134: the blocker PING re-fires on its escalating backoff (60/300/…
    — a silent blocker SHOULD keep being nudged), but the owning-manager cc is
    deduped to at most once per cooldown window while the block persists. Kills the
    3-identical-'X is blocking worker Y'-DMs-in-6-min flood (each a fresh thread)."""
    gw  = _GW()
    job = _cc_job( gw )                                              # default cooldown = 2700s window
    p2s = { "Bob": "bob-sid" }
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid=p2s )                                    # t0:   ping + cc
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=60  ), persona_to_sid=p2s )  # +60:  ping, cc suppressed
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=360 ), persona_to_sid=p2s )  # +300: ping, cc suppressed
    blocker_dms = [ s for s in gw.sent if s[ 0 ] == "Bob" ]
    mgr_ccs     = [ s for s in gw.sent if s[ 0 ] == "MgrB" ]
    assert len( blocker_dms ) == 3          # the silent blocker keeps getting nudged (backoff untouched)
    assert len( mgr_ccs )     == 1          # the manager is cc'd ONCE, not per-ping


def test_blocker_cc_refires_after_cooldown_expires():
    """A genuinely-persistent block eventually re-cc's the manager once the cooldown
    lapses (idempotency window, not permanent suppression)."""
    gw  = _GW()
    job = _cc_job( gw, manager_advisory_cooldown_seconds=100 )       # short window for the test
    p2s = { "Bob": "bob-sid" }
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid=p2s )                                    # t0:   cc (stamp until t0+100)
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=60  ), persona_to_sid=p2s )  # +60:  cc within 100 → suppressed
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=360 ), persona_to_sid=p2s )  # +300: cc past 100 → re-cc
    mgr_ccs = [ s for s in gw.sent if s[ 0 ] == "MgrB" ]
    assert len( mgr_ccs ) == 2


def test_blocker_cc_reannounces_when_blocked_item_changes():
    """Mr. Radio's positive case (ce13b134): two SEQUENTIAL blocks with the SAME
    (blocker, blocked_worker, recipient) but a DIFFERENT blocked item each announce
    exactly once — the item id is in the idempotency key, so instance 2 (a new item)
    is NOT suppressed as a dup of instance 1. A persona-only key would over-suppress
    it (RED against that)."""
    gw  = _GW()
    job = _cc_job( gw )
    p2s    = { "Bob": "bob-sid" }
    items1 = { ( "alice", "bob" ): frozenset( { "item-99399723" } ) }   # instance 1's blocked item
    items2 = { ( "alice", "bob" ): frozenset( { "item-ca8d6a19" } ) }   # instance 2's DIFFERENT blocked item
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid=p2s, edge_items=items1 )                                   # cc (item-1)
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=60  ), persona_to_sid=p2s, edge_items=items1 )  # echo → suppressed
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=360 ), persona_to_sid=p2s, edge_items=items2 )  # NEW item → cc again
    mgr_ccs = [ s for s in gw.sent if s[ 0 ] == "MgrB" ]
    assert len( mgr_ccs ) == 2              # each distinct blocked item announces exactly once


def test_blocker_cc_cooldown_cleared_on_edge_resume():
    """When the block resolves, the blocker-cc cooldown is dropped so a NEW block on
    the same edge re-cc's the manager immediately (mirrors the ping-ledger
    clear-on-resume)."""
    gw  = _GW()
    job = _cc_job( gw )
    p2s = { "Bob": "bob-sid" }
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid=p2s )                                    # cc fired + cooldown stamped
    assert ( "blocker-cc", "bob|alice|" ) in job._advisory_cooldown_until                            # canonical, empty item-sig
    job._auto_ping( { }, NOW + datetime.timedelta( seconds=10 ), persona_to_sid=p2s )                # edge gone → clear-on-resume
    assert ( "blocker-cc", "bob|alice|" ) not in job._advisory_cooldown_until
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=20 ), persona_to_sid=p2s )  # new block → cc again at once
    mgr_ccs = [ s for s in gw.sent if s[ 0 ] == "MgrB" ]
    assert len( mgr_ccs ) == 2


def test_blocker_cc_cooldown_disabled_ccs_every_ping():
    """manager_advisory_cooldown_seconds=0 is a deliberate opt-out → the legacy
    per-ping cc behaviour is restored (every blocker ping re-cc's), same disable
    semantics as the case-16/17 advisory cooldown."""
    gw  = _GW()
    job = _cc_job( gw, manager_advisory_cooldown_seconds=0 )
    p2s = { "Bob": "bob-sid" }
    job._auto_ping( { "Alice": "Bob" }, NOW, persona_to_sid=p2s )
    job._auto_ping( { "Alice": "Bob" }, NOW + datetime.timedelta( seconds=60 ), persona_to_sid=p2s )
    mgr_ccs = [ s for s in gw.sent if s[ 0 ] == "MgrB" ]
    assert len( mgr_ccs ) == 2              # gate disabled → cc rides every ping


def test_decision_cc_owning_manager_when_sender_resolves():
    """#10: decision-needed → Rick (notify) + cc owning manager when the sender resolves."""
    gw, notes = _GW(), [ ]
    entries = [ { "ts": "t5", "body": "scope?", "persona_name": "Wkr", "sender_session_id": "wkr-sid" } ]
    class _RGW( _GW ):
        def read( self, topic, since=None, limit=50 ): return list( entries )
    gw = _RGW()
    job = _job( gw, notify=notes.append,
                resolve_manager_fn=lambda sid, declared_manager=None: {
                    "manager_persona": "MgrD", "source": "lineage" } )
    job._decision_since = "t1"
    assert job._check_decision_needed( NOW ) == 1
    assert "DECISION-NEEDED" in notes[ 0 ]
    assert gw.sent and gw.sent[ -1 ][ 0 ] == "MgrD" and "decision-needed" in gw.sent[ -1 ][ 1 ]


def test_decision_no_cc_when_no_sender_session():
    gw, notes = _GW(), [ ]
    entries = [ { "ts": "t5", "body": "scope?", "persona_name": "Wkr" } ]   # no sender_session_id
    class _RGW( _GW ):
        def read( self, topic, since=None, limit=50 ): return list( entries )
    gw = _RGW()
    job = _job( gw, notify=notes.append )
    job._decision_since = "t1"
    assert job._check_decision_needed( NOW ) == 1
    assert gw.sent == [ ]                                          # Rick-only, no cc


def test_decision_cc_resolver_exception_degrades():
    gw, notes = _GW(), [ ]
    entries = [ { "ts": "t5", "body": "x", "sender_session_id": "s" } ]
    class _RGW( _GW ):
        def read( self, topic, since=None, limit=50 ): return list( entries )
    gw = _RGW()
    def _boom( sid, declared_manager=None ): raise RuntimeError( "down" )
    job = _job( gw, notify=notes.append, resolve_manager_fn=_boom )
    job._decision_since = "t1"
    assert job._check_decision_needed( NOW ) == 1 and gw.sent == [ ]   # Rick still notified, no cc


# ════════════════════════════════════════════════════════════════════════════
# (b) active-managers-on-duty resolver — phantom-guarded
# ════════════════════════════════════════════════════════════════════════════

def test_resolver_mixed_fleet_excludes_workers_and_phantoms():
    """RECEIPT (b) — THE killer assertion. A MIXED fleet:
       • TiberiusMgr — manager-role + LIVE bridge → INCLUDED
       • RioWorker   — LIVE bridge but NOT a manager → EXCLUDED (no role)
       • GhostMgr    — manager-role + commons-recent BUT bridge-ABSENT (reaped,
                       lingering last-post) → EXCLUDED (the phantom guard).
    """
    who_rows = [
        { "session_id": "mgr-tib", "persona_name": "TiberiusMgr" },
        { "session_id": "wkr-rio", "persona_name": "RioWorker" },
        { "session_id": "mgr-ghost", "persona_name": "GhostMgr" },   # lingering commons last-post
    ]
    bridge_sessions = { "mgr-tib": "TiberiusMgr", "wkr-rio": "RioWorker" }   # NO mgr-ghost (PID-dead)
    managers = resolve_active_managers(
        who_rows, bridge_sessions,
        list_managers = lambda sd: { "mgr-tib", "mgr-ghost" },   # both are managers by role
    )
    assert managers == [ "TiberiusMgr" ]                          # worker + PHANTOM both excluded
    assert "GhostMgr" not in managers                            # explicit phantom-exclusion guard


@pytest.mark.parametrize( "a,b,expected", [
    ( "", "x", False ), ( "x", "", False ), ( None, "x", False ),   # falsy → no match
    ( "abc", "abc", True ),                                          # exact
    ( "abc", "abc-full", True ),                                     # b extends a (b.startswith)
    ( "abc-full", "abc", True ),                                     # a extends b (a.startswith)
    ( "abc", "xyz", False ),                                         # disjoint
] )
def test_id_matches_branches( a, b, expected ):
    assert MR._id_matches( a, b ) is expected


def test_resolver_matches_heterogeneous_id_forms():
    """A manager whose commons row uses a SHORT id while its bridge/lineage uses
    the FULL uuid is still matched (prefix-tolerant _id_matches) → included."""
    managers = resolve_active_managers(
        who_rows=[ { "session_id": "mgr1234", "persona_name": "Mel" } ],   # short id
        bridge_sessions={ "mgr1234-aaaa-bbbb-uuid": "Mel" },               # full uuid
        list_managers=lambda sd: { "mgr1234-aaaa-bbbb-uuid" } )
    assert managers == [ "Mel" ]


def test_resolver_bridge_only_manager_included_without_who_row():
    """A live manager discovered via its bridge (no commons post yet) is included."""
    managers = resolve_active_managers(
        who_rows=[ ], bridge_sessions={ "mgr-a": "Ann" },
        list_managers=lambda sd: { "mgr-a" } )
    assert managers == [ "Ann" ]


def test_resolver_persona_falls_back_to_who_row_then_excluded_if_no_bridge():
    """A manager present in who_rows with a persona but NO live bridge → excluded
    (persona known, but the phantom guard requires a live bridge)."""
    managers = resolve_active_managers(
        who_rows=[ { "session_id": "mgr-x", "persona_name": "Xan" } ],
        bridge_sessions={ },                                      # no live bridge at all
        list_managers=lambda sd: { "mgr-x" } )
    assert managers == [ ]


def test_resolver_no_managers_returns_empty():
    assert resolve_active_managers( [ { "session_id": "w", "persona_name": "W" } ],
                                    { "w": "W" }, list_managers=lambda sd: set() ) == [ ]


def test_resolver_list_managers_exception_swallowed():
    def _boom( sd ): raise RuntimeError( "scan failed" )
    assert resolve_active_managers( [ ], { "m": "M" }, list_managers=_boom ) == [ ]


def test_resolver_none_inputs_safe():
    assert resolve_active_managers( None, None, list_managers=lambda sd: { "m" } ) == [ ]


def test_resolver_manager_without_persona_excluded():
    """A manager whose bridge persona is None (no DM-able name) → excluded."""
    managers = resolve_active_managers(
        who_rows=[ ], bridge_sessions={ "mgr-x": None },
        list_managers=lambda sd: { "mgr-x" } )
    assert managers == [ ]


# ── list_manager_session_ids (manifest enumeration) ─────────────────────────────

def test_list_manager_session_ids_enumerates_round_trip_manifests( tmp_path ):
    # two valid manager manifests (created via the SAME transform → round-trip)
    for mid in ( "mgr-uuid-1", "mgr-uuid-2" ):
        _manifest_path( mid, tmp_path ).write_text( "[]" )
    # a non-manifest file is ignored
    ( tmp_path / "not-a-manifest.json" ).write_text( "[]" )
    ids = list_manager_session_ids( tmp_path )
    assert ids == { "mgr-uuid-1", "mgr-uuid-2" }


def test_list_manager_session_ids_skips_non_round_tripping( tmp_path, monkeypatch ):
    """A filename whose parsed id does NOT round-trip _manifest_path is skipped
    (lossy/brittle → unresolved, never a wrong manager)."""
    _manifest_path( "good", tmp_path ).write_text( "[]" )
    # forge a manifest filename whose id would re-slug to a DIFFERENT name
    ( tmp_path / "spawned-Bad Id.json" ).write_text( "[]" )
    ids = list_manager_session_ids( tmp_path )
    assert ids == { "good" }                                      # the brittle one is dropped


def test_list_manager_session_ids_oserror_returns_empty( monkeypatch ):
    class _BadDir:
        def glob( self, pat ): raise OSError( "no dir" )
    assert list_manager_session_ids( _BadDir() ) == set()


# ── _active_managers (arbiter method) swallows resolver failure ─────────────────

def test_active_managers_method_swallows_resolver_error():
    def _boom( who, bridge ): raise RuntimeError( "resolver exploded" )
    job = _job( resolve_active_managers_fn=_boom )
    assert job._active_managers( [ ], { } ) == [ ]                # degrade to Rick-only fanout


def test_active_managers_method_delegates():
    job = _job( resolve_active_managers_fn=lambda who, bridge: [ "M1", "M2" ] )
    assert job._active_managers( [ ], { } ) == [ "M1", "M2" ]


# ── validation ──────────────────────────────────────────────────────────────────

def test_poll_error_threshold_validation():
    with pytest.raises( ValueError ):
        _job( poll_error_escalate_threshold=0 )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
