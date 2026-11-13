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
from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex import verdict as vd
from lupin_mcp import reuse_flip as rf
from lupin_mcp import reuse_pack as rp
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
DONE         = call_cap.DONE
CAP          = call_cap.CAP_HIT
BUDGET_HIT   = call_cap.BUDGET_HIT
FAILED       = call_cap.FAILED
ALONE        = "alone"             # the plant is asked in a pack of its own, after the 127 real places
IN_PACK      = "in_pack"           # the plant is asked inside the 128 places, in the packs the real run would cut
VARIANTS     = ( ALONE, IN_PACK )
IN_PACK_REQUESTS_PER = 3           # 128 places are packs of up to 50: 50, 50 and 28
ARM_BASELINE = "baseline"          # the plant as id and signature, the unchanged template (the names are judge_probe's; that module imports this one)
ARM_PLANT_LINE = "plant_line"      # the plant carries its purpose line, as the index gives a real entry its line
IN_PACK_ARMS = ( ARM_BASELINE, ARM_PLANT_LINE )
IN_PACK_REPEATS = ( 1, 2 )
ARM_STRIDE   = 100                 # run indexes: arm n, repeat r is n * 100 + r, so no two cells share a cache key
IN_PACK_BUDGET = 192               # 16 pairs, 2 arms, 2 repeats and 3 packs


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
    out      = { }
    model_id = draft.drafter_model()      # read once, so every saved answer is looked up under one model
    for p in pairs:
        try:
            rec = draft.draft_need( first_thousand.control_job( p, strip_fn ), yield_trace.saved_ask, ledger, model_id=model_id, max_tries=first_thousand.CONTROL_TRIES )
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


