#!/usr/bin/env python3
"""
E2E — Multiplexer Lane B WP2: CC-session strip subsystem (keystone).

Exercises SessionStripStore + SessionStripRenderer end-to-end via the
test-hook EventBus: icon add on `voice_persona_assigned` (initial, title,
persona color, data-active), in-place idempotent re-assign (no duplicate
icons), `voice_persona_released` → inactive-but-visible, the hide-inactive
filter toggle, and the focus-mode attribute mechanics (data-focused /
data-focus-active / data-focus-hidden). The WP10 focus HEIGHT contract (80vh)
lives in test_cc_session_strip_and_focus.py::TestMultiplexerFocusHeight80vh;
`session_reaped` icon-drop lives in test_multiplexer_reap_badge_drop.py (WP7).

Assertions anchor on the store/renderer's actual element surface — attribute
values, `.cc-strip-initial` text, the computed `--persona-color` custom
property — not bare element presence (the hasAttribute false-pass lesson).

Wire contract: strip state-updates ride `notification_queue_update` with a
`notification.type` discriminator (SessionStripStore.ts STRIP_STATE_TYPES).

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_session_strip.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_session_strip.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

SENDER_A = "wp2-strip-a"
SENDER_B = "wp2-strip-b"

# Emit one strip state-update through the test-hook EventBus. `extra` merges
# into the notification envelope (voice_persona, payload, ...).
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
        source : 'e2e-session-strip',
        ts     : Date.now(),
    });
    return true;
}
"""

# Emit a plain task notification — builds the sender card (NOT a strip icon;
# the strip populates ONLY from STRIP_STATE_TYPES).
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
        source : 'e2e-session-strip',
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


