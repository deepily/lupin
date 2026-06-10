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
