#!/usr/bin/env python3
"""
The one-click promote-to-P0 move, entered at the door a click enters at.

A held row is admitted to queued at P0 by one POST to /api/tasks/{id}/transition carrying
`promote_priority: "P0"`. Only the validated login mapped to the operator may do it. These
tests drive the real handler over HTTP against a mocked repository, the harness shape
`test_the_transition_door_calls_the_approval_gate.py` uses.

The named guard for the login check is `test_an_api_key_caller_is_refused_and_the_row_is_unchanged`
together with `test_another_approver_login_is_refused_and_the_row_is_unchanged`: delete the
`refusal_for_promote_p0` call in `transition_task` and both redden.
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
from cosa.rest import task_priority_firewall as firewall
from tests.helpers.approval_settings_fixtures import SettingsHandle
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW          = datetime( 2026, 11, 3, 0, 0, tzinfo=timezone.utc )
RICK_EMAIL   = "rick@example.com"
MARIA_EMAIL  = "maria@example.com"
_who         = { "email": None }


def _item( **overrides ):
    fields = dict(
        id=uuid.uuid4(), item_class="task", title="a held remediation row", body=None, project="lupin",
        owner_persona="rachel", accountable_manager="mr radio", created_by="rachel 17108a16",
        status="not_approved", blocked_by=[ ], next_chase_ts=None, gate_class="none", priority="P1",
        source_qid=None, correlation_key=None, created_ts=NOW, updated_ts=NOW, title_trimmed=False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """The router's db seams, faked."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo, monkeypatch ):
    """
    Stand down the manager-figure leg and the promotion ask.

    Neither is this file's subject. The login is real: it rides the account seam, where a validated token puts it.
    """
    from cosa.rest.task_promotion_gate import PromotionApproval
    monkeypatch.setattr( tasks.promotion_gate, "approval_for_promotion",
                         lambda *a, **k: PromotionApproval( allowed=True, approval_source="stubbed-for-this-file" ) )
    app = FastAPI()
    app.include_router( tasks.router )
    _who[ "email" ] = None
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.dependency_overrides[ tasks.authenticated_account_email ] = lambda: _who[ "email" ]
    return TestClient( app )


@pytest.fixture
def settings():
    """Rick and Maria are approvers; each has a login. Enforcement is forced on inside the test."""
    handle = SettingsHandle()
    handle.write_text( json.dumps( {
        "approvers": [ "rick", "maria" ], "enforcement_active": True,
        "approver_accounts": { RICK_EMAIL: "rick", MARIA_EMAIL: "maria" },
    } ) )
    return handle


def _event( item, actor ):
    return TaskEvent( id=1, item_id=item.id, item=item, ts=NOW, actor=actor,
                      transition="not_approved->queued", receipt_refs=None, authority="user_direct" )


def _post( client, item, to_status="queued", actor="operator approve-link", **extra ):
    body = { "to_status": to_status, "actor": actor, "authority": "user_direct" }
    body.update( extra )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


