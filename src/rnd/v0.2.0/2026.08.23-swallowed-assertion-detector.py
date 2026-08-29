#!/usr/bin/env python3
"""
Detector for row beffcddd — assertions that CANNOT fail the test they live in.

THE DEFECT. An `assert` inside a `try` whose `except` catches Exception (or
BaseException, or AssertionError) and neither re-raises nor fails. AssertionError
IS an Exception, so a failed assertion is caught and logged and the test goes
green. These lines still EXECUTE, so the coverage gate counts them as covered:
100% coverage over assertions that prove nothing.

⚠️ A FLAG IS NOT AUTOMATICALLY WORK — CHECK THE `collected` COLUMN FIRST.
Measured on 2026-08-23 (row beffcddd): of 51 functions this flagged, only SIX were
actually collected by pytest. The other 45 sat in files pytest collects NOTHING from
— a module-level `pytest.skip( allow_module_level=True )` firing on an ImportError,
or test methods hanging off a plain class (`FooUnitTests`) rather than a `Test*` one.
Un-swallowing an assertion in a file that never runs changes nothing. The v2 report
below splits the two so nobody works the wrong 45.

⇒ THE ORIGINAL VERSION OF THIS TOOL DID NOT CHECK COLLECTIBILITY, and its author
(me) reported a count that was ~8x the actionable size. That was a real false-positive
class, not a rounding error. Naming it here rather than quietly fixing it.

WHAT IT DELIBERATELY DOES NOT COUNT, so the number is workable rather than alarming:
  · files not named test_*.py (helpers, runners, comparison suites)
  · functions not named test_* (the quick_smoke_test() idiom, which wraps asserts
    in try/except ON PURPOSE to print a ✗ and return False)
  · handlers that re-raise, call something named *fail*, or return — those report
    the failure by another route and are doing their job

Usage:  python3 2026.08.23-swallowed-assertion-detector.py [root ...]
Exit 1 if any are found, so it can stand as a regression guard once the row closes.

Written by John 🏄🏽 while working row 122f07a1; the shape turned up in four of that
row's own files and generalises well past it.
"""
import ast
import os
import sys

SWALLOWED = { "Exception", "BaseException", "AssertionError" }


def handler_swallows( handler ):
    """True iff this except clause catches AssertionError and does nothing about it."""
    if handler.type is None:
        caught = [ "BaseException" ]
    else:
        t      = handler.type
        parts  = t.elts if isinstance( t, ast.Tuple ) else [ t ]
        caught = [ ast.unparse( e ) for e in parts ]

    if not any( c.split( "." )[ -1 ] in SWALLOWED for c in caught ): return False

    body = list( ast.walk( handler ) )
    if any( isinstance( x, ast.Raise ) for x in body ):                                    return False
    if any( isinstance( x, ast.Call ) and "fail" in ast.unparse( x.func ) for x in body ):  return False
    if any( isinstance( x, ast.Return ) for x in body ):                                    return False
    return True


def scan( roots ):
    """Yield ( path, test_name, try_lineno, dead_assert_count ) for every hit."""
    for root in roots:
        for dirpath, _, filenames in os.walk( root ):
            for filename in filenames:
                if not ( filename.startswith( "test_" ) and filename.endswith( ".py" ) ): continue
                path = os.path.join( dirpath, filename )
                try:
                    tree = ast.parse( open( path, encoding="utf-8" ).read() )
                except SyntaxError:
                    continue
                for func in ast.walk( tree ):
                    if not isinstance( func, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): continue
                    if not func.name.startswith( "test_" ):                                continue
                    for node in ast.walk( func ):
                        if not isinstance( node, ast.Try ):                                 continue
                        if not any( handler_swallows( h ) for h in node.handlers ):         continue
                        dead = sum( 1 for stmt in node.body
                                      for x in ast.walk( stmt ) if isinstance( x, ast.Assert ) )
                        if dead: yield ( path, func.name, node.lineno, dead )


def collected_test_names( path ):
    """
    The test names pytest can actually collect from `path`.

    Returns None if pytest could not be run at all (then collectibility is reported
    as unknown rather than guessed — a tool that guesses here is how the 45 got
    counted as work in the first place).
    """
    import subprocess
    try:
        out = subprocess.run(
            [ sys.executable, "-m", "pytest", path, "--collect-only", "-q",
              "-p", "no:cacheprovider" ],
            capture_output=True, text=True, timeout=180,
        ).stdout
    except Exception:
        return None
    return { line.split( "::" )[ -1 ].split( "[" )[ 0 ] for line in out.splitlines() if "::" in line }


def main():
    roots     = [ a for a in sys.argv[ 1: ] if not a.startswith( "-" ) ] or [ "src/tests", "src/cosa/tests" ]
    fast      = "--no-collect-check" in sys.argv        # skip the pytest subprocess per file
    hits      = sorted( scan( roots ) )

    collected = { }
    if not fast:
        for path in sorted( { h[ 0 ] for h in hits } ):
            collected[ path ] = collected_test_names( path )

    live, dark, unknown = [ ], [ ], [ ]
    for hit in hits:
        names = collected.get( hit[ 0 ], None ) if not fast else None
        if fast or names is None: unknown.append( hit )
        elif hit[ 1 ] in names:  live.append( hit )
        else:                    dark.append( hit )

    def _dump( label, group ):
        if not group: return
        print( f"\n{label}" )
        for path, name, lineno, dead in group:
            print( f"  {dead:3d} dead assert(s)  {path}::{name}  (try at line {lineno})" )

    _dump( "ACTIONABLE — pytest collects these, so the swallowing hides real failures:", live )
    _dump( "NOT RUN BY PYTEST — fix collection FIRST; un-swallowing here changes nothing:", dark )
    _dump( "COLLECTIBILITY UNKNOWN (pytest could not be run):", unknown )

    print( f"\nTOTAL flagged : {len( hits )} functions / {sum( h[ 3 ] for h in hits )} assertions"
           f", across {len( { h[ 0 ] for h in hits } )} files" )
    if not fast:
        print( f"  ACTIONABLE  : {len( live )} functions / {sum( h[ 3 ] for h in live )} assertions" )
        print( f"  NOT RUN     : {len( dark )} functions / {sum( h[ 3 ] for h in dark )} assertions" )

    # Exit non-zero only on ACTIONABLE hits, so this can stand as a regression guard
    # without the never-run population holding the gate red forever.
    return 1 if ( live or ( fast and hits ) ) else 0


if __name__ == "__main__":
    sys.exit( main() )
