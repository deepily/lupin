"""
THE REQUEST QUEUE'S TWO DOORS, DRIVEN AT THE REAL HTTP SURFACE.

Row c9fafb9d, rules 3 and 4. Rick ruled the door on 2026-09-09 by keypress: a PERSISTENT
QUEUE he works from a board, no expiry, no denial on timeout. Mr. Radio gave the go for
these two doors on 2026-09-09 ~19:50 EDT while the FILING door stays deferred on decision
row 8c83d7ce.

WHAT IS UNDER TEST, AND WHAT IS DELIBERATELY NOT
------------------------------------------------
  · GET  /api/tasks/request-badges          the two counts
  · POST /api/tasks/{task_id}/request-verdict  the operator's answer

There is NO filing door yet, and its absence is a ruling-in-waiting rather than an
oversight — see the router's block comment. So these arms set `request_state` on the row
directly, which is the ONLY way to reach an answerable request today. That is stated here
rather than hidden in a fixture, because a reader who assumes a filing door exists will
wonder why nothing calls it.

🔴 THE ARMS DRIVE THE REAL DOOR. The row's acceptance says a disabled control is
presentation, not a firewall — so every refusal below is a real request through a real
router, never a direct call to `refusal_for_verdict`. A test that enters at the module
cannot speak to whether the door is wired to it, and the 27 green arms already sitting on
that module are exactly the evidence that proves nothing about these doors.
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
from cosa.rest.db.repositories.task_repository import TaskRepository as RealTaskRepository
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"

BADGES_PATH  = "/api/tasks/request-badges"
VERDICT_PATH = "/api/tasks/{task_id}/request-verdict"

NOW     = datetime( 2026, 9, 9, 0, 0, tzinfo=timezone.utc )
MANAGER = "mr radio 21dff055"


def _item( **overrides ):
    """A TaskItem carrying whatever request shape an arm needs. Never DB-backed."""
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
    """
    Rick mapped to the operator account, in a TEMP override file.

    🔴 WITHOUT THIS these arms measure whoever happens to be an approver today — an
    operator-editable file deciding a test result — and they would WRITE the live fleet
    settings file, which carries Rick's standing rescission.
    """
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


def _client( app, account_email ):
    """
    A client whose ONE variable is the login account the SERVER resolves.

    `authenticated_account_email` is overridden rather than stubbed on the module, so the
    handler resolves it exactly as production does. `None` is EVERY AGENT SEAT IN THE
    FLEET: API-key auth, no account.
    """
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


@pytest.fixture
def stored( monkeypatch ):
    """
    A one-row store the verdict door reads and writes through the REAL repository seam.

    Returns a dict the arm mutates: `stored[ "item" ]` is what `get_by_id_for_update`
    hands back, and the handler's writes land on that same object — so an arm can assert
    what the door actually wrote rather than what it returned.
    """
    holder = { "item": None, "repo": None, "session": None }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    def _fake_repo( session ):
        repo = MagicMock()
        repo.get_by_id_for_update.side_effect = lambda task_id: holder[ "item" ]
        # 🔴 THE WRITE RUNS THE REAL REPOSITORY METHOD, over a mock session. A bare mock
        # here would accept the call and change nothing, and every "the row actually
        # changed" arm below would redden for a reason that has nothing to do with the door.
        repo.apply_request_verdict.side_effect = RealTaskRepository( session ).apply_request_verdict
        holder[ "repo" ]    = repo
        holder[ "session" ] = session
        return repo

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", _fake_repo )
    return holder


# ---------------------------------------------------------------------------
# THE ISOLATION CONTROL FIRST — a green file must not also be consistent with
# these arms reading the real fleet settings.
# ---------------------------------------------------------------------------

def test_the_arms_are_reading_the_TEMP_settings_and_not_the_fleet_one( settings ):
    """If this fails, every other result in this file is about the live deployment."""
    assert approval.override_path() == str( settings )
    assert "projects-data" not in approval.override_path()
    assert "/var/lupin"    not in approval.override_path()


# ---------------------------------------------------------------------------
# ROUTING — the verb AND the shadowing, because this router has shipped the
# shadowing defect twice and the verb defect once.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "method,path_template,expected", [
    ( "GET",  BADGES_PATH,  "get_request_badges" ),
    ( "POST", VERDICT_PATH, "record_request_verdict" ),
] )
def test_each_door_resolves_to_ITS_OWN_handler_for_ITS_OWN_verb( app, method, path_template, expected ):
    """
    🔴 THE SHADOWING ARM, AND IT IS NOT DECORATION HERE. `/api/tasks/request-badges` is a
    LITERAL path in a router that also mounts `/api/tasks/{task_id}`, and a literal
    registered after a parameterised sibling resolves to the sibling — that is how
    `/api/tasks/manager-pull` shipped once and how `/api/tasks/flow-ratio` answered 422
    "invalid UUID" in production for an evening.

    MEASURED, and the reason this arm exists rather than a comment: a GET for the badges
    path matches BOTH `get_request_badges` AND `get_task` at Match.FULL. Starlette takes
    the FIRST, so the badge door wins only because it is registered above `get_task`. Move
    the registration down and every badge arm below starts failing with a message about an
    invalid UUID — a routing change wearing a validation failure.

    Asked as a RESOLVED REQUEST rather than by reading `.methods`: `Match.FULL` requires
    the path AND the verb, so this pins the method and the ordering in one assertion.
    """
    path  = path_template.format( task_id=uuid.uuid4() )
    scope = { "type": "http", "method": method, "path": path, "path_params": { },
              "headers": [ ], "query_string": b"", "root_path": "" }

    resolved = [ r for r in app.routes if r.matches( scope )[ 0 ] == Match.FULL ]
    assert resolved, (
        f"{method} {path} resolves to NO route. Either the door changed verb or it is not "
        f"mounted; every arm in this file sends {method}."
    )
    assert resolved[ 0 ].endpoint.__name__ == expected, (
        f"{method} {path} resolves to {resolved[ 0 ].endpoint.__name__}, not {expected} — it "
        f"is shadowed by a sibling registered earlier."
    )


# ---------------------------------------------------------------------------
# THE BADGE READ
# ---------------------------------------------------------------------------

def _badge_rows( monkeypatch, rows ):
    """Point the badge door's query at `rows` — ( move, state ) pairs."""
    @contextmanager
    def _fake_get_db():
        session = MagicMock()
        session.query.return_value.filter.return_value.all.return_value = rows
        yield session
    monkeypatch.setattr( tasks, "get_db", _fake_get_db )


