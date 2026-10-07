#!/usr/bin/env python3
"""
Unit tests for un-parking a row on a card the server made.

Rick ruled that a manager may un-park a row with the card id on the row. The card must be
the server's own, for that row and that move, and the receipt covers parked to queued only.
The design of record is io/tmp/2026.10.07-pocholo-unpark-survey.md, sections 2 to 4.

Three levels share this file:
    - the card function, on real Notification records, one test per refusal, with a positive control
    - the gate clause in refusal_for_admission, pure
    - the transition door, driven over HTTP with the router's database seams faked

Nothing here touches the real store, the real settings file or a real session bridge.
"""
import os
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest import task_promotion_gate as gate
from cosa.rest import task_store_rules as rules
from cosa.rest.db.repositories.task_repository import TaskRepository
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.postgres_models import Notification, TaskEvent, TaskItem
from cosa.rest.routers import notifications
from cosa.rest.routers import tasks
from lupin_cli.claude_code.hooks.lib.manager_figure import DENIAL_DENIED
from tests.helpers.approval_settings_fixtures import SettingsHandle

PARKED_AT    = datetime( 2026, 10, 7, 20, 0, tzinfo=timezone.utc )
CARD_MADE_AT = PARKED_AT + timedelta( minutes = 5 )
RICK_EMAIL   = "rick@example.com"
MARIA_EMAIL  = "maria@example.com"
MANAGER_SID  = "d54262de"
WORKER_SID   = "5a3f00c1"
MANAGER      = f"mr radio {MANAGER_SID}"
WORKER       = f"sam {WORKER_SID}"
ROW_ID       = uuid.UUID( "11111111-1111-4111-8111-111111111111" )
OTHER_ROW_ID = uuid.UUID( "22222222-2222-4222-8222-222222222222" )

OPERATOR_STAMP = { "user_id": "u-1", "account_email": RICK_EMAIL,  "method": "jwt" }
API_KEY_STAMP  = { "user_id": "u-2", "account_email": None,        "method": "api_key" }
NON_OPERATOR   = { "user_id": "u-3", "account_email": MARIA_EMAIL, "method": "jwt" }


@pytest.fixture( autouse=True )
def accounts( monkeypatch ):
    """Rick's login maps to the operator persona; Maria's maps to a non-operator approver."""
    monkeypatch.setattr( gate, "approver_persona_for_account", lambda email: { RICK_EMAIL: "rick", MARIA_EMAIL: "maria" }.get( email ) )


def _answered_yes_through_the_real_door( card, answered_by_user="u-1", account_email=RICK_EMAIL, x_api_key=None ):
    """Store a yes on `card` with the answer door's and the repository's own writers."""
    stored = notifications._stored_response_dict( "yes", notifications._answered_by( answered_by_user, account_email, x_api_key ) )
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = card
    NotificationRepository( session ).update_response( card.id, stored )
    return card


def _card( **overrides ):
    """A real Notification made for ROW_ID, answered yes by the operator through the real door."""
    fields = dict(
        id                 = uuid.uuid4(),
        sender_id          = "claude.code@lupin.deepily.ai#promotion-gate",
        recipient_id       = uuid.uuid4(),
        message            = "Allow the un-park?",
        type               = "custom",
        priority           = "high",
        response_requested = True,
        response_type      = "yes_no",
        state              = "responded",
        responded_at       = CARD_MADE_AT + timedelta( minutes = 1 ),
        payload            = gate.unpark_ask_payload( ROW_ID ),
        created_at         = CARD_MADE_AT,
    )
    fields.update( overrides )
    card = Notification( **fields )
    if "response_value" not in overrides:
        stored_state, stored_at = card.state, card.responded_at
        _answered_yes_through_the_real_door( card )
        card.state, card.responded_at = stored_state, stored_at
    return card


def _refusal( card, used=( ), task_id=ROW_ID, parked_since=PARKED_AT ):
    return gate.unpark_card_refusal( card, task_id, parked_since, used )


# ── the card function: the positive control first ───────────────────────────

