"""
WS3 — Full-Page Chrome Parity-Oracle: shared browser/HTTP glue.

Single-sources the login + token-injection + navigate + chrome-walk the capture
and Tier 1–3 files all share. Leading-underscore module name → pytest does NOT
collect it as a test file; its lines are covered when any tier that imports it
runs. Pure PARSING/selector logic stays in tests.e2e_ui.parity_oracle; only the
browser/HTTP driving lives here (mirrors the sender-card split where `_login` +
`page.evaluate` glue live in the test files, not the shared module).
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest
import requests

from tests.e2e_ui.parity_oracle import (
    CHROME_STYLE_PROPS,
    PAGE_CHROME_WALK_JS,
    chrome_rows_for,
)

# querySelector( ".container" ) resolves BOTH the legacy `<div class="container">`
# and the mux `<main class="container">` — one selector, both clients.
CONTAINER_SEL = ".container"


def base_url() -> str:
    """The dev server under test (:7999 by default)."""
    return os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )


def login_tokens( base: str ) -> tuple[ str, str ]:
    """Authenticate the shared mock-jobs test user; return (access, refresh).

    Skips (not fails) when the credential env vars are unset — the same
    non-destructive skip the sender-card capture uses.
    """
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD not set" )
    resp = requests.post(
        f"{base}/auth/login", json={ "email": email, "password": password }, timeout=10,
    )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def open_and_walk( page, url: str, client: str, wait_selector: str, settle_ms: int = 1_500 ) -> dict[ str, Any ]:
    """Log in, seed auth, navigate to `url`, wait for the client to hydrate, and
    return the page-chrome walk (row → presence/display/styles/geom).

    Requires:
        - client is "legacy" or "mux"
        - wait_selector is a chrome anchor present in the served page shell

    Ensures:
        - auth tokens are injected before navigation
        - for the mux, waits for __multiplexerTestHook before walking
        - returns the PAGE_CHROME_WALK_JS result for `client`'s selectors
    """
    access, refresh = login_tokens( base_url() )
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    page.goto( url, wait_until="networkidle", timeout=20_000 )
    if client == "mux":
        page.wait_for_function( "() => window.__multiplexerTestHook !== undefined", timeout=10_000 )
    page.wait_for_selector( wait_selector, timeout=15_000 )
    page.wait_for_timeout( settle_ms )
    return page.evaluate(
        PAGE_CHROME_WALK_JS,
        { "rows": chrome_rows_for( client ), "props": CHROME_STYLE_PROPS, "containerSel": CONTAINER_SEL },
    )
