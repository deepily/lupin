#!/usr/bin/env python3
"""
Phase 6c acceptance smoke for the multiplexer.

This file is the SHARED smoke harness for all four Phase 6c sections
(D/B/A/C) per execution plan §3.D.1 + §3.B.1 + §3.A.1 + §3.C.1 — each
section appends its own tests here as it ships.

Currently populated for Section D (ConversationModePinRenderer) per Path δ
scope reduction (Rick 2026-05-19; mic_monopoly DEFERRED to Phase 6c follow-on).

Verifies (Section D):
  - AC-D10: 5 functional cases — pin_attribute, pin_moves_top,
    pin_between_senders, focus_flash, focus_flash_auto_removes
  - AC-D11: boot handshake — 5 stable :mounted console lines in canonical
    order (notifications → jobs → actionRequired → ttsChrome →
    conversationModePin)
  - AC-D12: perf gate — 20-sender pin/un-pin paint < 100 ms

Per CLAUDE.local.md "USER IS NEVER A TESTER" mandate: every assertion is
EXECUTOR: AI. Tests run on :7999 (AI-discretionary venue).

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via
`LUPIN_API_URL` env var (default http://localhost:7999).

Usage:
    pytest src/tests/smoke/test_multiplexer_phase6c_smoke.py -v
    LUPIN_API_URL=http://localhost:7999 pytest src/tests/smoke/test_multiplexer_phase6c_smoke.py -v
"""

from __future__ import annotations

import os
import time

import pytest

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"


# ---------------------------------------------------------------------------
# Test-hook polling (shared with Phase 5/6a/6b smokes)
# ---------------------------------------------------------------------------

def _wait_for_test_hook( page, timeout_ms: int = 10_000 ) -> None:
    """Poll for boot.ts test hook to be ready (post-boot_complete)."""
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=timeout_ms,
    )


# ---------------------------------------------------------------------------
# Fixture JS — Section D scenarios
# ---------------------------------------------------------------------------

_SEED_TWO_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    // Two regular notifications create two sender cards.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash   : 'n-a',
                message   : 'msg from A',
                sender_id : 'sess-a',
                timestamp : '2026-05-19T15:00:00.000Z',
                type      : 'task',
            },
        },
        source : 'phase6c-smoke',
        ts     : Date.now(),
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash   : 'n-b',
                message   : 'msg from B',
                sender_id : 'sess-b',
                timestamp : '2026-05-19T16:00:00.000Z',
                type      : 'task',
            },
        },
        source : 'phase6c-smoke',
        ts     : Date.now(),
    });
    return true;
}
"""

# Activate conversation mode for the named sender via conversation_mode_changed.
# Server-side rename pending; Path III bridge accepts payload.active OR payload.on.
_ACTIVATE_CONV_MODE_JS = """
( sender_id ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                type      : 'conversation_mode_changed',
                sender_id : sender_id,
                timestamp : '2026-05-19T15:30:00.000Z',
                payload   : { session_id: sender_id, active: true },
            },
        },
        source : 'phase6c-smoke',
        ts     : Date.now(),
    });
    return true;
}
"""

_DEACTIVATE_CONV_MODE_JS = """
( sender_id ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                type      : 'conversation_mode_changed',
                sender_id : sender_id,
                timestamp : '2026-05-19T15:31:00.000Z',
                payload   : { session_id: sender_id, active: false },
            },
        },
        source : 'phase6c-smoke',
        ts     : Date.now(),
    });
    return true;
}
"""


def _new_page( pw ):
    browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
    context = browser.new_context()
    page    = context.new_page()
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    _wait_for_test_hook( page )
    return browser, context, page


# ===========================================================================
# AC-D10 #1 : pin_attribute — conversation_mode_changed → data-pinned-conv-mode="true"
# ===========================================================================

def test_pin_attribute_applied_on_conversation_mode_active():
    """AC-D10 #1: activating conversation mode for a sender sets
    `data-pinned-conv-mode="true"` on that sender's card."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            # Let the reducer + reconcile flush.
            page.wait_for_selector( '.sender-card[data-sender-id="sess-a"][data-pinned-conv-mode="true"]', timeout=2000 )
            assert page.locator( '.sender-card[data-sender-id="sess-b"]' ).get_attribute( 'data-pinned-conv-mode' ) is None
        finally:
            browser.close()


