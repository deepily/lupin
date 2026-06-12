#!/usr/bin/env python3
"""
E2E — Multiplexer cold-load notification hydration (the card-gap fix).

Root cause (src/rnd/v0.1.8/2026.06.11-external-sender-card-gap-root-cause.md):
the multiplexer notifications pane had NO history hydration — cards were
live-event-only, so a cold load rendered ZERO sender cards (repro: 0 cards vs
102 senders with history) and one-shot external advisories (arbiter stall
warnings) vanished forever. Fix (design note
src/rnd/v0.1.8/2026.06.11-mux-cold-load-notification-hydration-design.md):
boot's single senders-visible fetch now also seeds SenderStore +
NotificationStore.hydrateHistory (per-sender conversation-by-date), one
"hydrated" emission per store, cards paint on boot with NO live events.

ADVERSARIAL RECEIPT CONTRACT (Tiberius sequencing, 2026-06-11): this spec is
committed SEPARABLY from the fix+bundle commit. Run against the PRE-FIX bundle
it must FAIL in `test_cold_load_paints_external_sender_card_with_no_live_events`
(0 sender cards — the RC repro); against the post-fix bundle it must PASS.

A FRESH external-sender row is persisted per run (the 2026-06-11
`[E2E-CARDGAP]` fixture row ages out of the 48h rolling window — classic's
virgin default, ruling amended post-review — by Saturday), exercising the
exact one-shot-advisory shape: POST /api/notify with the page CLOSED. The 48h
window also moots the midnight-straddle flake Rio flagged for a today-anchored
window: a row persisted seconds before load is always in-window.

Venue: :8000 (monopolize, scheduled via /api/test-suite/submit) —
`test_multiplexer_*` E2E batch. Per CLAUDE.local.md "USER IS NEVER A TESTER":
every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_cold_load_hydration.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_cold_load_hydration.py -v
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

SENDERS_VISIBLE_ROUTE = "**/api/notifications/senders-visible/**"
CONVERSATION_ROUTE    = "**/api/notifications/conversation-by-date/**"

EXTERNAL_SENDER = "lupin-arbiter-app-8001"


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ], email


def _open( page, access: str, refresh: str, stub_routes: bool = False,
           hydration_records: list[ dict ] | None = None,
           conversations: dict[ str, dict ] | None = None ):
    """Seed auth, optionally stub the hydration endpoints, navigate, wait for
    the test hook. With stub_routes=False the page exercises the REAL server
    hydration path (the adversarial spec)."""
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )

    if stub_routes:
        def _senders_handler( route ):
            route.fulfill( status=200, content_type="application/json",
                           body=json.dumps( hydration_records or [] ) )
        page.route( SENDERS_VISIBLE_ROUTE, _senders_handler )

        def _conversation_handler( route ):
            url = route.request.url
            body: dict = {}
            for sender_id, payload in ( conversations or {} ).items():
                if f"conversation-by-date/{ requests.utils.quote( sender_id, safe='' ) }/" in url \
                   or f"conversation-by-date/{ sender_id }/" in url:
                    body = payload
                    break
            route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )
        page.route( CONVERSATION_ROUTE, _conversation_handler )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _card_selector( sender_id: str ) -> str:
    return f'#sender-cards-container .sender-card[data-sender-id="{sender_id}"]'


def _card_surfaces( page, sender_id: str ) -> dict | None:
    return page.evaluate(
        """( sel ) => {
            const card = document.querySelector( sel );
            if ( !card ) return null;
            const badge  = card.querySelector( '.sender-persona-badge' );
            const unread = card.querySelector( '.sender-new-count' );
            return {
                text          : card.textContent,
                has_badge     : badge !== null,
                unread_text   : unread ? unread.textContent : null,
                message_count : card.querySelectorAll( '.sender-card-dates [data-id-hash]' ).length,
            };
        }""",
        _card_selector( sender_id ),
    )


# ---------------------------------------------------------------------------
# 1 — THE adversarial spec: real server, fresh persisted row, zero live events
# ---------------------------------------------------------------------------

def test_cold_load_paints_external_sender_card_with_no_live_events( page ):
    """
    Ensures (post-fix):
        - a one-shot external advisory persisted while NO page is open gets a
          sender card on the next cold load, with the advisory text present
        - the external card is persona-less (gray treatment — ruling b: no
          .sender-persona-badge)
        - at least one sender card paints overall (the 0-vs-102 RC repro)

    Pre-fix bundle: FAILS here — 0 sender cards (hydration absent). This
    failure IS the adversarial receipt.
    """
    access, refresh, email = _login_tokens()

    # Persist the advisory with the page CLOSED — the exact arbiter-stall
    # shape: fire-and-forget POST, fresh row each run so the 48h rolling
    # window always contains it. Accept queued OR user_not_available (another
    # open tab elsewhere changes connectivity, not persistence — persist is
    # unconditional, RC leg 1).
    unique_msg = f"[E2E-CARDGAP] cold-load hydration receipt { uuid.uuid4().hex[ :8 ] }"
    resp = requests.post(
        f"{BASE_URL}/api/notify",
        params  = {
            "message"     : unique_msg,
            "type"        : "alert",
            "priority"    : "medium",
            "target_user" : email,
            "sender_id"   : EXTERNAL_SENDER,
        },
        headers = { "Authorization": f"Bearer { access }" },
        timeout = 10,
    )
    assert resp.status_code == 200, f"notify POST failed: { resp.status_code } { resp.text }"
    assert resp.json()[ "status" ] in ( "queued", "user_not_available" )

    # Cold load — REAL hydration path, no live events for this sender.
    _open( page, access, refresh, stub_routes=False )
    page.wait_for_selector( _card_selector( EXTERNAL_SENDER ), timeout=15_000 )

    s = _card_surfaces( page, EXTERNAL_SENDER )
    assert s is not None, "external sender card must paint on cold load (RC: pre-fix this is None)"
    assert unique_msg in s[ "text" ], "the persisted advisory text must be in the hydrated card"
    assert s[ "has_badge" ] is False, "external sender is persona-less — no .sender-persona-badge (ruling b)"

    total_cards = page.locator( "#sender-cards-container .sender-card" ).count()
    assert total_cards >= 1, f"cold load must paint sender cards (RC repro was 0); got { total_cards }"


# ---------------------------------------------------------------------------
# 2 — deterministic stubbed snapshot: wiring-level assertions
# ---------------------------------------------------------------------------

def test_cold_load_hydrates_from_stubbed_snapshot_with_zero_live_events( page ):
    """
    Ensures (client wiring, deterministic — server data independent):
        - cards paint purely from stubbed senders-visible +
          conversation-by-date responses with ZERO live WS events
        - unread badge seeds from the snapshot's new_count
        - persona'd CC sender gets its .sender-persona-badge; external
          persona-less sender does not (ruling b)
        - the empty-state placeholder is gone after hydration
    """
    access, refresh, _email = _login_tokens()
    now_iso = datetime.now( timezone.utc ).isoformat()

    cc_sender = "claude.code@lupin.deepily.ai#e2ecold"
    records = [
        {
            "sender_id"       : EXTERNAL_SENDER,
            "last_activity"   : now_iso,
            "count"           : 1,
            "new_count"       : 2,
            "voice_persona"   : None,
            "manager_persona" : None,
        },
        {
            "sender_id"       : cc_sender,
            "last_activity"   : now_iso,
            "count"           : 1,
            "new_count"       : 1,
            "voice_persona"   : { "name": "Rachel", "voice_id": "v1", "icon": "🕊️",
                                  "color": "#CE93D8", "borrowed": False, "assigned_at": now_iso },
            "manager_persona" : None,
        },
    ]
    date_key = now_iso[ :10 ]
    conversations = {
        EXTERNAL_SENDER : { date_key: [ {
            "id"        : "e2e-ext-row-1",
            "sender_id" : EXTERNAL_SENDER,
            "message"   : "[E2E-CARDGAP] stubbed arbiter stall warning",
            "timestamp" : now_iso,
        } ] },
        cc_sender : { date_key: [ {
            "id"        : "e2e-cc-row-1",
            "sender_id" : cc_sender,
            "message"   : "stubbed cc history message",
            "timestamp" : now_iso,
        } ] },
    }

    _open( page, access, refresh, stub_routes=True,
           hydration_records=records, conversations=conversations )
    page.wait_for_selector( _card_selector( EXTERNAL_SENDER ), timeout=10_000 )
    page.wait_for_selector( _card_selector( cc_sender ), timeout=10_000 )

    ext = _card_surfaces( page, EXTERNAL_SENDER )
    cc  = _card_surfaces( page, cc_sender )
    assert ext is not None and cc is not None
    assert "[E2E-CARDGAP] stubbed arbiter stall warning" in ext[ "text" ]
    assert ext[ "has_badge" ]   is False, "persona-less external card must NOT render a persona badge"
    assert ext[ "unread_text" ] == "2", "unread badge must seed from the snapshot's new_count"
    assert ext[ "message_count" ] >= 1
    assert cc[ "has_badge" ]    is True, "persona'd CC sender must render its persona badge from hydration"
    assert "stubbed cc history message" in cc[ "text" ]

    empty_state = page.locator( '[data-testid="multiplexer-empty-state"]' ).count()
    assert empty_state == 0, "empty-state placeholder must be gone once hydration paints cards"
