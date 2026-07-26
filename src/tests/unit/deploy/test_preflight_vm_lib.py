"""
Unit tests for src/scripts/lib/preflight-vm-lib.sh — the pure (VM-uncoupled)
helpers behind preflight-vm.sh (task 47c4801b).

Strategy: source the bash lib in a subprocess and exercise each pure function
against literal inputs and TemporaryDirectory fixtures. No gcloud, no SSH, no
Docker, no network — :7999-eligible / AI-discretionary, runs in milliseconds.

Coverage note (100% mandate): bash line-coverage tooling (kcov/bashcov) is NOT
part of the Lupin pytest --cov / c8 gate, so the lib cannot be line-instrumented
here. Following the precedent of test_deploy_cloud_test_lib.py, this suite
instead asserts EVERY BRANCH of EVERY pure function behaviorally — including,
for each function, at least one input that makes it return NON-zero, so no
assertion in this file is one that cannot fail.

The Python in this file is itself 100%-covered when the suite runs.
"""
import os
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT  = cu.get_project_root()
LIB_PATH      = os.path.join( PROJECT_ROOT, "src/scripts/lib/preflight-vm-lib.sh" )
MANIFEST_PATH = os.path.join( PROJECT_ROOT, "src/conf/vm-unversioned-manifest.tsv" )

TAB = "\t"


def _run( snippet, cwd=None ):
    """
    Source the lib and run a bash snippet.

    Requires:
        - snippet is a bash fragment that may call any pfv_* function

    Ensures:
        - returns the CompletedProcess (stdout/stderr captured, text mode)
        - `set -u` is ON so an unset-variable bug in the lib fails loudly here
          rather than silently evaluating to empty
    """
    full = f"set -uo pipefail; source '{LIB_PATH}'; {snippet}"
    return subprocess.run(
        [ "bash", "-c", full ], cwd=cwd, capture_output=True, text=True
    )


# ══════════════════════════════════════════════════════════════════════════
# pfv_parse_manifest
# ══════════════════════════════════════════════════════════════════════════

def test_parse_manifest_drops_comments_and_blanks( tmp_path ):
    m = tmp_path / "m.tsv"
    m.write_text(
        "# a comment\n"
        "\n"
        "   \n"
        f"a{TAB}b{TAB}c{TAB}d{TAB}REQUIRED\n"
        "   # indented comment\n"
        f"e{TAB}f{TAB}g{TAB}h{TAB}OPTIONAL\n"
    )
    r = _run( f"pfv_parse_manifest '{m}'" )
    assert r.returncode == 0
    lines = [ l for l in r.stdout.split( "\n" ) if l ]
    assert len( lines ) == 2
    assert lines[ 0 ].startswith( "a" )
    assert lines[ 1 ].startswith( "e" )


def test_parse_manifest_unreadable_returns_1( tmp_path ):
    r = _run( f"pfv_parse_manifest '{tmp_path}/nope.tsv'" )
    assert r.returncode == 1
    assert r.stdout == ""


def test_parse_manifest_all_comments_is_empty_success( tmp_path ):
    """An all-comment manifest is a legitimate state, not an error."""
    m = tmp_path / "m.tsv"
    m.write_text( "# only\n# comments\n" )
    r = _run( f"pfv_parse_manifest '{m}'" )
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_parse_manifest_reads_the_real_shipped_manifest():
    """
    The instrument is proven against the file it exists to read. A parser tested
    only on fixtures can pass while being unable to read production data.
    """
    r = _run( f"pfv_parse_manifest '{MANIFEST_PATH}'" )
    assert r.returncode == 0
    rows = [ l for l in r.stdout.split( "\n" ) if l ]
    assert len( rows ) >= 4, f"expected the shipped manifest's data rows, got {rows}"
    for row in rows:
        assert len( row.split( TAB ) ) == 5, f"malformed shipped row: {row!r}"


# ══════════════════════════════════════════════════════════════════════════
# pfv_manifest_field
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "idx,expected", [
    ( 1, "loc" ), ( 2, "rem" ), ( 3, "1001:1001" ), ( 4, "644" ), ( 5, "REQUIRED" ),
] )
def test_manifest_field_extracts_each_column( idx, expected ):
    row = TAB.join( [ "loc", "rem", "1001:1001", "644", "REQUIRED" ] )
    r = _run( f"pfv_manifest_field '{row}' {idx}" )
    assert r.returncode == 0
    assert r.stdout == expected


