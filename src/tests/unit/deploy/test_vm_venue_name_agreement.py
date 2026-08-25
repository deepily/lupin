"""
Guard for row 0d175dac — the cloud venue names disagree with what the files do,
and two of those disagreements are live instructions rather than cosmetics.

MEASURED 2026-08-25 at sha 7394cab1, against the real project (read-only):

    $ gcloud compute instances list
    lupin-host-test  us-central1-a  e2-standard-8  RUNNING     <- the only VM
    $ gcloud compute instances describe lupin-host-test --format='yaml(guestAccelerators)'
                                                                <- no such field: ZERO GPUs

So the one host we have cannot run a container that reserves an nvidia device at
all. And the compose files are named the other way round from what they hold:

    docker-compose.cloud-gpu.yml   no nvidia/cuda/deploy.resources anywhere;
                                   its own line 253 says the model server is
                                   "INTENTIONALLY OMITTED" (it runs on Cloud Run)
    docker-compose.cloud-test.yml  DOES carry lupin-model-server with
                                   driver: nvidia / capabilities: [gpu] (line 196+)

The rename that reconciles those names touches 35 tracked code files and 209
occurrences of seven identifiers, so it is a coordinated change with its own
test pass and is NOT done here. What IS pinned here are the three statements
that were false at that sha and are cheap to keep true:

  1. cloud-gpu.env / cloud-test.env are git-ignored. Four places in the tree
     already CALLED them git-ignored (docker-compose.cloud-gpu.yml:18,
     preflight-vm-lib.sh:224, lupin-vm.sh:45, vm-unversioned-manifest.tsv:44)
     and `git check-ignore` returned nothing for either. Per env-contract.tsv
     they carry DB_PASSWORD (SECRET) and JWT_SECRET_KEY — the same content the
     `.env` rule exists to keep out of a tracked file (row adce3547).

  2. provision-arbiter-on-vm.sh does not send an operator at a container the VM
     does not run. Its final heredoc printed
     `docker restart lupin-rest-cloud-test` as a "bounce-survival check"; that
     container exists on lupin-host-test in no state, so the check errors out
     and proves nothing. lupin-app.ini was corrected cloud-test -> cloud-gpu for
     this exact VM on 2026-07-22 (see its own note at the key) and the
     provisioning script never followed.

  3. The compose file the live deploy path actually uses (lupin-vm.sh's
     COMPOSE_FILE) requires no GPU device. This is the one that would break
     production rather than confuse a reader: point the deploy path at the
     GPU-bearing file and `up` fails on a host with no accelerator.

Analysis of record: src/rnd/v0.2.0/2026.08.24-two-deploy-scripts-and-the-venue-names.md
"""

import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path( __file__ ).resolve().parents[ 4 ]

VM_ENV_FILES       = [ "cloud-gpu.env", "cloud-test.env" ]
VM_ENV_EXAMPLE     = "cloud-test.env.example"
PROVISION_SCRIPT   = REPO_ROOT / "src/scripts/provision-arbiter-on-vm.sh"
LUPIN_VM_SCRIPT    = REPO_ROOT / "src/scripts/lupin-vm.sh"
LUPIN_APP_INI      = REPO_ROOT / "src/conf/lupin-app.ini"
GCS_BLOCK          = "Lupin: Testing-GCS"
WATCH_KEY          = "arbiter health watch containers"


def _git_ignores( rel_path ):
    """
    Ask git itself, not the .gitignore text. `git check-ignore` is the authority:
    it honors precedence, negations and nested .gitignore files, none of which a
    substring search over the top-level file would see.

    Returns True when git would ignore <rel_path>, False when it would not.
    """
    proc = subprocess.run(
        [ "git", "check-ignore", "-q", "--no-index", rel_path ],
        cwd=REPO_ROOT, capture_output=True
    )
    if proc.returncode not in ( 0, 1 ):
        pytest.skip( f"git check-ignore unusable here (rc={proc.returncode}): {proc.stderr!r}" )
    return proc.returncode == 0


def _container_names( compose_rel ):
    services = yaml.safe_load( ( REPO_ROOT / compose_rel ).read_text() )[ "services" ]
    return { svc[ "container_name" ] for svc in services.values() if "container_name" in svc }


def _ini_watch_containers():
    """
    The [Lupin: Testing-GCS] value of `arbiter health watch containers`, as a set.
    That block is the VM's config, so it is the in-repo authority for which
    containers the GCP test VM runs.
    """
    text  = LUPIN_APP_INI.read_text()
    start = text.index( f"[{GCS_BLOCK}]" )
    nxt   = text.find( "\n[", start + 1 )
    block = text[ start : nxt if nxt != -1 else len( text ) ]
    for line in block.splitlines():
        if line.strip().startswith( WATCH_KEY ):
            return { c.strip() for c in line.split( "=", 1 )[ 1 ].split( "," ) if c.strip() }
    raise AssertionError( f"'{WATCH_KEY}' not found in [{GCS_BLOCK}] — the premise moved" )


def _shell_var( script_path, name ):
    m = re.search( rf'^{name}="([^"]+)"', script_path.read_text(), re.M )
    assert m, f"{name} not assigned in {script_path.name} — the premise moved"
    return m.group( 1 )