def _open( page ):
    """Seed auth on the managed page fixture, navigate, wait for the test hook."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _assign( page, sender_id: str, name: str, color: str = "#FFCC80", icon: str = "🌿", ts: str = "2026-06-11T18:00:00.000Z" ):
    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type"      : "voice_persona_assigned",
        "sender_id" : sender_id,
        "ts"        : ts,
        "extra"     : { "voice_persona": {
            "name"        : name,
            "voice_id"    : f"vid_{sender_id}",
            "icon"        : icon,
            "color"       : color,
            "borrowed"    : False,
            "assigned_at" : ts,
        } },
    } )


def _release( page, sender_id: str, ts: str = "2026-06-11T18:05:00.000Z" ):
    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type"      : "voice_persona_released",
        "sender_id" : sender_id,
        "ts"        : ts,
        "extra"     : {},
    } )


def _icon( page, sender_id: str ):
    return page.locator( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{sender_id}"]' )


def test_assign_adds_icon_with_persona_surfaces( page ):
    """
    Ensures:
        - voice_persona_assigned reveals the strip and adds ONE icon whose
          data-active, .cc-strip-initial text, title, and --persona-color all
          reflect the assigned persona (element-level anchors, not presence)
    """
    _open( page )
    _assign( page, SENDER_A, name="Cheech", color="#FFCC80" )

    page.wait_for_selector( "#cc-session-strip:not([hidden])", timeout=3_000 )
    icon = _icon( page, SENDER_A )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]', timeout=3_000 )

    assert icon.count() == 1
    assert icon.get_attribute( "data-active" ) == "true"
    assert icon.get_attribute( "title" ) == "Cheech"
    assert icon.locator( ".cc-strip-initial" ).text_content() == "C"
    persona_color = page.evaluate(
        "( sel ) => document.querySelector( sel ).style.getPropertyValue( '--persona-color' )",
        f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]',
    )
    assert persona_color == "#FFCC80", f"--persona-color must carry the persona color; got {persona_color!r}"


def test_reassign_updates_in_place_no_duplicate_icon( page ):
    """
    Ensures:
        - A second voice_persona_assigned for the SAME sender updates the
          existing icon in place (initial + title track the new persona) and
          never duplicates it (keyed-merge idempotency)
    """
    _open( page )
    _assign( page, SENDER_A, name="Cheech" )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]', timeout=3_000 )

    _assign( page, SENDER_A, name="Rachel", color="#B39DDB" )
    page.wait_for_function(
        """( sel ) => {
            const el = document.querySelector( sel );
            return el && el.getAttribute( 'title' ) === 'Rachel';
        }""",
        arg=f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]',
        timeout=2_000,
    )

    icon = _icon( page, SENDER_A )
    assert icon.count() == 1, "re-assignment must update in place, never duplicate"
    assert icon.locator( ".cc-strip-initial" ).text_content() == "R"
    assert icon.get_attribute( "data-active" ) == "true"


def test_release_keeps_icon_but_flips_inactive( page ):
    """
    Ensures:
        - voice_persona_released keeps the icon visible (retains last-known
          persona) but flips data-active to "false"
        - With hide-inactive OFF (default) the icon carries NO
          data-inactive-hidden attribute
    """
    _open( page )
    _assign( page, SENDER_A, name="Cheech" )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]', timeout=3_000 )

    _release( page, SENDER_A )
    page.wait_for_function(
        """( sel ) => {
            const el = document.querySelector( sel );
            return el && el.getAttribute( 'data-active' ) === 'false';
        }""",
        arg=f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]',
        timeout=2_000,
    )

    icon = _icon( page, SENDER_A )
    assert icon.count() == 1, "release must NOT remove the icon (that's reap's job)"
    assert icon.get_attribute( "data-inactive-hidden" ) is None, \
        "hide-inactive is OFF by default — inactive icon must remain unfiltered"


def test_hide_inactive_toggle_filters_only_inactive_icons( page ):
    """
    Ensures:
        - Clicking #cc-hide-inactive-toggle flips its data-hide-inactive to
          "true" and stamps data-inactive-hidden ONLY on inactive icons
        - Re-assigning the released sender reactivates it live (filter
          un-hides it without touching the toggle)
    """
    _open( page )
    _assign( page, SENDER_A, name="Cheech" )
    _assign( page, SENDER_B, name="Tiberius", color="#3F51B5" )
    _release( page, SENDER_A )
    page.wait_for_function(
        """( sel ) => {
            const el = document.querySelector( sel );
            return el && el.getAttribute( 'data-active' ) === 'false';
        }""",
        arg=f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]',
        timeout=2_000,
    )

    page.locator( "#cc-hide-inactive-toggle" ).click()
    page.wait_for_selector( '#cc-hide-inactive-toggle[data-hide-inactive="true"]', timeout=2_000 )

    assert _icon( page, SENDER_A ).get_attribute( "data-inactive-hidden" ) == "true", \
        "inactive icon must be filtered when hide-inactive is ON"
    assert _icon( page, SENDER_B ).get_attribute( "data-inactive-hidden" ) is None, \
        "active icon must never be filtered"

    # Re-assignment reactivates: the filter releases the icon with the toggle still ON.
    _assign( page, SENDER_A, name="Cheech" )
    page.wait_for_function(
        """( sel ) => {
            const el = document.querySelector( sel );
            return el
                && el.getAttribute( 'data-active' ) === 'true'
                && !el.hasAttribute( 'data-inactive-hidden' );
        }""",
        arg=f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]',
        timeout=2_000,
    )
    assert page.locator( '#cc-hide-inactive-toggle[data-hide-inactive="true"]' ).count() == 1, \
        "reactivation must not silently flip the user's toggle"


def test_focus_click_sets_attribute_contract_and_second_click_exits( page ):
    """
    Ensures:
        - Clicking icon A enters focus: toggle data-focus-active="true",
          icon A data-focused="true", card B data-focus-hidden="true",
          card A NOT hidden
        - Clicking icon A again exits: all three attribute surfaces clear
    """
    _open( page )
    # Cards must exist for the focus-hidden pass to have a surface to stamp.
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_A, "message": "from A", "ts": "2026-06-11T18:00:00.000Z" } )
    page.evaluate( _EMIT_MESSAGE_JS, { "sender_id": SENDER_B, "message": "from B", "ts": "2026-06-11T18:01:00.000Z" } )
    _assign( page, SENDER_A, name="Cheech" )
    _assign( page, SENDER_B, name="Tiberius", color="#3F51B5" )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_B}"]', timeout=3_000 )
    card_a = f'#notifications-pane .sender-card[data-sender-id="{SENDER_A}"]'
    card_b = f'#notifications-pane .sender-card[data-sender-id="{SENDER_B}"]'
    page.wait_for_selector( card_b, timeout=3_000 )

    _icon( page, SENDER_A ).click()
    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="true"]', timeout=2_000 )

    assert _icon( page, SENDER_A ).get_attribute( "data-focused" ) == "true"
    assert _icon( page, SENDER_B ).get_attribute( "data-focused" ) is None
    assert page.locator( card_b ).get_attribute( "data-focus-hidden" ) == "true", \
        "non-focused card must be focus-hidden"
    assert page.locator( card_a ).get_attribute( "data-focus-hidden" ) is None, \
        "focused card must stay visible"

    # Second click on the focused icon exits focus and clears every surface.
    _icon( page, SENDER_A ).click()
    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="false"]', timeout=2_000 )
    assert _icon( page, SENDER_A ).get_attribute( "data-focused" ) is None
    assert page.locator( card_b ).get_attribute( "data-focus-hidden" ) is None, \
        "exiting focus must reveal all cards"
