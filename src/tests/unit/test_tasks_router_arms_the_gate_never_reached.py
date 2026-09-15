#!/usr/bin/env python3
"""
THE ARMS OF routers/tasks.py THAT NO TEST HAD EVER DRIVEN — each through the real door.

Row ab8c5728, AC7 (100% lines/branches/functions on every module the Sword build touched).
The coverage gate on candidate d322aba1 left routers/tasks.py at 96%, missing lines 852,
1104, 1175, 1189, 1194->1223, 1730, 2218-2219, 2273-2286, 2391-2396, 3025-3032 and
3838-3841. All predate the Sword build; it touched the module, so it inherited them.

🔴 EVERY ARM ASSERTS THE BEHAVIOUR THE LINE EXISTS FOR, NOT MERELY THAT IT RAN. A line
executed by a test that asserts nothing about it is covered and still unguarded. So a WARN
arm asserts the write went through AND the warning names its reason; an error arm asserts
the status AND the words an operator reads; a permit arm has a refusal CONTROL beside it
with the same fixture, so a 201 cannot come from a gate that was never armed.

⚠️ Line 1730 (an asynchronous promotion whose precheck settles it) lives in
`test_the_asynchronous_promotion_resolves_or_shouts.py`, beside the fixture that can reach it.

VENUE: :7999-eligible. In-process TestClient, a MagicMock repository, tmp_path or
monkeypatched settings — never the fleet's live override files.
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

from cosa.rest import flow_ratio_settings as frs
from cosa.rest import task_approval_settings as approval
from cosa.rest import task_priority_firewall as firewall
from cosa.rest import task_request_lifecycle as request_lifecycle
from cosa.rest import task_store_rules as rules
from cosa.rest.auth_middleware import require_admin
from cosa.rest.postgres_models import TaskItem
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email
from cosa.rest.task_promotion_gate import DENIAL_STALE_BRIDGE, DENIAL_DENIED

NOW            = datetime( 2026, 9, 15, 16, 45, tzinfo=timezone.utc )
OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"

REFUSING_COUNTS = { "created": 10, "closed": 1 }
ALLOWING_COUNTS = { "created": 1, "closed": 10 }

_ITEM_FIELDS = (
    "item_class", "title", "body", "project", "owner_persona", "accountable_manager",
    "created_by", "status", "blocked_by", "next_chase_ts", "gate_class", "priority",
    "source_qid", "correlation_key",
)


def _item( **overrides ):
    fields = dict(
        id = uuid.uuid4(), item_class = "task", title = "a ticket", body = None, project = "lupin",
        owner_persona = "maria", accountable_manager = None, created_by = "maria 145bf6c7",
        status = "not_approved", blocked_by = [ ], next_chase_ts = None, gate_class = "none",
        priority = "P2", source_qid = None, correlation_key = None,
        created_ts = NOW, updated_ts = NOW, title_trimmed = False,
    )
    fields.update( overrides )
    return TaskItem( **fields )


@pytest.fixture
def repo( monkeypatch ):
    """A repository that returns real rows and reports whatever counts an arm sets."""
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
def ratio( monkeypatch ):
    """The ratio gate's three dials, stubbed at 1.0 over 24 h. Enforcement is set per arm."""
    monkeypatch.setattr( tasks.frs, "get_allow_below", lambda: 1.0 )
    monkeypatch.setattr( tasks.frs, "get_window_hours", lambda: 24 )
    monkeypatch.setattr( tasks.frs, "get_enforcement_active", lambda: True )


@pytest.fixture
def manager_bridge( monkeypatch ):
    """Every caller passes the P1–P4 manager rule, so only the gate under test can refuse."""
    monkeypatch.setattr( firewall, "caller_is_manager_by_bridge",
                         lambda actor, account_email=None, manager_fn=None: True )


def _client( account_email=None, admin=False ):
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    if admin:
        app.dependency_overrides[ require_admin ] = lambda: { "email": "admin@test" }
    return TestClient( app )