# ===========================================================================
# AC-D10 #2 : pin_moves_top — pinned sender card renders FIRST in DOM order
#   (Phase 6c sort comparator: pinned sender hoists above more-active unpinned)
# ===========================================================================

def test_pinned_sender_moves_to_top_of_list():
    """AC-D10 #2: with B more-recently-active than A, activating conv-mode
    on A hoists A's card to position 0 (above B)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            # Before activation: B's notification ts is newer → B renders first.
            cards_before = page.locator( '.sender-card' ).evaluate_all(
                "els => els.map(e => e.getAttribute('data-sender-id'))" )
            assert cards_before[ 0 ] == 'sess-b', f"pre-condition: B (newer) should be first; got {cards_before}"

            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            # Trigger a notification update to force the sender-section re-render
            # (Phase 6c sort comparator is applied at sort time inside
            # renderSenderSection; store emission of store_senders_changed
            # already drives that re-render).
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-a"][data-pinned-conv-mode="true"]',
                timeout=2000,
            )
            cards_after = page.locator( '.sender-card' ).evaluate_all(
                "els => els.map(e => e.getAttribute('data-sender-id'))" )
            assert cards_after[ 0 ] == 'sess-a', f"post-activation: A (pinned) should be first; got {cards_after}"
        finally:
            browser.close()


# ===========================================================================
# AC-D10 #3 : pin_between_senders — A→B pin-move clears A, sets B
# ===========================================================================

def test_pin_moves_between_senders():
    """AC-D10 #3: activating B while A is pinned → A's attribute clears,
    B's attribute sets (dual-emission single-pin invariant)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-a"][data-pinned-conv-mode="true"]',
                timeout=2000,
            )

            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-b" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-b"][data-pinned-conv-mode="true"]',
                timeout=2000,
            )
            # A must no longer carry the attribute.
            assert page.locator( '.sender-card[data-sender-id="sess-a"]' ).get_attribute( 'data-pinned-conv-mode' ) is None
        finally:
            browser.close()


# ===========================================================================
# AC-D10 #4 : focus_flash — pin-MOVE triggers data-focus-flash="true" on new card
# ===========================================================================

def test_pin_move_triggers_focus_flash_on_new_card():
    """AC-D10 #4: when pin MOVES from A → B (not first-time activation),
    the new card receives `data-focus-flash="true"`."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            # First activation (A) → NO flash (lastPinned starts null).
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-a"][data-pinned-conv-mode="true"]',
                timeout=2000,
            )
            assert page.locator( '.sender-card[data-sender-id="sess-a"]' ).get_attribute( 'data-focus-flash' ) is None, (
                "first-time activation must NOT trigger focus-flash"
            )

            # Pin-MOVE A → B → B gets the flash.
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-b" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-b"][data-focus-flash="true"]',
                timeout=2000,
            )
        finally:
            browser.close()


# ===========================================================================
# AC-D10 #5 : focus_flash_auto_removes — after ~1.2s the attribute disappears
# ===========================================================================

def test_focus_flash_auto_removes_after_duration():
    """AC-D10 #5: the data-focus-flash attribute auto-removes after the
    flash duration (production 1.2s; wait 1.5s to be safe)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-a"][data-pinned-conv-mode="true"]',
                timeout=2000,
            )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-b" )
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-b"][data-focus-flash="true"]',
                timeout=2000,
            )

            # Wait 1.5s — exceeds the 1.2s flash duration.
            time.sleep( 1.5 )
            assert page.locator( '.sender-card[data-sender-id="sess-b"]' ).get_attribute( 'data-focus-flash' ) is None, (
                "focus-flash attribute must auto-remove after 1.2s"
            )
        finally:
            browser.close()


