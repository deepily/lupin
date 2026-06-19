#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP14: prediction-hint thumbs vote (F8).

Exercises the PredictionVoteStore vote round-trip in a real browser: context
stash → vote(id, dir) → `POST /api/notify/prediction-vote/{id}` (stubbed) →
recorded vote, driven through the test-hook store (real in-browser ApiClient +
EventBus).

SCOPE NOTE (explicit per "USER IS NEVER A TESTER" — name what cannot be
automated yet + why): the vote CONTROLS template (`renderPredictionVoteControls`
— the ≥50%-confidence gate, the 👍🏼/👎🏼 buttons, the `.voted`/`.selected`
highlight) is invoked by the notification-item render path
(NotificationsListRenderer), which is the INTEGRATION OWNER's surface and is NOT
yet wired in the multiplexer. The DOM-level control assertions
(`test_vote_controls_*` below) are therefore `@pytest.mark.skip` with that reason
until the integration owner mounts the template; the store-level round-trip
(the POST contract + reducer) IS exercised now. The gate + DOM highlight are
already covered at 100% by the unit suite
(templates_prediction_vote_controls.test.ts).

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


@pytest.mark.skip(
    reason="Vote-controls template (gate + 👍🏼/👎🏼 + .voted/.selected) is invoked by "
           "NotificationsListRenderer (integration owner's surface), not yet mounted in the "
           "multiplexer. DOM-level control assertions land once the integration owner wires "
           "renderPredictionVoteControls into the notification-item render path. The gate + "
           "highlight are covered at 100% by templates_prediction_vote_controls.test.ts."
)
def test_vote_controls_dom_render_and_gate():  # pragma: no cover - documented deferral
    raise NotImplementedError
