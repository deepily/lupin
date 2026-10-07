"""
`lupin-vm.sh --dry-run deploy` prints what it would do and contacts nothing.

The deploy arm ran its pre-deploy preflight over SSH and ignored the dry-run flag.
A dry run with a real project id reached the VM.

gcloud is a stub on the search path. It records every call, so no project is touched.
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
    stub.write_text( '#!/bin/bash\necho "$*" >> "$STUB_CALLS"\nexit 0\n' )
    stub.chmod( 0o755 )
    return tmp_path, calls


def _dry_run_deploy( gcloud_stub, **extra_env ):
    tmp_path, calls = gcloud_stub
    env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "STUB_CALLS": str( calls ),
            "LUPIN_GCP_PROJECT_ID": "a-real-looking-project", "HOME": str( tmp_path ), **extra_env }
    out  = subprocess.run( [ "bash", str( SCRIPT ), "--dry-run", "deploy" ], capture_output=True, text=True, env=env )
    seen = calls.read_text().splitlines() if calls.exists() else [ ]
    return out, seen


def test_a_dry_run_deploy_contacts_the_vm_not_once( gcloud_stub ):
    out, seen = _dry_run_deploy( gcloud_stub )
    assert out.returncode == 0, out.stderr
    assert seen == [ ], seen


def test_a_dry_run_deploy_says_it_would_run_the_pre_deploy_preflight( gcloud_stub ):
    out, seen = _dry_run_deploy( gcloud_stub )
    assert "(dry-run) PRE-deploy preflight on VM" in out.stdout + out.stderr
    assert "preflight-vm.sh --phase pre" in out.stdout + out.stderr


def test_the_skip_flag_does_not_make_a_dry_run_contact_the_vm( gcloud_stub ):
    out, seen = _dry_run_deploy( gcloud_stub, LUPIN_SKIP_PREFLIGHT="1" )
    assert out.returncode == 0, out.stderr
    assert seen == [ ], seen
