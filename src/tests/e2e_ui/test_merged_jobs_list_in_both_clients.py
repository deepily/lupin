"""
E2E: one merged jobs list in both web clients.

This merges the Background Jobs and Scheduled Jobs accordions. There is one row per service. The
first line holds Service, Status, Last run and Last finished, a ⋯ button and a 📋. The ⋯ opens a second line
(the Scan, Fix and Clears figures, and the job's on/off switch) and a third (Run now and the targets). The
long text is behind the 📋. Each test runs once per client, against the real served page, script and login.

Tests 1, 2, 4 and 5 stub the two read doors, so the rows are known. Test 3 uses the real doors. The flip is
the real PUT, and it lands in the scratch copy of the configuration file, which the test then reads. It reuses
the scratch fixture of test_cron_jobs_section_in_both_clients.py. That fixture refuses to run unless the server
was created with LUPIN_CRON_SWITCH_INI naming a copy, so no real job is flipped.

No test here touches a GPU. The 📋 opens the tooltip in the vertical layout and the Reading Pane in the
horizontal one. The helper below reads whichever opened.

Venue: the scheduled :8000 E2E UI suite. The multiplexer bundle must be built in the served tree
with npm run build, or the multiplexer pane never mounts.
"""

# Row c80ef763: the merged jobs list.
from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import BASE_URL
from .test_cron_jobs_section_in_both_clients import scratch_ini, _on_disk, PAINT_MS    # noqa: F401  (scratch_ini is a fixture)

FIXTURE = json.loads( ( Path( __file__ ).resolve().parents[1] / "fixtures" / "jobs" / "jobs-summary.fixture.json" ).read_text( encoding="utf-8" ) )

CLIENTS = {
    "legacy"      : { "url": "/app/notifications?classic=1", "list": "#background-jobs-container", "count": "background-jobs-count" },
    "multiplexer" : { "url": "/app/multiplexer",             "list": "#background-jobs-pane [data-testid=jobs-accordion]", "count": "multiplexer-background-jobs-count" },
}

CRON_ROW = { "schedule": "cron 0 10-22 * * *", "key": "k", "enabled": True, "honoured": True, "drift": False, "last_changed_by": None, "last_changed_at": None }
STUBBED_SWITCHES = {
    "caller_is_admin": True,
    "jobs": [
        { **CRON_ROW, "job": "duplicate-check", "title": "Duplicate check" },
        { **CRON_ROW, "job": "fleet-arbiter",   "title": "Fleet arbiter (:8001)", "alarm": True, "reads": "tick" },
        { **CRON_ROW, "job": "reporting-off",   "title": "Reporting off", "enabled": False },     # a switch the summary does not report on
    ],
}


@pytest.fixture( params=list( CLIENTS ) )
def client( request ):
    """The client under test: its address and the selectors of its own list."""
    return CLIENTS[ request.param ]


def _stub( page ):
    """Stub the summary door and the switch list door."""
    page.route( "**/api/jobs/summary*", lambda route: route.fulfill( status=200, content_type="application/json", body=json.dumps( { **FIXTURE, "caller_is_operator": True } ) ) )
    page.route( "**/api/cron-jobs", lambda route: route.fulfill( status=200, content_type="application/json", body=json.dumps( STUBBED_SWITCHES ) )
                if route.request.method == "GET" else route.continue_() )


def _row( page, client, job ):
    return page.locator( f"{client[ 'list' ]} > [data-testid=jobs-item][data-job={job}]" )


def _open( page, client, job="duplicate-check" ):
    page.goto( f"{BASE_URL}{client[ 'url' ]}" )
    row = _row( page, client, job )
    row.wait_for( state="visible", timeout=PAINT_MS )
    return row


def _abstract_text( page ):
    """Read the text the 📋 opened, in the tooltip or the Reading Pane."""
    page.wait_for_function(
        "() => { const t = document.getElementById( 'abstract-tooltip' ); return ( t && t.classList.contains( 'visible' ) ) || !!document.querySelector( '.content-shell.pane-open' ); }",
        timeout=PAINT_MS,
    )
    return page.evaluate(
        "() => { const t = document.getElementById( 'abstract-tooltip' );"
        " if ( t && t.classList.contains( 'visible' ) ) return t.querySelector( '.abstract-tooltip-content' ).innerText;"
        " const p = document.getElementById( 'content-pane' ); return p ? p.innerText : ''; }"
    )


