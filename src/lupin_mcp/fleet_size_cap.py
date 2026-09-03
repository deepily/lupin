#!/usr/bin/env python3
"""
THE FLEET SIZE CAP — one number for the whole fleet, enforced at spawn.

RICK'S REQUEST, by voice 2026-09-03 (row `0ab1a095`). He had set a cap of four by
voice, counted six workers running, and had to read two managers the riot act to get it
back in line. A verbal cap is not a cap: it depends on every manager remembering it AND
doing the arithmetic. Neither happened — and the sentence itself ("four workers between
the two of you") was read three different ways by three sessions, which is why the number
has to live in one place and the control has to say what it counts.

=== HIS THREE RULINGS, answered by keypress. NOT re-derived here. ===

1. SCOPE — ONE NUMBER FOR THE WHOLE FLEET. The cap says 8, the fleet may run 8,
   whoever spawns them. Not per-manager. (The per-manager `spawn_cap` still exists and
   is a DIFFERENT limit: how many one call may launch at once.)

2. OVER CAP — REFUSE NEW SPAWNS, REAP NOBODY. Lowering the cap below the current count
   does not kill anything; the cap bites on the next spawn and the fleet drains
   naturally. ⇒ NOTHING IN THIS MODULE TERMINATES A SESSION, and that is a ruling, not
   an omission. A control that destroys work when dragged is not to be built.

3. WHO COUNTS — EVERY SESSION, MANAGERS INCLUDED. Not workers-only.

🔴 THE CONSEQUENCE OF RULING 3 THAT THE REFUSAL MUST CARRY. Because managers occupy the
cap, a cap at or below the number of live managers leaves ZERO room for workers — and a
manager spawning its own crew is refused by a cap it is itself consuming. That failure is
indistinguishable from a broken spawner unless the refusal says so, so
`refusal_for_spawn` reports the manager/worker split and names the zero-headroom case
outright. We spent 2026-09-03 measuring what a mislabelled failure costs; this one is
labelled at the source.

⚠️ THE CEILING IS DERIVED, NOT TYPED. Rick said "18 is the current ceiling" and, in the
same breath, that the maximum must track the real ceiling rather than hardcoding 18 in a
second place. Measured on this tree: there is no 18 anywhere in the INI, and
`cc session voice persona pool` holds FOURTEEN names. A session needs a persona, so the
pool is the binding constraint and `resolve_fleet_ceiling` counts it. If the pool grows,
the ceiling grows with it and nobody edits a second number — which is the ruling, whatever
the count happens to be today.
"""
from typing import Any, Callable, Dict, Iterable, Optional

# The fleet-wide default. Deliberately the same figure as the per-manager spawn cap so
# a fleet with one manager behaves as it did before this module existed.
DEFAULT_FLEET_CAP = 8

# Fallback only — used when the persona pool cannot be read at all. Not a second source
# of truth: `resolve_fleet_ceiling` prefers the live pool every time.
FALLBACK_FLEET_CEILING = 14

FLEET_CAP_KEY      = "cc session fleet size cap"
PERSONA_POOL_KEY   = "cc session voice persona pool"


def resolve_fleet_ceiling( config_mgr: Any ) -> int:
    """
    The largest cap that could ever be satisfied — the size of the persona pool.

    Requires:
        - config_mgr exposes .get(key, default=, return_type=, silent=) or is None

    Ensures:
        - returns the number of names in the persona pool when it can be read
        - returns FALLBACK_FLEET_CEILING when config is absent or the pool is empty
        - never raises

    ⚠️ THIS IS THE ONLY PLACE THE CEILING IS COMPUTED. A slider that hardcodes its own
    maximum is the second source of truth Rick's ruling forbids.
    """
    if config_mgr is None:
        return FALLBACK_FLEET_CEILING
    try:
        raw = config_mgr.get( PERSONA_POOL_KEY, default="", return_type="string", silent=True )
    except Exception:
        return FALLBACK_FLEET_CEILING
    names = [ n.strip() for n in ( raw or "" ).split( "," ) if n.strip() ]
    return len( names ) or FALLBACK_FLEET_CEILING


