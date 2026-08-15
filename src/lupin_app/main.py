#!/usr/bin/env python3
from logging import debug

from fastapi import FastAPI, Request, Query, HTTPException, File, UploadFile, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from datetime import datetime
import os
import sys
import base64
import json
import time
from typing import Optional
import asyncio
from contextlib import asynccontextmanager
from urllib.parse import quote
import uuid
import aiohttp
import websockets

# Bootstrap using LUPIN_ROOT environment variable
lupin_root = os.environ.get( 'LUPIN_ROOT' )
if lupin_root is None:
    raise RuntimeError(
        "LUPIN_ROOT environment variable not set.\n"
        "Set it before starting FastAPI server:\n"
        "  export LUPIN_ROOT=/mnt/DATA01/include/www.deepily.ai/projects/lupin\n"
        "  python src/lupin_app/main.py"
    )

# Load LoRA model paths from ~/.lora_env (auto-updated by peft_trainer.py)
_lora_env_path = os.path.expanduser( "~/.lora_env" )
if os.path.exists( _lora_env_path ):
    with open( _lora_env_path, "r" ) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line.startswith( "export " ) and "=" in _line:
                _var_def = _line[ len( "export " ): ]
                _key, _val = _var_def.split( "=", 1 )
                os.environ[ _key ] = _val.strip( '"' )

src_path = os.path.join( lupin_root, 'src' )
if src_path not in sys.path:
    sys.path.insert( 0, src_path )

# Promote the weak "LUPIN_ROOT is set" guard above to a strong "LUPIN_ROOT is
# valid" check — fails loud and immediate on the /app-vs-/var/lupin path drift
# instead of cryptically later at config load. (No defensive fallback.)
from lupin_app.bootstrap_helpers import assert_lupin_root_valid, reload_enabled as _reload_enabled
from cosa.rest.error_envelope import make_unhandled_exception_handler
assert_lupin_root_valid( lupin_root )

# Reduce CUDA memory fragmentation (prevents periodic OOM on Whisper inference)
os.environ.setdefault( "PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True" )

import torch
from transformers import pipeline

from cosa.config.configuration_manager import ConfigurationManager
from cosa.memory.input_and_output_table import InputAndOutputTable
from cosa.memory.solution_manager_factory import SolutionSnapshotManagerFactory
from cosa.rest.todo_fifo_queue import TodoFifoQueue
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.running_fifo_queue import RunningFifoQueue
import cosa.utils.util as du
from cosa.agents.two_word_id_generator import TwoWordIdGenerator
from cosa.rest.websocket_manager import WebSocketManager
from cosa.rest.notification_fifo_queue import NotificationFifoQueue

# Import routers
from cosa.rest.routers import system, notifications, speech, queues, jobs, websocket, websocket_admin, auth, admin, claude_code_queue, embeddings, mode, stats, deep_research, mock_job, io_files, docs_files, podcast_generator, presentation_generator, deep_research_to_podcast, deep_research_to_presentation, swe_team, bug_fix_expediter, decision_proxy, test_suite, pages, peer, speakerphone, voice_persona, multiplexer_config, commons, arbiter, tasks, fcm, dm, v2_ask
from cosa.rest.queue_consumer import start_todo_producer_run_consumer_thread
from cosa.rest.job_persistence import mark_interrupted_jobs, record_server_available

# Suppress noisy LanceDB warnings
import logging
logging.getLogger( "lance" ).setLevel( logging.ERROR )

def _log_vram( label ):
    """Log CUDA VRAM snapshot after model load."""
    if torch.cuda.is_available():
        alloc    = torch.cuda.memory_allocated() / 1024**3
        reserved = torch.cuda.memory_reserved() / 1024**3
        print( f"  [VRAM] {label}: Allocated {alloc:.2f} GiB, Reserved {reserved:.2f} GiB" )


# Global variables
config_mgr = None
app_debug = False
app_verbose = False
app_silent = True
whisper_pipeline = None
jobs_todo_queue = None
jobs_done_queue = None
jobs_dead_queue = None
jobs_run_queue = None
jobs_notification_queue = None
snapshot_mgr = None
io_tbl = None
id_generator = None
fcm_wake_service = None  # S6 silent-relay wake sender (disabled until Firebase credentials exist)

# Inter-Session Commons (Phase 2 — user-broadcast surface; Phase 3 — push-mode + LLM)
commons_store            = None
commons_rate_limiter     = None
commons_ack_watcher      = None
commons_activity_watcher = None

# WebSocket connection management
websocket_manager = WebSocketManager()
# Background task tracking for cleanup
active_tasks = {}
# Clock update background task
clock_task = None
# Consumer thread for producer-consumer pattern
consumer_thread = None
# WebSocket maintenance background tasks
websocket_heartbeat_task = None
websocket_cleanup_task = None

# ============================================================================
# DEPRECATED: Legacy emit_speech infrastructure (Session 97)
# Queue classes now use notification service directly via _notify() method
# Keeping commented for reference during migration verification
# TODO: Remove after migration verified stable (target: Session 100+)
# ============================================================================
# async def emit_speech( msg: str, user_id: str = "ricardo_felipe_ruiz_6bdc", websocket_id: str = None ) -> None:
#     """
#     [DEPRECATED] Generate TTS speech and emit via WebSocket to specific user or broadcast.
#
#     Replaced by: Notification service with _notify() method in queue classes
#     Reason: Migration to notification service for job_id routing, blocking queries, and suppress_ding
#
#     Requires:
#         - websocket_manager must be initialized and running
#         - msg must be a non-empty string
#         - user_id or websocket_id must be valid if provided
#
#     Ensures:
#         - TTS job request is emitted via WebSocket to target recipient
#         - No exceptions are propagated to caller (errors are logged)
#         - Speech data includes text and timestamp
#
#     Args:
#         msg: The text message to be converted to speech
#         user_id: User ID for user-specific routing (preferred method)
#         websocket_id: Optional websocket identifier for backwards compatibility
#
#     Returns:
#         None
#
#     Raises:
#         No exceptions raised - all errors are caught and logged
#     """
#     print( f"[SPEECH] emit_speech called:" )
#     print( f"  - Message: '{msg}'" )
#     print( f"  - User ID: {user_id if user_id else 'none'}" )
#     print( f"  - WebSocket ID: {websocket_id if websocket_id else 'none'}" )
#
#     try:
#         # Emit speech_update event to trigger TTS in browser
#         speech_data = {
#             "text": msg,
#             "timestamp": datetime.now().isoformat()
#         }
#
#         if user_id and user_id != "ricardo_felipe_ruiz_6bdc":
#             # Emit to specific user (preferred method)
#             await websocket_manager.emit_to_user( user_id, "tts_job_request", speech_data )
#             print( f"[SPEECH] Emitted tts_job_request to user {user_id}" )
#         elif user_id == "ricardo_felipe_ruiz_6bdc":
#             # Default user - still use user-based routing
#             await websocket_manager.emit_to_user( user_id, "tts_job_request", speech_data )
#             print( f"[SPEECH] Emitted tts_job_request to default user {user_id}" )
#         elif websocket_id:
#             # Backwards compatibility: Emit to specific session
#             await websocket_manager.emit_to_session( websocket_id, "tts_job_request", speech_data )
#             print( f"[SPEECH] Emitted tts_job_request to session {websocket_id} (backwards compatibility)" )
#         else:
#             # Fallback: Broadcast to all connected clients
#             await websocket_manager.async_emit( "tts_job_request", speech_data )
#             print( f"[SPEECH] Broadcasted tts_job_request to all connections (fallback)" )
#
#     except Exception as e:
#         print( f"[SPEECH] Error emitting speech: {e}" )
#         # Don't raise - this shouldn't break the calling flow
#
#
# def create_emit_speech_callback():
#     """
#     [DEPRECATED] Creates a sync wrapper for the async emit_speech function with user-based routing.
#
#     Replaced by: Notification service - queue classes use _notify() directly
#
#     Requires:
#         - No preconditions
#
#     Ensures:
#         - Returns a callable synchronous wrapper function
#         - Wrapper function runs emit_speech in isolated thread with own event loop
#         - Thread execution is non-blocking and daemon-enabled
#
#     Args:
#         None
#
#     Returns:
#         function: Synchronous wrapper function that accepts (msg, user_id, websocket_id) parameters
#
#     Raises:
#         No exceptions raised - wrapper function handles all errors internally
#     """
#     def sync_emit_speech( msg: str, user_id: str = "ricardo_felipe_ruiz_6bdc", websocket_id: str = None ):
#         import threading
#
#         def run_in_thread():
#             try:
#                 # Run async function in isolated thread with its own event loop
#                 asyncio.run( emit_speech( msg, user_id=user_id, websocket_id=websocket_id ) )
#             except Exception as e:
#                 print( f"[SPEECH] Error in speech thread: {e}" )
#
#         # Always run in separate thread to avoid event loop conflicts
#         thread = threading.Thread( target=run_in_thread, daemon=True )
#         thread.start()
#         print( f"[SPEECH] Started speech emission thread for: '{msg}' (user: {user_id})" )
#     return sync_emit_speech


