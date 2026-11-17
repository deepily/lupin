"""
A self-consistency check of the interim judge.

It samples definitions the model judged itself, judges them again on a second slot, and compares the two answers.
Without --go it only prints the sample and the calls the second pass would make, and makes no model call.
With --go it makes up to one call for each sampled definition, plus one more for each reply it has to ask for again.
Those calls count against the model's daily budget, and the run is written to the run history so the budget sees them.

Slot 0 is replayed from the judge ledger with no call.
A sampled definition the ledger cannot replay is left out of the comparison, and the report names it.
The comparison asks whether a definition was flagged both times, and which pairs were flagged both times.

Exit 0 means the plan or the comparison was printed. Exit 3 means it could not be made, with the reason printed.
"""
import argparse
import datetime
import json
import pathlib
import random
import sys

import cosa.utils.util as cu
from cosa.repo import code_health_settings as chs
from cosa.repo.duplicate_check import pipeline
from cosa.repo.duplicate_check.judge import FLAG_VERDICTS
from cosa.repo.duplicate_check.proof import ledger_agreement, proof_cli
from cosa.utils import jsonl_file
from cosa.utils.agreement_stats import mcnemar_exact
from lupin_mcp import duplicate_check_daily as daily
from lupin_mcp import duplicate_check_history as history
from lupin_mcp import duplicate_check_status as dcs
from lupin_mcp.reuse_needset.report_rollup import table

SAMPLE_SIZE   = 30
FIRST_SLOT    = 0
SECOND_SLOT   = 1
MODE          = "self-consistency"          # the mode of the history line this run writes; the daily and baseline readers filter on their own modes and skip it
WORKTREE_NAME = "self-consistency-"         # not the daily check's prefix, so a run beside it never shares its worktree
EXIT_NOT_MADE = 3


def own_lines( folder, model ):
    """
    List the definitions a model judged itself, once each.

    Requires:
        - folder is the daily check's result folder

    Ensures:
        - returns { definition id: its last manifest line } for the lines whose model_id is exactly model and which carry no reused_from_model
        - a missing manifest is an empty answer
    """
    lines = jsonl_file.read_jsonl( pathlib.Path( folder ) / daily.MANIFEST, missing_ok=True )
    return { line[ "id" ]: line for line in lines if line[ "model_id" ] == model and "reused_from_model" not in line }


def draw( ids, size, seed ):
    """
    Draw a seeded sample of ids, the one draw the sampling tools share.

    Requires:
        - size is a whole number of at least 1; seed is any integer

    Ensures:
        - returns the sorted ids of up to size of ids, drawn without replacement from ids in sorted order
        - the same ids, size and seed give the same answer
    """
    ids = sorted( ids )
    return sorted( random.Random( seed ).sample( ids, min( size, len( ids ) ) ) )


def sample_ids( folder, model, size, seed ):
    """
    Draw the definitions to judge again.

    Requires:
        - size is a whole number of at least 1; seed is any integer

    Ensures:
        - returns the sorted ids of up to size of own_lines( folder, model ), drawn without replacement from the ids in sorted order
        - the same folder, model, size and seed give the same answer
    """
    return draw( own_lines( folder, model ), size, seed )


def runs_of( folder, model, ids ):
    """
    Group sampled ids by the result file of the run that judged them.

    Ensures:
        - returns { run file: sorted ids } in run file order
    """
    lines, groups = own_lines( folder, model ), {}
    for i in ids: groups.setdefault( lines[ i ][ "run_file" ], [] ).append( i )
    return { run: sorted( groups[ run ] ) for run in sorted( groups ) }


def flagged_by_definition( rows ):
    """
    Say which definitions a set of verdict rows flags.

    Ensures:
        - returns { definition id: True when any of its rows has a verdict in FLAG_VERDICTS, else False }, for each id that has at least one row
    """
    got = {}
    for r in rows: got[ r[ "id" ] ] = got.get( r[ "id" ], False ) or r[ "verdict" ] in FLAG_VERDICTS
    return got


