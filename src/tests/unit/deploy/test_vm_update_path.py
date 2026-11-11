"""
Tests for the VM server-update path: secrets check, cron check, overlay checks, deploy.

Nothing here touches a VM, Secret Manager or a crontab. Stand-ins for gcloud, docker, curl, sudo and crontab sit on the path.
The lib functions run in a bash subprocess. Venue: :7999 (unit).
"""
import os
import shutil
import stat
import subprocess

import pytest

import cosa.utils.util as cu

ROOT   = cu.get_project_root()
VMSH   = f"{ROOT}/src/scripts/lupin-vm.sh"
LIB    = f"{ROOT}/src/scripts/lib/preflight-vm-lib.sh"
PREFLT = f"{ROOT}/src/scripts/preflight-vm.sh"

SECRET_NAMES = [ "lupin-db-password", "lupin-db-test-password", "lupin-notification-api-key",
                 "lupin-test-mock-jobs-email", "lupin-test-mock-jobs-password" ]

CRON_LINE = "47 10 * * * /mnt/lupin-data/lupin/src/scripts/cron-job.sh vector-refresh cron >> /mnt/x/refresh.log 2>&1 # reuse-vector-refresh"
BOOT_LINE = "@reboot sleep 240 && /mnt/lupin-data/lupin/src/scripts/cron-job.sh vector-refresh boot >> /mnt/x/refresh.log 2>&1 # reuse-vector-refresh"


def _lib( call, **env ):
    """Run one lib call; returns ( stdout, returncode )."""
    done = subprocess.run( [ "bash", "-c", f'source "$LIB"; {call}' ], env={ **os.environ, "LIB": LIB, **env }, capture_output=True, text=True, timeout=30 )
    return done.stdout, done.returncode


def _exe( path, text ):
    path.write_text( text ); path.chmod( path.stat().st_mode | stat.S_IEXEC )


# ── lib: pfv_cron_status ─────────────────────────────────────────────────────

@pytest.mark.parametrize( "text,want,rc", [
    ( CRON_LINE,                                   "PRESENT", 0 ),
    ( f"MAILTO=x\n{BOOT_LINE}\n{CRON_LINE}\n",     "PRESENT", 0 ),
    ( "",                                          "ABSENT",  1 ),
    ( f"# {CRON_LINE}",                            "ABSENT",  1 ),
    ( BOOT_LINE,                                   "ABSENT",  1 ),
    ( "47 10 * * * other-job cron # something-else", "ABSENT", 1 ),
] )
def test_cron_status_reads_the_one_line_cron_generate_writes( text, want, rc ):
    assert _lib( 'pfv_cron_status "$T"', T=text ) == ( want, rc )


def test_cron_status_with_no_argument_is_absent():
    assert _lib( "pfv_cron_status" ) == ( "ABSENT", 1 )


# ── lib: pfv_overlay_present ─────────────────────────────────────────────────

def test_overlay_present_needs_the_exact_container_name():
    assert _lib( 'pfv_overlay_present "$N" lupin-rest-test', N="a\nlupin-rest-test\nb" )[ 1 ] == 0
    assert _lib( 'pfv_overlay_present "$N" lupin-rest-test', N="lupin-rest-test-old\nx-lupin-rest-test" )[ 1 ] == 1
    assert _lib( 'pfv_overlay_present "" lupin-rest-test' )[ 1 ] == 1


# ── lib: pfv_test_login_email ────────────────────────────────────────────────

def _env_file( tmp_path, email="tester@example.com", extra="" ):
    path = tmp_path / "test_env.sh"
    path.write_text( f"export LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL='{email}'\nexport LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD='s3cret'\n{extra}" )
    return path


def test_login_email_prints_the_address_and_never_the_password( tmp_path ):
    out, rc = _lib( 'pfv_test_login_email "$F"', F=str( _env_file( tmp_path ) ) )
    assert ( out, rc ) == ( "tester@example.com", 0 ) and "s3cret" not in out


