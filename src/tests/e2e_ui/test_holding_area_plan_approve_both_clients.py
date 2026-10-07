#!/usr/bin/env python3
"""
E2E — "Approve all N" on a PLAN under a filer, on BOTH boards (row 451fd70e; replaces the
stories strip of row eb235858, which Rick read as broken groups).

Inside one filer's group, rows that share a plan key sit under a "Plan: <title>" sub-header that
opens and closes like the filer group and carries its own "Approve all N" for exactly the rows
listed under it. A filer's rows that belong to no plan stay directly under the filer. The
control is a client loop of ordinary single-row transitions — there is no batch route — so the
server's per-row approver gate is what keeps it operator-only.

TWO KINDS OF TEST, because the :8000 login is not Rick's and cannot be made so:

    REAL SERVER, REAL ROWS (non-operator): three held rows under one plan key plus one
    UNGROUPED row, all from one filer, are seeded into lupin_db_test through the ORM. The plan
    group is closed on arrival, opens on a click and lists exactly its three rows; the ungrouped
    row sits outside it; the confirmed click is answered 403 per row by the real door; the plan
    paints "0 of 3 approved — 3 refused" and the DB still holds all four as `not_approved`.

    ROUTE-SEEDED (operator): the operator path is simulated by answering the transitions 200,
    because the real door only answers Rick's own account. That proves what the BROWSER does —
    open the plan, see its rows, two clicks, N POSTs naming the plan's ids in order, the plan
    gone afterwards and the filer's ungrouped row STILL HELD — and nothing about the door, which
    the unit tier's TestClient arms cover.

It does NOT measure a real approval performing the move on :8000, for the reason above.

Every seeded row is deleted afterwards (fixture teardown, and again before seeding).

Venue: :8000 (scheduled) — seeds and deletes rows in lupin_db_test. Select with
`-k plan_approve`.
"""

import json
import os
import uuid

import pytest
import requests
from playwright.sync_api import expect

from .conftest import BASE_URL
from .task_panes import open_holding_groups

PLAN_MARKER    = "e2e-plan-approve@rachel"
PLAN_KEY       = "epic:e2e-plan-approve"
PLAN_TITLE     = "Plan: e2e plan approve"
PLAN_ROWS      = 3
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
        f"SAFETY: the plan-approve E2E must only seed lupin_db_test, got: {db_url}"


def _delete_plan_rows():
    """Delete every row this file created (events cascade)."""
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        for item in session.query( TaskItem ).filter( TaskItem.created_by == PLAN_MARKER ).all():
            session.delete( item )


def _seed_plan():
    """
    Three held rows under PLAN_KEY and one held row with NO key, all from one filer.

    Ensures:
        - returns ( plan_ids, ungrouped_id ) as strings, plan ids in creation order
        - every row is `not_approved` and carries created_by == PLAN_MARKER
    """
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    def _row( key, label ):
        return TaskItem(
            item_class="task", title=f"E2E plan approve {label} {uuid.uuid4().hex[ :6 ]}",
            project="lupin", created_by=PLAN_MARKER, owner_persona=None,
            accountable_manager=None, status="not_approved", blocked_by=[ ],
            priority="P3", correlation_key=key,
        )

    with get_db() as session:
        plan      = [ _row( PLAN_KEY, f"row {i}" ) for i in range( PLAN_ROWS ) ]
        ungrouped = _row( None, "ungrouped" )
        for item in plan + [ ungrouped ]:
            session.add( item )
        session.flush()
        return [ str( i.id ) for i in plan ], str( ungrouped.id )


def _statuses( ids ):
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import TaskItem

    with get_db() as session:
        return [ session.get( TaskItem, uuid.UUID( i ) ).status for i in ids ]


@pytest.fixture( scope="function" )
def plan():
    _require_test_db()
    _delete_plan_rows()
    ids, ungrouped = _seed_plan()
    yield { "ids": ids, "ungrouped": ungrouped }
    _delete_plan_rows()


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


def _plan( page, pane, key, filer=None ):
    sel = f'{pane} .holding-plan-group[data-plan="{key}"]'
    if filer is not None:
        sel += f'[data-filer="{filer}"]'
    return page.locator( sel )


def _row( page, pane, task_id ):
    """
    The disclose button of a row's VISIBLE line, which both clients paint. Not the verb select: that lives in the
    per-row editor, hidden until the button is pressed, so it is hidden even in an open group.
    """
    return page.locator( f'{pane} .task-disclose-button[data-task-id="{task_id}"]' )


