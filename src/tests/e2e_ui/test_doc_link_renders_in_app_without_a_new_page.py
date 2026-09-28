"""
E2E UI — row 47759aa3: every in-app doc surface renders in the content pane and opens NO
NEW PAGE, in BOTH clients and BOTH layouts.

Two surfaces, two clients, two layouts — eight cells:

    surface                         legacy /app/notifications      mux /app/multiplexer
    history doc link                vertical · horizontal          vertical · horizontal
    📂 roots button                 vertical · horizontal          vertical · horizontal

WHAT THIS FILE ADDS THAT NOTHING ELSE HAD
-----------------------------------------
🔴 **"WITHOUT OPENING A NEW PAGE" WAS ASSERTED NOWHERE.** The whole point of row 47759aa3
is that a doc link stopped spawning a tab and started rendering in the pane, and every
existing test checks only the second half. `test_doc_link_pane_is_in_the_viewport_in_vertical.py`
asserts geometry — viewport overlap, 100px minimums, `position: fixed` — and the two
`doc_link_opens_in_app_in_every_layout.test.ts` files assert the click is claimed. **A
render into the pane PLUS a stray new tab passes all of them.** That is not a hypothetical
shape: the original defect was a new tab, the fix was `preventDefault`, and
`preventDefault` is exactly the thing a later edit removes by accident.

🔴 **HORIZONTAL HAD NO E2E COVERAGE AT ALL.** The geometry file is vertical-only, by name
and by content, because vertical is where the measured defect lived. The unit files claim
"every layout" and are in-process, so they cannot see a tab open or a pane land off-screen.
Horizontal is the layout Rick actually demos in.

🔴 **THE 📂 ROOTS BUTTON HAD NO TEST AT ANY TIER.** It landed in `c6f52bca8` as the global
entry point to the viewer — `#doc-roots-toggle`, `data-testid="multiplexer-doc-roots-toggle"`
and `notifications-doc-roots-toggle` — and routes through the SAME door a doc link uses
(legacy `_openContentPane( "doc", "/app/docs", "Files" )`, mux
`store.open( "doc", DOC_ROOTS_HREF, "Files" )`). Sharing the door is the design's own
argument that the two cannot drift; that argument is worth nothing until something watches
both ends of it.

WHY A NEW FILE RATHER THAN EXTENDING THE GEOMETRY ONE
-----------------------------------------------------
That file's name states its scope — `_in_vertical` — and its `_assert_pane_visible`
asserts `position: fixed`, which is a VERTICAL property: in horizontal the pane is the
right-hand column in normal flow, not a fixed overlay. Adding horizontal there would either
make the filename lie or make that assertion conditional, weakening the one arm that caught
the JS-only fix. So: geometry stays there, the in-app/no-new-page contract lives here.

⚠️ **THE GEOMETRY PROBE IS IMPORTED, NOT REWRITTEN.** `_pane_geometry`, `_layout_mode`,
`_DOC_HREF`, `_DOC_LINK_MD` and `_MIN_USABLE_PX` all come from that module. Two probes
computing one geometry would agree until they did not, and a disagreement between the files
would then be indistinguishable from a disagreement between their measurements.

PROVING THE NO-NEW-PAGE PROBE CAN SEE A TAB
-------------------------------------------
A "no new page opened" assertion is worth nothing until the same probe has been watched
catching one — an absence measured by a broken instrument looks exactly like an absence.
`test_the_probe_itself_detects_a_new_page` plants an anchor with `target="_blank"` and a
NON-doc href, so no interceptor claims it, clicks it, and asserts BOTH arms of the probe
fire. It runs in the same file, against the same page, through the same helpers.

TWO ARMS, BECAUSE ONE OF THEM CAN MISS
--------------------------------------
The probe watches both `window.open` calls and Playwright's `context.pages`:

  · `window.open` alone misses a plain `target="_blank"` anchor, which the browser honours
    without any script call — and that attribute is precisely what the original bug rode.
  · `context.pages` alone misses a `window.open` the browser suppresses (popup blocking,
    `noopener` handling), and misses the ratified exception's deliberate call if it is ever
    silently dropped.

Neither is a superset of the other, so both are read and both are asserted.

A DELIBERATE INEQUALITY THIS FILE DOES NOT TOUCH
------------------------------------------------
`#action-required-content` and `.abstract-tooltip` doc links DO open a new tab, by ruling
(María + Rick, 2026-09-26) and via an EXPLICIT `window.open` since the markdown renderers
stopped stamping `target="_blank"`. That exception is owned by
`test_action_required_self_content_pane.py` (see `test_tooltip_self_doc_link_opens_new_tab_via_explicit_window_open`),
and nothing here asserts over it. Named rather than skipped silently: a reader who finds
"no doc link may open a tab" in this file needs to know where the exception is guarded, or
they will "fix" it.

Venue: :8000 (scheduled monopolize-mode via `POST /api/test-suite/submit`) — the
`logged_in_page` / `notifications_page` fixtures register a user, which is a persistent
write, and this drives a real browser.
"""

