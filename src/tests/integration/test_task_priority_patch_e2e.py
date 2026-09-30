#!/usr/bin/env python3
"""
THE PRIORITY EDIT NOBODY HAD WATCHED THE SERVER ANSWER — PATCH /api/tasks/{id}
exercised through the HTTP door with the exact envelope the browser sends.

WHY THIS FILE EXISTS. Commit `e2c353fc` added Rick's third pair to the shared actions
cell — a `.task-priority-select` and a `.task-priority-update` button — and proved the
CLIENT half with seven arms in `row_control_redesign.test.ts` plus four mutations. What
none of those arms can reach is the other end of the wire: `_handlePriorityUpdateClick`
calls `_patchTaskFields`, which PATCHes `{ actor, authority: "user_direct", priority }`
to `/api/tasks/{id}` — and **no test had ever watched the server accept or refuse that
body**. The client arms mock `authedFetch`, so they are green whatever the server does,
including 422 on every press.

WHAT EACH ARM CLAIMS, and none of them claims more:

  1. a valid priority is STORED and READABLE BACK — read from the store with a second
     request, never from the PATCH response's own echo, because an endpoint that
     returned the value it was handed without writing it would satisfy an echo check
  2. an INVALID priority is REFUSED in the server's own words, the row does NOT move,
     and the SAME ROW through the SAME DOOR accepts a valid value immediately after —
     without that last leg the 422 is equally consistent with a door that refuses
     everything
  3. `authority: "user_direct"` — the literal the client hardcodes — is ACCEPTED, and
     the field is REALLY CHECKED. Two legs, one variable. The acceptance leg alone
     would pass just as well against a server that ignores `authority` entirely, which
     is exactly the state that would let a client typo ship unnoticed
  4. THE FILE'S NEGATIVE CONTROL: a PATCH that touches no priority at all still works,
     so nothing above can be explained by the endpoint being broken

🔴 AND WHAT THIS IS NOT PROOF OF. It does not prove the button reaches this door — that
is the per-pane client work, and the two halves meet only in the payload shape written
out in `CLIENT_ENVELOPE` below. It does not prove authorization: `actor` is
caller-DECLARED on this endpoint exactly as it is on the transition door, so this
watches a policy answer and not a security boundary.

VENUE: :7999-eligible, by the same reasoning as `test_task_approval_gate_e2e.py` — a
real Postgres round-trip inside an outer transaction rolled back at teardown, so no row
written here outlives the test. No server, no network.
"""
import os
import sys
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Bootstrap (conftest also does this; kept for direct-invocation parity)
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db import database as db_module
from cosa.rest.routers import tasks
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest import task_store_rules as rules


# The literals `_patchTaskFields` hardcodes (notifications.js, symbol
# `NotificationManager._patchTaskFields`). Named here so that a client-side change to
# either one leaves this file describing a body nobody sends — which a reader can see,
# where a bare inline string would just quietly stop matching.
CLIENT_ACTOR     = "operator browser"
CLIENT_AUTHORITY = "user_direct"


@pytest.fixture
def txn_session( monkeypatch ):
    """
    A real Postgres Session joined to an OUTER transaction rolled back at teardown, so
    the create and patch seams see each other's writes yet NOTHING persists.

    Copied verbatim from `test_task_approval_gate_e2e.py` on María's instruction, and
    deliberately not re-invented: a bespoke isolation fixture is how a test ends up
    writing to the live fleet's board.
    """
    connection = db_module.engine.connect()
    outer      = connection.begin()
    session    = Session( bind=connection, join_transaction_mode="create_savepoint" )

    @contextmanager
    def _shared_get_db():
        try:
            yield session
            session.commit()             # → RELEASE SAVEPOINT; visible within the outer txn
        except Exception:
            session.rollback()           # → ROLLBACK TO SAVEPOINT only
            raise
        # deliberately NOT closed — the next get_db() block reuses this session

    monkeypatch.setattr( tasks, "get_db", _shared_get_db )
    yield session

    session.close()
    outer.rollback()                     # discard every savepoint — zero persistent state
    connection.close()


@pytest.fixture
def client( txn_session ):
    """TestClient over the real tasks router, auth overridden (this tests the field seam, not auth)."""
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def _create_row( client, **overrides ):
    """Mint a row through the real endpoint. P0 so the flow-ratio gate cannot refuse it."""
    body = {
        "item_class" : "task",
        "title"      : "priority-patch probe (e2e)",
        "project"    : "lupin",
        "created_by" : "maya d1cbb9ef",
        "priority"   : "P0",
        "status"     : "queued",
    }
    body.update( overrides )
    r = client.post( "/api/tasks", json=body )
    assert r.status_code == 201, f"{r.status_code}: {r.text}"
    item = r.json()
    assert item[ "priority" ] == body[ "priority" ], (
        f"the row minted at priority '{item['priority']}' rather than '{body['priority']}' — "
        f"every arm below measures a MOVE from a known starting value, so it must be known"
    )
    return item


def _patch_priority( client, task_id, priority, authority=CLIENT_AUTHORITY ):
    """
    The browser's request, byte-for-byte in shape.

    `_patchTaskFields` spreads `{ actor, authority }` and then the caller's patch object,
    so a priority update is exactly these three keys and no others. Sending anything more
    here would test a body the client cannot produce — and `TaskPatchIn` sets
    `extra="forbid"`, so an extra key is a 422 that would look like a priority defect.
    """
    return client.patch(
        f"/api/tasks/{task_id}",
        json={ "actor": CLIENT_ACTOR, "authority": authority, "priority": priority },
    )


