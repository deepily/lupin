#!/usr/bin/env python3
"""
Find assertions whose expected values are INTERCHANGEABLE — a triage aid for one
recognisable sub-shape of fixture blindness.

WHAT THIS FINDS, AND IT IS NARROW ON PURPOSE
--------------------------------------------
CLAUDE.md's fourth reading of a surviving mutant: an assertion can be present, correct,
and named for exactly the thing that broke, while the FIXTURE cannot tell the difference.
The mechanically-findable case is **values that repeat**:

    assert result == { "migrated": 1, "skipped": 1 }   # swapping them changes nothing
    assert counts  == ( 1, 1 )                          # same
    assert params  == { "limit": 0, "offset": 0 }       # same

If two expected values are equal, then swapping the two things they describe cannot
change the outcome — so that assertion measures their SUM, not their identity, whatever
its name says. `{ "migrated": 2, "skipped": 1 }` discriminates; `1 / 1` does not.

🔴 WHAT THIS IS NOT, AND THE DISTINCTION IS THE WHOLE POINT
----------------------------------------------------------
**It finds BLIND ASSERTIONS. It does not find UNDEFENDED BEHAVIOUR.** Discrimination
very often lives in a SIBLING assertion this probe cannot see:

    assert first[ "alpha" ]  == ( 1, 1 )   # flagged — blind on its own
    assert second[ "alpha" ] == ( 1, 0 )   # not flagged — and it covers the swap

Measured 2026-08-30 on the first two hits adjudicated: BOTH were covered elsewhere. One
by the adjacent line above; one — `{ "limit": 0, "offset": 0 }` — by two sibling tests in
the same file, confirmed by actually swapping `limit` and `offset` in the source
(mutated sha `80a636b90dea`, rc=1).

⇒ **Every hit still needs a mutation to adjudicate.** This narrows WHERE to point one.
A repeat is legal, common, and usually fine. Treating this output as a defect list would
be an instrument certifying itself by counting hits nobody adjudicated — which is the
exact failure the probe exists to help find.

EXIT CODES
    0  scanned, no interchangeable-value assertions found
    1  findings present (a TRIAGE queue, never a defect count)
    2  nothing could be scanned — no readable files matched

Usage:
    PYTHONPATH=src python src/scripts/find_interchangeable_assertions.py [ROOT]
                                                                        [--json]
                                                                        [--limit N]
"""

import argparse
import ast
import collections
import json
import os
import sys

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root is None:
    raise RuntimeError( "LUPIN_ROOT not set — export LUPIN_ROOT=/path/to/project" )
src_path = os.path.join( lupin_root, "src" )
if src_path not in sys.path: sys.path.insert( 0, src_path )


DEFAULT_ROOT = "src/tests"
TEST_GLOB    = "test_*.py"


def literal_of( node ):
    """
    The comparable literal a node carries, or None when it is not a plain literal.

    Requires:
        - node is any AST node

    Ensures:
        - returns repr( value ) for an int / str / float / bool constant
        - returns None for everything else, including None itself — an expression
          this probe cannot compare is not evidence of anything
        - never raises
    """
    if isinstance( node, ast.Constant ) and isinstance( node.value, ( int, str, float, bool ) ):
        return repr( node.value )
    return None


def repeated_in( node ):
    """
    The repeated literal inside one dict / tuple / list node, or None.

    Requires:
        - node is any AST node

    Ensures:
        - returns ( value, times, total ) when the node is a Dict/Tuple/List whose
          elements are ALL plain literals, there are at least 2 of them, and at least
          one value appears more than once
        - returns None when the container is uniform-free (every value distinct), too
          short, mixed with non-literals, or not a container at all
        - a container of entirely-equal values reports times == total
        - never raises
    """
    if   isinstance( node, ast.Dict ):                     values = node.values
    elif isinstance( node, ( ast.Tuple, ast.List ) ):      values = node.elts
    else:                                                  return None

    literals = [ literal_of( value ) for value in values ]
    if len( literals ) < 2 or any( item is None for item in literals ): return None

    counts       = collections.Counter( literals )
    value, times = counts.most_common( 1 )[ 0 ]
    if times < 2: return None
    return ( value, times, len( literals ) )


def findings_in_source( text, path ):
    """
    Every interchangeable-value assertion in one source file.

    Requires:
        - text is the file's source; path is its display name

    Ensures:
        - returns a list of dicts with path / line / value / times / total, in source
          order, at most ONE per assert statement (the first container that repeats)
        - returns [ ] for a file with no asserts, and for one that does not parse —
          an unparseable file is not a finding
        - never raises
    """
    try:
        tree = ast.parse( text )
    except ( SyntaxError, ValueError ):
        return [ ]

    findings = [ ]
    for node in ast.walk( tree ):
        if not isinstance( node, ast.Assert ): continue
        for sub in ast.walk( node.test ):
            repeated = repeated_in( sub )
            if repeated is None: continue
            value, times, total = repeated
            findings.append( {
                "path"  : path,
                "line"  : node.lineno,
                "value" : value,
                "times" : times,
                "total" : total,
            } )
            break
    return sorted( findings, key=lambda item: item[ "line" ] )


