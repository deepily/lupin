"""
Keep an integration run from leaving new untracked files at the repo root.

A dispatched Claude Code session run from the repo root sometimes writes its file there.
Two helpers: neutral_working_dir picks another directory for the session, and root_litter
lists the untracked files sitting directly in the root. The session guard in the integration
conftest compares root_litter before and after the run and fails on any new name.
"""

import os
import subprocess

SCRATCH_DIR_ENV    = "LUPIN_TEST_SCRATCH_PROJECT_DIR"
SCRATCH_CONTAINER  = "/var/external-projects/scratchpad"


def neutral_working_dir( project_root, fallback_dir, env=None, exists=os.path.isdir ):
    """
    Pick a session working directory: the scratch project, else a temp dir.

    Requires:
        - project_root is the repo root path as a string
        - fallback_dir is a directory the caller made (e.g. a pytest tmp_path)
        - env maps names to values; defaults to os.environ
        - exists is a callable path -> bool

    Ensures:
        - returns the first existing of: the LUPIN_TEST_SCRATCH_PROJECT_DIR override, the container
          mount of the scratchpad project, the scratchpad project beside the repo
        - returns str( fallback_dir ) when none exists
        - never returns project_root
    """
    env = os.environ if env is None else env
    candidates = [
        env.get( SCRATCH_DIR_ENV ),
        SCRATCH_CONTAINER,
        os.path.join( os.path.dirname( os.path.abspath( project_root ) ), "scratchpad" ),
    ]
    root = os.path.abspath( project_root )
    for candidate in candidates:
        if candidate and os.path.abspath( candidate ) != root and exists( candidate ):
            return candidate
    return str( fallback_dir )


def root_litter( project_root, run=subprocess.run ):
    """
    The untracked, non-ignored files that sit directly in the repo root.

    Requires:
        - project_root is the repo root path as a string
        - run is callable like subprocess.run

    Ensures:
        - returns a frozenset of names with no path separator
        - returns an empty frozenset when git is missing or project_root is not a work tree,
          so the guard stays quiet where it cannot look
    """
    try:
        done = run(
            [ "git", "-C", project_root, "ls-files", "--others", "--exclude-standard" ],
            capture_output=True, text=True, timeout=30
        )
    except ( OSError, subprocess.TimeoutExpired ):
        return frozenset()
    if done.returncode != 0: return frozenset()
    return frozenset( name for name in done.stdout.splitlines() if name and "/" not in name )


def new_litter( before, after ):
    """
    The names in after that were not in before.

    Requires:
        - before and after are collections of names

    Ensures:
        - returns a sorted list
    """
    return sorted( set( after ) - set( before ) )