async def clock_loop():
    """
    Background task that emits clock updates every minute to all connected WebSocket clients.
    
    Requires:
        - websocket_manager must be initialized and running
        - du.get_current_time() function must be available
        - app_debug and app_verbose global variables must be initialized
        
    Ensures:
        - Emits 'sys_time_update' event every 60 seconds to all connections
        - Continues until cancelled or exception occurs
        - Provides detailed debug logging when verbose mode enabled
        
    Args:
        None
        
    Returns:
        None - runs until cancelled
        
    Raises:
        asyncio.CancelledError: When task is cancelled during shutdown
        Exception: For any other errors during clock updates
    """
    lupin_env = os.environ.get( "LUPIN_ENV", "" ).lower()
    if lupin_env in [ "test", "testing" ]:
        env_label = "TEST"
    else:
        env_label = "DEVELOPMENT"

    print( "[CLOCK] Starting clock update loop..." )
    while True:
        try:
            # Emit time update to all connected WebSocket clients
            current_time = du.get_current_time( format="%Y-%m-%d @ %H:%M" )
            await websocket_manager.async_emit( 'sys_time_update', { 'date': current_time, 'env_label': env_label } )
            
            # Debug logging (only if verbose mode)
            if app_debug and app_verbose:
                connection_count = websocket_manager.get_connection_count()
                print( f"[CLOCK] Emitted time update to {connection_count} connections: {current_time}" )
                
                # Show detailed connection info
                all_sessions = list( websocket_manager.active_connections.keys() )
                if all_sessions:
                    print( f"[CLOCK] Active session IDs: {', '.join( all_sessions )}" )
                    
                    # Show user associations if any
                    user_info = []
                    for session_id in all_sessions:
                        user_id = websocket_manager.session_to_user.get( session_id, "no-auth" )
                        user_info.append( f"{session_id}→{user_id}" )
                    print( f"[CLOCK] Session→User mapping: {', '.join( user_info )}" )
            
            # Heartbeat: stamp server-available for downtime-aware scheduled-job
            # catch-up. Run off-thread so the sync DB write never blocks the loop.
            try:
                await asyncio.to_thread( record_server_available )
            except Exception as e:
                if app_debug: print( f"[CLOCK] server-available heartbeat failed: {e}" )

            # Wait 1 minute before next update
            sleep_time = 60
            await asyncio.sleep( sleep_time )

        except asyncio.CancelledError:
            print( "[CLOCK] Clock loop cancelled" )
            break
        except Exception as e:
            print( f"[CLOCK] Error in clock loop: {e}" )
            # Wait before retrying to avoid rapid error loops
            await asyncio.sleep( 60 )


async def websocket_heartbeat_loop():
    """
    Background task for WebSocket heartbeat checks.
    
    Requires:
        - websocket_manager must be initialized with config_mgr
        - websocket_manager.heartbeat_check() method must be available
        - app_debug and app_verbose global variables must be initialized
        
    Ensures:
        - Performs heartbeat checks at configured intervals (default 30s)
        - Removes dead connections automatically
        - Continues until cancelled or exception occurs
        
    Args:
        None
        
    Returns:
        None - runs until cancelled
        
    Raises:
        asyncio.CancelledError: When task is cancelled during shutdown
        Exception: For any other errors during heartbeat operations
    """
    # Get interval from config
    interval = websocket_manager.config_mgr.get(
        "websocket heartbeat interval seconds", default=30, return_type="int"
    )
    
    print( f"[WS-HEARTBEAT] Starting heartbeat loop with {interval}s interval" )
    
    while True:
        try:
            # Run heartbeat check
            dead_count = await websocket_manager.heartbeat_check()
            
            if app_debug and app_verbose and dead_count > 0:
                print( f"[WS-HEARTBEAT] Heartbeat removed {dead_count} dead connection(s)" )
            
            # Wait for next interval
            await asyncio.sleep( interval )
            
        except asyncio.CancelledError:
            print( "[WS-HEARTBEAT] Heartbeat loop cancelled" )
            break
        except Exception as e:
            print( f"[WS-HEARTBEAT] Error in heartbeat loop: {e}" )
            # Wait before retrying to avoid rapid error loops
            await asyncio.sleep( interval )


async def websocket_cleanup_loop():
    """
    Background task for automatic session cleanup.
    
    Requires:
        - websocket_manager must be initialized with config_mgr
        - websocket_manager.auto_cleanup() method must be available
        - app_debug and app_verbose global variables must be initialized
        
    Ensures:
        - Performs cleanup at configured intervals (default 1 hour)
        - Removes stale sessions exceeding maximum age
        - Continues until cancelled or exception occurs
        
    Args:
        None
        
    Returns:
        None - runs until cancelled
        
    Raises:
        asyncio.CancelledError: When task is cancelled during shutdown
        Exception: For any other errors during cleanup operations
    """
    # Get interval from config
    interval_hours = websocket_manager.config_mgr.get(
        "websocket cleanup interval hours", default=1, return_type="int"
    )
    interval_seconds = interval_hours * 3600
    
    print( f"[WS-CLEANUP] Starting cleanup loop with {interval_hours} hour interval" )
    
    while True:
        try:
            # Run cleanup
            cleaned = await websocket_manager.auto_cleanup()
            
            if app_debug and app_verbose and cleaned > 0:
                print( f"[WS-CLEANUP] Cleaned {cleaned} stale session(s)" )
            
            # Wait for next interval
            await asyncio.sleep( interval_seconds )
            
        except asyncio.CancelledError:
            print( "[WS-CLEANUP] Cleanup loop cancelled" )
            break
        except Exception as e:
            print( f"[WS-CLEANUP] Error in cleanup loop: {e}" )
            # Wait before retrying to avoid rapid error loops
            await asyncio.sleep( interval_seconds )


# ─── Managed-bounce broadcasts (R4 warning + R5 all-clear) ──────────────────
# Design of record: src/rnd/v0.1.9/2026.08.01-managed-bounce-review-tiffany.md +
# 2026.08.01-managed-bounce-for-7999.md Rev 2. Pure/injectable logic lives in
# cosa.rest.managed_bounce_broadcast; these thin wrappers bind it to the live
# commons singletons (module globals set during startup).

def _managed_bounce_server_label():
    """
    Which server THIS process is, as it should appear in a fleet broadcast.

    The dev and test containers run this same file and differ only by config
    block (`Lupin: Development` vs `Lupin: Testing`), so without this the test
    server announces itself as ":7999" — measured 2026-08-01, nine sessions were
    told the DEV server had bounced when the TEST container restarted (bug
    652271f3). Resolved ONCE here and passed to every call site so the warning
    and the all-clear can never disagree about who is speaking.
    """
    from cosa.rest.managed_bounce_broadcast import DEFAULT_SERVER_LABEL

    return config_mgr.get( "managed bounce server label", default=DEFAULT_SERVER_LABEL )


def _emit_managed_bounce( kind, message, broadcast_id=None ):
    """
    Fire a managed-bounce fleet broadcast in-process, never raising.

    Returns the execute_broadcast result dict, or None when commons is disabled /
    not yet wired (the not-wired guard + skip-log live in the measured module's
    emit_bounce_broadcast_in_process, so the branch is tested, not just written).
    """
    from cosa.rest.routers.commons import execute_broadcast, BroadcastRequestBody, build_sender_id_for_cc, _load_bridge_fields
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions
    from cosa.rest.managed_bounce_broadcast import emit_bounce_broadcast_in_process, FLEET_BROADCAST_USER_ID

    threshold = config_mgr.get( "commons broadcast liveness threshold seconds", default=28800, return_type="int" )
    return emit_bounce_broadcast_in_process(
        kind                             = kind,
        message                          = message,
        user_id                          = FLEET_BROADCAST_USER_ID,
        store                            = commons_store,
        rate_limiter                     = commons_rate_limiter,
        ack_watcher                      = commons_ack_watcher,
        notification_queue               = jobs_notification_queue,
        active_session_threshold_seconds = float( threshold ),
        raw_sessions_fn                  = find_active_voice_persona_sessions,
        bridge_loader                    = _load_bridge_fields,
        build_sender_id                  = build_sender_id_for_cc,
        execute_broadcast_fn             = execute_broadcast,
        broadcast_request_cls            = BroadcastRequestBody,
        broadcast_id                     = broadcast_id,
    )


