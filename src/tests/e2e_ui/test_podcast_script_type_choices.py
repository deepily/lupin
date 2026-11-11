"""
E2E: the podcast script-type choices at every surface that starts a podcast.

Three surfaces carry the same three choices. The choices are script type (research critical
pre-selected), a Spanish switch (off) and, for a status report, one-shot. The surfaces are the doc
viewer's confirm panel, the multiplexer research form and the legacy research form.
The viewer page is the one page both clients show a document through, so it is driven in each client.

The assertions are on the request body that left the page. With nothing picked, the request carries
no type, no review and no languages. With status report and Spanish picked, it carries all three.
Neither research form may send the retired target_languages key.

The doors are stubbed with page.route, so no job is queued and no audio is bought.

Venue: :8000 (scheduled), E2E UI suite. The served tree must hold the rebuilt bundles
(static/dist/multiplexer and static/dist/doc-podcast, `npm run build`) and the notifications.js
carrying the bumped ?v= token in notifications.html.
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
SPANISH  = [ "en", "es-MX" ]


def _stub_viewer( page ):
    """Stub the file, the scope list and both podcast doors; return the recorded start bodies."""
    seen = []
    page.route( "**/api/docs/scopes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( SCOPES ) ) )
    page.route( "**/api/docs/file*", lambda r: r.fulfill(
        status=200, headers={ "content-type": "text/markdown; charset=utf-8" }, body=MARKDOWN ) )
    page.route( "**/api/podcast-proxy/from-viewer/check*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( CHECK_OK ) ) )

    def _start( route ):
        seen.append( json.loads( route.request.post_data or "{}" ) )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( STARTED ) )
    page.route( "**/api/podcast-proxy/from-viewer", _start )
    return seen


def _stub_submit( page ):
    """Stub /api/v2/submit; return the recorded request bodies."""
    seen = []

    def _submit( route ):
        seen.append( json.loads( route.request.post_data or "{}" ) )
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "job_id": "job-1", "status": "waiting" } ) )
    page.route( "**/api/v2/submit", _submit )
    return seen


def _confirm( viewer, status_report_and_spanish ):
    """Open the viewer's confirm panel, optionally pick status report + Spanish, and confirm."""
    button = viewer.get_by_test_id( "doc-podcast-btn" )
    button.wait_for( state="visible", timeout=10_000 )
    button.click()
    viewer.get_by_test_id( "doc-podcast-confirm" ).wait_for( state="visible", timeout=5_000 )
    assert viewer.get_by_test_id( "doc-podcast-type" ).input_value() == "research_critical"
    assert not viewer.get_by_test_id( "doc-podcast-spanish" ).is_checked()
    assert viewer.get_by_test_id( "doc-podcast-oneshot" ).is_hidden()
    if status_report_and_spanish:
        viewer.get_by_test_id( "doc-podcast-type" ).select_option( "status_report" )
        viewer.get_by_test_id( "doc-podcast-oneshot" ).wait_for( state="visible", timeout=5_000 )
        assert viewer.get_by_test_id( "doc-podcast-oneshot" ).is_checked()
        viewer.get_by_test_id( "doc-podcast-spanish" ).check()
    viewer.get_by_test_id( "doc-podcast-yes" ).click()
    viewer.locator( "#doc-download-status" ).filter( has_text="pg-1a2b3c4d" ).wait_for( timeout=5_000 )


def _open_in_legacy( page ):
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
    return page.frame_locator( "#content-pane-body iframe" )


def _open_in_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane", timeout=15_000 )
    page.evaluate( "( href ) => window.__multiplexerTestHook.stores.readingPane.open( 'doc', href, 'Summary' )", DOC_HREF )
    page.locator( "#content-pane-body iframe" ).wait_for( timeout=10_000 )
    return page.frame_locator( "#content-pane-body iframe" )


# ---- the shared viewer page, as loaded in each client ----

def test_the_viewer_page_posts_no_type_and_no_languages_when_nothing_is_picked( logged_in_page ):
    seen = _stub_viewer( logged_in_page )
    logged_in_page.goto( f"{BASE_URL}{DOC_HREF}" )
    _confirm( logged_in_page, False )
    assert seen == [ { "path": PATH } ]


def test_the_viewer_page_posts_status_report_and_spanish( logged_in_page ):
    seen = _stub_viewer( logged_in_page )
    logged_in_page.goto( f"{BASE_URL}{DOC_HREF}" )
    _confirm( logged_in_page, True )
    assert seen == [ { "path": PATH, "script_type": "status_report", "review": "one_shot", "languages": SPANISH } ]


