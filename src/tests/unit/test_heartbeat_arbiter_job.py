#!/usr/bin/env python3
"""
Unit tests for the Heartbeat-Arbiter consumer job (arbiter_job.py).

Drives the FULL composition against Tiffany's REAL leaves (build_fleet_view /
build_graph / build_roster / ping_throttle) with injected seams — a FakeClock
(drives the poll/hard-cap loop without real waiting) + a FakeGateway (records
who/send_to/post) + synthetic on-disk event files in a tmp fleet dir.

Covers: __init__ validation, _poll_once composition, _auto_ping (fire/throttle/
global-cap/clear-on-resume), _escalate_deadlocks, _prune_recent_pings,
_surface_to_manager branches, and the _execute lifecycle (cancel / hard-cap /
per-poll-exception-swallowed) + do_all.

Venue: :7999-eligible / local — fully mocked I/O, no server, sub-second.
"""
import datetime
import json
import os
import sys

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.agents.heartbeat_arbiter.arbiter_job import (
    ArbiterConsumerJob, ROSTER_TOPIC,
)


NOW_ISO = "2026-06-05T12:00:00+00:00"


def _event( sid, outcome, awaiting="none", work_owed=False, persona=None,
            ts="2026-06-05T11:59:00+00:00", poke_count=1, cap=3 ):
    return {
        "schema_version": 1, "session_id": sid, "persona": persona, "ts": ts,
        "outcome": outcome, "poke_count": poke_count, "cap": cap,
        "work_owed": work_owed, "awaiting": awaiting,
    }


def _write_events( events_dir, sid, *records ):
    path = os.path.join( events_dir, f"{sid}.jsonl" )
    with open( path, "w" ) as f:
        for r in records:
            f.write( json.dumps( r ) + "\n" )
    return path


class FakeClock:
    """Drives the loop deterministically. monotonic() pops a scripted sequence."""
    def __init__( self, now_iso=NOW_ISO, monotonic_seq=None ):
        self._now_iso = now_iso
        self._seq     = list( monotonic_seq ) if monotonic_seq is not None else None
        self.sleeps   = [ ]

    def monotonic( self ):
        if self._seq is not None and self._seq:
            return self._seq.pop( 0 )
        return 0.0

    def now_iso( self ):
        return self._now_iso

    async def sleep( self, seconds ):
        self.sleeps.append( seconds )


class FakeGateway:
    """Records who/send_to/post; who() returns a scripted roster."""
    def __init__( self, who_rows=None ):
        self._who_rows = who_rows if who_rows is not None else [ ]
        self.sent      = [ ]    # (recipient, body)
        self.posts     = [ ]    # (topic, body)

    def who( self, retention_hours=24 ):
        return list( self._who_rows )

    def send_to( self, recipient, body, metadata=None ):
        self.sent.append( ( recipient, body ) )

    def post( self, topic, body ):
        self.posts.append( ( topic, body ) )

    def read( self, topic, since=None, limit=50 ):
        return [ ]   # v2.2 B3: no decision-needed posts in these v1 tests


def _make_job( events_dir, gateway=None, notify_fn=None, **overrides ):
    cfg = dict(
        poll_seconds            = 5,
        manager_recipient       = "Tiberius",
        alive_threshold_seconds = 600,
        quiet_threshold_seconds = 300,            # F3: quiet < alive (non-empty inference window)
        ping_global_cap         = 10,
        events_dir              = str( events_dir ),
        clock                   = FakeClock(),
        notify_fn               = notify_fn or ( lambda *a, **k: None ),
        # v2.2 B2: default these v1-era tests to an UNRESOLVED manager so the new
        # manager-tap fires zero DMs here — keeps the auto-ping send-count
        # assertions isolated from the tap. The tap is covered in its own suite.
        resolve_manager_fn      = lambda sid, declared_manager=None: {
            "manager_session_id": None, "manager_persona": None, "source": "unresolved" },
        # v1.4: hermetic bridge discovery — keep the union source (a) EMPTY so
        # these tests don't pick up the real ~/.claude live fleet. Override per-test.
        bridge_discovery_fn     = lambda: { },
    )
    cfg.update( overrides )
    return ArbiterConsumerJob( commons=gateway or FakeGateway(), **cfg )


# ── __init__ validation ───────────────────────────────────────────────────────

@pytest.mark.parametrize( "bad", [
    { "poll_seconds": 0 }, { "max_duration_seconds": 0 }, { "alive_threshold_seconds": 0 },
    { "quiet_threshold_seconds": 0 }, { "ping_global_cap": 0 }, { "ping_cap_window_seconds": 0 },
    { "tail_maxlen": 0 }, { "manager_recipient": "" },
    # F3 invariant: quiet >= alive → raise (empty inference window)
    { "quiet_threshold_seconds": 600 },           # == alive (600)
    { "quiet_threshold_seconds": 700 },           # >  alive (600)
] )
def test_init_validation_raises( tmp_path, bad ):
    with pytest.raises( ValueError ):
        _make_job( tmp_path, **bad )


def test_f3_default_quiet_below_alive( tmp_path ):
    """Shipped defaults must satisfy the F3 invariant (quiet < alive) so a
    default-constructed arbiter's inference half is NEVER config-dead."""
    job = _make_job( tmp_path )
    assert job.quiet_threshold_seconds < job.alive_threshold_seconds
    assert ( job.quiet_threshold_seconds, job.alive_threshold_seconds ) == ( 300, 600 )


def test_init_happy_defaults_seam( tmp_path ):
    job = ArbiterConsumerJob( commons=FakeGateway(), poll_seconds=5, manager_recipient="T" )
    assert job.JOB_TYPE == "heartbeat_arbiter"
    assert job._clock is not None and job._notify_fn is not None     # default seams resolved


def test_last_question_asked_display( tmp_path ):
    job = _make_job( tmp_path, manager_recipient="Tiberius", poll_seconds=30 )
    s = job.last_question_asked()
    assert "Heartbeat arbiter" in s and "Tiberius" in s and "30s" in s


# ── 5a1f17f8 (b): durable event offsets across restarts ───────────────────────

def test_offsets_state_path_none_is_in_memory_only( tmp_path ):
    """Default (no offsets_state_path) → offsets start empty + are NOT persisted:
    today's in-memory behavior is preserved exactly (the inert branch)."""
    job = _make_job( tmp_path )                                  # no offsets_state_path
    assert job._offsets == { } and job._offsets_state_path is None
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", persona="Alice" ) )
    job._poll_once()
    # nothing written anywhere; offsets advanced only in memory
    assert job._offsets.get( "s1", 0 ) > 0


def test_offsets_loaded_on_init_from_state_path( tmp_path ):
    """A restart RESUMES from the persisted offsets (bug 5a1f17f8 (b)): the durable
    store seeds self._offsets so tail_fleet_events does NOT re-read from byte 0."""
    import json as _json
    state = tmp_path / "offsets.json"
    state.write_text( _json.dumps( { "s1": 999999 } ) )         # a prior run's saved offset
    job = _make_job( tmp_path, offsets_state_path=str( state ) )
    assert job._offsets == { "s1": 999999 }                     # resumed, not fresh {}


