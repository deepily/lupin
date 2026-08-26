#!/usr/bin/env python3
"""
Detect coverage that a BACKGROUND THREAD credited, not a test.

Row `87ae7234`. A daemon started at import — `session-id-watcher`, started
unguarded at `src/lupin_mcp/cosa_voice_mcp.py:529-534` and polling every 2.0s — runs
for the life of the test process and executes product lines nobody wrote a test for.
Coverage.py credits them like any other executed line. Measured on
`src/tests/unit/lupin_mcp`: 41 statements of `session_bridge.py` are covered only
because that thread ran.

TWO LEVERS WERE TRIED. This script uses the second.

  1. THE CLOCK — run the scope twice, once held open past the poll interval, and
     diff. It DEMONSTRATES the defect well (15% vs 18% on the same 333 tests) but
     it makes a bad detector: it only fires when the baseline run finishes inside
     one poll. Measured — under this script's own subprocess overhead the baseline
     took 5.6s against a 2.0s poll, so both runs credited the same 134 lines and
     the check reported CLEAN on a scope known to be dirty. A detector that misses
     its own known positive is worse than none.

  2. THREAD ATTRIBUTION — record which thread executed each line, then report lines
     no test thread ever reached. Deterministic, independent of how long anything
     takes, and it names the responsible thread. That is what runs here.

SUPPRESSION IS NOT AN OPTION, and this is measured rather than assumed: no-op'ing
`Thread.start` for `session-id-watcher` takes `src/tests/unit/lupin_mcp` from
`EXIT=0 / 333 passed` to `EXIT=1` with no summary, because that daemon resolves the
session id and the failure path ends in `os._exit( 1 )`.

WHAT A FINDING MEANS, AND WHAT IT DOES NOT. A reported line was executed by a
non-test thread and by nothing else. That is always true of the report; whether it
is a DEFECT depends on the thread. A daemon started at import credits lines nobody
tested — that is the defect. A worker thread a test starts deliberately, and whose
work that test then asserts on, is legitimate: the coverage is earned, it just did
not happen on the test's own thread. The report names the thread so the reader can
tell them apart. It does not decide.

Usage:
    python src/scripts/detect_thread_credited_coverage.py <pytest-target>
        [--allow-thread NAME]... [--json OUT] [--quiet]

Exit codes:
    0  no thread-credited lines outside the allow-list
    1  thread-credited lines found (the report names thread, file and lines)
    2  the run failed, so the attribution means nothing
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

# The thread pytest runs tests on. Lines it executed are earned by definition.
TEST_THREAD = "MainThread"


def _project_root():
    root = os.environ.get( "LUPIN_ROOT" )
    if root is None:
        raise RuntimeError( "LUPIN_ROOT not set - export LUPIN_ROOT=/path/to/project" )
    return root


def _run_attributed( target, root, out_path, extra_args ):
    """
    Run the target scope once under the attribution tracer.

    Ensures:
        - returns the parsed attribution map {thread: {file: [lines]}}
        - raises RuntimeError if pytest exits non-zero or wrote no map, because a
          truncated run attributes only the part that ran
    """
    env = dict( os.environ )
    env[ "PYTHONPATH" ]                  = os.path.join( root, "src" ) + os.pathsep + \
                                           os.path.join( root, "src", "scripts" ) + os.pathsep + \
                                           env.get( "PYTHONPATH", "" )
    env[ "LUPIN_THREAD_ATTRIB_OUT" ]     = out_path
    env[ "LUPIN_THREAD_ATTRIB_PREFIX" ]  = os.path.join( root, "src" ) + os.sep

    cmd = [ sys.executable, "-m", "pytest", target, "-q", "--no-header",
            "-p", "no:cacheprovider", "-p", "thread_attribution_plugin" ] + list( extra_args )

    proc = subprocess.run( cmd, cwd=root, env=env, capture_output=True, text=True )
    if proc.returncode != 0:
        raise RuntimeError(
            f"the attributed run exited {proc.returncode}; a failed or truncated run cannot be "
            f"attributed.\n{proc.stdout[ -2000: ]}\n{proc.stderr[ -2000: ]}"
        )
    if not os.path.exists( out_path ):
        raise RuntimeError( "the attribution map was never written - the plugin did not load" )

    with open( out_path ) as fh:
        return json.load( fh )


def exclusive_lines( attribution, allow_threads ):
    """
    Reduce an attribution map to the lines only a non-test thread reached.

    Requires:
        - attribution maps thread name -> file -> list of line numbers
        - allow_threads is a collection of thread names to exempt

    Ensures:
        - returns {thread: {file: [lines]}} for lines absent from the test thread's
          own set, excluding allow-listed threads
        - a thread that executed only lines the test thread also executed does not
          appear at all
    """
    test_lines = { fn: set( ls ) for fn, ls in attribution.get( TEST_THREAD, {} ).items() }

    findings = {}
    for thread, files in attribution.items():
        if thread == TEST_THREAD or thread in allow_threads: continue
        for fn, lines in files.items():
            gained = sorted( set( lines ) - test_lines.get( fn, set() ) )
            if gained: findings.setdefault( thread, {} )[ fn ] = gained
    return findings


def main( argv=None ):
    parser = argparse.ArgumentParser(
        description="Report product lines executed only by a non-test thread."
    )
    parser.add_argument( "target", help="pytest target (directory, file, or nodeid)" )
    parser.add_argument( "--allow-thread", action="append", default=[], metavar="NAME",
                         help="thread name whose exclusive lines are known-legitimate; repeatable" )
    parser.add_argument( "--json", default=None, help="write the findings to this path as JSON" )
    parser.add_argument( "--quiet", action="store_true", help="print the verdict line only" )
    parser.add_argument( "pytest_args", nargs="*", help="extra args passed through to pytest" )
    args = parser.parse_args( argv )

    try:
        root = _project_root()
        with tempfile.TemporaryDirectory( prefix="thread-attrib-" ) as workdir:
            out_path    = os.path.join( workdir, "attrib.json" )
            attribution = _run_attributed( args.target, root, out_path, args.pytest_args )
    except RuntimeError as e:
        print( f"[thread-credited] CANNOT ATTRIBUTE: {e}", file=sys.stderr )
        return 2

    findings = exclusive_lines( attribution, set( args.allow_thread ) )

    if args.json:
        with open( args.json, "w" ) as fh: json.dump( findings, fh, indent=2, sort_keys=True )

    if not findings:
        print( f"[thread-credited] none - every product line under '{args.target}' was reached by "
               f"the test thread." )
        return 0

    total = sum( len( ls ) for files in findings.values() for ls in files.values() )
    print( f"[thread-credited] {total} line(s) were executed ONLY by a background thread under "
           f"'{args.target}'. No test reached them." )
    if not args.quiet:
        for thread in sorted( findings ):
            print( f"  thread {thread!r}:" )
            for fn in sorted( findings[ thread ] ):
                lines = findings[ thread ][ fn ]
                print( f"    {len( lines ):5d}  {fn}" )
                print( f"           {lines}" )
    return 1


if __name__ == "__main__":
    sys.exit( main() )