# ===========================================================================
# AC-D11 : boot handshake — 5 stable :mounted console lines in canonical order
# ===========================================================================

def test_boot_handshake_emits_canonical_mounted_lines_in_order():
    """AC-D11 + AC-B11: console emits the canonical :mounted lines in order
    BEFORE the JSON `boot_complete` line. Sequence:
        notifications → jobs → actionRequired → ttsChrome →
        conversationModePin (Node D) → focusTray (Node B)
    Future Node A + C land their lines after focusTray when they ship."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
            page    = context.new_page()
            log_lines: list[ str ] = []
            page.on( "console", lambda msg: log_lines.append( msg.text ) )
            page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
            _wait_for_test_hook( page )
            # Extract the [multiplexer] :mounted lines in order.
            mount_lines = [ line for line in log_lines if ":mounted" in line and "[multiplexer]" in line ]
            expected = [
                "[multiplexer] notificationsRenderer:mounted",
                "[multiplexer] jobsRenderer:mounted",
                "[multiplexer] actionRequiredRenderer:mounted",
                "[multiplexer] ttsChromeRenderer:mounted",
                "[multiplexer] conversationModePinRenderer:mounted",
                "[multiplexer] focusTrayRenderer:mounted",
                "[multiplexer] personaModalRenderer:mounted",
                "[multiplexer] senderCardRecorderRenderer:mounted",
            ]
            assert mount_lines == expected, (
                f"boot handshake mismatch:\nexpected={expected}\ngot     ={mount_lines}"
            )
        finally:
            browser.close()


# ===========================================================================
# AC-D12 : perf gate — 20-sender pin/un-pin paint < 100 ms
# ===========================================================================

_SEED_20_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    for ( let i = 0; i < 20; i++ ) {
        bus.emit({
            type    : 'notification_queue_update',
            payload : {
                notification : {
                    id_hash   : 'n-' + i,
                    message   : 'msg ' + i,
                    sender_id : 'sess-' + i,
                    timestamp : new Date( Date.UTC( 2026, 4, 19, 15, 0, i ) ).toISOString(),
                    type      : 'task',
                },
            },
            source : 'phase6c-perf',
            ts     : Date.now(),
        });
    }
    return true;
}
"""

# Measure round-trip pin/un-pin on the 0th sender across all 20.
_PIN_UNPIN_PAINT_TIMING_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    const t0 = performance.now();
    // Activate then deactivate sess-0 (one full reconcile cycle each).
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type      : 'conversation_mode_changed',
            sender_id : 'sess-0',
            timestamp : '2026-05-19T15:30:00.000Z',
            payload   : { session_id: 'sess-0', active: true },
        } },
        source : 'phase6c-perf',
        ts     : Date.now(),
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type      : 'conversation_mode_changed',
            sender_id : 'sess-0',
            timestamp : '2026-05-19T15:30:01.000Z',
            payload   : { session_id: 'sess-0', active: false },
        } },
        source : 'phase6c-perf',
        ts     : Date.now(),
    });
    return performance.now() - t0;
}
"""


def test_perf_20_sender_pin_unpin_under_100ms():
    """AC-D12: with 20 sender cards painted, a full pin/un-pin reconciliation
    cycle completes in < 100ms (measured in-browser via performance.now)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_20_SENDERS_JS )
            # Wait for the 20 cards to actually render.
            page.wait_for_function(
                "() => document.querySelectorAll('.sender-card').length === 20",
                timeout=5_000,
            )
            elapsed_ms = page.evaluate( _PIN_UNPIN_PAINT_TIMING_JS )
            assert elapsed_ms < 100, f"perf gate breach: {elapsed_ms:.1f}ms ≥ 100ms"
        finally:
            browser.close()


# ===========================================================================
# AC-A10 : Section A — voice-persona modal smoke
# ===========================================================================

