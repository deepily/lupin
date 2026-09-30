"""
Screenshot the New Ticket card's mics as efaa004b renders them.

Serves the worktree's static tree on a scratch port — NOT :7999 and NOT :8000, so no
venue is touched — and drives headless chromium over it. Read-only against the repo.
"""

import functools
import http.server
import socketserver
import threading
import sys

from playwright.sync_api import sync_playwright

ROOT = "/mnt/DATA01/include/www.deepily.ai/projects/lupin/.claude/worktrees/maya-shot-f9a449c3/src/lupin_app"
PORT = 8791
OUT  = "/tmp/claude-1001/-mnt-DATA01-include-www-deepily-ai-projects-lupin--claude-worktrees-seat-cc-author-maria-2/ba7be8c3-4cf9-4629-8c3d-ae429a97b980/scratchpad"


class Handler( http.server.SimpleHTTPRequestHandler ):
    """Maps /static/... onto the worktree's static dir; silent, so the log stays readable."""

    def translate_path( self, path ):
        path = path.split( "?", 1 )[ 0 ].split( "#", 1 )[ 0 ]
        if path.startswith( "/static/" ):
            return ROOT + path
        return ROOT + "/static" + path

    def log_message( self, *args ):
        pass


def main():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer( ( "127.0.0.1", PORT ), Handler )
    threading.Thread( target=httpd.serve_forever, daemon=True ).start()

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for client in ( "classic", "mux" ):
            page = browser.new_page( viewport={ "width": 1280, "height": 900 },
                                     device_scale_factor=2 )
            page.goto( f"http://127.0.0.1:{PORT}/html/maya-mic-shot.html?client={client}",
                       wait_until="networkidle" )
            page.wait_for_function( "window.__READY__ === true", timeout=10000 )

            card = page.locator( ".new-ticket-card" )
            card.screenshot( path=f"{OUT}/mics-{client}-card.png" )
            page.screenshot( path=f"{OUT}/mics-{client}-page.png" )

            # The numbers behind the picture, so the caption is measured, not eyeballed.
            box = page.evaluate( """() => {
                const r = ( sel ) => { const e = document.querySelector( sel );
                    const b = e.getBoundingClientRect();
                    return { l: Math.round(b.left), r: Math.round(b.right),
                             t: Math.round(b.top), b: Math.round(b.bottom),
                             w: Math.round(b.width), h: Math.round(b.height) }; };
                const style = ( sel ) => { const c = getComputedStyle( document.querySelector( sel ) );
                    return { fontSize: c.fontSize, minWidth: c.minWidth, padding: c.padding }; };
                return {
                    titleField : r( '[data-field="title"]' ),
                    titleMic   : r( '[data-mic-field="title"]' ),
                    detailsField: r( '[data-field="details"]' ),
                    detailsMic : r( '[data-mic-field="details"]' ),
                    micStyle   : style( '[data-mic-field="title"]' ),
                };
            }""" )
            results.append( ( client, box ) )
            page.close()
        browser.close()
    httpd.shutdown()

    for client, b in results:
        tf, tm = b[ "titleField" ], b[ "titleMic" ]
        df, dm = b[ "detailsField" ], b[ "detailsMic" ]
        print( f"\n=== {client} ===" )
        print( f"  mic style            : {b['micStyle']}" )
        print( f"  title field  l/r/t/b : {tf['l']}/{tf['r']}/{tf['t']}/{tf['b']}  ({tf['w']}x{tf['h']})" )
        print( f"  title mic    l/r/t/b : {tm['l']}/{tm['r']}/{tm['t']}/{tm['b']}  ({tm['w']}x{tm['h']})" )
        print( f"  → mic right edge vs field right edge : {tm['r'] - tf['r']:+d}px" )
        print( f"  → mic top vs field bottom            : {tm['t'] - tf['b']:+d}px  "
               f"({'BELOW the field' if tm['t'] >= tf['b'] else 'overlapping/beside'})" )
        print( f"  details field l/r/t/b: {df['l']}/{df['r']}/{df['t']}/{df['b']}  ({df['w']}x{df['h']})" )
        print( f"  details mic   l/r/t/b: {dm['l']}/{dm['r']}/{dm['t']}/{dm['b']}  ({dm['w']}x{dm['h']})" )
        print( f"  → mic right edge vs field right edge : {dm['r'] - df['r']:+d}px" )
        print( f"  → mic top vs field bottom            : {dm['t'] - df['b']:+d}px  "
               f"({'BELOW the field' if dm['t'] >= df['b'] else 'overlapping/beside'})" )
    print( f"\nwrote {OUT}/mics-<client>-card.png and -page.png" )
    return 0


if __name__ == "__main__":
    sys.exit( main() )
