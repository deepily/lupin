#!/usr/bin/env python3
"""
THE CAP COUNTS LIVE SEATS. IT USED TO COUNT ONLY THE ONES WITH A READABLE NAME.

🔴 ROW 9c3b817a. `default_fleet_gate` counted the fleet with
`find_active_voice_persona_sessions()` — which is `find_active_sessions(
require_persona=True )`, the POOL-OCCUPANCY projection. That filter is correct where it
was designed: `/allocate` excludes persona names already taken, and a seat with no
readable persona holds no name. It is wrong for a CAP, which asks a different question —
how many sessions EXIST.

MEASURED 2026-09-04 22:35, five live seats planted, all pids genuinely alive:

    find_active_voice_persona_sessions()           ->  1 of 5
    find_active_sessions( require_persona=False )  ->  4 of 5
    _scan_persona_by_tmux_session()                ->  index 4, unattributable 1

⇒ THE CAP SAW ONE SEAT IN FIVE. It dropped every bridge without a parseable
`voice_persona` DICT, and corrupt JSON is only one of four shapes that qualify:
garbage JSON · no persona key · `voice_persona: null` · persona present but not a dict.

🔴 AND THE COMMON SHAPE IS NOT CORRUPTION, IT IS A SEAT MID-BOOT. A session writes its
bridge before it allocates a persona, so `voice_persona: null` is the NORMAL state of
every seat on its way up. The cap under-counted a BOOTING fleet routinely — not a
corrupted one rarely — and permitted spawns it should have refused. Rick's own ruling is
that every session counts, and a persona-less seat is a session burning tokens.

=== WHAT DID *NOT* CHANGE, AND IT IS HALF THE FIX ===

⚠️ THE LIVENESS FILTER STAYS (María's ruling, 22:36). Only the persona-parseability
filter is dropped. A dead seat must still not count, or the cap would bind on ghosts and
a manager would hunt seats to reap that do not exist. The negative arms below pin that,
and without them "count more seats" is satisfied by counting everything.

⚠️ ALLOCATION IS UNTOUCHED BY CONSTRUCTION, NOT BY CARE. The shared scan's DEFAULT is
unchanged; what moved is which call the GATE makes. `/allocate` and `/pool` still get
`require_persona=True`, because "which names are taken" genuinely needs a readable name.
Two questions, two filters — this row's DONE MEANS #5, answered NO.
"""
import json
import os
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import session_bridge
from lupin_mcp import fleet_size_cap, session_spawner


@pytest.fixture
def live_pids():
    """Five genuinely-running processes — the liveness filter reads the pid out of the
    bridge FILENAME, so a planted bridge needs a real one."""
    procs = [ subprocess.Popen( [ "sleep", "120" ] ) for _ in range( 5 ) ]
    try:
        yield [ p.pid for p in procs ]
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait( timeout=5 )
            except subprocess.TimeoutExpired:      # pragma: no cover - defensive reap
                p.kill()


# The four shapes the old census dropped, plus the one it kept. Named so a failure says
# WHICH shape regressed rather than only that a count moved.
SHAPES = {
    "good"           : lambda: json.dumps( { "session_id": "s-good", "role": "author",
                                             "spawned_by": "21dff055",
                                             "voice_persona": { "name": "Good" } } ),
    "persona-null"   : lambda: json.dumps( { "session_id": "s-null", "role": "author",
                                             "spawned_by": "21dff055",
                                             "voice_persona": None } ),
    "no-persona-key" : lambda: json.dumps( { "session_id": "s-nokey", "role": "author",
                                             "spawned_by": "21dff055" } ),
    "persona-malform": lambda: json.dumps( { "session_id": "s-malf", "role": "author",
                                             "spawned_by": "21dff055",
                                             "voice_persona": "not-a-dict" } ),
    "garbage-json"   : lambda: "}{ not json at all",
}


def _plant_all( pids ):
    directory = session_bridge.SESSION_DIR
    directory.mkdir( parents=True, exist_ok=True )
    for pid, make in zip( pids, SHAPES.values() ):
        ( directory / f"cc-{pid}.json" ).write_text( make() )
    return directory


