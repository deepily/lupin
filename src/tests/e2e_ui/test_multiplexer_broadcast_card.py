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


# ---------------------------------------------------------------------------
# Row 4f320c27 M1 — the ack tally, and the one case that needs a real browser.
#
# 🔴 EVERY OTHER ASSERTION ABOUT THE TALLY IS A UNIT TEST, AND DELIBERATELY SO. The
# fold rules, the legacy strings, the fallbacks, the timeout state and the wiring are
# all measured in broadcast_ack_tally_renderer.test.ts and broadcast_card_renderer.
# test.ts against the REAL stores. Repeating them here would be slower and no more
# true.
#
# What CANNOT be measured there is this: that the tally survives an actual page
# reload. A unit test simulates one by building a second renderer over the same
# storage — honest, but it is the simulation asserting itself. Only a real reload
# throws away the real JS heap, the real EventBus and the real AckStore, and leaves
# nothing but what genuinely reached localStorage.
#
# THE TWO HALVES ARE INDISTINGUISHABLE ANY OTHER WAY. A live-folded tally and a
# hydrated one render identical DOM. The reload is the ONLY thing that tells you
# which one you are looking at — which is why the server half of this row exists at
# all, and why this test is the one that would notice if it stopped working.
# ---------------------------------------------------------------------------

BROADCAST_ACKS_ROUTE = "**/api/notifications/broadcast-acks/*"

# GET /api/notifications/broadcast-acks/{id} — the S4 `_project_broadcast_ack` shape.
# `ack_status`, not `status`: the server lifts the payload's status onto the envelope
# under a name that does not collide with the row's own delivery `state`.
_SAVED_ACKS = {
    "acks": [
        { "broadcast_id": _BROADCAST_RESULT[ "broadcast_id" ], "session_id": "bcce2e01",
          "persona_name": "Tiberius", "persona_icon": "👑", "persona_color": "#3F51B5",
          "ack_status": "completed", "body_summary": "on it" },
    ],
}

_NO_ACKS = { "acks": [] }


def _tally_text( page ) -> str:
    node = page.query_selector( '[data-testid="broadcast-ack-summary"]' )
    return ( node.text_content() if node is not None else "" ) or ""


def test_the_ack_tally_appears_after_a_send( page ):
    """
    Ensures (stubbed recipients + broadcast POST + an EMPTY ack list):
        - No tally before a send — there is no broadcast to tally.
        - After a successful send the tally renders, reading 0 of the 2 recipients.

    The ack list is deliberately EMPTY here. This case is about the tally APPEARING
    and being wired to the id the server minted; the reload case below is the one
    that proves saved acks come back.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS, broadcast_body=_BROADCAST_RESULT )
    page.route( BROADCAST_ACKS_ROUTE, _fulfill_json( _NO_ACKS ) )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    assert page.query_selector( '[data-testid="broadcast-ack-tally"]' ) is None, (
        "nothing has been broadcast yet — a tally here would be counting acks for nothing" )

    page.fill( "#broadcast-textarea", "all hands" )
    page.click( "#broadcast-send-button" )
    page.click( '[data-testid="multiplexer-broadcast-confirm-btn"]' )

    page.wait_for_selector( '[data-testid="broadcast-ack-tally"]', timeout=5_000 )
    assert _tally_text( page ) == "0/2 complete", (
        f"the tally must count against the recipient list, got { _tally_text( page )!r}" )


def test_a_live_ack_lands_in_the_tally_without_carding_a_notification( page ):
    """
    🔴 BOTH ARMS, IN A REAL BROWSER. The unit tests assert this against the real
    NotificationStore on a real bus; this asserts it against the real ASSEMBLED page,
    where the intercept, the bus, AckStore and the renderer are all the production
    wiring rather than a harness.

    The ack frame is pushed through the boot test-hook's EventBus exactly as the
    transport delivers it: `message: ""`, the whole identity in `payload`.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS, broadcast_body=_BROADCAST_RESULT )
    page.route( BROADCAST_ACKS_ROUTE, _fulfill_json( _NO_ACKS ) )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    page.fill( "#broadcast-textarea", "all hands" )
    page.click( "#broadcast-send-button" )
    page.click( '[data-testid="multiplexer-broadcast-confirm-btn"]' )
    page.wait_for_selector( '[data-testid="broadcast-ack-tally"]', timeout=5_000 )

    cards_before = len( page.query_selector_all( ".sender-message" ) )

    page.evaluate(
        """( bid ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type   : "notification_queue_update",
                payload: { notification: {
                    notification_type: "commons_broadcast_ack",
                    id_hash          : "e2e-ack-1",
                    message          : "",
                    sender_id        : "claude.code@unknown.deepily.ai#bcce2e01",
                    payload          : { broadcast_id: bid, session_id: "bcce2e01",
                                         persona_name: "Tiberius", persona_icon: "👑",
                                         status: "completed", body_summary: "on it" },
                } },
                source : "e2e",
                ts     : Date.now(),
            } );
        }""",
        _BROADCAST_RESULT[ "broadcast_id" ],
    )

    page.wait_for_function(
        """() => {
            const n = document.querySelector( '[data-testid="broadcast-ack-summary"]' );
            return n && n.textContent === '1/2 complete';
        }""",
        timeout=5_000,
    )

    row = page.query_selector( '[data-testid="broadcast-ack-row"]' )
    assert row is not None, "ARM A — the ack must reach the tally"
    assert "Tiberius" in ( row.text_content() or "" )

    cards_after = len( page.query_selector_all( ".sender-message" ) )
    assert cards_after == cards_before, (
        "ARM B — an ack must NOT be carded: a bodiless row in the user's notification "
        f"history is the defect the intercept exists to prevent (cards { cards_before } -> { cards_after })" )

    # 🔴 CONTROL, AND WITHOUT IT ARM B IS `0 == 0`. An unchanged card count is also what
    # a selector that matches NOTHING returns — and the first draft of this test used a
    # `data-testid` that does not exist in the tree, which would have passed forever.
    # An ORDINARY notification through the same hook must move the count.
    page.evaluate(
        """() => {
            window.__multiplexerTestHook.eventBus.emit( {
                type   : "notification_queue_update",
                payload: { notification: { id_hash: "e2e-ordinary-1", message: "an ordinary message",
                                           sender_id: "claude.code@lupin.deepily.ai#bcce2e01" } },
                source : "e2e",
                ts     : Date.now(),
            } );
        }"""
    )
    page.wait_for_function(
        f"() => document.querySelectorAll( '.sender-message' ).length === { cards_before + 1 }",
        timeout=5_000,
    )
    assert len( page.query_selector_all( ".sender-message" ) ) == cards_before + 1, (
        "CONTROL FAILED — `.sender-message` matches nothing on this page, so ARM B's "
        "unchanged count proved nothing at all" )


