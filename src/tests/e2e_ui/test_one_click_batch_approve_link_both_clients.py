#!/usr/bin/env python3
"""
E2E test of the one-click batch link from an action-required card, on both clients.

A card carries one line written by the shipped helper `approve_batch_line`.
It has one link that moves a whole list of held rows, and one 📋 link that lists them. Rick clicks the approve link once.
Both listed rows must read `queued` afterwards.
The third seeded row must still read `not_approved`, the answer must name each row, and no new tab may open.

The click tests answer the transition requests themselves, as the sibling file does, because the :8000 login is
not Rick's. The route handler records each row id and body and sets the row's status.
It answers 200, or 403 for a row the test names. That proves what the browser does: one request per listed row, for that row.
The landing-page tests use the real server and make no write.

The helpers (seeding, the stand-in door, the card drawers) are the sibling file's, imported not copied.

Venue: :8000, scheduled. It seeds and deletes rows in lupin_db_test.
It lives in half A, so the suite is `e2e_a`. Select it with `-k one_click_batch`.
"""

import json
import re

from playwright.sync_api import expect

from cosa.rest.task_approve_link import approve_batch_line
from .conftest import BASE_URL
from .test_one_click_approve_link_both_clients import (  # noqa: F401  (held is a fixture)
    TIMEOUT_MS, held, _statuses, _operator_door, _login_tokens, _show_card_legacy, _show_card_multiplexer,
)


def _ids( rows, n=2 ):
    return [ r[ "id" ] for r in rows[ :n ] ]


def _refusing_door( page, posted, refused_id ):
    """Like `_operator_door`, but a request for `refused_id` is answered 403 and moves nothing."""
    from .test_one_click_approve_link_both_clients import _set_status

    def handle( route ):
        match = re.search( r"/api/tasks/([0-9a-f-]{36})/transition", route.request.url )
        body  = json.loads( route.request.post_data or "{}" )
        posted.append( ( match.group( 1 ), body ) )
        if match.group( 1 ) == refused_id:
            route.fulfill( status=403, content_type="application/json", body=json.dumps( { "detail": "not yours to approve" } ) )
            return
        _set_status( match.group( 1 ), body[ "to_status" ] )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( { "item": { "status": body[ "to_status" ] } } ) )

    page.route( re.compile( r".*/api/tasks/[0-9a-f-]{36}/transition$" ), handle )


# ---------------------------------------------------------------------------
# Legacy client
# ---------------------------------------------------------------------------

def test_one_click_batch_legacy_one_click_approves_both_rows( notifications_page, held ):
    page   = notifications_page
    posted = []
    popups = []
    page.context.on( "page", lambda p: popups.append( p ) )
    _operator_door( page, posted )

    content = _show_card_legacy( page, held, abstract=approve_batch_line( _ids( held ) ) )
    link    = content.locator( "a[href*='/app/tasks/approve?rows=']" )
    expect( link ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( link ).to_have_text( "approve all 2 ☐" )

    link.click()
    result = content.locator( ".approve-link-approved" )
    expect( result ).to_contain_text( "2 of 2 applied", timeout=TIMEOUT_MS )
    expect( result ).to_contain_text( f"{held[ 0 ][ 'id' ][ :8 ]} applied ✅" )
    expect( result ).to_contain_text( f"{held[ 1 ][ 'id' ][ :8 ]} applied ✅" )
    assert sorted( row_id for row_id, _ in posted ) == sorted( _ids( held ) ), "one request per listed row, none for the third"
    assert all( body[ "to_status" ] == "queued" for _, body in posted )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "queued", "queued", "not_approved" ]
    assert popups == [], "a batch link must never open a tab"
    assert page.url.startswith( f"{BASE_URL}/app/notifications" ), "and must never navigate this one"


