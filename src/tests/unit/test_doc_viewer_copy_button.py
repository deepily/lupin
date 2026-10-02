"""
Unit tests for the doc viewer's 📋 Copy button (row 20e26936).

The viewer's script is inline in document-viewer.html, so there is no module to import. The
functions are sliced out of the served page by their own anchors and run under node against
small fakes of `document`, `navigator` and `window`. The slice is the code the browser runs,
not a copy of it.

Venue: :7999 (unit, no server).
"""

import json
import re
import shutil
import subprocess
import unittest

import cosa.utils.util as cu

_HTML = cu.get_project_root() + "/src/lupin_app/static/html/document-viewer.html"
_NODE = shutil.which( "node" )

_START = "function isCopyableType("
_END   = "// Ticket 416d4b00 — the viewer path of the folder a file lives in."

_HARNESS = r"""
const src = process.argv[ 1 ];
const scenario = JSON.parse( process.argv[ 2 ] );

function makeEl( id ) {
    const el = { id, dataset: {}, hidden: true, disabled: false, textContent: id === "doc-copy-btn" ? "📋 Copy" : "",
                 title: "", style: {}, listeners: {}, removed: false };
    el.addEventListener = ( ev, fn ) => { el.listeners[ ev ] = fn; };
    el.setAttribute = () => {};
    el.select = () => {};
    el.remove = () => { el.removed = true; };
    return el;
}
const els = { "doc-viewer-toolbar": makeEl( "doc-viewer-toolbar" ), "doc-copy-btn": makeEl( "doc-copy-btn" ),
              "doc-download-status": makeEl( "doc-download-status" ) };
const created = [];
global.document = {
    getElementById: ( id ) => scenario.missingBar && id === "doc-viewer-toolbar" ? null : els[ id ],
    createElement: () => { const t = makeEl( "ta" ); created.push( t ); return t; },
    body: { appendChild: () => {} },
    execCommand: ( cmd ) => { global.__execCmd = cmd; if ( scenario.execThrows ) throw new Error( "boom" ); return scenario.execOk; },
};
const written = [];
// Node 22 ships its own read-only `navigator`, so plain assignment is silently ignored.
const setNav = ( v ) => Object.defineProperty( globalThis, "navigator", { value: v, configurable: true, writable: true } );
if ( scenario.clipboard === "ok" ) {
    setNav( { clipboard: { writeText: async ( t ) => { written.push( t ); } } } );
} else if ( scenario.clipboard === "rejects" ) {
    setNav( { clipboard: { writeText: async () => { throw new Error( "Copy failed: denied" ); } } } );
} else {
    setNav( {} );
}
global.window = { __docViewerAuthedFetch: async ( url ) => {
    global.__fetched = url;
    return { ok: scenario.httpOk, status: scenario.httpOk ? 200 : 403, text: async () => scenario.body };
} };
let timer = null;
global.setTimeout = ( fn ) => { timer = fn; };

const api = new Function( src + "; return { isCopyableType, writeToClipboard, wireCopy };" )();

( async () => {
    const out = {};
    if ( scenario.op === "types" ) {
        out.results = scenario.cases.map( ( [ ct, name ] ) => api.isCopyableType( ct, name ) );
    } else if ( scenario.op === "wire" ) {
        api.wireCopy( "/api/docs/file?path=x", scenario.copyable );
        if ( scenario.twice ) api.wireCopy( "/api/docs/file?path=x", scenario.copyable );
        const btn = els[ "doc-copy-btn" ];
        out.hidden = btn.hidden; out.disabled = btn.disabled; out.title = btn.title;
        out.barHidden = els[ "doc-viewer-toolbar" ].hidden;
        out.listenerCount = Object.keys( btn.listeners ).length;
        if ( scenario.click ) {
            await btn.listeners.click();
            out.label = btn.textContent;
            out.status = els[ "doc-download-status" ].textContent;
            out.disabledAfter = btn.disabled;
            out.written = written;
            out.fetched = global.__fetched || null;
            out.execCmd = global.__execCmd || null;
            out.taValue = created.length ? created[ 0 ].value : null;
            out.taRemoved = created.length ? created[ 0 ].removed : null;
            if ( timer ) { timer(); out.labelAfterTimer = btn.textContent; }
        }
    }
    console.log( JSON.stringify( out ) );
} )();
"""


def _slice():
    with open( _HTML, encoding="utf-8" ) as f: text = f.read()
    assert text.count( _START ) == 1, "isCopyableType anchor must match exactly once"
    assert text.count( _END ) == 1, "end anchor must match exactly once"
    return text[ text.index( _START ) : text.index( _END ) ]