def test_offsets_saved_after_poll( tmp_path ):
    """After each poll the advanced offsets are persisted so the NEXT process start
    resumes here — no replay of historical cap_reached."""
    import json as _json
    state = tmp_path / "offsets.json"
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", persona="Alice" ) )
    job = _make_job( tmp_path, offsets_state_path=str( state ) )
    assert job._offsets == { }                                  # first-ever start (file absent → {})
    job._poll_once()
    persisted = _json.loads( state.read_text() )
    assert persisted.get( "s1", 0 ) > 0 and persisted == job._offsets   # saved == in-memory


# ── _poll_once composition ────────────────────────────────────────────────────

def test_poll_once_builds_view_no_roster_broadcast( tmp_path ):
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="none", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    summary = job._poll_once()
    assert summary[ "sessions" ] == 1
    assert job._poll_count == 1
    # Part-6 #6: the per-tick roster broadcast is DROPPED — the fleet roster is
    # pull-state (/state snapshot), NOT a commons post. Nothing is posted.
    assert gw.posts == [ ]


# ── v1.4 integrator: bridge discovery → UNION roster ──────────────────────────

def test_default_bridge_discovery_maps_personas( monkeypatch ):
    """The impure discovery helper reduces live bridges to {sid: persona_name}."""
    from cosa.agents.heartbeat_arbiter import arbiter_job as aj
    fake = [
        ( "/p/cc-1.json", "sid-dict", { "name": "Tiffany" } ),   # dict persona → name
        ( "/p/cc-2.json", "sid-str",  "BareString" ),            # str persona → itself
        ( "/p/cc-3.json", "sid-none", None ),                    # no persona → None
        ( "/p/cc-4.json", "",         { "name": "Skip" } ),      # empty sid → skipped
    ]
    monkeypatch.setattr( aj, "_find_active_voice_persona_sessions", lambda **k: fake )
    assert aj._default_bridge_discovery() == {
        "sid-dict": "Tiffany", "sid-str": "BareString", "sid-none": None
    }


def test_default_bridge_discovery_swallows_errors( monkeypatch ):
    """A discovery hiccup yields {} — the observer poll degrades safe (never raises)."""
    from cosa.agents.heartbeat_arbiter import arbiter_job as aj
    def _boom( **k ):
        raise RuntimeError( "bridge scan failed" )
    monkeypatch.setattr( aj, "_find_active_voice_persona_sessions", _boom )
    assert aj._default_bridge_discovery() == { }


def test_default_dead_session_ids_delegates_to_find_dead( monkeypatch ):
    """The kill-0 death probe forwards the fleet-view's sids and returns the dead set."""
    from cosa.agents.heartbeat_arbiter import arbiter_job as aj
    seen = {}
    def _fake( ids ):
        seen[ "ids" ] = set( ids )
        return { "deadguy" }
    monkeypatch.setattr( aj, "_find_dead_sessions", _fake )
    out = aj._default_dead_session_ids( { "deadguy": {}, "liveguy": {} } )
    assert out == { "deadguy" }
    assert seen[ "ids" ] == { "deadguy", "liveguy" }


def test_default_dead_session_ids_swallows_errors( monkeypatch ):
    """A probe hiccup yields an empty set — snapshot falls back to staleness (never raises)."""
    from cosa.agents.heartbeat_arbiter import arbiter_job as aj
    def _boom( ids ):
        raise RuntimeError( "probe failed" )
    monkeypatch.setattr( aj, "_find_dead_sessions", _boom )
    assert aj._default_dead_session_ids( { "s1": {} } ) == set()


def test_poll_once_folds_bridge_only_session_into_union( tmp_path ):
    """A session with NO events and NO commons — ONLY a live bridge — must enter
    the UNION roster AND read LIVE via its fresh bridge_age (the false-offline fix)."""
    import datetime
    now_epoch = datetime.datetime.fromisoformat( NOW_ISO ).timestamp()
    snapshots = [ ]
    gw  = FakeGateway( who_rows=[ ] )                               # nothing on commons
    job = _make_job(
        tmp_path, gateway=gw,
        bridge_discovery_fn = lambda: { "ghost-sid": "Ghost" },    # ONLY signal: a live bridge
        bridge_mtime_fn     = lambda sid: now_epoch - 5,           # fresh bridge mtime → 5s
        snapshot_sink       = snapshots.append,
    )
    summary = job._poll_once()
    assert summary[ "sessions" ] == 1                              # bridge-only session is a member
    row = snapshots[ -1 ][ "sessions" ][ 0 ]
    assert row[ "session_id" ] == "ghost-sid" and row[ "persona" ] == "Ghost"
    # the verdict reads LIVE off the FRESH bridge age — even with no events/commons
    assert row[ "liveness" ][ "verdict" ] == "LIVE"
    assert row[ "liveness" ][ "bridge_age_s" ] == 5
    # all FOUR distinct age columns are present (Step 1.5)
    assert set( row[ "liveness" ] ) >= {
        "bridge_age_s", "event_age_s", "commons_age_s", "idle_prompt_age_s", "freshest_age_s", "verdict"
    }


def test_poll_once_inference_idle_with_shipped_defaults( tmp_path ):
    """F3 end-to-end: an alive+quiet session lands on the roster as inference
    under the SHIPPED defaults (quiet 300 < alive 600) — the hybrid's inference
    half is alive, not config-dead. Drives real timestamps (no hardcoded alive)."""
    old_ts = "2026-06-05T11:53:20+00:00"          # 400s before NOW (12:00:00): 300 ≤ 400 ≤ 600
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "poked", awaiting="none", persona="Alice", ts=old_ts ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": old_ts } ] )
    job = _make_job( tmp_path, gateway=gw )        # shipped defaults: quiet=300, alive=600
    summary = job._poll_once()
    assert summary[ "roster" ] == 1                # inference half alive (roster built; #6 broadcast dropped)


def test_poll_once_auto_pings_blocker( tmp_path ):
    # s1 is HOLDING on peer:Bob → an edge s1→Bob → auto-ping Bob
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    summary = job._poll_once()
    assert summary[ "edges" ] == 1
    assert summary[ "pings_fired" ] == 1
    assert gw.sent[ 0 ][ 0 ] == "Bob"                     # the blocker (awaited peer)
    assert "blocking worker" in gw.sent[ 0 ][ 1 ]         # Part-6 #4 rewrite


def test_poll_once_throttle_blocks_second_ping( tmp_path ):
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "session_id_short": "s1", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    job._poll_once()                       # fires
    job._poll_once()                       # same edge, same now → backoff blocks
    assert len( gw.sent ) == 1


def test_auto_ping_backoff_schedule_advancing_clock( tmp_path ):
    """The first GATED gap is 60s (schedule[0]), then 300s — not 300/900 (F2 off-by-one)."""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "last_post_ts": NOW_ISO } ] )
    clk = FakeClock( now_iso="2026-06-05T12:00:00+00:00" )
    job = _make_job( tmp_path, gateway=gw, clock=clk )

    job._poll_once();                                      assert len( gw.sent ) == 1   # t0: immediate
    clk._now_iso = "2026-06-05T12:00:30+00:00"; job._poll_once(); assert len( gw.sent ) == 1   # +30s <60 → blocked
    clk._now_iso = "2026-06-05T12:01:00+00:00"; job._poll_once(); assert len( gw.sent ) == 2   # +60s ≥60 → fires
    clk._now_iso = "2026-06-05T12:04:00+00:00"; job._poll_once(); assert len( gw.sent ) == 2   # +180s <300 → blocked
    clk._now_iso = "2026-06-05T12:06:00+00:00"; job._poll_once(); assert len( gw.sent ) == 3   # +300s ≥300 → fires


