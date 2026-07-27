"""
`pfv_compose_var_regime` / `pfv_regime_requirement` / `pfv_requirement_agrees` —
row `b5ca8fd5`, the derive-from-compose half.

WHAT THIS REPLACES
------------------
`env-contract.tsv` has ONE `requirement` column and the venues genuinely disagree
about the same variable:

    docker-compose.cloud-gpu.yml    ${LUPIN_MODEL_SERVER_URL:?…}        REQUIRED
    docker-compose.yml              ${LUPIN_MODEL_SERVER_URL:-http://…} DEFAULTED
    docker-compose.cloud-test.yml   http://lupin-model-server:7998      LITERAL

The obvious fix is a per-venue requirement column. Mr. Radio ruled against it
(2026-07-27) and the reason is decision `2b20a6d6`: ONE fact — "which store backs
this data" — had FOUR authorities and no comparator, and reconciling three while
missing the fourth broke server startup. A per-venue column would be authority #2
for a fact compose already states. **The interpolation regime IS the requirement,
declared where the venue is defined. Adding a column duplicates it; deriving reads
it.**

⚠️ THE RISK THE TRADE ACCEPTS, AND WHY THIS FILE IS SHAPED THE WAY IT IS
------------------------------------------------------------------------
Deriving replaces a STATED fact with a PARSED one, so the parser becomes the
authority — and a parser that silently mis-classifies a form nobody enumerated
does it quietly, at a rate that reads like ordinary noise. Mr. Radio's condition
on the ruling was explicit: exercise **all three regimes plus at least one form it
should NOT match**, predict every verdict before running, and make anything
unenumerated an explicit CANNOT-DETERMINE — **never a default to OPTIONAL**,
because that waives an assertion by accident.

⇒ `test_a_form_the_reader_does_not_enumerate_is_UNKNOWN_not_ABSENT` is the test
  that caught the real defect. The first implementation matched only the KNOWN
  operators in a single regex, so `${VAR:%odd}` failed to match at all and the
  variable fell through to the not-interpolated branch — reported **ABSENT, "not
  present in this file", about a variable sitting right there**. The tier happened
  to land safe (ABSENT ⇒ UNDETERMINED, not OPTIONAL), but the FACT was false and a
  reader would have concluded the venue does not wire the var.

  Same defect class as the instrument itself is meant to remove: the parser's reach
  standing in for the file's content.

Venue: :7999-eligible. Sources the bash lib in a subprocess; no docker, no network.
"""
import os
import subprocess

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
LIB_PATH     = os.path.join( PROJECT_ROOT, "src/scripts/lib/preflight-vm-lib.sh" )

CLOUD_GPU  = os.path.join( PROJECT_ROOT, "docker-compose.cloud-gpu.yml" )
LOCAL      = os.path.join( PROJECT_ROOT, "docker-compose.yml" )
CLOUD_TEST = os.path.join( PROJECT_ROOT, "docker-compose.cloud-test.yml" )


def _run( snippet ):
    """Source the lib and run a snippet under `set -u`, returning CompletedProcess."""
    full = f"set -uo pipefail; source '{LIB_PATH}'; {snippet}"
    return subprocess.run( [ "bash", "-c", full ], capture_output=True, text=True )


def _regime( path, name ):
    """( regime_token, returncode ) for one variable in one compose file."""
    p = _run( f"pfv_compose_var_regime '{path}' '{name}'" )
    return p.stdout, p.returncode


def _fixture( tmp_path, body ):
    f = tmp_path / "compose.yml"
    f.write_text( body )
    return str( f )


# ══════════════════════════════════════════════════════════════════════════
# THE FULL GRAMMAR — all seven interpolation forms, each named
# ══════════════════════════════════════════════════════════════════════════
# Measured 2026-07-27 across every docker-compose*.yml in the repo: 27
# interpolations = 13 `:?` + 13 `:-` + 1 bare, and the classes SUM to the total.
# (A tally that did NOT reconcile — 53 classified out of 27 — is what exposed the
# first, broken counting script. A count is not a measurement until it balances.)
# The other four forms appear ZERO times today. That is a reason to handle them,
# not a reason to skip them: absence now is not absence later.

