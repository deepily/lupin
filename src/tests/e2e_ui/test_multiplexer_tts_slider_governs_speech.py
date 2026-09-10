"""
E2E UI — the TTS preview slider governs what the multiplexer SPEAKS (row c256fb66,
P0 from Rick's broadcast a090b845).

WHAT BROKE, reported by Rick 2026-09-10 ~18:07 EDT: with the slider at 0% the legacy
page spoke nothing, while the multiplexer spoke every high-priority notification in
full. Measured cause: the slider persisted its fraction, but nothing on the speech
path (store_notification_tts_intent → TtsQueueStore → wireTtsPlayback) read it.
Fix d71e5525, merged 916cbe3d: wireNotificationTtsIntent reads the fraction at each
arrival, legacy key first, and a fraction of 0 enqueues nothing.

REAL WIRE PATH: the notification is a fire-and-forget high-priority POST /api/notify
to the logged-in user; the server pushes notification_queue_update over the queue
socket; NotificationStore emits store_notification_tts_intent. The fraction is set
the way the legacy page sets it — the raw localStorage key
notifications_tts_preview_fraction_runtime — before the multiplexer boots.

WHAT IS OBSERVED, and why each arm is not vacuous:
  • the intent is recorded off the page's own EventBus, so the "0" arm first proves
    the notification REACHED the speech path's input before asserting nothing left it;
  • TtsQueueStore.enqueue is wrapped (forwarding to the original) to log every item;
  • POST /api/get-speech-elevenlabs is intercepted with page.route and answered 200
    by the test. Every request the page makes to that URL passes through the route,
    so the log is complete — and no ElevenLabs call is made, so the run spends nothing.

The "1" arm is the positive control: the same harness, the same notification, and a
POST carrying the full text. Without it a broken route or a dead TTS wire would make
the "0" arm pass.

EXPECTED AGAINST THE PRE-FIX BUNDLE (inferred from the measured mechanism, not run):
the "0" arm enqueues one item and POSTs its text, so both of its absence assertions
fail; the "1" arm passes either way.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). It registers a
user and persists notifications, so it is not :7999-eligible.

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_multiplexer_tts_slider_governs_speech",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

import time
import uuid

import requests

from .conftest import BASE_URL


E2E_SENDER          = "claude.code@lupin.deepily.ai#e2eslider"
LEGACY_FRACTION_KEY = "notifications_tts_preview_fraction_runtime"
SPEECH_URL_GLOB     = "**/api/get-speech-elevenlabs*"

# How long the "0" arm waits AFTER the intent is seen before asserting absence. The
# enqueue is synchronous inside the intent handler and the playback POST is issued
# synchronously on the resulting store_tts_queue_changed, so 2 s is generous.
ABSENCE_SETTLE_MS = 2000

# Records every socket the multiplexer opens and when each authenticated (same
# wrapper as test_multiplexer_ask_survives_audio_reconnect.py).
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

# Installed once the test hook exists and BEFORE the notification is raised.
TTS_PROBE = """
() => {
  const hook  = window.__multiplexerTestHook;
  const queue = hook.stores.ttsQueue;
  const rec   = { intents: [], enqueued: [] };
  hook.eventBus.on( "store_notification_tts_intent", ( e ) => { rec.intents.push( e.payload.ttsText ); } );
  const original = queue.enqueue.bind( queue );
  queue.enqueue = ( item ) => { rec.enqueued.push( item.ttsText ); return original( item ); };
  window.__e2eTts = rec;
}
"""


def _set_fraction_before_boot( page, fraction ):
    """Write the legacy slider key into every document of this context before its scripts run."""
    page.context.add_init_script(
        f"try {{ window.localStorage.setItem( '{ LEGACY_FRACTION_KEY }', '{ fraction }' ); }} catch ( e ) {{}}"
    )


def _intercept_speech_posts( page ):
    """Answer every speech request in the test and return the list the bodies land in."""
    posts = []

    def handle( route, request ):
        posts.append( { "method": request.method, "body": request.post_data_json } )
        route.fulfill( status=200, content_type="application/json", body='{"status": "e2e-intercepted"}' )

    page.route( SPEECH_URL_GLOB, handle )
    return posts


def _open_multiplexer( page ):
    page.context.add_init_script( TRACK_SOCKETS )
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.ttsQueue",
        timeout=15000,
    )
    for kind in ( "queue", "audio" ):
        page.wait_for_function(
            """( kind ) => ( window.__e2eSockets || [] ).some( r =>
                  r.url.includes( `/ws/${ kind }/` ) && r.authed && r.ws.readyState === 1 )""",
            arg=kind,
            timeout=20000,
        )
    page.evaluate( TTS_PROBE )


def _raise_notification( page, email, marker ):
    """POST a real fire-and-forget high-priority notification to the logged-in user."""
    token = page.evaluate( "() => localStorage.getItem( 'lupin_access_token' )" )
    resp  = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"       : f"[E2E-TTS-SLIDER] { marker } the slider decides whether this is spoken",
            "type"          : "custom",
            "priority"      : "high",
            "target_user"   : email,
            "sender_id"     : E2E_SENDER,
            "suppress_ding" : "true",
        },
        headers = { "Authorization": f"Bearer { token }" },
        timeout = 20,
    )
    assert resp.status_code == 200, f"notify POST failed: { resp.status_code } { resp.text[ :300 ] }"
    body = resp.json()
    assert body.get( "status" ) == "queued", f"notification was not queued to a live connection: { body }"


def _wait_intent( page, marker ):
    page.wait_for_function(
        "( marker ) => window.__e2eTts.intents.some( t => t.includes( marker ) )",
        arg=marker,
        timeout=15000,
    )


def _tts_record( page ):
    return page.evaluate(
        """() => ( {
            intents  : window.__e2eTts.intents,
            enqueued : window.__e2eTts.enqueued,
            active   : window.__multiplexerTestHook.stores.ttsQueue.activeItem(),
            pending  : window.__multiplexerTestHook.stores.ttsQueue.itemQueueLength(),
        } )"""
    )


class TestMultiplexerTtsSliderGovernsSpeech:

    def test_slider_at_zero_speaks_nothing( self, logged_in_page, test_user_credentials ):
        page   = logged_in_page
        marker = uuid.uuid4().hex[ :8 ]
        _set_fraction_before_boot( page, "0" )
        posts  = _intercept_speech_posts( page )
        _open_multiplexer( page )

        _raise_notification( page, test_user_credentials[ "email" ], marker )
        _wait_intent( page, marker )
        page.wait_for_timeout( ABSENCE_SETTLE_MS )

        record = _tts_record( page )
        assert record[ "enqueued" ] == [], f"slider at 0 still enqueued speech: { record }"
        assert record[ "active" ] is None and record[ "pending" ] == 0, f"TtsQueueStore is not empty: { record }"
        assert posts == [], f"slider at 0 still requested speech from the server: { posts }"

    def test_slider_at_one_speaks_the_full_text( self, logged_in_page, test_user_credentials ):
        page   = logged_in_page
        marker = uuid.uuid4().hex[ :8 ]
        _set_fraction_before_boot( page, "1" )
        posts  = _intercept_speech_posts( page )
        _open_multiplexer( page )

        _raise_notification( page, test_user_credentials[ "email" ], marker )
        _wait_intent( page, marker )

        deadline = time.monotonic() + 15
        ours     = []
        while time.monotonic() < deadline:
            ours = [ p for p in posts if marker in ( p[ "body" ] or {} ).get( "text", "" ) ]
            if ours: break
            page.wait_for_timeout( 250 )

        record = _tts_record( page )
        intent = next( t for t in record[ "intents" ] if marker in t )
        assert record[ "enqueued" ].count( intent ) == 1, f"slider at 1 did not enqueue the full text once: { record }"
        assert len( ours ) == 1, f"expected exactly one speech POST for this notification, got { posts }"
        assert ours[ 0 ][ "method" ] == "POST", f"speech request was not a POST: { ours[ 0 ] }"
        assert ours[ 0 ][ "body" ][ "text" ] == intent, f"speech POST did not carry the full text: { ours[ 0 ] } vs { intent!r }"
