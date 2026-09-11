"""
THE FILING DOOR, DRIVEN AT THE REAL HTTP SURFACE — row c9fafb9d, rule 3.

Rick, 2026-09-08 ~11:58 EDT by keypress: "Only thing managers can do is request". Mr. Radio
ruled the shape on 2026-09-10: a manager files as its OWN act through a request door (reading
A of 8c83d7ce), managers only (D1). Design: src/rnd/2026.09.10-request-door-design.md §2.

WHAT IS REAL AND WHAT IS NOT
----------------------------
  · real  — the router, `refusal_for_filing` / `refusal_for_refiling`, `manager_refusal`,
            `recorded_actor`, and `TaskRepository.apply_request_filing` (run over a mock
            session, so the row an arm asserts on was written by the production method)
  · fake  — the database session, and `is_manager_figure`, which reads a session bridge a
            unit test does not have. Each arm sets it explicitly; the default is NOT a
            manager, so an arm that forgets gets a refusal rather than a false green.
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
from starlette.routing import Match

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_request_lifecycle as lifecycle
from cosa.rest import task_store_rules as rules
from cosa.rest.db.repositories.task_repository import TaskRepository as RealTaskRepository
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"

FILE_PATH   = "/api/tasks/{task_id}/request"
BADGES_PATH = "/api/tasks/request-badges"

NOW     = datetime( 2026, 9, 10, 0, 0, tzinfo=timezone.utc )
MANAGER = "mr radio d54262de"
WORKER  = "pocholo 5bd424ca"
REASON  = "the fix is merged and the row is ready to work"


def _item( **overrides ):
    """A TaskItem in whatever shape an arm needs. Never DB-backed."""
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row somebody wants moved",
        body                = None,
        project             = "lupin",
        owner_persona       = "pocholo",
        accountable_manager = "mr radio",
        created_by          = MANAGER,
        status              = approval.NOT_APPROVED_STATUS,
        priority            = "P2",
        urgency             = "normal",
        created_ts          = NOW,
        updated_ts          = NOW,
        request_state       = None,
        request_move        = None,
        request_ts          = None,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """Rick mapped to the operator account in a TEMP override file, never the fleet's."""
    import json
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"         : [ "rick" ],
        "approver_accounts" : { OPERATOR_EMAIL: "rick" },
    } ) )
    approval._cache_mtime = None
    return target


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router( tasks.router )
    return a


def _client( app, account_email=None ):
    """`account_email=None` is every agent seat in the fleet: API-key auth, no account."""
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


@pytest.fixture
def managers( monkeypatch ):
    """
    Which session ids the bridge calls managers. Starts EMPTY — an arm that forgets to add
    one is refused, which fails loudly instead of passing for the wrong reason.
    """
    seats = set()
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: sid in seats )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda sid: "denied" )
    return seats


@pytest.fixture
def stored( monkeypatch ):
    """A one-row store whose write runs the REAL `apply_request_filing`."""
    holder = { "item": None, "session": None }

    @contextmanager
    def _fake_get_db():
        session = MagicMock()
        session.execute.return_value.scalar_one.return_value = NOW
        holder[ "session" ] = session
        yield session

    def _fake_repo( session ):
        repo = MagicMock()
        repo.get_by_id_for_update.side_effect = lambda task_id: holder[ "item" ]
        repo.apply_request_filing.side_effect = RealTaskRepository( session ).apply_request_filing
        return repo

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", _fake_repo )
    return holder


def _file( client, item, move, actor=MANAGER, reason=REASON ):
    return client.post( FILE_PATH.format( task_id=item.id ),
                        json={ "move": move, "reason": reason, "actor": actor } )


def _events( stored ):
    return [ c.args[ 0 ] for c in stored[ "session" ].add.call_args_list ]


# ---------------------------------------------------------------------------
# ROUTING
# ---------------------------------------------------------------------------

