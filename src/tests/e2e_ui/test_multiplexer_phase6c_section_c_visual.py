"""
Multiplexer Phase 6c Node C — visual regression baseline capture.

Per AC-C12 + AC-C13 (execution plan §3.C.7): baseline submission via
`/api/test-suite/submit` with `--update-snapshots -k multiplexer_phase6c_section_c`
captures snapshots; subsequent regression run must report 1 passed.

2 snapshots: idle voice-input footer (Record button only); ready-to-send
state (textarea + Re-record + Send buttons populated via manual DOM
mutation since real recording flow requires microphone access).
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

_SIMULATE_READY_TO_SEND_JS = """
() => {
    const voiceInput = document.querySelector('.cc-voice-input[data-session-hash="abcd1234"]');
    if ( !voiceInput ) throw new Error( "voice-input footer not found" );
    voiceInput.replaceChildren();
    voiceInput.setAttribute('data-recorder-state', 'ready_to_send');
    const textarea = document.createElement('textarea');
    textarea.className = 'cc-voice-input-textarea';
    textarea.value = 'Hello from the test harness.';
    voiceInput.appendChild(textarea);
    const re = document.createElement('button');
    re.type = 'button';
    re.className = 'record-button';
    re.textContent = 'Re-record';
    voiceInput.appendChild(re);
    const send = document.createElement('button');
    send.type = 'button';
    send.className = 'send-button';
    send.textContent = 'Send';
    voiceInput.appendChild(send);
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
    """AC-C12 snapshot #1: sender card with the .cc-voice-input footer in
    idle state (Record button only)."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.evaluate( _INJECT_SENDER_JS )
    page.wait_for_selector( '.cc-voice-input[data-session-hash="abcd1234"] .record-button', timeout=2000 )
    page.evaluate( _STABILIZE_JS )
    time.sleep( 0.3 )

    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_c_idle.png" )
    print( "✓ multiplexer_phase6c_section_c_idle: snapshot compared" )


def test_multiplexer_phase6c_section_c_ready_to_send_visual(
    request, clean_test_db, assert_snapshot, logged_in_page,
):
    """AC-C12 snapshot #2: voice-input footer in ready_to_send state with
    textarea + Re-record + Send buttons. DOM is mutated directly to bypass
    the microphone-access requirement of the real recording flow."""
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/multiplexer" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.evaluate( _INJECT_SENDER_JS )
    page.wait_for_selector( '.cc-voice-input[data-session-hash="abcd1234"]', timeout=2000 )
    page.evaluate( _SIMULATE_READY_TO_SEND_JS )
    page.evaluate( _STABILIZE_JS )
    time.sleep( 0.3 )

    pane = page.locator( '#notifications-pane' )
    assert_snapshot( pane, name="multiplexer_phase6c_section_c_ready_to_send.png" )
    print( "✓ multiplexer_phase6c_section_c_ready_to_send: snapshot compared" )
