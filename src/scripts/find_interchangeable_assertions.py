#!/usr/bin/env python3
"""
Find assertions whose expected values repeat, a triage aid for one shape of blind fixture.

An assertion can be correct and named for what broke while its fixture cannot tell right
from wrong. The one mechanically findable case is expected values that repeat:

    assert result == { "migrated": 1, "skipped": 1 }   # swapping them changes nothing
    assert counts  == ( 1, 1 )                          # same

Equal expected values mean a swap of the things they describe cannot change the outcome.
Such an assertion measures their sum, not their identity.

It finds blind assertions, not undefended behaviour. Discrimination often lives in a sibling
assertion this probe cannot see. A flagged assertion on `( 1, 1 )` can be covered by
a sibling asserting `( 1, 0 )`, which does tell the swap apart.
Both hits adjudicated so far were covered elsewhere. Every hit still needs a mutation. The list is never a defect count.

Recall is the bigger gap. A zero is not an all-clear, because most blind fixtures repeat
no literal at all:

    - no-op: the operation does nothing on this data, as `.zfill( 2 )` does on digits-free input.
    - masked: the code path never runs, as when an earlier clause always matches first.
    - coincidence: the wrong answer equals the right one, as `Path( "" )` does for a file.

Each needs a different repair. A no-op needs data the operation affects. A masked path needs
a call that happens. A coincidence needs an input that separates the two answers. A default that runs at import and is never asserted counts
as covered and is still unchecked. A file with no hits has not been cleared, only not
examined. Recall has no denominator, since nobody can enumerate the blind fixtures that
exist. Quote results as a count against a named sample, never as a bare rate.

Exit codes:
    0  scanned, nothing matched (not an all-clear)
    1  findings present (a triage queue)
    2  nothing could be scanned, no readable files matched

Usage:
    PYTHONPATH=src python src/scripts/find_interchangeable_assertions.py [root]
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
          elements are all plain literals, there are at least 2 of them, and at least
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
          order, at most one per assert statement (the first container that repeats)
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
        - a path that cannot be read is skipped and not counted in files_read, so an
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
    The human-readable report, with the caveat that makes it usable.

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
        # 🔴 A ZERO RUN IS THE OUTPUT MOST LIKELY TO BE MISREAD, so it says so HERE rather
        # than only in the docstring (Chloé, 2026-08-30). A consumer reading stdout never
        # opens this file, and "no findings" from a triage aid reads as an all-clear.
        print( "  NOT FOUND — and NOT the same as none present." )
        print( "  This probe matches REPEATED expected values, the one shape of fixture" )
        print( "  blindness with a syntactic trace. A fixture blind because its value makes" )
        print( "  the operation a no-op, or because the wrong answer coincides with the right" )
        print( "  one, repeats nothing and CANNOT be found here. Measured: it returns zero on" )
        print( "  a file carrying a blind assertion at src/tests/unit/scripts/" )
        print( "  test_watch_hook_events.py. A file with no hits has not been cleared —" )
        print( "  it has not been examined. Only a mutation clears it." )

    print( "\nWHAT THIS LIST IS — read before filing anything" )
    print( "  FINDS      : assertions whose expected values REPEAT, so a swap between the two"
           " things they describe cannot change the outcome." )
    print( "  DOES NOT   : find undefended behaviour. Discrimination often lives in a SIBLING"
           " assertion this probe cannot see." )
    print( "  MEASURED   : the two hits adjudicated so far (2026-08-30) were BOTH covered"
           " elsewhere — one by the adjacent line, one by two sibling tests. Two is the"
           " whole adjudicated sample; there is no larger one." )
    print( "  MISSES     : returns zero on a file that carries a blind assertion — recall is"
           " demonstrably not total, and its rate is unknown (no denominator)." )
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
            "recall"     : ( "An empty findings list is NOT an all-clear. This probe matches "
                             "repeated expected values only — the one shape of fixture blindness "
                             "with a syntactic trace. Blindness from a no-op value, or from a "
                             "wrong answer that coincides with the right one, repeats nothing and "
                             "cannot be found here. Measured: zero hits on a file carrying a blind "
                             "assertion. Recall is demonstrably not total and its rate is unknown." ),
        }, indent=2 ) )
    else:
        render( findings, files_read, args.limit )

    return 1 if findings else 0


if __name__ == "__main__":   # pragma: no cover - entry point
    sys.exit( main() )
