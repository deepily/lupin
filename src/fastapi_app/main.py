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

# Add paths for imports
sys.path.append( os.path.join( os.path.dirname( __file__ ), '..' ) )
sys.path.append( os.path.dirname( __file__ ) )

import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
from openai import OpenAI

from cosa.config.configuration_manager import ConfigurationManager
from cosa.rest import multimodal_munger as mmm
from cosa.memory.input_and_output_table import InputAndOutputTable
from cosa.memory.solution_snapshot_mgr import SolutionSnapshotManager
from cosa.rest.todo_fifo_queue import TodoFifoQueue
from cosa.rest.fifo_queue import FifoQueue
from cosa.rest.running_fifo_queue import RunningFifoQueue
import cosa.utils.util as du
import cosa.utils.util_stopwatch as sw
from lib.clients import lupin_client as gc
from cosa.agents.v010.two_word_id_generator import TwoWordIdGenerator
from cosa.rest.websocket_manager import WebSocketManager
from cosa.rest.auth import get_current_user, get_current_user_id
from cosa.rest.user_id_generator import email_to_system_id
from cosa.rest.notification_fifo_queue import NotificationFifoQueue

# Import routers
from cosa.rest.routers import system, notifications, speech, queues, jobs, websocket, websocket_admin
from cosa.rest.queue_consumer import start_todo_producer_run_consumer_thread

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

async def emit_speech( msg: str, user_id: str = "ricardo_felipe_ruiz_6bdc", websocket_id: str = None ) -> None:
    """
    Generate TTS speech and emit via WebSocket to specific user or broadcast.
    
    Args:
        msg: The text message to be converted to speech
        user_id: User ID for user-specific routing (preferred)
        websocket_id: Optional websocket identifier for backwards compatibility
    """
    print( f"[SPEECH] emit_speech called:" )
    print( f"  - Message: '{msg}'" )
    print( f"  - User ID: {user_id if user_id else 'none'}" )
    print( f"  - WebSocket ID: {websocket_id if websocket_id else 'none'}" )
    
    try:
        # Emit speech_update event to trigger TTS in browser
        speech_data = {
            "text": msg,
            "timestamp": datetime.now().isoformat()
        }
        
        if user_id and user_id != "ricardo_felipe_ruiz_6bdc":
            # Emit to specific user (preferred method)
            await websocket_manager.emit_to_user( user_id, "tts_job_request", speech_data )
            print( f"[SPEECH] Emitted tts_job_request to user {user_id}" )
        elif user_id == "ricardo_felipe_ruiz_6bdc":
            # Default user - still use user-based routing
            await websocket_manager.emit_to_user( user_id, "tts_job_request", speech_data )
            print( f"[SPEECH] Emitted tts_job_request to default user {user_id}" )
        elif websocket_id:
            # Backwards compatibility: Emit to specific session
            await websocket_manager.emit_to_session( websocket_id, "tts_job_request", speech_data )
            print( f"[SPEECH] Emitted tts_job_request to session {websocket_id} (backwards compatibility)" )
        else:
            # Fallback: Broadcast to all connected clients
            await websocket_manager.async_emit( "tts_job_request", speech_data )
            print( f"[SPEECH] Broadcasted tts_job_request to all connections (fallback)" )
            
    except Exception as e:
        print( f"[SPEECH] Error emitting speech: {e}" )
        # Don't raise - this shouldn't break the calling flow


def create_emit_speech_callback():
    """Creates a sync wrapper for the async emit_speech function with user-based routing"""
    def sync_emit_speech( msg: str, user_id: str = "ricardo_felipe_ruiz_6bdc", websocket_id: str = None ):
        import threading
        
        def run_in_thread():
            try:
                # Run async function in isolated thread with its own event loop
                asyncio.run( emit_speech( msg, user_id=user_id, websocket_id=websocket_id ) )
            except Exception as e:
                print( f"[SPEECH] Error in speech thread: {e}" )
        
        # Always run in separate thread to avoid event loop conflicts
        thread = threading.Thread( target=run_in_thread, daemon=True )
        thread.start()
        print( f"[SPEECH] Started speech emission thread for: '{msg}' (user: {user_id})" )
    return sync_emit_speech


