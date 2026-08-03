#!/usr/bin/env python3
"""
WS3 — Full-Page Chrome Parity-Oracle: HORIZONTAL-mode golden-capture (Oracle-EXTEND).

The existing full-page capture (test_golden_capture.py) captures legacy at its
IDLE/vertical state. This adds the HORIZONTAL layout-mode frames the harness had
ZERO coverage of (F-Clay-D2 / F-Sam-D5), per Krishna's OSQ A-1 finding: legacy has
ONE binary ⇆ toggle (no ▭/⊞ grid button), driven by
`window.notificationsUI._toggleLayoutMode()` (notifications.js:12119) which flips
`body[data-layout-mode="horizontal"]`; pane-open (`.content-shell.pane-open`) is
reached via `_enterActionRequiredPaneMode()` when action-required is active.

THREE frames (Rick's Q1 two-mode ruling, pane sub-states):
  (a) VERTICAL  — the existing fullpage golden (baseline; not re-captured here).
  (b) HORIZONTAL pane-CLOSED — the binary reflow: toolbar column→ROW, container
      padding-top 20px→52px (un-gated, 32dbf5ed / notifications.css:5632), center
      content shifts. NO action-required needed → fixture-free, no scenario pollution.
  (c) HORIZONTAL pane-OPEN — `.content-shell.pane-open` sub-state where `.abstract`
      + the action-required widget show. Needs an AR item → a SEPARATE AR-only
      scenario (Tiberius's fixture caution; NOT the shared parity scenario). Authored
      as a follow-on once the AR seed is wired — this file lands frame (b) first.

      FRAME (c) DESIGN NOTES (Sam 2026-07-02, from legacy code archaeology — for the
      follow-on author):
        1. AR INJECTION (deterministic, no server mutation): legacy holds AR items in
           `window.notificationsUI.actionRequiredNotifications` (a Map, notifications.js
           :281). The AR-add path builds a `state` from a `notification` object
           (:16155-16180) then, if horizontal, auto-calls `_enterActionRequiredPaneMode()`
           (:16195). Inject a synthetic AR notification via page.evaluate against the
           client's AR-handler (find its exact signature ~:16140), OR seed the localStorage
           restore path (:15974-16090). Then toggle horizontal → pane auto-opens (size>0).
           CAUTION (Tiberius, harness-gotcha): build the synthetic from a REAL captured AR
           payload shape — ALL fields a live AR notification carries, id_hash/class fields
           especially. Under-shaped stubs get SILENTLY dropped by client normalize/validation
           → empty pane + a FALSE geometry frame. VERIFY the widget actually rendered (present
           in #content-pane-body) BEFORE writing the golden — a fail-loud assert, not a hope.
        2. SELECTOR MAP REQUIRED: `.action-required-widget` is a MUX-ONLY class — it does
           NOT exist in legacy (grep: 0 hits in notifications.js/.css). Legacy renders the
           pane body under `#content-pane-body` with `.abstract-content`/`.abstract-header`
           (:7324-7325). So frame (c) needs a legacy↔mux pane-content selector map (the
           CHROME_ROWS pattern in parity_oracle.py), NOT a shared selector — the golden
           captures legacy's `#content-pane-body`/`.abstract-content` geometry; the held
           mux-side assert keys on `.action-required-widget`/`.abstract`.
        3. Capture surfaces: `.content-shell.pane-open .container` (center-shift when the
           pane owns the split), `#content-pane` / `#content-pane-body`, the abstract block.

Drives the LEGACY client only (via the JS toggle method), so it is UNAFFECTED by
the mux nav-brand click-occlusion (P1 bug c31c2d61) that blocks the mux toggle —
we call the method directly, never click. The mux-side horizontal captures + the
mux-vs-golden Tier assertions are HELD for the Lane-0 (0a/0c) merge.

Separate golden (never overwrites the vertical fullpage golden):
    src/tests/e2e_ui/fixtures/golden/notifications-legacy-fullpage-horizontal.golden.json

Gated behind LUPIN_PARITY_FULLPAGE_HORIZONTAL_CAPTURE=1 (recalibration step).
Venue: :7999 (legacy reachable; read-only — loading + reading DOM, no persistent
mutation). Run:
    LUPIN_PARITY_FULLPAGE_HORIZONTAL_CAPTURE=1 LUPIN_TEST_BASE_URL=http://localhost:7999 \
        pytest src/tests/parity_oracle_fullpage/test_golden_capture_horizontal.py -v -s
"""

