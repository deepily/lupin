"""
Unit tests for docker-compose.cloud-test.yml (GCP M1 VM deployment).

Guards the load-bearing invariants of the cloud-test compose so it can't
silently drift away from what the app actually requires — in particular the
Cloud SQL Auth Proxy unix-socket contract that database.py depends on.

Venue: :7999-eligible (pure YAML parse; no server, no DB, no network).

Requires:
    - docker-compose.cloud-test.yml exists at the project root
    - PyYAML available

Ensures:
    - the Cloud SQL Auth Proxy sidecar + shared socket volume are wired so the
      app's `?host=/cloudsql/<CONN>` URL (database.py) resolves
    - LUPIN_CLOUD_BACKED + Testing-GCS config block + mount-model bind are present
    - model-server stays pinned to cuda:0
"""

import os

import yaml
import pytest

import cosa.utils.util as cu


def _load_compose():
    path = cu.get_project_root() + "/docker-compose.cloud-test.yml"
    with open( path, "r" ) as f:
        return yaml.safe_load( f )


@pytest.fixture( scope="module" )
def compose():
    return _load_compose()


@pytest.fixture( scope="module" )
def services( compose ):
    return compose[ "services" ]


def test_compose_file_exists():
    path = cu.get_project_root() + "/docker-compose.cloud-test.yml"
    assert os.path.isfile( path ), f"missing cloud-test compose at {path}"


def test_cloud_sql_proxy_service_present( services ):
    assert "cloud-sql-proxy" in services, "Auth Proxy sidecar service missing"
    cmd = services[ "cloud-sql-proxy" ][ "command" ]
    assert any( "--unix-socket=/cloudsql" in c for c in cmd ), \
        "proxy must open the unix socket at /cloudsql"
    assert any( "CLOUD_SQL_CONNECTION_NAME" in c for c in cmd ), \
        "proxy command must reference the instance connection name"


def test_shared_cloudsql_socket_volume_in_both( compose, services ):
    # The named volume that carries the unix socket from proxy → app.
    assert "cloudsql-socket" in compose.get( "volumes", {} ), \
        "named cloudsql-socket volume must be declared"
    for svc in ( "cloud-sql-proxy", "lupin-rest" ):
        mounts = services[ svc ][ "volumes" ]
        assert any( m.startswith( "cloudsql-socket:/cloudsql" ) for m in mounts ), \
            f"{svc} must mount the shared socket at /cloudsql"


def test_database_url_socket_path_matches_proxy_mount( services ):
    # database.py builds `…?host=/cloudsql/<CONN>` — the in-container socket dir
    # MUST be /cloudsql for the app to find the proxy's socket. This couples the
    # two so a future rename of either side breaks this test, not production.
    rest_mounts = services[ "lupin-rest" ][ "volumes" ]
    socket_targets = [ m.split( ":" )[ 1 ] for m in rest_mounts if m.startswith( "cloudsql-socket:" ) ]
    assert "/cloudsql" in socket_targets, \
        "app must see the socket at /cloudsql (matches database.py host=/cloudsql/<CONN>)"


def test_lupin_rest_cloud_backed_flag( services ):
    env = services[ "lupin-rest" ][ "environment" ]
    # is_cloud_backed() gates SOLELY on this flag (database.py:32-51).
    assert str( env.get( "LUPIN_CLOUD_BACKED" ) ).lower() == "true", \
        "LUPIN_CLOUD_BACKED must be true for the Cloud SQL path"
    assert "CLOUD_SQL_CONNECTION_NAME" in env, "connection name env required"
    assert "Lupin:+Testing-GCS" in env[ "LUPIN_CONFIG_MGR_CLI_ARGS" ], \
        "cloud-test app must run the Testing-GCS config block"


def test_lupin_rest_mount_model_bind( services ):
    mounts = services[ "lupin-rest" ][ "volumes" ]
    assert any( m.startswith( "./src:/var/lupin/src" ) for m in mounts ), \
        "mount model requires bind-mounting the on-VM checkout's ./src"


def test_lupin_rest_depends_on_proxy_healthy( services ):
    dep = services[ "lupin-rest" ][ "depends_on" ][ "cloud-sql-proxy" ]
    assert dep[ "condition" ] == "service_healthy", \
        "app must wait for the proxy to be healthy before starting"


def test_model_server_pinned_to_gpu0( services ):
    env = services[ "lupin-model-server" ][ "environment" ]
    assert str( env.get( "CUDA_VISIBLE_DEVICES" ) ) == "0", \
        "Lupin models must always pin to GPU 0 (hard rule)"
    assert env.get( "LUPIN_MODEL_SERVER_DEVICE" ) == "cuda:0"
