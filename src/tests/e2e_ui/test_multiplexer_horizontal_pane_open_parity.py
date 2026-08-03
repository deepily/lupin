"""
E2E UI — multiplexer HORIZONTAL pane-OPEN parity vs the legacy full-page golden
(WS3 Oracle-EXTEND, frame (c) — Sam, 2026-07-02).

The mux-side counterpart to the legacy frame-(c) golden captured by
src/tests/parity_oracle_fullpage/test_golden_capture_horizontal.py
(notifications-legacy-fullpage-horizontal-pane-open.golden.json). Frame (b) — the
pane-CLOSED reflow parity — lives in the :7999 parity_oracle_fullpage suite
(test_tier_horizontal.py). Frame (c) lives HERE, on :8000, because the mux
AR-into-pane lift is only STABLE under clean-DB isolation: on the live :7999 dev
server a real WebSocket `notification_queue_update` reconciles the AR-pane CLOSED
~1s after the synthetic inject (the AR item persists in the store, but
`isActionRequiredInPane()` flips false). The `logged_in_page` fixture's
`clean_test_db` gives the isolation the sibling functional test
(test_multiplexer_action_required_in_pane.py) already relies on.

What frame (c) asserts (the F-Sam-D5 pane-open signals that are LEGITIMATE
cross-client, checked against the legacy golden's structural facts):
  1. pane-open center-shift — `.content-shell.pane-open .container` insets from the
     shell left edge (dx > 0), matching the legacy golden's pane-open sub-state.
  2. AR widget rendered IN the pane — the lifted `#action-required-section`
     (marked `.in-reading-pane`) moves into `#content-pane-body` and holds a
     `.action-required-widget` (legacy golden: ar_widget `.section-content
     .in-reading-pane`; the mux renames to `.action-required-widget`).
  3. the AR prompt is visible + non-empty — carries the legacy golden's
     "abstract visible" signal via the mux's STRUCTURAL EQUIVALENT node (see below).

ABSTRACT signal — mux-N/A for the AR-widget context, carried by the equivalent node
(Tiberius steer, 2026-07-02): the legacy AR pane renders an `.action-required-abstract`;
the MUX AR widget does NOT render a `.abstract` element — it renders
`.action-required-prompt` (render/templates/actionRequiredInteractive.ts:87 for
yes_no, :116/:147/:172/:211 for the other response types; grep: zero `.abstract` in
that template). So this test carries the "content visible in the AR pane" parity via
`.action-required-prompt` (signal 3 above), NOT `.abstract`. The `.abstract`-visible
assert for the case where the mux DOES render `.abstract` (regular reading-pane
content) lives in the :7999 sibling test_tier_horizontal.py
(test_mux_horizontal_regular_abstract_visible).

NOT asserted: absolute pane WIDTH — legacy uses a variable split ratio while the mux
forces 50/50 while AR owns the pane (same no-absolute rule as the vertical Tier
oracle, test_tier2_tier3.py).

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_multiplexer_horizontal_pane_open_parity",
        "scheduled_at"       : "<slot>",
        "auto_fix_on_failure": false
    }
"""

from __future__ import annotations

import json
from pathlib import Path

import cosa.utils.util as cu

from .conftest import BASE_URL

GOLDEN_PATH = (
    Path( cu.get_project_root() ) / "src" / "tests" / "e2e_ui" / "fixtures" / "golden"
    / "notifications-legacy-fullpage-horizontal-pane-open.golden.json"
)

# A REAL-shaped action-required notification (carry every field a live AR
# notification carries — id_hash + response_requested + response_type especially —
# so the ActionRequiredStore normalize does NOT silently drop it → empty pane + a
# FALSE frame). Shape mirrors the green wire-path reference
# (test_multiplexer_action_required_in_pane.py::_emit_action_required).
AR_NOTIFICATION = {
    "id_hash"            : "muxARframeC0001",
    "message"            : "Frame-c synthetic action-required — approve the horizontal pane-open capture?",
    "sender_id"          : "claude.code@lupin.deepily.ai#framec",
    "timestamp"          : "2026-07-02T15:00:00.000Z",
    "response_requested" : True,
    "response_type"      : "yes_no",
    "response_options"   : [ "yes", "no" ],
    "timeout_seconds"    : 300,
}

# Pane-open probe — the mux surfaces frame (c) asserts. The lifted
# `#action-required-section` (marked .in-reading-pane) is moved into
# `#content-pane-body`; the mux AR widget is `.action-required-widget`, whose visible
# content node is `.action-required-prompt` (the abstract structural equivalent).
PANE_OPEN_JS = r"""
() => {
    const round1 = ( n ) => Math.round( n * 10 ) / 10;
    const rect = ( el ) => {
        if ( !el ) return null;
        const r = el.getBoundingClientRect();
        return { x: round1( r.left ), y: round1( r.top ), w: round1( r.width ), h: round1( r.height ) };
    };
    const shell         = document.querySelector( '.content-shell' );
    const section       = document.getElementById( 'action-required-section' );
    const paneBody      = document.getElementById( 'content-pane-body' );
    const paneContainer = document.querySelector( '.content-shell.pane-open .container' );
    const arWidget      = document.querySelector( '#content-pane-body .action-required-widget' );
    const prompt        = document.querySelector( '#content-pane-body .action-required-prompt' );
    const shellRect     = shell ? shell.getBoundingClientRect() : null;
    const contRect      = paneContainer ? paneContainer.getBoundingClientRect() : null;
    return {
        layout_mode           : document.body.getAttribute( 'data-layout-mode' ),
        pane_open             : !!shell && shell.classList.contains( 'pane-open' ),
        section_in_pane       : !!( section && paneBody && section.parentNode === paneBody ),
        section_marked        : section ? section.classList.contains( 'in-reading-pane' ) : null,
        pane_body_has_content : !!paneBody && paneBody.textContent.trim().length > 0,
        ar_widget_present     : !!arWidget,
        prompt_present        : !!prompt,
        prompt_text           : prompt ? prompt.textContent.trim() : null,
        ar_widget             : rect( arWidget ),
        pane_open_container   : rect( paneContainer ),
        container_dx_in_shell : ( shellRect && contRect ) ? round1( contRect.left - shellRect.left ) : null,
    };
}
"""


