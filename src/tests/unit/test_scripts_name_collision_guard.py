"""
The control for row c89cec9b: a `src/scripts` name shadowing an importable top-level name.

WHY THIS FILE EXISTS. Every test that covers a `src/scripts` module puts that directory on
`sys.path` and imports the module by bare name — that is what the coverage frame needs, and
Tiberius's files, Maya's and mine all do it. From the moment any of them is collected, the
directory is on the path for the WHOLE pytest process, ahead of everything else. So any other
module in the run that does a bare `import <name>` can get the `src/scripts` file instead of
the one it meant, and the symptom would surface a long way from the cause.

WHAT THIS FILE IS: item 1 of that row — the control that reddens when the collision set
GROWS, so the safety we have today stops being a coincidence of naming and becomes something
enforced. Item 2 of the row (whether `src/scripts` should get `__init__.py` files, which would
close this and the coverage-frame omission together) is a ruling for Rick, not a thing a test
decides.

🔴 THE MEASURED STATE, WHICH IS NOT "ALL CLEAR".

  58 top-level .py modules in src/scripts  ->  0 collisions against src/, the stdlib, or
                                               the installed site-packages. Genuinely clean.

  8 subdirectories                          ->  ONE collision: `conf`.
                                               src/scripts/conf/ vs src/conf/

Neither directory has an `__init__.py`, so both are NAMESPACE packages — which are importable
anyway, and that is what makes this real rather than theoretical. PROVEN BY EXECUTION, not by
reading the import rules:

    with only src on the path    conf.__path__ = [ .../src/conf, ... ]
    with src/scripts at index 0  conf.__path__ = [ .../src/scripts/conf, .../src/conf, ... ]

src/scripts/conf wins. It is LATENT today only because nothing in the tree imports `conf` as
a module — verified by grep for `import conf` and `from conf import` across src/, which finds
nothing. It is DECLARED below rather than hidden behind an exclusion, and a second test
asserts the reason it is harmless is still true.
"""

import os
import subprocess
import sys

import cosa.utils.util as cu
import pytest


SCRIPTS_DIR = os.path.join( cu.get_project_root(), "src", "scripts" )
SRC_DIR     = os.path.join( cu.get_project_root(), "src" )

# name -> the measured reason it is currently harmless. A declaration, never a silencer:
# the entry states what was checked, and `test_no_declared_collision_has_gone_stale` fails
# if the name stops colliding, so the list cannot rot into folklore.
DECLARED_DIRECTORY_COLLISIONS = {
    "conf": (
        "src/scripts/conf/ vs src/conf/ — both are namespace packages (neither has "
        "__init__.py), and putting src/scripts on the path ahead of src makes the former "
        "win. Harmless only because nothing in the tree imports `conf` as a module, which "
        "test_the_declared_conf_collision_is_still_unreachable checks rather than assumes."
    ),
}


def _top_level_names( directory ):
    """Every name a bare `import` could resolve to if `directory` were on sys.path."""
    names = set()
    if not os.path.isdir( directory ):
        return names
    for entry in os.listdir( directory ):
        full = os.path.join( directory, entry )
        if entry == "__pycache__":
            continue
        if entry.endswith( ".py" ):
            names.add( entry[ : -3 ] )
        elif os.path.isdir( full ) and not entry.endswith( ( ".dist-info", ".egg-info" ) ):
            names.add( entry )
    return names


def _script_modules():
    """The .py files directly in src/scripts — the ones a bare import reaches."""
    return { e[ : -3 ] for e in os.listdir( SCRIPTS_DIR ) if e.endswith( ".py" ) }


def _script_directories():
    """Subdirectories of src/scripts. Importable as namespace packages, __init__.py or not."""
    return {
        e for e in os.listdir( SCRIPTS_DIR )
        if os.path.isdir( os.path.join( SCRIPTS_DIR, e ) ) and e != "__pycache__"
    }


def _site_packages():
    for path in sys.path:
        if path.endswith( "site-packages" ) and os.path.isdir( path ):
            return _top_level_names( path )
    return set()