_SEED_SENDER_WITH_PERSONA_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    // Regular notification to create the sender card.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash   : 'n-persona-a',
                message   : 'hello from persona-a',
                sender_id : 'persona-a',
                timestamp : '2026-05-19T15:00:00.000Z',
                type      : 'task',
            },
        },
        source : 'phase6c-a-smoke',
        ts     : Date.now(),
    });
    // voice_persona_assigned to attach persona — uses notification-subsystem custom type
    // per 2026-04-29 cleanup. SenderStore routes this to handlePersonaUpdate.
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                type          : 'voice_persona_assigned',
                sender_id     : 'persona-a',
                timestamp     : '2026-05-19T15:01:00.000Z',
                voice_persona : {
                    name     : 'Tiberius',
                    voice_id : 'vid_42',
                    icon     : '🌑',
                    color    : '#3F51B5',
                    borrowed : false,
                },
            },
        },
        source : 'phase6c-a-smoke',
        ts     : Date.now(),
    });
    return true;
}
"""

_SEED_BORROWED_PERSONA_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                id_hash   : 'n-persona-borrowed',
                message   : 'borrowed-persona sender',
                sender_id : 'persona-borrowed',
                timestamp : '2026-05-19T15:00:00.000Z',
                type      : 'task',
            },
        },
        source : 'phase6c-a-smoke',
        ts     : Date.now(),
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : {
            notification : {
                type          : 'voice_persona_assigned',
                sender_id     : 'persona-borrowed',
                timestamp     : '2026-05-19T15:01:00.000Z',
                voice_persona : {
                    name     : 'Maria',
                    voice_id : 'vid_99',
                    icon     : '🌸',
                    color    : '#A040A0',
                    borrowed : true,
                },
            },
        },
        source : 'phase6c-a-smoke',
        ts     : Date.now(),
    });
    return true;
}
"""


def test_a10_chip_renders_as_sender_persona_badge_button():
    """AC-A10 #1: persona-badge chip in sender card header is a `<button>`
    with `popovertarget` matching the popover id (chip rename per Step A1)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            page.wait_for_selector( '.sender-card[data-sender-id="persona-a"] .sender-persona-badge', timeout=2000 )
            badge = page.locator( '.sender-card[data-sender-id="persona-a"] .sender-persona-badge' )
            assert badge.evaluate( "el => el.tagName.toLowerCase()" ) == "button"
            assert badge.get_attribute( "popovertarget" ) == "persona-popover-persona-a"
        finally:
            browser.close()


def test_a10_popover_opens_on_chip_click():
    """AC-A10 #2: clicking the persona-badge button opens the popover
    (Popover API declarative trigger via popovertarget)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            page.wait_for_selector( '#persona-modal-portal #persona-popover-persona-a', state="attached", timeout=2000 )
            popover = page.locator( '#persona-popover-persona-a' )
            # Initially hidden (popover state closed).
            assert popover.evaluate( "el => el.matches(':popover-open')" ) is False
            page.locator( '.sender-card[data-sender-id="persona-a"] .sender-persona-badge' ).click()
            page.wait_for_function(
                "() => document.querySelector('#persona-popover-persona-a').matches(':popover-open')",
                timeout=2000,
            )
        finally:
            browser.close()


