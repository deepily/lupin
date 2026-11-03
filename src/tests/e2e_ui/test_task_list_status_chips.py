"""
E2E tests for the status chips in the live task list bar.

All is the default; the four chips are additive; all four or none is All. The chips compose
with find-by-id and its clear button. Claimed and review ride with In progress until Rick
rules. Routes are intercepted; the detail route goes last so Playwright checks it first.

Requires:
    - dev server on the test venue (:8000), clean test database

The visual test creates its baseline on the first run and fails once with "created (new)".
Run with --update-snapshots, review the PNG and commit it.
"""

import json

import pytest

from .conftest import BASE_URL
from .task_panes import LEGACY_TASK_LIST_PANE, EMPTY_TASKS, is_holding_area_query


def _row( task_id, title, status ):
    """One /api/tasks row in the real shape: array blocked_by, null chase."""
    return {
        "id"                  : task_id,
        "item_class"          : "task",
        "title"               : title,
        "owner_persona"       : "tiberius",
        "accountable_manager" : "tiberius",
        "status"              : status,
        "priority"            : "P2",
        "project"             : "lupin",
        "blocked_by"          : [ ],
        "next_chase_ts"       : None,
        "park_reason"         : None,
        "body"                : "",
    }


PARKED  = _row( "a1111111-1111-4111-8111-111111111111", "Row parked one",   "parked" )
BLOCKED = _row( "b2222222-2222-4222-8222-222222222222", "Row blocked one",  "blocked" )
ACTIVE  = _row( "c3333333-3333-4333-8333-333333333333", "Row active one",   "in_progress" )
CLAIMED = _row( "d4444444-4444-4444-8444-444444444444", "Row claimed one",  "claimed" )
REVIEW  = _row( "e5555555-5555-4555-8555-555555555555", "Row review one",   "review" )
QUEUED  = _row( "f6666666-6666-4666-8666-666666666666", "Row queued one",   "queued" )

BOARD_ROWS = [ PARKED, BLOCKED, ACTIVE, CLAIMED, REVIEW, QUEUED ]

TITLES = [ r[ "title" ] for r in BOARD_ROWS ]

# What each chip shows. Claimed and review under In progress are provisional until Rick rules.
EXPECTED = {
    "parked"      : [ PARKED ],
    "blocked"     : [ BLOCKED ],
    "in_progress" : [ ACTIVE, CLAIMED, REVIEW ],
    "queued"      : [ QUEUED ],
}

RATIO = { "created": 0, "closed": 0, "ratio": None, "verdict": "idle", "window_hours": 24 }


def _open( page, lookup_row=None ):
    """
    Stub the store, load the classic notifications page, wait for the rows.

    Requires:
        - page is a logged-in Playwright page; call before any navigation
    Ensures:
        - GET /api/tasks answers the six rows (the holding-area query answers empty)
        - GET /api/tasks/<ref> answers lookup_row (default: the queued row)
        - the six seeded rows are on screen when it returns
    """
    found = QUEUED if lookup_row is None else lookup_row

    def board( route ):
        body = EMPTY_TASKS if is_holding_area_query( route.request.url ) else { "tasks": BOARD_ROWS, "count": len( BOARD_ROWS ) }
        route.fulfill( status=200, content_type="application/json", body=json.dumps( body ) )

    def detail( route ):
        if "/api/tasks/flow-ratio" in route.request.url:
            route.fulfill( status=200, content_type="application/json", body=json.dumps( RATIO ) )
            return
        route.fulfill( status=200, content_type="application/json", body=json.dumps( found ) )

    page.route( "**/api/tasks*", board )
    page.route( "**/api/tasks/*", detail )   # LAST = checked first
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    page.wait_for_selector( f"{LEGACY_TASK_LIST_PANE} .task-row", state="attached" )
    return page


def _shown( page ):
    """The titles on screen in the live task list, as a sorted list."""
    text = page.locator( LEGACY_TASK_LIST_PANE ).inner_text()
    return sorted( t for t in TITLES if t in text )


def _titles( rows ):
    return sorted( r[ "title" ] for r in rows )


def _pressed( page ):
    """The data-chip keys of the buttons that are pressed."""
    return page.evaluate(
        "() => Array.from( document.querySelectorAll( '#task-status-chips button[aria-pressed=\"true\"]' ) )"
        ".map( b => b.getAttribute( 'data-chip' ) )"
    )


