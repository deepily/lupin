"""
Unit tests for R3b — `lupin-vm.sh push-env` derives its export set from
src/conf/env-contract.tsv, and REFUSES to run when the two disagree.

WHAT IS ACTUALLY UNDER TEST, and why it is not the generation:
    Today the contract's push-env rows and lupin-vm.sh's PUSH_ENV_VALUES map
    agree exactly — five names, same five. A test asserting "the generated set
    equals what we already emit" would therefore pass against the OLD hardcoded
    script too, and prove nothing. The deliverable is the COMPARATOR: the two
    directions of divergence that were previously undetectable.

        contract row with no value  -> preflight asserts the var, tells the
                                       operator "run push-env", and push-env
                                       does not write it. A remedy that cannot
                                       clear its own alarm.
        value with no contract row  -> push-env writes a var nothing declares,
                                       so preflight never checks it and its
                                       absence on a fresh VM is found by failing.

    Every death-path test below is therefore paired with the SHIPPED contract
    passing through the same harness (test_shipped_tree_dry_run_succeeds). That
    control is load-bearing: a harness that mis-stages the temp tree would make
    `die` fire for an unrelated reason and every negative test would go green
    against a script that never ran the check at all.

Venue: :7999 / AI-discretionary. No gcloud, no SSH, no network, no persistent
state — every invocation is `--dry-run` against a staged temp tree with a fake
$HOME, so the real dev box's ~/.bashrc and the real VM are untouched.

Coverage note (100% mandate): bash is not line-instrumented by the pytest --cov
gate, so — following test_preflight_vm_lib.py's precedent — every BRANCH of the
new lib function and both arms of the comparator are asserted behaviorally,
including at least one input per branch that makes the code return NON-zero.
"""
import os
import shutil
import subprocess

import pytest

import cosa.utils.util as cu

PROJECT_ROOT  = cu.get_project_root()
LIB_PATH      = os.path.join( PROJECT_ROOT, "src/scripts/lib/preflight-vm-lib.sh" )
VM_SCRIPT     = os.path.join( PROJECT_ROOT, "src/scripts/lupin-vm.sh" )
CONTRACT_PATH = os.path.join( PROJECT_ROOT, "src/conf/env-contract.tsv" )

TAB = "\t"

# The set the shipped contract declares, in contract order. Asserted as an
# ORDERED list, not a set: push-env appends to ~/.bashrc, and a later export
# overrides an earlier one, so order is behaviour rather than presentation.
EXPECTED_PUSH_ENV_VARS = [
    "LUPIN_ROOT",
    "PLANNING_IS_PROMPTING_ROOT",
    "DEEPILY_PROJECTS_DIR",
    "DEEPILY_DATA_DIR",
    "LUPIN_CC_VENV",
    "LUPIN_DEV_EMAIL",
]


def _run_lib( snippet ):
    """
    Source the preflight lib and run a bash snippet.

    Requires:
        - snippet is a bash fragment that may call any pfv_* function

    Ensures:
        - returns the CompletedProcess (stdout/stderr captured, text mode)
        - `set -u` is ON, so an unset-variable bug in the lib fails loudly here
          instead of silently evaluating to empty
    """
    full = f"set -uo pipefail; source '{LIB_PATH}'; {snippet}"
    return subprocess.run( [ "bash", "-c", full ], capture_output=True, text=True )


def _row( name, surface, writer, shape="LITERAL", req="REQUIRED", note="n" ):
    """
    Build one 6-column env-contract.tsv row.

    Requires:
        - all six arguments are strings containing no tab

    Ensures:
        - returns a tab-separated row with exactly 6 fields and no newline
    """
    return TAB.join( [ name, surface, writer, shape, req, note ] )


# ══════════════════════════════════════════════════════════════════════════
# pfv_contract_push_env_names — the derivation
# ══════════════════════════════════════════════════════════════════════════

def test_shipped_contract_yields_the_expected_ordered_set():
    r = _run_lib( f"pfv_contract_push_env_names '{CONTRACT_PATH}'" )
    assert r.returncode == 0, r.stderr
    names = [ l for l in r.stdout.split( "\n" ) if l ]
    assert names == EXPECTED_PUSH_ENV_VARS