def test_manifest_field_short_row_returns_2_not_empty():
    """
    A malformed row must be DISTINGUISHABLE from a missing value. Collapsing both
    onto '' is how a typo'd manifest row would read as 'nothing configured'.
    """
    row = TAB.join( [ "loc", "rem", "1001:1001" ] )   # only 3 fields
    r = _run( f"pfv_manifest_field '{row}' 5" )
    assert r.returncode == 2
    assert r.stdout == ""


def test_manifest_field_dash_placeholder_survives():
    row = TAB.join( [ "-", "/vm/path", "-", "-", "REQUIRED" ] )
    assert _run( f"pfv_manifest_field '{row}' 1" ).stdout == "-"
    assert _run( f"pfv_manifest_field '{row}' 3" ).stdout == "-"


# ══════════════════════════════════════════════════════════════════════════
# pfv_row_field / pfv_contract_field  (R3 — the env contract)
# ══════════════════════════════════════════════════════════════════════════

def test_row_field_arity_floor_is_a_parameter():
    """
    The floor is a parameter so the 5-column manifest and the 6-column contract
    share ONE parser. Two near-identical parsers drifting apart is the exact
    defect class this whole body of work exists to remove.
    """
    five = TAB.join( [ "a", "b", "c", "d", "e" ] )
    assert _run( f"pfv_row_field '{five}' 5 5" ).returncode == 0
    assert _run( f"pfv_row_field '{five}' 5 6" ).returncode == 2   # too short for a contract row


def test_contract_field_requires_six_columns():
    six = TAB.join( [ "LUPIN_ROOT", "BOTH", "push-env", "PATH_VM", "REQUIRED", "note" ] )
    r = _run( f"pfv_contract_field '{six}' 4" )
    assert r.returncode == 0
    assert r.stdout == "PATH_VM"
    five = TAB.join( [ "a", "b", "c", "d", "e" ] )
    assert _run( f"pfv_contract_field '{five}' 4" ).returncode == 2


def test_contract_field_reads_the_real_shipped_contract():
    """Proven against the file it exists to read, not only against fixtures."""
    r = _run( f"pfv_parse_manifest '{os.path.join( PROJECT_ROOT, 'src/conf/env-contract.tsv' )}'" )
    assert r.returncode == 0
    rows = [ l for l in r.stdout.split( "\n" ) if l ]
    assert len( rows ) >= 10
    for row in rows:
        assert len( row.split( TAB ) ) == 6, f"malformed contract row: {row!r}"


# ══════════════════════════════════════════════════════════════════════════
# pfv_shape_matches
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "value,shape,rc", [
    ( "/mnt/lupin-data/lupin", "PATH_VM",  0 ),
    ( "/mnt/DATA01/x",         "PATH_VM",  1 ),   # dev path on a VM
    ( "/anywhere",             "PATH_ANY", 0 ),
    ( "relative/path",         "PATH_ANY", 1 ),
    ( "a@b.com",               "EMAIL",    0 ),
    ( "not-an-email",          "EMAIL",    1 ),
    ( "1721846087",            "NUMERIC",  0 ),
    ( "100x",                  "NUMERIC",  1 ),
    ( "testing",               "ENUM:development|testing|production", 0 ),
    ( "staging",               "ENUM:development|testing|production", 1 ),
    ( "global",                "ENUM:global", 0 ),
    ( "us-central1",           "ENUM:global", 1 ),
    ( "ck_live_xxx",           "SECRET",   0 ),
    ( "anything",              "LITERAL",  0 ),
    ( "",                      "PATH_VM",  2 ),   # unset != wrong
    ( "",                      "SECRET",   2 ),
] )
def test_shape_matches_branches( value, shape, rc ):
    r = _run( f"pfv_shape_matches '{value}' '{shape}' '/mnt/lupin-data'" )
    assert r.returncode == rc, f"{value!r} vs {shape!r}: got {r.returncode}"


def test_shape_matches_unknown_token_accepts_the_value():
    """
    A TYPO IN THE CONTRACT MUST NOT BE REPORTED AS A BROKEN ENVIRONMENT. The two
    have different files to fix; conflating them sends the operator to the wrong one.
    """
    assert _run( "pfv_shape_matches '/x' 'PATH_TYPOD' '/mnt/lupin-data'" ).returncode == 0


