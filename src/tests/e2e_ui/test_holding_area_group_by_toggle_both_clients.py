#!/usr/bin/env python3
"""
E2E for the holding area's Creator / Assignee toggle, on both boards.

The holding area groups its held rows by `created_by` (Creator, the default) or by
`owner_persona` (Assignee). The choice is kept per browser.

This drives the served page in a real browser. The toggle is pressed with a real click and the
group headings are read back. Held rows are route-seeded with a different creator and assignee
on each row. A toggle that regroups on one field in both modes therefore cannot pass.
A reload must come back in the chosen mode.

Venue: :8000 (scheduled) — `logged_in_page` resets lupin_db_test and registers a user. Select with
`-k group_by_toggle`.
"""

import json
import os

import requests
from playwright.sync_api import expect

from .conftest import BASE_URL

LEGACY_PANE = "#holding-area-container"
MUX_PANE    = '[data-testid="multiplexer-holding-area-container"]'
TIMEOUT_MS  = 20_000

CREATOR_GROUPS  = [ "Mr Radio", "Rachel", "Sam" ]
ASSIGNEE_GROUPS = [ "Maria", "Mr Radio", "Tiberius", "Unassigned" ]


def _held( n, created_by, owner ):
    return {
        "id": f"00000000-0000-0000-0000-00000000010{n}", "title": f"toggle row {n}", "body": "",
        "owner_persona": owner, "status": "not_approved", "item_class": "task", "blocked_by": [ ],
        "next_chase_ts": None, "accountable_manager": "maria", "created_by": created_by,
        "priority": "P2", "project": "lupin", "correlation_key": None,
    }


ROWS = [
    _held( 1, "sam 0e61abe3",        "maria" ),
    _held( 2, "sam 0e61abe3",        "tiberius" ),
    _held( 3, "rachel 1111aaaa",     "maria" ),
    _held( 4, "rachel 1111aaaa",     None ),
    _held( 5, "mr radio 2222bbbb",   "mr radio" ),
]


def _route_rows( page ):
    def tasks_handler( route ):
        held = "status=not_approved" in route.request.url
        body = ROWS if held else [ ]
        route.fulfill( status=200, content_type="application/json",
                       body=json.dumps( { "tasks": body, "count": len( body ) } ) )
    page.route( "**/api/tasks*", tasks_handler )
    page.route( "**/api/epic-stories*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps( { "stories": [ ], "count": 0 } ) ) )


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
    _route_rows( page )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    return LEGACY_PANE, '[data-testid="holding-group-by-{by}"]'


def _open_mux( page ):
    _mux_login( page )
    _route_rows( page )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    return MUX_PANE, '[data-testid="multiplexer-holding-group-by-{by}"]'


def _groups( page, pane ):
    return page.locator( f"{pane} .holding-area-group" ).locator( ".holding-area-filer" ).evaluate_all( "els => els.map( e => e.textContent )" )


def _drive( page, pane, button ):
    expect( page.locator( f"{pane} .holding-area-group" ).first ).to_be_visible( timeout=TIMEOUT_MS )
    assert _groups( page, pane ) == CREATOR_GROUPS, "default grouping is by creator"
    expect( page.locator( button.format( by="creator" ) ) ).to_have_attribute( "aria-pressed", "true" )

    page.locator( button.format( by="assignee" ) ).click()
    expect( page.locator( f"{pane} .holding-area-group" ).first ).to_be_visible( timeout=TIMEOUT_MS )
    assert _groups( page, pane ) == ASSIGNEE_GROUPS, "Assignee regroups on owner_persona"
    expect( page.locator( button.format( by="assignee" ) ) ).to_have_attribute( "aria-pressed", "true" )

    page.reload( wait_until="networkidle" )
    expect( page.locator( f"{pane} .holding-area-group" ).first ).to_be_visible( timeout=TIMEOUT_MS )
    assert _groups( page, pane ) == ASSIGNEE_GROUPS, "the choice survives a reload"

    page.locator( button.format( by="creator" ) ).click()
    assert _groups( page, pane ) == CREATOR_GROUPS, "Creator returns to the filer grouping"


def test_group_by_toggle_legacy_board_switches_creator_and_assignee( logged_in_page ):
    pane, button = _open_legacy( logged_in_page )
    _drive( logged_in_page, pane, button )


def test_group_by_toggle_multiplexer_board_switches_creator_and_assignee( page ):
    pane, button = _open_mux( page )
    _drive( page, pane, button )
