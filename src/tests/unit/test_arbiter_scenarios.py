#!/usr/bin/env python3
"""
Post-game SCENARIO tier (2026-06-11) — operational-requirement acceptance tests.

THE MISSING TEST CLASS (post-game audit §2.3): every pre-existing arbiter test
encodes the IMPLEMENTED CONTRACT ("does the code do what the code intends?");
none encodes the OPERATIONAL REQUIREMENT ("does the system do what the operator
needs?"). Coverage measures code reachability, not requirement reachability — a
requirement with no implementing code is vacuously 100%-covered. These tests
start from the operator situation (a realistic fleet timeline) and assert the
operator-observable outcome (a DM fired, a Rick advisory landed, a journal event
exists), driven through the COMPOSED `_poll_once` — not a single detector branch.

  S1 — manager dark 45m with idle workers → outreach + Rick advisory.
  S2 — fleet decays 4→0 → exactly ONE fleet-dark advisory, re-arm on repopulation.
  S3 — the outreach-accounting invariant: every push has a journal event.
  S4 — the 2026-06-10 journal replay (the forensic case study as a regression pin).
  S5 — an equally-stale WORKER gets NOTHING (quiet≠stall survives the fix).

Venue: :7999-eligible / local — pure + fully mocked (tmp events dir, fake clock,
fake bridges; no server, no real IO).
Design: src/rnd/v0.1.8/2026.06.11-arbiter-missed-poke-postgame-and-outreach-logging.md §2.4.
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


T0 = datetime.datetime( 2026, 6, 10, 14, 0, 0, tzinfo=datetime.timezone.utc )   # 10:00 EDT 2026-06-10


class _GW:
    def __init__( self ):
        self.sent = [ ]
    def who( self, retention_hours=24 ): return [ ]
    def send_to( self, r, b ): self.sent.append( ( r, b ) )
    def post( self, t, b ): pass
    def read( self, topic, since=None, limit=50 ): return [ ]


class _Log:
    def __init__( self ):
        self.events = [ ]
    def __call__( self, event, **fields ):
        self.events.append( ( event, fields ) )
    def of( self, name ):
        return [ f for e, f in self.events if e == name ]


class _FakeClock:
    """Settable wall clock driving _poll_once's `now` (monotonic/sleep unused here)."""
    def __init__( self, t ): self.t = t
    def now_iso( self ): return self.t.isoformat()
    def monotonic( self ): return 0.0
    async def sleep( self, s ): return None


class Fleet:
    """
    A tiny simulated fleet: per-session bridge mtimes the test script advances.
    Sessions are bridge-discovered (the realistic quiet-fleet shape: no stop
    events, no commons posts — exactly how 2026-06-10 looked to the arbiter).
    """
    def __init__( self, clock ):
        self.clock    = clock
        self.bridges  = { }        # sid -> persona
        self.mtimes   = { }        # sid -> epoch float
        self.managers = set()      # sids with manager role (manifest)

    def add( self, sid, persona, manager=False ):
        self.bridges[ sid ] = persona
        self.touch( sid )
        if manager: self.managers.add( sid )

    def touch( self, sid ):
        self.mtimes[ sid ] = self.clock.t.timestamp()

    def remove( self, sid ):
        self.bridges.pop( sid, None )
        self.mtimes.pop( sid, None )
        self.managers.discard( sid )


def _build( tmp_path, clock, fleet, notify, log ):
    return ArbiterConsumerJob(
        commons                    = ( gw := _GW() ),
        poll_seconds               = 60,
        manager_recipient          = "manager-on-duty",
        events_dir                 = str( tmp_path ),
        clock                      = clock,
        notify_fn                  = notify.append,
        log_fn                     = log,
        bridge_discovery_fn        = lambda: dict( fleet.bridges ),
        bridge_mtime_fn            = lambda sid: fleet.mtimes.get( sid ),
        list_managers_fn           = lambda: set( fleet.managers ),
        resolve_manager_fn         = lambda sid, declared_manager=None: {
                                         "manager_persona": None, "source": "unresolved" },
        resolve_active_managers_fn = lambda who, bridges: [ ],
        render_sink                = lambda s: None,
        snapshot_sink              = lambda s: None,
    ), gw


def _advance( clock, fleet, job, minutes, touch=() ):
    """Advance the wall clock, refresh the named sessions' bridges, poll once."""
    clock.t = clock.t + datetime.timedelta( minutes=minutes )
    for sid in touch:
        fleet.touch( sid )
    return job._poll_once()


