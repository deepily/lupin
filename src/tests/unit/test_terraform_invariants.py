"""
Terraform IaC invariants — structural + security-attribute regression locks.

WHY THIS FILE EXISTS
--------------------
These assertions previously lived in `src/terraform/tests/modules.bats`. They had
NEVER RUN — not once:

  * `bats` is not installed on the dev host, so the file cannot execute; and
  * nothing in the repo invokes it — no CI job, no script, no Makefile, no pytest
    hook. The only reference to `modules.bats` anywhere was the exemption entry in
    test_no_hardcoded_gcp_identifiers.py.

So fifteen assertions guarding real security properties — no `objectAdmin`, no
`owner`/`editor` grants, private-IP-only Cloud SQL, PITR, immutable image tags, no
plaintext DB password — were decorative. They read like a guard, they were cited
like a guard, and they enforced nothing.

    A bounded check is armed only where it looks.
    A check nobody runs is not armed at all.

Porting them to pytest puts them in the unit lane, which actually executes on every
run. The one assertion that genuinely needs the `terraform` binary (`validate`) is
skipped EXPLICITLY, with a stated reason — never silently.

NOTE — the bats "no hardcoded sandbox project id" grep is NOT ported. It was bounded
(`--include="*.tf"`, blind to `.tfvars`, `.tfvars.example`, `.hcl`) and is fully
superseded by test_no_hardcoded_gcp_identifiers.py, which globs every tracked
executable surface in the repo, terraform included.

Venue: :7999-eligible — pure file reads + an offline `terraform validate`. No network
writes, no GCP calls, no mutation.
"""
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

TF_ROOT   = os.path.join( PROJECT_ROOT, "src", "terraform" )
ENV_TEST  = os.path.join( TF_ROOT, "envs", "test" )
MODULES   = os.path.join( TF_ROOT, "modules" )


def _read( *parts ):
    with open( os.path.join( *parts ), "r" ) as f:
        return f.read()


def _variable_block( source, name ):
    """Extract a single `variable "<name>" { ... }` block — the awk in the bats original."""
    match = re.search(
        r'variable\s+"' + re.escape( name ) + r'"\s*\{.*?^\}', source, re.DOTALL | re.MULTILINE
    )
    assert match, f'variable "{name}" not found'
    return match.group( 0 )


# ── env: project id must fail loud ────────────────────────────────────────────────

def test_env_project_id_variable_has_no_default():
    """No `default =` ARGUMENT on project_id — an unset project must fail loud, not silently
    resolve to somebody's sandbox. (The word 'default' inside the description must not trip it.)"""
    block = _variable_block( _read( ENV_TEST, "variables.tf" ), "project_id" )
    body  = re.sub( r'description\s*=\s*".*?"', "", block, flags=re.DOTALL )
    assert not re.search( r'^\s*default\s*=', body, re.MULTILINE ), (
        "envs/test variable project_id carries a `default =` — it must fail loud when unset"
    )


def test_env_repoints_iam_without_a_hardcoded_project_literal():
    """The VM SA email is CONSTRUCTED from var.project_id — the literal stays out of source."""
    main = _read( ENV_TEST, "main.tf" )
    assert 'external_vm_sa_email = "${var.vm_sa_account_id}@${var.project_id}.iam.gserviceaccount.com"' in main
    assert 'variable "vm_sa_account_id"' in _read( ENV_TEST, "variables.tf" )


# ── iam: least privilege ──────────────────────────────────────────────────────────

def test_iam_grants_object_user_never_object_admin():
    iam = _read( MODULES, "iam", "main.tf" )
    assert "roles/storage.objectUser" in iam, "runtime SA must hold storage.objectUser"
    assert not re.search( r"storage\.objectAdmin|roles/storage\.admin", iam ), (
        "iam grants storage.objectAdmin/storage.admin — privilege escalation over objectUser"
    )


def test_iam_creates_no_owner_or_editor_grants():
    iam = _read( MODULES, "iam", "main.tf" )
    assert not re.search( r"roles/owner|roles/editor", iam ), "iam creates an owner/editor grant"


