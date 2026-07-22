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

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, CLASS_UNKNOWN


NOW = datetime.datetime( 2026, 6, 11, 18, 0, 0, tzinfo=datetime.timezone.utc )


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


# ── 46eb7b98: union freshest_age future-mtime lower bound (097778b8 sibling) ──

def test_future_mtime_twin_does_not_suppress_stale_manager_poke():
    """46eb7b98 (sibling of 097778b8): a manager incarnation whose union
    freshest_age_s is NEGATIVE (future / corrupt mtime — clock skew) must NOT be
    counted LIVE. Pre-fix the `fa < threshold` live-set test carries no lower
    bound, so fa=-5 reads as fresh → the persona lands in live_personas → a
    genuinely-stale twin of the SAME persona is twin-suppressed → the warranted
    poke is silently swallowed (fail toward silence). Post-fix (0 <= fa) the
    corrupt incarnation is not counted live → the stale twin pokes (fail toward
    action). The eligibility gate at :3764-3765 already excludes negatives via
    threshold>0, so the real 097778b8 sibling is the live_personas floor."""
    gw  = _GW()
    job = _job( gw )
    snap = _snap(
        _row( "dorky-future", "manager", -5,   persona="Dorky" ),      # future mtime → negative union age
        _row( "dorky-stale",  "manager", 3000, persona="Dorky" ),      # genuinely stale twin, in [thr, max]
    )
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ ] )
    assert fired == 1                                                  # the stale twin pokes...
    assert len( _stale_pokes( gw ) ) == 1                             # ...unshielded by the corrupt incarnation


# ── 33949e83: store-health gate — MANAGER-STALE suppressed on a self-observed outage ──

def test_manager_stale_suppressed_when_store_degraded():
    """A stale (in-window) MANAGER whose owed_class is UNKNOWN DURING a degraded
    arbiter read → the silence is untrustworthy (infra outage swallowed signals) →
    SUPPRESS the case-14 poke + Rick advisory; the episode is NOT started (re-arms)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000 ) )                      # stale, in [2700, 7200]
    fired = job._check_manager_staleness( snap, NOW, [ ], owed_class={ "m1": CLASS_UNKNOWN },
                                          store_read_degraded=True )
    assert fired == 0
    assert _stale_pokes( gw ) == [ ] and escal == [ ]
    assert "m1" not in job._mgr_stale_since                           # episode NOT started → re-arms


def test_manager_stale_fires_when_store_healthy():
    """Store healthy → today's MANAGER-STALE case-14 poke still fires (the gate only
    suppresses on a self-observed outage — never silences a genuinely-dark manager)."""
    gw, escal = _GW(), [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000 ) )
    fired = job._check_manager_staleness( snap, NOW, [ ], owed_class={ "m1": CLASS_UNKNOWN },
                                          store_read_degraded=False )
    assert fired == 1


# ── task 70be69f2: hold-file mtime is a sign of life (the canonical repro) ────

def test_fresh_hold_mtime_keeps_interactive_manager_off_staleness_tier():
    """REPRO (Tiberius sess 6ec69a8c): an interactive, no-`/loop` MANAGER whose
    stop-event aged to 45m (and no bridge / commons) but whose HOLD mtime is fresh
    (re-stamped every Stop) must read LIVE, NOT MANAGER-STALE. Drives the REAL
    _publish_fleet_snapshot (which now reads the injected hold_mtime_fn) and then
    the staleness detector over its emitted snapshot — proving the full wiring."""
    gw, escal   = _GW(), [ ]
    stale_event = NOW - datetime.timedelta( seconds=2700 )            # 45m-old stop-event
    view = { "m1": { "session_id": "m1", "persona": "Tiberius", "state": "working",
                     "holding_on": "none", "stuck": False, "reaped": False,
                     "last_event_ts": stale_event, "commons_ts": None,
                     "idle_prompt_ts": None, "dm_ts": None } }
    job = _job(
        gw, notify=lambda m, *a, **k: escal.append( m ),
        declared_managers   = [ "Tiberius" ],                          # badge m1 role=manager
        bridge_mtime_fn     = lambda sid: None,                        # no bridge signal
        hold_mtime_fn       = lambda sid: NOW.timestamp() - 5,         # FRESH hold (5s)
        bridge_discovery_fn = lambda: { },
        list_managers_fn    = lambda: set(),
        resolve_manager_fn  = lambda sid, **k: { "manager_persona": None, "source": "unresolved" },
        snapshot_sink       = lambda s: None,
        render_sink         = lambda s: None,
    )
    job._publish_fleet_snapshot( view, NOW, True )
    row = job._last_full_snapshot[ "sessions" ][ 0 ]
    assert row[ "role" ] == "manager"
    assert row[ "liveness" ][ "hold_age_s" ] == 5                      # hold mtime folded in
    assert row[ "liveness" ][ "verdict" ] == "LIVE"                    # hold rescued it from "stale 45m"
    # the staleness detector over the SAME snapshot fires NOTHING — the bug is dead.
    assert job._check_manager_staleness( job._last_full_snapshot, NOW, [ ] ) == 0
    assert _stale_pokes( gw ) == [ ] and escal == [ ]


def test_stale_hold_does_not_rescue_a_truly_dark_manager():
    """FAIL-SAFE counter-control: a manager with a stale stop-event AND a stale hold
    mtime (everything aged out) still reads stale and IS poked — hold-mtime only
    ADDS liveness, it never suppresses a genuinely-dark session."""
    gw, escal   = _GW(), [ ]
    stale_event = NOW - datetime.timedelta( seconds=3000 )            # 50m-old stop-event
    view = { "m1": { "session_id": "m1", "persona": "Tiberius", "state": "working",
                     "holding_on": "none", "stuck": False, "reaped": False,
                     "last_event_ts": stale_event, "commons_ts": None,
                     "idle_prompt_ts": None, "dm_ts": None } }
    job = _job(
        gw, notify=lambda m, *a, **k: escal.append( m ),
        declared_managers   = [ "Tiberius" ],
        bridge_mtime_fn     = lambda sid: None,
        hold_mtime_fn       = lambda sid: NOW.timestamp() - 3000,      # hold ALSO 50m stale
        bridge_discovery_fn = lambda: { },
        list_managers_fn    = lambda: set(),
        resolve_manager_fn  = lambda sid, **k: { "manager_persona": None, "source": "unresolved" },
        snapshot_sink       = lambda s: None,
        render_sink         = lambda s: None,
    )
    job._publish_fleet_snapshot( view, NOW, True )
    row = job._last_full_snapshot[ "sessions" ][ 0 ]
    assert row[ "liveness" ][ "hold_age_s" ] == 3000
    assert job._check_manager_staleness( job._last_full_snapshot, NOW, active_managers=[ ] ) == 1
    assert len( _stale_pokes( gw ) ) == 1                              # genuinely dark → poked


# ── bug fb332fcd: transcript mtime is a sign of life (plan-mode repro) ────────

def test_fresh_transcript_mtime_keeps_planmode_manager_off_staleness_tier():
    """REPRO (bug fb332fcd, Tiberius 2026-06-30): a MANAGER deep in an APPROVED
    PLAN emits no Stop for the whole plan turn, so its stop-event aged to 45m and
    it posts no commons / bumps no bridge / refreshes no hold — yet it is actively
    appending its transcript .jsonl on every tool call. The fresh transcript mtime
    must read LIVE, NOT MANAGER-STALE. Drives the REAL _publish_fleet_snapshot
    (which now reads the injected transcript_mtime_fn) then the staleness detector
    over its emitted snapshot — the full end-to-end wiring (non-negotiable #2)."""
    gw, escal   = _GW(), [ ]
    stale_event = NOW - datetime.timedelta( seconds=2700 )            # 45m-old stop-event
    view = { "m1": { "session_id": "m1", "persona": "Tiberius", "state": "working",
                     "holding_on": "none", "stuck": False, "reaped": False,
                     "last_event_ts": stale_event, "commons_ts": None,
                     "idle_prompt_ts": None, "dm_ts": None } }
    job = _job(
        gw, notify=lambda m, *a, **k: escal.append( m ),
        declared_managers   = [ "Tiberius" ],                          # badge m1 role=manager
        bridge_mtime_fn     = lambda sid: None,                        # no bridge signal
        hold_mtime_fn       = lambda sid: None,                        # no hold signal either
        transcript_mtime_fn = lambda sid: NOW.timestamp() - 5,         # FRESH transcript (5s)
        bridge_discovery_fn = lambda: { },
        list_managers_fn    = lambda: set(),
        resolve_manager_fn  = lambda sid, **k: { "manager_persona": None, "source": "unresolved" },
        snapshot_sink       = lambda s: None,
        render_sink         = lambda s: None,
    )
    job._publish_fleet_snapshot( view, NOW, True )
    row = job._last_full_snapshot[ "sessions" ][ 0 ]
    assert row[ "role" ] == "manager"
    assert row[ "liveness" ][ "transcript_age_s" ] == 5               # transcript mtime folded in
    assert row[ "liveness" ][ "verdict" ] == "LIVE"                   # transcript rescued it from "stale 45m"
    # the staleness detector over the SAME snapshot fires NOTHING — the bug is dead.
    assert job._check_manager_staleness( job._last_full_snapshot, NOW, [ ] ) == 0
    assert _stale_pokes( gw ) == [ ] and escal == [ ]


def test_stale_transcript_does_not_rescue_a_truly_dark_manager():
    """FAIL-SAFE counter-control (non-negotiable #1): a manager whose stop-event
    AND transcript mtime are BOTH stale (a genuinely-dark / exited session — its
    transcript stopped appending) still reads stale and IS poked. Transcript-mtime
    only ADDS liveness, it NEVER suppresses a dark session. A MISSING transcript
    (transcript_mtime_fn → None) is exercised by every other test in this file
    that does not inject the fn, so the no-signal path is covered too."""
    gw, escal   = _GW(), [ ]
    stale_event = NOW - datetime.timedelta( seconds=3000 )            # 50m-old stop-event
    view = { "m1": { "session_id": "m1", "persona": "Tiberius", "state": "working",
                     "holding_on": "none", "stuck": False, "reaped": False,
                     "last_event_ts": stale_event, "commons_ts": None,
                     "idle_prompt_ts": None, "dm_ts": None } }
    job = _job(
        gw, notify=lambda m, *a, **k: escal.append( m ),
        declared_managers   = [ "Tiberius" ],
        bridge_mtime_fn     = lambda sid: None,
        hold_mtime_fn       = lambda sid: None,
        transcript_mtime_fn = lambda sid: NOW.timestamp() - 3000,      # transcript ALSO 50m stale
        bridge_discovery_fn = lambda: { },
        list_managers_fn    = lambda: set(),
        resolve_manager_fn  = lambda sid, **k: { "manager_persona": None, "source": "unresolved" },
        snapshot_sink       = lambda s: None,
        render_sink         = lambda s: None,
    )
    job._publish_fleet_snapshot( view, NOW, True )
    row = job._last_full_snapshot[ "sessions" ][ 0 ]
    assert row[ "liveness" ][ "transcript_age_s" ] == 3000
    assert job._check_manager_staleness( job._last_full_snapshot, NOW, active_managers=[ ] ) == 1
    assert len( _stale_pokes( gw ) ) == 1                              # genuinely dark → poked


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
    # AC-3 (mini-plan 04): RICK STILL RECEIVES IT. A regression that silences the
    # advisory entirely would satisfy "no peer got it" and fail the user, so the
    # Rick hop is pinned explicitly on the SAME episode as the peer-silence check.
    advisories = [ m for m in escal if "MANAGER-STALE" in m ]
    assert len( advisories ) == 1
    assert "Tiberius" in advisories[ 0 ] and "45m" in advisories[ 0 ]
    # EDT-labeled wall time in the Rick-facing body (commons/journal are UTC)
    assert "EDT" in advisories[ 0 ] or "EST" in advisories[ 0 ]
    # AC-2 (mini-plan 04): NO peer fan-out. Asserted on the RECIPIENT alone, never
    # as "that (recipient, message) tuple is absent" — a tuple check passes the
    # moment the message TEXT changes while the peer still receives a DM, and a
    # control an unrelated edit can satisfy is not a control.
    assert [ s for s in gw.sent if s[ 0 ] == "OtherMgr" ] == [ ]
    # the ONLY gateway traffic is the poke, addressed TO the stale subject
    assert [ s[ 0 ] for s in gw.sent ] == [ "Tiberius" ]


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


# ── L1 store-awareness (lane 4, 2026-06-17): BLOCKED_ON_USER / DONE suppress ──
#    the case-14 poke; ACTIVE / UNKNOWN keep today's behavior. The discriminator
#    is the per-poll store classification (owed_class), mirroring _check_manager_acks.

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    CLASS_BLOCKED_ON_USER, CLASS_DONE, CLASS_ACTIVE, CLASS_UNKNOWN,
)


