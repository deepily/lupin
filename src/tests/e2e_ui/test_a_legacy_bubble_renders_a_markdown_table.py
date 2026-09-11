"""
A legacy notification bubble renders a markdown table — measured in a real browser (row 5ae3ce90, Step 2).

THE DEFECT. Legacy bubbles render through `NotificationsUI.renderMarkdownInline`, which calls
`marked.parseInline`. A table is a block construct, so parseInline emits the pipes as text and the bubble
shows raw `| a | b |`. That is what Rick saw.

RICK'S RULING, 2026-09-10 (relayed by Mr. Radio): keep legacy minimal, since it is deleted once the
multiplexer is finished. Messages keep parseInline; only a message containing a GFM table goes through the
block renderer, the way a ``` fence already does. `align` joins the block allowlist, and bubbles get table CSS.

WHY A REAL BROWSER. DOMPurify does not sanitize under happy-dom (measured 2026-09-10), and happy-dom does
no CSS cascade, so neither what survives the sanitizer nor what the bubble looks like can be seen in the unit
tier. The routing alone is pinned there too, in unit/notifications_js/bubble_markdown_tables.test.ts.

WHAT THIS FILE RUNS: the REAL notifications.js class (sliced before its DOM-ready init, the same slice the
unit harness uses), the REAL vendored marked.min.js and purify.min.js, and the stylesheets the legacy page
links, in Chromium. It needs no server — the page is built with set_content — and rides the scheduled :8000
E2E run with the rest of e2e_ui.
"""

import pytest

import cosa.utils.util as cu


STATIC = cu.get_project_root() + "/src/lupin_app/static"

TABLE   = "| a | b |\n|---|:-:|\n| 1 | 2 |\n"
MESSAGE = "Board state:\n\n" + TABLE

# Everything the block allowlist must refuse, riding along with a table so the block path is the one taken.
HOSTILE = (
    '<img src="x" onerror="alert(1)">'
    '<form action="https://evil.example"><input name="p"><button>go</button></form>'
    '<style>body{display:none}</style>'
    '<iframe src="https://evil.example"></iframe>'
    '<svg onload="alert(2)"></svg>'
    '<a href="javascript:alert(3)">j</a>'
    '<div onclick="alert(4)" style="position:fixed;inset:0">overlay</div>'
    '<details open ontoggle="alert(5)">x</details>'
    "\n\n" + TABLE
)

# The stylesheets notifications.html links that could reach a bubble.
SHEETS = [ "css/lupin-base.css", "css/shared/notifications-surface.css", "css/notifications.css" ]


@pytest.fixture( scope="module" )
def ui_source():
    """
    notifications.js up to its DOM-ready init, with the class exposed on globalThis.

    Ensures:
        - returns script text that defines globalThis.NotificationsUI and starts nothing
        - fails the fixture when the init marker is gone, rather than running the whole page
    """
    full = open( f"{STATIC}/js/notifications.js" ).read()
    idx  = full.find( "// Initialize when DOM is ready" )
    assert idx > 0, "notifications.js no longer carries its DOM-ready init marker — the slice would run the page"
    return full[ :idx ] + "\n;globalThis.NotificationsUI = NotificationsUI;"


@pytest.fixture
def legacy_page( page, ui_source ):
    """A blank page carrying the vendored libraries, the legacy class and its stylesheets, and nothing from any server."""
    page.set_content( "<!doctype html><html><body></body></html>" )
    for sheet in SHEETS:
        page.add_style_tag( content=open( f"{STATIC}/{sheet}" ).read() )
    page.add_script_tag( content=open( f"{STATIC}/js/vendor/marked.min.js" ).read() )
    page.add_script_tag( content=open( f"{STATIC}/js/vendor/purify.min.js" ).read() )
    page.add_script_tag( content=ui_source )
    assert page.evaluate( "DOMPurify.isSupported" ) is True, "DOMPurify is not running as a real sanitizer on this page"
    return page


