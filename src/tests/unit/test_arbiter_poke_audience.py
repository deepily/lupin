#!/usr/bin/env python3
"""
AUDIENCE SCALPEL receipts (Rick via María, 2026-07-19) — the three audience-scoped
poke gates under the `auto_poke_enabled` master.

Rick's ask, verbatim in shape: silence workers + managers while STILL receiving his
own pokes. So these tests exercise the ROUTING PREDICATE and the EMISSION PATHS it
gates, not merely the config loader:

  • PREDICATE  — audience_for_role() derivation + _poke_audience_enabled() AND-gate,
    including the master-overrides-everything law and the unknown-audience
    fail-SILENT default.
  • STUCK TIER — a worker poke dies on workers-off; a manager poke dies on
    managers-off; each is INDEPENDENT (silencing one never silences the other).
  • STALE TIER — the manager-DIRECTED staleness poke dies on managers-off while
    Rick's case-14 MANAGER-STALE advisory SURVIVES (the whole point of the split).
  • MASTER HOLE — the regression that motivated this build: before 2026-07-19 the
    staleness tier read only its own threshold, so `auto_poke enabled = false`
    silenced the stuck tier while manager-staleness pokes kept firing. The master
    is now genuinely master across BOTH tiers.
  • TELEMETRY  — `audience_disabled` is reported DISTINCTLY from the master's
    `disabled`, so an outreach silence names which knob caused it.

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
    AUDIENCE_WORKER, AUDIENCE_MANAGER, AUDIENCE_OPERATOR,
)


NOW = datetime.datetime( 2026, 7, 19, 0, 0, 0, tzinfo=datetime.timezone.utc )


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


def _stuck_view( sid="s1", persona="Stuckie", role="worker" ):
    """A LIVE+stuck session of the given role — the stuck tier's pokeable shape."""
    return { sid: { "session_id": sid, "persona": persona, "state": "stuck",
                    "stuck": True, "holding_on": "none", "alive": True,
                    "role": role } }


def _stale_snapshot( sid="m1", persona="DarkMgr", age=4000 ):
    """A manager row gone dark past threshold but inside the corpse ceiling."""
    return { "sessions": [ { "session_id": sid, "persona": persona, "role": "manager",
                             "liveness": { "freshest_age_s": age } } ] }


def _pokes( gw ):
    """Stuck-tier wake-nudges only (the reap-rec also says 'auto-poke(s)')."""
    return [ s for s in gw.sent if "you appear STUCK" in s[ 1 ] ]


def _stale_pokes( gw ):
    # Match the POKE's own wording ("manager-staleness poke", body: "no signal from
    # your session"). NOT "silent" — that word lives in the case-14 ADVISORY, which
    # goes to notify_fn, never to the gateway. An advisory-shaped filter here made
    # the managers-off test pass VACUOUSLY (empty list either way): a guard that
    # could not fail. Anchored on the poke to keep it able to fail.
    return [ s for s in gw.sent if "manager-staleness poke" in s[ 1 ] ]


def _advisories( notes ):
    return [ n for n in notes if "MANAGER-STALE" in n ]


# ── THE PREDICATE ────────────────────────────────────────────────────────────

@pytest.mark.parametrize( "role,expected", [
    ( "manager",   AUDIENCE_MANAGER ),
    ( "Manager",   AUDIENCE_MANAGER ),   # case-insensitive
    ( "  MANAGER ", AUDIENCE_MANAGER ),  # space-tolerant
    ( "worker",    AUDIENCE_WORKER ),
    ( "",          AUDIENCE_WORKER ),
    ( None,        AUDIENCE_WORKER ),    # unknown role is a WORKER, never a manager
    ( "junk",      AUDIENCE_WORKER ),
] )
def test_audience_for_role_derivation( role, expected ):
    """Audience derives from the target's role, matching _append_goal_line's fork."""
    assert ArbiterConsumerJob.audience_for_role( role ) == expected


@pytest.mark.parametrize( "audience", [ AUDIENCE_WORKER, AUDIENCE_MANAGER, AUDIENCE_OPERATOR ] )
def test_master_off_silences_every_audience( audience ):
    """THE PANIC BUTTON: master off ⇒ all silent, whatever the audience flags say."""
    job = _job( auto_poke_enabled=False, poke_workers_enabled=True,
                poke_managers_enabled=True, poke_operator_enabled=True )
    assert job._poke_audience_enabled( audience ) is False


