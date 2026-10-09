"""
The end-to-end runner: a full sweep of the catalogue per member, for each question.

A run is one ledger run with one token ceiling. A canary of five members is read by a person before the
rest is paid for. A search is complete or it is a miss, and the reason is kept apart: the ceiling, the
ledger, failed calls, malformed answers. Searches the ceiling or the stop rule never started are not run.
The driver sends nothing itself: the transport is a factory, and a stand-in is the default in tests.
"""
import argparse
import collections
import json
import os
import pathlib
import sys
import time

from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_pack as rp
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_run as rr
from lupin_mcp import reuse_ceiling as rc
from lupin_mcp import reuse_tools as rt

FORMAT           = "e2e-run-1"
CANARY_FORMAT    = "e2e-canary-1"
CANARY_MEMBERS   = 5
CANARY_NAME      = "e2e-canary"
RUN_NAME         = "e2e-run"
ESTIMATE_TOKENS  = 420_000_000
E2E_SPEC         = { "prefix": "e2e", "members": e2e.MEMBERS, "estimate": ESTIMATE_TOKENS, "canary_members": CANARY_MEMBERS }
ESTIMATE_FACTOR  = 1.5
WINDOW_SEARCHES  = 20
MAX_INCOMPLETE   = 5
QUESTION_NAMES   = ( "old", "new" )


class E2EEnv:
    """
    Everything the runner needs from outside, injectable for tests.

    Requires:
        - ledger is an AccountLedger that already exists
        - asks maps a question name to ask( ctx, item ), which returns the public result of one full sweep
        - transport_factory takes the run's TokenBudget and returns a transport; the default is the live one
    Ensures:
        - results go to <data>/e2e-results/
    """

    def __init__( self, root, data, ledger, asks, transport_factory=None, pack_size=50, workers=rp.WORKERS_DEFAULT, model=rt.JEV_MODEL, clock=None ):
        self.root, self.data, self.ledger = pathlib.Path( root ), pathlib.Path( data ), ledger
        self.asks, self.pack_size, self.workers, self.model = asks, pack_size, workers, model
        self.transport_factory = transport_factory or ( lambda budget: rt.LiveJevTransport( budget=budget, transient=True ) )
        self.live  = transport_factory is None
        self.clock = clock or ( lambda: time.strftime( "%Y-%m-%dT%H:%M:%S%z" ) )

    @property
    def results_dir( self ):
        """Ensures: returns the directory every result file goes in."""
        return self.data / "e2e-results"