def test_iam_binds_secrets_and_buckets_per_resource_not_project_wide():
    """Project-level grants may carry ONLY cloudsql.client / logging / monitoring.
    objectUser + secretAccessor must be bound per-resource, never project-wide."""
    iam = _read( MODULES, "iam", "main.tf" )
    assert "google_secret_manager_secret_iam_member" in iam
    assert "google_storage_bucket_iam_member"        in iam

    allowed  = ( "cloudsql.client", "logging.logWriter", "monitoring.metricWriter" )
    offenders = []
    for block in re.findall( r'resource\s+"google_project_iam_member".*?^\}', iam, re.DOTALL | re.MULTILINE ):
        for role in re.findall( r'role\s*=\s*"([^"]+)"', block ):
            if not any( a in role for a in allowed ): offenders.append( role )
    assert not offenders, f"project-wide iam grants beyond the allowed set: {offenders}"


def test_iam_exposes_optional_external_vm_sa_email():
    """Optional → must carry an empty-string default so `validate` runs without it."""
    block = _variable_block( _read( MODULES, "iam", "variables.tf" ), "external_vm_sa_email" )
    assert re.search( r'default\s*=\s*""', block ), (
        "external_vm_sa_email must default to \"\" so it is genuinely optional"
    )


def test_iam_binds_runtime_roles_via_coalesce_local():
    """Runtime bindings go through the repoint local — never pin the module SA email directly."""
    iam = _read( MODULES, "iam", "main.tf" )
    assert "coalesce(var.external_vm_sa_email, google_service_account.runtime_sa.email)" in iam
    assert "member = local.runtime_sa_member" in iam
    assert not re.search(
        r'member\s*=\s*"serviceAccount:\$\{google_service_account\.runtime_sa\.email\}"', iam
    ), "a runtime binding still pins the module SA email directly, defeating the Phase-B repoint"


# ── artifact registry ─────────────────────────────────────────────────────────────

def test_artifact_registry_uses_immutable_tags():
    assert "immutable_tags = true" in _read( MODULES, "artifact-registry", "main.tf" )


# ── cloud sql ─────────────────────────────────────────────────────────────────────

def test_cloud_sql_is_private_ip_only():
    assert "ipv4_enabled    = false" in _read( MODULES, "cloud-sql-pg16", "main.tf" ), (
        "Cloud SQL must not expose a public IPv4 endpoint"
    )


def test_cloud_sql_has_pitr_enabled():
    assert "point_in_time_recovery_enabled = true" in _read( MODULES, "cloud-sql-pg16", "main.tf" )


def test_cloud_sql_password_is_generated_and_never_plaintext():
    """Generated in-module + written to Secret Manager. The password is never a literal/tfvar."""
    sql_main = _read( MODULES, "cloud-sql-pg16", "main.tf" )
    assert 'resource "random_password" "db"'                              in sql_main
    assert 'resource "google_secret_manager_secret_version" "db_password"' in sql_main
    assert "password = random_password.db[0].result"                       in sql_main

    for entry in os.listdir( ENV_TEST ):
        if entry.endswith( ".tfvars" ):
            assert "password" not in _read( ENV_TEST, entry ).lower(), (
                f"plaintext password assignment in {entry}"
            )


# ── onprem vpn ────────────────────────────────────────────────────────────────────

def test_onprem_vpn_is_fully_gated_on_enable_vpn():
    """Every resource in the module carries the enable_vpn count guard — false creates nothing."""
    vpn        = _read( MODULES, "onprem-vpn", "main.tf" )
    resources  = len( re.findall( r"^resource", vpn, re.MULTILINE ) )
    guards     = vpn.count( "var.enable_vpn ? 1 : 0" )
    assert resources > 0, "onprem-vpn declares no resources — the guard would pass vacuously"
    assert guards == resources, (
        f"{resources} resources but only {guards} enable_vpn guards — an ungated resource "
        f"would be created even when enable_vpn is false"
    )


# ── secret manager ────────────────────────────────────────────────────────────────

def test_secret_manager_creates_no_secret_versions():
    """Secret VALUES stay out-of-band — the module creates containers, never versions."""
    assert 'resource "google_secret_manager_secret_version"' not in _read(
        MODULES, "secret-manager", "main.tf"
    ), "secret-manager module creates a secret VERSION — values must stay out-of-band"


# ── terraform validate (needs the binary + initialized providers) ─────────────────

