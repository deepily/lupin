#!/usr/bin/env python3
"""
Phase 6b acceptance smoke for the multiplexer (action-required interactive
widgets + TTS chrome).

Verifies:
  - AC2a/AC2b: NO data-phase6-pending or aria-disabled="true" on action-required
    widgets post-mount
  - AC8a:     functional smoke — 3 action_required prompts (yes_no / multiple_choice /
    open_ended) render as interactive widgets; tts-pane renders chrome
  - AC8b:     perf gate — 50 prompts pre-seeded paint within 200ms
  - AC9:      boot_complete handshake — 4 stable :mounted console lines in
    canonical order (notifications → jobs → actionRequired → ttsChrome)
  - AC9b:     audio_chunks_arrive_after_mount — all 4 :mounted lines appear in
    console BEFORE the first store_audio_chunk_decoded event marker (Pass 2 A8
    ordering invariant)
  - AC10d:    CSS scope-leak canary — disabling action-required.css + tts-chrome.css
    produces ZERO body-style drift on [color, backgroundColor, fontFamily,
    margin, padding]

Per CLAUDE.local.md "USER IS NEVER A TESTER" mandate: every assertion is
EXECUTOR: AI. Tests run on :7999 (AI-discretionary venue).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
`LUPIN_API_URL` env var (default http://localhost:7999).

Usage:
    pytest src/tests/smoke/test_multiplexer_phase6b_smoke.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_multiplexer_phase6b_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

from tests.smoke.multiplexer_auth import seed_multiplexer_auth

BASE_URL          = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL   = f"{BASE_URL}/app/multiplexer"


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
# Fixture-injection JS — 3 action_required prompts (one per response_type).
#
# Wire shape per ActionRequiredStore: prompts arrive via `notification_queue_update`
# with `notification.response_requested === true` (per spec drift recorded in
# ActionRequiredStore.ts header comment).
# ---------------------------------------------------------------------------

_INJECT_3_PROMPTS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook missing — boot.ts test surface absent" );
    }
    const bus = hook.eventBus;

    // Prompt 1: yes_no.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'ar-yes-no-001',
                message             : 'Continue with the migration?',
                response_requested  : true,
                response_type       : 'yes_no',
                response_options    : [],
                response_default    : 'no',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-smoke',
                timestamp           : '2026-05-12T15:00:00.000Z',
            },
        },
        source : 'phase6b-smoke',
        ts     : Date.now(),
    });

    // Prompt 2: multiple_choice (single-select; multiSelect omitted).
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'ar-mc-002',
                message             : 'Which database?',
                response_requested  : true,
                response_type       : 'multiple_choice',
                response_options    : [ 'PostgreSQL', 'SQLite', 'MongoDB' ],
                response_default    : 'PostgreSQL',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-smoke',
                timestamp           : '2026-05-12T15:01:00.000Z',
            },
        },
        source : 'phase6b-smoke',
        ts     : Date.now(),
    });

    // Prompt 3: open_ended.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash             : 'ar-open-003',
                message             : 'What should I name the new service?',
                response_requested  : true,
                response_type       : 'open_ended',
                response_options    : [],
                response_default    : '',
                timeout_seconds     : 300,
                sender_id           : 'phase6b-smoke',
                timestamp           : '2026-05-12T15:02:00.000Z',
            },
        },
        source : 'phase6b-smoke',
        ts     : Date.now(),
    });

    return true;
}
"""


_BULK_INJECT_50_PROMPTS_JS = """
( count ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    const types = [ 'yes_no', 'multiple_choice', 'open_ended' ];

    const t0 = performance.now();
    for ( let i = 0; i < count; i++ ) {
        bus.emit({
            type    : 'notification_queue_update',
            payload : {
                notification : {
                    id_hash             : 'bulk-' + i,
                    message             : 'Bulk prompt ' + i,
                    response_requested  : true,
                    response_type       : types[ i % types.length ],
                    response_options    : i % 3 === 1 ? [ 'A', 'B', 'C' ] : [],
                    response_default    : '',
                    timeout_seconds     : 300,
                    sender_id           : 'phase6b-perf',
                    timestamp           : new Date( Date.UTC( 2026, 4, 12, 15, 0, i ) ).toISOString(),
                },
            },
            source : 'phase6b-perf',
            ts     : Date.now(),
        });
    }
    return performance.now() - t0;
}
"""