def _write_json( path, record ):
    """Ensures: writes the record whole or not at all."""
    path.parent.mkdir( parents=True, exist_ok=True )
    tmp = path.with_name( path.name + ".tmp" )
    tmp.write_text( json.dumps( record, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
    os.replace( tmp, path )


def _check_ready( env, items ):
    """
    Check what a run would otherwise learn only after its ledger run opened.

    Raises:
        - DriverRefused for no items, a repeated member, no questions, a pack size or worker count out of range
        - KeyMissing when the transport is the live one and the key variable is empty or unset
    """
    if not items: raise s1.DriverRefused( "a run needs at least one member" )
    members = collections.Counter( i[ "member" ] for i in items )
    repeated = sorted( m for m, n in members.items() if n > 1 )
    if repeated: raise s1.DriverRefused( f"member {repeated[ 0 ]!r} is repeated; the sample holds one search per member" )
    if not env.asks: raise s1.DriverRefused( "a run needs at least one question" )
    if type( env.pack_size ) is not int or not 1 <= env.pack_size <= rt.MAX_PACK_SIZE: raise s1.DriverRefused( f"pack size must be an integer from 1 to {rt.MAX_PACK_SIZE}, got {env.pack_size!r}" )
    if type( env.workers ) is not int or not rp.WORKERS_MIN <= env.workers <= rp.WORKERS_MAX: raise s1.DriverRefused( f"workers must be an integer from {rp.WORKERS_MIN} to {rp.WORKERS_MAX}, got {env.workers!r}" )
    if env.live and not s1.jt.has_key(): raise s1.KeyMissing( f"{s1.jt.KEY_VARIABLE} is not set; no ledger run was opened" )


def _context( env, transport, budget, cap ):
    """Ensures: returns a packed context whose sweeper draws on the run's one budget."""
    def sweeper( ctx, need, entries, frozen=False, template=None, model=None, gaps=None ):
        return rp.sweep_packed( ctx, need, entries, env.pack_size, workers=env.workers, key_mode="candidate", template=template, model=model,
                                frozen=frozen, gaps=gaps, budget=budget )
    return rt.ReuseContext( env.root, env.data, transport=transport, sweeper=sweeper, request_shape=rp.SHAPE, pack_size=env.pack_size, model=env.model,
                            call_budget=cap, call_budget_cap=cap, run_budget=budget )


def _record_of( member, question, status, causes, **rest ):
    """Ensures: returns one search record with every counter present."""
    base = { "member": member, "question": question, "status": status, "causes": causes, "tokens": 0, "requests": 0, "unasked": 0,
             "n429": 0, "n529": 0, "wall_seconds": 0.0, "receipt_id": None, "read": None }
    return { **base, **rest }


def _search( env, ctx, budget, item, question, twins ):
    """
    Run one search and describe it.

    Ensures:
        - returns a search record: status complete or incomplete, its causes, tokens spent by the run during it, requests, unasked, 429 and 529 counts
        - an exception from the ask is recorded as an error record on the way out
    """
    spent, refusals, started = budget.spent_tokens, budget.ceiling_refusals, time.monotonic()
    result = env.asks[ question ]( ctx, item )
    causes = e2e.incomplete_causes( result, budget.ceiling_refusals > refusals, budget.stop_reason is not None )
    rec    = _record_of( item[ "member" ], question, "complete" if not causes else "incomplete", causes, tokens=budget.spent_tokens - spent,
                         wall_seconds=round( time.monotonic() - started, 3 ) )
    if result[ "status" ] == "ok":
        stats = result[ "stats" ]
        counts = stats[ "attempt_counts" ] if "attempt_counts" in stats else {}
        rec.update( receipt_id=result[ "receipt_id" ], requests=stats[ "requests" ], unasked=stats[ "failed" ] + stats[ "not_checked" ],
                    n429=counts[ "n429" ] if counts else 0, n529=counts[ "n529" ] if counts else 0,
                    read=e2e.read_search( result, twins.get( item[ "member" ], set() ) ) )
        if "rows" in result: rec[ "rows" ] = result[ "rows" ]
    return rec


def _totals( searches, budget ):
    """Ensures: returns the run's counts and what it spent."""
    count = collections.Counter( s[ "status" ] for s in searches )
    return { "searches": len( searches ), "complete": count[ "complete" ], "incomplete": count[ "incomplete" ], "error": count[ "error" ], "not_run": count[ "not_run" ],
             "spent_tokens": budget.spent_tokens, "reserved_tokens": budget.reserved_tokens, "ceiling_refusals": budget.ceiling_refusals,
             "requests": sum( s[ "requests" ] for s in searches ), "unasked": sum( s[ "unasked" ] for s in searches ) }


def run_searches( env, run_name, items, twins, ceiling_tokens, kind="run", prior=(), canary_run=None ):
    """
    Run every member's searches in order, both questions, as one ledger run.

    Requires:
        - items are { member, need } in the frozen order; twins maps a member to its twins' ids
        - prior holds the search records of an earlier part of the same measurement, counted in the reliability window
    Ensures:
        - nothing is sent and no ledger run is opened when a check refuses: the ledger is read first, and a ceiling that with
          the ledger total passes the account limit is refused by the ledger
        - searches run member by member, the questions in the order of env.asks, and the result file is rewritten after each member
        - a search is complete only when nothing failed, nothing was left unasked and nothing was malformed; any other is incomplete with its causes
        - the ceiling stops the whole run: the search it cut is incomplete with cause ceiling, and every later search is not run
        - more than MAX_INCOMPLETE incomplete searches among the first WINDOW_SEARCHES, prior ones included, stops the run the same way
        - the run is closed in the ledger however it ends; an ask that raises is recorded as an error search and the error goes on
    Raises:
        - DriverRefused for a check that fails or a run name used before; KeyMissing, LedgerUnreadable, AccountLimitReached
    """
    _check_ready( env, items )
    env.ledger.snapshot()                                                                 # an unreadable ledger refuses here, before a run is opened
    ledger_limit, ledger_total = env.ledger.snapshot()
    plan   = [ ( item, q ) for item in items for q in env.asks ]
    probe  = rt.ReuseContext( env.root, env.data )
    entries = rt.prepare( probe )[ 1 ]
    cap    = rt.call_budget_cap_for( len( entries ) )
    try: budget = rc.TokenBudget( cap * len( plan ), ceiling_tokens, ledger=env.ledger, run=run_name )
    except ValueError as e: raise s1.DriverRefused( str( e ) ) from e
    record = { "format": FORMAT, "run_name": run_name, "kind": kind, "canary_run": canary_run, "pack_size": env.pack_size, "ceiling_tokens": ceiling_tokens,
               "ledger_limit": ledger_limit, "ledger_total_before": ledger_total, "questions": list( env.asks ), "members": [ i[ "member" ] for i in items ],
               "started_at": env.clock(), "state": "running", "stopped": None, "searches": [] }
    path, stop = env.results_dir / f"{run_name}.json", None
    try:
        ctx = _context( env, env.transport_factory( budget ), budget, cap )
        for n, ( item, question ) in enumerate( plan ):
            if stop is not None:
                record[ "searches" ].append( _record_of( item[ "member" ], question, "not_run", [ stop ] ) ); continue
            try: rec = _search( env, ctx, budget, item, question, twins )
            except BaseException as e:
                record[ "searches" ].append( _record_of( item[ "member" ], question, "error", [ f"ERROR:{type( e ).__name__}" ] ) )
                record[ "state" ] = "error"
                raise
            record[ "searches" ].append( rec )
            done = len( record[ "searches" ] )
            if "ceiling" in rec[ "causes" ] or "ledger" in rec[ "causes" ]: stop = "ceiling" if "ceiling" in rec[ "causes" ] else "ledger"
            elif sum( 1 for s in list( prior ) + record[ "searches" ] if s[ "status" ] != "complete" ) > MAX_INCOMPLETE and len( prior ) + done <= WINDOW_SEARCHES: stop = "reliability"
            if stop is not None: record[ "stopped" ] = { "reason": stop, "after": done }
            if n + 1 == len( plan ) or plan[ n + 1 ][ 0 ] is not item: _write_json( path, { **record, "totals": _totals( record[ "searches" ], budget ) } )
        if record[ "state" ] == "running": record[ "state" ] = "complete" if stop is None else "stopped"
    finally:
        record[ "ended_at" ] = env.clock()
        _write_json( path, { **record, "totals": _totals( record[ "searches" ], budget ) } )
        budget.end()
    return { **record, "totals": _totals( record[ "searches" ], budget ) }


def _canary_path( env, spec ): return env.results_dir / f"{spec[ 'prefix' ]}-canary.canary.json"


def run_canary( env, items, twins, ceiling_tokens, spec=E2E_SPEC ):
    """
    Ask the first five members, both questions, and write the numbers a person reads first.

    Requires:
        - spec is { prefix, members, estimate, canary_members }: the run names, the members the full run covers, its token estimate and the canary's size
    Ensures:
        - writes the run file and the canary file, with `approved` empty, and returns the canary report
        - the report holds the ledger total read before the first send, tokens, requests, unasked, 429 and 529 counts, wall time,
          the projection (the canary's tokens times 100 over the members asked) and the allowance it is held against
        - the allowance is the smaller of 1.5 times the estimate and the ledger's remaining allowance after the canary
        - tripped names each crossing: projection_over_allowance, incomplete, stopped
    """
    name = f"{spec[ 'prefix' ]}-canary"
    run  = run_searches( env, name, items[ :spec[ "canary_members" ] ], twins, ceiling_tokens, kind="canary" )
    limit, total = env.ledger.snapshot()
    tokens = run[ "totals" ][ "spent_tokens" ]
    asked  = len( run[ "members" ] )
    projection = tokens * spec[ "members" ] // asked
    allowance  = min( int( ESTIMATE_FACTOR * spec[ "estimate" ] ), limit - total )
    tripped = [ name for name, hit in ( ( "projection_over_allowance", projection > allowance ), ( "incomplete", run[ "totals" ][ "complete" ] != run[ "totals" ][ "searches" ] ),
                                        ( "stopped", run[ "stopped" ] is not None ) ) if hit ]
    report = { "format": CANARY_FORMAT, "run_name": name, "members": asked, "searches": run[ "totals" ][ "searches" ], "ledger_total_before": run[ "ledger_total_before" ],
               "ledger_limit": run[ "ledger_limit" ], "tokens": tokens, "projection_tokens": projection, "allowance_tokens": allowance, "requests": run[ "totals" ][ "requests" ],
               "unasked": run[ "totals" ][ "unasked" ], "n429": sum( s[ "n429" ] for s in run[ "searches" ] ), "n529": sum( s[ "n529" ] for s in run[ "searches" ] ),
               "wall_seconds": round( sum( s[ "wall_seconds" ] for s in run[ "searches" ] ), 3 ), "tripped": tripped, "approved": None }
    _write_json( _canary_path( env, spec ), report )
    return report


def canary_line( report ):
    """Ensures: returns the one line that says what the canary read and what it found."""
    return ( f"canary {report[ 'run_name' ]}: ledger total before the first send: {report[ 'ledger_total_before' ]} of {report[ 'ledger_limit' ]}; searches {report[ 'searches' ]}, "
             f"tokens {report[ 'tokens' ]}, projection {report[ 'projection_tokens' ]} against allowance {report[ 'allowance_tokens' ]}, requests {report[ 'requests' ]}, "
             f"unasked {report[ 'unasked' ]}, 429 {report[ 'n429' ]}, 529 {report[ 'n529' ]}, wall {report[ 'wall_seconds' ]}s, tripped {report[ 'tripped' ]}" )


def run_line( t ):
    """Ensures: returns the one line that says how a run ended."""
    return ( f"run {t[ 'run_name' ]}: state {t[ 'state' ]}, stopped {t[ 'stopped' ]}, complete {t[ 'totals' ][ 'complete' ]}, incomplete {t[ 'totals' ][ 'incomplete' ]}, "
             f"not run {t[ 'totals' ][ 'not_run' ]}, spent {t[ 'totals' ][ 'spent_tokens' ]}" )


def approve_canary( env, by, why, spec=E2E_SPEC, revised_estimate=None ):
    """
    Record that a person read the canary and let the rest run.

    Requires:
        - revised_estimate is None, or a positive whole number of tokens that replaces the spec's estimate
    Ensures:
        - a revised estimate is accepted only for a canary whose tripped list is exactly projection_over_allowance, and only when
          the projection is within the allowance it gives: the smaller of 1.5 times it and the ledger's remaining allowance now
        - the approval then keeps the old estimate, the new one and that allowance beside by, why and at; the measurement is untouched
    Raises:
        - DriverRefused for a missing by or why, a canary already approved, a revised estimate that is not a positive whole number,
          or a revised estimate for a canary that tripped nothing
        - CanaryNotApproved when no canary was run
        - CanaryTripped when the canary crossed a number a revised estimate cannot clear, or the projection is still above the revised allowance
    """
    if not isinstance( by, str ) or not by or not isinstance( why, str ) or not why: raise s1.DriverRefused( "by and why must say who approved the canary and why" )
    path = _canary_path( env, spec )
    if not path.exists(): raise s1.CanaryNotApproved( "no canary was run" )
    report = json.loads( path.read_text( encoding="utf-8" ) )
    if report[ "approved" ] is not None: raise s1.DriverRefused( "the canary is already approved" )
    if revised_estimate is not None and ( type( revised_estimate ) is not int or revised_estimate < 1 ):
        raise s1.DriverRefused( f"a revised estimate is a positive whole number of tokens, got {revised_estimate!r}" )
    approval = { "by": by, "why": why, "at": env.clock() }
    if revised_estimate is not None and not report[ "tripped" ]: raise s1.DriverRefused( "nothing tripped, so there is no estimate to revise" )
    if report[ "tripped" ]:
        if revised_estimate is None or report[ "tripped" ] != [ "projection_over_allowance" ]:
            raise s1.CanaryTripped( f"the canary tripped: {', '.join( report[ 'tripped' ] )}" )
        limit, total = env.ledger.snapshot()
        allowance    = min( int( ESTIMATE_FACTOR * revised_estimate ), limit - total )
        if report[ "projection_tokens" ] > allowance:
            raise s1.CanaryTripped( f"the canary's projection {report[ 'projection_tokens' ]} is above the allowance {allowance} that a revised estimate of {revised_estimate} gives" )
        approval[ "revised_estimate" ] = { "old": spec[ "estimate" ], "new": revised_estimate, "allowance_tokens": allowance }
    report[ "approved" ] = approval
    _write_json( path, report )


def run_full( env, items, twins, ceiling_tokens, spec=E2E_SPEC ):
    """
    Run the members after the canary's five, once the canary is approved.

    Ensures:
        - the canary's searches count in the reliability window, and the run file names the canary run
    Raises:
        - CanaryNotApproved when there is no approved canary
    """
    path = _canary_path( env, spec )
    if not path.exists() or json.loads( path.read_text( encoding="utf-8" ) )[ "approved" ] is None: raise s1.CanaryNotApproved( "the canary has not been approved" )
    canary = f"{spec[ 'prefix' ]}-canary"
    prior  = json.loads( ( env.results_dir / f"{canary}.json" ).read_text( encoding="utf-8" ) )[ "searches" ]
    return run_searches( env, f"{spec[ 'prefix' ]}-run", items[ spec[ "canary_members" ]: ], twins, ceiling_tokens, prior=prior, canary_run=canary )


def ask_old( ctx, item ):
    """Ensures: returns the public result of the old question's full sweep, the member left out."""
    return rt.sweep_need_impl( item[ "need" ], item[ "member" ], ctx )


def ask_new( ctx, item ):
    """Ensures: returns the public result of the new question's full sweep, the member left out."""
    return rt.sweep_need_impl( item[ "need" ], item[ "member" ], ctx, question="provides" )


NEW_ASK = ask_new                                           # the new question's ask; set to None and "new" is refused

FIRST_LINE = ( "100 searches, one per twin group, drawn from 151 groups of Python structural clones (exact and near); no TypeScript or JavaScript; "
               "no conceptual duplicates. This measures recall on clones, an upper bound for the harder case." )


def _asks( names ):
    """
    Turn the question names into asks, in order.

    Raises:
        - DriverRefused for a name that is not old or new, or for new while the new question is not wired
    """
    out = {}
    for name in names:
        if name not in QUESTION_NAMES: raise s1.DriverRefused( f"question {name!r} is not one of {QUESTION_NAMES}" )
        if name == "new" and NEW_ASK is None: raise s1.DriverRefused( "the new question is not wired yet; run old only" )
        out[ name ] = ask_old if name == "old" else NEW_ASK
    return out


def report_lines( searches, questions ):
    """
    Write the report as lines: the statement, each question's figures, the paired result.

    Ensures:
        - the first line is the statement of what the run is, in the words fixed in advance
        - every figure is given with its count out of the searches run and a 95% Wilson interval, an incomplete search counting as a miss
        - the searches run are stated out of the sample, and any not run are named
    """
    lines = [ FIRST_LINE ]
    for q, fig in e2e.figures( searches, questions ).items():
        lines.append( f"{q}: n run: {fig[ 'n_run' ]} of {e2e.MEMBERS}, complete {fig[ 'complete' ]}, incomplete {fig[ 'incomplete' ]}, not run {fig[ 'not_run' ]}" )
        for key, label in ( ( "on_shortlist", "twin on the shortlist" ), ( "ranked_first", "twin ranked first" ), ( "top_ten", "twin in the top ten" ) ):
            for suffix, note in ( ( "", "all run" ), ( "_complete", "complete only" ) ):
                c = fig[ key + suffix ]
                lines.append( f"  {label} ({note}): {c[ 'k' ]} of {c[ 'n' ]}, 95% interval {c[ 'interval' ]}" )
        lines.append( f"  incomplete causes {fig[ 'causes' ]}; verdict classes {fig[ 'verdicts' ]}; unasked {fig[ 'unasked' ]}; requests {fig[ 'requests' ]}; "
                      f"429 {fig[ 'n429' ]}, 529 {fig[ 'n529' ]}; dollars per search {fig[ 'usd_per_search' ]}" )
    if len( questions ) == 2:
        for key, row in e2e.paired( searches, questions[ 0 ], questions[ 1 ] ).items(): lines.append( f"paired {key}: {row}" )
    return lines


def _parser():
    """Ensures: returns the command line parser."""
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--root" )
    ap.add_argument( "--data" )
    ap.add_argument( "--ledger" )
    ap.add_argument( "--live", action="store_true" )
    ap.add_argument( "--pack-size", type=int, default=50 )
    ap.add_argument( "--questions", default="old" )
    sub = ap.add_subparsers( dest="command", required=True )
    for name in ( "status", "ledger-init", "canary", "approve", "run", "report" ):
        p = sub.add_parser( name )
        if name in ( "canary", "approve", "run", "report" ):
            p.add_argument( "--sample", required=True )
            p.add_argument( "--sample-sha", default=e2e.SAMPLE_SHA256 )
            p.add_argument( "--needs", required=True )
            p.add_argument( "--needs-sha", required=True )
            p.add_argument( "--manifest", required=True )
            p.add_argument( "--manifest-sha", default=e2e.MANIFEST_SHA256 )
        if name in ( "canary", "run" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
            p.add_argument( "--revised-estimate", type=int, default=None )
    return ap


def _open_env( root, data, ledger, live, asks, pack_size ):
    """Ensures: returns the environment; a stand-in run gets a marked folder and the stand-in."""
    data, ledger = rr.check_paths( root, data, ledger, live )
    factory      = None
    if not live:
        data.mkdir( parents=True, exist_ok=True )
        ( data / rr.STAND_IN_MARKER ).write_text( "written by a stand-in run; never read by a live one\n", encoding="utf-8" )
        factory = rr.StandIn
    return E2EEnv( root, data, rl.AccountLedger( ledger ), asks, transport_factory=factory, pack_size=pack_size )


def main( argv=None ):
    """
    Run one step of the end-to-end run.

    Ensures:
        - returns 0 after the step; prints how it ended
    Raises:
        - the refusals of the checks and of the frozen inputs, before anything is created or sent
    """
    args = _parser().parse_args( argv )
    root = args.root or os.environ.get( "LUPIN_ROOT" )
    if not root: raise rr.RunnerRefused( "give --root, or set LUPIN_ROOT" )
    if args.command == "ledger-init":
        if args.live: raise rr.RunnerRefused( "ledger-init is for a stand-in run; the real ledger is created by hand, on the go" )
        env = _open_env( root, args.data, args.ledger, False, {}, args.pack_size )
        env.ledger.path.parent.mkdir( parents=True, exist_ok=True )
        rl.AccountLedger.create( env.ledger.path, rl.ACCOUNT_LIMIT_TOKENS, "e2e-runner", "scratch ledger for a stand-in run" )
        print( f"ledger created: {env.ledger.path}" )
        return 0
    names = [ n for n in args.questions.split( "," ) if n ]
    rr.check_paths( root, args.data, args.ledger, args.live )                                    # a path refusal comes before the slow reads
    if args.command == "status":
        env = _open_env( root, args.data, args.ledger, args.live, {}, args.pack_size )
        print( f"ledger {env.ledger.snapshot()}  pack size {env.pack_size}  questions {names}" )
        return 0
    asks = _asks( names )
    members = e2e.load_sample( args.sample, args.sample_sha )
    items   = e2e.load_needs( args.needs, args.needs_sha, members, args.sample_sha )
    twins   = e2e.load_twins( args.manifest, args.manifest_sha )
    env     = _open_env( root, args.data, args.ledger, args.live, asks, args.pack_size )
    if args.command == "canary":
        print( canary_line( run_canary( env, items, twins, args.ceiling ) ) )
    elif args.command == "approve":
        approve_canary( env, args.by, args.why, revised_estimate=args.revised_estimate )
        print( f"canary approved by {args.by}" )
    elif args.command == "run":
        print( run_line( run_full( env, items, twins, args.ceiling ) ) )
    else:
        searches = []
        for name in ( CANARY_NAME, RUN_NAME ):
            path = env.results_dir / f"{name}.json"
            if path.exists(): searches += json.loads( path.read_text( encoding="utf-8" ) )[ "searches" ]
        print( "\n".join( report_lines( searches, names ) ) )
    return 0


def cli( argv=None ):
    """
    Run main as a command line: a refusal is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a refusal of the runner, the driver, the frozen inputs or the ledger
        - any other error propagates untouched, so a crash is never read as a refusal
    """
    try: return main( argv )
    except ( rr.RunnerRefused, s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, s1.CanaryTripped, s1.StageRefused,
             e2e.FrozenInputRefused, rl.AccountLimitReached, rl.LedgerUnreadable ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    raise SystemExit( cli() )
