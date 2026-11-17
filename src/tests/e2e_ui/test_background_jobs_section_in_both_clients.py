"""
E2E: the jobs list is a section of both the legacy client and the multiplexer.

Rick ruled that it is not a page of its own. Each test runs once per client, against the real
served page, script and login. Only the three job doors are stubbed with page.route.

The list also carries the switch list: each job's switch is on its second line.
The first line, the ⋯ and the 📋 are tested in test_merged_jobs_list_in_both_clients.py.

The summary door answers with the committed 23-job fixture. The switch list answers with two rows.
One is for a reported job and one is for a switch the summary does not report on, so the list holds 24 rows.
The Run now door answers as each test needs, so no job starts. No test here touches a GPU.
Assertions cover what left the page too: a Run now button that posts nothing, or twice, would pass a
test that only finds it.

The two clients share no runtime code. One set of assertions run against both keeps them from
drifting apart.

Venue: the scheduled :8000 E2E UI suite. The multiplexer bundle must be built in the served tree
with npm run build, or the multiplexer pane never mounts.
"""

# Row c80ef763: the merged jobs list.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import BASE_URL

FIXTURE = json.loads( ( Path( __file__ ).resolve().parents[1] / "fixtures" / "jobs" / "jobs-summary.fixture.json" ).read_text( encoding="utf-8" ) )
STARTED = { "job": "duplicate-check", "target": None, "status": "started", "trigger": "hand", "pid": 4242, "started_at": "2026-11-07T20:31:00-05:00" }

CLIENTS = {
    "legacy"      : { "url": "/app/notifications?classic=1", "section": "#section-background-jobs", "accordion": "#background-jobs-container",
                      "toolbar": "background-jobs-toolbar-btn", "count": "background-jobs-count", "refresh": "background-jobs-refresh-btn" },
    "multiplexer" : { "url": "/app/multiplexer",             "section": "#background-jobs-pane",     "accordion": "#background-jobs-pane [data-testid=jobs-accordion]",
                      "toolbar": "multiplexer-section-toolbar-background-jobs", "count": "multiplexer-background-jobs-count", "refresh": "multiplexer-background-jobs-refresh" },
}


@pytest.fixture( params=list( CLIENTS ) )
def client( request ):
    """The client under test: its address and the selectors of its own section."""
    return CLIENTS[ request.param ]


SWITCHES = { "caller_is_admin": True, "jobs": [
    { "job": "duplicate-check", "title": "Duplicate check", "schedule": "cron 0 10-22 * * *", "key": "k", "enabled": True,  "honoured": True, "drift": False, "last_changed_by": None, "last_changed_at": None },
    { "job": "reporting-off",   "title": "Reporting off",   "schedule": "cron 0 1 * * *",     "key": "k", "enabled": False, "honoured": True, "drift": False, "last_changed_by": None, "last_changed_at": None },
] }


def _stub( page, run_status=200, run_body=None, operator=True ):
    """Stub the summary, switch list and Run now doors; return the recorded requests."""
    runs     = [ ]
    summaries = [ ]
    summary  = { **FIXTURE, "caller_is_operator": operator }

    def _summary( route ):
        summaries.append( route.request.headers.get( "authorization", "" ) )
        route.fulfill( status=200, content_type="application/json", body=json.dumps( summary ) )
    page.route( "**/api/jobs/summary*", _summary )
    page.route( "**/api/cron-jobs", lambda route: route.fulfill( status=200, content_type="application/json", body=json.dumps( SWITCHES ) )
                if route.request.method == "GET" else route.continue_() )

    def _run( route ):
        runs.append( { "url": route.request.url, "method": route.request.method, "auth": route.request.headers.get( "authorization", "" ) } )
        route.fulfill( status=run_status, content_type="application/json", body=json.dumps( STARTED if run_body is None else run_body ) )
    page.route( "**/api/jobs/*/run*", _run )
    return runs, summaries


def _open( page, client ):
    page.goto( f"{BASE_URL}{client[ 'url' ]}" )
    page.locator( f"{client[ 'accordion' ]} > [data-testid=jobs-item]" ).first.wait_for( state="visible", timeout=20_000 )
    return page.locator( client[ "accordion" ] )


def _dup( accordion ):
    return accordion.locator( "[data-testid=jobs-item][data-job=duplicate-check]" )


def test_the_section_shows_all_24_rows_by_service_name_a_to_z_each_collapsed( logged_in_page, client ):
    page = logged_in_page
    _, summaries = _stub( page )
    accordion = _open( page, client )
    items = accordion.locator( ":scope > [data-testid=jobs-item]" )
    assert items.count() == 24, "the 23 reported jobs and the switch the summary does not report on"
    assert page.get_by_test_id( client[ "count" ] ).inner_text() == "24 (1 off)"
    titles = [ items.nth( i ).locator( "[data-testid=jobs-title]" ).first.inner_text() for i in range( 24 ) ]
    assert titles[ :2 ] == [ "Commons archival", "Context tick" ], "the default order is service name A to Z (row 1ac04991)"
    in_page = page.evaluate( "t => [ ...t ].sort( ( a, b ) => a.localeCompare( b ) )", titles )   # the page's own collation, which Python's sorted() does not share
    assert titles == in_page
    assert accordion.locator( "[data-testid=jobs-disclose][aria-expanded=true]" ).count() == 0
    assert accordion.locator( ":scope > [data-testid=jobs-item] > [data-testid=jobs-panel]:visible" ).count() == 0
    assert summaries and all( a.startswith( "Bearer " ) for a in summaries ), "the summary request must carry the login token"


