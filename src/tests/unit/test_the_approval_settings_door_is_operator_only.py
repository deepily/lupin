#!/usr/bin/env python3
"""
THE APPROVAL-SETTINGS WRITE DOOR, ENTERED AT THE LAYER AN AGENT WOULD ENTER AT.

🔨 RICK, 2026-09-08: "Only the server writes it." Agents lose direct file access;
changes go through an authenticated endpoint. He accepted, knowingly, that a seat
editing the file today breaks.

WHAT WAS THERE BEFORE. Measured at `2da8896f` with a fixed-string `git log --all -S`
sweep and working positive controls (6 / 4 / 17 / 9 against zeros for every symbol this
work adds): `task-approval-settings.json` carries FIVE override keys and exactly ONE —
`manager_pull_disabled` — had a validated writer and an HTTP door. The other four had
NO WRITER AT ALL, so hand-editing was the only way in and it had no validation
whatsoever. That is the "guard on the door nobody could open" shape, four times over.

🔴 WHY THESE ARMS DRIVE HTTP AND NOT `set_overrides` DIRECTLY. A module at 100% that
the app never mounts is a real shape in this tree, and every test that builds the
component stays green while the door stands open. `test_the_approval_settings_writer_
validates.py` covers the writer itself; these arms exist for the one fact it cannot
state — the gate is REACHED, with the value the handler actually has.

⚠️ WHAT THESE ARMS CANNOT PROVE, so nobody quotes them for more than they carry. This
door refuses a caller who is not an operator. It does NOT stop a seat with a text
editor from writing the file directly: every Claude seat runs as uid 1001 and owns it,
so `chmod` cannot separate Rick from the workers. The endpoint is the SANCTIONED path;
it is not the ONLY one. Closing that needs a deployment change (a distinct service UID)
or a signed-write scheme, and neither is in this file.
"""
import json
import os
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Match

_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest import task_approval_settings as approval
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

OPERATOR_EMAIL = "ricardo.felipe.ruiz@gmail.com"
BYSTANDER_MAIL = "somebody.else@example.com"

DOOR = "/api/tasks/approval-settings"


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """
    The override file, inside tmp_path, with Rick mapped to the operator account.

    🔴 WITHOUT THIS THE ARMS WOULD MEASURE WHOEVER HAPPENS TO BE AN APPROVER TODAY — an
    operator-editable file deciding a test result. And they would WRITE THE LIVE FILE,
    which currently holds Rick's standing rescission (`manager_pull_disabled: true`);
    a test that flips it would switch the fleet's pull gate back on.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    target.write_text( json.dumps( {
        "approvers"         : [ "rick" ],
        "approver_accounts" : { OPERATOR_EMAIL: "rick" },
    } ) )
    approval._cache_mtime = None
    return target


def _client( account_email ):
    """
    A client whose ONE variable is the login account the server resolves.

    `authenticated_account_email` is overridden rather than stubbed on the module, so
    the handler resolves it exactly as production does — through its own dependency.
    `None` is EVERY AGENT SEAT IN THE FLEET: API-key auth, no account.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


# ---------------------------------------------------------------------------
# The isolation control FIRST — a green file must not also be consistent with
# these arms reading and WRITING the real fleet settings file.
# ---------------------------------------------------------------------------

def test_the_arms_are_reading_the_TEMP_file_and_not_the_fleet_one( settings ):
    """
    If this fails, every other result in this file is about the live deployment.
    """
    assert approval.override_path() == str( settings )
    assert "projects-data" not in approval.override_path()
    assert "/var/lupin"    not in approval.override_path()


# ── the door refuses ─────────────────────────────────────────────────────────

