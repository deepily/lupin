#!/usr/bin/env python3
"""
Context-headroom writer, the standing context-pressure publisher on :8001.

Each tick this loop calls the pure leaf `assess_fleet_context_pressure`
(src/cosa/agents/heartbeat_arbiter/context_pressure.py). It applies the
budget-headroom transform and keys the result by persona. It then writes the
`context_pressure` section of the :8001-local store.
It only reads sensors: it emits nothing to commons and sends no notify.

Design: src/rnd/v0.1.8/2026.06.07-managing-context-memory/2026.06.09-context-pressure-published-headroom-service-design.md

The budget transform is below. The policy maps 1M to 0.50, 200K to 0.75, and
anything else to the default. Headroom is sign-honest and never clamped.
The current headroom, not the forward one, drives status.

    budget_fraction           = policy[ window_size ]

    budget_ceiling_tokens     = round( window_size * budget_fraction )

    headroom_tokens_current   = budget_ceiling_tokens - occupancy_tokens

    headroom_tokens_forward   = budget_ceiling_tokens - next_prompt_estimate

    status                    = over_budget iff headroom_tokens_current < 0

Both occupancy figures are published side by side: `occupancy_tokens` (the
calibrated /context total, `last_prompt_size`) and `next_prompt_estimate`
(forward, conservative). Each has its own headroom, and the consumer chooses.
Workers whose liveness is "IDLE" or "DEAD" publish `occupancy_tokens: null`.
So do "ACTIVE" workers with no assistant turn yet. No false zero is written,
so the absence of a fresh measurement is explicit, and status is idle, dead or unknown.

The module imports only stdlib plus the sibling SystemClock seam. The leaf is
injected (`assess_fn`), so the transform and the loop are fully unit-testable
with a fake fleet. Liveness and state are compared as plain strings
("ACTIVE", "IDLE", "DEAD", "UNKNOWN"), never by imported type.
"""
import datetime
import json
import threading

from typing import Any, Callable, Dict, List, Optional

from lupin_arbiter_app.health_watcher import SystemClock
from cosa.agents.heartbeat_arbiter.arbiter_journal import make_log_fn


SECTION_NAME = "context_pressure"


# Item A (2026.06.11 receipts design §2.3): the line shape has ONE owner —
# arbiter_journal.make_log_fn (ts + ts_local).
_default_log_fn = make_log_fn( loop="context_pressure_writer" )


def _budget_fraction_for( window_size: int, budget_fractions: Dict[ Any, float ] ) -> float:
    """
    Resolve the soft-budget fraction for a window size (policy lookup).

    Requires:
        - budget_fractions maps int window sizes → fraction, plus key "default"

    Ensures:
        - returns budget_fractions[ window_size ] when that exact size is mapped
        - returns budget_fractions[ "default" ] for any unmapped size
    """
    fraction = budget_fractions.get( window_size )
    return fraction if fraction is not None else budget_fractions[ "default" ]


def _liveness_value( liveness: Any ) -> str:
    """Ensures: returns the liveness as its plain string value ("ACTIVE"/"IDLE"/"DEAD")."""
    return str( liveness.value ) if hasattr( liveness, "value" ) else str( liveness )


def _unmeasured_status( liveness_value: str ) -> str:
    """
    Map an unmeasured worker's liveness to its published status.

    Ensures:
        - "IDLE" → "idle"; "DEAD" → "dead"
        - anything else ("ACTIVE" with no assistant turn yet) → "unknown"
    """
    if liveness_value == "IDLE":
        return "idle"
    if liveness_value == "DEAD":
        return "dead"
    return "unknown"


