"""
E2E UI — row 47759aa3: a history doc link clicked in VERTICAL layout renders the pane
WHERE THE USER CAN SEE IT.

Rick's ruling 2026-09-26, verbatim: the content renders "on top of the vertical accordion
stack" or on the right, following the layout the user chose.

🔴 WHY THIS TEST IS AT THIS ALTITUDE AND NOT IN THE UNIT TIER. The unit tests
(doc_link_opens_in_app_in_every_layout.test.ts, both clients) prove the click is CLAIMED
and the pane is asked to open. They cannot see geometry, and geometry is where this row's
second defect lived. Chloé measured it 2026-09-26: with the JS guard removed and no CSS,
an opened pane in vertical was 1568x80 px at y=4584 — below the whole accordion,
off-screen, its body 40px — because every geometry rule in both stylesheets gates on
`body[data-layout-mode="horizontal"]`. So the JS-only fix would have turned "opens in the
wrong place" into "opens nowhere visible", and a silent no-op is WORSE than a wrong-place
render: there is nothing for the user to complain about, so nobody reports it.

⇒ Mr. Radio's requirement, stated as such: assert the pane is IN THE VIEWPORT, not merely
in the DOM. `hidden` removed and `pane-open` set are both true of the broken state.

WHAT MAKES THE PASS MEAN SOMETHING. The assertion is an overlap of the pane's client rect
with the visible box, plus a minimum of 100px in BOTH dimensions, plus `position: fixed`.
Each is there for a measured reason: the broken geometry was `static` (so it scrolled away
with the document), ~6,700-7,000 px down the page (zero overlap), and collapsed to 150px
of iframe (a "postage stamp" the stylesheet header already warns about). A test asserting
only "width > 0" passes on all of it.

⚠️ THIS TEST NEEDS THE BRANCH'S CSS TO BE SERVED. :8000 serves the main checkout, so it
fails on a container that predates the merge — that is correct behaviour for a merge gate,
not a flake. Chloé verified the same geometry pre-merge with Playwright route interception
(branch bytes fulfilled in place of the served ones); that rig is not checked in, because a
rig that swaps the bytes cannot guard the bytes that ship.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).
"""

import pytest

from .conftest import BASE_URL

# A real, whitelisted doc path — the interceptor only fires on this prefix.
_DOC_HREF     = "/app/docs?path=lupin/CLAUDE.md"
_DOC_LINK_MD  = f"[View the guide]({_DOC_HREF})"
# Below this, in either dimension, the pane is the collapsed "postage stamp" the
# stylesheet warns about rather than something a person can read.
_MIN_USABLE_PX = 100


def _layout_mode( page ):
    return page.evaluate( "() => document.body.getAttribute( 'data-layout-mode' )" )


def _ensure_vertical( page ):
    """
    Reach vertical through the REAL toggle, never by writing the attribute.

    Writing `data-layout-mode` would set the CSS selector's input without running the
    app's own open path — which is the mistake that cost Chloé a false negative on
    2026-09-26: her probe forced `pane-open` but not `pane.hidden = false`, so
    `.content-pane[hidden] { display: none }` made every arm measure 0x0 and the
    instrument stopped discriminating entirely.
    """
    if _layout_mode( page ) != "vertical":
        page.locator( "#layout-mode-toggle" ).click()
        page.wait_for_timeout( 150 )
    assert _layout_mode( page ) == "vertical", \
        f"could not reach vertical layout through the toggle; got {_layout_mode( page )!r}"