def test_every_grammar_form_maps_to_its_own_regime( tmp_path ):
    f = _fixture( tmp_path,
        "services:\n"
        "  a:\n"
        "    environment:\n"
        "      A: ${V_COLON_DASH:-d}\n"       # default when unset OR empty
        "      B: ${V_DASH-d}\n"              # default when unset only
        "      C: ${V_COLON_QUERY:?e}\n"      # compose ABORTS when unset OR empty
        "      D: ${V_QUERY?e}\n"             # compose ABORTS when unset only
        "      E: ${V_COLON_PLUS:+r}\n"       # substitute only when set AND non-empty
        "      F: ${V_PLUS+r}\n"              # substitute only when set
        "      G: ${V_BARE}\n"                # empty when unset; compose only WARNS
    )
    assert _regime( f, "V_COLON_DASH"  ) == ( "DEFAULTED", 0 )
    assert _regime( f, "V_DASH"        ) == ( "DEFAULTED", 0 )
    assert _regime( f, "V_COLON_QUERY" ) == ( "REQUIRED",  0 )
    assert _regime( f, "V_QUERY"       ) == ( "REQUIRED",  0 )
    assert _regime( f, "V_COLON_PLUS"  ) == ( "ALTERNATE", 0 )
    assert _regime( f, "V_PLUS"        ) == ( "ALTERNATE", 0 )
    assert _regime( f, "V_BARE"        ) == ( "BARE",      0 )


def test_a_braceless_dollar_VAR_is_a_reference_not_an_absence( tmp_path ):
    """
    `$VAR` without braces is legal compose and means exactly `${VAR}`. It appears
    ZERO times in this repo today — so a reader that ignored it would be correct on
    every current file and wrong the first time someone wrote one, silently, by
    reporting a referenced variable as absent.
    """
    f = _fixture( tmp_path, "services:\n  a:\n    environment:\n      A: $V_BRACELESS\n" )
    assert _regime( f, "V_BRACELESS" ) == ( "BARE", 0 )


# ══════════════════════════════════════════════════════════════════════════
# THE FORMS IT MUST *NOT* MATCH — Mr. Radio's condition on the ruling
# ══════════════════════════════════════════════════════════════════════════

def test_a_form_the_reader_does_not_enumerate_is_UNKNOWN_not_ABSENT( tmp_path ):
    """
    ⚠️ THE REGRESSION GUARD FOR A REAL DEFECT, found by predicting this verdict
    before running it.

    The first implementation matched only known operators in one regex. An
    unenumerated operator therefore did not match AT ALL, and the variable fell
    through to the not-interpolated branch — reported **ABSENT**, i.e. "this compose
    file never references it", about a variable on the line being read.

    The requirement tier happened to land safe, because ABSENT maps to UNDETERMINED
    rather than OPTIONAL. But the reported FACT was false, and "the venue does not
    wire this var" sends a reader somewhere entirely different from "I do not
    understand how this var is written."

    ⇒ The reader now asks "is it referenced at all?" FIRST, and only then "which
      operator?" Referenced-but-unclassifiable is a loud UNKNOWN with rc=2.
    """
    f = _fixture( tmp_path, "services:\n  a:\n    environment:\n      A: ${V_WEIRD:%oddop}\n" )
    regime, rc = _regime( f, "V_WEIRD" )
    assert regime == "UNKNOWN", (
        f"an unenumerated operator reported {regime!r} — if that is ABSENT, the "
        "parser is claiming a variable it can see is not there"
    )
    assert rc == 2, "UNKNOWN must be cannot-determine, never a pass"


def test_a_prefix_of_another_variable_is_never_confused_for_it( tmp_path ):
    """
    `${LUPIN_ROOT}` and `${LUPIN_ROOT_EXTRA}` are different variables. An unanchored
    match would let the second answer for the first — the count-standing-in-for-a-set
    shape, where a hit is attributed to the wrong member.
    """
    f = _fixture( tmp_path, "services:\n  a:\n    environment:\n      A: ${V_PREFIX_EXTRA:-x}\n" )
    assert _regime( f, "V_PREFIX" ) == ( "ABSENT", 0 )
    assert _regime( f, "V_PREFIX_EXTRA" ) == ( "DEFAULTED", 0 )


