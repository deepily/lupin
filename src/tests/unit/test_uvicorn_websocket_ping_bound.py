#!/usr/bin/env python3
"""
Unit — the websocket ping bound that caps how long a stale socket can lie (row dc446601).

WHY THIS FILE EXISTS. Tiffany's ruling removed supersession for a mobile client that
sends no `device_id`: two such phones are indistinguishable, they would share one slot
and displace each other, and since the app ignores close codes and reconnects after any
close, that is not one bump but a loop. María's objection to the removal is the real
one: with nobody displacing it, a STALE fallback socket stays registered, keeps
`has_live_mobile_session` True, and silently suppresses the FCM wake — the exact failure
the whole row exists to prevent.

The answer is that the socket does not stay registered indefinitely. uvicorn pings every
`ws_ping_interval` and drops a peer that has not answered within `ws_ping_timeout`, so a
half-open socket is reaped in at most interval + timeout — comfortably inside the wake
debounce window, which means the wake it suppressed is only DELAYED by less than one
window, not lost.

⚠️ THAT BOUND IS AN ARGUMENT, AND AN ARGUMENT IS NOT A GUARD. It holds only while
main.py leaves the ping enabled: one `ws_ping_interval=None` in `uvicorn.run` turns the
bound into "forever" with nothing failing anywhere. This file is what makes the argument
falsifiable.

Both halves are asserted, because either alone proves nothing:
    (1) main.py does not disable the ping     — what a future edit could break
    (2) the installed defaults are finite AND sum to less than the wake window
                                              — what makes the bound a bound at all

The window is READ FROM THE INI rather than written here as 60. A test that restates a
configured number agrees with the config until someone changes one of them.

Venue: :7999 (pure unit — source parsing plus attribute inspection, no server, no IO).
"""

import ast
import os
import sys

import pytest

