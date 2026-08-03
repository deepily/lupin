#!/usr/bin/env python3
"""
E2E — Multiplexer F5 lane: inline voice-input row (MATCH-LEGACY rebuild).

Exercises the rebuilt inline `.cc-voice-input-row` (conv-mode + mic + text input
+ send) that senderCard.ts now renders STATICALLY between the card header and
`.sender-card-dates`, with SenderCardRecorderRenderer as the behavior layer. The
full recorder pipeline runs in a real browser — SenderCardRecorderRenderer →
recordingManager → AudioRecorder — with fakes ONLY at the two boundaries a
headless browser cannot cross: `navigator.mediaDevices.getUserMedia` +
`MediaRecorder` (injected via add_init_script) and the STT upload endpoint
`/api/upload-and-transcribe-mp3` (route stub). Everything in between, including
the F5 stash→splice→caret-restore path on the persistent `.cc-session-msg-input`,
is production code.

Covers (both acceptance-gate functional items + Tiberius's round-trip ask):
  - the inline row renders with all four legacy controls;
  - mic record → first-fill, re-record caret-splice (legacy `_insertTranscription
    Text` contract, 2026-06-01 Rick), highlighted-range replace;
  - send POSTs a user_initiated_message to /api/notify with the legacy wire shape;
  - the conv-mode toggle POSTs the legacy-verbatim /api/cosa-voice/speakerphone
    body {on: next} AND the conversation_mode_changed round-trip flips is-active.

Pre-deploy override: set LUPIN_WP6_BUNDLE_PATH to a locally-built
`dist/multiplexer/boot.js` to run this suite BEFORE the served bundle carries the
rebuild (the route swaps the bundle for this page only). Unset, the suite tests
the bundle the server actually serves.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_stt_insert_at_cursor.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_stt_insert_at_cursor.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

STT_ROUTE          = "**/api/upload-and-transcribe-mp3"
BUNDLE_ROUTE       = "**/static/dist/multiplexer/boot.js"
MANIFEST_ROUTE     = "**/static/dist/multiplexer/manifest.json"
NOTIFY_ROUTE       = "**/api/notify**"
SPEAKERPHONE_ROUTE = "**/api/cosa-voice/speakerphone/**"

SENDER_ID    = "wp6.stt@e2e.ai#wp6hash01"
SESSION_HASH = "wp6hash01"

# Browser-hardware boundary fakes. getUserMedia returns a track-bearing stub;
# FakeMediaRecorder emits ONE non-empty chunk then the stop event (the real
# AudioRecorder errors on an empty blob, so the chunk must have bytes).
_FAKE_MEDIA_INIT_JS = """
() => {
    if ( !navigator.mediaDevices ) {
        Object.defineProperty( navigator, 'mediaDevices', { value: {}, configurable: true } );
    }
    navigator.mediaDevices.getUserMedia = async () => ({
        getTracks : () => [ { stop : () => {} } ],
    });
    class FakeMediaRecorder {
        static isTypeSupported() { return true; }
        constructor( _stream, opts ) {
            this.state    = 'inactive';
            this.mimeType = ( opts && opts.mimeType ) || 'audio/mp4';
            this._l       = {};
        }
        addEventListener( type, cb ) { ( this._l[ type ] = this._l[ type ] || [] ).push( cb ); }
        start() { this.state = 'recording'; }
        stop() {
            this.state = 'inactive';
            const data = new Blob( [ 'fake-audio-bytes' ], { type: this.mimeType } );
            ( this._l[ 'dataavailable' ] || [] ).forEach( cb => cb( { data } ) );
            ( this._l[ 'stop' ] || [] ).forEach( cb => cb( {} ) );
        }
    }
    window.MediaRecorder = FakeMediaRecorder;
}
"""

_EMIT_MESSAGE_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'n-' + args.sender_id,
            message   : args.message,
            sender_id : args.sender_id,
            timestamp : args.ts,
            type      : 'task',
        } },
        source : 'e2e-f5-row',
        ts     : Date.now(),
    });
    return true;
}
"""

