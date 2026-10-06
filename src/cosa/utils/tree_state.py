"""
The canonical `[tree-state]` line: one implementation, used by every caller.

A pass is a statement about a tree, not about a repository. This module renders the line
that says which tree.

Why a module and not a shell function: the root conftest reaches every pytest tier and
nothing else. The node and c8 runners therefore produced results with no tree at all.
A shell function would re-derive the line with its own `git` calls. That is two
implementations of one contract, and they drift. Both callers use this one:
`src/conftest.py` imports it, and `src/scripts/lib/tree-state.sh` runs
`python3 -m cosa.utils.tree_state`.

`_coarse_age` lives here too because it has three call sites: the fetch age, the
coverage-file age, and this module. Leaving it behind would split a shared helper away
from two of its callers.

Standard library only, so the module stays dependency-free. conftest imports it early,
and already imports `cosa.utils.secret_redaction`.

Venue: :7999-eligible. Read-only git, no network, no mutation.
"""
import hashlib
import os
import re
import subprocess
import time


def _git_reader( repo_root ):
    """
    A callable running one read-only git command, returning stdout or None.

    Ensures:
        - returns None for any failure, including a decode failure. `text=True` decodes
          stdout, and a ref name carrying invalid bytes raises UnicodeDecodeError, which is
          neither an OSError nor a SubprocessError. The reader catches it so it cannot
          escape the reader or `tree_state_line`.
        - crosses filesystem boundaries while discovering the repository, because in the
          `:8000` test container it must. Without it every end-to-end log read
          `UNKNOWN - cannot read HEAD`, so no result could be tied to a sha at all. The cause is
          not git and not the repo: `docker-compose.yml` bind-mounts `/var/lupin/src` and
          `/var/lupin/.git` as separate mounts, and both callers hand this reader a path under
          `src/`. Discovery walks up, reaches the `/var/lupin/src` mount root, and stops one
          directory short of the `.git`: "not a git repository (or any parent up to mount point
          /var/lupin)", with `GIT_DISCOVERY_ACROSS_FILESYSTEM` not set. Measured in the test
          container: bare -> exit 128, with the flag -> the sha, `--show-toplevel` -> `/var/lupin`.
        - does not weaken the walk-up hedge the module already carries. Crossing a mount can
          in principle land on some other repository, which is why the line carries `root=`.
          The reader stays permissive and the line stays honest: whatever it finds, it names.
    """
    # Inherit the caller's environment so a hostile or unusual git config is still the
    # one the run actually used; add the one variable, rather than building an env from
    # scratch and silently changing what git reads.
    env = { **os.environ, "GIT_DISCOVERY_ACROSS_FILESYSTEM" : "1" }

    def read( *args ):
        try:
            done = subprocess.run( [ "git", "-C", repo_root, *args ],
                                   capture_output=True, text=True, timeout=5, env=env )
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
    How long ago this repo last fetched, as a coarse string, or None.

    `behind=` is computed against `@{upstream}`, the last-fetched ref. A bare `behind=0`
    therefore means "up to date as of the last fetch", not "up to date". The ref's own tip
    age does not answer this, because an untouched ref looks fresh forever. The mtime of
    FETCH_HEAD is the moment a fetch actually ran.
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


START_SHA_UNKNOWN = "UNKNOWN"

# Row 105ff244. src/lupin_app/static/dist/ is GITIGNORED (0 tracked files), so every HEAD
# comparison in this module is blind to a bundle rebuild inside a run: measured 2026-09-28,
# dist/multiplexer/{accordion-harness,parity-harness,boot.19ea80639a1e}.js were rewritten at
# 18:34:51 inside ts-e09fb548's e2e_b window and two results became unfalsifiable.
BUNDLE_REL     = os.path.join( "src", "lupin_app", "static", "dist" )
BUNDLE_NONE    = "none"
BUNDLE_UNKNOWN = "UNKNOWN"
BUNDLE_SERVED_SUFFIXES = ( ".js", ".json" )


