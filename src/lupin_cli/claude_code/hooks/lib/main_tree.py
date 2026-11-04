"""
Resolve the main working tree for a path that may sit inside a seat's worktree.

Fleet-shared logs (the commons topic files, the janitor's seat-teardown log) belong to
the repo, not to whichever seat wrote them. A seat pins `LUPIN_ROOT` to its own tree, so
a writer that joins `io/...` onto it leaves the log inside the seat's tree. That is a
gitignored file that is not build output. The worktree janitor refuses to delete exactly
such files, and they held back trees it could not remove.

Every worktree lives under `<main>/.claude/worktrees/<name>` (see CLAUDE.md, section
Worktrees), so the main tree is the part of the path before that lane. No git call is
made: this runs in hooks and at import time, and a path rule cannot hang or disagree
with itself.
"""

import os


WORKTREE_LANE_MARK = os.sep + os.path.join( ".claude", "worktrees" ) + os.sep


def main_tree_root( path ) -> str:
    """
    The main working tree for `path`: itself, unless it is inside a worktree lane.

    Requires:
        - path is a path-like or string

    Ensures:
        - returns str( path ) unchanged when no `/.claude/worktrees/` lane is in it
        - otherwise returns the part before the outermost lane, so a tree made inside a
          tree still resolves to the one main checkout
        - a path that is the lane directory resolves to the main tree as well
        - never touches the filesystem, never raises
    """
    text = str( path )
    cut  = ( text + os.sep ).find( WORKTREE_LANE_MARK )
    if cut == -1:
        return text
    return text[ :cut ] or os.sep
