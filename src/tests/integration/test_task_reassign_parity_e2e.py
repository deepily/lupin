#!/usr/bin/env python3
"""
ITEM B — 3-seam owner-canonicalization parity E2E for task-reassign (Phase-1 §4.3).

The headline gap the three Phase-1 review lenses (Rachel/Krishna/Tiffany) all
flagged: the ONLY end-to-end proof of the 2026-06-18 false-idle guard. The unit
suites (test_task_repository.py / test_tasks_router.py) prove each seam in
ISOLATION with mocks — but the false-idle class is a CROSS-SEAM defect: the
write seam stored a canonical key while the owed-read seam queried the raw
display form, so a re-owned item silently dropped out of BOTH personas' owed
sets ("maría"/"mr. radio" queried, "maria"/"mr radio" stored → zero rows).

This test exercises all THREE seams against a REAL Postgres round-trip and
proves they resolve a display-form owner to the SAME canonical key:

    1. create-write  — POST /api/tasks owner="María" (ACCENTED)  → stored "maria"
    2. patch-write   — PATCH .../{id} owner="Mr. Radio" (PUNCTUATED) → stored "mr radio",
                       the patched event carries the caller `reason`
    3. owed-read     — GET /api/tasks?owner_persona=<DISPLAY FORM>&count_only=true

The proof is the owed-COUNT delta queried BY THE DISPLAY FORM: creating under
"María" raises maría's owed count by 1; reassigning to "Mr. Radio" DROPS maría's
count back AND RAISES mr-radio's count by 1. Deltas (not absolutes) are used on
purpose — María and Mr. Radio are real personas with pre-existing dev rows, and
the round-trip is what's under test, not the absolute cardinality.

VENUE: :7999 AI-discretionary. It does a real Postgres round-trip, but the
transactional fixture (engine.connect → outer begin → Session join_transaction_
mode="create_savepoint" → outer.rollback() at teardown) guarantees ZERO
persistent state — no row written by this test outlives it. That satisfies all
three :7999 criteria (no persistent-state mutation, <2 min, no server monopoly),
so it is correctly NOT a :8000 scheduled suite despite living under integration/.
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
from lupin_mcp.persona_normalization import canonical_persona_key


# Display forms under test — one ACCENTED, one PUNCTUATED (the 2026-06-18 shape).
OWNER_ACCENTED_DISPLAY   = "María"        # canonicalizes to "maria"
OWNER_PUNCTUATED_DISPLAY = "Mr. Radio"    # canonicalizes to "mr radio"


@pytest.fixture
def txn_session( monkeypatch ):
    """
    A real Postgres Session joined to an OUTER transaction that is rolled back at
    teardown — every router get_db() block shares it (each handler-level commit
    releases a SAVEPOINT, never a real COMMIT), so the create / patch / query
    seams see each other's writes within the test yet NOTHING persists.

    This is the standard SQLAlchemy "join a session into an external transaction"
    pattern (join_transaction_mode="create_savepoint", SQLAlchemy 2.0): the outer
    rollback discards every savepoint, leaving the dev DB byte-identical.
    """
    connection = db_module.engine.connect()
    outer      = connection.begin()
    session    = Session( bind=connection, join_transaction_mode="create_savepoint" )

    @contextmanager
    def _shared_get_db():
        try:
            yield session
            session.commit()             # → RELEASE SAVEPOINT; writes visible within the outer txn
        except Exception:
            session.rollback()           # → ROLLBACK TO SAVEPOINT only (outer txn survives)
            raise
        # deliberately NOT closed — the next get_db() block reuses this session

    monkeypatch.setattr( tasks, "get_db", _shared_get_db )
    yield session

    session.close()
    outer.rollback()                     # discard every savepoint — zero persistent state
    connection.close()


@pytest.fixture
def client( txn_session ):
    """TestClient over the real tasks router with auth overridden (routing+DB, not auth-DB)."""
    app = FastAPI()
    app.include_router( tasks.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"
    return TestClient( app )


def _owed_count( client, display_owner ):
    """Owed-read seam: count items owned by `display_owner`, queried BY THE DISPLAY FORM."""
    r = client.get(
        "/api/tasks",
        params = { "owner_persona": display_owner, "count_only": "true" },
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()[ "count" ]


def test_reassign_owner_canonicalization_parity_across_three_seams( client ):
    """
    Create under an ACCENTED owner, reassign to a PUNCTUATED owner, and prove
    write + patch + owed-read all agree on ONE canonical key — old owner's owed
    count DROPS, new owner's RISES, when queried by the raw display forms.
    """
    # Baselines queried BY DISPLAY FORM (may be >0 — both are real personas).
    maria_pre    = _owed_count( client, OWNER_ACCENTED_DISPLAY )
    mr_radio_pre = _owed_count( client, OWNER_PUNCTUATED_DISPLAY )

    # ── Seam 1: create-write — owner given as the ACCENTED display form ──────────
    create_body = {
        "item_class"    : "task",
        "title"         : "reassign parity probe (ITEM B)",
        "project"       : "lupin",
        "created_by"    : "clayton f04dfb67",
        "owner_persona" : OWNER_ACCENTED_DISPLAY,
    }
    r = client.post( "/api/tasks", json=create_body )
    assert r.status_code == 201, f"{r.status_code}: {r.text}"
    item    = r.json()
    task_id = item[ "id" ]
    # Stored CANONICAL, not the raw display form (normalize-on-write).
    assert item[ "owner_persona" ] == "maria"
    assert item[ "owner_persona" ] == canonical_persona_key( OWNER_ACCENTED_DISPLAY )
    assert item[ "status" ]        == "queued"

    # owed-read seam sees the new row when queried by the ACCENTED display form:
    # the create-write canonical and the owed-read canonical MATCH (count rose by 1).
    assert _owed_count( client, OWNER_ACCENTED_DISPLAY ) == maria_pre + 1

    # ── Seam 2: patch-write (reassign) — new owner as the PUNCTUATED display form ─
    patch_body = {
        "owner_persona" : OWNER_PUNCTUATED_DISPLAY,
        "actor"         : "clayton f04dfb67",
        "authority"     : "standing",
        "reason"        : "reassigned: balance the Phase-2 queue",
    }
    r = client.patch( f"/api/tasks/{task_id}", json=patch_body )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    resp = r.json()
    # New owner stored CANONICAL (normalize-on-write parity with create).
    assert resp[ "item" ][ "owner_persona" ] == "mr radio"
    assert resp[ "item" ][ "owner_persona" ] == canonical_persona_key( OWNER_PUNCTUATED_DISPLAY )
    # The patched event carries the manager's WHY verbatim (the reassign headline).
    assert resp[ "event" ][ "transition" ] == "patched"
    assert resp[ "event" ][ "reason" ]     == "reassigned: balance the Phase-2 queue"

    # ── Seam 3: owed-read parity — old owner DROPS, new owner RISES ──────────────
    # Queried by the DISPLAY forms: the round-trip resolves both to the canonical
    # keys the rows are actually stored under (the 2026-06-18 false-idle guard).
    assert _owed_count( client, OWNER_ACCENTED_DISPLAY )   == maria_pre        # old owner ↓ back to baseline
    assert _owed_count( client, OWNER_PUNCTUATED_DISPLAY ) == mr_radio_pre + 1  # new owner ↑ by 1
