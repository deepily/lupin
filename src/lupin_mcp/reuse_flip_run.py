"""
The flip-rate driver: the old or the new question asked again and again, and its flips.

Thirty needs or more are each asked several times, every repeat keyed apart and stored nowhere.
A canary of five needs is read by a person before the rest is paid for.
The run, the ledger, the token ceiling and the stop rules are the end-to-end driver's own.
This module adds the needs file, the repeats as questions, and a report of the flip rate.
It sends nothing itself: the transport is the end-to-end driver's factory.
"""
import argparse
import collections
import json
import os
import sys

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_tools as rt

NEEDS_FORMAT    = "reuse-flip-needs-1"
KINDS           = ( "duplicate", "distinct" )
QUESTION_NAMES  = { "old": "choice", "new": "provides" }   # the command line names the question; the tools name it by its policy
PREFIX          = "fl"
ESTIMATE_TOKENS = 319_000_000                         # 150 searches at 2,125,705 tokens each, rounded up, from the end-to-end run of 9 October


def load_flip_needs( path, expected_sha ):
    """
    Read the frozen needs of the flip-rate test.

    Requires:
        - path names a JSON file { format, needs: [ { id, need, kind, exclude } ] }
    Ensures:
        - returns [ { member, need, exclude, kind } ] in file order; member is the need's id
        - the file's hash matched, there are at least MIN_NEEDS needs, and no id or need text is repeated
        - kind is duplicate or distinct, and exclude is a symbol id to leave out or null
    Raises:
        - FrozenInputRefused for any of the above that does not hold
    """
    record = e2e._read_checked( path, expected_sha, "flip needs file" )
    if record[ "format" ] != NEEDS_FORMAT: raise e2e.FrozenInputRefused( f"flip needs file format is {record[ 'format' ]!r}, expected {NEEDS_FORMAT!r}" )
    rows = record[ "needs" ]
    if len( rows ) < rf.MIN_NEEDS: raise e2e.FrozenInputRefused( f"flip needs file holds {len( rows )} needs; the test needs at least {rf.MIN_NEEDS}" )
    ids, texts, items = set(), set(), []
    for row in rows:
        if row[ "id" ] in ids: raise e2e.FrozenInputRefused( f"need id {row[ 'id' ]!r} is repeated" )
        text = row[ "need" ]
        if not isinstance( text, str ) or not text.strip(): raise e2e.FrozenInputRefused( f"need {row[ 'id' ]} has an empty need" )
        if text.strip() in texts: raise e2e.FrozenInputRefused( f"need {row[ 'id' ]} has the same need text as another" )
        if row[ "kind" ] not in KINDS: raise e2e.FrozenInputRefused( f"need {row[ 'id' ]} has kind {row[ 'kind' ]!r}, expected one of {KINDS}" )
        if row[ "exclude" ] is not None and not isinstance( row[ "exclude" ], str ): raise e2e.FrozenInputRefused( f"need {row[ 'id' ]}: exclude is a symbol id or null" )
        ids.add( row[ "id" ] ); texts.add( text.strip() )
        items.append( { "member": row[ "id" ], "need": text.strip(), "exclude": row[ "exclude" ], "kind": row[ "kind" ] } )
    return items


def repeat_asks( repeats, route, question="choice" ):
    """
    Turn the repeats into asks, one question name each: r1, r2 and so on.

    Ensures:
        - ask rN asks the need as repeat N by the route, leaving the item's excluded symbol out
        - question is "choice" (the old question) or "provides" (the new one, which has no page route)
        - the result carries rows: the repeat, the route, the question, the verdict and the sorted shortlist ids, so the report needs no receipt
        - an error result is returned as it is
    """
    def make( index ):
        def ask( ctx, item ):
            result = rf.ask_repeat( ctx, item[ "need" ], item[ "exclude" ], index, route=route, question=question )
            if result[ "status" ] != "ok": return result
            row = { "repeat": index, "route": route, "question": question, "verdict": result[ "verdict" ], "shortlist": sorted( s[ "id" ] for s in result[ "shortlist" ] ) }
            return { **result, "rows": [ row ] }
        return ask

    return { f"r{i}": make( i ) for i in range( 1, repeats + 1 ) }


