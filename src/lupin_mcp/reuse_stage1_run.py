"""
The packing runner: one command for each step of the run sheet, on a stand-in by default.

Every command builds the same driver environment from the same index. Without --live the transport is
a stand-in that answers from a hash of the candidate text. A stand-in run needs a data folder and a
ledger of its own, because its fake answers must never be read as real ones. The stand-in marks its
folder, and a live run refuses a marked folder. With --live the transport is the real one and the paths
default to the real ones. The driver refuses a missing key before it opens a ledger run.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

from lupin_mcp import reuse_ledger as rl
from lupin_mcp import reuse_stage1 as s1
from lupin_mcp import reuse_stage1_analysis as an
from lupin_mcp import reuse_stage1_probe as sp
from lupin_mcp import reuse_tools as rt

NEEDS = { 1: "A function that sends a notification to the user and waits for a yes/no answer, returning the answer.",
          2: "A function that checks that a database table's actual schema matches the expected columns, and reports any mismatch.",
          3: "A function that marks a one-time token record as used, so it cannot be redeemed twice.",
          4: "A function that takes an LLM reply containing a fenced JSON block and returns the metadata fields from it." }
STAND_IN_MARKER = ".stand-in"
STAND_IN_CLIENT = "stand-in"
NOT_READY       = ( "NOT_LUPIN_TREE", "INDEX_STALE", "DEPENDENCY_MISSING" )
ARM_NAMES       = sorted( arm for arm in s1.ARMS if arm != "canary" )
PACK_ARMS       = ( "single1", "single2", "pack10", "pack50", "pack200" )


class RunnerRefused( Exception ):
    """The runner would not start a step, and opened nothing."""


class StandIn:
    """
    A transport that answers a packed body from a hash of each candidate's text.

    Ensures:
        - the same text gets the same answer, whatever the pack it sits in, apart from a tiny jitter by pack size
        - every post takes one attempt from the budget and reports 40 output tokens for each question
    """

    def __init__( self, budget ): self.budget = budget

    def post_with_meta( self, body ):
        """Ensures: returns ( parsed response, meta ) shaped as the live transport's."""
        self.budget.take()
        questions, answers = body[ "questions" ], {}
        for key, question in questions.items():
            u = int( hashlib.sha256( question[ "instructions" ].encode() ).hexdigest()[ :8 ], 16 ) / 0xFFFFFFFF
            u = min( 1.0, max( 0.0, u + 0.002 * ( len( questions ) % 5 - 2 ) ) )
            answers[ key ] = { "probabilities": { "reuse": round( u * 0.6, 6 ), "extend": round( u * 0.4, 6 ), "unrelated": round( 1 - u, 6 ) } }
        usage = { "input_tokens": len( json.dumps( body ) ) // 4, "output_tokens": 40 * len( questions ) }
        meta  = { "status": 200, "attempts": 1, "retry_after": None, "latency_ms": 2, "attempt_log": [ { "status": 200, "request_ids": {} } ], "client_version": STAND_IN_CLIENT }
        return { "answers": answers, "model": body[ "model" ], "usage": usage }, meta


def load_inputs( root ):
    """
    Read the index the way the tool path does.

    Requires:
        - root is the repository tree to run in
    Ensures:
        - returns ( entries, pages ): entries are the sendable index symbols; pages are { id, sig, doc } dicts, one per wiki page
    Raises:
        - RunnerRefused when the index is not a lupin tree, is stale, lists a missing dependency, or lists a page slug twice
    """
    ctx = rt.context_from_environment( root )
    flags, entries, _, _ = rt.prepare( ctx )
    for flag in NOT_READY:
        if flag in flags: raise RunnerRefused( f"the index is not ready: {flag}" )
    pages, seen = [], set()
    for page in ctx.pages:
        if page[ "slug" ] in seen: raise RunnerRefused( f"page slug {page[ 'slug' ]!r} is listed twice in the wiki index" )
        seen.add( page[ "slug" ] )
        pages.append( { "id": page[ "slug" ], "sig": "", "doc": page[ "text" ] } )
    return entries, pages


def check_paths( root, data, ledger, live ):
    """
    Settle which data folder and ledger a run uses, creating nothing.

    Requires:
        - data and ledger are paths or None; live is a bool
    Ensures:
        - returns ( data, ledger ) as paths
        - without live: both were named, and neither is the real one
        - with live: the real paths, whether or not they are named; naming another is refused; the ledger is there and the folder is not marked
    Raises:
        - RunnerRefused for any of the above that does not hold
    """
    real_data, real_ledger = pathlib.Path( rt.data_dir( root ) ), pathlib.Path( rl.ledger_path( root ) )
    if live:
        if data and pathlib.Path( data ).resolve() != real_data.resolve(): raise RunnerRefused( "a live run uses the real data folder only" )
        if ledger and pathlib.Path( ledger ).resolve() != real_ledger.resolve(): raise RunnerRefused( "a live run uses the real ledger only: spend on another would escape the account limit" )
        data, ledger = real_data, real_ledger
        if ( data / STAND_IN_MARKER ).exists(): raise RunnerRefused( f"{data} was written by a stand-in run; a live run will not read its answers" )
        if not ledger.exists(): raise RunnerRefused( f"{ledger} does not exist; create the ledger first" )
        return data, ledger
    if data is None: raise RunnerRefused( "a stand-in run needs --data, a folder of its own" )
    if ledger is None: raise RunnerRefused( "a stand-in run needs --ledger, a ledger of its own" )
    data, ledger = pathlib.Path( data ), pathlib.Path( ledger )
    if data.resolve() == real_data.resolve(): raise RunnerRefused( "a stand-in run will not use the real data folder: its fake answers would be read as real ones" )
    if ledger.resolve() == real_ledger.resolve(): raise RunnerRefused( "a stand-in run will not use the real ledger" )
    return data, ledger


def open_env( root, data, ledger, live, entries_in_index ):
    """
    Build the driver environment, or refuse before anything is created.

    Ensures:
        - refuses as check_paths does
        - without live: a stand-in transport, and the data folder created and marked
        - with live: the real transport
    Raises:
        - RunnerRefused as check_paths does
    """
    data, ledger = check_paths( root, data, ledger, live )
    if live: factory = None
    else:
        data.mkdir( parents=True, exist_ok=True )
        ( data / STAND_IN_MARKER ).write_text( "written by a stand-in run; never read by a live one\n", encoding="utf-8" )
        factory = StandIn
    return s1.Stage1Env( root, data, rl.AccountLedger( ledger ), transport_factory=factory, entries_in_index=entries_in_index )


def _summary( record ):
    """Ensures: returns one line saying how an arm ended."""
    t = record[ "totals" ]
    return ( f"{record[ 'run_name' ]}: state {record[ 'state' ]}, stop {record[ 'stop_reason' ]}, answers {len( record[ 'answers' ] )}, failed {len( record[ 'failed' ] )}, "
             f"not reached {len( record[ 'not_reached' ] )}, requests {t[ 'requests' ]}, spent {t[ 'spent_tokens' ]}" )


def _single_run( env, question ):
    """Ensures: returns the question's single run 1 record; raises RunnerRefused if none."""
    path = env.results_dir / f"{s1.run_name( question, 'single1' )}.json"
    if not path.exists(): raise RunnerRefused( f"question {question} has no single run 1 yet" )
    return json.loads( path.read_text() )


def _probe_arm( env, question, entries, arm ):
    """Ensures: returns { entries, probe } for a probe arm, checked against the plan on disk."""
    built = sp.build_probe_plan( entries, _single_run( env, question ) )
    path  = env.results_dir / f"s1-q{question}-probe-plan.json"
    if not path.exists(): raise RunnerRefused( f"write the probe plan first, for question {question}" )
    if json.loads( path.read_text() ) != built[ "plan" ]: raise RunnerRefused( f"the probe plan on disk no longer matches single run 1 of question {question}" )
    return built[ "arms" ][ arm ]


def _parser():
    """Ensures: returns the command line parser."""
    ap = argparse.ArgumentParser( description=__doc__ )
    ap.add_argument( "--root" )
    ap.add_argument( "--data" )
    ap.add_argument( "--ledger" )
    ap.add_argument( "--live", action="store_true" )
    sub = ap.add_subparsers( dest="command", required=True )
    sub.add_parser( "status" )
    sub.add_parser( "ledger-init" )
    sub.add_parser( "report" )
    for name in ( "canary", "approve", "arm", "probe-plan", "old-shape" ):
        p = sub.add_parser( name )
        p.add_argument( "--question", type=int, required=True )
        if name in ( "canary", "arm" ): p.add_argument( "--ceiling", type=int, required=True )
        if name == "arm":
            p.add_argument( "--arm", choices=ARM_NAMES, required=True )
            p.add_argument( "--attempt-limit", type=int )
            p.add_argument( "--attempt", type=int, default=1 )
            p.add_argument( "--reason" )
        if name == "approve":
            p.add_argument( "--by", required=True )
            p.add_argument( "--why", required=True )
    return ap


def main( argv=None, loader=None ):
    """
    Run one step of the run sheet.

    Requires:
        - argv is a command line without the program name; loader reads the index (the real one by default)
    Ensures:
        - returns 0 after the step; prints how it ended
    Raises:
        - RunnerRefused before anything is created or sent, and the driver's own refusals as they come
    """
    args = _parser().parse_args( argv )
    root = args.root or os.environ.get( "LUPIN_ROOT" )
    if not root: raise RunnerRefused( "give --root, or set LUPIN_ROOT" )
    if args.command == "ledger-init":
        if args.live: raise RunnerRefused( "ledger-init is for a stand-in run; the real ledger is created by hand, on the go" )
        env = open_env( root, args.data, args.ledger, False, None )
        env.ledger.path.parent.mkdir( parents=True, exist_ok=True )
        rl.AccountLedger.create( env.ledger.path, rl.ACCOUNT_LIMIT_TOKENS, "runner", "scratch ledger for a stand-in run" )
        print( f"ledger created: {env.ledger.path}" )
        return 0
    if args.command != "ledger-init": check_paths( root, args.data, args.ledger, args.live )                  # a path refusal comes before the slow read of the index
    entries, pages = ( loader or load_inputs )( root ) if args.command in ( "status", "canary", "arm", "probe-plan", "old-shape" ) else ( [], [] )
    env = open_env( root, args.data, args.ledger, args.live, len( entries ) if entries else None )
    if args.command == "status":
        print( f"ledger {env.ledger.snapshot()}  stage remaining {s1.stage_remaining( env.ledger )}  entries {len( entries )}  pages {len( pages )}" )
    elif args.command == "canary":
        report = s1.run_canary( env, args.question, NEEDS[ args.question ], entries, args.ceiling )
        print( f"canary {report[ 'run_name' ]}: tripped {report[ 'tripped' ]}, output per entry {report[ 'output_tokens_per_entry' ]}, unasked {report[ 'unasked' ]}, approved {report[ 'approved' ]}" )
    elif args.command == "approve":
        s1.approve_canary( env, args.question, args.by, args.why )
        print( f"canary of question {args.question} approved by {args.by}" )
    elif args.command == "arm":
        if args.arm in PACK_ARMS: arm_entries, probe = entries, None
        elif args.arm.startswith( "page-" ): arm_entries, probe = pages, None
        else: chosen = _probe_arm( env, args.question, entries, args.arm ); arm_entries, probe = chosen[ "entries" ], chosen[ "probe" ]
        print( _summary( s1.run_arm( env, args.question, args.arm, NEEDS[ args.question ], arm_entries, args.ceiling, attempt_limit=args.attempt_limit, probe=probe, attempt=args.attempt, reason=args.reason ) ) )
    elif args.command == "probe-plan":
        built = sp.build_probe_plan( entries, _single_run( env, args.question ) )
        print( f"probe plan written: {sp.write_probe_plan( env, built )}  probe {built[ 'plan' ][ 'probe_id' ]}" )
    elif args.command == "old-shape":
        record = an.old_shape_arm( args.question, env.data, NEEDS[ args.question ], entries )
        path   = env.results_dir / f"s1-q{args.question}-old-shape.json"
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( json.dumps( record, sort_keys=True, indent=1 ) + "\n", encoding="utf-8" )
        print( f"old-shape record written: {path}  hits {record[ 'cache_hits' ]} of {len( entries )}" )
    else:
        return an.main( [ str( env.results_dir ) ] )
    return 0


def cli( argv=None, loader=None ):
    """
    Run main as a command line: a refusal the runner makes is one line and exit code 2.

    Ensures:
        - returns main's own code when it works
        - returns 2 after one line on the error stream for a RunnerRefused, DriverRefused, KeyMissing, CanaryNotApproved, CanaryTripped or StageRefused
        - any other error propagates untouched, so a crash is never read as a refusal
    """
    try: return main( argv, loader )
    except ( RunnerRefused, s1.DriverRefused, s1.KeyMissing, s1.CanaryNotApproved, s1.CanaryTripped, s1.StageRefused ) as e:
        print( f"refused ({type( e ).__name__}): {e}", file=sys.stderr )
        return 2


if __name__ == "__main__":  # pragma: no cover -- the module entry point; cli is what the tests drive
    raise SystemExit( cli() )