def _managed_bounce_all_clear_blocking( boot_id, boot_started, startup_began ):
    """
    R5 all-clear, run in a worker thread post-yield (option A: bounded settle gate).

    Waits for cc-listener/browser sockets to reconnect after the restart, then
    fires ONE boot-stamped all-clear. Blocking (filesystem + queue writes); the
    async wrapper hands it to a thread so it never touches the event loop.
    """
    from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions
    from cosa.rest.managed_bounce_broadcast import wait_for_roster_coverage, build_bounce_message

    # Fallback tracks the key; both are derived from RECONNECT_MAX_DELAY (pinned by test).
    deadline = config_mgr.get( "managed bounce all-clear settle deadline seconds",      default=15,  return_type="float" )
    interval = config_mgr.get( "managed bounce all-clear settle poll interval seconds", default=0.5, return_type="float" )

    # Hold until live sockets COVER the roster of sessions we expect back. The two
    # inputs are deliberately different sources and neither can do the other's job:
    #   · roster  = bridge files. They SURVIVE a bounce, which is why they answer
    #               "who was here before it" and CANNOT answer "who is back now".
    #   · present = websocket_manager.active_connections, re-instantiated EMPTY on
    #               a bounce and refilled only by a real reconnect.
    # Two earlier predicates failed by being FLOORS instead of completion tests —
    # v1 counted bridge files (always true → fired at 0.0s, 0 acks), v2 waited for
    # a plateau of live sockets and fired at 1 of 4 on a staggered reconnect
    # (bug 784d4a2e, boot #2: curve 0→1→1, fired at 1.0s, zero acks). Coverage is
    # a completion test: a subset never satisfies it, at any fleet size.
    # This is the SOLE delivery path — a straggler past the deadline gets NOTHING.
    gate = wait_for_roster_coverage(
        roster_fn             = lambda: [ sid for ( _path, sid, _persona ) in find_active_voice_persona_sessions() ],
        present_fn            = lambda: list( websocket_manager.active_connections.keys() ),
        deadline_seconds      = deadline,
        poll_interval_seconds = interval,
        now_fn                = time.monotonic,
        sleep_fn              = time.sleep,
    )

    uptime     = time.monotonic() - startup_began
    message    = build_bounce_message( "all-clear", boot_id=boot_id, boot_started=boot_started, uptime_seconds=uptime,
                                       server_label=_managed_bounce_server_label() )
    result     = _emit_managed_bounce( "all-clear", message )
    recipients = ( result or {} ).get( "recipients" )
    curve      = "→".join( str( c ) for c in gate[ "curve" ] )

    # Accepted delivery LOSS (Rick's ruling: no re-fire). NAME who had not rejoined
    # so the loss is legible, not a bare count: roster (bridge files = who we EXPECT
    # back — they survive the bounce) minus live sockets. A missed session gets
    # NOTHING: no push, and NO durable entry either (perform_fanout writes entries
    # only for the fire-time snapshot).
    #
    # COMPUTED FOR BOTH FIRE REASONS, not just deadline expiry (bug 784d4a2e). A
    # PLATEAU fire can miss just as many people: measured 2026-08-01 boot #2, the
    # gate saw curve 0→1→1, called it settled at 1.0s, and fired to 4 recipients of
    # whom ZERO acked — and because naming lived in the deadline branch alone, the
    # log line read "reconnect plateau after 1.0s ... reached 4 recipient(s)" and was
    # indistinguishable from success. An accepted loss that stops being visible is
    # just a loss.
    # Taken from the GATE's own firing observation, not re-read here. A second read
    # after the fanout would see late arrivals and report a SMALLER loss than the
    # one the gate actually decided on — an under-count in the direction that
    # flatters us.
    missed = gate[ "missing" ]
    loss   = (
        f" {len( missed )} session(s) had NOT rejoined and got NO all-clear "
        f"(accepted loss, no re-fire): {missed}."
        if missed
        else (
            f" all {gate[ 'roster_size' ]} session(s) on the roster had a live socket."
            if gate[ "roster_size" ]
            # ⚠️ An EMPTY roster is AMBIGUOUS and the gate cannot resolve it:
            # find_active_sessions returns [] both when nobody is expected back AND
            # when the bridge directory is missing or unreadable. Coverage is then
            # satisfied vacuously and this fires into nobody. Say that plainly rather
            # than reporting the flattering reading as fact (Arnold 🪨, attack #2).
            else (
                " ⚠️ the roster was EMPTY — either nobody was expected back, or the bridge "
                "directory could not be read. This fire reached nobody and the gate cannot "
                "tell those two apart."
            )
        )
    )

    # Fire-time receipt + reconnect curve — the instruments that tell us later
    # whether the guessed window was right and how the fleet came back.
    if gate[ "reason" ] == "deadline":
        print(
            f"[managed-bounce] ⚠️ all-clear FIRED on DEADLINE EXPIRY (boot #{boot_id}): reached "
            f"{recipients} recipient(s) after {gate[ 'elapsed' ]:.1f}s; reconnect curve {curve}."
            f"{loss}",
            file=sys.stderr,
        )
    else:
        print(
            f"[managed-bounce] all-clear FIRED (boot #{boot_id}): roster COVERED after "
            f"{gate[ 'elapsed' ]:.1f}s; reconnect curve {curve}; reached {recipients} recipient(s)."
            f"{loss}",
            file=sys.stderr,
        )


async def _run_managed_bounce_all_clear( *, boot_id, boot_started, startup_began ):
    """Post-yield async wrapper: run the blocking all-clear off the event loop."""
    try:
        await asyncio.to_thread( _managed_bounce_all_clear_blocking, boot_id, boot_started, startup_began )
    except Exception as e:  # pragma: no cover - best-effort boundary guard; must never surface (main.py is outside cov source=["cosa"])
        print( f"[managed-bounce] WARN: all-clear task failed: {e}", file=sys.stderr )


