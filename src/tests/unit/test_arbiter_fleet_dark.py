#!/usr/bin/env python3
"""
Post-game F3 receipts (2026-06-11) — the fleet-dark advisory (hybrid trigger).

The 2026-06-10 failure: the roster decayed 4→3→2→1→0 (16:30–17:05 EDT) and the
arbiter ticked "no changes · 0 session(s)" for 6+ hours — full-fleet death was
silence BY DESIGN (the stall detector requires LIVE owed work). F3 receipts:
  • EDGE — published count >0 → 0 fires ONE Rick-only advisory naming the last
    manager seen; no re-fire while dark; re-arms after repopulation.
  • RECOVERY (Tiberius NIT-1) — a boot/recycle straight into count==0 fires iff
    some session still shows a signal within DARK_LOOKBACK_SECONDS ("the fleet
    JUST died"); a cold morning boot over last evening's reaped roster (no
    signal that fresh) stays SILENT — no daily page.
  • The recovery arm is OFF once any nonzero roster has been seen this process.

Venue: :7999-eligible / local — pure + mocked.
Design: src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §3.3.
"""
import datetime
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import ArbiterConsumerJob, DARK_LOOKBACK_SECONDS


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


def _row( sid, role="worker", age=120, persona=None ):
    return { "session_id": sid, "persona": persona or sid, "state": "working",
             "holding_on": "none", "stuck": False, "role": role,
             "liveness": { "freshest_age_s": age, "verdict": "stale 45m" } }


def _snap( *rows ):
    return { "generated_at": NOW.isoformat(), "session_count": len( rows ),
             "sessions": list( rows ) }


# ── the edge arm: >0 → 0 fires once, re-arms on repopulation ─────────────────

def test_edge_decay_to_zero_fires_once_with_last_manager_seen():
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    live = _snap( _row( "m1", role="manager", age=300, persona="Tiberius" ), _row( "w1" ) )
    dark = _snap( _row( "m1", role="manager", age=4000, persona="Tiberius" ) )   # offline rows linger in FULL snap
    assert job._check_fleet_dark( live, 2, NOW ) == 0                    # roster alive
    assert job._check_fleet_dark( dark, 0, NOW + datetime.timedelta( seconds=60 ) ) == 1   # the edge
    darks = [ m for m in escal if "FLEET-DARK" in m ]
    assert len( darks ) == 1
    assert "2→0" in darks[ 0 ] and "Tiberius" in darks[ 0 ]
    assert "EDT" in darks[ 0 ] or "EST" in darks[ 0 ]                    # EDT-labeled wall time
    # still dark → silence (once per dark episode)
    assert job._check_fleet_dark( dark, 0, NOW + datetime.timedelta( seconds=120 ) ) == 0
    assert len( [ m for m in escal if "FLEET-DARK" in m ] ) == 1


def test_rearm_after_repopulation_fires_again_on_next_decay():
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    live = _snap( _row( "w1" ) )
    dark = _snap()
    job._check_fleet_dark( live, 1, NOW )
    assert job._check_fleet_dark( dark, 0, NOW + datetime.timedelta( seconds=60 ) ) == 1
    job._check_fleet_dark( live, 1, NOW + datetime.timedelta( seconds=120 ) )       # repopulated → re-arm
    assert job._check_fleet_dark( dark, 0, NOW + datetime.timedelta( seconds=180 ) ) == 1
    assert len( [ m for m in escal if "FLEET-DARK" in m ] ) == 2


def test_no_manager_ever_seen_reports_unknown():
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    job._check_fleet_dark( _snap( _row( "w1" ) ), 1, NOW )               # workers only
    assert job._check_fleet_dark( _snap(), 0, NOW + datetime.timedelta( seconds=60 ) ) == 1
    assert "unknown" in [ m for m in escal if "FLEET-DARK" in m ][ 0 ]


# ── the recovery arm (NIT-1): boot-into-dark fires iff corpses are FRESH ─────

def test_boot_into_dark_with_recent_corpse_fires_once():
    """RECOVERY: a restart mid-darkness (no >0 edge this process) still alerts
    Rick — some session's signal is within the 2h lookback ("just died")."""
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    corpse = _snap( _row( "m1", role="manager", age=DARK_LOOKBACK_SECONDS - 100, persona="Tiberius" ) )
    assert job._check_fleet_dark( corpse, 0, NOW ) == 1                  # first poll, prev None → recovery
    darks = [ m for m in escal if "FLEET-DARK" in m ]
    assert len( darks ) == 1 and "at startup" in darks[ 0 ] and "Tiberius" in darks[ 0 ]
    # at most once per process
    assert job._check_fleet_dark( corpse, 0, NOW + datetime.timedelta( seconds=60 ) ) == 0


def test_cold_morning_boot_over_old_corpses_is_silent():
    """NO DAILY PAGE (Tiberius's flagged failure mode): a cold boot over a roster
    reaped the previous evening — every signal older than the lookback — is silent."""
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    morning = _snap( _row( "m1", role="manager", age=DARK_LOOKBACK_SECONDS + 1, persona="Tiberius" ) )
    for k in range( 3 ):
        assert job._check_fleet_dark( morning, 0, NOW + datetime.timedelta( seconds=k * 60 ) ) == 0
    assert escal == [ ]


def test_boot_into_truly_empty_fleet_is_silent():
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    assert job._check_fleet_dark( _snap(), 0, NOW ) == 0                 # no rows, no corpses
    assert job._check_fleet_dark( None, 0, NOW ) == 0                    # falsy snapshot safe
    assert escal == [ ]


def test_recovery_arm_off_after_any_nonzero_roster():
    """Once a nonzero roster was seen, only the EDGE can fire — the recovery
    state-check never re-evaluates (prevents corpse-age flapping re-fires)."""
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    job._check_fleet_dark( _snap( _row( "w1" ) ), 1, NOW )               # saw nonzero
    # contrive: prev becomes 0 without an edge ever firing (count 0 with prev 0)
    job._published_count_prev = 0
    fresh_corpse = _snap( _row( "w1", age=60 ) )
    assert job._check_fleet_dark( fresh_corpse, 0, NOW + datetime.timedelta( seconds=60 ) ) == 0
    assert escal == [ ]


def test_malformed_rows_ignored_in_harvest_and_recovery():
    escal = [ ]
    job = _job( notify=lambda m, *a, **k: escal.append( m ) )
    snap = { "sessions": [ "not-a-dict",
                           { "session_id": "m1", "role": "manager", "liveness": "bad" },
                           { "session_id": "m2", "role": "manager",
                             "liveness": { "freshest_age_s": None } } ] }
    assert job._check_fleet_dark( snap, 0, NOW ) == 0                    # no usable recent signal
    assert escal == [ ]


def test_manager_seen_tracks_freshest_across_polls():
    job = _job()
    job._check_fleet_dark( _snap( _row( "m1", role="manager", age=600, persona="Old" ) ), 1, NOW )
    assert job._last_manager_seen[ "persona" ] == "Old"
    later = NOW + datetime.timedelta( seconds=60 )
    job._check_fleet_dark( _snap( _row( "m2", role="manager", age=30, persona="Fresh" ) ), 1, later )
    assert job._last_manager_seen[ "persona" ] == "Fresh"                # fresher signal wins
    # an OLDER signal never regresses the high-water mark
    even_later = NOW + datetime.timedelta( seconds=120 )
    job._check_fleet_dark( _snap( _row( "m3", role="manager", age=9000, persona="Ancient" ) ), 1, even_later )
    assert job._last_manager_seen[ "persona" ] == "Fresh"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