def test_an_operator_answered_yes_on_a_card_made_for_this_row_passes():
    """The positive control. If this fails, every refusal test below proves nothing."""
    assert _refusal( _card() ) is None


def test_the_payload_the_server_writes_names_the_row_and_the_move():
    assert gate.unpark_ask_payload( ROW_ID ) == { "kind": "unpark_ask", "task_id": str( ROW_ID ), "move": "parked->queued" }


# ── the card function: one test per refusal ─────────────────────────────────

def test_a_card_that_exists_nowhere_is_refused():
    assert "No card with that id exists" in _refusal( None )


def test_a_notification_that_asked_no_question_is_refused():
    assert "asked no question" in _refusal( _card( response_requested=False ) )


def test_an_unanswered_card_is_refused():
    assert "no answer yet" in _refusal( _card( responded_at=None, state="delivered", response_value=None ) )


def test_a_card_that_is_answered_but_not_in_the_responded_state_is_refused():
    assert "no answer yet" in _refusal( _card( state="expired" ) )


def test_the_fixture_is_the_shape_the_real_door_and_repository_write():
    card = _card()
    assert card.response_value == { "value": "yes", "source": "ui",
                                    "answered_by": { "user_id": "u-1", "account_email": RICK_EMAIL, "method": "jwt" } }


def test_the_real_writer_marks_a_delivered_card_responded_and_stamps_the_time():
    waiting = Notification( id=uuid.uuid4(), sender_id="x", recipient_id=uuid.uuid4(), message="m", type="custom",
                            priority="high", state="delivered", response_requested=True )
    _answered_yes_through_the_real_door( waiting )
    assert waiting.state == "responded" and waiting.responded_at is not None


def test_the_answer_is_read_without_regard_to_capital_letters():
    assert _refusal( _card( response_value={ "value": "Yes", "source": "ui", "answered_by": OPERATOR_STAMP }, state="responded",
                            responded_at=CARD_MADE_AT + timedelta( minutes = 1 ) ) ) is None


def test_a_card_settled_by_its_timed_out_default_is_refused():
    defaulted = _card( response_value={ "value": "yes", "source": "timeout_default" } )
    assert "timed-out default" in _refusal( defaulted )


def test_a_no_is_refused():
    assert "not yes" in _refusal( _card( response_value={ "value": "no", "source": "ui", "answered_by": OPERATOR_STAMP } ) )


def test_an_answer_stored_as_something_other_than_a_dict_is_refused_not_raised():
    assert "not yes" in _refusal( _card( response_value=None ) )


def test_a_yes_posted_with_an_api_key_is_refused():
    stamped = _card( response_value={ "value": "yes", "source": "ui", "answered_by": API_KEY_STAMP } )
    assert "API-key caller" in _refusal( stamped )


def test_a_yes_posted_by_a_login_that_is_not_the_operator_is_refused():
    stamped = _card( response_value={ "value": "yes", "source": "ui", "answered_by": NON_OPERATOR } )
    assert MARIA_EMAIL in _refusal( stamped )


def test_a_yes_with_nobody_recorded_is_refused():
    assert "nobody the server recorded" in _refusal( _card( response_value={ "value": "yes", "source": "ui" } ) )


def test_an_operator_yes_about_a_different_row_is_refused():
    assert "not made by the server for this row" in _refusal( _card( payload=gate.unpark_ask_payload( OTHER_ROW_ID ) ) )


def test_an_operator_yes_about_a_different_move_is_refused():
    other_move = { **gate.unpark_ask_payload( ROW_ID ), "move": "parked->in_progress" }
    assert "not made by the server for this row" in _refusal( _card( payload=other_move ) )


def test_a_card_whose_text_names_the_row_but_whose_payload_is_empty_is_refused():
    """A manager's own ask can say anything in its text. Only the server-written payload counts."""
    handwritten = _card( payload=None, message=f"Allow un-parking {ROW_ID}?", abstract=f"row {ROW_ID}, parked->queued" )
    assert "not made by the server for this row" in _refusal( handwritten )


