"""
Worktree drain-then-remove reaper: retire a git worktree without losing work or pushing.

The shared helper that safely retires a git worktree, without ever losing work and
without ever pushing. It is the one function the three reap surfaces all call:

    1. WorktreeContext.__aexit__  (clean Agent/TFE/BFE exit, in-repo path A/B)
    2. session_spawner.dismiss_sessions  (manager-harvest reap, in-repo path A)
    3. heartbeat_arbiter janitor reconcile  (backstop for hard-killed or harness-
       spawned workers that never run their own teardown; the only lever for
       worktrees not reachable from repo code)

Anchor principle (the no-push law): preservation is purely local.
A worktree directory is disposable (it holds node_modules/.venv/build, the disk
hog); a branch ref is durable and lives in the shared local object store. So:

    commit any WIP to the branch  ->  git worktree remove (dir gone, branch kept)
    ->  never push, never delete the branch

This makes "merged or resumed, never lost" true on local refs alone. The branch
survives `git worktree remove`, so the work is fully resumable later via
`git worktree add <branch>`, or mergeable locally after review.

Design decisions ratified in the guided walkthrough:
    D2 - this is the shared utility that both reap paths and the janitor call.
    D4 - WIP is always auto-committed (labeled), never silently discarded.
    D5 - branches are kept; drain_then_remove removes directories only, never branches.

Amendment: D5 left every reaped branch behind forever, and 80 piled up in lupin.
drain_then_remove still never deletes a branch. The janitor (reconcile_worktrees),
after a successful removal, hands the branch to delete_merged_branch. That deletes it
only when it is already an ancestor of the repo's current WIP branch, and only with
`git branch -d`. An unmerged branch is kept and reported. A deleted branch loses
nothing: every one of its commits is on the WIP line.

See: planning-is-prompting -> planning-is-prompting/src/rnd/2026.06.22-worktree-lifecycle-contract.md
     planning-is-prompting -> src/rnd/2026.09.18-worktree-and-branch-cleanup-proposal.md
"""

import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import cosa.utils.util as cu


WIP_COMMIT_PREFIX = "WIP: auto-saved at reap"
RESCUE_BRANCH_PREFIX = "wt-rescue"
BRANCH_GUARD_ALLOW_ENV = "BRANCH_GUARD_ALLOW"

# The Lupin server containers' canonical LUPIN_ROOT (docker-compose.yml). Used to
# detect an in-container reap so we never `git worktree prune` from inside a
# container (bug 47ac0e50 — see _is_in_container).
CONTAINER_PROJECT_ROOT = "/var/lupin"


def _is_in_container( project_root: str ) -> bool:
    """
    True when this reaper is running inside a Lupin server container.

    The :7999/:8000 containers bind-mount ./.git but not lupin-worktrees/, so an in-container
    prune reads every host worktree's gitdir as missing and wipes the shared registry. The
    container's LUPIN_ROOT is /var/lupin; it or a truthy LUPIN_IN_CONTAINER sentinel gates it off.

    Requires:
        - project_root is the resolved main-repo path a prune would run in

    Ensures:
        - returns True iff LUPIN_IN_CONTAINER is set truthy (1/true/yes, case-
          insensitive) or project_root == CONTAINER_PROJECT_ROOT
        - never raises
    """
    if os.environ.get( "LUPIN_IN_CONTAINER", "" ).strip().lower() in ( "1", "true", "yes" ):
        return True
    return project_root == CONTAINER_PROJECT_ROOT


def _default_run( argv, cwd=None, timeout=60 ):
    """
    Default git runner — thin wrapper over subprocess.run.

    Requires:
        - argv is a non-empty list whose first element is "git"
        - cwd is None or an existing directory path

    Ensures:
        - returns a CompletedProcess-shaped object with returncode/stdout/stderr
        - never raises on non-zero git exit (only on timeout / OS error)
        - runs with BRANCH_GUARD_ALLOW=reaper, so the branch guard (María's
          reference-transaction hook, which refuses new refs/heads/* from a Claude session)
          lets the drain mint its wt-rescue branch — without it a detached seat's commits
          would be unreachable once its tree is removed
    """
    return subprocess.run(
        argv,
        cwd            = cwd,
        capture_output = True,
        text           = True,
        timeout        = timeout,
        env            = { **os.environ, BRANCH_GUARD_ALLOW_ENV: "reaper" },
    )


def _git( run: Callable, cwd: str, *args: str, timeout: int = 60 ) -> dict:
    """
    Run `git <args>` in cwd via the injected runner; normalize to a dict.

    Requires:
        - run is a callable accepting ( argv, cwd=, timeout= )
        - cwd is the directory to run git in

    Ensures:
        - returns { success, stdout, stderr, returncode }
        - never raises; a runner exception becomes success=False with stderr set
    """
    try:
        proc = run( [ "git", *args ], cwd=cwd, timeout=timeout )
    except Exception as e:
        return { "success": False, "stdout": "", "stderr": str( e ), "returncode": -1 }

    stdout = ( proc.stdout or "" ).strip() if hasattr( proc, "stdout" ) else ""
    stderr = ( proc.stderr or "" ).strip() if hasattr( proc, "stderr" ) else ""
    return {
        "success"    : proc.returncode == 0,
        "stdout"     : stdout,
        "stderr"     : stderr,
        "returncode" : proc.returncode,
    }


def _utc_stamp( now: Optional[ datetime ] ) -> str:
    """Return an ISO-ish UTC stamp for the WIP commit / rescue-branch label."""
    dt = now if now is not None else datetime.now( timezone.utc )
    return dt.strftime( "%Y%m%dT%H%M%SZ" )


# ==========================================================================
# Ignored files — the loss `git worktree remove` does not warn about
# ==========================================================================
#
# 🔴 MEASURED 2026-09-14 (row 033538f6): a worktree holding ONLY a gitignored
# `.claude-memento.md` showed `git status --porcelain` = 0 lines, and a plain
# `git worktree remove` (no --force) exited 0 and DELETED it. `git add -A` respects
# .gitignore, so the WIP commit below never saw it either. Every reap was silently
# deleting ignored files. A reap now refuses instead of dumping them into a salvage
# folder: a salvage folder is the same pile, moved to where nobody reads it (Mr. Radio).

# Build output and vendored trees, which are disposable by definition. Matched against
# ANY path component, so `web/node_modules/` counts as well as `node_modules/`.
ARTIFACT_DIR_NAMES = {
    "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", "coverage", "htmlcov", ".tox",
    ".dart_tool", ".gradle",
}
# `pubspec.lock` and `gradlew.bat` (2026-09-29, María): lupin-mobile ignores both, so no
# branch ever records them and `flutter pub get` / a build recreates them. Only IGNORED
# entries reach this predicate, so a repo that tracks its lockfile is never affected.
ARTIFACT_FILE_NAMES    = { ".coverage", ".DS_Store", "local.properties", "pubspec.lock", "gradlew.bat" }
ARTIFACT_FILE_SUFFIXES = ( ".pyc", ".pyo" )
# Families, not names (2026-09-29, Mr. Radio + María): the coverage gate writes
# `.coverage-gate-<pid>` and coverage.py's parallel mode writes `.coverage.<host>.<pid>.<rand>`,
# so an exact `.coverage` entry refused every tree that had ever run the gate — forever.
# Flutter regenerates `.flutter-plugins*` and `GeneratedPluginRegistrant.*` on every build.
ARTIFACT_FILE_PREFIXES = ( ".coverage-", ".coverage.", ".flutter-plugins", "GeneratedPluginRegistrant." )

# A tree's OWN run output: what a seat's test runs, crew reports, hook logs and scratch
# leave behind in the tree it stood in. Disposable with the tree. Ruled with Mr. Radio
# 2026-09-14 on measured evidence: before the 233-tree removal, ~7 in 10 trees held
# ignored entries beyond mementos, almost all of them io/ (~166 trees: test-suite results,
# swe-team reports, claude_code_hooks), tmp/ (68) and .claude-session.md (25). Of 3,347
# ignored files triaged by hand, 3 were worth keeping. Without this list nearly every
# reap refuses, and the refusals become the new pile.
# `src/docs/index/` is the generated symbol index (`python -m cosa.repo.symindex build`),
# ignored and never committed: regenerable, so it goes with the tree (María, row aec2319f).
RUN_OUTPUT_PREFIXES   = ( "io/test-suite/", "io/swe-team/", "io/claude_code_hooks/", "tmp/", "src/docs/index/" )
RUN_OUTPUT_ROOT_FILES = { ".claude-session.md" }
MAX_EXPANDED_FILES    = 20000

