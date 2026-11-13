"""
The need-expansion replay, wired to the real model and the real search.

It runs the known-answer needs of the first-thousand run through expansion_replay: 37 attribution, the yield needs, and the control originals.
The needs are rebuilt from the saved answers of that run, so only the expansion calls are new. They run under one call-cap stage with a budget of its own.
The query embeddings go through the run's embedding client, are not counted, and are cached in this run's folder and never in the live one.
Without --live it reads files only: it contacts no model, no embedding server and no search.
It never builds a packet, takes a person's ruling or writes a label file.
"""
import argparse
import asyncio
import json
import os
import pathlib
import re

from cosa.repo.doc_lint import model_transport
from cosa.repo.symindex.candidates import rank_fusion as rf
from cosa.repo.symindex.candidates import resident
from cosa.repo.symindex.candidates import search as cs_search
from cosa.repo.symindex.candidates import vector_store as vs
from cosa.repo.symindex.candidates.errors import CandidateError, STAGE_UNKNOWN
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, draft, first_thousand, planted_pool, positive_control, smoke, source_at, stage_seeds, stages, strip, yield_trace
from lupin_mcp.reuse_needset import errors as er
from lupin_mcp.reuse_needset import expansion_replay as ex
from lupin_mcp.reuse_seeded_miss_e2e import SavedAnswerMissing

EXTRA_FILES = ( "ledger-control-draft.jsonl", "run-env.sh" )
LEDGER_FILE = "ledger-expansion.jsonl"
REPORT_FILE = "expansion-report.json"
CACHE_DIR   = "query-cache"
ENV_LINE    = re.compile( r"export (LUPIN_REUSE_[A-Z_]+)=(\S+)" )
ENV_NEEDED  = ( rt.PACK_SIZE_VARIABLE, rt.CEILING_VARIABLE, rt.RUN_NAME_VARIABLE )
WHOLE_LIST  = 10 ** 9
DONE        = call_cap.DONE
CAP         = call_cap.CAP_HIT
BUDGET      = call_cap.BUDGET_HIT
FAILED      = call_cap.FAILED


def read_env_file( path ):
    """
    Read the exported reuse settings of a run's environment file.

    Requires:
        - path is a run-env.sh whose lines read export, a setting name, an equals sign and a value

    Ensures:
        - returns { name: value } for each such line whose name starts with LUPIN_REUSE_, the last line of a name winning

    Raises:
        - NeedsetError ENV_FILE_INCOMPLETE when the pack size, the token ceiling or the run name is missing
    """
    found = { }
    for line in pathlib.Path( path ).read_text( encoding="utf-8" ).splitlines():
        match = ENV_LINE.fullmatch( line.strip() )
        if match: found[ match.group( 1 ) ] = match.group( 2 )
    missing = [ n for n in ENV_NEEDED if n not in found ]
    if missing: raise er.NeedsetError( er.ENV_FILE_INCOMPLETE, f"{path} does not export {missing}" )
    return found


def need_rows( group, needs ):
    """
    Turn final needs into expansion rows.

    Requires:
        - each need has one key symbol, its seed, which is its known answer

    Ensures:
        - returns { id, group, need, known_id } per need, in order

    Raises:
        - NeedsetError BAD_NEED for a need with more or fewer than one key symbol
    """
    rows = [ ]
    for n in needs:
        if len( n[ "key" ][ "symbols" ] ) != 1: raise er.NeedsetError( er.BAD_NEED, f"{n[ 'id' ]}: a seed-answer need has exactly one key symbol" )
        rows.append( { "id": n[ "id" ], "group": group, "need": n[ "need" ], "known_id": n[ "key" ][ "symbols" ][ 0 ] } )
    return rows


