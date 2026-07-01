#!/usr/bin/env python3
"""
2b-3 receipts — the bounded, non-destructive auto-poke + reap-recommendation.

Receipts (María's 3 hardening conditions + the calibration cross-gate):
  • REDLINE — enforced structurally by test_arbiter_redline (the AST-scan stays
    green; the poke is send_to/_route, never reap/kill/replace). Re-asserted here
    that the arbiter emits a RECOMMENDATION and takes NO destructive action.
  • ANTI-STORM (FM-20) — the ≤N cap PERSISTS per stall-EPISODE: many ticks over one
    stuck session → ≤N pokes TOTAL + exactly 1 reap-recommendation → silence.
  • STALL≠QUIET — busy/working, declared-holding, idle (not stuck) AND dead (the
    2b-1 calibration gate) are NEVER poked; only LIVE+stuck.
  • CONFIG KNOBS — threshold + cap (+ enable) validated; the threshold gates the
    first poke.

Venue: :7999-eligible / local — pure + mocked, no server, no real wait.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    ArbiterConsumerJob,
    CLASS_BLOCKED_ON_USER, CLASS_DONE, CLASS_ACTIVE, CLASS_UNKNOWN,
)


NOW = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )


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


def _view( sid, *, state, stuck, alive, persona="P" ):
    return { sid: { "session_id": sid, "persona": persona, "state": state,
                    "stuck": stuck, "holding_on": "none", "alive": alive } }


def _pokes( gw ):
    # the wake-nudge body is poke-only ("you appear STUCK"); the reap-rec DM also
    # mentions "auto-poke(s)" so filter on the poke-unique phrase, not "auto-poke"
    return [ s for s in gw.sent if "you appear STUCK" in s[ 1 ] ]


# ── STALL ≠ QUIET ────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "fleet,desc", [
    ( _view( "s", state="working", stuck=False, alive=True ), "busy/working alive" ),
    ( _view( "s", state="holding", stuck=False, alive=True ), "declared-holding alive" ),
    ( _view( "s", state="idle",    stuck=False, alive=True ), "idle alive" ),
    ( _view( "s", state="stuck",   stuck=True,  alive=False ), "stuck but DEAD (calibration gate)" ),
] )
def test_stall_not_quiet_these_are_never_poked( fleet, desc ):
    """STALL≠QUIET: a live-but-not-stuck session (busy/holding/idle) AND a
    dead-but-stuck session are NEVER poked. Only LIVE+stuck qualifies.

    POST-GAME SPLIT (2026-06-11, AC7 — the deliberate calibration flip): this
    test's scope is now the STUCK-TIER for WORKER-role sessions ONLY. The
    2026-06-10 silent stall showed the (working, not-stuck, alive) shape is
    EXACTLY a dark manager's — this test used to RATIFY that silence fleet-wide.
    The zero-poke assertions below stand VERBATIM for the stuck tier (workers'
    quiet≠stall protection is untouched); the MANAGER-role companion case now
    asserts the OPPOSITE outcome via the staleness tier — see
    test_arbiter_manager_staleness.py (unit) + test_arbiter_scenarios.py (S1/S5).
    Retired-by-decision, never by drift. Design:
    src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §2.2/AC7."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )
    # drive several polls past any threshold — still no poke
    for k in range( 5 ):
        assert job._auto_poke( fleet, NOW + datetime.timedelta( seconds=k * 100 ), [ ] ) == 0
    assert _pokes( gw ) == [ ], desc


def test_live_stuck_is_poked():
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )
    fired = job._auto_poke( _live_stuck(), NOW, active_managers=[ ] )
    assert fired == 1
    assert len( _pokes( gw ) ) == 1 and _pokes( gw )[ 0 ][ 0 ] == "Stuckie"
    assert "STUCK" in _pokes( gw )[ 0 ][ 1 ] and "Non-destructive" in _pokes( gw )[ 0 ][ 1 ]


# ── THRESHOLD GATE ───────────────────────────────────────────────────────────

