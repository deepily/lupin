#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP14: prediction-hint thumbs vote (F8).

Exercises the PredictionVoteStore vote round-trip in a real browser: context
stash → vote(id, dir) → `POST /api/notify/prediction-vote/{id}` (stubbed) →
recorded vote, driven through the test-hook store (real in-browser ApiClient +
EventBus).

SCOPE (F8 integration landed 2026-06-22, Tiffany 💍): the vote CONTROLS template
(`renderPredictionVoteControls` — the ≥50%-confidence gate, the 👍🏼/👎🏼 buttons,
the `.voted`/`.selected` highlight) is now wired into the notification-item render
path (NotificationsListRenderer ← boot.ts injects stores.predictionVote). The
previously-skipped DOM-level test (`test_vote_controls_dom_render_and_gate`) is
implemented + un-skipped: it seeds a prediction notification through the live
queue-update reducer and asserts the full-page render (gate present/absent),
the vote POST, the optimistic highlight, and the reconcile. It runs GREEN only
against a boot.js that includes the F8 wiring (rebuild via
src/scripts/build-multiplexer.sh). The store-level round-trip + the unit suite
(templates_prediction_vote_controls.test.ts, notifications_list_renderer.test.ts)
remain the fast logic gate.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Authored
by Lane E; RUN by the manager.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_prediction_vote.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

VOTE_ROUTE = "**/api/notify/prediction-vote/**"

# Stash context + cast a vote through the in-browser PredictionVoteStore. Returns
# the vote() boolean result so the test can assert success/failure.
_VOTE_VIA_STORE_JS = """
async ( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.stores || !hook.stores.predictionVote ) throw new Error( "predictionVote store missing" );
    const store = hook.stores.predictionVote;
    if ( args.withContext ) {
        store.setContext( args.id, {
            question        : 'Schedule the meeting?',
            predicted_value : 'yes',
            category        : 'calendar',
            response_type   : 'yes_no',
        } );
    }
    const ok = await store.vote( args.id, args.dir );
    return { ok: ok, recorded: store.getVote( args.id ) ?? null };
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


def _seed_auth( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.stores !== undefined",
        timeout=timeout_ms,
    )


def _open( page, hits: dict ):
    """Seed auth on the managed page + stub the vote endpoint, then navigate.

    Uses the pytest-playwright `page` fixture (loop-managed) instead of a manual
    `sync_playwright()` launch, which trips "Sync API inside the asyncio loop".
    """
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )

    def _vote_handler( route ):
        hits[ "n" ] += 1
        hits[ "last_url" ] = route.request.url
        hits[ "last_body" ] = route.request.post_data
        route.fulfill( status=200, content_type="application/json", body=json.dumps( { "status": "ok" } ) )

    page.route( VOTE_ROUTE, _vote_handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )


def test_vote_round_trip_posts_and_records( page ):
    hits = { "n": 0, "last_url": "", "last_body": "" }
    _open( page, hits )
    result = page.evaluate( _VOTE_VIA_STORE_JS, { "id": "n1", "dir": "up", "withContext": True } )
    assert result[ "ok" ] is True
    assert result[ "recorded" ] == "up"
    assert hits[ "n" ] == 1
    assert "/api/notify/prediction-vote/n1" in hits[ "last_url" ]
    body = json.loads( hits[ "last_body" ] )
    assert body[ "vote" ] == "up"
    assert body[ "response_type" ] == "yes_no"


def test_vote_without_context_is_rejected_no_post( page ):
    hits = { "n": 0, "last_url": "", "last_body": "" }
    _open( page, hits )
    result = page.evaluate( _VOTE_VIA_STORE_JS, { "id": "unknown", "dir": "up", "withContext": False } )
    assert result[ "ok" ] is False
    assert result[ "recorded" ] is None
    assert hits[ "n" ] == 0


# Seed a NON-action-required notification carrying a prediction_hint through the
# live queue-update path, so the NotificationsListRenderer paints it (sender
# section). `confidence` drives the gate (≥50% → controls mount). Returns once
# the synchronous reducer + re-render have run.
_SEED_PREDICTION_NOTIFICATION_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "eventBus missing on test hook" );
    hook.eventBus.emit( {
        type    : "notification_queue_update",
        payload : { notification : {
            id_hash         : args.id,
            message         : args.message,
            sender_id       : args.sender,
            timestamp       : "2026-06-22T14:00:00.000Z",
            response_type   : "yes_no",
            prediction_hint : { confidence: args.confidence, predicted_value: "yes", category: "calendar" },
        } },
        source : "test",
        ts     : 1750600000000,
    } );
}
"""

