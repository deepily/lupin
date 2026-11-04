"""
The :8000 server gets a test-only heartbeat poke switch file; :7999 keeps the real one.

Measured 2026-10-02: test_poke_mute_switch's own read_poke_mute() returned set_by "(setup)" while
the server answered with the admin, because the suite's isolation fixture points the test process
at a tmp file and the server wrote the shared flow-ratio file. The test's clicks therefore moved
the FLEET's real switch (the Stop hook on the host reads that file), and its restore wrote to the
tmp file, so the fleet stayed muted.

This pins the fix's two ends in the compose file: the test service names a test-only file inside
the flow-ratio mount, and no other service does.

Venue: :7999 (unit, static, no docker).
"""

import os

import yaml

import cosa.utils.util as cu

KEY = "LUPIN_HEARTBEAT_POKE_MUTE_FILE"


def _env( service ):
    with open( os.path.join( cu.get_project_root(), "docker-compose.yml" ), encoding="utf-8" ) as f:
        env = yaml.safe_load( f )[ "services" ][ service ][ "environment" ]
    return env if isinstance( env, dict ) else dict( item.split( "=", 1 ) for item in env )


def test_the_test_server_writes_a_test_only_file_inside_the_flow_ratio_mount():
    env  = _env( "lupin-rest-test" )
    path = env[ KEY ]
    assert os.path.dirname( path ) == env[ "LUPIN_FLOW_RATIO_DIR" ], "it must live in the mounted folder"
    assert os.path.basename( path ) != "heartbeat-poke-mute.json", "that name is the fleet's real switch"
    assert path.endswith( ".test.json" )


def test_the_dev_server_keeps_the_real_switch():
    assert KEY not in _env( "lupin-rest-dev" ), "setting it on :7999 would detach the real switch from the host hook"
