"""
Multiplexer F5 lane — voice-input-row visual regression (MATCH-LEGACY rebuild).

Supersedes the Phase 6c Node C Record-button snapshots: the voice-input surface
is now the legacy inline `.cc-voice-input-row` (conv-mode + mic + text input +
send) rendered STATICALLY by senderCard.ts between the card header and
`.sender-card-dates`. The retired states (idle Record-only / ready_to_send
textarea+Re-record+Send) no longer exist — there is ONE persistent row.

2 snapshots: the row at rest (empty input); the row with a transcription in the
input (post-record). Both baselines are REGENERATED with this rebuild — submit
via `/api/test-suite/submit` with `--update-snapshots -k
multiplexer_phase6c_section_c` (standing baseline-regen perm), then the
regression run must report 2 passed.
"""

from __future__ import annotations

import time

from .conftest import BASE_URL


_INJECT_SENDER_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : 'phase6c_c_visual',
            message   : 'message from phase6c-c-visual',
            sender_id : 'phase6c-c-visual#abcd1234',
            timestamp : '2026-05-19T15:00:00.000Z',
            type      : 'task',
        } },
        source : 'phase6c-c-visual',
        ts     : 1779235200000,
    });
    return true;
}
"""

# Fill the PERSISTENT input directly (the legacy-faithful post-record surface) —
# no microphone access, no synthetic markup; the row is what senderCard.ts emits.
_FILL_INPUT_JS = """
() => {
    const input = document.querySelector('.cc-voice-input[data-session-hash="abcd1234"] .cc-session-msg-input');
    if ( !input ) throw new Error( "voice-input text field not found" );
    input.value = 'Hello from the test harness.';
    return true;
}
"""

_STABILIZE_JS = """
() => {
    document.querySelectorAll('.sender-last-activity').forEach(el => { el.textContent = 'Last: 12:00'; });
    return true;
}
"""


def test_multiplexer_phase6c_section_c_idle_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """Snapshot #1: the inline voice-input row at rest (conv-mode + mic + empty
    input + send), rendered statically by senderCard.ts between header and dates."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.evaluate( _INJECT_SENDER_JS )
    page.wait_for_selector( '.cc-voice-input[data-session-hash="abcd1234"] .cc-session-stt', timeout=2000 )
    page.evaluate( _STABILIZE_JS )
    time.sleep( 0.3 )

    # Font-load barrier (task 006cb393 — emoji glyph-render race): await
    # document.fonts.ready + 2 RAFs so the conv-mode/mic NotoColorEmoji glyphs are
    # loaded before capture. networkidle does NOT gate fonts. See
    # test_multiplexer_task_editing.py:316-318. Pure load barrier — comparator untouched.
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_c_idle.png" )
    print( "✓ multiplexer_phase6c_section_c_idle: snapshot compared" )


def test_multiplexer_phase6c_section_c_filled_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """Snapshot #2: the same row with a transcription in the persistent input
    (post-record). The input is filled directly — no microphone, no synthetic
    markup; the row structure is exactly what senderCard.ts renders."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.evaluate( _INJECT_SENDER_JS )
    page.wait_for_selector( '.cc-voice-input[data-session-hash="abcd1234"] .cc-session-msg-input', timeout=2000 )
    page.evaluate( _FILL_INPUT_JS )
    page.evaluate( _STABILIZE_JS )
    time.sleep( 0.3 )

    # Font-load barrier (task 006cb393 — emoji glyph-render race): await
    # document.fonts.ready + 2 RAFs so the conv-mode/mic NotoColorEmoji glyphs are
    # loaded before capture. See test_multiplexer_task_editing.py:316-318.
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_c_filled.png" )
    print( "✓ multiplexer_phase6c_section_c_filled: snapshot compared" )
