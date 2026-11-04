"""
The :8000 test container must receive the admin credentials the smoke helpers read.

The smoke helpers sign in as an admin because the websocket debug route is admin-only. They read
the credentials from the environment, and the suite runs inside the `lupin-rest-test` container.
The compose file forwarded only the interactive-mock-jobs pair, so every admin-dependent smoke
test raised a RuntimeError there and the smoke tier stayed red.
"""

import pathlib
import re

import yaml

ROOT         = pathlib.Path( __file__ ).resolve().parents[ 3 ]
COMPOSE      = ROOT / "docker-compose.yml"
SMOKE_READER = ROOT / "src" / "tests" / "smoke" / "utilities" / "embedded_proxy.py"
TEST_SERVICE = "lupin-rest-test"


def _admin_names_the_smoke_reader_uses():
    """The LUPIN_TEST_ADMIN_* names that embedded_proxy.py reads from os.environ."""
    return set( re.findall( r'os\.environ\.get\(\s*"(LUPIN_TEST_ADMIN_\w+)"', SMOKE_READER.read_text() ) )


def _test_service_environment():
    return yaml.safe_load( COMPOSE.read_text() )[ "services" ][ TEST_SERVICE ][ "environment" ]


def test_the_reader_is_found_and_needs_exactly_an_email_and_a_password():
    """Control: the scan finds the two names, so an empty scan cannot pass the next test."""
    assert _admin_names_the_smoke_reader_uses() == { "LUPIN_TEST_ADMIN_EMAIL", "LUPIN_TEST_ADMIN_PASSWORD" }


def test_the_environment_reader_finds_a_name_known_to_be_forwarded():
    """Control: the compose reader sees a pair that was already forwarded."""
    env = _test_service_environment()
    assert "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" in env


def test_the_test_service_forwards_every_admin_name_the_smoke_reader_uses():
    """Each name is an environment entry of the test service, taken from the same shell name."""
    env = _test_service_environment()
    for name in sorted( _admin_names_the_smoke_reader_uses() ):
        assert name in env, f"{TEST_SERVICE} does not forward {name}"
        assert str( env[ name ] ).startswith( "${" + name ), f"{name} is not taken from the shell variable of that name: {env[ name ]!r}"