import pytest

from .conftest import BASE_URL
from .test_doc_link_pane_is_in_the_viewport_in_vertical import (
    _DOC_LINK_MD,
    _MIN_USABLE_PX,
    _layout_mode,
    _pane_geometry,
)

# Both pages carry the same two ids — verified on b96f2ba5a: `id="layout-mode-toggle"` and
# `id="content-pane"` each occur exactly once in multiplexer.html and once in
# notifications.html. That is what lets one set of helpers drive both clients, and a
# divergence here would be a real parity break rather than a test problem.
_LAYOUT_TOGGLE = "#layout-mode-toggle"
_ROOTS_BUTTON  = "#doc-roots-toggle"

# A `target="_blank"` anchor pointing at something NO interceptor claims, for the probe's
# positive control. `about:blank` is deliberate: it opens a real page in the context without
# navigating the app or depending on any route staying alive.
_UNCLAIMED_BLANK_HREF = "about:blank"

LAYOUTS = [ "vertical", "horizontal" ]


# ── the no-new-page probe ─────────────────────────────────────────────────────

def _install_open_probe( page ):
    """
    Record every `window.open` call on the page, without changing what it does.

    Requires:
        - page is a live Playwright page

    Ensures:
        - `window.__openCalls` is an array of the urls passed to window.open thereafter
        - window.open still behaves normally, so a deliberate new tab still opens and the
          probe observes rather than suppresses it
    """
    page.evaluate(
        """() => {
            window.__openCalls = [];
            const realOpen = window.open;
            window.open = function( url, target, features ) {
                window.__openCalls.push( String( url ) );
                return realOpen.call( window, url, target, features );
            };
        }"""
    )


def _open_calls( page ):
    return page.evaluate( "() => ( window.__openCalls || [] ).slice()" )


def _assert_no_new_page( page, pages_before, surface ):
    """
    Assert BOTH arms: no scripted `window.open`, and no extra page in the context.

    Requires:
        - _install_open_probe was called on this page
        - pages_before is len( page.context.pages ) captured before the click

    Ensures:
        - returns None when neither arm fired

    Raises:
        - AssertionError naming which arm fired and what it saw
    """
    calls = _open_calls( page )
    assert calls == [], (
        f"{surface}: window.open was called {len( calls )} time(s) — {calls}. Row 47759aa3's "
        f"whole point is that this surface renders in the content pane instead of spawning a "
        f"tab. If this is the ratified #action-required-content / .abstract-tooltip "
        f"exception, it does not belong in this file — that one is guarded in "
        f"test_action_required_self_content_pane.py."
    )

    pages_after = len( page.context.pages )
    assert pages_after == pages_before, (
        f"{surface}: the browser context went from {pages_before} page(s) to {pages_after}. "
        f"A plain target=\"_blank\" anchor opens a tab with NO window.open call, which is "
        f"exactly what the original defect rode — so this arm catches what the arm above "
        f"cannot."
    )


# ── layout ────────────────────────────────────────────────────────────────────

def _set_layout( page, wanted ):
    """
    Reach `wanted` layout through the REAL toggle, never by writing the attribute.

    Writing `data-layout-mode` sets the CSS selector's input without running the app's own
    open path, which cost a false negative on 2026-09-26 — the probe forced `pane-open` but
    not `pane.hidden = false`, so `.content-pane[hidden] { display: none }` made every arm
    measure 0x0 and the instrument stopped discriminating.

    Requires:
        - page is on a client page carrying #layout-mode-toggle
        - wanted is "vertical" or "horizontal"

    Ensures:
        - body[data-layout-mode] reads `wanted`
        - clicks at most twice, so a toggle that does not move fails loudly
    """
    for _ in range( 2 ):
        if _layout_mode( page ) == wanted: break
        page.locator( _LAYOUT_TOGGLE ).click()
        page.wait_for_timeout( 200 )
    assert _layout_mode( page ) == wanted, (
        f"could not reach {wanted!r} through {_LAYOUT_TOGGLE}; body[data-layout-mode] is "
        f"{_layout_mode( page )!r}. The toggle is the only sanctioned route — do not write "
        f"the attribute."
    )


