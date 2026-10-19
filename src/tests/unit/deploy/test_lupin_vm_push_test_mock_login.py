"""
Tests for the push-test-mock-login verb of lupin-vm.sh.

The verb writes the test login for the daily vector refresh into an owner-only file under the home folder.
It must never put a value in a command line. gcloud is a stub on the path. Its ssh call logs the
arguments and runs the remote command locally, with the home folder pointed at a scratch folder.
"""
import os
import subprocess
from pathlib import Path

import pytest

import cosa.repo.symindex.vector_refresh as vr

SCRIPT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "lupin-vm.sh"
EMAIL  = "someone" + "@example.test"
ODD_VALUE = "pa ss$wd" + "#42;`x`"

GCLOUD = r'''#!/bin/bash
echo "$*" >> "$STUB_CALLS"
if [ "$1" = "secrets" ]; then
    [ -n "$STUB_SECRET_FAILS" ] && case "$*" in *"$STUB_SECRET_FAILS"*) exit 1 ;; esac
    case "$*" in
        *lupin-test-mock-jobs-email*) printf '%s\n' "$STUB_EMAIL" ;;
        *lupin-test-mock-jobs-password*) printf '%s\n' "$STUB_PASSWORD" ;;
    esac
    exit 0
fi
if [ "$1" = "compute" ] && [ "$2" = "ssh" ]; then
    while [ $# -gt 0 ]; do [ "$1" = "--command" ] && { cmd="$2"; break; }; shift; done
    HOME="$STUB_VM_HOME" bash -c "$cmd"; exit $?
fi
exit 0
'''


@pytest.fixture
def run( tmp_path ):
    calls, home, vm_home = tmp_path / "calls.log", tmp_path / "home", tmp_path / "vmhome"
    home.mkdir(); vm_home.mkdir()
    ( tmp_path / "gcloud" ).write_text( GCLOUD )
    ( tmp_path / "gcloud" ).chmod( 0o755 )
    def go( *args, email=EMAIL, password=ODD_VALUE, project="proj-x", fails="" ):
        env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "HOME": str( home ), "STUB_CALLS": str( calls ),
                "STUB_EMAIL": email, "STUB_PASSWORD": password, "STUB_SECRET_FAILS": fails, "STUB_VM_HOME": str( vm_home ) }
        if project is not None: env[ "LUPIN_GCP_PROJECT_ID" ] = project
        done = subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env )
        return done, ( calls.read_text() if calls.exists() else "" )
    go.file    = home / vr.ENV_FILE_REL
    go.vm_file = vm_home / vr.ENV_FILE_REL
    return go


def _mode( path ): return oct( path.stat().st_mode & 0o777 )


def _sourced( path ):
    """What a shell that sources the file sees, which is how the refresh script reads it."""
    code = f'set -a; . "{path}"; set +a; printf "%s\\n%s" "$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" "$LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD"'
    return subprocess.run( [ "bash", "-c", code ], capture_output=True, text=True ).stdout


def test_a_local_run_writes_an_owner_only_file_the_refresh_script_reads_back_exactly( run ):
    done, _ = run( "push-test-mock-login" )
    assert done.returncode == 0, done.stderr
    assert _mode( run.file ) == "0o600" and _mode( run.file.parent ) == "0o700"
    assert _sourced( run.file ) == f"{EMAIL}\n{ODD_VALUE}" and not run.vm_file.exists()
    assert f"{run.file}: set" in done.stdout


def test_a_second_run_changes_nothing_and_a_new_value_is_replaced( run ):
    run( "push-test-mock-login" )
    again, _ = run( "push-test-mock-login", "local" )
    assert f"{run.file}: unchanged" in again.stdout
    changed, _ = run( "push-test-mock-login", password="another-one" )
    assert f"{run.file}: replaced" in changed.stdout and _sourced( run.file ).endswith( "another-one" )


def test_a_file_with_the_right_content_but_a_loose_mode_is_rewritten_to_600( run ):
    run( "push-test-mock-login" )
    run.file.chmod( 0o644 )
    done, _ = run( "push-test-mock-login" )
    assert _mode( run.file ) == "0o600" and "replaced" in done.stdout


def test_no_temporary_file_is_left_behind_by_the_first_run_or_by_an_unchanged_second_run( run ):
    run( "push-test-mock-login" )
    assert [ p.name for p in run.file.parent.iterdir() ] == [ run.file.name ]
    again, _ = run( "push-test-mock-login" )
    assert "unchanged" in again.stdout                                          # the path that exits before the move
    assert [ p.name for p in run.file.parent.iterdir() ] == [ run.file.name ]