@asynccontextmanager
async def lifespan( app: FastAPI ):
    """
    Manages the application lifecycle for FastAPI.
    
    Preconditions:
        - Environment variable LUPIN_CONFIG_MGR_CLI_ARGS must be set or empty string
        - Configuration files must exist at specified paths
        - CUDA device must be available if using GPU
    
    Postconditions:
        - All global components are initialized (config_mgr, queues, etc.)
        - Whisper STT model is loaded and ready
        - Application is ready to handle requests
    
    Args:
        app: FastAPI application instance
    
    Yields:
        None - Control returns to FastAPI after initialization
    """
    # Startup
    global config_mgr, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, jobs_run_queue, jobs_notification_queue, io_tbl, id_generator, app_debug, app_verbose, app_silent, clock_task, consumer_thread, websocket_heartbeat_task, websocket_cleanup_task, fcm_wake_service
    
    # Monotonic mark for the managed-bounce all-clear uptime stamp (R5).
    _startup_monotonic = time.monotonic()

    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # Get configuration flags (needed for debug output below)
    app_debug   = config_mgr.get( "app debug",   default=False, return_type="boolean" )
    app_verbose = config_mgr.get( "app verbose", default=False, return_type="boolean" )
    app_silent  = config_mgr.get( "app silent",  default=True,  return_type="boolean" )

    # Auto-migrate the database to the latest Alembic head BEFORE anything
    # touches it. Reproducible + hands-off: the human never runs SQL/ALTER by
    # hand (Rick's rule). Idempotent (no-op at head) and FAIL-LOUD — a migration
    # error MUST abort boot, never serve a half-migrated schema. Runs once per
    # process start. URL is resolved by the migrations' env.py via the app's own
    # get_database_url builder, so it connects exactly like the app in every env.
    from cosa.rest.db.auto_migrate import run_migrations_to_head
    print( "Running database auto-migration (alembic upgrade head)..." )
    migrate_result = run_migrations_to_head( debug=app_debug )
    print( "✓ Database schema is at migration head." )

    # ANNOUNCE AN APPLIED MIGRATION (row 0aae1a28 (a), Mr Radio's ruling).
    #
    # On :7999 uvicorn runs with StatReload over a bind-mounted repo, so SAVING a
    # watched host file restarts the server, which runs this migrate. Not
    # committing, not bouncing — saving. That means a schema change can reach the
    # fleet's task store with no gate and, until now, no announcement: both
    # `command.upgrade` and this block were silent whether they moved the
    # database or no-opped. María spent an afternoon asking for a deploy window
    # for a change that had already shipped hours earlier as she typed.
    #
    # ⚠️ The normal objection to a log line — "a log nobody reads is not a guard"
    # — was weighed and withdrawn by Mr Radio for this case specifically: a DEV
    # server log is read; that is what it is for. This is an ANNOUNCEMENT, not a
    # gate, and it is not claimed as one.
    #
    # Deliberately silent on a no-op: a line on every boot is a line nobody sees.
    if migrate_result[ "applied" ]:
        print(
            f"⚠️  MIGRATION APPLIED — the database moved {migrate_result[ 'before' ] or '(unstamped)'}"
            f" -> {migrate_result[ 'after' ]}.\n"
            f"    On :7999 a file-save restarts the server and runs this migrate, so this may be a\n"
            f"    schema deploy nobody decided. If you did not intend it, that is the thing to look at.",
            file=sys.stderr,
        )

    # ORM/database drift alarm — FAIL-OPEN. Detects a mapped_column that reached
    # the tree ahead of its migration: on :7999 uvicorn runs with --reload, so the
    # model edit IS the deploy, and the ORM immediately SELECTs a column the DB
    # lacks. Measured incident 2026-07-19: task_items.park_reason_captured_at, 12
    # live 500s on /api/tasks — the owed-work oracle the Stop-hook and arbiter
    # both read, so the outage was fleet-wide, not local.
    #
    # Placed AFTER auto-migrate deliberately: `upgrade head` cannot fabricate a
    # migration for a column that has none, so the target defect survives it
    # untouched and is fully visible here. Running BEFORE would instead alarm on
    # every legitimately-pending migration — a false alarm on every boot after any
    # new migration lands, which is how a detector gets ignored into uselessness.
    #
    # This call is structurally incapable of raising or blocking: no network, no
    # await, every exception swallowed internally. On drift it writes a CRITICAL
    # alarm to stderr naming model, table, column, and both revisions — stderr is
    # the alarm of record because it has no dependencies — and the server SERVES
    # ANYWAY. Fail-open is load-bearing: refusing boot would take down the box
    # carrying the MCP transport, the task store, and the owed-work oracle,
    # turning a partial outage into a total one. Worst case is a false alarm,
    # which is the correct price.
    #
    # No notify() here, by design: /api/notify requires auth plus a target_user,
    # and pre-yield this very server accepts no connections — the alarm's
    # transport would be the thing that is still booting. Richer routing is a
    # separate seam, deliberately absent rather than half-built.
    # The report is captured so the SECOND channel (a UI notification) can be
    # scheduled later, once the notification queue exists. The alarm of record
    # has already fired synchronously by the time this returns.
    from cosa.rest.db.schema_drift import emit_startup_drift_alarm
    schema_drift_report = emit_startup_drift_alarm( debug=app_debug )

    # Suppress LanceDB cosmetic warnings if configured
    # These warnings are non-functional - queries execute correctly regardless
    # Warnings occur when using .search() for metadata filtering (not vector similarity)
    if config_mgr.get( "suppress lancedb warnings", default=True, return_type="boolean" ):
        import logging
        import warnings

        # Suppress via warnings module (catches Rust layer warnings)
        warnings.filterwarnings( "ignore", message=".*nprobes is not set.*" )
        warnings.filterwarnings( "ignore", message=".*nearest has not been called.*" )

        # Set LanceDB loggers to ERROR level only (suppress WARN, INFO, DEBUG)
        logging.getLogger( "lance" ).setLevel( logging.ERROR )
        logging.getLogger( "lance.dataset" ).setLevel( logging.ERROR )
        logging.getLogger( "lance.dataset.scanner" ).setLevel( logging.ERROR )

        if app_debug:
            print( "✓ LanceDB warning suppression enabled (cosmetic warnings hidden)" )
    else:
        if app_debug:
            print( "⚠ LanceDB warning suppression disabled (all warnings visible)" )

    # Initialize the ID generator singleton
    id_generator = TwoWordIdGenerator()

    # Initialize solution snapshot manager using factory pattern
    manager_type = config_mgr.get( "solution snapshots manager type", default="file_based" )
    
    if manager_type.lower() == "lancedb":
        lancedb_table = config_mgr.get( "solution snapshots lancedb table", default="solution_snapshots" )

        # TWO AUTHORITIES, RECONCILED (decision 2b20a6d6). `solution snapshots manager
        # type` names the MANAGER class; `vector store backend` names the STORAGE the
        # manager routes to. Nothing compared them before, so this block built a LanceDB
        # path unconditionally and the manager silently ignored it under postgres.
        # `vector store backend` is the storage authority — ask it before building a path.
        from cosa.rest.db.repositories.vector_store_backend import is_postgres_backend

        if is_postgres_backend( config_mgr ):
            config = {
                "table_name" : lancedb_table
            }

            if app_debug:
                print( "Using Postgres+pgvector solution snapshot storage (no LanceDB path built)" )

        else:
            lancedb_path = config_mgr.get( "solution snapshots lancedb path", default="/src/conf/long-term-memory/lupin.lancedb" )

            # Convert relative path to absolute
            if lancedb_path.startswith( "/" ):
                lancedb_path = du.get_project_root() + lancedb_path

            config = {
                "db_path"    : lancedb_path,
                "table_name" : lancedb_table
            }

            if app_debug:
                print( f"Using LanceDB solution snapshot manager: {lancedb_path}" )


    else:
        # # Use file-based backend (default)
        # path_to_snapshots_dir_wo_root = config_mgr.get( "path to snapshots dir wo root" )
        # path_to_snapshots = du.get_project_root() + path_to_snapshots_dir_wo_root
        #
        # config = {"path": path_to_snapshots}
        #
        # if app_debug:
        #     print( f"Using file-based solution snapshot manager: {path_to_snapshots}" )
        # throw value error
        raise ValueError( "As of v0.1.0, only lancedb solution snapshot type supported" )
    
    # Create manager using factory pattern for true swappability
    snapshot_mgr = SolutionSnapshotManagerFactory.create_manager(
        manager_type, config, debug=app_debug, verbose=app_verbose
    )
    
    # Initialize the manager (required for both backends)
    snapshot_mgr.initialize()

    # Register a cache invalidator so /api/init reloads snapshots uniformly
    # with the rest of the cache_registry. Mirrors the per-instance .reload()
    # call previously inlined in routers/system.py:/api/init.
    from cosa.config.cache_registry import register_invalidator
    def _invalidate_snapshot_mgr():
        if snapshot_mgr is not None:
            print( "Reloading solution snapshots..." )
            snapshot_mgr.reload()
    register_invalidator( "snapshot_mgr", _invalidate_snapshot_mgr )

    # Initialize queues with websocket manager
    # NOTE (Session 97): emit_speech_callback is deprecated - queues now use notification service via _notify()
    jobs_todo_queue = TodoFifoQueue( websocket_manager, snapshot_mgr, app, config_mgr, emit_speech_callback=None, debug=app_debug, verbose=app_verbose, silent=app_silent )
    jobs_done_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="done", emit_enabled=True )
    jobs_dead_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="dead", emit_enabled=True )
    jobs_run_queue = RunningFifoQueue( app, websocket_manager, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, config_mgr=config_mgr, emit_speech_callback=None )
    
    # Initialize the FCM silent-relay wake sender (S6). Boots DISABLED with one
    # clear log line until Firebase credentials are provisioned (OSQ-7) — never
    # blocks startup. Token lookup opens a short-lived session per wake attempt
    # (debounce caps this at ≤1 per user per window).
    from cosa.rest.fcm_wake_service import FcmWakeService

    def _fcm_tokens_for_user( user_id ):
        from cosa.rest.db.database import get_db
        from cosa.rest.db.repositories.fcm_token_repository import FcmTokenRepository
        with get_db() as session:
            return FcmTokenRepository( session ).get_tokens_for_user( user_id )

    fcm_wake_service = FcmWakeService(
        config_mgr,
        token_lookup    = _fcm_tokens_for_user,
        mobile_liveness = websocket_manager.has_live_mobile_session,
        debug           = app_debug,
        verbose         = app_verbose
    )

    # Initialize notification queue with io_tbl logging
    jobs_notification_queue = NotificationFifoQueue( websocket_mgr=websocket_manager, emit_enabled=True, debug=app_debug, verbose=app_verbose, fcm_wake_service=fcm_wake_service )
    
    # Initialize input/output table
    io_tbl = InputAndOutputTable( debug=app_debug, verbose=app_verbose )

    # Database initialization
    # PostgreSQL database selected via LUPIN_ENV environment variable:
    #   - development: lupin_db_dev (automatic schema creation via Alembic migrations)
    #   - testing: lupin_db_test (automatic schema creation in tests)
    #   - production: Cloud SQL (automatic schema creation via Alembic migrations)
    print( "[AUTH] Using PostgreSQL authentication database" )

    # CJ Flow Persistence: Mark in-flight jobs as interrupted, preserve scheduled jobs
    try:
        counts = mark_interrupted_jobs()
        total_interrupted = counts.get( "running", 0 ) + counts.get( "pending_interrupted", 0 )
        preserved         = counts.get( "pending_preserved", 0 )
        catchup           = counts.get( "pending_catchup", 0 )
        if total_interrupted > 0 or preserved > 0 or catchup > 0:
            print( f"[CJ-PERSIST] Startup recovery: {total_interrupted} interrupted, "
                   f"{preserved} future-scheduled preserved, {catchup} downtime-missed caught up" )
        else:
            print( "[CJ-PERSIST] No interrupted or scheduled jobs found" )
    except Exception as e:
        print( f"[WARN] CJ Flow startup recovery failed: {e}" )

    # ===================================================================
    # Inter-Session Commons — Phase 2 (user-broadcast surface)
    # ===================================================================
    # Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md
    # AC14 (router) + AC7 (CommonsAckWatcher daemon). Gated by `commons enabled`
    # INI key — when False, the subsystem is fully absent and the router
    # endpoints will 503 per `_require_initialized()`.
    global commons_store, commons_rate_limiter, commons_ack_watcher, commons_activity_watcher
    if config_mgr.get( "commons enabled", default=True, return_type="boolean" ):
        try:
            import os
            from cosa.rest.commons_ack_watcher import CommonsAckWatcher
            from cosa.rest.commons_activity_watcher import CommonsActivityWatcher
            from cosa.rest.commons_rate_limiter import CommonsBroadcastRateLimiter
            from cosa.rest.routers.commons import init_commons_state, _load_bridge_fields
            from lupin_cli.claude_code.hooks.lib.session_bridge import find_active_voice_persona_sessions
            from lupin_mcp.commons_llm_disambiguator import CommonsLlmDisambiguator
            from lupin_mcp.commons_persona_matcher import configure_llm_disambiguator
            from lupin_mcp.commons_store import CommonsStore

            commons_root = os.environ.get( "LUPIN_ROOT" ) or os.getcwd()
            commons_store        = CommonsStore( commons_root )
            commons_rate_limiter = CommonsBroadcastRateLimiter(
                window_seconds = config_mgr.get( "commons broadcast rate limit seconds", default=30, return_type="int" )
            )
            commons_ack_watcher  = CommonsAckWatcher(
                store                  = commons_store,
                push_notification_fn   = jobs_notification_queue.push_notification,
                poll_interval_seconds  = config_mgr.get( "commons broadcast ack watch interval seconds", default=1, return_type="int" ),
            )
            init_commons_state(
                store                            = commons_store,
                rate_limiter                     = commons_rate_limiter,
                ack_watcher                      = commons_ack_watcher,
                active_session_threshold_seconds = config_mgr.get( "commons broadcast liveness threshold seconds", default=28800, return_type="int" ),
            )
            commons_ack_watcher.start()

            # Phase 2.5/3.5 — CommonsActivityWatcher for broadcast-card Recent Activity WS push.
            # Per src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md (AC3).
            # Gated by `commons traffic visibility enabled` AND `commons traffic visibility ws push enabled`.
            if (
                config_mgr.get( "commons traffic visibility enabled", default=True, return_type="boolean" )
                and config_mgr.get( "commons traffic visibility ws push enabled", default=True, return_type="boolean" )
            ):
                excluded_raw     = config_mgr.get( "commons traffic visibility exclude topics", default="presence, system-events" )
                excluded_topics  = [ t.strip() for t in excluded_raw.split( "," ) if t.strip() ]

                def _commons_activity_bridge_owner_resolver():
                    """Build a fresh {session_id: owner_user_id|None} map for each tick."""
                    out = { }
                    for path, sid, _persona in find_active_voice_persona_sessions():
                        bridge = _load_bridge_fields( path )
                        if bridge is not None:
                            out[ sid ] = bridge.get( "owner_user_id" )
                    return out

                commons_activity_watcher = CommonsActivityWatcher(
                    store                    = commons_store,
                    push_notification_fn     = jobs_notification_queue.push_notification,
                    excluded_topics          = excluded_topics,
                    bridge_owner_resolver_fn = _commons_activity_bridge_owner_resolver,
                    poll_interval_seconds    = config_mgr.get( "commons broadcast ack watch interval seconds", default=1, return_type="int" ),
                )
                commons_activity_watcher.start()
                print( f"[COMMONS] Phase 2.5/3.5 CommonsActivityWatcher started (excluded={excluded_topics})" )

            # Phase 3 — wire the LLM disambiguator singleton for commons_persona_matcher
            try:
                configure_llm_disambiguator( CommonsLlmDisambiguator( config_mgr ) )
                print( "[COMMONS] Phase 3 LLM disambiguator installed" )
            except Exception as e:
                print( f"[COMMONS] WARN — LLM disambiguator init failed (matcher falls back to Phase 1 stub): {e}" )
            print( f"[COMMONS] Phase 2+3 subsystem started (root={commons_root})" )
        except Exception as e:
            print( f"[COMMONS] WARN — Phase 2+3 init failed: {e}" )
    else:
        print( "[COMMONS] Disabled via `commons enabled = false` — skipping Phase 2+3 init" )

    # ===================================================================
    # GPU Model Loading (smallest → largest to minimize CUDA fragmentation)
    # ===================================================================
    #
    # Phase 3.6 of the model-server carve-out: read the INI provider switch.
    # When `speech to text provider = model-server`, SKIP all 3 eager GPU loads
    # and route embeddings + transcription via HTTP to lupin-model-server:7998.
    # Defaults to `local` (today's behavior) so a compute container without
    # `LUPIN_MODEL_SERVER_URL` injected continues to eager-load identically.
    # See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
    provider_mode = config_mgr.get(
        "speech to text provider", default="local", silent=True
    ).lower().strip()
    remote_mode = ( provider_mode == "model-server" )

    global whisper_pipeline

    if remote_mode:
        print( "[REMOTE-MODE] Skipping eager GPU loads — routing via HTTP to lupin-model-server" )

        # Set process-ownership flags appropriately for remote mode:
        # - Skip `EmbeddingProvider.declare_in_process_engine_owner()` →
        #   HTTP fallback engages on every embedding call (per R1=C, the
        #   `_resolve_http_target()` resolver returns the model-server URL
        #   when `LUPIN_MODEL_SERVER_URL` is set in env).
        # - Explicit `SpeechToTextProvider.declare_remote_only()` so the
        #   speech provider's `_should_use_local()` returns False even if
        #   some earlier path accidentally flipped the owner flag.
        from cosa.memory.speech_to_text_provider import SpeechToTextProvider
        SpeechToTextProvider.declare_remote_only()
        whisper_pipeline = None

        # Readiness probe — wait up to `model server startup probe timeout
        # seconds` (default 60 s) for the model-server's `/health` endpoint
        # to return 200. Best-effort: on timeout, log a warning and continue
        # so the rest of FastAPI (queue, notifications, doc viewer, auth)
        # comes up cleanly. Model endpoints will 503 (via the provider's
        # HTTP-fallback error path) until lupin-model-server becomes reachable.
        model_server_url = os.environ.get(
            "LUPIN_MODEL_SERVER_URL",
            config_mgr.get( "model server url", default="http://lupin-model-server:7998", silent=True )
        )
        probe_timeout = config_mgr.get(
            "model server startup probe timeout seconds",
            default=60, return_type="int", silent=True
        )
        probe_url = f"{model_server_url}/health"
        print( f"[REMOTE-MODE] Probing model-server readiness at {probe_url} (budget={probe_timeout}s)... ", end="" )
        import requests as _requests
        probe_start    = time.time()
        probe_deadline = probe_start + probe_timeout
        probe_ok       = False
        while time.time() < probe_deadline:
            try:
                _r = _requests.get( probe_url, timeout=2 )
                if _r.status_code == 200:
                    probe_ok = True
                    break
            except _requests.RequestException:
                pass
            await asyncio.sleep( 1.0 )
        elapsed = int( time.time() - probe_start )
        if probe_ok:
            print( f"OK ({elapsed}s)" )
        else:
            print( f"TIMEOUT after {elapsed}s — continuing; model endpoints will 503 until reachable" )

    else:
        # Local-mode (today's behavior): eager-load all 3 models on cuda:0,
        # declare in-process ownership so the provider classes route locally.

        # 1. CodeRankEmbed — Load + multi-batch warmup
        from cosa.memory.local_embedding_engine import get_code_engine, get_prose_engine

        print( "Loading CodeRankEmbed embedding engine... ", end="" )
        code_engine = get_code_engine( debug=app_debug, verbose=app_verbose )
        code_engine.encode_code( [ "def hello(): return 'world'" ] )
        code_engine.encode_query( [ "How do I sort a list in Python?" ] )
        code_engine.encode_code( [ "import os\nimport sys\n\ndef main():\n    path = os.getcwd()\n    print( path )\n    return 0" ] )
        print( "Done!" )
        _log_vram( "CodeRankEmbed" )

        # 2. Prose Embedding — Load + multi-batch warmup
        print( "Loading nomic-embed-text-v1.5 embedding engine... ", end="" )
        prose_engine = get_prose_engine( debug=app_debug, verbose=app_verbose )
        prose_engine.encode_query( [ "What is the meaning of life?" ] )
        prose_engine.encode_document( [ "The quick brown fox jumps over the lazy dog. This is a longer document to exercise memory allocation patterns." ] )
        prose_engine.encode_query( [ "Explain quantum computing in simple terms" ] )
        print( "Done!" )
        _log_vram( "Prose Embedding" )

        # Mark this process as the in-process owner of the GPU embedding singletons.
        # After this point, EmbeddingProvider.generate_embedding() in THIS process
        # routes directly to the loaded engines. Every other process (scripts,
        # tests, MCP, CC subagents) keeps the default flag=False and routes via
        # HTTP to /api/embeddings/{generate,batch} — so no second process ever
        # lazy-loads a duplicate GPU model.
        from cosa.memory.embedding_provider import EmbeddingProvider
        EmbeddingProvider.declare_in_process_engine_owner()
        print( "[EmbeddingProvider] Declared in-process engine owner — local routing enabled for this FastAPI process" )

        # 3. Whisper STT — Load + warmup transcription (LAST, largest GPU footprint)
        print( "Loading distill whisper engine... ", end="" )
        try:
            whisper_pipeline = await load_stt_model()
            # Warmup: transcribe audio to establish stable CUDA footprint
            warmup_path = du.get_project_root() + "/src/conf/warmup/whisper-warmup-85s.mp3"
            if os.path.exists( warmup_path ):
                whisper_pipeline( warmup_path, chunk_length_s=30, stride_length_s=5, return_timestamps=False )
                print( "Done! (with warmup)" )
            else:
                print( "Done! (no warmup file)" )
            # Phase 3.3 of the model-server carve-out: tell the SpeechToTextProvider
            # singleton that THIS process owns the in-process Whisper pipeline.
            # Mirrors EmbeddingProvider.declare_in_process_engine_owner() above.
            # See: src/rnd/v0.1.7/2026.05.16-model-server-carveout/01-design.md
            from cosa.memory.speech_to_text_provider import SpeechToTextProvider
            SpeechToTextProvider.declare_in_process_owner()
        except Exception as e:
            whisper_pipeline = None
            print( "FAILED!" )
            print( f"[WARN] Whisper STT model failed to load: {e}" )
            print( "[WARN] STT endpoints will return 503. All other endpoints remain functional." )
        _log_vram( "Whisper" )

    # 4. Prediction Engine — no GPU model, just initialization
    from cosa.agents.prediction_engine import get_prediction_engine
    prediction_engine = get_prediction_engine( config_mgr=config_mgr, debug=app_debug )
    print( f"[PREDICTION] Prediction engine initialized (enabled={prediction_engine.enabled})" )

    # Store event loop reference in WebSocketManager for thread-safe operations
    print( "[WS] Storing event loop reference for thread-safe operations..." )
    loop = asyncio.get_running_loop()
    websocket_manager.set_event_loop( loop )
    
    # Start background clock task
    print( "[CLOCK] Starting background clock task..." )
    clock_task = asyncio.create_task( clock_loop() )
    print( "[CLOCK] Background clock task started" )
    
    # Start WebSocket maintenance tasks
    if websocket_manager.config_mgr.get( "websocket heartbeat enabled", default=True, return_type="boolean" ):
        print( "[WS-HEARTBEAT] Starting heartbeat task..." )
        websocket_heartbeat_task = asyncio.create_task( websocket_heartbeat_loop() )
        print( "[WS-HEARTBEAT] Heartbeat task started" )
    
    if websocket_manager.config_mgr.get( "websocket cleanup enabled", default=True, return_type="boolean" ):
        print( "[WS-CLEANUP] Starting cleanup task..." )
        websocket_cleanup_task = asyncio.create_task( websocket_cleanup_loop() )
        print( "[WS-CLEANUP] Cleanup task started" )
    
    # Start consumer thread for producer-consumer pattern
    print( "[CONSUMER] Starting todo-producer-run-consumer thread..." )
    consumer_thread = start_todo_producer_run_consumer_thread( jobs_todo_queue, jobs_run_queue )
    print( "[CONSUMER] Todo-producer-run-consumer thread started" )

    # Initialize repair tracker + both queue watchdogs (BFE + TFE) via unified facade
    from cosa.rest.watchdogs import init_watchdogs
    from cosa.rest.repair_attempt_tracker import init_tracker
    init_tracker( config_mgr, debug=app_debug )
    init_watchdogs( config_mgr, jobs_todo_queue, debug=app_debug )

    # Initialize API Resource Manager singleton (Phase 1 CJ Flow async multi-lane).
    # No agents call it yet — wiring ensures the infrastructure is alive from boot
    # so Phase 2/3 can migrate callers without a startup-plumbing pass.
    from cosa.utils.api_resource_manager import init_arm
    init_arm()

    # Restore pre-execution jobs that survived the restart (preserved by
    # mark_interrupted_jobs): future-scheduled, downtime-catch-up, AND immediate
    # submits with no scheduled_at (row 2817b0f5 — a queued job must survive a bounce).
    try:
        from cosa.rest.job_persistence import get_restorable_jobs, restore_pending_jobs
        from cosa.rest.agentic_job_factory import create_agentic_job
        from cosa.rest.queue_extensions import user_job_tracker

        restore_pending_jobs(
            get_restorable_jobs(), create_agentic_job, jobs_todo_queue,
            register_scoped_job=user_job_tracker.register_scoped_job, debug=app_debug
        )
    except Exception as e:
        print( f"[WARN] Job restoration failed: {e}" )

    # v2.2 closed-loop (B1 standing cadence): auto-submit ONE standing
    # Heartbeat-Arbiter observer into CJ Flow. Single-instance-guarded (skips if a
    # restored/existing heartbeat_arbiter job is present) + degrade-safe (any
    # failure is swallowed inside; the arbiter is an additive observer, never a
    # dependency of the local poke path). See cosa.rest.arbiter_bootstrap.
    # R0 (2026-06-07): gated by `arbiter in-process bootstrap enabled` (default True).
    # When the standalone :8001 lupin-arbiter-app service owns Loop B, flip the flag
    # False so the in-process arbiter does NOT submit — never two arbiters actuating.
    from cosa.rest.arbiter_bootstrap import submit_arbiter_if_enabled
    submit_arbiter_if_enabled( jobs_todo_queue, jobs_run_queue, config_mgr )

    # Schema-drift SECOND channel. Scheduled here — not at detection time —
    # because the notification queue does not exist yet when the check runs, and
    # not after `yield` because everything after `yield` is SHUTDOWN.
    #
    # create_task() only QUEUES the coroutine; it cannot begin executing until
    # the loop resumes, which happens after this generator yields. So the network
    # work provably lands post-startup while the call itself blocks nothing —
    # awaiting delivery here would dial a server not yet accepting connections.
    #
    # No-ops entirely when there is no drift or no recipient is configured. The
    # recipient key is EMPTY by default (ratified by Rick 2026-07-19): an
    # unconfigured server degrades to log-only rather than misdelivering to a
    # guessed identity. The CRITICAL stderr log remains the alarm of record.
    from cosa.rest.db.schema_drift import schedule_drift_notification
    schedule_drift_notification(
        schema_drift_report,
        config_mgr.get( "schema drift alarm recipient email", default="" ),
        jobs_notification_queue
    )

    print( f"FastAPI startup complete at {datetime.now()}" )

    # ── R5: managed-bounce all-clear ──────────────────────────────────────────
    # Fires on EVERY start (script, hand-typed docker restart, compose up,
    # crash-restart, host reboot) — the just-started server is the one process
    # guaranteed alive when "I am up" must be spoken. Scheduled as a post-yield
    # task (create_task only QUEUES; it runs once the loop is serving) so it
    # NEVER blocks boot, and so the settle gate can wait for reconnecting sockets
    # while the server already accepts connections. Guarded on commons being
    # wired; any failure degrades to a log, never a failed boot.
    if config_mgr.get( "commons enabled", default=True, return_type="boolean" ) and commons_store is not None:
        try:
            from cosa.rest.managed_bounce_broadcast import next_boot_id, boot_counter_path
            # PER-SERVER counter (bug 652271f3): io/ is bind-mounted into both
            # containers, so one shared file interleaved dev and test boots and
            # made the number in a watched all-clear unpredictable.
            _boot_counter_path = boot_counter_path( du.get_project_root(), _managed_bounce_server_label() )
            _boot_id           = next_boot_id( _boot_counter_path )
            asyncio.create_task(
                _run_managed_bounce_all_clear(
                    boot_id       = _boot_id,
                    boot_started  = datetime.now().isoformat( timespec="seconds" ),
                    startup_began = _startup_monotonic,
                )
            )
        except Exception as e:  # pragma: no cover - best-effort boundary guard; never let the all-clear break boot (main.py is outside cov source=["cosa"])
            print( f"[managed-bounce] WARN: could not schedule all-clear: {e}", file=sys.stderr )

    yield

    # Shutdown
    print( f"FastAPI shutdown at {datetime.now()}" )

    # ── R4 backstop: managed-bounce warning on graceful shutdown ──────────────
    # PINNED FIRST in the shutdown block — BEFORE the WebSocket/consumer teardown
    # below — because after those are cancelled this emit is a silent no-op that
    # still LOOKS implemented (Tiffany, 2026-08-01). This is the backstop for
    # un-sanctioned bounce paths (hand-typed `docker restart`); the bounce script
    # sends its OWN ack-confirmed warning on the sanctioned path.
    #
    # Best-effort + will sometimes lose the race: `docker stop` grants ~10s before
    # SIGKILL, and a hard `docker kill`/OOM skips graceful shutdown entirely — so
    # this can fail to send. Accepted, because the NEXT start's all-clear closes
    # the loop regardless of how the last one died.
    #
    # Deliberately NOT a signal.signal(SIGTERM) handler: that would REPLACE
    # uvicorn's own SIGTERM handler and break graceful shutdown + the
    # timeout_graceful_shutdown outage fix (bug 5b654a15). The post-yield block
    # already runs on every graceful SIGTERM, which is exactly the edge we want.
    try:
        from cosa.rest.managed_bounce_broadcast import build_bounce_message
        _emit_managed_bounce( "warning", build_bounce_message( "warning", server_label=_managed_bounce_server_label() ) )
    except Exception as e:  # pragma: no cover - best-effort boundary guard; must never block shutdown (main.py is outside cov source=["cosa"])
        print( f"[managed-bounce] WARN: shutdown warning emit failed: {e}", file=sys.stderr )

    # Clean-shutdown marker: exact last-available stamp (the 60s heartbeat covers hard kills)
    try:
        record_server_available()
        print( "[CJ-PERSIST] Recorded clean-shutdown last-available marker" )
    except Exception as e:
        print( f"[WARN] shutdown last-available marker failed: {e}" )
    
    # Cancel and cleanup background clock task
    if clock_task:
        print( "[CLOCK] Cancelling background clock task..." )
        clock_task.cancel()
        try:
            await clock_task
        except asyncio.CancelledError:
            print( "[CLOCK] Background clock task cancelled successfully" )
        except Exception as e:
            print( f"[CLOCK] Error during clock task shutdown: {e}" )
    
    # Cancel and cleanup WebSocket maintenance tasks
    if websocket_heartbeat_task:
        print( "[WS-HEARTBEAT] Cancelling heartbeat task..." )
        websocket_heartbeat_task.cancel()
        try:
            await websocket_heartbeat_task
        except asyncio.CancelledError:
            print( "[WS-HEARTBEAT] Heartbeat task cancelled successfully" )
        except Exception as e:
            print( f"[WS-HEARTBEAT] Error during heartbeat task shutdown: {e}" )
    
    if websocket_cleanup_task:
        print( "[WS-CLEANUP] Cancelling cleanup task..." )
        websocket_cleanup_task.cancel()
        try:
            await websocket_cleanup_task
        except asyncio.CancelledError:
            print( "[WS-CLEANUP] Cleanup task cancelled successfully" )
        except Exception as e:
            print( f"[WS-CLEANUP] Error during cleanup task shutdown: {e}" )
    
    # Phase 2 (CJ Flow async multi-lane): drain agentic pool BEFORE consumer stops
    # and BEFORE HTTP socket closes. In-flight pool workers need the WebSocket
    # channel alive long enough to emit their final job_state_transition events
    # as they finish (or are dead-lettered on timeout).
    if jobs_run_queue is not None and hasattr( jobs_run_queue, "shutdown_pool" ):
        try:
            print( "[AGENTIC-POOL] Draining agentic pool before consumer stop..." )
            jobs_run_queue.shutdown_pool( wait=True, timeout=30.0 )
        except Exception as e:
            print( f"[AGENTIC-POOL] Error during pool drain (continuing): {e}" )

    # Shutdown consumer thread
    if consumer_thread:
        print( "[CONSUMER] Stopping todo-producer-run-consumer thread..." )
        with jobs_todo_queue.condition:
            jobs_todo_queue.consumer_running = False
            jobs_todo_queue.condition.notify()

        # Wait for consumer thread to finish
        consumer_thread.join( timeout=5.0 )
        if consumer_thread.is_alive():
            print( "[CONSUMER] Warning: Consumer thread did not exit cleanly" )
        else:
            print( "[CONSUMER] Todo-producer-run-consumer thread stopped successfully" )
    
    # Cancel any active peer-queue watchers
    try:
        print( "[PEER-WATCH] Cancelling active peer-queue watchers..." )
        await peer.cancel_all_watchers_on_shutdown()
        print( "[PEER-WATCH] Peer-queue watchers cancelled" )
    except Exception as e:
        print( f"[PEER-WATCH] Error cancelling watchers: {e}" )

    # Stop the commons ack watcher daemon (Phase 2)
    if commons_activity_watcher is not None:
        try:
            print( "[COMMONS] Stopping CommonsActivityWatcher daemon..." )
            commons_activity_watcher.stop( join_timeout=3.0 )
            print( "[COMMONS] CommonsActivityWatcher stopped" )
        except Exception as e:
            print( f"[COMMONS] WARN — CommonsActivityWatcher shutdown failed: {e}" )

    if commons_ack_watcher is not None:
        try:
            print( "[COMMONS] Stopping CommonsAckWatcher daemon..." )
            commons_ack_watcher.stop( join_timeout=3.0 )
            print( "[COMMONS] CommonsAckWatcher stopped" )
        except Exception as e:
            print( f"[COMMONS] Error stopping watcher: {e}" )


    # Add any other cleanup code here if needed

