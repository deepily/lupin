#!/usr/bin/env python3
"""
Unit tests for the context-headroom writer (the published per-persona service).

Venue: :7999-eligible (pure in-process — the leaf is faked/mocked, no live
bridges, no threads beyond the lifecycle test, no persistent state). Coverage
target: 100% line+branch+function on lupin_arbiter_app/context_pressure_writer.py.

Design under test (Rick's 5 locked decisions, 2026-06-09):
    src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.09-context-pressure-published-headroom-service-design.md
    §3 budget transform · §4 persona-keyed object · §9 testing plan
"""
import datetime
import json
import threading
import types

import pytest

from cosa.agents.heartbeat_arbiter.context_pressure import (
    ContextPressure, Liveness, PressureState, WorkerContextPressure,
)
from lupin_arbiter_app.context_pressure_writer import (
    SECTION_NAME, ContextPressureWriterLoop, _budget_fraction_for,
    _default_log_fn, _liveness_value, _persona_record, _unmeasured_status,
    build_context_pressure_section, quick_smoke_test,
)
from lupin_arbiter_app.local_snapshot_store import LocalSnapshotStore


FRACTIONS = { 1_000_000: 0.50, 200_000: 0.75, "default": 0.50 }
T0        = datetime.datetime( 2026, 6, 9, 17, 30, 0, tzinfo=datetime.timezone.utc )


# ── builders ─────────────────────────────────────────────────────────────────

def _pressure( window=1_000_000, occupancy=205_000, output=400, pending=1_000, state=PressureState.OK ):
    """One measured ContextPressure: next_prompt_estimate = occupancy + output + pending."""
    return ContextPressure(
        last_prompt_size       = occupancy,
        last_output_tokens     = output,
        pending_input_estimate = pending,
        next_prompt_estimate   = occupancy + output + pending,
        window_size            = window,
        effective_ceiling      = window,
        pct                    = 100.0 * ( occupancy + output + pending ) / window,
        state                  = state,
    )


def _worker( persona="Tiberius", session_id="7b76ad86", liveness=Liveness.ACTIVE,
             pressure=None, last_turn_age=41.0, recommendation="", tmux="__auto__" ):
    tmux_session = f"cc-{persona.lower()}" if tmux == "__auto__" and persona else tmux
    if tmux_session == "__auto__":
        tmux_session = None                       # persona=None with no explicit tmux
    return WorkerContextPressure(
        session_id    = session_id,
        persona       = persona,
        tmux_session  = tmux_session,
        liveness      = liveness,
        pressure      = pressure,
        last_turn_age = last_turn_age,
        recommendation= recommendation,
    )


class Recorder:
    """Collects structured log events."""
    def __init__( self ):
        self.logs = [ ]
    def log( self, event, **fields ):
        self.logs.append( ( event, fields ) )


class FakeClock:
    """Deterministic clock: fixed now(); sleep() can set a stop event after N calls."""
    def __init__( self, sleep_stops_after=None ):
        self._sleep_calls       = 0
        self._sleep_stops_after = sleep_stops_after
        self.stop_event         = None     # wired to the loop's _stop after construction
    def now( self ):
        return T0
    def sleep( self, seconds ):
        self._sleep_calls += 1
        if ( self._sleep_stops_after is not None
             and self._sleep_calls >= self._sleep_stops_after
             and self.stop_event is not None ):
            self.stop_event.set()


# ── policy lookup + tiny helpers ─────────────────────────────────────────────

def test_budget_fraction_for_mapped_and_default():
    assert _budget_fraction_for( 1_000_000, FRACTIONS ) == 0.50
    assert _budget_fraction_for( 200_000, FRACTIONS )   == 0.75
    assert _budget_fraction_for( 500_000, FRACTIONS )   == 0.50    # unmapped → default


def test_liveness_value_enum_and_plain_string():
    assert _liveness_value( Liveness.ACTIVE ) == "ACTIVE"          # str-Enum .value arm
    assert _liveness_value( "IDLE" )          == "IDLE"            # plain-string arm


def test_unmeasured_status_mapping():
    assert _unmeasured_status( "IDLE" )   == "idle"
    assert _unmeasured_status( "DEAD" )   == "dead"
    assert _unmeasured_status( "ACTIVE" ) == "unknown"             # ACTIVE, no assistant turn yet


