#!/usr/bin/env python3
"""
Post-game F2 receipts (2026-06-11) — the manager-staleness poke tier.

The 2026-06-10 silent stall: a manager session decayed to verdict "stale 34m"
(state=working, stuck=False) and was NEVER pokeable — `_pokeable_sessions`
requires alive∧stuck, taps require attention workers, D4 requires a prior tap.
F2 adds a SECOND, role-gated criterion: a MANAGER-role session whose freshest
union signal is ≥ `arbiter manager stale poke threshold seconds` gets a bounded
poke + ONE Rick advisory per episode — with zero stuck workers. Receipts:
  • ROLE GATE — an equally-stale WORKER row gets NOTHING (quiet≠stall intact).
  • ADVISORY-ON-FIRST-CROSSING — Rick's advisory fires the SAME poll as poke #1,
    not after poke exhaustion (pokes at a dark session are best-effort).
  • EPISODE MECHANICS — ≤ poke_max_per_episode pokes, one advisory, silence;
    recovery (freshening below threshold) clears + re-arms.
  • CORPSE CEILING (same-day calibration fix, 2026-06-11) — eligible iff
    threshold <= freshest_age_s <= max_age, both bounds inclusive. A >=20h
    corpse row resurfaced by the include_offline detection snapshot draws
    NOTHING (the 10:52 EDT boot-burst: yesterday's dead Tiberius session
    4f7a7ab8 poked at "silent 1134m" + a Rick advisory, on every restart).
  • NONE-AGE FLIP — freshest_age_s None = no signal EVER = corpse/malformed
    row → NOT eligible (was: maximally-stale-eligible; that choice poked
    corpses). Documented in _check_manager_staleness.
  • 0 DISABLES the tier; negative threshold raises ValueError; an EMPTY
    [threshold, max_age] window (max_age <= threshold, tier enabled) raises.

Venue: :7999-eligible / local — pure + mocked, no server, no real wait.
Design: src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §3.2.
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


NOW = datetime.datetime( 2026, 6, 11, 18, 0, 0, tzinfo=datetime.timezone.utc )


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
        log_fn            = lambda *a, **k: None,
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( **cfg )


def _row( sid, role, age, persona=None ):
    return { "session_id": sid, "persona": persona or sid, "state": "working",
             "holding_on": "none", "stuck": False, "role": role,
             "liveness": { "freshest_age_s": age, "verdict": "stale 45m" } }


def _snap( *rows ):
    return { "generated_at": NOW.isoformat(), "session_count": len( rows ),
             "sessions": list( rows ) }


def _stale_pokes( gw ):
    return [ s for s in gw.sent if "manager-staleness poke" in s[ 1 ] ]


# ── role gate: workers untouched (quiet≠stall preserved) ─────────────────────

def test_stale_worker_gets_nothing():
    """ROLE GATE: a WORKER-role row stale far past the threshold gets neither a
    staleness poke nor an advisory — María's quiet≠stall doctrine survives F2."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "w1", "worker", 9000 ) )
    for k in range( 4 ):
        assert job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ), [ ] ) == 0
    assert gw.sent == [ ] and escal == [ ]


def test_fresh_manager_gets_nothing():
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 120 ) )                       # 2 min fresh
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 0
    assert gw.sent == [ ] and escal == [ ]


# ── the headline: stale manager → poke + Rick advisory, same poll ────────────