def test_threshold_gates_the_first_poke():
    """A session must be continuously LIVE+stuck for ≥ threshold before its FIRST
    poke — a brief stick that self-resolves is never poked."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=600 )
    fleet = _live_stuck()
    assert job._auto_poke( fleet, NOW, [ ] ) == 0                          # episode start, elapsed 0 < 600
    assert job._auto_poke( fleet, NOW + datetime.timedelta( seconds=300 ), [ ] ) == 0   # still < 600
    assert job._auto_poke( fleet, NOW + datetime.timedelta( seconds=600 ), [ ] ) == 1   # threshold met → poke
    assert len( _pokes( gw ) ) == 1


# ── ANTI-STORM (FM-20) — ≤N pokes + 1 escalation per EPISODE, no storm ────────

def test_anti_storm_cap_persists_across_ticks():
    """RECEIPT: many ticks over ONE persistently-stuck session → ≤N pokes TOTAL +
    exactly ONE reap-recommendation → silence. The cap + escalated-flag PERSIST
    per episode (never a per-tick re-poke storm)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                poke_stall_threshold_seconds=0, poke_max_per_episode=3 )
    fleet = _live_stuck()
    # 12 ticks over the SAME stuck session
    for k in range( 12 ):
        job._auto_poke( fleet, NOW + datetime.timedelta( seconds=k * 60 ), active_managers=[ "MgrA" ] )
    # exactly N=3 pokes, then exactly ONE reap-recommendation, then silence
    assert len( _pokes( gw ) ) == 3
    reap_notifies = [ m for m in escal if "REAP-RECOMMENDATION" in m ]
    assert len( reap_notifies ) == 1
    assert "I do NOT reap" in reap_notifies[ 0 ] and "NO destructive action" in reap_notifies[ 0 ]
    # the reap-recommendation also fanned out to the active manager (Rick + managers tier)
    reap_dms = [ s for s in gw.sent if "REAP-RECOMMENDATION" in s[ 1 ] ]
    assert reap_dms == [ ( "MgrA", reap_notifies[ 0 ] ) ]


def test_episode_rearm_after_recovery():
    """When a stuck session RECOVERS (leaves the pokeable set) its episode ends:
    state clears and the cap RE-ARMS for a future episode."""
    gw = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, poke_max_per_episode=2 )
    fleet_stuck = _live_stuck()
    fleet_ok    = _view( "s1", state="working", stuck=False, alive=True, persona="Stuckie" )
    # episode 1: 2 pokes then capped
    for k in range( 4 ):
        job._auto_poke( fleet_stuck, NOW + datetime.timedelta( seconds=k * 60 ), [ ] )
    assert len( _pokes( gw ) ) == 2
    assert "s1" in job._poke_stuck_since
    # recovery → episode ends → state cleared
    job._auto_poke( fleet_ok, NOW + datetime.timedelta( seconds=300 ), [ ] )
    assert "s1" not in job._poke_stuck_since and "s1" not in job._poke_escalated
    # episode 2: cap re-armed → 2 more pokes
    for k in range( 4 ):
        job._auto_poke( fleet_stuck, NOW + datetime.timedelta( seconds=600 + k * 60 ), [ ] )
    assert len( _pokes( gw ) ) == 4                                        # 2 (ep1) + 2 (ep2)


# ── ESCALATION = RECOMMENDATION; arbiter NEVER reaps ─────────────────────────

