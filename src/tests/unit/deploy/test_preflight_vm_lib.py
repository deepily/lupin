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
# pfv_req_effective — OPTIONAL / REQUIRED / OPTIONAL_UNLESS
#
# Added 2026-07-26 after the first real `preflight pre` run reported 7 warnings,
# 5 of them false: the contract already said those vars were OPTIONAL and the
# runner still called UNSET-and-optional an UNKNOWN with a remedy. Three of the
# five printed a remedy that could not run — they are unset on the dev box too,
# so there was nothing for push-env to push.
# ══════════════════════════════════════════════════════════════════════════

def test_req_effective_optional_stays_optional():
    assert _run( "pfv_req_effective 'OPTIONAL'" ).stdout == "OPTIONAL"


def test_req_effective_required_stays_required():
    assert _run( "pfv_req_effective 'REQUIRED'" ).stdout == "REQUIRED"


def test_req_effective_conditional_is_optional_when_the_switch_is_off():
    """
    The Vertex trio's SAFE state. All three absent is coherent — Vertex is off —
    and must not warn. This is the case that produced 3 of the 5 false warnings.
    """
    r = _run( "unset CLAUDE_CODE_USE_VERTEX; pfv_req_effective 'OPTIONAL_UNLESS:CLAUDE_CODE_USE_VERTEX=1'" )
    assert r.stdout == "OPTIONAL"


def test_req_effective_conditional_is_REQUIRED_when_the_switch_is_on():
    """
    THE CASE THE FLAT OPTIONAL/REQUIRED SPLIT COULD NOT EXPRESS, and the reason
    this function exists rather than a blanket downgrade.

    A PARTIAL Vertex set is the dangerous state, not the empty one: with
    CLAUDE_CODE_USE_VERTEX=1 and no CLOUD_ML_REGION, Opus 4.8 is global-only, so a
    missing region yields model-not-found — which the CC wizard mis-reports as
    "permission denied". Flat OPTIONAL warned on the safe emptiness and would have
    stayed SILENT here. The alarm was loudest exactly where nothing was wrong.
    """
    r = _run( "export CLAUDE_CODE_USE_VERTEX=1; pfv_req_effective 'OPTIONAL_UNLESS:CLAUDE_CODE_USE_VERTEX=1'" )
    assert r.stdout == "REQUIRED"


def test_req_effective_conditional_is_optional_when_the_switch_holds_another_value():
    """`=0` is not `=1` — the condition is equality, not truthiness."""
    r = _run( "export CLAUDE_CODE_USE_VERTEX=0; pfv_req_effective 'OPTIONAL_UNLESS:CLAUDE_CODE_USE_VERTEX=1'" )
    assert r.stdout == "OPTIONAL"


@pytest.mark.parametrize( "req", [
    "OPTIONAL_UNLESS:",                 # no condition at all
    "OPTIONAL_UNLESS:NO_EQUALS_SIGN",   # missing the =
    "OPTIONAL_UNLESS:=1",               # empty var name
    "MAYBE",                            # unrecognised entirely
    "",                                 # blank
] )
def test_req_effective_fails_CLOSED_on_anything_it_cannot_parse( req ):
    """
    A malformed condition must never silently downgrade an assertion to OPTIONAL.
    Not-knowing makes the WAIVER unsafe, so the unknown resolves to REQUIRED — the
    same polarity the preflight's blocking arms use, and the opposite of the
    "ambiguous ⇒ pass" universal this instrument already refused once.
    """
    assert _run( f"pfv_req_effective '{req}'" ).stdout == "REQUIRED"


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


# ══════════════════════════════════════════════════════════════════════════
# pfv_pyc_expected_source / pfv_pyc_orphan_class / pfv_scan_orphan_pyc
#
# Row 70364793 (2026-08-18): the LanceDB sweep deleted two .py files, the VM
# deploys by git checkout, and __pycache__ is gitignored — so git removed the
# sources and left the bytecode. Nothing in the deploy path removed it and
# nothing looked for it. These are the tests for the thing that now looks.
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "pyc, expected", [
    # PEP 3147 layout — the tag is stripped, the directory steps up one level.
    ( "pkg/__pycache__/mod.cpython-313.pyc",              "pkg/mod.py"  ),
    ( "pkg/__pycache__/mod.cpython-313.opt-2.pyc",        "pkg/mod.py"  ),
    # THE FALSE-POSITIVE GENERATOR. pytest's assertion rewriter writes a DOTTED
    # tag, so stripping one trailing component leaves "mod.cpython-313-pytest-8.4",
    # whose .py never existed — and every rewritten test file in the repo reports
    # as an orphan. Measured on this tree the first time it ran: 1375 findings,
    # essentially all of them this. A detector that cries wolf 1375 times is a
    # detector nobody reads, which is worse than no detector at all.
    ( "pkg/__pycache__/mod.cpython-313-pytest-8.4.2.pyc", "pkg/mod.py"  ),
    ( "pkg/__pycache__/mod.cpython-311.pyc",              "pkg/mod.py"  ),
    # Legacy sibling layout — no tag to strip, the whole stem is the module name.
    ( "pkg/mod.pyc",                                      "pkg/mod.py"  ),
    # A bare name has no directory component; the parent is the working directory.
    ( "mod.pyc",                                          "./mod.py"    ),
    ( "__pycache__/mod.cpython-313.pyc",                  "./mod.py"    ),
    # Stepping out of a root-level __pycache__ leaves an empty parent, which the
    # format string turns back into a leading slash.
    ( "/__pycache__/mod.cpython-313.pyc",                 "/mod.py"     ),
    # The real one, from the incident.
    ( "src/cosa/memory/__pycache__/lancedb_solution_manager.cpython-313.pyc",
      "src/cosa/memory/lancedb_solution_manager.py" ),
] )
def test_pyc_expected_source_maps_bytecode_back_to_its_source( pyc, expected ):
    r = _run( f"pfv_pyc_expected_source '{pyc}'" )
    assert r.returncode == 0
    assert r.stdout == expected


