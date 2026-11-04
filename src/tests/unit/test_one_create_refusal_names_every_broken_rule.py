#!/usr/bin/env python3
"""
ONE CREATE REFUSAL NAMES EVERY RULE THE CALL BROKE.

Row 631a812e. A worker seat needed four calls to file one row: the create door raised
at the first broken rule and named only that one, so the seat learned the priority
rule, then the status rule, then the epic-key rule, one refusal at a time.

The row's acceptance: "a worker create that breaks all three rules gets one refusal
naming all three, and a call built from that refusal's text succeeds."

These arms drive the HTTP door, not `_raise_create_refusals` alone, because the fact
under test is that the router asks every gate before it answers.

What these arms do not show: the ratio gate and the blocked-mint manager guard are not
folded in. Both need IO the pure gates do not, and each still raises alone.
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
from cosa.rest import task_priority_firewall as firewall
from cosa.rest import task_store_rules as rules
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from tests.helpers.approval_settings_fixtures import seed

NOW            = datetime( 2026, 10, 5, 0, 0, tzinfo=timezone.utc )
WORKER_ACTOR   = "tiffany 54250c10"
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"

_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "task",
        title               = "a row a worker is filing",
        body                = None,
        project             = "lupin",
        owner_persona       = "tiffany",
        accountable_manager = "maria",
        created_by          = WORKER_ACTOR,
        status              = "queued",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P5",
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
    """A repository whose create returns a REAL TaskItem, so a success serializes to 201."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value         = { }
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }
    fake.create_item.side_effect               = lambda **kw: _item( **{
        k: v for k, v in kw.items() if k in _ITEM_FIELDS
    } )

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def worker_bridge( monkeypatch ):
    """A bridge that says every session is a WORKER, so the result does not depend on live seats."""
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None:
                             firewall.caller_is_operator( account_email ) )


def _settings( default_to_holding ):
    seed( {
        "approvers"          : [ "rick" ],
        "enforcement_active" : False,
        "approver_accounts"  : { OPERATOR_EMAIL: "rick" },
        "default_to_holding" : default_to_holding,
    } )


@pytest.fixture
def holding_on():
    _settings( True )


@pytest.fixture
def holding_off():
    _settings( False )


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: None
    return TestClient( app )


def _create( client, **fields ):
    body = {
        "item_class" : "task",
        "title"      : "a ticket a worker is filing",
        "project"    : "lupin",
        "created_by" : WORKER_ACTOR,
    }
    body.update( fields )
    return client.post( "/api/tasks", json=body )


# ---------------------------------------------------------------------------
# Controls first: the fixtures move the answer, and the epic rule is enforced.
# ---------------------------------------------------------------------------

def test_the_holding_fixture_moves_the_default( holding_on ):
    assert approval.default_mint_status() == rules.NOT_APPROVED_STATUS
    _settings( False )
    assert approval.default_mint_status() == "queued"


def test_the_epic_key_rule_is_enforced_today():
    # Every "epic key is named" arm below is vacuous if this flag is off.
    assert rules.EPIC_KEY_ENFORCEMENT_ACTIVE is True


# ---------------------------------------------------------------------------
# The row's acceptance
# ---------------------------------------------------------------------------

def test_a_worker_create_breaking_all_three_rules_gets_one_refusal_naming_all_three_and_the_recipe_works(
        holding_on, repo, worker_bridge, client ):
    refused = _create( client, priority="P1", status="in_progress" )

    assert refused.status_code == 403, refused.text
    detail = refused.json()[ "detail" ]
    assert not repo.create_item.called, "a refused create still reached the repository"

    # Each rule is named by the text of its OWN gate, asked with the same arguments.
    priority_text = firewall.refusal_for_priority_create( requested="P1", actor=WORKER_ACTOR, account_email=None )
    status_text   = rules.validate_create_status( "in_progress", [ ], None )[ 0 ]
    live_text     = approval.refusal_for_live_mint( "in_progress", True, "P1", caller_is_operator=False )
    epic_text     = rules.epic_key_advisory( None )
    assert detail.startswith( priority_text )
    assert status_text in detail
    assert live_text   in detail
    assert epic_text   in detail
    assert "breaks 3 more create rule(s)" in detail

    # The recipe, read out of the refusal: the worker's priority, omit `status`, and a legal key.
    assert f"a worker files {firewall.WORKER_CREATE_PRIORITY}" in detail
    assert "OMIT `status`" in detail
    assert f"'{rules.EPIC_KEY_UNASSIGNED}'" in detail

    filed = _create( client, priority=firewall.WORKER_CREATE_PRIORITY, correlation_key=rules.EPIC_KEY_UNASSIGNED )
    assert filed.status_code == 201, filed.text
    assert repo.create_item.call_count == 1
    assert filed.json()[ "status" ] == rules.NOT_APPROVED_STATUS