def test_a10_popover_closes_on_x_button():
    """AC-A10 #3: clicking the × close button hides the popover via the
    declarative `popovertargetaction='hide'`."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            page.wait_for_selector( '#persona-popover-persona-a', state="attached", timeout=2000 )
            page.locator( '.sender-card[data-sender-id="persona-a"] .sender-persona-badge' ).click()
            page.wait_for_function(
                "() => document.querySelector('#persona-popover-persona-a').matches(':popover-open')",
                timeout=2000,
            )
            page.locator( '#persona-popover-persona-a .persona-popover-close' ).click()
            page.wait_for_function(
                "() => !document.querySelector('#persona-popover-persona-a').matches(':popover-open')",
                timeout=2000,
            )
        finally:
            browser.close()


def test_a10_popover_closes_on_escape_key():
    """AC-A10 #4: ESC closes the popover (Popover API light-dismiss)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            page.wait_for_selector( '#persona-popover-persona-a', state="attached", timeout=2000 )
            page.locator( '.sender-card[data-sender-id="persona-a"] .sender-persona-badge' ).click()
            page.wait_for_function(
                "() => document.querySelector('#persona-popover-persona-a').matches(':popover-open')",
                timeout=2000,
            )
            page.keyboard.press( "Escape" )
            page.wait_for_function(
                "() => !document.querySelector('#persona-popover-persona-a').matches(':popover-open')",
                timeout=2000,
            )
        finally:
            browser.close()


def test_a10_only_one_popover_per_sender():
    """AC-A10 #5: PersonaModalRenderer creates exactly one popover per sender,
    not duplicates on repeated persona_assigned events (storm-safety)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            # Seed once, then re-emit assignment 5 times. Should still be 1 popover.
            page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            page.wait_for_selector( '#persona-popover-persona-a', state="attached", timeout=2000 )
            for _ in range( 5 ):
                page.evaluate( _SEED_SENDER_WITH_PERSONA_JS )
            count = page.locator( '#persona-modal-portal > [id^="persona-popover-"]' ).count()
            assert count == 1, f"expected 1 popover per sender, got {count}"
        finally:
            browser.close()


def test_a10_borrowed_label_visible_for_borrowed_persona():
    """AC-A10 #6: when persona is borrowed, the popover's borrowed badge is
    visible (not `hidden`)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_BORROWED_PERSONA_JS )
            page.wait_for_selector( '#persona-popover-persona-borrowed', state="attached", timeout=2000 )
            page.locator( '.sender-card[data-sender-id="persona-borrowed"] .sender-persona-badge' ).click()
            page.wait_for_function(
                "() => document.querySelector('#persona-popover-persona-borrowed').matches(':popover-open')",
                timeout=2000,
            )
            borrowed_el = page.locator( '#persona-popover-persona-borrowed .persona-popover-borrowed' )
            assert borrowed_el.evaluate( "el => el.hasAttribute('hidden')" ) is False
        finally:
            browser.close()


# ===========================================================================
# AC-D9 : CSS scope-leak canary (layer-3) — disabling conversation-mode-pin.css
#   produces ZERO body-style drift on canary axes. Mirrors Phase 6b AC10d.
# ===========================================================================

# ===========================================================================
# AC-B15 : hard-verification grep-gate — D-CSS has ZERO `@keyframes focus-flash`
#   declarations; B-CSS is SSOT. This gate fires at code-write time and is
#   re-verified here at smoke-test time as a regression check against future
#   refactors that might accidentally introduce the keyframe into D-CSS.
# ===========================================================================

def test_ac_b15_grep_gate_d_css_has_zero_keyframes_focus_flash():
    """AC-B15: `conversation-mode-pin.css` must have ZERO `@keyframes
    focus-flash` declarations. B-CSS (`focus-tray.css`) owns this keyframe
    as SSOT. Mechanical grep guards against the contract regressing during
    future Phase 6c refactors."""
    import subprocess
    d_css = "src/fastapi_app/static/css/multiplexer/conversation-mode-pin.css"
    b_css = "src/fastapi_app/static/css/multiplexer/focus-tray.css"

    # D-CSS: zero occurrences of "@keyframes focus-flash".
    d_result = subprocess.run(
        [ "grep", "-c", "@keyframes focus-flash", d_css ],
        capture_output=True, text=True
    )
    d_count = int( d_result.stdout.strip() or "0" )
    assert d_count == 0, (
        f"AC-B15 violation: D-CSS ({d_css}) has {d_count} @keyframes focus-flash declarations; expected 0. "
        f"B-CSS ({b_css}) is the single source of truth."
    )

    # B-CSS: at least one declaration (positive verification of the SSOT).
    b_result = subprocess.run(
        [ "grep", "-c", "@keyframes focus-flash", b_css ],
        capture_output=True, text=True
    )
    b_count = int( b_result.stdout.strip() or "0" )
    assert b_count >= 1, (
        f"AC-B15 contract: B-CSS ({b_css}) must own @keyframes focus-flash; found {b_count} declarations."
    )


