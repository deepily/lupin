"""
Live E2E for deploy-cloud-test.sh (task d8c699aa) — §5 of the design doc
`src/rnd/2026.06.23-gcp-code-sync-to-runtime-design.md`.

This is the REPRODUCIBLE form of the "axis-A + rollback" live proof. It is
**env-gated**: it touches the real GCP cloud-test VM (`lupin-host-test`) via
`gcloud compute ssh --tunnel-through-iap` and mutates the running
`lupin-rest-cloud-test` container, so it is SKIPPED unless
`LUPIN_E2E_DEPLOY_LIVE=1` is set. It must NEVER run in the unit/merge gate.

Venue: the cloud-test VM (real infra) — NOT :7999 / :8000. Prerequisites:
  - `gcloud` authenticated with IAP access to `lupin-host-test`.
  - The VM is RUNNING and the rest container is currently healthy.
  - `LUPIN_E2E_DEPLOY_LIVE=1` in the environment.

What it proves (design §5):
  - **Axis-A (code)**: a committed marker rides the `./src` bind-mount,
    the container restarts, and `.deployed-ref` records the exact SHA + axis.
  - **Rollback**: a deliberately-broken ref fails the health-gate and the
    prior healthy `src/` is auto-restored (`.bak` swap); `.deployed-ref`
    is NOT advanced to the broken SHA.
  - **Axis-B (deps)**: documented-skip — a real image rebuild + AR push is
    heavy + costs money + bumps the live tag; the axis-DETECT logic is
    fully unit-tested in `src/tests/unit/deploy/test_deploy_cloud_test_lib.py`,
    and axis-B was exercised by hand during the 2026-06-23 FCM 1.2.0 deploy.

The harness leaves the VM at a CLEAN committed HEAD with a `.deployed-ref`
stamp (a better state than the hand-synced pre-test state) and deletes every
throwaway branch + `src.bak-*` it created.

Author: Tiberius 👑 (session 6ec69a8c) — 2026-06-23.
"""

import os
import subprocess
import time
import uuid

import pytest

# ---------------------------------------------------------------------------
# Env gate — this is the ONLY thing that lets the module's tests run.
# ---------------------------------------------------------------------------
_LIVE          = os.environ.get( "LUPIN_E2E_DEPLOY_LIVE" ) == "1"
_SKIP_REASON   = "live deploy E2E — set LUPIN_E2E_DEPLOY_LIVE=1 to run (mutates the GCP cloud-test VM)"
pytestmark     = pytest.mark.skipif( not _LIVE, reason=_SKIP_REASON )

# ---------------------------------------------------------------------------
# Constants — mirror deploy-cloud-test.sh §config.
# ---------------------------------------------------------------------------
LUPIN_ROOT     = os.environ.get( "LUPIN_ROOT", os.getcwd() )
DEPLOY_SCRIPT  = os.path.join( LUPIN_ROOT, "src", "scripts", "deploy-cloud-test.sh" )

VM_NAME        = "lupin-host-test"
VM_ZONE        = "us-central1-a"
VM_ROOT        = "/mnt/lupin-data/lupin"
REST_CONTAINER = "lupin-rest-cloud-test"
DEPLOYED_REF   = f"{VM_ROOT}/.deployed-ref"
MARKER_REL     = "src/conf/.deploy-probe"                 # rides the bind-mount
MARKER_IN_CTR  = "/var/lupin/src/conf/.deploy-probe"      # bind-mount target
MAIN_REL       = "src/lupin_app/main.py"                  # break target for rollback

SSH_PREFIX     = [ "gcloud", "compute", "ssh", VM_NAME, f"--zone={VM_ZONE}",
                   "--tunnel-through-iap", "--command" ]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------
def _git( *args, check=True ):
    """Run a git command in LUPIN_ROOT; return stripped stdout."""
    r = subprocess.run( [ "git", *args ], cwd=LUPIN_ROOT,
                        capture_output=True, text=True )
    if check and r.returncode != 0:
        raise RuntimeError( f"git {' '.join( args )} failed: {r.stderr.strip()}" )
    return r.stdout.strip()


def _ssh( remote_cmd, timeout=240 ):
    """Run a command on the VM over IAP SSH; return CompletedProcess."""
    return subprocess.run( [ *SSH_PREFIX, remote_cmd ],
                           capture_output=True, text=True, timeout=timeout )


