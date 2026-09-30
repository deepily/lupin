"""
E2E — the doc viewer's 📁 Folder button, 🗂 Roots panel and ⬆ Upload (ticket 416d4b00).

Rick, 2026-09-24: from any document, get to its folder; from any folder, see every root the
viewer can browse; and drop a file into the folder you are looking at.

The /api/docs endpoints are stubbed with page.route so every request the page makes is
recorded and its answer is known exactly; the page itself, its auth path, its admin check and
its dispatch are the real ones. The admin case uses the real admin_page fixture — a JWT the
server minted with roles ["user", "admin"] — not a hand-built token.

🔴 THE UPLOAD ASSERTIONS READ THE MULTIPART BODY THE PAGE SENT. "An upload request happened"
would pass for a page that posted to the wrong folder or dropped the conflict mode, so each
test pins the `dir` and `on_conflict` fields by value.

Venue: :8000 (scheduled) — E2E UI suite.
"""

from __future__ import annotations

import json

from .conftest import BASE_URL

SCOPES = { "scopes": [
    { "name": "lupin",      "root": "/var/lupin",   "allowed_prefixes": [ "src/", "io/" ] },
    { "name": "claude-plans", "root": "/var/plans", "allowed_prefixes": [ ] },
] }

MARKDOWN = "# Title\n\nbody\n"


def _listing( names ):
    return { "kind": "directory", "scope": "lupin", "path": "src/rnd", "parent": "src", "entries": [
        { "name": n, "kind": "file", "size": 10, "rel_path": f"src/rnd/{n}",
          "view_url": f"/app/docs?path=lupin%2Fsrc%2Frnd%2F{n}" } for n in names ] }


