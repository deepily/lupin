"""
Tests for the VM test-server overlay, its lupin-vm.sh verbs and refresh --vm.

gcloud is a stub on the path and logs its arguments. Its ssh call runs the remote command locally
against a scratch directory, with sudo and install as shims. Its secrets call answers a fake value.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT      = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
SCRIPT    = ROOT / "src" / "scripts" / "lupin-vm.sh"
REFRESH   = ROOT / "src" / "scripts" / "refresh-test-server.sh"
OVERLAY   = ROOT / "docker-compose.vm-test-overlay.yml"
BASE      = ROOT / "docker-compose.cloud-gpu.yml"
INIT_SQL  = ROOT / "src" / "scripts" / "sql" / "init-vm-test-db.sql"
VM_ENV    = "/mnt/lupin-data/lupin/cloud-gpu.env"
SECRETS   = "/etc/lupin/secrets"
FAKE      = "placeholder" + "-value_42"

GCLOUD = r'''#!/bin/bash
echo "$*" >> "$STUB_CALLS"
if [ "$1" = "secrets" ]; then
    name=""; for a in "$@"; do case "$a" in --secret=*) name="${a#--secret=}" ;; esac; done
    [ "$name" = "$STUB_SECRET_FAILS" ] && exit 1
    [ "$name" = "$STUB_SECRET_EMPTY" ] && { echo; exit 0; }
    [ "$name" = "$STUB_SECRET_BAD" ] && { printf '%s\n' "$STUB_BAD_VALUE"; exit 0; }
    printf '%s\n' "${STUB_SECRET}-$name"; exit 0
fi
if [ "$1" = "compute" ] && [ "$2" = "ssh" ]; then
    while [ $# -gt 0 ]; do [ "$1" = "--command" ] && { cmd="$2"; break; }; shift; done
    printf '\n@@CMD@@%s@@END@@\n' "$cmd" >> "$STUB_CALLS"
    cmd="${cmd//\/mnt\/lupin-data\/lupin\/cloud-gpu.env/$STUB_ENV}"
    cmd="${cmd//\/etc\/lupin\/secrets/$STUB_SECRETS}"
    [ -n "$STUB_RUN_REMOTE" ] && { bash -c "$cmd"; exit $?; }
fi
exit 0
'''
# sudo is a pass-through; install drops the root-only -o flag so a non-root test run can use it.
INSTALL = r'''#!/bin/bash
args=(); skip=0
for a in "$@"; do
    if [ "$skip" = 1 ]; then skip=0; continue; fi
    if [ "$a" = "-o" ]; then skip=1; continue; fi
    args+=( "$a" )
done
exec /usr/bin/install "${args[@]}"
'''


@pytest.fixture
def vm( tmp_path ):
    calls   = tmp_path / "calls.log"
    secrets = tmp_path / "secrets"
    env     = tmp_path / "cloud-gpu.env"
    for name, body in ( ( "gcloud", GCLOUD ), ( "install", INSTALL ),
                        ( "sudo", '#!/bin/bash\nexec "$@"\n' ),
                        ( "openssl", '#!/bin/bash\necho "$STUB_RAND"\n' ) ):
        ( tmp_path / name ).write_text( body )
        ( tmp_path / name ).chmod( 0o755 )

    def run( script, *args, project="proj-x", remote=False, stdin=None, **stub ):
        e = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ), "STUB_CALLS": str( calls ),
              "STUB_ENV": str( env ), "STUB_SECRETS": str( secrets ), "STUB_SECRET": FAKE, "STUB_RAND": "a1b2c3",
              "STUB_SECRET_FAILS": "", "STUB_SECRET_EMPTY": "", "STUB_SECRET_BAD": "", "STUB_BAD_VALUE": "",
              "STUB_RUN_REMOTE": "1" if remote else "" }
        e.update( { k.upper(): v for k, v in stub.items() } )
        if project is not None: e[ "LUPIN_GCP_PROJECT_ID" ] = project
        done = subprocess.run( [ "bash", str( script ), *args ], capture_output=True, text=True, env=e, input=stdin )
        return done, ( calls.read_text() if calls.exists() else "" )
    run.env, run.secrets, run.calls = env, secrets, calls
    run.path = f"{tmp_path}:{os.environ[ 'PATH' ]}"
    return run


def _ssh_command( calls ):
    """The --command argument of the last ssh call in the stub's log."""
    return calls.rsplit( "@@CMD@@", 1 )[ 1 ].split( "@@END@@", 1 )[ 0 ]