def test_reap_recommendation_is_advisory_only():
    """The escalation is a reap-RECOMMENDATION to Rick + active managers; the
    arbiter emits it and STOPS — it never executes a reap (redline)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                poke_stall_threshold_seconds=0, poke_max_per_episode=1 )
    fleet = _live_stuck()
    job._auto_poke( fleet, NOW, active_managers=[ "M1", "M2" ] )           # poke 1
    job._auto_poke( fleet, NOW + datetime.timedelta( seconds=60 ), active_managers=[ "M1", "M2" ] )  # escalate
    reap = [ m for m in escal if "REAP-RECOMMENDATION" in m ]
    assert len( reap ) == 1 and "advisory" in reap[ 0 ]
    # fanned out to BOTH active managers + Rick (notify), no destructive call anywhere
    reap_dms = [ s[ 0 ] for s in gw.sent if "REAP-RECOMMENDATION" in s[ 1 ] ]
    assert reap_dms == [ "M1", "M2" ]


# ── ENABLE FLAG (make-before-break) + CONFIG VALIDATION ───────────────────────

def test_auto_poke_disabled_is_noop():
    gw = _GW()
    job = _job( gw, auto_poke_enabled=False, poke_stall_threshold_seconds=0 )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 0 and gw.sent == [ ]


@pytest.mark.parametrize( "bad", [
    { "poke_stall_threshold_seconds": -1 },
    { "poke_max_per_episode": 0 },
] )
def test_config_validation_rejects_bad_knobs( bad ):
    with pytest.raises( ValueError ):
        _job( **bad )


# ── leaf edge cases (pokeable predicate + formatters) ─────────────────────────

def test_pokeable_skips_non_dict_and_missing_sid():
    pokeable = ArbiterConsumerJob._pokeable_sessions( {
        "bad": "not-a-dict",
        "nosid": { "alive": True, "stuck": True },                        # no session_id
        "ok": { "session_id": "ok", "alive": True, "stuck": True },
    } )
    assert set( pokeable ) == { "ok" }


def test_formatters_use_persona_then_session_id():
    job = _job()
    p = job._format_poke( { "session_id": "sid-x", "persona": None } )     # persona None → session_id
    assert "sid-x" in p
    r = job._format_reap_recommendation( { "session_id": "s", "persona": "Pat" }, 3 )
    assert "Pat" in r and "3 bounded auto-poke" in r


def test_poll_once_summary_carries_pokes_fired( tmp_path ):
    """_poll_once exposes pokes_fired in its summary (the lane is wired)."""
    job = _job( events_dir=str( tmp_path ) )
    summary = job._poll_once()
    assert "pokes_fired" in summary and summary[ "pokes_fired" ] == 0       # empty fleet → no pokes


# ── c9575068: awaiting-user honored-hold suppresses the harsh STUCK poke ──────
#
# A session with a FRESH HONORED hold declaring awaiting:user (or holding ≥1 open
# user-gate) is MANAGER-AWAITING-RICK — advisory, NOT wedged. The stuck-tier poke
# must SUPPRESS the "you appear STUCK — wedged?" escalation for it, mirroring the
# other three detectors' not-owed suppression. The truth lives in the HOLD (the
# 6929f4ac open-gate override reclassifies this state ACTIVE in owed_class, so the
# store classification cannot see it). Repro: Tiberius session eb4b105f, hold
# awaiting:user:rick + 4 open pending_user_gates, DM'd "you appear STUCK" on a
# ~60s cadence. Seam is INERT (fail-SAFE) when the hold-reader is unwired / the
# read hiccups / the hold is not honored — today's poke behavior is preserved.

def _honored_hold( **extra ):
    hold = { "held_at": NOW.isoformat(), "ttl_seconds": 7200, "reason": "awaiting Rick" }
    hold.update( extra )
    return hold


def _reader( sid_to_hold ):
    return lambda sid: sid_to_hold.get( sid )


def test_awaiting_user_honored_hold_suppresses_stuck_poke():
    """RED→GREEN (c9575068): a LIVE+stuck session whose FRESH HONORED hold declares
    awaiting:user:rick is NOT poked — it is correctly parked on Rick, not wedged."""
    gw   = _GW()
    hold = _honored_hold( awaiting="user:rick", work_owed=True )
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    for k in range( 5 ):
        assert job._auto_poke( _live_stuck(), NOW + datetime.timedelta( seconds=k * 100 ), [ ] ) == 0
    assert _pokes( gw ) == [ ]


def test_open_user_gates_honored_hold_suppresses_stuck_poke():
    """A FRESH HONORED hold with ≥1 OPEN pending_user_gate (awaiting=none) also
    suppresses — all pending gates awaiting the user IS the awaiting-Rick state."""
    gw   = _GW()
    hold = _honored_hold( awaiting="none",
                          pending_user_gates=[ { "answered": False, "last_asked_ts": NOW.isoformat() } ] )
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 0
    assert _pokes( gw ) == [ ]


def test_no_hold_reader_seam_still_pokes():
    """INERT seam (fail-SAFE): with no hold-reader wired, the stuck poke fires
    exactly as today — the suppression can only ADD, never silence by default."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )                       # hold_reader_fn defaults None
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_non_honored_hold_still_pokes():
    """A STALE (past-TTL) hold is NOT honored → no suppression → the genuinely
    stuck session is still poked (a dead hold cannot defend quiescence)."""
    gw    = _GW()
    stale = { "held_at": ( NOW - datetime.timedelta( hours=3 ) ).isoformat(),
              "ttl_seconds": 60, "reason": "old", "awaiting": "user:rick" }
    job   = _job( gw, poke_stall_threshold_seconds=0,
                  hold_reader_fn=_reader( { "s1": stale } ) )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_hold_read_hiccup_still_pokes():
    """A hold-reader that RAISES is swallowed (observer invariant) → no
    suppression → the stuck session is still poked (never silence on a hiccup)."""
    def _boom( sid ): raise RuntimeError( "store hiccup" )
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, hold_reader_fn=_boom )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_honored_hold_not_awaiting_user_still_pokes():
    """A FRESH HONORED hold that does NOT declare awaiting:user and has NO open
    user-gate (awaiting=none, gates all answered) does NOT suppress — a genuinely
    stuck session carrying an unrelated hold is still poked."""
    gw   = _GW()
    hold = _honored_hold( awaiting="none",
                          pending_user_gates=[ { "answered": True } ] )
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_session_awaiting_user_predicate_branches():
    """Direct leaf coverage of the _session_awaiting_user predicate across every
    branch: unwired seam, honored+awaiting-user, honored+open-gate, honored+neither."""
    job_inert = _job( _GW() )                                              # no hold-reader
    assert job_inert._session_awaiting_user( "s1", NOW ) is False
    job = _job( _GW(), hold_reader_fn=_reader( {
        "await": _honored_hold( awaiting="user:rick" ),
        "gate" : _honored_hold( awaiting="none",
                                pending_user_gates=[ { "answered": False } ] ),
        "plain": _honored_hold( awaiting="none" ),
        "absent": None,
    } ) )
    assert job._session_awaiting_user( "await",  NOW ) is True
    assert job._session_awaiting_user( "gate",   NOW ) is True
    assert job._session_awaiting_user( "plain",  NOW ) is False
    assert job._session_awaiting_user( "absent", NOW ) is False


