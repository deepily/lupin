"""
The fresh-needs driver: the confirmation run on 30 needs, built on the flip driver.

The fresh-needs file is named here and opened by this driver alone: the shared reader refuses its hash for every other caller.
The token estimate is shown in three parts: the run, the canary and the full-sweep sample.
The sample is picked by a seed and recorded once, with the arm and index it was taken for, before the canary can start.
The sample sweeps are their own step; the flip driver's steps carry the confirmation's settings fixed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr

FRESH_NEEDS_NAME    = "2026.10.14-wa-fresh-needs-30.json"
FRESH_NEEDS_DIR     = "lupin/wa-john-2026.10.14"
PREFIX              = "p5"
SAMPLE_PREFIX       = "p5s"
SAMPLE_FILE         = "p5-sample.json"
REPEATS             = rf.MIN_REPEATS
SAMPLE_SIZE         = 10
PER_SEARCH_TOKENS   = 2_453_600                      # 306.7 M tokens over 125 full-sweep searches of the new question, John's saved run
CANARY_TOKENS       = 61_400_000                     # John's measured canary of 5 needs at 5 repeats
DOLLARS_PER_MILLION = 0.042                          # the ledger's price, John's close-out table


def estimate_parts( needs, repeats=REPEATS, sample=SAMPLE_SIZE ):
    """
    Work out the token estimate in its three parts.

    Requires:
        - needs, repeats and sample are positive whole numbers; needs is the count of the needs file's own rows
    Ensures:
        - returns { run, canary, sample, total }: run is needs x repeats searches, canary is John's measured canary, sample is one full-sweep search per sampled need
        - total is the sum of the three parts
    """
    run    = needs * repeats * PER_SEARCH_TOKENS
    smpl   = sample * PER_SEARCH_TOKENS
    return { "run": run, "canary": CANARY_TOKENS, "sample": smpl, "total": run + CANARY_TOKENS + smpl }


def estimate_lines( parts, needs ):
    """
    Write the estimate as lines, each part and the total with dollars and tokens per need.

    Requires:
        - parts is the result of estimate_parts; needs is the count it was worked for
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
    Refuse a hash that is not the reserved file's.

    Requires:
        - sha is the full sha256 given on the command line
    Ensures:
        - returns the sha when it starts with the reserved prefix the shared reader refuses for everyone else
    Raises:
        - FrozenInputRefused when it does not
    """
    if not isinstance( sha, str ) or not sha.startswith( e2e.FRESH_SHA_PREFIX ): raise e2e.FrozenInputRefused( f"the fresh-needs hash must start with {e2e.FRESH_SHA_PREFIX}, got {str( sha )[ :12 ]!r}" )
    return sha


def load_items( args ):
    """
    Read the checked fresh-needs file, as the one caller the shared reader allows.

    Requires:
        - args carry projects_data and needs_sha
    Ensures:
        - returns the flip driver's items in file order
    """
    return frun.load_flip_needs( needs_path( args.projects_data ), check_sha( args.needs_sha ), allow_fresh=True )


def write_sample( data, items, args ):
    """
    Record the sample once: seed, members, needs hash, arm and index hash.

    Requires:
        - data is the run's data directory; items are the needs file's items; args carry seed, needs_sha, arm and index_sha
    Ensures:
        - returns the record; the file is written the first time and never changed
        - a later call with the same seed, hash, arm and index returns the same record
    Raises:
        - DriverRefused when a record exists with another seed, hash, arm or index
    """
    record = { "format": "reuse-phase5-sample-1", "seed": args.seed, "members": pick_sample( items, args.seed ), "needs_sha": args.needs_sha,
               "arm": args.arm, "index_sha": args.index_sha }
    path = Path( data ) / SAMPLE_FILE
    Path( data ).mkdir( parents=True, exist_ok=True )
    try:
        with open( path, "x", encoding="utf-8" ) as handle: handle.write( json.dumps( record, sort_keys=True, indent=1 ) + "\n" )
        return record
    except FileExistsError: held = load_record( path )                                           # exclusive create: two callers cannot both write
    if held != record: raise s1.DriverRefused( f"the sample is already recorded as {held[ 'seed' ]!r} for arm {held[ 'arm' ]!r}, index {held[ 'index_sha' ]}; a different seed, arm or index is refused" )
    return held


def load_record( path ):
    """
    Read the sample record.

    Requires:
        - path names the record file
    Ensures:
        - returns the record as a dict
    Raises:
        - DriverRefused when the file is not a JSON object, so a cut-off write is a refusal and not a traceback
    """
    try: record = json.loads( Path( path ).read_text( encoding="utf-8" ) )
    except ValueError as e: raise s1.DriverRefused( f"the sample record {path} is not readable: {e}" ) from e
    if not isinstance( record, dict ): raise s1.DriverRefused( f"the sample record {path} is not a JSON object" )
    return record


def sample_sha( data ):
    """
    Hash the sample record file.

    Requires:
        - the record exists in data
    Ensures:
        - returns the sha256 of the file's bytes, which each result carries
    """
    return hashlib.sha256( ( Path( data ) / SAMPLE_FILE ).read_bytes() ).hexdigest()


def result_path( data, run_name ):
    """Ensures: returns the path of the run's result file under the data directory."""
    return Path( data ) / "e2e-results" / f"{run_name}.json"