def control_rows( pairs, ask, ledger, strip_fn, id_of ):
    """
    Build the rows of the control originals from the saved control drafts.

    Requires:
        - pairs come from positive_control.load_pairs; ask raises SavedAnswerMissing for an answer not saved
        - id_of( file, name ) gives an original's index id

    Ensures:
        - returns ( rows, undrafted ): a row per pair whose need was drafted, and the ids of the pairs whose need was not
        - the known answer is the original's index id, and the need is the one the control drafted from the original

    Raises:
        - NeedsetError BAD_NEED when an original has no index id
    """
    rows, undrafted = [ ], [ ]
    model_id        = draft.drafter_model()      # read once, so one run's ledger keys name one model
    for p in pairs:
        try:
            rec = draft.draft_need( first_thousand.control_job( p, strip_fn ), ask, ledger, model_id=model_id, max_tries=first_thousand.CONTROL_TRIES )
        except SavedAnswerMissing:
            undrafted.append( p[ "rewrite" ][ "id" ] )
            continue
        if not rec[ "ok" ]:
            undrafted.append( p[ "rewrite" ][ "id" ] )
            continue
        known = id_of( p[ "original" ][ "file" ], p[ "original" ][ "name" ] )
        if known is None: raise er.NeedsetError( er.BAD_NEED, f"{p[ 'original' ][ 'id' ]}: the original is not in the index" )
        rows.append( { "id": p[ "original" ][ "id" ], "group": "control", "need": rec[ "need" ], "known_id": known } )
    return rows, undrafted


class FullResident( resident.ResidentSearch ):
    """
    A resident search that returns each source's whole list.

    The parent cuts each list to twenty ids, which would hide a rank past twenty.
    """

    def search( self, request ):
        """
        Answer one search with the whole lists.

        Requires:
            - request holds stage_key, need and K, and may hold vectors_dir with query_vectors

        Ensures:
            - returns what search.answer_for_stage returns, with list_sizes added and no list cut

        Raises:
            - CandidateError STAGE_UNKNOWN when no stage is held under stage_key
            - everything search.answer_for_stage raises
        """
        with self._lock: stage = self._stages.get( request[ "stage_key" ] )
        if stage is None: raise CandidateError( STAGE_UNKNOWN, request[ "stage_key" ] )
        if request.get( "vectors_dir" ) is not None: request = dict( request, vectors_dir=self._confined( request[ "vectors_dir" ] ) )
        return resident.trim_lists( cs_search.answer_for_stage( request, stage, self._vectors_for ), head=WHOLE_LIST )


class FullStage( planted_pool.PlantedCandidateStage ):
    """
    The candidate stage answering in this process with whole lists.

    It reads the live vector set and plants nothing.
    """

    def __init__( self, vectors_dir, query_cache_dir, embed_client, base, **kwargs ):
        """Hold a FullResident over the base vectors in place of the planted one."""
        super().__init__( vectors_dir, query_cache_dir, embed_client, base, **kwargs )
        self._resident = FullResident( os.path.realpath( vectors_dir ), load_vectors=lambda _folder: base )


def lists_for( stage, entries, index_sha, pages ):
    """
    Build the function that searches one query text and returns its source lists.

    Requires:
        - stage is a FullStage; entries, index_sha and pages are what rt.prepare gives

    Ensures:
        - the returned function takes a text and returns { source: ranked ids } with every list whole
        - the query vector comes from the stage's cache folder or from its embedding client, and a miss embeds it
    """
    def lists( query ):
        """Ensures: returns the whole ranked list of each source for the query."""
        got = stage.shortlist( query, entries, index_sha, pages, K=ex.SHORTLIST )
        return { name: v[ "head" ] for name, v in got[ "lists" ].items() }
    return lists


