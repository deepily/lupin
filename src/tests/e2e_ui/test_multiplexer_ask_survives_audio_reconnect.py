"""
E2E UI — a REAL ask reaches the multiplexer before AND after its audio socket
reconnects (row d2b1b59a, FINDING 5).

WHAT BROKE, measured 2026-09-10 on :7999: the multiplexer opened /ws/queue and
/ws/audio under ONE session id. The server keeps one socket + one subscription
list per id, so every audio (re)registration overwrote the queue socket's
subscriptions and the server declined every notification to the tab —
"declined=2 (slow zebra, calm dolphin)". Rick's P0 petition asks and every
ordinary ask never reached it. Fix 7221b484: the audio socket gets its own id.
Write-up: src/rnd/2026.09.10-multiplexer-misses-petition-ask.md

WHY THE RECONNECT: the defect was a RACE decided by which socket registered
last, so a single cold load could pass by luck of ordering. An audio reconnect
re-runs the audio connect + audio auth AFTER the queue socket is settled — the
exact order that deafened the tab — so the "after" ask is the discriminating arm.

REAL WIRE PATH, nothing injected: the ask is a response-required POST
/api/notify to the logged-in user; the server pushes notification_queue_update
over the queue socket; ActionRequiredStore takes it; the renderer paints
[data-testid="multiplexer-action-required"][data-id-hash=<id>]. The audio
socket is closed from the page with a non-permanent code (3001), so the
transport's normal socket_close → backoff → reconnect path reopens it.

EXPECTED AGAINST THE PRE-FIX BUNDLE (inferred from the measured mechanism, not
run on :8000): the after-reconnect ask never reaches the store, and the
session-id assertion fails because both sockets carry one id.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). It
registers a user and persists notifications, so it is not :7999-eligible.

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_multiplexer_ask_survives_audio_reconnect",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import unquote, urlparse

import requests

from .conftest import BASE_URL


E2E_SENDER = "claude.code@lupin.deepily.ai#e2eaudio"

# Wraps window.WebSocket BEFORE boot so the test can see every socket the
# multiplexer opens, when each authenticated, and close one on demand.
# ws-channel resolves globalThis.WebSocket at construction, so the wrapper is
# what it instantiates. The prototype and ready-state constants are preserved.
TRACK_SOCKETS = """
(() => {
  const Native  = window.WebSocket;
  const tracked = [];
  function TrackedWebSocket( url, protocols ) {
    const ws  = protocols === undefined ? new Native( url ) : new Native( url, protocols );
    const rec = { url: String( url ), ws, authed: false };
    ws.addEventListener( "message", ( e ) => {
      if ( typeof e.data === "string" && e.data.includes( '"auth_success"' ) ) rec.authed = true;
    } );
    tracked.push( rec );
    return ws;
  }
  TrackedWebSocket.prototype = Native.prototype;
  Object.assign( TrackedWebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 } );
  window.WebSocket     = TrackedWebSocket;
  window.__e2eSockets  = tracked;
})();
"""


def _open_multiplexer( page ):
    page.context.add_init_script( TRACK_SOCKETS )
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.actionRequired",
        timeout=15000,
    )


def _wait_authed_sockets( page, kind, count ):
    """Wait until at least `count` sockets on /ws/<kind>/ are OPEN and have received auth_success."""
    page.wait_for_function(
        """( [ kind, count ] ) => ( window.__e2eSockets || [] ).filter( r =>
              r.url.includes( `/ws/${ kind }/` ) && r.authed && r.ws.readyState === 1
           ).length >= count""",
        arg=[ kind, count ],
        timeout=20000,
    )


def _live_session_ids( page ):
    """The session id of the newest OPEN socket per channel, decoded from its URL."""
    urls = page.evaluate(
        """() => {
            const newest = ( kind ) => ( window.__e2eSockets || [] )
                .filter( r => r.url.includes( `/ws/${ kind }/` ) && r.ws.readyState === 1 )
                .map( r => r.url ).pop() || null;
            return { queue: newest( "queue" ), audio: newest( "audio" ) };
        }"""
    )
    return { kind: ( unquote( urlparse( url ).path.rsplit( "/", 1 )[ -1 ] ) if url else None )
             for kind, url in urls.items() }


def _close_audio_socket( page ):
    closed = page.evaluate(
        """() => {
            const open = ( window.__e2eSockets || [] ).filter( r => r.url.includes( "/ws/audio/" ) && r.ws.readyState === 1 );
            open.forEach( r => r.ws.close( 3001, "e2e: force audio reconnect" ) );
            return open.length;
        }"""
    )
    assert closed == 1, f"expected exactly one open audio socket to close, found { closed }"


def _raise_ask( page, email, label ):
    """
    POST a real response-required yes/no ask to the logged-in user.

    Returns (streaming response, notification_id). The response stays open
    until the caller closes it; closing it walks away without answering.
    """
    token = page.evaluate( "() => localStorage.getItem( 'lupin_access_token' )" )
    resp  = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"            : f"[E2E-AUDIO-RECONNECT] { label } { uuid.uuid4().hex[ :8 ] }",
            "type"               : "custom",
            "priority"           : "high",
            "target_user"        : email,
            "response_requested" : "true",
            "response_type"      : "yes_no",
            "timeout_seconds"    : 120,
            "sender_id"          : E2E_SENDER,
            "suppress_ding"      : "true",
        },
        headers = { "Authorization": f"Bearer { token }" },
        stream  = True,
        timeout = 20,
    )
    assert resp.status_code == 200, f"notify POST failed: { resp.status_code } { resp.text[ :300 ] }"
    for line in resp.iter_lines( decode_unicode=True ):
        if line and line.startswith( "data:" ):
            frame = json.loads( line[ len( "data:" ): ].strip() )
            assert frame.get( "status" ) == "ack", f"first SSE frame was not the ack: { frame }"
            return resp, frame[ "notification_id" ]
    raise AssertionError( "SSE stream ended before the ack frame" )


def _wait_ask_rendered( page, notification_id ):
    page.wait_for_function(
        "( nid ) => window.__multiplexerTestHook.stores.actionRequired.getById( nid ) !== undefined",
        arg=notification_id,
        timeout=15000,
    )
    page.wait_for_selector(
        f'[data-testid="multiplexer-action-required"][data-id-hash="{ notification_id }"]',
        state="attached",
        timeout=5000,
    )


class TestMultiplexerAskSurvivesAudioReconnect:

    def test_sockets_use_different_ids_and_an_ask_arrives( self, logged_in_page, test_user_credentials ):
        page = logged_in_page
        _open_multiplexer( page )
        _wait_authed_sockets( page, "queue", 1 )
        _wait_authed_sockets( page, "audio", 1 )

        ids = _live_session_ids( page )
        assert ids[ "queue" ] and ids[ "audio" ], f"both sockets must be open: { ids }"
        assert ids[ "queue" ] != ids[ "audio" ], f"queue and audio sockets share a session id: { ids }"

        resp, nid = _raise_ask( page, test_user_credentials[ "email" ], "before reconnect" )
        try:
            _wait_ask_rendered( page, nid )
        finally:
            resp.close()

    def test_an_ask_still_arrives_after_the_audio_socket_reconnects( self, logged_in_page, test_user_credentials ):
        page  = logged_in_page
        email = test_user_credentials[ "email" ]
        _open_multiplexer( page )
        _wait_authed_sockets( page, "queue", 1 )
        _wait_authed_sockets( page, "audio", 1 )

        before, before_id = _raise_ask( page, email, "before reconnect" )
        try:
            _wait_ask_rendered( page, before_id )
        finally:
            before.close()

        _close_audio_socket( page )
        # A NEW audio socket must open and authenticate: two authed audio
        # records in total, the newest of them OPEN.
        page.wait_for_function(
            """() => ( window.__e2eSockets || [] ).filter( r => r.url.includes( "/ws/audio/" ) && r.authed ).length >= 2
                  && ( window.__e2eSockets || [] ).some( r => r.url.includes( "/ws/audio/" ) && r.authed && r.ws.readyState === 1 )""",
            timeout=20000,
        )

        ids = _live_session_ids( page )
        assert ids[ "queue" ] != ids[ "audio" ], f"after reconnect the sockets share a session id: { ids }"

        after, after_id = _raise_ask( page, email, "after audio reconnect" )
        try:
            _wait_ask_rendered( page, after_id )
        finally:
            after.close()
