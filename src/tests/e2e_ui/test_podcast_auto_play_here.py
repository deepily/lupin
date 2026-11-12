"""
A finished podcast starts in the Play Here player by itself in both clients.

The unit tests cover the decisions. This file drives the real pages.
The multiplexer and the legacy client each get a finished podcast's notification.
The test reads the floating player that each leaves on the page.

What is real: the page, its boot, the INI setting through `/api/config/client`, and the player page's own start
and block handling. What is stubbed: the audio file (`page.route`), so no audio is bought, and one browser
function (`play`), so a blocked start can be forced.

The notification is handed to each client the way its live path takes one: the multiplexer's event bus and the
legacy client's `simulateNotificationUpdate`. A history reload does not use that path, so it is not driven here.

Venue: port 8000, scheduled through `POST /api/v2/submit` with test type `e2e_a`, because the `logged_in_page`
fixture registers a user. The file is listed in `partition/half-a.txt`.
"""

import pytest

from .conftest import BASE_URL

CLIENTS = [ "multiplexer", "legacy" ]

_PLAY_A = "/app/audio?path=podcast%2Fe2e-a.mp3&title=First&embed=1"
_PLAY_B = "/app/audio?path=podcast%2Fe2e-b.mp3&title=Second&embed=1"

_PLAYER = "[data-testid=podcast-overlay]"
_FRAME  = "[data-testid=podcast-overlay-frame]"


def _abstract( play ):
    return f"**Podcast Activity Report**\n\n**English**: [▶️ Play Here]({play}) | [🎧 Listen](/app/audio?path=podcast%2Fe2e-a.mp3)"


def _stub_player_and_file( page ):
    """Stub the player page and the audio file, so no audio is bought."""
    page.route( "**/app/audio?**", lambda route: route.fulfill( status=200, content_type="text/html", body="<!doctype html><title>stub player</title>" ) )
    page.route( "**/api/io/file?**", lambda route: route.fulfill( status=200, body=b"stub-audio-bytes", content_type="audio/mpeg" ) )


def _open( page, client, config_overrides=None ):
    """Open the client; the config answer is real, then patched with config_overrides."""
    if config_overrides is not None:
        def patch( route ):
            response = route.fetch()
            body     = response.json()
            body.update( config_overrides )
            route.fulfill( response=response, json=body )
        page.route( "**/api/config/client", patch )
    _stub_player_and_file( page )
    if client == "multiplexer":
        page.goto( f"{BASE_URL}/app/multiplexer" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function( "() => window.__multiplexerTestHook && window.__multiplexerTestHook.eventBus", timeout=15000 )
    else:
        page.goto( f"{BASE_URL}/app/notifications?classic=1" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function( "() => window.notificationsUI && typeof window.notificationsUI.simulateNotificationUpdate === 'function'", timeout=15000 )
        # The legacy client reads the setting when its config fetch lands; wait for the answer, not for a guess.
        page.wait_for_function( "() => window.notificationsUI.podcastAutoPlayHereOnFinish !== undefined", timeout=15000 )


def _finish_podcast( page, client, note_id, play ):
    """Hand the client a finished podcast's notification by its live path."""
    notification = { "id_hash": note_id, "message": "Podcast complete.", "sender_id": "cc@e2e#podcast", "priority": "medium",
                     "abstract": _abstract( play ), "timestamp": "2026-11-11T19:00:00.000Z" }
    if client == "multiplexer":
        page.evaluate(
            "( n ) => window.__multiplexerTestHook.eventBus.emit( { type: 'notification_queue_update', payload: { notification: n }, source: 'test', ts: Date.now() } )",
            notification )
    else:
        page.evaluate( "( n ) => window.notificationsUI.simulateNotificationUpdate( n )", notification )


def _player_says( page, event ):
    """Post what the player page posts to its holder: same-origin, with the player's source."""
    page.evaluate( "( e ) => window.postMessage( { source: 'lupin-audio-player', event: e }, window.location.origin )", event )


@pytest.mark.parametrize( "client", CLIENTS )
class TestPodcastAutoPlayHere:

    def test_a_finished_podcast_starts_in_the_player_with_no_click( self, logged_in_page, client ):
        page = logged_in_page
        _open( page, client )
        assert page.locator( _PLAYER ).count() == 0

        _finish_podcast( page, client, "e2e-auto-1", _PLAY_A )

        page.locator( _PLAYER ).wait_for( state="visible", timeout=5000 )
        assert page.locator( _FRAME ).get_attribute( "src" ) == _PLAY_A + "&autoplay=1"
        assert page.locator( ".podcast-overlay-title" ).inner_text() == "First"

    def test_a_second_podcast_waits_for_the_first_to_end( self, logged_in_page, client ):
        page = logged_in_page
        _open( page, client )
        _finish_podcast( page, client, "e2e-q-1", _PLAY_A )
        page.locator( _PLAYER ).wait_for( state="visible", timeout=5000 )

        _finish_podcast( page, client, "e2e-q-2", _PLAY_B )
        page.wait_for_timeout( 300 )
        assert page.locator( _FRAME ).get_attribute( "src" ) == _PLAY_A + "&autoplay=1", "the first is not cut off"
        assert page.locator( _PLAYER ).count() == 1, "never two players at once"

        _player_says( page, "ended" )
        page.wait_for_function( "( u ) => document.querySelector( '[data-testid=podcast-overlay-frame]' ).getAttribute( 'src' ) === u", arg=_PLAY_B + "&autoplay=1", timeout=5000 )

    def test_the_setting_off_leaves_the_play_here_link_alone( self, logged_in_page, client ):
        page = logged_in_page
        _open( page, client, config_overrides={ "podcast_auto_play_here_on_finish": False } )

        _finish_podcast( page, client, "e2e-off-1", _PLAY_A )
        page.wait_for_timeout( 500 )

        assert page.locator( _PLAYER ).count() == 0


def test_a_blocked_start_shows_a_visible_play_button( logged_in_page ):
    """
    The player page opened with autoplay, while `play()` refuses as an autoplay block does.

    The page must show a Play button and say so to the page that holds it. A click on it plays.
    """
    page = logged_in_page
    _stub_player_and_file( page )
    page.unroute( "**/app/audio?**" )          # this test wants the real player page
    page.add_init_script(
        "window.__plays = 0;"
        "HTMLMediaElement.prototype.play = function () { window.__plays++; return window.__plays === 1"
        " ? Promise.reject( new DOMException( 'blocked', 'NotAllowedError' ) ) : Promise.resolve(); };"
    )
    page.goto( f"{BASE_URL}{_PLAY_A}&autoplay=1" )

    prompt = page.locator( "[data-testid=autoplay-blocked-prompt]" )
    prompt.wait_for( state="visible", timeout=10000 )
    assert prompt.inner_text().strip().endswith( "Play" )

    prompt.click()
    assert page.evaluate( "() => window.__plays" ) == 2, "the button starts the audio"
    assert page.locator( "[data-testid=autoplay-blocked-prompt]" ).count() == 0, "the button goes once it is used"
