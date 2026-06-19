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
  S6 — boot over a >=20h CORPSE manager row → zero staleness pokes/advisories,
       while a 50-min-dark LIVE manager in the same snapshot still fires
       (the 10:52 EDT 2026-06-11 boot-burst, pinned: corpse-ceiling fix).

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
    def send_to( self, r, b, metadata=None ): self.sent.append( ( r, b ) )
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


# ── S6: boot over a corpse → silence about it; a live dark manager still fires ─

def test_s6_boot_over_yesterday_corpse_manager_silent_while_live_dark_manager_fires( tmp_path ):
    """THE CORPSE-CEILING PIN (10:52 EDT 2026-06-11): on every :8001 process
    start, detection rebuilt over the include_offline=True snapshot (43 rows
    scanned vs 13 live) and the staleness tier poked YESTERDAY'S dead Tiberius
    session 4f7a7ab8 ("silent 1134m") + advised Rick — bounded per corpse sid,
    but re-bursting on every restart. A fresh-boot arbiter over a >=20h corpse
    manager row must stay SILENT about it, while a genuinely-dark (50m) LIVE
    manager in the very same snapshot still draws the F2 poke + advisory."""
    clock, notify, log = _FakeClock( T0 ), [ ], _Log()
    fleet = Fleet( clock )
    # yesterday's corpse: the bridge file is still on disk (discovery returns
    # it) but its last signal is 20h old — exactly how 4f7a7ab8 looked at boot
    fleet.add( "mgr-corpse-uuid", "Tiberius", manager=True )
    fleet.mtimes[ "mgr-corpse-uuid" ] = ( clock.t - datetime.timedelta( hours=20 ) ).timestamp()
    # today's fleet: a manager dark 50 minutes + a fresh worker
    fleet.add( "mgr-live-uuid", "Rio", manager=True )
    fleet.mtimes[ "mgr-live-uuid" ] = ( clock.t - datetime.timedelta( minutes=50 ) ).timestamp()
    fleet.add( "wkr-uuid", "Rachel" )
    job, gw = _build( tmp_path, clock, fleet, notify, log )

    job._poll_once()                                                  # the boot poll
    # the corpse drew NOTHING — no poke, no Rick advisory, no boot-burst
    assert [ s for s in gw.sent if s[ 0 ] == "Tiberius" ] == [ ]
    assert [ m for m in notify if "Tiberius" in m ] == [ ]
    # the LIVE dark manager still fired: poke + advisory, same poll
    pokes = [ s for s in gw.sent if s[ 0 ] == "Rio" and "manager-staleness poke" in s[ 1 ] ]
    assert len( pokes ) == 1
    advisories = [ m for m in notify if "MANAGER-STALE" in m ]
    assert len( advisories ) == 1 and "Rio" in advisories[ 0 ]
    # the journal EXPLAINS the corpse silence: its gate vector reads beyond_max_age
    corpse_gates = [ f for f in log.of( "arbiter_poke_gate" )
                     if f.get( "session_id" ) == "mgr-corpse-uuid" and not f.get( "evicted" ) ]
    assert corpse_gates and corpse_gates[ -1 ][ "stale_why_not" ] == [ "beyond_max_age" ]
    # the bug was a re-burst per process start; within a process, further polls
    # must stay corpse-silent too (no episode state ever opens for it)
    for _ in range( 3 ):
        _advance( clock, fleet, job, 1, touch=( "wkr-uuid", ) )
    assert [ s for s in gw.sent if s[ 0 ] == "Tiberius" ] == [ ]
    assert "mgr-corpse-uuid" not in job._mgr_stale_since


# ── S7: Rick offline → pending ledger → RECYCLE → re-announce delivered ───────

