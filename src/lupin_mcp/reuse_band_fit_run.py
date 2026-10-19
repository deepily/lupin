"""
The band-fit driver: measures how far Jev's per-entry overlap moves between repeats.

For each need it does one candidates-route lookup, which stores a receipt, then replays that receipt live five times
with replay_impl( rid, ctx, repeat=1..5 ). Every repeat asks the same shortlist again under its own replay keys, so it is a new draw.
The per-entry overlap of each repeat is captured as the sweep returns it, because the public result of a replay holds the verdict only.
The band is a high quantile of how far one draw sits from its entry's mean, never under the labelled set's minimum.

The run is one ledger run for a canary of five needs and one for the rest, as the flip driver does. A person reads the canary first.
Nothing here is chosen by the driver on its own: the quantile, the population limits, the estimate and the ceilings are arguments or constants below.
"""
import argparse
import contextlib
import copy
import hashlib
import json
import math
import os
import pathlib
import sys
import tempfile

from cosa.repo.symindex import labelled_set as ls
from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt

FORMAT            = "band-fit-1"
PREFIX            = "bandfit"
AUTHORIZED_RUN    = "d3f71441-band-repeat-2026.10.15"          # the name Cheech authorized for the row; the ledger prefix above is shorter, since a prefix holds 16 characters
REPEATS           = 5
LOOKUP            = "lookup"
ESTIMATE_TOKENS   = 5_800_000                                  # 30 needs x 6 asks x 128 entries x about 250 tokens, from the flip run's 2,125,705 per full search
PER_ASK_ENTRIES   = 128
TOKENS_PER_ENTRY  = 250
QUANTILE          = 0.95
POP_LOW           = 0.1                                        # an entry whose mean overlap is outside [low, high] sits far from every cut-off, so its jitter does not decide a verdict
POP_HIGH          = 0.9
SENSITIVITY       = ( 0.5, 0.9, 0.95, 0.99, 1.0 )
DECIMALS          = 3                                          # the recorded band is rounded up to this many places


def estimate( needs ):
    """
    Work out the token estimate for a run.

    Requires:
        - needs is a positive whole number
    Ensures:
        - returns needs x ( 1 lookup + the repeats ) x entries per ask x tokens per entry
    """
    return needs * ( 1 + REPEATS ) * PER_ASK_ENTRIES * TOKENS_PER_ENTRY


class Sink:
    """
    What the asks leave behind: the receipt id of each need's lookup.

    Ensures:
        - rids maps a need id to the receipt id of its lookup
    """

    def __init__( self ): self.rids = {}


@contextlib.contextmanager
def capture_replays( taken ):
    """
    Record every sweep a replay repeat makes, by wrapping its sweeper.

    Requires:
        - taken is a list; it gets the result of each sweep
    Ensures:
        - rf.replay_sweeper is restored on the way out, however the block ends
        - the sweeps are unchanged: the wrapper returns what the real sweeper returned
    """
    real = rf.replay_sweeper

    def wrapped( size, workers, run_index, breaker=None ):
        inner = real( size, workers, run_index, breaker )

        def sweeper( ctx, need, entries, **kw ):
            out = inner( ctx, need, entries, **kw )
            taken.append( out )
            return out

        return sweeper

    rf.replay_sweeper = wrapped
    try: yield
    finally: rf.replay_sweeper = real


def overlaps( sweeps ):
    """
    Read the overlap of every answered entry of some sweeps.

    Requires:
        - sweeps are results of sweep_packed
    Ensures:
        - returns ( overlap, invalid ): overlap maps an entry id to p_overlap, which is reuse plus extend, and a later sweep replaces an earlier one for the same entry
        - invalid lists { id, reason } for each answer the verdict layer would call malformed; such an answer has no overlap, and the search that holds one is incomplete
    """
    out, bad = {}, []
    for sw in sweeps:
        for a in sw[ "answers" ]:
            reason = vd.malformed_reason( a[ "probabilities" ] )
            if reason is None: out[ a[ "id" ] ] = vd.call_facts( a[ "probabilities" ] )[ 0 ]
            else: bad.append( { "id": a[ "id" ], "reason": reason } )
    return out, bad


