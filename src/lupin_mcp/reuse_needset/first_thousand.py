"""
The driver for the first 1,000 model calls of Set B, under one shared call cap.

The caller hands in the attribution and yield stages. This module builds the control and the remainder, installs the cap and runs the four.
The control and the remainder take every outside thing as an argument. A test runs them on fakes and a live run names the real ones.
It never builds a packet, takes a person's ruling or writes a label file.
It reads the labels that already exist, for the remainder's groups, and writes none.
"""
import argparse
import asyncio
import copy
import hashlib
import importlib
import json
import pathlib
import types

from cosa.repo.labelling import run_check
from cosa.repo.symindex.candidates import candidate_stage
from cosa.repo.symindex.candidates import vector_store as vs
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, draft, loss_trace, planted_pool, positive_control, stage3, stages, strip
from lupin_mcp.reuse_needset import errors as er

CALLS_FILE   = "call-ledger.jsonl"
QUERY_CACHE  = "query-cache"
REPORT_FILE  = "stage-reports.json"
NONE_CHOICE  = "NONE"
UNSURE_NOTE  = "UNSURE"


def read_latest_labels( paths ):
    """
    Read label files and keep the latest label of each item.

    Requires:
        - paths are label files, one JSON object per line with item_id, choice, note and ts

    Ensures:
        - returns { item id: label } holding for each item the label with the latest ts
        - the files are opened for reading only
    """
    latest = {}
    for path in paths:
        with open( path, encoding="utf-8" ) as f:
            for line in f:
                row = json.loads( line )
                if row[ "item_id" ] not in latest or row[ "ts" ] > latest[ row[ "item_id" ] ][ "ts" ]: latest[ row[ "item_id" ] ] = row
    return latest


def remainder_pairs( pairs, answer_key, first_labels, second_labels ):
    """
    Build the pairs the remainder runs the run-check on, each in its group.

    Requires:
        - pairs come from positive_control.load_pairs; answer_key is the key's items by pair id, each with a and b ( the two definition ids )
        - first_labels and second_labels are read_latest_labels results of the two reviewers

    Ensures:
        - returns { id, group, original, rewrite } for each pair, in file order; original and rewrite are the source texts
        - group is drifted when both reviewers chose none ( not the same job ), else unsure when either note starts with the unsure marker, else other
        - a pair with both holds the drifted group, so the two groups never overlap
        - unsure_flagged is true for every pair either reviewer marked unsure, drifted or not, so the plan's count of flagged pairs can still be made

    Raises:
        - NeedsetError CONTROL_INPUT_CHANGED when a pair has no item in the key or either reviewer lacks a label for it
    """
    by_ids = { frozenset( ( v[ "a" ], v[ "b" ] ) ): k for k, v in answer_key.items() }
    out    = []
    for p in pairs:
        item = by_ids.get( frozenset( ( p[ "rewrite" ][ "id" ], p[ "original" ][ "id" ] ) ) )
        if item is None or item not in first_labels or item not in second_labels: raise er.NeedsetError( er.CONTROL_INPUT_CHANGED, f"pair {p[ 'rewrite' ][ 'id' ]}: no key item or label" )
        a, b  = first_labels[ item ], second_labels[ item ]
        flag  = a[ "note" ].startswith( UNSURE_NOTE ) or b[ "note" ].startswith( UNSURE_NOTE )
        group = stages.DRIFTED if a[ "choice" ] == NONE_CHOICE and b[ "choice" ] == NONE_CHOICE else ( stages.UNSURE if flag else "other" )
        out.append( { "id": item, "group": group, "unsure_flagged": flag,
                      "original": p[ "original" ][ "text" ], "rewrite": p[ "rewrite" ][ "text" ] } )
    return out