def test_KNOWN_GAP_a_refused_P0_is_not_told_about_the_live_mint_rule_until_the_retry(
        holding_on, repo, worker_bridge, client ):
    # P0 is exempt from the live-mint rule by Rick's carve-out, and
    # test_tasks_router.py::test_a_P0_MAY_still_mint_live_at_the_door pins that the
    # gate's text does not appear on a non-operator's P0 create. So this one path
    # still costs a second call. This arm records that; it is not the wanted end state.
    refused = _create( client, priority="P0", status="queued" )
    assert refused.status_code == 403, refused.text
    detail = refused.json()[ "detail" ]
    assert "breaks 1 more create rule(s)" in detail
    assert f"[2] {rules.epic_key_advisory( None )}" in detail
    assert "holding area" not in detail

    retry = _create( client, priority="P5", status="queued", correlation_key=rules.EPIC_KEY_UNASSIGNED )
    assert retry.status_code == 403, retry.text
    assert "OMIT `status`" in retry.json()[ "detail" ]


# ---------------------------------------------------------------------------
# One broken rule reads exactly as it did before
# ---------------------------------------------------------------------------

def test_a_priority_refusal_alone_is_the_gates_own_text_and_nothing_more(
        holding_off, repo, worker_bridge, client ):
    r = _create( client, priority="P1", correlation_key=rules.EPIC_KEY_UNASSIGNED )
    assert r.status_code == 403, r.text
    assert r.json()[ "detail" ] == firewall.refusal_for_priority_create(
        requested="P1", actor=WORKER_ACTOR, account_email=None )


def test_a_status_refusal_alone_is_one_error( holding_off, repo, worker_bridge, client ):
    r = _create( client, priority="P5", status="in_progress", correlation_key=rules.EPIC_KEY_UNASSIGNED )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == { "errors": rules.validate_create_status( "in_progress", [ ], None ) }


def test_a_live_mint_refusal_alone_is_the_gates_own_text_and_nothing_more(
        holding_on, repo, worker_bridge, client ):
    r = _create( client, priority="P5", status="queued", correlation_key=rules.EPIC_KEY_UNASSIGNED )
    assert r.status_code == 403, r.text
    assert r.json()[ "detail" ] == approval.refusal_for_live_mint( "queued", True, "P5", caller_is_operator=False )


def test_an_epic_key_refusal_alone_is_still_raised_where_it_always_was(
        holding_off, repo, worker_bridge, client ):
    r = _create( client, priority="P5" )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == rules.epic_key_advisory( None )
    assert not repo.create_item.called


# ---------------------------------------------------------------------------
# Two broken rules: the first keeps its status code, the second rides along
# ---------------------------------------------------------------------------

def test_a_status_refusal_carries_the_live_mint_and_epic_key_refusals_in_its_error_list(
        holding_on, repo, worker_bridge, client ):
    r = _create( client, priority="P5", status="in_progress" )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == { "errors": [
        rules.validate_create_status( "in_progress", [ ], None )[ 0 ],
        approval.refusal_for_live_mint( "in_progress", True, "P5", caller_is_operator=False ),
        rules.epic_key_advisory( None ),
    ] }


def test_a_live_mint_refusal_carries_the_epic_key_refusal( holding_on, repo, worker_bridge, client ):
    r = _create( client, priority="P5", status="queued" )
    assert r.status_code == 403, r.text
    detail = r.json()[ "detail" ]
    assert detail.startswith( approval.refusal_for_live_mint( "queued", True, "P5", caller_is_operator=False ) )
    assert "breaks 1 more create rule(s)" in detail
    assert f"[2] {rules.epic_key_advisory( None )}" in detail


def test_the_epic_key_refusal_is_left_out_when_that_rule_is_not_enforced(
        holding_on, repo, worker_bridge, client, monkeypatch ):
    # Warn-only means the write is not blocked on it, so telling the caller it was
    # "refused" would be false.
    monkeypatch.setattr( rules, "EPIC_KEY_ENFORCEMENT_ACTIVE", False )
    r = _create( client, priority="P5", status="queued" )
    assert r.status_code == 403, r.text
    assert r.json()[ "detail" ] == approval.refusal_for_live_mint( "queued", True, "P5", caller_is_operator=False )


# ---------------------------------------------------------------------------
# The helper's own contract
# ---------------------------------------------------------------------------

def test_no_broken_rule_raises_nothing_and_an_epic_refusal_alone_is_not_raised_here():
    assert tasks._raise_create_refusals( None, [ ], None, None ) is None
    assert tasks._raise_create_refusals( None, [ ], None, "an epic refusal" ) is None


def test_the_also_suffix_numbers_from_two_and_is_empty_for_nothing():
    assert tasks._also_refused( [ ] ) == ""
    suffix = tasks._also_refused( [ "first other", "second other" ] )
    assert "breaks 2 more create rule(s)" in suffix
    assert "[2] first other [3] second other" in suffix
