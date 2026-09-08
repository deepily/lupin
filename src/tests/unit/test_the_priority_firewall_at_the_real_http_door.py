#!/usr/bin/env python3
"""
THE PRIORITY FIREWALL, ENTERED AT THE LAYER AN AGENT WOULD ENTER AT.

Row b8205986, Rick's broadcast e254ec7d (2026-09-07). The row's own acceptance:

    "Four rules, four named tests, each driving the real HTTP door with a real actor
     — plus a POSITIVE arm per rule (the permitted actor SUCCEEDS), or the test
     proves only that the door can refuse."

🔴 WHY THESE ARMS DRIVE HTTP AND NOT `task_priority_firewall` DIRECTLY.

`test_the_priority_firewall_refuses_the_right_caller.py` already covers the module at
100% lines and branches. It cannot tell you the ROUTER CALLS IT. A module at 100% that
the app never mounts is a real shape in this tree, and every test that builds the
component stays green while the door stands open. So these arms exist for exactly one
fact the unit file cannot state: the check is REACHED, on both doors, with the values
the handler actually has.

⚠️ ROW 4 IS DELIBERATELY ABSENT and this file has three rules, not four. Rick rescinded
manager pulling entirely twenty minutes after ruling on it (broadcast c43a29c5): "I
want to rescind the feature that allows you to pull from the holding area into the
queue and it must default to NO." A highest-priority-first refusal now sits under a
switch that is off. `refusal_for_pull` owns that surface and has its own tests.

⚠️ WHAT THESE ARMS CANNOT PROVE, so nobody quotes them for more than they carry.
Rules 2 and 3 key on a bridge role a session writes about ITSELF, so an arm that
declares a caller a manager has DECLARED it — it has not shown a real caller could not
declare the same. Rule 1 is the exception: it keys on `account_email`, which comes off
a signature-validated token, so `test_rule_1_...` genuinely flips the unforgeable
variable. Same file, two different strengths of claim.
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
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

NOW            = datetime( 2026, 9, 8, 0, 0, tzinfo=timezone.utc )
WORKER_ACTOR   = "john 54250c10"
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"


_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "bug",
        title               = "a row whose priority somebody wants to move",
        body                = None,
        project             = "lupin",
        owner_persona       = "john",
        accountable_manager = "maria",
        created_by          = "maria 21979045",
        status              = "in_progress",
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
    """
    A repository whose successful paths return a REAL TaskItem.

    ⚠️ `create_item` must not return a bare MagicMock. The handler serializes what it
    gets back, and a MagicMock serializes to a 500 — which reads exactly like a gate
    refusing, except with the wrong status code. The POSITIVE arms are the ones that
    exercise the success path, so they are precisely the arms that would have been
    reported as passing-through-a-500 had this returned a mock.
    """
    fake = MagicMock()
    fake.statuses_for_ids.return_value      = { }
    # A DICT, not a tuple — the handler subscripts it by name. A tuple here raises
    # TypeError deep in the handler and surfaces as a 500, which reads exactly like a
    # gate refusing with the wrong status code.
    fake.count_created_and_closed.return_value = { "created": 0, "closed": 0 }
    fake.create_item.side_effect             = lambda **kw: _item( **{
        k: v for k, v in kw.items() if k in _ITEM_FIELDS
    } )

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """
    The approval module's override file, inside tmp_path. The fleet INI is never read.

    Without this the arms would be measuring whoever happens to be an approver today —
    an operator-editable file deciding a test result, which is the defect that reddened
    six tests in test_spawn_sessions.py the same morning this file was written.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"         : [ "rick" ],
        "enforcement_active": False,
        "approver_accounts" : { OPERATOR_EMAIL: "rick" },
    } ) )
    approval._cache_mtime = None
    return target


@pytest.fixture
def worker_bridge( monkeypatch ):
    """
    A bridge that says every session is a WORKER.

    🔴 THE ROW'S OWN INSTRUCTION, AND IT IS NOT PEDANTRY: "A test that asserts a
    worker's P0 is refused must drive the door with a bridge that SAYS worker; it
    cannot prove refusal against an actor who says otherwise." Left un-stubbed, the
    live `is_manager_figure` reads whatever bridges are on this machine — so the arm
    would pass or fail depending on which seats happen to be running, which is not a
    fact about the code.
    """
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None:
                             firewall.caller_is_operator( account_email ) )


