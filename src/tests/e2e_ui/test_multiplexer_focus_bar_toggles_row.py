"""
E2E: the multiplexer's Focus, All and Keep place toggles have a row of their own.

Requires:
    - The :8000 test container, and the test-hook login variables set.

Ensures:
    - The three toggles share one row inside the focus bar.
    - That row sits below the persona badges, inside the focus bar.
    - Each toggle is as tall as a persona badge.
"""

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

SENDER_A = "toggles-row-a"

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
        source : 'e2e-toggles-row',
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


TOGGLE_IDS = [ "cc-strip-toggle", "cc-hide-inactive-toggle", "cc-keep-place-toggle" ]

_GEOMETRY_JS = """
( ids ) => {
    const box = ( el ) => { const r = el.getBoundingClientRect(); return { top : r.top, bottom : r.bottom }; };
    return {
        icons   : box( document.getElementById( "cc-strip-icons" ) ),
        row     : box( document.getElementById( "cc-strip-toggles" ) ),
        strip   : box( document.getElementById( "cc-session-strip" ) ),
        toggles : ids.map( ( id ) => ( { id : id, parent : document.getElementById( id ).parentElement.id, top : box( document.getElementById( id ) ).top } ) )
    };
}
"""


_HEIGHT_JS = """
( ids ) => {
    // A real persona badge, built the way the broadcast card builds one, so its height comes from the shipped CSS.
    const chip = document.createElement( "button" );
    chip.className = "broadcast-chip";
    chip.innerHTML = '<span class="broadcast-chip-icon">🌿</span><span>Cheech</span>';
    chip.style.cssText = "position:fixed;top:0;left:0;visibility:hidden";
    document.body.appendChild( chip );
    const badge = chip.getBoundingClientRect().height;
    chip.remove();
    return { badge : badge, toggles : ids.map( ( id ) => ( { id : id, height : document.getElementById( id ).getBoundingClientRect().height } ) ) };
}
"""


def _geometry( page ):
    _open( page )
    _assign( page, SENDER_A, name="Cheech" )
    page.wait_for_selector( "#cc-session-strip:not([hidden])", timeout=3_000 )
    page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{SENDER_A}"]', timeout=3_000 )
    return page.evaluate( _GEOMETRY_JS, TOGGLE_IDS )


def test_toggles_sit_on_their_own_row_below_the_badges( page ):
    """
    Ensures:
        - each toggle is in the toggles row, which starts at or below the badges
    """
    geo = _geometry( page )
    assert [ t[ "id" ] for t in geo[ "toggles" ] ] == TOGGLE_IDS
    for toggle in geo[ "toggles" ]:
        assert toggle[ "parent" ] == "cc-strip-toggles", f"{ toggle[ 'id' ] } is not in the toggles row"
        assert toggle[ "top" ] >= geo[ "icons" ][ "bottom" ] - 1, f"{ toggle[ 'id' ] } is not below the badges: { geo }"
    assert geo[ "row" ][ "top" ] >= geo[ "icons" ][ "bottom" ] - 1, f"the toggles row overlaps the badge row: { geo }"


def test_the_three_toggles_share_one_line_inside_the_focus_bar( page ):
    """
    Ensures:
        - the toggles line up and the row ends inside the focus bar
    """
    geo  = _geometry( page )
    tops = [ t[ "top" ] for t in geo[ "toggles" ] ]
    assert max( tops ) - min( tops ) < 2, f"the toggles are not on one line: { tops }"
    assert geo[ "row" ][ "bottom" ] <= geo[ "strip" ][ "bottom" ] + 1, "the toggles row spills out of the focus bar"


def test_each_toggle_is_as_tall_as_a_persona_badge( page ):
    """
    Ensures:
        - every toggle's height is within a tenth of a pixel of a persona badge's height
    """
    _geometry( page )
    got = page.evaluate( _HEIGHT_JS, TOGGLE_IDS )
    assert got[ "badge" ] > 0, f"the badge probe has no height: { got }"
    for toggle in got[ "toggles" ]:
        assert abs( toggle[ "height" ] - got[ "badge" ] ) < 0.1, f"{ toggle[ 'id' ] } is not as tall as a persona badge: { got }"