def test_an_API_KEY_ONLY_caller_is_REFUSED( settings ):
    """
    THE CASE THAT MATTERS: every agent seat in this fleet is exactly this caller.

    It holds a valid shared fleet credential and NO login account, so `account_email`
    is None. Rick's ruling closed precisely this: identity from a validated account,
    never from a name a caller types.
    """
    response = _client( None ).patch( DOOR, json={ "enforcement_active": True } )
    assert response.status_code == 403, response.text
    assert json.loads( settings.read_text() ).get( "enforcement_active" ) is None, (
        "the door answered 403 and the setting was written anyway — a refusal that "
        "does not refuse."
    )


def test_a_NON_OPERATOR_ACCOUNT_is_REFUSED( settings ):
    """
    A real, signature-validated login that is not Rick's. Proves the gate keys on WHICH
    account, not merely on an account being present.
    """
    response = _client( BYSTANDER_MAIL ).patch( DOOR, json={ "enforcement_active": True } )
    assert response.status_code == 403, response.text
    assert json.loads( settings.read_text() ).get( "enforcement_active" ) is None


def test_the_refusal_does_NOT_teach_the_caller_to_edit_the_file( settings ):
    """
    🔴 THE DEFECT THIS ROW EXISTS TO CLOSE, ONE LEVEL UP: the refusal for the
    unsanctioned path must not PRESCRIBE the unsanctioned path. `refusal_for_pull` did
    exactly that until 2026-09-08 — "clears manager_pull_disabled in <path>" — which is
    how a rule teaches its own bypass.
    """
    detail = _client( None ).patch( DOOR, json={ "enforcement_active": True } ).json()[ "detail" ]
    assert "task-approval-settings.json" not in detail
    assert "flow-ratio/"                 not in detail


# ── the door permits — THE POSITIVE ARM ──────────────────────────────────────

def test_the_OPERATOR_SUCCEEDS_and_the_setting_TAKES_EFFECT( settings ):
    """
    THE POSITIVE ARM. Without it the file above proves only that the door can say no,
    which is also true of a door that is nailed shut.

    Asserts the EFFECTIVE value through the public reader, not the response body — a
    handler could echo what it was sent while writing nothing.
    """
    response = _client( OPERATOR_EMAIL ).patch( DOOR, json={ "enforcement_active": True } )
    assert response.status_code == 200, response.text

    assert json.loads( settings.read_text() )[ "enforcement_active" ] is True
    approval._cache_mtime = None
    assert approval.get_enforcement_active() is True

    assert response.json()[ "enforcement_active" ][ "value" ]  is True
    assert response.json()[ "enforcement_active" ][ "source" ] == "override"


def test_the_operator_can_write_EVERY_key_that_had_no_door( settings ):
    """
    The four keys that had no writer at all before this. One arm each, because "the
    door works" proved on one key says nothing about the other three.
    """
    client = _client( OPERATOR_EMAIL )
    for payload, key, expected in [
        ( { "default_to_holding": True },                  "default_to_holding",  True ),
        ( { "manager_pull_disabled": False },              "manager_pull_disabled", False ),
        ( { "approvers": [ "rick", "maria" ] },            "approvers",  [ "rick", "maria" ] ),
        ( { "approver_accounts": { "A@B.COM": "rick" } },  "approver_accounts", { "a@b.com": "rick" } ),
    ]:
        assert client.patch( DOOR, json=payload ).status_code == 200, payload
        assert json.loads( settings.read_text() )[ key ] == expected


def test_the_READ_door_is_open_to_an_ordinary_seat( settings ):
    """
    DELIBERATE ASYMMETRY: the write is operator-only, the read is not.

    A seat that cannot see which gates are on cannot understand the refusal it just
    got, and would go looking in the file — which is the behaviour this whole row is
    trying to stop.
    """
    response = _client( None ).get( DOOR )
    assert response.status_code == 200, response.text
    assert set( response.json() ) == set( approval.WRITABLE_KEYS )


# ── the values it refuses ────────────────────────────────────────────────────