# ---------------------------------------------------------------- the overlay file

@pytest.fixture( scope="module" )
def overlay():
    return yaml.safe_load( OVERLAY.read_text() )


def test_the_overlay_adds_exactly_the_two_services_and_the_base_file_is_untouched( overlay ):
    assert sorted( overlay[ "services" ] ) == [ "lupin-pgvector-test", "lupin-rest-test" ]
    assert "lupin-rest-test" not in yaml.safe_load( BASE.read_text() )[ "services" ]


def test_the_test_server_listens_on_8000_as_uid_1001_with_the_host_gid_and_no_gpu( overlay ):
    svc = overlay[ "services" ][ "lupin-rest-test" ]
    assert svc[ "ports" ] == [ "8000:7999" ] and svc[ "user" ] == "1001:1001"
    assert svc[ "group_add" ] == [ "${LUPIN_BRIDGE_GID:?set LUPIN_BRIDGE_GID (host gid owning ~/.claude/sessions)}" ]
    assert "1002" not in str( svc[ "group_add" ] )
    assert "deploy" not in svc and "driver: nvidia" not in OVERLAY.read_text()
    assert svc[ "extra_hosts" ] == [ "host.docker.internal:host-gateway" ]
    assert svc[ "environment" ][ "LUPIN_MODEL_SERVER_URL" ].startswith( "${LUPIN_MODEL_SERVER_URL:?" )


def test_the_image_is_the_registry_image_not_a_local_candidate_tag( overlay ):
    image = overlay[ "services" ][ "lupin-rest-test" ][ "image" ]
    assert image == "${LUPIN_TEST_IMAGE:-${LUPIN_IMAGE:-lupin:1.1.0}}" and "candidate" not in image


def test_the_app_reaches_the_local_pgvector_and_never_cloud_sql( overlay ):
    env = overlay[ "services" ][ "lupin-rest-test" ][ "environment" ]
    assert env[ "DB_HOST" ] == overlay[ "services" ][ "lupin-pgvector-test" ][ "container_name" ] == "lupin-pgvector-test"
    assert env[ "DB_NAME" ] == "lupin_db_test" and env[ "DB_USER" ] == "lupin_app" and env[ "LUPIN_ENV" ] == "testing"
    for forbidden in ( "LUPIN_CLOUD_BACKED", "CLOUD_SQL_CONNECTION_NAME", "DB_PASSWORD" ):
        assert forbidden not in env, f"{forbidden} would send get_database_url() to Cloud SQL or carry a literal"
    assert env[ "DB_PASSWORD_FILE" ] == "/run/secrets/db_app_password"
    assert overlay[ "services" ][ "lupin-rest-test" ][ "depends_on" ] == { "lupin-pgvector-test": { "condition": "service_healthy" } }


def test_the_pgvector_container_is_pg16_loopback_free_and_reads_its_password_from_a_file( overlay ):
    pg = overlay[ "services" ][ "lupin-pgvector-test" ]
    assert pg[ "image" ] == "pgvector/pgvector:pg16" and "ports" not in pg
    assert pg[ "environment" ][ "POSTGRES_PASSWORD_FILE" ] == "/run/secrets/db_admin_password"
    assert "POSTGRES_PASSWORD" not in pg[ "environment" ]
    assert pg[ "environment" ][ "POSTGRES_USER" ] == "lupin_dev" and pg[ "environment" ][ "POSTGRES_DB" ] == "lupin_db_dev"