def _ungrouped_row( page, pane, task_id ):
    """A row sitting directly in a filer's own table — not inside any plan group."""
    return page.locator( f'{pane} .holding-area-group > table .task-disclose-button[data-task-id="{task_id}"]' )


# ---------------------------------------------------------------------------
# REAL SERVER: the plan sits under its filer, opens, lists its rows; a non-operator is refused
# ---------------------------------------------------------------------------

def _non_operator_refused( page, pane, plan ):
    group = _plan( page, pane, PLAN_KEY )
    expect( group ).to_have_count( 1, timeout=TIMEOUT_MS )
    # The plan sits INSIDE a filer group, never above one.
    expect( page.locator( f'{pane} .holding-area-group .holding-plan-group[data-plan="{PLAN_KEY}"]' ) ).to_have_count( 1 )
    expect( group.locator( ".holding-plan-label" ) ).to_have_text( PLAN_TITLE )
    expect( group.locator( ".holding-plan-count" ) ).to_have_text( str( PLAN_ROWS ) )
    expect( group.locator( ".holding-plan-approve-all" ) ).to_have_text( f"Approve all {PLAN_ROWS}" )

    # Closed on arrival, like its filer; one click on the header opens it and lists exactly its rows.
    expect( _row( page, pane, plan[ "ids" ][ 0 ] ) ).to_be_hidden()
    group.locator( ".holding-plan-header" ).click( position={ "x": 4, "y": 4 } )
    for task_id in plan[ "ids" ]:
        expect( _row( page, pane, task_id ) ).to_be_visible()
    # The filer's own ungrouped row is NOT inside the plan group, and is listed under the filer.
    expect( group.locator( f'.task-disclose-button[data-task-id="{plan[ "ungrouped" ]}"]' ) ).to_have_count( 0 )
    expect( _ungrouped_row( page, pane, plan[ "ungrouped" ] ) ).to_be_visible()

    posts = []
    page.on( "response", lambda r: posts.append( r ) if r.request.method == "POST" and "/transition" in r.url else None )
    # ARM, THEN CONFIRM (row 376dd4cb): the first click only arms, so it posts nothing.
    group.locator( ".holding-plan-approve-all" ).click()
    expect( group.locator( ".holding-plan-approve-all" ) ).to_have_text( f"Confirm approve all {PLAN_ROWS}" )
    assert posts == [ ], f"the arming click posted: {[ r.url for r in posts ]}"
    group.locator( ".holding-plan-approve-all" ).click()

    expect( group.locator( ".holding-plan-status" ) ).to_contain_text(
        f"0 of {PLAN_ROWS} approved — {PLAN_ROWS} refused. First refusal:", timeout=TIMEOUT_MS )

    sent = [ r.url.split( "/api/tasks/" )[ 1 ].split( "/" )[ 0 ] for r in posts ]
    assert sorted( sent ) == sorted( plan[ "ids" ] ), f"the click did not post exactly the plan's rows: {sent}"
    assert [ r.status for r in posts ] == [ 403 ] * PLAN_ROWS, f"expected three 403s, got {[ r.status for r in posts ]}"
    assert _statuses( plan[ "ids" ] ) == [ "not_approved" ] * PLAN_ROWS, "a refused click moved a row"
    assert _statuses( [ plan[ "ungrouped" ] ] ) == [ "not_approved" ], "the click touched the filer's ungrouped row"
    expect( group.locator( ".holding-plan-approve-all" ) ).to_be_enabled()


def test_plan_approve_legacy_board_refuses_a_non_operator( logged_in_page, plan ):
    pane = _open_legacy( logged_in_page )
    open_holding_groups( logged_in_page, pane )
    _non_operator_refused( logged_in_page, pane, plan )


def test_plan_approve_multiplexer_board_refuses_a_non_operator( page, plan ):
    pane = _open_mux( page )
    open_holding_groups( page, pane )
    _non_operator_refused( page, pane, plan )


# ---------------------------------------------------------------------------
# ROUTE-SEEDED: what the browser does when the door says yes
# ---------------------------------------------------------------------------

UNGROUPED_ID = "00000000-0000-0000-0000-0000000000f1"
SAM_IDS      = [ f"00000000-0000-0000-0000-0000000000a{i}" for i in range( 1, 3 ) ]