def capture_start_sha( git ):
    """
    The sha a run is about to start on, read with a single git call.

    Requires:
        - git is a reader as built by `_git_reader`.

    Ensures:
        - returns a short sha, or `START_SHA_UNKNOWN` when it cannot be read. Never None,
          because None is the caller's way of saying "no start was captured" (the node
          runners), which is a different claim from "I looked and could not read it".
          Collapsing the two would let a failed probe read as a point-in-time report, the
          shape of defect this module exists to catch.

    Why one call and not the whole probe: the gap being closed is that a commit landing
    mid-run goes undetected, which is a sha question. `branch`, `behind`, `ahead`, `fetched`
    and `tracked-dirty` at start answer questions nobody asked, at eight times the cost. One
    call moves the time ceiling from 45 to 50 seconds rather than from 45 to 90.
    """
    return git( "rev-parse", "--short", "HEAD" ) or START_SHA_UNKNOWN


def _run_span( start_sha, end_sha ):
    """
    The `run-span=` suffix, or "" when no start was captured.

    Ensures:
        - "" only when start_sha is None, so a caller that captured no start gets a line
          byte-identical to the one printed before the span existed. The node and c8 runners
          emit before their run, so their line is the start. Asserting `unmoved` there would
          be a claim about a run that has not happened.
        - states `unmoved` rather than saying nothing when the tree held still. A missing
          field would be indistinguishable from a probe that never ran. `unmoved` is a
          measurement; silence is not.
        - does not repeat the sha in the unmoved case, because `sha=` already carries it and
          by definition it equals the start.

    Reading this field: the value is not one character class. Three of the four values are
    lowercase words, and the fourth is `<start>..<end>`, which contains digits. The pattern
    `grep -o 'run-span=[a-z-]*'` truncates that value at its first digit, so the field reads as
    absent. A pattern tuned while the tree is still reports `unmoved` forever and goes blind
    exactly when the tree moves. Match to end-of-field (`run-span=[^ ]*`) or read the whole
    line. This is a note to readers, not a defect here: no emitted value can protect a pattern
    that assumes a narrower alphabet than the field uses.

    Two instruments print `run-span=` and their predicates differ:

        this one (pytest, every tier)   compares HEAD shas only
        run-coverage-gate.sh            hashes HEAD, `git status --porcelain` and `git diff HEAD`

    So here `unmoved` means "no commit landed". It does not mean the working tree held still.
    A file becoming dirty, becoming clean, or an already-dirty file being edited again is
    invisible here, and each moves the gate's fingerprint. If you need "did the working tree
    move", this is not the instrument. Read `tracked-dirty` beside it, and note that a count
    cannot see one file going clean while another goes dirty.
    """
    if start_sha is None:              return ""
    if start_sha == START_SHA_UNKNOWN: return " run-span=UNKNOWN — the start sha could not be read"
    if start_sha == end_sha:           return " run-span=unmoved"
    return f" run-span={start_sha}..{end_sha} ⚠️ TREE MOVED MID-RUN"


def bundle_hash( root ):
    """
    The 12-hex content digest of the served bundle under <root>/src/lupin_app/static/dist/.

    `dist/` is gitignored, so every HEAD comparison in this module is blind to a bundle
    rebuild inside a run. This digest is what sees it.

    Requires:
        - root is a directory path (the tree whose served bundle is being named)

    Ensures:
        - hashes file content, never mtime: the same bytes rewritten is "unmoved", and new
          bytes under an old mtime is "moved". The digest covers (relative path, content
          sha256) in sorted order, so a new boot.<hash>.js appearing or a harness changing
          both move it
        - the served set is .js plus the three manifest.json files (nav, console,
          multiplexer). The manifest is the pointer naming which boot.<hash>.js a page loads, so a rebuild moves it even when an old boot file is still on disk, and nothing else is served. .map files are
          never requested by the page and are left out
        - returns BUNDLE_NONE when there is no dist/ directory (a worktree that never built)
          and BUNDLE_UNKNOWN when it cannot be read, including a file vanishing mid-walk.
          Never None, for the reason `capture_start_sha` gives
    """
    dist = os.path.join( root, BUNDLE_REL )
    if not os.path.isdir( dist ): return BUNDLE_NONE
    digest = hashlib.sha256()
    try:
        for dirpath, dirs, files in os.walk( dist ):
            dirs.sort()
            for name in sorted( files ):
                if not name.endswith( BUNDLE_SERVED_SUFFIXES ): continue
                full = os.path.join( dirpath, name )
                with open( full, "rb" ) as handle:
                    content = hashlib.sha256( handle.read() ).hexdigest()
                digest.update( f"{os.path.relpath( full, dist )}\0{content}\n".encode() )
    except OSError:
        return BUNDLE_UNKNOWN
    return digest.hexdigest()[ :12 ]