def test_every_secret_is_a_host_file_under_etc_lupin_and_every_use_is_declared( overlay ):
    declared = overlay[ "secrets" ]
    assert { k: v[ "file" ] for k, v in declared.items() } == {
        "db_admin_password": f"{SECRETS}/db_admin_password", "db_app_password": f"{SECRETS}/db_app_password",
        "db_test_password":  f"{SECRETS}/db_test_password",  "test_env":        f"{SECRETS}/test_env.sh" }
    used = set()
    for svc in overlay[ "services" ].values():
        for item in svc.get( "secrets", [] ): used.add( item if isinstance( item, str ) else item[ "source" ] )
    assert used == set( declared ), "a declared secret nobody mounts, or a mount nobody declared"


def test_the_overlay_has_no_password_literal_and_every_required_value_fails_loud():
    text = OVERLAY.read_text()
    assert not re.search( r"(?im)^\s*(DB_PASSWORD|POSTGRES_PASSWORD|JWT_SECRET_KEY)\s*:\s*[^$\s#]", text )
    for var in ( "JWT_SECRET_KEY", "LUPIN_MODEL_SERVER_URL", "LUPIN_GCP_PROJECT_ID", "LUPIN_BRIDGE_GID" ):
        assert f"${{{var}}}" not in text and f"${{{var}:?" in text


def test_the_test_server_has_its_own_claude_creds_and_sessions_folder_and_joins_the_base_network( overlay ):
    svc = overlay[ "services" ][ "lupin-rest-test" ]
    assert "claude-creds-test:/home/rruiz/.claude" in svc[ "volumes" ]
    assert "claude-creds-test" in overlay[ "volumes" ] and "claude-creds" not in overlay[ "volumes" ]
    binds = { v[ "target" ]: v for v in svc[ "volumes" ] if isinstance( v, dict ) and v.get( "type" ) == "bind" }
    sessions = binds[ "/home/rruiz/.claude/sessions" ]
    assert sessions[ "source" ].endswith( "/projects-data/lupin/sessions-test" ) and sessions[ "bind" ] == { "create_host_path": False }
    assert svc[ "networks" ] == [ "lupin-cloud-network" ]
    assert svc[ "volumes" ].index( "claude-creds-test:/home/rruiz/.claude" ) < svc[ "volumes" ].index( sessions )


def test_the_init_sql_makes_the_test_database_and_the_extensions_and_no_tables():
    sql = INIT_SQL.read_text()
    assert "CREATE DATABASE lupin_db_test" in sql and sql.count( "CREATE EXTENSION IF NOT EXISTS vector" ) == 2
    assert "CREATE TABLE" not in sql.upper().replace( "NO TABLES", "" )


# ---------------------------------------------------------------- test-server verbs

@pytest.mark.parametrize( "action, expect", [
    ( "up",       "up -d lupin-pgvector-test lupin-rest-test" ),
    ( "recreate", "up -d --force-recreate --no-deps lupin-rest-test" ),
    ( "down",     "stop lupin-pgvector-test lupin-rest-test" ),
    ( "status",   "ps lupin-pgvector-test lupin-rest-test" ),
    ( "logs",     "logs -f --tail=200 lupin-rest-test" ),
] )
def test_the_compose_actions_name_both_files_and_the_right_services( vm, action, expect ):
    done, calls = vm( SCRIPT, "test-server", action )
    assert done.returncode == 0, done.stderr
    cmd = _ssh_command( calls )
    assert "-f docker-compose.cloud-gpu.yml -f docker-compose.vm-test-overlay.yml --env-file cloud-gpu.env " + expect in cmd
    assert "docker compose" in cmd and cmd.startswith( "cd /mnt/lupin-data/lupin && sudo " )


def test_prep_makes_both_host_folders_group_writable_and_setgid( vm ):
    done, calls = vm( SCRIPT, "test-server", "prep" )
    cmd = _ssh_command( calls )
    assert done.returncode == 0 and "sessions-test" in cmd and "flow-ratio" in cmd and "chmod 2775" in cmd


def test_refresh_restarts_the_container_and_polls_health_on_the_vm_itself( vm ):
    done, calls = vm( SCRIPT, "test-server", "refresh" )
    cmd = _ssh_command( calls )
    assert done.returncode == 0
    assert "restart lupin-rest-test" in cmd and "http://localhost:8000/health" in cmd and "tunnel" not in cmd


