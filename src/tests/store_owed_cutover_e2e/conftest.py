"""
Conftest — store-only owed-work cutover REAL-DATA E2E (disagreement proof).

Design: src/rnd/v0.1.8/2026.06.17-store-owed-cutover-e2e-design.md

The seam under test (kept 100% real — NO mocks):
    stop._run_heartbeat  →  _owed_count_from_store  →  query_owed (real urllib)
      →  GET /api/tasks?...&count_only=true  →  routers/tasks.py count branch
        →  TaskRepository.count_tasks  →  SQL COUNT(*) on lupin_db_test

To give the seam's `urllib` a REAL bound socket, this conftest OWNS a server:
a MINIMAL FastAPI app mounting ONLY routers/tasks.py, bound to lupin_db_test,
served by uvicorn in a background thread on an ephemeral port. The full Lupin
app is GPU-heavy at import — deliberately avoided. Auth (require_api_key_or_jwt)
is dependency-overridden to ACCEPT — auth is NOT the seam under test; the
X-API-Key still flows over real HTTP, only its validation is bypassed.

Receipts (the "logged SQL/HTTP params"):
    - HTTP : an app middleware records every inbound (method, path, query).
    - SQL  : a SQLAlchemy before_cursor_execute listener records each COUNT.

SAFETY: binds lupin_db_test ONLY (asserted); seeds + truncates task_items /
task_events ONLY (matches the integration suite's blast radius).
"""

import json
import socket
import threading
import time

import pytest

# The DB engine is module-level — import the module, then swap it to testing
# (lupin_db_test) inside the session fixture BEFORE any request is served.
from cosa.rest.db import database as db_module


def _free_ephemeral_port():
    """Grab an OS-assigned free 127.0.0.1 port (tiny TOCTOU window; fine for a test)."""
    s = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
    s.bind( ( "127.0.0.1", 0 ) )
    port = s.getsockname()[ 1 ]
    s.close()
    return port


@pytest.fixture( scope="session" )
def e2e_server():
    """
    Spin a minimal real tasks-router app bound to lupin_db_test on an ephemeral
    port, served by uvicorn in a background thread.

    Ensures:
        - db_module.engine is bound to lupin_db_test (asserted — SAFETY)
        - task_items / task_events schema present (create_all, idempotent)
        - yields { base_url, http_receipts, sql_receipts } — the two receipt
          lists are LIVE (appended to as requests/SQL flow); a test snapshots
          their length before driving the seam, then slices the new entries
        - server is shut down at session teardown
    """
    import uvicorn
    from fastapi import FastAPI
    from sqlalchemy import event

    from cosa.rest.postgres_models import Base
    from cosa.rest.routers import tasks as tasks_mod
    from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

    # ── 1) bind lupin_db_test (SAFETY-asserted) ────────────────────────────────
    db_module.swap_database( "testing" )
    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: store-owed E2E must bind lupin_db_test, got: {db_url}"

    # ── 2) ensure schema (idempotent — tables already exist on the test DB) ─────
    Base.metadata.create_all( db_module.engine )

    # ── 3) SQL receipts — capture every COUNT statement on the test engine ──────
    sql_receipts = [ ]

    @event.listens_for( db_module.engine, "before_cursor_execute" )
    def _capture_count_sql( conn, cursor, statement, parameters, context, executemany ):
        if "count(" in statement.lower():
            sql_receipts.append( {
                "statement"  : " ".join( statement.split() ),   # collapse whitespace
                "parameters" : _jsonable( parameters ),
            } )

    # ── 4) minimal app: HTTP receipts middleware + tasks router + auth override ──
    http_receipts = [ ]
    app = FastAPI( title="store-owed-cutover-e2e" )

    @app.middleware( "http" )
    async def _record_http( request, call_next ):
        http_receipts.append( {
            "method" : request.method,
            "path"   : request.url.path,
            "query"  : dict( request.query_params ),
        } )
        return await call_next( request )

    app.include_router( tasks_mod.router )
    # auth is NOT the seam under test — accept any caller (X-API-Key still flows
    # over real HTTP; only its validation is bypassed).
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "e2e-test-user"

    # ── 5) serve via uvicorn in a background thread on an ephemeral port ────────
    port   = _free_ephemeral_port()
    config = uvicorn.Config( app, host="127.0.0.1", port=port, log_level="warning" )
    server = uvicorn.Server( config )
    thread = threading.Thread( target=server.run, daemon=True, name="e2e-uvicorn" )
    thread.start()

    deadline = time.time() + 10.0
    while not server.started and time.time() < deadline:
        time.sleep( 0.05 )
    assert server.started, "uvicorn background server failed to start within 10s"

    base_url = f"http://127.0.0.1:{port}"
    try:
        yield { "base_url": base_url, "http_receipts": http_receipts, "sql_receipts": sql_receipts }
    finally:
        server.should_exit = True
        thread.join( timeout=5.0 )


