"""
Gap 2 of row 11253df9 — the `[tree-state]` line names WHICH files are dirty.

The incident this closes: `src/conf/epic-stories.json` carried 24 uncommitted lines
through TWO unit tiers, `tracked-dirty=1` printed on both runs, and nobody read it
(CLAUDE.md:755-756). An unnamed count is the easiest thing in a log to wave at.

Design: src/rnd/v0.2.1/2026.09.03-tree-state-gap-2-name-the-dirty-paths.md
"""
import importlib.util
import os
import re
from pathlib import Path

ROOT          = Path( os.environ.get( "LUPIN_ROOT", "/var/lupin" ) )
MODULE_PATH   = ROOT / "src" / "cosa" / "utils" / "tree_state.py"

_spec = importlib.util.spec_from_file_location( "tree_state_gap2", MODULE_PATH )
ts    = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( ts )

_dirty_paths    = ts._dirty_paths
tree_state_line = ts.tree_state_line
DIRTY_PATH_CAP  = ts.DIRTY_PATH_CAP


def git_for( mapping ):
    calls = []
    def git( *args ):
        calls.append( args )
        for prefix, value in mapping.items():
            if args[ :len( prefix ) ] == prefix: return value
        return None
    git.calls = calls
    return git


HEALTHY = {
    ( "rev-parse", "--short", "HEAD" )             : "abc1234",
    ( "rev-parse", "--show-toplevel" )             : "/repos/lupin",
    ( "rev-parse", "--abbrev-ref", "HEAD" )        : "wip-branch",
    ( "rev-parse", "--path-format=absolute", "--git-common-dir" ) : "/repos/lupin/.git",
    ( "rev-parse", "--abbrev-ref", "@{upstream}" ) : "origin/wip-branch",
    ( "status", "--porcelain" )                    : " M src/a.py\n?? scratch.txt\n",
    ( "rev-list", "--count", "HEAD..origin/wip-branch" ) : "0",
    ( "rev-list", "--count", "origin/wip-branch..HEAD" ) : "3",
}


def _field( line ):
    """Read the field the way the docstring tells a reader to: to end-of-field."""
    m = re.search( r"dirty-paths=([^ ]*)", line )
    return m.group( 1 ) if m else None


# ── the always-print rule ────────────────────────────────────────────────────

def test_a_clean_tree_still_prints_the_field():
    """
    A missing field is indistinguishable from a probe that never ran. This module has
    already ruled on that twice — `_run_span`'s `unmoved`, and `deleted=0`.
    """
    assert _dirty_paths( [] ) == "none"


def test_the_field_is_present_on_a_clean_live_line():
    clean = { **HEALTHY, ( "status", "--porcelain" ) : "?? only-untracked.txt\n" }
    assert _field( tree_state_line( git_for( clean ) ) ) == "none"


# ── the anti-laundering rule ─────────────────────────────────────────────────

def test_a_failed_status_read_says_UNKNOWN_and_never_none():
    """
    "I could not look" and "nothing to report" are different claims. The row already
    carries a test forbidding this collapse on `run-span`; this is the same rule on the
    same line, one field over.
    """
    blind = { k : v for k, v in HEALTHY.items() if k != ( "status", "--porcelain" ) }
    line  = tree_state_line( git_for( blind ) )
    assert _field( line ) == "UNKNOWN"
    assert "dirty-paths=none" not in line


# ── naming, ordering, capping ────────────────────────────────────────────────

def test_two_edits_are_both_named():
    assert _dirty_paths( [ " M a.py", "M  b.py" ] ) == "a.py,b.py"


def test_the_cap_holds_and_declares_the_remainder():
    six = [ f" M f{i}.py" for i in range( 6 ) ]
    assert _dirty_paths( six ) == "f0.py,f1.py,f2.py,f3.py,f4.py,+1-more"
    assert len( _dirty_paths( six ).split( "," ) ) == DIRTY_PATH_CAP + 1


def test_the_container_shape_names_the_real_edit_first():
    """
    🔴 THE CASE THE ORDERING EXISTS FOR. Inside `lupin-rest-test` 125 tracked files read
    ` D` for a bind-mount reason unrelated to anybody's work (pocholo, 2026-09-02), while
    ONE file is genuinely edited. A cap applied in porcelain order spends all five slots
    on phantom deletions and buries the only path a reader needs.
    """
    container = [ " M src/conf/epic-stories.json" ] + [ f" D .claude/f{i}.md" for i in range( 125 ) ]
    value     = _dirty_paths( container )
    assert value.split( "," )[ 0 ] == "src/conf/epic-stories.json"
    assert value.endswith( "+121-more" )