def _create( client, **fields ):
    # `status` is omitted by default: an explicit live status from a non-operator is refused
    # 403 by the create door (row 2d786391) before any gate below could speak.
    body = {
        "item_class"      : "task",
        "title"           : "an arm of the create door",
        "project"         : "lupin",
        "created_by"      : "maria 145bf6c7",
        "priority"        : "P2",
        "correlation_key" : "epic:unassigned",
    }
    body.update( fields )
    for key in [ k for k, v in body.items() if v is None ]: del body[ key ]
    return client.post( "/api/tasks", json=body )


# ═══════════════════════════════════════════════════════════════════════════════════
# 852 · the blocked-mint denial names what it OBSERVED when the bridge is stale
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_stale_bridge_denial_names_the_absent_stamp_and_not_a_permission_verdict():
    stale  = tasks._blocked_mint_denial_detail( DENIAL_STALE_BRIDGE )
    denied = tasks._blocked_mint_denial_detail( DENIAL_DENIED )

    assert "manager_figure_implicit" in stale, stale
    assert "field ABSENT, not false" in stale, stale
    assert "RESTART the session" in stale, "a stale bridge must be told the fix, not a permission verdict"
    # The CONTROL: a genuinely denied caller is told the field is FALSE and gets no restart advice.
    # Both messages name the field, so the distinction has to be anchored on what each claims.
    assert "is false" in denied, denied
    assert "ABSENT" not in denied, denied
    assert "RESTART" not in denied, denied


# ═══════════════════════════════════════════════════════════════════════════════════
# 1104 · the epic-key guard in warn-only mode lets the write through and SAYS so
# ═══════════════════════════════════════════════════════════════════════════════════

def test_CONTROL_an_enforcing_epic_key_guard_refuses_a_row_with_no_key( settings, repo, ratio, manager_bridge, monkeypatch ):
    monkeypatch.setattr( rules, "EPIC_KEY_ENFORCEMENT_ACTIVE", True )
    r = _create( _client( OPERATOR_EMAIL ), correlation_key=None )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == rules.epic_key_advisory( None )
    assert not repo.create_item.called


def test_a_warn_only_epic_key_guard_writes_the_row_and_prints_the_advisory( settings, repo, ratio, manager_bridge, monkeypatch, capsys ):
    monkeypatch.setattr( rules, "EPIC_KEY_ENFORCEMENT_ACTIVE", False )
    r = _create( _client( OPERATOR_EMAIL ), correlation_key=None )
    assert r.status_code == 201, r.text
    assert repo.create_item.called
    out = capsys.readouterr().out
    assert "[task WARN] epic-key guard on task create" in out
    assert "write NOT blocked" in out


# ═══════════════════════════════════════════════════════════════════════════════════
# 1175 · a ratio refusal with enforcement OFF writes the row and prints the refusal
# ═══════════════════════════════════════════════════════════════════════════════════

def test_CONTROL_the_same_counts_with_enforcement_ON_refuse( settings, repo, ratio, manager_bridge ):
    r = _create( _client( BYSTANDER_MAIL ) )
    assert r.status_code == 422, r.text
    assert not repo.create_item.called


def test_a_ratio_refusal_with_enforcement_OFF_writes_the_row_and_prints_why( settings, repo, ratio, manager_bridge, monkeypatch, capsys ):
    monkeypatch.setattr( tasks.frs, "get_enforcement_active", lambda: False )
    r = _create( _client( BYSTANDER_MAIL ) )
    assert r.status_code == 201, r.text
    assert repo.create_item.called
    out = capsys.readouterr().out
    assert "[task WARN] ratio gate on task create" in out
    assert "enforcement OFF" in out
    assert "write NOT blocked" in out


# ═══════════════════════════════════════════════════════════════════════════════════
# 1189 · a non-operator P0 skips the ratio gate, and every use is logged with its counts
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_P0_from_a_non_operator_passes_a_refusing_gate_and_logs_the_exemption( settings, repo, ratio, manager_bridge, monkeypatch, capsys ):
    # The priority firewall is a separate door (a seat may not mint P0); it is opened here so
    # only the ratio gate's P0 exemption is under test. The CONTROL above shows these counts refuse a P2.
    monkeypatch.setattr( tasks.priority_firewall, "refusal_for_priority_create", lambda **kw: None )
    r = _create( _client( BYSTANDER_MAIL ), priority="P0", title="a P0 whose skip must be visible" )
    assert r.status_code == 201, r.text
    out = capsys.readouterr().out
    assert "ratio-gate P0 EXEMPTION used by maria 145bf6c7" in out
    assert "a P0 whose skip must be visible" in out
    assert "created=10 closed=1" in out
    assert "OPERATOR EXEMPTION" not in out