def test_shape_matches_enum_does_not_substring_match():
    """'test' must not satisfy ENUM:testing — a substring match would silently widen every enum."""
    assert _run( "pfv_shape_matches 'test' 'ENUM:testing' '/x'" ).returncode == 1


# ══════════════════════════════════════════════════════════════════════════
# pfv_mode_matches
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "observed,expected,rc", [
    ( "644",  "644",  0 ),   # exact
    ( "0644", "644",  0 ),   # leading zero normalized (stat differs by platform)
    ( "644",  "0644", 0 ),   # ...both directions
    ( "2770", "2770", 0 ),   # setgid, 4 digits
    ( "600",  "644",  1 ),   # the DM-key defect's actual shape
    ( "755",  "-",    0 ),   # assertion waived
    ( "",     "644",  2 ),   # unreadable => UNKNOWN, never a pass
    ( "",     "-",    0 ),   # waived beats unknown
] )
def test_mode_matches_branches( observed, expected, rc ):
    r = _run( f"pfv_mode_matches '{observed}' '{expected}'" )
    assert r.returncode == rc, f"{observed!r} vs {expected!r}: got {r.returncode}"


# ══════════════════════════════════════════════════════════════════════════
# pfv_owner_matches
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "observed,expected,rc", [
    ( "1001:1001", "1001:1001", 0 ),
    ( "1721846087:1721846087", "1001:1001", 1 ),   # the persona-404 divergence
    ( "1001:1001", "-", 0 ),
    ( "", "1001:1001", 2 ),
] )
def test_owner_matches_branches( observed, expected, rc ):
    r = _run( f"pfv_owner_matches '{observed}' '{expected}'" )
    assert r.returncode == rc


def test_owner_matches_name_never_satisfies_a_numeric_expectation():
    """
    persona-404 was a uid divergence that read fine BY NAME on each side. A name
    must never satisfy a numeric expectation, or the check re-creates the bug.
    """
    r = _run( "pfv_owner_matches 'rruiz:rruiz' '1001:1001'" )
    assert r.returncode == 1


# ══════════════════════════════════════════════════════════════════════════
# pfv_diff_mount_sets
# ══════════════════════════════════════════════════════════════════════════

def test_diff_mount_sets_all_present_returns_0():
    r = _run(
        "pfv_diff_mount_sets "
        "'/var/lupin/src\n/cloudsql' "
        "'/cloudsql\n/var/lupin/src\n/extra'"
    )
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_diff_mount_sets_names_the_missing_target():
    r = _run(
        "pfv_diff_mount_sets "
        "'/var/lupin/src\n/var/external-projects/lupin' "
        "'/var/lupin/src'"
    )
    assert r.returncode == 1
    assert "/var/external-projects/lupin" in r.stdout


def test_diff_mount_sets_extra_running_mount_is_not_a_defect():
    """
    One-way by design: anonymous volumes and runtime binds legitimately appear in
    the running set. Only DECLARED-but-absent means the container predates the
    compose edit — which is the defect this exists to catch.
    """
    r = _run( "pfv_diff_mount_sets '/a' '/a\n/b\n/c'" )
    assert r.returncode == 0


def test_diff_mount_sets_ignores_blank_lines():
    r = _run( "pfv_diff_mount_sets '/a\n\n/b' '/a\n/b\n'" )
    assert r.returncode == 0


# ══════════════════════════════════════════════════════════════════════════
# pfv_env_is_vm_path
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "value,prefix,rc", [
    ( "/mnt/lupin-data/lupin", "/mnt/lupin-data", 0 ),
    ( "",                      "/mnt/lupin-data", 2 ),   # unset  => "run push-env"
    ( "/mnt/DATA01/include/x", "/mnt/lupin-data", 3 ),   # dev path => "push-env shipped wrong values"
    ( "/opt/somewhere",        "/mnt/lupin-data", 1 ),   # neither
] )
def test_env_is_vm_path_branches( value, prefix, rc ):
    r = _run( f"pfv_env_is_vm_path '{value}' '{prefix}'" )
    assert r.returncode == rc


def test_env_is_vm_path_separates_unset_from_devpath():
    """
    The two failures have DIFFERENT remedies. Collapsing them sends the operator
    down the wrong branch, which is how a 'missing' var that was actually wrong
    cost a round-trip on 07-24.
    """
    unset   = _run( "pfv_env_is_vm_path '' '/mnt/lupin-data'" ).returncode
    devpath = _run( "pfv_env_is_vm_path '/mnt/DATA01/x' '/mnt/lupin-data'" ).returncode
    assert unset != devpath


