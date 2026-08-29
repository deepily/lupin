"""
Row `e2099400` §6.1 — v2's routing denominator, frozen, and fatal when it cannot be read.

THE BREAK THIS PREVENTS (María's review, 2026-08-26 — a real defect the excision plan would
have shipped). `v2_eval.load_mappable_commands` imported `load_v1_class_to_command` from
`v1_eval_arm`, which reads the live v1 registry out of the pinned worktree. Both the script
and the worktree are being deleted. Two things made that worse than an ordinary dangling
import:

  1. It runs on EVERY v2 eval, not only paired ones — so deleting v1 would have moved v2's
     own numbers.
  2. Its failure path returned **None**, and None makes `compute_metrics` score routing over
     the FULL corpus instead of the eligible-only set. A different denominator, a percentage
     that still prints, and the only notice a WARNING line on stdout. Every figure after the
     deletion would have been quietly incomparable to every figure before it — the same shape
     as the paired run where v1 scored 0.4667 over a corpus missing a whole command category
     while v2 scored 0.9167 over all 100.

⇒ The pin is a fixed sha, so reading the registry live was never buying freshness — only a
dependency. The list is now a checked-in constant stamped with the sha it came from, and a
run that cannot read it RAISES rather than scoring something else.

⚠️ THE FATAL PATH IS THE POINT OF THIS FILE, not the happy one. A loader that returns the
right seven commands is easy; one that refuses to invent a denominator when the file is gone
is the whole fix, and six of the tests below exist to hold it there.

Venue: :7999-eligible. File reads and one import; no server, no state mutation, no network.
"""

import json
import os
import sys

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
FROZEN_PATH  = os.path.join( PROJECT_ROOT, "src", "conf", "v1-eligible-routing-commands.json" )
V2_EVAL_PATH = os.path.join( PROJECT_ROOT, "src", "scripts", "v2_eval.py" )
PIN_SHA      = "15536409"

# The seven the v1 registry at the pin could route. Written out rather than read from the
# file under test — a test that loads its own expectation from the artifact it is checking
# passes no matter what the artifact says.
EXPECTED_COMMANDS = [
    "agent router go to calculator",
    "agent router go to calendar",
    "agent router go to datetime",
    "agent router go to math",
    "agent router go to receptionist",
    "agent router go to todo",
    "agent router go to weather",
]


def _v2_eval():
    """Import v2_eval the way its own runner does — by path, from src/scripts."""
    scripts = os.path.join( PROJECT_ROOT, "src", "scripts" )
    if scripts not in sys.path: sys.path.insert( 0, scripts )
    import v2_eval
    return v2_eval


# ── the artifact itself ──────────────────────────────────────────────────────

def test_the_frozen_list_is_checked_in_and_parses():
    assert os.path.isfile( FROZEN_PATH ), f"the routing denominator is not at {FROZEN_PATH}"
    with open( FROZEN_PATH ) as handle:
        json.load( handle )


def test_the_frozen_list_carries_the_pin_sha_it_came_from():
    """
    Provenance, not decoration. A frozen list with no sha on it is a list somebody will
    eventually re-derive from the wrong tree and not be able to tell.
    """
    with open( FROZEN_PATH ) as handle:
        payload = json.load( handle )
    assert payload[ "pin_sha" ] == PIN_SHA


def test_the_frozen_list_is_exactly_the_seven_routable_commands():
    with open( FROZEN_PATH ) as handle:
        payload = json.load( handle )
    assert sorted( payload[ "commands" ] ) == sorted( EXPECTED_COMMANDS )


# ── the loader, happy path ───────────────────────────────────────────────────

def test_the_loader_returns_the_frozen_commands():
    assert sorted( _v2_eval().load_mappable_commands() ) == sorted( EXPECTED_COMMANDS )


def test_the_loader_never_returns_none():
    """
    ⚠️ THE OLD CONTRACT, KILLED DELIBERATELY. `Optional[List[str]]` returning None is what
    silently widened the denominator; a caller that still checks `if mappable is None` must
    never see one.
    """
    assert _v2_eval().load_mappable_commands() is not None


# ── the loader, every way it can fail ────────────────────────────────────────

def test_a_missing_file_raises_and_says_it_will_not_fall_back( tmp_path ):
    v2_eval = _v2_eval()
    with pytest.raises( v2_eval.EligibleCommandsUnavailable ) as caught:
        v2_eval.load_mappable_commands( path=str( tmp_path / "gone.json" ) )
    message = str( caught.value )
    assert "gone.json" in message,                 "the error does not say WHICH file"
    assert "full corpus" in message,               "the error does not say what it refused to do"
    assert "comparable" in message,                "the error does not say why that would be wrong"


