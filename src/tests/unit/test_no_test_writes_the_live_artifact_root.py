"""
The static guard on the tier's artifact root (rows `fd0cd863` × `691d49db`).

WHY A GUARD AND NOT JUST THE FIX
--------------------------------
`fd0cd863` was a test fixture writing the tier's REAL triage path. Measured in the
running test container 2026-07-27:

    /tmp/integration-latest.log  ->  line-1 line-2 line-3 line-4 line-5 line-6
    /tmp/unit-20260727-185252.log -> "first run"

The fix isolates those fixtures onto `_ARTIFACT_DIR`. **A moved path without a guard
re-arms the defect at the new location** — Clayton 😎's point, and it is the day's
ordering lesson wearing a different coat: the remedy and the thing that keeps the
remedy true have to land together, or the next writer re-opens it and nothing says so.

🔴 WHAT THIS CAN AND CANNOT SEE — READ BEFORE TRUSTING A GREEN
This is an AST scan for STRING LITERALS under the artifact root inside test modules.

**IT WOULD NOT HAVE CAUGHT `fd0cd863`.** The offending tests named no path at all: they
called `_run_suite()` / `_write_stdout_log()` and the *production* code computed the live
path. A source-text predicate cannot see a write that no source text describes.

So this guard covers the ADJACENT mode — a future test hardcoding the live root — while
the mode that actually bit is closed structurally, by the autouse `_isolate_artifact_root`
fixture plus `_ARTIFACT_DIR` being the single knob all three production paths derive from.
**Neither half is sufficient, and a green here is not evidence about the other.** Saying
so is the point: this file's own subject is instruments that report on something other
than what they claim.

It also cannot see a path assembled at runtime (`os.path.join( root, name )`, an f-string
over a variable, a config value). A floor on "tests that NAME the live root", never a
proof that none reaches it.

The complement — that the *production* writers all derive from one knob — is enforced
structurally instead: `_write_stdout_log`, the junit path and the symlink all resolve
through `TestSuiteJob._ARTIFACT_DIR`, so there is no second path to forget. That pair
is the actual guarantee; neither half is sufficient alone.

Venue: :7999-eligible — pure AST over the repo's own source. No container, no server.
"""
import ast
import os

import pytest

import cosa.utils.util as cu
from cosa.agents.test_suite.attestation import TEST_SUITE_IO_SUBDIR
from cosa.agents.test_suite.job import TestSuiteJob

PROJECT_ROOT = cu.get_project_root()

# The roots a test must never name — READ from production, never copied. A second
# hardcoded copy here would be the drift this file exists to prevent, committed inside
# the prevention.
#
# `TEST_SUITE_IO_SUBDIR` is deliberately the widest of Clayton's roots (`691d49db`,
# commit `c55bf44f`): it covers artifacts AND the attestation ledger, so a future third
# subdir beneath it is guarded by construction rather than needing an edit here.
# ⚠️ artifact_root() is NOT called here. It fails closed under pytest by design
# (c29beb07), so resolving it at module scope would raise at COLLECTION and take this
# guard — and every module importing it — down. The durable root is spelled from its
# repo-relative constant plus the project root instead, which is the same value by
# construction without invoking the refusal.
FORBIDDEN_ROOTS = (
    "/tmp/",                                                       # the legacy live root
    os.path.join( PROJECT_ROOT, TEST_SUITE_IO_SUBDIR ) + "/",      # the durable home
    TEST_SUITE_IO_SUBDIR + "/",                                    # repo-relative spelling
)

# Basenames the tier itself owns. A test naming one of these under a forbidden root is
# writing (or asserting on) the live triage surface.
TIER_ARTIFACT_HINTS = tuple( TestSuiteJob._LOG_BASENAMES.values() ) + ( "-junit-", "-latest.log" )

TEST_ROOTS = ( "src/tests", "src/cosa/tests" )


def _test_modules():
    for root in TEST_ROOTS:
        base = os.path.join( PROJECT_ROOT, root )
        for dirpath, dirnames, filenames in os.walk( base ):
            dirnames[ : ] = [ d for d in dirnames if d != "__pycache__" ]
            for fn in filenames:
                if fn.startswith( "test_" ) and fn.endswith( ".py" ):
                    yield os.path.join( dirpath, fn )


def _assignment_lines( source, name ):
    """
    Ensures:
        - returns the line number of every top-level-or-nested assignment to `name`
        - extracted from `source` (not from a fixed module) so the SINGULARITY check
          below can be driven in both directions without editing production code
    """
    tree  = ast.parse( source )
    lines = []
    for node in ast.walk( tree ):
        if isinstance( node, ast.Assign ):
            for tgt in node.targets:
                if isinstance( tgt, ast.Name ) and tgt.id == name: lines.append( node.lineno )
    return lines


def _offending_literals( path ):
    """Every string constant in `path` that names a tier artifact under a forbidden root."""
    try:
        tree = ast.parse( open( path, encoding="utf-8" ).read(), filename=path )
    except SyntaxError:
        return []                                  # a broken file is another test's problem
    hits = []
    for node in ast.walk( tree ):
        if not ( isinstance( node, ast.Constant ) and isinstance( node.value, str ) ): continue
        s = node.value
        if not any( s.startswith( r ) for r in FORBIDDEN_ROOTS ): continue
        if not any( hint in s for hint in TIER_ARTIFACT_HINTS ):  continue
        hits.append( ( node.lineno, s ) )
    return hits