async def clock_loop():
    """
    Background task that emits clock updates every second to all connected WebSocket clients.
    
    This replaces the Flask/Socket.IO enter_clock_loop() functionality with FastAPI/WebSocket.
    """
    print( "[CLOCK] Starting clock update loop..." )
    while True:
        try:
            # Emit time update to all connected WebSocket clients
            current_time = du.get_current_time( format="%Y-%m-%d @ %H:%M" )
            await websocket_manager.async_emit( 'sys_time_update', { 'date': current_time } )
            
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
    
    Periodically sends ping messages to all WebSocket connections
    to detect and remove dead connections.
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
    
    Periodically removes stale WebSocket sessions that have been
    connected for longer than the configured maximum age.
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
    
    # Initialize the ID generator singleton
    id_generator = TwoWordIdGenerator()
    
    # Get configuration flags
    app_debug   = config_mgr.get( "app_debug",   default=False, return_type="boolean" )
    app_verbose = config_mgr.get( "app_verbose", default=False, return_type="boolean" )
    app_silent  = config_mgr.get( "app_silent",  default=True,  return_type="boolean" )
    
    # Initialize other components
    path_to_snapshots_dir_wo_root = config_mgr.get( "path_to_snapshots_dir_wo_root" )
    path_to_snapshots = du.get_project_root() + path_to_snapshots_dir_wo_root
    snapshot_mgr = SolutionSnapshotManager( path_to_snapshots, debug=app_debug, verbose=app_verbose )
    
    # Initialize queues with emit_speech callback and websocket manager
    jobs_todo_queue = TodoFifoQueue( websocket_manager, snapshot_mgr, app, config_mgr, emit_speech_callback=create_emit_speech_callback(), debug=app_debug, verbose=app_verbose, silent=app_silent )
    jobs_done_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="done", emit_enabled=True )
    jobs_dead_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="dead", emit_enabled=True )
    jobs_run_queue = RunningFifoQueue( app, websocket_manager, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, config_mgr=config_mgr, emit_speech_callback=create_emit_speech_callback() )
    
    # Initialize notification queue with io_tbl logging
    jobs_notification_queue = NotificationFifoQueue( websocket_mgr=websocket_manager, emit_enabled=True, debug=app_debug, verbose=app_verbose )
    
    # Initialize input/output table
    io_tbl = InputAndOutputTable( debug=app_debug, verbose=app_verbose )
    
    # Load STT model on startup
    global whisper_pipeline
    print( "Loading distill whisper engine... ", end="" )
    whisper_pipeline = await load_stt_model()
    print( "Done!" )
    
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
    
    # Add any other cleanup code here if needed

app = FastAPI(
    title="Genie-in-the-Box FastAPI",
    description="A FastAPI migration of the Genie-in-the-Box agent system",
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

# Include routers
app.include_router(system.router)
app.include_router(notifications.router)
app.include_router(speech.router)
app.include_router(queues.router)
app.include_router(jobs.router)
app.include_router(websocket.router)
app.include_router(websocket_admin.router)

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
    stt_device_id = config_mgr.get( "stt_device_id", default="cuda:0" )
    stt_model_id = config_mgr.get( "stt_model_id" )
    
    pipe = pipeline(
        "automatic-speech-recognition",
        model=stt_model_id,
        torch_dtype=torch_dtype,
        device=stt_device_id
    )
    return pipe

async def stream_tts_elevenlabs( session_id: str, msg: str, voice_id: str = "21m00Tcm4TlvDq8ikWAM", stability: float = 0.5, similarity_boost: float = 0.5 ):
    """
    ElevenLabs TTS streaming: Forward chunks immediately via WebSocket.
    Connects to ElevenLabs WebSocket API and streams audio chunks in real-time.
    
    Args:
        session_id: Session ID for WebSocket connection
        msg: Text to convert to speech
        voice_id: ElevenLabs voice ID (default: Rachel)
        stability: Voice stability (0.0-1.0)
        similarity_boost: Voice similarity boost (0.0-1.0)
    """
    websocket = websocket_manager.active_connections.get( session_id )
    if not websocket:
        print( f"[ERROR] No WebSocket connection for session {session_id}" )
        return
    
    try:
        # Get ElevenLabs API key
        api_key = du.get_api_key( "elevenlabs" )
        if not api_key:
            raise Exception( "ElevenLabs API key not found" )
        
        print( f"[TTS-ELEVENLABS] Starting generation for: '{msg}'" )
        
        # Send status update
        await websocket.send_json({
            "type": "audio_streaming_status",
            "text": "Connecting to ElevenLabs...",
            "status": "loading",
            "provider": "elevenlabs"
        })
        
        # ElevenLabs WebSocket URL
        elevenlabs_ws_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id=eleven_turbo_v2_5"
        
        chunk_count = 0
        start_time = time.time()
        
        # Connect to ElevenLabs WebSocket
        async with websockets.connect(
            elevenlabs_ws_url,
            additional_headers={
                "xi-api-key": api_key
            }
        ) as elevenlabs_ws:
            
            # Send initial configuration
            config = {
                "text": " ",  # Initial space to start the stream
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity_boost
                },
                "generation_config": {
                    "chunk_length_schedule": [120, 160, 250, 290]
                }
            }
            await elevenlabs_ws.send( json.dumps( config ) )
            
            # Send the actual text
            text_message = {
                "text": msg + " ",
                "try_trigger_generation": True
            }
            await elevenlabs_ws.send( json.dumps( text_message ) )
            
            # Send end-of-stream marker
            eos_message = {"text": ""}
            await elevenlabs_ws.send( json.dumps( eos_message ) )
            
            # Send status update
            await websocket.send_json({
                "type": "audio_streaming_status", 
                "text": "Streaming audio from ElevenLabs...",
                "status": "streaming",
                "provider": "elevenlabs"
            })
            
            # Receive and forward audio chunks
            try:
                async for message in elevenlabs_ws:
                    # Check if our client is still connected
                    if not websocket_manager.is_connected( session_id ):
                        print( f"[TTS-ELEVENLABS] Connection lost for {session_id}" )
                        break
                    
                    try:
                        # ElevenLabs sends JSON messages
                        data = json.loads( message )
                        
                        if "audio" in data:
                            # Decode base64 audio and forward as binary
                            audio_chunk = base64.b64decode( data["audio"] )
                            chunk_count += 1
                            
                            # Forward chunk immediately to client
                            try:
                                await websocket.send_bytes( audio_chunk )
                            except Exception as e:
                                print( f"[ERROR] Failed to forward ElevenLabs chunk {chunk_count}: {e}" )
                                break
                        
                        elif "isFinal" in data and data["isFinal"]:
                            # Stream is complete
                            print( f"[TTS-ELEVENLABS] Stream marked as final" )
                            break
                            
                    except json.JSONDecodeError:
                        # Might be binary data, skip
                        continue
                    except Exception as e:
                        print( f"[ERROR] Error processing ElevenLabs message: {e}" )
                        continue
            
            except websockets.exceptions.ConnectionClosed:
                print( f"[TTS-ELEVENLABS] ElevenLabs WebSocket connection closed" )
        
        # Calculate timing
        total_time = time.time() - start_time
        
        print( f"[TTS-ELEVENLABS] Complete - {chunk_count} chunks in {total_time:.2f}s" )
        
        # Signal completion - use audio_streaming_complete for consistency
        if websocket_manager.is_connected( session_id ):
            await websocket.send_json({
                "type": "audio_streaming_complete",
                "text": f"ElevenLabs streaming complete ({chunk_count} chunks, {total_time:.1f}s)",
                "status": "success",
                "provider": "elevenlabs"
            })
    
    except Exception as e:
        print( f"[ERROR] ElevenLabs TTS failed for {session_id}: {e}" )
        if websocket_manager.is_connected( session_id ):
            await websocket.send_json({
                "type": "audio_streaming_status",
                "text": f"ElevenLabs TTS generation failed: {str(e)}",
                "status": "error",
                "provider": "elevenlabs"
            })


