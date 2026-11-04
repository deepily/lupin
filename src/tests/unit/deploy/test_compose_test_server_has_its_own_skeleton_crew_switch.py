"""
The :8000 server flips its own copy of the configuration file; :7999 keeps the real one.

The skeleton crew switch is a key in src/conf/lupin-app.ini.
The test service mounts the same ./src as the dev service.
Without an override, a flip on :8000 writes the file that :7999 reads.
The launcher and every Stop hook read it too.
The integration test would then put the real fleet on skeleton crew.

This pins three things in the compose file.
The test service names a test-only file inside the flow-ratio mount, and no other service does.
Neither service moves the write lock, so writes to the real file from both take the same lock.

Venue: :7999 (unit, static, no docker).
"""

import os

import yaml

import cosa.utils.util as cu

INI_KEY  = "LUPIN_SKELETON_CREW_INI"
LOCK_KEY = "LUPIN_CONFIG_LOCK_DIR"
FLOW_KEY = "LUPIN_FLOW_RATIO_DIR"


def _service( name ):
    with open( os.path.join( cu.get_project_root(), "docker-compose.yml" ), encoding="utf-8" ) as f:
        return yaml.safe_load( f )[ "services" ][ name ]


def _env( name ):
    env = _service( name )[ "environment" ]
    return env if isinstance( env, dict ) else dict( item.split( "=", 1 ) for item in env )


def _flow_ratio_source( name ):
    """The host folder a service mounts at its flow-ratio target."""
    target = _env( name )[ FLOW_KEY ]
    for volume in _service( name )[ "volumes" ]:
        if isinstance( volume, dict ):
            if volume.get( "target" ) == target:
                return volume[ "source" ]
        elif volume.split( ":" )[ 1 ] == target:
            return volume.split( ":" )[ 0 ]
    raise AssertionError( f"{name} mounts nothing at {target}" )


def test_the_test_server_flips_a_test_only_file_inside_the_flow_ratio_mount():
    env  = _env( "lupin-rest-test" )
    path = env[ INI_KEY ]
    assert os.path.dirname( path ) == env[ FLOW_KEY ], "it must live in the mounted folder"
    assert os.path.basename( path ) != "lupin-app.ini", "that name is the real configuration file"
    assert path.endswith( ".test.ini" )


def test_the_dev_server_keeps_the_real_file():
    assert INI_KEY not in _env( "lupin-rest-dev" ), \
        "setting it on :7999 would detach the real switch from the launcher and the hook"


def test_neither_server_moves_the_write_lock():
    for name in ( "lupin-rest-dev", "lupin-rest-test" ):
        assert LOCK_KEY not in _env( name ), f"{name} would take a different lock for the real file"


def test_both_servers_take_the_lock_in_the_same_host_folder():
    dev  = "lupin-rest-dev"
    test = "lupin-rest-test"
    assert _env( dev )[ FLOW_KEY ] == _env( test )[ FLOW_KEY ]
    assert _flow_ratio_source( dev ) == _flow_ratio_source( test )