def scan( paths, read_fn ):
    """
    Scan every path and return ( findings, files_read ).

    Requires:
        - paths is an iterable of file paths
        - read_fn( path ) -> source text, or raises when unreadable

    Ensures:
        - a path that cannot be read is SKIPPED and not counted in files_read, so an
          unreadable file never reports as a clean one
        - returns ( findings, files_read ) with findings in ( path, line ) order
        - never raises
    """
    findings   = [ ]
    files_read = 0
    for path in paths:
        try:
            text = read_fn( path )
        except Exception:
            continue
        files_read += 1
        findings.extend( findings_in_source( text, path ) )
    return ( sorted( findings, key=lambda item: ( item[ "path" ], item[ "line" ] ) ), files_read )


def _default_paths( root ):   # pragma: no cover - filesystem seam
    """Ensures: sorted test-file paths under `root`."""
    import pathlib
    return [ str( p ) for p in sorted( pathlib.Path( root ).rglob( TEST_GLOB ) ) ]


def _default_read( path ):    # pragma: no cover - filesystem seam
    """Ensures: the file's text."""
    with open( path, encoding="utf-8" ) as handle: return handle.read()


def render( findings, files_read, limit ):
    """
    The human-readable report, INCLUDING the caveat that makes it usable.

    Requires:
        - findings is scan()'s list; files_read is its count; limit is a positive int

    Ensures:
        - the caveat is printed whether or not there are findings — a triage aid that
          hides its own boundary is the thing it exists to catch
        - at most `limit` sites are listed, and the count of any remainder is stated
        - never raises
    """
    print( f"\nINTERCHANGEABLE-VALUE ASSERTIONS — {files_read} test files scanned\n" )
    for finding in findings[ :limit ]:
        print( f"  {finding[ 'path' ]}:{finding[ 'line' ]}  "
               f"value {finding[ 'value' ]} appears {finding[ 'times' ]} of {finding[ 'total' ]}" )
    if len( findings ) > limit:
        print( f"  … and {len( findings ) - limit} more (raise --limit to see them)" )
    if not findings:
        print( "  (none — no assertion compares against a container whose values repeat)" )

    print( "\nWHAT THIS LIST IS — read before filing anything" )
    print( "  FINDS      : assertions whose expected values REPEAT, so a swap between the two"
           " things they describe cannot change the outcome." )
    print( "  DOES NOT   : find undefended behaviour. Discrimination often lives in a SIBLING"
           " assertion this probe cannot see." )
    print( "  MEASURED   : the first two hits adjudicated (2026-08-30) were BOTH covered"
           " elsewhere — one by the adjacent line, one by two sibling tests." )
    print( "  SO         : every hit needs a mutation to adjudicate. This narrows where to point"
           " one; it does not replace one, and it is NEVER a defect count." )


def main( argv=None ):
    """
    Requires:
        - argv is a list of command-line arguments, or None for sys.argv[ 1: ]

    Ensures:
        - returns 2 when no file could be read, 1 when findings exist, else 0
        - --json emits the findings plus files_read and the caveat key
        - never raises
    """
    parser = argparse.ArgumentParser( description="Find assertions whose expected values are interchangeable" )
    parser.add_argument( "root", nargs="?", default=DEFAULT_ROOT )
    parser.add_argument( "--json", action="store_true", help="emit findings as JSON" )
    parser.add_argument( "--limit", type=int, default=40, help="how many sites to print" )
    args = parser.parse_args( argv )

    findings, files_read = scan( _default_paths( args.root ), _default_read )

    if files_read == 0:
        print( f"✗ no readable test files under {args.root} — this is NOT a clean result",
               file=sys.stderr )
        return 2

    if args.json:
        print( json.dumps( {
            "files_read" : files_read,
            "findings"   : findings,
            "caveat"     : ( "Blind ASSERTIONS, not undefended BEHAVIOUR. Discrimination often "
                             "lives in a sibling assertion this probe cannot see; every hit needs "
                             "a mutation to adjudicate. Never a defect count." ),
        }, indent=2 ) )
    else:
        render( findings, files_read, args.limit )

    return 1 if findings else 0


if __name__ == "__main__":   # pragma: no cover - entry point
    sys.exit( main() )