def places_for( row, ctx, stage, prepared, entries_of ):
    """
    Choose the real places that stand beside one row's plant.

    Requires:
        - stage is a planted candidate stage holding the row's plant; prepared is the planted pool's ( flags, entries, sha, gen )
        - entries_of( entries, language ) keeps the entries of one language

    Ensures:
        - returns ( sent, flags, pool, real, head ): the redacted need, the flags, the language's entries without the seed, forced_ids' real places, and the row's id, label, language and was_in_shortlist
        - the real places are the stage's own answer for the need, the seed left out, in the need's language
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
    return sent, flags, [ e for e in every if e[ "id" ] != need[ "seed" ] ], real, head


def judge_row( row, ctx, stage, prepared, entries_of, policy=vd.POLICY, route=rt._route, widen=rt._widened_route ):
    """
    Ask the judge about one missed plant placed in the shortlist.

    Requires:
        - stage is a planted candidate stage holding the row's plant; prepared is the planted pool's ( flags, entries, sha, gen )
        - entries_of( entries, language ) keeps the entries of one language

    Ensures:
        - the real shortlist is the one places_for chooses
        - the 127 best of it are asked in the usual packs, and the plant in a pack of its own
        - returns the row's id, label and language with plant_answer's figures and was_in_shortlist
        - a plant the stage already had in its first 128 was asked in the real run, so it is returned as was_in_shortlist true and nothing is asked
    """
    sent, flags, pool, real, head = places_for( row, ctx, stage, prepared, entries_of )
    if head[ "was_in_shortlist" ]: return { **head, "answered": None, "p_overlap": None, "confidence": None, "choice": None, "accepted": None }
    first    = route( ctx, sent, pool, flags, policy=policy, candidate_ids=real )
    routed   = widen( ctx, first, sent, pool, flags, [ row[ "id" ] ], policy=policy )
    return { **head, **plant_answer( routed, row[ "id" ], policy ) }


def pack_place( asked_ids, plant_id, size ):
    """
    Say where the plant sits among the places the judge is asked about.

    Requires:
        - asked_ids are the ids of every place in the question; size is the most entries in one pack

    Ensures:
        - returns { pack_index, pack_position, position, asked } counted from 0 over the ids sorted as the sweep sorts them, which is by id
        - the plant's place comes from its id, so it is a record of where it fell and not a claim of random placement
    """
    order    = sorted( asked_ids )
    position = order.index( plant_id )
    return { "pack_index": position // size, "pack_position": position % size, "position": position, "asked": len( order ) }


def in_pack_figures( routed, plant_id, policy ):
    """
    Read the judge's answer for the plant among the real places, and its standing.

    Requires:
        - routed is the result of one route over the real places and the plant

    Ensures:
        - returns { survives, rank, wrong_at_threshold }
        - survives is true when the plant is in the shortlist the verdict itself cut to policy["shortlist"], read from routed["d"] and not worked out again
        - rank counts from 1 over the answered places in the verdict's own order, p_overlap descending then id; None for a plant with no valid answer
        - wrong_at_threshold counts the other places with a valid answer at or above the policy threshold
    """
    rows = [ ]
    for a in routed[ "sw" ][ "answers" ]:
        if vd.malformed_reason( a[ "probabilities" ], policy ) is not None: continue
        p, _conf, _choice = vd.call_facts( a[ "probabilities" ] )
        rows.append( { "id": a[ "id" ], "p_overlap": round( p, 6 ) } )
    ids = [ r[ "id" ] for r in vd._order( rows ) ]
    return { "survives": plant_id in [ r[ "id" ] for r in routed[ "d" ][ "shortlist" ] ],
             "rank": ids.index( plant_id ) + 1 if plant_id in ids else None,
             "wrong_at_threshold": sum( 1 for r in rows if r[ "id" ] != plant_id and r[ "p_overlap" ] >= policy[ "threshold" ] ) }


def with_plant_line( pool, row ):
    """
    Give the row's plant its purpose line in the pool.

    Requires:
        - pool holds the plant, with a pin; row has plant_line

    Ensures:
        - returns a new list in which the plant is a copy carrying the line as `purpose`, as attach_purposes gives a real entry its line; every other entry is the same object
    """
    return [ sx_build.attach_purposes( [ e ], { e[ "pin" ]: row[ "plant_line" ] } )[ 0 ] if e[ "id" ] == row[ "id" ] else e for e in pool ]


def judge_row_in_pack( row, ctx, stage, prepared, entries_of, policy=vd.POLICY, route=rt._route, arm=ARM_BASELINE, template=None ):
    """
    Ask the judge about one plant placed among the 127 real places, in one question.

    Requires:
        - stage is a planted candidate stage holding the row's plant; prepared is the planted pool's ( flags, entries, sha, gen )
        - entries_of( entries, language ) keeps the entries of one language

    Ensures:
        - the real places are the ones places_for chooses, as judge_row takes them
        - the 127 best of them and the plant are asked in a single route call, so the plant is never asked alone and nothing is widened
        - a plant the real shortlist already held is asked all the same, and was_in_shortlist says so
        - the plant_line arm asks the plant with its purpose line; the baseline arm asks it as the control built it
        - template is the pack template the question is asked with; None is the production template
        - returns the row's id, label and language, was_in_shortlist, the arm, plant_answer's figures, in_pack_figures' figures and pack_place's place
    """
    sent, flags, pool, real, head = places_for( row, ctx, stage, prepared, entries_of )
    if arm == ARM_PLANT_LINE: pool = with_plant_line( pool, row )
    asked    = real + [ row[ "id" ] ]
    routed   = route( ctx, sent, pool, flags, template=template, policy=policy, candidate_ids=asked )
    return { **head, "arm": arm, **plant_answer( routed, row[ "id" ], policy ), **in_pack_figures( routed, row[ "id" ], policy ), **pack_place( asked, row[ "id" ], ctx.pack_size ) }


def in_pack_run_index( arm, repeat ):
    """
    Number one arm's repeat, so its answers are cached under a key of its own.

    Requires:
        - arm is one of IN_PACK_ARMS; repeat is a whole number from 1 to ARM_STRIDE minus 1

    Ensures:
        - returns the arm's position times ARM_STRIDE plus the repeat, a run index of 1 or more that no other arm and repeat share
    """
    return IN_PACK_ARMS.index( arm ) * ARM_STRIDE + repeat


def judge_job( job, ctx, stage, prepared, entries_of, policy=vd.POLICY, route=rt._route, sweeper_for=rf.replay_sweeper ):
    """
    Ask one arm and repeat of an in_pack question, posting its packs fresh.

    Requires:
        - job is one of expand_jobs' jobs; ctx has a pack_size

    Ensures:
        - the question is swept with sweeper_for( pack_size, workers, run index, shape ) under the whole shape, so its answers are keyed by arm and repeat
        - the key holds the arm and repeat, so the cell never reads another cell's or the production answers, and its packs are posted
        - the template ends with the cell's run index, as judge_probe.repeat_template makes it, so no two cells post the same body
        - the argument ctx is not changed
        - returns judge_row_in_pack's result with the repeat added
    """
    from lupin_mcp.reuse_needset import judge_probe                            # imported here: it imports this module
    index      = in_pack_run_index( job[ "arm" ], job[ "repeat" ] )
    at         = copy.copy( ctx )
    at.sweeper = sweeper_for( ctx.pack_size, rp.WORKERS_DEFAULT, index, shape=rp.SHAPE_WHOLE )
    return { **judge_row_in_pack( job, at, stage, prepared, entries_of, policy, route, job[ "arm" ], judge_probe.repeat_template( rt.PROMPT_TEMPLATE, index ) ), "repeat": job[ "repeat" ] }


def summarize_in_pack( results ):
    """
    Count the accepts and the plants that survive the cap, by arm, repeat and label.

    Ensures:
        - returns { "arm/repeat": { label: { pairs, answered, accepted, survived } } }, each level sorted
        - the cells are never pooled: an arm's repeats stay apart, as do the arms
        - every pair was asked, so there is no already_in count; survived counts the plants in the verdict's cut shortlist
    """
    out = { }
    for r in results:
        g = out.setdefault( f"{r[ 'arm' ]}/{r[ 'repeat' ]}", { } ).setdefault( r[ "label" ], { "pairs": 0, "answered": 0, "accepted": 0, "survived": 0 } )
        g[ "pairs" ]    += 1
        g[ "answered" ] += bool( r[ "answered" ] )
        g[ "accepted" ] += bool( r[ "accepted" ] )
        g[ "survived" ] += bool( r[ "survives" ] )
    return { cell: dict( sorted( labels.items() ) ) for cell, labels in sorted( out.items() ) }


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


def expand_jobs( rows, arms=IN_PACK_ARMS, repeats=IN_PACK_REPEATS ):
    """
    List the questions an in_pack run asks: one for each pair, arm and repeat.

    Requires:
        - rows are build_rows' rows, each with plant_line (the plant's purpose line, or None)

    Ensures:
        - returns ( jobs, skipped ): a job is its row with arm and repeat added, in the order pair, arm, repeat, so a stopped run leaves whole pairs
        - skipped lists { pair, arm, reason } for each plant_line arm of a pair with no purpose line; it has no job
    """
    jobs, skipped = [ ], [ ]
    for row in rows:
        for arm in arms:
            if arm == ARM_PLANT_LINE and row[ "plant_line" ] is None:
                skipped.append( { "pair": row[ "id" ], "arm": arm, "reason": "plant_has_no_line" } )
                continue
            jobs += [ { **row, "arm": arm, "repeat": n } for n in repeats ]
    return jobs, skipped


def plan_of( rows, undrafted, budget, variant=ALONE, jobs=None ):
    """
    Describe what a live run would do.

    Ensures:
        - returns { pairs, by_label, undrafted, requests_needed, stage_budget, variant }
        - requests_needed is REQUESTS_PER for each pair, or IN_PACK_REQUESTS_PER for each job of the in_pack variant, counted against the cap as one call each
        - jobs, when given, are expand_jobs' jobs, and the in_pack count is over them in place of the pairs
    """
    by_label = { }
    for r in rows: by_label[ r[ "label" ] ] = by_label.get( r[ "label" ], 0 ) + 1
    return { "pairs": len( rows ), "by_label": dict( sorted( by_label.items() ) ), "undrafted": undrafted, "requests_needed": ( REQUESTS_PER * len( rows ) if variant == ALONE else IN_PACK_REQUESTS_PER * len( rows if jobs is None else jobs ) ), "stage_budget": budget, "variant": variant }


def run_live( run_dir, rows, judge, limit, budget, summary=summarize ):
    """
    Judge each row under the call cap and write the report.

    Requires:
        - judge( row ) asks the judge about one row and returns its result; summary( results ) counts the results for the report

    Ensures:
        - the cap reads its count from call-ledger.jsonl in run_dir and gives the stage STAGE_NAME budget calls
        - returns { used, limit, by_stage, status, detail, summary, results } and writes it as forced-judge-report.json
        - status is done, budget_reached, cap_reached or failed; a NeedsetError ends the run with a report and no exception
        - any other error writes the report with the finished rows and status failed first, then is raised
    """
    def work( results ):
        """Ensures: appends the judge's result for each row."""
        for row in rows: results.append( judge( row ) )

    return call_cap.run_under_cap( f"{run_dir}/{first_thousand.CALLS_FILE}", f"{run_dir}/{REPORT_FILE}", limit, STAGE_NAME, budget, work, lambda results, _cap: summary( results ) )


