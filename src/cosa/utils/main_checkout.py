"""
The one answer to "which main checkout owns this path?" for code outside the hook library.

A linked worktree shares the .git directory of its main checkout, so the owner is the parent of
`git rev-parse --git-common-dir`. The hook library keeps its own copies, because a hook must not import cosa.
"""
import subprocess
from pathlib import Path


def _run_git( argv, cwd=None, timeout=10 ):
    """
    Run one git command and capture its text output.

    Requires:
        - argv is a non-empty list whose first element is "git"

    Ensures:
        - returns the CompletedProcess; a non-zero exit does not raise
    """
    return subprocess.run( argv, cwd=cwd, capture_output=True, text=True, timeout=timeout )


def main_checkout_of( path, run=None, timeout=10 ) -> str | None:
    """
    Name the main checkout that owns path, or the path itself when it is one.

    Requires:
        - path is a path-like or string
        - run is None or a callable taking ( argv, cwd=, timeout= ) and returning an object with returncode and stdout
        - timeout is the seconds git may take

    Ensures:
        - returns the parent of the absolute git common dir, as text
        - returns None when git cannot run, times out, exits non-zero or prints nothing
        - returns None when an injected run raises anything, because it then cannot say either
        - never raises
    """
    try:
        proc = ( run or _run_git )( [ "git", "rev-parse", "--path-format=absolute", "--git-common-dir" ], cwd=str( path ), timeout=timeout )
    except Exception:
        # any failure of the (possibly injected) runner means git cannot say; the callers hold their own fallbacks
        return None
    common = ( proc.stdout or "" ).strip()
    if proc.returncode != 0 or not common: return None
    return str( Path( common ).parent )
