#!/usr/bin/env python3
"""
Detector for row beffcddd — assertions that CANNOT fail the test they live in.

THE DEFECT. An `assert` inside a `try` whose `except` catches Exception (or
BaseException, or AssertionError) and neither re-raises nor fails. AssertionError
IS an Exception, so a failed assertion is caught and logged and the test goes
green. These lines still EXECUTE, so the coverage gate counts them as covered:
100% coverage over assertions that prove nothing.

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


def main():
    roots = sys.argv[ 1: ] or [ "src/tests", "src/cosa/tests" ]
    hits  = sorted( scan( roots ) )
    for path, name, lineno, dead in hits:
        print( f"{dead:3d} dead assert(s)  {path}::{name}  (try at line {lineno})" )
    files = len( { h[ 0 ] for h in hits } )
    print( f"\nTOTAL: {len( hits )} test functions, {sum( h[ 3 ] for h in hits )} "
           f"dead assertions, across {files} files" )
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit( main() )
