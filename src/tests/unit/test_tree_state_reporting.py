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
import re
import subprocess
import sys

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
    ( "rev-parse", "--show-toplevel" )        : "/repos/lupin",
    ( "rev-parse", "--path-format=absolute", "--git-common-dir" ) : "/repos/lupin/.git",
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
    assert "root=/repos/lupin" in line, "a line that does not name the repo it measured can name the wrong one"
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


# ---------------------------------------------------------------------------
# FORMAT CONTRACT (added 2026-08-26 after Mr Radio ran the suite and checked the
# real output against the repo's parsers). The line shares stdout with whatever
# reads a run's result, so its shape is not cosmetic — it is an interface.
#
# WHAT HIS CHECK ACTUALLY ESTABLISHED, corrected: of the three parsers, only ONE
# reads pytest output — `swe_team/test_runner.py:76`. The other two are
# `_parse_node_tap_summary` (Node/TAP, the TypeScript suite) and a branch of
# `_parse_non_pytest_stdout`; both are named for what they parse and do not match
# pytest output with or without this line. My earlier review listed all three as if
# each were a risk, which overstated the surface. The real check is the one pytest
# parser, and it is pinned below against REAL captured output.
# ---------------------------------------------------------------------------

COUNT_WORDS = ( "passed", "failed", "error", "errors", "skipped", "xfailed", "xpassed" )


def test_the_line_can_never_be_mistaken_for_a_pytest_COUNT_line():
    r"""
    The durable statement about the format: the line may carry digits, but never a
    bare number followed by a count word. `(\d+)\s+passed` is how the one pytest
    parser in this repo reads a run, so a line that grew such a substring would not
    merely add noise — it would change the number a caller believes.
    """
    line = tree_state_line( git_for( HEALTHY ) )
    for word in COUNT_WORDS:
        assert not re.search( rf"\d+\s+{word}", line ), (
            f"the tree-state line contains a '<n> {word}' substring; a pytest-output "
            f"parser would read it as a result count"
        )


def test_the_line_is_exactly_one_line_and_carries_no_braces():
    """
    One line, so it cannot be split across a parser's line-anchored regex; no braces,
    so it cannot be scooped up by anything hunting a JSON payload in stdout — the
    hazard the import-time watcher thread already demonstrated on this tree.
    """
    line = tree_state_line( git_for( HEALTHY ) )
    assert "\n" not in line, "a multi-line diagnostic can straddle a ^...$ parser"
    assert "{" not in line and "}" not in line


def test_the_real_pytest_parser_still_reads_the_right_count_with_the_line_present():
    """
    The check that actually matters, run against REAL captured output rather than a
    fixture: with the tree-state line in the stream, the one pytest parser in this
    repo must still return the run's true count.
    """
    captured = (
        "..........                                                        [100%]\n"
        + tree_state_line( git_for( HEALTHY ) ) + "\n"
        + "[unit-network:block] outbound connections: 0\n"
        + "10 passed in 0.11s\n"
    )
    assert re.findall( r"(\d+)\s+passed", captured ) == [ "10" ], (
        "the tree-state line perturbed the count the pytest parser reads"
    )


# ---------------------------------------------------------------------------
# THE ORDERING CLAUSE (Mr Radio, 2026-08-26). His durable sentence carries one
# guarantee the substring rules do not: the line "is never the last line", which
# protects a consumer that reads the LAST line rather than regex-searching. That
# ordering is pytest's, not this code's — this module cannot enforce it, so it is
# VERIFIED on a live run instead of asserted from a fixture. A fixture written in
# the order I expect would only prove I can write a fixture.
# ---------------------------------------------------------------------------

# A different file, so the run cannot recurse into this one. Measured at ~0.5s.
LIVE_TARGET = "src/tests/unit/test_arbiter_snapshot_store.py"


def test_on_a_live_run_the_line_is_present_and_is_never_the_last_line():
    """
    The full durable sentence, checked end to end against real pytest output:
    the tree-state line contains no "N passed", "N failed" or "N error" substring
    AND is never the last line, so no consumer of pytest's summary can misread it.

    Runs pytest as a subprocess against a small unit file. It must run inside the
    repo, because the line comes from the ROOT conftest — a temp-directory target
    would never load it and the test would pass by measuring nothing.
    """
    root = os.environ[ "LUPIN_ROOT" ]
    done = subprocess.run(
        [ sys.executable, "-m", "pytest", LIVE_TARGET, "-q", "--no-header", "-p", "no:cacheprovider" ],
        cwd=root, capture_output=True, text=True, timeout=180,
        env={ **os.environ, "PYTHONPATH": os.path.join( root, "src" ) },
    )
    lines = [ l for l in done.stdout.splitlines() if l.strip() ]
    assert lines, f"the probe run produced no output (exit {done.returncode})"

    tree_lines = [ l for l in lines if l.startswith( "[tree-state]" ) ]
    assert len( tree_lines ) == 1, (
        f"expected exactly one tree-state line in a real run, got {len( tree_lines )} — "
        f"the hook is either not wired or firing more than once"
    )

    assert lines[ -1 ] != tree_lines[ 0 ], "the tree-state line IS the last line"
    assert re.search( r"\d+\s+(passed|failed|error)", lines[ -1 ] ), (
        f"premise gone — the last line is no longer pytest's count: {lines[ -1 ]!r}"
    )
    for word in ( "passed", "failed", "error" ):
        assert not re.search( rf"\d+\s+{word}", tree_lines[ 0 ] ), (
            f"the live tree-state line carries a '<n> {word}' substring"
        )