async def draft_control_needs( pairs, make_job, ask, ledger, draft_fn ):
    """
    Write each pair's need sentence, in file order, with the real Set B drafter.

    Requires:
        - make_job( pair ) returns the job draft_fn takes; draft_fn( job, ask, ledger ) returns a record with ok and need
        - every model call goes through the installed cap, so these calls count toward the 1,000

    Ensures:
        - returns { rewrite id: sentence } for every pair

    Raises:
        - NeedsetError CONTROL_NEED_UNDRAFTED naming the first pair whose sentence did not pass, so a control never runs with a missing need
        - whatever the drafter raises, including CALL_CAP_REACHED
    """
    needs = {}
    for p in pairs:
        record = draft_fn( make_job( p ), ask, ledger )
        if not record[ "ok" ]: raise er.NeedsetError( er.CONTROL_NEED_UNDRAFTED, f"{p[ 'rewrite' ][ 'id' ]}: {record[ 'reason' ]}" )
        needs[ p[ "rewrite" ][ "id" ] ] = record[ "need" ]
    return needs


def planted_check( need, ctx, planted_stage, planted_entries, prepare=rt.prepare, run_question=rt.run_question ):
    """
    Ask the checker about one need over a pool that holds the planted rewrites.

    Requires:
        - need is a need record ( kind, write_lang, seed, need ); ctx is a reuse context with the candidate stage on
        - planted_stage is a planted_pool.PlantedCandidateStage over the same vector set as ctx's stage
        - planted_entries are planted_pool.planted_entry records

    Ensures:
        - the entries the judge may be asked about are the index's own plus the planted ones, screened as the index's are
        - the context is copied and only the copy's candidate stage is swapped, so the caller's context keeps its own
        - the question is loss_trace.check_need's: the seed left out, the need's write language, nothing stored
        - the index sha names the planted ids, so a receipt of this pool is never taken for one of the real index
    """
    flags, entries, sha, gen = prepare( ctx )
    kept, _dropped = rt.sendable_report( planted_entries )
    ids      = ",".join( sorted( e[ "id" ] for e in planted_entries ) )
    prepared = ( flags, [ *entries, *kept ], hashlib.sha256( f"{sha}|planted|{ids}".encode( "utf-8" ) ).hexdigest()[ :32 ], gen )
    at       = copy.copy( ctx )
    at.candidate_stage = planted_stage
    language = "all" if need[ "kind" ] == "cross_language" else need[ "write_lang" ]
    text     = need[ "need" ].strip()
    return run_question( at, loss_trace.CHECK_TOOL, text, text, exclude_id=need[ "seed" ], prepared=prepared, sweep_only=False, write=False, language=language )


def control_ask( needs, check_fn, asked_ids_fn ):
    """
    Build the control's ask function: the checker's candidate ids for a drafted need.

    Requires:
        - needs maps each rewrite id to its sentence; check_fn( need record, planted pool ) returns the checker's receipt
        - asked_ids_fn( receipt ) returns the ids the candidate stage sent to the judge

    Ensures:
        - returns an async ask( planted pool, pair ) giving that list
        - the need record is stage3.need_for( pair, sentence ), whose seed is the original, so the checker leaves the original out
    """
    async def ask( planted, pair ):
        """Ensures: returns the ids the checker asked about for this pair."""
        return asked_ids_fn( check_fn( stage3.need_for( pair, needs[ pair[ "rewrite" ][ "id" ] ] ), planted ) )
    return ask