@pytest.mark.parametrize( "not_a_pyc", [ "pkg/mod.py", "pkg/mod", "", "mod.pyc.bak" ] )
def test_pyc_expected_source_refuses_a_non_pyc( not_a_pyc ):
    """
    Answering this for a .py would FABRICATE a source path. Returning 2 with no
    output keeps "wrong question" distinguishable from "no answer".
    """
    r = _run( f"pfv_pyc_expected_source '{not_a_pyc}'" )
    assert r.returncode == 2
    assert r.stdout == ""


@pytest.mark.parametrize( "pyc, expected", [
    ( "pkg/__pycache__/mod.cpython-313.pyc", "DEAD"       ),
    ( "__pycache__/mod.cpython-313.pyc",     "DEAD"       ),
    ( "pkg/mod.pyc",                         "SOURCELESS" ),
    ( "mod.pyc",                             "SOURCELESS" ),
] )
def test_pyc_orphan_class_separates_what_runs_from_what_cannot( pyc, expected ):
    r = _run( f"pfv_pyc_orphan_class '{pyc}'" )
    assert r.returncode == 0
    assert r.stdout == expected


def test_pyc_orphan_class_refuses_a_non_pyc():
    r = _run( "pfv_pyc_orphan_class 'pkg/mod.py'" )
    assert r.returncode == 2
    assert r.stdout == ""


def test_the_class_split_matches_what_cpython_ACTUALLY_does( tmp_path ):
    """
    THE MEASUREMENT THE TIERING RESTS ON — run against the live interpreter, not
    asserted from the PEP.

    A __pycache__ orphan is INERT: Python refuses to import it once the .py is
    gone. A sibling .pyc is LIVE: sourceless import still works. If that ever
    stops being true, this test fails and the BLOCK/WARN split in preflight-vm.sh
    B5 is wrong — which is the only reason the split is defensible at all. Tiering
    a deploy-blocker on bytecode that provably cannot execute would be an alarm on
    something that cannot hurt anyone, and readers learn to skip such tiers.
    """
    pkg = tmp_path / "impl"
    pkg.mkdir()
    ( pkg / "ghost.py" ).write_text( "VALUE = 'orphan'\n" )
    compiled = subprocess.run(
        [ "python3", "-c", "import ghost" ], cwd=pkg, capture_output=True, text=True
    )
    assert compiled.returncode == 0, compiled.stderr

    ( pkg / "ghost.py" ).unlink()
    cached = list( ( pkg / "__pycache__" ).glob( "ghost.*.pyc" ) )
    assert len( cached ) == 1

    inert = subprocess.run(
        [ "python3", "-c", "import ghost" ], cwd=pkg, capture_output=True, text=True
    )
    assert inert.returncode != 0
    assert "ModuleNotFoundError" in inert.stderr
    assert _run( f"pfv_pyc_orphan_class '{cached[ 0 ]}'" ).stdout == "DEAD"

    sibling = pkg / "ghost.pyc"
    sibling.write_bytes( cached[ 0 ].read_bytes() )
    live = subprocess.run(
        [ "python3", "-c", "import ghost; print( ghost.VALUE )" ],
        cwd=pkg, capture_output=True, text=True
    )
    assert live.returncode == 0, live.stderr
    assert "orphan" in live.stdout
    assert _run( f"pfv_pyc_orphan_class '{sibling}'" ).stdout == "SOURCELESS"


def _plant( root, rel, body="" ):
    p = root / rel
    p.parent.mkdir( parents=True, exist_ok=True )
    p.write_text( body )
    return p


