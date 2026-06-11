#!/usr/bin/env python3
"""
E2E — Multiplexer Lane A WP0: boot-time login bounce (auth guard).

Exercises `authGuard.ts:redirectToLoginIfUnauthenticated` end-to-end through
real browser navigation: a user landing on /app/multiplexer with NO access
token under the canonical `lupin_access_token` storage key is bounced to
`/app/auth/login?redirect=%2Fapp%2Fmultiplexer` BEFORE boot proceeds; a user
WITH a token boots normally. The guard is presence-only by contract — an
expired/garbage token still proceeds to boot (AuthManager owns refresh).

Assertions are anchored on the guard's actual observable surface: the final
`window.location` (path + decoded `redirect` query param) and the boot
test-hook's presence/absence — not on intermediate DOM that could false-pass.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_auth_bounce.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_auth_bounce.py -v
"""

from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlparse

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"
LOGIN_PATH      = "/app/auth/login"


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


def _seed_tokens( context, access_token: str, refresh_token: str ) -> None:
    context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access_token ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh_token ) });"
    )


def _clear_tokens( context ) -> None:
    # Defensive: the managed context starts clean, but make the precondition
    # explicit so a future shared-state fixture can't silently invalidate it.
    context.add_init_script(
        "window.localStorage.removeItem('lupin_access_token');"
        "window.localStorage.removeItem('lupin_refresh_token');"
    )


def test_no_token_bounces_to_login_with_redirect_back( page ):
    """
    Ensures:
        - With NO `lupin_access_token`, landing on /app/multiplexer ends on
          /app/auth/login with `?redirect=/app/multiplexer` (decoded)
        - Boot HALTED: the multiplexer test hook never installs
    """
    _clear_tokens( page.context )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )

    page.wait_for_url( f"**{LOGIN_PATH}*", timeout=5_000 )

    parsed = urlparse( page.url )
    assert parsed.path == LOGIN_PATH, f"guard must land on the login page; got {page.url}"
    redirect_values = parse_qs( parsed.query ).get( "redirect" )
    assert redirect_values == [ "/app/multiplexer" ], \
        f"redirect-back param must round-trip the origin path; got {redirect_values!r}"

    # The guard returns true → boot.ts halts BEFORE wiring stores/renderers,
    # so the test hook must be absent on the page we ended up on.
    assert page.evaluate( "() => window.__multiplexerTestHook === undefined" ), \
        "boot must halt when the guard redirects — test hook found after bounce"


def test_valid_token_boots_without_bounce( page ):
    """
    Ensures:
        - With a real token under `lupin_access_token`, /app/multiplexer loads
          and stays (no login URL), and boot completes (test hook installs)
    """
    access, refresh = _login_tokens()
    _seed_tokens( page.context, access, refresh )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )

    assert urlparse( page.url ).path == "/app/multiplexer", \
        f"authenticated load must not bounce; got {page.url}"
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def test_guard_is_presence_only_expired_token_does_not_bounce( page ):
    """
    Ensures:
        - The guard checks token PRESENCE only (authGuard.ts contract): a
          syntactically-JWT-shaped but expired/unverifiable token does NOT
          bounce at the guard layer — the page stays on /app/multiplexer
          (downstream refresh/re-auth is AuthManager's job, out of scope here)
    """
    stale_jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJlMmUtc3RhbGUiLCJleHAiOjF9."
        "invalid-signature-for-guard-presence-test"
    )
    _seed_tokens( page.context, stale_jwt, stale_jwt )

    page.goto( MULTIPLEXER_URL, wait_until="domcontentloaded", timeout=15_000 )
    # Give a would-be (incorrect) bounce time to fire before asserting it didn't.
    page.wait_for_timeout( 1_000 )

    assert urlparse( page.url ).path == "/app/multiplexer", \
        f"presence-only guard must not bounce on an expired token; got {page.url}"