def test_the_section_lives_in_the_client_and_is_not_a_page_of_its_own( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    _open( page, client )
    assert page.locator( client[ "section" ] ).count() == 1
    assert page.get_by_test_id( "nav-jobs-link" ).count() == 0, "the nav bar must not carry a Jobs page link"
    resp = page.request.get( f"{BASE_URL}/app/jobs", max_redirects=0 )
    assert resp.status == 404, f"/app/jobs must be gone, saw {resp.status}"


def test_the_toolbar_button_hides_and_shows_the_section( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    _open( page, client )
    section, button = page.locator( client[ "section" ] ), page.get_by_test_id( client[ "toolbar" ] )
    assert section.is_visible() and "active" in ( button.get_attribute( "class" ) or "" )
    if client is CLIENTS[ "legacy" ]:
        # Row 61070c08: the legacy toolbar binds its handlers after init()'s awaits, later than the jobs rows appear.
        page.locator( "#section-toolbar[data-bound=true]" ).wait_for( state="attached", timeout=20_000 )
    button.click()
    section.wait_for( state="hidden", timeout=5_000 )
    button.click()
    section.wait_for( state="visible", timeout=5_000 )


def test_the_refresh_button_asks_the_summary_door_again( logged_in_page, client ):
    page = logged_in_page
    _, summaries = _stub( page )
    _open( page, client )
    before = len( summaries )
    page.get_by_test_id( client[ "refresh" ] ).click()
    page.wait_for_timeout( 500 )
    assert len( summaries ) == before + 1
    assert page.locator( f"{client[ 'accordion' ]} > [data-testid=jobs-item]" ).count() == 24


def test_the_duplicate_check_line_and_its_second_line_read_as_the_design_shows_them( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    item = _dup( _open( page, client ) )
    toggle = item.get_by_test_id( "jobs-disclose" )
    assert item.get_by_test_id( "jobs-badge" ).inner_text() == "FAILING · BEHIND"
    assert item.get_by_test_id( "jobs-last-run" ).inner_text() == "19:31 failed (stale_branch)"
    toggle.click()
    assert toggle.get_attribute( "aria-expanded" ) == "true"
    panel = item.get_by_test_id( "jobs-panel" )
    panel.wait_for( state="visible", timeout=5_000 )
    assert panel.get_by_test_id( "jobs-fig-clears" ).inner_text() == "Clears: never at this rate"
    assert panel.get_by_test_id( "cron-schedule" ).inner_text() == "cron 0 10-22 * * *"
    toggle.click()
    assert toggle.get_attribute( "aria-expanded" ) == "false"
    assert panel.is_hidden()


def test_run_now_posts_once_with_the_login_token_and_shows_the_outcome( logged_in_page, client ):
    page = logged_in_page
    runs, _ = _stub( page )
    item = _dup( _open( page, client ) )
    item.get_by_test_id( "jobs-disclose" ).click()
    item.get_by_test_id( "jobs-run-now" ).dblclick()
    item.get_by_test_id( "jobs-run-status" ).filter( has_text="pid 4242" ).wait_for( timeout=5_000 )
    assert len( runs ) == 1, f"a double click on a disabled button is one post; saw {len( runs )}"
    assert runs[ 0 ][ "method" ] == "POST" and runs[ 0 ][ "url" ].endswith( "/api/jobs/duplicate-check/run" )
    assert runs[ 0 ][ "auth" ].startswith( "Bearer " )


def test_a_refused_run_says_why_and_leaves_the_button_usable( logged_in_page, client ):
    page = logged_in_page
    runs, _ = _stub( page, run_status=409, run_body={ "status": "refused", "reason": "lock_held" } )
    item = _dup( _open( page, client ) )
    item.get_by_test_id( "jobs-disclose" ).click()
    button = item.get_by_test_id( "jobs-run-now" )
    button.click()
    item.get_by_test_id( "jobs-run-status" ).filter( has_text="run lock is held" ).wait_for( timeout=5_000 )
    assert button.is_enabled()
    assert len( runs ) == 1


def test_a_login_that_is_not_the_operator_sees_no_run_now_button( logged_in_page, client ):
    page = logged_in_page
    runs, _ = _stub( page, operator=False )
    accordion = _open( page, client )
    item = _dup( accordion )
    item.get_by_test_id( "jobs-disclose" ).click()
    item.get_by_test_id( "jobs-panel" ).wait_for( state="visible", timeout=5_000 )
    assert accordion.get_by_test_id( "jobs-run-now" ).count() == 0
    assert runs == [ ]


def test_a_job_that_cannot_run_by_hand_offers_no_run_now_button( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    arbiter = _open( page, client ).locator( "[data-testid=jobs-item][data-job=fleet-arbiter]" )
    arbiter.get_by_test_id( "jobs-disclose" ).click()
    arbiter.get_by_test_id( "jobs-panel" ).wait_for( state="visible", timeout=5_000 )
    assert arbiter.get_by_test_id( "jobs-run-now" ).count() == 0
    assert arbiter.get_by_test_id( "jobs-last-run" ).inner_text() == "up (lupin-arbiter-app.service)"