# memento_io's contract (planning-is-prompting → workflow/scripts/memento_io.py):
#   slot=root RECORD  .claude-memento-<persona>-<sid8>.md   IMMUTABLE
#             POINTER .claude-memento-<persona>.md          a regenerable copy
#   MIRROR    ~/.claude/mementos/<repo-basename>/<record path relative to the repo>
# By design the ROOT slot lands in the seat's OWN tree, so seat trees routinely hold
# one. A record whose mirror is byte-identical is disposable: the mirror is the durable
# copy and the only reader of the in-tree copy was the dead seat's own self_respin.
MEMENTO_RECORD_RE    = re.compile( r"^\.claude-memento-(?P<persona>.+)-[0-9a-f]{8}\.md$" )
MEMENTO_POINTER_RE   = re.compile( r"^\.claude-memento-(?P<persona>.+)\.md$" )
MEMENTO_POINTER_MARK = "<!-- MEMENTO POINTER"
MEMENTO_CURRENT_RE   = re.compile( r"^<!-- current: (?P<record>\S+) -->$" )
MAX_NAMED_BLOCKERS   = 10


def _memento_mirror_home() -> str:
    """The out-of-repo memento mirror root — memento_io.MIRROR_HOME, overridable for tests."""
    return os.environ.get( "LUPIN_MEMENTO_MIRROR_HOME",
                           os.path.join( os.path.expanduser( "~" ), ".claude", "mementos" ) )


def _is_artifact( rel_path: str, abs_path: str ) -> bool:
    """
    Is this ignored entry disposable build output rather than somebody's data?

    Requires:
        - rel_path is the entry's path relative to the worktree, as git printed it
          (a trailing "/" marks a wholly ignored directory)
        - abs_path is the same entry as an absolute path

    Ensures:
        - True for a symlink (every artifact the spawner borrows into a tree is one,
          and removing a link never touches its target)
        - True when any path component is in ARTIFACT_DIR_NAMES, or the basename is in
          ARTIFACT_FILE_NAMES, starts with an ARTIFACT_FILE_PREFIXES prefix, or ends with
          an ARTIFACT_FILE_SUFFIXES suffix
        - False otherwise; never raises
    """
    if os.path.islink( abs_path.rstrip( os.sep ) ):
        return True
    parts = [ p for p in rel_path.split( "/" ) if p ]
    if not parts:
        return False
    if any( p in ARTIFACT_DIR_NAMES for p in parts ):
        return True
    name = parts[ -1 ]
    return ( name in ARTIFACT_FILE_NAMES or name.startswith( ARTIFACT_FILE_PREFIXES )
             or name.endswith( ARTIFACT_FILE_SUFFIXES ) )


def _is_run_output( rel_path: str ) -> bool:
    """
    Is this ignored entry the tree's own run output (RUN_OUTPUT_PREFIXES / _ROOT_FILES)?

    Ensures:
        - True for a path under one of the prefixes, or for the prefix directory itself
          as git prints it ("tmp/"), or for a root-level file in RUN_OUTPUT_ROOT_FILES
        - False otherwise; never raises
    """
    if rel_path in RUN_OUTPUT_ROOT_FILES:
        return True
    return any( rel_path.startswith( prefix ) for prefix in RUN_OUTPUT_PREFIXES )


def _expand_ignored_directory( worktree_path: str, rel_dir: str ) -> Optional[ list ]:
    """
    List the files inside a wholly ignored directory, so each is judged on its own.

    `git ls-files --directory` collapses a wholly ignored directory to one entry ("io/"),
    and "io/" holds both a tree's run output and, possibly, somebody's data. Blocking on
    the folder name would refuse nearly every reap; passing it would pass the data.

    Requires:
        - rel_dir is a directory entry as git printed it, ending in "/"

    Ensures:
        - returns tree-relative file paths under rel_dir, not descending into symlinked
          directories or ARTIFACT_DIR_NAMES; a symlinked file is listed (the caller's
          _is_artifact passes it)
        - returns None when the walk fails or exceeds MAX_EXPANDED_FILES — the caller
          must treat that as "cannot judge" and block on the directory itself
        - never raises
    """
    base   = os.path.join( worktree_path, rel_dir )
    found  = []
    failed = []
    try:
        for root, dirs, files in os.walk( base, onerror=failed.append ):
            dirs[ : ] = [ d for d in dirs
                          if d not in ARTIFACT_DIR_NAMES and not os.path.islink( os.path.join( root, d ) ) ]
            for name in files:
                found.append( os.path.relpath( os.path.join( root, name ), worktree_path ) )
                if len( found ) > MAX_EXPANDED_FILES:
                    return None
    except Exception:
        return None
    return None if failed else found


def _files_identical( a: str, b: str ) -> bool:
    """True iff both paths are regular files with identical bytes; never raises."""
    try:
        if not ( os.path.isfile( a ) and os.path.isfile( b ) ):
            return False
        if os.path.getsize( a ) != os.path.getsize( b ):
            return False
        with open( a, "rb" ) as fa, open( b, "rb" ) as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _pointer_names( abs_path: str ) -> Optional[ str ]:
    """
    The record a memento pointer names, read from its header.

    Ensures:
        - returns the `<!-- current: <record> -->` value when the file's first line is
          memento_io's pointer mark and its second line names a record
        - returns None for anything else (not a pointer, unreadable, malformed)
        - never raises
    """
    try:
        with open( abs_path, "r", encoding="utf-8", errors="replace" ) as fh:
            first, second = fh.readline(), fh.readline()
    except OSError:
        return None
    if not first.startswith( MEMENTO_POINTER_MARK ):
        return None
    match = MEMENTO_CURRENT_RE.match( second.strip() )
    return match.group( "record" ) if match else None


def find_ignored_blockers( worktree_path: str, project_root: str, run: Callable ) -> dict:
    """
    List the ignored entries in a worktree that a removal would silently destroy.

    Requires:
        - worktree_path is an existing git worktree
        - project_root is the main checkout; its basename keys the memento mirror
        - run is the git runner used by drain_then_remove

    Ensures:
        - returns { "ok": bool, "blockers": [ rel_path, ... ], "error": str | None }
        - ok=False with error set when git could not list the ignored entries — the
          caller must treat that as "cannot prove it is safe" and refuse
        - an entry is not a blocker when it is a build artifact (_is_artifact), a
          root-slot memento record whose mirror is byte-identical, or a root-slot
          memento pointer whose header names a record that cleared that test (not
          merely some record for the same persona)
        - the mirror is keyed on the main checkout's basename, because memento_io's
          find_repo_root collapses a worktree to its main checkout before keying the
          mirror; keying on the worktree's own name would find no mirror and refuse
          every reap
        - everything else is a blocker — including the legacy `.claude-memento.md`,
          which has no mirror guarantee
        - never raises
    """
    listing = _git( run, worktree_path, "-c", "core.quotepath=off", "ls-files", "--others",
                    "--ignored", "--exclude-standard", "--directory", "--no-empty-directory" )
    if not listing[ "success" ]:
        return { "ok": False, "blockers": [], "error": f"git ls-files --ignored failed: {listing[ 'stderr' ]}" }

    listed          = [ line for line in listing[ "stdout" ].splitlines() if line.strip() ]
    mirror_dir      = os.path.join( _memento_mirror_home(), os.path.basename( os.path.normpath( project_root ) ) )
    cleared_records = set()
    pending         = []

    entries = []
    for rel in listed:
        abs_path = os.path.join( worktree_path, rel )
        if _is_artifact( rel, abs_path ) or _is_run_output( rel ):
            continue
        if rel.endswith( "/" ) and os.path.isdir( abs_path ):
            expanded = _expand_ignored_directory( worktree_path, rel )
            if expanded is None:
                entries.append( rel )            # cannot judge its contents ⇒ block on the directory
            else:
                entries.extend( expanded )
            continue
        entries.append( rel )

    for rel in entries:
        abs_path = os.path.join( worktree_path, rel )
        if _is_artifact( rel, abs_path ) or ( not rel.endswith( "/" ) and _is_run_output( rel ) ):
            continue
        if MEMENTO_RECORD_RE.match( rel ) and _files_identical( abs_path, os.path.join( mirror_dir, rel ) ):
            cleared_records.add( rel )
            continue
        pending.append( rel )

    blockers = []
    for rel in pending:
        if MEMENTO_POINTER_RE.match( rel ) and _pointer_names( os.path.join( worktree_path, rel ) ) in cleared_records:
            continue
        blockers.append( rel )

    return { "ok": True, "blockers": blockers, "error": None }


