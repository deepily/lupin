"""
Is the thing I am watching actually alive? — a liveness check that cannot match itself.

Bug 07786db9. A run monitor decided a paired eval was alive with:

    proc=$(pgrep -af "embedding_cost_live" 2>/dev/null | head -1)
    if [ -n "$proc" ]; then st="RUNNING ts-c16c33dd"; fi

`pgrep -af` matches the FULL COMMAND LINE of every process, and the monitor's own
command line CONTAINS the pattern — because the pattern is written inside it. The
monitor matched itself. It reported RUNNING 28 seconds after the job had already died,
would have kept reporting RUNNING all night including after the box powered off, and
could never have reported the run's death. Three seats held off `:8000` on that reading.

🔴 EXCLUDING YOUR OWN PID IS NOT ENOUGH, AND NEITHER IS YOUR PARENT'S. Measured on this
host 2026-08-17: a search for a string that existed nowhere on the machine except inside
the searching command matched the GRANDPARENT shell — the harness wraps commands as
`bash -c '<the whole thing>'`, so the pattern propagates up the ancestor chain. The row's
suggested fix ("exclude own-PID and own-PPID") would still have matched. This module
walks the whole chain.

THE THIRD STATE IS THE POINT. `alive` and `not alive` are not enough, because "I could
not tell" has to be distinguishable from "it is dead" — a monitor whose failure looks
like one of its answers is the defect this module exists for. Hence UNKNOWN.

Usage from a shell monitor, replacing the pgrep one-liner:

    python3 src/scripts/lib/job_liveness.py "pytest.*embedding_cost_live"
    # prints RUNNING / DEAD / UNKNOWN, exit 0 / 1 / 2

Generated on: 2026-08-17
"""

import os
import re
import sys


PROC_ROOT = "/proc"

RUNNING = "RUNNING"
DEAD    = "DEAD"
UNKNOWN = "UNKNOWN"

_EXIT_CODES = { RUNNING : 0, DEAD : 1, UNKNOWN : 2 }


def read_cmdline( pid, proc_root=PROC_ROOT ):
    """
    Return one process's command line as a space-joined string, or None.

    Requires:
        - pid is an int or a digit string

    Ensures:
        - Returns the NUL-separated /proc cmdline joined by single spaces
        - Returns None when the process is gone, unreadable, or a kernel thread
          (kernel threads have an empty cmdline)

    Raises:
        - nothing; a process may exit between listing and reading, and that is a
          normal race rather than an error
    """
    try:
        with open( os.path.join( proc_root, str( pid ), "cmdline" ), "rb" ) as handle:
            raw = handle.read()
    except ( FileNotFoundError, ProcessLookupError, PermissionError, NotADirectoryError, OSError ):
        return None

    if not raw:
        return None

    return raw.replace( b"\x00", b" " ).decode( "utf-8", errors="replace" ).strip()


def read_ppid( pid, proc_root=PROC_ROOT ):
    """
    Return a process's parent PID, or None when it cannot be read.

    Requires:
        - pid is an int or a digit string

    Ensures:
        - Returns the ppid field from /proc/<pid>/stat as an int
        - Returns None when the process is gone or the line is unparseable

    Raises:
        - nothing

    WHY THE FIELD IS TAKEN AFTER THE LAST ')': the second stat field is the executable
    name in parentheses and it MAY CONTAIN SPACES AND PARENTHESES itself, so splitting
    the whole line on whitespace puts ppid somewhere that depends on the program's name.
    """
    try:
        with open( os.path.join( proc_root, str( pid ), "stat" ), "r" ) as handle:
            line = handle.read()
    except ( FileNotFoundError, ProcessLookupError, PermissionError, NotADirectoryError, OSError ):
        return None

    close = line.rfind( ")" )
    if close == -1:
        return None

    fields = line[ close + 1: ].split()
    # after the ')' the next fields are: state, ppid, ...
    if len( fields ) < 2:
        return None

    try:
        return int( fields[ 1 ] )
    except ValueError:
        return None


