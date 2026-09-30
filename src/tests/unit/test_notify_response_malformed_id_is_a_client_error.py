"""
A malformed `notification_id` on POST /api/notify/response is the CLIENT's error,
and must not be reported as the SERVER's.

THE INCIDENT (row 96cf5cec, amendment [9]; measured on live :7999 2026-09-06):

    malformed id  {"notification_id": "not-a-uuid", …}  ->  500
        "Response submission failed: badly formed hexadecimal UUID string"
    well-formed but absent                              ->  404   <- always correct
    missing id                                          ->  422   <- always correct

🔴 THE TWO CONTROLS ARE WHAT MADE IT A FINDING RATHER THAN A COMPLAINT. Both
neighbouring cases were handled correctly and only the malformed one fell through
— one branch missing, not a route without error handling. So this file keeps all
three, not just the one that moved: a guard that asserts only the fixed case
cannot tell you the fix left its neighbours alone.

MECHANISM: `_submit_response_sync` called `uuid.UUID( notification_id )` inside
the handler body. The ValueError crossed `asyncio.to_thread` into
`submit_notification_response`'s blanket `except Exception`, which turns
everything it catches into a 500. 500 tells a caller THE SERVER BROKE — it did
not, and a client retrying on 5xx retries a request that can never succeed.

🔴 AND THE OTHER ARM IS NON-NEGOTIABLE (María's DONE MEANS #5 on that row, her
words): *"otherwise 'return success' is satisfied by never refusing anything."*
Same trap one door along — a change that simply stopped ever returning 500 would
satisfy the first case here and be STRICTLY WORSE than the defect. So
`test_a_genuine_server_failure_still_returns_500` holds that line, and it is the
load-bearing case in this file rather than a courtesy.

⚠️ WHY 422 AND NOT 400 — THIS IS NOT A NEW CONTRACT CHOICE. The endpoint already
answers 422 for a MISSING notification_id, so matching it is consistency with
this route's own precedent, not a policy decision taken on someone else's behalf.

⚠️ LAYER. These drive the REAL router over HTTP through TestClient, because the
incident entered at HTTP. A test calling `_submit_response_sync` directly would
prove the helper parses and say nothing about whether the route reaches that
branch — a helper-level receipt and a path-level receipt are different claims.
The app is assembled from the router alone (the house pattern in
test_notifications_api.py) rather than from `lupin_app.main`, which cannot be
imported in a worktree at all: it needs JWT_SECRET_KEY from the repo-root `.env`,
which is gitignored and deliberately not provisioned into worktrees.

:7999-eligible — no server, no network, no persistent state; the DB is mocked.
"""

import uuid as uuid_module
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt
from cosa.rest.routers.notifications import router


@pytest.fixture
def client():
    """
    The real notifications router, over a real HTTP stack.

    The credential dependency is stood in for, because what this file measures is the id
    handling BEHIND the door. The door's own refusal of an uncredentialed caller is pinned
    in test_the_answer_door_requires_a_credential_and_records_who.py (row e20e249a).
    """
    app = FastAPI()
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    app.include_router( router )
    with TestClient( app, raise_server_exceptions=False ) as c:
        yield c
    app.dependency_overrides.clear()


def _db_returning( notification ):
    """A get_db context manager whose repository returns `notification`."""
    session = MagicMock()

    class _Ctx:
        def __enter__( self ):  return session
        def __exit__ ( self, *a ): return False

    return _Ctx()


# ---------------------------------------------------------------------------
# THE CASE THAT MOVED
# ---------------------------------------------------------------------------