def test_selection_predicate_is_surface_and_writer( tmp_path ):
    """Both columns must participate — neither alone decides membership."""
    c = tmp_path / "c.tsv"
    c.write_text( "\n".join( [
        "# comment",
        _row( "TAKE_HOST",      "HOST",      "push-env"          ),
        _row( "TAKE_BOTH",      "BOTH",      "push-env + compose" ),
        _row( "SKIP_CONTAINER", "CONTAINER", "push-env"          ),  # right writer, wrong surface
        _row( "SKIP_WRITER",    "HOST",      "minted ON the target" ),  # right surface, wrong writer
    ] ) + "\n" )
    r = _run_lib( f"pfv_contract_push_env_names '{c}'" )
    assert r.returncode == 0, r.stderr
    assert [ l for l in r.stdout.split( "\n" ) if l ] == [ "TAKE_HOST", "TAKE_BOTH" ]


def test_unreadable_contract_returns_1_and_prints_nothing( tmp_path ):
    """
    A broken input must NOT read as "no vars to write" — that would let push-env
    write nothing and report success.
    """
    r = _run_lib( f"pfv_contract_push_env_names '{tmp_path}/does-not-exist.tsv'" )
    assert r.returncode == 1
    assert r.stdout == ""


def test_readable_but_empty_is_rc0_distinct_from_unreadable( tmp_path ):
    """The empty ANSWER and the broken INPUT are different outcomes."""
    c = tmp_path / "c.tsv"
    c.write_text( "# only comments\n\n" + _row( "X", "CONTAINER", "compose" ) + "\n" )
    r = _run_lib( f"pfv_contract_push_env_names '{c}'" )
    assert r.returncode == 0
    assert r.stdout == ""


def test_malformed_short_row_is_skipped_not_guessed( tmp_path ):
    """A 3-field row has no writer column; it must not be treated as matching."""
    c = tmp_path / "c.tsv"
    c.write_text(
        f"SHORT{TAB}HOST{TAB}push-env\n"          # only 3 fields — malformed
        + _row( "GOOD", "HOST", "push-env" ) + "\n"
    )
    r = _run_lib( f"pfv_contract_push_env_names '{c}'" )
    assert r.returncode == 0, r.stderr
    assert [ l for l in r.stdout.split( "\n" ) if l ] == [ "GOOD" ]


# ══════════════════════════════════════════════════════════════════════════
# pfv_contract_remedy — the READ-side half of the same defect
#
# Preflight's A1 used to hardcode "lupin-vm.sh push-env" as the remedy for
# every host var. Four contract vars are not push-env's to write, so for those
# the instrument prescribed a command that cannot clear its own alarm — and for
# LUPIN_API_KEY, running it would look like compliance while changing nothing.
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize( "writer,expected_fragment", [
    ( "push-env",             "lupin-vm.sh push-env" ),
    ( "push-env + compose",   "lupin-vm.sh push-env" ),
    ( "minted ON the target", "MINT it on the target" ),
    ( "operator ~/.bashrc",   "by hand in the operator's ~/.bashrc" ),
    ( "cloud-gpu.env",        "push-unversioned" ),
    ( "compose",              "compose environment:" ),
] )
def test_remedy_is_derived_from_the_writer_column( writer, expected_fragment ):
    r = _run_lib( f"pfv_contract_remedy '{writer}' 'SOME_VAR'" )
    assert r.returncode == 0, r.stderr
    assert expected_fragment in r.stdout


@pytest.mark.parametrize( "writer", [ "minted ON the target", "operator ~/.bashrc" ] )
def test_non_push_env_writers_never_prescribe_push_env( writer ):
    """
    The defect itself, stated as a negative. `push-env` must not appear in the
    remedy for a var push-env does not write.
    """
    r = _run_lib( f"pfv_contract_remedy '{writer}' 'SOME_VAR'" )
    assert r.returncode == 0, r.stderr
    assert "lupin-vm.sh push-env" not in r.stdout


