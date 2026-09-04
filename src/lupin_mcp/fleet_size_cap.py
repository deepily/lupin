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

🔨 THE CEILING IS CONFIGURED, NOT DERIVED — SUPERSEDED 2026-09-03. The paragraph this
replaces is SUMMARISED rather than deleted, because it was right about a real hazard and
a reader who meets only the new rule will not know why the old one existed.

WHAT IT SAID: the ceiling is `len( persona pool )`, because a session needs a persona, so
the pool is the binding constraint — and hardcoding 18 in a second place is what Rick's
earlier ruling forbade.

WHAT HE RULED LATER THE SAME DAY, by voice: the maximum must be CONFIGURABLE in the
configuration manager so he can tweak it over time. That is `cc session fleet size cap
maximum`, shipping as 18. ⇒ Not a second hardcode — the config layer, which is where he
asked for it.

⚠️ THE OLD PARAGRAPH'S HAZARD IS REAL AND HAS NOT GONE AWAY. It has only stopped being
enforced silently. The pool is still the number of seats that can be FILLED; the key is
only the width of the dial. Raise the key above the pool and the spawns above it are
refused for want of a PERSONA, not for want of cap.

🔴 SO IT IS DELIBERATELY NOT CLAMPED TO THE POOL. A dial silently trimmed to 14 when the
operator typed 18 cannot be told apart from a key that was ignored, and this fleet spent
2026-09-03 measuring what a mislabelled failure costs.

⚠️ AND THERE IS NOTHING TO CLAMP TO. A `pool_shortfall()` reporter was written for a gap
that cannot exist and then removed on measurement: allocation falls through the named
pool to the overflow persona and then to UNBOUNDED `Extra-N` seats. 18 requested fills
18; 200 fills 200. The persona pool is not a ceiling on anything.

⚠️ AND THE POOL'S OWN COUNT IS NOT ITS SEAT COUNT: a pool entry with no `voice id` is
silently skipped by the loader, so `pool_size()` counts voice ids rather than names.
"""
from typing import Any, Callable, Dict, Iterable, Optional

# The fleet-wide default. Deliberately the same figure as the per-manager spawn cap so
# a fleet with one manager behaves as it did before this module existed.
DEFAULT_FLEET_CAP = 8

# The dial's ceiling when config cannot be read. Rick named 18 by voice on 2026-09-03 and
# the INI ships that value; this is the fallback for an unreadable config, not a second
# source of truth.
DEFAULT_FLEET_CEILING = 18

FLEET_CAP_KEY      = "cc session fleet size cap"
FLEET_CEILING_KEY  = "cc session fleet size cap maximum"
PERSONA_POOL_KEY   = "cc session voice persona pool"


def pool_size( config_mgr: Any ) -> int:
    """
    How many seats can actually be FILLED — the ALLOCATABLE persona count.

    Ensures:
        - counts only pool names carrying a non-empty `voice id`, because that is
          exactly what the pool loader does
        - returns 0 when config is absent or the pool is unreadable
        - never raises

🔴 A NAME IS NOT A SEAT. The pool loader silently SKIPS a pool entry whose
    `voice id` is missing or empty — right for allocation, a trap for counting.

    ⚠️ THE CONSEQUENCE IS SMALLER THAN IT FIRST LOOKED, NARROWED BY MEASUREMENT
    2026-09-03. The first cut of this module treated the pool as a CEILING on seats and
    shipped a `pool_shortfall()` warning that the dial was wider than the pool. That
    warning was for a gap that CANNOT EXIST: `pick_unallocated_persona` falls through
    the named pool to the overflow persona and then to UNBOUNDED `Extra-N` identities.
    Measured on the live config — 18 requested, 18 distinct seats filled (14 named,
    then `arnold`, then `extra 1/2/3`); 200 requested fills 200.

    ⇒ A VOICELESS POOL ENTRY COSTS A *NAME*, NOT A SEAT. The session still gets a
    persona; it gets `Extra-N` instead of the one somebody meant to add.

    ⚠️ AND THE FALL-THROUGH WAS DOCUMENTED ALL ALONG, in the `spawn_sessions` contract.
    Two of us read past it and went looking at an ElevenLabs key for voice ids nobody
    needed. The mechanism was in plain sight; we did not read it.
    """
    if config_mgr is None:
        return 0
    try:
        raw = config_mgr.get( PERSONA_POOL_KEY, default="", return_type="string", silent=True )
    except Exception:
        return 0
    names = [ n.strip() for n in ( raw or "" ).split( "," ) if n.strip() ]
    fillable = 0
    for name in names:
        try:
            vid = config_mgr.get( f"cc session voice persona {name} voice id",
                                  default="", return_type="string", silent=True )
        except Exception:
            vid = ""
        if ( vid or "" ).strip():
            fillable += 1
    return fillable


def resolve_fleet_ceiling( config_mgr: Any ) -> int:
    """
    The largest value the fleet-size dial may take — READ FROM CONFIGURATION.

    Ensures:
        - returns `cc session fleet size cap maximum` when it can be read
        - returns DEFAULT_FLEET_CEILING when config is absent or the key is unset
        - a value below 1 clamps to 1
        - is NOT clamped to the persona pool size, which is not a ceiling on seats
        - never raises

    🔨 CONFIGURED, PER RICK'S 2026-09-03 RULING BY VOICE: the maximum must be tweakable
    in the configuration manager over time. The module docstring carries the SUPERSEDED
    derive-from-the-pool rule and the hazard it was protecting against — read it before
    "fixing" this back.
    """
    if config_mgr is None:
        return DEFAULT_FLEET_CEILING
    try:
        value = config_mgr.get( FLEET_CEILING_KEY, default=DEFAULT_FLEET_CEILING,
                                return_type="int", silent=True )
    except Exception:
        value = DEFAULT_FLEET_CEILING
    if value is None:
        value = DEFAULT_FLEET_CEILING
    return max( 1, int( value ) )


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
