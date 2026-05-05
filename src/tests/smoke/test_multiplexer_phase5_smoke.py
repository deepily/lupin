#!/usr/bin/env python3
"""
Phase 5 acceptance smoke for the multiplexer notifications-list pane.

Verifies AC8a (functional smoke), AC8b (perf gate), AC9 (boot_complete handler
handshake) from the design doc:
    src/rnd/v0.1.7/2026.05.02-notifications-ui-js-refactor/06-phase5-renderer-design.md

Per CLAUDE.local.md "USER IS NEVER A TESTER" mandate: every assertion is
EXECUTOR: AI. Tests run on :7999 (AI-discretionary venue per design doc).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
`LUPIN_API_URL` env var (default http://localhost:7999).

Fixture injection mechanism (D-E ratification 2026-05-05): tests use
`page.evaluate(window.__multiplexerTestHook.eventBus.emit(...))` to inject
notification envelopes directly into EventBus, bypassing the WebSocket
transport. The boot.ts test hook surfaces eventBus + stores under a global
property NOT covered by the no-globals ESLint rule.

Usage:
    pytest src/tests/smoke/test_multiplexer_phase5_smoke.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_multiplexer_phase5_smoke.py -v
"""

from __future__ import annotations

import json
import os
import time

import pytest

BASE_URL = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )

PHASE5_PAGE_URL = f"{BASE_URL}/app/multiplexer"


# ---------------------------------------------------------------------------
# Fixture envelopes (Phase 5 D-E)
# ---------------------------------------------------------------------------

def _plain_fixture( id_hash: str = "fix_plain", ts_iso: str = "2026-05-05T14:07:00.000Z" ) -> dict:
    return {
        "id_hash"          : id_hash,
        "message"          : "plain text fixture body",
        "sender_id"        : "fixture_sender_a",
        "timestamp"        : ts_iso,
        "response_requested": False,
    }


def _markdown_fixture( id_hash: str = "fix_md", ts_iso: str = "2026-05-05T14:07:00.000Z" ) -> dict:
    return {
        "id_hash"          : id_hash,
        "message"          : "**bold** _italic_ message",
        "sender_id"        : "fixture_sender_b",
        "timestamp"        : ts_iso,
        "response_requested": False,
    }


def _action_required_fixture( id_hash: str = "fix_ar", ts_iso: str = "2026-05-05T14:07:00.000Z" ) -> dict:
    return {
        "id_hash"          : id_hash,
        "message"          : "Approve the deploy?",
        "sender_id"        : "fixture_sender_c",
        "timestamp"        : ts_iso,
        "response_requested": True,
        "response_type"    : "yes_no",
        "response_options" : [ "yes", "no" ],
        "timeout_seconds"  : 60,
    }


# JS snippet to wait for the test hook to be ready then inject a notification
# fixture via eventBus.emit(notification_queue_update).
_INJECT_JS = """
( fixture ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present — boot.ts test surface missing" );
    }
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : { queue_name: 'notification', value: 1, notification: fixture },
        source  : 'phase5-smoke-test',
        ts      : Date.now(),
    } );
    return true;
}
"""

# Inject an action-required item into ActionRequiredStore by emitting on
# bus. Uses NEW Date().toISOString() at JS-eval time so expires_at is in
# the future (test fixture timestamps must be live-relative for the
# ActionRequiredStore countdown timer to produce a positive value).
_INJECT_AR_JS = """
( opts ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) {
        throw new Error( "test hook not present" );
    }
    const fixture = {
        id_hash    : opts.id_hash,
        message    : opts.message,
        sender_id  : opts.sender_id,
        timestamp  : new Date().toISOString(),
        response_requested: true,
        response_type    : opts.response_type,
        response_options : opts.response_options,
        timeout_seconds  : opts.timeout_seconds,
    };
    hook.eventBus.emit( {
        type    : 'notification_queue_update',
        payload : { queue_name: 'notification', value: 1, notification: fixture },
        source  : 'phase5-smoke-test',
        ts      : Date.now(),
    } );
    return true;
}
"""


def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    """Poll for the boot.ts test hook to be ready (post-boot_complete)."""
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


# ---------------------------------------------------------------------------
# AC8a — Functional smoke: 3 fixtures render within 500ms; data-phase6-pending ≥3
# ---------------------------------------------------------------------------