# ── 262c59f6 H2: awaiting-PEER honored-hold suppresses the harsh STUCK poke ────
#
# A delegating MANAGER correctly parked on LIVE WORKERS carries a FRESH HONORED
# hold that declares work_owed=true AND awaiting:peer:... — proper MANAGE-not-BUILD
# posture, with NO self-transition to show BY DESIGN (the workers make the
# progress, not the manager). The activity-tail stuck oracle reads "no progress +
# work owed" as wedged, which is exactly wrong for a delegating manager; the
# honored work_owed=true peer-hold is the defended-quiescence artifact the store
# classification cannot see. The c9575068 awaiting-USER suppressor did NOT cover
# this — the sibling _session_awaiting_peer does. Repro: Tiberius eb4b105f, hold
# awaiting:peer:Rachel,peer:Cheech + work_owed=true, DM'd "you appear STUCK" ~2 min
# after a MANAGER-DONE advisory (the 262c59f6 contradiction). Same inert / fail-SAFE
# seam as the user path (unwired reader / hiccup / stale / no-work_owed → still poke).

def test_awaiting_peer_honored_work_owed_hold_suppresses_stuck_poke():
    """RED→GREEN (262c59f6 H2): a LIVE+stuck MANAGER whose FRESH HONORED hold
    declares work_owed=true + awaiting:peer:... is NOT poked — it is correctly
    delegating to live workers, not wedged."""
    gw   = _GW()
    hold = _honored_hold( awaiting="peer:Rachel,peer:Cheech", work_owed=True )
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    for k in range( 5 ):
        assert job._auto_poke( _live_stuck(), NOW + datetime.timedelta( seconds=k * 100 ), [ ] ) == 0
    assert _pokes( gw ) == [ ]