def test_a_card_made_before_the_row_was_parked_is_refused():
    assert "older than the park" in _refusal( _card( created_at=PARKED_AT - timedelta( minutes = 1 ) ) )


def test_a_card_made_at_the_very_instant_of_the_park_is_refused():
    assert "older than the park" in _refusal( _card( created_at=PARKED_AT ) )


def test_a_card_with_no_creation_time_is_refused_not_raised():
    assert "older than the park" in _refusal( _card( created_at=None ) )


def test_a_row_with_no_recorded_park_time_refuses_every_card():
    assert "no recorded park time" in _refusal( _card(), parked_since=None )


def test_a_card_already_used_is_refused_the_second_time():
    card = _card()
    assert _refusal( card, used=set() ) is None
    assert "already been used" in _refusal( card, used={ str( card.id ) } )


def test_used_card_ids_are_compared_as_text_so_a_uuid_object_counts_too():
    card = _card()
    assert "already been used" in _refusal( card, used=[ card.id ] )


# ── the card id the caller cites ────────────────────────────────────────────

def test_a_cited_card_id_is_read_back_as_a_uuid():
    assert gate.approval_card_id( { "approval_card": str( ROW_ID ) } ) == ROW_ID


@pytest.mark.parametrize( "receipts", [ None, "x", [ ], { }, { "approval_card": 7 }, { "approval_card": "not-a-uuid" } ],
                          ids=[ "none", "string", "list", "no-key", "int", "malformed" ] )
def test_a_cited_card_id_that_cannot_be_looked_up_is_none_and_never_raises( receipts ):
    assert gate.approval_card_id( receipts ) is None


# ── the gate clause, pure ───────────────────────────────────────────────────

@pytest.fixture
def settings( monkeypatch ):
    """Enforcement is on, held in memory. The fleet INI is never read."""
    handle = SettingsHandle()
    monkeypatch.setattr( approval, "get_approver_accounts", lambda: { MARIA_EMAIL: "maria" } )
    handle.write_text( '{"approvers": ["maria", "mr radio"], "enforcement_active": true}' )
    return handle


def test_the_gate_lets_a_manager_un_park_to_queued_when_the_card_fact_is_true( settings ):
    """The positive control for the gate refusals below."""
    assert approval.refusal_for_admission( "parked", "queued", MANAGER, None, closer_is_manager=True, unpark_card_ok=True ) is None


def test_the_gate_still_refuses_the_same_move_when_the_card_fact_is_false( settings ):
    refusal = approval.refusal_for_admission( "parked", "queued", MANAGER, None, closer_is_manager=True, unpark_card_ok=False )
    assert refusal is not None and "un-parking a row out of" in refusal


def test_the_gate_refuses_a_worker_whatever_the_card_fact_says( settings ):
    refusal = approval.refusal_for_admission( "parked", "queued", WORKER, None, closer_is_manager=False, unpark_card_ok=True )
    assert refusal is not None and "un-parking a row out of" in refusal


def test_the_gate_keeps_the_default_so_every_old_caller_is_unchanged( settings ):
    refusal = approval.refusal_for_admission( "parked", "queued", MANAGER, None, closer_is_manager=True )
    assert refusal is not None and "un-parking a row out of" in refusal


@pytest.mark.parametrize( "destination", [ "in_progress", "done", "blocked" ] )
def test_the_receipt_covers_queued_only_so_other_moves_out_of_a_park_stay_refused( settings, destination ):
    refusal = approval.refusal_for_admission( "parked", destination, MANAGER, None, closer_is_manager=True, unpark_card_ok=True )
    assert refusal is not None


def test_the_receipt_does_not_open_a_promote_or_a_demote( settings ):
    promote = approval.refusal_for_admission( "not_approved", "queued", MANAGER, None, closer_is_manager=True, unpark_card_ok=True )
    demote  = approval.refusal_for_admission( "queued", "not_approved", MANAGER, None, closer_is_manager=True, unpark_card_ok=True )
    assert promote is not None and demote is not None


# ── the receipt key and the repository's single-use read ────────────────────