# ==========================================================================
# Evacuation — move a tree's ignored data out, then remove the tree (row aec2319f)
# ==========================================================================
#
# Refusing a tree that holds ignored data kept the data and kept the tree, forever:
# measured 2026-10-02, 6 of 6 remaining seat trees were refused, each ticketed to a persona
# whose ticket then parked. Rick's ruling: move the files to a dated folder in the main
# tree, remove the tree, and let the sweep delete the folder after the retention window.
# The earlier objection to a salvage folder ("the same pile, moved to where nobody reads
# it") is answered by the window: the folder has an expiry, the refusals did not.

EVACUATION_SUBDIR      = os.path.join( "io", "worktree-evacuated" )
ARCHIVE_REF_PREFIX     = "refs/archive"
ARCHIVE_RETENTION_DAYS = 14
DATED_NAME_RE          = re.compile( r"^(?P<day>\d{4}-\d{2}-\d{2})(?:$|[-_/T])" )


def default_evacuation_root( project_root: str ) -> str:
    """The main tree's evacuation folder: <project_root>/io/worktree-evacuated."""
    return os.path.join( project_root, EVACUATION_SUBDIR )


def evacuate_blockers( worktree_path: str, blockers: list, evacuation_root: str, stamp: str ) -> dict:
    """
    Move a tree's ignored data files into a new dated folder outside the tree.

    Requires:
        - blockers are tree-relative paths from find_ignored_blockers (a trailing "/"
          marks a directory that could not be expanded; it moves whole)
        - evacuation_root is a directory outside worktree_path
        - stamp is _utc_stamp()'s value for this reap

    Ensures:
        - destination is <evacuation_root>/<YYYY-MM-DD>-<tree name>-<stamp>, created new;
          if it already exists nothing moves and ok is False (never merges into, or
          overwrites, an earlier evacuation)
        - each blocker keeps its tree-relative path under the destination
        - returns { ok, dest, moved: [ rel ], error }; on a failed move ok is False, error
          names the file, and whatever already moved stays in dest (moved lists it) — the
          caller must then leave the tree in place
        - never raises
    """
    day  = f"{stamp[ 0:4 ]}-{stamp[ 4:6 ]}-{stamp[ 6:8 ]}"
    dest = os.path.join( evacuation_root, f"{day}-{os.path.basename( os.path.normpath( worktree_path ) )}-{stamp}" )
    out  = { "ok": False, "dest": dest, "moved": [], "error": None }
    if os.path.exists( dest ):
        out[ "error" ] = f"evacuation folder already exists, refusing to merge into it: {dest}"
        return out
    for rel in blockers:
        clean = rel.rstrip( "/" )
        try:
            target = os.path.join( dest, clean )
            os.makedirs( os.path.dirname( target ), exist_ok=True )
            shutil.move( os.path.join( worktree_path, clean ), target )
        except Exception as e:
            out[ "error" ] = f"could not move {rel}: {e}"
            return out
        out[ "moved" ].append( rel )
    out[ "ok" ] = True
    return out


