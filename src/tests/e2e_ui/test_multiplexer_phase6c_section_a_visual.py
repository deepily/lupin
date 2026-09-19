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
    closed (default) state — button with icon.

    WHAT THIS SNAPSHOT DOES NOT GUARD (row f0e00f01, measured by pocholo 📣 and
    re-measured here): it used to say "no popover visible". No capture in this
    test ever guarded that, under EITHER target. The popover's parent is
    `#persona-modal-portal` (multiplexer.html:295), which sits outside
    `#notifications-pane` (lines 175-209) as well as outside
    `#sender-cards-container` — the pane has exactly three children:
    broadcast-card-mount, cc-session-strip, sender-cards-container. So the
    narrowing neither caused nor exposed this; the sentence was inaccurate from
    the day it was written.

    The chip's closed state IS guarded: the badge button lives inside the captured
    container. Popover behaviour is guarded by the two tests below, which locate
    `#persona-popover-…` directly.
    """
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

    # Font-load barrier (task 006cb393 — emoji glyph-render race): await
    # document.fonts.ready + 2 RAFs so the persona/badge NotoColorEmoji glyphs are
    # loaded before capture. networkidle does NOT gate fonts. See
    # test_multiplexer_task_editing.py:316-318. Pure load barrier — comparator untouched.
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    # Row f0e00f01: snapshot #sender-cards-container, NOT #notifications-pane.
    # Same unstable-baseline-by-construction defect ts-127620e1 fixed for the two
    # popover tests below, arriving here by a different route. #notifications-pane
    # holds #broadcast-card-mount, and the commons "Recent Activity" feed is nested
    # inside that mount's rendered subtree (boot.ts:620). That feed is LIVE fleet
    # traffic and is never reset: clean_test_db truncates six auth/job tables and
    # never touches commons, and /api/commons/broadcast-history reads file-backed
    # topics plus the voice-persona bridge dir, capped at 200 entries. Measured
    # 2026-09-15: it returns exactly 200 — its ceiling — spanning ONE DAY, and the
    # pane read 960x804 of which the feed was 960x531 (66%) while this container,
    # the only surface this test asserts, was 960x119 (15%).
    # So the baseline's height tracked unrelated fleet churn → the exact
    # "ValueError: Image sizes do not match" ts-127620e1 named. Rebaselining would
    # re-arm it; narrowing is the fix that already works for the siblings.
    # snap_y: moves the container to an integer y with a spacer before capture,
    # so text anti-aliasing does not follow the fraction the content above adds up
    # to (see snap_to_integer_y in conftest.py). Its parent, #notifications-pane, is
    # a block, which is where a spacer works: measured landing on 915 from 914.09
    # and from 914.5 (Chloé 🗼, 2026-09-18).
    pane = page.locator( '#sender-cards-container' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_a_chip.png", snap_y=True )
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
    # Font-load barrier (task 006cb393 — emoji glyph-render race): await
    # document.fonts.ready + 2 RAFs so the persona/badge NotoColorEmoji glyphs are
    # loaded before capture. See test_multiplexer_task_editing.py:316-318.
    #
    # OPAQUE BACKGROUND — the same corner bleed row 856c7c96 fixed for the borrowed
    # sibling below, whose comment carries the measurement. The popover's rounded
    # corner is transparent, so its corner pixels are the shadow blended over
    # whatever page sits behind it; this capture was reported failing 5 px in its
    # bottom-right corner (Mr. Radio 🦉, 2026-09-18). Painting the top-layer `::backdrop`
    # solid fixes what the corner shows without touching the popover itself.
    page.add_style_tag( content="#persona-popover-phase6c-a-visual::backdrop { background: #fff; }" )
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    popover = page.locator( '#persona-popover-phase6c-a-visual' )
    assert_snapshot( popover, name="multiplexer_phase6c_section_a_popover_open.png" )
    print( "✓ multiplexer_phase6c_section_a_popover_open: snapshot compared" )


def test_multiplexer_phase6c_section_a_popover_borrowed_visual(
    request, clean_test_db, assert_snapshot_content_shift_tolerant, logged_in_page,
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
    # Font-load barrier (task 006cb393 — emoji glyph-render race): await
    # document.fonts.ready + 2 RAFs so the persona/badge NotoColorEmoji glyphs are
    # loaded before capture. See test_multiplexer_task_editing.py:316-318.
    #
    # OPAQUE BACKGROUND (row 856c7c96). The popover's 8px rounded corner is
    # transparent, so the capture's corner pixels are its shadow blended over
    # whatever page happens to sit behind it — and that moved between runs, failing
    # 8–11 px in the bottom-right corner only. A native popover renders in the top
    # layer with a `::backdrop` directly beneath it, so painting that backdrop
    # solid fixes what the corner shows without touching the popover itself.
    # Measured in plain headless Chromium with this stylesheet (Rio ⚡, 2026-09-18):
    # changing the page behind the corner moved 27 px in its 8x8 corner, which every
    # tolerant comparator refused; with the backdrop painted, 0 px.
    page.add_style_tag( content="#persona-popover-phase6c-a-borrowed::backdrop { background: #fff; }" )
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    popover = page.locator( '#persona-popover-phase6c-a-borrowed' )
    assert_snapshot_content_shift_tolerant( popover, name="multiplexer_phase6c_section_a_popover_borrowed.png" )
    print( "✓ multiplexer_phase6c_section_a_popover_borrowed: snapshot compared" )