def packed_context( ctx, stage ):
    """
    Give a run's context the candidate stage and the packing the lookup ships with.

    Requires:
        - ctx is the context a run builds for its asks; stage has the candidate stage's interface
    Ensures:
        - returns a copy; the run's own context is not changed
        - packs are cut from the whole shortlist sorted by id, and the request shape is named for it
        - the copy keeps the run's budget, so every send counts against the run's ceiling
    """
    out = copy.copy( ctx )
    out.candidate_stage = stage
    out.sweeper         = rp.packed_sweeper( ctx.pack_size, shape=rp.SHAPE_WHOLE )
    out.request_shape   = rp.SHAPE_WHOLE
    return out


def check_manifest( stage, pinned ):
    """
    Refuse when the stage's vector set is not the pinned one.

    Requires:
        - pinned is None, or the manifest hash the run was started against
    Ensures:
        - returns None when pinned is None or equals the stage's manifest hash
    Raises:
        - DriverRefused naming both hashes otherwise
    """
    if pinned is None: return
    got = stage.manifest()[ "manifest_hash" ]
    if got != pinned: raise s1.DriverRefused( f"the vector set is {got}, the run is pinned to {pinned}" )


def make_asks( stage, sink, repeats=REPEATS, pinned=None ):
    """
    Build the asks of a run: the lookup, then one ask per repeat.

    Requires:
        - stage is a candidate stage; sink is a Sink; repeats is a whole number of 1 or more; pinned is None or a manifest hash
    Ensures:
        - returns { "lookup": ask, "r1": ask, ... }; the order is the order the run asks them in
        - every ask first checks the stage's manifest hash against pinned, so a replaced vector set stops the run before the next send
        - lookup stores a receipt and notes its id in the sink; it is the only ask that writes one
        - rN replays that receipt as repeat N and returns a result shaped for the runner, whose rows hold the repeat and the overlap of every entry
        - rN for a need with no lookup receipt, or a replay that swept nothing, is an error result, so the search is incomplete and says why
    """
    def lookup( ctx, item ):
        check_manifest( stage, pinned )
        result = rt._need_impl( item[ "need" ], item[ "exclude" ], packed_context( ctx, stage ), "choice", False, True )
        if result[ "status" ] == "ok": sink.rids[ item[ "member" ] ] = result[ "receipt_id" ]
        return result

    def make( index ):
        def ask( ctx, item ):
            check_manifest( stage, pinned )
            if item[ "member" ] not in sink.rids: return { "status": "error", "error": "NO_LOOKUP_RECEIPT" }
            taken = []
            with capture_replays( taken ): out = rt.replay_impl( sink.rids[ item[ "member" ] ], packed_context( ctx, stage ), repeat=index )
            if out[ "status" ] != "ok": return out
            if not taken: return { "status": "error", "error": "NO_SWEEP" }
            failed       = sorted( { i for sw in taken for i in sw[ "failed" ] } )
            not_reached  = sorted( { i for sw in taken for i in sw[ "not_reached" ] } )
            seen, invalid = overlaps( taken )
            malformed    = [ m for sw in taken for m in sw[ "malformed" ] ] + invalid
            stopped      = next( ( sw[ "stopped_by" ] for sw in taken if sw[ "stopped_by" ] is not None ), None )
            row          = { "repeat": index, "asked": sum( len( sw[ "answers" ] ) + len( sw[ "failed" ] ) + len( sw[ "not_reached" ] ) for sw in taken ), "p_overlap": seen,
                             "failed": failed, "not_reached": not_reached }
            stats        = { "failed": len( failed ), "not_checked": len( not_reached ), "stopped_by": stopped, "requests": sum( sw[ "requests" ] for sw in taken ) }
            return { "status": "ok", "receipt_id": out[ "receipt_id" ], "verdict": out[ "head" ][ "verdict" ], "shortlist": out[ "head" ][ "shortlist" ], "nearest": [],
                     "malformed": malformed, "stats": stats, "rows": [ row ] }
        return ask

    return { LOOKUP: lookup, **{ f"r{i}": make( i ) for i in range( 1, repeats + 1 ) } }


