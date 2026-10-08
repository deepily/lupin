"""
The park-expiry integration test still hands its timing to check_park_silence.

The integration test needs the test server, so the unit tier cannot run it. This reads its
source instead and checks the wiring. The clock starts before the park. The count feeds the
helper, along with the elapsed time and the window.
"""

import ast

import pytest

from cosa.utils import util as cu

TEST_PATH = "/src/tests/integration/test_parked_status_ac6_live.py"
TEST_NAME = "test_park_expires_by_the_passage_of_time_alone"


def _calls_to( node, name ):
    """Every call in node whose callee is the bare name or the attribute `name`."""
    found = []
    for n in ast.walk( node ):
        if isinstance( n, ast.Call ):
            f = n.func
            if ( isinstance( f, ast.Name ) and f.id == name ) or ( isinstance( f, ast.Attribute ) and f.attr == name ):
                found.append( n )
    return found


@pytest.fixture( scope="module" )
def park_test():
    tree = ast.parse( open( cu.get_project_root() + TEST_PATH ).read() )
    hits = [ n for n in ast.walk( tree ) if isinstance( n, ast.FunctionDef ) and n.name == TEST_NAME ]
    assert len( hits ) == 1, f"expected exactly one {TEST_NAME}, found {len( hits )}"
    return hits[ 0 ]


def test_the_test_calls_the_helper_exactly_once( park_test ):
    assert len( _calls_to( park_test, "check_park_silence" ) ) == 1


def test_the_helper_is_given_the_count_the_elapsed_time_and_the_window( park_test ):
    call = _calls_to( park_test, "check_park_silence" )[ 0 ]
    assert len( call.args ) == 3
    count, elapsed, window = call.args
    assert isinstance( count, ast.Name ) and count.id == "during"
    assert isinstance( window, ast.Name ) and window.id == "EXPIRY_WINDOW_SECONDS"
    assert isinstance( elapsed, ast.BinOp ) and isinstance( elapsed.op, ast.Sub )
    assert _calls_to( elapsed.left, "monotonic" ), "elapsed must be a monotonic reading minus the start"
    assert isinstance( elapsed.right, ast.Name )


def test_the_start_is_a_monotonic_reading_taken_before_the_park( park_test ):
    call    = _calls_to( park_test, "check_park_silence" )[ 0 ]
    start   = call.args[ 1 ].right.id
    parks   = _calls_to( park_test, "_park" )
    assigns = [ n for n in ast.walk( park_test )
                if isinstance( n, ast.Assign ) and any( isinstance( t, ast.Name ) and t.id == start for t in n.targets )
                and _calls_to( n.value, "monotonic" ) ]
    assert len( assigns ) == 1, f"{start} must be set from time.monotonic() exactly once"
    assert len( parks ) == 1
    assert assigns[ 0 ].lineno < parks[ 0 ].lineno


def test_the_helper_runs_after_the_count_it_judges( park_test ):
    call   = _calls_to( park_test, "check_park_silence" )[ 0 ]
    counts = [ n for n in ast.walk( park_test )
               if isinstance( n, ast.Assign ) and any( isinstance( t, ast.Name ) and t.id == "during" for t in n.targets )
               and _calls_to( n.value, "_owed_count" ) ]
    assert len( counts ) == 1
    assert counts[ 0 ].lineno < call.lineno
