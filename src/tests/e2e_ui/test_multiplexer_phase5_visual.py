"""
Multiplexer Phase 5 — visual regression baseline capture.

Per AC11a + AC11b ratification (D-F 2026-05-05):
    - AC11a: submission via `POST /api/test-suite/submit` with `--update-snapshots
      -k multiplexer_phase5` returns HTTP 200 + valid `submission_id`
    - AC11b: post-run state — assert PNGs exist under `__snapshots__/` AND
      test-suite final_state === "passed"

Per locked 2026-05-05 directive:
    - Feature parity, NOT pixel parity (vs `/app/notifications`)
    - Baselines captured FRESH at first Phase 5 E2E run
    - No forensic snapshot capture from old `/app/notifications`

Per A11 + `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
the e2e_ui conftest standard (`LUPIN_TEST_BASE_URL` env var; default
`http://localhost:8000`). NO hardcoded `:8000` literal in this file.

**Venue**: `:8000` monopolize-mode (e2e_ui suite gate). Schedule via
`POST /api/test-suite/submit` with non-overlapping `scheduled_at` slot per
`feedback_test_server_monopolize_mode`. Side-door injection (ad-hoc curl,
direct queue push, in-process server instantiation) is PROHIBITED.

Submission body:
    {
        "test_types"   : "e2e_ui",
        "scheduled_at" : "<user-confirmed slot>",
        "args"         : "--update-snapshots -k multiplexer_phase5"
    }

The `-k multiplexer_phase5` filter ensures ONLY this file's tests run during
the scheduled slot — NOT the full ~285 functional + 12 visual E2E sweep.
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Test hook usage — see boot.ts `window.__multiplexerTestHook` (D-E)
# ---------------------------------------------------------------------------

# Inject 3 deterministic fixtures via eventBus.emit. Uses FIXED timestamps
# (NOT new Date()) so the rendered .message-time text is byte-identical across
# runs — first run with --update-snapshots captures the baseline; subsequent
# runs pixel-match against it without time-drift flakiness.
#
# Per pytest-playwright-visual-snapshot library: pixel-diff includes ALL
# rendered text. Time displays, countdowns, and any other live data MUST be
# fixed BEFORE the screenshot, or every run produces different pixels.
_INJECT_FIXTURES_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }

    // Fixed timestamps for byte-identical rendering across runs.
    const FIXED_TS_BASE = '2026-05-05T18:00:00.000Z';  // 14:00 EDT
    const FIXED_TS_2    = '2026-05-05T18:01:00.000Z';
    const FIXED_TS_3    = '2026-05-05T18:02:00.000Z';

    // Fixture 1 — plain notification.
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : {
            queue_name: 'notification', value: 1,
            notification: {
                id_hash    : 'phase5_visual_plain',
                message    : 'Plain notification body for visual baseline',
                sender_id  : 'phase5-visual-sender-a',
                timestamp  : FIXED_TS_BASE,
                time_display      : '14:00',
                response_requested: false,
            }
        },
        source : 'phase5-visual',
        ts     : 1778011200000,  // fixed
    } );

    // Fixture 2 — markdown notification.
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : {
            queue_name: 'notification', value: 2,
            notification: {
                id_hash    : 'phase5_visual_md',
                message    : '**bold** _italic_ markdown sample',
                sender_id  : 'phase5-visual-sender-b',
                timestamp  : FIXED_TS_2,
                time_display      : '14:01',
                response_requested: false,
            }
        },
        source : 'phase5-visual',
        ts     : 1778011260000,
    } );

    // Fixture 3 — action-required widget (read-only inert state).
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : {
            queue_name: 'notification', value: 3,
            notification: {
                id_hash    : 'phase5_visual_ar',
                message    : 'Approve the deploy?',
                sender_id  : 'phase5-visual-sender-c',
                timestamp  : FIXED_TS_3,
                time_display      : '14:02',
                response_requested: true,
                response_type    : 'yes_no',
                response_options : [ 'yes', 'no' ],
                timeout_seconds  : 60,
            }
        },
        source : 'phase5-visual',
        ts     : 1778011320000,
    } );

    return true;
}
"""