def test_phase5_functional_smoke():
    """AC8a — 3 fixtures (plain, markdown, action-required) render within
    500ms of boot_complete; data-phase6-pending count ≥ 3 (D-K)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=["--autoplay-policy=no-user-gesture-required"] )
        try:
            context = browser.new_context()
            page    = context.new_page()
            page.goto( PHASE5_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # Capture boot_complete timestamp + measure mount-to-paint delta.
            boot_complete_ts = page.evaluate( "() => window.__multiplexerTestHook.bootCompleteTs" )
            assert boot_complete_ts > 0

            # Inject 3 fixtures.
            page.evaluate( _INJECT_JS, _plain_fixture() )
            page.evaluate( _INJECT_JS, _markdown_fixture() )
            page.evaluate( _INJECT_AR_JS, {
                "id_hash"          : "fix_ar",
                "message"          : "Approve the deploy?",
                "sender_id"        : "fixture_sender_c",
                "response_type"    : "yes_no",
                "response_options" : [ "yes", "no" ],
                "timeout_seconds"  : 60,
            } )

            # Wait for the 2 sender cards (plain + markdown). Action-required
            # widget renders in #action-required-section.
            t_inject_done = page.evaluate( "() => performance.now()" )
            page.wait_for_selector(
                '[data-testid="multiplexer-sender-cards"] [data-id-hash="fixture_sender_a"]',
                timeout=2000,
            )
            page.wait_for_selector(
                '[data-testid="multiplexer-sender-cards"] [data-id-hash="fixture_sender_b"]',
                timeout=2000,
            )
            page.wait_for_selector(
                '[data-testid="multiplexer-action-required"]',
                timeout=2000,
            )
            t_paint_done = page.evaluate( "() => performance.now()" )

            # AC8a paint budget: 500ms from inject to paint.
            paint_delta_ms = t_paint_done - t_inject_done
            assert paint_delta_ms < 500, f"paint took {paint_delta_ms}ms, expected <500ms"

            # AC8a count assertion: 2 sender cards.
            sender_card_count = page.locator( '[data-testid="multiplexer-sender-cards"] > .sender-card' ).count()
            assert sender_card_count == 2, f"expected 2 sender cards, got {sender_card_count}"

            # AC8a plain notification body equals fixture text.
            plain_message_text = page.locator(
                '[data-id-hash="fixture_sender_a"] .message-text'
            ).first.text_content()
            assert plain_message_text is not None
            assert "plain text fixture body" in plain_message_text, (
                f"plain message text: {plain_message_text!r}"
            )

            # AC8a markdown notification contains rendered HTML (vendor marked
            # globals are loaded — should produce <strong> + <em>).
            md_message_html = page.locator(
                '[data-id-hash="fixture_sender_b"] .message-text'
            ).first.inner_html()
            # marked.min.js renders **bold** → <strong>bold</strong>; _italic_ → <em>italic</em>.
            # Accept either tag set (em vs i, strong vs b) — DOMPurify allows both.
            assert "<strong>" in md_message_html or "<b>" in md_message_html, (
                f"markdown not rendered as HTML: {md_message_html!r}"
            )

            # AC8a countdown ticks: capture .action-required-countdown text twice
            # 1100ms apart; values must differ.
            cd_locator = page.locator( '.action-required-countdown' ).first
            cd_t1 = cd_locator.text_content()
            time.sleep( 1.1 )
            cd_t2 = cd_locator.text_content()
            # In Phase 5, the ActionRequiredStore's per-actor setInterval(1000)
            # emits store_action_required_changed { changeKind: "tick" } at 1Hz.
            # Two samples 1100ms apart MUST observe different values.
            assert cd_t1 != cd_t2, (
                f"countdown did not tick: t1={cd_t1!r} t2={cd_t2!r}"
            )

            # AC8a (D-K) — data-phase6-pending count ≥ 3 (2 hidden panes +
            # ≥1 action-required widget).
            pending_count = page.locator( '[data-phase6-pending="true"]' ).count()
            assert pending_count >= 3, f"expected ≥3 phase6-pending, got {pending_count}"
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC8b — Perf gate: 50-fixture pre-seed renders within 100ms
# ---------------------------------------------------------------------------

_BULK_INJECT_JS = """
( count ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );

    const t0 = performance.now();
    for ( let i = 0; i < count; i++ ) {
        hook.eventBus.emit( {
            type    : 'notification_queue_update',
            payload : {
                queue_name: 'notification', value: i,
                notification: {
                    id_hash    : 'bulk_' + i,
                    message    : 'bulk msg ' + i,
                    sender_id  : 'bulk_sender_' + ( i % 5 ),
                    timestamp  : new Date( Date.UTC( 2026, 4, 5, 14, 7, i ) ).toISOString(),
                    response_requested: false,
                }
            },
            source : 'phase5-perf-gate',
            ts     : Date.now(),
        } );
    }
    return performance.now() - t0;
}
"""


def test_phase5_perf_gate():
    """AC8b — 50-fixture seed; first paint of count===50 within 100ms (D-K perf budget)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=["--autoplay-policy=no-user-gesture-required"] )
        try:
            context = browser.new_context()
            page    = context.new_page()
            page.goto( PHASE5_PAGE_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )

            # Burst-inject 50 notifications.
            inject_duration_ms = page.evaluate( _BULK_INJECT_JS, 50 )

            # Time paint completion.
            t_paint_start = page.evaluate( "() => performance.now()" )
            page.wait_for_function(
                """() => {
                    const cards = document.querySelectorAll('[data-testid="multiplexer-sender-cards"] > .sender-card');
                    if ( cards.length === 0 ) return false;
                    let total = 0;
                    cards.forEach(c => {
                        total += c.querySelectorAll('.sender-message').length;
                    });
                    return total >= 50;
                }""",
                timeout=2000,
            )
            t_paint_end = page.evaluate( "() => performance.now()" )

            paint_delta_ms = t_paint_end - t_paint_start
            # Total budget = inject + paint. Paint window alone must be < 100ms
            # per AC8b. The inject itself is also time-bounded but not part of
            # this AC.
            assert paint_delta_ms < 100, (
                f"perf gate failed: paint took {paint_delta_ms}ms (>100ms); "
                f"inject took {inject_duration_ms}ms"
            )
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# AC9 — boot_complete handler handshake (independent context per A3)
# ---------------------------------------------------------------------------

