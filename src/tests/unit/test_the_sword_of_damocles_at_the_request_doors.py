"""
THE SWORD OF DAMOCLES, DRIVEN THROUGH BOTH REQUEST DOORS — row ab8c5728, plan steps 4 and 5.

Rick, 2026-09-14 ~22:32 EDT: "if you're asking to add 1 the method for requesting 1 of me then
requires that you pass in A ticket ID that belongs to you". Rulings: no peer agreement (Q1);
approve admits AND drops in one transaction, deny touches nothing, a dead pledge is 409 and
may be re-filed (Q2); demote is exempt (Q3); the requester's persona comes from the server,
never the typed actor (María, 22:41). Plan: src/rnd/2026.09.14-sword-of-damocles-enforcement-plan.md.

WHAT IS REAL
------------
The router, both doors, `refusal_for_pledge` / `refusal_for_consuming_pledge`, the switch
reader, `_apply_transition_under_lock`, and the repository writes `apply_request_filing`,
`apply_request_verdict` and `apply_transition`, all over ONE recording session per arm.

WHAT IS FAKE
------------
The database session; the manager bridge and the persona bridge (each arm names who a session
is, and the default is NOBODY, so a forgotten arm is refused rather than passing); and the
repository READS, over a small in-memory store. The reads that decide a rule —
`find_pending_admit_pledging`, `peek_request_deletion_id`, `statuses_for_ids` — are computed
from the store's rows and their arguments, so a door passing the wrong id gets the wrong answer.
"""
import json
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
OTHER_MANAGER  = "maria ee680ab6"
NOW            = datetime( 2026, 9, 15, 0, 0, tzinfo=timezone.utc )

FILE_PATH    = "/api/tasks/{task_id}/request"
VERDICT_PATH = "/api/tasks/{task_id}/request-verdict"

LOW_ID  = uuid.UUID( "00000000-0000-4000-8000-000000000001" )
HIGH_ID = uuid.UUID( "ffffffff-ffff-4fff-bfff-ffffffffffff" )


class _Store:
    """Several rows, one recording session, the lock order, and any rolled-back request."""
    def __init__( self ):
        self.rows        = { }
        self.added       = [ ]
        self.rolled_back = [ ]
        self.locked      = [ ]

    def put( self, item ):
        self.rows[ item.id ] = item
        return item