def plan_of( rows, undrafted, unsaved, ledger, model_id, budget ):
    """
    Describe what a live run would do.

    Requires:
        - ledger has get( key ); the rows are those replay would take

    Ensures:
        - returns { rows, by_group, undrafted, unsaved, saved_replies, calls_needed, stage_budget, embeddings_needed }
        - calls_needed counts the rows whose expansion reply the ledger does not hold, which is the number of model calls
        - embeddings_needed is five queries per row, none counted against the cap
    """
    by_group = { }
    for r in rows: by_group[ r[ "group" ] ] = by_group.get( r[ "group" ], 0 ) + 1
    saved = sum( 1 for r in rows if ledger.get( ex.expansion_key( r[ "need" ], model_id ) ) is not None )
    return { "rows": len( rows ), "by_group": dict( sorted( by_group.items() ) ), "undrafted": undrafted, "unsaved": unsaved, "saved_replies": saved,
             "calls_needed": len( rows ) - saved, "stage_budget": budget, "embeddings_needed": 5 * len( rows ) }


def run_live( run_dir, rows, ask, ledger, search, fusion, limit, budget, model_id ):
    """
    Run the expansion under the call cap and write the report.

    Requires:
        - ask makes a counted model call, as draft.drafter_call does; search is lists_for's function

    Ensures:
        - the cap reads its count from call-ledger.jsonl in run_dir and gives the stage ex.STAGE_NAME budget calls
        - returns { used, limit, by_stage, status, detail, summary, results } and writes it as expansion-report.json
        - status is done, budget_reached, cap_reached or failed; a NeedsetError ends the run with a report and no exception
        - any other error writes the report with the finished rows and status failed first, then is raised
    """
    def work( results ):
        """Ensures: replays the rows, appending each result."""
        ex.replay( rows, ask, ledger, search, fusion, model_id, into=results )

    return call_cap.run_under_cap( f"{run_dir}/{first_thousand.CALLS_FILE}", f"{run_dir}/{REPORT_FILE}", limit, ex.STAGE_NAME, budget, work, lambda results, _cap: ex.summarize( results ) )


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the source tree, this run's folder, the earlier run's folder, the planted file, the seed and the source commit are required
        - live is false unless --live is given, and without it nothing but files is read
        - the stage budget is ex.BUDGET and the run's cap equal to it unless named
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "from_run", "planted", "seed", "source_commit" ): ap.add_argument( "--" + name.replace( "_", "-" ), required=True, type=int if name == "seed" else str )
    ap.add_argument( "--limit", type=int, default=ex.BUDGET )
    ap.add_argument( "--budget", type=int, default=ex.BUDGET )
    ap.add_argument( "--cli-path", default=None )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--probe-model", default=smoke.SECOND_MODEL )
    ap.add_argument( "--live", action="store_true" )
    return ap.parse_args( argv )


def collect_rows( args, root, ctx, deps ):
    """
    Rebuild every known-answer row from the saved answers.

    Requires:
        - the saved files are already in args.run_dir

    Ensures:
        - returns ( rows, undrafted, unsaved ): the attribution rows, then the yield rows, then the control rows, and the seeds or pairs left out and why
        - nothing is asked of a model: a missing answer lands in unsaved or undrafted
    """
    parts = yield_trace.live_parts( args, root, ctx, deps )
    lists = stage_seeds.load_lists( f"{args.run_dir}/{stage_seeds.LISTS_FILE}" )
    rows, unsaved = [ ], [ ]
    for group in ( stages.ATTRIBUTION, stages.YIELD ):
        needs, missing = asyncio.run( yield_trace.rebuild( lists[ group ][ "order" ], parts[ "make_need" ] ) )
        rows += need_rows( group, needs )
        unsaved += missing
    ledger  = draft.make_ledger( f"{args.run_dir}/ledger-control-draft.jsonl", args.cli_path, args.server )
    pairs   = positive_control.load_pairs( args.planted, deps[ "planted_sha" ] if "planted_sha" in deps else positive_control.PLANTED_SHA )
    by_name = { ( e[ "file" ], e[ "name" ] ): e[ "id" ] for e in rt.prepare( ctx )[ 1 ] }
    control, undrafted = control_rows( pairs, yield_trace.saved_ask, ledger, lambda rec: strip.strip_member( rec, root ), lambda f, n: by_name.get( ( f, n ) ) )
    return rows + control, undrafted, unsaved


