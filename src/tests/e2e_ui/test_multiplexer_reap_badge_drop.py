#!/usr/bin/env python3
"""
E2E — Multiplexer Lane B WP7: session_reaped → strip-icon drop + recipient refresh (F9).

Exercises the reap path end-to-end via the test-hook EventBus:
`session_reaped` removes the strip icon ENTIRELY (vs. release, which merely
deactivates), auto-exits focus mode when the reaped session was the focused
one (the legacy `_removeStripIcon` parity branch in SessionStripRenderer),
and re-fires the commons persona-filter refresh — the Tiberius-arbitrated
WP7 contract: CommonsActivityRenderer re-fetches
`/api/cosa-voice/voice-persona/pool` on every `store_session_strip_changed`,
so a just-reaped peer disappears from the recipient dropdown live.

Assertions anchor on icon NON-existence by keyed selector, the focus-toggle's
data-focus-active value + card un-hiding, and the dropdown's actual <option>
values after a re-stubbed pool fetch — not bare element presence.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_reap_badge_drop.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_reap_badge_drop.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

POOL_ROUTE = "**/api/cosa-voice/voice-persona/pool"

SENDER_A = "wp7-reap-a"
SENDER_B = "wp7-reap-b"

_EMIT_STATE_UPDATE_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: Object.assign(
            { type: args.type, sender_id: args.sender_id, timestamp: args.ts },
            args.extra || {}
        ) },
        source : 'e2e-reap',
        ts     : Date.now(),
    });
    return true;
}
"""

_EMIT_MESSAGE_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'n-' + args.sender_id,
            message   : args.message,
            sender_id : args.sender_id,
            timestamp : args.ts,
            type      : 'task',
        } },
        source : 'e2e-reap',
        ts     : Date.now(),
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


def _pool_body( persona_names: list[ str ] ) -> str:
    return json.dumps( {
        "pool"            : [ { "name": n, "icon": "🛰️", "display_name": n.capitalize() } for n in persona_names ],
        "active_sessions" : [ { "persona_name": n } for n in persona_names ],
    } )


def _open( page, pool_personas: list[ str ] | None = None ):
    """Seed auth, stub the persona-pool endpoint (mutable via returned state dict),
    navigate, wait for the test hook.

    Returns a dict whose "personas" key the test can mutate — the route handler
    reads it on EVERY fetch, so re-stubbing is a plain assignment.
    """
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )

    state = { "personas": pool_personas if pool_personas is not None else [], "fetch_count": 0 }

    def _pool_handler( route ):
        state[ "fetch_count" ] += 1
        route.fulfill( status=200, content_type="application/json", body=_pool_body( state[ "personas" ] ) )

    page.route( POOL_ROUTE, _pool_handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    return state


def _assign( page, sender_id: str, name: str, ts: str = "2026-06-11T18:00:00.000Z" ):
    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type"      : "voice_persona_assigned",
        "sender_id" : sender_id,
        "ts"        : ts,
        "extra"     : { "voice_persona": {
            "name"        : name,
            "voice_id"    : f"vid_{sender_id}",
            "icon"        : "🛰️",
            "color"       : "#80CBC4",
            "borrowed"    : False,
            "assigned_at" : ts,
        } },
    } )


def _reap( page, sender_id: str, ts: str = "2026-06-11T18:10:00.000Z" ):
    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type"      : "session_reaped",
        "sender_id" : sender_id,
        "ts"        : ts,
        "extra"     : {},
    } )


def _icon_selector( sender_id: str ) -> str:
    return f'#cc-strip-icons .cc-strip-icon[data-sender-id="{sender_id}"]'


def test_reap_drops_icon_entirely_release_does_not( page ):
    """
    Ensures:
        - session_reaped REMOVES the sender's icon from the strip (count 0),
          while a sibling released-not-reaped sender keeps its icon — the two
          terminal states stay distinguishable
    """
    _open( page )
    _assign( page, SENDER_A, name="Apollo" )
    _assign( page, SENDER_B, name="Boris" )
    page.wait_for_selector( _icon_selector( SENDER_B ), timeout=3_000 )

    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type": "voice_persona_released", "sender_id": SENDER_B,
        "ts": "2026-06-11T18:09:00.000Z", "extra": {},
    } )
    _reap( page, SENDER_A )

    page.wait_for_function(
        "( sel ) => document.querySelectorAll( sel ).length === 0",
        arg=_icon_selector( SENDER_A ),
        timeout=2_000,
    )
    assert page.locator( _icon_selector( SENDER_A ) ).count() == 0, "reap must drop the icon"
    released = page.locator( _icon_selector( SENDER_B ) )
    assert released.count() == 1, "release must keep the icon"
    assert released.get_attribute( "data-active" ) == "false"