def _item( status=approval.NOT_APPROVED_STATUS, owner="mr radio", id=None, **overrides ):
    fields = dict(
        id = id or uuid.uuid4(), item_class = "task", title = "a row", body = None,
        project = "lupin", owner_persona = owner, accountable_manager = "mr radio",
        created_by = MANAGER, status = status, priority = "P2", urgency = "normal",
        blocked_by = [ ], created_ts = NOW, updated_ts = NOW,
        request_state = None, request_move = None, request_ts = None, request_deletion_id = None,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def app():
    a = FastAPI()
    a.include_router( tasks.router )
    return a


@pytest.fixture
def switch( monkeypatch, tmp_path ):
    """
    Rick on the operator account in a TEMP settings file, with the Sword switch set per arm
    through the real override reader — `switch( True )` writes the key, it does not stub it.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "get_enforcement_active", lambda: True )

    def _set( on ):
        target.write_text( json.dumps( {
            "approvers"                : [ "rick" ],
            "approver_accounts"        : { OPERATOR_EMAIL: "rick" },
            "sword_of_damocles_active" : on,
        } ) )
        approval._cache_mtime = None
    _set( True )
    return _set


@pytest.fixture
def seats( monkeypatch ):
    """Manager seats and the persona each session resolves to. Both start EMPTY."""
    managers = set()
    personas = { }
    monkeypatch.setattr( tasks, "is_manager_figure", lambda sid: sid in managers )
    monkeypatch.setattr( tasks, "classify_manager_figure_denial", lambda sid: "denied" )
    monkeypatch.setattr( tasks, "get_voice_persona", lambda sid: { "name": personas[ sid ] } if sid in personas else None )

    def _no_ask( **kwargs ):
        raise AssertionError( "the promotion ask fired for Rick's own approval — he is ask-exempt" )
    real_approval = gate.approval_for_promotion
    monkeypatch.setattr( gate, "approval_for_promotion", lambda **k: real_approval( **{ **k, "ask_fn": _no_ask } ) )

    def _seat( actor, persona ):
        sid = rules.session_id_from_created_by( actor )
        managers.add( sid )
        if persona is not None: personas[ sid ] = persona
    return _seat


@pytest.fixture
def store( monkeypatch ):
    s       = _Store()
    session = MagicMock()

    def _add( obj ):
        if getattr( obj, "ts", None ) is None: obj.ts = NOW
        # The flush's relationship load: an event serializes its row's title.
        if getattr( obj, "item", None ) is None: obj.item = s.rows.get( obj.item_id )
        s.added.append( obj )
    session.add.side_effect = _add
    session.execute.return_value.scalar_one.return_value = NOW

    @contextmanager
    def _fake_get_db():
        try:
            yield session
        except Exception as e:
            s.rolled_back.append( e )
            raise

    def _lock( row_id ):
        s.locked.append( row_id )
        return s.rows.get( row_id )

    def _pending_admit_pledging( pledge_id, excluding_id ):
        for row in s.rows.values():
            if ( row.request_deletion_id == pledge_id and row.request_state == lifecycle.REQUEST_PENDING
                 and row.request_move == approval.MOVE_ADMIT and row.id != excluding_id ):
                return row.id
        return None

    def _statuses( ids ):
        return { i: ( s.rows[ uuid.UUID( i ) ].status if uuid.UUID( i ) in s.rows else None ) for i in ids }

    real = RealTaskRepository( session )
    repo = MagicMock()
    repo.get_by_id_for_update.side_effect        = _lock
    repo.peek_request_deletion_id.side_effect    = lambda row_id: s.rows[ row_id ].request_deletion_id if row_id in s.rows else None
    repo.find_pending_admit_pledging.side_effect = _pending_admit_pledging
    repo.statuses_for_ids.side_effect            = _statuses
    repo.count_admissions_since.return_value     = 0
    repo.apply_request_filing.side_effect        = real.apply_request_filing
    repo.apply_request_verdict.side_effect       = real.apply_request_verdict
    repo.apply_transition.side_effect            = real.apply_transition

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda sess: repo )
    s.repo = repo
    return s


def _client( app, account_email=None ):
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _file( app, target, move=approval.MOVE_ADMIT, pledge=None, actor=MANAGER, account_email=None ):
    body = { "move": move, "reason": "ready to work", "actor": actor }
    if pledge is not None: body[ "deletion_task_id" ] = str( pledge )
    return _client( app, account_email ).post( FILE_PATH.format( task_id=target.id ), json=body )


def _verdict( app, target, verdict ):
    return _client( app, OPERATOR_EMAIL ).post( VERDICT_PATH.format( task_id=target.id ), json={ "verdict": verdict } )


def _transitions( store ):
    return [ e.transition for e in store.added ]


# ---------------------------------------------------------------------------
# THE FILING DOOR
# ---------------------------------------------------------------------------

def test_with_the_switch_ON_an_admit_without_a_pledge_is_refused_and_names_the_setting( app, switch, seats, store ):
    """AC1. The refusal says what to send and which switch Rick turns it off with."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )

    response = _file( app, target )

    assert response.status_code == 422, response.text
    assert "deletion_task_id" in response.json()[ "detail" ]
    assert "sword_of_damocles_active" in response.json()[ "detail" ]
    assert target.request_state is None and store.added == [ ]


def test_with_the_switch_OFF_an_admit_without_a_pledge_is_filed( app, switch, seats, store ):
    """The same request, switch flipped through the real override file: accepted."""
    switch( False )
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )

    response = _file( app, target )

    assert response.status_code == 200, response.text
    assert target.request_state == lifecycle.REQUEST_PENDING
    assert target.request_deletion_id is None


