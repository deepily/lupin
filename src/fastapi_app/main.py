#!/usr/bin/env python3
from logging import debug

from fastapi import FastAPI, Request, Query, HTTPException, File, UploadFile, WebSocket, WebSocketDisconnect, Depends
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
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
from lib.clients import genie_client as gc
from cosa.agents.v010.two_word_id_generator import TwoWordIdGenerator
from cosa.rest.websocket_manager import WebSocketManager
from cosa.rest.auth import get_current_user, get_current_user_id
from cosa.rest.queue_extensions import push_job_with_user
from cosa.rest.user_id_generator import email_to_system_id
from cosa.rest.notification_fifo_queue import NotificationFifoQueue

# Import routers
from cosa.rest.routers import system, notifications, audio, queues, jobs, websocket

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



async def emit_audio( msg: str, websocket_id: str = None ) -> None:
    """
    Skeletal implementation - logs calls and simulates audio emission
    
    Args:
        msg: The text message to be converted to audio
        websocket_id: Optional websocket identifier for future WebSocket routing
    """
    print( f"[STUB] emit_audio called:" )
    print( f"  - Message: '{msg}'" )
    print( f"  - WebSocket ID: {websocket_id if websocket_id else 'broadcast'}" )
    print( f"  - Audio URL would be: /api/get-audio?msg={quote( msg )}" )
    print( f"  - Timestamp: {datetime.now().isoformat()}" )
    
    # Simulate some async work
    await asyncio.sleep( 0.1 )
    
    # Log successful "emission"
    print( f"[STUB] Audio emission complete for websocket {websocket_id}" )


def create_emit_audio_callback():
    """Creates a sync wrapper for the async emit_audio function"""
    def sync_emit_audio( msg: str, websocket_id: str = None ):
        # Run async function in sync context
        asyncio.create_task( emit_audio( msg, websocket_id ) )
    return sync_emit_audio


