"""
Guard — every pytest run states the TREE it was earned on (row e2099400).

A pass is a statement about a tree, not about a repository. On a tree several people
commit to, "the suite is green" decays the moment somebody else lands a commit, and
nothing in the output says which tree earned it. The same defect one layer over: a
coverage data file read seventy minutes apart reported 99% and then 38% for ONE file,
because a report is rendered against the source on disk NOW rather than the source
that was MEASURED.

These tests drive `tree_state_line` through an INJECTED git rather than a real
repository, so the hostile cases — no upstream, a detached worktree, a git that
returns nothing — are exercised rather than hoped about. The live wiring is asserted
separately at the bottom.

Venue: :7999-eligible — no subprocess, no network, no mutation.
"""
import importlib.util
import os

import pytest

# `import conftest` resolves to the NEAREST conftest, which is this directory's — not
# the root one under test. Load the root file by PATH so the import cannot silently
# bind to a different module than the one the assertions are about.
ROOT_CONFTEST = os.path.join( os.environ[ "LUPIN_ROOT" ], "src", "conftest.py" )
_spec         = importlib.util.spec_from_file_location( "lupin_root_conftest", ROOT_CONFTEST )
root_conftest = importlib.util.module_from_spec( _spec )
_spec.loader.exec_module( root_conftest )

_git_reader     = root_conftest._git_reader
_primary_branch = root_conftest._primary_branch
tree_state_line = root_conftest.tree_state_line


def git_for( mapping ):
    """Build a git whose answers come from an {args-prefix-tuple: stdout} mapping."""
    calls = []

    def git( *args ):
        calls.append( args )
        for prefix, value in mapping.items():
            if args[ :len( prefix ) ] == prefix: return value
        return None

    git.calls = calls
    return git


HEALTHY = {
    ( "rev-parse", "--short", "HEAD" )        : "abc1234",
    ( "rev-parse", "--abbrev-ref", "HEAD" )   : "wip-branch",
    ( "rev-parse", "--abbrev-ref", "@{upstream}" ) : "origin/wip-branch",
    ( "status", "--porcelain" )               : " M src/a.py\n?? scratch.txt\n",
    ( "rev-list", "--count", "HEAD..origin/wip-branch" ) : "12",
    ( "rev-list", "--count", "origin/wip-branch..HEAD" ) : "3",
}


def test_a_healthy_tree_states_sha_distance_ref_and_dirt():
    """The whole point in one line: which tree, how far back, and was it clean."""
    line = tree_state_line( git_for( HEALTHY ) )
    assert "sha=abc1234" in line
    assert "branch=wip-branch" in line
    assert "behind=12" in line
    assert "ahead=3" in line
    assert "vs origin/wip-branch" in line, "a distance with no ref named is not a measurement"
    assert "tracked-dirty=1" in line, "untracked scratch must not be counted as tracked dirt"


def test_the_line_is_never_empty_even_when_git_answers_nothing():
    """
    An instrument that goes quiet when it cannot answer is indistinguishable from one
    that was never armed — and silence reads as "not behind".
    """
    line = tree_state_line( git_for( {} ) )
    assert line, "a silent tree-state is worse than an honest UNKNOWN"
    assert "UNKNOWN" in line
    assert "cannot be tied to a tree" in line


def test_a_detached_worktree_says_detached_and_still_gets_a_comparison():
    """
    A detached worktree has NO upstream, and it is exactly the tree most likely to be
    far behind — so falling back to "no comparison" there would leave the case this
    exists for as the one case it cannot answer. It falls back to the primary
    worktree's branch.
    """
    mapping = {
        ( "rev-parse", "--short", "HEAD" )      : "dead123",
        ( "rev-parse", "--abbrev-ref", "HEAD" ) : "HEAD",
        ( "worktree", "list", "--porcelain" )   : (
            "worktree /repo\nHEAD ffff\nbranch refs/heads/main-line\n\n"
            "worktree /repo/wt\nHEAD dead123\ndetached\n"
        ),
        ( "status", "--porcelain" )             : "",
        ( "rev-list", "--count", "HEAD..main-line" ) : "1578",
        ( "rev-list", "--count", "main-line..HEAD" ) : "0",
    }
    line = tree_state_line( git_for( mapping ) )
    assert "branch=detached" in line, "'HEAD' is not a branch name a reader can use"
    assert "behind=1578" in line
    assert "vs main-line" in line
    assert "tracked-dirty=0" in line


