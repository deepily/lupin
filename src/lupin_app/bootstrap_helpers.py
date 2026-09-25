#!/usr/bin/env python3
"""
Bootstrap-time helpers for the FastAPI entry point.

These run during the `main.py` bootstrap, so this module deliberately imports
ONLY the standard library — keeping it dependency-free is what lets the unit
tests import it without spinning up the heavyweight cosa/* application stack.
"""
import faulthandler
import os
import signal
import sys


# Row abe4188d — set once `register_sigusr1_faulthandler` has armed the handler, so a
# second call is a no-op rather than a second sigaction. There is no API to ask
# faulthandler whether a signal is registered, so the flag is the only way to answer it.
_sigusr1_registered = False


def _reset_sigusr1_registration_for_testing():
    """Clear the idempotency flag. Test-only; nothing in the app calls it."""
    global _sigusr1_registered
    _sigusr1_registered = False


def register_sigusr1_faulthandler( signal_module=signal, faulthandler_module=faulthandler, stream=None ):
    """
    Arm `kill -USR1 <pid>` to print every thread's Python stack, without killing it.

    WHY THIS EXISTS (row abe4188d). A server that hangs is the one state no log
    explains, and on 2026-09-25 there was no read-only way to get a Python frame out
    of the running container: py-spy absent there AND on the host, gdb absent,
    `CapAdd=[]` so no SYS_PTRACE, and `faulthandler.is_enabled()` False — which meant
    signalling the process would have TERMINATED it rather than dumped it. A whole
    investigation ran out of instruments while the answer sat one signal away.

    ⚠️ The default disposition of SIGUSR1 is to terminate the process. Until this is
    called, `kill -USR1` on the server is not a diagnostic, it is a kill. That is the
    hazard this removes, and it is why the function reports what it did rather than
    returning None: a caller cannot otherwise tell an armed server from a fatal one.

    Read-only thereafter: no attach tooling, no ptrace, no container recreate, and it
    costs nothing until the signal arrives.

    Requires:
        - signal_module exposes SIGUSR1, getsignal and SIG_DFL (tests inject a double)
        - faulthandler_module exposes register( signum, file, all_threads )
        - stream is a writable file object, or None to use sys.stderr at call time

    Ensures:
        - returns "registered" and arms the handler when SIGUSR1 is free
        - returns "already-registered" on every later call — idempotent, so an import
          cycle or a second bootstrap never re-arms
        - returns "declined-existing-handler" and arms NOTHING when someone else already
          owns SIGUSR1. Stealing it would silently break whatever installed it, and this
          is a debugging aid: it does not get to outrank the application
        - returns "unsupported-platform" where SIGUSR1 does not exist, rather than raising
        - returns "unavailable-stream" when the destination has no usable file descriptor,
          having armed nothing
        - dumps ALL threads, since a hang is usually a thread other than the main one

    Never raises. That is load-bearing, not politeness: `cosa.rest.routers.speech`
    imports `lupin_app.main` LAZILY, inside a request handler, so this runs for the
    first time part-way through serving a request. An exception here would surface as
    that request failing, in a handler that knows nothing about signals — measured
    2026-09-25, when an earlier cut of this function raised AttributeError('fileno')
    under a captured stderr and two speech tests reported it as an upload-setup fault.
    """
    global _sigusr1_registered
    if _sigusr1_registered:
        return "already-registered"

    sigusr1 = getattr( signal_module, "SIGUSR1", None )
    if sigusr1 is None:
        # Windows has no SIGUSR1. Not an error — the server simply has no dump signal.
        return "unsupported-platform"

    # Only SIG_DFL means nobody owns it. SIG_IGN is a deliberate choice by someone else
    # and is left alone for the same reason a live handler is.
    current = signal_module.getsignal( sigusr1 )
    if current is not signal_module.SIG_DFL:
        return "declined-existing-handler"

    # faulthandler needs a REAL file descriptor and takes it at registration. A
    # captured or wrapped stderr — pytest's, a logging shim, anything without a live
    # fileno — makes this raise. Catch broadly and on purpose: every outcome here is
    # "the dump signal is not available", and none of them is worth failing a caller
    # that only ever imported a module.
    try:
        faulthandler_module.register( sigusr1, file=stream if stream is not None else sys.stderr,
                                      all_threads=True )
    except Exception:
        return "unavailable-stream"
    _sigusr1_registered = True
    return "registered"


def assert_lupin_root_valid( lupin_root ):
    """
    Assert that LUPIN_ROOT points at a populated Lupin source tree.

    Promotes the weak "is LUPIN_ROOT set?" guard in main.py to a strong
    "is LUPIN_ROOT valid?" check, catching the /app-vs-/var/lupin path drift
    at boot instead of cryptically later when ConfigurationManager cannot find
    the INI.

    Requires:
        - lupin_root is a non-empty string (the resolved LUPIN_ROOT value)

    Ensures:
        - returns None when <lupin_root>/src/conf/lupin-app.ini exists
        - raises RuntimeError naming the missing canary path otherwise

    Raises:
        - RuntimeError if the config canary file is not found under lupin_root
    """
    canary = os.path.join( lupin_root, "src", "conf", "lupin-app.ini" )
    if not os.path.isfile( canary ):
        raise RuntimeError(
            f"LUPIN_ROOT='{lupin_root}' is set but invalid: "
            f"expected config canary not found at '{canary}'. "
            f"Verify LUPIN_ROOT matches the Dockerfile bake path (/var/lupin)."
        )


def reload_enabled( env_value, is_prod_or_test ):
    """
    Decide whether uvicorn `--reload` is armed (R1 reload gate — pure/testable).

    Lives here, not in main.py, so it unit-tests without importing the
    heavyweight cosa/* stack. main.py reads the environment at container START
    and calls this; the gate is inert until a docker RECREATE (a plain
    `docker restart` reuses the container + its env).

    Requires:
        - env_value is the raw LUPIN_RELOAD value (str, None, or "" — all safe)
        - is_prod_or_test is a bool

    Ensures:
        - returns True iff the normalized opt-in is truthy AND this is neither
          production nor test — reload never arms outside local dev
        - accepts "1" / "true" / "yes" case-insensitively, surrounding whitespace
          tolerated, so `LUPIN_RELOAD=true` / `"1 "` don't silently fail closed

    Truth table (the spec — not the exact string):
        | LUPIN_RELOAD                          | is_prod_or_test | reload |
        | "1"/"true"/"yes" (any case, trimmed)  | False           | True   |
        | anything else / unset                 | False           | False  |
        | (any)                                 | True            | False  |
    """
    opted_in = ( env_value or "" ).strip().lower() in ( "1", "true", "yes" )
    return opted_in and not is_prod_or_test