def _awaiting( escal ):
    return [ m for m in escal if "MANAGER-AWAITING-RICK" in m ]

def _done_adv( escal ):
    return [ m for m in escal if "MANAGER-DONE" in m ]


def test_blocked_on_user_manager_suppressed_to_case16():
    """BLOCKED_ON_USER: a manager whose every owed item is Rick-gated is silent
    BECAUSE it correctly waits — NO case-14 poke; exactly ONE case-16 advisory."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                          owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert fired == 0                                       # no staleness poke
    assert _stale_pokes( gw ) == [ ]                        # nothing sent to the manager
    assert len( _awaiting( escal ) ) == 1                  # ONE awaiting-Rick advisory
    assert "Tiberius" in _awaiting( escal )[ 0 ]
    assert [ m for m in escal if "MANAGER-STALE" in m ] == [ ]   # NOT the case-14 advisory
    assert "m1" not in job._mgr_stale_since                # no staleness episode opened
    assert "Tiberius" in job._manager_blocked_advised


def test_done_manager_suppressed_to_case17():
    """DONE: a manager owing zero non-terminal work is finished/idle — NO case-14
    poke; exactly ONE case-17 consider-reaping advisory."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Rachel" ) )
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                          owed_class={ "Rachel": CLASS_DONE } )
    assert fired == 0 and _stale_pokes( gw ) == [ ]
    assert len( _done_adv( escal ) ) == 1 and "Rachel" in _done_adv( escal )[ 0 ]
    assert "m1" not in job._mgr_stale_since
    assert "Rachel" in job._manager_done_advised


def test_active_manager_still_poked():
    """ACTIVE (≥1 non-Rick-gated owed item) → today's case-14 staleness poke."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Krishna" ) )
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                          owed_class={ "Krishna": CLASS_ACTIVE } )
    assert fired == 1 and len( _stale_pokes( gw ) ) == 1
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 1   # case-14 advisory
    assert _awaiting( escal ) == [ ] and _done_adv( escal ) == [ ]


def test_unknown_class_fails_safe_to_poke():
    """UNKNOWN (seam unwired / store hiccup / persona absent from owed_class) →
    FAIL SAFE: today's case-14 poke (never silently suppress). This preserves the
    quota-freeze true positive (all-stale-UNKNOWN still escalates)."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Ghost" ) )
    # owed_class explicitly UNKNOWN AND, separately, persona absent → both fail-safe
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                          owed_class={ "Ghost": CLASS_UNKNOWN } )
    assert fired == 1 and len( _stale_pokes( gw ) ) == 1
    # absent-from-owed_class path (defaults to UNKNOWN) on a fresh job
    gw2, escal2 = _GW(), [ ]
    job2 = _job( gw2, notify=lambda m, *a, **k: escal2.append( m ) )
    assert job2._check_manager_staleness( snap, NOW, active_managers=[ ], owed_class={ } ) == 1