def resolve_fleet_cap( config_mgr: Any ) -> int:
    """
    The configured fleet cap, clamped into 1..ceiling.

    Ensures:
        - returns DEFAULT_FLEET_CAP when config is absent or the key is unset
        - a value below 1 clamps to 1; a value above the ceiling clamps to the ceiling
        - never raises

    ⚠️ CLAMPED RATHER THAN REJECTED because this is read on the SPAWN path. A malformed
    INI value must not take spawning down for the whole fleet — it must land somewhere
    sane and let the operator see the number on the control.
    """
    ceiling = resolve_fleet_ceiling( config_mgr )
    if config_mgr is None:
        return min( DEFAULT_FLEET_CAP, ceiling )
    try:
        value = config_mgr.get( FLEET_CAP_KEY, default=DEFAULT_FLEET_CAP,
                                return_type="int", silent=True )
    except Exception:
        value = DEFAULT_FLEET_CAP
    if value is None:
        value = DEFAULT_FLEET_CAP
    return max( 1, min( int( value ), ceiling ) )


def census( sessions: Iterable, is_manager_fn: Callable[ [ str ], bool ] ) -> Dict[ str, int ]:
    """
    Split the live fleet into managers and workers.

    Requires:
        - sessions is an iterable of (bridge_path, session_id, persona) triples —
          the shape `find_active_voice_persona_sessions()` returns
        - is_manager_fn( session_id ) -> bool; the canonical `is_manager_figure`

    Ensures:
        - returns { total, managers, workers } with managers + workers == total
        - a session whose classification RAISES counts as a worker, never dropped —
          an unclassifiable session still occupies a seat, and losing it from the total
          would let the fleet exceed its own cap through a classifier bug

    ⚠️ THE CLASSIFIER IS INJECTED so this is testable without a live bridge, and so the
    ONE canonical `is_manager_figure` is used rather than a second heuristic. Two
    definitions of "manager" is how a breakdown starts disagreeing with the board.
    """
    total = managers = 0
    for entry in sessions:
        total += 1
        session_id = entry[ 1 ] if isinstance( entry, ( tuple, list ) ) and len( entry ) > 1 else entry
        try:
            if is_manager_fn( session_id ):
                managers += 1
        except Exception:
            pass                      # counted in total, classified as a worker
    return { "total": total, "managers": managers, "workers": total - managers }


def refusal_for_spawn( requested: int, counts: Dict[ str, int ], cap: int ) -> Optional[ str ]:
    """
    The refusal message, or None when the spawn fits.

    Requires:
        - requested >= 1
        - counts is a census() result
        - cap >= 1

    Ensures:
        - returns None iff counts["total"] + requested <= cap
        - otherwise returns a message naming the CAP, the CURRENT TOTAL, the
          MANAGER/WORKER SPLIT, how many were requested and how many would fit
        - names the zero-headroom case explicitly when managers alone meet the cap
        - never raises, never reaps

    🔴 EVERY NUMBER A CALLER NEEDS IS IN THE STRING. Rick: "it would simply fail and tell
    you why, that you are already at limit." A spawn that fails without naming the cap
    sends a manager hunting a bug that does not exist.
    """
    total, managers, workers = counts[ "total" ], counts[ "managers" ], counts[ "workers" ]
    if total + requested <= cap:
        return None

    headroom = max( 0, cap - total )
    lines = [
        f"FLEET CAP REFUSED THIS SPAWN — the cap is {cap} and the fleet is already "
        f"running {total} ({managers} manager(s), {workers} worker(s)). "
        f"Requested {requested}; {headroom} seat(s) free."
    ]
    if managers >= cap:
        lines.append(
            f"⚠️ THE {managers} LIVE MANAGER(S) ALONE MEET OR EXCEED THE CAP OF {cap}, so "
            f"there is no room for a worker at any time — a manager is being refused by a "
            f"cap it is itself consuming. Raise the cap above {managers} or reap a manager; "
            f"lowering the cap will never free a seat, because it reaps nobody by design."
        )
    lines.append(
        "Nothing was terminated: the cap refuses NEW spawns and leaves running seats "
        "alone (Rick's ruling), so the fleet drains as sessions finish."
    )
    return " ".join( lines )
