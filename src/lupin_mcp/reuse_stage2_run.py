"""
The labelled-pair driver: both questions over a member's candidates, and the fit's rows.

A member's candidates are its twins, its lexical neighbours and its random draws from the negatives record.
The member's own entry text is the need. The run goes through the end-to-end engine: one ledger run, one token
ceiling, a canary a person approves, the same causes for an incomplete search. The new question is wired from the pair reader and request modules.
"""
import argparse
import json
import os
import pathlib
import sys

from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_e2e_run as e2r
from lupin_mcp import reuse_pack
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_stage2_fit as fit
from lupin_mcp import reuse_tools as rt

NEGATIVES_FORMAT = "stage2-negatives-1"
ROWS_FORMAT      = "stage2-rows-1"
PREFIX           = "s2"
SHORTLIST_CUT    = 0.5
NEW_PAIR_ASK     = reuse_pack.pair_ask          # ask( ctx, need, entries ) -> { answered, unasked, malformed, stats }; None refuses "new"


def spec_for( members, estimate_tokens ):
    """Ensures: returns the engine's spec: the s2 prefix, the member count and the estimate."""
    return { "prefix": PREFIX, "members": members, "estimate": estimate_tokens, "canary_members": e2r.CANARY_MEMBERS }


def load_plan( path, expected_sha, by_id ):
    """
    Read the negatives record into the run's items.

    Requires:
        - by_id maps every sendable id to its symbol dict
    Ensures:
        - the record is the negatives writer's: twins and random are id strings, lexical rows are { id, score }
        - returns ( items, twins ): items are { member, need, entries } sorted by member, entries being its twins,
          lexical neighbours and random draws in that order, each once and never the member
        - need is the member's own entry text; twins maps a member to the set of its twins' ids
    Raises:
        - FrozenInputRefused for a wrong hash or format, a member or candidate that is not in the index, or a member with no candidate
    """
    record = e2e._read_checked( path, expected_sha, "negatives record" )
    if record[ "format" ] != NEGATIVES_FORMAT: raise e2e.FrozenInputRefused( f"negatives record format is {record[ 'format' ]!r}, expected {NEGATIVES_FORMAT!r}" )
    items, twins = [], {}
    for member in sorted( record[ "members" ] ):
        if member not in by_id: raise e2e.FrozenInputRefused( f"member {member!r} is not in the index" )
        mine, ids = record[ "members" ][ member ], []
        for i in mine[ "twins" ] + [ r[ "id" ] for r in mine[ "lexical" ] ] + mine[ "random" ]:
            if i not in by_id: raise e2e.FrozenInputRefused( f"candidate {i!r} of {member!r} is not in the index" )
            if i != member and i not in ids: ids.append( i )
        if not ids: raise e2e.FrozenInputRefused( f"member {member!r} has no candidate" )
        items.append( { "member": member, "need": rt.entry_text( by_id[ member ] ), "entries": [ by_id[ i ] for i in ids ] } )
        twins[ member ] = set( mine[ "twins" ] )
    return items, twins


def _result( rows, malformed, stats, rank_key ):
    """Ensures: returns the engine-shaped result of one stage-two search, with its rows."""
    ranked = sorted( ( r for r in rows if r[ rank_key ] is not None ), key=lambda r: ( -r[ rank_key ], r[ "candidate" ] ) )
    return { "status": "ok", "verdict": "STAGE2", "receipt_id": None, "malformed": malformed, "stats": stats, "rows": rows,
             "shortlist": [ { "id": r[ "candidate" ] } for r in ranked if r[ rank_key ] >= SHORTLIST_CUT ][ :vd.POLICY[ "shortlist" ] ],
             "nearest": [ { "id": r[ "candidate" ] } for r in ranked[ :vd.POLICY[ "shortlist" ] ] ] }