def test_deletions_alone_are_still_named():
    """The ordering must not DROP deletions — only rank them below edits."""
    assert _dirty_paths( [ " D gone.py" ] ) == "gone.py"


def test_a_rename_names_the_destination():
    assert _dirty_paths( [ "R  old.py -> new.py" ] ) == "new.py"


# ── the strip trap, found by a live run and by nothing else ──────────────────

def test_the_first_line_is_read_correctly_even_after_the_reader_strips_it():
    """
    🔴 `_git_reader` returns `stdout.strip()`, which eats the LEADING SPACE OF THE FIRST
    LINE ONLY. So the first row of the commonest case — ` M path`, an unstaged edit —
    arrives one character short, and a fixed `line[ 3: ]` slice silently swallows a
    character of the path. Measured 2026-09-03 on a real tree:
    `dirty-paths=rc/cosa/utils/tree_state.py`.

    ⚠️ EVERY SYNTHETIC FIXTURE PASSED, because a hand-built porcelain line keeps its
    leading space. This arm is the stripped shape, which is what a live run actually
    hands the parser.
    """
    assert _dirty_paths( [ "M src/cosa/utils/tree_state.py" ] ) == "src/cosa/utils/tree_state.py"


def test_both_spellings_of_the_first_line_agree():
    """The negative control for the arm above: stripped and unstripped must not differ."""
    assert ( _dirty_paths( [ "M src/a.py" ] )
             == _dirty_paths( [ " M src/a.py" ] )
             == "src/a.py" )


# ── the cost, which is the reason the design is acceptable ───────────────────

def test_naming_the_paths_costs_no_extra_git_call():
    """
    The paths come from the `status --porcelain` result the line ALREADY reads — before
    this they were counted and thrown away. The row asks for the call count to be pinned
    because it regrows silently; this asserts the field added none.
    """
    git = git_for( HEALTHY )
    tree_state_line( git )
    status_calls = [ c for c in git.calls if c[ :1 ] == ( "status", ) ]
    assert len( status_calls ) == 1, f"status was read {len( status_calls )}x: {git.calls}"
    assert len( git.calls ) == 8, (
        f"the git-call budget moved to {len( git.calls )}; naming the dirty paths must "
        f"cost nothing, because the paths are already in the status output: {git.calls}"
    )


def test_the_worst_case_budget_is_untouched():
    """
    ⚠️ EIGHT ABOVE AND NINE HERE ARE THE SAME PIN READ ON TWO FIXTURES, not a
    disagreement — and I wrote 9 above first, lifted from `test_tree_state_reporting.py`
    without checking that its fixture is a different one. The canonical pin measures the
    WORST case: no upstream, which is also the detached-worktree path, and which spends
    one extra call on `worktree list`. A tree WITH an upstream never makes that call.

    Both are asserted because a single number would have been a fact about one fixture
    quoted as a fact about the module.
    """
    no_upstream = { k : v for k, v in HEALTHY.items()
                    if k != ( "rev-parse", "--abbrev-ref", "@{upstream}" ) }
    no_upstream[ ( "rev-parse", "--abbrev-ref", "HEAD" ) ]  = "HEAD"
    no_upstream[ ( "worktree", "list", "--porcelain" ) ]    = "worktree /r\nHEAD f\nbranch refs/heads/m\n"
    no_upstream[ ( "rev-list", "--count", "HEAD..m" ) ]     = "5"
    no_upstream[ ( "rev-list", "--count", "m..HEAD" ) ]     = "0"

    git = git_for( no_upstream )
    line = tree_state_line( git )
    assert len( git.calls ) == 9, f"worst-case budget moved to {len( git.calls )}: {git.calls}"
    assert "dirty-paths=" in line, "the field must appear on the no-upstream branch too"


def test_a_line_that_does_not_match_the_porcelain_shape_is_not_dropped():
    """
    ⚠️ COVERAGE REPORTED THIS BRANCH AS COVERED WHEN NOTHING EXERCISED IT. The fallback
    lives in a ternary (`m.group( 1 ) if m else line.strip()`), which coverage counts as
    ONE statement — so `--cov-branch` said 100% with the else-arm never once taken. This
    is § COVERAGE MEASURES WHETHER A LINE RAN, NEVER WHETHER THE TEST COULD HAVE NOTICED
    IT RUNNING WRONG, in the smallest possible form.

    The arm itself is defensive: real git always emits `XY<space>PATH` for a tracked
    entry. It is guarded rather than deleted because a silent drop would be the worst
    outcome — a dirty file the line does not name is the exact defect this field closes.
    """
    assert _dirty_paths( [ "weird-no-space" ] ) == "weird-no-space"