def capture_start_bundle( git ):
    """
    The served-bundle hash a run is about to start on, for `tree_state_line( start_bundle= )`.

    Ensures:
        - returns bundle_hash of the tree `git` reads, or BUNDLE_UNKNOWN when that tree's root
          cannot be read. Never None (None means "no start was captured"; see
          `capture_start_sha`)
    """
    root = git( "rev-parse", "--show-toplevel" )
    return bundle_hash( root ) if root else BUNDLE_UNKNOWN


def _bundle_where( git, root ):
    """`main` when root is the first worktree, `seat` for any other, `?` if unknowable."""
    listing = git( "worktree", "list", "--porcelain" )
    first   = next( ( l.split( " ", 1 )[ 1 ].strip() for l in ( listing or "" ).splitlines() if l.startswith( "worktree " ) ), None )
    if not first: return "?"
    return "main" if os.path.realpath( first ) == os.path.realpath( root ) else "seat"


def _bundle_span( git, root, start_bundle ):
    """
    The `bundle=` / `bundle-span=` suffix, or "" when no start was captured.

    Ensures:
        - "" only when start_bundle is None, for the reason `_run_span` gives: the node runners
          emit before their run, so there is no span to describe
        - names which root was hashed (`@main` or `@seat`): a seat's dist/ and the main tree's
          are different directories, and the :8000 container serves the main one
        - a moved hash prints `bundle-span=<start>..<end>` followed by a rebuilt-mid-run
          warning, as one token beside `run-span`, so no reader can miss it
        - states `unmoved` rather than saying nothing
        - an unreadable start prints `UNKNOWN`: a failed probe must not read as a
          point-in-time report
    """
    if start_bundle is None: return ""
    end   = bundle_hash( root ) if root and root != "?" else BUNDLE_UNKNOWN
    where = _bundle_where( git, root ) if root and root != "?" else "?"
    head  = f" bundle={end}@{where}"
    if start_bundle == BUNDLE_UNKNOWN: return f"{head} bundle-span=UNKNOWN — the start hash could not be read"
    if start_bundle == end:            return f"{head} bundle-span=unmoved"
    return f"{head} bundle-span={start_bundle}..{end} ⚠️ BUNDLE REBUILT MID-RUN"


