"""
AN APPROVED REQUEST PERFORMS THE MOVE — row c9fafb9d, Rick's Q2.

Rick, 2026-09-10 ~19:44 EDT by keypress (answered: true, default_used: false): "Approval moves
it" — approving a manager's request performs the move through the same transition path as his
own board click. Design: src/rnd/2026.09.10-request-door-design.md §4.

WHAT IS REAL
------------
The router, both doors, `_apply_transition_under_lock` (the transition door's own gate order),
and the repository writes `apply_request_filing`, `apply_request_verdict` and
`apply_transition`, run over ONE recording session shared by every request in an arm — so the
audit trail an arm reads is the one production would write, in production's order.

WHAT IS FAKE
------------
The database session, the manager bridge, and the promotion ask. Rick's account is
ask-exempt, so the real gate never asks him; the ask seam is replaced by one that FAILS the
test if it is ever reached, rather than one that quietly says yes.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as gate
from cosa.rest import task_request_lifecycle as lifecycle
from cosa.rest import task_store_rules as rules
from cosa.rest.db.repositories.task_repository import TaskRepository as RealTaskRepository
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
MANAGER        = "mr radio d54262de"
NOW            = datetime( 2026, 9, 10, 0, 0, tzinfo=timezone.utc )
TRIAGE_BY      = "2026-09-17T13:00:00+00:00"

FILE_PATH    = "/api/tasks/{task_id}/request"
VERDICT_PATH = "/api/tasks/{task_id}/request-verdict"


class _Store:
    """One row, one recording session, and whether a request's transaction was rolled back."""
    def __init__( self, item ):
        self.item        = item
        self.added       = [ ]
        self.rolled_back = [ ]


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router( tasks.router )
    return a


@pytest.fixture
def world( monkeypatch, tmp_path ):
    """Rick mapped to the operator account (TEMP file), one manager seat, and no live ask."""
    import json
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( { "approvers": [ "rick" ], "approver_accounts": { OPERATOR_EMAIL: "rick" } } ) )
    approval._cache_mtime = None
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: True )

    seats = { rules.session_id_from_created_by( MANAGER ) }
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: sid in seats )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda sid: "denied" )

    def _no_ask( **kwargs ):
        raise AssertionError( "the promotion ask fired for Rick's own approval — he is ask-exempt" )
    real_approval = gate.approval_for_promotion
    monkeypatch.setattr( gate, "approval_for_promotion", lambda **k: real_approval( **{ **k, "ask_fn": _no_ask } ) )


def _wire( monkeypatch, item ):
    store = _Store( item )

    session = MagicMock()
    def _add( obj ):
        if getattr( obj, "ts", None ) is None:  obj.ts   = NOW    # the flush's server default
        if getattr( obj, "item", None ) is None: obj.item = item
        store.added.append( obj )
    session.add.side_effect = _add
    session.execute.return_value.scalar_one.return_value = NOW

    @contextmanager
    def _fake_get_db():
        # The real `get_db` commits on success and rolls back on ANY exception. This records
        # which, so an arm can say a refused approval was rolled back rather than assume it.
        try:
            yield session
        except Exception as e:
            store.rolled_back.append( e )
            raise

    real = RealTaskRepository( session )
    repo = MagicMock()
    repo.get_by_id_for_update.side_effect  = lambda task_id: store.item
    repo.count_admissions_since.return_value = 0
    repo.apply_request_filing.side_effect  = real.apply_request_filing
    repo.apply_request_verdict.side_effect = real.apply_request_verdict
    repo.apply_transition.side_effect      = real.apply_transition

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda s: repo )
    return store, repo


def _client( app, account_email ):
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _item( status ):
    return TaskItem(
        id = uuid.uuid4(), item_class = "task", title = "a row a manager wants moved", body = None,
        project = "lupin", owner_persona = "pocholo", accountable_manager = "mr radio",
        created_by = MANAGER, status = status, priority = "P2", urgency = "normal",
        blocked_by = [ ], created_ts = NOW, updated_ts = NOW,
        request_state = None, request_move = None, request_ts = None,
    )


def _file( app, item, move ):
    return _client( app, None ).post( FILE_PATH.format( task_id=item.id ),
                                      json={ "move": move, "reason": "ready to work", "actor": MANAGER } )