def test_poll_once_global_cap_blocks( tmp_path ):
    # two blockers, cap=1 → only one ping fires
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="peer:Bob", persona="A" ) )
    _write_events( str( tmp_path ), "s2", _event( "s2", "honored", awaiting="peer:Cara", persona="B" ) )
    gw  = FakeGateway( who_rows=[
        { "session_id": "s1", "last_post_ts": NOW_ISO },
        { "session_id": "s2", "last_post_ts": NOW_ISO },
    ] )
    job = _make_job( tmp_path, gateway=gw, ping_global_cap=1 )
    summary = job._poll_once()
    assert summary[ "pings_fired" ] == 1
    assert len( gw.sent ) == 1


def test_clear_on_resume_drops_edge_state( tmp_path ):
    p = _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="peer:Bob", persona="A" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    job._poll_once()
    assert job._ledger.tracked_edges()                        # an edge is tracked
    # s1 resumes (no longer awaiting) → next poll the edge disappears → cleared
    with open( p, "a" ) as f:
        f.write( json.dumps( _event( "s1", "poked", awaiting="none", persona="A" ) ) + "\n" )
    job._poll_once()
    assert job._ledger.tracked_edges() == set()
    assert job._ping_attempts == { }


# ── bc1bc373 staleness-filter (dead hold → zero phantom edges) ──────────────────

def _live_hold( now_iso=NOW_ISO ):
    """A fresh, honored, work-owed hold (held 10s before now)."""
    held = ( datetime.datetime.fromisoformat( now_iso ) - datetime.timedelta( seconds=10 ) ).isoformat()
    return { "held_at": held, "ttl_seconds": 900, "work_owed": True, "reason": "waiting on Bob" }


def _dead_hold( now_iso=NOW_ISO ):
    """An EXPIRED hold (held 10_000s before now, ttl 900) → stale."""
    held = ( datetime.datetime.fromisoformat( now_iso ) - datetime.timedelta( seconds=10_000 ) ).isoformat()
    return { "held_at": held, "ttl_seconds": 900, "work_owed": True, "reason": "stale" }


def test_poll_once_dead_hold_drops_phantom_ping( tmp_path ):
    """AC B.1: s1's hold is DEAD (expired) → its peer:Bob edge contributes ZERO
    edges → NO 'Bob is blocking' phantom ping fires."""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw, hold_reader_fn=lambda sid: _dead_hold() )
    summary = job._poll_once()
    assert summary[ "edges" ] == 0
    assert summary[ "pings_fired" ] == 0
    assert gw.sent == [ ]


def test_poll_once_live_hold_keeps_ping( tmp_path ):
    """AC B.2: s1's hold is LIVE+honored+work-owed → its peer edge survives → the
    blocker is still pinged (no over-filtering regression)."""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw, hold_reader_fn=lambda sid: _live_hold() )
    summary = job._poll_once()
    assert summary[ "edges" ] == 1
    assert summary[ "pings_fired" ] == 1
    assert gw.sent[ 0 ][ 0 ] == "Bob"


def test_poll_once_no_hold_reader_is_inert( tmp_path ):
    """Reader unwired (default None) → filter inert → today's behavior (pings)."""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )                          # no hold_reader_fn
    summary = job._poll_once()
    assert summary[ "edges" ] == 1 and summary[ "pings_fired" ] == 1