def _assert_pane_holds_a_doc( geom, surface, layout ):
    """
    The pane is open, on screen, usably sized, and showing a doc — in either layout.

    ⚠️ `position` IS NOT ASSERTED HERE, and that is the one difference from the geometry
    file's `_assert_pane_visible`. Vertical needs a FIXED overlay (that is what gives the
    iframe's `height: 100%` something to resolve against); horizontal is the right-hand
    column in normal flow. Asserting `fixed` across both would be wrong in one of them, and
    asserting neither would drop the arm that caught the JS-only fix — so the vertical-only
    `fixed` assertion stays where it is, in that file, and this one asserts what both share.

    Requires:
        - geom came from _pane_geometry
        - layout is the layout the click happened in, for the message only

    Raises:
        - AssertionError naming the surface, the layout and the geometry
    """
    where = f"{surface} / {layout}"
    assert geom[ "present" ] is True,   f"{where}: #content-pane is not in the DOM at all"
    assert geom[ "hidden" ]  is False,  f"{where}: the pane is still [hidden], so nothing opened it: {geom}"
    assert geom[ "pane_open" ] is True, f"{where}: .content-shell.pane-open was never set: {geom}"
    assert geom[ "in_viewport" ] is True, (
        f"{where}: the pane opened but is NOT IN THE VIEWPORT — the silent no-op a JS-only "
        f"fix produces. Got: {geom}"
    )
    assert geom[ "width" ] >= _MIN_USABLE_PX and geom[ "height" ] >= _MIN_USABLE_PX, (
        f"{where}: smaller than {_MIN_USABLE_PX}px in some dimension — the collapsed "
        f"'postage stamp' the stylesheet warns about. Got: {geom}"
    )
    assert geom[ "iframe_src" ] is not None and "/app/docs" in geom[ "iframe_src" ], (
        f"{where}: the pane is visible but holds no doc iframe, so it is an empty overlay "
        f"rather than the document that was asked for. Got iframe_src={geom[ 'iframe_src' ]!r}"
    )
    assert geom[ "iframe_h" ] >= _MIN_USABLE_PX, (
        f"{where}: the iframe collapsed to {geom[ 'iframe_h' ]}px — the symptom of a pane "
        f"with no definite height"
    )


# ── planting a history doc link, per client ───────────────────────────────────