@pytest.mark.parametrize( "email", [ "a'b@x.com", "a b@x.com", "a;b@x.com", "" ] )
def test_login_email_refuses_a_character_that_could_break_the_sql_string( tmp_path, email ):
    assert _lib( 'pfv_test_login_email "$F"', F=str( _env_file( tmp_path, email=email ) ) ) == ( "", 1 )


def test_login_email_refuses_a_missing_file_and_a_missing_line( tmp_path ):
    assert _lib( 'pfv_test_login_email "$F"', F=str( tmp_path / "none" ) ) == ( "", 1 )
    blank = tmp_path / "blank.sh"; blank.write_text( "export OTHER='x'\n" )
    assert _lib( 'pfv_test_login_email "$F"', F=str( blank ) ) == ( "", 1 )


# ── lib: pfv_count_status ────────────────────────────────────────────────────

@pytest.mark.parametrize( "text,want,rc", [
    ( "1\n", "PRESENT", 0 ), ( " 12 ", "PRESENT", 0 ), ( "0\n", "ABSENT", 1 ), ( "000", "ABSENT", 1 ), ( "007", "PRESENT", 0 ),
    ( "", "UNKNOWN", 3 ), ( "ERROR: relation users does not exist", "UNKNOWN", 3 ),
] )
def test_count_status_reads_a_count_and_never_reads_an_error_as_zero( text, want, rc ):
    assert _lib( 'pfv_count_status "$T"', T=text ) == ( want, rc )


def test_count_status_with_no_argument_is_unknown():
    assert _lib( "pfv_count_status" ) == ( "UNKNOWN", 3 )


# ── lupin-vm.sh: the secret names are derived from the script ────────────────

def _vm( *args, env=None, script=VMSH, path=None ):
    base = { "PATH": path or os.environ[ "PATH" ], "HOME": "/nonexistent", "LUPIN_GCP_PROJECT_ID": "proj-x" }
    return subprocess.run( [ "bash", script, *args ], capture_output=True, text=True, env={ **base, **( env or {} ) }, timeout=60 )


def test_the_derived_names_are_exactly_the_five_the_verbs_read():
    done = _vm( "--dry-run", "secrets-check" )
    names = [ l.strip() for l in done.stdout.splitlines() if l.startswith( "    " ) ]
    assert done.returncode == 0 and names == SECRET_NAMES


def test_every_secret_flag_in_the_script_resolves_and_none_is_left_over():
    flags = open( VMSH ).read().count( '--secret="$' )
    assert flags == 5   # the denominator, pinned: five flag sites feed the five names, so a new site must be added here on purpose


def test_a_new_secret_reference_is_covered_without_anyone_editing_a_list( tmp_path ):
    copy = tmp_path / "lupin-vm.sh"
    copy.write_text( open( VMSH ).read().replace( 'TL_SECRET="lupin-db-test-password"', 'TL_SECRET="lupin-brand-new-secret"' ) )
    names = [ l.strip() for l in _vm( "--dry-run", "secrets-check", script=str( copy ) ).stdout.splitlines() if l.startswith( "    " ) ]
    assert "lupin-brand-new-secret" in names and "lupin-db-test-password" in names   # still named by the push-test-server-secrets list


def test_a_reference_that_cannot_be_resolved_fails_the_whole_call( tmp_path ):
    copy = tmp_path / "lupin-vm.sh"
    copy.write_text( open( VMSH ).read() + '\n: gcloud secrets versions access latest --secret="$NOWHERE_DEFINED"\n' )
    done = _vm( "--dry-run", "secrets-check", script=str( copy ) )
    assert "cannot resolve $NOWHERE_DEFINED" in done.stderr and "lupin-db-password" not in done.stdout


def test_a_script_with_no_secret_reference_fails_loudly( tmp_path ):
    copy = tmp_path / "lupin-vm.sh"
    copy.write_text( open( VMSH ).read().replace( '--secret="$', '--sekret="$' ) )
    done = _vm( "--dry-run", "secrets-check", script=str( copy ) )
    assert "no --secret= reference found" in done.stderr


# ── lupin-vm.sh secrets-check against a stand-in gcloud ──────────────────────

