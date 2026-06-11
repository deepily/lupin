#!/usr/bin/env python3
"""
Shared Sender ID Construction for COSA Agent Notifications.

Provides project detection from the current working directory and
sender_id string construction. Used by all agent cosa_interface/
notification_profile modules and the MCP server.

The sender_id format is: {agent_type}@{project}.deepily.ai[#{suffix}]

Examples:
    deep.research@lupin.deepily.ai
    podcast.gen@lupin.deepily.ai#cli
    swe.lead@lupin.deepily.ai#abc123
    claude.code@lupin.deepily.ai#a1b2c3d4
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


# Short-name aliases applied after basename resolution.
# Preserves legacy canonical short names (e.g. "plan" for "planning-is-prompting")
# so sender_id routing stays stable across the substring->walk-up refactor.
_PROJECT_ALIASES = {
    "planning-is-prompting" : "plan",
}


def _worktree_owner_basename( candidate: Path ) -> Optional[ str ]:
    """
    Resolve the MAIN repo basename when `candidate` is a git worktree.

    A worktree and a submodule both store `.git` as a FILE (a gitlink), so the
    bare walk-up in detect_project() cannot tell them apart. Git itself can:
    `git rev-parse --git-common-dir` reports the SHARED main-repo `.git` for a
    worktree (basename ".git") but the per-submodule `.git/modules/<name>` for a
    submodule (basename != ".git"). That distinction is the disambiguator.

    Requires:
        - candidate is a Path whose `.git` child is a file (a gitlink); the
          caller guarantees this before invoking

    Ensures:
        - Returns the lowercased basename of the MAIN repo root when candidate
          is a linked worktree (e.g. a worktree of /…/lupin -> "lupin")
        - Returns None when candidate is NOT a worktree — i.e. a submodule
          gitlink (common-dir basename != ".git"), git is unavailable, git
          returns non-zero, or stdout is empty — so the caller falls back to
          the existing basename behavior (fail toward existing behavior)
        - Never raises: every subprocess failure mode maps to None

    Args:
        candidate: Directory whose `.git` gitlink file is being resolved

    Returns:
        Optional[str]: MAIN repo basename (lowercased) for a worktree, else None
    """
    try:
        result = subprocess.run(
            [ "git", "rev-parse", "--git-common-dir" ],
            cwd            = str( candidate ),
            capture_output = True,
            text           = True,
            timeout        = 5
        )
    except ( OSError, subprocess.SubprocessError ):
        return None

    if result.returncode != 0:
        return None

    raw = result.stdout.strip()
    if not raw:
        return None

    common_dir = Path( raw )
    if not common_dir.is_absolute():
        common_dir = ( candidate / common_dir ).resolve()

    # Worktrees share the main repo's `<main>/.git` (basename ".git"); submodules
    # report `<main>/.git/modules/<name>` (basename != ".git"). Only the former
    # should resolve to a different (main-repo) identity.
    if common_dir.name != ".git":
        return None

    return common_dir.parent.name.lower()


def _dangling_gitlink_owner_basename( git_entry: Path ) -> Optional[ str ]:
    """
    Static-parse fallback: resolve the MAIN repo basename from the gitlink
    FILE's content when live git cannot answer.

    `git rev-parse --git-common-dir` fails ("not a git repository") in a
    worktree whose `<main>/.git/worktrees/<name>` admin dir has been deleted
    (e.g. an over-eager prune while the worktree is still in use — the
    2026-06-11 fleet incident). The gitlink file itself still says where the
    admin dir WAS:

        gitdir: <main>/.git/worktrees/<name>

    which is enough to recover the main-repo identity WITHOUT git: the path
    segment before `/.git/worktrees/` is the main repo root. Submodule
    gitlinks point at `<main>/.git/modules/<name>` instead and return None
    (same submodule semantics as the live-git path).

    Requires:
        - git_entry is a Path to a `.git` FILE (a gitlink); caller guarantees

    Ensures:
        - Returns the lowercased main-repo basename when the gitlink targets
          `<main>/.git/worktrees/<name>` (whether or not that dir still exists)
        - Returns None for submodule gitlinks, unreadable/malformed gitlink
          files, or a `.git/worktrees` with no parent segment
        - Never raises: every failure mode maps to None
    """
    try:
        content = git_entry.read_text()
    except OSError:
        return None

    if not content.startswith( "gitdir:" ):
        return None

    target = Path( content[ len( "gitdir:" ): ].strip() )
    if not target.is_absolute():
        target = ( git_entry.parent / target ).resolve()

    parts = target.parts
    for i in range( 1, len( parts ) - 1 ):
        if parts[ i ] == ".git" and parts[ i + 1 ] == "worktrees":
            return parts[ i - 1 ].lower()
    return None


def detect_project() -> str:
    """
    Detect project name as the basename of the nearest enclosing
    git repository — walking up from cwd until a .git entry is found,
    with worktree-aware resolution to the MAIN repo.

    Requires:
        - Current working directory is accessible

    Ensures:
        - Returns lowercase project name (basename of git repo root)
        - Walks up from cwd; first ancestor containing .git wins
        - .git may be a directory (normal repo), file (worktree/submodule
          gitlink), or any other FS entry — any form satisfies the check
        - WORKTREE-AWARE: when the found .git is a gitlink FILE and git
          reports a worktree, returns the MAIN repo basename (e.g. a worktree
          of lupin returns "lupin", NOT the worktree dir name). This prevents
          the MCP server from mis-detecting worktree crews as bogus projects.
        - DANGLING-GITLINK-SAFE: when live git CANNOT answer (the worktree's
          admin dir under `<main>/.git/worktrees/` was deleted while the
          worktree dir survives — 2026-06-11 fleet incident), the gitlink
          file's `gitdir:` target is parsed statically and still yields the
          MAIN repo basename. A broken worktree never degrades to its own
          dir basename (which spammed urgent "no credentials for project
          'sam-debt-sweep'" notifications).
        - Handles nested repos correctly: cwd inside src/cosa (which has
          its own .git gitlink) still returns "cosa", not "lupin" — submodule
          gitlinks are NOT treated as worktrees
        - Normal repos (.git is a directory) keep a zero-subprocess fast path
        - Falls back to basename of cwd if no .git ancestor is found
        - Applies _PROJECT_ALIASES for legacy short names (e.g.
          "planning-is-prompting" -> "plan")

    Returns:
        str: Detected project name
    """
    cwd = Path( os.getcwd() ).resolve()
    for candidate in [ cwd, *cwd.parents ]:
        git_entry = candidate / ".git"
        if git_entry.exists():
            if git_entry.is_file():
                owner = _worktree_owner_basename( candidate )
                if owner is None:
                    # Live git failed — dangling worktree admin dir. Parse the
                    # gitlink content directly so a broken worktree still
                    # resolves to its MAIN repo, never to its own basename.
                    owner = _dangling_gitlink_owner_basename( git_entry )
                if owner is not None:
                    return _PROJECT_ALIASES.get( owner, owner )
            name = candidate.name.lower()
            return _PROJECT_ALIASES.get( name, name )
    basename = cwd.name.lower()
    return _PROJECT_ALIASES.get( basename, basename )


def build_sender_id( agent_type: str, project: str = None, suffix: str = None ) -> str:
    """
    Construct a sender_id string for notification routing.

    Requires:
        - agent_type is a non-empty string (e.g., "deep.research", "swe.lead")

    Ensures:
        - Returns sender_id in format: {agent_type}@{project}.deepily.ai[#{suffix}]
        - If project is None, auto-detects from cwd
        - If suffix is provided, appends #{suffix}

    Args:
        agent_type: The agent identifier prefix (e.g., "deep.research", "podcast.gen")
        project: Project name override (None = auto-detect from cwd)
        suffix: Optional suffix after # (e.g., session hash, "cli")

    Returns:
        str: Fully-qualified sender_id string

    Examples:
        build_sender_id( "deep.research" )
            -> "deep.research@lupin.deepily.ai"

        build_sender_id( "podcast.gen", suffix="cli" )
            -> "podcast.gen@lupin.deepily.ai#cli"

        build_sender_id( "swe.lead", project="lupin", suffix="abc123" )
            -> "swe.lead@lupin.deepily.ai#abc123"
    """
    if project is None:
        project = detect_project()

    base = f"{agent_type}@{project}.deepily.ai"

    if suffix:
        return f"{base}#{suffix}"

    return base


def _assert_detect_for_cwd( probe_path, expected ):
    """Assert detect_project() returns `expected` when cwd == probe_path."""
    from unittest.mock import patch
    with patch( "os.getcwd", return_value=str( probe_path ) ):
        actual = detect_project()
    assert actual == expected, f"cwd={probe_path} expected={expected!r} got={actual!r}"


def quick_smoke_test():
    """Quick smoke test for sender_id module."""
    import cosa.utils.util as cu
    import tempfile

    cu.print_banner( "Sender ID Utilities Smoke Test", prepend_nl=True )

    try:
        # Test 1: detect_project returns a string (live cwd)
        print( "Testing detect_project (live cwd)..." )
        project = detect_project()
        assert isinstance( project, str )
        assert len( project ) > 0
        print( f"  Detected project: {project}" )

        # Test 2: detect_project with synthetic nested-repo tree
        print( "Testing detect_project (synthetic nested-repo scenarios)..." )
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp         = Path( tmpdir )
            lupin_root  = tmp / "lupin"
            cosa_dir    = lupin_root / "src" / "cosa"
            mobile_dir  = lupin_root / "src" / "lupin-mobile"
            firefox_dir = lupin_root / "src" / "lupin-plugin-firefox"
            no_repo     = tmp / "no-repo-here"

            # Build tree with nested .git markers
            for d in ( lupin_root, cosa_dir, mobile_dir, firefox_dir ):
                d.mkdir( parents=True, exist_ok=True )
                ( d / ".git" ).mkdir( exist_ok=True )
            no_repo.mkdir( parents=True, exist_ok=True )

            _assert_detect_for_cwd( lupin_root,  "lupin" )
            print( "  /lupin/                         -> lupin (PARENT_OK)" )
            _assert_detect_for_cwd( cosa_dir,    "cosa" )
            print( "  /lupin/src/cosa/                -> cosa (FIX)" )
            _assert_detect_for_cwd( mobile_dir,  "lupin-mobile" )
            print( "  /lupin/src/lupin-mobile/        -> lupin-mobile (FIX)" )
            _assert_detect_for_cwd( firefox_dir, "lupin-plugin-firefox" )
            print( "  /lupin/src/lupin-plugin-firefox -> lupin-plugin-firefox (FIX)" )
            _assert_detect_for_cwd( no_repo,     "no-repo-here" )
            print( "  /no-repo-here/                  -> no-repo-here (basename fallback)" )

        # Test 2b: detect_project with a REAL git worktree (worktree-aware fix)
        print( "Testing detect_project (real git worktree -> MAIN repo)..." )
        with tempfile.TemporaryDirectory() as wt_tmp:
            wt_root = Path( wt_tmp )
            main    = wt_root / "lupin"
            link    = wt_root / "wt-delegation-signal"
            main.mkdir()
            def _git( *args, cwd ):
                subprocess.run(
                    [ "git", *args ], cwd=str( cwd ),
                    check=True, capture_output=True, text=True
                )
            _git( "init", "-q", cwd=main )
            _git( "config", "user.email", "smoke@test.local", cwd=main )
            _git( "config", "user.name", "smoke", cwd=main )
            _git( "commit", "-q", "--allow-empty", "-m", "init", cwd=main )
            _git( "worktree", "add", "-q", str( link ), cwd=main )
            _assert_detect_for_cwd( link, "lupin" )
            print( "  /…/wt-delegation-signal/ (worktree) -> lupin (FIX)" )

        # Test 3: build_sender_id basic
        print( "Testing build_sender_id (basic)..." )
        sid = build_sender_id( "deep.research" )
        assert "deep.research@" in sid
        assert ".deepily.ai" in sid
        print( f"  Basic: {sid}" )

        # Test 4: build_sender_id with suffix
        print( "Testing build_sender_id (with suffix)..." )
        sid = build_sender_id( "podcast.gen", suffix="cli" )
        assert sid.endswith( "#cli" )
        print( f"  With suffix: {sid}" )

        # Test 5: build_sender_id with explicit project
        print( "Testing build_sender_id (explicit project)..." )
        sid = build_sender_id( "swe.lead", project="testproject", suffix="abc123" )
        assert "swe.lead@testproject.deepily.ai#abc123" == sid
        print( f"  Explicit: {sid}" )

        # Test 6: build_sender_id without suffix
        print( "Testing build_sender_id (no suffix)..." )
        sid = build_sender_id( "claude.code.job", project="lupin" )
        assert sid == "claude.code.job@lupin.deepily.ai"
        assert "#" not in sid
        print( f"  No suffix: {sid}" )

        print( "\n  Sender ID utilities smoke test completed successfully" )

    except Exception as e:
        print( f"\n  Smoke test failed: {e}" )
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    quick_smoke_test()