def flagged_pairs( rows ):
    """Ensures: returns the set of ( definition id, candidate id ) pairs whose row was flagged."""
    return { ( r[ "id" ], r[ "candidate" ] ) for r in rows if r[ "verdict" ] in FLAG_VERDICTS }


def compare( first, second ):
    """
    Compare two passes over the same definitions.

    Requires:
        - first and second are { definition id: flagged } from flagged_by_definition

    Ensures:
        - returns { definitions, both, first_only, second_only, neither, agreement, kappa, mcnemar_p } over the ids both passes hold
        - agreement is the share of definitions flagged by both or by neither, None with no definition
        - kappa is ledger_agreement.kappa of the four counts, None with no definition or when chance agreement is 1
        - mcnemar_p is agreement_stats.mcnemar_exact of the two discordant counts
    """
    ids    = sorted( set( first ) & set( second ) )
    both   = sum( 1 for i in ids if first[ i ] and second[ i ] )
    f_only = sum( 1 for i in ids if first[ i ] and not second[ i ] )
    s_only = sum( 1 for i in ids if second[ i ] and not first[ i ] )
    n      = len( ids )
    neither = n - both - f_only - s_only
    agree  = ( both + neither ) / n if n else None
    kappa  = ledger_agreement.kappa( ( both, f_only, s_only, neither ) ) if n else None
    return { "definitions": n, "both": both, "first_only": f_only, "second_only": s_only, "neither": neither, "agreement": agree, "kappa": kappa, "mcnemar_p": mcnemar_exact( f_only, s_only ) }


def render( model, size, seed, groups, result=None ):
    """
    Print the plan, or the comparison when the second pass ran.

    Requires:
        - groups is runs_of's answer; result is None for a plan, else the live run's answer ( first, second, missing, calls )

    Ensures:
        - returns the text: a title, the sample by run and, for a live run, the definition table, the pair counts, the calls made and the ids left out
        - a plan says that no call was made and how many the second pass may make
        - ratios carry three decimals, and a missing ratio reads n/a
    """
    ids   = [ i for run in groups.values() for i in run ]
    lines = [ f"# Interim judge self-consistency: {model}", "", f"Sample of {len( ids )} definitions (asked for {size}, seed {seed}) the model judged itself, from {len( groups )} run file(s)." , "",
              table( [ "run file", "sampled" ], [ [ run, len( groups[ run ] ) ] for run in groups ] ), "" ]
    if result is None: return "\n".join( lines + [ f"Plan only: no model call was made. The second pass may make up to {len( ids )} calls, and one more for each reply it must ask for again; add --go to run it." ] )
    first, second, missing, calls = result
    cmp   = compare( flagged_by_definition( first ), flagged_by_definition( second ) )
    pairs = ( flagged_pairs( first ), flagged_pairs( second ) )
    ratio = lambda v: "n/a" if v is None else f"{v:.3f}"
    lines += [ table( [ "definitions compared", "flagged both times", "first pass only", "second pass only", "flagged neither time", "agreement", "kappa", "McNemar p" ],
                      [ [ cmp[ "definitions" ], cmp[ "both" ], cmp[ "first_only" ], cmp[ "second_only" ], cmp[ "neither" ], ratio( cmp[ "agreement" ] ), ratio( cmp[ "kappa" ] ), ratio( cmp[ "mcnemar_p" ] ) ] ] ), "",
               f"Flagged pairs: {len( pairs[ 0 ] & pairs[ 1 ] )} both times, {len( pairs[ 0 ] - pairs[ 1 ] )} first pass only, {len( pairs[ 1 ] - pairs[ 0 ] )} second pass only.", f"Model calls made: {calls}." ]
    if missing: lines += [ "", f"Left out, because a pass could not be replayed or judged: {', '.join( sorted( missing ) )}" ]
    return "\n".join( lines )