@pytest.mark.parametrize( "email,password", [ ( EMAIL + "\r", ODD_VALUE ), ( EMAIL, ODD_VALUE + "\r" ), ( EMAIL + "\r", ODD_VALUE + "\r" ) ] )
def test_a_secret_ending_in_a_carriage_return_is_written_without_it( run, email, password ):
    done, _ = run( "push-test-mock-login", email=email, password=password )
    assert done.returncode == 0, done.stderr
    raw = run.file.read_bytes()
    assert b"\r" not in raw and raw.count( b"\n" ) == 2
    assert _sourced( run.file ) == f"{EMAIL}\n{ODD_VALUE}"


def test_the_vm_run_writes_on_the_vm_by_ssh_and_the_values_are_in_no_command_line( run ):
    done, calls = run( "push-test-mock-login", "vm" )
    assert done.returncode == 0, done.stderr
    assert _mode( run.vm_file ) == "0o600" and _sourced( run.vm_file ) == f"{EMAIL}\n{ODD_VALUE}" and not run.file.exists()
    assert "compute ssh" in calls and "--tunnel-through-iap" in calls
    for text in ( calls, done.stdout, done.stderr ):
        assert EMAIL not in text and ODD_VALUE not in text and "pa ss" not in text


def test_the_local_run_does_not_use_ssh( run ):
    _, calls = run( "push-test-mock-login" )
    assert "compute ssh" not in calls and calls.count( "secrets versions access latest" ) == 2


@pytest.mark.parametrize( "email,password", [ ( "a'b@x.test", "ok" ), ( EMAIL, "it's" ) ] )
def test_a_value_with_a_single_quote_is_refused_before_anything_is_written( run, email, password ):
    done, calls = run( "push-test-mock-login", "vm", email=email, password=password )
    assert done.returncode == 1 and "single quote" in done.stderr
    assert "compute ssh" not in calls and not run.vm_file.exists() and password not in done.stderr


@pytest.mark.parametrize( "which,field", [ ( "email", "lupin-test-mock-jobs-email" ), ( "password", "lupin-test-mock-jobs-password" ) ] )
def test_an_empty_secret_is_refused_and_named( run, which, field ):
    done, calls = run( "push-test-mock-login", **{ which: "" } )
    assert done.returncode == 1 and f"Secret Manager {field} has no value" in done.stderr and not run.file.exists()


@pytest.mark.parametrize( "failing", [ "lupin-test-mock-jobs-email", "lupin-test-mock-jobs-password" ] )
def test_an_unreadable_secret_is_refused_and_named( run, failing ):
    done, _ = run( "push-test-mock-login", fails=failing )
    assert done.returncode == 1 and f"could not read Secret Manager {failing}" in done.stderr and not run.file.exists()


def test_an_unknown_target_is_refused( run ):
    done, calls = run( "push-test-mock-login", "cloud" )
    assert done.returncode == 1 and "local or vm" in done.stderr and calls == ""


def test_a_dry_run_reads_nothing_sends_nothing_and_shows_a_command_without_the_values( run ):
    done, calls = run( "--dry-run", "push-test-mock-login", "vm" )
    assert done.returncode == 0 and calls == "" and not run.file.exists()
    assert vr.ENV_FILE_REL in done.stdout and EMAIL not in done.stdout and ODD_VALUE not in done.stdout


def test_a_missing_project_id_fails_and_runs_nothing( run ):
    done, calls = run( "push-test-mock-login", project=None )
    assert done.returncode == 1 and calls == ""


def test_the_writer_refuses_an_empty_stdin_value( tmp_path ):
    text = SCRIPT.read_text()
    block = text[ text.index( "read -r -d '' RCMD_TM" ): text.index( "TMEOF\n        RCMD_TM=" ) ]
    block = block[ block.index( "\n" ) + 1: ]
    done = subprocess.run( [ "bash", "-c", f"rel='{vr.ENV_FILE_REL}'\n{block}" ], input="\n\n", capture_output=True, text=True, env={ **os.environ, "HOME": str( tmp_path ) } )
    assert done.returncode == 4 and "no value arrived" in done.stderr and not ( tmp_path / vr.ENV_FILE_REL ).exists()


def test_the_path_the_verb_writes_is_the_path_the_cron_lines_name( run ):
    run( "push-test-mock-login" )
    named = vr.env_file_path( { "HOME": str( run.file.parents[ 1 ] ) } )
    assert named == str( run.file ) and Path( named ).is_file()
    assert f"REUSE_VECTOR_REFRESH_ENV={named} " in vr.cron_lines( "/m", "/p", "/l", named )[ 0 ]


def test_the_verb_is_documented_in_the_usage_text( run ):
    done, _ = run( "--help" )
    assert "push-test-mock-login" in done.stderr + done.stdout
