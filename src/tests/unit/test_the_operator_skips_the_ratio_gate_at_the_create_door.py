#!/usr/bin/env python3
"""
RICK'S OWN TICKETS SKIP THE RATIO GATE, AND SAY SO — entered at the real HTTP door.

Row c9895403. Rick, by keypress, 2026-09-10: "Yes my own tickets should skip the ratio gate
and get logged." His New Ticket card files straight onto the board; a throughput gate built
to meter the fleet's filing must not be able to refuse the operator's own ticket.

🔴 EVERY EXEMPTION ARM HAS A REFUSAL ARM BESIDE IT, WITH THE SAME COUNTS. Without it, a 201
for the operator is equally consistent with "the gate was never armed in this fixture", which
proves nothing about an exemption. The non-operator arm is what shows the gate WOULD refuse.

⚠️ THE EXEMPTION KEYS ON A VALIDATED LOGIN. `authenticated_account_email` is overridden as a
dependency, so the handler resolves identity exactly as production does. A caller who only
TYPES "rick" into `created_by` is still metered — that arm is here too.
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
from cosa.rest import task_store_rules as rules
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

NOW            = datetime( 2026, 9, 10, 15, 0, tzinfo=timezone.utc )
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"

# Filing ten for every one closed: the gate refuses at any threshold of 1.0.
REFUSING_COUNTS = { "created": 10, "closed": 1 }

_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


def _item( **overrides ):
    fields = dict(
        id = uuid.uuid4(), item_class = "task", title = "a ticket", body = None, project = "lupin",
        owner_persona = "rick", accountable_manager = None, created_by = "rick",
        status = "queued", blocked_by = [ ], next_chase_ts = None, gate_class = "none",
        priority = "P2", source_qid = None, correlation_key = None,
        created_ts = NOW, updated_ts = NOW, title_trimmed = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """A repository that returns real rows and reports counts the gate refuses on."""
    fake = MagicMock()
    fake.statuses_for_ids.return_value         = { }
    fake.count_created_and_closed.return_value = dict( REFUSING_COUNTS )
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
def armed_gate( monkeypatch ):
    """The ratio gate ENFORCING at 1.0 — read from these stubs, never the operator's live file."""
    monkeypatch.setattr( tasks.frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( tasks.frs, "get_allow_below", lambda: 1.0 )
    monkeypatch.setattr( tasks.frs, "get_window_hours", lambda: 24 )


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """The approval override file in tmp_path, mapping ONLY the operator's email to rick."""
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", { "approvers": None, "enforcement_active": None } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"          : [ "rick" ],
        "enforcement_active" : False,
        "approver_accounts"  : { OPERATOR_EMAIL: "rick" },
    } ) )
    return target


@pytest.fixture
def manager_bridge( monkeypatch ):
    """Every caller passes the P1–P4 manager rule, so ONLY the ratio gate can refuse a P2."""
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None: True )


