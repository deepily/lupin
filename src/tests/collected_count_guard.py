"""
Every test a file DECLARES must be a test pytest COLLECTS — row `282d4c19`.

THE SHAPE THIS CATCHES. On 2026-08-24 a test method in
`src/tests/unit/test_jstest_lane.py` landed OUTSIDE its class through a bad
append: present in the file, correctly indented, syntactically fine, and
collected by nothing. The suite stayed green. Nothing failed. The only signal
was the collected COUNT sitting at 15 where 16 was due — a number a human had to
be watching to notice, on a run nobody had a reason to look at twice.

That is vacuity shape 7: an assertion that is never reached is indistinguishable
from health. A method orphaned outside its class is the same defect wearing a
different hat — the assertion is not merely unreached, the whole test is.

WHY THIS IS NOT A HARDCODED COUNT. "Assert this file collects 16 tests" works,
and it costs a magic number that must be bumped on every addition — so it will
eventually be bumped WITHOUT anyone checking whether the new number is right,
which turns the guard into a rubber stamp. Comparing DECLARED against COLLECTED
needs no number and cannot drift: adding a test updates both sides at once, while
orphaning one updates only the first.

🔴 THE FIRST VERSION OF THIS GUARD DID NOT CATCH ITS OWN MOTIVATING DEFECT, and
that is worth writing down rather than quietly fixing. It excluded `test_*`
functions nested inside another function, reasoning that pytest never collects
them so they cannot be orphans. But a method dedented out of its class does not
land at module level — it lands INSIDE THE PRECEDING FUNCTION. The real defect
IS a nested function, so the exclusion written to reduce noise removed exactly
the case the guard existed for. It passed its own falsifier by not looking.

⇒ A nested `test_*` is now REPORTED, not excused. A genuine test factory with an
inner `test_*` helper is rare; a dedent accident is not. Rename a deliberate
inner helper to `_test_*` and this stops flagging it.

WHAT IT STILL DOES NOT FLAG:
  · names not beginning `test_`;
  · files whose collection pytest ITSELF limited (`-k`, `--last-failed`, an
    explicit node id). Under a filtered run this SKIPS rather than fails,
    because "you asked for a subset" is not a defect, and a guard that cries
    wolf on `-k` is a guard someone deletes.

USAGE — one test per suite file that matters:

    from tests.collected_count_guard import assert_every_declared_test_is_collected

    def test_every_test_in_this_file_is_actually_collected( request ):
        assert_every_declared_test_is_collected( request, __file__ )
"""
import ast
import os
from pathlib import Path

import pytest


def declared_test_names( path ):
    """
    Every test function name the FILE declares, as pytest would name it.

    Requires:
        - path names a readable Python file

    Ensures:
        - returns a set of bare function names beginning "test_"
        - includes methods of classes, module-level functions, AND functions
          nested inside another function — a nested one is the dedent-accident
          shape this guard exists for, not an exemption
        - EXCLUDES names not beginning "test_"
    """
    tree  = ast.parse( Path( path ).read_text( encoding="utf-8" ) )
    names = set()

    for node in ast.walk( tree ):
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ):
            if node.name.startswith( "test_" ):
                names.add( node.name )
    return names


def collected_test_names( request, path ):
    """
    The bare function names pytest actually collected FROM THIS FILE.

    Ensures:
        - parametrisation suffixes are stripped ("test_x[case]" -> "test_x")
        - items from other files are ignored
    """
    target = os.path.realpath( path )
    names  = set()
    for item in request.session.items:
        item_path = getattr( item, "path", None ) or getattr( item, "fspath", None )
        if item_path is None:
            continue
        if os.path.realpath( str( item_path ) ) != target:
            continue
        names.add( item.name.split( "[" )[ 0 ] )
    return names


def assert_every_declared_test_is_collected( request, path ):
    """
    Fail if the file declares a test pytest did not collect.

    Requires:
        - request is the pytest `request` fixture
        - path is the calling test file's __file__

    Ensures:
        - SKIPS when the session was filtered (-k / --last-failed), because a
          deliberate subset is not a defect
        - otherwise raises AssertionError naming every orphaned test
    """
    config = request.config
    if config.getoption( "-k", default="" ) or config.getoption( "--last-failed", default=False ):
        pytest.skip( "session is filtered (-k/--last-failed); a deliberate subset is not a defect" )

    declared  = declared_test_names( path )
    collected = collected_test_names( request, path )
    orphaned  = declared - collected

    assert not orphaned, (
        "🔴 THIS FILE DECLARES TESTS PYTEST DID NOT COLLECT — they run NOWHERE, and the "
        "suite is green BECAUSE of it (row 282d4c19).\n"
        "  orphaned : %s\n"
        "  declared : %d\n"
        "  collected: %d\n"
        "Most likely a method sitting outside its class, or a class pytest does not collect."
        % ( sorted( orphaned ), len( declared ), len( collected ) )
    )