def test_the_badge_door_returns_BOTH_keys_even_with_nothing_waiting( app, monkeypatch ):
    """
    Both keys ALWAYS present, so no caller has to tell "zero" from "absent" — a board that
    cannot make that distinction renders an empty badge and a broken query identically.
    """
    _badge_rows( monkeypatch, [ ] )
    body = _client( app, OPERATOR_EMAIL ).get( BADGES_PATH ).json()
    assert body == { lifecycle.BADGE_TASK_AREA: 0, lifecycle.BADGE_HOLDING_AREA: 0 }


def test_the_two_badges_count_their_own_list_and_are_NEVER_summed( app, monkeypatch ):
    """
    🔴 THE MAPPING LOOKS INVERTED AND IS NOT, so this arm pins it against a helpful swap.
    A badge sits on the list the row is in NOW, never the list it is asking to reach: a
    DEMOTE is filed against a row that is already LIVE, so it shows on the task list; a
    PROMOTE is filed against a row in the HOLDING area, so it shows there.

    The two counts must also be DIFFERENT numbers here. If an arm used one demote and one
    promote, a response that summed them, swapped them, or returned the same total twice
    would all be indistinguishable from the correct answer.
    """
    _badge_rows( monkeypatch, [
        ( approval.MOVE_DEMOTE, lifecycle.REQUEST_PENDING ),
        ( approval.MOVE_ADMIT,  lifecycle.REQUEST_PENDING ),
        ( approval.MOVE_ADMIT,  lifecycle.REQUEST_PENDING ),
    ] )
    body = _client( app, OPERATOR_EMAIL ).get( BADGES_PATH ).json()

    assert body[ lifecycle.BADGE_TASK_AREA ]    == 1, "a DEMOTE belongs to the task-area badge"
    assert body[ lifecycle.BADGE_HOLDING_AREA ] == 2, "a PROMOTE belongs to the holding-area badge"
    assert sum( body.values() ) == 3 and body[ lifecycle.BADGE_TASK_AREA ] != body[ lifecycle.BADGE_HOLDING_AREA ], (
        "the two counts must be distinct here, or a summing/swapping bug reads as correct"
    )