def test_default_log_fn_emits_one_json_line( capsys ):
    _default_log_fn( "test_event", detail="x" )
    line = json.loads( capsys.readouterr().out.strip() )
    assert line[ "event" ] == "test_event" and line[ "detail" ] == "x"
    assert line[ "loop" ]  == "context_pressure_writer"


# ── §3 budget transform — measured records ───────────────────────────────────

def test_measured_1m_worker_worked_example():
    """The §3 worked example: 1M worker at 205k → ceiling 500k, headroom 295k, 20.5%/29.5pts."""
    rec = _persona_record( _worker( pressure=_pressure() ), FRACTIONS )
    assert rec[ "window_size" ]               == 1_000_000
    assert rec[ "budget_fraction" ]           == 0.50
    assert rec[ "budget_ceiling_tokens" ]     == 500_000
    assert rec[ "occupancy_tokens" ]          == 205_000
    assert rec[ "next_prompt_estimate" ]      == 206_400
    assert rec[ "consumption_pct_of_window" ] == 20.5
    assert rec[ "headroom_tokens_current" ]   == 295_000
    assert rec[ "headroom_tokens_forward" ]   == 293_600
    assert rec[ "headroom_pct_points" ]       == 29.5
    assert rec[ "status" ]                    == "within_budget"
    assert rec[ "liveness" ]                  == "ACTIVE"
    assert rec[ "last_turn_age_s" ]           == 41.0
    # Rachel's §3 per-worker facts ride along (the superset fold, Decision 4)
    assert rec[ "pressure_state" ]            == "OK"
    assert rec[ "pending_input_estimate" ]    == 1_000
    assert rec[ "tmux_session" ]              == "cc-tiberius"


def test_measured_200k_worker_uses_075_line():
    rec = _persona_record( _worker( pressure=_pressure( window=200_000, occupancy=120_000 ) ), FRACTIONS )
    assert rec[ "budget_fraction" ]         == 0.75
    assert rec[ "budget_ceiling_tokens" ]   == 150_000
    assert rec[ "headroom_tokens_current" ] == 30_000
    assert rec[ "status" ]                  == "within_budget"


def test_measured_unmapped_window_falls_back_to_default_fraction():
    rec = _persona_record( _worker( pressure=_pressure( window=500_000, occupancy=100_000 ) ), FRACTIONS )
    assert rec[ "budget_fraction" ]       == 0.50
    assert rec[ "budget_ceiling_tokens" ] == 250_000


def test_measured_over_budget_is_sign_honest_negative():
    """Over the line → NEGATIVE headroom (never clamped) + over_budget status."""
    rec = _persona_record( _worker( pressure=_pressure( window=200_000, occupancy=180_000,
                                                        output=0, pending=0,
                                                        state=PressureState.CRITICAL ) ), FRACTIONS )
    assert rec[ "headroom_tokens_current" ] == -30_000
    assert rec[ "headroom_tokens_forward" ] == -30_000
    assert rec[ "headroom_pct_points" ]     == -15.0
    assert rec[ "status" ]                  == "over_budget"
    assert rec[ "pressure_state" ]          == "CRITICAL"


def test_measured_plain_string_duck_worker():
    """Duck-typed worker with PLAIN strings (no .value) covers the non-Enum arms + last_turn_age None."""
    pressure = types.SimpleNamespace(
        state="OK", window_size=1_000_000, last_prompt_size=10_000,
        next_prompt_estimate=11_000, pct=1.1, pending_input_estimate=0,
    )
    worker = types.SimpleNamespace(
        session_id="s-duck", persona="Duck", tmux_session=None, liveness="ACTIVE",
        pressure=pressure, last_turn_age=None, recommendation="",
    )
    rec = _persona_record( worker, FRACTIONS )
    assert rec[ "liveness" ]        == "ACTIVE"
    assert rec[ "pressure_state" ]  == "OK"
    assert rec[ "last_turn_age_s" ] is None
    assert rec[ "status" ]          == "within_budget"


# ── unmeasured records — no false zero ───────────────────────────────────────