def test_scan_orphan_pyc_is_SILENT_and_zero_on_a_clean_tree( tmp_path ):
    _plant( tmp_path, "pkg/live.py", "x = 1\n" )
    _plant( tmp_path, "pkg/__pycache__/live.cpython-313.pyc" )
    _plant( tmp_path, "pkg/__pycache__/live.cpython-313-pytest-8.4.2.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 0
    assert r.stdout == ""


def test_scan_orphan_pyc_reports_a_dead_orphan( tmp_path ):
    _plant( tmp_path, "pkg/live.py", "x = 1\n" )
    orphan = _plant( tmp_path, "pkg/__pycache__/lancedb_solution_manager.cpython-313.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 1
    assert r.stdout.strip().split( "\n" ) == [ f"DEAD\t{orphan}" ]


def test_scan_orphan_pyc_reports_a_sourceless_orphan( tmp_path ):
    orphan = _plant( tmp_path, "pkg/ghost.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 1
    assert r.stdout.strip().split( "\n" ) == [ f"SOURCELESS\t{orphan}" ]


def test_scan_orphan_pyc_classifies_a_mixed_tree( tmp_path ):
    _plant( tmp_path, "pkg/live.py", "x = 1\n" )
    _plant( tmp_path, "pkg/__pycache__/live.cpython-313.pyc" )
    dead = _plant( tmp_path, "pkg/__pycache__/gone.cpython-313.pyc" )
    live = _plant( tmp_path, "pkg/ghost.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 1
    assert sorted( r.stdout.strip().split( "\n" ) ) == sorted(
        [ f"DEAD\t{dead}", f"SOURCELESS\t{live}" ]
    )


@pytest.mark.parametrize( "pruned", [
    ".venv/lib/site-packages",
    "venv/lib",
    "node_modules/thing",
    ".git/hooks",
    "site-packages/wheelpkg",
    ".claude/worktrees/other-checkout/src/cosa",
] )
def test_scan_orphan_pyc_prunes_trees_that_are_not_ours( tmp_path, pruned ):
    """
    A wheel may legitimately ship .pyc without .py, and a worktree is a second
    checkout whose bytecode no deploy serves. Reporting either buries the real
    finding — the same noise problem as the pytest tag, from a different direction.
    """
    _plant( tmp_path, f"{pruned}/__pycache__/thirdparty.cpython-313.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 0
    assert r.stdout == ""


def test_scan_orphan_pyc_still_sees_a_real_orphan_beside_a_pruned_tree( tmp_path ):
    """
    The negative control for the pruning test above: prove the prune skips the
    vendored tree and not simply everything. Without this, all six parametrised
    cases could pass on a scanner that found nothing anywhere.
    """
    _plant( tmp_path, ".venv/lib/__pycache__/thirdparty.cpython-313.pyc" )
    orphan = _plant( tmp_path, "pkg/__pycache__/ours.cpython-313.pyc" )
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}'" )
    assert r.returncode == 1
    assert r.stdout.strip().split( "\n" ) == [ f"DEAD\t{orphan}" ]


def test_scan_orphan_pyc_returns_2_when_it_could_not_look( tmp_path ):
    """
    NOT 0. A scan that could not look must never report what a clean scan reports.
    The runner routes this through report/unknown at BLOCK tier, so an unreadable
    root stops a deploy instead of reading as coverage.
    """
    r = _run( f"pfv_scan_orphan_pyc '{tmp_path}/nowhere'" )
    assert r.returncode == 2
    assert r.stdout == ""


def test_scan_orphan_pyc_returns_2_when_handed_a_file_not_a_directory( tmp_path ):
    f = _plant( tmp_path, "notadir.txt", "x" )
    r = _run( f"pfv_scan_orphan_pyc '{f}'" )
    assert r.returncode == 2
    assert r.stdout == ""


def test_scan_orphan_pyc_runs_against_the_real_repo_tree():
    """
    The instrument is exercised against the tree it exists to police. A scanner
    proven only on fixtures can pass while being unable to walk production layout
    — which is exactly how the pytest-tag defect survived the fixtures and only
    surfaced on first contact with this repo.
    """
    src = os.path.join( PROJECT_ROOT, "src" )
    r = _run( f"pfv_scan_orphan_pyc '{src}'" )
    assert r.returncode in ( 0, 1 )
    for line in [ l for l in r.stdout.split( "\n" ) if l ]:
        cls, _, path = line.partition( "\t" )
        assert cls in ( "DEAD", "SOURCELESS" )
        assert path.endswith( ".pyc" )


# ══════════════════════════════════════════════════════════════════════════
# pfv_environ_lookup  (row e7048496 — the /proc/1/environ witness)
# ══════════════════════════════════════════════════════════════════════════

def test_environ_lookup_finds_a_set_variable():
    r = _run( "printf 'A=1\\nJWT_SECRET_KEY=deadbeef\\nB=2\\n' | pfv_environ_lookup JWT_SECRET_KEY" )
    assert r.returncode == 0
    assert r.stdout == "deadbeef"


def test_environ_lookup_returns_nonzero_for_an_absent_variable():
    """The failing arm. Without it the function could `return 0` always and every
    caller would read UNSET as SET."""
    r = _run( "printf 'A=1\\nB=2\\n' | pfv_environ_lookup JWT_SECRET_KEY" )
    assert r.returncode == 1
    assert r.stdout == ""


def test_environ_lookup_reports_set_but_EMPTY_as_set():
    """Set-but-empty and unset are DIFFERENT failures with different remedies; C6
    reports them differently, so the witness must not collapse them."""
    r = _run( "printf 'JWT_SECRET_KEY=\\nB=2\\n' | pfv_environ_lookup JWT_SECRET_KEY" )
    assert r.returncode == 0
    assert r.stdout == ""


def test_environ_lookup_keeps_equals_signs_inside_the_value():
    r = _run( "printf 'DSN=host=db;port=5432\\n' | pfv_environ_lookup DSN" )
    assert r.returncode == 0
    assert r.stdout == "host=db;port=5432"


def test_environ_lookup_does_not_match_a_name_that_is_merely_a_suffix():
    """`GH_TOKEN` must not be answered by a line for `MY_GH_TOKEN` — a sloppy match
    would pass a deploy on the strength of the wrong variable."""
    r = _run( "printf 'MY_GH_TOKEN=x\\n' | pfv_environ_lookup GH_TOKEN" )
    assert r.returncode == 1


def test_environ_lookup_takes_the_FIRST_match():
    """getenv() in the container returns the first entry; the witness must agree with
    what the process itself would see."""
    r = _run( "printf 'X=first\\nX=second\\n' | pfv_environ_lookup X" )
    assert r.returncode == 0
    assert r.stdout == "first"


def test_environ_lookup_reads_a_final_line_with_no_trailing_newline():
    r = _run( "printf 'A=1\\nX=last' | pfv_environ_lookup X" )
    assert r.returncode == 0
    assert r.stdout == "last"


# ══════════════════════════════════════════════════════════════════════════
# pfv_env_file_supplies  (row e7048496 — the bootstrap exemption's evidence)
# ══════════════════════════════════════════════════════════════════════════

def test_env_file_supplies_returns_0_for_a_nonempty_value( tmp_path ):
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "OTHER=1\nJWT_SECRET_KEY=0123456789abcdef\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 0


def test_env_file_supplies_returns_1_for_an_EMPTY_value( tmp_path ):
    """An empty entry must NOT read as supply: `${VAR:?}` aborts on empty exactly as
    it aborts on unset, so the recreate would fail and the exemption would have been
    a false promise."""
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "JWT_SECRET_KEY=\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 1


def test_env_file_supplies_returns_2_when_the_name_is_absent( tmp_path ):
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "OTHER=1\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 2


def test_env_file_supplies_returns_3_when_the_file_is_unreadable( tmp_path ):
    """Cannot-tell is its own answer and is never a pass — the rule pfv_classify_probe
    exists to enforce."""
    missing = tmp_path / "nope.env"
    assert _run( f"pfv_env_file_supplies '{missing}' JWT_SECRET_KEY" ).returncode == 3
    assert _run( "pfv_env_file_supplies '' JWT_SECRET_KEY" ).returncode == 3


def test_env_file_supplies_ignores_a_COMMENTED_OUT_assignment( tmp_path ):
    """cloud-gpu.env:31 carries exactly this shape for CLAUDE_CODE_OAUTH_TOKEN, so a
    scanner counting `#NAME=...` as supply would manufacture a false exemption on a
    real file in this repo."""
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "# CLAUDE_CODE_OAUTH_TOKEN=sk-live-xxxx\n" )
    assert _run( f"pfv_env_file_supplies '{f}' CLAUDE_CODE_OAUTH_TOKEN" ).returncode == 2
    f.write_text( "   #CLAUDE_CODE_OAUTH_TOKEN=sk-live-xxxx\n" )
    assert _run( f"pfv_env_file_supplies '{f}' CLAUDE_CODE_OAUTH_TOKEN" ).returncode == 2


def test_env_file_supplies_lets_the_LAST_assignment_win( tmp_path ):
    """Both compose's env-file reader and a shell resolve a repeated name to the last
    one, so a later blank-out must be seen as the blank-out it is."""
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "JWT_SECRET_KEY=good\nJWT_SECRET_KEY=\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 1
    f.write_text( "JWT_SECRET_KEY=\nJWT_SECRET_KEY=good\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 0


def test_env_file_supplies_accepts_an_export_prefixed_shell_style_file( tmp_path ):
    f = tmp_path / "host.env"
    f.write_text( "  export JWT_SECRET_KEY=abc\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 0


def test_env_file_supplies_strips_one_layer_of_matching_quotes( tmp_path ):
    f = tmp_path / "cloud-gpu.env"
    f.write_text( 'JWT_SECRET_KEY=""\n' )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 1, \
        "a quoted-empty value is still empty"
    f.write_text( "JWT_SECRET_KEY='abc'\n" )
    assert _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" ).returncode == 0


def test_env_file_supplies_does_not_match_a_name_that_is_merely_a_suffix( tmp_path ):
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "MY_GH_TOKEN=x\n" )
    assert _run( f"pfv_env_file_supplies '{f}' GH_TOKEN" ).returncode == 2


def test_env_file_supplies_never_prints_the_secret( tmp_path ):
    """These rows are SECRET-shaped and a preflight is run precisely when someone is
    confused — i.e. when they are most likely to paste its output somewhere."""
    f = tmp_path / "cloud-gpu.env"
    f.write_text( "JWT_SECRET_KEY=super-secret-value\n" )
    r = _run( f"pfv_env_file_supplies '{f}' JWT_SECRET_KEY" )
    assert "super-secret-value" not in r.stdout
    assert "super-secret-value" not in r.stderr


# ═════════════════════════════════════════════════════════════
# pfv_mcp_registration_env (row c9252819)
# ═════════════════════════════════════════════════════════════
#
# Every test here asserts stderr is empty beside the return code. The reader exits 4
# with a message on stderr when it fails internally, so a crash can no longer pass for
# the return code a test expected.

_VOICE_VAR  = "LUPIN_CONFIG_MGR_CLI_ARGS"
_GOOD_VALUE = "config_path=/src/conf/lupin-app.ini splainer_path=/src/conf/lupin-app-splainer.ini config_block_id=Lupin:+Development"


def _registration( tmp_path, body ):
    f = tmp_path / "claude.json"
    f.write_text( body )
    return f


def _registration_env( f ):
    return _run( f"pfv_mcp_registration_env '{f}' cosa-voice {_VOICE_VAR}" )


def test_registration_env_prints_the_value_when_present( tmp_path ):
    import json
    f = _registration( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": {
        "command" : "/venv/bin/python",
        "env"     : { "LUPIN_ROOT": "/r", _VOICE_VAR: "config_block_id=Lupin:+Development" },
    } } } ) )
    r = _registration_env( f )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "user\tconfig_block_id=Lupin:+Development"
    assert r.stderr == ""