def remainder_stage( pairs, seed, run_remainder=stages.run_remainder ):
    """
    Return the zero-argument async function for the remainder stage.

    Requires:
        - pairs come from remainder_pairs; run_remainder( pairs, seed ) is stages.run_remainder or a stand-in

    Ensures:
        - the report is run_remainder's, which says no model is contacted
        - it adds unsure_flagged { total, resolved, of, also_drifted, text } over every pair marked unsure, the drifted ones included
        - run_remainder counts a pair in one group only, so this is the count the plan quotes; text reads like "12 of 20, with 2 also drifted"
        - resolved counts a verdict route of accept or reject, as run_remainder does for its unsure group
    """
    flagged = { p[ "id" ] for p in pairs if p[ "unsure_flagged" ] }
    both    = sum( 1 for p in pairs if p[ "unsure_flagged" ] and p[ "group" ] == stages.DRIFTED )

    async def stage():
        """Ensures: returns the remainder report with the flagged count added."""
        report = run_remainder( pairs, seed )
        rows   = [ r for r in report[ "per_pair" ] if r[ "id" ] in flagged ]
        flag   = { "total": len( rows ), "resolved": sum( 1 for r in rows if r[ "route" ] in ( run_check.ACCEPT, run_check.REJECT ) ), "of": len( pairs ), "also_drifted": both }
        return { **report, "unsure_flagged": { **flag, "text": f"{flag[ 'total' ]} of {flag[ 'of' ]}, with {both} also drifted" } }
    return stage


async def run_first_thousand( run_dir, stage_one, stage_two, control, remainder, limit=call_cap.CALL_LIMIT ):
    """
    Run the four stages under one cap and write their report.

    Requires:
        - run_dir exists; each stage is a zero-argument async function returning a dict

    Ensures:
        - the cap reads its count from call-ledger.jsonl in run_dir, so a resumed run keeps the calls already spent
        - returns stages.run_stages' report, also written as stage-reports.json in run_dir
        - the cap is installed for the whole run and put back when it ends
    """
    cap = call_cap.CallCap( f"{run_dir}/{CALLS_FILE}", limit )
    with cap.installed():
        report = await stages.run_stages( cap, { stages.ATTRIBUTION: stage_one, stages.YIELD: stage_two, stages.CONTROL: control, stages.REMAINDER: remainder } )
    with open( f"{run_dir}/{REPORT_FILE}", "w", encoding="utf-8" ) as f: f.write( json.dumps( report, sort_keys=True, indent=4 ) + "\n" )
    return report


STAGE_MODULE = "lupin_mcp.reuse_needset.stage_one_two"
REQUIRED     = ( "root", "run_dir", "planted", "answer_key", "labels_dir", "seed", "source_commit" )


def control_job( pair, strip_fn ):
    """
    Build the job the Set B drafter takes for one planted pair.

    Requires:
        - pair comes from positive_control.load_pairs; strip_fn( record ) returns { kind, text, forbidden } for the original

    Ensures:
        - the seed is the original and the one key is the rewrite, both as index records with their language
        - the sentence is written from the original's stripped text, and the key is what the leak check keeps out of it
    """
    seed = { **planted_pool.planted_entry( pair[ "original" ] ), "lang": pair[ "original" ][ "lang" ] }
    key  = { **planted_pool.planted_entry( pair[ "rewrite" ] ), "lang": pair[ "rewrite" ][ "lang" ] }
    return { "seed": seed, "keys": [ key ], "stripped": strip_fn( seed ), "write_lang": pair[ "original" ][ "lang" ], "meta": { "control": True } }


def planted_stage_for( live, planted_entries, cache_dir, embed_rows=planted_pool.embed_rows, load_vectors=vs.load_vectors ):
    """
    Build the planted candidate stage from the live one's own settings.

    Requires:
        - live is the context's CandidateStage; planted_entries are planted_pool.planted_entry records
        - cache_dir is a folder inside the run folder, where the query vectors of this run are cached

    Ensures:
        - the vectors are the live set read from disk plus the planted rows embedded now, held in memory
        - the new stage shares the live stage's vector folder, client, arm, K and fusion, and has no refresher
        - its query cache is cache_dir, created here, so nothing of this run is written into the live data folder
    """
    pathlib.Path( cache_dir ).mkdir( parents=True, exist_ok=True )
    base    = load_vectors( live.vectors_dir )
    planted = planted_pool.PlantedVectors( base, [ e[ "id" ] for e in planted_entries ], embed_rows( planted_entries, live.embed_client ) )
    return planted_pool.PlantedCandidateStage( live.vectors_dir, str( cache_dir ), live.embed_client, planted, purposes_path=live.purposes_path, K=live.K, arm=live.arm, fusion=live.fusion )