def test_terraform_binary_is_installed():
    """
    T2 (Rio, stage-3 review) — MY OWN RULE, APPLIED TO MY OWN SKIP.

    `test_envs_test_passes_terraform_validate` is guarded by a `skipif`. That skip does
    not fire today — terraform IS installed — but it is `modules.bats` in a DORMANT
    state: the day the binary leaves this host or the CI image, the assertion stops
    running and says NOTHING. A skip is invisible in a 9,131-test run. That is the exact
    failure mode this entire file was written to kill:

        A check nobody runs is not armed at all — and a check that QUIETLY
        stops running is worse, because it was trusted while it was dying.

    So the skip gets a watchdog. The `skipif` still prevents a confusing cascade of
    subprocess errors, but it can no longer hide the disarming: THIS test goes red the
    moment the instrument disappears, naming the loss.
    """
    assert shutil.which( "terraform" ) is not None, (
        "terraform is NOT installed — test_envs_test_passes_terraform_validate is therefore "
        "SKIPPING, and a skip is invisible in a full-suite run. The terraform schema check is "
        "currently DISARMED. Install terraform or delete the validate test; do not leave a "
        "dormant assertion radiating false confidence (this is precisely how modules.bats's "
        "15 security assertions ran zero times)."
    )


PROVIDER_CACHE = os.path.join( ENV_TEST, ".terraform", "providers" )


def test_terraform_provider_cache_is_present():
    """
    THE SECOND WATCHDOG — and it exists because the FIRST ONE WAS NOT ENOUGH.

    T2 (Rio) predicted the validate check would go dormant if the terraform BINARY left the
    host. It named one environmental dependency. There were THREE:

        1. the terraform binary          <- T2 watched this one
        2. the provider plugins          <- unwatched
        3. GCS remote state + live ADC   <- unwatched, and ILLEGITIMATE (see below)

    So the check could stop being meaningful for two reasons nobody was watching. This
    watchdog names #2 out loud, so a missing cache can never again surface as a mysterious
    "terraform init failed" — an error message that tells you nothing and, worst of all,
    MOVES BETWEEN RUNS WITH NOBODY EDITING ANYTHING. A red that comes and goes on its own
    is not a red; it is an instrument with a loose wire, and it cannot tell you anything —
    including that you are fine.
    """
    assert os.path.isdir( PROVIDER_CACHE ), (
        f"terraform provider plugins are NOT cached at {PROVIDER_CACHE}, so "
        f"test_envs_test_passes_terraform_validate cannot schema-validate anything without "
        f"reaching the registry over the network. Populate the cache ONCE with:\n"
        f"    cd {ENV_TEST} && terraform init -backend=false\n"
        f"…or ship the providers in the CI image. Do NOT make the validate test skip."
    )


