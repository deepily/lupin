"""
Both doors into the 119 TypeScript files must reach the SAME capped cgroup.

🔴 WHAT THIS GUARDS, AND WHY A COMMENT COULD NOT. On 2026-08-23 two doors into
one test corpus were capped independently, one was missed, and the uncapped one
OOM-killed a session. The remedy was `src/scripts/lib/jstest-slice.sh` — ONE
ceiling, sourced by both doors, so neither can carry a copy that drifts.

⚠️ THE REMEDY SHIPPED BROKEN AND STAYED BROKEN. `run-js-tests-capped.sh` lives in
`src/scripts/`, so the repo root is TWO directories up; it said `SCRIPT_DIR/..`,
which lands on `src/` and gives every path built from it a phantom `src/` segment.
Measured: the file was ADDED at 8bf71a64 (2026-08-29) with that line already
wrong and was never touched again, so `npm test` has ALWAYS died at its `source`
line and door 1 has ALWAYS been uncapped — SIX DAYS AFTER the incident the cap was
written to prevent. The 2026-08-23 fix never fully landed.

⇒ So the invariant is NOT "npm test runs". It is "both doors reach the same cap",
and that is what these tests assert.

WHY THE EXPECTED ROOT IS DERIVED FROM THIS FILE'S OWN LOCATION, deliberately, in a
repo whose house rule is `cu.get_project_root()`. That helper reads ambient
`LUPIN_ROOT`, which in a worktree names the MAIN checkout — the very class of
wrong-tree answer this file exists to catch. A pin must not derive from the thing
it pins, so the duplication here is intentional and loudly labelled rather than
tidied away.
"""

import re
import subprocess

from pathlib import Path

import pytest


# This file is src/tests/unit/<name>.py, so the repo root is three parents up.
# See the module docstring for why this is NOT cu.get_project_root().
REPO_ROOT = Path( __file__ ).resolve().parents[ 3 ]

THE_SHARED_LIB = "src/scripts/lib/jstest-slice.sh"

# The two doors, named rather than discovered, so that a door DISAPPEARING is a
# failure instead of a smaller loop. test_the_corpus_is_exactly_the_two_known_doors
# below checks this list against the tree and fails if a third door is ever added.
KNOWN_DOORS = (
    "src/scripts/run-js-tests-capped.sh",     # door 1 — what `npm test` runs
    "src/tests/run-typescript-tests.sh",      # door 2 — the merge-gate runner
)


def _project_root_computed_by( door_path ):
    """
    Run a door script's OWN root-resolution lines and report what they produce.

    Requires:
        - door_path is a repo-relative path to a bash script that assigns both
          SCRIPT_DIR and PROJECT_ROOT

    Ensures:
        - returns the absolute path string the script itself would compute, by
          executing its verbatim assignments in bash with ${BASH_SOURCE[0]}
          substituted for the script's real location
        - never consults LUPIN_ROOT, PWD or any ambient root

    Raises:
        - AssertionError if the script does not assign both variables
    """
    absolute = REPO_ROOT / door_path
    source   = absolute.read_text()

    script_dir_line   = re.search( r"^SCRIPT_DIR=.*$",   source, re.MULTILINE )
    project_root_line = re.search( r"^PROJECT_ROOT=.*$", source, re.MULTILINE )

    assert script_dir_line   is not None, f"{door_path} assigns no SCRIPT_DIR"
    assert project_root_line is not None, f"{door_path} assigns no PROJECT_ROOT"

    # The scripts locate themselves via ${BASH_SOURCE[0]}; standing in for bash's
    # sourcing machinery is the whole point, so substitute the real path.
    prologue = "\n".join( [
        script_dir_line.group( 0 ).replace( "${BASH_SOURCE[0]}", str( absolute ) ),
        project_root_line.group( 0 ),
        'echo "$PROJECT_ROOT"',
    ] )

    done = subprocess.run( [ "bash", "-c", prologue ], capture_output=True, text=True )
    assert done.returncode == 0, f"{door_path} prologue failed: {done.stderr}"

    return done.stdout.strip()


