#!/usr/bin/env python3
"""
THE FLEET CENSUS COUNTS WHAT A SEAT DECLARES, NEVER WHAT IT IS CALLED.

🔴 THE DEFECT THIS PINS, measured on nine live seats 2026-09-04 (row `26f0cecf`).
`default_fleet_gate` classified the fleet with `is_manager_figure`, whose ratified
§2.1 predicate is an OR: an explicit `role == "manager"`, OR the persona NAME being a
named entry of `COSA_VOICE_PREFERRED_PERSONA__<PROJECT>`. **The name arm wins over an
explicit declared role.** So:

    persona   role      spawned_by   classified
    Cheech    author    21dff055     MANAGER      <- disagrees with BOTH its inputs
    John      author    21979045     worker

Two seats, identical declared role, identical lineage shape, opposite answers. The only
difference between them is the name. The census read 4 managers / 5 workers where the
bridges say 3 / 6 — and Rick spins managers down over that number.

⚠️ `is_manager_figure` IS NOT THE BUG AND IS DELIBERATELY UNTOUCHED. It answers an
AUTHORIZATION question (the store's managers-first write gate) where the name rule is
ratified and the fail-CLOSED degrade is deliberate. This file pins the COUNTING
predicate, which lives in `fleet_size_cap` as its own function. A similar name is not a
shared predicate — María's ruling, 2026-09-04 21:04.

=== WHAT MAKES THIS FILE DISCRIMINATE RATHER THAN MERELY PASS ===

The load-bearing arm plants two bridges differing ONLY in persona name and in the
`manager_figure_implicit` stamp that a real preferred-persona seat carries. Under the
shipped counting predicate both are workers. **Reintroduce the name lookup — swap
`default_counting_classifier` back to `is_manager_figure` at the census call site — and
that arm goes RED BY NAME**, because Cheech's stamped bridge then counts as a manager.

⚠️ AND THE ARM THAT MATTERS IS TWO MANAGERS, not one. With a single manager a
name-based and a lineage-based census can agree by coincidence; the split only separates
once a second manager exists. That is this row's DONE MEANS #3 and it is why the
four-seat arm is here rather than a cheaper two-seat one.

⚠️ EVERY POPULATED ARM ASSERTS ITS OWN CORPUS SIZE FIRST. A plant that silently lands
nowhere makes `managers == 0` true for the wrong reason, and an empty discovery passes
every per-item assertion in the loop.
"""
import json
import os
import re
import subprocess
import sys

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from lupin_cli.claude_code.hooks.lib import session_bridge
from lupin_mcp import fleet_size_cap, session_spawner


# 🔴 THE LIVENESS FILTER READS THE PID OUT OF THE FILENAME, and a bridge whose pid is
# dead is dropped before the file is ever opened. `test_the_census_seam_reads_the_
# isolated_directory` learned that the expensive way and its comment says so.
#
# ⚠️ IT ALSO ESTABLISHED THAT WALKING THIS PROCESS'S ANCESTRY DOES NOT YIELD ENOUGH
# PIDS — it bottoms out at init, and `_is_pid_alive( 1 )` is False for an unprivileged
# user because `os.kill( 1, 0 )` raises PermissionError. Four seats are needed for the
# two-manager arm, so this fixture OWNS four genuinely-live processes instead of
# borrowing them from the ancestry.
@pytest.fixture
def live_pids():
    """Four genuinely-running processes, reaped at teardown."""
    procs = [ subprocess.Popen( [ "sleep", "120" ] ) for _ in range( 4 ) ]
    try:
        yield [ p.pid for p in procs ]
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait( timeout=5 )
            except subprocess.TimeoutExpired:      # pragma: no cover - defensive reap
                p.kill()


def _plant( pid, *, persona, role, spawned_by, implicit ):
    """
    Write ONE live-looking bridge carrying the fields both predicates read.

    `manager_figure_implicit` is what a real preferred-persona seat carries — it is the
    stamp `is_manager_figure` trusts server-side. Planting it is what lets the
    load-bearing arm redden if the name lookup is ever restored.
    """
    directory = session_bridge.SESSION_DIR
    directory.mkdir( parents=True, exist_ok=True )
    body = {
        "session_id"              : f"seat-{persona}",
        "voice_persona"           : { "name": persona },
        "role"                    : role,
        "manager_figure_implicit" : implicit,
        "cwd"                     : str( directory ),
    }
    if spawned_by is not None:
        body[ "spawned_by" ] = spawned_by
    ( directory / f"cc-{pid}.json" ).write_text( json.dumps( body ) )