def test_an_ANSWERED_request_stops_being_counted( app, monkeypatch ):
    """
    Only PENDING counts. A denied request is finished and the manager must re-file; an
    approved one has already moved the row. Counting either keeps an answered question
    pulsing at Rick forever.

    The positive control rides in the same arm: the pending row IS counted, so a zero here
    cannot be produced by a query that simply found nothing.
    """
    _badge_rows( monkeypatch, [
        ( approval.MOVE_ADMIT,  lifecycle.REQUEST_PENDING  ),
        ( approval.MOVE_ADMIT,  lifecycle.REQUEST_APPROVED ),
        ( approval.MOVE_DEMOTE, lifecycle.REQUEST_DENIED   ),
    ] )
    body = _client( app, OPERATOR_EMAIL ).get( BADGES_PATH ).json()
    assert body == { lifecycle.BADGE_TASK_AREA: 0, lifecycle.BADGE_HOLDING_AREA: 1 }


# ---------------------------------------------------------------------------
# THE VERDICT DOOR — rules 1 and 2, one layer over
# ---------------------------------------------------------------------------

def _verdict( client, item, verdict ):
    return client.post( VERDICT_PATH.format( task_id=item.id ), json={ "verdict": verdict } )


@pytest.mark.parametrize( "account", [ None, BYSTANDER_MAIL ] )
@pytest.mark.parametrize( "verdict", [ lifecycle.REQUEST_APPROVED, lifecycle.REQUEST_DENIED ] )
def test_a_NON_OPERATOR_cannot_answer_a_request_either_way( app, settings, stored, account, verdict ):
    """
    🔴 `account=None` IS EVERY AGENT SEAT IN THE FLEET — API-key auth, no login account —
    and `BYSTANDER_MAIL` is a real login that maps to nobody. Both must be refused, and
    BOTH verdicts must be refused: a door that blocked denial and allowed approval would
    be a way to promote without Rick, which is the thing this door exists to prevent.

    ⚠️ AND THE ROW MUST BE UNTOUCHED. A 403 that had already written the verdict would
    still read as a refusal to the caller.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, account ), stored[ "item" ], verdict )

    assert response.status_code == 403, response.text
    assert "operator" in response.json()[ "detail" ].lower()
    assert stored[ "item" ].request_state == lifecycle.REQUEST_PENDING, (
        "the door refused and wrote the verdict anyway"
    )


@pytest.mark.parametrize( "verdict", [ lifecycle.REQUEST_APPROVED, lifecycle.REQUEST_DENIED ] )
def test_THE_OPERATOR_records_either_verdict_and_the_row_actually_changes( app, settings, stored, verdict ):
    """
    🔴 THE POSITIVE ARM. Without it the arms above prove only that the door can say no,
    and a door wired to refuse everything would satisfy every refusal test in this file.

    Asserts the WRITE, not just the status code: `request_state` on the stored object is
    what a later reader sees.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], verdict )

    assert response.status_code == 200, response.text
    assert stored[ "item" ].request_state == verdict
    assert response.json()[ "request_state" ] == verdict