def test_unknown_writer_names_it_verbatim_and_guesses_no_command():
    """
    An unrecognized writer must not fall back to a plausible command. A wrong
    remedy costs more than an honest "the contract says X writes this".
    """
    r = _run_lib( "pfv_contract_remedy 'some brand new writer' 'SOME_VAR'" )
    assert r.returncode == 0, r.stderr
    assert "some brand new writer" in r.stdout
    assert "lupin-vm.sh" not in r.stdout


def test_shipped_contract_has_no_var_misrouted_to_push_env():
    """
    REGRESSION CONTROL, asserted over the REAL contract rather than fixtures.

    For every host-surface row, the remedy may mention `lupin-vm.sh push-env`
    IF AND ONLY IF the writer column does. This is the assertion that goes red
    if A1 is ever reverted to a constant remedy — the four vars that exposed
    the defect (LUPIN_API_KEY, CLAUDE_CODE_USE_VERTEX, ANTHROPIC_VERTEX_PROJECT_ID,
    CLOUD_ML_REGION) are live rows, so this test is checking production data,
    not a fixture that encodes the answer.
    """
    snippet = (
        f"while IFS= read -r row; do "
        f"  s=$( pfv_contract_field \"$row\" 2 ); "
        f"  w=$( pfv_contract_field \"$row\" 3 ); "
        f"  n=$( pfv_contract_field \"$row\" 1 ); "
        f"  case \"$s\" in CONTAINER) continue ;; esac; "
        f"  printf '%s|%s|%s\\n' \"$n\" \"$w\" \"$( pfv_contract_remedy \"$w\" \"$n\" )\"; "
        f"done < <( pfv_parse_manifest '{CONTRACT_PATH}' )"
    )
    r = _run_lib( snippet )
    assert r.returncode == 0, r.stderr

    rows = [ l for l in r.stdout.split( "\n" ) if l ]
    assert rows, "no host-surface rows parsed — the harness saw nothing"

    misrouted = []
    for line in rows:
        name, writer, remedy = line.split( "|", 2 )
        if "lupin-vm.sh push-env" in remedy and "push-env" not in writer:
            misrouted.append( ( name, writer ) )
    assert not misrouted, f"remedy prescribes push-env for vars it does not write: {misrouted}"

    # And the positive arm — a test that only proves absence would also pass if
    # pfv_contract_remedy returned the empty string for everything.
    push_env_rows = [ l for l in rows if "push-env" in l.split( "|" )[ 1 ] ]
    assert push_env_rows, "no push-env-written rows found — the negative arm proves nothing"
    for line in push_env_rows:
        assert "lupin-vm.sh push-env" in line.split( "|", 2 )[ 2 ]


# ══════════════════════════════════════════════════════════════════════════
# The comparator in lupin-vm.sh push-env — the actual deliverable
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def staged_tree( tmp_path ):
    """
    Stage a minimal repo layout so lupin-vm.sh's BASH_SOURCE-relative DEV_ROOT
    resolves inside tmp_path, letting a test doctor the contract without
    touching the real one.

    Ensures:
        - returns ( script_path, contract_path, env ) where env carries a fake
          HOME holding the two alias files push-env checks for BEFORE reaching
          the comparator — so a death in these tests is always the comparator's
          and never a missing dev-box file
    """
    ( tmp_path / "src/scripts/lib" ).mkdir( parents=True )
    ( tmp_path / "src/conf" ).mkdir( parents=True )
    shutil.copy( VM_SCRIPT, tmp_path / "src/scripts/lupin-vm.sh" )
    shutil.copy( LIB_PATH,  tmp_path / "src/scripts/lib/preflight-vm-lib.sh" )
    shutil.copy( CONTRACT_PATH, tmp_path / "src/conf/env-contract.tsv" )

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    ( fake_home / ".bash_aliases" ).write_text( "# fake\n" )
    ( fake_home / ".bash_aliases_to_uc.py" ).write_text( "# fake\n" )

    env = dict( os.environ )
    env[ "HOME" ]                 = str( fake_home )
    env[ "LUPIN_GCP_PROJECT_ID" ] = "test-project-id"

    return str( tmp_path / "src/scripts/lupin-vm.sh" ), tmp_path / "src/conf/env-contract.tsv", env