FAKE_GCLOUD = r'''#!/bin/bash
# gcloud secrets versions list NAME ... : prints a version name unless NAME is in $FAKE_MISSING
name="$4"
case " $FAKE_MISSING " in *" $name "*) exit 0 ;; esac
echo "projects/1/secrets/$name/versions/1"
'''


def _gcloud_path( tmp_path, missing="" ):
    bindir = tmp_path / "bin"; bindir.mkdir( exist_ok=True )
    _exe( bindir / "gcloud", FAKE_GCLOUD )
    return f"{bindir}:{os.environ[ 'PATH' ]}", { "FAKE_MISSING": missing }


def test_secrets_check_passes_when_every_secret_has_an_enabled_version( tmp_path ):
    path, env = _gcloud_path( tmp_path )
    done = _vm( "secrets-check", path=path, env=env )
    assert done.returncode == 0 and done.stdout.count( "[OK]" ) == 5 and "[FAIL]" not in done.stdout


def test_secrets_check_names_the_missing_secret_and_the_line_a_person_runs( tmp_path ):
    path, env = _gcloud_path( tmp_path, missing="lupin-db-test-password" )
    done = _vm( "secrets-check", path=path, env=env )
    assert done.returncode == 1 and done.stdout.count( "[OK]" ) == 4
    assert "[FAIL]  Secret Manager lupin-db-test-password is missing" in done.stdout
    assert "gcloud secrets create lupin-db-test-password --project=proj-x --data-file=-" in done.stdout
    assert "gcloud secrets versions add lupin-db-test-password" in done.stdout


def test_secrets_check_prints_names_only_never_a_value( tmp_path ):
    path, env = _gcloud_path( tmp_path )
    done = _vm( "secrets-check", path=path, env=env )
    assert "projects/1/secrets" not in done.stdout + done.stderr


def test_secrets_check_without_gcloud_says_it_could_not_ask_and_exits_2( tmp_path ):
    bindir = tmp_path / "bare"; bindir.mkdir()
    for tool in ( "bash", "grep", "sed", "sort", "head", "dirname", "printenv", "cat" ):
        shutil.copy( shutil.which( tool ), bindir / tool )
    done = _vm( "secrets-check", path=str( bindir ) )
    assert done.returncode == 2 and "gcloud is not on this host" in done.stdout


def test_secrets_check_needs_the_project_id():
    done = subprocess.run( [ "bash", VMSH, "secrets-check" ], capture_output=True, text=True,
                           env={ "PATH": os.environ[ "PATH" ], "HOME": "/nonexistent" } )
    assert done.returncode != 0 and "LUPIN_GCP_PROJECT_ID" in done.stderr


# ── lupin-vm.sh deploy: the wiring ───────────────────────────────────────────

def test_deploy_runs_the_secret_check_first_and_refreshes_the_overlay_before_the_post_arm():
    text = _vm( "--dry-run", "deploy" ).stdout + _vm( "--dry-run", "deploy" ).stderr
    assert "PRE-deploy secret check: lupin-vm.sh secrets-check" in text
    overlay = text.index( "test server overlay (only when its containers exist)" )
    assert text.index( "[1/3] restart" ) < overlay < text.index( "POST-deploy preflight (--phase post)" )
    assert "-f docker-compose.cloud-gpu.yml -f docker-compose.vm-test-overlay.yml --env-file cloud-gpu.env restart lupin-rest-test" in text
    assert "overlay lupin-rest-test is not on this VM; skipped" in text


def test_deploy_warns_and_goes_on_when_the_secret_check_finds_a_problem( tmp_path ):
    # The one line that carries the decision, read from the script: advisory, never a die.
    line = [ l for l in open( VMSH ) if "vm_secrets_check ||" in l ][ 0 ]
    assert "WARN" in line and "die" not in line


def test_the_help_names_the_new_verb_and_the_update_path():
    text = _vm( "--help" ).stderr + _vm( "--help" ).stdout
    assert "secrets-check" in text and "the one command for a server update" in text


# ── preflight-vm.sh --phase post: cron and overlay ───────────────────────────