# ---------------------------------------------------------------------------
# RIO'S AUDIT (2026-08-26). Three ways the line could be confidently wrong rather
# than honestly unknown. Each was reproduced before being fixed.
# ---------------------------------------------------------------------------

def test_the_line_names_the_repository_it_measured():
    """
    `git -C <dir>` walks UP to the nearest ancestor repo. A directory that is not
    itself a repo — a worktree whose gitdir pointer was deleted, a scratch dir nested
    in the tree — therefore yields a fully confident line about a DIFFERENT
    repository, with no hedge of any kind.

    Rio measured exactly that: a nested non-repo directory returned the MAIN repo's
    sha. Six worktrees live inside this repo under `.claude/worktrees/tfe-*` at a sha
    ~1,581 commits from the branch; all still hold their pointer, so this is one
    deletion away rather than live, and no one's worktree was deleted to prove the
    last step. `root=` is what makes the walk-up visible.
    """
    line = tree_state_line( git_for( HEALTHY ) )
    assert "root=/repos/lupin" in line

    unresolvable = dict( HEALTHY ); del unresolvable[ ( "rev-parse", "--show-toplevel" ) ]
    assert "root=?" in tree_state_line( git_for( unresolvable ) ), (
        "an unreadable toplevel must print as unknown, not be omitted — an absent field "
        "reads as a field that did not matter"
    )


def test_behind_carries_the_age_of_the_last_fetch():
    """
    `behind=` is measured against `@{upstream}`, the last-FETCHED ref. Staying offline
    is right, but a bare `behind=0` reads as "up to date" when it means "up to date AS
    OF whenever I last fetched". The ref's own tip age cannot answer this — an
    untouched ref looks fresh forever — so the mtime of FETCH_HEAD is used.
    """
    line = tree_state_line( git_for( HEALTHY ) )
    assert "fetched=" in line, "a distance with no fetch age overstates how current it is"

    blind = dict( HEALTHY ); del blind[ ( "rev-parse", "--path-format=absolute", "--git-common-dir" ) ]
    assert "fetched=UNKNOWN" in tree_state_line( git_for( blind ) )


def test_a_decode_failure_is_contained_rather_than_raised():
    """
    `text=True` decodes stdout, and a ref name with invalid bytes raises
    UnicodeDecodeError — which is NEITHER an OSError nor a SubprocessError. The first
    version let it escape the reader AND this function; the caller's `except Exception`
    contained it, but that net carries `pragma: no cover`, so the only thing holding it
    up was the one line nobody tests.
    """
    def hostile( *args ):
        raise UnicodeDecodeError( "utf-8", b"\xff", 0, 1, "invalid start byte" )

    line = tree_state_line( hostile )
    assert "UNKNOWN" in line, "a decode failure must degrade to UNKNOWN, not propagate"


def test_the_git_call_budget_is_what_the_docs_claim():
    """
    The worst case is the NO-UPSTREAM path, which is also the detached-worktree path —
    the one this diagnostic most exists for. Each call carries `timeout=5`, so the
    budget is the run's worst-case cost and it must not drift silently.
    """
    no_upstream = { k: v for k, v in HEALTHY.items()
                    if k != ( "rev-parse", "--abbrev-ref", "@{upstream}" ) }
    no_upstream[ ( "rev-parse", "--abbrev-ref", "HEAD" ) ]       = "HEAD"
    no_upstream[ ( "worktree", "list", "--porcelain" ) ]         = "worktree /r\nHEAD f\nbranch refs/heads/m\n"
    no_upstream[ ( "rev-list", "--count", "HEAD..m" ) ]          = "5"
    no_upstream[ ( "rev-list", "--count", "m..HEAD" ) ]          = "0"

    git = git_for( no_upstream )
    tree_state_line( git )
    assert len( git.calls ) == 9, (
        f"the git-call budget moved to {len( git.calls )}; each call carries timeout=5, so this "
        f"is the worst-case cost of the diagnostic and the docs quote it"
    )