def drain_then_remove(
    worktree_path : str,
    project_root  : Optional[ str ]      = None,
    run           : Optional[ Callable ] = None,
    now           : Optional[ datetime ] = None,
    debug         : bool                 = False,
    evacuation_root : Optional[ str ]    = None,
) -> dict:
    """
    Retire a worktree: commit WIP to its branch, remove the directory, keep the branch.

    Requires:
        - worktree_path is the absolute path to the worktree directory
        - project_root is None (resolved via cu.get_project_root()) or the
          absolute path to the main repo's working tree
        - run is None (real git via subprocess) or an injected runner callable
          with signature run( argv, cwd=, timeout= ) for testing

    Ensures:
        - if worktree_path does not exist: returns removed=False,
          skipped_reason="path_absent" (nothing to do; caller may prune)
        - if the tree holds ignored entries a removal would destroy (see find_ignored_blockers):
          removed=False, skipped_reason="ignored_files_present", ignored_blockers lists them,
          and nothing is touched, so no rescue branch and no WIP commit. If they cannot be listed:
          skipped_reason="ignored_check_failed" (cannot prove safe, so refuse)
        - with evacuation_root set, those entries are moved there instead (see evacuate_blockers)
          and the reap goes on; "evacuated_to" names the folder and "evacuated" the entries.
          If the move fails: removed=False, skipped_reason="evacuation_failed", and the tree stays
        - detached HEAD whose rescue branch cannot be created: removed=False,
          skipped_reason="rescue_branch_failed" (its commits live only in this tree)
        - if uncommitted edits exist: they are committed to the worktree's branch as a labeled
          WIP commit before removal, never discarded; a detached HEAD is first given a rescue
          branch so the commit is reachable after removal
        - the worktree directory is removed (git worktree remove); the branch ref is preserved
        - never runs `git push` and never runs `git branch -d/-D`
        - returns a result dict (below); never raises, every git failure is captured in errors[]
          so a reaper loop is not derailed by one bad tree

    Returns:
        { worktree_path, branch (where the work is preserved, or None), wip_committed (bool),
          wip_sha, rescue_branch (set iff HEAD was detached), removed (bool, directory removed),
          skipped_reason, ignored_blockers (ignored entries that refused removal),
          evacuated_to (folder the ignored data went to), evacuated (the entries moved), errors }
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()

    result = {
        "worktree_path"  : worktree_path,
        "branch"         : None,
        "wip_committed"  : False,
        "wip_sha"        : None,
        "rescue_branch"  : None,
        "removed"          : False,
        "skipped_reason"   : None,
        "ignored_blockers" : [],
        "evacuated_to"     : None,
        "evacuated"        : [],
        "errors"           : [],
    }

    if not os.path.exists( worktree_path ):
        result[ "skipped_reason" ] = "path_absent"
        if debug: print( f"[worktree_reaper] path absent, nothing to do: {worktree_path}" )
        return result

    # 1. Identify the branch this worktree has checked out.
    head = _git( run, worktree_path, "rev-parse", "--abbrev-ref", "HEAD" )
    if not head[ "success" ]:
        # Broken orphan: admin gitdir gone, git can't operate in here. This util
        # does NOT rm broken orphans (that is the recovery track's hand-rm job);
        # we refuse rather than risk losing un-inspected content.
        result[ "skipped_reason" ] = "broken_or_not_a_worktree"
        result[ "errors" ].append( f"rev-parse HEAD failed: {head[ 'stderr' ]}" )
        if debug: print( f"[worktree_reaper] broken/non-worktree, refusing: {worktree_path}" )
        return result

    # 1b. Refuse BEFORE touching anything if the removal would destroy ignored files
    #     that are somebody's data (row 033538f6). Checked first so a refused tree gets
    #     no rescue branch and no WIP commit — it is left exactly as it was found.
    ignored = find_ignored_blockers( worktree_path, project_root, run )
    if not ignored[ "ok" ]:
        result[ "skipped_reason" ] = "ignored_check_failed"
        result[ "errors" ].append( ignored[ "error" ] )
        if debug: print( f"[worktree_reaper] could not list ignored files, refusing: {worktree_path}" )
        return result
    if ignored[ "blockers" ] and evacuation_root is not None:
        moved = evacuate_blockers( worktree_path, ignored[ "blockers" ], evacuation_root, _utc_stamp( now ) )
        result[ "evacuated_to" ] = moved[ "dest" ]
        result[ "evacuated" ]    = moved[ "moved" ]
        if not moved[ "ok" ]:
            result[ "skipped_reason" ]   = "evacuation_failed"
            result[ "ignored_blockers" ] = ignored[ "blockers" ]
            result[ "errors" ].append( moved[ "error" ] )
            if debug: print( f"[worktree_reaper] evacuation failed, refusing: {worktree_path}" )
            return result
        if debug: print( f"[worktree_reaper] evacuated {len( moved[ 'moved' ] )} entries to {moved[ 'dest' ]}" )
    elif ignored[ "blockers" ]:
        named = ignored[ "blockers" ][ :MAX_NAMED_BLOCKERS ]
        more  = len( ignored[ "blockers" ] ) - len( named )
        result[ "skipped_reason" ]   = "ignored_files_present"
        result[ "ignored_blockers" ] = ignored[ "blockers" ]
        result[ "errors" ].append( f"removal would delete {len( ignored[ 'blockers' ] )} ignored "
                                   f"non-artifact entr{'y' if len( ignored[ 'blockers' ] ) == 1 else 'ies'}: "
                                   f"{', '.join( named )}{f' (+{more} more)' if more else ''}" )
        if debug: print( f"[worktree_reaper] ignored files present, refusing: {worktree_path}" )
        return result

    branch    = head[ "stdout" ]
    detached  = ( branch == "HEAD" )
    stamp     = _utc_stamp( now )

    # 2. If HEAD is detached, mint a rescue branch so any WIP commit (and the
    #    current HEAD) stays reachable after the worktree dir is gone.
    if detached:
        rescue = f"{RESCUE_BRANCH_PREFIX}/{os.path.basename( worktree_path )}-{stamp}"
        sw = _git( run, worktree_path, "switch", "-c", rescue )
        if sw[ "success" ]:
            branch                  = rescue
            result[ "rescue_branch" ] = rescue
            if debug: print( f"[worktree_reaper] detached HEAD -> rescue branch {rescue}" )
        else:
            # Refuse rather than remove: a detached HEAD's commits are reachable only
            # through this tree, so removing it without the rescue branch orphans them.
            # Measured 2026-09-29 by a mutant — the drain used to report removed=True here.
            result[ "errors" ].append( f"rescue-branch create failed: {sw[ 'stderr' ]}" )
            result[ "skipped_reason" ] = "rescue_branch_failed"
            if debug: print( f"[worktree_reaper] rescue branch FAILED, refusing removal: {worktree_path}" )
            return result

    result[ "branch" ] = branch

    # 3. Commit any uncommitted edits to the branch (D4 — always, never discard).
    status = _git( run, worktree_path, "status", "--porcelain" )
    if status[ "success" ] and status[ "stdout" ]:
        add = _git( run, worktree_path, "add", "-A" )
        if not add[ "success" ]:
            result[ "errors" ].append( f"git add -A failed: {add[ 'stderr' ]}" )
        commit = _git(
            run, worktree_path,
            "commit", "--no-verify", "-m", f"{WIP_COMMIT_PREFIX} {stamp}",
        )
        if commit[ "success" ]:
            result[ "wip_committed" ] = True
            sha = _git( run, worktree_path, "rev-parse", "HEAD" )
            if sha[ "success" ]: result[ "wip_sha" ] = sha[ "stdout" ]
            if debug: print( f"[worktree_reaper] WIP committed on {branch}: {result[ 'wip_sha' ]}" )
        else:
            # Could not preserve WIP — do NOT remove the dir (zero-loss mandate).
            result[ "skipped_reason" ] = "wip_commit_failed"
            result[ "errors" ].append( f"WIP commit failed: {commit[ 'stderr' ]}" )
            if debug: print( f"[worktree_reaper] WIP commit FAILED, refusing removal: {worktree_path}" )
            return result

    # 4. Remove the worktree DIR from the main repo; keep the branch ref.
    remove = _git( run, project_root, "worktree", "remove", worktree_path )
    if remove[ "success" ]:
        result[ "removed" ] = True
        if debug: print( f"[worktree_reaper] removed dir, kept branch {branch}: {worktree_path}" )
    else:
        # Tree is clean now (WIP committed), so a remaining failure is unusual
        # (e.g. submodule). Prune cleans only the admin entry, not the dir, so we
        # surface the failure rather than force-remove (force could discard).
        result[ "errors" ].append( f"git worktree remove failed: {remove[ 'stderr' ]}" )
        # In-container guard (bug 47ac0e50): NEVER `git worktree prune` from inside
        # a Lupin container — it bind-mounts ./.git but not lupin-worktrees/, so an
        # in-container prune reads every host worktree's gitdir as a missing path
        # and wipes the ENTIRE shared registry. Skip with a recorded note instead.
        if _is_in_container( project_root ):
            result[ "errors" ].append(
                f"skipped `git worktree prune` — in-container (project_root={project_root}); "
                "an in-container prune would wipe the shared host worktree registry (bug 47ac0e50)"
            )
            if debug: print( "[worktree_reaper] in-container: SKIPPED prune to protect host registry" )
        else:
            prune = _git( run, project_root, "worktree", "prune" )
            if not prune[ "success" ]:
                result[ "errors" ].append( f"git worktree prune failed: {prune[ 'stderr' ]}" )
        if debug: print( f"[worktree_reaper] remove failed (work preserved on {branch}): {worktree_path}" )

    return result


def list_worktrees( project_root: Optional[ str ] = None, run: Optional[ Callable ] = None ) -> list:
    """
    Parse `git worktree list --porcelain` into structured records.

    Requires:
        - project_root is None (resolved via cu.get_project_root()) or the main
          repo's working-tree path
        - run is None (real git) or an injected runner ( argv, cwd=, timeout= )

    Ensures:
        - returns a list of dicts { path, branch (str|None), locked (bool),
          lock_reason (str|None), is_main (bool) }; is_main is True for the primary working tree
          (path == project_root)
        - never raises; a git failure yields []
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()

    res = _git( run, project_root, "worktree", "list", "--porcelain" )
    if not res[ "success" ]:
        return []

    records = []
    for block in res[ "stdout" ].split( "\n\n" ):
        rec = {}
        for line in block.splitlines():
            if   line.startswith( "worktree " ): rec[ "path" ]   = line[ 9: ].strip()
            elif line.startswith( "branch " ):   rec[ "branch" ] = line[ 7: ].strip().replace( "refs/heads/", "", 1 )
            elif line == "detached":             rec[ "branch" ] = None
            elif line.startswith( "locked" ):
                rec[ "locked" ]      = True
                rec[ "lock_reason" ] = line[ 6: ].strip() or None
        if rec.get( "path" ):
            rec.setdefault( "branch", None )
            rec.setdefault( "locked", False )
            rec.setdefault( "lock_reason", None )
            rec[ "is_main" ] = ( os.path.abspath( rec[ "path" ] ) == os.path.abspath( project_root ) )
            records.append( rec )
    return records


def _newest_mtime_age_hours( path: str, now_ts: float ) -> float:
    """
    Hours since the most-recently-modified non-vendored file under `path`.

    Ensures:
        - walks `path` skipping .git / node_modules / .venv / venv / __pycache__
          (vendored/build noise; a worker's source edits land outside these)
        - returns float('inf') for an empty/unreadable tree (treated as idle)
    """
    newest = 0.0
    for root, dirs, files in os.walk( path ):
        for d in ( ".git", "node_modules", ".venv", "venv", "__pycache__" ):
            if d in dirs: dirs.remove( d )
        for f in files:
            # In a LINKED worktree, .git is a FILE stamped fresh at `worktree add`
            # time — exclude it or it masks a genuinely-idle tree as active.
            if f == ".git": continue
            try:
                m = os.path.getmtime( os.path.join( root, f ) )
                if m > newest: newest = m
            except OSError:
                continue
    if newest == 0.0:
        return float( "inf" )
    return ( now_ts - newest ) / 3600.0


# ==========================================================================
# Merged-branch deletion — P1 of row 129cc96b (Rick, 2026-09-18)
# ==========================================================================
#
# The rule is ONE predicate: the branch tip is an ancestor of the repo's current WIP
# branch, so every commit on it is already on the line. Only then is `git branch -d`
# run, and `-d` refuses unmerged work on its own as a second lock.
#
# 🔴 FULLY QUALIFIED REFS, ALWAYS (Rachel's break test, 2026-09-18). git resolves a bare
# name to a TAG before a branch, so a tag named like the branch (or like the WIP branch)
# made the ancestry check measure the wrong commit and answer "merged". With an upstream
# set, `-d` then agreed, and a branch whose commits were only on the remote was deleted.
# merge_verdict is always handed `refs/heads/<name>` for both sides.
#
# ⚠️ `-d` ALONE IS NOT THE RULE. When a branch has an upstream, `git branch -d` measures
# it against the UPSTREAM and deletes it with only a warning, even when the WIP branch
# has none of its commits. The explicit ancestry check is what measures against the WIP
# branch, as the ruling says.

