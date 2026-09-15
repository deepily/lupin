"""
THE TWO PLEDGE READS IN `TaskRepository` — Sword of Damocles, row ab8c5728.

`find_pending_admit_pledging` decides whether a pledge is already spent, and
`peek_request_deletion_id` decides which second row the verdict door locks. Both are
queries, so a fake that ignored the filters would pass whatever the code asked for.

This fake APPLIES what it is given: each `filter( <column> <op> <value> )` is evaluated
against in-memory rows, so a query missing a filter, or filtering the wrong column, returns
the wrong rows and the arm fails.
"""
import operator
import os
import sys
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.task_repository import TaskRepository


class _ApplyingQuery:
    """Evaluates SQLAlchemy binary expressions (==, !=) against rows; projects the asked-for columns."""
    def __init__( self, rows, columns, filters=None ):
        self._rows    = rows
        self._columns = columns
        self.filters  = filters if filters is not None else [ ]

    def filter( self, expr ):
        assert expr.operator in ( operator.eq, operator.ne ), f"unsupported operator {expr.operator}"
        self.filters.append( ( expr.left.key, expr.operator.__name__ ) )
        kept = [ r for r in self._rows if expr.operator( getattr( r, expr.left.key ), expr.right.value ) ]
        return _ApplyingQuery( kept, self._columns, self.filters )

    def first( self ):
        if not self._rows: return None
        return tuple( getattr( self._rows[ 0 ], c ) for c in self._columns )


def _repo( rows ):
    session = MagicMock()
    queries = [ ]
    def _query( *columns ):
        q = _ApplyingQuery( rows, [ c.key for c in columns ] )
        queries.append( q )
        return q
    session.query.side_effect = _query
    return TaskRepository( session ), queries


def _row( **fields ):
    base = dict( id=uuid.uuid4(), request_deletion_id=None, request_state=None, request_move=None )
    base.update( fields )
    return SimpleNamespace( **base )


# ---------------------------------------------------------------------------
# find_pending_admit_pledging
# ---------------------------------------------------------------------------

def test_it_finds_the_other_row_whose_pending_admit_pledges_this_ticket():
    pledge   = uuid.uuid4()
    spender  = _row( request_deletion_id=pledge, request_state="pending", request_move="admit" )
    repo, qs = _repo( [ _row(), spender ] )

    assert repo.find_pending_admit_pledging( pledge, uuid.uuid4() ) == spender.id
    assert qs[ 0 ].filters == [
        ( "request_deletion_id", "eq" ), ( "request_state", "eq" ), ( "request_move", "eq" ), ( "id", "ne" ),
    ]


def test_an_ANSWERED_request_does_not_hold_the_pledge():
    pledge  = uuid.uuid4()
    repo, _ = _repo( [ _row( request_deletion_id=pledge, request_state="denied", request_move="admit" ) ] )

    assert repo.find_pending_admit_pledging( pledge, uuid.uuid4() ) is None


def test_the_row_being_filed_on_is_excluded():
    """A re-file over its own stranded request must not count against itself."""
    pledge  = uuid.uuid4()
    own     = _row( request_deletion_id=pledge, request_state="pending", request_move="admit" )
    repo, _ = _repo( [ own ] )

    assert repo.find_pending_admit_pledging( pledge, own.id ) is None


def test_a_different_pledge_does_not_match():
    repo, _ = _repo( [ _row( request_deletion_id=uuid.uuid4(), request_state="pending", request_move="admit" ) ] )

    assert repo.find_pending_admit_pledging( uuid.uuid4(), uuid.uuid4() ) is None


# ---------------------------------------------------------------------------
# peek_request_deletion_id
# ---------------------------------------------------------------------------

def test_peek_returns_the_stored_pledge_of_the_named_row():
    pledge  = uuid.uuid4()
    target  = _row( request_deletion_id=pledge )
    repo, _ = _repo( [ _row( request_deletion_id=uuid.uuid4() ), target ] )

    assert repo.peek_request_deletion_id( target.id ) == pledge


def test_peek_returns_None_for_a_row_without_a_pledge_and_for_a_missing_row():
    target  = _row()
    repo, _ = _repo( [ target ] )

    assert repo.peek_request_deletion_id( target.id ) is None
    assert repo.peek_request_deletion_id( uuid.uuid4() ) is None
