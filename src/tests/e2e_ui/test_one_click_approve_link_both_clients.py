#!/usr/bin/env python3
"""
E2E test of one-click ticket approval from an action-required card, on both clients.

A card lists three held rows, each with its own approve link. Rick clicks two of them.
Exactly those two rows must read `queued` afterwards and the third must still read `not_approved`.
The clicked links must read "Approved ✓", and no new tab may open.

The :8000 login is not Rick's and cannot be made so. Two kinds of test follow from that.

The click tests answer the transition request themselves. The route handler records the row id,
sets that row to `queued` in lupin_db_test, and answers 200. That proves what the browser does:
one request per clicked link, for that link's row id and no other. It says nothing about the
server door, which the unit tier's TestClient arms cover.

The landing-page tests use the real server. Opening `/app/tasks/approve?row=<id>` shows the row
and its Approve button and leaves the row `not_approved`. No click is made, so the account does not matter.

Every seeded row is deleted afterwards, by fixture teardown and again before seeding.

Venue: :8000, scheduled. It seeds and deletes rows in lupin_db_test.
It lives in half A, so the suite is `e2e_a`. Select it with `-k one_click_approve`.
"""

import json
import os
import re
import uuid

import pytest
import requests
from playwright.sync_api import expect

from .conftest import BASE_URL

MARKER     = "e2e-one-click-approve@rachel"
ROWS       = 3
TIMEOUT_MS = 20_000
CARD_ID    = "one-click-approve-card"
SENDER     = "claude.code@lupin.deepily.ai#e2eapprove"


# ---------------------------------------------------------------------------
# Real rows
# ---------------------------------------------------------------------------

def _require_test_db():
    from cosa.rest.db import database as db_module

    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: the one-click approve E2E must only seed lupin_db_test, got: {db_url}"


def _delete_rows():
    """Delete every row this file created (events cascade)."""
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        for item in session.query( TaskItem ).filter( TaskItem.created_by == MARKER ).all():
            session.delete( item )


