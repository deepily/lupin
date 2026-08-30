"""
AC-G4 — the cross-repo drift guard. The lupin-mobile fixture of the server's job-state → UI-lane
map must equal the LIVE `STATE_TO_UI_CONTAINER` in `src/cosa/rest/job_state.py`, bidirectionally.

WHY THIS LIVES IN THE PARENT REPO AND NOT IN lupin-mobile. Drift is a property of the PAIR of
repos, and a mobile test can only assert things inside the mobile repo. The chain today is:

    job_lifecycle.dart  <-pinned by-  job_lifecycle_test.dart (AC-S1.1)  <-reads-  the fixture
                                                                                      ^
                                                                          nothing pinned this

AC-S1.1 pins Dart to the fixture. Nothing pinned the fixture to the server, so a state added or a
lane changed in `job_state.py` left Dart green on the phone and wrong on the wire. This file is
the missing link, and it can only be written from here because only here are both sides on disk.

Precedent for the shape: `src/tests/unit/deploy/test_external_scope_mount_parity.py` — declared-set
vs satisfied-set, asserted in BOTH directions so neither side becomes a one-way ratchet.

THE FAILURE MODE THIS FILE IS SHAPED AROUND is not drift; it is a guard that passes without
watching anything. Three separate ways that happens here, and the three defenses:

  1. FIXTURE FILE ABSENT. A parity test that skips when its input is missing is a test that a
     one-character path typo disables forever, silently and green. So absence is split: the
     nested repo is detected by a marker that is NOT the fixture (`pubspec.yaml`). Repo present
     but fixture missing -> HARD FAIL, because that is drift (moved/deleted/typo'd). Repo itself
     absent -> skip, which is honest: a git worktree has no `src/lupin-mobile` at all, measured.

  2. EITHER SIDE EMPTY. An empty dict compares equal to nothing and every "for k in ..." loop
     over it passes vacuously. Both sides are asserted non-empty before they are compared.

  3. THE WRONG FIXTURE. Pinning a file Dart no longer reads is the same green-for-nothing:
     someone re-points `job_lifecycle_test.dart` at another fixture, leaves this one on disk,
     and this test happily guards an orphan. `test_the_dart_consumer_still_reads_this_fixture`
     reads the Dart test's own `loadFixture(...)` argument and fails if it stopped naming this
     file.

WHAT THIS TEST CANNOT SEE:
  - A NEW LANE VALUE agreed by both sides. If `job_state.py` grew a lane `"archive"` and the
    fixture was updated to match, this file goes green — correctly, they agree — while Dart's
    `JobLane` enum has no such member. That direction is covered on the mobile side: AC-S1.1
    compares `parsed.lane.name` against the fixture value, so a lane Dart cannot name fails
    there. It is named here so nobody reads this file's green as covering it.
  - Anything about the RUNNING server. This is a static source-vs-file comparison; it answers
    "do the two checked-in things agree", never "is that what the phone received".
"""

import json
import re

from pathlib import Path

import pytest

REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]

# The nested lupin-mobile repo. `MOBILE_MARKER` is deliberately a DIFFERENT file from the
# fixture: it answers "is the nested repo checked out here at all", which is the only question
# that may legitimately end in a skip. Using the fixture itself for both questions is what turns
# a path typo into a permanent silent pass.
MOBILE_ROOT   = REPO_ROOT / "src" / "lupin-mobile"
MOBILE_MARKER = MOBILE_ROOT / "pubspec.yaml"

# The fixture, and the Dart test that consumes it. FIXTURE_REL is the exact string the Dart side
# passes to `loadFixture()`; both are asserted, so the pair cannot drift apart either.
FIXTURE_REL   = "queue/state_to_ui_container.json"
FIXTURE_PATH  = MOBILE_ROOT / "test" / "fixtures" / FIXTURE_REL
DART_CONSUMER = MOBILE_ROOT / "test" / "unit" / "queue" / "job_lifecycle_test.dart"


def _require_mobile_checkout():
    """
    Skip only when the nested repo is absent entirely; never when it is present but incomplete.

    Ensures:
        - skips iff `src/lupin-mobile/pubspec.yaml` is missing (worktrees, VM checkouts)
        - returns None otherwise
    """
    if not MOBILE_MARKER.exists():
        pytest.skip(
            f"nested repo lupin-mobile is not checked out here ({MOBILE_MARKER} missing) — "
            f"no fixture exists to compare against. A git worktree has no src/lupin-mobile; "
            f"run this from the main tree."
        )


