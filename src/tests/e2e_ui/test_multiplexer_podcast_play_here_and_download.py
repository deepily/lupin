"""
Play Here and Download on a finished podcast card in the multiplexer.

Before `podcastLinks.ts` existed, neither click was claimed. Play Here opened a plain tab. Download
navigated with no Authorization header, and the server answers that with 401.

The unit tests cover the decisions. This file drives the real click in a real browser.

No audio is bought and no file is read. The two URLs the clicks reach are answered by `page.route`
stubs, and the download stub records the headers it saw.

The new-tab probe is proven too. `test_the_tab_probe_sees_a_listen_tab` clicks a Listen link, which
nothing claims, and asserts the probe fires. A zero elsewhere then means something.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_a`, because the
`logged_in_page` fixture registers a user. The file is listed in `partition/half-a.txt`.
"""

import pytest

from .conftest import BASE_URL

LAYOUTS = [ "vertical", "horizontal" ]

_AUDIO_REL = "podcast/e2e-stub.mp3"
_ENC       = "podcast%2Fe2e-stub.mp3"
_PLAY_HREF     = f"/app/audio?path={_ENC}&embed=1"
_LISTEN_HREF   = f"/app/audio?path={_ENC}"
_DOWNLOAD_HREF = f"/api/io/file?path={_ENC}&download=true"


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )


def _set_layout( page, mode ):
    if page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) != mode:
        page.locator( "#layout-mode-toggle" ).click()
        page.wait_for_timeout( 100 )
    assert page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" ) == mode


def _stub_the_two_urls( page ):
    """Stub the player page and the file endpoint; return the Authorization headers the file saw."""
    seen = []

    def player( route ):
        route.fulfill( status=200, content_type="text/html", body="<!doctype html><title>stub player</title>" )

    def file_endpoint( route ):
        seen.append( route.request.headers.get( "authorization" ) )
        route.fulfill(
            status=200, body=b"stub-audio-bytes", content_type="audio/mpeg",
            headers={ "Content-Disposition": 'attachment; filename="e2e-stub.mp3"' },
        )

    page.route( "**/app/audio?**", player )
    page.route( "**/api/io/file?**", file_endpoint )
    return seen


def _plant_link( page, href, text ):
    """Plant a target=_blank anchor the way the card renders it, in the history column."""
    page.evaluate(
        """( [ href, text ] ) => {
            const container = document.querySelector( '.left-column .container' ) || document.body;
            const host = document.createElement( 'div' );
            host.className = 'sender-card';
            const a = document.createElement( 'a' );
            a.setAttribute( 'href', href );
            a.setAttribute( 'target', '_blank' );
            a.textContent = text;
            host.appendChild( a );
            container.appendChild( host );
        }""",
        [ href, text ],
    )
    return page.get_by_role( "link", name=text )


def _install_open_probe( page ):
    page.evaluate(
        "() => { window.__opens = []; const o = window.open; window.open = function ( ...a ) { window.__opens.push( a[ 0 ] ); return o.apply( this, a ); }; }"
    )


def _tabs_opened( page, pages_before ):
    """Both arms: window.open calls, and extra pages in the browser context."""
    opens = page.evaluate( "() => window.__opens" )
    return len( opens ) + ( len( page.context.pages ) - pages_before )


@pytest.mark.parametrize( "mode", LAYOUTS )
class TestMultiplexerPodcastLinks:

    def test_play_here_opens_the_floating_player_and_no_tab( self, logged_in_page, mode ):
        page = logged_in_page
        _open_multiplexer( page )
        _set_layout( page, mode )
        _stub_the_two_urls( page )
        _install_open_probe( page )
        pages_before = len( page.context.pages )

        _plant_link( page, _PLAY_HREF, "▶️ Play Here" ).click()

        overlay = page.locator( "[data-testid=podcast-overlay]" )
        overlay.wait_for( state="visible", timeout=5000 )
        assert overlay.locator( "iframe" ).get_attribute( "src" ) == _PLAY_HREF + "&autoplay=1"
        assert _tabs_opened( page, pages_before ) == 0, "Play Here must not open a tab"

        page.locator( "[data-testid=podcast-overlay-dismiss]" ).click()
        assert page.locator( "[data-testid=podcast-overlay]" ).count() == 0, "the X closes the player"

    def test_download_fetches_with_the_bearer_token_and_saves_the_file( self, logged_in_page, mode ):
        page = logged_in_page
        _open_multiplexer( page )
        _set_layout( page, mode )
        seen = _stub_the_two_urls( page )
        token = page.evaluate( "() => localStorage.getItem( 'lupin_access_token' )" )
        assert token, "the logged-in fixture must have left a token to send"

        link = _plant_link( page, _DOWNLOAD_HREF, "⬇️ Download" )
        with page.expect_download( timeout=10000 ) as info:
            link.click()

        assert info.value.suggested_filename == "e2e-stub.mp3"
        assert seen == [ f"Bearer {token}" ], "exactly one fetch, carrying the Bearer token"

    def test_the_tab_probe_sees_a_listen_tab( self, logged_in_page, mode ):
        page = logged_in_page
        _open_multiplexer( page )
        _set_layout( page, mode )
        _stub_the_two_urls( page )
        _install_open_probe( page )
        pages_before = len( page.context.pages )

        with page.context.expect_page( timeout=5000 ):
            _plant_link( page, _LISTEN_HREF, "🎧 Listen" ).click()

        assert _tabs_opened( page, pages_before ) >= 1, "the probe must see the Listen tab, or its zeros above mean nothing"
        assert page.locator( "[data-testid=podcast-overlay]" ).count() == 0, "Listen never opens the floating player"