def _deployed_ref_sha():
    """The SHA recorded in the VM's .deployed-ref (empty string if none)."""
    r = _ssh( f"cat {DEPLOYED_REF} 2>/dev/null | awk '{{print $1}}'", timeout=120 )
    return ( r.stdout or "" ).strip()


def _deployed_ref_axis():
    """The axis field (3rd col) recorded in .deployed-ref (empty if none)."""
    r = _ssh( f"cat {DEPLOYED_REF} 2>/dev/null | awk '{{print $3}}'", timeout=120 )
    return ( r.stdout or "" ).strip()


def _container_started_at():
    """Container .State.StartedAt (RFC3339 string)."""
    r = _ssh( f"sudo docker inspect --format '{{{{.State.StartedAt}}}}' {REST_CONTAINER}",
              timeout=120 )
    return ( r.stdout or "" ).strip()


def _container_health():
    r = _ssh( f"sudo docker inspect --format '{{{{.State.Health.Status}}}}' {REST_CONTAINER}",
              timeout=120 )
    return ( r.stdout or "" ).strip()


def _wait_healthy( timeout=120, interval=6 ):
    """Poll container health until 'healthy' or timeout; return the last status.

    The deploy script's rollback restarts the container but does NOT re-run the
    health-gate, so the container is briefly 'starting' when the call returns.
    """
    deadline = time.time() + timeout
    status   = _container_health()
    while status != "healthy" and time.time() < deadline:
        time.sleep( interval )
        status = _container_health()
    return status


def _marker_in_container():
    """Contents of the probe marker inside the running container (empty if absent)."""
    r = _ssh( f"sudo docker exec {REST_CONTAINER} cat {MARKER_IN_CTR} 2>/dev/null",
              timeout=120 )
    return ( r.stdout or "" ).strip()


def _seed_deployed_ref( sha, axis="code" ):
    """Seed .deployed-ref so axis-detect compares against a KNOWN baseline.

    Test fixture only: the design has provenance land on first real run, but a
    clean axis-A proof needs a non-empty prev so the dep-diff resolves to
    'code' instead of the conservative empty-prev 'deps' default.
    """
    stamp = time.strftime( "%Y-%m-%dT%H:%M:%SZ", time.gmtime() )
    _ssh( f"echo '{sha} {stamp} {axis}' | sudo tee {DEPLOYED_REF} >/dev/null", timeout=120 )


def _run_deploy( ref, *extra ):
    """Invoke deploy-cloud-test.sh; return CompletedProcess (long timeout)."""
    return subprocess.run( [ "bash", DEPLOY_SCRIPT, "--ref", ref, *extra ],
                           cwd=LUPIN_ROOT, capture_output=True, text=True,
                           timeout=900 )


def _make_probe_branch( base_sha, branch, write_path, content, commit_msg ):
    """Create `branch` at base_sha, write+commit `content` to `write_path`.

    Returns the new commit SHA. Leaves the repo checked out on `branch`
    (caller restores). Uses an explicit add of only `write_path` so no
    foreign uncommitted file is swept in.
    """
    _git( "checkout", "-B", branch, base_sha )
    abs = os.path.join( LUPIN_ROOT, write_path )
    os.makedirs( os.path.dirname( abs ), exist_ok=True )
    with open( abs, "a" if write_path == MAIN_REL else "w" ) as fh:
        fh.write( content )
    _git( "add", "--", write_path )
    _git( "-c", "user.name=tiberius-e2e", "-c", "user.email=e2e@lupin.local",
          "commit", "-m", commit_msg )
    return _git( "rev-parse", "HEAD" )


# ---------------------------------------------------------------------------
# Fixture: snapshot pre-state, restore VM to clean HEAD + clean up on teardown
# ---------------------------------------------------------------------------
@pytest.fixture( scope="module" )
def vm_session():
    head        = _git( "rev-parse", "HEAD" )
    start_branch = _git( "rev-parse", "--abbrev-ref", "HEAD" )
    pre_ref     = _deployed_ref_sha()
    created_branches = []

    state = {
        "head"            : head,
        "start_branch"    : start_branch,
        "pre_ref"         : pre_ref,
        "created_branches": created_branches,
    }
    yield state

    # ---- teardown: back to the real branch, drop throwaway branches --------
    try:
        _git( "checkout", start_branch, check=False )
    finally:
        for b in created_branches:
            _git( "branch", "-D", b, check=False )

    # ---- restore VM to a CLEAN committed HEAD (axis-A) + stamp -------------
    _seed_deployed_ref( head )                       # so HEAD deploy is axis=code
    _run_deploy( head, "--allow-dirty" )
    # ---- remove the src.bak-* dirs this run created ------------------------
    _ssh( f"sudo rm -rf {VM_ROOT}/src.bak-*", timeout=180 )


