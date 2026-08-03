"""
WS3 — Full-Page Chrome Parity-Oracle: HORIZONTAL-mode Tier assertions (MUX side).

The capture sibling (test_golden_capture_horizontal.py) froze the LEGACY horizontal
frames into two goldens:
  - frame (b) notifications-legacy-fullpage-horizontal.golden.json           (pane-closed)
  - frame (c) notifications-legacy-fullpage-horizontal-pane-open.golden.json  (pane-open + AR)

This file is the HELD mux-side half (F-Sam-D5 / Oracle-EXTEND) for FRAME (b) — the
pane-CLOSED horizontal reflow. It drives the MUX into horizontal and asserts the mux
render matches the legacy golden on the LEGITIMATE cross-client claims — the
horizontal REFLOW signals — while deliberately NOT comparing absolute page-offset
(the section ORDER legitimately differs; same rule as test_tier2_tier3.py).

FRAME (c) — the pane-OPEN + action-required parity — lives in the :8000 e2e_ui suite
(test_multiplexer_horizontal_pane_open_parity.py), NOT here, for two reasons found
empirically (Sam, 2026-07-02): (1) the mux AR-into-pane lift is only STABLE under
clean-DB isolation — on the live :7999 dev server a real WebSocket
`notification_queue_update` reconciles the AR-pane closed ~1s after inject (the item
persists in the store, but `isActionRequiredInPane()` flips false); (2) the mux AR
widget renders `.action-required-prompt`, NOT a `.abstract` element, so the legacy
`.action-required-abstract` ↔ mux `.abstract` map does not hold for the AR-widget
context. Frame (c) therefore reuses the clean_test_db + logged_in_page fixtures on
:8000, mirroring its functional sibling test_multiplexer_action_required_in_pane.py.

Selector map (legacy ↔ mux — the horizontal surfaces diverge):
    reflow container      .container            ↔ .container            (shared)
    content shell         .content-shell        ↔ .content-shell        (shared)
    floating toolbar      .section-toolbar      ↔ .reading-pane-toolbar (mux renames)

The mux toggle is driven by a REAL click on #layout-mode-toggle (un-occluded since
the c31c2d61 nav-brand stacking fix; the 0b e2e suite is green on this same click).

Venue: :7999 — DB-free, read-only (loads a page + reads DOM), < 2 min → :7999-
eligible per CLAUDE.md §TESTING VENUES. Run:
    LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle_fullpage/test_tier_horizontal.py -v
"""

from __future__ import annotations

import json

import pytest

from tests.e2e_ui.parity_oracle import (
    MUX_FULLPAGE_PATH,
    repo_root,
)

from ._fullpage_helpers import base_url, login_tokens

MUX_URL     = f"{base_url()}{MUX_FULLPAGE_PATH}"

# Horizontal reflow tolerates a touch more flex than an isolated card; the
# pane-closed container padding is an EXACT px string compare (no tolerance
# needed — it is a discrete 20↔52 reflow), geometry compares within ±tol.
GEOM_TOL_PX = 1.5

HORIZONTAL_GOLDEN = (
    repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden"
    / "notifications-legacy-fullpage-horizontal.golden.json"
)
PANE_OPEN_GOLDEN = (
    repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden"
    / "notifications-legacy-fullpage-horizontal-pane-open.golden.json"
)

# Mux horizontal reflow probe — mirrors the legacy capture's HORIZONTAL_REFLOW_JS
# but keyed on the mux toolbar selector (.reading-pane-toolbar). Reads the reflow
# signals: container toolbar-clearing padding, toolbar orientation/position, and the
# container's inset from the content-shell left edge (the center-shift signal).
MUX_REFLOW_JS = r"""
( props ) => {
    const round1 = ( n ) => Math.round( n * 10 ) / 10;
    const rect = ( el ) => {
        if ( !el ) return null;
        const r = el.getBoundingClientRect();
        return { x: round1( r.left ), y: round1( r.top ), w: round1( r.width ), h: round1( r.height ) };
    };
    const styleOf = ( el ) => {
        if ( !el ) return null;
        const cs = getComputedStyle( el );
        const o = {};
        for ( const p of props ) o[ p ] = cs.getPropertyValue( p );
        return o;
    };
    const shell     = document.querySelector( '.content-shell' );
    const container = document.querySelector( '.container' );
    const toolbar   = document.querySelector( '.reading-pane-toolbar' );
    const shellRect = shell ? shell.getBoundingClientRect() : null;
    const contRect  = container ? container.getBoundingClientRect() : null;
    return {
        layout_mode           : document.body.getAttribute( 'data-layout-mode' ),
        pane_open             : !!shell && shell.classList.contains( 'pane-open' ),
        content_shell         : { geom: rect( shell ),     styles: styleOf( shell ) },
        container             : { geom: rect( container ), styles: styleOf( container ) },
        reading_pane_toolbar  : { geom: rect( toolbar ),   styles: styleOf( toolbar ) },
        container_dx_in_shell : ( shellRect && contRect ) ? round1( contRect.left - shellRect.left ) : null,
    };
}
"""

