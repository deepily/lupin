"""
Every visual test that snapshots a persona popover paints that popover's
`::backdrop` solid first.

WHY THIS FILE EXISTS: the popover's rounded corner is transparent, so a capture's
corner pixels are its shadow blended over whatever page sits behind it, and that
page moves between runs. Row 856c7c96 fixed it for the borrowed popover (Rio ⚡,
d9279d9c); the open popover beside it was left bare and was reported failing 5 px
in the same corner (Mr. Radio 🦉, 2026-09-18). The fix was applied one test at a
time, and one test was missed, so the fix is now checked here.

THE POPULATION is every test function under `src/tests/e2e_ui/` that hands a
`#persona-popover-*` locator to an `assert_snapshot*` fixture. It is read from
the code, not from a list, and its size is asserted before anything else, so a
walk that finds nothing reads as red rather than green.

WHAT THIS FILE DOES NOT ASSERT: that `#fff` is the right colour, or that the
backdrop is painted before the capture rather than after. It checks that the
style rule is present in the same function as the capture.
"""

import ast
import subprocess

import cosa.utils.util as cu


E2E_DIR         = "src/tests/e2e_ui"
POPOVER_PREFIX  = "#persona-popover"

# Measured 2026-09-18: two captures, popover_open and popover_borrowed, both in
# test_multiplexer_phase6c_section_a_visual.py. A floor, not an equality, so a
# new popover capture joins the population without editing this file.
MIN_CAPTURES    = 2


def _e2e_files():
    """
    List the git-tracked Python files under the E2E directory.

    Requires:
        - the project root is a git checkout

    Ensures:
        - returns repo-relative paths, one per tracked .py file
    """
    out = subprocess.run(
        [ "git", "ls-files", "--", f"{E2E_DIR}/*.py" ],
        cwd=cu.get_project_root(), capture_output=True, text=True, check=True,
    )
    return [ line for line in out.stdout.splitlines() if line ]


def _string_args( call ):
    """
    Return the constant string positional and keyword arguments of a call.

    Requires:
        - call is an ast.Call

    Ensures:
        - returns a list of str, possibly empty
    """
    values = [ a.value for a in call.args if isinstance( a, ast.Constant ) and isinstance( a.value, str ) ]
    values += [ k.value.value for k in call.keywords
                if isinstance( k.value, ast.Constant ) and isinstance( k.value.value, str ) ]
    return values


def _popover_captures( source ):
    """
    Find each test function that snapshots a persona popover.

    Requires:
        - source is the text of a Python module

    Ensures:
        - returns ( function name, popover selector, style tag contents ) per capture,
          where style tag contents are every string passed to add_style_tag in that function
    """
    captures = []
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, ast.FunctionDef ): continue

        calls       = [ c for c in ast.walk( node ) if isinstance( c, ast.Call ) and isinstance( c.func, ( ast.Attribute, ast.Name ) ) ]
        name_of     = lambda c: c.func.attr if isinstance( c.func, ast.Attribute ) else c.func.id
        snapshots   = any( name_of( c ).startswith( "assert_snapshot" ) for c in calls )
        styles      = [ s for c in calls if name_of( c ) == "add_style_tag" for s in _string_args( c ) ]
        selectors   = { s for c in calls if name_of( c ) == "locator" for s in _string_args( c ) if s.startswith( POPOVER_PREFIX ) }

        if snapshots:
            captures += [ ( node.name, sel, styles ) for sel in sorted( selectors ) ]
    return captures


def _all_captures():
    root = cu.get_project_root()
    found = []
    for rel in _e2e_files():
        with open( f"{root}/{rel}", encoding="utf-8" ) as f:
            found += [ ( rel, *cap ) for cap in _popover_captures( f.read() ) ]
    return found


def test_the_walk_finds_the_popover_captures():
    """The population is non-empty before any assertion ranges over it."""
    captures = _all_captures()
    assert len( captures ) >= MIN_CAPTURES, f"expected at least {MIN_CAPTURES} popover captures, found {captures}"


def test_every_popover_capture_paints_its_backdrop_solid():
    """Each captured popover has a `<selector>::backdrop` style rule in the same test."""
    bare = [ f"{rel}::{fn} ({sel})" for rel, fn, sel, styles in _all_captures()
             if not any( f"{sel}::backdrop" in s for s in styles ) ]
    assert not bare, "popover captured over a transparent corner, no solid ::backdrop: " + ", ".join( bare )


def test_the_recogniser_flags_a_bare_capture():
    """Positive control: a capture with no backdrop rule is found and reported bare."""
    source = (
        "def test_x( page, assert_snapshot ):\n"
        "    popover = page.locator( '#persona-popover-demo' )\n"
        "    assert_snapshot( popover, name='x.png' )\n"
    )
    assert _popover_captures( source ) == [ ( "test_x", "#persona-popover-demo", [] ) ]


def test_the_recogniser_ignores_a_popover_it_does_not_capture():
    """A popover located but never snapshotted is not in the population."""
    source = (
        "def test_y( page ):\n"
        "    page.locator( '#persona-popover-demo' ).click()\n"
    )
    assert _popover_captures( source ) == []