def test_idle_worker_publishes_nulls_and_idle_status():
    rec = _persona_record( _worker( persona="maria", liveness=Liveness.IDLE,
                                    pressure=None, last_turn_age=2000.46 ), FRACTIONS )
    assert rec[ "occupancy_tokens" ]        is None
    assert rec[ "next_prompt_estimate" ]    is None
    assert rec[ "headroom_tokens_current" ] is None
    assert rec[ "headroom_tokens_forward" ] is None
    assert rec[ "window_size" ]             is None    # IDLE skips the read — window never resolved
    assert rec[ "budget_fraction" ]         is None
    assert rec[ "budget_ceiling_tokens" ]   is None
    assert rec[ "pressure_state" ]          is None
    assert rec[ "pending_input_estimate" ]  is None
    assert rec[ "status" ]                  == "idle"
    assert rec[ "liveness" ]                == "IDLE"
    assert rec[ "last_turn_age_s" ]         == 2000.5


def test_dead_worker_publishes_dead_status():
    rec = _persona_record( _worker( liveness=Liveness.DEAD, pressure=None ), FRACTIONS )
    assert rec[ "status" ] == "dead" and rec[ "occupancy_tokens" ] is None


def test_active_no_assistant_turn_yet_is_unknown_not_zero():
    """ACTIVE + state UNKNOWN: the leaf reports occupancy 0 — we publish null, never the false zero."""
    pressure = _pressure( occupancy=0, output=0, pending=37, state=PressureState.UNKNOWN )
    rec      = _persona_record( _worker( pressure=pressure ), FRACTIONS )
    assert rec[ "occupancy_tokens" ]       is None
    assert rec[ "status" ]                 == "unknown"
    # the window WAS resolved (pressure present) → budget context still published
    assert rec[ "window_size" ]            == 1_000_000
    assert rec[ "budget_ceiling_tokens" ]  == 500_000
    assert rec[ "pressure_state" ]         == "UNKNOWN"
    assert rec[ "pending_input_estimate" ] == 37


# ── §4 section: persona keying + policy echo + summary ───────────────────────

def test_section_keys_by_persona_with_summary_counts():
    workers = [
        _worker( persona="Tiberius", session_id="7b76ad86", pressure=_pressure() ),
        _worker( persona="Rachel",   session_id="6fc52b2e",
                 pressure=_pressure( window=200_000, occupancy=180_000, output=0, pending=0,
                                     state=PressureState.CRITICAL ) ),
        _worker( persona="maria",    session_id="42954f0b", liveness=Liveness.IDLE, pressure=None ),
        _worker( persona="Krishna",  session_id="e260f79d",
                 pressure=_pressure( occupancy=0, output=0, pending=0, state=PressureState.UNKNOWN ) ),
    ]
    section = build_context_pressure_section( workers, budget_fractions=FRACTIONS,
                                              generated_at=T0.isoformat() )
    assert section[ "generated_at" ] == "2026-06-09T17:30:00+00:00"
    assert section[ "policy" ]       == { "1000000": 0.50, "200000": 0.75, "default": 0.50 }
    assert set( section[ "personas" ].keys() ) == { "Tiberius", "Rachel", "maria", "Krishna" }
    assert section[ "personas" ][ "Tiberius" ][ "session_id" ] == "7b76ad86"
    assert section[ "unnamed_seats" ] == [ ]      # all four are named
    assert section[ "summary" ] == {
        "personas"           : 4,
        "unnamed_live_seats" : 0,
        "within_budget"      : 1,
        "over_budget"        : 1,
        "idle_or_unknown"    : 2,    # the IDLE worker + the no-turn-yet unknown
    }


def test_section_empty_fleet():
    section = build_context_pressure_section( [ ], budget_fractions=FRACTIONS,
                                              generated_at=T0.isoformat() )
    assert section[ "personas" ] == { }
    assert section[ "unnamed_seats" ] == [ ]
    assert section[ "summary" ]  == { "personas": 0, "unnamed_live_seats": 0,
                                      "within_budget": 0, "over_budget": 0, "idle_or_unknown": 0 }


