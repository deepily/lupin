"""
WS3 — Layout-Parity Oracle: golden-capture (Doc 01 — "Golden-capture vs live
dual-render"; Doc 00 §6 "the one genuine risk").

Drives the LEGACY notifications.js client ONCE with the canonical fixture (via
its real senders-visible + conversation-by-date ingestion, route-stubbed from
the SAME TS adapter through window.__parityLegacyShapes), serializes the contract
subtree's skeleton + computed-style map + geometry map to the git-tracked golden
(src/tests/e2e_ui/fixtures/golden/notifications-legacy.golden.json), and bakes
the WS1 shared-sheet content hash as a staleness trip-wire (Rider C).

This is a CAPTURE / recalibration step, not a per-run test — it WRITES a tracked
artifact and is gated behind LUPIN_PARITY_CAPTURE=1 so a normal suite run never
rewrites the golden. Tiers 2/3 (test_tier2_tier3.py) read the golden and run
every time.

Venue: :7999 (legacy reachable; read-only — server data is fully stubbed). Run:
    bash src/scripts/build-parity-harness.sh
    LUPIN_PARITY_CAPTURE=1 LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle/test_golden_capture.py -v -s
"""

from __future__ import annotations

import json
import os

import pytest
import requests

from tests.e2e_ui.parity_oracle import (
    CONTRACT_SKELETON_JS,
    HARNESS_URL_PATH,
    content_hash,
    load_scenario,
    repo_root,
    shared_sheet_path,
)

BASE_URL    = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:7999" )
HARNESS_URL = f"{BASE_URL}{HARNESS_URL_PATH}"
LEGACY_URL  = f"{BASE_URL}/app/notifications?classic=1"

GOLDEN_PATH = repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden" / "notifications-legacy.golden.json"

_CAPTURE_ENABLED = os.environ.get( "LUPIN_PARITY_CAPTURE" ) == "1"

pytestmark = pytest.mark.skipif(
    not _CAPTURE_ENABLED,
    reason="golden-capture is a gated recalibration step — set LUPIN_PARITY_CAPTURE=1 to run",
)


def _login():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD not set" )
    resp = requests.post(
        f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10,
    )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ], email


def _legacy_shapes( page ) -> dict:
    """Compute the legacy stub bodies via the TS adapter on the harness bundle."""
    page.goto( HARNESS_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__parityHarnessReady === true && typeof window.__parityLegacyShapes === 'function'",
        timeout=10_000,
    )
    return page.evaluate( "( s ) => window.__parityLegacyShapes( s )", load_scenario() )


def _install_stubs( page, shapes: dict ):
    senders_visible     = shapes[ "sendersVisible" ]
    conversation_by_date = shapes[ "conversationByDate" ]

    def _senders( route ):
        route.fulfill( status=200, content_type="application/json", body=json.dumps( senders_visible ) )

    def _conversation( route ):
        url = route.request.url
        body: dict = {}
        for sender_id, payload in conversation_by_date.items():
            quoted = requests.utils.quote( sender_id, safe="" )
            if f"conversation-by-date/{quoted}/" in url or f"conversation-by-date/{sender_id}/" in url:
                body = payload
                break
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )

    page.route( "**/api/notifications/senders-visible/**", _senders )
    page.route( "**/api/notifications/conversation-by-date/**", _conversation )


def test_capture_legacy_golden( page ):
    """Drive legacy with the fixture; dump its contract DOM (exploration) and,
    once the structure is confirmed, serialize the golden."""
    access, refresh, _email = _login()
    shapes = _legacy_shapes( page )

    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    _install_stubs( page, shapes )

    page.goto( LEGACY_URL, wait_until="networkidle", timeout=20_000 )

    # Legacy renders sender cards into #notifications-list (notifications.js:11438).
    page.wait_for_selector( "#notifications-list .sender-card", timeout=15_000 )

    # --- Exploration dump: learn legacy's real contract DOM attributes --------
    summary = page.evaluate(
        """() => {
            const root = document.querySelector( '#notifications-list' );
            const cards = [ ...root.querySelectorAll( '.sender-card' ) ];
            return {
                card_count : cards.length,
                first_card_attrs : cards[0] ? [ ...cards[0].attributes ].map( a => a.name + '=' + a.value ) : null,
                accordion_attrs  : cards[0] ? [ ...cards[0].querySelectorAll( '.date-accordion' ) ].map(
                    a => [ ...a.attributes ].map( x => x.name + '=' + x.value ) ) : null,
                message_classes  : cards[0] ? [ ...cards[0].querySelectorAll( '.sender-message' ) ].map(
                    m => m.className + ' | id-hash=' + ( m.getAttribute('data-id-hash') ?? 'NONE' ) ) : null,
                has_badge        : cards[0] ? cards[0].querySelector('.sender-persona-badge, .persona-badge') !== null : null,
            };
        }"""
    )
    print( "\n=== LEGACY CONTRACT DOM SUMMARY ===" )
    print( json.dumps( summary, indent=2 ) )

    skeleton = page.evaluate( CONTRACT_SKELETON_JS, "#notifications-list" )
    print( "\n=== LEGACY CONTRACT SKELETON ===" )
    print( json.dumps( skeleton, indent=2 ) )

    # Capture is wired below once the dump confirms alignment; write a provisional
    # golden carrying the skeleton + the Rider-C shared-sheet hash trip-wire.
    GOLDEN_PATH.parent.mkdir( parents=True, exist_ok=True )
    golden = {
        "captured_from"     : "legacy notifications.js",
        "scenario"          : "notifications-parity-scenario.json",
        "shared_sheet_hash" : content_hash( shared_sheet_path() ),
        "skeleton"          : skeleton,
    }
    GOLDEN_PATH.write_text( json.dumps( golden, indent=2 ) + "\n" )
    print( f"\n✓ wrote provisional golden → {GOLDEN_PATH}" )

    assert summary[ "card_count" ] >= 1