def test_blocked_advisory_fires_once_then_silent():
    """The case-16 advisory is one-time: repeated polls over the same blocked
    manager never re-fire it (anti-storm; shared advised flag)."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    for k in range( 6 ):
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ],
                                      owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert len( _awaiting( escal ) ) == 1 and _stale_pokes( gw ) == [ ]


def test_done_advisory_fires_once_then_silent():
    """The case-17 advisory is one-time too: repeated polls over the same DONE
    manager never re-fire it (covers the `persona in _manager_done_advised`
    skip-branch — the DONE twin of the blocked anti-storm)."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Rachel" ) )
    for k in range( 5 ):
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ], owed_class={ "Rachel": CLASS_DONE } )
    assert len( _done_adv( escal ) ) == 1 and _stale_pokes( gw ) == [ ]


def test_blocked_then_freshens_rearms_case16():
    """RE-ARM: a suppressed BLOCKED manager that freshens below threshold clears
    the shared advised flag, so a FUTURE blocked episode re-advises once."""
    gw, escal = _GW(), [ ]
    job   = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    stale = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    fresh = _snap( _row( "m1", "manager", 60, persona="Tiberius" ) )
    bl    = { "Tiberius": CLASS_BLOCKED_ON_USER }
    job._check_manager_staleness( stale, NOW, [ ], owed_class=bl )                 # ep1: case-16
    assert "Tiberius" in job._manager_blocked_advised and "m1" in job._mgr_stale_suppressed
    job._check_manager_staleness( fresh, NOW + datetime.timedelta( seconds=60 ), [ ], owed_class=bl )  # freshen → re-arm
    assert "Tiberius" not in job._manager_blocked_advised and "m1" not in job._mgr_stale_suppressed
    job._check_manager_staleness( stale, NOW + datetime.timedelta( seconds=120 ), [ ], owed_class=bl ) # ep2: case-16 again
    assert len( _awaiting( escal ) ) == 2


def test_done_then_freshens_rearms_case17():
    """RE-ARM for the DONE branch (the else-arm of the suppressed-clear loop)."""
    gw, escal = _GW(), [ ]
    job   = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    stale = _snap( _row( "m1", "manager", 3000, persona="Rachel" ) )
    fresh = _snap( _row( "m1", "manager", 60, persona="Rachel" ) )
    dn    = { "Rachel": CLASS_DONE }
    job._check_manager_staleness( stale, NOW, [ ], owed_class=dn )
    assert "Rachel" in job._manager_done_advised
    job._check_manager_staleness( fresh, NOW + datetime.timedelta( seconds=60 ), [ ], owed_class=dn )
    assert "Rachel" not in job._manager_done_advised and "m1" not in job._mgr_stale_suppressed
    job._check_manager_staleness( stale, NOW + datetime.timedelta( seconds=120 ), [ ], owed_class=dn )
    assert len( _done_adv( escal ) ) == 2


# ── bug 58660c64: cross-detector ping-pong cooldown (advisory loop-fire fix) ──
#    _check_manager_acks re-arms (discards) the SHARED _manager_blocked_advised
#    flag on ANY liveness activity (:3085); the staleness path then re-fires the
#    case-16/17 advisory every poll while the union age reads stale (the 26dd3afb
#    bridge-vs-union divergence). A per-(family, persona) COOLDOWN caps the fire
#    rate independent of the flappy flag. RED-first: pre-fix these re-fire N times.

def _cooldown_sup_logs( logs ):
    return [ ( ev, f ) for ev, f in logs if ev == "arbiter_advisory_suppressed_cooldown" ]


def test_case16_cooldown_suppresses_pingpong_refire():
    """The case-16 advisory must fire ONCE across a multi-poll ping-pong: each poll
    the acks-path liveness re-arm discards the shared flag (simulated via discard —
    exactly the :3085 effect for a parked-but-alive manager) while the staleness
    view still reads the union stale. Cooldown → one advisory + an observable
    suppression journal event per suppressed re-fire."""
    gw, escal, logs = _GW(), [ ], [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                 log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    bl   = { "Tiberius": CLASS_BLOCKED_ON_USER }
    for k in range( 3 ):
        job._manager_blocked_advised.discard( "Tiberius" )     # acks-path :3085 liveness re-arm
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ], owed_class=bl )
    assert len( _awaiting( escal ) ) == 1                      # ONE, not 3 (the loop-fire is dead)
    sup = _cooldown_sup_logs( logs )
    assert len( sup ) == 2                                     # the 2 suppressed re-fires are observable
    assert sup[ 0 ][ 1 ][ "persona" ] == "Tiberius" and sup[ 0 ][ 1 ][ "family" ] == "blocked"
    assert sup[ 1 ][ 1 ][ "suppressed_count" ] == 2            # running count in the journal


def test_case17_cooldown_suppresses_pingpong_refire():
    """The DONE (case-17) advisory gets the same cooldown protection."""
    gw, escal, logs = _GW(), [ ], [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                 log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Rachel" ) )
    dn   = { "Rachel": CLASS_DONE }
    for k in range( 3 ):
        job._manager_done_advised.discard( "Rachel" )
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ], owed_class=dn )
    assert len( _done_adv( escal ) ) == 1
    sup = _cooldown_sup_logs( logs )
    assert len( sup ) == 2 and sup[ 0 ][ 1 ][ "family" ] == "done"


def test_case16_cooldown_expires_allows_one_more():
    """After the cooldown window elapses on a still-parked manager, exactly ONE
    more advisory is allowed (bounded re-notify, not silence-forever)."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    bl   = { "Tiberius": CLASS_BLOCKED_ON_USER }
    job._check_manager_staleness( snap, NOW, [ ], owed_class=bl )                    # fire #1
    job._manager_blocked_advised.discard( "Tiberius" )                              # acks re-arm
    past = NOW + datetime.timedelta( seconds=job.manager_advisory_cooldown_seconds + 60 )
    job._check_manager_staleness( snap, past, [ ], owed_class=bl )                   # cooldown expired → fire #2
    assert len( _awaiting( escal ) ) == 2


def test_advisory_cooldown_defaults_to_staleness_threshold():
    """The cooldown default ties to the staleness threshold (~45m) — one number."""
    job = _job()
    assert job.manager_advisory_cooldown_seconds == job.manager_stale_poke_threshold_seconds


def test_advisory_cooldown_zero_disables_gate_fires_every_tick():
    """cooldown=0 DISABLES the gate → legacy per-tick behavior (the escape hatch).
    Covers the disabled branches of _advisory_cooldown_blocks + _stamp_advisory_cooldown."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                 manager_advisory_cooldown_seconds=0 )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    bl   = { "Tiberius": CLASS_BLOCKED_ON_USER }
    for k in range( 3 ):
        job._manager_blocked_advised.discard( "Tiberius" )
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ], owed_class=bl )
    assert len( _awaiting( escal ) ) == 3                       # disabled → fires every tick
    assert job._advisory_cooldown_until == { }                 # stamp is a no-op when disabled


def test_holdgate_case16_cooldown_suppresses_pingpong():
    """Site E (the _session_awaiting_user hold-gate case-16) is cooldown-guarded too:
    a parked manager whose hold declares awaiting-user re-fires ONCE, not per tick."""
    gw, escal, logs = _GW(), [ ], [ ]
    job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                log_fn=lambda ev, **k: logs.append( ( ev, k ) ),
                hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
    snap = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
    oc   = { "mr radio": CLASS_ACTIVE }                         # ACTIVE → reaches the hold-gate branch
    for k in range( 3 ):
        job._manager_blocked_advised.discard( "mr radio" )     # acks-path liveness re-arm
        job._check_manager_staleness( snap, NOW + datetime.timedelta( seconds=k * 60 ),
                                      active_managers=[ ], owed_class=oc )
    assert len( _awaiting( escal ) ) == 1
    assert len( _cooldown_sup_logs( logs ) ) == 2