def _census():
    """The REAL census over the REAL scan, with the shipped counting classifier."""
    sessions = session_bridge.find_active_voice_persona_sessions()
    return sessions, fleet_size_cap.census( sessions, fleet_size_cap.default_counting_classifier )


_SPLIT_RE = re.compile( r"\((\d+) manager\(s\), (\d+) worker\(s\)\)" )


def _split_via_the_GATE( cap ):
    """
    The split as the SHIPPED SPAWN PATH computes it — `default_fleet_gate` for real,
    with the classifier it actually wires in.

    🔴 THIS EXISTS BECAUSE THE FIRST CUT OF THIS FILE COULD NOT SEE ITS OWN MUTATION.
    Its load-bearing arms called `census( sessions, default_counting_classifier )`
    directly, naming the classifier themselves. Measured: reverting the CALL SITE in
    `session_spawner` to `is_manager_figure` left every one of those arms GREEN — they
    were pinning the predicate, which was never in doubt, while the wiring they were
    written for went unwatched. Only the one arm that drove the gate reddened.

    ⇒ A test that names the collaborator itself cannot notice the product choosing a
    different one. Enter at the layer the defect enters at: the gate.
    """
    refusal = session_spawner.default_fleet_gate( 1, config_fn=_config( cap ) )
    assert refusal is not None, (
        f"this reader needs a REFUSAL to read the split out of — cap {cap} did not refuse"
    )
    found = _SPLIT_RE.search( refusal )
    assert found, f"the refusal must name the split — saw: {refusal}"
    return { "managers": int( found.group( 1 ) ), "workers": int( found.group( 2 ) ) }


def _config( cap ):
    class _Config:
        def get( self, key, default=None, return_type="string", silent=False ):
            return { "cc session fleet size cap"         : cap,
                     "cc session fleet size cap maximum" : 18 }.get( key, default )
    return lambda: _Config()


# ─────────────────────────── the pure predicate ───────────────────────────
# Cheap, and they pin the whole truth table so a later reader can see the rule without
# reconstructing it from the populated arms.

@pytest.mark.parametrize( "role,spawned_by,expected,why", [
    ( "manager", "21dff055", True,  "an explicit manager declaration is never overruled by its lineage" ),
    ( "manager", None,       True,  "an explicit manager declaration stands alone" ),
    ( "author",  "21dff055", False, "a declared non-manager role with a lineage is a worker" ),
    ( "author",  None,       False, "a declared non-manager role is a worker even unparented" ),
    ( "reviewer","21979045", False, "the role need not be 'author' — any declared non-manager role" ),
    ( None,      "21dff055", False, "no role but a lineage: somebody spawned it, so it is a worker" ),
    ( None,      None,       True,  "neither declared nor parented: a top-level seat" ),
    ( "",        "  ",       True,  "blank strings are absent, because that is how they reach a bridge" ),
] )
def test_the_counting_predicate_reads_role_and_lineage( role, spawned_by, expected, why ):
    assert fleet_size_cap.counted_as_manager( role, spawned_by ) is expected, why


def test_the_predicate_takes_no_persona_at_all():
    """
    🔴 THE STRUCTURAL GUARD. The counting predicate's signature carries `role` and
    `spawned_by` and NOTHING ELSE — there is no parameter a persona name could enter
    through. A future change that reintroduces the name lookup has to widen this
    signature, and this assertion is what makes that visible in a diff review rather
    than only in a behavioural arm somebody might delete.
    """
    import inspect
    params = list( inspect.signature( fleet_size_cap.counted_as_manager ).parameters )
    assert params == [ "role", "spawned_by" ], (
        f"the counting predicate must read declared role and lineage only — saw {params}"
    )


# ─────────────────────── the load-bearing behavioural arm ───────────────────────