def test_one_click_batch_legacy_a_refused_row_does_not_hide_the_other( notifications_page, held ):
    page   = notifications_page
    posted = []
    _refusing_door( page, posted, held[ 0 ][ "id" ] )

    content = _show_card_legacy( page, held, abstract=approve_batch_line( _ids( held ) ) )
    content.locator( "a[href*='/app/tasks/approve?rows=']" ).click()

    result = content.locator( ".approve-link-refused" )
    expect( result ).to_contain_text( "1 of 2 applied", timeout=TIMEOUT_MS )
    expect( result ).to_contain_text( f"{held[ 0 ][ 'id' ][ :8 ]} refused: not yours to approve" )
    expect( result ).to_contain_text( f"{held[ 1 ][ 'id' ][ :8 ]} applied ✅" )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved", "queued", "not_approved" ]


def _expect_tip_lists_only( tip, listed, unlisted ):
    # One retrying expect per claim. Waiting on one title and then calling inner_text() is a second look that does not wait.
    expect( tip ).to_contain_text( re.compile( "".join( f"(?=.*{re.escape( r[ 'title' ] )})" for r in listed ), re.DOTALL ), timeout=TIMEOUT_MS )
    expect( tip ).not_to_contain_text( unlisted[ "title" ], timeout=TIMEOUT_MS )


def test_one_click_batch_legacy_view_link_lists_every_title_before_the_click( notifications_page, held ):
    page    = notifications_page
    posted  = []
    _operator_door( page, posted )
    content = _show_card_legacy( page, held, abstract=approve_batch_line( _ids( held ) ) )

    content.locator( "a[href*='/app/tasks/view?rows=']" ).click()

    tip = page.locator( "#abstract-tooltip .abstract-tooltip-content" )
    _expect_tip_lists_only( tip, held[ :2 ], held[ 2 ] )
    assert posted == [] and _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved" ] * 3, "viewing moves nothing"


# ---------------------------------------------------------------------------
# Multiplexer
# ---------------------------------------------------------------------------

def test_one_click_batch_multiplexer_one_click_approves_both_rows( logged_in_page, held ):
    page   = logged_in_page
    posted = []
    popups = []
    page.context.on( "page", lambda p: popups.append( p ) )
    _operator_door( page, posted )

    card = _show_card_multiplexer( page, held, abstract=approve_batch_line( _ids( held ) ) )
    link = card.locator( "a[href*='/app/tasks/approve?rows=']" )
    expect( link ).to_have_count( 1, timeout=TIMEOUT_MS )
    expect( link ).to_have_text( "approve all 2 ☐" )

    link.click()
    result = card.locator( ".approve-link-approved" )
    expect( result ).to_contain_text( "2 of 2 applied", timeout=TIMEOUT_MS )
    assert sorted( row_id for row_id, _ in posted ) == sorted( _ids( held ) )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "queued", "queued", "not_approved" ]
    assert popups == [], "a batch link must never open a tab"
    assert page.url.startswith( f"{BASE_URL}/app/multiplexer" )


def test_one_click_batch_multiplexer_one_click_drops_both_rows_with_the_reason( logged_in_page, held ):
    page   = logged_in_page
    posted = []
    _operator_door( page, posted )

    card = _show_card_multiplexer( page, held, abstract=approve_batch_line( _ids( held ), "dropped", "duplicate refile" ) )
    link = card.locator( "a[href*='/app/tasks/approve?rows=']" )
    expect( link ).to_have_text( "drop all 2 ☐", timeout=TIMEOUT_MS )

    link.click()
    expect( card.locator( ".approve-link-approved" ) ).to_contain_text( "2 of 2 applied", timeout=TIMEOUT_MS )
    assert all( body[ "to_status" ] == "dropped" and body[ "reason" ] == "duplicate refile" for _, body in posted )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "dropped", "dropped", "not_approved" ]