# ── S1: manager dark 45m with idle workers → outreach + Rick advisory ─────────

def test_s1_manager_dark_45m_with_idle_workers_fires_outreach_and_rick_advisory( tmp_path ):
    """THE HEADLINE REQUIREMENT (Rick, 2026-06-11): "manager stale ≥45m → outreach
    + Rick advisory" — with ZERO stuck workers, the exact shape the old suite
    ratified as correctly-silent."""
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    fleet.add( "mgr-tiberius-uuid", "Tiberius", manager=True )
    fleet.add( "wkr-rio-uuid", "Rio" )
    fleet.add( "wkr-rachel-uuid", "Rachel" )
    job, gw = _build( tmp_path, clock, fleet, notify, log )

    job._poll_once()                                                  # t0: everyone fresh
    assert gw.sent == [ ] and notify == [ ]                           # quiet fleet → no outreach

    # 30 minutes: manager quiet but UNDER the 45m threshold; workers keep fresh
    _advance( clock, fleet, job, 30, touch=( "wkr-rio-uuid", "wkr-rachel-uuid" ) )
    assert gw.sent == [ ] and notify == [ ]                           # below threshold → still quiet

    # 46 minutes total: the manager crosses the threshold → poke + Rick advisory
    _advance( clock, fleet, job, 16, touch=( "wkr-rio-uuid", "wkr-rachel-uuid" ) )
    pokes = [ s for s in gw.sent if s[ 0 ] == "Tiberius" and "manager-staleness poke" in s[ 1 ] ]
    assert len( pokes ) == 1                                          # the outreach
    advisories = [ m for m in notify if "MANAGER-STALE" in m ]
    assert len( advisories ) == 1 and "Tiberius" in advisories[ 0 ]   # the Rick advisory
    assert "EDT" in advisories[ 0 ] or "EST" in advisories[ 0 ]
    # and BOTH are journaled (RC-2): a poke outreach + an advisory outreach
    kinds = [ f[ "kind" ] for f in log.of( "arbiter_outreach" ) ]
    assert "manager_stale_poke" in kinds and "manager_stale_advisory" in kinds
    # the idle workers were NOT poked by anything
    assert all( s[ 0 ] == "Tiberius" for s in gw.sent )


# ── S2: fleet decays 4→0 → exactly ONE dark advisory; re-arm on repopulation ──

def test_s2_fleet_decay_4_to_0_fires_one_dark_advisory( tmp_path ):
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    for sid, persona in ( ( "m1", "Tiberius" ), ( "w1", "Rio" ), ( "w2", "Rachel" ), ( "w3", "Krishna" ) ):
        fleet.add( sid, persona, manager=( sid == "m1" ) )
    job, gw = _build( tmp_path, clock, fleet, notify, log )

    job._poll_once()                                                  # 4 live sessions
    # every session goes silent; bridges age past the 1h offline horizon
    _advance( clock, fleet, job, 35 )                                 # ~35m: stale band (manager episode starts)
    _advance( clock, fleet, job, 35 )                                 # ~70m: all OFFLINE → published 0 → the edge
    darks = [ m for m in notify if "FLEET-DARK" in m ]
    assert len( darks ) == 1
    assert "→0" in darks[ 0 ] and "Tiberius" in darks[ 0 ]            # decay + last manager seen
    # 6 more silent hours (the 2026-06-10 tick parade) → NO re-fire
    for _ in range( 6 ):
        _advance( clock, fleet, job, 60 )
    assert len( [ m for m in notify if "FLEET-DARK" in m ] ) == 1
    # repopulation re-arms: a new fleet rises and dies → a second advisory
    fleet.add( "w9", "Tiffany" )
    _advance( clock, fleet, job, 1 )
    fleet.remove( "w9" )
    _advance( clock, fleet, job, 1 )
    assert len( [ m for m in notify if "FLEET-DARK" in m ] ) == 2


# ── S3: the outreach-accounting invariant — every push has a journal event ────

def test_s3_every_outreach_emits_a_journal_event( tmp_path ):
    """RC-2's testable form: across heterogeneous polls, the journal's recipient
    total equals the actual push total (gateway send_to calls + Rick notifies).
    'Attempting to reach out and communicate' is NEVER invisible."""
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    fleet.add( "mgr-uuid", "Tiberius", manager=True )
    fleet.add( "wkr-uuid", "Rio" )
    job, gw = _build( tmp_path, clock, fleet, notify, log )

    job._poll_once()                                                  # quiet
    _advance( clock, fleet, job, 50, touch=( "wkr-uuid", ) )          # manager-stale episode
    _advance( clock, fleet, job, 1,  touch=( "wkr-uuid", ) )          # poke #2
    _advance( clock, fleet, job, 1,  touch=( "wkr-uuid", ) )          # poke #3
    _advance( clock, fleet, job, 90 )                                 # everyone offline → fleet-dark

    pushes    = len( gw.sent ) + len( notify )
    journaled = sum( len( f[ "recipients" ] ) for f in log.of( "arbiter_outreach" ) )
    assert pushes > 0                                                 # the scenario DID communicate
    assert journaled == pushes                                        # ...and every push is in the journal