FAKE_DOCKER = r'''#!/bin/bash
case "$1" in
  ps) case "$*" in *"-a"*) printf '%s\n' "$FAKE_PS_ALL" ;; *) echo "$FAKE_CONTAINER" ;; esac ;;
  inspect) case "$*" in *Config.Labels*) printf %s "" ;; *State.Running*) echo true ;; esac ;;
  exec)
    case "$*" in
      *lupin-rest-test*check_schema_at_head*) echo "DETAIL=${FAKE_SCHEMA_DETAIL:-}"; exit "${FAKE_SCHEMA_RC:-0}" ;;
      *psql*lupin_db_test*) printf '%s\n' "${FAKE_COUNT-1}"; exit 0 ;;
      *) exit 1 ;;
    esac ;;
  *) exit 1 ;;
esac
'''
FAKE_SUDO = r'''#!/bin/bash
[ "$1" = "-n" ] && shift
case "$1" in
  env) echo "$*" >> "${FAKE_SUDO_LOG:-/dev/null}"; exit "${FAKE_ROLES_RC:-0}" ;;
  git) case "$*" in *rev-parse*) echo abc1234 ;; esac; exit 0 ;;
  *) exit 1 ;;
esac
'''


@pytest.fixture
def venue( tmp_path ):
    home = tmp_path / "home"; ( home / ".claude" / "projects" ).mkdir( parents=True )
    bindir = tmp_path / "bin"; bindir.mkdir()
    _exe( bindir / "docker", FAKE_DOCKER )
    _exe( bindir / "sudo", FAKE_SUDO )
    _exe( bindir / "curl", '#!/bin/bash\nprintf %s "${FAKE_HEALTH-200}"\n' )
    _exe( bindir / "crontab", '#!/bin/bash\n[ -f "$FAKE_CRONTAB" ] && cat "$FAKE_CRONTAB" || exit 1\n' )
    secrets = tmp_path / "secrets"; secrets.mkdir()
    _env_file( secrets ).rename( secrets / "test_env.sh" )
    ambient = { k: v for k, v in os.environ.items() if not k.startswith( ( "PREFLIGHT_VM_", "CLAUDE_CODE_USE_VERTEX" ) ) }
    env = { **ambient, "HOME": str( home ), "PATH": f"{bindir}:{os.environ[ 'PATH' ]}", "LUPIN_ROOT": ROOT,
            "PREFLIGHT_VM_CONTAINER": "fake-rest", "FAKE_CONTAINER": "fake-rest", "FAKE_PS_ALL": "fake-rest\nlupin-rest-test\nlupin-pgvector-test",
            "PREFLIGHT_VM_COMPOSE": f"{ROOT}/docker-compose.cloud-gpu.yml", "PREFLIGHT_VM_ENVFILE": str( tmp_path / "cloud-gpu.env" ),
            "PREFLIGHT_VM_PROJECT_MCP_JSON": str( tmp_path / "p.mcp.json" ), "PREFLIGHT_VM_OVERLAY_SECRETS": str( secrets ),
            "FAKE_CRONTAB": str( tmp_path / "crontab.txt" ) }
    ( tmp_path / "cloud-gpu.env" ).write_text( "LUPIN_GCP_PROJECT_ID=proj-x\n" )
    ( tmp_path / "crontab.txt" ).write_text( CRON_LINE + "\n" )
    return { "env": env, "tmp": tmp_path, "secrets": secrets }


def _post( venue, phase="post" ):
    return subprocess.run( [ "bash", PREFLT, "--phase", phase ], env=venue[ "env" ], capture_output=True, text=True, timeout=180 ).stdout


def _line( out, needle ):
    hits = [ l for l in out.split( "\n" ) if needle in l ]
    assert hits, f"no line containing {needle!r} in:\n{out}"
    return "\n".join( hits )


def test_post_reports_the_cron_present( venue ):
    assert "[OK]" in _line( _post( venue ), "reuse-vector-refresh cron line is in this user's crontab" )


def test_post_warns_when_the_cron_is_absent_and_prints_the_line_a_person_runs( venue ):
    ( venue[ "tmp" ] / "crontab.txt" ).unlink()
    out = _post( venue )
    assert "[WARN]" in _line( out, "cron line is NOT in this user's crontab" )
    assert "src/scripts/lupin-vm.sh install-refresh-cron vm" in out


