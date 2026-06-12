"""
Integration tests for the unified task store — /api/tasks/* (Phase 1).

Authored by Krishna 🦚 (Lane 2, task-store crew). The unit suite
(test_tasks_router.py / test_task_repository.py / test_task_store_rules.py /
test_task_store_models.py) covers routing + rules + persistence units in
isolation at 100%. THIS suite exercises the REAL stack end to end: live
server, real Postgres rows, real auth credentials, the Alembic-created
schema (CHECK constraint, defaults, FK cascade), and the full item
lifecycle with the append-only audit trail.

VENUE: :8000 monopolize-mode, SCHEDULED ONLY — submit via
POST /api/test-suite/submit (NEVER side-door). Mutates task_items/task_events
rows in the test DB → NOT :7999-eligible.

SHIP GATE (design §3.1 F2 rider, C2 pin): /api/tasks/* may only DEPLOY after
the :7999 async-handlers fix has LANDED. This file rides the repo until then;
scheduling it presupposes the deployed endpoints.

Lifecycle covered:
    create (201, queued, creation event) → get → query filters →
    claim → in_progress → blocked (chase_ts + typed refs) → unblock →
    review → done-with-junk-receipts (422) → done-with-valid-receipts (200) →
    terminal lockout (422) → full events trail shape
Auth matrix: no-auth 401 · X-API-Key 201/200 · Bearer JWT 200.
"""

import os
import uuid

import pytest
import requests
import bcrypt
import secrets

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository


BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"


@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
    api_key   = "ck_live_" + secrets.token_urlsafe( 48 )
    key_bytes = api_key.encode( "utf-8" )
    salt      = bcrypt.gensalt( rounds=12 )
    key_hash  = bcrypt.hashpw( key_bytes, salt ).decode( "utf-8" )

    email = f"test-{uuid.uuid4()}@test.com"

    with get_db() as session:
        user_repo = UserRepository( session )
        user = user_repo.create_user(
            email         = email,
            password_hash = "dummy_hash",
            roles         = [ "service_account" ],
        )
        user.email_verified = True
        user.is_active      = True

        api_key_repo = ApiKeyRepository( session )
        api_key_obj  = api_key_repo.create_key(
            user_id     = user.id,
            key_hash    = key_hash,
            description = "Task-store integration test key",
        )
        key_id  = str( api_key_obj.id )
        user_id = str( user.id )

    yield { "api_key": api_key, "user_id": user_id, "key_id": key_id, "email": email }

    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


def _create_body( **overrides ):
    body = {
        "item_class" : "task",
        "title"      : "integration probe item",
        "project"    : "lupin",
        "created_by" : "krishna 38d15e3b",
    }
    body.update( overrides )
    return body


def _transition( headers, task_id, **body ):
    return requests.post( f"{ENDPOINT}/{task_id}/transition", json=body, headers=headers, timeout=10 )