def test_the_corpus_is_exactly_the_two_known_doors():
    """
    The denominator control.

    🔴 WITHOUT THIS, EVERY TEST BELOW PASSES VACUOUSLY IF THE CORPUS EMPTIES. A
    loop over nothing is green, and this repo's own doctrine is that an empty
    result and a correct one print the same thing. So discover the doors FROM THE
    TREE — every script that calls the shared ceiling — and check that set against
    the list the other tests iterate.

    Ensures:
        - exactly the doors in KNOWN_DOORS call jstest_slice_exec
        - a third door added without updating this guard is a FAILURE, not a
          silently smaller loop
    """
    found = subprocess.run(
        [ "git", "grep", "-l", "jstest_slice_exec", "--", "src/" ],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    callers = {
        line for line in found.stdout.split()
        if line.endswith( ".sh" ) and not line.endswith( "lib/jstest-slice.sh" )
    }

    assert callers == set( KNOWN_DOORS ), (
        f"the set of scripts reaching the shared cap has changed: {sorted( callers )}. "
        f"A new door must be added to KNOWN_DOORS — an uncapped door into the same 119 "
        f"files is the 2026-08-23 incident."
    )


@pytest.mark.parametrize( "door", KNOWN_DOORS )
def test_a_door_resolves_a_project_root_that_really_holds_the_shared_cap( door ):
    """
    The arm that reddens when the defect is restored.

    Ensures:
        - the root the door computes for ITSELF actually contains
          src/scripts/lib/jstest-slice.sh
        - so a door whose `source` line cannot resolve fails HERE, at a named
          test, instead of at 3am inside `npm test`
    """
    computed = _project_root_computed_by( door )
    lib      = Path( computed ) / THE_SHARED_LIB

    assert lib.is_file(), (
        f"{door} computes PROJECT_ROOT={computed!r}, and {lib} does not exist — "
        f"this door cannot source the shared ceiling, so it runs UNCAPPED. Check for "
        f"a `..` that should be `../..`."
    )


def test_both_doors_resolve_the_SAME_root_and_it_is_the_repo_root():
    """
    The invariant itself: ONE cap, not two that agree by luck.

    ⚠️ Two doors resolving the same lib is not enough on its own — they must
    resolve the same ROOT, or a future edit can point one of them at a second copy
    of the ceiling and the drift the shared lib exists to prevent is back.

    Ensures:
        - every door computes an identical PROJECT_ROOT
        - that root is the repo root, derived independently from this file's own
          location rather than from the doors themselves
    """
    computed = { door: _project_root_computed_by( door ) for door in KNOWN_DOORS }

    assert len( set( computed.values() ) ) == 1, (
        f"the doors disagree about the repo root: {computed}. They would source "
        f"different copies of the ceiling — that is the 2026-08-23 shape."
    )
    assert set( computed.values() ) == { str( REPO_ROOT ) }, (
        f"the doors agree with each other but not with the tree they live in: "
        f"{computed} vs {REPO_ROOT}"
    )


def test_the_probe_itself_can_fail( tmp_path ):
    """
    The positive control for the instrument.

    🔴 A CHECK THAT HAS NEVER BEEN SEEN TO FAIL IS NOT A CHECK. The two arms above
    read PROJECT_ROOT out of a real script; if the extraction silently returned
    something harmless they would pass over a broken door. So feed the probe a
    door carrying the ORIGINAL defect and assert it reports the wrong root.

    Ensures:
        - a script whose PROJECT_ROOT is one level short resolves to <root>/src
        - and therefore does NOT contain the shared cap
    """
    door = tmp_path / "src" / "scripts" / "broken-door.sh"
    door.parent.mkdir( parents=True )
    door.write_text(
        'SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"\n'
        'PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"\n'   # the 8bf71a64 defect, verbatim
    )

    prologue = (
        f'SCRIPT_DIR="$( cd "$( dirname "{door}" )" && pwd )"\n'
        'PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"\n'
        'echo "$PROJECT_ROOT"\n'
    )
    done = subprocess.run( [ "bash", "-c", prologue ], capture_output=True, text=True )

    assert done.stdout.strip() == str( tmp_path / "src" ), (
        "the probe did not reproduce the original defect, so a passing run of the "
        "arms above proves nothing"
    )
    assert not ( Path( done.stdout.strip() ) / THE_SHARED_LIB ).is_file()
