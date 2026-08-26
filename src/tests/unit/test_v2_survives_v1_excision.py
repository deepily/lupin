"""
Row `e2099400` §2 Step 2 — v2 must stand up with the v1 apparatus absent.

WHY THIS FILE, AND NOT JUST THE THREE FIXES. The excision plan listed the files to delete,
and that list was assembled by asking *what is v1 apparatus*. Three dependencies were missed,
all found the other way round — by asking *what does v2 still take FROM it*:

  1. `v2_eval.load_mappable_commands` -> `v1_eval_arm.load_v1_class_to_command`  (María, §6.1)
     Lazy, inside a function, on EVERY v2 run; its failure path returned None, which scores
     routing over the full corpus and only whispers on stdout.
  2. `v2_eval` -> `paired_eval.make_provenance`                                  (found here)
     MODULE-LEVEL. Not a degradation — every v2 eval would have died at import.
  3. `eval_isolation_guard` -> `v1_eval_arm.V1_PIN_SHA`                          (found here)
     A keeper importing a constant back out of the delete list.

Two of the three were invisible to a grep for "v1" in v2's own file: one was lazy, one was in
a different keeper entirely. ⇒ **A delete list built by naming files is not the same as one
built by following imports**, and the only thing that settles it is running the import with
the files gone. That is what this does, and it keeps doing it after Step 3 — so a future edge
back into a deleted module fails here rather than at the next eval.

⚠️ IT BLOCKS THE IMPORT RATHER THAN MOVING THE FILES. Renaming files mid-suite would leave the
tree broken if the test died between the move and the restore, and a peer session shares this
tree. A meta-path finder that refuses the two module names reproduces the post-deletion world
exactly, in a child process, touching nothing.

Venue: :7999-eligible. One short child interpreter; no server, no state mutation, no network.
"""

import json
import os
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
SCRIPTS      = os.path.join( PROJECT_ROOT, "src", "scripts" )
FROZEN_PATH  = os.path.join( PROJECT_ROOT, "src", "conf", "v1-eligible-routing-commands.json" )

# Everything the V1 excision deletes that another module might still import.
DELETED_MODULES = [ "v1_eval_arm", "paired_eval", "pair_warm_spans" ]

# What has to keep working with those gone.
SURVIVORS = [ "v2_eval", "eval_isolation_guard", "ws_job_listener", "eval_provenance" ]


_PROBE = """
import sys

BLOCKED = {blocked!r}

class _Refuse:
    def find_module( self, name, path=None ):
        return self if name in BLOCKED else None
    def find_spec( self, name, path=None, target=None ):
        if name in BLOCKED:
            raise ImportError( "BLOCKED-BY-TEST: " + name )
        return None

sys.meta_path.insert( 0, _Refuse() )
sys.path.insert( 0, {scripts!r} )

import importlib
for module in {survivors!r}:
    importlib.import_module( module )
print( "SURVIVED" )
"""


def _run_probe( blocked, survivors ):
    code = _PROBE.format( blocked=set( blocked ), scripts=SCRIPTS, survivors=survivors )
    env  = dict( os.environ, LUPIN_ROOT=PROJECT_ROOT,
                 PYTHONPATH=os.path.join( PROJECT_ROOT, "src" ) )
    return subprocess.run( [ os.path.join( PROJECT_ROOT, ".venv", "bin", "python" ), "-c", code ],
                           cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300 )


def test_v2_and_its_keepers_import_with_the_v1_apparatus_gone():
    """
    THE PROPERTY THE WHOLE EXCISION RESTS ON. If this is green, Step 3 can delete those files
    without taking v2 down; if it is red, the message names the module that still reaches.
    """
    done = _run_probe( DELETED_MODULES, SURVIVORS )
    assert "SURVIVED" in done.stdout, (
        "v2 does not stand without the v1 apparatus — something still imports a module the "
        f"excision deletes:\n--- stderr ---\n{done.stderr[ -3000: ]}" )


def test_the_probe_itself_can_fail():
    """
    ⚠️ THE NEGATIVE CONTROL, AND THIS FILE IS USELESS WITHOUT IT. A blocker that silently
    blocks nothing would make the test above green forever and prove exactly nothing. Ask it
    to import a module that IS blocked and require the failure.
    """
    done = _run_probe( DELETED_MODULES, [ "v1_eval_arm" ] )
    assert "SURVIVED" not in done.stdout, "the import blocker did not block anything"
    assert "BLOCKED-BY-TEST" in done.stderr, f"blocked for the wrong reason:\n{done.stderr[ -1500: ]}"


@pytest.mark.parametrize( "survivor", SURVIVORS )
def test_each_survivor_individually_stands_alone( survivor ):
    """One at a time, so a red names the module rather than the set."""
    done = _run_probe( DELETED_MODULES, [ survivor ] )
    assert "SURVIVED" in done.stdout, \
        f"{survivor} still needs the v1 apparatus:\n--- stderr ---\n{done.stderr[ -2000: ]}"


def test_the_frozen_pin_and_the_guards_pin_are_the_same_sha():
    """
    ⚠️ TWO PLACES NOW NAME THE PIN — the frozen routing denominator and the isolation guard —
    because the constant had to leave the file being deleted. Two sources of truth that
    nothing compares is how they drift. This is the comparison.
    """
    import sys
    if SCRIPTS not in sys.path: sys.path.insert( 0, SCRIPTS )
    import eval_isolation_guard

    with open( FROZEN_PATH ) as handle:
        frozen = json.load( handle )
    assert frozen[ "pin_sha" ] == eval_isolation_guard.V1_PIN_SHA, (
        f"the frozen denominator says pin {frozen[ 'pin_sha' ]} and the isolation guard says "
        f"{eval_isolation_guard.V1_PIN_SHA} — one of them is scoring against the wrong tree" )
