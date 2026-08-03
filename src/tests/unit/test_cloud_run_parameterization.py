"""
Unit tests for Phase-1 Fix 3 — parameterized project ID + region.

Proves the four cloud-run-*.sh scripts no longer hardcode the sandbox project,
source the shared resolver, and that the resolver fails loud when
LUPIN_GCP_PROJECT_ID is unset (the bash analogue of the fail-loud doctrine).
Script edits are non-mutating; the behavioral test runs the resolver in a tmp
dir with no adjacent cloud-run.env, so it is hermetic. :7999-eligible.
"""
import os
import shutil
import subprocess

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

# src/scripts/cloud-run-deploy.sh retired 2026-07-11 (monolith-on-Cloud-Run path,
# Rick ruled; triggered by audit finding F1) — dropped from the coverage list.
CLOUD_RUN_SCRIPTS = [
    "src/scripts/cloud-run-build.sh",
    "src/scripts/cloud-run-setup-secrets.sh",
    "src/scripts/cloud-run-validate.sh",
]

CONFIG_SCRIPT = "src/scripts/cloud-run-config.sh"


def _abs( rel_path ):
    return os.path.join( PROJECT_ROOT, rel_path )


def _read( rel_path ):
    with open( _abs( rel_path ), "r" ) as f:
        return f.read()


# test_no_hardcoded_sandbox_project() RETIRED 2026-07-13 — superseded by
# src/tests/unit/test_no_hardcoded_gcp_identifiers.py. It grepped the hardcoded
# CLOUD_RUN_SCRIPTS list above (3 files) while 28 tracked files carried the literal,
# so it passed vacuously and was cited as proof the rule was "enforced forever."
# A hardcoded allowlist is a BOUNDED check and cannot support a completeness claim.
# The replacement inverts it: glob over `git ls-files`, so nothing has to be remembered.


def test_scripts_source_shared_resolver():
    for rel in CLOUD_RUN_SCRIPTS:
        assert "cloud-run-config.sh" in _read( rel ), f"{rel} does not source cloud-run-config.sh"


def test_resolver_has_fail_loud_form():
    assert "${LUPIN_GCP_PROJECT_ID:?" in _read( CONFIG_SCRIPT )


def test_all_scripts_pass_bash_syntax_check():
    for rel in CLOUD_RUN_SCRIPTS + [ CONFIG_SCRIPT ]:
        result = subprocess.run( [ "bash", "-n", _abs( rel ) ], capture_output=True, text=True )
        assert result.returncode == 0, f"bash -n failed for {rel}: {result.stderr}"


def test_resolver_aborts_when_project_unset( tmp_path ):
    """Unset LUPIN_GCP_PROJECT_ID → non-zero exit with a readable message (the :? branch)."""
    cfg = tmp_path / "cloud-run-config.sh"          # no cloud-run.env beside it → hermetic
    shutil.copy( _abs( CONFIG_SCRIPT ), cfg )

    env = { k: v for k, v in os.environ.items() if k != "LUPIN_GCP_PROJECT_ID" }
    result = subprocess.run( [ "bash", "-c", f"source '{cfg}'" ], capture_output=True, text=True, env=env )

    assert result.returncode != 0
    assert "LUPIN_GCP_PROJECT_ID" in result.stderr


def test_resolver_succeeds_when_project_set( tmp_path ):
    """Set LUPIN_GCP_PROJECT_ID → exit 0 with the resolved defaults (the success branch)."""
    cfg = tmp_path / "cloud-run-config.sh"
    shutil.copy( _abs( CONFIG_SCRIPT ), cfg )

    env = { **os.environ, "LUPIN_GCP_PROJECT_ID": "test-proj" }
    # Strip any inherited overrides so we assert the documented defaults.
    for k in ( "LUPIN_GCP_REGION", "LUPIN_GCP_REGISTRY", "LUPIN_GCP_AR_REPO" ):
        env.pop( k, None )

    result = subprocess.run(
        [ "bash", "-c", f'source "{cfg}"; echo "$PROJECT_ID|$REGION|$REGISTRY|$AR_REPO"' ],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "test-proj|us-central1|us-central1-docker.pkg.dev|lupin" in result.stdout