def check_stamps( data, sha, strict ):
    """
    Refuse a result with another sample hash than the file's, and name the ones with none.

    Requires:
        - sha is the sample file's sha256
    Ensures:
        - returns the names of the existing results that carry no sample hash, in the order canary, run, sweep
        - a result that carries a hash other than sha is refused
        - with strict, a result that carries none is refused too
    Raises:
        - DriverRefused naming the result and the hashes
    """
    missing = []
    for name in ( f"{PREFIX}-canary", f"{PREFIX}-run", f"{SAMPLE_PREFIX}-sample" ):
        path = result_path( data, name )
        if not path.exists(): continue
        record = json.loads( path.read_text( encoding="utf-8" ) )
        if "sample_sha256" not in record:
            if strict: raise s1.DriverRefused( f"result {name} carries no sample hash, so it cannot be tied to the recorded sample" )
            missing.append( name )
        elif record[ "sample_sha256" ] != sha: raise s1.DriverRefused( f"result {name} carries sample hash {record[ 'sample_sha256' ]}, but the sample file's is {sha}" )
    return missing


def canary_approved( data ):
    """
    Say whether the confirmation's canary has been run and approved.

    Ensures:
        - returns true only when the canary's report exists and holds an approval
    """
    path = Path( data ) / "e2e-results" / f"{PREFIX}-canary.canary.json"
    return path.exists() and json.loads( path.read_text( encoding="utf-8" ) )[ "approved" ] is not None


def read_sample( data, needs_sha ):
    """
    Read the recorded sample, which every step that spends or reports needs first.

    Requires:
        - data is the run's data directory; needs_sha is the hash the step was given
    Ensures:
        - returns the record
    Raises:
        - DriverRefused when no sample is recorded, or it was recorded for another needs file
    """
    path = Path( data ) / SAMPLE_FILE
    if not path.exists(): raise s1.DriverRefused( f"no sample is recorded in {data}; run the sample step first, with the seed written down before the canary" )
    record = load_record( path )
    if record[ "needs_sha" ] != needs_sha: raise s1.DriverRefused( f"the sample was recorded for needs file {record[ 'needs_sha' ]}, not {needs_sha}" )
    return record


def flip_argv( args, parts ):
    """
    Build the flip driver's arguments with the confirmation's settings fixed.

    Requires:
        - args are the parsed confirmation options; parts is the result of estimate_parts
    Ensures:
        - the question is new, the route is full, repeats are 5, the prefix is p5 and the estimate is the run and the canary
        - the sample sweeps are their own step, so their part is not in the estimate the canary and the run are held to
        - the needs path and hash are the reserved file's
    """
    spent = parts[ "run" ] + parts[ "canary" ]
    argv  = [ "--root", args.root, "--data", args.data, "--ledger", args.ledger, "--pack-size", str( args.pack_size ),
              "--prefix", PREFIX, "--estimate-tokens", str( spent ), "--repeats", str( REPEATS ), "--route", "full", "--question", "new" ]
    if args.live: argv.insert( 6, "--live" )
    argv += [ args.command, "--needs", needs_path( args.projects_data ), "--needs-sha", check_sha( args.needs_sha ) ]
    if args.command in ( "canary", "run" ): argv += [ "--ceiling", str( args.ceiling ) ]
    if args.command == "approve": argv += [ "--by", args.by, "--why", args.why ]
    return argv


