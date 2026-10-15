"""
Say whether a pid still names the kind of process a bridge file recorded.

A bridge file stores a listener or idle-waiter pid. `os.kill( pid, 0 )` proves only that some
process holds that number now. The OS reuses numbers, so a signal sent after that check alone
could stop an unrelated process. This reads the process's own command line and asks it.
"""
import os

PROC_ROOT = "/proc"


def process_runs( pid: int, marker: str, proc_root: str = PROC_ROOT ) -> bool:
    """
    True iff the process `pid` has `marker` in its command line.

    Requires:
        - pid is a positive int
        - marker is a non-empty string naming the program, e.g. a module name

    Ensures:
        - returns True when `proc_root` does not exist (an OS with no /proc: the caller
          keeps its earlier liveness-only behaviour, since nothing can be checked)
        - returns False when the process has gone, its command line cannot be read, or
          the command line does not contain `marker`
        - returns True iff the NUL-separated command line, read as one string, contains `marker`
        - never raises
    """
    if not os.path.isdir( proc_root ):
        return True
    try:
        with open( f"{proc_root}/{pid}/cmdline", "rb" ) as handle:
            raw = handle.read()
    except OSError:
        return False
    return marker in raw.replace( b"\0", b" " ).decode( "utf-8", "replace" )
