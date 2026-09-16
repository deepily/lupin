"""
E2E UI — the multiplexer section-header chevron is a KEYBOARD control (row 1f79c04f).

97ab72a2 (2026-09-06, Rick's divergence #5) turned the chevron from a
`<span role="button">` into a `<button type="button">`, because the span could not
be focused: a keyboard user could collapse legacy's sections and not the mux's.
Nothing guarded that fix. A refactor back to a span, a stray `tabindex="-1"`, or a
keydown handler that swallows Enter would all have stayed green.

🔴 THE PROPERTY, NOT THE TAG. Nothing here asserts `tagName === "BUTTON"` — that
passes for a disabled button and fails a correctly built span with tabindex=0 and
key handlers. What a keyboard user needs is asserted instead:

  - REACHABLE   real Tab presses from the top of the page land on every chevron
  - ENTER       collapses its section, and a second Enter restores it
  - SPACE       the same, independently

Both arms per key, so a handler that fires once, or flips the wrong section, fails.

THE DENOMINATOR. `renderSectionHeader(` has 9 call sites under
`src/lupin_app/static/js/multiplexer/render/` (counted 2026-09-16 at 04b7dad1), and
the page renders 9 `.section-header` bars, each with a chevron. The list below is
COPIED, not derived from the page — a list read off the thing it checks agrees with
itself. A new section means adding it here.

Measured on :7999 before writing an assertion (2026-09-16 ~18:40 EDT): all 9 reached
by Tab once the toolbar-hidden panes are shown; Enter and Space each flipped exactly
one `data-collapsed` element and the glyph ▼→▶→▼, for all 9.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit) — the
`logged_in_page` fixture registers a user, which is a persistent write.
"""

from __future__ import annotations

from .conftest import BASE_URL

# Page order, as rendered at 04b7dad1.
EXPECTED_CHEVRON_HEADERS = [
    "multiplexer-action-required-header",
    "multiplexer-tts-header",
    "multiplexer-notifications-header",
    "multiplexer-fleet-status-header",
    "multiplexer-finished-tasks-header",
    "multiplexer-task-list-header",
    "multiplexer-holding-area-header",
    "multiplexer-epic-board-header",
    "multiplexer-jobs-header",
]

CHEVRON = ".section-header .toggle-button"

# A generous bound on Tab presses. The page needed well under this on :7999; the bound
# exists so a chevron that is NOT in the tab order ends the walk instead of hanging it.
MAX_TAB_PRESSES = 800

_CENSUS_JS = """() => [ ...document.querySelectorAll( '.section-header' ) ].map( ( h ) => ( {
    testid    : h.getAttribute( 'data-testid' ),
    hasToggle : h.querySelector( '.toggle-button' ) !== null,
} ) )"""

_WATCH_FOCUS_JS = """( selector ) => {
    window.__chevronFocused = new Set();
    document.addEventListener( 'focusin', ( e ) => {
        const t = e.target;
        if ( t instanceof Element && t.matches( selector ) ) {
            window.__chevronFocused.add( t.closest( '.section-header' ).getAttribute( 'data-testid' ) );
        }
    } );
    if ( document.activeElement instanceof HTMLElement ) document.activeElement.blur();
}"""

_COLLAPSED_JS = """() => [ ...document.querySelectorAll( '[data-collapsed="true"]' ) ]
    .map( ( e ) => e.id || e.getAttribute( 'data-testid' ) || e.className )"""

_FOCUSED_TESTID_JS = """( selector ) => {
    const a = document.activeElement;
    return a instanceof Element && a.matches( selector )
        ? a.closest( '.section-header' ).getAttribute( 'data-testid' ) : null;
}"""


def _open_multiplexer_with_every_pane_shown( page ):
    """
    Open the multiplexer and show every toolbar-hidden pane.

    Requires:
        - page is logged in

    Ensures:
        - every `.section-header` on the page is rendered and visible, so a chevron
          missing from the tab order cannot hide behind a hidden pane
    """
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.eventBus",
        timeout=15000,
    )
    page.wait_for_selector( "#section-toolbar", timeout=5000 )
    for button in page.locator( "#section-toolbar .toolbar-btn" ).all():
        pane = button.get_attribute( "data-section" )
        if page.locator( f"#{pane}" ).is_hidden(): button.click()
    for testid in EXPECTED_CHEVRON_HEADERS:
        page.locator( f'[data-testid="{testid}"] .toggle-button' ).wait_for( state="visible", timeout=5000 )


def _tab_walk( page, wanted, max_presses=MAX_TAB_PRESSES ):
    """
    Press Tab from the top of the page until every header in `wanted` has had its
    chevron focused, or `max_presses` is spent.

    Ensures:
        - returns ( reached testids, presses spent )
        - a chevron that is not in the tab order spends the whole budget, never hangs
    """
    page.evaluate( _WATCH_FOCUS_JS, CHEVRON )
    reached = set()
    presses = 0
    while presses < max_presses and not wanted <= reached:
        for _ in range( 25 ): page.keyboard.press( "Tab" )
        presses += 25
        reached = set( page.evaluate( "() => [ ...window.__chevronFocused ]" ) )
    return reached, presses


# The shape 97ab72a2 replaced: a span that announces a control and is not one.
_SWAP_TO_PRE_FIX_SPAN_JS = """( testid ) => {
    const b = document.querySelector( `[data-testid="${ testid }"] .toggle-button` );
    const s = document.createElement( 'span' );
    s.className = b.className;
    s.setAttribute( 'role', 'button' );
    s.textContent = b.textContent;
    b.replaceWith( s );
    return s.tabIndex;
}"""