# Drive the SAME conversation_mode_changed envelope the server broadcasts after
# the speakerphone POST — the store consumes payload.active (SenderStore
# handleConversationModeUpdate) → store_senders_changed → card re-render →
# senderCard.ts renders is-active.
_EMIT_CONV_MODE_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            sender_id : args.sender_id,
            timestamp : args.ts,
            type      : 'conversation_mode_changed',
            payload   : { active: args.active },
        } },
        source : 'e2e-f5-convmode',
        ts     : Date.now(),
    });
    return true;
}
"""


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _open( page ):
    """Seed auth + media fakes + STT stub (mutable transcription), navigate,
    emit one sender card so a CC `.cc-voice-input` row exists.

    Returns a state dict; tests mutate state["transcription"] between takes.
    """
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )
    page.add_init_script( f"({ _FAKE_MEDIA_INIT_JS })()" )

    state = { "transcription": "" }

    def _stt_handler( route ):
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "transcription": state[ "transcription" ] } ) )
    page.route( STT_ROUTE, _stt_handler )

    bundle_override = os.environ.get( "LUPIN_WP6_BUNDLE_PATH" )
    if bundle_override:
        # multiplexer.html resolves the bundle through a manifest-driven
        # cache-bust (imports the content-hashed boot.<hash>.js). Pin the
        # manifest to the STABLE name so the import resolves to
        # /static/dist/multiplexer/boot.js, which the next route swaps for the
        # locally-built bundle under test.
        page.route( MANIFEST_ROUTE, lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps( { "boot.js": "boot.js" } ) ) )
        page.route( BUNDLE_ROUTE, lambda route: route.fulfill(
            status=200, content_type="text/javascript", path=bundle_override ) )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_ID, "message": "hello", "ts": "2026-06-11T18:00:00.000Z" } )
    page.wait_for_selector( f'.cc-voice-input[data-session-hash="{SESSION_HASH}"] .cc-session-stt', timeout=5_000 )
    return state


def _row( page ):
    return page.locator( f'.cc-voice-input[data-session-hash="{SESSION_HASH}"]' )


def _record_take( page, state, transcription: str ):
    """Drive one record→stop cycle through the REAL pipeline; the stubbed STT
    endpoint returns `transcription`. Mic is the record/stop toggle; the row
    returns to data-recorder-state="idle" once the transcription lands."""
    state[ "transcription" ] = transcription
    _row( page ).locator( ".cc-session-stt" ).click()   # record
    page.wait_for_selector(
        f'.cc-voice-input[data-session-hash="{SESSION_HASH}"][data-recorder-state="recording"]',
        timeout=3_000,
    )
    _row( page ).locator( ".cc-session-stt" ).click()   # stop → onComplete → idle
    page.wait_for_selector(
        f'.cc-voice-input[data-session-hash="{SESSION_HASH}"][data-recorder-state="idle"]',
        timeout=5_000,
    )


def _input_state( page ) -> dict:
    return page.evaluate(
        """( hash ) => {
            const el = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-session-msg-input` );
            if ( !el ) return null;
            return { value: el.value, selStart: el.selectionStart, selEnd: el.selectionEnd };
        }""",
        SESSION_HASH,
    )


def test_voice_input_row_renders_with_all_controls( page ):
    """
    Ensures:
        - The CC card renders the inline `.cc-voice-input-row` with the four
          legacy controls (conv-mode toggle + mic + text input + send)
    """
    _open( page )
    row = _row( page )
    assert row.locator( ".cc-voice-input-row" ).count() == 1
    assert row.locator( ".sender-conversation-mode-btn" ).count() == 1
    assert row.locator( ".stt-button.cc-session-stt" ).count() == 1
    assert row.locator( "input.cc-session-msg-input" ).count() == 1
    assert row.locator( ".response-submit-button.cc-session-send" ).count() == 1


def test_first_record_fills_the_input( page ):
    """
    Ensures:
        - The first record fills the persistent input with exactly the
          transcription (caret-splice into an empty field == plain fill)
    """
    state = _open( page )
    _record_take( page, state, "first take" )

    st = _input_state( page )
    assert st is not None
    assert st[ "value" ] == "first take"


def test_rerecord_splices_at_caret_preserving_edits( page ):
    """
    Ensures:
        - After the user edits the transcription and parks the caret, a
          Re-record's new transcription is spliced AT THE CARET — user edits
          preserved on both sides, caret restored after the inserted text
    """
    state = _open( page )
    _record_take( page, state, "first take" )

    page.evaluate(
        """( hash ) => {
            const el = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-session-msg-input` );
            el.value = 'edited first take';
            el.focus();
            el.setSelectionRange( 7, 7 );
        }""",
        SESSION_HASH,
    )

    _record_take( page, state, "NEW " )

    st = _input_state( page )
    assert st[ "value" ] == "edited NEW first take", \
        "Re-record must caret-splice, never clobber the user's edits"
    assert st[ "selStart" ] == 7 + len( "NEW " ), "caret lands after the inserted text"


def test_rerecord_replaces_only_highlighted_range( page ):
    """
    Ensures:
        - With a range selected, the Re-record transcription replaces ONLY
          that range (the legacy F5 selection contract)
    """
    state = _open( page )
    _record_take( page, state, "Hello cruel world" )

    page.evaluate(
        """( hash ) => {
            const el = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-session-msg-input` );
            el.focus();
            el.setSelectionRange( 6, 11 );   // select "cruel"
        }""",
        SESSION_HASH,
    )

    _record_take( page, state, "brave" )

    st = _input_state( page )
    assert st[ "value" ] == "Hello brave world"
    assert st[ "selStart" ] == 6 + len( "brave" )


def test_send_posts_user_initiated_message( page ):
    """
    Ensures:
        - Clicking send POSTs the input text to /api/notify with the legacy
          wire shape (type=user_initiated_message, message, target_user, job_id)
    """
    state = _open( page )

    captured: dict = {}

    def _notify_handler( route ):
        req = route.request
        captured[ "url" ]    = req.url
        captured[ "method" ] = req.method
        route.fulfill( status=200, content_type="application/json", body="{}" )
    page.route( NOTIFY_ROUTE, _notify_handler )

    _record_take( page, state, "ship it" )
    _row( page ).locator( ".cc-session-send" ).click()
    page.wait_for_function( "() => true", timeout=2_000 )  # let the click's async POST flush

    assert captured.get( "method" ) == "POST", f"expected a POST to /api/notify; got { captured }"
    url = captured[ "url" ]
    assert "type=user_initiated_message" in url
    assert "ship+it" in url or "ship%20it" in url, f"message not in query: { url }"
    assert f"job_id={ SESSION_HASH }" in url
    assert "target_user=wp6.stt%40e2e.ai" in url or "target_user=wp6.stt@e2e.ai" in url


def test_conv_mode_toggle_posts_speakerphone_and_roundtrips_is_active( page ):
    """
    Ensures:
        - The conv-mode toggle POSTs the legacy-verbatim
          /api/cosa-voice/speakerphone/<hash> body {on: true} (initial state
          off → next on), AND the conversation_mode_changed round-trip flips
          the button to is-active (byte-identical to legacy toggleConversationMode)
    """
    _open( page )

    captured: dict = {}

    def _sp_handler( route ):
        req = route.request
        captured[ "url" ]      = req.url
        captured[ "method" ]   = req.method
        captured[ "postData" ] = req.post_data
        route.fulfill( status=200, content_type="application/json", body="{}" )
    page.route( SPEAKERPHONE_ROUTE, _sp_handler )

    btn = _row( page ).locator( ".sender-conversation-mode-btn" )
    # Initially off (conversation_mode_active defaults false).
    assert "is-active" not in ( btn.get_attribute( "class" ) or "" )

    btn.click()
    page.wait_for_function( "() => true", timeout=2_000 )

    assert captured.get( "method" ) == "POST", f"expected a POST to /speakerphone; got { captured }"
    assert f"/api/cosa-voice/speakerphone/{ SESSION_HASH }" in captured[ "url" ]
    assert json.loads( captured[ "postData" ] ) == { "on": True }, \
        "legacy-verbatim body {on: next}; initial off → next on"

    # Server round-trip: broadcast conversation_mode_changed(active=true) → store
    # → card re-render → is-active.
    page.evaluate( _EMIT_CONV_MODE_JS, { "sender_id": SENDER_ID, "active": True, "ts": "2026-06-11T18:01:00.000Z" } )
    page.wait_for_selector(
        f'.cc-voice-input[data-session-hash="{SESSION_HASH}"] .sender-conversation-mode-btn.is-active',
        timeout=5_000,
    )