def test_the_filing_door_resolves_to_its_own_handler_for_POST( app ):
    """Resolved as a request, so the verb and the path are pinned together."""
    path  = FILE_PATH.format( task_id=uuid.uuid4() )
    scope = { "type": "http", "method": "POST", "path": path, "path_params": { },
              "headers": [ ], "query_string": b"", "root_path": "" }
    resolved = [ r for r in app.routes if r.matches( scope )[ 0 ] == Match.FULL ]
    assert resolved, f"POST {path} resolves to no route"
    assert resolved[ 0 ].endpoint.__name__ == "file_request"


# ---------------------------------------------------------------------------
# RULE 3 — a manager files, and filing never moves the row
# ---------------------------------------------------------------------------

def test_a_MANAGER_files_a_pending_admit_and_the_row_does_not_move( app, settings, stored, managers ):
    """
    🔴 THE ARM THIS DOOR EXISTS FOR. A request ASKS: the row stays in the holding area,
    and what changes is the request columns plus one event naming who asked and why.
    """
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item( status=approval.NOT_APPROVED_STATUS )

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT )

    assert response.status_code == 200, response.text
    item = stored[ "item" ]
    assert item.status        == approval.NOT_APPROVED_STATUS, "filing a request MOVED the row"
    assert item.request_state == lifecycle.REQUEST_PENDING
    assert item.request_move  == approval.MOVE_ADMIT
    assert item.request_ts    == NOW
    assert response.json()[ "request_state" ] == lifecycle.REQUEST_PENDING

    events = _events( stored )
    assert len( events ) == 1, f"expected one event, got {events!r}"
    assert events[ 0 ].transition == "request_filed"
    assert events[ 0 ].actor      == MANAGER, "an API-key filing records the declared actor unchanged"
    assert REASON in events[ 0 ].reason and "'admit'" in events[ 0 ].reason


def test_the_filed_request_is_counted_on_the_HOLDING_AREA_badge( app, settings, stored, managers, monkeypatch ):
    """
    The positive arm the design names: what the door wrote is what the badge counts. The
    badge query is fed the filed row's own columns, not a literal pair.
    """
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item()
    assert _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT ).status_code == 200

    filed = stored[ "item" ]

    @contextmanager
    def _badge_db():
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = [ ( filed.request_move, filed.request_state ) ]
        yield session
    monkeypatch.setattr( tasks, "get_db", _badge_db )

    body = _client( app, OPERATOR_EMAIL ).get( BADGES_PATH ).json()
    assert body == { lifecycle.BADGE_HOLDING_AREA: 1, lifecycle.BADGE_TASK_AREA: 0 }


def test_a_MANAGER_files_a_demote_from_the_live_board( app, settings, stored, managers ):
    """The other verb, from a live status — the positive control for the fits-where-it-is check."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item( status="queued" )

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_DEMOTE )

    assert response.status_code == 200, response.text
    assert stored[ "item" ].status       == "queued"
    assert stored[ "item" ].request_move == approval.MOVE_DEMOTE


def test_a_logged_in_filing_records_the_ACCOUNT_beside_the_declared_actor( app, settings, stored, managers ):
    """Rick's account passes the manager check on the account door, and is named first."""
    stored[ "item" ] = _item()

    response = _file( _client( app, OPERATOR_EMAIL ), stored[ "item" ], approval.MOVE_ADMIT, actor="rick host" )

    assert response.status_code == 200, response.text
    assert _events( stored )[ 0 ].actor == "rick (rick host)"


# ---------------------------------------------------------------------------
# RULE 3 — who may file
# ---------------------------------------------------------------------------

def test_a_WORKER_cannot_file_and_the_row_is_untouched( app, settings, stored, managers ):
    """D1: managers only. The refusal says why and where to go instead."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )   # a manager exists; the caller is not it
    stored[ "item" ] = _item()

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT, actor=WORKER )

    assert response.status_code == 403, response.text
    detail = response.json()[ "detail" ]
    assert "filing a promote or demote request" in detail
    assert "asks its manager" in detail
    assert stored[ "item" ].request_state is None, "the door refused and filed anyway"
    assert _events( stored ) == [ ]


def test_a_WORKER_is_refused_before_learning_a_request_is_pending( app, settings, stored, managers ):
    """
    ⚠️ ORDER, NOT JUST OUTCOME. A non-manager must not be able to probe the queue: a row
    with a pending request answers a worker 403, never the 409 that names the pending move.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT, actor=WORKER )

    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------------