def sweep( args, items, record, parts, sha ):
    """
    Run the sample's full sweeps: one new-question search per sampled need.

    Requires:
        - record is the recorded sample; items are the needs file's items; parts is the estimate; sha is the sample file's hash
    Ensures:
        - returns 0 after printing how the run ended, with the sample file's hash on the result
        - nothing is sent when a check refuses; the sample run is its own ledger run, p5s-sample, kept apart from the repeats
        - the canary must be approved first, and the ceiling may not exceed the sample estimate times the estimate factor
    Raises:
        - CanaryNotApproved when the canary has not been approved; DriverRefused for a ceiling above the cap
    """
    if not canary_approved( args.data ): raise s1.CanaryNotApproved( "the canary has not been approved, so the sample sweeps cannot spend" )
    cap = int( e2r.ESTIMATE_FACTOR * parts[ "sample" ] )
    if args.ceiling > cap: raise s1.DriverRefused( f"the sweep ceiling {args.ceiling} is above {cap}, the sample estimate times {e2r.ESTIMATE_FACTOR}" )
    chosen = [ i for i in items if i[ "member" ] in set( record[ "members" ] ) ]
    env    = e2r._open_env( args.root, args.data, args.ledger, args.live, frun.repeat_asks( 1, "full", frun.QUESTION_NAMES[ "new" ] ), args.pack_size )
    frun.check_excludes( chosen, env.root, env.data )
    print( e2r.run_line( e2r.run_searches( env, f"{SAMPLE_PREFIX}-sample", chosen, {}, args.ceiling, stamp={ "sample_sha256": sha } ) ) )
    return 0


def _parser():
    """Ensures: returns the command line parser."""
    ap  = argparse.ArgumentParser( description=__doc__ )
    sub = ap.add_subparsers( dest="command", required=True )
    p = sub.add_parser( "check" )
    for flag in ( "--projects-data", "--needs-sha", "--root", "--data" ): p.add_argument( flag, required=True )
    for name in ( "estimate", "sample", "sweep", "canary", "approve", "run", "report" ):
        p = sub.add_parser( name )
        p.add_argument( "--projects-data", required=True )
        p.add_argument( "--needs-sha", required=True )
        if name != "estimate": p.add_argument( "--data", required=True )
        if name == "sample":
            p.add_argument( "--seed", required=True )
            p.add_argument( "--arm", required=True )
            p.add_argument( "--index-sha", required=True )
        elif name != "estimate":
            p.add_argument( "--root", required=True )
            p.add_argument( "--ledger", required=True )
            p.add_argument( "--pack-size", type=int, default=50 )
            p.add_argument( "--live", action="store_true" )
        if name in ( "canary", "run", "sweep" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
    return ap


def main( argv=None ):
    """
    Run one step of the fresh-needs confirmation.

    Ensures:
        - check sends nothing: it prints each need whose excluded symbol is not a sendable entry of the index of --root, and returns 2 when there is one
        - estimate prints the three parts for the file's own count of needs; sample records the seed, members, arm and index once and prints the record
        - sweep, canary, approve, run and report need the recorded sample first, so a step that spends is refused without it
        - canary, approve, run and report hand the flip driver the fixed settings and return its code, 2 after a refusal of its own
        - each write of a canary, run or sweep result carries the sample file's sha256, so a run that stops partway still leaves a stamped file
        - a result whose hash differs is refused by every later step; one that carries none is refused by a step that spends and is named and skipped by report
        - report also prints the recorded sample
    Raises:
        - the refusals of the pinned hash, the seed, the sample record and the sample size, before anything is sent
    """
    args  = _parser().parse_args( argv )
    items = load_items( args )
    parts = estimate_parts( len( items ) )
    if args.command == "estimate":
        print( "\n".join( estimate_lines( parts, len( items ) ) ) )
        return 0
    if args.command == "check":
        known = frun.sendable_ids( Path( args.root ), Path( args.data ) )
        if known is None: raise s1.DriverRefused( f"the index of {args.root} cannot be read, so the fresh needs cannot be checked against it" )
        stale = frun.stale_excludes( items, known )
        print( f"{len( items ) - len( stale )} of {len( items )} needs leave out a sendable entry or none" + ( f"; not sendable: {', '.join( stale )}" if stale else "" ) )
        return 2 if stale else 0
    if args.command == "sample":
        print( json.dumps( write_sample( args.data, items, args ), sort_keys=True ) )
        return 0
    record = read_sample( args.data, args.needs_sha )
    sha    = sample_sha( args.data )
    missing = check_stamps( args.data, sha, strict=args.command != "report" )
    if args.command == "sweep": return sweep( args, items, record, parts, sha )
    skip = tuple( name[ len( PREFIX ) + 1: ] for name in missing if name.startswith( f"{PREFIX}-" ) )
    if missing: print( f"skipped, no sample hash: {', '.join( missing )}" )
    code = frun.cli( flip_argv( args, parts ), allow_fresh=True, stamp={ "sample_sha256": sha }, skip_results=skip )
    if args.command == "report": print( f"sample: seed {record[ 'seed' ]!r}, arm {record[ 'arm' ]!r}, index {record[ 'index_sha' ]}, members {', '.join( record[ 'members' ] )}" )
    return code


def cli( argv=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the driver, the sweep or the frozen needs
        - the flip driver's own refusals are returned as it returns them
    """
    return rr.run_cli( lambda: main( argv ),
                       ( s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, e2e.FrozenInputRefused ) )


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    sys.exit( cli() )
