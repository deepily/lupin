#!/usr/bin/env python3
"""
THE BROWSER'S IDENTITY, GUARDED AT THE DOOR THIS COMMIT OWNS.

Row 9d3a975e. Two endpoints refused an identity the UI believed it had, and the two
refusals do NOT share a cause — the row's "one identity fix, both endpoints" framing
did not survive the measurement, so this file guards two different things.

  LEG 1 — POST /api/tasks/{id}/transition, 403.
      The client mints its actor PER WEBSOCKET SESSION. Captured live in Rick's own
      browser 2026-09-04: body `{"to_status":"queued","actor":"operator foolish
      goat","authority":"user_direct"}`, `Authorization: Bearer <342-char JWT>`,
      response 403 naming "operator foolish goat". The credential was valid and the
      gate never saw it — it was handed `payload.actor` instead. The fix gives the
      gate a second door keyed on the LOGIN ACCOUNT off the validated token, which a
      per-session string cannot be.

  LEG 2 — POST /api/commons/broadcast-to-cc-sessions, 401 — IS NOT GUARDED HERE, AND
      THAT IS DELIBERATE, NOT AN OVERSIGHT. It has a different cause (`broadcast-panel.js`
      carried a second auth path that never refreshed a 30-minute token) and it lives on
      the door-2 branch, which owns every shared client asset after María's split ruling
      2026-09-04. Its two guards travelled WITH the file they read; a guard that outlived
      its subject here would assert about bytes this commit does not carry, and would go
      red for a reason that has nothing to do with what it was written to watch.

⚠️ EVERY ARM WAS REVERTED AND WATCHED GO RED — see this file's git commit for the
patched lines and the failing sets. An assertion nobody has watched fail is not a
guard. SIX OF THE EIGHT mutation arms remain here (arms, not tests — 8 tests, 6 arms);
M7 and M8 drove the client file and travelled with it.
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
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt, authenticated_account_email

NOW = datetime( 2026, 9, 4, 0, 0, tzinfo=timezone.utc )

# The actual string captured off Rick's browser, not a stand-in. Its whole point is
# that it is regenerated per websocket session, so no allowlist entry can match it.
BROWSER_ACTOR   = "operator foolish goat"
OPERATOR_EMAIL  = "the.operator@example.com"
STRANGER_EMAIL  = "somebody.else@example.com"


# ─────────────────────────────── LEG 1 ───────────────────────────────────────


def _item( **overrides ):
    fields = dict(
        id                  = uuid.uuid4(),
        item_class          = "bug",
        title               = "a row waiting in the holding area",
        body                = None,
        project             = "lupin",
        owner_persona       = "rio",
        accountable_manager = "maria",
        created_by          = "maria 4f98d12f",
        status              = "not_approved",
        blocked_by          = [ ],
        next_chase_ts       = None,
        gate_class          = "none",
        priority            = "P0",
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
    fake = MagicMock()
    fake.statuses_for_ids.return_value = { }

    @contextmanager
    def _fake_get_db():
        yield MagicMock()

    monkeypatch.setattr( tasks, "get_db", _fake_get_db )
    monkeypatch.setattr( tasks, "TaskRepository", lambda session: fake )
    return fake


@pytest.fixture
def settings( tmp_path, monkeypatch ):
    """
    The approval module's override file, inside tmp_path, cache cleared.

    ⚠️ THE INI IS NEVER TOUCHED and this file never asserts about the real fleet
    config. Putting a real account into service is outward-facing and Rick's word
    alone; a test must not make that call on his behalf, and a test that read the
    live file would also go red the day he edits it.
    """
    target = tmp_path / "task-approval-settings.json"
    monkeypatch.setattr( approval, "override_path", lambda: str( target ) )
    monkeypatch.setattr( approval, "_cache", {
        "approvers": None, "enforcement_active": None,
        "default_to_holding": None, "approver_accounts": None,
    } )
    monkeypatch.setattr( approval, "_cache_mtime", None )
    return target


def _write( target, **body ):
    target.write_text( json.dumps( body ) )
    approval._cache_mtime = None


def _client( account_email ):
    """
    A client whose caller is authenticated AND whose login account is `account_email`.

    The two dependencies are overridden SEPARATELY on purpose — that is the shape of
    the defect. `require_api_key_or_jwt` always succeeded; the gate simply never saw
    the second fact. Passing None for the account is the API-key caller, and is what
    reproduces the world before the fix.
    """
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ]      = lambda: "test-user"
    app.dependency_overrides[ authenticated_account_email ] = lambda: account_email
    return TestClient( app )


def _post( client, item, to_status, actor ):
    return client.post( f"/api/tasks/{item.id}/transition",
                        json={ "to_status": to_status, "actor": actor } )


def test_the_isolation_actually_isolates( settings ):
    """
    Runs first, and guards every test below it. Without it a green file is equally
    consistent with the module having read the real fleet settings all along.
    """
    assert str( settings ) == approval.override_path()
    assert "projects-data" not in approval.override_path()


def test_the_browser_actor_is_admitted_when_its_LOGIN_ACCOUNT_is_an_approver(
        repo, settings ):
    """
    🔴 THE ONE THIS FILE EXISTS FOR — Rick's click, at the layer his click enters at.

    The actor is the per-session string he cannot change and no allowlist can match.
    What lets him through is the account on his token. Revert the gate's account door
    and this goes 403 with his own words in it.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True,
            approver_accounts={ OPERATOR_EMAIL: "maria" } )
    item = _item()
    repo.get_by_id_for_update.return_value = item
    repo.apply_transition.return_value = TaskEvent(
        id=1, item_id=item.id, ts=NOW, actor=BROWSER_ACTOR,
        transition="not_approved->queued", receipt_refs=None, authority="user_direct",
    )

    r = _post( _client( OPERATOR_EMAIL ), item, "queued", BROWSER_ACTOR )

    assert r.status_code == 200, (
        f"a logged-in approver could not admit a row from the browser — this is the "
        f"defect of row 9d3a975e, verbatim. Got {r.status_code}: {r.text}"
    )
    repo.apply_transition.assert_called_once()