# The header whose chevron the control arm neutralises. Any one will do; a fixed one
# keeps a red run reproducible.
NEUTRALISED_HEADER = "multiplexer-tts-header"


def _press_twice( page, testid, key ):
    """
    Focus one chevron, press `key` twice, and report what each press did.

    Ensures:
        - returns None when every arm held, else a one-line description of the first
          arm that did not: focus did not land, the first press did not collapse
          exactly one section, or the second press did not restore it
    """
    chevron = page.locator( f'[data-testid="{testid}"] .toggle-button' )
    chevron.focus()
    if page.evaluate( _FOCUSED_TESTID_JS, CHEVRON ) != testid:
        return f"{testid}: .focus() did not land on the chevron"
    before_glyph, before = chevron.text_content(), set( page.evaluate( _COLLAPSED_JS ) )

    page.keyboard.press( key )
    mid_glyph, mid = chevron.text_content(), set( page.evaluate( _COLLAPSED_JS ) )
    flipped = mid - before
    if len( flipped ) != 1 or before - mid or mid_glyph == before_glyph:
        return f"{testid}: {key} #1 did not collapse exactly one section (newly collapsed {sorted( flipped )}, glyph {before_glyph!r}->{mid_glyph!r})"

    page.keyboard.press( key )
    after_glyph, after = chevron.text_content(), set( page.evaluate( _COLLAPSED_JS ) )
    if after != before or after_glyph != before_glyph:
        return f"{testid}: {key} #2 did not restore (still collapsed {sorted( after - before )}, glyph {mid_glyph!r}->{after_glyph!r})"
    return None


class TestMultiplexerSectionChevronKeyboard:
    """Every mux section-header chevron is reachable by Tab and activated by Enter and Space."""

    def test_every_section_header_carries_a_chevron_and_the_guard_names_them_all( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer_with_every_pane_shown( page )
        census = page.evaluate( _CENSUS_JS )
        assert [ h[ "testid" ] for h in census ] == EXPECTED_CHEVRON_HEADERS, (
            "The rendered section headers no longer match the guarded list, so this guard's "
            "denominator is wrong. Rendered: %r" % [ h[ "testid" ] for h in census ]
        )
        assert all( h[ "hasToggle" ] for h in census ), census

    def test_real_tab_presses_reach_every_chevron( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer_with_every_pane_shown( page )
        wanted = set( EXPECTED_CHEVRON_HEADERS )
        assert wanted, "the guarded list is empty — this test would pass over nothing"
        reached, presses = _tab_walk( page, wanted )
        assert reached == wanted, (
            "A keyboard user cannot reach these section chevrons with Tab (%d presses): %s. "
            "role=\"button\" announces a control without putting it in the tab order — "
            "see 97ab72a2." % ( presses, sorted( wanted - reached ) )
        )

    def test_enter_collapses_and_restores_every_section( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer_with_every_pane_shown( page )
        failures = [ f for f in ( _press_twice( page, t, "Enter" ) for t in EXPECTED_CHEVRON_HEADERS ) if f ]
        assert EXPECTED_CHEVRON_HEADERS, "the guarded list is empty — this test would pass over nothing"
        assert not failures, "Enter on a section chevron:\n  " + "\n  ".join( failures )

    def test_space_collapses_and_restores_every_section( self, logged_in_page ):
        page = logged_in_page
        _open_multiplexer_with_every_pane_shown( page )
        failures = [ f for f in ( _press_twice( page, t, "Space" ) for t in EXPECTED_CHEVRON_HEADERS ) if f ]
        assert EXPECTED_CHEVRON_HEADERS, "the guarded list is empty — this test would pass over nothing"
        assert not failures, "Space on a section chevron:\n  " + "\n  ".join( failures )

    def test_the_guard_FAILS_on_the_pre_fix_span_it_exists_to_stop( self, logged_in_page ):
        """
        The discrimination arm, inside the run. Swap ONE chevron in the page for the
        pre-97ab72a2 `<span role="button">` with no tabindex — product code untouched —
        and drive it through the same helpers the guards above use. They must report
        what a keyboard user would hit: Tab never lands on it, and Enter does nothing.
        The other eight must still be reached, or the walk proved nothing.
        """
        page = logged_in_page
        _open_multiplexer_with_every_pane_shown( page )
        tab_index = page.evaluate( _SWAP_TO_PRE_FIX_SPAN_JS, NEUTRALISED_HEADER )
        assert tab_index == -1, "the planted span is focusable (tabIndex %r) — it is not the pre-fix shape" % tab_index

        others           = set( EXPECTED_CHEVRON_HEADERS ) - { NEUTRALISED_HEADER }
        reached, presses = _tab_walk( page, set( EXPECTED_CHEVRON_HEADERS ) )
        assert others <= reached, "the Tab walk missed healthy chevrons %s, so it cannot vouch for the span" % sorted( others - reached )
        assert NEUTRALISED_HEADER not in reached, "Tab reached a span role=button with no tabindex in %d presses" % presses

        # Park focus on nothing first: the walk left it on some healthy chevron, where an
        # Enter would collapse THAT section and read as the span activating.
        page.evaluate( "() => document.activeElement instanceof HTMLElement && document.activeElement.blur()" )
        before = set( page.evaluate( _COLLAPSED_JS ) )
        result = _press_twice( page, NEUTRALISED_HEADER, "Enter" )
        assert result is not None and "did not land" in result, (
            "the Enter guard did not report the span as unreachable: %r" % result
        )
        page.keyboard.press( "Enter" )
        assert set( page.evaluate( _COLLAPSED_JS ) ) == before, "Enter collapsed a section with focus off every chevron"