def test_a_valid_pledge_is_stored_named_in_the_event_and_the_pledged_row_does_not_move( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item( owner="pocholo" ) )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )

    response = _file( app, target, pledge=pledge.id )

    assert response.status_code == 200, response.text
    assert target.request_deletion_id == pledge.id
    assert response.json()[ "request_deletion_id" ] == str( pledge.id )
    assert pledge.status == "queued", "filing a request moved the pledged row"
    assert _transitions( store ) == [ "request_filed" ]
    assert f"pledged for deletion: {pledge.id}" in store.added[ 0 ].reason


def test_a_demote_that_names_a_pledge_is_refused( app, switch, seats, store ):
    """Q3: demote is exempt, so a pledge on one is refused rather than silently ignored."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item( status="queued" ) )
    pledge = store.put( _item( status="queued" ) )

    response = _file( app, target, move=approval.MOVE_DEMOTE, pledge=pledge.id )

    assert response.status_code == 422, response.text
    assert "demote" in response.json()[ "detail" ]


def test_a_demote_without_a_pledge_is_filed_with_the_switch_on( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item( status="queued" ) )

    assert _file( app, target, move=approval.MOVE_DEMOTE ).status_code == 200


def test_a_row_cannot_pledge_itself( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )

    response = _file( app, target, pledge=target.id )

    assert response.status_code == 422, response.text
    assert "itself" in response.json()[ "detail" ]
    assert store.locked == [ target.id ], "a self-pledge took the same lock twice"


def test_a_pledge_that_does_not_exist_is_refused_naming_its_id( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target  = store.put( _item() )
    missing = uuid.uuid4()

    response = _file( app, target, pledge=missing )

    assert response.status_code == 422, response.text
    assert str( missing ) in response.json()[ "detail" ]


def test_a_pledge_owned_by_someone_else_is_refused_403( app, switch, seats, store ):
    """ "It better be yours." """
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="maria" ) )

    response = _file( app, target, pledge=pledge.id )

    assert response.status_code == 403, response.text
    assert "maria" in response.json()[ "detail" ]
    assert target.request_state is None


def test_an_unresolvable_persona_is_refused_even_when_the_typed_actor_names_the_owner( app, switch, seats, store ):
    """
    🔴 THE HOLE THIS CLOSES (row b8205986). The actor string says "mr radio" and the pledge is
    Mr. Radio's, but the bridge resolves nobody for that session — so the door refuses.
    """
    seats( MANAGER, None )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )

    response = _file( app, target, pledge=pledge.id )

    assert response.status_code == 403, response.text
    assert "session bridge" in response.json()[ "detail" ]


def test_the_persona_is_the_BRIDGE_answer_not_the_typed_name( app, switch, seats, store ):
    """The typed actor claims Mr. Radio; the bridge says María owns this session. María's pledge passes."""
    seats( MANAGER, "maria" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="maria" ) )

    assert _file( app, target, pledge=pledge.id ).status_code == 200


def test_a_logged_in_operator_is_resolved_from_the_ACCOUNT( app, switch, seats, store ):
    """Rick on his own account passes the manager check there, and his persona comes from it."""
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="rick" ) )

    response = _file( app, target, pledge=pledge.id, actor="rick host", account_email=OPERATOR_EMAIL )

    assert response.status_code == 200, response.text


def test_an_actor_with_no_session_id_resolves_no_persona( app, switch, seats, store, monkeypatch ):
    """The manager check is stood in for, so the arm reaches the persona lookup with no session id."""
    monkeypatch.setattr( gate, "manager_refusal", lambda *a, **k: None )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )

    response = _file( app, target, pledge=pledge.id, actor="mr radio" )

    assert response.status_code == 403, response.text
    assert "session bridge" in response.json()[ "detail" ]


@pytest.mark.parametrize( "terminal", [ "done", "dropped", "wont_fix" ] )
def test_a_finished_pledge_is_refused_409( app, switch, seats, store, terminal ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status=terminal, owner="mr radio" ) )

    response = _file( app, target, pledge=pledge.id )

    assert response.status_code == 409, response.text
    assert terminal in response.json()[ "detail" ]


