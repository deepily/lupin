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
        "  python src/fastapi_app/main.py"
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
from cosa.rest.routers import system, notifications, speech, queues, jobs, websocket, websocket_admin, auth, admin, claude_code_queue, embeddings, mode, stats, deep_research, mock_job, io_files, docs_files, podcast_generator, presentation_generator, deep_research_to_podcast, deep_research_to_presentation, swe_team, bug_fix_expediter, decision_proxy, test_suite, pages, peer, conversation_mode, voice_persona, multiplexer_config
from cosa.rest.queue_consumer import start_todo_producer_run_consumer_thread
from cosa.rest.job_persistence import mark_interrupted_jobs

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
    global config_mgr, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, jobs_run_queue, jobs_notification_queue, io_tbl, id_generator, app_debug, app_verbose, app_silent, clock_task, consumer_thread, websocket_heartbeat_task, websocket_cleanup_task
    
    config_mgr = ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" )

    # Get configuration flags (needed for debug output below)
    app_debug   = config_mgr.get( "app debug",   default=False, return_type="boolean" )
    app_verbose = config_mgr.get( "app verbose", default=False, return_type="boolean" )
    app_silent  = config_mgr.get( "app silent",  default=True,  return_type="boolean" )

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
        # Use LanceDB backend
        lancedb_path = config_mgr.get( "solution snapshots lancedb path", default="/src/conf/long-term-memory/lupin.lancedb" )
        lancedb_table = config_mgr.get( "solution snapshots lancedb table", default="solution_snapshots" )
        
        # Convert relative path to absolute
        if lancedb_path.startswith( "/" ):
            lancedb_path = du.get_project_root() + lancedb_path
        
        config = {
            "db_path": lancedb_path,
            "table_name": lancedb_table
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
    
    # Initialize queues with websocket manager
    # NOTE (Session 97): emit_speech_callback is deprecated - queues now use notification service via _notify()
    jobs_todo_queue = TodoFifoQueue( websocket_manager, snapshot_mgr, app, config_mgr, emit_speech_callback=None, debug=app_debug, verbose=app_verbose, silent=app_silent )
    jobs_done_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="done", emit_enabled=True )
    jobs_dead_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="dead", emit_enabled=True )
    jobs_run_queue = RunningFifoQueue( app, websocket_manager, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, config_mgr=config_mgr, emit_speech_callback=None )
    
    # Initialize notification queue with io_tbl logging
    jobs_notification_queue = NotificationFifoQueue( websocket_mgr=websocket_manager, emit_enabled=True, debug=app_debug, verbose=app_verbose )
    
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
        if total_interrupted > 0 or preserved > 0:
            print( f"[CJ-PERSIST] Startup recovery: {total_interrupted} interrupted, {preserved} scheduled preserved" )
        else:
            print( "[CJ-PERSIST] No interrupted or scheduled jobs found" )
    except Exception as e:
        print( f"[WARN] CJ Flow startup recovery failed: {e}" )

    # ===================================================================
    # GPU Model Loading (smallest → largest to minimize CUDA fragmentation)
    # ===================================================================

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
    global whisper_pipeline
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

    # Restore scheduled jobs that survived the restart (preserved by mark_interrupted_jobs)
    try:
        from cosa.rest.job_persistence import get_restorable_jobs
        from cosa.rest.agentic_job_factory import create_agentic_job

        restorable = get_restorable_jobs()
        for job_data in restorable:
            routing_cmd = job_data[ "routing_command" ]
            if not routing_cmd:
                print( f"[CJ-PERSIST] Cannot restore {job_data[ 'id_hash' ]}: no routing_command" )
                continue

            job = create_agentic_job(
                command    = routing_cmd,
                args_dict  = job_data.get( "metadata_json", {} ),
                user_id    = job_data[ "user_id" ],
                user_email = job_data[ "user_email" ],
                session_id = job_data[ "session_id" ],
                debug      = app_debug,
            )
            if job is None:
                print( f"[CJ-PERSIST] Cannot restore {job_data[ 'id_hash' ]}: factory returned None" )
                continue

            job.scheduled_at = job_data[ "scheduled_at" ]
            if job_data.get( "monopolize" ):
                job.monopolize = True

            jobs_todo_queue.push( job )
            print( f"[CJ-PERSIST] Restored scheduled job: {job_data[ 'id_hash' ]} "
                   f"(type={job_data[ 'job_type' ]}, scheduled_at={job_data[ 'scheduled_at' ]})" )

        if restorable:
            print( f"[CJ-PERSIST] Restored {len( restorable )} scheduled job(s)" )
    except Exception as e:
        print( f"[WARN] Scheduled job restoration failed: {e}" )

    print( f"FastAPI startup complete at {datetime.now()}" )
    
    yield
    
    # Shutdown
    print( f"FastAPI shutdown at {datetime.now()}" )
    
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

    # Add any other cleanup code here if needed

app = FastAPI(
    title="Lupin FastAPI",
    description="A FastAPI migration of the Lupin agent system",
    version="0.6.0",
    lifespan=lifespan
)

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
app.include_router(conversation_mode.router)
app.include_router(voice_persona.router)
app.include_router(multiplexer_config.router)

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
    reload_kwargs = {}
    if not is_production_or_test:
        reload_kwargs[ "reload" ] = True
        reload_kwargs[ "reload_dirs" ] = [ "fastapi_app", "cosa", "lib", "lupin_cli", "lupin_mcp" ]
    uvicorn.run(
        "fastapi_app.main:app",
        host="0.0.0.0",
        port=port,
        workers=1,  # Single worker required for in-memory notification state (pending_responses dict)
        log_level="info",
        **reload_kwargs
    )