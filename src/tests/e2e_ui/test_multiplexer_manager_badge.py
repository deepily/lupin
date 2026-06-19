#!/usr/bin/env python3
"""
E2E — Multiplexer Lane B WP9: manager-lineage badge (F11) — live + cold-reload.

Exercises the lineage badge end-to-end: `voice_persona_assigned` carrying
`payload.manager_persona` paints a `.cc-strip-manager-badge` child on the
strip icon (initial, "Spawned by <name>" title, --manager-color); the apply
is SINGLE + IDEMPOTENT (the a9ea8ab lesson — re-applies must never stack
badges); a manager-less re-assign CLEARS the badge; and the WP9 cold-reload
path hydrates icons + badges from a stubbed
GET /api/notifications/senders-visible/{email} snapshot with zero live events.

Assertions anchor on badge CHILD COUNT (the stacking regression), attribute
values (data-has-manager), title text, and the --manager-color custom
property — not bare badge presence.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_manager_badge.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_manager_badge.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

HYDRATION_ROUTE = "**/api/notifications/senders-visible/**"

SENDER_A = "wp9-badge-a"

_EMIT_ASSIGNED_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    const notification = {
        type          : 'voice_persona_assigned',
        sender_id     : args.sender_id,
        timestamp     : args.ts,
        voice_persona : {
            name        : args.name,
            voice_id    : 'vid_' + args.sender_id,
            icon        : '🧭',
            color       : '#90CAF9',
            borrowed    : false,
            assigned_at : args.ts,
        },
    };
    if ( args.manager !== null ) {
        notification.payload = { manager_persona: args.manager };
    }
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: notification },
        source  : 'e2e-manager-badge',
        ts      : Date.now(),
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


def _open( page, hydration_records: list[ dict ] | None = None ):
    """Seed auth, optionally stub the WP9 cold-reload hydration endpoint,
    navigate, wait for the test hook."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )

    if hydration_records is not None:
        def _hydration_handler( route ):
            route.fulfill( status=200, content_type="application/json", body=json.dumps( hydration_records ) )
        page.route( HYDRATION_ROUTE, _hydration_handler )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _assign( page, sender_id: str, name: str, manager: dict | None, ts: str = "2026-06-11T18:00:00.000Z" ):
    page.evaluate( _EMIT_ASSIGNED_JS, {
        "sender_id" : sender_id,
        "name"      : name,
        "manager"   : manager,
        "ts"        : ts,
    } )


def _icon_selector( sender_id: str ) -> str:
    return f'#cc-strip-icons .cc-strip-icon[data-sender-id="{sender_id}"]'


def _badge_surfaces( page, sender_id: str ) -> dict:
    return page.evaluate(
        """( sel ) => {
            const icon = document.querySelector( sel );
            if ( !icon ) return null;
            const badges = icon.querySelectorAll( '.cc-strip-manager-badge' );
            const badge  = badges.length > 0 ? badges[ 0 ] : null;
            return {
                badge_count   : badges.length,
                has_manager   : icon.getAttribute( 'data-has-manager' ),
                title         : badge ? badge.getAttribute( 'title' ) : null,
                initial       : badge ? badge.textContent : null,
                manager_color : badge ? badge.style.getPropertyValue( '--manager-color' ) : null,
            };
        }""",
        _icon_selector( sender_id ),
    )


TIBERIUS = { "name": "Tiberius", "icon": "👑", "color": "#3F51B5" }


def test_live_assignment_with_manager_paints_lineage_badge( page ):
    """
    Ensures:
        - payload.manager_persona on a live assignment paints exactly one
          .cc-strip-manager-badge whose initial, "Spawned by" title, and
          --manager-color all reflect the manager (element-level anchors)
        - data-has-manager="true" on the icon
    """
    _open( page )
    _assign( page, SENDER_A, name="Worker", manager=TIBERIUS )
    page.wait_for_selector( f'{_icon_selector( SENDER_A )} .cc-strip-manager-badge', timeout=3_000 )

    s = _badge_surfaces( page, SENDER_A )
    assert s is not None, "icon must exist"
    assert s[ "badge_count" ]   == 1
    assert s[ "has_manager" ]   == "true"
    assert s[ "initial" ]       == "T"
    assert s[ "title" ]         == "Spawned by Tiberius"
    assert s[ "manager_color" ] == "#3F51B5"


def test_reapply_is_single_and_idempotent_never_stacks( page ):
    """
    Ensures:
        - Re-delivering the manager-carrying assignment 3× leaves exactly ONE
          badge child (the a9ea8ab single-idempotent-apply lesson: every
          re-apply removes the existing badge before re-adding)
    """
    _open( page )
    for _ in range( 3 ):
        _assign( page, SENDER_A, name="Worker", manager=TIBERIUS )
    page.wait_for_selector( f'{_icon_selector( SENDER_A )} .cc-strip-manager-badge', timeout=3_000 )
    page.wait_for_timeout( 300 )   # allow any (incorrect) stacked badges to render

    s = _badge_surfaces( page, SENDER_A )
    assert s[ "badge_count" ] == 1, f"badge must never stack; found {s[ 'badge_count' ]}"
    assert s[ "title" ] == "Spawned by Tiberius"


def test_managerless_reassign_clears_badge( page ):
    """
    Ensures:
        - A subsequent assignment WITHOUT manager_persona clears the badge
          (count 0) and removes data-has-manager — lineage is current-state,
          not sticky
    """
    _open( page )
    _assign( page, SENDER_A, name="Worker", manager=TIBERIUS )
    page.wait_for_selector( f'{_icon_selector( SENDER_A )} .cc-strip-manager-badge', timeout=3_000 )

    _assign( page, SENDER_A, name="Worker", manager=None )
    page.wait_for_function(
        """( sel ) => {
            const icon = document.querySelector( sel );
            return icon && icon.querySelectorAll( '.cc-strip-manager-badge' ).length === 0;
        }""",
        arg=_icon_selector( SENDER_A ),
        timeout=2_000,
    )

    s = _badge_surfaces( page, SENDER_A )
    assert s[ "badge_count" ] == 0
    assert s[ "has_manager" ] is None, "data-has-manager must be removed with the badge"


def test_cold_reload_hydration_paints_icon_and_badge_without_live_events( page ):
    """
    Ensures:
        - The WP9 cold-reload path: with senders-visible stubbed to return a
          persona + manager_persona record, a FRESH page load paints the strip
          icon AND its lineage badge from hydration alone (zero live events)
    """
    records = [ {
        "sender_id"     : SENDER_A,
        "voice_persona" : {
            "name"        : "Worker",
            "voice_id"    : "vid_wp9",
            "icon"        : "🧭",
            "color"       : "#90CAF9",
            "borrowed"    : False,
            "assigned_at" : "2026-06-11T17:00:00.000Z",
        },
        "manager_persona" : TIBERIUS,
    } ]
    _open( page, hydration_records=records )

    page.wait_for_selector( f'{_icon_selector( SENDER_A )} .cc-strip-manager-badge', timeout=5_000 )

    s = _badge_surfaces( page, SENDER_A )
    assert s[ "badge_count" ]   == 1
    assert s[ "title" ]         == "Spawned by Tiberius"
    assert s[ "manager_color" ] == "#3F51B5"
    icon = page.locator( _icon_selector( SENDER_A ) )
    assert icon.get_attribute( "data-active" ) == "true"
    assert icon.locator( ".cc-strip-initial" ).text_content() == "W"
