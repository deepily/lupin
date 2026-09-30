"""
E2E — the holding area's per-filer accordion, and the multiplexer's CJ Flow Jobs toggles (row 52142a84).

Rick, 2026-09-24: each persona's held rows load HIDDEN, openable by a click on the bar
carrying the name; and in the multiplexer, neither the CJ Flow pane's own toggle nor its
bucket toggles hid anything.

🔴 THESE TESTS ASSERT VISIBILITY, NOT CLASSES. The unit tier already pins `.collapsed` and
aria-expanded. What it cannot see is a CSS rule losing to a more specific one — which is
exactly how the CJ Flow pane broke: `data-collapsed="true"` was set correctly while
`#jobs-buckets-container { display: flex }` kept every bucket on screen. Only a real
browser computing real styles can catch that, so every assertion here is `is_visible()`.

Venue: :8000 (scheduled) — E2E UI suite.
"""

from __future__ import annotations

import json
import os

import pytest
import requests

from .conftest import BASE_URL
from .task_panes import MUX_HOLDING_AREA_PANE, tasks_route_handler, EMPTY_TASKS

TASKS_ROUTE = "**/api/tasks*"

HELD = {
    "tasks" : [
        { "id": f"held{ i }", "item_class": "task", "title": f"held row { i }", "status": "not_approved",
          "owner_persona": "krishna", "created_by": filer, "priority": "P2", "project": "lupin",
          "blocked_by": None, "next_chase_ts": None }
        for i, filer in enumerate( [ "krishna 420f5ec9", "krishna 420f5ec9", "mr radio 0e61abe3" ] )
    ],
    "count" : 3,
}


def _tokens() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    resp = requests.post( f"{BASE_URL}/auth/login", json={ "email": email, "password": password }, timeout=10 )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _open_multiplexer( page ) -> None:
    access, refresh = _tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )
    page.route( TASKS_ROUTE, tasks_route_handler( EMPTY_TASKS, holding_body=HELD ) )
    page.goto( f"{BASE_URL}/app/multiplexer", wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )


def _assert_accordion( page, pane: str ) -> None:
    """Rows hidden on load; one bar click shows only that filer's rows; a second hides them."""
    page.wait_for_selector( f"{pane} .holding-area-group", state="attached", timeout=10_000 )
    rows = page.locator( f"{pane} tr.task-row" )
    assert rows.count() == 3, f"expected the 3 held rows in the DOM, found { rows.count() } — nothing below is measured"
    assert not any( rows.nth( i ).is_visible() for i in range( 3 ) ), "a held row is VISIBLE on load"

    krishna = page.locator( f'{pane} .holding-area-group[data-filer="Krishna"]' )
    assert krishna.locator( ".holding-area-group-count" ).text_content() == "2"
    assert krishna.locator( ".holding-area-filer" ).is_visible(), "the bar itself must stay visible while collapsed"

    krishna.locator( ".holding-area-filer" ).click()
    assert krishna.locator( "tr.task-row" ).first.is_visible(), "Krishna's rows did not appear after the click"
    assert not page.locator( f'{pane} .holding-area-group[data-filer="Mr Radio"] tr.task-row' ).first.is_visible(), \
        "opening Krishna opened Mr Radio too"

    krishna.locator( ".holding-area-filer" ).click()
    assert not krishna.locator( "tr.task-row" ).first.is_visible(), "a second click did not hide the rows"


def test_legacy_holding_area_groups_load_hidden_and_open_on_click( logged_in_page ):
    # The same login route test_holding_area_per_row_editor.py drives on this page.
    page = logged_in_page
    page.route( TASKS_ROUTE, tasks_route_handler( EMPTY_TASKS, holding_body=HELD ) )
    page.goto( f"{BASE_URL}/app/notifications?classic=1", wait_until="networkidle", timeout=15_000 )
    _assert_accordion( page, "#holding-area-container" )


def test_multiplexer_holding_area_groups_load_hidden_and_open_on_click( page ):
    _open_multiplexer( page )
    _assert_accordion( page, MUX_HOLDING_AREA_PANE )


def _show_jobs_pane( page ):
    """The CJ Flow pane is cold-hidden by default; show it through its own toolbar button."""
    pane = page.locator( '[data-testid="multiplexer-jobs-pane"]' )
    if not pane.is_visible():
        page.get_by_test_id( "multiplexer-section-toolbar-jobs" ).click()
    pane.wait_for( state="visible", timeout=5_000 )
    return pane


def test_multiplexer_cj_flow_pane_header_hides_its_buckets( page ):
    _open_multiplexer( page )
    pane      = _show_jobs_pane( page )
    header    = page.get_by_test_id( "multiplexer-jobs-header" )
    container = page.locator( "#jobs-buckets-container" )

    assert "CJ Flow Jobs" in ( header.text_content() or "" ), "the pane header must read CJ Flow Jobs"
    assert container.is_visible(), "precondition: buckets visible before the toggle"

    header.locator( "h3" ).click()
    assert pane.get_attribute( "data-collapsed" ) == "true", "the header click did not register at all"
    assert not container.is_visible(), "data-collapsed is true but the buckets are still on screen"

    header.locator( "h3" ).click()
    assert container.is_visible(), "a second click did not bring the buckets back"


def test_multiplexer_cj_flow_empty_bucket_hides_its_message( page ):
    _open_multiplexer( page )
    _show_jobs_pane( page )
    buckets = page.locator( "#jobs-pane .jobs-bucket:has( .jobs-bucket-empty )" )
    assert buckets.count() >= 1, "no empty bucket on the page, so this test measures nothing"

    bucket  = buckets.first
    header  = bucket.locator( ".jobs-bucket-header" )
    message = bucket.locator( ".jobs-bucket-empty" )
    if header.get_attribute( "aria-expanded" ) == "false":
        header.click()
    assert message.is_visible(), "precondition: an open empty bucket shows its message"

    header.click()
    assert header.get_attribute( "aria-expanded" ) == "false"
    assert not message.is_visible(), "the caret closed but the empty bucket's message stayed on screen"
