"""
The driver for the first 1,000 model calls of Set B, under one shared call cap.

The caller hands in the attribution and yield stages. This module builds the control and the remainder, installs the cap and runs the four.
The control and the remainder take every outside thing as an argument. A test runs them on fakes and a live run names the real ones.
It never builds a packet, takes a person's ruling or writes a label file.
It reads the labels that already exist, for the remainder's groups, and writes none.
"""
import copy
import hashlib
import json

from cosa.repo.labelling import run_check
from lupin_mcp import reuse_tools as rt
from lupin_mcp.reuse_needset import call_cap, loss_trace, stage3, stages
from lupin_mcp.reuse_needset import errors as er

CALLS_FILE   = "call-ledger.jsonl"
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
        group = stages.DRIFTED if a[ "choice" ] == NONE_CHOICE and b[ "choice" ] == NONE_CHOICE else ( stages.UNSURE if UNSURE_NOTE in a[ "note" ] or UNSURE_NOTE in b[ "note" ] else "other" )
        out.append( { "id": item, "group": group, "unsure_flagged": UNSURE_NOTE in a[ "note" ] or UNSURE_NOTE in b[ "note" ],
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
        - it adds unsure_flagged { total, resolved } over every pair marked unsure, the drifted ones included, because run_remainder counts a pair in one group only
        - resolved counts a verdict route of accept or reject, as run_remainder does for its unsure group
    """
    flagged = { p[ "id" ] for p in pairs if p[ "unsure_flagged" ] }

    async def stage():
        """Ensures: returns the remainder report with the flagged count added."""
        report = run_remainder( pairs, seed )
        rows   = [ r for r in report[ "per_pair" ] if r[ "id" ] in flagged ]
        return { **report, "unsure_flagged": { "total": len( rows ), "resolved": sum( 1 for r in rows if r[ "route" ] in ( run_check.ACCEPT, run_check.REJECT ) ) } }
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