# Bootstrap
_LUPIN_ROOT = os.environ.get( "LUPIN_ROOT", os.getcwd() )
_src_path   = os.path.join( _LUPIN_ROOT, "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

MAIN_PY = os.path.join( _src_path, "lupin_app", "main.py" )

PING_KEYS = ( "ws_ping_interval", "ws_ping_timeout" )


def _uvicorn_run_call():
    """
    The `uvicorn.run(...)` Call node in main.py, found rather than assumed.

    Ensures:
        - returns exactly one Call whose func is the attribute `run` on `uvicorn`
        - fails loudly if there is not exactly one, because a second call site would
          make every assertion below a statement about the wrong one
    """
    with open( MAIN_PY, "r" ) as handle:
        tree = ast.parse( handle.read(), filename=MAIN_PY )

    calls = [
        node for node in ast.walk( tree )
        if isinstance( node, ast.Call )
        and isinstance( node.func, ast.Attribute )
        and node.func.attr == "run"
        and isinstance( node.func.value, ast.Name )
        and node.func.value.id == "uvicorn"
    ]
    assert len( calls ) == 1, (
        f"expected exactly one uvicorn.run call in main.py, found {len( calls )}. "
        f"With more than one, this file would be guarding whichever it happened to pick."
    )
    return calls[ 0 ]


def _reload_kwargs_keys():
    """
    Every key written into the `reload_kwargs` dict that main.py splats into uvicorn.run.

    The splat is the hole an explicit-keyword check alone would leave: a ping setting
    injected through the dict never appears as a keyword on the call.
    """
    with open( MAIN_PY, "r" ) as handle:
        tree = ast.parse( handle.read(), filename=MAIN_PY )

    keys = set()
    for node in ast.walk( tree ):
        # reload_kwargs[ "x" ] = ...
        if isinstance( node, ast.Assign ) and len( node.targets ) == 1:
            target = node.targets[ 0 ]
            if ( isinstance( target, ast.Subscript )
                 and isinstance( target.value, ast.Name )
                 and target.value.id == "reload_kwargs"
                 and isinstance( target.slice, ast.Constant ) ):
                keys.add( target.slice.value )
            # reload_kwargs = { "x": ... }
            if ( isinstance( target, ast.Name ) and target.id == "reload_kwargs"
                 and isinstance( node.value, ast.Dict ) ):
                for k in node.value.keys:
                    if isinstance( k, ast.Constant ): keys.add( k.value )
    return keys


def test_the_parser_finds_a_real_call():
    """
    The instrument can find something.

    Every assertion below is of the form "this key is absent", and absence proves
    nothing until the same search has returned a presence. If main.py were renamed or
    the parse silently produced an empty tree, the guards would pass vacuously.
    """
    call = _uvicorn_run_call()
    names = { kw.arg for kw in call.keywords if kw.arg is not None }
    assert "port" in names and "workers" in names, (
        f"the parser found a uvicorn.run call but not its known keywords; got {sorted( names )}"
    )


def test_main_py_does_not_disable_the_websocket_ping():
    """
    THE GUARD. main.py must not turn the ping off, by keyword or by splat.

    `ws_ping_interval=None` disables pinging outright, and 0 is the same thing spelled
    differently. Either turns "a half-open socket is reaped in ~40s" into "never", and
    a stale mobile socket then suppresses that user's FCM wake indefinitely.
    """
    call     = _uvicorn_run_call()
    explicit = { kw.arg: kw.value for kw in call.keywords if kw.arg is not None }

    for key in PING_KEYS:
        if key not in explicit:
            continue
        node = explicit[ key ]
        assert isinstance( node, ast.Constant ), (
            f"main.py passes {key} as a non-literal, so this guard cannot read it. "
            f"Either inline the value or extend this test — do not leave it unreadable."
        )
        assert node.value not in ( None, 0 ), (
            f"main.py sets {key}={node.value!r}, which DISABLES the websocket ping. "
            f"A half-open mobile socket then stays registered forever and suppresses "
            f"that user's FCM wake — see this file's docstring and row dc446601."
        )

    leaked = sorted( set( PING_KEYS ) & _reload_kwargs_keys() )
    assert not leaked, (
        f"reload_kwargs injects {leaked} into uvicorn.run through the ** splat, where "
        f"the explicit-keyword check above cannot see it."
    )


def test_the_installed_defaults_make_the_bound_a_real_bound():
    """
    The other half: the defaults main.py relies on are finite, and small enough to matter.

    Without this, the guard above would be satisfied by a uvicorn whose default ping was
    disabled or an hour long — main.py would be "not disabling" a bound that does not
    exist. Read from the installed package, never quoted from a changelog.
    """
    import inspect

    import uvicorn

    params = inspect.signature( uvicorn.Config.__init__ ).parameters
    interval = params[ "ws_ping_interval" ].default
    timeout  = params[ "ws_ping_timeout" ].default

    for name, value in ( ( "ws_ping_interval", interval ), ( "ws_ping_timeout", timeout ) ):
        assert isinstance( value, ( int, float ) ) and value > 0, (
            f"uvicorn {uvicorn.__version__} defaults {name}={value!r}; the reaping bound "
            f"this row relies on does not exist in this environment."
        )

    window = _wake_debounce_seconds()
    assert interval + timeout < window, (
        f"uvicorn {uvicorn.__version__} reaps a half-open socket in up to "
        f"{interval + timeout}s, which is NOT inside the {window}s FCM wake debounce "
        f"window. A stale mobile socket could then suppress a wake for longer than the "
        f"window it was meant to be bounded by."
    )


def _wake_debounce_seconds():
    """
    The wake window, read from the INI the service itself reads.

    Asking the config rather than restating 60 — a projection of a rule that restates it
    agrees until one of the two is changed, and the restatement is usually the stale one.
    """
    from cosa.config.configuration_manager import ConfigurationManager

    return ConfigurationManager( env_var_name="LUPIN_CONFIG_MGR_CLI_ARGS" ).get(
        "fcm wake debounce seconds", default=60, return_type="int", silent=True
    )


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
