"""
E2E — the doc viewer's ⬇ Download button, and the binary types it used to mis-render (ticket 668aa0a3).

Rick, 2026-09-24: "if it wraps and displays a markdown document, I want to be able to download
the referenced document without the application rendering layer that contains it."

🔴 THE ASSERTION IS ON THE SAVED BYTES. A button that saves the RENDERED page, or the right
bytes under the wrong name, would satisfy "a download happened". So every test reads the
downloaded file and compares it to the exact body the stub served.

The file endpoint is stubbed with page.route so the bytes are known exactly and no fixture has
to live on disk; the page itself, its auth path and its dispatch are the real ones.

Venue: :8000 (scheduled) — E2E UI suite.
"""

from __future__ import annotations

import json

from .conftest import BASE_URL

SCOPES = { "scopes": [ { "name": "lupin", "root": "/var/lupin", "allowed_prefixes": [ "src/" ] } ] }

MARKDOWN = "# Raw title\n\nThis is the **source**, not the render.\n"
MP3      = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes( range( 256 ) )
PPTX     = b"PK\x03\x04" + bytes( range( 200 ) )
JSON_DOC = { "entries_not": "a listing", "k": [ 1, 2 ] }


def _stub( page, body: bytes, content_type: str, status: int = 200 ):
    """Serve /api/docs/scopes and answer /api/docs/file with `body`; record every file request."""
    seen = [ ]
    page.route( "**/api/docs/scopes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( SCOPES ) ) )

    def _file( route ):
        seen.append( route.request.headers.get( "authorization", "" ) )
        route.fulfill( status=status, headers={ "content-type": content_type }, body=body )
    page.route( "**/api/docs/file*", _file )
    return seen


def _download( page ):
    """Press the button and return ( suggested filename, saved bytes )."""
    btn = page.get_by_test_id( "doc-download-btn" )
    btn.wait_for( state="visible", timeout=5_000 )
    with page.expect_download( timeout=10_000 ) as info:
        btn.click()
    d = info.value
    return d.suggested_filename, open( d.path(), "rb" ).read()


def test_markdown_downloads_its_raw_source_not_the_render( logged_in_page ):
    page = logged_in_page
    seen = _stub( page, MARKDOWN.encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/notes.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )   # the render happened

    name, data = _download( page )
    assert name == "notes.md"
    assert data == MARKDOWN.encode(), f"saved bytes are not the raw source: { data[ :80 ]!r }"
    assert len( seen ) == 2 and all( h.startswith( "Bearer " ) for h in seen ), \
        f"the download must go through the authed fetch; saw headers { seen }"


def test_audio_plays_inline_and_downloads_byte_for_byte( logged_in_page ):
    page = logged_in_page
    seen = _stub( page, MP3, "audio/mpeg" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/clip.mp3" )
    audio = page.locator( "#doc-viewer-target audio" )
    audio.wait_for( state="attached", timeout=5_000 )
    assert ( audio.get_attribute( "src" ) or "" ).startswith( "blob:" )

    name, data = _download( page )
    assert ( name, data ) == ( "clip.mp3", MP3 )
    assert len( seen ) == 1, f"a media file must be fetched once and reused, not { len( seen ) } times"


def test_a_type_with_no_viewer_says_so_and_still_downloads( logged_in_page ):
    page = logged_in_page
    _stub( page, PPTX, "application/vnd.openxmlformats-officedocument.presentationml.presentation" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/deck.pptx" )
    target = page.locator( "#doc-viewer-target.doc-viewer-no-preview" )
    target.wait_for( timeout=5_000 )
    assert "No preview" in target.inner_text()

    name, data = _download( page )
    assert ( name, data ) == ( "deck.pptx", PPTX )


def test_a_json_file_renders_as_text_not_as_a_listing( logged_in_page ):
    page = logged_in_page
    body = json.dumps( JSON_DOC ).encode()
    _stub( page, body, "application/json" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/conf/thing.json" )
    page.locator( "#doc-viewer-target pre.doc-code-content" ).wait_for( timeout=5_000 )
    assert "entries_not" in page.locator( "#doc-viewer-target" ).inner_text()

    name, data = _download( page )
    assert ( name, data ) == ( "thing.json", body )


def test_a_directory_listing_offers_no_download( logged_in_page ):
    page = logged_in_page
    listing = { "scope": "lupin", "path": "src/rnd", "entries": [
        { "name": "notes.md", "kind": "file", "size": 10, "view_url": "/app/docs?path=lupin%2Fsrc%2Frnd%2Fnotes.md" } ] }
    _stub( page, json.dumps( listing ).encode(), "application/json" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd" )
    page.locator( "#doc-viewer-target .doc-dir-listing" ).wait_for( timeout=5_000 )
    assert page.get_by_test_id( "doc-download-btn" ).is_hidden(), "a folder has nothing to download"


def test_a_failed_download_says_so_beside_the_button( logged_in_page ):
    page = logged_in_page
    _stub( page, MARKDOWN.encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/notes.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )

    page.unroute( "**/api/docs/file*" )
    page.route( "**/api/docs/file*", lambda r: r.fulfill( status=500, body="boom" ) )
    page.get_by_test_id( "doc-download-btn" ).click()
    status = page.locator( "#doc-download-status" )
    status.wait_for( timeout=5_000 )
    page.wait_for_function( "() => document.getElementById( 'doc-download-status' ).textContent.includes( '500' )",
                            timeout=5_000 )
    assert page.url.endswith( "notes.md" ), "a failed download must not navigate away"


def test_io_audio_hands_off_to_the_existing_player( logged_in_page ):
    """io audio already has /app/audio (with its own Download MP3) — the viewer must not duplicate it."""
    page = logged_in_page
    _stub( page, MP3, "audio/mpeg" )
    page.route( "**/api/io/file*", lambda r: r.fulfill( status=200, headers={ "content-type": "audio/mpeg" }, body=MP3 ) )
    page.goto( f"{BASE_URL}/app/docs?path=io/podcasts/episode.mp3" )
    page.wait_for_url( "**/app/audio?path=podcasts%2Fepisode.mp3*", timeout=5_000 )
    page.locator( "a.audio-player-download" ).wait_for( state="attached", timeout=5_000 )


def test_the_button_floats_and_takes_no_vertical_space( logged_in_page ):
    """
    Rick, 2026-09-24: the button is a layer OVER the document, not a row above it.

    Measured by geometry, not by class: the bar is zero-height, the document starts at the
    top of its container exactly as if the button were absent, and the button itself is on
    screen and overlaps the document's band.
    """
    page = logged_in_page
    _stub( page, ( MARKDOWN + "\n" + "para\n\n" * 400 ).encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/notes.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )
    page.get_by_test_id( "doc-download-btn" ).wait_for( state="visible", timeout=5_000 )

    # Two arms off one page: the document's top WITH the bar, then with the bar removed
    # from layout. A floating bar leaves the document where it is; a row pushes it down.
    g = page.evaluate( """() => {
        const bar = document.getElementById( 'doc-viewer-toolbar' );
        const doc = document.getElementById( 'doc-viewer-target' );
        const btn = document.getElementById( 'doc-download-btn' ).getBoundingClientRect();
        const withBar = doc.getBoundingClientRect().top;
        const barH    = bar.getBoundingClientRect().height;
        bar.style.display = 'none';
        const withoutBar = doc.getBoundingClientRect().top;
        bar.style.display = '';
        return { barH, withBar, withoutBar, btnTop: btn.top, btnBottom: btn.bottom };
    }""" )
    assert g[ "barH" ] == 0, f"the bar takes { g[ 'barH' ] }px — it must float, not occupy a row"
    assert abs( g[ "withBar" ] - g[ "withoutBar" ] ) < 1, \
        f"the button pushes the document down by { g[ 'withBar' ] - g[ 'withoutBar' ] }px"
    assert g[ "btnBottom" ] > g[ "withBar" ] and g[ "btnTop" ] < g[ "withBar" ] + 60, \
        f"the button should sit over the top of the document: { g }"


def test_the_button_stays_pinned_below_the_nav_while_scrolling( logged_in_page ):
    page = logged_in_page
    _stub( page, ( MARKDOWN + "\n" + "para\n\n" * 400 ).encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/notes.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )
    page.evaluate( "() => window.scrollTo( 0, 2000 )" )
    page.wait_for_timeout( 200 )
    top = page.evaluate( "() => document.getElementById( 'doc-download-btn' ).getBoundingClientRect().top" )
    assert 56 <= top <= 80, f"after scrolling, the button is at { top }px — hidden under the 56px nav or scrolled away"
    assert page.get_by_test_id( "doc-download-btn" ).is_visible()