def test_registration_env_is_1_when_the_server_is_registered_without_the_variable( tmp_path ):
    # The defect itself: PYTHONPATH and LUPIN_ROOT only, as the VM's registration was.
    import json
    f = _registration( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": {
        "env": { "PYTHONPATH": "/r/src", "LUPIN_ROOT": "/r" },
    } } } ) )
    r = _registration_env( f )
    assert r.returncode == 1
    assert r.stdout == "user"
    assert r.stderr == ""


@pytest.mark.parametrize( "entry", [
    '{ "env": { "LUPIN_CONFIG_MGR_CLI_ARGS": "" } }',
    '{ "env": { "LUPIN_CONFIG_MGR_CLI_ARGS": "   " } }',
    '{ "env": { "LUPIN_CONFIG_MGR_CLI_ARGS": 7 } }',
    '{ "env": [ ] }',
    '{ }',
] )
def test_registration_env_is_1_for_an_empty_blank_or_non_string_value( tmp_path, entry ):
    f = _registration( tmp_path, '{ "mcpServers": { "cosa-voice": ' + entry + ' } }' )
    r = _registration_env( f )
    assert r.returncode == 1
    assert r.stdout == "user"
    assert r.stderr == ""


@pytest.mark.parametrize( "body", [
    '{ "mcpServers": { "some-other-server": { "env": { "LUPIN_CONFIG_MGR_CLI_ARGS": "x" } } } }',
    '{ "mcpServers": [ ] }',
    '{ "projects": { "/p": { "mcpServers": { "some-other-server": { } } } } }',
    '{ }',
] )
def test_registration_env_is_2_when_the_server_is_registered_nowhere( tmp_path, body ):
    r = _registration_env( _registration( tmp_path, body ) )
    assert r.returncode == 2
    assert r.stdout == ""
    assert r.stderr == ""


