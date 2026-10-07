"""
Every integration test that waits on the done queue carries the strict drain mark.

Inside a monopolize run the suite job holds the slot.
A job from a user the door does not tie to the suite waits until the suite ends.
A test waiting for that job fails with a timeout.
The mark turns that into an expected failure. Because it is strict, the run goes red when the
drain becomes observable again, and the mark cannot outlive its cause.

Venue: :7999 (unit, reads the test file's syntax tree, no server).
"""

import ast
import os

import pytest

PATH = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "tests", "integration", "test_job_queue_progressive_disclosure.py" )
MARK = "NEEDS_A_DRAINED_QUEUE"


def _tree():
    with open( PATH, encoding="utf-8" ) as handle: return ast.parse( handle.read() )


def _tests_and_waiters():
    """Each test method with whether it waits on the done queue, and its decorator names."""
    found = [ ]
    for node in ast.walk( _tree() ):
        if isinstance( node, ast.FunctionDef ) and node.name.startswith( "test_" ):
            waits = any( isinstance( n, ast.Attribute ) and n.attr == "_wait_for_jobs_in_done_queue" for n in ast.walk( node ) )
            marks = [ d.id for d in node.decorator_list if isinstance( d, ast.Name ) ]
            found.append( ( node.name, waits, marks ) )
    return found


def test_the_file_has_tests_and_four_of_them_wait_on_the_done_queue():
    found = _tests_and_waiters()
    assert len( found ) >= 9
    assert sorted( name for name, waits, _ in found if waits ) == [
        "test_done_queue_metadata_includes_session_fields",
        "test_job_interactions_endpoint",
        "test_job_interactions_unauthorized_access",
        "test_job_transitions_todo_to_done",
    ]


def test_every_test_that_waits_on_the_done_queue_carries_the_mark():
    unmarked = [ name for name, waits, marks in _tests_and_waiters() if waits and MARK not in marks ]
    assert unmarked == [ ], f"waits on the done queue without the drain mark: {unmarked}"


def test_no_test_that_does_not_wait_carries_the_mark():
    stray = [ name for name, waits, marks in _tests_and_waiters() if not waits and MARK in marks ]
    assert stray == [ ], f"marked but never waits on the done queue: {stray}"


def test_the_mark_is_a_strict_xfail_that_names_its_row():
    marks = [ n for n in ast.walk( _tree() ) if isinstance( n, ast.Assign )
              and any( isinstance( t, ast.Name ) and t.id == MARK for t in n.targets ) ]
    assert len( marks ) == 1
    call = marks[ 0 ].value
    assert isinstance( call, ast.Call ) and ast.unparse( call.func ) == "pytest.mark.xfail"
    keywords = { k.arg: k.value for k in call.keywords }
    assert isinstance( keywords[ "strict" ], ast.Constant ) and keywords[ "strict" ].value is True
    assert "ce29cd20" in ast.unparse( keywords[ "reason" ] )
