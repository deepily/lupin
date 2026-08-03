#!/usr/bin/env python3
"""
Minimal REAL-router server for the late-answer handback e2e (own-server venue).

WHY THIS EXISTS (venue finding, TODO.md 2026-08-02): the reported defect is
process-lifetime state — an answered ask is written to Postgres, then handed back
only by waking an IN-MEMORY dict (`pending_responses` in the notifications router).
A server restart wipes that dict; the durable row survives; the answer must then
travel by catch-up. Proving that needs a REAL server process we can kill+restart.
It CANNOT be a :8000-scheduled test (the test-suite runner Popens pytest as a child
of the :8000 process, so restarting :8000 kills its own runner — deadlock), and it
must NOT bounce the live :7999 (that writes to lupin_db_dev — the "no test touches a
live dev data store" rule — and disrupts the fleet). So the test stands up THIS
server on a throwaway migrated DB and bounces it via a genuine kill+restart.

WHAT IT IS: the PRODUCTION notifications + websocket routers, mounted on a bare
FastAPI app, with the two `lupin_app.main` globals those routers read wired up
(`config_mgr`, `jobs_notification_queue`). The route handlers, the in-memory
`pending_responses` waiter dict, the WS-connection registry, the repo queries, and
the Postgres persistence are all the real production code. What is deliberately
OMITTED is everything unrelated to the handback seam and everything that would grab
a GPU or touch the fleet: no lifespan startup, so no model loads, no commons /
arbiter / heartbeat daemons, no queue consumer, no MCP. (GPU load and those daemons
live in main.py's async lifespan, which is never run here — only module-level import
side effects fire, and those are cheap: ~5s, no GPU.)

ENV (set by the test BEFORE launch — read at import time, so they must precede it):
  LUPIN_ROOT, LUPIN_CONFIG_MGR_CLI_ARGS, AUTH_MODE=jwt, JWT_SECRET_KEY,
  DB_NAME / DB_HOST / DB_PORT / DB_USER / DB_PASSWORD  (→ throwaway DB),
  LUPIN_HOOK_SESSIONS_DIR  (→ temp bridge dir for sender_persona stamping),
  PORT.

A kill+restart of THIS process wipes `pending_responses` + the WS registry while
the throwaway Postgres DB survives — the exact process-lifetime seam under test.
"""

import os
import sys

_lupin_root = os.environ.get( "LUPIN_ROOT" )
if _lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
_src_path = os.path.join( _lupin_root, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

import uvicorn
from fastapi import FastAPI

# Module-level import of main is cheap + GPU-free (no lifespan). It gives us the
# real, already-constructed WebSocketManager (main.websocket_manager) plus the
# module globals the routers read; config_mgr + the notification queue are set in
# main's startup (never run here), so we wire them ourselves below.
import lupin_app.main as m
from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest.notification_fifo_queue import NotificationFifoQueue
from cosa.rest.routers import notifications, websocket


def build_app():
    """Wire the two main-module globals the routers read, then mount them."""
    m.config_mgr  = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )
    m.app_debug   = False
    m.app_verbose = False

    # The WS manager was constructed at import (real). The heartbeat gate reads
    # websocket_manager.config_mgr; give it ours if it has none (we never start the
    # heartbeat loop, but is_user_connected / connect must work).
    if getattr( m.websocket_manager, "config_mgr", None ) is None:
        m.websocket_manager.config_mgr = m.config_mgr

    # get_notification_queue() returns main.jobs_notification_queue — the online
    # response-required ask path calls .push_notification on it.
    m.jobs_notification_queue = NotificationFifoQueue(
        websocket_mgr    = m.websocket_manager,
        emit_enabled     = True,
        debug            = False,
        verbose          = False,
        fcm_wake_service = None
    )

    app = FastAPI( title="handback-e2e-own-server" )
    app.include_router( notifications.router )   # prefix="/api"
    app.include_router( websocket.router )        # /ws/queue/{session_id}
    return app


app = build_app()


if __name__ == "__main__":
    port = int( os.environ.get( "PORT", "8137" ) )
    # Single process, no reload → a clean kill+restart wipes pending_responses.
    uvicorn.run( app, host="127.0.0.1", port=port, log_level="warning" )