def test_idle_runs_venue_idle_on_the_vm_so_its_exit_code_is_the_answer( vm ):
    done, calls = vm( SCRIPT, "test-server", "idle" )
    assert "PYTHONPATH=src python3 -m cosa.rest.venue_idle --port 8000" in _ssh_command( calls )


@pytest.mark.parametrize( "flag", [ "", "--apply", "--check", "--grants-only" ] )
def test_roles_passes_the_password_files_never_a_password_and_only_a_known_flag( vm, flag ):
    done, calls = vm( SCRIPT, "test-server", "roles", *( [ flag ] if flag else [] ) )
    cmd = _ssh_command( calls )
    assert done.returncode == 0 and cmd.rstrip().endswith( ( flag or "'" ) )
    for f in ( "app", "host", "test" ): assert f"--{f}-pw-file {SECRETS}/db_{f}_password" in cmd
    assert "docker exec -i lupin-pgvector-test psql -U lupin_dev -d lupin_db_dev" in cmd and "PASSWORD" not in cmd


def test_roles_refuses_any_other_argument_and_so_does_an_unknown_action( vm ):
    bad, _ = vm( SCRIPT, "test-server", "roles", "--reassign" )
    assert bad.returncode != 0 and "--apply, --check or --grants-only" in bad.stderr
    unknown, _ = vm( SCRIPT, "test-server", "bogus" )
    assert unknown.returncode != 0 and "prep | node-modules | seed-companions | up-db | up | recreate" in unknown.stderr


def test_dry_run_prints_the_remote_script_and_calls_gcloud_for_nothing_but_the_network_lookup( vm ):
    done, calls = vm( SCRIPT, "--dry-run", "test-server", "idle" )
    assert done.returncode == 0 and "venue_idle --port 8000" in done.stderr + done.stdout
    assert "compute ssh" not in calls
    done, _ = vm( SCRIPT, "test-server", "up", project=None )
    assert done.returncode != 0 and "LUPIN_GCP_PROJECT_ID" in done.stderr


# ---------------------------------------------------------------- push-test-server-secrets

def _push( vm, **stub ):
    vm.env.write_text( "LUPIN_BRIDGE_GID=" + str( os.getgid() ) + "\nOTHER=1\n" )
    return vm( SCRIPT, "push-test-server-secrets", remote=True, **stub )


def test_the_four_secret_files_are_written_with_the_right_content_and_the_values_never_reach_a_command_line( vm ):
    done, calls = _push( vm )
    assert done.returncode == 0, done.stderr
    assert ( vm.secrets / "db_app_password" ).read_text() == f"{FAKE}-lupin-db-password\n"
    assert ( vm.secrets / "db_test_password" ).read_text() == f"{FAKE}-lupin-db-test-password\n"
    env_sh = ( vm.secrets / "test_env.sh" ).read_text()
    assert env_sh == ( f"export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL='{FAKE}-lupin-test-mock-jobs-email'\n"
                       f"export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD='{FAKE}-lupin-test-mock-jobs-password'\n" )
    assert ( vm.secrets / "db_admin_password" ).read_text() == "a1b2c3\n" and ( vm.secrets / "db_host_password" ).read_text() == "a1b2c3\n"
    for name in ( "db_app_password", "db_test_password", "test_env.sh", "db_admin_password", "db_host_password" ):
        assert oct( ( vm.secrets / name ).stat().st_mode & 0o777 ) == "0o440"
    assert FAKE not in calls and FAKE not in done.stdout + done.stderr and "a1b2c3" not in done.stdout + done.stderr
    assert "db_app_password: written" in done.stdout


def test_a_second_run_changes_nothing_and_keeps_the_generated_passwords( vm ):
    _push( vm )
    done, _ = _push( vm, stub_rand="different" )
    assert done.returncode == 0
    for name in ( "db_app_password", "db_test_password", "test_env.sh" ): assert f"{name}: unchanged" in done.stdout
    for name in ( "db_admin_password", "db_host_password" ):
        assert f"{name}: kept" in done.stdout and ( vm.secrets / name ).read_text() == "a1b2c3\n"