def _plant_one( pid, body ):
    directory = session_bridge.SESSION_DIR
    directory.mkdir( parents=True, exist_ok=True )
    ( directory / f"cc-{pid}.json" ).write_text( body )


def _config( cap ):
    class _Config:
        def get( self, key, default=None, return_type="string", silent=False ):
            return { "cc session fleet size cap"         : cap,
                     "cc session fleet size cap maximum" : 18 }.get( key, default )
    return lambda: _Config()


# ───────────────── the scan surfaces what it could not read ─────────────────

def test_the_scan_REPORTS_the_live_bridges_it_could_not_read( live_pids ):
    """
    🔴 THE SEAM, AND IT FOLLOWS AN IDIOM THE SCANNER ALREADY HAD. `find_active_sessions`
    carries `stale_out` for exactly this purpose — handing the caller what it dropped,
    rather than making the caller re-walk the directory. `unreadable_out` is the same
    shape, so counting the unreadable costs no THIRD enumeration.

    A third glob over the same population is how two counts start disagreeing, which is
    the defect this whole epic keeps producing.
    """
    _plant_all( live_pids )

    unreadable = [ ]
    seen = session_bridge.find_active_sessions( require_persona=False,
                                                unreadable_out=unreadable )
    assert len( seen ) == 4, (
        f"POSITIVE CONTROL: four of the five shapes are readable — saw {len( seen )}"
    )
    assert len( unreadable ) == 1, (
        f"the garbage-JSON bridge must be REPORTED, not silently dropped — saw {unreadable}"
    )
    assert len( seen ) + len( unreadable ) == 5, "every live seat is accounted for, once"


def test_the_scan_reports_NOTHING_unreadable_when_every_bridge_parses( live_pids ):
    """
    The discriminating negative. Without it the arm above is satisfied by a scan that
    reports every bridge as unreadable.
    """
    _plant_one( live_pids[ 0 ], SHAPES[ "good" ]() )

    unreadable = [ ]
    seen = session_bridge.find_active_sessions( require_persona=False,
                                                unreadable_out=unreadable )
    assert len( seen ) == 1, f"POSITIVE CONTROL: one readable bridge — saw {len( seen )}"
    assert unreadable == [ ], f"a healthy tree must report nothing unreadable — saw {unreadable}"


# ───────────────────── the census counts them ─────────────────────

def test_the_census_ADDS_the_unreadable_to_total_and_to_unknown():
    """
    María's ruling, 22:36: unattributable seats are COUNTED, not merely reported. They
    occupy the cap. They land in `unknown` because that is what is true about them — the
    seat exists and we cannot say what it is.
    """
    counts = fleet_size_cap.census( [ ( "p", "s0", { } ) ],
                                    lambda sid: fleet_size_cap.SEAT_WORKER,
                                    unreadable=2 )
    assert counts == { "total": 3, "managers": 0, "workers": 1, "unknown": 2 }
    assert ( counts[ "managers" ] + counts[ "workers" ] + counts[ "unknown" ]
             == counts[ "total" ] ), "the three-way reconcile must survive the addition"


def test_the_census_default_is_unchanged_for_every_existing_caller():
    """`unreadable` defaults to 0, so nothing that does not pass it moves."""
    assert fleet_size_cap.census( [ ( "p", "s0", { } ) ],
                                  lambda sid: fleet_size_cap.SEAT_WORKER ) == {
        "total": 1, "managers": 0, "workers": 1, "unknown": 0 }


# ─────────────── the whole thing, through the real gate ───────────────