# ═══════════════════════════════════════════════════════════════════════════════════
# 1194->1223 · the cc-task: mirror lane permits WITHOUT printing the permissive reading
# ═══════════════════════════════════════════════════════════════════════════════════

def test_CONTROL_a_permitted_epic_row_prints_the_ratio_reading( settings, repo, ratio, manager_bridge, capsys ):
    repo.count_created_and_closed.return_value = dict( ALLOWING_COUNTS )
    r = _create( _client( BYSTANDER_MAIL ) )
    assert r.status_code == 201, r.text
    assert _reading_line( capsys.readouterr().out ), "the permissive path printed no reading, so the arm below proves nothing"


def test_a_mirror_lane_row_is_created_without_the_ratio_reading( settings, repo, ratio, manager_bridge, capsys ):
    repo.count_created_and_closed.return_value = dict( ALLOWING_COUNTS )
    r = _create( _client( BYSTANDER_MAIL ), correlation_key=f"{rules.MIRROR_KEY_PREFIX}some-harness-task" )
    assert r.status_code == 201, r.text
    assert repo.create_item.called
    assert _reading_line( capsys.readouterr().out ) is None, "harness traffic must not drown the permit signal"


def _reading_line( out ):
    expected = rules.ratio_gate_reading(
        created     = ALLOWING_COUNTS[ "created" ],
        closed      = ALLOWING_COUNTS[ "closed" ],
        allow_below = 1.0,
        verdict     = "allow",
    )
    return next( ( line for line in out.splitlines() if line == expected ), None )


# ═══════════════════════════════════════════════════════════════════════════════════
# 2218-2219 · an approval-settings write that cannot persist says NOTHING was applied
# ═══════════════════════════════════════════════════════════════════════════════════

def test_an_approval_settings_write_that_fails_to_persist_is_a_500_saying_unchanged( settings, monkeypatch ):
    def _disk_full( **updates ): raise OSError( "No space left on device" )
    monkeypatch.setattr( tasks.approval, "set_overrides", _disk_full )
    r = _client( OPERATOR_EMAIL ).patch( "/api/tasks/approval-settings", json={ "enforcement_active": True } )
    assert r.status_code == 500, r.text
    detail = r.json()[ "detail" ]
    assert "No space left on device" in detail
    assert "UNCHANGED" in detail


# ═══════════════════════════════════════════════════════════════════════════════════
# 2273-2286 · the manager-pull toggle: success reads back, and both failures are honest
# ═══════════════════════════════════════════════════════════════════════════════════

def test_the_manager_pull_toggle_returns_the_value_READ_BACK_not_the_value_asked( monkeypatch, capsys ):
    asked = [ ]
    def _setter( disabled ):
        asked.append( disabled )
        return "read-back-sentinel"
    monkeypatch.setattr( tasks.approval, "set_manager_pull_disabled", _setter )
    r = _client( admin=True ).patch( "/api/tasks/manager-pull", json={ "disabled": True } )
    assert r.status_code == 200, r.text
    assert asked == [ True ]
    assert r.json() == { "disabled": "read-back-sentinel", "source": "override" }
    assert "manager-pull toggle set by admin@test: disabled=read-back-sentinel" in capsys.readouterr().out


def test_the_manager_pull_toggle_turns_a_refused_value_into_a_422( monkeypatch ):
    def _refuse( disabled ): raise ValueError( "manager pull must be a real boolean" )
    monkeypatch.setattr( tasks.approval, "set_manager_pull_disabled", _refuse )
    r = _client( admin=True ).patch( "/api/tasks/manager-pull", json={ "disabled": False } )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == "manager pull must be a real boolean"