def test_the_ack_tally_SURVIVES_A_RELOAD( page ):
    """
    🔴 THE CASE THE WHOLE SERVER HALF EXISTS FOR, and the only one a unit test cannot
    honestly make. Legacy kept its tally in a module-local Map, so closing the page
    lost it outright.

    THREE THINGS MUST ALL SURVIVE, and the reload destroys every in-memory copy of
    each: the broadcast id (localStorage), the acks themselves (the server, replayed
    through GET /api/notifications/broadcast-acks/{id}), and the renderer's ability to
    put them back on screen with NOTHING having been live-folded.

    The ack list is served ONLY after the reload. Before it, the tally reads 0/2 — so
    a 1/2 afterwards cannot have come from anything the first page held.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS, broadcast_body=_BROADCAST_RESULT )
    page.route( BROADCAST_ACKS_ROUTE, _fulfill_json( _NO_ACKS ) )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    page.fill( "#broadcast-textarea", "all hands" )
    page.click( "#broadcast-send-button" )
    page.click( '[data-testid="multiplexer-broadcast-confirm-btn"]' )
    page.wait_for_selector( '[data-testid="broadcast-ack-tally"]', timeout=5_000 )
    assert _tally_text( page ) == "0/2 complete", (
        f"PRECONDITION — the first page must hold NO acks, or a hit after the reload "
        f"proves nothing. Got { _tally_text( page )!r}" )

    # From here the server has an ack. Nothing on the first page ever saw it.
    page.unroute( BROADCAST_ACKS_ROUTE )
    page.route( BROADCAST_ACKS_ROUTE, _fulfill_json( _SAVED_ACKS ) )

    page.reload( wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )

    page.wait_for_function(
        """() => {
            const n = document.querySelector( '[data-testid="broadcast-ack-summary"]' );
            return n && n.textContent === '1/2 complete';
        }""",
        timeout=5_000,
    )

    # 🔴 AND IT MUST NEVER HAVE CLAIMED COMPLETION ON THE WAY THERE. María's blocker on
    # 5b569053: the tally restored and painted BEFORE the recipient list had loaded, so
    # expected was 0, received === expected was true at 0 === 0, and it rendered
    # "✅ All 0 sessions acknowledged" before jumping to "2/0". The unit tests could not
    # see it because every one of them awaited the recipient hydrate before mounting —
    # a mount order production never performs on a reload. Only the real page has the
    # real ordering, which is what this assertion is for.
    assert "All 0" not in ( _tally_text( page ) or "" ), (
        "a restored tally must never read 'All 0 ... acknowledged' — that says the "
        "broadcast is fully answered when the roster simply has not loaded" )

    row = page.query_selector( '[data-testid="broadcast-ack-row"]' )
    assert row is not None, "the replayed ack must render as a row"
    text = row.text_content() or ""
    assert "Tiberius" in text and "completed" in text, (
        f"the persisted ack's identity and status must come back, got { text!r}" )

    pending = page.query_selector( '[data-testid="broadcast-ack-pending"]' )
    assert pending is not None and "Rachel" in ( pending.text_content() or "" ), (
        "and the seat that has NOT acked must still be named as pending after the reload" )


def test_a_reload_with_NO_prior_send_shows_no_tally( page ):
    """
    🔴 THE CONTROL FOR THE RELOAD CASE. Every assertion above would pass just as well
    if the page rendered a tally unconditionally. This is the arm that says the tally
    came back because something was SAVED, not because the page always draws one.
    """
    _open( page, sessions_body=_TWO_RECIPIENTS )
    page.route( BROADCAST_ACKS_ROUTE, _fulfill_json( _SAVED_ACKS ) )
    page.wait_for_selector( "button.broadcast-chip[data-token='Tiberius']", timeout=5_000 )

    page.reload( wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    page.wait_for_selector( "#broadcast-aggregate-panel", timeout=5_000 )

    assert page.query_selector( '[data-testid="broadcast-ack-tally"]' ) is None, (
        "nothing was ever broadcast from this browser, so there is nothing to restore — "
        "a tally here would mean the page draws one regardless, and the reload test above "
        "would be measuring nothing" )