def quantile( values, q ):
    """
    Take the q quantile of some numbers by nearest rank.

    Requires:
        - values is a non-empty list of numbers; q is above 0 and at most 1
    Ensures:
        - returns the smallest value that at least a fraction q of the values do not exceed
    """
    ordered = sorted( values )
    return ordered[ max( 0, math.ceil( q * len( ordered ) ) - 1 ) ]


def spreads( draws ):
    """
    Describe how far each entry's draws sit from their mean.

    Requires:
        - draws maps a need id to { entry id: [ p_overlap per repeat ] }
    Ensures:
        - returns one record per ( need, entry ) with at least two draws, in need then entry order
        - mean is the mean of the draws, dev the largest distance of one draw from it, and span the largest minus the smallest draw
    """
    out = []
    for need in sorted( draws ):
        for entry in sorted( draws[ need ] ):
            v = draws[ need ][ entry ]
            if len( v ) < 2: continue
            mean = sum( v ) / len( v )
            out.append( { "need": need, "entry": entry, "draws": len( v ), "mean": mean, "dev": max( abs( x - mean ) for x in v ), "span": max( v ) - min( v ) } )
    return out


def fit_band( draws, q=QUANTILE, low=POP_LOW, high=POP_HIGH ):
    """
    Fit the uncertain band from repeat jitter.

    Requires:
        - draws maps a need id to { entry id: [ p_overlap per repeat ] }
        - q is above 0 and at most 1; low is under high
    Ensures:
        - the population is the entries whose mean overlap lies within [ low, high ]: the ones a cut-off can sit near
        - the band is the q quantile of the population's dev, rounded up to three places and not under ls.MIN_BAND
        - returns { band, raw, floored, population, entries, sensitivity }; sensitivity holds the same quantiles of the population, of each need's top entry and of all entries
    Raises:
        - ValueError when the population is empty, or from ls.check_band for a band the labelled set refuses
    """
    rows = spreads( draws )
    pop  = [ r for r in rows if low <= r[ "mean" ] <= high ]
    if not pop: raise ValueError( f"no entry has a mean overlap within {low} to {high}; there is no jitter to fit a band from" )
    tops = []
    for need in sorted( draws ):
        mine = [ r for r in rows if r[ "need" ] == need ]
        if mine: tops.append( max( mine, key=lambda r: ( r[ "mean" ], r[ "entry" ] ) ) )
    raw    = quantile( [ r[ "dev" ] for r in pop ], q )
    scale  = 10 ** DECIMALS
    rounded = math.ceil( round( raw * scale, 6 ) ) / scale
    band   = ls.check_band( max( ls.MIN_BAND, rounded ) )
    table  = lambda group: { str( x ): quantile( [ r[ "dev" ] for r in group ], x ) for x in SENSITIVITY } if group else None
    return { "band": band, "raw": raw, "floored": band == ls.MIN_BAND and rounded < ls.MIN_BAND, "population": len( pop ), "entries": len( rows ),
             "sensitivity": { "population": table( pop ), "top_entry_per_need": table( tops ), "all_entries": table( rows ) } }


def gather( results, members, repeats=REPEATS ):
    """
    Collect the per-entry overlaps of the completed repeats from the runs' result files.

    Requires:
        - results are the parsed result files of the canary and the run; members are the need ids the run covers
    Ensures:
        - returns ( draws, whole, short ): draws maps a need id to { entry id: [ p_overlap per repeat, in repeat order ] }
        - whole lists the needs that have every repeat complete, short the needs that do not, each with the repeats it lacks
        - draws holds the whole needs only
    """
    got = {}
    for run in results:
        for s in run[ "searches" ]:
            if s[ "question" ].startswith( "r" ) and s[ "status" ] == "complete" and s[ "rows" ]: got.setdefault( s[ "member" ], {} )[ s[ "rows" ][ 0 ][ "repeat" ] ] = s[ "rows" ][ 0 ][ "p_overlap" ]
    whole = sorted( m for m in members if sorted( got.get( m, {} ) ) == list( range( 1, repeats + 1 ) ) )
    short = { m: sorted( set( range( 1, repeats + 1 ) ) - set( got.get( m, {} ) ) ) for m in members if m not in whole }
    draws = {}
    for m in whole:
        per = {}
        for r in range( 1, repeats + 1 ):
            for entry, p in got[ m ][ r ].items(): per.setdefault( entry, [] ).append( p )
        draws[ m ] = per
    return draws, whole, short