@pytest.mark.parametrize( "verdict", [ lifecycle.REQUEST_APPROVED, lifecycle.REQUEST_DENIED ] )
def test_a_verdict_is_recorded_under_the_OPERATORS_ACCOUNT_with_its_own_event( app, settings, stored, verdict ):
    """
    🔴 WHO ANSWERED IS PART OF THE ANSWER. The door used to set `request_state` inline and
    append nothing, so the store could not say who approved or denied a request. The actor
    is read off the event the REAL repository method appended, not off the call's kwargs —
    so a door that passed the right actor to a method that dropped it would still redden.

    ⚠️ "test-user" is the id `require_api_key_or_jwt` resolves in `_client` — a server-known
    value. The declared half is never a string the caller typed, because the body has none.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], verdict )

    assert response.status_code == 200, response.text
    calls = stored[ "repo" ].apply_request_verdict.call_count
    assert calls == 1, f"the verdict was written {calls} times through the repository"

    added = [ c.args[ 0 ] for c in stored[ "session" ].add.call_args_list ]
    assert len( added ) == 1, f"expected exactly one appended event, got {added!r}"
    event = added[ 0 ]
    assert event.actor      == "rick (test-user)"
    assert event.transition == f"request_{verdict}"
    assert event.authority  == "user_direct"
    assert event.item_id    == stored[ "item" ].id
    assert "'pending'" in event.reason and f"'{verdict}'" in event.reason and "admit" in event.reason


def test_a_DENIAL_finishes_the_request_and_never_touches_the_TICKET( app, settings, stored ):
    """
    🔴 MR. RADIO'S READING A, MADE STRUCTURAL (2026-09-09). "A denial closes the row" means
    the REQUEST is finished and the TICKET is untouched — reading B, that a denial closes
    the TASK, is recorded as rejected. This arm is what stops reading B being re-introduced
    by someone who reads the sentence and not the ruling.
    """
    stored[ "item" ] = _item( status=approval.NOT_APPROVED_STATUS,
                              request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], lifecycle.REQUEST_DENIED )

    assert response.status_code == 200, response.text
    assert stored[ "item" ].request_state == lifecycle.REQUEST_DENIED
    assert stored[ "item" ].status == approval.NOT_APPROVED_STATUS, (
        "the denial moved the TICKET — that is reading B, which was rejected"
    )


def test_an_ANSWERED_request_cannot_be_answered_again( app, settings, stored ):
    """
    A verdict is final. Overwriting would let a second caller silently replace an answer
    Rick actually gave; to ask again a manager files a NEW request.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_DENIED,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], lifecycle.REQUEST_APPROVED )

    assert response.status_code == 409, response.text
    assert "final" in response.json()[ "detail" ].lower()
    assert stored[ "item" ].request_state == lifecycle.REQUEST_DENIED


def test_PENDING_is_not_a_verdict_anyone_can_record( app, settings, stored ):
    """
    'pending' is where a request already is, not something anyone decides. Accepting it
    would make "un-answer this request" reachable, and nothing has ruled that it should be.
    """
    stored[ "item" ] = _item( request_state=lifecycle.REQUEST_PENDING,
                              request_move=approval.MOVE_ADMIT, request_ts=NOW )

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], lifecycle.REQUEST_PENDING )

    assert response.status_code == 409, response.text
    assert "not a verdict" in response.json()[ "detail" ].lower()


def test_a_row_with_NO_REQUEST_says_so_instead_of_refusing_permission( app, settings, stored ):
    """
    🔴 A DIFFERENT MISTAKE DESERVES A DIFFERENT SENTENCE. Answering a row nobody asked
    about is not a permissions failure, and a 403 here would send the operator to look at
    his own access when the real answer is that no request was ever filed.
    """
    stored[ "item" ] = _item()   # request_state None — the state almost every row is in

    response = _verdict( _client( app, OPERATOR_EMAIL ), stored[ "item" ], lifecycle.REQUEST_APPROVED )

    assert response.status_code == 409, response.text
    detail = response.json()[ "detail" ]
    assert "no promote/demote request" in detail
    assert "not a permissions refusal" in detail


def test_a_MISSING_row_is_a_404_and_not_a_refusal( app, settings, stored ):
    """A door that answered 403 for an absent row would leak nothing and explain nothing."""
    stored[ "item" ] = None
    response = _client( app, OPERATOR_EMAIL ).post(
        VERDICT_PATH.format( task_id=uuid.uuid4() ), json={ "verdict": lifecycle.REQUEST_APPROVED }
    )
    assert response.status_code == 404, response.text
