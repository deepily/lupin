"""
The yield replay: the yield needs, traced end to end with each seed as its known answer.

The needs are rebuilt from the saved drafting and second-check ledgers of an earlier run, so the drafter and the second model are never asked.
A seed whose answers were not saved is listed as unsaved, and a live run that has one stops before it spends anything.
A live run makes only the trace's judge and probe calls. They run under one stage of the call cap, with a budget of its own.
Without --live it rebuilds the needs, reports how many there are and which seeds gave none, and makes no model call.
It never builds a packet, takes a person's ruling or writes a label file.
"""
import argparse
import asyncio
import json
import pathlib
import shutil
import types

from cosa.repo.doc_lint import harness_report, model_transport
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, draft, first_thousand, loss_trace, smoke, source_at, stage_parts, stage_seeds, stages, strip
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_seeded_miss_e2e import NoCallTransport, SavedAnswerMissing

YIELD_TRACE  = "yield_trace"
TRACE_BUDGET = 260                       # about 69 needs at about 3 calls each, with room for retries
RUN_LIMIT    = 300
SAVED_FILES  = ( "ledger-stage-draft.jsonl", "ledger-stage-second.jsonl", stage_seeds.LISTS_FILE )
TRACE_FILE   = "ledger-trace.jsonl"
REPORT_FILE  = "yield-trace-report.json"
CALLS_FILE   = first_thousand.CALLS_FILE
DONE         = "done"
BUDGET       = "budget_reached"
CAP          = "cap_reached"
STOPPED      = "stopped"
FAILED       = "failed"


def saved_ask( system, prompt ):
    """
    Stand in for the drafter and the second model.

    Raises:
        - SavedAnswerMissing always, so a seed with no saved answer is reported and no model is contacted
    """
    raise SavedAnswerMissing( "the saved ledgers hold no answer to this question; the yield replay never asks the drafter or the second model" )


def hold_transport( ctx ):
    """
    Give the context a transport that refuses every request.

    Requires:
        - ctx is a reuse context that has not been prepared

    Ensures:
        - prepare then builds no live transport, so it begins no spend-ledger run and holds no ceiling
        - a request that reaches the transport is refused and its need kept, so nothing is sent
    """
    ctx.transport = NoCallTransport()


def copy_saved( from_run, run_dir, names=SAVED_FILES ):
    """
    Copy the saved ledgers and the seed lists of an earlier run into this run's folder.

    Requires:
        - from_run is the earlier run's folder; run_dir exists
        - names are the files to copy, the saved ledgers and the seed lists unless a caller names more

    Ensures:
        - a file already in run_dir is kept as it is, so a resumed run is not overwritten
        - the earlier run's folder is only read
        - returns the names copied, in the order of names

    Raises:
        - NeedsetError SAVED_FILE_MISSING naming a file the earlier run lacks, before anything is copied
    """
    missing = [ n for n in names if not ( pathlib.Path( run_dir ) / n ).exists() and not ( pathlib.Path( from_run ) / n ).is_file() ]
    if missing: raise er.NeedsetError( er.SAVED_FILE_MISSING, f"{from_run} lacks {missing}" )
    copied = [ n for n in names if not ( pathlib.Path( run_dir ) / n ).exists() ]
    for name in copied: shutil.copyfile( pathlib.Path( from_run ) / name, pathlib.Path( run_dir ) / name )
    return copied


async def rebuild( order, make_need ):
    """
    Turn each yield seed into its final need from the saved answers.

    Requires:
        - make_need is an async function taking a seed id and returning a final need or None; it raises SavedAnswerMissing for an unsaved answer

    Ensures:
        - seeds run one at a time in the order given
        - returns ( needs, unsaved ): the needs found, and the seeds whose answers were not saved
        - a seed with no need for another reason is in neither list; the tally counts it
    """
    needs, unsaved = [], []
    for seed_id in order:
        try:
            need = await make_need( seed_id )
        except SavedAnswerMissing:
            unsaved.append( seed_id )
            continue
        if need is not None: needs.append( need )
    return needs, unsaved


async def rebuild_head( lists_path, make_need, tally ):
    """
    Rebuild the yield needs and describe them.

    Requires:
        - lists_path is a seed-lists file; tally is the Tally that make_need counts into

    Ensures:
        - returns ( needs, head ) with head holding seeds, needs, unsaved, no_final_need, by_lang (needs per write language) and lists_sha
        - no_final_need counts only this call's seeds
    """
    lists = stage_seeds.load_lists( lists_path )
    order = lists[ stages.YIELD ][ "order" ]
    since = stage_parts.mark( tally )
    needs, unsaved = await rebuild( order, make_need )
    by_lang = {}
    for n in needs: by_lang[ n[ "write_lang" ] ] = by_lang.get( n[ "write_lang" ], 0 ) + 1
    return needs, { "seeds": len( order ), "needs": len( needs ), "unsaved": unsaved, "no_final_need": stage_parts.counted( tally, since ),
                    "by_lang": dict( sorted( by_lang.items() ) ), "lists_sha": lists[ "sha" ] }


