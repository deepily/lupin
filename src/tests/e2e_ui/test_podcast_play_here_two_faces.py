"""
Play Here widget, two faces, in both clients.

The widget shows the browser's own audio player and nothing else. The ⤢ button opens the full page in a new tab:
clean title, player, download, the script, the original document and the file details.

No audio is bought. The file endpoint is answered by a `page.route` stub on the browser context, so the new tab
is served by it too. The player page itself is the real one.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_b`. The file is listed in
`partition/half-b.txt`.
"""

import io
import wave

import pytest

from .conftest import BASE_URL

CLIENTS = [ "legacy", "multiplexer" ]

TITLE   = "Grading Your Own Exam: Construct Validity"
AUDIO   = "podcasts/u/2026.11.01-014849-grading-your-own-exam-construct-validit.mp3"
SCRIPT  = "podcasts/u/2026.11.01-014724-grading-your-own-exam-construct-validit-script.md"
SOURCE  = "io/deep-research/u/report.md"
PLAY    = (
    f"/app/audio?path={AUDIO}&script={SCRIPT}&source={SOURCE}"
    f"&title=Grading%20Your%20Own%20Exam%3A%20Construct%20Validity&embed=1"
)
OLD     = f"/app/audio?path={AUDIO}&embed=1"

OVERLAY = "[data-testid=podcast-overlay]"
FRAME   = "[data-testid=podcast-overlay-frame]"
EXPAND  = "[data-testid=podcast-overlay-expand]"
DISMISS = "[data-testid=podcast-overlay-dismiss]"


def _wav_bytes():
    buf = io.BytesIO()
    with wave.open( buf, "wb" ) as w:
        w.setnchannels( 1 )
        w.setsampwidth( 2 )
        w.setframerate( 8000 )
        w.writeframes( b"\x00\x00" * 16000 )
    return buf.getvalue()


def _stub_files( page ):
    """Answer every file read for the whole browser context, so a new tab gets the same answers."""
    wav = _wav_bytes()

    def file_endpoint( route ):
        path = route.request.url.split( "path=", 1 )[ 1 ].split( "&", 1 )[ 0 ]
        path = path.replace( "%2F", "/" )
        if path.endswith( ".mp3" ):
            route.fulfill( status=200, body=wav, content_type="audio/wav" )
        elif path == SCRIPT:
            route.fulfill( status=200, body="# Podcast: Grading\n\nThe script says **hello**.", content_type="text/plain" )
        elif path == SOURCE[ 3: ]:
            route.fulfill( status=200, body="# The original report\n\nBody text.", content_type="text/plain" )
        else:
            route.fulfill( status=404, body="", content_type="text/plain" )

    page.context.route( "**/api/io/file?**", file_endpoint )


def _open_client_and_click_play( page, client, href ):
    """Plant a Play Here link the way each client's card renders it, and click it."""
    if client == "legacy":
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        page.evaluate(
            """( href ) => {
                const host = document.createElement( 'div' );
                host.style.cssText = 'position:fixed;left:8px;bottom:8px;z-index:2147483647;background:#222;padding:8px;';
                host.innerHTML = window.notificationsUI.renderAbstractSection( '[▶️ Play Here](' + href + ')' );
                document.body.appendChild( host );
            }""",
            href,
        )
        page.get_by_role( "link", name="Play Here" ).click()
        page.evaluate( "() => document.querySelector( \"div[style*='2147483647']\" ).remove()" )
    else:
        page.goto( f"{BASE_URL}/app/multiplexer" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores && window.__multiplexerTestHook.stores.readingPane",
            timeout=15000,
        )
        page.evaluate(
            """( href ) => {
                const container = document.querySelector( '.left-column .container' ) || document.body;
                const host = document.createElement( 'div' );
                host.className = 'sender-card';
                host.id = 'planted-play-here';
                const a = document.createElement( 'a' );
                a.setAttribute( 'href', href );
                a.setAttribute( 'target', '_blank' );
                a.textContent = '▶️ Play Here';
                host.appendChild( a );
                container.appendChild( host );
            }""",
            href,
        )
        page.get_by_role( "link", name="Play Here" ).click()
        page.evaluate( "() => document.getElementById( 'planted-play-here' ).remove()" )
    page.locator( OVERLAY ).wait_for( state="visible", timeout=5000 )


