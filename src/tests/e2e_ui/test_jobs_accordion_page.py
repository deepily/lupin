"""
E2E: the background-jobs accordion at /app/jobs.

The served page, its bundle and its auth path are the real ones. Only the two job doors are stubbed
with page.route. The summary door answers with the committed 23-job fixture,
src/tests/fixtures/jobs/jobs-summary.fixture.json. The Run now door answers as each test needs, so
no job is started. No test here touches a GPU.

Assertions cover what left the page as well as what is drawn. A Run now button that posts nothing,
or posts twice, would pass a test that only looks for the button.

Venue: :8000 (scheduled), E2E UI suite. The bundle static/dist/jobs/jobs.js must be built in the tree
:8000 serves (npm run build, or src/scripts/build-jobs.sh). Without it the page stays on "Loading…".
"""

from __future__ import annotations

import json
from pathlib import Path

from .conftest import BASE_URL

FIXTURE = json.loads( ( Path( __file__ ).resolve().parents[1] / "fixtures" / "jobs" / "jobs-summary.fixture.json" ).read_text( encoding="utf-8" ) )
STARTED = { "job": "duplicate-check", "target": None, "status": "started", "trigger": "hand", "pid": 4242, "started_at": "2026-11-07T20:31:00-05:00" }


def _stub( page, run_status=200, run_body=None, operator=True ):
    """Stub the summary door and the Run now door, and return the recorded run requests."""
    runs = [ ]
    summary = { **FIXTURE, "caller_is_operator": operator }
    page.route( "**/api/jobs/summary*", lambda r: r.fulfill( status=200, content_type="application/json", body=json.dumps( summary ) ) )

    def _run( route ):
        runs.append( { "url": route.request.url, "method": route.request.method, "auth": route.request.headers.get( "authorization", "" ) } )
        route.fulfill( status=run_status, content_type="application/json", body=json.dumps( STARTED if run_body is None else run_body ) )
    page.route( "**/api/jobs/*/run*", _run )
    return runs


def _open_jobs_page( page ):
    page.goto( f"{BASE_URL}/app/jobs" )
    page.get_by_test_id( "jobs-item" ).first.wait_for( state="visible", timeout=15_000 )


