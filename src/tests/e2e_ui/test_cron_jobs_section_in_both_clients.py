"""
E2E: the scheduled-jobs accordion is a section of both web clients.

Each test runs once per client, against the real served page, script, login and PUT. Nothing is stubbed:
the flip goes through PUT /api/cron-jobs/{job}/enabled and lands in the INI file the server reads.

The server writes a scratch copy of the configuration file, not the real one.
docker-compose.yml gives the :8000 container LUPIN_CRON_SWITCH_INI. It names that copy in the flow-ratio folder.
The flip never touches the file the cron jobs on the host read.
This module captures the variable when it is imported, before any fixture can replace it.
It seeds the copy from the real file on first use.
It refuses to run when the variable is unset or names the real file.
The container must be created with the variable (`up -d --force-recreate lupin-rest-test`).
A server without it would flip a real job.

Assertions read the scratch file directly as well as the page, so a toggle that repainted without
writing would fail.

Venue: the scheduled :8000 E2E UI suite. The multiplexer bundle must be built in the served tree
with npm run build, or the multiplexer pane never mounts.
"""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import expect

from cosa.rest import cron_job_switches as switches
from lupin_mcp import fleet_cap_ini_io as ini_io

from .conftest import BASE_URL

REAL_INI    = os.path.join( os.environ.get( "LUPIN_ROOT", "/var/lupin" ), "src", "conf", "lupin-app.ini" )
SERVER_INI  = os.environ.get( switches.INI_OVERRIDE_ENV )     # captured at import: what the server was created with
JOB         = "duplicate-check"
KEY         = switches.switch_key( JOB )
ALARM_JOB   = "fleet-arbiter"
ALARM_KEY   = switches.switch_key( ALARM_JOB )
PAINT_MS    = 20_000

CLIENTS = {
    "legacy"      : { "url": "/app/notifications?classic=1", "list": "#background-jobs-container" },
    "multiplexer" : { "url": "/app/multiplexer",             "list": "#background-jobs-pane [data-testid=jobs-accordion]" },
}


@pytest.fixture( params=list( CLIENTS ) )
def client( request ):
    """The client under test: its address and the selector of its own list."""
    return CLIENTS[ request.param ]


@pytest.fixture
def scratch_ini():
    """
    The server's scratch copy of the configuration file, with the job switched on.

    Requires:
        - the server was created with LUPIN_CRON_SWITCH_INI naming a file other than the real one

    Ensures:
        - yields the path; the job's key reads true and the attribution record is empty at the start
        - the key is put back to true afterwards, whatever the test did
        - never writes the real configuration file

    Raises:
        - pytest.fail when the variable was unset or names the real file when this module was imported
    """
    if not SERVER_INI:
        pytest.fail( f"{switches.INI_OVERRIDE_ENV} is not set, so a flip would write the real configuration file "
                     f"and switch a real job. Recreate the test service: up -d --force-recreate lupin-rest-test." )
    if os.path.realpath( SERVER_INI ) == os.path.realpath( REAL_INI ):
        pytest.fail( f"{switches.INI_OVERRIDE_ENV} names the real configuration file. Refusing to run." )
    if not os.path.exists( SERVER_INI ):
        with open( REAL_INI, "rb" ) as source, open( SERVER_INI, "wb" ) as target: target.write( source.read() )
    record = f"{SERVER_INI}.cron-state.json"
    if os.path.exists( record ): os.remove( record )
    for key in ( KEY, ALARM_KEY ): ini_io.write_bool_to_disk( SERVER_INI, key, True )
    yield SERVER_INI
    for key in ( KEY, ALARM_KEY ): ini_io.write_bool_to_disk( SERVER_INI, key, True )


def _on_disk( path ):
    return ini_io.read_value_from_disk( path, KEY ).strip().lower()


def _show( page, client, job=JOB ):
    """Open the job's second line with the ⋯ and return its switch."""
    item = page.locator( f"{client[ 'list' ]} [data-testid=jobs-item][data-job={job}]" )
    item.wait_for( state="visible", timeout=PAINT_MS )
    toggle = item.get_by_test_id( "jobs-disclose" )
    if toggle.get_attribute( "aria-expanded" ) != "true": toggle.click()
    row = item.locator( "[data-testid=cron-item]" )
    row.wait_for( state="visible", timeout=PAINT_MS )
    return row