def main( argv=None, deps=None ):
    """
    Plan the expansion from files, or with --live run it.

    Requires:
        - deps is None for the real parts, or a mapping that replaces any of: source_root, context, built, build_parts, planted_sha, rows, stage, ask, close_run
        - a run needs --cli-path, and the earlier run's folder must hold its run-env.sh

    Ensures:
        - the reuse settings, the run name among them, are read from the earlier run's run-env.sh and set in this process
        - the context gets a transport that refuses every request, because the expansion makes no Jev request; so no spend-ledger run is begun and the run name is only a label
        - without --live returns { live False, plan } and has contacted no model, no embedding server and no search
        - with --live the expansion replies are asked through the real transport, counted under the expansion stage, and the report is returned and written
        - with --live the spend-ledger run is closed when the replay ends, however it ends
        - the earlier run's folder is only read; this run's folder holds every copy and every new file

    Raises:
        - NeedsetError NO_CLI_PATH without --cli-path; SAVED_FILE_MISSING or ENV_FILE_INCOMPLETE before the context is built
        - whatever the source tree, the context and the parts raise
    """
    args = parse_args( argv )
    deps = { } if deps is None else deps
    if args.cli_path is None: raise er.NeedsetError( er.NO_CLI_PATH, "the ledgers are bound to the Claude Code binary's version, so even a plan needs --cli-path" )
    model_transport.configure( cli_path=args.cli_path )
    pathlib.Path( args.run_dir ).mkdir( parents=True, exist_ok=True )
    yield_trace.copy_saved( args.from_run, args.run_dir, yield_trace.SAVED_FILES + EXTRA_FILES )
    os.environ.update( read_env_file( f"{args.run_dir}/run-env.sh" ) )
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
    Plan the rows, and with --live run them and close the spend-ledger run.

    Ensures:
        - returns { live False, plan } for a plan, and { live True, plan, report, closed_run, close_error } for a live run
        - the drafter's model is read from the INI once, so the plan, the asks and the report name the same model
    """
    yield_trace.hold_transport( ctx )
    rows, undrafted, unsaved = deps[ "rows" ]( args, root, ctx ) if "rows" in deps else collect_rows( args, root, ctx, deps )
    ledger = draft.make_ledger( f"{args.run_dir}/{LEDGER_FILE}", args.cli_path, args.server )
    model  = draft.drafter_model()
    plan   = { **plan_of( rows, undrafted, unsaved, ledger, model, args.budget ), "run_name": os.environ[ rt.RUN_NAME_VARIABLE ] }
    if not args.live: return { "live": False, "plan": plan }
    if "stage" in deps: stage, search = deps[ "stage" ]( ctx )
    else:
        live  = ctx.candidate_stage
        stage = FullStage( live.vectors_dir, f"{args.run_dir}/{CACHE_DIR}", live.embed_client, vs.load_vectors( live.vectors_dir ), purposes_path=live.purposes_path, K=live.K, arm=live.arm, fusion=live.fusion )
        prepared = rt.prepare( ctx )
        search   = lists_for( stage, prepared[ 1 ], prepared[ 2 ], ctx.pages )
    fusion = ( stage.fusion if stage.fusion else { "k": rf.FUSION_K, "depth": rf.FUSION_DEPTH, "head": rf.FUSION_HEAD } )
    ask    = deps[ "ask" ] if "ask" in deps else draft.drafter_call( model )
    report = run_live( args.run_dir, rows, ask, ledger, search, fusion, args.limit, args.budget, model )
    try:
        closed, close_error = close( ctx ), None
    except Exception as error:
        closed, close_error = None, repr( error )
    return { "live": True, "plan": plan, "report": report, "closed_run": closed, "close_error": close_error }


def exit_status( result ):
    """
    Say what the process should exit with for the result main returned.

    Ensures:
        - returns 1 when the run failed or the spend-ledger run could not be closed, 3 when the cap or the stage budget ended it, else 0
        - a plan is 0
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
