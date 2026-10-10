"""
Integration tests for the skeleton crew switch, driven against the real test server.

    GET /api/arbiter/fleet-size-cap        -> carries the `skeleton_crew` object.
    PUT /api/arbiter/skeleton-crew         -> admin login only, flips the switch.
    GET /api/heartbeat/poke-mute           -> names the `source` while the switch is on.

Venue: the test server on :8000 in monopolize mode, scheduled runs only. A flip writes the
test server's configuration file and tells its live sessions. So this is not eligible for
:7999 and must never be injected through a side door. Submit through the v2 test-suite submit.
The base URL comes from `LUPIN_TEST_BASE_URL`, default http://localhost:8000.

State: every test starts from the state the server was in. The `switch` fixture puts that
value back in a `finally`, whatever fails. A failed restore is itself a test error.

Credentials: none beyond the integration conftest's own. A service-account API key is seeded
in the test database. An admin user is registered there and given the admin role, both
through `clean_test_db`. The pytest process needs the database settings the conftest checks.
"""

import os
import secrets
import shutil
import uuid

import bcrypt
import pytest
import requests

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import UserRepository, ApiKeyRepository
from lupin_mcp import fleet_cap_ini_io, fleet_size_cap, skeleton_crew


BASE_URL      = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
CAP_URL       = f"{BASE_URL}/api/arbiter/fleet-size-cap"
SWITCH_URL    = f"{BASE_URL}/api/arbiter/skeleton-crew"
POKE_MUTE_URL = f"{BASE_URL}/api/heartbeat/poke-mute"

SKELETON_KEYS = { "on", "since", "set_by", "settings_mute_while_off" }

REAL_INI = os.path.join( os.environ.get( "LUPIN_ROOT", "/var/lupin" ), "src", "conf", "lupin-app.ini" )


def _test_ini():
    """
    The test-only copy of the configuration file, seeded from the real one on first use.

    Requires:
        - LUPIN_SKELETON_CREW_INI names a file other than the real configuration file

    Ensures:
        - returns the path of a file that holds the switch key and the cap keys
        - never writes the real configuration file

    Raises:
        - pytest.fail when the variable is unset or names the real file, because the server would
          then write the file the whole fleet reads
    """
    path = os.environ.get( skeleton_crew.INI_OVERRIDE_ENV )
    if not path:
        pytest.fail( f"{skeleton_crew.INI_OVERRIDE_ENV} is not set, so a flip would write the real "
                     f"configuration file and put the fleet on skeleton crew. Refusing to run." )
    if os.path.realpath( path ) == os.path.realpath( REAL_INI ):
        pytest.fail( f"{skeleton_crew.INI_OVERRIDE_ENV} names the real configuration file. Refusing to run." )
    if not os.path.exists( path ):
        shutil.copyfile( REAL_INI, path )
        fleet_cap_ini_io.write_bool_to_disk( path, skeleton_crew.SKELETON_CREW_KEY, False,
                                             insert_after=fleet_size_cap.FLEET_CEILING_KEY )
    return path


@pytest.fixture
def test_api_key( clean_test_db ):
    """A seeded service-account API key. It can read the switch and cannot flip it."""
    api_key  = "ck_live_" + secrets.token_urlsafe( 48 )
    key_hash = bcrypt.hashpw( api_key.encode( "utf-8" ), bcrypt.gensalt( rounds=12 ) ).decode( "utf-8" )
    email    = f"test-{uuid.uuid4()}@test.com"

    with get_db() as session:
        user = UserRepository( session ).create_user(
            email         = email,
            password_hash = "dummy_hash",
            roles         = [ "service_account" ],
        )
        user.email_verified = True
        user.is_active      = True
        key_obj = ApiKeyRepository( session ).create_key(
            user_id     = user.id,
            key_hash    = key_hash,
            description = "Skeleton crew switch integration test key",
        )
        key_id  = str( key_obj.id )
        user_id = str( user.id )

    yield { "api_key": api_key, "user_id": user_id, "key_id": key_id, "email": email }

    with get_db() as session:
        ApiKeyRepository( session ).delete( uuid.UUID( key_id ) )
        UserRepository( session ).delete( uuid.UUID( user_id ) )


def _key_headers( test_api_key ):
    """The header a Claude session sends: an API key and no login."""
    return { "X-API-Key": test_api_key[ "api_key" ] }


def _admin_headers( create_test_admin ):
    """The header an administrator's browser sends: a bearer token and no API key."""
    return { "Authorization": f"Bearer {create_test_admin[ 'access_token' ]}" }


def _read_switch( headers ):
    """The `skeleton_crew` object from the fleet dial, asserted to be there."""
    response = requests.get( CAP_URL, headers=headers, timeout=10 )
    assert response.status_code == 200, f"{response.status_code}: {response.text}"
    body = response.json()
    assert "skeleton_crew" in body, body
    return body[ "skeleton_crew" ]


def _put_switch( headers, on ):
    """PUT the switch and return the raw response, so a refusal can be asserted."""
    return requests.put( SWITCH_URL, json={ "on": on }, headers=headers, timeout=10 )


