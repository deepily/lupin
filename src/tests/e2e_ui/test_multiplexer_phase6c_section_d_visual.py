"""
Multiplexer Phase 6c Node D — visual regression baseline capture.

Per AC-D13 + AC-D14 ratification (execution plan §3.D.7):
    - AC-D13: submission via `POST /api/test-suite/submit` with
      `--update-snapshots -k multiplexer_phase6c_section_d` returns HTTP 200 +
      valid `submission_id`. Standing permission for baseline capture
      (per `feedback_test_server_free_for_baseline_capture`) — pair with
      `auto_fix_on_failure: False` per `feedback_baseline_capture_disable_tfe`.
    - AC-D14: post-baseline regression run (no `--update-snapshots`) reports
      "1 passed, 0 errors" against the captured snapshots.

Per `feedback_tests_parameterize_base_url`: BASE_URL is parameterized via the
e2e_ui conftest standard (`LUPIN_TEST_BASE_URL` env var; default
`http://localhost:8000`).

**Path δ scope** (Rick 2026-05-19): mic-monopoly indicator was DEFERRED. The
3 snapshots below capture pin-glow + pin-move semantics; the mic-monopoly
overlay is NOT exercised. See TODO.md "Phase 6c follow-on: mic-monopoly
indicator" for when those snapshots get added.

**Path III bridge** (Tiberius 2026-05-19): fixtures emit
`conversation_mode_changed` notification type with `payload.active`; the
SenderStore reducer's bridge also accepts `speakerphone_changed` /
`payload.on` — see `sender_store_conversation_mode.test.ts` for that
coverage at unit-test tier.

**Venue**: `:8000` monopolize-mode. Submit via `/schedule-tests` skill, NOT
via ad-hoc curl. The `-k multiplexer_phase6c_section_d` filter ensures only
this file's 3 tests run during the scheduled slot.

3 snapshots captured:
    1. baseline (no conv-mode active) — `#sender-cards-container` layout
    2. pinned (sender A in conv-mode) — pin-glow + sort hoists A to top
    3. pin-moved (B activated after A) — pin moved to B; A demoted to position 1
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
# Fixture-injection JS — two senders with deterministic timestamps.
#
# B's notification has a later timestamp so under the default sort (no pin),
# B renders first. Under the Phase 6c sort with A pinned, A hoists above B.
# ---------------------------------------------------------------------------

_INJECT_TWO_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_d_visual_a',
            message   : 'message from sender A',
            sender_id : 'phase6c-d-visual-a',
            timestamp : '2026-05-19T15:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-d-visual',
        ts     : 1779235200000,
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_d_visual_b',
            message   : 'message from sender B',
            sender_id : 'phase6c-d-visual-b',
            timestamp : '2026-05-19T16:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-d-visual',
        ts     : 1779238800000,
    });
    return true;
}
"""

_ACTIVATE_CONV_MODE_A_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type      : 'conversation_mode_changed',
            sender_id : 'phase6c-d-visual-a',
            timestamp : '2026-05-19T15:30:00.000Z',
            payload   : { session_id: 'phase6c-d-visual-a', active: true },
        } },
        source : 'phase6c-d-visual',
        ts     : 1779237000000,
    });
    return true;
}
"""

_ACTIVATE_CONV_MODE_B_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type      : 'conversation_mode_changed',
            sender_id : 'phase6c-d-visual-b',
            timestamp : '2026-05-19T16:30:00.000Z',
            payload   : { session_id: 'phase6c-d-visual-b', active: true },
        } },
        source : 'phase6c-d-visual',
        ts     : 1779240600000,
    });
    return true;
}
"""

# Stabilize the live "Last: HH:MM" text in each sender card to a fixed
# placeholder. The renderer produces real wall-clock text otherwise, which
# would drift between runs.
_STABILIZE_LAST_ACTIVITY_JS = """
() => {
    document.querySelectorAll( '.sender-last-activity' ).forEach( el => {
        el.textContent = 'Last: 12:00';
    } );
    return true;
}
"""