def _plant_legacy_doc_notification( page ):
    page.evaluate(
        """( md ) => {
            window.notificationsUI.handleNotificationUpdate( {
                notification: {
                    id                 : 'doclink-newtab-legacy',
                    id_hash            : 'doclink-newtab-legacy',
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


def _plant_mux_doc_notification( page ):
    page.evaluate(
        """( md ) => {
            window.__multiplexerTestHook.bus.emit( {
                type    : 'notification_queue_update',
                payload : { notification: {
                    id_hash   : 'doclink-newtab-mux',
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


# The link text of `_DOC_LINK_MD`. Selecting on it is what makes the click land on the
# anchor THIS test planted.
_PLANTED_LINK_TEXT = "View the guide"


def _click_a_planted_doc_link( page ):
    """
    Click the anchor THIS test planted — never whatever anchor happens to be first.

    🔴 `.first` OVER EVERY `/app/docs?path=` ANCHOR IS NOT SAFE HERE, and that is why this
    helper exists rather than reusing the geometry file's. Chloé measured 5 ambient doc
    anchors per client on the real page, and some ambient surfaces are the RATIFIED
    EXCEPTION: a doc link inside `#action-required-content` or `.abstract-tooltip` opens a
    new tab on purpose. Clicking one of those would make `_assert_no_new_page` fail on
    correct behaviour — a false red that would read as a regression in the thing this file
    is guarding.

    ⇒ The selector is the planted link's TEXT, and the count is asserted to be exactly one.
    Exactly-one is the self-checking part: zero means the notification did not render and
    every assertion after this would be vacuous, and two or more means the text is no longer
    distinctive, in which case this refuses rather than guessing which to click.

    Requires:
        - a notification carrying _DOC_LINK_MD has been planted and rendered

    Ensures:
        - exactly one matching anchor was found and clicked
    """
    anchors = page.get_by_role( "link", name=_PLANTED_LINK_TEXT )
    count   = anchors.count()
    assert count == 1, (
        f"expected exactly 1 anchor reading {_PLANTED_LINK_TEXT!r}, found {count}. Zero means "
        f"the planted notification never rendered, so every assertion after this would be "
        f"vacuous. Two or more means the text is no longer distinctive — do not fall back to "
        f".first, because an ambient anchor may be a #action-required-content / "
        f".abstract-tooltip link that opens a new tab BY RULING, which would fail this file "
        f"on correct behaviour."
    )
    anchors.click()
    page.wait_for_timeout( 500 )


def _open_mux( page ):
    """
    Open /app/multiplexer and wait for the signal THIS page actually has.

    ⚠️ NOT `wait_for_ws_connected` — its predicate reads `#queue-ws-status`, which occurs
    zero times in multiplexer.html and once in notifications.html. Waiting on it here is
    unsatisfiable and burns the full timeout in setup, which is how
    `test_multiplexer_vertical_doc_link_pane_is_in_the_viewport` spent every run never
    reaching an assertion (ts-e09fb548, 2026-09-27). The store hook is the readiness signal
    this page has.
    """
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# The probe's own positive control — run this before trusting any absence below
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_probe_itself_detects_a_new_page( notifications_page ):
    """
    Watch both arms of `_assert_no_new_page` FIRE, on a page where a tab really opens.

    Without this, eight "no new page" passes are indistinguishable from eight passes by a
    probe that cannot see a page at all. The anchor points at `about:blank` — a href no
    interceptor claims — so nothing in the app is involved in the outcome.

    Both arms are checked separately, because each catches what the other misses: the
    `window.open` arm is driven by a scripted call, the `context.pages` arm by the bare
    `target="_blank"` attribute.
    """
    page = notifications_page
    _install_open_probe( page )

    # Arm 1 — a scripted window.open is recorded.
    page.evaluate( "( href ) => window.open( href, '_blank' )", _UNCLAIMED_BLANK_HREF )
    page.wait_for_timeout( 300 )
    assert _open_calls( page ) == [ _UNCLAIMED_BLANK_HREF ], (
        f"the window.open arm did not record a scripted call — it cannot vouch for any "
        f"absence. Got {_open_calls( page )!r}"
    )

    # Arm 2 — a bare target="_blank" anchor, with NO window.open call, still grows the
    # context. This is the arm that matters: it is the shape the original defect rode.
    page.evaluate( "() => { window.__openCalls = []; }" )
    pages_before = len( page.context.pages )
    page.evaluate(
        """( href ) => {
            const a = document.createElement( "a" );
            a.id = "e2e-probe-blank-anchor";
            a.href = href;
            a.target = "_blank";
            a.textContent = "probe";
            document.body.appendChild( a );
        }""",
        _UNCLAIMED_BLANK_HREF,
    )
    with page.context.expect_page( timeout=5000 ) as opened:
        page.locator( "#e2e-probe-blank-anchor" ).click()

    # Read the count WHILE the tab is still open — this is the arm being proven, so it is
    # asserted on its own terms rather than left to `expect_page` to have implied.
    pages_during = len( page.context.pages )
    opened.value.close()

    assert pages_during > pages_before, (
        f"context.pages did not grow when a target=_blank anchor opened a tab "
        f"({pages_before} -> {pages_during}), so the second arm of _assert_no_new_page "
        f"cannot vouch for any absence"
    )
    assert _open_calls( page ) == [], (
        "a bare target=_blank anchor produced a window.open call, so the two arms are not "
        "independent and the second one is not adding what this docstring claims"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Surface 1 — a history doc link
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "layout", LAYOUTS )
def test_a_legacy_history_doc_link_renders_in_app_and_opens_no_tab( notifications_page, layout ):
    """
    The legacy client, both layouts. Vertical is the layout the row's defect lived in —
    the interceptor used to open with `if ( this._layoutMode !== "horizontal" ) return;`,
    so the click went unclaimed and the anchor's baked-in `target="_blank"` won.
    """
    page = notifications_page
    _set_layout( page, layout )
    _install_open_probe( page )
    _plant_legacy_doc_notification( page )

    pages_before = len( page.context.pages )
    _click_a_planted_doc_link( page )

    _assert_no_new_page( page, pages_before, f"legacy history doc link / {layout}" )
    _assert_pane_holds_a_doc( _pane_geometry( page ), "legacy history doc link", layout )


@pytest.mark.parametrize( "layout", LAYOUTS )
def test_a_mux_history_doc_link_renders_in_app_and_opens_no_tab( logged_in_page, layout ):
    """The multiplexer, both layouts. Same contract, a different codebase — §4's parity rule."""
    page = logged_in_page
    _open_mux( page )
    _set_layout( page, layout )
    _install_open_probe( page )
    _plant_mux_doc_notification( page )

    pages_before = len( page.context.pages )
    _click_a_planted_doc_link( page )

    _assert_no_new_page( page, pages_before, f"mux history doc link / {layout}" )
    _assert_pane_holds_a_doc( _pane_geometry( page ), "mux history doc link", layout )


# ═══════════════════════════════════════════════════════════════════════════════
# Surface 2 — the 📂 roots button (c6f52bca8), untested at any tier until now
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "layout", LAYOUTS )
def test_the_legacy_roots_button_renders_in_app_and_opens_no_tab( notifications_page, layout ):
    """
    `#doc-roots-toggle` in the legacy client, both layouts.

    It routes through `_openContentPane( "doc", "/app/docs", "Files" )` — the SAME door a
    doc-link click uses, which is the design's argument that button and link cannot drift.
    This is the first test at any tier that watches the button end of it.
    """
    page = notifications_page
    _set_layout( page, layout )
    _install_open_probe( page )

    pages_before = len( page.context.pages )
    page.locator( _ROOTS_BUTTON ).click()
    page.wait_for_timeout( 500 )

    _assert_no_new_page( page, pages_before, f"legacy roots button / {layout}" )
    _assert_pane_holds_a_doc( _pane_geometry( page ), "legacy roots button", layout )


@pytest.mark.parametrize( "layout", LAYOUTS )
def test_the_mux_roots_button_renders_in_app_and_opens_no_tab( logged_in_page, layout ):
    """`#doc-roots-toggle` in the multiplexer: `store.open( "doc", DOC_ROOTS_HREF, "Files" )`."""
    page = logged_in_page
    _open_mux( page )
    _set_layout( page, layout )
    _install_open_probe( page )

    pages_before = len( page.context.pages )
    page.locator( _ROOTS_BUTTON ).click()
    page.wait_for_timeout( 500 )

    _assert_no_new_page( page, pages_before, f"mux roots button / {layout}" )
    _assert_pane_holds_a_doc( _pane_geometry( page ), "mux roots button", layout )


# ═══════════════════════════════════════════════════════════════════════════════
# The two properties the button's own comments claim, asserted
# ═══════════════════════════════════════════════════════════════════════════════

def test_the_legacy_roots_button_survives_a_toolbar_rerender( notifications_page ):
    """
    The reason the legacy handler is DELEGATED on `document` rather than bound to the
    element, stated in its own comment:

        ⚠️ DELEGATED ON document, NOT bound to the element. A direct listener is the idiom
        the layout-mode button above uses, and it is the wrong one here: this button lives
        in the section toolbar, which is re-rendered, and a listener on a replaced element
        is silently gone.

    A comment is not a control. This replaces the toolbar's subtree — what a re-render does
    — and then clicks the button, so a regression to a direct listener fails here instead
    of shipping as a button that stops working after the first re-render.
    """
    page = notifications_page
    _install_open_probe( page )

    replaced = page.evaluate(
        """() => {
            const btn = document.getElementById( "doc-roots-toggle" );
            if ( !btn ) return false;
            const parent = btn.parentElement;
            // Rebuild the button from its own outerHTML: same markup, a DIFFERENT element,
            // which is precisely what a re-render leaves behind.
            parent.innerHTML = parent.innerHTML;
            return document.getElementById( "doc-roots-toggle" ) !== btn;
        }"""
    )
    assert replaced is True, (
        "the toolbar subtree was not actually replaced, so this test did not reproduce a "
        "re-render and proves nothing about delegation"
    )

    pages_before = len( page.context.pages )
    page.locator( _ROOTS_BUTTON ).click()
    page.wait_for_timeout( 500 )

    _assert_no_new_page( page, pages_before, "legacy roots button after re-render" )
    _assert_pane_holds_a_doc( _pane_geometry( page ), "legacy roots button after re-render", "as-loaded" )


def test_the_legacy_roots_button_is_not_claimed_by_the_section_toggle_handler( notifications_page ):
    """
    The property the button's markup comment claims — and the comment is WRONG about the
    mechanism, which is why this asserts the observable instead of the attribute.

    The comment at notifications.html says:

        NO data-section: this is not a section toggle, so the delegated section handler must
        not claim it — same shape as the layout-mode button above.

    🔴 BOTH HALVES OF THAT ARE INACCURATE, AND THE SECOND ONE IS THE DEFECT.
    · The handler is not delegated. `initSectionToolbar` does
      `toolbar.querySelectorAll( ".toolbar-btn" ).forEach( btn => btn.addEventListener(
      "click", () => this.toggleSectionVisibility( btn.dataset.section ) ) )`
      (notifications.js:15528-15530) — one direct listener per button, selected BY CLASS,
      with no `data-section` filter anywhere.
    · So "same shape as the layout-mode button above" is not true. That button escapes the
      dispatcher by using a DIFFERENT CLASS, and its own comment says so in as many words:
      "(`layout-mode-btn`, NOT `toolbar-btn`) and NO `data-section` attr, so the
      section-visibility click dispatcher doesn't pick it up" (notifications.html:36-37).
      The roots button is `class="toolbar-btn"` — the very class the dispatcher iterates.

    ⇒ The roots button IS claimed. Every click also runs
    `toggleSectionVisibility( undefined )` → `getElementById( undefined )` → null →
    `this.error( "Section not found: undefined" )`, which is a real `console.error`
    (notifications.js:21323) plus a debug-panel entry. Harmless only by accident: nothing
    protects the button, the lookup just happens to miss.

    ⚠️ THE MULTIPLEXER GOT THIS RIGHT AND LEGACY DID NOT — multiplexer.html builds its roots
    button as `class="layout-mode-btn"`. So this is a one-word parity divergence, and the
    fix is to make legacy match: `toolbar-btn` → `layout-mode-btn`.

    This test asserts the OBSERVABLE consequence rather than the attribute, because the
    attribute is not what the dispatcher keys on — an attribute assertion would pass while
    the button stayed claimed.
    """
    page = notifications_page

    errors = []
    page.on( "console", lambda m: errors.append( m.text ) if m.type == "error" else None )

    before = page.evaluate(
        """() => [ ...document.querySelectorAll( '[data-collapsed="true"]' ) ]
                 .map( ( e ) => e.id || e.getAttribute( "data-testid" ) || e.className ).sort()"""
    )
    hidden_before = page.evaluate(
        """() => [ ...document.querySelectorAll( ".accordion-section, .section" ) ]
                 .filter( ( e ) => e.style.display === "none" ).length"""
    )

    page.locator( _ROOTS_BUTTON ).click()
    page.wait_for_timeout( 500 )

    after = page.evaluate(
        """() => [ ...document.querySelectorAll( '[data-collapsed="true"]' ) ]
                 .map( ( e ) => e.id || e.getAttribute( "data-testid" ) || e.className ).sort()"""
    )
    hidden_after = page.evaluate(
        """() => [ ...document.querySelectorAll( ".accordion-section, .section" ) ]
                 .filter( ( e ) => e.style.display === "none" ).length"""
    )

    # The pane still opened — the section handler firing must not cost the button its job.
    _assert_pane_holds_a_doc( _pane_geometry( page ), "legacy roots button", "as-loaded" )

    assert after == before, (
        f"clicking the roots button changed which sections are collapsed. before={before} "
        f"after={after}"
    )
    assert hidden_after == hidden_before, (
        f"clicking the roots button hid or showed a section ({hidden_before} -> "
        f"{hidden_after} display:none). The section-visibility dispatcher claimed it."
    )

    claimed = [ e for e in errors if "Section not found" in e ]
    assert not claimed, (
        f"the section-visibility dispatcher claimed the roots button: {claimed}. It selects "
        f"on `.toolbar-btn` (notifications.js:15528), not on `data-section`, so the missing "
        f"attribute protects nothing — `toggleSectionVisibility( undefined )` runs and logs. "
        f"FIX: give the button `class=\"layout-mode-btn\"` as multiplexer.html already does "
        f"and as the sibling layout-mode button does for exactly this reason "
        f"(notifications.html:36-37). Nothing else needs to change."
    )
