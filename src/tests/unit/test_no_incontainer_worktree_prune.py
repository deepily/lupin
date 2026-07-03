"""
Regression guard for bug 47ac0e50 — in-container `git worktree prune` wipes the
host worktree registry.

A `git worktree prune` executed via `docker exec` inside a Lupin server
container (`lupin-rest-test` / `lupin-rest-dev`) — which bind-mounts ./.git but
NOT lupin-worktrees/ — deletes the ENTIRE shared host .git/worktrees registry:
every host-registered worktree's gitdir resolves to a missing in-container path,
so prune deems them all stale and removes their admin dirs (propagating to the
host via the shared .git mount). This test fails loudly if any container-exec
preflight surface re-introduces the command.

Forensics: src/rnd/v0.1.9/2026.07.02-worktree-wipe-in-container-prune-forensics.md

Venue: :7999-eligible (pure source scan — no docker, no server, no state).
"""

import os

# Repo root from THIS file's location (worktree-correct — never reads the main
# tree by way of a stale LUPIN_ROOT): src/tests/unit/<this> -> ../../.. = root.
_ROOT = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )

# The container-exec preflight surfaces: both `docker exec <container> … git
# worktree prune` at teardown before this fix. A `git worktree remove --force
# <smoke>` already cleans the smoke worktree's admin entry, so the prune is
# redundant AND catastrophic in the mounted-.git / unmounted-worktrees topology.
_GUARDED_SOURCES = (
    "src/scripts/preflight-test-container.sh",
    "src/tests/smoke/test_container_preflight.py",
)


def _strip_comment_lines( source: str ) -> str:
    """Drop whole-line comments so the ban catches only executable commands,
    not the comments that EXPLAIN the ban (which legitimately name the command).
    Both guarded sources use `#` line comments."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith( "#" )
    )


def test_no_worktree_prune_in_container_preflight_sources():
    for rel in _GUARDED_SOURCES:
        path = os.path.join( _ROOT, rel )
        with open( path, encoding="utf-8" ) as fh:
            code = _strip_comment_lines( fh.read() )
        assert "worktree prune" not in code, (
            f"{rel} runs `git worktree prune` in a container-exec preflight "
            f"surface — forbidden (bug 47ac0e50: an in-container prune wipes the "
            f"host worktree registry). Use `git worktree remove --force <path>` "
            f"alone; it already cleans the smoke worktree's admin entry."
        )


if __name__ == "__main__":
    import sys
    import pytest
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
