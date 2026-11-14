"""
E2E UI: the multiplexer and a quiet worker.

The server stamps `worker_quiet: true` on a quiet worker's notifications. The multiplexer shows a
quiet chip on the worker's sender card. It does not speak the worker's `high`. It still speaks the
worker's `urgent`. These are Tiberius's third and fourth amendments. The tests emit on the page's
real event bus and read the speech intents that the notification store produces. The stores and the
card renderer are therefore the real ones.

Venue: :8000 (scheduled monopolize-mode via /api/v2/submit).
"""

from __future__ import annotations

import json
import os

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"
WORKER          = "claude.code@lupin.deepily.ai#muxquiet1"
OTHER           = "claude.code@lupin.deepily.ai#muxloud01"


def _login_tokens():
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _open( page ):
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( access )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( refresh )});"
    )
    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function( "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined", timeout=10_000 )
    page.evaluate( """() => {
        window.__intents = [];
        window.__multiplexerTestHook.eventBus.on( 'store_notification_tts_intent', ( e ) => window.__intents.push( e.payload.priority ) );
    }""" )


EMIT_JS = """
    ( args ) => {
        window.__intents.length = 0;
        window.__multiplexerTestHook.eventBus.emit( {
            type: 'notification_queue_update', source: 'e2e', ts: 0,
            payload: { notification: {
                id_hash: args.id, type: 'task', sender_id: args.sender, message: 'hello', priority: args.priority,
                timestamp: new Date().toISOString(),
                ...( args.quiet ? { worker_quiet: true } : {} )
            } }
        } );
        return window.__intents.slice();
    }
"""


def _emit( page, sender, priority, quiet ):
    return page.evaluate( EMIT_JS, { "id": f"m-{sender[-3:]}-{priority}-{int( quiet )}", "sender": sender, "priority": priority, "quiet": quiet } )


class TestMultiplexerQuietWorker:

    def test_medium_from_a_quiet_worker_is_not_spoken( self, page ):
        _open( page )
        assert _emit( page, WORKER, "medium", True ) == []

    def test_high_from_a_quiet_worker_is_not_spoken( self, page ):
        _open( page )
        assert _emit( page, WORKER, "high", True ) == []

    def test_urgent_from_a_quiet_worker_is_spoken( self, page ):
        _open( page )
        assert _emit( page, WORKER, "urgent", True ) == [ "urgent" ]

    def test_high_and_urgent_without_the_stamp_are_spoken( self, page ):
        _open( page )
        assert _emit( page, OTHER, "high", False ) == [ "high" ]
        assert _emit( page, OTHER, "urgent", False ) == [ "urgent" ]

    def test_a_quiet_worker_card_shows_the_chip_and_another_does_not( self, page ):
        _open( page )
        _emit( page, WORKER, "medium", True )
        _emit( page, OTHER, "medium", False )
        quiet_card = page.locator( f".sender-card[data-sender-id='{WORKER}']" )
        quiet_card.wait_for( timeout=5000 )
        assert quiet_card.locator( ".sender-quiet-chip" ).count() == 1
        assert quiet_card.get_attribute( "data-worker-quiet" ) == "true"
        loud_card = page.locator( f".sender-card[data-sender-id='{OTHER}']" )
        loud_card.wait_for( timeout=5000 )
        assert loud_card.locator( ".sender-quiet-chip" ).count() == 0

    def test_rick_turning_the_speakerphone_on_clears_the_chip( self, page ):
        _open( page )
        _emit( page, WORKER, "medium", True )
        page.locator( f".sender-card[data-sender-id='{WORKER}'] .sender-quiet-chip" ).wait_for( timeout=5000 )
        page.evaluate( """( sender ) => window.__multiplexerTestHook.eventBus.emit( {
            type: 'notification_queue_update', source: 'e2e', ts: 0,
            payload: { notification: { type: 'speakerphone_changed', sender_id: sender, timestamp: new Date().toISOString(), payload: { on: true } } }
        } )""", WORKER )
        page.wait_for_function( "( s ) => document.querySelector( `.sender-card[data-sender-id='${s}'] .sender-quiet-chip` ) === null", arg=WORKER, timeout=5000 )
