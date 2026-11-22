"""
The push-jev-key verb of lupin-vm.sh and the preflight's Jev key check.

cctmx on the VM gives a seat the Jev key only when its launching shell holds JEV_API_TOASTER.
Nothing ever put the key on the VM. The verb writes it to an owner-only file that ~/.bashrc sources.
The preflight function checks both halves. gcloud is a stub on the path. Its ssh call runs the
remote command locally, with the home folder set to a scratch folder. Venue: :7999 (unit).
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT        = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
SCRIPT      = ROOT / "src" / "scripts" / "lupin-vm.sh"
LIB         = ROOT / "src" / "scripts" / "lib" / "preflight-vm-lib.sh"
RUNNER      = ROOT / "src" / "scripts" / "preflight-vm.sh"
VERB        = "push-jev-key"
KEY         = "jev-test-key-0123456789abcdef"
SOURCE_LINE = "[ -r ~/.lupin/jev.env ] && . ~/.lupin/jev.env"

GCLOUD = r'''#!/bin/bash
echo "$*" >> "$STUB_CALLS"
if [ "$1" = "compute" ] && [ "$2" = "ssh" ]; then
    while [ $# -gt 0 ]; do [ "$1" = "--command" ] && { cmd="$2"; break; }; shift; done
    bash -c "$cmd"; exit $?
fi
exit 0
'''


@pytest.fixture
def vm( tmp_path ):
    calls = tmp_path / "calls.log"
    ( tmp_path / "gcloud" ).write_text( GCLOUD )
    ( tmp_path / "gcloud" ).chmod( 0o755 )
    def run( *args, key=KEY ):
        env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ),
                "STUB_CALLS": str( calls ), "LUPIN_GCP_PROJECT_ID": "proj-x" }
        if key is not None: env[ "JEV_API_TOASTER" ] = key
        done = subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env, timeout=60 )
        return done, ( calls.read_text() if calls.exists() else "" )
    run.home = tmp_path
    return run


def _status( key_file, bashrc ):
    r = subprocess.run( [ "bash", "-c", f"source '{LIB}'; pfv_jev_key_status '{key_file}' '{bashrc}'" ],
                        capture_output=True, text=True, timeout=30 )
    return r.returncode, r.stdout


def test_the_key_lands_owner_only_and_bashrc_sources_it_and_the_preflight_says_ok( vm ):
    ( vm.home / ".bashrc" ).write_text( "# stock\n" )
    done, calls = vm( VERB )
    assert done.returncode == 0, done.stderr
    key_file = vm.home / ".lupin" / "jev.env"
    assert key_file.read_text() == f"export JEV_API_TOASTER='{KEY}'\n"
    assert oct( key_file.stat().st_mode & 0o777 ) == "0o600"
    assert ( vm.home / ".bashrc" ).read_text() == f"# stock\n{SOURCE_LINE}\n"
    assert "jev.env: set" in done.stdout
    assert KEY not in calls and KEY not in done.stdout and KEY not in done.stderr
    assert _status( key_file, vm.home / ".bashrc" ) == ( 0, "OK" )


def test_a_second_run_changes_nothing_and_a_new_key_replaces_the_old( vm ):
    vm( VERB )
    again, _ = vm( VERB )
    assert "jev.env: unchanged" in again.stdout
    assert ( vm.home / ".bashrc" ).read_text().count( SOURCE_LINE ) == 1
    newer, _ = vm( VERB, key="another-key-42" )
    assert "jev.env: replaced" in newer.stdout
    assert ( vm.home / ".lupin" / "jev.env" ).read_text() == "export JEV_API_TOASTER='another-key-42'\n"


def test_a_shell_that_sources_the_written_bashrc_gets_the_key_even_after_a_last_line_with_no_newline( vm ):
    ( vm.home / ".bashrc" ).write_text( "alias ll='ls -l'" )
    vm( VERB )
    assert ( vm.home / ".bashrc" ).read_text() == f"alias ll='ls -l'\n{SOURCE_LINE}\n"
    out = subprocess.run( [ "bash", "-c", "source ~/.bashrc; printf '%s' \"$JEV_API_TOASTER\"" ],
                          capture_output=True, text=True, env={ "HOME": str( vm.home ), "PATH": os.environ[ "PATH" ] } )
    assert out.stdout == KEY


@pytest.mark.parametrize( "key", [ None, "", "has space", "quote'in", "semi;colon" ] )
def test_no_key_or_a_key_the_launcher_would_refuse_sends_nothing( vm, key ):
    done, calls = vm( VERB, key=key )
    assert done.returncode != 0
    assert "compute ssh" not in calls and not ( vm.home / ".lupin" / "jev.env" ).exists()


def test_the_dry_run_prints_the_command_without_the_key_and_touches_nothing( vm ):
    done, calls = vm( "--dry-run", VERB )
    assert done.returncode == 0, done.stderr
    assert "compute ssh" not in calls and KEY not in done.stdout + done.stderr
    assert not ( vm.home / ".lupin" ).exists()


@pytest.mark.parametrize( "setup,expected", [
    ( "none",       ( 1, "MISSING" ) ),
    ( "mode644",    ( 2, "MODE:644" ) ),
    ( "empty",      ( 3, "EMPTY" ) ),
    ( "unsourced",  ( 4, "UNSOURCED" ) ),
] )
def test_the_preflight_names_the_first_half_that_fails( tmp_path, setup, expected ):
    key_file, bashrc = tmp_path / "jev.env", tmp_path / ".bashrc"
    bashrc.write_text( f"{SOURCE_LINE}\n" )
    if setup != "none":
        key_file.write_text( "export JEV_API_TOASTER=''\n" if setup == "empty" else f"export JEV_API_TOASTER='{KEY}'\n" )
        key_file.chmod( 0o644 if setup == "mode644" else 0o600 )
    if setup == "unsourced": bashrc.write_text( "# no source line\n" )
    code, out = _status( key_file, bashrc )
    assert ( code, out ) == expected and KEY not in out


def test_the_verb_and_the_preflight_agree_on_the_source_line_and_the_runner_reports_at_warn():
    assert f"JK_SOURCE_LINE='{SOURCE_LINE}'" in SCRIPT.read_text()
    assert f"PFV_JEV_SOURCE_LINE='{SOURCE_LINE}'" in LIB.read_text()
    text  = RUNNER.read_text()
    block = text[ text.index( "# B13 —" ): ]
    block = block[ : block.index( "esac" ) ]
    assert 'pfv_jev_key_status "$JEV_FILE" "$HOME/.bashrc"' in block
    assert "BLOCK" not in block and block.count( "WARN" ) >= 3 and "push-jev-key" in block


def test_deploy_runs_the_verb_after_the_code_sync():
    text   = SCRIPT.read_text()
    deploy = text[ text.index( "    deploy)" ): text.index( "    push-unversioned)" ) ]
    assert "JK_ARGS=( push-jev-key )" in deploy
    assert deploy.index( "do_push_bundle" ) < deploy.index( "JK_ARGS=( push-jev-key )" )
