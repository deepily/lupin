#!/usr/bin/env python3
"""
FastAPI Server-Sent Events (SSE) Implementation - Proof of Concept

This is a standalone SSE server for validating the synchronous notification pattern.
Runs on port 8000 for isolated testing before production integration.

Usage:
    python server.py

Then in another terminal:
    python client.py "Test message" 5 120
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio
import json
from datetime import datetime
import random

app = FastAPI()

async def event_generator( message: str, heartbeat_interval: int = 5 ):
    """
    Generator that yields SSE events: heartbeats and final result.
    Simulates processing time between 2-120 seconds.

    Requires:
        - message is a string (can be empty)
        - heartbeat_interval is a positive integer (seconds)

    Ensures:
        - Yields ack event immediately
        - Yields heartbeat events every heartbeat_interval seconds
        - Yields result event after processing completes
        - All events are properly formatted SSE (data: {json}\n\n)

    Raises:
        - No exceptions (handles errors internally)
    """
    processing_time = random.uniform( 2, 120 )
    start_time = asyncio.get_event_loop().time()

    # Send initial acknowledgment
    ack_event = {
        "type": "ack",
        "message": "Request received",
        "timestamp": datetime.utcnow().isoformat()
    }
    yield f"data: {json.dumps( ack_event )}\n\n"

    # Simulate async processing with heartbeats
    elapsed = 0
    while elapsed < processing_time:
        await asyncio.sleep( heartbeat_interval )
        elapsed = asyncio.get_event_loop().time() - start_time

        # Send heartbeat
        heartbeat_event = {
            "type": "heartbeat",
            "elapsed": round( elapsed, 2 )
        }
        yield f"data: {json.dumps( heartbeat_event )}\n\n"

    # Send final result
    result = f"Processed: {message} (took {round( processing_time, 2 )}s)"
    result_event = {
        "type": "result",
        "data": result,
        "timestamp": datetime.utcnow().isoformat()
    }
    yield f"data: {json.dumps( result_event )}\n\n"


@app.post( "/process" )
async def process_message( payload: dict ):
    """
    SSE endpoint that streams events back to client.

    Requires:
        - payload is a dictionary with optional keys:
          - "message": str (default: "")
          - "heartbeat_interval": int (default: 5)

    Ensures:
        - Returns StreamingResponse with SSE content type
        - Headers configured to prevent buffering
        - Events streamed via event_generator

    Raises:
        - No exceptions expected (FastAPI handles validation)

    Example payload:
        {"message": "your message", "heartbeat_interval": 5}
    """
    message = payload.get( "message", "" )
    heartbeat_interval = payload.get( "heartbeat_interval", 5 )

    return StreamingResponse(
        event_generator( message, heartbeat_interval ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


if __name__ == "__main__":
    import uvicorn
    print( "Starting SSE PoC server on http://localhost:8000" )
    print( "Endpoint: POST /process" )
    print( "Press Ctrl+C to stop" )
    uvicorn.run( app, host="0.0.0.0", port=8000 )
