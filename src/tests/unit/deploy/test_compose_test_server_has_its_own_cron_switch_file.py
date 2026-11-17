"""
The :8000 server flips its own copy of the configuration file; :7999 keeps the real one.

The cron jobs on the host read `cron job <job> enabled` from src/conf/lupin-app.ini at every run.
The test service mounts the same ./src as the dev service.
Without an override, the E2E flip of a switch on :8000 would switch a real job off.

This pins three things in the compose file.
The test service names a test-only file inside the flow-ratio mount, and no other service does.
Neither service moves the write lock, so writes to the real file take the same lock.

Venue: :7999 (unit, static, no docker).
"""

import os

import yaml

import cosa.utils.util as cu
from cosa.rest import cron_job_switches as switches

INI_KEY  = switches.INI_OVERRIDE_ENV
LOCK_KEY = "LUPIN_CONFIG_LOCK_DIR"
FLOW_KEY = "LUPIN_FLOW_RATIO_DIR"


def _env( name ):
    with open( os.path.join( cu.get_project_root(), "docker-compose.yml" ), encoding="utf-8" ) as f:
        env = yaml.safe_load( f )[ "services" ][ name ][ "environment" ]
    return env if isinstance( env, dict ) else dict( item.split( "=", 1 ) for item in env )


def test_the_variable_is_the_one_the_resolver_reads():
    assert INI_KEY == "LUPIN_CRON_SWITCH_INI"


def test_the_test_server_flips_a_test_only_file_inside_the_flow_ratio_mount():
    env  = _env( "lupin-rest-test" )
    path = env[ INI_KEY ]
    assert os.path.dirname( path ) == env[ FLOW_KEY ], "it must live in the mounted folder"
    assert os.path.basename( path ) != "lupin-app.ini", "that name is the real configuration file"
    assert path.endswith( ".test.ini" )


def test_it_is_a_different_file_from_the_skeleton_crew_copy():
    env = _env( "lupin-rest-test" )
    assert env[ INI_KEY ] != env[ "LUPIN_SKELETON_CREW_INI" ], "two switches sharing one scratch file would share their keys"


def test_the_dev_server_keeps_the_real_file():
    assert INI_KEY not in _env( "lupin-rest-dev" ), "setting it on :7999 would detach the real switches from the cron jobs"


def test_neither_server_moves_the_write_lock():
    for name in ( "lupin-rest-dev", "lupin-rest-test" ):
        assert LOCK_KEY not in _env( name ), f"{name} would take a different lock for the real file"