def test_awaiting_peer_hold_without_work_owed_still_pokes():
    """A peer-hold that does NOT declare work_owed=true is NOT the defended
    delegating posture (an absent/non-bool work_owed → None, NOT True) → no
    suppression → the genuinely stuck session is still poked (fail-SAFE)."""
    gw   = _GW()
    hold = _honored_hold( awaiting="peer:Rachel" )                         # no work_owed field
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_awaiting_peer_hold_work_owed_false_still_pokes():
    """work_owed EXPLICITLY false + awaiting:peer is DONE-equivalent, not a defended
    delegating posture → still poked (only work_owed IS True suppresses)."""
    gw   = _GW()
    hold = _honored_hold( awaiting="peer:Rachel", work_owed=False )
    job  = _job( gw, poke_stall_threshold_seconds=0,
                 hold_reader_fn=_reader( { "s1": hold } ) )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_session_awaiting_peer_predicate_branches():
    """Direct leaf coverage of _session_awaiting_peer across every branch: unwired
    seam, read-raises, stale (not honored), honored+peer+work_owed (True), honored+
    peer+no-work_owed, honored+peer+work_owed-false, honored+user (wrong prefix),
    honored+work_owed+no-awaiting (non-str), absent."""
    job_inert = _job( _GW() )                                              # no hold-reader
    assert job_inert._session_awaiting_peer( "s1", NOW ) is False          # unwired seam
    def _boom( sid ): raise RuntimeError( "hiccup" )
    assert _job( _GW(), hold_reader_fn=_boom )._session_awaiting_peer( "x", NOW ) is False  # read raises → SAFE
    stale = { "held_at": ( NOW - datetime.timedelta( hours=3 ) ).isoformat(),
              "ttl_seconds": 60, "awaiting": "peer:Rachel", "work_owed": True }
    job = _job( _GW(), hold_reader_fn=_reader( {
        "peer_owed" : _honored_hold( awaiting="peer:Rachel", work_owed=True ),
        "peer_none" : _honored_hold( awaiting="peer:Rachel" ),
        "peer_false": _honored_hold( awaiting="peer:Rachel", work_owed=False ),
        "user"      : _honored_hold( awaiting="user:rick", work_owed=True ),
        "no_await"  : _honored_hold( work_owed=True ),                     # awaiting absent → non-str
        "stale"     : stale,
        "absent"    : None,
    } ) )
    assert job._session_awaiting_peer( "peer_owed",  NOW ) is True
    assert job._session_awaiting_peer( "peer_none",  NOW ) is False
    assert job._session_awaiting_peer( "peer_false", NOW ) is False
    assert job._session_awaiting_peer( "user",       NOW ) is False
    assert job._session_awaiting_peer( "no_await",   NOW ) is False
    assert job._session_awaiting_peer( "stale",      NOW ) is False
    assert job._session_awaiting_peer( "absent",     NOW ) is False


# ── 262c59f6 unify: the stuck path cross-checks the STORE owed_class ───────────
#
# The stuck oracle (activity tail, fleet_view["stuck"]) and the MANAGER-DONE oracle
# (store owed_class) read DIFFERENT sources and can contradict within one poll (the
# 262c59f6 root). Unify: the stuck poke consults the SAME store authority the other
# three detectors read (owed_class_suppresses) — a session the store says owes
# nothing pokeable (DONE / BLOCKED_ON_USER) is NOT harshly poked as "wedged WITH
# work owed". ACTIVE / UNKNOWN / omitted → today's behavior (fail-SAFE).

@pytest.mark.parametrize( "cls", [ CLASS_DONE, CLASS_BLOCKED_ON_USER ] )
def test_owed_class_not_owed_suppresses_stuck_poke( cls ):
    """A LIVE+stuck session the STORE classifies DONE / BLOCKED_ON_USER owes nothing
    pokeable → the stuck path suppresses, unifying with the other three detectors."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )
    assert job._auto_poke( _live_stuck(), NOW, [ ], owed_class={ "Stuckie": cls } ) == 0
    assert _pokes( gw ) == [ ]


@pytest.mark.parametrize( "cls", [ CLASS_ACTIVE, CLASS_UNKNOWN ] )
def test_owed_class_owed_or_unknown_still_pokes( cls ):
    """ACTIVE (owes real work) and UNKNOWN (fail-SAFE: seam unwired / store hiccup)
    → the store cross-check does NOT suppress → today's poke fires."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )
    assert job._auto_poke( _live_stuck(), NOW, [ ], owed_class={ "Stuckie": cls } ) == 1
    assert len( _pokes( gw ) ) == 1


def test_owed_class_omitted_defaults_to_today_behavior():
    """owed_class omitted (caller passes nothing) → None default → today's poke
    behavior (the store cross-check can only ADD suppression, never silence)."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0 )
    assert job._auto_poke( _live_stuck(), NOW, [ ] ) == 1                  # no owed_class arg
    assert len( _pokes( gw ) ) == 1


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
