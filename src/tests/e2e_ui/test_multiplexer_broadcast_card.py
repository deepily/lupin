#!/usr/bin/env python3
"""
E2E — Multiplexer Lane C: broadcast-to-all-CC compose card (focus-bar parity v0.1.9).

Exercises the BroadcastCardRenderer + BroadcastStore + ApiClient.broadcastToCcSessions()
end-to-end in a real browser. The card mounts at #broadcast-card-mount and is the
multiplexer port of the legacy `notifications.html:692-726` + `broadcast-panel.js`
control (collapsible compose card + 🎤 STT + live recipient chips + ↻ refresh +
confirm modal + Send → POST /api/commons/broadcast-to-cc-sessions + status line).

Two render dependencies are STUBBED via `page.route` (no real state mutation):
  - GET  /api/commons/active-sessions       → recipient chip-row (BroadcastStore.hydrate)
  - POST /api/commons/broadcast-to-cc-sessions → send → status line
The stub bodies use the REAL server response shapes (commons.py
`project_session_response` + `execute_broadcast`) so the intercept can't
false-pass against a shape the renderer doesn't actually consume. The basic
mount test runs WITHOUT a stub against the live endpoint, asserting the
robust "chips OR no-active-sessions pill" disjunction.

Harness lessons baked in (Lane A, Tester 2026-06-24):
  1. REAL mux selectors — the card mounts at #broadcast-card-mount; there is no
     legacy #broadcast-submit-section accordion wrapper from notifications.html.
  2. (n/a here — this card hydrates from REST, not synthetic notification emits;
     no id_hash concern. The store has no eventBus path, so recipients are
     driven via the active-sessions route stub, not the test-hook EventBus.)

Venue: :8000 (monopolize, scheduled via /api/test-suite/submit) — the
`test_multiplexer_*` E2E batch. Per CLAUDE.local.md "THE USER IS NEVER A
TESTER": every assertion is AI-run; the Tester owns scheduling this on :8000.
Authored by Lane C (Krishna 🦚); RUN by the Tester — do NOT side-door :8000.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_broadcast_card.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_broadcast_card.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

# GET /api/commons/active-sessions (no query) — `*` covers any trailing query.
ACTIVE_SESSIONS_ROUTE = "**/api/commons/active-sessions*"
# POST /api/commons/broadcast-to-cc-sessions
BROADCAST_ROUTE       = "**/api/commons/broadcast-to-cc-sessions"

# Recipient projection — the subset of commons.py `project_session_response`
# the chip-row consumes (session_id / persona_name / persona_icon / persona_color).
_TWO_RECIPIENTS = {
    "sessions": [
        { "session_id": "bcce2e01", "persona_name": "Tiberius", "persona_icon": "👑",
          "persona_color": "#3F51B5", "last_seen_iso": "2026-06-24T18:00:00Z", "speakerphone_on": False },
        { "session_id": "bcce2e02", "persona_name": "Rachel", "persona_icon": "🕊️",
          "persona_color": "#1DE9B6", "last_seen_iso": "2026-06-24T18:00:01Z", "speakerphone_on": False },
    ],
}

# POST /broadcast-to-cc-sessions 200 body — commons.py `execute_broadcast` shape.
_BROADCAST_RESULT = {
    "broadcast_id"      : "abcdef12-3456-4789-abcd-ef0123456789",
    "recipients"        : 2,
    "failed_recipients" : [],
    "filtered_out"      : [ { "session_id": "deadbeefcafef00d", "reason": "stale_bridge_mtime" } ],
    "status"            : "queued",
}


# ---------------------------------------------------------------------------
# Auth + test-hook helpers
# ---------------------------------------------------------------------------

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


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


def _fulfill_json( body: dict ):
    def _handler( route ):
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
    return _handler


def _open( page, *, sessions_body: dict | None = None, broadcast_body: dict | None = None ):
    """Seed auth, optionally stub the two endpoints, navigate, wait for the boot hook."""
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )
    if sessions_body is not None:
        page.route( ACTIVE_SESSIONS_ROUTE, _fulfill_json( sessions_body ) )
    if broadcast_body is not None:
        page.route( BROADCAST_ROUTE, _fulfill_json( broadcast_body ) )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )


# Recipient chip-row settles when EITHER a real recipient chip (a button with a
# data-token that is not the @all injector) OR the no-recipients/error pill is
# present — i.e. the async hydrate has resolved past the "loading…" state.
_ROW_SETTLED_JS = """
() => {
    const row = document.querySelector( '#broadcast-recipients-row' );
    if ( !row ) return false;
    const realChip = row.querySelector( "button.broadcast-chip[data-token]:not([data-token='all'])" );
    const pill     = row.querySelector( '.broadcast-chip.no-recipients' );
    return realChip !== null || pill !== null;
}
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_card_mounts_with_stt_and_send_disabled_live_endpoint( page ):
    """
    Ensures (against the LIVE active-sessions endpoint, no stub):
        - The compose card mounts at #broadcast-card-mount.
        - The 🎤 STT mic button renders.
        - The recipient row settles to EITHER ≥1 chip OR the no-active-sessions
          pill (robust to whatever :8000 actually has active).
        - The Send button is DISABLED with an empty textarea.
    """
    _open( page )

    card = page.query_selector( '#broadcast-card-mount [data-testid="multiplexer-broadcast-card"]' )
    assert card is not None, "broadcast compose card must mount at #broadcast-card-mount"

    assert page.query_selector( "#broadcast-stt-button" ) is not None, "🎤 STT mic button must render"

    page.wait_for_function( _ROW_SETTLED_JS, timeout=5_000 )
    settled = page.evaluate(
        """() => {
            const row = document.querySelector( '#broadcast-recipients-row' );
            return {
                has_recipient_chip : row.querySelector( "button.broadcast-chip[data-token]:not([data-token='all'])" ) !== null,
                has_no_recip_pill  : row.querySelector( '.broadcast-chip.no-recipients' ) !== null,
            };
        }"""
    )
    assert settled[ "has_recipient_chip" ] or settled[ "has_no_recip_pill" ], \
        "recipient row must show chips OR the no-active-sessions pill"

    send = page.query_selector( "#broadcast-send-button" )
    assert send is not None
    assert send.is_disabled(), "Send must be disabled with an empty textarea"


