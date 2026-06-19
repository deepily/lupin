"""
Multiplexer Phase 6c Node A — visual regression baseline capture.

Per AC-A12 + AC-A13 (execution plan §3.A.7): baseline submission via
`/api/test-suite/submit` with `--update-snapshots -k multiplexer_phase6c_section_a`
captures snapshots; subsequent regression run (without `--update-snapshots`)
must report 1 passed.

3 snapshots: chip-only sender card, popover-open with non-borrowed persona,
popover-open with borrowed persona (verifies the borrowed badge surface).
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


_INJECT_PERSONA_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_a_visual_a',
            message   : 'message from persona A',
            sender_id : 'phase6c-a-visual',
            timestamp : '2026-05-19T15:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-a-visual',
        ts     : 1779235200000,
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type          : 'voice_persona_assigned',
            sender_id     : 'phase6c-a-visual',
            timestamp     : '2026-05-19T15:01:00.000Z',
            voice_persona : {
                name     : 'Tiberius',
                voice_id : 'vid_42',
                icon     : '🌑',
                color    : '#3F51B5',
                borrowed : false,
            },
        } },
        source : 'phase6c-a-visual',
        ts     : 1779235260000,
    });
    return true;
}
"""

_INJECT_BORROWED_PERSONA_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    const bus = hook.eventBus;
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_a_borrowed',
            message   : 'borrowed persona sender',
            sender_id : 'phase6c-a-borrowed',
            timestamp : '2026-05-19T15:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-a-visual',
        ts     : 1779235200000,
    });
    bus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            type          : 'voice_persona_assigned',
            sender_id     : 'phase6c-a-borrowed',
            timestamp     : '2026-05-19T15:01:00.000Z',
            voice_persona : {
                name     : 'Maria',
                voice_id : 'vid_99',
                icon     : '🌸',
                color    : '#A040A0',
                borrowed : true,
            },
        } },
        source : 'phase6c-a-visual',
        ts     : 1779235260000,
    });
    return true;
}
"""

_STABILIZE_LAST_ACTIVITY_JS = """
() => {
    document.querySelectorAll('.sender-last-activity').forEach(el => { el.textContent = 'Last: 12:00'; });
    return true;
}
"""


def test_multiplexer_phase6c_section_a_chip_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-A12 snapshot #1: sender card showing the persona-badge chip in its
    closed (default) state — button with icon, no popover visible."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_PERSONA_JS )
    page.wait_for_selector( '.sender-card[data-sender-id="phase6c-a-visual"] .sender-persona-badge', timeout=2000 )
    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    time.sleep( 0.3 )

    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_a_chip.png" )
    print( "✓ multiplexer_phase6c_section_a_chip: snapshot compared" )


def test_multiplexer_phase6c_section_a_popover_open_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-A12 snapshot #2: popover OPEN for a non-borrowed persona — accent
    strip, name+icon row, voice_id row, no borrowed badge."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_PERSONA_JS )
    page.wait_for_selector( '#persona-popover-phase6c-a-visual', state="attached", timeout=2000 )
    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    page.locator( '.sender-card[data-sender-id="phase6c-a-visual"] .sender-persona-badge' ).click()
    page.wait_for_function(
        "() => document.querySelector('#persona-popover-phase6c-a-visual').matches(':popover-open')",
        timeout=2000,
    )
    time.sleep( 0.3 )

    # ts-127620e1 fix: snapshot the popover element itself, NOT `main.container`.
    # `main.container` includes the live "My Recent Activity" + "My Fleet Status"
    # regions, whose height grows with fleet churn between baseline capture and run
    # (unstable-baseline-by-construction → ValueError: Image sizes do not match).
    # The popover holds only the deterministic seeded surface this test asserts
    # (accent strip, name+icon row, voice_id row, no borrowed badge).
    popover = page.locator( '#persona-popover-phase6c-a-visual' )
    assert_snapshot( popover, name="multiplexer_phase6c_section_a_popover_open.png" )
    print( "✓ multiplexer_phase6c_section_a_popover_open: snapshot compared" )


def test_multiplexer_phase6c_section_a_popover_borrowed_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-A12 snapshot #3: popover OPEN for a borrowed persona — borrowed
    badge surfaces (no `hidden` attribute), distinguishing visually from
    snapshot #2."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )

    page.evaluate( _INJECT_BORROWED_PERSONA_JS )
    page.wait_for_selector( '#persona-popover-phase6c-a-borrowed', state="attached", timeout=2000 )
    page.evaluate( _STABILIZE_LAST_ACTIVITY_JS )
    page.locator( '.sender-card[data-sender-id="phase6c-a-borrowed"] .sender-persona-badge' ).click()
    page.wait_for_function(
        "() => document.querySelector('#persona-popover-phase6c-a-borrowed').matches(':popover-open')",
        timeout=2000,
    )
    time.sleep( 0.3 )

    # ts-127620e1 fix: snapshot the popover element itself, NOT `main.container`
    # (same unstable-baseline-by-construction reason as popover_open above). The
    # borrowed-badge surface lives entirely inside the popover element.
    popover = page.locator( '#persona-popover-phase6c-a-borrowed' )
    assert_snapshot( popover, name="multiplexer_phase6c_section_a_popover_borrowed.png" )
    print( "✓ multiplexer_phase6c_section_a_popover_borrowed: snapshot compared" )