# ══════════════════════════════════════════════════════════════════════════
# pfv_venv_is_foreign
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "path,is_link,owner,operator,rc", [
    ( "/r/.venv", "true",  "1001",       "1721846087", 1 ),  # THE trap: arbiter's venv
    ( "/r/.venv", "true",  "1721846087", "1721846087", 2 ),  # own symlink: suspicious
    ( "/r/.venv", "false", "1001",       "1721846087", 0 ),  # real dir, other owner: not this check
    ( "/r/.venv", "false", "1721846087", "1721846087", 0 ),  # healthy
    ( "",         "true",  "1001",       "1721846087", 0 ),  # nothing resolved
] )
def test_venv_is_foreign_branches( path, is_link, owner, operator, rc ):
    r = _run( f"pfv_venv_is_foreign '{path}' '{is_link}' '{owner}' '{operator}'" )
    assert r.returncode == rc


# ══════════════════════════════════════════════════════════════════════════
# pfv_classify_probe
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "outcome,tier,label,rc", [
    ( "pass",    "BLOCK", "OK",            0 ),
    ( "pass",    "WARN",  "OK",            0 ),
    ( "fail",    "BLOCK", "FAIL",          1 ),
    ( "fail",    "WARN",  "WARN",          0 ),
    ( "unknown", "BLOCK", "UNKNOWN-BLOCK", 1 ),
    ( "unknown", "WARN",  "UNKNOWN-WARN",  0 ),
    ( "garbage", "BLOCK", "UNKNOWN-BLOCK", 1 ),   # unrecognized => blocking
    ( "garbage", "WARN",  "UNKNOWN-BLOCK", 1 ),   # ...even at WARN tier
] )
def test_classify_probe_branches( outcome, tier, label, rc ):
    r = _run( f"pfv_classify_probe '{outcome}' '{tier}'" )
    assert r.stdout == label
    assert r.returncode == rc


def test_classify_probe_unknown_never_becomes_a_pass():
    """
    The standing rule, pinned: a probe that could not see one side has verified
    nothing. This is the same defect shape that let a DELETED Cloud SQL socket
    read as 'healthy' for hours on 2026-07-26.
    """
    for tier in ( "BLOCK", "WARN" ):
        assert _run( f"pfv_classify_probe 'unknown' '{tier}'" ).stdout != "OK"


# ══════════════════════════════════════════════════════════════════════════
# pfv_phase_includes  (Rick's both-arms ruling, 2026-07-26)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "phase,layer,rc", [
    ( "pre",  "A", 0 ), ( "pre",  "B", 1 ), ( "pre",  "C", 0 ),
    ( "pre",  "D", 1 ), ( "pre",  "E", 0 ),
    ( "post", "A", 0 ), ( "post", "B", 0 ), ( "post", "C", 0 ),
    ( "post", "D", 0 ), ( "post", "E", 0 ),
    ( "full", "B", 0 ), ( "full", "D", 0 ),
] )
def test_phase_includes_branches( phase, layer, rc ):
    r = _run( f"pfv_phase_includes '{phase}' '{layer}'" )
    assert r.returncode == rc


def test_phase_includes_unknown_layer_runs_rather_than_skips():
    """
    A typo'd layer must surface as a noisy extra probe, never as silently-skipped
    coverage. Silent skipping is indistinguishable from passing.
    """
    assert _run( "pfv_phase_includes 'pre' 'Z'" ).returncode == 0


def test_phase_includes_unknown_phase_runs_everything():
    assert _run( "pfv_phase_includes 'bogus' 'D'" ).returncode == 0


# ══════════════════════════════════════════════════════════════════════════
# Instrument control — the harness must be able to report a failure
# ══════════════════════════════════════════════════════════════════════════

def test_harness_reports_a_real_bash_failure():
    """
    Proves _run() surfaces a non-zero return rather than swallowing it. Without
    this, every rc assertion above could be passing vacuously.
    """
    r = _run( "exit 7" )
    assert r.returncode == 7


def test_harness_would_catch_a_missing_function():
    """The negative control for 'the lib sourced at all'."""
    r = _run( "pfv_this_function_does_not_exist" )
    assert r.returncode != 0
