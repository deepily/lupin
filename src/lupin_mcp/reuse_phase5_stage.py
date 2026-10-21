"""
The fresh-needs confirmation through the shipped candidate stage.

Each need gets one candidates-route lookup, then five replays of that lookup for the flip rate.
The vector set is pinned by its manifest hash, the stage never refreshes, and the asks are the band driver's own.
Recall is agreement with the full search on the sampled needs, not ground truth.
Nothing here opens the reserved fresh-needs file: the caller hands over items its own hash-checked reader returned.
"""
import json
import pathlib

from cosa.repo.symindex.candidates import arm_metrics
from lupin_mcp import reuse_band_fit_run as bf
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_flip_run as frun
from lupin_mcp import reuse_stage1 as s1

STAGE_PREFIX = "p5st"
TOP          = 10
ROUTE        = "candidates"
QUESTION     = "choice"
SWEEP_RESULT = "p5s-sample"
SWEEP_ASK    = "r1"


def stage_asks( stage, sink, repeats, pinned ):
    """
    Build the asks of the stage mode: the lookup, then one replay per repeat.

    Requires:
        - stage is a candidate stage with its refresher off; sink is a band Sink; pinned is the manifest hash the run was started against
    Ensures:
        - returns { "lookup": ask, "r1": ask, ... } on the band driver's asks, every one checking the pin before it sends
        - the lookup's row holds the verdict, the sorted shortlist ids and the first ten ids of the stage's ranking
        - each replay's row holds its verdict and sorted shortlist ids beside the overlaps, so the flip report reads it as it reads a flip run
        - an error result is returned as it is
    """
    base = bf.make_asks( stage, sink, repeats, pinned )

    def lookup( ctx, item ):
        out = base[ bf.LOOKUP ]( ctx, item )
        if out[ "status" ] != "ok": return out
        row = { "repeat": 0, "route": ROUTE, "question": QUESTION, "verdict": out[ "verdict" ], "nearest": [ r[ "id" ] for r in out[ "nearest" ] ][ :TOP ],
                "shortlist": sorted( s[ "id" ] for s in out[ "shortlist" ] ) }
        return { **out, "rows": [ row ] }

    def replay( name ):
        def ask( ctx, item ):
            out = base[ name ]( ctx, item )
            if out[ "status" ] != "ok": return out
            row = { **out[ "rows" ][ 0 ], "route": ROUTE, "question": QUESTION, "verdict": out[ "verdict" ], "shortlist": sorted( s[ "id" ] for s in out[ "shortlist" ] ) }
            return { **out, "rows": [ row ] }
        return ask

    return { bf.LOOKUP: lookup, **{ name: replay( name ) for name in base if name != bf.LOOKUP } }


def estimate_lines( needs, sample_tokens, dollars_per_million ):
    """
    Write the estimate of the stage mode, the full sweep as its own line.

    Requires:
        - needs is the count of the needs file's rows; sample_tokens is the full-sweep sample's estimate
    Ensures:
        - returns the run line, the canary line, the sample line and the total line
        - the canary is the first needs of the run, so the total is the run plus the sample
        - the run is the band driver's estimate: needs x ( 1 lookup + the repeats ) x entries per ask x tokens per entry
    """
    run, canary = bf.estimate( needs ), bf.estimate( e2r.CANARY_MEMBERS )
    total       = run + sample_tokens
    return [ f"run: {run / 1e6:.2f} M tokens ({needs} needs x {1 + bf.REPEATS} asks x {bf.PER_ASK_ENTRIES} entries x {bf.TOKENS_PER_ENTRY} tokens), ceiling {int( e2r.ESTIMATE_FACTOR * run )}",
             f"canary: {canary / 1e6:.2f} M tokens, the first {e2r.CANARY_MEMBERS} needs of the run, ceiling {int( e2r.ESTIMATE_FACTOR * canary )}",
             f"sample: {sample_tokens / 1e6:.1f} M tokens, the full sweep of the sampled needs, its own step",
             f"total: {total / 1e6:.2f} M tokens, about ${total / 1e6 * dollars_per_million:.2f} at ${dollars_per_million} per M (estimate, not measured on this run)" ]


def _load( path ): return json.loads( pathlib.Path( path ).read_text( encoding="utf-8" ) )


def _interval( k, n ):
    """Ensures: returns { k, n, rate, interval }, with a Wilson interval and no rate for n of 0."""
    low, high = e2e.wilson( k, n )
    return { "k": k, "n": n, "rate": k / n if n else None, "interval": [ low, high ] }


