"""
The stop poke switch, in both notification clients, against a real server (row 3526fb95).

Rick's ruling: a plain on/off toggle with a simple indicator in the toolbar of the legacy
client and the multiplexer; only an admin can flip it.

What only a real browser and a real server can show:
    - an admin's click reaches the endpoint, the switch file changes, and the settings
      loader the Stop hook uses then reports the poke as muted
    - the indicator in the OTHER client shows the new state on its next load
    - a signed-in user without the admin role sees the indicator on a disabled button

🔴 THIS TEST MOVES THE REAL SWITCH. Both rest containers mount the same host folder, so
the file the test server writes is the one every seat's Stop hook reads. The fixture
records the state it found and puts it back whatever happens; while the test runs (a few
seconds) the fleet's poke follows the test.

Venue: :8000 (scheduled). Listed in partition/half-a.txt.
"""

import json
import urllib.error
import urllib.request

import pytest

from lupin_cli.claude_code.hooks.lib.heartbeat_poke_mute import read_poke_mute, write_poke_mute
from .conftest import BASE_URL


NOTIFICATIONS_URL = f"{BASE_URL}/app/notifications?classic=1"
MULTIPLEXER_URL   = f"{BASE_URL}/app/multiplexer"
LEGACY_BUTTON     = '[data-testid="notifications-poke-mute"]'
MUX_BUTTON        = '[data-testid="multiplexer-poke-mute"]'
KNOWN             = "{sel}:not([data-muted='unknown'])"


def _server_state( page ):
    """What GET /api/heartbeat/poke-mute answers for this page's signed-in user."""
    token   = page.evaluate( 'localStorage.getItem( "lupin_access_token" )' )
    request = urllib.request.Request( f"{BASE_URL}/api/heartbeat/poke-mute",
                                      headers={ "Authorization": f"Bearer {token}" } )
    with urllib.request.urlopen( request, timeout=10 ) as response:
        return json.loads( response.read() )


@pytest.fixture
def switch_restored():
    """Start every test from 'poke on', and put back whatever the fleet had."""
    found = read_poke_mute()
    write_poke_mute( False, "e2e test_poke_mute_switch (setup)" )
    yield
    write_poke_mute( found[ "muted" ], found[ "set_by" ] or "e2e test_poke_mute_switch (restore)" )


def _wait_known( page, selector ):
    page.wait_for_selector( KNOWN.format( sel=selector ), timeout=15000 )
    return page.locator( selector )


def test_an_admin_mutes_from_the_legacy_client_and_the_multiplexer_shows_it( admin_page, switch_restored ):
    page = admin_page

    page.goto( NOTIFICATIONS_URL )
    legacy = _wait_known( page, LEGACY_BUTTON )
    assert legacy.get_attribute( "data-muted" ) == "false"
    assert legacy.is_enabled()

    legacy.click()
    page.wait_for_selector( f"{LEGACY_BUTTON}[data-muted='true']", timeout=10000 )

    served = _server_state( page )
    assert served[ "muted" ] is True
    assert read_poke_mute() == served, "the file the Stop hook reads must be the one the server wrote"

    page.goto( MULTIPLEXER_URL )
    mux = _wait_known( page, MUX_BUTTON )
    assert mux.get_attribute( "data-muted" ) == "true"
    assert mux.is_enabled()

    mux.click()
    page.wait_for_selector( f"{MUX_BUTTON}[data-muted='false']", timeout=10000 )
    assert _server_state( page )[ "muted" ] is False
    assert read_poke_mute()[ "muted" ] is False

    page.goto( NOTIFICATIONS_URL )
    assert _wait_known( page, LEGACY_BUTTON ).get_attribute( "data-muted" ) == "false"


def test_a_user_without_the_admin_role_sees_the_indicator_and_cannot_flip_it( logged_in_page, switch_restored ):
    page = logged_in_page
    write_poke_mute( True, "e2e test_poke_mute_switch (muted for the non-admin view)" )

    for url, selector in ( ( NOTIFICATIONS_URL, LEGACY_BUTTON ), ( MULTIPLEXER_URL, MUX_BUTTON ) ):
        page.goto( url )
        button = _wait_known( page, selector )
        assert button.get_attribute( "data-muted" ) == "true", url
        assert button.is_disabled(), url

    token   = page.evaluate( 'localStorage.getItem( "lupin_access_token" )' )
    request = urllib.request.Request(
        f"{BASE_URL}/api/heartbeat/poke-mute", method="PUT", data=json.dumps( { "muted": False } ).encode(),
        headers={ "Authorization": f"Bearer {token}", "Content-Type": "application/json" } )
    with pytest.raises( urllib.error.HTTPError ) as refused:
        urllib.request.urlopen( request, timeout=10 )
    assert refused.value.code == 403
    assert read_poke_mute()[ "muted" ] is True