# Locate the vote control sub-tree for a given notification id_hash in the
# rendered sender section. Returns presence + the cast-highlight state so one
# round-trip can assert mount → optimistic → reconcile.
_VOTE_CONTROL_STATE_JS = """
( id ) => {
    const msg = document.querySelector( `.sender-message[data-id-hash="${id}"]` );
    if ( msg === null ) return { present: false };
    const controls = msg.querySelector( '.prediction-hint-vote' );
    if ( controls === null ) return { present: false };
    const up   = controls.querySelector( '.prediction-vote-up' );
    const down = controls.querySelector( '.prediction-vote-down' );
    return {
        present      : true,
        voted        : controls.classList.contains( 'voted' ),
        up_selected  : up   !== null && up.classList.contains( 'selected' ),
        down_selected: down !== null && down.classList.contains( 'selected' ),
    };
}
"""


def test_vote_controls_dom_render_and_gate( page ):
    """F8 acceptance (Gate 1 + Gate 2): the vote-controls contract node renders
    PRESENT for a prediction notification clearing the confidence gate, is ABSENT
    below it, and a click drives the POST + optimistic highlight + reconcile.

    Drives the FULL multiplexer page (boot.js): seed a prediction notification
    through the live queue-update reducer → NotificationsListRenderer paints the
    notification-item → vote controls. The integration wiring (boot.ts injects
    stores.predictionVote into the renderer) must be in the served boot.js — so
    this runs GREEN only against a build that includes the F8 wiring.
    """
    hits = { "n": 0, "last_url": "", "last_body": "" }
    _open( page, hits )

    # --- Gate (below threshold → NO controls): confidence 0.40 < 0.50 ---
    page.evaluate( _SEED_PREDICTION_NOTIFICATION_JS, {
        "id": "pred-low", "message": "Low-confidence hint?", "sender": "sess_pred_low", "confidence": 0.40,
    } )
    page.wait_for_selector( '.sender-message[data-id-hash="pred-low"]', timeout=5_000 )
    low = page.evaluate( _VOTE_CONTROL_STATE_JS, "pred-low" )
    assert low[ "present" ] is False, "controls must NOT render below the 50% gate"

    # --- Gate 1 (at/above threshold → controls PRESENT): confidence 0.90 ---
    page.evaluate( _SEED_PREDICTION_NOTIFICATION_JS, {
        "id": "pred-hi", "message": "Schedule the meeting?", "sender": "sess_pred_hi", "confidence": 0.90,
    } )
    page.wait_for_selector( '.sender-message[data-id-hash="pred-hi"] .prediction-hint-vote', timeout=5_000 )
    before = page.evaluate( _VOTE_CONTROL_STATE_JS, "pred-hi" )
    assert before[ "present" ] is True, "vote-controls contract node must render PRESENT for a prediction notification"
    assert before[ "voted" ] is False and before[ "up_selected" ] is False, "no cast yet → unhighlighted"

    # --- Gate 2 (round-trip): click 👍🏼 → optimistic highlight + POST fires ---
    page.click( '.sender-message[data-id-hash="pred-hi"] .prediction-vote-up' )
    page.wait_for_selector( '.sender-message[data-id-hash="pred-hi"] .prediction-vote-up.selected', timeout=5_000 )
    assert hits[ "n" ] == 1, "exactly one prediction-vote POST must fire"
    assert "/api/notify/prediction-vote/pred-hi" in hits[ "last_url" ]
    body = json.loads( hits[ "last_body" ] )
    assert body[ "vote" ] == "up"
    assert body[ "question" ] == "Schedule the meeting?"
    assert body[ "response_type" ] == "yes_no"

    # --- Reconcile: the recorded vote survives the post-POST re-render ---
    after = page.evaluate( _VOTE_CONTROL_STATE_JS, "pred-hi" )
    assert after[ "present" ] is True
    assert after[ "voted" ] is True and after[ "up_selected" ] is True, "reconciled cast-vote highlight persists"
    assert after[ "down_selected" ] is False
