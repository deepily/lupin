#!/usr/bin/env python3
"""
Detect coverage that a background thread credited, not a test.

A daemon started at import credits product lines nobody tested, and coverage.py counts them like any other.
Example: `session-id-watcher`, started unguarded in `src/lupin_mcp/cosa_voice_mcp.py` and polling every 2.0s.

Usage:
    python src/scripts/detect_thread_credited_coverage.py <pytest-target>
        [--allow-thread NAME]... [--json OUT] [--quiet]

Exit codes:
    0  no call-time thread-credited lines outside the allow-list.
    1  call-time thread-credited lines found. The report names thread, file and lines.
    2  the run failed, so the attribution means nothing.

Notes:
    - The daemon runs for the life of the test process, and on `src/tests/unit/lupin_mcp` 41 `session_bridge.py` statements were covered only by it.
    - Two levers were tried, and this script uses the second, thread attribution.
    - The clock lever runs the scope twice, once held open past the poll interval, and diffs. It shows 15% vs 18% on the same 333 tests.
    - It is a bad detector, because it fires only when the baseline finishes inside one poll.
    - Under subprocess overhead the baseline took 5.6s against a 2.0s poll, so both runs credited the same 134 lines and reported clean.
    - Thread attribution records which thread executed each line and reports lines no test thread reached.
    - It is deterministic, independent of timing, and names the thread.
    - Suppression is not an option: no-op'ing `Thread.start` for the watcher turned 333 passed into a bare failing exit.
    - That daemon resolves the session id, and its failure path ends in `os._exit( 1 )`.
    - A module-scope declaration (a `class` statement, dataclass field, dict literal or decorator) executes at import.
    - If the import ran on a worker thread, the tracer credits the declaration to that worker.
    - One sweep found 2,085 of 7,580 reported lines were declarations, 1,840 of them under one thread.
    - They are neither earned nor defects, so they are bucketed, not dropped.
    - Which modules were imported only from a worker thread is a real signal, and it found the lazy-import cascade.
    - The verdict and exit code key on `call_time` alone.
    - call_time is inside a function body, non-test thread, absent from MainThread. This is the finding.
    - module_scope is a declaration executed at import, and allowed is a thread on --allow-thread. Both are reported, never counted.
    - A `def` line is not part of its body, so classification walks `node.body`, never the `lineno..end_lineno` span.
    - A `def` and its decorators execute at import, so crediting them to the body would invent call-time findings.
    - A reported line was executed by a non-test thread and by nothing else, and whether that is a defect depends on the thread.
    - A daemon started at import credits lines nobody tested, which is the defect.
    - A worker thread a test starts for its own work, and then asserts on, is legitimate, since the coverage is earned.
    - The report names the thread so the reader can tell them apart, and it does not decide.
"""
import argparse
import ast
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


def _stmt_span( stmt ):
    """
    The full line span a single statement occupies, decorators included.

    Requires:
        - stmt is an ast statement node carrying lineno/end_lineno

    Ensures:
        - returns a range covering stmt's own lines
        - a decorated nested def/class starts at its first decorator, because those
          decorator expressions run when the enclosing function is called
    """
    start = stmt.lineno
    if isinstance( stmt, ( ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef ) ):
        for decorator in stmt.decorator_list:
            start = min( start, decorator.lineno )
    end = stmt.end_lineno if stmt.end_lineno is not None else stmt.lineno
    return range( start, end + 1 )


def call_time_lines( source ):
    """
    The line numbers in `source` that execute only when a function is called.

    Requires:
        - source is the full text of a parseable Python module

    Ensures:
        - returns a set of 1-based line numbers belonging to statements inside some
          function body
        - a `def`/`async def` line, and the decorators of a module-scope function, are
          never included on account of the function they introduce - a def executes at
          import, and crediting it to its own body invents call-time lines
        - a class body at module scope is module-scope; the same class body written
          inside a function is call-time
        - raises SyntaxError if source does not parse
    """
    lines = set()
    for node in ast.walk( ast.parse( source ) ):
        if not isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): continue
        for stmt in node.body:
            lines.update( _stmt_span( stmt ) )
    return lines