def test_the_SAME_request_without_a_login_account_is_still_refused( repo, settings ):
    """
    THE NEGATIVE CONTROL, AND IT IS NOT OPTIONAL. Exactly one variable moves against
    the test above — the account. Without this arm, a gate that had simply stopped
    refusing anybody would pass, and the fix would look like a working door while
    being a removed one.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True,
            approver_accounts={ OPERATOR_EMAIL: "maria" } )
    item = _item()
    repo.get_by_id_for_update.return_value = item

    r = _post( _client( None ), item, "queued", BROWSER_ACTOR )

    assert r.status_code == 403, f"the holding area stopped refusing. Got {r.status_code}"
    assert "not an approver" in r.json()[ "detail" ]
    repo.apply_transition.assert_not_called()


def test_a_logged_in_stranger_is_refused_even_holding_a_valid_token( repo, settings ):
    """
    The account door grants nothing to an account nobody mapped. Being authenticated
    is not being an approver, and the fix must not have blurred the two.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True,
            approver_accounts={ OPERATOR_EMAIL: "maria" } )
    item = _item()
    repo.get_by_id_for_update.return_value = item

    r = _post( _client( STRANGER_EMAIL ), item, "queued", BROWSER_ACTOR )

    assert r.status_code == 403, f"an unmapped account approved. Got {r.status_code}"
    repo.apply_transition.assert_not_called()


def test_an_account_mapped_to_a_REVOKED_persona_loses_its_door( repo, settings ):
    """
    The allowlist stays the single place that says who approves. Drop a persona there
    and its accounts go with it — otherwise revoking somebody would need a second edit
    to a second key, and the one you forget is the one that still lets them in.
    """
    _write( settings, approvers=[ "cheech" ], enforcement_active=True,
            approver_accounts={ OPERATOR_EMAIL: "maria" } )
    item = _item()
    repo.get_by_id_for_update.return_value = item

    r = _post( _client( OPERATOR_EMAIL ), item, "queued", BROWSER_ACTOR )

    assert r.status_code == 403, (
        f"an account kept approving after its persona left the allowlist. "
        f"Got {r.status_code}"
    )
    repo.apply_transition.assert_not_called()


def test_the_refusal_names_the_account_the_server_thinks_you_are( repo, settings ):
    """
    The refusal Rick got named a string he had never chosen and listed personas he
    could not become, so it read as a dead end. Whoever hits this next is told the one
    fact that lets them act.
    """
    _write( settings, approvers=[ "maria" ], enforcement_active=True )
    item = _item()
    repo.get_by_id_for_update.return_value = item

    detail = _post( _client( STRANGER_EMAIL ), item, "queued", BROWSER_ACTOR ).json()[ "detail" ]

    assert STRANGER_EMAIL in detail, f"the refusal never says who you are: {detail}"
    assert approval.INI_KEY_APPROVER_ACCOUNTS in detail, (
        f"the refusal never says how a login account gets a door: {detail}"
    )


def test_an_unsigned_token_buys_no_identity():
    """
    THE DOOR IS ONLY STRONGER THAN THE ACTOR STRING IF IT VALIDATES.

    This is the whole reason the account path may be described as more than a policy
    control, so it is measured rather than asserted in a comment. A well-formed JWT
    body signed with the wrong key yields NO email — otherwise an approver identity
    would cost a caller one base64 encode, which is exactly what the actor string
    already costs.
    """
    import asyncio, base64

    def _seg( obj ):
        raw = json.dumps( obj ).encode()
        return base64.urlsafe_b64encode( raw ).rstrip( b"=" ).decode()

    forged = ".".join( [
        _seg( { "alg": "HS256", "typ": "JWT" } ),
        _seg( { "sub": "x", "email": OPERATOR_EMAIL, "exp": 4102444800, "token_type": "access" } ),
        "not-a-real-signature",
    ] )

    got = asyncio.run( authenticated_account_email( authorization=f"Bearer {forged}" ) )
    assert got is None, f"a forged token was accepted as identity {got!r}"


def test_a_missing_or_non_bearer_header_is_None_rather_than_an_exception():
    """
    The dependency authenticates nothing and must never 401 on its own — a route that
    also accepts API keys would start refusing every CLI caller the day it became
    account-aware.
    """
    import asyncio
    assert asyncio.run( authenticated_account_email( authorization=None ) ) is None
    assert asyncio.run( authenticated_account_email( authorization="ck_live_whatever" ) ) is None