def _persona_record( worker: Any, budget_fractions: Dict[ Any, float ] ) -> Dict[ str, Any ]:
    """
    Transform one WorkerContextPressure into its published persona record.

    The record carries the per-worker facts (tmux_session, pressure_state,
    pressure_pct, pending_input_estimate, recommendation) plus the
    budget-headroom fields. The caller keys it by persona.

    Requires:
        - worker duck-types WorkerContextPressure: session_id, tmux_session,
          liveness (str-comparable), pressure (ContextPressure duck or None),
          last_turn_age, recommendation
        - budget_fractions carries a "default" key

    Ensures:
        - "ACTIVE" + measured (pressure.state != "UNKNOWN") → full budget record:
          both occupancies, both headrooms (sign-honest, never clamped), and
          status over_budget/within_budget driven by headroom_tokens_current
        - unmeasured (pressure None, or state "UNKNOWN" = no assistant turn yet)
          → measurement fields null (no false zero), status idle/dead/unknown
        - window_size + budget_fraction + budget_ceiling_tokens are published
          whenever the leaf read the window (pressure present), null otherwise
          ("IDLE" and "DEAD" skip the transcript read, so the window was never resolved)
    """
    pressure       = worker.pressure
    liveness_value = _liveness_value( worker.liveness )
    record : Dict[ str, Any ] = {
        "session_id"      : worker.session_id,
        "tmux_session"    : worker.tmux_session,
        "liveness"        : liveness_value,
        "last_turn_age_s" : round( worker.last_turn_age, 1 ) if worker.last_turn_age is not None else None,
        "recommendation"  : worker.recommendation,
    }

    if pressure is not None and pressure.state != "UNKNOWN":
        window_size = pressure.window_size
        fraction    = _budget_fraction_for( window_size, budget_fractions )
        ceiling     = round( window_size * fraction )
        occupancy   = pressure.last_prompt_size
        forward     = pressure.next_prompt_estimate
        record.update( {
            "window_size"               : window_size,
            "budget_fraction"           : fraction,
            "budget_ceiling_tokens"     : ceiling,
            "occupancy_tokens"          : occupancy,
            "next_prompt_estimate"      : forward,
            "consumption_pct_of_window" : round( 100.0 * occupancy / window_size, 1 ),
            "headroom_tokens_current"   : ceiling - occupancy,
            "headroom_tokens_forward"   : ceiling - forward,
            "headroom_pct_points"       : round( fraction * 100.0 - 100.0 * occupancy / window_size, 1 ),
            "status"                    : "over_budget" if ( ceiling - occupancy ) < 0 else "within_budget",
            "pressure_state"            : str( pressure.state.value if hasattr( pressure.state, "value" ) else pressure.state ),
            "pressure_pct"              : round( pressure.pct, 1 ),
            "pending_input_estimate"    : pressure.pending_input_estimate,
        } )
    else:
        window_size = pressure.window_size if pressure is not None else None
        fraction    = _budget_fraction_for( window_size, budget_fractions ) if window_size is not None else None
        record.update( {
            "window_size"               : window_size,
            "budget_fraction"           : fraction,
            "budget_ceiling_tokens"     : round( window_size * fraction ) if window_size is not None else None,
            "occupancy_tokens"          : None,
            "next_prompt_estimate"      : None,
            "consumption_pct_of_window" : None,
            "headroom_tokens_current"   : None,
            "headroom_tokens_forward"   : None,
            "headroom_pct_points"       : None,
            "status"                    : _unmeasured_status( liveness_value ),
            "pressure_state"            : "UNKNOWN" if pressure is not None else None,
            "pressure_pct"              : None,
            "pending_input_estimate"    : pressure.pending_input_estimate if pressure is not None else None,
        } )
    return record


def build_context_pressure_section(
    workers          : List[ Any ],
    *,
    budget_fractions : Dict[ Any, float ],
    generated_at     : str,
) -> Dict[ str, Any ]:
    """
    Build the published `context_pressure` section (personas, policy echo, summary).

    Personas key the map with no collision guard. The voice-persona naming
    system never mints colliding names, so uniqueness is an upstream
    invariant and is not re-checked here.

    Requires:
        - workers is a list of WorkerContextPressure ducks (may be empty)
        - budget_fractions maps int window sizes → fraction and carries "default"
        - generated_at is an ISO-8601 UTC string

    Ensures:
        - returns { generated_at, policy, personas, unnamed_seats, summary }
        - policy echoes budget_fractions with str keys (JSON-stable)
        - a named worker (truthy persona) keys the persona map, preserving the
          uniqueness invariant (voice-persona names never collide)
        - a nameless live worker (persona None or "") does not key the map. It is
          appended to `unnamed_seats` as an explicit row carrying persona=null
          and its age. Keying it would collapse every nameless seat under one
          null key, so silence (no over-budget) and absence (nameless,
          unmeasured) would look identical. Nobody watches a nameless seat,
          so it must be visible as a row, not missing from the list.
        - summary counts: personas (named total), unnamed_live_seats,
          within_budget, over_budget, idle_or_unknown. The status buckets span
          both named and nameless seats, so a nameless over-budget seat still alarms
        - raises KeyError when budget_fractions lacks "default" and an unmapped
          window appears (fail loudly; the config wiring always provides it)
    """
    personas : Dict[ str, Any ]  = { }
    unnamed  : List[ Any ]       = [ ]
    within = over = idle_or_unknown = 0

    for worker in workers:
        record = _persona_record( worker, budget_fractions )
        if worker.persona:                             # named → persona-keyed map (uniqueness invariant)
            personas[ worker.persona ] = record
        else:                                          # nameless live seat → explicit, never dropped
            record[ "persona" ] = None                 # state it plainly: this seat has no persona
            unnamed.append( record )
        if record[ "status" ] == "within_budget":
            within += 1
        elif record[ "status" ] == "over_budget":
            over += 1
        else:
            idle_or_unknown += 1

    return {
        "generated_at"  : generated_at,
        "policy"        : { str( k ): v for k, v in budget_fractions.items() },
        "personas"      : personas,
        "unnamed_seats" : unnamed,
        "summary"       : {
            "personas"           : len( personas ),
            "unnamed_live_seats" : len( unnamed ),
            "within_budget"      : within,
            "over_budget"        : over,
            "idle_or_unknown"    : idle_or_unknown,
        },
    }