def _chip( page, key ):
    return page.get_by_test_id( f"task-status-chip-{ key }" )


def test_default_view_is_all( logged_in_page ):
    """All is pressed and every seeded open row shows, exactly as before the chips existed."""
    page = _open( logged_in_page )
    assert _pressed( page ) == [ "all" ]
    assert _shown( page ) == sorted( TITLES )
    labels = page.locator( "#task-status-chips button" ).all_inner_texts()
    assert labels == [ "All", "Parked", "Blocked", "In progress", "Queued" ]


@pytest.mark.parametrize( "key", list( EXPECTED ) )
def test_each_chip_alone( logged_in_page, key ):
    """One chip shows only its own statuses; All lets go."""
    page = _open( logged_in_page )
    _chip( page, key ).click()
    assert _pressed( page ) == [ key ]
    assert _shown( page ) == _titles( EXPECTED[ key ] )


def test_union_of_two_chips( logged_in_page ):
    """Parked and Queued together show both and nothing else."""
    page = _open( logged_in_page )
    _chip( page, "parked" ).click()
    _chip( page, "queued" ).click()
    assert _pressed( page ) == [ "parked", "queued" ]
    assert _shown( page ) == _titles( EXPECTED[ "parked" ] + EXPECTED[ "queued" ] )


def test_all_four_chips_equal_all( logged_in_page ):
    """Selecting the fourth chip collapses the bar to All and shows the whole list."""
    page = _open( logged_in_page )
    for key in EXPECTED:
        _chip( page, key ).click()
    assert _pressed( page ) == [ "all" ]
    assert _shown( page ) == sorted( TITLES )


def test_clearing_the_last_chip_returns_all( logged_in_page ):
    """Un-pressing the only selected chip returns to All, never to an empty list."""
    page = _open( logged_in_page )
    _chip( page, "blocked" ).click()
    assert _shown( page ) == _titles( EXPECTED[ "blocked" ] )
    _chip( page, "blocked" ).click()
    assert _pressed( page ) == [ "all" ]
    assert _shown( page ) == sorted( TITLES )


def test_all_button_drops_the_chips( logged_in_page ):
    """The All button clears a union in one click."""
    page = _open( logged_in_page )
    _chip( page, "blocked" ).click()
    _chip( page, "queued" ).click()
    _chip( page, "all" ).click()
    assert _pressed( page ) == [ "all" ]
    assert _shown( page ) == sorted( TITLES )


def test_filter_composes_with_find_by_id_and_its_clear( logged_in_page ):
    """Find-by-id pins one row over a chip view, and the ✕ puts the chip view back."""
    page = _open( logged_in_page )
    _chip( page, "blocked" ).click()
    assert _shown( page ) == _titles( EXPECTED[ "blocked" ] )

    page.get_by_test_id( "task-lookup-input" ).fill( QUEUED[ "id" ][ :8 ] )
    page.get_by_test_id( "task-lookup-go" ).click()
    page.wait_for_function(
        "() => document.getElementById( 'task-lookup-result' ).getAttribute( 'data-state' ) === 'filtered'"
    )
    assert _shown( page ) == _titles( [ QUEUED ] )
    assert _pressed( page ) == [ "blocked" ], "the chips keep their selection while a ticket is pinned"

    page.get_by_test_id( "task-lookup-clear" ).click()
    assert _shown( page ) == _titles( EXPECTED[ "blocked" ] )
    assert _pressed( page ) == [ "blocked" ]


def test_status_chip_bar_visual( logged_in_page, assert_snapshot ):
    """Pixels of the list bar with the chips: All selected, then a Blocked + Queued union."""
    page = _open( logged_in_page )
    page.evaluate( "() => document.fonts.ready" )
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    bar = page.get_by_test_id( "task-lookup" )
    assert_snapshot( bar, name="task_list_status_chips_all.png", snap_y=True )

    _chip( page, "blocked" ).click()
    _chip( page, "queued" ).click()
    page.evaluate( "() => new Promise( resolve => requestAnimationFrame( () => requestAnimationFrame( resolve ) ) )" )
    assert_snapshot( bar, name="task_list_status_chips_union.png", snap_y=True )
