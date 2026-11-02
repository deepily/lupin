"""
The forced-shortlist judge: does the judge accept a planted rewrite that retrieval missed?

Take each drafted control pair that retrieval missed. The plant is put into the shortlist of 128, and the judge is asked about it in a pack of its own.
The other 127 places hold the real shortlist, asked in the usual packs. The result is the judge's answer for the plant, beside the pair's human label.
The needs are the frozen drafts of the control, read from the saved ledger, so no sentence is written again.
Without --live it reads files only: it contacts no model, no search and no spend ledger, and builds no reuse context.
It never builds a packet, takes a person's ruling or writes a label file.
"""
import argparse
import copy
import hashlib
import json
import os
import pathlib

from cosa.repo.doc_lint import model_transport
from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_redact
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, draft, expansion_run, first_thousand, planted_pool, positive_control, source_at, stage3, strip, yield_trace
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_seeded_miss_e2e import SavedAnswerMissing

STAGE_NAME   = "forced_judge"
BUDGET       = 100                 # 12 missed pairs at 4 requests each, with room for retries
REQUESTS_PER = 4                   # 127 real places are 3 packs of up to 50, and the plant is one pack of its own
SHORTLIST    = 128
SAME_JOB     = "same_job"
NOT_SAME     = "not_same"
UNRESOLVED   = "unresolved"
NONE_CHOICE  = first_thousand.NONE_CHOICE
EXTRA_FILES  = ( "ledger-control-draft.jsonl", "run-env.sh" )
REPORT_FILE  = "forced-judge-report.json"
CACHE_DIR    = "query-cache"
DONE         = "done"
CAP          = "cap_reached"
BUDGET_HIT   = "budget_reached"
FAILED       = "failed"


def missed_ids( report_path ):
    """
    Read the rewrite ids the control's retrieval missed from a stage report.

    Requires:
        - report_path is a stage-reports json file whose control stage ran

    Ensures:
        - returns the first pass's missed list, in the report's order
    """
    return list( json.loads( pathlib.Path( report_path ).read_text( encoding="utf-8" ) )[ "stages" ][ "control" ][ "report" ][ "missed" ] )


def resolved_label( first, second, third ):
    """
    Resolve one pair's human label.

    Requires:
        - first, second and third are label rows with a choice, or None for no label; third is the tie-breaker

    Ensures:
        - returns same_job when the first two raters both chose a symbol, not_same when both chose none
        - when they differ, the third rater decides; with no third label the pair is unresolved
        - a pair missing a first or second label is unresolved
    """
    if first is None or second is None: return UNRESOLVED
    a, b = first[ "choice" ] == NONE_CHOICE, second[ "choice" ] == NONE_CHOICE
    if a == b: return NOT_SAME if a else SAME_JOB
    if third is None: return UNRESOLVED
    return NOT_SAME if third[ "choice" ] == NONE_CHOICE else SAME_JOB


def pair_labels( pairs, answer_key, first, second, third ):
    """
    Resolve the human label of each pair.

    Requires:
        - pairs come from positive_control.load_pairs; answer_key is the key's items by pair id, each with a and b
        - first, second and third are first_thousand.read_latest_labels results

    Ensures:
        - returns { rewrite id: label } for every pair, the label being resolved_label's
    """
    by_ids = { frozenset( ( v[ "a" ], v[ "b" ] ) ): k for k, v in answer_key.items() }
    out    = { }
    for p in pairs:
        item = by_ids.get( frozenset( ( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) ) )
        out[ p[ "rewrite" ][ "id" ] ] = resolved_label( first.get( item ), second.get( item ), third.get( item ) )
    return out


def frozen_needs( pairs, ledger, strip_fn ):
    """
    Read the control's frozen drafts from the saved ledger.

    Requires:
        - ledger is the control's drafting ledger; no model is ever asked

    Ensures:
        - returns { rewrite id: need sentence } for each pair whose draft passed
        - a pair whose draft was not saved, or never passed, is absent
    """
    out = { }
    for p in pairs:
        try:
            rec = draft.draft_need( first_thousand.control_job( p, strip_fn ), yield_trace.saved_ask, ledger, max_tries=first_thousand.CONTROL_TRIES )
        except SavedAnswerMissing:
            continue
        if rec[ "ok" ]: out[ p[ "rewrite" ][ "id" ] ] = rec[ "need" ]
    return out