def control_stage_live( ctx, pairs, ask, ledger, strip_fn, draft_fn, cache_dir, prepare=rt.prepare, check=planted_check, build_stage=candidate_stage.build_stage ):
    """
    Return the live control stage: draft the needs, then plant, ask, remove and prove.

    Requires:
        - ctx is a reuse context with its candidate stage on; ask is the drafter's call; ledger the drafting ledger
        - cache_dir is the run folder's query-cache folder
        - every model call goes through the cap that the runner has installed

    Ensures:
        - the needs are drafted first, one at a time in file order, and a need that does not pass stops the stage by name
        - the pool the control plants into and restores is the index's own sendable entries
        - the checker is planted_check over a planted stage that shares the live stage's folders and client
    """
    async def stage():
        """Ensures: returns the control report."""
        needs   = await draft_control_needs( pairs, lambda p: control_job( p, strip_fn ), ask, ledger, draft_fn )
        entries = [ planted_pool.planted_entry( p[ "rewrite" ] ) for p in pairs ]
        planted = planted_stage_for( ctx.candidate_stage, entries, cache_dir )
        pool    = prepare( ctx )[ 1 ]
        asker   = control_ask( needs, lambda need, _pool: check( need, ctx, planted, entries ), loss_trace.asked_ids )
        return await stage3.control_stage( pool, pairs, asker, build_stage )()
    return stage


def load_stage_factories( module_name=STAGE_MODULE, import_module=importlib.import_module ):
    """
    Load the two stage factories that Pocholo's module supplies, at run time.

    Ensures:
        - returns ( attribution_stage, yield_stage ), each taking an env and returning a zero-argument async function
        - the module is imported only here, so this one needs it only when a live run starts

    Raises:
        - NeedsetError STAGE_NOT_WIRED when the module or either factory is missing
    """
    try:
        module = import_module( module_name )
        return module.attribution_stage, module.yield_stage
    except ( ImportError, AttributeError ) as e:
        raise er.NeedsetError( er.STAGE_NOT_WIRED, f"{module_name} must supply attribution_stage( env ) and yield_stage( env ): {e}" ) from e


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the root, run folder, planted file, answer key, labels folder, seed and source commit are required
        - live is false unless --live is given, and without it main plans and contacts nothing
        - the cap is 1,000 calls unless --limit names another
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in REQUIRED: ap.add_argument( "--" + name.replace( "_", "-" ), required=True, type=int if name == "seed" else str )
    ap.add_argument( "--limit", type=int, default=call_cap.CALL_LIMIT )
    ap.add_argument( "--cli-path", default=None )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--live", action="store_true" )
    return ap.parse_args( argv )


def plan( args, loaded ):
    """
    Describe what a live run would do, from files only.

    Requires:
        - loaded holds pairs ( load_pairs ) and remainder ( remainder_pairs )

    Ensures:
        - returns { limit, used, remaining, pairs, groups, unsure_flagged, ledger } and contacts no model
        - used is what the ledger already holds, so a resumed run shows its starting count
    """
    cap    = call_cap.CallCap( f"{args.run_dir}/{CALLS_FILE}", args.limit )
    groups = {}
    for r in loaded[ "remainder" ]: groups[ r[ "group" ] ] = groups.get( r[ "group" ], 0 ) + 1
    return { "limit": args.limit, "used": cap.used(), "remaining": args.limit - cap.used(), "pairs": len( loaded[ "pairs" ] ), "groups": dict( sorted( groups.items() ) ),
             "unsure_flagged": sum( 1 for r in loaded[ "remainder" ] if r[ "unsure_flagged" ] ), "ledger": cap.path }