class ContextPressureWriterLoop:
    """
    The standing context-headroom writer, shaped like the health and fleet loops.

    Each tick runs the leaf, applies the budget transform, builds the
    persona-keyed section and calls store.set_section( "context_pressure", ... ).
    It runs on a background thread and is degrade-safe per tick.
    It only writes the store, nothing else.
    """

    def __init__(
        self,
        assess_fn        : Callable[ ..., List[ Any ] ],
        store            : Any,
        *,
        budget_fractions : Dict[ Any, float ],
        leaf_kwargs      : Optional[ Dict[ str, Any ] ] = None,
        clock            : Optional[ Any ]              = None,
        log_fn           : Optional[ Callable ]         = None,
        interval_seconds : int                          = 60,
    ) -> None:
        """
        Store the injected seams and validate the loop's configuration.

        Requires:
            - assess_fn is the fleet leaf (or a fake): assess_fn( **leaf_kwargs )
              → list[ WorkerContextPressure ]
            - store exposes set_section( name, value )
            - budget_fractions carries a "default" key
            - interval_seconds is positive

        Ensures:
            - injected seams resolved (clock → SystemClock, log_fn → structured JSON)
            - raises ValueError on any invariant violation
        """
        if "default" not in budget_fractions:
            raise ValueError( "budget_fractions must carry a 'default' key" )
        if interval_seconds <= 0:
            raise ValueError( f"interval_seconds must be positive, got {interval_seconds}" )

        self._assess_fn        = assess_fn
        self._store            = store
        self._budget_fractions = dict( budget_fractions )
        self._leaf_kwargs      = dict( leaf_kwargs or { } )
        self._clock            = clock if clock is not None else SystemClock()
        self._log_fn           = log_fn if log_fn is not None else _default_log_fn
        self._interval_seconds = interval_seconds
        self._stop             = threading.Event()
        self._thread           = None

    def poll_once( self ) -> bool:
        """
        Run one tick: assess the fleet, transform, write the section.

        Returns True only when the section was written this tick.

        Ensures:
            - an assess failure is swallowed + logged (`assess_error`); the
              previously-written section is left untouched (stale beats absent)
            - on success writes SECTION_NAME and logs `context_pressure_written`
            - never raises
        """
        try:
            workers = self._assess_fn( **self._leaf_kwargs )
        except Exception as e:                               # per-tick guard — the leaf must never kill the loop
            self._log_fn( "assess_error", error=str( e ) )
            return False

        section = build_context_pressure_section(
            workers,
            budget_fractions = self._budget_fractions,
            generated_at     = self._clock.now().isoformat(),
        )
        self._store.set_section( SECTION_NAME, section )
        self._log_fn( "context_pressure_written", summary=section[ "summary" ] )
        return True

    def run( self ) -> None:
        """
        Tick until stop(): poll_once, then sleep, with a per-tick guard.

        One bad tick never exits the loop (the observer invariant).
        """
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:                           # per-tick guard
                self._log_fn( "poll_error", error=str( e ) )
            self._clock.sleep( self._interval_seconds )

    def start( self ) -> None:
        """Spawn the daemon tick thread."""
        self._thread = threading.Thread( target=self.run, name="context-pressure-writer", daemon=True )
        self._thread.start()

    def stop( self ) -> None:
        """Signal stop and join the tick thread (no-op if never started)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join( timeout=5 )


def quick_smoke_test():
    """
    Build and print the live section from the real leaf (read-only, :7999-safe).
    """
    from cosa.agents.heartbeat_arbiter.context_pressure import assess_fleet_context_pressure

    print( "Building live context_pressure section (read-only)...\n" )
    section = build_context_pressure_section(
        assess_fleet_context_pressure(),
        budget_fractions = { 1_000_000: 0.50, 200_000: 0.75, "default": 0.50 },
        generated_at     = datetime.datetime.now( datetime.timezone.utc ).isoformat(),
    )
    print( json.dumps( section, indent=2, default=str ) )
    print( f"\n✓ section built: {section[ 'summary' ]}" )


if __name__ == "__main__":   # pragma: no cover - CLI entry point, exercised via quick_smoke_test() in tests
    quick_smoke_test()