PROTECTED_BRANCHES = ( "main", "master" )
PROTECTED_MARK     = "wip"      # any branch whose name holds it is a working line (María, 2026-09-18)


def is_protected_branch( branch: str, target: Optional[ str ] ) -> bool:
    """
    Is this a branch the janitor must never delete, whatever its merge state?

    Ensures:
        - True for main, master, the repo's current WIP branch (`target`), and any
          branch whose name contains "wip" in any case — the numbered release lines
          (`wip-v0.2.1-…`) are all merged into each other and would all qualify
    """
    return branch in PROTECTED_BRANCHES or branch == target or PROTECTED_MARK in branch.lower()


def checked_out_branches( project_root: str, run: Callable ) -> Optional[ set ]:
    """
    Every branch some worktree of this repo has checked out.

    Ensures:
        - returns the set of short branch names from `git worktree list --porcelain`
        - returns None when git fails — "could not look", never "none checked out"
        - never raises
    """
    res = _git( run, project_root, "worktree", "list", "--porcelain" )
    if not res[ "success" ]:
        return None
    return { line[ len( "branch refs/heads/" ): ].strip()
             for line in res[ "stdout" ].splitlines() if line.startswith( "branch refs/heads/" ) }


def main_worktree_branch( records: list ) -> Optional[ str ]:
    """
    The repo's current WIP branch: whatever the main working tree has checked out.

    Requires:
        - records is list_worktrees() output (dicts carrying is_main and branch)

    Ensures:
        - returns the main tree's branch name
        - returns None when there is no main record or its HEAD is detached — the
          caller must then keep every branch, since there is nothing to measure against
    """
    for rec in records:
        if rec.get( "is_main" ):
            return rec.get( "branch" )
    return None


def merge_verdict( project_root: str, ref: str, target: str, run: Callable ) -> dict:
    """
    Is every commit on `ref` already on `target`?

    Requires:
        - project_root is a directory git can run in; ref and target name commits.
          Callers pass `refs/heads/<name>` or a sha, never a bare branch name — a bare
          name resolves to a same-named tag first

    Ensures:
        - returns { verdict: "merged" | "unmerged" | "failed", commits_ahead, error }
        - "merged" iff `git merge-base --is-ancestor <ref> <target>` exits 0
        - "unmerged" iff it exits 1; commits_ahead is then `rev-list --count
          <target>..<ref>` (None when that count cannot be read)
        - "failed" for any other exit — could not look, which is never "merged"
        - never raises
    """
    anc = _git( run, project_root, "merge-base", "--is-ancestor", ref, target )
    if anc[ "returncode" ] == 0:
        return { "verdict": "merged", "commits_ahead": 0, "error": None }
    if anc[ "returncode" ] != 1:
        return { "verdict": "failed", "commits_ahead": None,
                 "error": f"merge-base --is-ancestor failed: {anc[ 'stderr' ]}" }
    count = _git( run, project_root, "rev-list", "--count", f"{target}..{ref}" )
    ahead = int( count[ "stdout" ] ) if count[ "success" ] and count[ "stdout" ].isdigit() else None
    return { "verdict": "unmerged", "commits_ahead": ahead, "error": None }


def delete_merged_branch(
    project_root : str,
    branch       : Optional[ str ],
    target       : Optional[ str ],
    run          : Optional[ Callable ] = None,
) -> dict:
    """
    Delete a branch only when it is fully merged into the repo's current WIP branch.

    Requires:
        - project_root is the main working tree, whose HEAD is `target`
        - branch is the reaped worktree's branch, or None
        - target is main_worktree_branch( ... ), or None

    Ensures:
        - returns { branch, target, deleted, kept_reason, commits_ahead, error }
        - kept "no_branch" / "no_target_branch" when either is missing
        - kept "protected" for main, master, the WIP branch itself, or any branch whose
          name contains "wip" (is_protected_branch) — never touched
        - kept "checked_out" when any worktree still has the branch checked out, and
          "worktree_list_failed" when that cannot be read
        - kept "unmerged" (with commits_ahead) when the ancestry check says so, and
          "merge_check_failed" when it could not be read
        - otherwise runs `git branch -d <branch>` — never -D — and reports
          "branch_d_refused" with git's own words if -d says no
        - never pushes, never deletes a remote ref, never raises
    """
    run     = run if run is not None else _default_run
    outcome = { "branch": branch, "target": target, "deleted": False,
                "kept_reason": None, "commits_ahead": None, "error": None }

    if not branch:
        outcome[ "kept_reason" ] = "no_branch"
        return outcome
    if not target:
        outcome[ "kept_reason" ] = "no_target_branch"
        return outcome
    if is_protected_branch( branch, target ):
        outcome[ "kept_reason" ] = "protected"
        return outcome
    held = checked_out_branches( project_root, run )
    if held is None:
        outcome[ "kept_reason" ] = "worktree_list_failed"
        return outcome
    if branch in held:
        outcome[ "kept_reason" ] = "checked_out"
        return outcome

    verdict = merge_verdict( project_root, f"refs/heads/{branch}", f"refs/heads/{target}", run )
    outcome[ "commits_ahead" ] = verdict[ "commits_ahead" ]
    if verdict[ "verdict" ] != "merged":
        outcome[ "kept_reason" ] = "unmerged" if verdict[ "verdict" ] == "unmerged" else "merge_check_failed"
        outcome[ "error" ]       = verdict[ "error" ]
        return outcome

    delete = _git( run, project_root, "branch", "-d", branch )
    if delete[ "success" ]:
        outcome[ "deleted" ] = True
    else:
        outcome[ "kept_reason" ] = "branch_d_refused"
        outcome[ "error" ]       = f"git branch -d refused: {delete[ 'stderr' ]}"
    return outcome


# ==========================================================================
# Archive — unmerged work leaves the branch list without being lost (row aec2319f)
# ==========================================================================
#
# A branch the ancestry check calls unmerged used to be kept forever, with no owner and
# no deadline. Two populations hide in that verdict: work that landed by another route (a
# squash merge, a cherry-pick — measured 2026-10-02, PR 22's squash left four branches
# reading 2,500+ commits ahead with 5 unique between them) and work that never landed.
# Rick's ruling: neither stays in `git branch`. The ref moves to refs/archive/<day>/<name>
# — still reachable, so nothing can be garbage-collected — and the sweep deletes it after
# the retention window. `landed` on the outcome says which population it was.
#
# Restore one with: git update-ref refs/heads/<name> <sha>


def content_landed( project_root: str, branch: str, target: str, run: Callable ) -> Optional[ bool ]:
    """
    Has every commit on `branch` already reached `target` by content, if not by ancestry?

    Ensures:
        - True when `git cherry refs/heads/<target> refs/heads/<branch>` lists no commit
          marked "+" (each has a patch-equivalent on target, or the branch adds nothing)
        - False when at least one commit is marked "+"
        - None when git could not answer — "could not look", never "landed"
        - never raises
    """
    res = _git( run, project_root, "cherry", f"refs/heads/{target}", f"refs/heads/{branch}", timeout=300 )
    if not res[ "success" ]:
        return None
    return not any( line.startswith( "+" ) for line in res[ "stdout" ].splitlines() )


