"""
Tests for the push-test-login verb of lupin-vm.sh.

The verb puts the test role's password into the VM's env file. It must never put it in a command line.
gcloud is a stub on the path. Its ssh call logs the arguments and runs the remote command locally.
That command works on a scratch file, and sudo is a pass-through shim.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "lupin-vm.sh"
VM_ENV = "/mnt/lupin-data/lupin/cloud-gpu.env"
FAKE_VALUE = "placeholder" + "-value_42"

GCLOUD = r'''#!/bin/bash
echo "$*" >> "$STUB_CALLS"
if [ "$1" = "secrets" ]; then
    [ -n "$STUB_SECRET_FAILS" ] && exit 1
    printf '%s\n' "$STUB_SECRET"; exit 0
fi
if [ "$1" = "compute" ] && [ "$2" = "ssh" ]; then
    while [ $# -gt 0 ]; do [ "$1" = "--command" ] && { cmd="$2"; break; }; shift; done
    cmd="${cmd//\/mnt\/lupin-data\/lupin\/cloud-gpu.env/$STUB_ENV}"
    bash -c "$cmd"; exit $?
fi
exit 0
'''


@pytest.fixture
def vm( tmp_path ):
    env_file = tmp_path / "cloud-gpu.env"
    calls = tmp_path / "calls.log"
    ( tmp_path / "gcloud" ).write_text( GCLOUD )
    ( tmp_path / "gcloud" ).chmod( 0o755 )
    ( tmp_path / "sudo" ).write_text( '#!/bin/bash\nexec "$@"\n' )
    ( tmp_path / "sudo" ).chmod( 0o755 )
    ( tmp_path / "install" ).write_text( '#!/bin/bash\necho "$*" >> "$STUB_INSTALL"\nexec /usr/bin/install "$@"\n' )
    ( tmp_path / "install" ).chmod( 0o755 )
    def run( *args, secret=FAKE_VALUE, project="proj-x", secret_fails="" ):
        env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ), "STUB_CALLS": str( calls ),
                "STUB_SECRET": secret, "STUB_SECRET_FAILS": secret_fails, "STUB_ENV": str( env_file ),
                "STUB_INSTALL": str( tmp_path / "install.log" ) }
        if project is not None: env[ "LUPIN_GCP_PROJECT_ID" ] = project
        done = subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env )
        return done, ( calls.read_text() if calls.exists() else "" )
    run.env_file = env_file
    run.install_log = tmp_path / "install.log"
    return run


def _values( path ): return [ l for l in path.read_text().splitlines() if l.startswith( "LUPIN_TEST_DB_PASSWORD=" ) ]


def test_a_missing_line_is_appended_and_the_rest_of_the_file_is_kept( vm ):
    vm.env_file.write_text( "DB_USER=lupin_app\nOTHER=1\n" )
    done, _ = vm( "push-test-login" )
    assert done.returncode == 0, done.stderr
    assert vm.env_file.read_text() == f"DB_USER=lupin_app\nOTHER=1\nLUPIN_TEST_DB_PASSWORD={FAKE_VALUE}\n"
    assert "LUPIN_TEST_DB_PASSWORD: set" in done.stdout


def test_an_existing_line_is_replaced_in_place_and_a_second_run_changes_nothing( vm ):
    vm.env_file.write_text( "A=1\nLUPIN_TEST_DB_PASSWORD=old\nB=2\n" )
    done, _ = vm( "push-test-login" )
    assert vm.env_file.read_text() == f"A=1\nLUPIN_TEST_DB_PASSWORD={FAKE_VALUE}\nB=2\n" and "replaced" in done.stdout
    again, _ = vm( "push-test-login" )
    assert "LUPIN_TEST_DB_PASSWORD: unchanged" in again.stdout and len( _values( vm.env_file ) ) == 1


def test_a_commented_line_and_a_longer_key_are_left_alone( vm ):
    vm.env_file.write_text( "#LUPIN_TEST_DB_PASSWORD=old\nLUPIN_TEST_DB_PASSWORD_FILE=/x\n" )
    vm( "push-test-login" )
    text = vm.env_file.read_text()
    assert "#LUPIN_TEST_DB_PASSWORD=old\n" in text and "LUPIN_TEST_DB_PASSWORD_FILE=/x\n" in text
    assert _values( vm.env_file ) == [ f"LUPIN_TEST_DB_PASSWORD={FAKE_VALUE}" ]


def test_the_files_mode_and_owner_are_kept( vm ):
    vm.env_file.write_text( "A=1\n" )
    vm.env_file.chmod( 0o640 )
    vm( "push-test-login" )
    assert oct( vm.env_file.stat().st_mode & 0o777 ) == "0o640"
    wanted = f"-o {os.getuid()} -g {os.getgid()} -m 640 "
    assert wanted in vm.install_log.read_text(), f"install was not told the owner and mode: {vm.install_log.read_text()}"


def test_the_value_is_in_no_command_line_and_no_output( vm ):
    vm.env_file.write_text( "A=1\n" )
    done, calls = vm( "push-test-login" )
    assert FAKE_VALUE not in calls and FAKE_VALUE not in done.stdout and FAKE_VALUE not in done.stderr


def test_a_missing_env_file_on_the_vm_is_refused_and_nothing_is_created( vm ):
    done, _ = vm( "push-test-login" )
    assert done.returncode != 0 and "create it first" in done.stderr and not vm.env_file.exists()


@pytest.mark.parametrize( "secret", [ 'a b', 'a"b', "a'b", "a$b", "a#b", "a`b", "a;b" ] )
def test_a_value_an_env_file_could_misread_is_refused_before_any_ssh( vm, secret ):
    vm.env_file.write_text( "A=1\n" )
    done, calls = vm( "push-test-login", secret=secret )
    assert done.returncode == 1 and "characters an env file may misread" in done.stderr
    assert "compute ssh" not in calls and vm.env_file.read_text() == "A=1\n"
    assert secret not in done.stdout + done.stderr


def test_an_empty_secret_is_refused_before_any_ssh( vm ):
    done, calls = vm( "push-test-login", secret="" )
    assert done.returncode == 1 and "has no value" in done.stderr and "compute ssh" not in calls


def test_an_unreadable_secret_is_refused_before_any_ssh( vm ):
    done, calls = vm( "push-test-login", secret_fails="1" )
    assert done.returncode == 1 and "could not read Secret Manager" in done.stderr and "compute ssh" not in calls


def test_a_dry_run_reads_nothing_and_sends_nothing_and_shows_a_command_without_the_value( vm ):
    done, calls = vm( "--dry-run", "push-test-login" )
    assert done.returncode == 0 and calls == "" and "LUPIN_TEST_DB_PASSWORD" in done.stdout
    assert FAKE_VALUE not in done.stdout


def test_a_missing_project_id_fails_and_runs_nothing( vm ):
    done, calls = vm( "push-test-login", project=None )
    assert done.returncode == 1 and calls == ""


def test_the_verb_is_documented_in_the_usage_text( vm ):
    done, _ = vm( "--help" )
    assert "push-test-login" in done.stderr + done.stdout


def test_the_vm_preflight_remedy_names_the_verb():
    text  = open( SCRIPT.parent / "preflight-vm.sh" ).read()
    block = text[ text.index( "# B8 —" ): text.index( "if layer_runs B; then" ) ]
    assert "lupin-vm.sh push-test-login" in block[ block.index( "PLAIN)" ): block.index( "*)" ) ]
