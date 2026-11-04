"""
E2E: the multiplexer's Keep place toggle looks like the Active toggle, on and off.

Requires:
    - The :8000 test container, and the test-hook login variables set.

Ensures:
    - A click flips data-keep-place and aria-checked on the toggle.
    - On, the toggle's computed background is the Active toggle's on background.
    - Off, the toggle has the same background as the Active toggle when it is off.
    - Hovered, on and off, it has the same background as the Active toggle.
    - Snapshots of the toggles row, on and off.
"""

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

KEEP_ID   = "cc-keep-place-toggle"
ACTIVE_ID = "cc-hide-inactive-toggle"

_EMIT_PERSONA_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: { type: 'voice_persona_assigned', sender_id: args.sender_id, timestamp: args.ts,
            voice_persona: { name: 'Cheech', voice_id: 'vid', icon: '🌿', color: '#FFCC80', borrowed: false, assigned_at: args.ts } } },
        source : 'e2e-keep-place-style',
        ts     : Date.now(),
    });
}
"""

_STATE_JS  = "( id ) => { const el = document.getElementById( id ); return { keep : el.getAttribute( 'data-keep-place' ), checked : el.getAttribute( 'aria-checked' ) }; }"
_ATTR_JS   = "( [ id, name ] ) => document.getElementById( id ).getAttribute( name )"
_COLOUR_JS = "( id ) => getComputedStyle( document.getElementById( id ) ).backgroundColor"


def _login_tokens() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


@pytest.fixture
def strip_page( page ):
    """The multiplexer with one persona badge, so the focus bar and its toggles row show."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function( "() => window.__multiplexerTestHook !== undefined", timeout=10_000 )
    page.evaluate( _EMIT_PERSONA_JS, { "sender_id": "keep-place-style-a", "ts": "2026-11-03T18:00:00.000Z" } )
    page.wait_for_selector( "#cc-session-strip:not([hidden])", timeout=3_000 )
    return page


def _set( page, toggle_id: str, attribute: str, on: bool ):
    """Click the toggle until it reads the wanted state, then move the mouse away."""
    if ( page.evaluate( _ATTR_JS, [ toggle_id, attribute ] ) == "true" ) != on:
        page.click( f"#{ toggle_id }" )
    page.mouse.move( 0, 0 )
    page.wait_for_function( f"() => document.getElementById( '{ toggle_id }' ).getAttribute( '{ attribute }' ) === '{ str( on ).lower() }'" )
    page.wait_for_timeout( 400 )


def test_a_click_flips_the_attribute_and_aria_checked( strip_page ):
    """
    Ensures:
        - off to on to off, both attributes move together
    """
    page = strip_page
    _set( page, KEEP_ID, "data-keep-place", False )
    assert page.evaluate( _STATE_JS, KEEP_ID ) == { "keep": "false", "checked": "false" }
    page.click( f"#{ KEEP_ID }" )
    assert page.evaluate( _STATE_JS, KEEP_ID ) == { "keep": "true", "checked": "true" }
    page.click( f"#{ KEEP_ID }" )
    assert page.evaluate( _STATE_JS, KEEP_ID ) == { "keep": "false", "checked": "false" }


def test_keep_place_on_has_the_active_toggles_on_background( strip_page ):
    """
    Keep place matches Active, on and off.

    Ensures:
        - on, Keep place and Active have the same computed background
        - off, they have the same one too, and it differs from the on one
    """
    page = strip_page
    _set( page, KEEP_ID, "data-keep-place", False )
    _set( page, ACTIVE_ID, "data-hide-inactive", False )
    keep_off, active_off = page.evaluate( _COLOUR_JS, KEEP_ID ), page.evaluate( _COLOUR_JS, ACTIVE_ID )
    _set( page, KEEP_ID, "data-keep-place", True )
    _set( page, ACTIVE_ID, "data-hide-inactive", True )
    keep_on, active_on = page.evaluate( _COLOUR_JS, KEEP_ID ), page.evaluate( _COLOUR_JS, ACTIVE_ID )
    assert keep_off == active_off, f"off: keep { keep_off } vs active { active_off }"
    assert keep_on == active_on, f"on: keep { keep_on } vs active { active_on }"
    assert keep_on != keep_off, f"Keep place looks the same on and off: { keep_on }"


def _hovered_colour( page, toggle_id: str ) -> str:
    """Return the toggle's background with the mouse over it, once the transition has run."""
    page.hover( f"#{ toggle_id }" )
    page.wait_for_timeout( 400 )
    return page.evaluate( _COLOUR_JS, toggle_id )


def test_keep_place_hovered_has_the_active_toggles_hover_background( strip_page ):
    """
    Keep place matches Active under the mouse, on and off.

    Ensures:
        - on, hovering each gives the same computed background
        - off, hovering each gives the same computed background
    """
    page = strip_page
    for on in ( False, True ):
        _set( page, KEEP_ID, "data-keep-place", on )
        _set( page, ACTIVE_ID, "data-hide-inactive", on )
        keep, active = _hovered_colour( page, KEEP_ID ), _hovered_colour( page, ACTIVE_ID )
        assert keep == active, f"hover, on={ on }: keep { keep } vs active { active }"


@pytest.mark.parametrize( "state", [ "off", "on" ] )
def test_toggles_row_visual( strip_page, assert_snapshot, state ):
    """
    Ensures:
        - the toggles row matches its baseline with Keep place off and on
    """
    page = strip_page
    _set( page, KEEP_ID, "data-keep-place", state == "on" )
    assert_snapshot( page.locator( "#cc-strip-toggles" ), name=f"multiplexer_toggles_row_keep_place_{ state }.png" )