def _pane_geometry( page ):
    """
    The pane's real geometry, plus its overlap with the visible box.

    `in_viewport` is the load-bearing field: a pane can be in the DOM, not `hidden`, and
    carry `pane-open`, and still be thousands of pixels below the fold. That was the
    measured broken state, and every weaker assertion passes on it.
    """
    return page.evaluate(
        """( minPx ) => {
            const pane = document.getElementById( 'content-pane' );
            if ( !pane ) return { present: false };
            const r  = pane.getBoundingClientRect();
            const cs = getComputedStyle( pane );
            const vw = window.innerWidth, vh = window.innerHeight;
            const overlapW = Math.max( 0, Math.min( r.right,  vw ) - Math.max( r.left, 0 ) );
            const overlapH = Math.max( 0, Math.min( r.bottom, vh ) - Math.max( r.top,  0 ) );
            const frame = pane.querySelector( 'iframe' );
            return {
                present     : true,
                hidden      : pane.hasAttribute( 'hidden' ),
                pane_open   : !!document.querySelector( '.content-shell.pane-open' ),
                position    : cs.position,
                z_index     : cs.zIndex,
                width       : Math.round( r.width ),
                height      : Math.round( r.height ),
                top         : Math.round( r.top ),
                overlap_w   : Math.round( overlapW ),
                overlap_h   : Math.round( overlapH ),
                in_viewport : overlapW >= minPx && overlapH >= minPx,
                iframe_src  : frame ? frame.getAttribute( 'src' ) : None_,
                iframe_h    : frame ? Math.round( frame.getBoundingClientRect().height ) : -1,
            };
        }""".replace( "None_", "null" ),
        _MIN_USABLE_PX,
    )


def _click_first_history_doc_link( page ):
    """
    Click a doc anchor that this test PLANTED via a real notification, never an ambient
    one. Chloé measured 5 live doc anchors per client on the real page, and depending on
    them would make this test pass or fail on whatever history happens to hold — a loop
    over nothing passes every assertion in it.
    """
    anchors = page.locator( f'a[href*="/app/docs?path="]' )
    count   = anchors.count()
    assert count > 0, \
        "no doc anchor rendered — the emitted notification did not produce one, so the " \
        "click below would have nothing to act on and every geometry assertion would be vacuous"
    anchors.first.click()
    page.wait_for_timeout( 400 )
    return count


def _assert_pane_visible( geom, client ):
    assert geom[ "present" ] is True, f"{client}: #content-pane is not in the DOM at all"
    assert geom[ "hidden" ] is False, \
        f"{client}: the pane is still [hidden], so the click never opened it: {geom}"
    assert geom[ "pane_open" ] is True, \
        f"{client}: .content-shell.pane-open was never set: {geom}"
    # 🔴 THE ONE THAT WOULD HAVE CAUGHT THE JS-ONLY FIX.
    assert geom[ "in_viewport" ] is True, (
        f"{client}: the pane opened but is NOT IN THE VIEWPORT — this is the silent no-op "
        f"a JS-only fix produces. Measured broken state for comparison: position static, "
        f"~6,700-7,000px down the document, zero visible height. Got: {geom}"
    )
    assert geom[ "position" ] == "fixed", (
        f"{client}: vertical mode needs the pane as a FIXED overlay — that is what gives it "
        f"a definite height for the iframe's height:100% to resolve against. In normal flow "
        f"it lands below the accordion at its natural height. Got position={geom[ 'position' ]!r}"
    )
    assert geom[ "width" ] >= _MIN_USABLE_PX and geom[ "height" ] >= _MIN_USABLE_PX, (
        f"{client}: the pane is smaller than {_MIN_USABLE_PX}px in some dimension — the "
        f"collapsed 'postage stamp' the stylesheet warns about. Got: {geom}"
    )
    assert geom[ "iframe_src" ] is not None and "/app/docs?path=" in geom[ "iframe_src" ], (
        f"{client}: the pane is visible but holds no doc iframe, so it is an empty overlay "
        f"rather than the document the user clicked. Got iframe_src={geom[ 'iframe_src' ]!r}"
    )
    assert geom[ "iframe_h" ] >= _MIN_USABLE_PX, (
        f"{client}: the iframe collapsed to {geom[ 'iframe_h' ]}px. height:100% resolves "
        f"against the pane, so this is the symptom of a pane with no definite height"
    )