def tree_state_line( git, start_sha=None, start_bundle=None ):
    """
    One line naming the tree a run was earned on.

    It is never the last line of pytest output: the counts line follows every terminal-summary hook. After a pytest upgrade, check that one function (the sessionfinish and terminal-summary ordering) rather than re-running a fixture and hoping the sample covered your case.


    Requires:
        - git returns stdout for git arguments, or None on any failure. Injected so this is testable without a
          repository, and so a hostile git can be exercised rather than hoped about.
        - start_sha is the sha captured before the run by `capture_start_sha`, or None if no reading was taken.
        - start_bundle is the served-bundle hash captured before the run by `capture_start_bundle`, or None if no reading was taken.

    Ensures:
        - returns a single line, always: an `UNKNOWN` line when the sha cannot be read, never "" and never None.
          A silent instrument reads as "nothing to report"
        - describes an interval, not a moment, when a start_sha is given, since a mid-run commit would otherwise
          go undetected: `run-span=` is `unmoved`, `<start>..<end>` with a warning, or `UNKNOWN`
        - is byte-identical to the line without a span when start_sha is None, because the node and c8 runners
          emit before their run and their line is the start
        - names the repository it measured (`root=`). `git -C <dir>` walks up to the nearest ancestor repo, so a
          non-repo directory yields a confident line about another repo
        - stamps fetch age beside the distance, because `@{upstream}` is the last fetched ref: a bare `behind=0`
          means "up to date as of the last fetch"
        - names the comparison ref it used, because "behind 88" means nothing without it, and the ref differs
          between a tracking branch and a detached worktree
        - reports dirty separately from behind: a clean tree 88 commits back and a dirty tree at the tip are
          different claims, and both invalidate a quoted figure in different ways
        - splits `deleted=` out of the dirty count: in the `:8000` container most tracked files that read as
          modified are not bind-mounted, so git calls them deleted
        - names the composition and claims nothing about the cause: git cannot tell an unmounted file from a
          really deleted one, so this does not guess, and `deleted=125` is a shape no human tree has, so a reader sees a partial mount without the line asserting one
        - prints `deleted=0` rather than omitting it, as `_run_span` states `unmoved`: a field that appears only
          when non-zero is indistinguishable from one that was never computed
        - performs no network access: `@{upstream}` reads the last fetched ref, so a run stays offline and
          cannot hang on a remote

        Raises:
        - nothing that this module can produce: every git call goes through a reader that returns None on
          OSError, SubprocessError, UnicodeDecodeError and ValueError, and the outer `except Exception` keeps
          this function total even if a reader raises.
    """
    try:
        return _tree_state_line( git, start_sha, start_bundle )
    except Exception:
        # TOTAL BY CONSTRUCTION, not by the caller's net. The caller does wrap this,
        # but that wrapper carries `pragma: no cover` — so before this, the only thing
        # standing between a decode failure and a propagating exception was the one
        # line nobody tests (Rio's audit). Now the guarantee lives where the docstring
        # makes it, and a test drives it with a git that raises.
        return "[tree-state] UNKNOWN — the tree-state probe failed; this run's result cannot be tied to a tree"


DIRTY_PATH_CAP = 5


def _dirty_paths( tracked ):
    """
    The `dirty-paths=` value: edited paths first, capped at `DIRTY_PATH_CAP`, then `+N-more`.

    Requires:
        - `tracked` is a list of `git status --porcelain` lines with the `??` untracked rows
          already removed (never None; the caller must render `UNKNOWN` for a failed read rather than calling here)

    Ensures:
        - "none" on a clean tree, printed rather than omitted. A missing field is
          indistinguishable from a probe that never ran
        - the cap belongs to the edits whenever there are any: deletions never take a slot
          while an edit exists, and are reported as a `+N-deleted` tail. With no edits at all
          the deletions take the slots, because then they are the whole report
        - sorting alone is not enough. Inside the `:8000` container about 125 tracked files
          read ` D` for a bind-mount reason unrelated to anyone's work, while one file is
          edited. Edits-first ordering still gave four of five slots to those phantom
          deletions. `+121-more` cannot tell 121 phantom deletions from 121 more edits, so a
          tail that names its own kind is counted separately, and `+N-deleted` never appears
          without an edit for it to be relative to
        - names the destination of a rename (`R old -> new`), because that is the path on
          disk now
        - costs no git call: the `git status --porcelain` output the caller already issued
          carries these paths. The call budget is 8 with an upstream and 9 in the no-upstream
          worst case, which `test_tree_state_reporting.py` pins. Both are stated because one
          number would be a fact about one fixture

    Reading this field: the quiet value is the lowercase word `none`, and a real value carries
    `/`, `.`, digits and `_`. A pattern tuned on a clean tree matches forever and goes blind
    when the field has something to report, the same asymmetry `_run_span` documents. Match to
    end-of-field (`[^ ]*`) or read the whole line.

    The field is comma-separated and space-free for ordinary paths only. Git quotes a path
    containing a space (`"a b.py"`), so the field then contains a space, and a rename line
    carries an arrow of which only the destination survives. Reading the whole line is correct
    in every case.
    """
    if not tracked: return "none"

    def path_of( line ):
        # 🔴 NOT `line[ 3: ]`, AND THE LIVE RUN IS THE ONLY THING THAT CAUGHT IT. Porcelain
        # is `XY<space>PATH`, so a fixed slice looks right — but `_git_reader` returns
        # `stdout.strip()`, which eats the LEADING SPACE OF THE FIRST LINE ONLY. So the
        # first row of the commonest case (` M path`, an unstaged edit) arrives one char
        # short and a fixed slice silently swallows a character of the path:
        # `dirty-paths=rc/cosa/utils/tree_state.py`, measured 2026-09-03. Every synthetic
        # fixture passed, because a hand-built line keeps its leading space.
        m = re.match( r"^\s*\S{1,2}\s+(.*)$", line )
        rest = m.group( 1 ) if m else line.strip()
        return rest.split( " -> " )[ -1 ] if " -> " in rest else rest

    deletions = [ l for l in tracked if "D" in l[ :2 ] ]
    edits     = [ l for l in tracked if "D" not in l[ :2 ] ]

    # THE CAP BELONGS TO THE EDITS WHENEVER THERE ARE ANY. With no edits, the deletions
    # are all there is to report and they take the slots themselves.
    named     = edits if edits else deletions
    shown     = [ path_of( l ) for l in named[ :DIRTY_PATH_CAP ] ]

    remainder = len( named ) - len( shown )
    if remainder:                shown.append( f"+{remainder}-more" )
    if edits and deletions:      shown.append( f"+{len( deletions )}-deleted" )
    return ",".join( shown )