def test_reap_of_focused_session_auto_exits_focus( page ):
    """
    Ensures:
        - Reaping the FOCUSED session auto-exits focus mode: the toggle's
          data-focus-active flips to "false" and other cards lose
          data-focus-hidden (nobody is stranded focused on a dead session)
    """
    _open( page )
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_A, "message": "from A", "ts": "2026-06-11T18:00:00.000Z" } )
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_B, "message": "from B", "ts": "2026-06-11T18:01:00.000Z" } )
    _assign( page, SENDER_A, name="Apollo" )
    _assign( page, SENDER_B, name="Boris" )
    page.wait_for_selector( _icon_selector( SENDER_B ), timeout=3_000 )
    card_b = f'#notifications-pane .sender-card[data-sender-id="{SENDER_B}"]'
    page.wait_for_selector( card_b, timeout=3_000 )

    page.locator( _icon_selector( SENDER_A ) ).click()
    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="true"]', timeout=2_000 )
    assert page.locator( card_b ).get_attribute( "data-focus-hidden" ) == "true"

    _reap( page, SENDER_A )

    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="false"]', timeout=2_000 )
    assert page.locator( card_b ).get_attribute( "data-focus-hidden" ) is None, \
        "auto-exit must un-hide the surviving cards"
    assert page.locator( _icon_selector( SENDER_A ) ).count() == 0


def test_reap_refreshes_commons_persona_dropdown( page ):
    """
    Ensures:
        - The WP7 recipient-refresh half: a strip change re-fires the persona
          pool fetch, and the dropdown's actual <option> values track the
          (re-stubbed) pool — the reaped peer's persona disappears live
    """
    state = _open( page, pool_personas=[ "apollo", "boris" ] )
    _assign( page, SENDER_A, name="Apollo" )
    _assign( page, SENDER_B, name="Boris" )

    # The assignment-driven refresh lands both personas in the dropdown.
    page.wait_for_function(
        """() => {
            const sel = document.querySelector( '#commons-activity-filter-persona' );
            if ( !sel ) return false;
            const values = Array.from( sel.options ).map( o => o.value );
            return values.includes( 'apollo' ) && values.includes( 'boris' );
        }""",
        timeout=5_000,
    )

    # Server-side, Apollo's session dies → pool now reports only Boris. The
    # reap event is what must trigger the re-fetch that notices.
    state[ "personas" ] = [ "boris" ]
    fetches_before = state[ "fetch_count" ]
    _reap( page, SENDER_A )

    page.wait_for_function(
        """() => {
            const sel = document.querySelector( '#commons-activity-filter-persona' );
            if ( !sel ) return false;
            const values = Array.from( sel.options ).map( o => o.value );
            return !values.includes( 'apollo' ) && values.includes( 'boris' );
        }""",
        timeout=5_000,
    )
    assert state[ "fetch_count" ] > fetches_before, \
        "reap must re-fire the persona-pool fetch (store_session_strip_changed contract)"


def test_reap_of_untracked_sender_is_silent_noop( page ):
    """
    Ensures:
        - session_reaped for a sender that never had a persona neither crashes
          nor disturbs existing icons (store no-op branch), and no console
          error is emitted
    """
    _open( page )
    errors: list[ str ] = []
    page.on( "console", lambda m: errors.append( m.text ) if m.type == "error" else None )

    _assign( page, SENDER_A, name="Apollo" )
    page.wait_for_selector( _icon_selector( SENDER_A ), timeout=3_000 )

    _reap( page, "wp7-never-tracked" )
    page.wait_for_timeout( 300 )

    assert page.locator( _icon_selector( SENDER_A ) ).count() == 1, \
        "untracked reap must not disturb existing icons"
    assert errors == [], f"untracked reap must be silent; console errors: {errors}"