from __future__ import annotations

import json
import os

import pytest

from tests.e2e_ui.parity_oracle import (
    CHROME_STYLE_PROPS,
    LEGACY_FULLPAGE_PATH,
    PAGE_CHROME_WALK_JS,
    chrome_css_hashes,
    chrome_rows_for,
    repo_root,
)

from ._fullpage_helpers import CONTAINER_SEL, base_url, login_tokens

LEGACY_URL = f"{base_url()}{LEGACY_FULLPAGE_PATH}"

HORIZONTAL_GOLDEN_PATH = (
    repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden"
    / "notifications-legacy-fullpage-horizontal.golden.json"
)

_CAPTURE_ENABLED = os.environ.get( "LUPIN_PARITY_FULLPAGE_HORIZONTAL_CAPTURE" ) == "1"

pytestmark = pytest.mark.skipif(
    not _CAPTURE_ENABLED,
    reason="horizontal fullpage golden-capture is a gated recalibration step — set "
           "LUPIN_PARITY_FULLPAGE_HORIZONTAL_CAPTURE=1 to run",
)

# The horizontal-reflow signal probe — the surfaces the F-Sam-D5 assertions key on:
# the container's toolbar-clearing padding (20→52px), the toolbar's orientation
# (column→row), and the center content's shift. Geometry is rounded to 0.1px; the
# container's inset from the content-shell left edge is the center-shift signal.
HORIZONTAL_REFLOW_JS = r"""
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
    const toolbar   = document.querySelector( '.section-toolbar' );
    const shellRect = shell ? shell.getBoundingClientRect() : null;
    const contRect  = container ? container.getBoundingClientRect() : null;
    return {
        layout_mode         : document.body.getAttribute( 'data-layout-mode' ),
        pane_open           : !!shell && shell.classList.contains( 'pane-open' ),
        content_shell       : { geom: rect( shell ),     styles: styleOf( shell ) },
        container           : { geom: rect( container ), styles: styleOf( container ) },
        section_toolbar     : { geom: rect( toolbar ),   styles: styleOf( toolbar ) },
        // center-shift signal: container's inset from the content-shell's left edge.
        container_dx_in_shell : ( shellRect && contRect ) ? round1( contRect.left - shellRect.left ) : null,
    };
}
"""

# The reflow-specific declarative props (superset of CHROME_STYLE_PROPS' spirit,
# focused on the horizontal signals: padding clearance + flex orientation).
REFLOW_STYLE_PROPS = [
    "display", "position", "flex-direction", "flex-wrap", "align-items", "justify-content",
    "padding-top", "padding-right", "padding-bottom", "padding-left",
    "margin-left", "margin-right", "left", "right", "width",
]


def _seed_auth( page ):
    access, refresh = login_tokens( base_url() )
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )


def test_capture_legacy_fullpage_horizontal_golden( page ):
    """Load legacy, drive the binary ⇆ toggle to HORIZONTAL (pane-closed) via the
    real client method (NOT a click — sidesteps the mux occlusion class), and
    serialize the horizontal chrome walk + reflow probe to the horizontal golden."""
    _seed_auth( page )
    page.goto( LEGACY_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_selector( "#action-required-section", timeout=15_000 )

    # Confirm the client handle + vertical starting state before toggling.
    start_mode = page.evaluate( "() => document.body.getAttribute('data-layout-mode')" )
    has_client = page.evaluate(
        "() => !!(window.notificationsUI && typeof window.notificationsUI._toggleLayoutMode === 'function')"
    )
    assert has_client, "window.notificationsUI._toggleLayoutMode must exist to drive the toggle"

    # Drive the binary toggle to horizontal (from the default vertical) via the method.
    if start_mode != "horizontal":
        page.evaluate( "() => window.notificationsUI._toggleLayoutMode()" )
    page.wait_for_function(
        "() => document.body.getAttribute('data-layout-mode') === 'horizontal'", timeout=5_000
    )
    page.wait_for_timeout( 1_000 )  # let the reflow settle

    reflow = page.evaluate( HORIZONTAL_REFLOW_JS, REFLOW_STYLE_PROPS )
    rows   = page.evaluate(
        PAGE_CHROME_WALK_JS,
        { "rows": chrome_rows_for( "legacy" ), "props": CHROME_STYLE_PROPS, "containerSel": CONTAINER_SEL },
    )

    print( "\n=== HORIZONTAL REFLOW PROBE (frame b — pane-closed) ===" )
    print( json.dumps( reflow, indent=2 ) )

    golden = {
        "captured_from" : "legacy notifications.html full page, HORIZONTAL pane-closed (?classic=1)",
        "frame"         : "b-horizontal-pane-closed",
        "container_sel" : CONTAINER_SEL,
        "css_hashes"    : chrome_css_hashes(),
        "reflow"        : reflow,
        "rows"          : rows,
    }
    HORIZONTAL_GOLDEN_PATH.parent.mkdir( parents=True, exist_ok=True )
    HORIZONTAL_GOLDEN_PATH.write_text( json.dumps( golden, indent=2 ) + "\n" )
    print( f"\n✓ wrote horizontal fullpage golden → {HORIZONTAL_GOLDEN_PATH}" )

    # Fail-loud invariants: the toggle actually engaged horizontal + the reflow fired.
    assert reflow[ "layout_mode" ] == "horizontal", "body must be in horizontal layout-mode after toggle"
    assert reflow[ "pane_open" ] is False, "frame (b) is the PANE-CLOSED sub-state"
    assert reflow[ "container" ][ "geom" ] is not None, "the .container must be present to measure reflow"


# ---------------------------------------------------------------------------
# Frame (c) — HORIZONTAL pane-OPEN (action-required in the reader pane)
# ---------------------------------------------------------------------------

# A REAL-SHAPED action-required notification (Tiberius's caution: NOT a minimal
# stub — carry every field a live AR notification carries, id_hash especially, so
# client normalize/validation does not silently drop it → empty pane + false frame).
# Field shape reverse-engineered from processNotification (notifications.js:5844-5880:
# response_requested→addActionRequiredNotification) + addActionRequiredNotification
# (:16149). Injected via a SEPARATE AR-only path (the client method), never the
# shared parity scenario.
AR_NOTIFICATION = {
    "id"                 : "e2e-ar-frame-c-0001",
    "id_hash"            : "e2eARframeC00001",
    "type"               : "custom",
    "notification_type"  : "custom",
    "priority"           : "high",
    "message"            : "Frame-c synthetic action-required — approve the horizontal pane-open capture?",
    "abstract"           : "Frame-c abstract body. Renders in the reader pane's abstract block so the "
                           "pane-open sub-state has real content to measure (center-shift + abstract geometry).",
    "response_requested" : True,
    "response_type"      : "yes_no",
    "timeout_seconds"    : 300,
    "sender_id"          : "claude.code@lupin.deepily.ai#framec",
    "title"              : "action:frame_c_capture",
    "suppress_ding"      : True,
    "timestamp"          : "2026-07-02T11:00:00-04:00",
    "voice_persona"      : None,
}

# Pane-open probe: the surfaces frame (c) asserts. Legacy renders the AR into
# `#content-pane-body` (`.abstract-content` for the abstract) — `.action-required-widget`
# is MUX-ONLY, so the LEGACY golden keys on legacy selectors and the HELD mux-side
# assert maps to `.action-required-widget`/`.abstract` (legacy↔mux map).
HORIZONTAL_PANE_OPEN_JS = r"""
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
    const shell        = document.querySelector( '.content-shell' );
    const paneContainer = document.querySelector( '.content-shell.pane-open .container' )
                          || document.querySelector( '.left-column .container' );
    const paneBody     = document.querySelector( '#content-pane-body' );
    const pane         = document.querySelector( '#content-pane' );
    // Legacy AR-pane surfaces (verified): the abstract renders as
    // `.action-required-abstract` (notifications.js:17724), NOT `.abstract-content`
    // (that's the message-card path). The AR "widget" is paneBody's rendered child.
    const abstract     = document.querySelector( '#content-pane-body .action-required-abstract' );
    const arWidget     = paneBody ? paneBody.firstElementChild : null;
    return {
        layout_mode          : document.body.getAttribute( 'data-layout-mode' ),
        pane_open            : !!shell && shell.classList.contains( 'pane-open' ),
        pane_body_present    : !!paneBody,
        pane_body_has_content : !!paneBody && paneBody.textContent.trim().length > 0,
        abstract_present     : !!abstract,
        ar_widget_class      : arWidget ? arWidget.className : null,
        content_pane         : { geom: rect( pane ),          styles: styleOf( pane ) },
        content_pane_body    : { geom: rect( paneBody ),      styles: styleOf( paneBody ) },
        pane_open_container  : { geom: rect( paneContainer ), styles: styleOf( paneContainer ) },
        ar_widget            : { geom: rect( arWidget ),      styles: styleOf( arWidget ) },
        abstract_block       : { geom: rect( abstract ),      styles: styleOf( abstract ) },
    };
}
"""


def test_capture_legacy_fullpage_horizontal_pane_open_golden( page ):
    """Frame (c): horizontal pane-OPEN. Toggle horizontal, inject a REAL-shaped AR
    notification via the client's addActionRequiredNotification (auto-enters pane
    mode in horizontal), FAIL-LOUD verify the pane actually rendered content, then
    serialize the pane-open geometry. Drives the LEGACY client only — unaffected by
    the mux nav-brand occlusion (c31c2d61)."""
    _seed_auth( page )
    page.goto( LEGACY_URL, wait_until="networkidle", timeout=20_000 )
    page.wait_for_selector( "#action-required-section", timeout=15_000 )

    assert page.evaluate(
        "() => !!(window.notificationsUI "
        "&& typeof window.notificationsUI._toggleLayoutMode === 'function' "
        "&& typeof window.notificationsUI.addActionRequiredNotification === 'function')"
    ), "legacy client must expose _toggleLayoutMode + addActionRequiredNotification"

    # Enter horizontal FIRST so the AR-add auto-lifts into the pane (size>0 path).
    if page.evaluate( "() => document.body.getAttribute('data-layout-mode')" ) != "horizontal":
        page.evaluate( "() => window.notificationsUI._toggleLayoutMode()" )
    page.wait_for_function(
        "() => document.body.getAttribute('data-layout-mode') === 'horizontal'", timeout=5_000
    )

    # Inject the real-shaped AR notification (separate AR-only path).
    page.evaluate( "( n ) => window.notificationsUI.addActionRequiredNotification( n )", AR_NOTIFICATION )

    # FAIL-LOUD render-verify BEFORE capture (Tiberius's gotcha): the pane must open
    # AND actually hold rendered content — an empty pane = a silently-dropped synthetic.
    page.wait_for_function(
        "() => { const s = document.querySelector('.content-shell');"
        " const b = document.querySelector('#content-pane-body');"
        " return !!s && s.classList.contains('pane-open') && !!b && b.textContent.trim().length > 0; }",
        timeout=8_000,
    )
    page.wait_for_timeout( 1_000 )  # settle the reflow

    pane = page.evaluate( HORIZONTAL_PANE_OPEN_JS, REFLOW_STYLE_PROPS )
    rows = page.evaluate(
        PAGE_CHROME_WALK_JS,
        { "rows": chrome_rows_for( "legacy" ), "props": CHROME_STYLE_PROPS, "containerSel": CONTAINER_SEL },
    )

    print( "\n=== HORIZONTAL PANE-OPEN PROBE (frame c) ===" )
    print( json.dumps( pane, indent=2 ) )

    golden = {
        "captured_from" : "legacy notifications.html full page, HORIZONTAL pane-OPEN + action-required (?classic=1)",
        "frame"         : "c-horizontal-pane-open",
        "container_sel" : CONTAINER_SEL,
        "css_hashes"    : chrome_css_hashes(),
        "ar_notification_shape" : sorted( AR_NOTIFICATION.keys() ),
        "pane"          : pane,
        "rows"          : rows,
    }
    path = (
        repo_root() / "src" / "tests" / "e2e_ui" / "fixtures" / "golden"
        / "notifications-legacy-fullpage-horizontal-pane-open.golden.json"
    )
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( json.dumps( golden, indent=2 ) + "\n" )
    print( f"\n✓ wrote horizontal pane-open golden → {path}" )

    # Fail-loud invariants.
    assert pane[ "layout_mode" ] == "horizontal", "must be horizontal for the pane-open frame"
    assert pane[ "pane_open" ] is True, "the content-shell must be pane-open (AR lifted into the reader pane)"
    assert pane[ "pane_body_has_content" ] is True, "the pane body must hold rendered AR content (not a dropped synthetic)"
    assert pane[ "ar_widget" ][ "geom" ] is not None, "the AR widget must render as a child of #content-pane-body"
    assert pane[ "abstract_present" ] is True, "the AR abstract (.action-required-abstract) must render (payload carries an abstract)"