def test_two_seats_with_the_SAME_declared_role_and_DIFFERENT_NAMES_classify_the_SAME( live_pids ):
    """
    🔴 THIS IS THE ARM THAT REDDENS IF THE NAME LOOKUP COMES BACK.

    Two bridges, identical `role="author"`, identical lineage shape. They differ in the
    persona name and in the `manager_figure_implicit` stamp — exactly as the live Cheech
    and John bridges differed on 2026-09-04. Both must count as WORKERS.

    Restore `is_manager_figure` at the census call site and Cheech's stamped bridge
    counts as a manager: managers becomes 1 and this fails by name.
    """
    _plant( live_pids[ 0 ], persona="Cheech", role="author", spawned_by="21dff055", implicit=True )
    _plant( live_pids[ 1 ], persona="John",   role="author", spawned_by="21979045", implicit=False )

    sessions, counts = _census()
    assert len( sessions ) == 2, (
        f"POSITIVE CONTROL: both planted bridges must be discovered — saw {len( sessions )}. "
        f"A corpus of 0 makes 'managers == 0' true for the wrong reason."
    )

    # THE READING THAT MATTERS — through the gate, so a call-site revert reddens here.
    assert _split_via_the_GATE( 2 ) == { "managers": 0, "workers": 2 }, (
        "two seats declaring the same role must classify the same. A managers count of 1 "
        "means the persona NAME is deciding at the spawn path's own call site, which is "
        "the defect row 26f0cecf exists to close."
    )

    # And the predicate agrees when named directly. Secondary: this arm alone cannot
    # see a call-site revert — see `_split_via_the_GATE`.
    assert counts == { "total": 2, "managers": 0, "workers": 2, "unknown": 0 }, counts


def test_TWO_managers_beside_TWO_workers_split_correctly( live_pids ):
    """
    ⚠️ THE TWO-MANAGER ARM — DONE MEANS #3, and the case where a name-based and a
    declaration-based census stop coinciding. With ONE manager the two definitions can
    agree by accident; the divergence needs a second.

    María and Mr. Radio are unparented and undeclared (managers). Cheech and John both
    declare `author` with a lineage (workers) — and Cheech carries the implicit stamp,
    so a name-based census would report 3/1 here instead of 2/2.
    """
    _plant( live_pids[ 0 ], persona="María",     role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 1 ], persona="Mr. Radio", role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 2 ], persona="Cheech",    role="author", spawned_by="21dff055", implicit=True )
    _plant( live_pids[ 3 ], persona="John",      role="author", spawned_by="21979045", implicit=False )

    sessions, counts = _census()
    assert len( sessions ) == 4, f"POSITIVE CONTROL: four planted bridges — saw {len( sessions )}"

    # Through the gate: this is what a call-site revert moves.
    assert _split_via_the_GATE( 4 ) == { "managers": 2, "workers": 2 }, (
        "expected two managers beside two workers. A managers count of 3 means Cheech's "
        "NAME outvoted his declared role at the spawn path's call site."
    )
    assert counts == { "total": 4, "managers": 2, "workers": 2, "unknown": 0 }, counts


def test_an_explicitly_declared_manager_counts_as_a_manager_even_with_a_lineage( live_pids ):
    """
    A manager spawned BY another manager is still a manager. This arm exists because
    María's rule as spoken — "worker if a declared role OR a lineage is present" —
    reproduces all nine live seats only because none of them carried `role="manager"`.
    Applied literally it would count an explicit manager as a worker, which is the same
    failure the name rule commits, pointing the other way.
    """
    _plant( live_pids[ 0 ], persona="Somebody", role="manager", spawned_by="21dff055", implicit=False )

    sessions, counts = _census()
    assert len( sessions ) == 1, f"POSITIVE CONTROL: one planted bridge — saw {len( sessions )}"
    assert _split_via_the_GATE( 1 ) == { "managers": 1, "workers": 0 }, (
        "an explicit manager declaration must not be overruled by its lineage"
    )
    assert counts == { "total": 1, "managers": 1, "workers": 0, "unknown": 0 }, counts


