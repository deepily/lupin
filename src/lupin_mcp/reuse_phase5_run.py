"""
The fresh-needs driver: the confirmation run on 30 needs, built on the flip driver.

The fresh-needs file is named here and opened by this driver alone, through the flip driver's checked reader.
The token estimate is shown in three parts: the run, the canary and the full-sweep sample.
The sample is picked from the needs by a seed that is written down before the run.
This module sends nothing itself: canary, approve, run and report are the flip driver's steps with the confirmation's settings fixed.
"""
import argparse
import hashlib
import json
import sys

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_stage1 as s1

FRESH_NEEDS_NAME    = "2026.10.14-wa-fresh-needs-30.json"
FRESH_NEEDS_DIR     = "lupin/wa-john-2026.10.14"
FRESH_SHA_PREFIX    = "0a0da7b7"
PREFIX              = "p5"
NEEDS               = 30
REPEATS             = rf.MIN_REPEATS
SAMPLE_SIZE         = 10
PER_SEARCH_TOKENS   = 2_453_600                      # 306.7 M tokens over 125 full-sweep searches of the new question, John's saved run
CANARY_TOKENS       = 61_400_000                     # John's measured canary of 5 needs at 5 repeats
DOLLARS_PER_MILLION = 0.042                          # the ledger's price, John's close-out table


def estimate_parts( needs=NEEDS, repeats=REPEATS, sample=SAMPLE_SIZE ):
    """
    Work out the token estimate in its three parts.

    Requires:
        - needs, repeats and sample are positive whole numbers
    Ensures:
        - returns { run, canary, sample, total }: run is needs x repeats searches, canary is John's measured canary, sample is one full-sweep search per sampled need
        - total is the sum of the three parts
    """
    run    = needs * repeats * PER_SEARCH_TOKENS
    smpl   = sample * PER_SEARCH_TOKENS
    return { "run": run, "canary": CANARY_TOKENS, "sample": smpl, "total": run + CANARY_TOKENS + smpl }


def estimate_lines( parts, needs=NEEDS ):
    """
    Write the estimate as lines, each part and the total with dollars and tokens per need.

    Requires:
        - parts is the result of estimate_parts
    Ensures:
        - returns one line per part, then the total line
    """
    lines = [ f"{name}: {parts[ name ] / 1e6:.1f} M tokens" for name in ( "run", "canary", "sample" ) ]
    total = parts[ "total" ]
    lines.append( f"total: {total / 1e6:.1f} M tokens, about ${total / 1e6 * DOLLARS_PER_MILLION:.2f} at ${DOLLARS_PER_MILLION} per M, {total / needs / 1e6:.2f} M per need (estimate, not measured on this run)" )
    return lines


def pick_sample( items, seed, size=SAMPLE_SIZE ):
    """
    Pick the full-sweep sample by a seed: the same needs for the same seed and file.

    Requires:
        - items are the needs file's items; seed is a non-empty string written down before the run
    Ensures:
        - returns size member ids, in the file's order
        - each need ranks by the sha256 of seed, a colon and its member id, so no random state is involved
    Raises:
        - DriverRefused when the seed is empty or size is not within 1 and the number of needs
    """
    if not isinstance( seed, str ) or not seed.strip(): raise s1.DriverRefused( "the sample seed is a non-empty string written down before the run" )
    if not 1 <= size <= len( items ): raise s1.DriverRefused( f"the sample takes between 1 and {len( items )} needs, got {size!r}" )
    ranked = sorted( items, key=lambda item: hashlib.sha256( f"{seed}:{item[ 'member' ]}".encode( "utf-8" ) ).hexdigest() )
    chosen = { item[ "member" ] for item in ranked[ :size ] }
    return [ item[ "member" ] for item in items if item[ "member" ] in chosen ]


def needs_path( projects_data ):
    """
    Name the fresh-needs file under the projects-data directory.

    Requires:
        - projects_data is the path of the projects-data directory
    Ensures:
        - returns the path as a string; nothing is read
    """
    return f"{projects_data.rstrip( '/' )}/{FRESH_NEEDS_DIR}/{FRESH_NEEDS_NAME}"


def check_sha( sha ):
    """
    Refuse a hash that is not this file's.

    Requires:
        - sha is the full sha256 given on the command line
    Ensures:
        - returns the sha when it starts with the pinned prefix
    Raises:
        - FrozenInputRefused when it does not
    """
    if not isinstance( sha, str ) or not sha.startswith( FRESH_SHA_PREFIX ): raise e2e.FrozenInputRefused( f"the fresh-needs hash must start with {FRESH_SHA_PREFIX}, got {str( sha )[ :12 ]!r}" )
    return sha


def flip_argv( args, parts ):
    """
    Build the flip driver's arguments with the confirmation's settings fixed.

    Requires:
        - args are the parsed confirmation options; parts is the result of estimate_parts
    Ensures:
        - the question is new, the route is full, repeats are 5, the prefix is p5 and the estimate is the total of the parts
        - the needs path and hash are the pinned file's
    """
    argv = [ "--root", args.root, "--data", args.data, "--ledger", args.ledger, "--pack-size", str( args.pack_size ),
             "--prefix", PREFIX, "--estimate-tokens", str( parts[ "total" ] ), "--repeats", str( REPEATS ), "--route", "full", "--question", "new" ]
    if args.live: argv.insert( 6, "--live" )
    argv += [ args.command, "--needs", needs_path( args.projects_data ), "--needs-sha", check_sha( args.needs_sha ) ]
    if args.command in ( "canary", "run" ): argv += [ "--ceiling", str( args.ceiling ) ]
    if args.command == "approve": argv += [ "--by", args.by, "--why", args.why ]
    return argv


def _parser():
    """Ensures: returns the command line parser."""
    ap  = argparse.ArgumentParser( description=__doc__ )
    sub = ap.add_subparsers( dest="command", required=True )
    sub.add_parser( "estimate" )
    p = sub.add_parser( "sample" )
    p.add_argument( "--seed", required=True )
    p.add_argument( "--projects-data", required=True )
    p.add_argument( "--needs-sha", required=True )
    for name in ( "canary", "approve", "run", "report" ):
        p = sub.add_parser( name )
        p.add_argument( "--root", required=True )
        p.add_argument( "--data", required=True )
        p.add_argument( "--ledger", required=True )
        p.add_argument( "--projects-data", required=True )
        p.add_argument( "--needs-sha", required=True )
        p.add_argument( "--pack-size", type=int, default=50 )
        p.add_argument( "--live", action="store_true" )
        if name in ( "canary", "run" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
    return ap


def main( argv=None ):
    """
    Run one step of the fresh-needs confirmation.

    Ensures:
        - estimate prints the three parts and the total; sample prints the seed and the sampled member ids
        - canary, approve, run and report hand the flip driver the fixed settings and return its code, 2 after a refusal of its own
    Raises:
        - the refusals of the pinned hash, the seed and the sample size, before anything is sent
    """
    args  = _parser().parse_args( argv )
    parts = estimate_parts()
    if args.command == "estimate":
        print( "\n".join( estimate_lines( parts ) ) )
        return 0
    if args.command == "sample":
        items = frun.load_flip_needs( needs_path( args.projects_data ), check_sha( args.needs_sha ) )
        print( json.dumps( { "seed": args.seed, "members": pick_sample( items, args.seed ) } ) )
        return 0
    return frun.cli( flip_argv( args, parts ) )


def cli( argv=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the driver or the frozen needs
        - the flip driver's own refusals are returned as it returns them
    """
    try: return main( argv )
    except ( s1.DriverRefused, e2e.FrozenInputRefused ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    sys.exit( cli() )