def test_registration_env_is_2_for_a_missing_file( tmp_path ):
    r = _registration_env( tmp_path / "absent.json" )
    assert r.returncode == 2
    assert r.stderr == ""


def test_registration_env_is_4_for_a_file_that_exists_and_cannot_be_read( tmp_path ):
    # Wrong owner or mode is the VM's usual defect. It is not "nothing registered".
    # Two guards give this answer, the shell's -r test and the reader's own OSError arm;
    # this test cannot tell which ran, and either alone is enough.
    if os.geteuid() == 0: pytest.skip( "root reads a mode-000 file, so the case cannot be built" )
    f = _registration( tmp_path, '{ "mcpServers": { "cosa-voice": { "env": { } } } }' )
    f.chmod( 0 )
    try:
        r = _registration_env( f )
    finally:
        f.chmod( 0o600 )
    assert r.returncode == 4
    assert r.stdout == ""
    assert r.stderr == ""


@pytest.mark.parametrize( "body", [
    'this is not json',
    '[ ]',
    '{ "mcpServers": { "cosa-voice": "not an object" } }',
    '{ "projects": { "/p": { "mcpServers": { "cosa-voice": 7 } } } }',
] )
def test_registration_env_is_3_when_the_file_or_an_entry_is_not_the_expected_shape( tmp_path, body ):
    r = _registration_env( _registration( tmp_path, body ) )
    assert r.returncode == 3
    assert r.stdout == ""
    assert r.stderr == ""


def test_registration_env_checks_a_local_scope_entry_as_well_as_the_user_one( tmp_path ):
    # A good user-scope entry does not excuse a local-scope one without the variable:
    # a session started in that project directory may run the local entry.
    import json
    good = { "env": { _VOICE_VAR: "v" } }
    bad  = { "env": { "LUPIN_ROOT": "/r" } }
    f = _registration( tmp_path, json.dumps( {
        "mcpServers" : { "cosa-voice": good },
        "projects"   : { "/mnt/b": { "mcpServers": { "cosa-voice": bad } },
                         "/mnt/a": { "mcpServers": { "cosa-voice": bad } },
                         "/mnt/c": { "mcpServers": { "cosa-voice": good } },
                         "/mnt/d": { "allowedTools": [] } },
    } ) )
    r = _registration_env( f )
    assert r.returncode == 1
    assert r.stdout.split( "\n" ) == [ "local:/mnt/a", "local:/mnt/b" ]
    assert r.stderr == ""


def test_registration_env_finds_a_server_registered_only_at_local_scope( tmp_path ):
    import json
    f = _registration( tmp_path, json.dumps( {
        "projects": { "/mnt/a": { "mcpServers": { "cosa-voice": { "env": { _VOICE_VAR: "local-value" } } } } },
    } ) )
    r = _registration_env( f )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "local:/mnt/a\tlocal-value"


def test_registration_env_prints_every_scope_and_value_when_all_carry_the_variable( tmp_path ):
    # The caller judges each value, so none may be dropped: the local one is the one a
    # session in that directory runs. Each value is printed as it is stored.
    import json
    f = _registration( tmp_path, json.dumps( {
        "mcpServers" : { "cosa-voice": { "env": { _VOICE_VAR: "user-value" } } },
        "projects"   : { "/mnt/b": { "mcpServers": { "cosa-voice": { "env": { _VOICE_VAR: "b value two" } } } },
                         "/mnt/a": { "mcpServers": { "cosa-voice": { "env": { _VOICE_VAR: "a-value" } } } } },
    } ) )
    r = _registration_env( f )
    assert r.returncode == 0, r.stderr
    assert r.stdout.split( "\n" ) == [ "user\tuser-value", "local:/mnt/a\ta-value", "local:/mnt/b\tb value two" ]


