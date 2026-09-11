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


def test_focus_click_sets_attribute_contract_and_only_the_toggle_exits( page ):
    """
    Ensures:
        - Clicking icon A enters focus: toggle data-focus-active="true",
          icon A data-focused="true", card B data-focus-hidden="true",
          card A NOT hidden
        - Clicking icon A again does nothing (row d04ff119, legacy parity)
        - Clicking the toggle exits: all three attribute surfaces clear
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

    # Row d04ff119: a second click on the focused icon does nothing (legacy); the
    # toggle is the only way out. Until 09-11 this test expected the click to exit.
    _icon( page, SENDER_A ).click()
    page.wait_for_timeout( 300 )   # give an (incorrect) exit time to render
    assert page.locator( '#cc-strip-toggle[data-focus-active="true"]' ).count() == 1, \
        "clicking the focused icon must not exit focus"
    assert _icon( page, SENDER_A ).get_attribute( "data-focused" ) == "true"

    page.locator( "#cc-strip-toggle" ).click()
    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="false"]', timeout=2_000 )
    assert _icon( page, SENDER_A ).get_attribute( "data-focused" ) is None
    assert page.locator( card_b ).get_attribute( "data-focus-hidden" ) is None, \
        "exiting focus must reveal all cards"


# Emit a task message with its own id_hash, so repeated arrivals from one sender are
# distinct rows (the _EMIT_MESSAGE_JS id is per sender, so a second one is a duplicate).
_EMIT_ARRIVAL_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : args.id_hash,
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

# What the browser actually paints for an icon: the ::after count and display, and the
# icon's own animation. Unit tests read attributes; this reads computed style, which is
# the only thing that shows whether a stylesheet the page links draws them.
_PAINTED_BADGE_JS = """
( sel ) => {
    const icon = document.querySelector( sel );
    if ( !icon ) return null;
    const after = getComputedStyle( icon, '::after' );
    return {
        unread         : icon.getAttribute( 'data-unread' ),
        count_attr     : icon.getAttribute( 'data-unread-count' ),
        after_content  : after.content,
        after_display  : after.display,
        animation_name : getComputedStyle( icon ).animationName,
    };
}
"""

MANAGER = { "name": "Tiberius", "icon": "👑", "color": "#3F51B5" }


def _arrive( page, sender_id: str, n: int ):
    page.evaluate( _EMIT_ARRIVAL_JS, {
        "id_hash"   : f"unread-{ sender_id }-{ n }",
        "message"   : f"arrival { n } from { sender_id }",
        "sender_id" : sender_id,
        "ts"        : f"2026-06-11T18:1{ n }:00.000Z",
    } )


def _painted( page, sender_id: str ):
    return page.evaluate( _PAINTED_BADGE_JS, f'#cc-strip-icons .cc-strip-icon[data-sender-id="{sender_id}"]' )


def _focus_on_a_with_b_hidden( page, b_extra: dict | None = None ):
    _open( page )
    _assign( page, SENDER_A, name="Cheech" )
    page.evaluate( _EMIT_STATE_UPDATE_JS, {
        "type"      : "voice_persona_assigned",
        "sender_id" : SENDER_B,
        "ts"        : "2026-06-11T18:00:30.000Z",
        "extra"     : dict( { "voice_persona": {
            "name"        : "Rachel",
            "voice_id"    : f"vid_{SENDER_B}",
            "icon"        : "🌿",
            "color"       : "#B39DDB",
            "borrowed"    : False,
            "assigned_at" : "2026-06-11T18:00:30.000Z",
        } }, **( b_extra or {} ) ),
    } )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_B}"]', timeout=3_000 )
    _icon( page, SENDER_A ).click()
    page.wait_for_selector( '#cc-strip-toggle[data-focus-active="true"]', timeout=2_000 )


def test_hidden_session_arrivals_paint_a_pulsing_count( page ):
    """
    Ensures:
        - With focus on A, two messages from B paint B's badge: the computed
          ::after content is "2" and the icon's computed animation-name is
          cc-strip-icon-pulse (row d04ff119; the rules must come from a sheet
          multiplexer.html links, which is what failed in Chrome on 09-11)
        - Before any arrival B paints no badge (the control: computed style is
          not "2" by accident)
    """
    _focus_on_a_with_b_hidden( page )
    before = _painted( page, SENDER_B )
    assert before[ "unread" ] is None and before[ "animation_name" ] != "cc-strip-icon-pulse", before

    _arrive( page, SENDER_B, 1 )
    _arrive( page, SENDER_B, 2 )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_B}"][data-unread-count="2"]', timeout=3_000 )

    after = _painted( page, SENDER_B )
    assert after[ "after_content" ] == '"2"', f"the count is set but not drawn: { after }"
    assert after[ "after_display" ] != "none", after
    assert after[ "animation_name" ] == "cc-strip-icon-pulse", f"the icon does not pulse: { after }"
    assert _painted( page, SENDER_A )[ "unread" ] is None, "the focused session never counts its own messages"


def test_a_workers_badge_pulses_without_drawing_an_empty_circle( page ):
    """
    Ensures:
        - A managed worker (manager_persona on its assignment) hidden by focus
          pulses on arrival but carries no count attribute, and its ::after
          computes to display none, so no empty red circle is drawn
    """
    _focus_on_a_with_b_hidden( page, b_extra={ "payload": { "manager_persona": MANAGER } } )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_B}"][data-has-manager="true"]', timeout=3_000 )

    _arrive( page, SENDER_B, 1 )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_B}"][data-unread="true"]', timeout=3_000 )

    painted = _painted( page, SENDER_B )
    assert painted[ "count_attr" ] is None, painted
    assert painted[ "after_display" ] == "none", f"a worker's empty circle is drawn: { painted }"
    assert painted[ "animation_name" ] == "cc-strip-icon-pulse", painted