def ancestor_pids( pid=None, proc_root=PROC_ROOT, max_depth=64 ):
    """
    Return the caller's own PID plus every ancestor up to init.

    THE WHOLE POINT OF THIS MODULE. The watcher's pattern can appear in the command
    line of any process above it, not just its own — measured on this host, the match
    was the GRANDPARENT. Anything in this set is the watcher looking at itself.

    Requires:
        - pid is an int or None (None → os.getpid())

    Ensures:
        - Returns a set of ints including `pid` itself
        - Walks parents until ppid is 0/None, or max_depth is reached
        - Terminates on a cycle, which cannot happen on a sane kernel but must not
          hang a monitor if it does

    Raises:
        - nothing
    """
    if pid is None:
        pid = os.getpid()

    seen  = set()
    depth = 0
    while pid and pid > 0 and pid not in seen and depth < max_depth:
        seen.add( pid )
        pid = read_ppid( pid, proc_root=proc_root )
        depth += 1

    return seen


def list_pids( proc_root=PROC_ROOT ):
    """
    Return every PID currently present in /proc, as ints.

    Requires:
        - proc_root names a readable procfs-shaped directory

    Ensures:
        - Returns a sorted list of ints
        - Returns [] when proc_root cannot be listed

    Raises:
        - nothing
    """
    try:
        entries = os.listdir( proc_root )
    except OSError:
        return [ ]

    return sorted( int( name ) for name in entries if name.isdigit() )


def find_matching_pids( pattern, proc_root=PROC_ROOT, own_pid=None ):
    """
    Return the PIDs whose command line matches `pattern`, EXCLUDING the watcher's own
    process and all of its ancestors.

    Requires:
        - pattern is a non-empty regular expression string

    Ensures:
        - Returns a sorted list of ints
        - Never includes the calling process or any of its ancestors
        - Skips processes that exit mid-scan rather than raising

    Raises:
        - re.error when the pattern is not a valid regular expression. Deliberately
          NOT swallowed: a monitor watching a typo would report DEAD forever, which is
          the same silent-wrong-answer this module exists to prevent.
    """
    compiled = re.compile( pattern )
    mine     = ancestor_pids( pid=own_pid, proc_root=proc_root )

    matches = [ ]
    for pid in list_pids( proc_root=proc_root ):
        if pid in mine:
            continue
        cmdline = read_cmdline( pid, proc_root=proc_root )
        if cmdline and compiled.search( cmdline ):
            matches.append( pid )

    return matches


def job_liveness( pattern, proc_root=PROC_ROOT, own_pid=None ):
    """
    Report RUNNING, DEAD, or UNKNOWN for the process(es) matching `pattern`.

    Requires:
        - pattern is a non-empty regular expression string

    Ensures:
        - RUNNING when at least one non-watcher process matches
        - DEAD when the scan succeeded and nothing matched
        - UNKNOWN when the scan itself could not be performed (no readable /proc), so
          "I could not look" is never returned as "it is not there"
        - Returns ( state, matching_pids )

    Raises:
        - ValueError when pattern is empty — an empty pattern matches every process
          and would report RUNNING unconditionally, which is this bug wearing a
          different hat
        - re.error on an invalid pattern
    """
    if not pattern:
        raise ValueError( "pattern must be non-empty: an empty pattern matches every process and would always report RUNNING" )

    if not list_pids( proc_root=proc_root ):
        # No readable process table at all. Distinct from "nothing matched".
        return UNKNOWN, [ ]

    pids = find_matching_pids( pattern, proc_root=proc_root, own_pid=own_pid )

    return ( RUNNING if pids else DEAD ), pids


def main( argv=None ):
    """
    CLI entry point: print the state, exit 0 RUNNING / 1 DEAD / 2 UNKNOWN.

    Requires:
        - argv[1] is the pattern to watch

    Ensures:
        - Prints the state and any matching PIDs to stdout
        - Returns the exit code rather than calling sys.exit, so it is testable

    Raises:
        - nothing; a bad pattern is reported as a usage error, not a traceback
    """
    argv = sys.argv if argv is None else argv
    if len( argv ) < 2 or not argv[ 1 ]:
        print( "usage: job_liveness.py <regex matching the watched process command line>" )
        return 2

    try:
        state, pids = job_liveness( argv[ 1 ] )
    except re.error as exc:
        print( f"{UNKNOWN} invalid pattern: {exc}" )
        return 2

    print( f"{state} {' '.join( str( p ) for p in pids )}".strip() )
    return _EXIT_CODES[ state ]


if __name__ == "__main__":
    sys.exit( main() )