def test_a_Rick_login_admits_the_row_at_P0_in_one_store_event( client, repo, settings ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    seen = { }

    def _apply( **kw ):
        # The priority is already P0 at the moment the single event is appended.
        seen[ "priority_at_event" ] = kw[ "item" ].priority
        seen[ "kw" ]                = kw
        return _event( item, kw[ "actor" ] )

    repo.apply_transition.side_effect = _apply
    _who[ "email" ] = RICK_EMAIL

    r = _post( client, item, promote_priority="P0" )

    assert r.status_code == 200, r.text
    repo.apply_transition.assert_called_once()
    assert seen[ "priority_at_event" ] == "P0"
    assert item.priority == "P0"
    assert seen[ "kw" ][ "to_status" ] == "queued"
    assert seen[ "kw" ][ "authority" ] == "user_direct"
    assert "promoted to P0 (was P1)" in seen[ "kw" ][ "reason" ]
    assert "rick" in seen[ "kw" ][ "reason" ]


def test_a_Rick_approve_without_the_flag_leaves_the_priority_alone( client, repo, settings ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item, "rick" )
    _who[ "email" ] = RICK_EMAIL

    r = _post( client, item )

    assert r.status_code == 200, r.text
    assert item.priority == "P1"
    assert "promoted to" not in ( repo.apply_transition.call_args.kwargs[ "reason" ] or "" )


def test_the_operator_reason_is_kept_after_the_promotion_words( client, repo, settings ):
    item = _item( priority="P2" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item, "rick" )
    _who[ "email" ] = RICK_EMAIL

    r = _post( client, item, promote_priority="P0", reason="urgent fix" )

    assert r.status_code == 200, r.text
    reason = repo.apply_transition.call_args.kwargs[ "reason" ]
    assert reason.startswith( "promoted to P0 (was P2)" ) and "urgent fix" in reason


def test_an_api_key_caller_is_refused_and_the_row_is_unchanged( client, repo, settings ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    _who[ "email" ] = None

    r = _post( client, item, actor="rick 12345678", promote_priority="P0" )   # a typed "rick" confers nothing

    assert r.status_code == 403, r.text
    assert "only for Rick's login" in r.json()[ "detail" ] and "API key" in r.json()[ "detail" ]
    assert item.priority == "P1" and item.status == "not_approved"
    repo.apply_transition.assert_not_called()


def test_another_approver_login_is_refused_and_the_row_is_unchanged( client, repo, settings ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    _who[ "email" ] = MARIA_EMAIL            # an approver, but not the operator

    r = _post( client, item, promote_priority="P0" )

    assert r.status_code == 403, r.text
    assert "only for Rick's login" in r.json()[ "detail" ] and MARIA_EMAIL in r.json()[ "detail" ]
    assert item.priority == "P1" and item.status == "not_approved"
    repo.apply_transition.assert_not_called()


@pytest.mark.parametrize( "from_status, to_status, value", [
    ( "queued",       "in_progress", "P0" ),    # not a held row
    ( "not_approved", "dropped", "P0" ),    # not an admission
    ( "not_approved", "queued",  "P1" ),    # not P0
] )
def test_Rick_on_any_other_move_is_refused_and_the_row_is_unchanged( client, repo, settings, from_status, to_status, value ):
    item = _item( status=from_status, priority="P2" )
    repo.get_by_id_for_update.return_value = item
    _who[ "email" ] = RICK_EMAIL

    r = _post( client, item, to_status, promote_priority=value, reason="x" )

    assert r.status_code == 403, r.text
    assert "only the move not_approved -> queued" in r.json()[ "detail" ]
    assert item.priority == "P2" and item.status == from_status
    repo.apply_transition.assert_not_called()


def test_the_pure_gate_says_nothing_without_the_flag_and_never_raises_on_odd_accounts( settings ):
    assert firewall.refusal_for_promote_p0( None, "not_approved", "queued", None ) is None
    assert firewall.refusal_for_promote_p0( "P0", "not_approved", "queued", RICK_EMAIL ) is None
    for odd in ( None, "", "   ", 7 ):
        assert "API key" in firewall.refusal_for_promote_p0( "P0", "not_approved", "queued", odd )


def test_with_enforcement_off_the_event_reason_is_just_the_promotion_words( client, repo, settings ):
    settings.write_text( json.dumps( { "approvers": [ "rick" ], "enforcement_active": False,
                                       "approver_accounts": { RICK_EMAIL: "rick" } } ) )
    item = _item( priority="P3" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = _event( item, "rick" )
    _who[ "email" ] = RICK_EMAIL

    r = _post( client, item, promote_priority="P0" )

    assert r.status_code == 200, r.text
    assert repo.apply_transition.call_args.kwargs[ "reason" ] == "promoted to P0 (was P3) by the operator login rick"