def archive_branch( project_root: str, branch: str, run: Callable, now: Optional[ datetime ] = None ) -> dict:
    """
    Move a branch out of refs/heads into refs/archive/<YYYY-MM-DD>/<branch>.

    Ensures:
        - returns { archived, archive_ref, sha, error }
        - the archive ref is written and read back before the branch ref is removed, and
          the branch ref is removed only if it still points at the sha that was archived
          (a commit landing in between keeps the branch)
        - when the archive ref already exists at another sha, the new one gets a
          `-<sha9>` suffix instead of overwriting it
        - archived is False, with error set and the branch untouched, on any failure
        - never pushes, never raises
    """
    out  = { "archived": False, "archive_ref": None, "sha": None, "error": None }
    head = _git( run, project_root, "rev-parse", "--verify", "-q", f"refs/heads/{branch}" )
    if not head[ "success" ] or not head[ "stdout" ]:
        out[ "error" ] = f"cannot resolve refs/heads/{branch}: {head[ 'stderr' ]}"
        return out
    sha = head[ "stdout" ]
    day = ( now if now is not None else datetime.now( timezone.utc ) ).strftime( "%Y-%m-%d" )
    ref = f"{ARCHIVE_REF_PREFIX}/{day}/{branch}"
    existing = _git( run, project_root, "rev-parse", "--verify", "-q", ref )
    if existing[ "success" ] and existing[ "stdout" ] and existing[ "stdout" ] != sha:
        ref = f"{ref}-{sha[ :9 ]}"
    out[ "sha" ] = sha

    write = _git( run, project_root, "update-ref", ref, sha )
    check = _git( run, project_root, "rev-parse", "--verify", "-q", ref )
    if not write[ "success" ] or check[ "stdout" ] != sha:
        out[ "error" ] = f"could not write {ref}: {write[ 'stderr' ] or 'read-back mismatch'}"
        return out
    out[ "archive_ref" ] = ref

    drop = _git( run, project_root, "update-ref", "-d", f"refs/heads/{branch}", sha )
    if not drop[ "success" ]:
        out[ "error" ] = f"archived at {ref} but could not remove the branch: {drop[ 'stderr' ]}"
        return out
    out[ "archived" ] = True
    return out


def retire_branch(
    project_root : str,
    branch       : Optional[ str ],
    target       : Optional[ str ],
    run          : Optional[ Callable ] = None,
    now          : Optional[ datetime ] = None,
) -> dict:
    """
    Take a branch out of the branch list: delete it when merged, archive it when not.

    Ensures:
        - starts from delete_merged_branch's outcome, unchanged for every result except
          kept "unmerged"
        - an unmerged branch is archived (archive_branch). The outcome then carries
          kept_reason "archived", archive_ref, sha, and landed (content_landed, measured
          before the ref moves): True means its commits are on the target by content,
          False means it holds work that never landed, None means git could not say
        - when the archive fails: kept_reason "archive_failed", error set, branch kept
        - never deletes an unmerged commit, never pushes, never raises
    """
    run     = run if run is not None else _default_run
    outcome = delete_merged_branch( project_root, branch, target, run=run )
    if outcome[ "kept_reason" ] != "unmerged":
        return outcome
    outcome[ "landed" ] = content_landed( project_root, branch, target, run )
    moved = archive_branch( project_root, branch, run, now=now )
    outcome[ "archive_ref" ] = moved[ "archive_ref" ]
    outcome[ "sha" ]         = moved[ "sha" ]
    if moved[ "archived" ]:
        outcome[ "kept_reason" ] = "archived"
    else:
        outcome[ "kept_reason" ] = "archive_failed"
        outcome[ "error" ]       = moved[ "error" ]
    return outcome


def _dated_before( name: str, cutoff_day: str ) -> bool:
    """True when `name` starts with a YYYY-MM-DD day earlier than cutoff_day, otherwise False."""
    hit = DATED_NAME_RE.match( name )
    return hit is not None and hit.group( "day" ) < cutoff_day


def sweep_archive(
    project_root    : str,
    run             : Optional[ Callable ] = None,
    now             : Optional[ datetime ] = None,
    retention_days  : int                  = ARCHIVE_RETENTION_DAYS,
    evacuation_root : Optional[ str ]      = None,
) -> dict:
    """
    Delete archived refs and evacuation folders older than the retention window.

    Ensures:
        - an archive ref refs/archive/<YYYY-MM-DD>/... is deleted when its day is more
          than retention_days before today (UTC); a ref without a dated first segment is
          never touched
        - an evacuation folder <evacuation_root>/<YYYY-MM-DD>-... is removed on the same
          rule; any other entry there is never touched. evacuation_root None means
          default_evacuation_root( project_root )
        - returns { refs_deleted: [ ref ], folders_deleted: [ path ], errors: [ str ] }
        - never pushes, never raises
    """
    run    = run if run is not None else _default_run
    today  = now if now is not None else datetime.now( timezone.utc )
    cutoff = ( today - timedelta( days=retention_days ) ).strftime( "%Y-%m-%d" )
    root   = evacuation_root if evacuation_root is not None else default_evacuation_root( project_root )
    out    = { "refs_deleted": [], "folders_deleted": [], "errors": [] }

    refs = _git( run, project_root, "for-each-ref", "--format=%(refname)", ARCHIVE_REF_PREFIX )
    if not refs[ "success" ]:
        out[ "errors" ].append( f"could not list {ARCHIVE_REF_PREFIX}: {refs[ 'stderr' ]}" )
    for ref in refs[ "stdout" ].split() if refs[ "success" ] else []:
        if not _dated_before( ref[ len( ARCHIVE_REF_PREFIX ) + 1: ], cutoff ):
            continue
        drop = _git( run, project_root, "update-ref", "-d", ref )
        if drop[ "success" ]:
            out[ "refs_deleted" ].append( ref )
        else:
            out[ "errors" ].append( f"could not delete {ref}: {drop[ 'stderr' ]}" )

    try:
        names = sorted( os.listdir( root ) ) if os.path.isdir( root ) else []
    except OSError as e:
        names = []
        out[ "errors" ].append( f"could not list {root}: {e}" )
    for name in names:
        path = os.path.join( root, name )
        if not _dated_before( name, cutoff ) or not os.path.isdir( path ) or os.path.islink( path ):
            continue
        try:
            shutil.rmtree( path )
            out[ "folders_deleted" ].append( path )
        except OSError as e:
            out[ "errors" ].append( f"could not remove {path}: {e}" )
    return out


BRANCH_GRACE_HOURS = 24.0


def branch_created_ts( project_root: str, branch: str, run: Callable ) -> Optional[ float ]:
    """
    When the branch was created, from the oldest entry of its reflog.

    Ensures:
        - returns the epoch seconds of the oldest `refs/heads/<branch>` reflog entry
        - returns 0.0 when the reflog is readable but empty — reflogs expire (90 days by
          default), so a branch with none is old, not new
        - returns None when the reflog cannot be read — "could not look", which the caller
          must treat as too young to delete
        - never raises
    """
    # `%gd` with --date=unix prints `<name>@{<entry epoch>}` — the time the ENTRY was
    # written. `%ct` would print the commit's time, and a branch made today at an old
    # commit would read as old (measured 2026-09-29).
    res = _git( run, project_root, "reflog", "show", "--date=unix", "--format=%gd", f"refs/heads/{branch}", "--" )
    if not res[ "success" ]:
        return None
    stamps = [ m.group( 1 ) for m in re.finditer( r"@\{(\d+)\}", res[ "stdout" ] ) ]
    return float( stamps[ -1 ] ) if stamps else 0.0


