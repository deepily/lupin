"""
Two speech streams open on one audio socket, and each frame names its utterance.

The app is assembled from the real speech router, the real websocket router and a real
WebSocketManager. The test enters at the two doors a client uses: POST
/api/get-speech-elevenlabs and /ws/audio/{session_id}. Only ElevenLabs is faked.

The first request's stream is held open until the second request's stream has finished.
So the completions arrive in the reverse of request order. A client that pairs a
completion with the utterance it asked for first, or last, gets one of them wrong.
"""

import asyncio
import base64
import json
import sys
import threading
import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import cosa.rest.routers.speech as speech
import cosa.rest.routers.websocket as websocket_router
from cosa.rest.auth import get_current_user_id
from cosa.rest.websocket_manager import WebSocketManager

SESSION_ID   = "wise penguin"
GATE_SECONDS = 10


def _audio( raw ):
    return json.dumps( { "audio": base64.b64encode( raw ).decode( "ascii" ) } )


class _HeldElevenWs:
    """A fake ElevenLabs socket that yields `before`, waits for the gate, then yields `after`."""

    def __init__( self, before, after, gate ):
        self.before = before
        self.after  = after
        self.gate   = gate

    async def __aenter__( self ):
        return self

    async def __aexit__( self, *exc ):
        return False

    async def send( self, data ):
        pass

    async def __aiter__( self ):
        for message in self.before: yield message
        waited = 0.0
        while not self.gate.is_set():
            if waited > GATE_SECONDS: raise RuntimeError( "the gate was never opened" )
            await asyncio.sleep( 0.005 )
            waited += 0.005
        for message in self.after: yield message


def _assembled( second_stream_messages ):
    """
    Build the app, its fake main module, and the connect() that feeds the two streams.

    Ensures:
        - the first connect() gets a stream held open on the returned gate
        - the second connect() gets `second_stream_messages` and is never held
    """
    gate   = threading.Event()
    opened = threading.Event(); opened.set()
    feeds  = [
        _HeldElevenWs( [ _audio( b"A1" ) ], [ _audio( b"A2" ), json.dumps( { "isFinal": True } ) ], gate ),
        _HeldElevenWs( second_stream_messages, [ ], opened ),
    ]

    async def connect( url, additional_headers=None ):
        return feeds.pop( 0 )

    main = types.SimpleNamespace(
        websocket_manager = WebSocketManager(),
        active_tasks      = { },
        config_mgr        = None,
        app_debug         = False,
        app_verbose       = False,
    )
    app = FastAPI()
    app.include_router( speech.router )
    app.include_router( websocket_router.router )
    app.dependency_overrides[ get_current_user_id ] = lambda: "u1"
    return app, main, connect, gate


def _run_two_overlapping_streams( second_stream_messages ):
    """
    Ask for utterance A, then utterance B, on one audio socket; return every frame in order.

    Ensures:
        - returns a list of ( "json", dict ) and ( "bytes", bytes ) in arrival order
        - A's stream is released only after B's audio_streaming_complete has arrived
    """
    app, main, connect, gate = _assembled( second_stream_messages )
    pkg = MagicMock(); pkg.main = main
    frames = [ ]
    with patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": main } ), \
         patch.object( speech.websockets, "connect", new=connect ), \
         patch.object( speech.du, "get_api_key", return_value="KEY" ), \
         TestClient( app ) as client:
        with client.websocket_connect( f"/ws/audio/{SESSION_ID}" ) as ws:
            assert ws.receive_json()[ "type" ] == "audio_streaming_status"
            for utterance_id in ( "utt-A", "utt-B" ):
                reply = client.post( "/api/get-speech-elevenlabs", json={
                    "session_id"   : SESSION_ID,
                    "text"         : f"say {utterance_id}",
                    "voice_id"     : "V",
                    "utterance_id" : utterance_id,
                } )
                assert reply.status_code == 200, reply.text
                assert reply.json()[ "utterance_id" ] == utterance_id
            completes = 0
            while completes < 2:
                message = ws.receive()
                if message.get( "bytes" ) is not None:
                    frames.append( ( "bytes", message[ "bytes" ] ) )
                    continue
                frame = json.loads( message[ "text" ] )
                frames.append( ( "json", frame ) )
                assert frame[ "type" ] != "error", frame
                if frame[ "type" ] == "audio_streaming_complete":
                    completes += 1
                    gate.set()
    return frames


def _json_of( frames, frame_type ):
    return [ f for kind, f in frames if kind == "json" and f[ "type" ] == frame_type ]


@pytest.mark.timeout( 60 )
def test_each_completion_names_its_own_utterance_when_the_streams_overlap():
    frames = _run_two_overlapping_streams( [ _audio( b"B1" ), json.dumps( { "isFinal": True } ) ] )

    # Control: the streams really overlapped. A's first chunk left before B finished and
    # A's last chunk left after it, so B's whole stream sits inside A's.
    order      = [ f if kind == "bytes" else f[ "type" ] for kind, f in frames ]
    b_complete = order.index( "audio_streaming_complete" )
    assert order.index( b"A1" ) < b_complete < order.index( b"A2" ), order
    assert order.index( b"B1" ) < b_complete, order

    completes = _json_of( frames, "audio_streaming_complete" )
    assert [ c[ "utterance_id" ] for c in completes ] == [ "utt-B", "utt-A" ]

    # Every JSON frame of both streams is stamped, and both utterances appear.
    stream_frames = [ f for kind, f in frames if kind == "json" ]
    assert len( stream_frames ) == 6, stream_frames
    assert sorted( f[ "utterance_id" ] for f in stream_frames ) == [ "utt-A" ] * 3 + [ "utt-B" ] * 3


@pytest.mark.timeout( 60 )
def test_an_error_on_one_stream_names_that_stream_and_not_the_one_still_open():
    frames = _run_two_overlapping_streams( [ json.dumps( { "error": "quota_exceeded: none left" } ) ] )

    errors = _json_of( frames, "tts_error" )
    assert len( errors ) == 1, errors
    assert errors[ 0 ][ "utterance_id" ] == "utt-B"
    assert errors[ 0 ][ "error_code" ] == "quota_exceeded"

    # A was open when B's error arrived, and A still finished with its own id and audio.
    order = [ f if kind == "bytes" else f[ "type" ] for kind, f in frames ]
    assert order.index( b"A1" ) < order.index( "tts_error" ) < order.index( b"A2" ), order
    completes = _json_of( frames, "audio_streaming_complete" )
    assert [ c[ "utterance_id" ] for c in completes ] == [ "utt-B", "utt-A" ]