def rejudge_run( root, doc, ids, parts, cli_path, cap, parallel, first_model=None, second_model=None, second_slot=SECOND_SLOT ):
    """
    Judge a run's sampled definitions on both slots.

    Requires:
        - doc is the run's result document, with the window it judged; ids are definition ids that run judged
        - parts are duplicate_check_daily.live_parts' answer; cap is the most model calls the second pass may make
        - first_model and second_model are model ids, or None for the frozen configuration's own; second_slot is the slot of the second pass

    Ensures:
        - rebuilds the run's window from its start and end commits, and for a baseline run takes every definition of the tree as the baseline did, then checks out its end commit in a worktree of its own, and removes the worktree afterwards, even on an error
        - replays slot 0 from the ledger under first_model with no call allowed, and judges second_slot under second_model with up to cap calls
        - returns ( first rows, second rows, missing ids, calls made ): missing are the sampled ids the window no longer yields as new definitions, or that a pass left unjudged
    """
    window   = { "start": doc[ "window" ][ "start" ], "end": doc[ "window" ][ "end" ] }
    baseline = doc.get( "mode" ) == history.MODE_BASELINE
    listed   = "" if baseline else daily.git( root, "rev-list", "--reverse", "--first-parent", f"{window[ 'start' ]}..{window[ 'end' ]}" )
    window[ "commits" ] = listed.split() if listed else []
    cfg    = parts[ "verify" ]()
    target = pathlib.Path( root ) / daily.source_at.WORKTREES / f"{WORKTREE_NAME}{window[ 'end' ][ :9 ]}"
    tree   = daily.source_at.ensure_worktree( root, window[ "end" ], target )
    count  = daily.Counting( parts[ "backend" ] )
    try:
        fresh  = daily.baseline_definitions( tree, window ) if baseline else daily.new_definitions( tree, root, window )
        wanted = [ d for d in fresh[ "defs" ] if d[ "id" ] in set( ids ) ]
        pool   = daily.pool_without_earlier_versions( tree, fresh[ "defs" ] )
        folder = pathlib.Path( parts[ "data_dir" ] ).joinpath( *daily.FOLDER )
        ledger = proof_cli.daily_ledger( parts[ "data_dir" ], cli_path, parts[ "backend" ], daily.FOLDER )
        wiring = { **proof_cli.base_wiring( folder / daily.VECTORS_DIR, parts[ "structural" ]( tree, cfg ), parallel, parts[ "client" ] ), "backend": count, "ledger": ledger, "redact_tools": True }
        first  = pipeline.judge_all( wanted, [ *fresh[ "defs" ], *pool ], { **cfg, **( { "model_id": first_model } if first_model else {} ) }, wiring, FIRST_SLOT, max_calls=0, skip_breaching=True )
        second = pipeline.judge_all( wanted, [ *fresh[ "defs" ], *pool ], { **cfg, **( { "model_id": second_model } if second_model else {} ) }, wiring, second_slot, max_calls=cap, skip_breaching=True )
    finally:
        daily.release( root, tree )
    unjudged = { u[ "id" ] for u in first[ "unjudged" ] } | { u[ "id" ] for u in second[ "unjudged" ] }
    missing  = ( set( ids ) - { d[ "id" ] for d in wanted } ) | unjudged
    return first[ "verdicts" ], second[ "verdicts" ], sorted( missing ), count.calls


def second_pass( root, folder, model, groups, parts, cli_path, parallel, now, second_model=None, second_slot=SECOND_SLOT ):
    """
    Judge every sampled run's definitions on both slots and record the calls.

    Requires:
        - the caller holds the daily check's run lock
        - second_model is None to judge again with model, or the id of another model; the day's budget and the history line then name second_model, because it makes the calls

    Ensures:
        - judges each run file's sample with rejudge_run, the calls of all of them bounded by the day's calls left
        - appends one history line, mode self-consistency, with the calls made and the model, so the day's budget counts them; the line is written even when a later run file raises, with status failed and the calls made so far
        - returns ( first rows, second rows, missing ids, calls made ), the rows of every run joined

    Raises:
        - duplicate_check_daily.SpendRefused when the model's day budget is spent, before any call
    """
    caller = second_model or model
    left   = daily.calls_left( folder, parts, caller, now )
    total  = [ [], [], [], 0 ]
    status = "failed"
    try:
        for run_file, ids in groups.items():
            doc = json.loads( ( pathlib.Path( folder ) / run_file ).read_text( encoding="utf-8" ) )
            got = rejudge_run( root, doc, ids, parts, cli_path, min( len( ids ), left - total[ 3 ] ), parallel, model, second_model, second_slot )
            for k in range( 3 ): total[ k ] += got[ k ]
            total[ 3 ] += got[ 3 ]
        status = "ok"
    finally:
        history.append_line( folder, history.line_of( { "started_at": now.isoformat(), "trigger": "hand", "status": status, "mode": MODE, "judge_calls": total[ 3 ], "judge_model": caller,
                                                       "elapsed_seconds": ( datetime.datetime.now().astimezone() - now ).total_seconds() }, MODE ) )
    return tuple( total )


