#!/usr/bin/env python3
"""
Phase 6a acceptance smoke for the multiplexer jobs pane.

Verifies AC8a (functional smoke + parameterized data-phase6-pending count),
AC8b (perf gate), AC9 (boot_complete handler handshake — stable line per F22),
and AC10d layer-3 (CSS scope-leak canary).

Per CLAUDE.local.md "USER IS NEVER A TESTER" mandate: every assertion is
EXECUTOR: AI. Tests run on :7999 (AI-discretionary venue per design doc).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
`LUPIN_API_URL` env var (default http://localhost:7999).

Usage:
    pytest src/tests/smoke/test_multiplexer_phase6a_smoke.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_multiplexer_phase6a_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

from tests.smoke.multiplexer_auth import seed_multiplexer_auth, stub_empty_hydration

BASE_URL          = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
PHASE6A_PAGE_URL  = f"{BASE_URL}/app/multiplexer"


# ---------------------------------------------------------------------------
# Test-hook polling
# ---------------------------------------------------------------------------

def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    """Poll for the boot.ts test hook to be ready (post-boot_complete)."""
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


# ---------------------------------------------------------------------------
# Fixture-injection JS — three jobs:
#   running (status_running), done (status_done), done-then-removed (history)
#
# Per Pass 2 F19 + F18: all three jobs use VALID Job.status values
# {todo|running|done|dead}; the history landing happens via the actual
# `job_removed` reducer path (NOT a fabricated `status:'history'` payload).
# ---------------------------------------------------------------------------

_INJECT_3_JOBS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook missing — boot.ts test surface absent" );
    }
    const bus = hook.eventBus;

    // Job 1: running (lands in `running` bucket).
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'fix-run-001',
            id_hash    : 'fix-run-001',
            from_state : null,
            to_state   : 'running',
            timestamp  : '2026-05-06T14:00:00.000Z',
            metadata   : { agent_type: 'DeepResearchJob' },
        },
        source : 'phase6a-smoke',
        ts     : Date.now(),
    });

    // Job 2: done (lands in `done` bucket).
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'fix-done-001',
            id_hash    : 'fix-done-001',
            from_state : null,
            to_state   : 'completed',
            timestamp  : '2026-05-06T14:01:00.000Z',
            metadata   : { agent_type: 'PodcastGeneratorJob' },
        },
        source : 'phase6a-smoke',
        ts     : Date.now(),
    });

    // Job 3: done → then removed (lands in `history` bucket via reducer).
    bus.emit({
        type    : 'job_state_transition',
        payload : {
            job_id     : 'fix-hist-001',
            id_hash    : 'fix-hist-001',
            from_state : null,
            to_state   : 'completed',
            timestamp  : '2026-05-06T14:02:00.000Z',
            metadata   : { agent_type: 'PresentationGeneratorJob' },
        },
        source : 'phase6a-smoke',
        ts     : Date.now(),
    });
    bus.emit({
        type    : 'job_removed',
        payload : { job_id: 'fix-hist-001', id_hash: 'fix-hist-001' },
        source  : 'phase6a-smoke',
        ts      : Date.now(),
    });

    return true;
}
"""


# ---------------------------------------------------------------------------
# AC8a — Functional smoke: 5 buckets present; 3 fixture jobs render correctly
# ---------------------------------------------------------------------------