def test_the_first_line_is_one_clean_line_per_service( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    item = _open( page, client )
    items = page.locator( f"{client[ 'list' ]} > [data-testid=jobs-item]" )
    assert items.count() == 24, "the 23 reported jobs and the one switch the summary does not report on"
    line = item.get_by_test_id( "jobs-line" )
    for testid in ( "jobs-title", "jobs-badge", "jobs-last-run", "jobs-last-finished", "jobs-disclose", "jobs-abstract" ):
        assert line.get_by_test_id( testid ).count() == 1, testid
    assert page.locator( f"{client[ 'list' ]} [data-testid=jobs-scan-cell], {client[ 'list' ]} [data-testid=jobs-fix-cell], {client[ 'list' ]} [data-testid=jobs-clears-cell]" ).count() == 0
    heads = page.locator( f"{client[ 'list' ]} [data-testid=jobs-header] [role=columnheader]" ).all_inner_texts()
    assert [ h.split( " " )[ 0 ] for h in heads ] == [ "", "", "Service", "Status", "Last", "Last", "" ], heads
    assert "Scan" not in " ".join( heads ) and "Fix" not in " ".join( heads ) and "Clears" not in " ".join( heads )
    assert page.get_by_test_id( "cron-jobs-container" ).count() == 0, "there is no separate Scheduled Jobs list"
    assert page.get_by_test_id( "multiplexer-section-toolbar-cron-jobs" ).count() == 0


def test_the_hamburger_opens_lines_2_and_3( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    item = _open( page, client )
    toggle, panel = item.get_by_test_id( "jobs-disclose" ), item.get_by_test_id( "jobs-panel" )
    assert toggle.get_attribute( "aria-expanded" ) == "false" and panel.is_hidden()
    toggle.click()
    panel.wait_for( state="visible", timeout=5_000 )
    assert toggle.get_attribute( "aria-expanded" ) == "true"
    line2, line3 = item.get_by_test_id( "jobs-line2" ), item.get_by_test_id( "jobs-line3" )
    assert line2.is_visible() and line3.is_visible()
    assert line2.get_by_test_id( "jobs-fig-scan" ).inner_text() == "Scan: 2,124 ▲"
    assert line2.get_by_test_id( "jobs-fig-fix" ).inner_text() == "Fix: unfiled 107 ▲"
    assert line2.get_by_test_id( "jobs-fig-clears" ).inner_text() == "Clears: never at this rate"
    assert line2.get_by_test_id( "cron-state" ).inner_text() == "ON"
    assert line2.get_by_test_id( "cron-flip" ).inner_text() == "Turn off"
    assert line3.get_by_test_id( "jobs-run-now" ).count() == 1
    toggle.click()
    assert toggle.get_attribute( "aria-expanded" ) == "false" and panel.is_hidden()


def test_a_switch_flip_from_line_2_changes_the_ini_file_and_the_row_stays_open( admin_page, scratch_ini, client ):
    page = admin_page          # real doors: nothing is stubbed, the flip is the real PUT into the scratch copy of the file
    item = _open( page, client )
    item.get_by_test_id( "jobs-disclose" ).click()
    line2 = item.get_by_test_id( "jobs-line2" )
    line2.wait_for( state="visible", timeout=PAINT_MS )
    state, flip = line2.get_by_test_id( "cron-state" ), line2.get_by_test_id( "cron-flip" )
    assert state.inner_text() == "ON" and flip.is_enabled() and _on_disk( scratch_ini ) == "true"
    flip.click()
    page.wait_for_function( "( el ) => el.textContent === 'OFF'", arg=state.element_handle(), timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "false", "the page said OFF but the file did not change"
    assert item.get_by_test_id( "jobs-panel" ).is_visible(), "the row the reader flipped from stays open after its repaint"
    assert item.get_by_test_id( "jobs-line2" ).get_by_test_id( "cron-flip" ).inner_text() == "Turn on"
    item.get_by_test_id( "jobs-line2" ).get_by_test_id( "cron-flip" ).click()
    page.wait_for_function( "( sel ) => document.querySelector( sel ).textContent === 'ON'",
                            arg=f"{client[ 'list' ]} > [data-testid=jobs-item][data-job=duplicate-check] [data-testid=cron-state]", timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "true"


def test_the_clipboard_emoji_opens_the_abstract_and_the_long_text_is_not_in_the_list( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    item = _open( page, client )
    list_text = page.locator( client[ "list" ] ).inner_text()
    for heading in ( "Reasons", "Last attempts", "Not reported" ):
        assert heading not in list_text, f"{heading!r} is behind the 📋 now, not in the list"
    item.get_by_test_id( "jobs-abstract" ).click()
    text = _abstract_text( page )
    for expected in ( "Duplicate check", "Reasons", "Last attempts", "Scan debt", "Fix debt", "Schedule", "People", "Not reported" ):
        assert expected in text, f"{expected!r} missing from the abstract: {text[ :300 ]!r}"
    assert "Open the detail page" in text, "the detail link is carried by the abstract"


def test_a_switch_the_summary_does_not_report_on_still_gets_its_own_row( logged_in_page, client ):
    page = logged_in_page
    _stub( page )
    item = _open( page, client, "reporting-off" )
    assert item.get_by_test_id( "jobs-badge" ).inner_text() == "NOT REPORTING"
    item.get_by_test_id( "jobs-disclose" ).click()
    assert item.get_by_test_id( "cron-state" ).inner_text() == "OFF"
    assert item.get_by_test_id( "cron-flip" ).inner_text() == "Turn on"