class TestTaskStoreAuth:
    """Credential matrix against the live server + auth DB (§4.1 AC2)."""

    def test_create_missing_auth_returns_401( self ):
        r = requests.post( ENDPOINT, json=_create_body(), timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"

    def test_query_missing_auth_returns_401( self ):
        r = requests.get( ENDPOINT, timeout=10 )
        assert r.status_code == 401, f"{r.status_code}: {r.text}"

    def test_create_with_api_key_returns_201( self, test_api_key ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = requests.post( ENDPOINT, json=_create_body(), headers=headers, timeout=10 )
        assert r.status_code == 201, f"{r.status_code}: {r.text}"
        assert r.json()[ "status" ] == "queued"

    def test_query_with_jwt_returns_200( self, auth_headers ):
        r = requests.get( ENDPOINT, headers=auth_headers, timeout=10 )
        assert r.status_code == 200, f"{r.status_code}: {r.text}"
        assert "tasks" in r.json() and "count" in r.json()


class TestTaskStoreLifecycle:
    """Full item lifecycle against real Postgres — the R4 determinism proof."""

    def test_full_lifecycle_with_audit_trail( self, test_api_key ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        actor   = "krishna 38d15e3b"

        # 1. create — queued, creation event stamped
        created = requests.post( ENDPOINT, json=_create_body(
            owner_persona       = "krishna",
            accountable_manager = "tiberius",
            gate_class          = "manager",
            priority            = "P1",
        ), headers=headers, timeout=10 )
        assert created.status_code == 201, f"{created.status_code}: {created.text}"
        item = created.json()
        task_id = item[ "id" ]
        assert item[ "status" ] == "queued" and item[ "blocked_by" ] == [ ]
        assert item[ "created_ts" ] is not None and item[ "updated_ts" ] is not None

        # 2. get — round-trips identically
        got = requests.get( f"{ENDPOINT}/{task_id}", headers=headers, timeout=10 )
        assert got.status_code == 200 and got.json()[ "id" ] == task_id

        # 3. query — the deterministic owed-work shape finds it
        q = requests.get( ENDPOINT, headers=headers, timeout=10, params={
            "owner_persona" : "krishna",
            "status"        : "queued",
            "gate_class"    : "manager",
        } )
        assert q.status_code == 200
        assert any( t[ "id" ] == task_id for t in q.json()[ "tasks" ] )

        # 4. claim → in_progress
        for to_status in ( "claimed", "in_progress" ):
            r = _transition( headers, task_id, to_status=to_status, actor=actor )
            assert r.status_code == 200, f"->{to_status}: {r.status_code}: {r.text}"
        assert r.json()[ "item" ][ "status" ] == "in_progress"

        # 5. blocked REQUIRES chase_ts + typed refs (I3 + gate ruling #5)
        bare = _transition( headers, task_id, to_status="blocked", actor=actor )
        assert bare.status_code == 422
        assert len( bare.json()[ "detail" ][ "errors" ] ) == 2

        blocked = _transition( headers, task_id,
                               to_status     = "blocked",
                               actor         = actor,
                               next_chase_ts = "2026-06-13T09:00:00+00:00",
                               blocked_by    = [ { "kind": "user", "id": "rick" } ] )
        assert blocked.status_code == 200, f"{blocked.status_code}: {blocked.text}"
        body = blocked.json()[ "item" ]
        assert body[ "status" ] == "blocked" and body[ "next_chase_ts" ] is not None
        assert body[ "blocked_by" ] == [ { "kind": "user", "id": "rick" } ]

        # 6. unblock clears block state (unblocked = blocked on nothing)
        unblocked = _transition( headers, task_id, to_status="in_progress", actor=actor )
        assert unblocked.status_code == 200
        body = unblocked.json()[ "item" ]
        assert body[ "next_chase_ts" ] is None and body[ "blocked_by" ] == [ ]

        # 7. review → done REJECTS junk receipts (T3 — not theater-able)
        review = _transition( headers, task_id, to_status="review", actor=actor )
        assert review.status_code == 200

        junk = _transition( headers, task_id, to_status="done", actor=actor,
                            receipt_refs={ "doc_path": "trust me" } )
        assert junk.status_code == 422

        bare_done = _transition( headers, task_id, to_status="done", actor=actor )
        assert bare_done.status_code == 422

        # 8. done with VALID receipts lands
        receipts = {
            "commit"   : "6be15f46",
            "test_run" : "ts-82ae2446",
            "qid"      : "c8c73fde-6ce4-4e8d-83d7-c55b5cce65a3",
        }
        done = _transition( headers, task_id, to_status="done", actor=actor,
                            authority="manager_relay", receipt_refs=receipts )
        assert done.status_code == 200, f"{done.status_code}: {done.text}"
        assert done.json()[ "item" ][ "status" ] == "done"
        assert done.json()[ "event" ][ "receipt_refs" ] == receipts

        # 9. terminal lockout — done is append-only
        locked = _transition( headers, task_id, to_status="queued", actor=actor )
        assert locked.status_code == 422
        assert any( "append-only" in e for e in locked.json()[ "detail" ][ "errors" ] )

        # 10. the audit trail tells the whole story, in order (R3)
        trail = requests.get( f"{ENDPOINT}/{task_id}/events", headers=headers, timeout=10 )
        assert trail.status_code == 200
        events = trail.json()[ "events" ]
        transitions = [ e[ "transition" ] for e in events ]
        assert transitions == [
            "->queued",
            "queued->claimed",
            "claimed->in_progress",
            "in_progress->blocked",
            "blocked->in_progress",
            "in_progress->review",
            "review->done",
        ]
        assert events[ -1 ][ "authority" ] == "manager_relay"
        assert all( e[ "actor" ] == actor for e in events[ 1: ] )

    def test_doc_path_receipt_validates_against_live_scope_registry( self, test_api_key ):
        """doc_path receipts resolve via the SERVER's scope registry (container mounts)."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        actor   = "krishna 38d15e3b"

        created = requests.post( ENDPOINT, json=_create_body(), headers=headers, timeout=10 )
        task_id = created.json()[ "id" ]
        for to_status in ( "claimed", "in_progress", "review" ):
            _transition( headers, task_id, to_status=to_status, actor=actor )

        # a file every container mount has — the app INI itself
        good = _transition( headers, task_id, to_status="done", actor=actor,
                            receipt_refs={ "doc_path": "lupin/src/conf/lupin-app.ini" } )
        assert good.status_code == 200, f"{good.status_code}: {good.text}"

    def test_create_rejects_bad_enums_and_writes_nothing( self, test_api_key ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        marker  = f"reject-probe-{uuid.uuid4()}"
        r = requests.post( ENDPOINT, json=_create_body( title=marker, item_class="chore" ),
                           headers=headers, timeout=10 )
        assert r.status_code == 422

        q = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "project": "lupin", "limit": 500 } )
        assert all( t[ "title" ] != marker for t in q.json()[ "tasks" ] )

    def test_get_missing_item_404s( self, test_api_key ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = requests.get( f"{ENDPOINT}/{uuid.uuid4()}", headers=headers, timeout=10 )
        assert r.status_code == 404

    def test_query_rejects_junk_status_filter( self, test_api_key ):
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "status": "finished" } )
        assert r.status_code == 422

    def test_query_rejects_negative_limit( self, test_api_key ):
        """N4 live: limit=-1 is a 422 at the wire — never a Postgres 500."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        r = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "limit": -1 } )
        assert r.status_code == 422

    def test_transition_rejects_junk_receipts_on_non_done( self, test_api_key ):
        """N2 live: junk receipts on ->claimed never land in the audit trail."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        created = requests.post( ENDPOINT, json=_create_body(), headers=headers, timeout=10 )
        task_id = created.json()[ "id" ]
        r = _transition( headers, task_id, to_status="claimed", actor="krishna 38d15e3b",
                         receipt_refs={ "vibes": "good" } )
        assert r.status_code == 422
        trail = requests.get( f"{ENDPOINT}/{task_id}/events", headers=headers, timeout=10 )
        assert [ e[ "transition" ] for e in trail.json()[ "events" ] ] == [ "->queued" ]


class TestTaskStorePhase2WritePaths:
    """Phase 2 live wire: reason on ->dropped, correlation_key filter, /correlate."""

    def test_dropped_requires_reason_and_persists_it( self, test_api_key ):
        """C12 live: ->dropped without reason 422s; with reason it lands on the event row."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        created = requests.post( ENDPOINT, json=_create_body(), headers=headers, timeout=10 )
        task_id = created.json()[ "id" ]

        bare = _transition( headers, task_id, to_status="dropped", actor="tiffany d03e6219" )
        assert bare.status_code == 422
        assert any( "reason is REQUIRED" in e for e in bare.json()[ "detail" ][ "errors" ] )

        reasoned = _transition( headers, task_id, to_status="dropped", actor="tiffany d03e6219",
                                reason="superseded-by-rewrite" )
        assert reasoned.status_code == 200
        assert reasoned.json()[ "event" ][ "reason" ] == "superseded-by-rewrite"

        trail = requests.get( f"{ENDPOINT}/{task_id}/events", headers=headers, timeout=10 )
        assert trail.json()[ "events" ][ -1 ][ "reason" ] == "superseded-by-rewrite"

    def test_query_filters_by_correlation_key( self, test_api_key ):
        """The C1 key is REST-queryable (spool-replay idempotency probe shape)."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        ck      = f"cc-task:{uuid.uuid4()}:5"
        requests.post( ENDPOINT, json=_create_body( correlation_key=ck ), headers=headers, timeout=10 )
        requests.post( ENDPOINT, json=_create_body(), headers=headers, timeout=10 )

        r = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "correlation_key": ck } )
        assert r.status_code == 200
        body = r.json()
        assert body[ "count" ] == 1 and body[ "tasks" ][ 0 ][ "correlation_key" ] == ck

    def test_correlate_restamps_key_with_audit_event( self, test_api_key ):
        """Respawn adoption live: re-stamp + 're-correlated' event; terminal items refuse."""
        headers = { "X-API-Key": test_api_key[ "api_key" ] }
        old_ck  = f"cc-task:{uuid.uuid4()}:3"
        new_ck  = f"cc-task:{uuid.uuid4()}:8"
        created = requests.post( ENDPOINT, json=_create_body( correlation_key=old_ck ), headers=headers, timeout=10 )
        task_id = created.json()[ "id" ]

        r = requests.post( f"{ENDPOINT}/{task_id}/correlate", headers=headers, timeout=10,
                           json={ "correlation_key": new_ck, "actor": "tiffany d03e6219" } )
        assert r.status_code == 200
        body = r.json()
        assert body[ "item" ][ "correlation_key" ] == new_ck
        assert body[ "item" ][ "status" ] == "queued"                     # status untouched
        assert body[ "event" ][ "transition" ] == "re-correlated"
        assert body[ "event" ][ "reason" ] == f"correlation_key: {old_ck} -> {new_ck}"

        # Old key no longer findable; new key is.
        hits = requests.get( ENDPOINT, headers=headers, timeout=10, params={ "correlation_key": old_ck } )
        assert hits.json()[ "count" ] == 0

        # Terminal lockout: drop it, then correlate must 422.
        _transition( headers, task_id, to_status="dropped", actor="tiffany d03e6219", reason="probe cleanup" )
        locked = requests.post( f"{ENDPOINT}/{task_id}/correlate", headers=headers, timeout=10,
                                json={ "correlation_key": old_ck, "actor": "tiffany d03e6219" } )
        assert locked.status_code == 422
        assert any( "immutable" in e for e in locked.json()[ "detail" ][ "errors" ] )