def test_a_changed_secret_is_rewritten_and_says_so( vm ):
    _push( vm )
    done, _ = _push( vm, stub_secret="rotated" )
    assert "db_app_password: written" in done.stdout and ( vm.secrets / "db_app_password" ).read_text() == "rotated-lupin-db-password\n"


def test_a_missing_env_file_or_gid_stops_before_any_file_is_written( vm ):
    done, _ = vm( SCRIPT, "push-test-server-secrets", remote=True )
    assert done.returncode == 3 and "create it first" in done.stderr and not vm.secrets.exists()
    vm.env.write_text( "OTHER=1\n" )
    done, _ = vm( SCRIPT, "push-test-server-secrets", remote=True )
    assert done.returncode == 5 and "LUPIN_BRIDGE_GID" in done.stderr and not vm.secrets.exists()


def test_a_value_that_does_not_arrive_on_stdin_stops_the_remote_script( vm ):
    vm.env.write_text( f"LUPIN_BRIDGE_GID={os.getgid()}\n" )
    # Drive the remote command alone with an empty stdin: the same shape as a gcloud that sent nothing.
    done, calls = vm( SCRIPT, "push-test-server-secrets", remote=True, stub_secret_empty="lupin-test-mock-jobs-password" )
    assert done.returncode != 0 and "has no value" in done.stderr
    cmd = _ssh_command( vm( SCRIPT, "push-test-server-secrets" )[ 1 ] )
    proc = subprocess.run( [ "bash", "-c", cmd.replace( "/mnt/lupin-data/lupin/cloud-gpu.env", str( vm.env ) ).replace( SECRETS, str( vm.secrets ) ) ],
                           input="", capture_output=True, text=True, env={ "PATH": vm.path, "HOME": "/tmp", "STUB_CALLS": str( vm.calls ) } )
    assert proc.returncode == 4 and "did not arrive" in proc.stderr


@pytest.mark.parametrize( "stub, message", [
    ( { "stub_secret_fails": "lupin-db-password" },                "could not read Secret Manager lupin-db-password" ),
    ( { "stub_secret_empty": "lupin-db-test-password" },           "lupin-db-test-password has no value" ),
    ( { "stub_secret_bad": "lupin-db-password", "stub_bad_value": "a b" },   "characters a psql variable may misread" ),
    ( { "stub_secret_bad": "lupin-test-mock-jobs-email", "stub_bad_value": "it's" }, "holds a single quote" ),
] )
def test_a_bad_secret_stops_the_verb_before_anything_is_sent( vm, stub, message ):
    done, calls = _push( vm, **stub )
    assert done.returncode != 0 and message in done.stderr
    assert "compute ssh" not in calls and not vm.secrets.exists()


def test_the_dry_run_names_the_four_secrets_and_runs_nothing( vm ):
    done, calls = vm( SCRIPT, "--dry-run", "push-test-server-secrets" )
    out = done.stdout + done.stderr
    assert done.returncode == 0 and "lupin-db-password" in out and "lupin-test-mock-jobs-email" in out
    assert "secrets versions" not in calls and "compute ssh" not in calls


def test_the_usage_text_lists_the_new_verbs_and_the_tunnel_recipe( vm ):
    done, _ = vm( SCRIPT, "--help" )
    for word in ( "push-test-server-secrets", "test-server prep", "test-server roles", "firewall open 8000", "tunnel 18000 8000" ):
        assert word in done.stderr + done.stdout, word


# ---------------------------------------------------------------- refresh-test-server.sh --vm

def test_refresh_vm_hands_off_to_the_test_server_refresh_verb_and_does_not_touch_local_docker( vm ):
    done, calls = vm( REFRESH, "--vm" )
    assert done.returncode == 0, done.stderr
    cmd = _ssh_command( calls )
    assert "restart lupin-rest-test" in cmd and "docker restart" not in calls


def test_refresh_vm_without_a_project_id_fails_loud( vm ):
    done, _ = vm( REFRESH, "--vm", project=None )
    assert done.returncode != 0 and "LUPIN_GCP_PROJECT_ID" in done.stderr


