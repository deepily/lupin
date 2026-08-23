#!/usr/bin/env python3
"""
Run ONE lupin_smoke test method through the same seam the smoke runner uses.

WHY THIS EXISTS. The methods in src/tests/lupin_smoke/*.py hang off plain classes
rather than Test*, so pytest never collects them and `pytest -k <name>` cannot
reach them. They DO run: run-lupin-smoke-tests.sh invokes each file as a script,
the module's main() walks a list of (method, name) pairs through
utilities.run_test_with_error_handling, and sys.exit( 0 if all passed else 1 )
carries the verdict. That exit code is the seam a mutation has to move.

Running a whole file to observe one method is a big footprint against a live
server. This driver reproduces the seam for a SINGLE method: same class, same
construction, the same run_test_with_error_handling wrapper (so the same
PASS/FAIL-by-name line), and the same exit-code convention.

It is deliberately faithful rather than clever — it imports the real wrapper
instead of reimplementing it, so a driver that drifts from the runner is a
driver that cannot compile.

Requires:
    - LUPIN_ROOT points at the tree under test
    - a FastAPI server answering at http://localhost:7999
    - LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD in the environment

Ensures:
    - prints the runner's own PASS/FAIL line, naming the test
    - exits 0 when the method passed, 1 when it failed

Usage:
    python3 <this> test_audio_tts AudioTTSSmokeTests test_audio_authentication
"""
import asyncio
import os
import sys


def _bootstrap():
    """Put <LUPIN_ROOT>/src on sys.path the way the smoke files themselves do."""
    lupin_root = os.environ.get( "LUPIN_ROOT" )
    if lupin_root is None:
        raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/worktree" )
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path: sys.path.insert( 0, src_path )
    return lupin_root


async def _run( module_name, class_name, method_name, debug ):
    import importlib
    module    = importlib.import_module( f"tests.lupin_smoke.{module_name}" )
    utilities = importlib.import_module( "tests.lupin_smoke.utilities" )

    test_cls = getattr( module, class_name )
    instance = test_cls( debug=debug )
    method   = getattr( instance, method_name )

    # The runner's own wrapper — imported, never reimplemented.
    return await utilities.run_test_with_error_handling( method, method_name )


def main():
    if len( sys.argv ) < 4:
        print( __doc__ )
        return 2

    module_name, class_name, method_name = sys.argv[ 1 ], sys.argv[ 2 ], sys.argv[ 3 ]
    debug = "--debug" in sys.argv

    lupin_root = _bootstrap()
    print( f"[DRIVER] LUPIN_ROOT = {lupin_root}" )
    print( f"[DRIVER] {module_name}.{class_name}.{method_name}" )

    passed = asyncio.run( _run( module_name, class_name, method_name, debug ) )
    print( f"[DRIVER] verdict: {'PASS' if passed else 'FAIL'}" )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit( main() )
