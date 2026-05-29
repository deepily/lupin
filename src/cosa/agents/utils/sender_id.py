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
from pathlib import Path


# Short-name aliases applied after basename resolution.
# Preserves legacy canonical short names (e.g. "plan" for "planning-is-prompting")
# so sender_id routing stays stable across the substring->walk-up refactor.
_PROJECT_ALIASES = {
    "planning-is-prompting" : "plan",
}


def detect_project() -> str:
    """
    Detect project name as the basename of the nearest enclosing
    git repository — walking up from cwd until a .git entry is found.

    Requires:
        - Current working directory is accessible

    Ensures:
        - Returns lowercase project name (basename of git repo root)
        - Walks up from cwd; first ancestor containing .git wins
        - .git may be a directory (normal repo), file (worktree/submodule
          gitlink), or any other FS entry — any form satisfies the check
        - Handles nested repos correctly: cwd inside src/cosa (which has
          its own .git) returns "cosa", not "lupin"
        - Falls back to basename of cwd if no .git ancestor is found
        - Applies _PROJECT_ALIASES for legacy short names (e.g.
          "planning-is-prompting" -> "plan")

    Returns:
        str: Detected project name
    """
    cwd = Path( os.getcwd() ).resolve()
    for candidate in [ cwd, *cwd.parents ]:
        if ( candidate / ".git" ).exists():
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
