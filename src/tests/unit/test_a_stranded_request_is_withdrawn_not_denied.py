"""
A PENDING REQUEST THE ROW CAN NO LONGER ANSWER IS WITHDRAWN — row c9fafb9d, design §7.

Mr. Radio's D2, 2026-09-10: any transition that makes a pending request's move impossible
clears the request, with a `request_withdrawn` event. It is not a denial (R5 is about Rick's
"no") and not an approval, so it writes neither state.

Driven through the REAL `TaskRepository.apply_transition` over a recording session, because
that method is the one place every status change in the store passes through.
"""
import os
import sys
import uuid
from datetime import datetime, timezone

import pytest

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_request_lifecycle as lifecycle
from cosa.rest import task_store_rules as rules
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.postgres_models import TaskItem

NOW   = datetime( 2026, 9, 10, 0, 0, tzinfo=timezone.utc )
ACTOR = "rick host"

PENDING  = lifecycle.REQUEST_PENDING
HOLDING  = approval.NOT_APPROVED_STATUS
ADMIT    = approval.MOVE_ADMIT
DEMOTE   = approval.MOVE_DEMOTE


class _RecordingSession:
    def __init__( self ):  self.added = [ ]
    def add( self, obj ):  self.added.append( obj )
    def flush( self ):     pass


def _item( status, request_state=None, request_move=None ):
    return TaskItem(
        id = uuid.uuid4(), item_class = "task", title = "a row", body = None, project = "lupin",
        owner_persona = "pocholo", accountable_manager = "mr radio", created_by = "mr radio d54262de",
        status = status, priority = "P2", urgency = "normal", created_ts = NOW, updated_ts = NOW,
        request_state = request_state, request_move = request_move,
        request_ts = NOW if request_state else None,
    )


def _transition( item, to_status ):
    session = _RecordingSession()
    event   = TaskRepository( session ).apply_transition(
        item = item, to_status = to_status, actor = ACTOR, authority = "user_direct",
        reason = "driving the real transition write",
    )
    return session, event


# ( label, from, request_state, request_move, to, withdrawn )
CASES = [
    ( "Rick admits directly over a pending admit",    HOLDING,  PENDING,                     ADMIT,  "queued",       True  ),
    ( "a pending admit's row is closed",              HOLDING,  PENDING,                     ADMIT,  "done",         True  ),
    ( "a pending demote's row is demoted directly",   "queued", PENDING,                     DEMOTE, HOLDING,        True  ),
    ( "a pending demote's row is dropped",            "queued", PENDING,                     DEMOTE, "dropped",      True  ),
    ( "a pending demote's row is started — still live", "queued", PENDING,                   DEMOTE, "in_progress",  False ),
    ( "a pending demote's row is blocked — still live", "queued", PENDING,                   DEMOTE, "blocked",      False ),
    ( "a DENIED admit's row is admitted",             HOLDING,  lifecycle.REQUEST_DENIED,    ADMIT,  "queued",       False ),
    ( "an APPROVED demote's row moves on",            "queued", lifecycle.REQUEST_APPROVED,  DEMOTE, HOLDING,        False ),
    ( "a row with no request moves",                  HOLDING,  None,                        None,   "queued",       False ),
]


@pytest.mark.parametrize( "label,frm,state,move,to,withdrawn", CASES, ids=[ c[ 0 ] for c in CASES ] )
def test_a_move_withdraws_exactly_the_requests_it_strands( label, frm, state, move, to, withdrawn ):
    """
    🔴 BOTH DIRECTIONS IN ONE TABLE. A withdrawal that fired on every move would erase
    Rick's verdicts and live requests alike; one that never fired would leave the badge
    counting questions with no subject. The table carries both, so neither passes.
    """
    item          = _item( frm, state, move )
    session, event = _transition( item, to )

    assert item.status == to
    assert event.transition == f"{frm}->{to}", "the transition's own event must come back, not the withdrawal"
    kinds = [ e.transition for e in session.added ]

    if withdrawn:
        assert ( item.request_state, item.request_move, item.request_ts ) == ( None, None, None ), label
        assert kinds == [ f"{frm}->{to}", "request_withdrawn" ], kinds
        withdrawal = session.added[ 1 ]
        assert withdrawal.actor == ACTOR
        assert repr( move ) in withdrawal.reason and f"{frm}->{to}" in withdrawal.reason
        assert "Not a denial" in withdrawal.reason
    else:
        assert ( item.request_state, item.request_move ) == ( state, move ), label
        assert kinds == [ f"{frm}->{to}" ], kinds


def test_a_withdrawal_writes_NEITHER_verdict():
    """R5 is about Rick's "no"; a stranded question is not one. The state goes to NULL, never 'denied'."""
    item = _item( HOLDING, PENDING, ADMIT )
    _transition( item, "queued" )
    assert item.request_state not in lifecycle.REQUEST_TERMINAL_STATES


def test_stale_is_the_filing_rule_read_after_the_move_across_EVERY_status():
    """
    The pure rule over the whole status surface: a pending request is stale exactly when
    it could not be filed against the row's new status — so the two cannot disagree.
    """
    assert len( rules.VALID_STATUSES ) >= 10
    for status in rules.VALID_STATUSES:
        for move in approval.REQUESTABLE_MOVES:
            fileable = lifecycle.refusal_for_filing( move, status ) is None
            assert lifecycle.request_is_stale( PENDING, move, status ) is ( not fileable ), ( move, status )
            assert lifecycle.request_is_stale( lifecycle.REQUEST_DENIED, move, status ) is False
            assert lifecycle.request_is_stale( None, None, status ) is False