def test_stale_manager_poked_and_rick_advised_same_poll():
    """ADVISORY-ON-FIRST-CROSSING: poke #1 and the Rick advisory fire on the SAME
    poll the threshold is crossed — the advisory is the load-bearing output."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 2700, persona="Tiberius" ) )   # exactly the threshold
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ "OtherMgr" ] )
    assert fired == 1
    assert len( _stale_pokes( gw ) ) == 1 and _stale_pokes( gw )[ 0 ][ 0 ] == "Tiberius"
    assert "45m" in _stale_pokes( gw )[ 0 ][ 1 ]
    advisories = [ m for m in escal if "MANAGER-STALE" in m ]
    assert len( advisories ) == 1
    assert "Tiberius" in advisories[ 0 ] and "45m" in advisories[ 0 ]
    # EDT-labeled wall time in the Rick-facing body (commons/journal are UTC)
    assert "EDT" in advisories[ 0 ] or "EST" in advisories[ 0 ]
    # case-14 fanout: the advisory also reached the OTHER active manager
    assert ( "OtherMgr", advisories[ 0 ] ) in gw.sent


def test_corpse_manager_age_none_not_eligible():
    """NONE-AGE FLIP (corpse-ceiling fix, 2026-06-11): freshest_age_s None = no
    signal EVER recorded = a corpse/malformed row, NOT a maximally-stale live
    manager. The original eligible-when-None choice interacted badly with corpse
    rows once detection went include_offline — flipped by decision, never by
    drift (this test replaces test_offline_manager_age_none_stays_eligible,
    which asserted the OPPOSITE outcome)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", None ) )
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 0
    assert gw.sent == [ ] and escal == [ ]
    assert "m1" not in job._mgr_stale_since                            # no episode ever opened


# ── the corpse ceiling: eligible iff threshold <= age <= max_age ──────────────

def test_age_at_ceiling_inclusive_one_past_not_eligible():
    """CEILING BOUNDARY: both bounds of [threshold, max_age] are inclusive —
    exactly max_age (7200 default) still fires; one second past it does not."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    assert job._check_manager_staleness( _snap( _row( "m1", "manager", 7200 ) ), NOW, [ ] ) == 1
    assert len( _stale_pokes( gw ) ) == 1
    gw2, escal2 = _GW(), [ ]
    job2 = _job( gw2, notify=lambda m, *a, **k: escal2.append( m ) )
    assert job2._check_manager_staleness( _snap( _row( "m1", "manager", 7201 ) ), NOW, [ ] ) == 0
    assert gw2.sent == [ ] and escal2 == [ ]


def test_yesterday_corpse_beyond_ceiling_draws_nothing_across_polls():
    """THE BUG, PINNED (10:52 EDT 2026-06-11 boot-burst): a corpse manager row at
    1134m = 68040s — yesterday's dead Tiberius session resurfaced by the
    include_offline=True detection snapshot — drew a poke burst + a Rick advisory
    on EVERY :8001 process start. Beyond the ceiling → never eligible, repeated
    polls included; no episode state is ever created for it."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "corpse-4f7a7ab8", "manager", 68040, persona="Tiberius" ) )
    for k in range( 4 ):
        assert job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ), [ ] ) == 0
    assert gw.sent == [ ] and escal == [ ]
    assert "corpse-4f7a7ab8" not in job._mgr_stale_since