def _open( page, client ):
    page.goto( f"{BASE_URL}{client[ 'url' ]}" )
    return _show( page, client )


def test_an_admin_sees_an_enabled_toggle_and_a_click_flips_the_ini_value( admin_page, scratch_ini, client ):
    row    = _open( admin_page, client )
    toggle = row.get_by_test_id( "cron-flip" )
    state  = row.get_by_test_id( "cron-state" )
    assert state.inner_text() == "ON"
    assert toggle.is_enabled(), "an admin must be able to flip a job that reads its switch"
    assert toggle.inner_text() == "Turn off"
    assert _on_disk( scratch_ini ) == "true"

    toggle.click()
    expect( state ).to_have_text( "OFF", timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "false", "the page said OFF but the file did not change"
    assert toggle.inner_text() == "Turn on"
    assert row.get_by_test_id( "cron-changed" ).inner_text() != "not reported", "a flip must record who and when"

    toggle.click()
    expect( state ).to_have_text( "ON", timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "true"


def test_a_flip_in_one_page_reaches_a_second_open_page_without_a_reload( admin_page, scratch_ini, client ):
    first   = _open( admin_page, client )
    second  = admin_page.context.new_page()
    other   = _open( second, client )                # opens its own second line: the frame repaints it in place
    assert other.get_by_test_id( "cron-state" ).inner_text() == "ON"
    first.get_by_test_id( "cron-flip" ).click()
    # The poll is 60 s; the socket frame is the only thing fast enough to move the second page inside this wait.
    second.wait_for_function(
        "( sel ) => document.querySelector( sel + ' [data-testid=cron-item][data-job=" + JOB + "] [data-testid=cron-state]' ).textContent === 'OFF'",
        arg=client[ "list" ], timeout=10_000,
    )
    assert _on_disk( scratch_ini ) == "false"
    second.close()


def test_a_user_who_is_not_an_admin_sees_the_switches_read_only( logged_in_page, scratch_ini, client ):
    row = _open( logged_in_page, client )
    assert row.get_by_test_id( "cron-state" ).inner_text() == "ON"
    assert row.get_by_test_id( "cron-flip" ).is_disabled()
    assert "Read-only" in logged_in_page.locator( f"{client[ 'list' ]} [data-testid=cron-note]" ).inner_text()
    assert _on_disk( scratch_ini ) == "true"


def test_on_a_drift_row_the_note_and_the_toggle_are_both_on_line_2( admin_page, scratch_ini, client ):
    row = _open( admin_page, client )
    row.get_by_test_id( "cron-flip" ).click()
    expect( row.get_by_test_id( "cron-state" ) ).to_have_text( "OFF", timeout=PAINT_MS )
    ini_io.write_bool_to_disk( scratch_ini, KEY, True )      # a hand edit the endpoint never recorded: the row now drifts
    row = _open( admin_page, client )
    drift = row.get_by_test_id( "cron-drift" )
    assert drift.is_visible(), "the file disagrees with the last recorded flip, so the row must say so"
    assert row.get_by_test_id( "cron-flip" ).is_visible(), "the toggle stays reachable on a drift row"
    line2 = row.locator( "xpath=ancestor::*[@data-testid='jobs-line2']" )
    assert line2.count() == 1, "the switch, and so its drift note, sits on line 2 of the job's row"
    first_line = row.locator( "xpath=ancestor::*[@data-testid='jobs-item']" ).get_by_test_id( "jobs-line" )
    assert first_line.get_by_test_id( "cron-drift" ).count() == 0, "the first line stays one clean line"


def test_turning_off_an_alarm_job_takes_a_confirming_click( admin_page, scratch_ini, client ):
    admin_page.goto( f"{BASE_URL}{client[ 'url' ]}" )
    row = _show( admin_page, client, ALARM_JOB )
    toggle = row.get_by_test_id( "cron-flip" )
    toggle.click()
    assert toggle.inner_text() == "Confirm: turn off"
    assert "silences what would report it" in row.get_by_test_id( "cron-error" ).inner_text()
    assert ini_io.read_value_from_disk( scratch_ini, ALARM_KEY ).strip().lower() == "true", "the first click must not write the file"
    toggle.click()
    expect( row.get_by_test_id( "cron-state" ) ).to_have_text( "OFF", timeout=PAINT_MS )
    assert ini_io.read_value_from_disk( scratch_ini, ALARM_KEY ).strip().lower() == "false"