def _client( account_email ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _create( client, **fields ):
    # 🔴 THE EPIC KEY IS NOT DECORATION. The epic-key guard is ENFORCING, and without a key
    # every arm here answers 422 "no epic key" — which the two CONTROL arms below read as
    # the ratio gate refusing, green for the wrong reason. Found exactly that way, 2026-09-10.
    body = {
        "item_class"      : "task",
        "title"           : "a ticket from the New Ticket card",
        "project"         : "lupin",
        "created_by"      : "rick",
        "priority"        : "P2",
        "status"          : "queued",
        "correlation_key" : "epic:unassigned",
    }
    body.update( fields )
    # `status=None` means OMIT it. Since row 2d786391 (2026-09-11) the create door refuses
    # an explicit live status from anyone but the operator or a P0, so a NON-operator arm
    # that named "queued" would be answered 403 by that door before the ratio gate could
    # speak — and the CONTROL arms below would be green or red for the wrong gate.
    if body[ "status" ] is None: del body[ "status" ]
    return client.post( "/api/tasks", json=body )


# ---------------------------------------------------------------------------
# The control first: with these counts, the gate refuses a caller who is not Rick.
# ---------------------------------------------------------------------------

def _ratio_refusal_for( priority="P2" ):
    """The EXACT refusal the ratio gate writes for these counts — so a control cannot pass on another gate's 422."""
    return rules.ratio_gate_advisory(
        created         = REFUSING_COUNTS[ "created" ],
        closed          = REFUSING_COUNTS[ "closed" ],
        priority        = priority,
        correlation_key = "epic:unassigned",
        allow_below     = 1.0,
    )


def test_CONTROL_the_refusal_helper_is_a_real_refusal():
    # A None here would make both controls below compare against nothing.
    assert _ratio_refusal_for()


def test_CONTROL_the_armed_gate_refuses_a_logged_in_non_operator( settings, repo, armed_gate, manager_bridge ):
    r = _create( _client( BYSTANDER_MAIL ), status=None )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == _ratio_refusal_for(), "the 422 must be the RATIO gate's, not another gate's"
    assert not repo.create_item.called, "a refused create still reached the repository"


def test_CONTROL_typing_rick_into_created_by_does_not_buy_the_exemption(
        settings, repo, armed_gate, manager_bridge ):
    # The API-key seat: no account. Its created_by says "rick" and that confers nothing.
    r = _create( _client( None ), created_by="rick 12345678", status=None )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == _ratio_refusal_for()
    assert not repo.create_item.called


# ---------------------------------------------------------------------------
# The exemption, and the log line that is its condition.
# ---------------------------------------------------------------------------

def test_the_operators_ticket_is_created_through_an_armed_refusing_gate(
        settings, repo, armed_gate, manager_bridge ):
    r = _create( _client( OPERATOR_EMAIL ) )
    assert r.status_code == 201, r.text
    assert repo.create_item.call_args.kwargs[ "priority" ] == "P2"


def test_every_operator_exemption_is_logged_with_the_counts( settings, repo, armed_gate, manager_bridge, capsys ):
    _create( _client( OPERATOR_EMAIL ), title="the ticket whose skip must be visible" )
    out = capsys.readouterr().out
    assert "ratio-gate OPERATOR EXEMPTION" in out
    assert "the ticket whose skip must be visible" in out
    assert "created=10 closed=1" in out


def test_the_log_names_the_validated_identity_not_only_the_typed_one(
        settings, repo, armed_gate, manager_bridge, capsys ):
    _create( _client( OPERATOR_EMAIL ), created_by="rick" )
    line = next( l for l in capsys.readouterr().out.splitlines() if "OPERATOR EXEMPTION" in l )
    expected = tasks.recorded_actor( "rick", OPERATOR_EMAIL )
    # The upgrade must have happened, or this arm cannot tell identity from a typed name.
    assert expected != "rick", expected
    assert f"used by {expected}:" in line, line


def test_a_p0_from_the_operator_logs_the_OPERATOR_line_not_the_P0_line(
        settings, repo, armed_gate, manager_bridge, capsys ):
    # The operator check comes first, so one ticket leaves one exemption record, not two.
    r = _create( _client( OPERATOR_EMAIL ), priority="P0" )
    assert r.status_code == 201, r.text
    out = capsys.readouterr().out
    assert "OPERATOR EXEMPTION" in out
    assert "P0 EXEMPTION" not in out


# ---------------------------------------------------------------------------
# The card's two destinations both mint as asked.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "status", [ "queued", "not_approved" ] )
def test_the_operators_explicit_status_is_the_status_minted( settings, repo, armed_gate, manager_bridge, status ):
    r = _create( _client( OPERATOR_EMAIL ), status=status )
    assert r.status_code == 201, r.text
    assert repo.create_item.call_args.kwargs[ "status" ] == status


def test_a_non_operator_on_the_allow_path_still_prints_the_reading_not_an_exemption(
        settings, repo, manager_bridge, monkeypatch, capsys ):
    # The permissive-path reading (row aba30387) must survive this change for everyone else.
    monkeypatch.setattr( tasks.frs, "get_enforcement_active", lambda: True )
    monkeypatch.setattr( tasks.frs, "get_allow_below", lambda: 1.0 )
    monkeypatch.setattr( tasks.frs, "get_window_hours", lambda: 24 )
    repo.count_created_and_closed.return_value = { "created": 1, "closed": 10 }
    r = _create( _client( BYSTANDER_MAIL ), status=None )
    assert r.status_code == 201, r.text
    out = capsys.readouterr().out
    assert "OPERATOR EXEMPTION" not in out
    assert "ratio" in out.lower()
