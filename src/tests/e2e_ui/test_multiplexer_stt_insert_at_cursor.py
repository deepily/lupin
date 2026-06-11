#!/usr/bin/env python3
"""
E2E — Multiplexer WP6: STT insert-at-caret on Re-record (F5).

Exercises the full recorder pipeline in a real browser — SenderCardRecorder-
Renderer → recordingManager → AudioRecorder — with fakes ONLY at the two
boundaries a headless browser cannot cross: `navigator.mediaDevices.
getUserMedia` + `MediaRecorder` (injected via add_init_script) and the STT
upload endpoint `/api/upload-and-transcribe-mp3` (route stub). Everything in
between, including the WP6 stash→splice→caret-restore path, is production code.

Contract under test (legacy `_insertTranscriptionText`, 2026-06-01 Rick):
a Re-record's transcription is INSERTED at the caret of the user's edited
text — replacing only a highlighted range — never clobbering the rest. The
first record stays plain-fill.

Pre-deploy override: set LUPIN_WP6_BUNDLE_PATH to a locally-built
`dist/multiplexer/boot.js` to run this suite BEFORE the served bundle carries
the WP6 code (the route swaps the bundle for this page only). Unset, the
suite tests the bundle the server actually serves — the normal mode.

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

STT_ROUTE    = "**/api/upload-and-transcribe-mp3"
BUNDLE_ROUTE = "**/static/dist/multiplexer/boot.js"

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
        source : 'e2e-wp6-stt',
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
    emit one sender card so a .cc-voice-input footer exists.

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
        page.route( BUNDLE_ROUTE, lambda route: route.fulfill(
            status=200, content_type="text/javascript", path=bundle_override ) )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_ID, "message": "hello", "ts": "2026-06-11T18:00:00.000Z" } )
    page.wait_for_selector( f'.cc-voice-input[data-session-hash="{SESSION_HASH}"] .record-button', timeout=5_000 )
    return state


def _footer( page ):
    return page.locator( f'.cc-voice-input[data-session-hash="{SESSION_HASH}"]' )


def _record_take( page, state, transcription: str ):
    """Drive one record→stop cycle through the REAL pipeline; the stubbed STT
    endpoint returns `transcription`."""
    state[ "transcription" ] = transcription
    _footer( page ).locator( ".record-button" ).click()   # Record / Re-record
    page.wait_for_selector(
        f'.cc-voice-input[data-session-hash="{SESSION_HASH}"][data-recorder-state="recording"]',
        timeout=3_000,
    )
    _footer( page ).locator( ".record-button" ).click()   # Stop
    page.wait_for_selector(
        f'.cc-voice-input[data-session-hash="{SESSION_HASH}"][data-recorder-state="ready_to_send"]',
        timeout=5_000,
    )


def _textarea_state( page ) -> dict:
    return page.evaluate(
        """( hash ) => {
            const ta = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-voice-input-textarea` );
            if ( !ta ) return null;
            return { value: ta.value, selStart: ta.selectionStart, selEnd: ta.selectionEnd };
        }""",
        SESSION_HASH,
    )


def test_first_record_plain_fills_textarea( page ):
    """
    Ensures:
        - The first record fills the fresh textarea with exactly the
          transcription (plain-fill path unchanged by WP6)
    """
    state = _open( page )
    _record_take( page, state, "first take" )

    ta = _textarea_state( page )
    assert ta is not None
    assert ta[ "value" ] == "first take"


def test_rerecord_splices_at_caret_preserving_edits( page ):
    """
    Ensures:
        - After the user edits the transcription and parks the caret, a
          Re-record's new transcription is spliced AT THE CARET — user edits
          preserved on both sides, caret restored after the inserted text
    """
    state = _open( page )
    _record_take( page, state, "first take" )

    # User edits, caret after "edited " (index 7).
    page.evaluate(
        """( hash ) => {
            const ta = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-voice-input-textarea` );
            ta.value = 'edited first take';
            ta.focus();
            ta.setSelectionRange( 7, 7 );
        }""",
        SESSION_HASH,
    )

    _record_take( page, state, "NEW " )

    ta = _textarea_state( page )
    assert ta[ "value" ] == "edited NEW first take", \
        "Re-record must caret-splice, never clobber the user's edits"
    assert ta[ "selStart" ] == 7 + len( "NEW " ), "caret lands after the inserted text"


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
            const ta = document.querySelector( `.cc-voice-input[data-session-hash="${hash}"] .cc-voice-input-textarea` );
            ta.focus();
            ta.setSelectionRange( 6, 11 );   // select "cruel"
        }""",
        SESSION_HASH,
    )

    _record_take( page, state, "brave" )

    ta = _textarea_state( page )
    assert ta[ "value" ] == "Hello brave world"
    assert ta[ "selStart" ] == 6 + len( "brave" )