def _read( path ): return json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )


def receipt( data, items, q, low, high, code_sha, needs_sha ):
    """
    Build the receipt of a finished run.

    Requires:
        - the canary and the run result files are in data; items are the needs file's items
    Ensures:
        - returns the receipt: format, names, inputs, the fitted band with its sensitivity, token totals, the needs that fell short and the raw draws
        - the band is the one fit_band gives, and every draw in the file is the overlap Jev gave in that repeat
    Raises:
        - DriverRefused when the canary or the run has no result file, the two disagree on the stage they ran, no need has all its repeats,
          or the labelled set refuses the band
    """
    paths = [ pathlib.Path( data ) / "e2e-results" / f"{PREFIX}-{part}.json" for part in ( "canary", "run" ) ]
    for p in paths:
        if not p.exists(): raise s1.DriverRefused( f"no result file {p}; run the canary and the run first" )
    results = [ _read( p ) for p in paths ]
    stages  = [ r[ "stage" ] for r in results ]
    if stages[ 0 ] != stages[ 1 ]: raise s1.DriverRefused( f"the canary ran on stage {stages[ 0 ]} but the run on {stages[ 1 ]}" )
    members = [ i[ "member" ] for i in items ]
    draws, whole, short = gather( results, members )
    if not whole: raise s1.DriverRefused( "no need has every repeat complete, so there is no jitter to measure" )
    try: fit = fit_band( draws, q, low, high )
    except ValueError as e: raise s1.DriverRefused( str( e ) ) from e
    return { "format": FORMAT, "authorized_run": AUTHORIZED_RUN, "ledger_runs": [ r[ "run_name" ] for r in results ], "code_sha": code_sha, "needs_sha": needs_sha,
             "stage": stages[ 0 ], "repeats": REPEATS, "quantile": q, "population_limits": [ low, high ], "needs": len( items ), "needs_whole": whole, "needs_short": short,
             "band": fit, "spent_tokens": sum( r[ "totals" ][ "spent_tokens" ] for r in results ),
             "ledger_total_before": results[ 0 ][ "ledger_total_before" ], "started_at": results[ 0 ][ "started_at" ], "ended_at": results[ 1 ][ "ended_at" ], "draws": draws }


def write_once( path, record ):
    """
    Write a JSON record whole, or not at all, under a name that must not exist.

    Ensures:
        - the file appears under its name only when it is complete
    Raises:
        - FileExistsError when the name exists
    """
    path = pathlib.Path( path )
    handle, temporary = tempfile.mkstemp( dir=path.parent, prefix=f".{path.name}.", suffix=".tmp" )
    try:
        with os.fdopen( handle, "w", encoding="utf-8" ) as stream: stream.write( json.dumps( record, indent=1, sort_keys=True ) + "\n" )
        os.link( temporary, path )
    finally:
        os.unlink( temporary )


def stage_record( stage ):
    """Ensures: returns the stage's arm, K and vector-set hash, which each result file carries."""
    return { "arm": stage.arm, "K": stage.K, "manifest_hash": stage.manifest()[ "manifest_hash" ] }


def check_ceiling( ceiling, estimated ):
    """
    Refuse a ceiling above the estimate times the estimate factor.

    Ensures:
        - returns the ceiling when it is at most int( ESTIMATE_FACTOR x estimated )
    Raises:
        - DriverRefused otherwise
    """
    cap = int( e2r.ESTIMATE_FACTOR * estimated )
    if ceiling > cap: raise s1.DriverRefused( f"the ceiling {ceiling} is above {cap}, the estimate times {e2r.ESTIMATE_FACTOR}" )
    return ceiling