def _open_multiplexer( page ):
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook"
        " && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.readingPane",
        timeout=15000,
    )


def _click_layout_toggle( page ):
    page.locator( "#layout-mode-toggle" ).click()
    page.wait_for_timeout( 100 )


def _emit_action_required( page, notif ):
    page.evaluate(
        """( notif ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type    : 'notification_queue_update',
                payload : { notification: notif },
                source  : 'oracle-horizontal-frame-c',
                ts      : 1780000000000,
            } );
        }""",
        notif,
    )
    page.wait_for_timeout( 300 )


def _golden() -> dict:
    assert GOLDEN_PATH.exists(), (
        f"legacy frame-(c) golden absent: {GOLDEN_PATH} — capture it first via "
        "parity_oracle_fullpage/test_golden_capture_horizontal.py "
        "(LUPIN_PARITY_FULLPAGE_HORIZONTAL_CAPTURE=1)."
    )
    return json.loads( GOLDEN_PATH.read_text() )


class TestMultiplexerHorizontalPaneOpenParity:
    """Frame (c): the mux horizontal pane-OPEN + action-required sub-state matches
    the legacy golden on the legitimate cross-client structural claims."""

    def test_mux_horizontal_pane_open_matches_legacy_golden( self, logged_in_page ):
        page   = logged_in_page
        golden = _golden()
        leg    = golden[ "pane" ]

        # Golden sanity — the legacy frame (c) is horizontal, pane-open, with a
        # rendered AR widget + abstract (its abstract is legacy-only; the mux
        # carries the signal via .action-required-prompt).
        assert leg[ "layout_mode" ] == "horizontal" and leg[ "pane_open" ] is True, \
            "legacy golden frame (c) must be horizontal + pane-open"
        assert leg[ "ar_widget" ][ "geom" ] is not None, \
            "legacy golden frame (c) must carry a rendered AR widget"
        assert leg[ "abstract_present" ] is True, \
            "legacy golden frame (c) must carry a visible abstract (mux equivalent: .action-required-prompt)"

        _open_multiplexer( page )
        _click_layout_toggle( page )                       # → horizontal
        _emit_action_required( page, AR_NOTIFICATION )

        # FAIL-LOUD render-verify BEFORE measuring: the section must actually lift
        # AND hold a rendered widget — an empty pane = a silently-dropped synthetic.
        page.wait_for_function(
            "() => { const s = document.getElementById('action-required-section');"
            " const b = document.getElementById('content-pane-body');"
            " const shell = document.querySelector('.content-shell');"
            " return !!shell && shell.classList.contains('pane-open')"
            " && !!s && !!b && s.parentNode === b"
            " && !!b.querySelector('.action-required-widget'); }",
            timeout=8000,
        )
        page.wait_for_timeout( 200 )

        mux = page.evaluate( PANE_OPEN_JS )
        print( "\n=== MUX HORIZONTAL PANE-OPEN (frame c) ===" )
        print( json.dumps( mux, indent=2 ) )

        # (1) horizontal + pane-open, AR section lifted + marked (matches the legacy
        #     golden's pane_open sub-state).
        assert mux[ "layout_mode" ] == "horizontal", "must be horizontal for the pane-open frame"
        assert mux[ "pane_open" ] is True, "the content-shell must be pane-open (AR lifted into the reader pane)"
        assert mux[ "section_in_pane" ] is True, "#action-required-section must move into #content-pane-body"
        assert mux[ "section_marked" ] is True, "the lifted section must carry the .in-reading-pane marker"
        assert mux[ "pane_body_has_content" ] is True, \
            "the pane body must hold rendered AR content (not a dropped synthetic)"

        # (2) AR widget renders IN the pane (F-Sam-D5 signal) — the mux
        #     `.action-required-widget` mirrors the legacy golden's ar_widget
        #     (legacy `.section-content.in-reading-pane`).
        assert mux[ "ar_widget_present" ] is True, \
            "the mux AR widget (.action-required-widget) must render inside the pane body"
        assert mux[ "ar_widget" ] is not None, "the AR widget must have a measurable box"

        # (3) AR prompt visible + non-empty — the mux STRUCTURAL EQUIVALENT of the
        #     legacy golden's abstract signal (mux AR widget renders
        #     .action-required-prompt, not .abstract — see module docstring).
        assert mux[ "prompt_present" ] is True, \
            "the mux AR prompt (.action-required-prompt) must render (abstract-signal equivalent)"
        assert mux[ "prompt_text" ], \
            f"the AR prompt must be visible + non-empty; got {mux['prompt_text']!r}"

        # (4) pane-open center-shift (F-Sam-D5 signal) — present + positive on both
        #     clients (the legacy golden carries the same pane-open sub-state).
        assert mux[ "pane_open_container" ] is not None, \
            "the pane-open container (.content-shell.pane-open .container) must be present"
        mux_dx = mux[ "container_dx_in_shell" ]
        assert mux_dx is not None and mux_dx > 0, (
            f"mux pane-open must center-shift the container (dx>0); got {mux_dx}"
        )