def test_no_test_module_names_a_tier_artifact_under_the_live_root():
    """
    A test that hardcodes the live artifact root is one edit away from writing it.

    The remedy is `monkeypatch.setattr( TestSuiteJob, "_ARTIFACT_DIR", str( tmp_path ) )`
    — one knob, which moves the log file, the symlink AND the junit XML together.
    Redirecting only `_LOG_SYMLINKS`, as this codebase did before 2026-07-27, moves the
    symlink and leaves the real file being written: a partial isolation that reads as done.
    """
    offenders = []
    for path in _test_modules():
        for lineno, literal in _offending_literals( path ):
            rel = os.path.relpath( path, PROJECT_ROOT )
            offenders.append( f"{rel}:{lineno}  {literal!r}" )

    assert not offenders, (
        "test modules name the tier's LIVE artifact root — the path a human triaging a "
        "scheduled run reads:\n  " + "\n  ".join( offenders )
        + "\n\nRemedy: monkeypatch TestSuiteJob._ARTIFACT_DIR to a tmp_path (autouse, so a "
          "test added later cannot reach the live path by omission). See the "
          "_isolate_artifact_root fixture in test_test_suite_job.py."
    )


@pytest.mark.parametrize( "source,expected", [
    ( "class J:\n    _ARTIFACT_DIR = '/tmp'\n",                                   1 ),
    ( "class J:\n    _ARTIFACT_DIR = '/tmp'\nclass K:\n    _ARTIFACT_DIR = '/x'\n", 2 ),
    ( "class J:\n    OTHER = '/tmp'\n",                                          0 ),
] )
def test_the_singularity_predicate_counts_correctly( source, expected ):
    """
    The singularity check is only as good as its counter. Driven here on synthetic
    source, because the real assertion reads production and cannot be made to fail
    without editing it — an assertion nobody can see fail is not one you can trust.
    """
    assert len( _assignment_lines( source, "_ARTIFACT_DIR" ) ) == expected


def test_the_scan_actually_examines_files():
    """
    A guard that walked zero files would pass loudly and mean nothing — the same
    can't-fail shape these rows are about, one level up.
    """
    assert sum( 1 for _ in _test_modules() ) > 500


@pytest.mark.parametrize( "suffix,should_flag", [
    ( "unit-latest.log",                True  ),   # the live symlink
    ( "integration-junit-2026.xml",     True  ),   # the live junit path
    ( "some-unrelated-scratch.txt",     False ),   # under the root, but not a tier artifact
] )
def test_the_predicate_bites_in_both_directions( suffix, should_flag, tmp_path ):
    """
    RED-FIRST, both arms. A predicate asserted only on offenders passes on a constant
    `[]`; one asserted only on innocents passes on a constant `[everything]`. Neither
    arm alone distinguishes a working scan from a broken one.

    ⚠️ The probe paths are ASSEMBLED here rather than written as literals. Spelling them
    out — `"/tmp/unit-latest.log"` — made this file match its own predicate and fail on
    its own test data, which is the day's recurring shape once more: the instrument
    matching a DESCRIPTION of the thing it hunts. Exempting this file by name would have
    "fixed" it by carving a hole in the very scan, so the data is built instead.
    """
    probe = tmp_path / "test_probe.py"
    probe.write_text( "X = %r\n" % os.path.join( "/tmp", suffix ) )
    assert bool( _offending_literals( str( probe ) ) ) is should_flag


@pytest.mark.parametrize( "literal", [ "unit-latest.log", "/var/lupin/io/unit-latest.log" ] )
def test_a_basename_or_a_different_root_is_not_an_offender( literal, tmp_path ):
    """Rooted-ness is load-bearing: the guard must not fire on every mention of a name."""
    probe = tmp_path / "test_probe.py"
    probe.write_text( "X = %r\n" % literal )
    assert _offending_literals( str( probe ) ) == []


def test_the_artifact_root_has_exactly_ONE_definition_site():
    """
    The structural half — and it asserts SINGULARITY, not agreement.

    🔴 Mr Radio's correction, and it is the sharper claim. A test that checks
    `actual_log`, `junit_xml_path` and the symlink all resolve to the same root
    **passes on the day someone re-splits them and updates all three.** Agreement is a
    coincidence that holds until the next edit; one definition is structural.

    That is not hypothetical here — `fd0cd863` IS the agreement failure. The symlink map
    was redirectable and `actual_log` hardcoded `/tmp/`, so a test could redirect one and
    still write the other. Two knobs is how they got out of step.

    So: scan `job.py` for root-shaped string literals and require that exactly one
    survives — the `_ARTIFACT_DIR` assignment itself.
    """
    import inspect
    job_mod     = __import__( "cosa.agents.test_suite.job", fromlist=[ "x" ] )
    definitions = _assignment_lines( inspect.getsource( job_mod ), "_ARTIFACT_DIR" )

    assert len( definitions ) == 1, (
        f"_ARTIFACT_DIR is defined {len( definitions )} times (lines {definitions}) — "
        "the artifact root must have exactly ONE definition site. Two definitions agree "
        "only until someone edits one of them, which is precisely how the symlink map and "
        "actual_log got out of step in fd0cd863."
    )

    # And no writer may reconstitute a root of its own beside it.
    offenders = []
    for name in ( "_write_stdout_log", "_log_symlink_path", "_artifact_path" ):
        fn_src = inspect.getsource( getattr( TestSuiteJob, name ) )
        for lit in ( '"/tmp', "'/tmp", '"/var/lupin/io', "'/var/lupin/io" ):
            if lit in fn_src: offenders.append( f"{name} hardcodes {lit}…" )
    assert not offenders, (
        "a writer hardcodes an artifact root beside _ARTIFACT_DIR:\n  "
        + "\n  ".join( offenders )
        + "\nRedirecting _ARTIFACT_DIR would no longer move it — the partial isolation of fd0cd863."
    )
