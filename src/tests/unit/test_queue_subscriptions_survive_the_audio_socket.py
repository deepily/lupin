#!/usr/bin/env python3
"""
Unit — a browser's queue-socket subscriptions survive its audio socket connecting
(row d2b1b59a, FINDING 5).

WHAT BROKE, measured 2026-09-10: the multiplexer opened /ws/queue and /ws/audio
under ONE session id. WebSocketManager keeps ONE socket and ONE subscription list
per id (`active_connections`, `session_subscriptions`), so the audio socket's
registration overwrote the queue's. Every notification to the tab — the P0
petition asks and every ordinary ask — was declined "not subscribed". Legacy
notifications.js already uses two ids. Write-up:
src/rnd/2026.09.10-multiplexer-misses-petition-ask.md

The client fix gives the audio socket its own id. These tests pin the server
behaviour that fix relies on, and a CONTROL pins why sharing an id is deaf — if the
server ever learns to hold two sockets per id, the control reddens and says so.

Event lists are LITERALS mirrored from the multiplexer transports
(QueueTransport.ts / AudioTransport.ts), the same lists
src/tests/websocket_smoke/test_multiplexer_transport.py mirrors.

Venue: :7999 (pure unit — WebSocketManager built via __new__, no config/server).
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.websocket_manager import WebSocketManager


QUEUE_EVENTS = [
    "job_state_transition", "job_removed", "tts_job_request", "sys_time_update",
    "notification_play_sound", "notification_queue_update", "notification_responded",
    "notification_expired", "auth_success", "auth_error", "connect", "sys_ping",
]
# The router's audio connect registers exactly this list (routers/websocket.py
# `audio_events`); the multiplexer's audio auth_request then rewrites the same id.
AUDIO_CONNECT_EVENTS = [ "audio_streaming_status", "audio_streaming_complete", "sys_ping" ]

USER     = "user-rick"
QUEUE_ID = "calm dolphin"
AUDIO_ID = "wise owl"
PROMOTION_ASK = {
    "notification" : {
        "id_hash"            : "bb290a48",
        "response_requested" : True,
        "response_type"      : "yes_no",
        "human_only"         : True,
    }
}


def _manager():
    """WebSocketManager without the config-heavy __init__ (existing test convention)."""
    mgr = WebSocketManager.__new__( WebSocketManager )
    mgr.active_connections      = {}
    mgr.session_to_user         = {}
    mgr.user_sessions           = {}
    mgr.user_to_email           = {}
    mgr.session_is_admin        = {}
    mgr.session_client_types    = {}
    mgr.session_timestamps      = {}
    mgr.session_subscriptions   = {}
    mgr.main_loop               = None
    mgr.single_session_per_user = False
    mgr.debug                   = False
    mgr.available_events        = set( QUEUE_EVENTS ) | set( AUDIO_CONNECT_EVENTS )
    return mgr


def _socket():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _emit_ask( mgr ):
    return asyncio.run( mgr.emit_to_user( USER, "notification_queue_update", PROMOTION_ASK ) )


def _received( ws ):
    return [ c.args[ 0 ][ "type" ] for c in ws.send_json.await_args_list ]


class TestSeparateIds:

    def test_queue_socket_gets_the_ask_when_audio_connects_after_it( self ):
        # The order that went deaf on 2026-09-10 21:30:23Z: queue auth, then audio.
        mgr, queue_ws, audio_ws = _manager(), _socket(), _socket()
        mgr.connect( queue_ws, QUEUE_ID, USER, QUEUE_EVENTS )
        mgr.connect( audio_ws, AUDIO_ID, USER, AUDIO_CONNECT_EVENTS )

        _emit_ask( mgr )

        assert _received( queue_ws ) == [ "notification_queue_update" ]
        assert _received( audio_ws ) == []

    def test_queue_socket_gets_the_ask_when_audio_connects_before_it( self ):
        mgr, queue_ws, audio_ws = _manager(), _socket(), _socket()
        mgr.connect( audio_ws, AUDIO_ID, USER, AUDIO_CONNECT_EVENTS )
        mgr.connect( queue_ws, QUEUE_ID, USER, QUEUE_EVENTS )

        _emit_ask( mgr )

        assert _received( queue_ws ) == [ "notification_queue_update" ]

    def test_the_audio_auth_rewrite_touches_only_its_own_id( self ):
        # routers/websocket.py's audio auth handler assigns
        # `session_subscriptions[ session_id ] = valid_events` AFTER connect — the
        # write that re-deafened the tab even when the queue auth landed second.
        mgr, queue_ws, audio_ws = _manager(), _socket(), _socket()
        mgr.connect( queue_ws, QUEUE_ID, USER, QUEUE_EVENTS )
        mgr.connect( audio_ws, AUDIO_ID, USER, AUDIO_CONNECT_EVENTS )
        mgr.session_subscriptions[ AUDIO_ID ] = AUDIO_CONNECT_EVENTS

        _emit_ask( mgr )

        assert mgr.session_subscriptions[ QUEUE_ID ] == QUEUE_EVENTS
        assert _received( queue_ws ) == [ "notification_queue_update" ]


class TestSharedIdControl:

    def test_CONTROL_a_shared_id_is_deaf_to_the_ask( self ):
        # Today's defect, reproduced on demand. If this ever reddens, the server
        # holds two sockets per id and the client-side split is no longer required.
        mgr, queue_ws, audio_ws = _manager(), _socket(), _socket()
        mgr.connect( queue_ws, QUEUE_ID, USER, QUEUE_EVENTS )
        mgr.connect( audio_ws, QUEUE_ID, USER, AUDIO_CONNECT_EVENTS )

        _emit_ask( mgr )

        assert mgr.active_connections[ QUEUE_ID ] is audio_ws
        assert mgr.session_subscriptions[ QUEUE_ID ] == AUDIO_CONNECT_EVENTS
        assert _received( queue_ws ) == []
        assert _received( audio_ws ) == []
