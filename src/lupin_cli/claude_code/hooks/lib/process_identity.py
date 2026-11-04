"""
Say whether a pid still names the program a bridge file recorded.

A bridge file stores a listener or idle-waiter pid. `os.kill( pid, 0 )` proves only that some
process holds that number now. The OS reuses numbers, so a signal sent after that check alone
could stop an unrelated process. This reads the process's own command line and asks it.
"""
import os

PROC_ROOT = "/proc"

# Interpreter options that take a value, so the value is not the script.
_VALUED_OPTIONS = ( "-W", "-X" )


def _names_module( argument: str, module: str ) -> bool:
    """True iff the argument is the module, or a dotted path whose last component is the module."""
    return argument == module or argument.endswith( "." + module )


def process_runs( pid: int, module: str, proc_root: str = PROC_ROOT ) -> bool:
    """
    True iff the process `pid` was started as the program `module`.

    Requires:
        - pid is a positive int
        - module is a non-empty module name, bare or dotted, e.g. `cc_notification_listener`

    Ensures:
        - returns True when `proc_root` does not exist (an OS with no /proc: the caller
          keeps its earlier liveness-only behaviour, since nothing can be checked)
        - returns False when the process has gone, its command line cannot be read or is empty,
          or its program is not a Python interpreter
        - otherwise reads the arguments after the interpreter, in order, and stops at the first of:
          `-c` (the rest are arguments of the code, so False); `-m` (True iff the next argument
          is the module, whole or as the last dotted component); or the first argument that is
          not an option, which is the script (True iff its basename is `<module>.py`)
        - never matches the name inside another argument, so an editor, a test runner or a
          `tail` that mentions the module is not the program
        - never raises
    """
    if not os.path.isdir( proc_root ):
        return True
    try:
        with open( f"{proc_root}/{pid}/cmdline", "rb" ) as handle:
            raw = handle.read()
    except OSError:
        return False
    arguments = [ part.decode( "utf-8", "replace" ) for part in raw.split( b"\0" ) if part ]
    if not arguments or not os.path.basename( arguments[ 0 ] ).startswith( "python" ):
        return False
    skip      = False
    for index, argument in enumerate( arguments[ 1: ], start=1 ):
        if skip:
            skip = False
            continue
        if argument == "-c":
            return False
        if argument == "-m":
            return index + 1 < len( arguments ) and _names_module( arguments[ index + 1 ], module )
        if argument in _VALUED_OPTIONS:
            skip = True
            continue
        if not argument.startswith( "-" ):
            return os.path.basename( argument ) == module + ".py"
    return False