def build_rows( pairs, missed, needs, labels ):
    """
    Build the rows to judge: the drafted pairs that retrieval missed.

    Ensures:
        - returns { pair, id, lang, label, need } in file order, for each pair in missed that has a frozen draft
        - returns as the second value the missed ids with no frozen draft
    """
    rows, undrafted = [ ], [ ]
    for p in pairs:
        rid = p[ "rewrite" ][ "id" ]
        if rid not in missed: continue
        if rid not in needs:
            undrafted.append( rid )
            continue
        rows.append( { "pair": p, "id": rid, "lang": p[ "rewrite" ][ "lang" ], "label": labels[ rid ], "need": needs[ rid ] } )
    return rows, undrafted


def forced_ids( ranking, plant_id, size=SHORTLIST ):
    """
    Choose the places of the real shortlist that stay beside the plant.

    Requires:
        - ranking is the fused order of the stage's answer

    Ensures:
        - returns ( real, was_in ): the first size minus one ids of the ranking other than the plant, and whether the plant was among the first size
        - real and the plant together fill the shortlist of size
    """
    top = ranking[ :size ]
    return [ i for i in ranking if i != plant_id ][ :size - 1 ], plant_id in top


def plant_answer( routed, plant_id, policy ):
    """
    Read the judge's answer for the plant.

    Requires:
        - routed is the widened route's result

    Ensures:
        - returns { answered, p_overlap, confidence, choice, accepted } with accepted true when p_overlap is at least the policy threshold
        - a plant with no answer, or a malformed one, is answered False with the rest None
    """
    mine = [ a for a in routed[ "sw" ][ "answers" ] if a[ "id" ] == plant_id ]
    if len( mine ) != 1 or vd.malformed_reason( mine[ 0 ][ "probabilities" ], policy ) is not None:
        return { "answered": False, "p_overlap": None, "confidence": None, "choice": None, "accepted": False }
    p, conf, choice = vd.call_facts( mine[ 0 ][ "probabilities" ] )
    return { "answered": True, "p_overlap": round( p, 6 ), "confidence": round( conf, 6 ), "choice": choice, "accepted": p >= policy[ "threshold" ] }


def judge_row( row, ctx, stage, prepared, entries_of, policy=vd.POLICY, route=rt._route, widen=rt._widened_route ):
    """
    Ask the judge about one missed plant placed in the shortlist.

    Requires:
        - stage is a planted candidate stage holding the row's plant; prepared is the planted pool's ( flags, entries, sha, gen )
        - entries_of( entries, language ) keeps the entries of one language

    Ensures:
        - the real shortlist is the stage's own answer for the need, the seed left out, in the need's language
        - the 127 best of it are asked in the usual packs, and the plant in a pack of its own
        - returns the row's id, label and language with plant_answer's figures and was_in_shortlist
        - a plant the stage already had in its first 128 was asked in the real run, so it is returned as was_in_shortlist true and nothing is asked
    """
    flags, entries, sha_, gen = prepared
    need     = stage3.need_for( row[ "pair" ], row[ "need" ] )
    language = need[ "write_lang" ]
    routes, _source = rt.known_routes_of( gen )
    sent, ranking, _redactions = reuse_redact.redact_need( need[ "need" ].strip(), routes )
    got      = stage.shortlist( ranking, entries, sha_, ctx.pages, exclude_id=need[ "seed" ], index_manifest=None )
    every    = entries_of( entries, language )
    known    = { e[ "id" ] for e in every }
    order    = [ i for i in got[ "ranking" ] if i in known ]
    real, was_in = forced_ids( order, row[ "id" ] )
    head     = { "id": row[ "id" ], "label": row[ "label" ], "lang": row[ "lang" ], "was_in_shortlist": was_in }
    if was_in: return { **head, "answered": None, "p_overlap": None, "confidence": None, "choice": None, "accepted": None }
    pool     = [ e for e in every if e[ "id" ] != need[ "seed" ] ]
    first    = route( ctx, sent, pool, flags, policy=policy, candidate_ids=real )
    routed   = widen( ctx, first, sent, pool, flags, [ row[ "id" ] ], policy=policy )
    return { **head, **plant_answer( routed, row[ "id" ], policy ) }


def summarize( results ):
    """
    Count the judge's accepts by the pairs' human label.

    Ensures:
        - returns { label: { pairs, already_in, answered, accepted } } sorted by label
        - a pair the real shortlist already held counts as already_in and is neither answered nor accepted
    """
    out = { }
    for r in results:
        g = out.setdefault( r[ "label" ], { "pairs": 0, "already_in": 0, "answered": 0, "accepted": 0 } )
        g[ "pairs" ] += 1
        if r[ "was_in_shortlist" ]:
            g[ "already_in" ] += 1
            continue
        g[ "answered" ] += bool( r[ "answered" ] )
        g[ "accepted" ] += bool( r[ "accepted" ] )
    return dict( sorted( out.items() ) )