def test_the_page_shows_all_23_jobs_worst_state_first_each_collapsed( logged_in_page ):
    page = logged_in_page
    _stub( page )
    _open_jobs_page( page )
    items = page.locator( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" )
    assert items.count() == 23
    assert page.get_by_test_id( "jobs-header" ).inner_text() == "23 jobs: 9 unknown, 2 silent, 3 failing, 9 healthy"
    states = [ items.nth( i ).get_attribute( "data-state" ) for i in range( 23 ) ]
    assert states == sorted( states, key=[ "unknown", "silent", "failing", "behind", "healthy" ].index )
    assert page.locator( "[data-testid=jobs-line][aria-expanded=true]" ).count() == 0
    assert page.locator( "[data-testid=jobs-accordion] > [data-testid=jobs-item] > [data-testid=jobs-panel]:visible" ).count() == 0


def test_the_duplicate_check_line_and_panel_read_as_the_design_shows_them( logged_in_page ):
    page = logged_in_page
    _stub( page )
    _open_jobs_page( page )
    item = page.locator( "[data-testid=jobs-item][data-job=duplicate-check]" )
    line = item.get_by_test_id( "jobs-line" )
    assert item.get_by_test_id( "jobs-badge" ).inner_text() == "FAILING · BEHIND"
    assert item.get_by_test_id( "jobs-last-run" ).inner_text() == "last run 19:31 failed (stale_branch)"
    assert item.get_by_test_id( "jobs-clears-cell" ).inner_text() == "clears: never at this rate"

    line.click()
    assert line.get_attribute( "aria-expanded" ) == "true"
    panel = item.get_by_test_id( "jobs-panel" )
    panel.wait_for( state="visible", timeout=5_000 )
    assert panel.get_by_test_id( "jobs-reason" ).count() == 3
    assert panel.get_by_test_id( "jobs-strip-entry" ).count() == 5
    assert panel.get_by_test_id( "jobs-detail-link" ).get_attribute( "href" ) == "/app/duplicate-check"
    assert panel.get_by_test_id( "jobs-schedule-grace" ).inner_text() == "30 minutes"

    line.click()
    assert line.get_attribute( "aria-expanded" ) == "false"
    assert panel.is_hidden()


def test_run_now_posts_once_with_the_login_token_and_shows_the_outcome( logged_in_page ):
    page = logged_in_page
    runs = _stub( page )
    _open_jobs_page( page )
    item = page.locator( "[data-testid=jobs-item][data-job=duplicate-check]" )
    item.get_by_test_id( "jobs-line" ).click()
    item.get_by_test_id( "jobs-run-now" ).dblclick()
    item.get_by_test_id( "jobs-run-status" ).filter( has_text="pid 4242" ).wait_for( timeout=5_000 )
    assert len( runs ) == 1, f"a double click on a disabled button is one post; saw {len( runs )}"
    assert runs[ 0 ][ "method" ] == "POST" and runs[ 0 ][ "url" ].endswith( "/api/jobs/duplicate-check/run" )
    assert runs[ 0 ][ "auth" ].startswith( "Bearer " )


def test_a_refused_run_says_why_and_leaves_the_button_usable( logged_in_page ):
    page = logged_in_page
    runs = _stub( page, run_status=409, run_body={ "status": "refused", "reason": "lock_held" } )
    _open_jobs_page( page )
    item = page.locator( "[data-testid=jobs-item][data-job=duplicate-check]" )
    item.get_by_test_id( "jobs-line" ).click()
    button = item.get_by_test_id( "jobs-run-now" )
    button.click()
    item.get_by_test_id( "jobs-run-status" ).filter( has_text="run lock is held" ).wait_for( timeout=5_000 )
    assert button.is_enabled()
    assert len( runs ) == 1


def test_a_login_that_is_not_the_operator_sees_no_run_now_button( logged_in_page ):
    page = logged_in_page
    runs = _stub( page, operator=False )
    _open_jobs_page( page )
    assert page.locator( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).count() == 23
    item = page.locator( "[data-testid=jobs-item][data-job=duplicate-check]" )
    item.get_by_test_id( "jobs-line" ).click()
    item.get_by_test_id( "jobs-panel" ).wait_for( state="visible", timeout=5_000 )
    assert page.get_by_test_id( "jobs-run-now" ).count() == 0
    assert runs == [ ]


def test_a_job_that_cannot_run_by_hand_offers_no_run_now_button( logged_in_page ):
    page = logged_in_page
    _stub( page )
    _open_jobs_page( page )
    arbiter = page.locator( "[data-testid=jobs-item][data-job=fleet-arbiter]" )
    arbiter.get_by_test_id( "jobs-line" ).click()
    arbiter.get_by_test_id( "jobs-panel" ).wait_for( state="visible", timeout=5_000 )
    assert arbiter.get_by_test_id( "jobs-run-now" ).count() == 0
    assert arbiter.get_by_test_id( "jobs-last-run" ).inner_text() == "up (lupin-arbiter-app.service)"


def test_the_legacy_client_nav_opens_the_accordion( notifications_page ):
    page = notifications_page
    _stub( page )
    link = page.get_by_test_id( "nav-jobs-link" )
    link.wait_for( state="visible", timeout=10_000 )
    assert link.get_attribute( "href" ) == "/app/jobs"
    link.click()
    page.get_by_test_id( "jobs-item" ).first.wait_for( state="visible", timeout=15_000 )
    assert page.locator( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).count() == 23


def test_the_multiplexer_nav_opens_the_accordion( logged_in_page ):
    page = logged_in_page
    _stub( page )
    page.goto( f"{BASE_URL}/app/multiplexer" )
    link = page.get_by_test_id( "nav-jobs-link" )
    link.wait_for( state="visible", timeout=15_000 )
    assert link.get_attribute( "href" ) == "/app/jobs"
    link.click()
    page.get_by_test_id( "jobs-item" ).first.wait_for( state="visible", timeout=15_000 )
    assert page.locator( "[data-testid=jobs-accordion] > [data-testid=jobs-item]" ).count() == 23