app = FastAPI(
    title="Lupin FastAPI",
    description="A FastAPI migration of the Lupin agent system",
    version="0.6.0",
    lifespan=lifespan
)

# Unhandled-exception envelope (row b101a60b). SERVER_STARTED_AT is stamped HERE,
# at module import, which is exactly what makes it useful: uvicorn's --reload
# re-imports this module, so a caller seeing a start instant a few seconds old
# knows it hit a reload window rather than a bug in its own request. Paired with
# `exception_class`, a 500 now explains itself AT THE CALLER — previously the
# body was the 21-byte string "Internal Server Error" and the class lived only in
# the container log, where nobody diagnosing a failed call was looking.
# Deliberately carries no `str(e)`: unaudited for what it exposes (see the module
# docstring). Raised HTTPExceptions keep FastAPI's own handling, untouched.
SERVER_STARTED_AT = datetime.now().isoformat( timespec="seconds" )
app.add_exception_handler( Exception, make_unhandled_exception_handler( SERVER_STARTED_AT ) )

# Add CORS middleware to allow Flutter web app to access API endpoints
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add security headers middleware (Phase 8)
@app.middleware( "http" )
async def add_security_headers( request: Request, call_next ):
    """
    Add security headers to all HTTP responses (Phase 8).

    Requires:
        - request is FastAPI Request object
        - call_next is the next middleware/endpoint function

    Ensures:
        - Security headers added to response
        - X-Content-Type-Options: nosniff (prevent MIME sniffing)
        - X-Frame-Options: DENY (prevent clickjacking)
        - X-XSS-Protection: 1; mode=block (XSS protection)
        - Strict-Transport-Security: enforce HTTPS

    Returns:
        Response with security headers
    """
    response = await call_next( request )

    response.headers["X-Content-Type-Options"] = "nosniff"
    # X-Frame-Options: DENY everywhere EXCEPT pages we intentionally embed
    # SAME-ORIGIN in a notifications-client iframe. DENY blocks ALL framing —
    # even same-origin — which surfaces as Chrome's "localhost refused to
    # connect" inside the frame. SAMEORIGIN still blocks cross-origin
    # clickjacking (only this same app can frame these).
    #   /app/docs  — document viewer in the Reading Pane iframe (2026-05-21)
    #   /app/audio — podcast player in the floating overlay iframe (2026-08-03,
    #                bug 4cfabc0f: DENY left the overlay blank, standalone worked
    #                because top-level navigation ignores X-Frame-Options)
    if request.url.path in ( "/app/docs", "/app/audio" ):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
    else:
        response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# Include routers
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(system.router)
app.include_router(notifications.router)
app.include_router(speech.router)
app.include_router(queues.router)
app.include_router(jobs.router)
app.include_router(websocket.router)
app.include_router(websocket_admin.router)
# claude_code router retired 2026-05-05 — see src/rnd/v0.1.7/2026.05.05-claude-code-dispatch-retirement/
app.include_router(claude_code_queue.router)
app.include_router(embeddings.router)
app.include_router(mode.router)
app.include_router(stats.router)
app.include_router(deep_research.router)
app.include_router(io_files.router)
app.include_router(docs_files.router)
app.include_router(mock_job.router)
app.include_router(podcast_generator.router)
app.include_router(presentation_generator.router)
app.include_router(deep_research_to_podcast.router)
app.include_router(deep_research_to_presentation.router)
app.include_router(swe_team.router)
app.include_router(bug_fix_expediter.router)
app.include_router(test_suite.router)
app.include_router(decision_proxy.router)
app.include_router(pages.router)
app.include_router(peer.router)
app.include_router(speakerphone.router)
app.include_router(voice_persona.router)
app.include_router(multiplexer_config.router)
app.include_router(commons.router)
app.include_router(arbiter.router)
app.include_router(tasks.router)
app.include_router(fcm.router)
app.include_router(dm.router)   # /api/dm/* — notification-native AI↔AI DM (relocated legacy peer-DM route)
app.include_router(v2_ask.router)   # /api/v2/ask — CJ Flow v2 unified ask endpoint (unit D)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