def _stub_scopes( page ):
    page.route( "**/api/docs/scopes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( SCOPES ) ) )


def _stub_file( page, body: bytes, content_type: str ):
    page.route( "**/api/docs/file*", lambda r: r.fulfill(
        status=200, headers={ "content-type": content_type }, body=body ) )


def _stub_listing( page, state ):
    """Serve the listing from `state["names"]`, so an upload stub can change what comes back."""
    page.route( "**/api/docs/file*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( _listing( state[ "names" ] ) ) ) )


def _field( body: bytes, name: str ) -> str:
    """One text field's value out of a multipart body."""
    marker = f'name="{name}"\r\n\r\n'.encode()
    start  = body.index( marker ) + len( marker )
    return body[ start : body.index( b"\r\n", start ) ].decode()


def _open_listing( page, state ):
    _stub_scopes( page )
    _stub_listing( page, state )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd" )
    page.locator( "#doc-viewer-target .doc-dir-listing" ).wait_for( timeout=5_000 )


# ── 📁 Folder ────────────────────────────────────────────────────────────────────────────────

def test_folder_button_opens_the_files_parent_folder( logged_in_page ):
    page = logged_in_page
    _stub_scopes( page )
    _stub_file( page, MARKDOWN.encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/src/rnd/notes.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )

    btn = page.get_by_test_id( "doc-folder-btn" )
    btn.wait_for( state="visible", timeout=5_000 )
    btn.click()
    page.wait_for_url( "**/app/docs?path=lupin%2Fsrc%2Frnd", timeout=5_000 )


def test_folder_of_a_root_level_file_is_the_scope_root( logged_in_page ):
    page = logged_in_page
    _stub_scopes( page )
    _stub_file( page, MARKDOWN.encode(), "text/markdown; charset=utf-8" )
    page.goto( f"{BASE_URL}/app/docs?path=lupin/README.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )
    assert page.get_by_test_id( "doc-folder-btn" ).get_attribute( "data-target" ) == "lupin/"


def test_folder_of_a_legacy_bare_io_path_gains_its_io_prefix( logged_in_page ):
    """A pre-unification link names no project; its folder link must still be canonical."""
    page = logged_in_page
    _stub_scopes( page )
    page.route( "**/api/io/file*", lambda r: r.fulfill(
        status=200, headers={ "content-type": "text/markdown; charset=utf-8" }, body=MARKDOWN.encode() ) )
    page.goto( f"{BASE_URL}/app/docs?path=reports/weekly.md" )
    page.locator( "#doc-viewer-target h1" ).wait_for( timeout=5_000 )
    assert page.get_by_test_id( "doc-folder-btn" ).get_attribute( "data-target" ) == "io/reports"


def test_a_listing_offers_no_folder_button( logged_in_page ):
    page = logged_in_page
    _open_listing( page, { "names": [ "a.md" ] } )
    assert page.get_by_test_id( "doc-folder-btn" ).is_hidden(), "a folder view is already the folder"


# ── 🗂 Roots ─────────────────────────────────────────────────────────────────────────────────

def test_roots_panel_lists_io_and_every_registered_scope_with_its_prefixes( logged_in_page ):
    page = logged_in_page
    _open_listing( page, { "names": [ "a.md" ] } )

    roots = page.locator( "#doc-viewer-target details.doc-roots" )
    assert roots.count() == 1
    assert roots.get_attribute( "open" ) is None, "the panel starts closed so the listing stays first"
    assert "Roots (3)" in roots.locator( "summary" ).inner_text()   # io + the two stubbed scopes

    hrefs = roots.locator( "a" ).evaluate_all( "els => els.map( a => a.getAttribute( 'href' ) )" )
    # io first, then the registry in the order the server sent it, each scope followed by its prefixes.
    assert hrefs == [
        "/app/docs?path=io%2F",
        "/app/docs?path=lupin%2F",
        "/app/docs?path=lupin%2Fsrc",
        "/app/docs?path=lupin%2Fio",
        "/app/docs?path=claude-plans%2F",
    ], f"roots links: { hrefs }"


# ── 🗂 Roots LANDING (row 47759aa3) ──────────────────────────────────────────────────────────
#
# Rick's ruling 2026-09-26, "A roots page, fully open": a bare /app/docs with no ?path= is
# the landing, not an error. It used to answer "No document path specified. Use
# ?path=<project>/<file>" — which is why the only way into the viewer was to find a doc
# link in the notification history first, the complaint this row was filed about.
#
# The landing REUSES this same Roots panel rather than growing a second list of the same
# registry: two renderings of one fact agree until somebody edits one of them.


def test_a_bare_docs_visit_lands_on_the_roots_panel_expanded( logged_in_page ):
    page = logged_in_page
    _stub_scopes( page )
    page.goto( f"{BASE_URL}/app/docs" )

    roots = page.locator( "#doc-viewer-target details.doc-roots" )
    roots.wait_for( timeout=5_000 )
    assert roots.get_attribute( "open" ) is not None, (
        "the LANDING must arrive expanded — Rick asked for 'fully open'. A listing's panel "
        "starts closed so the listing stays first, and that contrast is the point: the same "
        "panel, two states, one renderer"
    )
    assert page.locator( "#doc-viewer-target .doc-viewer-error" ).count() == 0, \
        "the old 'No document path specified' error must be gone, not merely pushed down"


def test_the_landing_lists_every_scope_the_LIVE_registry_returns( logged_in_page ):
    page = logged_in_page
    _stub_scopes( page )
    page.goto( f"{BASE_URL}/app/docs" )
    roots = page.locator( "#doc-viewer-target details.doc-roots" )
    roots.wait_for( timeout=5_000 )

    # 🔴 THE STUB *IS* THE MUTANT, which is what Rick's "a mutant that drops one must
    # redden" asks for: the assertion is derived from SCOPES, so removing an entry from the
    # registry changes what must appear. A hand-written expected list would pass while the
    # page ignored the registry entirely — bug 3d41fcba was exactly a hardcoded list going
    # stale, so an expectation hardcoded HERE would be the same defect on the other side.
    expected = [ "/app/docs?path=io%2F" ]
    for s in SCOPES[ "scopes" ]:
        expected.append( f"/app/docs?path={ s[ 'name' ] }%2F" )
        for prefix in s[ "allowed_prefixes" ]:
            expected.append( f"/app/docs?path={ s[ 'name' ] }%2F{ prefix.rstrip( '/' ) }" )

    hrefs = roots.locator( "a" ).evaluate_all( "els => els.map( a => a.getAttribute( 'href' ) )" )
    assert hrefs == expected, f"landing roots links: { hrefs } != { expected }"
    assert f"Roots ({ len( SCOPES[ 'scopes' ] ) + 1 })" in roots.locator( "summary" ).inner_text(), \
        "the count must be io/ plus every registered scope, derived rather than typed"


def test_the_landing_says_so_when_the_registry_answers_with_nothing( logged_in_page ):
    page = logged_in_page
    page.route( "**/api/docs/scopes*", lambda r: r.fulfill(
        status=200, content_type="application/json", body=json.dumps( { "scopes": [] } ) ) )
    page.goto( f"{BASE_URL}/app/docs" )

    roots = page.locator( "#doc-viewer-target details.doc-roots" )
    roots.wait_for( timeout=5_000 )
    # An empty registry and an unreachable one render the same list, and the user should not
    # have to guess which they got. io/ is still browsable either way, so the page says the
    # list is incomplete rather than pretending io/ is all there is.
    assert page.locator( "#doc-viewer-target .doc-viewer-error" ).count() == 1, \
        "an empty registry must be stated, not silently rendered as a one-entry roots list"
    hrefs = roots.locator( "a" ).evaluate_all( "els => els.map( a => a.getAttribute( 'href' ) )" )
    assert hrefs == [ "/app/docs?path=io%2F" ], f"io/ must still be offered; got { hrefs }"


# ── ⬆ Upload ────────────────────────────────────────────────────────────────────────────────

def test_upload_is_not_offered_to_a_non_admin( logged_in_page ):
    page = logged_in_page
    _open_listing( page, { "names": [ "a.md" ] } )
    assert page.get_by_test_id( "doc-upload-btn" ).is_hidden()


def test_admin_uploads_into_the_listed_folder_and_the_listing_refreshes( admin_page ):
    page  = admin_page
    state = { "names": [ "a.md" ] }
    sent  = [ ]
    _open_listing( page, state )

    def _upload( route ):
        sent.append( route.request.post_data_buffer )
        state[ "names" ] = [ "a.md", "new.md" ]
        route.fulfill( status=201, content_type="application/json", body=json.dumps( {
            "path": "lupin/src/rnd/new.md", "name": "new.md", "size": 5, "replaced": False,
            "view_url": "/app/docs?path=lupin%2Fsrc%2Frnd%2Fnew.md" } ) )
    page.route( "**/api/docs/upload*", _upload )

    page.get_by_test_id( "doc-upload-btn" ).wait_for( state="visible", timeout=5_000 )
    page.get_by_test_id( "doc-upload-input" ).set_input_files(
        files=[ { "name": "new.md", "mimeType": "text/markdown", "buffer": b"hello" } ] )

    page.locator( ".doc-dir-name", has_text="new.md" ).wait_for( timeout=5_000 )
    assert "Uploaded new.md" in page.get_by_test_id( "doc-upload-status" ).inner_text()
    assert len( sent ) == 1
    assert _field( sent[ 0 ], "dir" ) == "lupin/src/rnd"
    assert _field( sent[ 0 ], "on_conflict" ) == "refuse"
    assert b"hello" in sent[ 0 ]


def test_a_name_clash_offers_replace_rename_cancel_without_a_browser_dialog( admin_page ):
    page    = admin_page
    state   = { "names": [ "a.md" ] }
    modes   = [ ]
    dialogs = [ ]
    page.on( "dialog", lambda d: ( dialogs.append( d.message ), d.dismiss() ) )
    _open_listing( page, state )

    def _upload( route ):
        mode = _field( route.request.post_data_buffer, "on_conflict" )
        modes.append( mode )
        if mode == "refuse":
            route.fulfill( status=409, content_type="application/json", body=json.dumps( { "detail": {
                "error": "exists", "message": "a.md already exists in lupin/src/rnd", "suggested_name": "a-2.md" } } ) )
            return
        state[ "names" ] = [ "a.md", "a-2.md" ]
        route.fulfill( status=201, content_type="application/json", body=json.dumps( {
            "path": "lupin/src/rnd/a-2.md", "name": "a-2.md", "size": 5, "replaced": False,
            "view_url": "/app/docs?path=lupin%2Fsrc%2Frnd%2Fa-2.md" } ) )
    page.route( "**/api/docs/upload*", _upload )

    page.get_by_test_id( "doc-upload-input" ).set_input_files(
        files=[ { "name": "a.md", "mimeType": "text/markdown", "buffer": b"hello" } ] )

    rename = page.get_by_test_id( "doc-upload-rename" )
    rename.wait_for( timeout=5_000 )
    assert rename.inner_text() == "Rename to a-2.md"
    assert page.get_by_test_id( "doc-upload-replace" ).is_visible()
    assert page.get_by_test_id( "doc-upload-cancel" ).is_visible()

    rename.click()
    page.locator( ".doc-dir-name", has_text="a-2.md" ).wait_for( timeout=5_000 )
    assert modes == [ "refuse", "rename" ]
    assert dialogs == [ ], f"a browser dialog blocks automation; saw { dialogs }"


def test_cancel_clears_the_clash_and_sends_nothing_more( admin_page ):
    page  = admin_page
    modes = [ ]
    _open_listing( page, { "names": [ "a.md" ] } )

    def _upload( route ):
        modes.append( _field( route.request.post_data_buffer, "on_conflict" ) )
        route.fulfill( status=409, content_type="application/json", body=json.dumps( { "detail": {
            "error": "exists", "message": "a.md already exists", "suggested_name": "a-2.md" } } ) )
    page.route( "**/api/docs/upload*", _upload )

    page.get_by_test_id( "doc-upload-input" ).set_input_files(
        files=[ { "name": "a.md", "mimeType": "text/markdown", "buffer": b"hello" } ] )
    page.get_by_test_id( "doc-upload-cancel" ).wait_for( timeout=5_000 )
    page.get_by_test_id( "doc-upload-cancel" ).click()
    assert page.get_by_test_id( "doc-upload-status" ).inner_text() == ""
    assert modes == [ "refuse" ]


def test_a_refused_upload_says_why( admin_page ):
    page = admin_page
    _open_listing( page, { "names": [ "a.md" ] } )
    page.route( "**/api/docs/upload*", lambda r: r.fulfill( status=403, content_type="application/json",
        body=json.dumps( { "detail": "This folder is not writable on this server: lupin/src/rnd" } ) ) )

    page.get_by_test_id( "doc-upload-input" ).set_input_files(
        files=[ { "name": "b.md", "mimeType": "text/markdown", "buffer": b"hello" } ] )
    page.wait_for_function(
        "() => document.getElementById( 'doc-upload-status' ).textContent.includes( 'not writable' )",
        timeout=5_000 )
    assert page.get_by_test_id( "doc-upload-status" ).inner_text().startswith( "Upload failed:" )


def test_dropping_a_file_on_the_listing_uploads_it( admin_page ):
    page = admin_page
    sent = [ ]
    _open_listing( page, { "names": [ "a.md" ] } )
    page.route( "**/api/docs/upload*", lambda r: ( sent.append( r.request.post_data_buffer ), r.fulfill(
        status=201, content_type="application/json", body=json.dumps( {
            "path": "lupin/src/rnd/dropped.md", "name": "dropped.md", "size": 4, "replaced": False,
            "view_url": "/app/docs?path=lupin%2Fsrc%2Frnd%2Fdropped.md" } ) ) ) )

    page.get_by_test_id( "doc-upload-btn" ).wait_for( state="visible", timeout=5_000 )
    page.evaluate( """() => {
        const dt = new DataTransfer();
        dt.items.add( new File( [ 'drop' ], 'dropped.md', { type: 'text/markdown' } ) );
        const t = document.getElementById( 'doc-viewer-target' );
        t.dispatchEvent( new DragEvent( 'dragover', { dataTransfer: dt, bubbles: true, cancelable: true } ) );
        t.dispatchEvent( new DragEvent( 'drop',     { dataTransfer: dt, bubbles: true, cancelable: true } ) );
    }""" )
    page.wait_for_function(
        "() => document.getElementById( 'doc-upload-status' ).textContent.includes( 'Uploaded dropped.md' )",
        timeout=5_000 )
    assert len( sent ) == 1 and _field( sent[ 0 ], "dir" ) == "lupin/src/rnd"


def test_the_bar_still_floats_on_a_listing_with_upload_shown( admin_page ):
    page = admin_page
    _open_listing( page, { "names": [ "a.md" ] } )
    page.get_by_test_id( "doc-upload-btn" ).wait_for( state="visible", timeout=5_000 )
    h = page.evaluate( "() => document.getElementById( 'doc-viewer-toolbar' ).getBoundingClientRect().height" )
    assert h == 0, f"the bar takes { h }px — it must float, not occupy a row"
    assert page.get_by_test_id( "doc-download-btn" ).is_hidden()