def report_lines( searches, items, repeats ):
    """
    Write the report as lines: the flip rate, the needs it covers and the ones it leaves out.

    Requires:
        - searches are the search records of the canary and the run; items are the needs file's items
    Ensures:
        - a need counts only when all its repeats are complete; any other need that was asked is left out and named
        - returns the flip rate of rf.flip_rate with its interval, state, flipped needs, kinds and route
        - says so when the upper bound is above the pass line, since the pass rule is on the rate
        - returns one line when no search has run
    """
    if not searches: return [ "no searches have run yet" ]
    by_need = collections.defaultdict( list )
    for s in searches: by_need[ s[ "member" ] ].append( s )
    counted, left_out, routes, questions = {}, [], set(), set()
    for item in items:
        runs = by_need[ item[ "member" ] ] if item[ "member" ] in by_need else []
        if not runs: continue
        if len( runs ) != repeats or any( s[ "status" ] != "complete" for s in runs ):
            left_out.append( item[ "member" ] )
            continue
        rows = sorted( ( s[ "rows" ][ 0 ] for s in runs ), key=lambda row: row[ "repeat" ] )
        routes.update( row[ "route" ] for row in rows )
        questions.update( row[ "question" ] if "question" in row else "choice" for row in rows )                    # a row written before the question was recorded is the old question
        counted[ item[ "member" ] ] = [ { "status": "ok", "verdict": row[ "verdict" ], "shortlist": [ { "id": i } for i in row[ "shortlist" ] ] } for row in rows ]
    lines = []
    if left_out: lines.append( f"left out as incomplete: {', '.join( left_out )}" )
    if not counted: return [ "no need has all its repeats complete yet" ] + lines
    r = rf.flip_rate( counted )
    kind_of = { item[ "member" ]: item[ "kind" ] for item in items }
    kinds = ", ".join( f"{k} {sum( 1 for n in r[ 'flipped' ] if kind_of[ n ] == k )} of {sum( 1 for n in counted if kind_of[ n ] == k )}" for k in KINDS )
    route = routes.pop() if len( routes ) == 1 else "mixed"
    asked = { v: k for k, v in QUESTION_NAMES.items() }[ questions.pop() ] if len( questions ) == 1 else "mixed"
    lines = [ f"flip rate ({asked} question, route {route}): {r[ 'flips' ]} of {r[ 'needs' ]} needs flipped, rate {r[ 'rate' ]:.1%}, "
              f"95% interval {r[ 'interval' ][ 0 ]:.3f} to {r[ 'interval' ][ 1 ]:.3f}, state {r[ 'state' ]}",
              f"flipped: {', '.join( r[ 'flipped' ] ) if r[ 'flipped' ] else 'none'}",
              f"repeats per need: {r[ 'repeats_min' ]}; by kind: {kinds}" ] + lines
    if r[ "upper" ] > rf.PASS_LIMIT:
        lines.append( f"note: the upper bound {r[ 'upper' ]:.3f} is above 5% even when few or no needs flipped; the pass rule is on the rate, the bound is reported beside it" )
    return lines


def check_repeats( runs, repeats ):
    """
    Refuse a report whose repeats differ from the repeats the runs were given.

    Requires:
        - runs are the loaded result files of the canary and the run, each with its list of questions
    Ensures:
        - returns None when there is no run or every run was given exactly repeats questions
        - a run stopped early still holds all its questions, so it is not read as having fewer repeats
    Raises:
        - DriverRefused naming both numbers when a run was given another number of repeats
    """
    for run in runs:
        if len( run[ "questions" ] ) != repeats:
            raise s1.DriverRefused( f"the records were run with {len( run[ 'questions' ] )} repeats per need, but the report was given --repeats {repeats}" )


def _check_options( args ):
    """
    Check the options of a command line before anything is read or sent.

    Ensures:
        - returns the one prefix
    Raises:
        - DriverRefused for a bad or several prefixes, an estimate under one token, or fewer than two repeats
    """
    prefixes = e2r._prefixes( args.prefix )
    if len( prefixes ) != 1: raise s1.DriverRefused( f"the flip run takes one prefix only, got {args.prefix!r}" )
    if args.estimate_tokens < 1: raise s1.DriverRefused( f"the estimate is a positive whole number of tokens, got {args.estimate_tokens!r}" )
    if args.repeats < 2: raise s1.DriverRefused( f"a flip needs at least two repeats, got {args.repeats!r}" )
    return prefixes[ 0 ]


