#!/usr/bin/env python3
"""
Shared browser-auth seeding for the multiplexer Playwright smoke files.

WHY THIS EXISTS (measured 2026-08-26, sha b45fa75f)

Commit 53fef419 (2026-06-19) added a boot-time login bounce to the multiplexer
(`auth/authGuard.ts::redirectToLoginIfUnauthenticated`, called from `boot.ts`
before anything mounts) AND moved the persisted token out of the old
schema-versioned envelope key `lupin:auth_token` into two RAW localStorage keys
with no envelope and no `lupin:` prefix:

    lupin_access_token
    lupin_refresh_token

(`shared/StorageService.ts` ACCESS_TOKEN_KEY / REFRESH_TOKEN_KEY;
`auth/jwt.ts` names the envelope "the old schema-versioned `auth_token` blob".)

Every multiplexer smoke file predates that change. Phases 1/5/6a/6b/6c seeded
no token at all; phases 3/4 seeded the now-dead envelope key. Either way the
guard fires, `window.location` becomes `/app/auth/login?redirect=…`, boot never
runs, and every test that waits on `window.__multiplexerTestHook` or on a
`:mounted` console line times out. That is what the 41 reds were.

USAGE — call once per BrowserContext, before `context.new_page()`:

    from tests.smoke.multiplexer_auth import seed_multiplexer_auth
    ...
    context = browser.new_context()
    seed_multiplexer_auth( context )
    page = context.new_page()

`add_init_script` runs on every navigation in the context, so the tokens are in
place before `boot.ts` reads them on the first paint.
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

# StorageService.ts — RAW keys, no `lupin:` prefix, no envelope.
ACCESS_TOKEN_KEY  = "lupin_access_token"
REFRESH_TOKEN_KEY = "lupin_refresh_token"


def get_credentials() -> tuple[ str, str ]:
    """
    Requires:
        - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD in the environment

    Ensures:
        - returns ( email, password )

    Raises:
        - pytest.skip.Exception when either variable is unset
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def login_tokens() -> dict:
    """
    Requires:
        - a Lupin server answering at BASE_URL
        - credentials per get_credentials()

    Ensures:
        - returns the server's `tokens` dict ( access_token, refresh_token, expires_in )

    Raises:
        - AssertionError when /auth/login does not return 200
    """
    email, password = get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    return resp.json()[ "tokens" ]


def seed_multiplexer_auth( context, tokens: dict | None = None ) -> dict:
    """
    Seed a Playwright BrowserContext with the tokens `boot.ts` requires.

    Requires:
        - context is a Playwright BrowserContext with no page created yet
        - tokens, when supplied, carries access_token + refresh_token

    Ensures:
        - the context's localStorage holds lupin_access_token / lupin_refresh_token
          on every navigation, so the boot-time login bounce does not fire
        - returns the tokens dict used (fetched via login_tokens() when not given)
    """
    if tokens is None: tokens = login_tokens()
    context.add_init_script(
        f"window.localStorage.setItem( { json.dumps( ACCESS_TOKEN_KEY ) }, { json.dumps( tokens[ 'access_token' ] ) } );"
        f"window.localStorage.setItem( { json.dumps( REFRESH_TOKEN_KEY ) }, { json.dumps( tokens[ 'refresh_token' ] ) } );"
    )
    return tokens


def stub_empty_hydration( context ) -> None:
    """
    Make the multiplexer boot with an EMPTY sender list AND an empty job list.

    WHY: the page cold-hydrates from two endpoints on load —
    `GET /api/notifications/senders-visible/{email}` (boot.ts, 2026-06-11
    cold-load hydration design) and `GET /api/job-history` (JobsPaneRenderer's
    eager hydrate on mount, Q-A7). Once these smoke tests authenticate as a
    real account, both return that account's live data — 39 sender cards and 20
    jobs on the dev box at the time of writing — so a test that seeds two
    synthetic senders and asserts "2 cards", or injects three fixture jobs and
    asserts "3 job cards", reads the live rows instead of its own fixtures.
    Fulfilling both calls empty restores the blank starting page these tests
    were written against, without weakening a single assertion.

    This removes where the rows come FROM, not what gets DRAWN: each test then
    pushes its own rows through the real event bus, the real stores and the
    real renderers. Verified by mutation on 2026-08-26 — breaking the
    sender-card template's className in the served bundle turns "2 cards" into
    "0 cards" and reddens the same assertions, so a rendering regression still
    fails these tests. What it does hide is the cold-load path itself, which is
    covered separately by
    `src/tests/e2e_ui/test_multiplexer_cold_load_hydration.py`.

    Requires:
        - context is a Playwright BrowserContext

    Ensures:
        - the senders-visible hydration call resolves to an empty JSON array
        - the job-history hydration call resolves to an empty job list
        - both apply to every page in the context
    """
    context.route(
        "**/api/notifications/senders-visible/**",
        lambda route: route.fulfill( status=200, content_type="application/json", body="[]" ),
    )
    context.route(
        "**/api/job-history?**",
        lambda route: route.fulfill(
            status       = 200,
            content_type = "application/json",
            body         = json.dumps( { "jobs": [], "total": 0, "offset": 0, "limit": 0 } ),
        ),
    )
