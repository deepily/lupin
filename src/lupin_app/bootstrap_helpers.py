#!/usr/bin/env python3
"""
Bootstrap-time helpers for the FastAPI entry point.

These run during the `main.py` bootstrap, so this module imports only the standard
library. Staying dependency-free lets the unit tests import it without starting the
heavyweight cosa/* application stack.
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

    A hung server needs a read-only way to get a Python frame out, and the container has
    no py-spy, gdb or ptrace. SIGUSR1 terminates the process by default, so until this
    runs `kill -USR1` is a kill, not a diagnostic. The return value tells armed from fatal.

    Requires:
        - signal_module exposes SIGUSR1, getsignal and SIG_DFL (tests inject a double)
        - faulthandler_module exposes register( signum, file, all_threads )
        - stream is a writable file object, or None to use sys.stderr at call time

    Ensures:
        - returns "registered" and arms the handler when SIGUSR1 is free
        - returns "already-registered" on every later call — idempotent, so an import
          cycle or a second bootstrap never re-arms
        - returns "declined-existing-handler" and arms nothing when someone else already
          owns SIGUSR1. Stealing it would silently break whatever installed it, and this
          is a debugging aid: it does not get to outrank the application
        - returns "unsupported-platform" where SIGUSR1 does not exist, rather than raising
        - returns "unavailable-stream" when the destination has no usable file descriptor,
          having armed nothing
        - dumps all threads, since a hang is usually a thread other than the main one
        - never raises: `cosa.rest.routers.speech` imports `lupin_app.main` lazily inside
          a request handler, so this first runs part-way through a request. An exception
          here would fail that request in a handler that knows nothing about signals
          (a captured stderr once raised AttributeError('fileno') here)
        - read-only thereafter: no attach tooling, no ptrace, no container recreate, and
          no cost until the signal arrives
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

    This promotes the weak "is LUPIN_ROOT set?" guard in main.py to a strong "is it
    valid?" check. It catches the /app-vs-/var/lupin path drift at boot, not later
    when ConfigurationManager cannot find the INI.

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
    Decide whether uvicorn `--reload` is armed (pure function, so it is testable).

    Lives here, not in main.py, so it unit-tests without the heavyweight cosa/* stack.
    main.py reads the environment at container start and calls this. The gate stays
    inert until a docker recreate, since `docker restart` reuses the old env.

    Requires:
        - env_value is the raw LUPIN_RELOAD value (str, None, or "" — all safe)
        - is_prod_or_test is a bool

    Ensures:
        - returns True iff the normalized opt-in is truthy and this is neither
          production nor test — reload never arms outside local dev
        - accepts "1" / "true" / "yes" case-insensitively, surrounding whitespace
          tolerated, so `LUPIN_RELOAD=true` / `"1 "` don't silently fail closed

    Truth table (the spec, not the exact string):
        | LUPIN_RELOAD                          | is_prod_or_test | reload |
        | "1"/"true"/"yes" (any case, trimmed)  | False           | True   |
        | anything else / unset                 | False           | False  |
        | (any)                                 | True            | False  |
    """
    opted_in = ( env_value or "" ).strip().lower() in ( "1", "true", "yes" )
    return opted_in and not is_prod_or_test