SERVER_SOURCE = REPO_ROOT / "src" / "cosa" / "rest" / "job_state.py"


def _server_map_from_source():
    """
    The `STATE_TO_UI_CONTAINER` literal, read out of `job_state.py` as TEXT.

    This is NOT the authoritative reading — `_server_map()` below imports the module, which is
    what survives a refactor. This exists only to be COMPARED against the import, for the reason
    in `_server_map`'s docstring.

    Ensures:
        - returns {state_string: lane_string} parsed from the literal dict block
        - raises if the block cannot be located — a refactor must be seen, never skipped past
    """
    text  = SERVER_SOURCE.read_text( encoding="utf-8" )
    block = re.search( r"^STATE_TO_UI_CONTAINER\s*=\s*\{(.*?)^\}", text, re.MULTILINE | re.DOTALL )
    assert block, (
        f"could not find the `STATE_TO_UI_CONTAINER = {{ ... }}` literal in {SERVER_SOURCE}.\n"
        f"If it was refactored behind a function or a loop, this cross-check must be rewritten "
        f"to match — it is what stops a stale .pyc from silently supplying the map (see "
        f"_server_map). Deleting it instead re-opens that hole."
    )

    pairs = re.findall( r"JobState\.(\w+)\s*:\s*\"([^\"]+)\"", block.group( 1 ) )
    assert pairs, f"the STATE_TO_UI_CONTAINER block in {SERVER_SOURCE} parsed to zero entries"
    return pairs


def _server_map():
    """
    The live `STATE_TO_UI_CONTAINER`, as {state_string: lane_string}.

    IMPORTED, then CROSS-CHECKED AGAINST THE SOURCE TEXT. The import is authoritative — a regex
    alone would keep passing after a refactor moved the dict behind a function. But the import
    alone is not trustworthy either, and that is measured, not theoretical:

        MEASURED 2026-08-29, while mutation-proving this very file. `job_state.py` was edited
        (`"todo"` -> `"dead"`, a SAME-LENGTH edit) at 21:33:22.780; a pytest run had compiled
        `__pycache__/job_state.cpython-313.pyc` at 21:33:22.568. CPython's default pyc validation
        compares the source's whole-SECOND mtime and its SIZE — both were unchanged — so the
        stale bytecode was served as valid. `grep` said the lane was `todo` and `import` said
        `dead`, at the same instant, for minutes.

    A guard whose input can be a ghost is a guard that reports green on a map nobody is running.
    So both readings are taken and they must agree; a disagreement means stale bytecode or a
    shadowing module, and it is reported as such rather than silently picking a winner.

    Ensures:
        - returns a non-empty {str: str} dict
        - raises if the mapping is empty — every comparison below would pass vacuously
        - raises if the imported mapping disagrees with the source text
    """
    from cosa.rest.job_state import STATE_TO_UI_CONTAINER

    mapping = { str( state.value ): str( lane ) for state, lane in STATE_TO_UI_CONTAINER.items() }
    assert mapping, "STATE_TO_UI_CONTAINER is empty — instrument failure, not parity"

    from_source = { name: lane for name, lane in _server_map_from_source() }
    imported    = { state.name: str( lane ) for state, lane in STATE_TO_UI_CONTAINER.items() }
    assert imported == from_source, (
        f"the IMPORTED STATE_TO_UI_CONTAINER disagrees with the text of {SERVER_SOURCE}:\n"
        f"  imported   : {imported}\n"
        f"  source text: {from_source}\n"
        f"This is not a parity failure — it is a STALE IMPORT. Python is serving bytecode that "
        f"no longer matches the file. Most likely a same-second, same-size edit defeated pyc "
        f"timestamp validation (measured here 2026-08-29). Clear it and re-run:\n"
        f"  find src -name '__pycache__' -type d -exec rm -rf {{}} +\n"
        f"If it persists, another job_state module is shadowing this one on sys.path."
    )
    return mapping


def _fixture_map():
    """
    The mobile fixture's `map` block, as {state_string: lane_string}.

    Ensures:
        - returns a non-empty {str: str} dict
        - raises (never skips) if the fixture is missing while the repo IS checked out
    """
    _require_mobile_checkout()

    assert FIXTURE_PATH.exists(), (
        f"lupin-mobile IS checked out ({MOBILE_MARKER} present) but the parity fixture is "
        f"missing: {FIXTURE_PATH}\n"
        f"This is drift, not an environment gap — the fixture was moved, renamed or deleted, "
        f"or the path in this test is wrong. Either way AC-G4 is guarding nothing until it is "
        f"fixed, which is why this fails instead of skipping."
    )

    doc = json.loads( FIXTURE_PATH.read_text( encoding="utf-8" ) )
    assert "map" in doc, f"{FIXTURE_PATH} has no top-level 'map' key; got {sorted( doc )}"

    mapping = doc[ "map" ]
    assert isinstance( mapping, dict ) and mapping, f"{FIXTURE_PATH} 'map' is empty or not an object"
    assert all( isinstance( k, str ) and isinstance( v, str ) for k, v in mapping.items() ), (
        f"{FIXTURE_PATH} 'map' must be flat string->string; got "
        f"{ { k: type( v ).__name__ for k, v in mapping.items() } }"
    )
    return mapping