def test_the_approval_card_key_is_whitelisted_and_must_be_a_canonical_uuid():
    assert rules.APPROVAL_CARD_KEY in rules.RECEIPT_KEY_WHITELIST
    assert rules.validate_receipt_refs( { "approval_card": str( ROW_ID ) } ) == [ ]
    assert rules.validate_receipt_refs( { "approval_card": "NOT-A-UUID" } ) != [ ]


def test_the_approval_card_key_does_not_close_a_row():
    assert rules.APPROVAL_CARD_KEY not in rules.CLOSING_RECEIPT_KEYS


def test_the_single_use_read_asks_for_the_events_that_carry_the_card():
    session = MagicMock()
    query   = session.query.return_value
    query.filter.return_value = query
    query.scalar.return_value = 1
    card_id = uuid.uuid4()
    assert TaskRepository( session ).approval_card_ids_used( card_id ) == { str( card_id ) }
    where = query.filter.call_args.args[ 0 ].compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } )
    assert "receipt_refs ->> 'approval_card'" in str( where ) and str( card_id ) in str( where )


def test_the_single_use_read_returns_nothing_for_a_card_no_event_names():
    session = MagicMock()
    query   = session.query.return_value
    query.filter.return_value = query
    query.scalar.return_value = None
    assert TaskRepository( session ).approval_card_ids_used( uuid.uuid4() ) == set()


# ── the transition door, over HTTP ──────────────────────────────────────────

def _item( **overrides ):
    fields = dict(
        id=ROW_ID, item_class="task", title="a parked row Rick has approved", body=None, project="lupin",
        owner_persona="sam", accountable_manager="mr radio", created_by=MANAGER, status="parked",
        blocked_by=[ ], next_chase_ts=CARD_MADE_AT + timedelta( days = 1 ), gate_class="none", priority="P1",
        source_qid=None, correlation_key=None, created_ts=PARKED_AT, updated_ts=PARKED_AT, title_trimmed=False,
        park_reason="not now", park_reason_captured_at=PARKED_AT,
    )
    fields.update( overrides )
    return TaskItem( **fields )


class _Cards:
    """The notification table, as a dict, behind the one `get_by_id` the door calls."""

    def __init__( self ): self.rows = { }

    def add( self, card ):
        self.rows[ card.id ] = card
        return card

    def __call__( self, session ): return self

    def get_by_id( self, card_id ): return self.rows.get( card_id )


@pytest.fixture
def cards( monkeypatch ):
    table = _Cards()
    monkeypatch.setattr( tasks, "NotificationRepository", table )
    return table


@pytest.fixture
def repo( monkeypatch ):
    fake = MagicMock()
    fake.statuses_for_ids.return_value      = { }
    fake.approval_card_ids_used.return_value = set()

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def seats( monkeypatch ):
    monkeypatch.setattr( tasks, "is_manager_figure", lambda session_id, *a, **k: session_id == MANAGER_SID )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda session_id, *a, **k: DENIAL_DENIED )
    monkeypatch.setattr( tasks, "get_voice_persona", lambda session_id: { "name": "Mr. Radio" } if session_id == MANAGER_SID else None )


def _armed( repo, item ):
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, item=item, ts=CARD_MADE_AT, actor=MANAGER,
        transition=f"{item.status}->queued", receipt_refs=None, authority="standing",
    )