async def load_stt_model():
    """
    Load and initialize the speech-to-text model pipeline.
    
    Preconditions:
        - config_mgr must be initialized
        - CUDA toolkit installed if using GPU
        - Model files available locally or downloadable
    
    Postconditions:
        - Returns initialized Whisper pipeline ready for transcription
        - Model loaded on specified device (CPU/GPU)
    
    Returns:
        pipeline: Initialized HuggingFace pipeline for ASR
    
    Raises:
        RuntimeError: If model cannot be loaded
        KeyError: If required config values are missing
    """
    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
    stt_device_id = config_mgr.get( "stt device id", default="cuda:0" )
    stt_model_id = config_mgr.get( "stt model id" )
    
    pipe = pipeline(
        "automatic-speech-recognition",
        model=stt_model_id,
        torch_dtype=torch_dtype,
        device=stt_device_id
    )
    return pipe

if __name__ == "__main__":
    import os
    # Read PORT from environment (Cloud Run sets this), default to 7999 for local development
    port = int( os.environ.get( "PORT", 7999 ) )
    print( f"[LUPIN] Starting FastAPI server on 0.0.0.0:{port}" )

    # Detect environment: disable reload for test and production, enable for local dev
    lupin_env = os.environ.get( "LUPIN_ENV", "" ).lower()
    is_production_or_test = lupin_env in ["production", "test", "testing"]

    # reload_dirs whitelist: only watch runtime code paths. Without this, --reload
    # would scan the entire src/ tree (including tests/, rnd/, and the LanceDB
    # long-term-memory store), causing repeated 12-18s server restarts whenever
    # any of those files was touched — surfacing in the browser as
    # ERR_CONNECTION_REFUSED for 30s-2min at a time.
    #
    # Bug 5b654a15 (2026-07-13): the whitelist above was NOT sufficient. `cosa` was
    # watched wholesale, and `src/cosa/tests/` lives INSIDE it — 476 test files, half
    # the watched tree. So every test-file write tripped StatReload: writing a pure
    # test file, touching nothing the server imports at runtime, took the server down
    # for the entire fleet.
    #
    # Why not `reload_excludes`? Because it is INERT here. Verbatim from
    # uvicorn/supervisors/statreload.py:
    #
    #     if config.reload_excludes or config.reload_includes:
    #         logger.warning("--reload-include and --reload-exclude have no effect
    #                         unless watchfiles is installed.")
    #
    # watchfiles is NOT in this image, so uvicorn falls back to StatReload, which
    # rglobs every reload_dir and ignores the exclude list entirely. Passing excludes
    # here would look like a fix, log a warning nobody reads, and change nothing.
    #
    # The mechanism that DOES work under StatReload is narrowing the watch set: name
    # cosa's runtime subpackages explicitly and leave tests/ + rnd/ + docs/ + history/
    # out of it. (Installing watchfiles and using reload_excludes is the tidier
    # long-term option — noted in the R&D doc as a follow-on, deliberately not bundled
    # into a P0 hotfix that would require an image rebuild.)
    #
    # Known, accepted consequence: `cosa/__init__.py` sits at the cosa root and is no
    # longer watched. It is near-static; editing it needs a container restart.
    #
    # R1 (2026-08-01, Rick's direct instruction): auto-reload is now OFF by default,
    # even on local dev. The StatReload watcher took the whole fleet's :7999 server
    # down 16 times in 30 min (7 of them from ordinary board_sweep.py writes). Everyone
    # edits freely now; the server is bounced DELIBERATELY when a change needs serving
    # (see the bounce controls). Opt back in for a focused solo dev loop with
    # LUPIN_RELOAD=1. Precedent: :8000 already runs reload-off via LUPIN_ENV=testing.
    #
    # ⚠️ This gate reads the environment ONLY at container START (inside __main__).
    # Editing LUPIN_RELOAD — or this line — is INERT until a docker RECREATE, not a
    # restart (`docker restart` reuses the container + its env). With reload now off
    # by default, that trap is easy to hit: reload-having-been-live has trained
    # everyone that source edits are served live; they are not until you bounce.
    reload_enabled = _reload_enabled( os.environ.get( "LUPIN_RELOAD" ), is_production_or_test )
    reload_kwargs = {}
    if reload_enabled:
        reload_kwargs[ "reload" ]      = True
        reload_kwargs[ "reload_dirs" ] = [
            "lupin_app", "lib", "lupin_cli", "lupin_mcp",
            # cosa RUNTIME subpackages only — NOT cosa/tests, cosa/rnd, cosa/docs, cosa/history
            "cosa/agents", "cosa/config", "cosa/crud_for_dataframes", "cosa/io",
            "cosa/memory", "cosa/orchestration", "cosa/repo", "cosa/rest",
            "cosa/tools", "cosa/training", "cosa/utils",
        ]

    uvicorn.run(
        "lupin_app.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,  # Single worker required for in-memory notification state (pending_responses dict)
        log_level="info",
        # Bug 5b654a15 — THE fleet-outage fix. On reload (or any shutdown) uvicorn waits
        # for open connections to drain. Lupin holds long-lived WebSockets (the browser UI
        # plus every `cc-listener-*` session), which NEVER drain on their own — so uvicorn
        # blocked forever at "Waiting for connections to close", the new worker never
        # booted, and the server stayed down for the WHOLE FLEET until a human ran
        # `docker restart`. On 2026-07-13 that was 4 manual restarts in ~25 minutes.
        #
        # This bounds the drain wait: after 5s uvicorn force-closes the stragglers and
        # completes the restart. It converts an unbounded hang into a blip. Clients
        # reconnect on their own. Applies to reload AND to ordinary shutdown, so it is
        # correct even once the excludes above make reloads rare.
        timeout_graceful_shutdown=5,
        **reload_kwargs
    )