def _verdict( app, item, verdict, **extras ):
    return _client( app, OPERATOR_EMAIL ).post( VERDICT_PATH.format( task_id=item.id ),
                                                json={ "verdict": verdict, **extras } )


# ---------------------------------------------------------------------------
# Q2 — approval moves it
# ---------------------------------------------------------------------------

def test_an_approved_ADMIT_lands_the_row_in_queued_and_the_trail_reads_file_approve_move( app, world, monkeypatch ):
    """
    🔴 THE ARM Q2 EXISTS FOR, END TO END: a manager files, Rick approves, the row moves — and
    the audit trail records all three in that order, so a reader can see the move was an
    approved request and not a bare click.
    """
    item      = _item( approval.NOT_APPROVED_STATUS )
    store, _  = _wire( monkeypatch, item )

    assert _file( app, item, approval.MOVE_ADMIT ).status_code == 200
    response = _verdict( app, item, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 200, response.text
    assert item.status == "queued"
    assert item.request_state == lifecycle.REQUEST_APPROVED, "the approval was withdrawn as stranded by its own move"
    assert response.json()[ "status" ] == "queued"
    assert [ e.transition for e in store.added ] == [ "request_filed", "request_approved", "not_approved->queued" ]
    move_event = store.added[ 2 ]
    assert move_event.actor.startswith( "rick" ), move_event.actor
    assert "approved a manager's 'admit' request" in move_event.reason


def test_an_approved_DEMOTE_lands_in_the_holding_area_with_Ricks_triage_date( app, world, monkeypatch ):
    """The other verb: a demote carries the "Triage this by" date his own demote control asks for."""
    item     = _item( "queued" )
    store, _ = _wire( monkeypatch, item )

    assert _file( app, item, approval.MOVE_DEMOTE ).status_code == 200
    response = _verdict( app, item, lifecycle.REQUEST_APPROVED,
                         next_chase_ts=TRIAGE_BY, reason="not worth the board this week" )

    assert response.status_code == 200, response.text
    assert item.status == approval.NOT_APPROVED_STATUS
    assert item.next_chase_ts is not None and item.next_chase_ts.isoformat().startswith( "2026-09-17" )
    assert [ e.transition for e in store.added ][ -1 ] == "queued->not_approved"
    assert "not worth the board this week" in store.added[ -1 ].reason


def test_a_DENIAL_moves_nothing_and_writes_one_event( app, world, monkeypatch ):
    """R5, "No means take no action whatsoever": the control beside the two approval arms."""
    item     = _item( approval.NOT_APPROVED_STATUS )
    store, _ = _wire( monkeypatch, item )

    assert _file( app, item, approval.MOVE_ADMIT ).status_code == 200
    response = _verdict( app, item, lifecycle.REQUEST_DENIED )

    assert response.status_code == 200, response.text
    assert item.status == approval.NOT_APPROVED_STATUS
    assert [ e.transition for e in store.added ] == [ "request_filed", "request_denied" ]


def test_a_GATE_REFUSAL_on_the_move_returns_that_gate_and_rolls_the_approval_back( app, world, monkeypatch ):
    """
    🔴 THE APPROVAL AND THE MOVE ARE ONE ACT. If any gate on the transition path refuses, the
    caller gets that gate's refusal and the transaction that wrote 'approved' is rolled back —
    so the request stays pending instead of reading approved over a row that never moved.

    ⚠️ The refusal is injected at `refusal_for_admission`, which the transition path calls,
    because Rick's own account passes every real gate today and a refusal arm that cannot be
    reached proves nothing.
    """
    item        = _item( approval.NOT_APPROVED_STATUS )
    store, repo = _wire( monkeypatch, item )
    assert _file( app, item, approval.MOVE_ADMIT ).status_code == 200

    monkeypatch.setattr( approval, "refusal_for_admission", lambda *a, **k: "an injected gate refusal" )
    response = _verdict( app, item, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 403, response.text
    assert response.json()[ "detail" ] == "an injected gate refusal"
    assert len( store.rolled_back ) == 1, "the refused approval's transaction was not rolled back"
    repo.apply_transition.assert_not_called()
