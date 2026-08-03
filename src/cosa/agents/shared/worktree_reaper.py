"""
Worktree drain-then-remove reaper (Worktree Lifecycle Contract, 2026-06-22).

The shared, single-source-of-truth helper that safely retires a git worktree
WITHOUT ever losing work and WITHOUT ever pushing. It is the one function the
three reap surfaces all call:

    1. WorktreeContext.__aexit__  (clean Agent/TFE/BFE exit — path A/B in-repo)
    2. session_spawner.dismiss_sessions  (manager-harvest reap — path A in-repo)
    3. heartbeat_arbiter janitor reconcile  (backstop for hard-killed / harness-
       spawned workers that never run their own teardown — the ONLY lever for
       worktrees not reachable from repo code)

Anchor principle (Rick's no-push law, 2026-06-22): preservation is PURELY LOCAL.
A worktree DIRECTORY is disposable (it holds node_modules/.venv/build — the disk
hog); a BRANCH ref is durable and lives in the shared local object store. So:

    commit any WIP to the branch  ->  git worktree remove (dir gone, branch kept)
    ->  NEVER push, NEVER delete the branch

This makes "merged or resumed, never lost" true on local refs alone. The branch
survives `git worktree remove`, so the work is fully resumable later via
`git worktree add <branch>`, or mergeable locally after review.

Design decisions ratified by Rick (guided walkthrough, 2026-06-22):
    D2 — this is the shared utility BOTH reap paths + the janitor call.
    D4 — WIP is ALWAYS auto-committed (labeled), never silently discarded.
    D5 — branches are KEPT; this util removes DIRS only, never branches.

See: planning-is-prompting -> src/rnd/2026.06.22-worktree-lifecycle-contract.md
"""

import os
import subprocess
from datetime import datetime, timezone
from typing import Callable, Optional

import cosa.utils.util as cu


WIP_COMMIT_PREFIX = "WIP: auto-saved at reap"
RESCUE_BRANCH_PREFIX = "wt-rescue"

# The Lupin server containers' canonical LUPIN_ROOT (docker-compose.yml). Used to
# detect an in-container reap so we never `git worktree prune` from inside a
# container (bug 47ac0e50 — see _is_in_container).
CONTAINER_PROJECT_ROOT = "/var/lupin"


