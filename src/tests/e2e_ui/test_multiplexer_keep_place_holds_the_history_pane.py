#!/usr/bin/env python3
"""
E2E: Keep place holds the scroll inside a session's notification history (multiplexer).

Requires:
    - The :8000 test container, and the test-hook login variables set.

Ensures:
    - A progress-group message makes the renderer replace the whole sender card, so its history list restarts at the top.
    - With Keep place on, streamed progress-group messages leave card A's scrolled history where it was.
    - The control repeats the stream with Keep place off and must see the history return to the top.

Usage:
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_keep_place_holds_the_history_pane.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

SENDER_A = "mv-keep-a"
SENDER_B = "mv-keep-b"

# Emit one task message through the test-hook EventBus. `age_ms` back-dates it from the
# browser's clock, so every row lands in today's (open) date accordion and the newest
# arrival is the newest card.
_EMIT_MESSAGE_JS = """
( args ) => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    hook.eventBus.emit({
        type    : 'notification_queue_update',
        payload : { notification: {
            id_hash   : args.id_hash,
            message   : args.message,
            sender_id : args.sender_id,
            timestamp : new Date( Date.now() - args.age_ms ).toISOString(),
            type      : 'task',
            progress_group_id : args.group,
        } },
        source : 'e2e-keep-place-history',
        ts     : Date.now(),
    });
    return true;
}
"""

_FIRST_CARD_JS = """
() => {
    const card = document.querySelector( '#notifications-pane .sender-card' );
    return card === null ? null : card.getAttribute( 'data-sender-id' );
}
"""

_CARD_SELECTOR = '#notifications-pane .sender-card[data-sender-id="{}"]'


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _open( page, keep_place ):
    """Seed auth on the managed page fixture, navigate, wait for the test hook."""
    email, password = _get_credentials()
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    page.context.add_init_script(
        f"window.localStorage.setItem('notifications_keep_place', '{ 'true' if keep_place else 'false' }');"
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( tokens[ 'access_token' ] ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( tokens[ 'refresh_token' ] ) });"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _emit( page, sender_id: str, n: int, age_ms: int, group=None ):
    page.evaluate( _EMIT_MESSAGE_JS, {
        "id_hash"   : f"{ sender_id }-{ n }",
        "message"   : f"message { n } from { sender_id }\n\nsecond paragraph so each row has some height",
        "sender_id" : sender_id,
        "age_ms"    : age_ms,
        "group"     : group,
    } )


def _scrolled_history( page, keep_place ):
    """Seed card A below card B, scrolled; return its selector."""
    _open( page, keep_place )
    for n in range( 20 ):
        _emit( page, SENDER_A, n, age_ms=120_000 - n * 1_000 )
    _emit( page, SENDER_B, 0, age_ms=30_000 )
    card_a = _CARD_SELECTOR.format( SENDER_A )
    page.wait_for_selector( _CARD_SELECTOR.format( SENDER_B ), timeout=5_000 )
    page.wait_for_function( "( sel ) => document.querySelectorAll( sel + ' [data-id-hash]' ).length >= 20", arg=card_a, timeout=5_000 )
    before = page.evaluate(
        """( sel ) => {
            const scroller = document.querySelector( sel + ' .date-accordion-messages' );
            scroller.scrollTop = 100;
            scroller.__probe   = 'kept';
            return { scrollTop: scroller.scrollTop, scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight };
        }""",
        card_a,
    )
    assert before[ "scrollHeight" ] - before[ "clientHeight" ] > 150, f"precondition: A's history must scroll: { before }"
    assert before[ "scrollTop" ] == 100, f"precondition: the list took the scroll: { before }"
    return card_a


def _stream_progress_group( page, card_a ):
    for n in range( 3 ):
        _emit( page, SENDER_A, 100 + n, age_ms=0, group="pg-keep-place" )
        page.wait_for_timeout( 300 )
    return page.evaluate(
        """( sel ) => {
            const scroller = document.querySelector( sel + ' .date-accordion-messages' );
            return { scrollTop: scroller.scrollTop, same_list: scroller.__probe === 'kept' };
        }""",
        card_a,
    )


def test_pinned_history_is_not_scrolled_to_the_top_by_streaming_notifications( page ):
    """
    Pinned history survives streamed progress-group messages.

    Ensures:
        - with Keep place on, progress-group messages from A leave A's history scrolled where it was
        - the list is a new element (the card was replaced), so the offset was put back, not kept by luck
    """
    card_a = _scrolled_history( page, keep_place=True )
    after  = _stream_progress_group( page, card_a )
    assert not after[ "same_list" ], f"precondition: a progress-group arrival replaces the card: { after }"
    assert after[ "scrollTop" ] >= 100, f"the pinned history went back to the top: 100 -> { after[ 'scrollTop' ] }"


def test_control_unpinned_history_is_scrolled_to_the_top_by_the_same_stream( page ):
    """
    Control: unpinned history returns to the top.

    Ensures:
        - with Keep place off, the same stream puts A's history back at the top
    """
    card_a = _scrolled_history( page, keep_place=False )
    after  = _stream_progress_group( page, card_a )
    assert after[ "scrollTop" ] == 0, f"with Keep place off the history should be at the top: { after }"


def test_pinned_history_is_not_scrolled_to_the_top_when_a_plain_message_raises_the_card( page ):
    """
    Pinned history survives a plain message that moves its card above another.

    Ensures:
        - with Keep place on, a message with no progress group raises card A to the top
        - A's history is still scrolled afterwards
        - there is no unpinned control: this browser keeps the scroll on a card move by itself, so the test guards the path but cannot fail
    """
    card_a = _scrolled_history( page, keep_place=True )
    _emit( page, SENDER_A, 200, age_ms=0 )
    page.wait_for_function(
        "( id ) => document.querySelector( '#notifications-pane .sender-card' ).getAttribute( 'data-sender-id' ) === id",
        arg=SENDER_A, timeout=5_000,
    )
    page.wait_for_function( "( sel ) => document.querySelector( sel + ' [data-id-hash=\"mv-keep-a-200\"]' ) !== null", arg=card_a, timeout=5_000 )
    top = page.evaluate( "( sel ) => document.querySelector( sel + ' .date-accordion-messages' ).scrollTop", card_a )
    assert top >= 100, f"the pinned history went back toward the top: 100 -> { top }"