# ── S4: the 2026-06-10 journal replay — the forensic case study, pinned ───────

def test_s4_2026_06_10_journal_replay( tmp_path ):
    """REGRESSION PIN: the day's shape — three manager-quiet episodes
    (10:45–11:03 / 13:58–14:43 / 15:58→) with idle workers, then the roster
    decaying 4→0 (16:30–17:05 EDT) and hours of '0 session(s)' ticks. The OLD
    arbiter's journal for this day held ZERO outreach events. The post-game
    arbiter must produce: ≥2 manager-staleness episodes escalated, exactly ONE
    fleet-dark advisory, and gate events explaining every silent poll."""
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    fleet.add( "mgr-tiberius-uuid", "Tiberius", manager=True )
    for sid, persona in ( ( "w1", "Rio" ), ( "w2", "Rachel" ), ( "w3", "Krishna" ) ):
        fleet.add( sid, persona )
    job, gw = _build( tmp_path, clock, fleet, notify, log )
    workers = ( "w1", "w2", "w3" )

    job._poll_once()                                                  # morning: all fresh
    # episode A (the "stale to 27m" window scaled past the 45m threshold):
    _advance( clock, fleet, job, 50, touch=workers )                  # manager dark 50m → escalate
    # manager returns (the 11:03 recovery):
    _advance( clock, fleet, job, 5, touch=( "mgr-tiberius-uuid", ) + workers )
    # episode B (the 13:58–14:43 "45 minutes" Rick saw):
    _advance( clock, fleet, job, 48, touch=workers )                  # dark again → escalate again
    # manager returns briefly:
    _advance( clock, fleet, job, 5, touch=( "mgr-tiberius-uuid", ) + workers )
    # episode C → nobody returns; the whole fleet decays (16:30–17:05):
    _advance( clock, fleet, job, 50 )                                 # manager dark 3rd time (workers aging too)
    _advance( clock, fleet, job, 40 )                                 # everyone past the 1h offline horizon → 0
    # the evening tick parade:
    for _ in range( 4 ):
        _advance( clock, fleet, job, 60 )

    stale_advisories = [ m for m in notify if "MANAGER-STALE" in m ]
    darks            = [ m for m in notify if "FLEET-DARK" in m ]
    assert len( stale_advisories ) >= 2, stale_advisories             # ≥2 episodes escalated (was: zero)
    assert len( darks ) == 1, darks                                   # the decay-to-zero is LOUD, once
    assert all( "Tiberius" in m for m in stale_advisories )
    # the journal explains the silence: gate events exist for the quiet polls
    assert len( log.of( "arbiter_poke_gate" ) ) > 0
    # and the day's journal now contains outreach events (was: zero all day)
    assert len( log.of( "arbiter_outreach" ) ) >= len( stale_advisories ) + len( darks )


# ── S5: an equally-stale WORKER gets NOTHING — quiet≠stall survives the fix ───

def test_s5_worker_quiet_50m_is_not_poked_by_staleness_tier( tmp_path ):
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    fleet.add( "mgr-uuid", "Tiberius", manager=True )
    fleet.add( "wkr-uuid", "Rio" )                                    # the heads-down worker
    job, gw = _build( tmp_path, clock, fleet, notify, log )

    job._poll_once()
    # the WORKER goes dark 50m; the MANAGER keeps fresh
    _advance( clock, fleet, job, 50, touch=( "mgr-uuid", ) )
    assert gw.sent == [ ]                                             # no poke at the quiet worker
    assert [ m for m in notify if "MANAGER-STALE" in m ] == [ ]       # no advisory either
    # the journal still EXPLAINS why: the worker's gate vector says not_manager
    worker_gates = [ f for f in log.of( "arbiter_poke_gate" )
                     if f.get( "session_id" ) == "wkr-uuid" and not f.get( "evicted" ) ]
    assert worker_gates and worker_gates[ -1 ][ "stale_why_not" ] == [ "not_manager" ]


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