def test_a_seat_with_NO_declared_role_but_A_LINEAGE_counts_as_a_worker( live_pids ):
    """
    🔴 THIS ARM WAS ADDED BECAUSE A MUTATION SURVIVED WITHOUT IT, and the survivor is
    worth recording. `read_counting_fields` was changed to stop reading `spawned_by`
    at all — returning ( role, None ) — and the whole file stayed GREEN.

    The reason is a fixture defect, not a weak assertion: every worker in the arms
    above declares `role="author"`, so the predicate returns False on the declared-role
    branch and never consults lineage. The lineage branch was pinned ONLY in the pure
    parametrize, which calls `counted_as_manager` directly and never touches the reader.

    ⇒ So the bridge FIELD went unwatched while the PREDICATE looked thoroughly tested.
    This arm plants the one shape that separates them: a spawned seat whose bridge
    carries no `role`. It must count as a WORKER — somebody spawned it.
    """
    _plant( live_pids[ 0 ], persona="Nameless", role=None, spawned_by="21979045", implicit=False )

    sessions, counts = _census()
    assert len( sessions ) == 1, f"POSITIVE CONTROL: one planted bridge — saw {len( sessions )}"
    assert counts == { "total": 1, "managers": 0, "workers": 1, "unknown": 0 }, (
        f"a seat with a lineage and no declared role is a worker — saw {counts}. "
        f"A managers count of 1 means the reader is not reading `spawned_by` off the bridge."
    )


# ─────────────────── the count reaches the POLICY, not just the scan ───────────────────

def test_the_gate_REFUSES_at_the_cap_and_the_message_names_the_TWO_MANAGER_split( live_pids ):
    """
    The real `default_fleet_gate`, the real arithmetic, the shipped message. Four seats
    against a cap of four: the next spawn must be refused, and the refusal must report
    the split the counting predicate produced.
    """
    _plant( live_pids[ 0 ], persona="María",     role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 1 ], persona="Mr. Radio", role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 2 ], persona="Cheech",    role="author", spawned_by="21dff055", implicit=True )
    _plant( live_pids[ 3 ], persona="John",      role="author", spawned_by="21979045", implicit=False )

    refusal = session_spawner.default_fleet_gate( 1, config_fn=_config( 4 ) )
    assert refusal is not None, "a fleet at its cap must refuse the next spawn"
    assert "the cap is 4" in refusal, refusal
    assert "already running 4" in refusal, refusal
    assert "2 manager(s), 2 worker(s)" in refusal, (
        f"the refusal must report the counting predicate's split — saw: {refusal}"
    )


def test_the_gate_ALLOWS_one_below_the_cap_with_two_managers_live( live_pids ):
    """
    🔴 THE DISCRIMINATING NEGATIVE, and without it the arm above is satisfied by a gate
    that refuses everything. Same four seats, same predicate, cap of five: it must ALLOW.
    """
    _plant( live_pids[ 0 ], persona="María",     role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 1 ], persona="Mr. Radio", role=None,     spawned_by=None,       implicit=True )
    _plant( live_pids[ 2 ], persona="Cheech",    role="author", spawned_by="21dff055", implicit=True )
    _plant( live_pids[ 3 ], persona="John",      role="author", spawned_by="21979045", implicit=False )

    assert session_spawner.default_fleet_gate( 1, config_fn=_config( 5 ) ) is None, (
        "four seats under a cap of five must not be refused"
    )


# ───────────────────────────── the degrade direction ─────────────────────────────

def test_an_unreadable_bridge_reads_UNKNOWN_and_NOT_manager():
    """
    🔴 AMENDED 2026-09-04 — MARÍA OVERRULED MY FIRST ANSWER AND THIS TEST IS THE RECORD.

    I had an unreadable bridge degrade to ( None, None ), which the predicate reads as
    "undeclared and unparented" and therefore counts as a MANAGER. I defended it as the
    safe direction for a cap: the seat stays in `total`, so the cap can only bind
    earlier. Her correction — safe-for-the-cap is not true-for-the-reader, and a
    degraded read rendered as "manager" CONCEALS that the classifier is degraded.

    `read_counting_fields` now returns None (not a tuple) when it could not read, and
    the classifier turns that into `unknown`. See
    `test_the_fleet_split_reports_UNKNOWN_rather_than_guessing.py` for the full contract.
    """
    assert fleet_size_cap.read_counting_fields( "no-such-session-anywhere" ) is None
    assert fleet_size_cap.default_counting_classifier(
        "no-such-session-anywhere" ) == fleet_size_cap.SEAT_UNKNOWN


def quick_smoke_test():
    """Non-destructive: the pure predicate only — no bridges, no processes."""
    assert fleet_size_cap.counted_as_manager( "author", "21dff055" ) is False
    assert fleet_size_cap.counted_as_manager( None, None ) is True
    print( "✓ counting predicate reads role and lineage, not the name" )


if __name__ == "__main__":
    quick_smoke_test()