def _held( task_id, key, n, filer="rachel" ):
    return {
        "id": task_id, "title": f"plan row {n}", "body": "", "owner_persona": filer,
        "status": "not_approved", "item_class": "task", "blocked_by": [ ], "next_chase_ts": None,
        "accountable_manager": "maria", "created_by": f"{filer} 4f98d12f", "priority": "P2",
        "project": "lupin", "correlation_key": key,
    }


def _route_operator( page ):
    """
    Serve three plan rows and one ungrouped row from Rachel, and two rows Sam filed under the
    SAME key; a transition answered 200 removes its row.

    Ensures:
        - returns state with "transitions": [ { "id", "body" } ] in the order they arrived
    """
    rows  = [ _held( f"00000000-0000-0000-0000-00000000000{i}", PLAN_KEY, i ) for i in range( 1, PLAN_ROWS + 1 ) ]
    rows += [ _held( UNGROUPED_ID, None, 9 ) ]
    rows += [ _held( task_id, PLAN_KEY, 20 + n, filer="sam" ) for n, task_id in enumerate( SAM_IDS ) ]
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
                       body=json.dumps( { "item": _held( task_id, PLAN_KEY, 0 ) | { "status": "queued" } } ) )

    page.route( "**/api/tasks/*/transition", transition_handler )
    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps( { "stories": [ ], "count": 0 } ) ) )
    return state


def _operator_two_clicks( page, pane, state ):
    open_holding_groups( page, pane )
    rachel = _plan( page, pane, PLAN_KEY, "Rachel" )
    sam    = _plan( page, pane, PLAN_KEY, "Sam" )
    expect( rachel ).to_have_count( 1, timeout=TIMEOUT_MS )
    # The same key under two filers is TWO plans, one under each — never one merged group.
    expect( sam ).to_have_count( 1 )
    expect( rachel.locator( ".holding-plan-count" ) ).to_have_text( str( PLAN_ROWS ) )
    expect( sam.locator( ".holding-plan-count" ) ).to_have_text( str( len( SAM_IDS ) ) )

    # The plan is CLOSED on arrival, and its rows are hidden.
    expect( rachel.locator( ".holding-plan-header" ) ).to_have_attribute( "aria-expanded", "false" )
    expect( _row( page, pane, "00000000-0000-0000-0000-000000000001" ) ).to_be_hidden()

    # ARM, THEN CONFIRM (row 376dd4cb): the first click arms and posts nothing — and it OPENS the
    # plan, so the rows about to be approved are on screen before the confirming click.
    rachel.locator( ".holding-plan-approve-all" ).click()
    expect( rachel.locator( ".holding-plan-approve-all" ) ).to_have_text( f"Confirm approve all {PLAN_ROWS}" )
    expect( rachel.locator( ".holding-plan-header" ) ).to_have_attribute( "aria-expanded", "true" )
    for i in range( 1, PLAN_ROWS + 1 ):
        expect( _row( page, pane, f"00000000-0000-0000-0000-00000000000{i}" ) ).to_be_visible()
    expect( _ungrouped_row( page, pane, UNGROUPED_ID ) ).to_be_visible()
    expect( sam.locator( ".holding-plan-header" ) ).to_have_attribute( "aria-expanded", "false" )
    assert state[ "transitions" ] == [ ], f"the arming click posted: {state[ 'transitions' ]}"
    rachel.locator( ".holding-plan-approve-all" ).click()

    expect( _plan( page, pane, PLAN_KEY, "Rachel" ) ).to_have_count( 0, timeout=TIMEOUT_MS )
    sent = state[ "transitions" ]
    assert [ t[ "id" ] for t in sent ] == [ f"00000000-0000-0000-0000-00000000000{i}" for i in range( 1, PLAN_ROWS + 1 ) ], \
        f"two clicks did not post the plan's three rows in order: {sent}"
    assert all( t[ "body" ][ "to_status" ] == "queued" for t in sent ), f"a row went somewhere other than queued: {sent}"
    sent_ids = [ t[ "id" ] for t in sent ]
    assert UNGROUPED_ID not in sent_ids, "the filer's ungrouped row was approved"
    assert not set( SAM_IDS ) & set( sent_ids ), "the same key under another filer was approved"
    # The ungrouped row is STILL HELD, still listed under its filer, and Sam's plan is untouched.
    expect( _ungrouped_row( page, pane, UNGROUPED_ID ) ).to_be_visible()
    expect( _plan( page, pane, PLAN_KEY, "Sam" ) ).to_have_count( 1 )