# Force ALL dynamic / live-data DOM content to deterministic placeholders
# AFTER the renderer paints but BEFORE the screenshot. The renderer's tick
# handler keeps mutating `.action-required-countdown` at 1Hz; without this
# stabilization, the screenshot timing window itself becomes a source of
# byte drift even with fixed timestamps.
#
# This poke does NOT affect store state — only the displayed text.
_STABILIZE_DOM_JS = """
() => {
    // Action-required countdown — pinned to a known value.
    document.querySelectorAll( '.action-required-countdown' ).forEach( el => {
        el.textContent = '⏱ 01:00';
    } );
    // Last-active timestamps in sender-card chrome — pinned to fixed time.
    document.querySelectorAll( '.sender-last-activity' ).forEach( el => {
        el.textContent = 'Last: 14:02';
    } );
    return true;
}
"""


# ---------------------------------------------------------------------------
# Visual regression — Phase 5 notifications-list pane (read-only)
# ---------------------------------------------------------------------------

def test_multiplexer_phase5_notifications_pane_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """
    Capture the Phase 5 notifications-list pane in its rendered baseline state
    (3 fixtures: plain + markdown + action-required read-only).

    Requires:
        - Server running on `:8000` with Testing config
        - `logged_in_page` fixture (authenticated session)
        - `assert_snapshot` fixture (pytest-playwright-visual-snapshot)
        - `--update-snapshots` flag on first run to establish the baseline
        - Multiplexer build artifact present on disk (boot.<hash>.js)

    Ensures:
        - `/app/multiplexer` loads under authenticated session
        - boot.ts test hook (`window.__multiplexerTestHook`) is reachable
        - 3 fixture envelopes inject + render synchronously
        - Snapshot of `#notifications-pane` matches baseline (or establishes
          baseline on first run with `--update-snapshots`)

    Per locked 2026-05-05 directive: feature parity, not pixel parity. The
    baseline established here is the canonical Phase 5 visual state; it is
    NOT measured against the legacy `/app/notifications` page.
    """
    page = logged_in_page

    # Navigate; wait for boot_complete to land.
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )

    # Wait for the test hook surface (post boot_complete).
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    # Inject the 3 fixtures.
    page.evaluate( _INJECT_FIXTURES_JS )

    # Wait for all 3 to render.
    page.wait_for_selector(
        '[data-id-hash="phase5-visual-sender-a"]',
        timeout=2000,
    )
    page.wait_for_selector(
        '[data-id-hash="phase5-visual-sender-b"]',
        timeout=2000,
    )
    page.wait_for_selector(
        '[data-testid="multiplexer-action-required"]',
        timeout=2000,
    )

    # Stabilize ALL live-data DOM content (countdown ticks, sender-card
    # last-activity timestamps) before snapshot — see _STABILIZE_DOM_JS.
    # Without this, the visual diff fails on every run because text
    # rendering varies with the moment the screenshot fires.
    page.evaluate( _STABILIZE_DOM_JS )

    # Font-load barrier (Gate D font-load race, task 006cb393): sender/type/status
    # icons render as NotoColorEmoji glyphs that load lazily; a screenshot taken
    # before the color-emoji font is ready captures a FALLBACK glyph → intermittent
    # visual FAIL. `networkidle` does NOT gate font loading. Await
    # document.fonts.ready + two animation frames so the final glyph is committed
    # before capture. Mirrors test_multiplexer_task_editing.py:316-318. Pure load
    # barrier — comparators/tolerances untouched.
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )

    # Brief settle window for any post-inject layout repaint.
    time.sleep( 0.2 )

    # Capture the entire #notifications-pane element (avoids body-level
    # layout drift from unrelated chrome).
    pane = page.locator( '[data-testid="multiplexer-notifications-pane"]' )
    assert_snapshot( pane, name="multiplexer_phase5_notifications_pane.png" )

    print( "✓ multiplexer_phase5_notifications_pane: visual snapshot compared" )

    # Broadened coverage (task c7745a76): mux commit 75a1bad3 (Lane 0a+0c) extracted
    # #action-required-section OUT of #notifications-pane into its own standalone
    # LEADING accordion — so the notifications-pane snapshot above now covers only
    # the plain + markdown fixtures. Capture the action-required section separately
    # so phase5 still covers ALL 3 injected fixtures (the action-required fixture in
    # its NEW accordion home here). The countdown is already pinned by
    # _STABILIZE_DOM_JS above; the AR widget was waited-for at
    # `[data-testid="multiplexer-action-required"]`, so the section is rendered.
    ar_section = page.locator( '[data-testid="multiplexer-action-required-section"]' )
    assert_snapshot( ar_section, name="multiplexer_phase5_action_required_section.png" )

    print( "✓ multiplexer_phase5_action_required_section: visual snapshot compared" )