def test_one_click_batch_multiplexer_a_refused_row_does_not_hide_the_other( logged_in_page, held ):
    page   = logged_in_page
    posted = []
    _refusing_door( page, posted, held[ 1 ][ "id" ] )

    card = _show_card_multiplexer( page, held, abstract=approve_batch_line( _ids( held ) ) )
    card.locator( "a[href*='/app/tasks/approve?rows=']" ).click()

    result = card.locator( ".approve-link-refused" )
    expect( result ).to_contain_text( "1 of 2 applied", timeout=TIMEOUT_MS )
    expect( result ).to_contain_text( f"{held[ 1 ][ 'id' ][ :8 ]} refused: not yours to approve" )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "queued", "not_approved", "not_approved" ]


def test_one_click_batch_multiplexer_view_link_lists_every_title_before_the_click( logged_in_page, held ):
    page = logged_in_page
    card = _show_card_multiplexer( page, held, abstract=approve_batch_line( _ids( held ) ) )

    card.locator( "a[href*='/app/tasks/view?rows=']" ).click()

    tip = page.locator( "#abstract-tooltip .abstract-tooltip-content" )
    _expect_tip_lists_only( tip, held[ :2 ], held[ 2 ] )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved" ] * 3, "viewing moves nothing"


# ---------------------------------------------------------------------------
# The safe landing pages
# ---------------------------------------------------------------------------

def test_one_click_batch_landing_page_lists_the_rows_and_changes_nothing( logged_in_page, held ):
    page = logged_in_page
    _login_tokens( page )
    ids = ",".join( _ids( held ) )

    page.goto( f"{BASE_URL}/app/tasks/approve?rows={ids}&move=queued", wait_until="networkidle", timeout=15_000 )

    items = page.get_by_test_id( "task-approve-batch-list" ).locator( "li" )
    expect( items ).to_have_count( 2, timeout=TIMEOUT_MS )
    expect( items.nth( 0 ) ).to_contain_text( held[ 0 ][ "title" ] )
    expect( page.get_by_test_id( "task-approve-batch-button" ) ).to_have_text( "Approve all 2" )
    page.wait_for_timeout( 1000 )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved" ] * 3, "opening the page must not move any row"


def test_one_click_batch_landing_page_refuses_a_duplicate_id_and_a_drop_without_reason( logged_in_page, held ):
    page = logged_in_page
    a    = held[ 0 ][ "id" ]
    page.goto( f"{BASE_URL}/app/tasks/approve?rows={a},{a}&move=queued", wait_until="networkidle", timeout=15_000 )
    expect( page.get_by_test_id( "task-approve-error" ) ).to_contain_text( "clean list", timeout=TIMEOUT_MS )
    expect( page.get_by_test_id( "task-approve-batch" ) ).to_be_hidden()
    page.goto( f"{BASE_URL}/app/tasks/approve?rows={a}&move=dropped", wait_until="networkidle", timeout=15_000 )
    expect( page.get_by_test_id( "task-approve-error" ) ).to_contain_text( "clean list", timeout=TIMEOUT_MS )


def test_one_click_batch_view_landing_page_lists_the_rows( logged_in_page, held ):
    page = logged_in_page
    _login_tokens( page )
    page.goto( f"{BASE_URL}/app/tasks/view?rows={','.join( _ids( held ) )}", wait_until="networkidle", timeout=15_000 )
    items = page.get_by_test_id( "task-view-batch" ).locator( "li" )
    expect( items ).to_have_count( 2, timeout=TIMEOUT_MS )
    expect( items.nth( 1 ) ).to_contain_text( held[ 1 ][ "title" ] )
    assert _statuses( [ r[ "id" ] for r in held ] ) == [ "not_approved" ] * 3


def test_one_click_batch_view_landing_page_refuses_a_short_id( logged_in_page ):
    page = logged_in_page
    page.goto( f"{BASE_URL}/app/tasks/view?rows=a3975cf4", wait_until="networkidle", timeout=15_000 )
    expect( page.get_by_test_id( "task-view-error" ) ).to_contain_text( "clean list", timeout=TIMEOUT_MS )
