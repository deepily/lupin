#!/usr/bin/env python3
"""
IS THE FLEET-SIZE DIAL REACHABLE AT THE REAL PANE WIDTH, OR MERELY PRESENT?

🔴 THE PRECEDENT, AND IT IS WHY A DOM ASSERTION IS NOT ENOUGH. On 2026-09-03 the holding
area's per-row editor was fully rendered, fully wired, and **108 pixels off the right-hand
edge of the world**: the task table is 1065px, the pane is 916px, and `.section-content`
clips at `overflow-x: hidden`. Every unit assertion was green. `document.elementFromPoint`
over the control's centre returned null. Rick reported that the editor did not exist —
and from a chair, unreachable and absent are the same observation.

⇒ So this enters at GEOMETRY IN A REAL BROWSER. It reads bounding boxes and hit-tests,
never `querySelector`. A presence assertion is the assertion that was already passing.

⚠️ WHAT IT DOES **NOT** COVER, stated before the result rather than after it. It renders
the fleet section's own markup inside a 916px container with the real stylesheet, so it
cannot see a defect in which SOMETHING ELSE ON THE PAGE pushes the dial out of view. Real
geometry, partial page — narrower than a full-page E2E and not to be quoted as one.

⚠️ VENUE: **:7999**, and it is in `smoke/` by the RUBRIC rather than by the folder name.
It mutates nothing, needs no server at all (it renders from the files on disk), takes a
few seconds and needs no monopoly. It is NOT in `e2e_ui/` precisely because that suite's
conftest requires a live server on :8000 and this one must not imply it needs one.
"""
import os
import sys

import pytest

ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
PANE = 916          # the measured pane width from the per-row-editor incident

playwright_api = pytest.importorskip( "playwright.sync_api",
                                      reason="playwright is not installed in this venv" )


def _page_source():
    """The real stylesheet, the real dial markup and the real painter, in one document."""
    html = open( os.path.join( ROOT, "src/lupin_app/static/html/notifications.html" ) ).read()
    css  = open( os.path.join( ROOT, "src/lupin_app/static/css/notifications.css" ) ).read()
    js   = open( os.path.join( ROOT, "src/lupin_app/static/js/notifications.js" ) ).read()

    start = html.index( '<div class="fleet-size-cap-controls"' )
    end   = html.index( "</div>", html.index( 'class="fleet-size-cap-status"' ) ) + len( "</div>" )
    end   = html.index( "</div>", end ) + len( "</div>" )
    dial  = html[ start:end ]
    assert 'data-testid="fleet-size-cap"' in dial, "sliced the wrong fragment"

    # The class, sliced before its DOM-ready init — the same harness the TS suite uses.
    klass = js[ : js.index( "// Initialize when DOM is ready" ) ]

    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body {{ margin: 0; }}
#pane {{ width: {PANE}px; overflow-x: hidden; }}
{css}
</style></head><body><div id="pane"><div id="section-fleet-status">{dial}
<div id="fleet-status-container"></div></div></div>
<script>{klass}
window.__ui = Object.create( NotificationsUI.prototype );
window.__ui.debug = false; window.__ui.log = function(){{}}; window.__ui.error = function(){{}};
window.__calls = [];
window.__ui.authedFetch = async function( url, init ) {{
  window.__calls.push( {{ url: url, init: init }} );
  return {{ ok: true, status: 200, json: async function() {{
      return {{ cap: 9, ceiling: 18, live: {{ total: 6, managers: 2, workers: 4 }} }}; }} }};
}};
window.__ui._paintFleetSizeCap( {{ cap: 4, ceiling: 18,
                                   live: {{ total: 6, managers: 2, workers: 4 }} }} );
</script></body></html>"""


@pytest.fixture( scope="module" )
def dial_page():
    with playwright_api.sync_playwright() as pw:
        browser = pw.chromium.launch()
        page    = browser.new_page( viewport={ "width": PANE, "height": 900 } )
        page.set_content( _page_source() )
        page.wait_for_timeout( 250 )
        yield page
        browser.close()


@pytest.mark.parametrize( "name,selector", [
    ( "slider", '[data-testid="fleet-size-cap"]' ),
    ( "value",  '[data-testid="fleet-size-cap-value"]' ),
    ( "status", '[data-testid="fleet-size-cap-status"]' ),
] )
def test_every_part_of_the_dial_is_inside_the_pane( dial_page, name, selector ):
    """No part of the cluster may sit outside the 916px pane that clips its container."""
    pane = dial_page.eval_on_selector( "#pane", "e => e.getBoundingClientRect().toJSON()" )
    box  = dial_page.eval_on_selector( selector, "e => e.getBoundingClientRect().toJSON()" )
    assert box[ "left" ]  >= pane[ "left" ]  - 0.5, f"{name} starts left of the pane: {box}"
    assert box[ "right" ] <= pane[ "right" ] + 0.5, (
        f"{name} extends {box['right'] - pane['right']:.1f}px past the pane's right edge "
        f"({box['right']:.1f} vs {pane['right']:.1f}). This is the per-row-editor defect: "
        f"present in the DOM, unreachable from a chair." )


def test_a_click_at_the_sliders_centre_actually_REACHES_the_slider( dial_page ):
    """
    🔴 THE CHECK THAT CAUGHT THE PRECEDENT. A box can be inside the pane and still be
    covered by something else; `elementFromPoint` asks the browser what a real click at
    that point would hit. On the per-row editor it returned null.
    """
    hit = dial_page.evaluate( """() => {
        const s = document.querySelector('[data-testid="fleet-size-cap"]');
        const b = s.getBoundingClientRect();
        const el = document.elementFromPoint( b.x + b.width / 2, b.y + b.height / 2 );
        return el === null ? null : ( el.dataset.testid || el.tagName );
    }""" )
    assert hit == "fleet-size-cap", f"a click at the slider's centre reaches {hit!r}"


def test_a_REAL_mouse_drag_fires_exactly_one_write_on_RELEASE( dial_page ):
    """
    The on-release contract, measured at the layer a FINGER enters at rather than through
    a synthetic `dispatchEvent`. A range input fires `input` continuously while the handle
    moves, so a write bound there turns one drag into a write per pixel — this drives the
    browser's own input pipeline and counts what reached the network.
    """
    dial_page.evaluate( "() => { window.__calls = []; }" )
    box = dial_page.locator( '[data-testid="fleet-size-cap"]' ).bounding_box()
    dial_page.mouse.move( box[ "x" ] + box[ "width" ] * 0.5, box[ "y" ] + box[ "height" ] / 2 )
    dial_page.mouse.down()
    dial_page.mouse.move( box[ "x" ] + box[ "width" ] * 0.9, box[ "y" ] + box[ "height" ] / 2, steps=8 )
    dial_page.mouse.up()
    dial_page.wait_for_timeout( 250 )

    calls = dial_page.evaluate( "() => window.__calls" )
    puts  = [ c for c in calls if ( c.get( "init" ) or { } ).get( "method" ) == "PUT" ]
    assert len( puts ) == 1, f"one drag+release is one PUT — saw {len( puts )} of {len( calls )} calls"
    assert puts[ 0 ][ "url" ] == "/api/arbiter/fleet-size-cap"


def test_the_handle_follows_the_SERVER_not_the_finger( dial_page ):
    """
    The fake server answers 9 whatever was dragged to. A dial painting its own input would
    show the dragged value while the spawn path enforced 9 — and nothing on screen would
    say so. Runs after the drag above, so it reads the state that drag left behind.
    """
    assert dial_page.eval_on_selector( '[data-testid="fleet-size-cap"]', "e => e.value" ) == "9"