# ── row 9c720767: a live seat with NO persona must be REPORTED, not omitted ───
# The payload is keyed by persona, so a nameless seat has no key and — before
# this fix — collapses under a single null key or vanishes entirely: silence and
# absence look identical. A nameless seat is exactly the seat nobody is watching.
# It must appear EXPLICITLY, with persona null and its age, so it is visible AS a
# problem rather than missing from the list.
def test_nameless_live_seat_is_reported_explicitly_not_swallowed():
    """A persona=None worker must surface in `unnamed_seats` with persona null +
    its age, and be counted in the summary — never buried under a null key in
    the persona-keyed map (where a second nameless seat would overwrite it)."""
    workers = [
        _worker( persona="Tiberius", session_id="7b76ad86", pressure=_pressure() ),
        _worker( persona=None, session_id="a1b2c3d4", tmux=None,
                 liveness=Liveness.ACTIVE, pressure=None, last_turn_age=2400.0 ),
        _worker( persona=None, session_id="e5f6a7b8", tmux=None,
                 liveness=Liveness.ACTIVE, pressure=None, last_turn_age=45.0 ),
    ]
    section = build_context_pressure_section( workers, budget_fractions=FRACTIONS,
                                              generated_at=T0.isoformat() )
    # named seats keep the persona-keyed map to themselves — no null key
    assert set( section[ "personas" ].keys() ) == { "Tiberius" }
    assert None not in section[ "personas" ]
    # BOTH nameless seats survive as explicit rows (a keyed map would keep only one)
    unnamed = section[ "unnamed_seats" ]
    assert len( unnamed ) == 2
    by_sid = { r[ "session_id" ]: r for r in unnamed }
    assert by_sid[ "a1b2c3d4" ][ "persona" ]         is None       # persona null, stated
    assert by_sid[ "a1b2c3d4" ][ "last_turn_age_s" ] == 2400.0     # its age — 40 min nameless
    assert by_sid[ "e5f6a7b8" ][ "last_turn_age_s" ] == 45.0
    assert section[ "summary" ][ "unnamed_live_seats" ] == 2
    assert section[ "summary" ][ "personas" ]           == 1


def test_nameless_over_budget_seat_still_counts_in_status_summary():
    """A nameless seat that is over budget must count in the over_budget bucket —
    the whole point is that its pressure is not lost just because it has no name."""
    hot = _worker( persona=None, session_id="hot0seat", tmux=None,
                   pressure=_pressure( window=200_000, occupancy=180_000, output=0,
                                       pending=0, state=PressureState.CRITICAL ) )
    section = build_context_pressure_section( [ hot ], budget_fractions=FRACTIONS,
                                              generated_at=T0.isoformat() )
    assert section[ "summary" ][ "over_budget" ]        == 1
    assert section[ "summary" ][ "unnamed_live_seats" ] == 1
    assert section[ "unnamed_seats" ][ 0 ][ "status" ]  == "over_budget"


def test_section_is_json_serialisable():
    section = build_context_pressure_section( [ _worker( pressure=_pressure() ) ],
                                              budget_fractions=FRACTIONS,
                                              generated_at=T0.isoformat() )
    assert json.loads( json.dumps( section ) ) == section


# ── the loop ─────────────────────────────────────────────────────────────────

def _loop( assess_fn, rec, store=None, **kw ):
    return ContextPressureWriterLoop(
        assess_fn, store if store is not None else LocalSnapshotStore(),
        budget_fractions = FRACTIONS,
        clock            = kw.pop( "clock", FakeClock() ),
        log_fn           = rec.log,
        **kw,
    )


def test_init_rejects_missing_default_fraction():
    with pytest.raises( ValueError, match="default" ):
        ContextPressureWriterLoop( lambda: [ ], LocalSnapshotStore(),
                                   budget_fractions={ 1_000_000: 0.50 } )


def test_init_rejects_non_positive_interval():
    with pytest.raises( ValueError, match="interval_seconds" ):
        ContextPressureWriterLoop( lambda: [ ], LocalSnapshotStore(),
                                   budget_fractions=FRACTIONS, interval_seconds=0 )