def parse_args( argv ):
    """
    Read the command line.

    Ensures:
        - the source tree, this run's folder, the earlier run's folder, the planted file, the answer key, the labels folder, the control report, the seed and the source commit are required
        - live is false unless --live is given, and a live run also needs --run-name, a fresh spend-ledger run name
        - the variant is alone unless --variant in_pack is given
        - the stage budget is 100 calls and the run's cap equal to it unless named, 192 for the in_pack variant; the token ceiling is 8,000,000 unless named
    """
    ap = argparse.ArgumentParser( description=__doc__ )
    for name in ( "root", "run_dir", "from_run", "planted", "answer_key", "labels_dir", "control_report", "seed", "source_commit" ):
        ap.add_argument( "--" + name.replace( "_", "-" ), required=True, type=int if name == "seed" else str )
    ap.add_argument( "--limit", type=int, default=None )
    ap.add_argument( "--budget", type=int, default=None )
    ap.add_argument( "--ceiling", type=int, default=8_000_000 )
    ap.add_argument( "--run-name", default=None )
    ap.add_argument( "--cli-path", default=None )
    ap.add_argument( "--server", default="max-plan" )
    ap.add_argument( "--live", action="store_true" )
    ap.add_argument( "--variant", choices=VARIANTS, default=ALONE )
    args = ap.parse_args( argv )
    fallback = IN_PACK_BUDGET if args.variant == IN_PACK else BUDGET
    args.limit, args.budget = fallback if args.limit is None else args.limit, fallback if args.budget is None else args.budget
    return args