def sweep_merged_branches(
    project_root : Optional[ str ]      = None,
    run          : Optional[ Callable ] = None,
    delete_fn    : Optional[ Callable ] = None,
    grace_hours  : float                = BRANCH_GRACE_HOURS,
    now_ts       : Optional[ float ]    = None,
) -> dict:
    """
    Retire every local branch no worktree has checked out, then expire the archive.

    Merged branches are deleted and the rest are archived. This reaches the branches a tree reap
    never touches, since the janitor otherwise deleted a branch only when it removed that branch's tree.

    Requires:
        - project_root is None (meaning cu.get_project_root()) or a repo's main working tree
        - delete_fn is None (meaning retire_branch) or injected with its signature

    Ensures:
        - candidates are every `refs/heads` branch, minus protected and checked-out
          branches. An unmerged one is archived by retire_branch, so it leaves the list on
          the first poll after its grace and an ordinary poll reports only real work
        - a branch created less than grace_hours ago (branch_created_ts), or whose age
          cannot be read, is skipped. A brand-new branch sits at the target's tip and so
          reads as "merged" before anyone has committed to it
        - each candidate goes through retire_branch, which re-checks protection, checkout
          and ancestry: a merged branch is deleted with `git branch -d`, an unmerged one
          moves to refs/archive. No commit is lost either way
        - "archive_sweep" carries sweep_archive's summary (refs and evacuation folders past
          the retention window), and its errors are not fatal to the branch sweep
        - returns { target, deleted: [ outcome ], kept: [ outcome ], error, archive_sweep };
          error is set (and nothing is deleted) when the main tree's branch or the listings
          cannot be read
        - never pushes, never touches a remote ref, never raises
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()
    delete_fn    = delete_fn if delete_fn is not None else retire_branch
    now_ts       = now_ts if now_ts is not None else datetime.now( timezone.utc ).timestamp()
    out          = { "target": None, "deleted": [], "kept": [], "error": None, "archive_sweep": None }
    try:
        target = main_worktree_branch( list_worktrees( project_root, run=run ) )
        out[ "target" ] = target
        if not target:
            out[ "error" ] = "main tree has no branch checked out; nothing to measure against"
            return out
        held   = checked_out_branches( project_root, run )
        merged = _git( run, project_root, "for-each-ref", "--format=%(refname:short)", "refs/heads" )
        if held is None or not merged[ "success" ]:
            out[ "error" ] = f"could not list branches: {merged[ 'stderr' ] or 'worktree list failed'}"
            return out
        for branch in merged[ "stdout" ].split():
            if is_protected_branch( branch, target ) or branch in held:
                continue
            created = branch_created_ts( project_root, branch, run )
            if created is None or now_ts - created < grace_hours * 3600:
                continue
            outcome = delete_fn( project_root, branch, target, run=run )
            out[ "deleted" if outcome[ "deleted" ] else "kept" ].append( outcome )
        out[ "archive_sweep" ] = sweep_archive( project_root, run=run,
                                                now=datetime.fromtimestamp( now_ts, timezone.utc ) )
    except Exception as e:
        out[ "error" ] = f"branch sweep raised: {e}"
    return out


# ==========================================================================
# Seat trees — locked while the seat lives, swept once it is provably gone
# ==========================================================================
#
# `provision-seat-worktree.sh` puts every spawned seat's tree in this lane and locks it
# with reason `lupin-seat:<tmux session name>` (Rick, 2026-09-14, row 033538f6). A live
# seat can sit idle past the age threshold, so the lock is what keeps the janitor off a
# seat that is still working. The janitor reaps a seat-locked tree only when BOTH
# liveness signals say the seat is gone — its tmux session is absent AND no process has
# its cwd inside the tree (Mr. Radio's second signal) — and it is idle past the threshold.
# Every uncertainty counts as ALIVE: a janitor that cannot tell must not reap.

SEAT_LOCK_PREFIX = "lupin-seat:"
TMUX_ABSENT_MARKS = ( "can't find session", "no server running", "error connecting" )


def _tmux_session_absent( session_name: str ) -> bool:
    """
    Does tmux positively say this session does not exist?

    Ensures:
        - True only when `tmux has-session` exits non-zero with a message saying the
          session or the server is absent
        - False when the session exists, when tmux is not installed, or on any other
          error (cannot prove absence, so not absent); never raises
    """
    try:
        proc = subprocess.run( [ "tmux", "has-session", "-t", f"={session_name}" ],
                               capture_output=True, text=True, timeout=10 )
    except Exception:
        return False
    if proc.returncode == 0:
        return False
    stderr = ( proc.stderr or "" ).lower()
    return any( mark in stderr for mark in TMUX_ABSENT_MARKS )


def _process_cwd_inside( path: str, proc_root: str = "/proc" ) -> Optional[ bool ]:
    """
    Is any live process standing inside `path`?

    Ensures:
        - True when some /proc/<pid>/cwd resolves to `path` or below it
        - False when /proc was readable and no process is inside
        - None when /proc itself cannot be listed (cannot prove nobody is inside)
        - a single unreadable pid (exited, or another user's) is skipped, not fatal
        - never raises
    """
    cwds = live_process_cwds( proc_root )
    return None if cwds is None else cwd_inside( path, cwds )


def live_process_cwds( proc_root: str = "/proc" ) -> Optional[ set ]:
    """
    Where every live process is standing, read once.

    Ensures:
        - returns the set of real paths that some /proc/<pid>/cwd resolves to
        - returns None when /proc cannot be listed (cannot prove nobody is inside)
        - a single unreadable pid (exited, or another user's) is skipped, not fatal
        - never raises
    """
    try:
        pids = [ p for p in os.listdir( proc_root ) if p.isdigit() ]
    except OSError:
        return None
    cwds = set()
    for pid in pids:
        try:
            cwds.add( os.path.realpath( os.readlink( os.path.join( proc_root, pid, "cwd" ) ) ) )
        except OSError:
            continue
    return cwds


def cwd_inside( path: str, cwds: set ) -> bool:
    """
    Does any of these working directories sit in `path` or below it?

    Ensures:
        - a directory counts when it is `path` itself or under `path` + a separator, so a sibling
          whose name only starts the same does not
    """
    target = os.path.realpath( path )
    return any( c == target or c.startswith( target + os.sep ) for c in cwds )


def seat_is_alive( session_name: str, path: str ) -> bool:
    """
    The janitor's liveness verdict for a seat-locked tree. Fails closed.

    Ensures:
        - False (the seat is gone) only when tmux positively reports the session absent
          and /proc was readable and no process has its cwd inside `path`
        - True in every other case, including any error; never raises
    """
    if not _tmux_session_absent( session_name ):
        return True
    inside = _process_cwd_inside( path )
    return inside is None or inside


def reconcile_worktrees(
    sandbox_root        : Optional[ str ]      = None,
    project_root        : Optional[ str ]      = None,
    age_threshold_hours : float                = 6.0,
    run                 : Optional[ Callable ] = None,
    now                 : Optional[ datetime ] = None,
    drain_fn            : Optional[ Callable ] = None,
    list_fn             : Optional[ Callable ] = None,
    age_fn              : Optional[ Callable ] = None,
    seat_alive_fn       : Optional[ Callable ] = None,
    branch_fn           : Optional[ Callable ] = None,
    debug               : bool                 = False,
    evacuation_root     : Optional[ str ]      = None,
    cwds_fn             : Optional[ Callable ] = None,
) -> dict:
    """
    Janitor backstop: drain_then_remove every abandoned sandbox worktree.

    Abandoned (safe to retire) means: under sandbox_root, not the main tree, not git-locked, and idle
    longer than age_threshold_hours. No dir-to-session map is needed: the drain commits WIP and keeps
    the branch, so retiring a quiet live tree loses no work. A branch carrying WIP is never merged, so it is kept.

    Requires:
        - sandbox_root is None (meaning <project_root>/.claude/worktrees), an absolute
          path, or a project-root-relative path
        - run / drain_fn / list_fn / age_fn / seat_alive_fn / branch_fn / cwds_fn are None (real
          impls) or injected (testing); seat_alive_fn( session_name, path ) -> bool; cwds_fn() -> set or None;
          branch_fn( project_root, branch, target, run= ) -> delete_merged_branch's dict

    Ensures:
        - this is the only lever for hard-killed or harness-spawned workers that never reap themselves
        - locked worktrees are always skipped as a deliberate protection signal, except a seat
          tree (lock reason `lupin-seat:<session>`) whose seat is provably gone (see seat_is_alive)
        - returns { swept: [ {path, result} ], skipped: [ {path, reason} ],
          errors: [ str ], branches_deleted: [ outcome ], branches_kept: [ outcome ] }
        - a locked tree with any other reason (or none) is skipped as "locked"
        - a seat-locked tree is skipped as "seat_alive" while seat_alive_fn says so,
          and as "active_<h>h" while younger than the threshold; otherwise it is
          unlocked and drained, and if the drain does not remove it the lock is put
          back with its original reason (an unlocked survivor would lose the
          protection the next poll relies on)
        - a tree some live process stands in (its /proc cwd, never a pid) is skipped "process_cwd_inside"; no /proc: "process_cwd_unknown"
        - delegates removal to drain_then_remove, so it never pushes
        - the default drain is handed evacuation_root (None meaning <project_root>/io/worktree-evacuated),
          so a tree holding ignored data is emptied into a dated folder there and removed instead of
          refused; the default branch_fn is retire_branch, so an unmerged branch is archived under
          refs/archive (kept_reason "archived", listed in branches_kept) instead of staying in the list
        - after a drain that removed the tree, its branch goes to branch_fn, measured against the main
          tree's branch (main_worktree_branch). A merged branch is deleted with `git branch -d` and
          listed in branches_deleted; any other outcome is listed in branches_kept, never forced.
          The outcome is also attached to the swept entry's result as branch_outcome.
          A tree that was not removed keeps its branch untouched. The branch name is the
          record's (from the full `refs/heads/` ref) or the drain's rescue branch
        - swallow-safe: one bad worktree is captured in errors[], never raised
          (an observer/poll loop must not die on a single bad tree)
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()
    if sandbox_root is None:
        sandbox_root = os.path.join( project_root, ".claude/worktrees" )
    elif not os.path.isabs( sandbox_root ):
        sandbox_root = os.path.join( project_root, sandbox_root )

    # Row aec2319f: the janitor moves a tree's ignored data to the main tree's evacuation
    # folder instead of refusing the tree. An injected drain_fn is called as before.
    evacuation_root = evacuation_root if evacuation_root is not None else default_evacuation_root( project_root )
    if drain_fn is None:
        drain_fn = lambda path, **kw: drain_then_remove( path, evacuation_root=evacuation_root, **kw )
    list_fn  = list_fn  if list_fn  is not None else ( lambda: list_worktrees( project_root, run=run ) )
    now_dt   = now if now is not None else datetime.now( timezone.utc )
    now_ts   = now_dt.timestamp()
    age_fn   = age_fn if age_fn is not None else ( lambda p: _newest_mtime_age_hours( p, now_ts ) )
    seat_alive_fn = seat_alive_fn if seat_alive_fn is not None else seat_is_alive
    cwds_fn       = cwds_fn       if cwds_fn       is not None else live_process_cwds
    seen_cwds     = []              # filled on first use: the /proc scan runs once per poll, not once per tree
    branch_fn     = branch_fn     if branch_fn     is not None else retire_branch

    sandbox_abs = os.path.abspath( sandbox_root )
    out = { "swept": [], "skipped": [], "errors": [], "branches_deleted": [], "branches_kept": [] }

    records = list_fn()
    target  = main_worktree_branch( records )
    for rec in records:
        path = rec.get( "path" )
        try:
            if not path:
                continue
            if rec.get( "is_main" ):
                out[ "skipped" ].append( { "path": path, "reason": "main_worktree" } ); continue
            if not os.path.abspath( path ).startswith( sandbox_abs + os.sep ):
                out[ "skipped" ].append( { "path": path, "reason": "outside_sandbox" } ); continue
            lock_reason = rec.get( "lock_reason" ) or ""
            seat_lock   = rec.get( "locked" ) and lock_reason.startswith( SEAT_LOCK_PREFIX )
            if rec.get( "locked" ) and not seat_lock:
                out[ "skipped" ].append( { "path": path, "reason": "locked" } ); continue
            if seat_lock and seat_alive_fn( lock_reason[ len( SEAT_LOCK_PREFIX ): ], path ):
                out[ "skipped" ].append( { "path": path, "reason": "seat_alive" } ); continue
            if not seen_cwds: seen_cwds.append( cwds_fn() )
            if seen_cwds[ 0 ] is None:
                out[ "skipped" ].append( { "path": path, "reason": "process_cwd_unknown" } ); continue
            if cwd_inside( path, seen_cwds[ 0 ] ):
                out[ "skipped" ].append( { "path": path, "reason": "process_cwd_inside" } ); continue
            age = age_fn( path )
            if age < age_threshold_hours:
                out[ "skipped" ].append( { "path": path, "reason": f"active_{round( age, 2 )}h" } ); continue
            if seat_lock:
                unlock = _git( run, project_root, "worktree", "unlock", path )
                if not unlock[ "success" ]:
                    out[ "errors" ].append( f"{path}: unlock failed, not drained: {unlock[ 'stderr' ]}" ); continue
            result = drain_fn( path, project_root=project_root, run=run, now=now_dt, debug=debug )
            if seat_lock and not result.get( "removed" ):
                relock = _git( run, project_root, "worktree", "lock", "--reason", lock_reason, path )
                if not relock[ "success" ]:
                    out[ "errors" ].append( f"{path}: drain did not remove it AND re-lock failed — "
                                            f"the seat tree is now unprotected: {relock[ 'stderr' ]}" )
            if result.get( "removed" ):
                # The branch comes from the FULL ref in `worktree list --porcelain`, or is the
                # rescue branch the drain itself named. Never the drain's `--abbrev-ref`
                # value: with a same-named tag that reads `heads/<name>`, and a merged branch
                # was kept as "merge_check_failed" (Rachel via María, 2026-09-18).
                branch  = result.get( "rescue_branch" ) or rec.get( "branch" )
                outcome = branch_fn( project_root, branch, target, run=run )
                result[ "branch_outcome" ] = outcome
                out[ "branches_deleted" if outcome[ "deleted" ] else "branches_kept" ].append( outcome )
            out[ "swept" ].append( { "path": path, "result": result } )
            if debug: print( f"[worktree_reaper] janitor swept idle worktree ({round( age, 1 )}h): {path}" )
        except Exception as e:
            out[ "errors" ].append( f"{path}: {e}" )

    return out


# ==========================================================================
# Quick smoke test (no live git — exercises the path-absent + injected-runner
# branches so it is safe to run anywhere).
# ==========================================================================

def quick_smoke_test():
    """Quick smoke test for drain_then_remove using an injected fake runner."""
    from types import SimpleNamespace

    cu.print_banner( "worktree_reaper Smoke Test", prepend_nl=True )
    results = []

    # Test 1: path absent -> skipped, no removal, no error.
    r1 = drain_then_remove( "/tmp/definitely-not-a-real-worktree-xyz", project_root="/tmp" )
    ok1 = ( r1[ "removed" ] is False and r1[ "skipped_reason" ] == "path_absent" )
    results.append( ( "path_absent skip", ok1 ) )

    # Test 2: clean worktree (no WIP) -> remove succeeds, no WIP commit.
    calls = []
    def fake_clean( argv, cwd=None, timeout=60 ):
        calls.append( argv )
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout="", stderr="" )   # clean
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    # os.path.exists guard: point at a dir we know exists.
    r2 = drain_then_remove( "/tmp", project_root="/tmp", run=fake_clean )
    pushed = any( "push" in a for a in calls )
    branch_deleted = any( ( "branch" in a and ( "-d" in a or "-D" in a ) ) for a in calls )
    ok2 = ( r2[ "removed" ] and r2[ "wip_committed" ] is False
            and r2[ "branch" ] == "wt-feature" and not pushed and not branch_deleted )
    results.append( ( "clean remove, no push, branch kept", ok2 ) )

    # Test 3: dirty worktree -> WIP committed BEFORE remove, branch preserved.
    calls3 = []
    def fake_dirty( argv, cwd=None, timeout=60 ):
        calls3.append( argv )
        sub = argv[ 1 ] if len( argv ) > 1 else ""
        if sub == "rev-parse" and "--abbrev-ref" in argv:
            return SimpleNamespace( returncode=0, stdout="wt-feature\n", stderr="" )
        if sub == "status":
            return SimpleNamespace( returncode=0, stdout=" M src/foo.py\n", stderr="" )
        if sub == "rev-parse":   # HEAD sha after commit
            return SimpleNamespace( returncode=0, stdout="abc1234\n", stderr="" )
        return SimpleNamespace( returncode=0, stdout="", stderr="" )
    r3 = drain_then_remove( "/tmp", project_root="/tmp", run=fake_dirty )
    order_ok = ( [ a[ 1 ] for a in calls3 ].index( "commit" )
                 < [ a[ 1 ] for a in calls3 ].index( "worktree" ) )
    ok3 = ( r3[ "wip_committed" ] and r3[ "wip_sha" ] == "abc1234"
            and r3[ "removed" ] and order_ok
            and not any( "push" in a for a in calls3 ) )
    results.append( ( "dirty: WIP committed before remove, no push", ok3 ) )

    print()
    for name, ok in results:
        print( f"  [{'PASS' if ok else 'FAIL'}] {name}" )
    passed = sum( 1 for _, ok in results if ok )
    print( f"\n  {passed}/{len( results )} smoke checks passed" )


if __name__ == "__main__":
    quick_smoke_test()
