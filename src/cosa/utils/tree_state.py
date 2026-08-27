"""
The canonical `[tree-state]` line — ONE implementation, every caller.

A pass is a statement about a TREE, not about a repository. This module renders the line
that says which tree; see `src/rnd/v0.2.0/2026.08.26-every-green-states-its-tree.md`, and
§6b for why it lives here rather than in `src/conftest.py`.

WHY A MODULE AND NOT A SHELL FUNCTION. The root conftest reaches every pytest tier and
nothing else, so the node/c8 runners produced greens carrying no tree at all. The shortcut
is a shell function re-deriving the line with its own `git` calls — two implementations of
one contract, which drift. This is the single implementation both callers use:
`src/conftest.py` imports it, and `src/scripts/lib/tree-state.sh` runs
`python3 -m cosa.utils.tree_state`.

`_coarse_age` lives here too because it has THREE call sites, not one (Rio ⚡, 2026-08-26):
the fetch age, the coverage-file age, and this module. Leaving it behind would have split a
shared helper away from two of its callers.

Kept deliberately dependency-free — standard library only. conftest imports it early, and
already imports `cosa.utils.secret_redaction`, so the precedent and the cost are both known.

Venue: :7999-eligible — read-only git, no network, no mutation.
"""
import os
import subprocess
import time


def _git_reader( repo_root ):
    """
    A callable running one read-only git command, returning stdout or None.

    Ensures:
        - returns None for ANY failure, including a decode failure. `text=True`
          decodes stdout, and a ref name carrying invalid bytes raises
          UnicodeDecodeError — which is neither an OSError nor a SubprocessError, so
          the first version of this let it escape the reader AND `tree_state_line`
          (Rio's audit, 2026-08-26, measured with an injected reader). The caller's
          `except Exception` did contain it, but that net carries `pragma: no cover`,
          so the only thing holding it up was the one line nobody tests.
    """
    def read( *args ):
        try:
            done = subprocess.run( [ "git", "-C", repo_root, *args ],
                                   capture_output=True, text=True, timeout=5 )
        except ( OSError, subprocess.SubprocessError, UnicodeDecodeError, ValueError ):
            return None
        try:
            return done.stdout.strip() if done.returncode == 0 else None
        except UnicodeDecodeError:                       # a lazily-decoded stream
            return None
    return read


def _coarse_age( seconds ):
    """
    A duration as one coarse token — minutes, then hours, then days.

    Shared by `_fetch_age` and the coverage-file disclosure so the two ages read the
    same way. A reader comparing "fetched=2d-ago" against a coverage file's age should
    not have to work out whether the two units mean the same thing.
    """
    if seconds < 3600:    return f"{int( seconds // 60 )}m"
    if seconds < 86400:   return f"{int( seconds // 3600 )}h"
    return f"{int( seconds // 86400 )}d"


def _fetch_age( git ):
    """
    How long ago this repo last FETCHED, as a coarse string, or None.

    `behind=` is computed against `@{upstream}` — the last-FETCHED ref — so a bare
    `behind=0` reads as "up to date" when it means "up to date AS OF whenever I last
    fetched" (Rio's audit). The ref's own tip age does not answer this: an untouched
    ref looks fresh forever. FETCH_HEAD's mtime is the moment a fetch actually ran.
    """
    # `--git-path` returns a path relative to the git process's CWD, which is the
    # reader's directory and NOT this process's — resolving it here reported a real
    # two-day-old FETCH_HEAD as UNKNOWN, i.e. hid the exact staleness it exists to
    # show. `--path-format=absolute --git-common-dir` is unambiguous, and COMMON is
    # the right one: a linked worktree's own gitdir has no FETCH_HEAD, the shared one
    # does.
    common = git( "rev-parse", "--path-format=absolute", "--git-common-dir" )
    if not common: return None
    path = os.path.join( common, "FETCH_HEAD" )
    try:
        seconds = time.time() - os.path.getmtime( path )
    except OSError:
        return None
    return _coarse_age( seconds )