def plant_lines( control_report ):
    """Ensures: returns { plant id: purpose line } for the control rows that have one."""
    report = json.loads( pathlib.Path( control_report ).read_text( encoding="utf-8" ) )[ "stages" ][ "control" ][ "report" ]
    return { r[ "rewrite" ]: r[ "purpose_line" ] for r in report[ "rows" ] if "purpose_line" in r and r[ "purpose_line" ] }


def load_pairs_needs_labels( args, root, deps, copy_saved=False ):
    """
    Load the planted pairs, their frozen needs and their labels from files.

    Requires:
        - args holds planted, answer_key, labels_dir, run_dir, from_run, cli_path and server

    Ensures:
        - returns ( pairs, needs, labels ), the labels being the first rater's, then the second's, with the third rater for a disagreement
        - with copy_saved the saved draft ledger is copied from --from-run first, an existing file in the run folder kept, so the pairs are not read from a stub
        - builds no reuse context
    """
    pairs  = positive_control.load_pairs( args.planted, deps[ "planted_sha" ] if "planted_sha" in deps else positive_control.PLANTED_SHA )
    key    = json.loads( pathlib.Path( args.answer_key ).read_text( encoding="utf-8" ) )[ "items" ]
    read   = first_thousand.read_latest_labels
    first  = read( [ f"{args.labels_dir}/labels-rick.jsonl", f"{args.labels_dir}/labels-rick-redo.jsonl" ] )
    second = read( [ f"{args.labels_dir}/labels-reviewer-2.jsonl" ] )
    third  = read( [ f"{args.labels_dir}/labels-jason.jsonl" ] )
    if copy_saved: yield_trace.copy_saved( args.from_run, args.run_dir, ( "ledger-control-draft.jsonl", ) )
    ledger = draft.make_ledger( f"{args.run_dir}/ledger-control-draft.jsonl", args.cli_path, args.server )
    needs  = frozen_needs( pairs, ledger, lambda rec: strip.strip_member( rec, root ) )
    return pairs, needs, pair_labels( pairs, key, first, second, third )