@pytest.fixture
def switch( test_api_key, create_test_admin ):
    """
    Record the found state, hand the test both credentials, and put it back.

    Ensures:
        - the found value of `on` is written back in a `finally`, whatever the test did
        - a restore that does not take is an error, not a quiet pass
    """
    reader = _key_headers( test_api_key )
    admin  = _admin_headers( create_test_admin )
    ini    = _test_ini()
    for sentinel in ( True, False ):
        fleet_cap_ini_io.write_bool_to_disk( ini, skeleton_crew.SKELETON_CREW_KEY, sentinel,
                                             insert_after=fleet_size_cap.FLEET_CEILING_KEY )
        seen = _read_switch( reader )[ "on" ]
        assert seen is sentinel, ( f"the server does not read {ini}: it answered {seen} after the "
                                   f"file was set to {sentinel}. Refusing to flip the real switch." )
    found = _read_switch( reader )[ "on" ]
    try:
        yield { "reader": reader, "admin": admin, "found": found }
    finally:
        restored = _put_switch( admin, found )
        assert restored.status_code == 200, f"restore refused: {restored.status_code}: {restored.text}"
        assert _read_switch( reader )[ "on" ] is found, "the switch was not put back to the state found"


class TestTheSwitchIsReadable:

    def test_the_fleet_dial_shows_the_skeleton_crew_object( self, switch ):
        """An API key reads the switch: the object, its four fields, and the dial it rides on."""
        response = requests.get( CAP_URL, headers=switch[ "reader" ], timeout=10 )
        assert response.status_code == 200, f"{response.status_code}: {response.text}"
        body = response.json()
        assert { "cap", "ceiling", "live", "skeleton_crew" } <= set( body ), sorted( body )
        crew = body[ "skeleton_crew" ]
        assert isinstance( crew, dict ), crew
        assert SKELETON_KEYS <= set( crew ), sorted( crew )
        assert isinstance( crew[ "on" ], bool ), crew


class TestOnlyAnAdministratorFlipsIt:

    def test_an_api_key_alone_is_refused_and_the_switch_does_not_move( self, switch ):
        """A manager's key answers 403 for the opposite value, and the whole object is unchanged."""
        before   = _read_switch( switch[ "reader" ] )
        response = _put_switch( switch[ "reader" ], not before[ "on" ] )
        assert response.status_code == 403, f"{response.status_code}: {response.text}"
        assert _read_switch( switch[ "reader" ] ) == before

    def test_no_credential_at_all_is_refused( self, switch ):
        """No header answers 401 or 403, never 200, and the switch does not move."""
        before   = _read_switch( switch[ "reader" ] )
        response = requests.put( SWITCH_URL, json={ "on": not before[ "on" ] }, timeout=10 )
        assert response.status_code in ( 401, 403 ), f"{response.status_code}: {response.text}"
        assert _read_switch( switch[ "reader" ] ) == before

    def test_an_administrator_flips_it_and_the_read_agrees( self, switch ):
        """On then off through the admin login, each time read back through the API key."""
        turned_on = _put_switch( switch[ "admin" ], True )
        assert turned_on.status_code == 200, f"{turned_on.status_code}: {turned_on.text}"
        assert turned_on.json()[ "skeleton_crew" ][ "on" ] is True
        crew = _read_switch( switch[ "reader" ] )
        assert crew[ "on" ] is True, crew
        assert isinstance( crew[ "set_by" ], str ) and crew[ "set_by" ], crew
        assert "unknown" not in crew[ "set_by" ], crew

        turned_off = _put_switch( switch[ "admin" ], False )
        assert turned_off.status_code == 200, f"{turned_off.status_code}: {turned_off.text}"
        assert _read_switch( switch[ "reader" ] )[ "on" ] is False

    def test_a_value_that_is_not_a_boolean_is_refused_and_changes_nothing( self, switch ):
        """A string is a 422 from the model, and the switch does not move."""
        before   = _read_switch( switch[ "reader" ] )
        response = requests.put( SWITCH_URL, json={ "on": "true" }, headers=switch[ "admin" ], timeout=10 )
        assert response.status_code == 422, f"{response.status_code}: {response.text}"
        assert _read_switch( switch[ "reader" ] ) == before


class TestThePokeMuteNamesItsSource:

    def test_the_poke_mute_reports_skeleton_crew_as_the_source_while_on( self, switch ):
        """
        With the switch on, the poke is muted and `source` names the switch.

        A fleet file mute that was already set shows as `both`. The expected word comes from
        what the file alone said first.
        """
        assert _put_switch( switch[ "admin" ], False ).status_code == 200
        quiet = requests.get( POKE_MUTE_URL, headers=switch[ "reader" ], timeout=10 )
        assert quiet.status_code == 200, f"{quiet.status_code}: {quiet.text}"
        file_alone = quiet.json()
        assert file_alone[ "source" ] in ( "none", "file" ), file_alone

        assert _put_switch( switch[ "admin" ], True ).status_code == 200
        muted = requests.get( POKE_MUTE_URL, headers=switch[ "reader" ], timeout=10 )
        assert muted.status_code == 200, f"{muted.status_code}: {muted.text}"
        expected = "both" if file_alone[ "source" ] == "file" else "skeleton_crew"
        assert muted.json()[ "muted" ] is True, muted.json()
        assert muted.json()[ "source" ] == expected, muted.json()

        assert _put_switch( switch[ "admin" ], False ).status_code == 200
        released = requests.get( POKE_MUTE_URL, headers=switch[ "reader" ], timeout=10 ).json()
        assert released[ "source" ] == file_alone[ "source" ], released
        assert released[ "muted" ] == file_alone[ "muted" ], released