@pytest.mark.parametrize( "bad", [ "false", "true", "no", "0", 0, 1, [ ], { } ] )
def test_a_NON_BOOLEAN_is_refused_at_the_model_not_coerced( settings, bad ):
    """
    🔴 "false" IS THE VALUE THIS MODULE HAS BEEN BITTEN BY TWICE. `bool( "false" )` is
    True, so a lenient model would switch the gate ON for a caller who typed the word
    off. `StrictBool` refuses it at 422 before the handler body runs.
    """
    response = _client( OPERATOR_EMAIL ).patch( DOOR, json={ "enforcement_active": bad } )
    assert response.status_code == 422, f"{bad!r} was accepted: {response.text}"
    assert json.loads( settings.read_text() ).get( "enforcement_active" ) is None


def test_an_EMPTY_body_is_422_rather_than_a_silent_no_op( settings ):
    """
    A 200 for a body that changes nothing reports a write that never happened.
    """
    assert _client( OPERATOR_EMAIL ).patch( DOOR, json={ } ).status_code == 422


def test_an_UNKNOWN_key_is_REPORTED_rather_than_ignored( settings ):
    """
    Pydantic IGNORES unknown fields by default, so a typo would return 200 having
    changed nothing and the operator would conclude the switch is broken. `extra=forbid`
    is a deliberate choice against this router's prevailing default.
    """
    response = _client( OPERATOR_EMAIL ).patch( DOOR, json={ "enforcment_active": True } )
    assert response.status_code == 422, response.text


def test_a_BAD_key_in_a_TWO_KEY_call_writes_NEITHER( settings ):
    """
    Validation completes for every key before the file is touched, so a half-applied
    call cannot leave the gate in a state the caller never asked for and cannot see.
    """
    response = _client( OPERATOR_EMAIL ).patch( DOOR, json={
        "enforcement_active": True,
        "approvers"         : [ "rick", "" ],      # the blank is the offender
    } )
    assert response.status_code == 422, response.text
    on_disk = json.loads( settings.read_text() )
    assert on_disk.get( "enforcement_active" ) is None, (
        "the good key was written before the bad one was rejected — the call "
        "half-applied."
    )


def test_a_write_PRESERVES_an_unrelated_key( settings ):
    """
    Clobbering `approvers` while flipping a toggle would take the approval gate down as
    a side effect of an unrelated switch.
    """
    assert _client( OPERATOR_EMAIL ).patch(
        DOOR, json={ "enforcement_active": True } ).status_code == 200
    assert json.loads( settings.read_text() )[ "approver_accounts" ] == { OPERATOR_EMAIL: "rick" }


# ── the route exists at all ──────────────────────────────────────────────────

@pytest.mark.parametrize( "method, handler", [
    ( "GET",   "get_approval_settings" ),
    ( "PATCH", "patch_approval_settings" ),
] )
def test_the_route_is_NOT_SHADOWED_by_its_parameterised_sibling( method, handler ):
    """
    🔴 THIS EXACT DEFECT HAS SHIPPED TWICE IN THIS ROUTER. A literal path registered
    AFTER `PATCH /tasks/{task_id}` resolves to `patch_task` and answers 422 "invalid
    UUID" — `/api/tasks/manager-pull` shipped that way, and `/api/tasks/flow-ratio`
    answered 422 in production all evening for the same reason.

    Asks the ASSEMBLED app which route a request resolves to. Reading the source cannot
    answer this: registration ORDER is the variable, and it is invisible at any single
    line.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    scope = { "type": "http", "path": DOOR, "method": method,
              "headers": [ ], "query_string": b"", "root_path": "" }
    for route in app.routes:
        if route.matches( scope )[ 0 ] == Match.FULL:
            assert route.endpoint.__name__ == handler, (
                f"{method} {DOOR} resolves to {route.endpoint.__name__}, not {handler} "
                f"— it is shadowed by an earlier parameterised sibling."
            )
            return
    pytest.fail( f"{method} {DOOR} matches no route at all" )
