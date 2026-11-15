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
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

APP_ZONE = ZoneInfo( "America/New_York" )


def _just_before_midnight():
    """
    The moment to freeze the page clock for the midnight test: 23:59:50 yesterday.

    It lies behind the real clock, so the access tokens stay valid.
    A token lasts 30 minutes, and the page calls it expired within a minute of its expiry.
    A frozen moment ahead of the real clock would make every token read as expired.
    """
    yesterday = datetime.now( APP_ZONE ).date() - timedelta( days=1 )
    return datetime.combine( yesterday, time( 23, 59, 50 ), tzinfo=APP_ZONE )


SENDER_A = "mv-keep-a"
SENDER_B = "mv-keep-b"

# Emit one task message through the test-hook EventBus. `age_ms` back-dates it from the
# browser's clock, which each test freezes, so every row lands in today's (open) date accordion
# on any run and the newest arrival is the newest card.
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


_DATE_ACCORDIONS_JS = """
( sel ) => document.querySelectorAll( sel + ' .date-accordion-messages' ).length
"""


def _assert_one_date_accordion( page, card_a, when ):
    """Guard: the card has one date accordion, so the measured pane holds the whole history."""
    count = page.evaluate( _DATE_ACCORDIONS_JS, card_a )
    assert count == 1, f"{when}: the card has {count} date accordions, so the seeded and the new messages fell on different days"


def _open( page, keep_place, no_move_before=False, frozen=None ):
    """Seed auth, freeze the page clock, open the page, wait for the test hook."""
    page.clock.set_fixed_time( frozen or datetime.now( APP_ZONE ) )
    email, password = _get_credentials()
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    page.context.add_init_script(
        f"window.localStorage.setItem('notifications_keep_place', '{ 'true' if keep_place else 'false' }');"
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( tokens[ 'access_token' ] ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( tokens[ 'refresh_token' ] ) });"
    )
    if no_move_before:
        page.context.add_init_script( "delete Element.prototype.moveBefore;" )
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


def _scrolled_history( page, keep_place, no_move_before=False, frozen=None ):
    """Seed card A below card B, scrolled; return its selector."""
    _open( page, keep_place, no_move_before, frozen )
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
    _assert_one_date_accordion( page, card_a, "after seeding" )
    return card_a


def _stream_progress_group( page, card_a ):
    for n in range( 3 ):
        _emit( page, SENDER_A, 100 + n, age_ms=0, group="pg-keep-place" )
        page.wait_for_timeout( 300 )
    _assert_one_date_accordion( page, card_a, "after the stream" )
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


def _plain_message_raises_the_card( page, keep_place ):
    """Raise card A with a plain message, moveBefore removed; return its list scroll."""
    card_a = _scrolled_history( page, keep_place=keep_place, no_move_before=True )
    assert page.evaluate( "() => typeof Element.prototype.moveBefore" ) == "undefined", "precondition: moveBefore is removed"
    _emit( page, SENDER_A, 200, age_ms=0 )
    page.wait_for_function(
        "( id ) => document.querySelector( '#notifications-pane .sender-card' ).getAttribute( 'data-sender-id' ) === id",
        arg=SENDER_A, timeout=5_000,
    )
    page.wait_for_function( "( sel ) => document.querySelector( sel + ' [data-id-hash=\"mv-keep-a-200\"]' ) !== null", arg=card_a, timeout=5_000 )
    _assert_one_date_accordion( page, card_a, "after the arrival" )
    return page.evaluate( "( sel ) => document.querySelector( sel + ' .date-accordion-messages' ).scrollTop", card_a )


def test_pinned_history_is_not_scrolled_to_the_top_when_a_plain_message_raises_the_card( page ):
    """
    Pinned history survives a plain message that moves its card above another.

    Ensures:
        - with moveBefore removed, the card move falls back to insertBefore, which resets the list
        - with Keep place on, A's history is still scrolled afterwards
    """
    top = _plain_message_raises_the_card( page, keep_place=True )
    assert top >= 100, f"the pinned history went back toward the top: 100 -> { top }"


def test_control_unpinned_history_is_scrolled_to_the_top_when_a_plain_message_raises_the_card( page ):
    """
    Control: unpinned history returns to the top on the fallback.

    Ensures:
        - with moveBefore removed and Keep place off, the same message resets A's history to 0
    """
    top = _plain_message_raises_the_card( page, keep_place=False )
    assert top == 0, f"with Keep place off the history should be at the top, got { top }"


def test_pinned_history_holds_with_the_page_clock_at_one_minute_to_midnight( page ):
    """
    Pinned history survives the stream with the page clock frozen at 23:59:50.

    Ensures:
        - the seeded rows and the streamed ones fall on one date however long the run takes
        - the history is still scrolled afterwards
    """
    card_a = _scrolled_history( page, keep_place=True, frozen=_just_before_midnight() )
    after  = _stream_progress_group( page, card_a )
    assert after[ "scrollTop" ] >= 100, f"the pinned history went back to the top: 100 -> { after[ 'scrollTop' ] }"
