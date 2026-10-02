#!/usr/bin/env python3
"""
E2E — "Approve all N in this story" on BOTH boards (row eb235858).

A plan import files its rows as a batch of held rows sharing one `correlation_key`. The
holding area shows one bar per story of two or more rows, with ONE control. The control is
a client loop of ordinary single-row transitions — there is no batch route — so the server's
per-row approver gate is what keeps it operator-only.

TWO KINDS OF TEST, because the :8000 login is not Rick's and cannot be made so:

    REAL SERVER, REAL ROWS (non-operator): three held rows plus one lone row are seeded into
    lupin_db_test through the ORM. The bar shows for the three and not for the lone one; the
    click is answered 403 per row by the real door; the bar paints "0 of 3 approved — 3
    refused" and the DB still holds all three as `not_approved`.

    ROUTE-SEEDED (operator): the operator path is simulated by answering the transitions
    200, because the real door only answers Rick's own account. That proves what the BROWSER
    does — one click, N POSTs naming the story's ids in order, the bar gone afterwards — and
    nothing about the door, which the unit tier's TestClient arms cover.

It does NOT measure a real approval performing the move on :8000, for the reason above.

Venue: :8000 (scheduled) — seeds and deletes rows in lupin_db_test. Select with
`-k story_approve`.
"""

import json
import os
import uuid

import pytest
import requests
from playwright.sync_api import expect

from .conftest import BASE_URL
from .task_panes import open_holding_groups

STORY_MARKER   = "e2e-story-approve@rachel"
STORY_KEY      = "epic:e2e-story-approve"
LONE_KEY       = "epic:e2e-story-lone"
STORY_ROWS     = 3
TIMEOUT_MS     = 20_000

LEGACY_PANE = "#holding-area-container"
MUX_PANE    = '[data-testid="multiplexer-holding-area-container"]'


# ---------------------------------------------------------------------------
# Real rows
# ---------------------------------------------------------------------------

def _require_test_db():
    from cosa.rest.db import database as db_module

    db_url = str( db_module.engine.url )
    assert "lupin_db_test" in db_url, \
        f"SAFETY: the story-approve E2E must only seed lupin_db_test, got: {db_url}"


def _delete_story_rows():
    """Delete every row this file created (events cascade)."""
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        for item in session.query( TaskItem ).filter( TaskItem.created_by == STORY_MARKER ).all():
            session.delete( item )


