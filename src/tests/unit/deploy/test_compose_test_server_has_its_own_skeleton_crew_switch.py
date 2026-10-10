"""
The :8000 server flips its own copy of the configuration file; :7999 keeps the real one.

The skeleton crew switch is a key in src/conf/lupin-app.ini.
The test service mounts the same ./src as the dev service.
Without an override, a flip on :8000 writes the file that :7999 reads.
The launcher and every Stop hook read it too.
The integration test would then put the real fleet on skeleton crew.
The attribution record and the write lock follow the lock folder, which gets a test-only one.

This pins both ends in the compose file.
The test service names a test-only file and folder inside the flow-ratio mount.
No other service does.

Venue: :7999 (unit, static, no docker).
"""

import os

import yaml

import cosa.utils.util as cu

INI_KEY  = "LUPIN_SKELETON_CREW_INI"
LOCK_KEY = "LUPIN_CONFIG_LOCK_DIR"


def _env( service ):
    with open( os.path.join( cu.get_project_root(), "docker-compose.yml" ), encoding="utf-8" ) as f:
        env = yaml.safe_load( f )[ "services" ][ service ][ "environment" ]
    return env if isinstance( env, dict ) else dict( item.split( "=", 1 ) for item in env )


def test_the_test_server_flips_a_test_only_file_inside_the_flow_ratio_mount():
    env  = _env( "lupin-rest-test" )
    path = env[ INI_KEY ]
    assert os.path.dirname( path ) == env[ "LUPIN_FLOW_RATIO_DIR" ], "it must live in the mounted folder"
    assert os.path.basename( path ) != "lupin-app.ini", "that name is the real configuration file"
    assert path.endswith( ".test.ini" )


def test_the_test_server_keeps_its_record_and_lock_in_a_test_only_folder():
    env  = _env( "lupin-rest-test" )
    path = env[ LOCK_KEY ]
    assert os.path.dirname( path ) == env[ "LUPIN_FLOW_RATIO_DIR" ], "it must live in the mounted folder"
    assert path != env[ "LUPIN_FLOW_RATIO_DIR" ], "the flow-ratio folder itself holds the fleet's real record"


def test_the_dev_server_keeps_the_real_file_and_the_real_record():
    env = _env( "lupin-rest-dev" )
    assert INI_KEY not in env, "setting it on :7999 would detach the real switch from the launcher and the hook"
    assert LOCK_KEY not in env, "setting it on :7999 would move the real record away from the host hook"
