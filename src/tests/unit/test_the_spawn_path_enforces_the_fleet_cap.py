#!/usr/bin/env python3
"""
THE FLEET CAP, ENTERED AT THE LAYER A SPAWN ENTERS AT.

`test_fleet_size_cap.py` proves the PREDICATES — the cap, the ceiling, the census,
the refusal wording. Every one of them passed while `resolve_fleet_cap` had ZERO
production callers: it shipped at `93f167e4` and nothing in the tree called it, so
the dial turned and governed nothing. That is why the slider was held.

🔴 SO THESE TESTS ARE ABOUT THE CALL SITE, NOT THE MATH. Revert the guard in
`spawn_sessions` and every test in `test_fleet_size_cap.py` still passes.

⚠️ AND THEY DRIVE THE REAL GATE, NOT A STAND-IN FOR IT. Tonight a gate shipped whose
only live path could not run, because all 25 of its tests injected past the seam and
the default never executed once (instance 5 in
`src/rnd/2026.09.04-declared-but-never-arriving-six-instances.md`). The lesson from
Maya's guard is the shape used here: patch ONE LEVEL LOWER than the seam. So
`default_fleet_gate` runs for real, and what is supplied is its `config_fn` and
`census_fn` — the two things it reads the world through.
"""
import os
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_mcp import fleet_size_cap as fsc
from lupin_mcp import session_spawner as ss


class _Config:
    """Minimal ConfigurationManager stand-in — the same shape fleet_size_cap reads."""

    def __init__( self, values ):
        self._values = values

    def get( self, key, default=None, return_type=None, silent=False ):
        return self._values.get( key, default )


def _sessions( n ):
    """The (bridge_path, session_id, persona) triples find_active_voice_persona_sessions returns."""
    return [ ( f"/tmp/b{i}.json", f"s{i}", f"p{i}" ) for i in range( n ) ]


# ── THE GUARD EXISTS AT THE CALL SITE ────────────────────────────────────────────

def test_spawn_sessions_ASKS_the_fleet_gate_at_all():
    """
    🔴 THE ARM THE PREDICATE TESTS CANNOT CARRY. Delete the guard from
    `spawn_sessions` and this stays empty while `test_fleet_size_cap.py` stays green.
    """
    asked = [ ]

    with pytest.raises( ValueError ):
        ss.spawn_sessions(
            count              = 3,
            task_prompt        = "x",
            manager_session_id = "mgr",
            script_path        = "/nonexistent",
            fleet_gate_fn      = lambda n: ( asked.append( n ), "REFUSED: fleet is full" )[ 1 ],
        )

    assert asked == [ 3 ], "the spawn path never consulted the fleet gate"


def test_the_refusal_REACHES_the_caller_verbatim():
    """
    A gate that refuses and a caller that swallows the reason are the same thing to a
    manager staring at a failed spawn. Rick: "it would simply fail and tell you why."
    """
    with pytest.raises( ValueError ) as e:
        ss.spawn_sessions(
            count              = 2,
            task_prompt        = "x",
            manager_session_id = "mgr",
            script_path        = "/nonexistent",
            fleet_gate_fn      = lambda n: "fleet cap 8 reached: 8 live (2 managers, 6 workers)",
        )
    assert "fleet cap 8 reached" in str( e.value )
    assert "2 managers" in str( e.value )


def test_a_spawn_that_FITS_is_not_blocked_by_the_gate():
    """
    ⚠️ THE NEGATIVE CONTROL, AND THE FILE IS WORTHLESS WITHOUT IT. A guard wired to
    refuse unconditionally satisfies both tests above. This one says the gate is a
    gate rather than a wall — it gets past the cap check and fails later, on the
    missing script, which is a DIFFERENT error.
    """
    # ⚠️ ASSERTED AS IT ACTUALLY BEHAVES, NOT AS I FIRST ASSUMED. My first cut wrapped
    # this in `pytest.raises` expecting the missing script to blow up; it does not —
    # a fitting spawn gets past the gate and proceeds. The test now says the only
    # thing it can honestly say: whatever happens next, it is not a fleet refusal.
    try:
        ss.spawn_sessions(
            count              = 1,
            task_prompt        = "x",
            manager_session_id = "mgr",
            script_path        = "/nonexistent",
            dry_run            = True,
            fleet_gate_fn      = lambda n: None,
        )
    except Exception as e:
        assert "fleet" not in str( e ).lower(), (
            f"a spawn that fits was refused by the fleet gate: {e}" )


# ── THE REAL GATE, DRIVEN THROUGH ITS OWN SEAMS ──────────────────────────────────

def test_the_REAL_gate_refuses_when_the_fleet_is_full():
    """
    Not a stand-in — `default_fleet_gate` itself, reading a supplied config and census.
    """
    refusal = ss.default_fleet_gate(
        1,
        config_fn = lambda: _Config( { fsc.FLEET_CAP_KEY: 3, fsc.FLEET_CEILING_KEY: 18 } ),
        census_fn = lambda: _sessions( 3 ),
    )
    assert refusal is not None, "3 live against a cap of 3 was allowed a fourth"
    assert "3" in refusal


def test_the_REAL_gate_ALLOWS_when_there_is_room():
    """The other half — without it, a gate that refused everything would pass above."""
    assert ss.default_fleet_gate(
        1,
        config_fn = lambda: _Config( { fsc.FLEET_CAP_KEY: 8, fsc.FLEET_CEILING_KEY: 18 } ),
        census_fn = lambda: _sessions( 3 ),
    ) is None


def test_the_cap_counts_EVERY_session_not_only_workers():
    """
    Rick's ruling 3, checked where it bites. The census is handed sessions with no
    manager/worker distinction available, and the cap must still count all of them —
    a cap that counted workers only would allow a fourth here.
    """
    assert ss.default_fleet_gate(
        1,
        config_fn = lambda: _Config( { fsc.FLEET_CAP_KEY: 4, fsc.FLEET_CEILING_KEY: 18 } ),
        census_fn = lambda: _sessions( 4 ),
    ) is not None


def test_an_UNREADABLE_fleet_ALLOWS_the_spawn_rather_than_taking_the_fleet_down():
    """
    🔨 FAIL-OPEN, AND IT CONTRADICTS THE OTHER GATE BUILT TODAY ON PURPOSE.

    The promotion gate fails CLOSED because it guards an AUTHORISATION — not knowing
    who is asking is a reason to refuse. This guards a RESOURCE LIMIT, and the failure
    modes are not symmetric: a census that raises and refuses would take the whole
    fleet's spawning down over a bridge-read error, while allowing lets the cap be
    briefly exceeded and the next spawn re-checks. Rick's own ruling agrees — over cap
    reaps nobody, so the cap is a soft brake rather than an interlock.

    ⚠️ Stated in a test rather than only in a comment, so the choice is pinned and a
    later reader "fixing the inconsistency" gets a red instead of a surprise.
    """
    def _explodes():
        raise RuntimeError( "bridge directory unreadable" )

    assert ss.default_fleet_gate(
        1,
        config_fn = lambda: _Config( { fsc.FLEET_CAP_KEY: 1, fsc.FLEET_CEILING_KEY: 18 } ),
        census_fn = _explodes,
    ) is None, "an unreadable census refused a spawn — that takes the fleet down on a read error"