def test_acks_path_case16_case17_cooldown_suppress():
    """The acks-path (#9 _check_manager_acks) case-16 AND case-17 emit sites are
    cooldown-guarded: with the shared flag cleared but the cooldown armed, neither
    re-fires — covering the acks-path suppress branches + their journal events."""
    late = NOW + datetime.timedelta( seconds=1000 )            # past the ack window (~600s) but within the 2700s cooldown
    # case-16 (BLOCKED): cooldown pre-armed, flag clear → suppressed, no advisory
    gw, escal, logs = _GW(), [ ], [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                 log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
    job._last_tap_at[ "Tiberius" ] = NOW
    job._stamp_advisory_cooldown( "blocked", "Tiberius", NOW )
    job._check_manager_acks( late, [ ], None, [ ], owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert _awaiting( escal ) == [ ]                           # cooldown suppressed the acks-path advisory
    assert any( f[ "family" ] == "blocked" for _e, f in _cooldown_sup_logs( logs ) )
    # case-17 (DONE): same, other family
    gw2, escal2, logs2 = _GW(), [ ], [ ]
    job2 = _job( gw2, notify=lambda m, *a, **k: escal2.append( m ),
                 log_fn=lambda ev, **k: logs2.append( ( ev, k ) ) )
    job2._last_tap_at[ "Rachel" ] = NOW
    job2._stamp_advisory_cooldown( "done", "Rachel", NOW )
    job2._check_manager_acks( late, [ ], None, [ ], owed_class={ "Rachel": CLASS_DONE } )
    assert _done_adv( escal2 ) == [ ]
    assert any( f[ "family" ] == "done" for _e, f in _cooldown_sup_logs( logs2 ) )


def test_cross_detector_dedup_blocked_advised_already_set():
    """CROSS-DETECTOR DE-DUPE: if _check_manager_acks already fired the case-16
    advisory (persona in the SHARED _manager_blocked_advised), the staleness path
    suppresses the poke but does NOT double-page Rick."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    job._manager_blocked_advised.add( "Tiberius" )         # acks path already advised
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    fired = job._check_manager_staleness( snap, NOW, [ ],
                                          owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert fired == 0 and _stale_pokes( gw ) == [ ]        # poke still suppressed
    assert _awaiting( escal ) == [ ]                       # but NO second advisory
    assert "m1" not in job._mgr_stale_suppressed           # staleness didn't claim the flag


# ── bug b9911943: the named subject is excluded from its OWN advisory fan-out ──
#    The double-delivery repro the original fixtures missed: every prior test put
#    OTHER managers (or none) in active_managers, never the stale subject itself.
#    With the subject IN active_managers, the case-14 advisory used to fan out to
#    the subject too — so a dark manager got BOTH the about-itself MANAGER-STALE
#    advisory AND its own staleness poke ~1s apart. The fix drops the subject from
#    the TIER_RICK_AND_MANAGERS fan-out; the poke (addressed TO it) is unchanged.

def _subject_advisories( gw, subject, marker ):
    """Messages addressed to `subject` in the manager fan-out carrying `marker`."""
    return [ s for s in gw.sent if s[ 0 ] == subject and marker in s[ 1 ] ]


def test_case14_stale_subject_gets_poke_and_nobody_is_advised_but_rick():
    """THE b9911943 REPRO, SUPERSEDED BY mini-plan 04 (2026-07-21): the stale
    subject is itself an active manager. It still receives the POKE (addressed to
    it — unchanged), and now NOBODY on the gateway receives the advisory: not the
    subject (the original b9911943 double-delivery) and not the peer (the whole
    fan-out is gone, exactly as f48f089d did to cases 16/17). Rick still gets it."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 2700, persona="Tiberius" ) )
    fired = job._check_manager_staleness( snap, NOW,
                                          active_managers=[ "Tiberius", "OtherMgr" ] )
    assert fired == 1
    # subject DID get the poke (addressed TO the dark manager — correct)
    pokes = _stale_pokes( gw )
    assert len( pokes ) == 1 and pokes[ 0 ][ 0 ] == "Tiberius"
    # ...but NOT the about-itself advisory (the b9911943 double-delivery)
    assert _subject_advisories( gw, "Tiberius", "MANAGER-STALE:" ) == [ ]
    # AC-2: nor did the PEER manager — asserted on the recipient, not on a
    # (recipient, message) tuple, so a message-text edit cannot satisfy it
    assert [ s for s in gw.sent if s[ 0 ] == "OtherMgr" ] == [ ]
    # AC-3: Rick got it exactly once (the flip must not silence the advisory)
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 1


def test_case14_no_gateway_advisory_for_any_persona_key_variant():
    """mini-plan 04 successor to the canonical-key-tolerance receipt: with the peer
    fan-out gone there is no key to match against, so the invariant is stronger —
    NO gateway recipient, in any casing, receives a MANAGER-STALE advisory. The
    canonical-key exclusion itself is still exercised on case 5 by
    test_route_exclude_persona_matches_by_canonical_key (test_arbiter_routing.py),
    where the fan-out is live; it is NOT dead code."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 2700, persona="Tiberius" ) )
    job._check_manager_staleness( snap, NOW, active_managers=[ "tiberius", "OtherMgr" ] )
    # Anchored on the RECIPIENT LIST, not on an advisory-shaped text filter: a
    # filter like `"MANAGER-STALE:" in s[1]` passes VACUOUSLY the moment the
    # advisory is reworded (proven by an adversarial rename probe, 2026-07-21) —
    # it would report "no advisory on the wire" while every peer still got a DM.
    # The only legitimate gateway traffic is the poke, addressed TO the subject.
    assert [ s[ 0 ] for s in gw.sent ] == [ "Tiberius" ]
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 1      # Rick still advised


def test_case16_blocked_advisory_is_rick_only_no_peer_fanout():
    """f48f089d (2026-07-08): a BLOCKED_ON_USER manager's MANAGER-AWAITING-RICK
    advisory routes RICK-ONLY (case 20 twin) — the subject is alive and still OWNS
    its crew, only Rick unblocks it, so NEITHER the subject NOR any peer manager is
    DM'd. Supersedes the b9911943 subject-exclusion shape (the whole manager fan-out
    is gone now, not just the subject); mirrors the case-17 done-advisory flip."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Tiberius" ) )
    fired = job._check_manager_staleness( snap, NOW,
                                          active_managers=[ "Tiberius", "OtherMgr" ],
                                          owed_class={ "Tiberius": CLASS_BLOCKED_ON_USER } )
    assert fired == 0                                          # case 16 emits no poke
    awaiting = _awaiting( escal )
    assert len( awaiting ) == 1                                # one Rick advisory
    assert gw.sent == [ ]                                      # NO manager DM — not the subject, not a peer


def test_case17_done_advisory_is_rick_only_no_peer_fanout():
    """f48f089d (2026-07-08): a DONE manager's MANAGER-DONE advisory routes RICK-ONLY
    (case 20 twin) — its "consider reaping it" directive reaches NEITHER the subject
    NOR any peer manager; only Rick, who actuates the reap. Supersedes the b9911943
    subject-exclusion shape (the whole manager fan-out is gone now, not just the
    subject)."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 3000, persona="Rachel" ) )
    fired = job._check_manager_staleness( snap, NOW,
                                          active_managers=[ "Rachel", "OtherMgr" ],
                                          owed_class={ "Rachel": CLASS_DONE } )
    assert fired == 0
    done = _done_adv( escal )
    assert len( done ) == 1                                       # Rick advised exactly once
    assert gw.sent == [ ]                                         # NO manager DM — not the subject, not a peer


def test_case14_subject_absent_still_no_peer_advisory():
    """mini-plan 04: the shape the old fixtures exercised — subject NOT among
    active_managers, so the b9911943 exclusion drops nobody. Before the flip both
    listed peers were served; now NEITHER is. This is the observed defect Rick
    reported (peer managers interrupted about seats that are not theirs), pinned
    on the multi-peer shape so a partial fan-out cannot slip back in."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "m1", "manager", 2700, persona="Tiberius" ) )
    job._check_manager_staleness( snap, NOW, active_managers=[ "PeerA", "PeerB" ] )
    assert [ s for s in gw.sent if s[ 0 ] in ( "PeerA", "PeerB" ) ] == [ ]
    assert len( [ m for m in escal if "MANAGER-STALE" in m ] ) == 1       # Rick still advised