def _tree_state_line( git, start_sha=None, start_bundle=None ):
    """The body of `tree_state_line`; see it for the contract."""
    sha = git( "rev-parse", "--short", "HEAD" )
    if not sha:
        return "[tree-state] UNKNOWN — cannot read HEAD; this run's result cannot be tied to a tree"

    span   = _run_span( start_sha, sha )
    branch = git( "rev-parse", "--abbrev-ref", "HEAD" ) or "?"
    if branch == "HEAD": branch = "detached"
    root = git( "rev-parse", "--show-toplevel" ) or "?"
    span = _bundle_span( git, root, start_bundle ) + span          # beside run-span; a moved hash is a token a reader cannot miss

    ref = git( "rev-parse", "--abbrev-ref", "@{upstream}" ) or _primary_branch( git )
    dirty = git( "status", "--porcelain" )
    tracked   = [ l for l in dirty.splitlines() if l and not l.startswith( "??" ) ] if dirty is not None else None
    tracked_dirty = None if tracked is None else len( tracked )
    deleted       = None if tracked is None else len( [ l for l in tracked if "D" in l[ :2 ] ] )
    dirty_txt = ( "dirty=? dirty-paths=UNKNOWN" if tracked_dirty is None
                  else f"tracked-dirty={tracked_dirty} deleted={deleted} "
                       f"dirty-paths={_dirty_paths( tracked )}" )

    if not ref:
        return ( f"[tree-state] sha={sha} root={root} branch={branch} {dirty_txt} "
                 f"behind=UNKNOWN — no upstream and no primary branch to compare against{span}" )

    behind = git( "rev-list", "--count", f"HEAD..{ref}" )
    ahead  = git( "rev-list", "--count", f"{ref}..HEAD" )
    if behind is None or ahead is None:
        return ( f"[tree-state] sha={sha} root={root} branch={branch} {dirty_txt} "
                 f"behind=UNKNOWN vs {ref} — the comparison ref could not be walked{span}" )

    fetched = _fetch_age( git )
    fetch_txt = f"fetched={fetched}-ago" if fetched else "fetched=UNKNOWN"
    return ( f"[tree-state] sha={sha} root={root} branch={branch} behind={behind} "
             f"ahead={ahead} vs {ref} {fetch_txt} {dirty_txt}{span}" )


def _primary_branch( git ):
    """
    The branch checked out in the first worktree, used when there is no upstream.

    A detached worktree has no upstream at all, and it is the tree most likely to be far
    behind. Falling back to "no comparison" there would leave the case this function exists
    for as the one case it cannot answer.
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