def collect_rows( args, root, deps ):
    """
    Read the missed pairs, their frozen drafts and their labels from files.

    Ensures:
        - returns ( pairs, rows, undrafted ) and has built no reuse context
        - the labels are the first rater's, then the second's, with the third rater for a disagreement
        - the alone variant keeps the pairs retrieval missed; the in_pack variant keeps every pair with a frozen draft, since a plant asked among the real places needs no miss
        - the in_pack rows also carry plant_line, the purpose line the control report holds for the plant, or None
    """
    pairs, needs, labels = load_pairs_needs_labels( args, root, deps )
    missed  = { p[ "rewrite" ][ "id" ] for p in pairs } if args.variant == IN_PACK else set( missed_ids( args.control_report ) )
    rows, undrafted = build_rows( pairs, missed, needs, labels )
    if args.variant == IN_PACK:
        lines  = plant_lines( args.control_report )
        rows   = [ { **r, "plant_line": lines[ r[ "id" ] ] if r[ "id" ] in lines else None } for r in rows ]
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
    jobs, skipped = expand_jobs( rows ) if args.variant == IN_PACK else ( None, None )
    plan = { **plan_of( rows, undrafted, args.budget, args.variant, jobs ), "control_report": str( args.control_report ) }
    if jobs is not None: plan.update( arms=list( IN_PACK_ARMS ), repeats=list( IN_PACK_REPEATS ), jobs=len( jobs ), skipped=skipped )
    if not args.live: return { "live": False, "plan": plan }
    os.environ.update( { **expansion_run.read_env_file( f"{args.run_dir}/run-env.sh" ), rt.RUN_NAME_VARIABLE: args.run_name, rt.CEILING_VARIABLE: str( args.ceiling ) } )
    ctx   = ( deps[ "context" ] if "context" in deps else rt.context_from_environment )( root )
    close = deps[ "close_run" ] if "close_run" in deps else rt.close_run
    try:
        return _live( args, ctx, pairs, rows if jobs is None else jobs, plan, deps, close )
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
        ask      = judge_job if args.variant == IN_PACK else judge_row
        judge    = lambda row: ask( row, at, stage, prepared, rt.in_language, ctx.policy if ctx.policy is not None else vd.POLICY )
    report = run_live( args.run_dir, rows, judge, args.limit, args.budget, summarize_in_pack if args.variant == IN_PACK else summarize )
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
