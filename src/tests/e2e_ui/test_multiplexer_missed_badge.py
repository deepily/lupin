#!/usr/bin/env python3
"""
E2E — Multiplexer Lane E WP15: "N missed while away" badge + Reset (F7).

Exercises MissedStore + MissedBadgeRenderer end-to-end: the badge surfaces from
an `auth_success` frame carrying `undelivered_count` (seeded via the test-hook
EventBus), shows only when count > 0, and the Reset button soft-dismisses via
`POST /api/notifications/undelivered/dismiss` (stubbed) and zeroes the badge live.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Authored
by Lane E; RUN by the manager. Per CLAUDE.local.md "USER IS NEVER A TESTER":
every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_missed_badge.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_missed_badge.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

DISMISS_ROUTE = "**/api/notifications/undelivered/dismiss"

# Seed an auth_success frame with `undelivered_count` via the test-hook EventBus.
# QueueTransport delivers auth_success FLAT (payload === frame minus type/timestamp),
# so the EventBus payload carries undelivered_count at the top level (WP0 flat-frame).
_SEED_AUTH_SUCCESS_JS = """
( count ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    hook.eventBus.emit({
        type    : 'auth_success',
        payload : { user_id: 'u1', session_id: 's1', undelivered_count: count },
        source  : 'e2e-missed',
        ts      : Date.now(),
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


def _open( page, *, dismiss_remaining: int = 0 ):
    """Seed auth on the managed page + stub the dismiss endpoint, then navigate.

    Uses the pytest-playwright `page` fixture (loop-managed) instead of a manual
    `sync_playwright()` launch, which trips "Sync API inside the asyncio loop".
    """
    access, refresh = _login_tokens()
    _seed_auth( page.context, access, refresh )

    def _dismiss_handler( route ):
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps( { "status": "success", "dismissed_count": 5, "undelivered_count": dismiss_remaining } ),
        )

    page.route( DISMISS_ROUTE, _dismiss_handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )


def test_missed_badge_hidden_when_count_zero( page ):
    _open( page )
    page.evaluate( _SEED_AUTH_SUCCESS_JS, 0 )
    # Badge stays absent at 0.
    page.wait_for_timeout( 200 )
    assert page.locator( "#missed-badge-mount .missed-badge" ).count() == 0


def test_missed_badge_shows_count_when_nonzero( page ):
    _open( page )
    page.evaluate( _SEED_AUTH_SUCCESS_JS, 4 )
    page.wait_for_selector( "#missed-badge-mount .missed-badge", timeout=2000 )
    assert page.locator( ".missed-status" ).text_content() == "4 missed while away"
    assert page.locator( ".missed-reset-button" ).count() == 1


def test_missed_reset_dismisses_and_zeroes_badge_live( page ):
    _open( page, dismiss_remaining=0 )
    page.evaluate( _SEED_AUTH_SUCCESS_JS, 4 )
    page.wait_for_selector( "#missed-badge-mount .missed-badge", timeout=2000 )
    page.locator( ".missed-reset-button" ).click()
    # POST resolves with undelivered_count=0 → badge disappears live.
    page.wait_for_function(
        "() => document.querySelectorAll('#missed-badge-mount .missed-badge').length === 0",
        timeout=2000,
    )
