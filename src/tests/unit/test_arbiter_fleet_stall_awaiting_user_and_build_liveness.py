#!/usr/bin/env python3
"""
Unit tests for bug 423f04a5 — the WHOLE-FLEET-STALL (#11) false-positive, a
sibling of today's arbiter false-positive family (262c59f6 + a6f4929d).

Two facets, both RED-first here:

  FACET 1 — a session on a DEFENDED awaiting-user hold is correctly PARKED on
  Rick, NOT stalled. `_check_fleet_stall` must exclude it from the owed/stalled
  set (via `_session_awaiting_user`) — the 6929f4ac open-gate override
  reclassifies an awaiting-user session as CLASS_ACTIVE in owed_class, so the
  store classification cannot see this state; the truth lives in the hold.

  FACET 2 — an actively-BUILDING fleet holding its commits (bridge-mtime bumps,
  DMs, hold-refreshes, but zero task-store writes in the window) reads as "no
  progress" under the frozen semantic signature. `_fleet_has_recent_build_liveness`
  credits recent bridge(build)/dm/hold-refresh activity as fleet progress before
  declaring a stall — DELIBERATELY excluding commons/idle_prompt/event so the
  chatty-but-stuck blind spot stays CLOSED.

Redline held: the detector only OBSERVES/advises — these tests assert the
escalation COUNT, never any actuation.
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


NOW    = datetime.datetime( 2026, 7, 1, 13, 46, 0, tzinfo=datetime.timezone.utc )
WINDOW = 1800
LATE   = NOW + datetime.timedelta( seconds=WINDOW + 100 )
# A liveness timestamp that is RECENT as of the LATE stall-check (age 60s < window)
# — models a fleet still actively DMing/building at the moment the stall is evaluated.
RECENT = LATE - datetime.timedelta( seconds=60 )


class _GW:
    """Minimal commons gateway — the stall path never reads it."""
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b, metadata=None ): pass
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


def _job( *, notify=None, hold_reader_fn=None, bridge_mtime_fn=None, hold_mtime_fn=None ):
    """Arbiter job with every liveness seam injectable. Defaults model a fleet
    with NO bridge/hold liveness (the seams return None) and NO awaiting-user
    holds (hold_reader unwired → `_session_awaiting_user` inert)."""
    return ArbiterConsumerJob(
        commons                    = _GW(),
        poll_seconds               = 5,
        manager_recipient          = "DeclaredMgr",
        fleet_stall_window_seconds = WINDOW,
        notify_fn                  = notify or ( lambda *a, **k: None ),
        hold_reader_fn             = hold_reader_fn,
        bridge_mtime_fn            = bridge_mtime_fn if bridge_mtime_fn is not None else ( lambda sid: None ),
        hold_mtime_fn              = hold_mtime_fn   if hold_mtime_fn   is not None else ( lambda sid: None ),
    )


def _view( sid, persona, *, state="working", alive=True, dm_ts=None, holding_on="none" ):
    v = { "session_id": sid, "persona": persona, "state": state, "stuck": False,
          "holding_on": holding_on, "alive": alive }
    if dm_ts is not None:
        v[ "dm_ts" ] = dm_ts
    return v


def _honored_awaiting_user_hold( ):
    """A FRESH, REASONED hold declaring awaiting:user:rick (honored → parked)."""
    return { "held_at": NOW.isoformat(), "ttl_seconds": 3600,
             "reason": "parked on Rick's GCP terraform apply OK (Rick offline)",
             "awaiting": "user:rick" }


# ── FACET 1: awaiting-user held session excluded from the owed/stalled set ─────

class TestAwaitingUserExcludedFromStall:

    def test_awaiting_user_manager_alone_never_stalls( self ):
        """A lone manager on a defended awaiting-user hold, frozen past the window,
        is CORRECTLY parked on Rick — NOT a stall."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ),
                      hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        fv    = { "mgr": _view( "mgr", "Tiberius", state="holding", holding_on="user:rick" ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0                                 # SUPPRESSED
        assert escal == [ ]

    def test_reported_scenario_awaiting_user_mgr_plus_dming_builders_no_stall( self ):
        """THE 2026-07-01 13:46 false-fire, faithfully: 1 awaiting-user-held
        manager + N actively-DMing builders, zero task-transitions in the window →
        NO whole-fleet-stall. Facet-1 excludes the manager; facet-2's DM-liveness
        credits the builders."""
        escal = [ ]
        # only the manager session carries the awaiting-user hold; builders → None
        holds = { "mgr": _honored_awaiting_user_hold() }
        job   = _job( notify=lambda m, *a, **k: escal.append( m ),
                      hold_reader_fn=lambda sid: holds.get( sid ) )
        fv = {
            "mgr": _view( "mgr", "Tiberius", state="holding", holding_on="user:rick" ),
            "b1" : _view( "b1", "Sam",    state="working", dm_ts=RECENT ),
            "b2" : _view( "b2", "Rio",    state="working", dm_ts=RECENT ),
            "b3" : _view( "b3", "Rachel", state="working", dm_ts=RECENT ),
        }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0                                 # NO false stall
        assert escal == [ ]

    def test_awaiting_user_mgr_plus_genuinely_idle_builder_still_fires( self ):
        """Guard against over-suppression: the awaiting-user manager is excluded,
        but a co-resident builder that owes work AND shows NO build/DM/hold
        liveness is a REAL stall → STILL fires (the builder, not Rick's manager,
        is the frozen party)."""
        escal = [ ]
        holds = { "mgr": _honored_awaiting_user_hold() }
        job   = _job( notify=lambda m, *a, **k: escal.append( m ),
                      hold_reader_fn=lambda sid: holds.get( sid ) )
        fv = {
            "mgr": _view( "mgr", "Tiberius", state="holding", holding_on="user:rick" ),
            "b1" : _view( "b1", "Sam", state="stuck" ),                    # owes, no liveness
        }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 1                                 # REAL stall fires
        assert "WHOLE-FLEET-STALL" in escal[ 0 ]


# ── FACET 2: recent build/DM/hold-refresh credited as fleet progress ───────────

class TestBuildLivenessCreditedAsProgress:

    def test_all_idle_owed_fleet_still_fires( self ):
        """RED-KEEP: a genuine all-idle-with-owed-work fleet (no build/DM/hold
        liveness) STILL fires — facet-2 must NOT over-suppress."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        fv    = { "s1": _view( "s1", "Wkr", state="stuck" ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 1                                 # fires
        assert "WHOLE-FLEET-STALL" in escal[ 0 ]

    def test_recent_dm_activity_suppresses_stall( self ):
        """An owed fleet whose only in-window signal is a fresh SENT DM is
        coordinating → progress → NO stall."""
        job = _job()
        fv  = { "s1": _view( "s1", "Wkr", state="stuck", dm_ts=RECENT ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0                                 # SUPPRESSED

    def test_recent_bridge_build_activity_suppresses_stall( self ):
        """A fresh bridge-mtime (Read/Edit/Bash tool calls) is BUILD → progress."""
        job = _job( bridge_mtime_fn=lambda sid: LATE.timestamp() )                          # fresh @ eval time
        fv  = { "s1": _view( "s1", "Wkr", state="stuck" ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0                                 # SUPPRESSED

    def test_recent_hold_refresh_suppresses_stall( self ):
        """A fresh hold-file mtime (hold re-stamped every Stop) is a live
        defended-quiescence refresh → progress."""
        job = _job( hold_mtime_fn=lambda sid: LATE.timestamp() )
        fv  = { "s1": _view( "s1", "Wkr", state="stuck" ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0                                 # SUPPRESSED

    def test_stale_build_liveness_does_not_suppress( self ):
        """A bridge-mtime OLDER than the window is not recent progress → fires."""
        job = _job( bridge_mtime_fn=lambda sid: ( NOW - datetime.timedelta( seconds=WINDOW + 500 ) ).timestamp() )
        fv  = { "s1": _view( "s1", "Wkr", state="stuck" ) }
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 1                                 # fires (stale)

    def test_commons_chatter_still_stalls_blind_spot_closed( self ):
        """CHATTY-BUT-STUCK invariant PRESERVED: commons recency advancing is
        liveness NOT progress — facet-2 excludes commons_age, so a fleet whose
        only in-window signal is commons chatter STILL fires."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ) )
        c1 = { "s1": { **_view( "s1", "Wkr", state="stuck" ), "commons_ts": NOW } }
        c2 = { "s1": { **_view( "s1", "Wkr", state="stuck" ),
                       "commons_ts": RECENT } }
        assert job._check_fleet_stall( c1, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( c2, LATE, [ ] ) == 1                                 # STILL fires
        assert "WHOLE-FLEET-STALL" in escal[ 0 ]

    def test_dead_session_stale_mtime_never_credits( self ):
        """A dead/offline session (alive=False) with a fresh-ish mtime does NOT
        credit progress — the alive gate blocks it; the live owed session stalls."""
        job = _job( bridge_mtime_fn=lambda sid: LATE.timestamp() if sid == "dead" else None )
        fv  = {
            "dead": _view( "dead", "Ghost", state="stuck", alive=False ),
            "live": _view( "live", "Wkr",   state="stuck", alive=True, dm_ts=None ),
        }
        # 'dead' has a fresh bridge mtime but alive=False → skipped; 'live' has no
        # liveness → not credited → real stall.
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0                                  # baseline
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 1                                 # fires


# ── branch coverage for the new helpers ────────────────────────────────────────

class TestBuildLivenessHelperBranches:

    def test_none_fleet_view_has_no_liveness( self ):
        assert _job()._fleet_has_recent_build_liveness( None, NOW ) is False

    def test_non_dict_and_dead_and_sidless_views_skipped( self ):
        job = _job( bridge_mtime_fn=lambda sid: LATE.timestamp() )
        fv  = {
            "x"   : "not-a-dict",                                          # non-dict → skipped
            "dead": _view( "dead", "G", alive=False ),                     # not alive → skipped
            "nosid": { "persona": "P", "alive": True },                    # alive but no session_id → skipped
        }
        assert job._fleet_has_recent_build_liveness( fv, NOW ) is False

    def test_awaiting_user_filter_tolerates_non_dict_view( self ):
        """The facet-1 owed-view filter must not choke on a non-dict view (it keeps
        it; _has_live_owed_work ignores it) — exercises the `isinstance` False
        branch of the exclusion guard."""
        escal = [ ]
        job   = _job( notify=lambda m, *a, **k: escal.append( m ),
                      hold_reader_fn=lambda sid: _honored_awaiting_user_hold() )
        fv = {
            "bad": "not-a-dict",                                            # non-dict → kept, ignored downstream
            "s1" : _view( "s1", "Wkr", state="stuck" ),                     # real owed session (awaiting hold)
        }
        # s1 IS awaiting-user (hold_reader returns the awaiting hold for every sid)
        # → excluded; the non-dict view is ignored by _has_live_owed_work → nothing
        # live-owed remains → no stall.
        assert job._check_fleet_stall( fv, NOW, [ ] ) == 0
        assert job._check_fleet_stall( fv, LATE, [ ] ) == 0
        assert escal == [ ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
