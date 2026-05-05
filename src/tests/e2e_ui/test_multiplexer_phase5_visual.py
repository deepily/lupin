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

# Inject 3 deterministic fixtures via eventBus.emit. Mirrors the smoke-test
# pattern but landed in the visual baseline so subsequent runs detect any
# unintended visual drift in renderer output.
_INJECT_FIXTURES_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }
    const now = new Date();

    // Fixture 1 — plain notification.
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : {
            queue_name: 'notification', value: 1,
            notification: {
                id_hash    : 'phase5_visual_plain',
                message    : 'Plain notification body for visual baseline',
                sender_id  : 'phase5-visual-sender-a',
                timestamp  : now.toISOString(),
                response_requested: false,
            }
        },
        source : 'phase5-visual',
        ts     : Date.now(),
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
                timestamp  : new Date( now.getTime() + 1000 ).toISOString(),
                response_requested: false,
            }
        },
        source : 'phase5-visual',
        ts     : Date.now(),
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
                timestamp  : new Date( now.getTime() + 2000 ).toISOString(),
                response_requested: true,
                response_type    : 'yes_no',
                response_options : [ 'yes', 'no' ],
                timeout_seconds  : 60,
            }
        },
        source : 'phase5-visual',
        ts     : Date.now(),
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

    # Stabilize the countdown text BEFORE snapshot — the action-required
    # widget's countdown ticks at 1Hz and would produce flaky baselines.
    # Force the displayed text to a deterministic placeholder via direct DOM
    # poke (does not affect store state).
    page.evaluate( """
        () => {
            const cd = document.querySelector( '.action-required-countdown' );
            if ( cd ) cd.textContent = '⏱ 00:60';
        }
    """ )

    # Brief settle window for any post-inject layout repaint.
    time.sleep( 0.2 )

    # Capture the entire #notifications-pane element (avoids body-level
    # layout drift from unrelated chrome).
    pane = page.locator( '[data-testid="multiplexer-notifications-pane"]' )
    assert_snapshot( pane, name="multiplexer_phase5_notifications_pane.png" )

    print( "✓ multiplexer_phase5_notifications_pane: visual snapshot compared" )