def test_s7_undelivered_advisory_survives_recycle_and_reannounces( tmp_path ):
    """THE MILESTONE-MUST-LAND REQUIREMENT (2026.06.11 receipts design §3.5,
    Tiberius review constraint 2): an advisory that fires while Rick's WS is
    OFFLINE (user_not_available — tonight's latent miss) must survive a JOB
    RECYCLE and re-announce when he returns. Driven through the composed
    `_poll_once` on BOTH sides of the boundary: job A (escalates, misses, files
    the ledger entry) is discarded; a FRESH job B — new in-memory state, same
    ledger FILE — re-announces and closes the receipt. The clock crosses the
    boundary; only the file carries the obligation."""
    from cosa.agents.heartbeat_arbiter.outreach_ledger import read_pending

    ledger = tmp_path / "io" / "outreach-pending.json"
    clock, log_a = _FakeClock( T0 ), _Log()
    fleet = Fleet( clock )
    fleet.add( "mgr-tiberius-uuid", "Tiberius", manager=True )
    fleet.add( "wkr-rio-uuid", "Rio" )

    def _job_with( log, notify_fn, live_retry_fn=None ):
        return ArbiterConsumerJob(
            commons                    = _GW(),
            poll_seconds               = 60,
            manager_recipient          = "manager-on-duty",
            events_dir                 = str( tmp_path ),
            clock                      = clock,
            notify_fn                  = notify_fn,
            live_retry_fn              = live_retry_fn,
            pending_ledger_path        = str( ledger ),
            log_fn                     = log,
            bridge_discovery_fn        = lambda: dict( fleet.bridges ),
            bridge_mtime_fn            = lambda sid: fleet.mtimes.get( sid ),
            list_managers_fn           = lambda: set( fleet.managers ),
            resolve_manager_fn         = lambda sid, declared_manager=None: {
                                             "manager_persona": None, "source": "unresolved" },
            resolve_active_managers_fn = lambda who, bridges: [ ],
            render_sink                = lambda s: None,
            snapshot_sink              = lambda s: None,
        )

    # ── before the boundary: job A escalates while Rick is OFFLINE ──
    rick_offline = lambda m: [ { "channel": "live", "outcome": "user_not_available" } ]
    job_a = _job_with( log_a, rick_offline )
    job_a._poll_once()                                                # t0: fresh fleet, quiet
    clock.t = clock.t + datetime.timedelta( minutes=30 ); fleet.touch( "wkr-rio-uuid" )
    job_a._poll_once()                                                # manager under threshold
    clock.t = clock.t + datetime.timedelta( minutes=16 ); fleet.touch( "wkr-rio-uuid" )
    job_a._poll_once()                                                # 46m dark → case-14 advisory fires
    miss = [ f for f in log_a.of( "arbiter_outreach_result" )
             if f[ "recipient" ] == "rick" and f[ "outcome" ] == "user_not_available" ]
    assert miss, "the advisory must journal the user_not_available miss"
    pending = read_pending( ledger )
    assert len( pending ) == 1                                        # the obligation is ON DISK
    oid = next( iter( pending ) )
    assert log_a.of( "arbiter_outreach_receipt" ) == [ ]              # not terminal — pending

    # ── THE RECYCLE BOUNDARY: job A is discarded; job B has FRESH in-memory state ──
    del job_a
    log_b      = _Log()
    deliveries = [ ]
    def rick_back( message ):                                         # Rick's WS reconnected
        deliveries.append( message )
        return { "channel": "live", "outcome": "queued" }
    job_b = _job_with( log_b, rick_offline, live_retry_fn=rick_back )

    # advance past the reannounce interval ACROSS the boundary; fresh fleet so no new advisory
    clock.t = clock.t + datetime.timedelta( minutes=6 )
    fleet.touch( "mgr-tiberius-uuid" ); fleet.touch( "wkr-rio-uuid" )
    job_b._poll_once()

    assert len( deliveries ) == 1 and "MANAGER-STALE" in deliveries[ 0 ]
    receipt = [ f for f in log_b.of( "arbiter_outreach_receipt" )
                if f[ "outreach_id" ] == oid ][ 0 ]
    assert receipt[ "outcome" ] == "reannounced_delivered" and receipt[ "attempts" ] == 2
    assert read_pending( ledger ) == { }                              # obligation discharged


# ── S8: reaped worker keeps its manager ACROSS a restart (lineage carry) ──────

