"""
Gap 1 — a run states the tree it STARTED on as well as the one it ended on.

Store row `11253df9` gap 1: the `[tree-state]` line is emitted from the pytest
terminal-summary hook, i.e. at the END of a run, so a commit landing mid-run went
undetected. Measured on the row: the branch moved 20+ commits inside one session, and the
unit tier alone runs ~13 minutes — an ordinary occurrence, not a corner.

WHAT THESE PIN, and why each is the thing that decays silently rather than loudly:

  · the four span cases render EXACTLY, including `unmoved`. A line that says nothing when
    the tree held still is indistinguishable from a probe that never ran
  · the no-start line is BYTE-IDENTICAL to the pre-gap-1 line, because the node/c8 runners
    emit BEFORE their run and must not change output
  · the start capture costs ONE git call. The row left this gap open BECAUSE of cost — "the
    second probe's cost was not obviously worth it" — so a silent regrowth into a second
    full probe would undo the reason the design was accepted
  · a start-capture FAILURE is reported as UNKNOWN, never laundered into `unmoved`. Saying
    "the tree held still" when the truth is "I could not look" is the exact defect shape
    this module exists to catch

Design: `src/rnd/v0.2.0/2026.08.28-tree-state-gap-1-start-and-end-sha.md`.
Venue: :7999-eligible — no network, no mutation, injected git.
"""
import os
import re
import subprocess
import sys

from cosa.utils.tree_state import (
    START_SHA_UNKNOWN,
    _run_span,
    capture_start_sha,
    tree_state_line,
)

ROOT = os.environ[ "LUPIN_ROOT" ]


def _fake_git( head="abc1234", calls=None ):
    """A git that answers the whole probe, recording every call it was asked to make."""
    answers = {
        ( "rev-parse", "--short", "HEAD" )                              : head,
        ( "rev-parse", "--abbrev-ref", "HEAD" )                         : "wip-branch",
        ( "rev-parse", "--show-toplevel" )                              : "/repo",
        ( "rev-parse", "--abbrev-ref", "@{upstream}" )                  : "origin/wip-branch",
        ( "status", "--porcelain" )                                     : "",
        ( "rev-list", "--count", "HEAD..origin/wip-branch" )            : "0",
        ( "rev-list", "--count", "origin/wip-branch..HEAD" )            : "0",
        ( "rev-parse", "--path-format=absolute", "--git-common-dir" )   : "/repo/.git",
    }
    def git( *args ):
        if calls is not None: calls.append( args )
        return answers.get( args )
    return git


# ═════════════════════════════════════════════════════════════════════════════
# capture_start_sha — one call, and never None
# ═════════════════════════════════════════════════════════════════════════════

def test_capture_start_sha_costs_exactly_one_git_call():
    """
    THE COST IS THE REASON THIS DESIGN WAS ACCEPTED. The row left gap 1 open saying "the
    second probe's cost was not obviously worth it"; the answer was one call rather than
    the whole 9-call probe. If that quietly regrows, the ceiling doubles and nothing else
    in the suite would notice.
    """
    calls = []
    assert capture_start_sha( _fake_git( calls=calls ) ) == "abc1234"
    assert calls == [ ( "rev-parse", "--short", "HEAD" ) ], f"start capture made {calls}"


def test_capture_start_sha_reports_unknown_rather_than_none_when_git_cannot_answer():
    """
    NEVER None. None is the caller's way of saying "I took no start reading" — a different
    claim from "I looked and could not read it". Collapsing them lets a failed probe read
    as a deliberate point-in-time report.
    """
    assert capture_start_sha( lambda *a: None ) == START_SHA_UNKNOWN


# ═════════════════════════════════════════════════════════════════════════════
# _run_span — the four cases, exactly
# ═════════════════════════════════════════════════════════════════════════════

def test_no_start_captured_renders_no_field_at_all():
    """The node/c8 line IS the start; a span there would describe a run that has not run."""
    assert _run_span( None, "abc1234" ) == ""


def test_an_unmoved_tree_says_so_rather_than_saying_nothing():
    """Silence would be indistinguishable from a probe that never ran. `unmoved` is a measurement."""
    assert _run_span( "abc1234", "abc1234" ) == " run-span=unmoved"


def test_an_unmoved_tree_does_not_repeat_the_sha():
    """`sha=` already carries it, and by definition it equals the start."""
    assert "abc1234" not in _run_span( "abc1234", "abc1234" )


def test_a_moved_tree_names_both_ends_and_warns():
    span = _run_span( "abc1234", "def5678" )
    assert span == " run-span=abc1234..def5678 ⚠️ TREE MOVED MID-RUN"


def test_a_failed_start_capture_is_unknown_and_is_never_laundered_into_unmoved():
    """
    THE DEFECT THIS FORBIDS: reporting "the tree held still" when the truth is "I could not
    look". An UNKNOWN start must never collapse into the reassuring case.
    """
    span = _run_span( START_SHA_UNKNOWN, "abc1234" )
    assert "unmoved" not in span
    assert span == " run-span=UNKNOWN — the start sha could not be read"


# ═════════════════════════════════════════════════════════════════════════════
# tree_state_line — the span reaches the rendered line, on every sha-bearing path
# ═════════════════════════════════════════════════════════════════════════════