@pytest.mark.skipif(
    shutil.which( "terraform" ) is None,
    reason="terraform binary not installed — SKIPPED LOUDLY, never silently passed "
           "(test_terraform_binary_is_installed goes RED and names the loss)",
)
def test_envs_test_passes_terraform_validate():
    """
    Schema-validate the env against the real provider schemas.

    🔴 THIS TEST USED TO MAKE A LIVE GCP CALL, AND THAT IS WHY IT MOVED.

    It ran `terraform init -backend=false` in the working tree. `-backend=false` does NOT
    mean "no backend" — it means "do not RE-configure the backend", and terraform then
    loads the one cached in `.terraform/terraform.tfstate` from a previous full init. That
    backend is the GCS remote state bucket. So every unit run reached out to
    `storage.googleapis.com` with the developer's ADC, and the day those credentials
    needed reauth it failed with:

        Error loading state: … oauth2: "invalid_grant" "reauth related error (invalid_rapt)"

    Which surfaced, in a 9,326-test summary line, as the uninformative `terraform init
    failed` — a RED THAT APPEARS AND VANISHES WITH TOKEN EXPIRY, blocking a commit while
    everyone hunts for the peer who broke the tree. Nobody had. **A unit test had a network
    and a credential dependency it never declared, and it was making a GCP call from a
    suite whose entire cascade is under a ZERO-GCP-CALLS rule.**

    THE FIX IS TO REMOVE THE DEPENDENCY, NOT TO TOLERATE IT:

        TF_DATA_DIR       -> a tmp dir, so there is NO cached backend to load. No GCS. No
                             ADC. No network. It also stops the test MUTATING `.terraform/`
                             in a working tree that four sessions are editing.
        TF_PLUGIN_CACHE_DIR -> the already-downloaded providers, so init installs from disk
                             rather than the registry.

    `validate` never needed state — only schemas. The backend was pure collateral, and it
    was the only genuinely moving part. What remains (the provider cache) is watched by
    test_terraform_provider_cache_is_present and fails LOUD with a remedy.
    """
    with tempfile.TemporaryDirectory() as tf_data_dir:
        env = {
            **os.environ,
            "TF_DATA_DIR"         : tf_data_dir,     # no cached backend -> no GCS, no ADC
            "TF_PLUGIN_CACHE_DIR" : PROVIDER_CACHE,  # providers from disk -> no registry
            "TF_IN_AUTOMATION"    : "1",
        }
        init = subprocess.run(
            [ "terraform", "init", "-backend=false", "-no-color", "-input=false" ],
            cwd=ENV_TEST, capture_output=True, text=True, env=env,
        )
        assert init.returncode == 0, (
            f"terraform init failed OFFLINE (no backend, providers from {PROVIDER_CACHE}). "
            f"This should not depend on the network or on any credential — if the output below "
            f"mentions oauth/storage.googleapis.com, a backend dependency has crept back in and "
            f"this test is making a LIVE GCP CALL. If it mentions the registry, the provider "
            f"cache is stale versus .terraform.lock.hcl.\n{init.stdout}{init.stderr}"
        )

        result = subprocess.run(
            [ "terraform", "validate", "-no-color" ],
            cwd=ENV_TEST, capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, (
            f"terraform validate failed: {result.stdout}{result.stderr}"
        )
        assert "valid" in result.stdout


def _source_of( function_name ):
    """
    Return the source text of a top-level function in THIS file.

    Reads the file named by `__file__` rather than going through
    `inspect.getsource`, whose `co_filename` is baked into pytest's cached rewritten
    bytecode and is therefore wrong in whichever venue did not compile that cache
    (bug d8a23fca — `__pycache__` is bind-mounted into a container with a different
    repo root). `__file__` is resolved per-import from the module spec, so it names a
    path that exists wherever the test is actually running.

    Requires:
        - function_name is a top-level `def` in this module

    Ensures:
        - returns the text from that `def` line up to the next top-level statement
        - raises AssertionError naming the function when it is not found, rather than
          returning an empty string a caller's `in` check would silently pass on
    """
    lines = Path( __file__ ).read_text().splitlines( keepends=True )
    start = next( ( i for i, line in enumerate( lines )
                    if line.startswith( f"def {function_name}(" ) ), None )
    assert start is not None, f"{function_name} not found in {__file__} — the guard cannot read what it asserts about"

    end = next( ( j for j in range( start + 1, len( lines ) )
                  if lines[ j ].strip() and not lines[ j ][ 0 ].isspace() ), len( lines ) )
    return "".join( lines[ start : end ] )


def test_the_validate_check_never_touches_the_network_or_a_credential():
    """
    ⚠️ THE INVARIANT, PINNED — because the defect above was invisible in the test's own
    source: it was `-backend=false`, which READS LIKE the fix and was in fact the bug.

    The offline guarantee rests on exactly two env vars. Delete either one and the test
    silently starts reaching for GCS again (TF_DATA_DIR) or the registry
    (TF_PLUGIN_CACHE_DIR) — and it will PASS on the developer's machine, where both happen
    to be reachable, while moving at random in CI. So the mechanism is asserted, not
    trusted.

    ⚠️ Bug d8a23fca — this read the source via `inspect.getsource( fn )`, which resolves
    through the function's `co_filename`. pytest's assertion-rewriting BAKES that absolute
    path into the cached bytecode, and `src/tests/unit/__pycache__/` is bind-mounted into
    lupin-rest-test — a container whose repo root is /var/lupin, not the host's
    /mnt/DATA01/…. So whichever venue did not compile the cache loads a `co_filename`
    that does not exist for it, and `getsource` dies with "could not get source code".

    Measured both directions: with a host-written cache the CONTAINER failed; after
    deleting it and letting the container recompile, the HOST failed and the container
    passed. The venue that breaks is decided by run order, silently. `__file__` is set
    per-import from the module spec — the real filesystem — rather than from the cached
    bytecode, so reading the file directly is correct in every venue and under any cache.
    """
    source = _source_of( "test_envs_test_passes_terraform_validate" )
    for var in ( "TF_DATA_DIR", "TF_PLUGIN_CACHE_DIR" ):
        assert var in source, (
            f"{var} is gone from the terraform validate test. Without it the test reaches the "
            f"network or the GCS backend, and its result depends on a token nobody is watching. "
            f"That is the loose wire that froze a commit for an evening."
        )
    assert "-backend=false" in source, "the backend must stay disabled — validate needs no state"