@pytest.mark.parametrize( "client", CLIENTS )
class TestPlayHereTwoFaces:

    def test_the_widget_shows_only_the_native_audio_player( self, logged_in_page, client ):
        page = logged_in_page
        _stub_files( page )
        _open_client_and_click_play( page, client, PLAY )

        assert page.locator( ".podcast-overlay-title" ).inner_text() == TITLE
        frame = page.frame_locator( FRAME )
        frame.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        for absent in ( "h1", "a.audio-player-download", "details", ".audio-player-links" ):
            assert frame.locator( absent ).count() == 0, f"the mini face must not draw {absent}"
        assert frame.locator( "body" ).inner_text().strip() == "", "nothing but the player is visible text"
        assert page.locator( f"{OVERLAY} button" ).evaluate_all( "bs => bs.map( b => b.dataset.testid )" ) == [
            "podcast-overlay-expand", "podcast-overlay-dismiss",
        ]
        page.locator( DISMISS ).click()
        assert page.locator( OVERLAY ).count() == 0

    def test_the_audio_player_sits_directly_under_the_header_and_is_fully_visible( self, logged_in_page, client ):
        page = logged_in_page
        _stub_files( page )
        _open_client_and_click_play( page, client, PLAY )
        frame = page.frame_locator( FRAME )
        frame.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        page.wait_for_function(
            "() => document.querySelector( '[data-testid=podcast-overlay-frame]' ).contentDocument.querySelector( 'audio' ).getBoundingClientRect().height > 0"
        )

        box = frame.locator( "audio" ).evaluate(
            """a => {
                const r = a.getBoundingClientRect();
                const cs = getComputedStyle( document.body );
                return { top: r.top, bottom: r.bottom, height: r.height, frameHeight: window.innerHeight,
                         bodyPaddingTop: cs.paddingTop, bodyMarginTop: cs.marginTop,
                         scrollHeight: document.documentElement.scrollHeight };
            }"""
        )
        assert box[ "bodyPaddingTop" ] == "0px" and box[ "bodyMarginTop" ] == "0px", f"no space above the player: {box}"
        assert box[ "top" ] == 0, f"the player starts at the top of the frame: {box}"
        assert 0 < box[ "bottom" ] <= box[ "frameHeight" ], f"the player ends inside the frame, not cut off: {box}"
        assert box[ "scrollHeight" ] <= box[ "frameHeight" ], f"the frame has nothing to scroll: {box}"

        header_bottom = page.locator( ".podcast-overlay-header" ).evaluate( "h => h.getBoundingClientRect().bottom" )
        frame_top     = page.locator( FRAME ).evaluate( "f => f.getBoundingClientRect().top" )
        assert abs( frame_top - header_bottom ) <= 1, "the frame starts right under the header"

    def test_the_expand_icon_opens_the_full_page_and_closes_the_widget( self, logged_in_page, client ):
        page = logged_in_page
        _stub_files( page )
        _open_client_and_click_play( page, client, PLAY )

        with page.context.expect_page( timeout=10000 ) as opened:
            page.locator( EXPAND ).click()
        full = opened.value
        assert page.locator( OVERLAY ).count() == 0, "the widget closes, so the audio never plays twice"
        assert "embed=1" not in full.url and "autoplay=1" not in full.url

        full.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        assert full.locator( "h1" ).inner_text() == TITLE
        # The zero-padding rule is for embed=1 only: the full page keeps the room under its fixed nav bar.
        full.locator( "#lupin-nav" ).wait_for( state="visible", timeout=10000 )
        assert full.evaluate( "() => getComputedStyle( document.body ).paddingTop" ) == "56px"
        assert full.locator( "a.audio-player-download" ).count() == 1
        assert full.locator( "#audio-player-script-link" ).count() == 1
        assert full.locator( "#audio-player-source-link" ).count() == 1
        assert full.locator( "details summary" ).inner_text() == "File Details"
        for serial in ( "2026.11.01", "014849" ):
            assert serial not in full.locator( "h1" ).inner_text(), "the title carries no date or serial"

        with full.context.expect_page( timeout=10000 ) as script_tab:
            full.locator( "#audio-player-script-link" ).click()
        script = script_tab.value
        script.wait_for_function( "() => document.body.innerText.includes( 'hello' )", timeout=10000 )
        assert "The script says hello." in script.inner_text( "body" )

        with full.context.expect_page( timeout=10000 ) as source_tab:
            full.locator( "#audio-player-source-link" ).click()
        source = source_tab.value
        source.wait_for_function( "() => document.body.innerText.includes( 'Body text.' )", timeout=10000 )
        assert "The original report" in source.inner_text( "body" )

    def test_an_old_style_link_still_plays_with_a_date_free_title( self, logged_in_page, client ):
        page = logged_in_page
        _stub_files( page )
        _open_client_and_click_play( page, client, OLD )

        frame = page.frame_locator( FRAME )
        frame.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        with page.context.expect_page( timeout=10000 ) as opened:
            page.locator( EXPAND ).click()
        full = opened.value
        full.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        heading = full.locator( "h1" ).inner_text()
        assert heading == "Grading Your Own Exam Construct Validit"
        assert full.locator( ".audio-player-links" ).count() == 0, "no script or original link without the values"

    def test_a_link_whose_file_is_absent_is_left_out( self, logged_in_page, client ):
        page = logged_in_page
        _stub_files( page )
        missing = PLAY.replace( SCRIPT, "podcasts/u/absent-script.md" ).replace( SOURCE, "io/deep-research/u/absent.md" )
        _open_client_and_click_play( page, client, missing )
        with page.context.expect_page( timeout=10000 ) as opened:
            page.locator( EXPAND ).click()
        full = opened.value
        full.locator( "audio[controls]" ).wait_for( state="attached", timeout=15000 )
        assert full.locator( ".audio-player-links" ).count() == 0
        assert full.locator( "a.audio-player-download" ).count() == 1