@pytest.fixture
def clean_tasks():
    """TRUNCATE task_events + task_items on lupin_db_test before each test (SAFETY-asserted)."""
    from sqlalchemy import text
    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, f"SAFETY: clean_tasks only on lupin_db_test, got {db_url}"
    with db_module.engine.begin() as conn:
        conn.execute( text( "TRUNCATE TABLE task_events, task_items CASCADE" ) )
    yield


def seed_store_rows( owner_persona, project, n_queued=0, n_in_progress=0, next_chase_ts=None ):
    """
    Seed real owed rows into lupin_db_test via a direct ORM INSERT (real commit).

    Both 'queued' and 'in_progress' are members of STORE_OWED_STATUSES, so the
    owed total this persona+project owes is (n_queued + n_in_progress). Seeding a
    MIX exercises query_owed's sum-across-statuses path with both non-zero.

    `next_chase_ts` seeds a chase onto NON-blocked rows — the shape the WRITE
    path cannot currently produce (task_repository.create_with_event:149-154
    nulls it for any non-blocked mint; row 9bb4debe). Seeding via direct ORM
    INSERT bypasses that normalizer ON PURPOSE: the fence being tested is what
    the OWED ORACLE does with such a row, which is a separate question from
    whether the write path will let you make one. No DB CHECK forbids it — the
    constraints only require a chase on blocked/parked, never forbid one
    elsewhere.

    Requires:
        - owner_persona / project are non-empty strings
        - n_queued, n_in_progress are non-negative ints
        - next_chase_ts is a datetime or None

    Ensures:
        - inserts exactly n_queued queued + n_in_progress in_progress task rows
        - every seeded row carries next_chase_ts verbatim (None unless given)
        - returns the total count seeded
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    rows = (
        [ ( "queued", i )      for i in range( n_queued ) ] +
        [ ( "in_progress", i ) for i in range( n_in_progress ) ]
    )
    with get_db() as session:
        for status, i in rows:
            session.add( TaskItem(
                item_class    = "task",
                title         = f"owed-{project}-{owner_persona}-{status}-{i}",
                project       = project,
                created_by    = f"{owner_persona}@e2e-session",
                owner_persona = owner_persona,
                status        = status,
                next_chase_ts = next_chase_ts,
            ) )
    return n_queued + n_in_progress


def write_transcript( path, n_owed=0, n_completed=0 ):
    """
    Write a REAL Claude Code transcript JSONL the production transcript_reader
    parses (assistant lines with tool_use blocks).

    Replay model (heartbeat_task_state): the Nth TaskCreate => taskId str(N),
    initial status 'pending' (OWED). A TaskUpdate{taskId,status='completed'}
    clears it. So:
        - n_owed     TaskCreate blocks left at pending  => n_owed owed tasks
        - n_completed TaskCreate + a matching TaskUpdate->completed => not owed

    Requires:
        - path is a writable file path
        - n_owed, n_completed are non-negative ints

    Ensures:
        - writes a JSONL transcript whose replay yields exactly n_owed owed tasks
        - returns n_owed (the transcript-owed count)
    """
    creates    = [ ]
    updates    = [ ]
    ordinal    = 0
    for i in range( n_owed ):
        ordinal += 1
        creates.append( { "type": "tool_use", "name": "TaskCreate",
                          "input": { "subject": f"owed-transcript-{i}" }, "id": f"tc{ordinal}" } )
    for i in range( n_completed ):
        ordinal += 1
        creates.append( { "type": "tool_use", "name": "TaskCreate",
                          "input": { "subject": f"done-transcript-{i}" }, "id": f"tc{ordinal}" } )
        updates.append( { "type": "tool_use", "name": "TaskUpdate",
                          "input": { "taskId": str( ordinal ), "status": "completed" }, "id": f"tu{ordinal}" } )

    lines = [ ]
    if creates:
        lines.append( { "type": "assistant", "message": { "role": "assistant", "content": creates } } )
    if updates:
        lines.append( { "type": "assistant", "message": { "role": "assistant", "content": updates } } )

    with open( path, "w" ) as f:
        for obj in lines:
            f.write( json.dumps( obj ) + "\n" )
    return n_owed


def _jsonable( value ):
    """Best-effort coerce SQL bind params to something json/printable; never raises."""
    try:
        json.dumps( value )
        return value
    except ( TypeError, ValueError ):
        return str( value )
