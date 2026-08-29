"""
Row `e2099400` §3a — nothing outside our own tree may sit in the coverage denominator.

WHAT WAS IN THERE. Measured at `6f75b227`: 63,240 statements, 2,337 missing, and **~610 of the
missing were CPython's own `json` module** — encoder.py 235 @ 0%, decoder.py 206 @ 3%,
scanner.py 56 @ 0%, tool.py 41 @ 0%, __init__.py 61 @ 6%. Roughly a quarter of the gap in a
100% mandate was code this project does not own and cannot test.

⚠️ THE MECHANISM WAS TWICE MISDIAGNOSED, BOTH TIMES BY LOOKING FOR THE WRONG THING. The plan
first said "find what sets COVERAGE_PROCESS_START" — the venv's a1_coverage.pth starts coverage
in any child when that variable is set. A review then corrected it to "nothing in the tree sets
it, so the source is outside the repo and not ours to fix". Both are wrong, and grepping for
that variable is why: it was never the vector. The real one, reproduced 2026-08-26 rather than
argued — src/tests/unit/test_runner_coverage_blindness.py spawns child pytests with `--cov=json`
(that scope deliberately needs a real module to measure) and those children INHERITED the
parent's COVERAGE_FILE, so their stdlib data was written into the tier's own data file. Running
that one file under coverage with an isolated data file recorded five measured files, all five
outside src/, and they are exactly the five in the report.

⇒ FIXED AT THE SOURCE (the child now gets its own COVERAGE_FILE) with a report-level `omit` as
the floor under it. This file is the control over both, because the source fix protects against
the test that exists and the omit protects against the one nobody has written yet.

⚠️ A PERCENTAGE CANNOT SEE THIS CLASS OF DEFECT — that is the whole reason a test has to. The
frame was 96% with the stdlib inside it and would have been 96% with anything else inside it
too; the number moves smoothly and says nothing about what it is measuring.

Venue: :7999-eligible. One short child pytest plus config reads; no server, no state mutation,
no network.
"""

import os
import re
import subprocess

import pytest

import cosa.utils.util as cu


PROJECT_ROOT = cu.get_project_root()
PYPROJECT    = os.path.join( PROJECT_ROOT, "pyproject.toml" )
SRC_ROOT     = os.path.join( PROJECT_ROOT, "src" ) + os.sep

# The file whose children caused it. Named rather than generalised, because this is the
# regression pin for a defect that actually happened.
HAZARD_FILE  = os.path.join( "src", "tests", "unit", "test_runner_coverage_blindness.py" )

# The five that were in the denominator. Kept verbatim so the test says what it is protecting.
THE_FIVE = [ "json/encoder.py", "json/decoder.py", "json/scanner.py", "json/tool.py", "json/__init__.py" ]


# ── the report-level floor ───────────────────────────────────────────────────

def _omit_matcher():
    """
    coverage's OWN matcher over this repo's configured omit list.

    Deliberately not a hand-rolled fnmatch: the property worth asserting is what coverage
    will actually do, and a local re-implementation of glob semantics would be asserting my
    model of coverage instead of coverage.
    """
    import coverage
    try:
        from coverage.files import GlobMatcher
    except ImportError as failure:                                  # pragma: no cover - version guard
        pytest.fail( "coverage's omit matcher moved — this guard now asserts nothing. "
                     f"Re-point it at the current API before trusting a green here: {failure}" )
    config = coverage.Coverage( config_file=PYPROJECT ).config
    return GlobMatcher( config.run_omit, "omit" )


@pytest.mark.parametrize( "stdlib_file", THE_FIVE )
def test_the_stdlib_modules_that_were_in_the_denominator_are_omitted( stdlib_file ):
    """The five by name. If a leak recurs, the report still cannot show them."""
    path = f"/home/someone/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/lib/python3.13/{stdlib_file}"
    assert _omit_matcher().match( path ), f"{stdlib_file} would be reported again"


# ⚠️ EACH CASE HERE EXISTS TO MAKE A DIFFERENT PATTERN LOAD-BEARING. The first three all
# contain a `lib/python3*` segment, so the stdlib pattern alone matches them and the
# site-packages and .venv patterns could be deleted with every test still green — measured
# by deleting them. The last two have no such segment, so they fail unless their own pattern
# is present. A redundant guard reads as three controls and is one.
@pytest.mark.parametrize( "foreign", [
    "/usr/lib/python3.13/dataclasses.py",
    "/mnt/repo/.venv/lib/python3.13/site-packages/pytest/__init__.py",
    "/opt/venv/lib/python3.12/site-packages/fastapi/routing.py",
    "/srv/app/site-packages/vendored/thing.py",          # needs */site-packages/*
    "/mnt/repo/.venv/src/editable-package/module.py",    # needs */.venv/*
] )
def test_no_interpreter_or_third_party_file_can_enter_the_frame( foreign ):
    assert _omit_matcher().match( foreign ), f"{foreign} would be measured"