def plan_of( rows, undrafted, budget ):
    """
    Describe what a live run would do.

    Ensures:
        - returns { pairs, by_label, undrafted, requests_needed, stage_budget }
        - requests_needed is REQUESTS_PER for each pair, counted against the cap as one call each
    """
    by_label = { }
    for r in rows: by_label[ r[ "label" ] ] = by_label.get( r[ "label" ], 0 ) + 1
    return { "pairs": len( rows ), "by_label": dict( sorted( by_label.items() ) ), "undrafted": undrafted, "requests_needed": REQUESTS_PER * len( rows ), "stage_budget": budget }


def run_live( run_dir, rows, judge, limit, budget ):
    """
    Judge each row under the call cap and write the report.

    Requires:
        - judge( row ) asks the judge about one row and returns its result

    Ensures:
        - the cap reads its count from call-ledger.jsonl in run_dir and gives the stage STAGE_NAME budget calls
        - returns { used, limit, by_stage, status, detail, summary, results } and writes it as forced-judge-report.json
        - status is done, budget_reached, cap_reached or failed; a NeedsetError ends the run with a report and no exception
        - any other error writes the report with the finished rows and status failed first, then is raised
    """
    cap     = call_cap.CallCap( f"{run_dir}/{first_thousand.CALLS_FILE}", limit, { STAGE_NAME: budget } )
    results = [ ]
    status, detail, raised = DONE, None, None

    def write():
        """Ensures: writes the report as it stands and returns it."""
        out = { "used": cap.used(), "limit": limit, "by_stage": cap.by_stage(), "status": status, "detail": detail, "summary": summarize( results ), "results": results }
        pathlib.Path( f"{run_dir}/{REPORT_FILE}" ).write_text( json.dumps( out, sort_keys=True, indent=4 ) + "\n", encoding="utf-8" )
        return out

    with cap.installed():
        try:
            with call_cap.stage( STAGE_NAME ):
                for row in rows: results.append( judge( row ) )
        except er.NeedsetError as error:
            status = CAP if error.code == er.CALL_CAP_REACHED else BUDGET_HIT if error.code == er.STAGE_BUDGET_REACHED else FAILED
            detail = str( error )
        except BaseException as error:
            status, detail, raised = FAILED, f"{type( error ).__name__}: {error}", error
    out = write()
    if raised is not None: raise raised
    return out


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the source tree, this run's folder, the earlier run's folder, the planted file, the answer key, the labels folder, the control report, the seed and the source commit are required
        - live is false unless --live is given, and a live run also needs --run-name, a fresh spend-ledger run name
        - the stage budget is 100 calls and the run's cap equal to it unless named; the token ceiling is 8,000,000 unless named
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "from_run", "planted", "answer_key", "labels_dir", "control_report", "seed", "source_commit" ):
        ap.add_argument( "--" + name.replace( "_", "-" ), required=True, type=int if name == "seed" else str )
    ap.add_argument( "--limit", type=int, default=BUDGET )
    ap.add_argument( "--budget", type=int, default=BUDGET )
    ap.add_argument( "--ceiling", type=int, default=8_000_000 )
    ap.add_argument( "--run-name", default=None )
    ap.add_argument( "--cli-path", default=None )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--live", action="store_true" )
    return ap.parse_args( argv )


def collect_rows( args, root, deps ):
    """
    Read the missed pairs, their frozen drafts and their labels from files.

    Ensures:
        - returns ( pairs, rows, undrafted ) and has built no reuse context
        - the labels are the first rater's, then the second's, with the third rater for a disagreement
    """
    pairs  = positive_control.load_pairs( args.planted, deps[ "planted_sha" ] if "planted_sha" in deps else positive_control.PLANTED_SHA )
    key    = json.loads( pathlib.Path( args.answer_key ).read_text( encoding="utf-8" ) )[ "items" ]
    read   = first_thousand.read_latest_labels
    first  = read( [ f"{args.labels_dir}/labels-rick.jsonl", f"{args.labels_dir}/labels-rick-redo.jsonl" ] )
    second = read( [ f"{args.labels_dir}/labels-reviewer-2.jsonl" ] )
    third  = read( [ f"{args.labels_dir}/labels-jason.jsonl" ] )
    ledger = draft.make_ledger( f"{args.run_dir}/ledger-control-draft.jsonl", args.cli_path, args.server )
    needs  = frozen_needs( pairs, ledger, lambda rec: strip.strip_member( rec, root ) )
    rows, undrafted = build_rows( pairs, set( missed_ids( args.control_report ) ), needs, pair_labels( pairs, key, first, second, third ) )
    return pairs, rows, undrafted