def _stored_priority( client, task_id ):
    """Read the priority back OUT OF THE STORE — never off the PATCH response's echo."""
    r = client.get( f"/api/tasks/{task_id}" )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()[ "priority" ]


def test_a_VALID_priority_is_STORED_and_READABLE_BACK( client ):
    """
    The accept claim, read from the store rather than from the response.

    🔴 THE SECOND READ IS THE WHOLE TEST. `patch_task` returns `_serialize_item( item )`
    off the in-session object, so a handler that validated the value and never wrote it
    would still echo P2 here. The GET is a separate request through a separate seam and
    is the only leg that can tell a write from an echo.
    """
    item = _create_row( client )

    r = _patch_priority( client, item[ "id" ], "P2" )
    assert r.status_code == 200, (
        f"the browser's own priority envelope was refused ({r.status_code}: {r.text}) — "
        f"every press of the Update button would land here"
    )
    assert r.json()[ "item" ][ "priority" ] == "P2", f"the response echoed: {r.text}"

    assert _stored_priority( client, item[ "id" ] ) == "P2", (
        "the PATCH answered 200 and echoed P2, but a fresh read of the row still returns "
        "the old priority — the endpoint validated the edit without storing it"
    )


def test_an_INVALID_priority_is_REFUSED_in_the_SERVER_S_OWN_WORDS_and_the_row_does_NOT_move( client ):
    """
    🔴 THE LOAD-BEARING TEST IN THIS FILE, and the positive control at the end is what
    stops it passing for the wrong reason.

    The refusal must carry the offending value AND the list of legal ones, because the
    client puts `body.detail` straight into the operator's row stripe — a 422 whose text
    does not name the alternatives leaves the operator with a red stripe and no recourse.
    """
    item = _create_row( client )

    # ── THE REFUSAL ──────────────────────────────────────────────────────────────
    r = _patch_priority( client, item[ "id" ], "P9" )
    assert r.status_code == 422, (
        f"expected 422, got {r.status_code}: {r.text}\n"
        f"'P9' is not in {rules.VALID_PRIORITIES} and was NOT refused — the field seam "
        f"is storing whatever the wire hands it"
    )
    errors = r.json()[ "detail" ][ "errors" ]
    joined = " ".join( errors )
    assert "P9" in joined, f"the refusal does not name the offending value: {errors}"
    for legal in rules.VALID_PRIORITIES:
        assert legal in joined, (
            f"the refusal omits the legal value '{legal}': {errors}\n"
            f"this text is what the operator sees in the row stripe — a complaint that "
            f"does not list the alternatives is a dead end"
        )

    assert _stored_priority( client, item[ "id" ] ) == "P0", (
        "the request was refused with 422 but the priority moved anyway"
    )

    # ── POSITIVE CONTROL: same row, same door, only the VALUE differs ─────────────
    r = _patch_priority( client, item[ "id" ], "P1" )
    assert r.status_code == 200, (
        f"a valid priority was refused on the same row moments later ({r.status_code}: "
        f"{r.text}) — without this leg the 422 above proves nothing, since a door that "
        f"refused EVERY priority edit would pass the first half of this test"
    )
    assert _stored_priority( client, item[ "id" ] ) == "P1"


def test_the_CLIENT_S_OWN_authority_literal_is_ACCEPTED_and_authority_is_REALLY_CHECKED( client ):
    """
    Two legs, one variable — and the second leg is the reason the first one means
    anything.

    The client hardcodes `authority: "user_direct"`. Asserting only that it is accepted
    would pass identically against a server that never looks at the field, which is the
    state in which a client-side typo would ship silently and forever.
    """
    item = _create_row( client )

    # LEG 1 — the literal the browser sends
    r = _patch_priority( client, item[ "id" ], "P2", authority=CLIENT_AUTHORITY )
    assert r.status_code == 200, (
        f"the client's hardcoded authority '{CLIENT_AUTHORITY}' was refused "
        f"({r.status_code}: {r.text}) — it must be a member of {rules.VALID_AUTHORITIES}"
    )

    # LEG 2 — one character off. If this is ALSO accepted, leg 1 established nothing.
    r = _patch_priority( client, item[ "id" ], "P3", authority="user_direkt" )
    assert r.status_code == 422, (
        f"a misspelled authority was ACCEPTED ({r.status_code}) — the field is not "
        f"validated, so leg 1 above is vacuous and a client typo would never surface"
    )
    assert "user_direkt" in " ".join( r.json()[ "detail" ][ "errors" ] )

    assert _stored_priority( client, item[ "id" ] ) == "P2", (
        "the misspelled-authority request was refused but the priority moved anyway"
    )


def test_a_PATCH_that_names_NO_priority_still_works( client ):
    """
    THE NEGATIVE CONTROL FOR THE WHOLE FILE. A title edit through the same endpoint,
    with the same actor and authority, must succeed.

    Without it, every assertion above is consistent with `PATCH /api/tasks/{id}` being
    broken outright — the refusals would still be 422s and the two acceptance legs would
    be the only failures, which reads as a priority defect rather than a dead door.
    """
    item = _create_row( client )

    r = client.patch(
        f"/api/tasks/{item['id']}",
        json={ "actor": CLIENT_ACTOR, "authority": CLIENT_AUTHORITY, "title": "renamed by the negative control" },
    )
    assert r.status_code == 200, (
        f"an ordinary field PATCH was refused ({r.status_code}: {r.text}) — the door "
        f"itself is broken and nothing else in this file can be read as being about priority"
    )
    assert r.json()[ "item" ][ "title" ] == "renamed by the negative control"