def agreement( lookups, swept ):
    """
    Compare the stage's lookups with the full sweep on the sampled needs.

    Requires:
        - lookups maps a need id to the row of its complete lookup; swept maps a need id to the row of its complete full sweep
    Ensures:
        - only needs in both are compared, in id order
        - verdict is how often the lookup's final verdict equals the sweep's
        - recall is the share of the sweep's picks that sit in the lookup's first ten ranked ids, pooled over the needs whose picks are not empty
        - per_need holds each such need's own recall; a need whose sweep picked nothing is counted in compared but not in recall
    """
    members = sorted( m for m in swept if m in lookups )
    agree   = sum( 1 for m in members if lookups[ m ][ "verdict" ] == swept[ m ][ "verdict" ] )
    picks, held, per = 0, 0, {}
    for m in members:
        ref = set( swept[ m ][ "shortlist" ] )
        if not ref: continue
        per[ m ] = arm_metrics.recall_at_k( lookups[ m ][ "nearest" ][ :TOP ], ref )
        picks   += len( ref )
        held    += len( ref & set( lookups[ m ][ "nearest" ][ :TOP ] ) )
    return { "compared": len( members ), "verdict": _interval( agree, len( members ) ), "recall": _interval( held, picks ), "recall_needs": len( per ), "per_need": per }


def false_reuse( lookups, items ):
    """
    Count how often the lookup calls reuse on a need written to have no match.

    Requires:
        - lookups maps a need id to the row of its complete lookup; items are the needs file's items
    Ensures:
        - the absent needs are the items of kind distinct
        - returns { absent, asked, reuse, extend } where reuse and extend are Wilson figures over the absent needs that were asked
        - the headline is reuse; extend is reported beside it
    """
    mine = [ lookups[ i[ "member" ] ] for i in items if i[ "kind" ] == "distinct" and i[ "member" ] in lookups ]
    return { "absent": sum( 1 for i in items if i[ "kind" ] == "distinct" ), "asked": len( mine ),
             "reuse": _interval( sum( 1 for r in mine if r[ "verdict" ] == "REUSE" ), len( mine ) ),
             "extend": _interval( sum( 1 for r in mine if r[ "verdict" ] == "EXTEND" ), len( mine ) ) }


def tokens_per_need( searches, repeats ):
    """
    Work out what a need cost across its lookup and repeats.

    Requires:
        - searches are the search records of the canary and the run
    Ensures:
        - a need counts only when its lookup and every repeat are complete
        - returns { needs, total, mean }; mean is None when no need counts
    """
    by = {}
    for s in searches: by.setdefault( s[ "member" ], [] ).append( s )
    costs = [ sum( s[ "tokens" ] for s in runs ) for runs in by.values() if len( runs ) == 1 + repeats and all( s[ "status" ] == "complete" for s in runs ) ]
    return { "needs": len( costs ), "total": sum( costs ), "mean": sum( costs ) / len( costs ) if costs else None }


def _figure( name, f ):
    """Ensures: returns one line for a figure, or says there are no cases."""
    if f[ "n" ] == 0: return f"{name}: no cases"
    return f"{name}: {f[ 'k' ]} of {f[ 'n' ]}, {f[ 'rate' ]:.1%}, 95% interval {f[ 'interval' ][ 0 ]:.3f} to {f[ 'interval' ][ 1 ]:.3f}"


def report_lines( runs, sweep, items, repeats, dollars_per_million ):
    """
    Write the report: flip rate, recall, verdict agreement, false reuse and tokens per need.

    Requires:
        - runs are the loaded result files of the stage canary and run; sweep is the loaded full-sweep result or None
    Ensures:
        - returns the flip lines of the flip driver on the repeats only, then the other figures
        - recall is worded as agreement with the full search, not as ground truth
        - without a sweep result it says that recall and verdict agreement are not measured yet
        - false reuse says plainly when the file has no absent needs
    """
    searches = [ s for run in runs for s in run[ "searches" ] ]
    lookups  = { s[ "member" ]: s[ "rows" ][ 0 ] for s in searches if s[ "question" ] == bf.LOOKUP and s[ "status" ] == "complete" and s[ "rows" ] }
    lines    = frun.report_lines( [ s for s in searches if s[ "question" ] != bf.LOOKUP ], items, repeats )
    if sweep is None: lines.append( "recall and verdict agreement: not measured yet; the full sweep of the sample has not run" )
    else:
        swept = { s[ "member" ]: s[ "rows" ][ 0 ] for s in sweep[ "searches" ] if s[ "question" ] == SWEEP_ASK and s[ "status" ] == "complete" and s[ "rows" ] }
        a     = agreement( lookups, swept )
        lines.append( _figure( f"recall@{TOP}, agreement with the full search (not ground truth), {a[ 'recall_needs' ]} sampled needs with picks, picks pooled", a[ "recall" ] ) )
        lines.append( _figure( f"final verdict agreement with the full search, {a[ 'compared' ]} sampled needs", a[ "verdict" ] ) )
    fr = false_reuse( lookups, items )
    if fr[ "absent" ] == 0: lines.append( "false reuse: the file has no absent needs, so it is not measured" )
    else:
        lines.append( _figure( f"false reuse (verdict REUSE on an absent need), {fr[ 'absent' ]} absent needs", fr[ "reuse" ] ) )
        lines.append( _figure( "false extend (verdict EXTEND on an absent need), reported beside it", fr[ "extend" ] ) )
    t = tokens_per_need( searches, repeats )
    if t[ "mean" ] is None: lines.append( "tokens per need: no need has its lookup and every repeat complete yet" )
    else: lines.append( f"tokens per need: {t[ 'mean' ]:.0f} over {t[ 'needs' ]} needs ({t[ 'total' ]} in all), about ${t[ 'mean' ] / 1e6 * dollars_per_million:.4f} a need at ${dollars_per_million} per M" )
    return lines