@pytest.mark.parametrize( "value", [ "a=1\tb=2", "a=1  b=2", " a=1 b=2", "a=1 b=2 ", "a=1\nb=2" ] )
def test_registration_env_is_1_for_a_value_the_settings_reader_cannot_split( tmp_path, value ):
    # ConfigurationManager splits the value on single spaces only. A tab, a doubled
    # space or a space at either end gives it a word with no usable key, so such a
    # value is reported with the others that cannot be used, never tidied and passed.
    import json
    f = _registration( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": { "env": { _VOICE_VAR: value } } } } ) )
    r = _registration_env( f )
    assert r.returncode == 1
    assert r.stdout == "user (value has whitespace other than single spaces)"
    assert r.stderr == ""


def test_registration_env_names_the_top_level_entry_as_the_caller_says( tmp_path ):
    # A project .mcp.json has the same shape as the user file; its entry is project scope.
    import json
    f = _registration( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": { "env": { _VOICE_VAR: "v" } } } } ) )
    r = _run( f"pfv_mcp_registration_env '{f}' cosa-voice {_VOICE_VAR} project" )
    assert r.returncode == 0 and r.stdout == "project\tv"
    f.write_text( json.dumps( { "mcpServers": { "cosa-voice": { "env": {} } } } ) )
    r = _run( f"pfv_mcp_registration_env '{f}' cosa-voice {_VOICE_VAR} project" )
    assert r.returncode == 1 and r.stdout == "project"


def test_registration_env_reports_its_own_failure_as_4_with_the_cause_on_stderr( tmp_path ):
    # No input file makes the reader fail unexpectedly, so the failure is planted in the
    # interpreter: a json module on PYTHONPATH whose load raises an error the reader does
    # not expect. Without the shim this file ("{}") is a plain 2, registered nowhere.
    shim = tmp_path / "shim"; shim.mkdir()
    ( shim / "json.py" ).write_text( "def load( f ): raise RuntimeError( 'planted' )\n" )
    f = _registration( tmp_path, "{}" )
    r = _run( f"PYTHONPATH='{shim}' pfv_mcp_registration_env '{f}' cosa-voice {_VOICE_VAR}" )
    assert r.returncode == 4
    assert r.stdout == ""
    assert "reader failed" in r.stderr and "planted" in r.stderr
    assert _registration_env( f ).returncode == 2


# ═════════════════════════════════════════════════════════════
# pfv_config_mgr_args_resolve (row c9252819)
# ═════════════════════════════════════════════════════════════

def _resolve( value, root=PROJECT_ROOT ):
    return _run( f"pfv_config_mgr_args_resolve '{value}' '{root}'" )


def test_the_value_the_installer_writes_resolves_against_the_real_settings_file():
    # The value is read from the installer, not retyped, so the two cannot drift apart.
    text  = open( os.path.join( PROJECT_ROOT, "src/scripts/install-cosa-voice.sh" ), encoding="utf-8" ).read()
    lines = [ l for l in text.split( "\n" ) if l.startswith( "CONFIG_MGR_CLI_ARGS=" ) ]
    assert len( lines ) == 1, lines
    value = lines[ 0 ].split( "=", 1 )[ 1 ].strip( '"' ).replace( "$LUPIN_MCP_CONFIG_BLOCK", "Lupin:+Development" )
    assert value == _GOOD_VALUE
    r = _resolve( value )
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout == ""


_INI, _SPL = "config_path=/src/conf/lupin-app.ini", "splainer_path=/src/conf/lupin-app-splainer.ini"


@pytest.mark.parametrize( "value, reason", [
    ( "x",                                                     "no config_path= in the value" ),
    ( f"{_SPL} config_block_id=Lupin:+Development",            "no config_path= in the value" ),
    ( f"{_INI} config_block_id=Lupin:+Development",            "no splainer_path= in the value" ),
    ( f"{_INI} {_SPL}",                                        "no config_block_id= in the value" ),
    ( f"config_path=/src/conf/absent.ini {_SPL} config_block_id=Lupin:+Development",
                                                               "config_path /src/conf/absent.ini is not a readable file" ),
    ( f"config_path=/src/conf {_SPL} config_block_id=Lupin:+Development",
                                                               "config_path /src/conf is not a readable file" ),
    ( f"{_INI} splainer_path=/src/conf/absent.ini config_block_id=Lupin:+Development",
                                                               "splainer_path /src/conf/absent.ini is not a readable file" ),
    ( f"{_INI} {_SPL} config_block_id=Lupin:+No-Such",         "no [Lupin: No-Such] block in /src/conf/lupin-app.ini" ),
    ( f"{_INI} {_SPL} config_block_id=Lupin:",                 "no [Lupin:] block in /src/conf/lupin-app.ini" ),
] )
def test_a_value_that_names_nothing_does_not_resolve_and_says_why( value, reason ):
    r = _resolve( value )
    assert r.returncode == 1
    assert reason in r.stdout
    assert r.stderr == ""


def _tree( tmp_path, ini_text ):
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "a.ini" ).write_bytes( ini_text )
    ( tmp_path / "src" / "conf" / "s.ini" ).write_text( "" )
    return lambda block: _resolve( f"config_path=/src/conf/a.ini splainer_path=/src/conf/s.ini config_block_id={block}", tmp_path ).returncode


def test_the_block_must_match_a_whole_header_line( tmp_path ):
    # "Lupin: Dev" is a prefix of a real header and must not pass for it; nor may a
    # header that only appears inside a longer line.
    rc = _tree( tmp_path, b"[Lupin: Development]\nk = [Lupin: Inline]\n" )
    assert rc( "Lupin:+Development" ) == 0
    assert rc( "Lupin:+Dev" ) == 1
    assert rc( "Lupin:+Inline" ) == 1


def test_a_header_with_trailing_whitespace_or_windows_line_ends_still_matches( tmp_path ):
    # The settings reader takes these, so this check must not block them.
    rc = _tree( tmp_path, b"[Lupin: Development] \t \r\nk = v\r\n[Lupin: Testing]\r\nk = v\r\n" )
    assert rc( "Lupin:+Development" ) == 0
    assert rc( "Lupin:+Testing" ) == 0


def test_an_indented_header_is_not_a_block_here_because_it_is_not_one_to_the_settings_reader( tmp_path ):
    # The claim about the reader is checked against the reader's own parser, in the
    # same test, on the same bytes.
    import configparser
    text = b"[Lupin: Development]\nk = v\n  [Lupin: Testing]\n"
    rc = _tree( tmp_path, text )
    parser = configparser.ConfigParser()
    parser.read_string( text.decode() )
    assert parser.sections() == [ "Lupin: Development" ]
    assert rc( "Lupin:+Development" ) == 0
    assert rc( "Lupin:+Testing" ) == 1


def test_resolve_does_not_expand_a_word_of_the_value_against_the_working_directory( tmp_path ):
    # An unquoted loop over the value would turn "*" into the names in the cwd. One of
    # those names is planted to look like the missing word; a quoted read never sees it.
    rc = _tree( tmp_path, b"[B]\n" )
    ( tmp_path / "config_block_id=B" ).write_text( "" )
    r = _run( "pfv_config_mgr_args_resolve 'config_path=/src/conf/a.ini splainer_path=/src/conf/s.ini config_block_id*' "
              f"'{tmp_path}'", cwd=str( tmp_path ) )
    assert r.returncode == 1 and "no config_block_id= in the value" in r.stdout
    assert rc( "B" ) == 0


# ═════════════════════════════════════════════════════════════
# lupin-vm.sh install-voice (row c9252819)
# ═════════════════════════════════════════════════════════════
#
# Check A3b itself is driven end to end, through the real preflight script, in
# test_preflight_vm_host_test_fixes.py beside A8 and A9.

def _install_voice_dry_run( **extra ):
    vm = os.path.join( PROJECT_ROOT, "src/scripts/lupin-vm.sh" )
    env = { k: v for k, v in os.environ.items() if k != "LUPIN_MCP_CONFIG_BLOCK" }
    env.update( LUPIN_GCP_PROJECT_ID="example-project", **extra )
    return subprocess.run( [ "bash", vm, "--dry-run", "install-voice" ], capture_output=True, text=True, env=env )


def test_the_vm_script_has_a_dry_runnable_step_that_runs_the_installer_on_the_vm():
    r   = _install_voice_dry_run()
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    lines = out.split( "\n" )
    # Each line the installer cannot run without, as a whole line: the PATH that finds
    # `claude`, the tree, and the venv (its default is the arbiter's and is refused).
    assert 'export PATH="$HOME/.local/bin:$PATH"' in lines
    assert "export LUPIN_ROOT=/mnt/lupin-data/lupin" in lines
    assert 'export LUPIN_CC_VENV="$HOME/.venv-lupin-mcp"' in lines
    assert "bash /mnt/lupin-data/lupin/src/scripts/install-cosa-voice.sh" in lines
    assert "gcloud" not in out, "a dry run must not show or run the ssh call"
    assert "LUPIN_MCP_CONFIG_BLOCK" not in out, "unset on the dev box means the installer's default applies"


def _readback( tmp_path, claude_json ):
    """
    Run the part of the remote command that follows the installer, here.

    Requires:
        - claude_json is the text of the fake home's .claude.json, or None for no file

    Ensures:
        - takes the lines after the installer line from the real dry run, points the VM
          tree at this checkout, and runs them under set -e with a fake HOME
        - returns the CompletedProcess
    """
    lines     = _install_voice_dry_run().stderr.rstrip( "\n" ).split( "\n" )
    installer = lines.index( "bash /mnt/lupin-data/lupin/src/scripts/install-cosa-voice.sh" )
    assert lines[ 0 ] == "set -e"    # the remote command is the whole of stderr; the log line goes to stdout
    tail = "\n".join( lines[ installer + 1 : ] )
    assert tail.count( "/mnt/lupin-data/lupin" ) == 2, tail
    script = "set -e\n" + tail.replace( "/mnt/lupin-data/lupin", PROJECT_ROOT ) + "\necho REACHED-THE-END\n"
    home = tmp_path / "home"; home.mkdir()
    if claude_json is not None: ( home / ".claude.json" ).write_text( claude_json )
    return subprocess.run( [ "bash", "-c", script ], capture_output=True, text=True, env=dict( os.environ, HOME=str( home ) ) )


def _entry( value ):
    return { "env": { _VOICE_VAR: value } }


def test_the_readback_after_the_installer_prints_every_scope_and_value_and_carries_on( tmp_path ):
    import json
    r = _readback( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": _entry( _GOOD_VALUE ) },
                                           "projects": { "/p": { "mcpServers": { "cosa-voice": _entry( _GOOD_VALUE ) } } } } ) )
    assert r.returncode == 0, r.stderr
    assert f"user\t{_GOOD_VALUE}" in r.stdout.split( "\n" )
    assert f"local:/p\t{_GOOD_VALUE}" in r.stdout.split( "\n" )
    assert r.stdout.rstrip().endswith( "REACHED-THE-END" )