def test_plan_approve_legacy_board_two_clicks_approve_the_plan( logged_in_page ):
    state = _route_operator( logged_in_page )
    pane  = _open_legacy( logged_in_page )
    _operator_two_clicks( logged_in_page, pane, state )


def test_plan_approve_multiplexer_board_two_clicks_approve_the_plan( page ):
    state = _route_operator( page )
    pane  = _open_mux( page )
    _operator_two_clicks( page, pane, state )


def test_plan_approve_multiplexer_board_labels_the_plan_and_never_paints_the_raw_key( page ):
    """The label is "Plan: <title>"; the key is only a tooltip; nothing says story or epic."""
    _route_operator( page )
    pane = _open_mux( page )
    open_holding_groups( page, pane )
    group = _plan( page, pane, PLAN_KEY, "Rachel" )
    expect( group ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( group.locator( ".holding-plan-label" ) ).to_have_text( PLAN_TITLE )
    expect( group.locator( ".holding-plan-label" ) ).to_have_attribute( "title", PLAN_KEY )
    header_text = group.locator( ".holding-plan-header" ).inner_text()
    assert "epic" not in header_text.lower() and "story" not in header_text.lower(), \
        f"the header says story or epic: {header_text!r}"
    expect( page.locator( f"{pane} .holding-area-stories, {pane} .holding-story-bar" ) ).to_have_count( 0 )


def test_plan_approve_legacy_board_labels_the_plan_and_never_paints_the_raw_key( logged_in_page ):
    _route_operator( logged_in_page )
    pane = _open_legacy( logged_in_page )
    open_holding_groups( logged_in_page, pane )
    group = _plan( logged_in_page, pane, PLAN_KEY, "Rachel" )
    expect( group ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( group.locator( ".holding-plan-label" ) ).to_have_text( PLAN_TITLE )
    header_text = group.locator( ".holding-plan-header" ).inner_text()
    assert "epic" not in header_text.lower() and "story" not in header_text.lower(), \
        f"the header says story or epic: {header_text!r}"
    expect( logged_in_page.locator( f"{pane} .holding-area-stories, {pane} .holding-story-bar" ) ).to_have_count( 0 )


# ---------------------------------------------------------------------------
# ROUTE-SEEDED: closing a plan disarms its Approve all (bug e848467a)
# ---------------------------------------------------------------------------

def _arm_close_reopen( page, pane, state ):
    """
    Arm a plan, close it, reopen it: the button is at rest and one press only arms.

    The two-press rule exists so nobody approves rows they are not looking at. An arm that outlives
    a close would let one press, minutes later, approve a plan nobody is looking at.
    """
    open_holding_groups( page, pane )
    rachel = _plan( page, pane, PLAN_KEY, "Rachel" )
    expect( rachel ).to_have_count( 1, timeout=TIMEOUT_MS )
    button = rachel.locator( ".holding-plan-approve-all" )
    header = rachel.locator( ".holding-plan-header" )

    button.click()                                                    # arms, and opens the plan
    expect( button ).to_have_text( f"Confirm approve all {PLAN_ROWS}" )
    expect( header ).to_have_attribute( "aria-expanded", "true" )

    header.click( position={ "x": 4, "y": 4 } )                       # closes the plan
    expect( header ).to_have_attribute( "aria-expanded", "false" )
    expect( button ).to_have_text( f"Approve all {PLAN_ROWS}" )       # disarmed by the close
    expect( rachel.locator( ".holding-plan-status" ) ).to_have_text( "" )

    header.click( position={ "x": 4, "y": 4 } )                       # reopens it
    expect( header ).to_have_attribute( "aria-expanded", "true" )
    expect( button ).to_have_text( f"Approve all {PLAN_ROWS}" )
    expect( rachel.locator( ".holding-plan-status" ) ).to_have_text( "" )

    button.click()                                                    # one press arms again; it must not approve
    expect( button ).to_have_text( f"Confirm approve all {PLAN_ROWS}" )
    assert state[ "transitions" ] == [ ], f"a press after a close and a reopen posted: {state[ 'transitions' ]}"


def test_plan_approve_legacy_board_closing_a_plan_disarms_it( logged_in_page ):
    state = _route_operator( logged_in_page )
    pane  = _open_legacy( logged_in_page )
    _arm_close_reopen( logged_in_page, pane, state )


def test_plan_approve_multiplexer_board_closing_a_plan_disarms_it( page ):
    state = _route_operator( page )
    pane  = _open_mux( page )
    _arm_close_reopen( page, pane, state )