def found_intervals( summary ):
    """
    Give each language's found share with its two-sided 95 percent interval.

    Requires:
        - summary is loss_trace.summarize_members' dict

    Ensures:
        - returns { lang: { found, members, interval } } with interval from harness_report.interval
    """
    out = {}
    for lang, counts in summary[ "by_lang" ].items():
        found, total = counts.get( loss_trace.FOUND, 0 ), sum( counts.values() )
        out[ lang ] = { "found": found, "members": total, "interval": harness_report.interval( found, total ) }
    return out


async def trace_needs( needs, head, trace_fn ):
    """
    Trace the needs and report where each key member was lost.

    Requires:
        - trace_fn is an async function taking the needs and returning the trace records, as loss_trace.trace_all does

    Ensures:
        - returns head plus stages.attribution_report's figures, found_intervals and traced True
        - when the stage's own budget ends the trace, returns head with budget_reached True, budget_detail and traced False; finished traces stay in the trace ledger and a rerun resumes from them

    Raises:
        - NeedsetError for anything but the stage budget, the call cap included
    """
    try:
        records = await trace_fn( needs )
    except er.NeedsetError as error:
        if error.code != er.STAGE_BUDGET_REACHED: raise
        return { **head, "budget_reached": True, "budget_detail": error.detail, "traced": False }
    report = stages.attribution_report( records )
    return { **head, **report, "found_by_lang": found_intervals( report[ "summary" ] ), "traced": True }