def test_the_readback_stops_and_names_a_stale_local_entry_the_installer_does_not_remove( tmp_path ):
    import json
    r = _readback( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": _entry( _GOOD_VALUE ) },
                                           "projects": { "/old": { "mcpServers": { "cosa-voice": { "env": {} } } } } } ) )
    assert r.returncode == 1
    assert "READBACK FAILED (reader rc=1" in r.stderr and "local:/old" in r.stderr
    assert "REACHED-THE-END" not in r.stdout


def test_the_readback_stops_and_says_why_when_a_registered_value_names_no_block( tmp_path ):
    import json
    bad = _GOOD_VALUE.replace( "Lupin:+Development", "Lupin:+Testing-GSC" )
    r = _readback( tmp_path, json.dumps( { "mcpServers": { "cosa-voice": _entry( _GOOD_VALUE ) },
                                           "projects": { "/p": { "mcpServers": { "cosa-voice": _entry( bad ) } } } } ) )
    assert r.returncode == 1
    assert "READBACK FAILED: the local:/p registration does not resolve: no [Lupin: Testing-GSC] block" in r.stderr
    assert "REACHED-THE-END" not in r.stdout


@pytest.mark.parametrize( "claude_json, rc", [ ( None, 2 ), ( "{}", 2 ), ( "{oops", 3 ) ] )
def test_the_readback_stops_with_the_readers_code_when_nothing_was_registered( tmp_path, claude_json, rc ):
    r = _readback( tmp_path, claude_json )
    assert r.returncode == rc
    assert f"READBACK FAILED (reader rc={rc}" in r.stderr
    assert "REACHED-THE-END" not in r.stdout


