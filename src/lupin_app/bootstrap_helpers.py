#!/usr/bin/env python3
"""
Bootstrap-time helpers for the FastAPI entry point.

These run during the `main.py` bootstrap, so this module deliberately imports
ONLY the standard library — keeping it dependency-free is what lets the unit
tests import it without spinning up the heavyweight cosa/* application stack.
"""
import os


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