def test_one_file_using_two_operators_for_one_var_is_CONFLICT( tmp_path ):
    """
    Reporting either requirement would pick a side silently, and the file really is
    inconsistent. CONFLICT names the inconsistency instead of resolving it by luck.
    """
    f = _fixture( tmp_path,
        "services:\n  a:\n    environment:\n"
        "      A: ${V_BOTH:?a}\n"
        "      B: ${V_BOTH:-b}\n"
    )
    assert _regime( f, "V_BOTH" ) == ( "CONFLICT", 2 )


def test_LITERAL_and_ABSENT_are_kept_apart( tmp_path ):
    """
    "pinned to a hardcoded value here" and "not present at all" are different facts
    with different consequences: the first means the env var is not consulted on this
    venue, the second means the venue may have forgotten it. Collapsing them would
    report a deliberate pin as an omission.
    """
    f = _fixture( tmp_path,
        "services:\n  a:\n    environment:\n"
        "      V_PINNED: http://hardcoded:7998\n"
    )
    assert _regime( f, "V_PINNED"  ) == ( "LITERAL", 0 )
    assert _regime( f, "V_NOWHERE" ) == ( "ABSENT",  0 )


def test_an_unreadable_file_or_empty_name_is_UNKNOWN_not_ABSENT():
    """
    A file that cannot be read has told you NOTHING about the variable. Reporting
    ABSENT would convert "I could not look" into "I looked and it is not there".
    """
    assert _regime( "/definitely/not/a/file.yml", "V" ) == ( "UNKNOWN", 2 )
    assert _regime( CLOUD_GPU, "" )                     == ( "UNKNOWN", 2 )


# ══════════════════════════════════════════════════════════════════════════
# regime -> requirement
# ══════════════════════════════════════════════════════════════════════════

def test_only_the_aborting_forms_map_to_REQUIRED():
    for regime in ( "REQUIRED", ):
        p = _run( f"pfv_regime_requirement {regime}" )
        assert ( p.stdout, p.returncode ) == ( "REQUIRED", 0 )
    for regime in ( "DEFAULTED", "ALTERNATE", "BARE" ):
        p = _run( f"pfv_regime_requirement {regime}" )
        assert ( p.stdout, p.returncode ) == ( "OPTIONAL", 0 ), regime


def test_anything_unrecognized_maps_to_UNDETERMINED_and_NEVER_to_OPTIONAL():
    """
    ⚠️ THE POLARITY THAT MATTERS. A typo, a future compose operator, or a token this
    mapping has never seen must surface as "I cannot tell". Mapping it to OPTIONAL
    would WAIVE an assertion by accident — silently, and only for the cases nobody
    anticipated, which are exactly the cases worth catching.
    """
    for token in ( "LITERAL", "ABSENT", "CONFLICT", "UNKNOWN", "", "TYPO", "optional" ):
        p = _run( f"pfv_regime_requirement '{token}'" )
        assert p.stdout == "UNDETERMINED", f"{token!r} mapped to {p.stdout!r}"
        assert p.stdout != "OPTIONAL"
        assert p.returncode == 2


# ══════════════════════════════════════════════════════════════════════════
# the comparator — the half that pays for deriving
# ══════════════════════════════════════════════════════════════════════════

def test_the_comparator_reports_agreement_disagreement_and_cannot_tell():
    """
    Deriving removes a duplicate authority, but the contract column still exists and
    is still read by other consumers. Two authorities with nothing comparing them is
    the defect; two authorities WITH a comparator is a check.
    """
    assert _run( "pfv_requirement_agrees REQUIRED REQUIRED; echo -n $?" ).stdout == "0"
    assert _run( "pfv_requirement_agrees OPTIONAL OPTIONAL; echo -n $?" ).stdout == "0"
    assert _run( "pfv_requirement_agrees REQUIRED OPTIONAL; echo -n $?" ).stdout == "1"
    assert _run( "pfv_requirement_agrees OPTIONAL REQUIRED; echo -n $?" ).stdout == "1"