def derive_needs( frozen_path, frozen_sha, count, seed ):
    """
    Pick the band fit's needs from the frozen end-to-end needs by a seed.

    Requires:
        - frozen_path names the frozen end-to-end needs file and frozen_sha is its sha256; count is a whole number of at least the flip driver's minimum
        - seed is a non-empty string written down before the pick
    Ensures:
        - returns { format, needs } in the flip needs format, ordered by the sha256 of seed, a colon and the member id
        - ids are b01, b02 and so on in that order; each need is a duplicate-kind need with its own member left out, as the end-to-end run asked it
        - the reserved fresh-needs file is refused by its hash before it is opened, as the shared reader does for every caller
    Raises:
        - FrozenInputRefused for a wrong hash or format, a repeated member or need text, or an empty need
        - DriverRefused for an empty seed or a count above the number of needs, or under the flip driver's minimum
    """
    if not isinstance( seed, str ) or not seed.strip(): raise s1.DriverRefused( "the seed is a non-empty string written down before the pick" )
    record = e2e._read_checked( frozen_path, frozen_sha, "frozen needs file" )
    if record[ "format" ] != e2e.NEEDS_FORMAT: raise e2e.FrozenInputRefused( f"frozen needs file format is {record[ 'format' ]!r}, expected {e2e.NEEDS_FORMAT!r}" )
    rows = record[ "needs" ]
    if len( { r[ "member" ] for r in rows } ) != len( rows ) or len( { r[ "need" ] for r in rows } ) != len( rows ): raise e2e.FrozenInputRefused( "the frozen needs repeat a member or a need text" )
    if any( not isinstance( r[ "need" ], str ) or not r[ "need" ].strip() for r in rows ): raise e2e.FrozenInputRefused( "the frozen needs hold an empty need" )
    if not rf.MIN_NEEDS <= count <= len( rows ): raise s1.DriverRefused( f"the pick takes between {rf.MIN_NEEDS} and {len( rows )} needs, got {count!r}" )
    ranked = sorted( rows, key=lambda r: hashlib.sha256( f"{seed}:{r[ 'member' ]}".encode( "utf-8" ) ).hexdigest() )[ :count ]
    return { "format": frun.NEEDS_FORMAT,
             "needs": [ { "id": f"b{n:02d}", "need": r[ "need" ].strip(), "kind": "duplicate", "exclude": r[ "member" ] } for n, r in enumerate( ranked, 1 ) ] }