def test_pre_runs_neither_the_cron_nor_the_overlay_checks( venue ):
    out = _post( venue, phase="pre" )
    assert "reuse-vector-refresh cron" not in out and "overlay" not in out and "[SKIP]" not in out


def test_an_absent_overlay_is_a_skip_line_and_never_a_failure( venue ):
    venue[ "env" ][ "FAKE_PS_ALL" ] = "fake-rest"
    out = _post( venue )
    assert "[SKIP]  overlay test server lupin-rest-test is not on this host" in out
    assert "overlay" not in "\n".join( l for l in out.split( "\n" ) if l.startswith( ( "[FAIL]", "[WARN]", "[UNKN]", "[OK]" ) ) )


def test_a_healthy_overlay_passes_all_four_checks_without_showing_the_address( venue ):
    out = _post( venue )
    assert "[OK]" in _line( out, "overlay lupin-rest-test /health 200 on :8000" )
    assert "[OK]" in _line( out, "overlay DB schema is at the tree's head revision" )
    assert "[OK]" in _line( out, "overlay database roles and grants read back clean" )
    assert "[OK]" in _line( out, "holds the tester login (address not shown)" )
    assert "tester@example.com" not in out and "s3cret" not in out


def test_an_overlay_that_does_not_answer_health_fails_with_the_remedy( venue ):
    venue[ "env" ][ "FAKE_HEALTH" ] = "000"
    out = _post( venue )
    assert "[FAIL]" in _line( out, "overlay lupin-rest-test /health returned '000'" )
    assert "lupin-vm.sh test-server logs" in out


def test_overlay_schema_drift_names_the_recreate( venue ):
    venue[ "env" ].update( FAKE_SCHEMA_RC="1", FAKE_SCHEMA_DETAIL="db=a tree=b" )
    out = _post( venue )
    assert "[FAIL]" in _line( out, "overlay SCHEMA DRIFT — db=a tree=b" ) and "lupin-vm.sh test-server recreate" in out


def test_an_overlay_schema_that_cannot_be_read_is_unknown_not_drift( venue ):
    venue[ "env" ].update( FAKE_SCHEMA_RC="2", FAKE_SCHEMA_DETAIL="no db" )
    line = _line( _post( venue ), "cannot determine the overlay schema revision — no db" )
    assert "[UNKN]" in line and "DRIFT" not in line


def test_overlay_roles_that_are_not_clean_fail_with_the_two_verbs( venue ):
    venue[ "env" ][ "FAKE_ROLES_RC" ] = "1"
    out = _post( venue )
    assert "[FAIL]" in _line( out, "overlay database roles or grants are not clean" )
    assert "lupin-vm.sh test-server roles --apply" in out and "--grants-only" in out


def test_no_tester_login_row_warns_and_does_not_block( venue ):
    venue[ "env" ][ "FAKE_COUNT" ] = "0"
    out = _post( venue )
    assert "[WARN]" in _line( out, "has no tester login" )


def test_a_failed_tester_query_is_unknown_not_absent( venue ):
    venue[ "env" ][ "FAKE_COUNT" ] = ""
    line = _line( _post( venue ), "could not query lupin_db_test for the tester login" )
    assert "[UNKN]" in line and "has no tester login" not in line


def test_an_unreadable_tester_address_is_unknown_and_points_at_the_secrets_verb( venue ):
    ( venue[ "secrets" ] / "test_env.sh" ).unlink()
    out = _post( venue )
    assert "[UNKN]" in _line( out, "tester address could not be read" ) and "lupin-vm.sh push-test-server-secrets" in out


# ── the four bring-up fixes folded in from the 10 Nov bring-up ───────────────

def test_roles_runs_db_roles_with_the_vm_checkout_as_lupin_root():
    text = _vm( "--dry-run", "test-server", "roles", "--check" )
    out = text.stdout + text.stderr
    assert "sudo env LUPIN_ROOT=/mnt/lupin-data/lupin PYTHONPATH=src python3 -m cosa.utils.db_roles" in out