# ---------------------------------------------------------------------------
# Snapshot 1 — baseline (no conv-mode active)
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_d_baseline_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-D13 snapshot #1: two sender cards rendered without conv-mode pin.
    Establishes the no-pin baseline against which #2 + #3 will diff."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_TWO_SENDERS_JS )
    page.wait_for_selector( '.sender-card[data-sender-id="phase6c-d-visual-a"]', timeout=2000 )
    page.wait_for_selector( '.sender-card[data-sender-id="phase6c-d-visual-b"]', timeout=2000 )

    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    time.sleep( 0.3 )

    container = page.locator( '#sender-cards-container' )
    assert_snapshot( container, name="multiplexer_phase6c_section_d_baseline.png" )
    print( "✓ multiplexer_phase6c_section_d_baseline: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Snapshot 2 — sender A pinned (pin-glow visible; A hoisted to top despite
# B having newer activity timestamp)
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_d_pinned_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-D13 snapshot #2: sender A in conversation mode. Pin-glow rule from
    conversation-mode-pin.css applies via `[data-pinned-conv-mode="true"]`;
    Phase 6c sort hoists A above the more-recently-active B."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_TWO_SENDERS_JS )
    page.wait_for_selector( '.sender-card[data-sender-id="phase6c-d-visual-a"]', timeout=2000 )

    page.evaluate( _ACTIVATE_CONV_MODE_A_JS )
    page.wait_for_selector(
        '.sender-card[data-sender-id="phase6c-d-visual-a"][data-pinned-conv-mode="true"]',
        timeout=2000,
    )

    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    # 300ms exceeds the box-shadow transition (250ms ease-out) so the glow is
    # at steady-state when the snapshot fires.
    time.sleep( 0.3 )

    container = page.locator( '#sender-cards-container' )
    assert_snapshot( container, name="multiplexer_phase6c_section_d_pinned.png" )
    print( "✓ multiplexer_phase6c_section_d_pinned: visual snapshot compared" )


# ---------------------------------------------------------------------------
# Snapshot 3 — pin moved from A to B (focus-flash attribute is set on B but
# the @keyframes referenced by D-CSS lives in B-CSS which has not shipped
# yet — until then the animation reference resolves to no-op; the snapshot
# captures the dual-emission single-pin steady-state with B pinned)
# ---------------------------------------------------------------------------

def test_multiplexer_phase6c_section_d_pin_moved_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-D13 snapshot #3: pin moves A → B. Per single-pin invariant only
    B carries `data-pinned-conv-mode="true"` now; B also carries
    `data-focus-flash="true"` for ~1.2s post-move (until the cascade B-CSS
    @keyframes lands, no visible animation runs — the attribute presence is
    the testable surface). Snapshot is taken WITHIN the 1.2s flash window
    so the focus-flash attribute is in DOM at capture time."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_TWO_SENDERS_JS )
    page.evaluate( _ACTIVATE_CONV_MODE_A_JS )
    page.wait_for_selector(
        '.sender-card[data-sender-id="phase6c-d-visual-a"][data-pinned-conv-mode="true"]',
        timeout=2000,
    )

    page.evaluate( _ACTIVATE_CONV_MODE_B_JS )
    page.wait_for_selector(
        '.sender-card[data-sender-id="phase6c-d-visual-b"][data-pinned-conv-mode="true"]',
        timeout=2000,
    )
    # Confirm focus-flash IS set on B at this moment (capture-time invariant
    # for the snapshot's DOM state).
    page.wait_for_selector(
        '.sender-card[data-sender-id="phase6c-d-visual-b"][data-focus-flash="true"]',
        timeout=2000,
    )

    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    # 300ms: enough for layout/transition to settle, well under the 1.2s
    # flash window so the focus-flash attribute survives until capture.
    time.sleep( 0.3 )

    container = page.locator( '#sender-cards-container' )
    assert_snapshot( container, name="multiplexer_phase6c_section_d_pin_moved.png" )
    print( "✓ multiplexer_phase6c_section_d_pin_moved: visual snapshot compared" )