def test_phase6a_functional_smoke():
    """AC8a — page loads; jobs-pane lifts hidden + data-phase6-pending; 5 buckets
    present; 3 fixture jobs render with the third landing in history bucket
    via the actual job_removed reducer path (not a fabricated status='history').
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            stub_empty_hydration( context )
            page    = context.new_page()
            page.goto( PHASE6A_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # Jobs-pane stays cold-HIDDEN on mount. Refreshed 2026-08-26: the
            # original AC8a assertion required `hidden` to be lifted here, but
            # JobsPaneRenderer stopped stripping it on 2026-07-02 (Lane 0c) —
            # Job Queues is hidden by default for legacy parity (Q3 RULED) and
            # visibility is now owned by the section toolbar as a persisted user
            # choice, not by this renderer. See JobsPaneRenderer.ts ~line 192.
            # The renderer still populates the buckets while the section is
            # hidden, which is what the rest of this test verifies.
            jobs_pane = page.locator( '[data-testid="multiplexer-jobs-pane"]' ).first
            assert jobs_pane.evaluate( "el => el.hasAttribute('hidden')" ) is True, (
                "jobs-pane should stay cold-hidden after mount (Lane 0c, 2026-07-02)"
            )
            assert jobs_pane.evaluate( "el => el.hasAttribute('data-phase6-pending')" ) is False, (
                "jobs-pane still has data-phase6-pending after mount"
            )

            # 5 bucket sections present, in render order.
            buckets = page.locator( '#jobs-buckets-container > .jobs-bucket' )
            assert buckets.count() == 5, f"expected 5 buckets, got {buckets.count()}"
            actual_order = page.evaluate(
                "() => Array.from(document.querySelectorAll('#jobs-buckets-container > .jobs-bucket'))"
                ".map(b => b.getAttribute('data-bucket'))"
            )
            assert actual_order == [ "todo", "running", "done", "dead", "history" ], (
                f"bucket render order wrong: {actual_order}"
            )

            # Inject the 3 fixture jobs.
            page.evaluate( _INJECT_3_JOBS_JS )

            # Wait for the 3 cards to appear across their respective buckets.
            # state="attached", not the default "visible": since Lane 0c
            # (2026-07-02) the jobs pane is cold-hidden, so its cards are in the
            # DOM but never visible until the user shows the section. The
            # contract this test verifies is that the renderer POPULATES the
            # buckets regardless of whether the section is shown.
            page.wait_for_selector( '[data-bucket="running"] [data-id-hash="fix-run-001"]', state="attached", timeout=2000 )
            page.wait_for_selector( '[data-bucket="done"] [data-id-hash="fix-done-001"]',   state="attached", timeout=2000 )
            page.wait_for_selector( '[data-bucket="history"] [data-id-hash="fix-hist-001"]', state="attached", timeout=2000 )

            # Total job-card count = 3 (one per bucket).
            card_count = page.locator( '#jobs-buckets-container .job-card' ).count()
            assert card_count == 3, f"expected 3 job cards, got {card_count}"
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC8a (per Pass 1 F7 + C-5) — Exact data-phase6-pending count assertion.
#
# HISTORY: Phase 5 left ≥3 pending markers; Phase 6a lifted #jobs-pane; Phase 6b
# lifted #tts-pane's marker on TtsChromeRenderer mount → floor = 0.
# USER-LIVE FLIP (2026-07-02, WP5 final unit): #tts-pane's stub marker is now also
# REMOVED from the static HTML (the pane is a first-class live section — fed +
# audible + card-styled), so the count is 0 both BEFORE and after mount. The
# assertion below stays == 0 as a cross-phase safety net: any future re-
# introduction of a placeholder fails loudly. (The phase6b "lifted after mount"
# assertion in test_multiplexer_phase6b_smoke.py is the load-bearing positive.)
# ---------------------------------------------------------------------------

def test_phase6a_data_phase6_pending_exact_count():
    """AC8a F7+C-5 + AC10e Phase 6b cascade — exactly 0 elements carry
    data-phase6-pending=true after the full Phase 6a + Phase 6b mount stack
    lifts every remaining placeholder. Phase 5 baseline was ≥3; Phase 6a
    dropped to 1 (#tts-pane); Phase 6b lifted #tts-pane → floor = 0. Per the
    plan's AC10e regression spec, this assertion stays as a cross-phase
    safety net so any future re-introduction of a placeholder fails loudly."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            stub_empty_hydration( context )
            page    = context.new_page()
            page.goto( PHASE6A_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            pending_count = page.locator( '[data-phase6-pending="true"]' ).count()
            assert pending_count == 0, (
                f"AC10e cascade violated: expected 0 data-phase6-pending elements after "
                f"Phase 6a + Phase 6b mount, got {pending_count}. Phase 6b lifts the "
                f"final placeholder on #tts-pane; any non-zero count means a new "
                f"placeholder was reintroduced without being claimed by a renderer."
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC8b — Perf gate: 50-job pre-seed paints within 150ms of boot_complete
# (slightly looser than Phase 5's 100ms because 5 nested buckets cost more
# parent-traversal than the flat sender-cards container).
# ---------------------------------------------------------------------------

_BULK_INJECT_50_JOBS_JS = """
( count ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;

    // Spread across 4 server states so all buckets get a share:
    //   pending → todo, running → running, completed → done, failed → dead
    const states = [ 'pending', 'running', 'completed', 'failed' ];

    const t0 = performance.now();
    for ( let i = 0; i < count; i++ ) {
        bus.emit({
            type    : 'job_state_transition',
            payload : {
                job_id     : 'bulk-' + i,
                id_hash    : 'bulk-' + i,
                from_state : null,
                to_state   : states[ i % states.length ],
                timestamp  : new Date( Date.UTC( 2026, 4, 6, 14, 0, i ) ).toISOString(),
                metadata   : { agent_type: 'BulkAgent' + ( i % 4 ) },
            },
            source : 'phase6a-perf-gate',
            ts     : Date.now(),
        });
    }
    return performance.now() - t0;
}
"""


def test_phase6a_perf_gate():
    """AC8b — 50-job pre-seed renders within 150ms of injection completion."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            stub_empty_hydration( context )
            page    = context.new_page()
            page.goto( PHASE6A_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # Burst-inject 50 jobs across the 4 active buckets.
            inject_duration_ms = page.evaluate( _BULK_INJECT_50_JOBS_JS, 50 )

            # Time paint completion.
            t_paint_start = page.evaluate( "() => performance.now()" )
            page.wait_for_function(
                """() => {
                    const cards = document.querySelectorAll('#jobs-buckets-container .job-card');
                    return cards.length >= 50;
                }""",
                timeout=2000,
            )
            t_paint_end = page.evaluate( "() => performance.now()" )

            paint_delta_ms = t_paint_end - t_paint_start
            assert paint_delta_ms < 150, (
                f"perf gate failed: paint took {paint_delta_ms}ms (>150ms); "
                f"inject took {inject_duration_ms}ms"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC9 — boot_complete handler handshake (Pass 2 F22: stable non-JSON line)
# ---------------------------------------------------------------------------

def test_phase6a_boot_complete_handler_handshake():
    """AC9 — boot.ts emits the literal stable line `[multiplexer] jobsRenderer:mounted`
    exactly once. Mirror-emit `[multiplexer] notificationsRenderer:mounted` for
    Phase 5 surface consistency. Robust against future serialization refactors
    (per F22)."""
    from playwright.sync_api import sync_playwright

    console_messages: list[ str ] = []
    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            stub_empty_hydration( context )
            page    = context.new_page()
            page.on( "console", lambda msg: console_messages.append( msg.text ) )
            page.goto( PHASE6A_PAGE_URL, wait_until="networkidle", timeout=15_000 )

            # Wait briefly for the boot_complete console.log line to land.
            time.sleep( 0.5 )

            jobs_renderer_lines = [ m for m in console_messages if m == "[multiplexer] jobsRenderer:mounted" ]
            assert len( jobs_renderer_lines ) == 1, (
                f"expected exactly 1 stable line `[multiplexer] jobsRenderer:mounted`, got "
                f"{len( jobs_renderer_lines )} (all console: {console_messages})"
            )

            # Mirror-emit assertion for Phase 5 surface consistency.
            notif_renderer_lines = [ m for m in console_messages if m == "[multiplexer] notificationsRenderer:mounted" ]
            assert len( notif_renderer_lines ) == 1, (
                f"expected exactly 1 stable line `[multiplexer] notificationsRenderer:mounted`, got "
                f"{len( notif_renderer_lines )}"
            )

            # The JSON-form boot_complete line is also emitted (Phase 5 contract preserved).
            json_lines = [ m for m in console_messages if "boot_complete" in m ]
            assert len( json_lines ) == 1, f"expected 1 JSON-form boot_complete line, got {len(json_lines)}"
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC10d layer-3 — CSS scope-leak canary (per Pass 2 F28)
#
# Loads the Phase 6a multiplexer page and captures getComputedStyle(body) on
# the canary axes ["color", "backgroundColor", "fontFamily", "margin",
# "padding"]. Asserts the values match the expected vanilla-body baseline
# (the existing `notifications-list.css *{}` rule sets font-family + box-sizing
# but does NOT touch body color/background/margin/padding). If jobs-pane.css
# ever drops a global rule (e.g. `body { background: red }`), this canary
# catches it even when stylelint and grep miss.
# ---------------------------------------------------------------------------

def test_phase6a_css_canary_no_body_drift():
    """AC10d layer-3 — proves jobs-pane.css contributes ZERO body-style drift.

    Strategy: load the page with all stylesheets active, capture
    getComputedStyle(body) (baseline-WITH); then programmatically disable
    just the jobs-pane.css stylesheet; recompute (baseline-WITHOUT). Assert
    the canary axes [color, backgroundColor, fontFamily, margin, padding]
    are unchanged. If jobs-pane.css ever drops a global rule (e.g.
    `body { background: red }`), disabling it would change the body's
    computed style — this canary catches what stylelint and grep miss
    (CSS custom-property leaks, cascade leaks via @layer / :where, etc.)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            stub_empty_hydration( context )
            page    = context.new_page()
            page.goto( PHASE6A_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            CANARY_AXES = [ "color", "backgroundColor", "fontFamily", "margin", "padding" ]

            cs_with = page.evaluate( """
                ( axes ) => {
                    const s = getComputedStyle( document.body );
                    const out = {};
                    for ( const k of axes ) out[ k ] = s[ k ];
                    return out;
                }
            """, CANARY_AXES )

            # Programmatically disable jobs-pane.css and recompute body style.
            cs_without = page.evaluate( """
                ( axes ) => {
                    let toggled = false;
                    for ( const sheet of Array.from( document.styleSheets ) ) {
                        const href = sheet.href || '';
                        if ( href.endsWith( '/jobs-pane.css' ) ) {
                            sheet.disabled = true;
                            toggled = true;
                        }
                    }
                    if ( !toggled ) {
                        throw new Error( 'jobs-pane.css stylesheet not found in document.styleSheets' );
                    }
                    const s = getComputedStyle( document.body );
                    const out = {};
                    for ( const k of axes ) out[ k ] = s[ k ];
                    return out;
                }
            """, CANARY_AXES )

            assert cs_with == cs_without, (
                f"jobs-pane.css contributed body-style drift on canary axes: "
                f"WITH={cs_with} WITHOUT={cs_without}"
            )
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(
        pytest.main( [ __file__, "-v", "--tb=short" ] )
    )