def test_the_viewer_in_the_legacy_client_posts_no_choices_when_nothing_is_picked( notifications_page ):
    seen = _stub_viewer( notifications_page )
    _confirm( _open_in_legacy( notifications_page ), False )
    assert seen == [ { "path": PATH } ]


def test_the_viewer_in_the_legacy_client_posts_status_report_and_spanish( notifications_page ):
    seen = _stub_viewer( notifications_page )
    _confirm( _open_in_legacy( notifications_page ), True )
    assert seen == [ { "path": PATH, "script_type": "status_report", "review": "one_shot", "languages": SPANISH } ]


def test_the_viewer_in_the_multiplexer_posts_no_choices_when_nothing_is_picked( logged_in_page ):
    seen = _stub_viewer( logged_in_page )
    _confirm( _open_in_multiplexer( logged_in_page ), False )
    assert seen == [ { "path": PATH } ]


def test_the_viewer_in_the_multiplexer_posts_status_report_and_spanish( logged_in_page ):
    seen = _stub_viewer( logged_in_page )
    _confirm( _open_in_multiplexer( logged_in_page ), True )
    assert seen == [ { "path": PATH, "script_type": "status_report", "review": "one_shot", "languages": SPANISH } ]


# ---- the two research forms ----

REVEAL = """() => {
    const section = document.getElementById( 'research-submit-section' );
    for ( let node = section; node !== null; node = node.parentElement ) {
        node.classList.remove( 'collapsed' );
        node.hidden = false;
    }
}"""


def _research_args( page, prefix, status_report_and_spanish ):
    """Fill and submit the research form with this test id prefix; return the posted args."""
    seen = _stub_submit( page )
    page.evaluate( REVEAL )
    page.get_by_test_id( f"{prefix}-research-topic-input" ).fill( "what is a lupin" )
    page.get_by_test_id( f"{prefix}-research-podcast-checkbox" ).check()
    options = page.get_by_test_id( f"{prefix}-research-podcast-options" )
    options.wait_for( state="visible", timeout=5_000 )
    assert page.get_by_test_id( f"{prefix}-research-podcast-type" ).input_value() == "research_critical"
    assert not page.get_by_test_id( f"{prefix}-research-podcast-spanish" ).is_checked()
    assert page.get_by_test_id( f"{prefix}-research-podcast-oneshot" ).is_hidden()
    if status_report_and_spanish:
        page.get_by_test_id( f"{prefix}-research-podcast-type" ).select_option( "status_report" )
        page.get_by_test_id( f"{prefix}-research-podcast-oneshot" ).wait_for( state="visible", timeout=5_000 )
        page.get_by_test_id( f"{prefix}-research-podcast-spanish" ).check()
    page.get_by_test_id( f"{prefix}-research-submit-btn" ).click()
    page.wait_for_function( "() => document.getElementById( 'research-submit-status' ).textContent.includes( 'job-1' )",
                            timeout=5_000 )
    assert len( seen ) == 1
    assert seen[ 0 ][ "command" ] == "agent router go to research to podcast"
    assert "target_languages" not in seen[ 0 ][ "args" ]
    return seen[ 0 ][ "args" ]


def test_the_multiplexer_research_form_sends_no_languages_and_no_type_when_nothing_is_picked( logged_in_page ):
    logged_in_page.goto( f"{BASE_URL}/app/multiplexer" )
    logged_in_page.wait_for_load_state( "networkidle" )
    args = _research_args( logged_in_page, "multiplexer", False )
    assert args == { "query": "what is a lupin", "budget": 3, "dry_run": True }


def test_the_multiplexer_research_form_sends_status_report_and_spanish( logged_in_page ):
    logged_in_page.goto( f"{BASE_URL}/app/multiplexer" )
    logged_in_page.wait_for_load_state( "networkidle" )
    args = _research_args( logged_in_page, "multiplexer", True )
    assert args == { "query": "what is a lupin", "budget": 3, "dry_run": True,
                     "script_type": "status_report", "review": "one_shot", "languages": SPANISH }


def test_the_legacy_research_form_sends_no_languages_and_no_type_when_nothing_is_picked( logged_in_page ):
    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )
    args = _research_args( logged_in_page, "notifications", False )
    assert args == { "query": "what is a lupin", "budget": 3, "dry_run": True }


def test_the_legacy_research_form_sends_status_report_and_spanish( logged_in_page ):
    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    logged_in_page.wait_for_load_state( "networkidle" )
    args = _research_args( logged_in_page, "notifications", True )
    assert args == { "query": "what is a lupin", "budget": 3, "dry_run": True,
                     "script_type": "status_report", "review": "one_shot", "languages": SPANISH }
