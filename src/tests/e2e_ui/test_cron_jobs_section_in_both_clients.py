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

from cosa.rest import cron_job_switches as switches
from lupin_mcp import fleet_cap_ini_io as ini_io

from .conftest import BASE_URL

REAL_INI    = os.path.join( os.environ.get( "LUPIN_ROOT", "/var/lupin" ), "src", "conf", "lupin-app.ini" )
SERVER_INI  = os.environ.get( switches.INI_OVERRIDE_ENV )     # captured at import: what the server was created with
JOB         = "duplicate-check"
KEY         = switches.switch_key( JOB )
PAINT_MS    = 20_000

CLIENTS = {
    "legacy"      : { "url": "/app/notifications?classic=1", "list": "#cron-jobs-container" },
    "multiplexer" : { "url": "/app/multiplexer",             "list": "#cron-jobs-pane [data-testid=cron-jobs-container]" },
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
    ini_io.write_bool_to_disk( SERVER_INI, KEY, True )
    yield SERVER_INI
    ini_io.write_bool_to_disk( SERVER_INI, KEY, True )


def _on_disk( path ):
    return ini_io.read_value_from_disk( path, KEY ).strip().lower()


def _open( page, client ):
    page.goto( f"{BASE_URL}{client[ 'url' ]}" )
    row = page.locator( f"{client[ 'list' ]} [data-testid=cron-item][data-job={JOB}]" )
    row.wait_for( state="visible", timeout=PAINT_MS )
    return row


def test_an_admin_sees_an_enabled_toggle_and_a_click_flips_the_ini_value( admin_page, scratch_ini, client ):
    row    = _open( admin_page, client )
    toggle = row.get_by_test_id( "cron-flip" )
    state  = row.get_by_test_id( "cron-state" )
    assert state.inner_text() == "ON"
    assert toggle.is_enabled(), "an admin must be able to flip a job that reads its switch"
    assert toggle.inner_text() == "Turn off"
    assert _on_disk( scratch_ini ) == "true"

    toggle.click()
    admin_page.wait_for_function( "( el ) => el.textContent === 'OFF'", arg=state.element_handle(), timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "false", "the page said OFF but the file did not change"
    assert toggle.inner_text() == "Turn on"
    assert row.get_by_test_id( "cron-changed" ).inner_text() != "not reported", "a flip must record who and when"

    toggle.click()
    admin_page.wait_for_function( "( el ) => el.textContent === 'ON'", arg=state.element_handle(), timeout=PAINT_MS )
    assert _on_disk( scratch_ini ) == "true"


def test_a_flip_in_one_page_reaches_a_second_open_page_without_a_reload( admin_page, scratch_ini, client ):
    first   = _open( admin_page, client )
    second  = admin_page.context.new_page()
    other   = _open( second, client )
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
