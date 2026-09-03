#!/usr/bin/env python3
"""
THE APPROVAL GATE'S WIRING, ENTERED AT THE LAYER A CALLER ENTERS AT.

`test_task_approval_gate.py` proves the PREDICATE refuses — 39 tests over
`refusal_for_admission` — and one of them proves the router IMPORTS the module.
Neither can see a revert of the CALL SITE inside `transition_task`:

  - `tasks_router.approval is approval` stays true, because `approval` is ALSO used
    at `tasks.py:775` for `default_mint_status`. A wiring revert leaves that import.
  - the mounted-route leg looks for a **PATCH** task route. The transition door is
    **POST** `/tasks/{task_id}/transition`; the PATCH routes it finds are the edit
    door and the flow-ratio settings door. It is checking a different door.

Measured 2026-09-02 at `04bd6bb3`: deleting the gate's seven lines from
`transition_task` reddened NOTHING across the whole unit tier. These tests are what
reddens.

They drive the REAL handler over HTTP against a mocked repository — the same harness
shape `test_tasks_router.py` uses — because a request is where the incident would
enter. Enforcement is forced ON **inside the test**, never in `lupin-app.ini`:
putting the gate into service is outward-facing and Rick's word alone, and a test
must not make that call on his behalf.
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
from cosa.rest.postgres_models import TaskItem, TaskEvent
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

NOW          = datetime( 2026, 9, 2, 0, 0, tzinfo=timezone.utc )
APPROVER     = "maria 611e3c47"
NON_APPROVER = "somebody else 9999"


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "rachel",
        accountable_manager = "mr radio",
        created_by          = "rachel 17108a16",
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P2",
        source_qid          = None,
        correlation_key     = None,
        created_ts          = NOW,
        updated_ts          = NOW,
        title_trimmed       = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """The router's db seams, faked. Real ints and real dicts where the code does arithmetic."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def client( repo ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """
    Point the approval module's override file inside tmp_path and clear its cache.

    The INI is never touched. `_write` below is the only thing in this file that
    decides who is an approver or whether enforcement is on.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def _write( target, **body ):
    target.write_text( json.dumps( body ) )
    approval._cache_mtime = None


def _post( client, item, to_status, actor, **extra ):
    body = { "to_status": to_status, "actor": actor }
    body.update( extra )
    return client.post( f"/api/tasks/{item.id}/transition", json=body )


def test_the_isolation_actually_isolates( settings ):
    """
    The guard on every test below it, so it runs first. Without it a green file is
    also consistent with the module reading the real fleet settings.
    """
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_a_non_approver_is_refused_AT_THE_DOOR( client, repo, settings ):
    """
    THE ONE THIS FILE EXISTS FOR. A request, not a function call: this is the layer a
    caller enters at, and the only layer at which a missing call site is observable.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item

    r = _post( client, item, "queued", NON_APPROVER )

    assert r.status_code == 403, (
        f"the transition door admitted a non-approver out of the holding area — "
        f"the gate at routers/tasks.py is not being CALLED. Got {r.status_code}."
    )
    assert NON_APPROVER in r.json()[ "detail" ]
    # The refusal must be the gate's, not some other 403 the door might raise.
    assert "not an approver" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_an_APPROVER_is_let_through_the_same_door( client, repo, settings ):
    """
    The positive control, and it is not optional: without it a door that 403'd
    EVERYBODY would satisfy the test above. One variable changes — the actor.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=APPROVER,
        transition="not_approved->queued", receipt_refs=None, authority="standing",
    )

    r = _post( client, item, "queued", APPROVER )

    assert r.status_code == 200, r.text
    repo.apply_transition.assert_called_once()


def test_enforcement_OFF_is_what_keeps_the_gate_dark_today( client, repo, settings ):
    """
    The flags are OFF in `lupin-app.ini` and turning them on is Rick's call. This arm
    pins the CURRENT shipped behaviour — the same request the first test refuses is
    admitted while enforcement is off — so a future default flip is visible here
    instead of arriving as a surprise 403 in production.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=False )
    item = _item( status="not_approved" )
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=NON_APPROVER,
        transition="not_approved->queued", receipt_refs=None, authority="standing",
    )

    r = _post( client, item, "queued", NON_APPROVER )

    assert r.status_code == 200, r.text


def test_a_non_approver_cannot_close_a_row_as_wont_fix_AT_THE_DOOR( client, repo, settings ):
    """
    The other approver-only move, and the load-bearing one: `wont_fix` counts toward
    the create/close ratio, so a seat able to close rows this way holds both halves
    of a mint-by-deletion loop. The predicate is tested elsewhere; what is tested
    here is that a REQUEST reaches it.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item( status="queued" )
    repo.get_by_id_for_update.return_value = item

    # The reason is REQUIRED by the structural rules, which run BEFORE the gate on
    # purpose — a malformed payload must be told it is malformed, not that the caller
    # lacks permission to send it. Omit it and this arm 422s before the gate is
    # reached, and would then be green against a router that never calls the gate at
    # all. Measured: without the reason it returns 422, not 403.
    r = _post( client, item, "wont_fix", NON_APPROVER, reason="nobody is going to do this" )

    assert r.status_code == 403, (
        f"a non-approver closed a row as wont_fix through the door — the gate is not "
        f"being CALLED. Got {r.status_code}."
    )
    assert "wont_fix" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()