def test_malformed_json_raises( tmp_path ):
    bad = tmp_path / "bad.json"
    bad.write_text( "{ not json at all" )
    v2_eval = _v2_eval()
    with pytest.raises( v2_eval.EligibleCommandsUnavailable ):
        v2_eval.load_mappable_commands( path=str( bad ) )


@pytest.mark.parametrize( "payload,why", [
    ( {},                                  "no commands key at all" ),
    ( { "commands": [] },                  "an EMPTY list — the widest denominator of all" ),
    ( { "commands": "not-a-list" },        "a string, which would iterate character by character" ),
    ( { "commands": [ "ok", 7 ] },         "a non-string element" ),
    ( { "commands": None },                "an explicit null" ),
] )
def test_a_malformed_command_list_raises( tmp_path, payload, why ):
    """
    ⚠️ THE EMPTY LIST IS THE DANGEROUS ONE. `[]` is falsy, parses fine, and passes any check
    that only asks "did we get a list?" — and an empty eligible set means `compute_metrics`
    matches nothing, which does not read as an error, it reads as a score of zero.
    """
    path = tmp_path / "payload.json"
    path.write_text( json.dumps( payload ) )
    v2_eval = _v2_eval()
    with pytest.raises( v2_eval.EligibleCommandsUnavailable ):
        v2_eval.load_mappable_commands( path=str( path ) )


# ── the excision pin ─────────────────────────────────────────────────────────

def test_v2_eval_no_longer_reaches_into_v1_eval_arm_for_the_denominator():
    """
    The dependency this row exists to cut. Asserted on the source because the import was
    LAZY — inside the function — so nothing at import time would reveal it, which is exactly
    why it survived a first reading of the blast radius.

    ⚠️ AND IT ASKS ABOUT AN IMPORT, NOT A MENTION. The first version searched the whole file
    for the symbol name and was red on its own docstring — the one explaining that the import
    used to be there. A guard that cannot tell code from the comment describing it teaches
    people to delete the comment.
    """
    offenders = []
    for number, line in enumerate( open( V2_EVAL_PATH ), start=1 ):
        code = line.split( "#", 1 )[ 0 ]
        if "load_v1_class_to_command" in code and "import" in code:
            offenders.append( f"{number}: {line.strip()[ :90 ]}" )
    assert not offenders, \
        f"v2_eval still imports the v1 registry loader — deleting v1_eval_arm breaks every v2 eval: {offenders}"


# ── provenance: the freeze matches the live pinned registry, while it lasts ──

def test_the_frozen_list_still_matches_the_live_pinned_registry():
    """
    ⚠️ THIS TEST HAS A DELIBERATE EXPIRY. It re-derives the list from the pinned worktree and
    compares, which is the only thing that can prove the freeze was taken from the right tree.
    Once the worktree is removed (plan Step 4) it skips — and that is correct, not a hole: the
    artifact carries the sha, and the sha is what a future reader would re-derive from.

    Run BEFORE the deletion it guards, which is the whole reason §6.1 lands first.
    """
    worktree = os.path.join( os.path.dirname( PROJECT_ROOT ), f"lupin-v1-baseline-{PIN_SHA}" )
    if not os.path.isdir( worktree ):
        pytest.skip( f"the pinned worktree is gone ({worktree}) — provenance now rests on the stamped sha" )

    import subprocess
    probe = (
        "import sys, json; sys.path.insert( 0, 'src/scripts' );"
        "from v1_eval_arm import load_v1_class_to_command;"
        "print( json.dumps( sorted( set( load_v1_class_to_command()[ 0 ].values() ) ) ) )"
    )
    env  = dict( os.environ, LUPIN_ROOT=worktree, PYTHONPATH=os.path.join( PROJECT_ROOT, "src" ) )
    done = subprocess.run( [ os.path.join( PROJECT_ROOT, ".venv", "bin", "python" ), "-c", probe ],
                           cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300 )
    if done.returncode != 0:
        pytest.skip( f"the pinned registry no longer loads in this environment: {done.stderr[ -400: ]}" )

    live = json.loads( done.stdout.strip().splitlines()[ -1 ] )
    assert live == sorted( EXPECTED_COMMANDS ), \
        f"the frozen list and the pinned registry disagree — freeze taken from the wrong tree?\nlive: {live}"