def test_poll_once_stale_participant_store_backed_cycle_still_escalates( tmp_path ):
    """María review of bc1bc373/c88a7431 (CHANGES-REQUESTED regression): a REAL
    store-backed deadlock must STILL escalate even when a participant's hold is
    stale. alice (alive but with an EXPIRED hold) ↔ bob mutually hold (peer cycle);
    alice's dead hold filters her edge out of the ADVISORY graph so graph["cycles"]
    is EMPTY — the OLD feed (graph["cycles"]) would MISS the deadlock — but the store
    carries a real alice↔bob blocked_by ring, so the UNFILTERED escalation feed
    (find_deadlock_cycles(build_wait_edges(fleet_view))) STILL sees it and escalates."""
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="peer:bob",   persona="alice" ) )
    _write_events( str( tmp_path ), "s2", _event( "s2", "honored", awaiting="peer:alice", persona="bob"   ) )
    gw = FakeGateway( who_rows=[
        { "session_id": "s1", "persona_name": "alice", "last_post_ts": NOW_ISO },
        { "session_id": "s2", "persona_name": "bob",   "last_post_ts": NOW_ISO },
    ] )
    store_cycle = {
        "alice": [ { "id": "a1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "bob" } ] } ],
        "bob":   [ { "id": "b1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "alice" } ] } ],
    }
    escal = [ ]
    job = _make_job( tmp_path, gateway=gw,
                     hold_reader_fn         = lambda sid: _dead_hold() if sid == "s1" else None,
                     owed_work_fn           = lambda names: store_cycle,
                     deadlock_dwell_seconds = 0,                     # fire on first corroborated sight
                     notify_fn              = lambda msg, *a, **k: escal.append( msg ) )
    summary = job._poll_once()
    # the ADVISORY graph is FILTERED empty (alice's dead-hold edge dropped) → the OLD
    # graph["cycles"] feed would have MISSED this real deadlock...
    assert summary[ "cycles" ] == 0
    # ...but the UNFILTERED escalation feed (find_deadlock_cycles(build_wait_edges(...)))
    # sees the store-backed alice↔bob ring → the deadlock STILL escalates. Asserting the
    # store-corroborated DEADLOCK message NAMES BOTH participants proves it fired via the
    # unfiltered store-backed path specifically (María's ask: a future re-filter of the
    # escalation feed → empty cycles → no DEADLOCK escalation → this fails, never silent).
    deadlock_msgs = [ m for m in escal if "DEADLOCK" in m and "store-corroborated" in m ]
    assert deadlock_msgs, escal
    assert "alice" in deadlock_msgs[ 0 ] and "bob" in deadlock_msgs[ 0 ]


def test_poll_once_dead_session_participant_store_backed_cycle_still_escalates( tmp_path ):
    """8a450183 :1018 invariant — the SESSION-freshness AXIS twin of the hold-axis
    test above (Krishna's veto domain). A REAL store-backed deadlock must STILL
    escalate even when a ring participant is a beyond-alive-threshold (DEAD) SESSION.

    alice is a ~12h-stale session (bridge-absent → offline) holding peer:bob; bob is
    fresh holding peer:alice. The NEW per-session freshness gate drops alice's edge
    from the FILTERED advisory graph (summary['cycles'] == 0 — the OLD graph['cycles']
    feed would MISS the deadlock), but the store carries a real alice↔bob blocked_by
    ring, so the UNFILTERED escalation feed at :1018
    (find_deadlock_cycles(build_wait_edges(fleet_view)) — passes NO now/threshold)
    STILL sees the ring and escalates. This LOCKS the invariant against the session
    axis explicitly: if a future change ever threaded now/threshold into the :1018
    feed, alice would drop there too → empty cycles → no escalation → this fails LOUD
    (never silent), mirroring the hold-axis guard."""
    old_ts = ( datetime.datetime.fromisoformat( NOW_ISO ) - datetime.timedelta( hours=12 ) ).isoformat()
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="peer:bob",   persona="alice", ts=old_ts ) )
    _write_events( str( tmp_path ), "s2", _event( "s2", "honored", awaiting="peer:alice", persona="bob"   ) )
    # alice bridge-absent → her commons echo (if any) is phantom-nulled → last_activity
    # rests on the 12h-old event → session_is_stale fires for her in the FILTERED graph.
    gw = FakeGateway( who_rows=[
        { "session_id": "s2", "persona_name": "bob", "last_post_ts": NOW_ISO },
    ] )
    store_cycle = {
        "alice": [ { "id": "a1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "bob" } ] } ],
        "bob":   [ { "id": "b1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "alice" } ] } ],
    }
    escal = [ ]
    job = _make_job( tmp_path, gateway=gw,
                     bridge_discovery_fn    = lambda: { "s2": "bob" },     # alice ABSENT → dead session
                     owed_work_fn           = lambda names: store_cycle,
                     deadlock_dwell_seconds = 0,                            # fire on first corroborated sight
                     notify_fn              = lambda msg, *a, **k: escal.append( msg ) )
    summary = job._poll_once()
    # FILTERED advisory graph: alice's dead-SESSION edge dropped → ring dissolved → 0
    assert summary[ "cycles" ] == 0
    # UNFILTERED :1018 feed: store-backed alice↔bob ring STILL escalates
    deadlock_msgs = [ m for m in escal if "DEADLOCK" in m and "store-corroborated" in m ]
    assert deadlock_msgs, escal
    assert "alice" in deadlock_msgs[ 0 ] and "bob" in deadlock_msgs[ 0 ]


def test_stale_hold_holders_missing_hold_keeps_edge( tmp_path ):
    """A session with NO readable hold is NOT added to the stale set (absence ≠
    deadness) — the edge survives. Directly exercises _stale_hold_holders."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: None )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "Alice", "session_id": "s1", "holding_on": "peer:Bob" } }
    assert job._stale_hold_holders( view, now ) == set()


def test_stale_hold_holders_swallows_reader_error_and_skips_non_peer( tmp_path ):
    """A raising reader degrades that session to 'not stale' (edge survives); a
    non-peer / persona-less / non-dict view is skipped without a read."""
    reads = [ ]
    def boom( sid ):
        reads.append( sid )
        raise RuntimeError( "reader down" )
    job  = _make_job( tmp_path, hold_reader_fn=boom )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = {
        "s1": { "persona": "Alice", "session_id": "s1", "holding_on": "peer:Bob" },  # read → raises → not stale
        "s2": { "persona": "Cal",   "session_id": "s2", "holding_on": "user:Rick" }, # non-peer → skipped (no read)
        "s3": { "persona": "Dan",   "session_id": "",   "holding_on": "peer:Eve" },  # no sid → skipped
        "s4": { "session_id": "s4", "holding_on": "peer:Eve" },                      # no persona → skipped
        "s5": "not-a-dict",                                                          # non-dict → skipped
    }
    assert job._stale_hold_holders( view, now ) == set()
    assert reads == [ "s1" ]                                         # ONLY the peer-edge holder was read


def test_stale_hold_holders_inert_when_reader_none( tmp_path ):
    job  = _make_job( tmp_path )                                     # hold_reader_fn defaults to None
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "Alice", "session_id": "s1", "holding_on": "peer:Bob" } }
    assert job._stale_hold_holders( view, now ) == set()


# ── 7f9a8ee2 reconciliation (fresh hold awaiting contradicts stale holding_on) ─────

def _fresh_hold( awaiting, now_iso=NOW_ISO ):
    """A fresh+honored+work-owed hold with an explicit awaiting field."""
    held = ( datetime.datetime.fromisoformat( now_iso ) - datetime.timedelta( seconds=10 ) ).isoformat()
    return { "held_at": held, "ttl_seconds": 1800, "work_owed": True, "reason": "parked", "awaiting": awaiting }


def test_stale_hold_holders_includes_dead_hold( tmp_path ):
    """Directly exercises the hold_is_stale operand of the subtraction OR (dead hold
    → added), at the unit level (not only via _poll_once)."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _dead_hold() )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "Alice", "session_id": "s1", "holding_on": "peer:Bob" } }
    assert job._stale_hold_holders( view, now ) == { "Alice" }


def test_stale_hold_holders_includes_fresh_contradicting_hold( tmp_path ):
    """7f9a8ee2: a FRESH hold whose awaiting='none' contradicts holding_on=peer:maria
    → the holder joins the subtraction set (the reconciliation operand of the OR)."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _fresh_hold( "none" ) )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "mr radio", "session_id": "s1", "holding_on": "peer:maria" } }
    assert job._stale_hold_holders( view, now ) == { "mr radio" }


def test_stale_hold_holders_keeps_fresh_corroborating_hold( tmp_path ):
    """A fresh hold whose awaiting MATCHES holding_on is a genuine wait → NOT added
    (the both-False arm: not stale AND not contradicting)."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _fresh_hold( "peer:maria" ) )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "mr radio", "session_id": "s1", "holding_on": "peer:maria" } }
    assert job._stale_hold_holders( view, now ) == set()


# ── ping-storm durable Fix 2 (2026-06-24): session_is_stale as a 3rd ADDITIVE,
# fail-safe subtraction axis in _stale_hold_holders. A holder whose hold is FRESH
# and CORROBORATING (so hold_is_stale + hold_contradicts both say "keep") but whose
# SESSION is beyond the alive threshold contributes ZERO edges. Defense-in-depth
# behind build_graph's existing per-session gate (8a450183) — observable here at
# the method level. Stays INSIDE the `hold is not None` guard so the method's
# contract ("no readable hold → never added") is preserved. _STALE_TS = 1h before
# NOW (> 600s threshold); _FRESH_TS = 60s before NOW (< 600s).

_STALE_TS = "2026-06-05T11:00:00+00:00"          # 3600s before NOW → session_is_stale True
_FRESH_TS = "2026-06-05T11:59:00+00:00"          #   60s before NOW → session_is_stale False


def test_stale_hold_holders_includes_stale_session_fresh_corroborating_hold( tmp_path ):
    """Fix 2 RED-first: a STALE session (last_activity_ts beyond alive_threshold)
    with a FRESH+CORROBORATING hold (both other axes say keep) is now SUBTRACTED via
    the session_is_stale axis. Pre-fix: returns set() (hold neither stale nor
    contradicting); post-fix: { holder }."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _fresh_hold( "peer:maria" ) )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "mr radio", "session_id": "s1",
                     "holding_on": "peer:maria", "last_activity_ts": _STALE_TS } }
    assert job._stale_hold_holders( view, now ) == { "mr radio" }


def test_stale_hold_holders_fresh_session_keeps_corroborating_hold( tmp_path ):
    """Fix 2 no-over-subtract: a FRESH session with a fresh corroborating hold is
    NOT added (session_is_stale False, both other axes False)."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _fresh_hold( "peer:maria" ) )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "mr radio", "session_id": "s1",
                     "holding_on": "peer:maria", "last_activity_ts": _FRESH_TS } }
    assert job._stale_hold_holders( view, now ) == set()


def test_stale_hold_holders_missing_ts_keeps_corroborating_hold( tmp_path ):
    """Fix 2 fail-safe: a missing/unparseable last_activity_ts → session_is_stale
    False → the corroborating-hold holder's edge is KEPT (never hide a live block)."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: _fresh_hold( "peer:maria" ) )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    missing = { "s1": { "persona": "mr radio", "session_id": "s1", "holding_on": "peer:maria" } }
    garbage = { "s2": { "persona": "cal", "session_id": "s2",
                        "holding_on": "peer:maria", "last_activity_ts": "not-a-ts" } }
    assert job._stale_hold_holders( missing, now ) == set()
    assert job._stale_hold_holders( garbage, now ) == set()


def test_stale_hold_holders_no_readable_hold_stale_session_still_not_added( tmp_path ):
    """Fix 2 contract preservation: session_is_stale stays INSIDE the `hold is not
    None` guard — a STALE session with NO readable hold is STILL not added here
    (absence ≠ deadness; build_graph's own per-session gate handles the no-hold dead
    session). Guards against the axis leaking outside the hold-subtraction contract."""
    job  = _make_job( tmp_path, hold_reader_fn=lambda sid: None )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    view = { "s1": { "persona": "ghost", "session_id": "s1",
                     "holding_on": "peer:maria", "last_activity_ts": _STALE_TS } }
    assert job._stale_hold_holders( view, now ) == set()


def test_poll_once_fresh_hold_awaiting_none_drops_phantom_edge( tmp_path ):
    """7f9a8ee2 DETERMINISTIC REPRO: mr radio's last_activity.awaiting is a STALE
    'peer:maria', but its CURRENT hold is fresh with awaiting='none'. The phantom
    'maria is blocking worker mr radio' edge must contribute ZERO edges → no cc DM,
    no advisory. (Pre-fix: hold_is_stale is False for a fresh hold → edge survived.)"""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:maria", persona="mr radio" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "mr radio", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw, hold_reader_fn=lambda sid: _fresh_hold( "none" ) )
    summary = job._poll_once()
    assert summary[ "edges" ]       == 0
    assert summary[ "pings_fired" ] == 0
    assert gw.sent == [ ]


def test_poll_once_fresh_hold_awaiting_matches_keeps_ping( tmp_path ):
    """7f9a8ee2 complement (no over-filter): a fresh hold whose awaiting MATCHES
    holding_on is a GENUINE wait → its edge survives → the blocker is still pinged."""
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:maria", persona="mr radio" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "mr radio", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw, hold_reader_fn=lambda sid: _fresh_hold( "peer:maria" ) )
    summary = job._poll_once()
    assert summary[ "edges" ]       == 1
    assert summary[ "pings_fired" ] == 1
    assert gw.sent[ 0 ][ 0 ] == "maria"


def test_poll_once_fresh_contradicting_hold_does_not_break_store_backed_deadlock( tmp_path ):
    """7f9a8ee2 test #7: the new reconciliation feeds ONLY the FILTERED advisory graph
    (build_graph); the deadlock ESCALATION reads the UNFILTERED build_wait_edges feed.
    A real store-backed alice↔bob ring STILL escalates even when alice's fresh hold
    contradicts (awaiting='none') and its advisory edge is dropped."""
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="peer:bob",   persona="alice" ) )
    _write_events( str( tmp_path ), "s2", _event( "s2", "honored", awaiting="peer:alice", persona="bob"   ) )
    gw = FakeGateway( who_rows=[
        { "session_id": "s1", "persona_name": "alice", "last_post_ts": NOW_ISO },
        { "session_id": "s2", "persona_name": "bob",   "last_post_ts": NOW_ISO },
    ] )
    store_cycle = {
        "alice": [ { "id": "a1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "bob" } ] } ],
        "bob":   [ { "id": "b1", "status": "in_progress", "gate_class": "none",
                     "blocked_by": [ { "kind": "persona", "id": "alice" } ] } ],
    }
    escal = [ ]
    job = _make_job( tmp_path, gateway=gw,
                     # alice's hold is FRESH but awaiting='none' (contradicts peer:bob) → her
                     # advisory edge is dropped; bob has no hold (edge kept either feed).
                     hold_reader_fn         = lambda sid: _fresh_hold( "none" ) if sid == "s1" else None,
                     owed_work_fn           = lambda names: store_cycle,
                     deadlock_dwell_seconds = 0,
                     notify_fn              = lambda msg, *a, **k: escal.append( msg ) )
    summary = job._poll_once()
    deadlock_msgs = [ m for m in escal if "DEADLOCK" in m and "store-corroborated" in m ]
    assert deadlock_msgs, escal
    assert "alice" in deadlock_msgs[ 0 ] and "bob" in deadlock_msgs[ 0 ]


def test_poll_once_dead_session_no_hold_excluded_from_ping_feed_confirming( tmp_path ):
    """7f9a8ee2 test #5, UPDATED for 8a450183: a DEAD/reaped session with a lingering
    stale holding_on=peer:X but NO hold file. Originally this proved the pre-existing
    alive-prune (live_edges @~1038, alive holders only) suppressed the PING without
    new code, while the dead edge still showed in summary["edges"]. The 8a450183
    per-SESSION freshness gate now ALSO drops that dead session's edge from the
    FILTERED advisory graph at ingestion (a strictly stronger fix that subsumes the
    secondary gap), so summary["edges"] (the FILTERED graph count) is now 0 — while
    the UNFILTERED :1018 escalation feed, which passes no now/threshold, is unchanged.
    pings_fired stays 0 (the operator-observable invariant)."""
    old_ts = "2026-06-05T11:00:00+00:00"          # 1h before NOW → beyond alive_threshold(600s) → alive=False
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:maria", persona="ghost", ts=old_ts ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "ghost", "last_post_ts": old_ts } ] )
    job = _make_job( tmp_path, gateway=gw )        # NO hold_reader_fn → hold-reconciliation inert (isolates the session-freshness gate)
    summary = job._poll_once()
    assert summary[ "edges" ]       == 0           # 8a450183: dead SESSION dropped from the FILTERED graph at ingestion
    assert summary[ "pings_fired" ] == 0           # and (as before) no phantom ping fires
    assert gw.sent == [ ]                           # no cc DM emitted on its behalf


# ── _escalate_deadlocks ───────────────────────────────────────────────────────

def test_escalate_deadlocks_notifies( tmp_path ):
    """A STORE-CORROBORATED ring (dwell=0 → fires on first sight) escalates."""
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ), deadlock_dwell_seconds=0 )
    now = datetime.datetime.fromisoformat( NOW_ISO )
    store_edges = { "alice": { "bob" }, "bob": { "alice" } }       # corroborates Alice↔Bob
    job._escalate_deadlocks( [ [ "Alice", "Bob" ] ], store_edges, now )
    assert fired and "DEADLOCK" in fired[ 0 ] and "store-corroborated" in fired[ 0 ]


def test_escalate_deadlocks_noop_when_empty( tmp_path ):
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ) )
    now = datetime.datetime.fromisoformat( NOW_ISO )
    job._escalate_deadlocks( [ ], { }, now )
    assert fired == [ ]


def test_escalate_deadlocks_suppressed_without_store_backing( tmp_path ):
    """Bug 436a366b: a derived ring with NO corroborating store edges does NOT
    escalate (the false-fire we are killing) — even past the dwell."""
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ), deadlock_dwell_seconds=0 )
    now = datetime.datetime.fromisoformat( NOW_ISO )
    job._escalate_deadlocks( [ [ "Alice", "Bob" ] ], { }, now )    # empty store_edges → not corroborated
    assert fired == [ ]


def test_escalate_deadlocks_dwell_belt_suppresses_fresh_ring( tmp_path ):
    """Progressing-wait belt: a store-backed ring younger than deadlock_dwell_seconds
    is suppressed on first sight, then escalates ONCE after the dwell, and a SECOND
    poll past the dwell does NOT re-escalate (de-dup)."""
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ), deadlock_dwell_seconds=300 )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    store_edges = { "alice": { "bob" }, "bob": { "alice" } }
    cycles      = [ [ "Alice", "Bob" ] ]
    job._escalate_deadlocks( cycles, store_edges, now )                                  # fresh → recorded, suppressed
    assert fired == [ ]
    job._escalate_deadlocks( cycles, store_edges, now + datetime.timedelta( seconds=200 ) )   # still within dwell
    assert fired == [ ]
    job._escalate_deadlocks( cycles, store_edges, now + datetime.timedelta( seconds=400 ) )   # past dwell → fire ONCE
    assert len( fired ) == 1
    job._escalate_deadlocks( cycles, store_edges, now + datetime.timedelta( seconds=500 ) )   # de-dup: no re-fire
    assert len( fired ) == 1


def test_escalate_deadlocks_rearms_after_ring_resolves( tmp_path ):
    """A resolved ring (gone from this poll) prunes its first-seen + escalated
    state, so a genuine RECURRENCE re-arms and can escalate again."""
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ), deadlock_dwell_seconds=0 )
    now  = datetime.datetime.fromisoformat( NOW_ISO )
    store_edges = { "alice": { "bob" }, "bob": { "alice" } }
    cycles      = [ [ "Alice", "Bob" ] ]
    job._escalate_deadlocks( cycles, store_edges, now )                                  # fires once
    assert len( fired ) == 1
    job._escalate_deadlocks( [ ], { }, now + datetime.timedelta( seconds=10 ) )          # ring gone → prune/re-arm
    assert ( "Alice", "Bob" ) not in job._deadlock_escalated
    job._escalate_deadlocks( cycles, store_edges, now + datetime.timedelta( seconds=20 ) )   # recurrence fires again
    assert len( fired ) == 2


# ── _prune_recent_pings ───────────────────────────────────────────────────────

def test_prune_recent_pings_drops_old( tmp_path ):
    import datetime
    job = _make_job( tmp_path, ping_cap_window_seconds=100 )
    now = datetime.datetime.fromisoformat( NOW_ISO )
    job._recent_pings = [
        now - datetime.timedelta( seconds=200 ),     # old → dropped
        now - datetime.timedelta( seconds=10 ),      # recent → kept
    ]
    job._prune_recent_pings( now )
    assert len( job._recent_pings ) == 1


# NOTE (2b-2 Part-6 #6): `_surface_to_manager` is DELETED — the per-tick roster
# broadcast is dropped (pull-state via /state). Its former tests are removed;
# the negative receipt (no roster post) is asserted by
# test_poll_once_builds_view_no_roster_broadcast above and the integration suite.


# ── _execute lifecycle + do_all ───────────────────────────────────────────────

def test_execute_cancelled_exits( tmp_path ):
    job = _make_job( tmp_path )
    job._cancel_requested = True
    summary = job.do_all()
    assert "cancelled" in summary


def test_execute_hard_cap_exits_after_polls( tmp_path ):
    _write_events( str( tmp_path ), "s1", _event( "s1", "idle", persona="A" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "last_post_ts": NOW_ISO } ] )
    # monotonic: start=0, check1=0 (<cap → poll), check2=100 (>=cap → exit)
    clk = FakeClock( monotonic_seq=[ 0, 0, 100 ] )
    job = _make_job( tmp_path, gateway=gw, clock=clk, max_duration_seconds=100 )
    summary = job.do_all()
    assert "hard-cap" in summary
    assert job._poll_count == 1
    assert clk.sleeps == [ 5 ]                       # slept once (poll_seconds)


def test_execute_swallows_poll_exception_transient_logs_not_escalates( tmp_path, monkeypatch ):
    """Part-6 #12: ONE poll error is TRANSIENT — DEMOTED to a render-sink log, NOT
    escalated to Rick (notify_fn). The loop survives."""
    errs, logs = [ ], [ ]
    clk  = FakeClock( monotonic_seq=[ 0, 0, 100 ] )
    job  = _make_job( tmp_path, clock=clk, notify_fn=lambda m: errs.append( m ),
                      render_sink=logs.append, max_duration_seconds=100 )   # threshold default 3
    monkeypatch.setattr( job, "_poll_once", lambda: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    summary = job.do_all()
    assert "hard-cap" in summary                     # loop survived the bad poll
    assert errs == [ ]                               # #12: NOT escalated to Rick on a one-off
    assert any( "poll-error (transient" in l and "boom" in l for l in logs )


def test_execute_persistent_poll_error_escalates_once( tmp_path, monkeypatch ):
    """Part-6 #12: at ≥ poll_error_escalate_threshold consecutive failures the
    arbiter IS escalated to Rick (notify_fn) — ONCE, 'effectively down'."""
    errs = [ ]
    clk  = FakeClock( monotonic_seq=[ 0, 0, 0, 100 ] )                       # two polls, then exit
    job  = _make_job( tmp_path, clock=clk, notify_fn=lambda m: errs.append( m ),
                      poll_error_escalate_threshold=2, max_duration_seconds=100 )
    monkeypatch.setattr( job, "_poll_once", lambda: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    summary = job.do_all()
    assert "hard-cap" in summary
    assert len( errs ) == 1                          # escalated once on the 2nd consecutive failure
    assert "POLL-ERROR persistent" in errs[ 0 ] and "Rick" in errs[ 0 ]


def test_do_all_stamps_timestamps( tmp_path ):
    job = _make_job( tmp_path )
    job._cancel_requested = True
    job.do_all()
    assert job.started_at is not None and job.completed_at is not None


# ── v2.2 B5: composed _poll_once integration (all detectors wired together) ─────

def test_poll_once_composes_all_v2_2_detectors( tmp_path ):
    """One full poll runs tap + ack-check + decision-needed + stall together and
    returns the composed v2.2 summary keys — proving the lanes integrate."""
    # s1: two cap_reached+owed → STUCK → attention → manager tap.
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "cap_reached", work_owed=True, persona="Stuckie",
                           ts="2026-06-05T11:58:00+00:00", poke_count=3 ),
                   _event( "s1", "cap_reached", work_owed=True, persona="Stuckie",
                           ts="2026-06-05T11:59:00+00:00", poke_count=3 ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Stuckie", "last_post_ts": NOW_ISO } ] )
    job = _make_job(
        tmp_path, gateway=gw,
        resolve_manager_fn=lambda sid, declared_manager=None: {
            "manager_session_id": "m1", "manager_persona": "MgrX", "source": "lineage" },
    )
    summary = job._poll_once()

    # composed summary surface
    for key in ( "taps_fired", "managers_down", "decisions", "stalled", "rendered" ):
        assert key in summary
    assert summary[ "taps_fired" ] == 1                 # MgrX tapped for stuck Stuckie
    assert gw.sent and gw.sent[ -1 ][ 0 ] == "MgrX"
    assert summary[ "decisions" ] == 0                  # FakeGateway.read → []
    assert summary[ "stalled" ] == 0                    # first poll = progress baseline
    assert summary[ "managers_down" ] == 0             # MgrX just tapped, ack window open
    assert "do not assign" in gw.sent[ -1 ][ 1 ].lower()   # advisory framing carried through


# ── declared-manager roster (COSA_VOICE_MANAGERS__<PROJECT>, Rick 2026-06-11) ──

class TestDeclaredManagers:
    """declared_managers wiring: fallback head, list copy, default-resolver fold,
    snapshot pass-through. Role-only — allocation is untouched."""

    def test_default_empty_roster_falls_back_to_manager_recipient( self, tmp_path ):
        job = _make_job( tmp_path )
        assert job.declared_managers == [ ]
        assert job.declared_fallback_manager == "Tiberius"      # = manager_recipient

    def test_roster_head_outranks_manager_recipient( self, tmp_path ):
        job = _make_job( tmp_path, declared_managers=[ "Mr. Radio", "Tiberius" ] )
        assert job.declared_managers == [ "Mr. Radio", "Tiberius" ]
        assert job.declared_fallback_manager == "Mr. Radio"

    def test_roster_is_copied_not_aliased( self, tmp_path ):
        roster = [ "Mr. Radio" ]
        job    = _make_job( tmp_path, declared_managers=roster )
        roster.append( "Imposter" )
        assert job.declared_managers == [ "Mr. Radio" ]

    def test_default_active_resolver_folds_declared_roster( self, tmp_path, monkeypatch ):
        # The production default seam must thread declared_managers through to
        # manager_resolver.resolve_active_managers (the Part-6 fanout source).
        import cosa.agents.heartbeat_arbiter.arbiter_job as aj
        calls = [ ]
        def fake_resolver( who_rows, bridge_sessions, declared_managers=None ):
            calls.append( ( who_rows, bridge_sessions, declared_managers ) )
            return [ "Mr. Radio" ]
        monkeypatch.setattr( aj, "_default_resolve_active_managers", fake_resolver )
        job = _make_job( tmp_path, declared_managers=[ "Mr. Radio" ],
                         resolve_active_managers_fn=None )      # force the production default
        assert job._active_managers( [ ], { "s": "Mr. Radio" } ) == [ "Mr. Radio" ]
        assert calls == [ ( [ ], { "s": "Mr. Radio" }, [ "Mr. Radio" ] ) ]

    def test_injected_active_resolver_seam_signature_unchanged( self, tmp_path ):
        # Existing fakes keep their two-arg signature — the fold lives ONLY in
        # the production default.
        job = _make_job( tmp_path, declared_managers=[ "Mr. Radio" ],
                         resolve_active_managers_fn=lambda w, b: [ "Custom" ] )
        assert job._active_managers( [ ], { } ) == [ "Custom" ]

    def test_publish_snapshot_passes_declared_to_build_snapshot( self, tmp_path, monkeypatch ):
        import datetime as _dt
        import cosa.agents.heartbeat_arbiter.arbiter_job as aj
        seen = { }
        def fake_build_snapshot( fleet_view, bridge_mtimes, now, **kwargs ):
            seen.update( kwargs )
            return { "generated_at": now.isoformat(), "session_count": 0, "sessions": [ ] }
        monkeypatch.setattr( aj, "build_snapshot", fake_build_snapshot )
        job = _make_job( tmp_path, declared_managers=[ "Mr. Radio", "Tiberius" ],
                         snapshot_sink=lambda snap: None, render_sink=lambda line: None,
                         bridge_mtime_fn=lambda sid: None )
        job._publish_fleet_snapshot( { }, _dt.datetime( 2026, 6, 11, tzinfo=_dt.timezone.utc ) )
        assert seen[ "declared_managers" ] == [ "Mr. Radio", "Tiberius" ]


# ── eng#7: follow-through aged-escalation watcher wiring (build-plan §3b) ───────
#
# Proves (a) the watcher rides the poll path (sweep_once invoked from _poll_once),
# (b) the factory seam is invoked ONCE at construction with the job (chicken-egg
# resolver), (c) the `follow through escalation enabled`=False flag gates it OFF
# end-to-end through a REAL watcher, and (d) the sweep is swallow-safe + inert when
# unwired. Lane: Rachel (eng#7 wiring). Manager: Mr. Radio.

class _FakeFollowThroughWatcher:
    """Records sweep_once() calls; returns a scripted result or raises."""
    def __init__( self, result=None, raises=False ):
        self._result = result
        self._raises  = raises
        self.calls    = 0
    def sweep_once( self ):
        self.calls += 1
        if self._raises:
            raise RuntimeError( "sweep boom" )
        return self._result


class _FakeCfg:
    """Minimal ConfigurationManager stand-in for the REAL watcher's flag read."""
    def __init__( self, values ):
        self._v = values
    def get( self, key, default=None, return_type=None ):
        return self._v.get( key, default )


def test_follow_through_watcher_none_by_default( tmp_path ):
    # No factory wired (in-pool / unit-fake / legacy construction) → INERT.
    job = _make_job( tmp_path )
    assert job._follow_through_watcher is None
    assert job._sweep_follow_through() == 0                       # direct: None → 0
    summary = job._poll_once()
    assert summary[ "ft_escalated" ] == 0                         # poll-path: inert → 0


def test_follow_through_factory_invoked_once_with_job_at_construction( tmp_path ):
    seen    = [ ]
    watcher = _FakeFollowThroughWatcher( result={ "enabled": True, "escalated": 0, "candidates": 0 } )
    def fac( job ):
        seen.append( job )
        return watcher
    job = _make_job( tmp_path, follow_through_watcher_factory=fac )
    assert seen == [ job ]                                        # called ONCE, with the job itself
    assert job._follow_through_watcher is watcher                 # the chicken-egg resolver bound it


def test_follow_through_sweep_invoked_from_poll_path_and_counted( tmp_path ):
    watcher = _FakeFollowThroughWatcher( result={ "enabled": True, "escalated": 2, "candidates": 3 } )
    job     = _make_job( tmp_path, follow_through_watcher_factory=lambda j: watcher )
    summary = job._poll_once()
    assert watcher.calls == 1                                     # swept exactly once from _poll_once
    assert summary[ "ft_escalated" ] == 2                         # escalated count surfaced in the summary


def test_follow_through_flag_off_gates_sweep_off_through_real_watcher( tmp_path ):
    # The activation gate proof: a REAL FollowThroughEscalationWatcher with the
    # enable flag FALSE → sweep_once short-circuits (no DB, no escalate_fn) → 0.
    from cosa.rest.follow_through_escalation_watcher import FollowThroughEscalationWatcher
    escalations = [ ]
    watcher = FollowThroughEscalationWatcher(
        _FakeCfg( { "follow through escalation enabled": False } ),
        escalate_fn = lambda *a: escalations.append( a ),
    )
    job     = _make_job( tmp_path, follow_through_watcher_factory=lambda j: watcher )
    summary = job._poll_once()
    assert summary[ "ft_escalated" ] == 0                         # flag OFF → zero escalations
    assert escalations == [ ]                                     # escalate_fn never fired


def test_follow_through_sweep_swallows_exception( tmp_path ):
    # Observer invariant: a watcher hiccup is demoted to a render-sink line, not a
    # dead poll. (sweep_once raises only on THIS direct path — its daemon _loop is
    # bypassed — so the guard lives in _sweep_follow_through.)
    rendered = [ ]
    watcher  = _FakeFollowThroughWatcher( raises=True )
    job      = _make_job( tmp_path, follow_through_watcher_factory=lambda j: watcher,
                          render_sink=rendered.append )
    assert job._sweep_follow_through() == 0                       # swallowed → 0
    assert any( "follow-through sweep error" in line for line in rendered )
    # and the whole poll still completes (never raises)
    assert job._poll_once()[ "ft_escalated" ] == 0


def test_follow_through_sweep_non_dict_result_returns_zero( tmp_path ):
    # A non-dict sweep_once result (defensive) → 0, never an attribute error.
    watcher = _FakeFollowThroughWatcher( result=None )
    job     = _make_job( tmp_path, follow_through_watcher_factory=lambda j: watcher )
    assert job._sweep_follow_through() == 0
    assert watcher.calls == 1


# ── §4b worktree janitor seam (Worktree Lifecycle Contract) ─────────────────────

def test_worktree_janitor_inert_by_default( tmp_path ):
    # None seam → no reconcile, byte-identical to today; summary reports 0.
    summary = _make_job( tmp_path )._poll_once()
    assert summary[ "worktrees_swept" ] == 0


def test_worktree_janitor_fires_when_wired( tmp_path ):
    calls = []
    def janitor():
        calls.append( 1 )
        return { "swept": [ { "path": "/wt/a" }, { "path": "/wt/b" } ], "skipped": [], "errors": [] }
    summary = _make_job( tmp_path, worktree_janitor_fn=janitor )._poll_once()
    assert calls == [ 1 ]                        # invoked exactly once per poll
    assert summary[ "worktrees_swept" ] == 2     # swept-count surfaced to the journal


def test_worktree_janitor_hiccup_is_swallowed( tmp_path ):
    # Observer invariant: a reconcile exception must NOT kill the poll.
    def janitor(): raise RuntimeError( "reconcile boom" )
    summary = _make_job( tmp_path, worktree_janitor_fn=janitor )._poll_once()
    assert summary[ "worktrees_swept" ] == 0     # demoted to 0, poll completes


# ── ee59d5ed ORPHAN-BRIDGE JANITOR: per-poll lineage-independent reap seam ───────

def test_bridge_sweep_inert_by_default( tmp_path ):
    # None seam → no sweep, byte-identical to today; summary reports 0.
    summary = _make_job( tmp_path )._poll_once()
    assert summary[ "bridges_reaped" ] == 0


def test_bridge_sweep_fires_when_wired( tmp_path ):
    calls = []
    def sweep():
        calls.append( 1 )
        return { "reaped": [ { "session_id": "s-1" }, { "session_id": "s-2" } ],
                 "skipped": [], "errors": [] }
    summary = _make_job( tmp_path, bridge_sweep_fn=sweep )._poll_once()
    assert calls == [ 1 ]                         # invoked exactly once per poll
    assert summary[ "bridges_reaped" ] == 2       # reaped-count surfaced to the journal


def test_bridge_sweep_hiccup_is_swallowed( tmp_path ):
    # Observer invariant: a sweep exception must NOT kill the poll.
    def sweep(): raise RuntimeError( "sweep boom" )
    summary = _make_job( tmp_path, bridge_sweep_fn=sweep )._poll_once()
    assert summary[ "bridges_reaped" ] == 0       # demoted to 0, poll completes


def test_bridge_sweep_non_dict_return_counts_zero( tmp_path ):
    # A seam returning a non-dict (contract violation) is demoted to 0, not crashed.
    summary = _make_job( tmp_path, bridge_sweep_fn=lambda: None )._poll_once()
    assert summary[ "bridges_reaped" ] == 0


# ── 8a450183 PERSONA-COLLAPSE: dead session's stale edge on a live persona ───────

def test_poll_once_dead_session_same_persona_no_phantom_ping( tmp_path ):
    """Bug 8a450183 (the committed gap-closer): a DEAD session and a LIVE session
    SHARE persona 'mr radio'. The dead session's last activity is ~12h stale and its
    `awaiting=peer:maria` lingers; the live session is fresh and awaiting nothing.

    Pre-fix: the dead session's `mr radio→maria` edge survives the per-PERSONA
    `alive_personas` filter (the persona is alive via the LIVE session — the
    persona-collapse) → a phantom 'maria is blocking worker mr radio' ping fires
    every poll. This dual-session-same-persona case had ZERO test coverage.

    Post-fix: the per-SESSION freshness gate drops the dead session's edge at
    INGESTION (keyed by session-id, before the holder→persona collapse), with NO
    hold_reader wired — so this proves A1 (session-keyed) + A3 (explicit ts, not
    view['alive']) INDEPENDENTLY of the bc1bc373/7f9a8ee2 hold filters."""
    old_ts = ( datetime.datetime.fromisoformat( NOW_ISO ) - datetime.timedelta( hours=12 ) ).isoformat()
    _write_events( str( tmp_path ), "s_dead",
                   _event( "s_dead", "honored", awaiting="peer:maria", persona="mr radio", ts=old_ts ) )
    _write_events( str( tmp_path ), "s_live",
                   _event( "s_live", "honored", awaiting="none", persona="mr radio", ts=NOW_ISO ) )
    # s_live is bridge-present + commons-fresh → alive; s_dead is bridge-ABSENT
    # (its commons echo, if any, is phantom-nulled) → offline, ~12h stale.
    gw  = FakeGateway( who_rows=[ { "session_id": "s_live", "persona_name": "mr radio", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw, bridge_discovery_fn=lambda: { "s_live": "mr radio" } )
    summary = job._poll_once()
    assert summary[ "pings_fired" ] == 0          # no phantom 'maria blocking mr radio'
    assert gw.sent == [ ]                         # nothing sent to maria
    assert summary[ "edges" ] == 0               # live same-persona session not over-filtered into an edge