async def run_traced( run_dir, limit, budget, work ):
    """
    Run the traced work under the call cap and write the report.

    Requires:
        - work is an async function taking no argument and returning a report dict

    Ensures:
        - the cap reads its count from call-ledger.jsonl in run_dir and gives the stage YIELD_TRACE budget calls
        - returns { used, limit, by_stage, status, report } and writes it as yield-trace-report.json
        - status is done, stopped (the report says stop), budget_reached, cap_reached or failed; a NeedsetError ends the run with a report and no exception
    """
    cap = call_cap.CallCap( f"{run_dir}/{CALLS_FILE}", limit, { YIELD_TRACE: budget } )
    with cap.installed():
        try:
            with call_cap.stage( YIELD_TRACE ):
                report = await work()
            status = BUDGET if report.get( "budget_reached" ) else STOPPED if report.get( "stop" ) else DONE
        except er.NeedsetError as error:
            report = { "code": error.code, "detail": error.detail }
            status = CAP if error.code == er.CALL_CAP_REACHED else FAILED
    out = { "used": cap.used(), "limit": limit, "by_stage": cap.by_stage(), "status": status, "report": report }
    pathlib.Path( f"{run_dir}/{REPORT_FILE}" ).write_text( json.dumps( out, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
    return out


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the source tree, this run's folder, the earlier run's folder, the seed and the source commit are required
        - live is false unless --live is given, and without it nothing but files is read and no model is contacted
        - the cap is RUN_LIMIT calls and the stage budget TRACE_BUDGET unless named
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "from_run", "seed", "source_commit" ): ap.add_argument( "--" + name.replace( "_", "-" ), required=True, type=int if name == "seed" else str )
    ap.add_argument( "--limit", type=int, default=RUN_LIMIT )
    ap.add_argument( "--budget", type=int, default=TRACE_BUDGET )
    ap.add_argument( "--cli-path", default=None )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--probe-model", default=smoke.SECOND_MODEL )
    ap.add_argument( "--live", action="store_true" )
    return ap.parse_args( argv )


def live_parts( args, root, ctx, deps ):
    """
    Build the parts that rebuild the needs from the saved answers and trace them.

    Requires:
        - root is the source commit's tree; ctx is its reuse context

    Ensures:
        - returns the parts build_parts gives, over the saved ledgers copied into args.run_dir
        - the drafter and the second model are saved_ask, so a missing answer raises SavedAnswerMissing and no model is contacted
        - the seed is its own known answer, because partners is off
        - every ledger lives in args.run_dir, and the earlier run's folder is not touched
    """
    make    = lambda name: draft.make_ledger( f"{args.run_dir}/{name}", args.cli_path, args.server )
    built   = deps[ "built" ]( args ) if "built" in deps else smoke.index_parts( root, f"{args.run_dir}/index" )
    ledgers = { "draft": draft.SharedLedger( make( SAVED_FILES[ 0 ] ) ), "second": draft.SharedLedger( make( SAVED_FILES[ 1 ] ) ), "trace": make( TRACE_FILE ),
                "rejections": stage_parts.RejectionLedger( f"{args.run_dir}/{first_thousand.REJECTIONS_FILE}" ) }
    env     = types.SimpleNamespace( root=root, run_dir=args.run_dir, seed=args.seed, source_commit=args.source_commit, server=args.server,
                                     strip_fn=lambda rec: strip.strip_member( rec, root ), ctx=ctx, ask=saved_ask )
    lists   = stage_seeds.load_lists( f"{args.run_dir}/{stage_seeds.LISTS_FILE}" )
    build   = deps[ "build_parts" ] if "build_parts" in deps else stage_parts.build_parts
    return build( env, built, lists, { "second": args.probe_model, "probe": args.probe_model }, saved_ask, saved_ask, ledgers, False )


def main( argv=None, deps=None ):
    """
    Rebuild the yield needs from the saved answers, and with --live trace them.

    Requires:
        - deps is None for the real parts, or a mapping that replaces any of: source_root, context, built, build_parts, close_run, runner
        - a run needs --cli-path, because the ledgers are bound to the binary's version
        - the reuse environment variables the context reads are set

    Ensures:
        - without --live returns { live False, plan } with the counts of seeds, needs and unsaved seeds; no model is contacted and no spend-ledger run is begun
        - with --live and an unsaved seed returns the plan with a stopped report and no call
        - with --live and every answer saved the needs are traced under the cap and the report is returned and written
        - with --live the spend-ledger run is closed when the trace ends, however it ends
        - the earlier run's folder is only read; this run's folder holds every copy and every new file

    Raises:
        - NeedsetError NO_CLI_PATH without --cli-path, SAVED_FILE_MISSING for a file the earlier run lacks, before the context is built
        - whatever the source tree, the context and the parts raise
    """
    args = parse_args( argv )
    deps = {} if deps is None else deps
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledgers are bound to the Claude Code binary's version, so even a plan needs --cli-path" )
    model_transport.configure( cli_path=args.cli_path )
    pathlib.Path( args.run_dir ).mkdir( parents=True, exist_ok=True )
    copy_saved( args.from_run, args.run_dir )
    made, repo = "source_root" not in deps, args.root
    root       = deps[ "source_root" ]( args ) if not made else source_at.ensure_worktree( repo, args.source_commit )
    try:
        ctx   = ( deps[ "context" ] if "context" in deps else rt.context_from_environment )( root )
        close = deps[ "close_run" ] if "close_run" in deps else rt.close_run
        try:
            return _run( args, root, ctx, deps, close )
        except BaseException:
            try: close( ctx )
            except Exception as error: print( f"close_run failed while another error was raised: {error!r}" )
            raise
    finally:
        if made: source_at.unlock( repo, root )


def _run( args, root, ctx, deps, close ):
    """
    Rebuild the needs; with --live trace them and close the spend-ledger run.

    Ensures:
        - returns { live, plan, report, closed_run, close_error } for a live run and { live False, plan } for a plan
    """
    if not args.live: hold_transport( ctx )
    parts = live_parts( args, root, ctx, deps )
    path  = f"{args.run_dir}/{stage_seeds.LISTS_FILE}"
    needs, head = asyncio.run( rebuild_head( path, parts[ "make_need" ], parts[ "tally" ] ) )
    if not args.live: return { "live": False, "plan": head }
    if head[ "unsaved" ] or not needs:
        why = f"{len( head[ 'unsaved' ] )} seeds have no saved answer" if head[ "unsaved" ] else "no seed gave a need"
        report = { "used": 0, "limit": args.limit, "by_stage": {}, "status": STOPPED, "report": { **head, "stop": True, "reason": why } }
    else:
        runner = deps[ "runner" ] if "runner" in deps else run_traced
        report = asyncio.run( runner( args.run_dir, args.limit, args.budget, lambda: trace_needs( needs, head, parts[ "trace_fn" ] ) ) )
    try:
        closed, close_error = close( ctx ), None
    except Exception as error:
        closed, close_error = None, repr( error )
    return { "live": True, "plan": head, "report": report, "closed_run": closed, "close_error": close_error }


def exit_status( result ):
    """
    Say what the process should exit with for the result main returned.

    Ensures:
        - returns 1 when the run failed or the spend-ledger run could not be closed, 3 when the cap or the stage budget ended it, else 0
        - a plan, a stop and a finished trace are 0, because a stop on a finding is a result and not a failure
    """
    if not result[ "live" ]: return 0
    if result[ "close_error" ] is not None or result[ "report" ][ "status" ] == FAILED: return first_thousand.EXIT_FAILED
    return first_thousand.EXIT_CAP_REACHED if result[ "report" ][ "status" ] in ( CAP, BUDGET ) else 0


def run_cli( argv=None, deps=None, out=print ):
    """
    Run main, print its result as JSON and return the exit status.

    Ensures:
        - the JSON goes to out before the status is returned
    """
    result = main( argv, deps )
    out( json.dumps( result, indent=4, sort_keys=True ) )
    return exit_status( result )


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; run_cli is tested with stand-ins
    import sys
    sys.exit( run_cli() )
