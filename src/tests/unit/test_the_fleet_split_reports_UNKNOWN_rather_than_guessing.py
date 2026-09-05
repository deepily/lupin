#!/usr/bin/env python3
"""
AN UNREADABLE SEAT IS A THIRD STATE — the split must say UNKNOWN, never resolve it.

🔴 MARÍA'S RULING, 2026-09-04 21:52, overruling me. My first cut let an unreadable
bridge degrade to (None, None), which the counting predicate reads as "undeclared and
unparented" and therefore counts as a MANAGER. I defended that as the safe direction
for a cap — the seat stays in `total`, so the cap can only bind earlier.

Her correction, and it is the right one: **safe-for-the-cap is not the same as
true-for-the-reader.** A degraded classification rendered as "manager" is a confident
answer to a question nobody could answer, and it CONCEALS that the classifier is
degraded. Reported as UNKNOWN it tells the reader both things at once.

⇒ Three states, not two resolved in the safe direction:
      manager · worker · unknown        managers + workers + unknown == total

=== AND THE DEGRADATION LIVES IN THE DATA, NOT ONLY IN ONE HUMAN-FACING STRING ===

Her second ruling, the same minute. Putting UNKNOWN only in the refusal sentence fixes
what a human reads at the spawn gate and leaves every other consumer of the census dict
— `GET /api/arbiter/fleet-size-cap`, and the operator pane it renders — reporting a
clean split over a degraded read. So the key is on the dict.

=== 🔴 WHY THIS FILE EXISTS RATHER THAN AN EDIT TO THE DIAL'S EXISTING TEST ===

`test_the_fleet_size_dial_serves_the_key_not_a_constant.py:428` looks like the guard for
this and cannot be. It STUBS the thing it checks:

    monkeypatch.setattr( arbiter, "_live_fleet_counts", lambda: {...literal...} )
    assert body[ "live" ] == {...the same literal...}

Both sides come from one source, so it asserts the endpoint passes a dict through and
nothing about the census contract. Measured: it stays GREEN across this entire change.
Its sibling at :444 stubs the same function. **Those are the ONLY two tests naming
`_live_fleet_counts`, so NOTHING drove the real one** — the server's split was
`is_manager_figure`'s, unfixed and unwatched, while the module it calls sat fully tested.

⇒ This file drives the REAL `_live_fleet_counts` against planted bridges. Every arm was
run against the pre-change code first and FAILED there; the reds are recorded on row
`26f0cecf`.
"""
import json
import os
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.routers import arbiter
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from lupin_cli.claude_code.hooks.lib import session_bridge
from lupin_mcp import fleet_size_cap


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( arbiter.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture( autouse=True )
def _no_ambient_ini( monkeypatch, tmp_path ):
    """Same reason as the dial's own fixture: keep the fresh disk read off the live INI."""
    monkeypatch.setattr( fleet_size_cap, "config_file_path",
                         lambda: str( tmp_path / "no-such-config.ini" ) )


@pytest.fixture
def live_pids():
    """Three genuinely-running processes — the liveness filter reads the pid out of the
    bridge FILENAME, so a planted bridge needs a real one."""
    procs = [ subprocess.Popen( [ "sleep", "120" ] ) for _ in range( 3 ) ]
    try:
        yield [ p.pid for p in procs ]
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait( timeout=5 )
            except subprocess.TimeoutExpired:      # pragma: no cover - defensive reap
                p.kill()


def _plant( pid, *, persona, role, spawned_by, body=None ):
    directory = session_bridge.SESSION_DIR
    directory.mkdir( parents=True, exist_ok=True )
    path = directory / f"cc-{pid}.json"
    if body is not None:
        path.write_text( body )                    # deliberately unparseable
        return
    payload = { "session_id"    : f"seat-{persona}",
                "voice_persona" : { "name": persona },
                "role"          : role,
                "cwd"           : str( directory ) }
    if spawned_by is not None:
        payload[ "spawned_by" ] = spawned_by
    path.write_text( json.dumps( payload ) )


# ───────────────────────── the census contract ─────────────────────────

def test_the_census_dict_CARRIES_unknown_and_the_three_reconcile():
    """
    The shape itself. `managers + workers + unknown == total` is the invariant that
    replaces the old two-way one, and a reader can only trust the split if it holds.
    """
    counts = fleet_size_cap.census( [ ( "p", "s0", { } ), ( "p", "s1", { } ) ],
                                    lambda sid: "manager" if sid == "s0" else "unknown" )
    assert counts == { "total": 2, "managers": 1, "workers": 0, "unknown": 1 }
    assert counts[ "managers" ] + counts[ "workers" ] + counts[ "unknown" ] == counts[ "total" ]


def test_a_classifier_that_RAISES_is_UNKNOWN_and_no_longer_silently_a_worker():
    """
    🔴 THE BEHAVIOUR CHANGE, stated plainly. It used to be counted as a worker — a
    guess, rendered as a fact. It still occupies a seat (that ruling is untouched: it
    stays in `total`, so the cap cannot bind later), but the split now says it could
    not be read.
    """
    def explode( session_id ):
        if session_id == "s2":
            raise RuntimeError( "bridge unreadable" )
        return session_id == "s0"

    counts = fleet_size_cap.census(
        [ ( "p", f"s{n}", { } ) for n in range( 4 ) ], explode )
    assert counts[ "total" ] == 4, "an unclassifiable session must never vanish from the total"
    assert counts == { "total": 4, "managers": 1, "workers": 2, "unknown": 1 }


def test_an_UNPARSEABLE_bridge_classifies_UNKNOWN_not_manager( live_pids ):
    """
    🔴 THE ARM THAT SEPARATES DEGRADED FROM TOP-LEVEL, and it is the whole point of the
    third state. Before this change both landed on (None, None): a seat whose bridge is
    corrupt and a seat that genuinely declares nothing were the same answer — MANAGER.
    """
    _plant( live_pids[ 0 ], persona="Broken", role=None, spawned_by=None, body="{ not json" )
    assert fleet_size_cap.default_counting_classifier( "seat-Broken" ) == "unknown"


def test_a_seat_that_GENUINELY_declares_nothing_is_still_a_manager( live_pids ):
    """
    The discriminating counterpart. Without it the arm above is satisfied by calling
    everything unknown, which would be a different lie in the same place.
    """
    _plant( live_pids[ 0 ], persona="Toplevel", role=None, spawned_by=None )
    assert fleet_size_cap.default_counting_classifier( "seat-Toplevel" ) == "manager"


# ───────────────────── the refusal names it ─────────────────────

def test_the_REFUSAL_names_the_unknown_seats():
    counts  = { "total": 4, "managers": 1, "workers": 2, "unknown": 1 }
    refusal = fleet_size_cap.refusal_for_spawn( 1, counts, 4 )
    assert refusal is not None
    assert "1 unclassified" in refusal, (
        f"a degraded read must be visible in the refusal, not folded into a clean "
        f"split — saw: {refusal}"
    )


def test_a_CLEAN_split_says_nothing_about_unknown():
    """
    The discriminating negative. A refusal that always mentions unclassified seats
    carries no information when one actually appears.
    """
    refusal = fleet_size_cap.refusal_for_spawn(
        1, { "total": 4, "managers": 1, "workers": 3, "unknown": 0 }, 4 )
    assert refusal is not None
    assert "unclassified" not in refusal, refusal


# ─────────────── the API surface, driving the REAL census ───────────────

def test_the_ENDPOINT_counts_by_declaration_and_not_by_persona_name( client, live_pids ):
    """
    🔴 THE ARM FOR `arbiter.py:263`, WHICH NO TEST HAS EVER REACHED. The handler used
    `is_manager_figure`, so the operator pane reported the NAME-based split while the
    spawn gate reported the declaration-based one — two derivations of one number,
    agreeing until the day somebody needed them.

    Cheech declares `role="author"` with a lineage. He is a WORKER at the pane, exactly
    as he is at the gate.
    """
    _plant( live_pids[ 0 ], persona="Cheech", role="author", spawned_by="21dff055" )
    _plant( live_pids[ 1 ], persona="María",  role=None,     spawned_by=None )

    live = client.get( "/api/arbiter/fleet-size-cap" ).json()[ "live" ]
    assert live[ "total" ] == 2, (
        f"POSITIVE CONTROL: both planted bridges must reach the endpoint — saw {live}"
    )
    assert live == { "total": 2, "managers": 1, "workers": 1, "unknown": 0 }, (
        f"the pane must count the way the gate counts. A managers count of 2 means the "
        f"handler is still classifying by persona NAME — saw {live}"
    )


def test_the_ENDPOINT_surfaces_a_degraded_read_rather_than_concealing_it(
        client, live_pids, monkeypatch ):
    """
    And the third state reaches the pane. This is the arm that makes "the degradation
    lives in the DATA" true rather than aspirational — an operator reading the dial can
    see that a seat could not be classified.

    🔴 THE DEGRADE IS INDUCED AT THE RE-LOCATION STEP, NOT BY CORRUPTING THE FILE, AND
    THE FIRST CUT OF THIS ARM GOT THAT WRONG. See the test below for what a corrupt
    bridge actually does. The census reads each seat TWICE by two different routes —
    the directory scan supplies the session id, then `find_session_path_by_id` re-opens
    that seat's bridge for its `role` and `spawned_by`. A seat can pass the first and
    fail the second: renamed, unlinked, or rewritten between the two reads. That is the
    real path to `unknown`, and it is a plain time-of-check/time-of-use window.
    """
    _plant( live_pids[ 0 ], persona="Fine",     role="author", spawned_by="21dff055" )
    _plant( live_pids[ 1 ], persona="Vanished", role="author", spawned_by="21dff055" )

    from lupin_cli.claude_code.hooks.lib import session_bridge as sb
    real_locator = sb.find_session_path_by_id
    monkeypatch.setattr( sb, "find_session_path_by_id",
                         lambda sid, *a, **k: None if sid == "seat-Vanished"
                                              else real_locator( sid, *a, **k ) )

    live = client.get( "/api/arbiter/fleet-size-cap" ).json()[ "live" ]
    assert live[ "total" ] == 2, f"POSITIVE CONTROL: two planted bridges — saw {live}"
    assert live[ "unknown" ] == 1, (
        f"a seat whose bridge could not be re-read must show as unclassified at the "
        f"pane, not be resolved into a manager — saw {live}"
    )
    assert live[ "managers" ] == 0, (
        f"and it must NOT be counted as a manager, which is the pre-ruling behaviour — "
        f"saw {live}"
    )


def test_a_CORRUPT_bridge_VANISHES_from_the_census_entirely_KNOWN_GAP( client, live_pids ):
    """
    ⚠️ THIS PINS TODAY'S BEHAVIOUR AND TODAY'S BEHAVIOUR IS WRONG. It is here so the
    gap is visible and so a future fix reddens deliberately rather than silently.

    🔴 MEASURED 2026-09-04 while writing the arm above, which I had built on the
    assumption that a corrupt bridge produces `unknown`. It does not. The directory
    scan requires a parseable `voice_persona`, so an unreadable bridge is dropped
    BEFORE the census ever sees it — the seat does not become unclassified, it becomes
    INVISIBLE.

    ⇒ That is worse than a wrong split, and it points the dangerous way: the seat is
    missing from `total`, so the cap UNDER-COUNTS the fleet and permits a spawn it
    should refuse. `unknown` at least keeps the seat in the total.

    ⇒ Not fixed here. Fixing it means changing what the SCAN returns, which is shared
    with the voice-persona allocation endpoints — a blast radius well outside this row.
    Reported to María 2026-09-04 as its own finding.
    """
    _plant( live_pids[ 0 ], persona="Fine",   role="author", spawned_by="21dff055" )
    _plant( live_pids[ 1 ], persona="Broken", role=None, spawned_by=None, body="}{ corrupt" )

    live = client.get( "/api/arbiter/fleet-size-cap" ).json()[ "live" ]
    assert live == { "total": 1, "managers": 0, "workers": 1, "unknown": 0 }, (
        f"KNOWN GAP CHANGED — a corrupt bridge used to vanish from the census before "
        f"reaching it. If this now reports 2 the scan has been fixed and this test "
        f"should be replaced by a real assertion. Saw {live}"
    )


def quick_smoke_test():
    """Non-destructive: the census contract only — no bridges, no processes, no server."""
    counts = fleet_size_cap.census( [ ( "p", "s0", { } ) ], lambda sid: "unknown" )
    assert counts == { "total": 1, "managers": 0, "workers": 0, "unknown": 1 }
    print( "✓ the census carries a third state" )


if __name__ == "__main__":
    quick_smoke_test()