# ===========================================================================
# AC-B10 #1-#8 : Section B functional smoke (focus-mode toggle + focus-tray)
# ===========================================================================

def test_b10_toggle_exists_and_enabled_when_pin_present():
    """AC-B10 #1: #focus-mode-toggle is in the DOM + enabled when a pinned
    sender exists (the renderer lifts hidden + data-phase6-pending; the
    OSQ-B-3 disabled gate is off when a pin is active)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([hidden])', timeout=2000 )
            toggle = page.locator( '#focus-mode-toggle' )
            assert toggle.evaluate( "el => el.disabled" ) is False
            assert toggle.evaluate( "el => el.getAttribute('aria-pressed')" ) == "false"
            assert toggle.text_content() == "Focus mode OFF"
        finally:
            browser.close()


def test_b10_toggle_disabled_with_tooltip_when_no_pin():
    """AC-B10 #2: with no pinned sender, the toggle is disabled and carries
    a tooltip explaining the requirement (OSQ-B-3 ratification)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            # No conversation_mode_active sender — toggle stays disabled.
            page.wait_for_selector( '#focus-mode-toggle:not([hidden])', timeout=2000 )
            toggle = page.locator( '#focus-mode-toggle' )
            assert toggle.evaluate( "el => el.disabled" ) is True
            assert "conversation" in (toggle.get_attribute( 'title' ) or "").lower()
        finally:
            browser.close()


def test_b10_toggle_click_flips_focus_mode_on():
    """AC-B10 #3: clicking the toggle with a pinned sender flips
    aria-pressed=true and textContent to 'Focus mode ON'."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([hidden]):not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            toggle = page.locator( '#focus-mode-toggle' )
            assert toggle.evaluate( "el => el.getAttribute('aria-pressed')" ) == "true"
            assert toggle.text_content() == "Focus mode ON"
        finally:
            browser.close()


def test_b10_focus_mode_hides_non_pinned_cards_via_data_attribute():
    """AC-B10 #4: focus mode ON applies data-focus-hidden=true to non-pinned
    sender cards; B-CSS's `display: none` rule hides them via offsetParent."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            # state="attached" — the card has display:none via data-focus-hidden,
            # so the default state="visible" would time out even though the
            # attribute IS present.
            page.wait_for_selector(
                '.sender-card[data-sender-id="sess-b"][data-focus-hidden="true"]',
                state="attached", timeout=2000,
            )
            # display:none ⇒ offsetParent is null in browsers.
            b_visible = page.evaluate(
                """() => {
                    const el = document.querySelector('.sender-card[data-sender-id="sess-b"]');
                    return el && el.offsetParent !== null;
                }"""
            )
            assert b_visible is False, "B-CSS display:none should hide non-pinned card"
        finally:
            browser.close()


def test_b10_focus_tray_populated_with_hidden_senders():
    """AC-B10 #5: focus mode ON populates #focus-tray with a button per
    hidden sender."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            page.wait_for_selector( '#focus-tray .focus-tray-row[data-sender-id="sess-b"]', timeout=2000 )
            assert page.locator( '#focus-tray .focus-tray-row' ).count() == 1
        finally:
            browser.close()


def test_b10_tray_row_click_exits_focus_mode():
    """AC-B10 #6: clicking a focus-tray row exits focus mode (OSQ-B-2)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            page.wait_for_selector( '#focus-tray .focus-tray-row[data-sender-id="sess-b"]', timeout=2000 )
            page.locator( '#focus-tray .focus-tray-row[data-sender-id="sess-b"]' ).click()
            # Wait for focus mode to fully exit.
            page.wait_for_function(
                "() => document.querySelector('#focus-mode-toggle').getAttribute('aria-pressed') === 'false'",
                timeout=2000,
            )
            # data-focus-hidden cleared.
            hidden = page.locator( '.sender-card[data-sender-id="sess-b"]' ).get_attribute( 'data-focus-hidden' )
            assert hidden is None
        finally:
            browser.close()