def test_a_pledge_already_on_another_pending_admit_is_refused_naming_that_row( app, switch, seats, store ):
    """One pledge pays for one admit — the second request sees the first under the pledge's lock."""
    seats( MANAGER, "mr radio" )
    first  = store.put( _item() )
    second = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )

    assert _file( app, first, pledge=pledge.id ).status_code == 200
    response = _file( app, second, pledge=pledge.id )

    assert response.status_code == 409, response.text
    assert str( first.id ) in response.json()[ "detail" ]
    assert second.request_state is None


def test_an_answered_request_does_not_hold_its_pledge( app, switch, seats, store ):
    """A denied request finished; its pledge is free for another admit."""
    seats( MANAGER, "mr radio" )
    first  = store.put( _item() )
    second = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )

    assert _file( app, first, pledge=pledge.id ).status_code == 200
    assert _verdict( app, first, lifecycle.REQUEST_DENIED ).status_code == 200
    assert _file( app, second, pledge=pledge.id ).status_code == 200


@pytest.mark.parametrize( "target_id, pledge_id", [ ( LOW_ID, HIGH_ID ), ( HIGH_ID, LOW_ID ) ] )
def test_the_filing_door_locks_both_rows_lower_id_first( app, switch, seats, store, target_id, pledge_id ):
    """AC5's precondition: one fixed lock order, whichever row is the target."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item( id=target_id ) )
    pledge = store.put( _item( status="queued", owner="mr radio", id=pledge_id ) )

    assert _file( app, target, pledge=pledge.id ).status_code == 200
    assert store.locked == [ LOW_ID, HIGH_ID ]


def test_a_pending_admit_whose_pledge_DIED_may_be_refiled_with_a_live_one( app, switch, seats, store ):
    """Q2: the 409 at the verdict leaves the request pending, so the manager must be able to replace it."""
    seats( MANAGER, "mr radio" )
    target   = store.put( _item() )
    old      = store.put( _item( status="queued", owner="mr radio" ) )
    new      = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=old.id ).status_code == 200

    old.status = "done"
    response   = _file( app, target, pledge=new.id )

    assert response.status_code == 200, response.text
    assert target.request_deletion_id == new.id


def test_a_pending_admit_whose_pledge_is_ALIVE_still_refuses_a_refile( app, switch, seats, store ):
    """The control for the arm above: the one-request-per-row rule is untouched otherwise."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    old    = store.put( _item( status="queued", owner="mr radio" ) )
    new    = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=old.id ).status_code == 200

    response = _file( app, target, pledge=new.id )

    assert response.status_code == 409, response.text
    assert target.request_deletion_id == old.id


def test_a_non_manager_learns_nothing_about_the_pledged_row( app, switch, seats, store ):
    """The manager check runs before the pledge rule, so a worker gets the manager refusal."""
    target = store.put( _item() )
    pledge = store.put( _item( status="done", owner="maria" ) )

    response = _file( app, target, pledge=pledge.id, actor="pocholo 5bd424ca" )

    assert response.status_code == 403, response.text
    assert "maria" not in response.json()[ "detail" ]
    store.repo.find_pending_admit_pledging.assert_not_called()


# ---------------------------------------------------------------------------
# THE VERDICT DOOR
# ---------------------------------------------------------------------------