def check_excludes( items, root, data ):
    """
    Refuse before any spend a need whose excluded symbol the sweep would not know.

    Requires:
        - items are the needs file's items; root is the tree the run asks about; data is the run's data directory
    Ensures:
        - returns None when every excluded id is an entry the sweep sends (sendable and in the index), or the tree is not one it can read
        - nothing is sent and no ledger run is opened
    Raises:
        - DriverRefused naming each need and its excluded id that is not a sendable entry
    """
    flags, entries = rt.prepare( rt.ReuseContext( root, data ) )[ :2 ]
    if flags & { "NOT_LUPIN_TREE", "INDEX_STALE" }: return None
    known   = { e[ "id" ] for e in entries }
    missing = [ f"{item[ 'member' ]} ({item[ 'exclude' ]})" for item in items if item[ "exclude" ] is not None and item[ "exclude" ] not in known ]
    if missing: raise s1.DriverRefused( f"excluded symbol is not a sendable entry of this index, so the need would end UNKNOWN_ENTRY: {', '.join( missing )}" )


def _parser():
    """Ensures: returns the command line parser."""
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--root" )
    ap.add_argument( "--data" )
    ap.add_argument( "--ledger" )
    ap.add_argument( "--live", action="store_true" )
    ap.add_argument( "--pack-size", type=int, default=50 )
    ap.add_argument( "--prefix", default=PREFIX )
    ap.add_argument( "--estimate-tokens", type=int, default=ESTIMATE_TOKENS )
    ap.add_argument( "--repeats", type=int, default=rf.MIN_REPEATS )
    ap.add_argument( "--route", choices=rf.ROUTES, default=rf.ROUTES[ 0 ] )
    ap.add_argument( "--question", choices=tuple( QUESTION_NAMES ), default="old" )
    sub = ap.add_subparsers( dest="command", required=True )
    for name in ( "canary", "approve", "run", "report" ):
        p = sub.add_parser( name )
        p.add_argument( "--needs", required=True )
        p.add_argument( "--needs-sha", required=True )
        if name in ( "canary", "run" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
            p.add_argument( "--revised-estimate", type=int, default=None )
    return ap


def main( argv=None ):
    """
    Run one step of the flip-rate test.

    Ensures:
        - returns 0 after the step; prints how it ended
    Raises:
        - the refusals of the options, the checks and the frozen needs, before anything is created or sent
    """
    args = _parser().parse_args( argv )
    root = args.root or os.environ.get( "LUPIN_ROOT" )
    if not root: raise rr.RunnerRefused( "give --root, or set LUPIN_ROOT" )
    prefix = _check_options( args )
    rr.check_paths( root, args.data, args.ledger, args.live )                                    # a path refusal comes before the slow reads
    items = load_flip_needs( args.needs, args.needs_sha )
    spec  = { "prefix": prefix, "members": len( items ), "estimate": args.estimate_tokens, "canary_members": e2r.CANARY_MEMBERS }
    if args.question == "new" and args.route != "full": raise s1.DriverRefused( "the new question has no page route; give --route full" )
    env   = e2r._open_env( root, args.data, args.ledger, args.live, repeat_asks( args.repeats, args.route, QUESTION_NAMES[ args.question ] ), args.pack_size )
    if args.command in ( "canary", "run" ): check_excludes( items, env.root, env.data )
    if args.command == "canary": print( e2r.canary_line( e2r.run_canary( env, items, {}, args.ceiling, spec=spec ) ) )
    elif args.command == "approve":
        e2r.approve_canary( env, args.by, args.why, spec=spec, revised_estimate=args.revised_estimate )
        print( f"canary approved by {args.by}" )
    elif args.command == "run": print( e2r.run_line( e2r.run_full( env, items, {}, args.ceiling, spec=spec ) ) )
    else:
        runs = [ json.loads( path.read_text( encoding="utf-8" ) ) for path in ( env.results_dir / f"{prefix}-{part}.json" for part in ( "canary", "run" ) ) if path.exists() ]
        check_repeats( runs, args.repeats )
        searches = [ s for run in runs for s in run[ "searches" ] ]
        print( "\n".join( report_lines( searches, items, args.repeats ) ) )
    return 0


def cli( argv=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the runner, the driver, the frozen needs or the ledger
        - any other error propagates untouched, so a crash is never read as a refusal
    """
    try: return main( argv )
    except ( rr.RunnerRefused, s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, s1.CanaryTripped, s1.StageRefused,
             e2e.FrozenInputRefused, rl.AccountLimitReached, rl.LedgerUnreadable ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    sys.exit( cli() )
