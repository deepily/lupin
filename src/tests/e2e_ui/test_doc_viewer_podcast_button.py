"""
E2E: the doc viewer's "Make a podcast" button, through both clients.

The doc viewer page is the one page both clients show a file through, so the button is drawn there
once. Three surfaces are driven: the page opened directly, the legacy client's content pane, and the
multiplexer's reading pane.

The assertions are on the requests that left the page. A button that is drawn but posts nothing, or
posts twice, would pass a test that only looks for the button. Every case counts the posts to the
start door, reads the body, and checks the Authorization header.

The doors are stubbed with page.route, which covers the embedded frame too. No job is queued and no
audio is bought. The viewer page, its auth path and the bundle are the real ones.

Venue: :8000 (scheduled), E2E UI suite. The bundle static/dist/doc-podcast/doc-podcast.js must be
built in the tree :8000 serves, by src/scripts/build-doc-podcast.sh. Without it no button appears.
"""

from __future__ import annotations

import json

from .conftest import BASE_URL

SCOPES   = { "scopes": [ { "name": "lupin", "root": "/var/lupin", "allowed_prefixes": [ "src/" ] } ] }
PATH     = "lupin/src/rnd/summary.md"
DOC_HREF = f"/app/docs?path={PATH}"
MARKDOWN = "# A summary\n\nSome words, enough to hear.\n"
CHECK_OK = { "ok": True, "name": "summary.md", "size": 4300 }
STARTED  = { "job_id": "pg-1a2b3c4d", "status": "waiting", "name": "summary.md", "queue_position": 1, "size": 4300 }


def _stub( page, check_status=200, check_body=None, start_status=200, start_body=None ):
    """Stub the file, the scope list and both podcast doors, and return the recorded requests."""
    seen = { "check": [ ], "start": [ ] }
    page.route( "**/api/docs/scopes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( SCOPES ) ) )
    page.route( "**/api/docs/file*", lambda r: r.fulfill(
        status=200, headers={ "content-type": "text/markdown; charset=utf-8" }, body=MARKDOWN ) )

    def _check( route ):
        seen[ "check" ].append( route.request.url )
        route.fulfill( status=check_status, content_type="application/json",
                       body=json.dumps( CHECK_OK if check_body is None else check_body ) )
    page.route( "**/api/podcast-proxy/from-viewer/check*", _check )

    def _start( route ):
        seen[ "start" ].append( { "body": json.loads( route.request.post_data or "{}" ),
                                  "auth": route.request.headers.get( "authorization", "" ) } )
        route.fulfill( status=start_status, content_type="application/json",
                       body=json.dumps( STARTED if start_body is None else start_body ) )
    page.route( "**/api/podcast-proxy/from-viewer", _start )
    return seen


def _drive_the_button( viewer, seen ):
    """
    Cancel once, then confirm with a double click.

    The viewer is a page or a frame locator. In order it asserts that the button is visible, that the
    confirmation names the file with nothing posted yet, and that Cancel posts nothing. A double click
    on Yes then posts once, with the page's path and a bearer token.
    """
    button = viewer.get_by_test_id( "doc-podcast-btn" )
    button.wait_for( state="visible", timeout=10_000 )

    button.click()
    text = viewer.get_by_test_id( "doc-podcast-text" )
    text.wait_for( state="visible", timeout=5_000 )
    assert "summary.md" in text.inner_text()
    assert seen[ "start" ] == [ ], "the confirmation must come before any post"

    viewer.get_by_test_id( "doc-podcast-cancel" ).click()
    assert viewer.get_by_test_id( "doc-podcast-confirm" ).is_hidden()
    assert seen[ "start" ] == [ ], "Cancel must post nothing"

    button.click()
    viewer.get_by_test_id( "doc-podcast-yes" ).dblclick()
    viewer.locator( "#doc-download-status" ).filter( has_text="pg-1a2b3c4d" ).wait_for( timeout=5_000 )
    assert len( seen[ "start" ] ) == 1, f"one confirmed click is one post; saw {len( seen[ 'start' ] )}"
    assert seen[ "start" ][ 0 ][ "body" ] == { "path": PATH }
    assert seen[ "start" ][ 0 ][ "auth" ].startswith( "Bearer " )
    assert len( seen[ "check" ] ) == 1, "the check runs once per file view"


def test_the_viewer_page_opened_directly_offers_and_starts_a_podcast( logged_in_page ):
    page = logged_in_page
    seen = _stub( page )
    page.goto( f"{BASE_URL}{DOC_HREF}" )
    _drive_the_button( page, seen )


def test_the_legacy_client_pane_offers_and_starts_a_podcast( notifications_page ):
    page = notifications_page
    seen = _stub( page )
    page.evaluate(
        """( href ) => {
            const a = document.createElement( 'a' );
            a.setAttribute( 'href', href );
            a.textContent = 'Open the summary';
            a.dataset.testDoc = '1';
            ( document.querySelector( '.container' ) || document.body ).appendChild( a );
        }""",
        DOC_HREF,
    )
    page.locator( "a[data-test-doc='1']" ).click()
    page.locator( "#content-pane-body iframe" ).wait_for( timeout=10_000 )
    _drive_the_button( page.frame_locator( "#content-pane-body iframe" ), seen )


def test_the_multiplexer_reading_pane_offers_and_starts_a_podcast( logged_in_page ):
    page = logged_in_page
    seen = _stub( page )
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane", timeout=15_000 )
    page.evaluate( "( href ) => window.__multiplexerTestHook.stores.readingPane.open( 'doc', href, 'Summary' )", DOC_HREF )
    page.locator( "#content-pane-body iframe" ).wait_for( timeout=10_000 )
    _drive_the_button( page.frame_locator( "#content-pane-body iframe" ), seen )


def test_a_file_the_server_will_not_podcast_gets_no_button( logged_in_page ):
    page = logged_in_page
    seen = _stub( page, check_status=400, check_body={ "detail": { "code": "wrong_kind", "message": "It is a .png file." } } )
    page.goto( f"{BASE_URL}{DOC_HREF}" )
    page.get_by_test_id( "doc-download-btn" ).wait_for( state="visible", timeout=10_000 )   # the page rendered
    page.wait_for_timeout( 500 )
    assert len( seen[ "check" ] ) == 1
    assert page.get_by_test_id( "doc-podcast-btn" ).is_hidden()


def test_a_refused_start_says_why_and_leaves_the_button_usable( logged_in_page ):
    page = logged_in_page
    seen = _stub( page, start_status=502,
                  start_body={ "detail": { "code": "queue_failed", "message": "The job could not be queued." } } )
    page.goto( f"{BASE_URL}{DOC_HREF}" )
    button = page.get_by_test_id( "doc-podcast-btn" )
    button.wait_for( state="visible", timeout=10_000 )
    button.click()
    page.get_by_test_id( "doc-podcast-yes" ).click()
    page.locator( "#doc-download-status" ).filter( has_text="could not be queued" ).wait_for( timeout=5_000 )
    assert len( seen[ "start" ] ) == 1 and button.is_enabled()
