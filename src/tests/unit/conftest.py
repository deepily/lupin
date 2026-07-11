#!/usr/bin/env python3
"""
Unit-test conftest.

Belt-and-suspenders isolation for the Heartbeat-Hook event emitter.

Why this exists: once `~/.claude/settings.json` has `heartbeat.enabled: true`
(the hook is LIVE), ANY unit test that exercises the Stop hook's `main()`
Branch-C path with the REAL `heartbeat_events` module + a default `base_dir`
would append to the real fleet dir `~/.claude/heartbeat-events/`, polluting it
with synthetic test sessions (e.g. `abc12345`, `fallback1`). That fleet dir is
consumed by the v2 arbiter, so test exhaust must never land there.

This autouse fixture redirects the module-level `FLEET_EVENTS_DIR` to a
per-test tmp dir, so a default-`base_dir` emit writes to tmp instead of
`~/.claude`. Tests that pass `base_dir` explicitly (e.g. the heartbeat_events
unit tests) are unaffected; tests that mock `heartbeat_events` entirely are
unaffected. The result: NO unit test can write the real fleet dir, regardless
of the live settings.json heartbeat state.
"""
import os
import sys

import pytest

# Bootstrap: ensure src/ is importable (mirrors the hook bootstrap)
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )


@pytest.fixture( autouse=True )
def _isolate_heartbeat_events_dir( tmp_path, monkeypatch ):
    """
    Redirect the heartbeat-events FLEET dir to a per-test tmp dir so no unit
    test writes the real ~/.claude/heartbeat-events/, even when the live
    settings.json has heartbeat enabled and a test runs the Stop main() path
    without explicitly isolating the emit.
    """
    from lupin_cli.claude_code.hooks.lib import heartbeat_events
    monkeypatch.setattr(
        heartbeat_events, "FLEET_EVENTS_DIR", tmp_path / "heartbeat-events"
    )


@pytest.fixture( autouse=True )
def _isolate_hook_log_dir( tmp_path, monkeypatch ):
    """
    Redirect the hook-event log dir (hook_common._logs_dir) to a per-test tmp dir
    via LUPIN_HOOK_LOG_DIR — the Lever-P SET site (item 6fc8d78d, 2026-07-07).

    Why (the sibling of the FLEET-dir isolation above): once the Stop hook is LIVE,
    ANY unit test driving log_to_stream / log_payload (the Branch-C _run_heartbeat
    path, the oracle `heartbeat_oracle` line, etc.) appended to the REAL production
    io/claude_code_hooks/logs/hook-events.jsonl. test_heartbeat_integration —
    which monkeypatches the persona to "Mr. Radio 🦉" and drives synthetic session
    ids sidC2/sidC3/sidC6b — thereby wrote 1,259+ synthetic `sidC*` rows into the
    prod log, manufacturing a false "Mr-Radio-only" arbiter false-poke signature
    that María's overnight watch counted as 336 spurious pokes.

    hook_common._logs_dir resolves the dir at CALL time and honors this env var, so
    the redirect holds regardless of import order. Tests that need the production
    default (env UNSET) monkeypatch.delenv it locally.
    """
    monkeypatch.setenv( "LUPIN_HOOK_LOG_DIR", str( tmp_path / "hook-logs" ) )


# ---------------------------------------------------------------------------
# Additive per-test isolation for the ProxyDecisionEmbeddings Postgres tests
# (bug cfcbb703 Family B — 2026-07-11, Rio).
#
# Why: `vector store backend = postgres` routes ProxyDecisionEmbeddings to the
# shared dev `prediction_decisions` table (the `db_path=tmpdir` these tests pass
# is inert under Postgres). That broke isolation two ways — (1) the tests bled
# rows into the shared dev DB on every run (duplicate-key floods), and (2) the
# tests assume an EMPTY / only-my-rows table (test_empty_table asserts
# find_similar == []; the round-trip asserts results[0] is its own row), which
# transaction-rollback isolation CANNOT provide because the ~200k committed base
# rows stay visible inside the txn. So we give each test a genuinely empty,
# throwaway `prediction_decisions` inside its own per-test schema and point the
# store's get_db() sessions at it via search_path. Strictly ADDITIVE — never
# touches / locks / wipes public.prediction_decisions; DROP SCHEMA CASCADE tears
# the throwaway down. Design + recipe: src/rnd/2026.07.11-cfcbb703-unit-test-triage.md.
# ---------------------------------------------------------------------------
_PG_ISOLATION_MODULES = { "test_data_origin", "test_proxy_decision_embeddings" }


@pytest.fixture( autouse=True )
def _isolate_pg_vector_store( request, monkeypatch ):
    """
    Route ProxyDecisionEmbeddings' Postgres get_db() sessions at an empty per-test
    schema so each test sees ONLY its own rows and nothing lands in public.

    Ensures:
        - only fires for the two target modules (no-op yield for every other unit test)
        - creates schema "test_pdv_<uuid>" with an empty prediction_decisions table
        - the store's `from cosa.rest.db.database import get_db` (imported at call
          time inside each _pg_* method) resolves to a patched get_db whose sessions
          are bound to a fixture-owned connection with search_path = <schema>, public
        - teardown drops the schema (CASCADE) and resets the connection's search_path
          before returning it to the pool (no leakage); public is never mutated
    """
    module = request.module.__name__.rsplit( ".", 1 )[ -1 ]
    if module not in _PG_ISOLATION_MODULES:
        yield
        return

    import uuid
    from contextlib   import contextmanager
    from sqlalchemy   import MetaData
    from sqlalchemy.orm import Session
    from cosa.rest.db import database as _db
    from cosa.rest.db.vector_store_models import PredictionDecision

    schema = "test_pdv_" + uuid.uuid4().hex[ :12 ]
    conn   = _db.engine.connect()
    try:
        conn.exec_driver_sql( f'CREATE SCHEMA "{schema}"' )
        # The `vector` type/opclass live in public (CREATE EXTENSION vector is
        # DB-global), so public MUST stay on the path for vector(768) to resolve;
        # the ROWS land in the test schema.
        conn.exec_driver_sql( f'SET search_path TO "{schema}", public' )
        # Copy ONLY prediction_decisions into the test schema. Indexes are dropped
        # from the copy — a handful of test rows seq-scan fine, and this sidesteps
        # any empty-table HNSW/opclass quirk.
        test_md  = MetaData()
        test_tbl = PredictionDecision.__table__.to_metadata( test_md, schema=schema )
        test_tbl.indexes.clear()
        test_tbl.create( bind=conn )
        conn.commit()   # persist the empty schema + table for the store's sessions

        @contextmanager
        def _isolated_get_db():
            # Bind to the fixture-owned connection so every _pg_* call shares the
            # one search_path'd connection + transaction visibility.
            session = Session( bind=conn )
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        monkeypatch.setattr( _db, "get_db", _isolated_get_db )
        yield
    finally:
        conn.rollback()   # defensive: clear any aborted txn so cleanup always runs
        conn.exec_driver_sql( f'DROP SCHEMA IF EXISTS "{schema}" CASCADE' )
        conn.exec_driver_sql( "RESET search_path" )   # no leakage back to the pool
        conn.commit()
        conn.close()