@asynccontextmanager
async def lifespan( app: FastAPI ):
    """
    Manages the application lifecycle for FastAPI.
    
    Preconditions:
        - Environment variable GIB_CONFIG_MGR_CLI_ARGS must be set or empty string
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
    global config_mgr, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, jobs_run_queue, jobs_notification_queue, io_tbl, id_generator, app_debug, app_verbose, app_silent
    
    config_mgr = ConfigurationManager( env_var_name="GIB_CONFIG_MGR_CLI_ARGS" )
    
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
    
    # Initialize queues with emit_audio callback and websocket manager
    jobs_todo_queue = TodoFifoQueue( websocket_manager, snapshot_mgr, app, config_mgr, emit_audio_callback=create_emit_audio_callback(), debug=app_debug, verbose=app_verbose, silent=app_silent )
    jobs_done_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="done", emit_enabled=True )
    jobs_dead_queue = FifoQueue( websocket_mgr=websocket_manager, queue_name="dead", emit_enabled=True )
    jobs_run_queue = RunningFifoQueue( app, websocket_manager, snapshot_mgr, jobs_todo_queue, jobs_done_queue, jobs_dead_queue, config_mgr=config_mgr, emit_audio_callback=create_emit_audio_callback() )
    
    # Initialize notification queue with io_tbl logging
    jobs_notification_queue = NotificationFifoQueue( websocket_mgr=websocket_manager, emit_enabled=True, debug=app_debug, verbose=app_verbose )
    
    # Initialize input/output table
    io_tbl = InputAndOutputTable( debug=app_debug, verbose=app_verbose )
    
    # Load STT model on startup
    global whisper_pipeline
    print( "Loading distill whisper engine... ", end="" )
    whisper_pipeline = await load_stt_model()
    print( "Done!" )
    
    print( f"FastAPI startup complete at {datetime.now()}" )
    
    yield
    
    # Shutdown
    print( f"FastAPI shutdown at {datetime.now()}" )
    # Add any cleanup code here if needed

app = FastAPI(
    title="Genie-in-the-Box FastAPI",
    description="A FastAPI migration of the Genie-in-the-Box agent system",
    version="0.1.0",
    lifespan=lifespan
)

# Include routers
app.include_router(system.router)
app.include_router(notifications.router)
app.include_router(audio.router)
app.include_router(queues.router)
app.include_router(jobs.router)
app.include_router(websocket.router)

# Mount static files
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# REMOVED: websocket_endpoint - moved to websocket router


# REMOVED: websocket_queue_endpoint - moved to websocket router


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





# REMOVED: auth_test - moved to websocket router




# REMOVED: upload_and_transcribe_mp3_file - moved to audio router
    """
    Upload and transcribe MP3 audio file using Whisper model.
    
    Preconditions:
        - Request body must contain base64 encoded MP3 audio
        - Whisper pipeline must be initialized
        - Write permissions to docker path
        - Valid prompt_key in configuration
    
    Postconditions:
        - Audio file saved to disk temporarily
        - Transcription completed and processed
        - Response saved to last_response.json
        - Entry added to I/O table if not agent request
        - Job queued if agent request detected
    
    Args:
        request: FastAPI request containing base64 encoded audio
        prefix: Optional prefix for transcription processing
        prompt_key: Key for prompt selection (default: "generic")
        prompt_verbose: Verbosity level (default: "verbose")
    
    Returns:
        JSONResponse: Processed transcription results
    
    Raises:
        HTTPException: If audio decoding or transcription fails
    """
    global app_debug, app_verbose
    if debug:
        print( "upload_and_transcribe_mp3_file() called" )
        print( f"    prefix: [{prefix}]" )
        print( f"prompt_key: [{prompt_key}]" )
    
    # Get the request body (base64 encoded audio)
    body = await request.body()
    decoded_audio = base64.b64decode( body )
    
    path = gc.docker_path.format( "recording.mp3" )
    
    if app_debug: print( f"Saving file recorded audio bytes to [{path}]...", end="" )
    with open( path, "wb" ) as f:
        f.write( decoded_audio )
    if app_debug: print( " Done!" )
    
    # Transcribe the audio
    if app_debug: timer = sw.Stopwatch( f"Transcribing {path}..." )
    raw_transcription = whisper_pipeline( path, chunk_length_s=30, stride_length_s=5 )
    if app_debug: timer.print( "Done!", use_millis=True, end="\n\n" )
    
    raw_transcription = raw_transcription[ "text" ].strip()
    
    if app_debug: print( f"Result: [{raw_transcription}]" )
    
    # Fetch last response processed
    last_response_path = "/io/last_response.json"
    if os.path.isfile( du.get_project_root() + last_response_path ):
        with open( du.get_project_root() + last_response_path ) as json_file:
            last_response = json.load( json_file )
    else:
        last_response = None
    
    # Process the transcription
    # app_debug   = config_mgr.get( "app_debug", default=False, return_type="boolean" )
    # app_verbose = config_mgr.get( "app_verbose", default=False, return_type="boolean" )
    #
    munger = mmm.MultiModalMunger(
        raw_transcription, prefix=prefix, prompt_key=prompt_key, debug=app_debug, 
        verbose=app_verbose, last_response=last_response, config_mgr=config_mgr
    )
    
    try:
        if munger.is_agent():
            print( f"Munger: Posting [{munger.transcription}] to the agent's todo queue..." )
            munger.results = jobs_todo_queue.push_job( munger.transcription )
        else:
            print( "Munger: Transcription is not for agent. Returning brute force munger string..." )
            # Insert into I/O table
            io_tbl.insert_io_row( 
                input_type=f"upload and proofread mp3: {munger.mode}", 
                input=raw_transcription, 
                output_raw=munger.transcription, 
                output_final=munger.get_jsons() 
            )
        
        # Write JSON string to the file system
        last_response = munger.get_jsons()
        du.write_string_to_file( du.get_project_root() + last_response_path, last_response )
        
        return JSONResponse( content=json.loads( last_response ) )
        
    except Exception as e:
        # Pass through the actual error details without assumptions
        error_response = {
            "status": "error",
            "error_type": type( e ).__name__,
            "error_message": str( e ),
            "transcription": raw_transcription,
            "timestamp": datetime.now().isoformat()
        }
        
        print( f"ERROR: {type( e ).__name__}: {e}" )
        print( f"Returning error response to client: {error_response}" )
        
        # Return 422 Unprocessable Entity instead of 500 to indicate business logic failure
        return JSONResponse( 
            status_code=422, 
            content=error_response 
        )


@app.post( "/api/get-audio" )
async def get_tts_audio( request: Request ):
    """
    WebSocket-based TTS endpoint that streams audio via WebSocket.
    
    Preconditions:
        - Request body must contain session_id and text
        - WebSocket connection must exist for session_id
        - OpenAI API key must be available
        - config_mgr must be initialized
        
    Postconditions:
        - Returns immediate status response
        - Streams audio chunks via WebSocket to specified session
        
    Args:
        request: FastAPI request containing JSON body with session_id and text
        
    Returns:
        JSONResponse: Immediate status response
    """
    try:
        # Parse request body
        request_data = await request.json()
        session_id = request_data.get( "session_id" )
        msg = request_data.get( "text" )
        if not session_id or not msg:
            raise HTTPException( status_code=400, detail="Missing session_id or text" )
        
        # Check if WebSocket connection exists
        if not websocket_manager.is_connected( session_id ):
            raise HTTPException( status_code=404, detail=f"No WebSocket connection for session {session_id}" )
        
        print( f"[TTS] Hybrid TTS request - session: {session_id}, msg: '{msg}'" )
        
        # Start hybrid TTS streaming in background
        task = asyncio.create_task( stream_tts_hybrid( session_id, msg ) )
        active_tasks[session_id] = task
        
        # Return immediate status response
        return JSONResponse({
            "status": "success",
            "message": "TTS generation started",
            "session_id": session_id
        })
        
    except HTTPException:
        raise
    except Exception as e:
        print( f"[ERROR] TTS request failed: {e}" )
        raise HTTPException( status_code=500, detail=f"TTS request error: {str(e)}" )


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
            "type": "status",
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
                        "type": "audio_complete",
                        "text": f"Streaming complete ({chunk_count} chunks, {total_time:.1f}s)",
                        "status": "success"
                    })
        
        except Exception as tts_error:
            raise tts_error
    
    except Exception as e:
        print( f"[ERROR] Hybrid TTS failed for {session_id}: {e}" )
        if session_id in active_websockets:
            await websocket.send_json({
                "type": "status",
                "text": f"TTS generation failed: {str(e)}",
                "status": "error"
            })






# REMOVED: push - moved to queues router


# REMOVED: get_queue - moved to queues router












# REMOVED: delete_snapshot - moved to jobs router


# REMOVED: get_answer - moved to jobs router


# REMOVED: upload_and_transcribe_wav_file - moved to audio router


if __name__ == "__main__":
    uvicorn.run(
        "fastapi_app.main:app",
        host="0.0.0.0",
        port=7999,
        reload=True,
        log_level="info"
    )