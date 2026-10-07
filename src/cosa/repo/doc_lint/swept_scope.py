"""
The one definition of the swept scope, shared by the commit gate and the merge gate.

A swept file is a tracked Python file that the documentation standard covers and that is not held.
A held file keeps its findings until its own review is done, so the zero rule does not apply to it.
"""

from .cli import in_scope, tracked_files

# Repo-relative prefixes. A directory prefix ends in a slash; a file is named in full.
# The one entry is tool text that a model reads as its instructions.
HELD_PREFIXES = ( "src/lupin_mcp/", )


def is_swept( path ):
    """
    Say whether a repo-relative path is held to zero findings.

    Requires:
        - path is a posix repo-relative path

    Ensures:
        - True for a Python file that in_scope accepts and that starts with no held prefix
        - False for every other path

    Raises:
        - nothing
    """
    if not path.endswith( ".py" ) or not in_scope( path ): return False
    return not any( path.startswith( prefix ) for prefix in HELD_PREFIXES )


def swept_files( repo_root ):
    """
    List the swept files of a working tree.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns sorted repo-relative posix paths, each one accepted by is_swept
        - the population comes from git, never from a disk walk

    Raises:
        - RuntimeError naming the git error when the listing fails
    """
    return [ path for path in tracked_files( repo_root, ( ".py", ) ) if is_swept( path ) ]