def ask_old_pairs( ctx, item ):
    """
    Ask the old three-way question about the member's candidates only.

    Ensures:
        - returns an engine-shaped result whose rows hold, per candidate, p_overlap, the malformed reason and whether it went unasked
    """
    sw = ctx.sweeper( ctx, item[ "need" ], item[ "entries" ] )
    answers, rows, malformed = { a[ "id" ]: a[ "probabilities" ] for a in sw[ "answers" ] }, [], []
    for e in item[ "entries" ]:
        i = e[ "id" ]
        if i not in answers: rows.append( { "candidate": i, "p_overlap": None, "malformed": None, "unasked": True } ); continue
        reason = vd.malformed_reason( answers[ i ], vd.POLICY )
        if reason is not None: malformed.append( { "id": i, "reason": reason } )
        rows.append( { "candidate": i, "p_overlap": None if reason else round( vd.call_facts( answers[ i ] )[ 0 ], 6 ), "malformed": reason, "unasked": False } )
    stats = { "failed": len( sw[ "failed" ] ), "not_checked": len( sw[ "not_reached" ] ), "stopped_by": sw[ "stopped_by" ], "requests": sw[ "requests" ],
              "attempt_counts": rt.attempt_counts( sw[ "attempt_logs" ] ) }
    return _result( rows, malformed, stats, "p_overlap" )


def ask_new_pairs( ctx, item ):
    """
    Ask the new question about the member's candidates only.

    Ensures:
        - returns an engine-shaped result whose rows hold, per candidate, provides, coverage, score, the malformed reasons and whether it went unasked
    Raises:
        - DriverRefused while the new question is not wired
    """
    if NEW_PAIR_ASK is None: raise s1.DriverRefused( "the new question is not wired yet; run old only" )
    out = NEW_PAIR_ASK( ctx, item[ "need" ], item[ "entries" ] )
    bad = { m[ "id" ]: "; ".join( m[ "reasons" ] ) for m in out[ "malformed" ] }
    rows = []
    for e in item[ "entries" ]:
        i = e[ "id" ]
        if i in out[ "answered" ]: a = out[ "answered" ][ i ]; rows.append( { "candidate": i, "provides": a[ "provides" ], "coverage": a[ "coverage" ], "score": a[ "score" ], "malformed": None, "unasked": False } )
        else: rows.append( { "candidate": i, "provides": None, "coverage": None, "score": None, "malformed": bad[ i ] if i in bad else None, "unasked": i not in bad } )
    return _result( rows, [ { "id": i, "reason": r } for i, r in bad.items() ], out[ "stats" ], "provides" )


def rows_from_run( searches, twins ):
    """
    Join the two questions' rows into the fit script's rows.

    Ensures:
        - returns one row per member and candidate for every member that has rows from both questions, in the order run
        - label is true for a twin; p_overlap comes from the old question, provides, coverage and score from the new
        - malformed joins the two questions' reasons; unasked is true when either left the candidate unasked
    """
    by = { ( s[ "member" ], s[ "question" ] ): s[ "rows" ] for s in searches if "rows" in s }
    out = []
    for member in dict.fromkeys( m for m, _ in by ):
        if ( member, "old" ) not in by or ( member, "new" ) not in by: continue
        new = { r[ "candidate" ]: r for r in by[ ( member, "new" ) ] }
        for old in by[ ( member, "old" ) ]:
            n, c = new[ old[ "candidate" ] ], old[ "candidate" ]
            reasons = [ r for r in ( old[ "malformed" ], n[ "malformed" ] ) if r is not None ]
            out.append( { "member": member, "candidate": c, "label": c in twins[ member ], "provides": n[ "provides" ], "coverage": n[ "coverage" ], "score": n[ "score" ],
                          "p_overlap": old[ "p_overlap" ], "malformed": "; ".join( reasons ) if reasons else None, "unasked": old[ "unasked" ] or n[ "unasked" ] } )
    return out


def write_rows( path, rows ):
    """
    Write the rows file the fit script takes.

    Ensures:
        - the rows pass the fit script's own check before anything is written, and the file is written whole or not at all
    Raises:
        - ValueError from the fit script's check
    """
    fit.check_rows( rows )
    e2r._write_json( pathlib.Path( path ), { "format": ROWS_FORMAT, "rows": rows } )