def _importable_pools():
    """The three places a bare import could otherwise have landed."""
    return {
        "src/ top-level"  : _top_level_names( SRC_DIR ),
        "the stdlib"      : set( sys.stdlib_module_names ),
        "site-packages"   : _site_packages(),
    }


def _collisions( names ):
    """{ name: [pool, ...] } for every name that exists in at least one pool."""
    found = {}
    for label, pool in _importable_pools().items():
        for name in sorted( names & pool ):
            found.setdefault( name, [] ).append( label )
    return found


# ── the guard ────────────────────────────────────────────────────────────────────

def test_no_script_module_shadows_an_importable_top_level_name():
    """
    The dangerous case: a real module shadowing a real module. Currently zero, and this is
    what must stay zero — adding src/scripts/config.py, types.py or queue.py would silently
    redirect a bare import somewhere else in the tier.
    """
    collisions = _collisions( _script_modules() )
    assert collisions == {}, (
        "a src/scripts module now shadows an importable top-level name: "
        + "; ".join( f"{n} (also in {', '.join( p )})" for n, p in sorted( collisions.items() ) )
        + " — see row c89cec9b"
    )


def test_no_undeclared_script_directory_shadows_an_importable_top_level_name():
    """
    Subdirectories shadow too: with no __init__.py they are still importable as namespace
    packages. Known instances are DECLARED above with their measured reason, so a NEW one
    reddens here rather than joining an unread list.
    """
    collisions  = _collisions( _script_directories() )
    undeclared  = { n: p for n, p in collisions.items() if n not in DECLARED_DIRECTORY_COLLISIONS }
    assert undeclared == {}, (
        "a src/scripts subdirectory now shadows an importable top-level name: "
        + "; ".join( f"{n} (also in {', '.join( p )})" for n, p in sorted( undeclared.items() ) )
        + " — declare it with a measured reason or rename it; see row c89cec9b"
    )


def test_no_declared_collision_has_gone_stale():
    """
    A declaration that no longer describes anything is folklore. If `conf` is renamed or
    removed, this fails and the entry must go — the list cannot outlive its subject.
    """
    still_colliding = set( _collisions( _script_directories() ) )
    stale = set( DECLARED_DIRECTORY_COLLISIONS ) - still_colliding
    assert stale == set(), f"declared collisions that no longer exist: {sorted( stale )}"


def test_the_declared_conf_collision_is_still_unreachable():
    """
    The declaration says `conf` is harmless BECAUSE nothing imports it. That reason is
    checked here rather than trusted: the day a module does `import conf`, the shadowing
    stops being latent and this reddens.
    """
    result = subprocess.run(
        [ "grep", "-rInE", r"^[[:space:]]*(import conf([[:space:]]|$|\.)|from conf[[:space:].])",
          "--include=*.py", SRC_DIR ],
        capture_output=True, text=True
    )
    assert result.stdout == "", (
        "something now imports `conf` as a module, so the src/scripts/conf shadowing is no "
        f"longer latent:\n{result.stdout}"
    )


# ── the detector's own positive control ──────────────────────────────────────────

def test_the_detector_actually_fires_on_a_collision():
    """
    An all-clear and a broken detector look identical. This feeds it a name that certainly
    exists in a pool and asserts it is reported — so the zero above is a measurement.
    """
    collisions = _collisions( { "json" } )
    assert "json" in collisions
    assert "the stdlib" in collisions[ "json" ]


def test_the_detector_stays_silent_on_a_name_that_exists_nowhere():
    """The paired negative: proof the predicate is not simply always true."""
    assert _collisions( { "definitely-not-a-module-anywhere-xyzzy" } ) == {}


def test_the_pools_are_populated_so_an_empty_result_means_something():
    """
    Every pool must be non-empty. A pool that silently failed to enumerate would make the
    guard pass by seeing nothing — the exact defect family row c89cec9b came out of.
    """
    pools = _importable_pools()
    for label, pool in pools.items():
        assert len( pool ) > 0, f"pool '{label}' is empty — the guard would pass by blindness"
    assert len( _script_modules() ) > 0
    assert len( _script_directories() ) > 0
