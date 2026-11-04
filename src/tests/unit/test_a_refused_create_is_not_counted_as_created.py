#!/usr/bin/env python3
"""
A create the door REFUSES does not count as "created" in the ratio gate (parent bug 08691779).

Cheech's unverified lead: a task_create rejected on validation (422, e.g. a correlation_key
without "epic:") still counts toward the closed-vs-new ratio. The count is
`TaskRepository.count_created_and_closed`, a SQL COUNT over TaskEvent rows whose transition
starts with "->", and the only writer of that stamp is `create_item`. So the lead is true only
if a refused request reaches `create_item` (or leaves a committed event behind).

The repo here is STATEFUL: its "created" count is the baseline plus the number of
`create_item` calls actually made, so a refused request that leaked into the count would move
the very number the gate reads. The door is the real router, entered over HTTP.

🔴 THE CONTROL ARM IS WHAT MAKES THE REFUSAL ARMS MEAN ANYTHING. An accepted create MUST move
the count by exactly one, or "the count did not move" is equally consistent with a fixture
that never counts.
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

from cosa.rest import task_store_rules as rules
from cosa.rest import task_priority_firewall as firewall
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

NOW        = datetime( 2026, 9, 30, 15, 0, tzinfo=timezone.utc )
ADMITTING  = { "created": 6,  "closed": 10 }    # ratio 0.6, room for several creates: under the 0.9 threshold, the gate admits
REFUSING   = { "created": 10, "closed": 9 }     # ratio 1.11: the gate refuses

_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


class _CountingRepo:
    """Stateful stand-in: `created` = baseline + every create_item that actually ran."""

    def __init__( self, baseline ):
        self.baseline      = baseline
        self.created_items = [ ]
        self.mock          = MagicMock()
        self.mock.statuses_for_ids.return_value = { }

    def count_created_and_closed( self, since, until=None, project=None ):
        return { "created": self.baseline[ "created" ] + len( self.created_items ), "closed": self.baseline[ "closed" ] }

    def create_item( self, **kw ):
        item = TaskItem( **{ k: v for k, v in kw.items() if k in _ITEM_FIELDS },
                         id=uuid.uuid4(), created_ts=NOW, updated_ts=NOW, title_trimmed=False )
        self.created_items.append( item )
        return item

    def __getattr__( self, name ):
        return getattr( self.mock, name )


@pytest.fixture
def repo( monkeypatch ):
    fake = _CountingRepo( ADMITTING )

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None: True )
    monkeypatch.setattr( tasks.frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( tasks.frs, "get_allow_below", lambda: 0.9 )
    monkeypatch.setattr( tasks.frs, "get_window_hours", lambda: 24 )
    return fake


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: "somebody@example.com"
    return TestClient( app )


def _post( client, **fields ):
    body = {
        "item_class": "task", "title": "a ticket", "project": "lupin", "created_by": "maria",
        "priority": "P2", "correlation_key": "epic:unassigned",
    }
    body.update( fields )
    return client.post( "/api/tasks", json=body )


def test_control_an_accepted_create_moves_the_count_by_one( repo, client ):
    before = repo.count_created_and_closed( since=None )[ "created" ]
    resp   = _post( client )
    assert resp.status_code == 201, resp.text
    assert repo.count_created_and_closed( since=None )[ "created" ] == before + 1


def test_an_epic_key_refusal_is_not_counted( repo, client ):
    assert rules.EPIC_KEY_ENFORCEMENT_ACTIVE, "precondition: the epic guard must be enforcing"
    before = repo.count_created_and_closed( since=None )[ "created" ]
    resp   = _post( client, correlation_key="no-epic-here" )
    assert resp.status_code == 422 and "epic" in resp.text.lower()
    assert repo.created_items == [ ]
    assert repo.count_created_and_closed( since=None )[ "created" ] == before


def test_a_ratio_gate_refusal_is_not_counted( repo, client ):
    repo.baseline = REFUSING
    before = repo.count_created_and_closed( since=None )[ "created" ]
    resp   = _post( client )
    assert resp.status_code == 422 and "gated" in resp.text, resp.text
    assert repo.created_items == [ ]
    assert repo.count_created_and_closed( since=None )[ "created" ] == before


def test_a_refusal_after_admitted_creates_leaves_the_count_where_the_creates_put_it( repo, client ):
    """Counts move only for creates that ran: 2 accepted, then one refused for a bad epic key."""
    assert _post( client ).status_code == 201
    assert _post( client ).status_code == 201
    assert _post( client, correlation_key="nope" ).status_code == 422
    assert len( repo.created_items ) == 2
    assert repo.count_created_and_closed( since=None )[ "created" ] == ADMITTING[ "created" ] + 2