def _parser():
    """Ensures: returns the command line parser."""
    ap  = argparse.ArgumentParser( description=__doc__ )
    sub = ap.add_subparsers( dest="command", required=True )
    p   = sub.add_parser( "derive-needs" )
    for flag in ( "--frozen", "--frozen-sha", "--seed", "--out" ): p.add_argument( flag, required=True )
    p.add_argument( "--count", type=int, default=rf.MIN_NEEDS )
    for name in ( "estimate", "canary", "approve", "run", "report" ):
        p = sub.add_parser( name )
        p.add_argument( "--needs", required=True )
        p.add_argument( "--needs-sha", required=True )
        if name == "estimate": continue
        p.add_argument( "--root", required=True )
        p.add_argument( "--data", required=True )
        p.add_argument( "--ledger", required=True )
        p.add_argument( "--live", action="store_true" )
        p.add_argument( "--pack-size", type=int, default=50 )
        if name in ( "canary", "run" ):
            p.add_argument( "--ceiling", type=int, required=True )
            p.add_argument( "--manifest-hash", required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
            p.add_argument( "--revised-estimate", type=int, default=None )
        if name == "report":
            p.add_argument( "--out", required=True )
            p.add_argument( "--code-sha", required=True )
            p.add_argument( "--quantile", type=float, default=QUANTILE )
            p.add_argument( "--pop-low", type=float, default=POP_LOW )
            p.add_argument( "--pop-high", type=float, default=POP_HIGH )
    return ap


def main( argv=None, stage_factory=None ):
    """
    Run one step of the band fit.

    Requires:
        - stage_factory is None for the live candidate stage of the tree, or a function of the tree's path for a stand-in run
    Ensures:
        - derive-needs picks the needs from the frozen end-to-end needs by a seed and writes them once, printing the file's sha256
        - estimate prints the token estimate for the needs file's own count and sends nothing
        - canary asks the first five needs, approve records that a person read it, run asks the rest, and both stamp their result files with the stage
        - report writes the receipt under a name that must not exist, and prints the band
        - a ceiling above the estimate times the estimate factor is refused before anything is opened
    Raises:
        - the refusals of the paths, the frozen needs, the ledger and the canary, before anything is sent
    """
    args  = _parser().parse_args( argv )
    if args.command == "derive-needs":
        record = derive_needs( args.frozen, args.frozen_sha, args.count, args.seed )
        write_once( args.out, record )
        print( f"{len( record[ 'needs' ] )} needs from {args.frozen_sha} by seed {args.seed!r}; sha256 {hashlib.sha256( pathlib.Path( args.out ).read_bytes() ).hexdigest()}" )
        return 0
    items = frun.load_flip_needs( args.needs, args.needs_sha )
    spent = estimate( len( items ) )
    if args.command == "estimate":
        print( f"{len( items )} needs x {1 + REPEATS} asks x {PER_ASK_ENTRIES} entries x {TOKENS_PER_ENTRY} tokens = {spent} tokens; ceiling {int( e2r.ESTIMATE_FACTOR * spent )}" )
        return 0
    data, ledger = rr.check_paths( args.root, args.data, args.ledger, args.live )
    if args.command == "report":
        rec = receipt( data, items, args.quantile, args.pop_low, args.pop_high, args.code_sha, args.needs_sha )
        write_once( args.out, rec )
        print( f"band={rec[ 'band' ][ 'band' ]} raw={rec[ 'band' ][ 'raw' ]:.6f} population={rec[ 'band' ][ 'population' ]} needs={len( rec[ 'needs_whole' ] )} short={len( rec[ 'needs_short' ] )} spent={rec[ 'spent_tokens' ]}" )
        return 0
    if args.command in ( "canary", "run" ): check_ceiling( args.ceiling, spent )
    stage = None if args.command == "approve" else ( stage_factory or rt._candidate_stage )( pathlib.Path( args.root ) )          # approving sends nothing, so it needs no stage
    if stage is not None: check_manifest( stage, args.manifest_hash )
    env   = e2r._open_env( args.root, args.data, args.ledger, args.live, make_asks( stage, Sink(), pinned=args.manifest_hash if stage is not None else None ), args.pack_size )
    spec  = { "prefix": PREFIX, "members": len( items ), "estimate": spent, "canary_members": e2r.CANARY_MEMBERS,
              "stamp": None if stage is None else { "stage": stage_record( stage ), "needs_sha": args.needs_sha } }
    if args.command in ( "canary", "run" ): frun.check_excludes( items, env.root, env.data )
    if args.command == "canary": print( e2r.canary_line( e2r.run_canary( env, items, {}, args.ceiling, spec=spec ) ) )
    elif args.command == "approve":
        e2r.approve_canary( env, args.by, args.why, spec=spec, revised_estimate=args.revised_estimate )
        print( f"canary approved by {args.by}" )
    else: print( e2r.run_line( e2r.run_full( env, items, {}, args.ceiling, spec=spec ) ) )
    return 0


def cli( argv=None, stage_factory=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the runner, the driver, the frozen needs, the ledger or the receipt
        - any other error propagates untouched
    """
    try: return main( argv, stage_factory )
    except ( rr.RunnerRefused, s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, s1.CanaryTripped, s1.StageRefused,
             e2e.FrozenInputRefused, rl.AccountLimitReached, rl.LedgerUnreadable, FileExistsError ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    sys.exit( cli() )