@pytest.mark.parametrize( "audience,flags,expected", [
    ( AUDIENCE_WORKER,   dict( poke_workers_enabled=True  ), True  ),
    ( AUDIENCE_WORKER,   dict( poke_workers_enabled=False ), False ),
    ( AUDIENCE_MANAGER,  dict( poke_managers_enabled=True  ), True  ),
    ( AUDIENCE_MANAGER,  dict( poke_managers_enabled=False ), False ),
    ( AUDIENCE_OPERATOR, dict( poke_operator_enabled=True  ), True  ),
    ( AUDIENCE_OPERATOR, dict( poke_operator_enabled=False ), False ),
] )
def test_audience_gate_under_live_master( audience, flags, expected ):
    """Master on ⇒ each audience answers for itself."""
    job = _job( auto_poke_enabled=True, **flags )
    assert job._poke_audience_enabled( audience ) is expected


def test_rick_configuration_workers_and_managers_off_operator_on():
    """Rick's exact ask: crew silent, his own stream live."""
    job = _job( auto_poke_enabled=True, poke_workers_enabled=False,
                poke_managers_enabled=False, poke_operator_enabled=True )
    assert job._poke_audience_enabled( AUDIENCE_WORKER )   is False
    assert job._poke_audience_enabled( AUDIENCE_MANAGER )  is False
    assert job._poke_audience_enabled( AUDIENCE_OPERATOR ) is True


def test_unknown_audience_fails_silent():
    """An unrecognized audience must never become an unscoped poke channel."""
    job = _job( auto_poke_enabled=True )
    assert job._poke_audience_enabled( "nobody" )  is False
    assert job._poke_audience_enabled( None )      is False


def test_defaults_are_behavior_neutral():
    """Unconfigured ⇒ every audience enabled ⇒ byte-identical to pre-2026-07-19."""
    job = _job()
    assert job.poke_workers_enabled  is True
    assert job.poke_managers_enabled is True
    assert job.poke_operator_enabled is True


# ── STUCK TIER: worker + manager audiences are INDEPENDENT ───────────────────

def test_stuck_worker_poked_when_workers_enabled():
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, poke_workers_enabled=True )
    assert job._auto_poke( _stuck_view( role="worker" ), NOW, active_managers=[ ] ) == 1
    assert len( _pokes( gw ) ) == 1


def test_stuck_worker_silenced_when_workers_disabled():
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, poke_workers_enabled=False )
    for k in range( 5 ):
        assert job._auto_poke( _stuck_view( role="worker" ),
                               NOW + datetime.timedelta( seconds=k * 100 ), [ ] ) == 0
    assert _pokes( gw ) == [ ]


def test_stuck_manager_silenced_when_managers_disabled():
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, poke_managers_enabled=False )
    for k in range( 5 ):
        assert job._auto_poke( _stuck_view( role="manager" ),
                               NOW + datetime.timedelta( seconds=k * 100 ), [ ] ) == 0
    assert _pokes( gw ) == [ ]


def test_audiences_are_independent_workers_off_managers_on():
    """Silencing workers must NOT silence managers — the scalpel cuts one way only."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0,
                poke_workers_enabled=False, poke_managers_enabled=True )
    assert job._auto_poke( _stuck_view( "w1", "Worker", role="worker" ), NOW, [ ] ) == 0
    assert job._auto_poke( _stuck_view( "m1", "Mgr",    role="manager" ), NOW, [ ] ) == 1
    assert [ p[ 0 ] for p in _pokes( gw ) ] == [ "Mgr" ]


def test_audiences_are_independent_managers_off_workers_on():
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0,
                poke_workers_enabled=True, poke_managers_enabled=False )
    assert job._auto_poke( _stuck_view( "m1", "Mgr",    role="manager" ), NOW, [ ] ) == 0
    assert job._auto_poke( _stuck_view( "w1", "Worker", role="worker" ), NOW, [ ] ) == 1
    assert [ p[ 0 ] for p in _pokes( gw ) ] == [ "Worker" ]


def test_silenced_session_episode_state_is_clean():
    """A silenced session leaves no episode residue — re-enabling mid-episode is
    clean (the cap re-arms, exactly as a recovery would)."""
    gw  = _GW()
    job = _job( gw, poke_stall_threshold_seconds=0, poke_workers_enabled=False )
    job._auto_poke( _stuck_view( "w1", role="worker" ), NOW, [ ] )
    assert "w1" not in job._poke_stuck_since
    assert job._poke_count.get( "w1", 0 ) == 0


# ── STALE TIER: the manager/operator SPLIT ───────────────────────────────────

def test_stale_poke_and_advisory_both_fire_by_default():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=lambda m, **k: notes.append( m ) )
    job._check_manager_staleness( _stale_snapshot(), NOW, active_managers=[ ] )
    assert len( _stale_pokes( gw ) ) == 1
    assert len( _advisories( notes ) ) == 1


def test_managers_off_silences_stale_poke_but_KEEPS_rick_advisory():
    """THE POINT OF THE SPLIT: silencing the crew never blinds Rick to a dark
    manager. The manager-DIRECTED poke dies; the case-14 advisory survives."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=lambda m, **k: notes.append( m ),
                poke_managers_enabled=False, poke_operator_enabled=True )
    job._check_manager_staleness( _stale_snapshot(), NOW, active_managers=[ ] )
    assert _stale_pokes( gw ) == [ ]          # crew: silent
    assert len( _advisories( notes ) ) == 1   # Rick: still told


