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


# ---------------------------------------------------------------------------
# 3 — FAIL-LOUD boot contract: zero 4xx on load + Jobs pane really hydrates
# ---------------------------------------------------------------------------
#
# Closes the SAME 404 false-pass class the unit contract test
# (src/tests/unit/test_multiplexer_api_contract.py) attacks at the API layer —
# here at the live-boot layer. The historical JobStore bug
# (`/api/queue/job-history` → 404) slipped EVERY tier because:
#   GAP 1  JobsPaneRenderer.ts:169 `hydrateHistory(api).catch()` SWALLOWS the
#          rejection — the page boots, "page-loads" e2e stays green.
#   GAP 2  the boot e2e registered ONLY page.on("response") for 4xx — a JS
#          error that emits NO 4xx (a TypeError in a renderer, an uncaught
#          throw in boot.ts, a console.error from a failed dynamic import)
#          left the page "loaded" and the suite green. (WS3 cross-cutting,
#          2026-06-22: closed by the console/pageerror capture below.)
#   GAP 3  the boot e2e had no no-4xx / no-console-error assertion and no
#          positive "Jobs pane actually hydrated" assertion.
# This test adds ALL THREE guards, so a swallowed boot-time 4xx OR a no-4xx
# JS error can no longer hide.
#
# >>> VENUE / RUN STATUS: NOT YET RUN. Requires the :8000 test server in
# >>> monopolize mode (live backend + real `/api/job-history` data), scheduled
# >>> via POST /api/test-suite/submit in the `test_multiplexer_*` E2E batch.
# >>> The reviewing manager owns that scheduled run; this spec is written,
# >>> compile-clean, and held — it has NOT been executed here. <<<

def test_boot_has_zero_4xx_and_jobs_pane_hydrates( page ):
    """
    Ensures (live boot, real backend):
        - NO response with a 4xx status is observed for any request issued
          during the `/app/multiplexer` cold load. A swallowed JobStore 404
          (or any sibling client-URL typo) shows up HERE even though the
          renderer's `.catch()` keeps the page booting.
        - ZERO console errors and ZERO uncaught page errors during the boot.
          A JS error that emits no 4xx (a renderer TypeError, an uncaught
          throw in boot.ts, a failed dynamic import) is invisible to the 4xx
          guard but fails HERE (GAP 2).
        - the Jobs pane genuinely HYDRATES: `JobStore.isHistoryHydrated()` is
          true AND the history bucket holds real rows — proving the
          `/api/job-history` round-trip resolved and populated the store, not
          that an empty error-catch left the pane blank.
        - DOM corroboration: the jobs-pane mounts and renders `.job-card`
          elements for the hydrated rows (defeats the store-only false-pass).

    Pre-fix bundle (JobStore calling `/api/queue/job-history`): FAILS here —
    the boot 4xx is observed AND the history bucket stays empty / not hydrated.
    Post-fix bundle: PASSES.

    Requires:
        - live :8000 server with at least one terminal job in /api/job-history
          for the test user (the E2E batch seeds queue history upstream).

    Ensures:
        - fail-loud assertions on both the negative (no 4xx) and positive
          (store hydrated with rows) sides of the contract.
    """
    access, refresh, _email = _login_tokens()

    # Capture every response status seen during the load. page.on("response")
    # fires for the document, every XHR/fetch, and every static asset — exactly
    # the surface a swallowed client-URL 404 would otherwise hide in.
    bad_responses: list[ dict ] = []

    def _record_response( response ):
        status = response.status
        if 400 <= status <= 499:
            bad_responses.append( { "url": response.url, "status": status } )

    page.on( "response", _record_response )

    # GAP 2 — capture JS errors that emit NO 4xx. `console` fires for every
    # console.* call (we keep only type=="error"); `pageerror` fires for every
    # uncaught exception that reaches the window. Registered BEFORE navigation
    # (inside _open) so nothing on the boot path is missed.
    console_errors: list[ str ] = []
    page_errors:    list[ str ] = []

    def _record_console( msg ):
        if msg.type == "error":
            console_errors.append( msg.text )

    def _record_pageerror( error ):
        page_errors.append( str( error ) )

    page.on( "console",   _record_console )
    page.on( "pageerror", _record_pageerror )

    # Cold load against the REAL hydration path (no route stubs).
    _open( page, access, refresh, stub_routes=False )

    # Let the floated hydrateHistory promise settle (it is fire-and-forget off
    # the renderer mount, so wait on the store's own hydration flag rather than
    # a fixed sleep). The hook exposes the live store map.
    page.wait_for_function(
        "() => window.__multiplexerTestHook?.stores?.jobs?.isHistoryHydrated?.() === true",
        timeout=15_000,
    )

    # --- Negative side: zero 4xx during the entire boot ---------------------
    assert not bad_responses, (
        "boot issued request(s) that returned 4xx — a swallowed client-URL "
        "error (the JobStore 404 class):\n"
        + "\n".join( f"  {r['status']}  {r['url']}" for r in bad_responses )
    )

    # --- Negative side: zero JS errors during the boot (GAP 2) --------------
    assert not page_errors, (
        "boot raised uncaught page error(s) — a JS exception that emits no "
        "4xx and would otherwise pass the 4xx-only guard:\n"
        + "\n".join( f"  {e}" for e in page_errors )
    )
    assert not console_errors, (
        "boot logged console error(s) — a no-4xx failure surface (failed "
        "dynamic import, renderer TypeError, etc.):\n"
        + "\n".join( f"  {e}" for e in console_errors )
    )

    # --- Positive side: the Jobs pane really hydrated -----------------------
    hydration = page.evaluate(
        """() => {
            const jobs = window.__multiplexerTestHook.stores.jobs;
            return {
                hydrated   : jobs.isHistoryHydrated(),
                history_n  : jobs.bucket( "history" ).length,
            };
        }"""
    )
    assert hydration[ "hydrated" ] is True, (
        "JobStore.isHistoryHydrated() must be true after boot — a swallowed "
        "/api/job-history failure leaves this false while the page still boots"
    )
    assert hydration[ "history_n" ] >= 1, (
        "the history bucket must hold real rows from /api/job-history "
        f"(swallowed-empty-catch repro is 0); got { hydration['history_n'] }"
    )

    # --- DOM corroboration: hydrated rows actually paint --------------------
    page.wait_for_selector( '[data-testid="multiplexer-jobs-pane"]', timeout=10_000 )
    card_count = page.locator( "#jobs-buckets-container .job-card" ).count()
    assert card_count >= 1, (
        "the jobs-pane must render .job-card elements for hydrated history "
        f"rows (store reported { hydration['history_n'] } rows); got { card_count }"
    )