def test_the_GATE_counts_all_five_live_seats( live_pids ):
    """
    🔴 THE ARM THIS FILE EXISTS FOR, driven through the shipped `default_fleet_gate`.
    Five live seats against a cap of five: the next spawn must be REFUSED, and the
    refusal must name five.

    Before this change the gate saw ONE seat and allowed the spawn — four seats of
    headroom that did not exist.
    """
    _plant_all( live_pids )

    refusal = session_spawner.default_fleet_gate( 1, config_fn=_config( 5 ) )
    assert refusal is not None, (
        "five live seats against a cap of five must refuse. A None here means the gate "
        "is still counting only the seats with a readable persona."
    )
    assert "already running 5" in refusal, refusal
    assert "1 unclassified" in refusal, (
        f"the garbage-JSON seat is counted AND declared unreadable — saw: {refusal}"
    )


def test_the_GATE_still_ALLOWS_one_below_the_cap( live_pids ):
    """
    The discriminating negative for the arm above. Same five seats, cap of six: ALLOW.
    A gate that refuses everything satisfies the test above and protects nothing.
    """
    _plant_all( live_pids )
    assert session_spawner.default_fleet_gate( 1, config_fn=_config( 6 ) ) is None, (
        "five live seats under a cap of six must not be refused"
    )


def test_a_DEAD_seat_is_still_not_counted():
    """
    🔴 THE LIVENESS FILTER STAYS — María's ruling, and the half that stops this fix from
    becoming its own defect. A bridge whose pid is dead must not occupy the cap:
    counting ghosts would refuse spawns forever and send a manager reaping seats that do
    not exist.

    A pid that is started and reaped is genuinely dead, which is stronger than picking a
    number and hoping nothing owns it.
    """
    dead = subprocess.Popen( [ "sleep", "0.01" ] )
    dead.wait()
    _plant_one( dead.pid, SHAPES[ "good" ]() )

    unreadable = [ ]
    seen = session_bridge.find_active_sessions( require_persona=False,
                                                unreadable_out=unreadable )
    assert seen == [ ] and unreadable == [ ], (
        f"a dead seat must be filtered before either bucket — saw {seen}, {unreadable}"
    )
    assert session_spawner.default_fleet_gate( 1, config_fn=_config( 1 ) ) is None, (
        "a fleet of nothing-but-a-dead-bridge must not refuse a spawn"
    )


def test_a_DEAD_and_UNREADABLE_bridge_is_not_counted_either():
    """
    The corner where the two filters meet, and the one an implementation is most likely
    to get wrong: liveness must be decided BEFORE readability, or a dead corrupt bridge
    lands in `unreadable` and occupies the cap forever — nothing will ever reap it,
    because there is no process to reap.
    """
    dead = subprocess.Popen( [ "sleep", "0.01" ] )
    dead.wait()
    _plant_one( dead.pid, SHAPES[ "garbage-json" ]() )

    unreadable = [ ]
    session_bridge.find_active_sessions( require_persona=False, unreadable_out=unreadable )
    assert unreadable == [ ], (
        f"a DEAD unreadable bridge must be dropped by liveness first — saw {unreadable}"
    )


# ─────────────── allocation is untouched — DONE MEANS #5 ───────────────

def test_ALLOCATION_still_sees_only_the_seats_with_a_readable_persona( live_pids ):
    """
    🔴 DONE MEANS #5, ANSWERED NO, AND PINNED. `/allocate` and `/pool` ask which persona
    NAMES are taken; that genuinely requires a readable persona, and widening it would
    make the pool think a nameless seat holds a name.

    So the shared scan's DEFAULT must not move. If a later change "simplifies" this by
    flipping `require_persona` at the source, this arm goes red and names why.
    """
    _plant_all( live_pids )
    assert len( session_bridge.find_active_voice_persona_sessions() ) == 1, (
        "the persona projection must still see exactly the one seat with a readable "
        "persona — the cap's widening must not reach allocation"
    )


def quick_smoke_test():
    """Non-destructive: the census arithmetic only — no bridges, no processes."""
    counts = fleet_size_cap.census( [ ( "p", "s0", { } ) ],
                                    lambda sid: fleet_size_cap.SEAT_WORKER, unreadable=2 )
    assert counts == { "total": 3, "managers": 0, "workers": 1, "unknown": 2 }
    print( "✓ unreadable seats occupy the cap" )


if __name__ == "__main__":
    quick_smoke_test()