def test_no_upstream_and_no_primary_branch_says_so_instead_of_guessing():
    """A missing comparison must be stated, never silently rendered as behind=0."""
    mapping = {
        ( "rev-parse", "--short", "HEAD" )      : "abc1234",
        ( "rev-parse", "--abbrev-ref", "HEAD" ) : "HEAD",
        ( "status", "--porcelain" )             : "",
    }
    line = tree_state_line( git_for( mapping ) )
    assert "behind=UNKNOWN" in line
    assert "no upstream" in line
    assert "behind=0" not in line, "an unknown distance rendered as zero is a false green"


def test_a_ref_that_cannot_be_walked_reports_unknown_and_names_the_ref():
    """
    The ref resolved but rev-list failed — a shallow clone, a pruned remote ref. The
    reader must learn the distance is unknown AND which ref failed.
    """
    mapping = dict( HEALTHY )
    del mapping[ ( "rev-list", "--count", "HEAD..origin/wip-branch" ) ]
    line = tree_state_line( git_for( mapping ) )
    assert "behind=UNKNOWN" in line
    assert "origin/wip-branch" in line, "the failing ref must be named"


def test_unreadable_dirt_is_reported_as_unknown_not_as_clean():
    """`dirty=?` and `tracked-dirty=0` are different claims; collapsing them lies."""
    mapping = dict( HEALTHY )
    del mapping[ ( "status", "--porcelain" ) ]
    line = tree_state_line( git_for( mapping ) )
    assert "dirty=?" in line
    assert "tracked-dirty=0" not in line


def test_the_probe_never_reaches_the_network():
    """
    `@{upstream}` reads the LAST-FETCHED ref, so this stays offline. A probe that
    fetched would add network time to every run and could hang a suite on a remote.
    """
    git = git_for( HEALTHY )
    tree_state_line( git )
    forbidden = { "fetch", "pull", "ls-remote", "remote", "clone" }
    assert not [ c for c in git.calls if c and c[ 0 ] in forbidden ], (
        f"the tree-state probe issued a network git command: {git.calls}"
    )


def test_primary_branch_ignores_detached_worktrees_and_takes_the_first_branch():
    """The fallback must not return a detached worktree's absent branch."""
    listing = ( "worktree /repo/wt\nHEAD aaaa\ndetached\n\n"
                "worktree /repo\nHEAD bbbb\nbranch refs/heads/the-line\n" )
    assert _primary_branch( git_for( { ( "worktree", "list", "--porcelain" ) : listing } ) ) == "the-line"
    assert _primary_branch( git_for( {} ) ) is None


def test_the_real_reader_returns_none_instead_of_raising_on_a_bad_repo( tmp_path ):
    """
    The production reader is the one thing here that touches a subprocess. It must
    degrade to None rather than raise — a diagnostic may never fail a suite.
    """
    read = _git_reader( str( tmp_path ) )                # not a git repository
    assert read( "rev-parse", "--short", "HEAD" ) is None


def test_the_live_hook_prints_the_line_before_any_early_return():
    """
    WIRING, asserted on the source rather than assumed. The network guard's summary
    returns early when its mode is off — which is the DEFAULT — so a tree-state line
    placed after that return would never print on an ordinary run.
    """
    source = open( ROOT_CONFTEST ).read()
    body   = source[ source.index( "def pytest_terminal_summary(" ) : ]
    call   = body.index( "tree_state_line(" )
    early  = body.index( '_NETWORK_MODE not in ( "count", "block" )' )
    assert call < early, (
        "tree_state_line is called after the network guard's early return — on a default "
        "run the mode is off, so the line would never print"
    )
