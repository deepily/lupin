#!/usr/bin/env python3
"""
E2E — Multiplexer Lane B WP8: spin-up persona symmetry (F10).

Exercises the spawn-side symmetry of the strip: a `voice_persona_assigned`
delivered MORE THAN ONCE for the same sender (the spin-up double-fire race —
listener + hydration, or a re-broadcast) lands exactly ONE icon; and an
assignment re-fires the commons persona-filter refresh so a freshly-spawned
peer appears in the recipient dropdown live (the symmetric twin of WP7's
reap-side disappearance).

Assertions anchor on keyed icon COUNT (the exact duplicate-event case, beyond
the change-persona re-assign covered in test_multiplexer_session_strip.py),
strip ordering stability, and the dropdown's actual <option> values.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_spinup_symmetry.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_spinup_symmetry.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

POOL_ROUTE = "**/api/cosa-voice/voice-persona/pool"

SENDER_A = "wp8-spinup-a"
SENDER_B = "wp8-spinup-b"

_EMIT_ASSIGNED_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    for ( let i = 0; i < args.times; i++ ) {
        hook.eventBus.emit({
            type    : 'notification_queue_update',
            payload : { notification: {
                type          : 'voice_persona_assigned',
                sender_id     : args.sender_id,
                timestamp     : args.ts,
                voice_persona : {
                    name        : args.name,
                    voice_id    : 'vid_' + args.sender_id,
                    icon        : '🚀',
                    color       : args.color,
                    borrowed    : false,
                    assigned_at : args.ts,
                },
            } },
            source : 'e2e-spinup',
            ts     : Date.now(),
        });
    }
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


def _open( page, pool_personas: list[ str ] | None = None ):
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )

    state = { "personas": pool_personas if pool_personas is not None else [] }

    def _pool_handler( route ):
        body = json.dumps( {
            "pool"            : [ { "name": n, "icon": "🚀", "display_name": n.capitalize() } for n in state[ "personas" ] ],
            "active_sessions" : [ { "persona_name": n } for n in state[ "personas" ] ],
        } )
        route.fulfill( status=200, content_type="application/json", body=body )

    page.route( POOL_ROUTE, _pool_handler )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    return state


def _assign_n_times( page, sender_id: str, name: str, times: int, color: str = "#FFAB91", ts: str = "2026-06-11T18:00:00.000Z" ):
    page.evaluate( _EMIT_ASSIGNED_JS, {
        "sender_id" : sender_id,
        "name"      : name,
        "times"     : times,
        "color"     : color,
        "ts"        : ts,
    } )


def _icon_selector( sender_id: str ) -> str:
    return f'#cc-strip-icons .cc-strip-icon[data-sender-id="{sender_id}"]'


def test_duplicate_assignment_events_land_exactly_one_icon( page ):
    """
    Ensures:
        - The IDENTICAL voice_persona_assigned event delivered 3× (spin-up
          double-fire race) produces exactly one icon, with the persona
          surfaces intact (initial + data-active) — keyed-merge idempotency
          at the event level, not just the change-persona level
    """
    _open( page )
    _assign_n_times( page, SENDER_A, name="Nova", times=3 )

    page.wait_for_selector( _icon_selector( SENDER_A ), timeout=3_000 )
    page.wait_for_timeout( 300 )   # allow any (incorrect) trailing duplicates to render

    icons = page.locator( _icon_selector( SENDER_A ) )
    assert icons.count() == 1, "3 identical assignments must land exactly 1 icon"
    assert icons.get_attribute( "data-active" ) == "true"
    assert icons.locator( ".cc-strip-initial" ).text_content() == "N"


def test_duplicate_assignment_preserves_strip_ordering( page ):
    """
    Ensures:
        - Re-delivering A's assignment AFTER B joined does not re-order the
          strip: assigned_at is the chronological anchor and first-seen wins
          (icon order stays A, B)
    """
    _open( page )
    _assign_n_times( page, SENDER_A, name="Nova",  times=1, ts="2026-06-11T18:00:00.000Z" )
    _assign_n_times( page, SENDER_B, name="Orion", times=1, ts="2026-06-11T18:01:00.000Z" )
    page.wait_for_selector( _icon_selector( SENDER_B ), timeout=3_000 )

    # The spin-up re-broadcast: A's assignment arrives again, late.
    _assign_n_times( page, SENDER_A, name="Nova", times=1, ts="2026-06-11T18:00:00.000Z" )
    page.wait_for_timeout( 300 )

    order = page.evaluate(
        """() => Array.from(
            document.querySelectorAll( '#cc-strip-icons .cc-strip-icon' )
        ).map( el => el.getAttribute( 'data-sender-id' ) )"""
    )
    assert order == [ SENDER_A, SENDER_B ], \
        f"late duplicate assignment must not re-order the strip; got {order}"


def test_assignment_refreshes_commons_persona_dropdown( page ):
    """
    Ensures:
        - The WP8 recipient-refresh half (symmetric twin of WP7): a NEW
          assignment re-fires the persona-pool fetch and the freshly-spawned
          persona appears in the dropdown's actual <option> values live
    """
    state = _open( page, pool_personas=[ "nova" ] )
    _assign_n_times( page, SENDER_A, name="Nova", times=1 )

    page.wait_for_function(
        """() => {
            const sel = document.querySelector( '#commons-activity-filter-persona' );
            if ( !sel ) return false;
            return Array.from( sel.options ).map( o => o.value ).includes( 'nova' );
        }""",
        timeout=5_000,
    )

    # A new peer spins up server-side; its assignment event must drive the
    # dropdown refresh that surfaces it.
    state[ "personas" ] = [ "nova", "orion" ]
    _assign_n_times( page, SENDER_B, name="Orion", times=1, ts="2026-06-11T18:01:00.000Z" )

    page.wait_for_function(
        """() => {
            const sel = document.querySelector( '#commons-activity-filter-persona' );
            if ( !sel ) return false;
            const values = Array.from( sel.options ).map( o => o.value );
            return values.includes( 'nova' ) && values.includes( 'orion' );
        }""",
        timeout=5_000,
    )