def test_refresh_still_prints_help_and_refuses_an_unknown_argument( vm ):
    done, _ = vm( REFRESH, "-h" )
    assert done.returncode == 0 and "--vm" in done.stdout
    bad, _ = vm( REFRESH, "--bogus" )
    assert bad.returncode == 2


def test_refresh_local_path_restarts_the_local_container_and_polls_health( vm, tmp_path ):
    ( tmp_path / "docker" ).write_text( '#!/bin/bash\necho "docker $*" >> "$STUB_CALLS"\n[ "$STUB_DOCKER_FAILS" = 1 ] && exit 1\nexit 0\n' )
    ( tmp_path / "docker" ).chmod( 0o755 )
    ( tmp_path / "curl" ).write_text( '#!/bin/bash\n[ "$STUB_CURL_FAILS" = 1 ] && exit 22\nexit 0\n' )
    ( tmp_path / "curl" ).chmod( 0o755 )
    done, calls = vm( REFRESH, "--quiet" )
    assert done.returncode == 0 and "docker restart lupin-rest-test" in calls and "refreshed lupin-rest-test" in done.stdout
    loud, _ = vm( REFRESH )
    assert "OK: lupin-rest-test healthy" in loud.stdout
    failed, _ = vm( REFRESH, stub_docker_fails="1" )
    assert failed.returncode == 1 and "docker restart failed" in failed.stderr
    stuck, _ = vm( REFRESH, stub_curl_fails="1", refresh_timeout_secs="1" )
    assert stuck.returncode == 1 and "health check did not pass within 1s" in stuck.stderr and "docker logs --tail 50" in stuck.stderr


# ---------------------------------------------------------------- row 8d67e474: node_modules and the companions


def test_node_modules_is_a_named_volume_the_overlay_declares_and_the_test_service_mounts():
    overlay = yaml.safe_load( OVERLAY.read_text() )
    assert "node-modules-test:/var/lupin/node_modules" in overlay[ "services" ][ "lupin-rest-test" ][ "volumes" ]
    assert "node-modules-test" in overlay[ "volumes" ]


def test_the_node_modules_verb_installs_without_scripts_as_root_and_proves_esbuild_last( vm ):
    done, calls = vm( SCRIPT, "test-server", "node-modules" )
    cmd = _ssh_command( calls )
    assert done.returncode == 0 and "run --rm --no-deps -u root lupin-rest-test" in cmd and "-f docker-compose.vm-test-overlay.yml" in cmd
    assert cmd.index( "npm ci --ignore-scripts" ) < cmd.index( "node_modules/.bin/esbuild --version" )


def test_the_overlay_turns_the_dev_database_companion_copy_off():
    env = yaml.safe_load( OVERLAY.read_text() )[ "services" ][ "lupin-rest-test" ][ "environment" ]
    assert env[ "LUPIN_TEST_SEED_FROM_DEV" ] == "0"


def test_seed_companions_pipes_the_export_from_the_app_container_into_the_test_database_and_holds_no_password( vm ):
    done, calls = vm( SCRIPT, "test-server", "seed-companions" )
    cmd = _ssh_command( calls )
    export = "docker exec -e LUPIN_ROOT=/var/lupin lupin-rest-cloud-gpu python3 /var/lupin/src/scripts/export_test_companions.py"
    assert done.returncode == 0 and cmd.startswith( "set -o pipefail; sudo " + export )
    assert cmd.index( export ) < cmd.index( "| sudo docker exec -i lupin-pgvector-test psql -U lupin_dev -d lupin_db_test -v ON_ERROR_STOP=1 -q" )
    assert "PASSWORD" not in cmd and "--check" not in cmd


def test_seed_companions_check_only_counts_and_never_names_the_test_database( vm ):
    done, calls = vm( SCRIPT, "test-server", "seed-companions", "--check" )
    cmd = _ssh_command( calls )
    assert done.returncode == 0 and cmd.endswith( "export_test_companions.py --check" ) and "psql" not in cmd


def test_seed_companions_refuses_any_other_argument( vm ):
    bad, _ = vm( SCRIPT, "test-server", "seed-companions", "--force" )
    assert bad.returncode != 0 and "takes --check or nothing" in bad.stderr
