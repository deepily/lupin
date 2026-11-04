"""
Both rest services must mount the reuse-review folder read-only and name it.

The resident candidate search confines a request's vectors folder under LUPIN_REUSE_REVIEW_DATA_ROOT.
The caller sends a host path, so the folder must be mounted at that same path, and the variable must
name the mounted path. The declaration is checked here; whether a container was recreated to pick
it up is not (a restart keeps the old mounts and env).

Venue: :7999-eligible, parses one yaml file, no server, no network.
"""
import pytest

from tests.unit.test_flow_ratio_mount_invariants import _load, _rest_services

COMPOSE  = "docker-compose.yml"
ENV_KEY  = "LUPIN_REUSE_REVIEW_DATA_ROOT"
HOST_DIR = "/mnt/DATA01/include/www.deepily.ai/projects-data/lupin/reuse-review"
SERVICES = _rest_services( _load( COMPOSE ), COMPOSE )


def test_the_population_is_the_dev_and_the_test_server():
    assert sorted( SERVICES ) == [ "lupin-rest-dev", "lupin-rest-test" ]


@pytest.mark.parametrize( "name", sorted( SERVICES ) )
def test_the_service_mounts_the_folder_read_only_at_the_hosts_own_path( name ):
    mounts = [ v for v in SERVICES[ name ][ "volumes" ] if isinstance( v, str ) and HOST_DIR in v ]
    assert mounts == [ f"{HOST_DIR}:{HOST_DIR}:ro" ]


@pytest.mark.parametrize( "name", sorted( SERVICES ) )
def test_the_variable_names_the_mounted_path_and_not_another( name ):
    env    = SERVICES[ name ][ "environment" ]
    target = [ v.split( ":" )[ 1 ] for v in SERVICES[ name ][ "volumes" ] if isinstance( v, str ) and v.startswith( HOST_DIR ) ]
    assert ENV_KEY in env and target == [ HOST_DIR ] and env[ ENV_KEY ] == target[ 0 ]