# ── persona-twin suppression (bug 7c931b3a, 2026-06-27) ──────────────────────
# A RE-SPUN manager leaves its OLD (dead) session row in the include_offline
# snapshot; for ~45 min that ghost's freshest_age sits in [threshold, max_age].
# The poke is PERSONA-addressed, so the ghost's "silent 47m" lands on the LIVE
# twin. Suppress a stale row whose persona is alive on another session_id; a
# persona dark across ALL incarnations is still poked (true-positive preserved).


def _stale_twin_suppressed( logs ):
    return [ r for r in logs if r[ 0 ] == "arbiter_manager_stale_twin_suppressed" ]


def _poke_components( logs ):
    return [ r for r in logs if r[ 0 ] == "arbiter_manager_stale_poke_components" ]


def test_persona_twin_live_suppresses_stale_ghost():
    """The 2026-06-27 mr radio case: a stale DEAD-incarnation manager row whose
    persona is LIVE on a fresh session_id draws NEITHER a poke NOR an advisory —
    the ghost is suppressed and the suppression is logged."""
    gw, escal, logs = _GW(), [ ], [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                 log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    snap = _snap(
        _row( "dead-54622550", "manager", 2820, persona="mr radio" ),   # ghost (stale)
        _row( "live-cd637762", "manager",   10, persona="mr radio" ),   # live twin (fresh)
    )
    fired = job._check_manager_staleness( snap, NOW, active_managers=[ "mr radio" ] )
    assert fired == 0                                              # no poke fired
    assert _stale_pokes( gw ) == [ ]                               # nothing sent to the persona
    assert [ m for m in escal if "MANAGER-STALE" in m ] == [ ]     # no Rick advisory
    sup = _stale_twin_suppressed( logs )
    assert len( sup ) == 1 and sup[ 0 ][ 1 ][ "session_id" ] == "dead-54622550"


def test_persona_twin_live_row_may_be_worker_role():
    """The live-twin liveness scan is ROLE-AGNOSTIC: a fresh row of the same
    persona suppresses the stale ghost even if that fresh row is a worker (a
    re-spun session may surface under either role mid-transition)."""
    gw, logs = _GW(), [ ]
    job  = _job( gw, log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    snap = _snap(
        _row( "ghost", "manager", 3600, persona="Hal" ),     # stale ghost manager
        _row( "live",  "worker",   30, persona="Hal" ),      # fresh same-persona worker
    )
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 0
    assert len( _stale_twin_suppressed( logs ) ) == 1


def test_genuinely_dark_persona_still_poked_no_twin():
    """TRUE-POSITIVE preserved: a stale manager with NO live incarnation anywhere
    is poked exactly as before — suppression only fires for a live twin."""
    gw, logs = _GW(), [ ]
    job  = _job( gw, log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    snap = _snap( _row( "lonely", "manager", 2820, persona="Dot" ) )
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 1     # poked
    assert _stale_twin_suppressed( logs ) == [ ]                   # nothing suppressed


def test_stale_ghost_with_other_persona_live_not_suppressed():
    """Cross-persona safety: a DIFFERENT persona being live does NOT mute an
    unrelated stale manager — suppression is keyed on the SAME persona only."""
    gw = _GW()
    job  = _job( gw )
    snap = _snap(
        _row( "ghost", "manager", 2820, persona="Tiberius" ),   # stale, no live twin
        _row( "live",  "manager",   10, persona="Krishna" ),    # live, UNRELATED persona
    )
    assert job._check_manager_staleness( snap, NOW, [ ] ) == 1    # still poked


def test_real_poke_logs_component_age_breakdown():
    """Observability (Mr Radio's handoff ask): every row we actually poke logs its
    full per-component liveness breakdown so a future false-positive is
    self-diagnosing without re-deriving ages from raw event logs."""
    gw, logs = _GW(), [ ]
    job  = _job( gw, log_fn=lambda e, **k: logs.append( ( e, k ) ) )
    row  = { "session_id": "m1", "persona": "Pat", "state": "working",
             "holding_on": "none", "stuck": False, "role": "manager",
             "liveness": { "freshest_age_s": 2820, "verdict": "stale 47m",
                           "bridge_age_s": 2820, "event_age_s": None,
                           "commons_age_s": 3000, "idle_prompt_age_s": None,
                           "dm_age_s": None, "hold_age_s": 2820 } }
    assert job._check_manager_staleness( _snap( row ), NOW, [ ] ) == 1
    comp = _poke_components( logs )
    assert len( comp ) == 1
    fields = comp[ 0 ][ 1 ]
    assert fields[ "session_id" ] == "m1" and fields[ "event_age_s" ] is None
    assert fields[ "bridge_age_s" ] == 2820 and fields[ "dm_age_s" ] is None


# ── work_owed=false → DONE suppression (bug 25ba173e, 2026-06-29) ─────────────
#    A manager that self-declares work_owed=false in its heartbeat hold is DONE-
#    equivalent even when the STORE still shows a non-terminal ACTIVE item (or
#    reads UNKNOWN) — the 45-min poke-spam repro. _classify_owed folds the hold's
#    declared_work_owed=false into a CLASS_DONE override, in the SAME hold-read
#    loop as the 6929f4ac open-gate override and applied BEFORE it, so an open
#    user-gate (owes a re-ask) still wins. Fail-safe: an unwired seam, a raising
#    reader, or an absent/non-bool work_owed field never suppresses (preserves
#    today's escalation). Spec: src/rnd/v0.1.9/2026.06.29-arbiter-staleness-
#    work-owed-false-fix-plan.md.

from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as _ug


def _active_item():
    """A non-terminal, NON-Rick-gated owed item → classifies CLASS_ACTIVE from the store alone."""
    return { "id": "i1", "status": "in_progress", "gate_class": "none", "blocked_by": None }


def _work_owed_false_hold( **extra ):
    """A heartbeat hold self-declaring work_owed=false (DONE-equivalent), plus any override."""
    hold = { "work_owed": False, "pending_user_gates": [ ] }
    hold.update( extra )
    return hold


def _active_reader( names ):
    return { n: [ _active_item() ] for n in names }


class TestWorkOwedFalseSuppression:

    _FV = { "m1": { "persona": "Krishna" } }       # fleet_view: sid m1 ↔ persona Krishna

    # ── AC1 (RED-first): work_owed=false hold + store ACTIVE → DONE, no case-14 poke ──

    def test_classify_owed_work_owed_false_overrides_active_to_done( self ):
        """CORE FIX: store says ACTIVE (≥1 non-Rick-gated owed item) but the hold
        self-declares work_owed=false ⇒ CLASS_DONE. FAILS on main (store-only ⇒
        ACTIVE — declared_work_owed is never read)."""
        job = _job( hold_reader_fn=lambda sid: _work_owed_false_hold(), owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_DONE }

    def test_work_owed_false_hold_no_case14_poke_one_done_advisory( self ):
        """THE POKE-PATH AC1: a stale manager whose hold says work_owed=false, with a
        STORE showing a live ACTIVE item, draws NO case-14 poke and AT MOST ONE
        case-17 DONE advisory. FAILS on main (store-only ⇒ ACTIVE ⇒ poke fires)."""
        gw, escal = _GW(), [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    hold_reader_fn=lambda sid: _work_owed_false_hold(), owed_work_fn=_active_reader )
        snap       = _snap( _row( "m1", "manager", 3000, persona="Krishna" ) )
        owed_class = job._classify_owed( [ "Krishna" ], self._FV )
        fired = job._check_manager_staleness( snap, NOW, active_managers=[ ], owed_class=owed_class )
        assert fired == 0                                            # no staleness poke
        assert _stale_pokes( gw ) == [ ]                            # nothing sent to the manager
        assert len( _done_adv( escal ) ) == 1                      # exactly ONE case-17 advisory
        assert [ m for m in escal if "MANAGER-STALE" in m ] == [ ]  # NOT the case-14 advisory
        assert "m1" not in job._mgr_stale_since                    # no staleness episode opened
        assert "Krishna" in job._manager_done_advised

    # ── AC2: open-gate precedence — work_owed=false BUT an open user-gate ⇒ ACTIVE ──

    def test_open_gate_beats_work_owed_false( self ):
        """6929f4ac PRESERVED: a work_owed=false hold that ALSO holds an OPEN user-gate
        owes Rick a re-ask → CLASS_ACTIVE. The open-gate override is applied AFTER the
        work_owed→DONE override, so it wins."""
        gate = _ug.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=NOW.isoformat() )
        job  = _job( hold_reader_fn=lambda sid: _work_owed_false_hold( pending_user_gates=[ gate ] ),
                     owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    def test_open_gate_beats_work_owed_false_over_store_done( self ):
        """Same precedence with the store ALSO DONE (zero owed): work_owed=false →
        DONE, then the open gate re-promotes to ACTIVE."""
        gate = _ug.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=NOW.isoformat() )
        job  = _job( hold_reader_fn=lambda sid: _work_owed_false_hold( pending_user_gates=[ gate ] ),
                     owed_work_fn=lambda names: { n: [ ] for n in names } )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    # ── AC3: fail-safe — never silence a real escalation ──────────────────────────

    def test_unwired_seam_no_suppression( self ):
        """No hold-reader wired (default None) → the work_owed override is inert →
        store class (ACTIVE) stands. Byte-identical to today's store-only behavior."""
        job = _job( owed_work_fn=_active_reader )                   # hold_reader_fn defaults to None
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    def test_raising_reader_swallowed_no_suppression( self ):
        """A hold-read hiccup (reader raises) is swallowed → hold None →
        declared_work_owed(None) is None → no override → store class (ACTIVE) stands."""
        def _boom( sid ): raise RuntimeError( "hold read failed" )
        job = _job( hold_reader_fn=_boom, owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    def test_absent_work_owed_no_suppression( self ):
        """A hold with NO work_owed key → declared_work_owed None (not False) → no
        suppression (the field is absent, not a finished-declaration)."""
        job = _job( hold_reader_fn=lambda sid: { "pending_user_gates": [ ] }, owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    def test_non_bool_work_owed_no_suppression( self ):
        """A non-bool work_owed value → declared_work_owed None → no suppression."""
        job = _job( hold_reader_fn=lambda sid: { "work_owed": "yes", "pending_user_gates": [ ] },
                    owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }

    def test_work_owed_true_no_suppression( self ):
        """Only work_owed=false suppresses — an explicit work_owed=true never flips a
        store-ACTIVE classification to DONE."""
        job = _job( hold_reader_fn=lambda sid: _work_owed_false_hold( work_owed=True ),
                    owed_work_fn=_active_reader )
        assert job._classify_owed( [ "Krishna" ], self._FV ) == { "Krishna": CLASS_ACTIVE }


# ── bug 26dd3afb: session-bridge mtime as a MANAGER-STALE veto ───────────────
# The union `freshest_age_s` can read stale even while the manager is
# demonstrably alive (its hooks-driven bridge file was touched seconds ago but
# that mtime never reached the union — sid→bridge resolution gap, or a re-spun
# twin whose live bridge is under a different session_id the live_personas guard
# didn't catch: the 2026-07-02 Tiberius false-positive). A fresh bridge is
# ground-truth liveness → veto the stale tier. Keyed by PERSONA (the always-
# present analog of the sid-keyed union signal). Sibling of the hold-mtime 6th
# signal (a1395315) which Tiberius lacked (no hold file).

from lupin_mcp.persona_normalization import canonical_persona_key


def _bridge_key( persona ):
    return canonical_persona_key( persona ) or persona


def test_fresh_bridge_vetoes_stale_manager():
    """The Tiberius repro: a manager whose UNION age is stale (9000s) but whose
    session-bridge mtime is fresh (60s) is VETOED — no poke, no advisory, no
    episode started. Fresh bridge ⇒ not stale, regardless of comms silence."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "s_tib", "manager", 5000, persona="tiberius" ) )
    bridge_mtimes = { _bridge_key( "tiberius" ): NOW.timestamp() - 60 }   # touched 60s ago → fresh
    fired = job._check_manager_staleness( snap, NOW, [ ], bridge_mtimes=bridge_mtimes )
    assert fired == 0
    assert _stale_pokes( gw ) == [ ]
    assert escal == [ ]
    assert job._mgr_stale_since == { }                                    # episode NOT started


def test_stale_bridge_does_not_veto():
    """A stale bridge (mtime older than the threshold) does NOT veto — the manager
    really is dark on every signal → the case-14 poke + advisory fire as before."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "s_dark", "manager", 5000, persona="tiberius" ) )
    bridge_mtimes = { _bridge_key( "tiberius" ): NOW.timestamp() - 9000 }  # bridge equally stale
    fired = job._check_manager_staleness( snap, NOW, [ ], bridge_mtimes=bridge_mtimes )
    assert fired == 1
    assert len( _stale_pokes( gw ) ) == 1


def test_absent_persona_bridge_does_not_veto():
    """A bridge map that lacks the subject persona (fresh bridge for someone else)
    does NOT veto — the veto is persona-specific."""
    gw = _GW()
    job  = _job( gw )
    snap = _snap( _row( "s_dark", "manager", 5000, persona="tiberius" ) )
    bridge_mtimes = { _bridge_key( "someone_else" ): NOW.timestamp() - 60 }
    fired = job._check_manager_staleness( snap, NOW, [ ], bridge_mtimes=bridge_mtimes )
    assert fired == 1
    assert len( _stale_pokes( gw ) ) == 1


def test_bridge_mtimes_none_is_inert():
    """bridge_mtimes=None (seam unwired / read failed) → veto inert → today's
    behavior (poke fires). This is the fail-safe default."""
    gw = _GW()
    job  = _job( gw )
    snap = _snap( _row( "s_dark", "manager", 5000, persona="tiberius" ) )
    fired = job._check_manager_staleness( snap, NOW, [ ], bridge_mtimes=None )
    assert fired == 1
    assert len( _stale_pokes( gw ) ) == 1


def test_future_bridge_does_not_veto():
    """097778b8: a FUTURE bridge mtime (clock skew/corruption ⇒ negative age) must
    NOT veto — without the 0<=age lower bound a negative age slips under the
    threshold and falsely suppresses a real escalation. Fail toward poking: the
    case-14 poke + advisory fire as if the bridge signal were absent."""
    gw, escal = _GW(), [ ]
    job  = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )
    snap = _snap( _row( "s_dark", "manager", 5000, persona="tiberius" ) )
    bridge_mtimes = { _bridge_key( "tiberius" ): NOW.timestamp() + 60 }   # future mtime → age -60
    fired = job._check_manager_staleness( snap, NOW, [ ], bridge_mtimes=bridge_mtimes )
    assert fired == 1
    assert len( _stale_pokes( gw ) ) == 1


# ── the swallow-safe per-poll reader (mirrors _read_known_owners) ────────────

def test_read_manager_bridge_mtimes_none_when_unwired():
    """Seam unwired (bridge_mtimes_fn=None) → reader returns None (veto inert)."""
    job = _job()
    assert job._read_manager_bridge_mtimes() is None


def test_read_manager_bridge_mtimes_passthrough():
    """A wired reader's map is returned verbatim."""
    m   = { "tiberius": 1234.5 }
    job = _job( bridge_mtimes_fn=lambda: m )
    assert job._read_manager_bridge_mtimes() == m


def test_read_manager_bridge_mtimes_swallows_exception():
    """A read that RAISES is swallowed → None (fail-SAFE: veto never suppresses a
    genuine escalation on an infra hiccup)."""
    def _boom():
        raise RuntimeError( "bridge scan blew up" )
    job = _job( bridge_mtimes_fn=_boom )
    assert job._read_manager_bridge_mtimes() is None


# ── item 285c0343 Lever A: HOLD-GATING (honored awaiting-user hold ⇒ suppress) ──
# The hold-side dual of the owed_class BLOCKED_ON_USER branch. owed_class reads the
# STORE, where the 6929f4ac open-gate override reclassifies an awaiting-user session
# as CLASS_ACTIVE (it owes Rick a re-ask) — so a manager PARKED awaiting Rick's gate
# answer reaches the poke path classed ACTIVE and would draw the case-14 poke (the
# 2026-07-07 episode-2 false positive). Lever A reads the HOLD and suppresses.
#
# RED-first equivalence: each suppression test is PAIRED with its seam-off fail-safe
# (hold_reader_fn=None → main behavior → the SAME scenario POKES). The pair proves the
# new branch is load-bearing (remove it ⇒ revert to poke), stronger than a stash-RED.

from lupin_cli.claude_code.hooks.lib import heartbeat_user_gates as _ug2


def _honored_awaiting_user_hold( awaiting="user:rick", pending_user_gates=None ):
    """A FRESH HONORED hold (is_honored: fresh + reasoned) declaring awaiting:user:*."""
    return { "awaiting": awaiting, "reason": "parked awaiting Rick's gate answer",
             "held_at": NOW.isoformat(), "ttl_seconds": 100000,     # huge → honored across every test's time span
             "work_owed": True, "pending_user_gates": pending_user_gates or [ ] }


def _await_sup_logs( logs ):
    return [ ( ev, f ) for ev, f in logs if ev == "arbiter_manager_stale_suppressed_awaiting_user_hold" ]


class TestLeverA_AwaitingUserHoldGating:

    def test_awaiting_user_hold_suppresses_case14_poke( self ):
        """CORE (RED on main — main never calls _session_awaiting_user in the staleness
        poke path): honored awaiting:user:rick hold + owed_class ACTIVE ⇒ ZERO pokes,
        exactly ONE case-16 MANAGER-AWAITING-RICK advisory, distinct suppression log."""
        gw, escal, logs = _GW(), [ ], [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    log_fn=lambda ev, **k: logs.append( ( ev, k ) ),
                    hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        snap  = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
        fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                              owed_class={ "mr radio": CLASS_ACTIVE } )
        assert fired == 0                                       # Lever A suppressed the case-14 poke
        assert _stale_pokes( gw ) == [ ]
        assert len( _awaiting( escal ) ) == 1                  # ONE case-16 advisory
        assert [ m for m in escal if "MANAGER-STALE" in m ] == [ ]   # NOT the case-14 advisory
        assert "m1" not in job._mgr_stale_since                # no staleness episode opened
        assert "mr radio" in job._manager_blocked_advised
        assert len( _await_sup_logs( logs ) ) == 1             # distinct, observable
        assert _await_sup_logs( logs )[ 0 ][ 1 ][ "awaiting" ] == "user:rick"   # Q1 rider: awaiting stamped

    def test_awaiting_user_hold_advisory_is_rick_only_no_peer_fanout( self ):
        """f48f089d (2026-07-08): the hold-gate (~line 4159) case-16 emitter is
        RICK-ONLY too — with a PEER manager present in active_managers, an honored
        awaiting-user hold advises Rick ONCE and DMs NO peer (the whole manager
        fan-out is gone, mirror case 20). Distinguishes the flip from the empty-
        active_managers Lever-A cases above, which are peer-silent only by vacuity;
        here a real peer is offered and still gets nothing. RED on pre-flip routing:
        gw.sent == [("OtherMgr", <awaiting body>)]."""
        gw, escal = _GW(), [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        snap  = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
        fired = job._check_manager_staleness( snap, NOW,
                                              active_managers=[ "OtherMgr", "mr radio" ],
                                              owed_class={ "mr radio": CLASS_ACTIVE } )
        assert fired == 0
        assert len( _awaiting( escal ) ) == 1                  # Rick advised exactly once
        assert gw.sent == [ ]                                  # NO peer DM (case 20 twin)

    def test_seam_off_same_scenario_still_pokes( self ):
        """FAIL-SAFE / RED-equivalence: hold_reader_fn=None (main behavior) → Lever A
        inert → the SAME awaiting-user scenario draws the case-14 poke. Proves the
        branch is load-bearing."""
        gw, escal = _GW(), [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ) )   # hold_reader_fn defaults None
        snap  = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
        fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                              owed_class={ "mr radio": CLASS_ACTIVE } )
        assert fired == 1 and len( _stale_pokes( gw ) ) == 1   # pokes without the hold read

    def test_open_gate_hold_suppresses_and_stamps_next_chase( self ):
        """The open-gate branch of _session_awaiting_user (no awaiting str, ≥1 OPEN
        user-gate) also suppresses — and the Q1-rider log carries the soonest
        next_chase_ts. Covers the defer_to_chase cadence transitively (an open gate on
        a future next_chase_ts is still OPEN)."""
        soon = "2026-06-11T19:30:00+00:00"
        late = "2026-06-11T20:30:00+00:00"
        g1   = _ug2.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=NOW.isoformat(),
                               next_chase_ts=late )
        g2   = _ug2.make_gate( "g2", "Deploy?",  "ask_yes_no", last_asked_ts=NOW.isoformat(),
                               next_chase_ts=soon )
        gw, escal, logs = _GW(), [ ], [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    log_fn=lambda ev, **k: logs.append( ( ev, k ) ),
                    hold_reader_fn=lambda sid: _honored_awaiting_user_hold(
                        awaiting="peer:cheech", pending_user_gates=[ g1, g2 ] ) )
        snap  = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
        fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                              owed_class={ "mr radio": CLASS_ACTIVE } )
        assert fired == 0 and _stale_pokes( gw ) == [ ]
        assert _await_sup_logs( logs )[ 0 ][ 1 ][ "soonest_next_chase_ts" ] == soon   # earliest chosen

    def test_awaiting_user_hold_rearms_after_freshen( self ):
        """Re-arm: the SHARED _manager_blocked_advised flag clears when the manager
        freshens below threshold (leaves eligible), so a LATER awaiting-user episode
        re-advises once (mirrors the BLOCKED_ON_USER re-arm)."""
        gw, escal = _GW(), [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        oc  = { "mr radio": CLASS_ACTIVE }
        job._check_manager_staleness( _snap( _row( "m1", "manager", 3000, persona="mr radio" ) ),
                                      NOW, active_managers=[ ], owed_class=oc )
        assert len( _awaiting( escal ) ) == 1
        # freshen: a sub-threshold row clears the suppression bookkeeping
        job._check_manager_staleness( _snap( _row( "m1", "manager", 100, persona="mr radio" ) ),
                                      NOW, active_managers=[ ], owed_class=oc )
        assert "mr radio" not in job._manager_blocked_advised
        # a later stale episode re-advises
        job._check_manager_staleness( _snap( _row( "m1", "manager", 3000, persona="mr radio" ) ),
                                      NOW, active_managers=[ ], owed_class=oc )
        assert len( _awaiting( escal ) ) == 2

    def test_expired_hold_falls_through_lever_a( self ):
        """LAYERED PAIR (Tiberius rider): an EXPIRED hold (is_honored=False: stale
        held_at) is NOT defended by Lever A → falls THROUGH to the poke path (here,
        with velocity off, it pokes). This is the class today's hook-side 9-FP fix
        targets; the arbiter hands it to Lever B, not Lever A."""
        gw, escal = _GW(), [ ]
        expired = { "awaiting": "user:rick", "reason": "parked",
                    "held_at": "2026-06-11T10:00:00+00:00", "ttl_seconds": 60,   # long expired at NOW=18:00
                    "work_owed": True, "pending_user_gates": [ ] }
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    manager_stale_velocity_suppress_streak=0,          # isolate Lever A
                    hold_reader_fn=lambda sid: expired )
        snap  = _snap( _row( "m1", "manager", 3000, persona="mr radio" ) )
        fired = job._check_manager_staleness( snap, NOW, active_managers=[ ],
                                              owed_class={ "mr radio": CLASS_ACTIVE } )
        assert fired == 1 and len( _stale_pokes( gw ) ) == 1   # not honored → not suppressed by A

    def test_awaiting_user_hold_facets_swallows_raising_reader( self ):
        """_awaiting_user_hold_facets is best-effort: a raising reader → {} (the
        suppression still fires elsewhere; the log row just omits facets)."""
        def _boom( sid ): raise RuntimeError( "hold read failed" )
        job = _job( hold_reader_fn=_boom )
        assert job._awaiting_user_hold_facets( "m1" ) == { }

    def test_awaiting_user_hold_facets_unwired_and_non_dict( self ):
        """Facets helper: unwired seam → {}; a non-dict hold → {}."""
        assert _job()._awaiting_user_hold_facets( "m1" ) == { }        # hold_reader_fn None
        job = _job( hold_reader_fn=lambda sid: "not-a-dict" )
        assert job._awaiting_user_hold_facets( "m1" ) == { }

    def test_awaiting_user_hold_facets_unparseable_next_chase_falls_back( self ):
        """Q1 rider robustness: an unparseable next_chase_ts → fall back to the first
        stamp (never raises), and a hold with no awaiting str omits that key."""
        g = _ug2.make_gate( "g1", "Proceed?", "ask_yes_no", last_asked_ts=NOW.isoformat(),
                            next_chase_ts="not-an-iso-stamp" )
        job = _job( hold_reader_fn=lambda sid: { "reason": "x", "held_at": NOW.isoformat(),
                                                 "ttl_seconds": 7200, "pending_user_gates": [ g ] } )
        facets = job._awaiting_user_hold_facets( "m1" )
        assert facets == { "soonest_next_chase_ts": "not-an-iso-stamp" }   # no awaiting key; fallback stamp


