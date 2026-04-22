"""
ElevenLabs PCM 24000 Streaming Demo Server

Minimal FastAPI server to test PCM streaming from ElevenLabs.
This is a proof-of-concept to validate smooth audio playback
before modifying the production notifications.js.

Usage:
    uvicorn server:app --port 8000 --reload
"""

import os
import base64
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from typing import Optional
import websockets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI( title="ElevenLabs PCM 24000 Streaming Demo" )


@app.get( "/" )
async def get_demo_page():
    """Serve the demo HTML page."""
    html_path = Path( __file__ ).parent / "index.html"
    return HTMLResponse( html_path.read_text() )


@app.websocket( "/ws/pcm-tts" )
async def pcm_tts_endpoint(
    websocket: WebSocket,
    model_id: Optional[str] = Query( default="eleven_turbo_v2_5" ),
    voice_id: Optional[str] = Query( default="G7ILShrCNLfmS0A37SXS" )
):
    """
    WebSocket endpoint that streams PCM 24000 audio from ElevenLabs.

    Connects to ElevenLabs with output_format=pcm_24000 and forwards
    raw PCM chunks to the browser for Web Audio API playback.

    Args:
        model_id: ElevenLabs model ID (default: eleven_turbo_v2_5)
        voice_id: ElevenLabs voice ID (default: Sam)
    """
    await websocket.accept()

    # Get API key from environment
    api_key = os.getenv( "ELEVENLABS_API_KEY" )
    if not api_key:
        await websocket.send_json( {
            "type": "error",
            "message": "ELEVENLABS_API_KEY not set in environment"
        } )
        await websocket.close()
        return

    # ElevenLabs configuration
    print( f"[PCM-DEMO] Using model_id: {model_id}, voice_id: {voice_id}" )

    # Connect to ElevenLabs with PCM 24000 format
    elevenlabs_url = (
        f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
        f"?model_id={model_id}&output_format=pcm_24000"
    )

    try:
        print( f"[PCM-DEMO] Connecting to ElevenLabs..." )
        elevenlabs_ws = await websockets.connect(
            elevenlabs_url,
            additional_headers={ "xi-api-key": api_key }
        )

        async with elevenlabs_ws:
            print( f"[PCM-DEMO] Connected to ElevenLabs WebSocket" )

            # Send status to client
            await websocket.send_json( {
                "type": "status",
                "message": "Connected to ElevenLabs, starting stream..."
            } )

            # Send configuration message
            config_message = {
                "text": " ",  # Initial space to start stream
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.5,
                    "style": 0.0,
                    "use_speaker_boost": False
                },
                "generation_config": {
                    "chunk_length_schedule": [120, 160, 250, 290]  # Low latency
                }
            }
            await elevenlabs_ws.send( json.dumps( config_message ) )

            # Send test text
            test_text = (
                "Hello! This is a test of PCM streaming from ElevenLabs. "
                "The audio should sound smooth without any choppy stuttering. "
                "If you can hear this clearly without gaps or glitches, "
                "then the PCM 24000 format with Web Audio API scheduling is working correctly."
            )

            text_message = {
                "text": test_text,
                "try_trigger_generation": True
            }
            await elevenlabs_ws.send( json.dumps( text_message ) )

            # Send end-of-stream marker
            await elevenlabs_ws.send( json.dumps( { "text": "" } ) )

            print( f"[PCM-DEMO] Sent text, streaming audio..." )

            # Stream audio chunks from ElevenLabs to client
            chunk_count = 0
            total_bytes = 0

            async for message in elevenlabs_ws:
                try:
                    data = json.loads( message )

                    if data.get( "audio" ):
                        # Decode base64 audio chunk
                        audio_chunk = base64.b64decode( data["audio"] )
                        chunk_count += 1
                        total_bytes += len( audio_chunk )

                        # Forward raw PCM bytes to client
                        await websocket.send_bytes( audio_chunk )

                        print( f"[PCM-DEMO] Sent chunk {chunk_count}: {len( audio_chunk )} bytes" )

                    elif data.get( "isFinal" ):
                        print( f"[PCM-DEMO] Stream complete" )
                        break

                    elif data.get( "error" ):
                        error_msg = data.get( "error", "Unknown error" )
                        print( f"[PCM-DEMO] ElevenLabs error: {error_msg}" )
                        await websocket.send_json( {
                            "type": "error",
                            "message": f"ElevenLabs error: {error_msg}"
                        } )
                        break

                except json.JSONDecodeError:
                    print( f"[PCM-DEMO] Non-JSON message received" )

            # Send completion message
            await websocket.send_json( {
                "type": "complete",
                "chunks": chunk_count,
                "total_bytes": total_bytes
            } )

            print( f"[PCM-DEMO] Finished: {chunk_count} chunks, {total_bytes} bytes total" )

    except websockets.exceptions.WebSocketException as e:
        print( f"[PCM-DEMO] WebSocket error: {e}" )
        await websocket.send_json( {
            "type": "error",
            "message": f"WebSocket error: {str( e )}"
        } )

    except Exception as e:
        print( f"[PCM-DEMO] Error: {e}" )
        await websocket.send_json( {
            "type": "error",
            "message": f"Error: {str( e )}"
        } )


if __name__ == "__main__":
    import uvicorn
    print( "[PCM-DEMO] Starting server on port 8000..." )
    uvicorn.run( app, host="0.0.0.0", port=8000 )
