#!/usr/bin/env python3
"""
DOES EACH NEW TICKET MIC BUTT AGAINST ITS FIELD'S LEFT EDGE, AND IS THE CARD ITS NORMAL HEIGHT?

Row ab1f06e7, Rick's ruling verbatim: *"there would be a third Column in the middle into
which these 2 recording widgets buttons would be inserted They would be right aligned so
they would butt up against the left hand side of the text widget they correspond to"*.

🔴 WHY THIS READS GEOMETRY AND NOT THE DOM OR THE CSS TEXT. The layout was described in
prose three times and built wrong three times, and every build had green unit tests: a DOM
order or a stylesheet string is what the author believed the browser would do. This asks
the browser. It measures bounding boxes in real Chromium, and a hit test at each mic's
centre, so a mic that is present but covered or clipped reads as the defect it is.

WHAT IT RENDERS. The card is built by the real `shared/task-create.js`, styled by every
stylesheet the page itself links, in the page's own order, parsed out of
`notifications.html` and `multiplexer.html` so the list cannot drift from the pages. Files
come from `$LUPIN_ROOT` through Playwright request routing, so pointing `LUPIN_ROOT` at
another checkout measures that checkout.
⇒ That is how the red run was taken: against a detached tree at efaa004b (mics under each
field's right edge, card 42.8px taller), then green at this change.

THE MULTIPLEXER, THROUGH ITS OWN BOOT. The first half hands the card a dictation hook
itself, so it proves the LAYOUT and not that the multiplexer ever supplies one — and it
did not: `boot.ts` passed no recorder, so the multiplexer's card rendered with no mics at
all while every test above stayed green. The last tests therefore load the real
`multiplexer.html` and its BUILT bundle (`dist/multiplexer/`, what a browser runs, so run
`npm run build` first), answer every API call with an empty body, click ＋ New, and
measure the card that boot actually produced.

⚠️ WHAT IT DOES **NOT** COVER, stated before the result. The first half renders the card
alone on a blank page, not inside a logged-in notifications page, so a defect where the REST of the
page restyles the card is outside it. It also does not check that a mic records;
`src/tests/unit/shared/task_create.test.ts` and the two clients' hook tests do that.

⚠️ VENUE: **:7999**, by the rubric and not the folder name. It mutates nothing, needs no
server (it renders files from disk), takes a few seconds and needs no monopoly. It is not
in `e2e_ui/` because that suite's conftest requires a live :8000.
"""
import mimetypes
import os
import re

import pytest

ROOT   = os.environ.get( "LUPIN_ROOT", os.getcwd() )
STATIC = os.path.join( ROOT, "src/lupin_app/static" )
ORIGIN = "http://new-ticket-harness.invalid"

# Half a CSS pixel. Layout snaps to device pixels at dpr 2, so any real miss is larger.
EDGE_TOLERANCE_PX = 0.5

playwright_api = pytest.importorskip( "playwright.sync_api",
                                      reason="playwright is not installed in this venv" )


def _linked_sheets( page_name ):
    """
    Every stylesheet `<page_name>.html` links, in document order, query strings dropped.

    Ensures:
        - at least one sheet, and task-list.css among them, or the harness would be
          measuring an unstyled card and every assertion below would be about nothing
    """
    html   = open( os.path.join( STATIC, "html", f"{ page_name }.html" ) ).read()
    hrefs  = re.findall( r'<link\s+rel="stylesheet"\s+href="([^"]+)"', html )
    sheets = [ href.split( "?" )[ 0 ] for href in hrefs if href.startswith( "/static/" ) ]
    assert any( s.endswith( "/css/task-list.css" ) for s in sheets ), (
        f"{ page_name }.html links no task-list.css — the card would render unstyled: { sheets }" )
    return sheets


def _harness( sheets ):
    """One blank page: the page's own stylesheets and the real card module."""
    links = "\n".join( f'<link rel="stylesheet" href="{ href }">' for href in sheets )
    return f"""<!doctype html><html><head><meta charset="utf-8">{ links }</head><body>
<script type="module">
import {{ openNewTicketCard }} from "/static/js/shared/task-create.js";
window.openCard = ( withMics ) => openNewTicketCard( {{
    postTicket : async () => ( {{ status: 201 }} ),
    assignees  : [ "maria" ],
    ...( withMics ? {{ onDictate: () => {{}} }} : {{}} ),
}} );
window.harnessReady = true;
</script></body></html>"""


def _serve_from_disk( route ):
    """Answer a harness request from `$LUPIN_ROOT/src/lupin_app/static`, or 404."""
    path = route.request.url[ len( ORIGIN ): ].split( "?" )[ 0 ]
    if not path.startswith( "/static/" ):
        route.fulfill( status=404, body="" )
        return
    disk = os.path.join( STATIC, path[ len( "/static/" ): ] )
    if not os.path.isfile( disk ):
        route.fulfill( status=404, body="" )
        return
    kind, _ = mimetypes.guess_type( disk )
    if disk.endswith( ".js" ): kind = "text/javascript"
    route.fulfill( status=200, body=open( disk, "rb" ).read(), content_type=kind or "application/octet-stream" )