def check_results( runs, pinned, sample_sha, repeats ):
    """
    Refuse a report over results that are not this run's.

    Requires:
        - runs are the loaded result files of the stage canary and run
    Ensures:
        - returns None when every run ran on the pinned vector set, carries the sample hash and holds a lookup and every repeat for each need
    Raises:
        - DriverRefused naming the first run that is not
    """
    for run in runs:
        if run[ "stage" ][ "manifest_hash" ] != pinned: raise s1.DriverRefused( f"{run[ 'run_name' ]} ran on vector set {run[ 'stage' ][ 'manifest_hash' ]}, the report is pinned to {pinned}" )
        if "sample_sha256" not in run or run[ "sample_sha256" ] != sample_sha: raise s1.DriverRefused( f"{run[ 'run_name' ]} does not carry the recorded sample's hash {sample_sha}" )
        if len( run[ "questions" ] ) != 1 + repeats: raise s1.DriverRefused( f"{run[ 'run_name' ]} was run with {len( run[ 'questions' ] ) - 1} repeats per need, but the report was given {repeats}" )


def run_step( args, items, sample_sha, stage_factory=None, repeats=bf.REPEATS ):
    """
    Run one spending step of the stage mode: the canary, its approval or the run.

    Requires:
        - args carry command (stage-canary, stage-approve or stage-run), prefix, root, data, ledger, live, pack_size, needs_sha, and manifest_hash and ceiling for the steps that take them
        - stage_factory is None for the live stage of the tree, or a function of the tree's path for a stand-in run
    Ensures:
        - a ceiling above the estimate times the estimate factor is refused, and a stage on another vector set than the pin is refused, before anything is opened
        - the results are named by the prefix, so another arm or policy can run again on the same sample under its own prefix
        - the results are stamped with the sample hash, the stage and the needs hash
        - an approval sends nothing, so it builds no stage
    Raises:
        - DriverRefused for the checks above; the refusals of the runner, the ledger and the canary
    """
    command = args.command[ len( "stage-" ): ]
    prefix  = bf.one_prefix( args.prefix )
    spent   = bf.estimate( len( items ) )
    if command in ( "canary", "run" ): bf.check_ceiling( args.ceiling, spent )
    stage = None if command == "approve" else ( stage_factory or bf.live_stage )( pathlib.Path( args.root ) )
    if stage is not None: bf.check_manifest( stage, args.manifest_hash )
    env   = e2r._open_env( args.root, args.data, args.ledger, args.live, stage_asks( stage, bf.Sink(), repeats, None if stage is None else args.manifest_hash ), args.pack_size )
    spec  = { "prefix": prefix, "members": len( items ), "estimate": spent, "canary_members": e2r.CANARY_MEMBERS,
              "stamp": None if stage is None else { "sample_sha256": sample_sha, "stage": bf.stage_record( stage ), "needs_sha": args.needs_sha } }
    if command in ( "canary", "run" ): frun.check_excludes( items, env.root, env.data )
    if command == "canary": print( e2r.canary_line( e2r.run_canary( env, items, {}, args.ceiling, spec=spec ) ) )
    elif command == "approve":
        e2r.approve_canary( env, args.by, args.why, spec=spec, revised_estimate=args.revised_estimate )
        print( f"canary approved by {args.by}" )
    else: print( e2r.run_line( e2r.run_full( env, items, {}, args.ceiling, spec=spec ) ) )
    return 0


def report( args, items, sample_sha, dollars_per_million, repeats=bf.REPEATS ):
    """
    Print the report of the stage mode from the result files, sending nothing.

    Requires:
        - args carry data, prefix and manifest_hash
    Ensures:
        - reads the canary and run results of the prefix that exist, and the full-sweep result when it exists
        - returns 0 after printing the lines of report_lines
    Raises:
        - DriverRefused when no stage result exists, or check_results refuses one, or the sweep result carries another sample hash
    """
    folder = pathlib.Path( args.data ) / "e2e-results"
    prefix = bf.one_prefix( args.prefix )
    runs   = [ _load( p ) for p in ( folder / f"{prefix}-{part}.json" for part in ( "canary", "run" ) ) if p.exists() ]
    if not runs: raise s1.DriverRefused( f"no {prefix} result in {folder}; run the stage canary first" )
    check_results( runs, args.manifest_hash, sample_sha, repeats )
    swept = folder / f"{SWEEP_RESULT}.json"
    sweep = _load( swept ) if swept.exists() else None
    if sweep is not None and ( "sample_sha256" not in sweep or sweep[ "sample_sha256" ] != sample_sha ): raise s1.DriverRefused( f"the full-sweep result does not carry the recorded sample's hash {sample_sha}" )
    print( "\n".join( report_lines( runs, sweep, items, repeats, dollars_per_million ) ) )
    return 0