def test_the_manager_pull_toggle_that_fails_to_persist_is_a_500_saying_unchanged( monkeypatch ):
    def _disk_full( disabled ): raise OSError( "read-only file system" )
    monkeypatch.setattr( tasks.approval, "set_manager_pull_disabled", _disk_full )
    r = _client( admin=True ).patch( "/api/tasks/manager-pull", json={ "disabled": True } )
    assert r.status_code == 500, r.text
    assert "read-only file system" in r.json()[ "detail" ]
    assert "UNCHANGED" in r.json()[ "detail" ]


# ═══════════════════════════════════════════════════════════════════════════════════
# 2391-2396 · a stored request naming an unruled move is a 500, never a silent zero
# ═══════════════════════════════════════════════════════════════════════════════════

def _badge_session( rows, monkeypatch ):
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = rows

    @contextmanager
    def _fake_get_db():
        yield session

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )


def test_CONTROL_ruled_pending_requests_are_counted( monkeypatch ):
    _badge_session( [ ( approval.MOVE_ADMIT, request_lifecycle.REQUEST_PENDING ) ], monkeypatch )
    r = _client().get( "/api/tasks/request-badges" )
    assert r.status_code == 200, r.text
    assert r.json()[ request_lifecycle.BADGE_HOLDING_AREA ] == 1


def test_a_pending_request_with_an_unruled_move_is_a_500_with_its_own_words( monkeypatch ):
    _badge_session( [ ( "teleport", request_lifecycle.REQUEST_PENDING ) ], monkeypatch )
    r = _client().get( "/api/tasks/request-badges" )
    assert r.status_code == 500, r.text
    detail = r.json()[ "detail" ]
    assert "no ruled badge" in detail
    assert "no badge is ruled for move 'teleport'" in detail, "the 500 must carry the lifecycle's own words"


# ═══════════════════════════════════════════════════════════════════════════════════
# 3025-3032 · id_prefix is classified: junk is refused, a full UUID is normalized
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_junk_id_prefix_is_refused_before_it_reaches_the_query( repo ):
    r = _client().get( "/api/tasks", params={ "id_prefix": "zz", "count_only": "true" } )
    assert r.status_code == 422, r.text
    assert "is not a task reference" in json.dumps( r.json() )
    assert not repo.count_tasks.called


def test_a_full_uuid_id_prefix_reaches_the_query_in_compact_form( repo ):
    repo.count_tasks.return_value = 1
    full = uuid.uuid4()
    r = _client().get( "/api/tasks", params={ "id_prefix": str( full ), "count_only": "true" } )
    assert r.status_code == 200, r.text
    assert repo.count_tasks.call_args.kwargs[ "id_prefix" ] == full.hex


def test_an_eight_hex_id_prefix_reaches_the_query_as_the_normalized_prefix( repo ):
    repo.count_tasks.return_value = 1
    r = _client().get( "/api/tasks", params={ "id_prefix": "C5FAC934", "count_only": "true" } )
    assert r.status_code == 200, r.text
    kind, value = rules.classify_task_ref( "C5FAC934" )
    assert kind != rules.TASK_REF_FULL
    assert repo.count_tasks.call_args.kwargs[ "id_prefix" ] == value


# ═══════════════════════════════════════════════════════════════════════════════════
# 3838-3841 · the ratio settings PATCH: a refused value is 422, a failed write is 500
# ═══════════════════════════════════════════════════════════════════════════════════

def test_a_ratio_settings_value_the_writer_refuses_is_a_422( monkeypatch ):
    def _refuse( **kw ): raise ValueError( "window_hours must be at least 1" )
    monkeypatch.setattr( tasks.frs, "set_overrides", _refuse )
    r = _client( admin=True ).patch( "/api/tasks/flow-ratio/settings", json={ "window_hours": 12 } )
    assert r.status_code == 422, r.text
    assert r.json()[ "detail" ] == "window_hours must be at least 1"


def test_a_ratio_settings_write_that_fails_to_persist_is_a_500_saying_unchanged( monkeypatch ):
    def _disk_full( **kw ): raise OSError( "No space left on device" )
    monkeypatch.setattr( tasks.frs, "set_overrides", _disk_full )
    r = _client( admin=True ).patch( "/api/tasks/flow-ratio/settings", json={ "allow_below": 1.5 } )
    assert r.status_code == 500, r.text
    assert "No space left on device" in r.json()[ "detail" ]
    assert "UNCHANGED" in r.json()[ "detail" ]