# ---------------------------------------------------------------------------
# TEST 1 — Axis-A (code) deploy rides the bind-mount + provenance stamp
# ---------------------------------------------------------------------------
def test_axis_a_code_deploy( vm_session ):
    head     = vm_session[ "head" ]
    token    = f"e2e-axis-a-{uuid.uuid4().hex[:12]}"
    branch   = "e2e-axis-a-probe"
    vm_session[ "created_branches" ].append( branch )

    before_started = _container_started_at()
    assert _container_health() == "healthy", "precondition: container must start healthy"

    # committed marker on a throwaway branch (HEAD + marker; deps unchanged)
    sha_a = _make_probe_branch( head, branch, MARKER_REL,
                                f"{token}\n", f"[e2e] axis-A deploy probe {token}" )
    _git( "checkout", vm_session[ "start_branch" ], check=False )

    # baseline so axis-detect => code (deps identical between HEAD and HEAD+marker)
    _seed_deployed_ref( head )

    r = _run_deploy( sha_a, "--allow-dirty" )
    assert r.returncode == 0, f"deploy failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"

    # (a) marker present in the running container
    assert _marker_in_container() == token, "marker not visible in container via bind-mount"
    # (b) container actually restarted (StartedAt advanced)
    assert _container_started_at() != before_started, "container did not restart"
    # (c) provenance stamp records the exact SHA + axis=code
    assert _deployed_ref_sha() == sha_a, ".deployed-ref SHA mismatch"
    assert _deployed_ref_axis() == "code", ".deployed-ref axis should be 'code'"
    assert _container_health() == "healthy", "container unhealthy after axis-A deploy"


# ---------------------------------------------------------------------------
# TEST 2 — Rollback: a broken ref fails the health-gate and is auto-reverted
# ---------------------------------------------------------------------------
def test_rollback_on_unhealthy_deploy( vm_session ):
    head   = vm_session[ "head" ]
    branch = "e2e-rollback-probe"
    vm_session[ "created_branches" ].append( branch )

    # establish a KNOWN-GOOD healthy baseline at clean HEAD first
    _seed_deployed_ref( head )
    good = _run_deploy( head, "--allow-dirty" )
    assert good.returncode == 0, f"baseline HEAD deploy failed:\n{good.stdout}\n{good.stderr}"
    assert _container_health() == "healthy"
    good_ref = _deployed_ref_sha()
    assert good_ref == head

    # a deliberately-broken ref: top-level raise crashes uvicorn import
    broken_src = (
        '\n\n# E2E ROLLBACK PROBE — deliberate import crash to exercise the '
        'deploy-cloud-test health-gate auto-rollback. NEVER merged.\n'
        'raise RuntimeError( "deploy-cloud-test e2e rollback probe — expected; '
        'auto-rollback should restore the prior healthy src/" )\n'
    )
    sha_broken = _make_probe_branch( head, branch, MAIN_REL, broken_src,
                                     "[e2e] rollback probe — deliberate import crash" )
    _git( "checkout", vm_session[ "start_branch" ], check=False )

    _seed_deployed_ref( head )                       # prev=good HEAD, deps unchanged => code
    r = _run_deploy( sha_broken, "--allow-dirty" )

    # the deploy MUST fail (health-gate red) and roll back
    assert r.returncode != 0, "broken deploy unexpectedly reported success"
    assert "rolled back" in ( r.stdout + r.stderr ).lower(), "no rollback in deploy output"

    # post-rollback invariants (poll: rollback restart needs time to go green)
    assert _wait_healthy() == "healthy", "rollback did not restore a healthy container"
    assert _deployed_ref_sha() == good_ref, ".deployed-ref advanced to the broken SHA (should not)"
    # the broken raise must NOT be live: a healthy container proves prior src restored