@pytest.mark.parametrize( "ours", [
    "src/cosa/utils/coverage_contention.py",
    "src/lupin_cli/claude_code/hooks/register_session.py",
    "src/lupin_app/main.py",
    "src/lupin_mcp/cosa_voice_mcp.py",
] )
def test_the_omit_does_not_hide_any_of_our_own_code( ours ):
    """
    ⚠️ THE NEGATIVE HALF, AND IT IS THE IMPORTANT ONE. An omit broad enough to exclude the
    stdlib is one careless glob away from excluding us, and THAT failure is invisible: the
    percentage goes UP and everything looks better. Narrowing the frame is the exact move
    this mandate exists to forbid.
    """
    assert not _omit_matcher().match( os.path.join( PROJECT_ROOT, ours ) ), \
        f"{ours} is being omitted — the frame just got smaller and the number just got prettier"


# ── the source fix, pinned by re-running the hazard ──────────────────────────

def test_the_file_that_leaked_the_stdlib_now_records_nothing_outside_src( tmp_path ):
    """
    THE REGRESSION PIN, run against the real file rather than a model of it. Its children run
    `--cov=json` by design; what changed is that they no longer write into the parent's data
    file. Before the fix this recorded 5 measured files, all 5 outside src/.
    """
    import coverage

    data_file = str( tmp_path / "probe.data" )
    env       = dict( os.environ, LUPIN_ROOT=PROJECT_ROOT, COVERAGE_FILE=data_file )
    env.pop( "LUPIN_ALLOW_CONTENDED_COVERAGE", None )
    env[ "LUPIN_ALLOW_CONTENDED_COVERAGE" ] = "1"   # this IS a nested run; the guard is not the subject here

    done = subprocess.run(
        [ os.path.join( PROJECT_ROOT, ".venv", "bin", "pytest" ), HAZARD_FILE,
          "-q", "--no-header", "-p", "no:cacheprovider",
          # Scoped at a module the HAZARD FILE ITSELF imports (`cosa.utils.util`), not one
          # only its children touch — otherwise the parent measures nothing, the data file
          # is empty, and "no files outside src/" is true for the wrong reason.
          "--cov=cosa.utils.util", "--cov-report=", "--cov-fail-under=0" ],
        cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=600 )
    assert done.returncode == 0, f"the hazard file itself is failing:\n{done.stdout[ -3000: ]}"

    data = coverage.CoverageData( data_file )
    data.read()
    measured = sorted( data.measured_files() )
    assert measured, "nothing was measured at all — this probe would pass for the wrong reason"
    outside  = [ path for path in measured if not path.startswith( SRC_ROOT ) ]
    assert not outside, f"{len( outside )} file(s) outside src/ leaked into the data file: {outside[ :6 ]}"


# ── the property, over every test that could do it next ──────────────────────

_COV_FLAG = re.compile( r'["\']--cov[=\s"\']' )

# ⚠️ AN ASSIGNMENT, NOT A MENTION. The first version of this check accepted any file whose
# text contained the string COVERAGE_FILE — and the very comment explaining WHY a child needs
# its own data file satisfied it, so deleting the assignment underneath that comment left the
# guard green. Measured, on this file's own mutation pass.
_COV_FILE_SET = re.compile( r'COVERAGE_FILE["\']?\s*\]?\s*[:=]' )


def _test_files():
    for directory, _dirs, names in os.walk( os.path.join( PROJECT_ROOT, "src", "tests" ) ):
        if "__pycache__" in directory: continue
        for name in sorted( names ):
            if name.startswith( "test_" ) and name.endswith( ".py" ):
                yield os.path.relpath( os.path.join( directory, name ), PROJECT_ROOT )


def test_any_test_that_spawns_a_coverage_child_isolates_its_data_file():
    """
    ⚠️ THE PROPERTY, NOT THE ONE FILE. Fixing test_runner_coverage_blindness.py protects against
    the test that exists. This walks src/tests so the NEXT one — written months from now by
    somebody who has never read this row — is caught when it lands rather than when a stdlib
    module turns up in a report and somebody spends a day working out where it came from.

    ⚠️ IT IS DELIBERATELY COARSE: it asks whether a file that hands `--cov` to a child also
    mentions COVERAGE_FILE anywhere. That cannot prove the isolation is correct, only that the
    author thought about it. A precise check would have to model subprocess construction, and a
    guard nobody can read is a guard nobody maintains. Exemptions go in the dict, with a reason.
    """
    exempt = {
        # file -> why it hands --cov to nothing that writes a data file
        "src/tests/unit/test_contended_coverage_guard.py":
            "its --cov strings are arguments to a REFUSAL check that never reaches pytest",
        "src/tests/unit/test_pytest_args_policy.py":
            "asserts on argument STRINGS; spawns no coverage child",
    }
    offenders = []
    for rel in _test_files():
        if rel in exempt: continue
        body = open( os.path.join( PROJECT_ROOT, rel ) ).read()
        if not _COV_FLAG.search( body ):        continue
        if _COV_FILE_SET.search( body ):        continue
        if "subprocess" not in body:            continue
        offenders.append( rel )
    assert not offenders, (
        "these tests hand --cov to a subprocess without ever naming COVERAGE_FILE, so the child "
        f"writes into whatever data file the parent is using: {offenders}" )


def test_the_exemptions_named_above_still_exist():
    """An exemption for a file that has moved is a hole with a comment on it."""
    known = set( _test_files() )
    for rel in ( "src/tests/unit/test_contended_coverage_guard.py",
                 "src/tests/unit/test_pytest_args_policy.py" ):
        assert rel in known, f"{rel} is exempted above but is no longer there — drop the entry"