def test_manager_aging_past_ceiling_mid_episode_clears_episode():
    """A live episode whose manager keeps darkening PAST the ceiling transitions
    to corpse status: it drops out of eligibility and the episode state clears
    (cap + advisory re-arm if the manager ever returns to the window)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    job._check_manager_staleness( _snap( _row( "m1", "manager", 3000 ) ), NOW, [ ] )
    assert "m1" in job._mgr_stale_since and "m1" in job._mgr_advised
    job._check_manager_staleness( _snap( _row( "m1", "manager", 9000 ) ),
                                  NOW + datetime.timedelta( seconds=60 ), [ ] )
    assert "m1" not in job._mgr_stale_since and "m1" not in job._mgr_advised


# ── episode mechanics: bounded pokes, one advisory, recovery re-arms ─────────

def test_episode_caps_pokes_and_advises_once():
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ), poke_max_per_episode=3 )
    snap = _snap( _row( "m1", "manager", 3000 ) )
    for k in range( 8 ):                                               # 8 polls over the same dark manager
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ), [ ] )
    assert len( _stale_pokes( gw ) ) == 3                              # capped
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 1    # one advisory, then silence


def test_recovery_clears_episode_and_rearms():
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ), poke_max_per_episode=2 )
    stale = _snap( _row( "m1", "manager", 3000 ) )
    fresh = _snap( _row( "m1", "manager", 60 ) )
    # episode 1: 2 pokes + 1 advisory, then capped
    for k in range( 4 ):
        job._check_manager_staleness( stale, NOW + datetime.timedelta( seconds=k * 60 ), [ ] )
    assert len( _stale_pokes( gw ) ) == 2
    assert "m1" in job._mgr_stale_since and "m1" in job._mgr_advised
    # recovery → episode state cleared
    job._check_manager_staleness( fresh, NOW + datetime.timedelta( seconds=300 ), [ ] )
    assert "m1" not in job._mgr_stale_since and "m1" not in job._mgr_advised
    # episode 2: cap + advisory re-armed
    for k in range( 4 ):
        job._check_manager_staleness( stale, NOW + datetime.timedelta( seconds=600 + k * 60 ), [ ] )
    assert len( _stale_pokes( gw ) ) == 4                              # 2 (ep1) + 2 (ep2)
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 2    # one per episode


def test_manager_leaving_roster_clears_episode():
    gw = _GW()
    job = _job( gw )
    job._check_manager_staleness( _snap( _row( "m1", "manager", 3000 ) ), NOW, [ ] )
    assert "m1" in job._mgr_stale_since
    job._check_manager_staleness( _snap(), NOW + datetime.timedelta( seconds=60 ), [ ] )   # roster empty
    assert "m1" not in job._mgr_stale_since


# ── config: 0 disables; negative raises; malformed rows skipped ──────────────

def test_threshold_zero_disables_tier():
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                manager_stale_poke_threshold_seconds=0 )
    assert job._check_manager_staleness( _snap( _row( "m1", "manager", 99999 ) ), NOW, [ ] ) == 0
    assert gw.sent == [ ] and escal == [ ]


def test_negative_threshold_raises():
    with pytest.raises( ValueError ):
        _job( manager_stale_poke_threshold_seconds=-1 )


def test_empty_eligibility_window_raises():
    """max_age <= threshold makes the [threshold, max_age] window EMPTY — the
    tier would be silently config-dead, so the constructor fails fast (same
    bug-class guard as the quiet < alive invariant)."""
    with pytest.raises( ValueError ):
        _job( manager_stale_poke_max_age_seconds=2700 )                # == threshold (2700): empty
    with pytest.raises( ValueError ):
        _job( manager_stale_poke_max_age_seconds=600 )                 # below threshold


def test_max_age_unchecked_when_tier_disabled():
    """threshold == 0 disables the tier; the empty-window guard short-circuits
    (the ceiling is irrelevant on a disabled tier)."""
    job = _job( manager_stale_poke_threshold_seconds=0,
                manager_stale_poke_max_age_seconds=0 )
    assert job._check_manager_staleness( _snap( _row( "m1", "manager", 3000 ) ), NOW, [ ] ) == 0


def test_malformed_rows_and_snapshot_are_safe():
    gw = _GW()
    job = _job( gw )
    snap = { "sessions": [ "not-a-dict",
                           { "role": "manager" },                       # no session_id
                           { "session_id": "m2", "role": "manager",
                             "liveness": "not-a-dict" },                # malformed → age None → NOT eligible (the flip)
                           { "session_id": "m3", "role": "manager",
                             "liveness": { "freshest_age_s": 3000 } } ] }   # in-window control row
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 1          # ONLY the in-window m3 fires
    assert "m2" not in job._mgr_stale_since                             # the malformed row opened no episode
    assert job._check_manager_staleness( None, NOW, [ ] ) == 0          # falsy snapshot → no-op
    # m3 left the roster via the None snapshot → episode cleared
    assert "m3" not in job._mgr_stale_since


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