def main( argv=None, deps=None ):
    """
    Plan the forced judge from files, or with --live run it.

    Requires:
        - deps is None for the real parts, or a mapping that replaces any of: source_root, rows, context, stage, judge, close_run, planted_sha
        - a run needs --cli-path, and the earlier run's folder must hold the saved control ledger and run-env.sh

    Ensures:
        - without --live returns { live False, plan } and has contacted no model, no search and no spend ledger, and built no context
        - with --live the settings of the earlier run's run-env.sh are used with --run-name and --ceiling in place of its run name and ceiling
        - with --live the judge is asked through the real transport, counted under the forced_judge stage, and the report is returned and written
        - with --live the spend-ledger run is closed when the judging ends, however it ends
        - the earlier run's folder is only read

    Raises:
        - NeedsetError NO_CLI_PATH without --cli-path; BAD_NEED on a live run without --run-name; SAVED_FILE_MISSING or ENV_FILE_INCOMPLETE before any context is built
        - whatever the source tree, the context and the stage raise
    """
    args = parse_args( argv )
    deps = { } if deps is None else deps
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledgers are bound to the Claude Code binary's version, so even a plan needs --cli-path" )
    if args.live and not args.run_name: raise er.NeedsetError( er.BAD_NEED, "a live run needs --run-name, a spend-ledger run name that was not used before" )
    model_transport.configure( cli_path=args.cli_path )
    pathlib.Path( args.run_dir ).mkdir( parents=True, exist_ok=True )
    yield_trace.copy_saved( args.from_run, args.run_dir, EXTRA_FILES )
    made, repo = "source_root" not in deps, args.root
    root       = deps[ "source_root" ]( args ) if not made else source_at.ensure_worktree( repo, args.source_commit )
    try:
        return _run( args, root, deps )
    finally:
        if made: source_at.unlock( repo, root )


def _run( args, root, deps ):
    """
    Read the rows and plan, and with --live set up the context and judge them.

    Ensures:
        - returns { live False, plan } for a plan, and _live's result for a live run
        - a live run closes the spend-ledger run when an error ends it, and an error from that close never replaces the first error
    """
    pairs, rows, undrafted = deps[ "rows" ]( args, root ) if "rows" in deps else collect_rows( args, root, deps )
    plan = { **plan_of( rows, undrafted, args.budget ), "control_report": str( args.control_report ) }
    if not args.live: return { "live": False, "plan": plan }
    os.environ.update( { **expansion_run.read_env_file( f"{args.run_dir}/run-env.sh" ), rt.RUN_NAME_VARIABLE: args.run_name, rt.CEILING_VARIABLE: str( args.ceiling ) } )
    ctx   = ( deps[ "context" ] if "context" in deps else rt.context_from_environment )( root )
    close = deps[ "close_run" ] if "close_run" in deps else rt.close_run
    try:
        return _live( args, ctx, pairs, rows, plan, deps, close )
    except BaseException:
        try: close( ctx )
        except Exception as error: print( f"close_run failed while another error was raised: {error!r}" )
        raise


def _live( args, ctx, pairs, rows, plan, deps, close ):
    """
    Judge the rows and close the spend-ledger run.

    Ensures:
        - returns { live True, plan, report, closed_run, close_error }
        - the planted stage holds every pair's plant, so each pair's plant is found in the pool it is judged in
    """
    if "judge" in deps: judge = deps[ "judge" ]( ctx )
    else:
        entries  = [ planted_pool.planted_entry( p[ "rewrite" ] ) for p in pairs ]
        build    = deps[ "stage" ] if "stage" in deps else first_thousand.planted_stage_for
        stage    = build( ctx.candidate_stage, entries, f"{args.run_dir}/{CACHE_DIR}" )
        flags, pool, sha_, gen = rt.prepare( ctx )
        kept, _dropped = rt.sendable_report( entries )
        ids      = ",".join( sorted( e[ "id" ] for e in entries ) )
        prepared = ( flags, [ *pool, *kept ], hashlib.sha256( f"{sha_}|planted|{ids}".encode( "utf-8" ) ).hexdigest()[ :32 ], gen )
        at       = copy.copy( ctx )
        at.candidate_stage = stage
        judge    = lambda row: judge_row( row, at, stage, prepared, rt.in_language, ctx.policy if ctx.policy is not None else vd.POLICY )
    report = run_live( args.run_dir, rows, judge, args.limit, args.budget )
    try:
        closed, close_error = close( ctx ), None
    except Exception as error:
        closed, close_error = None, repr( error )
    return { "live": True, "plan": plan, "report": report, "closed_run": closed, "close_error": close_error }


exit_status = expansion_run.exit_status


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