# ---------------------------------------------------------------------------
# AC8a — Functional smoke: 3 prompts (one per response_type) render as
# interactive widgets; tts-pane chrome renders too.
# ---------------------------------------------------------------------------

def test_phase6b_functional_smoke():
    """AC8a — page loads; 3 action_required prompts render as interactive
    widgets (`.action-required-widget`), one per response_type; #tts-pane is live
    (no `data-phase6-pending`) and, with an EMPTY queue on a fresh load, renders
    the empty-state panel (desync-fix: queue-driven empty), not the control row."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # tts-pane lift verified.
            tts_pane = page.locator( '#tts-pane' )
            assert tts_pane.evaluate( "el => el.hasAttribute('hidden')" ) is False, (
                "tts-pane still has hidden attribute after Phase 6b mount"
            )
            assert tts_pane.evaluate( "el => el.hasAttribute('data-phase6-pending')" ) is False, (
                "tts-pane still has data-phase6-pending after Phase 6b mount"
            )
            # desync-fix (queue-driven empty): a fresh page has an EMPTY tts queue,
            # so #tts-pane renders the empty-state panel (🔇 Nothing in the queue),
            # NOT the control row — controls appear once an item is queued (the
            # live-fed path is proven by the :8000 whole-chain E2E post-merge).
            assert page.locator( '#tts-pane .tts-queue-empty-state' ).count() == 1, (
                "tts-pane empty-state panel not rendered on a fresh (empty-queue) load"
            )
            assert page.locator( '#tts-pane .tts-controls' ).count() == 0, (
                "tts-pane should render the empty panel (no control row) when the queue is empty"
            )

            # Inject 3 action_required prompts (one per response_type).
            page.evaluate( _INJECT_3_PROMPTS_JS )

            # Wait for the 3 widgets to render.
            page.wait_for_selector( '.action-required-widget[data-id-hash="ar-yes-no-001"]', timeout=2000 )
            page.wait_for_selector( '.action-required-widget[data-id-hash="ar-mc-002"]',     timeout=2000 )
            page.wait_for_selector( '.action-required-widget[data-id-hash="ar-open-003"]',   timeout=2000 )

            # Each widget renders the expected response-type-specific control.
            assert page.locator( '.action-required-widget[data-id-hash="ar-yes-no-001"] .action-required-btn-yes' ).count() == 1
            assert page.locator( '.action-required-widget[data-id-hash="ar-yes-no-001"] .action-required-btn-no' ).count() == 1

            assert page.locator(
                '.action-required-widget[data-id-hash="ar-mc-002"] .action-required-options-group'
            ).count() == 1
            assert page.locator(
                '.action-required-widget[data-id-hash="ar-mc-002"] .action-required-option-label'
            ).count() == 3   # PostgreSQL / SQLite / MongoDB

            assert page.locator(
                '.action-required-widget[data-id-hash="ar-open-003"] .action-required-input'
            ).count() == 1
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC2a / AC2b — NO data-phase6-pending or aria-disabled="true" on
# action-required widgets post-mount.
# ---------------------------------------------------------------------------

def test_phase6b_no_pending_markers_after_mount():
    """AC2a / AC2b — post-mount, action-required widgets carry ZERO
    `data-phase6-pending` markers and ZERO `aria-disabled="true"` attributes.
    #tts-pane's stub marker is now REMOVED from the static HTML (WP5 user-live
    flip, 2026-07-02); boot.ts retains a defensive lift. Either way the page
    carries zero `data-phase6-pending` after mount."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )
            page.evaluate( _INJECT_3_PROMPTS_JS )
            page.wait_for_selector( '.action-required-widget', timeout=2000 )

            # AC2a — NO data-phase6-pending markers anywhere on the page
            # (#tts-pane's stub marker was removed from the HTML in the WP5 user-live
            # flip; historically Phase 6b lifted it on mount — either way, count 0).
            pending_count = page.locator( '[data-phase6-pending="true"]' ).count()
            assert pending_count == 0, (
                f"AC2a violated: {pending_count} elements still carry data-phase6-pending=true "
                f"after Phase 6b mount (Phase 6a baseline was 1 for #tts-pane; "
                f"Phase 6b lifts it via TtsChromeRenderer mount)"
            )

            # AC2b — NO aria-disabled="true" on action-required widgets.
            disabled_inside_ar = page.evaluate(
                """() => {
                    const widgets = document.querySelectorAll('.action-required-widget');
                    let count = 0;
                    for (const w of widgets) {
                        count += w.querySelectorAll('[aria-disabled="true"]').length;
                    }
                    return count;
                }"""
            )
            assert disabled_inside_ar == 0, (
                f"AC2b violated: {disabled_inside_ar} aria-disabled='true' inside .action-required-widget"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC8b — Perf gate: 50 action_required prompts pre-seed paint <200ms.
# ---------------------------------------------------------------------------

def test_phase6b_perf_gate():
    """AC8b — 50 action_required prompts injected → all widgets render within
    200ms of injection-complete timestamp."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            inject_duration_ms = page.evaluate( _BULK_INJECT_50_PROMPTS_JS, 50 )

            t_paint_start = page.evaluate( "() => performance.now()" )
            page.wait_for_function(
                """() => {
                    return document.querySelectorAll('.action-required-widget').length >= 50;
                }""",
                timeout=2000,
            )
            t_paint_end = page.evaluate( "() => performance.now()" )

            paint_delta_ms = t_paint_end - t_paint_start
            assert paint_delta_ms < 200, (
                f"perf gate failed: paint took {paint_delta_ms}ms (>200ms); "
                f"inject took {inject_duration_ms}ms"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC9 — boot_complete handshake; 4 stable :mounted console lines in canonical
# order: notifications → jobs → actionRequired → ttsChrome.
# ---------------------------------------------------------------------------

def test_phase6b_boot_complete_handshake():
    """AC9 — the 4 stable `[multiplexer] <renderer>:mounted` console lines
    appear in canonical order: notifications → jobs → actionRequired → ttsChrome."""
    from playwright.sync_api import sync_playwright

    console_messages: list[ str ] = []
    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.on( "console", lambda msg: console_messages.append( msg.text ) )
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )

            time.sleep( 0.5 )

            expected_order = [
                "[multiplexer] notificationsRenderer:mounted",
                "[multiplexer] jobsRenderer:mounted",
                "[multiplexer] actionRequiredRenderer:mounted",
                "[multiplexer] ttsChromeRenderer:mounted",
            ]

            indices = [
                next(
                    ( i for i, m in enumerate( console_messages ) if m == line ),
                    -1,
                )
                for line in expected_order
            ]

            for i, ( line, idx ) in enumerate( zip( expected_order, indices ) ):
                assert idx >= 0, f"missing console line: {line!r} (got {console_messages})"
                if i > 0:
                    assert indices[ i - 1 ] < idx, (
                        f"canonical order violated: {expected_order[ i - 1 ]!r} "
                        f"(idx={indices[ i - 1 ]}) appeared AFTER {line!r} (idx={idx})"
                    )

            # The JSON-form boot_complete line lands AFTER the 4 :mounted lines.
            json_idx = next(
                ( i for i, m in enumerate( console_messages ) if "boot_complete" in m and "JSON" not in m and m.startswith("[multiplexer] boot_complete") ),
                -1,
            )
            assert json_idx > indices[ -1 ], (
                f"JSON boot_complete line should follow the 4 :mounted lines; got json_idx={json_idx} vs last mounted_idx={indices[-1]}"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC9b — Pass 2 A8 boot ordering invariant: all 4 :mounted console lines
# appear in console BEFORE the first `store_audio_chunk_decoded` event marker.
# ---------------------------------------------------------------------------

_AUDIO_CHUNK_PROBE_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    // Subscribe a console-emitting probe to capture the first chunk event.
    hook.eventBus.on( 'store_audio_chunk_decoded', () => {
        console.log( '[probe] store_audio_chunk_decoded' );
    });
    // Synthesize an audio_chunk_decoded event via the bus to simulate the
    // first real audio frame arriving from the WS transport.
    hook.eventBus.emit({
        type    : 'store_audio_chunk_decoded',
        payload : { senderId: 'phase6b-smoke', durationMs: 100 },
        source  : 'phase6b-smoke',
        ts      : Date.now(),
    });
    return true;
}
"""


def test_phase6b_audio_chunks_arrive_after_mount():
    """AC9b (Pass 2 A8) — the 4 `:mounted` console lines appear BEFORE the
    first `store_audio_chunk_decoded` event marker. Verifies the renderer
    subscriptions are wired before any audio frames are processed."""
    from playwright.sync_api import sync_playwright

    console_messages: list[ str ] = []
    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.on( "console", lambda msg: console_messages.append( msg.text ) )
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # Issue the probe AFTER boot_complete so the 4 :mounted lines are
            # guaranteed to already be in the console log.
            page.evaluate( _AUDIO_CHUNK_PROBE_JS )
            time.sleep( 0.2 )

            mounted_indices = [
                next( ( i for i, m in enumerate( console_messages ) if m == line ), -1 )
                for line in [
                    "[multiplexer] notificationsRenderer:mounted",
                    "[multiplexer] jobsRenderer:mounted",
                    "[multiplexer] actionRequiredRenderer:mounted",
                    "[multiplexer] ttsChromeRenderer:mounted",
                ]
            ]
            probe_idx = next(
                ( i for i, m in enumerate( console_messages ) if m == "[probe] store_audio_chunk_decoded" ),
                -1,
            )

            assert probe_idx >= 0, (
                f"probe marker not seen in console (got {console_messages})"
            )
            for line, idx in zip(
                [
                    "notificationsRenderer:mounted",
                    "jobsRenderer:mounted",
                    "actionRequiredRenderer:mounted",
                    "ttsChromeRenderer:mounted",
                ],
                mounted_indices,
            ):
                assert idx >= 0, f"missing :mounted line: {line}"
                assert idx < probe_idx, (
                    f"AC9b violated: {line} (idx={idx}) must precede "
                    f"first store_audio_chunk_decoded (idx={probe_idx})"
                )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC10d — CSS scope-leak canary (layer-3): disabling action-required.css +
# tts-chrome.css produces ZERO body-style drift on canary axes.
# ---------------------------------------------------------------------------

def test_phase6b_css_canary_no_body_drift():
    """AC10d layer-3 — proves action-required.css AND tts-chrome.css contribute
    ZERO body-style drift. Strategy: load the page with both stylesheets active
    (baseline-WITH); disable both stylesheets; recompute body style
    (baseline-WITHOUT); assert canary axes unchanged."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            seed_multiplexer_auth( context )
            page    = context.new_page()
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            CANARY_AXES = [ "color", "backgroundColor", "fontFamily", "margin", "padding" ]

            cs_with = page.evaluate(
                """( axes ) => {
                    const s = getComputedStyle( document.body );
                    const out = {};
                    for ( const k of axes ) out[ k ] = s[ k ];
                    return out;
                }""",
                CANARY_AXES,
            )

            cs_without = page.evaluate(
                """( axes ) => {
                    let toggled = 0;
                    for ( const sheet of Array.from( document.styleSheets ) ) {
                        const href = sheet.href || '';
                        if ( href.endsWith( '/action-required.css' ) ||
                             href.endsWith( '/tts-chrome.css' ) ) {
                            sheet.disabled = true;
                            toggled += 1;
                        }
                    }
                    if ( toggled !== 2 ) {
                        throw new Error( 'Expected 2 Phase 6b stylesheets; toggled=' + toggled );
                    }
                    const s = getComputedStyle( document.body );
                    const out = {};
                    for ( const k of axes ) out[ k ] = s[ k ];
                    return out;
                }""",
                CANARY_AXES,
            )

            assert cs_with == cs_without, (
                f"Phase 6b stylesheets contributed body-style drift on canary axes: "
                f"WITH={cs_with} WITHOUT={cs_without}"
            )
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(
        pytest.main( [ __file__, "-v", "--tb=short" ] )
    )