def test_an_APPROVED_admit_moves_the_row_and_DROPS_the_pledge_in_one_transaction( app, switch, seats, store ):
    """AC4, the arm Q2 exists for."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="in_progress", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    response = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 200, response.text
    assert target.status == "queued"
    assert pledge.status == "dropped"
    assert _transitions( store ) == [ "request_filed", "request_approved", "not_approved->queued", "in_progress->dropped" ]
    drop = store.added[ -1 ]
    assert drop.item_id == pledge.id
    assert str( target.id ) in drop.reason and "Sword of Damocles" in drop.reason
    assert drop.actor.startswith( "rick" ), drop.actor


def test_a_DENIAL_touches_neither_row( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    response = _verdict( app, target, lifecycle.REQUEST_DENIED )

    assert response.status_code == 200, response.text
    assert target.status == approval.NOT_APPROVED_STATUS
    assert pledge.status == "queued"
    assert _transitions( store ) == [ "request_filed", "request_denied" ]


def test_an_approval_over_a_pledge_that_died_is_409_and_writes_nothing( app, switch, seats, store ):
    """The pledge was closed after filing: nothing is admitted, and the request stays pending."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    pledge.status = "done"
    response      = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 409, response.text
    assert "stays pending" in response.json()[ "detail" ]
    assert target.request_state == lifecycle.REQUEST_PENDING
    assert target.status == approval.NOT_APPROVED_STATUS
    assert _transitions( store ) == [ "request_filed" ]


def test_an_approval_over_a_pledge_that_no_longer_EXISTS_is_409( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    del store.rows[ pledge.id ]
    response = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 409, response.text
    assert "no longer exists" in response.json()[ "detail" ]


def test_a_refusal_on_the_DROP_rolls_back_the_admit_with_it( app, switch, seats, store, monkeypatch ):
    """
    🔴 BOTH OR NEITHER. The refusal is injected on the drop alone — the admit's transition to
    queued is let through — so the arm proves the drop's refusal leaves the door, which is
    what makes `get_db` roll the whole transaction back.
    """
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    real_validate = rules.validate_transition
    def _refuse_the_drop( from_status, to_status, *a, **k ):
        if to_status == "dropped": return [ "an injected refusal on the drop" ]
        return real_validate( from_status, to_status, *a, **k )
    monkeypatch.setattr( rules, "validate_transition", _refuse_the_drop )

    response = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 422, response.text
    assert "an injected refusal on the drop" in response.text
    assert len( store.rolled_back ) == 1, "the refused drop did not roll back the transaction"
    assert "in_progress->dropped" not in _transitions( store ) and "queued->dropped" not in _transitions( store )


def test_a_grandfathered_admit_with_no_pledge_is_admitted_alone( app, switch, seats, store ):
    """Filed while the switch was off; approved after it went on. María, 22:41: grandfathered."""
    switch( False )
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    assert _file( app, target ).status_code == 200

    switch( True )
    response = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 200, response.text
    assert target.status == "queued"
    assert _transitions( store ) == [ "request_filed", "request_approved", "not_approved->queued" ]


def test_a_request_re_filed_between_the_peek_and_the_lock_is_refused_409( app, switch, seats, store ):
    """The verdict would otherwise answer a request whose pledge Rick was never shown."""
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    store.repo.peek_request_deletion_id.side_effect = lambda row_id: None
    response = _verdict( app, target, lifecycle.REQUEST_APPROVED )

    assert response.status_code == 409, response.text
    assert "re-filed" in response.json()[ "detail" ]
    assert target.status == approval.NOT_APPROVED_STATUS


@pytest.mark.parametrize( "target_id, pledge_id", [ ( LOW_ID, HIGH_ID ), ( HIGH_ID, LOW_ID ) ] )
def test_the_verdict_door_locks_both_rows_in_the_filing_doors_order( app, switch, seats, store, target_id, pledge_id ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item( id=target_id ) )
    pledge = store.put( _item( status="queued", owner="mr radio", id=pledge_id ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    store.locked.clear()
    assert _verdict( app, target, lifecycle.REQUEST_APPROVED ).status_code == 200
    assert store.locked[ :2 ] == [ LOW_ID, HIGH_ID ]


def test_a_non_operator_verdict_is_refused_before_any_pledge_is_consumed( app, switch, seats, store ):
    seats( MANAGER, "mr radio" )
    target = store.put( _item() )
    pledge = store.put( _item( status="queued", owner="mr radio" ) )
    assert _file( app, target, pledge=pledge.id ).status_code == 200

    response = _client( app, None ).post( VERDICT_PATH.format( task_id=target.id ), json={ "verdict": "approved" } )

    assert response.status_code == 403, response.text
    assert pledge.status == "queued"