def test_phase5_boot_complete_handler_handshake():
    """AC9 — boot_complete console line includes notificationsRenderer:mounted exactly once."""
    from playwright.sync_api import sync_playwright

    console_messages: list[ str ] = []
    with sync_playwright() as p:
        browser = p.chromium.launch( headless=True, args=["--autoplay-policy=no-user-gesture-required"] )
        try:
            context = browser.new_context()
            page    = context.new_page()
            page.on( "console", lambda msg: console_messages.append( msg.text ) )
            page.goto( PHASE5_PAGE_URL, wait_until="networkidle", timeout=15_000 )

            # Wait briefly for the boot_complete console.log to land.
            time.sleep( 0.5 )

            # AC9 — locate the boot_complete line and parse its JSON payload.
            boot_lines = [ m for m in console_messages if "boot_complete" in m ]
            assert len( boot_lines ) >= 1, (
                f"no boot_complete console line found; saw: {console_messages}"
            )

            # The console line format is:
            #   "[multiplexer] boot_complete {\"handlers\":{\"audioBinary\":\"...\",\"notificationsRenderer\":\"mounted\"}}"
            # console.log writes args separated by space; Playwright concatenates
            # them in `msg.text`.
            matched = None
            for line in boot_lines:
                if "notificationsRenderer" in line:
                    matched = line
                    break
            assert matched is not None, (
                f"boot_complete line lacks notificationsRenderer: {boot_lines!r}"
            )

            # F22 invariant: literal string "mounted", NOT function-name.
            assert "notificationsRenderer" in matched, (
                f"matched line missing key: {matched!r}"
            )
            assert "mounted" in matched, (
                f"matched line missing 'mounted' literal: {matched!r}"
            )

            # AC9 spec: the substring 'notificationsRenderer:mounted' (or
            # JSON form) appears at least once.
            count = sum( 1 for line in console_messages if "notificationsRenderer" in line and "mounted" in line )
            assert count == 1, f"expected exactly 1 boot_complete with notificationsRenderer:mounted, got {count}"
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(
        pytest.main( [ __file__, "-v", "--tb=short" ] )
    )