def test_operator_off_silences_rick_advisory():
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=lambda m, **k: notes.append( m ),
                poke_operator_enabled=False )
    job._check_manager_staleness( _stale_snapshot(), NOW, active_managers=[ ] )
    assert _advisories( notes ) == [ ]


# ── THE MASTER-GATE HOLE (regression) ────────────────────────────────────────

def test_master_off_silences_the_STALENESS_tier_too():
    """REGRESSION, bug closed 2026-07-19: the staleness tier read ONLY its own
    threshold, so `auto poke enabled = false` left manager-staleness pokes firing
    while the stuck tier went quiet — the 'master gate' was never master. Both
    tiers now honor it."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=lambda m, **k: notes.append( m ), auto_poke_enabled=False )
    assert job._check_manager_staleness( _stale_snapshot(), NOW, active_managers=[ ] ) == 0
    assert _stale_pokes( gw ) == [ ]
    assert _advisories( notes ) == [ ]


def test_master_off_silences_both_tiers_together():
    """The panic button, end to end: neither tier emits anything."""
    gw, notes = _GW(), [ ]
    job = _job( gw, notify=lambda m, **k: notes.append( m ),
                auto_poke_enabled=False, poke_stall_threshold_seconds=0 )
    assert job._auto_poke( _stuck_view( role="worker" ), NOW, [ ] ) == 0
    assert job._auto_poke( _stuck_view( "m1", "Mgr", role="manager" ), NOW, [ ] ) == 0
    assert job._check_manager_staleness( _stale_snapshot(), NOW, active_managers=[ ] ) == 0
    assert gw.sent == [ ] and notes == [ ]


# ── TELEMETRY: which knob caused the silence? ────────────────────────────────

def test_gate_vector_distinguishes_master_from_audience():
    """`disabled` (master) and `audience_disabled` (this audience) stay DISTINCT —
    an outreach silence must name its cause."""
    view = _stuck_view( "w1", role="worker" )[ "w1" ]

    master_off = _job( auto_poke_enabled=False )
    assert "disabled" in master_off._stuck_gate_why_not( "w1", view, NOW )
    assert "audience_disabled" not in master_off._stuck_gate_why_not( "w1", view, NOW )

    audience_off = _job( auto_poke_enabled=True, poke_workers_enabled=False )
    why = audience_off._stuck_gate_why_not( "w1", view, NOW )
    assert "audience_disabled" in why and "disabled" not in why


def test_stale_gate_vector_reports_audience_disabled():
    row = _stale_snapshot()[ "sessions" ][ 0 ]
    job = _job( auto_poke_enabled=True, poke_managers_enabled=False )
    assert "audience_disabled" in job._stale_gate_why_not( "m1", row )


def test_gate_vectors_clean_when_everything_enabled():
    """No false gate reasons on a fully-enabled arbiter."""
    view = _stuck_view( "w1", role="worker" )[ "w1" ]
    job  = _job( poke_stall_threshold_seconds=0 )
    why  = job._stuck_gate_why_not( "w1", view, NOW )
    assert "disabled" not in why and "audience_disabled" not in why