class TestDocLinkPaneIsInTheViewportInVertical:
    """One case per web client. Both shipped the same defect and the same fix."""

    def test_legacy_vertical_doc_link_pane_is_in_the_viewport( self, notifications_page ):
        page = notifications_page
        _ensure_vertical( page )

        page.evaluate(
            """( md ) => {
                window.notificationsUI.handleNotificationUpdate( {
                    notification: {
                        id                 : 'doclink-viewport-legacy',
                        id_hash            : 'doclink-viewport-legacy',
                        type               : 'custom',
                        priority           : 'medium',
                        response_requested : false,
                        message            : md,
                        title              : 'A doc link in the history',
                        timestamp          : new Date().toISOString(),
                    }
                } );
            }""",
            _DOC_LINK_MD,
        )
        page.wait_for_timeout( 300 )

        _click_first_history_doc_link( page )
        _assert_pane_visible( _pane_geometry( page ), "legacy" )

    def test_multiplexer_vertical_doc_link_pane_is_in_the_viewport( self, logged_in_page ):
        page = logged_in_page
        page.goto( f"{BASE_URL}/app/multiplexer" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            "() => window.__multiplexerTestHook"
            " && window.__multiplexerTestHook.stores"
            " && window.__multiplexerTestHook.stores.readingPane",
            timeout=15000,
        )
        # 🔴 NO `wait_for_ws_connected( page )` HERE, AND THAT IS THE FIX (ts-e09fb548,
        # 2026-09-27). This test shipped with that call and it can never succeed on this
        # page: the helper's predicate is
        # `document.getElementById( "queue-ws-status" ).textContent.includes( "Connected" )`
        # (conftest.py:1097), and `queue-ws-status` occurs ZERO times in
        # static/html/multiplexer.html and once in static/html/notifications.html. It is
        # the LEGACY page's status readout. The multiplexer page has no ws-status element
        # at all — its status sections are `#fleet-status-pane` and `#system-status-pane`
        # (multiplexer.html:252 and :361), which carry `data-testid` attributes of
        # `multiplexer-fleet-status-pane` / `multiplexer-system-status-pane`.
        #
        # ⚠️ THIS SENTENCE USED TO WRITE THE TEST IDS WITH A `#`, AS THOUGH THEY WERE THE
        # ELEMENT IDS. They are not — the `multiplexer-` prefix belongs to `data-testid`, and
        # the ids have no prefix. `test_no_probe_names_a_dead_selector` reads a `#name` in this
        # file as a probe's ID selector and correctly reported both as shipping nowhere, which
        # they do not, as ids. Two names for one element, and the notation is what tells them
        # apart. (Caught via the unit tier, 2026-09-27.)
        #
        # So the wait burned its full 10s in setup on every run and the test never reached
        # a single assertion. Its sibling above passes because `notifications_page` opens
        # the page where that element exists; the two differ in exactly that.
        #
        # ⚠️ The readiness signal this page DOES have is the one already waited on
        # immediately above — `__multiplexerTestHook.stores.readingPane`, which only
        # exists once boot has wired the stores. That is the in-tree pattern
        # (`_open_multiplexer` in test_multiplexer_action_required_in_pane.py:40 waits on
        # the hook and nothing else). Adding a second, page-appropriate socket wait would
        # need a multiplexer ws-status element to exist first; do not reach for the legacy
        # helper again.
        _ensure_vertical( page )

        page.evaluate(
            """( md ) => {
                window.__multiplexerTestHook.bus.emit( {
                    type    : 'notification_queue_update',
                    payload : { notification: {
                        id_hash   : 'doclink-viewport-mux',
                        type      : 'custom',
                        priority  : 'medium',
                        message   : md,
                        sender_id : 'e2e-doclink',
                        timestamp : new Date().toISOString(),
                    } },
                    source : 'e2e',
                    ts     : Date.now(),
                } );
            }""",
            _DOC_LINK_MD,
        )
        page.wait_for_timeout( 400 )

        _click_first_history_doc_link( page )
        _assert_pane_visible( _pane_geometry( page ), "multiplexer" )
