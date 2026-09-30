#!/usr/bin/env python3
"""
E2E — a sender card that an arrival moves to the top keeps the scroll inside it (row 11793820).

THE DEFECT. keyedListMerge placed a moved card with insertBefore, which detaches the node before
re-inserting it, and a detached element loses its scroll position. In Chrome on bundle 3d959d529554
the card node, its rows and reply-box focus all survived an arrival, but when the arrival raised the
card to the top, the scroll inside its `.date-accordion-messages` list went from 100 to 0. The fix
moves an already-attached card with Element.moveBefore, which does not detach it.

WHAT THIS PINS. In a real browser: card A sits below card B with its date list scrolled to 100; a
message from A raises A to the top; the card is the same node, and the list's scrollTop is still at
least 100 (scroll anchoring may add the new row's height; a detach resets it to 0). Unit tests stub
moveBefore because happy-dom has none, so only a browser can show the scroll survives.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch.

Usage:
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_card_move_keeps_scroll.py -v
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

SENDER_A = "mv-scroll-a"
SENDER_B = "mv-scroll-b"

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
        } },
        source : 'e2e-card-move-scroll',
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


def _open( page ):
    """Seed auth on the managed page fixture, navigate, wait for the test hook."""
    email, password = _get_credentials()
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( tokens[ 'access_token' ] ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( tokens[ 'refresh_token' ] ) });"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _emit( page, sender_id: str, n: int, age_ms: int ):
    page.evaluate( _EMIT_MESSAGE_JS, {
        "id_hash"   : f"{ sender_id }-{ n }",
        "message"   : f"message { n } from { sender_id }\n\nsecond paragraph so each row has some height",
        "sender_id" : sender_id,
        "age_ms"    : age_ms,
    } )


def test_a_card_raised_to_the_top_by_an_arrival_keeps_its_scroll( page ):
    """
    Ensures:
        - card A, below card B, with its date list scrolled to 100, is raised to the top by a
          message from A
        - the raised card is the same DOM node, and its date list's scrollTop is still >= 100
    """
    _open( page )
    for n in range( 20 ):
        _emit( page, SENDER_A, n, age_ms=120_000 - n * 1_000 )
    _emit( page, SENDER_B, 0, age_ms=30_000 )

    card_a = _CARD_SELECTOR.format( SENDER_A )
    page.wait_for_selector( _CARD_SELECTOR.format( SENDER_B ), timeout=5_000 )
    page.wait_for_function( "( sel ) => document.querySelectorAll( sel + ' .notification-item, ' + sel + ' [data-id-hash]' ).length >= 20", arg=card_a, timeout=5_000 )
    assert page.evaluate( _FIRST_CARD_JS ) == SENDER_B, "precondition: B's newer message puts B's card above A's"

    before = page.evaluate(
        """( sel ) => {
            const card     = document.querySelector( sel );
            const scroller = card.querySelector( '.date-accordion-messages' );
            card.__moveProbe     = 'a';
            scroller.__moveProbe = 'a';
            scroller.scrollTop   = 100;
            return { scrollTop: scroller.scrollTop, scrollHeight: scroller.scrollHeight, clientHeight: scroller.clientHeight };
        }""",
        card_a,
    )
    assert before[ "scrollHeight" ] - before[ "clientHeight" ] > 150, f"precondition: A's date list must scroll: { before }"
    assert before[ "scrollTop" ] == 100, f"precondition: the list took the scroll: { before }"

    _emit( page, SENDER_A, 20, age_ms=0 )
    page.wait_for_function( "( id ) => { const c = document.querySelector( '#notifications-pane .sender-card' ); return c !== null && c.getAttribute( 'data-sender-id' ) === id; }", arg=SENDER_A, timeout=5_000 )
    page.wait_for_function( "( sel ) => document.querySelector( sel + ' [data-id-hash=\"mv-scroll-a-20\"]' ) !== null", arg=card_a, timeout=5_000 )

    after = page.evaluate(
        """( sel ) => {
            const card     = document.querySelector( sel );
            const scroller = card.querySelector( '.date-accordion-messages' );
            return { card_kept: card.__moveProbe === 'a', scroller_kept: scroller.__moveProbe === 'a', scrollTop: scroller.scrollTop };
        }""",
        card_a,
    )
    assert after[ "card_kept" ] and after[ "scroller_kept" ], f"the raised card is not the same node: { after }"
    assert after[ "scrollTop" ] >= before[ "scrollTop" ], (
        f"moving the card to the top reset the scroll inside it: { before[ 'scrollTop' ] } -> { after[ 'scrollTop' ] }"
    )
