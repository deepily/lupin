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

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob


NOW = datetime.datetime( 2026, 6, 9, 0, 0, 0, tzinfo=datetime.timezone.utc )


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b ): self.sent.append( ( r, b ) )
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


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