def _asks( names ):
    """Ensures: returns the asks in order; refuses an unknown name, and new while it is unwired."""
    asks = {}
    for name in names:
        if name not in e2r.QUESTION_NAMES: raise s1.DriverRefused( f"question {name!r} is not one of {e2r.QUESTION_NAMES}" )
        if name == "new" and NEW_PAIR_ASK is None: raise s1.DriverRefused( "the new question is not wired yet; run old only" )
        asks[ name ] = ask_old_pairs if name == "old" else ask_new_pairs
    return asks


def _parser():
    """Ensures: returns the command line parser."""
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--root" )
    ap.add_argument( "--data" )
    ap.add_argument( "--ledger" )
    ap.add_argument( "--live", action="store_true" )
    ap.add_argument( "--pack-size", type=int, default=50 )
    ap.add_argument( "--questions", default="old,new" )
    sub = ap.add_subparsers( dest="command", required=True )
    sub.add_parser( "status" )
    for name in ( "canary", "approve", "run", "rows" ):
        p = sub.add_parser( name )
        p.add_argument( "--negatives", required=True )
        p.add_argument( "--negatives-sha", required=True )
        p.add_argument( "--estimate-tokens", type=int, required=True )
        if name in ( "canary", "run" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
        if name == "rows": p.add_argument( "--out", required=True )
    return ap


def main( argv=None, loader=None ):
    """
    Run one step of the labelled-pair run.

    Requires:
        - loader reads the index as ( entries, pages ); the real one by default
    Ensures:
        - returns 0 after the step; prints how it ended
    Raises:
        - the refusals of the checks and of the frozen inputs, before anything is created or sent
    """
    args = _parser().parse_args( argv )
    root = args.root or os.environ.get( "LUPIN_ROOT" )
    if not root: raise rr.RunnerRefused( "give --root, or set LUPIN_ROOT" )
    names = [ n for n in args.questions.split( "," ) if n ]
    rr.check_paths( root, args.data, args.ledger, args.live )
    if args.command == "status":
        env = e2r._open_env( root, args.data, args.ledger, args.live, {}, args.pack_size )
        print( f"ledger {env.ledger.snapshot()}  pack size {env.pack_size}  questions {names}" )
        return 0
    asks = _asks( names )
    entries, _ = ( loader or rr.load_inputs )( root )
    items, twins = load_plan( args.negatives, args.negatives_sha, { e[ "id" ]: e for e in entries } )
    spec = spec_for( len( items ), args.estimate_tokens )
    env  = e2r._open_env( root, args.data, args.ledger, args.live, asks, args.pack_size )
    if args.command == "canary": print( e2r.canary_line( e2r.run_canary( env, items, twins, args.ceiling, spec=spec ) ) )
    elif args.command == "approve":
        e2r.approve_canary( env, args.by, args.why, spec=spec )
        print( f"canary approved by {args.by}" )
    elif args.command == "run": print( e2r.run_line( e2r.run_full( env, items, twins, args.ceiling, spec=spec ) ) )
    else:
        searches = []
        for name in ( f"{PREFIX}-canary", f"{PREFIX}-run" ):
            path = env.results_dir / f"{name}.json"
            if path.exists(): searches += json.loads( path.read_text( encoding="utf-8" ) )[ "searches" ]
        rows = rows_from_run( searches, twins )
        write_rows( args.out, rows )
        print( f"rows written: {args.out} ({len( rows )} rows from {len( {r[ 'member' ] for r in rows} )} members)" )
    return 0


def cli( argv=None, loader=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the runner, the driver, the frozen inputs or the ledger
        - any other error propagates untouched
    """
    try: return main( argv, loader )
    except ( rr.RunnerRefused, s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, s1.CanaryTripped, s1.StageRefused,
             e2e.FrozenInputRefused, e2r.rl.AccountLimitReached, e2r.rl.LedgerUnreadable ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    raise SystemExit( cli() )