# --- 1. the VM env files are what four other files already call them ----------

@pytest.mark.parametrize( "env_file", VM_ENV_FILES )
def test_vm_compose_env_files_are_git_ignored( env_file ):
    assert _git_ignores( env_file ), (
        f"{env_file} is NOT git-ignored. It carries DB_PASSWORD and JWT_SECRET_KEY "
        f"per src/conf/env-contract.tsv, and four places in the tree already "
        f"describe it as git-ignored. Add it to .gitignore beside the `.env` rule."
    )


def test_the_tracked_example_stays_tracked():
    """
    Negative control. A rule broad enough to swallow `cloud-test.env.example`
    would silently untrack the one file a new deployer copies from, so the
    ignore must be exact rather than a `cloud-*.env*` glob.
    """
    assert not _git_ignores( VM_ENV_EXAMPLE ), (
        f"{VM_ENV_EXAMPLE} must remain tracked — it is the copy-from template."
    )


# --- 2. the provisioning script points the operator at containers that exist --

def test_premise_the_two_compose_files_name_different_rest_containers():
    """
    Derive the container names from the compose files rather than hardcoding
    them, so this file does not quietly outlive a rename it cannot see.

    Only the VENUE-SUFFIXED containers are expected to differ. The two Cloud SQL
    sidecars (lupin-cloudsql-proxy, lupin-cloudsql-socket-init) carry the SAME
    container_name in both files on purpose — they are the same service either
    way. That shared prefix space is exactly why dctl_venue_present matches
    whole-line-exact: `lupin-rest` is a prefix of `lupin-rest-cloud-gpu`, and a
    substring test would report a cloud-test container present on a cloud-gpu VM.
    """
    gpu_rest  = { n for n in _container_names( "docker-compose.cloud-gpu.yml"  ) if n.startswith( "lupin-rest-" ) }
    test_rest = { n for n in _container_names( "docker-compose.cloud-test.yml" ) if n.startswith( "lupin-rest-" ) }

    assert gpu_rest and test_rest, "each cloud compose file must name a lupin-rest-* container"
    assert gpu_rest & test_rest == set(), (
        f"the two cloud compose files now share a rest container_name "
        f"({sorted( gpu_rest & test_rest )}); the collision this guard reasons "
        f"about has changed shape — re-read row 0d175dac"
    )


def test_provision_script_names_only_containers_the_vm_runs():
    """
    provision-arbiter-on-vm.sh brings up the :8001 arbiter on lupin-host-test and
    PRINTS operator steps. Any lupin-rest-* container it names in those steps must
    be one the VM actually runs, i.e. one the [Lupin: Testing-GCS] watch list
    knows about — otherwise the operator runs a command against nothing.
    """
    watched   = _ini_watch_containers()
    mentioned = set( re.findall( r"\blupin-rest-cloud-[a-z]+\b", PROVISION_SCRIPT.read_text() ) )
    assert mentioned, "no lupin-rest-cloud-* mention found — the premise moved"

    stray = { m for m in mentioned if m not in watched }
    assert not stray, (
        f"provision-arbiter-on-vm.sh names {sorted( stray )}, which "
        f"[{GCS_BLOCK}] does not watch (it watches {sorted( watched )}). "
        f"That container does not exist on lupin-host-test, so the operator step "
        f"quoting it addresses nothing."
    )


# --- 3. the live deploy path does not require hardware the only VM lacks ------

def test_live_deploy_compose_file_requires_no_gpu_device():
    """
    lupin-vm.sh is the working deploy path. The single VM (lupin-host-test) is an
    e2-standard-8 with no guestAccelerators, so if COMPOSE_FILE ever pointed at a
    file reserving an nvidia device, `docker compose up` would fail on the host.
    """
    compose_rel = _shell_var( LUPIN_VM_SCRIPT, "COMPOSE_FILE" )
    body        = ( REPO_ROOT / compose_rel ).read_text()

    for marker in ( "driver: nvidia", "capabilities: [gpu]", "device_requests" ):
        assert marker not in body, (
            f"{compose_rel} is the file lupin-vm.sh deploys, and it now contains "
            f"'{marker}'. lupin-host-test has no GPU attached — `up` would fail. "
            f"Either the VM gained an accelerator or the deploy path was repointed."
        )


def test_premise_the_other_cloud_file_is_the_gpu_bearing_one():
    """
    The inversion this row exists to reconcile, pinned so it cannot be quietly
    'fixed' by moving the GPU block instead of moving the names: the file NOT
    named for a GPU is the one that reserves one.
    """
    test_body = ( REPO_ROOT / "docker-compose.cloud-test.yml" ).read_text()
    gpu_body  = ( REPO_ROOT / "docker-compose.cloud-gpu.yml"  ).read_text()

    assert "driver: nvidia" in test_body, (
        "docker-compose.cloud-test.yml no longer reserves a GPU. If the GPU block "
        "moved to the cloud-gpu file, the names finally agree — delete this test "
        "and close row 0d175dac."
    )
    assert "driver: nvidia" not in gpu_body, (
        "docker-compose.cloud-gpu.yml now reserves a GPU. Re-read "
        "test_live_deploy_compose_file_requires_no_gpu_device — the VM has none."
    )
