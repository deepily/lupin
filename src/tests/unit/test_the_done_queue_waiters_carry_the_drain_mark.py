"""
Every done-queue waiter in the integration file carries a strict xfail that names its row.

One waiter, test_job_interactions_endpoint, is repaired by the suite token and carries none.

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
MARKS = { "NEEDS_A_DRAINED_QUEUE": "ce29cd20" }
UNMARKED_WAITERS = [ "test_job_interactions_endpoint" ]


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
    unmarked = sorted( name for name, waits, marks in _tests_and_waiters() if waits and not set( marks ) & set( MARKS ) )
    assert unmarked == UNMARKED_WAITERS, f"waits on the done queue without the drain mark: {unmarked}"


def test_no_test_that_does_not_wait_carries_the_mark():
    stray = [ name for name, waits, marks in _tests_and_waiters() if not waits and set( marks ) & set( MARKS ) ]
    assert stray == [ ], f"marked but never waits on the done queue: {stray}"


@pytest.mark.parametrize( "mark, row", sorted( MARKS.items() ) )
def test_each_mark_is_a_strict_xfail_that_names_its_row( mark, row ):
    marks = [ n for n in ast.walk( _tree() ) if isinstance( n, ast.Assign )
              and any( isinstance( t, ast.Name ) and t.id == mark for t in n.targets ) ]
    assert len( marks ) == 1
    call = marks[ 0 ].value
    assert isinstance( call, ast.Call ) and ast.unparse( call.func ) == "pytest.mark.xfail"
    keywords = { k.arg: k.value for k in call.keywords }
    assert isinstance( keywords[ "strict" ], ast.Constant ) and keywords[ "strict" ].value is True
    assert row in ast.unparse( keywords[ "reason" ] )


def test_the_repaired_waiter_is_unmarked_and_the_drain_mark_is_on_the_other_three():
    by_name = { name: marks for name, waits, marks in _tests_and_waiters() if waits }
    assert by_name[ "test_job_interactions_endpoint" ] == [ ]
    others = sorted( name for name, marks in by_name.items() if marks == [ "NEEDS_A_DRAINED_QUEUE" ] )
    assert others == [ "test_done_queue_metadata_includes_session_fields", "test_job_interactions_unauthorized_access",
                       "test_job_transitions_todo_to_done" ]


def test_the_lineage_stop_gap_mark_is_gone_from_the_file():
    names = { n.id for n in ast.walk( _tree() ) if isinstance( n, ast.Name ) }
    targets = { t.id for n in ast.walk( _tree() ) if isinstance( n, ast.Assign ) for t in n.targets if isinstance( t, ast.Name ) }
    assert "NEEDS_THE_LINEAGE_REPAIR" not in names | targets