def test_the_preflight_roles_check_carries_lupin_root_too():
    assert 'sudo -n env LUPIN_ROOT="$REPO_ROOT" PYTHONPATH=src python3 -m cosa.utils.db_roles' in open( PREFLT ).read()


def test_up_db_starts_the_database_container_alone_and_the_docs_put_it_before_roles():
    out = _vm( "--dry-run", "test-server", "up-db" ); text = out.stdout + out.stderr
    assert "docker-compose.vm-test-overlay.yml --env-file cloud-gpu.env up -d lupin-pgvector-test" in text and "lupin-rest-test" not in text.split( "up -d" )[ -1 ]
    doc = open( f"{ROOT}/src/docs/vm-test-server.md" ).read()
    assert doc.index( "test-server up-db" ) < doc.index( "test-server roles" )


def test_refresh_waits_up_to_180_seconds_for_health():
    out = _vm( "--dry-run", "test-server", "refresh" ); text = out.stdout + out.stderr
    assert "seq 1 180" in text and "within 180s" in text and "seq 1 60" not in text


def test_the_deploy_overlay_step_restarts_and_waits_up_to_180_seconds():
    text = _vm( "--dry-run", "deploy" ); text = text.stdout + text.stderr
    assert "--env-file cloud-gpu.env restart lupin-rest-test" in text and "seq 1 90" in text


def test_install_refresh_cron_exports_the_config_manager_args_from_the_job_registry( tmp_path ):
    # Run the exported prefix of the printed command against the real registry, with the root pointed at this tree.
    text = _vm( "--dry-run", "install-refresh-cron", "vm" ); lines = ( text.stdout + text.stderr ).splitlines()
    start = next( i for i, l in enumerate( lines ) if l.strip().startswith( "LUPIN_CONFIG_MGR_CLI_ARGS=" ) )
    snippet = "\n".join( l.strip() for l in lines[ start:start + 3 ] ).replace( "/mnt/lupin-data/lupin", ROOT )
    assert snippet.rstrip().endswith( "export LUPIN_CONFIG_MGR_CLI_ARGS" )
    done = subprocess.run( [ "bash", "-c", f"set -e\n{snippet}\nprintf %s \"$LUPIN_CONFIG_MGR_CLI_ARGS\"" ], capture_output=True, text=True, timeout=30 )
    import json
    want = json.load( open( f"{ROOT}/src/conf/job-registry.json" ) )[ "defaults" ][ "run_env" ][ "LUPIN_CONFIG_MGR_CLI_ARGS" ]
    assert done.returncode == 0 and done.stdout == want and "config_block_id=" in want


def test_install_refresh_cron_stops_when_the_registry_has_no_value( tmp_path ):
    text = _vm( "--dry-run", "install-refresh-cron", "vm" ); lines = ( text.stdout + text.stderr ).splitlines()
    start = next( i for i, l in enumerate( lines ) if l.strip().startswith( "LUPIN_CONFIG_MGR_CLI_ARGS=" ) )
    empty = tmp_path / "src" / "conf"; empty.mkdir( parents=True )
    ( empty / "job-registry.json" ).write_text( '{"defaults":{"run_env":{"LUPIN_CONFIG_MGR_CLI_ARGS":""}}}' )
    snippet = "\n".join( l.strip() for l in lines[ start:start + 3 ] ).replace( "/mnt/lupin-data/lupin", str( tmp_path ) )
    done = subprocess.run( [ "bash", "-c", f"set -e\n{snippet}" ], capture_output=True, text=True, timeout=30 )
    assert done.returncode == 1 and "no LUPIN_CONFIG_MGR_CLI_ARGS" in done.stdout


def test_the_roles_check_is_limited_to_lupin_db_test_so_an_empty_dev_database_cannot_block_it( venue ):
    log = venue[ "tmp" ] / "sudo.log"
    venue[ "env" ][ "FAKE_SUDO_LOG" ] = str( log )
    _post( venue )
    calls = [ l for l in log.read_text().splitlines() if "cosa.utils.db_roles" in l ]
    assert len( calls ) == 1 and calls[ 0 ].endswith( "--check --database lupin_db_test" )
    assert "--apply" not in calls[ 0 ] and "--grants-only" not in calls[ 0 ]