def test_send_enables_only_with_body_and_recipients( page ):
    """
    Ensures (stubbed 2-recipient list):
        - Send starts disabled (empty body), enables once a non-empty message is
          typed, and disables again when the body is cleared.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    send = page.query_selector( "#broadcast-send-button" )
    assert send.is_disabled(), "disabled with empty body even though recipients exist"

    page.fill( "#broadcast-textarea", "hello fleet" )
    assert not send.is_disabled(), "enabled with body + recipients"

    page.fill( "#broadcast-textarea", "" )
    assert send.is_disabled(), "disabled again when the body is cleared"


def test_confirm_modal_opens_and_status_reflects_recipients( page ):
    """
    Ensures (stubbed 2 recipients + stubbed broadcast POST):
        - Clicking Send (with body + recipients) opens the confirm modal with the
          message preview.
        - Confirm + Send posts the broadcast, clears the textarea, and the status
          line reflects the recipient count + the filtered_out receipt.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS, broadcast_body=_BROADCAST_RESULT )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    page.fill( "#broadcast-textarea", "ship the parity build" )
    page.click( "#broadcast-send-button" )

    overlay = page.wait_for_selector( "#broadcast-confirm-modal-overlay", timeout=3_000 )
    assert overlay is not None, "confirm modal must open on Send"
    preview = page.text_content( "#broadcast-confirm-modal .modal-preview" )
    assert "ship the parity build" in ( preview or "" ), "modal preview shows the message"

    page.click( '[data-testid="multiplexer-broadcast-confirm-btn"]' )

    # Status line updates after the POST resolves; modal closes; textarea clears.
    page.wait_for_function(
        """() => {
            const s = document.querySelector( '#broadcast-submit-status' );
            return s && s.textContent && s.textContent.indexOf( 'sent to' ) !== -1;
        }""",
        timeout=5_000,
    )
    status = page.text_content( "#broadcast-submit-status" ) or ""
    assert "sent to 2 sessions" in status, f"status must reflect the recipient count: { status }"
    assert "filtered out" in status, f"status must surface filtered_out receipts: { status }"

    assert page.query_selector( "#broadcast-confirm-modal-overlay" ) is None, "modal closes after a successful send"
    assert ( page.input_value( "#broadcast-textarea" ) or "" ) == "", "textarea clears after send"