def live_run( root, folder, model, groups, parts, cli_path, parallel, now, second_model=None, second_slot=SECOND_SLOT ):
    """
    Run the second pass for every sampled run, inside the daily check's run lock.

    Ensures:
        - returns second_pass's answer
        - makes no call when another run holds the lock

    Raises:
        - RuntimeError when the lock is held; duplicate_check_daily.SpendRefused when the budget is spent
    """
    with daily.run_lock( parts[ "data_dir" ] ) as held:
        got = second_pass( root, folder, model, groups, parts, cli_path, parallel, now, second_model, second_slot ) if held else None
    if got is None: raise RuntimeError( "another run holds the run lock; try again when it ends" )
    return got


def main( argv=None, out=None, config=None, parts=None, now=None, run=None ):
    """
    Print the self-consistency plan, or run it with --go.

    Requires:
        - --model defaults to the `duplicate check judge model` INI key, read through config or the process's own manager
        - --go needs --claude-cli-path, and makes model calls

    Ensures:
        - without --go, prints the plan and returns 0 with no model call and nothing written
        - with --go, prints the comparison and returns 0
        - prints a refusal line with the reason and returns 3 when the model key, the folder, the sample, the lock or the day's budget refuses it
    """
    ap = argparse.ArgumentParser( description="Judge a sample of the interim judge's own rulings again, on a second slot." )
    ap.add_argument( "--model", default=None )
    ap.add_argument( "--size", type=int, default=SAMPLE_SIZE )
    ap.add_argument( "--seed", type=int, default=None, help="default is the date as YYYYMMDD, so each week draws its own sample" )
    ap.add_argument( "--check-dir", default=None )
    ap.add_argument( "--go", action="store_true", help="make the model calls; without it the command only prints the plan" )
    ap.add_argument( "--claude-cli-path", default=None )
    ap.add_argument( "--root", default=None )
    ap.add_argument( "--parallel", type=int, default=proof_cli.DEFAULT_PARALLEL )
    a    = ap.parse_args( argv )
    out  = out if out is not None else sys.stdout
    when = now or datetime.datetime.now().astimezone()
    try:
        if a.go and not a.claude_cli_path: raise ValueError( "--go needs --claude-cli-path" )
        model  = a.model or chs.model_id( chs.JUDGE_MODEL_KEY, config )
        root   = a.root or cu.get_project_root()
        folder = pathlib.Path( a.check_dir ) if a.check_dir else dcs.folder_of( root )
        seed   = a.seed if a.seed is not None else int( when.strftime( "%Y%m%d" ) )
        ids    = sample_ids( folder, model, a.size, seed )
        if not ids: raise ValueError( f"the manifest names no definition that {model} judged itself" )
        groups = runs_of( folder, model, ids )
        result = ( run or live_run )( root, folder, model, groups, parts or daily.live_parts(), a.claude_cli_path, a.parallel, when ) if a.go else None
        text   = render( model, a.size, seed, groups, result )
    except ( OSError, ValueError, RuntimeError, chs.CodeHealthSettingError, daily.SpendRefused ) as e:
        print( f"REFUSING: {type( e ).__name__}: {e}. Nothing was made.", file=out )
        return EXIT_NOT_MADE
    print( text, file=out )
    return 0


if __name__ == "__main__":  # pragma: no cover - thin process entry, main() is tested
    sys.exit( main() )
