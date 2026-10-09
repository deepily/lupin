"""
The VM preflight check for the test role's password in the env file.

The check is a sourced function plus a block in the runner. The function is driven with scratch
env files, and the runner's block is pinned by its text. Venue: :7999 (unit).
"""

import os
import subprocess

import pytest

ROOT   = os.environ[ "LUPIN_ROOT" ]
LIB    = os.path.join( ROOT, "src/scripts/lib/preflight-vm-lib.sh" )
RUNNER = os.path.join( ROOT, "src/scripts/preflight-vm.sh" )


def _status( path ):
    r = subprocess.run( [ "bash", "-c", f"source '{LIB}'; pfv_test_login_env_status '{path}'" ], capture_output=True, text=True, timeout=30 )
    return r.returncode, r.stdout


@pytest.mark.parametrize( "text,expected", [
    ( "LUPIN_TEST_DB_PASSWORD=abc\n",                   ( 0, "SUPPLIED" ) ),
    ( "export LUPIN_TEST_DB_PASSWORD=\"abc\"\n",        ( 0, "SUPPLIED" ) ),
    ( "LUPIN_TEST_DB_PASSWORD=\n",                      ( 1, "PLAIN" ) ),
    ( "LUPIN_TEST_DB_PASSWORD=\"\"\n",                  ( 1, "PLAIN" ) ),
    ( "OTHER=1\n",                                      ( 1, "PLAIN" ) ),
    ( "# LUPIN_TEST_DB_PASSWORD=abc\n",                 ( 1, "PLAIN" ) ),
] )
def test_the_status_names_supplied_and_plain( tmp_path, text, expected ):
    path = tmp_path / "cloud-gpu.env"
    path.write_text( text )
    assert _status( path ) == expected


def test_an_unreadable_file_is_named_not_called_plain( tmp_path ):
    assert _status( tmp_path / "nowhere.env" ) == ( 3, "UNREADABLE" )


def test_the_status_never_prints_the_value( tmp_path ):
    path = tmp_path / "cloud-gpu.env"
    path.write_text( "LUPIN_TEST_DB_PASSWORD=hunter2-never-printed\n" )
    assert "hunter2" not in "".join( _status( path )[ 1: ] )


def test_the_runner_reports_the_three_states_as_warn_tier_and_names_the_secret():
    text  = open( RUNNER ).read()
    block = text[ text.index( "# B8 —" ): text.index( "if layer_runs B; then" ) ]
    assert 'pfv_test_login_env_status "$ENV_FILE"' in block
    assert block.count( "WARN" ) >= 3 and "BLOCK" not in block
    assert "lupin-db-test-password" in block and "report pass" in block and "report unknown" in block
    assert subprocess.run( [ "bash", "-n", RUNNER ] ).returncode == 0