def test_b10_pin_move_while_focus_mode_on_transfers_hidden():
    """AC-B10 #7: when pin moves while focus mode is ON, data-focus-hidden
    re-applies to the new non-pinned set per F-Arnold-B-Stage2-4."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            page.wait_for_selector( '.sender-card[data-sender-id="sess-b"][data-focus-hidden="true"]', state="attached", timeout=2000 )

            # Pin moves to B.
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-b" )
            page.wait_for_selector( '.sender-card[data-sender-id="sess-a"][data-focus-hidden="true"]', state="attached", timeout=2000 )
            # B is no longer focus-hidden.
            b_hidden = page.locator( '.sender-card[data-sender-id="sess-b"]' ).get_attribute( 'data-focus-hidden' )
            assert b_hidden is None
        finally:
            browser.close()


def test_b10_pin_disappears_disables_toggle_holds_focus_mode():
    """AC-B10 #8: deactivating the pin while focus mode is ON disables the
    toggle (visual cue) but HOLDS focus mode state per the dual-emission
    transient guard — the SenderStore pin-MOVE always passes through a
    momentary no-pin state, and force-exiting on that transient would lose
    the user's focus-mode state every time the pin swaps. The next pin
    activation re-applies focus-hidden transparently; a deliberate user
    toggle click is required to exit."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, _ctx, page = _new_page( pw )
        try:
            page.evaluate( _SEED_TWO_SENDERS_JS )
            page.evaluate( _ACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
            page.locator( '#focus-mode-toggle' ).click()
            page.wait_for_selector( '.sender-card[data-sender-id="sess-b"][data-focus-hidden="true"]', state="attached", timeout=2000 )

            page.evaluate( _DEACTIVATE_CONV_MODE_JS, "sess-a" )
            page.wait_for_function(
                "() => document.querySelector('#focus-mode-toggle').disabled === true",
                timeout=2000,
            )
            toggle = page.locator( '#focus-mode-toggle' )
            # focus mode HELD — aria-pressed stays "true" per the transient
            # guard. data-focus-hidden state survives on B.
            assert toggle.evaluate( "el => el.getAttribute('aria-pressed')" ) == "true"
            assert page.locator( '.sender-card[data-sender-id="sess-b"]' ).get_attribute( "data-focus-hidden" ) == "true"
        finally:
            browser.close()


def test_css_canary_no_body_drift_from_conversation_mode_pin_css():
    """AC-D9 layer-3 — proves conversation-mode-pin.css contributes ZERO
    body-style drift. The stylelint global-selector ban (layer-2) provides
    static enforcement; this runtime check provides the dynamic guarantee."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch( headless=True, args=[ "--autoplay-policy=no-user-gesture-required" ] )
        try:
            context = browser.new_context()
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
                        if ( href.endsWith( '/conversation-mode-pin.css' ) ) {
                            sheet.disabled = true;
                            toggled += 1;
                        }
                    }
                    if ( toggled !== 1 ) {
                        throw new Error( 'Expected 1 Phase 6c Node D stylesheet; toggled=' + toggled );
                    }
                    const s = getComputedStyle( document.body );
                    const out = {};
                    for ( const k of axes ) out[ k ] = s[ k ];
                    return out;
                }""",
                CANARY_AXES,
            )

            assert cs_with == cs_without, (
                f"conversation-mode-pin.css contributed body-style drift on canary axes: "
                f"WITH={cs_with} WITHOUT={cs_without}"
            )
        finally:
            browser.close()