def test_the_comparator_refuses_rather_than_agreeing_when_it_cannot_compare():
    """
    A comparator that answers "fine" whenever it cannot parse its input is quietest
    exactly when something has changed underneath it.
    """
    assert _run( "pfv_requirement_agrees REQUIRED UNDETERMINED; echo -n $?" ).stdout == "2"
    assert _run( "pfv_requirement_agrees '' REQUIRED; echo -n $?" ).stdout          == "2"
    assert _run( "pfv_requirement_agrees REQUIRED ''; echo -n $?" ).stdout          == "2"


def test_the_comparator_resolves_OPTIONAL_UNLESS_before_comparing():
    """
    An `OPTIONAL_UNLESS:VAR=VAL` row means REQUIRED only while its condition holds.
    Comparing its literal text against a derived REQUIRED/OPTIONAL would report a
    disagreement that is an artifact of the encoding, not a fact about the venue.
    """
    cond = "OPTIONAL_UNLESS:PFV_PROBE=1"
    assert _run( f"PFV_PROBE=1; pfv_requirement_agrees '{cond}' REQUIRED; echo -n $?" ).stdout == "0"
    assert _run( f"PFV_PROBE=0; pfv_requirement_agrees '{cond}' OPTIONAL; echo -n $?" ).stdout == "0"
    assert _run( f"PFV_PROBE=1; pfv_requirement_agrees '{cond}' OPTIONAL; echo -n $?" ).stdout == "1"


# ══════════════════════════════════════════════════════════════════════════
# THE REAL FILES — the venue split this whole design exists for
# ══════════════════════════════════════════════════════════════════════════

def test_the_three_venues_really_do_disagree_about_one_variable():
    """
    ⚠️ THE ROW'S STATED PRECONDITION, pinned against the shipped files rather than
    quoted from the row.

    If these three ever collapse to one answer, the argument for deriving evaporates
    and this test should be the thing that says so — not a reader re-discovering the
    split a year from now.
    """
    gpu,  _ = _regime( CLOUD_GPU,  "LUPIN_MODEL_SERVER_URL" )
    loc,  _ = _regime( LOCAL,      "LUPIN_MODEL_SERVER_URL" )
    test, _ = _regime( CLOUD_TEST, "LUPIN_MODEL_SERVER_URL" )

    assert ( gpu, loc, test ) == ( "REQUIRED", "DEFAULTED", "LITERAL" )
    assert len( { gpu, loc, test } ) == 3, "the venue split is the premise of this design"


def test_no_CONTAINER_contract_row_reads_as_UNKNOWN_on_the_target_venue():
    """
    THE SWEEP. Every `surface=CONTAINER` row classified against the venue preflight
    actually targets. An UNKNOWN here means the reader met a form it does not
    enumerate in a file we ship — the parser-reach failure, live.

    Deliberately asserts NO specific regimes beyond that: pinning all thirteen would
    make this test fail every time someone legitimately edits the compose file, and a
    test that cries wolf gets muted.
    """
    contract = os.path.join( PROJECT_ROOT, "src/conf/env-contract.tsv" )
    p = _run(
        f'while IFS= read -r row; do '
        f'  n="$(pfv_contract_field "$row" 1)" || continue; '
        f'  s="$(pfv_contract_field "$row" 2)"; '
        f'  [ "$s" = CONTAINER ] || continue; '
        f'  printf "%s=%s\\n" "$n" "$(pfv_compose_var_regime {CLOUD_GPU} "$n")"; '
        f'done < <(pfv_parse_manifest {contract})'
    )
    lines = [ l for l in p.stdout.splitlines() if l ]
    assert lines, "the sweep found NO surface=CONTAINER rows — the instrument, not the contract"
    bad = [ l for l in lines if l.endswith( ( "=UNKNOWN", "=CONFLICT" ) ) ]
    assert not bad, f"unclassifiable on the shipped cloud-gpu compose: {bad}"


def test_the_sweep_can_actually_find_something( tmp_path ):
    """
    CONTROL for the sweep above. Its assertion is a NULL — "no row is unclassifiable"
    — and a null proves nothing until the search is shown able to return a hit.
    Same reader, same call shape, against a file that DOES contain an unenumerable
    form: it must come back UNKNOWN.
    """
    f = _fixture( tmp_path, "services:\n  a:\n    environment:\n      A: ${DB_USER:%nope}\n" )
    assert _regime( f, "DB_USER" ) == ( "UNKNOWN", 2 )