def _run( **scenario ):
    base = { "clipboard": "ok", "httpOk": True, "body": "# raw\n", "execOk": True }
    base.update( scenario )
    proc = subprocess.run( [ _NODE, "-e", _HARNESS, _slice(), json.dumps( base ) ],
                           capture_output=True, text=True, timeout=30 )
    assert proc.returncode == 0, proc.stderr
    return json.loads( proc.stdout )


@unittest.skipUnless( _NODE, "node is required to run the viewer's inline script" )
class TestDocViewerCopyButton( unittest.TestCase ):

    def test_text_types_are_copyable_and_binary_types_are_not( self ):
        cases = [
            [ "text/markdown; charset=utf-8", "a.md" ], [ "text/x-python", "a.py" ], [ "text/plain", "a.txt" ],
            [ "application/json", "data.JSON" ],
            [ "application/json", "dir" ], [ "application/json", "" ],
            [ "image/png", "a.png" ], [ "audio/mpeg", "a.mp3" ], [ "video/mp4", "a.mp4" ],
            [ "application/pdf", "a.pdf" ], [ "application/octet-stream", "a.bin" ], [ "", "a" ],
        ]
        got = _run( op="types", cases=cases )[ "results" ]
        self.assertEqual( [ True, True, True, True, False, False, False, False, False, False, False, False ], got )

    def test_text_file_enables_the_button_and_copies_the_raw_body( self ):
        out = _run( op="wire", copyable=True, click=True, body="# raw **source**\n" )
        self.assertFalse( out[ "hidden" ] )
        self.assertFalse( out[ "barHidden" ] )
        self.assertEqual( [ "# raw **source**\n" ], out[ "written" ] )
        self.assertEqual( "/api/docs/file?path=x", out[ "fetched" ] )
        self.assertEqual( "✓ Copied", out[ "label" ] )
        self.assertEqual( "📋 Copy", out[ "labelAfterTimer" ] )
        self.assertEqual( "", out[ "status" ] )
        self.assertFalse( out[ "disabledAfter" ] )

    def test_binary_file_shows_a_disabled_button_with_no_click_handler( self ):
        out = _run( op="wire", copyable=False )
        self.assertFalse( out[ "hidden" ] )
        self.assertTrue( out[ "disabled" ] )
        self.assertIn( "Download", out[ "title" ] )
        self.assertEqual( 0, out[ "listenerCount" ] )

    def test_wiring_twice_attaches_one_handler( self ):
        out = _run( op="wire", copyable=True, twice=True )
        self.assertEqual( 1, out[ "listenerCount" ] )

    def test_missing_toolbar_is_a_no_op( self ):
        out = _run( op="wire", copyable=True, missingBar=True )
        self.assertTrue( out[ "hidden" ] )

    def test_http_error_is_reported_beside_the_button_and_nothing_is_copied( self ):
        out = _run( op="wire", copyable=True, click=True, httpOk=False )
        self.assertEqual( "Copy failed (HTTP 403)", out[ "status" ] )
        self.assertEqual( [], out[ "written" ] )
        self.assertEqual( "📋 Copy", out[ "label" ] )
        self.assertFalse( out[ "disabledAfter" ] )

    def test_clipboard_rejection_is_reported_and_the_label_is_not_flipped( self ):
        out = _run( op="wire", copyable=True, click=True, clipboard="rejects" )
        self.assertEqual( "Copy failed: denied", out[ "status" ] )
        self.assertEqual( "📋 Copy", out[ "label" ] )

    def test_insecure_context_falls_back_to_execcommand_on_a_textarea( self ):
        out = _run( op="wire", copyable=True, click=True, clipboard="none", execOk=True, body="plain\n" )
        self.assertEqual( "copy", out[ "execCmd" ] )
        self.assertEqual( "plain\n", out[ "taValue" ] )
        self.assertTrue( out[ "taRemoved" ] )
        self.assertEqual( "✓ Copied", out[ "label" ] )

    def test_fallback_refusal_is_reported_and_the_textarea_is_still_removed( self ):
        out = _run( op="wire", copyable=True, click=True, clipboard="none", execOk=False )
        self.assertIn( "refused clipboard access", out[ "status" ] )
        self.assertTrue( out[ "taRemoved" ] )

    def test_fallback_that_throws_still_removes_the_textarea( self ):
        out = _run( op="wire", copyable=True, click=True, clipboard="none", execThrows=True )
        self.assertEqual( "boom", out[ "status" ] )
        self.assertTrue( out[ "taRemoved" ] )

    def test_the_copy_button_sits_in_the_bar_with_its_test_id( self ):
        with open( _HTML, encoding="utf-8" ) as f: text = f.read()
        self.assertEqual( 1, len( re.findall( r'id="doc-copy-btn"[^>]*data-testid="doc-copy-btn"', text ) ) )
        self.assertEqual( 1, text.count( "wireCopy( fetchUrl, isCopyableType( contentType, filename ) );" ) )


if __name__ == "__main__":
    unittest.main()
