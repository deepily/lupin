"""
`lupin-vm.sh vm-start` picks `resume` for a SUSPENDED instance and `start` for a TERMINATED one,
says which it ran, and a missing LUPIN_GCP_PROJECT_ID fails with a plain message.

The VM is suspended-by-default, and `gcloud compute instances start` refuses a SUSPENDED
instance. gcloud is replaced by a stub on PATH that answers `describe` with a chosen state and
records every call, so nothing touches a real project.
"""
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) ) / "src" / "scripts" / "lupin-vm.sh"


@pytest.fixture
def gcloud_stub( tmp_path ):
    calls = tmp_path / "calls.log"
    stub  = tmp_path / "gcloud"
    stub.write_text( '#!/bin/bash\necho "$*" >> "$STUB_CALLS"\n'
                     '[ "$3" = "describe" ] && echo "$STUB_STATE"\nexit 0\n' )
    stub.chmod( 0o755 )
    return tmp_path, calls


def _run( gcloud_stub, state, *args, project="proj-x" ):
    tmp_path, calls = gcloud_stub
    env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_STATE": state, "STUB_CALLS": str( calls ),
            "HOME": str( tmp_path ) }
    if project is not None: env[ "LUPIN_GCP_PROJECT_ID" ] = project
    out  = subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env )
    seen = calls.read_text().splitlines() if calls.exists() else [ ]
    return out, seen


@pytest.mark.parametrize( "state, verb", [ ( "SUSPENDED", "resume" ), ( "SUSPENDING", "resume" ),
                                           ( "TERMINATED", "start" ), ( "STOPPED", "start" ) ] )
def test_the_verb_follows_the_instance_state_and_is_reported( gcloud_stub, state, verb ):
    out, seen = _run( gcloud_stub, state, "vm-start" )
    assert out.returncode == 0, out.stderr
    assert any( c.startswith( f"compute instances {verb} " ) for c in seen ), seen
    assert len( [ c for c in seen if " describe " not in c ] ) == 1, seen          # exactly one action, and it is the right one
    assert f"is {state}: running 'instances {verb}'" in out.stdout


def test_a_running_instance_is_left_alone_and_says_so( gcloud_stub ):
    out, seen = _run( gcloud_stub, "RUNNING", "vm-start" )
    assert out.returncode == 0 and "already RUNNING" in out.stdout
    assert all( " describe " in c for c in seen ), seen


def test_a_transitional_state_is_refused_without_acting( gcloud_stub ):
    out, seen = _run( gcloud_stub, "STAGING", "vm-start" )
    assert out.returncode == 1 and "STAGING" in out.stderr
    assert all( " describe " in c for c in seen ), seen


def test_an_unreadable_state_is_refused( tmp_path ):
    stub = tmp_path / "gcloud"
    stub.write_text( "#!/bin/bash\nexit 1\n" ); stub.chmod( 0o755 )
    env  = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "LUPIN_GCP_PROJECT_ID": "p", "HOME": str( tmp_path ) }
    out  = subprocess.run( [ "bash", str( SCRIPT ), "vm-start" ], capture_output=True, text=True, env=env )
    assert out.returncode == 1 and "could not read the state" in out.stderr


def test_a_missing_project_id_fails_with_a_plain_message_and_runs_nothing( gcloud_stub ):
    out, seen = _run( gcloud_stub, "SUSPENDED", "vm-start", project=None )
    assert out.returncode == 1 and seen == [ ]
    assert "LUPIN_GCP_PROJECT_ID is not set" in out.stderr and "unbound variable" not in out.stderr


def test_dry_run_works_without_a_project_and_acts_on_nothing( gcloud_stub ):
    out, seen = _run( gcloud_stub, "SUSPENDED", "--dry-run", "vm-start", project=None )
    assert out.returncode == 0 and seen == [ ]
    assert "<LUPIN_GCP_PROJECT_ID>" in out.stdout and "SUSPENDED -> resume" in out.stdout


def test_help_needs_no_project( gcloud_stub ):
    out, seen = _run( gcloud_stub, "RUNNING", "--help", project=None )
    assert out.returncode == 0 and seen == [ ]
    assert "vm-start" in out.stderr and "resume" in out.stderr                      # usage() prints to stderr