def tree_state_line( git ):
    """
    One line naming the tree a run was earned on.

    Requires:
        - git is a callable taking git arguments and returning stdout, or None on
          any failure. Injected so this is testable without a repository, and so a
          hostile git can be exercised rather than hoped about.

    Ensures:
        - returns a single line, always: an UNKNOWN line when the sha cannot be read,
          never "" and never None. A silent instrument reads as "nothing to report"
        - NAMES THE REPOSITORY IT MEASURED (`root=`). `git -C <dir>` walks UP to the
          nearest ancestor repo, so a directory that is not itself a repo — a worktree
          whose gitdir pointer was deleted, a scratch dir nested in the tree — yields
          a fully confident line about a DIFFERENT repository, with no hedge at all
          (Rio's audit, 2026-08-26: a nested non-repo dir returned the main repo's sha).
          Printing the resolved toplevel makes a walk-up visible instead of silent
        - STAMPS FETCH AGE beside the distance, because `@{upstream}` is the last
          FETCHED ref: a bare `behind=0` reads as "up to date" when it means "up to
          date as of whenever I last fetched"
        - names the comparison ref it used, because "behind 88" means nothing without
          it, and the ref differs between a tracking branch and a detached worktree
        - reports dirty separately from behind: a clean tree 88 commits back and a
          dirty tree at the tip are different claims, and both invalidate a quoted
          figure in different ways
        - performs NO network access: `@{upstream}` reads the last-fetched ref, so a
          run stays offline and cannot hang on a remote

    THE LINE IS NEVER THE LAST LINE — BY MECHANISM, NOT BY OBSERVATION (Mr Radio,
    2026-08-26). In `_pytest.terminal`, `TerminalReporter.pytest_sessionfinish` is a
    hookimpl WRAPPER: it `yield`s, then calls `config.hook.pytest_terminal_summary(...)`
    — every plugin's line, including this one — and only afterwards calls
    `self.summary_stats()`, which writes the counts line. So the counts line follows
    every terminal-summary hook by construction, and this line cannot be last on any
    run shape without someone changing pytest. After a pytest upgrade, check that one
    function rather than re-running a fixture and hoping the sample covered your case.

    Raises:
        - nothing that this module can produce. Every git call goes through a reader
          that returns None on OSError, SubprocessError, UnicodeDecodeError and
          ValueError. The earlier "Raises: nothing" was WRONG — a UnicodeDecodeError
          escaped both the reader and this function until Rio measured it.
    """
    try:
        return _tree_state_line( git )
    except Exception:
        # TOTAL BY CONSTRUCTION, not by the caller's net. The caller does wrap this,
        # but that wrapper carries `pragma: no cover` — so before this, the only thing
        # standing between a decode failure and a propagating exception was the one
        # line nobody tests (Rio's audit). Now the guarantee lives where the docstring
        # makes it, and a test drives it with a git that raises.
        return "[tree-state] UNKNOWN — the tree-state probe failed; this run's result cannot be tied to a tree"


def _tree_state_line( git ):
    """The body of `tree_state_line`; see it for the contract."""
    sha = git( "rev-parse", "--short", "HEAD" )
    if not sha:
        return "[tree-state] UNKNOWN — cannot read HEAD; this run's result cannot be tied to a tree"

    branch = git( "rev-parse", "--abbrev-ref", "HEAD" ) or "?"
    if branch == "HEAD": branch = "detached"
    root = git( "rev-parse", "--show-toplevel" ) or "?"

    ref = git( "rev-parse", "--abbrev-ref", "@{upstream}" ) or _primary_branch( git )
    dirty = git( "status", "--porcelain" )
    tracked_dirty = (
        len( [ l for l in dirty.splitlines() if l and not l.startswith( "??" ) ] )
        if dirty is not None else None
    )
    dirty_txt = "dirty=?" if tracked_dirty is None else f"tracked-dirty={tracked_dirty}"

    if not ref:
        return ( f"[tree-state] sha={sha} root={root} branch={branch} {dirty_txt} "
                 f"behind=UNKNOWN — no upstream and no primary branch to compare against" )

    behind = git( "rev-list", "--count", f"HEAD..{ref}" )
    ahead  = git( "rev-list", "--count", f"{ref}..HEAD" )
    if behind is None or ahead is None:
        return ( f"[tree-state] sha={sha} root={root} branch={branch} {dirty_txt} "
                 f"behind=UNKNOWN vs {ref} — the comparison ref could not be walked" )

    fetched = _fetch_age( git )
    fetch_txt = f"fetched={fetched}-ago" if fetched else "fetched=UNKNOWN"
    return ( f"[tree-state] sha={sha} root={root} branch={branch} behind={behind} "
             f"ahead={ahead} vs {ref} {fetch_txt} {dirty_txt}" )


def _primary_branch( git ):
    """
    The branch checked out in the FIRST worktree, used when there is no upstream.

    A detached worktree has no upstream at all, and it is exactly the tree most
    likely to be far behind — so falling back to "no comparison" there would leave
    the case this exists for as the one case it cannot answer.
    """
    listing = git( "worktree", "list", "--porcelain" )
    if not listing: return None
    for line in listing.splitlines():
        if line.startswith( "branch " ):
            return line.split( " ", 1 )[ 1 ].strip().replace( "refs/heads/", "" )
    return None


def main():
    """
    Print the line, for callers that are not Python — the node/c8 runners.

    Ensures:
        - always prints exactly one line and always exits 0. A diagnostic that can fail a
          runner is worse than no diagnostic: a runner that dies while reporting which tree
          it ran on has destroyed the result it was describing.
    """
    here = os.path.dirname( os.path.abspath( __file__ ) )
    try:
        print( tree_state_line( _git_reader( here ) ) )
    except Exception:                                    # pragma: no cover - see Ensures
        print( "[tree-state] UNKNOWN — the tree-state probe failed; this run's result cannot be tied to a tree" )
    return 0


if __name__ == "__main__":                               # pragma: no cover - module entry point
    raise SystemExit( main() )