def _seed_story():
    """
    Three held rows under STORY_KEY and one lone held row under LONE_KEY.

    Ensures:
        - returns ( story_ids, lone_id ) as strings, story ids in creation order
        - every row is `not_approved` and carries created_by == STORY_MARKER
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    def _row( key, label ):
        return TaskItem(
            item_class="task", title=f"E2E story approve {label} {uuid.uuid4().hex[ :6 ]}",
            project="lupin", created_by=STORY_MARKER, owner_persona=None,
            accountable_manager=None, status="not_approved", blocked_by=[ ],
            priority="P3", correlation_key=key,
        )

    with get_db() as session:
        story = [ _row( STORY_KEY, f"row {i}" ) for i in range( STORY_ROWS ) ]
        lone  = _row( LONE_KEY, "lone" )
        for item in story + [ lone ]:
            session.add( item )
        session.flush()
        return [ str( i.id ) for i in story ], str( lone.id )


def _statuses( ids ):
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        return [ session.get( TaskItem, uuid.UUID( i ) ).status for i in ids ]


@pytest.fixture( scope="function" )
def story():
    _require_test_db()
    _delete_story_rows()
    ids, lone = _seed_story()
    yield { "ids": ids, "lone": lone }
    _delete_story_rows()


# ---------------------------------------------------------------------------
# Shared drivers
# ---------------------------------------------------------------------------

def _mux_login( page ):
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


def _open_legacy( page ):
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    return LEGACY_PANE


def _open_mux( page ):
    _mux_login( page )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    return MUX_PANE


def _bar( page, pane, key ):
    return page.locator( f'{pane} .holding-story-bar[data-story="{key}"]' )


# ---------------------------------------------------------------------------
# REAL SERVER: the bar shows for a story, not for a lone row, and a non-operator is refused
# ---------------------------------------------------------------------------

def _non_operator_refused( page, pane, story ):
    story_bar = _bar( page, pane, STORY_KEY )
    expect( story_bar ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( story_bar.locator( ".holding-story-approve-all" ) ).to_have_text( f"Approve all {STORY_ROWS} in this story" )
    # The lone row is held, on the board, and has NO bar — a story is two rows or more.
    expect( _bar( page, pane, LONE_KEY ) ).to_have_count( 0 )

    posts = []
    page.on( "response", lambda r: posts.append( r ) if r.request.method == "POST" and "/transition" in r.url else None )
    # ARM, THEN CONFIRM (row 376dd4cb): the first click only arms, so it posts nothing.
    story_bar.locator( ".holding-story-approve-all" ).click()
    expect( story_bar.locator( ".holding-story-approve-all" ) ).to_have_text( f"Confirm approve all {STORY_ROWS} in this story" )
    assert posts == [ ], f"the arming click posted: {[ r.url for r in posts ]}"
    story_bar.locator( ".holding-story-approve-all" ).click()

    status = story_bar.locator( ".holding-story-status" )
    expect( status ).to_contain_text( f"0 of {STORY_ROWS} approved — {STORY_ROWS} refused. First refusal:", timeout=TIMEOUT_MS )

    sent = [ r.url.split( "/api/tasks/" )[ 1 ].split( "/" )[ 0 ] for r in posts ]
    assert sorted( sent ) == sorted( story[ "ids" ] ), f"the click did not post exactly the story's rows: {sent}"
    assert [ r.status for r in posts ] == [ 403 ] * STORY_ROWS, f"expected three 403s, got {[ r.status for r in posts ]}"
    assert _statuses( story[ "ids" ] ) == [ "not_approved" ] * STORY_ROWS, "a refused click moved a row"
    assert _statuses( [ story[ "lone" ] ] ) == [ "not_approved" ], "the click touched the lone row"
    # The bar stays for a retry, and its button is live again.
    expect( story_bar.locator( ".holding-story-approve-all" ) ).to_be_enabled()


def test_story_approve_legacy_board_refuses_a_non_operator( logged_in_page, story ):
    pane = _open_legacy( logged_in_page )
    open_holding_groups( logged_in_page, pane )
    _non_operator_refused( logged_in_page, pane, story )


def test_story_approve_multiplexer_board_refuses_a_non_operator( page, story ):
    pane = _open_mux( page )
    open_holding_groups( page, pane )
    _non_operator_refused( page, pane, story )


# ---------------------------------------------------------------------------
# ROUTE-SEEDED: what the browser does when the door says yes
# ---------------------------------------------------------------------------

def _held( task_id, key, n ):
    return {
        "id": task_id, "title": f"story row {n}", "body": "", "owner_persona": "rachel",
        "status": "not_approved", "item_class": "task", "blocked_by": [ ], "next_chase_ts": None,
        "accountable_manager": "maria", "created_by": "rachel 4f98d12f", "priority": "P2",
        "project": "lupin", "correlation_key": key,
    }


def _route_operator( page ):
    """
    Serve three story rows and one lone row; a transition answered 200 removes its row.

    Ensures:
        - returns state with "transitions": [ { "id", "body" } ] in the order they arrived
    """
    rows  = [ _held( f"00000000-0000-0000-0000-00000000000{i}", STORY_KEY, i ) for i in range( 1, STORY_ROWS + 1 ) ]
    rows += [ _held( "00000000-0000-0000-0000-0000000000f1", LONE_KEY, 9 ) ]
    state = { "transitions": [ ], "rows": rows }

    def tasks_handler( route ):
        held = "status=not_approved" in route.request.url
        body = state[ "rows" ] if held else [ ]
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "tasks": body, "count": len( body ) } ) )

    def transition_handler( route ):
        task_id = route.request.url.split( "/api/tasks/" )[ 1 ].split( "/" )[ 0 ]
        state[ "transitions" ].append( { "id": task_id, "body": json.loads( route.request.post_data or "{}" ) } )
        state[ "rows" ] = [ r for r in state[ "rows" ] if r[ "id" ] != task_id ]
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "item": _held( task_id, STORY_KEY, 0 ) | { "status": "queued" } } ) )

    page.route( "**/api/tasks/*/transition", transition_handler )
    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps( { "stories": [ ], "count": 0 } ) ) )
    return state


def _operator_two_clicks( page, pane, state ):
    page.wait_for_selector( f"{pane} .holding-area-group", state="attached" )
    story_bar = _bar( page, pane, STORY_KEY )
    expect( story_bar ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( _bar( page, pane, LONE_KEY ) ).to_have_count( 0 )

    # ARM, THEN CONFIRM (row 376dd4cb): the first click arms and posts nothing.
    story_bar.locator( ".holding-story-approve-all" ).click()
    expect( story_bar.locator( ".holding-story-approve-all" ) ).to_have_text( f"Confirm approve all {STORY_ROWS} in this story" )
    assert state[ "transitions" ] == [ ], f"the arming click posted: {state[ 'transitions' ]}"
    story_bar.locator( ".holding-story-approve-all" ).click()

    expect( _bar( page, pane, STORY_KEY ) ).to_have_count( 0, timeout=TIMEOUT_MS )
    sent = state[ "transitions" ]
    assert [ t[ "id" ] for t in sent ] == [ f"00000000-0000-0000-0000-00000000000{i}" for i in range( 1, STORY_ROWS + 1 ) ], \
        f"two clicks did not post the story's three rows in order: {sent}"
    assert all( t[ "body" ][ "to_status" ] == "queued" for t in sent ), f"a row went somewhere other than queued: {sent}"
    assert "00000000-0000-0000-0000-0000000000f1" not in [ t[ "id" ] for t in sent ], "the lone row was approved"


def test_story_approve_legacy_board_two_clicks_approve_the_story( logged_in_page ):
    state = _route_operator( logged_in_page )
    pane  = _open_legacy( logged_in_page )
    _operator_two_clicks( logged_in_page, pane, state )


def test_story_approve_multiplexer_board_two_clicks_approve_the_story( page ):
    state = _route_operator( page )
    pane  = _open_mux( page )
    _operator_two_clicks( page, pane, state )
