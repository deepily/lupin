#!/usr/bin/env python3
"""
E2E — Multiplexer R5: session-topic → `.sender-session-name` population.

Closes the LIVE-integration leg of tracker R5 (session-topic population). The
unit tier already proves every layer in isolation (SenderStore.onSessionTopic:
existing-set+emit / pre-card buffer / persona-create / localStorage
persist+restore / null-seed — sender_store.test.ts; NotificationStore intercept
+ re-emit both discriminators + missing-name-no-emit — notification_store.test.ts;
the `.sender-session-name` span presence — templates_sender_card.test.ts). What
NO unit can cover is the CROSS-UNIT RE-RENDER wire:

    session_topic notification  →  NotificationStore intercept (BEFORE normalize)
      →  EventBus `session_topic`  →  SenderStore.onSessionTopic (set name + emit
      "updated")  →  store_senders_changed  →  NotificationsListRenderer re-creates
      the card  →  senderCard.ts:161 renders `${sender.session_name ?? ""}` populated.

That chain is what these two tests prove — the unit-green-but-untested-together seam.

Architecture anchors:
  - server:  session_name Query param + `session_topic` notification type
             (notifications.py:542 / :610 / :954 — the param's own description:
             "Updates sender-session-name span in notification history card").
  - client:  NotificationStore.ts:541 (intercept/re-emit), SenderStore.ts:274
             (onSessionTopic), NotificationsListRenderer.ts:260 (re-render on
             store_senders_changed), senderCard.ts:161 (the span).

THE TEST — DETERMINISTIC (server-data-independent): cold-load a stubbed persona'd
CC card, assert `.sender-session-name` starts empty, emit a `session_topic` event
on the live EventBus via the test hook (the exact shape NotificationStore
re-emits after intercepting), and assert the card's span now shows the name —
the store→re-render integration the unit tier cannot prove.

WHY NO LIVE-WIRE BROWSER TEST (deliberate two-tier coverage, Sam 2026-07-02):
the server→client leg (a real `session_topic` notification shape → NotificationStore
intercept → bus emission, NOT carded) is already deterministically covered at the
UNIT tier — notification_store.test.ts: "a session_topic notification emits a
session_topic event and is NOT carded" (+ the discriminator + missing-name cases).
The only remaining live path would be a WS-push-to-an-already-open-page browser
assertion, which is inherently timing/subscription-flaky (the sibling
test_multiplexer_cold_load_hydration.py avoids live push for exactly this reason,
using persist-then-cold-load instead). R5's `session_name` is NOT server-persisted
(client-localStorage only, by design — SenderStore.ts:140) so there is no robust
cold-load path for it either. Shipping a known-flaky red is worse than the two
deterministic tiers above, which together cover the full contract.

Venue: :8000 (monopolize, scheduled via /api/test-suite/submit) — the
`test_multiplexer_*` E2E batch. The e2e_ui conftest HARD-GATES on the test DB
(`conftest.py:353` refuses any non-`lupin_db_test` server), so BOTH tests are
structurally :8000-only — there is no :7999 dry-run path by design. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI-executed.

Usage:
    LUPIN_API_URL=http://localhost:8000 pytest \
        src/tests/e2e_ui/test_multiplexer_session_topic_name.py -v
    # or, the sanctioned monopolize path (self-authorized on a verified-idle :8000):
    #   POST /api/test-suite/submit {test_types:"e2e", pytest_args:"-k session_topic"}
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

# CC sender ids carry a '#'; only they emit the session block (with the
# `.sender-session-name` span) — see templates_sender_card.test.ts:210.
CC_SENDER = "claude.code@lupin.deepily.ai#r5e2e"


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
    """Seed auth, optionally stub the hydration endpoints, navigate, wait for the
    multiplexer test hook (eventBus + stores). stub_routes=False exercises the
    REAL server hydration path (the live-wire spec)."""
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
        "() => window.__multiplexerTestHook !== undefined "
        "&& window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _card_selector( sender_id: str ) -> str:
    return f'#sender-cards-container .sender-card[data-sender-id="{sender_id}"]'


def _session_name_text( page, sender_id: str ) -> str | None:
    """The rendered text of the card's `.sender-session-name` span (None if the
    card or span is absent)."""
    return page.evaluate(
        """( sel ) => {
            const card = document.querySelector( sel );
            if ( !card ) return null;
            const span = card.querySelector( '.sender-session-name' );
            return span ? span.textContent : null;
        }""",
        _card_selector( sender_id ),
    )


def _emit_session_topic( page, sender_id: str, session_name: str ):
    """Emit a `session_topic` event on the live EventBus exactly as
    NotificationStore does after intercepting the raw notification — the
    deterministic injection point that drives SenderStore.onSessionTopic."""
    page.evaluate(
        """( args ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type   : "session_topic",
                payload: { sender_id: args.sender_id, session_name: args.session_name },
                source : "e2e-r5",
                ts     : Date.now(),
            } );
        }""",
        { "sender_id": sender_id, "session_name": session_name },
    )


def _stub_cc_card( now_iso: str ) -> tuple[ list[ dict ], dict ]:
    """A single persona'd CC sender snapshot + one history row — enough to paint
    the card (with its session block + `.sender-session-name` span) deterministically."""
    records = [ {
        "sender_id"       : CC_SENDER,
        "last_activity"   : now_iso,
        "count"           : 1,
        "new_count"       : 1,
        "voice_persona"   : { "name": "Rachel", "voice_id": "v1", "icon": "🕊️",
                              "color": "#CE93D8", "borrowed": False, "assigned_at": now_iso },
        "manager_persona" : None,
    } ]
    date_key = now_iso[ :10 ]
    conversations = {
        CC_SENDER : { date_key: [ {
            "id"        : "e2e-r5-row-1",
            "sender_id" : CC_SENDER,
            "message"   : "stubbed cc history message for R5",
            "timestamp" : now_iso,
        } ] },
    }
    return records, conversations


# ---------------------------------------------------------------------------
# 1 — DETERMINISTIC: EventBus session_topic → card `.sender-session-name`
#     (server-data-independent, non-mutating; dry-runnable on :7999)
# ---------------------------------------------------------------------------

def test_session_topic_populates_sender_session_name_deterministic( page ):
    """
    Ensures (store→re-render wire, deterministic — server data independent):
        - a stubbed persona'd CC card paints with an EMPTY `.sender-session-name`
          span (the designed cold-state: no topic received yet)
        - emitting a `session_topic` event on the live EventBus (the exact shape
          NotificationStore re-emits) drives SenderStore.onSessionTopic, which
          sets the name and emits store_senders_changed
        - NotificationsListRenderer re-creates the card and the span now shows
          the session name — the cross-unit re-render the unit tier cannot prove

    Zero server mutation (routes stubbed, event injected client-side): this is
    the leg that runs on the served bundle without touching persistent state.
    """
    access, refresh, _email = _login_tokens()
    now_iso = datetime.now( timezone.utc ).isoformat()
    records, conversations = _stub_cc_card( now_iso )

    _open( page, access, refresh, stub_routes=True,
           hydration_records=records, conversations=conversations )
    page.wait_for_selector( _card_selector( CC_SENDER ), timeout=10_000 )

    # Cold state: the span exists but is empty (legacy `${sessionName || ''}` parity).
    assert _session_name_text( page, CC_SENDER ) == "", \
        "`.sender-session-name` must start EMPTY before any session_topic (cold-state fallback)"

    # Inject the topic exactly as NotificationStore would after intercepting.
    session_name = f"R5 topic { uuid.uuid4().hex[ :6 ] }"
    _emit_session_topic( page, CC_SENDER, session_name )

    # The card re-renders on store_senders_changed → the span populates.
    page.wait_for_function(
        """( args ) => {
            const card = document.querySelector( args.sel );
            if ( !card ) return false;
            const span = card.querySelector( '.sender-session-name' );
            return span !== null && span.textContent === args.name;
        }""",
        arg={ "sel": _card_selector( CC_SENDER ), "name": session_name },
        timeout=5_000,
    )
    assert _session_name_text( page, CC_SENDER ) == session_name, \
        "`.sender-session-name` must show the emitted session_topic name after re-render"