_MEASURE = """( withMics ) => {
    window.openCard( withMics );
    const box  = ( el ) => el === null ? null : el.getBoundingClientRect().toJSON();
    const out  = { card: box( document.querySelector( ".new-ticket-card" ) ), fields: {}, mics: {}, hits: {} };
    for ( const el of document.querySelectorAll( ".new-ticket-form [data-field]" ) ) {
        out.fields[ el.getAttribute( "data-field" ) ] = box( el );
    }
    for ( const mic of document.querySelectorAll( ".new-ticket-mic" ) ) {
        const b     = mic.getBoundingClientRect();
        const field = mic.getAttribute( "data-mic-field" );
        out.mics[ field ] = b.toJSON();
        out.hits[ field ] = document.elementFromPoint( b.x + b.width / 2, b.y + b.height / 2 ) === mic;
    }
    return out;
}"""


@pytest.fixture( scope="module", params=[ "notifications", "multiplexer" ] )
def measured( request ):
    """The card measured without mics, then with them, under one page's stylesheets."""
    sheets = _linked_sheets( request.param )
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page( viewport={ "width": 1200, "height": 900 }, device_scale_factor=2 )
        page.route( f"{ ORIGIN }/**", _serve_from_disk )
        page.route( f"{ ORIGIN }/", lambda route: route.fulfill( status=200, body=_harness( sheets ),
                                                                  content_type="text/html" ) )
        page.goto( f"{ ORIGIN }/" )
        page.wait_for_function( "window.harnessReady === true" )
        without = page.evaluate( _MEASURE, False )
        with_   = page.evaluate( _MEASURE, True )
        browser.close()
    yield { "page": request.param, "without": without, "with": with_ }


def test_the_harness_measured_something( measured ):
    """A card, two mics and nine fields — or every assertion below loops over nothing."""
    m = measured[ "with" ]
    assert m[ "card" ] is not None and m[ "card" ][ "height" ] > 100, f"{ measured[ 'page' ] }: no card rendered"
    assert sorted( m[ "mics" ] ) == [ "details", "title" ], f"{ measured[ 'page' ] }: mics were { sorted( m[ 'mics' ] ) }"
    assert len( m[ "fields" ] ) == 9, f"{ measured[ 'page' ] }: fields were { sorted( m[ 'fields' ] ) }"
    assert measured[ "without" ][ "mics" ] == { }, "the no-hook card must carry no mics"


@pytest.mark.parametrize( "field", [ "title", "details" ] )
def test_each_mics_right_edge_IS_its_fields_left_edge( measured, field ):
    """
    Rick's "butt up against the left hand side of the text widget". The mic ends exactly
    where its field starts, and it sits in that field's row, not below it.
    """
    mic, box = measured[ "with" ][ "mics" ][ field ], measured[ "with" ][ "fields" ][ field ]
    gap = box[ "left" ] - mic[ "right" ]
    assert abs( gap ) <= EDGE_TOLERANCE_PX, (
        f"{ measured[ 'page' ] }: the { field } mic's right edge is at { mic['right']:.1f}px and the field's "
        f"left edge at { box['left']:.1f}px — a { gap:.1f}px gap. (At efaa004b the mic sat under the field's "
        f"RIGHT edge.)" )
    assert box[ "top" ] - EDGE_TOLERANCE_PX <= mic[ "top" ] and mic[ "bottom" ] <= box[ "bottom" ] + EDGE_TOLERANCE_PX, (
        f"{ measured[ 'page' ] }: the { field } mic spans { mic['top']:.1f}–{ mic['bottom']:.1f}px but its field "
        f"spans { box['top']:.1f}–{ box['bottom']:.1f}px — it is not beside the field it dictates into" )


@pytest.mark.parametrize( "field", [ "title", "details" ] )
def test_a_click_at_each_mics_centre_reaches_that_mic( measured, field ):
    """A mic can be in the right place and still be covered; this asks what a click would hit."""
    assert measured[ "with" ][ "hits" ][ field ], (
        f"{ measured[ 'page' ] }: a click at the { field } mic's centre does not reach the mic" )


def test_the_mics_do_not_make_the_card_taller( measured ):
    """
    "Card height should return to normal". The build at efaa004b put each mic on its own
    line under its field and added 42.8px. With the mics in their own column, the card is
    exactly as tall as the card with no mics at all.
    """
    tall, normal = measured[ "with" ][ "card" ][ "height" ], measured[ "without" ][ "card" ][ "height" ]
    assert abs( tall - normal ) <= EDGE_TOLERANCE_PX, (
        f"{ measured[ 'page' ] }: the card is { tall:.1f}px with mics and { normal:.1f}px without — "
        f"the mics add { tall - normal:.1f}px" )