def test_the_line_is_byte_identical_to_the_pre_gap_1_line_when_no_start_is_given():
    """
    AC2. The node runners pass no start and their output must not move. Asserted as strict
    equality against the same call with the argument omitted, so a stray default cannot
    slip a field in.
    """
    assert tree_state_line( _fake_git() ) == tree_state_line( _fake_git(), None )
    assert "run-span" not in tree_state_line( _fake_git() )


def test_the_span_reaches_the_full_line():
    line = tree_state_line( _fake_git( head="def5678" ), "abc1234" )
    assert line.startswith( "[tree-state] sha=def5678 " )
    assert line.endswith( " run-span=abc1234..def5678 ⚠️ TREE MOVED MID-RUN" )


def test_the_span_reaches_the_line_that_has_no_comparison_ref():
    """
    A tree with no upstream and no primary branch still ran on a sha, so it still has a
    span. A degraded line is the one most likely to be read by someone already suspicious.
    """
    def git( *args ):
        if args == ( "rev-parse", "--short", "HEAD" ):        return "def5678"
        if args == ( "rev-parse", "--abbrev-ref", "HEAD" ):   return "HEAD"
        if args == ( "rev-parse", "--show-toplevel" ):        return "/repo"
        if args == ( "status", "--porcelain" ):               return ""
        return None
    line = tree_state_line( git, "abc1234" )
    assert "behind=UNKNOWN — no upstream" in line
    assert line.endswith( " run-span=abc1234..def5678 ⚠️ TREE MOVED MID-RUN" )


def test_the_span_reaches_the_line_whose_comparison_ref_could_not_be_walked():
    def git( *args ):
        if args == ( "rev-parse", "--short", "HEAD" ):                   return "def5678"
        if args == ( "rev-parse", "--abbrev-ref", "HEAD" ):              return "wip-branch"
        if args == ( "rev-parse", "--show-toplevel" ):                   return "/repo"
        if args == ( "rev-parse", "--abbrev-ref", "@{upstream}" ):       return "origin/wip-branch"
        if args == ( "status", "--porcelain" ):                          return ""
        return None                                          # rev-list refuses
    line = tree_state_line( git, "abc1234" )
    assert "the comparison ref could not be walked" in line
    assert line.endswith( " run-span=abc1234..def5678 ⚠️ TREE MOVED MID-RUN" )


def test_a_hostile_git_still_yields_one_line_and_raises_nothing():
    """The module's standing total-by-construction guarantee, re-checked with a start sha."""
    def git( *args ): raise UnicodeDecodeError( "utf-8", b"", 0, 1, "boom" )
    line = tree_state_line( git, "abc1234" )
    assert line.startswith( "[tree-state] UNKNOWN" )
    assert "\n" not in line


# ═════════════════════════════════════════════════════════════════════════════
# The conftest wiring — captured at start, and not re-grown locally
# ═════════════════════════════════════════════════════════════════════════════

def test_the_conftest_captures_the_start_sha_rather_than_deriving_its_own():
    """
    THE SINGLE-IMPLEMENTATION PROPERTY, one level on from gap 3's. A local `rev-parse` in
    the conftest would look right and drift, exactly as a local `tree_state_line` would.
    """
    source = open( os.path.join( ROOT, "src", "conftest.py" ) ).read()
    assert "capture_start_sha" in source, "the conftest no longer captures a start sha"
    assert not re.search( r"^def capture_start_sha\(", source, re.MULTILINE ), (
        "the conftest defines its own start capture again; there must be exactly one"
    )


def test_the_conftest_passes_the_captured_start_to_the_line():
    """
    Capturing it and then not USING it would leave every run reporting a moment while
    looking like it reports an interval — worse than not capturing at all.
    """
    source = open( os.path.join( ROOT, "src", "conftest.py" ) ).read()
    assert "_TREE_STATE_START_SHA = capture_start_sha(" in source
    # NOT `[^)]*` — the call nests `_git_reader( ... )`, so a no-close-paren match stops
    # short and the assertion passes on a source that never threads the value through.
    assert re.search( r"tree_state_line\(.*_TREE_STATE_START_SHA", source ), (
        "the captured start sha never reaches tree_state_line"
    )


def test_a_real_pytest_run_emits_the_span_on_its_tree_state_line():
    """
    END-TO-END, in a REAL pytest process. Everything above injects a git or reads source;
    this drives an actual run and reads the line it printed.

    ⚠️ IT IS A SUBPROCESS ON PURPOSE, and the first draft got this wrong: importing the root
    conftest by name from inside the suite resolves to `src/tests/unit/conftest.py`, the
    NEAREST one — so the test would have measured the wrong module and said so as an
    ImportError. Reading the emitted line is also the stronger claim: it checks what a human
    actually sees, not what a module holds.
    """
    done = subprocess.run(
        [ sys.executable, "-m", "pytest", "--collect-only", "-q",
          os.path.join( ROOT, "src", "tests", "unit", "test_tree_state_run_span.py" ) ],
        cwd=ROOT, capture_output=True, text=True, timeout=300,
        env={ **os.environ, "PYTHONPATH": os.path.join( ROOT, "src" ),
              "COVERAGE_FILE": os.environ.get( "COVERAGE_FILE", "/tmp/cov-tree-state-span-probe.data" ) } )
    tree_lines = [ l for l in done.stdout.splitlines() if l.startswith( "[tree-state]" ) ]
    assert len( tree_lines ) == 1, f"expected one tree-state line, got {tree_lines!r}"
    assert "run-span=" in tree_lines[ 0 ], (
        f"a real pytest run reported a MOMENT, not an interval: {tree_lines[ 0 ]!r}"
    )