# ── item 285c0343 Lever B: LAST-SIGNAL VELOCITY (N advancing episodes ⇒ suppress) ──

def _velocity_sup_logs( logs ):
    return [ ( ev, f ) for ev, f in logs if ev == "arbiter_manager_stale_suppressed_velocity" ]


def test_negative_velocity_streak_raises():
    """Config guard: a negative velocity-suppress streak is a config bug → ValueError."""
    with pytest.raises( ValueError, match="manager_stale_velocity_suppress_streak" ):
        _job( manager_stale_velocity_suppress_streak=-1 )


class TestLeverB_LastSignalVelocity:

    _OC = { "mr radio": CLASS_ACTIVE }

    def _episode( self, job, gw, at_epoch_min ):
        """Drive one stale episode at a wall-clock `at_epoch_min` minutes past NOW with a
        fixed 3000s age (so last_seen = that-instant − 3000 ADVANCES each episode), then
        freshen to close the episode. Returns pokes fired on the stale poll."""
        t_stale = NOW + datetime.timedelta( minutes=at_epoch_min )
        before  = len( _stale_pokes( gw ) )
        fired   = job._check_manager_staleness( _snap( _row( "m1", "manager", 3000, persona="mr radio" ) ),
                                                t_stale, active_managers=[ ], owed_class=self._OC )
        # freshen (sub-threshold) at +1min → clears the per-sid episode so the next call re-opens one
        job._check_manager_staleness( _snap( _row( "m1", "manager", 100, persona="mr radio" ) ),
                                      t_stale + datetime.timedelta( minutes=1 ), active_managers=[ ], owed_class=self._OC )
        return fired, len( _stale_pokes( gw ) ) - before

    def test_third_advancing_episode_suppressed( self ):
        """CORE (RED on main — main has no velocity memory): three episodes whose
        last-signal ADVANCES each time → ep1 pokes, ep2 pokes, ep3 SUPPRESSED with a
        distinct velocity log carrying advancing_streak>=2 (the mr radio 13:08→13:59→
        14:59 cadence)."""
        gw, logs = _GW(), [ ]
        job = _job( gw, log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )   # default streak=2
        f1, _ = self._episode( job, gw, 0 )     # last_seen ≈ NOW-3000
        f2, _ = self._episode( job, gw, 60 )    # advanced ~1h → streak 1
        f3, s3 = self._episode( job, gw, 120 )  # advanced ~1h → streak 2 ⇒ suppress
        assert f1 == 1 and f2 == 1              # first two episodes poke
        assert f3 == 0 and s3 == 0              # third suppressed (no poke sent)
        assert len( _velocity_sup_logs( logs ) ) == 1
        assert _velocity_sup_logs( logs )[ 0 ][ 1 ][ "advancing_streak" ] >= 2

    def test_streak_zero_disables_lever( self ):
        """manager_stale_velocity_suppress_streak=0 → the lever is OFF → even a long
        advancing run keeps poking (RED-equivalence: turning the knob to 0 reverts to
        main behavior)."""
        gw, logs = _GW(), [ ]
        job = _job( gw, manager_stale_velocity_suppress_streak=0,
                    log_fn=lambda ev, **k: logs.append( ( ev, k ) ) )
        f1, _ = self._episode( job, gw, 0 )
        f2, _ = self._episode( job, gw, 60 )
        f3, _ = self._episode( job, gw, 120 )
        assert ( f1, f2, f3 ) == ( 1, 1, 1 )
        assert _velocity_sup_logs( logs ) == [ ]

    def test_non_advancing_episode_resets_streak_and_pokes( self ):
        """A FROZEN last-signal (genuinely wedged) RESETS the streak → the real-stall
        true positive still pokes. Drive two advancing episodes (streak→1) then an
        episode whose last-signal did NOT advance (same instant math) → reset → poke."""
        gw = _GW()
        job = _job( gw )   # streak=2
        self._episode( job, gw, 0 )       # ep1
        self._episode( job, gw, 60 )      # ep2 advanced → streak 1
        # ep3 with a LARGER age so last_seen does NOT advance vs ep2:
        # ep2 last_seen ≈ (NOW+60m) − 3000s; make ep3 last_seen == that by pairing now/age.
        t3   = NOW + datetime.timedelta( minutes=120 )
        # choose age so t3 - age <= ep2 last_seen (NOW+60m-3000s): age = 120m-60m + 3000s = 6600s (< max 7200)
        before = len( _stale_pokes( gw ) )
        fired  = job._check_manager_staleness( _snap( _row( "m1", "manager", 6600, persona="mr radio" ) ),
                                               t3, active_managers=[ ], owed_class=self._OC )
        assert fired == 1 and len( _stale_pokes( gw ) ) - before == 1   # frozen last-signal → pokes

    def test_first_episode_always_pokes( self ):
        """Q3 (intended): the FIRST quiet episode has no prior → streak 0 → pokes. A
        manager that just went quiet once is caught on ep1, never never."""
        gw = _GW()
        job = _job( gw )
        f1, _ = self._episode( job, gw, 0 )
        assert f1 == 1

    def test_lever_a_wins_over_velocity_when_both_apply( self ):
        """ORDERING: a manager BOTH awaiting-user AND on an advancing cadence → Lever A
        (honored hold) suppresses FIRST via the case-16 path and NEVER perturbs the
        velocity streak (no velocity log; streak stays 0)."""
        gw, escal, logs = _GW(), [ ], [ ]
        job = _job( gw, notify=lambda m, *a, **k: escal.append( m ),
                    log_fn=lambda ev, **k: logs.append( ( ev, k ) ),
                    hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        for mins in ( 0, 60, 120 ):
            job._check_manager_staleness( _snap( _row( "m1", "manager", 3000, persona="mr radio" ) ),
                                          NOW + datetime.timedelta( minutes=mins ),
                                          active_managers=[ ], owed_class=self._OC )
        assert _stale_pokes( gw ) == [ ]                       # never poked
        assert _velocity_sup_logs( logs ) == [ ]               # velocity never engaged
        assert job._mgr_velocity_streak.get( "mr radio", 0 ) == 0
        assert len( _await_sup_logs( logs ) ) == 3             # A suppressed every episode


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