def _is_in_container( project_root: str ) -> bool:
    """
    True when this reaper is running INSIDE a Lupin server container.

    Bug 47ac0e50: the :7999/:8000 containers bind-mount ./.git but NOT
    lupin-worktrees/, so a `git worktree prune` run in-container reads every
    host-registered worktree's gitdir as a missing /mnt/DATA01 path and prunes
    the ENTIRE shared registry — wiping every host lane at once. The container's
    canonical LUPIN_ROOT is /var/lupin (docker-compose.yml), so
    project_root == /var/lupin — or an explicit truthy LUPIN_IN_CONTAINER env
    sentinel — is the discriminator that gates the in-container prune OFF.

    Requires:
        - project_root is the resolved main-repo path a prune would run in

    Ensures:
        - returns True iff LUPIN_IN_CONTAINER is set truthy (1/true/yes, case-
          insensitive) OR project_root == CONTAINER_PROJECT_ROOT
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
    """
    return subprocess.run(
        argv,
        cwd            = cwd,
        capture_output = True,
        text           = True,
        timeout        = timeout,
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


def drain_then_remove(
    worktree_path : str,
    project_root  : Optional[ str ]      = None,
    run           : Optional[ Callable ] = None,
    now           : Optional[ datetime ] = None,
    debug         : bool                 = False,
) -> dict:
    """
    Safely retire a git worktree: commit any WIP locally, then remove the DIR,
    keeping the branch ref. Never pushes; never deletes a branch.

    Requires:
        - worktree_path is the absolute path to the worktree directory
        - project_root is None (resolved via cu.get_project_root()) or the
          absolute path to the main repo's working tree
        - run is None (real git via subprocess) or an injected runner callable
          with signature run( argv, cwd=, timeout= ) for testing

    Ensures:
        - if worktree_path does not exist: returns removed=False,
          skipped_reason="path_absent" (nothing to do; caller may prune)
        - if uncommitted edits exist: they are committed to the worktree's
          branch as a labeled WIP commit BEFORE removal (D4 — never discarded);
          a detached HEAD is first given a rescue branch so the commit is
          reachable after removal
        - the worktree DIRECTORY is removed (git worktree remove); the BRANCH
          ref is preserved (D5)
        - NEVER runs `git push` and NEVER runs `git branch -d/-D`
        - returns a result dict (below); never raises — every git failure is
          captured in errors[] so a reaper loop is not derailed by one bad tree

    Returns:
        {
          "worktree_path" : str,
          "branch"        : str | None,   # branch the work is preserved on
          "wip_committed" : bool,
          "wip_sha"       : str | None,
          "rescue_branch" : str | None,   # set iff HEAD was detached
          "removed"       : bool,         # dir successfully removed
          "skipped_reason": str | None,
          "errors"        : [ str, ... ],
        }
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()

    result = {
        "worktree_path"  : worktree_path,
        "branch"         : None,
        "wip_committed"  : False,
        "wip_sha"        : None,
        "rescue_branch"  : None,
        "removed"        : False,
        "skipped_reason" : None,
        "errors"         : [],
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
            result[ "errors" ].append( f"rescue-branch create failed: {sw[ 'stderr' ]}" )

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
          is_main (bool) }; is_main is True for the primary working tree
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
            elif line.startswith( "locked" ):    rec[ "locked" ] = True
        if rec.get( "path" ):
            rec.setdefault( "branch", None )
            rec.setdefault( "locked", False )
            rec[ "is_main" ] = ( os.path.abspath( rec[ "path" ] ) == os.path.abspath( project_root ) )
            records.append( rec )
    return records


def _newest_mtime_age_hours( path: str, now_ts: float ) -> float:
    """
    Hours since the most-recently-modified non-vendored file under `path`.

    Ensures:
        - walks `path` skipping .git / node_modules / .venv / venv / __pycache__
          (vendored/build noise — a worker's SOURCE edits land outside these)
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


def reconcile_worktrees(
    sandbox_root        : Optional[ str ]      = None,
    project_root        : Optional[ str ]      = None,
    age_threshold_hours : float                = 6.0,
    run                 : Optional[ Callable ] = None,
    now                 : Optional[ datetime ] = None,
    drain_fn            : Optional[ Callable ] = None,
    list_fn             : Optional[ Callable ] = None,
    age_fn              : Optional[ Callable ] = None,
    debug               : bool                 = False,
) -> dict:
    """
    Janitor backstop (Worktree Lifecycle Contract §4b): drain_then_remove every
    ABANDONED sandbox worktree. This is the ONLY lever for hard-killed / harness-
    spawned workers that never run their own reap teardown.

    A worktree is abandoned (safe to retire) iff ALL hold: it lives under
    sandbox_root, is NOT the main working tree, is NOT git-locked, and has been
    idle longer than age_threshold_hours (newest non-vendored file older than
    the threshold).

    Safety (why no dir->session mapping is needed): drain_then_remove commits any
    WIP to the branch and KEEPS the branch, so even a false-positive retire of a
    quiet-but-live worktree loses NO work — the branch + WIP survive and the dir
    is re-addable via `git worktree add <branch>`. Locked worktrees are always
    skipped (a deliberate protection signal).

    Requires:
        - sandbox_root is None (→ <project_root>/.claude/worktrees), an absolute
          path, or a project-root-relative path
        - run / drain_fn / list_fn / age_fn are None (real impls) or injected
          (testing)

    Ensures:
        - returns { swept: [ {path, result} ], skipped: [ {path, reason} ],
          errors: [ str ] }
        - delegates removal to drain_then_remove → NEVER pushes, NEVER deletes a
          branch
        - swallow-safe: one bad worktree is captured in errors[], never raised
          (an observer/poll loop must not die on a single bad tree)
    """
    run          = run if run is not None else _default_run
    project_root = project_root if project_root is not None else cu.get_project_root()
    if sandbox_root is None:
        sandbox_root = os.path.join( project_root, ".claude/worktrees" )
    elif not os.path.isabs( sandbox_root ):
        sandbox_root = os.path.join( project_root, sandbox_root )

    drain_fn = drain_fn if drain_fn is not None else drain_then_remove
    list_fn  = list_fn  if list_fn  is not None else ( lambda: list_worktrees( project_root, run=run ) )
    now_dt   = now if now is not None else datetime.now( timezone.utc )
    now_ts   = now_dt.timestamp()
    age_fn   = age_fn if age_fn is not None else ( lambda p: _newest_mtime_age_hours( p, now_ts ) )

    sandbox_abs = os.path.abspath( sandbox_root )
    out = { "swept": [], "skipped": [], "errors": [] }

    for rec in list_fn():
        path = rec.get( "path" )
        try:
            if not path:
                continue
            if rec.get( "is_main" ):
                out[ "skipped" ].append( { "path": path, "reason": "main_worktree" } ); continue
            if not os.path.abspath( path ).startswith( sandbox_abs + os.sep ):
                out[ "skipped" ].append( { "path": path, "reason": "outside_sandbox" } ); continue
            if rec.get( "locked" ):
                out[ "skipped" ].append( { "path": path, "reason": "locked" } ); continue
            age = age_fn( path )
            if age < age_threshold_hours:
                out[ "skipped" ].append( { "path": path, "reason": f"active_{round( age, 2 )}h" } ); continue
            result = drain_fn( path, project_root=project_root, run=run, now=now_dt, debug=debug )
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