# RULE 3 — one request at a time, and only a request the row can answer
# ---------------------------------------------------------------------------

def test_a_SECOND_filing_while_one_is_pending_is_409_and_names_the_pending_move( app, settings, stored, managers ):
    """R7, one at a time: a second filing would put the same question in Rick's queue twice."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT )

    assert response.status_code == 409, response.text
    assert "'admit' request is already pending" in response.json()[ "detail" ]
    assert _events( stored ) == [ ]


def test_a_DENIED_request_may_be_filed_again_and_the_event_names_the_prior_verdict( app, settings, stored, managers ):
    """A denial forces a re-file (Rick, 2026-09-09); the verdict it replaces survives in the event."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_DENIED,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT )

    assert response.status_code == 200, response.text
    assert stored[ "item" ].request_state == lifecycle.REQUEST_PENDING
    assert "prior request: 'denied'" in _events( stored )[ 0 ].reason


@pytest.mark.parametrize( "move,status,where", [
    ( approval.MOVE_ADMIT,  "queued",                      "not in the holding area" ),
    ( approval.MOVE_DEMOTE, approval.NOT_APPROVED_STATUS,  "not on the live board" ),
    ( approval.MOVE_DEMOTE, "done",                        "not on the live board" ),
] )
def test_a_move_the_row_CANNOT_make_is_409_naming_where_the_row_is( app, settings, stored, managers, move, status, where ):
    """Asking the wrong question is a different mistake from lacking permission, and says so."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item( status=status )

    response = _file( _client( app ), stored[ "item" ], move )

    assert response.status_code == 409, response.text
    detail = response.json()[ "detail" ]
    assert f"'{status}'" in detail and where in detail
    assert stored[ "item" ].request_state is None


@pytest.mark.parametrize( "move", [ approval.MOVE_WONT_FIX, approval.MOVE_UN_PARK, "promote-please" ] )
def test_a_move_that_is_not_REQUESTABLE_is_422_naming_the_two_that_are( app, settings, stored, managers, move ):
    """Won't-fix and un-park are approver-only and nobody has ruled a manager may ask for them."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item()

    response = _file( _client( app ), stored[ "item" ], move )

    assert response.status_code == 422, response.text
    detail = response.json()[ "detail" ]
    assert "'admit'" in detail and "'demote'" in detail


def test_a_BLANK_reason_is_422( app, settings, stored, managers ):
    """Rick decides from the reason; a request without one is not something he can answer."""
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = _item()

    response = _file( _client( app ), stored[ "item" ], approval.MOVE_ADMIT, reason="   " )

    assert response.status_code == 422, response.text
    assert "reason" in response.json()[ "detail" ]
    assert stored[ "item" ].request_state is None


def test_a_MISSING_row_is_404( app, settings, stored, managers ):
    managers.add( rules.session_id_from_created_by( MANAGER ) )
    stored[ "item" ] = None
    response = _client( app ).post( FILE_PATH.format( task_id=uuid.uuid4() ),
                                    json={ "move": approval.MOVE_ADMIT, "reason": REASON, "actor": MANAGER } )
    assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# THE PURE RULE, OVER THE WHOLE STATUS SURFACE
# ---------------------------------------------------------------------------

def test_where_each_move_may_be_filed_from_across_EVERY_status():
    """
    Enumerates the surface rather than the traffic: every status for both moves. `admit`
    fits only the holding area; `demote` fits every live status and nothing terminal.
    """
    assert len( rules.VALID_STATUSES ) >= 10, "the status population shrank — this loop proves less"
    for status in rules.VALID_STATUSES:
        admit_ok  = lifecycle.refusal_for_filing( approval.MOVE_ADMIT,  status ) is None
        demote_ok = lifecycle.refusal_for_filing( approval.MOVE_DEMOTE, status ) is None
        assert admit_ok  == ( status == approval.NOT_APPROVED_STATUS ), status
        assert demote_ok == ( status != approval.NOT_APPROVED_STATUS and status not in rules.TERMINAL_STATUSES ), status