def load_inputs( args, expected_sha=positive_control.PLANTED_SHA ):
    """
    Read the 20 pairs and their groups from the proof's files, for reading only.

    Ensures:
        - returns { pairs, remainder }; the planted file is checked against expected_sha, the recorded hash unless a test names another
        - the first reviewer's labels are labels-rick.jsonl then labels-rick-redo.jsonl, the second's labels-reviewer-2.jsonl
    """
    pairs = positive_control.load_pairs( args.planted, expected_sha )
    key   = json.loads( pathlib.Path( args.answer_key ).read_text( encoding="utf-8" ) )[ "items" ]
    one   = read_latest_labels( [ f"{args.labels_dir}/labels-rick.jsonl", f"{args.labels_dir}/labels-rick-redo.jsonl" ] )
    two   = read_latest_labels( [ f"{args.labels_dir}/labels-reviewer-2.jsonl" ] )
    return { "pairs": pairs, "remainder": remainder_pairs( pairs, key, one, two ) }


def main( argv=None, deps=None ):
    """
    Plan the first 1,000 calls, or with --live run them.

    Requires:
        - deps is None for the real parts, or a mapping that replaces any of: planted_sha, context, ask, ledger, draft_fn, strip_fn, factories, control, runner, remainder
        - a live run needs the reuse environment variables the context reads, and the two stage factories of STAGE_MODULE

    Ensures:
        - without --live the plan is printed and returned, and no model, vector server or context is touched
        - with --live the four stages run under one cap in args.run_dir and the report is returned
        - the pairs and their groups are read before anything else, so a bad input stops the run before a call

    Raises:
        - NeedsetError STAGE_NOT_WIRED on a live run when the stage module is absent
        - whatever the inputs raise, including CONTROL_INPUT_CHANGED
    """
    args   = parse_args( argv )
    deps   = {} if deps is None else deps
    loaded = load_inputs( args, deps[ "planted_sha" ] if "planted_sha" in deps else positive_control.PLANTED_SHA )
    shown  = plan( args, loaded )
    if not args.live: return { "live": False, "plan": shown }
    factories = deps[ "factories" ] if "factories" in deps else load_stage_factories()
    ctx       = ( deps[ "context" ] if "context" in deps else rt.context_from_environment )( args.root )
    ask       = deps[ "ask" ] if "ask" in deps else draft.drafter_call()
    ledger    = deps[ "ledger" ]( args ) if "ledger" in deps else draft.make_ledger( f"{args.run_dir}/ledger-control-draft.jsonl", args.cli_path, args.server )
    strip_fn  = deps[ "strip_fn" ] if "strip_fn" in deps else ( lambda rec: strip.strip_member( rec, args.root ) )
    draft_fn  = deps[ "draft_fn" ] if "draft_fn" in deps else draft.draft_need
    env       = types.SimpleNamespace( root=args.root, run_dir=args.run_dir, seed=args.seed, source_commit=args.source_commit, ctx=ctx, ask=ask, draft_ledger=ledger )
    control   = ( deps[ "control" ] if "control" in deps else control_stage_live )( ctx, loaded[ "pairs" ], ask, ledger, strip_fn, draft_fn, f"{args.run_dir}/{QUERY_CACHE}" )
    rem       = remainder_stage( loaded[ "remainder" ], args.seed, **( { "run_remainder": deps[ "remainder" ] } if "remainder" in deps else { } ) )
    runner    = deps[ "runner" ] if "runner" in deps else run_first_thousand
    report    = asyncio.run( runner( args.run_dir, factories[ 0 ]( env ), factories[ 1 ]( env ), control, rem, args.limit ) )
    return { "live": True, "plan": shown, "report": report }


if __name__ == "__main__":  # pragma: no cover  reason: the command line entry; main is tested with stand-ins
    import sys
    print( json.dumps( main(), indent=4, sort_keys=True ) )
    sys.exit( 0 )