def _post( item, to_status, actor, **extra ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: None
    body = { "to_status": to_status, "actor": actor }
    body.update( extra )
    return TestClient( app ).post( f"/api/tasks/{item.id}/transition", json=body )


def _unpark( item, card, actor=MANAGER, to_status="queued" ):
    return _post( item, to_status, actor, receipt_refs={ "approval_card": str( card.id ) } if card is not None else { "approval_card": str( uuid.uuid4() ) } )


def test_a_manager_citing_a_valid_card_un_parks_the_row_and_the_card_id_lands_on_the_event( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )

    response = _unpark( item, card )

    assert response.status_code == 200, response.text
    recorded = repo.apply_transition.call_args.kwargs[ "receipt_refs" ]
    assert recorded[ "approval_card" ] == str( card.id )
    assert repo.apply_transition.call_args.kwargs[ "to_status" ] == "queued"


def test_the_servers_resolved_card_id_replaces_whatever_the_caller_typed( repo, settings, seats, cards, monkeypatch ):
    """A seam pins the overwrite, since a valid typed id equals the resolved one."""
    item = _item()
    _armed( repo, item )
    typed, resolved = cards.add( _card() ), uuid.uuid4()
    monkeypatch.setattr( tasks, "_resolved_unpark_card", lambda session, repo, item, receipts: resolved )

    assert _unpark( item, typed ).status_code == 200
    assert repo.apply_transition.call_args.kwargs[ "receipt_refs" ][ "approval_card" ] == str( resolved )


def test_a_manager_citing_a_card_id_that_exists_nowhere_is_refused_and_the_row_stays_parked( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )

    response = _unpark( item, None )

    assert response.status_code == 403 and "No card with that id exists" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_citing_a_card_made_for_another_row_is_refused( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )
    card = cards.add( _card( payload=gate.unpark_ask_payload( OTHER_ROW_ID ) ) )

    response = _unpark( item, card )

    assert response.status_code == 403 and "not made by the server for this row" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_citing_a_card_a_second_time_is_refused( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )
    repo.approval_card_ids_used.return_value = { str( card.id ) }

    response = _unpark( item, card )

    assert response.status_code == 403 and "already been used" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_worker_citing_a_valid_card_is_still_refused( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )

    response = _unpark( item, card, actor=WORKER )

    assert response.status_code == 403 and "belongs to a manager's un-park" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_workers_own_un_park_with_enforcement_off_does_not_write_the_card_id( repo, settings, seats, cards ):
    """With the gate off the move is lawful, but a typed card id must never reach an event."""
    settings.write_text( '{"approvers": ["maria", "mr radio"], "enforcement_active": false}' )
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )

    response = _unpark( item, card, actor=WORKER )

    assert response.status_code == 403 and "belongs to a manager's un-park" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_workers_plain_un_park_with_enforcement_off_still_moves_the_row( repo, settings, seats, cards ):
    """The control for the test above: the refusal is about the card id, not the move."""
    settings.write_text( '{"approvers": ["maria", "mr radio"], "enforcement_active": false}' )
    item = _item()
    _armed( repo, item )

    response = _post( item, "queued", WORKER )

    assert response.status_code == 200, response.text
    assert "approval_card" not in ( repo.apply_transition.call_args.kwargs[ "receipt_refs" ] or { } )


def test_a_manager_citing_a_card_on_parked_to_in_progress_is_refused_by_the_receipt_rule( repo, settings, seats, cards ):
    """Without the destination half of the claim, the card is judged first."""
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )

    response = _post( item, "in_progress", MANAGER, receipt_refs={ "approval_card": str( card.id ) } )

    assert response.status_code == 403 and "belongs to a manager's un-park" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_without_any_receipt_is_refused_as_before( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )

    response = _post( item, "queued", MANAGER )

    assert response.status_code == 403 and "un-parking a row out of" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


@pytest.mark.parametrize( "destination", [ "in_progress", "done" ] )
def test_a_valid_card_does_not_open_the_other_moves_out_of_a_park( repo, settings, seats, cards, destination ):
    item = _item()
    _armed( repo, item )
    card = cards.add( _card() )

    response = _unpark( item, card, to_status=destination )

    assert response.status_code in ( 403, 422 ), response.text
    repo.apply_transition.assert_not_called()


def test_a_malformed_card_id_is_rejected_before_any_lookup( repo, settings, seats, cards ):
    item = _item()
    _armed( repo, item )

    response = _post( item, "queued", MANAGER, receipt_refs={ "approval_card": "not-a-uuid" } )

    assert response.status_code == 422
    repo.apply_transition.assert_not_called()