@pytest.mark.parametrize( "bad_id", [
    "not-a-uuid",
    "nonexistent-uuid-12345",          # the id the smoke test actually sends
    "12345",
    "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
    "notification_1757190000_ab12cd",  # notifications.js:19037's synthesized shape
] )
def test_a_malformed_notification_id_is_a_client_error_not_a_server_error( client, bad_id ):
    """
    ⚠️ THE LAST PARAMETER IS NOT DECORATIVE. `notification_<epoch>_<random>` is
    built at notifications.js:19037 when the server sends no id_hash. Today it is
    a DOM element id and never reaches this endpoint (row 96cf5cec, [10]) — but
    "constructible and merely unconnected" is not "unreachable" ([11], María's
    framing), and nothing prevents the connection or would notice it. Pinning the
    shape here means that if it ever does arrive, it arrives as a 4xx.
    """
    r = client.post( "/api/notify/response",
                     json={ "notification_id": bad_id, "response_value": "yes" } )

    assert r.status_code == 422, (
        f"a malformed id must be a client error; got {r.status_code}. "
        f"A 500 here says the SERVER broke when the CLIENT sent a bad id, and it "
        f"teaches a caller to retry a request that can never succeed."
    )
    assert "not a valid UUID" in r.json()[ "detail" ]
    assert bad_id in r.json()[ "detail" ], "the refusal must name the id it rejected"


# ---------------------------------------------------------------------------
# 🔴 THE OTHER ARM — without this, "stop returning 500" is satisfied by never
# returning 500, which is strictly worse than the defect.
# ---------------------------------------------------------------------------

def test_a_genuine_server_failure_still_returns_500( client ):
    """A well-formed id whose DB read explodes is the SERVER's fault. Still 500."""
    def _boom( *a, **k ):
        raise RuntimeError( "postgres is on fire" )

    with patch( "cosa.rest.routers.notifications.get_db", _boom ):
        r = client.post( "/api/notify/response",
                         json={ "notification_id": str( uuid_module.uuid4() ),
                                "response_value" : "yes" } )

    assert r.status_code == 500, (
        f"got {r.status_code}. A real server failure must KEEP saying 500 — if the "
        f"malformed-id fix widened far enough to swallow this, it satisfied the "
        f"first case in this file by making the endpoint incapable of reporting a "
        f"fault at all."
    )


# ---------------------------------------------------------------------------
# THE NEIGHBOURS — always correct, and the fix must leave them that way
# ---------------------------------------------------------------------------

def test_a_missing_notification_id_still_returns_422( client ):
    r = client.post( "/api/notify/response", json={ "response_value": "yes" } )
    assert r.status_code == 422
    assert "required" in r.json()[ "detail" ]


def test_a_well_formed_but_absent_id_still_returns_404( client ):
    """
    Well-formed and not in the DB is NOT-FOUND, and must not be dragged into the
    malformed bucket: 422 here would tell a caller its id was malformed when it
    was perfectly well formed and simply gone.
    """
    absent = str( uuid_module.uuid4() )
    ctx    = _db_returning( None )

    with patch( "cosa.rest.routers.notifications.get_db", return_value=ctx ), \
         patch( "cosa.rest.routers.notifications.NotificationRepository" ) as MockRepo:
        MockRepo.return_value.get_by_id = Mock( return_value=None )
        r = client.post( "/api/notify/response",
                         json={ "notification_id": absent, "response_value": "yes" } )

    assert r.status_code == 404
    assert absent in r.json()[ "detail" ]


def test_the_parse_happens_before_the_database_is_opened( client ):
    """
    The refusal must not cost a connection. `get_db` is booby-trapped to fail the
    test if it is called at all — a malformed id is rejected on the argument, so
    nothing downstream should run.

    ⚠️ AND THIS IS WHY THE 422 CASE ABOVE IS NOT ENOUGH ON ITS OWN: the endpoint
    could return 422 while still opening a session and reading, and every
    status-code assertion in this file would stay green.
    """
    called = []

    def _tripwire( *a, **k ):
        called.append( 1 )
        raise AssertionError( "get_db was opened for an id that never parsed" )

    with patch( "cosa.rest.routers.notifications.get_db", _tripwire ):
        r = client.post( "/api/notify/response",
                         json={ "notification_id": "not-a-uuid", "response_value": "yes" } )

    assert r.status_code == 422
    assert called == [], "the malformed id reached the database layer"