async def stream_tts_hybrid( session_id: str, msg: str ):
    """
    Hybrid TTS streaming: Forward chunks immediately, client plays when complete.
    Simple, no format complexity, no buffering - just pipe OpenAI chunks to WebSocket.
    
    Args:
        session_id: Session ID for WebSocket connection
        msg: Text to convert to speech
    """
    websocket = websocket_manager.active_connections.get( session_id )
    if not websocket:
        print( f"[ERROR] No WebSocket connection for session {session_id}" )
        return
    
    try:
        # Always use OpenAI with MP3 - simple and reliable
        api_key = du.get_api_key( "openai" )
        # TODO: We should be dynamically getting the proper base URL for this connection.
        # Override base URL for TTS - vLLM doesn't support TTS, need real OpenAI API
        client = OpenAI( api_key=api_key, base_url="https://api.openai.com/v1" )
        
        print( f"[TTS-HYBRID] Starting generation for: '{msg}'" )
        
        # Send status update
        await websocket.send_json({
            "type": "audio_streaming_status",
            "text": "Generating and streaming audio...",
            "status": "loading"
        })
        
        
        # Stream from OpenAI directly to WebSocket - no buffering, no format logic
        try:
            with client.audio.speech.with_streaming_response.create(
                model="tts-1",
                voice="alloy",
                speed=1.125,
                response_format="mp3",  # Always MP3 - simple and universal
                input=msg
            ) as response:
                
                chunk_count = 0
                start_time = time.time()
                
                # Forward each chunk immediately as received
                for chunk in response.iter_bytes( chunk_size=8192 ):
                    # Check connection
                    if not websocket_manager.is_connected( session_id ):
                        print( f"[TTS-HYBRID] Connection lost for {session_id}" )
                        break
                    
                    if chunk:
                        chunk_count += 1
                        
                        # Forward chunk immediately - no processing, no buffering
                        try:
                            await websocket.send_bytes( chunk )
                        except Exception as e:
                            print( f"[ERROR] Failed to forward chunk {chunk_count}: {e}" )
                            break
                
                # Calculate timing
                total_time = time.time() - start_time
                
                print( f"[TTS-HYBRID] Complete - {chunk_count} chunks in {total_time:.2f}s" )
                
                # Signal completion
                if websocket_manager.is_connected( session_id ):
                    await websocket.send_json({
                        "type": "audio_streaming_complete",
                        "text": f"Streaming complete ({chunk_count} chunks, {total_time:.1f}s)",
                        "status": "success"
                    })
        
        except Exception as tts_error:
            raise tts_error
    
    except Exception as e:
        print( f"[ERROR] Hybrid TTS failed for {session_id}: {e}" )
        if session_id in active_websockets:
            await websocket.send_json({
                "type": "audio_streaming_status",
                "text": f"TTS generation failed: {str(e)}",
                "status": "error"
            })

if __name__ == "__main__":
    uvicorn.run(
        "fastapi_app.main:app",
        host="0.0.0.0",
        port=7999,
        reload=True,
        log_level="info"
    )