def _push_env_dry_run( script, env ):
    return subprocess.run(
        [ "bash", script, "--dry-run", "push-env" ],
        capture_output=True, text=True, env=env,
    )


def test_shipped_tree_dry_run_succeeds( staged_tree ):
    """
    CONTROL for every death test below. If the harness mis-staged the tree, the
    script would die for an unrelated reason and each negative test would pass
    against a comparator that never ran.
    """
    script, _, env = staged_tree
    r = _push_env_dry_run( script, env )
    assert r.returncode == 0, r.stderr
    for name in EXPECTED_PUSH_ENV_VARS:
        assert name in r.stdout, f"{name} missing from dry-run output"


def test_dry_run_keeps_HOME_unexpanded( staged_tree ):
    """
    LUPIN_CC_VENV's value must reach the VM as a literal $HOME. If it expanded
    on the dev box, the VM's ~/.bashrc would carry the DEV operator's home path
    — a right var name holding a wrong machine's path, which is the exact class
    of defect the contract exists to prevent.
    """
    script, _, env = staged_tree
    r = _push_env_dry_run( script, env )
    assert r.returncode == 0, r.stderr
    assert "export LUPIN_CC_VENV=$HOME/.venv-lupin-mcp" in r.stdout
    # Scope the negative to the EXPORT LINES only. The dry-run legitimately
    # echoes the fake $HOME elsewhere (the scp source paths), so asserting over
    # the whole of stdout would fail on correct output — and "the test found
    # HOME somewhere" is not the claim; "HOME was baked into a bashrc line" is.
    export_lines = [ l for l in r.stdout.split( "\n" ) if "export LUPIN_CC_VENV" in l ]
    assert export_lines, "no LUPIN_CC_VENV export line in the dry-run output"
    for line in export_lines:
        assert str( env[ "HOME" ] ) not in line, f"dev-box HOME baked into: {line}"


def test_contract_row_without_a_value_is_fatal( staged_tree ):
    """Direction 1: the contract declares a push-env var lupin-vm.sh cannot write."""
    script, contract, env = staged_tree
    contract.write_text(
        contract.read_text() + _row( "LUPIN_BRAND_NEW_VAR", "HOST", "push-env" ) + "\n"
    )
    r = _push_env_dry_run( script, env )
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "LUPIN_BRAND_NEW_VAR" in combined
    assert "no VM value" in combined


def test_value_without_a_contract_row_is_fatal( staged_tree ):
    """Direction 2: lupin-vm.sh would export a var the contract does not declare."""
    script, contract, env = staged_tree
    kept = [
        l for l in contract.read_text().split( "\n" )
        if not l.startswith( "LUPIN_DEV_EMAIL" + TAB )
    ]
    contract.write_text( "\n".join( kept ) )
    r = _push_env_dry_run( script, env )
    assert r.returncode != 0
    combined = r.stdout + r.stderr
    assert "LUPIN_DEV_EMAIL" in combined
    assert "no row in" in combined


def test_contract_declaring_no_push_env_vars_is_fatal( staged_tree ):
    """
    An empty qualifying set must abort rather than write an empty environment to
    the VM. Silently writing nothing is indistinguishable from a successful run
    whose vars were already present.
    """
    script, contract, env = staged_tree
    contract.write_text( "# every row removed\n" )
    r = _push_env_dry_run( script, env )
    assert r.returncode != 0
    assert "declares NO push-env vars" in ( r.stdout + r.stderr )


def test_unreadable_contract_is_fatal( staged_tree ):
    """The lib's rc=1 must surface as a death, not as an empty export set."""
    script, contract, env = staged_tree
    contract.unlink()
    r = _push_env_dry_run( script, env )
    assert r.returncode != 0
    assert "env contract not readable" in ( r.stdout + r.stderr )