def _seed():
    """
    Three held rows from one filer.

    Ensures:
        - returns [ { "id", "title" } ] in creation order, every row `not_approved`
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        items = [
            TaskItem(
                item_class="task", title=f"E2E one-click approve row {i} {uuid.uuid4().hex[ :6 ]}",
                project="lupin", created_by=MARKER, owner_persona=None,
                accountable_manager=None, status="not_approved", blocked_by=[ ], priority="P3",
            )
            for i in range( ROWS )
        ]
        for item in items:
            session.add( item )
        session.flush()
        return [ { "id": str( i.id ), "title": i.title } for i in items ]


def _statuses( ids ):
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        return [ session.get( TaskItem, uuid.UUID( i ) ).status for i in ids ]


def _set_queued( row_id ):
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        session.get( TaskItem, uuid.UUID( row_id ) ).status = "queued"


@pytest.fixture( scope="function" )
def held():
    _require_test_db()
    _delete_rows()
    rows = _seed()
    yield rows
    _delete_rows()


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def _abstract_for( rows ):
    """The card abstract, written by the shipped helper so the format under test is the real one."""
    from cosa.rest.task_approve_link import approve_link_line

    return "\n".join( approve_link_line( r[ "id" ], r[ "title" ] ) for r in rows )


def _operator_door( page, posted ):
    """
    Answer transitions as Rick's own login would: record the row, queue it, say 200.

    Ensures:
        - `posted` receives ( row_id, request body ) per request, in order
    """
    def handle( route ):
        match = re.search( r"/api/tasks/([0-9a-f-]{36})/transition", route.request.url )
        body  = json.loads( route.request.post_data or "{}" )
        posted.append( ( match.group( 1 ), body ) )
        if body.get( "to_status" ) == "queued": _set_queued( match.group( 1 ) )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( { "item": { "status": "queued" } } ) )

    page.route( re.compile( r".*/api/tasks/[0-9a-f-]{36}/transition$" ), handle )


def _login_tokens( page ):
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        raise ValueError( "Set LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL and LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: {resp.status_code} {resp.text}"
    tokens = resp.json()[ "tokens" ]
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', {json.dumps( tokens[ 'access_token' ] )});"
        f"window.localStorage.setItem('lupin_refresh_token', {json.dumps( tokens[ 'refresh_token' ] )});"
    )


# ---------------------------------------------------------------------------
# Legacy client
# ---------------------------------------------------------------------------

def test_one_click_approve_legacy_two_clicks_approve_exactly_two_rows( notifications_page, held ):
    page    = notifications_page
    posted  = []
    popups  = []
    page.context.on( "page", lambda p: popups.append( p ) )
    _operator_door( page, posted )

    # Horizontal layout lifts the card into the shared pane: the surface whose doc links open a tab.
    page.locator( "#layout-mode-toggle" ).click()
    page.evaluate(
        """( args ) => {
            window.notificationsUI.handleNotificationUpdate( { notification: {
                id: args.nid, id_hash: args.nid, type: 'custom', response_requested: true,
                response_type: 'yes_no', message: 'Approve these tickets?', title: 'Approve these tickets?',
                abstract: args.abstract, timeout_seconds: 300, sender_id: args.sender } } );
        }""",
        { "nid": CARD_ID, "abstract": _abstract_for( held ), "sender": SENDER },
    )
    page.locator( "#action-required-content .abstract-indicator" ).first.click()
    tooltip_links = page.locator( "#abstract-tooltip .abstract-tooltip-content a[href*='/app/tasks/approve']" )
    expect( tooltip_links ).to_have_count( ROWS, timeout=TIMEOUT_MS )

    tooltip_links.nth( 0 ).click()
    expect( page.locator( "#abstract-tooltip .approve-link-approved" ) ).to_have_count( 1, timeout=TIMEOUT_MS )
    page.locator( "#abstract-tooltip .abstract-tooltip-content a[href*='/app/tasks/approve']" ).nth( 1 ).click()
    expect( page.locator( "#abstract-tooltip .approve-link-approved" ) ).to_have_count( 2, timeout=TIMEOUT_MS )

    assert [ row_id for row_id, _ in posted ] == [ held[ 0 ][ "id" ], held[ 2 ][ "id" ] ], \
        "one request per clicked link, for that link's row, in click order"
    assert all( body[ "to_status" ] == "queued" for _, body in posted )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "queued", "not_approved", "queued" ]
    assert popups == [], "an approve link must never open a tab"
    assert page.url.startswith( f"{BASE_URL}/app/notifications" ), "and must never navigate this one"


# ---------------------------------------------------------------------------
# Multiplexer
# ---------------------------------------------------------------------------

def test_one_click_approve_multiplexer_two_clicks_approve_exactly_two_rows( logged_in_page, held ):
    page   = logged_in_page
    posted = []
    popups = []
    page.context.on( "page", lambda p: popups.append( p ) )
    _operator_door( page, posted )

    _login_tokens( page )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook && window.__multiplexerTestHook.eventBus && window.__multiplexerTestHook.stores"
        " && window.__multiplexerTestHook.stores.actionRequired",
        timeout=15_000,
    )
    page.evaluate(
        """( args ) => {
            window.__multiplexerTestHook.eventBus.emit( {
                type: 'notification_queue_update', source: 'one-click-approve-e2e', ts: 1789790400000,
                payload: { notification: {
                    id_hash: args.nid, message: 'Approve these tickets?', sender_id: args.sender,
                    timestamp: '2026-10-31T18:00:00.000Z', response_requested: true, response_type: 'yes_no',
                    timeout_seconds: 300, abstract: args.abstract } } } );
        }""",
        { "nid": CARD_ID, "abstract": _abstract_for( held ), "sender": SENDER },
    )
    card  = page.locator( f'[data-testid="multiplexer-action-required"][data-id-hash="{CARD_ID}"]' )
    links = card.locator( "a[href*='/app/tasks/approve']" )
    expect( links ).to_have_count( ROWS, timeout=TIMEOUT_MS )

    links.nth( 0 ).click()
    expect( card.locator( ".approve-link-approved" ) ).to_have_count( 1, timeout=TIMEOUT_MS )
    card.locator( "a[href*='/app/tasks/approve']" ).nth( 1 ).click()
    expect( card.locator( ".approve-link-approved" ) ).to_have_count( 2, timeout=TIMEOUT_MS )

    assert [ row_id for row_id, _ in posted ] == [ held[ 0 ][ "id" ], held[ 2 ][ "id" ] ]
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "queued", "not_approved", "queued" ]
    assert popups == [], "an approve link must never open a tab"
    assert page.url.startswith( f"{BASE_URL}/app/multiplexer" )


# ---------------------------------------------------------------------------
# The safe landing page
# ---------------------------------------------------------------------------

def test_one_click_approve_landing_page_shows_the_row_and_changes_nothing( logged_in_page, held ):
    page = logged_in_page
    _login_tokens( page )
    row = held[ 0 ]

    page.goto( f"{BASE_URL}/app/tasks/approve?row={row[ 'id' ]}", wait_until="networkidle", timeout=15_000 )

    expect( page.get_by_test_id( "task-approve-title" ) ).to_have_text( row[ "title" ], timeout=TIMEOUT_MS )
    expect( page.get_by_test_id( "task-approve-status" ) ).to_have_text( "not_approved" )
    expect( page.get_by_test_id( "task-approve-button" ) ).to_be_enabled()
    page.wait_for_timeout( 1000 )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved" ] * ROWS, \
        "opening the landing page must not move any row"


def test_one_click_approve_landing_page_refuses_a_short_id( logged_in_page ):
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/tasks/approve?row=a3975cf4", wait_until="networkidle", timeout=15_000 )
    expect( page.get_by_test_id( "task-approve-error" ) ).to_contain_text( "full ticket id", timeout=TIMEOUT_MS )
    expect( page.get_by_test_id( "task-approve-row" ) ).to_be_hidden()