def _bubble( page, message ):
    """
    Render one message into a legacy bubble and report what the browser built and how it styled it.

    Ensures:
        - the markup is exactly what the page does: span.message-text inside div.sender-message.incoming
        - returns tags, attributes, handler and javascript: counts, and computed styles of the table cells
    """
    return page.evaluate( """( message ) => {
        const ui = Object.create( NotificationsUI.prototype );
        ui.debug = false; ui.log = () => {}; ui.error = () => {};
        const bubble = document.createElement( "div" );
        bubble.className = "sender-message incoming";
        bubble.style.width = "320px";
        bubble.innerHTML = `<span class="message-text">${ ui.renderMarkdownInline( message ) }</span>`;
        document.body.replaceChildren( bubble );
        const text = bubble.querySelector( ".message-text" );
        const tags = new Set();
        let handlers = 0, jsLinks = 0;
        for ( const el of text.querySelectorAll( "*" ) ) {
            tags.add( el.tagName.toLowerCase() );
            for ( const a of el.attributes ) {
                if ( a.name.startsWith( "on" ) ) handlers++;
                if ( /^\\s*javascript:/i.test( a.value ) ) jsLinks++;
            }
        }
        const table = text.querySelector( "table" );
        const cell  = ( sel ) => { const c = text.querySelector( sel ); return c ? getComputedStyle( c ) : null; };
        const th = cell( "th" ), td = cell( "td" ), centred = cell( "td[align]" );
        const plainTh = cell( "th:not([align])" ), centredTh = cell( "th[align]" );
        return {
            tags     : [ ...tags ].sort(),
            handlers, jsLinks,
            tables   : text.querySelectorAll( "table" ).length,
            aligned  : [ ...text.querySelectorAll( "th[align], td[align]" ) ]
                         .map( c => `${ c.tagName.toLowerCase() }:${ c.textContent }:${ c.getAttribute( "align" ) }` ),
            style    : table ? {
                table_display   : getComputedStyle( table ).display,
                table_overflow  : getComputedStyle( table ).overflowX,
                td_border       : td.borderTopStyle,
                th_border       : th.borderTopStyle,
                th_background   : th.backgroundColor,
                centred_align   : centred ? centred.textAlign : null,
                th_plain_align  : plainTh ? plainTh.textAlign : null,
                th_centred_align: centredTh ? centredTh.textAlign : null,
            } : null,
        };
    }""", message )


@pytest.mark.parametrize( "message", [ MESSAGE, MESSAGE.replace( "\n", "\\n" ) ], ids=[ "real-newlines", "literal-backslash-n" ] )
def test_a_message_with_a_table_renders_a_table( legacy_page, message ):
    # Both newline forms: the stored bytes carry real newlines (Step 0), and the renderer still normalises the
    # literal form that MCP/JSON transport once produced.
    out = _bubble( legacy_page, message )
    assert out[ "tables" ] == 1, f"no table in the bubble — the message went down parseInline: {out[ 'tags' ]}"
    assert { "thead", "tbody", "tr", "th", "td" } <= set( out[ "tags" ] )


def test_a_column_alignment_survives( legacy_page ):
    # marked writes `|:-:|` as align="center" on that column's th and td; column a asks for nothing and carries
    # nothing, which ties the attribute to the markdown.
    assert _bubble( legacy_page, MESSAGE )[ "aligned" ] == [ "th:b:center", "td:2:center" ]


def test_a_message_without_a_table_keeps_the_inline_path( legacy_page ):
    # The ruling's other half: nothing else changes. The block renderer would wrap this in <p>.
    out = _bubble( legacy_page, "hello **world**\nsecond line" )
    assert out[ "tags" ] == [ "br", "strong" ], f"a plain message left the inline path: {out[ 'tags' ]}"


@pytest.mark.parametrize( "message", [ "a | b | c", "| a | b |\n| 1 | 2 |", "cost | time\n--- then more" ] )
def test_pipes_without_a_table_keep_the_inline_path( legacy_page, message ):
    # A GFM table needs a header row AND a delimiter row that match. Pipes in prose, a header with no delimiter,
    # and a delimiter-looking line under non-table text must not be read as a table.
    out = _bubble( legacy_page, message )
    assert out[ "tables" ] == 0 and "p" not in out[ "tags" ], f"{message!r} was treated as a table: {out[ 'tags' ]}"


def test_the_table_path_lets_no_active_content_through( legacy_page ):
    out     = _bubble( legacy_page, HOSTILE )
    assert out[ "tables" ] == 1, "the hostile payload did not take the table path, so this test measured the inline one"
    refused = sorted( set( out[ "tags" ] ) & { "img", "form", "input", "button", "style", "iframe", "svg", "details", "div" } )
    assert ( refused, out[ "handlers" ], out[ "jsLinks" ] ) == ( [], 0, 0 ), out


def test_a_bubble_table_is_styled_and_keeps_its_alignment( legacy_page ):
    style = _bubble( legacy_page, MESSAGE )[ "style" ]
    assert style is not None, "no table rendered, so there was nothing to style"
    assert ( style[ "td_border" ], style[ "th_border" ] ) == ( "solid", "solid" ), f"bubble table cells have no borders: {style}"
    assert style[ "th_background" ] not in ( "rgba(0, 0, 0, 0)", "transparent" ), f"header row is unshaded: {style}"
    # A table wider than the bubble scrolls inside itself, not the card.
    assert ( style[ "table_display" ], style[ "table_overflow" ] ) == ( "block", "auto" ), style
    # CSS text-align beats the align attribute, so a cell rule that sets it would silently undo the column's alignment.
    # Chromium computes an honoured align="center" as `-webkit-center`; a stylesheet override would read `left`.
    honoured = { "center", "-webkit-center" }
    assert { style[ "centred_align" ], style[ "th_centred_align" ] } <= honoured, f"the stylesheet overrode align=center: {style}"
    # Headers that ask for nothing read left, like the abstract's; the browser default would centre them.
    assert style[ "th_plain_align" ] == "left", f"an unaligned header is not left-aligned: {style}"