def test_every_server_state_is_in_the_mobile_fixture_with_the_same_lane():
    """
    DIRECTION 1 — server -> fixture. Alone, this passes when the fixture carries an extra state
    the server has retired.

    Ensures:
        - every JobState in STATE_TO_UI_CONTAINER appears as a fixture key
        - each one carries the identical lane string
    """
    server  = _server_map()
    fixture = _fixture_map()

    missing = sorted( set( server ) - set( fixture ) )
    assert not missing, (
        f"{len( missing )} server job state(s) have NO entry in the mobile fixture: {missing}\n"
        f"A state added to src/cosa/rest/job_state.py reaches the phone on the wire before it "
        f"reaches the phone's enum; unmapped, the Dart side drops the frame.\n"
        f"FIX: add the state to {FIXTURE_PATH} 'map' with its lane, and to JobLifecycleState in "
        f"lib/features/queue/domain/job_lifecycle.dart."
    )

    disagreements = { state: ( server[ state ], fixture[ state ] )
                      for state in sorted( set( server ) & set( fixture ) )
                      if server[ state ] != fixture[ state ] }
    assert not disagreements, (
        f"lane disagreement(s) between the server and the mobile fixture "
        f"{{state: (server, fixture)}}: {disagreements}\n"
        f"The phone would file these jobs in the wrong column. FIX: update {FIXTURE_PATH}."
    )


def test_every_mobile_fixture_state_exists_on_the_server():
    """
    DIRECTION 2 — fixture -> server, and the half a one-way check leaves out. Alone, this passes
    when the server has grown a state the fixture never heard of.

    Ensures:
        - no fixture key names a state the server does not define
    """
    server  = _server_map()
    fixture = _fixture_map()

    invented = sorted( set( fixture ) - set( server ) )
    assert not invented, (
        f"{len( invented )} state(s) in the mobile fixture do NOT exist in the server's "
        f"STATE_TO_UI_CONTAINER: {invented}\n"
        f"Either the server retired them (delete from {FIXTURE_PATH} and from "
        f"JobLifecycleState) or they were invented on the phone and nothing will ever emit them."
    )


def test_the_two_maps_are_identical():
    """
    The decisive assertion. The two directional tests above exist so a failure names WHICH way
    the drift runs; this one is what makes "bidirectional" a single fact rather than a claim
    assembled from two.

    Ensures:
        - the server map and the fixture map are equal as dicts
    """
    assert _server_map() == _fixture_map(), (
        f"the mobile fixture and STATE_TO_UI_CONTAINER are not identical.\n"
        f"server : {_server_map()}\n"
        f"fixture: {_fixture_map()}"
    )


def test_the_dart_consumer_still_reads_this_fixture():
    """
    The anti-orphan check. Guarding a file nobody reads is green-for-nothing, and it is invisible
    from either repo's own test suite: the Dart side keeps passing against its new fixture, and
    the comparison here keeps passing against the abandoned one.

    Ensures:
        - job_lifecycle_test.dart exists
        - it calls loadFixture() naming exactly FIXTURE_REL
    """
    _require_mobile_checkout()

    assert DART_CONSUMER.exists(), (
        f"the AC-S1.1 consumer {DART_CONSUMER} is gone. If the Dart-side parity test was moved "
        f"or renamed, point this test at it — until then nothing connects the fixture guarded "
        f"here to any code that reads it."
    )

    loaded = re.findall( r"loadFixture\(\s*'([^']+)'\s*\)", DART_CONSUMER.read_text( encoding="utf-8" ) )
    assert FIXTURE_REL in loaded, (
        f"{DART_CONSUMER} no longer loads '{FIXTURE_REL}' (it loads {loaded}).\n"
        f"This test would keep passing against an orphaned fixture while the one Dart actually "
        f"reads drifts unwatched. FIX: re-point FIXTURE_REL here at the fixture Dart consumes."
    )
