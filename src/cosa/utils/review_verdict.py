"""
The review verdict gate: one line naming the tree, the census result and Merge or Fix.

A reviewer runs `src/scripts/review-verdict.sh --verdict Merge|Fix` at the sha under review.
The script refuses a dirty tree and runs `src/tests/run-census-guards.sh`, or reads a log of it
with --census-log. It refuses a census that ran on another tree and prints one `REVIEW-VERDICT` line.
The merger runs `--check "<line>"`. That refuses a verdict with no census count, one for another tree,
and Merge over a red census.

Reuses lupin_mcp.reuse_harness.commands.run_command for every command. Venue: :7999-eligible apart from the census run, which has its own rules.
"""
import argparse
import os
import re
from functools import partial

from lupin_mcp.reuse_harness.commands import run_command

VERDICTS    = ( "Merge", "Fix" )
LINE_SHAPE  = re.compile( r"^REVIEW-VERDICT sha=([0-9a-f]{12}) census=(\d+)p/(\d+)f/(\d+)e verdict=(Merge|Fix)$" )
TREE_SHAPE  = re.compile( r"\[tree-state\] sha=([0-9a-f]+)" )
SUMMARY     = re.compile( r"^=*\s*\d+ [a-z]+(?:, \d+ [a-z]+)* in \d+(?:\.\d+)?s(?: \(\d+:\d{2}:\d{2}\))?\s*=*$" )
COUNT       = re.compile( r"(\d+) (passed|failed|errors?)\b" )
SHA_LENGTH  = 12
CENSUS_SECONDS = 1800


def parse_census( text ):
    """
    Read the tree sha and the result counts from a census run's output.

    Requires:
        - text is the output of src/tests/run-census-guards.sh

    Ensures:
        - returns { sha, passed, failed, errors } from the first [tree-state] line and the last pytest summary line

    Raises:
        - ValueError when the output has no tree-state line or no pytest summary
    """
    tree = TREE_SHAPE.search( text )
    if tree is None: raise ValueError( "the census output has no tree-state line, so it names no tree" )
    summaries = [ l for l in text.splitlines() if SUMMARY.match( l.strip() ) ]
    if not summaries: raise ValueError( "the census output has no pytest summary line, so the guards may not have run" )
    counts = { "passed": 0, "failed": 0, "errors": 0 }
    for n, word in COUNT.findall( summaries[ -1 ] ): counts[ "errors" if word.startswith( "error" ) else word ] += int( n )
    return { "sha": tree.group( 1 ), **counts }


def require_clean_for_merge( verdict, passed, failed, errors ):
    """Raises: ValueError when Merge is given over a census that is empty or red."""
    if verdict == "Merge" and passed == 0: raise ValueError( "Merge with no passed tests in the census is refused; a census that ran nothing proves nothing" )
    if verdict == "Merge" and ( failed or errors ): raise ValueError( f"Merge with {failed} failed and {errors} errors in the census is refused; the verdict is Fix" )


def verdict_line( head, census, verdict ):
    """
    Build the one verdict line for the tree at head.

    Requires:
        - head is the full sha of the tree under review; census is parse_census's answer

    Ensures:
        - returns `REVIEW-VERDICT sha=<12 hex> census=<p>p/<f>f/<e>e verdict=<Merge|Fix>`

    Raises:
        - ValueError when the verdict is not Merge or Fix, the census ran on another tree, or Merge is given over a red census
    """
    if verdict not in VERDICTS: raise ValueError( f"verdict must be one of {VERDICTS}, got {verdict!r}" )
    if not ( head.startswith( census[ "sha" ] ) or census[ "sha" ].startswith( head ) ): raise ValueError( f"the census ran on {census[ 'sha' ]}, the tree under review is {head[ :SHA_LENGTH ]}" )
    require_clean_for_merge( verdict, census[ "passed" ], census[ "failed" ], census[ "errors" ] )
    return f"REVIEW-VERDICT sha={head[ :SHA_LENGTH ]} census={census[ 'passed' ]}p/{census[ 'failed' ]}f/{census[ 'errors' ]}e verdict={verdict}"


def check_line( line, head ):
    """
    Check a verdict line against the tree about to be merged.

    Ensures:
        - returns { sha, passed, failed, errors, verdict } when the line has a census count, names head, and is not Merge over a red census

    Raises:
        - ValueError otherwise, with the reason
    """
    shape = LINE_SHAPE.match( line.strip() )
    if shape is None: raise ValueError( "the verdict carries no census count in the REVIEW-VERDICT line shape" )
    sha, passed, failed, errors, verdict = shape.groups()
    if not head.startswith( sha ): raise ValueError( f"the verdict is for {sha}, the tree is {head[ :SHA_LENGTH ]}" )
    require_clean_for_merge( verdict, int( passed ), int( failed ), int( errors ) )
    return { "sha": sha, "passed": int( passed ), "failed": int( failed ), "errors": int( errors ), "verdict": verdict }


def main( argv=None, run=None, out=print ):
    """
    Print the verdict line for the tree at HEAD, or check a line given with --check.

    Ensures:
        - returns 0 after printing the line; returns 2 after printing the refusal, which names the cause
        - run is None for lupin_mcp.reuse_harness.commands.run_command in LUPIN_ROOT with a CENSUS_SECONDS timeout, or a stand-in taking one command list
        - building a verdict refuses a tree with tracked changes, since the census would describe other bytes
    """
    parser = argparse.ArgumentParser( description="Print or check a review verdict line." )
    group  = parser.add_mutually_exclusive_group( required=True )
    group.add_argument( "--verdict", choices=VERDICTS )
    group.add_argument( "--check", metavar="LINE" )
    parser.add_argument( "--census-log" )
    args = parser.parse_args( argv )
    if run is None: run = partial( run_command, cwd=os.environ.get( "LUPIN_ROOT" ), timeout=CENSUS_SECONDS )
    head = run( [ "git", "rev-parse", "HEAD" ] )[ 1 ].strip()
    try:
        if args.check is not None: line = args.check.strip(); check_line( line, head )
        else:
            if run( [ "git", "status", "--porcelain", "--untracked-files=no" ] )[ 1 ].strip(): raise ValueError( "the tree has tracked changes; commit them so the census describes the sha" )
            text = open( args.census_log, encoding="utf-8" ).read() if args.census_log else run( [ "bash", "src/tests/run-census-guards.sh" ] )[ 1 ]
            line = verdict_line( head, parse_census( text ), args.verdict )
    except ValueError as error:
        out( f"review-verdict: refused: {error}" )
        return 2
    out( line )
    return 0


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested with stand-ins
    raise SystemExit( main() )