@pytest.fixture
def manager_bridge( monkeypatch ):
    """A bridge that says every session is a MANAGER — the positive arms for rules 2-3."""
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None: True )


def _client( account_email ):
    """
    A client whose ONE variable is the login account the server resolves.

    `authenticated_account_email` is overridden rather than stubbed on the module, so
    the handler resolves it exactly as production does — through its own dependency.
    `None` is every agent seat in the fleet: API-key auth, no account.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _create( client, priority, created_by=WORKER_ACTOR ):
    return client.post( "/api/tasks", json={
        "item_class" : "task",
        "title"      : "a ticket somebody is filing",
        "project"    : "lupin",
        "created_by" : created_by,
        "priority"   : priority,
    } )


def _patch( client, item, priority, actor=WORKER_ACTOR ):
    return client.patch( f"/api/tasks/{item.id}", json={
        "priority" : priority,
        "actor"    : actor,
    } )


# ---------------------------------------------------------------------------
# The isolation control FIRST — a green file must not also be consistent with
# these arms reading the real fleet settings.
# ---------------------------------------------------------------------------

def test_the_isolation_actually_isolates( settings ):
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()
    assert approval.approver_persona_for_account( OPERATOR_EMAIL ) == "rick"
    assert approval.approver_persona_for_account( None ) is None


# ---------------------------------------------------------------------------
# RULE 1 — P0 is the operator's alone. The one arm that flips an UNFORGEABLE
# variable, so the only one that can carry a forgery claim.
# ---------------------------------------------------------------------------

def test_rule_1_the_create_door_refuses_p0_to_an_accountless_caller(
        settings, repo, worker_bridge ):
    r = _create( _client( None ), "P0" )
    assert r.status_code == 403, r.text
    assert "P0" in r.json()[ "detail" ]
    assert not repo.create.called, "a refused create still reached the repository"


def test_rule_1_the_create_door_refuses_p0_to_a_logged_in_NON_operator(
        settings, repo, manager_bridge ):
    # The arm that separates "has an account" from "is Rick". A manager with a real
    # login is exactly the caller rule 1 exists to stop, and `manager_bridge` makes
    # this caller pass rule 3 — so only rule 1 can be producing the refusal.
    r = _create( _client( BYSTANDER_MAIL ), "P0" )
    assert r.status_code == 403, r.text
    assert not repo.create.called


def test_rule_1_POSITIVE_the_operators_own_account_creates_p0( settings, repo, worker_bridge ):
    # Without this, every arm above is satisfied by a door that refuses P0 to
    # everybody — including Rick, which is not the rule.
    r = _create( _client( OPERATOR_EMAIL ), "P0" )
    assert r.status_code != 403, r.text


def test_rule_1_the_patch_door_refuses_p0_to_an_accountless_caller(
        settings, repo, worker_bridge ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    r = _patch( _client( None ), item, "P0" )
    assert r.status_code == 403, r.text
    assert not repo.apply_patch.called and not repo.patch.called, "a refused patch was written"


def test_rule_1_POSITIVE_the_operator_patches_a_row_to_p0( settings, repo, worker_bridge ):
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    r = _patch( _client( OPERATOR_EMAIL ), item, "P0" )
    assert r.status_code != 403, r.text


# ---------------------------------------------------------------------------
# RULE 2 — raising to P1-P4 needs the operator or a manager. Bridge-keyed, so a
# POLICY control: these arms show the door is reached, not that it is unforgeable.
# ---------------------------------------------------------------------------

def test_rule_2_the_patch_door_refuses_a_worker_raising_the_priority(
        settings, repo, worker_bridge ):
    item = _item( priority="P5" )
    repo.get_by_id_for_update.return_value = item
    r = _patch( _client( None ), item, "P2" )
    assert r.status_code == 403, r.text
    assert "P2" in r.json()[ "detail" ]


def test_rule_2_POSITIVE_a_manager_raises_the_priority( settings, repo, manager_bridge ):
    item = _item( priority="P5" )
    repo.get_by_id_for_update.return_value = item
    r = _patch( _client( None ), item, "P2" )
    assert r.status_code != 403, r.text


def test_rule_2_a_worker_may_still_LOWER_a_priority( settings, repo, worker_bridge ):
    # The boundary. Demotion is Rick's 11:58 ruling and lands on the admission path,
    # not here. If somebody later adds a demotion check to this module, this named
    # arm is what should redden first.
    item = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item
    r = _patch( _client( None ), item, "P4" )
    assert r.status_code != 403, r.text


def test_rule_2_the_current_priority_is_read_from_the_LOCKED_ROW_not_the_caller(
        settings, repo, worker_bridge ):
    # 🔴 THE ARM THAT PINS WHICH SIDE THE "current" COMES FROM. The payload cannot
    # carry a current priority (extra='forbid'), so the only way this check knows
    # where the row is now is the locked read. Proved by moving the ROW and watching
    # the same request flip: at P5 a raise to P2 is refused, at P1 the same request
    # is a LOWERING and is allowed. A gate reading the caller's word could not tell
    # these two apart.
    item_low = _item( priority="P5" )
    repo.get_by_id_for_update.return_value = item_low
    assert _patch( _client( None ), item_low, "P2" ).status_code == 403

    item_high = _item( priority="P1" )
    repo.get_by_id_for_update.return_value = item_high
    assert _patch( _client( None ), item_high, "P2" ).status_code != 403


# ---------------------------------------------------------------------------
# RULE 3 — a worker's create is P5.
# ---------------------------------------------------------------------------

def test_rule_3_the_create_door_refuses_a_worker_filing_above_the_floor(
        settings, repo, worker_bridge ):
    r = _create( _client( None ), "P1" )
    assert r.status_code == 403, r.text
    assert "P5" in r.json()[ "detail" ]
    assert not repo.create.called


def test_rule_3_POSITIVE_a_worker_files_at_the_floor( settings, repo, worker_bridge ):
    # The normal case, and the one an over-eager gate breaks silently. Every ticket
    # the fleet files goes through here.
    r = _create( _client( None ), "P5" )
    assert r.status_code != 403, r.text


def test_rule_3_POSITIVE_a_manager_files_above_the_floor( settings, repo, manager_bridge ):
    r = _create( _client( None ), "P1" )
    assert r.status_code != 403, r.text


# ---------------------------------------------------------------------------
# The gate is REACHED — the fact the unit file cannot state
# ---------------------------------------------------------------------------

def test_the_create_door_actually_consults_the_firewall( settings, repo, monkeypatch ):
    # Pins the CALL, not just the outcome. Without it, a refusal could be coming from
    # any other gate on this handler and the arms above would still be green.
    seen = { }

    def spy( requested, bridge_role=None, account_email=None, actor=None, manager_fn=None ):
        seen.update( requested=requested, actor=actor, account_email=account_email )
        return None

    monkeypatch.setattr( tasks.priority_firewall, "refusal_for_priority_create", spy )
    _create( _client( OPERATOR_EMAIL ), "P3", created_by="maria 21979045" )
    assert seen == { "requested": "P3", "actor": "maria 21979045",
                     "account_email": OPERATOR_EMAIL }, seen


def test_the_patch_door_actually_consults_the_firewall( settings, repo, monkeypatch ):
    seen = { }

    def spy( current, requested, bridge_role=None, account_email=None, actor=None, manager_fn=None ):
        seen.update( current=current, requested=requested, actor=actor,
                     account_email=account_email )
        return None

    monkeypatch.setattr( tasks.priority_firewall, "refusal_for_priority_change", spy )
    item = _item( priority="P4" )
    repo.get_by_id_for_update.return_value = item
    _patch( _client( OPERATOR_EMAIL ), item, "P2", actor="maria 21979045" )
    assert seen == { "current": "P4", "requested": "P2", "actor": "maria 21979045",
                     "account_email": OPERATOR_EMAIL }, seen


def test_the_patch_door_does_NOT_consult_the_firewall_without_a_priority_edit(
        settings, repo, monkeypatch ):
    # The other half: a title-only edit must not pay for, or be refused by, a
    # priority rule. A gate that fires on every PATCH is a different feature.
    called = [ ]
    monkeypatch.setattr( tasks.priority_firewall, "refusal_for_priority_change",
                         lambda *a, **k: called.append( 1 ) )
    item = _item()
    repo.get_by_id_for_update.return_value = item
    _client( None ).patch( f"/api/tasks/{item.id}",
                           json={ "title": "a new title", "actor": WORKER_ACTOR } )
    assert called == [ ], "the priority gate fired on an edit that changed no priority"
