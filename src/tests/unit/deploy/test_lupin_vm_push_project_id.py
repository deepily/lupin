"""
The push-project-id verb of lupin-vm.sh puts LUPIN_GCP_PROJECT_ID into the VM's env file.

The cloud-gpu compose file requires that variable, and the VM runs compose with
`--env-file cloud-gpu.env`, which drops the shell's environment. Without the line,
`docker compose config` and `ps` abort, and so does every svc verb.

gcloud is a stub on the path. Its ssh call runs the remote command locally on a scratch
file, and sudo is a pass-through shim.
"""
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT     = Path( os.environ.get( "LUPIN_ROOT", os.getcwd() ) )
SCRIPT   = ROOT / "src" / "scripts" / "lupin-vm.sh"
CONTRACT = ROOT / "src" / "conf" / "env-contract.tsv"
COMPOSE  = ROOT / "docker-compose.cloud-gpu.yml"
VM_ENV   = "/mnt/lupin-data/lupin/cloud-gpu.env"
VERB     = "push-project-id"

GCLOUD = r'''#!/bin/bash
echo "$*" >> "$STUB_CALLS"
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
    calls    = tmp_path / "calls.log"
    ( tmp_path / "gcloud" ).write_text( GCLOUD )
    ( tmp_path / "gcloud" ).chmod( 0o755 )
    ( tmp_path / "sudo" ).write_text( '#!/bin/bash\nexec "$@"\n' )
    ( tmp_path / "sudo" ).chmod( 0o755 )
    def run( *args, project="proj-x" ):
        env = { "PATH": f"{tmp_path}:{os.environ[ 'PATH' ]}", "HOME": str( tmp_path ),
                "STUB_CALLS": str( calls ), "STUB_ENV": str( env_file ) }
        if project is not None: env[ "LUPIN_GCP_PROJECT_ID" ] = project
        done = subprocess.run( [ "bash", str( SCRIPT ), *args ], capture_output=True, text=True, env=env )
        return done, ( calls.read_text() if calls.exists() else "" )
    run.env_file = env_file
    return run


def _lines( path ): return [ l for l in path.read_text().splitlines() if l.startswith( "LUPIN_GCP_PROJECT_ID=" ) ]


def test_a_missing_line_is_appended_and_the_rest_of_the_file_is_kept( vm ):
    vm.env_file.write_text( "DB_USER=lupin_app\n" )
    done, _ = vm( VERB )
    assert done.returncode == 0, done.stderr
    assert vm.env_file.read_text() == "DB_USER=lupin_app\nLUPIN_GCP_PROJECT_ID=proj-x\n"


def test_an_old_value_is_replaced_and_a_second_run_changes_nothing( vm ):
    vm.env_file.write_text( "A=1\nLUPIN_GCP_PROJECT_ID=old\nB=2\n" )
    vm( VERB )
    assert vm.env_file.read_text() == "A=1\nLUPIN_GCP_PROJECT_ID=proj-x\nB=2\n"
    again, _ = vm( VERB )
    assert "unchanged" in again.stdout and len( _lines( vm.env_file ) ) == 1


def test_a_value_an_env_file_could_misread_is_refused_before_any_ssh( vm ):
    vm.env_file.write_text( "A=1\n" )
    done, calls = vm( VERB, project="proj x;rm" )
    assert done.returncode != 0
    assert "compute ssh" not in calls and vm.env_file.read_text() == "A=1\n"


def test_the_project_id_the_compose_file_requires_has_a_compose_row_naming_this_verb():
    assert re.search( r"\$\{LUPIN_GCP_PROJECT_ID:\?", COMPOSE.read_text() ), "the compose file no longer requires it"
    rows = [ l.split( "\t" ) for l in CONTRACT.read_text().splitlines()
             if l.startswith( "LUPIN_GCP_PROJECT_ID\t" ) ]
    compose_rows = [ r for r in rows if r[ 1 ] == "COMPOSE" ]
    assert len( compose_rows ) == 1, f"expected one COMPOSE row, found {len( compose_rows )}"
    assert VERB in compose_rows[ 0 ][ 2 ], "the row's writer must name the verb that writes the line"
    assert f"{VERB})" in SCRIPT.read_text(), "the verb the row names does not exist in lupin-vm.sh"