def test_a_card_id_the_server_cannot_parse_is_refused_by_the_helper( repo, settings, seats, cards, monkeypatch ):
    """The validator stops a malformed id first; the helper keeps its own refusal."""
    item = _item()
    with pytest.raises( tasks.HTTPException ) as raised:
        tasks._resolved_unpark_card( MagicMock(), repo, item, { "approval_card": "not-a-uuid" } )
    assert raised.value.status_code == 403 and "not a card id" in raised.value.detail


# ── the door: a card id is not a thing to type on other moves ───────────────

def test_a_card_id_typed_on_an_ordinary_move_is_refused_and_burns_nothing( repo, settings, seats, cards ):
    """Finding 1: a worker moving a row queued to in_progress with someone's real card id."""
    item = _item( status="queued" )
    _armed( repo, item )
    card = cards.add( _card() )

    response = _post( item, "in_progress", WORKER, receipt_refs={ "approval_card": str( card.id ) } )

    assert response.status_code == 403 and "belongs to a manager's un-park" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_manager_citing_a_card_on_a_row_that_is_not_parked_is_refused_by_the_receipt_rule( repo, settings, seats, cards ):
    """Finding 3a: no card is looked up, and no card sentence comes back."""
    item = _item( status="blocked", next_chase_ts=None )
    _armed( repo, item )
    card = cards.add( _card() )

    response = _post( item, "queued", MANAGER, receipt_refs={ "approval_card": str( card.id ) } )

    assert response.status_code == 403 and "belongs to a manager's un-park" in response.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_worker_hears_the_same_refusal_for_a_real_card_and_a_made_up_one( repo, settings, seats, cards ):
    """Finding 3b: a worker must not learn whether a card id exists or who answered it."""
    item = _item()
    _armed( repo, item )
    real = cards.add( _card() )

    on_real = _unpark( item, real, actor=WORKER )
    on_fake = _unpark( item, None, actor=WORKER )

    assert on_real.status_code == on_fake.status_code == 403
    assert on_real.json()[ "detail" ] == on_fake.json()[ "detail" ]
    assert "belongs to a manager's un-park" in on_real.json()[ "detail" ]


def test_the_single_use_read_counts_only_un_park_events():
    session = MagicMock()
    query   = session.query.return_value
    query.filter.return_value = query
    query.scalar.return_value = 0
    TaskRepository( session ).approval_card_ids_used( uuid.uuid4() )
    filters = [ str( call.args[ 0 ].compile( dialect=postgresql.dialect(), compile_kwargs={ "literal_binds": True } ) ) for call in query.filter.call_args_list ]
    assert any( "task_events.transition = 'parked->queued'" in text for text in filters ), filters


# ── the binding rests on one fact: no public door writes a payload on a question ──

def _create_notification_calls_that_pass_a_payload():
    """Files under src/cosa that call create_notification with a payload keyword, found by AST."""
    import ast
    root   = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src", "cosa" )
    found  = set()
    walked = 0
    for folder, dirs, names in os.walk( root ):
        dirs[ : ] = [ d for d in dirs if d not in ( ".venv", "node_modules", "__pycache__", "tests" ) ]
        for name in names:
            if not name.endswith( ".py" ): continue
            walked += 1
            path = os.path.join( folder, name )
            tree = ast.parse( open( path, encoding="utf-8" ).read() )
            for node in ast.walk( tree ):
                if isinstance( node, ast.Call ) and getattr( node.func, "attr", None ) == "create_notification":
                    if any( k.arg == "payload" for k in node.keywords ):
                        found.add( os.path.relpath( path, root ) )
    return found, walked


def test_the_files_that_write_a_notification_payload_are_pinned():
    found, walked = _create_notification_calls_that_pass_a_payload()
    assert walked > 200, "the sweep found too few files to mean anything"
    assert found == { "rest/commons_ack_watcher.py" }, found


def test_the_payload_guard_would_notice_a_call_that_passes_one( tmp_path ):
    """The instrument finds a positive: the same walk over a planted file."""
    import ast
    planted = ast.parse( "repo.create_notification( message='x', payload={ 'kind': 'unpark_ask' } )" )
    assert any( isinstance( n, ast.Call ) and any( k.arg == "payload" for k in n.keywords ) for n in ast.walk( planted ) )
