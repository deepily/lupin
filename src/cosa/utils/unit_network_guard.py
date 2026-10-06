"""
Hold the outbound-network guard's state in one copy, however often a conftest loads.

The guard used to keep its state in `src/conftest.py` itself. That file is loaded twice
as two separate module objects. So `pytest_runtest_setup` recorded a test's
`allows_outbound_network` marker into one copy's dict. The installed socket patch
read a different dict that nothing wrote to. Every such marker was inert on a
whole-directory run. Also `outbound_attempts` recorded `<collection>` for every dial,
so the census could not name which test made it. The same test class errored when run with
the whole unit directory and passed when run from its own file.

Why the conftest loads twice is not established. One hypothesis was tested and rejected:
`src/` and `src/tests/unit/` both lack `__init__.py`, so their conftests might collide
on the module name "conftest". Adding the package marker changed nothing.

This module makes the cause irrelevant instead of removing it. A module under `cosa/` is
imported through the ordinary machinery and lives at one key in `sys.modules`. However
many times a conftest loads, every copy binds the same dict and the same list. This is
the same reasoning as `cosa.utils.tree_state`: one implementation, many callers, because
two copies of one contract drift.

`arm()` is idempotent for the same reason. A double-loaded conftest calling it twice
would otherwise wrap the socket patch around itself.

Venue: :7999-eligible. It uses no network of its own and mutates nothing outside this
process.
"""
import os
import socket
import traceback


# THREE MODES, chosen by LUPIN_UNIT_NETWORK — see `src/conftest.py` for the full account of
# why `count` exists and why the escape hatch is a marker rather than an environment default.
#   off   (default) — inert
#   count           — record and ALLOW, printing a summary
#   block           — record and RAISE, naming the test, the address and the frames
NETWORK_MODE_RAW  = os.environ.get( "LUPIN_UNIT_NETWORK" )
NETWORK_MODE      = ( NETWORK_MODE_RAW or "off" ).strip().lower()
LOOPBACK_HOSTS    = { "127.0.0.1", "::1", "localhost", "0.0.0.0", "" }

outbound_attempts = []                         # (test id, address, formatted frames)
current_test      = { "id": "<collection>", "exempt": False }

_real_socket_connect    = socket.socket.connect
_real_socket_connect_ex = socket.socket.connect_ex
_armed                  = False


def is_loopback( address ):
    """
    Say whether a connect address is local, so only routed dials are guarded.

    Ensures:
        - returns True for anything that is not a routed address, so AF_UNIX and
          in-process transports are never touched
        - returns True for loopback: TestClient and the real-socket arms in
          test_model_server_liveness.py bind 127.0.0.1, and a guard that
          breaks legitimate tests gets switched off, which is worse than no guard
    """
    if not isinstance( address, tuple ) or not address:
        return True
    host = address[ 0 ]
    if host in LOOPBACK_HOSTS:
        return True
    return isinstance( host, str ) and host.startswith( "127." )


def caller_frames():
    """Return the repo frames beneath the connect, so a report names the caller, not the library."""
    frames = [ f for f in traceback.extract_stack()[ :-2 ]
               if "/site-packages/" not in f.filename and "/lib/python" not in f.filename ]
    return [ f"{f.filename}:{f.lineno} in {f.name}" for f in frames[ -6: ] ]


def set_current_test( node_id, exempt ):
    """
    Record which test is in flight and whether it declared the marker.

    Mutates the module's own dict in place rather than rebinding it. A rebind would give
    a caller holding `from ... import current_test` a stale object, which brings back
    the two-copies defect this module exists to remove.
    """
    current_test[ "id" ]     = node_id
    current_test[ "exempt" ] = exempt


def network_guard( real ):
    """Wrap a socket method so a non-exempt routed dial is recorded, and raised in block mode."""
    def wrapper( self, address, *args, **kwargs ):
        if NETWORK_MODE in ( "count", "block" ) and not is_loopback( address ) \
           and not current_test[ "exempt" ]:
            frames = caller_frames()
            outbound_attempts.append( ( current_test[ "id" ], address, frames ) )
            if NETWORK_MODE == "block":
                raise RuntimeError(
                    f"OUTBOUND NETWORK BLOCKED in a unit test (row 7c84b8b8).\n"
                    f"  test    : {current_test[ 'id' ]}\n"
                    f"  address : {address}\n"
                    f"  from    :\n    " + "\n    ".join( frames ) + "\n"
                    f"  A unit test that dials out passes or fails on whether a server "
                    f"happened to be up. Inject the seam, or mark the test with "
                    f"@pytest.mark.allows_outbound_network if it genuinely needs the network."
                )
        return real( self, address, *args, **kwargs )
    return wrapper


def arm():
    """
    Install the socket patches, at most once per process.

    Requires:
        - nothing; safe to call from a conftest that is loaded more than once.

    Ensures:
        - patches only in count/block mode, so integration and e2e runs, which legitimately
          use the network and do not set the variable, are untouched
        - is idempotent: a second call is a no-op. Without that, a double-loaded conftest
          wraps the guard around itself, every dial is recorded twice, and the block-mode
          summary reports a count nobody could reconcile against the run
        - returns True when this call did the arming, False when it was already armed,
          so a test can assert the second call was a no-op rather than infer it

    Call it at import, not in a fixture. A dial-out can sit in a
    `@pytest.mark.skipif( not _mistral_reachable(), ... )` argument, which Python
    evaluates at collection, before any fixture exists to catch it.
    """
    global _armed
    if _armed or NETWORK_MODE not in ( "count", "block" ):
        return False
    socket.socket.connect    = network_guard( _real_socket_connect )
    socket.socket.connect_ex = network_guard( _real_socket_connect_ex )
    _armed = True
    return True