def test_install_voice_accepts_each_block_this_checkouts_settings_file_has():
    # The refusal below is only worth something if real names get through.
    text   = open( os.path.join( PROJECT_ROOT, "src/conf/lupin-app.ini" ), encoding="utf-8" ).read()
    blocks = [ l.strip()[ 1:-1 ] for l in text.split( "\n" ) if l.startswith( "[Lupin: " ) ]
    assert len( blocks ) >= 5, blocks
    for block in blocks:
        r = _install_voice_dry_run( LUPIN_MCP_CONFIG_BLOCK=block.replace( " ", "+" ) )
        assert r.returncode == 0, ( block, r.stderr )


def test_install_voice_refuses_a_block_name_this_checkouts_settings_file_does_not_have():
    # A transposed letter passes the character check and would be registered as typed.
    r = _install_voice_dry_run( LUPIN_MCP_CONFIG_BLOCK="Lupin:+Testing-GSC" )
    assert r.returncode == 1
    assert "names no block in" in r.stderr and "[Lupin: Testing-GSC]" in r.stderr
    assert "install-cosa-voice.sh" not in r.stdout + r.stderr


def test_install_voice_passes_the_settings_block_through_when_the_dev_box_sets_one():
    r = _install_voice_dry_run( LUPIN_MCP_CONFIG_BLOCK="Lupin:+Testing-GCS" )
    lines = ( r.stdout + r.stderr ).split( "\n" )
    assert r.returncode == 0
    block = lines.index( "export LUPIN_MCP_CONFIG_BLOCK=Lupin:+Testing-GCS" )
    assert block < lines.index( "bash /mnt/lupin-data/lupin/src/scripts/install-cosa-voice.sh" )


@pytest.mark.parametrize( "block", [ "x; touch /tmp/owned", "a b", "$(id)", "a'b", 'a"b' ] )
def test_install_voice_refuses_a_settings_block_that_could_break_out_of_the_remote_command( block ):
    r = _install_voice_dry_run( LUPIN_MCP_CONFIG_BLOCK=block )
    assert r.returncode == 1
    assert "LUPIN_MCP_CONFIG_BLOCK may hold only" in r.stderr
    assert "install-cosa-voice.sh" not in r.stdout + r.stderr


def test_the_usage_text_and_the_checklist_name_what_install_voice_needs_and_changes():
    usage = subprocess.run( [ "bash", os.path.join( PROJECT_ROOT, "src/scripts/lupin-vm.sh" ), "--help" ],
                            capture_output=True, text=True )
    text  = usage.stdout + usage.stderr
    start = text.index( "  install-voice" )
    entry = " ".join( text[ start : text.index( "  push-env  ", start ) ].split() )
    doc   = open( os.path.join( PROJECT_ROOT, "src/docs/vm-new-host-checklist.md" ), encoding="utf-8" ).read()
    doc   = " ".join( doc[ doc.index( "## The voice-server registration" ) : doc.index( "## Adding a new item" ) ].split() )
    for needed in ( "install-cli", "push-env (writes ~/.lupin/config)", "push-unversioned (delivers the notification key)",
                    "LUPIN_MCP_CONFIG_BLOCK", "defaults to Lupin:+Development", ".bak-<epoch>", "reading" ):
        assert needed in entry, needed
        assert needed in doc.replace( "`", "" ), needed
    assert "any hand-added env on that entry is dropped" in entry
    assert "any `env` added to it by hand is dropped" in doc