def make_scope_classifier():
    """
    Build `is_call_time( path, line )`, parsing each file at most once.

    Ensures:
        - returns a callable answering whether that line executes inside a function body
        - a file that cannot be read or parsed answers True for every line: the tool
          must not silently drop a finding it was unable to classify
    """
    cache = {}

    def is_call_time( path, line ):
        if path not in cache:
            try:
                with open( path ) as fh: cache[ path ] = call_time_lines( fh.read() )
            except ( OSError, SyntaxError, ValueError ):
                cache[ path ] = None
        known = cache[ path ]
        if known is None: return True
        return line in known

    return is_call_time


def bucket_findings( attribution, allow_threads, is_call_time ):
    """
    Split the reduction into the three buckets the verdict is read from.

    Requires:
        - attribution maps thread name -> file -> list of line numbers
        - allow_threads is a collection of thread names to bucket as `allowed`
        - is_call_time( path, line ) answers whether a line runs inside a function body

    Ensures:
        - returns { "call_time": {...}, "module_scope": {...}, "allowed": {...} },
          each a {thread: {file: [lines]}} map, every one of them sorted
        - an allow-listed thread lands whole in `allowed` and is never classified,
          so an exemption can never be mistaken for a clean scope
        - only `call_time` is the finding; the other two are reported, never counted
    """
    raw     = exclusive_lines( attribution, set() )
    buckets = { "call_time": {}, "module_scope": {}, "allowed": {} }

    for thread in raw:
        for fn, lines in raw[ thread ].items():
            if thread in allow_threads:
                buckets[ "allowed" ].setdefault( thread, {} )[ fn ] = list( lines )
                continue
            at_call_time = [ ln for ln in lines if is_call_time( fn, ln ) ]
            declared     = [ ln for ln in lines if ln not in set( at_call_time ) ]
            if at_call_time: buckets[ "call_time"    ].setdefault( thread, {} )[ fn ] = at_call_time
            if declared:     buckets[ "module_scope" ].setdefault( thread, {} )[ fn ] = declared

    return buckets


def verdict_exit_code( buckets ):
    """
    The exit code, keyed on `call_time` alone.

    Ensures:
        - returns 1 when any call-time line was found, 0 otherwise
        - module-scope declarations and allow-listed threads never fail the check;
          keying on them would leave the change cosmetic
    """
    return 1 if buckets[ "call_time" ] else 0


def _count( bucket ):
    return sum( len( ls ) for files in bucket.values() for ls in files.values() )


def _print_bucket( bucket ):
    for thread in sorted( bucket ):
        print( f"  thread {thread!r}:" )
        for fn in sorted( bucket[ thread ] ):
            lines = bucket[ thread ][ fn ]
            print( f"    {len( lines ):5d}  {fn}" )
            print( f"           {lines}" )


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

    buckets = bucket_findings( attribution, set( args.allow_thread ), make_scope_classifier() )

    if args.json:
        with open( args.json, "w" ) as fh: json.dump( buckets, fh, indent=2, sort_keys=True )

    call_time = _count( buckets[ "call_time"    ] )
    declared  = _count( buckets[ "module_scope" ] )
    allowed   = _count( buckets[ "allowed"      ] )

    if not call_time:
        print( f"[thread-credited] none - no product line under '{args.target}' was executed inside "
               f"a function body by a background thread alone." )
    else:
        print( f"[thread-credited] {call_time} call-time line(s) were executed ONLY by a background "
               f"thread under '{args.target}'. No test reached them." )
        if not args.quiet: _print_bucket( buckets[ "call_time" ] )

    if declared:
        print( f"[thread-credited] {declared} further line(s) are module-scope declarations executed "
               f"on import by a worker thread. Reported, NOT counted." )
        if not args.quiet: _print_bucket( buckets[ "module_scope" ] )

    if allowed:
        print( f"[thread-credited] {allowed} further line(s) belong to allow-listed thread(s): "
               f"{', '.join( sorted( buckets[ 'allowed' ] ) )}. Reported, NOT counted." )

    return verdict_exit_code( buckets )


if __name__ == "__main__":
    sys.exit( main() )
