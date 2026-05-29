"""
Multiplexer Phase 6c Node B — visual regression baseline capture.

Per AC-B13 + AC-B14 (execution plan §3.B.7):
    - AC-B13: submission via `POST /api/test-suite/submit` with
      `--update-snapshots -k multiplexer_phase6c_section_b` returns HTTP 200
      and produces baseline PNGs. Standing permission per
      `feedback_test_server_free_for_baseline_capture`; pair with
      `auto_fix_on_failure: False` per `feedback_baseline_capture_disable_tfe`.
    - AC-B14: post-baseline regression run (no `--update-snapshots`) reports
      "1 passed, 0 errors" against the captured snapshots.

**Path δ scope** (Rick 2026-05-19): mic-monopoly indicator deferred — these
snapshots capture pin-glow + focus-mode hide / tray-populate semantics only.

**Path III bridge** (Tiberius 2026-05-19): fixtures emit
`conversation_mode_changed` with `payload.active`; renderer accepts either
type-name + field-name via Path III bridge logic (covered at unit-test tier).

**Venue**: `:8000` monopolize-mode. Submit via `/schedule-tests` skill, NOT
ad-hoc curl. The `-k multiplexer_phase6c_section_b` filter ensures only
this file's 3 tests run during the scheduled slot.

3 snapshots captured:
    1. baseline (focus mode OFF, no conv-mode pin) — toggle visible+disabled,
       tray hidden, no cards have data-focus-hidden
    2. focus mode ON, pin on sess-a — toggle aria-pressed=true, B card
       hidden via display:none, tray populated with B's row
    3. focus mode ON with two non-pinned senders — toggle aria-pressed=true,
       both B and C hidden, tray populated with 2 rows
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Fixture-injection JS — deterministic timestamps for byte-identical wire
# payloads across runs.
# ---------------------------------------------------------------------------

_INJECT_TWO_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_b_visual_a',
            message   : 'message from sender A',
            sender_id : 'phase6c-b-visual-a',
            timestamp : '2026-05-19T15:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-b-visual',
        ts     : 1779235200000,
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_b_visual_b',
            message   : 'message from sender B',
            sender_id : 'phase6c-b-visual-b',
            timestamp : '2026-05-19T16:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-b-visual',
        ts     : 1779238800000,
    });
    return true;
}
"""

_INJECT_THREE_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    const seeds = [
        { id: 'phase6c-b-visual-a', ts: '2026-05-19T15:00:00.000Z', msg: 'sender A' },
        { id: 'phase6c-b-visual-b', ts: '2026-05-19T16:00:00.000Z', msg: 'sender B' },
        { id: 'phase6c-b-visual-c', ts: '2026-05-19T17:00:00.000Z', msg: 'sender C' },
    ];
    for ( const s of seeds ) {
        bus.emit({
            type    : 'notification_queue_update',
            payload : { notification: {
                id_hash   : 'n-' + s.id,
                message   : s.msg,
                sender_id : s.id,
                timestamp : s.ts,
                type      : 'task',
            } },
            source : 'phase6c-b-visual',
            ts     : 1779235200000,
        });
    }
    return true;
}
"""

_ACTIVATE_CONV_MODE_A_JS = """
() => {
    window.__multiplexerTestHook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type      : 'conversation_mode_changed',
            sender_id : 'phase6c-b-visual-a',
            timestamp : '2026-05-19T15:30:00.000Z',
            payload   : { session_id: 'phase6c-b-visual-a', active: true },
        } },
        source : 'phase6c-b-visual',
        ts     : 1779237000000,
    });
    return true;
}
"""

# Stabilize the live "Last: HH:MM" text in sender cards to a fixed placeholder
# (the renderer's wall-clock text otherwise drifts between runs).
_STABILIZE_LAST_ACTIVITY_JS = """
() => {
    document.querySelectorAll( '.sender-last-activity' ).forEach( el => {
        el.textContent = 'Last: 12:00';
    } );
    return true;
}
"""


# ---------------------------------------------------------------------------
# Snapshot 1 — baseline: focus mode OFF, no conv-mode pin
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_b_baseline_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-B13 snapshot #1: notifications-pane with the focus-mode toggle
    visible and disabled (no pin yet). The tray is hidden."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_TWO_SENDERS_JS )
    page.wait_for_selector( '#focus-mode-toggle:not([hidden])', timeout=2000 )
    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    time.sleep( 0.3 )

    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_b_baseline.png" )
    print( "✓ multiplexer_phase6c_section_b_baseline: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Snapshot 2 — focus mode ON with one pinned + one hidden sender
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_b_focus_mode_on_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-B13 snapshot #2: focus mode ON. Sender A is pinned with the pin
    glow; sender B is hidden via display:none (and surfaced in the focus
    tray as a row)."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_TWO_SENDERS_JS )
    page.evaluate( _ACTIVATE_CONV_MODE_A_JS )
    page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
    page.locator( '#focus-mode-toggle' ).click()
    page.wait_for_selector(
        '.sender-card[data-sender-id="phase6c-b-visual-b"][data-focus-hidden="true"]',
        state="attached", timeout=2000,
    )
    page.wait_for_selector( '#focus-tray .focus-tray-row[data-sender-id="phase6c-b-visual-b"]', timeout=2000 )

    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    time.sleep( 0.3 )

    # Capture the full <main> so both the notifications-pane (with pinned A)
    # and the focus-tray (with B's row) appear in the snapshot.
    main = page.locator( 'main.container' )
    assert_snapshot( main, name="multiplexer_phase6c_section_b_focus_mode_on.png" )
    print( "✓ multiplexer_phase6c_section_b_focus_mode_on: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Snapshot 3 — focus mode ON with multiple hidden senders
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_b_focus_tray_multiple_hidden_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-B13 snapshot #3: focus mode ON with two non-pinned senders hidden.
    The tray renders two rows. Verifies the tray's list layout at >1 row."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_THREE_SENDERS_JS )
    page.evaluate( _ACTIVATE_CONV_MODE_A_JS )
    page.wait_for_selector( '#focus-mode-toggle:not([disabled])', timeout=2000 )
    page.locator( '#focus-mode-toggle' ).click()
    # Wait for BOTH B and C to be focus-hidden + present in the tray.
    page.wait_for_selector( '#focus-tray .focus-tray-row[data-sender-id="phase6c-b-visual-b"]', timeout=2000 )
    page.wait_for_selector( '#focus-tray .focus-tray-row[data-sender-id="phase6c-b-visual-c"]', timeout=2000 )

    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    time.sleep( 0.3 )

    main = page.locator( 'main.container' )
    assert_snapshot( main, name="multiplexer_phase6c_section_b_focus_tray_multiple.png" )
    print( "✓ multiplexer_phase6c_section_b_focus_tray_multiple: visual snapshot compared" )