def test_s8_reaped_worker_keeps_manager_across_restart( tmp_path ):
    """THE LINEAGE-PERSISTENCE REQUIREMENT (2026.06.11 design F-A; Rick's
    "(Unmanaged)" Cheech/old-Rio bug): at reap, dismiss_sessions destroys BOTH
    lineage sources (manifest record + bridge), so the decaying row's manager
    survives ONLY via the carry — and the carry was in-memory, wiped by each of
    tonight's 4× :8001 restarts. Driven through the composed `_poll_once` with
    the REAL dismiss aftermath simulated (bridge gone + resolver unresolved):
    job A observes the lineage and persists it; job A is DISCARDED; a FRESH
    job B — same carry FILE, empty memory — still renders the row under
    Tiberius. Pre-fix, job B rendered "(Unmanaged)"."""
    import json as _json
    from cosa.agents.heartbeat_arbiter.lineage_carry import read_carry

    carry = tmp_path / "io" / "lineage-carry.json"
    clock = _FakeClock( T0 )
    fleet = Fleet( clock )
    fleet.add( "wkr-cheech-uuid", "Cheech" )
    # the worker has an events trace, so its row PERSISTS in the fleet view
    # after the bridge vanishes (the realistic decay shape).
    ( tmp_path / "wkr-cheech-uuid.jsonl" ).write_text( _json.dumps( {
        "schema_version": 1, "session_id": "wkr-cheech-uuid",
        "persona": "Cheech", "outcome": "idle", "ts": T0.isoformat(),
    } ) + "\n" )

    snapshots = [ ]
    def _job_with():
        return ArbiterConsumerJob(
            commons                    = _GW(),
            poll_seconds               = 60,
            manager_recipient          = "manager-on-duty",
            events_dir                 = str( tmp_path ),
            clock                      = clock,
            notify_fn                  = lambda m: [ { "channel": "live", "outcome": "queued" } ],
            lineage_carry_path         = str( carry ),
            log_fn                     = _Log(),
            bridge_discovery_fn        = lambda: dict( fleet.bridges ),
            bridge_mtime_fn            = lambda sid: fleet.mtimes.get( sid ),
            list_managers_fn           = lambda: set( fleet.managers ),
            # lineage resolves ONLY while the worker's bridge exists — after the
            # reap (bridge unlinked + manifest record dropped) the resolver is
            # structurally unresolved, exactly like production.
            resolve_manager_fn         = lambda sid, declared_manager=None: (
                { "manager_persona": "Tiberius", "source": "lineage" }
                if sid in fleet.bridges else
                { "manager_persona": None, "source": "unresolved" } ),
            resolve_active_managers_fn = lambda who, bridges: [ ],
            render_sink                = lambda s: None,
            snapshot_sink              = snapshots.append,
        )

    def _row( snap, sid ):
        return next( r for r in snap[ "sessions" ] if r[ "session_id" ] == sid )

    # ── job A: observes the live worker under Tiberius; carry hits the FILE ──
    job_a = _job_with()
    job_a._poll_once()
    assert _row( snapshots[ -1 ], "wkr-cheech-uuid" )[ "manager" ] == "Tiberius"
    assert read_carry( carry ) == { "wkr-cheech-uuid": "Tiberius" }   # persisted

    # ── the REAP: bridge gone, resolver unresolved; row decays but stays parented ──
    fleet.remove( "wkr-cheech-uuid" )
    clock.t = clock.t + datetime.timedelta( minutes=10 )
    job_a._poll_once()
    assert _row( snapshots[ -1 ], "wkr-cheech-uuid" )[ "manager" ] == "Tiberius"   # in-memory carry (2026-06-10 fix)

    # ── THE RESTART BOUNDARY: job A discarded; job B = fresh memory, same FILE ──
    del job_a
    job_b = _job_with()
    clock.t = clock.t + datetime.timedelta( minutes=5 )
    job_b._poll_once()
    row = _row( snapshots[ -1 ], "wkr-cheech-uuid" )
    assert row[ "manager" ] == "Tiberius", \
        f"pre-fix failure shape: restart orphaned the row to Unmanaged (got {row[ 'manager' ]!r})"


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