def test_every_field_starts_on_one_left_edge( measured ):
    """The third column only works if all nine fields share it, mic or no mic."""
    lefts = { f: round( b[ "left" ], 1 ) for f, b in measured[ "with" ][ "fields" ].items() }
    assert len( set( lefts.values() ) ) == 1, f"{ measured[ 'page' ] }: field left edges differ: { lefts }"


# ---------------------------------------------------------------------------
# The multiplexer's own card — booted from multiplexer.html and the built bundle
# ---------------------------------------------------------------------------

MUX_ORIGIN = "http://mux-harness.invalid"


def _serve_the_multiplexer( route ):
    """The page and its static files from disk; every other request answers an empty 200."""
    path = route.request.url[ len( MUX_ORIGIN ): ].split( "?" )[ 0 ]
    if path == "/app/multiplexer":
        route.fulfill( status=200, content_type="text/html",
                       body=open( os.path.join( STATIC, "html", "multiplexer.html" ) ).read() )
        return
    if path.startswith( "/static/" ):
        disk = os.path.join( STATIC, path[ len( "/static/" ): ] )
        if not os.path.isfile( disk ):
            route.fulfill( status=404, body="" )
            return
        kind, _ = mimetypes.guess_type( disk )
        if disk.endswith( ".js" ): kind = "text/javascript"
        route.fulfill( status=200, body=open( disk, "rb" ).read(), content_type=kind or "application/octet-stream" )
        return
    route.fulfill( status=200, content_type="application/json",
                   body='{"tasks": []}' if path.startswith( "/api/tasks" ) else "{}" )


@pytest.fixture( scope="module" )
def mux_card():
    """The New Ticket card as the booted multiplexer opens it, measured."""
    manifest = os.path.join( STATIC, "dist", "multiplexer", "manifest.json" )
    assert os.path.isfile( manifest ), (
        f"no built multiplexer bundle at { manifest } — run `npm run build`; this test measures what "
        f"the browser runs, and without a build there is nothing to measure" )
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page( viewport={ "width": 1600, "height": 1000 }, device_scale_factor=2 )
        page.route( f"{ MUX_ORIGIN }/**", _serve_the_multiplexer )
        # Boot renders the panes only for a page that holds a login token; any value will do,
        # because every API answer here is faked.
        page.add_init_script( "try { localStorage.setItem( 'lupin_access_token', 'smoke' ); } catch ( e ) {}" )
        page.goto( f"{ MUX_ORIGIN }/app/multiplexer" )
        button = page.locator( '[data-testid="multiplexer-task-list-new-ticket"]' )
        button.wait_for( state="attached", timeout=15000 )
        button.click()
        page.locator( '[data-testid="multiplexer-new-ticket"]' ).wait_for( state="attached" )
        measured = page.evaluate( """() => {
            const out = { mics: {}, fields: {}, hits: {} };
            for ( const el of document.querySelectorAll( ".new-ticket-form [data-field]" ) ) {
                out.fields[ el.getAttribute( "data-field" ) ] = el.getBoundingClientRect().toJSON();
            }
            for ( const mic of document.querySelectorAll( ".new-ticket-mic" ) ) {
                const b     = mic.getBoundingClientRect();
                const field = mic.getAttribute( "data-mic-field" );
                out.mics[ field ] = b.toJSON();
                out.hits[ field ] = document.elementFromPoint( b.x + b.width / 2, b.y + b.height / 2 ) === mic;
            }
            return out;
        }""" )
        browser.close()
    return measured


def test_the_booted_multiplexer_card_carries_both_mics( mux_card ):
    """Rick, ~22:01 2026-09-18: yes to the multiplexer card getting the classic page's mics."""
    assert len( mux_card[ "fields" ] ) == 9, f"the booted card rendered fields { sorted( mux_card[ 'fields' ] ) }"
    assert sorted( mux_card[ "mics" ] ) == [ "details", "title" ], (
        f"the multiplexer's card has mics { sorted( mux_card[ 'mics' ] ) } — boot.ts must hand the task "
        f"list a recorder, or the card is built without any" )


@pytest.mark.parametrize( "field", [ "title", "details" ] )
def test_each_booted_multiplexer_mic_butts_against_its_field( mux_card, field ):
    """The same geometry as the first half, on the card the multiplexer really opens."""
    assert field in mux_card[ "mics" ], f"the booted multiplexer card has no { field } mic"
    mic, box = mux_card[ "mics" ][ field ], mux_card[ "fields" ][ field ]
    gap = box[ "left" ] - mic[ "right" ]
    assert abs( gap ) <= EDGE_TOLERANCE_PX, (
        f"multiplexer (booted): the { field } mic's right edge is at { mic['right']:.1f}px and the field's "
        f"left edge at { box['left']:.1f}px — a { gap:.1f}px gap" )
    assert box[ "top" ] - EDGE_TOLERANCE_PX <= mic[ "top" ] and mic[ "bottom" ] <= box[ "bottom" ] + EDGE_TOLERANCE_PX, (
        f"multiplexer (booted): the { field } mic is not beside its field" )
    assert mux_card[ "hits" ][ field ], f"multiplexer (booted): a click at the { field } mic's centre misses it"
