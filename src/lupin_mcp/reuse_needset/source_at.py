"""
The source tree of one commit, as a detached worktree a run takes for its root.

A live run takes hours, and the main tree moves under it as peers merge.
A member found by line number in one version of a file cannot be stripped from another.
So the context, the index, the strips, the trace and the probe all take this one root.
"""
import pathlib
import subprocess

from lupin_mcp.reuse_needset import errors as er

WORKTREES = ".claude/worktrees"
PREFIX    = "needset-run-"
SHA_CHARS = 9


def full_sha( repo_root, commit ):
    """
    Resolve a commit name to its full sha.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns the 40-character sha of the commit

    Raises:
        - NeedsetError SOURCE_TREE_FAILED when git does not know the commit
    """
    got = subprocess.run( [ "git", "-C", str( repo_root ), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}" ], capture_output=True, text=True )
    if got.returncode != 0: raise er.NeedsetError( er.SOURCE_TREE_FAILED, f"{repo_root}: no commit {commit!r}" )
    return got.stdout.strip()


def worktree_path( repo_root, commit ):
    """
    Name the folder a commit's worktree lives in.

    Ensures:
        - returns <repo_root>/.claude/worktrees/needset-run-<first 9 of the sha>, where the worktree rules and the janitor expect it
    """
    return pathlib.Path( repo_root ) / WORKTREES / f"{PREFIX}{full_sha( repo_root, commit )[ :SHA_CHARS ]}"


def at_commit( root, sha ):
    """
    Say whether a tree is at a commit with no tracked file changed.

    Requires:
        - root is a git working tree; sha is a full sha

    Ensures:
        - returns True iff HEAD is the sha and no tracked file is modified or staged
        - untracked and ignored files, such as the generated index, do not count
    """
    head   = subprocess.run( [ "git", "-C", str( root ), "rev-parse", "HEAD" ], capture_output=True, text=True )
    status = subprocess.run( [ "git", "-C", str( root ), "status", "--porcelain", "--untracked-files=no" ], capture_output=True, text=True )
    return head.returncode == 0 and head.stdout.strip() == sha and status.returncode == 0 and status.stdout.strip() == ""


def ensure_worktree( repo_root, commit, dest=None ):
    """
    Return a detached worktree at the commit, making it when it is missing.

    Requires:
        - repo_root is a git working tree that holds the commit
        - dest is None for worktree_path, or a path whose parent exists or can be made

    Ensures:
        - returns the worktree's path, at the full sha of the commit with no tracked file changed
        - the worktree resolves to the parent checkout for the data folder and the spend ledger, which a plain copy of the files would not
        - a worktree already there at the same commit is reused as it is

    Raises:
        - NeedsetError SOURCE_TREE_MISMATCH when dest exists and is at another commit or has a changed tracked file
        - NeedsetError SOURCE_TREE_FAILED when git cannot make the worktree
    """
    sha  = full_sha( repo_root, commit )
    dest = worktree_path( repo_root, commit ) if dest is None else pathlib.Path( dest )
    if dest.exists():
        if at_commit( dest, sha ): return dest
        raise er.NeedsetError( er.SOURCE_TREE_MISMATCH, f"{dest} is not at {sha} with its tracked files unchanged; remove it with git worktree remove to make it again" )
    dest.parent.mkdir( parents=True, exist_ok=True )
    got = subprocess.run( [ "git", "-C", str( repo_root ), "worktree", "add", "--detach", str( dest ), sha ], capture_output=True, text=True )
    if got.returncode != 0: raise er.NeedsetError( er.SOURCE_TREE_FAILED, f"{repo_root}: git worktree add {sha}: {got.stderr.strip()}" )
    return dest
