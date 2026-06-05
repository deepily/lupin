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

    def send_to( self, recipient, body ):
        self.sent.append( ( recipient, body ) )

    def post( self, topic, body ):
        self.posts.append( ( topic, body ) )


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


# ── _poll_once composition ────────────────────────────────────────────────────

def test_poll_once_builds_view_and_surfaces( tmp_path ):
    _write_events( str( tmp_path ), "s1", _event( "s1", "honored", awaiting="none", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    summary = job._poll_once()
    assert summary[ "sessions" ] == 1
    assert job._poll_count == 1
    # manager surface posted to the roster topic
    assert gw.posts and gw.posts[ 0 ][ 0 ] == ROSTER_TOPIC


def test_poll_once_inference_idle_with_shipped_defaults( tmp_path ):
    """F3 end-to-end: an alive+quiet session lands on the roster as inference
    under the SHIPPED defaults (quiet 300 < alive 600) — the hybrid's inference
    half is alive, not config-dead. Drives real timestamps (no hardcoded alive)."""
    old_ts = "2026-06-05T11:53:20+00:00"          # 400s before NOW (12:00:00): 300 ≤ 400 ≤ 600
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "poke", awaiting="none", persona="Alice", ts=old_ts ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": old_ts } ] )
    job = _make_job( tmp_path, gateway=gw )        # shipped defaults: quiet=300, alive=600
    summary = job._poll_once()
    assert summary[ "roster" ] == 1
    assert "quiet (inferred)" in gw.posts[ 0 ][ 1 ]


def test_poll_once_auto_pings_blocker( tmp_path ):
    # s1 is HOLDING on peer:Bob → an edge s1→Bob → auto-ping Bob
    _write_events( str( tmp_path ), "s1",
                   _event( "s1", "honored", awaiting="peer:Bob", persona="Alice" ) )
    gw  = FakeGateway( who_rows=[ { "session_id": "s1", "persona_name": "Alice", "last_post_ts": NOW_ISO } ] )
    job = _make_job( tmp_path, gateway=gw )
    summary = job._poll_once()
    assert summary[ "edges" ] == 1
    assert summary[ "pings_fired" ] == 1
    assert gw.sent[ 0 ][ 0 ] == "Bob"
    assert "holding on you" in gw.sent[ 0 ][ 1 ]


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
        f.write( json.dumps( _event( "s1", "poke", awaiting="none", persona="A" ) ) + "\n" )
    job._poll_once()
    assert job._ledger.tracked_edges() == set()
    assert job._ping_attempts == { }


# ── _escalate_deadlocks ───────────────────────────────────────────────────────

def test_escalate_deadlocks_notifies( tmp_path ):
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ) )
    job._escalate_deadlocks( [ [ "Alice", "Bob" ] ] )
    assert fired and "DEADLOCK" in fired[ 0 ]


def test_escalate_deadlocks_noop_when_empty( tmp_path ):
    fired = [ ]
    job = _make_job( tmp_path, notify_fn=lambda m: fired.append( m ) )
    job._escalate_deadlocks( [ ] )
    assert fired == [ ]


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


# ── _surface_to_manager branches ──────────────────────────────────────────────

def test_surface_empty_fleet( tmp_path ):
    gw  = FakeGateway()
    job = _make_job( tmp_path, gateway=gw )
    job._surface_to_manager( { }, { "edges": { }, "cycles": [ ] }, [ ] )
    body = gw.posts[ 0 ][ 1 ]
    assert "Idle-roster: (none)" in body and "Blocked edges: (none)" in body


def test_surface_with_roster_edges_cycles_stuck( tmp_path ):
    gw  = FakeGateway()
    job = _make_job( tmp_path, gateway=gw )
    fleet_view = {
        "s1": { "session_id": "s1", "persona": "Alice", "stuck": True },
        "s2": { "session_id": "s2", "persona": "Bob", "stuck": False },
        "bad": "not-a-dict",                          # skipped by the stuck comprehension
    }
    graph  = { "edges": { "s1": "Bob" }, "cycles": [ [ "Alice", "Bob" ] ] }
    roster = [ { "session_id": "s2", "persona": "Bob", "trust_label": "quiet (inferred)" } ]
    job._surface_to_manager( fleet_view, graph, roster )
    body = gw.posts[ 0 ][ 1 ]
    assert "Bob [quiet (inferred)]" in body
    assert "s1→Bob" in body
    assert "DEADLOCK" in body
    assert "Stuck" in body and "s1" in body


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


def test_execute_swallows_poll_exception( tmp_path, monkeypatch ):
    errs = [ ]
    clk  = FakeClock( monotonic_seq=[ 0, 0, 100 ] )
    job  = _make_job( tmp_path, clock=clk, notify_fn=lambda m: errs.append( m ),
                      max_duration_seconds=100 )
    monkeypatch.setattr( job, "_poll_once", lambda: ( _ for _ in () ).throw( RuntimeError( "boom" ) ) )
    summary = job.do_all()
    assert "hard-cap" in summary                     # loop survived the bad poll
    assert errs and "arbiter poll error" in errs[ 0 ]


def test_do_all_stamps_timestamps( tmp_path ):
    job = _make_job( tmp_path )
    job._cancel_requested = True
    job.do_all()
    assert job.started_at is not None and job.completed_at is not None