def test_poll_once_writes_persona_keyed_section_and_logs():
    rec, store = Recorder(), LocalSnapshotStore()
    loop = _loop( lambda **kw: [ _worker( pressure=_pressure() ) ], rec, store=store )
    assert loop.poll_once() is True
    section = store.get_section( SECTION_NAME )
    assert section[ "personas" ][ "Tiberius" ][ "headroom_tokens_current" ] == 295_000
    assert section[ "generated_at" ] == T0.isoformat()
    assert any( ev == "context_pressure_written" and f[ "summary" ][ "within_budget" ] == 1
                for ev, f in rec.logs )


def test_poll_once_passes_leaf_kwargs_through():
    rec, captured = Recorder(), { }
    def assess( **kw ):
        captured.update( kw )
        return [ ]
    loop = _loop( assess, rec, leaf_kwargs={ "warn_pct": 70.0, "idle_mtime_seconds": 1800 } )
    loop.poll_once()
    assert captured == { "warn_pct": 70.0, "idle_mtime_seconds": 1800 }


def test_poll_once_assess_failure_logged_and_section_untouched():
    """A leaf failure never kills the tick; the previously-written section survives (stale beats absent)."""
    rec, store = Recorder(), LocalSnapshotStore()
    store.set_section( SECTION_NAME, { "personas": { "prior": { } } } )
    def boom( **kw ):
        raise RuntimeError( "bridge walk exploded" )
    loop = _loop( boom, rec, store=store )
    assert loop.poll_once() is False
    assert store.get_section( SECTION_NAME ) == { "personas": { "prior": { } } }
    assert any( ev == "assess_error" and "bridge walk exploded" in f[ "error" ] for ev, f in rec.logs )


def test_default_seams_resolve( capsys ):
    """No clock/log_fn injected → SystemClock + the structured default logger."""
    store = LocalSnapshotStore()
    loop  = ContextPressureWriterLoop( lambda **kw: [ ], store, budget_fractions=FRACTIONS )
    assert loop.poll_once() is True
    assert store.get_section( SECTION_NAME )[ "summary" ][ "personas" ] == 0
    line = json.loads( capsys.readouterr().out.strip() )
    assert line[ "event" ] == "context_pressure_written"


def test_run_loop_polls_until_stopped():
    rec, store = Recorder(), LocalSnapshotStore()
    clock = FakeClock( sleep_stops_after=2 )
    loop  = _loop( lambda **kw: [ ], rec, store=store, clock=clock )
    clock.stop_event = loop._stop
    loop.run()                                                     # exits after 2 sleeps
    assert clock._sleep_calls == 2
    assert store.get_section( SECTION_NAME ) is not None


def test_run_loop_survives_poll_error():
    """The per-tick guard: a raising tick is logged, the loop keeps running."""
    rec   = Recorder()
    clock = FakeClock( sleep_stops_after=1 )
    loop  = _loop( lambda **kw: [ ], rec, clock=clock )
    clock.stop_event = loop._stop
    def explode():
        raise RuntimeError( "boom-tick" )
    loop.poll_once = explode
    loop.run()
    assert any( ev == "poll_error" and "boom-tick" in f[ "error" ] for ev, f in rec.logs )


def test_start_and_stop_lifecycle():
    rec, store = Recorder(), LocalSnapshotStore()
    wrote = threading.Event()

    class WaitClock:
        def now( self ):
            return T0
        def sleep( self, seconds ):
            wrote.set()                    # first tick done → let the test proceed
            threading.Event().wait( 0.005 )

    loop = _loop( lambda **kw: [ ], rec, store=store, clock=WaitClock() )
    loop.start()
    assert wrote.wait( timeout=5 ) is True
    loop.stop()
    assert loop._thread.is_alive() is False
    assert store.get_section( SECTION_NAME ) is not None


def test_stop_without_start_is_noop():
    loop = _loop( lambda **kw: [ ], Recorder() )
    loop.stop()                                                    # thread is None → no join


# ── quick_smoke_test ─────────────────────────────────────────────────────────

def test_quick_smoke_test_prints_live_section( capsys, monkeypatch ):
    import cosa.agents.heartbeat_arbiter.context_pressure as leaf
    monkeypatch.setattr( leaf, "assess_fleet_context_pressure",
                         lambda: [ _worker( pressure=_pressure() ) ] )
    quick_smoke_test()
    out = capsys.readouterr().out
    assert "✓ section built" in out
    assert "Tiberius" in out


if __name__ == "__main__":
    import sys
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