REFLOW_STYLE_PROPS = [
    "display", "position", "flex-direction", "flex-wrap", "align-items", "justify-content",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin-left", "margin-right", "left", "right", "width",
]


def _golden( path ) -> dict:
    if not path.exists():
        pytest.skip(
            f"horizontal golden absent: {path} — capture it first via "
            "test_golden_capture_horizontal.py (a SKIP is a finding, not a pass)."
        )
    return json.loads( path.read_text() )


def _seed_and_open_mux( page ):
    """Auth-seed, open the mux full page, wait for the boot test hook."""
    access, refresh = login_tokens( base_url() )
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    page.goto( MUX_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_function( "() => window.__multiplexerTestHook !== undefined", timeout=10_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook.stores && window.__multiplexerTestHook.stores.readingPane",
        timeout=10_000,
    )
    page.wait_for_selector( "#sender-cards-container", timeout=15_000 )


def _toggle_to_horizontal( page ):
    """Drive the mux binary toggle to horizontal via a REAL click (un-occluded
    post c31c2d61). Fail-loud if the toggle did not engage."""
    assert page.evaluate( "() => document.body.getAttribute('data-layout-mode')" ) == "vertical", \
        "precondition: mux loads in vertical mode"
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_function(
        "() => document.body.getAttribute('data-layout-mode') === 'horizontal'", timeout=5_000
    )
    page.wait_for_timeout( 1_000 )  # let the reflow settle


# ---------------------------------------------------------------------------
# Frame (b) — HORIZONTAL pane-CLOSED reflow parity (mux vs legacy golden)
# ---------------------------------------------------------------------------

def test_mux_horizontal_pane_closed_reflow_parity( page ):
    """Frame (b): the mux horizontal pane-closed reflow matches the legacy golden
    on the legitimate cross-client claims — the container gains the 52px
    toolbar-clearing top padding (un-gated), the floating toolbar is a fixed ROW,
    and the center content shifts inward. Absolute page-dy is NOT compared."""
    golden   = _golden( HORIZONTAL_GOLDEN )
    leg      = golden[ "reflow" ]
    assert leg[ "layout_mode" ] == "horizontal" and leg[ "pane_open" ] is False, \
        "golden frame (b) must be horizontal + pane-closed"

    _seed_and_open_mux( page )
    _toggle_to_horizontal( page )
    mux = page.evaluate( MUX_REFLOW_JS, REFLOW_STYLE_PROPS )

    print( "\n=== MUX HORIZONTAL REFLOW (frame b) ===" )
    print( json.dumps( mux, indent=2 ) )

    # (1) mux entered horizontal, pane-closed.
    assert mux[ "layout_mode" ] == "horizontal", "mux must be horizontal after toggle"
    assert mux[ "pane_open" ] is False, "frame (b) is the pane-CLOSED sub-state"

    # (2) container toolbar-clearing padding parity — the discrete 20→52 reflow.
    leg_pt = leg[ "container" ][ "styles" ][ "padding-top" ]
    mux_pt = mux[ "container" ][ "styles" ][ "padding-top" ]
    assert leg_pt == "52px", f"golden sanity: legacy container padding-top should be 52px, got {leg_pt}"
    assert mux_pt == leg_pt, (
        f"container toolbar-clearing padding diverges: legacy {leg_pt} · mux {mux_pt} "
        "(the un-gated horizontal reflow must reach 52px on both)"
    )

    # (3) floating toolbar is a FIXED ROW on both (legacy .section-toolbar ↔ mux
    #     .reading-pane-toolbar — the selector map handles the rename).
    leg_tb = leg[ "section_toolbar" ][ "styles" ]
    mux_tb = mux[ "reading_pane_toolbar" ][ "styles" ]
    assert mux[ "reading_pane_toolbar" ][ "geom" ] is not None, \
        "mux must render the floating .reading-pane-toolbar in horizontal mode"
    for prop in ( "position", "flex-direction" ):
        assert mux_tb[ prop ] == leg_tb[ prop ], (
            f"toolbar {prop} diverges: legacy {leg_tb[prop]!r} · mux {mux_tb[prop]!r}"
        )

    # (4) center-shift present on both — the container insets from the shell left
    #     edge when horizontal centers the narrower content column.
    leg_dx = leg[ "container_dx_in_shell" ]
    mux_dx = mux[ "container_dx_in_shell" ]
    assert leg_dx and leg_dx > 0, f"golden sanity: legacy center-shift should be positive, got {leg_dx}"
    assert mux_dx is not None and mux_dx > 0, (
        f"mux horizontal must center-shift the container (dx>0); got {mux_dx}"
    )


# ---------------------------------------------------------------------------
# Frame (b) territory — the "abstract visible" signal for REGULAR reading-pane
# content (Tiberius steer 2b, 2026-07-02).
# ---------------------------------------------------------------------------

def test_mux_horizontal_regular_abstract_visible( page ):
    """The legacy horizontal pane surfaces an `.action-required-abstract`; the mux
    carries the "abstract visible" signal for REGULAR reading-pane content via the
    rendered markdown in `#content-pane-body` — the mux has NO bare `.abstract`
    element anywhere (grep: zero hits; the reading pane renders raw markdown via
    ReadingPaneRenderer.renderEntry:280 → this.body.replaceChildren(frag), and the
    only `.abstract*` classes are `.abstract-indicator` on notification cards +
    `.action-required-prompt` in the AR widget). This gesture-opened abstract is a
    ReadingPaneStore entry (NOT the AR-reconcile path), so it is :7999-stable — no
    live-WS `notification_queue_update` closes it (the instability that moved frame
    (c) to :8000 is specific to the action-required lift/reconcile).

    Asserts the mux, in horizontal mode, opens an abstract into the reader pane and
    the pane body holds VISIBLE, NON-EMPTY rendered content — the abstract-visible
    signal, carried by the mux's structural equivalent node."""
    _seed_and_open_mux( page )
    _toggle_to_horizontal( page )

    abstract_md = "# Frame-b abstract\n\nRegular reading-pane content — the mux abstract-visible equivalent."
    page.evaluate(
        "( md ) => window.__multiplexerTestHook.stores.readingPane.open( 'abstract', md, 'Oracle frame-b abstract' )",
        abstract_md,
    )
    page.wait_for_function(
        "() => { const shell = document.querySelector('.content-shell');"
        " const b = document.getElementById('content-pane-body');"
        " return !!shell && shell.classList.contains('pane-open')"
        " && !!b && b.textContent.trim().length > 0; }",
        timeout=8_000,
    )
    page.wait_for_timeout( 300 )

    state = page.evaluate(
        """() => {
            const shell = document.querySelector( '.content-shell' );
            const body  = document.getElementById( 'content-pane-body' );
            const bareAbstract = document.querySelector( '.content-shell .abstract' );
            return {
                pane_open       : !!shell && shell.classList.contains( 'pane-open' ),
                body_present    : !!body,
                body_text_len   : body ? body.textContent.trim().length : 0,
                body_has_heading: !!body && !!body.querySelector( 'h1, h2, h3, p' ),
                bare_abstract   : !!bareAbstract,
            };
        }"""
    )
    print( "\n=== MUX HORIZONTAL REGULAR ABSTRACT (frame-b territory) ===" )
    print( json.dumps( state, indent=2 ) )

    assert state[ "pane_open" ] is True, "opening an abstract must open the reading pane"
    assert state[ "body_present" ] is True, "#content-pane-body must be present when the pane is open"
    assert state[ "body_text_len" ] > 0, \
        "the reading-pane body must hold VISIBLE, NON-EMPTY rendered abstract content"
    assert state[ "body_has_heading" ] is True, \
        "the abstract markdown must render to real block content (heading/paragraph), not an empty node"
    # Ground-truth the divergence finding: the mux has NO bare .abstract element —
    # the signal is carried by the rendered #content-pane-body content, not a
    # `.abstract` wrapper (documents why the legacy↔mux `.abstract` map is retired).
    assert state[ "bare_abstract" ] is False, \
        "sanity: the mux renders NO bare .abstract element (raw markdown in #content-pane-body instead)"
