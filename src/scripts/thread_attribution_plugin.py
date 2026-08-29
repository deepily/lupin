"""
pytest plugin: record which THREAD executed each first-party line.

Row `87ae7234`. Used by `detect_thread_credited_coverage.py`. `threading.settrace`
installs on every thread started after it is set; `sys.settrace` covers the thread
pytest runs tests on. Third-party frames are rejected on one substring compare
before anything is recorded, because the tracer runs on every line of the process.

Output (LUPIN_THREAD_ATTRIB_OUT, default /tmp/thread-attrib.json):
    { "<thread name>": { "<file>": [line, ...] } }

⚠️ settrace is SLOW — roughly 1.5-2x on the scopes measured so far. This is a
periodic check, not something to put in front of every run.
"""
import atexit
import collections
import json
import os
import threading

PREFIX = os.environ.get( "LUPIN_THREAD_ATTRIB_PREFIX", "/src/" )
OUT    = os.environ.get( "LUPIN_THREAD_ATTRIB_OUT",    "/tmp/thread-attrib.json" )

_hits = collections.defaultdict( lambda: collections.defaultdict( set ) )
_lock = threading.Lock()
_done = False


def _tracer( frame, event, arg ):
    if event != "line":
        return _tracer
    fn = frame.f_code.co_filename
    if PREFIX not in fn or "/tests/" in fn or "site-packages" in fn:
        return _tracer
    with _lock:
        _hits[ threading.current_thread().name ][ fn ].add( frame.f_lineno )
    return _tracer


def pytest_configure( config ):
    import sys
    threading.settrace( _tracer )
    sys.settrace( _tracer )


def pytest_unconfigure( config ):
    import sys
    sys.settrace( None )
    threading.settrace( None )
    _dump()


def _dump():
    """
    Write the attribution map once.

    Ensures:
        - writes at most once, whether called from pytest_unconfigure or atexit
        - atexit is the fallback for a run that ends without unconfigure; it does
          NOT survive os._exit, which is the point made in the row about the
          module's hard-exit path
    """
    global _done
    if _done: return
    _done = True
    with _lock:
        payload = { t: { fn: sorted( ls ) for fn, ls in files.items() }
                    for t, files in _hits.items() }
    with open( OUT, "w" ) as fh:
        json.dump( payload, fh, indent=2, sort_keys=True )


atexit.register( _dump )
